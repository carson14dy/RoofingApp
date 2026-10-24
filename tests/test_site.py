"""
Website checks (website/): parsers, failure handling, the built pages and the town label sides.

Everything runs offline. Parsers get NWS/SPC-shaped documents; builds use the labelled sample data
or small fake fetchers that fail on purpose. The live sources are checked separately by the
website workflow (`python -m website.build --require-live` on branch pushes).
"""

import contextlib
import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.parse
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
                                              "satellite", "basemap", "imagery", "hail_history", "lsr",
                                              "ncei_storm_events", "swdi_nx3hail", "nws_warnings_polygons",
                                              "nws_zone_products", "asos_daily_gusts", "msl_addresses",
                                              "msl_roads", "census_roads", "usa_structures", "census_counties",
                                              "census_tiger_counties",
                                              "hail_swath",
                                              "nclimgrid_daily", "nohrsc_season_snowfall", "ghcn_daily",
                                              "iem_watchwarn", "iem_lsr", "nwps_gauges", "usgs_water_api",
                                              "roof_references", "iem_ugcs"})
        for key, c in src.CONTRACTS.items():
            # a row a B5 row replaces names it (superseded_by); every other row has the five fields only
            self.assertTrue({"name", "request", "units", "timing", "missing"} <= set(c) <= {"name", "request", "units",
                            "timing", "missing", "superseded_by"}, key)
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
        b3 = site.B3_ROWS + tuple(site.ROAD_ROWS.values())                         # flag-gated: HailAddresses
        for key, c in src.CONTRACTS.items():
            if key not in site.STORM_CONTRACTS and key not in site.HAIL_CONTRACTS and key not in b3:
                self.assertIn(c["name"], html)
        for key in site.STORM_CONTRACTS + site.HAIL_CONTRACTS + b3:
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

    # D45: NOAA's "radar coverage" is allowed; any other "coverage" is the D13 stem
    FORBIDDEN = re.compile(r"\bdry\b|\bno hail\b|(?<!-)\bclear\b|(?<!radar )\bcoverage\b", re.IGNORECASE)
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


def tile_names_of(block: dict) -> list[str]:
    """The tile names a map.json hail block's split map lists (D40: no block lists every tile name), sorted."""
    return sorted(f"r{int(row):04d}_c{c:04d}" for row, runs in block["tile_split"].items()
                  for first, last in runs for c in range(first, last + 1))


