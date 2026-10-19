"""Hail history joins (website/joins.py, B2): the parsers and their units (LSR, NCEI, SWDI, IEM daily, IEM watchwarn,
the NWS zone shapefile), the join rules (distance from the tile bounds and the cell, the 100-bit cover, zone lookup,
station choice, SPC days), the words (forbidden terms, the kind words, the unavailable and partial sentences), the
Montana clock, the fetcher (cache, stale copy, ledger), an offline build of a small store from canned responses (no
network), verify on the build, and the committed SAMPLE joins in website/data/hail-fixture.

No network: every request goes through a fake that returns canned bytes. Each test that writes files makes its own
temporary folder and removes only that folder (decision 7). Shapefile tests need pyshp and skip without it."""

import csv
import gzip
import hashlib
import io
import json
import math
import random
import re
import shutil
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from website import hail
from website import joins as J
from website import sources as src

FIXTURE = Path(__file__).resolve().parent.parent / "website" / "data" / "hail-fixture"
GATE = (797, 1986)          # Benchland's gate cell (B2 gate 1): its centre is 47.025 N, 110.135 W
GATE_KEY = hail.cell_key(*GATE)
GATE_TILE = hail.tile_name(GATE[0] // 10, GATE[1] // 10)
GATE_TILE_RC = (GATE[0] // 10, GATE[1] // 10)
FORBIDDEN = re.compile(r"\b(damag\w*|dry|clear\w*|insurance|eligib\w*|confirm\w*|customers?|guaranteed|approved|best)\b",
                       re.IGNORECASE)
# D34, D35: the ten zone products: the nine of D34 and flood watches (FA.A). FL.W is not a zone product.
D35_ZONE_PRODUCTS = {("HW", "W"), ("WS", "W"), ("BZ", "W"), ("IS", "W"), ("EC", "W"), ("WC", "W"), ("DS", "W"),
                     ("WI", "Y"), ("FW", "W"), ("FA", "A")}
try:
    import shapefile as _pyshp   # noqa: F401
    HAVE_PYSHP = True
except ImportError:
    HAVE_PYSHP = False


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def check_words(test: unittest.TestCase, text: str) -> None:
    """No forbidden term outside a quoted remark (the NWS's own words, D4), the label "NWS damage threat tag" and the
    negation "not an all-clear"; "no hail" or "no wind" only in a sentence that says it is not the conclusion;
    "all-clear" only inside "not an all-clear"."""
    stripped = re.sub(r"\u201c[^\u201d]*\u201d", "", text).replace("NWS damage threat tag", "")
    stripped = stripped.replace("not an all-clear", "")
    test.assertIsNone(FORBIDDEN.search(stripped), f"forbidden term in: {text!r}")
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\bno (hail|wind)\b", sentence, re.IGNORECASE):
            test.assertRegex(sentence, r"\bnot\b", f"'no hail' or 'no wind' without a negation: {sentence!r}")
    if "all-clear" in text.lower():
        test.assertIn("not an all-clear", text.lower(), f"all-clear as a claim: {text!r}")


def store_form(inline: dict) -> tuple[dict, dict]:
    """(tile doc, events table) from a tile written with inline rows: the rows go to one events table and the tile
    holds their indexes, as the build writes them. Warnings are given as (event dict, cover hex) pairs."""
    events = {"f": J.EVENTS_FORMAT, "d0": "2020-01-01", "reports": [], "records": [], "warnings": []}
    doc = dict(inline)
    doc["reports"] = []
    for row in inline.get("reports", []):
        events["reports"].append(list(row))
        doc["reports"].append(len(events["reports"]) - 1)
    doc["records"] = []
    for row in inline.get("records", []):
        events["records"].append(list(row))
        doc["records"].append(len(events["records"]) - 1)
    doc["warnings"] = []
    for item, cover in inline.get("warnings", []):
        events["warnings"].append(dict(item))
        doc["warnings"].append([len(events["warnings"]) - 1, cover])
    doc["zones"] = dict(inline.get("zones", {}))
    return doc, events


def lsr_csv(rows) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(J.LSR_HEADER)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


BENCHLAND_LSR = ["202506152010", "2025/06/15 20:10", "47.08", "-110.02", "1.75", "TFX", "H", "HAIL", "Benchland",
                 "Judith Basin", "MT", "Public", "Public caller updated with golf ball sized hail.", "MTC045",
                 "Judith Basin", "E"]


class ParserTests(unittest.TestCase):
    def test_lsr_hail_row_units_and_qualifier(self):
        rows = J.parse_lsr(lsr_csv([BENCHLAND_LSR]))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["utc"], utc(2025, 6, 15, 20, 10))
        self.assertEqual((row["code"], row["type"], row["mag_text"], row["unit"]), ("H", "hail", "1.75", "in"))
        self.assertEqual((row["qual"], row["src"], row["city"]), ("E", "Public", "Benchland"))
        self.assertLessEqual(len(row["remark"]), 160)

    def test_lsr_gust_is_mph_and_none_mag_is_missing(self):
        gust = ["202506081615", "2025/06/08 16:15", "47.42", "-104.96", "58.0", "GGW", "N", "NON-TSTM WND GST",
                "2 W Bloomfield", "Dawson", "MT", "Mesonet", "Station.", "MTC021", "Dawson", "M"]
        damage = ["202506010100", "2025/06/01 01:00", "46.0", "-111.0", "None", "TFX", "D", "TSTM WND DMG", "X",
                  "Y", "MT", "Trained Spotter", "", "MTC001", "Z", ""]
        rows = J.parse_lsr(lsr_csv([gust, damage]))
        self.assertEqual((rows[0]["mag_text"], rows[0]["unit"], rows[0]["qual"]), ("58", "mph", "M"))
        self.assertEqual((rows[1]["mag_text"], rows[1]["unit"], rows[1]["qual"]), ("", "", ""))
        self.assertEqual(rows[1]["src"], "Trained spotter")

    def test_lsr_unquoted_comma_in_city_keeps_the_qualifier(self):
        raw = ("VALID,VALID2,LAT,LON,MAG,WFO,TYPECODE,TYPETEXT,CITY,COUNTY,STATE,SOURCE,REMARK,UGC,UGCNAME,QUALIFIER\n"
               "202212221055,2022/12/22 10:55,46.0,-108.0,70,BYZ,N,NON-TSTM WND GST,Big, Sky,Yellowstone,MT,"
               "Mesonet,Remark,MTC111,Yellowstone,M\n").encode("utf-8")
        rows = J.parse_lsr(raw)
        self.assertEqual(rows[0]["city"], "Big, Sky")
        self.assertEqual(rows[0]["qual"], "M")
        self.assertEqual(rows[0]["mag_text"], "70")

    def test_lsr_header_is_checked(self):
        with self.assertRaises(J.JoinsError):
            J.parse_lsr(b"a,b,c\n1,2,3\n")

    def test_lsr_sentence_case(self):
        self.assertEqual(J._sentence_case("TRAINED SPOTTER"), "Trained spotter")
        self.assertEqual(J._sentence_case("CO-OP Observer"), "CO-OP observer")
        self.assertEqual(J._sentence_case("MELVILLE FOOTHILLS"), "Melville foothills")
        self.assertEqual(J._sentence_case("CoCoRaHS"), "CoCoRaHS")
        self.assertEqual(J._sentence_case("ASOS"), "ASOS")

    def _ncei_gz(self, rows) -> bytes:
        fields = ["EVENT_TYPE", "STATE", "BEGIN_DATE_TIME", "CZ_TYPE", "CZ_FIPS", "BEGIN_LAT", "BEGIN_LON",
                  "MAGNITUDE", "MAGNITUDE_TYPE", "SOURCE", "CZ_TIMEZONE", "BEGIN_LOCATION", "CZ_NAME", "WFO"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            base = {f: "" for f in fields}
            base.update({"STATE": "MONTANA", "CZ_TIMEZONE": "MST-7", "WFO": "TFX"})
            base.update(row)
            writer.writerow(base)
        return gzip.compress(buf.getvalue().encode("utf-8"))

    def test_ncei_local_time_units_and_zone_rows(self):
        data = self._ncei_gz([
            {"EVENT_TYPE": "Hail", "CZ_TYPE": "C", "CZ_FIPS": "45", "BEGIN_DATE_TIME": "15-JUN-25 13:10:00",
             "BEGIN_LAT": "47.08", "BEGIN_LON": "-110.02", "MAGNITUDE": "1.75", "SOURCE": "PUBLIC",
             "BEGIN_LOCATION": "BENCHLAND"},
            {"EVENT_TYPE": "Thunderstorm Wind", "CZ_TYPE": "C", "CZ_FIPS": "45", "BEGIN_DATE_TIME": "15-JUN-25 14:00:00",
             "BEGIN_LAT": "47.0", "BEGIN_LON": "-109.9", "MAGNITUDE": "50", "MAGNITUDE_TYPE": "MG",
             "SOURCE": "Mesonet", "BEGIN_LOCATION": "X"},
            {"EVENT_TYPE": "High Wind", "CZ_TYPE": "Z", "CZ_FIPS": "7", "BEGIN_DATE_TIME": "24-MAR-25 11:15:00",
             "MAGNITUDE": "50.00", "MAGNITUDE_TYPE": "MG", "SOURCE": "Mesonet", "CZ_NAME": "KOOTENAI"},
            {"EVENT_TYPE": "Winter Storm", "CZ_TYPE": "Z", "CZ_FIPS": "172", "BEGIN_DATE_TIME": "01-JAN-25 00:00:00",
             "SOURCE": "NWS", "CZ_NAME": "MELVILLE FOOTHILLS"},
            {"EVENT_TYPE": "Hail", "STATE": "IDAHO", "CZ_TYPE": "C", "CZ_FIPS": "1", "BEGIN_DATE_TIME":
             "15-JUN-25 13:10:00", "BEGIN_LAT": "47.08", "BEGIN_LON": "-110.02", "MAGNITUDE": "1.00"},
        ])
        out = J.parse_ncei(data)
        self.assertEqual(len(out["points"]), 2)
        hail_row, wind_row = out["points"]
        self.assertEqual(hail_row["utc"], utc(2025, 6, 15, 20, 10))         # 13:10 MST-7 is 20:10 UTC
        self.assertEqual((hail_row["mag_text"], hail_row["unit"], hail_row["code"]), ("1.75", "in", "hail"))
        self.assertEqual((wind_row["mag_text"], wind_row["unit"]), ("50", "kt"))
        self.assertEqual((wind_row["mag_kt"], wind_row["mag_mph"]), (50, 58))   # 50 kt is 57.5 mph, shown as 58
        self.assertEqual(wind_row["qual"], "MG")                       # the NCEI code (D5); the words come later
        self.assertEqual(J._qualifier(wind_row["qual"], J.WORDS_JOINS), " (measured gust)")
        zones = {z["zone"]: z for z in out["zone_rows"]}
        self.assertEqual(set(zones), {"MTZ007", "MTZ172"})
        self.assertEqual((zones["MTZ007"]["mag_kt"], zones["MTZ007"]["mag_mph"]), (50, 58))
        self.assertEqual(zones["MTZ172"]["mag_text"], "")
        self.assertEqual(out["newest_local"], datetime(2025, 6, 15, 14, 0))

    def test_county_coded_points_of_other_types_are_not_joined_in_this_version(self):
        """D34: tornado, flood, flash flood, heavy rain, funnel cloud, lightning and debris flow points are county rows
        with coordinates. This version joins the hail and thunderstorm wind points and the zone-coded rows only."""
        kinds = ("Tornado", "Flood", "Flash Flood", "Heavy Rain", "Funnel Cloud", "Lightning", "Debris Flow")
        data = self._ncei_gz([
            {"EVENT_TYPE": kind, "CZ_TYPE": "C", "CZ_FIPS": "45", "BEGIN_DATE_TIME": "15-JUN-25 13:10:00",
             "BEGIN_LAT": "47.08", "BEGIN_LON": "-110.02", "SOURCE": "PUBLIC", "BEGIN_LOCATION": "BENCHLAND"}
            for kind in kinds])
        out = J.parse_ncei(data)
        self.assertEqual((out["points"], out["zone_rows"], out["malformed"]), ([], [], 0))

    def test_swdi_footers_duplicates_and_hundredths(self):
        raw = ("ZTIME,WSR_ID,CELL_ID,PROB,SEVPROB,MAXSIZE,LAT,LON\n"
               "2025-06-15T20:10:00Z,KTFX,A1,100,40,1.75,47.08,-110.02\n"
               "2025-06-15T20:10:00Z,KTFX,A1,100,40,1.75,47.08,-110.02\n"
               "2025-06-15T20:20:00Z,KTFX,A2,100,0,0.5,47.1,-110.0\n"
               "2025-06-15T20:30:00Z,KTFX,A3,100,0,0,47.1,-110.0\n"
               "summary\ncount,3\ntotalTimeInSeconds,0.1\n").encode("utf-8")
        out = J.parse_swdi(raw)
        self.assertEqual(out["duplicates"], 1)
        self.assertEqual([r["size"] for r in out["rows"]], [175, 50])     # MAXSIZE 0 is not a detection
        self.assertEqual(out["newest"], utc(2025, 6, 15, 20, 20))

    def test_swdi_month_with_no_detections_is_empty(self):
        raw = b"summary\ncount,0\ntotalTimeInSeconds,0.0\n"
        out = J.parse_swdi(raw)
        self.assertEqual((out["rows"], out["duplicates"]), ([], 0))
        with self.assertRaises(J.JoinsError):
            J.parse_swdi(b"summary\ncount,2\ntotalTimeInSeconds,0.0\n")

    def test_swdi_header_is_checked(self):
        with self.assertRaises(J.JoinsError):
            J.parse_swdi(b"ZTIME,LAT\n2025-06-15T20:10:00Z,47\n")

    def test_daily_missing_days_are_counted_not_zero(self):
        raw = ("station,day,max_wind_gust_kts,network\n"
               "LWT,2025-06-15,None,MT_ASOS\nLWT,2025-06-16,50.0,MT_ASOS\nLWT,2025-06-17,72.12503,MT_ASOS\n")
        out = J.parse_daily(raw.encode("utf-8"))
        self.assertEqual(out["missing"], 1)
        self.assertEqual(out["days"], [(date(2025, 6, 16), 50.0), (date(2025, 6, 17), 72.12503)])

    def test_station_units_and_thresholds(self):
        self.assertEqual(J.station_day_row(date(2025, 6, 17), 72.12503), [hail.day_index(date(2025, 6, 17)), 83, 72])
        self.assertEqual(J.station_day_row(date(2025, 6, 16), 50.0)[1:], [58, 50])
        self.assertEqual(J.station_day_row(date(2025, 6, 16), 56.5)[1:], [65, 57])     # D18: whole knots, half up
        self.assertEqual(J.station_day_kind(49.99), "below")
        self.assertEqual(J.station_day_kind(50.0), "keep")
        self.assertEqual(J.station_day_kind(129.99), "keep")
        self.assertEqual(J.station_day_kind(130.0), "dropped")

    def test_asos_station_list(self):
        doc = {"features": [
            {"properties": {"sid": "LWT", "sname": "Lewistown"}, "geometry": {"coordinates": [-109.4, 47.06]}},
            {"properties": {"sid": "BIL", "sname": "Billings"}, "geometry": {"coordinates": [-108.54, 45.81]}}]}
        out = J.parse_asos(json.dumps(doc).encode("utf-8"))
        self.assertEqual([s["id"] for s in out], ["BIL", "LWT"])
        self.assertEqual((out[1]["lat"], out[1]["lon"]), (47.06, -109.4))

    def test_warning_csv_times_are_utc(self):
        raw = ("wfo,utc_issue,utc_expire,utc_prodissue,utc_init_expire,phenomena,gtype,significance,eventid,status,"
               "ugc,area2d,utc_updated,hvtec_nwsli,hvtec_severity,hvtec_cause,hvtec_record,is_emergency,"
               "utc_polygon_begin,utc_polygon_end,windtag,hailtag,tornadotag,damagetag,product_id,fcster,vtec_year\n"
               "BYZ,2025-01-10 07:00,2025-01-11 08:17,2025-01-09 20:46,202501110300,HW,C,W,1,NEW,MTZ141,2003.9,"
               "2025-01-11 08:17,,,,,False,,,,,,,,,2025\n").encode("utf-8")
        rows = J.parse_ww_csv(raw)["rows"]
        self.assertEqual(rows[0]["issue"], utc(2025, 1, 10, 7, 0))
        self.assertEqual((rows[0]["ugc"], rows[0]["status"], rows[0]["phen"]), ("MTZ141", "NEW", "HW"))

    def test_zone_zip_name_is_the_newest_edition(self):
        page = (b'<a href="/source/gis/Shapefiles/WSOM/z_18mr25.zip">old</a>'
                b'<a href="/source/gis/Shapefiles/WSOM/z_16ap26.zip">new</a>')
        self.assertEqual(J.zone_zip_name(page), "z_16ap26.zip")

    def test_ncei_listing_names_pick_the_newest_creation(self):
        page = (b"StormEvents_details-ftp_v1.0_d2021_c20260101.csv.gz StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz"
                b" StormEvents_details-ftp_v1.0_d2022_c20260625.csv.gz")
        names = J.ncei_listing_names(page, [2021, 2022])
        self.assertEqual(names[2021], "StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz")
        self.assertEqual(names[2022], "StormEvents_details-ftp_v1.0_d2022_c20260625.csv.gz")


class GeometryTests(unittest.TestCase):
    def test_haversine_one_degree_of_latitude(self):
        self.assertAlmostEqual(float(J.haversine_km(47.0, -110.0, 48.0, -110.0)), 111.195, places=1)

    def test_five_mile_and_two_mile_limits(self):
        south, north, west, east = J.tile_bounds(79, 198)
        self.assertTrue(south < hail.cell_centre(*GATE)[0] < north)
        self.assertTrue(west < hail.cell_centre(*GATE)[1] < east)
        for miles, inside in ((4.9, True), (5.1, False)):
            lat = north + miles * J.MILE_KM / 111.195
            dist = float(J.rect_distance_km(lat, -110.1, south, north, west, east)) / J.MILE_KM
            self.assertEqual(dist <= J.REPORT_MILES, inside, (miles, dist))
        lat = north + 2.9 * J.MILE_KM / 111.195
        self.assertLessEqual(float(J.rect_distance_km(lat, -110.1, south, north, west, east)) / J.MILE_KM, 3.0)

    def test_point_inside_the_tile_is_distance_zero(self):
        south, north, west, east = J.tile_bounds(79, 198)
        self.assertEqual(float(J.rect_distance_km(47.05, -110.15, south, north, west, east)), 0.0)

    def test_tile_bounds_hold_the_gate_cell(self):
        south, north, west, east = J.tile_bounds(*GATE_TILE_RC)
        lat, lon = hail.cell_centre(*GATE)
        self.assertTrue(south < lat < north and west < lon < east)

    def test_points_in_rings_square_hole_and_parts(self):
        np = J._np()
        outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]
        lon = np.array([1.0, 5.0, 11.0, 9.0])
        lat = np.array([1.0, 5.0, 5.0, 9.0])
        self.assertEqual(J.points_in_rings(lon, lat, [outer]).tolist(), [True, True, False, True])
        self.assertEqual(J.points_in_rings(lon, lat, [outer, hole]).tolist(), [True, False, False, True])
        far = np.array([20.0])
        self.assertEqual(J.points_in_rings(far, np.array([20.0]), [outer]).tolist(), [False])

    def test_cover_bits_are_cell_keys_and_25_hex_digits(self):
        self.assertEqual(J.cover_hex([0]), "0" * 24 + "1")
        top = J.cover_hex([99])
        self.assertEqual(len(top), 25)
        self.assertEqual(top, "8" + "0" * 24)
        self.assertTrue(J.cover_has(top, 99))
        self.assertFalse(J.cover_has(top, 98))
        rng = random.Random(5)
        for _ in range(20):
            keys = sorted(rng.sample(range(100), rng.randint(1, 40)))
            cover = J.cover_hex(keys)
            self.assertEqual(len(cover), 25)
            self.assertEqual([k for k in range(100) if J.cover_has(cover, k)], keys)

    def test_compass_and_bearing(self):
        self.assertEqual(J.compass(0.0), "N")
        self.assertEqual(J.compass(90.0), "E")
        self.assertEqual(J.compass(225.0), "SW")
        self.assertEqual(J.compass(359.0), "N")
        self.assertEqual(J.compass(J.bearing_deg(47.0, -110.0, 47.5, -110.0)), "N")


class TimeTests(unittest.TestCase):
    def test_montana_clock_changes_in_2025(self):
        pairs = dict(J.montana_transitions(2025, 2025))
        self.assertEqual(pairs.get("2025-03-09T09:00Z"), "MDT")
        self.assertEqual(pairs.get("2025-11-02T08:00Z"), "MST")

    def test_clock_text_and_spc_day(self):
        self.assertEqual(J.fmt_clock(utc(2025, 6, 15, 20, 10)), "2:10 pm MDT")
        self.assertEqual(J.fmt_clock(utc(2025, 1, 15, 20, 10)), "1:10 pm MST")
        self.assertEqual(J.fmt_clock(utc(2025, 6, 15, 0, 5)), "6:05 pm MDT")
        self.assertEqual(J.spc_day(utc(2025, 6, 16, 0, 30)), date(2025, 6, 15))
        self.assertEqual(J.spc_day(utc(2025, 6, 16, 12, 0)), date(2025, 6, 16))

    def test_row_time_round_trip(self):
        d = hail.day_index(date(2025, 6, 15))
        self.assertEqual(J.utc_from_row(d, 2010), utc(2025, 6, 15, 20, 10))
        self.assertEqual(J.hhmm(utc(2025, 6, 15, 20, 10)), 2010)


def _index(parts=None, reasons=None, partial=None) -> dict:
    parts = parts or {p: "loaded" for p in J.PARTS}
    block = {"lags": {"ncei": "2026-06-30", "swdi": "2026-10-14", "warnings": "2026-09-14"}, "parts": parts,
             "reasons": reasons or {}, "partial": partial or {}, "types": {"H": "hail", "G": "tstm wnd gst"},
             "zone_names": {"MTZ313": "Judith Basin County"}, "station_days_by_year": {}}
    return {"format": "hail-store-v1", "as_of": "2026-10-16", "window": ["2021-10-17", "2026-10-16"],
            "joins": block}


def _cell_doc(**extra) -> dict:
    doc = {"f": J.FORMAT, "r": GATE_TILE_RC[0], "c": GATE_TILE_RC[1], "d0": "2020-01-01", "reports": [],
           "records": [], "detections": [], "warnings": [], "zones": {}, "stations": []}
    doc.update(extra)
    return doc


class JoinRuleTests(unittest.TestCase):
    def setUp(self):
        self.centre = hail.cell_centre(*GATE)
        self.day = hail.day_index(date(2025, 6, 15))

    def _section(self, sections, sid):
        return next(s for s in sections if s["id"] == sid)

    def _describe(self, inline, store_dir=None, index=None):
        doc, events = store_form(inline)
        return J.describe_joins(index or _index(), doc, *GATE, store_dir=store_dir, events=events)

    def test_reports_within_five_miles_newest_first_and_the_remark_line(self):
        # the gate cell's centre, a report 4.9 miles due north (in), one 5.1 miles north (out), and one at the centre
        north = self.centre[0] + 4.9 * J.MILE_KM / 111.195
        far = self.centre[0] + 5.1 * J.MILE_KM / 111.195
        doc = _cell_doc(reports=[
            [self.day, 2010, round(self.centre[0], 4), round(self.centre[1], 4), "H", "1.75", "in", "E", "Public",
             "Benchland", "Public caller updated with golf ball sized hail."],
            [self.day, 900, round(north, 4), round(self.centre[1], 4), "H", "1.00", "in", "M", "Trained spotter", "", ""],
            [self.day, 1200, round(far, 4), round(self.centre[1], 4), "G", "58", "mph", "M", "Mesonet", "", ""],
        ])
        out = self._describe(doc)
        sec = self._section(out["sections"], "reports")
        self.assertEqual(len(sec["rows"]), 2, sec["rows"])
        self.assertIn("2:10 pm MDT: hail, 1.75 in (estimated), Public, 0.0 mi", sec["rows"][0]["text"])
        self.assertEqual(sec["rows"][0]["remark"],
                         "Remark, as written: \u201cPublic caller updated with golf ball sized hail.\u201d")
        self.assertIn("4.9 mi N", sec["rows"][1]["text"])
        self.assertIn("1.00 in (measured)", sec["rows"][1]["text"])
        self.assertEqual(sec["lead"], "2 NWS local storm reports within 5 miles between Oct 17, 2021 and Oct 16, 2026.")

    def test_empty_reports_say_not_a_complete_record(self):
        out = self._describe(_cell_doc())
        sec = self._section(out["sections"], "reports")
        self.assertEqual(sec["rows"], [])
        self.assertIn("they are not a complete record", sec["lead"])
        for section in out["sections"]:
            for text in [section["lead"], section["what"]] + [r["text"] for r in section["rows"]]:
                if text:
                    check_words(self, text)

    def test_cover_decides_which_warnings_cover_this_spot(self):
        def warning(key, begin, end, office="TFX"):
            item = {"k": "SV", "b": begin, "e": end, "o": office,
                    "tags": {"hail_in": 1.0, "wind_mph": 60.0, "tornado": None, "damage": "CONSIDERABLE"}}
            return item, J.cover_hex([key])
        doc = _cell_doc(warnings=[warning(GATE_KEY, "2025-06-15T00:26Z", "2025-06-15T01:08Z"),
                                  warning((GATE_KEY + 1) % 100, "2025-06-15T05:39Z", "2025-06-15T05:59Z")])
        out = self._describe(doc)
        sec = self._section(out["sections"], "warnings")
        self.assertEqual(len(sec["rows"]), 1)
        text = sec["rows"][0]["text"]
        self.assertEqual(text, "Warning: Jun 14, 2025 6:26 pm MDT to 7:08 pm MDT, issuance polygon in effect: Severe "
                               "thunderstorm warning, TFX; tags: hail 1.00 in, wind 60 mph, NWS damage threat tag: "
                               "considerable")
        self.assertIn("Tags are the forecast threat at issue time, not what fell.", sec["what"])
        check_words(self, text)

    def test_warning_with_no_tags_says_none_stated(self):
        doc = _cell_doc(warnings=[({"k": "TO", "b": "2025-06-15T05:39Z", "e": "2025-06-15T05:59Z", "o": "BYZ",
                                    "tags": {"hail_in": None, "wind_mph": None, "tornado": "OBSERVED",
                                             "damage": None}}, J.cover_hex([GATE_KEY]))])
        out = self._describe(doc)
        self.assertIn("tags: tornado observed", self._section(out["sections"], "warnings")["rows"][0]["text"])
        doc["warnings"][0][0]["tags"]["tornado"] = None
        out = self._describe(doc)
        self.assertIn("tags: none stated", self._section(out["sections"], "warnings")["rows"][0]["text"])

    def test_detections_group_by_spc_day(self):
        doc = _cell_doc(detections=[
            [self.day, 2010, 47.03, -110.13, 175],
            [self.day + 1, 30, 47.03, -110.13, 100],       # 00:30 UTC on 16 June is the SPC day of 15 June
            [self.day, 1300, 47.03, -110.13, 50],
            [self.day, 1300, 48.5, -110.13, 300],          # far away: not within two miles
        ])
        out = self._describe(doc)
        rows = self._section(out["sections"], "detections")["rows"]
        self.assertEqual([r["text"] for r in rows], ["Detection: Jun 15, 2025: 3 detections, largest 1.75 in"])
        check_words(self, rows[0]["text"])

    def test_zone_products_and_no_zone_sentences(self):
        doc = _cell_doc(zones={"MTZ313": [GATE_KEY]})
        out = self._describe(doc)
        sec = self._section(out["sections"], "zones")
        self.assertEqual(sec["id"], "zones")
        self.assertEqual(sec["heading"], "Zone products for Judith Basin County (MTZ313)")
        self.assertIn("No product for zone Judith Basin County (MTZ313) between", sec["lead"])
        self.assertIn("That does not mean the weather was calm.", sec["lead"])
        self.assertNotIn("in the archive", sec["lead"])          # no claim that a missing product is absent
        self.assertIn("These covered the whole zone, not this spot alone.", sec["what"])
        none = self._describe(_cell_doc())
        self.assertEqual(self._section(none["sections"], "zones")["lead"],
                         "The forecast zone for this cell could not be determined.")
        self.assertEqual(self._section(none["sections"], "zones")["heading"], "Zone products")

    def test_zone_product_rows_from_the_zone_file(self):
        root = Path(tempfile.mkdtemp(prefix="joins-test-zone-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "z" / "MTZ313.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [],
                "events": [{"k": "HW", "s": "W", "b": "2025-01-10T07:00Z", "e": "2025-01-11T08:17Z", "o": "TFX"},
                           {"k": "HW", "s": "W", "b": "2025-03-24T17:00Z", "e": "2025-03-24T19:00Z", "o": "TFX"}]}))
            doc = _cell_doc(zones={"MTZ313": [GATE_KEY]})
            out = self._describe(doc, store_dir=root)
            rows = self._section(out["sections"], "zones")["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["text"], "Zone product: High wind warning: Jan 10, 2025 12:00 am MST to Jan 11, "
                                              "2025 1:17 am MST; Mar 24, 2025 11:00 am MDT to 1:00 pm MDT")
        finally:
            shutil.rmtree(root)

    def test_station_rows_and_the_implausible_count(self):
        root = Path(tempfile.mkdtemp(prefix="joins-test-station-"))
        try:
            (root / "hail" / "s").mkdir(parents=True)
            day = hail.day_index(date(2025, 6, 16))
            (root / "hail" / "s" / "LWT.json").write_text(json.dumps({
                "f": J.STATION_FORMAT, "id": "LWT", "name": "Lewistown", "lat": 47.06, "lon": -109.4,
                "days": [[day, 58, 50]], "dropped": 3}))
            doc = _cell_doc(stations=[{"id": "LWT", "name": "Lewistown", "lat": 47.06, "lon": -109.4, "miles": 12.3}])
            out = self._describe(doc, store_dir=root)
            sec = self._section(out["sections"], "stations")
            self.assertEqual(sec["rows"][0]["text"], "Station: Jun 16, 2025: 50 kt (58 mph) at Lewistown, about 12.3 "
                                                 "miles away")
            self.assertIn("3 readings of 130 kt or more were left out as implausible.", sec["lines"])
            self.assertIn("A station reading is at the airport, not at this address.", sec["what"])
        finally:
            shutil.rmtree(root)

    def test_unavailable_part_says_data_unavailable_not_all_clear(self):
        index = _index(parts={**{p: "loaded" for p in J.PARTS}, "warnings": "unavailable"},
                       reasons={"warnings": "the file was in an unexpected format"})
        out = self._describe(_cell_doc(), index=index)
        sec = self._section(out["sections"], "warnings")
        self.assertEqual(sec["unavailable"], "Warnings could not be loaded in this update; that is not the same as no "
                                             "warning.")
        self.assertEqual(sec["rows"], [])
        check_words(self, sec["unavailable"])

    def test_partial_part_names_the_periods(self):
        index = _index(parts={**{p: "loaded" for p in J.PARTS}, "reports": "partial"},
                       reasons={"reports": "the source did not answer"}, partial={"reports": ["2025-03"]})
        out = self._describe(_cell_doc(), index=index)
        self.assertEqual(self._section(out["sections"], "reports")["unavailable"],
                         "Data unavailable for some periods: NWS local storm reports did not load for 2025-03 "
                         "(the source did not answer). This is not an all-clear.")

    def test_six_sections_in_order_and_every_sentence_passes_the_words_check(self):
        out = self._describe(_cell_doc())
        self.assertEqual([s["id"] for s in out["sections"]],
                         ["reports", "records", "detections", "warnings", "zones", "stations"])
        for section in out["sections"]:
            check_words(self, section["what"])
            if section["lead"]:
                check_words(self, section["lead"])
            for line in section["lines"]:
                check_words(self, line)


