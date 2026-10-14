"""
Website checks (website/): parsers, failure handling, the built pages and the map label layout.

Everything runs offline. Parsers get NWS/SPC-shaped documents; builds use the labelled sample data
or small fake fetchers that fail on purpose. The live sources are checked separately by the
website workflow (`python -m website.build --require-live` on branch pushes).
"""

import contextlib
import io
import json
import math
import struct
import sys
import tempfile
import unittest
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import build as site  # noqa: E402
from website import sources as src  # noqa: E402
from website.sample import SampleFetcher  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


def feature(fid, event, *, status="Actual", msg="Alert", geometry=None, ends=None, refs=()):
    return {"id": fid, "type": "Feature", "geometry": geometry,
            "properties": {"id": fid, "status": status, "messageType": msg, "event": event,
                           "areaDesc": "Somewhere", "sent": "2026-10-14T14:00:00Z",
                           "ends": ends, "expires": ends,
                           "references": [{"identifier": r} for r in refs]}}


SQUARE = {"type": "Polygon", "coordinates": [[[-110, 45], [-109, 45], [-109, 46], [-110, 46], [-110, 45]]]}


class Alerts(unittest.TestCase):
    def test_sorted_most_urgent_first(self):
        doc = {"features": [
            feature("a", "Wind Advisory", ends="2026-10-14T18:00:00Z"),
            feature("b", "High Wind Warning", ends="2026-10-15T03:00:00Z"),
            feature("c", "Severe Thunderstorm Warning", ends="2026-10-14T16:00:00Z", geometry=SQUARE),
            feature("d", "Special Weather Statement"),
            feature("e", "Winter Storm Watch"),
            feature("f", "Blizzard Warning", ends="2026-10-14T20:00:00Z"),
        ]}
        events = [a["event"] for a in src.parse_alerts(doc)]
        # warnings (convective first, then by end time), then watches, advisories, statements
        self.assertEqual(events, ["Severe Thunderstorm Warning", "Blizzard Warning", "High Wind Warning",
                                  "Winter Storm Watch", "Wind Advisory", "Special Weather Statement"])

    def test_null_geometry_is_kept_not_dropped(self):
        alerts = src.parse_alerts({"features": [feature("z", "Winter Weather Advisory", geometry=None)]})
        self.assertEqual(len(alerts), 1)
        self.assertIsNone(alerts[0]["geometry"])

    def test_tests_cancels_and_replaced_updates_left_out(self):
        doc = {"features": [
            feature("old", "Severe Thunderstorm Warning"),
            feature("new", "Severe Thunderstorm Warning", refs=["old"]),
            feature("t", "Tornado Warning", status="Test"),
            feature("x", "Tornado Warning", msg="Cancel"),
        ]}
        self.assertEqual([a["id"] for a in src.parse_alerts(doc)], ["new"])

    def test_unreadable_response_is_an_error_not_an_empty_list(self):
        for bad in (None, {}, {"features": None}, {"features": "nope"}, {"features": [None]}):
            with self.assertRaises(ValueError):
                src.parse_alerts(bad)
        self.assertEqual(src.parse_alerts({"features": []}), [])

    def test_kind_from_event_name(self):
        self.assertEqual(src.alert_kind("Tornado Emergency"), "warning")
        self.assertEqual(src.alert_kind("Red Flag Warning"), "warning")
        self.assertEqual(src.alert_kind("Fire Weather Watch"), "watch")
        self.assertEqual(src.alert_kind("Dense Fog Advisory"), "advisory")
        self.assertEqual(src.alert_kind("Hydrologic Outlook"), "statement")


