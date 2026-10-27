"""
Website checks (website/): parsers, failure handling, the built pages and the town label sides.

Everything runs offline. Parsers get NWS/SPC-shaped documents; builds use the labelled sample data
or small fake fetchers that fail on purpose. The live sources are checked separately by the
website workflow (`python -m website.build --require-live` on branch pushes).
"""

import atexit
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
import textwrap
import unittest
import urllib.parse
from datetime import date, datetime, timedelta, timezone, time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import basemap2 as b2  # noqa: E402
from website import build as site  # noqa: E402
from website import buildings as bd  # noqa: E402
from website import gridded as g  # noqa: E402
from website import hail as hs  # noqa: E402
from website import history_layers as hl  # noqa: E402
from website import labels as lb  # noqa: E402
from website import landmarks as lm  # noqa: E402
from website import sources as src  # noqa: E402
from website import terrain as tr  # noqa: E402
from website.sample import SampleFetcher  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))   # tests/words_rules.py: the one forbidden list (D41, D81(c))
import words_rules  # noqa: E402

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
                                              "roof_references", "iem_ugcs"} | set(site.B6_CONTRACTS))     # B6: the 23 base map,
        # landmark, picture, zone and recent-hail rows (the B6 class below pins their words)
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
        self.assertIn("never drawn as cloud-free sky", c["missing"])                  # D86(b): "clear" is the all-clear stem
        self.assertIn("This is not an all-clear.", c["missing"])


class Formatting(unittest.TestCase):
    def test_times_have_no_leading_zeros_on_any_platform(self):
        self.assertEqual(site.fmt_time("2026-10-14T15:05:00Z"), "Wed 9:05 am MDT")
        self.assertEqual(site.fmt_time("2026-12-02T03:00:00Z", "%a %b %-d %-I %p"), "Tue Dec 1 8 pm")
        self.assertEqual(site.fmt_time(None), "-")
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
    atexit.register(shutil.rmtree, out, True)       # the run removes its own builds when it ends
    result = site.build(out, fetch, NOW, previous)
    return out, result


def page(out, name):
    return (out / name).read_text(encoding="utf-8")


class SampleBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-sample-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        cls.result = site.build(cls.out, None, NOW, sample=True)

    def test_every_file_is_there(self):
        expected = ["index.html", "reports.html", "about.html", "map.html", "data/map.json", "data/base.json",
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
        self.assertIn('src="map.html?embed=1&amp;v=', page(self.out, "index.html"))      # the home page's map
        self.assertIn("overlay=reports", page(self.out, "reports.html"))
        self.assertIn('<a href="index.html"', page(self.out, "about.html"))       # the sidebar's Map (the home page holds the map)
        self.assertIn("index.html?town=livingston", page(self.out, "town/livingston.html"))
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
        self.assertIn(f"static/veor.css?v={digest('veor.css')}", page(self.out, "index.html"))
        self.assertEqual(site.asset_versions(site.HERE / "static"), site.asset_versions(self.out / "static"))
        minute = NOW.strftime("%Y%m%d%H%M")
        self.assertIn(f"data/map.json?v={minute}", html)
        self.assertIn(f"map.html?embed=1&amp;v={minute}", page(self.out, "index.html"))

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

    def test_town_page_says_over_limit_station_values_in_words_and_keeps_the_veor_hooks(self):
        html = page(self.out, "town/livingston.html")
        # the gust over the limit: colour plus a spoken "(over limit)", as the hourly table does
        self.assertIn('<dd class="over">41<small> mph</small><span class="visually-hidden"> (over limit)</span></dd>', html)
        self.assertIn('<div class="town-page">', html)          # the Veor place layout (veor.css, .town-page)
        self.assertIn('<span class="hi">', html)                # a day's high, styled apart from its low

    def test_about_page_lists_every_source(self):
        html = page(self.out, "about.html")
        b3 = site.B3_ROWS + tuple(site.ROAD_ROWS.values())                         # flag-gated: HailAddresses
        for key, c in src.CONTRACTS.items():
            if key not in site.STORM_CONTRACTS and key not in site.HAIL_CONTRACTS and key not in b3:
                self.assertIn(c["name"], html)
        for key in site.STORM_CONTRACTS + site.HAIL_CONTRACTS + b3:
            self.assertNotIn(src.CONTRACTS[key]["name"], html)

    def test_about_page_names_the_app_and_frames_the_sources_table(self):
        html = page(self.out, "about.html")
        self.assertIn("Veor is a plain weather page for roofing work in Montana. It gathers public data",
                      " ".join(html.split()))
        self.assertIn('<div class="about-page">', html)              # the page's scope in veor.css (.about-page)
        self.assertIn('<div class="table-box contracts">', html)     # the framed table; it scrolls inside its own box

    def test_about_page_table_card_has_its_own_surface_and_the_office_links_are_targets_on_phones(self):
        """The data sources card keeps the card surface behind its table (the gradient shorthand alone would reset
        it). On phones the office links are a row of 44 px targets; links inside sentences keep their lines (padding
        on an inline link would overlap the next line's link)."""
        css = (self.out / "static" / "veor.css").read_text()
        self.assertIn(".about-page .contracts {", css)
        self.assertIn("background-color: var(--v-surface); }", css)
        self.assertIn(".about-page .offices a { display: inline-flex; align-items: center; min-height: 44px; }", css)
        self.assertNotIn(".about-page .prose a {", css)
        self.assertIn('<p class="offices">', page(self.out, "about.html"))

    def test_reports_page_shows_sizes_in_inches_and_unknown_wind(self):
        html = page(self.out, "reports.html")
        self.assertIn("1.75 in", html)
        self.assertIn("unknown", html)
        self.assertIn("No report is not the same as no hail.", html)
        empty = "No reports of hail or wind in or near Montana for this day; that is not the same as no hail."
        self.assertIn(empty, html)                                       # the empty days say it too (D91(c))
        self.assertEqual(html.count('<p class="empty">'), html.count(empty))

    def test_reports_page_text_passes_the_one_forbidden_list(self):
        """D91(c): the storm reports page is built text, so tests/words_rules.py scans its visible text: the stems of the one
        forbidden list, and "no hail" only inside "not the same as no hail" (the lead and each empty day)."""
        visible = re.sub(r"<(script|style)\b.*?</\1>", " ", page(self.out, "reports.html"), flags=re.S)
        words_rules.assert_clean(self, " ".join(html_text(visible).split()), "reports.html")

    def test_reports_page_frames_the_map_and_its_key_and_colours_the_kind_words(self):
        """The Veor reports page (docs/DESIGN.md section 14): the map card and its key share one framed block,
        each reporting day is a card whose heading keeps its count, and the hail and wind words keep the
        .kind-hail and .kind-wind colours with a dot of the same colour beside them (the dot is aria-hidden)."""
        html = page(self.out, "reports.html")
        self.assertIn('<div class="map-block">', html)
        self.assertIn('<iframe class="map map-card" src="map.html?card=1&amp;layer=precip&amp;overlay=reports&amp;v=', html)
        self.assertIn('title="Map of storm reports in and near Montana" loading="lazy"></iframe>', html)
        self.assertIn('<span class="kind kind-hail"><span class="swatch swatch-hail" aria-hidden="true"></span>Hail</span>', html)
        self.assertIn('<span class="kind kind-wind"><span class="swatch swatch-wind" aria-hidden="true"></span>Wind</span>', html)
        self.assertIn('<span class="day-count">(0 reports)</span>', html)
        # the key's link is a 44 px touch target on tablets and phones (45.6 px: the 21.6 px line plus 12 px each side),
        # and a table wider than its card shows a scroll shade on its edge (veor.css, .reports-page)
        css = (self.out / "static" / "veor.css").read_text()
        self.assertIn(".reports-page .legend a { display: inline-block; padding-block: 12px; margin-block: -12px; }", css)
        self.assertIn("--edge-w: 0.75rem;", css)

    def test_reports_map_key_names_the_forecast_numbers_and_outlines(self):
        """The Storm reports card draws town bubbles and warning outlines beside the reports and hides
        its own legend, so the page's key says what they are (rule 5: forecast is not a report). The
        card shows precipitation, which rings no town, so the key has no ring; the card counts alerts
        without an outline, and the key says where they are listed (rule 6)."""
        html = page(self.out, "reports.html")
        self.assertIn("<li>Town number: NWS forecast temperature, °F</li>", html)
        self.assertNotIn("orange ring", html)
        self.assertIn("Outline: NWS alert area (red warning, orange watch, gold advisory, grey statement)", html)
        self.assertIn('Alerts without an outline (issued by county or zone) are listed in the '
                      '<a href="index.html#forecast">home page\'s Forecast</a>', html)

    def test_reporting_days_start_at_noon_utc_in_montana_time(self):
        self.assertIn("Reporting day starting Wed Oct 14 at 6 am MDT", page(self.out, "reports.html"))
        winter = datetime(2026, 12, 10, 18, 0, tzinfo=UTC)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-winter-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, SampleWith(winter), winter)
        html = page(out, "reports.html")
        self.assertIn("Reporting day starting Thu Dec 10 at 5 am MST", html)      # 12:00 UTC in winter
        self.assertNotIn("MDT", html)

    def test_now_page_card_words_match_the_sample_picture(self):
        """The home page's map frame is named and described in build.map_card's words for the picture it
        opens on, so a screen reader hears what the map shows (and, below, what is missing)."""
        html = " ".join(page(self.out, "index.html").split())
        self.assertIn('title="Montana map: sample radar, warning outlines and town temperatures" '
                      'aria-describedby="map-words"', html)
        self.assertIn('<p class="visually-hidden" id="map-words">The latest sample radar picture (invented, not NOAA '
                      "radar), NWS warning outlines and the NWS forecast temperature for each town. </p>", html)


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
        self.addCleanup(shutil.rmtree, out, True)
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
        html = " ".join(page(out, "index.html").split())    # the home page's map frame names what is missing
        self.assertIn('title="Montana map: warning outlines and town temperatures"', html)
        self.assertIn("NWS warning outlines and the NWS forecast temperature for each town. Missing from this "
                      "update: the radar and model pictures. This is not an all-clear.</p>", html)
        self.assertIn('<p class="bad"><a href="#forecast" data-view="forecast">2 source problems: see Forecast</a>', html)
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
    """The words for the home page's map (build.map_card) follow what it shows when it opens: the frame
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

    def test_last_verified_alerts_and_some_town_forecasts(self):
        c = self.card(map_layers(model=False), alerts={"ok": False, "items": [{"id": "w1"}]},
                      towns=[{"hours": [{}]}, {"hours": []}])
        self.assertEqual(c["shown"], "The latest NOAA radar estimate, the outlines of the NWS alerts listed on this "
                                     "page and the NWS forecast temperature for each town whose forecast loaded.")
        self.assertEqual(c["missing"], "")

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
        SPC fail. The home page's map frame title and description name the model forecast, never radar."""
        def forecast_only(out_dir, get, now, sample=False):
            return map_layers(radar=False, now=now), {
                "radar": {"label": g.LABELS["radar"], "ok": False,
                          "detail": "the radar file list didn't load (server error (HTTP 503))"},
                "forecast": {"label": g.LABELS["forecast"], "ok": True, "detail": "run 7:00 am, 12 hours"}}
        with mock.patch.object(g, "build_gridded", forecast_only):
            out, _ = build_with(FailingFetcher())
        html = " ".join(page(out, "index.html").split())
        self.assertIn('title="Montana map: HRRR model forecast for 10 am"', html)
        self.assertIn('<p class="visually-hidden" id="map-words">The HRRR model forecast for 10 am. Missing from '
                      "this update: NOAA radar, NWS warning outlines and town temperatures. This is not an all-clear.</p>",
                      html)
        self.assertNotIn("radar estimate", html)
        m = json.loads(page(out, "data/map.json"))
        precip = m["layers"]["precip"]
        self.assertEqual(precip["frames"][precip["modes"]["12h"][precip["now_index"]["12h"]]]["time"],
                         "2026-10-14T16:00:00Z")                     # 10 am MDT: the frame the card opens on


