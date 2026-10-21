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
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.parse
from datetime import date, datetime, timedelta, timezone, time
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


def reading(minutes_old=10, temp=5.0, wind=16.668, gust=None, gust_qc="Z", wind_unit="wmoUnit:km_h-1",
            direction=190, qc="V", timestamp=True):
    """An NWS /observations/latest document, as KBIL sent one on 2026-10-16 (5 °C, 16.7 km/h from 190°,
    no gust)."""
    p = {"textDescription": "Clear", "elevation": {"unitCode": "wmoUnit:m", "value": 1088},
         "temperature": {"unitCode": "wmoUnit:degC", "value": temp, "qualityControl": qc},
         "windSpeed": {"unitCode": wind_unit, "value": wind, "qualityControl": qc},
         "windGust": {"unitCode": wind_unit, "value": gust, "qualityControl": gust_qc},
         "windDirection": {"unitCode": "wmoUnit:degree_(angle)", "value": direction, "qualityControl": "V"}}
    if timestamp:
        p["timestamp"] = (NOW - timedelta(minutes=minutes_old)).isoformat()
    return {"properties": p}


def station(sid, lon, lat, state="MT", elev=1100):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"stationIdentifier": sid, "name": f"Station {sid}",
                           "elevation": {"unitCode": "wmoUnit:m", "value": elev},
                           "county": f"https://api.weather.gov/zones/county/{state}C029"}}


class StationReadings(unittest.TestCase):
    def test_units_are_converted_and_a_missing_gust_is_no_gust_reported(self):
        r = src.parse_observation(reading(), NOW)
        self.assertAlmostEqual(r["temp"]["value"], 41.0)
        self.assertAlmostEqual(r["wind"]["value"], 10.357, places=2)
        self.assertEqual(r["dir"], "S")
        self.assertIsNone(r["gust"]["value"])
        self.assertTrue(r["no_gust"])                       # beside a measured wind: not a broken sensor
        self.assertEqual((r["temp"]["qc"], r["gust"]["qc"]), ("V", "Z"))
        self.assertEqual(round(r["elev_ft"]), 3570)
        self.assertEqual(r["sky"], "Clear")
        r = src.parse_observation(reading(wind=10, gust=15, wind_unit="wmoUnit:m_s-1"), NOW)
        self.assertAlmostEqual(r["wind"]["value"], 22.37, places=1)
        self.assertAlmostEqual(r["gust"]["value"], 33.55, places=1)
        self.assertFalse(r["no_gust"])

    def test_calm_wind_has_no_direction(self):
        self.assertEqual(src.parse_observation(reading(wind=0, direction=0), NOW)["dir"], "calm")
        self.assertEqual(src.parse_observation(reading(wind=None, gust=None), NOW)["dir"], "")

    def test_readings_older_than_75_minutes_are_stale_not_hidden(self):
        fresh, stale = src.parse_observation(reading(75), NOW), src.parse_observation(reading(76), NOW)
        self.assertTrue(fresh["current"])
        self.assertFalse(stale["current"])
        self.assertEqual(stale["age_min"], 76)
        self.assertAlmostEqual(stale["temp"]["value"], 41.0)    # the value is still there
        self.assertEqual(src.age_words(76), "1 h 16 min ago")
        self.assertEqual(src.age_words(120), "2 h ago")
        self.assertEqual(src.age_words(12), "12 min ago")

    def test_values_that_failed_quality_control_are_withheld_and_kept_raw(self):
        r = src.parse_observation(reading(gust=190.0, gust_qc="X"), NOW)
        self.assertIsNone(r["gust"]["value"])
        self.assertTrue(r["gust"]["withheld"])
        self.assertEqual(r["gust"]["raw"], 190.0)
        self.assertFalse(r["no_gust"])                     # withheld is not "no gust reported"
        r = src.parse_observation(reading(qc="S"), NOW)    # screened values are shown with their flag
        self.assertAlmostEqual(r["temp"]["value"], 41.0)
        self.assertEqual(r["temp"]["qc"], "S")
        self.assertEqual(src.QC_WORDS["S"], "screened")

    def test_an_unknown_unit_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            src.parse_observation(reading(wind_unit="wmoUnit:furlong_fortnight-1"), NOW)

    def test_no_time_or_no_values_is_no_reading(self):
        with self.assertRaises(ValueError):
            src.parse_observation(reading(timestamp=False), NOW)
        with self.assertRaises(ValueError):
            src.parse_observation(reading(temp=None, wind=None, gust=None), NOW)
        with self.assertRaises(ValueError):
            src.parse_observation({"type": "Feature"}, NOW)

    def test_nearest_stations_first_and_never_filtered_by_state(self):
        # West Yellowstone (44.66, -111.10): its nearest stations are across the line in Wyoming (D25)
        doc = {"features": [station("FAR", -110.4, 44.56, "WY"), station("OFAW4", -110.83, 44.46, "WY"),
                            station("MTX", -111.6, 45.0, "MT"), station("NEAR", -111.0, 44.6, "WY"),
                            {"properties": {"stationIdentifier": "NOGEOM"}}]}
        got = src.parse_stations(doc, 44.66, -111.10)
        self.assertEqual([s["id"] for s in got], ["NEAR", "OFAW4", "MTX"])
        self.assertEqual([s["state"] for s in got], ["WY", "WY", "MT"])
        self.assertTrue(all(a["miles"] <= b["miles"] for a, b in zip(got, got[1:])))
        self.assertEqual(round(got[0]["elev_ft"]), 3609)
        with self.assertRaises(ValueError):
            src.parse_stations({"type": "FeatureCollection"}, 44.66, -111.10)

    def test_a_card_quotes_the_nearest_current_reading_with_a_temperature_or_wind(self):
        def s(sid, current, temp=40.0, wind=10.0):
            return {"id": sid, "obs": {"current": current, "temp": {"value": temp}, "wind": {"value": wind}}}
        gust_only = s("ROAD", True, temp=None, wind=None)
        self.assertEqual(src.reading_now([s("A", False), gust_only, s("B", True)])["id"], "B")
        self.assertEqual(src.reading_now([s("A", False), gust_only])["id"], "ROAD")
        self.assertEqual(src.reading_now([{"id": "X", "obs": None}, s("A", False)])["id"], "A")
        self.assertIsNone(src.reading_now([{"id": "X", "obs": None}]))

    def test_the_point_lookup_keeps_the_station_link(self):
        p = {"properties": {"forecast": f"{src.NWS}/gridpoints/BYZ/1,1/forecast",
                            "forecastHourly": f"{src.NWS}/gridpoints/BYZ/1,1/forecast/hourly",
                            "forecastGridData": f"{src.NWS}/gridpoints/BYZ/1,1",
                            "observationStations": f"{src.NWS}/gridpoints/BYZ/1,1/stations"}}
        self.assertEqual(src.parse_point(p)["stations"], f"{src.NWS}/gridpoints/BYZ/1,1/stations")
        p["properties"]["observationStations"] = "https://elsewhere.example/stations"
        self.assertIsNone(src.parse_point(p)["stations"])


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
        self.assertEqual(set(src.CONTRACTS), {"alerts", "points", "hourly", "gusts", "daily", "stations",
                                              "observations", "reports", "radar", "forecast_model", "storm_levels",
                                              "satellite", "basemap", "imagery", "hail_history"})
        for key, c in src.CONTRACTS.items():
            self.assertEqual(set(c), {"name", "request", "units", "timing", "missing"}, key)
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in c.values()), key)
        self.assertIn("hundredths of an inch", src.CONTRACTS["reports"]["units"])
        self.assertIn("PrecipRate", src.CONTRACTS["radar"]["request"])
        self.assertIn("hatched", src.CONTRACTS["radar"]["missing"])
        self.assertIn("byte range", src.CONTRACTS["forecast_model"]["request"])
        self.assertIn("model forecast", src.CONTRACTS["forecast_model"]["missing"])
        self.assertIn("75 minutes", src.CONTRACTS["observations"]["timing"])
        self.assertIn("no gust reported", src.CONTRACTS["observations"]["missing"])
        self.assertIn("withheld", src.CONTRACTS["observations"]["missing"])
        self.assertIn("Never filtered by state", src.CONTRACTS["stations"]["missing"])

    def test_the_satellite_feed_is_an_observation_with_its_limits(self):
        c = src.CONTRACTS["satellite"]
        self.assertIn("observation", c["name"])
        self.assertIn("noaa-goes19.s3.amazonaws.com", c["request"])
        self.assertIn("noaa-goes18", c["request"])
        self.assertIn("not a height, not a hail signal", c["units"])
        self.assertIn("20 to 33 km", c["units"])
        self.assertIn("20 minutes", c["timing"])
        self.assertIn("60 minutes", c["timing"])
        self.assertIn("never drawn as clear sky", c["missing"])
        self.assertIn("Not an all-clear", c["missing"])


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
                and not url.endswith("hourly") and not url.endswith("stations"):
            return None, "server error (HTTP 500)"
        if "stations" in self.fail and "/gridpoints/" in url and url.endswith("/stations"):
            return None, "server error (HTTP 500)"
        if "readings" in self.fail and url.endswith("/observations/latest"):
            return None, "not published (HTTP 404)"
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

    def test_map_json_gives_each_town_its_min_zoom(self):
        """towns.json min_zoom (else 7 for a "minor" town, 5 for the rest) goes to data/map.json, next to
        "minor": the map hides a town below it (map.js townMinZoom)."""
        m = json.loads(page(self.out, "data/map.json"))
        by_slug = {t["slug"]: t for t in m["towns"]}
        for t in site.TOWNS:
            self.assertEqual(by_slug[t["slug"]]["min_zoom"], t.get("min_zoom", 7 if t.get("minor") else 5), t["name"])
            self.assertEqual(by_slug[t["slug"]]["minor"], bool(t.get("minor")), t["name"])
        self.assertEqual({s: by_slug[s]["min_zoom"] for s in ("anaconda", "belgrade", "sidney")},
                         {"anaconda": 8, "belgrade": 9, "sidney": 5})

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

    def test_map_page_tags_load_only_site_files(self):
        # The page's own tags (scripts, stylesheets, icons) name only this site's files. The one exception, the
        # USGS imagery tiles (D32), is not in any tag: map.js asks for them only while Imagery is on, from the
        # address in data-imagery; ImageryBaseMap checks where that address appears.
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
        for key, c in src.CONTRACTS.items():
            if key not in site.STORM_CONTRACTS and key not in site.HAIL_CONTRACTS:   # flag-gated: StormLayers, HailHistory
                self.assertIn(c["name"], html)
        for key in site.STORM_CONTRACTS + site.HAIL_CONTRACTS:
            self.assertNotIn(src.CONTRACTS[key]["name"], html)

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


    def test_observed_now_on_the_town_pages_and_cards(self):
        def text(name):
            return " ".join(page(self.out, name).replace("&nbsp;", " ").split())
        town = text("town/livingston.html")
        self.assertIn("Observed now", town)
        self.assertIn("The latest reading at the 3 nearest NWS weather stations", town)
        self.assertIn("SAMPLE Livingston airport", town)
        self.assertIn("Read at 8:48 am, 12 min ago", town)                      # NOW - 12 min, Montana time
        self.assertIn("2 h 30 min ago · <strong>stale</strong>", town)          # the pass: kept, marked stale
        self.assertIn("gusts failed quality control, so withheld", town)        # the hill's X-flagged gust
        self.assertIn('<span class="obs-word">withheld</span>', town)
        self.assertIn("no gust reported", town)
        self.assertIn("wind screened", town)
        self.assertIn("This town's forecast grid square is at 4,593 ft.", town)    # sample: 1,400 m (SAMPLE_GROUND_M)
        self.assertLess(town.index("Observed now"), town.index("Next 24 hours"))
        wy = text("town/west-yellowstone.html")
        self.assertIn("SAMPLE West Yellowstone airport, WY", wy)                 # across the line, labelled
        glasgow = text("town/glasgow.html")
        self.assertIn("No reading from this station in this update (not published (HTTP 404)).", glasgow)
        now = text("index.html")
        self.assertEqual(now.count('class="tc-now"'), len(site.TOWNS))
        # the sample's station ids carry the town's place in towns.json (SMP + index + station number)
        liv, lew = (next(n for n, t in enumerate(site.TOWNS) if t["slug"] == s) for s in ("livingston", "lewistown"))
        self.assertIn(f"12 min ago · station SMP{liv:02d}0, 2 mi away, 3,445 ft", now)
        # its airport reading is stale, so the card quotes the next station (the hill)
        self.assertIn(f"41 min ago · station SMP{lew:02d}1, 10 mi away", now)
        self.assertIn('gusts <b class="over">41</b> mph', now)     # over the 25 mph placeholder limit
        state = json.loads(page(self.out, "data/state.json"))
        self.assertEqual([s["id"] for s in state["stations"]["livingston"]], [f"SMP{liv:02d}{k}" for k in range(3)])
        hill = state["readings"]["livingston"][1]["obs"]["gust"]
        self.assertEqual((hill["value"], hill["withheld"], hill["raw"], hill["qc"]), (None, True, 190.0, "X"))
        self.assertTrue(self.result["status"]["observations"]["ok"])
        self.assertEqual(self.result["towns_with_readings"], len(site.TOWNS))


