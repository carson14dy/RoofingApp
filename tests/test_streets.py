"""Streets (website/streets.py, B3 roads layer): the field allow-list (no owner field is read, decision 6), the table
layouts, the class rules (D33), the concurrency merge with names joined by " / " (D16), placeholder names (D16a), the
simplification bound on the stored (rounded) line (2 m, D16), the clipping to shards and the byte split (D26), the name
table, the download cache (D24), the index block, the unavailable path (D20, D36), the words (the forbidden-term check,
D29) and the workflow step.

The tests write their own synthetic zips (a Library-style polyline file with the 51-field table, and a Census-style
county file with the four TIGER fields) in a temporary folder they create and remove. No network. Tests that project
positions need pyproj and tests that cut shards need numpy; both are in the job and skip without them."""

import contextlib
import hashlib
import io
import json
import math
import random
import re
import shutil
import struct
import sys
import tempfile
import os
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from website import hail
from website import streets as S

sys.path.insert(0, str(Path(__file__).resolve().parent))   # words_rules is the one forbidden list (D81(c))
import words_rules as W  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "hail-store.yml"
REAL_LIBRARY = Path(os.environ.get("HAIL_CACHE_DIR", "cache")) / "roads" / "TransportationFramework_shp.zip"   # the local cache; the tests that read it skip when it is absent

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

try:
    import pyproj  # noqa: F401
    HAVE_STACK = HAVE_NUMPY
except ImportError:
    HAVE_STACK = False

FORBIDDEN = re.compile(r"\b(home|homes|house|houses|residence|residences|dwelling|dwellings|use|uses)\b", re.I)


# ---------------------------------------------------------------- synthetic files

def _shp_header(words: int, box) -> bytes:
    return (struct.pack(">i", 9994) + b"\x00" * 20 + struct.pack(">i", words) + struct.pack("<ii", 1000, 3)
            + struct.pack("<4d", *box) + struct.pack("<4d", 0, 0, 0, 0))


