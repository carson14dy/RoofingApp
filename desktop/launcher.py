"""
Montana Hail Watch — desktop app
================================
Opens the app in its own window and keeps it current from GitHub, so a change
you push reaches every install without a new download. This shell changes
rarely; the app it runs (the ``payload/`` folder) updates itself.

    python desktop/launcher.py                 native window
    python desktop/launcher.py --browser       use your web browser instead
    python desktop/launcher.py --headless      server only (testing)
    python desktop/launcher.py --selftest payload    check a payload before shipping it
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import logging.handlers
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from html import escape
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import updater as upd  # noqa: E402

SHELL_VERSION = "1.1.0"
SHELL_API = 1          # raise when the payload needs something only a newer shell provides
APP_NAME = "Montana Hail Watch"
APP_ID = "MontanaHailWatch"
COOKIE = "hw_session"
log = logging.getLogger("hailwatch")


def _bundle_imports():  # pragma: no cover — never called
    """Lists what app versions may import, so PyInstaller packs it into the
    installer. A future payload can only use packages listed (or imported) here."""
    import calendar, collections, csv, dataclasses, decimal, enum, functools, hashlib, html  # noqa
    import io, itertools, math, re, sqlite3, statistics, string, textwrap, uuid, zoneinfo  # noqa
    import xml.etree.ElementTree, email.utils, urllib.parse, concurrent.futures  # noqa
    import flask, jinja2, werkzeug, requests, waitress, tzdata  # noqa
    import folium, folium.plugins, branca, xyzservices  # noqa


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def resource_dir() -> Path:
    """Read-only files that ship with the app (inside the installer when frozen)."""
    return Path(getattr(sys, "_MEIPASS", HERE.parent))


def default_data_dir() -> Path:
    if os.environ.get("HAILWATCH_DATA_DIR"):
        return Path(os.environ["HAILWATCH_DATA_DIR"])
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_ID


def load_update_defaults() -> dict:
    p = resource_dir() / "desktop" / "update_config.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except (OSError, ValueError):
        return {}


def setup_logging(data_dir: Path, verbose: bool) -> Path:
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    path = data_dir / "logs" / "hailwatch.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if verbose or not getattr(sys, "frozen", False):
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(console)
    logging.getLogger("waitress").setLevel(logging.WARNING)
    return path


# --------------------------------------------------------------------------
# WSGI pieces
# --------------------------------------------------------------------------
class Dispatcher:
    """Forwards requests to whichever app version is current. Swapping is a
    single assignment, so an update takes effect on the very next click."""

    def __init__(self):
        self.current = (None, None)  # (wsgi_app, version)

    def swap(self, app, version):
        self.current = (app, version)

    @property
    def version(self):
        return self.current[1]

    def __call__(self, environ, start_response):
        return self.current[0](environ, start_response)


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0c1622;color:#e9f0f7;
font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif}}main{{max-width:560px;padding:28px}}
h1{{font:700 26px 'Arial Narrow',sans-serif;text-transform:uppercase;letter-spacing:.5px;margin:0 0 8px}}
p{{color:#8ea6bf}}code{{color:#e9f0f7;font-size:12.5px;word-break:break-all}}
button,a.b{{display:inline-block;margin:8px 8px 0 0;padding:10px 14px;border-radius:9px;border:1px solid #2a3e54;
background:#16273a;color:#e9f0f7;font:600 13px system-ui;text-decoration:none;cursor:pointer}}
button.p{{background:#e0a93c;border-color:#e0a93c;color:#20160a}}form{{display:inline}}</style></head>
<body><main><h1>{title}</h1>{body}</main></body></html>"""


def page(title, body):
    return PAGE.format(title=escape(title), body=body).encode("utf-8")


