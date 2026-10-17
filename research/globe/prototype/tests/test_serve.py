"""Offline unit tests for serve.py: layer states, PNG reader, GOES frame walk, alert geometry,
parallax wording and an offline server. No network and no browser are used.

Run from the prototype folder:  python -m unittest discover -s tests -v
"""
import json
import os
import struct
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
sys.path.insert(0, PROTO)
import serve  # noqa: E402

FIXTURES = os.path.join(PROTO, "fixtures")
PARALLAX_JSON = os.path.normpath(os.path.join(PROTO, "..", "validation-evidence", "parallax.json"))
NOW = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)


def load_fixture_alerts():
    with open(os.path.join(FIXTURES, "nws_alerts_mt_2026-10-17T0255Z.json"), encoding="utf-8") as f:
        return json.load(f)["features"]


def square(lon, lat, d=0.1):
    return {"type": "Polygon", "coordinates": [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d],
                                                  [lon - d, lat + d], [lon - d, lat - d]]]}


def fake_zone_ok(url):
    """Synthetic zone outline (not a real NWS boundary): a small square placed by the zone URL."""
    seed = sum(map(ord, url)) % 50
    return {"type": "Feature", "geometry": square(-110.0 + seed * 0.01, 46.0 + seed * 0.01),
            "properties": {"name": url.rsplit("/", 1)[-1]}}


def fake_zone_fail(url):
    raise serve.FeedError("could not reach api.weather.gov (timeout)")


# ---------------------------------------------------------------------------
# Minimal PNG encoder for the tests (all five filter types, so the reader's unfilter code is exercised)
# ---------------------------------------------------------------------------
BPP = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def encode_png(width, height, rows, colour=6, depth=8, palette=None, trns=None, filters=(0, 1, 2, 3, 4)):
    bpp = BPP[colour]
    raw = bytearray()
    prev = bytearray(width * bpp)
    for y, row in enumerate(rows):
        line = bytearray(b for px in row for b in px)
        kind = filters[y % len(filters)]
        out = bytearray(len(line))
        for i in range(len(line)):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 0:
                pred = 0
            elif kind == 1:
                pred = a
            elif kind == 2:
                pred = b
            elif kind == 3:
                pred = (a + b) >> 1
            else:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            out[i] = (line[i] - pred) & 0xFF
        raw.append(kind)
        raw.extend(out)
        prev = line
    data = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0))
    if palette is not None:
        data += _chunk(b"PLTE", palette)
    if trns is not None:
        data += _chunk(b"tRNS", trns)
    return data + _chunk(b"IDAT", zlib.compress(bytes(raw))) + _chunk(b"IEND", b"")


class LayerStateTests(unittest.TestCase):
    def test_live_within_the_limit(self):
        state, age, text = serve.layer_state(NOW - timedelta(minutes=5), NOW, 15)
        self.assertEqual(state, "live")
        self.assertAlmostEqual(age, 5.0)
        self.assertIn("within the 15-min limit", text)

    def test_live_exactly_at_the_limit(self):
        state, _, _ = serve.layer_state(NOW - timedelta(minutes=15), NOW, 15)
        self.assertEqual(state, "live")

    def test_stale_over_the_limit(self):
        state, age, text = serve.layer_state(NOW - timedelta(minutes=42), NOW, 15)
        self.assertEqual(state, "stale")
        self.assertAlmostEqual(age, 42.0)
        self.assertIn("over the 15-min limit", text)

    def test_unavailable_without_a_valid_time(self):
        state, age, text = serve.layer_state(None, NOW, 15)
        self.assertEqual((state, age), ("unavailable", None))
        self.assertTrue(text.startswith("Data unavailable"))

    def test_off_when_offline_even_with_a_time(self):
        state, age, text = serve.layer_state(NOW, NOW, 15, offline=True)
        self.assertEqual((state, age, text), ("off", None, "Live feeds are off"))

    def test_failed_refresh_keeps_the_last_good_data_as_stale(self):
        state, _, text = serve.layer_state(NOW - timedelta(minutes=3), NOW, 15,
                                           error="could not reach gibs.earthdata.nasa.gov (timeout)", had_good=True)
        self.assertEqual(state, "stale")
        self.assertTrue(text.startswith("Last refresh failed"))
        self.assertIn("last good data", text)

    def test_failed_refresh_with_nothing_good_is_unavailable(self):
        state, _, text = serve.layer_state(NOW - timedelta(minutes=3), NOW, 15, error="HTTP 500 from api.weather.gov",
                                           had_good=False)
        self.assertEqual(state, "unavailable")
        self.assertIn("HTTP 500", text)

    def test_a_time_in_the_future_is_unavailable(self):
        state, _, _ = serve.layer_state(NOW + timedelta(minutes=10), NOW, 15)
        self.assertEqual(state, "unavailable")


