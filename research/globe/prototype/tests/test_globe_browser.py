"""Browser check for the 3D storm view prototype (Playwright and headless Chromium).

Skips, and does not fail, when Playwright, Pillow, the Chromium binary or the network the page needs
is missing. Otherwise it:
  1. starts serve.py on a free port and opens the page with the recipe
     (executable_path to the installed Chromium, headless, no extra flags)
  2. waits until Cesium reports globe.tilesLoaded, or 45 s, then until tile requests settle
  3. takes a screenshot and writes a copy of at most 300 KB to validation-evidence/globe-prototype.png
  4. measures the canvas: fraction of non-black pixels (must be above 0.2)
  5. turns the GOES GeoColor layer off in the panel: the canvas pixels must change
  6. checks that the GOES legend holds the parallax wording verbatim, and every layer row is present
  7. hovers over Billings: its name must show while the pointer is over it
  8. blocks cdnjs and reloads: "3D view could not load" shows and the layer panel still renders

The 3D storms (volume) cases start serve.py with a volume file and check the layer on the page:
  9. synthetic volume (serve.py's default): the legend text is in the DOM, turning the layer on changes
     the canvas, the drawn count and the dBZ swatches are right, and exaggeration 3x is labelled on screen
 10. sample volume (--volume fixtures/volume-2025-06-15-sample.json): the count in the panel equals the
     fixture's voxel count; the screenshot of this run goes to validation-evidence/globe-volume.png

Run from the prototype folder with a Python that has Playwright and Pillow:
    <venv>/bin/python -I -m unittest discover -s tests -p "test_globe_browser.py" -v
Set GLOBE_CHROMIUM to point at another Chromium binary. Set GLOBE_P1_SCREENSHOT_DIR to a scratch folder to
keep the screenshot tests from rewriting validation-evidence/globe-prototype.png and globe-volume.png.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
EVIDENCE = os.path.normpath(os.path.join(PROTO, "..", "validation-evidence"))
EVIDENCE_PNG = os.path.join(os.environ.get("GLOBE_P1_SCREENSHOT_DIR", EVIDENCE), "globe-prototype.png")
VOLUME_PNG = os.path.join(os.environ.get("GLOBE_P1_SCREENSHOT_DIR", EVIDENCE), "globe-volume.png")
PARALLAX_JSON = os.path.join(EVIDENCE, "parallax.json")
UA = "RoofingApp-globe-prototype (research)"
TILES_WAIT_S = 45
SCREENSHOT_LIMIT = 300 * 1024
TILE_HOSTS = ("gibs.earthdata.nasa.gov", "basemap.nationalmap.gov", "mapservices.weather.noaa.gov",
              "cdnjs.cloudflare.com", "api.weather.gov")
LAYER_HITS = {
    "goes_east_geocolor": "GOES-East_ABI_GeoColor",
    "goes_east_band13": "GOES-East_ABI_Band13",
    "bluemarble": "BlueMarble",
    "usgs_imagery": "USGSImageryOnly",
    "nws_radar": "MapServer/export",
    "nws_alerts_zones": "api.weather.gov/zones",
}


def resample_filter(image_module):
    resampling = getattr(image_module, "Resampling", image_module)
    return getattr(resampling, "LANCZOS")


def browser_path():
    override = os.environ.get("GLOBE_CHROMIUM")
    if override:
        return override if os.path.exists(override) else None
    found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return found[-1] if found else None


def network_reachable():
    """True when the hosts the page needs answer at all (any HTTP status counts as reachable)."""
    for url in ("https://api.cdnjs.com/libraries/cesium?fields=version",
                "https://api.weather.gov/alerts/active?area=MT"):
        try:
            urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15).close()
        except urllib.error.HTTPError:
            continue
        except (urllib.error.URLError, OSError):
            return False
    return True


def write_screenshot_copy(src, dst, limit=SCREENSHOT_LIMIT):
    """Write the largest copy that fits in `limit` bytes: full colour first, then 256 colours, at
    decreasing widths. Returns its size, pixels and colour mode."""
    from PIL import Image

    img = Image.open(src).convert("RGB")
    lanczos = resample_filter(Image)
    for width in (1280, 1152, 1024, 960, 896, 800, 720):
        w = min(width, img.width)
        scaled = img.resize((w, round(img.height * w / img.width)), lanczos)
        for mode in ("RGB", "palette-256"):
            copy = scaled if mode == "RGB" else scaled.quantize(colors=256)
            copy.save(dst, format="PNG", optimize=True)
            size = os.path.getsize(dst)
            if size <= limit:
                return {"width": copy.width, "height": copy.height, "bytes": size, "colours": mode}
    raise AssertionError(f"no copy of the screenshot fits in {limit} bytes")


def fraction_nonblack(image):
    hist = image.convert("L").histogram()
    total = sum(hist)
    return sum(hist[17:]) / float(total)


def fraction_changed(a, b):
    from PIL import ImageChops

    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    hist = diff.histogram()
    return sum(hist[17:]) / float(sum(hist))


class GlobeBrowserTests(unittest.TestCase):
    server = None
    base = None
    expected_rows = 0
    results = {}

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed in this Python")
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Pillow is not installed in this Python")
        if not browser_path():
            raise unittest.SkipTest("Chromium binary not found (set GLOBE_CHROMIUM)")
        if not network_reachable():
            raise unittest.SkipTest("the network the page needs (cdnjs, NWS) is not reachable")

        cls.server = subprocess.Popen([sys.executable, "-B", os.path.join(PROTO, "serve.py"), "--port", "0"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = {}

        def read_port():
            line["text"] = cls.server.stdout.readline()

        reader = threading.Thread(target=read_port, daemon=True)
        reader.start()
        reader.join(30)
        text = line.get("text", "").strip()
        if not text.startswith("PORT="):
            cls.server.kill()
            raise AssertionError(f"serve.py did not print PORT=<n>: {text!r}")
        cls.base = f"http://127.0.0.1:{int(text.split('=')[1])}"
        with urllib.request.urlopen(cls.base + "/api/layers.json", timeout=120) as r:
            cls.expected_rows = len(json.loads(r.read())["layers"])
        cls.results = {"server_port_note": "random free port", "expected_layer_rows": cls.expected_rows}

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server.kill()
            for pipe in (cls.server.stdout, cls.server.stderr):
                if pipe is not None:
                    pipe.close()

    def _track(self, page, hits, bad, console):
        pending = set()

        def host_of(url):
            return url.split("/")[2] if "://" in url else ""

        def on_request(r):
            if host_of(r.url) in TILE_HOSTS:
                pending.add(r.url)

        def on_done(r):
            pending.discard(r.url)

        def on_response(r):
            name = host_of(r.url)
            hosts = self.results.setdefault("responses_by_host", {})
            entry = hosts.setdefault(name, {"ok": 0, "error": 0})
            if r.status >= 400:
                entry["error"] += 1
                bad.append({"status": r.status, "url": r.url[:160]})
            else:
                entry["ok"] += 1
                for key, needle in LAYER_HITS.items():
                    if needle in r.url:
                        hits[key] = hits.get(key, 0) + 1
            pending.discard(r.url)

        def on_console(m):
            if m.type == "error":
                console.append(m.text[:200])

        page.on("request", on_request)
        page.on("requestfinished", on_done)
        page.on("requestfailed", on_done)
        page.on("response", on_response)
        page.on("console", on_console)
        page.on("pageerror", lambda e: console.append("pageerror: " + str(e)[:200]))
        return pending

    def test_globe_draws_toggles_hovers_and_matches_the_panel(self):
        from playwright.sync_api import sync_playwright

        with open(PARALLAX_JSON, encoding="utf-8") as f:
            parallax = json.load(f)["wording"]["ui_legend_uncorrected_phase1"]
        hits, bad, console = {}, [], []
        tmp = tempfile.mkdtemp(prefix="globe-browser-")
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            pending = self._track(page, hits, bad, console)
            t0 = time.time()
            page.goto(self.base + "/", wait_until="load", timeout=120000)
            self.results["page_load_s"] = round(time.time() - t0, 1)

            tiles_at = None
            while time.time() - t0 < TILES_WAIT_S:
                if page.evaluate("() => !!(window.globeViewer && window.globeViewer.scene.globe.tilesLoaded)"):
                    tiles_at = round(time.time() - t0, 1)
                    break
                page.wait_for_timeout(250)
            self.results["tiles_loaded_s"] = tiles_at
            quiet = None
            settled = False
            while time.time() - t0 < TILES_WAIT_S + 15:
                if not pending:
                    quiet = quiet or time.time()
                    if time.time() - quiet >= 2.0:
                        settled = True
                        break
                else:
                    quiet = None
                page.wait_for_timeout(250)
            self.results["tile_requests_settled"] = settled
            self.results["tile_requests_pending_at_capture"] = len(pending)

            full = os.path.join(tmp, "full.png")
            page.screenshot(path=full)
            shot_info = write_screenshot_copy(full, EVIDENCE_PNG)
            self.results["screenshot"] = shot_info

            from PIL import Image

            canvas_a_bytes = page.locator("#cesiumContainer canvas").first.screenshot()
            canvas_a = Image.open(io.BytesIO(canvas_a_bytes)).convert("RGB")
            nonblack = fraction_nonblack(canvas_a)
            self.results["canvas_nonblack_fraction"] = round(nonblack, 4)
            self.results["canvas_size_px"] = list(canvas_a.size)
            self.assertGreater(nonblack, 0.2, "the canvas is mostly black: the globe did not draw")

            page.uncheck("#toggle-goes_east_geocolor")
            page.wait_for_timeout(4000)
            canvas_b = Image.open(io.BytesIO(page.locator("#cesiumContainer canvas").first.screenshot())).convert("RGB")
            changed = fraction_changed(canvas_a, canvas_b)
            self.results["canvas_changed_fraction_after_goes_off"] = round(changed, 4)
            self.assertGreater(changed, 0.02, "turning GOES GeoColor off did not change the canvas")
            page.check("#toggle-goes_east_geocolor")
            page.wait_for_timeout(1500)

            legend = page.evaluate("() => { const n = document.querySelector('[data-layer=goes_east_geocolor] .legend');"
                                   " return n ? n.textContent : null; }")
            self.assertIsNotNone(legend, "the GOES GeoColor row has no legend")
            self.assertIn(parallax, legend, "the GOES legend does not hold the parallax wording verbatim")
            panel_text = page.evaluate("() => document.getElementById('panel').textContent")
            self.assertIn(parallax, panel_text)
            self.results["parallax_wording_in_dom"] = True
            rows = page.locator("#layer-list .layer").count()
            self.assertEqual(rows, self.expected_rows, "the panel does not list every layer")
            self.results["panel_rows"] = rows
            states = page.evaluate("() => Array.from(document.querySelectorAll('#layer-list .layer')).map("
                                   "l => [l.dataset.layer, l.querySelector('.state').textContent])")
            self.results["panel_states"] = states
            # The Limit row shows Python's words: timed layers say so, untimed layers say they are not timed.
            limits = page.evaluate("() => Array.from(document.querySelectorAll('#layer-list .layer')).map((l) => {"
                                   " const dt = Array.from(l.querySelectorAll('dt')).find((d) => d.textContent === 'Limit');"
                                   " return [l.dataset.layer, dt ? dt.nextElementSibling.textContent : null]; })")
            self.results["panel_limit_rows"] = limits
            for layer_id, text in limits:
                if layer_id in UNTIMED_LAYERS:
                    self.assertEqual(text, "none: not timed", layer_id)
                else:
                    self.assertIn(LIMIT_PHRASE, text, f"the {layer_id} Limit row does not say it is a proposal")

            hover = page.evaluate("""() => {
              const v = window.globeViewer;
              const src = v.dataSources.getByName('places')[0];
              const e = src.entities.values.find((x) => x.name === 'Billings');
              const c = v.scene.cartesianToCanvasCoordinates(e.position.getValue(Cesium.JulianDate.now()));
              const r = v.canvas.getBoundingClientRect();
              return c ? {x: r.left + c.x, y: r.top + c.y} : null;
            }""")
            self.assertIsNotNone(hover, "Billings is not on screen to hover")
            page.mouse.move(hover["x"], hover["y"])
            page.wait_for_timeout(800)
            shown = page.evaluate("""() => {
              const src = window.globeViewer.dataSources.getByName('places')[0];
              return src.entities.values.filter((x) => x.label && x.label.show.getValue(Cesium.JulianDate.now()))
                .map((x) => x.name);
            }""")
            self.results["hover_labels_shown"] = shown
            self.assertEqual(shown, ["Billings"], "hovering Billings did not show exactly its name")

            drawn = page.evaluate("() => { const s = window.globeStatus; return {cesium: s.cesium, viewer: s.viewer,"
                                  " drawn: s.drawn, alerts: s.alerts, places: s.places, tileErrors: s.tileErrors,"
                                  " error: s.error}; }")
            self.results["browser_status"] = drawn
            self.results["tile_requests_by_layer"] = hits
            self.results["bad_responses"] = bad[:10]
            self.results["console_errors_first_10"] = [c for c in console if "GL Driver Message" not in c][:10]
            self.results["console_gl_driver_messages"] = sum(1 for c in console if "GL Driver Message" in c)
            browser.close()
        print("GLOBE_BROWSER_RESULT=" + json.dumps(self.results, sort_keys=True))

    def test_phone_width_has_no_horizontal_scroll(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(self.base + "/", wait_until="load", timeout=120000)
            page.wait_for_selector("#layer-list .layer", timeout=60000)
            measure = page.evaluate("""() => {
              const doc = document.documentElement;
              const stage = document.getElementById('globe-stage').getBoundingClientRect();
              return {innerWidth: window.innerWidth, scrollWidth: doc.scrollWidth,
                      bodyScrollWidth: document.body.scrollWidth, stageWidth: Math.round(stage.width),
                      stageHeight: Math.round(stage.height),
                      rows: document.querySelectorAll('#layer-list .layer').length};
            }""")
            self.results["phone_width"] = measure
            self.assertLessEqual(measure["scrollWidth"], measure["innerWidth"], "the page scrolls sideways")
            self.assertLessEqual(measure["bodyScrollWidth"], measure["innerWidth"])
            self.assertEqual(measure["rows"], self.expected_rows)
            self.assertGreater(measure["stageHeight"], 300)
            browser.close()
        print("GLOBE_BROWSER_PHONE_RESULT=" + json.dumps(measure, sort_keys=True))

    def test_cdn_blocked_shows_failure_and_the_panel_still_renders(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.route("https://cdnjs.cloudflare.com/**", lambda route: route.abort())
            page.goto(self.base + "/", wait_until="load", timeout=120000)
            page.wait_for_selector("#globe-error:not([hidden])", timeout=30000)
            text = page.inner_text("#globe-error")
            self.assertIn("3D view could not load", text)
            cesium_state = page.evaluate("() => window.globeStatus.cesium")
            self.assertEqual(cesium_state, "failed")
            rows = page.locator("#layer-list .layer").count()
            self.assertEqual(rows, self.expected_rows, "the panel did not render with the 3D view down")
            legend_count = page.locator("#layer-list .legend").count()
            self.assertEqual(legend_count, self.expected_rows)
            self.results["cdn_blocked"] = {"error_text": text.strip()[:200], "panel_rows": rows,
                                           "cesium_state": cesium_state}
            browser.close()
        print("GLOBE_BROWSER_CDN_RESULT=" + json.dumps(self.results["cdn_blocked"], sort_keys=True))


class GlobeOfflineBrowserTests(unittest.TestCase):
    """serve.py --offline: feed layers show Off, the panel still renders, and the base maps still draw
    when the browser can reach their providers."""

    server = None
    base = None

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed in this Python")
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Pillow is not installed in this Python")
        if not browser_path():
            raise unittest.SkipTest("Chromium binary not found (set GLOBE_CHROMIUM)")
        cls.server = subprocess.Popen([sys.executable, "-B", os.path.join(PROTO, "serve.py"), "--port", "0",
                                       "--offline"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = {}

        def read_port():
            line["text"] = cls.server.stdout.readline()

        reader = threading.Thread(target=read_port, daemon=True)
        reader.start()
        reader.join(30)
        text = line.get("text", "").strip()
        if not text.startswith("PORT="):
            cls.server.kill()
            raise AssertionError(f"serve.py --offline did not print PORT=<n>: {text!r}")
        cls.base = f"http://127.0.0.1:{int(text.split('=')[1])}"

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server.kill()
            for pipe in (cls.server.stdout, cls.server.stderr):
                if pipe is not None:
                    pipe.close()

    def test_offline_feeds_are_off_and_the_panel_renders(self):
        from PIL import Image
        from playwright.sync_api import sync_playwright

        results = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(self.base + "/", wait_until="load", timeout=120000)
            page.wait_for_selector("#layer-list .layer", timeout=60000)
            rows = page.evaluate("""() => Array.from(document.querySelectorAll('#layer-list .layer')).map((l) => ({
              id: l.dataset.layer, state: l.querySelector('.state').textContent,
              toggleDisabled: l.querySelector('input').disabled}))""")
            results["rows"] = rows
            feeds = [r for r in rows if r["id"] in ("goes_east_geocolor", "goes_east_band13", "nws_radar", "nws_alerts")]
            self.assertEqual([r["state"] for r in feeds], ["Off"] * 4)
            self.assertTrue(all(r["toggleDisabled"] for r in feeds))
            self.assertIn("Live feeds are off", page.evaluate("() => document.getElementById('layer-list').textContent"))
            page.wait_for_function("() => window.globeStatus && (window.globeStatus.cesium === 'failed'"
                                   " || window.globeStatus.viewer === true)", timeout=60000)
            cesium = page.evaluate("() => window.globeStatus.cesium")
            results["cesium"] = cesium
            if cesium == "loaded":
                deadline = time.time() + TILES_WAIT_S
                while time.time() < deadline:
                    if page.evaluate("() => !!(window.globeViewer && window.globeViewer.scene.globe.tilesLoaded)"):
                        break
                    page.wait_for_timeout(250)
                page.wait_for_timeout(2000)
                canvas = Image.open(io.BytesIO(page.locator("#cesiumContainer canvas").first.screenshot())).convert("RGB")
                results["base_canvas_nonblack_fraction"] = round(fraction_nonblack(canvas), 4)
                drawn = page.evaluate("() => window.globeStatus.drawn")
                results["drawn"] = drawn
                self.assertEqual(drawn.get("usgs_imagery"), "imagery")
                self.assertEqual(drawn.get("bluemarble"), "imagery")
                for off_layer in ("goes_east_geocolor", "nws_radar", "nws_alerts"):
                    self.assertNotIn(off_layer, drawn)
                self.assertGreater(results["base_canvas_nonblack_fraction"], 0.2)
            else:
                text = page.inner_text("#globe-error")
                self.assertIn("3D view could not load", text)
                results["error_text"] = text.strip()[:160]
            browser.close()
        print("GLOBE_OFFLINE_RESULT=" + json.dumps(results, sort_keys=True))


# ----------------------------------------------------------------------------
# 3D storms (MRMS reflectivity volume): the layer as the page shows it
# ----------------------------------------------------------------------------
SYNTH_FIXTURE = "volume-synthetic.json"
SAMPLE_FIXTURE = "volume-2025-06-15-sample.json"
SYNTH_LABEL = "synthetic: not weather"
ARCHIVED_LABEL = "Archived event: recorded MRMS volume, not live"
VOLUME_LEGEND = ("Radar echo strength (dBZ). Not hail size. -99/-999 cells are no radar data; "
                 "no echo is not clear.")
# The 14 NWS reflectivity colours, 5-10 dBZ up to 70-75 dBZ (serve.py DBZ_STEPS; MetPy 1.7.1 table). Kept here
# as an independent copy, so the swatches are checked against the table, not against themselves.
NWS_STEP_HEX = ["#00ECEC", "#01A0F6", "#0000F6", "#00FF00", "#00C800", "#009000", "#FFFF00",
                "#E7C000", "#FF9000", "#FF0000", "#D60000", "#C00000", "#FF00FF", "#9955C9"]
NWS_STEP_LABELS = [f"{lo}–{lo + 5}{'+' if lo == 70 else ''} dBZ" for lo in range(5, 71, 5)]
UNTIMED_LAYERS = {"places", "usgs_imagery", "bluemarble"}
LIMIT_PHRASE = "limit (proposal, from measured latency)"
# Turning the storms on must change at least this share of canvas pixels (luma difference of 17 or more).
VOLUME_MIN_CHANGED = 0.002
VOLUME_ROW_JS = """() => {
  const row = document.querySelector('[data-layer=mrms_volume]');
  if (!row) return null;
  const box = row.querySelector('input[type=checkbox]');
  const chip = row.querySelector('.label-chip');
  const legend = row.querySelector('.legend');
  return {legend: legend ? legend.textContent : null, label: chip ? chip.textContent : null,
          state: row.querySelector('.state').textContent, toggleDisabled: box.disabled, checked: box.checked};
}"""
SWATCH_JS = ("() => Array.from(document.querySelectorAll('[data-layer=mrms_volume] .swatch'))"
             ".map((s) => getComputedStyle(s).backgroundColor)")
SWATCH_LABEL_JS = ("() => Array.from(document.querySelectorAll('[data-layer=mrms_volume] .dbz-step'))"
                   ".map((s) => s.textContent.trim())")


def load_fixture(name):
    with open(os.path.join(PROTO, "fixtures", name), encoding="utf-8") as f:
        return json.load(f)


def rgb_css(hex_colour):
    h = hex_colour.lstrip("#")
    return "rgb(%d, %d, %d)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def track_requests(page):
    """Imagery requests still pending, and HTTP errors and page errors seen, for one page."""
    pending, errors = set(), []

    def host_of(url):
        return url.split("/")[2] if "://" in url else ""

    def on_request(r):
        if host_of(r.url) in TILE_HOSTS:
            pending.add(r.url)

    def on_done(r):
        pending.discard(r.url)

    def on_response(r):
        if r.status >= 400:
            errors.append({"status": r.status, "url": r.url[:120]})
        pending.discard(r.url)

    page.on("request", on_request)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)
    page.on("response", on_response)
    page.on("pageerror", lambda e: errors.append({"pageerror": str(e)[:200]}))
    return pending, errors


def settle_tiles(page, pending, timeout_s, results, key):
    """Waits until the 3D view reports tilesLoaded and no imagery request has been pending for 2 s."""
    t0 = time.time()
    quiet_since = None
    loaded = False
    while time.time() - t0 < timeout_s:
        loaded = page.evaluate("() => !!(window.globeViewer && window.globeViewer.scene.globe.tilesLoaded)")
        if loaded and not pending:
            quiet_since = quiet_since or time.time()
            if time.time() - quiet_since >= 2.0:
                break
        else:
            quiet_since = None
        page.wait_for_timeout(250)
    results[key] = {"waited_s": round(time.time() - t0, 1), "tiles_loaded": loaded, "pending": len(pending)}


def write_palette_copy(src, dst, widths=(1024, 960, 896, 800), limit=SCREENSHOT_LIMIT):
    """A downscaled 256-colour PNG whose palette always holds the 14 NWS swatch colours exactly. A plain
    median-cut palette drops the small saturated swatches, so the picture would show the wrong colours.
    Returns the size, the colour mode and how many of the 14 colours the picture keeps exactly."""
    from PIL import Image

    img = Image.open(src).convert("RGB")
    lanczos = resample_filter(Image)
    nws_rgb = [tuple(int(h[k:k + 2], 16) for k in (1, 3, 5)) for h in NWS_STEP_HEX]
    for width in widths:
        scaled = img.resize((width, round(img.height * width / img.width)), lanczos)
        coarse = scaled.quantize(colors=256 - len(nws_rgb), method=Image.Quantize.MEDIANCUT)
        palette = bytearray(coarse.getpalette()[:(256 - len(nws_rgb)) * 3])
        for rgb in nws_rgb:
            palette += bytes(rgb)
        palette += bytes(3 * (256 - len(palette) // 3))
        palette_img = Image.new("P", (1, 1))
        palette_img.putpalette(bytes(palette))
        out = scaled.quantize(palette=palette_img, dither=Image.Dither.NONE)
        out.save(dst, format="PNG", optimize=True)
        size = os.path.getsize(dst)
        if size <= limit:
            kept = {rgb for _count, rgb in out.convert("RGB").getcolors(maxcolors=1 << 24)}
            return {"width": out.width, "height": out.height, "bytes": size,
                    "colours": "palette-256, NWS swatch colours kept exact",
                    "nws_colours_exact": sum(1 for rgb in nws_rgb if rgb in kept)}
    raise AssertionError(f"no palette copy of the screenshot fits in {limit} bytes")


def canvas_rgb(page):
    from PIL import Image

    return Image.open(io.BytesIO(page.locator("#cesiumContainer canvas").first.screenshot())).convert("RGB")


class GlobeVolumeBrowserBase(unittest.TestCase):
    """serve.py started with the volume arguments of a subclass. Skips like the other browser checks."""

    volume_args = []
    server = None
    base = None
    results = {}

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed in this Python")
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("Pillow is not installed in this Python")
        if not browser_path():
            raise unittest.SkipTest("Chromium binary not found (set GLOBE_CHROMIUM)")
        if not network_reachable():
            raise unittest.SkipTest("the network the page needs (cdnjs, NWS) is not reachable")
        cls.server = subprocess.Popen([sys.executable, "-B", os.path.join(PROTO, "serve.py"), "--port", "0"]
                                      + cls.volume_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = {}

        def read_port():
            line["text"] = cls.server.stdout.readline()

        reader = threading.Thread(target=read_port, daemon=True)
        reader.start()
        reader.join(30)
        text = line.get("text", "").strip()
        if not text.startswith("PORT="):
            cls.server.kill()
            raise AssertionError(f"serve.py {' '.join(cls.volume_args)} did not print PORT=<n>: {text!r}")
        cls.base = f"http://127.0.0.1:{int(text.split('=')[1])}"
        cls.results = {"volume_args": cls.volume_args}

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server.kill()
            for pipe in (cls.server.stdout, cls.server.stderr):
                if pipe is not None:
                    pipe.close()


class SyntheticVolumeBrowserTests(GlobeVolumeBrowserBase):
    """serve.py's default volume: the synthetic test field, labelled 'synthetic: not weather'."""

    volume_args = []

    def test_legend_toggle_canvas_count_exaggeration_and_swatches(self):
        from playwright.sync_api import sync_playwright

        expected = len(load_fixture(SYNTH_FIXTURE)["voxels"])
        self.results["fixture_voxels"] = expected
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            pending, errors = track_requests(page)
            page.goto(self.base + "/", wait_until="load", timeout=120000)
            page.wait_for_selector("#layer-list .layer", timeout=60000)
            settle_tiles(page, pending, TILES_WAIT_S + 15, self.results, "initial_tiles")

            row = page.evaluate(VOLUME_ROW_JS)
            self.results["volume_row_before"] = row
            self.assertEqual(row["legend"], VOLUME_LEGEND, "the volume legend text is not in the DOM")
            self.assertEqual(row["label"], SYNTH_LABEL)
            self.assertEqual(row["state"], "Unavailable", "a synthetic field must not show as live")
            self.assertFalse(row["toggleDisabled"])
            self.assertFalse(row["checked"], "the storms should start hidden")
            before = page.evaluate("() => window.globeStatus.volume")
            self.results["volume_status_before"] = before
            self.assertEqual(before["drawn"], expected, "the points were not all created")
            self.assertFalse(before["visible"])

            page.click("#zoom-volume")
            settle_tiles(page, pending, 150, self.results, "after_zoom_tiles")
            page.wait_for_timeout(1000)
            hidden = canvas_rgb(page)

            page.check("#toggle-mrms_volume")
            page.wait_for_timeout(2000)
            settle_tiles(page, pending, 60, self.results, "after_toggle_tiles")
            shown = canvas_rgb(page)
            changed = fraction_changed(hidden, shown)
            self.results["volume_pixel_diff"] = {"changed_fraction": round(changed, 4),
                                                 "min_required": VOLUME_MIN_CHANGED}
            self.assertGreater(changed, VOLUME_MIN_CHANGED, "turning the storms on did not change the canvas")
            drawn_text = page.text_content("#volume-drawn")
            self.results["panel_count_text"] = drawn_text
            self.assertEqual(int(re.search(r"([\d,]+) voxels", drawn_text).group(1).replace(",", "")), expected)
            self.assertTrue(page.is_visible("#volume-factor"), "the on-screen exaggeration label is hidden")
            self.assertIn("Vertical exaggeration ×1", page.text_content("#volume-factor"))

            page.uncheck("#toggle-mrms_volume")
            page.wait_for_timeout(2000)
            back = fraction_changed(hidden, canvas_rgb(page))
            self.results["volume_pixel_diff_after_off"] = round(back, 4)
            self.assertLess(back, 0.001, "turning the storms off did not restore the canvas")

            page.check("#toggle-mrms_volume")
            page.check('input[name="vexag"][value="3"]')
            page.wait_for_timeout(1500)
            self.assertIn("×3", page.text_content("#volume-factor"))
            after3 = page.evaluate("() => window.globeStatus.volume")
            self.results["volume_status_3x"] = after3
            self.assertEqual(after3["factor"], 3)
            self.assertEqual(after3["drawn"], expected)
            self.assertGreaterEqual(after3["builds"], 2, "the points were not rebuilt at 3x")

            swatches = page.evaluate(SWATCH_JS)
            self.assertEqual(swatches, [rgb_css(h) for h in NWS_STEP_HEX], "the dBZ swatches are not the NWS steps")
            self.results["swatches_match_nws_steps"] = True
            labels = page.evaluate(SWATCH_LABEL_JS)
            self.assertEqual(labels, NWS_STEP_LABELS, "the dBZ swatch labels are not the Python step labels")
            self.results["swatch_labels_match_python_steps"] = True
            self.assertEqual([e for e in errors if "pageerror" in e], [], "the page raised an error")
            browser.close()
        print("GLOBE_VOLUME_SYNTH_RESULT=" + json.dumps(self.results, sort_keys=True))


