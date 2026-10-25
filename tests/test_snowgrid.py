"""Snow analysis (B5 Source 2): the NOHRSC cell rule (D4), the Montana box, the GeoTIFF reader on a synthetic file, the D7
unit check, the n/ tile writer (integers or null, never zero; negatives null and counted; half up), the failures (a timeout,
a refused answer, an unreadable cached file, a deadline; D16), the file records and the words. Offline: requests are
replaced by fakes, and time.sleep is patched so the retries cost nothing. The real files are checked by
`python -m website.snowgrid verify`."""
from __future__ import annotations

import functools
import json
import re
import sys
import tempfile
import time
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from unittest import mock

import numpy as np
import requests
from PIL import Image
from PIL.TiffImagePlugin import ImageFileDirectory_v2

from website import hail
from website import snowgrid as G
from website import stations as S

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the one forbidden list, D41 and D56)
import words_rules as W  # noqa: E402

FORBIDDEN = re.compile(r"\b(damag\w*|dry|clear\w*|insurance|eligib\w*|confirm\w*|coverage|risk|probab\w*|claim\w*|"
                       r"loss\w*|all-clear|structure|warrant\w*)\b|\bno hail\b", re.IGNORECASE)
LM = "Mon, 05 Oct 2026 14:33:16 GMT"           # the Last-Modified of the 2025-26 file, read live on 2026-10-19
D20_ALL = "Snow analysis could not be loaded in this update; that is not the same as no snow analysis."
D20_2025 = ("Snow analysis for water year 2025 could not be loaded in this update; that is not the same as no snow "
            "analysis for water year 2025.")
NWS_PUBLIC = ("The information on National Weather Service (NWS) Web pages are in the public domain, unless specifically "
              "noted otherwise, and may be used without charge for any lawful purpose so long as you do not: 1) claim it "
              "is your own (e.g., by claiming copyright for NWS information -- see below), 2) use it in a manner that "
              "implies an endorsement or affiliation with NOAA/NWS, or 3) modify its content and then present it as "
              "official government material.")
NWS_403 = ("As required by 17 U.S.C. § 403, third parties producing copyrighted works consisting predominantly of the "
           "material appearing in NWS Web pages must provide notice with such work(s) identifying the NWS material "
           "incorporated and stating that such material is not subject to copyright protection.")
# three station cells (row, col, inches) with grid values equal to their inches, so the D7 slope is 1.0
STATION_CELLS = {"A": (200, 300, 20.0), "B": (202, 305, 30.0), "C": (204, 310, 40.0), "D": (206, 315, 50.0),
                 "E": (208, 320, 60.0)}


def write_tif(path: Path, values: np.ndarray, *, corner=(-126.0, 55.0), scale=0.04) -> None:
    """A synthetic NOHRSC-shaped GeoTIFF: mode F, LZW, tags 33550 (scale) and 33922 (corner) as the real files carry."""
    ifd = ImageFileDirectory_v2()
    ifd[33550] = (scale, scale, 0.0)
    ifd[33922] = (0.0, 0.0, 0.0, corner[0], corner[1], 0.0)
    img = Image.fromarray(values.astype(np.float32), mode="F")
    img.save(path, compression="tiff_lzw", tiffinfo=ifd)


class FakeResponse:
    """The parts of a requests response that the snow download reads."""

    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self._body = body
        self.headers = dict(headers or {})

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        pass


def tif_bytes(values: np.ndarray) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.tif"
        write_tif(path, values)
        return path.read_bytes()


@functools.lru_cache(maxsize=None)
def default_tif() -> bytes:
    return tif_bytes(station_grid())


def station_grid(scale: float = 1.0) -> np.ndarray:
    values = np.zeros((850, 1500), dtype=np.float32)
    for row, col, inches in STATION_CELLS.values():
        values[row, col] = inches * scale
    return values


def station_docs(scale: float = 1.0, only=None) -> dict:
    """Station summaries with complete water-year SNOW values equal to the station's inches (sum in mm)."""
    docs = {}
    for sid, (row, col, inches) in STATION_CELLS.items():
        if only is not None and sid not in only:
            continue
        lat, lon = G.cell_centre(row, col)
        water = {}
        for year in S.WATER_YEARS:
            water[str(year)] = {"start": 0, "end": 0, "n": 365, "partial": False,
                                "SNOW": {"rep": 365, "ok": 365, "sum": round(inches * scale * 25.4)}}
        docs[sid] = {"lat": lat, "lon": lon, "periods": {"water": water}}
    return docs


