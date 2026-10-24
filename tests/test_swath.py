"""The hail swath layers (website/swath.py; B4 of the hail history): the header checks, the picture window and its
palette, the floor and the codes, the live per-tile files, the freshness states, the unavailable reasons, the cache,
the words and the forbidden-term check, and the sample frames.

Offline, and no pygrib needed. The GRIB message is a stand-in with the keys the decode reads (FakeMessage: a dict of
header keys and a values object that supports slicing, as pygrib's full grid does). The bucket is a fake that answers
the listings and the files. Where a file would be decoded, the collect tests patch swath.decode_bytes with a fake that
returns a synthetic picture of the same shape (a Decoded over the picture window).
"""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import gridded as g  # noqa: E402
from website import hail as hs  # noqa: E402
from website import sample as sample_data  # noqa: E402
from website import swath as sw  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))   # words_rules is the one forbidden list (D81(c))
import words_rules as W  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
VALID = datetime(2026, 10, 19, 1, 58, tzinfo=UTC)          # the hour file's valid time (the end of its window)
DAY_VALID = datetime(2026, 10, 19, 1, 30, tzinfo=UTC)      # the day file's valid time
HOUR, DAY = sw.PRODUCTS[0], sw.PRODUCTS[1]
TOWNS = json.loads((ROOT / "website" / "towns.json").read_text(encoding="utf-8"))
MT_VALID_TEXT = "Oct 18, 7:58 pm MDT"                       # 01:58 UTC in Montana time (daylight time)
ALL_CLEAR = "This is not an all-clear."


class FakeValues:
    """Stands in for pygrib's full grid (3,500 by 7,000): slicing returns the cells that are set, -1 elsewhere."""
    shape = (sw.NJ, sw.NI)

    def __init__(self, cells: dict, default: float = -1.0):
        self.cells, self.default = cells, default

    def __getitem__(self, key):
        rs, cs = key
        r0, r1, c0, c1 = rs.start, rs.stop, cs.start, cs.stop
        out = np.full((r1 - r0, c1 - c0), self.default, dtype=np.float64)
        for (r, c), v in self.cells.items():
            if r0 <= r < r1 and c0 <= c < c1:
                out[r - r0, c - c0] = v
        return out


class FakeMessage:
    """Stands in for a pygrib message: the header keys the decode reads, the values, and a KeyError for a missing key.
    The defaults are the header of the live 60-minute file checked on 2026-10-19 (its name and units read 'unknown')."""

    def __init__(self, values=None, **overrides):
        self.keys = {"discipline": 209, "parameterCategory": 3, "parameterNumber": 30, "gridType": "regular_ll",
                     "Ni": 7000, "Nj": 3500, "latitudeOfFirstGridPointInDegrees": 54.995,
                     "longitudeOfFirstGridPointInDegrees": 230.005, "latitudeOfLastGridPointInDegrees": 20.005001,
                     "longitudeOfLastGridPointInDegrees": 299.994998, "iDirectionIncrementInDegrees": 0.01,
                     "jDirectionIncrementInDegrees": 0.01, "jScansPositively": 0, "iScansNegatively": 0,
                     "dataDate": 20261019, "dataTime": 158, "centre": "161", "units": "unknown", "name": "unknown"}
        self.keys.update(overrides)
        self._values = values if values is not None else FakeValues({})

    def __getitem__(self, name):
        if name not in self.keys:
            raise KeyError(name)
        return self.keys[name]

    @property
    def values(self):
        return self._values


class BrokenMessage(FakeMessage):
    """A message whose values cannot be read (pygrib failing to decode the grid)."""

    @property
    def values(self):
        raise RuntimeError("boom")


def synthetic(product=HOUR, valid=VALID, cells=None, default: float = -1.0) -> sw.Decoded:
    """A Decoded over the picture window from {(grid row, grid column): value in mm, -1 or -3}, packed as a live file is."""
    win = sw.picture_window()
    raw = np.full((win.r1 - win.r0 + 1, win.c1 - win.c0 + 1), default, dtype=np.float64)
    for (r, c), v in (cells or {}).items():
        if win.r0 <= r <= win.r1 and win.c0 <= c <= win.c1:      # a cell outside the picture is not read
            raw[r - win.r0, c - win.c0] = v
    tenths, packed = hs.pack_tenths(raw)
    return sw.Decoded(valid, {"synthetic": True}, tenths.astype(np.int32), raw == -3.0, win.r0, win.c0, packed)


def picture_pixel(row: int, col: int) -> tuple[int, int]:
    """(y, x) of a picture pixel that samples grid cell (row, col)."""
    win = sw.picture_window()
    return int(np.flatnonzero(win.rows == row)[0]), int(np.flatnonzero(win.cols == col)[0])


def class_of_index(p: int):
    """The B1 class (0 to 5) of a palette index of 2 and up, 'uncoloured' for 0 and 'hatched' for 1."""
    if p == 0:
        return "uncoloured"
    if p == 1:
        return "hatched"
    palette = [int(v) for v in sw.class_palette()]
    return palette.index(p) if p in palette else "unknown"


def listing_xml(keys) -> bytes:
    body = "".join(f"<Contents><Key>{k}</Key><Size>1</Size></Contents>" for k in keys)
    return ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult><IsTruncated>false</IsTruncated>'
            f"{body}</ListBucketResult>").encode()


def key_for(product, valid: datetime) -> str:
    return f"CONUS/{product.folder}/{valid:%Y%m%d}/MRMS_{product.folder}_{valid:%Y%m%d-%H%M%S}.grib2.gz"


class FakeBucket:
    """Answers the S3 listings (by the prefix in the query) and the downloads. A URL in errors gets that error."""

    def __init__(self, keys=(), files=None, errors=None):
        self.keys = list(keys)
        self.files = files or {}
        self.errors = errors or {}
        self.urls = []

    def __call__(self, url, headers=None):
        self.urls.append(url)
        if url in self.errors:
            return None, self.errors[url]
        if "list-type=2" in url:
            prefix = parse_qs(urlsplit(url).query)["prefix"][0]
            return listing_xml([k for k in self.keys if k.startswith(prefix)]), None
        key = url.replace(sw.BUCKET, "")
        if key in self.files:
            return self.files[key], None
        return None, "not published (HTTP 404)"

    def downloads(self):
        return [u for u in self.urls if "list-type=2" not in u]


def fake_decode(data, product, expected):
    """Stands in for swath.decode_bytes: the bytes b'junk' are refused as a file; anything else is a picture with
    one cell at 66 tenths (0.25 in) at grid cell (705, 2273), which is in Montana near Glasgow."""
    if data == b"junk":
        raise sw.SwathError("NOAA's download was not a readable radar file")
    return synthetic(product, expected, {(705, 2273): 6.6})


