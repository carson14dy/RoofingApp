"""Landmark points (B6 P3): the name and position rules, the FAA airport lines (the columns, the public-use and operational
filter, the Montana records), the NCES, USGS, FEMA and PAD-US readers on the small real samples, the TIGER park reader (with
pyshp; skipped when it is absent), the polygon label point (the pole search, checked against the containment test), the
park merge and the same-name rule, the cache and the failures (a source that cannot be read, a count below its floor, a
hospital layer with no rows that hands over to the HIFLD copy, an unavailable block, the unavailable command), the shard
files (format, tile, sort order, held kinds never written, the gzip budget, determinism, the second run from the cache),
the verify checks, the manifest check, and the words against the shared list. Offline: the build reads the fixtures from a
primed cache folder (tests/fixtures/landmarks), and the request code is tested with fake sessions."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from website import hail
from website import landmarks as L

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the one forbidden list)
import words_rules as W  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "landmarks"
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
try:
    import shapefile                 # noqa: F401  (pyshp: the TIGER reader and the fixture writer)
    HAVE_SHAPEFILE = True
except ImportError:
    HAVE_SHAPEFILE = False
ALL_FLOORS = {key: 1 for key in L.SOURCES}          # the samples are a few rows; the real floors are tested on their own


def sample() -> dict:
    return json.loads((FIXTURES / "sources_sample.json").read_text(encoding="utf-8"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prime(cache: Path, data: dict, skip=()) -> None:
    """Writes the fixture responses into a cache folder with the module's own file names, so an offline build reads them."""
    for key, spec in L.SOURCES.items():
        if key in skip or key not in data["pages"]:
            continue
        folder = cache / key
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(json.dumps(data["meta"][key]), encoding="utf-8")
        page_folder = folder / L._query_key(spec)
        page_folder.mkdir(parents=True, exist_ok=True)
        (page_folder / "p000.json").write_text(json.dumps(data["pages"][key]), encoding="utf-8")
    if "faa_nasr" not in skip:
        faa_dir = cache / "faa_nasr"
        faa_dir.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("APT.txt", (FIXTURES / "faa_apt_mt_sample.txt").read_bytes())
        (faa_dir / "APT_2026-10-01.zip").write_bytes(buf.getvalue())
    if "tiger_park" not in skip:
        tiger_dir = cache / "tiger_park"
        tiger_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / "tiger_arealm_mt_sample.zip", tiger_dir / "tl_2026_30_arealm.zip")