class FailureHonesty(unittest.TestCase):
    def test_station_failures_are_never_shown_as_calm(self):
        out, result = build_with(SampleWith(NOW, fail={"stations"}))
        self.assertFalse(result["status"]["observations"]["ok"])
        self.assertEqual(result["status"]["observations"]["detail"],
                         f"0 of {len(site.TOWNS)} towns, 0 with a reading under 75 minutes old")
        town = " ".join(page(out, "town/billings.html").split())
        self.assertIn("Station readings are unavailable in this update. Couldn&#39;t look up the nearest weather "
                      "stations (server error (HTTP 500)). This is not an all-clear.", town)
        self.assertIn("Station readings unavailable in this update.", page(out, "index.html"))
        # with a station list from the last build, the readings still load
        _, good = build_with(SampleFetcher(NOW))
        previous = {"stations": {"billings": [{"id": "SMP000", "name": "SAMPLE Billings airport", "lat": 45.8,
                                               "lon": -108.5, "elev_ft": 3445.0, "miles": 2.4, "state": "MT"}]}}
        out, result = build_with(SampleWith(NOW, fail={"stations"}), previous)
        self.assertIn("station SMP000, 2 mi away", page(out, "index.html").replace("&nbsp;", " "))
        self.assertEqual(result["towns_with_readings"], 1)
        # every station answering 404: each one says so, and the card has no numbers
        out, result = build_with(SampleWith(NOW, fail={"readings"}))
        town = page(out, "town/billings.html")
        self.assertEqual(town.count("No reading from this station in this update (not published (HTTP 404))."), 3)
        self.assertNotIn('class="tc-now"', page(out, "index.html"))
        self.assertFalse(result["status"]["observations"]["ok"])

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
                         {"alerts": False, "forecasts": False, "observations": False, "reports": False,
                          "radar": False, "forecast": False})
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


