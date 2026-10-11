"""
The update channel, end to end, against a fake GitHub that serves the same
three API calls as the real one (commit SHA, manifest, zipball -> codeload).

Covers: update found -> downloaded -> self-tested on a copy of real data ->
applied without restarting; broken update rejected; update needing a new
installer; startup failure rolled back automatically; manual roll back and
skip; rate limit; private repo token; ETag 304; zip path traversal; the local
server's key check, host check and crash-recovery page; dev reinstall.
"""

import argparse
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from flask import Flask, Response, redirect, request
from werkzeug.serving import make_server
from werkzeug.test import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
import launcher  # noqa: E402
import updater as upd  # noqa: E402

launcher.setup_logging = lambda data_dir, verbose: Path(data_dir) / "logs" / "test.log"   # keep test output quiet
import logging  # noqa: E402
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def payload_files(version, app_patch=None, manifest_patch=None):
    files = {}
    for p in (ROOT / "payload").rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            files["payload/" + p.relative_to(ROOT / "payload").as_posix()] = p.read_bytes()
    m = json.loads(files["payload/manifest.json"])
    m.update({"version": version, "notes": f"Test release {version}"}, **(manifest_patch or {}))
    files["payload/manifest.json"] = json.dumps(m).encode()
    if app_patch:
        files["payload/app.py"] = app_patch(files["payload/app.py"].decode()).encode()
    files["README.md"] = b"repo root file that must not be installed"
    return files