class ZoneProductListTests(unittest.TestCase):
    """D34, D35: the zone products are the ten the decision names: the nine of D34 and flood watches (FA.A). FL.W is a
    polygon product, so it is not a zone product, and no zone product name calls a flood warning a zone product."""

    def test_the_zone_products_are_the_ten_the_decision_names(self):
        self.assertEqual(len(J.ZONE_PRODUCTS), 10)
        self.assertEqual(set(J.ZONE_PRODUCTS), D35_ZONE_PRODUCTS)

    def test_the_flood_warning_is_not_a_zone_product_and_has_no_product_name(self):
        self.assertNotIn(("FL", "W"), J.ZONE_PRODUCTS)
        self.assertNotIn("FL.W", J.PRODUCT_NAMES)

    def test_the_flood_watch_is_a_zone_product_named_flood_watch(self):
        self.assertIn(("FA", "A"), J.ZONE_PRODUCTS)
        self.assertEqual(J.PRODUCT_NAMES["FA.A"], "Flood watch")

    def test_every_zone_product_has_a_name_and_no_zone_product_is_a_flood_warning(self):
        for phen, sig in J.ZONE_PRODUCTS:
            name = J.PRODUCT_NAMES[f"{phen}.{sig}"]
            self.assertNotIn("flood warning", name.lower(), name)
            if "flood" in name.lower():
                self.assertEqual(name, "Flood watch")

    def test_the_browser_product_names_are_the_zone_products(self):
        index = _index()
        index["joins"].update({"state": "loaded", "cover": "x", "shapes": {}, "montana_time": [], "compare": {},
                               "built_at": "x", "station_days_by_year": {}})
        products = J.map_data_joins(index)["products"]
        self.assertNotIn("FL.W", products)
        self.assertEqual(products["FA.A"], "Flood watch")
        for phen, sig in J.ZONE_PRODUCTS:
            self.assertIn(f"{phen}.{sig}", products)

    def test_no_zone_word_calls_a_flood_warning_a_zone_product(self):
        for key, text in J.WORDS_JOINS.items():
            if isinstance(text, str) and "zone" in key:
                self.assertNotIn("flood warning", text.lower(), key)

    def test_the_zone_contract_row_lists_the_ten_products_and_says_the_flood_warning_is_not_joined(self):
        row = src.CONTRACTS["nws_zone_products"]
        request = " ".join(row["request"].split())
        self.assertEqual(set(re.findall(r"\b[A-Z]{2}\.[A-Z]\b", request)), {f"{p}.{s}" for p, s in D35_ZONE_PRODUCTS})
        self.assertIn("FA.A (flood watch)", request)
        self.assertNotIn("flood warning", request.lower())
        missing = " ".join(row["missing"].split())
        self.assertIn("FL.W (flood warning) is a polygon product and is not joined in this version.", missing)
        self.assertIn("county-only flood watches are not joined in this version", missing)

    def test_the_records_contract_row_names_the_points_joined_and_the_points_not_joined(self):
        request = " ".join(src.CONTRACTS["ncei_storm_events"]["request"].split())
        self.assertIn("Hail and Thunderstorm Wind rows with coordinates within 5 miles", request)
        self.assertIn("Not joined in this version: tornado, flood, flash flood, heavy rain, funnel cloud, lightning and "
                      "debris flow points", request)