class HailHistory(unittest.TestCase):
    """The five-year hail history (--hail-history; website/hail.py) behind a flag. Off by default: no hail key, files
    or section, and no hail words on the pages. On with --sample: the labelled SAMPLE store on the Map's sheet data,
    the town sections and the About paragraph. A store that doesn't load is a failed source, and the pages still
    build (--require-live then fails). The map script is checked for literals it must not hold (the store's words
    and units live in data/map.json and website/hail.py), for the size rule run in node when node is installed, and
    for the tile list and state lists the browser reads."""

    HAIL_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    HAIL_PAGE_WORDS = ("Five years of weather at", "<h2>Hail history</h2>", 'id="hail-sheet"', 'id="hail-list"',
                       "legend-tap", "data-hail", "Tap or click the map for the five-year hail history")
    # the words that must not appear unless a sentence says "not the same as no hail" or "'no hail'" (the negation)
    FORBIDDEN = re.compile(r"\bdamag\w*|\bdry\b|\bclear\b|\binsurance\b|\beligib\w*|\bconfirm\w*|\bno hail\b", re.I)
    # the sentences the contract row, the About page, DESIGN and D34 share (decision 14), and the display rule (decision 10)
    DAY_SENTENCE = ("A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to 6 am Mountain daylight time, 5 am to "
                    "5 am in winter (the SPC reporting day).")
    CELL_SENTENCE = ("the largest hail over this cell, about 0.7 miles north to south and 0.5 miles east to west, during "
                     "the day")
    NEXT_DAY_SENTENCE = ("The newest day is added by a job that starts at 12:43 UTC and shows here on the next rebuild, "
                         "usually within the hour.")
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
        self.assertEqual(tile_names_of(h), fixture["tiles"])            # the browser's outside test reads the split map (D40)
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
        names = tile_names_of(h)
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
        self.assertIn("Five years of weather at Billings", town)
        self.assertIn("SAMPLE data", town)
        self.assertIn("Radar estimate: Jul 24, 2022: 0.62 in (16.0 mm), pea to mothball", visible(town))   # 160 tenths: 0.62
        self.assertIn("Radar estimate: Jun 15, 2025: 0.25 in (6.5 mm), pea to mothball", visible(town))
        self.assertIn("Radar days by size class in these five seasons: 4 days pea to mothball", visible(town))
        as_of = hs.fmt_date(date.fromisoformat(fixture["as_of"]))
        self.assertIn(f"1,826 storm-report days (each from 12:00 to 12:00 UTC) ending {as_of}", visible(town))   # the as-of date
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
        self.assertIn("Five years of weather at Billings", page(out, "town/billings.html"))

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

    def test_the_sheet_shows_the_radar_days_before_the_joins(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        open_hail = js[js.index("function openHail("):js.index("function onHailClick(")]
        self.assertIn('hailShow(h, "loaded", text, null);', open_hail)
        self.assertIn('joinRender(el.sheetBody.querySelector(\'[data-hail="joins"]\'), joins);', open_hail)
        self.assertNotIn('hailShow(h, "loaded", text, joins)', open_hail)

    def test_a_warning_row_gives_the_end_date_only_on_a_later_montana_day(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn('var ends = joinDay(x.e) === joinDay(x.b) ? "" : joinDay(x.e) + " ";', js)
        self.assertIn("end: ends + joinClock(J, x.e),", js)

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
        self.assertEqual(h["tile_split"], {})                  # no tile is known: the map says unavailable, not outside
        self.assertIn("missing", h["problem"])
        self.assertFalse((out / "hail").exists())
        self.assertIn("Weather history could not be loaded in this update: the history store file store.tar.gz is missing.",
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
        self.assertEqual(tile_names_of(h), json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["tiles"])
        self.assertNotIn("SAMPLE data", page(out, "town/billings.html"))
        self.assertIn("Radar estimate: Jul 24, 2022: 0.62 in (16.0 mm), pea to mothball", visible(page(out, "town/billings.html")))
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
        self.assertEqual(len(args), 1)
        self.assertIn('if [ "$GITHUB_REF" != "refs/heads/main" ]', args[0])
        self.assertIn("--require-live --storm-layers --hail-history", args[0])
        unit = [line for line in text.splitlines() if "python -m unittest" in line]
        self.assertEqual(len(unit), 1)
        self.assertIn("tests.test_hail", unit[0])
        self.assertIn('"tests/test_hail.py"', text)

    def test_the_smoke_test_has_the_hail_checks(self):
        smoke = smoke_map()
        for name in ("check_hail", "check_no_hail", "no_estimate_spot", "outside_spot"):
            self.assertTrue(callable(getattr(smoke, name, None)), name)
        self.assertEqual(smoke.HAIL_GATE, (47.025, -110.135))       # the centre of cell (797, 1986) (decision 15)


class HailJoins(unittest.TestCase):
    """The joined records behind the hail history (B2, website/joins.py): six contract rows gated like the store's, the
    About paragraph on the kinds joined and the sources not joined, the sheet and town markup, and a flag-off build with
    none of it. The records themselves are checked in tests/test_joins.py (builder 1)."""

    # the joined feeds the About page lists in a hail build: the B2 rows that B5 keeps and the three B5 rows that replace
    # the B2 feeds (sources.py superseded_by); the replaced rows stay in CONTRACTS for the record and are not listed
    JOIN_KEYS = ("ncei_storm_events", "swdi_nx3hail", "asos_daily_gusts", "iem_lsr", "iem_watchwarn")
    SUPERSEDED = ("lsr", "nws_warnings_polygons", "nws_zone_products")
    HAIL_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    # the words a row or paragraph must not state as a fact (AGENTS.md rule 5); "damage threat" is the warning tag's own
    # word and "not the same as no hail" is the negation the words always carry
    FORBIDDEN = re.compile(r"\bdamag\w*|\bdry\b|\bclear\b|\binsurance\b|\beligib\w*|\bconfirm\w*|\bcustomers?\b|"
                           r"\bbest\b|\bguarantee\w*", re.I)

    @classmethod
    def setUpClass(cls):
        cls.off = Path(tempfile.mkdtemp(prefix="hailwatch-join-off-"))
        cls.on = Path(tempfile.mkdtemp(prefix="hailwatch-join-on-"))
        cls.addClassCleanup(shutil.rmtree, cls.off, True)      # only the folders this class made
        cls.addClassCleanup(shutil.rmtree, cls.on, True)
        site.build(cls.off, None, cls.HAIL_NOW, sample=True)
        site.build(cls.on, None, cls.HAIL_NOW, sample=True, hail_history=True)

    def test_the_joined_feed_rows_are_present_complete_and_gated_like_the_store(self):
        for key in self.JOIN_KEYS + self.SUPERSEDED:
            row = src.CONTRACTS[key]
            for field in ("name", "request", "units", "timing", "missing"):
                self.assertTrue(row[field].strip(), (key, field))
            self.assertIn(key, site.HAIL_CONTRACTS)
            self.assertNotIn(key, site.STORM_CONTRACTS)
        for key in self.SUPERSEDED:
            self.assertIn(src.CONTRACTS[key]["superseded_by"], src.CONTRACTS)     # the row that replaces it exists
        self.assertEqual(list(src.CONTRACTS)[-len(site.B5_CONTRACTS):], list(site.B5_CONTRACTS))

    def test_the_contract_rows_state_no_damage_insurance_or_all_clear(self):
        for key in self.JOIN_KEYS:
            text = " ".join(src.CONTRACTS[key].values())
            plain = re.sub(r"damage threat|not the same as no (?:hail|wind)", "", text, flags=re.I)
            self.assertIsNone(self.FORBIDDEN.search(plain), key)
            self.assertNotRegex(plain, r"\bno hail\b", key)
            self.assertNotRegex(plain, r"\bno wind\b", key)

    def test_the_about_page_names_the_kinds_joined_and_the_sources_not_joined(self):
        about = " ".join(page(self.on, "about.html").split())
        self.assertIn("Other records for the same cell", about)
        for phrase in ("NWS local storm reports within 5 miles, of every type the history reads",
                       "NEXRAD hail signatures within 2 miles", "not hail on the ground",
                       "the NWS polygons that intersect the cell", "the two nearest airport stations within 40 miles",
                       "Not in this history", "Flood zones (FEMA)", "Iowa State's inventory of radar detections is not complete"):
            self.assertIn(phrase, about)
        self.assertNotIn("Other records for the same cell", page(self.off, "about.html"))
        self.assertNotIn("Not in this history", page(self.off, "about.html"))

    def test_the_joined_feed_rows_appear_on_the_about_page_only_with_the_flag(self):
        on, off = page(self.on, "about.html"), page(self.off, "about.html")
        for key in self.JOIN_KEYS:
            name = src.CONTRACTS[key]["name"]
            self.assertIn(jesc(name), on)
            self.assertNotIn(jesc(name), off)
        for key in self.SUPERSEDED:                  # the rows a B5 row replaces are not listed on the About page
            self.assertNotIn(jesc(src.CONTRACTS[key]["name"]), on, key)

    def test_the_flag_off_build_has_no_join_markup_anywhere(self):
        for path in sorted(self.off.rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            for words in ("hail-join-sec", "joins-sec", "joins-rows", "joins-more", 'data-hail="joins"',
                          "Other records for the same cell", "Five years of weather at"):
                self.assertNotIn(words, text, f"{words!r} in {path.name}")
        self.assertFalse((self.off / "hail").exists())
        self.assertNotIn("hail", json.loads(page(self.off, "data/map.json")))

    def test_the_sheet_has_the_template_slots_for_the_six_sections(self):
        on = page(self.on, "map.html")
        self.assertIn('<template id="hail-join-sec">', on)
        self.assertIn('<div data-hail="joins"></div>', on)
        for slot in ("heading", "sample", "lead", "fire-lead", "rows", "more", "more-summary", "more-rows", "what", "note",
                     "unavailable"):
            self.assertIn(f'data-join="{slot}"', on, slot)
        off = page(self.off, "map.html")
        self.assertNotIn("hail-join-sec", off)
        self.assertNotIn('data-hail="joins"', off)


    # the browser's joined-records block (map.js, from "joined records at a spot" to the card mode): code only, no comments
    BLOCK_FORBIDDEN = (" in ", "mph", " kt", "knot", "mile", " mi", "inch", "hundredth", "millimet", "damage", "insurance",
                       "eligib", "all clear", "no hail", "no wind", "estimated", "measured", "unknown", "warning",
                       "radar", "nws", "ncei", "swdi", "iem", "benchland", "utica", "montana", "severe", "tornado",
                       "flash", "hail", "wind", "rain", "snow", "dbz", "tenths", "radius")

    @staticmethod
    def joins_block_code() -> str:
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        block = js[js.index("joined records at a spot (--hail-history builds, B2)"):js.index("card mode (inside other pages)")]
        code = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        return re.sub(r"//[^\n]*", "", code)

    def test_the_browser_joins_hold_no_unit_threshold_or_sentence_of_their_own(self):
        code = self.joins_block_code()
        for text in re.findall(r'"((?:[^"\\\n]|\\.)*)"', code):          # every double-quoted string
            if " " not in text:                                           # an identifier or a key, not a sentence
                continue
            for word in self.BLOCK_FORBIDDEN:
                self.assertNotIn(word, text.lower(), (word, text))
        # the field maps name the record rows' indices: their declarations are the one place those numbers live
        bare = re.sub(r"var (?:JROW|JDET|JDAY) = \{[^}]*\};", "", code)
        numbers = set(re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)", bare))
        # 0-4: indices, the nibble and digit arithmetic and the decimal places; 10: an ISO date's length; 16: hex;
        # 60 and 100: the hhmm and minute arithmetic of the time codes; 180: the degrees-to-radians factor
        self.assertLessEqual(numbers, {"0", "1", "2", "3", "4", "10", "16", "60", "100", "180"}, numbers)

    def test_every_word_the_browser_fills_is_one_the_build_writes(self):
        from website import joins as jn
        known = set(jn.WORDS_JOINS) | set(site.JOIN_SITE_WORDS)
        code = self.joins_block_code()
        used = set(re.findall(r"\bW\.(\w+)", code)) | set(re.findall(r'\bW\["(\w+)"\]', code)) | \
            set(re.findall(r"\bJ\.words\.(\w+)", code))
        self.assertFalse(sorted(used - known), sorted(used - known))
        for part in jn.PARTS:                                            # the keys each part's sections are built from
            for key in (f"{part}_heading", f"{part}_what", f"source_{part}", f"feed_{part}"):
                self.assertIn(key, known, key)
            if part != "zones":
                self.assertIn(f"{part}_lead_none", known, part)
        for key in ("reports_row", "reports_row_here", "records_zone_row", "detections_row_one", "detections_row_many",
                    "warnings_row_b5", "warnings_row_point", "zones_row", "zones_event", "stations_row", "unavailable", "partial",
                    "show_all"):
            self.assertIn(key, known, key)
        for stop in jn.ZONE_STOP_WORDS:                 # the browser names a stop's words as zones_<stop> and zones_<stop>_at
            for key in (f"zones_{stop}", f"zones_{stop}_at"):
                self.assertIn(key, jn.WORDS_JOINS, key)
        for stop in ("cancelled", "upgraded"):          # the stops map.js reads: joins.ZONE_STOP_STATE's words
            self.assertIn(stop, jn.ZONE_STOP_WORDS)


def write_joined_store(dest: Path) -> Path:
    """A small store with the joined records (hail/j, hail/z, hail/s) built on the B1 fixture, written into dest (a folder
    the caller made). The values are invented for the test; the formats are joins.py's B5 formats (hail-events-v2,
    hail-joins-v2, hail-station-v2): one events table holds every report, record and warning row once
    (hail/j/events.json), each tile refers to its rows by index, a warning comes with the tile's cover of cell keys, and
    a tile's zones map each zone code to its cell keys. The Benchland day
    (2025-06-15) has an LSR hail report of 1.75 in at 20:10 UTC and an NCEI record at the same time, a Thunderstorm Wind
    record in knots, radar detections, a severe thunderstorm warning covering the cell, one zone, and the Billings
    station's gusts. The manifest lists every file, as hail.load_store checks it."""
    from website import hail as hs
    hail = dest / "hail"
    shutil.copytree(hs.FIXTURE_DIR / "hail", hail)
    day = (date(2025, 6, 15) - hs.D0).days

    def cover(keys):
        value = 0
        for key in keys:
            value |= 1 << key
        return f"{value:025x}"

    def row(d, t, lat, lon, code, mag, unit, qual, src, city, remark, kind):
        return [d, t, lat, lon, code, mag, unit, qual, src, city, remark, kind]

    def record(d, t, lat, lon, code, mag, unit, qual, src, city, remark, mph, kt, cause=""):
        return [d, t, lat, lon, code, mag, unit, qual, src, city, remark, mph, kt, cause]

    remark = "Public caller updated with golf ball sized hail a few minutes after initial call."
    reports = [row(day, 545, 46.97, -110.09, "H", "1.0", "in", "E", "Public", "Utica", "", "hail"),                 # 0
               row(day, 2010, 47.08, -110.02, "H", "1.75", "in", "E", "Public", "Benchland", remark, "hail"),       # 1
               row(day, 2005, 47.08, -110.02, "H", "1.0", "in", "M", "Public", "Benchland", "", "hail"),            # 2
               row(day, 2020, 47.08, -110.02, "H", "1.25", "in", "M", "Trained Spotter", "Benchland", "", "hail")]  # 3
    records = [record(day, 2010, 47.08, -110.02, "hail", "1.75", "in", "", "Public", "Judith Basin", "", None, None),
               record(day, 2000, 47.00, -110.10, "thunderstorm wind", "56", "kt", "MG", "Mesonet", "Test", "", 64, 56)]
    warnings = [{"k": "SV", "s": "W", "b": "2025-06-15T20:33Z", "e": "2025-06-15T21:00Z", "o": "TFX",
                 "tags": {"hail_in": 1.0, "wind_mph": 50.0, "damage": "", "tornado": ""}}]
    bil = {"id": "BIL", "name": "Billings/Logan Intl", "lat": 45.8069, "lon": -108.5422, "miles": 30.2}   # the fixture's station
    # R9 (D61): the gate cell and Benchland get a station within 40 miles of their own cells, the fixture's Lewistown
    # Municipal gust file (LWT); Billings is 113 miles from the gate cell, so it is not a candidate there
    from website import joins as jn
    lwt = {"id": "LWT", "name": "Lewistown Municipal", "lat": 47.0492, "lon": -109.4667}

    def near(lat, lon):
        return dict(lwt, miles=round(jn.haversine_km(lat, lon, lwt["lat"], lwt["lon"]) / jn.MILE_KM, 1))

    gate_lat, gate_lon = hs.cell_centre(797, 1986)
    bench_lat, bench_lon = hs.cell_centre(792, 1998)
    assert near(gate_lat, gate_lon)["miles"] <= jn.STATION_MILES and near(bench_lat, bench_lon)["miles"] <= jn.STATION_MILES
    tiles = {
        "r0079_c0198": {   # the gate cell's tile (797, 1986): key 76, the zone MTZ048
            "reports": [0, 1], "records": [0, 1], "warnings": [[0, cover([76])]],
            "detections": [[day, 300, 47.02, -110.13, 75], [day, 2030, 47.07, -110.01, 100]],
            "zones": {"MTZ048": [76]}, "fire": {"MTZ117": [76]}, "stations": [near(gate_lat, gate_lon)]},
        "r0079_c0199": {   # Benchland's own cell (792, 1998): key 28, the same zone
            "reports": [2, 1, 3], "records": [0], "warnings": [[0, cover([28])]],
            "detections": [[day, 2030, 47.07, -110.01, 100], [day, 2000, 47.075, -110.015, 75]],
            "zones": {"MTZ048": [28]}, "stations": [near(bench_lat, bench_lon)]},
        "r0092_c0214": {   # Billings' tile: no reports; the airport's gusts
            "reports": [], "records": [], "warnings": [], "detections": [], "zones": {},
            "stations": [dict(bil, miles=1.2)]},
    }
    # the in-range station's gust file: the fixture's Billings file (one gust day in the window, 2025-06-16) under Lewistown
    # Municipal's id and position, so the gate cell and Benchland have a station with a day inside 40 miles (R9)
    bil_file = json.loads((hail / "s" / "BIL.json").read_text(encoding="utf-8"))
    lwt_file = dict(bil_file, id=lwt["id"], name=lwt["name"], lat=lwt["lat"], lon=lwt["lon"])
    (hail / "s" / f"{lwt['id']}.json").write_text(json.dumps(lwt_file, separators=(",", ":")), encoding="utf-8")
    (hail / "j").mkdir(exist_ok=True)
    (hail / "j" / jn.TILE_EVENTS_DIR).mkdir(exist_ok=True)
    events = {"f": jn.EVENTS_FORMAT, "d0": "2020-01-01", "reports": reports, "records": records, "warnings": warnings}
    (hail / "j" / "events.json").write_text(json.dumps(events, separators=(",", ":")), encoding="utf-8")
    for name, body in tiles.items():
        doc = {"f": "hail-joins-v2", "r": int(name[1:5]), "c": int(name[7:11]), "d0": "2020-01-01", "counties": {}, **body}
        (hail / "j" / f"{name}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        # D30: the tile's own events file, the rows its tile refers to (the browser fetches it on a tap, never events.json)
        tile_events = jn._tile_events(doc, reports, records, warnings)
        (hail / "j" / jn.TILE_EVENTS_DIR / f"{name}.json").write_text(json.dumps(tile_events, separators=(",", ":")),
                                                                      encoding="utf-8")
    (hail / "z").mkdir(exist_ok=True)
    # the zone's products: a high wind warning, and a winter storm warning cancelled with no start recorded (D16)
    zone = {"f": "hail-zone-v1", "zone": "MTZ048", "name": "Judith Basin",
            "events": [{"k": "HW", "s": "W", "b": "2025-06-15T18:00Z", "e": "2025-06-16T02:00Z", "o": "BYZ"},
                       {"k": "WS", "s": "W", "b": None, "e": "2025-06-15T06:00Z", "st": "cancelled", "o": "BYZ"}],
            "records": [record(day, 1100, 47.0, -110.5, "high wind", "58", "kt", "", "Mesonet", "Test", "", 67, 58),
                        record(day, 300, 47.0, -110.5, "winter storm", "", "", "", "Mesonet", "Test", "", None, None)]}
    (hail / "z" / "MTZ048.json").write_text(json.dumps(zone, separators=(",", ":")), encoding="utf-8")
    # the fire weather zone's red flag warnings (D7, D17): one with a start and an end, and one with a start and no end
    fire = {"f": "hail-zone-v1", "kind": "fire", "zone": "MTZ117", "name": "Central and Eastern Lewis and Clark National "
            "Forest Areas", "events": [{"k": "FW", "s": "W", "b": "2025-06-15T16:00Z", "e": "2025-06-15T23:00Z", "o": "TFX"},
                                       {"k": "FW", "s": "W", "b": "2025-06-14T15:00Z", "e": None, "o": "TFX"}]}
    (hail / "z" / "fire-MTZ117.json").write_text(json.dumps(fire, separators=(",", ":")), encoding="utf-8")
    # the Billings gust file is the B1 fixture's own hail-station-v3 file, copied with the folder above: one gust day
    # (2025-06-16, 50 kt, 58 mph), so the Billings page has one station line
    index = json.loads((hail / "index.json").read_text(encoding="utf-8"))
    index["joins"] = {
        "format": jn.FORMAT, "events_format": jn.EVENTS_FORMAT,           # R9: the formats the readers check (D30)
        "built_at": "2026-10-18T12:00:00Z", "lsr_rows": 4, "ncei_rows": 2, "ncei_newest_event": "2026-06-30",
        "swdi_rows": 3, "warnings": {"SV": 2, "TO": 0, "FF": 0}, "zone_events": 2, "zones": 1, "stations": 1,
        "station_days": 3, "sources": {}, "state": "loaded",
        "parts": {part: "loaded" for part in ("reports", "records", "detections", "warnings", "zones", "stations")},
        "reasons": {}, "lags": {"ncei": "2026-06-30", "swdi": "2026-10-14", "warnings": "2026-10-16"}, "partial": {},
        "zone_names": {"MTZ048": "Judith Basin"}, "fire_zones": {"state": "loaded"},
        "fire_zone_names": {"MTZ117": "Central and Eastern Lewis and Clark National Forest Areas"},
        "zone_products_unplaced": 2, "warnings_no_outline": 0,
        "types": {"H": "hail", "G": "thunderstorm wind gust", "N": "non-thunderstorm wind gust", "R": "heavy rain"},
        "cover": "bit k is cell key k", "shapes": {}, "montana_time": []}
    (hail / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    manifest_path = hail / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {}
    for path in sorted(hail.rglob("*")):
        if path.is_dir() or path.name == "manifest.json":
            continue
        data = path.read_bytes()
        files[path.relative_to(dest).as_posix()] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest["files"] = files
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return dest


def write_store_without_joins(dest: Path) -> Path:
    """The SAMPLE fixture's hail/ folder copied into dest with its joined records taken out (no j/, z/ or s/ folders and no
    joins block in the index), with a manifest that lists what is left: a store of the B1 kind."""
    from website import hail as hs
    hail = dest / "hail"
    shutil.copytree(hs.FIXTURE_DIR / "hail", hail)
    for name in ("j", "z", "s"):
        shutil.rmtree(hail / name, ignore_errors=True)
    index_path = hail / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.pop("joins", None)
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    manifest_path = hail / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {}
    for path in sorted(hail.rglob("*")):
        if path.is_dir() or path.name == "manifest.json":
            continue
        data = path.read_bytes()
        manifest["files"][path.relative_to(dest).as_posix()] = {"bytes": len(data),
                                                              "sha256": hashlib.sha256(data).hexdigest()}
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return dest


def write_b2_only_store(dest: Path) -> Path:
    """A B2 store made from the sample fixture's hail/ folder with its B5 parts taken out (D64): the climate, snow, station
    and gauge files and their index blocks, the county files, the per-tile events files, the towns file and the joins
    block's B5 keys. What is left is the B2 store (the radar shards, the joins, the zone and gust files), and its
    manifest lists exactly those files, so hail.load_store checks it."""
    from website import hail as hs
    hail = dest / "hail"
    shutil.copytree(hs.FIXTURE_DIR / "hail", hail)
    for name in ("c", "n", "sd", "tl", "g", "k"):
        shutil.rmtree(hail / name, ignore_errors=True)
    shutil.rmtree(hail / "j" / "e", ignore_errors=True)
    (hail / "j" / "towns.json").unlink(missing_ok=True)
    index_path = hail / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for key in ("climate", "snow", "stations", "gauges", "county"):
        index.pop(key, None)
    if isinstance(index.get("joins"), dict):
        for key in ("counties", "events_tiles", "towns_file"):
            index["joins"].pop(key, None)
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    manifest_path = hail / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {}
    for path in sorted(hail.rglob("*")):
        if path.is_dir() or path.name == "manifest.json":
            continue
        data = path.read_bytes()
        manifest["files"][path.relative_to(dest).as_posix()] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return dest


JOIN_IDS = ("reports", "records", "detections", "warnings", "zones", "stations")
BROWSER_JOINS_START = "joined records at a spot (--hail-history builds, B2)"     # the joined block in map.js
BROWSER_JOINS_END = "card mode (inside other pages)"
# node runs the sheet's joined-records code from map.js: the input (code, h, cells, site, tz) comes on stdin as JSON, the six
# sections of each cell go out as JSON. Only fetch is stubbed: it reads the built site's files, as the browser would.
NODE_JOINS_SCRIPT = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");
let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { raw += chunk; });
process.stdin.on("end", () => {
  const input = JSON.parse(raw);
  const fetchFile = (url) => new Promise((resolve) => {
    fs.readFile(path.join(input.site, url), "utf8", (err, text) => resolve(err ? { ok: false, status: 404 }
      : { ok: true, status: 200, json: () => new Promise((ok) => ok(JSON.parse(text))) }));   // a bad body rejects, as json() does
  });
  const ctx = vm.createContext({ Intl: Intl, Date: Date, Math: Math, JSON: JSON, Promise: Promise, Set: Set,
    Object: Object, Array: Array, String: String, Number: Number, Error: Error, isFinite: isFinite,
    fetch: fetchFile, data: { tz: input.tz }, hailTiles: {} });
  vm.runInContext(input.code, ctx);
  vm.runInContext("this.runCells = async (h, cells) => { const out = []; for (const c of cells) " +
    "out.push(await joinSections(h, c)); return out; };", ctx);
  ctx.runCells(input.h, input.cells).then((out) => process.stdout.write(JSON.stringify(out)),
    (err) => { process.stderr.write(String((err && err.stack) || err)); process.exit(1); });
});
"""


def js_function(js: str, name: str) -> str:
    """One top-level function of map.js (two-space indent, as the file writes them): its own line when it is one line,
    else its lines up to the closing brace at the same indent."""
    lines = js.split("\n")
    first = next(n for n, line in enumerate(lines) if line.startswith(f"  function {name}("))
    if lines[first].count("{") == lines[first].count("}"):
        return lines[first]
    last = next(n for n in range(first + 1, len(lines)) if lines[n] == "  }")
    return "\n".join(lines[first:last + 1])


def browser_join_code(js: str) -> str:
    """The part of map.js the sheet's joined records run on: the constants and helpers the block calls, then the block
    from its heading to the card mode. Nothing else of the page is run."""
    consts = [line for line in js.split("\n") if re.match(r"  var (MIN|HAIL_DAY_MS|dtfUtcDay|hailTiles)\b", line)]
    helpers = [js_function(js, name) for name in ("fill", "pad4", "hailIso", "hailDate", "hailKey", "hailTileName",
                                                  "hailTile", "hailFailure")]
    start = js.rindex("\n", 0, js.index(BROWSER_JOINS_START)) + 1          # from the start of the heading's line
    end = js.rindex("\n", 0, js.index(BROWSER_JOINS_END)) + 1               # up to the card mode's heading line
    return "\n".join(consts + helpers + [js[start:end]])


def node_join_sections(site: Path, h: dict, tz: str, cells: list[dict]) -> list[dict]:
    """The six sections for each cell as the browser's code writes them (joinSections in map.js, under node), with h the
    map.json hail block the page would read and site the built folder its fetches read."""
    js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
    payload = {"code": browser_join_code(js), "site": str(site), "h": h, "tz": tz, "cells": cells}
    done = subprocess.run([shutil.which("node"), "-e", NODE_JOINS_SCRIPT], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise AssertionError(f"the browser's joined records did not run under node: {done.stderr[-800:]}")
    return json.loads(done.stdout)


def module_view(sec: dict) -> dict:
    """A section as describe_joins writes it, in the comparable form the browser's section is put in below."""
    return {"id": sec["id"], "heading": sec["heading"], "what": " ".join(x for x in (sec["what"], sec["source"]) if x),
            "lead": sec["lead"] or "", "fire_lead": sec.get("fire_lead") or "",
            "rows": [[r["text"], r["remark"] or ""] for r in sec["rows"]],
            "lines": list(sec["lines"]), "unavailable": sec["unavailable"] or ""}


def browser_view(sec: dict) -> dict:
    """A section as the browser's code writes it (its what already holds the source line), in the same form."""
    return {"id": sec["id"], "heading": sec["heading"], "what": sec["what"], "lead": sec["lead"] or "",
            "fire_lead": sec.get("fire_lead") or "", "rows": [[r["text"], r["remark"] or ""] for r in sec["rows"]],
            "lines": list(sec["lines"] or []), "unavailable": sec["unavailable"] or ""}


class HailJoinedRecords(unittest.TestCase):
    """The joined records in a built site (B2), from a store made here: the sheet's data, the town tables, the words the
    build writes, and a store without the records. The store is invented for the test (write_joined_store says so); the
    real store is checked by tools/smoke_map.py and by builder 1's verification."""

    NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="hailwatch-joined-"))        # this class made it; only it removes it
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.store = write_joined_store(cls.tmp / "store")
        cls.site = cls.tmp / "site"
        cls.result = site.build(cls.site, None, cls.NOW, sample=True, hail_history=True,
                                hail_store_path=str(cls.store))     # sample: no network for the other feeds
        cls.plain = cls.tmp / "plain"
        cls.plain_store = write_store_without_joins(cls.tmp / "plain-store")
        cls.plain_site = site.build(cls.plain, None, cls.NOW, sample=True, hail_history=True,
                                    hail_store_path=str(cls.plain_store))

    def test_the_map_block_carries_the_words_radii_and_zone_names_the_browser_reads(self):
        m = json.loads(page(self.site, "data/map.json"))["hail"]
        j = m["joins"]
        self.assertEqual(j["state"], "loaded")
        self.assertEqual(j["radius_miles"], {"report": 5.0, "detection": 2.0, "station": 40.0})
        self.assertEqual(j["shards"], {"j": "hail/j/{tile}.json", "z": "hail/z/{zone}.json", "s": "hail/s/{station}.json",
                                       "fire": "hail/z/fire-{zone}.json"})
        self.assertEqual(j["fire_state"], "loaded")
        self.assertEqual(j["counts"], {"warnings_no_outline": 0, "ncei_zone_rows_unmatched": 0, "zone_products_unplaced": 2})
        self.assertGreater(j["earth_radius_km"], 6000)
        self.assertEqual(j["zone_names"], {"MTZ048": "Judith Basin"})
        self.assertEqual((j["hail_unit"], j["show_first"], j["spc_hours"], j["hundredths_per_inch"]), ("in", 10, 12, 100))
        self.assertEqual(j["unit_words"], {"mph": "magnitude_mph", "kt": "magnitude_kt"})
        for key in ("show_all", "times_note", "reports_row", "zones_heading_no_zone", "records_newest_unknown", "unavailable",
                    "partial", "part_reports", "one_reports", "fire_lead_one", "zones_lead_one", "fire_product"):
            self.assertIn(key, j["words"])
        for key in ("not_known", "zone_unknown_name", "zone_unknown_code"):
            self.assertNotIn(key, j["words"])

    def test_the_billings_town_page_joins_sit_in_their_sections_newest_first(self):
        # the s/ v3 fixture holds one gust day, so the page has one station line: its words come from the fixture (the day
        # index, the knots and miles per hour, the station's own name) and its distance is from the town point (D36)
        from website import hail as hs, joins as jn
        fixture = json.loads((hs.FIXTURE_DIR / "hail" / "s" / "BIL.json").read_text(encoding="utf-8"))
        (index, mph, kt, _flag), = fixture["days"]
        town = next(t for t in json.loads(jn.TOWNS_FILE.read_text(encoding="utf-8")) if t["slug"] == "billings")
        miles = jn.haversine_km(town["lat"], town["lon"], fixture["lat"], fixture["lon"]) / jn.MILE_KM
        line = (f"Station: {hs.fmt_date(hs.day_of_index(index))}: {kt} kt ({mph} mph) at {fixture['name']}, "
                f"about {miles:.1f} miles away")
        town_page = page(self.site, "town/billings.html")
        wind = town_page[town_page.index('id="sec-wind"'):town_page.index('id="sec-storms"')]     # the station rows are the wind section's
        self.assertEqual(visible(wind).count("Station: "), len(fixture["days"]))
        self.assertIn(line, visible(wind))
        from website import summary as sm
        self.assertIn(jesc(sm.WORDS_INDICATORS["what_station"]), wind)                        # the kind's own sentence

    def test_the_module_words_for_the_gate_and_benchland_cells(self):
        from website import hail as hs
        from website import joins as jn
        index = hs.load_index(self.site)
        def words(lat, lon):
            row, col = hs.cell_for(lat, lon)
            tile = json.loads((self.site / "hail" / "j" / f"{hs.tile_name(row // 10, col // 10)}.json").read_text("utf-8"))
            return jn.describe_joins(index, tile, row, col, self.NOW, sample=False, store_dir=self.site)
        gate = {sec["id"]: sec for sec in words(47.025, -110.135)["sections"]}
        self.assertIn("1 NWS local storm report within 5 miles", gate["reports"]["lead"])   # the 1.75 report is 6.6 miles away
        self.assertIn("Jun 14, 2025 11:45 pm MDT", gate["reports"]["rows"][0]["text"])  # 05:45 UTC on Jun 15, the newest report
        self.assertIn("Jun 14, 2025 11:45 pm MDT: hail, 1.00 in (estimated), Public, 4.4 mi SE", gate["reports"]["rows"][0]["text"])
        self.assertIn("TFX", gate["warnings"]["rows"][0]["text"])
        bench = {sec["id"]: sec for sec in words(47.075, -110.015)["sections"]}
        rows = bench["reports"]["rows"]                       # newest first: the 2:20 pm report leads
        self.assertIn("Jun 15, 2025 2:20 pm MDT: hail, 1.25 in (measured), Trained Spotter, 0.4 mi NW", rows[0]["text"])
        golf = [r for r in rows if "1.75 in (estimated)" in r["text"]]
        self.assertEqual(len(golf), 1)
        self.assertIn("Jun 15, 2025 2:10 pm MDT", golf[0]["text"])
        self.assertEqual(golf[0]["remark"], "Remark, as written: “Public caller updated with golf ball sized hail "
                         "a few minutes after initial call.”")

    def test_a_store_without_the_records_says_so_in_the_history(self):
        town = page(self.plain, "town/billings.html")       # a town in a sample tile: each joined part says why, once
        for sentence in ("Reports could not be loaded in this update; that is not the same as no report.",
                         "Records could not be loaded in this update; that is not the same as no record.",
                         "Detections could not be loaded in this update; that is not the same as no detection.",
                         "Warnings could not be loaded in this update; that is not the same as no warning.",
                         "Zone products could not be loaded in this update; that is not the same as no zone product.",
                         "Station readings could not be loaded in this update; that is not the same as no station reading."):
            self.assertIn(sentence, town)
        m = json.loads(page(self.plain, "data/map.json"))["hail"]["joins"]
        self.assertEqual(m["state"], "unavailable")   # the sample fixture holds no records: every part says so

    # the three cells the parity checks read: the gate cell, Benchland's own cell, and a cell with no records (Billings' tile)
    PARITY_CELLS = {"the gate cell": (47.025, -110.135), "Benchland's cell": (47.075, -110.015),
                    "a cell with no records (Billings)": (45.7833, -108.5007)}

    def page_hail(self) -> tuple[dict, str]:
        """The map block the page reads (data/map.json "hail") and the page's time zone."""
        m = json.loads(page(self.site, "data/map.json"))
        return m["hail"], m["tz"]

    def assert_browser_matches_module(self, index: dict, h: dict, tz: str, label: str) -> None:
        """For the three cells, the browser's sections (map.js run under node on the page's own block and files) say what
        describe_joins says for the same index: the same headings, leads, rows, remarks, lines, unavailable sentences and
        times, section by section."""
        from website import hail as hs
        from website import joins as jn
        cells = []
        for lat, lon in self.PARITY_CELLS.values():
            row, col = hs.cell_for(lat, lon)
            cells.append({"row": row, "col": col})
        browser = node_join_sections(self.site, h, tz, cells)
        for (name, (lat, lon)), got in zip(self.PARITY_CELLS.items(), browser):
            row, col = hs.cell_for(lat, lon)
            tile = json.loads((self.site / "hail" / "j" / f"{hs.tile_name(row // hs.TILE, col // hs.TILE)}.json")
                              .read_text(encoding="utf-8"))
            want = jn.describe_joins(index, tile, row, col, self.NOW, sample=False, store_dir=self.site)
            self.assertEqual([browser_view(got[key]) for key in JOIN_IDS], [module_view(s) for s in want["sections"]],
                             f"{label}: {name}")
            self.assertEqual(got["times"], want["times_note"], f"{label}: {name} times")

    def test_the_browser_joins_say_what_the_module_says_for_three_cells(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import hail as hs
        h, tz = self.page_hail()
        self.assert_browser_matches_module(hs.load_index(self.site), h, tz, "the built store")
        row, col = hs.cell_for(*self.PARITY_CELLS["a cell with no records (Billings)"])
        billings = node_join_sections(self.site, h, tz, [{"row": row, "col": col}])[0]
        for key in ("reports", "records", "detections", "warnings"):       # the cell the name says has no records
            self.assertEqual(billings[key]["rows"], [], key)

    def test_the_zone_sections_name_both_leads_and_the_red_flag_rows(self):
        """The gate cell's zone section as the sheet shows it (the browser's code, under node): the forecast zone's lead and
        the fire weather zone's lead (D17), the red flag rows with their fire weather words (D7), a cancelled product with
        no recorded start (D16), a red flag warning with no end, and the unplaced line (D11)."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import hail as hs
        h, tz = self.page_hail()
        row, col = hs.cell_for(47.025, -110.135)
        zones = node_join_sections(self.site, h, tz, [{"row": row, "col": col}])[0]["zones"]
        self.assertIn("2 products for zone Judith Basin (MTZ048) between", zones["lead"])
        self.assertIn("2 red flag warnings for fire weather zone Central and Eastern Lewis and Clark National Forest Areas "
                      "(MTZ117) between", zones["fire_lead"])
        self.assertIn("Zone product: Red flag warning, fire weather zone Central and Eastern Lewis and Clark National Forest "
                      "Areas (MTZ117): Jun 14, 2025 9:00 am MDT to end not recorded", " ".join(r["text"] for r in zones["rows"]))
        texts = [r["text"] for r in zones["rows"]]
        self.assertIn("Zone product: High wind warning: Jun 15, 2025 12:00 pm MDT to 8:00 pm MDT", texts)
        self.assertIn("Zone product: Winter storm warning: start not recorded; end Jun 15, 2025 12:00 am MDT, cancelled", texts)
        red = [x for x in texts if x.startswith("Zone product: Red flag warning, fire weather zone Central")]
        self.assertEqual(len(red), 1)
        self.assertIn("Jun 15, 2025 10:00 am MDT to 5:00 pm MDT", red[0])
        self.assertIn("end not recorded", red[0])
        self.assertNotIn("end end", " ".join(texts))
        from website import joins as jn
        self.assertEqual(zones["lines"], [jn.WORDS_JOINS["zones_unplaced_many"].format(n=2)])   # the module's own words

    def test_a_record_with_no_unit_reads_as_its_type_word_and_no_size_is_given(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import hail as hs
        h, tz = self.page_hail()
        row, col = hs.cell_for(47.025, -110.135)
        got = node_join_sections(self.site, h, tz, [{"row": row, "col": col}])[0]
        winter = [r["text"] for r in got["records"]["rows"] if "winter storm" in r["text"]]
        self.assertEqual(winter, ["Record: Jun 14, 2025 9:00 pm MDT: winter storm, Mesonet, across zone MTZ048"])
        for part in JOIN_IDS:
            self.assertNotIn("no size given", json.dumps(got[part]), part)
        wind = [r["text"] for r in got["records"]["rows"] if "thunderstorm wind" in r["text"]]
        self.assertEqual(len(wind), 1)                              # a unit type: its speeds, knots first (D5, D19)
        self.assertIn("thunderstorm wind, 56 kt (64 mph) (measured gust), Mesonet, 2.4 mi SE", wind[0])
        row, col = hs.cell_for(47.075, -110.015)                    # Benchland's cell: the 1.75 in hail record is 0.4 miles away
        bench = node_join_sections(self.site, h, tz, [{"row": row, "col": col}])[0]["records"]["rows"]
        hail = [r["text"] for r in bench if ": hail, " in r["text"]]
        self.assertEqual(len(hail), 1)
        self.assertIn("hail, 1.75 in, Public", hail[0])

    def test_a_part_that_did_not_load_reads_the_same_on_both_surfaces(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import hail as hs
        index = hs.load_index(self.site)
        h, tz = self.page_hail()
        marks = {"parts": {"reports": "unavailable", "records": "partial", "detections": "partial"},
                 "partial": {"records": ["Jun 14, 2025"], "detections": ["Jun 14, 2025"]}}
        for block in (index["joins"], h["joins"]):     # the same mark on the store's index and on the page's block
            block["parts"].update(marks["parts"])
            block["partial"] = dict(marks["partial"])
        self.assert_browser_matches_module(index, h, tz, "a part marked unavailable or partial")
        got = node_join_sections(self.site, h, tz, [{"row": hs.cell_for(47.025, -110.135)[0],
                                                       "col": hs.cell_for(47.025, -110.135)[1]}])[0]
        self.assertEqual(got["reports"]["lead"], "")                 # a part that did not load says no lead ("No ...")
        self.assertEqual(got["reports"]["rows"], [])
        self.assertTrue(got["reports"]["unavailable"])
        self.assertTrue(got["records"]["unavailable"])              # a partial part keeps its rows and says why
        self.assertTrue(got["records"]["rows"])

    GATE_POINT = (47.025, -110.135)          # the gate cell (797, 1986): one forecast zone and one fire weather zone
    STATION_UNAVAILABLE = ("Station readings could not be loaded in this update; that is not the same as no station "
                           "reading. This is not an all-clear.")          # D41: the unavailable line ends with the all-clear
    ZONE_UNAVAILABLE = ("Zone products could not be loaded in this update; that is not the same as no zone product. "
                        "This is not an all-clear.")   # D41: the unavailable line ends with the all-clear sentence

    def copy_site(self) -> Path:
        """A copy of the built site's hail folder, for one test to change. The test makes it and removes it."""
        folder = Path(tempfile.mkdtemp(prefix="hailwatch-copy-"))
        self.addCleanup(shutil.rmtree, folder, True)
        shutil.copytree(self.site / "hail", folder / "hail")
        return folder

    def gate_copy(self) -> Path:
        """A copy of the site whose gate tile lists two stations: Lewistown Municipal (the store's own file, with a day in the
        window, within 40 miles of the gate cell, R9) and Lima (the B1 fixture's file, which holds no day). A test changes or
        removes one of the two files."""
        from website import hail as hs
        folder = self.copy_site()
        row, col = hs.cell_for(*self.GATE_POINT)
        path = folder / "hail" / "j" / f"{hs.tile_name(row // hs.TILE, col // hs.TILE)}.json"
        tile = json.loads(path.read_text(encoding="utf-8"))
        tile["stations"].append({"id": "1LM", "name": "Lima", "lat": 46.7, "lon": -109.7333, "miles": 38.6})
        path.write_text(json.dumps(tile, separators=(",", ":")), encoding="utf-8")
        return folder

    def both_ways(self, folder: Path) -> tuple[dict, dict]:
        """The gate cell's six sections as the browser's code writes them (under node, reading the folder's files), and as
        describe_joins writes them from the same folder; each side keyed by section id, in the comparable views."""
        from website import hail as hs
        from website import joins as jn
        h, tz = self.page_hail()
        row, col = hs.cell_for(*self.GATE_POINT)
        got = node_join_sections(folder, h, tz, [{"row": row, "col": col}])[0]
        tile = json.loads((folder / "hail" / "j" / f"{hs.tile_name(row // hs.TILE, col // hs.TILE)}.json")
                          .read_text(encoding="utf-8"))
        want = jn.describe_joins(hs.load_index(folder), tile, row, col, self.NOW, sample=False, store_dir=folder)
        self.assertEqual(got["times"], want["times_note"])
        return {key: browser_view(got[key]) for key in JOIN_IDS}, {s["id"]: module_view(s) for s in want["sections"]}

    def test_a_store_with_no_records_says_every_part_is_unavailable_in_the_browser(self):
        """The published store may hold no joined records at all (the B1 asset until the daily job's joins step has run,
        or a job whose joins step failed). The browser then shows every section's unavailable sentence and nothing else,
        and throws nothing: the block's empty window dates are read only once the store is known to hold records (the
        preview of 2026-10-19 failed on exactly this: "Invalid time value" and six silent sections)."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import build as bd
        from website import hail as hs
        from website import joins as jn
        h, tz = self.page_hail()
        h = dict(h)
        h["joins"] = bd.join_block_unavailable(jn, "the joined records are not in this history store")
        self.assertEqual(h["joins"]["window"], ["", ""])          # the shape the build writes for such a store
        row, col = hs.cell_for(47.025, -110.135)
        got = node_join_sections(self.site, h, tz, [{"row": row, "col": col}])[0]
        w = jn.WORDS_JOINS
        for part in jn.PARTS:
            self.assertEqual(got[part]["unavailable"], w["unavailable"].format(part=w["part_" + part], one=w["one_" + part]))
            self.assertEqual((got[part]["lead"], got[part]["rows"], got[part]["lines"]), ("", [], []))

    def test_a_station_file_that_did_not_load_says_so_and_gives_no_count(self):
        """A station file the browser cannot load makes the stations section show its unavailable sentence and nothing else
        (D27, D28): no lead, no rows, no note, and none of the other station's days. The gate cell's tile lists Lewistown
        Municipal and Lima (gate_copy); Lima's file is removed, not JSON, not an object, or JSON whose days are not a list.
        Each case matches describe_joins on the same folder, which reads the same failure."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        browser, module = self.both_ways(self.gate_copy())                  # the baseline: both files load
        self.assertEqual(browser["stations"], module["stations"])
        self.assertEqual(browser["stations"]["unavailable"], "")
        self.assertTrue(any("Lewistown Municipal" in r[0] for r in browser["stations"]["rows"]))
        for label, text in (("missing", None), ("not JSON", "{not json"), ("not an object", "null"),
                            ("days that are not a list", '{"f": "hail-station-v2", "days": "x"}')):
            with self.subTest(label):
                folder = self.gate_copy()
                path = folder / "hail" / "s" / "1LM.json"
                if text is None:
                    path.unlink()
                else:
                    path.write_text(text, encoding="utf-8")
                browser, module = self.both_ways(folder)
                got = browser["stations"]
                self.assertEqual(got["unavailable"], self.STATION_UNAVAILABLE)
                self.assertEqual((got["lead"], got["rows"], got["lines"]), ("", [], []))
                self.assertEqual(got, module["stations"])

    def test_a_zone_file_that_did_not_load_keeps_the_point_records_and_says_so(self):
        """A zone file the browser cannot load (D27) makes the zone products section show its unavailable sentence and nothing
        else. The records section keeps the point records that loaded, with the partial sentence for the zone part: it names
        the zone and the reason (the file did not answer, or it was in an unexpected format). Each case matches describe_joins
        on the same folder: the zone file is removed, is not JSON, or is JSON whose records are not a list."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import joins as jn
        for label, text, reason in (("missing", None, jn.WORDS_JOINS["reason_no_answer"]),
                                    ("not JSON", "{not json", jn.WORDS_JOINS["reason_format"]),
                                    ("records that are not a list", '{"f": "hail-zone-v1", "records": "x"}',
                                     jn.WORDS_JOINS["reason_format"])):
            with self.subTest(label):
                folder = self.copy_site()
                path = folder / "hail" / "z" / "MTZ048.json"
                if text is None:
                    path.unlink()
                else:
                    path.write_text(text, encoding="utf-8")
                browser, module = self.both_ways(folder)
                zones = browser["zones"]
                self.assertEqual(zones["unavailable"], self.ZONE_UNAVAILABLE)
                self.assertEqual((zones["lead"], zones["fire_lead"], zones["rows"], zones["lines"]), ("", "", [], []))
                records = browser["records"]
                self.assertEqual(records["unavailable"], jn.WORDS_JOINS["partial"].format(
                    feed=jn.WORDS_JOINS["feed_records"], periods="MTZ048", reason=reason))
                texts = [r[0] for r in records["rows"]]
                self.assertTrue(any("thunderstorm wind" in t for t in texts))        # the point record within five miles stays
                self.assertFalse(any("winter storm" in t for t in texts))            # the zone's own records are missing
                self.assertNotEqual(records["lead"], "")
                self.assertEqual(browser, module)

    def test_a_fire_weather_zone_file_that_did_not_load_keeps_the_public_products(self):
        """D7, D17: a fire weather zone file that does not load leaves the public zone products as they are. The zone section
        gets the line that red flag warnings are not listed (the fire weather zones were not available) and no fire weather
        lead. The browser and describe_joins agree on the folder."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import joins as jn
        folder = self.copy_site()
        (folder / "hail" / "z" / "fire-MTZ117.json").unlink()
        browser, module = self.both_ways(folder)
        zones = browser["zones"]
        self.assertEqual(zones["unavailable"], "")
        self.assertIn(jn.WORDS_JOINS["zones_fire_unavailable"], zones["lines"])
        self.assertEqual(zones["fire_lead"], "")
        self.assertTrue(any(r[0].startswith("Zone product: High wind warning:") for r in zones["rows"]))
        self.assertEqual(browser, module)

    def test_a_cancelled_zone_product_at_or_before_its_begin_reads_cancelled_at_as_the_module_does(self):
        """D26: a cancellation at or before the product's begin reads "cancelled at {time}" in place of the span, in the module
        and in the sheet alike. The gate cell's zone file gets such a product here (the row is built in this test): a winter
        storm warning that begins at 6 am Montana time and is cancelled an hour earlier."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import joins as jn
        folder = self.copy_site()
        path = folder / "hail" / "z" / "MTZ048.json"
        zone = json.loads(path.read_text(encoding="utf-8"))
        zone["events"].append({"k": "WS", "s": "W", "b": "2025-06-15T12:00Z", "e": "2025-06-15T11:00Z", "st": "cancelled",
                               "o": "BYZ"})
        path.write_text(json.dumps(zone, separators=(",", ":")), encoding="utf-8")
        browser, module = self.both_ways(folder)
        self.assertEqual(browser["zones"], module["zones"])
        winter = [r[0] for r in browser["zones"]["rows"] if r[0].startswith("Zone product: Winter storm warning:")]
        self.assertEqual(len(winter), 1)
        self.assertIn(jn.WORDS_JOINS["zones_cancelled_at"].format(time="Jun 15, 2025 5:00 am MDT"), winter[0])
        self.assertNotIn("Jun 15, 2025 6:00 am MDT to", winter[0])

    def test_an_upgraded_zone_product_reads_its_span_with_upgraded_and_one_upgraded_at_its_begin_reads_so(self):
        """D31: an upgrade ends the lower product at its upgrade time, and the span reads "{begin} to {end}, upgraded"; an
        upgrade at or before the begin reads "upgraded at {time}" in place of the span. Both rows are built here into the gate
        cell's zone file, and the browser and describe_joins agree on every section."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import joins as jn
        folder = self.copy_site()
        path = folder / "hail" / "z" / "MTZ048.json"
        zone = json.loads(path.read_text(encoding="utf-8"))
        zone["events"].append({"k": "HW", "s": "W", "b": "2025-06-15T20:00Z", "e": "2025-06-15T22:00Z", "st": "upgraded",
                               "o": "BYZ"})                                        # 2:00 pm to 4:00 pm, upgraded
        zone["events"].append({"k": "WS", "s": "W", "b": "2025-06-15T12:00Z", "e": "2025-06-15T12:00Z", "st": "upgraded",
                               "o": "BYZ"})                                        # upgraded at 6:00 am, the begin's own time
        path.write_text(json.dumps(zone, separators=(",", ":")), encoding="utf-8")
        browser, module = self.both_ways(folder)
        self.assertEqual(browser["zones"], module["zones"])
        rows = {r[0].split(": ")[1]: r[0] for r in browser["zones"]["rows"]}      # by the product's name (the row's second part)
        self.assertIn("Jun 15, 2025 2:00 pm MDT to 4:00 pm MDT" + jn.WORDS_JOINS["zones_upgraded"], rows["High wind warning"])
        self.assertIn(jn.WORDS_JOINS["zones_upgraded_at"].format(time="Jun 15, 2025 6:00 am MDT"), rows["Winter storm warning"])

    def test_each_joined_section_of_a_sample_build_carries_the_sample_label(self):
        """A sample build's six sections each say SAMPLE data, as the sheet's own tag does. map_data_joins writes the state
        "sample" for a sample build; this class's store is real-format, so the state is set here, and nothing else in the
        block depends on it."""
        if shutil.which("node") is None:
            self.skipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        from website import hail as hs
        from website import joins as jn
        h, tz = self.page_hail()
        row, col = hs.cell_for(47.025, -110.135)
        cell = [{"row": row, "col": col}]
        h["joins"]["state"] = "sample"
        got = node_join_sections(self.site, h, tz, cell)[0]
        for key in JOIN_IDS:
            self.assertEqual(got[key]["sample"], jn.WORDS_JOINS["sample"], key)
        h["joins"]["state"] = "loaded"
        got = node_join_sections(self.site, h, tz, cell)[0]
        for key in JOIN_IDS:
            self.assertEqual(got[key]["sample"], "", key)


class HailAddresses(unittest.TestCase):
    """The B3 layers (--hail-addresses, with --hail-history): the address dots and the typed-address search, the street
    lines and the building outlines, each from its module (website/addresses.py, streets.py, buildings.py). Off by
    default: no B3 key, words, form, legend line, About paragraph or contract row. --address-text off (D35) writes no
    address text, no search index and no form. A layer that did not load says so in words and the build goes on (D36).
    The browser checks are in tools/smoke_map.py (check_addresses, run with --addresses)."""

    B3_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    B3_HEADING = "Addresses, streets and building outlines"
    B3_ABOUT_END = "<h2>Base map imagery</h2>"
    B3_BEGIN, B3_END = "B3 layers: begin", "B3 layers: end"     # the markers of the B3 section in map.js
    B3_FORM = ("Find an address", 'id="address-input"', 'id="address-form"', 'id="address-results"')
    B3_LEGEND = ("Dots are addresses from Montana", "Each dot is one building outline", "Streets from the Montana State")
    # D29 and D34: no word of a B3 template says what a building is or who uses it. "use" and the others are checked as
    # whole words. The source's own quotes and labels are removed first (they are the sources' words, quoted exactly),
    # and so are the proper names that contain "Structures" (the two data sources' names).
    # The county file's quoted use sentence (sources.py census_counties, quoted from its metadata) is exempt as a quotation;
    # "occupancy" is forbidden outside a quotation (D45, R-04). The quotes go first (the purpose sentence holds a proper
    # name), then the proper names.
    B3_CENSUS_USE = ("These products are free to use in a product or publication, however acknowledgement must be given to the "
                     "U.S. Census Bureau as the source.")
    B3_EXEMPT = ("Use terms in the file's metadata", "Structures and Addresses Framework", "Structures/Addresses Framework",
                 "USA Structures", "Montana State Library Structures")
    B3_FORBIDDEN = re.compile(r"\b(homes?|houses?|residences?|dwellings?|use|structures?|occupancy)\b", re.I)

    @classmethod
    def setUpClass(cls):
        cls.dirs, cls.results = {}, {}
        builds = (("off", {}), ("history", {"hail_history": True}),
                  ("on", {"hail_history": True, "hail_addresses": True}),
                  ("notext", {"hail_history": True, "hail_addresses": True, "address_text": "off"}))
        for key, options in builds:
            out = Path(tempfile.mkdtemp(prefix=f"hailwatch-b3-{key}-"))
            cls.addClassCleanup(shutil.rmtree, out, True)
            cls.results[key] = site.build(out, None, cls.B3_NOW, sample=True, **options)
            cls.dirs[key] = out

    def test_the_b3_sizes_are_recorded_for_the_budgets(self):
        self.assertNotIn("b3_sizes", self.results["history"])
        sizes = self.results["on"]["b3_sizes"]
        self.assertEqual(set(sizes), {"outline_shards", "address_shards", "search_files", "road_shards"})
        self.assertGreater(sizes["address_shards"]["files"], 0)
        self.assertGreater(sizes["search_files"]["files"], 0)
        self.assertEqual(sizes["outline_shards"]["files"], 0)          # the sample has no outline part
        # D38 and D42: the totals are recorded beside their budgets (60 MB address shards and letter files, 250 MB outlines)
        self.assertEqual({k: v["budget_bytes"] for k, v in sizes.items()},
                         {"outline_shards": 250_000_000, "address_shards": 60_000_000, "search_files": 60_000_000,
                          "road_shards": None})
        self.assertTrue(all(v["within_budget"] for v in sizes.values()))
        self.assertEqual(sizes["address_shards"]["largest_bytes"],
                         max((self.dirs["on"] / "hail" / "a").glob("*.json"), key=lambda p: p.stat().st_size).stat().st_size)

    def html_text(self, html: str) -> str:
        import html as html_lib
        return html_lib.unescape(re.sub(r"<[^>]+>", " ", html))

    def test_the_flags_need_the_history_flag_and_the_text_mode_needs_the_flag(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b3-flags-"))
        self.addCleanup(shutil.rmtree, out, True)
        with self.assertRaises(ValueError):
            site.build(out, None, self.B3_NOW, sample=True, hail_addresses=True)
        with self.assertRaises(ValueError):
            site.build(out, None, self.B3_NOW, sample=True, hail_history=True, address_text="maybe")
        for argv, message in ((["--hail-addresses"], "--hail-addresses needs --hail-history"),
                              (["--hail-history", "--address-text", "off"],
                               "--address-text off needs --hail-addresses"),
                              (["--hail-history", "--hail-addresses", "--address-text", "maybe"], "invalid choice")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                site.main(["--out", str(out), "--sample", *argv])
            self.assertIn(message, err.getvalue(), argv)

    def test_the_flag_off_builds_have_no_address_layer_key_words_form_row_or_text(self):
        for key in ("off", "history"):
            out = self.dirs[key]
            m = json.loads(page(out, "data/map.json"))
            for name in ("addresses", "roads", "buildings", "attribution"):
                self.assertNotIn(name, m.get("hail", {}), key)
            for path in sorted(out.rglob("*.html")):
                text = path.read_text(encoding="utf-8")
                for words in (self.B3_HEADING, *self.B3_FORM, *self.B3_LEGEND, "Montana State Library address points",
                              "USA Structures, Oak Ridge", "Oak Ridge National Laboratory and FEMA, USA Structures"):
                    self.assertNotIn(words, text, f"{words!r} in {key}/{path.name}")

    def test_a_history_build_without_the_addresses_flag_has_no_contract_row_for_a_layer(self):
        about = page(self.dirs["history"], "about.html")
        for key in ("msl_addresses", "msl_roads", "census_roads", "usa_structures", "census_counties"):
            self.assertNotIn(src.CONTRACTS[key]["name"], about, key)
        self.assertNotIn(src.CONTRACTS["lsr"]["name"], about)       # superseded by iem_lsr (B5): listed once, as the B5 row
        self.assertIn(src.CONTRACTS["iem_lsr"]["name"], about)      # the B2 reports still show with the history, through it

    def test_the_sample_build_with_both_flags_has_the_address_layer_and_two_unavailable_layers(self):
        from website import buildings, streets
        out = self.dirs["on"]
        m = json.loads(page(out, "data/map.json"))["hail"]
        self.assertEqual(m["addresses"]["state"], "sample")
        self.assertGreater(m["addresses"]["count"], 0)
        self.assertEqual(m["addresses"]["text"], "on")
        for key in ("roads", "buildings"):
            self.assertEqual(m[key]["state"], "unavailable", key)
            self.assertTrue(m[key]["problem"], key)
        # the address list loaded, so its line is there (D44); the two layers that did not load name no source (D29)
        self.assertEqual(len(m["attribution"]), 1)
        self.assertTrue(m["attribution"][0].startswith("Addresses: Montana State Library, Structures and Addresses Framework"))
        status = json.loads(page(out, "data/state.json"))["status"]
        self.assertTrue(status["address_list"]["ok"])
        self.assertFalse(status["street_list"]["ok"])
        self.assertFalse(status["outline_list"]["ok"])
        self.assertTrue(status["hail_history"]["ok"])
        html = page(out, "map.html")
        for words in self.B3_FORM:
            self.assertIn(words, html)
        self.assertIn("SAMPLE data", html)                             # the fixture's address list is labelled
        for words in self.B3_LEGEND[:1] + (streets.WORDS_STREETS["msl"]["unavailable"],
                                           buildings.WORDS_BUILDINGS["unavailable"]):
            self.assertIn(words, html)
        about = page(out, "about.html")
        self.assertIn(self.B3_HEADING, about)
        self.assertIn(streets.WORDS_STREETS["msl"]["unavailable"], about)
        self.assertIn(buildings.WORDS_BUILDINGS["unavailable"], about)
        self.assertIn(src.CONTRACTS["msl_addresses"]["name"], about)
        self.assertIn(src.CONTRACTS["usa_structures"]["name"], about)
        self.assertNotIn(src.CONTRACTS["msl_roads"]["name"], about)    # no road part was built, so no road row (D25)
        self.assertNotIn(src.CONTRACTS["census_roads"]["name"], about)

    def test_a_row_is_shown_only_for_the_layer_that_is_built(self):
        shown = site.contract_shown
        self.assertTrue(shown("msl_addresses", False, True, True, None))
        self.assertFalse(shown("msl_addresses", False, True, False, None))
        self.assertFalse(shown("msl_addresses", False, False, True, None))
        self.assertTrue(shown("census_roads", False, True, True, "census_roads"))
        self.assertFalse(shown("msl_roads", False, True, True, "census_roads"))
        self.assertFalse(shown("census_roads", False, True, True, None))
        self.assertFalse(shown("msl_roads", False, True, False, "msl_roads"))
        self.assertTrue(shown("census_counties", False, True, True, None))          # gated like the other B3 rows
        self.assertFalse(shown("census_counties", False, True, False, None))
        self.assertFalse(shown("census_counties", False, False, True, None))
        self.assertTrue(shown("lsr", False, True, False, None))

    def test_the_b3_contract_rows_name_their_files_and_their_limits(self):
        for key in ("msl_addresses", "msl_roads", "census_roads", "usa_structures", "census_counties"):
            self.assertEqual(set(src.CONTRACTS[key]), {"name", "request", "units", "timing", "missing"}, key)
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in src.CONTRACTS[key].values()), key)
        request = src.CONTRACTS
        self.assertIn("StructuresFramework_shp.zip", request["msl_addresses"]["request"])
        self.assertIn("Montana State Plane grid", request["msl_addresses"]["units"])
        self.assertIn("for no other purpose", request["msl_addresses"]["missing"])
        self.assertIn("Transportation Framework", request["msl_roads"]["request"])
        self.assertIn("for no other purpose", request["msl_roads"]["missing"])
        self.assertIn("TIGER2026", request["census_roads"]["request"])
        self.assertIn("acknowledgement must be given to the U.S. Census Bureau", request["census_roads"]["missing"])
        self.assertIn("registered trademarks", request["census_roads"]["missing"])
        self.assertIn("high-precision measurement", request["census_roads"]["missing"])
        self.assertIn("MT_Structures_20260913.zip", request["usa_structures"]["request"])
        self.assertIn("15 metres", request["usa_structures"]["units"])
        self.assertIn("Only the outline geometry is", request["usa_structures"]["request"])
        self.assertIn("not surveys", request["usa_structures"]["timing"] + request["usa_structures"]["missing"])
        # D45 (R-04): no attribute field is named as read, and "occupancy" appears only in a quotation (none here)
        self.assertIn("other field of the file is ever read, stored or shown", request["usa_structures"]["request"])
        self.assertNotIn("occupancy", request["usa_structures"]["request"])
        # D48: the county row quotes its file's own use sentence (cb_2025_us_county_500k.zip metadata); the TIGER road
        # files' "not copyrighted" words are theirs, and the county row does not claim them
        self.assertIn("cb_2025_us_county_500k.zip", request["census_counties"]["request"])
        self.assertIn("acknowledgement must be given to the U.S. Census Bureau as the source", request["census_counties"]["missing"])
        self.assertIn("should not be used for geocoding addresses", request["census_counties"]["missing"])
        self.assertIn("label, not a measurement", request["census_counties"]["missing"])
        self.assertNotIn("not copyrighted", request["census_counties"]["missing"])
        self.assertIn("census_counties", site.B3_ROWS)

    def test_the_about_page_states_the_attribution_and_no_counsel_reasoning_about_the_outline_licence(self):
        # The licence reading is open with counsel (D14, counsel item 1): the About page gives the attribution only.
        for key in ("on", "notext"):
            about = " ".join(page(self.dirs[key], "about.html").split())
            self.assertNotIn("licence reading", about, key)
            self.assertNotIn("Data.gov", about, key)
            self.assertIn("Oak Ridge National Laboratory and FEMA, USA Structures", about, key)

    def test_the_address_text_off_build_writes_no_search_no_form_and_no_address_text(self):
        from website import hail as hs
        out = self.dirs["notext"]
        self.assertFalse((out / "hail" / "a" / "idx").exists())
        m = json.loads(page(out, "data/map.json"))["hail"]
        self.assertEqual(m["addresses"]["text"], "off")
        self.assertEqual(m["buildings"]["text"], "off")
        for key in ("cities", "letter", "words", "search_words", "dir", "file_key"):
            self.assertNotIn(key, m["addresses"], key)
        self.assertNotIn("title", m["addresses"]["templates"])
        html = page(out, "map.html")
        for words in self.B3_FORM:
            self.assertNotIn(words, html)
        self.assertIn("Dots are addresses from Montana", html)         # the legend line names no address
        self.assertNotIn("What you type stays in your browser.", page(out, "about.html"))
        hs.check_manifest(out)                                         # the copied files match the rewritten manifest
        texts = []
        for path in sorted((out / "hail" / "a").glob("*.json")):
            for row in json.loads(path.read_text(encoding="utf-8"))["a"]:
                self.assertEqual(row[2:5], ["", "", ""], path.name)
                self.assertEqual(len(row), 6, path.name)
            texts.append(path.read_text(encoding="utf-8"))
        self.assertNotIn("Billings", "".join(texts))
        on = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.dirs["on"] / "hail" / "a").glob("*.json"))]
        self.assertTrue(any(row[2] for doc in on for row in doc["a"]))  # the text-on build keeps the text

    def test_the_address_text_on_build_keeps_the_text_and_the_search_index(self):
        out = self.dirs["on"]
        self.assertTrue((out / "hail" / "a" / "idx" / "cities.json").is_file())
        m = json.loads(page(out, "data/map.json"))["hail"]["addresses"]
        self.assertEqual(m["cities"], "hail/a/idx/cities.json")
        self.assertEqual(m["letter"], "hail/a/idx/{dir}/{key}.json")

    def test_a_failed_text_strip_removes_the_address_files_and_says_the_layer_failed(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b3-strip-"))
        self.addCleanup(shutil.rmtree, out, True)
        with mock.patch.object(site, "strip_address_text", side_effect=OSError("disk full")):
            result = site.build(out, None, self.B3_NOW, sample=True, hail_history=True, hail_addresses=True,
                                address_text="off")
        self.assertFalse((out / "hail" / "a").exists())
        m = json.loads(page(out, "data/map.json"))["hail"]
        self.assertEqual(m["addresses"]["state"], "unavailable")
        self.assertIn("couldn't be prepared", m["addresses"]["problem"])
        self.assertFalse(result["status"]["address_list"]["ok"])
        self.assertNotIn('id="address-input"', page(out, "map.html"))

    def test_a_store_that_is_missing_marks_the_three_layers_unavailable_with_its_reason(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b3-missing-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, None, self.B3_NOW, sample=True, hail_history=True, hail_addresses=True,
                            hail_store_path=str(out / "no-such-store.tar.gz"))
        m = json.loads(page(out, "data/map.json"))["hail"]
        for key in ("addresses", "roads", "buildings"):
            self.assertEqual(m[key]["state"], "unavailable", key)
            self.assertIn("missing", m[key]["problem"], key)
        self.assertEqual(m["attribution"], [])
        self.assertFalse(result["status"]["hail_history"]["ok"])
        for key in ("address_list", "street_list", "outline_list"):
            self.assertFalse(result["status"][key]["ok"], key)
        html = page(out, "map.html")
        self.assertNotIn('id="address-input"', html)
        self.assertIn("address list could not be loaded in this update", html)

    def test_strip_address_text_writes_no_text_and_a_manifest_that_checks(self):
        from website import hail as hs
        root = Path(tempfile.mkdtemp(prefix="hailwatch-b3-unit-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "hail" / "a" / "idx" / "billings").mkdir(parents=True)
        (root / "hail" / "b").mkdir()
        shard = {"f": "hail-addresses-v1", "b": [-108.5, 45.7, -108.4, 45.8], "n": 1,
                 "a": [[-108.45, 45.78, "401 North 27th Street", "Billings", "59101", "S"]]}
        (root / "hail" / "a" / "r0092_c0213123.json").write_text(json.dumps(shard), encoding="utf-8")
        (root / "hail" / "a" / "idx" / "cities.json").write_text(
            json.dumps({"f": "hail-address-cities-v1", "cities": {"Billings": {"n": 1, "keys": {"N": 1}}}}),
            encoding="utf-8")
        (root / "hail" / "a" / "idx" / "billings" / "N.json").write_text(
            json.dumps({"f": "hail-address-idx-v1", "a": [["401", "North 27th Street", "", -108.45, 45.78, "59101", "S"]]}),
            encoding="utf-8")
        outline = {"f": "hail-buildings-v1", "b": [-108.5, 45.7, -108.4, 45.8], "n": 1, "m": 1, "c": ["Billings", "59101"],
                   "a": [{"p": [-108.45, 45.78], "g": [[[-108.46, 45.77], [-108.44, 45.77], [-108.44, 45.79],
                                                         [-108.46, 45.77]]],
                          "l": ["401 North 27th Street"], "z": [None]}]}
        (root / "hail" / "b" / "r0092_c0213123.json").write_text(json.dumps(outline), encoding="utf-8")
        index = {"format": hs.FORMAT, "as_of": "2026-10-15", "window": ["2021-10-15", "2026-10-15"], "missing_days": [],
                 "floor_tenths": 64, "tiles": [], "d0": hs.D0.isoformat(), "grid": dict(hs.GRID)}
        (root / "hail" / "index.json").write_text(json.dumps(index), encoding="utf-8")

        def entry(rel):
            data = (root / rel).read_bytes()
            return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

        rels = sorted(p.relative_to(root).as_posix() for p in (root / "hail").rglob("*.json") if p.name != "manifest.json")
        manifest = {"format": hs.MANIFEST_FORMAT, "as_of": "2026-10-15", "sample": True, "counts": {},
                    "files": {rel: entry(rel) for rel in rels}}
        (root / "hail" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        site.strip_address_text(root)
        self.assertFalse((root / "hail" / "a" / "idx").exists())
        doc = json.loads((root / "hail" / "a" / "r0092_c0213123.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["a"], [[-108.45, 45.78, "", "", "", "S"]])
        bdoc = json.loads((root / "hail" / "b" / "r0092_c0213123.json").read_text(encoding="utf-8"))
        self.assertIsNone(bdoc["c"])
        self.assertNotIn("l", bdoc["a"][0])
        self.assertNotIn("z", bdoc["a"][0])
        self.assertEqual(bdoc["a"][0]["p"], [-108.45, 45.78])
        self.assertEqual(bdoc["m"], 1)
        listed = json.loads((root / "hail" / "manifest.json").read_text(encoding="utf-8"))["files"]
        self.assertFalse(any(name.startswith("hail/a/idx/") for name in listed))
        hs.check_manifest(root)

    def test_only_the_addresses_flag_copies_the_store_address_outline_and_road_folders(self):
        from website import hail as hs
        self.assertFalse((self.dirs["off"] / "hail").exists())             # no history folder without --hail-history
        out = self.dirs["history"]
        for folder in ("a", "b", "r"):
            self.assertFalse((out / "hail" / folder).exists(), f"history has hail/{folder}")
        listed = json.loads(page(out, "hail/manifest.json"))["files"]
        self.assertFalse([name for name in listed if name.split("/")[1] in ("a", "b", "r")])
        hs.check_manifest(out)
        self.assertTrue((self.dirs["on"] / "hail" / "a" / "idx").is_dir())
        hs.check_manifest(self.dirs["on"])

    def test_the_history_copy_drops_the_b3_blocks_files_and_folders_and_still_checks_out(self):
        # D35 and gate B3-6: a history build without --hail-addresses has no B3 index block, file, folder or manifest
        # entry. The synthetic store holds every B3 part (the fixture, counts.json, hail/b/, hail/r/ and the three blocks);
        # with the flag on, the copy keeps all of them.
        from website import addresses as ad, buildings as bd, hail as hs, streets as st
        root = Path(tempfile.mkdtemp(prefix="hailwatch-b3-store-"))
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(hs.FIXTURE_DIR / "hail", root / "hail")
        (root / "hail" / "counts.json").write_bytes(b'{"f": "hail-buildings-counts-v1"}')
        for folder in ("b", "r"):
            (root / "hail" / folder).mkdir()
            (root / "hail" / folder / "r0000_c0000.json").write_bytes(b'{"f": "test"}')
        index = json.loads((root / "hail" / "index.json").read_text(encoding="utf-8"))
        for key in (ad.INDEX_KEY, st.INDEX_KEY, bd.INDEX_KEY):
            index[key] = {"state": "loaded", "sample": True}
        (root / "hail" / "index.json").write_bytes(hs._pretty(index))
        manifest = json.loads((root / "hail" / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"] = {}
        for path in sorted((root / "hail").rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                data = path.read_bytes()
                manifest["files"][path.relative_to(root).as_posix()] = {
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        (root / "hail" / "manifest.json").write_bytes(hs._pretty(manifest))
        hs.check_manifest(root)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b3-copy-"))
        self.addCleanup(shutil.rmtree, out, True)
        kept = site._copy_hail(root, out / "off", index, addresses=False)
        hail_off = out / "off" / "hail"
        for name in ("a", "b", "r", "counts.json"):
            self.assertFalse((hail_off / name).exists(), name)
        written = json.loads((hail_off / "index.json").read_text(encoding="utf-8"))
        for key in (ad.INDEX_KEY, st.INDEX_KEY, bd.INDEX_KEY):
            self.assertNotIn(key, written)
            self.assertNotIn(key, kept)
        listed = json.loads((hail_off / "manifest.json").read_text(encoding="utf-8"))["files"]
        self.assertFalse([rel for rel in listed if rel.split("/")[1] in ("a", "b", "r", "counts.json")])
        self.assertEqual(listed["hail/index.json"]["sha256"],
                         hashlib.sha256((hail_off / "index.json").read_bytes()).hexdigest())
        hs.check_manifest(out / "off")
        site._copy_hail(root, out / "on", index, addresses=True)
        hail_on = out / "on" / "hail"
        for name in ("a", "b", "r", "counts.json"):
            self.assertTrue((hail_on / name).exists(), name)
        self.assertEqual({ad.INDEX_KEY, st.INDEX_KEY, bd.INDEX_KEY} & set(json.loads(page(out / "on", "hail/index.json"))),
                         {ad.INDEX_KEY, st.INDEX_KEY, bd.INDEX_KEY})
        hs.check_manifest(out / "on")
        # The sample history build (no flag) carries none of the B3 blocks or files either.
        history = self.dirs["history"]
        history_index = json.loads(page(history, "hail/index.json"))
        self.assertFalse({"addresses", "roads", "buildings"} & set(history_index))
        self.assertFalse((history / "hail" / "counts.json").exists())
        hs.check_manifest(history)

    def test_the_b3_words_and_the_rendered_b3_sections_say_no_forbidden_word(self):
        from website import addresses as ad, buildings as bd, streets as st
        # the longest quotes first: the TIGER acknowledgement is a part of the county file's sentence, so it must not go first
        exempt = (self.B3_CENSUS_USE, ad.PURPOSE_TEXT, ad.USE_DISCLAIMER_TEXT, ad.USE_CONVENIENCE_TEXT, ad.ACCCONST_TEXT,
                  st.TIGER_ACK, st.TIGER_TRADEMARK, st.TIGER_ACCURACY) + self.B3_EXEMPT
        texts = [*ad.WORDS_ADDRESSES.values(), *bd.WORDS_BUILDINGS.values(), site.FIND_BUTTON]
        for kind in st.WORDS_STREETS.values():
            texts += list(kind.values())
        for key in ("msl_addresses", "msl_roads", "census_roads", "usa_structures", "census_counties"):
            texts += list(src.CONTRACTS[key].values())
        on = self.dirs["on"]
        about = page(on, "about.html")
        texts.append(self.html_text(about[about.index('<h2 id="addresses">'):about.index(self.B3_ABOUT_END)]))
        texts += json.loads(page(on, "data/map.json"))["hail"]["attribution"]     # the map's own attribution lines (D29, D44)
        map_html = page(on, "map.html")
        start = map_html.index('<section class="glass find"')
        texts.append(self.html_text(map_html[start:map_html.index("</section>", start)]))
        texts += [self.html_text(line) for line in re.findall(r'<p class="legend-tap" data-layer=[^\n]*', map_html)]
        for text in texts:
            self.assertNotIn("\u2014", text)                     # no em dash
            self.assertNotIn("\u2013", text)                     # no en dash
            rest = text
            for quote in exempt:
                rest = rest.replace(quote, " ")
            self.assertIsNone(self.B3_FORBIDDEN.search(rest), text)

    def test_the_map_attribution_carries_the_addresses_line_first_with_the_library_terms(self):
        from website import addresses as ad
        for key in ("on", "notext"):                  # the address text mode does not change the source's line
            lines = json.loads(page(self.dirs[key], "data/map.json"))["hail"]["attribution"]
            address = [line for line in lines if line.startswith(smoke_map().ADDRESS_ATTRIBUTION_START)]
            self.assertEqual(len(address), 1, key)                              # D44: the line the smoke expects
            self.assertIn(ad.USE_CONVENIENCE_TEXT, address[0], key)             # the quoted use sentence (D17)
            self.assertEqual(lines[0], address[0], key)                         # the Library's line comes first
        about = " ".join(page(self.dirs["on"], "about.html").split())
        self.assertIn("Source: Montana State Library Structures and Addresses Framework, file dated", about)  # D44: About

    def test_the_phone_legend_holds_no_b3_sentence_and_the_find_panel_sits_behind_a_button(self):
        # D43 (R-01): the two B3 legend sentences are in the layer menu, not on the legend card; at a phone width the find
        # panel is behind the Find an address button (map.css), so the card does not cover the map's centre. The legend's
        # height and the centre tap are measured in Chromium (tools/smoke_map.py: check_phone_legend and check_taps).
        html = page(self.dirs["on"], "map.html")
        card = html[html.index('id="legend"'):html.index('<a class="mapdata"')]
        self.assertNotIn('data-layer="shapes"', card)
        self.assertNotIn('data-layer="dots"', card)
        self.assertIn("Tap or click the map for the five-year hail history", card)
        menu = html[html.index('id="b3-keys"'):html.index('id="btn-list"')]
        self.assertIn('data-layer="shapes"', menu)
        self.assertIn('data-layer="dots"', menu)                  # the sample has no outlines, so the dots line stays
        self.assertIn('data-layer="streets"', menu)
        self.assertEqual(html.count('id="btn-find"'), 1)
        self.assertIn('aria-controls="find"', html)
        self.assertNotIn('id="btn-find"', page(self.dirs["notext"], "map.html"))
        css = (ROOT / "website" / "static" / "map" / "map.css").read_text(encoding="utf-8")
        self.assertIn(".icon-btn.find-open { display: none; }", css)
        self.assertIn("@media (max-width: 520px) {\n  .icon-btn.find-open { display: grid; }\n"
                      "  .top:not(.find-shown) > #find { display: none; }\n"
                      "  .top.find-shown .legend-wrap { display: none; }\n}", css)
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn('b3FindOpen(!el.top.classList.contains("find-shown"))', js)

    def test_the_outlines_line_stands_in_for_the_dot_sentence_when_the_outlines_load(self):
        # D48 (R-05): the unmatched-address sentence shows only when the outline layer is absent; build.py's b3_words sets the
        # flag, and map.html guards both places the sentence is printed (the layer menu and the no-script text).
        from website import addresses as ad, buildings as bd, streets as st
        loaded = {"state": "loaded", "sample": True}
        missing = {"state": "unavailable", "reason": "not built"}
        found = {ad.INDEX_KEY: loaded, st.INDEX_KEY: missing, bd.INDEX_KEY: loaded}
        self.assertTrue(site.b3_words(found, "on")["outlines_loaded"])
        found[bd.INDEX_KEY] = missing
        self.assertFalse(site.b3_words(found, "on")["outlines_loaded"])
        template = (ROOT / "website" / "templates" / "map.html").read_text(encoding="utf-8")
        self.assertEqual(template.count("{% if not b3.outlines_loaded %}"), 2)
        self.assertEqual(template.count("{{ b3.legend.dots }}"), 2)
        self.assertIn("Dots are addresses from Montana", page(self.dirs["on"], "map.html"))   # no outlines in the sample: shown

    def test_the_about_names_the_county_file_only_when_its_counts_were_made(self):
        from website import addresses as ad, buildings as bd, streets as st
        made = {"state": "loaded", "sample": True, "counties": {"state": "loaded"}}
        found = {ad.INDEX_KEY: {"state": "loaded", "sample": True}, st.INDEX_KEY: {"state": "unavailable", "reason": "x"},
                 bd.INDEX_KEY: made}
        self.assertTrue(site.counties_loaded(found))
        self.assertEqual(site.b3_words(found, "on")["about"]["counties"], bd.COUNTY_ACK)
        made["counties"] = {"state": "unavailable", "reason": "the county file could not be read"}
        self.assertFalse(site.counties_loaded(found))
        self.assertEqual(site.b3_words(found, "on")["about"]["counties"], "")
        self.assertFalse(site.counties_loaded({}))
        # the sample's outlines are unavailable, so About prints no county paragraph (no empty one either)
        about = page(self.dirs["on"], "about.html")
        self.assertNotIn(bd.COUNTY_ACK, about)
        self.assertNotIn("<p> </p>", about)
        self.assertIn(src.CONTRACTS["census_counties"]["name"], about)

    def test_map_script_b3_section_holds_no_sentence_unit_radius_zoom_cap_width_or_colour_literal(self):
        from website import addresses as ad, buildings as bd, streets as st
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b(houses?|residences?|dwellings?)\b", js, re.I))
        begin, end = js.find(self.B3_BEGIN), js.find(self.B3_END)
        self.assertTrue(begin >= 0 and end > begin, "map.js needs the B3 section between the two markers")
        block = js[begin:end]
        code = re.sub(r"/\*.*?\*/|//[^\n]*", " ", block, flags=re.S)  # comments may hold the words of the design
        literals = re.findall(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`([^`]*)`', code)
        for group in literals:
            text = group[0] or group[1] or group[2]
            words = text.split()
            self.assertFalse(len(words) >= 3, f"a sentence in the B3 section: {text!r}")
            self.assertIsNone(re.search(r"\b(mph|mm|inch|inches|miles?|metres?|kt|knots?)\b|%|°", text), text)
            self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", text), text)
        bare = re.sub(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`[^`]*`', " ", code)
        # A number on a line about a zoom, a radius, a width, a cap, a limit or a grid is a display rule and must come from
        # map.json. Geometry constants (0, 1, 2, 0.5, 180, 256, 360: the half turn, the tile size, the full turn) are allowed.
        rule_words = re.compile(r"radius|width|\bcap\b|zoom|\bz\b|\bZ\.|tap|\bpx\b|limit|per_view|grid|min_|max_|from\b")
        allowed = {"0", "1", "2", "0.5", "180", "256", "360"}
        flagged = []
        for line in bare.splitlines():
            if rule_words.search(line):
                flagged += [n for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", line) if n not in allowed]
        self.assertEqual(sorted(set(flagged)), [], "a display rule written in map.js (it must come from map.json)")
        for text in [*ad.WORDS_ADDRESSES.values(), *bd.WORDS_BUILDINGS.values(), *st.WORDS_STREETS["msl"].values()]:
            if "{" not in text and len(text) > 25:
                self.assertNotIn(text, js, text)
            elif "{" in text:
                for part in re.split(r"\{\w+\}", text):
                    if len(part) > 25:
                        self.assertNotIn(part, js, part)

    def test_the_workflow_previews_pass_the_addresses_flag_and_the_tests_and_smoke_run(self):
        text = (ROOT / ".github" / "workflows" / "website.yml").read_text(encoding="utf-8")
        args = [line for line in text.splitlines() if "args+=(" in line and "--hail-history" in line]
        self.assertEqual(len(args), 1)
        self.assertIn("--require-live --storm-layers --hail-history --hail-addresses", args[0])
        unit = [line for line in text.splitlines() if "python -m unittest" in line]
        self.assertEqual(len(unit), 1)
        self.assertIn("tests.test_streets", unit[0])
        self.assertIn("tests.test_buildings", unit[0])
        self.assertIn("python tools/smoke_map.py _site --addresses", text)
        self.assertIn('"tests/test_streets.py"', text)
        self.assertIn('"tests/test_buildings.py"', text)

    def test_the_smoke_test_has_the_address_checks(self):
        smoke = smoke_map()
        for name in ("check_addresses", "check_zoom_rules", "check_budget_and_pan", "check_taps", "check_attribution",
                     "check_search", "check_address_text_off"):
            self.assertTrue(callable(getattr(smoke, name, None)), name)
        self.assertEqual(smoke.ADDRESS_GATE_ZOOM, 15)                 # the zoom of the gate and the budget (D30)
        self.assertEqual(smoke.ADDRESS_FETCH_BUDGET_GZIP, 650 * 1024)
        self.assertEqual(smoke.ADDRESS_DRAW_MS, 30)
        self.assertEqual(smoke.PAN_FETCH_LIMIT, 20)
        self.assertEqual(smoke.B3_BILLINGS, (45.7857, -108.5071))     # 401 North 27th Street, Billings


class B3Completion(unittest.TestCase):
    """The B3 completion rulings that need no full build (D42 to D48): the unpack limits and their refusals, the address zoom
    rules run under node, the index rewrite of the address-text mode, and the workflow's install line. The builds and the
    browser are checked in HailAddresses (offline) and tools/smoke_map.py (in Chromium)."""

    def test_the_unpack_limits_are_800_mib_and_60000_files_and_hold_the_b3_store(self):
        from website import hail as hs
        self.assertEqual(hs.MAX_UNPACK_BYTES, 800 * 1024 * 1024)               # D42
        self.assertEqual(hs.MAX_UNPACK_FILES, 60000)
        # the B3 store as measured at the site re-check: 372,880,597 bytes in 31,129 files under hail/ (the fresh job store)
        self.assertLess(372880597, hs.MAX_UNPACK_BYTES)
        self.assertLess(31129, hs.MAX_UNPACK_FILES)

    def test_the_unpack_refuses_more_files_or_bytes_than_the_limits_and_reads_up_to_them(self):
        from website import hail as hs

        def archive(members):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for name, data in members:
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            return buf.getvalue()

        def stage():
            path = Path(tempfile.mkdtemp(prefix="hailwatch-unpack-"))
            self.addCleanup(shutil.rmtree, path, True)
            return path

        two = [("hail/index.json", b"{}"), ("hail/manifest.json", b"{}")]
        with mock.patch.object(hs, "MAX_UNPACK_FILES", 2):
            here = stage()
            hs._unpack_hail(archive(two), here)                                  # at the file limit: read
            self.assertTrue((here / "hail" / "index.json").is_file())
            with self.assertRaises(hs.HailStoreError) as ctx:
                hs._unpack_hail(archive(two + [("hail/a/x.json", b"{}")]), stage())
            self.assertIn("larger than the limits", str(ctx.exception))
        with mock.patch.object(hs, "MAX_UNPACK_BYTES", 4):
            here = stage()
            hs._unpack_hail(archive([("hail/index.json", b"{}")]), here)         # two bytes: within 4
            with self.assertRaises(hs.HailStoreError) as ctx:
                hs._unpack_hail(archive([("hail/index.json", b"{}"), ("hail/manifest.json", b"{}x")]), stage())
            self.assertIn("larger than the limits", str(ctx.exception))

    def test_the_address_zoom_keys_give_the_dots_and_the_chooser_zoom_without_outlines(self):
        # D47 (R-02): an address-only build has no outline zoom and no street zoom; its own zoom keys still set the dots
        # (15) and the search's zoom (17), and the top zoom the map may reach is at least the chooser's.
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        code = js_function(js, "b3Zoom")

        def zoom(h):
            done = subprocess.run([node, "-e", code + f"\nconsole.log(JSON.stringify(b3Zoom({json.dumps(h)})));"],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr[-500:])
            return json.loads(done.stdout)

        only_addresses = zoom({"addresses": {"zoom": {"dots": 15, "choose": 17}}})
        self.assertEqual((only_addresses["dots"], only_addresses["choose"], only_addresses["top"]), (15, 17, 17))
        with_outlines = zoom({"addresses": {"zoom": {"dots": 15, "choose": 17}},
                              "buildings": {"zoom": {"dots": 15, "fills": 16, "emphasis": 17, "counts": 13}},
                              "roads": {"zoom": {"arterials_from": 13, "local_from": 15, "names_from": 16}}})
        self.assertEqual((with_outlines["dots"], with_outlines["choose"], with_outlines["emphasis"]), (15, 17, 17))
        self.assertEqual(with_outlines["top"], 17)
        bare = zoom({})
        self.assertEqual(bare["top"], 0)
        self.assertIsNone(bare.get("dots"))                                      # undefined is left out of the JSON
        self.assertIn("B3.zoom.choose || B3.zoom.emphasis", js)                 # the chooser's zoom (b3Choose)

    def test_strip_address_text_drops_the_letter_counts_and_rewrites_the_index_and_its_manifest(self):
        from website import addresses as ad, hail as hs
        root = Path(tempfile.mkdtemp(prefix="hailwatch-b3-index-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "hail" / "a" / "idx" / "billings").mkdir(parents=True)
        shard = {"f": "hail-addresses-v1", "b": [-108.5, 45.7, -108.4, 45.8], "n": 1,
                 "a": [[-108.45, 45.78, "401 North 27th Street", "Billings", "59101", "S"]]}
        (root / "hail" / "a" / "r0092_c0213123.json").write_text(json.dumps(shard), encoding="utf-8")
        (root / "hail" / "a" / "idx" / "cities.json").write_text(
            json.dumps({"f": "hail-address-cities-v1", "cities": {"Billings": {"n": 1, "keys": {"N": 1}}}}), encoding="utf-8")
        (root / "hail" / "a" / "idx" / "billings" / "N.json").write_text(
            json.dumps({"f": "hail-address-idx-v1", "a": [["401", "North 27th Street", "", -108.45, 45.78, "59101", "S"]]}),
            encoding="utf-8")
        block = {"state": "loaded", "sample": True, "rows": 1, "shards": 1, "cities": 1, "letter_files": 1,
                 "largest_letter": {"city": "Billings", "key": "N", "rows": 1, "bytes": 90,
                                    "file": "hail/a/idx/billings/N.json"},
                 "two_character_files": 0, "over_limit_letter_files": [],
                 "largest_shard": {"name": "r0092_c0213123", "bytes": 999, "rows": 1},
                 "bytes": {"shards": 999, "letters": 90, "cities": 60, "words": 20, "idx": 170, "a": 1169},
                 "source": {"pubdate": "2026-09-30", "export_date": "2026-09-30"}}
        index = {"format": hs.FORMAT, "as_of": "2026-10-15", "window": ["2021-10-15", "2026-10-15"], "missing_days": [],
                 "floor_tenths": 64, "tiles": [], "d0": hs.D0.isoformat(), "grid": dict(hs.GRID), ad.INDEX_KEY: block}
        (root / "hail" / "index.json").write_text(json.dumps(index), encoding="utf-8")

        def entry(rel):
            data = (root / rel).read_bytes()
            return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

        rels = sorted(p.relative_to(root).as_posix() for p in (root / "hail").rglob("*.json") if p.name != "manifest.json")
        manifest = {"format": hs.MANIFEST_FORMAT, "as_of": "2026-10-15", "sample": True, "counts": {},
                    "files": {rel: entry(rel) for rel in rels}}
        (root / "hail" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        site.strip_address_text(root)
        written = json.loads((root / "hail" / "index.json").read_text(encoding="utf-8"))[ad.INDEX_KEY]
        for key in site.ADDRESS_LETTER_KEYS:                                       # R-07: the letter counts leave the block
            self.assertNotIn(key, written, key)
        self.assertEqual(written["rows"], 1)                                       # the rest of the block stays
        shard_bytes = (root / "hail" / "a" / "r0092_c0213123.json").stat().st_size
        self.assertEqual(written["bytes"], {"shards": shard_bytes, "a": shard_bytes})
        self.assertEqual(written["largest_shard"], {"name": "r0092_c0213123", "bytes": shard_bytes, "rows": 1})
        listed = json.loads((root / "hail" / "manifest.json").read_text(encoding="utf-8"))["files"]
        self.assertEqual(listed["hail/index.json"], entry("hail/index.json"))      # the manifest carries the new index
        hs.check_manifest(root)

    def test_the_workflow_installs_pyproj_and_pyogrio_as_compatible_releases_and_pins_nothing(self):
        text = (ROOT / ".github" / "workflows" / "website.yml").read_text(encoding="utf-8")
        installs = [line for line in text.splitlines() if "python -m pip install" in line and "pygrib" in line]
        self.assertEqual(len(installs), 1)
        self.assertIn('"pyproj~=3.8"', installs[0])                                # D19: a compatible release
        self.assertIn('"pyogrio~=0.13"', installs[0])
        self.assertIn("h5py", installs[0].split())                                 # the satellite reader's install is kept
        for line in text.splitlines():
            if "pip install" in line:
                self.assertNotIn("==", line)                                       # no pin on any pip line (D19)
        for module in ("tests.test_addresses", "tests.test_streets", "tests.test_buildings"):
            unit = [line for line in text.splitlines() if "python -m unittest" in line]
            self.assertEqual(len(unit), 1)
            self.assertIn(module, unit[0].split())


# ---------------------------------------------------------------- the five-season history (B5, --hail-history)

def jesc(text: str) -> str:
    """The text as Jinja writes it into a page (its autoescape: quotes and apostrophes as entities)."""
    from markupsafe import escape
    return str(escape(text))


def write_manifest(root: Path) -> None:
    """A test store's manifest: every file under hail/ with its bytes and SHA-256 (hail.check_manifest reads it)."""
    from website import hail as hs
    files = {}
    for path in sorted((root / "hail").rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            data = path.read_bytes()
            files[path.relative_to(root).as_posix()] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (root / "hail" / "manifest.json").write_text(json.dumps({"format": hs.MANIFEST_FORMAT, "files": files}), encoding="utf-8")


def fixture_store(variant: str = "full") -> Path:
    """A store tests/test_summary.py writes, with its manifest. The summary fixture writes the parts the five-season table
    reads; the joined records also read the lag, cover and clock keys of the B2 index, which are added here (their values
    are the fixture's own, as the real index gives them)."""
    from tests import test_summary as ts
    root, _ = ts.build_store(variant)
    path = root / "hail" / "index.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    joins_block = doc["joins"]
    joins_block.setdefault("cover", "")
    joins_block.setdefault("lags", {"ncei": None, "swdi": doc["as_of"], "warnings": doc["as_of"]})
    joins_block.setdefault("montana_time", [])
    joins_block.setdefault("shapes", {})
    joins_block.setdefault("types", {})
    path.write_text(json.dumps(doc), encoding="utf-8")
    write_manifest(root)
    return root


def set_index(root: Path, **blocks) -> None:
    """Change blocks of a test store's index and rewrite its manifest (so the store still checks out)."""
    path = root / "hail" / "index.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(blocks)
    path.write_text(json.dumps(doc), encoding="utf-8")
    write_manifest(root)


def visible(fragment: str) -> str:
    """The text a reader sees in an HTML fragment (tags out, entities back, blank runs squeezed)."""
    text = re.sub(r"<style>.*?</style>", " ", fragment, flags=re.S)
    text = re.sub(r"<(?:br|/?(?:p|li|h2|h3|h4|tr|table|ol|ul|section|details|summary))[^>]*>", "\n", text)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))




SHARED_STATIC = ("static/map/map.js", "static/map/map.css")   # left out of the identity check: they change with the feature
VERSION_QUERY = re.compile(rb"(static/map/map\.(?:js|css))\?v=[0-9a-f]{12}")


def default_digests(root: Path) -> dict:
    """Relative path -> digest for every file of a build: the bytes (the pages' ?v= hashes normalised), or for a PNG the
    decoded RGBA pixels with the size, so the encoder does not matter. Shared script and style files are left out."""
    from PIL import Image
    out = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name in SHARED_STATIC:
            continue
        if path.suffix == ".png":
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            digest = hashlib.sha256(f"{image.size[0]}x{image.size[1]}".encode() + image.tobytes()).hexdigest()
        else:
            data = path.read_bytes()
            if path.suffix == ".html":
                data = VERSION_QUERY.sub(rb"\1?v=HASH", data)
            digest = hashlib.sha256(data).hexdigest()
        out[name] = digest
    return out


def write_default_manifest(build_dir, base: str) -> Path:
    """Writes tests/fixtures/default-build-manifest.json from a default build of the base commit (its tree extracted, then
    python -m website.build --out <dir> --sample --now 2026-10-19T12:00:00Z run there). A PR that changes the default build
    on purpose runs this on its own build and commits the file, with the command in its description:
    python -c "import sys; sys.path.insert(0, 'tests'); import test_site as t; t.write_default_manifest('<dir>', '<base>')"
    """
    files = default_digests(Path(build_dir))
    path = ROOT / "tests" / "fixtures" / "default-build-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base": base, "build": "python -m website.build --sample --now 2026-10-19T12:00:00Z",
                                "files": files}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


class HailSwathLayers(unittest.TestCase):
    """The live hail swath layers (B4; website/swath.py) behind --storm-layers, sample builds only (the live feed is
    checked by the Website workflow and tools/smoke_map.py): the two Map layers and their status line, the List and the
    no-JavaScript panel (with the SAMPLE credit), the map page's two radios, the About bullet, the words, the browser's
    scans (map.js: no threshold, word, unit or numeric literal in the swath section), a layer that cannot be read, and
    the default build's identity with the base commit (B4-6)."""

    NOW_SWATH = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    SWATH_BASE = "c860e23"                  # the base of this stage: the default build must match its build (B4-6)
    # words that must not appear unless a negation comes before them (the same rule as test_swath's WordsTests)
    NEGATED = (("damage", "not "), ("observed hail", "not "), ("no hail", "same as "), ("dry", "not "),
               ("insurance", "not "), ("eligib", "not "), ("confirmed", "not "))
    HAIL_TITLES = ("Hail, last hour", "Hail, last 24 hours")

    @classmethod
    def setUpClass(cls):
        cls.off = Path(tempfile.mkdtemp(prefix="hailwatch-swath-off-"))
        cls.on = Path(tempfile.mkdtemp(prefix="hailwatch-swath-on-"))
        cls.addClassCleanup(shutil.rmtree, cls.off, True)      # only the folders this class made
        cls.addClassCleanup(shutil.rmtree, cls.on, True)
        cls.off_result = site.build(cls.off, None, cls.NOW_SWATH, sample=True)
        cls.on_result = site.build(cls.on, None, cls.NOW_SWATH, sample=True, storm_layers=True)
        cls.env = site.env()

    @staticmethod
    def panel(html: str) -> str:
        """The map page's <noscript> panel (the one with the class; the head has a style-only one)."""
        blocks = [b for b in re.findall(r"<noscript>.*?</noscript>", html, re.S) if 'class="noscript"' in b]
        assert len(blocks) == 1
        return blocks[0]

    def phrase(self, text: str) -> str:
        """The text as the page renders it (Jinja escapes an apostrophe)."""
        return self.env.from_string("{{ t }}").render(t=text)

    def test_the_flag_adds_the_two_layers_and_their_status_and_nothing_else_to_the_contract(self):
        off = json.loads(page(self.off, "data/map.json"))
        on = json.loads(page(self.on, "data/map.json"))
        self.assertEqual(set(on["layers"]), {"precip", "temp", "wind", "satellite", "hail_60", "hail_1440"})
        self.assertNotIn("hail_60", off["layers"])
        self.assertNotIn("hail_swath", off["status"])
        self.assertNotIn("hail_swath", json.loads(page(self.off, "data/state.json"))["status"])
        self.assertEqual(on["status"]["hail_swath"]["label"], "Hail swath (radar estimate)")
        self.assertNotIn("hail", on)                       # the flag does not turn on the history (B1's flag)
        self.assertTrue((self.on / "hail" / "live").is_dir())    # the live files are written with this flag
        self.assertFalse((self.on / "hail" / "t").exists())      # the history store (--hail-history) is not
        self.assertFalse((self.off / "hail").exists())           # and the default build writes no hail folder

    def test_the_swath_layers_carry_the_words_and_the_numbers_the_browser_fills(self):
        on = json.loads(page(self.on, "data/map.json"))
        for key, window, word, stamp, title in (("hail_60", 60, "hour", "202610191158", self.HAIL_TITLES[0]),
                                                ("hail_1440", 1440, "24 hours", "202610191130", self.HAIL_TITLES[1])):
            L = on["layers"][key]
            self.assertEqual((L["kind"], L["title"], L["unit"], L["window"], L["window_word"]),
                             ("hail_swath", title, "in", window, word))
            self.assertEqual((L["fresh_min"], L["stale_min"]), (20, 60) if window == 60 else (60, 120))
            self.assertEqual(L["live"]["pattern"], f"hail/live/{window}/{stamp}/{{tile}}.json")
            self.assertNotIn("?", L["live"]["pattern"])                       # the folder carries the time (D14)
            self.assertEqual(L["frames"][0]["src"], f"map/frames/hail-{window}-{stamp}.png")
            self.assertTrue((self.on / L["frames"][0]["src"]).is_file())
            self.assertTrue((self.on / "hail" / "live" / str(window) / stamp).is_dir())
            self.assertEqual((L["modes"], L["now_index"]), ({"12h": [0]}, {"12h": 0}))
            self.assertEqual(L["bounds"], [[43.0, -118.5], [50.5, -101.0]])
            self.assertTrue(L["sample"])
            self.assertEqual(L["valid"][:16], f"2026-10-19T{stamp[8:10]}:{stamp[10:12]}")
            for name in ("fresh", "stale", "unavailable", "age_out", "all_clear", "live_line", "no_estimate",
                         "no_coverage", "large_note", "sample_sheet", "outside", "hatch_key", "hatch_note",
                         "hatch_key_out", "hatch_note_out", "live_failed", "live_loading", "no_picture", "list_heading"):
                self.assertIn(name, L["words"], name)
            self.assertIn("{age}", L["words"]["fresh"])
            self.assertIn("{age}", L["words"]["stale"])
            self.assertIn("{window}", L["words"]["live_line"])
            self.assertEqual(L["live"]["tenths_per_inch"], 254)
            self.assertEqual(L["live"]["floor_tenths"], 64)

    def test_the_legend_has_every_class_with_its_inches_and_the_uncoloured_sentence(self):
        from website import hail as hs
        from website import swath as sw
        L = json.loads(page(self.on, "data/map.json"))["layers"]["hail_60"]
        self.assertEqual([e["label"] for e in L["legend"]], [f"{c['min_in']:.2f} in, {c['word']}" for c in reversed(hs.CLASSES)])
        self.assertEqual(len({e["color"] for e in L["legend"]}), len(hs.CLASSES))
        self.assertTrue(L["legend_note"].startswith("Sample: invented field, not NOAA MRMS MESH."), L["legend_note"])
        self.assertEqual(L["legend_uncoloured"], sw.WORDS_SWATH["uncoloured"].format(window=L["window_word"]))   # its own line
        self.assertEqual(L["legend_uncoloured"], "Uncoloured: no radar hail estimate of 0.25 in or more in the last hour, "
                         "or no value; NOAA's data does not tell the two apart.")
        for field in ("legend_note", "legend_uncoloured"):                          # no template left unfilled in the legend
            self.assertNotIn("{", L[field], field)
        self.assertNotIn(sw.WORDS_SWATH["uncoloured"].format(window=L["window_word"]), L["legend_note"])   # not repeated
        self.assertIn("not observed hail and not damage", L["legend_note"])

    def test_the_status_line_names_both_layers_with_their_valid_time_and_age(self):
        status = self.on_result["status"]["hail_swath"]
        self.assertTrue(status["ok"], status)
        self.assertEqual(status["detail"], "Hail, last hour: valid Oct 19, 5:58 am MDT, 2 min ago; "
                                           "Hail, last 24 hours: valid Oct 19, 5:30 am MDT, 30 min ago")
        state = json.loads(page(self.on, "data/state.json"))["status"]["hail_swath"]
        self.assertEqual(state["label"], "Hail swath (radar estimate)")

    def test_the_panel_and_the_list_carry_the_build_s_lines_and_credit_the_sample(self):
        html = page(self.on, "map.html")
        panel = self.panel(html)
        lines = self.on_result["content"]["hail_swath"]
        self.assertEqual(set(lines), set(self.HAIL_TITLES))
        self.assertIn("<h3>Hail swath (radar estimate)</h3>", panel)
        self.assertIn('<p class="sample-tag">SAMPLE: invented values, not NOAA data.</p>', panel)
        self.assertLess(panel.index("<h3>Satellite picture</h3>"), panel.index("<h3>Hail swath (radar estimate)</h3>"))
        self.assertLess(panel.index("<h3>Hail swath (radar estimate)</h3>"), panel.index("<h3>Radar echo tops</h3>"))
        template = re.search(r'<template id="storm-list">.*?</template>', html, re.S).group(0)
        self.assertIn('data-storm="hail"', template)
        self.assertIn('<h3 id="hail-swath-list-h">Hail swath (radar estimate)</h3>', template)
        for title in self.HAIL_TITLES:
            self.assertIn(f"<h4>{title}</h4>", panel)
            self.assertIn(f"<h4>{title}</h4>", template)
            for row in lines[title]:
                self.assertIn(f"<p>{self.phrase(row)}</p>", panel, row)
                self.assertIn(f"<p>{self.phrase(row)}</p>", template, row)
        self.assertIn("SAMPLE: invented radar estimate, not NOAA data.", " ".join(lines["Hail, last hour"]))

    def test_the_map_page_has_the_two_radios_after_the_weather_layers_and_only_with_the_flag(self):
        from website import swath as sw
        on, off = page(self.on, "map.html"), page(self.off, "map.html")
        self.assertEqual([p.title for p in sw.PRODUCTS], list(self.HAIL_TITLES))
        for value, title in (("hail_60", self.HAIL_TITLES[0]), ("hail_1440", self.HAIL_TITLES[1])):
            self.assertEqual(on.count(f'<input type="radio" name="layer" value="{value}">'), 1)
            self.assertIn(f'<span class="choice-text">{title}</span>', on)
            self.assertIn(f"sw-{value}", on)                       # the swatch is painted from the layer's legend
            self.assertNotIn(value, off)
        self.assertLess(on.index('value="satellite"'), on.index('value="hail_60"'))
        self.assertLess(on.index('value="hail_1440"'), on.index("<legend>Base map</legend>"))

    def test_the_about_page_has_the_bullet_with_the_contract_words_and_only_with_the_flag(self):
        about = page(self.on, "about.html")
        c = src.CONTRACTS["hail_swath"]
        self.assertIn("<strong>Hail swath (radar estimate)</strong> is NOAA's MRMS MESH (maximum estimated size of hail), "
                      "a radar estimate", about)
        self.assertIn("not observed hail and not damage", about)
        self.assertIn(self.phrase(c["name"]), about)
        self.assertIn("This is not an all-clear.", about)
        self.assertNotIn("Hail swath", page(self.off, "about.html"))
        self.assertNotIn(c["name"], page(self.off, "about.html"))

    def test_a_default_build_has_no_swath_word_in_any_page_or_data_file(self):
        for path in self.off.rglob("*"):
            if path.is_file() and path.suffix in (".html", ".json"):
                text = path.read_text(encoding="utf-8", errors="replace")
                for word in ("hail_60", "hail_1440", "Hail swath", "hail_swath", "hail/live"):
                    self.assertNotIn(word, text, f"{word!r} in {path.relative_to(self.off)}")

    def test_a_storm_layers_build_without_the_history_has_the_layers_and_no_sheet_words(self):
        on_map = page(self.on, "map.html")
        self.assertNotIn('id="hail-sheet"', on_map)           # the live line is part of the history sheet (--hail-history)
        self.assertNotIn("data-live", on_map)                 # made by the script, and only when a hail layer is on
        self.assertIn('value="hail_60"', on_map)

    def test_a_layer_that_cannot_be_read_still_builds_with_its_words_and_says_so(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-swath-down-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, FailingFetcher(), self.NOW_SWATH, storm_layers=True)
        self.assertFalse(result["status"]["hail_swath"]["ok"])
        self.assertIn("hail_swath", [k for k, v in result["status"].items() if not v["ok"]])
        on = json.loads(page(out, "data/map.json"))
        for key in ("hail_60", "hail_1440"):
            L = on["layers"][key]
            self.assertEqual((L["state"], L["frames"], L["modes"]), ("unavailable", [], {"12h": []}))
            self.assertTrue(L["state_line"].endswith("This is not an all-clear."), L["state_line"])
            self.assertIn("is unavailable: ", L["state_line"])
        self.assertIn("Hail swath problem", page(out, "map.html"))
        self.assertIn("Hail, last hour is unavailable: ", self.panel(page(out, "map.html")))
        self.assert_status_ends_with_all_clear(out)
        self.assert_swath_words_clean(out)

    def test_require_live_fails_when_a_swath_status_is_not_ok(self):
        from website import swath as sw
        real = sw.collect

        def one_stale(now, cache_dir, out_dir, towns, get=None, sample=False, offline=False):
            frames, files, states = real(now, cache_dir, out_dir, towns, get=get, sample=sample, offline=offline)
            states["hail_1440"]["ok"] = False                  # a stale day picture: not fresh, so not ok
            return frames, files, states
        out = Path(tempfile.mkdtemp(prefix="hailwatch-swath-live-"))
        self.addCleanup(shutil.rmtree, out, True)
        err = io.StringIO()
        argv = ["--out", str(out / "site"), "--sample", "--storm-layers", "--require-live", "--now", "2026-10-19T12:00:00Z"]
        with mock.patch.object(sw, "collect", one_stale), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            self.assertEqual(site.main(argv), 1)
        self.assertIn("Sources that failed or were stale: hail_swath", err.getvalue())

    def test_the_site_words_say_no_forbidden_term_and_no_dash(self):
        from website import swath as sw
        for name, text in list(sw.WORDS_SWATH.items()) + list(site.SWATH_SITE_WORDS.items()):
            self.assertNotIn("\u2014", text, name)          # no em dash
            self.assertNotIn("\u2013", text, name)          # no en dash
            low = text.lower()
            for word, before in self.NEGATED:
                for m in re.finditer(re.escape(word), low):
                    self.assertTrue(low[max(0, m.start() - len(before)):m.start()].endswith(before), f"{name}: {word}")
            for m in re.finditer(r"all-clear", low):
                self.assertEqual(low[max(0, m.start() - 7):m.start()], "not an ", f"{name}: all-clear")
            self.assertNotIn("clear", low.replace("all-clear", ""), f"{name}: clear")

    def test_the_live_swath_section_of_the_map_script_holds_no_threshold_word_unit_or_size_literal(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        start = js.index("live hail swath (--storm-layers builds, B4)")
        section = js[start:js.index("joined records at a spot (--hail-history builds, B2)")]
        code = re.sub(r"/\*.*?\*/", "", section, flags=re.S)           # comments out
        code = re.sub(r"//[^\n]*", "", code)
        strings = [a or b for a, b in re.findall(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', code)]
        bare = re.sub(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', '""', code)
        # the numbers left in the code: indexes (0, 1, 2) and the HTTP status of a tile with no live file (404, D4)
        self.assertEqual(set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", bare)), {"0", "1", "2", "404"})
        forbidden = ("0.25", "0.75", "1.00", "1.50", "2.00", "2.75", "25.4", "6.35", "pea", "penny", "quarter",
                     "ping-pong", "hen egg", "baseball", "mothball", "not observed", "not damage", "uncoloured",
                     "hatched", "valid ", "min ago", "older than", "all-clear", "basemap", "polygon", "geometry",
                     "estimate", "NOAA", "SAMPLE", "Montana", "in the last", "No radar")
        for text in strings:
            for word in forbidden:
                self.assertNotIn(word, text, f"{word!r} in the string {text!r}")
        for name in ("function hailView(", "function hailShowable(", "function hailWatch(", "function hailTick(",
                     "function liveText(", "function liveFile(", "function liveOpen(", "function liveAttach(",
                     "NO_FILE = 404"):
            self.assertIn(name, section, name)
        header = js[:js.index("*/")]
        self.assertIn("(D7)", header)                                  # the duties are documented in the header
        self.assertIn("(D16)", header)

    def assert_status_ends_with_all_clear(self, out: Path) -> None:
        """A failed swath status ends its line with the all-clear sentence on every page that shows the status (live-1):
        the index, About, the storm reports and a town page."""
        town = sorted((out / "town").glob("*.html"))[0].relative_to(out).as_posix()
        for name in ("index.html", "about.html", "reports.html", town):
            span = re.search(r'<span class="bad">Hail swath \(radar estimate\) problem: .*?</span>', page(out, name), re.S)
            self.assertIsNotNone(span, name)
            self.assertTrue(span.group(0).endswith("This is not an all-clear.</span>"), f"{name}: {span.group(0)[-80:]}")

    def assert_swath_words_clean(self, out: Path) -> None:
        """The words the swath layers show on the map page and the About page keep the rules (rules-6): the two Layers
        labels, the no-JavaScript panel, the List block (tags stripped), the About bullet and the "Hail swath problem" line."""
        def plain(html: str) -> str:
            return " ".join(re.sub(r"<[^>]+>", " ", html).split())
        map_html, about_html = page(out, "map.html"), page(out, "about.html")
        labels = [plain(m) for m in re.findall(r"<label[^>]*>.*?</label>", map_html, re.S) if "Hail, last" in m]
        self.assertEqual(len(labels), 2)
        block = re.search(r'<section class="storm-sec" data-storm="hail".*?</section>', map_html, re.S)
        bullet = re.search(r"<li><strong>Hail swath \(radar estimate\)</strong>.*?</li>", about_html, re.S)
        self.assertIsNotNone(block)
        self.assertIsNotNone(bullet)
        panel = self.panel(map_html)
        start = panel.index("Hail swath (radar estimate)</h3>")
        end = panel.find("<h3>", start + 5)
        swath_panel = panel[start:] if end < 0 else panel[start:end]          # the panel's swath part, up to the next heading
        words = plain(map_html)
        problem = words[words.index("Hail swath problem"):]
        problem = problem[:problem.index("This is not an all-clear.") + len("This is not an all-clear.")]
        for where, text in (("layer labels", " ".join(labels)), ("panel", plain(swath_panel)),
                            ("list", plain(block.group(0))), ("about bullet", plain(bullet.group(0))),
                            ("problem line", problem)):
            self.assert_clean_words(text, where)

    def assert_clean_words(self, text: str, where: str) -> None:
        """The swath's word rules on a rendered fragment: no dash; a damage, observed-hail or no-hail word only with its
        negation before it; "all-clear" only as "not an all-clear"; no bare "clear"."""
        self.assertNotIn("\u2014", text, where)
        self.assertNotIn("\u2013", text, where)
        low = text.lower()
        for word, before in self.NEGATED:
            for m in re.finditer(re.escape(word), low):
                self.assertTrue(low[max(0, m.start() - len(before)):m.start()].endswith(before), f"{where}: {word}")
        for m in re.finditer(r"all-clear", low):
            self.assertEqual(low[max(0, m.start() - 7):m.start()], "not an ", f"{where}: all-clear")
        self.assertNotIn("clear", low.replace("all-clear", ""), f"{where}: clear")

    def test_a_storm_layers_build_with_the_hail_history_builds_both_flags_together(self):
        """The preview's flags together (rules-3): the swath's live folder and the store's tiles share hail/, and the store
        copy merges into it (build.py _copy_hail, dirs_exist_ok). No FileExistsError; both folders are there."""
        out = Path(tempfile.mkdtemp(prefix="hailwatch-both-flags-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, None, self.NOW_SWATH, sample=True, storm_layers=True, hail_history=True)
        self.assertTrue(result["status"]["hail_swath"]["ok"], result["status"]["hail_swath"])
        self.assertTrue(result["status"]["hail_history"]["ok"], result["status"]["hail_history"])
        map_json = json.loads(page(out, "data/map.json"))
        self.assertEqual(map_json["hail"]["state"], "sample")
        pattern = map_json["layers"]["hail_60"]["live"]["pattern"]           # hail/live/60/<stamp>/{tile}.json
        self.assertTrue((out / pattern.split("{tile}")[0]).is_dir(), pattern)
        self.assertTrue((out / "hail" / "t").is_dir())
        for path in out.rglob("*.html"):
            self.assertNotIn("FileExistsError", path.read_text(encoding="utf-8", errors="replace"), path.name)

    def test_a_stale_hour_file_ends_its_status_on_every_page_with_the_all_clear_sentence(self):
        from website import swath as sw
        real = sw.collect

        def hour_stale(now, cache_dir, out_dir, towns, get=None, sample=False, offline=False):
            frames, files, states = real(now, cache_dir, out_dir, towns, get=get, sample=sample, offline=offline)
            frames["hail_60"]["state"] = "stale"       # a stale hour file: not fresh, so not ok (a sample frame is ok by design)
            states["hail_60"]["ok"] = False
            return frames, files, states
        out = Path(tempfile.mkdtemp(prefix="hailwatch-swath-stale-"))
        self.addCleanup(shutil.rmtree, out, True)
        with mock.patch.object(sw, "collect", hour_stale):
            result = site.build(out, None, self.NOW_SWATH, sample=True, storm_layers=True)
        self.assertFalse(result["status"]["hail_swath"]["ok"])
        self.assertEqual(result["status"]["hail_swath"]["words"], sw.WORDS_SWATH["all_clear"])
        self.assertIn("Hail, last hour: valid ", result["status"]["hail_swath"]["detail"])
        self.assertIn("That is more than 20 minutes old", result["status"]["hail_swath"]["detail"])
        for name in ("index.html", "about.html", "reports.html"):
            span = re.search(r'<span class="bad">Hail swath \(radar estimate\) problem: .*?</span>', page(out, name), re.S)
            self.assertIsNotNone(span, name)
            self.assertTrue(span.group(0).endswith("This is not an all-clear.</span>"), name)
            self.assertEqual(span.group(0).count("This is not an all-clear."), 1, name)     # once, not doubled
            self.assertNotIn("..", span.group(0), name)                                    # no doubled full stop
        banner = re.search(r'<div class="banner banner-problem" role="alert" id="problems">.*?</div>',
                           page(out, "map.html"), re.S)
        self.assertIsNotNone(banner, "the single-problem banner on the map page")
        self.assertEqual(banner.group(0).count("This is not an all-clear."), 1)
        state = json.loads(page(out, "data/state.json"))["status"]["hail_swath"]
        self.assertEqual(state["words"], sw.WORDS_SWATH["all_clear"])                    # state.json: the sentence once
        self.assertNotIn("This is not an all-clear.", state["detail"])
        self.assertNotIn("..", state["detail"])

    def test_an_unavailable_hour_file_says_the_all_clear_once_on_every_page(self):
        """rules-12: on an unavailable live-path build (the hour layer's file cannot be read; the other sources are fine,
        so the banner is the single-problem form), the freshness line, the banner and state.json each carry "This is not
        an all-clear." exactly once, with no doubled full stop."""
        from website import swath as sw
        real = sw.collect

        def hour_down(now, cache_dir, out_dir, towns, get=None, sample=False, offline=False):
            frames, files, states = real(now, cache_dir, out_dir, towns, get=get, sample=sample, offline=offline)
            frames["hail_60"] = sw._unavailable(sw.PRODUCT_BY_KEY["hail_60"],
                                                "the file list for the last hour didn't load: NOAA could not be reached")
            states["hail_60"].update(state="unavailable", ok=False, detail=frames["hail_60"]["state_line"])
            return frames, files, states
        out = Path(tempfile.mkdtemp(prefix="hailwatch-swath-down-once-"))
        self.addCleanup(shutil.rmtree, out, True)
        with mock.patch.object(sw, "collect", hour_down):
            result = site.build(out, None, self.NOW_SWATH, sample=True, storm_layers=True)
        self.assertFalse(result["status"]["hail_swath"]["ok"])
        for name in ("index.html", "about.html", "reports.html"):
            span = re.search(r'<span class="bad">Hail swath \(radar estimate\) problem: .*?</span>', page(out, name), re.S)
            self.assertIsNotNone(span, name)
            self.assertEqual(span.group(0).count("This is not an all-clear."), 1, name)
            self.assertNotIn("..", span.group(0), name)
        banner = re.search(r'<div class="banner banner-problem" role="alert" id="problems">.*?</div>',
                           page(out, "map.html"), re.S)
        self.assertIsNotNone(banner, "the single-problem banner on the map page")
        self.assertEqual(banner.group(0).count("This is not an all-clear."), 1)
        state = json.loads(page(out, "data/state.json"))["status"]["hail_swath"]
        self.assertEqual(state["words"], sw.WORDS_SWATH["all_clear"])
        self.assertNotIn("This is not an all-clear.", state["detail"])
        self.assertNotIn("..", state["detail"])

    def test_the_sheet_notes_name_each_kind_of_cell_in_words_and_no_bare_kind_token(self):
        """The smoke tool's notes for a build with no cell of a kind (browser-17, rules-14, live-14): one phrase per kind,
        and no bare kind word such as "none cell"."""
        smoke = smoke_map()
        frame = {"frames": [1], "title": "Hail, last hour"}
        data = {"hail": {}, "layers": {"hail_60": dict(frame), "hail_1440": {"frames": [1], "title": "Hail, last 24 hours"}}}
        with mock.patch.object(smoke, "swath_spots", return_value={}):
            problems = smoke.check_swath_sheet(None, "http://127.0.0.1/", Path(tempfile.gettempdir()), data, None)
        for title in ("Hail, last hour", "Hail, last 24 hours"):
            for phrase in ("with a value", "without an estimate in a tile that has a live file", "in a tile with no live file"):
                want = (f"note: {title}: this build has no Montana cell {phrase}, so the sheet's live line is not checked")
                self.assertIn(want, problems)
        self.assertEqual(len(problems), 6, problems)
        for msg in problems:
            self.assertIsNone(re.search(r"\b(?:none|missing|value) cell", msg), msg)
        self.assertEqual(smoke.KIND_WORDS["none"], "without an estimate in a tile that has a live file")

    def test_the_timeline_words_of_a_hail_layer_carry_no_clock_time(self):
        from website import swath as sw
        for name in ("timeline_fresh", "timeline_stale"):
            self.assertIsNone(re.search(r"\d{1,2}(?::\d{2})?\s?(?:am|pm)|Valid|MDT|MST", sw.WORDS_SWATH[name], re.I), name)
        self.assertEqual(sw.WORDS_SWATH["timeline_fresh"], "Radar estimate, {age} min ago.")
        self.assertIn("This is not an all-clear.", sw.WORDS_SWATH["timeline_stale"])

    def swath_section(self) -> str:
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        return js[js.index("live hail swath (--storm-layers builds, B4)"):js.index("joined records at a spot (--hail-history builds, B2)")]

    def test_the_timeline_line_is_the_timeline_words_with_the_sample_label_on_a_sample_build(self):
        section = self.swath_section()
        self.assertIn("function swathPre(lay) { return lay && lay.sample ? lay.words.sample_sheet + \" \" : \"\"; }", section)
        self.assertIn("var pre = swathPre(lay);", section)
        self.assertIn("pre + fill(w.timeline_fresh, { age: age })", section)
        self.assertIn("pre + fill(w.timeline_stale, { age: age, limit: lay.fresh_min })", section)   # {limit} is the fresh minutes
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn("return [swathPre(swathLayer()) + swathLayer().state_line];", js)     # the note's words, labelled on a sample build
        self.assertNotIn("fill(w.fresh, { valid", section)                  # the valid clause stays in the List and the status

    def test_the_hail_state_is_checked_once_a_minute_and_the_docs_say_so(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn("var STATE_TICK = MIN;", js)
        self.assertIn("setInterval(hailTick, STATE_TICK)", js)
        self.assertNotIn("MIN / 6", js)                                    # not ten seconds
        self.assertNotIn("every 10 seconds", js)
        self.assertIn("is checked every minute (D7)", js)                  # the STATE_TICK comment, above the section
        # the docs' hail passages say the same cadence: DESIGN section 11, the D37 entry and the ROADMAP's B4 row
        design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8").split("## 11. ")[1]
        decisions = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        decisions = decisions[decisions.index("**D37 · "):]
        roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
        roadmap = roadmap[roadmap.index("| Live hail swaths"):][:roadmap[roadmap.index("| Live hail swaths"):].index("\n")]
        for where, part in (("DESIGN section 11", design), ("DECISIONS D37", decisions), ("ROADMAP B4 row", roadmap)):
            self.assertNotIn("every 10 seconds", part, where)
            self.assertNotIn("10-second", part, where)

    def test_the_smoke_picture_gate_for_the_sparse_hail_layers_is_the_d17_rule(self):
        """D17 (the B4 brief): the gate zooms to a listed value cell at zoom 10 or closer, needs 16 changed pixels at that
        spot, notes the no-values case and records the count. The 2 percent rule stays with the dense radar and satellite."""
        smoke = (ROOT / "tools" / "smoke_map.py").read_text(encoding="utf-8")
        gate = smoke[smoke.index("def check_swath_gate("):smoke.index("def check_swath_tick(")]
        self.assertIn("GATE_MIN_CHANGED = 16", smoke)
        self.assertIn("GATE_MIN_ZOOM = 10", smoke)
        self.assertIn("cell = value_cell(root, L)", gate)                  # a listed cell with a value, nothing else
        self.assertIn("zoom_on_spot(page, data, lat, lon)", gate)           # zoomed on the spot, not the centre
        self.assertIn("changed_count_at(without, shown", gate)              # counted in a box around the spot
        self.assertIn("GATE_SPOT_RADIUS = 80", smoke)
        self.assertIn("zoom < GATE_MIN_ZOOM - 0.05", gate)
        self.assertIn("no values in the box: pixel gate not applicable", gate)
        self.assertIn("pixels changed at the spot", gate)                  # the count is recorded as a note
        self.assertNotIn("0.02", gate)
        self.assertIn("TICK_MS = 60_000", smoke)

    def test_the_hail_words_name_the_window_by_its_own_name_and_never_in_the_window(self):
        """D21: the About bullet and the contract row say "in the last hour" or "in the last 24 hours" (the window's own
        words), and "this map's area" stands in for "the picture" in every viewer's sentence."""
        about = page(self.on, "about.html")
        words = json.dumps(src.CONTRACTS["hail_swath"]) + about
        self.assertNotIn("in the window", words)
        self.assertIn("in the last hour (hour layer) or the last 24 hours (24-hour layer)", about)
        from website import swath as sw
        self.assertNotIn("in the window", json.dumps(sw.WORDS_SWATH))
        self.assertIn("this map's area", sw.WORDS_SWATH["montana_outside"])

    def test_the_live_line_reads_no_tile_for_a_point_the_store_puts_outside_montana(self):
        from website import swath as sw
        section = self.swath_section()
        self.assertIn("outside_montana_live", sw.WORDS_SWATH)
        self.assertIn("w.outside_montana_live", section)
        self.assertIn('var montana = !cell ? false : H.state === "unavailable" ? "unknown" : '
                      'hailListed(H, hailTileName(H, cell)) ? "pending" : false;', section)
        open_live = section[section.index("function liveOpen("):]
        self.assertNotIn("liveFile(", open_live)                       # liveOpen reads no tile: the shard answers first (F-9)
        live_montana = section[section.index("function liveMontana("):section.index("function liveCurrent(")]
        self.assertIn("if (value === true) liveLoad(liveFor);", live_montana)   # only a point the shard puts in Montana
        self.assertIn("function liveLoad(f) {", section)
        self.assertEqual(section.count("liveFile("), 2)                 # its definition and its one call, in liveLoad
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        open_hail = js[js.index("function openHail("):js.index("function onHailClick(")]
        self.assertIn("liveMontana(false);", open_hail)                       # the shard's answer reaches the live line
        self.assertIn("liveMontana(true);", open_hail)
        self.assertIn('liveMontana("unknown")', open_hail)                    # a store or shard that did not load is no answer

    def test_a_closed_hail_sheet_takes_its_live_line_with_it(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn("sheetState = null;\n    liveFor = null;\n    liveNode = null;\n", js)
        # the live line goes right after a dot's address block (B3), or first when the sheet has none (liveAttach)
        self.assertIn("hailTopEnd = block && block.nodeType === 11 ? block.lastChild : block;", js)
        self.assertIn("var end = hailTopEnd && hailTopEnd.parentNode === el.sheetBody ? hailTopEnd : null;", js)
        self.assertIn("el.sheetBody.insertBefore(liveNode, end ? end.nextSibling : el.sheetBody.firstChild);", js)

    def test_the_legend_keeps_the_hail_sentences_in_view_on_phones_and_its_keys_match_the_pictures(self):
        css = (ROOT / "website" / "static" / "map" / "map.css").read_text(encoding="utf-8")
        self.assertIn(".legend.swath-words .legend-note:not(:empty) { display: block; }", css)
        self.assertIn(".legend-uncoloured { margin-top: 3px;", css)
        self.assertIn(".legend-2col .legend-head, .legend-2col .legend-note, .legend-2col .legend-uncoloured", css)
        self.assertIn("html:not(.is-card) .legend:not(.show-note) .legend-uncoloured { display: none !important; }", css)
        # the picture's no-coverage stripes (gridded.HATCH, 1 px every 5 px) in both themes; the outside band as the map draws it
        self.assertEqual(css.count("--hatch-gap: rgba(142, 142, 147, 0.35);"), 2)
        self.assertIn(".key-hatch { background: repeating-linear-gradient(-45deg, var(--hatch-gap) 0 1px, transparent 1px 5px);", css)
        self.assertIn(".key-hatch-out { background: repeating-linear-gradient(-45deg, var(--hatch-out) 0 1px, transparent 1px 6px);", css)

    def test_the_legend_of_a_hail_layer_has_its_own_uncoloured_line_and_only_on_the_flag(self):
        from website import swath as sw
        self.assertIn('id="legend-uncoloured"', page(self.on, "map.html"))
        self.assertNotIn("legend-uncoloured", page(self.off, "map.html"))
        self.assertNotIn(sw.WORDS_SWATH["uncoloured"].format(window="hour"),
                         json.loads(page(self.on, "data/map.json"))["layers"]["hail_60"]["legend_note"])

    # B4-6 without git history (the Website workflow checks out shallow): the default build's files as digests, against
    # the manifest of the base commit's build. The shared script and style files are left out (they change with the
    # feature), the pages' ?v= hashes are normalised, and PNG frames are compared by their decoded pixels, so an encoder
    # change does not count. Regenerate with write_default_manifest (see its docstring).
    MANIFEST = ROOT / "tests" / "fixtures" / "default-build-manifest.json"
    ABOUT_CHANGED = ("about.html",)
    # the radar line of the default page (D53): the sentences the base build's page did not have; the D74 rows are checked by
    # test_joins (the contract texts) and the storm and address builds elsewhere in this file
    ABOUT_SENTENCES = ("a blank area is not a statement about the weather", "areas with no radar coverage are hatched")

    def test_the_default_build_matches_the_manifest_of_its_base_commit(self):
        expected = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        work = Path(tempfile.mkdtemp(prefix="hailwatch-identity-"))
        self.addCleanup(shutil.rmtree, work, True)
        out = work / "site"
        done = subprocess.run([sys.executable, "-m", "website.build", "--out", str(out), "--sample",
                               "--now", "2026-10-19T12:00:00Z"], cwd=ROOT, capture_output=True, text=True, timeout=900)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        now = default_digests(out)
        self.assertEqual(sorted(set(now) ^ set(expected["files"])), [], f"base {expected['base']}: files differ")
        # D53 and D77: the About page's radar line changed on purpose, so its digest is not the base's; every other file must
        # match, and the page must carry the changed sentences
        changed = sorted(name for name in now if now[name] != expected["files"][name] and name not in self.ABOUT_CHANGED)
        self.assertEqual(changed, [], f"base {expected['base']}: these files differ from the base build")
        about = " ".join(page(out, "about.html").split())
        for sentence in self.ABOUT_SENTENCES:
            self.assertIn(sentence, about)
class FiveSeasonHistory(unittest.TestCase):
    """The town page's five-season table and sections, the About words and the copies (B5, --hail-history), on the
    synthetic store that tests/test_summary.py writes (a spot at Billings with every part present). Nothing here is real."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    SECTIONS = ("hail", "wind", "storms", "temperature", "rain", "snow", "flooding", "ice", "heat", "roof", "made")
    B5_KEYS = ("nclimgrid_daily", "nohrsc_season_snowfall", "ghcn_daily", "iem_watchwarn", "iem_ugcs", "iem_lsr",
               "nwps_gauges", "usgs_water_api", "census_tiger_counties", "roof_references")

    @classmethod
    def setUpClass(cls):
        cls.store = fixture_store("full")
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-b5-on-"))
        cls.off = Path(tempfile.mkdtemp(prefix="hailwatch-b5-off-"))
        for path in (cls.store, cls.out, cls.off):
            cls.addClassCleanup(shutil.rmtree, path, True)
        cls.result = site.build(cls.out, None, cls.NOW, sample=True, hail_history=True, hail_store_path=str(cls.store))
        site.build(cls.off, None, cls.NOW, sample=True)
        cls.town = page(cls.out, "town/billings.html")
        cls.summary = cls.town[cls.town.index('id="hist-h"'):cls.town.index('id="sec-hail"')]    # the table leads the history
        cls.details = cls.town[cls.town.index('id="sec-hail"'):cls.town.index('id="other-h"')]  # the sections
        cls.section = cls.summary + cls.details

    def test_the_sections_come_in_the_brief_order(self):
        pos = [self.section.index(f'id="sec-{s}"') for s in self.SECTIONS]
        self.assertEqual(pos, sorted(pos))
        self.assertLess(self.section.index('<table class="five">'), pos[0])       # the table leads
        for season in ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "Five seasons"):
            self.assertIn(f'<th scope="col" class="num">{season}</th>', self.section)

    def test_the_forecast_keeps_the_top_and_the_history_follows_under_one_heading(self):
        # D39: alerts, observed now, the hourly and 7-day forecast, then the one history heading with its summary table
        # first; a jump link near the top opens it
        town = self.town
        anchors = ("alerts-h", "obs-h", "hours-h", "days-h", 'id="history"', "hist-h", "sec-hail", "sec-made", "other-h")
        order = [town.index(anchor if anchor.startswith('id=') else f'id="{anchor}"') for anchor in anchors]
        self.assertEqual(order, sorted(order))
        self.assertEqual(town.count('id="hist-h"'), 1)                    # one heading for the history
        self.assertLess(town.index('href="#history"'), town.index('id="alerts-h"'))   # the jump link is in the first screen
        self.assertLess(town.index('<table class="five">'), town.index('id="sec-hail"'))  # the table leads the history
        self.assertNotIn('id="hours-h"', self.summary)
        self.assertNotIn('id="hours-h"', self.details)
        self.assertNotIn('id="obs-h"', self.details)

    def test_no_map_block_lists_every_tile_and_the_split_map_says_which_exist(self):
        # D40: map.json carries a split map and URL patterns; no block holds every tile name
        raw = page(self.out, "data/map.json")
        m = json.loads(raw)["hail"]
        self.assertNotIn("tiles", m)
        self.assertNotIn("tile_names", m["climate"])
        self.assertTrue(m["tile_split"])
        self.assertLess(len(re.findall(r"r\d{4}_c\d{4}", raw)), 5)
        self.assertEqual(m["climate"]["tile"], "hail/c/{tile}.json")
        self.assertEqual(m["stations"]["tile"], "hail/sd/{station}.json")
        self.assertEqual(m["gauges"]["tile"], "hail/g/{usgs}.json")
        self.assertEqual(m["county"]["tile"], "hail/k/{county}.json")

    def test_the_about_page_has_the_new_sources_terms_and_the_reference_note(self):
        about = " ".join(page(self.out, "about.html").split())
        self.assertIn("Terms of the new sources", about)
        self.assertIn("license = no restrictions", about)
        self.assertIn("Observations courtesy of U.S. Geological Survey", about)
        self.assertIn("These data are in the public domain in the United States.", about)
        self.assertIn("Five roof references are not quoted: R2 (NWS glossary, severe thunderstorm)", about)
        self.assertIn("R20 (its title is in the references list above)", about)          # D46: the title is a citation
        self.assertIn("freeze-thaw damage to roofs (R20, not quoted): it is a secondary source", about)
        self.assertIn("Iowa State IEM zone outlines (the Montana public forecast zones by date)", about)   # D44
        self.assertNotIn("coverage rule", about)                          # D13: the stem leaves About
        self.assertIn("enough-days rule", about)
        self.assertIn("The history sits below the town's forecast", about)

    def test_the_town_page_has_one_history_heading_and_a_jump_link_in_the_first_screen(self):
        town = self.town
        self.assertEqual(town.count('id="hist-h"'), 1)
        self.assertIn('<a href="#history">Five years of weather at Billings</a>', town)
        self.assertLess(town.index('href="#history"'), town.index('id="alerts-h"'))
        self.assertEqual(town.count("River gauge: River gauge"), 0)       # D41: one label a line

    def test_every_row_names_its_kind_word_and_its_unit(self):
        heads = re.findall(r'<th scope="row" class="row-head">(.*?)</th>', self.section, re.S)
        self.assertGreaterEqual(len(heads), 20)
        for head in heads:
            kind = re.search(r'<span class="kind">([^<]*)</span>', head)
            self.assertIsNotNone(kind, head)
            self.assertRegex(kind.group(1), r"^(Radar estimate|Radar detection|Report|Record|Official record|Warning|Zone product|"
                                            r"County product|Station reading|Grid estimate|Reference|Data unavailable)")
            self.assertRegex(kind.group(1), r"(inches|days|degrees Fahrenheit|count|knots|record)")   # the held row: its reason

    def test_every_season_value_carries_its_unit_or_says_data_unavailable(self):
        cells = re.findall(r'<td class="num"[^>]*>(.*?)</td>', self.section, re.S)
        self.assertGreater(len(cells), 100)
        for cell in cells:
            text = visible(re.sub(r"<sup>.*?</sup>|<span class=\"cov\">.*?</span>", "", cell, flags=re.S)).strip()
            if text.startswith("Data unavailable") or text.startswith("No "):
                continue
            self.assertRegex(text, r"\d", text)
            self.assertRegex(text, r"\b(in|F|days?|kt|reports?|warnings?|watch(?:es)?|advisor\w*|mph)\b", text)

    def test_a_season_with_missing_days_says_how_many(self):
        self.assertIn("31 days missing", visible(self.section))      # the fixture's 2023-24 season has 31 missing grid days

    def test_the_partial_line_sits_below_the_table_and_the_radar_sentence_under_it(self):
        self.assertLess(self.section.index("</table>"), self.section.index("2026-27 so far"))
        self.assertLess(self.section.index("2026-27 so far"), self.section.index("Radar estimates can miss hail that people"))

    def test_a_cell_that_did_not_load_says_data_unavailable_with_its_reason_in_a_footnote(self):
        store = fixture_store("climate_unavailable")
        self.addCleanup(shutil.rmtree, store, True)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b5-climate-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        town = page(out, "town/billings.html")
        section = town[town.index('id="hist-h"'):town.index('id="other-h"')]
        self.assertRegex(section, r"Data unavailable<sup>1</sup>")
        footnotes = section[section.index('<ol class="hist-foot">'):]
        footnotes = footnotes[:footnotes.index("</ol>")]
        self.assertIn("could not be loaded", visible(footnotes))
        grid_rows = ("Highest temperature", "Lowest temperature", "Days with a high of 90 F", "Days with a low below 32 F",
                     "Freeze-thaw days", "Precipitation", "Largest one-day precipitation")
        for label in grid_rows:                                           # an unloaded grid value is never a zero
            row = re.search(r'<tr>\s*<th scope="row" class="row-head">' + re.escape(label) + r".*?</tr>", section, re.S)
            self.assertIsNotNone(row, label)
            cells = re.findall(r'<td class="num"[^>]*>(.*?)</td>', row.group(0), re.S)
            self.assertTrue(cells, label)
            for cell in cells:
                self.assertTrue(visible(cell).strip().startswith("Data unavailable"), (label, visible(cell)))

    def test_the_about_page_has_the_b5_terms_only_with_the_flag(self):
        from website import summary as sm, joins as jn
        on = page(self.out, "about.html")
        off = page(self.off, "about.html")
        for text in (sm.WORDS_SUMMARY["analysis_held"], jn.WORDS_JOINS["about_hit_miss"], src.CENSUS_TERMS,
                     sm.REFERENCE_LINES["R1"]["source"], sm.REFERENCE_LINES["R19"]["source"]):
            self.assertIn(jesc(text), on, text[:60])
            self.assertNotIn(jesc(text), off, text[:60])
        for key in self.B5_KEYS:
            self.assertIn(jesc(src.CONTRACTS[key]["name"]), on, key)
            self.assertNotIn(jesc(src.CONTRACTS[key]["name"]), off, key)
        self.assertNotIn(jesc(src.CONTRACTS["lsr"]["name"]), on)     # superseded by iem_lsr
        self.assertNotIn(jesc(src.CONTRACTS["nws_zone_products"]["name"]), on)

    def test_every_b5_contract_row_has_units_timing_and_missing_rules(self):
        for key in self.B5_KEYS:
            row = src.CONTRACTS[key]
            for field in ("name", "request", "units", "timing", "missing"):
                self.assertTrue(row.get(field), f"{key}.{field}")
        self.assertIn("Flood", src.CONTRACTS["ncei_storm_events"]["request"])                 # the point types B5 joins
        self.assertIn("left out", src.CONTRACTS["nohrsc_season_snowfall"]["units"] + src.CONTRACTS["nohrsc_season_snowfall"]["missing"])

    def test_the_partial_line_and_the_roof_lines_name_their_kinds_in_the_page(self):
        self.assertIn("Reference", self.section)
        self.assertIn("Data unavailable", self.section)

    def test_the_sections_words_say_no_forbidden_term_outside_quotes(self):
        from website import summary as sm
        text = visible(self.section)
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]
        hits = {s.strip()[:80]: sm.forbidden_hits(s) for s in sentences if sm.forbidden_hits(s)}
        self.assertEqual(hits, {})

    def test_flag_off_builds_have_no_five_season_section_or_b5_key(self):
        off = page(self.off, "town/billings.html")
        self.assertNotIn('id="hist-h"', off)
        self.assertNotIn("Five years of weather at", off)
        self.assertNotIn("hail_history", json.loads(page(self.off, "data/map.json")))
        self.assertNotIn("climate", json.loads(page(self.off, "data/map.json")).get("hail", {}))
        self.assertFalse((self.off / "hail").exists())

    def test_the_map_block_carries_every_b5_block_from_its_functions(self):
        m = json.loads(page(self.out, "data/map.json"))["hail"]
        for key in ("climate", "summary", "snow", "stations", "gauges", "county"):
            self.assertIn(key, m)
        self.assertEqual(m["climate"]["state"], "loaded")
        self.assertEqual(m["snow"]["state"], "unavailable")          # the fixture's snow analysis is not shown
        self.assertFalse(m["snow"]["shown"])
        self.assertIn("words", m["summary"])
        self.assertIn("rows", m["summary"])

    def test_the_hail_copies_are_the_store_folders_and_n_only_when_shown(self):
        copied = {p.name for p in (self.out / "hail").iterdir() if p.is_dir()}
        stored = {p.name for p in (self.store / "hail").iterdir() if p.is_dir()}
        self.assertEqual(copied, stored)                                   # the fixture has no snow folder
        self.assertNotIn("n", copied)

    def test_a_snow_folder_is_copied_only_when_the_index_says_it_is_shown(self):
        for shown in (True, False):
            store = fixture_store("full")
            self.addCleanup(shutil.rmtree, store, True)
            (store / "hail" / "n").mkdir()
            (store / "hail" / "n" / "r0092_c0214.json").write_text("{}", encoding="utf-8")
            set_index(store, snow={"state": "loaded", "shown": shown, "check": {}, "water_years": []})
            out = Path(tempfile.mkdtemp(prefix="hailwatch-b5-n-"))
            self.addCleanup(shutil.rmtree, out, True)
            site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
            self.assertEqual((out / "hail" / "n").is_dir(), shown, shown)

    def test_a_store_whose_file_changed_after_its_manifest_is_refused_before_any_copy(self):
        store = fixture_store("full")
        self.addCleanup(shutil.rmtree, store, True)
        (store / "hail" / "c" / next(iter(sorted(p.name for p in (store / "hail" / "c").iterdir())))).write_text("{}")
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b5-bad-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        self.assertFalse(result["status"]["hail_history"]["ok"])
        self.assertFalse((out / "hail").exists())
        town = page(out, "town/billings.html")
        self.assertIn("Weather history could not be loaded in this update", town)

    def test_a_b2_only_store_builds_and_every_b5_part_is_unavailable(self):      # D64
        # the store is the sample fixture's hail/ folder with the B5 parts taken out (write_b2_only_store), so the test
        # holds whatever the committed fixture gains (the tile lists, the station files and the stations block)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b5-b2-"))
        self.addCleanup(shutil.rmtree, out, True)
        store = write_b2_only_store(out / "store")
        site.build(out / "site", None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        m = json.loads(page(out / "site", "data/map.json"))["hail"]
        for key in ("climate", "snow", "stations", "gauges"):
            self.assertEqual(m[key]["state"], "unavailable", key)
            self.assertTrue(m[key]["problem"], key)
        self.assertIn("Five years of weather at Billings", page(out / "site", "town/billings.html"))

    def test_the_section_router_sends_each_joined_row_to_one_section(self):
        cases = {
            "Report: Jun 15, 2025 8:41 pm MDT: hail, 0.75 in (estimated), Public, 4.2 mi NE": "hail",
            "Report: Jun 16, 2025 5:16 pm MDT: tstm wnd gst, 59 mph (measured), Mesonet, 1.7 mi E": "wind",
            "Report: Jan 5, 2025 7:00 am MST: freezing rain, 0.10 in (estimated), Public, 1 mi": "ice",
            "Report: Jan 5, 2025 7:00 am MST: heavy snow, 6.0 in, Public, 1 mi": "snow",
            "Report: Jul 1, 2024 1:00 pm MDT: extreme heat, 105 F, Public, 2 mi": "heat",
            "Report: Jul 1, 2024 1:00 pm MDT: heavy rain, 1.20 in (estimated), Public, 2 mi": "rain",
            "Report: Jul 1, 2024 1:00 pm MDT: flash flood, Public, 2 mi": "flooding",
            "Report: Jul 1, 2024 1:00 pm MDT: tornado, Public, 2 mi": "storms",
            "Record: Jul 1, 2024 1:00 pm MDT: debris flow, Public, across zone MTZ001": "flooding",
            "Station: Jun 16, 2025: 50 kt (58 mph) at Billings/Logan Intl, about 3.9 miles away": "wind",
            "Detection: Jun 15, 2025: 1 detection, largest 1.75 in": "hail",
            "Warning: Jun 15, 2025 8:00 pm to 9:00 pm, issuance polygon in effect: Flash flood warning, BYZ; tags: x": "flooding",
            "Warning: Jun 15, 2025 8:00 pm to 9:00 pm, issuance polygon in effect: Severe thunderstorm warning, BYZ; tags: x": "storms",
            "Zone product: High wind warning: Jun 15, 2025 2:00 pm MDT to 4:00 pm MDT": "wind",
            "Zone product: Winter storm warning: Jun 15, 2025": "ice",
            "Zone product: Red flag warning, fire weather zone Yellowstone (MTZ001): Jun 15, 2025": "storms",
            # B5 D41: a watch and an advisory keep their kind label and route by the product's name, not by the tags
            "Watch: Jun 15, 2025 8:00 pm to 9:00 pm: flood watch, BYZ, covered this cell or part of it; tags: none stated":
                "flooding",
            "Advisory: Jan 10, 2025 12:00 am MST to Jan 11, 2025 1:00 am MST: areal flood advisory, TFX, covered this cell or "
            "part of it; tags: none stated": "flooding",
            "Advisory: Jan 10, 2025 12:00 am MST to Jan 11, 2025 1:00 am MST: winter weather advisory, TFX, covered this cell "
            "or part of it; tags: wind 45 mph": "ice",
            "Warning: Jun 15, 2025 8:00 pm to 9:00 pm: severe thunderstorm warning, BYZ, covered this cell or part of it; "
            "tags: hail 1.75 in": "storms",
        }
        for text, want in cases.items():
            label, body = site._split_kind(text)
            self.assertEqual(site._section_of(label, body), want, text)
        self.assertEqual(site._split_kind("no label here"), ("", "no label here"))
        self.assertEqual(site._split_kind("Watch: a")[0], "Watch")
        self.assertEqual(site._split_kind("Advisory: a")[0], "Advisory")

    def test_an_unavailable_summary_gives_its_words_and_no_sections(self):
        from website import joins as jn
        s = site.summary_unavailable("the history index file is missing")
        view = site.history_view(s, site.join_view_unavailable(jn), {"state": "unavailable", "unavailable": "x"},
                                 {"name": "Billings", "slug": "billings"}, self.NOW, None)
        self.assertEqual(view["state"], "unavailable")
        self.assertEqual(view["sections"], [])
        self.assertIn("the history index file is missing", " ".join(view["notices"]))

    def test_a_spot_outside_the_store_says_so_in_words(self):
        from website import summary as sm
        s = sm._result("outside", "x", {}, None, sm._empty_table(), None, [], None, None)
        view = site.history_view(s, {"sections": []}, {"state": "outside"}, {"name": "Glasgow"}, self.NOW, None)
        self.assertEqual(view["state"], "outside")
        self.assertEqual(view["notices"], [site.HISTORY_WORDS["outside"]])


ICE_LINE = re.compile(r"<li>(?P<text>[^<]*1 inch or more[^<]*on the ground[^<]*)</li>")


def ice_line_text(town_page: str) -> str:
    """The roof section's ice-dam line on a town page (D57): its text, as the page shows it."""
    found = ICE_LINE.findall(town_page)
    if len(found) != 1:
        raise AssertionError(f"expected one ice-dam line on the page, found {len(found)}")
    return html.unescape(found[0])


class MapBlocksForTheBrowser(unittest.TestCase):
    """The map.json blocks the browser fills (B5 part B2, site side; D29, D40, D42, D57): the words, the thresholds, the fixed
    orders, the file paths and the budgets are in the blocks, and map.json stays under 140 KB raw. Nothing here is real data:
    the sample build reads the committed fixture. HAIL_PARITY_STORE (a built store, the combined store) runs the same
    checks on the real store: the size, and the ice-dam line on each of the 17 town pages (D57)."""

    NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    SECTIONS = ["hail", "wind", "storms", "temperature", "rain", "snow", "flooding", "ice", "heat", "roof", "made"]

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-b2-blocks-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        site.build(cls.out, None, cls.NOW, sample=True, hail_history=True)

    def hail_block(self) -> dict:
        return json.loads(page(self.out, "data/map.json"))["hail"]

    def test_the_summary_block_carries_the_section_order_the_tile_list_path_and_the_rule(self):
        s = self.hail_block()["summary"]
        self.assertEqual(s["sections"], self.SECTIONS)                           # the fixed order (D29)
        self.assertEqual(s["tile_list"], "hail/tl/{tile}.json")                  # the station picks read these files (D36)
        self.assertEqual(s["tile_list_format"], "hail-stn-tiles-v1")
        self.assertEqual(s["rule"]["radius_miles"], 40.0)
        self.assertEqual((s["rule"]["cover_min"], s["rule"]["season_min"], s["rule"]["fresh_days"]), (0.8, 0.95, 30))
        self.assertNotIn("gust_five_at", s["words"])                             # the season cell names its station (D57)
        self.assertIn("none_gust_at", s["words"])

    def test_the_joins_block_carries_the_six_section_order_and_the_per_tile_events_path(self):
        j = self.hail_block()["joins"]
        self.assertEqual(j["section_order"], ["reports", "records", "detections", "warnings", "zones", "stations"])
        self.assertEqual(j["events_tiles"], "hail/j/e/{tile}.json")              # D30: the browser fetches this, never events.json
        self.assertEqual(j["shards"]["s"], "hail/s/{station}.json")

    def test_the_budget_block_holds_the_phone_view_and_the_per_tile_file(self):
        self.assertEqual(self.hail_block()["budget"], {"phone_gzip_bytes": 650 * 1024, "tile_events_gzip_bytes": 100_000})

    def test_map_json_stays_under_140_kb_raw(self):
        self.assertLess(len((self.out / "data" / "map.json").read_bytes()), 140_000)

    def test_the_ice_dam_line_on_the_billings_page_leads_with_station_reading(self):      # D57
        self.assertTrue(ice_line_text(page(self.out, "town/billings.html")).startswith("Station reading: "))

    def test_with_the_real_store_every_town_page_leads_with_station_reading_and_map_json_is_under_140_kb(self):   # D57, B5-12
        store = os.environ.get("HAIL_PARITY_STORE")
        if not store:
            self.skipTest("set HAIL_PARITY_STORE to a built store (the combined store) to check the 17 town pages")
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b2-real-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=store)
        self.assertLess(len((out / "data" / "map.json").read_bytes()), 140_000)
        towns = json.loads((ROOT / "website" / "towns.json").read_text(encoding="utf-8"))
        for town in towns:
            with self.subTest(town["slug"]):
                self.assertTrue(ice_line_text(page(out, f"town/{town['slug']}.html")).startswith("Station reading: "))


if __name__ == "__main__":
    unittest.main()
