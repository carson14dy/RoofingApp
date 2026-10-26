"""Landmark points (B6 P3): the name and position rules, the FAA airport lines (the columns, the public-use and operational
filter, the Montana records), the NCES, USGS, FEMA and PAD-US readers on the small real samples, the TIGER park reader (with
pyshp; skipped when it is absent), the polygon label point (the pole search, checked against the containment test), the
park merge and the same-name rule, the cache and the failures (a source that cannot be read, a count below its floor, a
hospital layer with no rows that hands over to the HIFLD copy, an unavailable block, the unavailable command), the shard
files (format, tile, sort order, held kinds never written, the gzip budget, determinism, the second run from the cache),
the verify checks, the manifest check, and the words against the shared list. B6 rulings pass (D112 to D118): the held Census
park list and church list (null counts, the summary figures, the alternate names), the shared base index format, the owner's
display names, the credit lines, the cache cycles, the bytes of a source, and the fixtures without contact text.
B6 integration fixes (D128(e), D132(b) to (d)): this module's block is mirrored into hail/index.json's "base" block under its own
key, and the unavailable command mirrors its block (HailIndexMirrorTests); a held source publishes its reason alone as its terms,
so no licence sentence of a held source reaches the index, the mirror or the map data (HeldTermsTests); the held church kind has
one reason sentence in the words, the index, the mirror, the map data and the About words (HeldKindSentenceTests).
The TIGER park fixture (tiger_arealm_mt_sample.zip) is synthetic (D132(c)): made-up park names (the word Synthetic, or a blank
name on purpose), positions inside Montana, and the Census field layout (STATEFP, MTFCC, FULLNAME, INTPTLAT, INTPTLON). It holds
no row of the held Census file, and FixtureTests.test_the_tiger_fixture_is_synthetic checks that.
Offline: the build reads the fixtures from a primed cache folder (tests/fixtures/landmarks), and the request code is tested
with fake sessions."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from website import hail
from website import landmarks as L
from website import sources as src

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
needs_shapefile = unittest.skipUnless(HAVE_SHAPEFILE, "pyshp is not installed (the park source needs its reader)")
# The synthetic TIGER park fixture (D132(c)), as the reader gives its names: the Garden park merges with the PAD-US Rose Garden
# (its position is 13 m from the Rose Garden label point), and the two kept parks stay as points.
TIGER_GARDEN = "Synthetic Garden Park"
TIGER_GARDEN_POSITION = (-114.00528, 46.85665)            # lon, lat (rounded to five decimals by the reader)
TIGER_KEPT = ("Synthetic Aspen Park", "Synthetic Cedar Park")


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
        (folder / f"meta-{L._meta_key(spec)}.json").write_text(json.dumps(data["meta"][key]), encoding="utf-8")
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


def meta_path(cache: Path, key: str) -> Path:
    """The cache file of a layer description (named by the layer URL, P3-R7)."""
    return cache / key / f"meta-{L._meta_key(L.SOURCES[key])}.json"


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


def faa_zip(member: str = "APT.txt", text: bytes | None = None) -> bytes:
    """An APT zip with one member (the fixture's airport lines by default)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, text if text is not None else (FIXTURES / "faa_apt_mt_sample.txt").read_bytes())
    return buf.getvalue()


class RouterSession:
    """Answers each request with answer(url) -> (status, body), and records the URLs asked for."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def get(self, url, timeout=None, allow_redirects=True):
        self.calls.append(url)
        status, body = self.answer(url)
        return FakeResponse(status, body)


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

    def test_the_airport_abbreviations_are_written_out_and_usfs_stays_an_acronym(self):
        self.assertEqual(L.airport_name("WOKAL FLD/GLASGOW-VALLEY COUNTY AIRPORT"), "Wokal Field/Glasgow-Valley County Airport")
        self.assertEqual(L.airport_name("WOLTERMANN MEML AIRPORT"), "Woltermann Memorial Airport")
        self.assertEqual(L.airport_name("CONDON USFS AIRPORT"), "Condon USFS Airport")
        self.assertEqual(L.airport_name("BIG TIMBER AT HOWARD FIELD"), "Big Timber at Howard Field")
        self.assertEqual(L.clean_name("SCHAFER /USFS/ AIRPORT"), "Schafer /USFS/ Airport")

    def test_the_fire_kind_is_labelled_fire_and_ems_stations(self):
        self.assertEqual(L.KIND_LABEL["fire"], "Fire and EMS stations")
        self.assertEqual(L.KIND_PLURAL["fire"], "fire and EMS stations")


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
        """The synthetic fixture (D132(c)): six records. The capitals name is title-cased; one record is blank, one is a state
        park code (P2, not a point here), one is another state's code, and the other three are park points."""
        rows, drops, count = L.read_tiger((FIXTURES / "tiger_arealm_mt_sample.zip").read_bytes())
        self.assertEqual(count, 6)
        self.assertEqual(sorted(r[1] for r in rows), sorted((TIGER_GARDEN,) + TIGER_KEPT))
        self.assertTrue(all(r[0] == "park" and r[4] == "tiger_park" for r in rows))
        self.assertEqual(drops["no name or placeholder name"], 1)
        self.assertEqual(drops["not Montana"], 1)
        garden = next(r for r in rows if r[1] == TIGER_GARDEN)
        self.assertAlmostEqual(garden[2], TIGER_GARDEN_POSITION[0], places=5)
        self.assertAlmostEqual(garden[3], TIGER_GARDEN_POSITION[1], places=5)
        self.assertTrue(all(L._position(r[2], r[3]) is not None for r in rows))

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


class FixtureTests(unittest.TestCase):
    """B6 P3-R1 and D120(e): the fixtures hold no owner, address, phone, manager or contact text. The FAA file keeps only the
    columns the module reads (the eight spans in KEPT, which test_the_faa_parser_reads_exactly_the_kept_columns checks against
    parse_faa_lines); every other column is blank, with spaces of the same width, so the fixed-width offsets hold."""

    KEPT = ((1, 3), (15, 27), (49, 50), (134, 183), (186, 187), (524, 538), (551, 565), (841, 842))
    CONTACT_WORDS = ("OWNER", "MANAGER", "PHONE", "CONTACT", "EMAIL")
    MODULE_COLUMN_WORDS = frozenset()      # no column the module reads has one of these words in its name

    def faa_records(self):
        lines = (FIXTURES / "faa_apt_mt_sample.txt").read_bytes().decode("latin-1").split("\r\n")
        return [(number, line) for number, line in enumerate(lines, 1) if line]

    def test_the_faa_file_keeps_only_the_columns_the_module_reads(self):
        records = self.faa_records()
        self.assertEqual(len(records), 4)
        kept = {i for start, end in self.KEPT for i in range(start - 1, end)}
        for number, line in records:
            self.assertEqual(len(line), 1531, f"line {number}: the fixed width holds")
            outside = [i + 1 for i in range(len(line)) if i not in kept and line[i] != " "]
            self.assertEqual(outside, [], f"line {number}: text outside the kept columns, from column {outside[:5]}")

    def test_the_faa_parser_reads_exactly_the_kept_columns(self):
        """D120(e): the kept spans are the columns parse_faa_lines reads. Writing X over every column outside KEPT leaves the
        parse unchanged, and writing X over each kept span changes it, so no read column is missing from KEPT and no other
        column is read."""
        records = [line for _, line in self.faa_records()]
        base = L.parse_faa_lines(records)
        kept = {i for start, end in self.KEPT for i in range(start - 1, end)}

        def with_x(line, columns):
            return "".join("X" if i in columns else ch for i, ch in enumerate(line))

        other = set(range(1531)) - kept
        self.assertEqual(L.parse_faa_lines([with_x(line, other) for line in records]), base,
                         "the parse changed when a column outside KEPT was written over")
        for start, end in self.KEPT:
            columns = set(range(start - 1, end))
            changed = L.parse_faa_lines([with_x(line, columns) for line in records])
            self.assertNotEqual(changed, base, f"columns {start} to {end} are not read by the parser")

    def test_the_faa_fixture_holds_no_owner_manager_or_phone_text(self):
        """The owner, address, phone and manager columns (1-based 188 to 523) are blank on every record, and no line has a
        phone number or one of the contact words. The fixture carries no column names, so the words are looked for on every
        line."""
        for number, line in self.faa_records():
            self.assertEqual(line[187:523].strip(), "", f"line {number}: the owner or manager columns are not blank")
            self.assertIsNone(re.search(r"\d{3}-\d{3}-\d{4}", line), f"line {number}: a phone number")
            self.assertEqual(re.findall(r"\b(?:OWNER|MANAGER|PHONE|CONTACT|EMAIL)\b", line, re.IGNORECASE), [], f"line {number}")

    def test_no_fixture_holds_a_phone_number_or_a_contact_word(self):
        """No fixture file (the text files, the JSON samples, and each member of the TIGER zip) matches a phone pattern or the
        words OWNER, MANAGER, PHONE, CONTACT or EMAIL, outside the module's own column names (none)."""
        words = re.compile(r"\b(?:%s)\b" % "|".join(w for w in self.CONTACT_WORDS if w not in self.MODULE_COLUMN_WORDS),
                           re.IGNORECASE)
        for path in sorted(FIXTURES.iterdir()):
            if path.suffix == ".zip":
                with zipfile.ZipFile(path) as z:
                    parts = [(f"{path.name}:{name}", z.read(name)) for name in z.namelist()]
            else:
                parts = [(path.name, path.read_bytes())]
            for label, data in parts:
                text = data.decode("latin-1")
                with self.subTest(fixture=label):
                    self.assertIsNone(re.search(r"\d{3}-\d{3}-\d{4}", text), "a phone number")
                    self.assertEqual(words.findall(text), [], "a contact word")

    @needs_shapefile
    def test_the_tiger_fixture_is_synthetic(self):
        """D132(c): the TIGER park fixture is made up. The zip is small, it holds the three shapefile parts and the five Census
        fields the reader needs (and no other field), every name is made up (the word Synthetic, or blank on purpose), and every
        position is inside Montana."""
        path = FIXTURES / "tiger_arealm_mt_sample.zip"
        self.assertLess(path.stat().st_size, 20_000)
        with zipfile.ZipFile(path) as z:
            parts = {Path(name).suffix.lower(): io.BytesIO(z.read(name)) for name in z.namelist() if not name.endswith("/")}
        self.assertEqual(sorted(parts), [".dbf", ".shp", ".shx"])
        reader = shapefile.Reader(shp=parts[".shp"], dbf=parts[".dbf"], shx=parts[".shx"])
        self.assertEqual([f[0] for f in reader.fields[1:]], ["STATEFP", "MTFCC", "FULLNAME", "INTPTLAT", "INTPTLON"])
        records = [rec.as_dict() for rec in reader.iterRecords()]
        self.assertEqual(len(records), 6)
        for rec in records:
            name = str(rec.get("FULLNAME") or "").strip()
            self.assertTrue(name == "" or name.lower().startswith("synthetic"), name)
            self.assertIsNotNone(L._position(float(str(rec["INTPTLON"]).strip()), float(str(rec["INTPTLAT"]).strip())))

    def test_the_sample_json_keeps_only_names_positions_status_state_and_kind_codes(self):
        """The JSON sample holds only attributes the module reads: names, positions, status, state, kind codes and the
        object ids the layers page by (checked against the reader's own field lists)."""
        data = sample()
        read = {"NAME", "LAT", "LON", "STFIP", "name", "X", "Y", "LOC_NAME", "STATE", "STATUS", "LATITUDE", "LONGITUDE",
                "Unit_Nm", "Des_Tp", "State_Nm", "OBJECTID", "FID"}
        for key, page in data["pages"].items():
            for feature in page.get("features", []):
                self.assertLessEqual(set(feature.get("attributes", {})), read, key)
        for key, meta in data["meta"].items():
            self.assertLessEqual({f["name"] for f in meta["fields"]}, read, key)


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
        tiger = [("park", TIGER_GARDEN, TIGER_GARDEN_POSITION[0], TIGER_GARDEN_POSITION[1], "tiger_park"),
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

    def test_a_body_that_does_not_parse_is_not_cached_and_the_next_request_asks_again(self):
        path = self.tmp / "cache" / "list.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        fetch, session = self.fetch([(200, b'{"error": {"message": "boom"}}'), (200, b'{"features": []}')])
        parse = lambda raw: L._page_doc(raw, "test")                                # noqa: E731
        with self.assertRaises(L.SourceFailure):
            fetch.file(path, "https://example.test/f", "the test list", parse=parse)
        self.assertFalse(path.exists())
        self.assertEqual(fetch.file(path, "https://example.test/f", "the test list", parse=parse), {"features": []})
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(path.exists())

    def test_under_refresh_a_failed_request_keeps_the_cached_copy(self):
        path = self.tmp / "cache" / "list.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"features": [1]}')
        fetch, session = self.fetch([(503, b"")] * 3, refresh=True)
        parse = lambda raw: L._page_doc(raw, "test")                                # noqa: E731
        self.assertEqual(fetch.file(path, "https://example.test/g", "the test list", parse=parse), {"features": [1]})
        self.assertEqual(path.read_bytes(), b'{"features": [1]}')
        self.assertEqual(len(session.calls), 3)

    def test_a_cached_copy_that_does_not_parse_is_removed_and_the_offline_run_says_so(self):
        path = self.tmp / "cache" / "list.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"other": 1}')
        fetch, session = self.fetch([], offline=True)
        with self.assertRaises(L.SourceFailure) as ctx:
            fetch.file(path, "https://example.test/h", "the test list", parse=lambda raw: L._page_doc(raw, "test"))
        self.assertIn("not usable", str(ctx.exception))
        self.assertIn("makes no request", str(ctx.exception))
        self.assertFalse(path.exists())
        self.assertEqual(session.calls, [])


@needs_shapefile
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
        block = self.block()
        self.assertTrue(block["held"]["kinds"]["church"]["held"])
        self.assertEqual(block["held"]["kinds"]["church"]["reason"], L.HELD_KIND_REASONS["church"])
        self.assertEqual(block["kinds"]["church"]["state"], "held")
        self.assertIsNone(block["kinds"]["church"]["count"])
        self.assertEqual(self.build()["held"]["church_rows"], 1)    # the figure is in the summary (report.md), not the index

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

    def index(self) -> dict:
        return json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))

    def test_an_unavailable_kind_has_a_null_count_and_the_map_data_leaves_it_out(self):
        prime(self.cache, sample(), skip=("nces_private",))
        shutil.rmtree(self.cache / "nces_private", ignore_errors=True)
        self.build()
        block = self.block()
        self.assertIsNone(block["kinds"]["school"]["count"])
        self.assertIsNone(block["counts"]["kinds"]["school"])
        counts = L.map_data_landmarks(self.index())["counts"]["kinds"]
        self.assertNotIn("school", counts)
        self.assertIn("hospital", counts)

    def test_the_held_figures_are_null_in_the_block_whether_or_not_the_held_source_loaded(self):
        self.build()
        self.assertTrue(L._held_figures_null(self.block()))
        prime(self.cache, sample(), skip=("fema_worship",))
        shutil.rmtree(self.cache / "fema_worship", ignore_errors=True)
        summary = self.build()
        block = self.block()
        self.assertIsNone(block["counts"]["held_rows"])
        self.assertIsNone(block["held"]["kinds"]["church"]["count"])
        self.assertIsNone(summary["held"]["church_rows"])
        self.assertEqual(block["kinds"]["church"]["state"], "held")
        self.assertIsNone(block["kinds"]["church"]["count"])
        self.assertTrue(L._held_figures_null(block))

    def test_a_malformed_layer_description_fails_only_its_source(self):
        data = sample()
        data["meta"]["nces_public"]["maxRecordCount"] = "many"
        prime(self.cache, data)
        summary = self.build()
        self.assertEqual(summary["state"], "partial")
        block = self.block()
        self.assertEqual(block["kinds"]["school"]["state"], "unavailable")
        self.assertIn("record count", block["sources"]["nces_public"]["reason"])
        for kind in ("hospital", "fire", "airport", "park"):
            self.assertEqual(block["kinds"][kind]["state"], "loaded", kind)
        self.assertFalse(meta_path(self.cache, "nces_public").exists())

    def test_a_reader_error_in_one_source_fails_only_that_source(self):
        real = L.load_source

        def broken(fetch, key, today):
            if key == "nces_public":
                raise KeyError("a field the reader did not expect")
            return real(fetch, key, today)

        with mock.patch.object(L, "load_source", side_effect=broken), contextlib.redirect_stderr(io.StringIO()):
            summary = self.build()
        self.assertEqual(summary["state"], "partial")
        block = self.block()
        self.assertEqual(block["kinds"]["school"]["state"], "unavailable")
        self.assertIn("(KeyError)", block["sources"]["nces_public"]["reason"])
        self.assertEqual(block["kinds"]["hospital"]["state"], "loaded")

    def test_the_hospital_failure_names_the_copy_that_failed(self):
        data = sample()
        data["pages"]["usgs_hospitals"] = {"features": [], "exceededTransferLimit": False}
        prime(self.cache, data, skip=("hifld_hospitals",))
        shutil.rmtree(self.cache / "hifld_hospitals", ignore_errors=True)
        self.build()
        block = self.block()
        hospital = block["kinds"]["hospital"]
        self.assertEqual(hospital["state"], "unavailable")
        self.assertEqual(hospital["failed"], ["hifld_hospitals"])
        self.assertEqual(hospital["sources"], ["usgs_hospitals", "hifld_hospitals"])
        self.assertIn("named no Montana hospital", hospital["reason"])
        self.assertIsNone(block["hospital_source"]["used"])

    def test_the_about_names_the_hospital_copy_when_it_was_used(self):
        data = sample()
        data["pages"]["usgs_hospitals"] = {"features": [], "exceededTransferLimit": False}
        prime(self.cache, data)
        self.build()
        joined = " ".join(L.describe_landmarks(self.index())["sources"])
        self.assertIn("Hospital list copied from the state licensure list", joined)
        self.assertNotIn("hospitals and medical centers", joined)

    def test_the_about_lines_carry_one_date_each_and_leave_out_the_held_list(self):
        self.build()
        about = L.describe_landmarks(self.index())["sources"]
        self.assertTrue(about)
        for line in about:
            self.assertLessEqual(line.count("("), 1, line)
            self.assertLessEqual(len(re.findall(r"\b20\d\d\b", line)), 1, line)
        joined = " ".join(about)
        self.assertIn("cycle effective 2026-10-01", joined)
        self.assertNotIn("places of worship", joined)
        self.assertNotIn("copyright line", joined)

    def test_the_faa_cache_keeps_only_the_cycle_in_force(self):
        folder = self.cache / "faa_nasr"
        (folder / "APT_2026-09-03.zip").write_bytes(b"an older cycle")
        (folder / "APT_2026-09-03.zip.meta.json").write_text("{}", encoding="utf-8")
        self.build()
        self.assertEqual(sorted(p.name for p in folder.glob("APT_*")), ["APT_2026-10-01.zip"])

    def test_an_airport_file_that_is_not_usable_leaves_the_airports_unavailable(self):
        path = self.cache / "faa_nasr" / "APT_2026-10-01.zip"
        path.write_bytes(b"this is not a zip file")
        self.build()
        airport = self.block()["kinds"]["airport"]
        self.assertEqual(airport["state"], "unavailable")
        self.assertIn("not a zip file", airport["reason"])
        self.assertFalse(path.exists())
        path.write_bytes(faa_zip("OTHER.txt"))
        self.build()
        self.assertIn("has no APT.txt member", self.block()["kinds"]["airport"]["reason"])

    def test_verify_fails_on_a_tampered_shard(self):
        self.build()
        shard = sorted((self.store / "hail" / "base" / "p").glob("*.json"))[0]
        doc = json.loads(shard.read_text(encoding="utf-8"))
        doc["i"].append([-114.0, 46.8, "s", "Unlisted School", "nces_public"])
        doc["n"] = len(doc["i"])
        shard.write_text(json.dumps(doc), encoding="utf-8")
        result = L.verify(self.store)
        self.assertFalse(result["ok"])
        failed = [check["check"] for check in result["checks"] if not check["pass"]]
        self.assertTrue(any("manifest" in name for name in failed), failed)

    def test_the_unavailable_command_writes_null_counts(self):
        self.build()
        L.mark_unavailable(self.store, "the test failed")
        counts = self.block()["counts"]
        self.assertIsNone(counts["points"])
        self.assertIsNone(counts["shards"])