class ZoneAssignmentTests(unittest.TestCase):
    def test_cells_inside_a_zone_get_its_code(self):
        zone = {"zone": "MTZ313", "name": "Test", "rings": [[(-110.2, 46.9), (-110.0, 46.9), (-110.0, 47.1),
                                                          (-110.2, 47.1), (-110.2, 46.9)]]}
        cells = [(GATE[0], GATE[1], *hail.cell_centre(*GATE)),
                 (100, 100, *hail.cell_centre(100, 100))]
        out = J.assign_zones(cells, [zone])
        self.assertEqual(out, {GATE: "MTZ313"})

    def test_first_zone_in_code_order_wins_an_overlap(self):
        square = [(-110.2, 46.9), (-110.0, 46.9), (-110.0, 47.1), (-110.2, 47.1), (-110.2, 46.9)]
        zones = [{"zone": "MTZ001", "name": "a", "rings": [square]}, {"zone": "MTZ002", "name": "b", "rings": [square]}]
        out = J.assign_zones([(GATE[0], GATE[1], *hail.cell_centre(*GATE))], zones)
        self.assertEqual(out[GATE], "MTZ001")


class WordsTests(unittest.TestCase):
    def test_no_forbidden_term_in_any_word(self):
        for key, text in J.WORDS_JOINS.items():
            if isinstance(text, str):
                check_words(self, text)
        self.assertIn("damage threat", J.WORDS_JOINS["tag_damage"])

    def test_the_brief_sentences_are_present(self):
        words = J.WORDS_JOINS
        self.assertEqual(words["reports_lead_none"], "No NWS local storm report within 5 miles in these five years. "
                                                     "Reports are what people sent the NWS; they are not a complete record.")
        self.assertEqual(words["records_lag"], "NCEI's database runs to {newest}.")
        self.assertIn("A detection is the radar algorithm's hail signature for a storm cell, not hail on the ground.",
                      words["detections_what"])
        self.assertIn("These covered the whole zone, not this spot alone.", words["zones_what"])
        self.assertIn("A station reading is at the airport, not at this address.", words["stations_what"])
        self.assertEqual(words["unavailable"], "{part} could not be loaded in this update; that is not the same as no "
                                               "{one}.")

    def test_the_records_words_name_the_points_joined_and_the_points_not_joined(self):
        text = " ".join(J.WORDS_JOINS["records_what"].split())
        self.assertIn("This list has hail and thunderstorm wind points within 5 miles.", text)
        self.assertIn("Zone-coded records (high wind, winter storm, heavy snow and the other events NCEI codes to a forecast "
                      "zone) are for the spot's forecast zone", text)
        self.assertIn("NCEI county-coded points of tornado, flood, flash flood, heavy rain, funnel cloud, lightning "
                      "and debris flow are not joined in this version; the NWS local storm reports of those kinds are "
                      "joined as reports.", text)

    def test_map_block_carries_the_templates_radii_and_units(self):
        index = _index()
        index["joins"].update({"state": "loaded", "cover": "x", "shapes": {}, "montana_time": [],
                               "compare": {}, "built_at": "x", "station_days_by_year": {}})
        block = J.map_data_joins(index)
        self.assertEqual(block["radius_miles"], {"report": 5.0, "detection": 2.0, "station": 40.0})
        self.assertEqual(block["words"]["reports_lead_none"], J.WORDS_JOINS["reports_lead_none"])
        self.assertEqual(block["station_mph"], 58)
        self.assertEqual(block["km_per_mile"], 1.609344)


class FakeFetcher(J.Fetcher):
    """A Fetcher that never touches the network: _download answers from a function of (url, params)."""

    def __init__(self, cache_dir, ledger, responder, **kw):
        super().__init__(cache_dir, ledger, procs=1, **kw)
        self.responder = responder
        self.requests = []

    def _pace(self):
        return None

    def _download(self, url, params=None):
        self.requests.append((url, dict(params or {})))
        data = self.responder(url, params or {})
        if data is None:
            return None, 503, "HTTP 503"
        return data, 200, None


def canned(url, params):
    if url == J.NWS_GIS_URL:
        return b'<a href="/source/gis/Shapefiles/WSOM/z_16ap26.zip">z</a>'
    if url == J.NWS_FIRE_URL:
        return b'<a href="/source/gis/Shapefiles/WSOM/fz16ap26.zip">fire</a>'
    if url == J.ASOS_URL:
        return json.dumps({"features": [
            {"properties": {"sid": "LWT", "sname": "Lewistown"}, "geometry": {"coordinates": [-109.4, 47.06]}},
            {"properties": {"sid": "BIL", "sname": "Billings"}, "geometry": {"coordinates": [-108.54, 45.81]}}]}).encode()
    if url == J.NCEI_DIR:
        return b"".join(f"StormEvents_details-ftp_v1.0_d{y}_c20260323.csv.gz ".encode() for y in range(2021, 2027))
    if url.startswith(J.NCEI_DIR):
        year = int(re.search(r"_d(\d{4})_", url).group(1))
        rows = []
        if year == 2025:
            rows.append({"EVENT_TYPE": "Hail", "CZ_TYPE": "C", "CZ_FIPS": "45", "BEGIN_DATE_TIME": "15-JUN-25 13:10:00",
                         "BEGIN_LAT": "47.08", "BEGIN_LON": "-110.02", "MAGNITUDE": "1.75", "SOURCE": "PUBLIC",
                         "BEGIN_LOCATION": "BENCHLAND"})
        buf = io.StringIO()
        fields = ["EVENT_TYPE", "STATE", "BEGIN_DATE_TIME", "CZ_TYPE", "CZ_FIPS", "BEGIN_LAT", "BEGIN_LON",
                  "MAGNITUDE", "MAGNITUDE_TYPE", "SOURCE", "CZ_TIMEZONE", "BEGIN_LOCATION", "CZ_NAME", "WFO"]
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            base = {f: "" for f in fields}
            base.update({"STATE": "MONTANA", "CZ_TIMEZONE": "MST-7", "WFO": "TFX"})
            base.update(row)
            writer.writerow(base)
        return gzip.compress(buf.getvalue().encode("utf-8"))
    if url == J.LSR_URL:
        if params.get("sts", "").startswith("2025-06"):
            return lsr_csv([BENCHLAND_LSR])
        return lsr_csv([])
    if url.startswith(J.SWDI_URL.split("{")[0]):
        if "20250601" in url:
            return (b"ZTIME,WSR_ID,CELL_ID,PROB,SEVPROB,MAXSIZE,LAT,LON\n"
                    b"2025-06-15T20:10:00Z,KTFX,A1,100,40,1.75,47.08,-110.02\ncount,1\n")
        return b"ZTIME,WSR_ID,CELL_ID,PROB,SEVPROB,MAXSIZE,LAT,LON\ncount,0\n"
    if url == J.WW_URL and params.get("accept") == "shapefile":
        return b"not a zip file"
    if url == J.WW_URL and params.get("accept") == "csv":
        return (b"wfo,utc_issue,utc_expire,utc_prodissue,utc_init_expire,phenomena,gtype,significance,eventid,"
                b"status,ugc,area2d,utc_updated,hvtec_nwsli,hvtec_severity,hvtec_cause,hvtec_record,is_emergency,"
                b"utc_polygon_begin,utc_polygon_end,windtag,hailtag,tornadotag,damagetag,product_id,fcster,vtec_year\n")
    if url.startswith(J.NWS_BASE_URL):
        return b"not a zip file"
    if url == J.DAILY_URL:
        # the IEM answers for the year asked: the 2025 rows only when year1 is 2025
        if params.get("stations") == "LWT" and params.get("year1") == "2025":
            return (b"station,day,max_wind_gust_kts,network\nLWT,2025-06-15,None,MT_ASOS\n"
                    b"LWT,2025-06-16,50.0,MT_ASOS\nLWT,2025-06-17,140.0,MT_ASOS\n")
        return b"station,day,max_wind_gust_kts,network\n"
    return None


