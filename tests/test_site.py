"""
Website checks (website/): parsers, failure handling, the built pages and the town label sides.

Everything runs offline. Parsers get NWS/SPC-shaped documents; builds use the labelled sample data
or small fake fetchers that fail on purpose. The live sources are checked separately by the
website workflow (`python -m website.build --require-live` on branch pushes).
"""

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import build as site  # noqa: E402
from website import gridded as g  # noqa: E402
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

    def test_binary_downloads_send_a_range_and_accept_partial_content(self):
        class Recorder(FakeSession):
            def get(self, url, **kw):
                self.seen = kw.get("headers")
                return super().get(url, **kw)
        session = Recorder([FakeResponse(206, b"GRIB...7777", "binary/octet-stream")])
        data, err = src.Fetcher(session, pause=0).binary("https://noaa-hrrr-bdp-pds.s3.amazonaws.com/x.grib2",
                                                         {"Range": "bytes=10-20"})
        self.assertEqual((data, err), (b"GRIB...7777", None))
        self.assertEqual(session.seen, {"Range": "bytes=10-20"})
        session = FakeSession([FakeResponse(404)])
        self.assertEqual(src.Fetcher(session, pause=0).binary("https://x/y.grib2"), (None, "not published (HTTP 404)"))
        self.assertEqual(session.calls, 1)


class Contracts(unittest.TestCase):
    def test_every_feed_the_build_uses_is_described(self):
        self.assertEqual(set(src.CONTRACTS), {"alerts", "points", "hourly", "gusts", "daily", "reports", "radar",
                                              "forecast_model", "basemap"})
        for key, c in src.CONTRACTS.items():
            self.assertEqual(set(c), {"name", "request", "units", "timing", "missing"}, key)
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in c.values()), key)
        self.assertIn("hundredths of an inch", src.CONTRACTS["reports"]["units"])
        self.assertIn("PrecipRate", src.CONTRACTS["radar"]["request"])
        self.assertIn("hatched", src.CONTRACTS["radar"]["missing"])
        self.assertIn("byte range", src.CONTRACTS["forecast_model"]["request"])
        self.assertIn("model forecast", src.CONTRACTS["forecast_model"]["missing"])


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

    def binary(self, url, headers=None):
        return None, "ConnectionError"


