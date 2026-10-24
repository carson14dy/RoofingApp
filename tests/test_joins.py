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
import sys
import tempfile
import time
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from website import hail
from website import joins as J
from website import sources as src

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the shared forbidden list)
import words_rules as W  # noqa: E402

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
# B5 (source 4 and 6): the ten zone products B5 adds to the ten of D35
B5_ZONE_PRODUCTS = {("WW", "Y"), ("WS", "A"), ("HW", "A"), ("HT", "Y"), ("EH", "W"), ("EH", "A"), ("FR", "Y"),
                    ("FZ", "W"), ("DU", "Y"), ("FF", "A")}
try:
    import shapefile as _pyshp   # noqa: F401
    HAVE_PYSHP = True
except ImportError:
    HAVE_PYSHP = False


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


AC = " This is not an all-clear."     # D41: the sentence every unavailable and partial line ends with


def check_words(test: unittest.TestCase, text: str) -> None:
    """The shared list (tests/words_rules.py, F29): no forbidden stem outside what the brief allows (quoted wording, the
    NWS damage threat tag, "This is not an all-clear.", "not the same as no hail"), no other "no hail"; "no wind" only in
    a sentence that says it is not the conclusion."""
    W.assert_clean(test, text)
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\bno wind\b", W.residue(sentence), re.IGNORECASE):
            test.assertRegex(sentence, r"\bnot\b", f"'no wind' without a negation: {sentence!r}")


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
                  "MAGNITUDE", "MAGNITUDE_TYPE", "SOURCE", "CZ_TIMEZONE", "BEGIN_LOCATION", "CZ_NAME", "WFO",
                  "FLOOD_CAUSE"]
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

    def test_county_coded_points_of_the_seven_b5_types_are_joined_as_records_with_their_type_word(self):
        """B5 source 5: tornado, flood, flash flood, heavy rain, funnel cloud, lightning and debris flow points are county
        rows with coordinates; they join as records within 5 miles, typed (no magnitude), with FLOOD_CAUSE as written."""
        kinds = ("Tornado", "Flood", "Flash Flood", "Heavy Rain", "Funnel Cloud", "Lightning", "Debris Flow")
        data = self._ncei_gz([
            {"EVENT_TYPE": kind, "CZ_TYPE": "C", "CZ_FIPS": "45", "BEGIN_DATE_TIME": "15-JUN-25 13:10:00",
             "BEGIN_LAT": "47.08", "BEGIN_LON": "-110.02", "SOURCE": "PUBLIC", "BEGIN_LOCATION": "BENCHLAND",
             "FLOOD_CAUSE": "Heavy Rain / Snow Melt" if kind == "Flood" else ""}
            for kind in kinds])
        out = J.parse_ncei(data)
        self.assertEqual([p["code"] for p in out["points"]], [k.lower() for k in kinds])
        self.assertEqual(out["zone_rows"], [])
        flood = out["points"][1]
        self.assertEqual((flood["mag_text"], flood["unit"], flood["cause"]), ("", "", "Heavy Rain / Snow Melt"))
        self.assertEqual(out["points"][0]["cause"], "")

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
            item = {"k": "SV", "s": "W", "b": begin, "e": end, "o": office,
                    "tags": {"hail_in": 1.0, "wind_mph": 60.0, "tornado": None, "damage": "CONSIDERABLE"}}
            return item, J.cover_hex([key])
        doc = _cell_doc(warnings=[warning(GATE_KEY, "2025-06-15T00:26Z", "2025-06-15T01:08Z"),
                                  warning((GATE_KEY + 1) % 100, "2025-06-15T05:39Z", "2025-06-15T05:59Z")])
        out = self._describe(doc)
        sec = self._section(out["sections"], "warnings")
        self.assertEqual(len(sec["rows"]), 1)
        text = sec["rows"][0]["text"]
        self.assertEqual(text, "Warning: Jun 14, 2025 6:26 pm MDT to 7:08 pm MDT: severe thunderstorm warning, TFX, covered "
                               "this cell or part of it; tags: hail 1.00 in, wind 60 mph, NWS damage threat tag: "
                               "considerable")
        self.assertIn("Tags are the forecast threat at issue time, not what fell.", sec["what"])
        self.assertIn("covered this cell or part of it", sec["what"])
        check_words(self, text)

    def test_a_warning_with_no_tags_shows_no_tags_clause_and_a_tornado_tag_is_shown(self):
        doc = _cell_doc(warnings=[({"k": "TO", "s": "W", "b": "2025-06-15T05:39Z", "e": "2025-06-15T05:59Z", "o": "BYZ",
                                    "tags": {"hail_in": None, "wind_mph": None, "tornado": "OBSERVED",
                                             "damage": None}}, J.cover_hex([GATE_KEY]))])
        out = self._describe(doc)
        self.assertIn("tags: tornado observed", self._section(out["sections"], "warnings")["rows"][0]["text"])
        doc["warnings"][0][0]["tags"]["tornado"] = None
        out = self._describe(doc)
        text = self._section(out["sections"], "warnings")["rows"][0]["text"]
        self.assertTrue(text.endswith("; tags: none stated"), text)          # the browser's warnings_tags_none
        self.assertIn("covered this cell or part of it; tags: none stated", text)   # D41: the B5 row (part B1)

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
                         "The forecast zone for this cell could not be determined. This is not an all-clear.")
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
            self.assertEqual(sec["rows"][0]["text"], "Station: Jun 16, 2025: 50 kt (58 mph) at Lewistown, about 34.7 "
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
                                             "warning. This is not an all-clear.")
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

    def test_the_zone_products_are_the_twenty_the_decisions_and_the_b5_brief_name(self):
        self.assertEqual(len(J.ZONE_PRODUCTS), 20)
        self.assertEqual(set(J.ZONE_PRODUCTS), D35_ZONE_PRODUCTS | B5_ZONE_PRODUCTS)

    def test_the_flood_warning_is_a_polygon_product_named_flood_warning_not_a_zone_product(self):
        self.assertNotIn(("FL", "W"), J.ZONE_PRODUCTS)
        self.assertIn(("FL", "W"), J.POLYGON_PRODUCTS)
        self.assertEqual(J.PRODUCT_NAMES["FL.W"], "Flood warning")

    def test_the_flood_watch_is_a_zone_product_named_flood_watch(self):
        self.assertIn(("FA", "A"), J.ZONE_PRODUCTS)
        self.assertEqual(J.PRODUCT_NAMES["FA.A"], "Areal flood watch")   # D41: the areal product, not the hydrologic one

    def test_every_zone_product_has_a_name_and_no_zone_product_is_a_flood_warning(self):
        for phen, sig in J.ZONE_PRODUCTS:
            name = J.PRODUCT_NAMES[f"{phen}.{sig}"]
            self.assertNotIn("flood warning", name.lower(), name)
            if "flood" in name.lower():
                self.assertIn(name, ("Flood watch", "Flash flood watch", "Areal flood watch"))

    def test_the_browser_product_names_are_the_zone_products_and_the_polygon_products(self):
        index = _index()
        index["joins"].update({"state": "loaded", "cover": "x", "shapes": {}, "montana_time": [], "compare": {},
                               "built_at": "x", "station_days_by_year": {}})
        products = J.map_data_joins(index)["products"]
        self.assertEqual(products["FL.W"], "Flood warning")
        self.assertEqual(products["FA.A"], "Areal flood watch")
        for phen, sig in J.ZONE_PRODUCTS + J.POLYGON_PRODUCTS:
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
        self.assertIn("Joined as points: Hail, Thunderstorm Wind, Flood, Flash Flood, Heavy Rain, Tornado, Funnel Cloud, "
                      "Lightning and Debris Flow rows with coordinates within 5 miles of a cell's centre", request)
        self.assertIn("Other county-coded types are not joined as points.", request)


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
                                               "{one}. This is not an all-clear.")

    def test_the_records_words_name_the_points_joined_and_the_points_not_joined(self):
        text = " ".join(J.WORDS_JOINS["records_what"].split())
        self.assertIn("This list has the point records within 5 miles: hail, thunderstorm wind, flood, flash flood, "
                      "heavy rain, tornado, funnel cloud, lightning and debris flow.", text)
        self.assertIn("Zone-coded records (high wind, winter storm, heavy snow and the other events NCEI codes to a forecast "
                      "zone) are for the spot's forecast zone", text)
        self.assertIn("A flood record shows NCEI's cause as written.", text)

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


def _iem_zone_codes(after_switch: bool) -> list:
    """The synthetic Montana zone codes of one IEM snapshot (D44): the 83 current codes, and with the 20 zones removed on
    13 September 2022 the 103 codes the set held before it. The codes are the real ones, the geometry is not."""
    current = ([f"MTZ{n:03d}" for n in list(range(1, 8)) + list(range(16, 44)) + list(range(56, 64)) + list(range(64, 74))]
               + [f"MTZ{n:03d}" for n in range(301, 331)])
    return current if after_switch else sorted(current + list(J.IEM_REMOVED_ZONES))


def _iem_geojson(codes, extra_county: bool = True) -> bytes:
    """A GeoJSON snapshot of the codes: one small square per zone, placed on a grid (the test geometry), and a county
    feature the reader must skip."""
    feats = []
    for i, code in enumerate(codes):
        x0 = -114.0 + (i % 20) * 0.5
        y0 = 44.5 + (i // 20) * 0.4
        ring = [[x0, y0], [x0 + 0.4, y0], [x0 + 0.4, y0 + 0.3], [x0, y0 + 0.3], [x0, y0]]
        feats.append({"type": "Feature", "properties": {"ugc": code, "name": f"Test zone {code}", "state": "MT",
                                                       "wfo": "TFX"},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
    if extra_county:
        feats.append({"type": "Feature", "properties": {"ugc": "MTC001", "name": "Beaverhead", "state": "MT"},
                      "geometry": {"type": "Polygon", "coordinates": [[[-113, 45], [-112, 45], [-112, 46], [-113, 45]]]}})
    return json.dumps({"type": "FeatureCollection", "features": feats}).encode("utf-8")


def _iem_snap(stamp: str, codes) -> dict:
    """One IEM snapshot as the build holds it after _iem_sets (its zones read from the synthetic file)."""
    zones = J.parse_iem_ugcs(_iem_geojson(codes))
    return {"valid": stamp, "date": J._iem_date(stamp), "file": f"iem-ugcs/valid-{stamp}/MT.geojson", "zones": zones,
            "why": None, "bytes": 1, "sha256": "0" * 64, "codes": {z["zone"] for z in zones}}


def _placement_ctx() -> "J.Context":
    """A context with the seven IEM snapshots, the current zones (83), the archived editions the NWS does not publish and
    the two linked editions, as _collect leaves them when every request loads (D44)."""
    ctx = J.Context()
    ctx.zone_map = J.parse_iem_ugcs(_iem_geojson(_iem_zone_codes(True), extra_county=False))
    ctx.iem_sets = [_iem_snap("2021-09-15T12:00:00Z", _iem_zone_codes(False)),
                    _iem_snap("2022-06-01T12:00:00Z", _iem_zone_codes(False)),
                    _iem_snap("2022-09-10T12:00:00Z", _iem_zone_codes(False)),
                    _iem_snap("2022-09-13T12:00:00Z", _iem_zone_codes(False)),
                    _iem_snap("2022-09-13T18:00:00Z", _iem_zone_codes(True)),
                    _iem_snap("2023-06-01T12:00:00Z", _iem_zone_codes(True)),
                    _iem_snap("2025-03-18T12:00:00Z", _iem_zone_codes(True))]
    before = [s for s in ctx.iem_sets if s["zones"] is not None and s["date"] < J.IEM_SWITCH]
    ctx.iem_outline = [z for z in before[-1]["zones"] if z["zone"] in J.IEM_OUTLINE_ZONES]
    ctx.zone_editions = [edition(name, None) for name in J.ZONE_EDITION_ARCHIVE] + [
        edition("z_18mr25.zip", ctx.zone_map), edition("z_16ap26.zip", ctx.zone_map)]
    J._edition_maps(ctx)
    return ctx


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
                  "MAGNITUDE", "MAGNITUDE_TYPE", "SOURCE", "CZ_TIMEZONE", "BEGIN_LOCATION", "CZ_NAME", "WFO",
                  "FLOOD_CAUSE"]
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
    if url.startswith("https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson"):      # D44: the IEM zone sets by date
        valid = re.search(r"valid=([^&]+)", url).group(1)
        return _iem_geojson(_iem_zone_codes(after_switch=valid >= "2022-09-13T18:00:00Z"))
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
        self.assertEqual(station["days"], [[hail.day_index(date(2025, 6, 16)), 58, 50, 0]])
        self.assertEqual(station["dropped"], 1)
        self.assertTrue((self.store / "ledger" / "joins.jsonl").is_file())
        self.assertIn("joins", json.loads((self.store / "hail" / "index.json").read_text()))

    def test_the_build_asks_for_the_twenty_zone_products_and_the_polygon_products_with_a_margin(self):
        J.build(self.store, self.tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=self.fetcher,
                log=lambda text: None)
        csv_asked = {(params["phenomena[]"], params["significance[]"]) for url, params in self.fetcher.requests
                     if url == J.WW_URL and params.get("accept") == "csv"}
        self.assertEqual(csv_asked, set(J.ZONE_PRODUCTS) | set(J.POLYGON_PRODUCTS))     # zone rows and the polygons' rows
        self.assertTrue(("FL", "W") in csv_asked and ("FL", "W") not in set(J.ZONE_PRODUCTS))
        windows = {(params["year1"], params["month1"], params["day1"], params["year2"], params["month2"],
                    params["day2"]) for url, params in self.fetcher.requests if url == J.WW_URL}
        self.assertTrue(all(w[1:3] == ("12", "1") and w[4:6] == ("1", "31") for w in windows), windows)

    def test_verify_passes_and_reports_the_gate_row(self):
        J.build(self.store, self.tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=self.fetcher,
                log=lambda text: None)
        result = J.verify(self.store)
        self.assertTrue(result["ok"], result["checks"])
        # F15: the warnings outage means the town point check did not run: it is named with its reason, and it passes nothing
        self.assertFalse(any(c["name"].startswith("D11: the town point check") for c in result["checks"]))
        self.assertIn({"name": "D11: the town point check for the 17 towns (every polygon product, 2021 to 2026)",
                       "reason": "warnings part unavailable"}, result["not_run"])
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
        # D10, D18, D54, D64 and D74: the store and joins files have a 480 KB budget. D64 restated it from 62 KB when the sample
        # gained the station part, and D74 from 320 KB: the sample names the rejected candidates of its tile lists (D69), so
        # their summaries are cut in too (67 summaries where there were 33). D78(c) adds the GHCN name beside each display name
        # (ghcn_name in the summaries, the tile lists and the stations block): measured on the regenerated fixture, 485,066
        # bytes outside hail/a/ (471,538 before the display names; 305,024 before D74). The address files under hail/a/ keep
        # their 50 KB budget
        store_bytes = sum(p.stat().st_size for p in FIXTURE.rglob("*") if p.is_file()
                          and not p.relative_to(FIXTURE).as_posix().startswith("hail/a/"))
        address_bytes = sum(p.stat().st_size for p in (FIXTURE / "hail" / "a").rglob("*") if p.is_file())
        self.assertLess(store_bytes, 480 * 1024, store_bytes)
        self.assertLess(address_bytes, 50 * 1024, address_bytes)

    def test_the_committed_fixture_names_are_the_display_names_with_the_ghcn_name_beside_them(self):
        """D78(c): the fixture's tile lists, station summaries and stations block carry each station's display name (the rule
        stations.display_name) and the GHCN name beside it, so the browser and the words show the name as given."""
        from website import stations as stn
        root = FIXTURE / "hail"
        checked = 0
        for path in sorted((root / "tl").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for res in doc["elements"].values():
                for key in ("passing", "unread", "rejected"):
                    for entry in res.get(key, []):
                        checked += 1
                        self.assertEqual(entry["name"], stn.display_name(entry["ghcn_name"]), (path.name, entry["id"]))
        self.assertGreater(checked, 0)
        for path in sorted((root / "sd").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["name"], stn.display_name(doc["ghcn_name"]), path.name)
        block = json.loads((root / "index.json").read_text(encoding="utf-8"))["stations"]["stations"]
        for sid, row in block.items():
            self.assertEqual(row["name"], stn.display_name(row["ghcn_name"]), sid)

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


def zone_row(ugc, phen, status, issue, expire, eventid="1", wfo="TFX", sig="W", gtype="C", vtec_year="2025",
             prod=None):
    """One zone row as parse_ww_csv gives it (B5: with the product time, which orders the rows of a period, D8)."""
    return {"ugc": ugc, "phen": phen, "sig": sig, "wfo": wfo, "eventid": eventid, "vtec_year": vtec_year,
            "gtype": gtype, "status": status, "issue": issue, "expire": expire,
            "prod": issue if prod is None else prod}


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
            warnings=[({"k": "SV", "s": "W", "b": "2025-06-15T19:53Z", "e": "2025-06-15T20:02Z", "o": "TFX",
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

    def test_the_first_closing_row_ends_the_period_and_a_later_one_is_a_period_of_its_own(self):
        # D8 (B2 D31 kept for ties): the first closing row in product order ends the open period and gives its word; at
        # the same product time a cancellation comes before an upgrade, so a tie reads as cancelled. A later closing row
        # is a period of its own, from its issue time to its expiry.
        base = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 7, 0), utc(2025, 1, 11, 8, 0), eventid="24",
                         prod=utc(2025, 1, 10, 6, 0))]
        # (label, the two rows (status, issue hour, expiry hour), the first span's word, the second span's word)
        cases = (("upgrade first", [("UPG", 8, 9), ("CAN", 9, 10)], "upgraded", "cancelled"),
                 ("cancellation first", [("CAN", 8, 9), ("UPG", 9, 10)], "cancelled", "upgraded"),
                 ("tie, upgrade listed first", [("UPG", 8, 9), ("CAN", 8, 9)], "cancelled", "upgraded"),
                 ("tie, cancellation listed first", [("CAN", 8, 9), ("UPG", 8, 9)], "cancelled", "upgraded"))
        for label, stops, word, second_word in cases:
            with self.subTest(label):
                rows = base + [zone_row("MTZ313", "HW", status, utc(2025, 1, 10, hour), utc(2025, 1, 10, end),
                                        eventid="24", prod=utc(2025, 1, 10, hour)) for status, hour, end in stops]
                events = J._zone_events(zone_ctx(rows), *WINDOW)["MTZ313"]
                self.assertEqual(len(events), 2)
                first = events[0]
                self.assertEqual((first["b"], first["e"], first["st"]), ("2025-01-10T07:00Z", "2025-01-10T09:00Z", word))
                ordered = sorted(stops, key=lambda x: (x[1], 0 if x[0] == "CAN" else 1))
                self.assertEqual(events[1]["b"], f"2025-01-10T{ordered[1][1]:02d}:00Z")
                self.assertEqual(events[1]["st"], second_word)

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

    def test_an_event_number_reused_for_a_later_period_is_two_spans_d8(self):
        # D8 (B2 D33, implemented in B5): the MTZ004 WS 2024 event 1 pattern (office MSO): a cancellation on 10 January,
        # then a continuation issued on 11 January. The rows are two periods: the cancelled one, and the continuation,
        # which is open and ends at its latest expiry. (The zone here is MTZ313 WS 2025 event 31: a synthetic case.)
        rows = [zone_row("MTZ313", "WS", "CAN", utc(2025, 1, 9, 0, 0), utc(2025, 1, 10, 15, 22), eventid="31",
                         prod=utc(2025, 1, 7, 21, 57)),
                zone_row("MTZ313", "WS", "CON", utc(2025, 1, 11, 12, 0), utc(2025, 1, 12, 12, 0), eventid="31",
                         prod=utc(2025, 1, 10, 20, 13))]
        out = J._zone_events(zone_ctx(rows), *WINDOW)
        self.assertEqual([(e["b"], e["e"], e.get("st")) for e in out["MTZ313"]],
                         [("2025-01-09T00:00Z", "2025-01-10T15:22Z", "cancelled"),
                          ("2025-01-11T12:00Z", "2025-01-12T12:00Z", None)])

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

    def test_an_edition_the_nws_links_that_did_not_load_leaves_its_products_unplaced_and_the_index_says_so(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 6, 1, 12), utc(2025, 6, 1, 18), eventid="40")]
        ctx = self._ctx(rows, [edition(self.OLD, None, why="the source did not answer"), edition(self.NEW, [ZONE_313])],
                        zone_map=[ZONE_313])
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual(out, {})
        self.assertEqual(ctx.zone_products_unplaced, 1)
        self.assertEqual(ctx.zone_unplaced_rows, [["HW.W", "MTZ313", "2025-06-01", self.OLD, "edition_unread"]])

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
        self.assertIn("3 zone products in Montana in these five years could not be placed on a zone: their zone codes "
                      "are not in the zone set in force when they were issued (the IEM zone sets, About). This is not an "
                      "all-clear.", zones["lines"])
        self.assertEqual(len(zones["rows"]), 2)
        for text in [zones["lead"], zones["fire_lead"]]:
            check_words(self, text)


class UnavailableWordsTests(unittest.TestCase):
    """D20 and F-07: a part that did not load shows one sentence, exactly, from one template: the Python town page and
    the browser fill the same words from the map block, so they cannot disagree. It is never a "No ..." lead."""

    EXPECTED = {
        "reports": "Reports could not be loaded in this update; that is not the same as no report." + AC,
        "records": "Records could not be loaded in this update; that is not the same as no record." + AC,
        "detections": "Detections could not be loaded in this update; that is not the same as no detection." + AC,
        "warnings": "Warnings could not be loaded in this update; that is not the same as no warning." + AC,
        "zones": "Zone products could not be loaded in this update; that is not the same as no zone product." + AC,
        "stations": "Station readings could not be loaded in this update; that is not the same as no station reading." + AC,
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
            self.assertTrue(sentence.endswith(AC), part)      # D41: the sentence ends with the all-clear

    def test_the_part_names_and_the_sentence_pass_the_words_check(self):
        for sentence in self.EXPECTED.values():
            check_words(self, sentence)


class DamagedFileTests(unittest.TestCase):
    """D27: a station or zone file that is missing, unreadable or not in its format makes its section unavailable, with
    D20's sentence and never a "No day", "No product" or "No red flag" lead. A forecast-zone file that did not load
    keeps the point records, and the records section gives the partial sentence for the zone part. A fire zone file
    that did not load leaves out only the red flag warnings, with the sentence the sheet gives when the fire zones are
    missing."""

    STATIONS = "Station readings could not be loaded in this update; that is not the same as no station reading." + AC
    ZONES = "Zone products could not be loaded in this update; that is not the same as no zone product." + AC
    FIRE_LINE = "Red flag warnings are not listed (fire weather zones were not available)." + AC
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
                  "MAGNITUDE", "MAGNITUDE_TYPE", "SOURCE", "CZ_TIMEZONE", "BEGIN_LOCATION", "CZ_NAME", "WFO",
                  "FLOOD_CAUSE"]
        good = ["Hail", "MONTANA", "15-JUN-25 13:10:00", "C", "45", "47.08", "-110.02", "1.75", "", "PUBLIC",
                "MST-7", "BENCHLAND", "JUDITH BASIN", "TFX", ""]
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
        self.assertIn("Red flag warnings are not listed (fire weather zones were not available)." + AC, zones["lines"])

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
        self.assertIn("1 warning in these five years has no outline on file, so it cannot be matched to this cell or "
                      "part of it." + AC, warnings["lines"])
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

    def test_an_unknown_ncei_date_reads_as_the_words_key_not_a_placeholder(self):
        # D68 and D71 (F2): the lead's {newest} is WORDS_JOINS["records_newest_unknown"], Python's voice, which the browser fills
        self.assertEqual(J.WORDS_JOINS["records_newest_unknown"], "an unknown date")
        lead = J._records_lead(0, None, {"start": "Jun 1, 2025", "end": "Jun 30, 2025"}, J.WORDS_JOINS)
        self.assertEqual(lead, "NCEI's database runs to an unknown date. No official record for this spot or its zone between "
                               "Jun 1, 2025 and Jun 30, 2025. Records are not a complete account of every storm.")
        centre = hail.cell_centre(*GATE)
        day = hail.day_index(date(2025, 6, 15))
        record = [day, 2010, round(centre[0], 4), round(centre[1], 4), "hail", "1.75", "in", "", "Public", "Benchland",
                  "", None, None]
        doc, events = store_form({"records": [record]})
        index = _index()
        index["joins"]["lags"]["ncei"] = None
        out = J.describe_joins(index, _cell_doc(records=doc["records"]), *GATE, events=events)
        lead = next(s for s in out["sections"] if s["id"] == "records")["lead"]
        self.assertTrue(lead.startswith("NCEI's database runs to an unknown date. 1 official record"), lead)
        self.assertNotIn("[", lead)                                # no bracketed placeholder from the browser's fallback


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
                           ("detections_row_many", "Detection: "),
                           ("zones_row", "Zone product: "), ("county_row", "County product: "),
                           ("stations_row", "Station: ")):
            self.assertTrue(J.WORDS_JOINS[key].startswith(label), key)


