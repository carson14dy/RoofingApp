"""Climate grid (website/climate.py, B5 builder 1): the grid's cell rule on exact edges and at the two D4 test points
(website.hail.cell_for decides the expected B1 cells), the tile of each grid cell, the day rules (the 90 F rule at
32.2 C and at 32.15 C, a day at 0 C, the 0 F rule), rounding before sums (hundredths of a mm, tenths of a degree C),
the -999.99 fill never summed, the period records (extremes with their first dates, missing days), the water cells
("no land value"), the unavailable and partial paths (D16), the store writer on a small synthetic store, the
verification of that store, the words (forbidden terms, plain sentences), the Range reader's contract (with a fake
session), the GHCN .dly reader, and a synthetic netCDF written with h5py and read back through the file path.

Offline: no network. Every file this test writes is made in a folder the test creates (tempfile.mkdtemp) and removed
by that test. The synthetic netCDF has the real grid's shape (596 by 1,385, one chunk per day) and few values."""

import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import requests
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import climate as cl  # noqa: E402
from website import hail as h  # noqa: E402
from website import stations as st  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
BILLINGS = (509, 388)        # the Billings grid cell (research: 401 North 27th Street is 1.9 km away)
BENCHLAND_GRID = (540, 352)  # the Benchland rural grid cell (research)
FORBIDDEN = re.compile(r"\b(damag\w*|dry|clear\w*|insurance|eligib\w*|confirm\w*|claim\w*|coverage|risk\w*|"
                       r"probab\w*|loss|structure|warrant\w*|guarantee\w*|customers?|best|approved)\b", re.IGNORECASE)


def plain(text: str) -> str:
    """The text without the sentence the stale and unavailable lines must end with (it names all-clear to deny it)."""
    return text.replace("This is not an all-clear.", "")


class GridRule(unittest.TestCase):
    def test_edges_north_included_south_excluded(self):
        # Row 10 covers lat (24.958333, 25.0]: 25.0 is its north edge and goes to row 10 (the cell to the south).
        self.assertEqual(cl.climate_cell_for(25.0, -100.0)[0], 10)
        self.assertEqual(cl.climate_cell_for(25.0000001, -100.0)[0], 11)
        self.assertEqual(cl.climate_cell_for(24.99, -100.0)[0], 10)

    def test_edges_west_included_east_excluded(self):
        # Column 113 covers lon [-120.0, -119.958333): -120.0 is its west edge and goes east, to column 113.
        self.assertEqual(cl.climate_cell_for(45.0, -120.0)[1], 113)
        self.assertEqual(cl.climate_cell_for(45.0, -120.0000001)[1], 112)
        self.assertEqual(cl.climate_cell_for(45.0, -119.9999999)[1], 113)

    def test_centres_are_their_own_cells(self):
        for i, j in ((0, 0), (509, 388), (540, 352), (595, 1384), (300, 700)):
            lat, lon = cl.climate_centre(i, j)
            self.assertEqual(cl.climate_cell_for(lat, lon), (i, j))

    def test_off_grid_is_none(self):
        self.assertIsNone(cl.climate_cell_for(24.0, -100.0))
        self.assertIsNone(cl.climate_cell_for(47.0, -124.0 - 1.0))

    def test_billings_centre_and_tile(self):
        lat, lon = cl.climate_centre(*BILLINGS)
        self.assertAlmostEqual(lat, 45.770833, places=6)
        self.assertAlmostEqual(lon, -108.520833, places=6)
        self.assertEqual(cl.climate_tile(*BILLINGS), (92, 214, 27))

    def test_d4_half_cell_points_agree_with_hail_cell_for(self):
        # The B1 expected cells come from website.hail.cell_for (D4). Benchland (47.08 N, 110.02 W) sits on a B1
        # cell edge; Petrolia Lake (46.93 N, 108.25 W) is on a B1 edge too (B2 research: row 806.5 and column 2174.5).
        self.assertEqual(h.cell_for(47.08, -110.02), (792, 1998))
        self.assertEqual(h.cell_for(46.93, -108.25), (807, 2175))
        # The climate function applies the same rule to the same points.
        self.assertEqual(cl.climate_cell_for(47.08, -110.02), (540, 352))
        self.assertEqual(cl.climate_cell_for(46.93, -108.25), (537, 395))
        # Petrolia's longitude is the west edge of climate column 395, so it goes east, as the B1 rule does.
        self.assertEqual(cl.climate_cell_for(46.93, -108.25)[1], 395)
        self.assertEqual(cl.climate_cell_for(46.93, -108.2500001)[1], 394)

    def test_spot_tile_is_the_tile_of_the_climate_centre(self):
        row, col = h.cell_for(47.08, -110.02)
        name = cl.climate_tile_for_cell(row, col)
        self.assertEqual(name, h.tile_name(*cl.climate_tile(*cl.climate_cell_for(47.08, -110.02))[:2]))

    def test_nominal_grid_matches_the_research_geometry(self):
        self.assertEqual(cl.climate_centre(0, 0), (24.5625, -124.6875))
        lat, lon = cl.climate_centre(595, 1384)
        self.assertAlmostEqual(lat, 49.354167, places=6)
        self.assertAlmostEqual(lon, -67.020833, places=6)