class HomeConcept(unittest.TestCase):
    """The Veor home page concept (design branch; docs/DESIGN.md section 14): an app shell around the site's
    own map. The map is map.html in its embedded mode, the lead is sample data labelled as such in every build,
    and the old Now page's freshness line, warnings and town cards are in the Forecast panel, which the other
    pages' links to the warnings list open (index.html#forecast)."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-home-"))
        site.build(cls.out, None, NOW, sample=True)
        cls.html = " ".join(page(cls.out, "index.html").split())

    def test_the_map_is_the_sites_own_map_embedded(self):
        self.assertIn('<iframe class="stage-map" id="map-frame" src="map.html?embed=1&amp;v=', self.html)
        m = page(self.out, "map.html")
        self.assertIn('document.documentElement.classList.add("is-embed")', m)
        self.assertIn('{ target: "_top" }', m)                  # links in the map open in the whole window
        css = (site.HERE / "static" / "map" / "map.css").read_text(encoding="utf-8")
        self.assertIn(".is-embed .corner-left > .close, .is-embed #btn-layers { display: none; }", css)
        js = (site.HERE / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn('var EMBED = !CARD && params.get("embed") === "1";', js)
        self.assertIn('window.parent.document.getElementById("btn-layers-top")', js)   # focus and state on the top bar
        self.assertIn("if (EMBED) copyToHome(q);", js)                     # the map's choices in the home page's address
        self.assertIn('id="btn-layers-top"', self.html)

    def test_the_sample_lead_is_labelled_in_a_live_build_too(self):
        out, _ = build_with(FailingFetcher())                   # not a sample build: the weather is not invented
        html = " ".join(page(out, "index.html").split())
        self.assertIn('Lead details <span class="tag">Sample</span>', html)
        self.assertIn("Desktop concept · Sample data", html)
        self.assertNotIn("Everything on this page is invented", html)
        self.assertIn("Everything on this page is invented", self.html)      # the sample build says so as well

    def test_the_forecast_panel_has_the_freshness_line_the_warnings_and_every_town(self):
        self.assertIn('<section class="view view-forecast" id="view-forecast" aria-labelledby="fc-h" hidden>', self.html)
        self.assertIn("rebuilt on a schedule set to every 10 minutes", self.html)
        self.assertIn("Loaded: NWS alerts, NWS forecasts", self.html)
        self.assertIn('Warnings and advisories<span class="count">2</span>', self.html)
        self.assertIn("High Wind Warning", self.html)
        self.assertEqual(self.html.count('<li data-slug="'), len(site.TOWNS))
        self.assertIn("Weather information only. It does not confirm roof damage", self.html)
        self.assertIn("<style>.shell #view-forecast { display: block; }</style></noscript>", self.html)   # scripting off

    def test_the_forecast_button_counts_the_alerts_and_names_the_kind_or_says_they_did_not_load(self):
        self.assertIn('<span class="badge badge-warning"><span aria-hidden="true">2</span><span class="visually-hidden">, '
                      "2 NWS alerts, the most urgent a warning</span></span>", self.html)
        out, _ = build_with(FailingFetcher())
        html = " ".join(page(out, "index.html").split())
        self.assertIn('<span class="badge badge-unknown"><span aria-hidden="true">?</span>'
                      "<span class=\"visually-hidden\">, NWS alerts didn't load</span></span>", html)
        self.assertIn("Couldn't load NWS alerts at", html)
        self.assertNotIn("No active NWS warnings", html)
        self.assertNotIn('class="alert-now"', html)          # no alert is named from a failed check
        self.assertNotIn("Every source loaded", html)
        self.assertIn("Every source loaded", self.html)

    def test_the_status_names_the_most_urgent_alert_and_any_missing_town_data(self):
        """Alerts issued by county or zone have no outline on the map, so the top bar names the most urgent alert
        (with a count of the rest) on the first screen. 'Every source loaded' needs every town's values too."""
        self.assertIn('<p class="alert-now"><a href="#forecast" data-view="forecast">High Wind Warning and 1 more</a></p>',
                      self.html)
        def pictures_loaded(out_dir, get, now, sample=False):         # SampleWith's radar and model downloads fail
            return map_layers(now=now), {"radar": {"label": g.LABELS["radar"], "ok": True, "detail": "7 frames"},
                                         "forecast": {"label": g.LABELS["forecast"], "ok": True, "detail": "12 hours"}}
        with mock.patch.object(g, "build_gridded", pictures_loaded):
            gaps, _ = build_with(SampleWith(NOW, fail=("alerts-point",)))
            state, _ = build_with(SampleWith(NOW, fail=("alerts-state",)))
        html = " ".join(page(gaps, "index.html").split())
        self.assertIn(f'<p class="bad"><a href="#forecast" data-view="forecast">{len(site.TOWNS)} towns with missing data: '
                      "see Forecast</a></p>", html)
        self.assertNotIn("Every source loaded", html)
        self.assertIn("Alerts not checked", html)
        html = " ".join(page(state, "index.html").split())
        self.assertIn('<p class="bad"><a href="#forecast" data-view="forecast">NWS alerts problem: see Forecast</a> '
                      '<span class="bad">NWS alerts problem: ', html)      # the detail and its words follow the link
        self.assertIn('<span class="badge badge-unknown">', html)        # the count of a failed check is never shown
        self.assertIn('<p class="alert-now"><a href="#forecast" data-view="forecast">High Wind Warning and 1 more, may be out of date'
                      "</a></p>", html)                                 # what the town checks found is still named

    def test_the_page_reloads_every_ten_minutes_carrying_the_place_and_without_script_as_before(self):
        for name in ("index.html", "about.html", "town/billings.html"):
            raw = page(self.out, name)
            self.assertEqual(raw.count('http-equiv="refresh"'), 1, name)
            self.assertIn('<noscript><meta http-equiv="refresh" content="600">', raw, name)
            self.assertIn("if (Date.now() - loadedAt < 600000 || pressed || typing()) return;", raw, name)   # waits for a press or typing only
            self.assertIn("function typing() { return Date.now() - lastKey < 30000; }", raw, name)         # typing: a key in the last 30 s
            self.assertIn('sessionStorage.setItem("veor-restore"', raw, name)              # the viewer's place goes across
            self.assertIn("showAge();", raw, name)                                          # the age counts on
        home = page(self.out, "index.html")
        self.assertIn("s.panel = panel.scrollTop;", home)                                  # the home page's own part
        js = (site.HERE / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn('p.set("view", c.lat.toFixed(4)', js)                                # and the map's view

    def test_the_forecast_alerts_sit_under_their_heading_and_the_tab_panels_take_focus(self):
        self.assertIn("<h4>High Wind Warning</h4>", self.html)
        self.assertIn("<h3>High Wind Warning</h3>", " ".join(page(self.out, "town/livingston.html").split()))
        self.assertIn('<h1 class="visually-hidden">Veor: Montana weather map and forecast</h1>', self.html)
        self.assertEqual(self.html.count('role="tabpanel"'), 3)
        self.assertEqual(self.html.count('role="tabpanel" id="tp-'), 3)
        self.assertEqual(len(re.findall(r'role="tabpanel" id="tp-\w+" aria-labelledby="tab-\w+" tabindex="0"', self.html)), 3)

    def test_every_town_is_in_the_area_menu_and_the_search_list(self):
        for t in site.TOWNS:
            self.assertIn(f'<option value="{t["slug"]}">{t["name"]} area</option>', self.html)
            self.assertIn(f'<option value="{t["name"]}"></option>', self.html)
        self.assertIn('<option value="">All of Montana</option>', self.html)     # the map opens on all of Montana

    def test_the_home_page_loads_only_site_files_and_serves_its_font(self):
        self.assertNotRegex(self.html, r'<(script|link|img|iframe)[^>]+(src|href)="(https?:)?//')
        self.assertTrue((self.out / "static" / "fonts" / "newsreader-latin-opsz-normal.woff2").is_file())
        self.assertIn("url(newsreader-latin-opsz-normal.woff2)", page(self.out, "static/fonts/fonts.css"))
        self.assertIn("The Newsreader Project Authors", page(self.out, "static/fonts/LICENSE-fonts.txt"))

    def test_the_links_to_the_warnings_list_open_the_forecast_panel(self):
        self.assertIn('if (location.hash !== "#forecast") return;', self.html)
        self.assertIn('show("forecast", !!e || nav.type !== "reload");', self.html)     # focus on a link, not a reload
        self.assertIn("""closest('a[href$="#forecast"]')""", self.html)      # the map's links open it in place
        self.assertIn('<a href="../index.html#forecast">All towns</a>', page(self.out, "town/livingston.html"))
        self.assertIn('id="btn-forecast" href="index.html#forecast"', page(self.out, "about.html"))   # the top bar's Forecast
        self.assertIn('id="btn-forecast" href="../index.html#forecast"', page(self.out, "town/livingston.html"))
        self.assertIn('href="index.html#forecast"', page(self.out, "map.html"))           # the noscript list
        js = (site.HERE / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn('href="index.html#forecast">All warnings and town forecasts</a>', js)
        self.assertNotIn("Now page", js)


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
        self.assertEqual(html.count('data-group="live" data-key="satellite"'), 1)
        self.assertIn('<span class="mo-label">Satellite</span>', html)
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
        self.assertIn('<h3 class="mo-h" id="mo-base-h">Base map</h3>', html)
        self.assertIn('data-group="base" data-key="map" aria-pressed="true"', html)
        self.assertNotIn('data-key="imagery" aria-pressed="true"', html)
        for name in ("index.html", "reports.html"):
            self.assertNotIn("data-imagery", page(self.out, name), name)
            self.assertNotIn('data-group="base"', page(self.out, name), name)

    def test_the_switch_has_its_privacy_line_and_the_about_page_says_it_is_off_by_default(self):
        html = " ".join(page(self.out, "map.html").split())
        self.assertIn('data-group="base" data-key="imagery" aria-pressed="false" data-legend="Imagery: USDA, USGS, The National '
                      'Map. Your IP address and the map area you view go to USGS while it is on."', html)
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
        self.assertIn('data-group="base" data-key="imagery"', page(out, "map.html"))
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

    def test_the_base_map_cards_come_first_in_the_options_sheet_and_the_live_chips_after_them(self):
        html = page(self.out, "map.html")
        sheet = html[html.index('id="map-options"'):]
        sheet = sheet[:sheet.index("\n  <noscript>")]
        self.assertLess(sheet.index("Base map"), sheet.index('data-group="base"'))
        self.assertLess(sheet.index('data-group="base"'), sheet.index('data-group="live"'))
        self.assertLess(sheet.index('data-group="live"'), sheet.index('data-group="history"'))

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
        # D110(d) (B6): the credit row carries the privacy words "while it is on", as the Map page's Imagery description does
        self.assertEqual(site.IMAGERY["credit_line"], "Imagery: USDA, USGS, The National Map. Your IP address and the "
                         "map area you view go to USGS while it is on.")
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
        self.assertIn('<section id="history" class="history hail-history" aria-labelledby="hist-h">', town)   # the Veor hail styles (veor.css)
        about = " ".join(page(self.on, "about.html").split())      # the template wraps the sentences across lines
        self.assertIn("<h2>Hail history</h2>", page(self.on, "about.html"))
        self.assertIn("An estimate is not a measurement at the ground and not an inspection.", about)
        self.assertIn("(6.35&nbsp;mm)", about)              # one unbreakable unit: no break between 6.35 and mm
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
        self.assertEqual(hs.WORDS["heading_failed"], "Hail history didn't load")     # D98(a): Python supplies the banner heading
        self.assertIn("{{ s.heading }}", (ROOT / "website" / "templates" / "map.html").read_text(encoding="utf-8"))
        self.assertNotIn("legend-tap", off)
        self.assertNotIn("hail-sheet", off)
        self.assertNotIn("Each town's page has its five-year hail history", off)
        self.assertIn("Hail history (radar estimates)", page(self.on, "index.html"))

    def test_the_hail_styles_are_on_the_map_page_only_with_the_flag(self):
        # The sheet's and the legend's rules are a style block that only a --hail-history build writes. The shared
        # map.css is the same file in every build, so the default build's static files are the ones it was before.
        source_css = (ROOT / "website" / "static" / "map" / "map.css").read_text(encoding="utf-8")
        self.assertNotIn(".legend-tap", source_css)
        self.assertEqual((self.off / "static" / "map" / "map.css").read_bytes(),
                         (ROOT / "website" / "static" / "map" / "map.css").read_bytes())
        on, off = page(self.on, "map.html"), page(self.off, "map.html")
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
        inches = next(line for line in js.splitlines() if line.startswith("  function hailInches(h, t) {"))
        self.assertNotRegex(inches, r"\b(?:100|2)\b")        # no literal scale or decimals: the block gives them (D87(d), D87(r))
        self.assertIn("U.scale", inches)                     # read from summary.units.in, the build's own unit spec
        self.assertIn("U.decimals", inches)
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
        for signature in (r"own\(obj, key\)", r"missingKey\(key\)", r"hailInches\(h, t\)", r"hailMm\(h, t\)"):
            match = re.search(r"^  function %s \{.*\}$" % signature, js, re.M)     # one line each, as map.js writes them
            self.assertIsNotNone(match, signature)
            parts.append(match.group(0))
        script = "\n".join(parts) + (
            "\nconst h = { tenths_per_inch: 254, tenths_per_mm: 10, summary: { units: { in: { scale: 100, decimals: 2 } } } };"
            "\nconst cases = [513, 185, 253, 190, 1015, 254, 1016, 64];"
            "\nconst tenths = { tenths_per_inch: 254, tenths_per_mm: 10, summary: { units: { in: { scale: 10, decimals: 1 } } } };"
            "\nconst bare = { tenths_per_inch: 254, tenths_per_mm: 10, summary: {} };"
            "\nconsole.log(JSON.stringify([cases.map(t => [hailInches(h, t), hailMm(h, t)]), hailInches(tenths, 513),"
            " hailInches(bare, 513)]));")
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60, check=True)
        rows, read_from_block, without_block = json.loads(out.stdout)
        self.assertEqual(rows, [["2.01", "51.3"], ["0.72", "18.5"], ["0.99", "25.3"], ["0.74", "19.0"],
                                ["3.99", "101.5"], ["1.00", "25.4"], ["4.00", "101.6"], ["0.25", "6.4"]])
        self.assertEqual(read_from_block, "2.0")          # the scale and the decimals come from the block: 513 at scale 10 (D87(r))
        self.assertEqual(without_block, "[missing words key: summary.units.in.scale]")   # no block, no guess (D16)

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

    def test_the_sheet_shows_the_radar_days_before_the_joins(self):                                        # D81(e): round 2's order
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        open_hail = js[js.index("function openHail("):js.index("function onHailClick(")]
        radar = open_hail.index('hailShow(h, "loaded", text, null);')          # the radar text first; the table and sections follow
        table = open_hail.index("sumRender(el.sheetBody.querySelector('[data-hail=\"summary\"]'), res);")
        sections = open_hail.index("histRender(slot, histModel(h, cell, both[0], both[1], text));")
        self.assertLess(radar, table)
        self.assertLess(table, sections)
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
            rest = rest.replace("This is not an all-clear.", "")      # the required sentence of every unavailable line (D41)
            self.assertIsNone(self.FORBIDDEN.search(rest), text)

    def test_the_sheet_prints_the_stale_line_once_and_map_js_adds_no_second_all_clear(self):
        """D96(b): the stale line is the words' own sentence, which ends with the required all-clear sentence once; map.js
        fills that line from the words and appends no all-clear to it, and the sheet shows the line in one slot."""
        from website import hail as hs
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertEqual(js.count("out.stale = fill(w.stale, { as_of: hailDate(h.as_of) });"), 1)
        self.assertEqual(js.count('show(slot("stale"), payload.stale);'), 1)
        self.assertNotIn("out.stale +=", js)
        self.assertNotIn("w.stale + ", js)
        self.assertTrue(hs.WORDS["stale"].endswith("This is not an all-clear."))
        self.assertEqual(hs.WORDS["stale"].count("This is not an all-clear."), 1)

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
        # D98(a): the banner's heading is Python's word for a store that did not load, and its sentence says the plain words
        banner = re.search(r'<div class="banner banner-problem" role="alert" id="problems">.*?</div>',
                           page(out, "map.html"), re.S)
        self.assertIsNotNone(banner)
        self.assertIn("<strong>Hail history didn&#39;t load</strong>", banner.group(0))    # the template escapes the apostrophe
        self.assertIn("The history store file store.tar.gz is missing.", banner.group(0))
        # D96(b): the banner's own line carries the all-clear sentence once (the macro line no longer adds a second copy)
        self.assertEqual(banner.group(0).count("This is not an all-clear."), 1)

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
        # a branch build waits for its branch's latest store job before it reads the asset (main never waits); the listing
        # needs the actions scope, and the wait is bounded (the job's timeout covers it)
        wait = text[text.index("Wait for this branch's hail history store job"):text.index("- name: Build from live data")]
        self.assertIn("if: steps.plan.outputs.run == 'true' && github.ref != 'refs/heads/main'\n", wait)
        self.assertIn('--workflow hail-store.yml --branch "$GITHUB_REF_NAME" --limit 1', wait)
        self.assertIn("      actions: read", text)
        build_job = text[text.index("\n  build:\n"):text.index("\n  deploy:\n")]
        # a branch preview may wait up to 60 minutes for its store job; main never waits and keeps its 15
        self.assertIn("timeout-minutes: ${{ github.ref == 'refs/heads/main' && 15 || 75 }}", build_job)
        self.assertIn('print("\\nHail history (--hail-history):")', text)   # the summary names main's build too
        unit = [line for line in text.splitlines() if "python -m unittest" in line]
        self.assertEqual(len(unit), 2, "the offline unit step and the real-store parity step (D88(a))")
        self.assertIn("tests.test_hail", unit[0])
        self.assertIn('"tests/test_hail.py"', text)
        self.assertIn("HAIL_PARITY_STORE: _site", text)      # the parity step reads the built site's copy of the store (D88(a))

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
        self.assertIn("waits for its branch's latest store job", row["timing"])
        self.assertIn("(main does not wait)", row["timing"])
        self.assertIn("a branch preview is marked as failed.", row["timing"])
        self.assertEqual(hs.STALE_DAYS, 3)
        self.assertIn("more than three days old is a failed source", row["timing"])
        self.assertNotIn("within the hour", row["timing"])

    def test_a_failed_download_reads_plainly_on_the_pages_and_in_full_in_the_log(self):
        """The build log keeps the file name and the HTTP code; the pages say the store could not be downloaded."""
        from website import hail as hs

        class Fetcher:
            def binary(self, url, headers=None):
                return (None, "not published (HTTP 404)")
        out = Path(tempfile.mkdtemp(prefix="hailwatch-404-"))
        self.addCleanup(shutil.rmtree, out, True)
        c = site.Collector(Fetcher(), self.HAIL_NOW)
        town = {"name": "Billings", "lat": 45.78, "lon": -108.5}
        block = c.hail(out, False, None, [town])
        status = c.status["hail_history"]
        self.assertFalse(status["ok"])
        self.assertIn("hail-store-main.tar.gz: not published (HTTP 404)", status["detail"])
        self.assertEqual(block["state"], "unavailable")
        self.assertIn("could not be downloaded", json.dumps(block))
        self.assertNotIn("HTTP", json.dumps(block))
        # the town's words, summary and joins take the same plain sentence (the unavailable branch passes it on)
        self.assertIn("could not be downloaded", json.dumps(town["hail"]))
        self.assertNotIn("HTTP", json.dumps(town["hail"]))
        self.assertEqual(hs.plain_problem("the history store file x.tar.gz is missing"), "the history store file x.tar.gz is missing")

    def test_the_map_banner_for_a_failed_download_says_didnt_load_in_plain_words(self):
        """D98(a): a store whose download answers 404 heads the map banner "Hail history didn't load"; its sentence is the
        plain words (the HTTP code stays in the build log), and the all-clear sentence closes the banner once."""
        from website import hail as hs

        class DownloadFails(SampleFetcher):
            """Sample data for every feed; the history store's download answers 404, as when no asset is published."""
            def binary(self, url, headers=None):
                return None, "not published (HTTP 404)"
        out = Path(tempfile.mkdtemp(prefix="hailwatch-404-banner-"))
        self.addCleanup(shutil.rmtree, out, True)
        result = site.build(out, DownloadFails(self.HAIL_NOW), self.HAIL_NOW, hail_history=True)
        status = result["status"]["hail_history"]
        self.assertFalse(status["ok"])
        self.assertIn("(HTTP 404)", status["detail"])                                   # the log keeps the code
        self.assertEqual(status["heading"], hs.WORDS["heading_failed"])
        self.assertEqual(status["sentence"], "The history store could not be downloaded in this update.")
        banner = re.search(r'<div class="banner banner-problem" role="alert" id="problems">.*?</div>',
                           page(out, "map.html"), re.S)
        self.assertIsNotNone(banner, "a failed download is a failed source: the map page's problem banner")
        self.assertIn("<strong>Hail history didn&#39;t load</strong>", banner.group(0))
        self.assertIn("The history store could not be downloaded in this update.", banner.group(0))
        self.assertNotIn("Hail history is older", banner.group(0))
        start = banner.group(0).index('data-source="hail_history"')
        hail_line = banner.group(0)[start:].split("</li>")[0].split("</p>")[0]         # the history's own line, as printed
        self.assertNotIn("HTTP", hail_line)
        self.assertEqual(banner.group(0).count("This is not an all-clear."), 1)

    def test_an_unavailable_joins_block_carries_the_same_words_as_a_loaded_one(self):
        """D95(b) and D96(a): the unavailable joins block reads the same word table as a loaded block, so it is filtered by
        nothing; no word in that table quotes an HTTP code (the zone-edition reason says it in plain words)."""
        from website import build as bd
        from website import joins as jn
        self.assertEqual([k for k, v in jn.WORDS_JOINS.items() if "HTTP" in str(v)], [],
                         "a word that quotes an HTTP code is reworded in WORDS_JOINS, never filtered out of a block")
        gone = bd.join_block_unavailable(jn, "the joined records are not in this history store")
        self.assertNotIn("HTTP", json.dumps(gone))
        self.assertIn("reason_not_published", gone["words"])
        self.assertIn("section_flooding", gone["words"])
        store = {"state": "ok", "parts": {part: "ok" for part in jn.PARTS}, "reasons": {}, "lags": {}, "partial": {},
                 "zone_names": {}, "types": {}, "cover": "", "shapes": {}, "montana_time": []}
        loaded = bd.join_block(jn, {"as_of": "2026-10-19", "window": ["2021-10-19", "2026-10-19"], jn.INDEX_KEY: store}, False)
        self.assertEqual(gone["words"], loaded["words"])

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
        self.assertEqual(status["heading"], hs.WORDS["heading_stale"])                # D98(a): the banner's heading for this state
        self.assertEqual(hs.STALE_DAYS, 3)                                             # the heading's "three days"
        self.assertEqual(hs.WORDS["stale"], hs.WORDS["stale_lead"] + " This is not an all-clear.")   # D96(b): one sentence, one source
        self.assertEqual(json.loads(page(out, "data/map.json"))["hail"]["state"], "loaded")
        billings = page(out, "town/billings.html")
        stale = hs.WORDS["stale"].format_map({"as_of": hs.fmt_date(as_of)})
        self.assertEqual(billings.count(stale), 1)                                  # one stale line, not two
        self.assertIn(f"<p class=\"sub\"><strong>{stale}</strong></p>", billings)  # the town page's own stale paragraph
        self.assertEqual(stale.count("This is not an all-clear."), 1)               # D96(b): the sentence once in the line
        from website import summary as sm
        self.assertEqual(sm.WORDS_SUMMARY["stale"], hs.WORDS["stale"])            # D96(b): one text, imported by summary.py
        # D96(b): the stale store is a failed source, so the map page's problem banner says so, with the all-clear once
        banner = re.search(r'<div class="banner banner-problem" role="alert" id="problems">.*?</div>',
                           page(out, "map.html"), re.S)
        self.assertIsNotNone(banner, "a stale store is a failed source: the map page's problem banner")
        # D98(a): the heading says the store is older than three days (not that it did not load), and the sentence after it
        # keeps what loaded and the as-of date
        self.assertIn("<strong>" + hs.WORDS["heading_stale"] + "</strong>", banner.group(0))
        self.assertNotIn("didn&#39;t load", banner.group(0))
        self.assertIn(hs.WORDS["stale_lead"].format_map({"as_of": hs.fmt_date(as_of)}), banner.group(0))
        self.assertEqual(banner.group(0).count("This is not an all-clear."), 1)
        fresh = datetime.combine(as_of + timedelta(days=hs.STALE_DAYS), time(13, 0), tzinfo=timezone.utc)
        self.assertTrue(site.build(out, None, fresh, sample=True, hail_history=True,
                                   hail_store_path=str(store))["status"]["hail_history"]["ok"])
        self.assertTrue(site.build(out, None, late, sample=True, hail_history=True)["status"]["hail_history"]["ok"])

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

    def test_the_sheet_has_the_template_slots_for_the_table_and_the_sections(self):                          # D81(e): round 2's slots
        on = page(self.on, "map.html")
        self.assertIn('<template id="hail-sheet">', on)
        for slot in ('data-hail="sample"', 'data-hail="summary"', 'data-hail="stale"', 'data-hail="sections"'):
            self.assertIn(slot, on, slot)
        off = page(self.off, "map.html")
        self.assertNotIn('id="hail-sheet"', off)
        self.assertNotIn('data-hail="sections"', off)


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
        menu = html[html.index('id="b3-keys"'):html.index('id="mo-reset"')]          # the keys sit in the sheet, before Reset
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
        self.assertEqual(len(args), 2, "the branch line and main's own line (D59: main passes --hail-history alone)")
        self.assertIn("--require-live --storm-layers --hail-history --hail-addresses", args[0])
        self.assertIn("args+=(--hail-history)", args[1])
        unit = [line for line in text.splitlines() if "python -m unittest" in line]
        self.assertEqual(len(unit), 2, "the offline unit step and the real-store parity step (D88(a))")
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
        # D91(a), D66, D82(b): the phone budget is read from the build's map.json (hail.budget.phone_gzip_bytes, written from
        # build.PHONE_GZIP_BUDGET) by the smoke's map_budget; the B3 check and the whole phone view both use it, and the smoke
        # keeps no budget constant of its own. A map.json without the budget gives None, which the smoke names as a problem.
        self.assertFalse(hasattr(smoke, "ADDRESS_FETCH_BUDGET_GZIP"))
        self.assertEqual(smoke.map_budget({"hail": {"budget": {"phone_gzip_bytes": 123_456}}}, "phone_gzip_bytes"), 123_456)
        self.assertEqual(smoke.map_budget({"hail": {"budget": {"phone_gzip_bytes": site.PHONE_GZIP_BUDGET}}}, "phone_gzip_bytes"),
                         700_000)
        self.assertIsNone(smoke.map_budget({"hail": {}}, "phone_gzip_bytes"))
        self.assertEqual(site.PHONE_GZIP_BUDGET, 700_000)
        self.assertEqual(smoke.ADDRESS_DRAW_MS, 30)
        self.assertEqual(smoke.PAN_FETCH_LIMIT, 20)
        self.assertEqual(smoke.B3_BILLINGS, (45.7857, -108.5071))     # 401 North 27th Street, Billings


class SiteCopySource(unittest.TestCase):
    """D92(a), D75(a): a build's copy may take a built site's own hail/ folder as its source (the parity step reads _site as
    HAIL_PARITY_STORE). That folder holds B4's live swath files under hail/live/, which the manifest never lists. _copy_hail
    checks its source with allow_live=True, so such a source passes; any other unlisted file under hail/ still refuses it, and
    a link is refused either way. The copy's own check stays strict, and the copy takes only the listed folders."""

    def store(self, extra: dict) -> Path:
        """A hail/ folder copied from the sample fixture, with extra files written under the store root. The manifest lists
        the fixture's files only, so each extra file is unlisted."""
        root = Path(tempfile.mkdtemp(prefix="hailwatch-d92-store-"))
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(hs.FIXTURE_DIR / "hail", root / "hail")
        for rel, data in extra.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        return root

    def site_dir(self) -> Path:
        """A site folder that does not exist yet (the copy makes its hail/ folder)."""
        out = Path(tempfile.mkdtemp(prefix="hailwatch-d92-site-"))
        self.addCleanup(shutil.rmtree, out, True)
        return out / "site"

    def test_a_source_with_live_files_passes_and_the_copy_never_carries_them(self):
        root = self.store({"hail/live/60/20261024T120000Z/MTC045.json": b'{"f": "hail-live-test"}'})
        with self.assertRaises(hs.HailStoreError):
            hs.check_manifest(root)                     # strict refuses it: the pass below is allow_live's doing
        out = self.site_dir()
        site._copy_hail(root, out, hs.load_index(root), addresses=False)
        self.assertFalse((out / "hail" / "live").exists())
        hs.check_manifest(out)

    def test_a_source_with_an_unlisted_file_elsewhere_under_hail_still_fails(self):
        for rel in ("hail/zz/unlisted.json", "hail/t/unlisted.json"):
            with self.subTest(rel=rel):
                root = self.store({rel: b"{}"})
                out = self.site_dir()
                words = "the history has a file the manifest does not list: " + re.escape(rel)
                with self.assertRaisesRegex(hs.HailStoreError, words):
                    site._copy_hail(root, out, hs.load_index(root), addresses=False)
                self.assertFalse((out / "hail").exists())

    def test_a_link_under_the_live_folder_is_refused_either_way(self):
        root = self.store({})
        (root / "hail" / "live").mkdir()
        os.symlink(root / "hail" / "manifest.json", root / "hail" / "live" / "link.json")
        with self.assertRaisesRegex(hs.HailStoreError, "the history has a link"):
            site._copy_hail(root, self.site_dir(), hs.load_index(root), addresses=False)

    def test_the_source_is_checked_with_allow_live_and_the_copy_strictly(self):
        root = self.store({"hail/live/60/20261024T120000Z/MTC045.json": b"{}"})
        out = self.site_dir()
        real_check = hs.check_manifest
        calls = []

        def recording(path, allow_live=False):
            calls.append((Path(path).resolve(), allow_live))
            return real_check(path, allow_live=allow_live)

        with mock.patch.object(hs, "check_manifest", side_effect=recording):
            site._copy_hail(root, out, hs.load_index(root), addresses=False)
        self.assertEqual(calls[0], (root.resolve(), True))       # the source: hail/live is skipped (D92(a))
        self.assertEqual(calls[-1], (out.resolve(), False))      # the copy: its own check is strict

    def test_the_copy_refuses_an_unlisted_file_it_would_carry_from_a_clean_source(self):
        root = self.store({})
        out = self.site_dir()
        real_copytree = shutil.copytree

        def copytree_with_a_stray(src, dst, *args, **kwargs):
            result = real_copytree(src, dst, *args, **kwargs)
            (Path(dst) / "stray.json").write_bytes(b"{}")         # an unlisted file the copy would carry
            return result

        with mock.patch.object(shutil, "copytree", side_effect=copytree_with_a_stray):
            with self.assertRaisesRegex(hs.HailStoreError, "the history has a file the manifest does not list: hail/"):
                site._copy_hail(root, out, hs.load_index(root), addresses=False)


class B3Completion(unittest.TestCase):
    """The B3 completion rulings that need no full build (D42 to D48): the unpack limits and their refusals, the address zoom
    rules run under node, the index rewrite of the address-text mode, and the workflow's install line. The builds and the
    browser are checked in HailAddresses (offline) and tools/smoke_map.py (in Chromium)."""

    def test_the_unpack_limits_are_800_mib_and_60000_files_and_hold_the_b3_store(self):
        from website import hail as hs
        self.assertEqual(hs.MAX_UNPACK_BYTES, 800 * 1024 * 1024)               # D42
        self.assertEqual(hs.MAX_UNPACK_FILES, 60000)
        # the B3 store's measured size is recorded with the job (b5-verification.json); the limits are the constants above
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
            self.assertEqual(len(unit), 2, "the offline unit step and the real-store parity step (D88(a))")
            self.assertIn(module, unit[0].split())


class B3SplitMaps(unittest.TestCase):
    """The B3 blocks' compact split maps (D40; docs/ROADMAP.md engineering follow-up A, D66, D82(b)): build.py b3_map_blocks
    turns each block's tile list into tile_split, so no block lists every tile name. The browser reads the split maps
    (map.js b3Listed and b3ListedCount). The every-flag sample build (--sample --hail-history --hail-addresses
    --storm-layers) holds the addresses; the sample store has no roads or outlines, so the outlines' split map is checked on
    a loaded block the test writes."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-b3-split-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)      # only the folder this class made
        site.build(cls.out, None, cls.NOW, sample=True, hail_history=True, hail_addresses=True, storm_layers=True)
        cls.hail = json.loads(page(cls.out, "data/map.json"))["hail"]

    def test_no_b3_block_lists_every_tile_name_and_the_split_maps_say_which_have_a_file(self):
        # D40: each block has tile_split and no tiles list; the split map lists the store's tiles of that block
        index = json.loads((hs.FIXTURE_DIR / "hail" / "index.json").read_text(encoding="utf-8"))
        for key in ("addresses", "roads", "buildings"):
            block = self.hail[key]
            self.assertNotIn("tiles", block, key)
            self.assertIn("tile_split", block, key)
            # the sample store has no roads or outlines block, so their split maps are empty (the state says unavailable)
            self.assertEqual(tile_names_of(block), sorted(index.get(key, {}).get("tiles", [])), key)
        self.assertTrue(index["addresses"]["tiles"])
        self.assertEqual(self.hail["addresses"]["state"], "sample")
        self.assertEqual((self.hail["roads"]["state"], self.hail["buildings"]["state"]), ("unavailable", "unavailable"))
        self.assertEqual((self.hail["roads"]["tile_split"], self.hail["buildings"]["tile_split"]), ({}, {}))

    def test_the_buildings_split_map_lists_leaf_names_only(self):
        # D40 and D34: the outlines' split map lists each tile's leaf names; each leaf's box is derived in the browser from
        # its quadtree digits (map.js b3NameBox). The block is written here, as a loaded outlines block, so the test has leaves
        tiles = [f"r{r:04d}_c{c:04d}" for r in (79, 80) for c in range(198, 208)]     # 2 rows of 10 tiles: 20 tiles
        box = [-108.5, 45.7, -108.49, 45.71]
        split_boxes = {tile: [[tile + "0", box], [tile + "1", box]] for tile in tiles}   # two leaves per tile
        counts = {"footprints": 40, "multipart": 0, "with_addresses": 30, "without_address": 10, "matched_rows": 30,
                  "unmatched_rows": 5, "unmatched_by_class": {}}
        block = {"state": "loaded", "addresses": "loaded", "tiles": tiles, "split_boxes": split_boxes, "counts": counts,
                 "overhang_deg": 0.0, "counties": {"state": "unavailable"}, "source": {"file_date": "2026-09-13"}}
        blocks = site.b3_map_blocks({bd.INDEX_KEY: block}, "on")
        outlines = blocks["buildings"]
        self.assertEqual(outlines["state"], "loaded")
        self.assertNotIn("tiles", outlines)
        self.assertEqual(outlines["tile_split"], {"79": [[198, 207]], "80": [[198, 207]]})     # the same 20 tiles, compactly
        split = outlines["split"]
        self.assertIsInstance(split, dict)
        self.assertEqual(split, {tile: [name for name, leaf_box in leaves] for tile, leaves in split_boxes.items()})
        for tile, names in split.items():
            self.assertIsInstance(names, list, tile)
            self.assertTrue(names, tile)
            for name in names:
                self.assertIsInstance(name, str)
                self.assertTrue(name.startswith(tile) and len(name) > len(tile), name)
        # the three B3 blocks together name a tile in a key or a leaf and no tile list: the matches are the keys and the leaves
        raw = json.dumps({key: blocks[key] for key in ("addresses", "roads", "buildings")})
        leaves = sum(len(names) for names in split.values())
        self.assertLess(len(re.findall(r"r\d{4}_c\d{4}", raw)), len(split) + leaves + 20)

    def test_the_browser_reads_the_split_maps(self):
        # D40: map.js reads each block's tile_split through b3Listed (membership) and b3ListedCount (the test hook's counts)
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn("function b3Listed(", js)
        self.assertIn("function b3ListedCount(", js)
        for block in ("roads", "adr", "bld"):
            self.assertIn(f"b3Listed(B.tiles.{block}, t)", js)
        self.assertIn("b3ListedCount(B3.tiles.roads)", js)
        self.assertIn("own(split, String(t.r))", js)             # the row key is the number's decimal form, as str(r) writes it
        for old in ("tiles.roads[t.name]", "tiles.adr[t.name]", "tiles.bld[t.name]"):
            self.assertNotIn(old, js)                          # the old set lookups are gone
        self.assertEqual(js.count(".tiles[t.name]"), 1, "only the counts document (doc.tiles) keeps a name lookup")

    def test_the_address_text_off_mode_keeps_the_split_map_and_drops_the_search_names(self):
        # D35: --address-text off leaves out the search index's names and the form's words; the split map stays (D40)
        index = json.loads((hs.FIXTURE_DIR / "hail" / "index.json").read_text(encoding="utf-8"))
        blocks = site.b3_map_blocks({"addresses": index["addresses"]}, "off")       # the key is addresses.INDEX_KEY
        addresses = blocks["addresses"]
        self.assertEqual(addresses["text"], "off")
        self.assertNotIn("tiles", addresses)
        self.assertEqual(tile_names_of(addresses), sorted(index["addresses"]["tiles"]))
        for name in site.ADDRESS_SEARCH_KEYS:
            self.assertNotIn(name, addresses, name)
        for name in site.ADDRESS_FORM_WORDS:
            self.assertNotIn(name, addresses["templates"], name)

    def test_tile_split_round_trips(self):
        # D40: build.tile_split writes runs of columns per row, and tile_names_of reads them back as sorted names
        names = ["r0092_c0214", "r0092_c0215", "r0092_c0217", "r0079_c0199"]
        split = site.tile_split(names)
        self.assertEqual(split, {"79": [[199, 199]], "92": [[214, 215], [217, 217]]})
        self.assertEqual(tile_names_of({"tile_split": split}), sorted(names))
        self.assertEqual(site.tile_split([]), {})


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


def restore_base(data: bytes, changes) -> tuple[bytes, list]:
    """The page with each named on-purpose change written back to the base's text (D95(g)). A change the page does not
    carry exactly the stated number of times is a problem; the restored bytes are what the digest then compares."""
    problems = []
    for ruling, base_text, now_text, count in changes:
        new, old = now_text.encode("utf-8"), base_text.encode("utf-8")
        found = data.count(new)
        if found != count:
            problems.append(f"{ruling}: the page has {found} copies of {now_text!r}, not {count}")
        data = data.replace(new, old)
    return data, problems


def on_purpose_problems(name: str, data: bytes, changes, base_digest: str) -> list:
    """The problems with one page of the default build: a named change that is missing or repeated, or a line that no
    named change accounts for (the page still differs from the base's digest once the named changes are written back).
    An empty list means the page differs from the base only as the rulings name (D93(a), D95(g))."""
    restored, problems = restore_base(data, changes)
    if name.endswith(".html"):
        restored = VERSION_QUERY.sub(rb"\1?v=HASH", restored)
    if hashlib.sha256(restored).hexdigest() != base_digest:
        problems.append(f"{name} differs from the base build on a line that no named ruling accounts for")
    return problems


class HailSwathLayers(unittest.TestCase):
    """The live hail swath layers (B4; website/swath.py) behind --storm-layers, sample builds only (the live feed is
    checked by the Website workflow and tools/smoke_map.py): the two Map layers and their status line, the List and the
    no-JavaScript panel (with the SAMPLE credit), the map page's two radios, the About bullet, the words, the browser's
    scans (map.js: no threshold, word, unit or numeric literal in the swath section), a layer that cannot be read, and
    the default build's identity with the base commit (B4-6)."""

    NOW_SWATH = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    SWATH_BASE = "f96f5c7"                  # main at the B1 go-live (D59): the default build must match its build (B4-6)
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
        self.assertIn("not observed hail and not an inspection", L["legend_note"])   # the swath words (D89(e))

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

    def test_the_map_page_has_the_two_hail_chips_after_the_weather_layers_and_only_with_the_flag(self):
        from website import swath as sw
        on, off = page(self.on, "map.html"), page(self.off, "map.html")
        self.assertEqual([p.title for p in sw.PRODUCTS], list(self.HAIL_TITLES))
        for value, title in (("hail_60", self.HAIL_TITLES[0]), ("hail_1440", self.HAIL_TITLES[1])):
            self.assertEqual(on.count(f'data-group="live" data-key="{value}"'), 1)
            self.assertIn(f'<span class="mo-label">{title}</span>', on)
            self.assertNotIn(value, off)
        self.assertLess(on.index('data-key="satellite"'), on.index('data-key="hail_60"'))
        self.assertLess(on.index('data-key="hail_1440"'), on.index('id="mo-hist-h"'))

    def test_the_about_page_has_the_bullet_with_the_contract_words_and_only_with_the_flag(self):
        about = page(self.on, "about.html")
        c = src.CONTRACTS["hail_swath"]
        self.assertIn("<strong>Hail swath (radar estimate)</strong> is NOAA's MRMS MESH (maximum estimated size of hail), "
                      "a radar estimate", about)
        self.assertIn("not observed hail and not an inspection", about)     # the About wording (words owner, D41, D86)
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
        self.assertIn('data-key="hail_60"', on_map)

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
        labels = [plain(m) for m in re.findall(r'<button type="button" class="mo-chip"[^>]*>.*?</button>', map_html, re.S)
                  if "Hail, last" in m]
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
    # the manifest of the base commit's build (SWATH_BASE). Regenerate with write_default_manifest (see its docstring).
    # D93(a): map.js and map.css are not digested (SHARED_STATIC; the browser code is one file for every build), and the
    # ?v= hashes that map.html carries for them are normalised, so map.html differs from the base only in those hashes.
    MANIFEST = ROOT / "tests" / "fixtures" / "default-build-manifest.json"
    # The base is the commit the manifest names ("base"): the Veor shell on every page (D145) and the compact tile sets
    # (D144) changed the default build on purpose, so the manifest was written from that commit's own build and no ruling
    # is open. The rulings of the earlier base f96f5c7 (D53, D85, D91(c), D110(d) and D108, with the fixture
    # default-build-s1-rulings.json they read) are in git history at 1f9068e. A later change to the default build names
    # its ruling here, as (ruling, the base's text, the text the build has now, how many times the build has it), or
    # regenerates the manifest with write_default_manifest and says so in its pull request.
    ON_PURPOSE: dict = {}

    def test_the_default_build_matches_the_manifest_of_its_base_commit(self):
        expected = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        work = Path(tempfile.mkdtemp(prefix="hailwatch-identity-"))
        self.addCleanup(shutil.rmtree, work, True)
        out = work / "site"
        done = subprocess.run([sys.executable, "-m", "website.build", "--out", str(out), "--sample",
                               "--now", "2026-10-19T12:00:00Z"], cwd=ROOT, capture_output=True, text=True, timeout=900)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        now = default_digests(out)
        self.assertEqual(sorted(set(now) - set(expected["files"])), [], f"base {expected['base']}: files added")
        self.assertEqual(sorted(set(expected["files"]) - set(now)), [], f"base {expected['base']}: files removed")
        # every file the table does not name has the base's digest
        changed = sorted(name for name in now if now[name] != expected["files"][name] and name not in self.ON_PURPOSE)
        self.assertEqual(changed, [], f"base {expected['base']}: these files differ from the base build")
        # each named page differs from the base only in its named lines (the rulings above)
        for name, changes in self.ON_PURPOSE.items():
            problems = on_purpose_problems(name, (out / name).read_bytes(), changes, expected["files"][name])
            self.assertEqual(problems, [], f"base {expected['base']}: {'; '.join(problems)}")

    def test_a_line_the_table_does_not_name_fails_the_identity(self):
        """The check is exact: one more word in a page, not in the table, makes the page differ from the base, and a
        ruling names a change the page must carry exactly as often as it says."""
        expected = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        real = (self.off / "about.html").read_bytes()
        digest = expected["files"]["about.html"]
        self.assertEqual(on_purpose_problems("about.html", real, (), digest), [])
        mutated = real.replace(b"This is not an all-clear.", b"This is not an all-clear now.", 1)
        self.assertNotEqual(mutated, real)
        self.assertTrue(on_purpose_problems("about.html", mutated, (), digest))
        ruling = (("a test ruling", "<h1>About this site</h1>", "<h1>About this page</h1>", 1),)
        renamed = real.replace(b"<h1>About this site</h1>", b"<h1>About this page</h1>", 1)
        self.assertNotEqual(renamed, real)
        self.assertEqual(on_purpose_problems("about.html", renamed, ruling, digest), [])   # the named change, once
        self.assertTrue(on_purpose_problems("about.html", real, ruling, digest))            # the page lacks the change


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

    def test_the_cell_sentence_gives_the_radar_cell_and_the_grid_cell_their_own_sizes(self):          # the round-1 check's fix
        text = html.unescape(self.town)                       # the page escapes the apostrophe in "town's"
        self.assertIn("The radar rows are for the radar cell at the town's centre, about 0.7 miles north to south and 0.5 miles "
                      "east to west.", text)
        self.assertIn("The grid rows are for the grid cell there, about 4.6 km north to south and about 3 km east to west.", text)
        self.assertNotIn("The grid and radar rows are for that cell", text)

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


HISTORY_MAP_GATE = 163_840      # map.json with the history flag, raw bytes: 160 KB (D82(a), restating D66's 140 KB). The gate is
                                # the budget; the figures measured on the combined store are in
                                # research/hail-history/validation-evidence/b5-verification.json (every flag, B3 included, is
                                # recorded there beside it, not gated: D66).


def map_json_bytes(out: Path) -> int:
    """The raw size of the built map.json: the whole file, every block the history flag writes (the joins block too). A gate
    never measures a part of the file (D82(a)); the every-flag file, B3's tile sets included, is recorded beside the gate (D66)."""
    return len((out / "data" / "map.json").read_bytes())


def site_summary():
    from website import summary
    return summary


class MapBlocksForTheBrowser(unittest.TestCase):
    """The map.json blocks the browser fills (B5 part B2, site side; D29, D40, D42, D57): the words, the thresholds, the fixed
    orders, the file paths and the budgets are in the blocks, and the whole map.json with the history flag stays under 160 KB
    raw (D82(a)). Nothing here is real data: the sample build reads the committed fixture. HAIL_PARITY_STORE (a built store,
    the combined store) runs the same checks on the real store: the size, and the ice-dam line on each of the 17 town pages."""

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

    def test_the_section_order_is_one_constant_for_map_json_and_the_town_page(self):          # D87(g), D88(i)
        from website import summary as sm
        self.assertEqual(sm.SECTION_ORDER, tuple(sm.SECTION_KEYS))
        self.assertEqual(list(sm.SECTION_ORDER), self.SECTIONS)
        block = self.hail_block()["summary"]
        self.assertEqual(block["section_order"], list(sm.SECTION_ORDER))
        self.assertEqual(block["sections"], list(sm.SECTION_ORDER))
        town = page(self.out, "town/billings.html")
        pos = [town.index(f'id="sec-{sid}"') for sid in sm.SECTION_ORDER]
        self.assertEqual(pos, sorted(pos), "the town page shows the sections in SECTION_ORDER")

    def test_the_joins_block_carries_the_six_section_order_and_the_per_tile_events_path(self):
        j = self.hail_block()["joins"]
        self.assertEqual(j["section_order"], ["reports", "records", "detections", "warnings", "zones", "stations"])
        self.assertEqual(j["events_tiles"], "hail/j/e/{tile}.json")              # D30: the browser fetches this, never events.json
        self.assertEqual(j["shards"]["s"], "hail/s/{station}.json")

    def test_the_budget_block_holds_the_phone_view_and_the_per_tile_file(self):                  # D66, D82(b): 700,000 bytes gzip
        from website import joins as jn
        self.assertEqual(self.hail_block()["budget"], {"phone_gzip_bytes": site.PHONE_GZIP_BUDGET,
                                                       "tile_events_gzip_bytes": jn.TILE_EVENTS_BUDGET_GZIP})
        self.assertEqual(self.hail_block()["budget"]["phone_gzip_bytes"], site.PHONE_GZIP_BUDGET)   # D88(r): the build's constant
        self.assertEqual(site.PHONE_GZIP_BUDGET, 700_000)                 # D82(b): restated with its reason, no cut
        self.assertEqual(jn.TILE_EVENTS_BUDGET_GZIP, 100_000)

    def test_map_json_with_the_history_flag_stays_under_160_kb_raw_with_the_new_keys(self):   # D82(a): the whole file
        size = map_json_bytes(self.out)
        self.assertLess(size, HISTORY_MAP_GATE, size)

    def test_the_new_keys_the_browser_reads_are_in_the_blocks(self):                       # D68, D71, D79(a), the sections' data
        h = self.hail_block()
        summary = h["summary"]
        names = h["county"]["names"]
        self.assertEqual(h["county"]["short_names"], {code: name.replace(" County", "") for code, name in names.items()})
        words = h["stations"]["words"]
        self.assertEqual({k: words[k] for k in ("station_status_failed", "station_status_not_read",
                                                "station_status_not_read_many", "station_status_both")},
                         {"station_status_failed": "did not load", "station_status_not_read": "is not read",
                          "station_status_not_read_many": "are not read", "station_status_both": "could not be read"})
        self.assertIn("A station's position comes from its source. Two sources can place one airport a few hundred yards apart, "
                      "so two rows may give slightly different distances to the same airport.", summary["how_made"])     # D80(c)
        self.assertEqual(summary["section_kinds"], site_summary().SECTION_KINDS)
        self.assertEqual(len(summary["indicators"]["roof_lines"]), 23)
        self.assertEqual(summary["indicators"]["roof_lines"]["hail_warnings"]["label"],
                         "Severe thunderstorm warnings {covered} (count)")
        self.assertEqual(summary["codes"]["polygon"]["sv"], ["SV"])
        self.assertEqual(summary["codes"]["depth_pair"], "DL")
        self.assertEqual(summary["rule"]["report_miles"], 5.0)
        self.assertEqual(set(summary["indicators"]["held_names"]), {"ponding", "roof_surface_temperature", "fema_flood_zones",
                                                                     "lightning", "uv_and_sun", "ground_snow_load", "snotel"})

    def test_the_ice_dam_line_on_the_billings_page_leads_with_station_reading(self):      # D57
        self.assertTrue(ice_line_text(page(self.out, "town/billings.html")).startswith("Station reading: "))

    def test_with_the_real_store_every_town_page_leads_with_station_reading_and_map_json_is_under_160_kb(self):   # D57, D82(a)
        store = os.environ.get("HAIL_PARITY_STORE")
        if not store:
            self.skipTest("set HAIL_PARITY_STORE to a built store (the combined store) to check the 17 town pages")
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b2-real-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=store)
        self.assertLess(map_json_bytes(out), HISTORY_MAP_GATE, map_json_bytes(out))
        towns = json.loads((ROOT / "website" / "towns.json").read_text(encoding="utf-8"))
        for town in towns:
            with self.subTest(town["slug"]):
                self.assertTrue(ice_line_text(page(out, f"town/{town['slug']}.html")).startswith("Station reading: "))


# ---------------------------------------------------------------- the five-season table and sections in the browser (B5)

SUM_BLOCK_START = "  var SUM_SEASONS"              # the browser's summary block in map.js (B5, the sheet's table and sections)
SUM_BLOCK_END = "  // B3 layers: begin"
# the top-level vars and functions outside the block that the block calls (the hail and join readers and the words helpers);
# a name that moves or is renamed fails the run with a ReferenceError that names it
SUM_VARS = ("MIN", "dtfUtcDay", "HAIL_DAY_MS", "HAIL_MICRO", "JROW", "JDET", "JDAY", "JZONE_STOP", "JOIN_PARTS", "KIND_WORD", "FALLBACK_VIEW",
            "BLANK")
SUM_HELPERS = ("fill", "own", "missingKey", "hailTile", "hailTileName", "hailShardUrl", "hailCentre", "hailKey", "hailDate",
               "hailIso", "hailDays", "hailFailure", "joinEvents", "joinFile", "joinZoneOf", "joinPicks", "joinUnavailable",
               "joinWarningText", "joinClock", "joinCompass", "joinCovers", "joinDay", "joinEnd", "joinInstant", "joinMiles",
               "joinReason", "joinRecordText", "joinReportText", "joinSpcIso", "joinZoneRecordText", "joinZoneSpan", "hailCell",
               "hailPoint", "hailInState", "hailMm", "hailInches", "hailClass", "stWord", "pad4", "has", "hailText",
               "thousands")
# node runs the sheet's table (sumTable) and, in mode "sheet", renders it (sumRender) into a stand-in for the page's elements,
# which keep their text and children, so a test reads every line the sheet shows. Only fetch is stubbed (the built site's files).
NODE_SUMMARY_SCRIPT = r"""
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
      : { ok: true, status: 200, json: () => new Promise((ok) => ok(JSON.parse(text))) }));
  });
  class El {
    constructor(tag) { this.tag = tag; this.children = []; this.text = ""; this.hidden = false; this.className = ""; }
    appendChild(c) { this.children.push(c); return c; }
    insertRow() { const r = new El("tr"); this.children.push(r); return r; }
    insertCell() { const c = new El("td"); this.children.push(c); return c; }
    createTHead() { const t = new El("thead"); this.children.push(t); return t; }
    createTBody() { const t = new El("tbody"); this.children.push(t); return t; }
    setAttribute() {}
    get textContent() { return this.text; }
    set textContent(v) { this.text = String(v); }
    get classList() { return { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
    querySelector() { return null; }
    closest() { return null; }
    remove() {}
  }
  const texts = (node, out) => { if (node.text) out.push(node.text); node.children.forEach((c) => texts(c, out)); return out; };
  const document = { createElement: (tag) => new El(tag), createTextNode: (t) => { const e = new El("#text"); e.text = String(t); return e; },
    getElementById: () => null };
  const ctx = vm.createContext({ Intl: Intl, Date: Date, Math: Math, JSON: JSON, Promise: Promise, Set: Set, Object: Object,
    Array: Array, String: String, Number: Number, Error: Error, isFinite: isFinite, RegExp: RegExp, fetch: fetchFile,
    data: { tz: input.tz }, hailTiles: {}, document: document, window: { console: console }, console: console,
    texts: texts });
  vm.runInContext(input.code, ctx);
  vm.runInContext("this.run = (h, cell) => sumTable(h, cell).then((r) => {" +
    " const out = { rows: r.rows, partial: r.partial };" +
    " if (" + (input.mode === "sheet" ? "true" : "false") + ") { const slot = document.createElement('div');" +
    " sumRender(slot, r); out.sheet = texts(slot, []); } return out; });", ctx);
  ctx.run(input.h, input.cell).then((out) => process.stdout.write(JSON.stringify(out)),
    (err) => { process.stderr.write(String((err && err.stack) || err)); process.exit(1); });
});
"""


def js_var(js: str, name: str) -> str:
    """One top-level var of map.js ("  var NAME = ..."): its line, or its lines up to the one that closes the value."""
    lines = js.split("\n")
    first = next(n for n, line in enumerate(lines) if line.startswith(f"  var {name} "))
    text, n = lines[first], first
    while True:
        code = re.sub(r"\s//[^\"']*$", "", text).rstrip()
        if code.endswith(";") and text.count("{") + text.count("[") <= text.count("}") + text.count("]"):
            return "\n".join(lines[first:n + 1])
        n += 1
        text = lines[n]


def browser_summary_code(js: str) -> str:
    """The part of map.js the sheet's five-season table runs on: the vars and helpers the block calls, then the block from its
    first line to the roads and addresses block (B3). Nothing else of the page is run."""
    start = js.index(SUM_BLOCK_START)
    end = js.index(SUM_BLOCK_END)
    start = js.rindex("\n", 0, start) + 1
    end = js.rindex("\n", 0, end) + 1
    return "\n".join([js_var(js, name) for name in SUM_VARS] + [js_function(js, name) for name in SUM_HELPERS]
                     + [js[start:end]])


def node_summary(site: Path, h: dict, cell: dict, mode: str = "table") -> dict:
    """The browser's table at a cell (sumTable under node; mode "sheet" also renders it, as the sheet shows it): the rows by key,
    the partial line and, in sheet mode, every text the rendered sheet holds."""
    js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
    payload = {"code": browser_summary_code(js), "site": str(site), "h": h, "cell": cell, "tz": "America/Denver", "mode": mode}
    done = subprocess.run([shutil.which("node"), "-e", NODE_SUMMARY_SCRIPT], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=180)
    if done.returncode:
        raise AssertionError(f"the browser's five-season table did not run under node: {done.stderr[-900:]}")
    return json.loads(done.stdout)


def block_literals(js: str) -> list[str]:
    """The string literals of the browser's summary block (double or single quoted), without their quotes. The comments
    are taken out first, so an apostrophe in a comment starts no literal."""
    start = js.index(SUM_BLOCK_START)
    end = js.index(SUM_BLOCK_END)
    code = re.sub(r"/\*.*?\*/", "", js[start:end], flags=re.S)           # the JSDoc comments first
    code = re.sub(r"//[^\n]*", "", code)
    code = re.sub(r"console\.\w+\([^;]*\);", "", code)                  # developer log lines are not sheet text
    found = re.findall(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', code)
    return [a or b for a, b in found]


class SheetFiveSeasonsInTheBrowser(unittest.TestCase):
    """The browser's five-season table on the sheet (B5, the browser's round 1 and round 2): it runs map.js's summary code under
    node on the synthetic store's built site (the fixture), and checks what the sheet shows against the module's rows. The
    rules: a missing words key shows a placeholder and never stops the table (R1, R2); every note of a row is on the sheet
    (R4); a records failure keeps its row's label and kind (R5); a zone product that could not be placed is said in its season
    (R14); the block holds no sheet sentence as a literal (R6)."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    CELL = {"row": 921, "col": 2149}                    # the B1 cell of Billings (the town point is 45.7833 N, 108.5007 W)

    @classmethod
    def setUpClass(cls):
        # the committed sample fixture (website/data/hail-fixture): its Billings tile holds the per-tile event files the browser
        # reads (hail/j/e), which the synthetic store of tests/test_summary.py does not
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-sheet-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        site.build(cls.out, None, cls.NOW, sample=True, hail_history=True)
        cls.h = json.loads(page(cls.out, "data/map.json"))["hail"]

    def copy_h(self) -> dict:
        """A copy of the built block. The fixture has no climate grid (its climate part is unavailable), so the copy takes a
        stand-in grid far outside Montana: the cell is then outside the grid and the climate rows say so, and the table's
        other rows are the ones under test. test_a_store_without_the_climate_grid_still_builds_the_table uses the block as built."""
        h = json.loads(json.dumps(self.h))
        if h["climate"].get("grid") is None:
            h["climate"]["grid"] = {"rows": 1, "cols": 1, "per_degree": 24, "lat0": 0.0, "lon0": 0.0, "units_per_degree": 48,
                                    "lat_centre_units": [0, 0], "lon_centre_units": [0, 0], "lat_edge_units": 0,
                                    "lon_edge_units": 0, "rule": "lat (south edge, north edge], lon [west edge, east edge)"}
        return h

    def test_a_store_without_the_climate_grid_still_builds_the_table(self):                                    # D16
        out = node_summary(self.out, json.loads(json.dumps(self.h)), self.CELL)
        self.assertEqual(len(out["rows"]), 24)                  # the climate part says its own words, the rest of the table builds

    def test_the_table_builds_with_placeholders_when_report_types_nouns_or_table_problem_are_missing(self):   # R1, R2
        h = self.copy_h()
        del h["summary"]["report_types"]
        del h["summary"]["nouns"]
        del h["summary"]["words"]["table_problem"]
        out = node_summary(self.out, h, self.CELL)
        self.assertEqual(len(out["rows"]), 24)
        text = json.dumps(out)
        self.assertIn("[missing words key: report_types]", text)
        self.assertIn("[missing words key: nouns]", text)
        # a part that throws is said with the table_problem words; a missing key there is a placeholder, not a crash
        h = self.copy_h()
        del h["joins"]["words"]
        del h["summary"]["words"]["table_problem"]
        out = node_summary(self.out, h, self.CELL)
        self.assertEqual(len(out["rows"]), 24)
        self.assertIn("[missing words key: table_problem]", json.dumps(out))

    def test_every_row_note_is_on_the_sheet(self):                                                              # R4
        out = node_summary(self.out, self.h, self.CELL, mode="sheet")
        sheet = out["sheet"]
        notes = [n for row in out["rows"].values() for n in row["notes"]]
        self.assertGreater(len(notes), 5)
        missing = [n for n in notes if not any(n in text for text in sheet)]
        self.assertEqual(missing, [], missing[:3])

    def test_every_row_note_is_on_the_sheet_with_an_unread_candidate_and_a_rejected_one(self):               # R4, (3b), D32, D62, D69
        """The unread line (a Canadian station, not read, nearer than the second pick, so the snowfall row names it) and the
        rejected line (a station that fails the rule, named with its share) are row notes, and the sheet shows them. A copy of
        the built site gets the unread candidate on the fixture's Billings tile; the rejected line is the fixture's own."""
        from website import hail as hs
        from website import stations as st
        copy = Path(tempfile.mkdtemp(prefix="hailwatch-unread-"))
        self.addCleanup(shutil.rmtree, copy, True)
        shutil.copytree(self.out, copy / "site")
        tile = hs.tile_name(self.CELL["row"] // hs.TILE, self.CELL["col"] // hs.TILE)
        path = copy / "site" / "hail" / "tl" / f"{tile}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        snow = doc["elements"]["SNOW"]
        snow["unread"] = list(snow["unread"]) + [{"id": "CA000000001", "name": "Milk River", "lat": 45.80, "lon": -108.50,
                                                 "reason": st.CANADA_REASON}]
        path.write_text(json.dumps(doc), encoding="utf-8")
        out = node_summary(copy / "site", self.h, self.CELL, mode="sheet")
        notes = [n for row in out["rows"].values() for n in row["notes"]]
        self.assertTrue(any("Milk River is not read (in Canada; the terms for its data are under review)" in n for n in notes),
                        notes[:3])
        self.assertTrue(any(" is not used: " in n for n in notes), notes[:3])
        missing = [n for n in notes if not any(n in text for text in out["sheet"])]
        self.assertEqual(missing, [], missing[:3])

    def test_with_the_real_store_every_row_note_reaches_the_sheet_at_four_cells(self):                      # R4, (3b), D62
        """On the combined store every row note of four cells is on the sheet: the gate cell 797,1986, Benchland 792,1998,
        Billings 921,2149, and cell 602,1396, whose snowfall row names the unread Canadian station Lister."""
        store = os.environ.get("HAIL_PARITY_STORE")
        if not store:
            self.skipTest("set HAIL_PARITY_STORE to a built store (the combined store) to check the sheet at the real cells")
        out = Path(tempfile.mkdtemp(prefix="hailwatch-sheet-real-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=store)
        h = json.loads(page(out, "data/map.json"))["hail"]
        for row, col in ((921, 2149), (792, 1998), (797, 1986), (602, 1396)):
            with self.subTest(cell=f"{row},{col}"):
                sheet = node_summary(out, h, {"row": row, "col": col}, mode="sheet")
                notes = [n for r in sheet["rows"].values() for n in r["notes"]]
                missing = [n for n in notes if not any(n in text for text in sheet["sheet"])]
                self.assertEqual(missing, [], missing[:3])
                if (row, col) == (602, 1396):
                    self.assertTrue(any("Lister is not read" in n for n in notes), "the unread line at 602,1396")

    def test_a_zone_product_that_could_not_be_placed_is_said_in_its_season_cell(self):                         # R14
        h = self.copy_h()
        h["joins"]["zone_unplaced_rows"] = [["HW.W", "MTZ235", "2025-07-18", "2025-07", "the zone code is not in the zone maps"]]
        row = node_summary(self.out, h, self.CELL)["rows"]["hw_zone"]
        season_2025_26 = " ".join([row["coverage"][4] or "", row["texts"][4] or ""] + row["notes"])
        self.assertIn("could not be placed to a zone", season_2025_26)
        self.assertNotIn("could not be placed to a zone", " ".join([row["coverage"][0] or ""]))

    def test_a_records_failure_keeps_the_row_label_and_kind(self):                                              # R5
        h = self.copy_h()
        h["joins"]["parts"]["records"] = "unavailable"
        row = node_summary(self.out, h, self.CELL)["rows"]["flood_record_n"]
        self.assertEqual(row["label"], "Flood and flash flood records within 5 miles")
        self.assertEqual(row["kind"], "Record (NCEI)")
        self.assertTrue(any("This is not an all-clear." in n for n in row["notes"]), row["notes"])

    def test_no_sheet_sentence_is_a_string_literal_in_the_summary_block(self):                                  # R6, (e)
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        # a sentence is three words or more; the two-word LSR kinds (freezing rain, flash flood) are the data's own words
        kinds = {"freezing rain", "flash flood", "funnel cloud", "extreme heat"}
        sentences = [lit for lit in block_literals(js) if len(lit.split()) >= 3 or (len(lit.split()) == 2 and lit not in kinds
                                                                                       and lit.islower() and " " in lit
                                                                                       and not lit.startswith(".")
                                                                                       and not re.search(r"[-_.]", lit))]
        self.assertEqual(sentences, [], sentences[:5])


# ---------------------------------------------------------------- the whole sheet in the browser against the module (B5 round 3)

# node runs the sheet as the page runs it: the table (sumTable and sumRender), the joined records (joinSections), the B1 radar
# text (hailText) and the eleven sections (histModel and histRender). Each element keeps its text, its children and its
# attributes, so the test reads every line the sheet holds, the rows behind "Show all" included. Only fetch is stubbed.
NODE_SHEET_SCRIPT = r"""
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
      : { ok: true, status: 200, json: () => new Promise((ok) => ok(JSON.parse(text))) }));
  });
  class El {
    constructor(tag) { this.tag = tag; this.children = []; this.text = ""; this.attrs = {}; this.hidden = false; this.className = ""; }
    appendChild(c) { this.children.push(c); return c; }
    insertRow() { const r = new El("tr"); this.children.push(r); return r; }
    insertCell() { const c = new El("td"); this.children.push(c); return c; }
    createTHead() { const t = new El("thead"); this.children.push(t); return t; }
    createTBody() { const t = new El("tbody"); this.children.push(t); return t; }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
    get textContent() { return this.text; }
    set textContent(v) { this.text = String(v); }
    get classList() { return { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
    querySelector() { return null; }
    closest() { return null; }
    remove() {}
  }
  const document = { createElement: (tag) => new El(tag), createTextNode: (t) => { const e = new El("#text"); e.text = String(t); return e; },
    getElementById: () => null };
  const ctx = vm.createContext({ Intl: Intl, Date: Date, Math: Math, JSON: JSON, Promise: Promise, Set: Set, Object: Object,
    Array: Array, String: String, Number: Number, Error: Error, isFinite: isFinite, RegExp: RegExp, fetch: fetchFile,
    data: { tz: input.tz }, hailTiles: {}, document: document, window: { console: console }, console: console });
  vm.runInContext(input.code, ctx);
  vm.runInContext(`
    this.texts = (node, out) => { if (node.text) out.push(node.text); node.children.forEach((c) => texts(c, out)); return out; };
    this.sectionTexts = (root) => {
      const found = {};
      const walk = (node, current) => {
        const id = node.getAttribute("data-section");
        const here = id !== null ? id : current;
        if (node.text && here !== null) (found[here] = found[here] || []).push(node.text);
        node.children.forEach((c) => walk(c, here));
      };
      walk(root, null);
      return found;
    };
    this.runCell = async (h, cell) => {
      const table = await sumTable(h, cell);
      const joins = await joinSections(h, cell);
      const doc = await hailTile(hailShardUrl(h, cell));
      const radar = hailText(h, cell, doc);
      const model = histModel(h, cell, table, joins, radar);
      const tableSlot = document.createElement("div");
      sumRender(tableSlot, table);
      const sectionSlot = document.createElement("div");
      histRender(sectionSlot, model);
      return { table: { rows: table.rows, partial: table.partial }, model: model, radar: radar,
        tableTexts: texts(tableSlot, []), sectionTexts: sectionTexts(sectionSlot) };
    };`, ctx);
  ctx.runCell(input.h, input.cell).then((out) => process.stdout.write(JSON.stringify(out)),
    (err) => { process.stderr.write(String((err && err.stack) || err)); process.exit(1); });
});
"""

# the browser's share rounding (sumSharePct, under node) over the shares the station rule can see: round(k / 2192, 4)
NODE_SHARE_SCRIPT = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const ctx = require("vm").createContext({ Math: Math, Number: Number, String: String, Object: Object, Array: Array, RegExp: RegExp });
require("vm").runInContext(input.code + "\nthis.pct = (S, xs) => xs.map(function (x) { return sumSharePct(S, x); });", ctx);
process.stdout.write(JSON.stringify(ctx.pct(input.S, input.shares)));
"""