class FixtureLinkTests(unittest.TestCase):
    def test_the_fixture_holds_the_fire_zone_name_list(self):
        index = hail.load_index(FIXTURE)
        self.assertIn("fire_zone_list", index["joins"])


# ---------------------------------------------------------------- B5 (the products builder): the rules and paths

def _rows_of(events):
    return [(e["b"], e["e"], e.get("st")) for e in events]


class PeriodRuleTests(unittest.TestCase):
    """D8 (B2 D33, implemented in B5): rows in product order; a CAN, UPG or EXP closes the open period; a NEW, CON, EXT,
    EXA or EXB opens a period when none is open; each period is a span. The four named cases are checked against their
    rows as the cache holds them (MTZ004 WS 2024 event 1, MTZ302 HW 2022 event 38, MTZ320 WS 2023 event 4, MTZ003 WS 2021
    event 12)."""

    def test_the_four_named_cases_give_their_periods(self):
        cases = {
            "MTZ004": [zone_row("MTZ004", "WS", "CAN", utc(2024, 1, 9), utc(2024, 1, 10, 15, 22), eventid="1",
                                prod=utc(2024, 1, 7, 21, 57)),
                       zone_row("MTZ004", "WS", "CON", utc(2024, 1, 11, 12), utc(2024, 1, 12, 12), eventid="1",
                                prod=utc(2024, 1, 10, 20, 13))],
            "MTZ302": [zone_row("MTZ302", "HW", "CAN", utc(2022, 12, 26, 18), utc(2022, 12, 27, 7, 19), eventid="38",
                                prod=utc(2022, 12, 26, 8, 37)),
                       zone_row("MTZ302", "HW", "CAN", utc(2022, 12, 27, 15), utc(2022, 12, 28, 15, 29), eventid="38",
                                prod=utc(2022, 12, 27, 8, 22))],
            "MTZ320": [zone_row("MTZ320", "WS", "CAN", utc(2023, 2, 19, 18), utc(2023, 2, 22, 10, 54), eventid="4",
                                prod=utc(2023, 2, 19, 10, 17)),
                       zone_row("MTZ320", "WS", "EXP", utc(2023, 2, 22, 18, 58), utc(2023, 2, 23, 1), eventid="4",
                                prod=utc(2023, 2, 22, 18, 58))],
            "MTZ003": [zone_row("MTZ003", "WS", "EXP", utc(2021, 12, 19, 4), utc(2021, 12, 19, 15), eventid="12",
                                prod=utc(2021, 12, 19, 0, 24)),
                       zone_row("MTZ003", "WS", "CAN", utc(2021, 12, 19, 18), utc(2021, 12, 20, 3, 27), eventid="12",
                                prod=utc(2021, 12, 19, 17, 56))],
        }
        expected = {
            "MTZ004": [("2024-01-09T00:00Z", "2024-01-10T15:22Z", "cancelled"),
                       ("2024-01-11T12:00Z", "2024-01-12T12:00Z", None)],
            "MTZ302": [("2022-12-26T18:00Z", "2022-12-27T07:19Z", "cancelled"),
                       ("2022-12-27T15:00Z", "2022-12-28T15:29Z", "cancelled")],
            "MTZ320": [("2023-02-19T18:00Z", "2023-02-22T10:54Z", "cancelled"),
                       ("2023-02-22T18:58Z", "2023-02-23T01:00Z", None)],
            "MTZ003": [("2021-12-19T04:00Z", "2021-12-19T15:00Z", None),
                       ("2021-12-19T18:00Z", "2021-12-20T03:27Z", "cancelled")],
        }
        for zone, rows in cases.items():
            with self.subTest(zone):
                out = J._zone_events(zone_ctx(rows, zone_map=[dict(ZONE_313, zone=zone)]), *WINDOW)
                self.assertEqual(_rows_of(out[zone]), expected[zone])

    def test_a_continuation_inside_an_open_period_is_one_period_to_the_latest_expiry(self):
        rows = [zone_row("MTZ313", "WS", "NEW", utc(2025, 1, 10, 7), utc(2025, 1, 11, 8), eventid="40"),
                zone_row("MTZ313", "WS", "CON", utc(2025, 1, 10, 19), utc(2025, 1, 11, 10), eventid="40")]
        self.assertEqual(_rows_of(J.periods(rows)) if False else [(p["begin"], p["end"], p["stop"]) for p in J.periods(rows)],
                         [(utc(2025, 1, 10, 7), utc(2025, 1, 11, 10), None)])

    def test_a_cancellation_with_no_open_period_is_its_own_period_ending_at_its_expiry(self):
        rows = [zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 9), utc(2025, 1, 10, 12), eventid="41")]
        self.assertEqual([(p["begin"], p["end"], p["stop"]) for p in J.periods(rows)],
                         [(utc(2025, 1, 10, 9), utc(2025, 1, 10, 12), "CAN")])

    def test_an_open_period_whose_latest_expiry_is_not_after_its_begin_has_no_end(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 9), utc(2025, 1, 10, 9), eventid="42")]
        self.assertEqual([(p["begin"], p["end"]) for p in J.periods(rows)], [(utc(2025, 1, 10, 9), None)])

    def test_a_cancellation_at_or_before_the_begin_is_kept_as_the_end(self):
        rows = [zone_row("MTZ313", "HW", "NEW", utc(2025, 1, 10, 9), utc(2025, 1, 11), eventid="43",
                         prod=utc(2025, 1, 10, 8)),
                zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 8), utc(2025, 1, 10, 8, 30), eventid="43",
                         prod=utc(2025, 1, 10, 9, 30))]
        self.assertEqual([(p["begin"], p["end"], p["stop"]) for p in J.periods(rows)],
                         [(utc(2025, 1, 10, 9), utc(2025, 1, 10, 8, 30), "CAN")])

    def test_the_product_time_orders_the_rows_not_their_issue_times(self):
        rows = [zone_row("MTZ313", "HW", "CAN", utc(2025, 1, 10, 8), utc(2025, 1, 10, 9), eventid="44",
                         prod=utc(2025, 1, 10, 9)),
                zone_row("MTZ313", "HW", "CON", utc(2025, 1, 10, 10), utc(2025, 1, 10, 12), eventid="44",
                         prod=utc(2025, 1, 10, 8, 30))]
        self.assertEqual([(p["begin"], p["stop"]) for p in J.periods(rows)],
                         [(utc(2025, 1, 10, 10), "CAN")])