class SampleWith(SampleFetcher):
    """Sample NWS data with chosen requests failing. Its binary() fails, so no radar or forecast."""

    def __init__(self, now, fail=()):
        super().__init__(now)
        self.fail = fail

    def json(self, url, params=None):
        if "alerts-state" in self.fail and url.endswith("/alerts/active") and params and "area" in params:
            return None, "server error (HTTP 503)"
        if "alerts-point" in self.fail and url.endswith("/alerts/active") and params and "point" in params:
            return None, "server error (HTTP 503)"
        if "gusts" in self.fail and "/gridpoints/" in url and not url.endswith("forecast") \
                and not url.endswith("hourly"):
            return None, "server error (HTTP 500)"
        return super().json(url, params)


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
        expected = ["index.html", "reports.html", "about.html", "map.html", "data/map.json",
                    "static/map/map.js", "static/map/map.css", "static/map/basemap.json",
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
        self.assertEqual(r["map"]["precip"]["radar"], 7)
        self.assertGreaterEqual(r["map"]["precip"]["forecast"], 12)
        self.assertEqual(r["map"]["temp"]["frames"], 13)
        self.assertEqual(r["map"]["wind"]["frames"], 13)

    def test_map_page_loads_only_files_from_this_site(self):
        html = page(self.out, "map.html")
        for needed in ("static/leaflet/leaflet.js", "static/leaflet/leaflet.css", "static/map/map.js",
                       "static/map/map.css", "data/map.json", "static/map/basemap.json"):
            self.assertIn(needed, html)
        self.assertNotRegex(html, r'<(script|link|img)[^>]+(src|href)="(https?:)?//')
        self.assertIn("Sample data", html)
        self.assertIn('src="map.html?card=1&amp;layer=precip', page(self.out, "index.html"))
        self.assertIn("overlay=reports", page(self.out, "reports.html"))
        self.assertIn('href="map.html"', page(self.out, "about.html"))           # main navigation
        self.assertIn("map.html?town=livingston", page(self.out, "town/livingston.html"))
        for name in ("index.html", "about.html", "map.html"):
            self.assertNotIn("googleapis", page(self.out, name))

    def test_static_files_keep_their_address_until_they_change(self):
        """?v= on the scripts, stylesheets and basemap is each file's content hash, so the 10-minute
        rebuilds don't make browsers download unchanged code and outlines again; data/map.json and
        the map card, new at every build, keep the build minute."""
        def digest(name):
            return hashlib.sha256((self.out / "static" / name).read_bytes()).hexdigest()[:12]
        html = page(self.out, "map.html")
        for name in ("map/map.js", "map/map.css", "map/basemap.json"):
            self.assertIn(f"static/{name}?v={digest(name)}", html)
        self.assertIn(f"static/style.css?v={digest('style.css')}", page(self.out, "index.html"))
        self.assertEqual(site.asset_versions(site.HERE / "static"), site.asset_versions(self.out / "static"))
        minute = NOW.strftime("%Y%m%d%H%M")
        self.assertIn(f"data/map.json?v={minute}", html)
        self.assertIn(f"map.html?card=1&amp;layer=precip&amp;v={minute}", page(self.out, "index.html"))

    def test_map_page_landmark_and_text_version(self):
        html = page(self.out, "map.html")
        self.assertIn('<main id="app" class="app"', html)               # banners and notes are in a landmark
        self.assertIn("The radar and model pictures have no text version yet.", " ".join(html.split()))
        self.assertIn('content="#fafafa" media="(prefers-color-scheme: light)"', html)   # = the map's background

    def test_map_data_follows_the_contract(self):
        m = json.loads(page(self.out, "data/map.json"))
        self.assertEqual((m["version"], m["sample"], m["tz"]), (1, True, "America/Denver"))
        self.assertEqual(set(m["layers"]), {"precip", "temp", "wind"})
        for key, layer in m["layers"].items():
            times = [f["time"] for f in layer["frames"]]
            self.assertEqual(times, sorted(times), key)
            for f in layer["frames"]:
                self.assertTrue((self.out / f["src"]).is_file(), f["src"])
                self.assertIn(f["kind"], ("radar", "forecast"))
                self.assertTrue(f["source"].startswith("SAMPLE"), f["source"])
                if f["kind"] == "forecast":
                    self.assertIn("HRRR", f["source"])
            for mode, idx in layer["modes"].items():
                self.assertTrue(idx and all(0 <= i < len(layer["frames"]) for i in idx), (key, mode))
                self.assertTrue(0 <= layer["now_index"][mode] < len(idx), (key, mode))
        precip = m["layers"]["precip"]
        radar = [f for f in precip["frames"] if f["kind"] == "radar"]
        forecast = [f for f in precip["frames"] if f["kind"] == "forecast"]
        self.assertEqual(m["now"], radar[-1]["time"])
        self.assertLess(radar[-1]["time"], forecast[0]["time"])          # radar before now, model after
        self.assertEqual(len(m["towns"]), len(site.TOWNS))
        liv = next(t for t in m["towns"] if t["slug"] == "livingston")
        self.assertEqual(liv["alert_ids"], ["sample-high-wind"])
        self.assertTrue(liv["hours"] and all(h["time"].endswith("Z") for h in liv["hours"]))
        self.assertEqual(len(m["alerts"]["items"]), 2)
        self.assertEqual(sum(1 for a in m["alerts"]["items"] if a["geometry"] is None), 1)
        self.assertEqual(len(m["reports"]), 5)
        self.assertTrue({"radar", "forecast", "alerts", "forecasts", "reports"} <= set(m["status"]))

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

    def test_reports_map_key_names_the_forecast_numbers_and_outlines(self):
        """The Storm reports card draws town bubbles and warning outlines beside the reports and hides
        its own legend, so the page's key says what they are (rule 5: forecast is not a report). The
        card shows precipitation, which rings no town, so the key has no ring; the card counts alerts
        without an outline, and the key says where they are listed (rule 6)."""
        html = page(self.out, "reports.html")
        self.assertIn("<li>Town number: NWS forecast temperature, °F</li>", html)
        self.assertNotIn("orange ring", html)
        self.assertIn("Outline: NWS alert area (red warning, orange watch, gold advisory, grey statement)", html)
        self.assertIn('Alerts without an outline (issued by county or zone) are listed on the <a href="index.html">Now page</a>', html)

    def test_reporting_days_start_at_noon_utc_in_montana_time(self):
        self.assertIn("Reporting day starting Wed Oct 14 at 6 am MDT", page(self.out, "reports.html"))
        winter = datetime(2026, 12, 10, 18, 0, tzinfo=UTC)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-winter-"))
        site.build(out, SampleWith(winter), winter)
        html = page(out, "reports.html")
        self.assertIn("Reporting day starting Thu Dec 10 at 5 am MST", html)      # 12:00 UTC in winter
        self.assertNotIn("MDT", html)

    def test_now_page_card_words_match_the_sample_picture(self):
        html = " ".join(page(self.out, "index.html").split())
        self.assertIn('title="Montana map: sample radar, warning outlines and town temperatures"', html)
        self.assertIn("The latest sample radar picture (invented, not NOAA radar), NWS warning outlines and the NWS "
                      'forecast temperature for each town. <a href="map.html">Open the map</a> to play the past hour '
                      "of sample radar and the sample model forecast, or switch to temperature and wind gusts.", html)


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
        html = " ".join(page(out, "index.html").split())
        self.assertIn("Severe Thunderstorm Warning", html)
        # the town checks still worked: what they found joins the last verified list, and says so
        self.assertIn("Below is the last list we verified, from Wed 8:50 am MDT, with 2 alerts the town checks "
                      "found in this update.", html)
        state = json.loads(page(out, "data/state.json"))
        self.assertEqual(state["alerts"]["last_known"], "2026-10-14T14:50:00Z")
        self.assertEqual([a["id"] for a in state["alerts"]["items"]], ["w1", "sample-high-wind", "sample-winter"])
        self.assertNotIn("from_towns", state["alerts"])
        # a second failure in a row keeps pointing at the last verified list, not the failed attempt
        out2, _ = build_with(SampleWith(NOW + timedelta(minutes=10), fail={"alerts-state"}), state)
        state2 = json.loads(page(out2, "data/state.json"))
        self.assertEqual(state2["alerts"]["last_known"], "2026-10-14T14:50:00Z")
        self.assertEqual(len(state2["alerts"]["items"]), 3)
        self.assertNotIn("town checks found", page(out2, "index.html"))   # nothing new this time

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
                          "forecast": False})
        m = json.loads(page(out, "data/map.json"))
        self.assertTrue(all(layer["frames"] == [] for layer in m["layers"].values()))
        self.assertTrue(m["status"]["radar"]["detail"] and m["status"]["forecast"]["detail"])
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