class BuildTests(unittest.TestCase):
    """The whole joins build on the committed SAMPLE store (three tiles), with canned sources and no network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="joins-test-build-"))
        self.store = self.tmp / "store"
        hail.fixture_store(self.store)          # the B1 SAMPLE store: its own shards, index and manifest
        self.fetcher = FakeFetcher(self.tmp / "cache", self.store / "ledger" / "joins.jsonl", canned)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_build_writes_j_z_s_and_marks_the_unavailable_parts(self):
        block = J.build(self.store, self.tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=self.fetcher,
                        log=lambda text: None)
        self.assertEqual(block["parts"]["reports"], "loaded")
        self.assertEqual(block["parts"]["records"], "loaded")
        self.assertEqual(block["parts"]["warnings"], "unavailable")   # the shapefile is not a zip: refused
        self.assertEqual(block["parts"]["zones"], "unavailable")
        self.assertEqual(block["state"], "partial")
        self.assertEqual(block["parts"]["stations"], "loaded")
        events = json.loads((self.store / "hail" / "j" / J.EVENTS_NAME).read_text())
        self.assertEqual(events["f"], J.EVENTS_FORMAT)
        doc = json.loads((self.store / "hail" / "j" / f"{GATE_TILE}.json").read_text())
        self.assertIn("warnings", doc["missing"])
        bench = [events["reports"][r] for r in doc["reports"] if events["reports"][r][4] == "H"
                 and events["reports"][r][5] == "1.75"]
        self.assertEqual(len(bench), 1)
        self.assertEqual(bench[0][:4], [hail.day_index(date(2025, 6, 15)), 2010, 47.08, -110.02])
        self.assertTrue(any(events["records"][r][5] == "1.75" for r in doc["records"]))
        self.assertTrue(all(isinstance(r, int) for r in doc["reports"] + doc["records"]))
        self.assertEqual(list((self.store / "hail" / "z").glob("MTZ*.json")), [])   # no zone map, no zone files
        self.assertTrue((self.store / "hail" / "s" / "LWT.json").is_file())
        station = json.loads((self.store / "hail" / "s" / "LWT.json").read_text())
        self.assertEqual(station["days"], [[hail.day_index(date(2025, 6, 16)), 58, 50]])
        self.assertEqual(station["dropped"], 1)
        self.assertTrue((self.store / "ledger" / "joins.jsonl").is_file())
        self.assertIn("joins", json.loads((self.store / "hail" / "index.json").read_text()))

    def test_the_build_asks_for_the_ten_zone_products_and_not_the_flood_warning(self):
        J.build(self.store, self.tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=self.fetcher,
                log=lambda text: None)
        asked = {(params["phenomena[]"], params["significance[]"]) for url, params in self.fetcher.requests
                 if url == J.WW_URL and params.get("accept") == "csv"}
        self.assertTrue(asked)
        self.assertEqual(asked, D35_ZONE_PRODUCTS)
        self.assertNotIn(("FL", "W"), asked)

    def test_verify_passes_and_reports_the_gate_row(self):
        J.build(self.store, self.tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=self.fetcher,
                log=lambda text: None)
        result = J.verify(self.store)
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["gate"]["report_cell"], [792, 1998])     # D1: the report is on Benchland's cell
        self.assertEqual(result["gate"]["lsr_row"]["in"], "1.75")
        self.assertEqual(result["gate"]["lsr_row"]["utc"], "2025-06-15T20:10Z")
        self.assertEqual(result["gate"]["ncei_hail_row"]["in"], "1.75")
        self.assertLessEqual(result["gate"]["lsr_row"]["miles_from_cell"], J.REPORT_MILES)
        self.assertEqual(result["gate"]["lsr_row"]["miles_from_cell"], 0.42)
        self.assertNotIn("miles_from_tile", result["gate"]["lsr_row"])

    def test_two_offline_builds_from_the_same_cache_are_byte_identical(self):
        # the first build fills the cache (a network build); the next two are offline, so each output is a function of
        # the cache alone (the brief's gate B2-8). An online build and an offline one differ in the reasons a failed
        # download gives (the offline reason is said as such), so the comparison is between the two offline builds.
        J.build(self.store, self.tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=self.fetcher,
                log=lambda text: None)
        outs = []
        for name in ("store2", "store3"):
            store = self.tmp / name
            hail.fixture_store(store)
            offline = FakeFetcher(self.tmp / "cache", store / "ledger" / "joins.jsonl", canned, offline=True)
            J.build(store, self.tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=offline,
                    log=lambda text: None)
            self.assertEqual(offline.requests, [])
            outs.append({p.relative_to(store).as_posix(): p.read_bytes()
                         for sub in ("j", "z", "s") for p in (store / "hail" / sub).rglob("*.json")})
        self.assertTrue(outs[0])
        self.assertEqual(set(outs[0]), set(outs[1]))
        self.assertTrue(all(outs[0][k] == outs[1][k] for k in outs[0]))


@unittest.skipUnless(HAVE_PYSHP, "pyshp is not installed (the daily job installs it)")
class ShapefileTests(unittest.TestCase):
    def test_zone_shapefile_round_trip(self):
        import zipfile
        import shapefile
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-shp-"))
        try:
            base = tmp / "z_01jn26"
            writer = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
            writer.field("STATE", "C", size=2)
            writer.field("ZONE", "C", size=3)
            writer.field("NAME", "C", size=40)
            writer.field("STATE_ZONE", "C", size=5)
            for n in range(12):     # the reader wants a full state's zones, so twelve squares
                west = -110.2 + n * 0.01
                square = [[west, 46.9], [west + 0.01, 46.9], [west + 0.01, 47.1], [west, 47.1], [west, 46.9]]
                writer.poly([square])
                writer.record("MT", f"{300 + n:03d}", "Judith Basin County" if n == 0 else f"Zone {n}", f"MT{300 + n}")
            writer.close()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for ext in (".shp", ".dbf", ".shx"):
                    zf.write(str(base) + ext, base.name + ext)
            zones = J.parse_zone_map(buf.getvalue())
            self.assertEqual(len(zones), 12)
            self.assertEqual(zones[0]["zone"], "MTZ300")
            self.assertEqual(zones[0]["name"], "Judith Basin County")
        finally:
            shutil.rmtree(tmp)


class FixtureTests(unittest.TestCase):
    def test_the_committed_sample_joins_verify_and_are_small(self):
        result = J.verify(FIXTURE)
        self.assertTrue(result["ok"], result["checks"])
        total = sum(p.stat().st_size for p in FIXTURE.rglob("*") if p.is_file())
        self.assertLess(total, 50 * 1024, total)

    @staticmethod
    def _edit_zone_file(root: Path, rel: str, events: list) -> None:
        """Appends events to a copied store's zone file and writes its new size and SHA-256 into the copy's manifest,
        so the copy still passes the manifest check. The committed fixture is not changed."""
        zone_file = root / "hail" / rel
        doc = json.loads(zone_file.read_text(encoding="utf-8"))
        doc["events"].extend(events)
        zone_file.write_text(json.dumps(doc), encoding="utf-8")
        data = zone_file.read_bytes()
        manifest_path = root / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][f"hail/{rel}"] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    def test_verify_exempts_a_cancelled_span_that_ends_at_or_before_its_begin(self):
        # D26 and D31: a cancelled or upgraded span may end at or before its begin (its end is the cancellation or
        # upgrade time); a span that no cancellation or upgrade ended may not, so the same span without the mark fails
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-verify-span-"))
        try:
            cases = (("cancelled", {"st": "cancelled"}, True), ("upgraded", {"st": "upgraded"}, True),
                     ("live", {}, False))
            for name, mark, passes in cases:
                root = tmp / name
                shutil.copytree(FIXTURE, root)
                span = {"k": "HW", "s": "W", "b": "2025-01-10T15:59Z", "e": "2025-01-10T09:00Z", "o": "TFX", **mark}
                self._edit_zone_file(root, "z/MTZ313.json", [span])
                result = J.verify(root)
                check = next(c for c in result["checks"] if c["name"].startswith("zone spans"))
                self.assertEqual(check["ok"], passes, check)
        finally:
            shutil.rmtree(tmp)

    def test_the_fixture_gate_cell_lists_the_reports_within_five_miles(self):
        index = hail.load_index(FIXTURE)
        doc = json.loads((FIXTURE / "hail" / "j" / f"{GATE_TILE}.json").read_text())
        out = J.describe_joins(index, doc, *GATE, store_dir=FIXTURE)
        reports = next(s for s in out["sections"] if s["id"] == "reports")
        # the Benchland 1.75 in report is 6.6 miles from this cell's centre: it is in the tile file, not on this sheet
        self.assertFalse(any("1.75 in" in r["text"] for r in reports["rows"]), reports["rows"][:3])
        self.assertTrue(any("1.00 in (estimated)" in r["text"] and "4." in r["text"] for r in reports["rows"]),
                        reports["rows"][:3])
        self.assertTrue(any(r[5] == "1.75" for r in json.loads(
            (FIXTURE / "hail" / "j" / J.EVENTS_NAME).read_text())["reports"]))
        records = next(s for s in out["sections"] if s["id"] == "records")
        self.assertTrue(records["rows"] is not None)
        for section in out["sections"]:
            check_words(self, section["what"])
            for row in section["rows"]:
                check_words(self, row["text"])

    def test_the_gate_day_fixture_has_a_zone_name(self):
        index = hail.load_index(FIXTURE)
        doc = json.loads((FIXTURE / "hail" / "j" / f"{GATE_TILE}.json").read_text())
        zone = J._zone_for_key(doc, GATE_KEY)
        self.assertIsNotNone(zone)
        self.assertIn(zone, index["joins"]["zone_names"])


# ---------------------------------------------------------------- fixes after review round 1 (the B2 fixer)

SQUARE_313 = [(-110.2, 46.9), (-110.0, 46.9), (-110.0, 47.1), (-110.2, 47.1), (-110.2, 46.9)]
ZONE_313 = {"zone": "MTZ313", "name": "Judith Basin County", "rings": [SQUARE_313]}
ZONE_060 = {"zone": "MTZ060", "name": "Southwest Phillips", "rings": [[(-108.8, 47.9), (-108.6, 47.9), (-108.6, 48.1),
                                                                      (-108.8, 48.1), (-108.8, 47.9)]]}
WINDOW = (utc(2021, 10, 17, 12), utc(2026, 10, 17, 12))


def zone_row(ugc, phen, status, issue, expire, eventid="1", wfo="TFX", sig="W", gtype="C", vtec_year="2025"):
    return {"ugc": ugc, "phen": phen, "sig": sig, "wfo": wfo, "eventid": eventid, "vtec_year": vtec_year,
            "gtype": gtype, "status": status, "issue": issue, "expire": expire}


def zone_ctx(rows, zone_map=None, fire_map=None):
    ctx = J.Context()
    ctx.zone_map = [ZONE_313] if zone_map is None else zone_map
    ctx.fire_map = fire_map
    ctx.zone_rows = rows
    return ctx


class LabelTests(unittest.TestCase):
    """D3: every row starts with its kind label, and an NCEI point record never starts with "Report:" (data-8,
    rules-2, job-16)."""

    def test_every_row_of_every_section_starts_with_its_label(self):
        centre = hail.cell_centre(*GATE)
        day = hail.day_index(date(2025, 6, 15))
        doc = _cell_doc(
            reports=[[day, 2010, round(centre[0], 4), round(centre[1], 4), "H", "1.75", "in", "E", "Public",
                      "Benchland", ""]],
            records=[[day, 2010, 47.08, -110.02, "hail", "1.75", "in", "", "Public", "Benchland", "", None, None]],
            detections=[[day, 2010, 47.03, -110.13, 175]],
            warnings=[({"k": "SV", "b": "2025-06-15T19:53Z", "e": "2025-06-15T20:02Z", "o": "TFX",
                        "tags": {"hail_in": 1.0, "wind_mph": None, "tornado": None, "damage": None}},
                       J.cover_hex([GATE_KEY]))],
            zones={"MTZ313": [GATE_KEY]},
            stations=[{"id": "LWT", "name": "Lewistown", "lat": 47.06, "lon": -109.4, "miles": 12.3}])
        root = Path(tempfile.mkdtemp(prefix="joins-test-label-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "s").mkdir(parents=True)
            (root / "hail" / "z" / "MTZ313.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County",
                "events": [{"k": "HW", "s": "W", "b": "2025-01-10T07:00Z", "e": "2025-01-11T08:17Z", "o": "TFX"}],
                "records": [[day, 1200, None, None, "high wind", "50", "kt", "", "Mesonet", "KOOTENAI", "", 58, 50]]}))
            (root / "hail" / "s" / "LWT.json").write_text(json.dumps({
                "f": J.STATION_FORMAT, "id": "LWT", "name": "Lewistown", "lat": 47.06, "lon": -109.4,
                "days": [[hail.day_index(date(2025, 6, 16)), 58, 50]], "dropped": 0}))
            out = self._describe(doc, store_dir=root)
        finally:
            shutil.rmtree(root)
        labels = {"reports": "Report: ", "records": "Record: ", "detections": "Detection: ",
                  "warnings": "Warning: ", "zones": "Zone product: ", "stations": "Station: "}
        for section in out["sections"]:
            self.assertTrue(section["rows"], section["id"])
            for row in section["rows"]:
                self.assertTrue(row["text"].startswith(labels[section["id"]]), (section["id"], row["text"]))
                if section["id"] == "records":
                    self.assertFalse(row["text"].startswith("Report:"), row["text"])
        for section in out["sections"]:
            check_words(self, section["what"])

    def _describe(self, inline, store_dir=None):
        doc, events = store_form(inline)
        return J.describe_joins(_index(), doc, *GATE, store_dir=store_dir, events=events)


class GateRegressionTests(unittest.TestCase):
    """D1 and B2 gate 1: the report and the record come from the report cell, at the gate's hour on the gate's day, and
    the row chosen is the Benchland one even when the same tile holds another 1.75 in hail row that day (data-1)."""

    def setUp(self):
        self.report_cell = (792, 1998)
        self.report_tile = hail.tile_name(79, 199)
        self.day = hail.day_index(date(2025, 6, 15))

    def _gate(self, reports, records=()):
        events = {"f": J.EVENTS_FORMAT, "d0": "2020-01-01", "reports": [list(r) for r in reports],
                  "records": [list(r) for r in records], "warnings": []}
        report_doc = {"reports": list(range(len(reports))), "records": list(range(len(records)))}
        gate_doc = {"warnings": [], "zones": {}}
        index = _index()
        return J._benchland_gate(Path("/nonexistent"), index, gate_doc, report_doc, events)

    def test_the_benchland_row_is_chosen_over_another_hail_row_the_same_day(self):
        benchland = [self.day, 2010, 47.08, -110.02, "H", "1.75", "in", "E", "Public", "Benchland", "golf ball"]
        other_hour = [self.day, 1600, 47.09, -110.0, "H", "1.75", "in", "E", "Public", "Hobson", "other"]
        gate = self._gate([other_hour, benchland])
        self.assertEqual(gate["lsr_row"]["utc"], "2025-06-15T20:10Z")
        self.assertEqual(gate["lsr_row"]["remark"], "golf ball")
        self.assertEqual(gate["report_cell"], [792, 1998])

    def test_a_row_on_the_spc_day_before_at_the_same_clock_time_is_not_chosen(self):
        early = [self.day - 1, 2010, 47.08, -110.02, "H", "1.75", "in", "E", "Public", "Benchland", ""]
        gate = self._gate([early])
        self.assertIsNone(gate["lsr_row"])

    def test_distance_is_from_the_report_cell_centre(self):
        gate = self._gate([[self.day, 2010, 47.08, -110.02, "H", "1.75", "in", "E", "Public", "Benchland", ""]])
        centre = hail.cell_centre(*self.report_cell)
        expect = float(J.haversine_km(centre[0], centre[1], 47.08, -110.02)) / J.MILE_KM
        self.assertAlmostEqual(gate["lsr_row"]["miles_from_cell"], round(expect, 2), places=2)
        self.assertLess(gate["lsr_row"]["miles_from_cell"], 1.0)


class ZoneSpanTests(unittest.TestCase):
    """D6, D16, D26 and D31: an event begins at its earliest NEW or CON row, and has no begin ("start not recorded")
    when it has none. It ends at its earliest cancellation (CAN) or upgrade (UPG) row's expire time when one exists,
    even when that is at or before the begin (D26; the sheet then says "cancelled at {time}" or "upgraded at {time}").
    The status of that row names the end. Otherwise it ends at the latest expiry of its other rows, and it has no end
    ("end not recorded") when there is no such time and no expiry after the begin (D6)."""

    def test_a_cancellation_only_group_begins_at_the_issue_its_rows_carry_and_ends_at_its_cancellation(self):
        rows = [zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 15, 59), utc(2025, 1, 10, 23, 56), eventid="2")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        event = out["MTZ313"][0]
        self.assertEqual(event["b"], "2025-01-10T15:59Z")
        self.assertNotIn("seen", event)
        self.assertEqual(event["e"], "2025-01-10T23:56Z")
        self.assertEqual(event["st"], "cancelled")

    def test_the_begin_is_the_earliest_new_or_con_row(self):
        rows = [zone_row("MTZ313", "HW", "CON", utc(2025, 1, 10, 9, 0), utc(2025, 1, 11, 10, 0), eventid="21"),
                zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 17), eventid="21")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual(out["MTZ313"][0]["b"], "2025-01-10T07:00Z")
        self.assertNotIn("seen", out["MTZ313"][0])
        self.assertEqual(out["MTZ313"][0]["e"], "2025-01-11T10:00Z")

    def test_an_expiry_only_group_begins_at_its_issue_and_keeps_its_expiry_as_the_end(self):
        rows = [zone_row("MTZ313", "WS", "EXP", utc(2025, 2, 1, 10, 0), utc(2025, 2, 1, 12, 0), eventid="4", sig="W")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual(out["MTZ313"][0]["b"], "2025-02-01T10:00Z")
        self.assertEqual(out["MTZ313"][0]["e"], "2025-02-01T12:00Z")

    def test_without_a_cancellation_the_latest_non_cancellation_expiry_is_the_end(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 17), eventid="5"),
                zone_row("MTZ313", "HW", "CON", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 10, 0), eventid="5")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual(out["MTZ313"][0]["e"], "2025-01-11T10:00Z")
        self.assertNotIn("st", out["MTZ313"][0])

    def test_a_cancellation_row_ends_the_event_at_its_cancellation_time(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 17), eventid="8"),
                zone_row("MTZ313", "HW", "CON", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 10, 0), eventid="8"),
                zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 9, 0), utc(2025, 1, 10, 9, 0), eventid="8")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual(out["MTZ313"][0]["b"], "2025-01-10T07:00Z")
        self.assertEqual(out["MTZ313"][0]["e"], "2025-01-10T09:00Z")
        self.assertEqual(out["MTZ313"][0]["st"], "cancelled")

    def test_an_end_that_is_not_after_the_begin_is_unset(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 10, 7, 0), eventid="6")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertIsNone(out["MTZ313"][0]["e"])

    def test_cancellation_rows_at_midnight_are_counted_for_the_owner_not_rewritten(self):
        rows = [zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 0, 0), utc(2025, 1, 10, 6, 0), eventid="7")]
        ctx = zone_ctx(rows)
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual(ctx.zone_can_midnight, 1)
        self.assertEqual(out["MTZ313"][0]["b"], "2025-01-10T00:00Z")   # the issue on the row, not a rewritten time

    def test_the_sheet_says_end_not_recorded_and_cancelled_in_words(self):
        root = Path(tempfile.mkdtemp(prefix="joins-test-span-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "z" / "MTZ313.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [],
                "events": [{"k": "HW", "s": "W", "b": "2025-01-10T15:59Z", "e": None, "o": "TFX", "st": "cancelled"},
                           {"k": "HW", "s": "W", "b": "2025-03-24T17:00Z", "e": "2025-03-24T19:00Z", "o": "TFX"}]}))
            doc = _cell_doc(zones={"MTZ313": [GATE_KEY]})
            out = J.describe_joins(_index(), doc, *GATE, store_dir=root)
        finally:
            shutil.rmtree(root)
        rows = next(s for s in out["sections"] if s["id"] == "zones")["rows"]
        self.assertEqual(rows[0]["text"], "Zone product: High wind warning: Jan 10, 2025 8:59 am MST to end not "
                                          "recorded, cancelled; Mar 24, 2025 11:00 am MDT to 1:00 pm MDT")
        check_words(self, rows[0]["text"])


    def test_a_zone_event_with_no_recorded_begin_says_so_in_the_sheet(self):
        # the contract allows a null begin (D16); the build writes a begin on every event, so this is the sheet's words only
        root = Path(tempfile.mkdtemp(prefix="joins-test-nostart-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "z" / "MTZ313.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [],
                "events": [{"k": "HW", "s": "W", "b": None, "e": "2025-01-10T23:56Z", "o": "TFX", "st": "cancelled"}]}))
            out = J.describe_joins(_index(), _cell_doc(zones={"MTZ313": [GATE_KEY]}), *GATE, store_dir=root)
        finally:
            shutil.rmtree(root)
        rows = next(s for s in out["sections"] if s["id"] == "zones")["rows"]
        self.assertEqual(rows[0]["text"], "Zone product: High wind warning: start not recorded; end Jan 10, 2025 4:56 pm "
                                          "MST, cancelled")
        check_words(self, rows[0]["text"])

    def test_a_cancellation_at_or_before_the_begin_is_the_end_and_reads_cancelled_at(self):
        # D26: the cancellation time (the CAN row's expire) is kept although it precedes the begin
        rows = [zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 15, 59), utc(2025, 1, 10, 9, 0), eventid="22")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        event = out["MTZ313"][0]
        self.assertEqual(event["b"], "2025-01-10T15:59Z")
        self.assertEqual(event["e"], "2025-01-10T09:00Z")
        self.assertEqual(event["st"], "cancelled")
        begin, end_at = J._zone_span(event)
        self.assertEqual(J._zone_event_text(begin, end_at, "cancelled", J.WORDS_JOINS),
                         "cancelled at Jan 10, 2025 2:00 am MST")

    def test_the_sheet_says_cancelled_at_for_a_cancellation_before_the_begin(self):
        root = Path(tempfile.mkdtemp(prefix="joins-test-cancelled-at-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "z" / "MTZ313.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [],
                "events": [{"k": "HW", "s": "W", "b": "2025-01-10T15:59Z", "e": "2025-01-10T09:00Z", "o": "TFX",
                            "st": "cancelled"}]}))
            out = J.describe_joins(_index(), _cell_doc(zones={"MTZ313": [GATE_KEY]}), *GATE, store_dir=root)
        finally:
            shutil.rmtree(root)
        rows = next(s for s in out["sections"] if s["id"] == "zones")["rows"]
        self.assertEqual(rows[0]["text"], "Zone product: High wind warning: cancelled at Jan 10, 2025 2:00 am MST")
        check_words(self, rows[0]["text"])

    def test_a_cancellation_after_the_begin_keeps_the_span_and_the_cancelled_suffix(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 17), eventid="23"),
                zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 9, 0), utc(2025, 1, 10, 9, 0), eventid="23")]
        event = J._zone_events(zone_ctx(rows), *WINDOW)["MTZ313"][0]
        begin, end_at = J._zone_span(event)
        self.assertEqual(J._zone_event_text(begin, end_at, "cancelled", J.WORDS_JOINS),
                         "Jan 10, 2025 12:00 am MST to 2:00 am MST, cancelled")

    def test_an_upgrade_row_ends_its_event_at_the_upgrade_time_and_is_named_upgraded(self):
        # D31: an upgrade's expire is the time the lower event was upgraded, so an upgrade ends the event as a
        # cancellation does; the span is named upgraded, not cancelled
        rows = [zone_row("MTZ313", "WS", "UPG", utc(2025, 2, 1, 10, 0), utc(2025, 2, 1, 12, 0), eventid="10")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual(out["MTZ313"][0]["b"], "2025-02-01T10:00Z")
        self.assertEqual(out["MTZ313"][0]["e"], "2025-02-01T12:00Z")
        self.assertEqual(out["MTZ313"][0]["st"], "upgraded")

    def test_an_upgrade_ends_the_event_it_updates_at_the_upgrade_time_not_at_the_later_expiry(self):
        # D31: the lower event's expiry (12:00) is later than the upgrade (10:00), so the upgrade ends the event
        rows = [zone_row("MTZ313", "WS", "NEW", utc(2025, 2, 1, 7, 0), utc(2025, 2, 1, 12, 0), eventid="11"),
                zone_row("MTZ313", "WS", "UPG", utc(2025, 2, 1, 8, 0), utc(2025, 2, 1, 10, 0), eventid="11")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual(out["MTZ313"][0]["b"], "2025-02-01T07:00Z")
        self.assertEqual(out["MTZ313"][0]["e"], "2025-02-01T10:00Z")
        self.assertEqual(out["MTZ313"][0]["st"], "upgraded")

    def test_the_earliest_cancellation_or_upgrade_ends_the_event_and_names_it(self):
        # D31: the earliest of the cancellation and upgrade times ends the event and gives its word; a tie reads as
        # cancelled whichever row is listed first
        base = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 0), eventid="24")]
        cases = (("upgrade first", [("UPG", 9), ("CAN", 10)], "upgraded"),
                 ("cancellation first", [("CAN", 9), ("UPG", 10)], "cancelled"),
                 ("tie, upgrade listed first", [("UPG", 9), ("CAN", 9)], "cancelled"),
                 ("tie, cancellation listed first", [("CAN", 9), ("UPG", 9)], "cancelled"))
        for label, stops, word in cases:
            with self.subTest(label):
                rows = base + [zone_row("MTZ313", "HW", status, utc(2025, 1, 10, 8, 0), utc(2025, 1, 10, hour),
                                        eventid="24") for status, hour in stops]
                event = J._zone_events(zone_ctx(rows), *WINDOW)["MTZ313"][0]
                self.assertEqual(event["e"], "2025-01-10T09:00Z")
                self.assertEqual(event["st"], word)

    def test_an_upgrade_at_or_before_the_begin_is_the_end_and_reads_upgraded_at(self):
        # D31 with D26: the upgrade time is kept although it precedes the begin
        rows = [zone_row("MTZ313", "HW", "UPG", utc(2025, 1, 10, 15, 59), utc(2025, 1, 10, 9, 0), eventid="27")]
        event = J._zone_events(zone_ctx(rows), *WINDOW)["MTZ313"][0]
        self.assertEqual(event["b"], "2025-01-10T15:59Z")
        self.assertEqual(event["e"], "2025-01-10T09:00Z")
        self.assertEqual(event["st"], "upgraded")
        begin, end_at = J._zone_span(event)
        self.assertEqual(J._zone_event_text(begin, end_at, "upgraded", J.WORDS_JOINS),
                         "upgraded at Jan 10, 2025 2:00 am MST")

    def test_the_sheet_says_upgraded_and_upgraded_at_in_words(self):
        root = Path(tempfile.mkdtemp(prefix="joins-test-upgraded-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "z" / "MTZ313.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [],
                "events": [{"k": "HW", "s": "W", "b": "2025-01-10T07:00Z", "e": "2025-01-10T09:00Z", "o": "TFX",
                            "st": "upgraded"},
                           {"k": "HW", "s": "W", "b": "2025-01-10T15:59Z", "e": "2025-01-10T09:00Z", "o": "TFX",
                            "st": "upgraded"}]}))
            out = J.describe_joins(_index(), _cell_doc(zones={"MTZ313": [GATE_KEY]}), *GATE, store_dir=root)
        finally:
            shutil.rmtree(root)
        rows = next(s for s in out["sections"] if s["id"] == "zones")["rows"]
        self.assertEqual(rows[0]["text"], "Zone product: High wind warning: Jan 10, 2025 12:00 am MST to 2:00 am MST, "
                                          "upgraded; upgraded at Jan 10, 2025 2:00 am MST")
        check_words(self, rows[0]["text"])

    def test_the_group_key_is_the_vtec_event_zone_phenomenon_significance_office_number_and_year(self):
        # D30: rows that share the six key fields are one event, whatever their issue times; another office or year
        # is another event
        same = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 0), eventid="30"),
                zone_row("MTZ313", "HW", "CON", utc(2025, 1, 10, 19, 0), utc(2025, 1, 11, 10, 0), eventid="30")]
        self.assertEqual(len(J._zone_events(zone_ctx(same), *WINDOW)["MTZ313"]), 1)
        other_office = zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 0), eventid="30",
                                wfo="BYZ")
        other_year = zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 0), eventid="30",
                              vtec_year="2024")
        self.assertEqual(len(J._zone_events(zone_ctx(same + [other_office]), *WINDOW)["MTZ313"]), 2)
        self.assertEqual(len(J._zone_events(zone_ctx(same + [other_office, other_year]), *WINDOW)["MTZ313"]), 3)

    def test_an_event_number_reused_for_a_later_period_is_one_span_the_known_limit(self):
        # D30's known limit (DECISIONS D35, open item 15): one zone, phenomenon, significance, office, event number and
        # year is one event. The rows follow the pattern of MTZ004 WS 2024 event 1 (office MSO): a cancellation on 10
        # January, then a continuation issued on 11 January, is one group and one span that begins at the continuation
        # and ends at the earlier cancellation time (D26). The zone here is MTZ313 WS 2025 event 31 (a synthetic case).
        rows = [zone_row("MTZ313", "WS", "CAN", utc(2025, 1, 9, 0, 0), utc(2025, 1, 10, 15, 22), eventid="31"),
                zone_row("MTZ313", "WS", "CON", utc(2025, 1, 11, 12, 0), utc(2025, 1, 12, 12, 0), eventid="31")]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual(len(out["MTZ313"]), 1)
        self.assertEqual(out["MTZ313"][0]["b"], "2025-01-11T12:00Z")
        self.assertEqual(out["MTZ313"][0]["e"], "2025-01-10T15:22Z")
        self.assertEqual(out["MTZ313"][0]["st"], "cancelled")


class ZoneEditionDateTests(unittest.TestCase):
    """D16: each public zone edition the NWS page links is read; its date is the day, month and year in its file name;
    the edition in force on a day is the newest whose date is on or before it, so the cut-over is the newer edition's
    date (16 April 2026 for z_16ap26.zip)."""

    def test_each_edition_date_comes_from_its_file_name(self):
        self.assertEqual(J.zone_name_date("z_18mr25.zip"), date(2025, 3, 18))
        self.assertEqual(J.zone_name_date("z_16ap26.zip"), date(2026, 4, 16))
        for name in ("z_31xx25.zip", "fz16ap26.zip", "z_30fe26.zip"):
            with self.assertRaises(J.JoinsError):
                J.zone_name_date(name)

    def test_every_linked_edition_is_read_oldest_first_and_the_newest_is_current(self):
        page = (b'<a href="/source/gis/Shapefiles/WSOM/z_16ap26.zip">2026</a>'
                b'<a href="/source/gis/Shapefiles/WSOM/z_18mr25.zip">2025</a>')
        self.assertEqual(J.zone_zip_names(page), ["z_18mr25.zip", "z_16ap26.zip"])
        self.assertEqual(J.zone_zip_name(page), "z_16ap26.zip")

    def test_the_edition_in_force_changes_on_the_newer_editions_date(self):
        editions = [{"file": "z_18mr25.zip", "date": date(2025, 3, 18)}, {"file": "z_16ap26.zip", "date": date(2026, 4, 16)}]
        self.assertEqual(J._edition_in_force(editions, date(2024, 1, 1))["file"], "z_18mr25.zip")
        self.assertEqual(J._edition_in_force(editions, date(2026, 4, 15))["file"], "z_18mr25.zip")
        self.assertEqual(J._edition_in_force(editions, date(2026, 4, 16))["file"], "z_16ap26.zip")
        self.assertIsNone(J._edition_in_force([], date(2026, 4, 16)))


def edition(name: str, zones, why=None) -> dict:
    """One public zone edition as the build holds it: its file name, its date, its zones (None when not read)."""
    return {"file": name, "date": J.zone_name_date(name), "zones": zones, "why": why}


class ZoneEditionTests(unittest.TestCase):
    """D16 and D11: a product takes the zone code of the edition in force at its issue time, and that code maps to the
    current edition's zone with the same name and outline. The two linked editions agree (F-05: the same 83 zones with
    the same codes, names and outlines), so MTZ060 products issued in 2025 and in 2026 are placed on MTZ060 alike. A
    code no current zone holds is counted as unplaced, in Montana."""

    OLD, NEW = "z_18mr25.zip", "z_16ap26.zip"

    def _ctx(self, rows, editions, zone_map=None):
        ctx = zone_ctx(rows, zone_map=zone_map)
        ctx.zone_editions = editions
        J._edition_maps(ctx)
        return ctx

    def test_products_under_the_same_codes_are_placed_before_and_after_the_cut_over(self):
        rows = [zone_row("MTZ060", "HW", "NEW", utc(2025, 6, 1, 12), utc(2025, 6, 1, 18), eventid="12"),
                zone_row("MTZ060", "HW", "NEW", utc(2026, 4, 15, 12), utc(2026, 4, 15, 18), eventid="10"),
                zone_row("MTZ060", "HW", "NEW", utc(2026, 4, 23, 12), utc(2026, 4, 23, 18), eventid="11")]
        ctx = self._ctx(rows, [edition(self.OLD, [ZONE_313, ZONE_060]), edition(self.NEW, [ZONE_313, ZONE_060])],
                        zone_map=[ZONE_313, ZONE_060])
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual([e["b"] for e in out["MTZ060"]],
                         ["2025-06-01T12:00Z", "2026-04-15T12:00Z", "2026-04-23T12:00Z"])
        self.assertEqual((ctx.zone_products_unplaced, ctx.zone_products_renumbered), (0, 0))
        old, new = ctx.zone_edition_report
        self.assertEqual((old["file"], old["same_codes"], old["renamed"], old["geometry_max_diff_deg"]),
                         (self.OLD, 2, {}, 0.0))
        self.assertFalse(old["current"])
        self.assertTrue(new["current"])

    def test_a_zone_renumbered_in_the_newer_edition_takes_its_new_code(self):
        old_zone = {"zone": "MTZ070", "name": "Test Zone", "rings": [SQUARE_313]}
        new_zone = {"zone": "MTZ071", "name": "Test Zone", "rings": [SQUARE_313]}
        rows = [zone_row("MTZ070", "HW", "NEW", utc(2025, 6, 1, 12), utc(2025, 6, 1, 18), eventid="20"),
                zone_row("MTZ071", "HW", "NEW", utc(2026, 5, 1, 12), utc(2026, 5, 1, 18), eventid="21")]
        ctx = self._ctx(rows, [edition(self.OLD, [ZONE_313, old_zone]), edition(self.NEW, [ZONE_313, new_zone])],
                        zone_map=[ZONE_313, new_zone])
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual([e["b"] for e in out["MTZ071"]], ["2025-06-01T12:00Z", "2026-05-01T12:00Z"])
        self.assertEqual(ctx.zone_products_renumbered, 1)
        self.assertEqual(ctx.zone_edition_report[0]["renamed"], {"MTZ070": "MTZ071"})

    def test_a_product_under_a_code_no_current_zone_holds_is_counted_unplaced(self):
        gone = {"zone": "MTZ080", "name": "Gone Zone",
                "rings": [[(-100.0, 45.0), (-99.0, 45.0), (-99.0, 46.0), (-100.0, 46.0), (-100.0, 45.0)]]}
        rows = [zone_row("MTZ080", "HW", "NEW", utc(2025, 6, 1, 12), utc(2025, 6, 1, 18), eventid="30")]
        ctx = self._ctx(rows, [edition(self.OLD, [ZONE_313, gone]), edition(self.NEW, [ZONE_313])], zone_map=[ZONE_313])
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual(out, {})
        self.assertEqual(ctx.zone_products_unplaced, 1)
        self.assertIsNone(ctx.zone_edition_report[0]["renamed"]["MTZ080"])

    def test_an_edition_that_did_not_load_keeps_its_codes_and_the_index_says_so(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 6, 1, 12), utc(2025, 6, 1, 18), eventid="40")]
        ctx = self._ctx(rows, [edition(self.OLD, None, why="the source did not answer"), edition(self.NEW, [ZONE_313])],
                        zone_map=[ZONE_313])
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual([e["b"] for e in out["MTZ313"]], ["2025-06-01T12:00Z"])
        self.assertEqual(ctx.zone_edition_report[0], {"file": self.OLD, "effective": "2025-03-18", "current": False,
                                                      "read": False, "reason": "the source did not answer"})

    def test_ncei_zone_rows_follow_the_same_editions_and_unmatched_rows_are_counted(self):
        def ncei(zone, when):
            return {"zone": zone, "utc": when, "lat": None, "lon": None, "code": "high wind", "mag_text": "50",
                    "unit": "kt", "qual": "", "src": "Mesonet", "city": "X", "remark": "", "mag_mph": 58, "mag_kt": 50}
        ctx = self._ctx([], [edition(self.OLD, [ZONE_313, ZONE_060]), edition(self.NEW, [ZONE_313, ZONE_060])],
                        zone_map=[ZONE_313, ZONE_060])
        ctx.ncei_zone_rows = [ncei("MTZ060", utc(2025, 6, 1, 12)), ncei("MTZ060", utc(2026, 4, 23, 12)),
                              ncei("MTZ999", utc(2025, 6, 1, 12))]
        out = J._zone_records(ctx, *WINDOW)
        self.assertEqual(len(out["MTZ060"]), 2)
        self.assertEqual(ctx.zone_records_unmatched, 1)
        self.assertEqual(ctx.zone_records_renumbered, 0)

    def test_unplaced_products_are_said_to_be_in_montana_and_each_lead_counts_its_own_zone(self):
        index = _index()
        index["joins"].update({"zone_products_unplaced": 3, "ncei_zone_rows_unmatched": 0,
                               "fire_zones": {"state": "loaded", "reason": None, "zones": 1, "events": 2},
                               "fire_zone_names": {"MTZ117": "Central and Eastern Lewis and Clark"}})
        root = Path(tempfile.mkdtemp(prefix="joins-test-leads-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "z" / "MTZ313.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [],
                "events": [{"k": "HW", "s": "W", "b": "2025-01-10T15:59Z", "e": "2025-01-11T08:00Z", "o": "TFX"}]}))
            (root / "hail" / "z" / "fire-MTZ117.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "kind": "fire", "zone": "MTZ117", "name": "Central and Eastern Lewis and Clark",
                "records": [], "events": [
                    {"k": "FW", "s": "W", "b": "2025-03-01T16:00Z", "e": "2025-03-01T23:00Z", "o": "TFX"},
                    {"k": "FW", "s": "W", "b": "2025-03-02T16:00Z", "e": "2025-03-02T23:00Z", "o": "TFX"}]}))
            doc = _cell_doc(zones={"MTZ313": [GATE_KEY]}, fire={"MTZ117": [GATE_KEY]})
            out = J.describe_joins(index, doc, *GATE, store_dir=root)
        finally:
            shutil.rmtree(root)
        zones = next(s for s in out["sections"] if s["id"] == "zones")
        self.assertEqual(zones["lead"], "1 product for zone Judith Basin County (MTZ313) between Oct 17, 2021 and "
                                        "Oct 16, 2026.")
        self.assertEqual(zones["fire_lead"], "2 red flag warnings for fire weather zone Central and Eastern Lewis and "
                                             "Clark (MTZ117) between Oct 17, 2021 and Oct 16, 2026.")
        self.assertIn("3 zone products in Montana in the window could not be placed on a zone; their zone codes are not "
                      "in the public zone editions the NWS page links.", zones["lines"])
        self.assertEqual(len(zones["rows"]), 2)
        for text in [zones["lead"], zones["fire_lead"]]:
            check_words(self, text)


class UnavailableWordsTests(unittest.TestCase):
    """D20 and F-07: a part that did not load shows one sentence, exactly, from one template: the Python town page and
    the browser fill the same words from the map block, so they cannot disagree. It is never a "No ..." lead."""

    EXPECTED = {
        "reports": "Reports could not be loaded in this update; that is not the same as no report.",
        "records": "Records could not be loaded in this update; that is not the same as no record.",
        "detections": "Detections could not be loaded in this update; that is not the same as no detection.",
        "warnings": "Warnings could not be loaded in this update; that is not the same as no warning.",
        "zones": "Zone products could not be loaded in this update; that is not the same as no zone product.",
        "stations": "Station readings could not be loaded in this update; that is not the same as no station reading.",
    }

    def test_each_part_shows_its_own_sentence_from_the_one_template(self):
        for part, sentence in self.EXPECTED.items():
            index = _index(parts={**{p: "loaded" for p in J.PARTS}, part: "unavailable"},
                           reasons={part: "the source did not answer"})
            out = J.describe_joins(index, _cell_doc(), *GATE)
            sec = next(s for s in out["sections"] if s["id"] == part)
            self.assertEqual(sec["unavailable"], sentence, part)
            self.assertIsNone(sec["lead"], part)
            self.assertEqual(sec["rows"], [], part)
            browser = J.WORDS_JOINS["unavailable"].format(part=J.WORDS_JOINS[f"part_{part}"],
                                                          one=J.WORDS_JOINS[f"one_{part}"])
            self.assertEqual(browser, sentence, part)
            self.assertNotIn("not an all-clear", sentence)

    def test_the_part_names_and_the_sentence_pass_the_words_check(self):
        for sentence in self.EXPECTED.values():
            check_words(self, sentence)


class DamagedFileTests(unittest.TestCase):
    """D27: a station or zone file that is missing, unreadable or not in its format makes its section unavailable, with
    D20's sentence and never a "No day", "No product" or "No red flag" lead. A forecast-zone file that did not load
    keeps the point records, and the records section gives the partial sentence for the zone part. A fire zone file
    that did not load leaves out only the red flag warnings, with the sentence the sheet gives when the fire zones are
    missing."""

    STATIONS = "Station readings could not be loaded in this update; that is not the same as no station reading."
    ZONES = "Zone products could not be loaded in this update; that is not the same as no zone product."
    FIRE_LINE = "Red flag warnings are not listed (fire weather zones were not available)."
    LWT = {"id": "LWT", "name": "Lewistown", "lat": 47.06, "lon": -109.4, "miles": 12.3}
    UNREADABLE = '{"f": "hail-zone-v1", "events": ['

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="joins-test-damaged-"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def _store(self, name):
        root = self.root / name
        (root / "hail" / "z").mkdir(parents=True)
        (root / "hail" / "s").mkdir(parents=True)
        return root

    @staticmethod
    def _write(root, rel, text):
        if text is not None:            # None: the file is missing
            (root / "hail" / rel).write_text(text, encoding="utf-8")

    def _describe(self, root, inline, index=None):
        doc, events = store_form(inline)
        return J.describe_joins(index or _index(), _cell_doc(**doc), *GATE, store_dir=root, events=events)

    @staticmethod
    def _section(out, sid):
        return next(s for s in out["sections"] if s["id"] == sid)

    def _good_zone(self, root):
        self._write(root, "z/MTZ313.json", json.dumps({
            "f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [],
            "events": [{"k": "HW", "s": "W", "b": "2025-01-10T07:00Z", "e": "2025-01-11T08:17Z", "o": "TFX"}]}))

    def test_a_station_file_that_is_missing_or_damaged_makes_the_stations_section_unavailable(self):
        cases = {"missing": None,
                 "truncated": '{"f": "hail-station-v1", "days": [[',
                 "not an object": "[]",
                 "days not a list": '{"f": "hail-station-v1", "days": 3}',
                 "another format": '{"f": "hail-zone-v1", "days": []}'}
        for name, text in cases.items():
            with self.subTest(case=name):
                root = self._store("station_" + name.replace(" ", "_"))
                self._write(root, "s/LWT.json", text)
                sec = self._section(self._describe(root, {"stations": [self.LWT]}), "stations")
                self.assertEqual(sec["unavailable"], self.STATIONS)
                self.assertIsNone(sec["lead"])
                self.assertEqual((sec["rows"], sec["lines"]), ([], []))
                check_words(self, sec["unavailable"])

    def test_one_missing_station_file_clears_the_rows_of_the_other_stations(self):
        root = self._store("station_one_missing")
        self._write(root, "s/LWT.json", json.dumps({
            "f": J.STATION_FORMAT, "id": "LWT", "name": "Lewistown", "lat": 47.06, "lon": -109.4,
            "days": [[hail.day_index(date(2025, 6, 16)), 58, 50]], "dropped": 0}))
        other = dict(self.LWT, id="BIL", name="Billings", miles=30.0)     # its file is missing
        sec = self._section(self._describe(root, {"stations": [self.LWT, other]}), "stations")
        self.assertEqual(sec["unavailable"], self.STATIONS)
        self.assertIsNone(sec["lead"])
        self.assertEqual(sec["rows"], [])

    def test_a_tile_with_no_stations_keeps_its_sentence(self):
        sec = self._section(self._describe(self._store("no_stations"), {}), "stations")
        self.assertEqual(sec["lead"], "No station within 40 miles of this spot.")
        self.assertIsNone(sec["unavailable"])
        self.assertEqual(sec["rows"], [])

    def test_a_zone_file_that_is_missing_or_damaged_keeps_the_point_records(self):
        centre = hail.cell_centre(*GATE)
        record = [hail.day_index(date(2025, 6, 15)), 2010, round(centre[0], 4), round(centre[1], 4), "hail", "1.75",
                  "in", "", "Public", "Benchland", "", None, None]
        cases = {"missing": (None, "the source did not answer"),
                 "truncated": (self.UNREADABLE, "the file was in an unexpected format"),
                 "not an object": ("[]", "the file was in an unexpected format"),
                 "events not a list": ('{"f": "hail-zone-v1", "events": 3}', "the file was in an unexpected format"),
                 "another format": ('{"f": "hail-station-v1", "events": []}', "the file was in an unexpected format")}
        for name, (text, reason) in cases.items():
            with self.subTest(case=name):
                root = self._store("zone_" + name.replace(" ", "_"))
                self._write(root, "z/MTZ313.json", text)
                out = self._describe(root, {"zones": {"MTZ313": [GATE_KEY]}, "records": [record]})
                zones = self._section(out, "zones")
                self.assertEqual(zones["unavailable"], self.ZONES)
                self.assertIsNone(zones["lead"])
                self.assertIsNone(zones["fire_lead"])
                self.assertEqual((zones["rows"], zones["lines"]), ([], []))
                records = self._section(out, "records")
                self.assertIsNotNone(records["lead"])
                self.assertEqual(len(records["rows"]), 1)
                self.assertTrue(records["rows"][0]["text"].startswith("Record: "), records["rows"][0]["text"])
                self.assertEqual(records["unavailable"], "Data unavailable for some periods: NCEI Storm Events did not "
                                                         f"load for MTZ313 ({reason}). This is not an all-clear.")
                check_words(self, records["unavailable"])

    def test_a_fire_zone_file_that_is_missing_or_damaged_leaves_out_only_the_red_flag_rows(self):
        index = _index()
        index["joins"]["fire_zones"] = {"state": "loaded", "reason": None}
        cases = {"missing": None, "truncated": self.UNREADABLE, "not an object": "[]"}
        for name, text in cases.items():
            with self.subTest(case=name):
                root = self._store("fire_" + name.replace(" ", "_"))
                self._good_zone(root)
                self._write(root, "z/fire-MTZ120.json", text)
                out = self._describe(root, {"zones": {"MTZ313": [GATE_KEY]}, "fire": {"MTZ120": [GATE_KEY]}},
                                     index=index)
                zones = self._section(out, "zones")
                self.assertIsNone(zones["unavailable"])
                self.assertIsNone(zones["fire_lead"])
                self.assertIn(self.FIRE_LINE, zones["lines"])
                self.assertTrue(zones["lead"].startswith("1 product for zone Judith Basin County (MTZ313)"),
                                zones["lead"])
                self.assertEqual(len(zones["rows"]), 1)
                self.assertIn("High wind warning", zones["rows"][0]["text"])
                self.assertFalse(any("Red flag" in row["text"] for row in zones["rows"]))
                check_words(self, self.FIRE_LINE)


class RepullTests(unittest.TestCase):
    """D15: a re-pull window fetches fresh even when the cached copy is recent, and writes the fresh copy over it; the
    cached copy is used only when the fresh request fails. January re-pulls the previous year too. Offline, no request
    is made and a file the cache lacks is a failed source."""

    def test_the_refresh_years_are_the_current_year_and_in_january_the_previous_one(self):
        self.assertTrue(J._refresh_year(2026, date(2026, 10, 18)))
        self.assertFalse(J._refresh_year(2025, date(2026, 10, 18)))
        self.assertTrue(J._refresh_year(2025, date(2026, 1, 5)))
        self.assertFalse(J._refresh_year(2024, date(2026, 1, 5)))
        self.assertFalse(J._refresh_year(2025, date(2026, 2, 1)))

    def test_a_re_pull_fetches_even_when_the_cached_copy_is_one_hour_old(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-repull-"))
        try:
            cache = tmp / "cache"
            (cache / "lsr").mkdir(parents=True)
            (cache / "lsr" / "2026-10.csv").write_bytes(b"old\n")
            fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
            (cache / "lsr" / "2026-10.csv.meta.json").write_text(
                json.dumps({"fetched": fresh, "url": J.LSR_URL, "bytes": 4}), encoding="utf-8")
            fetcher = FakeFetcher(cache, None, lambda url, params: b"new\n")
            result = fetcher.get("lsr", J.LSR_URL, "lsr/2026-10.csv", refresh=True)
            written = (cache / "lsr" / "2026-10.csv").read_bytes()
        finally:
            shutil.rmtree(tmp)
        self.assertEqual((result.state, result.data), ("fetched", b"new\n"))
        self.assertEqual(written, b"new\n")
        self.assertEqual(len(fetcher.requests), 1)

    def test_offline_no_request_is_made_and_a_missing_file_is_a_failed_source(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-offline-"))
        try:
            cache = tmp / "cache"
            (cache / "lsr").mkdir(parents=True)
            (cache / "lsr" / "2026-10.csv").write_bytes(b"cached\n")
            fetcher = FakeFetcher(cache, None, lambda url, params: b"never\n", offline=True)
            cached = fetcher.get("lsr", J.LSR_URL, "lsr/2026-10.csv", refresh=True)
            missing = fetcher.get("lsr", J.LSR_URL, "lsr/2026-09.csv", refresh=True)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(fetcher.requests, [])
        self.assertEqual((cached.state, cached.data), ("cache", b"cached\n"))
        self.assertFalse(missing.ok)
        self.assertEqual(missing.reason, J.WORDS_JOINS["reason_offline"])


class MalformedRowTests(unittest.TestCase):
    """D21: a row whose date, position or magnitude cannot be read is skipped and counted; it never fails its file or
    the build, and the good rows around it are kept."""

    def test_an_lsr_row_with_a_bad_time_or_position_is_skipped_and_counted(self):
        bad_time = list(BENCHLAND_LSR)
        bad_time[0] = "2025-13-45 99:99"
        bad_lat = list(BENCHLAND_LSR)
        bad_lat[2] = "north"
        out = J.parse_lsr_rows(lsr_csv([BENCHLAND_LSR, bad_time, bad_lat]))
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["malformed"], 2)
        self.assertEqual(out["short"], 0)

    def test_an_lsr_short_row_is_still_counted_as_short(self):
        out = J.parse_lsr_rows(lsr_csv([BENCHLAND_LSR, ["202506152010", "2025/06/15 20:10"]]))
        self.assertEqual((len(out["rows"]), out["short"], out["malformed"]), (1, 1, 0))

    def test_an_ncei_row_with_a_bad_date_or_position_is_skipped_and_counted(self):
        header = ("EVENT_TYPE,STATE,BEGIN_DATE_TIME,CZ_TYPE,CZ_FIPS,BEGIN_LAT,BEGIN_LON,MAGNITUDE,MAGNITUDE_TYPE,"
                  "SOURCE,CZ_TIMEZONE,BEGIN_LOCATION,CZ_NAME,WFO")
        good = "Hail,MONTANA,11-MAY-25 17:23:00,C,1,47.08,-110.02,1.75,,Public,MST-7,BENCHLAND,JUDITH BASIN,TFX"
        bad_date = "Hail,MONTANA,31-XXX-25 17:23:00,C,1,47.08,-110.02,1.75,,Public,MST-7,BENCHLAND,JUDITH BASIN,TFX"
        bad_lat = "Hail,MONTANA,11-MAY-25 17:23:00,C,1,north,-110.02,1.75,,Public,MST-7,BENCHLAND,JUDITH BASIN,TFX"
        out = J.parse_ncei(("\n".join([header, good, bad_date, bad_lat]) + "\n").encode("utf-8"))
        self.assertEqual(len(out["points"]), 1)
        self.assertEqual(out["malformed"], 2)

    def test_a_swdi_row_with_a_bad_size_is_skipped_and_counted(self):
        raw = ("ZTIME,WSR_ID,CELL_ID,PROB,SEVPROB,MAXSIZE,LAT,LON\n"
               "2025-06-15T20:10:00Z,KTFX,A1,100,40,1.75,47.08,-110.02\n"
               "2025-06-15T20:20:00Z,KTFX,A2,100,40,big,47.10,-110.00\n"
               "count,2\ntotalTimeInSeconds,0.1\n").encode("utf-8")
        out = J.parse_swdi(raw)
        self.assertEqual([r["size"] for r in out["rows"]], [175])
        self.assertEqual(out["malformed"], 1)

    def test_a_daily_row_with_a_bad_day_is_skipped_and_counted(self):
        raw = ("station,day,max_wind_gust_kts,network\n"
               "LWT,2025-13-45,60.0,MT_ASOS\nLWT,2025-06-16,60.0,MT_ASOS\n").encode("utf-8")
        out = J.parse_daily(raw)
        self.assertEqual(out["days"], [(date(2025, 6, 16), 60.0)])
        self.assertEqual(out["malformed"], 1)

    def test_a_warning_csv_row_with_a_bad_time_is_skipped_and_counted(self):
        header = ("wfo,utc_issue,utc_expire,phenomena,gtype,significance,eventid,status,ugc,vtec_year,hailtag,windtag,"
                  "tornadotag,damagetag")
        good = "TFX,2025-06-15 20:10,2025-06-15 21:00,HW,C,W,5,NEW,MTZ313,2025,,,,"
        bad = "TFX,2025-99-99 20:10,2025-06-15 21:00,HW,C,W,6,NEW,MTZ313,2025,,,,"
        out = J.parse_ww_csv((header + "\n" + good + "\n" + bad + "\n").encode("utf-8"))
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["malformed"], 1)

    def test_an_asos_station_with_no_id_is_skipped_and_counted(self):
        raw = json.dumps({"features": [
            {"properties": {"sid": "LWT", "sname": "Lewistown"}, "geometry": {"coordinates": [-109.4, 47.06]}},
            {"properties": {"sname": "No id"}, "geometry": {"coordinates": [-108.5, 45.8]}}]}).encode("utf-8")
        out = J.parse_asos_rows(raw)
        self.assertEqual([s["id"] for s in out["stations"]], ["LWT"])
        self.assertEqual(out["malformed"], 1)


class WordingDecisionTests(unittest.TestCase):
    """The round-2 decisions the words carry (D22, D23, D17, D9, the reports sentence)."""

    def test_the_report_is_not_an_inspection_sentence_is_in_the_reports_words(self):
        self.assertIn("A report is not an inspection and not a finding about a roof.", J.WORDS_JOINS["reports_what"])

    def test_the_older_years_have_fewer_tags_sentence_is_not_written(self):
        self.assertNotIn("fewer tags", json.dumps(J.WORDS_JOINS))

    def test_no_zone_boundary_change_is_claimed_and_no_guessed_code_table_is_kept(self):
        self.assertNotIn("Zone boundaries changed", json.dumps(J.WORDS_JOINS))
        self.assertFalse(hasattr(J, "ZONE_CODE_CHANGES"))

    def test_the_joins_deadline_is_35_minutes(self):
        self.assertEqual(J.JOINS_DEADLINE_S, 35 * 60)

    def test_a_record_of_a_type_with_no_unit_is_typed_and_never_says_no_size_given(self):
        row = [0, 0, 47.0, -110.0, "winter storm", "", "", "", "ASOS", "Lewistown", "", None, None]
        text = J._zone_record_text(utc(2026, 3, 12, 6), row, "MTZ235", J.WORDS_JOINS)
        self.assertIn(": winter storm, ASOS, across zone MTZ235", text)
        self.assertNotIn("no size given", text)
        self.assertRegex(text, r"^Record: ")
        check_words(self, text)

    def test_a_record_of_a_type_with_a_unit_and_no_number_says_no_size_given(self):
        row = [0, 0, 47.0, -110.0, "hail", "", "", "", "Public", "Lewistown", "", None, None]
        text = J._record_text(utc(2025, 6, 15, 20, 10), row, 1.0, 47.0, -110.0, 47.0, -110.0, J.WORDS_JOINS)
        self.assertIn("hail, no size given", text)

    def test_the_unit_codes_are_the_lsr_codes_that_carry_a_unit_and_the_ncei_wind_and_hail_words(self):
        self.assertEqual(sorted(J.UNIT_CODES), ["A", "G", "H", "N", "R", "S", "hail", "high wind", "strong wind",
                                                "thunderstorm wind"])



class ZoneNearestTests(unittest.TestCase):
    """D8: a Montana cell no zone claims takes the nearest zone edge within 2 km; farther cells stay unassigned."""

    def _cell_at(self, lat, lon, row=500, col=500):
        return (row, col, lat, lon)

    def test_a_cell_about_a_kilometre_outside_a_zone_takes_its_code(self):
        lon = -110.0 + 1.0 / (111.32 * math.cos(math.radians(47.0)))
        out = J.assign_zones([self._cell_at(47.0, lon)], [ZONE_313])
        self.assertEqual(out, {(500, 500): "MTZ313"})

    def test_a_cell_about_five_kilometres_outside_takes_none(self):
        lon = -110.0 + 5.0 / (111.32 * math.cos(math.radians(47.0)))
        self.assertEqual(J.assign_zones([self._cell_at(47.0, lon)], [ZONE_313]), {})

    def test_the_nearest_rule_is_off_for_the_fire_zones(self):
        lon = -110.0 + 1.0 / (111.32 * math.cos(math.radians(47.0)))
        self.assertEqual(J.assign_zones([self._cell_at(47.0, lon)], [ZONE_313], near_km=0.0), {})


class LagTests(unittest.TestCase):
    """rules-10 and job-20: a lag names its newest event by its own date; a missing date says so, and "not known"
    appears nowhere."""

    def test_the_lags_name_the_newest_event_by_its_own_date(self):
        ctx = J.Context()
        ctx.swdi_newest = utc(2026, 9, 28, 8, 53)     # SPC day 27 September (grouped by SPC day)
        ctx.ww_newest = utc(2026, 9, 19, 1, 40)       # Montana local 18 September
        lags = J._lag_dates(ctx)
        self.assertEqual(lags["swdi"], "2026-09-27")
        self.assertEqual(lags["warnings"], "2026-09-18")
        self.assertEqual(J._lag_dates(J.Context()), {"ncei": None, "swdi": None, "warnings": None})

    def test_a_missing_lag_date_reads_as_no_date_not_not_known(self):
        index = _index()
        index["joins"]["lags"] = {"ncei": None, "swdi": None, "warnings": None}
        out = J.describe_joins(index, _cell_doc(), *GATE, events=store_form({})[1])
        text = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("not known", text)
        detections = next(s for s in out["sections"] if s["id"] == "detections")
        warnings = next(s for s in out["sections"] if s["id"] == "warnings")
        self.assertIn("No detection date is in this build.", detections["lines"])
        self.assertIn("No warning start date is in this build.", warnings["lines"])
        self.assertIn("an unknown date", next(s for s in out["sections"] if s["id"] == "records")["lead"])
        self.assertNotIn("not known", J.WORDS_JOINS["detections_lag"] + J.WORDS_JOINS["warnings_lag"])

    def test_a_present_lag_names_its_date(self):
        out = J.describe_joins(_index(), _cell_doc(), *GATE, events=store_form({})[1])
        detections = next(s for s in out["sections"] if s["id"] == "detections")
        self.assertIn("The newest detection in this build is from Oct 14, 2026.", detections["lines"])


class ShortRowTests(unittest.TestCase):
    """D10: a short row is skipped and counted, never aborting the file (data-6)."""

    def test_a_short_zone_row_is_skipped_and_counted(self):
        header = ("wfo,utc_issue,utc_expire,utc_prodissue,utc_init_expire,phenomena,gtype,significance,eventid,status,"
                  "ugc,area2d,utc_updated,hvtec_nwsli,hvtec_severity,hvtec_cause,hvtec_record,is_emergency,"
                  "utc_polygon_begin,utc_polygon_end,windtag,hailtag,tornadotag,damagetag,product_id,fcster,vtec_year")
        good = ("BYZ,2025-01-10 07:00,2025-01-11 08:17,2025-01-09 20:46,202501110300,HW,C,W,1,NEW,MTZ141,2003.9,"
                "2025-01-11 08:17,,,,,False,,,,,,,,,2025")
        raw = "\n".join([header, "TFX,2025-01-10 07:00", good]).encode("utf-8")
        out = J.parse_ww_csv(raw)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["short"], 1)

    def test_a_short_ncei_row_is_skipped_and_counted(self):
        fields = ["EVENT_TYPE", "STATE", "BEGIN_DATE_TIME", "CZ_TYPE", "CZ_FIPS", "BEGIN_LAT", "BEGIN_LON",
                  "MAGNITUDE", "MAGNITUDE_TYPE", "SOURCE", "CZ_TIMEZONE", "BEGIN_LOCATION", "CZ_NAME", "WFO"]
        good = ["Hail", "MONTANA", "15-JUN-25 13:10:00", "C", "45", "47.08", "-110.02", "1.75", "", "PUBLIC",
                "MST-7", "BENCHLAND", "JUDITH BASIN", "TFX"]
        raw = ",".join(fields) + "\n" + ",".join(good) + "\nHail,MONTANA,15-JUN-25 13:10:00\n"
        out = J.parse_ncei(gzip.compress(raw.encode("utf-8")))
        self.assertEqual(len(out["points"]), 1)
        self.assertEqual(out["short"], 1)

    def test_a_short_lsr_row_is_skipped_and_counted(self):
        raw = lsr_csv([BENCHLAND_LSR]).decode("utf-8") + "202506151200,2025/06/15 12:00,47.0\n"
        out = J.parse_lsr_rows(raw.encode("utf-8"))
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["short"], 1)

    def test_a_build_with_a_short_row_returns_and_counts_it(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-short-"))
        try:
            store = tmp / "store"
            hail.fixture_store(store)
            short_lsr = lsr_csv([BENCHLAND_LSR]).decode("utf-8") + "202506151200,2025/06/15 12:00,47.0\n"

            def responder(url, params):
                if url == J.LSR_URL and params.get("sts", "").startswith("2025-06"):
                    return short_lsr.encode("utf-8")
                return canned(url, params)
            fetcher = FakeFetcher(tmp / "cache", store / "ledger" / "joins.jsonl", responder)
            block = J.build(store, tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=fetcher,
                            log=lambda text: None)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(block["parts"]["reports"], "loaded")
        self.assertEqual(block["short_rows"]["reports"], 1)


class CacheContentTests(unittest.TestCase):
    """data-7 and job-15: a 200 response with an error page is never written to the cache for the NCEI details and the
    zone products."""

    def test_an_error_page_is_not_cached_for_ncei_details_or_zone_products(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-check-"))
        try:
            fetcher = FakeFetcher(tmp / "cache", None, lambda url, params: b"<html>service unavailable</html>")
            url = J.NCEI_DIR + "StormEvents_details-ftp_v1.0_d2025_c20260323.csv.gz"
            result = fetcher.get("ncei", url, "ncei/x.csv.gz", check=J._checker(J.parse_ncei))
            self.assertFalse(result.ok)
            self.assertFalse((tmp / "cache" / "ncei" / "x.csv.gz").exists())
            result = fetcher.get("zone_products", J.WW_URL, "zones/HWW-2025.csv",
                                 check=J._checker(J.parse_ww_csv))
            self.assertFalse(result.ok)
            self.assertFalse((tmp / "cache" / "zones" / "HWW-2025.csv").exists())
        finally:
            shutil.rmtree(tmp)


class DeadlineTests(unittest.TestCase):
    """job-12: no new request starts after the joins' time limit; an attempt in flight at the limit is the only
    overrun. The session is stubbed, so no request leaves the test."""

    class Resp:
        def __init__(self, status, content=b"ok"):
            self.status_code, self.content = status, content

    class Session:
        def __init__(self, statuses, on_call=None):
            self.statuses, self.calls, self.on_call = list(statuses), 0, on_call

        def get(self, url, params=None, timeout=None, headers=None):
            self.calls += 1
            if self.on_call is not None:
                self.on_call(self)
            return DeadlineTests.Resp(self.statuses.pop(0) if self.statuses else 503)

    def _fetcher(self, cache, session, deadline_s, **kw):
        fetcher = J.Fetcher(cache, None, procs=1, attempts=4, pause=0.0, deadline_s=deadline_s, **kw)
        fetcher._session = lambda: session
        fetcher._pace = lambda: None
        return fetcher

    def test_no_request_starts_after_the_deadline(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-deadline-"))
        try:
            session = self.Session([200])
            result = self._fetcher(tmp / "cache", session, -1.0).get("x", "https://example.invalid/a", "a.json")
            self.assertFalse(result.ok)
            self.assertEqual(session.calls, 0)
            self.assertEqual(result.reason, J.WORDS_JOINS["reason_no_answer"])
        finally:
            shutil.rmtree(tmp)

    def test_a_cached_copy_past_the_deadline_is_served_as_stale(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-deadline-"))
        try:
            cache = tmp / "cache"
            cache.mkdir()
            (cache / "a.json").write_bytes(b"{}")
            session = self.Session([200])
            fetcher = self._fetcher(cache, session, -1.0, max_age_s=0.0)
            result = fetcher.get("x", "https://example.invalid/a", "a.json", refresh=True)
            self.assertEqual(result.state, "stale")
            self.assertEqual(result.data, b"{}")
            self.assertEqual(session.calls, 0)
        finally:
            shutil.rmtree(tmp)

    def test_before_the_deadline_the_four_attempts_still_run(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-deadline-"))
        try:
            session = self.Session([503, 503, 503, 503])
            result = self._fetcher(tmp / "cache", session, 3600.0).get("x", "https://example.invalid/a", "a.json")
            self.assertFalse(result.ok)
            self.assertEqual(session.calls, 4)
        finally:
            shutil.rmtree(tmp)

    def test_an_attempt_in_flight_at_the_deadline_is_the_only_overrun(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-deadline-"))
        try:
            holder = {}

            def expire(session):
                holder["fetcher"].deadline_at = time.monotonic() - 1.0
            session = self.Session([503, 503, 503, 503], on_call=expire)
            holder["fetcher"] = self._fetcher(tmp / "cache", session, 3600.0)
            result = holder["fetcher"].get("x", "https://example.invalid/a", "a.json")
            self.assertFalse(result.ok)
            self.assertEqual(session.calls, 1)
        finally:
            shutil.rmtree(tmp)


class ListingTests(unittest.TestCase):
    """job-6 and data-18: one missing NCEI year drops that year only, with its own reason; a listing that did not
    answer keeps its reason."""

    def test_a_listing_missing_one_year_returns_the_others(self):
        page = (b"StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz StormEvents_details-ftp_v1.0_d2022_c20260625.csv.gz")
        names = J.ncei_listing_names(page, [2021, 2022, 2026])
        self.assertEqual(sorted(names), [2021, 2022])

    def test_a_listing_with_no_requested_year_is_refused(self):
        with self.assertRaises(J.JoinsError):
            J.ncei_listing_names(b"StormEvents_details-ftp_v1.0_d1999_c20260323.csv.gz", [2021])

    def test_a_missing_year_marks_only_that_year_with_the_file_list_reason(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-listing-"))
        try:
            store = tmp / "store"
            hail.fixture_store(store)

            def responder(url, params):
                if url == J.NCEI_DIR:
                    return b"".join(f"StormEvents_details-ftp_v1.0_d{y}_c20260323.csv.gz ".encode()
                                    for y in range(2021, 2027) if y != 2026)
                return canned(url, params)
            fetcher = FakeFetcher(tmp / "cache", store / "ledger" / "joins.jsonl", responder)
            block = J.build(store, tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=fetcher,
                            log=lambda text: None)
            index = hail.load_index(store)
            doc = json.loads((store / "hail" / "j" / f"{GATE_TILE}.json").read_text())
            out = J.describe_joins(index, doc, *GATE, store_dir=store)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(block["parts"]["records"], "partial")
        self.assertEqual(block["partial"]["records"], ["2026"])
        self.assertEqual(block["reasons"]["records"], J.WORDS_JOINS["reason_no_file_year"])
        self.assertEqual(sum(1 for url, _p in fetcher.requests if url.startswith(J.NCEI_DIR + "StormEvents")), 5)
        records = next(s for s in out["sections"] if s["id"] == "records")
        self.assertEqual(records["unavailable"], "Data unavailable for some periods: NCEI Storm Events did not load for "
                                                 "2026 (the NCEI file list has no file for this year). This is not an "
                                                 "all-clear.")

    def test_a_listing_that_does_not_answer_keeps_its_reason(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-listing-"))
        try:
            store = tmp / "store"
            hail.fixture_store(store)

            def responder(url, params):
                if url == J.NCEI_DIR:
                    return None
                return canned(url, params)
            fetcher = FakeFetcher(tmp / "cache", store / "ledger" / "joins.jsonl", responder)
            block = J.build(store, tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=fetcher,
                            log=lambda text: None)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(block["parts"]["records"], "unavailable")
        self.assertEqual(block["reasons"]["records"], J.WORDS_JOINS["reason_no_answer"])


class StaleCopyTests(unittest.TestCase):
    """job-4 and D10: a re-pull that fails keeps the cached copy, the part is partial with the reason, the index names
    the day the copy is from, and the gate still holds."""

    def test_a_failed_re_pull_is_served_from_the_cache_and_says_so(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-stale-"))
        try:
            store = tmp / "store"
            hail.fixture_store(store)
            first = FakeFetcher(tmp / "cache", store / "ledger" / "joins.jsonl", canned)
            J.build(store, tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=first, log=lambda text: None)
            fetched = datetime.now(timezone.utc) - timedelta(hours=25)
            for name in ("lsr/2026-09.csv", "lsr/2026-10.csv"):
                meta = tmp / "cache" / (name + ".meta.json")
                doc = json.loads(meta.read_text(encoding="utf-8"))
                doc["fetched"] = fetched.isoformat(timespec="seconds")
                meta.write_text(json.dumps(doc), encoding="utf-8")

            def failing(url, params):
                if url == J.LSR_URL:
                    return None
                return canned(url, params)
            second = FakeFetcher(tmp / "cache", store / "ledger" / "joins.jsonl", failing)
            block = J.build(store, tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=second,
                            log=lambda text: None)
            result = J.verify(store)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(block["parts"]["reports"], "partial")
        self.assertEqual(block["partial"]["reports"], ["2026-09", "2026-10"])
        self.assertEqual(block["reasons"]["reports"], J.WORDS_JOINS["reason_stale"])
        self.assertEqual(block["sources"]["lsr"]["stale"], 2)
        self.assertEqual(block["sources"]["lsr"]["served_from_cache_since"], fetched.date().isoformat())
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["gate"]["lsr_row"]["in"], "1.75")


class RedFlagTests(unittest.TestCase):
    """D7: red flag warnings (FW) go to their fire weather zone; when the fire zones did not load, the sheet says so."""

    def test_the_newest_fire_zone_edition_is_named_as_the_page_links_it(self):
        page = (b'<a href="/source/gis/Shapefiles/WSOM/fz18mr25.zip">old</a>'
                b'<a href="/source/gis/Shapefiles/WSOM/fz16ap26.zip">new</a>')
        self.assertEqual(J.fire_zip_name(page), "fz16ap26.zip")

    def test_red_flag_rows_go_to_their_fire_zone(self):
        fire_map = [{"zone": "MTZ120", "name": "Fort Peck", "rings": [SQUARE_313]}]
        rows = [zone_row("MTZ120", "FW", "NEW", utc(2025, 6, 1, 12), utc(2025, 6, 2, 12), eventid="20", wfo="GGW")]
        ctx = zone_ctx(rows, fire_map=fire_map)
        out = J._zone_events(ctx, *WINDOW)
        self.assertNotIn("MTZ120", out)
        self.assertEqual(ctx.fire_events["MTZ120"][0]["k"], "FW")
        self.assertEqual(ctx.zone_products_unplaced, 0)

    def test_red_flag_rows_are_not_listed_as_unplaced_when_the_fire_zones_did_not_load(self):
        rows = [zone_row("MTZ120", "FW", "NEW", utc(2025, 6, 1, 12), utc(2025, 6, 2, 12), eventid="21", wfo="GGW")]
        ctx = zone_ctx(rows, fire_map=None)
        J._zone_events(ctx, *WINDOW)
        self.assertEqual(ctx.fire_events, {})
        self.assertEqual(ctx.zone_products_fire_missing, 1)
        self.assertEqual(ctx.zone_products_unplaced, 0)

    def test_the_sheet_says_red_flag_warnings_are_not_listed_when_the_fire_zones_are_missing(self):
        index = _index()
        index["joins"]["fire_zones"] = {"state": "unavailable", "reason": "the file was in an unexpected format"}
        out = J.describe_joins(index, _cell_doc(), *GATE)
        zones = next(s for s in out["sections"] if s["id"] == "zones")
        self.assertIn("Red flag warnings are not listed (fire weather zones were not available).", zones["lines"])

    def test_fire_zone_events_appear_in_the_zone_section_with_their_zone_named(self):
        root = Path(tempfile.mkdtemp(prefix="joins-test-fire-"))
        try:
            (root / "hail" / "z").mkdir(parents=True)
            (root / "hail" / "z" / "fire-MTZ120.json").write_text(json.dumps({
                "f": J.ZONE_FORMAT, "kind": "fire", "zone": "MTZ120", "name": "Fort Peck", "records": [],
                "events": [{"k": "FW", "s": "W", "b": "2025-06-01T12:00Z", "e": "2025-06-02T12:00Z", "o": "GGW"}]}))
            index = _index()
            index["joins"]["fire_zones"] = {"state": "loaded", "reason": None}
            doc = _cell_doc(fire={"MTZ120": [GATE_KEY]})
            out = J.describe_joins(index, doc, *GATE, store_dir=root)
        finally:
            shutil.rmtree(root)
        zones = next(s for s in out["sections"] if s["id"] == "zones")
        self.assertEqual(zones["rows"][0]["text"], "Zone product: Red flag warning, fire weather zone Fort Peck "
                                                   "(MTZ120): Jun 1, 2025 6:00 am MDT to Jun 2, 2025 6:00 am MDT")


class NoOutlineTests(unittest.TestCase):
    """rules-15: a NEW warning with no outline is counted and shown, never dropped, and a spot with no kept warning
    gets the can't-tell lead."""

    def test_an_outline_less_new_warning_is_counted(self):
        if not HAVE_PYSHP:
            self.skipTest("pyshp is not installed (the daily job installs it)")
        import shapefile
        import zipfile
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-noout-"))
        try:
            base = tmp / "sv_2025"
            writer = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
            for name in ("WFO", "PHENOM", "GTYPE", "STATUS", "ETN", "POLY_BEG", "POLY_END", "HAILTAG", "WINDTAG",
                         "TORNTAG", "DAMAGTAG", "VTEC_YR"):
                writer.field(name, "C", size=12)
            values = ["TFX", "SV", "P", "NEW", "1", "202506151953", "202506152002", "1.00", "", "", "", "2025"]
            writer.null()
            writer.record(*values)
            writer.poly([SQUARE_313])
            writer.record(*(values[:4] + ["2"] + values[5:]))
            writer.close()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for ext in (".shp", ".dbf", ".shx"):
                    zf.write(str(base) + ext, base.name + ext)
            parsed = J.parse_ww_shapefile(buf.getvalue())
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(parsed["no_outline"], 1)
        self.assertEqual([e["eventid"] for e in parsed["events"]], ["2"])

    def test_a_spot_with_no_kept_warning_gets_the_cannot_be_checked_lead(self):
        index = _index()
        index["joins"]["warnings_no_outline"] = 1
        out = J.describe_joins(index, _cell_doc(), *GATE, events=store_form({})[1])
        warnings = next(s for s in out["sections"] if s["id"] == "warnings")
        self.assertEqual(warnings["lead"], J.WORDS_JOINS["warnings_lead_unknown"])
        self.assertIn("1 warning in these five years has no outline on file, so it cannot be matched to this spot.",
                      warnings["lines"])
        self.assertNotIn("No warning in the archive", warnings["lead"])