def run_collect(test, bucket, now=NOW, cache=None, decode=fake_decode, **kw):
    """collect() with the fake bucket and the fake decode, in a temporary folder that the test removes when it ends."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    cache = cache or str(Path(tmp.name) / "cache")
    out = Path(tmp.name) / "site"
    with mock.patch.object(sw, "decode_bytes", decode):
        frames, files, states = sw.collect(now, cache, out, TOWNS, get=bucket, **kw)
    return frames, files, states, out


def bucket_with(hour=(VALID,), day=(DAY_VALID,), **kw) -> FakeBucket:
    keys = [key_for(HOUR, v) for v in hour] + [key_for(DAY, v) for v in day]
    files = {key_for(HOUR, v): b"fake-hour" for v in hour}
    files.update({key_for(DAY, v): b"fake-day" for v in day})
    return FakeBucket(keys=keys, files=files, **kw)


class ListingTests(unittest.TestCase):
    def test_the_listing_is_ordered_by_time_and_names_each_key(self):
        keys = [key_for(HOUR, VALID), key_for(HOUR, VALID - timedelta(minutes=2))]
        items = sw.parse_listing(listing_xml(keys), HOUR)
        self.assertEqual([v for v, _k in items], [VALID - timedelta(minutes=2), VALID])
        self.assertEqual(items[-1][1], key_for(HOUR, VALID))

    def test_other_products_and_other_files_are_not_listed(self):
        keys = [key_for(DAY, DAY_VALID), "CONUS/MESH_Max_60min_00.50/20261019/notes.txt"]
        self.assertEqual(sw.parse_listing(listing_xml(keys), HOUR), [])

    def test_a_listing_cut_short_is_refused(self):
        xml = listing_xml([key_for(HOUR, VALID)]).replace(b"<IsTruncated>false", b"<IsTruncated>true")
        with self.assertRaisesRegex(sw.SwathError, "cut short"):
            sw.parse_listing(xml, HOUR)

    def test_an_unreadable_listing_is_refused(self):
        with self.assertRaisesRegex(sw.SwathError, "not readable"):
            sw.parse_listing(b"<html>error</html>", HOUR)

    def test_yesterday_is_listed_when_today_is_empty(self):
        yesterday = VALID - timedelta(days=1)
        bucket = FakeBucket(keys=[key_for(HOUR, yesterday), key_for(HOUR, yesterday + timedelta(minutes=2))])
        valid, key = sw.newest_file(HOUR, datetime(2026, 10, 19, 0, 1, tzinfo=UTC), bucket, [])
        self.assertEqual(valid, yesterday + timedelta(minutes=2))
        self.assertEqual(key, key_for(HOUR, valid))
        self.assertEqual(sum("list-type=2" in u for u in bucket.urls), 2)     # today, then yesterday

    def test_one_listing_when_today_has_files(self):
        bucket, ledger = FakeBucket(keys=[key_for(HOUR, VALID)]), []
        sw.newest_file(HOUR, NOW, bucket, ledger)
        self.assertEqual(len(bucket.urls), 1)
        self.assertEqual((ledger[0]["kind"], ledger[0]["files"]), ("list", 1))

    def test_no_file_today_or_yesterday_is_unavailable(self):
        with self.assertRaisesRegex(sw.SwathError, "no file for today or yesterday"):
            sw.newest_file(HOUR, NOW, FakeBucket(), [])


class HeaderTests(unittest.TestCase):
    def decode(self, msg, product=HOUR, expected=VALID):
        return sw.decode_message(msg, product, expected)

    def test_a_good_header_decodes_and_its_valid_time_comes_from_dataDate_and_dataTime(self):
        dec = self.decode(FakeMessage(FakeValues({(705, 2273): 6.6})))
        self.assertEqual(dec.valid, VALID)                  # dataDate 20261019, dataTime 158 is 01:58
        self.assertEqual(dec.header["parameterNumber"], 30)
        self.assertEqual(int(dec.tenths[705 - dec.r0, 2273 - dec.c0]), 66)

    def test_the_parameter_must_match_the_folder(self):
        # C9: the page says which window the file covers; the parameter number and folder go to the record
        with self.assertRaises(sw.SwathError) as cm:
            self.decode(FakeMessage(parameterNumber=34))
        self.assertEqual(str(cm.exception), "NOAA's file covers the last 24 hours, not the last hour")
        self.assertEqual(cm.exception.detail, "parameter 34 in folder MESH_Max_60min_00.50 (parameter 30 expected)")
        with self.assertRaises(sw.SwathError) as cm:
            self.decode(FakeMessage(parameterNumber=7))
        self.assertEqual(str(cm.exception), "the file is not NOAA's hail product for the last hour")
        self.assertEqual(cm.exception.detail, "parameter 7 in folder MESH_Max_60min_00.50 (parameter 30 expected)")
        self.assertEqual(self.decode(FakeMessage(parameterNumber=34, dataTime=130), DAY, DAY_VALID).valid, DAY_VALID)

    def test_discipline_and_category_are_checked(self):
        with self.assertRaises(sw.SwathError) as cm:
            self.decode(FakeMessage(discipline=2))
        self.assertEqual(str(cm.exception), "the file is not NOAA's MRMS radar product")
        self.assertIn("discipline 2, category 3", cm.exception.detail)
        with self.assertRaises(sw.SwathError) as cm:
            self.decode(FakeMessage(parameterCategory=2))
        self.assertIn("category 2", cm.exception.detail)

    def test_the_grid_must_be_the_b1_grid_and_scanned_the_same_way(self):
        with self.assertRaisesRegex(sw.SwathError, "not 7,000 by 3,500"):
            self.decode(FakeMessage(Ni=6999))
        with self.assertRaisesRegex(sw.SwathError, "latitudeOfFirstGridPointInDegrees 54"):
            self.decode(FakeMessage(latitudeOfFirstGridPointInDegrees=54.0))
        with self.assertRaisesRegex(sw.SwathError, "longitudeOfFirstGridPointInDegrees"):
            self.decode(FakeMessage(longitudeOfFirstGridPointInDegrees=229.995))
        with self.assertRaisesRegex(sw.SwathError, "not scanned"):
            self.decode(FakeMessage(jScansPositively=1))

    def test_the_header_valid_time_must_be_the_file_name_time(self):
        # C10: both times in Montana time, and no UTC in the words
        with self.assertRaises(sw.SwathError) as cm:
            self.decode(FakeMessage(dataTime=159))
        self.assertEqual(str(cm.exception), "the file's time (Oct 18, 7:59 pm MDT) does not match the time in its name "
                                            "(Oct 18, 7:58 pm MDT)")
        with self.assertRaisesRegex(sw.SwathError, r"^the file's time \(Oct 17, 7:58 pm MDT\) does not match the time"):
            self.decode(FakeMessage(dataDate=20261018))

    def test_a_missing_header_key_is_named(self):
        msg = FakeMessage()
        del msg.keys["dataTime"]
        with self.assertRaisesRegex(sw.SwathError, "no dataTime"):
            self.decode(msg)

    def test_codes_other_than_missing_and_no_coverage_are_refused(self):
        with self.assertRaisesRegex(sw.SwathError, "code the NOAA table does not list"):
            self.decode(FakeMessage(FakeValues({(705, 2273): -2.0})))

    def test_values_off_the_tenth_of_a_millimetre_are_refused(self):
        with self.assertRaisesRegex(sw.SwathError, "tenths of a millimetre"):
            self.decode(FakeMessage(FakeValues({(705, 2273): 6.37})))

    def test_values_must_match_the_grid_shape(self):
        class Small(FakeValues):
            shape = (10, 10)
        with self.assertRaisesRegex(sw.SwathError, "don't match its grid"):
            self.decode(FakeMessage(Small({})))

    def test_a_file_that_is_not_grib_is_refused_before_pygrib_is_needed(self):
        with self.assertRaisesRegex(sw.SwathError, "^NOAA's download was not a readable radar file$"):
            sw.decode_bytes(b"not a grib file at all", HOUR, VALID)
        with self.assertRaisesRegex(sw.SwathError, "not a readable gzip"):
            sw.decode_bytes(b"\x1f\x8b" + b"\x00" * 8, HOUR, VALID)


class PictureTests(unittest.TestCase):
    def test_the_picture_covers_the_box_on_the_b1_grid(self):
        win = sw.picture_window()
        self.assertEqual((win.r0, win.r1, win.c0, win.c1), (450, 1199, 1150, 2899))
        self.assertEqual((win.r1 - win.r0 + 1, win.c1 - win.c0 + 1), (750, 1750))
        self.assertEqual(hs.cell_for(50.5, -110.0)[0], 450)
        self.assertEqual(hs.cell_for(43.0, -110.0)[0], 1200)   # the box's bottom edge; the picture stops one row above
        self.assertEqual(g.image_size(sw.WIDTH), (1750, 1097))

    def test_every_picture_column_samples_one_cell(self):
        win = sw.picture_window()
        self.assertEqual(len(set(win.cols.tolist())), 1750)
        self.assertTrue(np.all(np.diff(win.cols) == 1))

    def test_the_crop_takes_the_cell_at_its_grid_position(self):
        dec = synthetic(cells={(705, 2273): 6.6})
        self.assertEqual(int(dec.tenths[705 - dec.r0, 2273 - dec.c0]), 66)
        self.assertEqual(dec.tenths.shape, (750, 1750))
        self.assertEqual(int(dec.tenths.max()), 66)

    def test_a_cell_outside_the_box_is_not_in_the_picture(self):
        dec = synthetic(cells={(100, 100): 50.0})               # far outside the box: not read
        index, hatched = sw.picture_index(dec)
        self.assertEqual(int(dec.tenths.max()), 0)
        self.assertFalse(index.any())
        self.assertFalse(hatched)

    def test_the_floor_is_6_point_4_mm_and_values_below_it_are_uncoloured(self):
        self.assertEqual(hs.FLOOR_TENTHS, 64)
        y, x = picture_pixel(705, 2273)
        for mm, expect in ((6.3, "uncoloured"), (6.4, 0), (6.6, 0)):
            index, _ = sw.picture_index(synthetic(cells={(705, 2273): mm}))
            self.assertEqual(class_of_index(int(index[y, x])), expect, mm)

    def test_minus_one_is_uncoloured_and_minus_three_is_hatched(self):
        cells = {(r, c): -3.0 for r in range(700, 711) for c in range(2270, 2281)}
        cells[(690, 2270)] = -1.0
        index, hatched = sw.picture_index(synthetic(cells=cells))
        self.assertTrue(hatched)
        y0, x0 = picture_pixel(700, 2270)
        y1, x1 = picture_pixel(710, 2280)
        block = index[y0:y1 + 1, x0:x1 + 1]
        self.assertTrue(np.any(block == 1))                    # the stripes show
        self.assertEqual(set(np.unique(block).tolist()), {0, 1})
        yy, xx = picture_pixel(690, 2270)
        self.assertEqual(int(index[yy, xx]), 0)                 # -1 is never hatched

    def test_class_edges_follow_b1(self):
        edges = {190: 0, 191: 1, 253: 1, 254: 2, 380: 2, 381: 3, 507: 3, 508: 4, 698: 4, 699: 5, 2000: 5}
        y, x = picture_pixel(705, 2273)
        for tenths, cls in edges.items():
            index, _ = sw.picture_index(synthetic(cells={(705, 2273): tenths / 10.0}))
            self.assertEqual(class_of_index(int(index[y, x])), cls, tenths)

    def test_the_palette_colours_are_the_class_bands(self):
        rgb, alpha = g.palette(sw.STYLE)
        for (lo, hi, colour, a), p in zip(g.HAIL_SWATH_BANDS, sw.class_palette()):
            p = int(p)
            self.assertEqual(tuple(rgb[3 * p:3 * p + 3]), g._hex(colour))
            self.assertEqual(alpha[p], round(a * 255))
            self.assertTrue(lo - 1e-9 <= g.level_value(sw.STYLE, p - 2) <= hi + 1e-9)
        self.assertEqual(len(rgb) // 3, 256)

    def test_the_png_keeps_the_palette_indices_exactly(self):
        index, _ = sw.picture_index(synthetic(cells={(705, 2273): 6.6, (800, 2000): 300.0, (801, 2000): -3.0}))
        png = g.png_bytes(index, sw.STYLE)
        with Image.open(io.BytesIO(png)) as im:
            self.assertEqual((im.mode, im.size), ("P", (1750, 1097)))
            back = np.array(im)
        np.testing.assert_array_equal(back, index)

    def test_round_trip_at_1000_sampled_pixels_has_no_mismatch(self):
        """Gate B4-1 in test form: at sampled pixels of the PNG, the class shown equals the class of the decoded cell."""
        rng = np.random.default_rng(7)
        win = sw.picture_window()
        shape = (win.r1 - win.r0 + 1, win.c1 - win.c0 + 1)
        raw = np.full(shape, -1.0)
        draw = rng.random(shape)
        raw[draw < 0.02] = rng.uniform(0.2, 75.0, size=int((draw < 0.02).sum()))
        raw[(draw >= 0.02) & (draw < 0.021)] = -3.0
        raw = np.round(raw, 1)
        tenths, packed = hs.pack_tenths(raw)
        dec = sw.Decoded(VALID, {}, tenths.astype(np.int32), raw == -3.0, win.r0, win.c0, packed)
        index, _ = sw.picture_index(dec)
        with Image.open(io.BytesIO(g.png_bytes(index, sw.STYLE))) as im:
            back = np.array(im)
        ys, xs = rng.integers(0, back.shape[0], 1000), rng.integers(0, back.shape[1], 1000)
        mismatches = 0
        for y, x in zip(ys.tolist(), xs.tolist()):
            row, col = int(win.rows[y]), int(win.cols[x])
            t = int(dec.tenths[row - dec.r0, col - dec.c0])
            shown = class_of_index(int(back[y, x]))
            if raw[row - dec.r0, col - dec.c0] == -3.0:
                ok = shown in ("hatched", "uncoloured")
            elif t < hs.FLOOR_TENTHS:
                ok = shown == "uncoloured"
            else:
                wanted = [i for i, c in enumerate(hs.CLASSES) if c["min_tenths"] == hs.class_for(t)["min_tenths"]][0]
                ok = shown == wanted
            mismatches += 0 if ok else 1
        self.assertEqual(mismatches, 0)


class LiveFileTests(unittest.TestCase):
    def test_only_tiles_with_a_cell_at_the_floor_or_a_no_coverage_cell_are_written(self):
        dec = synthetic(cells={(705, 2273): 6.6, (706, 2273): 6.3, (900, 1200): 25.4, (900, 1205): 0.0,
                               (900, 1210): -3.0})
        files = sw.live_files(dec, 60)
        self.assertEqual(sorted(files), ["r0070_c0227", "r0090_c0120", "r0090_c0121"])    # D13: the -3 cell's tile too
        self.assertEqual(json.loads(files["r0070_c0227"])["cells"], [[705, 2273, 66]])     # 6.3 mm is below the floor
        self.assertEqual(json.loads(files["r0090_c0120"])["cells"], [[900, 1200, 254]])
        self.assertNotIn("nocov", json.loads(files["r0090_c0120"]))
        self.assertEqual((json.loads(files["r0090_c0121"])["cells"], json.loads(files["r0090_c0121"])["nocov"]),
                         ([], [[900, 1210]]))

    def test_the_file_format_and_its_cells(self):
        dec = synthetic(valid=VALID, cells={(705, 2273): 6.6, (701, 2270): 25.4})
        doc = json.loads(sw.live_files(dec, 60)["r0070_c0227"])
        self.assertEqual(set(doc), {"f", "window", "valid", "cells"})
        self.assertEqual((doc["f"], doc["window"], doc["valid"]), ("hail-live-v1", 60, "2026-10-19T01:58:00Z"))
        self.assertEqual(doc["cells"], [[701, 2270, 254], [705, 2273, 66]])
        self.assertTrue(all(isinstance(v, int) for cell in doc["cells"] for v in cell))

    def test_the_live_files_equal_the_decoded_tenths_at_every_cell_at_the_floor(self):
        rng = np.random.default_rng(3)
        win = sw.picture_window()
        shape = (win.r1 - win.r0 + 1, win.c1 - win.c0 + 1)
        raw = np.full(shape, -1.0)
        hit = rng.random(shape) < 0.01
        raw[hit] = np.round(rng.uniform(1.0, 60.0, size=int(hit.sum())), 1)
        tenths, packed = hs.pack_tenths(raw)
        dec = sw.Decoded(VALID, {}, tenths.astype(np.int32), raw == -3.0, win.r0, win.c0, packed)
        seen = {}
        for text in sw.live_files(dec, 60).values():
            for row, col, value in json.loads(text)["cells"]:
                seen[(row, col)] = value
        expected = {(int(r) + win.r0, int(c) + win.c0): int(dec.tenths[r, c])
                    for r, c in zip(*np.nonzero(dec.tenths >= hs.FLOOR_TENTHS))}
        self.assertEqual(seen, expected)
        self.assertGreater(len(expected), 100)

    def test_sub_floor_cells_alone_have_no_file_and_a_no_coverage_cell_makes_one(self):
        self.assertEqual(sw.live_files(synthetic(cells={(705, 2273): 6.3}), 1440), {})
        doc = json.loads(sw.live_files(synthetic(cells={(705, 2273): 6.3, (700, 2270): -3.0}), 1440)["r0070_c0227"])
        self.assertEqual((doc["cells"], doc["nocov"]), ([], [[700, 2270]]))     # D13; the sub-floor cell is not written

    def test_a_tile_with_only_no_coverage_cells_is_written_with_an_empty_cells_list(self):
        # D13: such a tile has a file, with an empty "cells" list and its no-coverage cells under "nocov"
        files = sw.live_files(synthetic(cells={(705, 2273): -3.0, (706, 2274): -3.0, (900, 1210): -3.0}), 60)
        self.assertEqual(sorted(files), ["r0070_c0227", "r0090_c0121"])
        for name, want in (("r0070_c0227", [[705, 2273], [706, 2274]]), ("r0090_c0121", [[900, 1210]])):
            doc = json.loads(files[name])
            self.assertEqual(set(doc), {"f", "window", "valid", "cells", "nocov"})
            self.assertEqual((doc["cells"], doc["nocov"]), ([], want))
        # the sheet reads a no-coverage cell as no coverage, and a stale line keeps the all-clear sentence (D9)
        self.assertEqual(sw.sheet_line(60, 0, VALID, "fresh", None, nocov=True), sw.WORDS_SWATH["no_coverage"])
        self.assertEqual(sw.sheet_line(60, 0, VALID, "stale", "", nocov=True),
                         sw.WORDS_SWATH["no_coverage"] + " " + ALL_CLEAR)
        # the picture flags the no-coverage cells and draws no size class for them
        index, hatched = sw.picture_index(synthetic(cells={(705, 2273): -3.0}))
        self.assertTrue(hatched)
        self.assertFalse(np.any(index >= 2))

    def test_a_tile_lists_its_no_coverage_cells_under_nocov_and_not_in_cells(self):
        dec = synthetic(cells={(705, 2273): 6.6, (706, 2274): -3.0})
        doc = json.loads(sw.live_files(dec, 60)["r0070_c0227"])
        self.assertEqual(doc["cells"], [[705, 2273, 66]])
        self.assertEqual(doc["nocov"], [[706, 2274]])
        self.assertNotIn("sample", doc)

    def test_a_sample_tile_is_marked_and_a_live_tile_is_not(self):
        dec = synthetic(cells={(705, 2273): 6.6})
        self.assertNotIn("sample", json.loads(sw.live_files(dec, 60)["r0070_c0227"]))
        self.assertTrue(json.loads(sw.live_files(dec, 60, sample=True)["r0070_c0227"])["sample"])

    def test_every_sample_no_coverage_cell_is_listed_in_its_tile(self):
        # D13: no-coverage cells are listed whether or not their tile has a cell at the floor (the sample has
        # 175 such tiles)
        dec = sw.sample_decoded(HOUR, VALID)
        tiles = sw.live_files(dec, 60, sample=True)
        listed = sorted(cell for text in tiles.values() for cell in json.loads(text).get("nocov", []))
        expected = sorted([int(r) + dec.r0, int(c) + dec.c0] for r, c in zip(*np.nonzero(dec.nocov)))
        self.assertGreater(len(expected), 0)
        self.assertEqual(listed, expected)
        self.assertTrue(any(json.loads(text)["cells"] == [] for text in tiles.values()))


class FreshnessTests(unittest.TestCase):
    def test_the_hour_layer_thresholds(self):
        self.assertEqual(sw.freshness(HOUR, NOW - timedelta(minutes=20), NOW)[0], "fresh")
        self.assertEqual(sw.freshness(HOUR, NOW - timedelta(minutes=20, seconds=1), NOW)[0], "stale")
        self.assertEqual(sw.freshness(HOUR, NOW - timedelta(minutes=60), NOW)[0], "stale")
        state, _age, problem = sw.freshness(HOUR, NOW - timedelta(minutes=61), NOW)
        self.assertEqual(state, "unavailable")
        self.assertIn("61 min old, more than 60 min", problem)
        state, _age, problem = sw.freshness(HOUR, NOW - timedelta(minutes=60, seconds=30), NOW)
        self.assertEqual(state, "unavailable")
        self.assertEqual(problem, sw.WORDS_SWATH["age_out"].format(age=61, limit=60))   # 60.5 min rounds up to 61

    def test_the_day_layer_thresholds(self):
        self.assertEqual(sw.freshness(DAY, NOW - timedelta(minutes=60), NOW)[0], "fresh")
        self.assertEqual(sw.freshness(DAY, NOW - timedelta(minutes=61), NOW)[0], "stale")
        self.assertEqual(sw.freshness(DAY, NOW - timedelta(minutes=120), NOW)[0], "stale")
        self.assertEqual(sw.freshness(DAY, NOW - timedelta(minutes=121), NOW)[0], "unavailable")
        state, _age, problem = sw.freshness(DAY, NOW - timedelta(minutes=120, seconds=30), NOW)
        self.assertEqual(state, "unavailable")
        self.assertIn("121 min old, more than 120 min", problem)

    def test_a_file_stamped_after_the_build_clock_is_unavailable_beyond_five_minutes(self):
        self.assertEqual(sw.freshness(HOUR, NOW + timedelta(minutes=2), NOW)[0], "fresh")
        state, _age, problem = sw.freshness(HOUR, NOW + timedelta(minutes=6), NOW)
        self.assertEqual(state, "unavailable")
        self.assertIn("newer than this build's time", problem)


class CollectTests(unittest.TestCase):
    """collect() end to end with the fake bucket and the fake decode: no network, no pygrib."""

    def test_both_layers_fresh_draw_their_pictures_and_live_files(self):
        frames, files, states, out = run_collect(self, bucket_with())
        self.assertEqual(set(frames), {"hail_60", "hail_1440"})
        self.assertEqual((frames["hail_60"]["state"], frames["hail_1440"]["state"]), ("fresh", "fresh"))
        self.assertTrue((out / frames["hail_60"]["src"]).is_file())
        tile = "hail/live/1440/202610190130/r0070_c0227.json"       # the day frame's valid time (D14)
        self.assertIn(tile, files)
        self.assertTrue((out / tile).is_file())
        self.assertNotIn("sample", json.loads((out / tile).read_text(encoding="utf-8")))
        self.assertEqual(states["hail_60"]["label"], sw.LABEL)
        names = [e["what"].rsplit("/", 1)[1] for e in states["hail_60"]["requests"] if e["kind"] == "file"]
        self.assertEqual(names, [key_for(HOUR, VALID).rsplit("/", 1)[1]])

    def test_live_files_sit_in_the_folder_of_the_frame_valid_time_and_a_later_build_writes_only_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, out = Path(tmp) / "cache", Path(tmp) / "site"
            later = VALID + timedelta(minutes=2)
            with mock.patch.object(sw, "decode_bytes", fake_decode):
                first, _files, _states = sw.collect(NOW, cache, out, TOWNS, get=bucket_with(hour=(VALID,)))
                second, files, _states = sw.collect(NOW + timedelta(minutes=2), cache, out, TOWNS,
                                                    get=bucket_with(hour=(VALID, later)))
            self.assertTrue(first["hail_60"]["src"].endswith("hail-60-202610190158.png"))
            self.assertEqual(first["hail_60"]["live"]["pattern"], "hail/live/60/202610190158/{tile}.json")
            self.assertEqual(second["hail_60"]["stamp"], "202610190200")
            self.assertEqual(second["hail_60"]["live"]["pattern"], "hail/live/60/202610190200/{tile}.json")
            live = [f for f in files if f.startswith("hail/live/60/")]
            self.assertTrue(live)
            self.assertTrue(all(f.startswith("hail/live/60/202610190200/") for f in live))   # only the current folder
            self.assertTrue((out / "hail/live/60/202610190200/r0070_c0227.json").is_file())

    def test_the_cache_serves_a_second_build_without_a_download(self):
        bucket = bucket_with()
        with tempfile.TemporaryDirectory() as tmp:
            cache, out = Path(tmp) / "cache", Path(tmp) / "site"
            with mock.patch.object(sw, "decode_bytes", fake_decode):
                sw.collect(NOW, cache, out, TOWNS, get=bucket)
                self.assertEqual(len(bucket.downloads()), 2)          # one download per product
                frames, _files, states = sw.collect(NOW, cache, out, TOWNS, get=bucket)
            self.assertEqual(len(bucket.downloads()), 2)              # the second build downloads nothing
            self.assertEqual(frames["hail_60"]["state"], "fresh")
            self.assertTrue(any(e.get("cache") == "hit" for e in states["hail_60"]["requests"]))

    def test_a_bad_cached_copy_is_fetched_once_more(self):
        bucket = bucket_with()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            (cache / key_for(HOUR, VALID).rsplit("/", 1)[1]).write_bytes(b"junk")
            with mock.patch.object(sw, "decode_bytes", fake_decode):
                frames, _files, _states = sw.collect(NOW, cache, Path(tmp) / "site", TOWNS, get=bucket)
        self.assertEqual(frames["hail_60"]["state"], "fresh")
        self.assertEqual(sum("60min" in u for u in bucket.downloads()), 1)

    def test_the_newest_listed_file_is_the_one_drawn(self):
        frames, *_ = run_collect(self, bucket_with(hour=(VALID - timedelta(minutes=4), VALID - timedelta(minutes=2), VALID)))
        self.assertEqual(frames["hail_60"]["valid"], "2026-10-19T01:58:00Z")

    def test_a_failed_listing_is_unavailable_with_its_reason_and_no_picture(self):
        bucket = bucket_with(errors={sw.list_url(HOUR, NOW.date()): "HTTP 503"})
        frames, files, states, _out = run_collect(self, bucket)
        hour = frames["hail_60"]
        self.assertEqual(hour["state"], "unavailable")
        self.assertIn("NOAA's server had an error", hour["state_line"])
        self.assertTrue(hour["state_line"].endswith(ALL_CLEAR))
        self.assertFalse(any("hail-60" in f for f in files))
        self.assertEqual(states["hail_60"]["state"], "unavailable")
        self.assertEqual(frames["hail_1440"]["state"], "fresh")          # one product's failure is its own

    def test_a_failed_download_names_the_reason(self):
        bucket = bucket_with(errors={sw.BUCKET + key_for(DAY, DAY_VALID): "HTTP 500"})
        frames, *_ = run_collect(self, bucket)
        self.assertEqual(frames["hail_1440"]["state"], "unavailable")
        self.assertIn("didn't load: NOAA's server had an error", frames["hail_1440"]["problem"])

    def test_a_file_that_does_not_decode_is_unavailable_with_the_reason(self):
        bucket = FakeBucket(keys=[key_for(HOUR, VALID)], files={key_for(HOUR, VALID): b"junk"})
        frames, *_ = run_collect(self, bucket)
        self.assertEqual(frames["hail_60"]["state"], "unavailable")
        self.assertIn("not a readable radar file", frames["hail_60"]["problem"])

    def test_a_stale_day_file_is_drawn_and_says_so(self):
        frames, _files, states, out = run_collect(self, bucket_with(day=(NOW - timedelta(minutes=90),)))
        day = frames["hail_1440"]
        self.assertEqual(day["state"], "stale")
        self.assertTrue(day["state_line"].endswith(ALL_CLEAR))
        self.assertTrue((out / day["src"]).is_file())
        self.assertFalse(states["hail_1440"]["ok"])

    def test_an_old_hour_file_is_unavailable_and_draws_nothing(self):
        frames, files, *_ = run_collect(self, bucket_with(hour=(NOW - timedelta(minutes=75),)))
        self.assertEqual(frames["hail_60"]["state"], "unavailable")
        self.assertIn("more than 60 min", frames["hail_60"]["problem"])
        self.assertFalse(any("hail-60" in f for f in files))

    def test_the_sample_is_labelled_and_needs_no_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames, files, states = sw.collect(NOW, Path(tmp) / "cache", Path(tmp) / "site", TOWNS, sample=True)
            self.assertEqual(frames["hail_60"]["state"], "fresh")
            self.assertTrue(frames["hail_60"]["sample"])
            self.assertTrue(states["hail_60"]["detail"].startswith("SAMPLE"))
            self.assertIn("Sample:", sw.map_data_swath(frames)["hail_60"]["legend_note"])
            self.assertIn("SAMPLE: invented radar estimate", frames["hail_1440"]["source"])
            self.assertTrue(sw.map_data_swath(frames)["hail_60"]["sample"])
            tile = next(f for f in files if f.startswith("hail/live/60/"))
            self.assertTrue(json.loads((Path(tmp) / "site" / tile).read_text(encoding="utf-8"))["sample"])
            self.assertTrue(sw.sheet_line(60, 66, VALID, "fresh", None, sample=True).startswith(
                sw.WORDS_SWATH["sample_sheet"] + " "))
            png = (Path(tmp) / "site" / frames["hail_1440"]["src"]).read_bytes()
            self.assertLess(len(png), 150 * 1024)
            with Image.open(io.BytesIO(png)) as im:
                self.assertEqual(im.mode, "P")
                used = set(np.unique(np.array(im)).tolist())
        self.assertGreaterEqual(len({class_of_index(p) for p in used if p >= 2}), 4)

    def test_a_sample_list_credits_the_sample_and_never_noaa(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames, _files, _states = sw.collect(NOW, Path(tmp) / "cache", Path(tmp) / "site", TOWNS, sample=True)
            for key in ("hail_60", "hail_1440"):
                lines = sw.describe(frames[key], NOW, TOWNS)
                text = " ".join(lines)
                self.assertTrue(lines[0].startswith("SAMPLE:"), key)
                self.assertIn("SAMPLE: invented radar estimate, not NOAA data.", text, key)
                self.assertNotIn("NOAA Open Data", text, key)
                self.assertFalse(any(line.startswith("Source: NOAA") for line in lines), key)

    def test_offline_draws_the_newest_cached_file_and_makes_no_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, out = Path(tmp) / "cache", Path(tmp) / "site"
            cache.mkdir()
            (cache / f"MRMS_MESH_Max_60min_00.50_{VALID:%Y%m%d-%H%M%S}.grib2").write_bytes(b"fake-hour")
            with mock.patch.object(sw, "decode_bytes", fake_decode):
                frames, files, states = sw.collect(NOW, cache, out, TOWNS, offline=True)
        self.assertEqual(frames["hail_60"]["state"], "fresh")
        self.assertIn("hail/live/60/202610190158/r0070_c0227.json", files)
        self.assertFalse(any(e["kind"] in ("list", "file") for e in states["hail_60"]["requests"]))
        self.assertEqual(frames["hail_1440"]["state"], "unavailable")
        self.assertIn("holds no file", frames["hail_1440"]["problem"])
        self.assertTrue(frames["hail_1440"]["state_line"].endswith(ALL_CLEAR))

    def test_offline_with_an_empty_or_missing_cache_is_unavailable_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            frames, files, _states = sw.collect(NOW, empty, Path(tmp) / "site", TOWNS, offline=True)
            missing, _files, _states = sw.collect(NOW, Path(tmp) / "missing", Path(tmp) / "site", TOWNS, offline=True)
        for key in ("hail_60", "hail_1440"):
            self.assertEqual(frames[key]["state"], "unavailable", key)
            self.assertTrue(frames[key]["state_line"].endswith(ALL_CLEAR), key)
            self.assertEqual(missing[key]["state"], "unavailable", key)
            self.assertTrue(missing[key]["state_line"].endswith(ALL_CLEAR), key)
        self.assertIn("holds no file", frames["hail_60"]["problem"])
        self.assertIn("does not exist", missing["hail_60"]["problem"])
        self.assertEqual(files, [])


class CommandLineTests(unittest.TestCase):
    """main(): the record the build reads, for the sample field and for an offline build with no cached file."""

    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sw.main(argv)
        return code, json.loads(out.getvalue())

    def test_the_sample_build_writes_both_layers_fresh_and_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, record = self.run_main(["--out", str(Path(tmp) / "site"), "--cache", str(Path(tmp) / "cache"),
                                          "--sample", "--now", "2026-10-19T02:00:00Z"])
        self.assertEqual(code, 0)
        self.assertEqual({k: v["state"] for k, v in record["layers"].items()},
                         {"hail_60": "fresh", "hail_1440": "fresh"})
        for layer in record["layers"].values():
            self.assertTrue(layer["lines"][0].startswith("SAMPLE:"))
            self.assertFalse(any(line.startswith("Source: NOAA") for line in layer["lines"]))
        self.assertTrue(any(f.startswith("hail/live/60/") for f in record["files"]))

    def test_an_offline_build_with_an_empty_cache_is_unavailable_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            code, record = self.run_main(["--out", str(Path(tmp) / "site"), "--cache", str(cache), "--offline",
                                          "--now", "2026-10-19T02:00:00Z"])
        self.assertEqual(code, 0)
        self.assertEqual(record["files"], [])
        for layer in record["layers"].values():
            self.assertEqual(layer["state"], "unavailable")
            self.assertTrue(layer["detail"].endswith(ALL_CLEAR))


class SampleFieldTests(unittest.TestCase):
    def test_the_sample_field_uses_the_noaa_codes_and_has_a_no_coverage_corner(self):
        win = sw.picture_window()
        lats = (hs.ROW0_LAT_E3 - 10 * np.arange(win.r0, win.r1 + 1)) / 1000.0
        lons = (hs.COL0_LON_E3 + 10 * np.arange(win.c0, win.c1 + 1)) / 1000.0
        for window in (60, 1440):
            raw = sample_data.swath_field(lats, lons, window)
            self.assertEqual(raw.shape, (750, 1750))
            self.assertFalse(np.any(raw == 0.0))
            self.assertTrue(set(np.unique(raw[raw < 0]).tolist()) <= {-1.0, -3.0})
            self.assertTrue(np.any(raw == -3.0))
            self.assertGreater(int(np.count_nonzero(raw > 6.35)), 1000)
        self.assertGreaterEqual(float(sample_data.swath_field(lats, lons, 60).max()), 69.9)


class WordsTests(unittest.TestCase):
    FORBIDDEN = (("damage", "not "), ("observed hail", "not "), ("no hail", "same as "))

    def drawn(self, tenths=6.6, state="fresh"):
        dec = synthetic(cells={(705, 2273): tenths})
        return sw._drawn(HOUR, dec, NOW, state, timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), False, TOWNS,
                         False)

    def all_words(self):
        out = dict(sw.WORDS_SWATH)
        out["describe"] = " ".join(sw.describe(self.drawn(), NOW, TOWNS))
        out["describe_none"] = " ".join(sw.describe(self.drawn(0.0), NOW, TOWNS))
        out["sheet_hit"] = sw.sheet_line(60, 66, VALID, "fresh", None)
        out["sheet_none"] = sw.sheet_line(60, 0, VALID, "fresh", None)
        out["unavailable"] = sw._unavailable(DAY, "the file list for the last 24 hours didn't load: HTTP 503")["state_line"]
        return out

    def test_forbidden_terms_are_negated_or_absent(self):
        for name, text in self.all_words().items():
            if not isinstance(text, str):
                continue
            low = text.lower()
            for word, before in self.FORBIDDEN:
                for m in re.finditer(re.escape(word), low):
                    self.assertTrue(low[max(0, m.start() - len(before)):m.start()].endswith(before),
                                    f"{name}: {word!r} is not negated: {text[:100]}")
            for bad in ("confirmed", "insurance", "eligib", "dry", "all clear", "clearly"):
                self.assertNotIn(bad, low, f"{name}: {bad}")
            for m in re.finditer(r"all-clear", low):
                self.assertEqual(low[max(0, m.start() - 7):m.start()], "not an ", f"{name}: all-clear")
            self.assertNotIn("clear", low.replace("all-clear", ""), f"{name}: clear")

    def test_the_swath_sentences_pass_the_one_words_list_with_no_exemption(self):   # D89(e); D88(q) is withdrawn
        for name in ("legend_note", "sample_legend_note", "what_this_is"):
            text = sw.WORDS_SWATH[name]
            self.assertEqual(W.residue(text), text, name)        # no EXEMPT or FORECAST pattern applies to the sentence
            W.assert_clean(self, text, name)
        self.assertIn("not observed hail and not an inspection", sw.WORDS_SWATH["legend_note"])
        for name, text in self.all_words().items():              # every line the swath layers print, as Python gives it
            if isinstance(text, str):
                W.assert_clean(self, text, name)

    def test_the_required_sentences_are_present(self):
        self.assertIn("not observed hail and not an inspection", sw.WORDS_SWATH["legend_note"])
        self.assertIn("Uncoloured: no radar hail estimate of 0.25 in or more in the last {window}, or no value; "
                      "NOAA's data does not tell the two apart.", sw.WORDS_SWATH["uncoloured"])
        self.assertTrue(self.all_words()["unavailable"].endswith(ALL_CLEAR))
        self.assertIn("MESH (maximum estimated size of hail) is a radar estimate at the grid cell",
                      " ".join(sw.describe(self.drawn(), NOW, TOWNS)))
        self.assertIn("That is not the same as no hail.", sw.WORDS_SWATH["lead_none"])
        self.assertIn("No radar coverage at this point in the product.", sw.WORDS_SWATH["no_coverage"])

    def test_a_stale_line_and_an_unavailable_line_end_with_the_all_clear_sentence(self):
        stale = " ".join(sw.describe(self.drawn(state="stale"), NOW, TOWNS))
        self.assertIn(ALL_CLEAR, stale)
        self.assertTrue(sw.describe(self.drawn(state="stale"), NOW, TOWNS)[0].endswith(ALL_CLEAR))

    def test_a_stale_sheet_line_ends_with_the_all_clear_sentence(self):
        fresh = sw.sheet_line(60, 0, VALID, "fresh", None)
        self.assertEqual(sw.sheet_line(60, 0, VALID, "stale", ""), fresh + " " + ALL_CLEAR)
        live = sw.sheet_line(60, 66, VALID, "fresh", None)
        self.assertEqual(sw.sheet_line(60, 66, VALID, "stale", ""), live + " " + ALL_CLEAR)
        self.assertEqual(sw.sheet_line(60, 0, VALID, "stale", "", nocov=True),
                         sw.WORDS_SWATH["no_coverage"] + " " + ALL_CLEAR)

    def test_an_unavailable_layer_gives_its_state_line_and_no_cell_words(self):
        line = sw._unavailable(HOUR, "the file list for the last hour didn't load: HTTP 503")["state_line"]
        for valid in (None, VALID):
            for tenths in (0, 66, 1016):
                self.assertEqual(sw.sheet_line(60, tenths, valid, "unavailable", line), line)
        self.assertTrue(line.endswith(ALL_CLEAR))
        self.assertEqual(sw.sheet_line(60, 66, VALID, "not a state", "the given line"), "the given line")

    def test_a_sample_sheet_line_begins_with_the_sample_label_and_the_default_is_unchanged(self):
        label = sw.WORDS_SWATH["sample_sheet"] + " "
        for tenths in (0, 66):
            plain = sw.sheet_line(60, tenths, VALID, "fresh", None)
            self.assertEqual(sw.sheet_line(60, tenths, VALID, "fresh", None, sample=True), label + plain)
        self.assertEqual(sw.sheet_line(60, 66, VALID, "fresh", None),
                         "In the last hour: 0.25 in (6.6 mm), pea to mothball, the largest radar estimate for the "
                         "period ending Oct 18, 7:58 pm MDT.")

    def test_a_no_coverage_cell_reads_the_d9_sentence_and_no_other_cell_does(self):
        self.assertEqual(sw.sheet_line(60, 0, VALID, "fresh", None, nocov=True),
                         "No radar coverage at this point in the product.")
        self.assertTrue(sw.sheet_line(60, 0, VALID, "fresh", None).startswith("No radar hail estimate"))

    def test_the_four_inch_note_is_on_the_sheet_at_1016_tenths_as_in_the_list(self):
        self.assertNotIn("unusually large", sw.sheet_line(60, 1015, VALID, "fresh", None).lower())
        self.assertTrue(sw.sheet_line(60, 1016, VALID, "fresh", None).endswith(" " + sw.WORDS_SWATH["large_note"]))
        self.assertEqual(sw.WORDS_SWATH["large_note"].lower().rstrip("."), hs.WORDS["large_note"])
        self.assertIn(sw.WORDS_SWATH["large_note"], " ".join(sw.describe(self.drawn(tenths=101.6), NOW, TOWNS)))
        self.assertEqual(sw.map_data_swath({})["hail_60"]["live"]["large_note_tenths"], 1016)

    def test_the_panel_says_when_the_build_made_the_state(self):
        self.assertEqual(sw.describe(self.drawn(), NOW, TOWNS)[1], "As of the build at Oct 18, 8:00 pm MDT.")
        unavailable = sw._unavailable(HOUR, "the map check failed")
        self.assertEqual(sw.describe(unavailable, NOW, TOWNS),
                         [unavailable["state_line"], "As of the build at Oct 18, 8:00 pm MDT."])

    def test_describe_names_the_hatched_cells_when_the_layer_has_no_coverage(self):
        dec = synthetic(cells={(705, 2273): 6.6, (700, 2270): -3.0})
        frame = sw._drawn(HOUR, dec, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), True,
                          TOWNS, False)
        self.assertTrue(frame["nodata"])
        self.assertIn(sw.WORDS_SWATH["hatched"], sw.describe(frame, NOW, TOWNS))

    def test_the_viewer_words_say_map_not_picture_or_swath(self):
        for name, text in sw.WORDS_SWATH.items():
            for word in ("picture", "swath"):
                self.assertNotIn(word, text.lower(), f"{name}: {word}")
        self.assertEqual(sw.WORDS_SWATH["montana_outside"],
                         "The largest value in this map's area, {in} in, is outside Montana.")
        line = sw._unavailable(DAY, "the file list for the last 24 hours didn't load: HTTP 503")["state_line"]
        self.assertTrue(line.startswith("Hail, last 24 hours is unavailable: "))
        self.assertTrue(line.endswith(ALL_CLEAR))

    def test_the_sheet_lines_follow_d4_and_d5(self):
        self.assertEqual(sw.sheet_line(60, 66, VALID, "fresh", None),
                         "In the last hour: 0.25 in (6.6 mm), pea to mothball, the largest radar estimate for the "
                         "period ending Oct 18, 7:58 pm MDT.")
        self.assertEqual(sw.sheet_line(60, 0, VALID, "fresh", None),
                         "No radar hail estimate of 0.25 in or more in the last hour here (as of Oct 18, 7:58 pm MDT).")
        self.assertIn("2.01 in (51.3 mm)", sw.sheet_line(1440, 513, DAY_VALID, "fresh", None))
        self.assertIn("0.72 in (18.5 mm)", sw.sheet_line(60, 185, VALID, "fresh", None))
        self.assertNotIn("no hail", sw.sheet_line(60, 0, VALID, "fresh", None).replace("No radar hail", ""))

    def test_the_legend_entries_carry_their_words_and_colours(self):
        entries, gradient = g.legend(sw.STYLE)
        self.assertEqual([e["label"] for e in entries], [c["word"] for c in reversed(hs.CLASSES)])
        self.assertEqual([e["color"] for e in entries], [b[2] for b in reversed(g.HAIL_SWATH_BANDS)])
        self.assertEqual(entries[-1]["range"], "0.25 to 0.74 in")
        self.assertEqual(entries[0]["range"], "2.75 in or more")
        self.assertTrue(all(e["label"] for e in entries))
        self.assertEqual(gradient.count("rgba("), 2 * len(g.HAIL_SWATH_BANDS))

    def test_describe_states_the_largest_value_its_class_its_place_and_the_nearest_town(self):
        lines = sw.describe(self.drawn(), NOW, TOWNS)
        joined = " ".join(lines)
        self.assertIn("Valid Oct 18, 7:58 pm MDT, 2 min ago.", lines[0])
        self.assertIn("0.25 in (6.6 mm), pea to mothball", joined)
        self.assertIn("47.945 degrees north, 107.265 degrees west", joined)
        self.assertIn("miles from Glasgow", joined)
        self.assertNotIn("Cells with a radar estimate of 1.00 in or more", joined)     # D19: no whole-area count
        self.assertNotIn("in this map's area: ", joined)                                 # and no count names the area

    def test_d19_every_count_and_largest_value_in_the_list_is_montana_only(self):
        counts = {name: text for name, text in sw.WORDS_SWATH.items() if "Cells with" in text}
        self.assertEqual(sorted(counts), ["montana_count"])                 # the whole-area count line is gone
        self.assertIn("in Montana", counts["montana_count"])
        self.assertNotIn("severe_count", sw.WORDS_SWATH)
        for name in ("lead_largest", "lead_largest_no_town", "lead_none", "montana_count", "montana_outside"):
            self.assertIn("Montana", sw.WORDS_SWATH[name], name)           # each count and largest value names Montana

    def test_describe_says_when_no_cell_reaches_the_floor(self):
        joined = " ".join(sw.describe(self.drawn(0.0), NOW, TOWNS))
        self.assertIn("No cell in Montana has a radar hail estimate of 0.25 in or more", joined)
        self.assertIn("That is not the same as no hail.", joined)

    def test_d15_the_words_name_montana_first_and_say_when_the_largest_value_is_outside_it(self):
        # a value of 0.74 in (188 tenths) in Canada, north of the Montana border; 0.25 in (66 tenths) in Montana
        canada = (sw.picture_window().r0 + 5, 2273)            # a picture row near the top of the box
        lat, lon = hs.cell_centre(*canada)
        self.assertGreater(lat, 49.0)                          # north of the border
        dec = synthetic(cells={(705, 2273): 6.6, canada: 18.8})
        frame = sw._drawn(HOUR, dec, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), False, TOWNS, False)
        lines = sw.describe(frame, NOW, TOWNS)
        miles = frame["montana_nearest_town_miles"]
        self.assertEqual(lines[2], "Largest radar estimate in Montana: 0.25 in (6.6 mm), pea to mothball. It is at "
                                   f"47.945 degrees north, 107.265 degrees west, {miles} miles from Glasgow.")
        self.assertEqual(lines[3], "Cells with a radar estimate of 0.25 in or more in Montana: 1.")
        self.assertEqual(lines[4], "The largest value in this map's area, 0.74 in, is outside Montana.")
        self.assertEqual(frame["largest_tenths"], 188)
        self.assertEqual(frame["montana_largest_tenths"], 66)
        self.assertEqual(frame["montana_nearest_town"], "Glasgow")  # the Montana cell's town, not the Canadian cell's

    def test_d15_no_town_is_named_for_a_cell_outside_montana(self):
        canada = (sw.picture_window().r0 + 5, 2273)
        dec = synthetic(cells={canada: 18.8})                   # only a Canadian value reaches the floor
        frame = sw._drawn(HOUR, dec, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), False, TOWNS, False)
        self.assertEqual(frame["montana_largest_tenths"], 0)
        self.assertIsNone(frame["montana_nearest_town"])
        self.assertIsNone(frame["montana_nearest_town_miles"])
        self.assertIsNotNone(frame["largest_centre"])          # the picture's own cell is named by its centre only
        lines = sw.describe(frame, NOW, TOWNS)
        joined = " ".join(lines)
        self.assertIn("No cell in Montana has a radar hail estimate of 0.25 in or more", joined)
        self.assertIn("The largest value in this map's area, 0.74 in, is outside Montana.", joined)
        self.assertNotIn("Glasgow", joined)
        self.assertNotIn("Billings", joined)

    def test_d15_no_outside_sentence_when_the_largest_value_is_in_montana(self):
        dec = synthetic(cells={(705, 2273): 6.6})
        frame = sw._drawn(HOUR, dec, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), False, TOWNS, False)
        self.assertFalse(any("is outside Montana" in line for line in sw.describe(frame, NOW, TOWNS)))
        self.assertEqual(frame["largest_tenths"], frame["montana_largest_tenths"])

    def test_the_montana_count_line_counts_the_montana_cells_at_the_floor(self):
        self.assertIn("Cells with a radar estimate of 0.25 in or more in Montana: 1.",
                      " ".join(sw.describe(self.drawn(6.6), NOW, TOWNS)))
        two = synthetic(cells={(705, 2273): 6.6, (706, 2273): 6.6})
        frame = sw._drawn(HOUR, two, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(two), False, TOWNS,
                          False)
        self.assertIn("Cells with a radar estimate of 0.25 in or more in Montana: 2.", sw.describe(frame, NOW, TOWNS))
        self.assertIn("Cells with a radar estimate of 0.25 in or more in Montana: 0.",
                      " ".join(sw.describe(self.drawn(0.0), NOW, TOWNS)))

    def test_a_value_of_4_inches_outside_montana_is_followed_by_its_note(self):
        canada = (sw.picture_window().r0 + 5, 2273)
        dec = synthetic(cells={(705, 2273): 25.4, canada: 114.3})     # 1.00 in in Montana; 4.50 in in Canada
        frame = sw._drawn(HOUR, dec, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), False,
                          TOWNS, False)
        lines = sw.describe(frame, NOW, TOWNS)
        self.assertEqual(lines[2], "Largest radar estimate in Montana: 1.00 in (25.4 mm), quarter to half dollar. It is at "
                                   f"47.945 degrees north, 107.265 degrees west, {frame['montana_nearest_town_miles']} "
                                   "miles from Glasgow.")
        self.assertEqual(lines[3], "Cells with a radar estimate of 0.25 in or more in Montana: 1.")
        self.assertEqual(lines[4], "The largest value in this map's area, 4.50 in, is outside Montana. "
                                   "Unusually large for a radar estimate; treat with care.")
        self.assertNotIn(sw.WORDS_SWATH["large_note"], lines[2:4])           # the Montana value is under 4.00 in

    def test_a_montana_lead_with_no_towns_names_no_town_and_keeps_the_location(self):
        dec = synthetic(cells={(705, 2273): 6.6})
        frame = sw._drawn(HOUR, dec, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), False, [],
                          False)
        lines = sw.describe(frame, NOW, [])
        self.assertEqual(lines[2], "Largest radar estimate in Montana: 0.25 in (6.6 mm), pea to mothball. It is at "
                                   "47.945 degrees north, 107.265 degrees west.")
        self.assertIsNone(frame["montana_nearest_town"])

    def test_the_uncoloured_sentence_names_each_layers_window(self):
        for product, word in ((HOUR, "hour"), (DAY, "24 hours")):
            dec = synthetic(cells={(705, 2273): 6.6})
            frame = sw._drawn(product, dec, NOW, "fresh", timedelta(minutes=2), b"png", {}, sw.cell_stats(dec), False,
                              TOWNS, False)
            want = (f"Uncoloured: no radar hail estimate of 0.25 in or more in the last {word}, or no value; "
                    "NOAA's data does not tell the two apart.")
            self.assertIn(want, sw.describe(frame, NOW, TOWNS))
            self.assertEqual(sw.describe(frame, NOW, TOWNS).count(want), 1)

    def test_the_sheet_line_names_the_period_it_covers(self):
        self.assertEqual(sw.sheet_line(1440, 513, DAY_VALID, "fresh", None),
                         "In the last 24 hours: 2.01 in (51.3 mm), hen egg to tennis ball, the largest radar estimate "
                         "for the period ending Oct 18, 7:30 pm MDT.")

    def test_the_outside_words_and_the_location_use_degrees(self):
        self.assertEqual(sw.map_data_swath({})["hail_60"]["words"]["outside"],
                         "Outside this map's area, which covers 43.0 to 50.5 degrees north and 118.5 to 101.0 degrees "
                         "west. Nothing is drawn here, so no estimate is shown.")
        self.assertEqual(sw._where(47.945, -107.265), "47.945 degrees north, 107.265 degrees west")

    def test_the_stale_line_names_the_layers_limit(self):
        for product, limit in ((HOUR, 20), (DAY, 60)):
            dec = synthetic(cells={(705, 2273): 6.6})
            frame = sw._drawn(product, dec, NOW, "stale", timedelta(minutes=30), b"png", {}, sw.cell_stats(dec),
                              False, TOWNS, False)
            line = frame["state_line"]
            self.assertIn(f"That is more than {limit} minutes old, so it may be out of date.", line)
            self.assertEqual(line.count(ALL_CLEAR), 1)
            self.assertTrue(line.endswith(ALL_CLEAR))

    def test_the_nearest_town_comes_from_towns_json(self):
        name, miles = sw.nearest_town(TOWNS, 45.7833, -108.5007)
        self.assertEqual(name, "Billings")
        self.assertLess(miles, 0.1)

    def test_valid_time_is_montana_time_with_its_zone(self):
        self.assertEqual(sw.valid_text(VALID), MT_VALID_TEXT)
        self.assertEqual(sw.valid_text(datetime(2026, 1, 15, 20, 0, tzinfo=UTC)), "Jan 15, 1:00 pm MST")

    def test_map_data_has_both_layers_with_their_legend_and_templates(self):
        frames, _files, _states, _out = run_collect(self, bucket_with())
        blocks = sw.map_data_swath(frames)
        self.assertEqual(set(blocks), {"hail_60", "hail_1440"})
        self.assertEqual((blocks["hail_60"]["title"], blocks["hail_1440"]["title"]),
                         ("Hail, last hour", "Hail, last 24 hours"))
        for key, block in blocks.items():
            self.assertEqual(block["bounds"], [[43.0, -118.5], [50.5, -101.0]])
            self.assertEqual(len(block["legend"]), 6)
            self.assertTrue(all(e["label"] and e["color"] for e in block["legend"]))
            self.assertEqual((block["live"]["floor_tenths"], block["live"]["tenths_per_inch"]), (64, 254))
            stamp = {"hail_60": "202610190158", "hail_1440": "202610190130"}[key]     # the frames' valid times
            self.assertEqual(block["live"]["pattern"], f"hail/live/{block['window']}/{stamp}/{{tile}}.json")
            self.assertNotIn("?", block["live"]["pattern"])                       # the folder carries the time (D14)
            self.assertTrue(block["frames"][0]["src"].endswith(f"-{stamp}.png"))  # the picture carries it too
            self.assertEqual((block["state"], len(block["frames"])), ("fresh", 1))
            self.assertIn(ALL_CLEAR, block["words"]["unavailable"])
            self.assertIn(ALL_CLEAR, block["words"]["stale"])
            self.assertIn("No radar hail estimate", block["words"]["no_estimate"])

    def test_map_data_carries_the_freshness_minutes_and_the_sample_flag(self):
        blocks = sw.map_data_swath({})
        for p in sw.PRODUCTS:
            self.assertEqual((blocks[p.key]["fresh_min"], blocks[p.key]["stale_min"]),
                             (int(p.fresh.total_seconds() // 60), int(p.stale.total_seconds() // 60)))
        self.assertEqual((blocks["hail_60"]["fresh_min"], blocks["hail_60"]["stale_min"]), (20, 60))
        self.assertEqual((blocks["hail_1440"]["fresh_min"], blocks["hail_1440"]["stale_min"]), (60, 120))
        self.assertEqual(blocks["hail_60"]["words"]["age_out"], sw.WORDS_SWATH["age_out"])
        self.assertIsNone(blocks["hail_60"]["live"]["pattern"])     # no frame, so no folder to read (D14)
        frames, _files, _states, _out = run_collect(self, bucket_with())
        self.assertFalse(sw.map_data_swath(frames)["hail_60"]["sample"])

    def test_the_templates_and_sentences_are_all_in_the_words_table(self):
        block = sw.map_data_swath({})["hail_60"]
        self.assertEqual(block["state"], "unavailable")
        for name in ("live_line", "no_estimate", "fresh", "stale", "unavailable", "uncoloured", "hatched", "outside",
                     "legend_note", "sample_legend_note", "lead_largest", "lead_none", "what_this_is", "source",
                     "all_clear", "age_out", "as_of_build", "no_coverage", "sample_sheet", "sample_source",
                     "large_note", "montana_count", "montana_outside", "lead_largest_no_town"):
            self.assertIn(name, block["words"], name)


class PlainFailureTests(unittest.TestCase):
    """A failure line is plain words for the page. The technical reason (an exception name, a GRIB number, a folder)
    goes to the layer's record, and the page never shows it."""

    CAMEL = re.compile(r"\b[A-Z]{2,}[a-z]\w*|\b[A-Z][a-z]+[A-Z]\w*")     # an exception name such as SSLError
    CODES = ("UTC)", "parameter", "MESH_", "GRIB", "HTTP")

    def assertPlain(self, text: str):
        self.assertFalse(self.CAMEL.search(text), text)
        for word in self.CODES:
            self.assertNotIn(word, text, text)

    @staticmethod
    def request_classes() -> list:
        import requests
        return sorted(name for name, obj in vars(requests.exceptions).items()
                      if isinstance(obj, type) and issubclass(obj, requests.RequestException))

    def test_request_words_names_every_request_exception_class_and_nothing_raw(self):
        names = self.request_classes()
        self.assertGreaterEqual(len(names), 20)            # 22 classes in the pinned requests, plus the base class
        for name in names:
            words = sw.request_words(name)
            self.assertEqual(words, sw.REQUEST_WORDS.get(name, sw.REQUEST_GENERIC), name)
            self.assertPlain(words)
            self.assertEqual(sw.request_words(f"unexpected error ({name})"), words, name)
        self.assertEqual({sw.REQUEST_WORDS[n] for n in ("ReadTimeout", "Timeout", "ConnectTimeout")},
                         {"NOAA did not answer in time"})
        self.assertEqual({sw.REQUEST_WORDS[n] for n in ("ConnectionError", "ProxyError")}, {"NOAA could not be reached"})

    def test_request_words_for_the_forms_the_fetcher_writes(self):
        cases = {
            "server error (HTTP 503)": "NOAA's server had an error",
            "not published (HTTP 404)": "NOAA did not have that file",
            "HTTP 403": "NOAA did not accept the request",
            "HTTP 500": "NOAA's server had an error",
            "no data": sw.REQUEST_GENERIC,
            None: sw.REQUEST_GENERIC,
            "HTTPSConnectionPool(host='noaa-mrms-pds.s3.amazonaws.com', port=443): Read timed out.":
                "NOAA did not answer in time",
            "HTTPSConnectionPool(host='noaa-mrms-pds.s3.amazonaws.com', port=443): Max retries exceeded":
                sw.REQUEST_GENERIC,
        }
        for err, want in cases.items():
            self.assertEqual(sw.request_words(err), want, err)
        self.assertNotIn("noaa-mrms", sw.request_words("HTTPSConnectionPool(host='noaa-mrms-pds.s3.amazonaws.com')"))

    def test_a_request_that_raises_is_named_in_words_and_its_reason_stays_in_the_record(self):
        import requests

        def boom(url, headers=None):
            raise requests.exceptions.ReadTimeout()
        frames, _files, states, _out = run_collect(self, boom)
        hour = frames["hail_60"]
        self.assertEqual(hour["state"], "unavailable")
        self.assertIn("didn't load: NOAA did not answer in time", hour["problem"])
        self.assertPlain(hour["state_line"])
        self.assertEqual(states["hail_60"]["error"], "unexpected error (ReadTimeout)")
        listing = next(e for e in states["hail_60"]["requests"] if e["kind"] == "list")
        self.assertEqual((listing["ok"], listing["error"]), (False, "unexpected error (ReadTimeout)"))

    def test_a_bare_connection_error_reads_as_unreachable_and_keeps_its_name_in_the_record(self):
        bucket = bucket_with(errors={sw.list_url(HOUR, NOW.date()): "ConnectionError"})
        frames, _files, states, _out = run_collect(self, bucket)
        self.assertIn("NOAA could not be reached", frames["hail_60"]["problem"])
        self.assertEqual(states["hail_60"]["error"], "ConnectionError")
        self.assertEqual(frames["hail_1440"]["state"], "fresh")

    def test_c9_and_c10_say_the_plain_reason_and_keep_the_numbers_in_the_record(self):
        def decode_as_the_day_file(data, product, expected):
            if product is HOUR:
                return sw.decode_message(FakeMessage(parameterNumber=34), product, expected)
            return fake_decode(data, product, expected)
        frames, _files, states, _out = run_collect(self, bucket_with(), decode=decode_as_the_day_file)
        self.assertEqual(frames["hail_60"]["problem"], "NOAA's file covers the last 24 hours, not the last hour")
        self.assertEqual(states["hail_60"]["error"], "parameter 34 in folder MESH_Max_60min_00.50 (parameter 30 expected)")
        self.assertEqual(frames["hail_1440"]["state"], "fresh")

        def decode_other_time(data, product, expected):
            return sw.decode_message(FakeMessage(dataTime=159), product, expected)
        frames, _files, states, _out = run_collect(self, bucket_with(), decode=decode_other_time)
        problem = frames["hail_60"]["problem"]
        self.assertEqual(problem, "the file's time (Oct 18, 7:59 pm MDT) does not match the time in its name "
                                  "(Oct 18, 7:58 pm MDT)")
        self.assertPlain(problem)

    def test_a_decoder_error_gives_plain_words_and_keeps_its_reason_in_the_record(self):
        with self.assertRaises(sw.SwathError) as cm:
            sw.decode_message(BrokenMessage(), HOUR, VALID)
        self.assertEqual(str(cm.exception), "the file's values could not be read")
        self.assertEqual(cm.exception.detail, "unexpected error (RuntimeError)")

    def test_a_download_that_is_not_grib_reads_as_a_readable_radar_file(self):
        with self.assertRaises(sw.SwathError) as cm:
            sw.decode_bytes(b"not a grib file at all", HOUR, VALID)
        self.assertEqual(str(cm.exception), "NOAA's download was not a readable radar file")
        self.assertEqual(cm.exception.detail, "the download was not a GRIB file")

    def test_the_unavailable_lines_carry_no_exception_name_code_folder_or_utc(self):
        import requests
        lines = []
        for name in self.request_classes():
            def get(url, headers=None, exc=getattr(requests.exceptions, name)):
                raise exc()
            frames, _files, _states, _out = run_collect(self, get)
            lines += [frames[key]["state_line"] for key in ("hail_60", "hail_1440")]
        for overrides in ({"parameterNumber": 34}, {"parameterNumber": 7}, {"discipline": 2},
                          {"parameterCategory": 2}, {"dataTime": 159}, {"dataDate": 20261018}):
            with self.assertRaises(sw.SwathError) as cm:
                sw.decode_message(FakeMessage(**overrides), HOUR, VALID)
            lines.append(sw._unavailable(HOUR, str(cm.exception))["state_line"])
        with self.assertRaises(sw.SwathError) as cm:
            sw.decode_message(BrokenMessage(), HOUR, VALID)
        lines.append(sw._unavailable(HOUR, str(cm.exception))["state_line"])
        with self.assertRaises(sw.SwathError) as cm:
            sw.decode_bytes(b"not a grib file at all", HOUR, VALID)
        lines.append(sw._unavailable(HOUR, str(cm.exception))["state_line"])
        for line in lines:
            self.assertTrue(line.endswith(ALL_CLEAR), line)
            self.assertPlain(line)


class ProductTests(unittest.TestCase):
    def test_the_two_products_and_their_windows(self):
        self.assertEqual([(p.key, p.window, p.parameter, p.folder) for p in sw.PRODUCTS],
                         [("hail_60", 60, 30, "MESH_Max_60min_00.50"), ("hail_1440", 1440, 34, "MESH_Max_1440min_00.50")])
        self.assertEqual(sw.PARAMETER_WINDOW, {30: 60, 34: 1440})

    def test_the_style_has_254_levels_inside_the_256_palette_entries(self):
        stops, _log, n = g.STYLE[sw.STYLE]
        self.assertEqual((n, n + 2, stops[0][0], stops[-1][0]), (254, 256, 6.4, 110.0))


if __name__ == "__main__":
    unittest.main()