class SnowTestCase(unittest.TestCase):
    """A store with an index and a manifest, a cache folder, and no network: requests and sleeps are fakes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.store = self.root / "store"
        (self.store / "hail" / "sd").mkdir(parents=True)
        (self.store / "hail" / "index.json").write_text(json.dumps({"as_of": "2026-10-16", "tiles": []}),
                                                        encoding="utf-8")
        (self.store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        # the build tests write only the station cells' tiles (the full box's tile count is in the verification record; the store-write
        # tests cover once); the code path is the same
        small_box = [(row, col) for row, col, _inches in STATION_CELLS.values()]
        self.patches = [mock.patch("time.sleep", lambda seconds: None),
                        mock.patch("requests.get", side_effect=self._unexpected_get),
                        mock.patch("requests.head", side_effect=self._default_head),
                        mock.patch.object(G, "box_cells", lambda: list(small_box))]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def _unexpected_get(url, **kwargs):
        raise AssertionError(f"unexpected request to {url}")

    @staticmethod
    def _default_head(url, **kwargs):
        return FakeResponse(200, headers={"Last-Modified": LM})

    def cache_year(self, year: int, values: np.ndarray | None = None, last_modified: str | None = LM) -> Path:
        folder = self.cache / "nohrsc"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / G.water_year_file(year)
        if values is None:
            path.write_bytes(default_tif())             # encoded once: the station grid, as every water year
        else:
            write_tif(path, values)
        G._write_meta(path, {"url": G.water_year_url(year), "last_modified": last_modified,
                             "bytes": path.stat().st_size, "sha256": ""})
        return path

    def cache_all(self, **kwargs):
        for year in S.WATER_YEARS:
            self.cache_year(year, **kwargs)

    def write_station_docs(self, docs=None):
        for sid, doc in (docs if docs is not None else station_docs()).items():
            (self.store / "hail" / "sd" / f"{sid}.json").write_text(json.dumps(doc), encoding="utf-8")

    def block(self) -> dict:
        return json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["snow"]


class CellTests(unittest.TestCase):
    def test_gate_points_and_the_research_cells(self):
        self.assertEqual(G.cell_for(47.08, -110.02), (198, 399))       # Benchland's point, on the north edge
        self.assertEqual(G.cell_for(*S.GATE_POINTS["billings"]), (230, 437))   # Billings (D80(a): the town point)
        self.assertEqual(G.cell_for(47.075, -110.015), (198, 399))     # Benchland's own cell centre

    def test_the_billings_point_is_the_towns_json_point_everywhere(self):
        """D80(a): one Billings point, towns.json's, in the station gate, the snow grid's sample and its self-check."""
        towns = json.loads(S.TOWNS_FILE.read_text(encoding="utf-8"))
        billings = next(t for t in towns if t["slug"] == "billings")
        point = (billings["lat"], billings["lon"])
        self.assertEqual(point, (45.7833, -108.5007))
        self.assertEqual(S.GATE_POINTS["billings"], point)
        self.assertEqual(G.SAMPLE_POINTS["billings"], point)
        self.assertEqual(G.cell_for(*point), (230, 437))

    def test_edges_go_south_and_east(self):
        self.assertEqual(G.cell_for(47.04, -110.0), (199, 400))        # the south edge of row 198, the east edge of 399
        self.assertEqual(G.cell_for(47.08, -110.04), (198, 399))       # the west edge of column 399 is in column 399

    def test_centre_round_trip_and_grid_bounds(self):
        for row, col in ((0, 0), (198, 399), (849, 1499), (150, 248)):
            self.assertEqual(G.cell_for(*G.cell_centre(row, col)), (row, col))
        self.assertFalse(G.in_grid(850, 0))

    def test_montana_box_is_the_half_open_slice(self):
        cells = G.box_cells()
        self.assertEqual(len(cells), 34916)
        self.assertEqual((min(r for r, _ in cells), max(r for r, _ in cells)), (150, 265))
        self.assertEqual((min(c for _, c in cells), max(c for _, c in cells)), (248, 548))

    def test_snow_tile_is_the_hail_tile_of_the_centre(self):
        lat, lon = G.cell_centre(198, 399)
        hrow, hcol = hail.cell_for(lat, lon)
        self.assertEqual(G.snow_tile(198, 399), (hrow // 10, hcol // 10))
        self.assertEqual(G.tile_name_for(198, 399), hail.tile_name(hrow // 10, hcol // 10))


class GridReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_mode_f_and_no_data_as_nan(self):
        values = np.full((850, 1500), 12.5, dtype=np.float32)
        values[0, 0] = -99999.0
        values[1, 1] = 3.0
        path = self.dir / "s.tif"
        write_tif(path, values)
        grid = G.read_grid(path)
        self.assertTrue(np.isnan(grid[0, 0]))
        self.assertAlmostEqual(float(grid[1, 1]), 3.0, places=5)
        self.assertAlmostEqual(float(grid[5, 5]), 12.5, places=5)

    def test_reads_downloaded_bytes_the_same_way(self):
        values = np.full((850, 1500), 7.0, dtype=np.float32)
        grid = G.read_grid(tif_bytes(values), name="download")
        self.assertAlmostEqual(float(grid[10, 10]), 7.0, places=5)

    def test_refuses_another_corner(self):
        values = np.zeros((850, 1500), dtype=np.float32)
        path = self.dir / "bad.tif"
        write_tif(path, values, corner=(-125.0, 55.0))
        with self.assertRaises(G.SnowError):
            G.read_grid(path)

    def test_refuses_another_size(self):
        path = self.dir / "small.tif"
        write_tif(path, np.zeros((10, 10), dtype=np.float32))
        with self.assertRaises(G.SnowError):
            G.read_grid(path)

    def test_a_damaged_body_is_a_snow_error_not_another_exception(self):
        # F3: any file that cannot be decoded is a SnowError (the caller leaves the water year out)
        with self.assertRaises(G.SnowError):
            G.read_grid(b"<html>not a grid</html>", name="page")
        with self.assertRaises(G.SnowError):
            G.read_grid(self.dir / "missing.tif")

    def test_water_year_file_names(self):
        self.assertEqual(G.water_year_file(2026), "sfav2_CONUS_2025093012_to_2026093012.tif")
        self.assertEqual(G.water_year_url(2022),
                         "https://www.nohrsc.noaa.gov/snowfall/data/202209/sfav2_CONUS_2021093012_to_2022093012.tif")


class UnitCheckTests(unittest.TestCase):
    def test_regression_recovers_a_known_slope(self):
        fit = G.regress([(x, 1.0 * x + 0.5) for x in (10.0, 20.0, 30.0, 40.0)])
        self.assertAlmostEqual(fit["slope"], 1.0, places=9)
        self.assertAlmostEqual(fit["intercept"], 0.5, places=9)
        self.assertLess(fit["rms"], 1e-9)
        self.assertEqual(fit["n"], 4)

    def test_centimetre_values_fail_the_check(self):
        # station inches against a grid in centimetres: the slope is near 0.39 and the product stays out
        pairs = [(x, x * 0.3937 + 0.1) for x in (20.0, 35.0, 50.0, 70.0)]
        fit = G.regress(pairs)
        self.assertLess(fit["slope"], 0.85)
        self.assertFalse(G.unit_check(fit["slope"])["pass"])

    def test_bounds_of_the_check(self):
        self.assertTrue(G.unit_check(0.85)["pass"])
        self.assertTrue(G.unit_check(1.15)["pass"])
        self.assertFalse(G.unit_check(0.849)["pass"])
        self.assertFalse(G.unit_check(1.151)["pass"])
        self.assertEqual(G.unit_check(1.0)["unit"], "inches")

    def test_too_few_pairs_refuses(self):
        with self.assertRaises(G.SnowError):
            G.regress([(1.0, 1.0), (2.0, 2.0)])

    def test_pairs_need_95_percent_of_days(self):
        def doc(ok, n, lat=47.08, lon=-110.02):
            return {"lat": lat, "lon": lon, "periods": {"water": {"2025": {"n": n, "SNOW": {"ok": ok, "sum": 2540}}}}}
        grids = {2025: np.full((850, 1500), 40.0)}
        docs = {"A": doc(361, 365), "B": doc(360, 365)}           # 98.9 and 98.6 percent: both complete
        rows, left = G.station_pairs(docs, grids)
        self.assertEqual(len(rows), 2)
        docs = {"C": doc(346, 365)}                                # 94.8 percent: not a complete season
        rows, left = G.station_pairs(docs, grids)
        self.assertEqual(rows, [])
        self.assertEqual(left["incomplete"], 1)

    def test_a_negative_grid_value_is_no_value_for_the_pair(self):
        grids = {2025: np.full((850, 1500), -2.0)}
        docs = {"A": {"lat": 47.08, "lon": -110.02, "periods": {"water": {"2025": {"n": 365, "SNOW": {"ok": 365,
                                                                                                    "sum": 2540}}}}}}
        rows, left = G.station_pairs(docs, grids)
        self.assertEqual(rows, [])
        self.assertEqual(left["no_grid_value"], 1)

    def test_a_season_whose_every_snow_value_is_flagged_is_incomplete(self):
        grids = {2025: np.full((850, 1500), 40.0)}
        docs = {"A": {"lat": 47.08, "lon": -110.02, "periods": {"water": {"2025": {"n": 365, "SNOW": {"rep": 365,
                                                                                                    "ok": 0}}}}}}
        rows, left = G.station_pairs(docs, grids)
        self.assertEqual(rows, [])
        self.assertEqual(left["incomplete"], 1)                  # counted as left out, as before, never a zero pair

    def test_a_season_with_no_snow_record_is_skipped_not_read_as_zero(self):
        grids = {2025: np.full((850, 1500), 40.0)}
        docs = {"A": {"lat": 47.08, "lon": -110.02, "periods": {"water": {"2025": {"n": 365, "SNOW": {"rep": 0}}}}}}
        rows, left = G.station_pairs(docs, grids)
        self.assertEqual(rows, [])
        self.assertEqual(left["incomplete"], 0)


class StoreWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        (self.store / "hail").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_value_that_rounds_to_zero_is_zero_and_a_rounded_negative_is_null_and_counted(self):
        grids = {year: np.full((850, 1500), np.nan) for year in G.WATER_YEARS}
        grids[2023][198, 399] = -0.004              # rounds to 0 hundredths: zero, not null and not counted
        grids[2024][198, 399] = -0.006              # rounds to -1 hundredth: no value, and counted for 2024
        with mock.patch.object(G, "box_cells", lambda: [(198, 399)]):
            _cells, _files, _total, negatives = G._write_n(self.store, grids, {})
        doc = json.loads((self.store / "hail" / "n" / f"{G.tile_name_for(198, 399)}.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["cells"]["198:399"], [None, 0, None, None, None])
        self.assertEqual(negatives, {"2022": 0, "2023": 0, "2024": 1, "2025": 0, "2026": 0})

    def test_values_are_hundredths_null_is_null_never_zero(self):
        grids = {year: np.full((850, 1500), np.nan) for year in G.WATER_YEARS}
        grids[2026][G.cell_for(47.08, -110.02)] = 33.85
        grids[2025][198, 399] = np.nan
        cells, files, total, negatives = G._write_n(self.store, grids, {})
        name = G.tile_name_for(198, 399)
        doc = json.loads((self.store / "hail" / "n" / f"{name}.json").read_text(encoding="utf-8"))
        vals = doc["cells"]["198:399"]
        self.assertEqual(vals, [None, None, None, None, 3385])
        self.assertTrue(all(isinstance(v, int) or v is None for v in vals))
        self.assertEqual(doc["u"], "hundredths of an inch")
        self.assertEqual(cells, 34916)                  # every box cell has an entry; the missing ones are null
        self.assertTrue(f"hail/n/{name}.json" in files)
        self.assertGreater(total, 0)
        self.assertEqual(negatives, {str(y): 0 for y in G.WATER_YEARS})

    def test_every_box_cell_is_written_once(self):
        grids = {year: np.zeros((850, 1500)) for year in G.WATER_YEARS}
        cells, files, total, _negatives = G._write_n(self.store, grids, {})
        self.assertEqual(cells, 34916)
        seen = 0
        for rel in files:
            seen += len(json.loads((self.store / rel).read_text(encoding="utf-8"))["cells"])
        self.assertEqual(seen, 34916)

    def test_a_negative_value_is_null_and_counted_per_water_year(self):
        # no snowfall is below zero; the value is no value (null), counted for the block, never zero
        grids = {year: np.full((850, 1500), np.nan) for year in G.WATER_YEARS}
        grids[2024][198, 399] = -0.5
        grids[2026][198, 399] = -0.01
        _cells, _files, _total, negatives = G._write_n(self.store, grids, {})
        self.assertEqual(negatives["2024"], 1)
        self.assertEqual(negatives["2026"], 1)
        self.assertEqual(negatives["2022"], 0)
        doc = json.loads((self.store / "hail" / "n" / f"{G.tile_name_for(198, 399)}.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["cells"]["198:399"], [None, None, None, None, None])

    def test_half_up_rounding_and_the_tie_case(self):
        # rounding is half up (floor of value x 100 + 0.5); Python's round() would give 6862 for 68.625
        self.assertEqual(G.hundredths_half_up(68.625), 6863)
        self.assertEqual(round(68.625 * 100), 6862)
        self.assertEqual(G.hundredths_half_up(33.85), 3385)
        self.assertEqual(G.hundredths_half_up(0.0), 0)
        self.assertEqual(G.hundredths_half_up(12.0049), 1200)
        self.assertEqual(G.hundredths_half_up(12.125), 1213)               # a tie in binary: half up, not to even
        self.assertEqual(round(12.125 * 100), 1212)
        grids = {year: np.full((850, 1500), np.nan) for year in G.WATER_YEARS}
        grids[2023][198, 399] = 68.625
        G._write_n(self.store, grids, {})
        doc = json.loads((self.store / "hail" / "n" / f"{G.tile_name_for(198, 399)}.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["cells"]["198:399"][1], 6863)

    def test_half_up_matches_decimal_on_exact_binary_ties(self):
        # eighths are exact in binary, so the scaled value is exact: every second value is a tie that must round up
        for j in range(0, 4000):
            value = j / 8
            want = int((Decimal(j) * Decimal("12.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            self.assertEqual(G.hundredths_half_up(value), want, f"{value}")


class UnavailableTests(SnowTestCase):
    """Gate B5-14 and D16: a failed water year or a missing part is named, with the B2 D20 sentence; the rest builds."""

    def test_no_files_and_offline_marks_the_block_unavailable(self):
        result = G.build(self.store, self.root / "empty-cache", offline=True)
        self.assertEqual(result["state"], "unavailable")
        block = self.block()
        self.assertEqual(block["state"], "unavailable")
        self.assertFalse(block["shown"])
        self.assertEqual(block["problem"], D20_ALL)
        self.assertIsNone(FORBIDDEN.search(block["problem"]))
        self.assertFalse((self.store / "hail" / "n").exists())

    def test_one_read_timeout_is_partial_with_the_year_named_and_no_exception(self):
        for year in (2022, 2023, 2024, 2026):
            self.cache_year(year)
        self.write_station_docs()
        calls = []

        def get(url, **kwargs):
            calls.append(url)
            if url == G.water_year_url(2025):
                raise requests.exceptions.ReadTimeout("read timed out")
            raise AssertionError(f"unexpected request to {url}")
        with mock.patch("requests.get", side_effect=get):
            result = G.build(self.store, self.cache)
        self.assertEqual(result["state"], "partial")
        block = self.block()
        self.assertEqual(block["state"], "partial")
        self.assertEqual(block["missing_water_years"], [2025])
        self.assertEqual(block["problem"], D20_2025)
        self.assertTrue(block["shown"])
        self.assertEqual(calls.count(G.water_year_url(2025)), G.ATTEMPTS)     # tried, then named as missing
        self.assertIn("ReadTimeout", block["water_year_files"]["2025"]["reason"])

    def test_a_file_that_cannot_be_kept_is_a_note_and_the_year_still_loads(self):
        for year in (2022, 2023, 2024, 2026):
            self.cache_year(year)
        self.write_station_docs()
        real_write = S._write_atomic

        def refuse_tif(path, data):
            if path.name.startswith("sfav2_"):           # the water-year file and its record cannot be written
                raise OSError("disk full")
            return real_write(path, data)

        with mock.patch("requests.get", return_value=FakeResponse(200, default_tif(), headers={"Last-Modified": LM})), \
                mock.patch.object(S, "_write_atomic", side_effect=refuse_tif):
            result = G.build(self.store, self.cache)
        block = self.block()
        self.assertEqual(result["state"], "loaded")
        self.assertEqual(block["missing_water_years"], [])
        self.assertEqual(block["water_year_files"]["2025"]["source"], "fetched")
        self.assertIn("could not be kept in the cache (OSError)", block["water_year_files"]["2025"]["note"])

    def test_all_five_connection_errors_are_unavailable_with_the_d20_sentence(self):
        self.write_station_docs()
        with mock.patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            result = G.build(self.store, self.cache)
        self.assertEqual(result["state"], "unavailable")
        block = self.block()
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["missing_water_years"], list(G.WATER_YEARS))
        self.assertEqual(block["problem"], D20_ALL)
        self.assertFalse(block["shown"])

    def test_a_corrupt_200_body_is_partial_and_no_exception(self):
        for year in (2022, 2023, 2024, 2026):
            self.cache_year(year)
        self.write_station_docs()

        def get(url, **kwargs):
            if url == G.water_year_url(2025):
                return FakeResponse(200, b"<html>an error page</html>")
            raise AssertionError(url)
        with mock.patch("requests.get", side_effect=get):
            G.build(self.store, self.cache)
        block = self.block()
        self.assertEqual(block["state"], "partial")
        self.assertEqual(block["missing_water_years"], [2025])
        self.assertIn("cannot be read", block["water_year_files"]["2025"]["reason"])

    def test_an_unreadable_cached_file_is_removed_and_requested_once_then_used(self):
        self.cache_all()
        bad = self.cache / "nohrsc" / G.water_year_file(2025)
        bad.write_bytes(b"not a tif at all")
        self.write_station_docs()
        fresh = tif_bytes(station_grid())
        calls = []

        def get(url, **kwargs):
            calls.append(url)
            if url == G.water_year_url(2025):
                return FakeResponse(200, fresh)
            raise AssertionError(url)
        with mock.patch("requests.get", side_effect=get):
            G.build(self.store, self.cache)
        block = self.block()
        self.assertEqual(block["state"], "loaded")
        self.assertEqual(block["missing_water_years"], [])
        self.assertEqual(calls.count(G.water_year_url(2025)), 1)              # requested once
        self.assertEqual(block["water_year_files"]["2025"]["source"], "fetched")
        self.assertIn("cache_problem", block["water_year_files"]["2025"])

    def test_an_unreadable_cached_file_that_cannot_be_refetched_leaves_the_year_out(self):
        self.cache_all()
        (self.cache / "nohrsc" / G.water_year_file(2025)).write_bytes(b"garbage")
        self.write_station_docs()
        with mock.patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            G.build(self.store, self.cache)
        block = self.block()
        self.assertEqual(block["state"], "partial")
        self.assertEqual(block["missing_water_years"], [2025])
        self.assertFalse((self.cache / "nohrsc" / G.water_year_file(2025)).exists())

    def test_offline_an_unreadable_cached_file_is_reported_and_kept(self):
        self.cache_all()
        bad = self.cache / "nohrsc" / G.water_year_file(2025)
        bad.write_bytes(b"garbage")
        self.write_station_docs()
        G.build(self.store, self.cache, offline=True)
        block = self.block()
        self.assertEqual(block["state"], "partial")
        self.assertEqual(block["missing_water_years"], [2025])
        self.assertTrue(bad.exists())                                          # an offline build changes nothing
        self.assertIn("cache_problem", block["water_year_files"]["2025"])

    def test_a_deadline_that_has_passed_makes_no_request_and_names_the_source(self):
        for year in (2022, 2023, 2024, 2026):
            self.cache_year(year)
        self.write_station_docs()
        calls = []
        with mock.patch("requests.get", side_effect=lambda url, **kw: calls.append(url) or FakeResponse(200, b"")):
            G.build(self.store, self.cache, deadline_at=time.monotonic() - 1)
        self.assertEqual(calls, [])
        block = self.block()
        self.assertEqual(block["missing_water_years"], [2025])
        self.assertEqual(block["water_year_files"]["2025"]["reason"], S.REASON_NO_ANSWER)
        self.assertEqual(block["problem"], D20_2025)

    def test_a_changed_last_modified_is_requested_again_and_an_unchanged_one_is_not(self):
        self.cache_all(last_modified="Wed, 01 Oct 2025 00:00:00 GMT")          # the cached copy's own date (older)
        self.write_station_docs()
        fresh = tif_bytes(station_grid())
        calls = []

        def get(url, **kwargs):
            calls.append(url)
            return FakeResponse(200, fresh, headers={"Last-Modified": LM})
        with mock.patch("requests.get", side_effect=get):
            G.build(self.store, self.cache)
        self.assertEqual(calls, [G.water_year_url(2026)])                       # only the 2025-26 file, once
        block = self.block()
        self.assertEqual(block["water_year_files"]["2026"]["revision_check"]["status"], "changed: requested again")
        self.assertEqual(json.loads((self.cache / "nohrsc" / (G.water_year_file(2026) + ".meta.json"))
                                    .read_text(encoding="utf-8"))["last_modified"], LM)
        # the same date next run: no request for that file
        calls.clear()
        with mock.patch("requests.get", side_effect=get):
            G.build(self.store, self.cache)
        self.assertEqual(calls, [])

    def test_a_failed_request_for_a_changed_file_keeps_the_cached_copy(self):
        self.cache_all(last_modified="Wed, 01 Oct 2025 00:00:00 GMT")
        self.write_station_docs()
        with mock.patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            G.build(self.store, self.cache)
        block = self.block()
        self.assertEqual(block["state"], "loaded")                             # the cached copy is still a copy
        self.assertEqual(block["water_year_files"]["2026"]["source"], "cache")
        self.assertIn("served the cached copy", block["water_year_files"]["2026"]["reason"])


class FileDateTests(SnowTestCase):
    """Every water-year file read records its Last-Modified, bytes and SHA-256; a file cached before dates were
    kept gets one HEAD request on the run that finds it, and is not downloaded again."""

    def test_a_cached_file_without_a_date_gets_one_head_and_is_not_downloaded(self):
        self.cache_all()
        for year in (2022, 2023):
            (self.cache / "nohrsc" / (G.water_year_file(year) + ".meta.json")).unlink()
        self.write_station_docs()
        heads, gets = [], []
        dates = {G.water_year_url(2022): "Wed, 05 Oct 2022 14:11:48 GMT",
                 G.water_year_url(2023): "Wed, 05 Oct 2023 14:02:10 GMT"}

        def head(url, **kwargs):
            heads.append(url)
            return FakeResponse(200, headers={"Last-Modified": dates.get(url, LM)})

        def get(url, **kwargs):
            gets.append(url)
            return FakeResponse(404)
        with mock.patch("requests.head", side_effect=head), mock.patch("requests.get", side_effect=get):
            G.build(self.store, self.cache)
        self.assertEqual(sorted(heads), sorted([G.water_year_url(2022), G.water_year_url(2023), G.water_year_url(2026)]))
        self.assertEqual(gets, [])                                            # no download for the dated files
        block = self.block()
        self.assertEqual(block["water_year_files"]["2022"]["last_modified"], dates[G.water_year_url(2022)])
        self.assertEqual(block["water_year_files"]["2023"]["last_modified"], dates[G.water_year_url(2023)])
        self.assertEqual(block["state"], "loaded")
        meta = json.loads((self.cache / "nohrsc" / (G.water_year_file(2022) + ".meta.json")).read_text(encoding="utf-8"))
        self.assertEqual(meta["last_modified"], dates[G.water_year_url(2022)])


class LoadedBlockTests(SnowTestCase):
    """The shown product: the check passes on the synthetic stations, the block carries the urls, the terms and the file
    records, and the n files hold the rule's values."""

    def test_a_loaded_block_has_urls_terms_and_file_records(self):
        self.cache_all()
        self.write_station_docs()
        result = G.build(self.store, self.cache)
        self.assertEqual(result["state"], "loaded")
        self.assertTrue(result["shown"])
        block = self.block()
        self.assertEqual(sorted(block["urls"]), sorted(str(y) for y in G.WATER_YEARS))
        for year in G.WATER_YEARS:
            url = block["urls"][str(year)]
            self.assertEqual(url, G.water_year_url(year))
            self.assertNotIn("{", url)
            self.assertNotIn("<", url)
        self.assertIn(G.PUBLIC_DOMAIN_TEXT, block["terms"])
        self.assertIn(G.SECTION_403_TEXT, block["terms"])
        record = block["water_year_files"]["2026"]
        self.assertEqual(record["last_modified"], LM)
        self.assertEqual(record["bytes"], (self.cache / "nohrsc" / G.water_year_file(2026)).stat().st_size)
        self.assertEqual(len(record["sha256"]), 64)
        self.assertEqual(block["revisions"], G.REVISIONS_NOTE)
        self.assertEqual(block["negative_cells"], {str(y): 0 for y in G.WATER_YEARS})
        self.assertEqual(block["check"]["pass"], True)
        self.assertEqual(block["cells"], len(STATION_CELLS))
        self.assertEqual(set(block["water_year_files"]), {str(y) for y in G.WATER_YEARS})
        self.assertEqual(block["check"]["slope"], 1.0)
        self.assertTrue((self.store / "hail" / "n").is_dir())

    def test_the_unit_check_failing_keeps_the_product_out_with_the_d7_sentence(self):
        # station inches are 0.39 of the grid value: the slope is near 0.39, so the analysis is not shown
        self.cache_year(2026, station_grid(scale=1.0))
        for year in (2022, 2023, 2024, 2025):
            self.cache_year(year, station_grid(scale=1.0))
        docs = station_docs(scale=0.3937)
        self.write_station_docs(docs)
        G.build(self.store, self.cache)
        block = self.block()
        self.assertEqual(block["state"], "unavailable")
        self.assertFalse(block["shown"])
        self.assertEqual(block["problem"], G.WORDS["unit_failed"])
        self.assertFalse((self.store / "hail" / "n").exists())

    def test_too_few_station_seasons_says_the_units_could_not_be_checked(self):
        # every station season is incomplete (100 of 365 days), so no pair is left: the check cannot run
        self.cache_all()
        docs = station_docs()
        for doc in docs.values():
            for rec in doc["periods"]["water"].values():
                rec["SNOW"]["ok"] = 100
        self.write_station_docs(docs)
        G.build(self.store, self.cache)
        block = self.block()
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["problem"], G.WORDS["unit_unchecked"])
        self.assertIn("fewer than three", block["detail"])

    def test_no_station_files_is_unavailable_with_the_d20_sentence(self):
        self.cache_all()
        result = G.build(self.store, self.cache)
        self.assertEqual(result["state"], "unavailable")
        block = self.block()
        self.assertEqual(block["problem"], D20_ALL)
        self.assertIn("station files", block["detail"])