class Gate:
    """Front door for the local server. Only the app's own window gets in:
    it receives a one-time key at launch and keeps it in a cookie that other
    sites and programs can't read. Also turns a crash page from a bad app
    version into a recovery screen with a one-click roll back."""

    def __init__(self, inner, desktop: "Desktop"):
        self.inner, self.d = inner, desktop

    def _deny(self, start_response, status, title, body):
        start_response(status, [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store")])
        return [page(title, body)]

    def _redirect(self, start_response, location, cookie=None):
        headers = [("Location", location), ("Cache-Control", "no-store")]
        if cookie:
            headers.append(("Set-Cookie", cookie))
        start_response("303 See Other", headers)
        return [b""]

    def __call__(self, environ, start_response):
        host = environ.get("HTTP_HOST", "")
        if host not in (f"127.0.0.1:{self.d.port}", f"localhost:{self.d.port}"):
            return self._deny(start_response, "400 Bad Request", "Not available", "<p>Wrong address.</p>")
        path = environ.get("PATH_INFO") or "/"
        if path == "/__auth":
            key = parse_qs(environ.get("QUERY_STRING", "")).get("k", [""])[0]
            if hmac.compare_digest(key, self.d.token):
                return self._redirect(start_response, "/",
                                      f"{COOKIE}={self.d.token}; Path=/; HttpOnly; SameSite=Strict")
            return self._deny(start_response, "403 Forbidden", "Link expired",
                              "<p>Open Montana Hail Watch again to get a fresh window.</p>")
        cookie = SimpleCookie()
        try:
            cookie.load(environ.get("HTTP_COOKIE", ""))
        except Exception:
            pass
        sent = cookie.get(COOKIE).value if cookie.get(COOKIE) else ""
        if not hmac.compare_digest(sent, self.d.token):
            return self._deny(start_response, "403 Forbidden", "Open the app window",
                              "<p>This page only opens inside the Montana Hail Watch app.</p>")

        method = environ.get("REQUEST_METHOD", "GET")
        if path == "/__shell/rollback" and method == "POST":
            self.d.rollback()
            return self._redirect(start_response, "/app")
        if path == "/__shell/quit" and method == "POST":
            self.d.quit()
            return self._deny(start_response, "200 OK", "Closed", "<p>The app has closed. You can close this tab.</p>")

        captured = {}

        def capture(status, headers, exc_info=None):
            captured["status"] = status
            if status.startswith("500"):
                return lambda _data: None
            return start_response(status, headers, exc_info)

        try:
            result = self.inner(environ, capture)
        except Exception:
            log.exception("app version %s crashed on %s", self.d.dispatcher.version, path)
            captured["status"] = "500"
            result = None
        if captured.get("status", "").startswith("500"):
            if hasattr(result, "close"):
                result.close()
            return self._recovery(start_response)
        return result

    def _recovery(self, start_response):
        target = self.d.updater.rollback_target()
        ver = self.d.dispatcher.version or "?"
        body = (f"<p>Version {escape(ver)} hit an error on this page. Your data is safe.</p>"
                + (f'<form method="post" action="/__shell/rollback"><button class="p">Roll back to {escape(target)}</button></form>'
                   if target else "")
                + '<a class="b" href="/">Back to the map</a>'
                + f"<p>Details are in the log file:<br><code>{escape(str(self.d.log_path))}</code></p>")
        start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8")])
        return [page("Something went wrong", body)]


def fatal_app(message, log_path):
    def app(environ, start_response):
        start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8")])
        return [page("The app couldn't start",
                     f"<p>{escape(message)}</p><p>Reinstall the desktop app from your GitHub Releases page. "
                     f"Your data is untouched.</p><p>Log file:<br><code>{escape(str(log_path))}</code></p>")]
    return app


# --------------------------------------------------------------------------
# What the app version can ask the desktop to do
# --------------------------------------------------------------------------
class Bridge:
    api = SHELL_API

    def __init__(self, desktop: "Desktop"):
        self._d = desktop

    def info(self):
        d = self._d
        return {"shell_version": SHELL_VERSION, "shell_api": SHELL_API, "payload_version": d.dispatcher.version,
                "data_dir": str(d.data_dir), "db_path": str(d.db_path), "log_path": str(d.log_path),
                "mode": d.mode, "frozen": bool(getattr(sys, "frozen", False))}

    def update_status(self):
        s = self._d.updater.status()
        s["session_rollback"] = self._d.session_rollback
        s["mode"] = self._d.mode
        return s

    def check_updates(self):
        self._d.request_check()
        return self.update_status()

    def apply_update(self):
        return self._d.apply_ready()

    def rollback(self):
        return self._d.rollback()

    def set_update_source(self, repo, branch="main", token="", clear_token=False):
        return self._d.updater.set_source(repo, branch, token, clear_token)

    def save_file(self, suggested_name, data: bytes):
        return self._d.save_file(suggested_name, data)

    def open_data_folder(self):
        open_path(self._d.data_dir)

    def open_url(self, url):
        webbrowser.open(url)

    def notify(self, title, body):
        self._d.notify(title, body)

    def quit(self):
        self._d.quit()


def os_notify(title: str, body: str) -> bool:
    """Show a desktop notification. Text goes through environment variables,
    never into a command string."""
    env = {**os.environ, "HW_TITLE": title[:120], "HW_BODY": body[:400]}
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e",
                              'display notification (system attribute "HW_BODY") with title (system attribute "HW_TITLE")'],
                             env=env)
        elif sys.platform == "win32":
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                  "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  "$x=$t.GetElementsByTagName('text');"
                  "$x.Item(0).AppendChild($t.CreateTextNode($env:HW_TITLE)) > $null;"
                  "$x.Item(1).AppendChild($t.CreateTextNode($env:HW_BODY)) > $null;"
                  "$id='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show("
                  "[Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
                             env=env, creationflags=0x08000000)  # CREATE_NO_WINDOW
        else:
            subprocess.Popen(["notify-send", "--app-name", APP_NAME, title, body], env=env)
        return True
    except (OSError, ValueError) as e:
        log.warning("couldn't show a desktop notification: %s", e)
        return False