@needs_shapefile
class CacheAndRequestTests(unittest.TestCase):
    """The request path, with a session that answers by URL. A body of the wrong kind sent with HTTP 200 is never cached, and
    the next build asks again; a cached file is read without a request."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-request-"))
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        self.overrides: dict = {}
        self.addCleanup(shutil.rmtree, self.root, True)

    def answer(self, url):
        if url in self.overrides:
            return self.overrides[url]
        data = sample()
        for key, spec in L.SOURCES.items():
            if spec.get("format") not in ("arcgis", "padus") or not url.startswith(spec["url"]):
                continue
            if "/query?" in url:
                return 200, json.dumps(data["pages"][key]).encode("utf-8")
            if url == spec["url"] + "?f=pjson":
                return 200, json.dumps(data["meta"][key]).encode("utf-8")
        if url.startswith("https://nfdc.faa.gov/"):
            return 200, faa_zip()
        if url == L.SOURCES["tiger_park"]["url"]:
            return 200, (FIXTURES / "tiger_arealm_mt_sample.zip").read_bytes()
        return 404, b""

    def build(self):
        session = RouterSession(self.answer)
        summary = L.build(self.store, self.cache, now=NOW, session=session, floors=ALL_FLOORS, sleep=lambda seconds: None)
        return summary, session

    def test_an_error_body_sent_with_http_200_is_not_cached_and_the_next_build_asks_again(self):
        meta_url = L.SOURCES["padus_local"]["url"] + "?f=pjson"
        self.overrides[meta_url] = (200, b'{"error": {"code": 500, "message": "service unavailable"}}')
        summary, first = self.build()
        self.assertEqual(summary["state"], "partial")
        self.assertIn(meta_url, first.calls)
        self.assertFalse(meta_path(self.cache, "padus_local").exists())
        del self.overrides[meta_url]
        summary, second = self.build()
        self.assertEqual(summary["state"], "loaded")
        self.assertIn(meta_url, second.calls)
        self.assertNotIn(L.SOURCES["nces_public"]["url"] + "?f=pjson", second.calls)
        self.assertTrue(meta_path(self.cache, "padus_local").exists())
        self.assertTrue(L.verify(self.store)["ok"])

    def test_the_hifld_copy_is_not_requested_while_the_usgs_layer_has_rows(self):
        """The hospital rule (D118(a)): the HIFLD copy is read only when the USGS layer answers with no Montana rows."""
        summary, session = self.build()
        self.assertEqual(summary["state"], "loaded")
        self.assertFalse(any(url.startswith(L.SOURCES["hifld_hospitals"]["url"]) for url in session.calls))
        self.assertTrue(any(url.startswith(L.SOURCES["usgs_hospitals"]["url"]) for url in session.calls))

    def test_a_cached_copy_is_read_without_a_request(self):
        self.build()
        summary, again = self.build()
        self.assertEqual(again.calls, [])
        self.assertEqual(summary["requests"], 0)


class BuildWithoutTheShapefileReaderTests(unittest.TestCase):
    """D20: without the shapefile reader only the parks fail, and the rest of the build loads. The test removes the reader for
    its own run, so it holds whether or not pyshp is installed."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-noreader-"))
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = mock.patch.dict(sys.modules, {"shapefile": None})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_held_census_source_fails_and_the_shown_parks_still_load(self):
        """With the Census list held (P3-R4), a missing reader is that held source's own failure: no shown kind is affected,
        because the shown parks are the PAD-US parks."""
        summary = L.build(self.store, self.cache, now=NOW, offline=True, floors=ALL_FLOORS)
        self.assertEqual(summary["state"], "loaded")
        block = json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))[L.INDEX_KEY]
        self.assertEqual(block["sources"]["tiger_park"]["state"], "held")
        self.assertEqual(block["kinds"]["park"]["state"], "loaded")
        self.assertEqual(block["kinds"]["park"]["sources"], ["padus_local"])
        reasons = {f["source"]: f["reason"] for f in block["failures"]}
        self.assertIn("shapefile reader is not installed", reasons["tiger_park"])
        for kind in ("school", "hospital", "airport", "fire", "park"):
            self.assertEqual(block["kinds"][kind]["state"], "loaded", kind)
        self.assertTrue(L.verify(self.store)["ok"])