class Forecasts(unittest.TestCase):
    def test_hourly_keeps_missing_values_missing(self):
        doc = {"properties": {"updateTime": "2026-10-14T12:00:00Z", "periods": [
            {"startTime": "2026-10-14T09:00:00-06:00", "temperature": 10, "temperatureUnit": "C",
             "windSpeed": "10 to 15 mph", "windDirection": "W", "isDaytime": True,
             "probabilityOfPrecipitation": {"value": None}, "shortForecast": "Sunny"},
            {"startTime": "2026-10-14T10:00:00-06:00", "temperature": None, "windSpeed": "",
             "probabilityOfPrecipitation": {"value": 40}}]}}
        hours, updated = src.parse_hourly(doc)
        self.assertEqual(updated, "2026-10-14T12:00:00Z")
        self.assertEqual(hours[0]["start"], datetime(2026, 10, 14, 15, 0, tzinfo=UTC))
        self.assertEqual(hours[0]["temp_f"], 50)
        self.assertEqual(hours[0]["wind_mph"], 15)          # the higher number of a range
        self.assertIsNone(hours[0]["precip"])
        self.assertIsNone(hours[1]["temp_f"])
        self.assertIsNone(hours[1]["wind_mph"])
        self.assertEqual(hours[1]["precip"], 40)
        with self.assertRaises(ValueError):
            src.parse_hourly({"properties": {"periods": []}})

    def test_gusts_units_and_durations(self):
        kmh = {"properties": {"windGust": {"uom": "wmoUnit:km_h-1", "values": [
            {"validTime": "2026-10-14T15:00:00+00:00/PT3H", "value": 40.2336},
            {"validTime": "2026-10-14T18:00:00+00:00/PT1H", "value": None}]}}}
        g = src.parse_gusts(kmh)
        self.assertEqual(sorted(g), [NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2)])
        self.assertEqual(set(g.values()), {25})
        self.assertNotIn(NOW + timedelta(hours=3), g)      # a null value stays missing
        ms = {"properties": {"windGust": {"uom": "wmoUnit:m_s-1", "values": [
            {"validTime": "2026-10-14T15:00:00+00:00/P1DT1H", "value": 10}]}}}
        g = src.parse_gusts(ms)
        self.assertEqual(len(g), 25)
        self.assertEqual(g[NOW], 22)
        with self.assertRaises(ValueError):
            src.parse_gusts({"properties": {"windGust": {"uom": "wmoUnit:kt", "values": [
                {"validTime": "2026-10-14T15:00:00+00:00/PT1H", "value": 20}]}}})
        self.assertEqual(src.parse_gusts({"properties": {}}), {})

    def test_durations(self):
        self.assertEqual(src.duration_hours("PT6H"), 6)
        self.assertEqual(src.duration_hours("P1DT2H"), 26)
        self.assertEqual(src.duration_hours("PT30M"), 1)
        self.assertEqual(src.duration_hours("junk"), 1)

    def test_flags_use_limits_and_never_flag_or_pass_a_missing_value(self):
        L = src.LIMITS
        self.assertEqual(src.flags_for({"gust_mph": L["gust_mph"]}), [f"Gusts {L['gust_mph']} mph"])
        self.assertEqual(src.flags_for({"gust_mph": L["gust_mph"] - 1}), [])
        self.assertEqual(src.flags_for({"precip": L["pop_pct"]}), [f"{L['pop_pct']}% chance of rain or snow"])
        self.assertEqual(src.flags_for({"temp_f": L["cold_f"]}), [])
        self.assertEqual(src.flags_for({"temp_f": L["cold_f"] - 1}), [f"{L['cold_f'] - 1} °F"])
        self.assertEqual(src.flags_for({"gust_mph": None, "wind_mph": None, "precip": None, "temp_f": None}), [])

    def test_summary_starts_at_the_current_hour(self):
        hours = [{"start": NOW + timedelta(hours=i), "temp_f": 50 + i, "wind_mph": 5, "precip": 0,
                  "gust_mph": None} for i in range(-2, 20)]
        hours[3]["gust_mph"] = 30                              # NOW + 1 h
        for h in hours:
            h["flags"] = src.flags_for(h)
        s = src.summarize(hours, NOW + timedelta(minutes=30))
        self.assertEqual(s["hours"], 12)
        self.assertEqual(s["lo"], 50)                           # the hour that started at NOW
        self.assertEqual(s["gust"], 30)
        self.assertTrue(s["gusts_known"])
        self.assertEqual(s["first_flag"]["start"], NOW + timedelta(hours=1))
        for h in hours:
            h["gust_mph"] = None
        self.assertFalse(src.summarize(hours, NOW)["gusts_known"])

    def test_seven_day_pairs_day_and_night(self):
        def period(name, day, temp, pop=None):
            return {"name": name, "day": day, "temp_f": temp, "precip": pop, "sky": "Sunny" if day else "Clear",
                    "wind": "5 mph", "wind_dir": "W", "detail": "", "start": None}
        rows = src.pair_days([period("Tonight", False, 30), period("Thursday", True, 60, 10),
                              period("Thursday Night", False, 35, 40), period("Friday", True, 58)])
        self.assertEqual([(r["name"], r["hi"], r["lo"], r["precip"]) for r in rows],
                         [("Tonight", None, 30, None), ("Thursday", 60, 35, 40), ("Friday", 58, None, None)])