class SampleVolumeBrowserTests(GlobeVolumeBrowserBase):
    """--volume fixtures/volume-2025-06-15-sample.json (a relative path, read from the prototype folder)."""

    volume_args = ["--volume", os.path.join("fixtures", SAMPLE_FIXTURE)]

    def test_panel_count_equals_the_fixture_and_the_screenshot_is_saved(self):
        from playwright.sync_api import sync_playwright

        expected = len(load_fixture(SAMPLE_FIXTURE)["voxels"])
        self.results["fixture_voxels"] = expected
        tmp = tempfile.mkdtemp(prefix="globe-volume-")
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            pending, errors = track_requests(page)
            page.goto(self.base + "/", wait_until="load", timeout=120000)
            page.wait_for_selector("#layer-list .layer", timeout=60000)
            settle_tiles(page, pending, TILES_WAIT_S + 15, self.results, "initial_tiles")

            row = page.evaluate(VOLUME_ROW_JS)
            self.results["volume_row_before"] = row
            self.assertEqual(row["legend"], VOLUME_LEGEND)
            self.assertEqual(row["label"], ARCHIVED_LABEL)
            self.assertEqual(row["state"], "Stale", "a 2025 volume must not show as live")

            count_text = page.text_content("#volume-drawn")
            self.results["panel_count_text"] = count_text
            panel_count = int(re.search(r"([\d,]+) voxels", count_text).group(1).replace(",", ""))
            self.assertEqual(panel_count, expected, "the voxel count in the panel is not the fixture's count")

            page.click("#zoom-volume")
            settle_tiles(page, pending, 150, self.results, "after_zoom_tiles")
            page.wait_for_timeout(1000)
            hidden = canvas_rgb(page)
            page.check("#toggle-mrms_volume")
            page.wait_for_timeout(2000)
            settle_tiles(page, pending, 60, self.results, "after_toggle_tiles")
            changed = fraction_changed(hidden, canvas_rgb(page))
            self.results["volume_pixel_diff"] = {"changed_fraction": round(changed, 4),
                                                 "min_required": VOLUME_MIN_CHANGED}
            self.assertGreater(changed, VOLUME_MIN_CHANGED, "turning the storms on did not change the canvas")

            full = os.path.join(tmp, "full.png")
            page.screenshot(path=full)
            shot = write_palette_copy(full, VOLUME_PNG)
            self.results["screenshot"] = shot
            self.assertLessEqual(shot["bytes"], SCREENSHOT_LIMIT)
            self.assertEqual(shot["nws_colours_exact"], len(NWS_STEP_HEX), "the picture lost a swatch colour")

            status = page.evaluate("() => window.globeStatus.volume")
            self.results["volume_status"] = status
            self.assertEqual(status["drawn"], expected)
            self.assertEqual(status["drawnInFile"], expected)
            self.assertEqual(page.evaluate(SWATCH_JS), [rgb_css(h) for h in NWS_STEP_HEX])
            self.assertEqual([e for e in errors if "pageerror" in e], [], "the page raised an error")
            browser.close()
        print("GLOBE_VOLUME_SAMPLE_RESULT=" + json.dumps(self.results, sort_keys=True))