class UrlAndWordsTests(unittest.TestCase):
    def test_the_block_has_one_url_per_water_year_and_no_template(self):
        # one concrete file per water year, not the template with its placeholders
        urls = {str(y): G.water_year_url(y) for y in G.WATER_YEARS}
        self.assertEqual(sorted(urls), ["2022", "2023", "2024", "2025", "2026"])
        self.assertEqual(urls["2026"], "https://www.nohrsc.noaa.gov/snowfall/data/202609/"
                                       "sfav2_CONUS_2025093012_to_2026093012.tif")
        for value in urls.values():
            self.assertNotIn("{", value)
            self.assertNotIn("<", value)

    def test_no_forbidden_term_in_any_snow_word(self):
        # D41 and D56: the one list in words_rules. Its residue rule removes what D13 allows before the forbidden check,
        # and nothing else: quoted wording (curly or straight quotation marks), the NWS damage threat tag label, the
        # required "This is not an all-clear." (the end of every unavailable, partial and held line), the allowed "not
        # the same as no hail", and the proper name "USA Structures" (words_rules.EXEMPT)
        for key, text in G.WORDS.items():
            if isinstance(text, str):
                W.assert_clean(self, text, key)

    def test_analysis_words_are_the_brief_words(self):
        text = G.WORDS["analysis"].format(inches=S.fmt_in(3385), water_year="2025-26 (October 2025 to September 2026)",
                                           miles="2.1")
        self.assertEqual(text, "Analysis: 33.9 in of snow in the 2025-26 (October 2025 to September 2026) water year, "
                               "from the analysis cell about 2.1 miles away. An analysis, not a measurement at this "
                               "address.")

    def test_the_unit_sentence_is_the_plain_sentence_with_no_regression_word(self):
        # the reader is not asked to decode a regression slope
        # D41: the line ends with the required sentence, which the forbidden scan allows (words_rules.residue)
        self.assertEqual(G.WORDS["unit_failed"], "Analysis: not shown. Its amounts did not match measured snowfall "
                                                 "closely enough to be sure they are in inches. Station readings are "
                                                 "shown instead. This is not an all-clear.")
        self.assertEqual(W.residue(G.WORDS["unit_failed"]).split(), "Analysis: not shown. Its amounts did not match measured "
                                                                    "snowfall closely enough to be sure they are in inches. "
                                                                    "Station readings are shown instead.".split())
        self.assertNotIn("slope", G.WORDS["unit_failed"].lower())
        self.assertNotIn("regression", G.WORDS["unit_unchecked"].lower())

    def test_the_unavailable_sentence_is_the_d20_sentence(self):
        self.assertEqual(G.WORDS["unavailable"].format(Part="Snow analysis", one="snow analysis"), D20_ALL)
        self.assertEqual(G.WORDS["unavailable"].format(Part="Snow analysis for water year 2025",
                                                       one="snow analysis for water year 2025"), D20_2025)

    def test_the_nws_conditions_are_stated_in_plain_words_outside_the_quotes(self):
        plain = re.sub(r'"[^"]*"', " ", G.TERMS_NOTE)
        for phrase in ("not presented as", "not used to imply an endorsement by NOAA or the NWS",
                       "not changed and then presented as official government material",
                       "not subject to copyright protection", "17 U.S.C. 403"):
            self.assertIn(phrase, plain)

    def test_no_snow_word_or_term_says_store(self):
        texts = [t for t in G.WORDS.values() if isinstance(t, str)] + [G.TERMS_NOTE, G.REVISIONS_NOTE, G.NOT_IN_STORE]
        for text in texts:
            self.assertNotRegex(text, r"\bstore\b")

    def test_the_terms_are_the_nws_text_quoted_and_outside_the_word_scan(self):
        # the verbatim public-domain paragraph and the 17 U.S.C. 403 sentence, inside quotation marks
        self.assertEqual(G.PUBLIC_DOMAIN_TEXT, NWS_PUBLIC)
        self.assertEqual(G.SECTION_403_TEXT, NWS_403)
        self.assertIn(f'"{NWS_PUBLIC}"', G.TERMS_NOTE)
        self.assertIn(f'"{NWS_403}"', G.TERMS_NOTE)
        self.assertIsNone(FORBIDDEN.search(re.sub(r'"[^"]*"', " ", G.TERMS_NOTE)))   # the quoted wording is exempt

    def test_one_decimal_inches_round_half_up(self):
        self.assertEqual(S.fmt_in(5029), "50.3")
        self.assertEqual(S.fmt_in(3385), "33.9")
        self.assertEqual(S.fmt_in(0), "0.0")
        self.assertEqual(S.mm_to_hundredths_in(1633), 6429)


if __name__ == "__main__":
    unittest.main()