class StormReports(unittest.TestCase):
    CSV = ("Time,Size,Location,County,State,Lat,Lon,Comments\n"
           "2215,175,2 SE Wibaux,Wibaux,MT,46.96,-104.16,QUARTER TO GOLF BALL (BYZ)\n"
           "2215,175,2 SE Wibaux,Wibaux,MT,46.96,-104.16,DUPLICATE (BYZ)\n"
           "0105,100,6 W Sidney,Richland,MT,47.72,-104.29,(GGW)\n"
           "2300,250,Amarillo,Potter,TX,35.2,-101.8,FAR AWAY (AMA)\n"
           "bad,100,Nowhere,None,MT,47,-108,\n")

    def test_reporting_day_runs_noon_to_noon_utc(self):
        self.assertEqual(src.spc_day_for(datetime(2026, 7, 2, 11, 59, tzinfo=UTC)), date(2026, 7, 1))
        self.assertEqual(src.spc_day_for(datetime(2026, 7, 2, 12, 0, tzinfo=UTC)), date(2026, 7, 2))
        self.assertEqual(src.spc_url(date(2026, 7, 1), "hail"),
                         "https://www.spc.noaa.gov/climo/reports/260701_rpts_filtered_hail.csv")

    def test_hail_sizes_rollover_and_montana_filter(self):
        reps = src.parse_spc(self.CSV, date(2026, 7, 1), "hail")
        self.assertEqual([(r["place"], r["size_in"], r["time"]) for r in reps],
                         [("2 SE Wibaux", 1.75, "2026-07-01T22:15:00Z"), ("6 W Sidney", 1.0, "2026-07-02T01:05:00Z")])

    def test_unknown_wind_stays_unknown(self):
        text = ("Time,Speed,Location,County,State,Lat,Lon,Comments\n"
                "2230,UNK,Glendive,Dawson,MT,47.11,-104.71,TREES DOWN\n2305,61,Terry,Prairie,MT,46.79,-105.25,\n")
        self.assertEqual([r["mph"] for r in src.parse_spc(text, date(2026, 7, 1), "wind")], [None, 61])

    def test_a_page_that_is_not_a_report_file_is_an_error(self):
        with self.assertRaises(ValueError):
            src.parse_spc("<html>Not found</html>", date(2026, 7, 1), "hail")