class VolumeDataBlockedBrowserTests(GlobeVolumeBrowserBase):
    """The volume endpoint is blocked in the browser: the row says why, and the rest of the page still works."""

    volume_args = []

    def test_volume_data_blocked_says_why_and_the_panel_still_renders(self):
        from playwright.sync_api import sync_playwright

        with urllib.request.urlopen(self.base + "/api/layers.json", timeout=60) as r:
            expected_rows = len(json.loads(r.read())["layers"])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.route("**/api/volume.json", lambda route: route.abort())
            page.goto(self.base + "/", wait_until="load", timeout=120000)
            page.wait_for_selector("#layer-list .layer", timeout=60000)
            page.wait_for_function("() => !!(window.globeStatus && window.globeStatus.volume"
                                   " && window.globeStatus.volume.error)", timeout=60000)
            drawn = page.text_content("#volume-drawn")
            self.results["blocked_drawn_text"] = drawn
            self.assertIn("could not load", drawn, "the row does not say why nothing is drawn")
            self.assertEqual(page.locator("#layer-list .layer").count(), expected_rows)
            self.assertEqual(page.locator("[data-layer=mrms_volume] .legend").count(), 1)
            self.assertEqual(page.evaluate(SWATCH_JS), [rgb_css(h) for h in NWS_STEP_HEX])
            browser.close()
        print("GLOBE_VOLUME_BLOCKED_RESULT=" + json.dumps(self.results, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