# the browser's season rule (D83(b), D87(d)): the 95 percent share of a season's days, the season label of a day and the
# bounds of a label, called with the summary block the build wrote (the signature may take S first; the script adapts)
NODE_SEASON_SCRIPT = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const ctx = require("vm").createContext({ Math: Math, Number: Number, String: String, Object: Object, Array: Array,
  RegExp: RegExp, Date: Date, Error: Error, JSON: JSON });
require("vm").runInContext(input.code + "\nthis.season = {"
  + " rule: function (S) { return sumSeasonRule(S); },"
  + " label: function (S, iso) { return sumSeasonOf.length === 2 ? sumSeasonOf(S, iso) : sumSeasonOf(iso); },"
  + " bounds: function (S, label) { return sumBounds.length === 2 ? sumBounds(S, label) : sumBounds(label); },"
  + " iso: function (n) { return sumIsoOf(n); } };", ctx);
const S = input.S;
const share = ctx.season.rule(S);
const full = [];
for (const total of input.totals) {
  for (let valid = 0; valid <= 366; valid++) full.push([total, valid, valid * share.scale >= total * share.share]);
}
const bounds = input.labels.map(function (label) {
  const b = ctx.season.bounds(S, label);
  return [label, ctx.season.iso(b.start), ctx.season.iso(b.end)];
});
const labels = input.days.map(function (iso) { return [iso, ctx.season.label(S, iso)]; });
process.stdout.write(JSON.stringify({ share: share, full: full, bounds: bounds, labels: labels }));
"""

# the four exact ties of the share rule (k / 2192 is a sixteenth: its percent ends in .x5): half to even, as Python's round()
SHARE_TIES = {137: "6.2", 685: "31.2", 1233: "56.2", 1781: "81.2"}

# the five cells the brief names for the browser against the module: Billings, Benchland, the gate, and two more
FIVE_CELLS = ((921, 2149), (792, 1998), (797, 1986), (753, 2230), (920, 1899))

# every key of the summary block that map.js reads, by the form the read takes (round 3: the summary contract)
def summary_reads(js: str) -> dict:
    words = set(re.findall(r'sumWord\(\s*[\w.]+\s*,\s*"([^"]+)"', js))
    paths = {p for p in re.findall(r'sdGet\(\s*\w+\s*,\s*"([^"]+)"', js) + re.findall(r'sdList\(\s*\w+\s*,\s*"([^"]+)"', js)
             if not p.endswith(".")}
    rule = set(re.findall(r"\bS\.rule\.(\w+)", js)) | set(re.findall(r'own\(\s*S\.rule,\s*"(\w+)"', js))
    indicators = set(re.findall(r"S\.indicators\.words\.(\w+)", js)) | set(re.findall(r'own\(\s*S\.indicators\.words,\s*"(\w+)"', js))
    top = set(re.findall(r"\bS\.(\w+)", js)) - {"rule", "words", "indicators", "unplaced", "canada"}
    # the block's own reads by its object name (h.summary.partial, hd.summary.words, own(h.summary, "tile_list")), R1-F6
    direct = set(re.findall(r"\bh[d]?\.summary\.(\w+)", js)) | set(re.findall(r'own\(\s*h[d]?\.summary,\s*"(\w+)"', js))
    return {"words": words, "paths": paths, "rule": rule, "indicators": indicators, "top": top | direct}


def node_sheet(site: Path, h: dict, cell: dict) -> dict:
    """The sheet's table and sections for a cell as the browser's code writes them (under node), with h the map.json hail
    block the page reads and site the built folder its fetches read."""
    js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
    payload = {"code": browser_join_code(js) + "\n" + browser_summary_code(js), "site": str(site), "h": h, "cell": cell,
               "tz": "America/Denver"}
    done = subprocess.run([shutil.which("node"), "-e", NODE_SHEET_SCRIPT], input=json.dumps(payload), capture_output=True,
                          text=True, timeout=300)
    if done.returncode:
        raise AssertionError(f"the browser's sheet did not run under node: {done.stderr[-900:]}")
    return json.loads(done.stdout)


def module_sheet(site: Path, cell: tuple[int, int], now) -> dict:
    """The sheet for a cell as the module writes it: summary.describe_sheet (D88(p), S-4), the one function the browser's sheet
    is compared with. Its keys: summary (table, sections' leads, roof), radar (the B1 words), joined (the join views), built
    (the rows and notes of the eleven sections) and section_order."""
    from website import summary as sm
    row, col = cell
    return sm.describe_sheet(site, row, col, now)


def section_rows(rows: list[dict]) -> list[list[str]]:
    """The label, text and note of each row, in the form both sides are compared in."""
    return [[r.get("label", ""), r["text"], r.get("note", "") or ""] for r in rows]


class SheetAgreesWithTheModule(unittest.TestCase):
    """The sheet in the browser against the module at the five cells (B5 round 3, D82(d), D83): the table, every row note,
    each section's lead, kind, rows and notes, and the roof lines, from the same data. The rows behind "Show all" are in
    the rendered sheet too (D83(a)). The fixture is the committed sample; the adopted store is HAIL_PARITY_STORE."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed; tools/smoke_map.py checks the same sheet in Chromium")
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-agree-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        site.build(cls.out, None, cls.NOW, sample=True, hail_history=True)
        cls.h = json.loads(page(cls.out, "data/map.json"))["hail"]

    def cell_differences(self, folder: Path, h: dict, cell: tuple[int, int]) -> list[str]:
        """One cell: the browser's table, sections and radar against the module's, row by row. Every difference is collected
        and reported together (with its place), so one run shows the whole list the browser has to mirror."""
        row, col = cell
        mod = module_sheet(folder, cell, self.NOW)
        browser = node_sheet(folder, h, {"row": row, "col": col})
        summary = mod["summary"]
        if summary.get("state") not in ("loaded", "partial"):      # partial: the fixture has no climate grid (a stated part)
            self.skipTest(f"cell {row},{col} is outside the built store ({summary.get('state')})")
        diffs: list[str] = []

        def check(where: str, got, want) -> None:
            if got != want:
                diffs.append(f"{where}: browser {json.dumps(got, ensure_ascii=False)[:220]} != module "
                             f"{json.dumps(want, ensure_ascii=False)[:220]}")

        # the table: every row's cells, five-season figure, coverage and notes
        module_rows = {r["key"]: r for r in summary["table"]["rows"]}
        check("table rows", sorted(browser["table"]["rows"]), sorted(module_rows))
        for key, mrow in module_rows.items():
            brow = browser["table"]["rows"].get(key, {})
            for field in ("texts", "coverage", "values", "five", "five_text", "five_coverage", "five_missing", "notes"):
                check(f"table {key}.{field}", brow.get(field), mrow[field])
        check("radar lead", browser["radar"].get("lead"), mod["radar"].get("lead"))
        # the sections: heading, lead, kind, rows (behind Show all too) and notes, in the brief's order
        built = mod["built"]
        by_id = {sec["id"]: sec for sec in browser["model"]["sections"]}
        check("section order", [sec["id"] for sec in browser["model"]["sections"]], sm_sections())
        for sec in summary["sections"]:
            sid = sec["id"]
            got = by_id.get(sid, {})
            check(f"{sid} heading", got.get("heading"), sec["heading"])
            check(f"{sid} lead", got.get("lead"), sec["lead"])
            check(f"{sid} kind", got.get("kind"), sec["kind"])
            check(f"{sid} rows", section_rows(got.get("rows", [])), section_rows(built["rows"][sid]))
            if sid != "roof":
                check(f"{sid} notes", got.get("notes"), built["notes"][sid])
            rendered = browser["sectionTexts"].get(sid, [])
            for text in [r["text"] for r in got.get("rows", [])] + list(got.get("notes", [])):
                if text not in rendered:
                    diffs.append(f"{sid}: a text is not in the rendered sheet: {text[:120]}")
        module_lines = [(ln["label"], ln["text"], ln["kind"]) for g in summary["roof"]["groups"] for ln in g["lines"]]
        browser_lines = [(ln["label"], ln["text"], ln["kind"]) for g in by_id.get("roof", {}).get("groups") or []
                         for ln in g["lines"]]
        check("roof lines", browser_lines, module_lines)
        check("roof how made", by_id.get("roof", {}).get("notes"), summary["roof"]["how_made"])
        # nothing the sheet shows is a placeholder (the words the sheet asks for are in the summary block)
        everything = browser["tableTexts"] + [t for texts_ in browser["sectionTexts"].values() for t in texts_]
        diffs += [f"placeholder on the sheet: {t[:120]}" for t in everything if "[missing" in t]
        return diffs

    def compare_cell(self, folder: Path, h: dict, cell: tuple[int, int]) -> None:
        diffs = self.cell_differences(folder, h, cell)
        self.assertEqual(diffs, [], f"cell {cell[0]},{cell[1]}: {len(diffs)} difference(s), the browser against the module")

    def test_the_five_cells_agree_on_the_fixture(self):                                                       # D82(d), D83, R1-F2
        """The committed sample holds the joined records of three tiles only (hail/j). A cell whose tile the sample lacks is a
        skipped subtest that names the cell, never a silent continue; the present set is asserted, and the adopted store test
        below compares all five."""
        present = [cell for cell in FIVE_CELLS
                   if (self.out / "hail" / "j" / f"{hs.tile_name(cell[0] // hs.TILE, cell[1] // hs.TILE)}.json").exists()]
        compared = []
        for cell in FIVE_CELLS:
            with self.subTest(cell=cell):
                if cell not in present:
                    self.skipTest(f"the fixture holds no joined tile for the cell {cell[0]},{cell[1]} (only the adopted store does)")
                self.compare_cell(self.out, self.h, cell)
                compared.append(cell)
        self.assertEqual(sorted(present), sorted(FIVE_CELLS[:3]), "the sample's present tiles")
        self.assertEqual(sorted(compared), sorted(present))

    def test_the_rendered_sheet_holds_every_row_behind_show_all(self):                                       # D83(a)
        mod = module_sheet(self.out, FIVE_CELLS[0], self.NOW)
        browser = node_sheet(self.out, self.h, {"row": FIVE_CELLS[0][0], "col": FIVE_CELLS[0][1]})
        for sec in browser["model"]["sections"]:
            rendered = browser["sectionTexts"].get(sec["id"], [])
            for r in sec["rows"]:
                self.assertIn(r["text"], rendered)
        self.assertGreaterEqual(max(len(s["rows"]) for s in browser["model"]["sections"]), 1)
        self.assertEqual(browser["model"]["showFirst"], self.h["joins"]["show_first"])
        self.assertTrue(mod["built"]["rows"])

    @unittest.skipUnless(os.environ.get("HAIL_PARITY_STORE"), "set HAIL_PARITY_STORE to the adopted combined store")
    def test_the_five_cells_agree_on_the_adopted_store(self):                                                 # D82(d), D83, D64
        folder = Path(tempfile.mkdtemp(prefix="hailwatch-agree-real-"))
        self.addCleanup(shutil.rmtree, folder, True)
        site.build(folder, None, self.NOW, sample=True, hail_history=True,
                   hail_store_path=os.environ["HAIL_PARITY_STORE"])
        h = json.loads(page(folder, "data/map.json"))["hail"]
        for cell in FIVE_CELLS:
            with self.subTest(cell=cell):
                self.compare_cell(folder, h, cell)

    def test_a_flagged_zone_line_reads_the_all_clear_sentence_once(self):                                    # D98(b), D99(b)
        """Montana's unplaced zone products (two high wind warnings in 2021-22, one high wind watch in 2024-25) add a statement
        to the high wind row's coverage lines. The browser prints the statement as summary.WORDS_SUMMARY gives it and composes
        each line as summary._cover does: the sentence once, at the line's end, never a doubled full stop. The sheet agrees
        with the module cell by cell, the coverage lines included. The rows go into a copy of the fixture store, with its
        index and its manifest entry written again (hail.check_manifest)."""
        store = Path(tempfile.mkdtemp(prefix="hailwatch-flag-store-"))
        self.addCleanup(shutil.rmtree, store, True)
        shutil.copytree(hs.FIXTURE_DIR, store, dirs_exist_ok=True)
        index_path = store / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["joins"]["zone_unplaced_rows"] = [["HW.W", "MTZ235", "2021-12-11", "2021-12-07", "not_in_iem_set"],
                                                ["HW.W", "MTZ235", "2022-01-02", "2021-12-07", "not_in_iem_set"],
                                                ["HW.A", "MTZ235", "2024-10-01", "2024-09-30", "not_in_iem_set"]]
        data = hs._pretty(index)
        index_path.write_bytes(data)
        manifest_path = store / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["hail/index.json"] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        manifest_path.write_bytes(hs._pretty(manifest))
        hs.check_manifest(store)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-flag-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        h = json.loads(page(out, "data/map.json"))["hail"]
        self.assertEqual(len(h["joins"]["zone_unplaced_rows"]), 3)
        for cell in FIVE_CELLS[:3]:                 # the cells the fixture holds (the other two need the adopted store)
            with self.subTest(cell=cell):
                self.compare_cell(out, h, cell)
        rows = node_sheet(out, h, {"row": 921, "col": 2149})["table"]["rows"]
        flagged = [text for row in rows.values() for text in row["coverage"] + [row["five_coverage"]]
                   if text and "could not be placed to a zone" in text]
        self.assertTrue(flagged, "the high wind row says what could not be placed")
        for text in flagged:
            self.assertEqual(text.count("This is not an all-clear."), 1, text)
            self.assertTrue(text.endswith("This is not an all-clear."), text)
            self.assertNotIn("..", text)

    def test_a_partial_stations_part_adds_the_same_note_in_the_browser_and_the_module(self):                 # D20, D41, B5-12
        """When the station gusts loaded for some station-years only (the joins block's parts.stations is "partial"), summary.py
        closes both gust rows' notes with the sentence that names the station-years that did not load, with the reason the
        block gives and the all-clear sentence once, and the wind section carries it once. The browser mirrors that from the
        same block: the branch's own store had 65 such station-years, and the preview's parity step found the browser without
        the note (B5-12). The part goes into a copy of the fixture store, with its index and its manifest entry written again."""
        store = Path(tempfile.mkdtemp(prefix="hailwatch-partial-store-"))
        self.addCleanup(shutil.rmtree, store, True)
        shutil.copytree(hs.FIXTURE_DIR, store, dirs_exist_ok=True)
        index_path = store / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["joins"]["parts"]["stations"] = "partial"
        index["joins"]["partial"]["stations"] = ["00U 2024", "THM 2025"]
        index["joins"]["reasons"]["stations"] = "the gust files were not fetched"
        data = hs._pretty(index)
        index_path.write_bytes(data)
        manifest_path = store / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["hail/index.json"] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        manifest_path.write_bytes(hs._pretty(manifest))
        hs.check_manifest(store)
        out = Path(tempfile.mkdtemp(prefix="hailwatch-partial-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        h = json.loads(page(out, "data/map.json"))["hail"]
        self.assertEqual(h["joins"]["parts"]["stations"], "partial")
        self.assertEqual(h["joins"]["partial"]["stations"], ["00U 2024", "THM 2025"])
        for cell in FIVE_CELLS[:3]:                 # the cells the fixture holds
            with self.subTest(cell=cell):
                self.compare_cell(out, h, cell)
        browser = node_sheet(out, h, {"row": FIVE_CELLS[0][0], "col": FIVE_CELLS[0][1]})
        for key in ("gust_days", "gust_max"):
            last = browser["table"]["rows"][key]["notes"][-1]
            self.assertIn("did not load for 00U 2024, THM 2025 (the gust files were not fetched)", last)
            self.assertEqual(last.count("This is not an all-clear."), 1, last)
            self.assertTrue(last.endswith("This is not an all-clear."), last)
        wind = {sec["id"]: sec for sec in browser["model"]["sections"]}["wind"]
        self.assertEqual(sum(1 for n in wind["notes"] if "did not load for 00U 2024, THM 2025" in n), 1, wind["notes"])


def sm_sections() -> list[str]:
    """The eleven section ids in the brief's order (summary.WORDS_SUMMARY section_titles; Hail first, How this was made last)."""
    from website import summary as sm
    return list(sm.WORDS_SUMMARY["section_titles"])


class SummaryReadsReader(unittest.TestCase):
    """The every-key test reads the summary keys map.js uses (R1-F6): the reads of the S copy, of h.summary and hd.summary
    read directly, and through own(...), sdGet and sumWord (D83, D87(h)). A key read in any of these forms is seen, so a key
    the build does not write fails the every-key test whichever form the browser uses."""

    def test_each_form_map_js_uses_is_seen(self):
        js = (
            'var a = h.summary.seasons; var b = hd.summary.words; var c = own(h.summary, "tile_list");\n'
            'var d = S.partial; var e = sumWord(h.summary, "table_problem"); var f = S.rule.season_min;\n'
            'var g = own(S.indicators.words, "held"); var k = sdGet(S, "roof.reference_line");\n'
        )
        reads = summary_reads(js)
        for key in ("seasons", "words", "tile_list", "partial"):
            self.assertIn(key, reads["top"])
        self.assertIn("table_problem", reads["words"])
        self.assertIn("season_min", reads["rule"])
        self.assertIn("held", reads["indicators"])
        self.assertIn("roof.reference_line", reads["paths"])

    def test_a_key_the_block_lacks_is_reported_by_the_reader(self):
        self.assertIn("not_written_key", summary_reads('var x = h.summary.not_written_key;')["top"])


class SummaryContract(unittest.TestCase):
    """The summary block the browser reads: every key map.js reads is written by the build (round 3, F1, D83), the share
    rounding matches Python at every share the station rule can see (D82, D83(b)), and the sheet's joined code holds no
    literal fallback for the rows it shows first (D83(a))."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-contract-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        site.build(cls.out, None, datetime(2026, 10, 19, 12, 0, tzinfo=UTC), sample=True, hail_history=True)
        cls.h = json.loads(page(cls.out, "data/map.json"))["hail"]
        cls.js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")

    def test_every_summary_key_the_browser_reads_is_in_the_block(self):                                      # F1, D83
        d = self.h["summary"]
        reads = summary_reads(self.js)
        self.assertEqual(sorted(reads["words"] - set(d["words"])), [], "summary.words keys the build does not write")
        self.assertEqual(sorted(reads["rule"] - set(d["rule"])), [], "summary.rule keys the build does not write")
        self.assertEqual(sorted(reads["indicators"] - set(d["indicators"]["words"])), [], "summary.indicators.words keys")
        self.assertEqual(sorted(reads["top"] - set(d)), [], "summary keys the build does not write")
        sd = d["section_data"]
        for path in sorted(reads["paths"]):
            cur = sd
            for part in path.split("."):
                self.assertIsInstance(cur, dict, f"section_data.{path}")
                self.assertIn(part, cur, f"section_data.{path} is not written")
                cur = cur[part]
        self.assertEqual(len(sd["roof"]["lines"]), 23)
        for line in sd["roof"]["lines"].values():
            self.assertTrue(line["label"] and line["kind"] and "noun" in line)
            self.assertTrue(line["noun"] is None or line["noun"] in d["nouns"], line)

    def test_the_section_data_is_the_contract_the_browser_round_two_wrote(self):                             # F1, D83
        sd = self.h["summary"]["section_data"]
        self.assertEqual(sd["kind"], {"radar": "Radar estimate", "report": "Report", "record": "Record (NCEI)",
                                      "reference": "Reference", "unavailable": "Data unavailable"})
        self.assertEqual(sd["row_labels"], ["Report", "Record", "Detection", "Warning", "Watch", "Advisory", "Zone product",
                                            "County product", "Station"])
        self.assertEqual(sd["rules"]["by_label"], {"Station": "wind", "Detection": "hail"})
        self.assertEqual([r[0] for r in sd["rules"]["rules"]], ["ice", "heat", "flooding", "snow", "hail", "rain", "wind"])
        self.assertEqual(sd["rules"]["default"], "storms")
        self.assertEqual(sd["partial_marker"], "not counting")
        self.assertEqual(sd["words"]["span_to"], "to")
        self.assertEqual(sd["words"]["report_near"], "{count} within 5 miles{tail}")
        self.assertEqual(sd["words"]["county_word"], "County")
        self.assertEqual(sd["roof"]["partial_keys"], ["heat_advisory", "excessive_heat", "ice_storm", "winter_storm"])
        self.assertEqual(sd["roof"]["reference_line"], "{source}: “{quote}”")
        self.assertEqual(sd["section_keys"]["hail"], ["radar_max", "radar_1in", "hail_max", "hail_n"])
        self.assertEqual(sd["extra_notes"], {"snow": ["analysis_held"]})
        self.assertEqual(sd["season_rows"][0], {"section": "temperature", "kind": "Grid estimate", "keys": ["tmax", "tmin"],
                                                "names": ["highest", "lowest"]})
        self.assertEqual(sd["roof"]["lines"]["hail_size_days"]["noun"], "days")
        self.assertEqual(sd["roof"]["extra"]["hail_warnings"], {"polygon": ["SV"], "sig": "W", "noun": "sv"})
        self.assertEqual(sd["roof"]["extra"]["heat_advisory"]["sig"], ["Y"])
        self.assertEqual(sd["kind_what"]["Warning"], self.h["summary"]["indicators"]["words"]["what_warnings"])

    def test_the_rule_percent_is_the_three_values(self):                                                      # D82(c), D83(b)
        self.assertEqual(self.h["summary"]["rule"]["percent"], {"scale": 100, "decimals": 1, "step": 0.1})

    def test_the_day_noun_and_the_show_first_count_are_written(self):                                         # D83(a), D83(b)
        self.assertEqual(self.h["summary"]["nouns"]["days"], ["day", "days"])
        self.assertEqual(self.h["joins"]["show_first"], 10)
        self.assertEqual(self.h["summary"]["rule"]["season_min"], 0.95)
        self.assertEqual(self.h["summary"]["units"]["in"]["scale"], 100)

    def test_the_station_words_the_browser_reads_are_in_the_stations_block(self):                            # F8, D71
        words = set(re.findall(r"stWord\(\s*[\w.]+\s*,\s*\"([^\"]+)\"", self.js))
        self.assertEqual(sorted(words - set(self.h["stations"]["words"])), [])

    def test_the_browser_rounds_each_share_as_python_does_at_every_share(self):                              # D82, D83(b)
        from website import summary as sm
        rule = self.h["summary"]["rule"]
        shares = [round(k / 2192, 4) for k in range(0, 2193)]
        payload = {"code": "\n".join(js_function(self.js, name) for name in ("sumPercent", "sumRoundEven", "sumSharePct",
                                                                             "missingKey", "has", "own")),
                   "S": {"rule": {"cover_min": rule["cover_min"], "percent": rule["percent"]}}, "shares": shares}
        done = subprocess.run([shutil.which("node"), "-e", NODE_SHARE_SCRIPT], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        browser = json.loads(done.stdout)
        python = [sm._share_text(share) for share in shares]
        differing = [(k, python[k], browser[k]) for k in range(len(shares)) if python[k] != browser[k]]
        self.assertEqual(differing, [], differing[:5])
        for k, digits in SHARE_TIES.items():                          # the exact ties: 137, 685, 1233 and 1781 of 2,192
            with self.subTest(k=k):
                self.assertEqual(python[k], digits)
                self.assertEqual(browser[k], digits)

    def test_the_browser_season_rule_is_pythons_at_every_day_count_and_the_bounds(self):                    # D83(b), D87(d), F-09
        from website import summary as sm
        from website import stations
        rule = self.h["summary"]["rule"]
        first, last = date(2020, 6, 25), date(2027, 7, 5)
        days = [(first + timedelta(days=k)).isoformat() for k in range((last - first).days + 1)]
        labels = list(sm.FIVE) + [sm.PARTIAL]
        payload = {"code": "\n".join([js_var(self.js, "HAIL_DAY_MS")] + [js_function(self.js, name) for name in (
                       "own", "has", "sumPercent", "sumSeasonRule", "sumSeasonOf", "sumBounds", "sumDayNum", "sumIsoOf")]),
                   "S": {"rule": rule}, "totals": [365, 366], "labels": labels, "days": days}
        done = subprocess.run([shutil.which("node"), "-e", NODE_SEASON_SCRIPT], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        browser = json.loads(done.stdout)
        python_share = int(round(sm.SEASON_SHARE * 100))
        self.assertEqual(browser["share"], {"scale": 100, "share": python_share})
        python_full = [[total, valid, valid * 100 >= total * python_share] for total in (365, 366) for valid in range(367)]
        self.assertEqual(browser["full"], python_full, "the 95 percent rule at every day count 0 to 366")
        full = {(total, valid): ok for total, valid, ok in browser["full"]}
        for total, enough, short in ((365, 347, 346), (366, 348, 347)):        # D88(l): 346.75 and 347.7 days need 347 and 348
            with self.subTest(total=total):
                self.assertTrue(full[(total, enough)], f"{enough} of {total} days is a season shown")
                self.assertFalse(full[(total, short)], f"{short} of {total} days is not")
        self.assertEqual(rule["season"], sm.SEASON_RULE)                        # the block the browser reads is the module's rule
        self.assertEqual(sm.season_bounds("2023-24"), (date(2023, 7, 1), date(2024, 6, 30)))
        self.assertEqual((sm.season_bounds("2023-24")[1] - sm.season_bounds("2023-24")[0]).days + 1, 366)   # a leap season
        for label, start, end in browser["bounds"]:
            with self.subTest(label=label):
                self.assertEqual((start, end), tuple(d.isoformat() for d in sm.season_bounds(label)))
        differing = []
        for iso, label in browser["labels"]:
            want = stations.season_of(date.fromisoformat(iso))
            if want is not None and label != want:
                differing.append((iso, label, want))
        self.assertEqual(differing, [], differing[:5])

    def test_the_browser_reads_the_season_bounds_and_the_inch_scale_from_map_json(self):                    # D87(d), F-08, F-12
        season = js_function(self.js, "sumSeasonOf") + js_function(self.js, "sumBounds")
        for literal in ('"-07-01"', '"-06-30"', "m >= 7", "07-01", "06-30"):
            self.assertNotIn(literal, season, "the season bounds are map.json's (summary.rule.season), not literals")
        inches = js_function(self.js, "hailInches")
        self.assertNotIn("100", inches, "hailInches reads summary.units.in.scale from map.json, not the literal 100")
        self.assertIn("scale", inches)

    def test_each_joined_line_feeds_the_section_its_part_names(self):                                        # D82(d)
        from website import build as bd
        from website import joins as jn
        county = jn.WORDS_JOINS["county_lead_none"].format(county_name="Yellowstone", start="1 Jan 2021", end="31 Dec 2025")
        self.assertEqual(bd._line_part(county, "zones"), "county")
        self.assertEqual(bd._line_part(jn.WORDS_JOINS["county_unavailable"], "zones"), "county")
        self.assertEqual(bd._line_part(jn.WORDS_JOINS["zones_fire_none"], "zones"), "fire")
        self.assertEqual(bd._line_part(jn.WORDS_JOINS["zones_before_line_one"].format(n=1, zone_name="X", zone="MTZ001"), "zones"),
                         "zones")
        self.assertEqual(bd._line_part("The newest warning in this build starts on Sep 19, 2026.", "warnings"), "warnings")
        self.assertEqual(bd.JOIN_PART_SECTIONS["county"], "flooding")
        self.assertEqual(bd.JOIN_PART_SECTIONS["fire"], "storms")

    def test_the_sheet_code_holds_no_literal_fallback_for_the_rows_it_shows_first(self):                     # D83(a), (e)
        self.assertNotIn("|| 10", self.js)
        self.assertNotIn("showFirst: 10", self.js)

    def test_a_sheet_line_with_no_value_is_never_a_placeholder_on_the_fixture(self):                         # (d)
        browser = node_sheet(self.out, self.h, {"row": FIVE_CELLS[0][0], "col": FIVE_CELLS[0][1]})
        everything = browser["tableTexts"] + [t for texts_ in browser["sectionTexts"].values() for t in texts_]
        self.assertTrue(everything)
        self.assertEqual([t for t in everything if "[missing" in t], [])

    def test_the_billings_page_carries_each_joined_line_under_the_section_it_feeds(self):                     # D82(d)
        page_html = page(self.out, "town/billings.html")
        hail_sec = re.search(r'<section class="hist-sec[^"]*" id="sec-hail".*?</section>', page_html, re.S).group(0)
        storms = re.search(r'<section class="hist-sec[^"]*" id="sec-storms".*?</section>', page_html, re.S).group(0)
        flooding = re.search(r'<section class="hist-sec[^"]*" id="sec-flooding".*?</section>', page_html, re.S).group(0)
        wind = re.search(r'<section class="hist-sec[^"]*" id="sec-wind".*?</section>', page_html, re.S).group(0)
        text = {"hail": " ".join(html_text(hail_sec).split()), "storms": " ".join(html_text(storms).split()),
                "flooding": " ".join(html_text(flooding).split()), "wind": " ".join(html_text(wind).split())}
        self.assertIn("The newest detection in this build is from", text["hail"])          # the freshness line of detections
        self.assertIn("The newest warning in this build starts on", text["storms"])        # the freshness line of warnings
        self.assertIn("County products could not be loaded in this update", text["flooding"])   # the county line (its own part)
        self.assertNotIn("County products could not be loaded", text["storms"])

    def test_the_real_store_names_are_the_display_names_the_store_gives(self):                               # D78(c), round 3
        store = os.environ.get("HAIL_PARITY_STORE")
        if not store:
            self.skipTest("set HAIL_PARITY_STORE to the adopted combined store")
        folder = Path(tempfile.mkdtemp(prefix="hailwatch-names-"))
        self.addCleanup(shutil.rmtree, folder, True)
        site.build(folder, None, datetime(2026, 10, 19, 12, 0, tzinfo=UTC), sample=True, hail_history=True,
                   hail_store_path=store)
        h = json.loads(page(folder, "data/map.json"))["hail"]
        benchland = node_sheet(folder, h, {"row": 792, "col": 1998})
        snow = benchland["table"]["rows"]["snow"]
        text = " ".join(snow["texts"] + snow["notes"] + [t for texts_ in benchland["sectionTexts"].values() for t in texts_])
        self.assertIn("Buffalo 1.7 E", text)
        self.assertIn("Harlowton 11NW", text)
        for upper in ("BUFFALO", "HARLOWTON", "BILLINGS WTP"):
            self.assertNotIn(upper, text)
        billings = node_sheet(folder, h, {"row": 921, "col": 2149})
        text = " ".join(billings["table"]["rows"]["snow"]["texts"] + billings["table"]["rows"]["snow"]["notes"])
        self.assertIn("Billings WTP", text)
        self.assertNotIn("BILLINGS WTP", text)


# ---------------------------------------------------------------- the B6 base map's data files (D125(d); build.base_document)
# data/base.json (every word, credit, band, cell, held kind and budget the sheet and the toggled layers need) and map.json's
# first-paint pointer. The store below is invented: the fixture's hail files, and small files named as the B6 modules name
# them, with the module's own map functions reading them. Real figures are in the B6 build records, not here.

B6_TERRAIN = {
    "state": "loaded", "problem": None, "zooms": [5, 6, 7, 8, 9, 10], "tile_px": 256,
    "as_of": {"shading_date": "2026-09-28", "shading_month": "2026-09", "shading_copyright": "Test copyright line.",
              "land_cover": "2023-06"},
    "layers": {"h": {"state": "loaded", "path": "hail/base/h/{z}/{x}/{y}.jpg", "missing": [], "files": 1, "problem": None},
               "l": {"state": "loaded", "path": "hail/base/l/{z}/{x}/{y}.png", "missing": [], "files": 1, "problem": None}},
    "budget": {"zooms": "5 to 10", "bytes_limit": 20000000, "bytes": 1234, "under_budget": True},
    "bytes": 1234, "counts": {},
    "sources": {"shading": {"name": "test shading", "as_of": "2026-09-28"}, "land_cover": {"name": "test land cover", "as_of": "2023-06"}},
}
# every vector source the loaded store read (basemap2's keys); the credit lines of the About page follow these (T5, D134(b))
B6_VECTOR_READ = ("tiger_aiannh", "tiger_prisec", "tiger_place", "census_pl2020", "edw", "padus", "nhd_small_lines",
                  "nhd_small_areas", "nhd_large_lines", "nhd_large_areas", "gnis", "3dep")
B6_VECTOR = {
    "state": "loaded", "problem": None, "as_of": "2026-10-16",
    "budgets": {"A": {"limit": 150000, "gzip": 100, "ok": True},
                "B": {"limit": 100000, "gzip_largest": 10, "over_budget": 0, "files": 1},
                "C": {"limit": 60000, "gzip_largest": 10, "over_budget": 0, "files": 1},
                "D": {"limit": 30000, "gzip_largest": 10, "over_budget": 0, "shards": 1}},
    "coverage": {"tiles_listed": 1, "tiles_in_coverage": 1, "tiles_built": 1, "tiles_unbuilt": 0, "band_d_areas": 1,
                 "band_d_failed_cells": [], "band_d_cell_reasons": {}},
    "failures": [], "counts": {},
    # the vector part's rows as basemap2 writes them: file counts and bytes, no date (F12)
    "sources": {name: {"state": "cache", "files": 1, "fetched": 0, "cache": 1, "failed": 0, "bytes": 1, "reasons": []}
                for name in B6_VECTOR_READ},
}
B6_LANDMARKS = {
    "state": "loaded", "problem": None, "as_of": "2026-10-25",
    "kinds": {"school": {"code": "s", "state": "loaded", "held": False, "sources": ["nces_public", "nces_private"], "count": 2},
              "hospital": {"code": "h", "state": "loaded", "held": False, "sources": ["usgs_hospitals"], "count": 1},
              "fire": {"code": "f", "state": "loaded", "held": False, "sources": ["usgs_fire"], "count": 1},
              "park": {"code": "p", "state": "loaded", "held": False, "sources": ["padus_local", "tiger_park"], "count": 1},
              "airport": {"code": "a", "state": "loaded", "held": False, "sources": ["faa_nasr"], "count": 3},
              "church": {"code": "c", "state": "held", "held": True, "sources": ["fema_worship"], "count": None}},
    "counts": {"points": 8, "kinds": {"school": 2, "hospital": 1, "fire": 1, "park": 1, "airport": 3}}, "tiles": ["r0079_c0199"],
    "held": {"kinds": {"church": {"held": True, "state": "held", "count": None, "reason": "held for the test"}},
             "sources": {"fema_worship": {"held": True, "state": "held", "count": None, "reason": "held for the test"}}},
    "budget": {"shard_gzip_bytes": 20000, "largest_gzip_bytes": 90, "within": True},
    "sources": {"nces_public": {"kind": "school", "label": "test school list", "state": "loaded", "as_of": "2024-25 school year",
                                "kept": 1, "credit": "Source: National Center for Education Statistics, EDGE public school "
                                                     "locations, 2024-25 school year."},
                "usgs_hospitals": {"kind": "hospital", "label": "test hospital list", "state": "loaded", "as_of": "October 2026 refresh",
                                   "kept": 1, "credit": "Source: USGS The National Map, hospitals and medical centers, October 2026 "
                                                        "refresh."},
                "nces_private": {"kind": "school", "label": "test private school list", "state": "loaded",
                                 "as_of": "2023-24 school year", "kept": 1,
                                 "credit": "Source: National Center for Education Statistics, EDGE private school "
                                           "locations, 2023-24 school year."},
                "usgs_fire": {"kind": "fire", "label": "test fire and EMS list", "state": "loaded",
                              "as_of": "October 2026 refresh", "kept": 1,
                              "credit": "Source: USGS The National Map, fire and EMS stations, October 2026 refresh."},
                "faa_nasr": {"kind": "airport", "label": "test airport file", "state": "loaded", "as_of": "2026-10-01", "kept": 3,
                             "credit": "Source: Federal Aviation Administration, National Airspace System Resources airport data, "
                                       "cycle effective 2026-10-01."},
                "padus_local": {"kind": "park", "label": "test park list", "state": "loaded", "as_of": "2026-10-20", "kept": 1,
                                "credit": "Source: USGS Gap Analysis Project, Protected Areas Database of the United States "
                                          "(PAD-US) 4.1, local parks, layer last edited 2026-10-20."},
                "fema_worship": {"kind": "church", "state": "held", "held": True, "reason": "held for the test"}},
}
# B6 landmark indexes for the credit tests (F1, F2, F9, F10): a copy of the hospitals used (USGS answered with no Montana
# rows, so the copy was read), the FAA cycle with its date, and PAD-US with no date in its index
HIFLD_LANDMARKS = {
    "state": "loaded", "problem": None, "as_of": "2026-10-25",
    "kinds": {"hospital": {"code": "h", "state": "loaded", "held": False, "sources": ["hifld_hospitals"], "count": 2},
              "airport": {"code": "a", "state": "loaded", "held": False, "sources": ["faa_nasr"], "count": 3},
              "park": {"code": "p", "state": "loaded", "held": False, "sources": ["padus_local", "tiger_park"], "count": 4},
              "church": {"code": "c", "state": "held", "held": True, "sources": ["fema_worship"], "count": None}},
    "counts": {"points": 9, "kinds": {"hospital": 2, "airport": 3, "park": 4}}, "tiles": ["r0079_c0199"],
    "held": B6_LANDMARKS["held"],
    "budget": {"shard_gzip_bytes": 20000, "largest_gzip_bytes": 90, "within": True},
    "sources": {"usgs_hospitals": {"kind": "hospital", "label": "test hospital list", "state": "loaded", "as_of": None, "kept": 0,
                                   "credit": "Source: USGS The National Map, hospitals and medical centers, October 2026 refresh."},
                "hifld_hospitals": {"kind": "hospital", "label": "test state licensure copy", "state": "loaded", "as_of": "2026-10-20",
                                    "kept": 2, "credit": "Source: Hospital list copied from the state licensure list (copy by the "
                                                         "Homeland Infrastructure Foundation-Level Data), layer last edited 2026-10-20."},
                "faa_nasr": {"kind": "airport", "label": "test airport file", "state": "loaded", "as_of": "2026-10-01", "kept": 3,
                             "credit": "Source: Federal Aviation Administration, National Airspace System Resources airport data, "
                                       "cycle effective 2026-10-01."},
                "padus_local": {"kind": "park", "label": "test park list", "state": "loaded", "as_of": None, "kept": 4,
                                "credit": "Source: USGS Gap Analysis Project, Protected Areas Database of the United States "
                                          "(PAD-US) 4.1, local parks, Data unavailable."},
                "tiger_park": {"kind": "park", "state": "held", "held": True, "reason": "held for the test"},
                "fema_worship": {"kind": "church", "state": "held", "held": True, "reason": "held for the test"}},
}
# no hospital, airport or park source was read (each one failed): the page names none of them
NONE_LANDMARKS = {
    "state": "partial", "problem": "Data unavailable: some landmarks could not be loaded in this update. This is not an all-clear.",
    "as_of": "2026-10-25",
    "kinds": {"school": {"code": "s", "state": "loaded", "held": False, "sources": ["nces_public"], "count": 1},
              "hospital": {"code": "h", "state": "unavailable", "held": False, "sources": ["usgs_hospitals"], "count": None,
                           "reason": "the USGS layer could not be used (test)"},
              "airport": {"code": "a", "state": "unavailable", "held": False, "sources": ["faa_nasr"], "count": None,
                          "reason": "test"},
              "park": {"code": "p", "state": "unavailable", "held": False, "sources": ["padus_local", "tiger_park"], "count": None,
                       "reason": "test"},
              "church": {"code": "c", "state": "held", "held": True, "sources": ["fema_worship"], "count": None}},
    "counts": {"points": 1, "kinds": {"school": 1}}, "tiles": ["r0079_c0199"],
    "held": B6_LANDMARKS["held"],
    "budget": {"shard_gzip_bytes": 20000, "largest_gzip_bytes": 90, "within": True},
    "sources": {"nces_public": B6_LANDMARKS["sources"]["nces_public"],
                "usgs_hospitals": {"kind": "hospital", "label": "test hospital list", "state": "unavailable", "reason": "test"},
                "faa_nasr": {"kind": "airport", "label": "test airport file", "state": "unavailable", "reason": "test"},
                "padus_local": {"kind": "park", "label": "test park list", "state": "unavailable", "reason": "test"},
                "fema_worship": {"kind": "church", "state": "held", "held": True, "reason": "held for the test"}},
}
B6_HISTORY = {
    "state": "loaded", "problem": None, "as_of": "2026-10-16", "window": ["2021-10-17", "2026-10-16"],
    "built_at": "2026-10-19T12:00:00Z", "sidecar": {"file": "hail/history/index.json", "bytes": 1, "sha256": "0"},
    "pictures": {"hail1": {"state": "loaded"}, "heat90": {"state": "loaded"}},
    "zones": {"state": "loaded", "file": "hail/history/zones.json", "bytes": 1, "sha256": "0", "zones": 1,
              "newest_warning": "2026-10-10", "unavailable": None, "missing_zone_files": None},
    "outlines": {"state": "loaded", "file": "hail/base/v/zones.json", "bytes": 1, "sha256": "0", "zones": 1, "simplify_m": 150.0},
    "failures": [], "seconds": 0.1,
}
B6_RECENT = {
    "state": "loaded", "file": "hail/recent/cells.json", "bytes": 1, "sha256": "0", "as_of": "2026-10-16",
    "window": ["2026-09-17", "2026-10-16"], "cells": 0, "days": 0, "stale": None, "floor_tenths": 254,
    "words": {"title": hl.WORDS["recent_title"], "legend": hl.WORDS["recent_legend"].format(first="2026-09-17",
                                                                                              as_of="2026-10-16")},
}
B6_LABEL_RULE = {"zooms": [17, 18], "cluster_px": 55.75, "tol_px": 2.0, "dot_radius_px": 4.0, "tip_gap_px": 1.0,
                 "pointer_px": 5.0, "body_px": 22.0, "pad_px": 7.0, "letter_px": -0.26, "min_width_px": 30.0,
                 "font": "atkinson-hyperlegible-next-latin-700-normal.woff2", "order": "test order",
                 "placement": "test placement", "clusters": "test clusters",
                 "words": {"dash": "--", "unavailable": "Data unavailable", "legend": hl.WORDS["label_legend"]}}
B6_LABELS = {"state": "loaded", "problem": None, "as_of": "2026-10-16", "window": ["2021-10-17", "2026-10-16"],
             "built_at": "2026-10-19T12:00:00Z", "zooms": [17, 18], "rule": B6_LABEL_RULE, "tiles": "all",
             "counts": {"shards": 0}, "bytes_added": 0, "failures": [], "seconds": 0.1}


def b6_store(root: Path, *, base: bool = True, history: bool = True, terrain: dict | None = None,
             landmarks: dict | None = None, vector: dict | None = None, recent: dict | None = None,
             history_block: dict | None = None, labels: dict | None = None, pictures: dict | None = None) -> Path:
    """A hail/ folder for the B6 tests: the sample fixture, plus the base map, the five-year pictures, the zone counts, the
    recent cells and the labels as the modules name them. The manifest lists every file (hail.check_manifest)."""
    hail = root / "hail"
    shutil.copytree(hs.FIXTURE_DIR / "hail", hail)
    index = json.loads((hail / "index.json").read_text(encoding="utf-8"))

    def put(rel: str, data) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")

    if base:
        put("hail/base/index.json", {"f": "hail-base-index-v1", "terrain": terrain or B6_TERRAIN, "vector": vector or B6_VECTOR,
                                     "landmarks": landmarks or B6_LANDMARKS})
        put("hail/base/h/5/8/12.jpg", b"\xff\xd8 test tile")
        put("hail/base/l/5/8/12.png", b"\x89PNG test tile")
        put("hail/base/v/a.json", {"f": "hail-base-vector-v1", "features": []})
        put("hail/base/v/b/n46w114.json", {"f": "hail-base-vector-v1", "features": []})
        put("hail/base/v/c/n46w114.json", {"f": "hail-base-vector-v1", "features": []})
        put("hail/base/v/zones.json", {"f": "hail-zone-outlines-v1", "zones": [],
                                       "source": {"credit": hl.WORDS["about_outlines"]}})
        put("hail/base/w/r0079_c0199.json", {"f": "hail-base-water-v1", "features": []})
        put("hail/base/p/r0079_c0199.json", {"f": "hail-landmarks-v1", "t": "r0079_c0199", "n": 1,
                                             "i": [[-108.5, 45.8, "s", "Test School", "nces_public"]]})
        put("hail/base/peaks.json", {"f": "hail-base-peaks-v1", "peaks": []})
        put("hail/base/places.json", {"f": "hail-base-places-v1", "places": []})
    if history:
        put("hail/history/hail1.png", b"\x89PNG hail test")
        put("hail/history/heat90.png", b"\x89PNG heat test")
        sidecar_pictures = {
            "hail1": {"state": "loaded", "file": hl.HAIL1_PATH, "width": 2, "height": 2, "unit": "days",
                      "window": ["2021-10-17", "2026-10-16"], "classes": [dict(c, alpha=217) for c in hl.HAIL_CLASSES],
                      "words": {"title": hl.WORDS["hail1_title"],
                                "legend": hl.WORDS["hail1_legend"].format(first="2021-10-17", last="2026-10-16"),
                                "transparent": "A blank cell is "
                                                                                                 "not the same as no hail."}},
            "heat90": {"state": "loaded", "file": hl.HEAT_PATH, "width": 2, "height": 2, "unit": "days",
                       "window": ["2021-07-01", "2026-06-30"], "classes": [dict(c, alpha=209) for c in hl.HEAT_CLASSES],
                       "words": {"title": hl.WORDS["heat90_title"], "legend": hl.WORDS["heat90_legend"]}},
        }
        sidecar_pictures.update(pictures or {})          # D138(b) tests: a picture the copy lacks (its entry replaced whole)
        put(hl.SIDECAR_PATH, {"f": hl.FORMAT_PICTURES, "as_of": "2026-10-16", "window": ["2021-10-17", "2026-10-16"],
                              "bounds": [[43.0, -118.5], [50.5, -101.0]], "state": "loaded", "stale": None,
                              "missing_days": [], "pictures": sidecar_pictures, "words": hl.WORDS})
        put(hl.ZONES_PATH, {"f": hl.FORMAT_ZONES, "as_of": "2026-10-16", "window": ["2021-10-17", "2026-10-16"],
                            "newest_warning": {"date": "2026-10-10", "words": hl._newest_sentence("2026-10-10")},
                            "measures": [{"key": m["key"], "label": m["label"], "kind": m["kind"]} for m in hl.MEASURES],
                            "outline": {"file": hl.OUTLINE_PATH, "format": hl.FORMAT_OUTLINES}, "unavailable": None,
                            "missing_zone_files": None,
                            "words": {"title": hl.WORDS["zones_title"], "legend": "Test zone legend."}, "zones": {}})
        put(hl.RECENT_PATH, {"f": hl.FORMAT_RECENT, "as_of": "2026-10-16", "window": ["2026-09-17", "2026-10-16"],
                             "cells": 0, "days": 0, "stale": None, "rows": []})
        index[hl.INDEX_KEY] = history_block or B6_HISTORY
        index[hl.RECENT_KEY] = recent or B6_RECENT
        index[lb.INDEX_KEY] = labels or B6_LABELS
    put("hail/index.json", index)
    manifest = json.loads((hail / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"] = {}
    for path in sorted(hail.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            data = path.read_bytes()
            manifest["files"][path.relative_to(root).as_posix()] = {"bytes": len(data),
                                                                   "sha256": hashlib.sha256(data).hexdigest()}
    put("hail/manifest.json", manifest)
    hs.check_manifest(root)
    return root


class B6BaseMapData(unittest.TestCase):
    """The B6 base map's two data files (D125(d)): the default and the sample build write both with every block unavailable
    and its reason (the identity rule); a store with the B6 folders fills the blocks through the modules' own map functions,
    so the browser prints the modules' words; map.json keeps only the pointer and the first-paint states."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    BLOCKS = ("base", "history_layers", "recent", "labels")

    @classmethod
    def setUpClass(cls):
        cls.default = Path(tempfile.mkdtemp(prefix="hailwatch-b6-default-"))
        cls.addClassCleanup(shutil.rmtree, cls.default, True)
        site.build(cls.default, None, cls.NOW, sample=True)
        cls.sample_hail = Path(tempfile.mkdtemp(prefix="hailwatch-b6-hail-"))
        cls.addClassCleanup(shutil.rmtree, cls.sample_hail, True)
        site.build(cls.sample_hail, None, cls.NOW, sample=True, hail_history=True)     # the fixture store: no B6 parts
        cls.store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-store-"))
        cls.addClassCleanup(shutil.rmtree, cls.store, True)
        b6_store(cls.store)
        cls.loaded = Path(tempfile.mkdtemp(prefix="hailwatch-b6-loaded-"))
        cls.addClassCleanup(shutil.rmtree, cls.loaded, True)
        site.build(cls.loaded, None, cls.NOW, sample=True, hail_history=True, hail_store_path=str(cls.store))

    def data(self, out: Path, name: str = "data/base.json") -> dict:
        return json.loads(page(out, name))

    def test_the_copy_list_names_the_three_b6_folders(self):
        self.assertEqual(site.HAIL_FOLDERS_B6, ("base", "history", "recent"))

    def test_the_copy_takes_the_b6_folders_a_store_holds_and_a_store_without_them_still_copies(self):
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-copy-"))
        self.addCleanup(shutil.rmtree, out, True)
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        site._copy_hail(self.store, out / "with", index, addresses=False)
        for name in ("base", "history", "recent"):
            self.assertTrue((out / "with" / "hail" / name).is_dir(), name)
        self.assertTrue((out / "with" / "hail" / "base" / "index.json").is_file())
        hs.check_manifest(out / "with")
        fixture_index = json.loads((hs.FIXTURE_DIR / "hail" / "index.json").read_text(encoding="utf-8"))
        site._copy_hail(hs.FIXTURE_DIR, out / "without", fixture_index, addresses=False)     # no error: a stated absence
        for name in ("base", "history", "recent"):
            self.assertFalse((out / "without" / "hail" / name).exists(), name)
        hs.check_manifest(out / "without")

    def test_the_default_and_the_sample_builds_write_both_files_with_every_block_unavailable(self):
        for out in (self.default, self.sample_hail):
            m = self.data(out, "data/map.json")
            self.assertEqual(tuple(list(m)[-len(self.BLOCKS):]), self.BLOCKS)
            b = self.data(out)
            self.assertEqual(sorted(b), ["as_of", "base", "budget", "built", "history_layers", "labels", "recent", "sheet", "version"])
            for key in self.BLOCKS:
                self.assertEqual(b[key]["state"], "unavailable", key)
                self.assertTrue(b[key]["problem"].startswith("Data unavailable"), key)
                self.assertTrue(b[key]["problem"].endswith("This is not an all-clear."), key)
                self.assertEqual(m[key]["state"], "unavailable", key)
        default = self.data(self.default)
        self.assertEqual({default[key]["reason"] for key in self.BLOCKS}, {site.REASON_NO_STORE})
        sample = self.data(self.sample_hail)
        self.assertEqual(sample["base"]["reason"], site.REASON_NO_BASE)            # the fixture store has no base folder
        self.assertEqual(sample["history_layers"]["reason"], site.REASON_NO_HISTORY)
        self.assertEqual(sample["recent"]["reason"], site.REASON_NO_RECENT)
        self.assertEqual(sample["labels"]["reason"], site.REASON_NO_LABELS)

    def test_map_json_carries_the_pointer_and_the_first_paint_states_only(self):
        m = self.data(self.default, "data/map.json")
        self.assertEqual(m["base"], {"state": "unavailable", "as_of": None, "file": "data/base.json", "zooms": [5, 10],
                                     "tiles": {"h": "hail/base/h/{z}/{x}/{y}.jpg", "l": "hail/base/l/{z}/{x}/{y}.png"}})
        for key in ("history_layers", "recent", "labels"):
            self.assertEqual(m[key], {"state": "unavailable"}, key)
        self.assertEqual(site.BASE_TILES, {"h": "hail/base/h/{z}/{x}/{y}.jpg", "l": "hail/base/l/{z}/{x}/{y}.png"})

    def test_data_base_json_has_the_keys_and_the_same_build_time_as_map_json(self):
        for out in (self.default, self.loaded):
            m, b = self.data(out, "data/map.json"), self.data(out)
            self.assertEqual(b["built"], m["built"])
            self.assertEqual(b["version"], 1)
            self.assertEqual(sorted(b["base"]), sorted(["as_of", "cells", "credit", "held", "landmarks", "problem", "reason",
                                                        "sources", "state", "terrain", "tiles", "vector", "zooms"]))
            self.assertEqual(sorted(b["budget"]), ["bands", "base_tiles", "landmark_shard"])
            self.assertEqual(b["sheet"], site.SHEET_WORDS)
            self.assertEqual(m["base"]["as_of"], b["as_of"])
            for key in self.BLOCKS[1:]:
                self.assertEqual(m[key]["state"], b[key]["state"], key)

    def test_a_loaded_store_fills_the_base_map_through_the_module_functions(self):
        base = self.data(self.loaded)["base"]
        self.assertEqual(base["state"], "loaded")
        self.assertIsNone(base["reason"])
        self.assertIsNone(base["problem"])
        self.assertEqual(base["cells"], {"B": ["n46w114"], "C": ["n46w114"], "D": ["r0079_c0199"]})
        self.assertEqual(base["terrain"]["layers"]["h"]["template"], site.BASE_TILES["h"])        # the pointer's template
        self.assertEqual(base["terrain"]["layers"]["l"]["template"], site.BASE_TILES["l"])
        self.assertEqual(base["terrain"]["words"]["unavailable"], tr.WORDS["unavailable"])
        self.assertEqual(base["terrain"]["credits"]["land_cover"], tr.WORDS["land_source"])
        self.assertEqual(base["terrain"]["credits"]["shading"], tr.WORDS["shading_source"].format(date="2026-09-28"))
        self.assertEqual(base["vector"]["words"], b2.WORDS)
        self.assertEqual(base["vector"]["part_words"]["water"], list(b2.PART_WORDS["water"]))
        self.assertEqual(base["vector"]["tiles"]["w"], "hail/base/w/{tile}.json")
        self.assertEqual(base["vector"]["zooms"]["D"], [13, 18])
        for line in (b2.CREDIT[0], b2.CREDIT[1], b2.CREDIT[2], b2.CREDIT[3], b2.CREDIT[4], b2.CREDIT[5], b2.CREDIT[6]):   # T5
            self.assertIn(line, base["credit"])                 # every vector source this store read, PAD-US outlines included
        self.assertEqual(base["landmarks"]["templates"]["what"], lm.WORDS["what"])
        self.assertEqual(base["landmarks"]["shard"], "hail/base/p/{name}.json")
        self.assertEqual(base["landmarks"]["tiles"], ["r0079_c0199"])
        # the credit lines of the shown landmark sources, in the module's order, with the date words built here (F2)
        self.assertEqual(base["landmarks"]["sources"], [
            lm.SOURCES["nces_public"]["credit"],
            lm.SOURCES["nces_private"]["credit"],
            lm.SOURCES["usgs_hospitals"]["credit"],
            lm.SOURCES["usgs_fire"]["credit"],
            site.landmark_line("faa_nasr", "2026-10-01"),                # the airports, read with the cycle date (F2)
            "Source: USGS Gap Analysis Project, Protected Areas Database of the United States (PAD-US) 4.1, local parks, "
            "layer last edited 2026-10-20."])
        self.assertEqual(base["as_of"]["vector"], "2026-10-16")
        self.assertEqual(base["as_of"]["landmarks"], "2026-10-25")
        # the date of each source: the as_of its row carries, and Data unavailable where it carries none (F12); a fetch time or a
        # file count is never a date
        self.assertEqual(base["sources"]["terrain"]["shading"], {"as_of": "2026-09-28"})     # the name stays in the module's block
        self.assertEqual(base["sources"]["vector"]["tiger_aiannh"], {"state": "cache", "as_of": site.NO_DATE})
        self.assertEqual(base["sources"]["landmarks"]["nces_public"], {"state": "loaded", "as_of": "2024-25 school year"})
        self.assertEqual(base["sources"]["landmarks"]["padus_local"], {"state": "loaded", "as_of": "2026-10-20"})
        self.assertEqual(base["sources"]["landmarks"]["fema_worship"], {"state": "held", "as_of": site.NO_DATE})
        # the hospital source the store used (F1, D130(b)): USGS, with its own line and no other; the FAA line, with its cycle date
        self.assertEqual(base["landmarks"]["hospital"], {"state": "loaded", "source": "usgs_hospitals",
                                                         "sentence": lm.WORDS["hospital_usgs"],
                                                         "credit": lm.SOURCES["usgs_hospitals"]["credit"]})
        self.assertEqual(base["landmarks"]["credits"], {
            "faa_nasr": site.landmark_line("faa_nasr", "2026-10-01"),
            "padus": "Source: USGS Gap Analysis Project, Protected Areas Database of the United States (PAD-US) 4.1, local parks, "
                     "layer last edited 2026-10-20."})

    def test_held_kinds_and_sources_show_their_reason_and_no_count(self):
        base = self.data(self.loaded)["base"]
        self.assertEqual(base["landmarks"]["kinds"]["church"]["state"], "held")
        self.assertTrue(base["landmarks"]["kinds"]["church"]["held"])
        self.assertEqual(base["held"]["kinds"]["church"], {"held": True, "state": "held", "count": None,
                                                           "reason": "held for the test"})
        self.assertEqual(base["held"]["sources"]["fema_worship"]["reason"], "held for the test")
        self.assertIsNone(base["held"]["sources"]["fema_worship"]["count"])
        self.assertNotIn("church", base["landmarks"]["counts"]["kinds"])     # a held kind has no count in the words either

    def test_the_history_layers_recent_cells_and_labels_come_from_the_store_and_the_modules_words(self):
        b = self.data(self.loaded)
        history = b["history_layers"]
        self.assertEqual(history["state"], "loaded")
        self.assertEqual(history["pictures"]["hail1"]["classes"][0]["word"], "1 day")
        self.assertEqual(history["pictures"]["hail1"]["bounds"], [[43.0, -118.5], [50.5, -101.0]])
        self.assertEqual(history["pictures"]["heat90"]["words"]["title"], hl.WORDS["heat90_title"])
        self.assertEqual([m["key"] for m in history["zones"]["measures"]], [m["key"] for m in hl.MEASURES])
        self.assertEqual(len(history["zones"]["measures"]), 8)                       # the eight zone measures (D112(i))
        self.assertEqual(history["zones"]["newest_warning"], {"date": "2026-10-10",
                                                              "words": "The newest warning in these counts is dated Oct 10, 2026."})
        self.assertEqual(history["outlines"]["credit"], hl.WORDS["about_outlines"])
        self.assertEqual(history["outlines"]["url"], "hail/base/v/zones.json")
        recent = b["recent"]
        self.assertEqual((recent["state"], recent["window"], recent["stale"]), ("loaded", ["2026-09-17", "2026-10-16"], None))
        self.assertEqual(recent["url"], "hail/recent/cells.json")
        self.assertEqual(recent["words"]["title"], hl.WORDS["recent_title"])
        labels = b["labels"]
        self.assertEqual(labels["state"], "loaded")
        self.assertEqual(labels["words"], {"dash": "--", "unavailable": "Data unavailable", "legend": hl.WORDS["label_legend"],
                                           "what": hl.WORDS["label_what"]})                  # D141(d): what a bubble is
        self.assertEqual(labels["words"]["legend"], hl.WORDS["label_legend"])       # D135(a): one bubble legend, one text
        self.assertNotIn("words", labels["rule"])
        self.assertEqual(labels["rule"]["cluster_px"], 55.75)
        self.assertEqual(labels["budget"], {"shard_gzip": site.LABEL_SHARD_GZIP, "shard_raw_split": bd.SHARD_BYTES})

    def test_the_budgets_carry_the_base_tiles_bytes_and_the_band_budgets(self):
        budget = self.data(self.loaded)["budget"]
        self.assertEqual(budget["base_tiles"], {"zooms": "5 to 10", "bytes": 1234, "limit_bytes": 20000000, "under_budget": True})
        self.assertEqual(budget["bands"], B6_VECTOR["budgets"])
        self.assertEqual(budget["landmark_shard"], {"limit_gzip": 20000, "largest_gzip": 90})

    def test_the_sheet_words_are_the_d110_sub_lines_the_switch_name_and_the_b6_lines(self):
        self.assertEqual(site.SHEET_WORDS["points_of_interest"], "Landmark dots and names, for the kinds chosen above")     # D110(a)
        self.assertEqual(site.SHEET_WORDS["five_year_history"], "Past records from the last five years. Not a forecast.")   # D110(b)
        self.assertEqual(site.SHEET_WORDS["highlight_recent_hail"], "Highlight recent radar hail")                          # D110(g)
        # F3: the water line for an area with no band D shard, imported from the vector module (not retyped here)
        self.assertIs(site.SHEET_WORDS["water_line_unavailable"], b2.WORDS["water_line_unavailable"])
        # F3 (DESIGN section 13.6, item 5): the Landmarks sub-line the sheet shows under its heading
        self.assertEqual(site.SHEET_WORDS["landmarks_sub_line"],
                         "Schools, parks, hospitals, airports, and fire and EMS stations, from the public lists named under About.")
        # B6 stage S1 (DESIGN 13.6): every word the options sheet shows, and nothing else (tests/test_site.py OptionsSheet)
        self.assertEqual(sorted(site.SHEET_WORDS), sorted(["airport", "base_failed", "base_heading", "church", "close_label", "coming", "coming_fire", "coming_smoke", "fire_ems", "fire_smoke", "five_year_history", "flood_history", "hail_history", "hail_last_day", "hail_last_hour", "heat_history", "held", "held_church", "highlight_recent_hail", "history_heading", "hospital", "imagery_card", "landmark_line", "landmarks_heading", "landmarks_sub_line", "legend_hail_last_day", "legend_hail_last_hour", "legend_imagery", "legend_precipitation", "legend_recent", "legend_reports", "legend_temperature", "legend_wind", "list_and", "list_comma", "list_last", "live_heading", "map_card", "name_airport", "name_fire_ems", "name_hospital", "name_park", "name_school", "options_title", "park", "points_of_interest", "points_of_interest_name", "precipitation", "recent_description", "reset", "reset_line", "school", "storm_reports", "storm_reports_description", "temperature", "unavailable", "waiting", "warnings", "warnings_description", "water_line_unavailable", "wind_gusts", "wind_history", "partial_history"]))
        self.assertEqual(self.data(self.loaded)["sheet"], site.SHEET_WORDS)
        self.assertEqual(site.BUBBLE_LEGEND, hl.WORDS["label_legend"])              # D135(a): the printed legend is the module's text

    def test_the_sheet_water_line_is_the_vector_modules_words_imported(self):                      # F3: imported, not retyped
        self.assertIs(site.SHEET_WORDS["water_line_unavailable"], b2.WORDS["water_line_unavailable"])

    def test_the_sheet_water_line_carries_the_d122b_words_in_the_vector_module(self):              # F3, D122(b): the exact words
        # The words the decision and the F3 item name. basemap2.WORDS must hold them; this test fails until it does.
        self.assertEqual(site.SHEET_WORDS["water_line_unavailable"],
                         "Detailed water and local parks: Data unavailable for this area in this update. This is not an all-clear.")

    def test_the_imagery_credit_row_in_map_json_carries_the_privacy_words(self):
        imagery = self.data(self.default, "data/map.json")["imagery"]
        self.assertEqual(imagery["credit_line"], "Imagery: USDA, USGS, The National Map. Your IP address and the map area you "
                                                 "view go to USGS while it is on.")

    def test_map_json_stays_under_the_raw_gate_with_the_loaded_store(self):
        size = map_json_bytes(self.loaded)
        self.assertLess(size, HISTORY_MAP_GATE, size)                                  # D82(a): the whole file

    def test_every_string_of_data_base_json_and_the_b6_keys_of_map_json_pass_the_words_gate(self):      # F11, AGENTS.md rule 5
        # Every string VALUE of data/base.json is scanned, and the values under data/map.json's B6 keys. The old scan read the raw
        # file text, where words_rules sets every straight-quoted string aside, so it could never fail; keys are field names,
        # not text a reader sees.
        for out in (self.default, self.loaded):
            base = self.data(out)
            m = self.data(out, "data/map.json")
            self.assertEqual(b6_words_hits(base), [], f"data/base.json ({out.name})")
            self.assertEqual(b6_words_hits({key: m[key] for key in self.BLOCKS}), [], f"data/map.json B6 keys ({out.name})")
        church = self.data(self.loaded)["base"]["held"]["kinds"]["church"]
        self.assertIsNone(church["count"])

    def test_the_words_gate_fails_on_a_planted_forbidden_word_and_on_a_planted_em_dash(self):     # F11: a mutant of the data
        mutant = json.loads(json.dumps(self.data(self.loaded)))
        mutant["base"]["landmarks"]["templates"]["what"] += " A roof at risk."
        mutant["sheet"]["points_of_interest"] += " " + chr(0x2014) + " kept"
        hits = b6_words_hits(mutant)
        self.assertEqual([path for path, _, _ in hits], ["$.base.landmarks.templates.what", "$.sheet.points_of_interest"])
        self.assertEqual(hits[0][1], ["risk"])
        self.assertEqual(hits[1][1], [])                                                          # the em dash is the hit there
        clean = self.data(self.loaded)
        self.assertEqual(b6_words_hits(clean), [])                                                # the mutant is the only change

    def test_a_part_that_cannot_be_read_fails_alone(self):
        store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-bad-"))
        self.addCleanup(shutil.rmtree, store, True)
        b6_store(store, terrain=dict(B6_TERRAIN, zooms=None))            # the terrain block cannot be read
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-bad-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        base = self.data(out)["base"]
        self.assertEqual(base["terrain"]["state"], "unavailable")
        self.assertIn("the terrain files could not be read", base["terrain"]["reason"])
        self.assertEqual(base["vector"]["state"], "loaded")
        self.assertEqual(base["landmarks"]["state"], "loaded")
        self.assertEqual(base["state"], "partial")
        self.assertEqual(self.data(out)["history_layers"]["state"], "loaded")


def json_strings(node, path: str = "$"):
    """Every string VALUE of a parsed JSON document, with its path (F11). Keys are field names, not text a reader sees."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from json_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from json_strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def b6_words_hits(doc) -> list:
    """(path, forbidden words, text) for each string of a B6 document that holds a forbidden word (words_rules) or an em dash
    (AGENTS.md rule 5). An empty list is a pass."""
    hits = []
    for path, text in json_strings(doc):
        found = words_rules.forbidden_words(text)
        if found or chr(0x2014) in text:
            hits.append((path, found, text))
    return hits


def html_text(fragment: str) -> str:
    """The visible text of an HTML fragment: its tags removed and its entities read."""
    import html as html_lib
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))


class B6AboutAndSources(unittest.TestCase):
    """The B6 feeds (sources.py rows: the base map, the landmark points, the five-year pictures, the zone counts and the recent
    radar hail, B6_CONTRACTS) and the About page's B6 sentences under the hail history heading: each source's sentence with its
    credit line in the "Source: ..." form (D121(a)), the newest-warning words from the counted rows (D125(a)), the held kinds with
    the modules' own reasons and no figure of a held source (D118(b)), and the words gate (AGENTS.md rule 5)."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    # one credit line per source, as the About page carries it in a loaded build (the modules' lines, the Source form)
    CREDITS = (
        "Source: 3DEP data courtesy of the U.S. Geological Survey (data as of 2026-09-28).",
        "Source: National Land Cover Database 2021 data courtesy of the U.S. Geological Survey and the Multi-Resolution Land Characteristics "
        "Consortium (public domain).",
        "Source: U.S. Census Bureau, TIGER/Line 2026 (reservations, roads and place names).",
        "Source: U.S. Census Bureau, 2020 Census, Public Law 94-171 counts (place populations).",
        "Source: USDA Forest Service, forest boundaries (national forests).",
        # the two PAD-US lines, one per section (D141(k)): basemap2's under the park outlines, and the landmarks' under the park
        # points, with the layer's own date (F2, F10)
        b2.CREDIT[3],
        "Source: USGS Gap Analysis Project, Protected Areas Database of the United States (PAD-US) 4.1, local parks, layer last "
        "edited 2026-10-20.",
        "Source: U.S. Geological Survey, National Hydrography Dataset (lakes and rivers).",
        "Source: U.S. Geological Survey, Geographic Names Information System (summit names).",
        "3DEP data courtesy of the U.S. Geological Survey (summit heights).",
        "Source: National Center for Education Statistics, EDGE public school locations, 2024-25 school year.",
        "Source: National Center for Education Statistics, EDGE private school locations, 2023-24 school year.",
        "Source: USGS The National Map, hospitals and medical centers, October 2026 refresh.",
        "Source: USGS The National Map, fire and EMS stations, October 2026 refresh.",
        "Source: NOAA MRMS MESH radar estimates, NOAA Open Data on AWS.",
        "Source: NOAA nClimGrid-Daily grid estimates (file attribute \"license = no restrictions\"; attribution requested).",
        "Source: National Weather Service warnings, through the Iowa Environmental Mesonet archive.",
        "Source: Iowa State University, Iowa Environmental Mesonet, ugcs service. The outlines are simplified.",
    )

    @classmethod
    def setUpClass(cls):
        cls.default = Path(tempfile.mkdtemp(prefix="hailwatch-b6-about-default-"))
        cls.addClassCleanup(shutil.rmtree, cls.default, True)
        site.build(cls.default, None, cls.NOW, sample=True)
        cls.bare = Path(tempfile.mkdtemp(prefix="hailwatch-b6-about-bare-"))
        cls.addClassCleanup(shutil.rmtree, cls.bare, True)
        site.build(cls.bare, None, cls.NOW, sample=True, hail_history=True)        # no B6 parts in the store
        cls.store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-about-store-"))
        cls.addClassCleanup(shutil.rmtree, cls.store, True)
        b6_store(cls.store)
        cls.loaded = Path(tempfile.mkdtemp(prefix="hailwatch-b6-about-loaded-"))
        cls.addClassCleanup(shutil.rmtree, cls.loaded, True)
        site.build(cls.loaded, None, cls.NOW, sample=True, hail_history=True, hail_store_path=str(cls.store))

    @staticmethod
    def b6_block(out: Path) -> str:
        """The B6 sentences of the About page as a reader sees them: from the Base map heading to the Five years heading."""
        text = page(out, "about.html")
        start, end = text.index("<h3>Base map</h3>"), text.index("<h2>Five years of weather</h2>")
        return " ".join(html_text(text[start:end]).split())

    def test_the_b6_rows_are_one_group_in_sources_order_before_the_b5_rows(self):
        keys = list(src.CONTRACTS)
        self.assertEqual(len(site.B6_CONTRACTS), 23)
        self.assertEqual(len(set(site.B6_CONTRACTS)), 23)
        start = keys.index("terrain_shading")
        self.assertEqual(keys[start:start + len(site.B6_CONTRACTS)], list(site.B6_CONTRACTS))
        self.assertLess(keys.index("bubble_anchors"), keys.index("nclimgrid_daily"))     # the B5 order test keeps B5 last
        for key in site.B6_CONTRACTS:
            self.assertIn(key, site.HAIL_CONTRACTS, key)                                 # on the About page in a hail build only
            self.assertNotIn(key, site.STORM_CONTRACTS, key)
            row = src.CONTRACTS[key]
            self.assertEqual(set(row), {"name", "request", "units", "timing", "missing"}, key)
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in row.values()), key)

    def test_the_b6_rows_carry_the_corrected_words(self):
        rows = src.CONTRACTS
        self.assertIn("2.9 by 1.9 miles (4.6 by 3 km)", rows["history_pictures"]["units"])                       # D141(b7): the cells
        self.assertNotIn("1/24 degree cells", rows["history_pictures"]["units"])
        self.assertNotIn("4.6 km", rows["history_pictures"]["units"])
        self.assertIn("Source: 3DEP data courtesy of the U.S. Geological Survey.", rows["terrain_shading"]["missing"])  # D112(c)
        self.assertIn("Source: National Land Cover Database 2021 data courtesy of the U.S. Geological Survey and the Multi-Resolution Land "
                      "Characteristics Consortium (public domain).", rows["terrain_land_cover"]["missing"])
        self.assertNotIn("CC0", " ".join(rows["terrain_land_cover"].values()))                                         # D124
        self.assertIn("USDA Forest Service", rows["base_forests"]["name"])                                            # D114(b)
        self.assertNotIn("counsel item 23", rows["base_forests"]["missing"])                                          # D141(f)
        self.assertIn("and counsel reads the terms.", rows["base_forests"]["missing"])
        self.assertIn("17 U.S.C. 105", rows["base_forests"]["missing"])
        self.assertIn("iem_watchwarn", rows["history_zone_counts"]["request"])                                        # D113(d)
        self.assertNotRegex(" ".join(" ".join(rows[k].values()) for k in site.B6_CONTRACTS), r"\blag\b")
        self.assertIn("valid=2026-10-25T00:00Z", rows["iem_ugcs"]["request"])

    def test_the_held_rows_name_the_hold_and_publish_no_count(self):
        for key in ("tiger_park", "fema_worship"):                                                                    # D118(b)
            row = src.CONTRACTS[key]
            self.assertIn("not shown yet", row["name"], key)                                                        # D141(b): plain words
            self.assertNotRegex(" ".join(row.values()), r"\d[\d,]*\s+(?:rows|features|points|places|churches|parks|schools|records)\b",
                                key)
        self.assertIn("No count of its rows is published", src.CONTRACTS["fema_worship"]["request"])

    def test_no_b6_row_has_an_em_dash_or_a_forbidden_word(self):
        for key in site.B6_CONTRACTS:
            text = " ".join(src.CONTRACTS[key].values())
            self.assertNotIn(chr(0x2014), text, key)
            # addresses and file names are names, not claims: the scan reads the words around them
            words_rules.assert_clean(self, re.sub(r"\S*/\S*|\S*\.(?:gov|com|zip|json|txt|geojson)\S*", " ", text), key)

    def test_the_default_build_has_no_b6_sentence(self):
        about = page(self.default, "about.html")
        for words in ("<h3>Base map</h3>", "Highlight recent radar hail", "Source: 3DEP", "NOAA nClimGrid-Daily",
                      "<h3>Zone counts</h3>", "Source: FEMA copy"):
            self.assertNotIn(words, about, words)

    def test_the_b6_block_sits_under_the_hail_history_heading(self):
        text = page(self.loaded, "about.html")
        self.assertLess(text.index("<h2>Hail history</h2>"), text.index("<h3>Base map</h3>"))
        self.assertLess(text.index("<h3>Value bubbles</h3>"), text.index("<h2>Five years of weather</h2>"))
        self.assertNotIn("Relief: ", self.b6_block(self.loaded))            # the labelled legend lines are not the About form
        self.assertNotIn("Land cover: ", self.b6_block(self.loaded))

    def test_the_hail_history_about_page_gives_each_source_its_credit_line(self):
        block = self.b6_block(self.loaded)
        for line in self.CREDITS:
            self.assertIn(line, block, line)

    def test_the_loaded_page_prints_no_unavailable_sentence_and_the_held_sentences_as_landmarks_words_them(self):     # D136(a)
        block = self.b6_block(self.loaded)
        for words in ("could not be loaded in this update", "could not be built in this update"):
            self.assertNotIn(words, block, words)                            # every source was read: no module sentence prints
        ctx = site.about_b6_context(json.loads(page(self.loaded, "data/base.json")))
        for key in [key for key in ctx if key.endswith("unavailable")]:
            self.assertIsNone(ctx[key], key)
        self.assertEqual((ctx["held_church"], ctx["held_park"]), (lm.CHURCH_HELD, lm.WORDS["held_parks"]))
        self.assertIn(lm.CHURCH_HELD, block)                                 # the two held lines are the module's sentences, whole
        self.assertIn(lm.WORDS["held_parks"], block)

    def test_each_held_sentence_is_its_own_paragraph_with_nothing_composed_around_it(self):     # U1 (D136(a))
        paragraphs = [" ".join(html_text(body).split())
                      for body in re.findall(r"<p>(.*?)</p>", page(self.loaded, "about.html"), re.S)]
        self.assertIn(lm.CHURCH_HELD, paragraphs)          # the church line: the module's one sentence, as its own paragraph
        self.assertIn(lm.WORDS["held_parks"], paragraphs)  # the park line: the module's two sentences, as their own paragraph

    def test_the_held_sentences_print_the_fixed_words_exactly_and_no_old_words(self):     # D141(b), B9
        church = ("Places of worship are not shown yet: the use terms of the list they come from are still being read, so no "
                  "church is drawn or named.")
        parks = "The Census park points and their names are not shown yet: the file's use terms are still being read."
        self.assertEqual((lm.CHURCH_HELD, lm.WORDS["held_parks"]), (church, parks))           # the modules' own sentences
        block = self.b6_block(self.loaded)
        self.assertIn(church, block)
        self.assertIn(parks, block)
        self.assertNotIn("Places of worship are held and not shown", block)
        self.assertNotIn("held for counsel", block)
        self.assertNotIn("The file's use constraints are for counsel to read", block)

    def test_the_held_kinds_carry_the_modules_words_and_no_figure(self):
        block = self.b6_block(self.loaded)
        self.assertIn(lm.CHURCH_HELD, block)                                 # D118(b), D141(b): the church's one sentence
        self.assertIn(lm.WORDS["held_parks"], block)
        self.assertIn("so no church is drawn or named.", block)              # the church sentence's own last clause
        self.assertNotRegex(block, r"\d[\d,]*\s+(?:places of worship|churches|church|parks held)\b")

    def test_the_zone_counts_carry_the_newest_warning_words_from_the_counted_rows(self):
        block = self.b6_block(self.loaded)
        base = json.loads(page(self.loaded, "data/base.json"))
        newest = base["history_layers"]["zones"]["newest_warning"]
        self.assertEqual(newest["date"], "2026-10-10")                       # D125(a): the counted rows, not the joins lag
        self.assertIn(newest["words"], block)
        self.assertIn("The newest warning in these counts is dated Oct 10, 2026.", block)
        self.assertNotRegex(block, r"\blag\b")

    def test_the_zone_and_picture_windows_come_from_the_store_not_from_fixed_words(self):
        block = self.b6_block(self.loaded)
        self.assertIn("from October 17, 2021 to October 16, 2026", block)            # the store's window, in the About form
        self.assertIn("Days at or above 90 F are counted over July 1, 2021 to June 30, 2026", block)
        self.assertNotIn("the five seasons in the store", block)
        bare = self.b6_block(self.bare)
        # F7 (rule 5): with no heat picture the count sentence says Data unavailable, and reads as no count over the seasons
        self.assertIn(hl.WORDS["missing"].format(what="The five-year history layers"), bare)     # D138(b): the layer's own sentence
        self.assertNotIn("counted over", bare)
        self.assertNotIn("the five seasons in the store", bare)

    def test_the_five_year_pictures_print_the_index_legend_the_module_sentences_and_the_window(self):     # D141(b4), (b7)
        block = self.b6_block(self.loaded)
        base = json.loads(page(self.loaded, "data/base.json"))
        legend = base["history_layers"]["pictures"]["hail1"]["words"]["legend"]
        self.assertEqual(legend, hl.WORDS["hail1_legend"].format(first="2021-10-17", last="2026-10-16"))   # the index's own words
        self.assertIn(legend, block)                                            # the hail picture's legend, from the index words
        self.assertIn("counted per 1 km cell over five years, from October 17, 2021 to October 16, 2026.", block)   # the module's window
        self.assertNotIn("over five seasons", block)                            # five years, not July to June seasons
        blank = "Data unavailable. A blank cell has no grid value. This is not an all-clear."
        self.assertIn(blank, block)                                             # the 90 F legend's closing sentence, as the module words it
        self.assertTrue(hl.WORDS["heat90_legend"].endswith(blank), "the module's own sentence")
        self.assertNotIn("and a blank cell has no grid value", block)
        zero = "A zero means the archive files read hold no such product for the zone. This is not an all-clear."
        self.assertIn(zero, block)                                              # the zone counts' zero sentence
        self.assertTrue(hl.WORDS["zones_legend"].endswith(zero), "the module's own sentence")
        self.assertIn("grid cells about 2.9 by 1.9 miles (4.6 by 3 km)", block)  # D141(b7): the heat grid cell words
        self.assertNotIn("1/24 degree cells", block)

    def test_a_missing_radar_day_is_named_in_the_hail_legend_the_about_page_prints(self):     # D141(b4)
        legend = " ".join([hl.WORDS["hail1_legend"].format(first="2021-10-17", last="2026-10-16"),
                           hl.WORDS["missing_one"].format(day="2024-05-03")])
        store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-missing-day-store-"))
        self.addCleanup(shutil.rmtree, store, True)
        picture = {"state": "loaded", "file": hl.HAIL1_PATH, "width": 2, "height": 2, "unit": "days",
                   "window": ["2021-10-17", "2026-10-16"], "classes": [dict(c, alpha=217) for c in hl.HAIL_CLASSES],
                   "words": {"title": hl.WORDS["hail1_title"], "legend": legend,
                             "transparent": "A blank cell is not the same as no hail."}}
        b6_store(store, pictures={"hail1": picture})
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-missing-day-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        block = self.b6_block(out)
        self.assertIn(legend, block)                                            # the legend, with the missing-day sentence, from the index
        self.assertIn(hl.WORDS["missing_one"].format(day="2024-05-03"), block)

    def test_the_summit_place_and_route_paragraphs_print_the_basemap_notes_and_no_figure(self):     # D141(h)
        block = self.b6_block(self.loaded)
        summit = "A summit height is the 3D Elevation Program's value at the summit's position, in metres and feet."
        self.assertEqual(block.count(summit), 1)                                # once: the summit note opens with that sentence
        self.assertIn(b2.WORDS["peak_note"], block)
        self.assertIn("It can differ from a published height.", block)
        self.assertNotIn("by tens of metres", block)                            # a figure with no check behind it
        self.assertNotIn("and a summit with no value is not shown", block)
        self.assertIn(b2.WORDS["place_note"], block)
        self.assertLess(block.index(b2.CREDIT[1]), block.index(b2.WORDS["place_note"]))     # the place note follows its credit
        self.assertIn(b2.WORDS["route_note"], block)
        self.assertLess(block.index(b2.CREDIT[0]), block.index(b2.WORDS["route_note"]))     # the route note follows the TIGER credit

    def test_the_forest_row_drops_the_internal_reference_and_keeps_the_terms_and_the_statute(self):     # D141(f)
        about = " ".join(html_text(page(self.loaded, "about.html")).split())
        self.assertNotIn("counsel item 23", about)                              # the internal item number is not published
        self.assertIn("and counsel reads the terms.", about)                    # the terms sentence stays
        self.assertIn("(public domain, 17 U.S.C. 105)", about)                  # the statute mention stays

    def test_the_terms_lead_the_water_line_and_the_cell_words_are_the_fixed_sentences(self):     # D141(j)
        self.assertEqual(site.TERMS_LEAD, "Each line below quotes the source's own words where the build read them, and says so "
                                          "where it did not.")
        self.assertEqual(site.WATER_AROUND, "Where an area's detailed water did not load, the statewide lakes and rivers still show, "
                                            "and the map's information sheet says:")
        about = " ".join(html_text(page(self.loaded, "about.html")).split())
        self.assertIn(site.TERMS_LEAD, about)                                   # the Terms section's lead-in
        self.assertNotIn("Each sentence below is the source's own words", about)
        block = self.b6_block(self.loaded)
        self.assertIn(site.WATER_AROUND + ' "' + b2.WORDS["water_line_unavailable"] + '"', block)   # then the D122(b) line, in quotes

    def test_the_zone_counts_name_the_eight_measures_and_say_what_they_use_in_plain_words(self):     # F5, D141(c)
        block = self.b6_block(self.loaded)
        self.assertIn("Counts of " + site.ZONES_WHAT + " by public forecast zone come from the NWS zone products and warning areas",
                      block)
        self.assertIn("A warning area counts in a zone when it touches the zone.", block)
        self.assertIn("The counts use the rows the build counted from the zone and warning-area files.", block)
        self.assertIn("The zone outlines are the zone outline file of 2026-10-25 from the Iowa State archive, which gives the 83 "
                      "public zone outlines only.", block)
        for words in ("counted rows from the store's zone and polygon files", "ugcs snapshot", "polygon", "valid="):
            self.assertNotIn(words, block, words)
        terms = " ".join(text for item in site.about_terms() for text in item["terms"])
        self.assertIn("the 83 zone outlines are the Iowa State copy, simplified, within 0.014 degrees of the NWS file.", terms)
        self.assertNotIn("keep the NWS outlines", terms)

    def test_the_recent_radar_hail_list_and_the_bubble_legend_are_data_statements(self):
        block = self.b6_block(self.loaded)
        self.assertEqual(site.SHEET_WORDS["highlight_recent_hail"], "Highlight recent radar hail")     # D110(g): the sheet's name
        self.assertIn("Recent radar hail", block)                                                     # the heading
        self.assertIn("The recent radar hail list holds the cells with a radar estimate of 1 inch or more", block)   # F4
        self.assertIn(hl.WORDS["label_legend"], block)                                                  # D110(c), D138(a): one legend
        self.assertIn("grid cells about 2.9 by 1.9 miles (4.6 by 3 km)", block)                        # D141(b7): the cell words
        self.assertNotIn("4.6 km across", block)

    def test_the_value_bubbles_print_the_one_legend_text_once_and_it_is_the_module_words(self):     # V2 (D138(a))
        about = " ".join(html_text(page(self.loaded, "about.html")).split())
        self.assertEqual(site.BUBBLE_LEGEND, hl.WORDS["label_legend"])          # D135(a): build.py's copy is the module's text
        self.assertEqual(about.count(hl.WORDS["label_legend"]), 1)              # the page carries the legend once
        self.assertNotIn("A dash (--) means", about)                            # the page's own dash sentence is gone
        self.assertNotIn("That is not zero.", about)
        base = json.loads(page(self.loaded, "data/base.json"))
        self.assertEqual(base["labels"]["words"]["legend"], hl.WORDS["label_legend"])                    # the map's copy too

    def test_the_value_bubbles_say_what_a_bubble_is_before_the_legend(self):                         # D141(d)
        block = self.b6_block(self.loaded)
        self.assertIn(hl.WORDS["label_what"], block)
        self.assertLess(block.index(hl.WORDS["label_what"]), block.index(hl.WORDS["label_legend"]))
        self.assertNotIn("The bubble values on the building outlines are the largest radar estimate", block)
        base = json.loads(page(self.loaded, "data/base.json"))
        self.assertEqual(base["labels"]["words"]["what"], hl.WORDS["label_what"])                      # the labels words block carries it

    def test_the_value_bubble_paragraph_prints_the_labels_problem_after_its_first_sentence(self):     # V2 (D138(a))
        problem = hl.WORDS["unavailable"].format(what="The bubble values on the building outlines",
                                                 reason="the test shards are not in the store")
        store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-labels-store-"))
        self.addCleanup(shutil.rmtree, store, True)
        b6_store(store, labels=dict(B6_LABELS, state="unavailable", problem=problem))     # a synthetic index: the labels block failed
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-labels-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        block = self.b6_block(out)
        first = block.index(hl.WORDS["label_what"])                             # D141(d): what a bubble is leads the paragraph
        self.assertLess(first, block.index(problem))                            # the problem sentence follows it
        self.assertLess(block.index(problem), block.index(hl.WORDS["label_legend"]))
        self.assertEqual(block.count(hl.WORDS["label_legend"]), 1)
        self.assertNotIn("A dash (--) means", block)

    def test_a_partial_bubble_layer_prints_the_labels_sentence_and_no_template_words(self):     # D141(d)
        store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-partial-store-"))
        self.addCleanup(shutil.rmtree, store, True)
        b6_store(store, labels=dict(B6_LABELS, state="partial", problem=lb.LABELS_PARTIAL))     # the labels block's own sentence
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-partial-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        block = self.b6_block(out)
        self.assertLess(block.index(hl.WORDS["label_what"]), block.index(lb.LABELS_PARTIAL))     # what a bubble is, then the partial sentence
        self.assertLess(block.index(lb.LABELS_PARTIAL), block.index(hl.WORDS["label_legend"]))
        self.assertEqual(block.count(lb.LABELS_PARTIAL), 1)
        # the partial sentence is the module's: no copy of it or of its wording sits in the template or in build.py
        for path in (ROOT / "website" / "templates" / "about.html", ROOT / "website" / "build.py"):
            self.assertNotIn("Bubble values were built", path.read_text(encoding="utf-8"), path.name)

    BUILD_REASON_LITERALS = ("the store holds no five-year pictures", "the picture file is not in the store",
                             "the zone files are not in the store", "the store holds no recent radar hail")
    COPY_REASONS = ("the store has no five-year picture files", "the store has no recent radar hail files",
                    "the store has no bubble values")

    def test_a_store_copy_without_the_problem_sentence_prints_the_module_sentence_and_never_a_build_reason(self):   # V3 (D138(b))
        build_text = (ROOT / "website" / "build.py").read_text(encoding="utf-8")
        for literal in self.BUILD_REASON_LITERALS:
            self.assertNotIn(literal, build_text, literal)                       # the four fallbacks' literals are gone from build.py
        bare = self.b6_block(self.bare)                                          # the copy's index lacks the five-year, recent and labels blocks
        self.assertIn(hl.WORDS["missing"].format(what="The five-year history layers"), bare)
        self.assertIn(hl.WORDS["missing"].format(what="The recent radar hail list"), bare)
        self.assertIn(hl.WORDS["missing"].format(what="The bubble values on the building outlines"), bare)
        for words in self.BUILD_REASON_LITERALS + self.COPY_REASONS:
            self.assertNotIn(words, bare, words)
        # a copy whose index holds each block but no problem sentence for its missing parts
        store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-missing-store-"))
        self.addCleanup(shutil.rmtree, store, True)
        b6_store(store, history_block=dict(B6_HISTORY, state="partial", problem=None, zones={"state": "unavailable"}),
                 pictures={"hail1": {"state": "unavailable"}}, recent={"state": "unavailable"},
                 labels={"state": "unavailable"})
        out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-missing-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        partial = self.b6_block(out)
        for part in ("The five-year hail picture", "The zone counts", "The recent radar hail list",
                     "The bubble values on the building outlines"):
            self.assertIn(hl.WORDS["missing"].format(what=part), partial, part)
        for words in self.BUILD_REASON_LITERALS + self.COPY_REASONS:
            self.assertNotIn(words, partial, words)

    def test_a_90_f_count_is_not_counted_over_when_its_picture_did_not_load(self):     # V4 (D138(c))
        real = site.base_document
        problem = hl.WORDS["unavailable"].format(what="The days at or above 90 F picture", reason="the grid file could not be read")

        def heat_unavailable(out, store_index, store_problem, now):
            doc = real(out, store_index, store_problem, now)
            # the fixture: the 90 F picture's state is unavailable, and the block still holds its window
            doc["history_layers"]["pictures"]["heat90"].update(state="unavailable", problem=problem)
            return doc

        out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-heat-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        with mock.patch.object(site, "base_document", side_effect=heat_unavailable):
            site.build(out, None, self.NOW, sample=True, hail_history=True, hail_store_path=str(self.store))
        block = self.b6_block(out)
        self.assertIn(problem, block)                                            # the unavailable sentence
        self.assertNotIn("counted over", block)
        self.assertNotIn("has no grid value", block)
        ctx = site.about_b6_context(json.loads(page(out, "data/base.json")))
        self.assertIsNone(ctx["heat_window"])                                    # gated on the read state, not the window alone
        self.assertEqual(ctx["heat90_unavailable"], problem)

    def test_the_b6_block_names_no_browser_behaviour_the_page_does_not_draw_yet(self):     # F4 (D132(a)): the B6-3 pass brings it back
        block = self.b6_block(self.loaded)
        for words in ("dark mode", "overlap", "tapped", "clicked", "fades", "zooms 11 and 12", "switch", "Highlight", "tap "):
            self.assertNotIn(words, block, words)

    def test_an_unloaded_base_map_says_data_unavailable_and_credits_nothing_it_does_not_use(self):
        block = self.b6_block(self.bare)
        self.assertIn("Terrain shading is a picture of the land for zooms 5 to 10. Data unavailable. Terrain shading could not be "
                      "loaded in this update; that is not the same as no terrain shading. This is not an all-clear.", block)
        self.assertIn("Data unavailable: airports could not be loaded in this update", block)     # the FAA paragraph's kind sentence
        self.assertNotIn("Source: 3DEP", block)
        self.assertNotIn("The newest warning in these counts is dated", block)
        self.assertIn(hl.WORDS["missing"].format(what="The five-year history layers"), block)     # D138(b): the part's name, no reason
        # F1, F2, F10: no source was read, so no credit line for one (the hospital, FAA or PAD-US source)
        self.assertNotIn("Protected Areas Database", block)
        self.assertNotIn("Federal Aviation Administration", block)
        self.assertNotIn("Source: USGS The National Map, hospitals", block)
        self.assertIn("Data unavailable: hospitals could not be loaded in this update", block)
        ctx = site.about_b6_context(json.loads(page(self.bare, "data/base.json")))
        self.assertIsNone(ctx["relief"])
        self.assertIsNone(ctx["land_cover"])
        self.assertIsNone(ctx["newest"])
        self.assertIsNone(ctx["faa_credit"])
        self.assertIsNone(ctx["padus_credit"])
        self.assertIsNone(ctx["hospital_credit"])
        self.assertTrue(ctx["zones_unavailable"].startswith("Data unavailable."))

    def test_the_water_fallback_says_both_ways_and_the_map_has_no_3d_view(self):
        block = self.b6_block(self.loaded)
        self.assertIn("the statewide lakes and rivers still show", block)        # D122(b), D141(j): both true statements
        self.assertIn(b2.WORDS["water_line_unavailable"], block)                  # T10: the module's words, quoted on the page
        self.assertIn("The map has no 3D view.", block)                           # D106(b), D107(c)
        self.assertIn("counts once for each part", block)                         # D125(b): the rows, as the legend says

    def test_the_b6_about_words_pass_the_words_gate_and_carry_no_em_dash(self):
        for out in (self.loaded, self.bare):
            block = self.b6_block(out)
            words_rules.assert_clean(self, block, out.name)
            self.assertNotIn(chr(0x2014), block, out.name)

    def test_the_usgs_hospital_line_is_printed_when_the_usgs_layer_is_the_source_used(self):       # F1, the USGS case
        block = self.b6_block(self.loaded)
        self.assertIn("Hospitals come from the USGS list of hospitals and medical centers.", block)
        self.assertIn(lm.SOURCES["usgs_hospitals"]["credit"], block)
        self.assertNotIn("Hospital list copied", block)                                # the copy was not read

    def test_the_zone_outline_line_is_the_history_words_and_its_sentence_is_the_module_words(self):                 # U3
        ctx = site.about_b6_context(json.loads(page(self.loaded, "data/base.json")))
        self.assertEqual(ctx["ugcs"], hl.WORDS["about_outlines"])            # the credit words come from history_layers, via build.py
        self.assertIsNone(ctx["ugcs_unavailable"])
        self.assertIn(hl.WORDS["about_outlines"], self.b6_block(self.loaded))
        bare = site.about_b6_context(json.loads(page(self.bare, "data/base.json")))
        self.assertIsNone(bare["ugcs"])
        self.assertEqual(bare["ugcs_unavailable"], hl.WORDS["outline_unavailable"])     # no outlines read: the module's sentence
        self.assertIn(hl.WORDS["outline_unavailable"], self.b6_block(self.bare))

    def test_the_park_names_paragraph_says_the_census_points_are_not_shown_yet(self):             # F6, F9, D141(b)
        about = page(self.loaded, "about.html")
        self.assertNotIn("Some park names come from a second public list", about)
        self.assertIn(lm.WORDS["held_parks"], self.b6_block(self.loaded))     # the module's sentence, as it is (D136(a))
        self.assertIn("The Census park points and their names are not shown yet: the file's use terms are still being read.",
                      self.b6_block(self.loaded))
        self.assertNotIn("held for counsel", self.b6_block(self.loaded))
        self.assertNotIn("Source: U.S. Census Bureau, TIGER/Line 2026 area landmarks.", about)

    def test_the_held_sources_are_named_as_held_with_their_reason_and_no_source_line(self):        # F9 (D118(b))
        block = self.b6_block(self.loaded)
        self.assertNotIn("Source: FEMA copy", page(self.loaded, "about.html"))
        self.assertIn("Places of worship are not shown yet: the use terms of the list they come from are still being read, "
                      "so no church is drawn or named.", block)                 # D141(b): the module's sentence, as it is
        self.assertNotIn("Places of worship are held and not shown", block)

    def test_the_nclimgrid_sentence_quotes_the_file_attribute_and_asks_for_attribution(self):      # F8
        block = self.b6_block(self.loaded)
        sentence = re.search(r"Source: NOAA nClimGrid-Daily grid estimates \(([^)]*)\)\.", block)
        self.assertIsNotNone(sentence)
        self.assertEqual(sentence.group(1), 'file attribute "license = no restrictions"; attribution requested')
        self.assertIn("Data unavailable. A blank cell has no grid value. This is not an all-clear. Source: NOAA nClimGrid-Daily grid estimates",
                      block)                                                    # D141(i): the module's sentence, then the credit
        self.assertNotIn("NOAA declares", block)

    def test_each_section_prints_its_own_pad_us_line_and_the_base_map_prints_basemap2s(self):      # F10, D141(k)
        text = page(self.loaded, "about.html")
        base_map = " ".join(html_text(text[text.index("<h3>Base map</h3>"):text.index("<h3>Landmarks</h3>")]).split())
        landmarks = " ".join(html_text(text[text.index("<h3>Landmarks</h3>"):text.index("<h3>Five-year pictures</h3>")]).split())
        local = ("Source: USGS Gap Analysis Project, Protected Areas Database of the United States (PAD-US) 4.1, local parks, layer "
                 "last edited 2026-10-20.")
        self.assertIn(b2.CREDIT[3], base_map)                                   # basemap2's PAD-US line, under the park outlines
        self.assertNotIn(local, base_map)                                       # not the landmarks' local-parks line
        self.assertIn(local, landmarks)                                         # the landmarks' line, in the park paragraph
        self.assertNotIn(b2.CREDIT[3], landmarks)
        self.assertEqual(self.b6_block(self.loaded).count("Protected Areas Database of the United States (PAD-US) 4.1"), 2)