def montana_tiles() -> set:
    """The B1 tiles that cover the Montana box, on a 0.1 degree grid (the tile list the store would hold)."""
    tiles = set()
    lat = 44.3
    while lat <= 49.1:
        lon = -116.2
        while lon <= -103.9:
            r, c = hail.cell_for(lat, lon)
            tiles.add(hail.tile_name(r // hail.TILE, c // hail.TILE))
            lon += 0.05
        lat += 0.05
    return tiles


def make_store(root: Path) -> Path:
    """A minimal hail store: the index (the grid and the tile list) and a manifest that lists it, which is all the part reads."""
    store = root / "store"
    (store / "hail").mkdir(parents=True)
    index = {"format": hail.FORMAT, "d0": hail.D0.isoformat(), "grid": dict(hail.GRID), "as_of": "2026-10-16",
             "window": ["2021-10-17", "2026-10-16"], "missing_days": [], "floor_tenths": 64,
             "tiles": sorted(montana_tiles())}
    data = json.dumps(index, indent=1).encode("utf-8")
    (store / "hail" / "index.json").write_bytes(data)
    manifest = {"format": hail.MANIFEST_FORMAT, "as_of": "2026-10-16", "counts": {},
                "files": {"hail/index.json": {"bytes": len(data), "sha256": _sha(data)}}}
    (store / "hail" / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return store


class FakeResponse:
    def __init__(self, status, body=b""):
        self.status_code = status
        self.content = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Answers each get() with the next outcome: a (status, body) pair, or an exception to raise."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, timeout=None, allow_redirects=True):
        self.calls.append(url)
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(*item)


class NamesAndCyclesTests(unittest.TestCase):
    def test_all_capital_names_are_title_cased_and_placeholders_dropped(self):
        self.assertEqual(L.clean_name("LOYOLA SACRED HEART HIGH SCHOOL"), "Loyola Sacred Heart High School")
        self.assertEqual(L.clean_name("Hellgate High School"), "Hellgate High School")
        self.assertIsNone(L.clean_name("Unknown Park"))
        self.assertIsNone(L.clean_name("N/A"))
        self.assertIsNone(L.clean_name("   "))
        self.assertIsNone(L.clean_name(None))

    def test_an_airport_gets_its_airport_word_and_its_abbreviations_are_written_out(self):
        self.assertEqual(L.airport_name("MISSOULA MONTANA"), "Missoula Montana Airport")
        self.assertEqual(L.airport_name("BILLINGS LOGAN INTL"), "Billings Logan International Airport")
        self.assertEqual(L.airport_name("LEWISTOWN MUNI FLD"), "Lewistown Municipal Field")

    def test_the_faa_cycle_in_force_is_28_days_from_the_anchor(self):
        from datetime import date
        self.assertEqual(L.faa_cycle(date(2026, 10, 1)), date(2026, 10, 1))
        self.assertEqual(L.faa_cycle(date(2026, 10, 25)), date(2026, 10, 1))
        self.assertEqual(L.faa_cycle(date(2026, 10, 29)), date(2026, 10, 29))
        self.assertEqual(L.faa_cycle(date(2026, 11, 25)), date(2026, 10, 29))
        self.assertEqual(L.faa_cycle(date(2026, 9, 30)), date(2026, 9, 3))

    def test_degrees_minutes_seconds_with_the_hemisphere_letter(self):
        self.assertAlmostEqual(L.dms_value("46-54-58.7000N ", "lat"), 46.9163055, places=6)
        self.assertAlmostEqual(L.dms_value("114-05-26.0000W", "lon"), -114.0905556, places=6)
        self.assertAlmostEqual(L.dms_value("12-00-00S", "lat"), -12.0)
        self.assertIsNone(L.dms_value("46-54-58.7000W", "lat"))       # a longitude letter on a latitude
        self.assertIsNone(L.dms_value("", "lat"))

    def test_a_tile_is_the_b1_tile_that_holds_the_position(self):
        # the Loyola Sacred Heart High School position, and the Missoula airport
        self.assertEqual(L._tile_of(-114.00214, 46.86217), "r0081_c0159")
        self.assertEqual(L._tile_of(-114.09056, 46.91631), "r0080_c0159")
        r, c = hail.cell_for(46.86217, -114.00214)
        self.assertEqual(L._tile_of(-114.00214, 46.86217), hail.tile_name(r // hail.TILE, c // hail.TILE))


class ReaderTests(unittest.TestCase):
    def test_the_faa_lines_keep_only_public_operational_airports_in_montana(self):
        text = (FIXTURES / "faa_apt_mt_sample.txt").read_text(encoding="latin-1")
        rows, drops, counts = L.parse_faa_lines(text.splitlines())
        self.assertEqual(counts["apt records"], 4)
        self.assertEqual(counts["montana records"], 4)
        self.assertEqual([r[1] for r in rows], ["Missoula Montana Airport"])
        self.assertEqual(rows[0][0], "airport")
        self.assertAlmostEqual(rows[0][2], -114.09056, places=5)
        self.assertAlmostEqual(rows[0][3], 46.91631, places=5)
        self.assertEqual(rows[0][4], "faa_nasr")
        self.assertEqual(sum(drops.values()), 3)
        self.assertEqual(drops["not an airport (facility type)"], 1)

    def test_a_line_that_is_not_a_montana_airport_record_is_not_read(self):
        text = (FIXTURES / "faa_apt_mt_sample.txt").read_text(encoding="latin-1")
        other = "APT" + text.splitlines()[0][3:48] + "WY" + text.splitlines()[0][50:]
        rows, drops, counts = L.parse_faa_lines([other])
        self.assertEqual(rows, [])
        self.assertEqual(counts["apt records"], 1)
        self.assertEqual(counts["montana records"], 0)

    def test_point_sources_drop_placeholders_and_missing_positions(self):
        data = sample()
        feats = data["pages"]["nces_public"]["features"]
        rows, drops = L.points_from(feats, "school", "nces_public", name_key="NAME",
                                    coords=L.attr_coords("LON", "LAT"))
        names = [r[1] for r in rows]
        self.assertIn("Hellgate High School", names)
        self.assertNotIn("Unknown School", names)
        self.assertEqual(drops["no name or placeholder name"], 1)
        self.assertEqual(drops["no position or outside Montana"], 1)

    def test_a_worship_row_must_be_a_point_address_match_in_montana(self):
        feats = sample()["pages"]["fema_worship"]["features"]
        rows, drops = L.points_from(feats, "church", "fema_worship", name_key="NAME", coords=L.attr_coords("X", "Y"),
                                    keep=L._fema_keep)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "St Paul Lutheran Church of Missoula")
        self.assertEqual(drops["not a point-address match"], 1)

    def test_a_hospital_row_takes_its_position_from_the_geometry(self):
        feats = sample()["pages"]["usgs_hospitals"]["features"]
        rows, _ = L.points_from(feats, "hospital", "usgs_hospitals", name_key="NAME", coords=L.geometry_coords)
        self.assertEqual(sorted(r[1] for r in rows), ["Community Medical Center", "Saint Patrick Hospital"])
        saint = next(r for r in rows if r[1] == "Saint Patrick Hospital")
        self.assertAlmostEqual(saint[2], -114.00002, places=5)
        self.assertAlmostEqual(saint[3], 46.87514, places=5)

    def test_the_same_name_at_the_same_place_is_one_row(self):
        rows = [("school", "A School", -114.0, 46.8, "nces_public"), ("school", "a school", -114.0, 46.8, "nces_public"),
                ("school", "B School", -114.0, 46.8, "nces_public")]
        kept, dropped = L.dedupe(rows)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, 1)

    def test_a_park_polygon_gets_its_name_and_a_label_point_inside_it(self):
        polys, drops = L.polygons_from(sample()["pages"]["padus_local"]["features"])
        self.assertEqual([p["name"] for p in polys], ["Rose Garden"])
        self.assertEqual(drops["no name or placeholder name"], 1)
        lon, lat = polys[0]["pos"]
        self.assertTrue(L.point_in_rings(lon, lat, polys[0]["rings"]))
        self.assertLess(abs(lon + 114.00521), 0.0005)

    @unittest.skipUnless(HAVE_SHAPEFILE, "pyshp is not installed (the TIGER reader is skipped)")
    def test_the_tiger_park_reader_keeps_named_park_codes_in_montana(self):
        rows, drops, count = L.read_tiger((FIXTURES / "tiger_arealm_mt_sample.zip").read_bytes())
        self.assertEqual(count, 6)
        self.assertEqual(sorted(r[1] for r in rows), ["Dickerson Park", "Lange Park", "Rose Park"])
        self.assertTrue(all(r[0] == "park" and r[4] == "tiger_park" for r in rows))
        self.assertEqual(drops["no name or placeholder name"], 1)
        self.assertEqual(drops["not Montana"], 1)
        rose = next(r for r in rows if r[1] == "Rose Park")
        self.assertAlmostEqual(rose[2], -114.00523, places=5)

    @unittest.skipUnless(HAVE_SHAPEFILE, "pyshp is not installed")
    def test_a_park_file_without_the_interior_point_fields_is_a_failure(self):
        base = Path(tempfile.mkdtemp(prefix="lm-tiger-"))
        try:
            w = shapefile.Writer(str(base / "x"), shapeType=shapefile.NULL)
            w.field("STATEFP", "C", 2)
            w.field("MTFCC", "C", 5)
            w.field("FULLNAME", "C", 40)
            w.null()
            w.record("30", "K2180", "Nope Park")
            w.close()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for ext in (".shp", ".shx", ".dbf"):
                    z.write(str(base / ("x" + ext)), "x" + ext)
            with self.assertRaises(L.SourceFailure) as ctx:
                L.read_tiger(buf.getvalue())
            self.assertIn("INTPTLAT", str(ctx.exception))
        finally:
            shutil.rmtree(base)


class GeometryTests(unittest.TestCase):
    def test_the_pole_of_a_square_is_its_centre(self):
        x, y = L.pole_of_inaccessibility([[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]])
        self.assertAlmostEqual(x, 5.0, places=3)
        self.assertAlmostEqual(y, 5.0, places=3)

    def test_the_pole_of_a_donut_is_in_the_ring_not_the_hole(self):
        outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        hole = [(2, 2), (8, 2), (8, 8), (2, 8), (2, 2)]
        x, y = L.pole_of_inaccessibility([outer, hole])
        self.assertTrue(L.point_in_rings(x, y, [outer, hole]))
        self.assertFalse(L.point_in_rings(x, y, [hole]))

    def test_the_pole_of_an_l_shape_is_inside_it(self):
        ring = [(0, 0), (10, 0), (10, 2), (2, 2), (2, 10), (0, 10), (0, 0)]
        x, y = L.pole_of_inaccessibility([ring])
        self.assertTrue(L.point_in_rings(x, y, [ring]))

    def test_a_park_that_holds_a_named_tiger_point_is_one_park(self):
        polys, _ = L.polygons_from(sample()["pages"]["padus_local"]["features"])
        tiger = [("park", "Rose Park", -114.00523, 46.85674, "tiger_park"),
                 ("park", "Far Park", -113.90, 46.90, "tiger_park")]
        pad_rows, kept, merged = L.merge_parks(polys, tiger)
        self.assertEqual(merged, 1)
        self.assertEqual([r[1] for r in kept], ["Far Park"])
        self.assertEqual([r[1] for r in pad_rows], ["Rose Garden"])

    def test_two_pieces_of_one_park_with_the_same_name_are_one_park(self):
        rows = [("park", "Scotty Park", -114.05544, 46.80875, "padus_local"),
                ("park", "Scotty Park", -114.05543, 46.80874, "padus_local"),
                ("park", "Scotty Park", -113.80000, 46.80000, "padus_local")]
        kept, dropped = L.dedupe_parks(rows)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, 1)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lm-fetch-"))
        self.sleeps = []

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fetch(self, outcomes, **kwargs):
        session = FakeSession(outcomes)
        fetch = L.Fetch(self.tmp / "cache", session=session, sleep=self.sleeps.append, **kwargs)
        return fetch, session

    def test_a_server_error_is_tried_again_and_then_answers(self):
        fetch, session = self.fetch([(503, b""), (200, b'{"ok": true}')])
        body = fetch.get("https://example.test/a", "the test list")
        self.assertEqual(body, b'{"ok": true}')
        self.assertEqual(len(session.calls), 2)
        self.assertIn(2.0, self.sleeps)     # the wait before the second try (pacing waits are also recorded)

    def test_a_client_error_fails_at_once(self):
        fetch, session = self.fetch([(404, b"")])
        with self.assertRaises(L.SourceFailure) as ctx:
            fetch.get("https://example.test/b", "the test list")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertEqual(len(session.calls), 1)

    def test_a_dropped_connection_fails_after_three_tries(self):
        fetch, session = self.fetch([ConnectionError("reset"), ConnectionError("reset"), ConnectionError("reset")])
        with self.assertRaises(L.SourceFailure) as ctx:
            fetch.get("https://example.test/c", "the test list")
        self.assertIn("ConnectionError", str(ctx.exception))
        self.assertEqual(len(session.calls), 3)

    def test_the_offline_run_makes_no_request_for_a_missing_file(self):
        fetch, session = self.fetch([], offline=True)
        with self.assertRaises(L.SourceFailure) as ctx:
            fetch.file(self.tmp / "cache" / "nope.json", "https://example.test/d", "the missing file")
        self.assertIn("makes no request", str(ctx.exception))
        self.assertEqual(session.calls, [])

    def test_a_cached_file_is_read_without_a_request(self):
        path = self.tmp / "cache" / "x.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"{}")
        fetch, session = self.fetch([])
        self.assertEqual(fetch.file(path, "https://example.test/e", "x"), b"{}")
        self.assertEqual(session.calls, [])
        self.assertEqual(fetch.hits, 1)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-build-"))
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())

    def tearDown(self):
        shutil.rmtree(self.root)

    def build(self, **kwargs):
        options = dict(now=NOW, offline=True, floors=ALL_FLOORS)
        options.update(kwargs)
        return L.build(self.store, self.cache, **options)

    def shards(self) -> dict:
        out = {}
        for path in sorted((self.store / "hail" / "base" / "p").glob("*.json")):
            out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        return out

    def block(self) -> dict:
        return json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))[L.INDEX_KEY]

    def all_rows(self) -> list:
        return [(tile, row) for tile, doc in self.shards().items() for row in doc["i"]]

    def test_the_build_writes_the_shards_the_block_and_the_manifest(self):
        summary = self.build()
        self.assertEqual(summary["state"], "loaded")
        self.assertEqual(summary["requests"], 0)
        shards = self.shards()
        self.assertTrue(shards)
        for tile, doc in shards.items():
            self.assertEqual(doc["f"], L.FORMAT)
            self.assertEqual(doc["t"], tile)
            self.assertEqual(doc["n"], len(doc["i"]))
        block = self.block()
        self.assertEqual(block["state"], "loaded")
        self.assertEqual(block["counts"]["points"], sum(d["n"] for d in shards.values()))
        self.assertEqual(sorted(block["tiles"]), sorted(shards))
        self.assertEqual(block["budget"]["within"], True)

    def test_the_missoula_points_are_in_the_shards(self):
        self.build()
        names = {(row[2], L._norm_name(row[3])) for _, row in self.all_rows()
                 if L.MISSOULA_BOX[0] <= row[0] <= L.MISSOULA_BOX[2] and L.MISSOULA_BOX[1] <= row[1] <= L.MISSOULA_BOX[3]}
        for kind, name in L.MISSOULA_CHECK:
            self.assertIn((L.KIND_CODE[kind], L._norm_name(name)), names, name)

    def test_a_held_kind_is_built_and_counted_but_never_written(self):
        self.build()
        codes = {row[2] for _, row in self.all_rows()}
        self.assertNotIn("c", codes)
        held = self.block()["held"]["church"]
        self.assertTrue(held["held"])
        self.assertEqual(held["rows"], 1)
        self.assertEqual(self.block()["kinds"]["church"]["state"], "held")

    def test_the_shard_rows_are_sorted_by_kind_then_name(self):
        self.build()
        for doc in self.shards().values():
            keys = [(row[2], row[3].casefold()) for row in doc["i"]]
            self.assertEqual(keys, sorted(keys))

    def test_a_shard_is_under_the_gzip_budget(self):
        self.build()
        for tile, doc in self.shards().items():
            data = (self.store / "hail" / "base" / "p" / f"{tile}.json").read_bytes()
            self.assertLess(L._gzip_size(data), L.BUDGET_GZIP, tile)

    def test_verify_and_the_manifest_check_pass_on_the_built_store(self):
        self.build()
        result = L.verify(self.store)
        self.assertTrue(result["ok"], [c for c in result["checks"] if not c["pass"]])
        hail.check_manifest(self.store)

    def test_a_second_build_gives_the_same_shard_bytes(self):
        self.build()
        first = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.store / "hail" / "base" / "p").glob("*.json")}
        self.build()
        second = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.store / "hail" / "base" / "p").glob("*.json")}
        self.assertEqual(first, second)

    def test_a_source_that_cannot_be_read_makes_its_kind_unavailable(self):
        prime(self.cache, sample(), skip=("nces_private",))
        shutil.rmtree(self.cache / "nces_private", ignore_errors=True)
        summary = self.build()
        self.assertEqual(summary["state"], "partial")
        block = self.block()
        self.assertEqual(block["kinds"]["school"]["state"], "unavailable")
        self.assertIn("Data unavailable: schools could not be loaded in this update; that is not the same as no schools. "
                      "This is not an all-clear.", block["problem"])
        self.assertNotIn("s", {row[2] for _, row in self.all_rows()})
        self.assertEqual(block["sources"]["nces_private"]["state"], "unavailable")
        self.assertTrue(L.verify(self.store)["ok"])

    def test_a_count_below_the_floor_is_a_failure_of_that_source(self):
        floors = dict(ALL_FLOORS, nces_public=10_000)
        summary = self.build(floors=floors)
        self.assertEqual(self.block()["kinds"]["school"]["state"], "unavailable")
        self.assertEqual(summary["state"], "partial")

    def test_a_hospital_layer_with_no_rows_hands_over_to_the_hifld_copy(self):
        empty = {"features": [], "exceededTransferLimit": False}
        data = sample()
        data["pages"]["usgs_hospitals"] = empty
        prime(self.cache, data)
        self.build()
        block = self.block()
        self.assertEqual(block["hospital_source"]["used"], "hifld_hospitals")
        self.assertIn("state licensure list", block["hospital_source"]["why"])
        names = {row[3] for _, row in self.all_rows() if row[2] == "h"}
        self.assertEqual(names, {"St Patrick Hospital", "Community Medical Center"})
        self.assertEqual(block["sources"]["usgs_hospitals"]["state"], "loaded")

    def test_a_hospital_layer_that_cannot_be_read_is_not_replaced_by_the_hifld_copy(self):
        prime(self.cache, sample(), skip=("usgs_hospitals",))
        shutil.rmtree(self.cache / "usgs_hospitals", ignore_errors=True)
        self.build()
        block = self.block()
        self.assertIsNone(block["hospital_source"]["used"])
        self.assertEqual(block["kinds"]["hospital"]["state"], "unavailable")
        self.assertNotIn("h", {row[2] for _, row in self.all_rows()})

    def test_no_source_at_all_leaves_the_block_unavailable_and_no_shards(self):
        empty_cache = self.root / "empty-cache"
        summary = L.build(self.store, empty_cache, now=NOW, offline=True, floors=ALL_FLOORS)
        self.assertEqual(summary["state"], "unavailable")
        self.assertFalse((self.store / "hail" / "base" / "p").exists())
        result = L.verify(self.store)
        self.assertTrue(result["ok"])
        self.assertIn("Data unavailable: landmarks could not be loaded", result["note"])

    def test_the_unavailable_command_keeps_the_other_parts_keys(self):
        self.build()
        base_path = self.store / "hail" / "base" / "index.json"
        base = json.loads(base_path.read_text(encoding="utf-8"))
        base["other_part"] = {"state": "loaded"}
        base_path.write_text(json.dumps(base), encoding="utf-8")
        L.mark_unavailable(self.store, "the test failed")
        after = json.loads(base_path.read_text(encoding="utf-8"))
        self.assertEqual(after["other_part"], {"state": "loaded"})
        self.assertEqual(after[L.INDEX_KEY]["state"], "unavailable")
        self.assertIn("the test failed", after[L.INDEX_KEY]["detail"])
        self.assertFalse((self.store / "hail" / "base" / "p").exists())
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse([k for k in manifest["files"] if k.startswith(L.P_PREFIX)])
        hail.check_manifest(self.store)

    def test_the_unavailable_command_needs_a_reason(self):
        with self.assertRaises(L.LandmarkError):
            L.mark_unavailable(self.store, "   ")

    def test_map_data_names_the_unavailable_kind_and_the_held_kind(self):
        prime(self.cache, sample(), skip=("nces_private",))
        shutil.rmtree(self.cache / "nces_private", ignore_errors=True)
        self.build()
        index = json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))
        data = L.map_data_landmarks(index)
        self.assertEqual(data["shard"], "hail/base/p/{name}.json")
        self.assertEqual(data["kinds"]["school"]["state"], "unavailable")
        self.assertIn("Data unavailable", data["kinds"]["school"]["problem"])
        self.assertIn("not shown", data["kinds"]["church"]["problem"])
        self.assertTrue(data["kinds"]["church"]["held"])
        about = L.describe_landmarks(index)
        self.assertTrue(about["sources"])
        self.assertTrue(all("Data unavailable" not in s for s in about["sources"]))

    def test_the_rows_of_one_point_are_read_from_the_source_list_and_nothing_else(self):
        self.build()
        for _, row in self.all_rows():
            self.assertEqual(len(row), 5)
            self.assertIn(row[4], L.SOURCES)


class WordsTests(unittest.TestCase):
    def test_the_words_pass_the_shared_forbidden_list(self):
        texts = list(L.WORDS.values())
        for text in texts:
            W.assert_clean(self, text, text[:40])

    def test_the_unavailable_sentence_keeps_its_required_words(self):
        text = L.WORDS["kind_unavailable"].format(plural="schools")
        self.assertTrue(text.startswith("Data unavailable:"))
        self.assertTrue(text.endswith("This is not an all-clear."))
        self.assertEqual(W.forbidden_words(text), [])

    def test_no_em_dash_is_in_the_module(self):
        source = (Path(__file__).resolve().parent.parent / "website" / "landmarks.py").read_text(encoding="utf-8")
        self.assertNotIn("—", source)


if __name__ == "__main__":
    unittest.main()