def tiny_png(width, height):
    """A real, fully transparent PNG of the given size."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00" * (width * 4) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Radar(unittest.TestCase):
    def test_request_is_a_mercator_box_around_montana(self):
        params, w, h = src.radar_request()
        x0, y0, x1, y1 = (float(v) for v in params["bbox"].split(","))
        self.assertEqual((params["layers"], params["srs"], w), ("1", "EPSG:3857", 1400))
        self.assertTrue(x0 < x1 and y0 < y1)
        self.assertAlmostEqual(w / h, (x1 - x0) / (y1 - y0), places=2)

    def test_png_size_and_frame_time(self):
        self.assertEqual(src.png_size(tiny_png(3, 2)), (3, 2))
        self.assertIsNone(src.png_size(b"<html>"))
        with self.assertRaises(ValueError):
            src.parse_radar_time({"features": []})
        ms = int(NOW.timestamp() * 1000)
        self.assertEqual(src.parse_radar_time({"features": [{"attributes": {"idp_validtime": ms}}]}), NOW)


class FakeResponse:
    def __init__(self, status, body=b"{}", ctype="application/json"):
        self.status_code, self.content, self.headers = status, body, {"Content-Type": ctype}
        self.text = body.decode("latin-1")

    def json(self):
        return json.loads(self.content)


class FakeSession:
    def __init__(self, answers):
        self.answers, self.headers, self.calls = list(answers), {}, 0

    def get(self, url, **kw):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


class Fetching(unittest.TestCase):
    def test_server_errors_are_retried_then_reported(self):
        f = src.Fetcher(FakeSession([FakeResponse(503), FakeResponse(200, b'{"ok": 1}')]), pause=0)
        self.assertEqual(f.json("https://api.weather.gov/x"), ({"ok": 1}, None))
        f = src.Fetcher(FakeSession([src.requests.ConnectionError()] * 3), pause=0)
        self.assertEqual(f.json("https://api.weather.gov/x"), (None, "ConnectionError"))
        self.assertEqual(f.s.calls, 3)

    def test_missing_file_is_not_retried(self):
        session = FakeSession([FakeResponse(404)])
        self.assertEqual(src.Fetcher(session, pause=0).text("https://www.spc.noaa.gov/x.csv"),
                         (None, "not published (HTTP 404)"))
        self.assertEqual(session.calls, 1)

    def test_base_map_must_answer_with_a_picture(self):
        page_html = FakeResponse(200, b"<html>maintenance</html>" * 40, "text/html")
        self.assertEqual(src.Fetcher(FakeSession([page_html]), pause=0).image("https://x/tile/6/22/12")[1],
                         "the map service did not return a map picture")
        jpeg = FakeResponse(200, b"\xff\xd8" + b"\0" * 4000, "image/jpeg")
        self.assertIsNone(src.Fetcher(FakeSession([jpeg]), pause=0).image("https://x/tile/6/22/12")[1])
        self.assertEqual(src.BASEMAP_PROBE, (6, 22, 12))
        z, y, x = src.BASEMAP_PROBE                             # the probe tile covers central Montana
        lon = x / 2 ** z * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))
        self.assertTrue(-112.5 <= lon <= -106 and 45 <= lat <= 49, (lat, lon))

    def test_radar_must_be_a_png(self):
        html = FakeResponse(200, b"<html>error</html>", "text/html")
        self.assertEqual(src.Fetcher(FakeSession([html]), pause=0).png(src.RADAR_WMS, {})[1],
                         "the radar service did not return a PNG image")
        png = FakeResponse(200, tiny_png(2, 2), "image/png")
        self.assertEqual(src.png_size(src.Fetcher(FakeSession([png]), pause=0).png(src.RADAR_WMS, {})[0]), (2, 2))


class Contracts(unittest.TestCase):
    def test_every_feed_the_build_uses_is_described(self):
        self.assertEqual(set(src.CONTRACTS),
                         {"alerts", "points", "hourly", "gusts", "daily", "reports", "radar", "basemap"})
        for key, c in src.CONTRACTS.items():
            self.assertEqual(set(c), {"name", "request", "units", "timing", "missing"}, key)
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in c.values()), key)
        self.assertIn("hundredths of an inch", src.CONTRACTS["reports"]["units"])
        self.assertIn("layer 1", src.CONTRACTS["radar"]["request"])


class Formatting(unittest.TestCase):
    def test_times_have_no_leading_zeros_on_any_platform(self):
        self.assertEqual(site.fmt_time("2026-10-14T15:05:00Z"), "Wed 9:05 am MDT")
        self.assertEqual(site.fmt_time("2026-12-02T03:00:00Z", "%a %b %-d %-I %p"), "Tue Dec 1 8 pm")
        self.assertEqual(site.fmt_time(None), "—")
        self.assertEqual(site.strftime(date(2026, 7, 4), "%b %-d"), "Jul 4")


class FailingFetcher:
    """Every request fails, as when the network or every source is down."""

    def json(self, url, params=None):
        return None, "ConnectionError"

    def text(self, url):
        return None, "ConnectionError"

    def png(self, url, params):
        return None, "ConnectionError"

    def image(self, url):
        return None, "ConnectionError"


class SampleWith(SampleFetcher):
    """Sample data with chosen requests failing, plus an optional working radar."""

    def __init__(self, now, fail=(), radar_age_min=None):
        super().__init__(now)
        self.fail, self.radar_age_min = fail, radar_age_min

    def json(self, url, params=None):
        if url == src.RADAR_TIME and self.radar_age_min is not None:
            ms = int((self.now - timedelta(minutes=self.radar_age_min)).timestamp() * 1000)
            return {"features": [{"attributes": {"idp_validtime": ms}}]}, None
        if "alerts-state" in self.fail and url.endswith("/alerts/active") and params and "area" in params:
            return None, "server error (HTTP 503)"
        if "alerts-point" in self.fail and url.endswith("/alerts/active") and params and "point" in params:
            return None, "server error (HTTP 503)"
        if "gusts" in self.fail and "/gridpoints/" in url and not url.endswith("forecast") \
                and not url.endswith("hourly"):
            return None, "server error (HTTP 500)"
        return super().json(url, params)

    def png(self, url, params):
        if self.radar_age_min is None:
            return super().png(url, params)
        _, w, h = src.radar_request()
        return tiny_png(w, h), None


def build_with(fetch, previous=None):
    out = Path(tempfile.mkdtemp(prefix="hailwatch-site-"))
    result = site.build(out, fetch, NOW, previous)
    return out, result


def page(out, name):
    return (out / name).read_text(encoding="utf-8")


class SampleBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-sample-"))
        cls.result = site.build(cls.out, None, NOW, sample=True)

    def test_every_file_is_there(self):
        expected = ["index.html", "reports.html", "about.html", "map-now.html", "map-reports.html",
                    "data/state.json", ".nojekyll", "static/style.css", "static/favicon.svg", "static/icon-180.png",
                    "static/leaflet/leaflet.js", "static/leaflet/leaflet.css", "static/leaflet/images/layers.png",
                    "static/fonts/fonts.css", "static/fonts/atkinson-hyperlegible-next-latin-700-normal.woff2"]
        expected += [f"town/{t['slug']}.html" for t in site.TOWNS]
        missing = [p for p in expected if not (self.out / p).is_file()]
        self.assertEqual(missing, [])

    def test_sample_is_labelled_on_every_page(self):
        pages = ["index.html", "reports.html", "about.html"] + [f"town/{t['slug']}.html" for t in site.TOWNS]
        for p in pages:
            self.assertIn("Sample data.", page(self.out, p), p)
        state = json.loads(page(self.out, "data/state.json"))
        self.assertTrue(state["sample"])

    def test_counts(self):
        r = self.result
        self.assertEqual((r["alerts"], r["alerts_null_geometry"], r["reports"]), (2, 1, 5))
        c = r["content"]
        self.assertEqual(len(c["towns"]), len(site.TOWNS))
        self.assertEqual(c["towns"]["Livingston"]["alerts"], 1)
        self.assertTrue(c["alert_events"][0].startswith("High Wind Warning until"))
        self.assertEqual(sum(c["reports_by_day"].values()), 5)
        json.dumps(r, default=str)                              # the build log prints it
        self.assertEqual(r["towns_with_forecast"], len(site.TOWNS))
        self.assertEqual(r["towns_with_gusts"], len(site.TOWNS))

    def test_maps_load_only_files_from_this_site(self):
        for name in ("map-now.html", "map-reports.html"):
            html = page(self.out, name)
            self.assertIn('"static/leaflet/leaflet.js"', html)
            self.assertNotIn("cdn.", html)
            self.assertNotIn("jquery", html.lower())
            self.assertNotIn("$(", html)                        # Folium's popups need jQuery; ours don't
            self.assertIn("town/billings.html", html)
        for name in ("index.html", "about.html"):
            self.assertNotIn("googleapis", page(self.out, name))

    def test_null_geometry_alert_is_listed_with_a_note(self):
        html = page(self.out, "index.html")
        self.assertIn("Winter Weather Advisory", html)
        self.assertIn("issued by county or zone, so it has no outline on the map", html)

    def test_town_page_marks_values_over_a_limit(self):
        html = page(self.out, "town/livingston.html")
        self.assertIn("High Wind Warning", html)
        self.assertIn("(over limit)", html)
        self.assertIn("Next 7 days", html)

    def test_about_page_lists_every_source(self):
        html = page(self.out, "about.html")
        for c in src.CONTRACTS.values():
            self.assertIn(c["name"], html)

    def test_reports_page_shows_sizes_in_inches_and_unknown_wind(self):
        html = page(self.out, "reports.html")
        self.assertIn("1.75 in", html)
        self.assertIn("unknown", html)
        self.assertIn("No report is not evidence that no hail fell.", html)


class FailureHonesty(unittest.TestCase):
    def test_failed_alert_request_is_never_shown_as_no_alerts(self):
        out, result = build_with(SampleWith(NOW, fail={"alerts-state", "alerts-point"}))
        html = page(out, "index.html")
        self.assertIn("Couldn't load NWS alerts", html)
        self.assertIn("This is not an all-clear.", html)
        self.assertNotIn("No active NWS", html)
        self.assertIn("Alerts not checked", html)
        self.assertFalse(result["status"]["alerts"]["ok"])
        town = page(out, "town/livingston.html")
        self.assertIn("Couldn't check NWS alerts for Livingston", town)
        self.assertNotIn("No active NWS alerts", town)

    def test_last_verified_alerts_stay_up_when_a_refresh_fails(self):
        _, good = build_with(SampleFetcher(NOW))
        previous = {"alerts": {"items": [{"id": "w1", "event": "Severe Thunderstorm Warning", "kind": "warning",
                                          "headline": "", "area": "Yellowstone", "severity": "Severe", "sender": "",
                                          "sent": "2026-10-14T14:40:00Z", "onset": None,
                                          "until": "2026-10-14T16:00:00Z", "description": "", "instruction": "",
                                          "geometry": SQUARE}],
                               "ok": True, "checked": "2026-10-14T14:50:00Z", "last_known": None}}
        out, result = build_with(SampleWith(NOW, fail={"alerts-state"}), previous)
        html = page(out, "index.html")
        self.assertIn("Severe Thunderstorm Warning", html)
        self.assertIn("Below is the last list we verified, from Wed 8:50 am MDT", html)
        state = json.loads(page(out, "data/state.json"))
        self.assertEqual(state["alerts"]["last_known"], "2026-10-14T14:50:00Z")
        self.assertEqual(len(state["alerts"]["items"]), 1)
        # a second failure in a row keeps pointing at the last verified list, not the failed attempt
        out2, _ = build_with(SampleWith(NOW + timedelta(minutes=10), fail={"alerts-state"}), state)
        state2 = json.loads(page(out2, "data/state.json"))
        self.assertEqual(state2["alerts"]["last_known"], "2026-10-14T14:50:00Z")
        self.assertEqual(len(state2["alerts"]["items"]), 1)

    def test_missing_gusts_are_a_dash_and_not_a_pass(self):
        out, result = build_with(SampleWith(NOW, fail={"gusts"}))
        self.assertEqual(result["towns_with_gusts"], 0)
        html = page(out, "index.html")
        self.assertIn("Gust forecast unavailable, so gusts weren't checked.", html)   # template text
        self.assertIn("Gust forecast didn&#39;t load", page(out, "town/billings.html"))   # escaped value

    def test_everything_down_still_builds_and_says_so(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-down-"))
        with mock.patch.object(site.src, "Fetcher", lambda *a, **k: FailingFetcher()), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = site.main(["--out", str(out), "--require-live", "--now", "2026-10-14T15:00:00Z"])
        self.assertEqual(code, 1)
        state = json.loads(page(out, "data/state.json"))
        self.assertEqual({k: v["ok"] for k, v in state["status"].items()},
                         {"alerts": False, "forecasts": False, "reports": False, "radar": False,
                          "basemap": False})
        html = page(out, "index.html")
        self.assertIn("Couldn't load NWS alerts", html)
        self.assertIn("Forecast unavailable.", html)
        self.assertNotIn("No hour reaches", html)
        self.assertIn("Some report files didn't load", page(out, "reports.html"))

    def test_sample_state_is_never_used_as_last_known(self):
        class Prev:
            def json(self, url, params=None):
                return {"sample": True, "alerts": {"items": [1], "ok": True}}, None
        with mock.patch.object(site.src, "Fetcher", lambda *a, **k: Prev()):
            self.assertIsNone(site.load_previous("https://example.invalid/site/"))


class RadarOnTheMap(unittest.TestCase):
    def test_fresh_radar_is_drawn_from_the_saved_picture(self):
        out, result = build_with(SampleWith(NOW, radar_age_min=6))
        self.assertTrue((out / "radar.png").is_file())
        self.assertTrue(result["status"]["radar"]["ok"])
        self.assertIn("radar.png?v=202610141500", page(out, "map-now.html"))
        self.assertIn("Radar: NOAA composite, frame Wed 8:54 am MDT", page(out, "index.html"))

    def test_old_radar_is_shown_with_its_time_but_reported_as_stale(self):
        out, result = build_with(SampleWith(NOW, radar_age_min=40))
        self.assertFalse(result["status"]["radar"]["ok"])
        self.assertEqual(result["status"]["radar"]["detail"], "frame 40 min old")
        self.assertIn("frame Wed 8:20 am MDT", page(out, "index.html"))


class MapLabels(unittest.TestCase):
    """Town labels must not cover each other or another town's dot, at the zoom a map opens at.

    Maps 546 px and wider open at zoom 6 with every town; narrower maps (phones) open at zoom 5 and
    hide the towns marked "minor" in towns.json. Widths are the labels as drawn (13 px bold Atkinson
    Hyperlegible Next plus 6 px padding), measured in Chromium; an unknown name is estimated wide.
    """
    WIDTH = {"Billings": 51.8, "Bozeman": 61.5, "Butte": 38.7, "Glasgow": 57.9, "Glendive": 59.7,
             "Great Falls": 72.5, "Havre": 41.0, "Helena": 48.3, "Kalispell": 59.4, "Lewistown": 69.6,
             "Livingston": 69.2, "Miles City": 67.1, "Missoula": 60.6, "West Yellowstone": 112.6}
    HEIGHT = 18.2

    @staticmethod
    def project(lat, lon, zoom):
        size = 256 * 2 ** zoom
        y = (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * size
        return (lon + 180) / 360 * size, y

    def place(self, zoom, towns):
        s, n, w, e = src.MT_BOX
        (x0, y0), (x1, y1) = self.project(n, w, zoom), self.project(s, e, zoom)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2               # fitBounds centres the box
        out = []
        for t in towns:
            x, y = self.project(t["lat"], t["lon"], zoom)
            x, y = x - cx, y - cy
            lw, h = self.WIDTH.get(t["name"], 6 + 8.5 * len(t["name"])), self.HEIGHT
            side = t.get("label", "right")
            box = {"right": (x + 6, y - h / 2, x + 6 + lw, y + h / 2),
                   "left": (x - 6 - lw, y - h / 2, x - 6, y + h / 2),
                   "top": (x - lw / 2, y - 6 - h, x + lw / 2, y - 6),
                   "bottom": (x - lw / 2, y + 6, x + lw / 2, y + 6 + h)}[side]
            out.append((t["name"], (x - 6, y - 6, x + 6, y + 6), box))
        return out

    @staticmethod
    def overlap(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    def check(self, zoom, half_width, towns):
        placed, problems = self.place(zoom, towns), []
        for i, (name, _, box) in enumerate(placed):
            if box[0] < -half_width or box[2] > half_width:
                problems.append(f"{name} label runs off the map")
            for j, (other, dot, obox) in enumerate(placed):
                if i != j and self.overlap(box, dot):
                    problems.append(f"{name} label covers the {other} dot")
                if j > i and self.overlap(box, obox):
                    problems.append(f"{name} and {other} labels overlap")
        return problems

    def test_desktop_map_every_town(self):
        self.assertEqual(self.check(6, 546 / 2, site.TOWNS), [])

    def test_phone_map_main_towns(self):
        main = [t for t in site.TOWNS if not t.get("minor")]
        self.assertGreaterEqual(len(main), 8)
        self.assertEqual(self.check(5, 288 / 2, main), [])

    def test_label_sides_are_valid(self):
        for t in site.TOWNS:
            self.assertIn(t.get("label", "right"), ("right", "left", "top", "bottom"), t["name"])


if __name__ == "__main__":
    unittest.main()