class B6CreditsFollowTheStore(unittest.TestCase):
    """T5 (D134(b)): every B6 credit line prints only for a source the store read, from the index. In this synthetic store one
    terrain layer (land cover), one vector source (the forest boundaries, edw), one landmark source (the fire and EMS list,
    usgs_fire) and the recent cells failed, and the place population file is not listed at all. Each failed or unlisted
    source's line does not print, the part's own sentence stands, and every other line prints as before."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    LAND = "Source: National Land Cover Database 2021"
    FOREST = "Source: USDA Forest Service, forest boundaries (national forests)."
    FIRE = "Source: USGS The National Map, fire and EMS stations, October 2026 refresh."
    PL = "Source: U.S. Census Bureau, 2020 Census, Public Law 94-171 counts (place populations)."
    MRMS = "Source: NOAA MRMS MESH radar estimates, NOAA Open Data on AWS."

    @classmethod
    def setUpClass(cls):
        terrain = json.loads(json.dumps(B6_TERRAIN))
        terrain["state"] = "partial"
        terrain["layers"]["l"] = {"state": "unavailable", "path": "hail/base/l/{z}/{x}/{y}.png", "missing": [], "files": 0,
                                  "problem": "test: the land cover layer failed"}
        vector = json.loads(json.dumps(B6_VECTOR))
        vector["sources"]["edw"] = {"state": "failed", "files": 1, "fetched": 0, "cache": 0, "failed": 1, "bytes": 0,
                                    "reasons": ["test: the forest service failed"]}
        del vector["sources"]["census_pl2020"]                                     # not listed: the place counts were not read
        landmarks = json.loads(json.dumps(B6_LANDMARKS))
        landmarks["kinds"]["fire"] = {"code": "f", "state": "unavailable", "held": False, "sources": ["usgs_fire"],
                                      "count": None, "reason": "test"}
        landmarks["sources"]["usgs_fire"] = {"kind": "fire", "label": "test fire and EMS list", "state": "failed", "reason": "test"}
        # the recent cells failed, and the index records the reason for that part in its failures (D136(a))
        recent = dict(B6_RECENT, state="unavailable", problem=hl.WORDS["unavailable"].format(
            what="The recent radar hail list", reason="the recent cells test failed"))
        history = dict(B6_HISTORY, failures=[{"part": "recent", "reason": "the recent cells test failed"}])
        cls.store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-credits-store-"))
        cls.addClassCleanup(shutil.rmtree, cls.store, True)
        b6_store(cls.store, terrain=terrain, landmarks=landmarks, vector=vector, recent=recent, history_block=history)
        cls.out = Path(tempfile.mkdtemp(prefix="hailwatch-b6-credits-"))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        site.build(cls.out, None, cls.NOW, sample=True, hail_history=True, hail_store_path=str(cls.store))

    def block(self) -> str:
        text = page(self.out, "about.html")
        start, end = text.index("<h3>Base map</h3>"), text.index("<h2>Five years of weather</h2>")
        return " ".join(html_text(text[start:end]).split())

    def test_a_failed_or_unlisted_source_prints_no_credit_line_and_its_part_keeps_its_sentence(self):
        block = self.block()
        for line in (self.LAND, self.FOREST, self.FIRE, self.PL):
            self.assertNotIn(line, block, line)
        # each part that did not load keeps the module's own sentence, with its part name and the reason the index recorded
        self.assertIn("It covers zooms 5 to 10. " + tr.WORDS["part_unavailable"].format(**tr.LAYER_WORDS["l"]), block)   # land cover
        self.assertIn(b2.WORDS["part_unavailable"].format(Part=b2.PART_WORDS["forest"][0], one=b2.PART_WORDS["forest"][1]), block)
        self.assertIn(b2.WORDS["part_unavailable"].format(Part=b2.PART_WORDS["place"][0], one=b2.PART_WORDS["place"][1]), block)
        self.assertIn(lm.WORDS["kind_unavailable"].format(plural=lm.KIND_PLURAL["fire"]), block)
        self.assertIn(hl.WORDS["unavailable"].format(what="The recent radar hail list", reason="the recent cells test failed"), block)
        self.assertIn("Fire and EMS stations are points from the USGS list of fire and EMS stations.", block)        # its description
        self.assertEqual(block.count(self.MRMS), 1)              # the five-year pictures' line; the recent cells' line is gone

    def test_every_other_line_prints_for_the_source_it_names(self):
        block = self.block()
        for line in ("Source: 3DEP data courtesy of the U.S. Geological Survey (data as of 2026-09-28).",
                     b2.CREDIT[0], b2.CREDIT[4], b2.CREDIT[5], b2.CREDIT[6],
                     lm.SOURCES["nces_public"]["credit"], lm.SOURCES["nces_private"]["credit"],
                     lm.SOURCES["usgs_hospitals"]["credit"],
                     "Source: National Weather Service warnings, through the Iowa Environmental Mesonet archive."):
            self.assertIn(line, block, line)

    def test_the_data_file_and_the_about_context_name_only_the_sources_read(self):
        data = json.loads(page(self.out, "data/base.json"))
        base = data["base"]
        self.assertFalse(any(line.startswith("Land cover: ") for line in base["credit"]), base["credit"])
        self.assertNotIn(lm.SOURCES["usgs_fire"]["credit"], base["credit"])
        self.assertEqual(base["vector"]["credit"], [b2.CREDIT[0], b2.CREDIT[3], b2.CREDIT[4], b2.CREDIT[5], b2.CREDIT[6]])
        ctx = site.about_b6_context(data)
        self.assertIsNone(ctx["land_cover"])
        self.assertEqual(ctx["land_cover_unavailable"], tr.WORDS["part_unavailable"].format(**tr.LAYER_WORDS["l"]))
        self.assertIsNone(ctx["relief_unavailable"])
        self.assertEqual(ctx["forests_unavailable"],
                         b2.WORDS["part_unavailable"].format(Part=b2.PART_WORDS["forest"][0], one=b2.PART_WORDS["forest"][1]))
        self.assertTrue(ctx["relief"].startswith("Source: 3DEP"), ctx["relief"])
        self.assertIsNone(ctx["forests"])
        self.assertIsNone(ctx["places_2020"])
        self.assertIsNone(ctx["fire_ems"])
        self.assertEqual(ctx["tiger"], b2.CREDIT[0])
        self.assertTrue(ctx["mrms_pictures"])
        self.assertFalse(ctx["mrms_recent"])
        self.assertTrue(ctx["iem_warnings"])
        self.assertTrue(ctx["nclimgrid"])
        self.assertEqual(ctx["ugcs"], hl.WORDS["about_outlines"])
        data["history_layers"]["pictures"]["heat90"]["state"] = "unavailable"        # the picture failed: no nClimGrid line
        data["history_layers"]["outlines"]["state"] = "failed"                       # the outlines failed: no ugcs line
        ctx = site.about_b6_context(data)
        self.assertFalse(ctx["nclimgrid"])
        self.assertIsNone(ctx["ugcs"])
        self.assertEqual(ctx["ugcs_unavailable"], hl.WORDS["outline_unavailable"])
        self.assertEqual(ctx["water_line"], site.SHEET_WORDS["water_line_unavailable"])

    def test_the_read_rule_names_a_line_for_a_read_source_and_none_for_the_rest(self):                  # T5 (unit)
        rows = {"tiger_place": {"state": "partial"}, "edw": {"state": "failed"}, "3dep": {"state": "cache"},
                "nhd_large_areas": {"state": "fetched"}, "census_pl2020": {"state": "unknown"}}
        self.assertEqual(site.read_vector_lines(rows), [b2.CREDIT[0], b2.CREDIT[4], b2.CREDIT[6]])
        self.assertEqual(site.read_vector_lines(None), [])
        terrain = {"layers": {"h": {"state": "loaded"}, "l": {"state": "unavailable"}},
                   "credits": {"shading": "Relief: test shading", "land_cover": "Land cover: test land cover"}}
        self.assertEqual(site.terrain_line(terrain, "h"), "Relief: test shading")
        self.assertIsNone(site.terrain_line(terrain, "l"))
        self.assertIsNone(site.terrain_line({"layers": {"h": {"state": "loaded"}}, "credits": {"shading": "Data unavailable"}}, "h"))


class B6LandmarkCredits(unittest.TestCase):
    """F1, F2, F9, F10 (D130(b)): the About page prints the credit line of the hospital source the store used and no other line
    for a source that was not read; the FAA and PAD-US lines print only when their source was read, each with its own date or
    Data unavailable (never 'date not recorded'); a held source has no source line; and the page has one PAD-US line. Two
    synthetic stores: a state licensure copy used (the USGS layer answered with no Montana rows), and a store where no hospital,
    airport or park source was read."""

    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    USGS_LINE = lm.SOURCES["usgs_hospitals"]["credit"]
    COPY_LINE = ("Source: Hospital list copied from the state licensure list (copy by the Homeland Infrastructure "
                 "Foundation-Level Data), layer last edited 2026-10-20.")
    FAA_LINE = ("Source: Federal Aviation Administration, National Airspace System Resources airport data, cycle effective "
                "2026-10-01.")
    PAD_LINE = ("Source: USGS Gap Analysis Project, Protected Areas Database of the United States (PAD-US) 4.1, local parks, "
                "Data unavailable.")

    @classmethod
    def setUpClass(cls):
        cls.copy = Path(tempfile.mkdtemp(prefix="hailwatch-b6-copy-about-"))
        cls.addClassCleanup(shutil.rmtree, cls.copy, True)
        store = Path(tempfile.mkdtemp(prefix="hailwatch-b6-copy-store-"))
        cls.addClassCleanup(shutil.rmtree, store, True)
        b6_store(store, landmarks=HIFLD_LANDMARKS)
        site.build(cls.copy, None, cls.NOW, sample=True, hail_history=True, hail_store_path=str(store))
        cls.none = Path(tempfile.mkdtemp(prefix="hailwatch-b6-none-about-"))
        cls.addClassCleanup(shutil.rmtree, cls.none, True)
        empty = Path(tempfile.mkdtemp(prefix="hailwatch-b6-none-store-"))
        cls.addClassCleanup(shutil.rmtree, empty, True)
        vector = json.loads(json.dumps(B6_VECTOR))                                 # the PAD-US outlines failed too: neither source
        vector["sources"]["padus"] = {"state": "failed", "files": 1, "fetched": 0, "cache": 0, "failed": 1, "bytes": 0,
                                      "reasons": ["test: the protected areas service failed"]}
        b6_store(empty, landmarks=NONE_LANDMARKS, vector=vector)
        site.build(cls.none, None, cls.NOW, sample=True, hail_history=True, hail_store_path=str(empty))

    def test_the_copy_line_is_the_hospital_source_the_store_used_and_no_usgs_line_is_printed(self):      # F1
        block = B6AboutAndSources.b6_block(self.copy)
        self.assertIn(self.COPY_LINE, block)
        self.assertIn("Hospitals come from a copy of the state licensure list, because the USGS list named no Montana hospital "
                      "in this update.", block)
        self.assertNotIn(self.USGS_LINE, block)                                  # the USGS layer answered, with no Montana row
        self.assertNotIn("If that list names no Montana hospital", block)       # D141(g): the template's sentence is dropped
        self.assertIn(lm.WORDS["hospital_hifld"], block)                        # the copy's own sentence prints by itself

    def test_both_school_paragraphs_print_the_kind_sentence_when_the_store_lists_no_school_kind(self):             # D136(a)
        block = B6AboutAndSources.b6_block(self.copy)                             # this store has no school kind
        self.assertEqual(block.count(lm.WORDS["kind_unavailable"].format(plural=lm.KIND_PLURAL["school"])), 2)

    def test_no_hospital_line_when_no_hospital_source_was_read(self):                                    # F1
        block = B6AboutAndSources.b6_block(self.none)
        self.assertIn("Data unavailable: hospitals could not be loaded in this update; that is not the same as no hospitals.", block)
        self.assertNotIn(self.USGS_LINE, block)
        self.assertNotIn(self.COPY_LINE, block)
        self.assertNotIn("If that list names no Montana hospital", block)       # D141(g): no copy read, no template sentence

    def test_the_faa_line_takes_the_cycle_date_and_the_pad_us_line_says_data_unavailable_for_a_missing_date(self):     # F2
        block = B6AboutAndSources.b6_block(self.copy)
        self.assertIn(self.FAA_LINE, block)
        self.assertIn(self.PAD_LINE, block)                                      # the index's layer has no as_of

    def test_no_faa_or_pad_us_line_when_neither_source_was_read(self):                                   # F1's rule, for each line
        block = B6AboutAndSources.b6_block(self.none)                            # the B6 sentences (the table names the layers too)
        self.assertNotIn("Federal Aviation Administration", block)
        self.assertNotIn("Protected Areas Database of the United States", block)
        self.assertIn("Only public-use airports that are operational are shown. Heliports are not shown.", block)
        self.assertIn(lm.WORDS["kind_unavailable"].format(plural=lm.KIND_PLURAL["airport"]), block)   # D136(a): the airports' sentence
        self.assertIn(lm.WORDS["kind_unavailable"].format(plural=lm.KIND_PLURAL["park"]), block)       # the local parks' sentence
        self.assertIn(b2.WORDS["part_unavailable"].format(Part=b2.PART_WORDS["park"][0], one=b2.PART_WORDS["park"][1]), block)

    def test_one_pad_us_line_per_section_and_no_source_line_for_a_held_source(self):                      # F9, F10, D141(k)
        block = B6AboutAndSources.b6_block(self.copy)
        self.assertEqual(block.count("Protected Areas Database of the United States (PAD-US) 4.1"), 2)   # the base map's and the landmarks'
        about = page(self.copy, "about.html")
        self.assertNotIn("Source: FEMA copy", about)
        self.assertNotIn("Source: U.S. Census Bureau, TIGER/Line 2026 area landmarks.", about)

    def test_date_not_recorded_appears_nowhere_on_the_page_or_in_the_data(self):                          # F2
        for out in (self.copy, self.none):
            self.assertNotIn("not recorded", page(out, "about.html"), out.name)
            self.assertNotIn("not recorded", page(out, "data/base.json"), out.name)

    def test_the_credit_builder_takes_the_index_date_and_says_data_unavailable_without_one(self):        # F2 (unit)
        self.assertEqual(site.landmark_line("faa_nasr", "2026-10-01"), self.FAA_LINE)
        self.assertEqual(site.landmark_line("padus_local", None), self.PAD_LINE)
        self.assertEqual(site.landmark_line("padus_local", "2026-10-20"), "Source: USGS Gap Analysis Project, Protected Areas "
                         "Database of the United States (PAD-US) 4.1, local parks, layer last edited 2026-10-20.")
        self.assertEqual(site.landmark_line("usgs_hospitals", None), self.USGS_LINE)     # no date slot: the module's own line
        for key in ("faa_nasr", "padus_local", "hifld_hospitals"):
            self.assertNotIn("not recorded", site.landmark_line(key, None), key)

    def test_the_hospital_source_is_named_only_when_the_store_used_it_for_each_case(self):                  # F1 (unit)
        usgs = site._landmark_words({"landmarks": B6_LANDMARKS}, None)
        self.assertEqual(usgs["hospital"], {"state": "loaded", "source": "usgs_hospitals", "sentence": lm.WORDS["hospital_usgs"],
                                            "credit": self.USGS_LINE})
        self.assertNotIn(self.COPY_LINE, usgs["sources"])
        copy = site._landmark_words({"landmarks": HIFLD_LANDMARKS}, None)
        self.assertEqual(copy["hospital"], {"state": "loaded", "source": "hifld_hospitals", "sentence": lm.WORDS["hospital_hifld"],
                                            "credit": self.COPY_LINE})
        self.assertNotIn(self.USGS_LINE, copy["sources"])                        # read, with no row kept: never named
        none = site._landmark_words({"landmarks": NONE_LANDMARKS}, None)
        self.assertEqual(none["hospital"]["state"], "unavailable")
        self.assertIsNone(none["hospital"]["source"])
        self.assertIsNone(none["hospital"]["credit"])
        self.assertEqual(none["hospital"]["sentence"], lm.WORDS["kind_unavailable"].format(plural="hospitals"))
        # a copy the kind names but that kept no row is not the source used
        kept_none = json.loads(json.dumps(HIFLD_LANDMARKS))
        kept_none["sources"]["hifld_hospitals"]["kept"] = 0
        self.assertIsNone(site._landmark_words({"landmarks": kept_none}, None)["hospital"]["source"])
        nothing = site._landmark_words(None, None)
        self.assertEqual((nothing["sources"], nothing["credits"]), ([], {"faa_nasr": None, "padus": None}))

    def test_the_pad_us_line_follows_either_part_that_read_the_layer(self):                               # F10 (unit)
        vector_read = {"sources": {"padus": {"state": "fetched", "files": 1, "fetched": 1, "cache": 0, "failed": 0}}}
        only_vector = site._landmark_words({"landmarks": NONE_LANDMARKS}, vector_read)
        self.assertEqual(only_vector["credits"]["padus"], self.PAD_LINE)         # the park outlines were read: one line
        vector_failed = {"sources": {"padus": {"state": "failed", "files": 1, "fetched": 0, "cache": 0, "failed": 1}}}
        self.assertIsNone(site._landmark_words({"landmarks": NONE_LANDMARKS}, vector_failed)["credits"]["padus"])

    def test_a_source_row_with_no_as_of_has_no_date_and_its_count_is_never_read_as_one(self):            # F12 (unit)
        block = {"sources": {"tiger_aiannh": {"state": "cache", "files": 1, "fetched": 1, "cache": 0, "failed": 0, "bytes": 9,
                                              "reasons": []},
                             "shown": {"state": "loaded", "as_of": "2026-09-28"},
                             "fetched_only": {"state": "loaded", "fetched": "2026-10-20T12:00:00Z"}}}
        self.assertEqual(site._source_dates(block), {"tiger_aiannh": {"state": "cache", "as_of": site.NO_DATE},
                                                     "shown": {"state": "loaded", "as_of": "2026-09-28"},
                                                     "fetched_only": {"state": "loaded", "as_of": site.NO_DATE}})
        self.assertEqual(site._source_dates(None), {})



def attr(text):
    """A sentence as the template writes it inside an attribute (Jinja escapes the quote and the ampersand)."""
    from markupsafe import escape
    return str(escape(text))


class OptionsSheet(unittest.TestCase):
    """The map options sheet (DESIGN 13.6, D108, D110; B6 stage S1): the markup the browser drives (templates/map.html), the words
    it prints (build.SHEET_WORDS, rendered by Python and carried in data/base.json), the roles its colours come from (map.css
    and style.css), and the map script that holds none of its sentences (AGENTS.md rule 4). Browser behaviour is checked by
    tools/smoke_map.py (check_options_sheet)."""

    @classmethod
    def setUpClass(cls):
        cls.full = Path(tempfile.mkdtemp(prefix="hailwatch-sheet-full-"))
        cls.addClassCleanup(shutil.rmtree, cls.full, True)
        cls.result = site.build(cls.full, None, NOW, sample=True, storm_layers=True, hail_history=True, hail_addresses=True)
        cls.plain = Path(tempfile.mkdtemp(prefix="hailwatch-sheet-plain-"))
        cls.addClassCleanup(shutil.rmtree, cls.plain, True)
        site.build(cls.plain, None, NOW, sample=True)
        cls.html = page(cls.full, "map.html")
        cls.sheet = cls.html[cls.html.index('<section class="sheet map-options" id="map-options"'):]
        cls.sheet = cls.sheet[:cls.sheet.index("\n  <noscript>")]

    def test_the_sheet_is_a_hidden_dialog_section_and_the_button_names_it(self):
        self.assertIn('<section class="sheet map-options" id="map-options" role="dialog" aria-modal="true" '
                      'aria-labelledby="mo-title" hidden>', self.html)
        self.assertIn('aria-controls="map-options"', self.html)
        self.assertEqual(self.html.count('id="map-options"'), 1)
        for gone in ('id="layers"', 'name="layer"', 'name="base"', "popover", "<legend>Base map</legend>", "fieldset"):
            self.assertNotIn(gone, self.html, gone)

    def test_the_header_title_and_the_close_button_are_python_words_of_44_px_or_more(self):
        self.assertIn('<h2 class="mo-title" id="mo-title" tabindex="-1">Map options</h2>', self.sheet)
        self.assertIn('<button type="button" class="mo-close" id="mo-close" aria-label="Close map options">', self.sheet)

    def test_the_groups_come_in_the_design_order(self):
        order = ["Base map", "Live weather", "Five-year history", "Landmarks", 'id="tg-poi"', 'id="tg-hail-recent"',
                 'id="tg-warnings"', 'id="tg-reports"', 'id="mo-reset"']
        at = [self.sheet.index(part) for part in order]
        self.assertEqual(at, sorted(at))
        self.assertLess(self.sheet.index("Addresses, streets and building outlines"), self.sheet.index('id="mo-reset"'))
        self.assertLess(self.sheet.index('id="tg-reports"'), self.sheet.index('id="b3-keys"'))

    def test_the_base_map_cards_are_buttons_with_the_map_and_imagery_values(self):
        self.assertEqual(self.sheet.count('data-group="base"'), 2)
        self.assertIn('data-group="base" data-key="map" aria-pressed="true"', self.sheet)
        self.assertIn('data-group="base" data-key="imagery" aria-pressed="false" data-legend="'
                      "Imagery: USDA, USGS, The National Map. Your IP address and the map area you view go to USGS while it "
                      'is on."', self.sheet)
        self.assertEqual(self.sheet.count('data-legend="' + site.IMAGERY["credit_line"] + '"'), 1)

    def test_the_live_chips_are_the_layers_with_their_legend_words(self):
        for key in ("precip", "temp", "wind", "satellite", "hail_60", "hail_1440"):
            self.assertEqual(self.sheet.count(f'data-group="live" data-key="{key}"'), 1, key)
        self.assertIn('data-legend="' + attr(site.SHEET_WORDS["legend_precipitation"]) + '"', self.sheet)
        self.assertIn('data-legend="' + attr(site.SHEET_WORDS["legend_temperature"]) + '"', self.sheet)
        self.assertIn('data-legend="' + attr(site.SHEET_WORDS["legend_wind"]) + '"', self.sheet)
        self.assertIn('data-legend="' + attr(site.SHEET_WORDS["legend_hail_last_hour"]) + '"', self.sheet)
        plain = self.plain_sheet()
        self.assertNotIn('data-key="hail_60"', plain)                    # the swath layers exist only in --storm-layers builds
        self.assertNotIn('data-key="satellite"', plain)
        self.assertIn('data-group="live" data-key="precip" aria-pressed="true"', plain)

    def plain_sheet(self):
        html = page(self.plain, "map.html")
        start = html.index('<section class="sheet map-options" id="map-options"')
        return html[start:html.index("\n  <noscript>", start)]

    def test_the_five_year_chips_and_the_fire_and_smoke_coming_words(self):
        for key in ("hail", "heat", "wind", "flood", "fire_smoke"):
            self.assertEqual(self.sheet.count(f'data-group="history" data-key="{key}"'), 1, key)
        self.assertIn("Past records from the last five years. Not a forecast.", self.sheet)
        fire = self.sheet[self.sheet.index('data-key="fire_smoke"'):]
        fire = fire[:fire.index("</button>")]
        self.assertIn('data-reason="Coming later: fire is not in the map yet. Coming later: smoke is not in the map yet."', fire)
        self.assertIn('<span class="mo-note">Coming</span>', fire)

    def test_the_landmark_chips_carry_the_codes_of_the_landmark_module_and_the_held_church_reason(self):
        self.assertEqual(lm.KIND_CODE, {"school": "s", "hospital": "h", "airport": "a", "fire": "f", "park": "p", "church": "c"})
        for code in ("s", "p", "h", "a", "f", "c"):
            self.assertEqual(self.sheet.count(f'data-group="landmark" data-key="{code}"'), 1, code)
        church = self.sheet[self.sheet.index('data-key="c"'):]
        church = church[:church.index("</button>")]
        self.assertIn('data-reason="' + attr(lm.CHURCH_HELD) + '"', church)
        self.assertIn('<span class="mo-note">Held</span>', church)
        self.assertIn('data-name="schools"', self.sheet)
        self.assertIn('data-name="fire and EMS stations"', self.sheet)

    def test_the_landmark_line_reads_its_template_and_the_sub_line_is_the_sheet_words(self):
        self.assertIn('id="mo-land-line" data-template="' + attr(site.SHEET_WORDS["landmark_line"]) + '"', self.sheet)
        self.assertIn('<p class="mo-sub">' + attr(site.SHEET_WORDS["landmarks_sub_line"]) + "</p>", self.sheet)
        self.assertEqual(site.SHEET_WORDS["landmark_line"],
                         "{kinds} from the public lists named under About, shown as dots with their names.")
        self.assertIn('data-waiting="Turn on Points of interest to show these."', self.sheet)

    def test_the_switches_are_role_switch_checkboxes_with_their_descriptions(self):
        for id_ in ("tg-poi", "tg-hail-recent", "tg-warnings", "tg-reports"):
            self.assertEqual(self.sheet.count(f'id="{id_}"'), 1, id_)
            self.assertRegex(self.sheet, rf'<input type="checkbox" role="switch" id="{id_}"', id_)
        self.assertIn('<input type="checkbox" role="switch" id="tg-poi" checked>', self.sheet)
        self.assertIn('<input type="checkbox" role="switch" id="tg-warnings" checked>', self.sheet)
        self.assertIn('<input type="checkbox" role="switch" id="tg-reports"', self.sheet)
        self.assertNotIn('id="tg-reports" checked', self.sheet)
        for words in ("Landmark dots and names, for the kinds chosen above", "Radar estimate of 1 in or more, last 30 days",
                      "NWS outlines", "Storm Prediction Center (SPC), last 3 days", "Points of interest",
                      "Highlight recent radar hail", "Warnings", "Storm reports"):
            self.assertIn(words, self.sheet, words)

    def test_reset_has_its_button_and_its_line(self):
        self.assertIn('<button type="button" class="mo-reset-btn" id="mo-reset">Reset</button>', self.sheet)
        self.assertIn("Back to Map and Precipitation, with Points of interest and Warnings on. Everything else off.", self.sheet)

    def test_the_address_legend_sits_inside_the_sheet_under_its_heading_only_with_the_flag(self):
        self.assertIn('<div class="b3-keys" id="b3-keys">', self.sheet)
        self.assertIn('<p class="legend-tap b3-head">Addresses, streets and building outlines</p>', self.sheet)
        self.assertIn('data-layer="shapes"', self.sheet)
        self.assertNotIn('id="b3-keys"', self.plain_sheet())

    def test_the_hail_legends_are_the_swath_module_sentences_written_once(self):
        from website import swath as sw
        note = sw.WORDS_SWATH["legend_note"].format(window="hour")
        self.assertIn(note, site.SHEET_WORDS["legend_hail_last_hour"])
        self.assertIn(sw.WORDS_SWATH["uncoloured"].format(window="24 hours"), site.SHEET_WORDS["legend_hail_last_day"])
        self.assertIn('data-legend="' + attr(site.SHEET_WORDS["legend_hail_last_hour"]) + '"', self.html)

    def test_the_sheet_words_hold_the_13_6_lines_verbatim_and_reuse_the_module_sentences(self):
        words = site.SHEET_WORDS
        self.assertEqual(words["legend_precipitation"], "Rate as liquid water. Radar estimate up to now, High-Resolution Rapid "
                                                        "Refresh (HRRR) model forecast after.")
        self.assertEqual(words["legend_temperature"], "HRRR model temperature, in °F. Town numbers are the National Weather "
                                                      "Service (NWS) forecast.")
        self.assertEqual(words["legend_wind"], "HRRR model. Roofing limit 25 mph.")
        self.assertEqual(words["legend_recent"], "Buildings in cells where radar estimated 1 in or more in the last 30 days are "
                                                 "highlighted. Buildings in other cells are not; that is not the same as no hail. "
                                                 "Radar estimate, not a measurement at the ground.")
        self.assertEqual(words["legend_reports"], "No report is not “no hail”.")
        self.assertEqual(words["waiting"], "Turn on Points of interest to show these.")
        self.assertIs(words["held_church"], lm.CHURCH_HELD)
        self.assertIs(words["legend_imagery"], site.IMAGERY["credit_line"])
        self.assertEqual(words["coming_fire"], "Coming later: fire is not in the map yet.")
        self.assertEqual(words["coming_smoke"], "Coming later: smoke is not in the map yet.")
        self.assertIs(words["unavailable"], lb.UNAVAILABLE_TEXT)
        self.assertTrue(words["base_failed"].startswith("Data unavailable. "))
        self.assertTrue(words["base_failed"].endswith(" This is not an all-clear."))

    def test_the_sheet_words_are_all_in_base_json_and_none_is_an_em_or_en_dash(self):
        base_sheet = json.loads(page(self.full, "data/base.json"))["sheet"]
        self.assertEqual(base_sheet, site.SHEET_WORDS)
        for key, text in site.SHEET_WORDS.items():
            self.assertNotIn("\u2014", text, key)
            self.assertNotIn("\u2013", text, key)

    def test_the_map_script_holds_none_of_the_sheet_sentences(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        js = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), js)   # the script's own escapes, read as text
        for key, text in site.SHEET_WORDS.items():
            if len(text) < 25:
                continue
            for part in re.split(r"\{\w+\}", text):
                if len(part) >= 25:
                    self.assertNotIn(part.strip(), js, key)
        from website import swath as sw
        for words in (sw.WORDS_SWATH["legend_note"], sw.WORDS_SWATH["uncoloured"]):     # the two the sheet reuses (the all-clear
            for part in re.split(r"\{\w+\}", words):                                # sentence is shared by every module)
                if len(part) >= 25:
                    self.assertNotIn(part.strip(), js)

    def test_the_map_script_names_no_word_of_the_sheet_by_hand(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        for needle in ("toggleLayers", "fitLayersMenu", "paintSwatches", "LAYER_WORD", 'input[name=', "#layers"):
            self.assertNotIn(needle, js, needle)
        for needle in ('"Map options', '"Live weather', '"Five-year history', '"Points of interest', '"Coming later',
                       '"Turn on Points', '"Reset', '"Base map'):
            self.assertNotIn(needle, js, needle)
        for name in ("toggleOptions", "renderOptions", "setLive", "setHistory", "setLandmark", "setPoi", "landmarkLine",
                     "setHailRecent", "resetOptions", "readOptionParams", "optionParams", "loadBase", "trapOptionsFocus"):
            self.assertRegex(js, rf"function {name}\(", name)
        self.assertIn('getAttribute("data-legend")', js)
        self.assertIn('getAttribute("data-template")', js)

    def test_the_address_keeps_the_sheet_choices_under_their_own_names(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        for name in ('"poi"', '"hail_recent"', '"history"', '"landmarks"', '"layer"', '"none"'):
            self.assertIn(name, js, name)

    def test_the_sheet_css_uses_the_roles_and_no_glass_blur_or_shadow(self):
        css = (ROOT / "website" / "static" / "map" / "map.css").read_text(encoding="utf-8")
        start = css.index("/* ---------------------------------------------------------------- the options sheet")
        block = css[start:css.index("/* ---------------------------------------------------------------- bottom:", start)]
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", block), [], "a hex value in a sheet rule")
        for word in ("--glass", "backdrop-filter: blur", "drop-shadow"):
            self.assertNotIn(word, block, word)
        self.assertIn("box-shadow: none", block)
        self.assertIn("border-radius: var(--radius)", block)
        self.assertIn("min-height: 44px", block)
        self.assertIn("outline: 3px solid var(--color-focus)", block)

    def test_the_map_css_roles_are_the_style_css_roles_in_both_schemes(self):
        style = (ROOT / "website" / "static" / "style.css").read_text(encoding="utf-8")
        mapcss = (ROOT / "website" / "static" / "map" / "map.css").read_text(encoding="utf-8")
        roles = ("color-surface", "color-surface-muted", "color-line", "color-text", "color-text-muted", "color-focus",
                 "color-on-chip")

        def blocks(text):
            light = text[text.index(":root {"):]
            light = light[:light.index("\n}")]
            dark_at = text.index("@media (prefers-color-scheme: dark) {")
            dark = text[dark_at:]
            dark = dark[dark.index(":root {"):]
            dark = dark[:dark.index("\n  }")]
            decl = lambda s: {k: v.strip() for k, v in re.findall(r"--([\w-]+):\s*([^;]+);", s)}
            return decl(light), decl(dark)

        def resolve(name, *scopes, depth=0):
            for scope in scopes:
                if name in scope:
                    value = scope[name]
                    m = re.fullmatch(r"var\(--([\w-]+)\)", value)
                    return resolve(m.group(1), *scopes, depth=depth + 1) if m else value
            raise AssertionError(name)

        style_light, style_dark = blocks(style)
        map_light, map_dark = blocks(mapcss)
        for role in roles:
            want_light = resolve(role, style_light)
            want_dark = resolve(role, style_dark, style_light)
            self.assertEqual(resolve(role, map_light).lower(), want_light.lower(), f"light {role}")
            self.assertEqual(resolve(role, map_dark, map_light).lower(), want_dark.lower(), f"dark {role}")

    def test_the_sheet_markup_takes_its_words_from_python(self):
        template = (ROOT / "website" / "templates" / "map.html").read_text(encoding="utf-8")
        start = template.index('<section class="sheet map-options"')
        sheet_src = template[start:template.index("\n  <noscript>", start)]
        for words in ("Map options", "Live weather", "Five-year history", "Landmarks", "Base map", "Reset", "Coming later"):
            self.assertNotIn(words, sheet_src, words)
        self.assertGreaterEqual(sheet_src.count("{{ chip("), 15)
        self.assertGreaterEqual(sheet_src.count("{{ card("), 2)

    def test_the_default_build_has_the_sheet_without_the_storm_chips_or_the_address_block(self):
        html = page(self.plain, "map.html")
        self.assertIn('id="map-options"', html)
        self.assertNotIn("data-key=\"hail_1440\"", html)
        self.assertNotIn('id="b3-keys"', html)


    def test_the_first_paint_words_travel_as_json_in_the_map_page(self):
        start = self.html.index('<script type="application/json" id="map-words">')
        block = self.html[start:self.html.index("</script>", start)]
        words = json.loads(block[block.index(">") + 1:])
        self.assertEqual(words, site.MAP_WORDS)
        for key in ("reports_failed", "reports_none", "no_reports", "nothing_to_show", "no_layer_pictures", "no_layer_picture",
                    "radar_reason", "satellite_reason", "forecast_reason", "base_failed", "unavailable", "held", "waiting",
                    "partial_history", "list_and", "list_comma", "list_last"):
            self.assertIn(key, words, key)
        self.assertLess(start, self.html.index('id="map-options"'))

    def test_the_page_words_are_pinned_by_value_and_no_interim_sentence_is_invented(self):
        pinned = site.PAGE_WORDS
        self.assertEqual(pinned["reports_failed"], "<strong>Storm reports didn't all load</strong> ({detail}). ")
        self.assertEqual(pinned["reports_none"], "No SPC storm reports in or near Montana in the last 3 days. ")
        self.assertEqual(pinned["no_reports"], "No reports. ")
        self.assertEqual(pinned["nothing_to_show"], "Nothing to show for {layer}")
        self.assertEqual(pinned["no_layer_pictures"], "No {layer} pictures in this update{why}. This is not an all-clear.")
        self.assertEqual(pinned["no_layer_picture"], "No {layer} picture in this update. This is not an all-clear.")
        self.assertEqual(pinned["radar_reason"], "radar: {detail}")
        self.assertEqual(site.SHEET_WORDS["fire_smoke"], "Fire and smoke")
        # supervisor ruling (S1 legends): nothing is published before S5, so no interim words are invented for the layers
        # that are not drawn yet; their chips and lines keep their 13.6 words
        self.assertNotIn("not_drawn", site.SHEET_WORDS)
        self.assertNotIn("Not drawn on the map", self.html)
        self.assertTrue(site.SHEET_WORDS["partial_history"].startswith("Data unavailable. "))
        self.assertTrue(site.SHEET_WORDS["partial_history"].endswith(" This is not an all-clear."))
        self.assertIn("a zero may mean a count is missing", site.SHEET_WORDS["partial_history"])

    def test_the_map_script_reads_the_page_words_and_holds_none_of_the_moved_sentences(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        for literal in ("didn't all load</strong> (", "No SPC storm reports in or near Montana", '"Nothing to show for ',
                        '" picture in this update. This is not an all-clear."', '"<p>No reports. "', '"radar: "', '"satellite: "',
                        '"model forecast: "', '" pictures in this update" + (why'):
            self.assertNotIn(literal, js, literal)
        for key in ("reports_failed", "nothing_to_show", "no_layer_pictures", "no_layer_picture", "radar_reason",
                    "satellite_reason", "forecast_reason"):
            self.assertIn(f'wordFill("{key}"', js, key)
        self.assertIn("PW.reports_none", js)
        self.assertIn("PW.no_reports", js)
        self.assertIn('getElementById("map-words")', js)

    def test_the_legends_of_the_layers_not_drawn_yet_keep_their_spec_words(self):
        # the chips and lines of the five-year, landmark and recent layers keep the words of DESIGN 13.6 until their layers
        # are drawn (S2 to S4); no sentence on the page says a layer is not drawn yet
        self.assertNotIn("data-not-drawn", self.sheet)
        recent = self.sheet[self.sheet.index('id="tg-hail-recent"'):]
        tag = recent[:recent.index(">")]
        self.assertIn('data-legend="' + attr(site.SHEET_WORDS["legend_recent"]) + '"', tag)   # the 13.6 legend

    def test_the_history_reason_line_sits_under_the_history_line(self):
        self.assertLess(self.sheet.index('id="mo-hist-line"'), self.sheet.index('id="mo-hist-reason"'))
        self.assertLess(self.sheet.index('id="mo-hist-reason"'), self.sheet.index('id="mo-land-h"'))

    def test_the_landmark_chips_carry_the_unavailable_words_on_their_faces(self):
        for code in ("s", "p", "h", "a", "f"):
            chip = self.sheet[self.sheet.index(f'data-group="landmark" data-key="{code}"'):]
            chip = chip[:chip.index("</button>")]
            self.assertIn('<span class="mo-note">Data unavailable</span>', chip, code)

    def test_the_pending_chips_are_solid_and_the_switch_input_is_a_44_px_target(self):
        css = (ROOT / "website" / "static" / "map" / "map.css").read_text(encoding="utf-8")
        pending = css[css.index("#map-options .mo-chip.is-pending {"):]
        self.assertNotIn("dashed", pending[:pending.index("}")])
        switch = css[css.index('#map-options .mo-switch input[type="checkbox"] {'):]
        self.assertIn("height: 44px", switch[:switch.index("}")])
        track = css[css.index('#map-options .mo-switch input[type="checkbox"]::before {'):]
        self.assertIn("height: 28px", track[:track.index("}")])

    def test_a_chip_still_loading_is_not_disabled_and_a_tap_on_it_changes_nothing(self):
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        self.assertIn('look === "plain" || look === "pending"', js)           # aria-disabled is for the other looks
        self.assertIn('item.classList.contains("is-pending")', js)           # a tap on a chip still loading returns


if __name__ == "__main__":
    unittest.main()