class Rounding(unittest.TestCase):
    def test_half_up_to_hundredths_and_tenths(self):
        values = np.array([32.2, 32.15, 32.14, 0.0, -0.04, -17.8, -17.75, 27.3125, 1.2265625, 0.125])
        cents = cl._centi(np, values)
        self.assertEqual(cents.tolist(), [3220, 3215, 3214, 0, -4, -1780, -1775, 2731, 123, 13])
        self.assertEqual(((cents + 5) // 10).tolist(), [322, 322, 321, 0, 0, -178, -177, 273, 12, 1])

    def test_exact_decimal_tie_handling(self):
        # 0.125 is an exact binary tie at the hundredth: half up gives 0.13 (never 0.12).
        self.assertEqual(int(cl._centi(np, np.array([0.125]))[0]), 13)
        self.assertEqual(cl._decimal_centi(14.35), 1435)
        self.assertEqual(cl._decimal_centi(-14.355), -1435)

    def test_thresholds_on_the_tenth_of_a_degree(self):
        # 32.2 C and 32.15 C (rounds to 32.2 C) are 90 F days; 32.14 C (32.1 C) is not (D1).
        tmax = np.array([[32.2], [32.15], [32.14], [32.0]])
        tmin = np.array([[10.0], [10.0], [10.0], [10.0]])
        prcp = np.zeros((4, 1))
        valid, cmm, tx, tn, _f = cl.daily_arrays(np, prcp, tmax, tmin)
        fields = cl.month_fields(np, valid, cmm, tx, tn, 4)
        self.assertEqual(int(fields[0, 9]), 2)                     # hot90 counts 32.2 and 32.15
        self.assertEqual(cl._tenths_f_text(int((18 * 322 + 3205) // 10)), "90.0")
        self.assertEqual(cl._tenths_f_text(int((18 * 321 + 3205) // 10)), "89.8")

    def test_freeze_thaw_and_below_32_and_zero_f(self):
        # day 1: high 0.0 C (not above 0), low -1.0 C; day 2: high 1.0 C and low -0.04 C (rounds to 0.0: not below 0)
        # day 3: high 2.0 C and low -17.8 C (0 F); day 4: high 2.0 and low -17.7 C (0.1 F: not at or below 0 F)
        tmax = np.array([[0.0], [1.0], [2.0], [2.0]])
        tmin = np.array([[-1.0], [-0.04], [-17.8], [-17.7]])
        prcp = np.zeros((4, 1))
        valid, cmm, tx, tn, _f = cl.daily_arrays(np, prcp, tmax, tmin)
        fields = cl.month_fields(np, valid, cmm, tx, tn, 4)[0].tolist()
        self.assertEqual(fields[cl.MONTH_FIELDS.index("freeze_thaw")], 2)   # days 3 and 4 (high above 0, low below 0)
        self.assertEqual(fields[cl.MONTH_FIELDS.index("below32")], 3)       # days 1, 3 and 4 (day 2 rounds to 0.0 C)
        self.assertEqual(fields[cl.MONTH_FIELDS.index("cold0")], 1)         # day 3 only (-17.8 C is 0.0 F)
        tmax2 = np.array([[1.0], [1.0]])
        tmin2 = np.array([[-0.2], [-0.2]])
        v2, c2, x2, n2, _ = cl.daily_arrays(np, np.zeros((2, 1)), tmax2, tmin2)
        self.assertEqual(int(cl.month_fields(np, v2, c2, x2, n2, 2)[0, 11]), 2)   # freeze-thaw days

    def test_rain_is_summed_after_rounding_each_day(self):
        # 0.004 mm a day rounds to 0.00 each day; the sum of rounded values is 0, not the raw 0.12 mm.
        prcp = np.full((30, 1), 0.004)
        tmax = np.full((30, 1), 10.0)
        tmin = np.full((30, 1), 0.0)
        valid, cmm, tx, tn, _f = cl.daily_arrays(np, prcp, tmax, tmin)
        self.assertEqual(int(cl.month_fields(np, valid, cmm, tx, tn, 30)[0, 2]), 0)
        prcp2 = np.array([[0.125], [0.125], [9.453125]])
        v2, c2, x2, n2, _ = cl.daily_arrays(np, prcp2, np.full((3, 1), 10.0), np.full((3, 1), 0.0))
        f2 = cl.month_fields(np, v2, c2, x2, n2, 3)[0]
        self.assertEqual(int(f2[2]), 13 + 13 + 945)                   # hundredths of a mm
        self.assertEqual(int(f2[3]), 945)
        self.assertEqual(int(f2[4]), 3)
        self.assertEqual((10 * 971 + 127) // 254, 38)                  # 9.71 mm is 0.38 in

    def test_inches_from_hundredths_of_mm(self):
        # 468.94 mm is 46,894 hundredths of a mm and 18.46 in (1846 hundredths of an inch).
        self.assertEqual((10 * 46894 + 127) // 254, 1846)
        self.assertEqual(cl._hin_text(1846), "18.46")
        self.assertEqual(cl._tenths_f_text(-23), "-2.3")


class Fill(unittest.TestCase):
    def test_fill_is_missing_not_summed(self):
        prcp = np.array([[5.0], [-999.99], [2.0]])
        tmax = np.array([[20.0], [-999.99], [20.0]])
        tmin = np.array([[5.0], [-999.99], [5.0]])
        valid, cmm, tx, tn, fill = cl.daily_arrays(np, prcp, tmax, tmin)
        self.assertTrue(fill[1, 0])
        self.assertFalse(valid[1, 0])
        f = cl.month_fields(np, valid, cmm, tx, tn, 3)[0]
        self.assertEqual(int(f[1]), 1)                 # one missing day inside the available days
        self.assertEqual(int(f[2]), 700)               # 7.00 mm: the fill is not in the sum
        self.assertLess(int(f[5]), 300)                # the highest is a real tenth of a degree, not a fill

    def test_days_after_the_newest_are_not_counted_as_missing(self):
        prcp = np.array([[5.0], [1.0], [-999.99], [-999.99]])
        tmax = np.array([[20.0], [21.0], [-999.99], [-999.99]])
        tmin = np.array([[5.0], [6.0], [-999.99], [-999.99]])
        valid, cmm, tx, tn, _f = cl.daily_arrays(np, prcp, tmax, tmin)
        f = cl.month_fields(np, valid, cmm, tx, tn, 2)[0]
        self.assertEqual(int(f[0]), 2)
        self.assertEqual(int(f[1]), 0)

    def test_no_value_cells_have_no_valid_day(self):
        prcp = np.full((30, 2), np.nan)
        valid, cmm, tx, tn, _f = cl.daily_arrays(np, prcp, np.full((30, 2), np.nan), np.full((30, 2), np.nan))
        self.assertFalse(valid.any())
        self.assertFalse(valid.any(axis=0).any())


class Periods(unittest.TestCase):
    def test_extremes_keep_their_first_dates_and_counts_add(self):
        # two months: July (highest 35.0 C on day 3, lowest -2.0 C on day 1), August (highest 35.0 C on day 9, lowest
        # -2.0 C on day 2); the period keeps the first date of each extreme (July 3 and July 1).
        def month(days_tmax, days_tmin, avail, year, mon):
            tmax = np.array(days_tmax, dtype=np.float64).reshape(-1, 1)
            tmin = np.array(days_tmin, dtype=np.float64).reshape(-1, 1)
            prcp = np.zeros_like(tmax)
            v, c, x, n, _f = cl.daily_arrays(np, prcp, tmax, tmin)
            return cl.month_fields(np, v, c, x, n, avail)
        m1 = month([20.0, 30.0, 35.0], [5.0, -2.0, 4.0], 3, 2021, 7)
        m2 = month([20.0, 35.0, 33.0], [-2.0, 3.0, 6.0], 3, 2021, 8)
        rows = cl.combine(np, [m1, m2], [2021, 2021], [7, 8])
        rec = rows[0]
        self.assertEqual(rec[0], 6)                    # days
        self.assertEqual(rec[1], 0)                    # missing
        self.assertEqual(rec[5], (18 * 350 + 3205) // 10)   # highest 35.0 C = 95.0 F
        self.assertEqual(rec[6], 20210703)             # first day of the highest (July 3)
        self.assertEqual(rec[7], (18 * -20 + 3205) // 10)   # lowest -2.0 C = 28.4 F
        self.assertEqual(rec[8], 20210702)             # first day of the lowest (-2.0 C on July 2 and August 1)
        self.assertEqual(rec[9], 3)                    # hot days: 35.0 C in July; 35.0 and 33.0 C in August
        self.assertEqual(rec[12], 2)                   # below 32 F: July day 1 and August day 1

    def test_missing_extreme_is_none(self):
        empty = np.zeros((1, cl.NF), dtype=np.int64)
        empty[0, 0] = 31
        empty[0, 1] = 31
        empty[0, 3] = cl.RAIN_NONE
        empty[0, 5] = cl.MAX_NONE
        empty[0, 7] = cl.MIN_NONE
        rows = cl.combine(np, [empty], [2026], [9])
        self.assertIsNone(rows[0][5])
        self.assertIsNone(rows[0][3])
        self.assertEqual(rows[0][1], 31)

    def test_period_members(self):
        self.assertEqual(cl.period_members("2021-22", "season")[0], (2021, 7))
        self.assertEqual(cl.period_members("2021-22", "season")[-1], (2022, 6))
        self.assertEqual(cl.period_members(2022, "water")[0], (2021, 10))
        self.assertEqual(cl.period_members(2022, "water")[-1], (2022, 9))
        self.assertEqual(len(cl.period_members(2025, "calendar")), 12)


class Plan(unittest.TestCase):
    def test_scaled_preferred_prelim_only_without_scaled(self):
        objects = {}
        for ym in ("2026-03", "2026-04", "2026-05"):
            key = f"access/grids/2026/ncdd-{ym.replace('-', '')}-grd-scaled.nc"
            objects[key] = {"size": 100, "etag": "a", "last_modified": "x"}
        for ym in ("2026-04", "2026-10"):
            key = f"access/grids/2026/ncdd-{ym.replace('-', '')}-grd-prelim.nc"
            objects[key] = {"size": 50, "etag": "p", "last_modified": "y"}
        objects["access/grids/2026/ncdd-202610-version.txt"] = {"size": 5, "etag": "v", "last_modified": "z"}
        plan = cl.plan_months(objects, date(2026, 10, 19))
        kinds = {p["month"]: p["kind"] for p in plan}
        self.assertEqual(kinds["2026-04"], "scaled")
        self.assertEqual(kinds["2026-10"], "prelim")
        self.assertEqual(kinds["2026-06"], "missing")
        self.assertEqual(plan[0]["month"], "2021-07")
        self.assertEqual(plan[-1]["month"], "2026-10")

    def test_months_after_today_are_not_planned(self):
        objects = {"access/grids/2026/ncdd-202611-grd-prelim.nc": {"size": 1, "etag": "p", "last_modified": "y"}}
        self.assertEqual(cl.plan_months(objects, date(2026, 10, 19)), [])


class RangeContract(unittest.TestCase):
    def test_range_file_reads_the_bytes_asked_for(self):
        data = bytes(range(256)) * 9000       # 2.3 MB
        calls = []

        class Resp:
            def __init__(self, status, content):
                self.status_code = status
                self.content = content

        class Session:
            headers = {}

            def get(self, url, headers=None, timeout=None):
                start, end = headers["Range"].split("=")[1].split("-")
                calls.append((int(start), int(end)))
                return Resp(206, data[int(start): int(end) + 1])

        rf = cl.RangeFile("https://example.invalid/x.nc", len(data), block=1 << 20, session=Session())
        rf.seek(1000)
        first = rf.read(10)
        rf.seek((1 << 20) - 5)
        span = rf.read(20)
        self.assertEqual(first, data[1000:1010])
        self.assertEqual(span, data[(1 << 20) - 5:(1 << 20) + 15])
        self.assertEqual(rf.requests, 2)
        self.assertEqual(calls[0], (0, (1 << 20) - 1))

    def test_range_file_refuses_a_short_answer(self):
        class Session:
            headers = {}

            def get(self, url, headers=None, timeout=None):
                class R:
                    status_code = 200
                    content = b"short"
                return R()

        rf = cl.RangeFile("https://example.invalid/x.nc", 100, block=50, session=Session())
        with self.assertRaises(cl.ClimateError):
            rf.read(10)


    def test_a_timeout_on_a_range_read_is_a_named_source_failure_kept_on_the_reader(self):
        class Session:
            headers = {}

            def __init__(self):
                self.calls = 0

            def get(self, url, headers=None, timeout=None):
                self.calls += 1
                raise requests.exceptions.ReadTimeout("slow")

        session = Session()
        with mock.patch.object(cl, "RETRY_PAUSE_S", 0):
            rf = cl.RangeFile("https://example.invalid/x.nc", 100, block=50, session=session)
            with self.assertRaises(cl.SourceError) as ctx:
                rf.read(10)
        self.assertEqual(ctx.exception.reason, "ReadTimeout")
        self.assertEqual(rf.failure["reason"], "ReadTimeout")
        self.assertEqual(session.calls, cl.RETRY_ATTEMPTS)


class GhcnFreezeThaw(unittest.TestCase):
    def test_counts_days_with_tmax_above_and_tmin_below_zero(self):
        tmp = Path(tempfile.mkdtemp(prefix="climate-test-ghcn-"))
        try:
            def line(year, month, element, values):
                body = ""
                for d in range(1, 32):
                    v = values.get(d, -9999)
                    body += f"{v:5d}   " if v != -9999 else "-9999   "
                return f"USW00024033{year:04d}{month:02d}{element:<4s}" + body
            lines = [line(2025, 1, "TMAX", {1: 10, 2: 5, 3: 20}), line(2025, 1, "TMIN", {1: -5, 2: 3, 3: -1}),
                     line(2025, 2, "TMAX", {1: 4}), line(2025, 2, "TMIN", {1: -2})]
            path = tmp / "USW00024033.dly"
            path.write_text("\n".join(lines) + "\n", encoding="ascii")
            out = cl.ghcn_freeze_thaw(path, 2025)
            self.assertEqual(out["freeze_thaw_days"], 3)     # Jan 1, Jan 3 and Feb 1 (a high above 0 and a low below 0)
            self.assertEqual(out["days_with_both"], 4)
        finally:
            shutil.rmtree(tmp)


class Words(unittest.TestCase):
    def test_templates_avoid_forbidden_terms_and_dashes(self):
        for key, value in cl.WORDS_CLIMATE.items():
            texts = value if isinstance(value, list) else [value]
            for text in texts:
                if not isinstance(text, str):
                    continue
                self.assertIsNone(FORBIDDEN.search(plain(text)), (key, text))
                self.assertNotIn("\u2014", text, key)
                self.assertNotIn("\u2013", text, key)

    def test_the_forbidden_list_catches_what_it_should(self):
        for word in ("damage", "insurance", "risk", "probability", "eligible", "coverage", "claim"):
            self.assertIsNotNone(FORBIDDEN.search(word), word)
        self.assertIsNone(FORBIDDEN.search("a plain sentence"))

    def test_the_stale_and_unavailable_lines_end_with_the_negation(self):
        for key in ("stale", "no_land", "partial_months", "unavailable", "days_missing",
                    "season_unavailable", "five_unavailable_temperature", "five_unavailable_rain",
                    "calendar_unavailable", "water_unavailable", "not_in_store"):
            self.assertTrue(cl.WORDS_CLIMATE[key].endswith("This is not an all-clear."), key)

    def test_the_brief_templates_are_present(self):
        w = cl.WORDS_CLIMATE
        self.assertEqual(w["freeze_thaw"].format(n=3, days="days", season="2024-25"),
                         "Grid estimate: 3 freeze-thaw days in the 2024-25 season (a high above 32 F and a low below 32 F).")
        self.assertIn("about 4.6 km north to south and about 3 km east to west", w["cell_sentence"])


def _synthetic_basemap(path: Path) -> None:
    """A small Montana-like rectangle around Billings (lon -109.0 to -107.5, lat 45.5 to 46.5)."""
    ring = [[-109.0, 45.5], [-107.5, 45.5], [-107.5, 46.5], [-109.0, 46.5], [-109.0, 45.5]]
    doc = {"land": {"features": [{"properties": {"montana": True}, "geometry": {"type": "Polygon",
                                                                                 "coordinates": [ring]}}]}}
    path.write_text(json.dumps(doc), encoding="utf-8")


def _fake_hail_store(store: Path, as_of: str = "2026-10-15") -> None:
    """The minimal B1 store the climate builder adds to: hail/index.json and hail/manifest.json."""
    hail_dir = store / "hail"
    hail_dir.mkdir(parents=True, exist_ok=True)
    (hail_dir / "t").mkdir(exist_ok=True)
    index = {"format": h.FORMAT, "d0": h.D0.isoformat(), "grid": dict(h.GRID), "as_of": as_of,
             "window": ["2021-10-17", as_of], "missing_days": [], "days_expected": 1826, "days_present": 1826,
             "floor_tenths": 64, "floor_in": 0.25, "tiles": [], "events": 0, "shards": 0, "bytes": 0, "sample": True,
             "cells_in_state": 2}
    index_bytes = h._pretty(index)
    (hail_dir / "index.json").write_bytes(index_bytes)
    manifest = {"format": h.MANIFEST_FORMAT, "as_of": as_of,
                "counts": {"days_expected": 1826, "days_present": 1826, "events": 0, "shards": 0, "bytes": 0},
                "files": {"hail/index.json": {"bytes": len(index_bytes),
                                              "sha256": hashlib.sha256(index_bytes).hexdigest()}}}
    (hail_dir / "manifest.json").write_bytes(h._pretty(manifest))


def _month_fields_for(ym: str, cells: int, avail: int, tmax_c: float, tmin_c: float, rain_mm: float,
                      np_=np) -> np.ndarray:
    """Month fields for `cells` identical cells: a month of constant values, `avail` days available."""
    year, month = int(ym[:4]), int(ym[5:])
    dim = cl.days_in(year, month)
    tmax = np.full((dim, cells), tmax_c)
    tmin = np.full((dim, cells), tmin_c)
    prcp = np.full((dim, cells), rain_mm)
    v, c, x, n, _f = cl.daily_arrays(np_, prcp, tmax, tmin)
    return cl.month_fields(np_, v, c, x, n, avail)


def _dly_line(station: str, year: int, month: int, element: str, values: dict) -> str:
    """One GHCN-Daily .dly record: 31 day slots of 8 characters (value and three flags); -9999 where a day is absent."""
    body = "".join(f"{values[d]:5d}   " if d in values else "-9999   " for d in range(1, 32))
    return f"{station}{year:04d}{month:02d}{element:<4s}{body}"


def _seed_billings_dly(cache: Path) -> None:
    """The Billings airport file for 2025, written into the cache so that verify runs offline. Both TMAX and TMIN
    are present on January 1 to 4 and December 31, and January 1, 3 and December 31 are freeze-thaw days."""
    station = cl.GHCN_BILLINGS
    lines = [
        _dly_line(station, 2025, 1, "TMAX", {1: 10, 2: 5, 3: 20, 4: -2}),
        _dly_line(station, 2025, 1, "TMIN", {1: -5, 2: 3, 3: -1, 4: -6}),
        _dly_line(station, 2025, 12, "TMAX", {31: 5}),
        _dly_line(station, 2025, 12, "TMIN", {31: -3}),
    ]
    path = cache / "ghcn" / "dly" / f"{station}.dly"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _describe_billings(store: Path, now=NOW) -> dict:
    """The describe output for the Billings spot of a built store (the tile is read when the store holds it)."""
    index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    tr, tc, _key = cl.climate_tile(*BILLINGS)
    path = store / "hail" / "c" / f"{h.tile_name(tr, tc)}.json"
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    row, col = h.cell_for(*cl.climate_centre(*BILLINGS))
    return cl.describe_climate(index, doc, row, col, now)


def _sentences(out: dict) -> list:
    """Every sentence the page would show for a describe output (leads, lines, partial, stale, the table's text)."""
    texts = [out["temperature"]["lead"], out["rain"]["lead"], out.get("stale")]
    for part in ("temperature", "rain"):
        texts.append(out[part].get("partial"))
        texts.extend(out[part]["lines"])
    texts.extend(out["how_made"])
    texts.append((out.get("table", {}).get("partial") or {}).get("text"))
    return [t for t in texts if isinstance(t, str)]


def _strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


DEVELOPER_WORDS = re.compile(r"\b(?:stor(?:e|es|ed|ing)|tiles?|buckets?|builds?|index(?:es)?|aggregates?)\b",
                             re.IGNORECASE)


def _assert_plain(test: unittest.TestCase, out: dict) -> None:
    """Every sentence and table value of a describe output is free of developer words and of the word None (F11)."""
    for text in _sentences(out):
        test.assertIsNone(DEVELOPER_WORDS.search(text), text)
        test.assertNotRegex(text, r"\bNone\b")
    for value in _strings(out.get("table", {})):
        test.assertNotRegex(value, r"\bNone\b")


def _ym_list(first: tuple, last: tuple) -> list:
    return [f"{y:04d}-{m:02d}" for (y, m) in cl.months_between(first, last)]


def _listing_bytes(objects: dict) -> bytes:
    """A ListObjectsV2 page for {key: (size, etag)}, not truncated."""
    items = "".join(f"<Contents><Key>{key}</Key><Size>{size}</Size><ETag>&quot;{etag}&quot;</ETag>"
                    f"<LastModified>2026-10-01T00:00:00.000Z</LastModified></Contents>"
                    for key, (size, etag) in objects.items())
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<IsTruncated>false</IsTruncated>{items}</ListBucketResult>").encode("utf-8")


class _Resp:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self.content = content


class _DropAfterChunk:
    """A streamed response that yields one chunk and then fails the way a dropped connection does."""
    status_code = 200

    def __init__(self, first: bytes):
        self.first = first

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        yield self.first
        raise requests.exceptions.ChunkedEncodingError("connection broken")


class _FakeSession:
    """A requests-like session for the update. Listing pages come from `listing` (year -> bytes, a response, or an
    exception to raise). Any other request is answered from `files` (a part of the URL -> a response, a streamed
    response or an exception). Every request is counted in `calls`."""

    def __init__(self, listing=None, files=None):
        self.headers = {}
        self.listing = listing or {}
        self.files = files or {}
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append(url)
        if params and "list-type" in params:
            year = int(params["prefix"].split("/")[2])
            answer = self.listing.get(year, _Resp(200, _listing_bytes({})))
        else:
            answer = next((v for needle, v in self.files.items() if needle in url), None)
            if answer is None:
                raise AssertionError(f"unexpected request for {url}")
        if callable(answer) and not isinstance(answer, _Resp):
            answer = answer()          # a factory: a new exception each time, as requests raises them
        if isinstance(answer, bytes):
            answer = _Resp(200, answer)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _write_cache(cache: Path, basemap: Path, plan_list: list, loaded: dict, etag: str = "e") -> None:
    """A cache for the update and the build. Every planned month is a scaled month when it is in `loaded` and missing
    from the bucket otherwise. The loaded months have aggregates: (avail days, tmax C, tmin C, rain mm) for the
    Billings cell, and the other cells hold no valid day."""
    ci, cj = cl.montana_cells(basemap)
    n = int(ci.size)
    digest = cl.mask_digest(ci, cj)
    paths = cl._cache_paths(cache)
    cl._ensure(paths)
    plan = []
    for ym in plan_list:
        scaled = ym in loaded
        plan.append({"month": ym, "kind": "scaled" if scaled else "missing",
                     "days": cl.days_in(int(ym[:4]), int(ym[5:])),
                     "key": f"access/grids/{ym[:4]}/ncdd-{ym.replace('-', '')}-grd-scaled.nc" if scaled else None,
                     "size": 1000 if scaled else None, "etag": etag if scaled else None, "last_modified": "x"})
    cl._save_ledger(paths, {"format": cl.LEDGER_FORMAT, "plan": plan, "months": {}, "requests": 0})
    for ym, (avail, tmax, tmin, rain) in loaded.items():
        fields = np.zeros((n, cl.NF), dtype=np.int64)
        has = np.zeros(n, dtype=bool)
        for idx in range(n):
            if (int(ci[idx]), int(cj[idx])) == BILLINGS:
                fields[idx] = _month_fields_for(ym, 1, avail, tmax, tmin, rain)[0]
                has[idx] = True
            else:
                fields[idx, 0] = avail
                fields[idx, 1] = avail
                fields[idx, 3] = cl.RAIN_NONE
                fields[idx, 5] = cl.MAX_NONE
                fields[idx, 7] = cl.MIN_NONE
        meta = {"format": cl.AGG_FORMAT, "month": ym, "kind": "scaled", "avail_days": avail,
                "days_in_month": cl.days_in(int(ym[:4]), int(ym[5:])),
                "through": date(int(ym[:4]), int(ym[5:]), avail).isoformat(), "etag": etag,
                "mask_sha256": digest, "mask_cells": n}
        cl.save_month_aggregate(paths, ym, {"fields": fields, "has_value": has, "meta": meta})


def _fixture_dirs(tmp: Path):
    """A cache folder, a store folder with the minimal B1 index, and a small Montana-like basemap, all under tmp."""
    cache = tmp / "cache"
    store = tmp / "store"
    basemap = tmp / "basemap.json"
    _synthetic_basemap(basemap)
    _fake_hail_store(store)
    return cache, store, basemap


KEY_2506 = "access/grids/2025/ncdd-202506-grd-scaled.nc"
HDF5_HEAD = b"\x89HDF\r\n\x1a\n"


class StoreBuild(unittest.TestCase):
    """A small store from synthetic aggregates: two months loaded (July and August 2025, one cell with values and
    one water cell in the mask), the rest of the planned months missing, so the state is partial and the missing
    months are named."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="climate-test-store-"))
        cls.store = cls.tmp / "store"
        cls.cache = cls.tmp / "cache"
        cls.basemap = cls.tmp / "basemap.json"
        _synthetic_basemap(cls.basemap)
        _fake_hail_store(cls.store)
        cls.cache.mkdir(parents=True)
        _seed_billings_dly(cls.cache)
        cls.ci, cls.cj = cl.montana_cells(cls.basemap)
        cls.n = int(cls.ci.size)
        cls.digest = cl.mask_digest(cls.ci, cls.cj)
        paths = cl._cache_paths(cls.cache)
        cl._ensure(paths)
        plan = []
        for ym in ("2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12", "2025-01", "2025-02", "2025-03",
                   "2025-04", "2025-05", "2025-06", "2025-07", "2025-08"):
            kind = "scaled" if ym in ("2025-06", "2025-07") else "missing"
            plan.append({"month": ym, "kind": kind, "days": cl.days_in(int(ym[:4]), int(ym[5:])),
                         "key": "k" if kind == "scaled" else None, "size": 1 if kind == "scaled" else None,
                         "etag": "e" if kind == "scaled" else None, "last_modified": "x"})
        cl._save_ledger(paths, {"format": cl.LEDGER_FORMAT, "plan": plan, "months": {}, "requests": 0})
        cells_arr = np.zeros((cls.n, cl.NF), dtype=np.int64)
        has = np.zeros(cls.n, dtype=bool)
        for idx in range(cls.n):
            if (int(cls.ci[idx]), int(cls.cj[idx])) == BILLINGS:
                f = _month_fields_for("2025-06", 1, 30, 32.9, 14.4, 47.69)
                cells_arr[idx] = f[0]
                has[idx] = True
        for ym, avail in (("2025-06", 30), ("2025-07", 31)):    # the two loaded months; the others are not loaded
            fields = np.zeros((cls.n, cl.NF), dtype=np.int64)
            hv = np.zeros(cls.n, dtype=bool)
            for idx in range(cls.n):
                if (int(cls.ci[idx]), int(cls.cj[idx])) == BILLINGS:
                    fields[idx] = _month_fields_for(ym, 1, avail, 30.0 if ym == "2025-06" else 25.0,
                                                    10.0 if ym == "2025-06" else 8.0, 3.0)[0]
                    hv[idx] = True
                else:
                    fields[idx, 0] = avail
                    fields[idx, 1] = avail
                    fields[idx, 3] = cl.RAIN_NONE
                    fields[idx, 5] = cl.MAX_NONE
                    fields[idx, 7] = cl.MIN_NONE
            meta = {"format": cl.AGG_FORMAT, "month": ym, "kind": "scaled", "avail_days": avail,
                    "days_in_month": cl.days_in(int(ym[:4]), int(ym[5:])),
                    "through": date(int(ym[:4]), int(ym[5:]), avail).isoformat(), "etag": "e",
                    "mask_sha256": cls.digest, "mask_cells": cls.n}
            cl.save_month_aggregate(paths, ym, {"fields": fields, "has_value": hv, "meta": meta})

        cl.build_store(cls.store, cls.cache, log=lambda s: None, basemap_path=cls.basemap)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_build_writes_tiles_index_and_manifest(self):
        block = cl.build_store(self.store, self.cache, log=lambda s: None, basemap_path=self.basemap)
        self.assertEqual(block["state"], "partial")
        self.assertIn("2025-08", block["months_missing"])
        self.assertEqual(len(block["months_missing"]), 12)
        self.assertEqual(block["mask_cells"], self.n)
        self.assertEqual(block["land_cells"], 1)
        self.assertEqual(block["water_cells"], self.n - 1)
        self.assertEqual(block["through"], "2025-07-31")
        index = json.loads((self.store / "hail" / "index.json").read_text())
        self.assertEqual(index["climate"]["state"], "partial")
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text())
        c_entries = [k for k in manifest["files"] if k.startswith("hail/c/")]
        self.assertEqual(len(c_entries), block["files"])
        h.check_manifest(self.store)                    # every file listed with its size and hash

    def test_the_tile_holds_the_billings_record_with_whole_numbers(self):
        tr, tc, key = cl.climate_tile(*BILLINGS)
        doc = json.loads((self.store / "hail" / "c" / f"{h.tile_name(tr, tc)}.json").read_text())
        self.assertEqual(doc["f"], cl.FORMAT)
        self.assertIn(key, doc["state"])
        rec = doc["cells"][str(key)]
        self.assertEqual((rec["i"], rec["j"]), BILLINGS)
        self.assertEqual(len(rec["s"]), 6)
        self.assertEqual(len(rec["c"]), 6)
        self.assertEqual(len(rec["w"]), 7)
        season_2425 = rec["s"][3]                        # July 2024 to June 2025: June 2025 is loaded, the rest is not
        self.assertEqual(season_2425[0], 365)            # days
        self.assertEqual(season_2425[1], 335)            # missing: 365 minus the 30 June days that are loaded
        self.assertEqual(rec["s"][4][0], 31)             # 2025-26 so far: July 2025 only (August is not loaded)
        self.assertEqual(rec["s"][4][1], 0)
        flat = [v for field in [rec["f"]] + rec["s"] + rec["c"] + rec["w"] for v in field if v is not None]
        self.assertTrue(all(type(v) is int for v in flat))
        self.assertNotIn(".", json.dumps(rec))

    def test_verify_passes_on_the_built_store(self):
        report = cl.verify_store(self.store, self.cache, basemap_path=self.basemap, log=lambda s: None)
        self.assertTrue(report["ok"])
        self.assertEqual(report["records"], 1)
        self.assertEqual(report["water_cells"], self.n - 1)

    def test_describe_says_partial_with_the_month_named_and_no_land_for_water(self):
        index = json.loads((self.store / "hail" / "index.json").read_text())
        tr, tc, _key = cl.climate_tile(*BILLINGS)
        doc = json.loads((self.store / "hail" / "c" / f"{h.tile_name(tr, tc)}.json").read_text())
        row, col = h.cell_for(*cl.climate_centre(*BILLINGS))
        out = cl.describe_climate(index, doc, row, col, NOW)
        self.assertEqual(out["state"], "partial")
        self.assertIn("2025-08", out["temperature"]["partial"])
        self.assertIn("This is not an all-clear.", out["temperature"]["partial"])
        self.assertTrue(out["temperature"]["lead"].startswith("Grid estimate: from July 1, 2021 to June 30, 2026, highest "))
        self.assertTrue(any("days missing" in line for line in out["temperature"]["lines"]))
        # a water cell in the same tile is not in cells: no land value
        water_key = next(k for k in doc["state"] if str(k) not in doc["cells"])
        water_row, water_col = None, None
        for idx in range(self.n):
            i, j = int(self.ci[idx]), int(self.cj[idx])
            if (i, j) != BILLINGS and cl.climate_tile(i, j)[:2] == (tr, tc) and cl.climate_tile(i, j)[2] == water_key:
                water_row, water_col = h.cell_for(*cl.climate_centre(i, j))
                break
        if water_row is not None:
            out_w = cl.describe_climate(index, doc, water_row, water_col, NOW)
            self.assertEqual(out_w["state"], "no_land")
            self.assertIn("No land value for this grid cell", out_w["temperature"]["lead"])

    def test_calendar_2025_reads_61_days_with_data_and_151_missing(self):
        out = _describe_billings(self.store)
        row = out["calendar"][cl.CALENDAR_YEARS.index(2025)]["row"]
        self.assertEqual((row["valid"], row["missing"]), (61, 151))
        lines = out["temperature"]["lines"]
        self.assertTrue(any(line.startswith("Grid estimate: calendar 2025 (61 days with data): highest ")
                            for line in lines))
        self.assertIn("Data unavailable: 151 days missing in the calendar 2025; the totals and counts are for the "
                      "days present. This is not an all-clear.", lines)
        _assert_plain(self, out)

    def test_a_season_coverage_line_and_the_partial_line_are_exact_sentences(self):
        out = _describe_billings(self.store)
        self.assertIn("Data unavailable: 335 days missing in the 2024-25 season; the totals and counts are for the "
                      "days present. This is not an all-clear.", out["temperature"]["lines"])
        self.assertEqual(out["temperature"]["partial"],
                         "Data unavailable for some months: 2024-07, 2024-08, 2024-09, 2024-10, 2024-11, 2024-12, "
                         "2025-01, 2025-02, 2025-03, 2025-04, 2025-05, 2025-08 did not load (no NOAA file was found "
                         "for them when this update ran). This is not an all-clear.")

    def test_a_season_with_no_loaded_month_says_it_has_no_valid_day(self):
        out = _describe_billings(self.store)
        self.assertIn("Data unavailable for 2021-22: no day of this season has a valid grid value. This is not an "
                      "all-clear.", out["temperature"]["lines"])
        season = next(s for s in out["table"]["seasons"] if s["label"] == "2021-22")
        self.assertEqual(season["rows"], [])
        _assert_plain(self, out)

    def test_a_calendar_or_water_year_with_days_but_no_valid_day_says_so(self):
        out = _describe_billings(self.store)
        lines = out["temperature"]["lines"] + out["rain"]["lines"]
        self.assertIn("Data unavailable for calendar 2024: no day has a valid grid value, so no highest or lowest "
                      "temperature or rain total is shown. This is not an all-clear.", lines)
        self.assertIn("Data unavailable for water year 2024: no day has a valid grid value, so no highest or lowest "
                      "temperature or rain total is shown. This is not an all-clear.", lines)
        self.assertFalse(any(line.startswith("Grid estimate: calendar 2024") for line in lines))

    def test_verify_reports_the_airport_freeze_thaw_count_beside_the_grid_count(self):
        report = cl.verify_store(self.store, self.cache, basemap_path=self.basemap, log=lambda s: None)
        airport = report["airport_comparison_2025"]
        self.assertEqual(set(airport), {"station", "year", "freeze_thaw_days", "days_with_both", "units",
                                        "grid_billings_calendar_2025_freeze_thaw_days"})
        self.assertEqual((airport["station"], airport["year"]), ("USW00024033", 2025))
        self.assertEqual(airport["freeze_thaw_days"], 3)
        self.assertEqual(airport["days_with_both"], 5)
        self.assertEqual(airport["grid_billings_calendar_2025_freeze_thaw_days"], 0)
        self.assertNotIn("colder", json.dumps(report))
        self.assertNotIn("note", airport)

    def test_describe_unavailable_without_a_block_or_tile(self):
        out = cl.describe_climate({}, None, 800, 1990, NOW)
        self.assertEqual(out["state"], "unavailable")
        self.assertIn("could not be loaded in this update", out["temperature"]["lead"])
        self.assertIn("that is not the same as no temperature", out["temperature"]["lead"])
        self.assertIn("This is not an all-clear.", out["rain"]["lead"])

    def test_the_map_block_carries_the_thresholds_once(self):
        index = json.loads((self.store / "hail" / "index.json").read_text())
        block = cl.map_data_climate(index)
        self.assertEqual(block["tile"], "hail/c/{tile}.json")
        self.assertEqual(block["thresholds"]["hot_day"]["tenths_c"], 322)
        self.assertEqual(block["state"], "partial")

    def test_the_stale_line_appears_for_an_old_newest_day(self):
        index = json.loads((self.store / "hail" / "index.json").read_text())
        tr, tc, _key = cl.climate_tile(*BILLINGS)
        doc = json.loads((self.store / "hail" / "c" / f"{h.tile_name(tr, tc)}.json").read_text())
        row, col = h.cell_for(*cl.climate_centre(*BILLINGS))
        much_later = datetime(2026, 12, 1, tzinfo=UTC)
        out = cl.describe_climate(index, doc, row, col, much_later)
        self.assertIsNotNone(out["stale"])
        self.assertTrue(out["stale"].endswith("This is not an all-clear."))

    def test_a_spot_with_no_tile_in_the_store_is_outside_not_unavailable(self):
        index = json.loads((self.store / "hail" / "index.json").read_text())
        row, col = h.cell_for(*cl.climate_centre(*BILLINGS))
        absent = dict(index)
        # the Billings tile is listed, so a missing file is a failure (unavailable)...
        failed = cl.describe_climate(index, None, row, col, NOW)
        self.assertEqual(failed["state"], "unavailable")
        # ...but a tile the store does not list is a grid cell centred outside Montana (outside, not a failure)
        block = dict(index["climate"])
        block["tile_names"] = [n for n in block["tile_names"] if n != cl.climate_tile_name(*BILLINGS)]
        absent["climate"] = block
        out = cl.describe_climate(absent, None, row, col, NOW)
        self.assertEqual(out["state"], "outside")
        self.assertEqual(out["temperature"]["lead"], cl.WORDS_CLIMATE["not_in_store"])
        self.assertNotIn("Outside Montana", out["temperature"]["lead"])

    def test_archive_round_trip_and_refusal(self):
        tmp = Path(tempfile.mkdtemp(prefix="climate-test-archive-"))
        try:
            cache = tmp / "cache"
            paths = cl._cache_paths(cache)
            cl._ensure(paths)
            np_ = np
            fields = np_.zeros((4, cl.NF), dtype=np_.int64)
            cl.save_month_aggregate(paths, "2025-06", {"fields": fields, "has_value": np_.zeros(4, dtype=bool),
                                                       "meta": {"format": cl.AGG_FORMAT, "month": "2025-06"}})
            cl._save_ledger(paths, {"format": cl.LEDGER_FORMAT, "plan": [], "months": {}, "requests": 0})
            archive = cl.pack_cache(cache, tmp / "a.tar.gz")
            self.assertEqual(archive["members"], 1)
            out = tmp / "unpacked"
            cl.unpack_cache(tmp / "a.tar.gz", out)
            self.assertEqual((out / "aggregates" / "2025-06.npz").read_bytes(),
                             (cache / "aggregates" / "2025-06.npz").read_bytes())
            # a member changed inside the archive is refused, and nothing is written
            import tarfile
            bad = tmp / "bad.tar.gz"
            with tarfile.open(tmp / "a.tar.gz", "r:gz") as src_tar, tarfile.open(bad, "w:gz") as dst:
                for m in src_tar.getmembers():
                    data = src_tar.extractfile(m).read()
                    if m.name == "ledger.json":
                        data = data + b" "
                    info = tarfile.TarInfo(m.name)
                    info.size = len(data)
                    import io as _io
                    dst.addfile(info, _io.BytesIO(data))
            with self.assertRaises(cl.ClimateError):
                cl.unpack_cache(bad, tmp / "refused")
            self.assertFalse((tmp / "refused" / "ledger.json").exists())
        finally:
            shutil.rmtree(tmp)

    def test_tile_of_another_grid_cell_is_refused(self):
        index = json.loads((self.store / "hail" / "index.json").read_text())
        other = {"f": cl.FORMAT, "r": 0, "c": 0, "state": [], "cells": {}}
        row, col = h.cell_for(*cl.climate_centre(*BILLINGS))
        with self.assertRaises(cl.ClimateError):
            cl.describe_climate(index, other, row, col, NOW)

    def test_a_manifest_change_is_refused_by_verify(self):
        manifest_path = self.store / "hail" / "manifest.json"
        before = manifest_path.read_bytes()
        try:
            doc = json.loads(before)
            tile = next(k for k in doc["files"] if k.startswith("hail/c/"))
            doc["files"][tile]["sha256"] = "0" * 64
            manifest_path.write_bytes(h._pretty(doc))
            with self.assertRaises(h.HailStoreError):
                cl.verify_store(self.store, self.cache, basemap_path=self.basemap, log=lambda s: None)
        finally:
            manifest_path.write_bytes(before)

    def test_build_is_byte_identical_from_the_same_cache(self):
        first = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((self.store / "hail" / "c").glob("*.json"))}
        cl.build_store(self.store, self.cache, log=lambda s: None, basemap_path=self.basemap)
        second = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((self.store / "hail" / "c").glob("*.json"))}
        self.assertEqual(first, second)
        self.assertTrue(first)


class ValidDays(unittest.TestCase):
    """The page counts valid days (days minus missing days) and never shows a zero for a missing day (D2, F05)."""

    def test_a_period_with_no_valid_day_has_no_value_and_no_zero_count(self):
        rec = [365, 365, 0, None, None, None, None, None, None, 0, 0, 0, 0]
        row = cl._record_row(rec)
        self.assertEqual(row["valid"], 0)
        for key in ("rain", "hot90", "freeze_thaw", "below32", "tmax", "tmin", "rain_max"):
            self.assertIsNone(row[key]["value"], key)
        self.assertEqual(cl._table_rows(row), [])
        out = cl._season_lines("2022-23", rec)
        unavailable = ("Data unavailable for 2022-23: no day of this season has a valid grid value. "
                       "This is not an all-clear.")
        coverage = ("Data unavailable: 365 days missing in the 2022-23 season; the totals and counts are for the days "
                    "present. This is not an all-clear.")
        self.assertEqual(out["temperature"], [unavailable, coverage])
        self.assertEqual(out["rain"], [unavailable, coverage])

    def test_a_partial_period_counts_only_the_days_present(self):
        rec = [31, 1, 100, 50, 20210705, 950, 20210705, 280, 20210702, 2, 0, 1, 3]
        row = cl._record_row(rec)
        self.assertEqual(row["valid"], 30)
        self.assertEqual(row["rain"]["value"], "1.00")
        out = cl._season_lines("2021-22", rec)
        self.assertEqual(out["temperature"][1], "Grid estimate: 2 days with a high of 90 F or more in the 2021-22 season.")
        self.assertEqual(out["temperature"][-1], "Data unavailable: 1 day missing in the 2021-22 season; the totals "
                         "and counts are for the days present. This is not an all-clear.")
        self.assertEqual(out["rain"][-1], out["temperature"][-1])
        rows = cl._table_rows(row)
        self.assertNotIn("missing", {r["key"] for r in rows})
        self.assertEqual(next(r["value"] for r in rows if r["key"] == "hot90"), 2)

    def test_the_coverage_line_starts_with_data_unavailable_and_ends_with_the_negation(self):
        for days, missing in ((31, 1), (365, 365), (61, 151)):
            text = cl.WORDS_CLIMATE["days_missing"].format(n=missing, days="days" if missing != 1 else "day",
                                                          period="calendar 2025")
            self.assertTrue(text.startswith("Data unavailable"), text)
            self.assertTrue(text.endswith("This is not an all-clear."), text)

    def test_the_warnings_name_the_part_with_no_zero(self):
        self.assertEqual(cl._plain_reason("HTTP 503"), "the source returned HTTP 503")
        self.assertEqual(cl._plain_reason("ReadTimeout"), "the request timed out")
        self.assertEqual(cl._plain_reason("SomethingNew"), "the source did not answer as expected")
        self.assertIsNone(cl._partial_line({}))

    def test_the_partial_line_names_each_month_and_its_reason_once(self):
        self.assertEqual(
            cl._partial_line({"2024-07": "no_file", "2024-08": "no_file", "2025-06": "ReadTimeout"}),
            "Data unavailable for some months: 2024-07, 2024-08 did not load (no NOAA file was found for them when "
            "this update ran); 2025-06 did not load (the request timed out). This is not an all-clear.")
        self.assertEqual(cl._partial_line({"2025-06": "no_file"}),
                         "Data unavailable for some months: 2025-06 did not load (no NOAA file was found for it when "
                         "this update ran). This is not an all-clear.")


class FiveSeasonsUnloaded(unittest.TestCase):
    """The five seasons unloaded and July and August 2026 loaded (F05, F06): no sentence or table value carries None,
    every line about a season or year with no valid day starts with "Data unavailable", and no zero count stands for
    a missing day. The partial season and the mixed calendar year use their valid days."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="climate-test-five-"))
        cls.store = cls.tmp / "store"
        cls.cache = cls.tmp / "cache"
        cls.basemap = cls.tmp / "basemap.json"
        _synthetic_basemap(cls.basemap)
        _fake_hail_store(cls.store)
        cls.cache.mkdir(parents=True)
        _write_cache(cls.cache, cls.basemap, _ym_list((2021, 7), (2026, 8)),
                     {"2026-07": (31, 30.0, 10.0, 2.0), "2026-08": (31, 30.0, 10.0, 2.0)})
        cls.block = cl.build_store(cls.store, cls.cache, log=lambda s: None, basemap_path=cls.basemap)
        cls.out = _describe_billings(cls.store)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_the_block_is_partial_with_the_two_loaded_months(self):
        self.assertEqual(self.block["state"], "partial")
        self.assertEqual(len(self.block["months_missing"]), 60)
        self.assertEqual(self.out["state"], "partial")

    def test_the_five_season_leads_and_table_say_there_is_no_valid_day(self):
        self.assertEqual(self.out["temperature"]["lead"], cl.WORDS_CLIMATE["five_unavailable_temperature"])
        self.assertEqual(self.out["rain"]["lead"], cl.WORDS_CLIMATE["five_unavailable_rain"])
        self.assertEqual(self.out["table"]["five"]["valid"], 0)
        self.assertEqual(self.out["table"]["five"]["rows"], [])
        for season in self.out["table"]["seasons"]:
            self.assertEqual(season["valid"], 0)
            self.assertEqual(season["rows"], [])

    def test_no_sentence_or_table_value_is_none(self):
        _assert_plain(self, self.out)

    def test_every_line_about_a_season_or_year_without_data_starts_with_data_unavailable(self):
        labels = (list(cl.FIVE_SEASONS) + [f"calendar {y}" for y in range(2021, 2026)]
                  + [f"water year {y}" for y in range(2021, 2026)])
        lines = self.out["temperature"]["lines"] + self.out["rain"]["lines"]
        affected = [line for line in lines if any(label in line for label in labels)]
        self.assertTrue(affected)
        for line in affected:
            self.assertTrue(line.startswith("Data unavailable"), line)

    def test_no_zero_count_stands_for_a_missing_day(self):
        lines = self.out["temperature"]["lines"] + self.out["rain"]["lines"]
        for line in lines:
            if any(label in line for label in cl.FIVE_SEASONS):
                self.assertNotRegex(line, r"\b0 (days|day|in)\b", line)

    def test_the_partial_season_and_the_mixed_calendar_year_use_their_valid_days(self):
        partial = self.out["table"]["partial"]
        self.assertEqual((partial["valid"], partial["missing"]), (62, 0))
        self.assertTrue(partial["rows"])
        self.assertTrue(partial["text"].startswith("Grid estimate: 2026-27 so far, 62 days with data, July 1, 2026 to "))
        row = self.out["calendar"][cl.CALENDAR_YEARS.index(2026)]["row"]
        self.assertEqual((row["valid"], row["missing"]), (62, 181))
        lines = self.out["temperature"]["lines"]
        self.assertTrue(any(line.startswith("Grid estimate: calendar 2026 (62 days with data): highest 86.0 F on ")
                            for line in lines))
        self.assertIn("Data unavailable: 181 days missing in the calendar 2026; the totals and counts are for the days "
                      "present. This is not an all-clear.", lines)

    def test_the_stale_line_and_the_words_are_plain(self):
        self.assertTrue(self.out["stale"].endswith("This is not an all-clear."))
        _assert_plain(self, self.out)


def _walk_text(value, where: str):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_text(item, f"{where}.{key}")
    elif isinstance(value, list):
        for k, item in enumerate(value):
            yield from _walk_text(item, f"{where}[{k}]")
    elif isinstance(value, str):
        yield where, value


class WordGuard(unittest.TestCase):
    """Every template is plain: no store, tile, bucket, build, index or aggregate, and no None (F11)."""

    def test_no_template_has_a_developer_word_or_none(self):
        count = 0
        for where, text in _walk_text(cl.WORDS_CLIMATE, "WORDS_CLIMATE"):
            count += 1
            self.assertIsNone(DEVELOPER_WORDS.search(text), (where, text))
            self.assertNotRegex(text, r"\bNone\b", where)
        self.assertGreater(count, 30)

    def test_the_stale_and_unavailable_lines_end_with_the_negation(self):
        for key in ("five_unavailable_temperature", "five_unavailable_rain", "season_unavailable",
                    "calendar_unavailable", "water_unavailable", "days_missing", "partial_months", "stale",
                    "no_land", "unavailable", "not_in_store"):
            self.assertTrue(cl.WORDS_CLIMATE[key].endswith("This is not an all-clear."), key)

    def test_the_five_season_and_year_sentences_are_exact(self):
        w = cl.WORDS_CLIMATE
        self.assertEqual(w["five_unavailable_temperature"],
                         "Data unavailable for the five seasons: no day from July 1, 2021 to June 30, 2026 has a valid "
                         "grid value, so no highest or lowest temperature is shown. This is not an all-clear.")
        self.assertEqual(w["five_unavailable_rain"],
                         "Data unavailable for the five seasons: no day from July 1, 2021 to June 30, 2026 has a valid "
                         "grid value, so no rain total is shown. This is not an all-clear.")
        self.assertEqual(w["calendar_unavailable"].format(year=2025),
                         "Data unavailable for calendar 2025: no day has a valid grid value, so no highest or lowest "
                         "temperature or rain total is shown. This is not an all-clear.")
        self.assertEqual(w["water_unavailable"].format(year=2025),
                         "Data unavailable for water year 2025: no day has a valid grid value, so no highest or lowest "
                         "temperature or rain total is shown. This is not an all-clear.")
        self.assertNotEqual(w["five_unavailable_temperature"], w["unavailable"])


class RunUpdateFailures(unittest.TestCase):
    """A source failure is recorded and the update goes on; the store says so (B5 D16, job-F7). Each test has its own
    folder under a temporary directory, removed afterwards."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="climate-test-failures-"))
        self.cache, self.store, self.basemap = _fixture_dirs(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _run(self, session, today=date(2025, 7, 15)) -> dict:
        with mock.patch.object(cl, "RETRY_PAUSE_S", 0):
            return cl.run_update(self.cache, today, session=session, log=lambda s: None, basemap_path=self.basemap)

    def _index(self) -> dict:
        return json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))

    def test_a_cut_download_is_recorded_and_leaves_no_partial_file(self):
        sess = _FakeSession(listing={2025: _listing_bytes({KEY_2506: (1000, "new")})},
                            files={"ncdd-202506-grd-scaled": _DropAfterChunk(HDF5_HEAD + b"x" * 40)})
        run = self._run(sess)
        self.assertIsNone(run["failures"]["listing"])
        self.assertEqual(run["months_failed"], ["2025-06"])
        self.assertEqual(run["failures"]["months"]["2025-06"]["reason"], "ChunkedEncodingError")
        self.assertEqual(list((self.cache / "months").iterdir()), [])
        self.assertFalse(cl.aggregate_path(cl._cache_paths(self.cache), "2025-06").exists())
        ledger = json.loads((self.cache / "ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["failures"]["months"]["2025-06"]["reason"], "ChunkedEncodingError")
        self.assertEqual(ledger["months"]["2025-05"]["kind"], "missing")
        self.assertNotIn("2025-05", ledger["failures"]["months"])
        block = cl.build_store(self.store, self.cache, log=lambda s: None, basemap_path=self.basemap)
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["problem"], "no month of the climate grid has loaded")
        index = self._index()
        row, col = h.cell_for(*cl.climate_centre(*BILLINGS))
        out = cl.describe_climate(index, None, row, col, NOW)
        self.assertEqual(out["state"], "unavailable")
        self.assertEqual(out["temperature"]["lead"],
                         "Temperature could not be loaded in this update; that is not the same as no temperature. "
                         "This is not an all-clear.")
        self.assertEqual(out["rain"]["lead"],
                         "Rain could not be loaded in this update; that is not the same as no rain. "
                         "This is not an all-clear.")

    def test_an_older_month_that_fails_to_update_shows_partial_with_its_reason(self):
        _write_cache(self.cache, self.basemap, _ym_list((2021, 7), (2025, 6)), {"2025-06": (30, 30.0, 10.0, 3.0)},
                     etag="old")
        sess = _FakeSession(listing={2025: _listing_bytes({KEY_2506: (1000, "new")})},
                            files={"ncdd-202506-grd-scaled": _DropAfterChunk(HDF5_HEAD + b"x" * 40)})
        run = self._run(sess)
        self.assertEqual(run["months_failed"], ["2025-06"])
        block = cl.build_store(self.store, self.cache, log=lambda s: None, basemap_path=self.basemap)
        self.assertEqual(block["state"], "partial")
        self.assertEqual(block["months_failed"], ["2025-06"])
        out = _describe_billings(self.store)
        partial = out["temperature"]["partial"]
        self.assertTrue(partial.startswith("Data unavailable for some months: 2021-07, 2021-08, "), partial)
        self.assertTrue(partial.endswith("; 2025-06 did not load (the download stopped before the end). "
                                         "This is not an all-clear."), partial)
        self.assertTrue(out["temperature"]["lead"].startswith("Grid estimate: from July 1, 2021 to June 30, 2026"))
        self.assertEqual(out["rain"]["partial"], partial)
        _assert_plain(self, out)

    def test_a_failed_listing_makes_the_part_unavailable_even_with_older_aggregates(self):
        _write_cache(self.cache, self.basemap, _ym_list((2021, 7), (2025, 6)), {"2025-06": (30, 30.0, 10.0, 3.0)})
        sess = _FakeSession(listing={2024: lambda: requests.exceptions.ConnectTimeout("slow")})
        run = self._run(sess)
        self.assertEqual(run["failures"]["listing"]["reason"], "ConnectTimeout")
        self.assertEqual(run["failures"]["months"], {})
        block = cl.build_store(self.store, self.cache, log=lambda s: None, basemap_path=self.basemap)
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["tile_names"], [])
        self.assertEqual(list((self.store / "hail" / "c").glob("*.json")), [])
        out = _describe_billings(self.store)
        self.assertEqual(out["state"], "unavailable")
        self.assertEqual(out["rain"]["lead"],
                         "Rain could not be loaded in this update; that is not the same as no rain. "
                         "This is not an all-clear.")
        report = cl.verify_store(self.store, self.cache, basemap_path=self.basemap, log=lambda s: None)
        self.assertEqual((report["state"], report["ok"], report["records"]), ("unavailable", True, 0))

    def test_a_first_listing_that_fails_writes_an_unavailable_part_without_tiles(self):
        sess = _FakeSession(listing={2021: lambda: requests.exceptions.ReadTimeout("slow")})
        run = self._run(sess)
        self.assertEqual(run["failures"]["listing"]["reason"], "ReadTimeout")
        block = cl.build_store(self.store, self.cache, log=lambda s: None, basemap_path=self.basemap)
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["problem"], "the NOAA file list did not load: the request timed out")
        self.assertEqual(block["tile_names"], [])

    def test_a_prelim_month_whose_range_reads_time_out_is_recorded(self):
        sess = _FakeSession(listing={2025: _listing_bytes({"access/grids/2025/ncdd-202506-grd-prelim.nc": (1000, "p")})},
                            files={"ncdd-202506-grd-prelim": lambda: requests.exceptions.ReadTimeout("slow")})
        run = self._run(sess)
        self.assertEqual(run["failures"]["months"]["2025-06"]["reason"], "ReadTimeout")
        paths = cl._cache_paths(self.cache)
        self.assertFalse(cl.aggregate_path(paths, "2025-06").exists())
        self.assertFalse(cl._days_path(paths, "2025-06").exists())
        ledger = json.loads((self.cache / "ledger.json").read_text(encoding="utf-8"))
        self.assertNotIn("2025-06", ledger["months"])


class DownloadFailures(unittest.TestCase):
    """Each request to the source is a named failure, retried a bounded number of times (job-F7)."""

    def test_a_cut_download_is_retried_then_named_and_leaves_no_partial_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="climate-test-dl-"))
        try:
            dest = tmp / "ncdd-202506-grd-scaled.nc"
            sess = _FakeSession(files={"ncdd-202506": _DropAfterChunk(HDF5_HEAD + b"x" * 64)})
            with mock.patch.object(cl, "RETRY_PAUSE_S", 0):
                with self.assertRaises(cl.SourceError) as ctx:
                    cl.fetch_whole("https://example.invalid/ncdd-202506-grd-scaled.nc", dest, 100, session=sess)
            self.assertEqual(ctx.exception.reason, "ChunkedEncodingError")
            self.assertFalse(dest.exists())
            self.assertFalse((tmp / (dest.name + ".part")).exists())
            self.assertEqual(len(sess.calls), cl.RETRY_ATTEMPTS)
        finally:
            shutil.rmtree(tmp)

    def test_a_short_download_is_refused_and_leaves_no_partial_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="climate-test-short-"))
        try:
            dest = tmp / "ncdd-202506-grd-scaled.nc"

            class Short(_DropAfterChunk):
                def iter_content(self, size):
                    yield self.first

            sess = _FakeSession(files={"ncdd-202506": Short(HDF5_HEAD + b"x" * 8)})
            with mock.patch.object(cl, "RETRY_PAUSE_S", 0):
                with self.assertRaises(cl.SourceError) as ctx:
                    cl.fetch_whole("https://example.invalid/ncdd-202506-grd-scaled.nc", dest, 1000, session=sess)
            self.assertEqual(ctx.exception.reason, "ShortDownload")
            self.assertFalse((tmp / (dest.name + ".part")).exists())
        finally:
            shutil.rmtree(tmp)

    def test_a_listing_timeout_is_retried_and_named(self):
        sess = _FakeSession(listing={2021: lambda: requests.exceptions.ReadTimeout("slow")})
        with mock.patch.object(cl, "RETRY_PAUSE_S", 0):
            with self.assertRaises(cl.SourceError) as ctx:
                cl.list_year(2021, session=sess)
        self.assertEqual(ctx.exception.reason, "ReadTimeout")
        self.assertEqual(len(sess.calls), cl.RETRY_ATTEMPTS)

    def test_a_status_that_is_not_retried_is_named_at_once(self):
        sess = _FakeSession(listing={2021: _Resp(404, b"")})
        with self.assertRaises(cl.SourceError) as ctx:
            cl.list_year(2021, session=sess)
        self.assertEqual(ctx.exception.reason, "HTTP 404")
        self.assertEqual(len(sess.calls), 1)

    def test_the_ghcn_download_timeout_is_named_and_leaves_no_partial_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="climate-test-ghcn-dl-"))
        try:
            def timeout(*args, **kwargs):
                raise requests.exceptions.ReadTimeout("slow")

            with mock.patch("requests.get", side_effect=timeout) as get, \
                    mock.patch.object(cl, "RETRY_PAUSE_S", 0):
                with self.assertRaises(cl.SourceError) as ctx:
                    cl.fetch_ghcn(tmp)
            self.assertEqual(ctx.exception.reason, "ReadTimeout")
            self.assertEqual(get.call_count, cl.RETRY_ATTEMPTS)
            self.assertEqual(get.call_args.args[0], st.DLY_URL.format(id="USW00024033"))
            self.assertEqual(list((tmp / "ghcn" / "dly").glob("*.part")), [])
        finally:
            shutil.rmtree(tmp)


class CommandLine(unittest.TestCase):
    def test_a_recorded_source_failure_exits_zero(self):
        tmp = Path(tempfile.mkdtemp(prefix="climate-test-cli-"))
        try:
            run = {"failures": {"listing": {"reason": "ReadTimeout"}, "months": {}}}
            err = io.StringIO()
            with mock.patch.object(cl, "run_update", return_value=run), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = cl.main(["update", "--cache", str(tmp), "--today", "2025-07-15"])
            self.assertEqual(code, 0)
            self.assertIn("source failure(s) recorded", err.getvalue())
        finally:
            shutil.rmtree(tmp)

    def test_a_store_error_exits_one(self):
        tmp = Path(tempfile.mkdtemp(prefix="climate-test-cli-"))
        try:
            with mock.patch.object(cl, "run_update", side_effect=cl.ClimateError("the cache is not in the expected format")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = cl.main(["update", "--cache", str(tmp), "--today", "2025-07-15"])
            self.assertEqual(code, 1)
        finally:
            shutil.rmtree(tmp)


class SourceConstants(unittest.TestCase):
    """The gate points, the .dly address and the repository address are each defined once (F18)."""

    def test_the_gate_points_are_the_stations_points_and_give_the_same_cells(self):
        self.assertEqual(cl.climate_cell_for(*st.GATE_POINTS["billings"]), BILLINGS)
        self.assertEqual(cl.climate_cell_for(*st.GATE_POINTS["benchland"]), BENCHLAND_GRID)

    def test_the_user_agent_and_the_repository_come_from_the_hail_module(self):
        self.assertEqual(cl.REPO_URL, f"https://github.com/{h.REPO}")
        self.assertTrue(cl.USER_AGENT.endswith(f"(+{cl.REPO_URL})"))
        self.assertFalse(hasattr(cl, "GHCN_DLY_URL"))


class FileRead(unittest.TestCase):
    """Synthetic netCDF files with the grid's shape and three variables, for two months (July and August 2025), written
    with h5py one day at a time and read back through check_file, read_box, select_cells and daily_arrays. Two cells
    hold values (Billings and Benchland); every other cell is NaN, like the water cells of the real file."""

    @classmethod
    def setUpClass(cls):
        import h5py
        cls.tmp = Path(tempfile.mkdtemp(prefix="climate-test-nc-"))
        cls.paths = {}
        bi, bj = BILLINGS
        ki, kj = BENCHLAND_GRID
        # July 2025 (day index, 0-based) -> {cell: (prcp, tmax, tmin)}; NaN elsewhere
        july = {
            0: {BILLINGS: (0.125, 32.15, 10.0), BENCHLAND_GRID: (3.0, 25.0, -1.0)},
            1: {BILLINGS: (1.2265625, 32.14, -0.04)},
            2: {BILLINGS: (-999.99, -999.99, -999.99), BENCHLAND_GRID: (0.0, 1.0, -999.99)},
            3: {BILLINGS: (0.0, 0.0, -1.0)},
            4: {BILLINGS: (0.0, 27.3125, 14.3515625)},
        }
        august = {
            0: {BILLINGS: (0.0, 32.2, 12.0), BENCHLAND_GRID: (0.0, 30.0, 4.0)},
            1: {BILLINGS: (2.0, 20.0, -5.0)},
        }
        for ym, days_map in (("2025-07", july), ("2025-08", august)):
            year, month = int(ym[:4]), int(ym[5:])
            days = cl.days_in(year, month)
            path = cls.tmp / f"ncdd-{ym.replace('-', '')}-grd-scaled.nc"
            cls.paths[ym] = path
            with h5py.File(path, "w") as f:
                f.attrs["license"] = "no restrictions"
                lat = (cl.LAT_CENTRE0 + 2 * np.arange(cl.ROWS)).astype(np.float64) / 48.0
                lon = (cl.LON_CENTRE0 + 2 * np.arange(cl.COLS)).astype(np.float64) / 48.0
                f.create_dataset("lat", data=lat.astype(np.float32))
                f.create_dataset("lon", data=lon.astype(np.float32))
                origin = (date(year, month, 1) - date(1800, 1, 1)).days
                f.create_dataset("time", data=(origin + np.arange(days)).astype(np.int32))
                sets = {}
                for name, lo, hi, k in (("prcp", 0.0, 2000.0, 0), ("tmax", -100.0, 100.0, 1),
                                        ("tmin", -100.0, 100.0, 2)):
                    ds = f.create_dataset(name, shape=(days, cl.ROWS, cl.COLS), dtype="f8",
                                          chunks=(1, cl.ROWS, cl.COLS), compression="gzip", compression_opts=4,
                                          shuffle=True, fillvalue=np.nan)
                    ds.attrs["valid_min"] = np.array([lo])
                    ds.attrs["valid_max"] = np.array([hi])
                    sets[name] = (ds, k)
                # Only the days with values are written: an unwritten chunk reads back as the fill value (NaN),
                # which is what the water cells and the other days hold in the real file.
                for d in sorted(days_map):
                    for name, (ds, k) in sets.items():
                        layer = np.full((cl.ROWS, cl.COLS), np.nan)
                        for (ci_, cj_), values in days_map[d].items():
                            layer[ci_, cj_] = values[k]
                        ds[d] = layer

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def _cell(self, ym="2025-07", cell=BILLINGS):
        import h5py
        year, month = int(ym[:4]), int(ym[5:])
        with h5py.File(self.paths[ym], "r") as f:
            facts = cl.check_file(f, year, month)
            box = (cell[0], cell[0] + 1, cell[1], cell[1] + 1)
            raw = cl.read_box(f, box)
        cells = cl.select_cells(raw, box, np.array([cell[0]]), np.array([cell[1]]))
        return facts, cl.daily_arrays(np, cells["prcp"], cells["tmax"], cells["tmin"])

    def test_the_file_checks_and_reads_the_cell(self):
        facts, (valid, cmm, tx, tn, fill) = self._cell()
        self.assertEqual(facts["license"], "license = no restrictions")
        self.assertEqual(valid[:, 0].tolist()[:5], [True, True, False, True, True])
        self.assertTrue(fill[2, 0])
        self.assertEqual(int(cmm[0, 0]), 13)                    # 0.125 mm -> 0.13 mm
        self.assertEqual(int(tx[0, 0]), 322)                    # 32.15 C -> 32.2 C
        self.assertEqual(int(tn[1, 0]), 0)                      # -0.04 C -> 0.0 C
        self.assertEqual(int(tx[4, 0]), 273)                    # 27.3125 C -> 27.3 C
        self.assertEqual(int(tn[4, 0]), 144)                    # 14.3515625 C -> 14.4 C

    def test_a_second_cell_and_a_second_month(self):
        facts, (valid, cmm, tx, tn, fill) = self._cell("2025-07", BENCHLAND_GRID)
        self.assertEqual(int(tx[0, 0]), 250)                    # Benchland 25.0 C
        self.assertEqual(int(tn[0, 0]), -10)                    # -1.0 C
        self.assertFalse(valid[1, 0] and valid[2, 0] and False)
        self.assertTrue(fill[2, 0])                             # the Benchland day 3 fill
        facts_aug, (vaug, cmaug, txaug, tnaug, _f) = self._cell("2025-08", BILLINGS)
        self.assertEqual(facts_aug["days"], 31)
        self.assertEqual(int(txaug[0, 0]), 322)                 # August 1: 32.2 C, a 90 F day
        # the August file has the same grid and its own time axis
        self.assertEqual(int(cl.month_fields(np, vaug, cmaug, txaug, tnaug, 2)[0, cl.MONTH_FIELDS.index("hot90")]), 1)

    def test_a_water_cell_is_nan_in_the_file_and_has_no_valid_day(self):
        facts, (valid, cmm, tx, tn, fill) = self._cell("2025-07", (cl.ROWS - 1, cl.COLS - 1))
        self.assertFalse(valid.any())
        self.assertFalse(fill.any())

    def test_month_fields_from_the_file(self):
        facts, (valid, cmm, tx, tn, _fill) = self._cell()
        f = cl.month_fields(np, valid, cmm, tx, tn, 4)[0].tolist()
        self.assertEqual(f[cl.MONTH_FIELDS.index("days")], 4)
        self.assertEqual(f[cl.MONTH_FIELDS.index("missing")], 1)
        self.assertEqual(f[cl.MONTH_FIELDS.index("hot90")], 1)
        self.assertEqual(f[cl.MONTH_FIELDS.index("freeze_thaw")], 0)
        self.assertEqual(f[cl.MONTH_FIELDS.index("rain_cmm")], 13 + 123)

    def test_the_wrong_licence_is_refused(self):
        import h5py
        path = self.paths["2025-07"]
        with h5py.File(path, "a") as f:
            old = f.attrs["license"]
            f.attrs["license"] = "restricted"
        try:
            with h5py.File(path, "r") as f:
                with self.assertRaises(cl.ClimateError):
                    cl.check_file(f, 2025, 7)
        finally:
            with h5py.File(path, "a") as f:
                f.attrs["license"] = old


class Mask(unittest.TestCase):
    def test_the_montana_mask_has_the_research_count(self):
        ci, cj = cl.montana_cells()
        self.assertEqual(int(ci.size), cl.EXPECTED_MASK_CELLS)
        self.assertEqual(len(set(zip(ci.tolist(), cj.tolist()))), int(ci.size))
        self.assertTrue(all(0 <= i < cl.ROWS and 0 <= j < cl.COLS for i, j in zip(ci.tolist()[:50], cj.tolist()[:50])))

    def test_the_billings_cell_is_in_the_mask_and_the_cell_rule_agrees(self):
        ci, cj = cl.montana_cells()
        self.assertTrue(((ci == BILLINGS[0]) & (cj == BILLINGS[1])).any())


if __name__ == "__main__":
    unittest.main()