class PngStatsTests(unittest.TestCase):
    def test_rgba_opaque_fraction_and_colours_with_every_filter(self):
        width, height = 8, 5
        rows = [[(x * 30 % 256, y * 40 % 256, 128, 255 if x < 4 else 0) for x in range(width)] for y in range(height)]
        stats = serve.png_stats(encode_png(width, height, rows, colour=6))
        self.assertEqual((stats["width"], stats["height"], stats["pixels"]), (8, 5, 40))
        self.assertEqual(stats["opaque_fraction"], 0.5)
        self.assertEqual(stats["distinct_colours"], len({px for row in rows for px in row}))

    def test_rgb_is_fully_opaque(self):
        rows = [[(10, 200, 30)] * 4 for _ in range(3)]
        stats = serve.png_stats(encode_png(4, 3, rows, colour=2))
        self.assertEqual(stats["opaque_fraction"], 1.0)
        self.assertEqual(stats["distinct_colours"], 1)
        self.assertGreater(stats["mean_luma_opaque"], 0)

    def test_palette_with_transparency(self):
        palette = bytes([255, 0, 0, 0, 0, 255])
        trns = bytes([0, 255])  # index 0 transparent, index 1 opaque
        rows = [[(0,), (1,), (1,), (0,)] for _ in range(2)]
        stats = serve.png_stats(encode_png(4, 2, rows, colour=3, palette=palette, trns=trns))
        self.assertEqual(stats["opaque_fraction"], 0.5)

    def test_gray_with_alpha(self):
        rows = [[(100, 255), (100, 0)] * 2 for _ in range(2)]
        stats = serve.png_stats(encode_png(4, 2, rows, colour=4))
        self.assertEqual(stats["opaque_fraction"], 0.5)

    def test_refuses_sixteen_bit_images(self):
        data = encode_png(2, 2, [[(1, 2, 3)] * 2] * 2, colour=2, depth=16)
        with self.assertRaises(ValueError):
            serve.png_stats(data)

    def test_refuses_data_that_is_not_a_png(self):
        with self.assertRaises(ValueError):
            serve.png_stats(b"<html>not an image</html>")


class GoesFrameTests(unittest.TestCase):
    SPEC = serve.GOES_LAYERS[0]

    @staticmethod
    def imagery_png():
        rows = [[(x, y, (x * 7 + y * 3) % 256, 255) for x in range(256)] for y in range(256)]
        return encode_png(256, 256, rows, colour=6, filters=(4,))

    @staticmethod
    def black_png():
        rows = [[(0, 0, 0, 255)] * 256 for _ in range(256)]
        return encode_png(256, 256, rows, colour=6, filters=(0,))

    def test_walks_back_to_the_first_frame_that_is_imagery(self):
        calls = []

        def probe(spec, t):
            calls.append(t)
            if len(calls) < 3:
                return False, {"status": 404, "bytes": 0}
            return True, {"status": 200, "bytes": 1}

        t, steps = serve.find_goes_frame(self.SPEC, NOW, probe)
        self.assertEqual(t, datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc) - timedelta(minutes=20))
        self.assertEqual(len(steps), 3)
        self.assertEqual(calls[1] - calls[0], timedelta(minutes=-10))

    def test_gives_up_after_twelve_steps(self):
        t, steps = serve.find_goes_frame(self.SPEC, NOW, lambda spec, t: (False, {"status": 404}))
        self.assertIsNone(t)
        self.assertEqual(len(steps), serve.PROBE_STEPS)

    def test_stops_when_the_time_budget_is_used(self):
        t, steps = serve.find_goes_frame(self.SPEC, NOW, lambda spec, t: (False, {"status": 404}), budget_s=-1)
        self.assertIsNone(t)
        self.assertEqual(steps, [{"stopped": "probe time budget used"}])

    def test_network_error_is_kept_in_the_steps(self):
        def probe(spec, t):
            raise serve.FeedError("could not reach gibs.earthdata.nasa.gov (timeout)")

        t, steps = serve.find_goes_frame(self.SPEC, NOW, probe, budget_s=60)
        self.assertIsNone(t)
        self.assertEqual(serve.missing_frame_text(steps), "could not reach gibs.earthdata.nasa.gov (timeout)")

    def test_a_200_that_is_black_is_not_imagery(self):
        with mock.patch.object(serve, "http_fetch", return_value=(200, self.black_png())):
            ok, info = serve.goes_probe(self.SPEC, NOW)
        self.assertFalse(ok)
        self.assertEqual(info["content"]["verdict"], "not imagery")

    def test_a_200_with_imagery_passes_the_content_check(self):
        with mock.patch.object(serve, "http_fetch", return_value=(200, self.imagery_png())):
            ok, info = serve.goes_probe(self.SPEC, NOW)
        self.assertTrue(ok)
        self.assertEqual(info["content"]["verdict"], "imagery")

    def test_a_404_is_not_a_frame(self):
        with mock.patch.object(serve, "http_fetch", return_value=(404, b"")):
            ok, info = serve.goes_probe(self.SPEC, NOW)
        self.assertFalse(ok)
        self.assertEqual(info["status"], 404)

    def test_the_probe_tile_covers_montana(self):
        self.assertEqual(serve.PROBE_TILE, (1, 2))
        url_parts = serve.goes_template(self.SPEC, NOW).split("/")
        self.assertEqual(url_parts[-3:], ["{z}", "{y}", "{x}.png"])