class PartialSentenceTests(unittest.TestCase):
    """job-3: a partial records or detections part names its periods, as the reports part does."""

    def test_partial_records_and_detections_name_the_periods(self):
        index = _index(parts={**{p: "loaded" for p in J.PARTS}, "records": "partial", "detections": "partial"},
                       reasons={"records": "the file was in an unexpected format", "detections": "the source did not answer"},
                       partial={"records": ["2023"], "detections": ["2024-03"]})
        out = J.describe_joins(index, _cell_doc(), *GATE, events=store_form({})[1])
        records = next(s for s in out["sections"] if s["id"] == "records")
        detections = next(s for s in out["sections"] if s["id"] == "detections")
        self.assertEqual(records["unavailable"], "Data unavailable for some periods: NCEI Storm Events did not load for "
                                                 "2023 (the file was in an unexpected format). This is not an all-clear.")
        self.assertEqual(detections["unavailable"], "Data unavailable for some periods: radar hail signatures (SWDI) did "
                                                    "not load for 2024-03 (the source did not answer). This is not an "
                                                    "all-clear.")


class WordsRoundTests(unittest.TestCase):
    """The words made in this round: the remark quotes, the sizes and labels, the knots, the record lead, the
    unit-less LSR types (D9), and the list of unit codes the browser reads."""

    def test_a_damage_word_in_a_remark_is_quoted_and_nowhere_else(self):
        centre = hail.cell_centre(*GATE)
        row = [hail.day_index(date(2025, 6, 15)), 2010, round(centre[0], 4), round(centre[1], 4), "H", "1.75", "in",
               "E", "Public", "Benchland", "WIND DAMAGE TO ROOF AND BARN."]
        doc, events = store_form({"reports": [row]})
        out = J.describe_joins(_index(), doc, *GATE, events=events)
        sec = next(s for s in out["sections"] if s["id"] == "reports")
        self.assertIn("“WIND DAMAGE TO ROOF AND BARN.”", sec["rows"][0]["remark"])
        check_words(self, sec["rows"][0]["remark"])
        self.assertIn("A report's remark and a warning's tag are the NWS's own words", sec["what"])

    def test_the_sizes_and_lead_words(self):
        self.assertEqual(J.station_day_row(date(2025, 6, 16), 56.483456)[1:], [65, 56])
        self.assertEqual(J.WORDS_JOINS["records_lead_one"].format(newest="Jun 30, 2026", start="a", end="b"),
                         "NCEI's database runs to Jun 30, 2026. 1 official record for this spot or its zone between a "
                         "and b.")
        self.assertNotIn("checked by NCEI", J.WORDS_JOINS["records_what"])

    def test_no_row_word_names_a_forbidden_term(self):
        for key, text in J.WORDS_JOINS.items():
            if isinstance(text, str):
                check_words(self, text)

    def test_a_type_with_no_unit_shows_its_type_and_qualifier_only(self):
        centre = hail.cell_centre(*GATE)
        day = hail.day_index(date(2025, 6, 15))
        row = [day, 2010, round(centre[0], 4), round(centre[1], 4), "6", "-40", "", "E", "Public", "Here", ""]
        doc, events = store_form({"reports": [row]})
        out = J.describe_joins(_index(), doc, *GATE, events=events)
        text = next(s for s in out["sections"] if s["id"] == "reports")["rows"][0]["text"]
        self.assertEqual(text, "Report: Jun 15, 2025 2:10 pm MDT: 6 (estimated), Public, 0.0 mi")
        self.assertNotIn("-40", text)

    def test_a_tornado_with_no_size_and_hail_with_no_size(self):
        centre = hail.cell_centre(*GATE)
        day = hail.day_index(date(2025, 6, 15))
        rows = [[day, 2010, round(centre[0], 4), round(centre[1], 4), "T", "None", "", "", "Public", "X", ""],
                [day, 2000, round(centre[0], 4), round(centre[1], 4), "H", "", "", "", "Public", "X", ""]]
        doc, events = store_form({"reports": rows})
        index = _index()
        index["joins"]["types"]["T"] = "tornado"
        out = J.describe_joins(index, doc, *GATE, events=events)
        texts = [r["text"] for r in next(s for s in out["sections"] if s["id"] == "reports")["rows"]]
        self.assertEqual(texts[0], "Report: Jun 15, 2025 2:10 pm MDT: tornado, Public, 0.0 mi")
        self.assertEqual(texts[1], "Report: Jun 15, 2025 2:00 pm MDT: hail, no size given, Public, 0.0 mi")

    def test_the_map_block_carries_the_unit_codes(self):
        index = _index()
        index["joins"].update({"state": "loaded", "cover": "x", "shapes": {}, "montana_time": [],
                               "compare": {}, "built_at": "x", "station_days_by_year": {}})
        block = J.map_data_joins(index)
        self.assertEqual(block["unit_codes"], ["A", "G", "H", "N", "R", "S", "hail", "high wind", "strong wind",
                                               "thunderstorm wind"])
        self.assertIn("warnings_lead_unknown", block["words"])


