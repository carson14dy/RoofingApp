"""
Update engine for Big Sky Hail Watch
====================================
Checks GitHub for a newer ``payload/manifest.json``, downloads that exact
commit, self-tests it against a *copy* of the user's real database, and only
then stages it. Every install backs the database up first. A version that fails
its test, fails to start, or is rolled back is skipped until a newer one ships.

Layout inside the user's data folder::

    versions/<version>/   one folder per installed app version (never edited in place)
    backups/              database backups (before each update + daily, newest 14 kept)
    state.json            which version is current / previous / ready, history
    settings.json         update source (repo, branch, token) chosen in the app
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

log = logging.getLogger("hailwatch.updater")


class UpdateError(Exception):
    """A problem the user should read (written in plain words)."""


# --------------------------------------------------------------------------
# Versions and manifests
# --------------------------------------------------------------------------
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(v) -> tuple[int, int, int]:
    m = _VERSION.match(str(v or "").strip())
    if not m:
        raise UpdateError(f"“{v}” isn't a version number — use MAJOR.MINOR.PATCH, like 1.2.0.")
    return tuple(int(x) for x in m.groups())


def read_manifest(payload_dir) -> dict:
    d = Path(payload_dir)
    try:
        data = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UpdateError("The update has no manifest.json.") from None
    except json.JSONDecodeError as e:
        raise UpdateError(f"manifest.json isn't valid JSON ({e.msg}, line {e.lineno}).") from None
    if not isinstance(data, dict):
        raise UpdateError("manifest.json must be a JSON object.")
    parse_version(data.get("version"))
    data.setdefault("min_shell", 1)
    data.setdefault("notes", "")
    data.setdefault("selftest", ["/healthz", "/"])
    if not isinstance(data["min_shell"], int):
        raise UpdateError("min_shell in manifest.json must be a whole number.")
    if not (d / "app.py").is_file():
        raise UpdateError("The update has no app.py.")
    return data


# --------------------------------------------------------------------------
# Loading and testing a payload
# --------------------------------------------------------------------------
_load_counter = itertools.count(1)


def load_payload(payload_dir, tag: str = "live"):
    """Import the payload as a package under a unique name (app.py is the
    package's __init__, sibling .py files are its modules). Two versions can
    live in one process, so a new one can be swapped in without a restart."""
    name = f"hw_payload_{tag}_{next(_load_counter)}"
    spec = importlib.util.spec_from_file_location(
        name, str(Path(payload_dir) / "app.py"), submodule_search_locations=[str(payload_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        unload_payload(name)
        raise
    if not hasattr(module, "create_app"):
        unload_payload(name)
        raise UpdateError("app.py has no create_app(config) function.")
    return module


def unload_payload(name: str) -> None:
    for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        sys.modules.pop(key, None)


def copy_database(src, dst) -> None:
    """Consistent copy of a live SQLite database (safe while the app is open)."""
    source = sqlite3.connect(str(src))
    target = sqlite3.connect(str(dst))
    try:
        with target:
            source.backup(target)
    finally:
        source.close()
        target.close()


def selftest(payload_dir, db_source=None, timeout: float = 90) -> tuple[bool, str | None]:
    """Run a payload against a throwaway copy of the user's database and load
    the pages listed in its manifest. Nothing touches the real data."""
    result: dict = {}

    def run():
        tmp = tempfile.mkdtemp(prefix="hailwatch-selftest-")
        name = None
        try:
            manifest = read_manifest(payload_dir)
            db = os.path.join(tmp, "hailwatch.db")
            if db_source and os.path.exists(db_source):
                copy_database(db_source, db)
            module = load_payload(payload_dir, tag="selftest")
            name = module.__name__
            app = module.create_app({"DATA_DIR": tmp, "DB_PATH": db, "NETWORK": False,
                                     "SHELL": None, "TESTING": True})
            client = app.test_client()
            for path in manifest.get("selftest") or ["/healthz", "/"]:
                resp = client.get(path)
                if resp.status_code >= 400:
                    raise UpdateError(f"Opening {path} returned HTTP {resp.status_code}.")
            result["ok"] = True
        except BaseException as e:  # SyntaxError, ImportError, template errors, …
            result["ok"] = False
            result["error"] = f"{type(e).__name__}: {e}"
        finally:
            if name:
                unload_payload(name)
            shutil.rmtree(tmp, ignore_errors=True)

    worker = threading.Thread(target=run, name="selftest", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return False, f"The self-test didn't finish within {int(timeout)} seconds."
    return bool(result.get("ok")), result.get("error")


def backup_database(db_path, backups_dir, reason: str, keep: int = 14) -> Path | None:
    db_path, backups_dir = Path(db_path), Path(backups_dir)
    if not db_path.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", reason)
    dest = backups_dir / f"hailwatch-{stamp}-{safe}.db"
    n = 1
    while dest.exists():
        n += 1
        dest = backups_dir / f"hailwatch-{stamp}-{safe}-{n}.db"
    copy_database(db_path, dest)
    old = sorted(backups_dir.glob("hailwatch-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in old[keep:]:
        try:
            p.unlink()
        except OSError:
            pass
    log.info("Backed up database to %s", dest)
    return dest


# --------------------------------------------------------------------------
# GitHub as the update channel
# --------------------------------------------------------------------------
class GitHubSource:
    """Three calls: latest commit SHA on the branch, that commit's
    payload/manifest.json, and (only when newer) that commit's zip."""

    MAX_DOWNLOAD = 50 * 1024 * 1024

    def __init__(self, repo, branch="main", token="", api="https://api.github.com",
                 payload_path="payload", user_agent="BigSkyHailWatch", timeout=20):
        self.repo, self.branch, self.token = repo, branch or "main", (token or "").strip()
        self.api, self.payload_path, self.timeout = api.rstrip("/"), payload_path.strip("/"), timeout
        self.http = requests.Session()
        self.http.headers["User-Agent"] = user_agent

    def _headers(self, accept):
        h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _check(self, r, what):
        if r.status_code in (200, 304):
            return
        if r.status_code == 401:
            raise UpdateError("GitHub turned down the access token. Paste a new one under “Update source.”")
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            when = ""
            try:
                when = datetime.fromtimestamp(int(r.headers["X-RateLimit-Reset"])).strftime("%I:%M %p").lstrip("0")
            except (KeyError, ValueError):
                pass
            raise UpdateError("GitHub's hourly limit for update checks is used up"
                              + (f"; it resets at {when}." if when else ".")
                              + " Adding an access token raises the limit.")
        if r.status_code == 404:
            if what == "manifest":
                raise UpdateError(f"{self.repo} has no {self.payload_path}/manifest.json on “{self.branch}”. "
                                  "Push the whole project folder to the repository.")
            raise UpdateError(f"Couldn't find {self.repo} (branch “{self.branch}”) on GitHub. Check the name — "
                              "if the repository is private, add an access token.")
        raise UpdateError(f"GitHub answered the {what} request with HTTP {r.status_code}.")

    def latest_sha(self, etag=None):
        """Return (sha, etag), or (None, etag) when nothing changed since `etag`."""
        h = self._headers("application/vnd.github.sha")
        if etag:
            h["If-None-Match"] = etag
        r = self.http.get(f"{self.api}/repos/{self.repo}/commits/{quote(self.branch, safe='')}",
                          headers=h, timeout=self.timeout)
        if r.status_code == 304:
            return None, etag
        self._check(r, "update check")
        sha = r.text.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise UpdateError("GitHub sent back something that isn't a commit ID.")
        return sha, r.headers.get("ETag")

    def manifest(self, sha) -> dict:
        r = self.http.get(f"{self.api}/repos/{self.repo}/contents/{self.payload_path}/manifest.json",
                          params={"ref": sha}, headers=self._headers("application/vnd.github.raw+json"),
                          timeout=self.timeout)
        self._check(r, "manifest")
        try:
            data = json.loads(r.text)
        except ValueError:
            raise UpdateError("manifest.json on GitHub isn't valid JSON.") from None
        if not isinstance(data, dict):
            raise UpdateError("manifest.json on GitHub must be a JSON object.")
        parse_version(data.get("version"))
        return data

    def download(self, sha, dest: Path) -> Path:
        with self.http.get(f"{self.api}/repos/{self.repo}/zipball/{sha}",
                           headers=self._headers("application/vnd.github+json"),
                           timeout=self.timeout, stream=True) as r:
            self._check(r, "download")
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > self.MAX_DOWNLOAD:
                        raise UpdateError("The update download is over 50 MB, so it was refused.")
                    f.write(chunk)
        return dest


def extract_payload(zip_path, dest: Path, payload_path="payload", max_files=2000) -> None:
    """Extract only the payload folder from a GitHub zipball, refusing anything
    that would land outside `dest` (path traversal) or links."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = os.path.realpath(dest)
    marker = f"{payload_path.strip('/')}/manifest.json"
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        hits = [n for n in names if n == marker or n.endswith("/" + marker)]
        if not hits:
            raise UpdateError(f"The download has no {marker}.")
        prefix = min(hits, key=len)[: -len("manifest.json")]
        count = 0
        for info in z.infolist():
            if not info.filename.startswith(prefix) or info.is_dir():
                continue
            rel = info.filename[len(prefix):]
            if not rel or "__pycache__" in rel.split("/"):
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError(f"The update contains a link ({rel}); refusing it.")
            target = os.path.realpath(os.path.join(root, rel))
            if not target.startswith(root + os.sep):
                raise UpdateError(f"The update tried to write outside its folder ({rel}); refusing it.")
            count += 1
            if count > max_files:
                raise UpdateError("The update has too many files; refusing it.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


# --------------------------------------------------------------------------
# The updater
# --------------------------------------------------------------------------
LABELS = {
    "installed": "Installed",
    "downloaded": "Ready",
    "rejected": "Skipped",
    "failed": "Failed to start",
    "rolled_back": "Rolled back",
    "needs_shell": "Needs installer",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pretty(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%b %d, %I:%M %p").replace(" 0", " ")
    except (TypeError, ValueError):
        return iso or ""


class Updater:
    BUSY = ("checking", "downloading", "validating")

    def __init__(self, data_dir, bundled_dir, shell_api: int, defaults: dict | None = None,
                 user_agent="BigSkyHailWatch"):
        self.data = Path(data_dir)
        self.bundled = Path(bundled_dir)
        self.shell_api = shell_api
        self.user_agent = user_agent
        self.versions = self.data / "versions"
        self.backups = self.data / "backups"
        self.tmp = self.data / "tmp"
        self.state_path = self.data / "state.json"
        self.settings_path = self.data / "settings.json"
        for d in (self.versions, self.backups, self.tmp):
            d.mkdir(parents=True, exist_ok=True)
        self.defaults = {"repo": "", "branch": "main", "token": "", "api": "https://api.github.com",
                         "payload_path": "payload", "check_every_hours": 1, **(defaults or {})}
        self.state = self._load(self.state_path)
        self.state.setdefault("bad", [])
        self.state.setdefault("history", [])
        self.settings = self._load(self.settings_path)
        self._lock = threading.RLock()
        self._busy = False
        last = self.state.get("last_result") or {}
        self.phase = last.get("phase", "idle")
        self.message = last.get("message", "")

    # ---------------- persistence ----------------
    @staticmethod
    def _load(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    @staticmethod
    def _write(path: Path, data: dict):
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _save(self):
        self._write(self.state_path, self.state)

    def event(self, kind, version, detail=""):
        with self._lock:
            self.state["history"].append({"at": _now_iso(), "kind": kind, "version": version, "detail": detail})
            self.state["history"] = self.state["history"][-40:]
            self._save()
        log.info("update event: %s %s %s", kind, version, detail)

    # ---------------- settings ----------------
    def source_settings(self) -> dict:
        return {**self.defaults, **{k: v for k, v in self.settings.items() if v is not None}}

    def configured(self) -> bool:
        return bool(self.source_settings().get("repo"))

    def check_interval_hours(self) -> float:
        try:
            return max(0.25, float(self.source_settings().get("check_every_hours") or 1))
        except (TypeError, ValueError):
            return 1.0

    def source(self) -> GitHubSource:
        s = self.source_settings()
        return GitHubSource(s["repo"], s.get("branch"), s.get("token"), s.get("api"),
                            s.get("payload_path", "payload"), user_agent=self.user_agent)

    def set_source(self, repo, branch="main", token="", clear_token=False) -> dict:
        repo = (repo or "").strip()
        repo = re.sub(r"^(https?://)?(www\.)?github\.com/", "", repo).strip("/")
        repo = re.sub(r"\.git$", "", repo)
        branch = (branch or "").strip() or "main"
        if repo and not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo):
            return {"ok": False, "message": "Use the form owner/repository — for example carson14dy/bigsky-hailwatch."}
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
            return {"ok": False, "message": "That branch name has characters GitHub doesn't allow."}
        with self._lock:
            self.settings["repo"], self.settings["branch"] = repo, branch
            if clear_token:
                self.settings["token"] = ""
            elif token and token.strip():
                self.settings["token"] = token.strip()
            self._write(self.settings_path, self.settings)
            for k in ("etag", "seen_sha", "last_result"):
                self.state.pop(k, None)
            self._save()
            self.phase, self.message = ("idle", "") if repo else ("idle", "Updates are turned off.")
        return {"ok": True, "message": "Saved."}

    # ---------------- installed versions ----------------
    def payload_dir(self, version) -> Path:
        return self.versions / version

    def bundled_version(self) -> str:
        return read_manifest(self.bundled)["version"]

    def _valid(self, version) -> bool:
        if not version:
            return False
        try:
            m = read_manifest(self.payload_dir(version))
        except UpdateError:
            return False
        return m["version"] == version and m["min_shell"] <= self.shell_api

    @staticmethod
    def _content_hash(folder: Path) -> str:
        import hashlib
        h = hashlib.sha256()
        for p in sorted(folder.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc" and p.name != ".content-hash":
                h.update(str(p.relative_to(folder)).encode())
                h.update(p.read_bytes())
        return h.hexdigest()

    def _install_folder(self, src: Path, version: str):
        """Copy the built-in payload into versions/. Re-copies when its content
        changed under the same version number (only happens while developing)."""
        target = self.payload_dir(version)
        digest = self._content_hash(src)
        marker = target / ".content-hash"
        if self._valid(version) and marker.exists() and marker.read_text() == digest:
            return
        partial = self.versions / f".{version}.partial-{os.getpid()}"
        shutil.rmtree(partial, ignore_errors=True)
        shutil.copytree(src, partial, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (partial / ".content-hash").write_text(digest)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(partial, target)

    def prepare_startup(self, db_path) -> str:
        """Decide which version to run at launch. Installs the version built
        into this desktop app if it's newer, and applies a staged update."""
        with self._lock:
            bundled = self.bundled_version()
            self._install_folder(self.bundled, bundled)
            cur = self.state.get("current")
            if not self._valid(cur):
                if cur:
                    self.event("failed", cur, "its files were missing; using the built-in version")
                cur = bundled
            elif parse_version(bundled) > parse_version(cur):
                self.state["previous"] = cur
                cur = bundled
                self.event("installed", bundled, "came with a new desktop installer")
            self.state["current"] = cur
            ready = self.state.get("ready")
            if (ready and self._valid(ready) and ready not in self.state["bad"]
                    and parse_version(ready) > parse_version(cur)):
                backup_database(db_path, self.backups, f"before-{ready}")
                self.state["previous"], self.state["current"] = cur, ready
                self.event("installed", ready, "installed at startup")
                self._settle("up_to_date", f"Running {ready}.")
            self.state["ready"] = None
            self._save()
            return self.state["current"]

    def record_failure(self, version, error) -> str | None:
        """`version` failed to start: skip it and pick the best fallback."""
        with self._lock:
            if version not in self.state["bad"]:
                self.state["bad"].append(version)
            self.event("failed", version, error)
            options = [self.state.get("previous")]
            try:
                options.append(self.bundled_version())
            except UpdateError:
                pass
            installed = sorted((p.name for p in self.versions.iterdir() if not p.name.startswith(".")),
                               key=lambda v: parse_version(v) if _VERSION.match(v) else (0, 0, 0), reverse=True)
            options += installed
            choice = next((v for v in options if v and v != version and v not in self.state["bad"]
                           and self._valid(v)), None)
            self.state["current"], self.state["previous"] = choice, None
            self._save()
            return choice

    def rollback_target(self) -> str | None:
        cur, prev = self.state.get("current"), self.state.get("previous")
        if prev and prev != cur and self._valid(prev):
            return prev
        try:
            b = self.bundled_version()
        except UpdateError:
            return None
        return b if b != cur and self._valid(b) else None

    def rollback(self) -> tuple[str | None, str | None]:
        """Go back one version. Returns (new_current, skipped_version)."""
        with self._lock:
            cur, target = self.state.get("current"), self.rollback_target()
            if not target:
                return None, None
            if cur and cur not in self.state["bad"]:
                self.state["bad"].append(cur)
            self.state["current"], self.state["previous"] = target, None
            self.event("rolled_back", target, f"from {cur}; {cur} will be skipped until a newer version ships")
            self._settle("up_to_date", f"Rolled back to {target}. {cur} will be skipped until a newer version ships.")
            return target, cur

    def ready_version(self) -> str | None:
        r = self.state.get("ready")
        return r if r and self._valid(r) else None

    def promote_ready(self, db_path) -> tuple[str, str]:
        """Make the staged update current (after a database backup)."""
        with self._lock:
            ready = self.ready_version()
            if not ready:
                raise UpdateError("No update is ready to install.")
            backup_database(db_path, self.backups, f"before-{ready}")
            prev = self.state.get("current")
            self.state["previous"], self.state["current"], self.state["ready"] = prev, ready, None
            self.event("installed", ready, f"replaced {prev}")
            self._settle("up_to_date", f"Running {ready}.")
            return ready, prev

    def cleanup(self):
        keep = {self.state.get("current"), self.state.get("previous"), self.state.get("ready")}
        try:
            keep.add(self.bundled_version())
        except UpdateError:
            pass
        for p in self.versions.iterdir():
            if p.name not in keep:
                shutil.rmtree(p, ignore_errors=True)
        for p in self.tmp.iterdir():
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            except OSError:
                pass

    def daily_backup(self, db_path):
        newest = max((p.stat().st_mtime for p in self.backups.glob("hailwatch-*.db")), default=0)
        if time.time() - newest > 24 * 3600:
            try:
                backup_database(db_path, self.backups, "daily")
            except (sqlite3.Error, OSError) as e:
                log.warning("Daily backup failed: %s", e)

    # ---------------- checking GitHub ----------------
    def _set(self, phase, message=""):
        self.phase, self.message = phase, message

    def _settle(self, phase, message):
        """A final outcome worth remembering across restarts."""
        self._set(phase, message)
        self.state["last_result"] = {"phase": phase, "message": message}
        self._save()

    def mark_checking(self):
        with self._lock:
            if not self._busy and self.configured():
                self._set("checking", "Checking GitHub for updates…")

    def check(self, db_path) -> None:
        with self._lock:
            if self._busy:
                return
            if not self.configured():
                self._set("idle", "")
                return
            self._busy = True
            self._set("checking", "Checking GitHub for updates…")
        partial = zip_path = None
        try:
            src = self.source()
            sha, etag = src.latest_sha(self.state.get("etag"))
            self.state["last_check"] = _now_iso()
            self._save()
            if sha is None or sha == self.state.get("seen_sha"):
                last = self.state.get("last_result") or {"phase": "up_to_date",
                                                         "message": f"Running {self.state.get('current')}."}
                if self.ready_version():
                    last = {"phase": "ready", "message": ""}
                self._set(last["phase"], last["message"])
                return

            current = self.state.get("current")
            remote = src.manifest(sha)
            version = remote["version"]
            min_shell = remote.get("min_shell", 1)

            def seen(phase, message):
                self.state["etag"], self.state["seen_sha"] = etag, sha
                self._settle(phase, message)

            if current and parse_version(version) <= parse_version(current):
                return seen("up_to_date", f"Running {current} — the newest version on GitHub.")
            if version in self.state["bad"]:
                return seen("up_to_date", f"Running {current}. Version {version} was skipped earlier; "
                                          "publish a newer version number to ship a fix.")
            if not isinstance(min_shell, int) or min_shell > self.shell_api:
                self.state["needs_shell"] = {"version": version, "notes": remote.get("notes", "")}
                self.event("needs_shell", version, "requires a newer desktop installer")
                return seen("needs_shell", f"Version {version} needs a newer desktop installer. "
                                           "Download it once; after that, updates are automatic again.")
            if self.ready_version() == version:
                return seen("ready", "")

            self._set("downloading", f"Downloading {version}…")
            zip_path = self.tmp / f"{sha}.zip"
            src.download(sha, zip_path)
            partial = self.versions / f".{version}.partial-{os.getpid()}"
            shutil.rmtree(partial, ignore_errors=True)
            extract_payload(zip_path, partial, src.payload_path)
            got = read_manifest(partial)
            if got["version"] != version:
                raise UpdateError(f"The download says it's version {got['version']}, not {version}. Try again.")

            self._set("validating", f"Testing {version} on a copy of your data…")
            ok, err = selftest(partial, db_path)
            if not ok:
                hint = (" It needs a Python package this desktop build doesn't include — "
                        "build a new installer." if err and "ModuleNotFoundError" in err else "")
                self.state["bad"].append(version)
                self.event("rejected", version, f"failed its self-test: {err}")
                return seen("error", f"Version {version} failed its self-test and wasn't installed: {err}.{hint}")

            target = self.payload_dir(version)
            shutil.rmtree(target, ignore_errors=True)
            os.replace(partial, target)
            partial = None
            self.state["ready"] = version
            self.state["ready_notes"] = got.get("notes", "")
            self.state.pop("needs_shell", None)
            self.event("downloaded", version, "passed its self-test")
            seen("ready", "")
        except UpdateError as e:
            self._set("error", str(e))
        except requests.RequestException as e:
            log.warning("update check: %s", e)
            self._set("error", "Couldn't reach GitHub — check the internet connection. "
                               "The app keeps working; it will try again later.")
        except Exception as e:  # never let an update problem take the app down
            log.exception("update check crashed")
            self._set("error", f"The update check hit an unexpected problem ({type(e).__name__}: {e}).")
        finally:
            if partial is not None:
                shutil.rmtree(partial, ignore_errors=True)
            if zip_path is not None:
                try:
                    zip_path.unlink()
                except OSError:
                    pass
            with self._lock:
                self._busy = False

    # ---------------- for the app's “App & updates” page ----------------
    def status(self) -> dict:
        s = self.source_settings()
        ready = self.ready_version()
        backups = sorted(self.backups.glob("hailwatch-*.db"), key=lambda p: p.stat().st_mtime)
        try:
            bundled = self.bundled_version()
        except UpdateError:
            bundled = None
        history = [{"time": _pretty(h.get("at")), "label": LABELS.get(h.get("kind"), h.get("kind")),
                    "version": h.get("version"), "detail": h.get("detail", "")}
                   for h in reversed(self.state.get("history", [])[-12:])]
        return {
            "phase": "ready" if (ready and self.phase not in self.BUSY) else self.phase,
            "message": self.message,
            "busy": self._busy,
            "configured": bool(s.get("repo")),
            "repo": s.get("repo"),
            "branch": s.get("branch"),
            "has_token": bool(s.get("token")),
            "current": self.state.get("current"),
            "previous": self.state.get("previous"),
            "bundled": bundled,
            "rollback_to": self.rollback_target(),
            "ready": {"version": ready, "notes": self.state.get("ready_notes", "")} if ready else None,
            "needs_shell": self.state.get("needs_shell"),
            "last_check": _pretty(self.state.get("last_check")) if self.state.get("last_check") else None,
            "check_every_hours": int(self.check_interval_hours()) if self.check_interval_hours() >= 1
            else self.check_interval_hours(),
            "releases_url": f"https://github.com/{s['repo']}/releases/latest" if s.get("repo") else None,
            "last_backup": _pretty(datetime.fromtimestamp(backups[-1].stat().st_mtime, timezone.utc).isoformat())
            if backups else None,
            "history": history,
        }