def _shp_and_shx(records):
    """records: a list, one item per shape: None (a null shape) or a list of parts, each a list of (x, y)."""
    contents, bodies, offsets, xs, ys = [], [], [], [], []
    pos = 100
    for rec in records:
        if rec is None:
            content = struct.pack("<i", 0)
        else:
            pts = [p for part in rec for p in part]
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
            starts, off = [], 0
            for part in rec:
                starts.append(off)
                off += len(part)
            content = (struct.pack("<i", 3)
                       + struct.pack("<4d", min(p[0] for p in pts), min(p[1] for p in pts),
                                     max(p[0] for p in pts), max(p[1] for p in pts))
                       + struct.pack("<ii", len(rec), len(pts)) + struct.pack(f"<{len(rec)}i", *starts)
                       + b"".join(struct.pack("<dd", x, y) for x, y in pts))
        contents.append(content)
        offsets.append(pos)
        bodies.append(struct.pack(">ii", len(contents), len(content) // 2) + content)
        pos += 8 + len(content)
    box = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)
    shp = _shp_header((100 + sum(len(b) for b in bodies)) // 2, box) + b"".join(bodies)
    shx = _shp_header((100 + 8 * len(contents)) // 2, box) + b"".join(
        struct.pack(">ii", off // 2, len(c) // 2) for off, c in zip(offsets, contents))
    return shp, shx


def _dbf_bytes(spec, rows) -> bytes:
    """rows: (deleted, {field: text}). Fixed-width records, the deletion flag in byte 0, text left-justified and numbers
    right-justified, as the Library and Census tables are written."""
    hlen = 32 + 32 * len(spec) + 1
    rlen = 1 + sum(length for _n, _t, length in spec)
    head = bytearray(32)
    head[0] = 3
    head[1:4] = bytes([126, 10, 19])
    struct.pack_into("<IHH", head, 4, len(rows), hlen, rlen)
    desc = bytearray()
    for name, kind, length in spec:
        field = bytearray(32)
        raw = name.encode("ascii")[:11]
        field[:len(raw)] = raw
        field[11] = ord(kind)
        field[16] = length
        desc += field
    body = bytearray()
    for deleted, values in rows:
        record = bytearray(b"*" if deleted else b" ")
        for name, kind, length in spec:
            text = str(values.get(name, "") or "").encode("ascii", "replace")[:length]
            record += text.rjust(length) if kind == "N" else text.ljust(length)
        body += record
    return bytes(head) + bytes(desc) + b"\r" + bytes(body)


def _meta_xml(pubdate="20260930", useconst=None) -> bytes:
    useconst = useconst or (S.LIBRARY_DISCLAIMER + " " + S.LIBRARY_CONVENIENCE)
    return (f"<metadata><idinfo><citation><citeinfo><pubdate>{pubdate}</pubdate></citeinfo></citation>"
            f"<accconst>None</accconst><useconst>{useconst}</useconst>"
            "<purpose>The goal of the Montana Transportation Framework is to have a routinely updated statewide "
            "database of road centerlines for Montana.</purpose></idinfo></metadata>").encode("utf-8")


def write_library_zip(path, features, *, spec=None, prj_name=None, useconst=None, readme_date="20260930"):
    """A Library-style zip: features are dicts with parts (lists of (x, y) in EPSG:6514 metres), fields (the table's
    text by name), and optional deleted and null flags."""
    spec = spec or S.LIBRARY_DBF_SPEC
    records = [None if f.get("null") else f["parts"] for f in features]
    shp, shx = _shp_and_shx(records)
    dbf = _dbf_bytes(spec, [(f.get("deleted", False), f.get("fields", {})) for f in features])
    prj = (f'PROJCS["{prj_name or S.LIBRARY_PRJ}",GEOGCS["GCS_NAD_1983_2011",DATUM["D_NAD_1983_2011",'
           'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0]],PROJECTION['
           '"Lambert_Conformal_Conic"],UNIT["Meter",1.0]]')
    readme = ("*****\nThe Montana Transportation Framework data contained in this zip file were exported from the "
              f"Montana State Library enterprise geodatabase on {readme_date}.\n\n"
              "The Transportation Framework downloads are exported monthly.\n")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(S.LIBRARY_README, readme)
        zf.writestr(S.LIBRARY_META, _meta_xml(useconst=useconst))
        zf.writestr(S.LIBRARY_PRJ_MEMBER, prj)
        zf.writestr(S.LIBRARY_SHP, shp)
        zf.writestr(S.LIBRARY_SHX, shx)
        zf.writestr(S.LIBRARY_DBF, dbf)


def write_county_zip(path, fips, features):
    """A Census-style county zip: features are dicts with parts (lists of (lon, lat) in NAD83 degrees) and fields."""
    base = f"tl_2026_{fips}_roads"
    records = [f["parts"] for f in features]
    shp, shx = _shp_and_shx(records)
    dbf = _dbf_bytes(S.TIGER_DBF_SPEC, [(False, f.get("fields", {})) for f in features])
    prj = ('GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",SPHEROID["GRS_1980",6378137,'
           '298.257222101]],PRIMEM["Greenwich",0],UNIT["Degree",0.0174532925199433]]')
    iso = ("<gmd:otherConstraints><gco:CharacterString>Access constraints: None</gco:CharacterString>"
           "</gmd:otherConstraints><gmd:otherConstraints><gco:CharacterString>Use Constraints: The TIGER/Line "
           "Shapefile products are not copyrighted however " + S.TIGER_TRADEMARK + " These products are free to use "
           "in a product or publication, however " + S.TIGER_ACK + " The horizontal spatial accuracy information is "
           "provided for statistical purposes. The TIGER/Line Shapefiles " + S.TIGER_ACCURACY + "</gco:CharacterString>"
           "</gmd:otherConstraints>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(base + ".shp", shp)
        zf.writestr(base + ".shx", shx)
        zf.writestr(base + ".dbf", dbf)
        zf.writestr(base + ".prj", prj)
        zf.writestr(base + ".shp.iso.xml", iso)


def _feature(fields, parts, **extra):
    return dict(fields=fields, parts=parts, **extra)


def _library_fields(**values):
    base = {name: "" for name, _k, _l in S.LIBRARY_DBF_SPEC}
    base.update(values)
    return base


def _road(name, pre_type="", post_type="", road_class="Local", county="Yellowstone County", **extra):
    fields = _library_fields(St_Name=name, St_PreTyp=pre_type, St_PosTyp=post_type, RoadClass=road_class,
                             County_L=county, SurfaceTyp="Paved")
    fields.update(extra)
    return fields


class StreetsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="streets-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)       # removes only the folder this test made

    def line(self, x, y, length=100.0, dy=0.0):
        return [[(x, y + dy), (x + length, y + dy)]]

    def make_store(self, name: str = "store") -> Path:
        store = self.tmp / name
        (store / "hail").mkdir(parents=True)
        (store / "hail" / "index.json").write_text(json.dumps({"grid": {}}), encoding="utf-8")
        (store / "hail" / "manifest.json").write_text(json.dumps({"format": "hail-manifest-v1", "files": {}}),
                                                      encoding="utf-8")
        return store


# ---------------------------------------------------------------- the layouts and the allow-list (decision 6, D1, D41)

class LayoutTests(unittest.TestCase):
    def test_library_table_is_the_51_field_layout(self):
        self.assertEqual(len(S.LIBRARY_DBF_SPEC), 51)
        self.assertEqual(S.LIBRARY_HEADER_BYTES, 32 + 32 * 51 + 1)
        self.assertEqual(S.LIBRARY_RECORD_BYTES, 1 + sum(length for _n, _k, length in S.LIBRARY_DBF_SPEC))
        self.assertEqual(S.LIBRARY_DBF_SPEC[-1][0], "GlobalID")

    def test_allow_list_holds_no_owner_or_identifier_field(self):
        self.assertEqual(set(S.LIBRARY_ALLOWED) & set(S.LIBRARY_NEVER), set())
        self.assertNotIn("Ownership", S.LIBRARY_ALLOWED)
        self.assertNotIn("LocalID", S.LIBRARY_ALLOWED)
        self.assertNotIn("GlobalID", S.LIBRARY_ALLOWED)
        self.assertTrue(set(S.LIBRARY_ALLOWED) <= {name for name, _k, _l in S.LIBRARY_DBF_SPEC})

    def test_census_fields_are_the_four_the_brief_names(self):
        self.assertEqual(tuple(S.TIGER_ALLOWED), ("LINEARID", "FULLNAME", "RTTYP", "MTFCC"))
        self.assertEqual(S.TIGER_RECORD_BYTES, 1 + sum(length for _n, _k, length in S.TIGER_DBF_SPEC))
        self.assertEqual(S.TIGER_HEADER_BYTES, 32 + 32 * 4 + 1)

    def test_two_projections_and_their_names(self):
        self.assertEqual(S.LIBRARY_PRJ, "NAD_1983_2011_StatePlane_Montana_FIPS_2500")
        self.assertEqual(S.LIBRARY_CRS, "EPSG:6514")
        self.assertEqual(S.TIGER_CRS, "EPSG:32100")


# ---------------------------------------------------------------- classes, names and placeholders (D16, D16a, D33)

class RuleTests(unittest.TestCase):
    def test_library_classes(self):
        expect = {"Primary": "p", "Secondary": "s", "Local": "l", "Ramp": "r", "Service Drive": "d", "Alley": "a",
                  "Private": "v", "Vehicular Trail": "t"}
        for road_class, letter in expect.items():
            self.assertEqual(S.classify_library(road_class, _road("X"))[0], letter, road_class)

    def test_non_vehicular_library_classes_are_left_out_with_their_names(self):
        for road_class in ("Walkway/Pedestrian Trail", "Parking Lot", "Stairway", ""):
            cls, reason = S.classify_library(road_class, _road("X", road_class=road_class))
            self.assertIsNone(cls)
            self.assertTrue(reason)

    def test_other_class_rules(self):
        self.assertEqual(S.classify_library("Other", _road("Sheep Mountain", post_type="Road", road_class="Other"))[0],
                         "l")
        self.assertEqual(S.classify_library("Other", _road("Ridge", post_type="Trail", road_class="Other")),
                         (None, "Other: trail"))
        self.assertEqual(S.classify_library("Other", _road("Ferry", road_class="Other")), (None, "Other: ferry"))
        self.assertEqual(S.classify_library("Other", _road("Greers Ferry", post_type="Road", road_class="Other"))[0],
                         "l")
        self.assertEqual(S.classify_library("Other", _road("Driveway", road_class="Other")),
                         (None, "Other: private drive"))
        self.assertEqual(S.classify_library("Other", _road("Pvt1", road_class="Other")),
                         (None, "Other: private drive"))
        self.assertEqual(S.classify_library("Other", _road("Taxiway", road_class="Other")),
                         (None, "Other: airfield surface"))

    def test_census_classes(self):
        for mtfcc, letter in {"S1100": "p", "S1200": "s", "S1400": "l", "S1500": "t", "S1630": "r", "S1640": "d",
                              "S1730": "a", "S1740": "v"}.items():
            self.assertEqual(S.classify_tiger(mtfcc), (letter, None), mtfcc)
        self.assertEqual(S.classify_tiger("S1750"), (None, "S1750"))
        self.assertEqual(S.classify_tiger("S1780"), (None, "S1780"))
        self.assertEqual(S.classify_tiger("S1710"), (None, "S1710"))

    def test_placeholders_are_unnamed(self):
        for name in ("Internal", "Dwy", "Driveway", "DRIVEWAY", "Unknown", "Unnamed", "No Name", "Not Named", ""):
            self.assertTrue(S.is_placeholder(name), name)
        self.assertFalse(S.is_placeholder("Madrid Drive"))
        self.assertFalse(S.is_placeholder("Internal Road Ext"))

    def test_census_names_are_spelled_out(self):
        cases = {"Co Rd 308": "County Road 308", "US Hwy 87": "United States Highway 87",
                 "13th St W": "13th Street West", "Benchland Rd": "Benchland Road", "N 27th St": "North 27th Street",
                 "Chief Black Otter Trl": "Chief Black Otter Trail", "Agri Dr": "Agri Drive",
                 "Antelope Way": "Antelope Way"}
        for raw, shown in cases.items():
            self.assertEqual(S.expand_name(raw), shown, raw)

    def test_library_name_is_in_nena_order(self):
        fields = _library_fields(St_PreDir="North", St_Name="27th", St_PosTyp="Street", St_PreTyp="")
        self.assertEqual(S.library_name(fields), "North 27th Street")


# ---------------------------------------------------------------- the words (D17, D24, D29, D33)

class WordTests(unittest.TestCase):
    def test_legend_lines_are_the_brief_text(self):
        self.assertEqual(S.WORDS_STREETS["msl"]["legend"], "Streets from the Montana State Library's Transportation "
                                                          "Framework; unnamed roads are drawn without a label")
        self.assertEqual(S.WORDS_STREETS["tiger"]["legend"], "Streets from the U.S. Census Bureau's 2026 road files; "
                                                            "unnamed roads are drawn without a label")

    def test_templates_have_no_forbidden_words_outside_quotes(self):
        for kind, words in S.WORDS_STREETS.items():
            for key, template in words.items():
                authored = re.sub(r'"[^"]*"', "", template)
                self.assertIsNone(FORBIDDEN.search(authored), f"{kind}.{key}: {authored!r}")

    def test_the_unavailable_lines_end_with_the_required_sentence(self):   # D41, D89(d)
        for kind, words in S.WORDS_STREETS.items():
            self.assertTrue(words["unavailable"].endswith(" This is not an all-clear."), kind)
            self.assertIn("could not be loaded in this update; that is not the same as having no streets.",
                          words["unavailable"], kind)
        self.assertEqual(S.wording("msl", {})["unavailable"], S.WORDS_STREETS["msl"]["unavailable"])

    def test_the_filled_streets_words_pass_the_one_words_list(self):   # D13, D41, D81(c)
        msl = S.wording("msl", {"pubdate": "2026-09-30", "quotes": {"convenience": S.LIBRARY_CONVENIENCE,
                                                                    "disclaimer": S.LIBRARY_DISCLAIMER}})
        undated = S.wording("msl", {})
        tiger = S.wording("tiger", {"quotes": {}})
        for label, facts in (("msl", msl), ("msl undated", undated), ("tiger", tiger)):
            for key in ("legend", "attribution", "caveat", "unavailable"):
                W.assert_clean(self, facts[key], f"{label}.{key}")

    def test_filled_attribution_quotes_the_file_verbatim(self):
        msl = S.wording("msl", {"pubdate": "2026-09-30", "quotes": {"convenience": S.LIBRARY_CONVENIENCE,
                                                                      "disclaimer": S.LIBRARY_DISCLAIMER}})
        self.assertIn(S.LIBRARY_CONVENIENCE, msl["attribution"])
        self.assertIn("file dated 2026-09-30", msl["attribution"])
        self.assertIn(S.LIBRARY_DISCLAIMER, msl["caveat"])
        tiger = S.wording("tiger", {"quotes": {}})
        self.assertIn(S.TIGER_ACK, tiger["attribution"])
        self.assertIn(S.TIGER_TRADEMARK, tiger["attribution"])
        self.assertIn(S.TIGER_ACCURACY, tiger["caveat"])
        for text in (msl["attribution"], msl["caveat"], tiger["attribution"], tiger["caveat"]):
            self.assertIsNone(FORBIDDEN.search(re.sub(r'"[^"]*"', "", text)), text)

    def test_quotes_are_the_census_iso_wording(self):
        self.assertIn("may not be suitable for high-precision measurement applications such as engineering problems, "
                      "property transfers", S.TIGER_ACCURACY)
        self.assertTrue(S.TIGER_ACCURACY.endswith("earth's surface."))


# ---------------------------------------------------------------- the readers on synthetic files (D25, D36, D16)

@unittest.skipUnless(HAVE_STACK, "the readers project positions with pyproj and numpy")
class ReaderTests(StreetsTestBase):
    def test_reads_fields_and_drops_owner_values(self):
        path = self.tmp / "road.zip"
        owner = "SENTINEL-OWNER-NAME"
        features = [
            {"parts": self.line(600000, 2000000), "fields": _road("Madrid", post_type="Drive", Ownership=owner,
                                                                    LocalID=owner)},
            {"parts": self.line(600000, 2000100), "fields": _road("Driveway", road_class="Private")},
            {"parts": self.line(600000, 2000200), "fields": _road("Trail Ext", post_type="Trail",
                                                                    road_class="Walkway/Pedestrian Trail")},
            {"parts": self.line(600000, 2000300), "fields": _road("Ghost", road_class="Local"), "deleted": True},
            {"null": True, "fields": _road("Nothing", road_class="Local")},
        ]
        write_library_zip(path, features)
        net = S.read_library(path)
        self.assertEqual(net.counts["kept features"], 2)
        self.assertEqual(net.counts["deleted records"], 1)
        self.assertEqual(net.left_out["no geometry"], 1)
        self.assertEqual(net.left_out["Walkway/Pedestrian Trail"], 1)
        self.assertEqual(net.fid_name, ["Madrid Drive", None])     # the placeholder Driveway is unnamed (D16a)
        self.assertEqual(net.raw_placeholder["Driveway"], 1)
        self.assertNotIn(owner, json.dumps(net.facts))            # the owner value is not read anywhere

    def test_changed_field_list_is_unavailable(self):
        path = self.tmp / "changed.zip"
        spec = list(S.LIBRARY_DBF_SPEC)
        spec[-3] = ("AccessX", "C", 50)
        write_library_zip(path, [{"parts": self.line(600000, 2000000), "fields": _road("A")}], spec=spec)
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.read_library(path)
        self.assertIn("field list", str(caught.exception))

    def test_changed_projection_is_unavailable(self):
        path = self.tmp / "prj.zip"
        write_library_zip(path, [{"parts": self.line(600000, 2000000), "fields": _road("A")}],
                          prj_name="Some_Other_Projection")
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.read_library(path)
        self.assertIn("projection", str(caught.exception))

    def test_changed_terms_sentence_is_unavailable(self):
        path = self.tmp / "terms.zip"
        write_library_zip(path, [{"parts": self.line(600000, 2000000), "fields": _road("A")}],
                          useconst="DISCLAIMER: something else entirely.")
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.read_library(path)
        self.assertIn("terms", str(caught.exception))

    def test_county_reader_reads_the_four_fields_and_checks_the_datum(self):
        path = self.tmp / "tl_2026_30111_roads.zip"
        write_county_zip(path, "30111", [
            {"parts": [[(-108.5, 45.78), (-108.49, 45.78)]], "fields": {"LINEARID": "1", "FULLNAME": "Madrid Dr",
                                                                         "RTTYP": "M", "MTFCC": "S1400"}},
            {"parts": [[(-108.5, 45.79), (-108.49, 45.79)]], "fields": {"LINEARID": "2", "FULLNAME": "Internal",
                                                                         "RTTYP": "M", "MTFCC": "S1750"}},
        ])
        net = S.read_tiger([path], strict=False)
        self.assertEqual(net.counts["kept features"], 1)
        self.assertEqual(net.left_out["MTFCC S1750"], 1)
        self.assertEqual(net.fid_name, ["Madrid Drive"])
        self.assertEqual(net.facts["edition"], "2026")

    def test_county_reader_refuses_a_changed_field_list(self):
        path = self.tmp / "tl_2026_30111_roads.zip"
        write_county_zip(path, "30111", [{"parts": [[(-108.5, 45.78), (-108.49, 45.78)]],
                                          "fields": {"MTFCC": "S1400", "FULLNAME": "X"}}])
        changed = self.tmp / "changed" / "tl_2026_30111_roads.zip"
        changed.parent.mkdir()
        spec = [("LINEARID", "C", 22), ("FULLNAMEX", "C", 100), ("RTTYP", "C", 1), ("MTFCC", "C", 5)]
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(changed, "w") as dst:
            for info in src.infolist():
                data = (_dbf_bytes(spec, [(False, {"MTFCC": "S1400"})]) if info.filename.endswith(".dbf")
                        else src.read(info.filename))
                dst.writestr(info.filename, data)
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.read_tiger([changed], strict=False)
        self.assertIn("field list", str(caught.exception))

    def test_tiger_pipeline_names_classes_and_shards(self):
        """Two county files, one line in each, a concurrent pair, a placeholder, an excluded S1750 and a left-out
        S1780: the cleaning and the shards carry the Census rules end to end."""
        import numpy  # noqa: F401
        first = self.tmp / "tl_2026_30111_roads.zip"
        second = self.tmp / "tl_2026_30045_roads.zip"
        write_county_zip(first, "30111", [
            {"parts": [[(-108.500, 45.780), (-108.490, 45.780)]], "fields": {"MTFCC": "S1100", "FULLNAME": "US Hwy 87",
                                                                              "LINEARID": "1", "RTTYP": "S"}},
            {"parts": [[(-108.500, 45.780), (-108.490, 45.780)]], "fields": {"MTFCC": "S1400", "FULLNAME": "Bench Rd",
                                                                              "LINEARID": "2", "RTTYP": "M"}},
            {"parts": [[(-108.500, 45.790), (-108.490, 45.790)]], "fields": {"MTFCC": "S1400", "FULLNAME": "Internal",
                                                                              "LINEARID": "3", "RTTYP": "M"}},
            {"parts": [[(-108.500, 45.800), (-108.490, 45.800)]], "fields": {"MTFCC": "S1780", "FULLNAME": "Lot Road",
                                                                              "LINEARID": "4", "RTTYP": "M"}},
        ])
        write_county_zip(second, "30045", [
            {"parts": [[(-110.050, 47.080), (-110.040, 47.080)]], "fields": {"MTFCC": "S1200", "FULLNAME": "Co Rd 308",
                                                                              "LINEARID": "5", "RTTYP": "C"}},
        ])
        net = S.read_tiger([first, second], strict=False)
        out = S.clean_network(net)
        labels = sorted((p["name"] or "", p["cls"]) for p in out["pieces"])
        self.assertIn(("Bench Road / United States Highway 87", "p"), labels)  # the pair merges, class p wins
        self.assertIn(("County Road 308", "s"), labels)                      # TIGER abbreviations spelled out
        self.assertIn(("", "l"), labels)                                     # "Internal" is unnamed (D16a)
        self.assertEqual(net.left_out["MTFCC S1780"], 1)
        self.assertEqual(out["counts"]["covered chunks"] > 0, True)
        names = out["names"]
        import json as _json
        for piece in out["pieces"]:
            self.assertIsNotNone(piece["lon5"])
        stage = self.tmp / "tiger-stage"
        stage.mkdir()
        for piece in out["pieces"]:
            piece["name_id"] = -1 if piece["name"] is None else names.index(piece["name"])
        result = S.write_shards(stage, out["pieces"], names)
        self.assertEqual(result["shards"], len(list(stage.glob("*.json"))))
        seen = set()
        for shard in stage.glob("*.json"):
            seen.update(_json.loads(shard.read_bytes())["names"])
        self.assertIn("County Road 308", seen)
        self.assertNotIn("Internal", seen)

    def test_county_reader_refuses_a_projected_file(self):
        path = self.tmp / "tl_2026_30111_roads.zip"
        write_county_zip(path, "30111", [{"parts": [[(-108.5, 45.78), (-108.49, 45.78)]],
                                          "fields": {"MTFCC": "S1400", "FULLNAME": "X"}}])
        projected = self.tmp / "projected" / "tl_2026_30111_roads.zip"
        projected.parent.mkdir()
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(projected, "w") as dst:
            for info in src.infolist():
                data = b'PROJCS["NAD83 / Montana"]' if info.filename.endswith(".prj") else src.read(info.filename)
                dst.writestr(info.filename, data)
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.read_tiger([projected], strict=False)
        self.assertIn("NAD83 degrees", str(caught.exception))


# ---------------------------------------------------------------- the cleaning: concurrency, names, simplification (D16)

@unittest.skipUnless(HAVE_STACK, "the cleaning projects positions with pyproj and numpy")
class CleaningTests(StreetsTestBase):
    def clean(self, features, name="state.zip"):
        path = self.tmp / name
        write_library_zip(path, features)
        return S.clean_network(S.read_library(path))

    def test_identical_features_are_one_line_with_names_joined(self):
        parts = self.line(600000, 2000000, length=300.0)
        out = self.clean([
            {"parts": parts, "fields": _road("Main", post_type="Street")},
            {"parts": parts, "fields": _road("Route 3", post_type="Highway", road_class="Primary")},
        ])
        self.assertEqual(len(out["pieces"]), 1)
        self.assertEqual(out["pieces"][0]["name"], "Main Street / Route 3 Highway")
        self.assertEqual(out["pieces"][0]["cls"], "p")           # the more prominent class wins the merge
        self.assertGreaterEqual(out["counts"]["covered chunks"], 1)

    def test_lines_one_metre_apart_merge(self):
        out = self.clean([
            {"parts": self.line(600000, 2000000, length=300.0), "fields": _road("Main", post_type="Street")},
            {"parts": self.line(600000, 2000001, length=300.0), "fields": _road("Bench", post_type="Road")},
        ])
        self.assertEqual(len(out["pieces"]), 1)
        self.assertEqual(out["pieces"][0]["name"], "Bench Road / Main Street")

    def test_lines_ten_metres_apart_stay_apart(self):
        out = self.clean([
            {"parts": self.line(600000, 2000000, length=300.0), "fields": _road("Main", post_type="Street")},
            {"parts": self.line(600000, 2000010, length=300.0), "fields": _road("Bench", post_type="Road")},
        ])
        self.assertEqual(len(out["pieces"]), 2)
        self.assertEqual(sorted(p["name"] for p in out["pieces"]), ["Bench Road", "Main Street"])

    def test_placeholder_name_is_unnamed_and_drawn(self):
        out = self.clean([{"parts": self.line(600000, 2000000), "fields": _road("Unknown")}])
        self.assertEqual(len(out["pieces"]), 1)
        self.assertIsNone(out["pieces"][0]["name"])

    def test_simplification_keeps_every_removed_point_within_two_metres(self):
        rng = random.Random(7)
        for trial in range(20):
            n = rng.randint(3, 400)
            xs, ys = [], []
            for i in range(n):
                xs.append(600000 + i * 3.0 + rng.uniform(-1.0, 1.0))
                ys.append(2000000 + 40 * math.sin(i / 17.0) + rng.uniform(-2.5, 2.5))
            import numpy as np
            keep = S._dp_keep(np.array(xs), np.array(ys), S.DP_TOL_M, np)
            self.assertLess(S.max_deviation(np.array(xs), np.array(ys), keep), S.DP_TOL_M, f"trial {trial}")
            self.assertTrue(keep[0] and keep[-1])

    def test_the_stored_line_stays_within_two_metres_of_every_source_point(self):
        """The store keeps the simplified line rounded to 5 decimals (D14), and its vertices move by up to ROUND_MOVE_M (0.7 m, D48). So
        the bound must hold for the stored line: 1 m samples of each source line lie within DP_TOL_M of the polyline
        that the build writes, read back from the cleaning's output (not from the simplification's own arrays)."""
        import numpy as np
        rng = random.Random(29)
        worst = 0.0
        for trial in range(12):
            n = rng.randint(20, 160)
            xs = [600000 + i * 3.0 for i in range(n)]
            ys = [2000000 + 40 * math.sin(i / 17.0 + trial) + rng.uniform(-2.5, 2.5) for i in range(n)]
            out = self.clean([{"parts": [list(zip(xs, ys))], "fields": _road("Wiggle")}], name=f"wiggle{trial}.zip")
            self.assertEqual(len(out["pieces"]), 1)
            piece = out["pieces"][0]
            stored_x, stored_y = S._forward_inverse(S.LIBRARY_LONLAT, S.LIBRARY_CRS,
                                                    piece["lon5"] / S.SCALE, piece["lat5"] / S.SCALE)
            samples_x, samples_y = [], []
            for (ax, ay), (bx, by) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
                steps = max(1, int(math.hypot(bx - ax, by - ay)))
                t = np.linspace(0.0, 1.0, steps, endpoint=False)
                samples_x.append(ax + t * (bx - ax))
                samples_y.append(ay + t * (by - ay))
            samples_x.append(np.array([xs[-1]]))
            samples_y.append(np.array([ys[-1]]))
            px, py = np.concatenate(samples_x), np.concatenate(samples_y)
            nearest = np.full(len(px), np.inf)
            for k in range(len(stored_x) - 1):
                nearest = np.minimum(nearest, S._segment_distance(px, py, stored_x[k], stored_y[k],
                                                                  stored_x[k + 1], stored_y[k + 1]))
            worst = max(worst, float(nearest.max()))
        self.assertLessEqual(worst, S.DP_TOL_M + 1e-6, f"the worst source sample is {worst:.4f} m from the stored line")

    def test_rounding_moves_a_position_by_at_most_round_move_m_anywhere_in_montana(self):
        """D48: rounding to 5 decimals moves a position by at most ROUND_MOVE_M, measured in the Library's metres. The
        worst case is the southern edge (44.4 N, about 0.68 m); the corners are in the sample."""
        import numpy as np
        rng = np.random.default_rng(11)
        lon = np.concatenate([rng.uniform(-116.05, -104.03, 4000), [-116.05, -104.03, -116.05, -104.03]])
        lat = np.concatenate([rng.uniform(44.47, 49.0, 4000), [44.47, 44.47, 49.0, 49.0]])
        x, y = S._forward_inverse(S.LIBRARY_LONLAT, S.LIBRARY_CRS, lon, lat)
        rounded_lon, rounded_lat = np.rint(lon * S.SCALE) / S.SCALE, np.rint(lat * S.SCALE) / S.SCALE
        rx, ry = S._forward_inverse(S.LIBRARY_LONLAT, S.LIBRARY_CRS, rounded_lon, rounded_lat)
        move = np.hypot(rx - x, ry - y)
        self.assertLessEqual(float(move.max()), S.ROUND_MOVE_M, f"the largest move is {float(move.max()):.4f} m")
        self.assertGreater(float(move.max()), 0.6)            # the sample reaches the bound: it is not a loose figure

    def test_a_straight_run_of_collinear_chunks_becomes_its_endpoints(self):
        out = self.clean([{"parts": self.line(600000, 2000000, length=500.0), "fields": _road("Long")}])
        self.assertEqual(len(out["pieces"]), 1)
        self.assertEqual(len(out["pieces"][0]["lon5"]), 2)

    def test_madrid_drive_is_in_the_library_build(self):
        out = self.clean([{"parts": self.line(600000, 2000000),
                           "fields": _road("Madrid", post_type="Drive", post_comm="Billings")}])
        self.assertIn("Madrid Drive", [p["name"] for p in out["pieces"]])


# ---------------------------------------------------------------- shards: clipping, quadtree, byte split, names (D26)

@unittest.skipUnless(HAVE_STACK, "the shard tests need numpy")
class ShardTests(StreetsTestBase):
    def test_clip_crossing_line_to_the_box(self):
        self.assertEqual(S.clip_line([-500, 1500], [500, 500], (0, 0, 1000, 1000)), [([0, 1000], [500, 500])])
        inside = ([10, 20, 30], [10, 20, 40])
        self.assertEqual(S.clip_line(inside[0], inside[1], (0, 0, 1000, 1000)), [inside])
        self.assertEqual(S.clip_line([-5, -4], [-5, -4], (0, 0, 1000, 1000)), [])

    def test_children_cover_the_parent_and_are_named_by_quarter(self):
        box = (-13000000, 4000000, -12990000, 4010000)
        children = S._children(box)
        self.assertEqual(sorted(children), ["0", "1", "2", "3"])
        self.assertEqual(children["0"][0], box[0])          # north west keeps the west and north edges
        self.assertEqual(children["0"][3], box[3])
        self.assertEqual(children["3"][1], box[1])          # south east keeps the south and east edges
        self.assertEqual(children["3"][2], box[2])
        self.assertLessEqual(children["2"][0], box[0] + 1)
        self.assertGreaterEqual(children["3"][2], box[2] - 1)

    def test_byte_split_keeps_every_shard_under_the_limit_or_at_the_cap(self):
        import numpy as np
        old = S.SHARD_LIMIT
        S.SHARD_LIMIT = 4000
        try:
            pieces, names = [], ["Main Street", "Bench Road"]
            rng = random.Random(3)
            base_lon, base_lat = -108500000 + 2000, 45780000 + 2000
            for i in range(300):
                lat0 = base_lat + rng.randint(0, 8000)
                lon0 = base_lon + rng.randint(0, 8000)
                xs = np.array([lon0 + k * 50 for k in range(20)])
                ys = np.array([lat0 + rng.randint(-30, 30) for _ in range(20)])
                pieces.append({"cls": "l", "name": names[i % 2] if i % 3 else None, "name_id": (i % 2) if i % 3 else -1,
                               "lon5": xs, "lat5": ys})
            stage = self.tmp / "stage"
            stage.mkdir()
            result = S.write_shards(stage, pieces, names)
            self.assertGreater(result["shards"], 1)
            for leaf in stage.glob("*.json"):
                data = leaf.read_bytes()
                depth = len(leaf.stem) - S.TILE_NAME_LEN
                self.assertTrue(len(data) <= S.SHARD_LIMIT or depth >= S.DEPTH_CAP, leaf.name)
                doc = json.loads(data)
                self.assertEqual(doc["f"], S.FORMAT)
                self.assertEqual(doc["n"], len(doc["r"]))
                for cls, idx, pts in doc["r"]:
                    self.assertTrue(idx == -1 or 0 <= idx < len(doc["names"]))
                    self.assertGreaterEqual(len(pts), 2)
            self.assertTrue(all(name.startswith(S.hail.tile_name(0, 0)[:1]) for name in result["names"]))
        finally:
            S.SHARD_LIMIT = old

    def test_name_table_holds_each_name_once_and_minus_one_for_unnamed(self):
        import numpy as np
        pieces = [
            {"cls": "p", "name": "Main Street", "name_id": 0, "lon5": np.array([-10850000, -10849000]),
             "lat5": np.array([4578000, 4578000])},
            {"cls": "l", "name": None, "name_id": -1, "lon5": np.array([-10850000, -10849500]),
             "lat5": np.array([4578100, 4578100])},
            {"cls": "l", "name": "Main Street", "name_id": 0, "lon5": np.array([-10849900, -10849200]),
             "lat5": np.array([4578200, 4578200])},
        ]
        stage = self.tmp / "table"
        stage.mkdir()
        S.write_shards(stage, pieces, ["Main Street"])
        doc = json.loads(next(stage.glob("*.json")).read_bytes())
        self.assertEqual(doc["names"], ["Main Street"])
        self.assertEqual([row[1] for row in doc["r"]], [0, -1, 0])

    def test_tile_index_and_bounds_follow_the_b1_grid(self):
        self.assertEqual(S.TILE_NAME_LEN, 11)
        box_for = (S.COL_LEFT + 0, S.ROW_TOP - S.TILE_UNITS, S.COL_LEFT + S.TILE_UNITS, S.ROW_TOP)
        self.assertEqual(S.hail.tile_name(0, 0), "r0000_c0000")
        self.assertEqual(box_for[0], -13000000)


# ---------------------------------------------------------------- build, verify and the unavailable path (D20, D36)

@unittest.skipUnless(HAVE_STACK, "the build needs numpy and pyproj")
class BuildTests(StreetsTestBase):
    def test_build_writes_the_block_the_manifest_and_verifies(self):
        zip_path = self.tmp / "road.zip"
        features = [
            {"parts": self.line(600000, 2000000, length=400.0), "fields": _road("Madrid", post_type="Drive",
                                                                                  Ownership="SENTINEL-OWNER")},
            {"parts": self.line(600000, 2000000, length=400.0), "fields": _road("Route 3", post_type="Highway",
                                                                                  road_class="Primary")},
            {"parts": self.line(600000, 2000100, length=400.0), "fields": _road("Driveway", road_class="Private")},
            {"parts": self.line(600000, 2000200, length=400.0),
             "fields": _road("Ferry", road_class="Other", post_type="Ferry")},
        ]
        write_library_zip(zip_path, features)
        store = self.make_store()
        block = S.build(store, source="msl", zip_path=zip_path)
        self.assertEqual(block["state"], "loaded")
        self.assertEqual(block["counts"]["kept features"], 3)
        self.assertEqual(block["counts"]["left out Other: ferry"], 1)
        self.assertGreaterEqual(block["shards"], 1)
        index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["roads"]["state"], "loaded")
        manifest = json.loads((store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(any(rel.startswith("hail/r/") for rel in manifest["files"]))
        result = S.verify(store)
        self.assertTrue(result["ok"], [c for c in result["checks"] if not c["ok"]])
        bound = [c for c in result["checks"] if c["check"].startswith("simplification: the gate is 2 m before rounding")]
        self.assertEqual(len(bound), 1)
        self.assertTrue(bound[0]["ok"])
        self.assertIn("2.48 m", bound[0]["check"])              # D48: the measured post-rounding maximum is stated
        self.assertEqual(result["counts"]["post_rounding_max_m_measured"], 2.48)
        # the owner value is never written anywhere in the store (decision 6)
        for path in (store / "hail").rglob("*"):
            if path.is_file():
                self.assertNotIn(b"SENTINEL-OWNER", path.read_bytes(), path.name)
        names = set()
        for shard in (store / "hail" / "r").glob("*.json"):
            names.update(json.loads(shard.read_bytes())["names"])
        self.assertIn("Madrid Drive / Route 3 Highway", names)     # the merged pair, names sorted (D16)
        self.assertEqual(block["counts"]["lines drawn"], 2)         # the merged pair and the unnamed driveway

    def test_build_is_byte_identical_on_a_second_run(self):
        zip_path = self.tmp / "road.zip"
        write_library_zip(zip_path, [{"parts": self.line(600000, 2000000, length=900.0), "fields": _road("Long Road")},
                                     {"parts": self.line(600010, 2000000, length=900.0), "fields": _road("Other Road")}])
        digests = []
        for run in range(2):
            store = self.tmp / f"store{run}"
            (store / "hail").mkdir(parents=True)
            (store / "hail" / "index.json").write_text("{}", encoding="utf-8")
            (store / "hail" / "manifest.json").write_text(json.dumps({"format": "x", "files": {}}), encoding="utf-8")
            S.build(store, source="msl", zip_path=zip_path)
            digests.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted((store / "hail" / "r").glob("*.json"))})
        self.assertEqual(digests[0], digests[1])

    def test_missing_zip_marks_the_roads_unavailable_and_exits_zero(self):
        store = self.make_store()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = S.main(["build", "--store", str(store), "--zip", str(self.tmp / "missing.zip")])
        self.assertEqual(code, 0)
        index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["roads"]["state"], "unavailable")
        self.assertTrue(index["roads"]["source_unavailable"])
        self.assertIn("not there", index["roads"]["reason"])

    def test_unavailable_subcommand_writes_the_reason(self):
        store = self.make_store()
        with contextlib.redirect_stdout(io.StringIO()):
            code = S.main(["unavailable", "--store", str(store), "--reason", "the job crashed"])
        self.assertEqual(code, 0)
        index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["roads"]["reason"], "the job crashed")
        result = S.verify(store)
        self.assertTrue(result["ok"])

    def test_verify_refuses_a_tampered_shard(self):
        zip_path = self.tmp / "road.zip"
        write_library_zip(zip_path, [{"parts": self.line(600000, 2000000, length=400.0), "fields": _road("Main")}])
        store = self.make_store()
        S.build(store, source="msl", zip_path=zip_path)
        shard = next((store / "hail" / "r").glob("*.json"))
        shard.write_bytes(shard.read_bytes().replace(b'"Main"', b'"Mai"'))
        result = S.verify(store)
        self.assertFalse(result["ok"])

    def _three_road_zip(self) -> Path:
        """A three-road Library file that names Madrid Drive, so the shard check passes in the verify runs below."""
        zip_path = self.tmp / "road.zip"
        write_library_zip(zip_path, [
            {"parts": self.line(600000, 2000000, length=400.0), "fields": _road("Madrid", post_type="Drive")},
            {"parts": self.line(600000, 2000100, length=400.0),
             "fields": _road("Route 3", post_type="Highway", road_class="Primary")},
            {"parts": self.line(600000, 2000200, length=400.0), "fields": _road("Bench", post_type="Road")},
        ])
        return zip_path

    def test_record_count_check_fails_by_name_when_the_block_names_another_count(self):
        """data-4 (D36): the recount compares the file's records with the block's. A block that says 258208 for a
        three-record file fails that check by name. Madrid Drive is named, so no other check fails."""
        zip_path = self._three_road_zip()
        store = self.make_store()
        S.build(store, source="msl", zip_path=zip_path)
        block = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["roads"]
        self.assertEqual(block["counts"]["records"], 3)
        block["counts"]["records"] = 258208
        S._wire(store, block)
        result = S.verify(store, source="msl", zip_path=zip_path)
        self.assertEqual([item["check"] for item in result["checks"] if not item["ok"]],
                         ["source record count matches the block"])
        checks = {item["check"]: item for item in result["checks"]}
        self.assertIn("258208 in the block", checks["source record count matches the block"]["detail"])

    def test_record_count_check_passes_when_the_block_matches_the_file(self):
        zip_path = self._three_road_zip()
        store = self.make_store()
        S.build(store, source="msl", zip_path=zip_path)
        result = S.verify(store, source="msl", zip_path=zip_path)
        checks = {item["check"]: item for item in result["checks"]}
        self.assertTrue(checks["source record count matches the block"]["ok"])
        self.assertTrue(result["ok"], [item for item in result["checks"] if not item["ok"]])

    def test_verify_with_a_zip_recounts_the_records_without_a_source_flag(self):
        """data-9: the default source is msl (the job's verify step passes it too), so verify --zip recounts."""
        zip_path = self._three_road_zip()
        store = self.make_store()
        S.build(store, source="msl", zip_path=zip_path)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = S.main(["verify", "--store", str(store), "--zip", str(zip_path)])
        self.assertEqual(code, 0, err.getvalue())
        names = [item["check"] for item in json.loads(out.getvalue())["checks"]]
        self.assertIn("source record count matches the block", names)

    def test_the_printed_summary_has_a_number_for_every_count_it_names(self):
        """job-18: the summary the build prints has a value, not null, for each count it names. "left out no geometry"
        is absent from the block when nothing is left out, so it prints 0 then, and 1 when a record has no shape."""
        roads = [{"parts": self.line(600000, 2000000, length=400.0), "fields": _road("Main", post_type="Street")},
                 {"parts": self.line(600000, 2000000, length=400.0),
                  "fields": _road("Route 3", post_type="Highway", road_class="Primary")}]

        def summary_for(name, features):
            zip_path = self.tmp / f"{name}.zip"
            write_library_zip(zip_path, features)
            store = self.make_store(name)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = S.main(["build", "--store", str(store), "--zip", str(zip_path)])
            self.assertEqual(code, 0, err.getvalue())
            return json.loads(out.getvalue())

        plain = summary_for("plain", roads)
        with_null = summary_for("null", roads + [{"null": True, "fields": _road("Nothing", road_class="Local")}])
        for summary in (plain, with_null):
            self.assertNotIn("concurrent lines merged", summary)
            for key in ("records", "kept features", "left out no geometry", "chunks", "covered chunks",
                        "features with a covered piece", "lines drawn", "vertices after simplification"):
                self.assertIsNotNone(summary[key], key)
        self.assertEqual(plain["left out no geometry"], 0)
        self.assertEqual(with_null["left out no geometry"], 1)


@unittest.skipUnless(HAVE_NUMPY, "the reader needs numpy; pyproj is not needed, the test hides it")
class ProjectionMissingTests(StreetsTestBase):
    def test_a_missing_projection_library_marks_the_roads_unavailable_and_exits_zero(self):
        """data-11 (D36): the lazy import of pyproj is a source failure, not a traceback. The test hides pyproj
        whether or not it is installed, so it runs in every environment."""
        zip_path = self.tmp / "road.zip"
        write_library_zip(zip_path, [{"parts": self.line(600000, 2000000, length=400.0),
                                      "fields": _road("Madrid", post_type="Drive")}])
        store = self.make_store()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(sys.modules, {"pyproj": None}), mock.patch.dict(S._TRANSFORMERS, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = S.main(["build", "--store", str(store), "--zip", str(zip_path)])
        self.assertEqual(code, 0, err.getvalue())
        block = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["roads"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIs(block["source_unavailable"], True)
        self.assertEqual(block["reason"], f"{S.UNAVAILABLE}: the projection library is not installed")
        self.assertFalse((store / "hail" / "r").exists())


class _FakeHead:
    def __init__(self, status_code, headers):
        self.status_code = status_code
        self.headers = headers


class _FakeSession:
    def __init__(self, status_code, headers, error):
        self.status_code, self.headers, self.error = status_code, headers, error

    def head(self, url, allow_redirects=True, timeout=None):
        if self.error is not None:
            raise self.error
        return _FakeHead(self.status_code, dict(self.headers))


class _FakeFetcher:
    """Stands in for sources.Fetcher, with no network: HEAD answers from the given headers, and binary() returns the
    bytes it was given and counts its calls."""

    def __init__(self, data, *, status_code=200, headers=None, error=None):
        self.s = _FakeSession(status_code, headers or {}, error)
        self.timeout = 5
        self.data = data
        self.gets = []

    def binary(self, url, headers=None):
        self.gets.append(url)
        return self.data, None


class DownloadTests(StreetsTestBase):
    """download_one (D20, D24): a cached copy is used only when its meta file matches the name, the size and the
    Last-Modified header. Otherwise the file is fetched once and its meta is written. No network: a fake fetcher."""
    URL = "https://example.test/roads/TransportationFramework_shp.zip"
    NAME = "TransportationFramework_shp.zip"
    MODIFIED = "Mon, 28 Sep 2026 10:00:00 GMT"
    NEW = b"PK" + b"1" * 98

    def fetcher(self, data=None, *, length=None, status_code=200, error=None):
        headers = {"Content-Length": str(len(self.NEW) if length is None else length), "Last-Modified": self.MODIFIED}
        return _FakeFetcher(self.NEW if data is None else data, status_code=status_code, headers=headers, error=error)

    def test_a_same_size_cached_file_with_no_meta_is_fetched_again(self):
        cache = self.tmp / "cache"
        cache.mkdir()
        (cache / self.NAME).write_bytes(b"PK" + b"0" * 98)            # the server's size, but not the server's file
        fetcher = self.fetcher()
        path, info = S.download_one(cache, self.NAME, self.URL, fetcher=fetcher)
        self.assertEqual(info["cache"], "fetched")
        self.assertEqual(path.read_bytes(), self.NEW)                  # the bytes kept are the bytes served
        meta = json.loads((cache / (self.NAME + ".meta.json")).read_text(encoding="utf-8"))
        self.assertEqual(meta["last_modified"], self.MODIFIED)
        _path, again = S.download_one(cache, self.NAME, self.URL, fetcher=fetcher)
        self.assertEqual(again["cache"], "hit")
        self.assertEqual(fetcher.gets, [self.URL])                     # one GET in all: the second call is a hit

    def test_a_meta_file_that_matches_is_a_hit_with_no_request(self):
        cache = self.tmp / "cache"
        cache.mkdir()
        (cache / self.NAME).write_bytes(self.NEW)
        (cache / (self.NAME + ".meta.json")).write_text(json.dumps(
            {"name": self.NAME, "bytes": len(self.NEW), "size": len(self.NEW), "last_modified": self.MODIFIED}),
            encoding="utf-8")
        fetcher = self.fetcher()
        _path, info = S.download_one(cache, self.NAME, self.URL, fetcher=fetcher)
        self.assertEqual(info["cache"], "hit")
        self.assertEqual(fetcher.gets, [])

    def test_a_meta_file_with_another_last_modified_is_fetched_again(self):
        cache = self.tmp / "cache"
        cache.mkdir()
        (cache / self.NAME).write_bytes(self.NEW)
        (cache / (self.NAME + ".meta.json")).write_text(json.dumps(
            {"name": self.NAME, "bytes": len(self.NEW), "size": len(self.NEW),
             "last_modified": "Sun, 01 Feb 2026 00:00:00 GMT"}), encoding="utf-8")
        fetcher = self.fetcher()
        _path, info = S.download_one(cache, self.NAME, self.URL, fetcher=fetcher)
        self.assertEqual(info["cache"], "fetched")
        self.assertEqual(fetcher.gets, [self.URL])

    def test_a_head_that_raises_is_unavailable_with_the_reason(self):
        fetcher = self.fetcher(error=ConnectionError("no route to host"))
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.download_one(self.tmp / "cache", self.NAME, self.URL, fetcher=fetcher)
        self.assertIn(S.UNAVAILABLE, str(caught.exception))
        self.assertIn(f"the download of {self.NAME} did not answer (ConnectionError)", str(caught.exception))
        self.assertEqual(fetcher.gets, [])

    def test_a_head_that_answers_an_error_status_is_unavailable(self):
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.download_one(self.tmp / "cache", self.NAME, self.URL, fetcher=self.fetcher(status_code=503))
        self.assertIn("answered HTTP 503", str(caught.exception))

    def test_a_download_of_another_size_or_not_a_zip_is_unavailable_and_writes_nothing(self):
        cache = self.tmp / "cache"
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.download_one(cache, self.NAME, self.URL, fetcher=self.fetcher(length=len(self.NEW) + 5))
        self.assertIn("not the size the server gave", str(caught.exception))
        self.assertFalse((cache / self.NAME).exists())
        self.assertFalse((cache / (self.NAME + ".meta.json")).exists())
        html = b"<html>not a zip</html>"
        with self.assertRaises(S.SourceUnavailable) as caught:
            S.download_one(cache, self.NAME, self.URL, fetcher=self.fetcher(data=html, length=len(html)))
        self.assertIn("not a zip file", str(caught.exception))
        self.assertFalse((cache / self.NAME).exists())


class LeftoverTests(StreetsTestBase):
    def test_an_interrupted_build_leaves_nothing_under_hail_that_the_manifest_does_not_list(self):
        """job-2: a roads build stopped while it writes its shards leaves hail/.r-stage and hail/.streets-* files. The
        unavailable command (the job's failure branch) removes them, so the store's own check passes again."""
        store = self.tmp / "store"
        hail.fixture_store(store)
        hail.check_manifest(store)
        (store / "hail" / ".r-stage").mkdir()
        (store / "hail" / ".r-stage" / "r0059_c0139.json").write_text("{}", encoding="utf-8")
        (store / "hail" / ".streets-12345").write_bytes(b"part of an index")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = S.main(["unavailable", "--store", str(store), "--reason", "the build was interrupted"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertFalse((store / "hail" / ".r-stage").exists())
        self.assertFalse((store / "hail" / ".streets-12345").exists())
        hail.check_manifest(store)
        block = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["roads"]
        self.assertEqual(block["state"], "unavailable")


# ---------------------------------------------------------------- the site's words and map data, the workflow (D27, D33)

class SiteTests(unittest.TestCase):
    def test_map_data_when_unavailable_has_the_templates(self):
        data = S.map_data_streets({"roads": {"state": "unavailable", "reason": "x"}})
        self.assertEqual(data["state"], "unavailable")
        self.assertIn("unavailable", data["templates"])

    def test_map_data_carries_zoom_rules_and_widths(self):
        block = {"format": S.FORMAT, "state": "loaded", "kind": "msl", "tiles": ["r0092_c0213"],
                 "split": {"r0092_c0213": ["r0092_c0213" + "0", "r0092_c0213" + "1"]}, "shards": 2,
                 "counts": {"lines drawn": 3}, "source": {"file": "x.zip", "pubdate": "2026-09-30"},
                 "wording": S.wording("msl", {"pubdate": "2026-09-30", "quotes": {}}),
                 "classes": {}, "quotes": {}}
        data = S.map_data_streets({"roads": block})
        self.assertEqual(data["state"], "loaded")
        self.assertEqual(data["zoom"]["arterials_from"], 13)
        self.assertEqual(data["zoom"]["local_from"], 15)
        self.assertEqual(data["zoom"]["names_from"], 16)
        self.assertEqual(data["zoom"]["outline_emphasis_from"], 17)
        self.assertEqual(data["classes"]["p"]["min_zoom"], 13)
        self.assertEqual(data["classes"]["l"]["min_zoom"], 15)
        self.assertEqual(data["shard"], "hail/r/{name}.json")
        self.assertIn("hwy", data["abbreviations"])

    def test_describe_states_the_source_and_the_quote(self):
        block = {"format": S.FORMAT, "state": "loaded", "kind": "tiger",
                 "wording": S.wording("tiger", {"quotes": {}})}
        text = S.describe_streets({"roads": block})
        self.assertIn("U.S. Census Bureau", text["attribution"])
        self.assertEqual(S.describe_streets({})["state"], "unavailable")

    def test_workflow_has_the_streets_step_with_the_source_and_no_double_equals(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python -m website.streets build --store store", text)
        self.assertIn("--roads-source msl", text)
        self.assertIn("python -m website.streets verify", text)
        self.assertIn("python -m website.streets unavailable", text)
        self.assertNotIn("==", text)                       # decision D19: no pins in the job text
        self.assertLess(text.index("website.streets build"), text.index("website.addresses build"))


@unittest.skipUnless(HAVE_STACK and REAL_LIBRARY.is_file(), "the real Library file is not cached here")
class RealLibraryTests(unittest.TestCase):
    """Reads the cached state file (about two minutes). The figures are the B3 brief's, measured on the 2026-09-30
    file; they run only when the cache is present and are the build's own measures, not a copy of them."""

    def test_library_records_and_madrid(self):
        net = S.read_library(REAL_LIBRARY)
        self.assertEqual(net.counts["records"] + net.counts["deleted records"], 258208)
        self.assertIn("Madrid Drive", net.fid_name)


if __name__ == "__main__":
    unittest.main()