class FakeGitHub:
    def __init__(self):
        self.commits, self.head, self.token, self.rate_limited, self.calls = {}, None, None, False, []
        app = Flask("fake-github")

        def gate():
            self.calls.append(request.path)
            if self.rate_limited:
                return Response("rate limited", 403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1900000000"})
            if self.token and request.headers.get("Authorization") != f"Bearer {self.token}":
                return Response("Not Found", 404)
            return None

        @app.get("/repos/<o>/<r>/commits/<path:ref>")
        def commit(o, r, ref):
            if (resp := gate()) is not None:
                return resp
            etag = f'"{self.head}"'
            if request.headers.get("If-None-Match") == etag:
                return Response(status=304)
            return Response(self.head, mimetype="text/plain", headers={"ETag": etag})

        @app.get("/repos/<o>/<r>/contents/<path:p>")
        def contents(o, r, p):
            if (resp := gate()) is not None:
                return resp
            data = self.commits[request.args["ref"]].get(p)
            return Response(data, mimetype="text/plain") if data is not None else Response("Not Found", 404)

        @app.get("/repos/<o>/<r>/zipball/<sha>")
        def zipball(o, r, sha):
            if (resp := gate()) is not None:
                return resp
            return redirect(f"/codeload/{o}/{r}/zip/{sha}", 302)

        @app.get("/codeload/<o>/<r>/zip/<sha>")
        def codeload(o, r, sha):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for path, data in self.commits[sha].items():
                    z.writestr(f"{o}-{r}-{sha[:7]}/{path}", data)
            return Response(buf.getvalue(), mimetype="application/zip")

        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def publish(self, files):
        sha = hashlib.sha1(json.dumps(sorted((k, hashlib.sha1(v).hexdigest()) for k, v in files.items())).encode()).hexdigest()
        self.commits[sha], self.head = files, sha
        return sha

    def close(self):
        self.server.shutdown()


class UpdateChannel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gh = FakeGitHub()

    @classmethod
    def tearDownClass(cls):
        cls.gh.close()

    def setUp(self):
        self.gh.token, self.gh.rate_limited, self.gh.calls = None, False, []
        self.tmp = Path(tempfile.mkdtemp())
        self.res = self.tmp / "resources"
        shutil.copytree(ROOT / "payload", self.res / "payload", ignore=shutil.ignore_patterns("__pycache__"))
        built_in = self.res / "payload" / "manifest.json"          # tests don't depend on the repo's version
        built_in.write_text(json.dumps({**json.loads(built_in.read_text()), "version": "1.0.0"}))
        (self.res / "desktop").mkdir(parents=True)
        (self.res / "desktop" / "update_config.json").write_text(json.dumps(
            {"repo": "test/hail", "branch": "main", "api": self.gh.url, "check_every_hours": 1}))
        self._orig = launcher.resource_dir
        launcher.resource_dir = lambda: self.res
        self.gh.publish(payload_files("1.0.0"))

    def tearDown(self):
        launcher.resource_dir = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def desktop(self):
        args = argparse.Namespace(headless=True, browser=False, data_dir=str(self.tmp / "data"), port=0,
                                  no_update=True, selftest=None, db=None, debug=False, verbose=False, offline=True)
        d = launcher.Desktop(args)
        d.boot()
        d.port = 5555
        return d

    def health(self, d):
        return d.dispatcher.current[0].test_client().get("/healthz").get_json()

    # ------------------------------------------------------------------
    def test_update_found_tested_and_applied_without_restart(self):
        d = self.desktop()
        self.assertEqual(self.health(d)["version"], "1.0.0")
        con = sqlite3.connect(d.db_path)
        con.execute("INSERT INTO places (kind,name,lat,lng) VALUES ('job','Keep me',45.8,-108.5)")
        con.commit()
        con.close()
        self.gh.publish(payload_files("1.0.1"))
        d.updater.check(d.db_path)
        st = d.updater.status()
        self.assertEqual(st["phase"], "ready", st["message"])
        self.assertEqual(st["ready"]["version"], "1.0.1")
        self.assertFalse((d.updater.payload_dir("1.0.1") / "README.md").exists())   # only payload/ installed
        old = d.dispatcher.current[0]
        stopped = []
        old.extensions["hailwatch.stop"] = lambda: stopped.append(True)
        res = d.apply_ready()
        self.assertTrue(res["ok"], res)
        h = self.health(d)
        self.assertEqual(h["version"], "1.0.1")
        self.assertEqual(h["places"], 1)                                   # data preserved
        self.assertTrue(stopped)                                           # old version's background work stopped
        self.assertTrue(list((self.tmp / "data" / "backups").glob("*before-1.0.1*")))

    def test_broken_update_is_rejected_and_skipped(self):
        d = self.desktop()
        self.gh.publish(payload_files("1.0.2", app_patch=lambda s: s + "\ndef broken(:\n"))
        d.updater.check(d.db_path)
        st = d.updater.status()
        self.assertEqual(st["phase"], "error")
        self.assertIn("SyntaxError", st["message"])
        self.assertIsNone(st["ready"])
        self.assertEqual(self.health(d)["version"], "1.0.0")
        self.assertIn("1.0.2", d.updater.state["bad"])

    def test_template_error_is_caught_by_the_selftest(self):
        d = self.desktop()
        files = payload_files("1.0.3")
        files["payload/templates/live.html"] = files["payload/templates/live.html"] + b"{% endblock %}{% if %}"
        self.gh.publish(files)
        d.updater.check(d.db_path)
        self.assertEqual(d.updater.status()["phase"], "error")

    def test_update_that_needs_a_new_installer(self):
        d = self.desktop()
        self.gh.publish(payload_files("1.1.0", manifest_patch={"min_shell": launcher.SHELL_API + 1}))
        d.updater.check(d.db_path)
        st = d.updater.status()
        self.assertEqual(st["phase"], "needs_shell")
        self.assertIn("releases", st["releases_url"])

    def test_startup_failure_rolls_back_automatically(self):
        d = self.desktop()
        self.gh.publish(payload_files("1.0.1"))
        d.updater.check(d.db_path)
        d.apply_ready()
        # passes its self-test (no desktop bridge there) but fails when it really starts
        trap = "\n_real = create_app\n\ndef create_app(config=None):\n    if (config or {}).get('SHELL') is not None:\n" \
               "        raise RuntimeError('only fails inside the desktop app')\n    return _real(config)\n"
        self.gh.publish(payload_files("1.0.4", app_patch=lambda s: s + trap))
        d.updater.check(d.db_path)
        self.assertEqual(d.updater.status()["phase"], "ready")
        d2 = self.desktop()                                   # next launch installs it, it fails, app recovers
        self.assertEqual(self.health(d2)["version"], "1.0.1")
        self.assertEqual(d2.session_rollback["from"], "1.0.4")
        self.assertIn("1.0.4", d2.updater.state["bad"])
        d2.updater.check(d2.db_path)                          # the failed version is not offered again
        self.assertIsNone(d2.updater.status()["ready"])

    def test_manual_roll_back_and_skip(self):
        d = self.desktop()
        self.gh.publish(payload_files("1.1.0"))
        d.updater.check(d.db_path)
        d.apply_ready()
        res = d.rollback()
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.health(d)["version"], "1.0.0")
        self.gh.publish(payload_files("1.1.0") | {"payload/extra.txt": b"same version, new commit"})
        d.updater.check(d.db_path)
        self.assertIsNone(d.updater.status()["ready"])        # 1.1.0 skipped until a newer number ships
        self.gh.publish(payload_files("1.1.1"))
        d.updater.check(d.db_path)
        self.assertEqual(d.updater.status()["ready"]["version"], "1.1.1")

    def test_rate_limit_private_repo_and_etag(self):
        d = self.desktop()
        self.gh.rate_limited = True
        d.updater.check(d.db_path)
        self.assertIn("hourly limit", d.updater.status()["message"])
        self.gh.rate_limited, self.gh.token = False, "s3cret"
        d.updater.check(d.db_path)
        self.assertIn("private", d.updater.status()["message"])
        self.assertTrue(d.updater.set_source("test/hail", "main", "s3cret")["ok"])
        d.updater.check(d.db_path)
        self.assertEqual(d.updater.status()["phase"], "up_to_date", d.updater.status()["message"])
        self.gh.calls = []
        d.updater.check(d.db_path)                            # nothing changed: answered by a 304
        self.assertEqual(self.gh.calls, ["/repos/test/hail/commits/main"])

    def test_zip_path_traversal_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("o-r-abc/payload/manifest.json", '{"version": "9.9.9"}')
            z.writestr("o-r-abc/payload/../../evil.py", "boom")
        zp = self.tmp / "evil.zip"
        zp.write_bytes(buf.getvalue())
        with self.assertRaises(upd.UpdateError):
            upd.extract_payload(zp, self.tmp / "out")
        self.assertFalse((self.tmp / "evil.py").exists())

    def test_local_server_key_host_and_recovery_page(self):
        d = self.desktop()
        c = Client(launcher.Gate(d.dispatcher, d))
        base = {"base_url": f"http://127.0.0.1:{d.port}"}
        self.assertEqual(c.get("/", **base).status_code, 403)                       # no key
        self.assertEqual(c.get("/__auth?k=wrong", **base).status_code, 403)
        r = c.get(f"/__auth?k={d.token}", **base)
        self.assertEqual(r.status_code, 303)
        self.assertIn("HttpOnly", r.headers["Set-Cookie"])
        self.assertEqual(c.get("/healthz", **base).status_code, 200)               # cookie now set
        self.assertEqual(c.get("/healthz", base_url="http://evil.example").status_code, 400)
        boom = Flask("boom")
        boom.get("/")(lambda: 1 / 0)
        d.dispatcher.swap(boom.wsgi_app, "9.9.9")
        r = c.get("/", **base)
        self.assertEqual(r.status_code, 500)
        self.assertIn(b"Something went wrong", r.data)

    def test_edited_builtin_payload_is_reinstalled_while_developing(self):
        d = self.desktop()
        target = d.updater.payload_dir("1.0.0") / "templates" / "app.html"
        (self.res / "payload" / "templates" / "app.html").write_text(
            target.read_text(encoding="utf-8") + "<!-- dev edit -->", encoding="utf-8")
        self.desktop()
        self.assertIn("dev edit", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