class TouchRuleTests(unittest.TestCase):
    """D11: a polygon covers a cell when it intersects the cell's square; the centre rule is a subset of that."""

    def setUp(self):
        self.row, self.col = hail.cell_for(47.08, -110.02)          # Benchland's cell (792, 1998)
        self.tile = {"r": self.row // 10, "c": self.col // 10}
        self.clat, self.clon = hail.cell_centre(self.row, self.col)
        self.key = hail.cell_key(self.row, self.col)
        self.east = hail.cell_key(self.row, self.col + 1)

    def test_a_polygon_inside_one_cell_touches_that_cell_only(self):
        d = 0.001
        ring = [(self.clon - d, self.clat - d), (self.clon + d, self.clat - d), (self.clon + d, self.clat + d),
                (self.clon - d, self.clat + d)]
        centre, touched = J._cover_sets([ring], self.tile)
        self.assertEqual((centre, touched), ([self.key], [self.key]))

    def test_a_thin_polygon_across_a_cell_side_touches_both_cells_and_has_the_centre_of_one(self):
        ring = [(self.clon + 0.004, self.clat - 0.001), (self.clon + 0.02, self.clat - 0.001),
                (self.clon + 0.02, self.clat + 0.001), (self.clon + 0.004, self.clat + 0.001)]
        centre, touched = J._cover_sets([ring], self.tile)
        self.assertEqual(centre, [self.east])                       # the east cell's centre is inside
        self.assertEqual(touched, sorted([self.key, self.east]))   # this cell's square is crossed at its east side

    def test_a_polygon_inside_a_cell_away_from_its_centre_touches_without_the_centre(self):
        ring = [(self.clon + 0.003, self.clat + 0.003), (self.clon + 0.004, self.clat + 0.003),
                (self.clon + 0.004, self.clat + 0.004)]
        centre, touched = J._cover_sets([ring], self.tile)
        self.assertEqual((centre, touched), ([], [self.key]))

    def test_a_polygon_outside_the_tile_touches_nothing(self):
        ring = [(self.clon + 1.0, self.clat), (self.clon + 1.1, self.clat), (self.clon + 1.1, self.clat + 0.1)]
        self.assertEqual(J._cover_sets([ring], self.tile), ([], []))

    def test_every_centre_key_is_a_touch_key(self):
        rng = __import__("random").Random(7)
        for _ in range(20):
            cx, cy = self.clon + rng.uniform(-0.03, 0.03), self.clat + rng.uniform(-0.03, 0.03)
            ring = [(cx + rng.uniform(-0.02, 0.02), cy + rng.uniform(-0.02, 0.02)) for _ in range(5)]
            centre, touched = J._cover_sets([ring], self.tile)
            self.assertTrue(set(centre) <= set(touched))


@unittest.skipUnless(HAVE_PYSHP, "pyshp is not installed (the daily job installs it)")
class PolygonParseTests(unittest.TestCase):
    """The polygon path (B5): any polygon product's NEW polygons; an outline-less NEW row is kept as a null, never dropped."""

    def _shapefile(self, rows):
        import shapefile
        shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
        w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
        for name in ("WFO", "PHENOM", "SIG", "GTYPE", "STATUS", "ETN", "POLY_BEG", "POLY_END", "HAILTAG", "WINDTAG",
                     "TORNTAG", "DAMAGTAG", "VTEC_YR"):
            w.field(name, "C", size=24)
        for shape, rec in rows:
            if shape is None:
                w.null()
            else:
                w.poly([shape])
            w.record(*rec)
        w.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("wwa.shp", shp.getvalue())
            zf.writestr("wwa.shx", shx.getvalue())
            zf.writestr("wwa.dbf", dbf.getvalue())
        return buf.getvalue()

    def test_new_polygons_of_any_product_are_events_and_outline_less_ones_are_nulls(self):
        ring = [[-110.0, 47.0], [-109.9, 47.0], [-109.9, 47.1], [-110.0, 47.0]]
        base = ["TFX", "FL", "W", "P", "NEW", "7", "202506150000", "202506150600", "", "", "", "", "2025"]
        rows = [(ring, base), (None, base[:5] + ["8"] + base[6:]),
                (ring, ["TFX", "SQ", "W", "P", "CON", "9"] + base[6:])]
        data = self._shapefile(rows)
        out = J.parse_ww_shapefile(data, "FL", "W")
        self.assertEqual(len(out["events"]), 1)
        self.assertEqual((out["events"][0]["k"], out["events"][0]["s"], out["events"][0]["eventid"]), ("FL", "W", "7"))
        self.assertEqual(out["events"][0]["b"], utc(2025, 6, 15, 0))
        self.assertEqual(len(out["nulls"]), 1)
        self.assertEqual(out["no_outline"], 1)

    def test_a_damage_threat_tag_is_kept_for_the_tag_word(self):
        ring = [[-110.0, 47.0], [-109.9, 47.0], [-109.9, 47.1], [-110.0, 47.0]]
        row = ["TFX", "SQ", "W", "P", "NEW", "3", "202506150000", "202506150600", "", "", "", "SIGNIFICANT", "2025"]
        out = J.parse_ww_shapefile(self._shapefile([(ring, row)]), "SQ", "W")
        self.assertEqual(out["events"][0]["damage"], "SIGNIFICANT")
        self.assertIsNone(out["events"][0]["hail_in"])

    def test_repeated_polygon_rows_from_two_years_are_one_event(self):
        ring = [(-110.0, 47.0), (-109.9, 47.0), (-109.9, 47.1)]
        ev = {"k": "FL", "s": "W", "b": utc(2025, 6, 15), "e": utc(2025, 6, 16), "o": "TFX", "eventid": "7",
              "vtec_year": "2025", "rings": [ring]}
        ctx = J.Context()
        ctx.window_bounds = (utc(2021, 10, 17, 12), utc(2026, 10, 16, 12))
        ctx.ww_all = [dict(ev), dict(ev)]
        ctx.ww_nulls = []
        J._dedupe_polygons(ctx)
        self.assertEqual(len(ctx.ww_all), 1)
        self.assertEqual(ctx.polygon_duplicates, 1)
        self.assertEqual(len(ctx.ww_events), 1)


class MarginAndCacheTests(unittest.TestCase):
    """The IEM requests run a month either side of the year (B5): a row issued in one year and begun in the next is
    in both years' requests, and is one row once the copies are dropped."""

    def test_the_request_runs_from_december_of_the_year_before_to_january_of_the_year_after(self):
        csv_params = J._ww_params("FL", "W", 2024, shapefile=False)
        self.assertEqual([csv_params[k] for k in ("year1", "month1", "day1", "year2", "month2", "day2")],
                         ["2023", "12", "1", "2025", "1", "31"])
        self.assertEqual((csv_params["accept"], csv_params["phenomena[]"], csv_params["significance[]"]),
                         ("csv", "FL", "W"))
        self.assertEqual(J._ww_params("SV", "W", 2024, shapefile=True)["accept"], "shapefile")

    def test_the_margin_cache_folders_are_new_so_the_year_only_files_are_not_mixed_in(self):
        self.assertEqual(J._ww_rel("SV", "W", 2024, True), "ww-m/SVW-2024.zip")
        self.assertEqual(J._ww_rel("WW", "Y", 2024, False), "zones-m/WWY-2024.csv")


class CountyPathTests(unittest.TestCase):
    """Source 4: a county-only event (its rows carry an MTC code and its key has no zone row) joins the cells of its
    county; a county twin of a zone-coded event does not; an outline-less polygon joins by the county codes of its rows."""

    COUNTY = {"zone": "MTC045", "name": "Judith Basin", "rings": [[(-110.5, 46.5), (-109.5, 46.5), (-109.5, 47.5),
                                                                  (-110.5, 47.5), (-110.5, 46.5)]]}

    def _ctx(self, rows):
        ctx = J.Context()
        ctx.zone_map = [ZONE_313]
        ctx.fire_map = None
        ctx.county_map = [self.COUNTY]
        ctx.zone_rows = rows
        return ctx

    def test_a_county_only_event_is_a_county_event(self):
        ctx = self._ctx([zone_row("MTC045", "FA", "NEW", utc(2025, 1, 10, 7), utc(2025, 1, 11), eventid="5",
                                  wfo="TFX", sig="A")])
        J._zone_events(ctx, *WINDOW)
        self.assertEqual([(e["k"], e["s"], e["b"]) for e in ctx.county_events["MTC045"]],
                         [("FA", "A", "2025-01-10T07:00Z")])

    def test_a_county_twin_of_a_zone_coded_event_is_not_a_county_event(self):
        ctx = self._ctx([zone_row("MTZ313", "FA", "NEW", utc(2025, 1, 10, 7), utc(2025, 1, 11), eventid="5", sig="A"),
                         zone_row("MTC045", "FA", "NEW", utc(2025, 1, 10, 7), utc(2025, 1, 11), eventid="5", sig="A")])
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual(ctx.county_events, {})
        self.assertEqual(len(out["MTZ313"]), 1)

    def test_an_outline_less_polygon_joins_by_its_county_codes_and_is_counted_otherwise(self):
        null = {"k": "FL", "s": "W", "o": "TFX", "eventid": "9", "vtec_year": "2025", "b": utc(2025, 6, 15, 1),
                "e": utc(2025, 6, 15, 9)}
        ctx = self._ctx([])
        ctx.ww_nulls = [dict(null)]
        ctx.poly_rows = [dict(zone_row("MTC045", "FL", "CAN", utc(2025, 6, 15, 2), utc(2025, 6, 15, 5), eventid="9"),
                              phen="FL", sig="W")]
        J._join_nulls(ctx, *WINDOW)
        self.assertEqual(ctx.null_polygons, {"window": 1, "joined": 1, "unjoined": 0})
        self.assertEqual([(e["k"], e["n"]) for e in ctx.county_events["MTC045"]], [("FL", 1)])
        ctx2 = self._ctx([])
        ctx2.ww_nulls = [dict(null)]
        J._join_nulls(ctx2, *WINDOW)
        self.assertEqual(ctx2.null_polygons, {"window": 1, "joined": 0, "unjoined": 1})
        self.assertEqual(ctx2.county_events, {})


class LsrKindTests(unittest.TestCase):
    """Source 6: the labels NWS changed fold into one word per kind; every other label shows the archive's own words."""

    def test_the_changed_labels_fold_into_one_word_per_kind(self):
        for label, word in (("HEAVY RAIN", "rain"), ("RAIN", "rain"), ("HEAVY SNOW", "snow"), ("SNOW", "snow"),
                            ("EXTR WIND CHILL", "wind chill"), ("WIND CHILL", "wind chill"),
                            ("EXCESSIVE HEAT", "extreme heat"), ("EXTREME HEAT", "extreme heat")):
            with self.subTest(label):
                self.assertEqual(J.lsr_kind(label), word)

    def test_the_other_labels_show_the_archive_words_in_lower_case(self):
        self.assertEqual(J.lsr_kind("FREEZING RAIN"), "freezing rain")
        self.assertEqual(J.lsr_kind("EXTREME COLD"), "extreme cold")
        self.assertEqual(J.lsr_kind("SNOW/ICE DMG"), "snow/ice dmg")

    def test_a_report_row_shows_the_kind_word_it_carries(self):
        utc_ = utc(2024, 3, 1, 15)
        r = [0, 0, 47.0, -110.0, "R", "0.50", "in", "", "Public", "Town", "", "rain"]
        text = J._report_text(utc_, r, 1.0, 47.0, -110.0, 47.0, -110.0, J.WORDS_JOINS)
        self.assertIn(": rain, 0.50 in", text)
        self.assertNotIn("heavy rain", text)


class NcePointTypeTests(unittest.TestCase):
    def test_the_unit_codes_are_hail_and_the_wind_types_only(self):
        self.assertEqual(J.NCEI_UNIT_CODES, frozenset({"hail", "thunderstorm wind", "high wind", "strong wind"}))
        for kind in ("flood", "flash flood", "tornado", "lightning", "debris flow", "heavy rain", "funnel cloud"):
            self.assertNotIn(kind, J.UNIT_CODES)

    def test_a_flood_record_shows_its_type_word_and_no_number(self):
        r = [0, 1300, 47.0, -110.0, "flood", "", "", "", "PUBLIC", "BENCHLAND", "", None, None,
             "Heavy Rain / Snow Melt"]
        text = J._record_text(utc(2025, 6, 15, 13), r, 1.0, 47.0, -110.0, 47.0, -110.0, J.WORDS_JOINS)
        self.assertIn("Record: Jun 15, 2025 7:00 am MDT: flood, NCEI cause as written: Heavy Rain / Snow Melt, PUBLIC, "
                      "0.0 mi", text)
        self.assertNotIn("no size given", text)
        check_words(self, text)

    def test_the_b5_record_row_shows_the_cause_as_written(self):
        w = J.WORDS_JOINS
        cause = w["records_cause"].format(cause="Heavy Rain / Snow Melt")
        self.assertEqual(w["records_row_here_typed_b5"].format(date="Jun 15, 2025", time="7:00 am MDT", type="flood",
                                                               cause=cause, qualifier="", source="PUBLIC", miles="0.0"),
                         "Record: Jun 15, 2025 7:00 am MDT: flood, NCEI cause as written: Heavy Rain / Snow Melt, PUBLIC, "
                         "0.0 mi")
        check_words(self, w["records_row_here_typed_b5"].format(date="d", time="t", type="flood", cause=cause,
                                                                qualifier="", source="s", miles="0.0"))


class GustFlagTests(unittest.TestCase):
    def test_readings_at_130_knots_or_more_are_dropped_and_the_rest_are_kept_or_not_stored(self):
        self.assertEqual([J.station_day_kind(kt) for kt in (182.5, 130, 129.9, 50, 49.9)],
                         ["dropped", "dropped", "keep", "keep", "below"])

    def test_the_flagged_readings_are_the_two_the_brief_names(self):
        self.assertEqual(J.FLAG_CHECK, {("HVR", "2025-02-20"), ("MSO", "2025-05-09")})

    def test_the_station_row_carries_its_flag_as_a_fourth_element(self):
        row = J.station_day_row(date(2025, 2, 20), 105.146)
        self.assertEqual(len(row + [1]), 4)
        self.assertEqual(row, [hail.day_index(date(2025, 2, 20)), 121, 105])

    def test_the_flag_words_are_plain_and_pass_the_words_check(self):
        for key in ("flag_check", "flag_check_line", "flag_suffix"):
            check_words(self, J.WORDS_JOINS[key])
        self.assertIn("not been checked", J.WORDS_JOINS["flag_check"])


class TownAndPairTests(unittest.TestCase):
    def test_a_town_point_outside_a_polygon_whose_cell_centre_is_inside_is_listed(self):
        row, col = hail.cell_for(47.08, -110.02)
        clat, clon = hail.cell_centre(row, col)
        # the polygon's east edge lies between the cell centre (inside) and a point 0.001 degree east of it (outside);
        # both are in the same cell, so the centre rule says inside and the point rule says outside
        ring = [(clon - 0.01, clat - 0.01), (clon + 0.0005, clat - 0.01), (clon + 0.0005, clat + 0.01),
                (clon - 0.01, clat + 0.01)]
        towns = [{"name": "Edge", "lat": clat, "lon": clon + 0.001}]
        ev = {"k": "FL", "s": "W", "b": utc(2025, 6, 15), "e": utc(2025, 6, 16), "o": "TFX", "eventid": "7",
              "vtec_year": "2025", "rings": [ring]}
        ctx = J.Context()
        ctx.ww_all = [ev]
        check = J.town_checks(ctx, towns)
        self.assertEqual(check["events_checked"], 1)
        self.assertEqual(check["towns"][0]["cell"], [row, col])
        self.assertEqual(len(check["disagreements"]), 1)
        self.assertEqual((check["disagreements"][0]["point_inside"], check["disagreements"][0]["centre_inside"]),
                         (False, True))

    def test_a_matched_ncei_pair_offset_is_recorded_and_an_off_zero_pair_is_listed(self):
        rec_a = [0, 1000, 47.0, -110.0, "hail", "1.75", "in", "", "PUBLIC", "X", "", None, None, ""]
        lsr_a = [0, 1000, 47.0, -110.0, "H", "1.75", "in", "", "PUBLIC", "X", "", "hail"]
        rec_b = [0, 1200, 47.5, -110.5, "hail", "1.00", "in", "", "PUBLIC", "Y", "", None, None, ""]
        lsr_b = [0, 1300, 47.5, -110.5, "H", "1.00", "in", "", "PUBLIC", "Y", "", "hail"]
        events = {"reports": [lsr_a, lsr_b], "records": [rec_a, rec_b]}
        out = J._ncei_pairs(events)
        self.assertEqual(out["pairs"], 2)
        self.assertEqual(out["offsets"], {"0.0": 1, "1.0": 1})
        self.assertEqual(out["on_rule"], 1)
        self.assertEqual(len(out["off_rule"]), 1)


class WordsB5Tests(unittest.TestCase):
    def test_the_b5_unavailable_line_ends_with_the_negation(self):
        # rules-13 and D41: every unavailable line ends with the required sentence, the D20 sentence included
        self.assertTrue(J.WORDS_JOINS["county_unavailable"].endswith("This is not an all-clear."))
        self.assertTrue(J.WORDS_JOINS["unavailable"].endswith("This is not an all-clear."))

    def test_the_radar_sentence_is_the_brief_sentence(self):
        self.assertEqual(J.WORDS_JOINS["radar_sentence"], "Radar estimates can miss hail that people reported and can "
                                                          "show hail that no one reported.")

    def test_the_flooding_ice_and_heat_headings_are_written(self):
        self.assertEqual((J.WORDS_JOINS["section_flooding"], J.WORDS_JOINS["section_ice"],
                          J.WORDS_JOINS["section_heat"]), ("Flooding", "Ice and winter", "Heat"))

    def test_the_new_words_pass_the_forbidden_term_check(self):
        samples = [J.WORDS_JOINS["warnings_row_b5"].format(label="Warning", date="Jun 15, 2025",
                                                           span="1:00 pm MDT to 2:00 pm MDT",
                                                           product="flood warning", office="TFX", tags="none stated"),
                   J.WORDS_JOINS["warnings_row_point"].format(label="Warning", date="Jun 15, 2025",
                                                              span="1:00 pm MDT to 2:00 pm MDT", product="flash flood warning",
                                                              office="TFX", tags="none stated"),
                   J.WORDS_JOINS["warnings_span_none"].format(begin="1:00 pm MDT"),
                   J.WORDS_JOINS["county_row"].format(product="Flood watch", county_name="Judith Basin",
                                                      events="x"),
                   J.WORDS_JOINS["county_what"], J.WORDS_JOINS["hit_miss_summary"], J.WORDS_JOINS["about_hit_miss"],
                   J.WORDS_JOINS["period_note"], J.WORDS_JOINS["records_cause"].format(cause="Ice Jam"),
                   J.WORDS_JOINS["county_unavailable"], J.WORDS_JOINS["warnings_what"]]
        for text in samples:
            with self.subTest(text[:40]):
                check_words(self, text)

    def test_the_warning_words_say_covered_this_cell_or_part_of_it(self):
        self.assertIn("covered this cell or part of it", J.WORDS_JOINS["warnings_row_b5"])
        self.assertIn("covered this cell or part of it", J.WORDS_JOINS["warnings_what"])

    def test_the_browser_row_templates_keep_the_placeholders_the_browser_fills(self):
        """The record templates keep the B2 keys as db84d76 writes them: the browser fills these placeholders and no others.
        The warning rows are the B5 keys (D79(d): the B2 "warnings_row" is removed); the sheet and the town page fill the
        same placeholders in warnings_row_b5 and its _point twin."""
        from string import Formatter
        fields = {key: {field for _lit, field, _spec, _conv in Formatter().parse(J.WORDS_JOINS[key]) if field}
                  for key in ("warnings_row_b5", "warnings_row_point", "records_row", "records_row_here", "records_row_typed",
                              "records_row_here_typed")}
        self.assertEqual(fields["warnings_row_b5"], {"label", "date", "span", "product", "office", "tags"})
        self.assertEqual(fields["warnings_row_point"], fields["warnings_row_b5"])
        self.assertNotIn("warnings_row", J.WORDS_JOINS)
        self.assertEqual(fields["records_row"], {"date", "time", "type", "magnitude", "qualifier", "source", "miles",
                                                 "bearing"})
        self.assertEqual(fields["records_row_here_typed"], {"date", "time", "type", "qualifier", "source", "miles"})
        self.assertEqual(J.WORDS_JOINS["warnings_tags_none"], "none stated")
        self.assertIn("{cause}", J.WORDS_JOINS["records_row_b5"])
        self.assertNotIn("{cause}", J.WORDS_JOINS["records_row"])


@unittest.skipUnless(HAVE_PYSHP, "pyshp is not installed (the daily job installs it)")
class CountyFileTests(unittest.TestCase):
    def test_a_county_file_without_the_56_montana_counties_is_refused(self):
        import shapefile
        shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
        w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
        for name in ("STATEFP", "COUNTYFP", "NAME"):
            w.field(name, "C", size=10)
        w.poly([[(-110.0, 47.0), (-109.0, 47.0), (-109.0, 48.0), (-110.0, 47.0)]])
        w.record("30", "001", "Beaverhead")
        w.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("c.shp", shp.getvalue())
            zf.writestr("c.shx", shx.getvalue())
            zf.writestr("c.dbf", dbf.getvalue())
        with self.assertRaises(J.JoinsError):
            J.parse_county_zip(buf.getvalue())

    def test_the_cached_census_file_holds_the_56_montana_counties_with_their_iem_codes(self):
        path = Path("/home/user/hail-b5/cache/joins/counties/tl_2026_us_county.zip")
        if not path.is_file():
            self.skipTest("the county file is not in the cache")
        counties = J.parse_county_zip(path.read_bytes())
        self.assertEqual(len(counties), 56)
        self.assertEqual(counties[0]["zone"], "MTC001")
        self.assertEqual(counties[-1]["zone"], "MTC111")
        self.assertIn("Yellowstone", {c["name"] for c in counties})


class B5SheetTests(unittest.TestCase):
    """The sheet's county rows (from k/) and flagged station rows (from s/), read from a temporary store folder that this
    test makes and removes."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="b5-sheet-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write(self, rel, doc):
        path = self.root / "hail" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_a_county_flood_watch_shows_as_a_whole_county_row_and_a_lead(self):
        self._write("k/MTC045.json", {"f": J.COUNTY_FORMAT, "county": "MTC045", "name": "Judith Basin County",
                                      "events": [{"k": "FA", "s": "A", "b": "2025-01-10T07:00Z",
                                                  "e": "2025-01-11T08:00Z", "o": "TFX"}]})
        index = _index()
        index["joins"]["counties"] = {"state": "loaded", "names": {"MTC045": "Judith Basin County"}}
        doc = _cell_doc(counties={"MTC045": [GATE_KEY]})
        out = J.describe_joins(index, doc, *GATE, store_dir=self.root)
        sec = next(s for s in out["sections"] if s["id"] == "zones")
        texts = [row["text"] for row in sec["rows"]]
        self.assertIn("County product: Areal flood watch, whole county Judith Basin County: Jan 10, 2025 12:00 am MST to "
                      "Jan 11, 2025 1:00 am MST", texts)
        self.assertIn("1 county product for Judith Basin County between", " ".join(sec["lines"]))
        check_words(self, " ".join(sec["lines"]))

    def test_a_county_section_says_so_when_the_county_file_did_not_load(self):
        index = _index()
        index["joins"]["counties"] = {"state": "unavailable", "reason": "the file was in an unexpected format"}
        doc = _cell_doc(counties={"MTC045": [GATE_KEY]})
        out = J.describe_joins(index, doc, *GATE, store_dir=self.root)
        sec = next(s for s in out["sections"] if s["id"] == "zones")
        self.assertIn(J.WORDS_JOINS["county_unavailable"], sec["lines"])
        # D71: the line is written once when the county file is lost and the block says unavailable (it was written twice)
        self.assertEqual(sec["lines"].count(J.WORDS_JOINS["county_unavailable"]), 1)

    def test_a_flagged_station_reading_carries_the_flag_words(self):
        day = hail.day_index(date(2025, 2, 20))
        self._write("s/HVR.json", {"f": J.STATION_FORMAT, "id": "HVR", "name": "Havre", "lat": 47.05, "lon": -110.12,
                                   "days": [[day, 121, 105, 1]], "dropped": 0})
        index = _index()
        doc = _cell_doc(stations=[{"id": "HVR", "name": "Havre", "lat": 47.05, "lon": -110.12, "miles": 5.0}])
        out = J.describe_joins(index, doc, *GATE, store_dir=self.root)
        sec = next(s for s in out["sections"] if s["id"] == "stations")
        self.assertEqual(len(sec["rows"]), 1)
        self.assertTrue(sec["rows"][0]["text"].endswith(J.WORDS_JOINS["flag_suffix"]), sec["rows"][0]["text"])
        self.assertIn(J.WORDS_JOINS["flag_check_line"], sec["lines"])
        check_words(self, sec["rows"][0]["text"])


class NotRunTests(unittest.TestCase):
    """F15: a check that did not run is named under not_run with its reason, and it never passes; ok is the checks that
    ran. Each store here is a copy of the committed fixture with its index edited (the copy's manifest is updated)."""

    def _copy_with_index(self, edit) -> Path:
        root = Path(tempfile.mkdtemp(prefix="joins-test-notrun-"))
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(FIXTURE, root / "store")
        store = root / "store"
        index_path = store / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        edit(index[J.INDEX_KEY])
        data = (json.dumps(index, indent=1, sort_keys=True) + "\n").encode("utf-8")
        index_path.write_bytes(data)
        manifest_path = store / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["hail/index.json"] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        return store

    @staticmethod
    def _towns(count=17):
        return [{"town": f"Town {i}", "cell": [1, 2], "point_inside": 0, "centre_inside": 0} for i in range(count)]

    def _d11(self, result):
        return [item for item in result["not_run"] if item["name"].startswith("D11: the town point check")]

    def test_the_committed_fixture_names_the_town_check_as_absent_from_its_store(self):
        result = J.verify(FIXTURE)
        self.assertTrue(result["ok"], result["checks"])
        self.assertFalse(any(c["name"].startswith("D11: the town point check") for c in result["checks"]))
        self.assertEqual([item["reason"] for item in self._d11(result)], ["this store has no town_checks block"])
        reasons = {item["name"]: item["reason"] for item in result["not_run"]}
        counties = [v for k, v in reasons.items() if k.startswith("source 4")]
        self.assertEqual(counties, ["this store is the three-day fixture, so it does not hold every Montana cell's county"])
        self.assertTrue(all(item["reason"] for item in result["not_run"]), result["not_run"])

    def test_a_warnings_part_that_did_not_load_says_so_and_the_town_check_does_not_pass(self):
        def edit(block):
            block["parts"]["warnings"] = "unavailable"
            block["town_checks"] = {"towns": self._towns(), "events_checked": 1000, "pairs_tested": 5,
                                    "disagreements": []}
        result = J.verify(self._copy_with_index(edit))
        self.assertTrue(result["ok"], result["checks"])
        self.assertFalse(any(c["name"].startswith("D11: the town point check") for c in result["checks"]))
        self.assertEqual([item["reason"] for item in self._d11(result)], ["warnings part unavailable"])

    def test_a_partial_warnings_part_does_not_pass_the_full_17_town_check_and_lists_the_years_not_covered(self):
        def edit(block):
            block["parts"]["warnings"] = "partial"
            block["unavailable_units"] = {"warnings": ["SV.W 2023", "FF.A 2024", "SV.W 2023"]}
            block["town_checks"] = {"towns": self._towns(), "events_checked": 1000, "pairs_tested": 5,
                                    "disagreements": []}
        result = J.verify(self._copy_with_index(edit))
        self.assertTrue(result["ok"], result["checks"])
        self.assertFalse(any(c["name"].startswith("D11: the town point check") for c in result["checks"]))
        reason = self._d11(result)[0]["reason"]
        self.assertEqual(reason, "warnings part partial: the files for 2023, 2024 did not load, so those years are not "
                                 "checked")

    def test_a_partial_warnings_part_with_only_cached_units_says_the_cache_served_them(self):
        def edit(block):
            block["parts"]["warnings"] = "partial"
            block["town_checks"] = {"towns": self._towns(), "events_checked": 1000, "pairs_tested": 5,
                                    "disagreements": []}
        result = J.verify(self._copy_with_index(edit))
        self.assertEqual(self._d11(result)[0]["reason"],
                         "warnings part partial: some files were served from the cache after a failed request")

    def test_a_store_with_no_polygon_read_says_so(self):
        def edit(block):
            block["town_checks"] = {"towns": self._towns(), "events_checked": 0, "pairs_tested": 0, "disagreements": []}
        result = J.verify(self._copy_with_index(edit))
        self.assertEqual([item["reason"] for item in self._d11(result)], ["no polygon event was read in this store"])

    def test_the_town_check_passes_only_when_the_warnings_part_loaded_and_all_17_towns_are_checked(self):
        def edit(block):
            block["town_checks"] = {"towns": self._towns(), "events_checked": 1000, "pairs_tested": 5,
                                    "disagreements": []}
        result = J.verify(self._copy_with_index(edit))
        self.assertTrue(result["ok"], result["checks"])
        self.assertIn("D11: the town point check ran for the 17 towns",
                      [c["name"] for c in result["checks"] if c["ok"]])
        self.assertEqual(self._d11(result), [])

    def test_the_town_check_fails_when_a_loaded_store_checks_fewer_than_17_towns(self):
        def edit(block):
            block["town_checks"] = {"towns": self._towns(16), "events_checked": 1000, "pairs_tested": 5,
                                    "disagreements": []}
        result = J.verify(self._copy_with_index(edit))
        self.assertFalse(result["ok"])
        self.assertFalse(any(c["ok"] for c in result["checks"] if c["name"] == "D11: the town point check ran for the 17 towns"))


class HitMissRecordTests(unittest.TestCase):
    """D15 and gate 17: the hit-and-miss table, its named cases, and the research case outside the window."""

    STORE_START = datetime(2021, 10, 17, 12, tzinfo=timezone.utc)

    def test_the_named_rows_are_inside_the_window_and_the_research_case_is_before_it(self):
        for case in J.HIT_MISS_ROWS:
            when = datetime.strptime(case["utc"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            self.assertGreaterEqual(when, self.STORE_START, case["name"])
            self.assertLess(when, datetime(2026, 10, 17, 12, tzinfo=timezone.utc), case["name"])
        self.assertEqual([c["name"] for c in J.HIT_MISS_ROWS], ["Lewistown", "Petrolia Lake"])
        glendive = J.KNOWN_HAIL_CASES[0]
        self.assertEqual((glendive["name"], glendive["in"], glendive["mesh_mm_research"]), ("Glendive", "4.00", 14.4))
        self.assertLess(datetime.strptime(glendive["utc"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc),
                        self.STORE_START)

    def test_hits_misses_and_the_round_down_of_a_radar_value_in_the_table(self):
        day = hail.day_index(date(2025, 6, 15))
        reports = [
            [day, 2010, 47.08, -110.02, "H", "1.75", "in", "E", "Public", "Benchland", ""],     # MESH 1.00 in: a hit
            [day, 900, 46.90, -108.30, "H", "1.00", "in", "M", "Spotter", "X", ""],            # MESH 0.996 in: a miss
            [day, 1200, 46.50, -109.00, "H", "1.25", "in", "M", "Spotter", "Y", ""],           # SWDI 2.00 in: a hit
            [day, 1300, 45.50, -107.50, "H", "1.50", "in", "M", "Spotter", "Z", ""],           # nothing: a miss
            [day, 1400, 45.00, -108.00, "H", "0.75", "in", "M", "Spotter", "W", ""],           # under one inch: not listed
            [day, 1500, 45.10, -108.10, "G", "58", "mph", "M", "Mesonet", "V", ""],            # a gust: not listed
        ]
        mesh = {(47.08, -110.02): 254, (46.90, -108.30): 253}
        swdi = {(46.50, -109.00): 2.0}

        def fake_mesh(root, index, lat, lon, day_):
            return mesh.get((lat, lon), 0) / J.hail.TENTHS_PER_INCH

        def fake_swdi(root, index, lat, lon, day_):
            return swdi.get((lat, lon), 0.0)

        with mock.patch.object(J, "_mesh_in", side_effect=fake_mesh), mock.patch.object(J, "_swdi_in", side_effect=fake_swdi):
            out = J._hit_and_miss(None, {}, {"reports": reports})
        rows = out["rows"]
        self.assertEqual([r["hit"] for r in rows], [True, False, True, False])
        self.assertEqual(rows[1]["mesh_in"], 0.99)         # 253 tenths is 0.996 in: shown rounded down, a miss
        self.assertEqual(rows[0]["mesh_in"], 1.0)
        self.assertEqual(out["summary"]["reports"], 4)
        self.assertEqual((out["summary"]["hits"], out["summary"]["misses"]), (2, 2))
        self.assertEqual(out["summary"]["misses_under_by_max_in"], 1.5)

    def test_the_fixture_does_not_run_the_named_rows_and_says_which_tile_is_missing(self):
        result = J.verify(FIXTURE)
        names = {item["name"]: item["reason"] for item in result["not_run"]}
        self.assertEqual(names["D15: the named case Lewistown (2.50 in, 2025-06-15T22:48Z) is in the table"],
                         "this store has no tile for Lewistown")
        self.assertEqual(names["D15: the named case Petrolia Lake (3.50 in, 2025-06-16T01:01Z) is in the table"],
                         "this store has no tile for Petrolia Lake")
        self.assertTrue(any(c["name"] == "D15: the hit-and-miss table holds no report before the window start" and c["ok"]
                            for c in result["checks"]))

    def test_the_record_writes_the_research_case_as_a_research_value(self):
        result = J.verify(FIXTURE)
        cases = result["b5"]["hit_and_miss"]["research_cases"]
        self.assertEqual([c["name"] for c in cases], ["Glendive"])
        self.assertIn("not a table row", cases[0]["note"])
        first, last = hail.load_index(FIXTURE)["window"]          # the sample's own window (B1's sample starts a day earlier)
        self.assertEqual(result["b5"]["windows"]["store"], [f"{first}T12:00Z", f"{date.fromisoformat(last) + timedelta(days=1)}T12:00Z"])
        self.assertEqual(result["b5"]["windows"]["research"], ["2021-10-19T00:00Z", "2026-10-19T00:00Z"])


class CompareWindowTests(unittest.TestCase):
    """F26: the research window is named where the B5 rows of compare are written, and _hays_check takes the store's start."""

    def test_the_b5_rows_of_compare_name_the_research_window(self):
        block = {"compare": {"lsr_hail": 0, "lsr_g": 0, "ncei_hail_by_year": {}, "swdi_montana_polygon": 0,
                             "sv_events": 0, "to_events": 0}, "built_at": "2026-10-19T00:00:00Z",
                 "station_days_by_year": {}, "vtec_counts_research": {}}
        fake = {"window": ["2021-10-17", "2026-10-16"], J.INDEX_KEY: block}
        with mock.patch.object(J, "load_joins_index", return_value=fake):
            rows = J.compare("unused")["rows"]
        notes = [r["note"] for r in rows if r["name"].startswith("B5 window events")]
        self.assertTrue(notes, rows[:3])
        for note in notes:
            self.assertIn("2021-10-19 00:00 UTC to 2026-10-19 00:00 UTC", note)
            self.assertIn("2021-10-17 12:00 UTC to 2026-10-17 12:00 UTC", note)

    def test_the_hays_check_uses_the_window_start_it_is_given(self):
        empty = {"records": []}
        self.assertTrue(J._hays_check(empty, datetime(2021, 10, 17, 12, tzinfo=timezone.utc))["outside_window"])
        self.assertFalse(J._hays_check(empty, datetime(2021, 6, 1, tzinfo=timezone.utc))["outside_window"])


class CountyProductLabelTests(unittest.TestCase):
    """F08: a county-coded row starts with "County product:" (its own label), never "Zone product:"; a polygon warning that
    is joined by county reads the same way."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="joins-test-county-label-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write_county(self, events):
        path = self.root / "hail" / "k" / "MTC045.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"f": J.COUNTY_FORMAT, "county": "MTC045", "name": "Judith Basin County",
                                    "events": events}), encoding="utf-8")

    def _zones_rows(self):
        index = _index()
        index["joins"]["counties"] = {"state": "loaded", "names": {"MTC045": "Judith Basin County"}}
        doc = _cell_doc(counties={"MTC045": [GATE_KEY]})
        out = J.describe_joins(index, doc, *GATE, store_dir=self.root)
        return next(s for s in out["sections"] if s["id"] == "zones")["rows"]

    def test_county_rows_start_with_county_product_and_no_k_row_says_zone_product(self):
        self._write_county([{"k": "FA", "s": "A", "b": "2025-01-10T07:00Z", "e": "2025-01-11T08:00Z", "o": "TFX"},
                            {"k": "FF", "s": "A", "b": "2025-02-01T01:00Z", "e": "2025-02-01T05:00Z", "o": "TFX"}])
        rows = self._zones_rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row["text"].startswith("County product: "), row["text"])
            self.assertFalse(row["text"].startswith("Zone product:"), row["text"])
        check_words(self, J.WORDS_JOINS["county_row"].format(product="Flood watch", county_name="X", events="y"))

    def test_a_polygon_warning_joined_by_county_reads_as_a_county_product_row(self):
        ctx = zone_ctx([])
        ctx.county_map = [{"zone": "MTC045", "name": "Judith Basin", "rings": [[(-110.5, 46.5), (-109.5, 46.5),
                                                                              (-109.5, 47.5), (-110.5, 47.5), (-110.5, 46.5)]]}]
        null = {"k": "FL", "s": "W", "o": "TFX", "eventid": "9", "vtec_year": "2025", "b": utc(2025, 6, 15, 1),
                "e": utc(2025, 6, 15, 9)}
        ctx.ww_nulls = [dict(null)]
        ctx.poly_rows = [dict(zone_row("MTC045", "FL", "CAN", utc(2025, 6, 15, 2), utc(2025, 6, 15, 5), eventid="9"),
                              phen="FL", sig="W")]
        J._join_nulls(ctx, *WINDOW)
        self.assertEqual(ctx.null_polygons["joined"], 1)
        self._write_county([dict(e) for e in ctx.county_events["MTC045"]])
        rows = self._zones_rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["text"].startswith("County product: Flood warning, whole county Judith Basin County"),
                        rows[0]["text"])


class WordRulesTests(unittest.TestCase):
    """F09, F10 and F29: the one allowed "no hail", the decodable hit-and-miss sentence, and the shared list over every
    joins word and over the sentences the describe functions build on the fixture spot."""

    def test_no_hail_appears_in_a_joins_word_only_inside_not_the_same_as_no_hail(self):
        for key, text in J.WORDS_JOINS.items():
            if not isinstance(text, str):
                continue
            with self.subTest(key):
                self.assertEqual(len(re.findall(r"\bno hail\b", text, re.IGNORECASE)),
                                 len(re.findall(r"not the same as no hail", text)), text)

    def test_the_detection_sentence_carries_the_allowed_phrase(self):
        text = J.WORDS_JOINS["detections_lead_none"].format(start="Jun 1, 2025", end="Jun 30, 2025")
        self.assertTrue(text.endswith("so this is not the same as no hail."), text)

    def test_the_hit_and_miss_sentence_says_what_it_shows_in_plain_words(self):
        self.assertEqual(J.WORDS_JOINS["hit_miss_summary"],
                         "At the report's own cell, radar estimates showed hail of one inch or more at fewer than half of "
                         "the NWS hail reports of one inch or more. Counting radar detections within 2 miles as well, most "
                         "reports had a radar value of one inch or more. A radar miss, where neither showed one inch or "
                         "more, is not a finding about the hail that fell.")
        text = J.WORDS_JOINS["hit_miss_summary"]
        self.assertIn("radar estimates", text)                 # the kind word Radar estimate
        self.assertIn("NWS hail reports", text)                # the kind word Report
        check_words(self, text)

    def test_every_joins_word_passes_the_shared_list(self):
        for key, text in J.WORDS_JOINS.items():
            if isinstance(text, str):
                with self.subTest(key):
                    W.assert_clean(self, text, key)

    def test_the_rendered_sentences_on_the_fixture_spot_pass_the_shared_list(self):
        index = hail.load_index(FIXTURE)
        for tile, cell in ((GATE_TILE, GATE), ("r0092_c0214", (922, 2140))):
            doc = json.loads((FIXTURE / "hail" / "j" / f"{tile}.json").read_text())
            out = J.describe_joins(index, doc, *cell, store_dir=FIXTURE)
            for section in out["sections"]:
                for text in [section.get("heading") or "", section.get("lead") or "", section.get("what") or ""] + \
                        [r["text"] for r in section["rows"]] + list(section.get("lines", [])):
                    if text:
                        W.assert_clean(self, text, f"{tile} {section['id']}")

    def test_the_shared_list_flags_what_it_should_and_allows_what_the_brief_allows(self):
        self.assertEqual(W.forbidden_words("Risk of hail."), ["risk"])
        self.assertEqual(W.forbidden_words("A damage claim."), ["claim", "damage"])
        self.assertEqual(W.forbidden_words("Structural limits."), ["structural"])
        self.assertTrue(W.has_no_hail("No hail fell here."))
        self.assertFalse(W.has_no_hail("This is not the same as no hail."))
        self.assertEqual(W.forbidden_words("NWS damage threat tag: considerable"), [])
        self.assertEqual(W.forbidden_words("Remark, as written: “structure damage”"), [])
        self.assertEqual(W.forbidden_words("USA Structures"), [])
        self.assertEqual(W.forbidden_words("This is not an all-clear."), [])
        self.assertEqual(W.forbidden_words("Pass an all-clear."), ["all-clear"])
        self.assertEqual(W.forbidden_words("Warrant: a warrant."), ["warrant"])     # the words found, once each


def _zone_csv(rows) -> bytes:
    """An IEM watchwarn CSV of HW.W rows (the columns parse_ww_csv reads)."""
    head = ("wfo,utc_issue,utc_expire,utc_prodissue,phenomena,gtype,significance,eventid,status,ugc,vtec_year,"
            "hailtag,windtag,tornadotag,damagetag\n")
    lines = [f"{r['wfo']},{r['issue']:%Y-%m-%d %H:%M},{r['expire']:%Y-%m-%d %H:%M},{r['prod']:%Y-%m-%d %H:%M},HW,C,W,"
             f"{r['eid']},{r['status']},{r['ugc']},{r['yr']},,,," for r in rows]
    return (head + "".join(line + "\n" for line in lines)).encode("utf-8")


class ZoneRowsOnceTests(unittest.TestCase):
    """D17: a zone row that two yearly requests share (the margins, B5) is read once, across every year and product, so no
    copied row opens a phantom period (a cancellation read twice closed the period and opened a second one)."""

    ROWS = [
        {"wfo": "TFX", "issue": utc(2021, 12, 30, 12), "expire": utc(2022, 1, 1, 12), "prod": utc(2021, 12, 30, 12),
         "eid": 7, "status": "NEW", "ugc": "MTZ012", "yr": 2021},
        {"wfo": "TFX", "issue": utc(2022, 1, 1, 13), "expire": utc(2022, 1, 1, 13), "prod": utc(2022, 1, 1, 13),
         "eid": 7, "status": "CAN", "ugc": "MTZ012", "yr": 2021},
    ]

    def _responder(self):
        rows = self.ROWS

        def responder(url, params):
            if url == J.WW_URL and params.get("accept") == "csv" and params.get("phenomena[]") == "HW" \
                    and params.get("significance[]") == "W":
                lo = datetime(int(params["year1"]), int(params["month1"]), 1, tzinfo=timezone.utc)
                hi = datetime(int(params["year2"]), int(params["month2"]), 28, tzinfo=timezone.utc)
                return _zone_csv([r for r in rows if lo <= r["issue"] <= hi])
            return canned(url, params)
        return responder

    def test_a_row_two_requests_share_is_kept_once_and_its_cancellation_closes_one_period(self):
        index = _index()
        index["window"] = ["2021-10-19", "2022-12-31"]                 # two request years, so the margins overlap
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-zone-once-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        fetcher = FakeFetcher(tmp / "cache", None, self._responder())
        ctx = J._collect(fetcher, index, date(2026, 10, 18))
        mine = [r for r in ctx.zone_rows if r["ugc"] == "MTZ012" and r["phen"] == "HW"]
        self.assertEqual(sorted(r["status"] for r in mine), ["CAN", "NEW"])
        self.assertEqual(ctx.zone_row_copies, 2)
        ctx.zone_map = [{"zone": "MTZ012", "name": "Test zone", "rings": []}]
        start, end, _first, _last = J.window_utc(index)
        events = J._zone_events(ctx, start, end)["MTZ012"]
        self.assertEqual([(e["b"], e["e"], e.get("st")) for e in events],
                         [("2021-12-30T12:00Z", "2022-01-01T13:00Z", "cancelled")])

    def test_the_key_names_the_row_not_its_request(self):
        # a row as parse_ww_csv keeps it, with its product's phen and sig added
        row = {"wfo": "TFX", "phen": "HW", "sig": "W", "eventid": "7", "status": "NEW", "ugc": "MTZ012",
               "vtec_year": "2021", "issue": utc(2021, 12, 30, 12), "expire": utc(2022, 1, 1, 12),
               "gtype": "C", "prod": utc(2021, 12, 30, 12)}
        self.assertEqual(J.zone_row_key(row), J.zone_row_key(dict(row)))
        self.assertNotEqual(J.zone_row_key(row), J.zone_row_key(dict(row, status="CON")))
        self.assertNotEqual(J.zone_row_key(row), J.zone_row_key(dict(row, phen="WS")))


class TigerTermsTests(unittest.TestCase):
    """rules-F23: the TIGER use constraint is quoted verbatim, the research record's own words for the state file and the
    county file's words as its ISO metadata gives them (joins' module docstring)."""

    RECORD = ("The TIGER/Line Shapefile products are not copyrighted however TIGER/Line and Census TIGER are registered "
              "trademarks of the U.S. Census Bureau. These products are free to use in a product or publication, however "
              "acknowledgement must be given to the U.S. Census Bureau as the source.")
    COUNTY = ("The TIGER/Line shapefile products are not copyrighted; however, TIGER/Line and Census TIGER are registered "
              "trademarks of the U.S. Census Bureau. These products are free to use in a product or publication, however "
              "acknowledgement must be given to the U.S. Census Bureau as the source.")

    def test_the_use_constraints_are_quoted_verbatim(self):
        doc = " ".join(J.__doc__.split())
        self.assertIn(self.RECORD, doc)
        self.assertIn(self.COUNTY, doc)
        self.assertNotIn("registered trademarks ...", doc)          # the abbreviated variant is not what the record says


class HwAWindowNoteTests(unittest.TestCase):
    """rules-F26: the compare step records the HW.A window note: HW.A has no NEW rows, so its begin is the earliest CON."""

    def test_the_compare_step_records_the_hw_a_note(self):
        block = {"compare": {"lsr_hail": 0, "lsr_g": 0, "ncei_hail_by_year": {}, "swdi_montana_polygon": 0,
                             "sv_events": 0, "to_events": 0}, "built_at": "2026-10-19T00:00:00Z",
                 "station_days_by_year": {}, "vtec_counts_research": {"HW.A": {"window": 277, "zone": 277}}}
        fake = {"window": ["2021-10-17", "2026-10-16"], J.INDEX_KEY: block}
        with mock.patch.object(J, "load_joins_index", return_value=fake):
            rows = J.compare("unused")["rows"]
        hw = next(r for r in rows if r["name"] == "B5 window events HW.A")
        self.assertEqual(hw["research"], 277)
        self.assertIn("HW.A has no NEW rows in the archive", hw["note"])
        self.assertIn("earliest CON issue", hw["note"])
        self.assertIn(J.B5_WINDOW_NOTES["HW.A"], hw["note"])


class B5PartB1Tests(unittest.TestCase):
    """B5 part B1 (D27, D29, D30 and the wording rulings): the zone editions and their placement, a kind word for every
    product, the per-tile events files, and the sentences the brief quotes."""

    FIXTURE = Path(__file__).resolve().parent.parent / "website" / "data" / "hail-fixture" / "hail"

    def test_every_product_code_the_store_holds_has_an_nws_kind_word(self):
        """D29: every product code the store joins (the polygon and zone products, the fire weather zone product and
        every code in the committed sample's events, zone, fire and county files) has a kind word by its NWS name."""
        codes = {f"{p}.{s}" for p, s in J.POLYGON_PRODUCTS + J.ZONE_PRODUCTS}
        for path in (self.FIXTURE / "j" / J.EVENTS_NAME,):
            doc = json.loads(path.read_text(encoding="utf-8"))
            codes |= {f"{row['k']}.{row['s']}" for row in doc["warnings"]}
        for folder in ("z", "k"):
            for path in (self.FIXTURE / folder).glob("*.json"):
                doc = json.loads(path.read_text(encoding="utf-8"))
                codes |= {f"{ev['k']}.{ev['s']}" for ev in doc.get("events", [])}
        self.assertTrue(len(codes) >= 20, sorted(codes))
        for code in sorted(codes):
            name = J.KIND_WORDS.get(code)
            self.assertIsNotNone(name, f"no kind word for {code}")
            self.assertNotEqual(name, code)
            self.assertRegex(name, r"^[a-z]", code)
            self.assertNotRegex(name, r"\bwarning warning\b", code)
            self.assertEqual(name, J.PRODUCT_NAMES[code][:1].lower() + J.PRODUCT_NAMES[code][1:], code)

    def test_a_warning_row_names_its_product_and_never_reads_as_a_bare_code(self):
        item = {"k": "FA", "s": "Y", "o": "TFX", "b": utc(2025, 1, 10, 7), "e": utc(2025, 1, 11, 8),
                "tags": {"hail_in": None, "wind_mph": None, "tornado": None, "damage": None}}
        text = J._warning_text(item["b"], item["e"], item, J.WORDS_JOINS)
        self.assertIn("Advisory: Jan 10, 2025 12:00 am MST to Jan 11, 2025 1:00 am MST: areal flood advisory, TFX, covered "
                      "this cell or part of it; tags: none stated", text)
        self.assertNotIn("FA warning", text)
        self.assertFalse(text.startswith("Warning:"))           # D41: an advisory is never labelled a warning
        item = dict(item, k="FL", s="A")
        watch = J._warning_text(item["b"], item["e"], item, J.WORDS_JOINS)
        self.assertTrue(watch.startswith("Watch: "), watch)
        self.assertIn(": flood watch, TFX, covered this cell or part of it", watch)
        item = dict(item, k="SQ", s="W")
        snow = J._warning_text(item["b"], item["e"], item, J.WORDS_JOINS)
        self.assertTrue(snow.startswith("Warning: "), snow)
        self.assertIn(": snow squall warning, TFX, covered this cell or part of it", snow)

    def test_the_browser_phenomenon_words_cover_each_significance_in_the_store(self):
        words = J.PHENOMENON_KIND_WORDS
        self.assertEqual(set(words), {"SV", "TO", "FF", "FL", "FA", "SQ"})
        self.assertIn("advisory", words["FA"])
        self.assertIn("watch", words["FL"])
        self.assertIn("advisory", words["FL"])
        self.assertNotIn("FA", " ".join(words.values()))

    def test_the_change_history_editions_are_dated_by_their_names_and_all_predate_the_published_ones(self):
        dates = [J.zone_name_date(name) for name in J.ZONE_EDITION_ARCHIVE]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(dates[0], date(2021, 9, 8))
        self.assertEqual(dates[-1], date(2024, 3, 5))
        self.assertTrue(all(day < date(2025, 3, 18) for day in dates))
        self.assertEqual(J.zone_name_date("z_18mr25.zip"), date(2025, 3, 18))
        self.assertEqual(J.zone_name_date("z_16ap26.zip"), date(2026, 4, 16))
        self.assertIn("zone_ch_log.txt", J.ZONE_CHANGE_LOG_URL)

    def test_a_product_under_an_edition_the_nws_does_not_publish_is_placed_by_the_iem_set_in_force(self):
        """D44: the edition in force decides the placement. An archived edition the NWS does not publish gives way to the IEM
        zone set in force at the issue time; a read older edition maps its code ("mapped"); the current edition places the
        code by name ("current"); a code no zone holds is unplaced with its reason."""
        ctx = _placement_ctx()
        names = {z["zone"] for z in ctx.zone_map}
        p = J._place(ctx, names, "MTZ001", utc(2021, 12, 1, 12))
        self.assertEqual((p["zone"], p["set"], p["how"], p["outline"]), ("MTZ001", "2021-09-15T12:00:00Z", "iem", "nws"))
        p = J._place(ctx, names, "MTZ008", utc(2022, 3, 1, 12))
        self.assertEqual((p["zone"], p["how"], p["outline"], p["reason"]), ("MTZ008", "iem", "iem", None))
        p = J._place(ctx, names, "MTZ008", utc(2025, 6, 1, 12))
        self.assertEqual((p["zone"], p["set"], p["how"], p["reason"]), (None, "z_18mr25.zip", "mapped", "retired_zone"))
        p = J._place(ctx, names, "MTZ301", utc(2026, 5, 1, 12))
        self.assertEqual((p["zone"], p["set"], p["how"]), ("MTZ301", "z_16ap26.zip", "current"))
        self.assertEqual(J._place(ctx, names, "MTZ301", utc(2022, 11, 1, 12))["zone"], "MTZ301")

    def test_a_zone_group_is_counted_per_product_set_and_way_with_the_outline_it_took(self):
        ctx = J.Context()
        J._note_placed(ctx, "WW.Y", {"zone": "MTZ008", "set": "2021-09-15T12:00:00Z", "how": "iem", "outline": "iem",
                                     "reason": None})
        J._note_placed(ctx, "WW.Y", {"zone": "MTZ001", "set": "2022-09-13T12:00:00Z", "how": "changeover",
                                     "outline": "nws", "reason": None})
        J._note_placed(ctx, "WW.Y", {"zone": "MTZ301", "set": "z_16ap26.zip", "how": "current", "outline": "nws",
                                     "reason": None})
        J._note_unplaced(ctx, "WW.Y", "MTZ010", utc(2022, 9, 14, 12),
                         {"zone": None, "set": "2022-09-13T18:00:00Z", "how": "iem", "outline": None,
                          "reason": "not_in_iem_set"})
        self.assertEqual(ctx.zone_placement, {"WW.Y": {"2021-09-15T12:00:00Z": {"iem": 1},
                                                       "2022-09-13T12:00:00Z": {"changeover": 1},
                                                       "z_16ap26.zip": {"current": 1}}})
        self.assertEqual(ctx.zone_simplified, 1)
        self.assertEqual(ctx.zone_unplaced_rows, [["WW.Y", "MTZ010", "2022-09-14", "2022-09-13T18:00:00Z",
                                                   "not_in_iem_set"]])
        self.assertEqual(J._placement_table(ctx), {"groups": 4, "current": 1, "mapped": 0, "iem_set": 1,
                                                   "changeover_week": 1, "unplaced": 1, "expected_unplaced": 0,
                                                   "simplified_outline": 1})

    def test_the_zone_words_say_in_these_five_years_and_the_zone_set_in_force(self):
        for key in ("zones_unplaced_one", "zones_unplaced_many", "records_unplaced_one", "records_unplaced_many"):
            text = J.WORDS_JOINS[key]
            self.assertIn("in these five years", text, key)
            self.assertNotIn("in the window", text, key)
            self.assertNotIn("page links", text, key)
            check_words(self, text.format(n=2))
        self.assertIn("zone set in force", J.WORDS_JOINS["zones_unplaced_one"])
        self.assertNotIn("zones_kept_one", J.WORDS_JOINS)
        check_words(self, J.WORDS_JOINS["zones_before_line_one"].format(n=1, zone_name="Beaverhead", zone="MTZ008"))
        check_words(self, J.WORDS_JOINS["zones_before_line_many"].format(n=3, zone_name="Beaverhead", zone="MTZ008"))
        check_words(self, J.WORDS_JOINS["about_iem_zones"])
        self.assertIn("You are free to use these services for any lawful purpose", J.WORDS_JOINS["about_iem_zones"])
        self.assertIn("does not publish", J.WORDS_JOINS["reason_not_published"])
        self.assertIn("HTTP 404", J.WORDS_JOINS["reason_not_published"])

    def test_the_radar_sentence_and_the_about_sentence_for_hail_misses_are_as_the_brief_states(self):
        self.assertEqual(J.WORDS_JOINS["radar_sentence"], "Radar estimates can miss hail that people reported and can "
                                                          "show hail that no one reported.")
        about = J.WORDS_JOINS["about_hit_miss"]
        self.assertTrue(about.startswith("NWS hail reports of one inch or more were checked against the radar "
                                         "estimate"))
        self.assertIsNone(re.search(r"\d", about), about)          # the About summary is in words, without numbers
        check_words(self, about)
        check_words(self, J.WORDS_JOINS["radar_sentence"])

    def test_a_tile_events_file_holds_the_rows_its_tile_refers_to_under_their_own_indexes(self):
        reports = [["r0"], ["r1"], ["r2"]]
        records = [["c0"]]
        warnings = [{"k": "SV", "s": "W"}, {"k": "FA", "s": "Y"}]
        doc = {"r": 93, "c": 194, "reports": [2, 0], "records": [], "warnings": [[1, "0" * 25]]}
        out = J._tile_events(doc, reports, records, warnings)
        self.assertEqual(out["f"], J.TILE_EVENTS_FORMAT)
        self.assertEqual(out["reports"], {"2": ["r2"], "0": ["r0"]})
        self.assertEqual(out["records"], {})
        self.assertEqual(out["warnings"], {"1": {"k": "FA", "s": "Y"}})

    def test_the_events_block_names_the_largest_files_and_the_budget(self):
        block = J._events_tiles_block([("r1.json", 100, 50), ("r2.json", 300, 20), ("r3.json", 200, 50)],
                                      {"reports": 4, "records": 1, "warnings": 2})
        self.assertEqual(block["format"], "hail-events-tile-v1")
        self.assertEqual(block["count"], 3)
        self.assertEqual(block["largest_raw"], {"file": "r2.json", "bytes": 300})
        self.assertEqual(block["largest_gzip"], {"file": "r3.json", "bytes": 50})
        self.assertEqual(block["budget_gzip"], 100_000)
        self.assertEqual(block["gzip_bytes"], 120)
        self.assertEqual(block["referenced"], {"reports": 4, "records": 1, "warnings": 2})

    def test_the_committed_fixture_has_an_events_file_for_every_tile_and_its_index_names_them(self):
        index = json.loads((self.FIXTURE / "index.json").read_text(encoding="utf-8"))
        block = index[J.INDEX_KEY]
        self.assertEqual(block["events_tiles"]["format"], "hail-events-tile-v1")
        self.assertEqual(block["events_tiles"]["count"], len(index["tiles"]))
        for tile in index["tiles"]:
            path = self.FIXTURE / "j" / J.TILE_EVENTS_DIR / f"{tile}.json"
            self.assertTrue(path.is_file(), tile)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["f"], "hail-events-tile-v1")
        self.assertLessEqual(block["events_tiles"]["largest_gzip"]["bytes"], block["events_tiles"]["budget_gzip"])

    def test_the_wind_zone_contract_row_says_in_these_five_years_and_names_the_editions(self):
        """B2's 'in the window' phrase in the wind zone contract row is reworded (B5 part B1), and the row's edition
        sentence says what the build reads (D27): the two published editions and the six the NWS does not publish."""
        row = src.CONTRACTS["nws_zone_products"]
        missing = " ".join(row["missing"].split())
        request = " ".join(row["request"].split())
        self.assertIn("A zone with no product in these five years is listed as none, which is not the same as no wind.",
                      missing)
        self.assertNotIn("in the window", missing)
        self.assertNotIn("in the window", request)
        self.assertIn("z_18mr25.zip (effective 18 March 2025) and z_16ap26.zip (effective 16 April 2026)", request)
        self.assertIn("are not published (HTTP 404 when checked on 2026-10-19)", request)
        self.assertNotIn("the NWS links two editions", request)
        check_words(self, missing)


class TownsFileAndGustPeriodsTests(unittest.TestCase):
    """D37 and D38: each station gust file carries the days it reported in the five seasons; hail/j/towns.json lists the
    polygon products whose outline holds each town point, with the event id, the dates and the state of the warnings part;
    towns_file_check compares it with the cell covers, and a town event the cover lacks is a failure."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="joins-test-towns-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def square(lon0, lat0, lon1, lat1):
        return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]

    @staticmethod
    def ctx(events, state="loaded"):
        return SimpleNamespace(ww_events=events,
                               part_all_failed={"warnings": state == "unavailable"},
                               part_failures={"warnings": ["one file"] if state == "partial" else []},
                               part_reason={"warnings": "the file was in an unexpected format"})

    def test_a_town_lists_the_polygon_products_whose_outline_holds_its_point(self):
        inside = {"k": "FL", "s": "W", "o": "TFX", "b": datetime(2025, 6, 14, 0, 26, tzinfo=timezone.utc), "e": None,
                  "rings": [self.square(-110.2, 47.0, -109.9, 47.2)], "ref": 0}
        outside = {"k": "FA", "s": "Y", "o": "TFX", "b": datetime(2025, 6, 14, 0, 26, tzinfo=timezone.utc),
                   "e": datetime(2025, 6, 14, 1, 0, tzinfo=timezone.utc),
                   "rings": [self.square(-108.0, 46.0, -107.5, 46.5)], "ref": 1}
        towns = [{"slug": "testtown", "name": "Test Town", "lat": 47.1, "lon": -110.05}]
        doc = J.towns_polygon_file(self.ctx([inside, outside]), towns)
        self.assertEqual((doc["f"], doc["state"], doc["reason"]), (J.TOWNS_FORMAT, "loaded", None))
        events = doc["towns"]["testtown"]["events"]
        self.assertEqual([row[0] for row in events], [0])          # the event id is the events table's index
        self.assertEqual(events[0][1], "FL.W")
        self.assertIsNone(events[0][4])                            # no end recorded

    def test_an_unavailable_warnings_part_gives_no_events_and_says_so(self):
        towns = [{"slug": "testtown", "name": "Test Town", "lat": 47.1, "lon": -110.05}]
        doc = J.towns_polygon_file(self.ctx([], state="unavailable"), towns)
        self.assertEqual(doc["state"], "unavailable")
        self.assertEqual(doc["reason"], "the file was in an unexpected format")
        self.assertEqual(doc["towns"]["testtown"]["events"], [])

    def test_a_warning_row_takes_its_label_from_the_significance_and_the_kind_from_the_product(self):
        begin = datetime(2025, 6, 14, 0, 26, tzinfo=timezone.utc)
        end = datetime(2025, 6, 14, 1, 8, tzinfo=timezone.utc)
        tags = {"hail_in": None, "wind_mph": None, "tornado": None, "damage": None}
        for code, label, product in (("SV.W", "Warning", "severe thunderstorm warning"),
                                     ("FL.A", "Watch", "flood watch"),
                                     ("FA.Y", "Advisory", "areal flood advisory"),
                                     ("FA.A", "Watch", "areal flood watch")):
            phen, sig = code.split(".")
            text = J._warning_text(begin, end, {"k": phen, "s": sig, "o": "TFX", "tags": tags}, J.WORDS_JOINS)
            self.assertTrue(text.startswith(label + ": Jun 13, 2025 6:26 pm MDT to 7:08 pm MDT: "), text)   # 00:26 UTC is 6:26 pm MDT
            self.assertIn(": " + product + ", TFX, covered this cell or part of it; tags: none stated", text)

    def test_the_five_seasons_count_the_days_each_station_reported(self):
        rows = [(date(2023, 7, 1), 50.0), (date(2023, 7, 2), 60.0), (date(2024, 6, 30), 40.0)]
        periods = J.station_periods(rows, date(2026, 10, 16))["season"]
        self.assertEqual(sorted(periods), ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"])
        self.assertEqual(periods["2023-24"], {"n": 366, "ok": 3})          # 2024 is a leap year: 366 days
        self.assertEqual(periods["2022-23"], {"n": 365, "ok": 0})          # reported no day: zero of 365, not missing
        self.assertNotIn("2026-27", periods)

    def test_the_towns_file_agrees_with_the_cell_cover_or_says_where_it_does_not(self):
        lat, lon = 47.1, -110.05
        row, col = hail.cell_for(lat, lon)
        tile = hail.tile_name(row // hail.TILE, col // hail.TILE)
        key = hail.cell_key(row, col)
        jdir = self.tmp / "hail" / "j"
        jdir.mkdir(parents=True)
        town_event = [[0, "FL.W", "TFX", "2025-06-14T00:26:00Z", None]]
        towns = {"testtown": {"name": "Test Town", "lat": lat, "lon": lon, "cell": [row, col], "events": town_event}}
        (jdir / "towns.json").write_text(json.dumps({"f": J.TOWNS_FORMAT, "d0": "2021-10-17", "state": "loaded",
                                                     "reason": None, "towns": towns}), encoding="utf-8")

        def write_tile(warnings):
            (jdir / f"{tile}.json").write_text(json.dumps({"warnings": warnings}), encoding="utf-8")

        write_tile([[0, J.cover_hex([key])]])                       # the cover holds the town's cell: agreement
        ok = J.towns_file_check(self.tmp, {tile})
        self.assertEqual((ok["town_not_cover"], ok["cover_not_town"], ok["not_in_store"]), (0, 0, []))
        write_tile([[0, J.cover_hex([(key + 1) % 100])]])           # the cover lacks the town's cell: a failure
        missing = J.towns_file_check(self.tmp, {tile})
        self.assertEqual(missing["town_not_cover"], 1)
        write_tile([[1, J.cover_hex([key])]])                       # a cover-only event: recorded, not failed
        extra = J.towns_file_check(self.tmp, {tile})
        self.assertEqual((extra["town_not_cover"], extra["cover_not_town"]), (1, 1))
        self.assertEqual(J.towns_file_check(self.tmp, set())["not_in_store"], ["testtown"])

    def test_the_gust_file_check_names_a_season_that_is_missing_or_wrong(self):
        index = {"window": ["2021-10-17", "2026-10-16"]}
        sdir = self.tmp / "hail" / "s"
        sdir.mkdir(parents=True)
        seasons = {}
        for label in J.SEASON_LABELS:
            start, end = J.season_bounds(label, date(2026, 10, 16))
            seasons[label] = {"n": (end - start).days + 1, "ok": 0}
        (sdir / "GOOD.json").write_text(json.dumps({"periods": {"season": seasons}}), encoding="utf-8")
        self.assertEqual(J.station_periods_check(self.tmp, index)["bad"], 0)
        seasons["2023-24"]["ok"] = 999                              # more days than the season has
        (sdir / "BAD.json").write_text(json.dumps({"periods": {"season": seasons}}), encoding="utf-8")
        checked = J.station_periods_check(self.tmp, index)
        self.assertEqual((checked["files"], checked["bad"]), (2, 1))
        self.assertEqual(checked["examples"], ["BAD 2023-24"])


class IemZoneSetTests(unittest.TestCase):
    """D44: the Montana zone sets by date from IEM's snapshots, read from synthetic snapshots (no network): the reader,
    the set in force, the placement by issue time, the outlines, the changeover week and the cells the removed zones take."""

    def test_a_snapshot_reads_its_mtz_zones_sorted_with_their_rings_and_skips_the_counties(self):
        zones = J.parse_iem_ugcs(_iem_geojson(_iem_zone_codes(False)))
        self.assertEqual(len(zones), 103)
        self.assertEqual([z["zone"] for z in zones], sorted(z["zone"] for z in zones))
        self.assertTrue(all(z["rings"] and len(z["rings"][0]) >= 3 for z in zones))
        self.assertNotIn("MTC001", {z["zone"] for z in zones})
        doc = json.loads(_iem_geojson(_iem_zone_codes(True)).decode("utf-8"))
        doc["features"][0]["geometry"] = {"type": "MultiPolygon", "coordinates": [
            [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]], [[[5.0, 5.0], [6.0, 5.0], [6.0, 6.0], [5.0, 5.0]]]]}
        first = J.parse_iem_ugcs(json.dumps(doc).encode("utf-8"))[0]
        self.assertEqual(len(first["rings"]), 2)

    def test_a_snapshot_that_is_not_a_zone_set_is_refused(self):
        good = json.loads(_iem_geojson(_iem_zone_codes(True)).decode("utf-8"))
        no_outline = json.loads(json.dumps(good))
        no_outline["features"][0]["geometry"] = None
        repeated = json.loads(json.dumps(good))
        repeated["features"][1]["properties"]["ugc"] = repeated["features"][0]["properties"]["ugc"]
        few = dict(good, features=good["features"][:3])
        cases = {"not json": b"<html>", "not a collection": json.dumps({"type": "Feature"}).encode("utf-8"),
                 "no outline": json.dumps(no_outline).encode("utf-8"), "repeated code": json.dumps(repeated).encode("utf-8"),
                 "too few zones": json.dumps(few).encode("utf-8")}
        for name, data in cases.items():
            with self.assertRaises(J.JoinsError, msg=name):
                J.parse_iem_ugcs(data)

    def test_the_snapshot_date_reads_its_stamp_in_utc(self):
        self.assertEqual(J._iem_date("2022-09-13T12:00:00Z"), utc(2022, 9, 13, 12))

    def test_the_set_in_force_is_the_newest_snapshot_at_or_before_the_time(self):
        ctx = _placement_ctx()
        self.assertEqual(J._iem_in_force(ctx, utc(2021, 10, 17))["valid"], "2021-09-15T12:00:00Z")
        self.assertEqual(J._iem_in_force(ctx, utc(2022, 9, 13, 12))["valid"], "2022-09-13T12:00:00Z")
        self.assertEqual(J._iem_in_force(ctx, utc(2022, 9, 13, 17, 59))["valid"], "2022-09-13T12:00:00Z")
        self.assertEqual(J._iem_in_force(ctx, utc(2022, 9, 13, 18))["valid"], "2022-09-13T18:00:00Z")
        self.assertEqual(J._iem_in_force(ctx, utc(2030, 1, 1))["valid"], "2025-03-18T12:00:00Z")
        self.assertEqual(J._iem_in_force(ctx, utc(2000, 1, 1))["valid"], "2021-09-15T12:00:00Z")
        self.assertIsNone(J._iem_in_force(J.Context(), utc(2022, 1, 1)))

    def test_a_removed_zone_before_the_switch_is_placed_with_its_iem_outline(self):
        ctx = _placement_ctx()
        names = {z["zone"] for z in ctx.zone_map}
        for when, set_stamp in ((utc(2022, 3, 1, 12), "2021-09-15T12:00:00Z"), (utc(2022, 6, 15, 12), "2022-06-01T12:00:00Z"),
                                (utc(2022, 9, 7, 10), "2022-06-01T12:00:00Z")):
            p = J._place(ctx, names, "MTZ008", when)
            self.assertEqual((p["zone"], p["set"], p["outline"], p["reason"]), ("MTZ008", set_stamp, "iem", None), when)
        self.assertEqual(J._place(ctx, names, "MTZ008", utc(2022, 3, 1, 12))["how"], "iem")
        self.assertEqual(J._place(ctx, names, "MTZ008", utc(2022, 9, 7, 10))["how"], "changeover")

    def test_the_changeover_week_is_placed_by_the_set_that_holds_the_code(self):
        ctx = _placement_ctx()
        names = {z["zone"] for z in ctx.zone_map}
        p = J._place(ctx, names, "MTZ060", utc(2022, 9, 12, 20))
        self.assertEqual((p["zone"], p["how"], p["outline"]), ("MTZ060", "changeover", "iem"))
        p = J._place(ctx, names, "MTZ001", utc(2022, 9, 8, 12))
        self.assertEqual((p["zone"], p["how"], p["outline"]), ("MTZ001", "changeover", "nws"))

    def test_a_removed_zone_after_the_switch_is_unplaced_as_not_in_the_iem_set(self):
        ctx = _placement_ctx()
        names = {z["zone"] for z in ctx.zone_map}
        p = J._place(ctx, names, "MTZ008", utc(2022, 9, 14, 12))
        self.assertEqual((p["zone"], p["set"], p["reason"]), (None, "2022-09-13T18:00:00Z", "not_in_iem_set"))

    def test_mtz060_uses_the_iem_outline_before_the_switch_and_the_nws_outline_after_it(self):
        ctx = _placement_ctx()
        names = {z["zone"] for z in ctx.zone_map}
        p = J._place(ctx, names, "MTZ060", utc(2022, 6, 1, 12))
        self.assertEqual((p["zone"], p["outline"], p["how"]), ("MTZ060", "iem", "iem"))
        p = J._place(ctx, names, "MTZ060", utc(2023, 1, 1, 12))
        self.assertEqual((p["zone"], p["outline"], p["how"]), ("MTZ060", "nws", "iem"))

    def test_a_zone_of_the_current_set_before_the_switch_keeps_the_nws_outline(self):
        ctx = _placement_ctx()
        p = J._place(ctx, {z["zone"] for z in ctx.zone_map}, "MTZ001", utc(2021, 12, 1, 12))
        self.assertEqual((p["outline"], p["how"]), ("nws", "iem"))

    def test_a_set_that_did_not_load_or_is_missing_leaves_its_products_unplaced_with_the_reason(self):
        ctx = _placement_ctx()
        names = {z["zone"] for z in ctx.zone_map}
        ctx.iem_sets[1]["zones"], ctx.iem_sets[1]["codes"] = None, set()
        p = J._place(ctx, names, "MTZ008", utc(2022, 6, 15, 12))
        self.assertEqual((p["zone"], p["reason"]), (None, "set_unread"))
        ctx.iem_sets = []
        p = J._place(ctx, names, "MTZ008", utc(2022, 3, 1, 12))
        self.assertEqual((p["zone"], p["reason"]), (None, "set_unread"))

    def test_a_linked_edition_that_did_not_load_leaves_its_products_unplaced(self):
        ctx = _placement_ctx()
        ctx.zone_editions[6]["zones"] = None                      # z_18mr25.zip, linked by the NWS page, did not load
        J._edition_maps(ctx)
        p = J._place(ctx, {z["zone"] for z in ctx.zone_map}, "MTZ313", utc(2025, 6, 1, 12))
        self.assertEqual((p["zone"], p["set"], p["reason"]), (None, "z_18mr25.zip", "edition_unread"))

    def test_zone_events_place_the_removed_zone_products_and_the_table_counts_them(self):
        ctx = _placement_ctx()
        ctx.zone_rows = [zone_row("MTZ008", "HW", "NEW", utc(2022, 3, 1, 12), utc(2022, 3, 1, 18), eventid="50"),
                         zone_row("MTZ008", "HW", "NEW", utc(2022, 9, 14, 12), utc(2022, 9, 14, 18), eventid="51"),
                         zone_row("MTZ001", "HW", "NEW", utc(2022, 9, 8, 12), utc(2022, 9, 8, 18), eventid="52")]
        out = J._zone_events(ctx, *WINDOW)
        self.assertEqual([e["b"] for e in out["MTZ008"]], ["2022-03-01T12:00Z"])
        self.assertEqual([e["b"] for e in out["MTZ001"]], ["2022-09-08T12:00Z"])
        self.assertEqual(J._placement_table(ctx), {"groups": 3, "current": 0, "mapped": 0, "iem_set": 1,
                                                   "changeover_week": 1, "unplaced": 1, "expected_unplaced": 0,
                                                   "simplified_outline": 1})
        self.assertEqual(ctx.zone_unplaced_rows, [["HW.W", "MTZ008", "2022-09-14", "2022-09-13T18:00:00Z",
                                                   "not_in_iem_set"]])

    def test_cells_inside_a_removed_zone_take_it_before_the_switch_and_no_other_cell_does(self):
        ctx = _placement_ctx()
        removed = next(z for z in ctx.iem_outline if z["zone"] == "MTZ008")
        pts = removed["rings"][0]
        lon = sum(p[0] for p in pts) / len(pts)
        lat = sum(p[1] for p in pts) / len(pts)
        claimed = J.assign_zones([(1, 1, lat, lon)], ctx.iem_outline)
        self.assertEqual(claimed, {(1, 1): "MTZ008"})
        self.assertEqual(J.assign_zones([(2, 2, 40.0, -100.0)], ctx.iem_outline), {})     # outside every outline


class ZoneBeforeSwitchReadTests(unittest.TestCase):
    """D44 (the reader): a cell in a removed zone's outline shows that zone's products issued before the switch, with the
    note that the zone is placed with a simplified outline; the zone's later products are not read for it."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="joins-test-before-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "hail" / "z").mkdir(parents=True)
        (self.root / "hail" / "z" / "MTZ313.json").write_text(json.dumps(
            {"f": J.ZONE_FORMAT, "zone": "MTZ313", "name": "Judith Basin County", "records": [], "events": []}))
        (self.root / "hail" / "z" / "MTZ008.json").write_text(json.dumps(
            {"f": J.ZONE_FORMAT, "zone": "MTZ008", "name": "Beaverhead", "records": [], "events": [
                {"k": "HW", "s": "W", "b": "2022-03-01T12:00Z", "e": "2022-03-01T18:00Z", "o": "TFX"},
                {"k": "HW", "s": "W", "b": "2022-09-14T12:00Z", "e": "2022-09-14T18:00Z", "o": "TFX"}]}))

    def test_the_zone_section_adds_the_removed_zone_products_before_the_switch_with_their_note(self):
        index = _index()
        index["joins"]["zone_names"] = {"MTZ313": "Judith Basin County", "MTZ008": "Beaverhead"}
        doc = _cell_doc(zones={"MTZ313": [GATE_KEY]}, zones_before={"MTZ008": [GATE_KEY]})
        out = J.describe_joins(index, doc, *GATE, store_dir=self.root)
        zones = next(s for s in out["sections"] if s["id"] == "zones")
        self.assertEqual(len(zones["rows"]), 1, zones["rows"])
        text = zones["rows"][0]["text"]
        self.assertIn("Mar 1, 2022", text)
        self.assertNotIn("Sep 14, 2022", text)
        self.assertIn("zone Beaverhead (MTZ008), placed with a simplified zone outline", text)
        self.assertIn("1 product for zone Beaverhead (MTZ008) was issued before 13 September 2022", " ".join(zones["lines"]))
        check_words(self, text)

    def test_a_pre_switch_product_of_mtz060_carries_the_note_on_its_own_zone(self):
        (self.root / "hail" / "z" / "MTZ060.json").write_text(json.dumps(
            {"f": J.ZONE_FORMAT, "zone": "MTZ060", "name": "Southwest Phillips", "records": [], "events": [
                {"k": "HW", "s": "W", "b": "2022-03-01T12:00Z", "e": "2022-03-01T18:00Z", "o": "TFX"},
                {"k": "HW", "s": "W", "b": "2023-01-10T12:00Z", "e": "2023-01-10T18:00Z", "o": "TFX"}]}))
        index = _index()
        index["joins"]["zone_names"] = {"MTZ060": "Southwest Phillips"}
        out = J.describe_joins(index, _cell_doc(zones={"MTZ060": [GATE_KEY]}), *GATE, store_dir=self.root)
        zones = next(s for s in out["sections"] if s["id"] == "zones")
        texts = [r["text"] for r in zones["rows"]]
        self.assertEqual(len(texts), 2, texts)
        simplified = [t for t in texts if "placed with a simplified zone outline" in t]
        self.assertEqual(len(simplified), 1, texts)
        self.assertIn("Mar 1, 2022", simplified[0])
        self.assertNotIn("Jan 10, 2023", simplified[0])
        self.assertTrue(zones["lead"].startswith("2 products for zone Southwest Phillips (MTZ060)"), zones["lead"])
        check_words(self, simplified[0])

    def test_a_cell_outside_the_removed_zone_reads_only_its_current_zone(self):
        index = _index()
        doc = _cell_doc(zones={"MTZ313": [GATE_KEY]})
        out = J.describe_joins(index, doc, *GATE, store_dir=self.root)
        zones = next(s for s in out["sections"] if s["id"] == "zones")
        self.assertEqual(zones["rows"], [])


class StationPickFromSpotTests(unittest.TestCase):
    """D36: the gust stations of a cell or a town are picked from its own point. A tile's candidates hold every station that
    could be one of the two nearest to any point of the tile."""

    def test_the_candidates_hold_the_two_nearest_stations_to_any_point_of_the_tile(self):
        bounds = (47.0, 47.1, -110.2, -110.0)
        rng = random.Random(7)
        stations = [{"id": f"S{i:02d}", "name": f"Station {i}", "lat": 46.0 + rng.random() * 2.0,
                     "lon": -111.5 + rng.random() * 3.0} for i in range(60)]
        cands = {c["id"] for c in J._station_candidates(stations, bounds)}
        self.assertLess(len(cands), len(stations))
        for _ in range(200):
            lat = bounds[0] + rng.random() * (bounds[1] - bounds[0])
            lon = bounds[2] + rng.random() * (bounds[3] - bounds[2])
            near = sorted((J.haversine_km(lat, lon, s["lat"], s["lon"]) / J.MILE_KM, s["id"]) for s in stations)
            picks = [sid for miles, sid in near[:2] if miles <= J.STATION_MILES]
            self.assertTrue(set(picks) <= cands, (lat, lon, picks))

    def test_a_town_point_picks_its_own_two_nearest_stations_and_gives_the_miles_from_it(self):
        root = Path(tempfile.mkdtemp(prefix="joins-test-spot-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "hail" / "s").mkdir(parents=True)
        day = hail.day_index(date(2025, 6, 15))
        stations = [{"id": "NEARTOWN", "name": "Near the town", "lat": 47.20, "lon": -110.05},
                    {"id": "CENTRE", "name": "At the centre", "lat": 47.02, "lon": -110.13},
                    {"id": "FAR", "name": "Far", "lat": 47.60, "lon": -110.60}]
        for st in stations:
            (root / "hail" / "s" / f"{st['id']}.json").write_text(json.dumps(
                {"f": J.STATION_FORMAT, "id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                 "days": [[day, 58, 50]], "dropped": 0}))
        doc = _cell_doc(stations=[{"id": "CENTRE", "name": "At the centre", "lat": 47.02, "lon": -110.13, "miles": 0.5}],
                        station_candidates=stations)
        town = (47.19, -110.04)
        out = J.describe_joins(_index(), doc, *GATE, store_dir=root, spot=town)
        sec = next(s for s in out["sections"] if s["id"] == "stations")
        names = sorted(row["text"].split(" at ")[1].split(",")[0] for row in sec["rows"])
        self.assertEqual(names, ["At the centre", "Near the town"])       # the two nearest the town point; Far is third
        miles = J.haversine_km(town[0], town[1], 47.20, -110.05) / J.MILE_KM
        self.assertTrue(any(f"about {miles:.1f} miles away" in row["text"] for row in sec["rows"]))
        out = J.describe_joins(_index(), doc, *GATE, store_dir=root)
        sec = next(s for s in out["sections"] if s["id"] == "stations")
        self.assertEqual(sorted(row["text"].split(" at ")[1].split(",")[0] for row in sec["rows"]),
                         ["At the centre", "Near the town"])

    def test_a_tile_file_from_before_d36_still_picks_from_its_two_station_list(self):
        self.assertEqual([s["id"] for s in J.station_picks({"stations": [
            {"id": "A", "name": "A", "lat": 47.02, "lon": -110.13}]}, 47.0, -110.1)], ["A"])


class TownPointWarningTests(unittest.TestCase):
    """D71 (F4): a town page's warning rows are the town point's rows from hail/j/towns.json (the D11 point test, D38),
    worded "covered this spot", and the count note agrees with them. The sheet keeps the tile's cell covers ("covered this
    cell or part of it"). A town file that cannot answer for the point gives the D20 sentence, never an empty list."""

    TOWN = (47.025, -110.135)         # the centre of the gate cell (797, 1986): inside both warnings' cell cover
    OTHER = (47.030, -110.140)        # a second town point in the same cell, inside neither warning
    FIRST = {"k": "SV", "s": "W", "o": "TFX", "b": utc(2025, 6, 15, 0, 26), "e": utc(2025, 6, 15, 1, 8),
             "tags": {"hail_in": 1.0, "wind_mph": 60.0, "tornado": None, "damage": None}}
    SECOND = {"k": "FL", "s": "A", "o": "TFX", "b": utc(2025, 6, 15, 5, 39), "e": utc(2025, 6, 15, 5, 59),
              "tags": {"hail_in": None, "wind_mph": None, "tornado": None, "damage": None}}

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="joins-test-town-point-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "hail" / "j").mkdir(parents=True)
        self.index = _index()
        # the events table holds the warnings with their times as ISO text, as the build writes them
        self.items = [dict(self.FIRST, b=J.iso_utc(self.FIRST["b"]), e=J.iso_utc(self.FIRST["e"])),
                      dict(self.SECOND, b=J.iso_utc(self.SECOND["b"]), e=J.iso_utc(self.SECOND["e"]))]
        cover = J.cover_hex([GATE_KEY])
        self.doc, self.events = store_form({"warnings": [(self.items[0], cover), (self.items[1], cover)]})
        self.path = self.root / "hail" / "j" / J.TOWNS_NAME

    def town(self, point, refs):
        """One town entry as the build writes it: the warnings its point is inside, by their events-table index."""
        events = []
        for ref in refs:
            item = self.items[ref] if ref < len(self.items) else self.items[0]    # a ref the table does not hold
            events.append([ref, f"{item['k']}.{item['s']}", item["o"], item["b"], item["e"]])
        return {"name": "Test town", "lat": point[0], "lon": point[1], "cell": list(GATE), "events": events}

    def write_towns(self, towns, **over):
        doc = {"f": J.TOWNS_FORMAT, "d0": "2020-01-01", "state": "loaded", "reason": None, "towns": towns}
        doc.update(over)
        self.path.write_text(json.dumps(doc), encoding="utf-8")

    def warnings(self, spot=None, folder=None):
        out = J.describe_joins(self.index, _cell_doc(warnings=self.doc["warnings"]), *GATE,
                               store_dir=self.root if folder is None else folder, events=self.events, spot=spot)
        return next(s for s in out["sections"] if s["id"] == "warnings")

    def test_a_town_point_lists_its_own_rows_and_the_sheet_keeps_the_cell_covers(self):
        self.write_towns({"edge": self.town(self.TOWN, [0])})
        town = self.warnings(spot=self.TOWN)
        self.assertEqual(len(town["rows"]), 1)
        self.assertIn("covered this spot", town["rows"][0]["text"])
        self.assertNotIn("cell or part of it", town["rows"][0]["text"])
        self.assertTrue(town["lead"].startswith("1 warning covered this spot"), town["lead"])
        self.assertEqual(town["what"], J.WORDS_JOINS["warnings_what_point"])
        self.assertEqual(town["heading"], "Warnings that covered this spot")
        sheet = self.warnings()
        self.assertEqual(len(sheet["rows"]), 2)
        self.assertTrue(all("covered this cell or part of it" in row["text"] for row in sheet["rows"]))
        # F4: the heading and the count note are checked in their words, not only by the count
        self.assertEqual(sheet["heading"], "Warnings that covered this cell or part of it")
        self.assertTrue(sheet["lead"].startswith("2 warnings covered this cell or part of it between "), sheet["lead"])
        self.assertNotIn("this spot", sheet["lead"])
        self.assertEqual(sheet["what"], J.WORDS_JOINS["warnings_what"])

    def test_the_count_note_and_the_rows_agree_for_each_town_point_in_the_cell(self):
        self.write_towns({"edge": self.town(self.TOWN, [0, 1]), "inner": self.town(self.OTHER, [])})
        both = self.warnings(spot=self.TOWN)
        self.assertEqual(len(both["rows"]), 2)
        self.assertTrue(both["lead"].startswith("2 warnings covered this spot"), both["lead"])
        neither = self.warnings(spot=self.OTHER)
        self.assertEqual(neither["rows"], [])
        self.assertTrue(neither["lead"].startswith("No warning in the archive covered this spot"), neither["lead"])
        self.assertIsNone(neither["unavailable"])

    def test_the_town_rows_are_newest_first_and_each_starts_with_its_significance(self):
        self.write_towns({"edge": self.town(self.TOWN, [0, 1])})
        rows = self.warnings(spot=self.TOWN)["rows"]
        self.assertTrue(rows[0]["text"].startswith("Watch: "), rows[0]["text"])        # the flood watch, 05:39 UTC
        self.assertTrue(rows[1]["text"].startswith("Warning: "), rows[1]["text"])
        self.assertEqual([row["utc"] for row in rows], sorted((row["utc"] for row in rows), reverse=True))

    def test_a_town_file_that_cannot_answer_gives_the_unavailable_sentence_and_no_rows(self):
        cases = {
            "the file is missing": None,
            "the warnings part did not load": ({"edge": self.town(self.TOWN, [0])}, {"state": "unavailable"}),
            "the file is in another format": ({"edge": self.town(self.TOWN, [0])}, {"f": "other"}),
            "no town is at this point": ({"inner": self.town(self.OTHER, [])}, {}),
            "a row names an event the table does not hold": ({"edge": self.town(self.TOWN, [9])}, {}),
        }
        for label, case in cases.items():
            with self.subTest(label):
                if case is None:
                    self.path.unlink(missing_ok=True)
                else:
                    self.write_towns(case[0], **case[1])
                sec = self.warnings(spot=self.TOWN)
                self.assertEqual(sec["rows"], [])
                self.assertIsNone(sec["lead"])
                self.assertEqual(sec["unavailable"], J._unavailable_text("warnings", None))
                self.assertTrue(sec["unavailable"].endswith("This is not an all-clear."), sec["unavailable"])

    def test_the_sheet_still_lists_its_cell_covers_without_a_town_file(self):
        self.assertFalse(self.path.exists())
        sec = self.warnings()
        self.assertEqual(len(sec["rows"]), 2)
        self.assertIsNone(sec["unavailable"])

    def test_a_town_point_without_a_store_folder_is_unavailable_not_empty(self):
        out = J.describe_joins(self.index, _cell_doc(warnings=self.doc["warnings"]), *GATE, store_dir=None,
                               events=self.events, spot=self.TOWN)
        sec = next(s for s in out["sections"] if s["id"] == "warnings")
        self.assertEqual(sec["rows"], [])
        self.assertEqual(sec["unavailable"], J._unavailable_text("warnings", None))

    def section(self, warnings, spot=None):
        out = J.describe_joins(self.index, _cell_doc(warnings=warnings), *GATE, store_dir=self.root, events=self.events,
                               spot=spot)
        return next(s for s in out["sections"] if s["id"] == "warnings")

    def test_the_sheet_heading_and_count_notes_name_the_cell_cover_for_every_count(self):
        """F1, F4: the sheet's heading and count notes say "covered this cell or part of it" for one, many, none and the
        unknown count, and the no-outline line names the cell too. None of them says "this spot"."""
        cell = "covered this cell or part of it"
        sheet = self.section(self.doc["warnings"])
        self.assertEqual(sheet["heading"], "Warnings that covered this cell or part of it")
        self.assertTrue(sheet["lead"].startswith("2 warnings " + cell + " between "), sheet["lead"])
        one = self.section(self.doc["warnings"][:1])
        self.assertTrue(one["lead"].startswith("1 warning " + cell + " between "), one["lead"])
        none = self.section([])
        self.assertTrue(none["lead"].startswith("No warning in the archive " + cell + " between "), none["lead"])
        self.index["joins"]["warnings_no_outline"] = 1
        unknown = self.section([])
        self.assertEqual(unknown["lead"], J.WORDS_JOINS["warnings_lead_unknown"])
        self.assertIn("1 warning in these five years has no outline on file, so it cannot be matched to this cell or "
                      "part of it." + AC, unknown["lines"])
        for text in [sheet["heading"], sheet["lead"], one["lead"], none["lead"], unknown["lead"], *unknown["lines"]]:
            self.assertNotIn("this spot", text)

    def test_the_town_point_heading_and_count_notes_say_this_spot_for_every_count(self):
        """F4: a town page's heading and count notes say "covered this spot" (the town point's rows) for one, none
        and the unknown count, and none of its lines says "cell or part of it"."""
        self.write_towns({"edge": self.town(self.TOWN, [0]), "inner": self.town(self.OTHER, [])})
        town = self.section(self.doc["warnings"], spot=self.TOWN)
        self.assertEqual(town["heading"], "Warnings that covered this spot")
        self.assertTrue(town["lead"].startswith("1 warning covered this spot between "), town["lead"])
        neither = self.section(self.doc["warnings"], spot=self.OTHER)
        self.assertTrue(neither["lead"].startswith("No warning in the archive covered this spot between "),
                        neither["lead"])
        self.index["joins"]["warnings_no_outline"] = 1
        unknown = self.section([], spot=self.OTHER)
        self.assertEqual(unknown["lead"], J.WORDS_JOINS["warnings_lead_unknown_point"])
        self.assertIn("1 warning in these five years has no outline on file, so it cannot be matched to this spot."
                      + AC, unknown["lines"])
        for text in [town["heading"], town["lead"], neither["lead"], unknown["lead"], *unknown["lines"]]:
            self.assertNotIn("cell or part of it", text)

    def test_the_no_outline_clause_names_the_cell_on_the_sheet_and_the_spot_on_a_town_page_for_one_and_for_many(self):
        """D80(d): the no-outline clause has the cell words on the sheet and its _point twin with the spot words on a town
        page, for one warning and for several. The sentence is the same in both except for the place it names."""
        self.write_towns({"edge": self.town(self.TOWN, [0]), "inner": self.town(self.OTHER, [])})
        self.index["joins"]["warnings_no_outline"] = 2
        sheet = self.section([])
        town = self.section([], spot=self.TOWN)
        self.assertIn("2 warnings in these five years have no outline on file, so they cannot be matched to this cell or "
                      "part of it." + AC, sheet["lines"])
        self.assertIn("2 warnings in these five years have no outline on file, so they cannot be matched to this spot."
                      + AC, town["lines"])
        self.index["joins"]["warnings_no_outline"] = 1
        one = self.section([], spot=self.TOWN)
        self.assertIn("1 warning in these five years has no outline on file, so it cannot be matched to this spot." + AC,
                      one["lines"])
        for text in sheet["lines"]:
            self.assertNotIn("this spot", text)
        for text in [*town["lines"], *one["lines"]]:
            self.assertNotIn("cell or part of it", text)
        self.assertEqual(J.WORDS_JOINS["warnings_no_outline_many_point"].format(n=2),
                         "2 warnings in these five years have no outline on file, so they cannot be matched to this spot."
                         + AC)

    def test_each_warning_word_the_sheet_reads_names_the_cell_and_each_point_twin_names_the_spot(self):
        """F1, F4: the keys the browser reads for the sheet (the heading and the count notes, map.js) name the cell
        cover, and each "_point" twin names the spot. A twin takes the same fields, so one .format call fills either."""
        from string import Formatter

        def fields(text):
            return {field for _lit, field, _spec, _conv in Formatter().parse(text) if field}

        for key in ("warnings_heading", "warnings_lead_one", "warnings_lead_many", "warnings_lead_none",
                    "warnings_lead_unknown", "warnings_no_outline_one", "warnings_no_outline_many"):
            cell, point = J.WORDS_JOINS[key], J.WORDS_JOINS[key + "_point"]
            self.assertIn("this cell or part of it", cell, key)
            self.assertNotIn("this spot", cell, key)
            self.assertIn("this spot", point, key)
            self.assertNotIn("cell or part of it", point, key)
            self.assertEqual(fields(point), fields(cell), key)
            check_words(self, cell)
            check_words(self, point)

    def test_the_point_words_say_covered_this_spot_with_the_fields_of_the_cell_row(self):
        from string import Formatter

        def fields(text):
            return {field for _lit, field, _spec, _conv in Formatter().parse(text) if field}

        self.assertEqual(fields(J.WORDS_JOINS["warnings_row_point"]), fields(J.WORDS_JOINS["warnings_row_b5"]))
        self.assertIn("covered this spot", J.WORDS_JOINS["warnings_row_point"])
        self.assertNotIn("cell or part of it", J.WORDS_JOINS["warnings_row_point"])
        self.assertIn("covered this spot", J.WORDS_JOINS["warnings_what_point"])
        self.assertNotIn("covered this cell or part of it", J.WORDS_JOINS["warnings_what_point"])
        for text in (J.WORDS_JOINS["warnings_row_point"], J.WORDS_JOINS["warnings_what_point"]):
            check_words(self, text)

    def test_the_fixture_town_page_reads_its_town_file_and_shows_no_unavailable_line(self):
        index = hail.load_index(FIXTURE)
        events = J._read_events(FIXTURE)
        tile = json.loads((FIXTURE / "hail" / "j" / "r0092_c0214.json").read_text(encoding="utf-8"))
        town = json.loads((FIXTURE / "hail" / "j" / J.TOWNS_NAME).read_text(encoding="utf-8"))["towns"]["billings"]
        row, col = town["cell"]
        key = hail.cell_key(row, col)
        covers = sum(1 for _ref, cover in tile["warnings"] if J.cover_has(cover, key))
        point = J.describe_joins(index, tile, row, col, None, sample=True, store_dir=FIXTURE, events=events,
                                 spot=(town["lat"], town["lon"]))
        point_sec = next(s for s in point["sections"] if s["id"] == "warnings")
        self.assertEqual(point_sec["rows"], [])        # the town file lists no warning at the point
        self.assertTrue(point_sec["lead"].startswith("No warning in the archive covered this spot"), point_sec["lead"])
        sheet = J.describe_joins(index, tile, row, col, None, sample=True, store_dir=FIXTURE, events=events)
        sheet_sec = next(s for s in sheet["sections"] if s["id"] == "warnings")
        self.assertEqual(len(sheet_sec["rows"]), covers)
        self.assertTrue(all("covered this cell or part of it" in r["text"] for r in sheet_sec["rows"]))


class FloodRecordRowTests(unittest.TestCase):
    """D48: NCEI flood and flash flood records within five miles are their own row (the words the summary reads). The
    Red Lodge record of 10 June 2022 (event 1039252) is 0.3 miles from its cell's centre."""

    RED_LODGE = [891, 700, 45.1677, -109.2503, "flood", "", "", "", "Emergency manager", "RED LODGE", "", None, None,
                 "Heavy Rain / Snow Melt"]
    FLASH = [1271, 30, 45.1, -109.26, "flash flood", "", "", "", "Emergency manager", "RED LODGE ARPT", "", None, None,
             "Heavy Rain"]

    def test_the_red_lodge_flood_record_is_its_own_count_at_three_tenths_of_a_mile(self):
        doc, events = store_form({"records": [self.RED_LODGE, self.FLASH]})
        out = J.describe_joins(_index(), doc, 983, 2074, events=events)
        sec = next(s for s in out["sections"] if s["id"] == "records")
        texts = [row["text"] for row in sec["rows"]]
        red = [t for t in texts if "flood" in t and "0.3 mi" in t]
        self.assertEqual(len(red), 1, texts)
        self.assertIn("0.3 mi", red[0])
        self.assertIn(J.WORDS_JOINS["flood_records_line_many"].format(n=2), sec["lines"])
        self.assertEqual(J.WORDS_JOINS["flood_records_label"], "Flood and flash flood records within 5 miles")
        self.assertEqual(J.WORDS_JOINS["flood_records_kind"], "Record (NCEI)")
        self.assertEqual(J.FLOOD_RECORD_CODES, ("flood", "flash flood"))
        for key in ("flood_records_line_one", "flood_records_line_many", "flood_records_none", "flood_records_label"):
            check_words(self, J.WORDS_JOINS[key].format(n=2))

    def test_a_record_outside_five_miles_is_not_in_the_flood_count(self):
        far = [891, 700, 45.5, -109.0, "flood", "", "", "", "Emergency manager", "FAR", "", None, None, ""]
        doc, events = store_form({"records": [far]})
        out = J.describe_joins(_index(), doc, 983, 2074, events=events)
        sec = next(s for s in out["sections"] if s["id"] == "records")
        self.assertEqual(sec["rows"], [])
        self.assertFalse(any("flood or flash flood records" in line for line in sec["lines"]))


def _zone_zip_bytes(codes) -> bytes:
    """A zone edition as the NWS zip holds it (D16): a shapefile of the codes, one square each, with STATE, ZONE, NAME and
    STATE_ZONE, in a zip the reader opens (pyshp, as ShapefileTests uses)."""
    import shapefile
    tmp = Path(tempfile.mkdtemp(prefix="joins-test-zip-"))
    try:
        base = tmp / "z_16ap26"
        writer = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
        writer.field("STATE", "C", size=2)
        writer.field("ZONE", "C", size=3)
        writer.field("NAME", "C", size=40)
        writer.field("STATE_ZONE", "C", size=6)              # MTZ002 is six characters (pyshp would truncate it to MTZ00)
        for i, code in enumerate(codes):
            x0 = -114.0 + (i % 20) * 0.5
            y0 = 44.5 + (i // 20) * 0.4
            writer.poly([[[x0, y0], [x0 + 0.4, y0], [x0 + 0.4, y0 + 0.3], [x0, y0 + 0.3], [x0, y0]]])
            writer.record("MT", code[3:], f"Test zone {code}", code)
        writer.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for ext in (".shp", ".dbf", ".shx"):
                zf.write(str(base) + ext, base.name + ext)
        return buf.getvalue()
    finally:
        shutil.rmtree(tmp)


class PlacementTableBuildTests(unittest.TestCase):
    """D44 on a built store: the index's table, the snapshots, and the z/ files of the removed zones."""

    def test_the_index_names_the_table_the_snapshots_and_the_removed_zones_files(self):
        tmp = Path(tempfile.mkdtemp(prefix="joins-test-d44-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        store = tmp / "store"
        hail.fixture_store(store)
        def responder(url, params):
            if url == J.NWS_BASE_URL + "z_16ap26.zip":
                return _zone_zip_bytes(_iem_zone_codes(True))
            return canned(url, params)
        fetcher = FakeFetcher(tmp / "cache", store / "ledger" / "joins.jsonl", responder)
        block = J.build(store, tmp / "cache", procs=1, today=date(2026, 10, 18), fetcher=fetcher, log=lambda text: None)
        self.assertEqual(block["parts"]["zones"], "loaded")
        self.assertEqual([s["zones"] for s in block["iem_sets"]], [103, 103, 103, 103, 83, 83, 83])
        self.assertTrue(all(s["state"] == "loaded" and s["sha256"] for s in block["iem_sets"]))
        self.assertEqual(block["zone_placement_table"]["unplaced"], 0)
        self.assertEqual(block["zones_before"]["codes"], sorted(J.IEM_OUTLINE_ZONES))
        for code in J.IEM_REMOVED_ZONES:
            self.assertTrue((store / "hail" / "z" / f"{code}.json").is_file(), code)
        result = J.verify(store, tmp / "cache")
        d44 = [c for c in result["checks"] if c["name"].startswith((
            "zone placement", "IEM zone sets", "zones before the switch"))]
        self.assertGreaterEqual(len(d44), 5, [c["name"] for c in result["checks"]])
        self.assertEqual([c["name"] for c in d44 if not c["ok"]], [], d44)     # the gate and period checks need real geometry


class EdgeWindowTests(unittest.TestCase):
    """D55: the store window (the 1,826 SPC days ending on as_of) and the research window (calendar days) count an event
    as they begin it; an event at one window's edge only is named with its first row, and every difference between the two
    counts must be the named edges, or verify says so."""

    STORE = ["2021-10-17T12:00Z", "2026-10-17T12:00Z"]

    def block(self, store, research, edges):
        return {"vtec_store_window": self.STORE, "vtec_counts": store, "vtec_counts_research": research,
                "vtec_window_edges": edges}

    def test_the_research_window_and_the_store_window_differ_by_the_named_edge_and_nothing_else(self):
        edge = {"product": "HW.A", "level": "zone", "wfo": "TFX", "eventid": "30", "vtec_year": "2026",
                "begin": "2026-10-17T15:00Z", "in_store_window": False, "in_research_window": True,
                "first_status": "UPG", "first_issue": "2026-10-17T15:00Z", "product_time": "2026-10-15T04:45Z",
                "expire": "2026-10-16T18:23Z", "codes": ["MTZ301"], "rows": 5}
        block = self.block({"HW.A": {"zone": 276, "county": 0, "window": 276}},
                           {"HW.A": {"zone": 277, "county": 0, "window": 277}}, [edge])
        got = J._window_edge_check(block)
        self.assertEqual(got["unexplained"], [])
        self.assertEqual([(r["product"], r["difference"], r["named"]) for r in got["differences"]], [("HW.A", -1, -1)])
        self.assertEqual(got["edges"], 1)
        self.assertIn("counted in the research window only", got["sentences"][0])
        self.assertIn("begins 17 October 2026 at 15:00 UTC", got["sentences"][0])
        self.assertIn("its first archived row is UPG issued 17 October 2026 at 15:00 UTC", got["sentences"][0])
        self.assertIn("No store rule drops it", got["sentences"][0])

    def test_a_difference_with_no_named_edge_is_unexplained(self):
        block = self.block({"HW.W": {"zone": 338, "county": 0, "window": 338}},
                           {"HW.W": {"zone": 339, "county": 0, "window": 339}}, [])
        got = J._window_edge_check(block)
        self.assertEqual([(r["product"], r["level"], r["difference"], r["named"]) for r in got["unexplained"]],
                         [("HW.W", "zone", -1, 0)])

    def test_an_edge_on_the_store_side_is_counted_plus_one_and_the_polygon_level_is_checked(self):
        edge = {"product": "FW.W", "level": "zone", "wfo": "TFX", "eventid": "19", "vtec_year": "2021",
                "begin": "2021-10-17T18:00Z", "in_store_window": True, "in_research_window": False,
                "first_status": "EXP", "first_issue": "2021-10-17T18:00Z", "product_time": "2021-10-16T20:37Z",
                "expire": "2021-10-18T00:00Z", "codes": ["MTZ112"], "rows": 4}
        poly = {"product": "SQ.W", "level": "polygon", "wfo": "MSO", "eventid": "5", "vtec_year": "2021",
                "begin": "2021-10-18T01:00Z", "in_store_window": True, "in_research_window": False,
                "first_status": "NEW", "first_issue": "2021-10-18T01:00Z", "product_time": None, "expire": None,
                "codes": [], "rows": 1}
        block = self.block({"FW.W": {"zone": 170, "county": 0, "window": 170},
                            "SQ.W": {"polygon": 1, "window": 1}},
                           {"FW.W": {"zone": 169, "county": 0, "window": 169}}, [edge, poly])
        got = J._window_edge_check(block)
        self.assertEqual(got["unexplained"], [])
        self.assertEqual(sorted((r["product"], r["level"], r["difference"]) for r in got["differences"]),
                         [("FW.W", "zone", 1), ("SQ.W", "polygon", 1)])
        self.assertIn("counted in the store window only", got["sentences"][0])

    def test_the_edge_records_carry_the_first_row_and_the_polygon_fields(self):
        t = lambda h: datetime(2026, 10, 17, h, tzinfo=timezone.utc)      # noqa: E731
        first = {"issue": t(15), "status": "UPG", "prod": datetime(2026, 10, 15, 4, 45, tzinfo=timezone.utc),
                 "expire": datetime(2026, 10, 16, 18, 23, tzinfo=timezone.utc)}
        item = {"issues": [t(15)], "new": [], "level": {"zone"}, "first": first, "codes": {"MTZ302", "MTZ301"}}
        edge = J._vtec_edge("HW.A", ("HW", "A", "TFX", "30", "2026"), item, t(15), False, True)
        self.assertEqual((edge["product"], edge["level"], edge["wfo"], edge["eventid"], edge["vtec_year"]),
                         ("HW.A", "zone", "TFX", "30", "2026"))
        self.assertEqual((edge["begin"], edge["first_status"], edge["product_time"], edge["expire"]),
                         ("2026-10-17T15:00Z", "UPG", "2026-10-15T04:45Z", "2026-10-16T18:23Z"))
        self.assertEqual(edge["codes"], ["MTZ301", "MTZ302"])
        poly = {"k": "FL", "s": "W", "o": "MSO", "eventid": "9", "vtec_year": "2026", "b": t(12), "e": None}
        pe = J._polygon_edge(poly, True, False)
        self.assertEqual((pe["product"], pe["level"], pe["first_status"], pe["expire"]), ("FL.W", "polygon", "NEW", None))
        self.assertEqual(pe["begin"], "2026-10-17T12:00Z")

    def test_the_utc_words_and_the_research_table(self):
        self.assertEqual(J._utc_words("2026-10-17T15:00Z"), "17 October 2026 at 15:00 UTC")
        self.assertEqual(J._utc_words("2021-10-19T00:00Z"), "19 October 2021 at 00:00 UTC")
        # D55: the research's own counts, with HW.W from the research record and FW.W from an independent recount of the
        # cached FW.W rows (169 in the research window; 170 in the store window, which verify checks)
        self.assertEqual((J.RESEARCH_B5["HW.A"], J.RESEARCH_B5["HW.W"], J.RESEARCH_B5["FW.W"]), (277, 339, 169))
        self.assertEqual((J.RESEARCH_START.date().isoformat(), J.RESEARCH_END.date().isoformat()),
                         ("2021-10-19", "2026-10-19"))


class ContractStemTests(unittest.TestCase):
    """D13, D41, D45, D60 and D74: no About contract row says a bare "coverage" (the stem is barred; NOAA's "radar coverage"
    is allowed), and the rows that gave the stem its place say "no radar coverage" or "completeness"."""

    def test_no_contract_row_says_a_bare_coverage(self):
        from website import sources
        stem = re.compile(r"(?<!radar )\bcoverage\b", re.IGNORECASE)
        for key, row in sources.CONTRACTS.items():
            for field, text in row.items():
                if isinstance(text, str):
                    self.assertIsNone(stem.search(text), (key, field, text[:80]))
        self.assertIn("-3 is no radar coverage in NOAA's table", sources.CONTRACTS["hail_swath"]["missing"])
        self.assertIn("its completeness varies from county to county", sources.CONTRACTS["msl_addresses"]["missing"])

    def test_the_swdi_row_quotes_noaas_definition_of_prob(self):
        """D78(a) and D81(d): the SWDI row keeps NOAA's own definition of PROB, as a quotation (D13 allows a quoted source
        definition, and the words rule sets quoted wording aside before its scan)."""
        from website import sources
        units = sources.CONTRACTS["swdi_nx3hail"]["units"]
        self.assertIn('NOAA defines PROB as "the probability of hail in percent"', units)

    def test_the_about_visible_contract_fields_pass_the_words_rules(self):
        """D85: the About-visible fields of every contract row (name, request, units, timing, cadence, missing and terms)
        follow tests/words_rules.py. Set aside before the scan: NOAA's "radar coverage" (D45, the phrase the test above
        allows) and the State Library's address file name and product name (proper names, as the B3 exemptions in
        tests/test_site.py name them). Quoted wording is set aside by words_rules itself."""
        from website import sources
        proper = ("StructuresFramework_shp.zip", "Structures and Addresses Framework")
        for key, row in sources.CONTRACTS.items():
            for field in ("name", "request", "units", "timing", "cadence", "missing", "terms"):
                text = row.get(field)
                if not isinstance(text, str):
                    continue
                text = re.sub(r"radar coverage", " ", text, flags=re.IGNORECASE)
                for name in proper:
                    text = text.replace(name, " ")
                W.assert_clean(self, text, f"{key}.{field}")


class FixtureStationTests(unittest.TestCase):
    """D56: the sample store carries the station reader's part, cut from the real build: the tile lists of the sample tiles
    (the candidates the point picks read), the summaries of the stations they name (a station without a summary file is
    left out), and the index's stations block cut to those stations, marked as a sample. Without that block the summary
    reads every station row as "could not be loaded" while the joins part of the same page reads the gusts."""

    @staticmethod
    def entry(sid, name, lat, lon):
        return {"id": sid, "name": name, "lat": lat, "lon": lon, "miles": 1.0, "ok": 2000, "of": 2192, "share": 0.91}

    def write_source(self, src: Path):
        (src / "hail" / "tl").mkdir(parents=True)
        (src / "hail" / "sd").mkdir(parents=True)
        # the tile centre and ALPHA sit at towns.json's Billings point, the one Billings point the tests use (D80(a))
        tile = {"f": "hail-stn-tiles-v1", "miles": 40.0, "margin_miles": 3.8, "centre": [45.7833, -108.5007],
                "elements": {"SNOW": {"centre": [45.7833, -108.5007], "margin_miles": 3.8, "rejected": [],
            "passing": [self.entry("USC00000A01", "ALPHA", 45.7833, -108.5007),
                        self.entry("USC00000A02", "BETA", 45.9, -108.2)],
            "unread": [{"id": "USC00000A03", "name": "GAMMA", "lat": None, "lon": None, "reason": "its file did not load"}],
            "capped": False}}}
        (src / "hail" / "tl" / "T1.json").write_text(json.dumps(tile), encoding="utf-8")
        (src / "hail" / "sd" / "USC00000A01.json").write_text("{}", encoding="utf-8")     # BETA has no summary file
        return {"stations": {"as_of": "2026-10-16", "rule": {"radius_miles": 40.0}, "sources": {"ghcn": "x"},
                             "stations": {"USC00000A01": {"name": "ALPHA", "lat": 45.7833, "lon": -108.5007, "net": "COOP"},
                                          "USC00000A02": {"name": "BETA", "lat": 45.9, "lon": -108.2, "net": "COOP"}}}}

    def test_the_sample_keeps_a_row_for_every_named_station_and_a_summary_file_where_one_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            real = self.write_source(src)
            block, lists, ids = J._station_sample(src, real, ["T1", "T2"], ["USC00000G9"])
            self.assertEqual(ids, ["USC00000A01"])                      # only ALPHA has a summary file: the one copied
            self.assertEqual(sorted(block["stations"]), ["USC00000A01", "USC00000A02"])   # D74: BETA is named, so it has a row
            self.assertEqual(sorted(lists), ["T1"])                     # T2 has no list file, so none is written
            self.assertEqual((block["state"], block["sample"], block["as_of"]), ("loaded", True, "2026-10-16"))
            self.assertEqual(block["counts"], {"sample_tiles": 1, "sample_stations": 2})
            self.assertEqual(block["chosen_station_ids"], ["USC00000A01", "USC00000A02"])
            self.assertEqual(block["tile_lists"]["files"], 1)
            self.assertEqual(block["tile_lists"]["unread"], 1)
            self.assertNotIn("cap", block["tile_lists"])                # D61: no cap; the margin is recorded
            self.assertEqual((block["tile_lists"]["miles"], block["tile_lists"]["margin_miles_max"]), (40.0, 3.8))

    def test_the_sample_answers_the_point_picks_from_its_own_tile_list(self):
        # the shared rule (stations.tile_list_picks) reads the cut tile list and the cut block's net at the point
        from website import stations as stn
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            real = self.write_source(src)
            block, lists, _ids = J._station_sample(src, real, ["T1"], [])
            got = stn.tile_list_picks(lists["T1"]["elements"]["SNOW"], 45.7833, -108.5007, light=block["stations"])
            self.assertEqual([p["id"] for p in got["picks"]], ["USC00000A01", "USC00000A02"])
            self.assertEqual((got["picks"][0]["net"], got["picks"][0]["miles"]), ("COOP", 0.0))
            self.assertEqual(got["state"], "two")
            self.assertEqual([u["name"] for u in got["unread"]], ["GAMMA"])     # no position: named, never skipped (D32)

    def test_the_committed_fixture_ties_the_tile_lists_the_summaries_and_the_stations_block_together(self):
        # D74 (RV10): every station a tile list names has a row in the stations block; the summary files are those of the rows
        # that are loaded (not unread), every passing station has one, and the chosen set is the rows' set
        root = Path(J.__file__).resolve().parent / "data" / "hail-fixture" / "hail"
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        rows = index["stations"]["stations"]
        named, passing, lists = set(), set(), 0
        for path in sorted((root / "tl").glob("*.json")):
            lists += 1
            doc = json.loads(path.read_text(encoding="utf-8"))
            for part in doc["elements"].values():
                named.update(e["id"] for key in ("passing", "unread", "rejected") for e in part.get(key, []))
                passing.update(e["id"] for e in part.get("passing", []))
        files = {p.stem for p in (root / "sd").glob("*.json")}
        loaded = {sid for sid, row in rows.items() if not row.get("unread")}
        self.assertEqual(index["stations"]["tile_lists"]["files"], lists)
        self.assertFalse(named - set(rows), sorted(named - set(rows)))
        self.assertEqual(files, loaded)
        self.assertTrue(passing <= files, sorted(passing - files))
        self.assertEqual(index["stations"]["chosen_station_ids"], sorted(rows))
        self.assertEqual(index["stations"]["counts"]["sample_stations"], len(rows))

    def test_a_source_without_a_stations_block_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            self.write_source(src)
            block, _lists, ids = J._station_sample(src, {}, ["T1"], [])
            self.assertEqual(block["state"], "unavailable")
            # D28 and R14: the D20 sentence is the problem (the same words stations.py writes); the reason is the detail
            from website import stations as stn
            self.assertEqual(block["problem"], stn.WORDS["unavailable"])
            self.assertTrue(block["problem"].endswith("This is not an all-clear."), block["problem"])
            self.assertEqual(block["detail"], "the build the sample is cut from has no stations block")
            self.assertEqual(block["stations"], {})
            self.assertEqual(ids, [])                                    # no summary is named without the block's stations


if __name__ == "__main__":
    unittest.main()