class RecordLeadTests(unittest.TestCase):
    """rules-14: one official record reads in the singular."""

    def test_one_record_reads_in_the_singular(self):
        centre = hail.cell_centre(*GATE)
        day = hail.day_index(date(2025, 6, 15))
        record = [day, 2010, round(centre[0], 4), round(centre[1], 4), "hail", "1.75", "in", "", "Public", "Benchland",
                  "", None, None]
        doc, events = store_form({"records": [record]})
        index = _index()
        index["joins"]["lags"]["ncei"] = "2026-06-30"
        out = J.describe_joins(index, _cell_doc(records=doc["records"]), *GATE, events=events)
        lead = next(s for s in out["sections"] if s["id"] == "records")["lead"]
        self.assertTrue(lead.startswith("NCEI's database runs to Jun 30, 2026. 1 official record"), lead)
        self.assertNotIn("1 official records", lead)


class DocumentedDataTests(unittest.TestCase):
    """data-14 and data-15: the module note states the gust rule as the data show it, and the SWDI filter keeps only
    PROB 100 rows."""

    def test_the_module_note_states_the_gust_rule_as_inferred(self):
        self.assertIn("many are whole knots", J.__doc__)
        self.assertIn("inferred from the values", J.__doc__)

    def test_swdi_keeps_prob_100_only(self):
        raw = ("ZTIME,WSR_ID,CELL_ID,PROB,SEVPROB,MAXSIZE,LAT,LON\n"
               "2025-06-15T20:10:00Z,KTFX,A1,100,40,1.75,47.08,-110.02\n"
               "2025-06-15T20:20:00Z,KTFX,A2,50,40,1.00,47.10,-110.00\n"
               "2025-06-15T20:30:00Z,KTFX,A3,90,40,0.75,47.10,-110.00\n"
               "summary\ncount,3\ntotalTimeInSeconds,0.1\n").encode("utf-8")
        out = J.parse_swdi(raw)
        self.assertEqual([r["size"] for r in out["rows"]], [175])
        short = J.parse_swdi(b"ZTIME,WSR_ID,CELL_ID,PROB,SEVPROB,MAXSIZE,LAT,LON\n2025-06-15T20:10:00Z,KTFX,A1\ncount,1\n"
                             b"summary\n")
        self.assertEqual((short["rows"], short["malformed"]), ([], 1))       # D21: a short row is skipped and counted


class CollectionLabelTests(unittest.TestCase):
    """D3 in the town table and the browser's words: the labels are in the template, so every row carries them."""

    def test_the_labels_are_in_the_templates(self):
        for key, label in (("reports_row", "Report: "), ("reports_row_here", "Report: "),
                           ("records_row", "Record: "), ("records_row_here", "Record: "),
                           ("records_zone_row", "Record: "), ("detections_row_one", "Detection: "),
                           ("detections_row_many", "Detection: "), ("warnings_row", "Warning: "),
                           ("zones_row", "Zone product: "), ("stations_row", "Station: ")):
            self.assertTrue(J.WORDS_JOINS[key].startswith(label), key)


class FixtureLinkTests(unittest.TestCase):
    def test_the_fixture_holds_the_fire_zone_name_list(self):
        index = hail.load_index(FIXTURE)
        self.assertIn("fire_zone_list", index["joins"])


if __name__ == "__main__":
    unittest.main()