class MainTests(unittest.TestCase):
    """The command line: the exit codes of build, verify and unavailable."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-main-"))
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())
        self.addCleanup(shutil.rmtree, self.root, True)

    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = L.main(argv)
        return code, out.getvalue()

    def test_a_build_and_its_check_exit_zero(self):
        code, _ = self.run_main(["build", "--store", str(self.store), "--cache", str(self.cache), "--offline",
                                 "--now", "2026-10-25T20:00:00Z"])
        self.assertEqual(code, 0)
        code, out = self.run_main(["verify", "--store", str(self.store)])
        self.assertEqual(code, 0, out)

    def test_a_missing_store_exits_one(self):
        code, _ = self.run_main(["build", "--store", str(self.root / "nowhere"), "--cache", str(self.cache), "--offline"])
        self.assertEqual(code, 1)

    def test_a_store_without_landmarks_fails_the_check(self):
        code, _ = self.run_main(["verify", "--store", str(self.store)])
        self.assertEqual(code, 1)

    def test_the_unavailable_command_needs_a_reason(self):
        code, _ = self.run_main(["unavailable", "--store", str(self.store), "--reason", "   "])
        self.assertEqual(code, 1)
        code, _ = self.run_main(["unavailable", "--store", str(self.store), "--reason", "the test"])
        self.assertEqual(code, 0)


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
        self.assertNotIn("\u2014", source)

    def test_the_about_credits_and_terms_pass_the_shared_list(self):
        for key, spec in L.SOURCES.items():
            for field in ("credit", "terms"):
                with self.subTest(source=key, field=field):
                    W.assert_clean(self, spec[field].replace("{when}", "layer last edited 2026-04-22"), key)

    def test_the_terms_quote_only_what_the_layers_say(self):
        padus = L.SOURCES["padus_local"]["terms"]
        self.assertIn("U.S. Geological Survey (USGS) Gap Analysis Project (GAP), 2025", padus)
        self.assertIn("https://doi.org/10.5066/P96WBCHS", padus)
        self.assertIn("does not say the data is in the public domain", padus)
        self.assertNotIn("This content describes the PAD-US dataset", padus)
        fema = L.SOURCES["fema_worship"]["terms"]
        self.assertIn("geocoded by a commercial geocoder whose terms are not read", fema)
        self.assertNotIn("use limitations", fema)
        self.assertIn("in the public domain", L.SOURCES["nces_public"]["terms"])
        self.assertIn("not checked", L.SOURCES["hifld_hospitals"]["terms"])

    def test_the_credit_lines_carry_their_date_without_the_copyright_line(self):
        for key, spec in L.SOURCES.items():
            with self.subTest(source=key):
                self.assertNotIn("copyright line", spec["credit"])
        self.assertIn("October 2026 refresh", L.SOURCES["usgs_hospitals"]["credit"])
        self.assertIn("{when}", L.SOURCES["faa_nasr"]["credit"])

    def test_the_held_parks_words_are_the_parks_sentence(self):                       # F6, D141(b)
        self.assertEqual(L.PARKS, "The Census park points and their names are not shown yet: the file's use terms are still "
                                  "being read.")
        self.assertEqual(L.WORDS["held_parks"], L.PARKS)
        self.assertEqual(L.TIGER_HELD_SENTENCE, L.PARKS)
        self.assertEqual(L.TIGER_HELD_REASON, L.PARKS)

    def test_the_held_church_and_parks_sentences_are_plain_words_and_one_sentence_each(self):   # D141(b)
        self.assertEqual(L.CHURCH, "Places of worship are not shown yet: the use terms of the list they come from are still "
                                   "being read, so no church is drawn or named.")
        for sentence in (L.CHURCH, L.PARKS):
            with self.subTest(sentence=sentence[:30]):
                self.assertTrue(sentence[:1].isupper() and sentence.endswith("."), sentence)
                self.assertEqual(sentence.count("."), 1, sentence)
                self.assertNotIn("\u2014", sentence)
                W.assert_clean(self, sentence, sentence[:30])
                for word in ("held", "counsel", "geocoder", "rows", "store", "polygon", "ugcs", "run", "tile", "band"):
                    self.assertIsNone(re.search(rf"\b{word}\b", sentence, re.IGNORECASE), (word, sentence))
        source = (Path(__file__).resolve().parent.parent / "website" / "landmarks.py").read_text(encoding="utf-8")
        self.assertNotIn("second public", source.lower())

    def test_a_missing_date_reads_data_unavailable_in_every_credit_line(self):                  # F2
        for key in L.ORDER + ("hifld_hospitals",):
            for res in (None, {"as_of": None}):
                with self.subTest(source=key, res=res):
                    line = L._credit(key, res)
                    self.assertNotIn("not recorded", line)
                    if "{when}" in L.SOURCES[key]["credit"]:
                        self.assertTrue(line.endswith(" Data unavailable."), line)
        self.assertEqual(L._credit("faa_nasr", {"as_of": "2026-10-01"}),
                         "Source: Federal Aviation Administration, National Airspace System Resources airport data, "
                         "cycle effective 2026-10-01.")

    def test_the_index_credit_lines_read_data_unavailable_when_no_date_was_read(self):          # F2
        block = L._sources_block({})
        for key in L.ORDER + ("hifld_hospitals",):
            self.assertNotIn("not recorded", block[key]["credit"], key)
        for key in ("faa_nasr", "padus_local", "hifld_hospitals"):
            self.assertTrue(block[key]["credit"].endswith(" Data unavailable."), key)


class HeldAndFiguresTests(unittest.TestCase):
    """B6 P3-R4 and D118(b): the Census park list and the church list are held; the index carries their state and reason with
    null counts; the figures are in the summary only; the cache keeps the cycle in force (P3-R7); a loaded source reports the
    size of the file it read (X4)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-held-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())

    def build(self, **kwargs):
        options = dict(now=NOW, offline=True, floors=ALL_FLOORS)
        options.update(kwargs)
        return L.build(self.store, self.cache, **options)

    def index(self) -> dict:
        return json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))

    def block(self) -> dict:
        return self.index()[L.INDEX_KEY]

    def shown_rows(self) -> list:
        out = []
        for path in sorted((self.store / "hail" / "base" / "p").glob("*.json")):
            out += json.loads(path.read_text(encoding="utf-8"))["i"]
        return out

    @needs_shapefile
    def test_the_park_count_is_taken_from_the_pad_us_parks_alone_while_the_census_list_is_held(self):    # D132(g), D141(a)
        with mock.patch.object(L, "dedupe_parks", wraps=L.dedupe_parks) as spy:
            self.build()
        self.assertEqual(spy.call_count, 1)
        rows = spy.call_args[0][0]
        self.assertTrue(rows)
        self.assertEqual({row[4] for row in rows}, {"padus_local"})          # the held TIGER points never reach the count
        self.assertIsInstance(self.block()["counts"]["park_same_name"], int)

    @needs_shapefile
    def test_the_census_park_points_are_held_and_the_pad_us_parks_ship(self):
        summary = self.build()
        block = self.block()
        self.assertEqual(block["sources"]["tiger_park"]["state"], "held")
        self.assertEqual(block["held"]["sources"]["tiger_park"]["reason"], L.PARKS)
        self.assertEqual(block["kinds"]["park"]["sources"], ["padus_local"])
        self.assertEqual(block["kinds"]["park"]["state"], "loaded")
        names = {row[3] for row in self.shown_rows() if row[2] == "p"}
        self.assertIn("Rose Garden", names)
        for held in (TIGER_GARDEN,) + TIGER_KEPT:
            self.assertNotIn(held, names)
        self.assertNotIn("tiger_park", block["counts"]["sources_written"])
        self.assertIsNone(block["counts"]["tiger_merged"])
        self.assertEqual(summary["held"], {"church_rows": 1, "tiger_rows": 2, "tiger_merged": 1, "alt_names": 1})
        about = L.describe_landmarks(self.index())
        self.assertEqual(about["held_parks"], L.WORDS["held_parks"])
        self.assertFalse(any("Census Bureau" in line for line in about["sources"]))
        self.assertTrue(L.verify(self.store)["ok"])

    def test_no_row_of_a_held_source_and_no_alternate_name_is_written_while_it_is_held(self):
        self.build()
        self.assertTrue(all(len(row) == 5 for row in self.shown_rows()))
        self.assertTrue(all(row[4] != "tiger_park" for row in self.shown_rows()))

    @needs_shapefile
    def test_a_pad_us_park_takes_the_census_name_as_its_alternate_once_the_census_list_is_released(self):
        with mock.patch.object(L, "HELD_SOURCES", frozenset({"fema_worship"})):
            summary = self.build()
            self.assertTrue(L.verify(self.store)["ok"])
        rows = self.shown_rows()
        rose = next(row for row in rows if row[3] == "Rose Garden")
        self.assertEqual(rose[5], TIGER_GARDEN)
        self.assertEqual(len(rose), 6)
        self.assertTrue(all(len(row) == 5 for row in rows if row is not rose))
        names = {row[3] for row in rows if row[2] == "p"}
        self.assertTrue(set(TIGER_KEPT) <= names)
        self.assertEqual(self.block()["sources"]["tiger_park"]["state"], "loaded")
        self.assertEqual(summary["held"]["alt_names"], 1)

    @needs_shapefile
    def test_verify_fails_when_a_held_row_or_an_alternate_name_is_written(self):
        self.build()
        shard = sorted((self.store / "hail" / "base" / "p").glob("*.json"))[0]
        doc = json.loads(shard.read_text(encoding="utf-8"))
        doc["i"].append([-114.0, 46.8, "p", "Census Park", "tiger_park"])
        doc["n"] = len(doc["i"])
        shard.write_text(json.dumps(doc), encoding="utf-8")
        failed = [c["check"] for c in L.verify(self.store)["checks"] if not c["pass"]]
        self.assertIn("no held kind or source is written to a shard", failed)
        doc["i"][-1] = [-114.0, 46.8, "p", "Rose Garden", "padus_local", TIGER_GARDEN]
        shard.write_text(json.dumps(doc), encoding="utf-8")
        failed = [c["check"] for c in L.verify(self.store)["checks"] if not c["pass"]]
        self.assertIn("an alternate name is written only on a PAD-US park while the Census list is released", failed)

    def test_the_map_data_and_the_index_carry_no_held_count(self):
        self.build()
        index = self.index()
        data = L.map_data_landmarks(index)
        self.assertNotIn("church", data["counts"]["kinds"])
        self.assertIsNone(data["counts"]["held_rows"])
        self.assertIsNone(data["counts"]["tiger_merged"])        # the Census merge count is held with its list (D118(b))
        self.assertNotIn("tiger_park", data["counts"]["sources_written"])
        self.assertTrue(L._held_figures_null(index[L.INDEX_KEY]))
        self.assertIn("not shown", data["kinds"]["church"]["problem"])

    def test_the_held_block_names_each_held_kind_and_source_with_a_null_count(self):
        self.build()
        held = self.block()["held"]
        self.assertEqual(held["kinds"]["church"]["state"], "held")
        self.assertEqual(held["kinds"]["church"]["reason"], L.HELD_KIND_REASONS["church"])
        self.assertIsNone(held["kinds"]["church"]["count"])
        for key in L.HELD_SOURCES:
            with self.subTest(source=key):
                self.assertEqual(held["sources"][key]["state"], "held")
                self.assertEqual(held["sources"][key]["reason"], L.HELD_SOURCE_REASONS[key])
                self.assertIn("count", held["sources"][key])
                self.assertIsNone(held["sources"][key]["count"])
        failed = [c["check"] for c in L.verify(self.store)["checks"] if not c["pass"]]
        self.assertNotIn("the held block names each held kind and source with its state, its reason and a null count", failed)

    def test_verify_fails_when_the_held_block_carries_a_count(self):
        self.build()
        path = self.store / "hail" / "base" / "index.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        index[L.INDEX_KEY]["held"]["sources"]["tiger_park"]["count"] = 26
        path.write_text(json.dumps(index), encoding="utf-8")
        failed = [c["check"] for c in L.verify(self.store)["checks"] if not c["pass"]]
        self.assertIn("the held block names each held kind and source with its state, its reason and a null count", failed)

    def test_a_loaded_source_reports_the_size_of_the_file_it_read_even_on_a_cached_run(self):
        self.build()                                    # offline: every file is read from the cache
        sources = self.block()["sources"]
        faa = self.cache / "faa_nasr" / "APT_2026-10-01.zip"
        self.assertEqual(sources["faa_nasr"]["bytes"], faa.stat().st_size)
        page = self.cache / "nces_public" / L._query_key(L.SOURCES["nces_public"]) / "p000.json"
        self.assertEqual(sources["nces_public"]["bytes"], meta_path(self.cache, "nces_public").stat().st_size + page.stat().st_size)
        for key in ("nces_public", "nces_private", "usgs_hospitals", "usgs_fire", "padus_local", "faa_nasr"):
            self.assertGreater(sources[key]["bytes"], 0, key)
        self.assertNotIn("bytes", sources["fema_worship"])         # a held source publishes no size

    @needs_shapefile
    def test_a_good_build_keeps_the_cycle_in_force_and_removes_the_older_ones(self):
        older_meta = self.cache / "nces_public" / "meta-0000000000ff.json"
        older_meta.write_text("{}", encoding="utf-8")
        older_query = self.cache / "nces_public" / "0123456789ab"
        older_query.mkdir(parents=True)
        (older_query / "p000.json").write_text('{"features": []}', encoding="utf-8")
        older_vintage = self.cache / "tiger_park" / "tl_2025_30_arealm.zip"
        older_vintage.write_bytes(b"an older vintage")
        self.build()
        self.assertFalse(older_meta.exists())
        self.assertFalse(older_query.exists())
        self.assertFalse(older_vintage.exists())
        self.assertTrue(meta_path(self.cache, "nces_public").exists())
        self.assertTrue((self.cache / "tiger_park" / "tl_2026_30_arealm.zip").exists())

    def test_a_build_that_fails_a_source_keeps_that_sources_older_cycle(self):
        older_query = self.cache / "nces_public" / "0123456789ab"
        older_query.mkdir(parents=True)
        (older_query / "p000.json").write_text('{"features": []}', encoding="utf-8")
        shutil.rmtree(self.cache / "nces_public" / L._query_key(L.SOURCES["nces_public"]))
        summary = self.build()
        self.assertEqual(self.block()["sources"]["nces_public"]["state"], "unavailable")
        self.assertTrue(older_query.exists())
        self.assertIn("nces_public", {f["source"] for f in summary["failures"]})