class StormLayers(unittest.TestCase):
    """Radar echo tops (website/storm.py) behind --storm-layers. Off by default: the default build has no
    storm words, keys or files, and its noscript panel is unchanged. On: every town has a value or a named
    reason, in the Map's List, in the same words in the noscript panel (a browser with JavaScript off) and on
    its town page, and each value names its source and time. Sample data only, so nothing here is live."""

    FORBIDDEN = re.compile(r"\bdry\b|\bno hail\b|(?<!-)\bclear\b|no radar coverage", re.IGNORECASE)
    STORM_WORDS = ("echo top", "radar echo", "mrms reflectivity levels", "storm-list", "storm.js", "data-storm")

    @classmethod
    def setUpClass(cls):
        cls.off = Path(tempfile.mkdtemp(prefix="hailwatch-off-"))
        cls.addClassCleanup(shutil.rmtree, cls.off, True)
        cls.off_result = site.build(cls.off, None, NOW, sample=True)
        cls.on = Path(tempfile.mkdtemp(prefix="hailwatch-on-"))
        cls.addClassCleanup(shutil.rmtree, cls.on, True)
        cls.on_result = site.build(cls.on, None, NOW, sample=True, storm_layers=True)
        cls.env = site.env()                  # the same Jinja escaping the pages get, for the text checks

    def text_copy(self, html):
        """The map page's <noscript> panel: the words a browser with JavaScript off reads. The head has a
        second, style-only noscript, so the panel is the one with the class."""
        panels = [block for block in re.findall(r"<noscript>.*?</noscript>", html, re.S)
                  if 'class="noscript"' in block]
        self.assertEqual(len(panels), 1)
        return panels[0]

    def test_the_default_build_has_no_storm_words_keys_or_files(self):
        for path in self.off.rglob("*"):
            if path.is_file() and path.suffix in (".html", ".json", ".js", ".css"):
                text = path.read_text(encoding="utf-8", errors="replace").lower()
                for word in self.STORM_WORDS:
                    self.assertNotIn(word, text, f"{word!r} in {path.relative_to(self.off)}")
        m = json.loads(page(self.off, "data/map.json"))
        self.assertNotIn("storm", m["status"])
        self.assertTrue(all("storm" not in t for t in m["towns"]))
        self.assertNotIn("storm", json.loads(page(self.off, "data/state.json"))["status"])
        self.assertFalse((self.off / "static" / "map" / "storm.js").exists())
        self.assertNotIn("storm", self.off_result["status"])
        off_panel = self.text_copy(page(self.off, "map.html"))
        on_panel = self.text_copy(page(self.on, "map.html"))
        start = on_panel.index("      <h3>Satellite picture</h3>")     # the flag's sections: satellite, then echo tops
        end = on_panel.index("    </div>\n  </noscript>")
        self.assertEqual(off_panel, on_panel[:start] + on_panel[end:])    # the flag adds only its two sections

    def test_the_default_build_asks_for_no_storm_files(self):
        urls = []
        fetch = SampleFetcher(NOW)
        binary = fetch.binary

        def recording(url, headers=None):
            urls.append(url)
            return binary(url, headers)
        fetch.binary = recording
        out = Path(tempfile.mkdtemp(prefix="hailwatch-off-live-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, fetch, NOW)
        self.assertTrue(urls)                                       # the radar and model are still asked for
        self.assertEqual([u for u in urls if "MergedReflectivityQC" in u], [])

    def test_every_town_has_a_value_or_a_named_reason_in_the_list_and_on_its_page(self):
        m = json.loads(page(self.on, "data/map.json"))
        self.assertEqual(len(m["towns"]), len(site.TOWNS))
        map_html = page(self.on, "map.html")
        self.assertEqual(map_html.count('data-storm="town"'), len(site.TOWNS))
        template = re.search(r'<template id="storm-list">.*?</template>', map_html, re.S).group(0)
        panel = self.text_copy(map_html)                  # the same words for a browser with JavaScript off
        sub = re.search(r'<p class="sub">(.*?)</p>', template, re.S).group(1)
        self.assertIn("<h3>Radar echo tops</h3>", panel)
        self.assertIn(f"<p>{sub}</p>", panel)
        self.assertTrue(self.on_result["status"]["storm"]["ok"], self.on_result["status"]["storm"])
        named = ("Echo top (radar estimate)", "No echo at or above 35 dBZ (radar estimate)",
                 "No radar value (radar estimate;")
        for t in m["towns"]:
            storm = t["storm"]
            text = storm["text"]
            self.assertTrue(text.startswith("SAMPLE, invented values."), text)
            self.assertIn("This is not an all-clear.", text)
            self.assertFalse(self.FORBIDDEN.search(text), text)
            self.assertTrue(any(n in text for n in named), text)
            escaped = self.env.from_string("{{ t }}").render(t=text)
            self.assertIn(escaped, map_html, t["name"])             # the List's copy
            name = self.env.from_string("{{ t }}").render(t=t["name"])
            line = f"<li><strong>{name}.</strong> {escaped}</li>"
            self.assertIn(line, template, t["name"])                # the List's line in the template
            self.assertIn(line, panel, t["name"])                   # the same line in the noscript panel
            self.assertIn(escaped, " ".join(page(self.on, t["url"]).split()), t["name"])   # the town page
            if storm["echo_top_m"] is not None or storm["valid_time_utc"]:
                self.assertIn("radar estimate", text)
                self.assertRegex(text, r"valid \d{1,2}:\d{2} (am|pm) M[DS]T")
            if storm["echo_top_m"] is not None:
                self.assertIn("above sea level", text)
                self.assertIn(f"{storm['echo_top_m']:,} m above sea level", text)
            self.assertIn("MRMS", storm["source"])

    def test_sample_echo_tops_and_the_named_reasons_are_all_present(self):
        m = json.loads(page(self.on, "data/map.json"))
        tops = {t["slug"]: t["storm"]["echo_top_m"] for t in m["towns"]}
        self.assertEqual(tops["billings"], 8000)
        self.assertEqual(sum(1 for v in tops.values() if v is not None), 5)
        nodata = [t["slug"] for t in m["towns"] if t["storm"]["no_data_levels"] == 11]
        self.assertEqual(sorted(nodata), ["kalispell", "west-yellowstone"])
        for t in m["towns"]:
            self.assertEqual(t["storm"]["valid_levels"] + t["storm"]["no_data_levels"], 11, t["name"])

    def test_the_sample_ground_heights_differ_by_town(self):
        m = json.loads(page(self.on, "data/map.json"))
        below = {t["storm"]["below_ground_levels"] for t in m["towns"]}
        self.assertGreater(len(below), 2)                    # 1, 2 and 3 heights below ground in the sample

    def test_the_storm_script_and_the_about_rows_ship_only_with_the_flag(self):
        self.assertIn("static/map/storm.js?v=", page(self.on, "map.html"))
        self.assertTrue((self.on / "static" / "map" / "storm.js").is_file())
        about = page(self.on, "about.html")
        self.assertIn(src.CONTRACTS["storm_levels"]["name"], about)
        self.assertIn("Radar echo tops</strong> are NOAA", about)
        self.assertEqual(self.on_result["status"]["storm"]["label"], "MRMS reflectivity levels")
        self.assertIn("MRMS reflectivity levels", page(self.on, "index.html"))   # the freshness line

    def test_a_town_page_shows_the_radar_text_under_observations(self):
        html = " ".join(page(self.on, "town/billings.html").split())
        self.assertIn('<h2 id="storm-h">Radar echo top</h2>', html)
        self.assertLess(html.index('id="obs-h"'), html.index('id="storm-h"'))
        self.assertLess(html.index('id="storm-h"'), html.index('id="hours-h"'))

    def test_a_failed_storm_feed_is_named_on_every_page_and_never_an_all_clear(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-storm-down-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, SampleFetcher(NOW), NOW, storm_layers=True)     # no downloads: the feed fails
        self.assertFalse(result["status"]["storm"]["ok"])
        self.assertIn("MRMS reflectivity levels problem:", page(out, "index.html"))
        self.assertIn("Radar echo tops problem", page(out, "map.html"))
        m = json.loads(page(out, "data/map.json"))
        for t in m["towns"]:
            self.assertEqual(t["storm"]["status"], "problem", t["name"])
            self.assertTrue(t["storm"]["text"].startswith("Echo top not available: "), t["storm"]["text"])
            self.assertIn("This is not an all-clear.", t["storm"]["text"])
            self.assertIsNone(t["storm"]["echo_top_m"])
        self.assertIn("Echo top not available", " ".join(page(out, "town/billings.html").split()))

    def test_flag_off_has_no_satellite_layer_status_state_key_frames_or_radio(self):
        m = json.loads(page(self.off, "data/map.json"))
        self.assertNotIn("satellite", m["layers"])
        self.assertNotIn("satellite", m["status"])
        self.assertNotIn("satellite", json.loads(page(self.off, "data/state.json"))["status"])
        self.assertNotIn("satellite", self.off_result["status"])
        self.assertNotIn("satellite", self.off_result["map"])
        self.assertNotIn("satellite", self.off_result["content"])
        self.assertEqual(list((self.off / "map" / "frames").glob("satellite-*")), [])
        html = page(self.off, "map.html")
        self.assertNotIn('value="satellite"', html)
        self.assertNotIn("sw-satellite", html)

    def test_flag_off_has_no_satellite_or_band_13_words_in_any_page_or_data_file(self):
        for path in self.off.rglob("*"):
            if not path.is_file() or path.suffix not in (".html", ".json", ".js", ".css", ".svg"):
                continue
            name = path.relative_to(self.off).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            self.assertNotIn("band 13", text, name)
            if path.suffix in (".html", ".json"):      # map.js ships in both builds; its code may name the layer
                self.assertNotIn("satellite", text, name)

    def test_flag_off_ships_no_satellite_asset_and_copies_the_others_unchanged(self):
        def files(root: Path) -> dict:
            return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        built = files(self.off / "static")
        self.assertEqual([n for n in built if "satellite" in n or "goes" in n.lower()], [])
        self.assertNotIn("map/storm.js", built)     # copied only with the flag (build._unbuilt_static)
        expected = files(site.HERE / "static")
        expected.pop("map/storm.js", None)
        self.assertEqual(built, expected)           # every other file is copied byte for byte

    def test_flag_off_asks_for_no_satellite_files(self):
        urls = []
        fetch = SampleFetcher(NOW)
        binary = fetch.binary

        def recording(url, headers=None):
            urls.append(url)
            return binary(url, headers)
        fetch.binary = recording
        out = Path(tempfile.mkdtemp(prefix="hailwatch-off-goes-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, fetch, NOW)
        self.assertTrue(urls)                                       # the radar and model are still asked for
        self.assertEqual([u for u in urls if "noaa-goes" in u or "ABI-L2" in u], [])

    def test_flag_on_draws_one_satellite_picture_under_150_kb(self):
        from PIL import Image
        from website import satellite as sat
        layer = json.loads(page(self.on, "data/map.json"))["layers"].get("satellite")
        self.assertIsNotNone(layer, "data/map.json has no satellite layer")
        self.assertEqual(len(layer["frames"]), 1, "one picture: the newest scan")
        f = layer["frames"][0]
        self.assertEqual(f["kind"], "satellite")
        self.assertTrue(f["src"].startswith("map/frames/satellite-"), f["src"])
        picture = self.on / f["src"]
        self.assertTrue(picture.is_file(), f["src"])
        self.assertLess(picture.stat().st_size, 150_000)
        self.assertEqual(len(list((self.on / "map" / "frames").glob("satellite-*"))), 1)   # no other picture
        with Image.open(picture) as image:
            self.assertEqual(image.size, g.image_size(sat.WIDTH))
        self.assertTrue(f["source"].startswith("SAMPLE"), f["source"])        # a sample build says so
        self.assertEqual((layer["title"], layer["unit"]), ("Satellite", "K"))
        self.assertEqual(layer["modes"], {"12h": [0]})
        self.assertEqual(layer["now_index"], {"12h": 0})
        labels = [e["label"] for e in layer["legend"]]
        self.assertIn("195 K", labels)
        self.assertIn("290 K", labels)
        self.assertIn("invented", layer["legend_note"])
        status = self.on_result["status"].get("satellite")
        self.assertIsNotNone(status, "no satellite status line in the build result")
        self.assertTrue(status["ok"], status)
        self.assertIn("satellite", json.loads(page(self.on, "data/state.json"))["status"])

    def test_flag_on_map_page_has_the_satellite_radio_and_the_same_words_in_the_panel_and_the_list(self):
        html = page(self.on, "map.html")
        self.assertEqual(html.count('<input type="radio" name="layer" value="satellite">'), 1)
        self.assertIn('<span class="choice-text">Satellite</span>', html)
        description = (self.on_result.get("content") or {}).get("satellite")
        self.assertTrue(description, "the build result has no satellite paragraph")
        words = self.env.from_string("{{ t }}").render(t=description)
        panel = self.text_copy(html)
        self.assertIn("<h3>Satellite picture</h3>", panel)
        self.assertIn(f"<p>{words}</p>", panel)
        self.assertLess(panel.index("<h3>Satellite picture</h3>"), panel.index("<h3>Radar echo tops</h3>"))
        template = re.search(r'<template id="storm-list">.*?</template>', html, re.S)
        self.assertIsNotNone(template, "no storm-list template")
        self.assertRegex(template.group(0), r"<h3[^>]*>Satellite picture</h3>")
        self.assertIn(f"<p>{words}</p>", template.group(0))

    def test_flag_on_about_lists_the_satellite_contract_and_the_flag_off_does_not(self):
        about = page(self.on, "about.html")
        c = src.CONTRACTS["satellite"]
        for key in ("name", "request", "units", "timing", "missing"):
            self.assertIn(self.env.from_string("{{ t }}").render(t=c[key]), about, key)
        self.assertIn("not a height and not a hail signal", about)
        self.assertIn("north-west for GOES-East", about)            # the parallax words, on the About page
        self.assertNotIn(c["name"], page(self.off, "about.html"))

    def test_require_live_counts_the_satellite_picture_like_every_other_source(self):
        from website import satellite as sat
        out = Path(tempfile.mkdtemp(prefix="hailwatch-live-check-"))
        self.addCleanup(shutil.rmtree, out, True)
        argv = ["--out", str(out / "site"), "--sample", "--storm-layers", "--require-live",
                "--now", "2026-10-14T15:00:00Z"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(site.main(argv), 0)                    # every source is ok in the sample build
        real = sat.build_satellite

        def stale(out_dir, get, now, sample=False):
            layer, status = real(out_dir, get, now, sample)
            return layer, {**status, "ok": False, "detail": "satellite picture is 25 min old; scan ended 8:58 am"}
        err = io.StringIO()
        with mock.patch.object(sat, "build_satellite", stale), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            self.assertEqual(site.main(argv), 1)
        self.assertIn("Sources that failed or were stale: satellite", err.getvalue())


class ImageryBaseMap(unittest.TestCase):
    """The imagery base map (D32): the one place the browser fetches from off this site. The address is
    build.py's IMAGERY. The Map page reads it from data-imagery and data/map.json carries it; map.js holds no
    address or host name (AGENTS.md rule 4). The default map is the white one, and the card never uses imagery."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-imagery-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        site.build(cls.out, None, NOW, sample=True)

    def test_the_address_is_https_on_one_named_host(self):
        url, host = site.IMAGERY["url"], site.IMAGERY["host"]
        parts = urllib.parse.urlsplit(url)
        self.assertEqual((parts.scheme, parts.netloc), ("https", host))
        self.assertEqual(host, "basemap.nationalmap.gov")                  # USGS The National Map
        self.assertIn("/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}", url)   # the service's order: row, then column
        self.assertEqual(site.IMAGERY["max_zoom"], 16)

    def test_the_address_is_only_in_the_map_page_attribute_and_map_json(self):
        url, host = site.IMAGERY["url"], site.IMAGERY["host"]
        html = page(self.out, "map.html")
        found = re.findall(r"data-imagery='([^']*)'", html)
        self.assertEqual(len(found), 1)
        self.assertEqual(json.loads(found[0]), site.IMAGERY)
        self.assertNotIn(host, html.replace(found[0], ""))                  # the host is named nowhere else on the page
        self.assertEqual(json.loads(page(self.out, "data/map.json"))["imagery"], site.IMAGERY)
        for path in self.out.rglob("*"):
            if not path.is_file() or path.suffix not in (".html", ".json", ".js", ".css"):
                continue
            name = path.relative_to(self.out).as_posix()
            if name not in ("map.html", "data/map.json"):
                self.assertNotIn(url, path.read_text(encoding="utf-8"), name)

    def test_map_js_holds_no_address_or_host_name(self):
        js = (site.HERE / "static" / "map" / "map.js").read_text(encoding="utf-8").lower()
        for needle in ("http:", "https:", "nationalmap", "usgsimagery", ".gov"):
            self.assertNotIn(needle, js, needle)
        # the credit row's words come from build.py (imagery.credit_line and failed_line), not from the script
        for words in ("your ip address", "didn't load from usgs", "outlines and towns are still shown", "imagery: usda"):
            self.assertNotIn(words, js, words)

    def test_the_white_map_is_the_default_and_the_pages_with_the_card_have_no_imagery(self):
        # The card's own page (map.html?card=1) is checked at run time by tools/smoke_map.py
        # (check_card_ignores_imagery); here the pages that embed the card carry no imagery.
        html = page(self.out, "map.html")
        self.assertIn('<legend>Base map</legend>', html)
        self.assertIn('<input type="radio" name="base" value="map" checked>', html)
        self.assertNotIn('value="imagery" checked', html)
        for name in ("index.html", "reports.html"):
            self.assertNotIn("data-imagery", page(self.out, name), name)
            self.assertNotIn('name="base"', page(self.out, name), name)

    def test_the_switch_has_its_privacy_line_and_the_about_page_says_it_is_off_by_default(self):
        html = " ".join(page(self.out, "map.html").split())
        self.assertIn('<input type="radio" name="base" value="imagery"><span class="choice-text">Imagery<small>'
                      "Aerial imagery with roads and names from USGS. Your IP address and the map area you view go to "
                      "USGS while it is on.</small>", html)
        about = " ".join(page(self.out, "about.html").split())
        self.assertIn("Base map imagery", about)
        self.assertIn("in the public domain", about)
        self.assertIn("commercially licensed road data", about)              # the US Topo exception, as USGS states it
        self.assertIn("has not stated a licence for this service's road and name layers", about)
        self.assertIn("USDA, USGS, The National Map", about)
        self.assertIn("The imagery is off unless you switch it on or open a link that switches it on.", about)
        self.assertIn("A link that opens on Imagery loads the tiles as the page opens.", about)

    def test_the_imagery_feed_says_what_it_is_and_where_it_stops(self):
        c = src.CONTRACTS["imagery"]
        self.assertIn("basemap.nationalmap.gov", c["request"])
        self.assertIn("only after they switch the base map to Imagery", c["request"])
        self.assertIn("at small scales a global image", c["units"])          # the service also shows Blue Marble
        self.assertNotIn("satellite", c["units"])                            # the flag-off build names no satellite picture
        self.assertIn("not weather and not evidence", c["units"])
        self.assertIn("shown to zoom 16", c["timing"])
        self.assertIn("Outside the United States, tiles above zoom 8 are blank or missing", c["missing"])

    def test_the_storm_layers_build_has_the_same_switch(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-imagery-on-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, NOW, sample=True, storm_layers=True)
        self.assertIn('<input type="radio" name="base" value="imagery">', page(out, "map.html"))
        self.assertEqual(json.loads(page(out, "data/map.json"))["imagery"], site.IMAGERY)


class ImageryPages(unittest.TestCase):
    """The imagery base map (D32) on the pages, and the helpers the browser check (tools/smoke_map.py) uses. The default
    map page asks no other site for a script, stylesheet, icon or frame; the base map choice sits in the Layers menu
    after the weather layers; the About page carries the privacy line; the credit and the zoom are the design's."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-imagery-pages-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        site.build(cls.out, None, NOW, sample=True)

    def test_the_default_map_page_has_no_off_site_script_link_image_or_frame(self):
        html = page(self.out, "map.html")
        tags = re.findall(r"<(?:script|link|img|iframe)\b[^>]*>", html, re.IGNORECASE)
        self.assertGreater(len(tags), 5)                       # its scripts, stylesheets and icons are all there
        off = [t for t in tags if re.search(r"""\b(?:src|href|srcset)\s*=\s*["']?\s*(?:https?:)?//""", t, re.IGNORECASE)]
        self.assertEqual(off, [])

    def test_the_base_map_choice_is_in_the_layers_menu_after_the_weather_layers(self):
        html = page(self.out, "map.html")
        menu = html[html.index('id="layers"'):]
        menu = menu[:menu.index("</section>")]
        weather_end = menu.index("</fieldset>")           # the weather layers' fieldset closes first
        self.assertLess(menu.index('name="layer"'), weather_end)
        self.assertGreater(menu.index('name="base"'), weather_end)
        self.assertLess(menu.index("<legend>Base map</legend>"), menu.index('name="base"'))

    def test_the_tile_address_is_on_the_element_that_holds_the_map(self):
        tag = re.search(r'<main id="app"[^>]*>', page(self.out, "map.html"))
        self.assertIsNotNone(tag, 'map.html has no <main id="app">')
        self.assertIn("data-imagery=", tag.group(0))

    def test_the_about_page_has_the_privacy_line_the_credit_and_the_public_domain_statement(self):
        about = " ".join(page(self.out, "about.html").split())
        self.assertIn("Your IP address and the map area you view go to USGS while it is on.", about)
        self.assertIn("USDA, USGS, The National Map", about)
        self.assertIn("public domain", about)
        self.assertIn("some exceptions", about)                              # the public-domain statement is qualified
        # USGS's requested acknowledgment, verbatim, with a link to the USGS FAQ it comes from (checked 2026-10-18)
        self.assertIn('"Map services and data available from U.S. Geological Survey, National Geospatial Program."', about)
        self.assertIn("https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map", about)

    def test_the_imagery_config_has_its_fields_and_the_two_words_the_credit_row_shows(self):
        self.assertEqual(set(site.IMAGERY), {"url", "max_zoom", "host", "credit_line", "failed_line"})
        self.assertEqual(site.IMAGERY["credit_line"], "Imagery: USDA, USGS, The National Map. Your IP address and the "
                         "map area you view go to USGS.")
        self.assertEqual(site.IMAGERY["failed_line"], "Imagery didn't load from USGS. Outlines and towns are still shown.")
        self.assertTrue(site.IMAGERY["url"].endswith("/tile/{z}/{y}/{x}"))

    def test_the_contract_names_the_feed_and_its_limits_as_the_design_does(self):
        c = src.CONTRACTS["imagery"]
        self.assertEqual(c["name"], "USGS National Map imagery (ImageryTopo), base map")
        self.assertIn("USGSImageryTopo tiles", c["request"])
        self.assertIn("refreshed in April 2026", c["timing"])                # USGS's service metadata, checked 2026-10-18
        self.assertNotIn("flown", c["timing"])                               # no flight-date source is recorded
        self.assertIn("leaves a plain near-white background", c["missing"])
        self.assertIn("the credit row says that imagery didn't load until a tile loads", c["missing"])
        self.assertIn("roads, lakes, rivers, counties and names stay hidden while Imagery is on", c["missing"])
        self.assertNotIn("white map showing underneath", c["missing"])       # the vector base map is hidden, not under

    def test_the_zoom_is_read_back_from_the_width_of_a_picture_overlay(self):
        class FakePage:
            def __init__(self, width):
                self.width = width

            def evaluate(self, *args):
                return self.width

        data = {"image_bounds": [[43.0, -118.5], [50.5, -101.0]]}      # 17.5 degrees of longitude
        for zoom in (5.0, 6.75, 11.0, 16.0):
            width = 256 * 2 ** zoom * 17.5 / 360                       # the overlay's width on screen at this zoom
            self.assertAlmostEqual(smoke_map().map_zoom(FakePage(width), data), zoom, places=6)
        self.assertIsNone(smoke_map().map_zoom(FakePage(0), data))     # no overlay on the page: no reading

    def test_the_browser_check_refuses_an_imagery_entry_that_is_not_https_on_the_named_host(self):
        smoke = smoke_map()
        good = {"url": site.IMAGERY["url"], "max_zoom": 16, "credit_line": "x", "host": "basemap.nationalmap.gov"}
        self.assertIsNone(smoke.imagery_problem({"imagery": good}))
        self.assertIn("no imagery entry", smoke.imagery_problem({}))
        self.assertIn("not https", smoke.imagery_problem({"imagery": {**good, "url": good["url"].replace("https:", "http:")}}))
        self.assertIn("not https", smoke.imagery_problem({"imagery": {**good, "url": "https://example.org/{z}/{y}/{x}"}}))


def smoke_map():
    """tools/smoke_map.py, loaded by path (it is a script, not a package; its browser code runs only when called)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("smoke_map", ROOT / "tools" / "smoke_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MapLabels(unittest.TestCase):
    """Town label sides in towns.json. Whether a name covers another town's bubble or name, a basemap
    label or a place is tested where the map's geometry is modelled: tools/build_basemap.py
    check_layout, run by tests/test_basemap.py (test_labels_and_places_never_cover_a_bubble_or_each_other).
    """

    def test_label_sides_are_valid(self):
        for t in site.TOWNS:
            self.assertIn(t.get("label", "right"), ("right", "left", "top", "bottom"), t["name"])

    def test_min_zoom_is_a_whole_zoom_from_5_to_9(self):
        for t in site.TOWNS:
            self.assertIn(t.get("min_zoom", 5), range(5, 10), t["name"])
            self.assertIs(type(t.get("min_zoom", 5)), int, t["name"])

    def test_map_js_hides_each_town_below_its_min_zoom(self):
        """map.js reads townMinZoom(t) at the four places that used to test "minor" (the first view,
        the markers, the bubble on screen, the location dot), and the marker gets its zoom class from
        zoomCls, the class map.css already uses for the basemap's names."""
        js = (Path(site.HERE) / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertEqual(js.count("t.minor"), 1, "only the townMinZoom fallback reads minor")
        self.assertIn("function townMinZoom(t)", js)
        self.assertIn("zoomCls(townMinZoom(t))", js)
        self.assertGreaterEqual(js.count("townMinZoom(t)"), 5)     # the definition's use, and the four places


class HailHistory(unittest.TestCase):
    """The five-year hail history (--hail-history; website/hail.py) behind a flag. Off by default: no hail key, files
    or section, and no hail words on the pages. On with --sample: the labelled SAMPLE store on the Map's sheet data,
    the town sections and the About paragraph. A store that doesn't load is a failed source, and the pages still
    build (--require-live then fails). The map script is checked for literals it must not hold (the store's words
    and units live in data/map.json and website/hail.py), for the size rule run in node when node is installed, and
    for the tile list and state lists the browser reads."""

    HAIL_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    HAIL_PAGE_WORDS = ("Hail history, five years", "<h2>Hail history</h2>", 'id="hail-sheet"', 'id="hail-list"',
                       "legend-tap", "data-hail", "Tap or click the map for the five-year hail history")
    # the words that must not appear unless a sentence says "not the same as no hail" or "'no hail'" (the negation)
    FORBIDDEN = re.compile(r"\bdamag\w*|\bdry\b|\bclear\b|\binsurance\b|\beligib\w*|\bconfirm\w*|\bno hail\b", re.I)
    # the sentences the contract row, the About page, DESIGN and D34 share (decision 14), and the display rule (decision 10)
    DAY_SENTENCE = ("A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to 6 am Mountain daylight time, 5 am to "
                    "5 am in winter (the SPC reporting day).")
    CELL_SENTENCE = ("the largest hail over this cell, about 0.7 miles north to south and 0.5 miles east to west, during "
                     "the day")
    NEXT_DAY_SENTENCE = ("The newest day is added by a job that starts at 12:43 UTC and shows here on the next rebuild.")
    DISPLAY_SENTENCE = "Sizes are shown to the hundredth of an inch, rounded down, with the millimetre value exact"

    @classmethod
    def setUpClass(cls):
        cls.off = Path(tempfile.mkdtemp(prefix="hailwatch-hail-off-"))
        cls.on = Path(tempfile.mkdtemp(prefix="hailwatch-hail-on-"))
        cls.addClassCleanup(shutil.rmtree, cls.off, True)
        cls.addClassCleanup(shutil.rmtree, cls.on, True)
        cls.off_result = site.build(cls.off, None, cls.HAIL_NOW, sample=True)
        cls.on_result = site.build(cls.on, None, cls.HAIL_NOW, sample=True, hail_history=True)

    def test_flag_off_has_no_hail_key_files_or_section(self):
        m = json.loads(page(self.off, "data/map.json"))
        self.assertNotIn("hail", m)
        self.assertFalse((self.off / "hail").exists())
        self.assertNotIn("hail_history", self.off_result["status"])
        self.assertNotIn("hail", self.off_result["content"])
        self.assertNotIn("hail_history", json.loads(page(self.off, "data/state.json"))["status"])
        for path in sorted(self.off.rglob("*.html")):
            for words in self.HAIL_PAGE_WORDS:
                self.assertNotIn(words, path.read_text(encoding="utf-8"), f"{words!r} in {path.name}")
        self.assertNotIn("Hail history (radar estimates)", page(self.off, "index.html"))

    def test_flag_on_writes_the_store_and_its_map_block(self):
        from website import hail as hs
        fixture = json.loads((hs.FIXTURE_DIR / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertTrue((self.on / "hail" / "index.json").is_file())
        self.assertTrue((self.on / "hail" / "manifest.json").is_file())
        self.assertEqual(sorted(p.name for p in (self.on / "hail" / "t").iterdir()),
                         sorted(f"{name}.json" for name in fixture["tiles"]))
        status = self.on_result["status"]["hail_history"]
        self.assertTrue(status["ok"])
        self.assertTrue(status["detail"].startswith(
            f"SAMPLE store: {fixture['events']:,} events in {fixture['shards']} shard files"), status["detail"])
        h = json.loads(page(self.on, "data/map.json"))["hail"]
        self.assertEqual(h["state"], "sample")
        self.assertEqual((h["as_of"], h["window"][0], h["d0"]), (fixture["as_of"], fixture["window"][0], "2020-01-01"))
        self.assertEqual(h["tiles"], fixture["tiles"])                  # the browser's outside test reads this list
        self.assertEqual(h["shard"], "hail/t/r{r}_c{c}.json")
        self.assertEqual((h["tenths_per_inch"], h["tenths_per_mm"], h["floor_tenths"]), (254, 10, 64))
        self.assertEqual((h["stale_days"], h["at_zoom"]), (3, 9))
        self.assertEqual(h["grid"]["rows"], 3500)
        self.assertEqual(len(h["classes"]), 6)
        self.assertNotIn("display_caps", h)                             # decision 10: no caps table
        for key in ("title", "lead_many", "lead_one", "lead_none", "lead_none_one", "lead_none_plain", "row",
                    "severe_tag", "large_note", "class_counts_title", "class_count_one", "class_count_many",
                    "what_this_is", "missing", "outside", "unavailable", "source", "sample", "stale", "loading",
                    "fetch_failed"):
            self.assertIn(key, h["words"])
        self.assertEqual(h["words"]["sample"], "SAMPLE data")

    def test_every_listed_tile_has_a_shard_in_the_state_format(self):
        h = json.loads(page(self.on, "data/map.json"))["hail"]
        names = h["tiles"]
        self.assertEqual(names, sorted(set(names)))
        self.assertTrue(names)
        for name in names:
            self.assertRegex(name, r"^r\d{4}_c\d{4}$")
            shard = json.loads((self.on / "hail" / "t" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual((shard["f"], shard["u"], shard["d0"]), ("hail-cells-v1", "tenths of a mm", "2020-01-01"))
            self.assertEqual(f"r{shard['r']:04d}_c{shard['c']:04d}", name)
            state = shard["state"]
            self.assertEqual(state, sorted(set(state)))                 # the Montana keys of the tile, sorted
            self.assertTrue(all(isinstance(k, int) and 0 <= k <= 99 for k in state))
            self.assertTrue({int(k) for k in shard["cells"]} <= set(state))   # cells holds only Montana keys
            for key, rows in shard["cells"].items():
                self.assertTrue(rows, key)                              # a key is in cells only with events
                self.assertEqual(rows, sorted(rows))
                for day, tenths in rows:
                    self.assertTrue(isinstance(day, int) and isinstance(tenths, int))

    def test_a_listed_tile_without_its_shard_file_is_a_failed_store(self):
        from website import hail as hs
        index = json.loads((hs.FIXTURE_DIR / "hail" / "index.json").read_text(encoding="utf-8"))
        out = Path(tempfile.mkdtemp(prefix="hailwatch-tiles-"))
        self.addCleanup(shutil.rmtree, out, True)
        (out / "hail" / "t").mkdir(parents=True)
        first, rest = index["tiles"][0], index["tiles"][1:]
        for name in rest:
            shutil.copy(hs.FIXTURE_DIR / "hail" / "t" / f"{name}.json", out / "hail" / "t" / f"{name}.json")
        with self.assertRaises(hs.HailStoreError) as cm:
            site.hail_tiles(index, out)
        self.assertIn(first, str(cm.exception))
        shutil.copy(hs.FIXTURE_DIR / "hail" / "t" / f"{first}.json", out / "hail" / "t" / f"{first}.json")
        self.assertEqual(site.hail_tiles(index, out), index["tiles"])
        with self.assertRaises(hs.HailStoreError):                      # not sorted
            site.hail_tiles({"tiles": ["r0092_c0214", "r0079_c0199"]}, out)
        with self.assertRaises(hs.HailStoreError):                      # not the name format
            site.hail_tiles({"tiles": ["r79_c199"]}, out)
        with self.assertRaises(hs.HailStoreError):                      # no list at all
            site.hail_tiles({}, out)

    def test_sample_words_show_in_the_town_section_and_the_about_paragraph(self):
        from website import hail as hs            # the source line's words are hail.WORDS; the page must carry them
        fixture = json.loads((hs.FIXTURE_DIR / "hail" / "index.json").read_text(encoding="utf-8"))
        town = page(self.on, "town/billings.html")
        self.assertIn("Hail history, five years", town)
        self.assertIn("SAMPLE data", town)
        self.assertIn("4 days with a radar-estimated hail size of 0.25 in or more between Oct 16, 2021 and "
                      "Oct 15, 2026. Largest: 0.62 in (16.0 mm) on Jul 24, 2022.", town)     # 160 tenths: 0.62, not 0.63
        self.assertIn("<th scope=\"row\">Jul 24, 2022</th>", town)
        self.assertIn("<td class=\"n\">16.0</td>", town)
        self.assertIn("<td>pea to mothball</td>", town)
        self.assertIn("Days with no data, not counted: Jun 8, 2022.", town)
        self.assertIn(hs.WORDS["source"].format(as_of=hs.fmt_date(date.fromisoformat(fixture["as_of"]))), town)
        about = " ".join(page(self.on, "about.html").split())      # the template wraps the sentences across lines
        self.assertIn("<h2>Hail history</h2>", page(self.on, "about.html"))
        self.assertIn("An estimate is not a measurement at the ground and not an inspection.", about)
        self.assertIn("(6.35 mm)", about)
        self.assertIn("12:43 UTC", about)
        self.assertIn(src.CONTRACTS["hail_history"]["name"], about)
        for sentence in (self.DAY_SENTENCE, self.CELL_SENTENCE, self.NEXT_DAY_SENTENCE, self.DISPLAY_SENTENCE):
            self.assertIn(sentence, about)                              # decision 14: the same sentences as the contract
        self.assertNotIn("to a tenth", about)                           # decision 10: no tenths display left

    def test_no_town_page_prints_none_and_a_town_outside_the_sample_says_so(self):
        from website import hail as hs
        pages = sorted((self.on / "town").glob("*.html"))
        self.assertTrue(pages)
        for path in pages:                                   # a missing sentence must never print as None
            self.assertNotIn(">None<", path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(page(self.on, "town/helena.html").count(hs.WORDS["sample_outside"]), 1)   # Helena: not in the sample
        missoula = page(self.on, "town/missoula.html")       # Missoula's tile is not in the sample store
        self.assertEqual(missoula.count(hs.WORDS["sample_outside"]), 1)
        self.assertNotIn(hs.WORDS["sample_outside"], page(self.on, "town/billings.html"))
        self.assertNotIn("Hail history is unavailable", missoula)

    def test_the_build_log_has_a_hail_line_for_every_town(self):
        from website import hail as hs
        hail = self.on_result["content"]["hail"]
        self.assertTrue(hail)
        for name, line in hail.items():                      # the outside line counts too: no null in the log
            self.assertIsInstance(line, str, name)
        self.assertEqual(hail["Helena"], hs.WORDS["sample_outside"])
        self.assertTrue(hail["Billings"].startswith("4 days with"))

    def test_a_build_on_the_fixture_as_a_store_file_prints_no_none_either(self):
        from website import hail as hs
        out = Path(tempfile.mkdtemp(prefix="hailwatch-hail-file-"))
        self.addCleanup(shutil.rmtree, out, True)            # only the folder this test made
        result = site.build(out, None, self.HAIL_NOW, sample=True, hail_history=True, hail_store_path=str(hs.FIXTURE_DIR))
        self.assertTrue(result["status"]["hail_history"]["ok"])
        for path in sorted((out / "town").glob("*.html")):
            self.assertNotIn(">None<", path.read_text(encoding="utf-8"), path.name)
        self.assertIn("Hail history, five years", page(out, "town/billings.html"))

    def test_the_contract_row_carries_the_same_sentences(self):
        row = src.CONTRACTS["hail_history"]
        self.assertIn(self.DISPLAY_SENTENCE, row["units"])
        self.assertIn(self.CELL_SENTENCE, row["units"])
        self.assertIn(self.DAY_SENTENCE, row["timing"])
        self.assertIn(self.NEXT_DAY_SENTENCE, row["timing"])
        self.assertNotIn("to a tenth", " ".join(row.values()))
        self.assertNotIn("0.01-degree", " ".join(row.values()))

    def test_the_contract_row_says_what_happens_when_iowa_state_does_not_answer(self):
        request = " ".join(src.CONTRACTS["hail_history"]["request"].split())
        self.assertIn("the day is rebuilt as the maximum of its two-minute frames. Where Iowa State's copy does not answer, "
                      "the NOAA copy is used alone and the store's index counts those days as skipped.", request)

    def test_the_gate_cell_and_benchland_show_the_decided_sizes(self):
        from website import hail as hs
        index = hs.load_index(hs.FIXTURE_DIR)
        gate = hs.describe(index, hs.cell_events(hs.FIXTURE_DIR, 47.025, -110.135), self.HAIL_NOW, sample=True)
        row = [r for r in gate["rows"] if r["iso"] == "2025-06-15"]
        self.assertEqual(len(row), 1)
        self.assertEqual((row[0]["in"], row[0]["mm"]), ("2.01", "51.3"))
        self.assertIn("Jun 15, 2025: 2.01 in (51.3 mm)", row[0]["text"])          # the gate: row 797, col 1986
        bench = hs.describe(index, hs.cell_events(hs.FIXTURE_DIR, 47.075, -110.015), self.HAIL_NOW, sample=True)
        row = [r for r in bench["rows"] if r["iso"] == "2025-06-15"]
        self.assertEqual(len(row), 1)
        self.assertIn("Jun 15, 2025: 0.72 in (18.5 mm)", row[0]["text"])          # Benchland's own cell: 185 tenths

    def test_the_contract_row_appears_only_with_the_flag(self):
        self.assertIn(src.CONTRACTS["hail_history"]["name"], page(self.on, "about.html"))
        self.assertNotIn(src.CONTRACTS["hail_history"]["name"], page(self.off, "about.html"))
        self.assertIn("hail_history", site.HAIL_CONTRACTS)

    def test_the_map_page_has_the_legend_line_the_sheet_templates_and_the_noscript_words(self):
        on, off = page(self.on, "map.html"), page(self.off, "map.html")
        self.assertIn('<p class="legend-tap">Tap or click the map for the five-year hail history at that spot</p>', on)
        self.assertIn('<template id="hail-sheet">', on)
        self.assertIn('<template id="hail-list">', on)
        self.assertIn("Each town's page has its five-year hail history", on)
        self.assertIn("Hail history didn't load", (ROOT / "website" / "templates" / "map.html").read_text(encoding="utf-8"))
        self.assertNotIn("legend-tap", off)
        self.assertNotIn("hail-sheet", off)
        self.assertNotIn("Each town's page has its five-year hail history", off)
        self.assertIn("Hail history (radar estimates)", page(self.on, "index.html"))

    def test_the_hail_styles_are_on_the_map_page_only_with_the_flag(self):
        # The sheet's and the legend's rules are a style block that only a --hail-history build writes. The shared
        # map.css is the same file in every build, so the default build's static files are the ones it was before.
        source_css = (ROOT / "website" / "static" / "map" / "map.css").read_text(encoding="utf-8")
        self.assertNotIn(".sheet-body .hail-days", source_css)
        self.assertNotIn(".legend-tap", source_css)
        self.assertEqual((self.off / "static" / "map" / "map.css").read_bytes(),
                         (ROOT / "website" / "static" / "map" / "map.css").read_bytes())
        on, off = page(self.on, "map.html"), page(self.off, "map.html")
        self.assertIn(".sheet-body .hail-days:not([hidden])", on)
        self.assertIn(".legend-2col .legend-tap", on)
        self.assertNotIn("hail-days", off)
        self.assertNotIn(".legend-tap", off)

    def test_the_about_page_says_a_day_with_no_radar_estimate_is_not_no_hail(self):
        about = " ".join(page(self.on, "about.html").split())      # the template wraps the sentence across two lines
        self.assertIn("A day with no radar estimate is not the same as no hail: radar misses some hail, and a day with "
                      "no file is listed and not counted.", about)
        self.assertNotIn("No radar estimate on a day", about)
        self.assertNotIn("A day with no radar estimate", page(self.off, "about.html"))

    def test_the_about_page_puts_days_not_listed_after_the_estimate_sentence(self):
        about = " ".join(page(self.on, "about.html").split())
        sentence = "Days not listed have no radar estimate of 0.25 in or more; that is not the same as no hail."
        self.assertIn(sentence, about)
        estimate = about.index("An estimate is not a measurement at the ground and not an inspection.")
        self.assertLess(estimate, about.index(sentence))
        self.assertLess(about.index(sentence), about.index("The newest day is added by a job"))
        self.assertNotIn("Days not listed", page(self.off, "about.html"))

    def test_map_script_holds_no_threshold_unit_class_word_or_sentence(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        for literal in ("25.4", "254", "6.35"):
            self.assertNotIn(literal, js)
        for name in ("display_caps", "display_hundredths", "hailHundredths"):   # decision 10: the caps are gone
            self.assertNotIn(name, js)
        self.assertIn("Math.floor(t * 100 / h.tenths_per_inch) / 100", js)     # the floor rule, from the data's divisor
        from website import hail as hs
        strings = [c["word"] for c in hs.CLASSES] + list(hs.WORDS.values()) + list(site.HAIL_SITE_WORDS.values())
        for text in strings:
            if "{" not in text:                       # templates are checked as their fixed text below
                self.assertNotIn(text, js, text)
            else:
                for part in re.split(r"\{\w+\}", text):
                    if len(part) > 25:                # a long run of a template's own words
                        self.assertNotIn(part, js, part)

    def test_the_map_script_rounds_sizes_down_to_the_hundredth(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sizes in Chromium")
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        parts = []
        for name in ("hailInches", "hailMm"):
            match = re.search(r"^  function %s\(h, t\) \{.*\}$" % name, js, re.M)
            self.assertIsNotNone(match, name)
            parts.append(match.group(0))
        script = "\n".join(parts) + (
            "\nconst h = { tenths_per_inch: 254, tenths_per_mm: 10 };"
            "\nconst cases = [513, 185, 253, 190, 1015, 254, 1016, 64];"
            "\nconsole.log(JSON.stringify(cases.map(t => [hailInches(h, t), hailMm(h, t)])));")
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(out.stdout), [["2.01", "51.3"], ["0.72", "18.5"], ["0.99", "25.3"], ["0.74", "19.0"],
                                                  ["3.99", "101.5"], ["1.00", "25.4"], ["4.00", "101.6"], ["0.25", "6.4"]])

    def test_the_hail_part_of_the_map_script_reads_no_polygon_and_no_basemap(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        section = js[js.index("hail history at a spot (--hail-history builds)"):js.index("card mode (inside other pages)")]
        for word in ("basemap", "polygon", "geometry"):
            self.assertNotIn(word, section.lower())

    def test_the_map_script_gives_a_sample_build_its_own_outside_words(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        open_hail = js[js.index("function openHail("):js.index("function onHailClick(")]
        self.assertIn('var outside = h.state === "sample" ? h.words.sample_outside : h.words.outside;', open_hail)
        self.assertEqual(open_hail.count('hailShow(h, "outside", outside)'), 2)   # a tile the list lacks; a key outside the state
        self.assertIn('if (!cell) return hailShow(h, "outside", h.words.outside);', open_hail)   # off the grid: outside for certain

    def test_the_sheet_labels_every_state_of_a_sample_build(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        show = js[js.index("function hailShow("):js.index("function openHail(")]
        self.assertIn('if (h.state === "sample") {', show)
        self.assertIn('tag.className = "sample-tag";', show)
        self.assertIn("tag.textContent = h.words.sample;", show)

    def test_every_placeholder_is_filled_by_the_map_script(self):
        from website import hail as hs
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        section = js[js.index("hail history at a spot (--hail-history builds)"):js.index("card mode (inside other pages)")]
        names = set()
        for text in list(hs.WORDS.values()) + list(site.HAIL_SITE_WORDS.values()):
            names |= set(re.findall(r"\{(\w+)\}", text))
        self.assertTrue(names)
        for name in sorted(names):
            self.assertRegex(section, r"[\"']?\b%s\b[\"']?\s*:" % re.escape(name), f"{{{name}}} is not filled")

    def test_the_new_words_say_no_forbidden_term_and_no_dash(self):
        from website import hail as hs
        texts = list(hs.WORDS.values()) + list(site.HAIL_SITE_WORDS.values()) + list(
            src.CONTRACTS["hail_history"].values())
        for text in texts:
            self.assertNotIn("\u2014", text)        # no em dash
            self.assertNotIn("\u2013", text)        # no en dash
            rest = text.replace("not the same as no hail", "").replace("'no hail'", "")
            self.assertIsNone(self.FORBIDDEN.search(rest), text)

    def test_the_build_flag_adds_only_the_hail_key_to_map_data(self):
        off = set(json.loads(page(self.off, "data/map.json")))
        on = set(json.loads(page(self.on, "data/map.json")))
        self.assertEqual(on - off, {"hail"})
        self.assertEqual(off - on, set())

    def test_a_store_that_does_not_load_marks_the_source_failed_and_the_pages_still_build(self):
        missing_dir = Path(tempfile.mkdtemp(prefix="hailwatch-missing-"))
        self.addCleanup(shutil.rmtree, missing_dir, True)      # only the folder this test made
        missing = missing_dir / "store.tar.gz"                 # not there
        out = Path(tempfile.mkdtemp(prefix="hailwatch-hail-bad-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, FailingFetcher(), self.HAIL_NOW, hail_history=True, hail_store_path=str(missing))
        status = result["status"]["hail_history"]
        self.assertFalse(status["ok"])
        self.assertIn("missing", status["detail"])
        h = json.loads(page(out, "data/map.json"))["hail"]
        self.assertEqual(h["state"], "unavailable")
        self.assertEqual(h["tiles"], [])                       # no tile is known: the map says unavailable, not outside
        self.assertIn("missing", h["problem"])
        self.assertFalse((out / "hail").exists())
        self.assertIn("Hail history is unavailable: the history store file store.tar.gz is missing.",
                      page(out, "town/billings.html"))
        self.assertTrue((out / "index.html").is_file())
        self.assertIn("Hail history (radar estimates)", page(out, "index.html"))
        self.assertIn("Hail history didn't load", page(out, "map.html"))     # the banner says it, with no all-clear
        self.assertIn("This is not an all-clear.", page(out, "map.html"))

    def test_require_live_fails_on_a_failed_store_and_the_default_build_passes(self):
        missing_dir = Path(tempfile.mkdtemp(prefix="hailwatch-missing-"))
        self.addCleanup(shutil.rmtree, missing_dir, True)
        missing = missing_dir / "store.tar.gz"
        out = Path(tempfile.mkdtemp(prefix="hailwatch-hail-main-"))
        self.addCleanup(shutil.rmtree, out, True)
        argv = ["--out", str(out), "--sample", "--now", "2026-10-18T12:00:00Z", "--hail-history",
                "--hail-store", str(missing)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(site.main(argv + ["--require-live"]), 1)
        self.assertIn("Sources that failed or were stale: hail_history", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(site.main(argv), 0)
        self.assertTrue((out / "town" / "billings.html").is_file())

    def test_hail_store_needs_the_flag(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as cm:
            site.main(["--out", "unused", "--sample", "--hail-store", "x.tar.gz"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--hail-store needs --hail-history", err.getvalue())

    def test_a_local_store_folder_is_copied_after_its_manifest_checks_out(self):
        from website import hail as hs
        store = Path(tempfile.mkdtemp(prefix="hailwatch-store-dir-"))
        self.addCleanup(shutil.rmtree, store, True)
        hs.fixture_store(store)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-hail-dir-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, None, self.HAIL_NOW, sample=True, hail_history=True, hail_store_path=str(store))
        self.assertTrue(result["status"]["hail_history"]["ok"])
        self.assertFalse(result["status"]["hail_history"]["detail"].startswith("SAMPLE"))
        h = json.loads(page(out, "data/map.json"))["hail"]
        self.assertEqual(h["state"], "loaded")          # a store file is real data: no SAMPLE label on it
        self.assertEqual(h["tiles"], json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["tiles"])
        self.assertNotIn("SAMPLE data", page(out, "town/billings.html"))
        self.assertIn("4 days with a radar-estimated hail size", page(out, "town/billings.html"))
        self.assertEqual((out / "hail" / "t" / "r0079_c0199.json").read_bytes(),
                         (store / "hail" / "t" / "r0079_c0199.json").read_bytes())

    def test_a_store_whose_file_differs_from_its_manifest_is_not_copied(self):
        from website import hail as hs
        store = Path(tempfile.mkdtemp(prefix="hailwatch-store-bad-"))
        self.addCleanup(shutil.rmtree, store, True)
        hs.fixture_store(store)
        shard = store / "hail" / "t" / "r0079_c0199.json"
        shard.write_bytes(shard.read_bytes() + b"\n")          # one byte more: the manifest's hash no longer matches
        out = Path(tempfile.mkdtemp(prefix="hailwatch-hail-tamper-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, None, self.HAIL_NOW, sample=True, hail_history=True, hail_store_path=str(store))
        status = result["status"]["hail_history"]
        self.assertFalse(status["ok"])
        self.assertIn("does not match the manifest", status["detail"])
        self.assertFalse((out / "hail").exists())

    def test_a_store_archive_is_unpacked_and_checked_before_it_is_copied(self):
        from website import hail as hs
        import tarfile
        work = Path(tempfile.mkdtemp(prefix="hailwatch-archive-"))
        self.addCleanup(shutil.rmtree, work, True)
        hs.fixture_store(work / "src")
        archive = work / "hail-store.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(work / "src" / "hail", arcname="hail")
        out = Path(tempfile.mkdtemp(prefix="hailwatch-archive-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, None, self.HAIL_NOW, sample=True, hail_history=True, hail_store_path=str(archive))
        self.assertTrue(result["status"]["hail_history"]["ok"], result["status"]["hail_history"])
        self.assertEqual((out / "hail" / "index.json").read_bytes(), (work / "src" / "hail" / "index.json").read_bytes())
        self.assertEqual(json.loads(page(out, "data/map.json"))["hail"]["state"], "loaded")

    def test_the_workflow_passes_the_flag_to_branch_previews_and_runs_its_tests(self):
        text = (ROOT / ".github" / "workflows" / "website.yml").read_text(encoding="utf-8")
        args = [line for line in text.splitlines() if "args+=(" in line and "--hail-history" in line]
        self.assertEqual(len(args), 2)
        self.assertIn('if [ "$GITHUB_REF" != "refs/heads/main" ]', args[0])
        self.assertIn("--require-live --storm-layers --hail-history", args[0])
        # main passes the flag on its own (at the owner's decision of 2026-10-21) and never --require-live: a failed
        # store download leaves the pages saying the history is unavailable while the rest of the site publishes.
        self.assertIn('if [ "$GITHUB_REF" = "refs/heads/main" ]', args[1])
        self.assertIn("args+=(--hail-history)", args[1])
        self.assertNotIn("--require-live", args[1])
        # every build reads its own branch's asset, named as the store job names it
        self.assertIn('export HAIL_STORE_ASSET="hail-store-$(echo "$GITHUB_REF_NAME" | tr \'/\' \'-\').tar.gz"', text)
        # every build waits for the same commit's store job before it reads the asset; the listing needs the actions
        # scope, and the wait is bounded (the job's timeout covers it)
        wait = text[text.index("Wait for this branch's hail history store job"):text.index("- name: Build from live data")]
        self.assertIn("if: steps.plan.outputs.run == 'true' && github.ref != 'refs/heads/main'\n", wait)
        self.assertIn('--workflow hail-store.yml --branch "$GITHUB_REF_NAME" --limit 1', wait)
        self.assertIn("      actions: read", text)
        build_job = text[text.index("\n  build:\n"):text.index("\n  deploy:\n")]
        # a branch preview may wait up to 60 minutes for its store job; main never waits and keeps its 15
        self.assertIn("timeout-minutes: ${{ github.ref == 'refs/heads/main' && 15 || 75 }}", build_job)
        self.assertIn('print("\\nHail history (--hail-history):")', text)   # the summary names main's build too
        unit = [line for line in text.splitlines() if "python -m unittest" in line]
        self.assertEqual(len(unit), 1)
        self.assertIn("tests.test_hail", unit[0])
        self.assertIn('"tests/test_hail.py"', text)

    def test_the_wait_step_waits_for_a_running_store_job_and_fails_a_branch_on_a_bad_one(self):
        """The step's own shell runs under bash as GitHub runs a step with no shell key (bash -e), with a stub gh
        and a no-op sleep: no job for the commit; a job that is running and then succeeds; a job that failed (fatal
        on a branch, not on main); a listing error (the same); a job still running at the end of the loop (the
        same)."""
        text = (ROOT / ".github" / "workflows" / "website.yml").read_text(encoding="utf-8")
        step = text[text.index("Wait for this branch's hail history store job"):text.index("- name: Build from live data")]
        script = textwrap.dedent(step[step.index("run: |") + len("run: |"):])
        work = Path(tempfile.mkdtemp(prefix="hailwatch-wait-"))
        self.addCleanup(shutil.rmtree, work, True)
        stub = work / "bin"
        stub.mkdir()
        (stub / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (stub / "gh").write_text(
            '#!/bin/sh\n'
            'n=$(cat "$WAIT_TEST_COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$WAIT_TEST_COUNT"\n'
            'case "$WAIT_TEST_CASE" in\n'
            '  none) echo "null null null";;\n'
            '  runs-then-ok) if [ $n -lt 3 ]; then echo "queued null abc"; else echo "completed success abc"; fi;;\n'
            '  failed-this) echo "completed failure abc";;\n'
            '  failed-earlier) echo "completed failure older";;\n'
            '  error) echo "HTTP 403: Resource not accessible by integration" >&2; exit 1;;\n'
            '  forever) echo "in_progress null abc";;\n'
            'esac\n', encoding="utf-8")
        for name in ("sleep", "gh"):
            (stub / name).chmod(0o755)

        def run(case, ref):
            count = work / f"count-{case}-{ref.replace('/', '-')}"
            env = dict(os.environ, PATH=f"{stub}:{os.environ.get('PATH', '')}", GITHUB_REF=ref, GITHUB_SHA="abc",
                       GITHUB_REF_NAME=ref.replace("refs/heads/", ""), WAIT_TEST_CASE=case, WAIT_TEST_COUNT=str(count))
            p = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True)
            calls = int(count.read_text(encoding="utf-8")) if count.exists() else 0
            return p.returncode, (p.stdout.strip().splitlines() or [""])[-1], calls

        branch = "refs/heads/claude/x"
        self.assertEqual(run("none", branch), (0, "No store job on this branch; the build reads the asset already published.", 1))
        self.assertEqual(run("runs-then-ok", branch), (0, "The store job succeeded, after 3 checks.", 3))
        self.assertEqual(run("failed-this", branch)[:2], (1, "The store job for this commit ended as failure. Read its log in the Actions tab."))
        self.assertEqual(run("failed-earlier", branch)[:2],
                         (0, "The branch's last store job ended as failure (an earlier commit); the build reads the asset already published."))
        self.assertEqual(run("error", branch)[:2], (1, "The store job's state could not be read. Check the gh output above and the build job's actions: read scope."))
        still = "The store job is still running after 60 minutes. Read its log in the Actions tab, then re-run this build."
        self.assertEqual(run("forever", branch), (1, still, 60))

    def test_the_job_and_the_build_name_the_asset_the_same_way_for_every_branch(self):
        """The store job's asset step and the build's export use one formula: run both under bash for main and for
        a branch with a slash, and compare them with each other and with the reader's default for main."""
        from website import hail as hs
        job = (ROOT / ".github" / "workflows" / "hail-store.yml").read_text(encoding="utf-8")
        site_wf = (ROOT / ".github" / "workflows" / "website.yml").read_text(encoding="utf-8")
        job_line = [line for line in job.splitlines() if 'echo "name=hail-store-' in line][0].strip().split("run: ", 1)[1]
        site_line = [line for line in site_wf.splitlines() if "export HAIL_STORE_ASSET=" in line][0].strip()
        for ref, want in (("main", "hail-store-main.tar.gz"), ("claude/hail-b1", "hail-store-claude-hail-b1.tar.gz")):
            env = dict(os.environ, GITHUB_REF_NAME=ref, GITHUB_OUTPUT="/dev/stdout")
            from_job = subprocess.run(["bash", "-e", "-c", job_line], env=env, capture_output=True, text=True).stdout.strip()
            from_site = subprocess.run(["bash", "-e", "-c", site_line + '; echo "$HAIL_STORE_ASSET"'], env=env,
                                       capture_output=True, text=True).stdout.strip()
            self.assertEqual(from_job, "name=" + want)
            self.assertEqual(from_site, want)
        self.assertEqual(hs.STORE_ASSET_DEFAULT, "hail-store-main.tar.gz")

    def test_the_download_takes_the_branch_asset_and_falls_back_to_main(self):
        """site.hail_store with the build's fetcher: the branch's asset first (HAIL_STORE_ASSET), then main's when the
        branch has none; the index records which one it took."""
        from website import hail as hs
        import tarfile
        work = Path(tempfile.mkdtemp(prefix="hailwatch-fallback-"))
        self.addCleanup(shutil.rmtree, work, True)
        hs.fixture_store(work / "src")
        archive = work / "store.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(work / "src" / "hail", arcname="hail")
        data = archive.read_bytes()
        asked = []

        class Fetcher:
            def binary(self, url, headers=None):
                asked.append(url.rsplit("/", 1)[-1])
                return (None, "not published (HTTP 404)") if "claude-x" in url else (data, None)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-fallback-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        with mock.patch.dict(os.environ, {"HAIL_STORE_ASSET": "hail-store-claude-x.tar.gz"}):
            index = site.hail_store(out, None, False, Fetcher())
        self.assertEqual(asked, ["hail-store-claude-x.tar.gz", "hail-store-main.tar.gz"])
        self.assertEqual(index["asset"], "hail-store-main.tar.gz")
        self.assertTrue((out / "hail" / "index.json").is_file())
        # the build's status line names the asset it took
        out2 = Path(tempfile.mkdtemp(prefix="hailwatch-fallback-status-"))
        self.addCleanup(shutil.rmtree, out2, True)
        c = site.Collector(Fetcher(), self.HAIL_NOW)
        with mock.patch.dict(os.environ, {"HAIL_STORE_ASSET": "hail-store-claude-x.tar.gz"}):
            c.hail(out2, False, None, [])
        self.assertTrue(c.status["hail_history"]["ok"], c.status["hail_history"])
        self.assertIn(", from hail-store-main.tar.gz", c.status["hail_history"]["detail"])

    def test_the_hail_contract_row_states_the_asset_the_wait_and_the_stale_rule(self):
        from website import hail as hs
        row = src.CONTRACTS["hail_history"]
        self.assertIn("hail-store-main.tar.gz", row["request"])
        self.assertIn("its own branch's store", row["request"])
        self.assertIn("waits for the store job of its own commit", row["timing"])
        self.assertEqual(hs.STALE_DAYS, 3)
        self.assertIn("more than three days old is a failed source", row["timing"])
        self.assertNotIn("within the hour", row["timing"])

    def test_a_stale_store_is_a_failed_source_but_the_sample_never_is(self):
        """A real store whose last day is more than STALE_DAYS old still builds the pages (with the stale line) but
        counts as a failed source, so --require-live reports it; the SAMPLE fixture is exempt."""
        from website import hail as hs
        store = Path(tempfile.mkdtemp(prefix="hailwatch-store-stale-"))
        self.addCleanup(shutil.rmtree, store, True)
        hs.fixture_store(store)
        as_of = date.fromisoformat(json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["as_of"])
        out = Path(tempfile.mkdtemp(prefix="hailwatch-stale-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        late = datetime.combine(as_of + timedelta(days=hs.STALE_DAYS + 1), time(13, 0), tzinfo=timezone.utc)
        result = site.build(out, None, late, sample=True, hail_history=True, hail_store_path=str(store))
        status = result["status"]["hail_history"]
        self.assertFalse(status["ok"])
        self.assertIn("stale", status["detail"])
        self.assertEqual(json.loads(page(out, "data/map.json"))["hail"]["state"], "loaded")
        self.assertIn(hs.WORDS["stale"].format_map({"as_of": hs.fmt_date(as_of)}), page(out, "town/billings.html"))
        fresh = datetime.combine(as_of + timedelta(days=hs.STALE_DAYS), time(13, 0), tzinfo=timezone.utc)
        self.assertTrue(site.build(out, None, fresh, sample=True, hail_history=True,
                                   hail_store_path=str(store))["status"]["hail_history"]["ok"])
        self.assertTrue(site.build(out, None, late, sample=True, hail_history=True)["status"]["hail_history"]["ok"])

    def test_the_smoke_test_has_the_hail_checks(self):
        smoke = smoke_map()
        for name in ("check_hail", "check_no_hail", "no_estimate_spot", "outside_spot"):
            self.assertTrue(callable(getattr(smoke, name, None)), name)
        self.assertEqual(smoke.HAIL_GATE, (47.025, -110.135))       # the centre of cell (797, 1986) (decision 15)


if __name__ == "__main__":
    unittest.main()