class LateAlerts(SampleFetcher):
    """Sample data, plus extra alert features: `state` in the statewide answer, `points[lat]` in the
    answer for the town at that latitude (point checks run after the statewide request)."""

    def __init__(self, now, state=(), points=None):
        super().__init__(now)
        self.state, self.points = list(state), points or {}

    def json(self, url, params=None):
        doc, err = super().json(url, params)
        if url.endswith("/alerts/active") and params:
            if "area" in params:
                doc["features"] += self.state
            else:
                doc["features"] += self.points.get(params["point"].split(",")[0], [])
        return doc, err


class TownAlertsInTheList(unittest.TestCase):
    """Every alert a town points to is in the statewide list, so the map's town sheet, outlines and
    List, the Now page and state.json all show it (a town sheet once said only "An alert that is
    listed on the Now page", for an alert the list didn't have)."""

    def build(self, fetch):
        out, result = build_with(fetch)
        return out, result, json.loads(page(out, "data/map.json")), json.loads(page(out, "data/state.json"))

    def test_a_warning_issued_while_the_towns_are_checked(self):
        late = feature("late-svr", "Severe Thunderstorm Warning", ends="2026-10-14T16:00:00Z", geometry=SQUARE)
        out, result, m, state = self.build(LateAlerts(NOW, points={"45.7833": [late]}))     # Billings only
        ids = [a["id"] for a in m["alerts"]["items"]]
        self.assertEqual(ids, ["late-svr", "sample-high-wind", "sample-winter"])            # most urgent first
        listed = set(ids)
        for t in m["towns"]:
            self.assertTrue(set(t["alert_ids"]) <= listed, t["name"])
        self.assertEqual(next(t for t in m["towns"] if t["slug"] == "billings")["alert_ids"], ["late-svr"])
        self.assertEqual(m["alerts"]["items"][0]["geometry"], SQUARE)                       # its outline draws
        self.assertEqual([a["id"] for a in state["alerts"]["items"]], ids)                  # next build's last list
        self.assertIn("Severe Thunderstorm Warning", page(out, "index.html"))
        self.assertEqual(result["alerts"], 3)
        self.assertEqual(result["status"]["alerts"]["detail"], "3 active (1 found only by the town checks)")
        self.assertNotIn("town checks found", page(out, "index.html"))   # the statewide list loaded: no note

    def test_a_listed_warning_a_town_check_shows_was_replaced(self):
        old = feature("old-svr", "Severe Thunderstorm Warning", ends="2026-10-14T15:30:00Z", geometry=SQUARE)
        new = feature("new-svr", "Severe Thunderstorm Warning", ends="2026-10-14T16:00:00Z", geometry=SQUARE,
                      refs=["old-svr"])
        _, _, m, _ = self.build(LateAlerts(NOW, state=[old], points={"45.7833": [new]}))
        ids = [a["id"] for a in m["alerts"]["items"]]
        self.assertIn("new-svr", ids)
        self.assertNotIn("old-svr", ids)                   # the update replaced it, as within one answer
        # a town whose own check still returned the old message keeps it listed: its sheet must resolve
        _, _, m, _ = self.build(LateAlerts(NOW, state=[old], points={"45.7833": [new], "45.6624": [old]}))
        ids = [a["id"] for a in m["alerts"]["items"]]
        self.assertTrue({"new-svr", "old-svr"} <= set(ids))
        for t in m["towns"]:
            self.assertTrue(set(t["alert_ids"]) <= set(ids), t["name"])

    def test_statewide_list_failed_with_nothing_verified_before(self):
        out, result, m, state = self.build(SampleWith(NOW, fail={"alerts-state"}))
        html = " ".join(page(out, "index.html").split())
        self.assertIn("Couldn't load NWS alerts", html)
        self.assertIn("Below are the alerts the town checks found in this update. This is not an all-clear.", html)
        self.assertEqual([a["id"] for a in m["alerts"]["items"]], ["sample-high-wind", "sample-winter"])
        self.assertFalse(m["alerts"]["ok"])
        self.assertIsNone(m["alerts"]["last_known"])
        self.assertFalse(result["status"]["alerts"]["ok"])                    # still reported as failed

    def test_the_map_sheet_backstop_names_the_town_page(self):
        js = (site.HERE / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertNotIn("An alert that is listed on the Now page", js)
        self.assertIn("this map update has no details for it. The full forecast page below lists it.", js)


class MapFailures(unittest.TestCase):
    def test_radar_and_forecast_failures_are_reported_not_drawn_as_dry(self):
        out, result = build_with(SampleWith(NOW))          # NWS sample data, but no gridded downloads
        self.assertFalse(result["status"]["radar"]["ok"])
        self.assertFalse(result["status"]["forecast"]["ok"])
        m = json.loads(page(out, "data/map.json"))
        self.assertEqual(m["layers"]["precip"]["frames"], [])
        self.assertFalse(m["status"]["radar"]["ok"])
        self.assertEqual(m["now"], "2026-10-14T15:00:00Z")    # no radar frame: "now" is the build time
        self.assertEqual(len(m["towns"]), len(site.TOWNS))    # the towns and alerts still draw
        html = " ".join(page(out, "index.html").split())    # the Now page's card names what is missing
        self.assertIn('title="Montana map: warning outlines and town temperatures"', html)
        self.assertIn("NWS warning outlines and the NWS forecast temperature for each town. Missing from this "
                      "update: the radar and model pictures. This is not an all-clear. "
                      '<a href="map.html">Open the map</a> for the List of alerts and towns.', html)
        self.assertNotIn("radar estimate", html)


def frames(kind, layer, times, run=None, source=None):
    """Frame entries as build_gridded makes them, without the pictures (the words don't need them)."""
    out = []
    for v in times:
        f = {"time": src._iso(v), "kind": kind, "src": g.frame_src(layer, v, run if kind == "forecast" else None),
             "source": source or (g.RADAR_SOURCE if kind == "radar" else g.MODEL_SOURCE), "nodata": False}
        if kind == "forecast":
            f.update(run=src._iso(run), lead_min=int((v - run) / timedelta(minutes=1)))
        out.append(f)
    return out


def map_layers(radar=True, model=True, now=NOW, radar_age=4, sample=False):
    """data/map.json layers through gridded.assemble: seven radar frames ending radar_age minutes
    before now, then an HRRR run's frames from the radar time (from now without radar or when the
    radar is stale, as build_gridded anchors them)."""
    t0 = now - timedelta(minutes=radar_age)
    anchor = t0 if radar and timedelta(minutes=radar_age) <= g.RADAR_STALE else now
    times = g.forecast_times(anchor)
    run = anchor.replace(minute=0, second=0) - timedelta(hours=2)
    radar_src = g.SAMPLE_RADAR_SOURCE if sample else None
    model_src = g.SAMPLE_MODEL_SOURCE if sample else None
    past = frames("radar", "precip", [t0 - k * g.RADAR_STEP for k in reversed(range(g.RADAR_FRAMES))],
                  source=radar_src) if radar else []
    precip = sorted(set(times["hourly"]) | {v for v in times["quarters"] if v.minute})
    forecast = {"precip": frames("forecast", "precip", precip, run, model_src),
                "temp": frames("forecast", "temp", times["hours13"], run, model_src),
                "wind": frames("forecast", "wind", times["hours13"], run, model_src)} if model else {}
    return g.assemble(past, forecast, anchor if (radar or model) else None, sample)


class MapCard(unittest.TestCase):
    """The words with the Now page's map card (build.map_card) follow what the card shows: the frame
    map.js opens it on (precipitation, 12h, now_index), the outlines and the town numbers."""

    OK = {"radar": {"ok": True}, "forecast": {"ok": True}}
    ALERTS = {"ok": True, "items": [{"id": "w1"}]}
    TOWNS = [{"hours": [{}]}, {"hours": [{}]}]

    def card(self, layers, alerts=None, towns=None, status=None, now=NOW):
        return site.map_card(layers, alerts or self.ALERTS, self.TOWNS if towns is None else towns,
                             status or self.OK, now)

    def test_everything_loaded(self):
        c = self.card(map_layers())
        self.assertEqual(c["title"], "Montana map: latest radar, warning outlines and town temperatures")
        self.assertEqual(c["shown"], "The latest NOAA radar estimate, NWS warning outlines and the NWS forecast "
                                     "temperature for each town.")
        self.assertEqual(c["missing"], "")
        self.assertEqual(c["then"], "to play the past hour of radar and the HRRR model forecast, or switch to "
                                    "temperature and wind gusts")

    def test_radar_failed_the_model_forecast_is_never_called_radar(self):
        layers = map_layers(radar=False)
        idx = layers["precip"]["modes"]["12h"]
        self.assertEqual(layers["precip"]["frames"][idx[0]]["time"], "2026-10-14T16:00:00Z")   # what the card shows
        c = self.card(layers, status={"radar": {"ok": False}, "forecast": {"ok": True}})
        self.assertEqual(c["title"], "Montana map: HRRR model forecast for 10 am, warning outlines and town "
                                     "temperatures")
        self.assertEqual(c["shown"], "The HRRR model forecast for 10 am, NWS warning outlines and the NWS forecast "
                                     "temperature for each town.")
        self.assertEqual(c["missing"], "Missing from this update: NOAA radar. This is not an all-clear.")
        self.assertEqual(c["then"], "to play the HRRR model forecast, or switch to temperature and wind gusts")
        self.assertNotIn("radar estimate", " ".join(c.values()))

    def test_stale_radar_is_still_radar_and_says_how_old(self):
        c = self.card(map_layers(radar_age=46), status={"radar": {"ok": False}, "forecast": {"ok": True}})
        self.assertTrue(c["shown"].startswith("The latest NOAA radar estimate (from 8:14 am, older than usual), "))
        self.assertEqual(c["missing"], "")

    def test_no_pictures_and_failed_alerts_and_forecasts(self):
        c = self.card(map_layers(radar=False, model=False), alerts={"ok": False, "items": []},
                      towns=[{"hours": []}], status={"radar": {"ok": False}, "forecast": {"ok": False}})
        self.assertEqual(c["title"], "Montana map: nothing loaded in this update")
        self.assertEqual(c["shown"], "")
        self.assertEqual(c["missing"], "Missing from this update: the radar and model pictures, NWS warning outlines "
                                       "and town temperatures. This is not an all-clear.")
        self.assertEqual(c["then"], "for the List of alerts and towns")

    def test_last_verified_alerts_and_some_town_forecasts(self):
        c = self.card(map_layers(model=False), alerts={"ok": False, "items": [{"id": "w1"}]},
                      towns=[{"hours": [{}]}, {"hours": []}])
        self.assertEqual(c["shown"], "The latest NOAA radar estimate, the outlines of the NWS alerts listed on this "
                                     "page and the NWS forecast temperature for each town whose forecast loaded.")
        self.assertEqual(c["missing"], "")
        self.assertEqual(c["then"], "to play the past hour of radar")

    def test_sample_pictures_say_they_are_invented(self):
        self.assertTrue(self.card(map_layers(sample=True))["shown"].startswith(
            "The latest sample radar picture (invented, not NOAA radar), "))
        c = self.card(map_layers(radar=False, sample=True))
        self.assertTrue(c["shown"].startswith("The sample model forecast for 10 am (invented, not the HRRR model), "))
        self.assertTrue(c["title"].startswith("Montana map: sample model forecast for 10 am, "))

    def test_the_zone_is_named_when_it_differs_from_the_build_time(self):
        now = datetime(2026, 11, 1, 7, 10, tzinfo=UTC)          # 1:10 am MDT; at 8:00 UTC it is 1 am MST
        c = self.card(map_layers(radar=False, now=now), status={"radar": {"ok": False}, "forecast": {"ok": True}},
                      now=now)
        self.assertTrue(c["shown"].startswith("The HRRR model forecast for 1 am MST, "), c["shown"])

    def test_forecast_only_build(self):
        """The forecast-only state of a real build: the radar bucket fails, the HRRR answers, NWS and
        SPC fail. The Now page's caption and frame title name the model forecast, never radar."""
        def forecast_only(out_dir, get, now, sample=False):
            return map_layers(radar=False, now=now), {
                "radar": {"label": g.LABELS["radar"], "ok": False,
                          "detail": "the radar file list didn't load (server error (HTTP 503))"},
                "forecast": {"label": g.LABELS["forecast"], "ok": True, "detail": "run 7:00 am, 12 hours"}}
        with mock.patch.object(g, "build_gridded", forecast_only):
            out, _ = build_with(FailingFetcher())
        html = " ".join(page(out, "index.html").split())
        self.assertIn('title="Montana map: HRRR model forecast for 10 am"', html)
        self.assertIn('<p class="caption"> The HRRR model forecast for 10 am. Missing from this update: NOAA radar, '
                      "NWS warning outlines and town temperatures. This is not an all-clear. "
                      '<a href="map.html">Open the map</a> to play the HRRR model forecast, or switch to temperature '
                      "and wind gusts. </p>", html)
        self.assertNotIn("radar estimate", html)
        m = json.loads(page(out, "data/map.json"))
        precip = m["layers"]["precip"]
        self.assertEqual(precip["frames"][precip["modes"]["12h"][precip["now_index"]["12h"]]]["time"],
                         "2026-10-14T16:00:00Z")                     # 10 am MDT: the frame the card opens on


class MapLabels(unittest.TestCase):
    """Town label sides in towns.json. Whether a name covers another town's bubble or name, a basemap
    label or a place is tested where the map's geometry is modelled: tools/build_basemap.py
    check_layout, run by tests/test_basemap.py (test_labels_and_places_never_cover_a_bubble_or_each_other).
    """

    def test_label_sides_are_valid(self):
        for t in site.TOWNS:
            self.assertIn(t.get("label", "right"), ("right", "left", "top", "bottom"), t["name"])


if __name__ == "__main__":
    unittest.main()