class SharedBaseIndexTests(unittest.TestCase):
    """B6 P3-R8 (P1-14): hail/base/index.json is one document. This module's block sits beside the other parts' blocks in either
    order of writes; a document of another format is reported as a failure of this module and is kept, never discarded."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-base-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())
        self.base = self.store / "hail" / "base" / "index.json"
        self.base.parent.mkdir(parents=True, exist_ok=True)

    def build(self):
        return L.build(self.store, self.cache, now=NOW, offline=True, floors=ALL_FLOORS)

    def read(self) -> dict:
        return json.loads(self.base.read_text(encoding="utf-8"))

    def other_part_writes(self, key: str, block: dict) -> None:
        """Another part's write, as the parts make it: read the document (a new one starts with the shared format key), set its
        own key, write the document back."""
        doc = self.read() if self.base.is_file() else {"f": L.BASE_FORMAT}
        doc[key] = block
        self.base.write_text(json.dumps(doc, indent=1), encoding="utf-8")

    def test_a_new_document_starts_with_the_shared_format_key(self):
        self.build()
        self.assertEqual(self.read()["f"], "hail-base-index-v1")
        self.assertEqual(L.BASE_FORMAT, "hail-base-index-v1")

    def test_the_other_parts_use_the_same_format_key(self):
        from website import basemap2, terrain
        self.assertEqual(terrain.BASE_INDEX_FORMAT, L.BASE_FORMAT)
        self.assertEqual(basemap2.FORMAT_INDEX, L.BASE_FORMAT)

    def test_the_other_parts_blocks_survive_a_landmarks_write_and_the_reverse(self):
        terrain_block = {"state": "loaded", "as_of": "2026-10-25"}
        vector_block = {"state": "loaded", "as_of": "2026-10-25"}
        self.other_part_writes("terrain", terrain_block)
        self.other_part_writes("vector", vector_block)
        self.build()                                                  # a landmarks write after the other parts
        doc = self.read()
        self.assertEqual((doc["terrain"], doc["vector"], doc["f"]), (terrain_block, vector_block, L.BASE_FORMAT))
        landmarks_block = doc[L.INDEX_KEY]
        self.other_part_writes("terrain", {"state": "partial"})       # the reverse: another part writes after landmarks
        doc = self.read()
        self.assertEqual(doc[L.INDEX_KEY], landmarks_block)
        self.assertEqual(doc["vector"], vector_block)
        self.assertEqual(doc["terrain"], {"state": "partial"})

    def test_a_base_index_of_another_format_is_reported_and_kept(self):
        for before in ({"f": "some-other-format", "terrain": {"state": "loaded"}},
                       {"format": "hail-base-index-v1", "vector": {"state": "loaded"}}):
            with self.subTest(before=before):
                self.base.write_text(json.dumps(before), encoding="utf-8")
                with self.assertRaises(L.LandmarkError) as ctx:
                    self.build()
                self.assertIn("is not a hail-base-index-v1 document", str(ctx.exception))
                self.assertEqual(self.read(), before)
                self.assertFalse((self.store / "hail" / "base" / "p").exists())
                with self.assertRaises(L.LandmarkError):
                    L.mark_unavailable(self.store, "the test failed")
                self.assertEqual(self.read(), before)


class HailIndexMirrorTests(unittest.TestCase):
    """B6 integration C1 (D128(e)): this module's block is mirrored into hail/index.json's "base" block under its own key, as the
    terrain and vector parts mirror theirs. A build writes the mirror, the unavailable command writes an unavailable mirror, and
    the other parts' mirror blocks and every other key of the index survive both. The manifest lists hail/index.json with its
    current bytes and hash after each write, so hail.check_manifest passes."""

    TERRAIN = {"state": "loaded", "problem": None, "as_of": {"shading": "2026-09-28"}, "zooms": [5, 10],
               "counts": {"tiles": 881}, "bytes": 14349318, "budget": {"bytes_limit": 20000000}, "sources": {}, "layers": {}}
    VECTOR = {"state": "partial", "problem": "a test sentence", "as_of": "2026-10-16", "counts": {"shards": 20},
              "sources": {"tiger_aiannh": {"state": "cache"}}, "bytes": 543500}

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-mirror-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())
        index = self.hail_index()
        index["base"] = {"terrain": self.TERRAIN, "vector": self.VECTOR}
        self.write_hail_index(index)

    def hail_index(self) -> dict:
        return json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))

    def write_hail_index(self, index: dict) -> None:
        """Writes hail/index.json and its manifest entry (as the parts do), so the manifest check holds between the writes."""
        data = (json.dumps(index, indent=1, ensure_ascii=True) + "\n").encode("utf-8")
        (self.store / "hail" / "index.json").write_bytes(data)
        manifest_path = self.store / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["hail/index.json"] = {"bytes": len(data), "sha256": _sha(data)}
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    def block(self) -> dict:
        return json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))[L.INDEX_KEY]

    def build(self) -> dict:
        return L.build(self.store, self.cache, now=NOW, offline=True, floors=ALL_FLOORS)

    def test_a_build_writes_this_key_of_the_mirror_and_keeps_the_other_parts(self):
        before = self.hail_index()
        self.assertEqual(self.build()["state"], "loaded")
        after = self.hail_index()
        self.assertEqual({k: v for k, v in after.items() if k != "base"}, {k: v for k, v in before.items() if k != "base"})
        self.assertEqual(after["base"]["terrain"], self.TERRAIN)
        self.assertEqual(after["base"]["vector"], self.VECTOR)
        block = self.block()
        mirror = after["base"][L.INDEX_KEY]
        self.assertEqual(sorted(mirror), sorted(["as_of", "bytes", "counts", "held", "problem", "sources", "state"]))
        self.assertEqual((mirror["state"], mirror["problem"], mirror["as_of"]), ("loaded", None, "2026-10-25"))
        self.assertEqual(mirror["counts"], block["counts"])
        self.assertEqual(mirror["sources"], block["sources"])
        self.assertEqual(mirror["bytes"], block["counts"]["bytes"])
        self.assertEqual(mirror["held"], block["held"])
        self.assertIsNone(mirror["held"]["kinds"]["church"]["count"])
        self.assertIsNone(mirror["held"]["sources"]["fema_worship"]["count"])
        self.assertIsNone(mirror["counts"]["held_rows"])
        hail.check_manifest(self.store)
        result = L.verify(self.store)
        self.assertTrue(result["ok"], [c for c in result["checks"] if not c["pass"]])

    def test_the_unavailable_command_writes_an_unavailable_mirror_and_keeps_the_other_parts(self):
        self.build()
        L.mark_unavailable(self.store, "the test failed")
        after = self.hail_index()
        self.assertEqual(after["base"]["terrain"], self.TERRAIN)
        self.assertEqual(after["base"]["vector"], self.VECTOR)
        mirror = after["base"][L.INDEX_KEY]
        self.assertEqual(mirror["state"], "unavailable")
        self.assertEqual(mirror["problem"], L.WORDS["all_unavailable"])
        self.assertEqual(mirror["counts"], {"points": None, "shards": None})
        self.assertIsNone(mirror["bytes"])
        self.assertEqual(mirror["held"], {})
        hail.check_manifest(self.store)
        self.assertTrue(L.verify(self.store)["ok"])

    def test_another_part_written_after_landmarks_keeps_the_landmarks_mirror(self):
        self.build()
        mirror = self.hail_index()["base"][L.INDEX_KEY]
        index = self.hail_index()
        index["base"]["vector"] = {"state": "loaded", "as_of": "2026-10-30"}
        self.write_hail_index(index)
        self.assertEqual(self.hail_index()["base"][L.INDEX_KEY], mirror)
        self.assertTrue(L.verify(self.store)["ok"])

    def test_a_store_index_with_no_base_block_gets_only_the_landmarks_key(self):
        index = self.hail_index()
        del index["base"]
        self.write_hail_index(index)
        self.build()
        self.assertEqual(sorted(self.hail_index()["base"]), [L.INDEX_KEY])
        hail.check_manifest(self.store)

    def test_verify_fails_when_the_mirror_does_not_match_the_block(self):
        self.build()
        index = self.hail_index()
        index["base"][L.INDEX_KEY]["counts"]["points"] = 999
        self.write_hail_index(index)
        failed = [c["check"] for c in L.verify(self.store)["checks"] if not c["pass"]]
        self.assertIn("hail/index.json base mirror matches the block (this key only; the other parts' keys are kept)", failed)


class HeldTermsTests(unittest.TestCase):
    """B6 integration C2 (D132(b)): a held source publishes its reason alone as its terms. The licence sentence that the file's own
    notice gives (kept in SOURCES, marked as not read by counsel) is not in the index, the mirror, the map data or the About words,
    and the held reason is the only text a held source carries."""

    LICENCE = re.compile(r"not copyrighted|free to use|acknowledg\w*|public domain", re.IGNORECASE)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-terms-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())
        L.build(self.store, self.cache, now=NOW, offline=True, floors=ALL_FLOORS)

    def index(self) -> dict:
        return json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))

    def mirror(self) -> dict:
        return json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["base"][L.INDEX_KEY]

    def test_the_file_notice_is_kept_in_the_internal_note_marked_as_not_read_by_counsel(self):
        note = L.SOURCES["tiger_park"]["terms"]
        self.assertIn("not published", note)
        self.assertIn("not read by counsel", note)
        self.assertIn("Not copyrighted; free to use in a product or publication.", note)

    def test_each_held_source_publishes_its_reason_alone_as_its_terms(self):
        block = self.index()[L.INDEX_KEY]
        mirror = self.mirror()
        for key in L.HELD_SOURCES:
            with self.subTest(source=key):
                for where, sources in (("index", block["sources"]), ("mirror", mirror["sources"])):
                    self.assertEqual(sources[key]["terms"], L.HELD_SOURCE_REASONS[key], where)
                    self.assertIsNone(self.LICENCE.search(sources[key]["terms"]), where)
        self.assertEqual(block["sources"]["tiger_park"]["terms"], L.PARKS)
        self.assertEqual(block["sources"]["fema_worship"]["terms"], L.CHURCH_HELD)

    def test_no_held_source_licence_sentence_is_in_the_map_data_or_the_about_words(self):
        index = self.index()
        data = L.map_data_landmarks(index)
        about = L.describe_landmarks(index)
        published = json.dumps({"map": data, "about": about}, ensure_ascii=False, sort_keys=True)
        match = self.LICENCE.search(published)
        self.assertIsNone(match, match.group(0) if match else None)
        for key in L.HELD_SOURCES:
            self.assertNotIn(L.SOURCES[key]["terms"], published, key)
        for text in about["sources"]:
            self.assertIsNone(self.LICENCE.search(text), text)

    def test_verify_fails_when_a_held_source_publishes_a_licence_sentence(self):
        path = self.store / "hail" / "base" / "index.json"
        index = self.index()
        index[L.INDEX_KEY]["sources"]["tiger_park"]["terms"] = L.SOURCES["tiger_park"]["terms"]
        path.write_text(json.dumps(index), encoding="utf-8")
        failed = [c["check"] for c in L.verify(self.store)["checks"] if not c["pass"]]
        self.assertIn("held sources publish their reason alone as terms, in the index and the mirror (no licence text)", failed)


class HeldKindSentenceTests(unittest.TestCase):
    """B6 integration C4 (D132(d)): the held church kind has one reason sentence in every place it appears: the words (WORDS held,
    the chip's reason), the index (the kind, the held block and the church list's source), the hail index mirror, the map data, and
    the About words. The About page prints the same sentence as its own paragraph (about.html, which build.py fills with
    lm.CHURCH_HELD, D136(a)); the module holds the sentence once, as CHURCH (HELD_REASON and CHURCH_HELD are that text)."""

    SENTENCE = ("Places of worship are not shown yet: the use terms of the list they come from are still being read, so no church "
                "is drawn or named.")

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-kind-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = make_store(self.root)
        self.cache = self.root / "cache"
        prime(self.cache, sample())

    def test_the_one_sentence_is_the_same_in_the_words_the_index_the_mirror_the_map_data_and_the_about_words(self):
        self.assertEqual(L.CHURCH_HELD, self.SENTENCE)
        self.assertEqual(L.WORDS["held"], self.SENTENCE)
        self.assertEqual(L.HELD_KIND_REASONS["church"], self.SENTENCE)
        self.assertEqual(L.HELD_SOURCE_REASONS["fema_worship"], self.SENTENCE)
        L.build(self.store, self.cache, now=NOW, offline=True, floors=ALL_FLOORS)
        index = json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))
        block = index[L.INDEX_KEY]
        mirror = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["base"][L.INDEX_KEY]
        self.assertEqual(block["kinds"]["church"]["reason"], self.SENTENCE)
        self.assertEqual(block["held"]["kinds"]["church"]["reason"], self.SENTENCE)
        self.assertEqual(block["sources"]["fema_worship"]["reason"], self.SENTENCE)
        self.assertEqual(block["held"]["sources"]["fema_worship"]["reason"], self.SENTENCE)
        self.assertEqual(mirror["held"]["kinds"]["church"]["reason"], self.SENTENCE)
        self.assertEqual(L.map_data_landmarks(index)["kinds"]["church"]["problem"], self.SENTENCE)
        self.assertEqual(L.describe_landmarks(index)["held"], self.SENTENCE)

    def test_the_about_template_prints_the_church_sentence_as_its_own_paragraph_that_build_passes(self):
        # D136(a): the template prints the module's sentence whole, as its own paragraph; build.py passes lm.CHURCH_HELD under
        # "held_church". Both files are read as text, so the page and the build cannot drift from the module's one sentence.
        root = Path(__file__).resolve().parent.parent
        template = (root / "website" / "templates" / "about.html").read_text(encoding="utf-8")
        build_text = (root / "website" / "build.py").read_text(encoding="utf-8")
        self.assertIn("<p>{{ b6.held_church }}</p>", template)
        self.assertIn('"held_church": lm.CHURCH_HELD', build_text)
        self.assertEqual(L.CHURCH, self.SENTENCE)
        self.assertEqual(L.HELD_REASON, self.SENTENCE)


class DisplayNameTests(unittest.TestCase):
    """B6 P3-D118(c): the owner's casing rules after the shared title case, the school words, the abbreviations that stay, and
    the characters that are kept as the source gives them."""

    def test_a_possessive_s_after_an_apostrophe_is_lower_case(self):
        self.assertEqual(L.clean_name("SHODAIR CHILDREN'S HOSPITAL"), "Shodair Children's Hospital")
        self.assertEqual(L.clean_name("PEOPLE'S PARK"), "People's Park")
        self.assertEqual(L.clean_name("YOGI BEAR'S JELLYSTONE PARK"), "Yogi Bear's Jellystone Park")
        self.assertEqual(L.clean_name("RIVER\u2019S EDGE PARK"), "River\u2019s Edge Park")
        self.assertEqual(L.clean_name("O'CONNELL PARK"), "O'Connell Park")

    def test_ordinal_suffixes_are_lower_case_when_they_are_the_numbers_own(self):
        self.assertEqual(L.clean_name("9TH STREET PARK"), "9th Street Park")
        self.assertEqual(L.clean_name("12TH ST W PARK"), "12th St W Park")
        self.assertEqual(L.clean_name("2ND STREET PARKS"), "2nd Street Parks")
        self.assertEqual(L.clean_name("4TH AVE E N PARK"), "4th Ave E N Park")
        self.assertEqual(L.clean_name("1049TH FIRE FIGHTING PLATOON FIRE STATION"), "1049th Fire Fighting Platoon Fire Station")
        self.assertEqual(L.clean_name("21ST STREET"), "21st Street")
        self.assertEqual(L.clean_name("11TH STREET"), "11th Street")
        self.assertEqual(L.clean_name("16ST PARK"), "16St Park")

    def test_mc_before_a_lower_case_letter_takes_a_capital(self):
        self.assertEqual(L.clean_name("MCCORMICK PARK"), "McCormick Park")
        self.assertEqual(L.clean_name("MCLEOD PARK"), "McLeod Park")
        self.assertEqual(L.clean_name("MCGRUFF PARK"), "McGruff Park")
        self.assertEqual(L.clean_name("MC GREGOR LAKE STATION"), "Mc Gregor Lake Station")

    def test_a_backslash_is_a_slash_and_a_lower_case_word_after_a_slash_is_capitalised(self):
        self.assertEqual(L.clean_name("KIWANIS PARK/HAMILTON ATHLETIC FIELDS"), "Kiwanis Park/Hamilton Athletic Fields")
        self.assertEqual(L.clean_name("Kiwanis Park/hamilton Athletic Fields"), "Kiwanis Park/Hamilton Athletic Fields")
        self.assertEqual(L.clean_name("MCGRUFF\\MANNING PARK"), "McGruff/Manning Park")
        self.assertEqual(L.clean_name("SCHAFER\\USFS\\AIRPORT"), "Schafer/USFS/Airport")

    def test_school_words_are_written_out_for_school_names_only(self):
        self.assertEqual(L.school_name("BROWNING HS"), "Browning High School")
        self.assertEqual(L.school_name("MISSOULA CONNECT ACADEMY MS"), "Missoula Connect Academy Middle School")
        self.assertEqual(L.school_name("PRICKLY PEAR ELEM"), "Prickly Pear Elementary")
        self.assertEqual(L.school_name("PINE BUTTE ELEMENTARY SCH"), "Pine Butte Elementary School")
        self.assertEqual(L.school_name("HAYS-LODGE POLE HIGH SCHL"), "Hays-Lodge Pole High School")
        self.assertEqual(L.school_name("ANACONDA JR HIGH SCHOOL"), "Anaconda Junior High School")
        self.assertEqual(L.school_name("BILLINGS SR HIGH SCHOOL"), "Billings Senior High School")
        self.assertEqual(L.school_name("COLUMBIA FALLS JR HS"), "Columbia Falls Junior High School")
        self.assertEqual(L.school_name("MT SCH FOR DEAF & BLND HS"), "Mt School For Deaf & Blnd High School")
        self.assertEqual(L.school_name("CSD HS RISE PATHWAY ACADEMY"), "Csd Hs Rise Pathway Academy")
        self.assertEqual(L.clean_name("BROWNING HS"), "Browning Hs")
        self.assertEqual(L.clean_name("JR PARK"), "Jr Park")

    def test_abbreviations_stay_as_the_source_gives_them_and_are_counted(self):
        self.assertEqual(L.clean_name("BEAVERHEAD CO HIGH SCHOOL"), "Beaverhead Co High School")
        names = ["Beaverhead Co High School", "Powder River Co Dist High", "Kingsbury Colony Attn Ctr", "Bn Plaza",
                 "Mt Ellis Elementary", "Us Bank Park", "Fort Harrison Va Medical Center", "Mount Ascension Learning Ac El",
                 "Jeannette Rankin Elementary Sc"]
        counts = L.abbreviation_counts(names)
        self.assertEqual(counts, {"Ac": 1, "Attn": 1, "Bn": 1, "Co": 2, "Ctr": 1, "Dist": 1, "El": 1, "Mt": 1, "Sc": 1,
                                  "Us": 1, "Va": 1})

    def test_an_en_dash_and_an_apostrophe_are_kept_as_the_source_gives_them(self):
        self.assertEqual(L.clean_name("LOGAN HEALTH \u2013 WHITEFISH"), "Logan Health \u2013 Whitefish")
        self.assertEqual(L.clean_name("ST MATTHEW'S SCHOOL"), "St Matthew's School")


class ParkNameTests(unittest.TestCase):
    """B6 P3-R3: the PAD-US name stands for a park that a Census point is the same as; the Census name is the alternate."""

    @needs_shapefile
    def test_a_pad_us_park_names_its_census_twin_as_the_alternate(self):
        polys, _ = L.polygons_from(sample()["pages"]["padus_local"]["features"])
        pad_rows, kept, merged = L.merge_parks(polys, [("park", TIGER_GARDEN, TIGER_GARDEN_POSITION[0], TIGER_GARDEN_POSITION[1],
                                                        "tiger_park")])
        self.assertEqual(pad_rows[0][1], "Rose Garden")
        self.assertEqual(pad_rows[0][5], TIGER_GARDEN)
        self.assertEqual((kept, merged), ([], 1))
        pad_rows, _, _ = L.merge_parks(polys, [("park", "Rose Garden", TIGER_GARDEN_POSITION[0], TIGER_GARDEN_POSITION[1],
                                                 "tiger_park")])
        self.assertEqual(len(pad_rows[0]), 5)                     # the same name is no alternate

    def test_the_alternate_name_of_a_dropped_piece_stays_with_the_park(self):
        rows = [("park", "Scotty Park", -114.05544, 46.80875, "padus_local"),
                ("park", "Scotty Park", -114.05543, 46.80874, "padus_local", "Scotty Pk")]
        kept, dropped = L.dedupe_parks(rows)
        self.assertEqual((len(kept), dropped, kept[0][5]), (1, 1, "Scotty Pk"))


class CreditWordsTests(unittest.TestCase):
    """B6 P3-R5 (D113(a)): every credit line reads "Source: ..." and carries no endorsement word."""

    def test_every_credit_line_reads_source_and_carries_no_endorsement_word(self):
        endorsement = re.compile(r"(?i)\b(endorse\w*|official\w*|approved|sponsor\w*|partner\w*|certif\w*|recommend\w*|"
                                 r"authoriz\w*|courtesy|in cooperation)\b")
        for key, spec in L.SOURCES.items():
            with self.subTest(source=key):
                self.assertTrue(spec["credit"].startswith("Source: "), spec["credit"])
                self.assertIsNone(endorsement.search(spec["credit"]))

    def test_the_hospital_rule_is_the_same_in_the_docstring_and_in_both_source_rows(self):
        sentence = ("The HIFLD copy is read only when the USGS layer answers with no Montana rows; a failed USGS request makes "
                    "hospitals unavailable, never a silent switch of source.")
        self.assertEqual(L.HOSPITAL_RULE, sentence)
        self.assertIn(sentence, " ".join(L.__doc__.split()))
        self.assertEqual(L.SOURCES["usgs_hospitals"]["rule"], sentence)
        self.assertEqual(L.SOURCES["hifld_hospitals"]["rule"], sentence)

    def test_every_held_kind_source_is_a_held_source_with_a_reason(self):
        for kind in L.HELD:
            for key in L.KIND_SOURCES[kind]:
                self.assertIn(key, L.HELD_SOURCES)
        for key, reason in L.HELD_SOURCE_REASONS.items():
            self.assertTrue(reason, key)


class SourceRowWordingTests(unittest.TestCase):
    """The website/sources.py rows that the B6 tidy items name. tests/test_site.py pins the other rows; these checks sit here
    with the held-source rules: the held Census row and the church row carry no licence sentence of their file (D132(b));
    the two terrain rows say what the monthly job passes, its caps, and that a tile is asked again only when its month
    changed, and no row says every tile is asked again each month (D128(f), D132(e)); the IEM zone row says what its
    snapshot gives and what the zone counts use (F5)."""

    ROWS = src.CONTRACTS

    def test_the_held_census_row_says_held_and_carries_no_licence_sentence(self):              # D132(b)
        row = self.ROWS["tiger_park"]
        self.assertTrue(row["missing"].startswith("Not shown yet: the file's use terms are still being read"),
                        row["missing"])
        self.assertTrue(row["missing"].endswith("the PAD-US parks still ship."), row["missing"])
        text = " ".join(row.values())
        self.assertNotIn("Not copyrighted", text)
        self.assertNotIn("acknowledgement to the U.S. Census Bureau", text)

    def test_the_held_church_row_carries_no_licence_sentence(self):                            # D132(b)
        text = " ".join(self.ROWS["fema_worship"].values())
        self.assertNotIn("Not copyrighted", text)
        self.assertNotIn("acknowledgement to the U.S. Census Bureau", text)

    def test_the_terrain_rows_say_what_the_monthly_job_passes_and_its_caps(self):              # D128(f), D132(e)
        for key in ("terrain_shading", "terrain_land_cover"):
            with self.subTest(row=key):
                timing = self.ROWS[key]["timing"]
                self.assertIn("passes --refresh-descriptions", timing)
                self.assertIn("the two service descriptions are read again", timing)
                self.assertIn("a tile is requested again only when its data month changed, through the cache key", timing)
                self.assertIn("A full --refresh runs only when the owner asks.", timing)
                self.assertIn("capped at 25 minutes", timing)
                self.assertIn("the check at 900 seconds", timing)

    def test_no_row_says_every_tile_is_asked_again_each_month(self):                           # D128(f)
        for key, row in self.ROWS.items():
            for field, text in row.items():
                with self.subTest(row=key, field=field):
                    self.assertNotRegex(text, r"(?i)every tile[^.]*\bagain\b")
                    self.assertNotIn("asks again (--refresh)", text)

    def test_the_iem_zone_row_says_what_the_snapshot_gives_and_what_the_counts_use(self):       # F5
        row = self.ROWS["iem_ugcs"]
        for field in ("request", "timing"):
            with self.subTest(field=field):
                self.assertIn("ugcs snapshot of 2026-10-25", row[field])
                self.assertIn("gives the 83 public zone outlines only", row[field])
                self.assertIn("B6 zone counts use the counted rows from the store's zone and polygon files", row[field])
        self.assertNotIn("139 features", " ".join(row.values()))


if __name__ == "__main__":
    unittest.main()