class AlertGeometryTests(unittest.TestCase):
    def setUp(self):
        self.raw = load_fixture_alerts()

    def test_fixture_is_the_three_null_geometry_alerts(self):
        self.assertEqual(len(self.raw), 3)
        self.assertTrue(all(f.get("geometry") is None for f in self.raw))

    def test_zone_outlines_make_geometry_source_zone(self):
        zones = serve.ZoneOutlines(fetch=fake_zone_ok)
        budget = {"left": 20}
        features = [serve.alert_feature(f, zones, budget) for f in self.raw]
        self.assertEqual([f["properties"]["geometry_source"] for f in features], ["zone", "zone", "zone"])
        self.assertEqual(features[0]["geometry"]["type"], "MultiPolygon")
        self.assertEqual(features[0]["properties"]["text"], "zone outline")
        self.assertEqual(features[0]["properties"]["zones_matched"], 5)
        self.assertEqual(features[0]["properties"]["zones_outlined"], 5)
        # the marker is the bounding-box centre of the outlines
        self.assertEqual(len(features[0]["properties"]["marker"]), 2)

    def test_no_outline_and_no_centroid_gives_none_with_no_geometry(self):
        zones = serve.ZoneOutlines(fetch=fake_zone_fail)
        budget = {"left": 20}
        features = [serve.alert_feature(f, zones, budget) for f in self.raw]
        for f in features:
            self.assertEqual(f["properties"]["geometry_source"], "none")
            self.assertIsNone(f["geometry"])
            self.assertEqual(f["properties"]["text"], "zone match, outline not loaded")

    def test_a_known_centroid_without_an_outline_gives_a_point(self):
        zones = serve.ZoneOutlines(fetch=fake_zone_fail)
        url = "https://api.weather.gov/zones/forecast/MTZ301"
        zones.centroids[url] = [-107.5, 47.1]
        feature = serve.alert_feature(self.raw[0], zones, {"left": 20})
        self.assertEqual(feature["properties"]["geometry_source"], "none")
        self.assertEqual(feature["geometry"], {"type": "Point", "coordinates": [-107.5, 47.1]})
        self.assertEqual(feature["properties"]["text"], "zone match, outline not loaded")

    def test_some_outlines_loaded_says_partial(self):
        ok_url = "https://api.weather.gov/zones/forecast/MTZ301"

        def fetch(url):
            if url == ok_url:
                return fake_zone_ok(url)
            raise serve.FeedError("HTTP 404 from api.weather.gov")

        feature = serve.alert_feature(self.raw[0], serve.ZoneOutlines(fetch=fetch), {"left": 20})
        self.assertEqual(feature["properties"]["geometry_source"], "zone")
        self.assertEqual(feature["properties"]["text"], "zone outline, partial: 1 of 5 zones")

    def test_a_polygon_alert_is_polygon(self):
        raw = {"id": "urn:test:polygon", "type": "Feature", "geometry": square(-110.0, 46.5, 0.5),
               "properties": {"event": "Severe Thunderstorm Warning", "severity": "Severe", "affectedZones": []}}
        feature = serve.alert_feature(raw, serve.ZoneOutlines(fetch=fake_zone_fail), {"left": 20})
        self.assertEqual(feature["properties"]["geometry_source"], "polygon")
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        self.assertIsNone(feature["properties"]["marker"])
        self.assertEqual(feature["properties"]["style"]["outline"], serve.SEVERITY_COLOUR["Severe"])

    def test_an_alert_with_no_zone_codes_says_so(self):
        raw = {"id": "urn:test:none", "geometry": None, "properties": {"event": "Test", "affectedZones": [],
                                                                        "geocode": {}}}
        feature = serve.alert_feature(raw, serve.ZoneOutlines(fetch=fake_zone_ok), {"left": 20})
        self.assertEqual(feature["properties"]["geometry_source"], "none")
        self.assertIn("cannot be placed", feature["properties"]["text"])

    def test_ugc_codes_are_used_when_affected_zones_are_missing(self):
        raw = {"id": "urn:test:ugc", "geometry": None,
               "properties": {"event": "Test", "affectedZones": [], "geocode": {"UGC": ["MTC111", "MTZ003"]}}}
        seen = []

        def fetch(url):
            seen.append(url)
            return fake_zone_ok(url)

        feature = serve.alert_feature(raw, serve.ZoneOutlines(fetch=fetch), {"left": 20})
        self.assertEqual(seen, ["https://api.weather.gov/zones/county/MTC111",
                                "https://api.weather.gov/zones/forecast/MTZ003"])
        self.assertEqual(feature["properties"]["geometry_source"], "zone")

    def test_a_bad_alert_is_kept_not_dropped(self):
        feature = serve.safe_alert_feature("not an alert", serve.ZoneOutlines(fetch=fake_zone_ok), {"left": 20})
        self.assertEqual(feature["properties"]["geometry_source"], "none")
        self.assertIsNone(feature["geometry"])

    def test_the_per_request_fetch_cap_is_twenty(self):
        urls = [f"https://api.weather.gov/zones/forecast/MTZ{n:03d}" for n in range(1, 26)]
        calls = []

        def fetch(url):
            calls.append(url)
            return fake_zone_ok(url)

        raw = {"id": "urn:test:many", "geometry": None,
               "properties": {"event": "Test", "affectedZones": urls}}
        feature = serve.alert_feature(raw, serve.ZoneOutlines(fetch=fetch), {"left": serve.ZONE_FETCH_CAP})
        self.assertEqual(len(calls), serve.ZONE_FETCH_CAP)
        self.assertEqual(feature["properties"]["zones_matched"], 25)
        self.assertEqual(feature["properties"]["zones_outlined"], serve.ZONE_FETCH_CAP)
        self.assertIn("partial", feature["properties"]["text"])

    def test_outlines_are_cached_between_lookups(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return fake_zone_ok(url)

        zones = serve.ZoneOutlines(fetch=fetch)
        url = "https://api.weather.gov/zones/forecast/MTZ003"
        zones.lookup(url, {"left": 5})
        zones.lookup(url, {"left": 0})  # a cache hit costs no budget
        self.assertEqual(calls, [url])

    def test_a_failed_zone_is_not_asked_again_inside_the_retry_window(self):
        calls = []

        def fetch(url):
            calls.append(url)
            raise serve.FeedError("HTTP 500 from api.weather.gov")

        zones = serve.ZoneOutlines(fetch=fetch)
        url = "https://api.weather.gov/zones/forecast/MTZ003"
        budget = {"left": 5}
        self.assertEqual(zones.lookup(url, budget), (None, None))
        self.assertEqual(zones.lookup(url, budget), (None, None))
        self.assertEqual(len(calls), 1)

    def test_outline_memory_is_bounded_and_the_centroid_survives_eviction(self):
        with mock.patch.object(serve, "ZONE_OUTLINE_MAX", 2):
            urls = [f"https://api.weather.gov/zones/forecast/MTZ{n:03d}" for n in (1, 2, 3)]
            zones = serve.ZoneOutlines(fetch=fake_zone_ok)
            for url in urls:
                zones.lookup(url, {"left": 5})
            self.assertEqual(len(zones.outlines), 2)
            self.assertIn(urls[0], zones.centroids)
            zones.fetch = fake_zone_fail
            zones.failed.clear()
            outline, centroid = zones.lookup(urls[0], {"left": 5})
            self.assertIsNone(outline)
            self.assertIsNotNone(centroid)

    def test_severity_colours(self):
        self.assertEqual(serve.SEVERITY_COLOUR["Severe"], "#ff8b8b")
        self.assertEqual(serve.SEVERITY_COLOUR["Moderate"], "#e0a93c")
        self.assertEqual(serve.DEFAULT_COLOUR, "#e9f0f7")


class SyntheticClassTests(unittest.TestCase):
    """geometry_source classification on fixtures/alerts_classes_synthetic.json: polygon, zone, none."""

    @staticmethod
    def load():
        with open(os.path.join(FIXTURES, "alerts_classes_synthetic.json"), encoding="utf-8") as f:
            return json.load(f)["features"]

    def test_each_class_is_classified(self):
        zones = serve.ZoneOutlines(fetch=fake_zone_ok)
        sources = [serve.alert_feature(f, zones, {"left": 20})["properties"]["geometry_source"] for f in self.load()]
        self.assertEqual(sources, ["polygon", "zone", "none"])

    def test_zone_alert_without_outlines_is_none_and_kept(self):
        feats = [serve.alert_feature(f, serve.ZoneOutlines(fetch=fake_zone_fail), {"left": 20})
                 for f in self.load()]
        self.assertEqual([f["properties"]["geometry_source"] for f in feats], ["polygon", "none", "none"])
        self.assertEqual(feats[1]["properties"]["text"], "zone match, outline not loaded")
        self.assertEqual(feats[2]["properties"]["text"],
                         "no zone codes in the alert, so it cannot be placed on the map")
        self.assertEqual(len(feats), 3)


class AlertsFeedTests(unittest.TestCase):
    """The alerts feed with the NWS response replaced by the fixture: no network."""

    @staticmethod
    def fixture_doc():
        with open(os.path.join(FIXTURES, "nws_alerts_mt_2026-10-17T0255Z.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_zone_failures_keep_every_alert_and_say_why(self):
        with mock.patch.object(serve, "http_json", return_value=self.fixture_doc()):
            svc = serve.Service(fetch_zone=fake_zone_fail)
            value, error, _, _ = svc.alerts.get()
        self.assertIsNone(error)
        self.assertEqual(value["input_count"], 3)
        self.assertEqual(len(value["features"]), 3)
        self.assertEqual(value["counts"], {"polygon": 0, "zone": 0, "none": 3})
        self.assertEqual(len(value["zone_errors"]), 7)  # seven distinct zones named by the three alerts
        self.assertTrue(all("timeout" in e["error"] for e in value["zone_errors"]))

    def test_a_failed_refresh_keeps_the_last_good_alerts_as_stale(self):
        svc = serve.Service(fetch_zone=fake_zone_ok)
        with mock.patch.object(serve, "http_json", return_value=self.fixture_doc()):
            svc.alerts.get()
        with mock.patch.object(serve, "http_json",
                               side_effect=serve.FeedError("could not reach api.weather.gov (timeout)")):
            svc.alerts.tried_at = None  # force a refresh now
            value, error, ok_at, _ = svc.alerts.get()
        self.assertIsNotNone(error)
        self.assertEqual(len(value["features"]), 3)  # the warnings are still there
        layer = serve.alerts_layer((value, error, ok_at, None), serve.utcnow(), offline=False)
        self.assertEqual(layer["state"], "stale")
        self.assertTrue(layer["state_text"].startswith("Last refresh failed"))
        self.assertEqual(len(layer["items"]), 3)

    def test_a_first_failure_with_nothing_good_is_unavailable_and_empty(self):
        with mock.patch.object(serve, "http_json", side_effect=serve.FeedError("HTTP 503 from api.weather.gov")):
            svc = serve.Service(fetch_zone=fake_zone_ok)
            res = svc.alerts.get()
        layer = serve.alerts_layer(res, serve.utcnow(), offline=False)
        self.assertEqual(layer["state"], "unavailable")
        self.assertEqual(layer["items"], [])
        self.assertEqual(layer["counts"], {"polygon": 0, "zone": 0, "none": 0})


class ParallaxWordingTests(unittest.TestCase):
    def test_legend_wording_is_verbatim_from_parallax_json(self):
        with open(PARALLAX_JSON, encoding="utf-8") as f:
            wording = json.load(f)["wording"]["ui_legend_uncorrected_phase1"]
        self.assertEqual(serve.PARALLAX_WORDING, wording)
        self.assertTrue(serve.GOES_LEGEND["goes_east_geocolor"].endswith(wording))
        self.assertTrue(serve.GOES_LEGEND["goes_east_band13"].endswith(wording))


class PlacesFixtureTests(unittest.TestCase):
    def test_places_match_the_brief(self):
        places, provenance = serve.load_places()
        expected = {
            "Billings": (45.7833, -108.5007), "Great Falls": (47.5053, -111.3008),
            "Missoula": (46.8721, -113.9940), "Glasgow": (48.1970, -106.6350), "Miles City": (46.4083, -105.8406),
        }
        self.assertEqual({p["name"]: (p["lat"], p["lon"]) for p in places}, expected)
        self.assertIn("research brief", provenance["source"])

    def test_places_document_is_points(self):
        doc = serve.places_doc(serve.Service(offline=True))
        self.assertEqual(doc["type"], "FeatureCollection")
        self.assertEqual(len(doc["features"]), 5)
        self.assertTrue(all(f["geometry"]["type"] == "Point" for f in doc["features"]))


class OfflineDocumentTests(unittest.TestCase):
    def test_offline_documents_make_no_network_calls(self):
        svc = serve.Service(offline=True)
        with mock.patch.object(serve, "http_fetch", side_effect=AssertionError("network used")):
            layers = serve.layers_doc(svc)
            alerts = serve.alerts_doc(svc)
            radar = serve.radar_doc(svc)
        by_id = {layer["id"]: layer for layer in layers["layers"]}
        for live in ("goes_east_geocolor", "goes_east_band13", "nws_radar", "nws_alerts"):
            self.assertEqual(by_id[live]["state"], "off", live)
            self.assertEqual(by_id[live]["state_text"], "Live feeds are off")
        self.assertIsNone(by_id["goes_east_geocolor"]["tile_template"])
        self.assertIsNone(by_id["nws_radar"]["image_url"])
        self.assertEqual(by_id["usgs_imagery"]["state"], "live")
        self.assertEqual(by_id["bluemarble"]["state"], "live")
        self.assertEqual(by_id["places"]["state"], "live")
        self.assertEqual(alerts["features"], [])
        self.assertEqual(alerts["state"], "off")
        self.assertEqual(radar["state"], "off")
        self.assertTrue(layers["offline"])

    def test_layers_doc_states_the_limits_are_proposals(self):
        doc = serve.layers_doc(serve.Service(offline=True))
        self.assertIn("proposals", doc["limits_note"])
        self.assertIn("D12", doc["limits_note"])


class OfflineServerTests(unittest.TestCase):
    """Starts serve.py with --offline and checks what a browser would receive."""

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen([sys.executable, "-B", os.path.join(PROTO, "serve.py"), "--port", "0",
                                     "--offline"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = {}

        def read_first_line():
            line["text"] = cls.proc.stdout.readline()

        reader = threading.Thread(target=read_first_line, daemon=True)
        reader.start()
        reader.join(30)
        text = line.get("text", "").strip()
        if not text.startswith("PORT="):
            cls.proc.kill()
            raise RuntimeError(f"serve.py did not print its port: {text!r}")
        cls.base = f"http://127.0.0.1:{int(text.split('=')[1])}"

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        for pipe in (cls.proc.stdout, cls.proc.stderr):
            if pipe is not None:
                pipe.close()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=20) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read()

    def test_page_and_scripts_are_served(self):
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b'id="cesiumContainer"', body)
        self.assertIn(b"3D view could not load.", body)
        self.assertIn(b'integrity="sha384-', body)
        for path, kind in (("/globe.js", b"globe.js"), ("/globe.css", b"--storm-900")):
            status, _, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(kind, body)

    def test_layers_json_is_offline(self):
        status, ctype, body = self.get("/api/layers.json")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        doc = json.loads(body)
        self.assertTrue(doc["offline"])
        off = [layer["id"] for layer in doc["layers"] if layer["state"] == "off"]
        self.assertEqual(sorted(off), ["goes_east_band13", "goes_east_geocolor", "nws_alerts", "nws_radar"])

    def test_alerts_radar_and_places_json(self):
        status, _, body = self.get("/api/alerts.json")
        alerts = json.loads(body)
        self.assertEqual((status, alerts["type"], alerts["features"], alerts["state"]), (200, "FeatureCollection", [], "off"))
        status, _, body = self.get("/api/radar.json")
        radar = json.loads(body)
        self.assertEqual((status, radar["state"], radar["image_url"]), (200, "off", None))
        status, _, body = self.get("/api/places.json")
        self.assertEqual(len(json.loads(body)["features"]), 5)

    def test_unknown_paths_are_refused(self):
        self.assertEqual(self.get("/nope")[0], 404)
        self.assertEqual(self.get("/../serve.py")[0], 404)
        self.assertEqual(self.get("/serve.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