def open_path(path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — opening the user's own folder
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# --------------------------------------------------------------------------
# The desktop app
# --------------------------------------------------------------------------
class Desktop:
    def __init__(self, args):
        self.args = args
        self.mode = "headless" if args.headless else ("browser" if args.browser else "window")
        self.data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = setup_logging(self.data_dir, args.verbose)
        self.db_path = self.data_dir / "hailwatch.db"
        self.updater = upd.Updater(self.data_dir, resource_dir() / "payload", SHELL_API,
                                   defaults=load_update_defaults(), user_agent=f"{APP_ID}/{SHELL_VERSION}")
        self.dispatcher = Dispatcher()
        self.bridge = Bridge(self)
        self.token = secrets.token_urlsafe(32)
        self.session_rollback = None
        self.window = None
        self.port = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._swap_lock = threading.Lock()
        self._last_error = None

    # ---------------- app versions ----------------
    def activate(self, version) -> bool:
        app = None
        try:
            module = upd.load_payload(self.updater.payload_dir(version), tag="live")
            app = module.create_app({"DATA_DIR": str(self.data_dir), "DB_PATH": str(self.db_path),
                                     "NETWORK": not self.args.offline, "SHELL": self.bridge, "TESTING": False})
            resp = app.test_client().get("/healthz")
            if resp.status_code != 200:
                raise upd.UpdateError(f"its health check returned HTTP {resp.status_code}")
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {e}"
            log.error("version %s failed to start:\n%s", version, traceback.format_exc())
            stop = getattr(app, "extensions", {}).get("hailwatch.stop") if app is not None else None
            if callable(stop):
                stop()
            return False
        old = self.dispatcher.current[0]
        self.dispatcher.swap(app, version)
        stop_old = getattr(old, "extensions", {}).get("hailwatch.stop") if old is not None else None
        if callable(stop_old):
            try:
                stop_old()            # the replaced version stops its background checks
            except Exception:
                log.exception("stopping the previous version")
        log.info("running app version %s", version)
        return True

    def boot(self):
        version = self.updater.prepare_startup(self.db_path)
        tried = set()
        while version and version not in tried:
            tried.add(version)
            if self.activate(version):
                break
            fallback = self.updater.record_failure(version, self._last_error)
            self.session_rollback = {"from": version, "to": fallback, "error": self._last_error}
            version = fallback
        else:
            self.dispatcher.swap(fatal_app(f"No app version could start. Last error: {self._last_error}",
                                           self.log_path), None)
            return
        self.updater.cleanup()
        self.updater.daily_backup(self.db_path)

    def apply_ready(self) -> dict:
        with self._swap_lock:
            try:
                new, old = self.updater.promote_ready(self.db_path)
            except upd.UpdateError as e:
                return {"ok": False, "message": str(e)}
            if self.activate(new):
                self.updater.cleanup()
                return {"ok": True, "version": new}
            err = self._last_error
            fallback = self.updater.record_failure(new, err)
            if fallback:
                self.activate(fallback)
            return {"ok": False, "message": f"Version {new} failed to start, so the app stayed on "
                                            f"{fallback or old}. ({err})"}

    def rollback(self) -> dict:
        with self._swap_lock:
            target, skipped = self.updater.rollback()
            if not target:
                return {"ok": False, "message": "There's no earlier version on this computer to go back to."}
            if self.activate(target):
                return {"ok": True, "message": f"Rolled back to {target}. Version {skipped} will be skipped "
                                               "until a newer version is published."}
            return {"ok": False, "message": f"Rolling back to {target} failed too: {self._last_error}"}

    # ---------------- background update checks ----------------
    def request_check(self):
        self.updater.mark_checking()
        self._wake.set()

    def _update_loop(self):
        if self._stop.wait(4):
            return
        while not self._stop.is_set():
            try:
                self.updater.check(self.db_path)
            except Exception:
                log.exception("update loop")
            self._wake.wait(self.updater.check_interval_hours() * 3600)
            self._wake.clear()

    # ---------------- server ----------------
    def serve(self):
        from waitress.server import create_server
        self.server = create_server(Gate(self.dispatcher, self), host="127.0.0.1",
                                    port=self.args.port or 0, threads=8, ident=APP_ID)
        self.port = self.server.effective_port
        threading.Thread(target=self.server.run, name="http", daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.auth_url = f"{self.base_url}/__auth?k={self.token}"

    # ---------------- desktop services ----------------
    def save_file(self, suggested_name, data: bytes):
        """Native Save dialog. None = not available (browser mode), '' = cancelled."""
        if self.mode != "window" or self.window is None:
            return None
        import webview
        ext = Path(suggested_name).suffix.lower()
        kinds = {".csv": "Spreadsheet (*.csv)", ".html": "Web page (*.html)", ".json": "JSON (*.json)"}
        start = Path.home() / "Downloads"
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE, directory=str(start if start.is_dir() else Path.home()),
            save_filename=suggested_name, file_types=(kinds.get(ext, "All files (*.*)"),))
        path = result if isinstance(result, str) else (result[0] if result else "")
        if not path:
            return ""
        Path(path).write_bytes(data)
        log.info("saved %s", path)
        return str(path)

    def notify(self, title, body):
        log.info("notification: %s — %s", title, body)
        if self.mode != "headless":
            os_notify(title, body)

    def quit(self):
        self._stop.set()
        self._wake.set()
        if self.window is not None:
            threading.Thread(target=self.window.destroy, daemon=True).start()

    # ---------------- run ----------------
    def run(self):
        log.info("%s desktop %s starting (mode=%s, data=%s)", APP_NAME, SHELL_VERSION, self.mode, self.data_dir)
        self.boot()
        self.serve()
        if not self.args.no_update:
            threading.Thread(target=self._update_loop, name="updates", daemon=True).start()
        if self.mode == "window":
            try:
                return self._run_window()
            except Exception:
                log.exception("Couldn't open the app window; falling back to the web browser")
                self.mode = "browser"
        if self.mode == "browser":
            webbrowser.open(self.auth_url)
            print(f"{APP_NAME} is open in your browser. Use “Quit the app” on the App & updates page to stop it.")
        else:
            print(json.dumps({"url": self.base_url, "auth_url": self.auth_url, "data_dir": str(self.data_dir)}),
                  flush=True)
        try:
            while not self._stop.wait(1):
                pass
        except KeyboardInterrupt:
            pass

    def _run_window(self):
        import webview
        from webview.menu import Menu, MenuAction, MenuSeparator

        def later(fn):
            return lambda: threading.Thread(target=fn, daemon=True).start()

        def go(path):
            self.window.load_url(self.base_url + path)

        def check():
            self.request_check()
            go("/app")

        def roll_back():
            target = self.updater.rollback_target()
            if not target:
                self.window.create_confirmation_dialog(APP_NAME, "There's no earlier version to go back to.")
                return
            if self.window.create_confirmation_dialog(
                    "Roll back?", f"Go back to version {target}? Version {self.dispatcher.version} "
                                  "will be skipped until a newer version is published. Your data stays as it is."):
                self.rollback()
                go("/app")

        menu = [Menu("Hail Watch", [
            MenuAction("Live Storms", later(lambda: go("/"))),
            MenuAction("App && updates", later(lambda: go("/app"))) if sys.platform == "win32"
            else MenuAction("App & updates", later(lambda: go("/app"))),
            MenuAction("Check for updates", later(check)),
            MenuAction("Roll back to previous version…", later(roll_back)),
            MenuSeparator(),
            MenuAction("Open data folder", later(lambda: open_path(self.data_dir))),
        ])]
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        self.window = webview.create_window(
            APP_NAME, url=self.auth_url, width=1440, height=920, min_size=(980, 640),
            background_color="#0c1622", text_select=True, menu=menu)
        icon = resource_dir() / "assets" / "icon.png"
        webview.start(private_mode=True, storage_path=str(self.data_dir / "webview"),
                      icon=str(icon) if icon.exists() else None, debug=self.args.debug)
        self.quit()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog=APP_ID, description=f"{APP_NAME} desktop app")
    ap.add_argument("--browser", action="store_true", help="open in the web browser instead of a window")
    ap.add_argument("--headless", action="store_true", help="run the local server only (testing)")
    ap.add_argument("--data-dir", help="use this data folder instead of the default")
    ap.add_argument("--port", type=int, default=0, help="local port (default: any free port)")
    ap.add_argument("--no-update", action="store_true", help="don't check GitHub for updates")
    ap.add_argument("--offline", action="store_true", help="no live weather calls (testing)")
    ap.add_argument("--selftest", nargs="?", const="", metavar="PAYLOAD_DIR",
                    help="test an app payload and exit (no folder = the one built into this app)")
    ap.add_argument("--db", help="with --selftest: test against a copy of this database")
    ap.add_argument("--debug", action="store_true", help="enable the web inspector")
    ap.add_argument("--verbose", action="store_true", help="also log to the console")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} desktop {SHELL_VERSION} (API {SHELL_API})")
    args = ap.parse_args(argv)

    if args.selftest is not None:
        args.selftest = args.selftest or str(resource_dir() / "payload")
        try:
            manifest = upd.read_manifest(args.selftest)
        except upd.UpdateError as e:
            print(f"FAIL  {e}")
            return 1
        if manifest["min_shell"] > SHELL_API:
            print(f"FAIL  payload {manifest['version']} needs desktop API {manifest['min_shell']}; "
                  f"this shell provides {SHELL_API}. Build a new installer.")
            return 1
        ok, err = upd.selftest(args.selftest, args.db)
        print(f"{'PASS' if ok else 'FAIL'}  payload {manifest['version']}" + ("" if ok else f": {err}"))
        return 0 if ok else 1

    Desktop(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
