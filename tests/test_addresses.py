"""Address data (website/addresses.py, B3): the field allow-list (no owner, parcel or place-type field is read), the
reader on a synthetic framework zip the test writes itself (a .shp of point records, a .shx, a .dbf with the 51 field
names of the MSL file in order and their lengths, the .prj, _ReadMe.txt with the export date, and a metadata XML with the
three quoted sentences), the address line (D3), the city and zip (D4), the counts (left out, merged, rows), the shards
(the quadtree on the 0.1-degree tiles, names and bounds, D5), the search index (city and letter files, the two-character
split, the slug, words.json, D6), the unavailable state on a changed field list or projection, the words (forbidden
terms, the quoted metadata sentences and the About's exclusion sentence excepted by exact text, D8, D12), the projection
pairs (D2, within 2 m), verify (the counts, the manifest hashes, a tampered shard), the workflow's step order, the
committed fixture (D10: under 50 KB) and the command line.

No network. Each test that writes files makes its own temporary folder and removes only that folder (decision 7 of
hail-build-brief). The projection and build tests need pyproj and skip without it; the job always has it (D9)."""

import contextlib
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from website import addresses as A
from website import hail

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "website" / "data" / "hail-fixture"
WORKFLOW = ROOT / ".github" / "workflows" / "hail-store.yml"
try:
    import pyproj  # noqa: F401
    HAVE_PYPROJ = True
except ImportError:
    HAVE_PYPROJ = False
try:
    import yaml
except ImportError:
    yaml = None
_ABSENT = object()

# ---------------------------------------------------------------- the names the module exports (adapter block)
# The brief fixes the API by role. If the module names a thing differently, change it here and nowhere else.
ALLOW = A.ALLOWED_FIELDS                 # the allow-list (D1): the sixteen fields the reader slices
FORBIDDEN = A.FORBIDDEN_FIELDS           # the fields that are never read, stored or shown (D1, decision 6)
SLICES = A.FIELD_SLICES                  # the reader's slice table: {field: (start, end)} inside a DBF record
WORDS = A.WORDS_ADDRESSES                # every sentence the addresses layer shows (D8, D12)

# ---------------------------------------------------------------- the MSL file's facts (pre-check, 2026-10-19)
DBF_FIELDS = [
    ("DiscrpAgID", "C", 100, 0), ("DateUpdate", "D", 8, 0), ("Effective", "D", 8, 0), ("Expire", "D", 8, 0),
    ("NGUID", "C", 254, 0), ("Country", "C", 2, 0), ("State", "C", 2, 0), ("County", "C", 100, 0),
    ("Inc_Muni", "C", 100, 0), ("Uninc_Comm", "C", 100, 0), ("Nbrhd_Comm", "C", 100, 0), ("AddNum_Pre", "C", 15, 0),
    ("Add_Number", "N", 10, 0), ("AddNum_Suf", "C", 15, 0), ("St_PreMod", "C", 15, 0), ("St_PreDir", "C", 10, 0),
    ("St_PreTyp", "C", 50, 0), ("St_PreSep", "C", 20, 0), ("St_Name", "C", 254, 0), ("St_PosTyp", "C", 50, 0),
    ("St_PosDir", "C", 10, 0), ("St_PosMod", "C", 25, 0), ("LSt_PreDir", "C", 2, 0), ("LSt_Name", "C", 75, 0),
    ("LSt_Typ", "C", 4, 0), ("LSt_PosDir", "C", 2, 0), ("Post_Comm", "C", 40, 0), ("Post_Code", "C", 7, 0),
    ("PostCodeEx", "C", 4, 0), ("Building", "C", 75, 0), ("Floor", "C", 75, 0), ("Unit", "C", 75, 0),
    ("Room", "C", 75, 0), ("Seat", "C", 75, 0), ("Addtl_Loc", "C", 225, 0), ("LandmkName", "C", 150, 0),
    ("Milepost", "C", 150, 0), ("Place_Type", "C", 50, 0), ("Placement", "C", 25, 0), ("Longitude", "N", 19, 8),
    ("Latitude", "N", 19, 8), ("Elevation", "N", 10, 0), ("MT_PlcType", "N", 10, 0), ("ParcelID", "C", 17, 0),
    ("LocalID", "C", 38, 0), ("Addtl_Desc", "C", 254, 0), ("GNIS_ID", "C", 10, 0), ("DatasetTyp", "C", 25, 0),
    ("ProcessID", "N", 10, 0), ("ProcessDte", "D", 8, 0), ("GlobalID", "C", 38, 0),
]
DBF_RECORD_BYTES = 2824                  # the flag byte plus the field lengths (the MSL file's record length)
ALLOW_EXPECTED = {"Add_Number", "AddNum_Pre", "AddNum_Suf", "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
                  "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod", "Post_Comm", "Post_Code", "Inc_Muni", "County",
                  "Unit", "Placement"}                # the seventeen fields of D1 and D32 (Placement: the class)
FORBIDDEN_EXPECTED = {"ParcelID", "LocalID", "NGUID", "GlobalID", "Place_Type", "MT_PlcType", "LandmkName",
                      "Addtl_Desc", "Addtl_Loc", "GNIS_ID", "Latitude", "Longitude", "DiscrpAgID"}
PRJ = ('PROJCS["NAD_1983_2011_StatePlane_Montana_FIPS_2500",GEOGCS["GCS_NAD_1983_2011",DATUM["D_NAD_1983_2011",'
       'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
       'PROJECTION["Lambert_Conformal_Conic"],PARAMETER["False_Easting",600000.0],PARAMETER["False_Northing",0.0],'
       'PARAMETER["Central_Meridian",-109.5],PARAMETER["Standard_Parallel_1",45.0],'
       'PARAMETER["Standard_Parallel_2",49.0],PARAMETER["Latitude_Of_Origin",44.25],UNIT["Meter",1.0]]')
README = ("*****\r\n\r\nThe Montana Structures Framework data contained in this zip file were exported from the Montana "
          "State Library enterprise geodatabase on 20260930.\r\n\r\nThe Structures Framework downloads are exported "
          "monthly, around the end of the month (the exact date varies).\r\n")
# The three quoted sentences, as the file's metadata gives them (quoted exactly; D8).
ACCCONST = "None. All data contained in the Framework are publicly available and non-sensitive."
USECONST = ("DISCLAIMER: The Montana State Library Geographic Information Services provides this product/service for "
            "informational purposes only. The Library did not produce it for, nor is it suitable for legal, "
            "engineering, or surveying purposes. Consumers of this information should review or consult the primary "
            "data and information sources to ascertain the viability of the information for their purposes. The "
            "Library provides these data in good faith but does not represent or warrant its accuracy, adequacy, or "
            "completeness. In no event shall the Library be liable for any incorrect results or analysis; any direct, "
            "indirect, special, or consequential damages to any party; or any lost profits arising out of or in "
            "connection with the use or the inability to use the data or the services provided. The Library makes "
            "these data and services available as a convenience to the public, and for no other purpose. The Library "
            "reserves the right to change or revise published data and/or services at any time.")
PURPOSE = ("To provide a statewide, standardized repository for structure and address point data. The "
           "Structures/Addresses Framework complies with the NENA Standard for NG9-1-1 GIS Data Model and is designed "
           "to support a wide range of public and private sector uses including: 9-1-1 and emergency response, "
           "elections management, broadband internet mapping, census programs, planning, natural resource studies, "
           "etc.")
QUOTED = (ACCCONST, "The Library makes these data and services available as a convenience to the public, and for no "
          "other purpose.", "The Montana State Library Geographic Information Services provides this product/service "
          "for informational purposes only. The Library did not produce it for, nor is it suitable for legal, "
          "engineering, or surveying purposes.")
ABOUT_EXCLUSION = "Owner names and parcel identifiers are never read, stored or shown."

# Synthetic positions: EPSG:6514 metres and the lon/lat they give (pyproj 3.8.0, always_xy), chosen off the grid's
# rounding edges so each falls in one 0.1-degree tile. A is 401 North 27th Street's neighbourhood (tile r0092_c0214).
POS = {
    "A": (677493.6650499215, 171417.4559773415, -108.503, 45.788),         # tile r0092_c0214
    "B": (677497.4804688215, 171423.06023597406, -108.50295, 45.78805),    # tile r0092_c0214
    "C": (619672.6083644092, 481578.27016397985, -109.2333, 48.5834),      # tile r0064_c0207 (Chinook)
    "D": (416564.16811992484, 520845.83601406537, -112.003, 48.9105),      # tile r0060_c0179 (Glacier County)
    "E": (654798.8244158938, 117079.73262439056, -108.8012, 45.3012),      # tile r0096_c0211 (Red Lodge)
    # The three recorded projection pairs' records, at their file positions: the build finds each once (D2).
    "M": (255597.15399999917, 298707.32660000026, -114.02078244268027, 46.84868062644647),   # 1611 South Avenue West
    "R": (676384.9230000004, 274679.25730000064, -108.50030774199726, 46.717503918061354),   # 500 Colony Road
    "H": (404013.22619999945, 264755.8504000008, -112.05996955887122, 46.60374035148729),    # 1617 Euclid Avenue Unit 4
}
# The three recorded projection pairs (D2): the file's EPSG:6514 position of the record and the live map service's
# lon/lat for the same NGUID (msdi_structures_addresses_map_v1, outSR=4326, queried 2026-10-19).
PAIRS = [
    {"name": "1611 South Avenue West, Missoula", "nguid": "99063000.{3721951F-7232-40A5-91F1-406973B01490}",
     "x": 255597.15399999917, "y": 298707.32660000026, "live": (-114.02079563702587, 46.84868711344614)},
    {"name": "500 Colony Road, Roundup", "nguid": "99065000.109",
     "x": 676384.9230000004, "y": 274679.25730000064, "live": (-108.5003197130036, 46.71751092724771)},
    {"name": "1617 Euclid Avenue Unit 4, Helena", "nguid": "99049000.ADR032563",
     "x": 404013.22619999945, "y": 264755.8504000008, "live": (-112.05998229436645, 46.6037470105732)},
]
DATA_DBF_NAME = "SiteStructureAddressPoint.dbf"


def row(pos, **attrs):
    """One synthetic record: its position key in POS (None for a null shape) and its attribute values by field name."""
    return {"pos": pos, "attrs": attrs}


def deleted_row(pos, **attrs):
    """A synthetic record marked deleted in the table (the flag byte is an asterisk; D1 leaves it out)."""
    return {"pos": pos, "attrs": attrs, "deleted": True}


def base_rows() -> list:
    """The synthetic rows the brief asks for. Expected output is in BASE_LINES (dot records) and the counts."""
    billings = {"Post_Comm": "Billings", "Post_Code": "59101", "State": "MT"}
    return [
        row("A", Add_Number=401, St_PreDir="North", St_Name="27th", St_PosTyp="Street", **billings),
        row("A", Add_Number=401, St_PreDir="North", St_Name="27th", St_PosTyp="Street", **billings),   # exact duplicate
        row("A", Add_Number=401, St_PreDir="North", St_Name="27th", St_PosTyp="Street", Unit="UNIT A", **billings),
        row("B", Add_Number=401, St_PreDir="North", St_Name="27th", St_PosTyp="Street", Unit="A", **billings),
        row("A", Add_Number=12, Post_Comm="Billings", Post_Code="59101"),                              # blank street
        row("C", Add_Number=25, St_Name="Main", St_PosTyp="Street", Inc_Muni="Chinook", Post_Code="59523",
            County="Blaine County"),                                                                  # blank Post_Comm
        row("D", Add_Number=3, St_Name="Colony", St_PosTyp="Road", Inc_Muni="Unincorporated",
            County="Glacier County"),                                                                 # the county
        row("E", Add_Number=1234, St_PreTyp="United States Highway", St_Name="212", Post_Comm="Red Lodge",
            Post_Code="590681"),                                                                      # 6-character zip
        row("A", Add_Number=401, AddNum_Suf="1/2", St_PreDir="North", St_Name="27th", St_PosTyp="Street",
            **billings),
        row("A", Add_Number=0, St_PreDir="North", St_Name="27th", St_PosTyp="Street", **billings),     # number 0
        row("A", Add_Number=401, AddNum_Suf="A", St_PreDir="North", St_Name="27th", St_PosTyp="Street",
            **billings),
        row(None, Add_Number=77, St_Name="Ash", St_PosTyp="Street", **billings),                       # null shape
        row("M", Add_Number=1611, St_Name="South", St_PosTyp="Avenue", St_PosDir="West", Post_Comm="Missoula",
            Post_Code="59801", County="Missoula County"),                                             # pair 1
        row("R", Add_Number=500, St_Name="Colony", St_PosTyp="Road", Post_Comm="Roundup", Post_Code="59072",
            Inc_Muni="Unincorporated", County="Musselshell County"),                                  # pair 2
        row("H", Add_Number=1617, St_Name="Euclid", St_PosTyp="Avenue", Post_Comm="Helena", Post_Code="59601",
            Unit="UNIT 4", Inc_Muni="Helena", County="Lewis and Clark County"),                       # pair 3
    ]


def pair_rows() -> list:
    """The three projection-pair records (D2): every synthetic build needs them for its projection check."""
    return [item for item in base_rows() if item["pos"] in ("M", "R", "H")]


# The dot records the rows above must give, in row order, with the rows that are left out or merged removed (D3, D4).
BASE_LINES = [
    (POS["A"][2], POS["A"][3], "401 North 27th Street", "Billings", "59101"),
    (POS["A"][2], POS["A"][3], "401 North 27th Street Unit A", "Billings", "59101"),
    (POS["B"][2], POS["B"][3], "401 North 27th Street Unit A", "Billings", "59101"),
    (POS["C"][2], POS["C"][3], "25 Main Street", "Chinook", "59523"),
    (POS["D"][2], POS["D"][3], "3 Colony Road", "Glacier County", ""),
    (POS["E"][2], POS["E"][3], "1234 United States Highway 212", "Red Lodge", ""),
    (POS["A"][2], POS["A"][3], "401 1/2 North 27th Street", "Billings", "59101"),
    (POS["A"][2], POS["A"][3], "North 27th Street", "Billings", "59101"),
    (POS["A"][2], POS["A"][3], "401A North 27th Street", "Billings", "59101"),
    (POS["M"][2], POS["M"][3], "1611 South Avenue West", "Missoula", "59801"),
    (POS["R"][2], POS["R"][3], "500 Colony Road", "Roundup", "59072"),
    (POS["H"][2], POS["H"][3], "1617 Euclid Avenue Unit 4", "Helena", "59601"),
]


def _dbf_bytes(rows: list, fields: list = DBF_FIELDS) -> bytes:
    """A dBASE III table with the MSL field list (names, types and lengths in order), one record per row."""
    hlen = 32 + 32 * len(fields) + 1
    rlen = 1 + sum(length for _n, _t, length, _d in fields)
    if rlen != DBF_RECORD_BYTES:
        raise AssertionError(f"the test's field list is {rlen} bytes a record, not {DBF_RECORD_BYTES}")
    head = struct.pack("<BBBBIHH", 0x03, 26, 10, 19, len(rows), hlen, rlen) + b"\x00" * 20
    for name, kind, length, dec in fields:
        head += (name.encode("ascii").ljust(11, b"\x00")[:11] + kind.encode("ascii") + b"\x00" * 4
                 + bytes([length, dec]) + b"\x00" * 14)
    head += b"\x0d"
    body = b""
    for item in rows:
        record = b"*" if item.get("deleted") else b" "
        for name, kind, length, _dec in fields:
            value = item["attrs"].get(name, "")
            if kind == "N":
                text = "" if value == "" else str(value)
                record += text.rjust(length).encode("ascii")[:length]
            elif kind == "D":
                record += b" " * length
            else:
                record += str(value).encode("latin-1")[:length].ljust(length)
        body += record
    return head + body + b"\x1a"


def _shp_bytes(rows: list) -> tuple[bytes, bytes]:
    """The .shp and .shx of point records (type 1); a row with pos None is a null shape (type 0)."""
    records, index = [], []
    offset = 100
    points = [POS[item["pos"]][:2] for item in rows if item["pos"] is not None]
    for number, item in enumerate(rows, start=1):
        if item["pos"] is None:
            content = struct.pack("<i", 0)
        else:
            x, y = POS[item["pos"]][:2]
            content = struct.pack("<idd", 1, x, y)
        header = struct.pack(">ii", number, len(content) // 2)
        index.append(struct.pack(">ii", offset // 2, len(content) // 2))
        records.append(header + content)
        offset += 8 + len(content)
    xs = [p[0] for p in points] or [0.0]
    ys = [p[1] for p in points] or [0.0]
    bbox = struct.pack("<4d", min(xs), min(ys), max(xs), max(ys))

    def header(file_bytes: int) -> bytes:
        return (struct.pack(">i", 9994) + b"\x00" * 20 + struct.pack(">i", file_bytes // 2)
                + struct.pack("<ii", 1000, 1) + bbox + struct.pack("<4d", 0, 0, 0, 0))

    shp_body = b"".join(records)
    shx_body = b"".join(index)
    return header(100 + len(shp_body)) + shp_body, header(100 + len(shx_body)) + shx_body


def make_zip(path: Path, rows: list, *, prj: str = PRJ, dbf_fields: list | None = None,
             readme: str = README, useconst: str = USECONST, accconst: str = ACCCONST, purpose: str = PURPOSE) -> Path:
    """Write a synthetic framework zip at path with the members the reader needs (the caller's own folder only)."""
    dbf = _dbf_bytes(rows, dbf_fields if dbf_fields is not None else DBF_FIELDS)
    shp, shx = _shp_bytes(rows)
    meta = ("<?xml version=\"1.0\"?><metadata><idinfo><citation><citeinfo><pubdate>20260930</pubdate></citeinfo>"
            "</citation><descript><purpose>" + purpose + "</purpose></descript><accconst>" + accconst +
            "</accconst><useconst>" + useconst + "</useconst></idinfo></metadata>")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SiteStructureAddressPoint.shp", shp)
        zf.writestr("SiteStructureAddressPoint.shx", shx)
        zf.writestr(DATA_DBF_NAME, dbf)
        zf.writestr("SiteStructureAddressPoint.prj", prj)
        zf.writestr("_ReadMe.txt", readme)
        zf.writestr("StructuresFramework_metadata.xml", meta)
    return path


def copy_zip_with(src: Path, dst: Path, member: str, data: bytes) -> Path:
    """Copy a synthetic zip, replacing one member's bytes (used to damage a table in a test)."""
    with zipfile.ZipFile(src) as old, zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as new:
        for info in old.infolist():
            new.writestr(info.filename, data if info.filename == member else old.read(info.filename))
    return dst


def _ascii_ok(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def check_terms(test: unittest.TestCase, text: str) -> None:
    """No forbidden term in a sentence the site shows. The quoted metadata sentences, the About's exclusion sentence and
    the D23 sentence (which says no history is kept, not that there was no hail) are removed by exact text first (D8);
    "no hail" and "all clear" appear only in a sentence that negates them."""
    stripped = text
    for quoted in QUOTED + (ABOUT_EXCLUSION, WORDS["outside_grid"]):
        stripped = stripped.replace(quoted, "")
    forbidden = re.compile(r"\b(owners?|residen\w*|lives?|tenants?|occupan\w*|parcels?|values?|sales?|mortgag\w*|"
                           r"damag\w*|claims?|insurance|eligib\w*|confirm\w*|homes?|houses?|business\w*|commercial"
                           r"|guarantee\w*|dwell\w*|housing|building use)\b", re.IGNORECASE)
    test.assertIsNone(forbidden.search(stripped), f"forbidden term in: {text!r}")
    for sentence in re.split(r"(?<=[.!?])\s+", stripped):
        if re.search(r"\bno hail\b", sentence, re.IGNORECASE):
            test.assertRegex(sentence, r"\bnot\b", f"'no hail' without a negation: {sentence!r}")
        if re.search(r"all[- ]clear", sentence, re.IGNORECASE):
            test.assertRegex(sentence, r"not an? all[- ]clear", f"'all clear' as a claim: {sentence!r}")


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    radius = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


@contextlib.contextmanager
def projection_library_missing():
    """pyproj as a missing package: importing it raises ModuleNotFoundError (a None entry in sys.modules, D36). The
    transformer cache is emptied inside the block and put back after it, so other tests keep their transformer."""
    saved_module = sys.modules.get("pyproj", _ABSENT)
    saved_cache = dict(A._TRANSFORMER)
    sys.modules["pyproj"] = None
    A._TRANSFORMER.clear()
    try:
        yield
    finally:
        if saved_module is _ABSENT:
            sys.modules.pop("pyproj", None)
        else:
            sys.modules["pyproj"] = saved_module
        A._TRANSFORMER.clear()
        A._TRANSFORMER.update(saved_cache)


class TempFolderMixin:
    """Each test gets its own folder, and tearDown removes that folder and nothing else (decision 7)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="addresses-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- the allow-list and the reader's slices

class AllowListTests(unittest.TestCase):
    def test_the_allow_list_is_the_seventeen_fields_of_d1_and_d32(self):
        self.assertEqual(set(ALLOW), ALLOW_EXPECTED)
        self.assertEqual(len(ALLOW), 17)

    def test_the_allow_list_excludes_every_forbidden_field(self):
        self.assertEqual(set(ALLOW) & set(FORBIDDEN), set())

    def test_the_forbidden_list_names_the_fields_of_d1(self):
        self.assertTrue(FORBIDDEN_EXPECTED <= set(FORBIDDEN), FORBIDDEN_EXPECTED - set(FORBIDDEN))

    def test_no_name_in_the_allow_list_is_an_owner_or_a_parcel_or_a_place_type_field(self):
        # "Placement" is the placement class (D32), not the place type: only Place_Type and MT_PlcType are place types.
        for name in ALLOW:
            self.assertNotRegex(name, r"(?i)owner|parcel|place_?type|nguid|global|local|landmark|addtl_desc|gnis")

    def test_placement_is_read_and_is_not_the_place_type(self):
        self.assertIn("Placement", ALLOW)
        self.assertNotIn("Place_Type", ALLOW)
        self.assertNotIn("MT_PlcType", ALLOW)

    def test_the_reader_slices_exactly_the_allow_list_and_nothing_else(self):
        self.assertEqual(set(SLICES), set(ALLOW))
        self.assertEqual(set(SLICES) & FORBIDDEN_EXPECTED, set())

    def test_each_slice_is_the_field_position_in_the_51_field_record(self):
        position, offsets = 1, {}
        for name, _kind, length, _dec in DBF_FIELDS:
            offsets[name] = (position, position + length)
            position += length
        self.assertEqual(position, DBF_RECORD_BYTES)
        for name, bounds in SLICES.items():
            self.assertEqual(tuple(bounds), offsets[name], name)


class ReaderTests(TempFolderMixin, unittest.TestCase):
    def test_a_zip_with_a_changed_field_list_is_unavailable_not_misread(self):
        renamed = [(("AddNumber" if name == "Add_Number" else name), kind, length, dec)
                   for name, kind, length, dec in DBF_FIELDS]
        zip_path = make_zip(self.tmp / "changed.zip", base_rows(), dbf_fields=renamed)
        with self.assertRaises(A.AddressesError) as caught:
            A.read_points(zip_path)
        self.assertIn("unavailable", str(caught.exception).lower())

    def test_a_zip_with_a_changed_projection_is_unavailable_not_misread(self):
        zip_path = make_zip(self.tmp / "prj.zip", base_rows(),
                            prj=PRJ.replace("NAD_1983_2011_StatePlane_Montana_FIPS_2500", "NAD_1983_StatePlane_Montana"))
        with self.assertRaises(A.AddressesError) as caught:
            A.read_points(zip_path)
        self.assertIn("unavailable", str(caught.exception).lower())

    def test_the_export_date_is_read_from_the_readme(self):
        zip_path = make_zip(self.tmp / "date.zip", base_rows())
        self.assertEqual(A.source_facts(zip_path)["export_date"], "2026-09-30")

    def test_the_three_quoted_metadata_sentences_are_read_exactly(self):
        zip_path = make_zip(self.tmp / "meta.zip", base_rows())
        facts = A.source_facts(zip_path)
        self.assertEqual(facts["accconst"], ACCCONST)
        self.assertIn("for no other purpose", facts["useconst"])
        self.assertEqual(facts["purpose"], PURPOSE)

    def test_the_reader_counts_the_rows_it_reads_and_the_null_shape(self):
        zip_path = make_zip(self.tmp / "rows.zip", base_rows())
        rows = list(A.read_points(zip_path))
        self.assertEqual(len(rows), len(base_rows()))


# ---------------------------------------------------------------- the lines, the city and zip, the counts

def read_shards(store: Path) -> list:
    """Every shard document under store/hail/a/ (the dot records are in doc["a"], one list per address)."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((store / "hail" / "a").glob("*.json"))]


def read_index(store: Path) -> dict:
    return json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))


class BuiltStore(TempFolderMixin):
    """A synthetic store built from base_rows() on the B1 sample store (its hail/index.json and manifest)."""

    def build_synthetic(self):
        zip_path = make_zip(self.tmp / "framework.zip", base_rows())
        self.store = self.tmp / "store"
        hail.fixture_store(self.store)
        return A.build(zip_path, self.store)


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class BuildRuleTests(BuiltStore, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.result = self.build_synthetic()
        self.counts = read_index(self.store)["addresses"]

    def lines(self):
        return [tuple(r[:5]) for doc in read_shards(self.store) for r in doc["a"]]

    def test_a_dot_record_is_lon_lat_line_city_zip_and_one_placement_class(self):
        for doc in read_shards(self.store):
            for record in doc["a"]:
                self.assertEqual(len(record), 6, record)
                self.assertIsInstance(record[0], float)
                self.assertIsInstance(record[1], float)
                self.assertIn(record[5], A.CLASS_LETTERS)
                self.assertEqual(len(record[5]), 1)

    def test_the_address_line_and_the_city_and_zip_follow_d3_and_d4(self):
        got = self.lines()
        self.assertEqual(sorted(got), sorted((round(lon, 5), round(lat, 5), line, city, zip_)
                                             for lon, lat, line, city, zip_ in BASE_LINES))

    def test_a_blank_street_and_a_null_shape_are_left_out_and_counted(self):
        self.assertEqual(self.counts["left_out_no_street"], 1)
        self.assertEqual(self.counts["left_out_no_position"], 1)

    def test_the_exact_duplicate_is_merged_and_counted(self):
        self.assertEqual(self.counts["merged_duplicates"], 1)

    def test_the_counts_add_up_to_the_record_count(self):
        counts = self.counts
        self.assertEqual(counts["points"], len(base_rows()))
        self.assertEqual(counts["rows"] + counts["left_out_no_street"] + counts["left_out_no_position"]
                         + counts["left_out_no_city"] + counts["left_out_deleted"] + counts["merged_duplicates"],
                         counts["points"])
        self.assertEqual(counts["rows"], len(BASE_LINES))

    def test_a_unit_is_title_cased_and_a_bare_unit_gets_unit_in_front(self):
        self.assertIn("401 North 27th Street Unit A", {line for _lo, _la, line, _c, _z in self.lines()})

    def test_the_number_suffix_one_half_has_a_space_and_the_letter_suffix_does_not(self):
        lines = {line for _lo, _la, line, _c, _z in self.lines()}
        self.assertIn("401 1/2 North 27th Street", lines)     # D3 as written would print "4011/2"; see the report
        self.assertIn("401A North 27th Street", lines)

    def test_a_zero_number_is_left_out_of_the_line(self):
        lines = {line for _lo, _la, line, _c, _z in self.lines()}
        self.assertIn("North 27th Street", lines)

    def test_a_six_character_zip_is_left_blank(self):
        zips = {zip_ for _lo, _la, line, city, zip_ in self.lines() if city == "Red Lodge"}
        self.assertEqual(zips, {""})

    def test_a_blank_post_comm_takes_inc_muni_or_the_county(self):
        cities = {(line, city) for _lo, _la, line, city, _z in self.lines()}
        self.assertIn(("25 Main Street", "Chinook"), cities)
        self.assertIn(("3 Colony Road", "Glacier County"), cities)

    def test_the_positions_are_the_file_projection_to_five_decimals(self):
        from_pos = {(round(POS[k][2], 5), round(POS[k][3], 5)) for k in POS}
        for lon, lat, _line, _city, _zip in self.lines():
            self.assertIn((lon, lat), from_pos)


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class UnavailableBuildTests(BuiltStore, unittest.TestCase):
    """A changed file fails loudly: the build raises, the index says "unavailable" and no address files are left."""

    def setUp(self):
        super().setUp()
        self.build_synthetic()
        self.assertTrue((self.store / "hail" / "a").is_dir())

    def assert_unavailable(self, source: bool = True):
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIn("unavailable", block["reason"].lower())
        self.assertIs(block["source_unavailable"], source)
        self.assertFalse((self.store / "hail" / "a").exists())
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse([k for k in manifest["files"] if k.startswith("hail/a/")])

    def test_a_changed_field_list_raises_and_marks_the_index_unavailable(self):
        renamed = [(("AddNumber" if name == "Add_Number" else name), kind, length, dec)
                   for name, kind, length, dec in DBF_FIELDS]
        zip_path = make_zip(self.tmp / "changed.zip", base_rows(), dbf_fields=renamed)
        with self.assertRaises(A.AddressesError):
            A.build(zip_path, self.store)
        self.assert_unavailable()

    def test_a_changed_projection_raises_and_marks_the_index_unavailable(self):
        zip_path = make_zip(self.tmp / "prj.zip", base_rows(),
                            prj=PRJ.replace("NAD_1983_2011_StatePlane_Montana_FIPS_2500", "NAD_1983_StatePlane_Montana"))
        with self.assertRaises(A.AddressesError):
            A.build(zip_path, self.store)
        self.assert_unavailable()

    def test_a_failed_download_marks_the_index_unavailable_from_its_source(self):
        failure = A.SourceUnavailable("Montana's address list is unavailable: the framework download failed (test)")
        with mock.patch.object(A, "download", side_effect=failure):
            with self.assertRaises(A.SourceUnavailable):
                A.build(None, self.store)
        self.assert_unavailable(source=True)

    def test_a_changed_terms_sentence_marks_the_list_unavailable_from_its_source(self):
        changed = USECONST.replace("for informational purposes only", "for general purposes")
        zip_path = make_zip(self.tmp / "terms.zip", base_rows(), useconst=changed)
        with self.assertRaises(A.SourceUnavailable) as caught:
            A.build(zip_path, self.store)
        self.assertIn("terms sentences", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_a_changed_purpose_sentence_marks_the_list_unavailable_from_its_source(self):
        zip_path = make_zip(self.tmp / "purpose.zip", base_rows(), purpose=PURPOSE + " Changed.")
        with self.assertRaises(A.SourceUnavailable):
            A.build(zip_path, self.store)
        self.assert_unavailable(source=True)

    def test_a_readme_without_an_export_date_marks_the_list_unavailable_from_its_source(self):
        zip_path = make_zip(self.tmp / "readme.zip", base_rows(), readme="*****\r\nNo export date here.\r\n")
        with self.assertRaises(A.SourceUnavailable) as caught:
            A.build(zip_path, self.store)
        self.assertIn("export date", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_a_placement_value_that_is_not_one_of_the_classes_marks_the_list_unavailable(self):
        rows = base_rows() + [row("E", Add_Number=3, St_Name="Rooftop", St_PosTyp="Way", Post_Comm="Red Lodge",
                                  Post_Code="59068", Placement="Rooftop")]
        zip_path = make_zip(self.tmp / "placement.zip", rows)
        with self.assertRaises(A.SourceUnavailable) as caught:
            A.build(zip_path, self.store)
        self.assertIn("placement value 'Rooftop'", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_a_table_that_ends_before_its_last_record_marks_the_list_unavailable(self):
        good = make_zip(self.tmp / "good.zip", base_rows())
        with zipfile.ZipFile(good) as zf:
            table = zf.read(DATA_DBF_NAME)
        cut = copy_zip_with(good, self.tmp / "cut.zip", DATA_DBF_NAME, table[: len(table) // 2])
        with self.assertRaises(A.SourceUnavailable):
            A.build(cut, self.store)
        self.assert_unavailable(source=True)

    def test_a_source_that_will_not_decode_marks_the_list_unavailable_from_its_source(self):
        zip_path = make_zip(self.tmp / "decode.zip", base_rows())
        with mock.patch.object(A, "_collect", side_effect=zipfile.BadZipFile("Bad CRC-32 for file (test)")):
            with self.assertRaises(A.SourceUnavailable) as caught:
                A.build(zip_path, self.store)
        self.assertIn("could not be decoded (BadZipFile)", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_a_point_that_is_not_a_number_marks_the_list_unavailable(self):
        with mock.patch.dict(POS, {"N": (float("nan"), 1.0, 0.0, 0.0)}):
            zip_path = make_zip(self.tmp / "nan.zip", base_rows() + [row("N", Add_Number=8, St_Name="Ash",
                                                                          St_PosTyp="Street", Post_Comm="Billings",
                                                                          Post_Code="59101")])
            with self.assertRaises(A.SourceUnavailable) as caught:
                A.build(zip_path, self.store)
        self.assertIn("is not a number", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_a_missing_zip_file_marks_the_list_unavailable_from_its_source(self):
        # D36 wins over the earlier rule: a wrong path is the source failing to answer, so the list is unavailable.
        with self.assertRaises(A.SourceUnavailable) as caught:
            A.build(self.tmp / "missing.zip", self.store)
        self.assertIn("is not there", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_a_folder_given_as_the_zip_marks_the_list_unavailable_from_its_source(self):
        folder = self.tmp / "framework-folder"
        folder.mkdir()
        with self.assertRaises(A.SourceUnavailable) as caught:
            A.build(folder, self.store)
        self.assertIn("is not a file", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_an_unreadable_zip_file_marks_the_list_unavailable_from_its_source(self):
        # The sandbox runs as root, where a mode of 000 does not stop a read, so the read error is raised by the mock.
        zip_path = make_zip(self.tmp / "unreadable.zip", base_rows())
        with mock.patch.object(A, "_sha256_file", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(A.SourceUnavailable) as caught:
                A.build(zip_path, self.store)
        self.assertIn("could not be read (PermissionError)", str(caught.exception))
        self.assert_unavailable(source=True)

    def test_a_failure_while_writing_is_not_a_source_failure(self):
        zip_path = make_zip(self.tmp / "write.zip", base_rows())
        with mock.patch.object(A, "_write_tree", side_effect=A.AddressesError("the shards could not be written")):
            with self.assertRaises(A.AddressesError) as caught:
                A.build(zip_path, self.store)
        self.assertNotIsInstance(caught.exception, A.SourceUnavailable)
        self.assert_unavailable(source=False)


# ---------------------------------------------------------------- quadtree shards (D5)

TILE_R, TILE_C = 92, 214                  # the tile that holds Billings' 401 North 27th Street (r0092_c0214)


SUB = A.SUB                               # sub-units per 1e-5 degree (the quadtree's integer unit; B3R-07)


def tile_bounds(tr: int, tc: int) -> tuple[int, int, int, int]:
    """The tile's box in sub-units, from the grid's cell edges (the oracle the module's tile_box must match)."""
    north5 = round((54.995 - tr * 0.1 + 0.005) * 100000)
    west5 = round((-129.995 + tc * 0.1 - 0.005) * 100000)
    return west5 * SUB, (north5 - 10000) * SUB, (west5 + 10000) * SUB, north5 * SUB


def dense_points(n: int, west, south, east, north) -> list:
    """n distinct positions in whole sub-units spread over the box, each with its own payload. Every point is inside the
    box as the quadtree reads it: west <= lon < east and south < lat <= north."""
    side = math.ceil(math.sqrt(n))
    out = []
    for i in range(side):
        for j in range(side):
            if len(out) == n:
                return out
            lon = west + (j * (east - west - 1)) // max(side - 1, 1)
            lat = south + 1 + (i * (north - south - 1)) // max(side - 1, 1)
            out.append((lon, lat, len(out)))
    return out


def inside_as_the_grid_reads_it(bounds, lon: int, lat: int) -> bool:
    west, south, east, north = bounds
    return west <= lon < east and south < lat <= north


class ShardTests(unittest.TestCase):
    def test_the_module_tile_box_is_the_grid_cell_edges_of_the_tile(self):
        for tr, tc in ((TILE_R, TILE_C), (0, 0), (349, 699), (60, 179)):
            self.assertEqual(A.tile_box(tr, tc), tile_bounds(tr, tc), (tr, tc))

    def test_a_tile_of_more_than_2500_rows_splits_into_quarters_with_the_right_digits_and_bounds(self):
        bounds = tile_bounds(TILE_R, TILE_C)
        west, south, east, north = bounds
        points = dense_points(2600, west, south, east, north)
        shards = A.quadtree(f"r{TILE_R:04d}_c{TILE_C:04d}", bounds, points)
        names = sorted(name for name, _b, _pts in shards)
        self.assertEqual(names, [f"r0092_c0214{d}" for d in "0123"])
        mid_lon, mid_lat = (west + east) // 2, (south + north) // 2
        expect = {"0": (west, mid_lat, mid_lon, north), "1": (mid_lon, mid_lat, east, north),
                  "2": (west, south, mid_lon, mid_lat), "3": (mid_lon, south, east, mid_lat)}
        for name, leaf_bounds, pts in shards:
            self.assertEqual(tuple(leaf_bounds), expect[name[-1]], name)
            self.assertLessEqual(len(pts), 2500)
            self.assertTrue(all(inside_as_the_grid_reads_it(leaf_bounds, p[0], p[1]) for p in pts), name)

    def test_a_dense_quarter_splits_again_and_the_names_grow_by_one_digit(self):
        bounds = tile_bounds(TILE_R, TILE_C)
        west, south, east, north = bounds
        mid_lon, mid_lat = (west + east) // 2, (south + north) // 2
        points = dense_points(2600, west, mid_lat, mid_lon, north)        # every point in the north-west quarter
        shards = A.quadtree(f"r{TILE_R:04d}_c{TILE_C:04d}", bounds, points)
        names = sorted(name for name, _b, _pts in shards)
        self.assertEqual(names, ["r0092_c021400", "r0092_c021401", "r0092_c021402", "r0092_c021403"])

    def test_a_shard_at_the_depth_cap_may_exceed_the_limit(self):
        bounds = tile_bounds(TILE_R, TILE_C)
        west, south, _east, _north = bounds
        points = [(west + 1, south + 1, k) for k in range(2600)]    # all at one position: one cap-depth shard
        shards = A.quadtree(f"r{TILE_R:04d}_c{TILE_C:04d}", bounds, points)
        self.assertEqual(len(shards), 1)
        name, _bounds, pts = shards[0]
        self.assertEqual(len(name) - len(f"r{TILE_R:04d}_c{TILE_C:04d}"), 6)     # six digits: depth 6
        self.assertEqual(len(pts), 2600)

    def test_a_tile_of_2500_rows_or_fewer_is_one_shard_with_the_tile_name(self):
        bounds = tile_bounds(TILE_R, TILE_C)
        shards = A.quadtree(f"r{TILE_R:04d}_c{TILE_C:04d}", bounds, dense_points(2500, *bounds))
        self.assertEqual([name for name, _b, _p in shards], ["r0092_c0214"])


class MidlineTests(unittest.TestCase):
    """A point on a middle line files in one quarter, the same one every time, because the compare is exact in whole
    sub-units (B3R-07). The grid's rule: longitude [west, east), latitude (south, north]."""

    def test_the_quarter_of_a_point_on_the_middle_lines_of_a_tile(self):
        box = (0, 0, 640000, 640000)               # a tile in sub-units: its middle lines are at 320000 both ways
        self.assertEqual(A.quarter(box, 320000, 320000), "3")   # on both lines: east, and south (lat not above)
        self.assertEqual(A.quarter(box, 319999, 320000), "2")   # west, on the south line
        self.assertEqual(A.quarter(box, 320000, 320001), "1")   # east, north of the line
        self.assertEqual(A.quarter(box, 319999, 320001), "0")   # west, north

    def test_a_point_on_a_middle_line_at_depth_one_files_in_one_quarter(self):
        box = (0, 0, 320000, 320000)               # a depth-1 box: its middle lines are at 160000
        points = dense_points(2600, *box) + [(160000, 160000, "mid")]
        leaves = A.quadtree("r0092_c0214", box, points, depth=1)
        holding = [(name, leaf_bounds) for name, leaf_bounds, pts in leaves if any(p[2] == "mid" for p in pts)]
        self.assertEqual(len(holding), 1)
        name, leaf_bounds = holding[0]
        self.assertEqual(name[-1], "3")            # east (lon 160000 is not below the middle) and south (lat not above)
        self.assertEqual(leaf_bounds, (160000, 0, 320000, 160000))
        self.assertTrue(inside_as_the_grid_reads_it(leaf_bounds, 160000, 160000))

    def test_a_point_on_a_middle_line_at_depth_four_files_in_one_quarter(self):
        # A depth-4 box is 40000 sub-units wide, so its middle line is at 20000 sub-units: a point on it is not a
        # 5-decimal position, which is why the compare is in sub-units (64 per 1e-5 degree).
        box = (0, 0, 40000, 40000)
        points = dense_points(2600, *box) + [(20000, 20000, "mid")]
        leaves = A.quadtree("r0092_c0214", box, points, depth=4)
        holding = [(name, leaf_bounds) for name, leaf_bounds, pts in leaves if any(p[2] == "mid" for p in pts)]
        self.assertEqual(len(holding), 1)
        name, leaf_bounds = holding[0]
        self.assertEqual(len(name) - len("r0092_c0214"), 1)          # one digit below the name given, at depth 5
        self.assertEqual(name[-1], "3")
        self.assertEqual(leaf_bounds, (20000, 0, 40000, 20000))
        self.assertTrue(inside_as_the_grid_reads_it(leaf_bounds, 20000, 20000))

    def test_the_quadtree_never_puts_a_point_outside_its_leaf(self):
        box = (0, 0, 40000, 40000)
        points = dense_points(2600, *box) + [(20000, 20000, "mid"), (19999, 20000, "west"), (20000, 19999, "south")]
        for name, leaf_bounds, pts in A.quadtree("r0092_c0214", box, points, depth=4):
            self.assertTrue(all(inside_as_the_grid_reads_it(leaf_bounds, p[0], p[1]) for p in pts), name)


class TileRuleTests(unittest.TestCase):
    def test_the_tile_of_a_position_is_the_b1_cell_of_the_hail_module(self):
        cases = [(4580000, -10860000), (4579999, -10859999), (4570000, -10850000), (4570001, -10850001),
                 (4600000, -10900000), (4599999, -10899999), (4550000, -10800000), (4580001, -10860001),
                 (4570000, -10850000)]
        for lat5, lon5 in cases:
            cell = hail.cell_for(lat5 / 100000, lon5 / 100000)
            self.assertEqual(A.tile_of(lat5, lon5), (cell[0] // hail.TILE, cell[1] // hail.TILE), (lat5, lon5))


# ---------------------------------------------------------------- the search index (D5, D6)

class SearchIndexTests(unittest.TestCase):
    def test_the_slug_is_lower_case_with_dashes_and_no_leading_or_trailing_dash(self):
        self.assertEqual(A.slug("Great Falls"), "great-falls")
        self.assertEqual(A.slug("Columbia Falls"), "columbia-falls")
        self.assertEqual(A.slug("Glacier County"), "glacier-county")
        self.assertEqual(A.slug("St. Ignatius"), "st-ignatius")
        self.assertTrue(_ascii_ok(A.slug("Great Falls")))

    def test_a_city_key_is_the_first_character_upper_cased_and_digits_stay_digits(self):
        keys = A.city_keys([("Billings", "27th Street"), ("Billings", "Main Street"), ("Billings", "1st Avenue")])
        self.assertEqual(keys["Billings"], {"2": 1, "M": 1, "1": 1})

    def test_a_letter_with_more_than_2500_rows_splits_to_two_characters_and_writes_no_one_character_file(self):
        streets = [("Testburg", f"S{chr(65 + k % 26)}{k:04d} Road") for k in range(2600)]
        keys = A.city_keys(streets)
        self.assertNotIn("S", keys["Testburg"])
        self.assertTrue(all(len(k) == 2 for k in keys["Testburg"] if k.startswith("S")))
        self.assertEqual(sum(keys["Testburg"].values()), 2600)

    def test_words_json_expands_the_abbreviations_to_the_file_words(self):
        words = A.search_words()
        self.assertEqual(words["n"], "north")
        self.assertEqual(words["st"], "street")
        self.assertEqual(words["ave"], "avenue")
        self.assertEqual(words["hwy"], "highway")
        self.assertEqual(words["us"], "united states")
        self.assertEqual(words["mt"], "montana")
        self.assertEqual(words["#"], "unit")


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class SearchOutputTests(BuiltStore, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.build_synthetic()
        self.idx = self.store / "hail" / "a" / "idx"

    def test_the_index_names_the_city_files_and_the_letter_files(self):
        cities = json.loads((self.idx / "cities.json").read_text(encoding="utf-8"))
        self.assertEqual(cities["f"], "hail-address-cities-v1")
        self.assertEqual(cities["cities"]["Billings"]["n"], 6)
        self.assertEqual(cities["cities"]["Billings"]["keys"], {"2": 6})
        self.assertEqual(cities["cities"]["Chinook"]["keys"], {"M": 1})
        self.assertEqual(cities["cities"]["Glacier County"]["keys"], {"C": 1})
        self.assertTrue((self.idx / "billings" / "2.json").is_file())
        self.assertTrue((self.idx / "glacier-county" / "C.json").is_file())
        self.assertFalse((self.idx / "billings" / "3.json").exists())

    def test_a_letter_row_is_number_street_unit_lon_lat_zip(self):
        letter = json.loads((self.idx / "billings" / "2.json").read_text(encoding="utf-8"))
        self.assertEqual(letter["f"], "hail-address-idx-v1")
        numbers = sorted(row[0] for row in letter["a"])
        self.assertEqual(numbers, ["", "401", "401", "401", "401 1/2", "401A"])
        for number, street, unit, lon, lat, zip_, cls in letter["a"]:
            self.assertEqual(street, "North 27th Street")
            self.assertIsInstance(lon, float)
            self.assertIsInstance(lat, float)
            self.assertEqual(zip_, "59101")
            self.assertEqual(len(cls), 1)
            self.assertIn(cls, A.CLASS_LETTERS)
        self.assertIn("Unit A", {row[2] for row in letter["a"]})

    def test_the_search_index_holds_no_owner_or_parcel_text(self):
        for path in self.idx.rglob("*.json"):
            self.assertNotRegex(path.read_text(encoding="utf-8").lower(), r"owner|parcel|nguid|global")


# ---------------------------------------------------------------- words, the terms and the privacy sentence (D8, D12)

class WordsTests(unittest.TestCase):
    def test_no_word_or_described_sentence_names_a_forbidden_term(self):
        for key, text in WORDS.items():
            if isinstance(text, str):
                check_terms(self, text)
        for text in A.describe_addresses(sample=True).values():
            if isinstance(text, str):
                check_terms(self, text)

    def test_the_exclusion_sentence_is_in_the_about_words_exactly(self):
        self.assertIn(ABOUT_EXCLUSION, " ".join(str(v) for v in WORDS.values()))

    def test_the_privacy_sentence_and_the_search_and_legend_words_are_exact(self):
        text = " ".join(str(v) for v in WORDS.values())
        self.assertIn("What you type stays in your browser.", text)
        self.assertIn("Find an address", text)
        self.assertIn("Type a street address and a town", text)
        self.assertIn("No match in Montana's address list; try the street name alone", text)
        self.assertIn("Dots are addresses from Montana's public address list; tap one for its history", text)

    def test_the_terms_quote_the_metadata_sentences_exactly(self):
        text = " ".join(str(v) for v in WORDS.values())
        for quoted in QUOTED:
            self.assertIn(quoted, text)

    def test_the_words_never_say_who_lives_there_or_what_the_building_is(self):
        text = " ".join(str(v) for v in WORDS.values())
        for quoted in QUOTED + (ABOUT_EXCLUSION,):
            text = text.replace(quoted, "")
        for bad in ("lives", "resident\\w*", "tenant\\w*", "owner\\w*", "home\\w*", "house\\w*", "business\\w*",
                    "commercial"):
            self.assertNotRegex(text.lower(), rf"\b{bad}\b")

    def test_the_about_text_says_no_positive_claim_about_commercial_use(self):
        self.assertNotRegex(" ".join(str(v) for v in WORDS.values()).lower(), r"commercial use is (permitted|allowed)")

    def test_the_statute_citation_is_2_6_1017_only(self):
        self.assertIn("2-6-1017", WORDS["about_persons"])
        self.assertNotIn("2-6-109", " ".join(str(v) for v in WORDS.values()))
        self.assertNotIn("2-6-109", " ".join(str(v) for v in A.describe_addresses(sample=True).values()))

    def test_the_coverage_words_are_the_sentence_of_d21_with_no_number(self):
        self.assertEqual(WORDS["about_coverage"],
                         "The list is of addresses, not of buildings, and its coverage varies from county to county.")
        self.assertNotRegex(WORDS["about_coverage"], r"\d")

    def test_the_use_terms_join_the_two_quoted_sentences_with_the_marker(self):
        joined = A.USE_DISCLAIMER_TEXT + " [...] " + A.USE_CONVENIENCE_TEXT
        self.assertIn(joined, WORDS["about_use"])
        self.assertIn(joined, A.describe_addresses(sample=True)["use"])

    def test_the_source_line_gives_a_file_date_only_when_the_index_read_one(self):
        undated = ("Source: Montana State Library Structures and Addresses Framework (file date not available in this "
                   "update).")
        self.assertEqual(WORDS["about_source_undated"], undated)
        for index in (None, {}, {"addresses": None}, {"addresses": {"state": "unavailable", "reason": "r"}}):
            line = A.describe_addresses(index)["source"]
            self.assertEqual(line, undated)
            self.assertNotIn("2026-09-30", line)

    def test_a_loaded_index_keeps_its_own_dates_in_the_source_line(self):
        index = {"addresses": {"state": "loaded", "source": {"pubdate": "2026-10-01", "export_date": "2026-10-01"}}}
        self.assertEqual(A.describe_addresses(index)["source"],
                         "Source: Montana State Library Structures and Addresses Framework, file dated 2026-10-01, "
                         "exported 2026-10-01.")


class BuildingWordsTests(unittest.TestCase):
    """The words for a building outline (D29, D34) and the D23 and D32 sentences: exact text, and no house word (D34)."""

    def test_the_building_outline_words_are_the_d29_and_d34_sentences_exactly(self):
        self.assertEqual(WORDS["outline_legend"], "Each dot is one building outline. Tap a dot for its address, if one "
                         "is on file, and the weather history for its cell.")
        self.assertEqual(WORDS["outline_no_address"], "No address on file for this building. The weather history below "
                         "is for this building's cell.")
        self.assertEqual(WORDS["outline_units"], "Units on file: {n}.")
        self.assertEqual(WORDS["outline_caveat"], "Outlines come from imagery dated 2008 to 2025 and are not surveys; "
                         "sheds and barns are outlines too.")
        self.assertIn("building outline", WORDS["outline_legend"])

    def test_no_module_word_says_house_home_residence_or_dwelling(self):
        texts = [str(v) for v in WORDS.values()] + list(A.describe_addresses(sample=True).values())
        texts += list(A.PLACEMENT_HOW.values()) + [WORDS["placed"]]
        for text in texts:
            stripped = text
            for quoted in QUOTED + (ABOUT_EXCLUSION,):
                stripped = stripped.replace(quoted, "")
            self.assertNotRegex(stripped.lower(), r"\b(houses?|homes?|residences?|residential|dwellings?|dwell\w*)\b",
                                text)

    def test_the_d23_outside_grid_sentence_is_exact_and_the_map_data_carries_it(self):
        self.assertEqual(WORDS["outside_grid"],
                         "This point is outside the hail grid's Montana outline; no hail history is kept here.")
        block = A.map_data_addresses({"addresses": {"state": "unavailable", "reason": "r"}})
        self.assertEqual(block["templates"]["outside_grid"], WORDS["outside_grid"])

    def test_the_d32_placed_sentence_and_the_placement_phrases_are_exact(self):
        self.assertEqual(WORDS["placed"], "This address point was placed {how}, not on the building.")
        self.assertEqual(A.PLACEMENT_HOW, {"P": "at the property entrance", "G": "along the road by its number",
                                           "L": "at the parcel", "T": "at the site",
                                           "U": "by a method the file does not state"})
        block = A.map_data_addresses({"addresses": {"state": "unavailable", "reason": "r"}})
        self.assertEqual(block["templates"]["placed_how"], A.PLACEMENT_HOW)

    def test_the_zoom_rules_and_the_dot_radius_are_carried_in_every_state(self):    # D47
        for block in (A.map_data_addresses({"addresses": {"state": "unavailable", "reason": "r"}}),
                      A.map_data_addresses({})):
            self.assertEqual(block["zoom"], {"dots": 15, "choose": 17})
            self.assertEqual(block["dot_radius_px"]["max"], 4.0)

    def test_the_about_sentence_names_the_fields_the_site_reads_including_placement(self):
        self.assertIn("number, street, unit, city, zip, county and placement", WORDS["about_fields"])


class UnitCasingTests(unittest.TestCase):
    """The unit as the line shows it (D3 and the completion list, B3R-04)."""

    def test_a_letter_run_with_digits_keeps_its_letters_title_cased_and_no_prefix(self):
        self.assertEqual(A.unit_text("APT2"), "Apt2")
        self.assertEqual(A.unit_text("RM403"), "Rm403")
        self.assertEqual(A.unit_text("LOT 2"), "Lot 2")
        self.assertEqual(A.unit_text("UNIT A1"), "Unit A1")

    def test_a_single_letter_or_a_number_gets_unit_in_front(self):
        self.assertEqual(A.unit_text("A1"), "Unit A1")
        self.assertEqual(A.unit_text("A"), "Unit A")
        self.assertEqual(A.unit_text("#3"), "Unit #3")
        self.assertEqual(A.unit_text("1/2"), "Unit 1/2")

    def test_the_plain_words_are_unchanged(self):
        self.assertEqual(A.unit_text("UNIT A"), "Unit A")
        self.assertEqual(A.unit_text("UNIT 201"), "Unit 201")
        self.assertEqual(A.unit_text("APT 1"), "Apt 1")
        self.assertEqual(A.unit_text(""), "")


class CityNameTests(unittest.TestCase):
    """One display spelling per city, the most-used one (D22). The list is passed, so each use counts."""

    def test_the_most_used_mixed_case_spelling_is_the_display_spelling(self):
        names = ["Red Lodge"] * 5 + ["Red lodge"] + ["RED LODGE"] * 9
        self.assertEqual(A.canonical_cities(names)["Red lodge"], "Red Lodge")
        self.assertEqual(A.canonical_cities(names)["RED LODGE"], "Red Lodge")

    def test_a_less_used_spelling_does_not_win_because_it_is_seen_first(self):
        names = ["Red lodge", "Red lodge", "Red Lodge"]
        self.assertEqual(A.canonical_cities(names)["Red Lodge"], "Red lodge")

    def test_a_city_written_only_in_capitals_is_capitalised_word_by_word(self):
        self.assertEqual(A.canonical_cities(["LEWISTOWN"] * 4)["LEWISTOWN"], "Lewistown")
        self.assertEqual(A.canonical_cities(["ST. IGNATIUS"])["ST. IGNATIUS"], "St. Ignatius")

    def test_spellings_that_differ_only_in_capitals_or_punctuation_are_one_city(self):
        names = ["St. Ignatius"] * 3 + ["St Ignatius"] * 2
        out = A.canonical_cities(names)
        self.assertEqual({out[n] for n in names}, {"St. Ignatius"})
        self.assertEqual(A.city_key("St. Ignatius"), A.city_key("St Ignatius"))
        self.assertEqual(A.city_key("ST IGNATIUS"), A.city_key("St Ignatius"))


class PlacementTests(unittest.TestCase):
    """The placement class of each spelling of the file's Placement field (D32)."""

    def test_each_spelling_of_the_placement_field_has_its_class(self):
        expect = {"Structure": "S", "Property Access": "P", "PropertyAccess": "P", "Geocoding": "G", "Parcel": "L",
                  "Site": "T", "Unknown": "U", "": "U"}
        for value, letter in expect.items():
            self.assertEqual(A.placement_class(value), letter, repr(value))

    def test_a_value_that_is_not_a_spelling_of_the_field_is_a_source_failure(self):
        with self.assertRaises(A.SourceUnavailable) as caught:
            A.placement_class("Rooftop")
        self.assertIn("is not one this build reads", str(caught.exception))

    def test_the_counts_add_up_per_county_and_a_blank_is_unknown(self):
        keep = [{"Placement": "Structure", "County": "Carbon County"}, {"Placement": "", "County": "Carbon County"},
                {"Placement": "PropertyAccess", "County": "Sanders County"},
                {"Placement": "Property Access", "County": ""}]
        counts = A.placement_counts(keep)
        self.assertEqual(counts["classes"], {"S": 1, "P": 2, "G": 0, "L": 0, "T": 0, "U": 1})
        self.assertEqual(counts["blank_as_unknown"], 1)
        self.assertEqual(counts["by_county"]["Carbon County"], {"S": 1, "P": 0, "G": 0, "L": 0, "T": 0, "U": 1})
        self.assertEqual(counts["by_county"]["(blank)"]["P"], 1)
        self.assertEqual(sum(sum(c.values()) for c in counts["by_county"].values()), len(keep))


# ---------------------------------------------------------------- projection pairs (D2)

@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed")
class ProjectionTests(unittest.TestCase):
    def test_three_recorded_pairs_reproduce_within_two_metres(self):
        for pair in PAIRS:
            lon, lat = A.to_lonlat(pair["x"], pair["y"])
            metres = haversine_m(lon, lat, *pair["live"])
            self.assertLess(metres, 2.0, f"{pair['name']}: {metres:.3f} m")

    def test_the_file_coordinates_round_to_the_recorded_five_decimal_values(self):
        expect = {"1611 South Avenue West, Missoula": (-114.02078, 46.84868),
                  "500 Colony Road, Roundup": (-108.50031, 46.7175),
                  "1617 Euclid Avenue Unit 4, Helena": (-112.05997, 46.60374)}
        for pair in PAIRS:
            lon, lat = A.to_lonlat(pair["x"], pair["y"])
            self.assertEqual((round(lon, 5), round(lat, 5)), expect[pair["name"]])

    def test_the_module_records_the_same_live_pairs_as_this_test(self):
        self.assertEqual([p["live"] for p in A.PROJECTION_PAIRS], [p["live"] for p in PAIRS])
        self.assertEqual([p["name"] for p in A.PROJECTION_PAIRS], [p["name"] for p in PAIRS])

    def test_the_synthetic_positions_round_trip(self):
        for key, (x, y, lon, lat) in POS.items():
            got = A.to_lonlat(x, y)
            self.assertLess(haversine_m(got[0], got[1], lon, lat), 0.01, key)


# ---------------------------------------------------------------- build, verify and the store (D9, gate B3-1, B3-8)

@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class StoreTests(BuiltStore, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.result = self.build_synthetic()

    def test_verify_passes_on_the_synthetic_store(self):
        result = A.verify(self.store)
        self.assertTrue(result["ok"], result)

    def test_verify_fails_on_a_tampered_shard_by_its_manifest_hash(self):
        shard = next(p for p in sorted((self.store / "hail" / "a").glob("*.json"))
                     if "Billings" in p.read_text(encoding="utf-8"))           # the Billings tile holds the edit
        text = shard.read_text(encoding="utf-8")
        self.assertIn("Billings", text)
        shard.write_text(text.replace("Billings", "Billingz", 1), encoding="utf-8")
        result = A.verify(self.store)
        self.assertFalse(result["ok"], "a tampered shard passed verify")
        self.assertIn(shard.name, json.dumps(result))

    def test_the_index_states_the_source_and_the_fields_read(self):
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "loaded")
        self.assertEqual(block["source"]["export_date"], "2026-09-30")
        self.assertEqual(set(block["source"]["fields_read"]), ALLOW_EXPECTED)
        self.assertEqual(set(block["source"]["fields_read"]) & FORBIDDEN_EXPECTED, set())
        self.assertEqual(block["source"]["accconst"], ACCCONST)

    def test_map_data_names_the_split_map_and_the_shard_pattern(self):
        block = A.map_data_addresses(read_index(self.store))
        self.assertIn("split", block)
        self.assertIn("shard", block)
        self.assertNotIn("ParcelID", json.dumps(block))

    def test_map_data_carries_the_zoom_rules_and_the_dot_radius(self):              # D47
        block = A.map_data_addresses(read_index(self.store))
        self.assertEqual(block["zoom"], {"dots": 15, "choose": 17})
        self.assertNotIn("zoom", block["limits"])
        self.assertEqual(block["dot_radius_px"], {"zoom": 13, "at_zoom": 2.5, "per_zoom": 0.5, "max": 4.0})

    def test_the_manifest_lists_every_address_file_and_nothing_else_under_a(self):
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        listed = {k for k in manifest["files"] if k.startswith("hail/a/")}
        on_disk = {p.relative_to(self.store).as_posix() for p in (self.store / "hail" / "a").rglob("*") if p.is_file()}
        self.assertEqual(listed, on_disk)


def list_in_manifest(store: Path, *paths: Path) -> None:
    """Record each file's size and SHA-256 in hail/manifest.json, as the pack step does for the files it writes."""
    manifest_path = store / "hail" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for path in paths:
        data = path.read_bytes()
        manifest["files"][path.relative_to(store).as_posix()] = {"bytes": len(data),
                                                                 "sha256": hashlib.sha256(data).hexdigest()}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def outline_step(store: Path, take: int, *, keep_in_a: bool = False) -> Path:
    """What the outline step leaves in the address files (D28), made by hand so the count can be tested without
    footprints: the first `take` rows of the busiest a/ shard move to hail/b/ under the same name, with their number in
    "m". keep_in_a copies them instead, so the rows sit in both places. Returns the hail/b/ file."""
    a_dir, b_dir = store / "hail" / "a", store / "hail" / "b"
    shard = max(sorted(a_dir.glob("*.json")), key=lambda p: len(json.loads(p.read_text(encoding="utf-8"))["a"]))
    doc = json.loads(shard.read_text(encoding="utf-8"))
    if not keep_in_a:
        doc["a"] = doc["a"][take:]
        doc["n"] = len(doc["a"])
        shard.write_text(json.dumps(doc), encoding="utf-8")
    b_dir.mkdir(parents=True, exist_ok=True)
    b_path = b_dir / shard.name
    b_path.write_text(json.dumps({"f": "hail-buildings-v1", "b": doc["b"], "n": 0, "m": take, "c": None, "a": []}),
                      encoding="utf-8")
    # The outline step also writes its block, which records the rows it left in hail/a (buildings a rows, D28).
    index_path = store / "hail" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    left = sum(len(json.loads(p.read_text(encoding="utf-8"))["a"]) for p in a_dir.glob("*.json"))
    index["buildings"] = {"state": "loaded", "addresses": "loaded", "a": {"rows": left}}
    index["addresses"] = A.refresh_figures(store, index["addresses"])   # D49: the outline step writes the figures back
    index_path.write_text(json.dumps(index), encoding="utf-8")
    list_in_manifest(store, shard, b_path, index_path)
    return b_path


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class OutlineCountTests(TempFolderMixin, unittest.TestCase):
    """D28: after the outline step the matched rows sit in hail/b/ and the unmatched rows in hail/a/, and verify adds
    the two. The job verifies before the outline step, so this is the check for a store the outline step has rewritten."""

    def setUp(self):
        super().setUp()
        self.store = build_rows_store(self.tmp / "outline", base_rows())
        self.total = read_index(self.store)["addresses"]["rows"]

    @staticmethod
    def count_check(result: dict) -> dict:
        return next(c for c in result["checks"] if c["name"].startswith("the shard count matches the index"))

    def test_no_outline_block_and_a_full_a_passes(self):
        self.assertFalse(read_index(self.store).get("buildings"))
        check = self.count_check(A.verify(self.store))
        self.assertTrue(check["ok"], check)
        self.assertIn(f"{self.total} in the index", check["detail"])

    def test_a_post_split_a_holding_only_the_unmatched_rows_passes(self):
        outline_step(self.store, take=2)
        self.assertEqual(read_index(self.store)["buildings"]["a"]["rows"], self.total - 2)
        check = self.count_check(A.verify(self.store))
        self.assertTrue(check["ok"], check)
        self.assertIn(f"2 matched in hail/b, {self.total} in the index", check["detail"])

    def test_a_post_split_a_with_a_wrong_count_fails(self):
        outline_step(self.store, take=2)
        a_dir = self.store / "hail" / "a"
        a_path = max(sorted(a_dir.glob("*.json")), key=lambda p: len(json.loads(p.read_text(encoding="utf-8"))["a"]))
        doc = json.loads(a_path.read_text(encoding="utf-8"))
        doc["a"] = doc["a"][1:]                                   # one unmatched row goes missing from hail/a
        doc["n"] = len(doc["a"])
        a_path.write_text(json.dumps(doc), encoding="utf-8")
        list_in_manifest(self.store, a_path)
        check = self.count_check(A.verify(self.store))
        self.assertFalse(check["ok"], check)
        self.assertFalse(A.verify(self.store)["ok"])

    def test_verify_passes_when_the_matched_rows_sit_in_b_and_the_rest_in_a(self):
        outline_step(self.store, take=2)
        result = A.verify(self.store)
        check = self.count_check(result)
        self.assertTrue(check["ok"], check)
        self.assertIn(f"2 matched in hail/b, {self.total} in the index", check["detail"])
        self.assertTrue(result["ok"], [c for c in result["checks"] if not c["ok"]])

    def test_verify_fails_when_a_matched_count_in_b_is_changed(self):
        b_path = outline_step(self.store, take=2)
        doc = json.loads(b_path.read_text(encoding="utf-8"))
        doc["m"] = 3
        b_path.write_text(json.dumps(doc), encoding="utf-8")
        list_in_manifest(self.store, b_path)                      # the manifest agrees, so only the count can fail
        result = A.verify(self.store)
        self.assertFalse(self.count_check(result)["ok"])
        self.assertFalse(result["ok"])

    def test_verify_fails_when_the_matched_rows_are_in_both_a_and_b(self):
        outline_step(self.store, take=2, keep_in_a=True)
        result = A.verify(self.store)
        self.assertFalse(self.count_check(result)["ok"])
        self.assertFalse(result["ok"])

    def test_verify_names_a_matched_file_it_cannot_read(self):
        b_path = outline_step(self.store, take=2)
        b_path.write_text("not json", encoding="utf-8")
        list_in_manifest(self.store, b_path)
        check = self.count_check(A.verify(self.store))
        self.assertFalse(check["ok"])
        self.assertIn(f"{b_path.name} is not JSON", check["detail"])

    def test_the_outline_step_writes_the_figures_of_the_shards_it_leaves(self):           # D49
        before = read_index(self.store)["addresses"]
        outline_step(self.store, take=2)
        after = read_index(self.store)["addresses"]
        self.assertEqual(A.figure_differences(after, A.disk_figures(self.store)), [])
        self.assertLess(after["bytes"]["shards"], before["bytes"]["shards"])
        check = next(c for c in A.verify(self.store)["checks"] if c["name"] == A.FIGURES_CHECK)
        self.assertTrue(check["ok"], check)


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class FigureTests(TempFolderMixin, unittest.TestCase):
    """D49: the figures of hail/a in the addresses block are the files' own. The build writes them, the outline step
    writes them back when it rewrites the shards, and verify names any figure that differs from the files."""

    def setUp(self):
        super().setUp()
        self.store = build_rows_store(self.tmp / "figures", base_rows())
        self.index_bytes = (self.store / "hail" / "index.json").read_bytes()
        self.manifest_bytes = (self.store / "hail" / "manifest.json").read_bytes()

    def verify_with(self, change) -> dict:
        """Verify the store with its addresses block changed by change. The manifest entry for the index is written too,
        so the manifest check passes and only the figure can be wrong."""
        index_path = self.store / "hail" / "index.json"
        manifest_path = self.store / "hail" / "manifest.json"
        index = json.loads(self.index_bytes.decode("utf-8"))
        change(index["addresses"])
        index_path.write_text(json.dumps(index), encoding="utf-8")
        manifest = json.loads(self.manifest_bytes.decode("utf-8"))
        data = index_path.read_bytes()
        manifest["files"]["hail/index.json"] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return A.verify(self.store)

    @staticmethod
    def figure_check(result: dict) -> dict:
        return next(c for c in result["checks"] if c["name"] == A.FIGURES_CHECK)

    def test_a_built_store_has_the_figures_of_its_files(self):
        block = read_index(self.store)["addresses"]
        self.assertEqual(A.figure_differences(block, A.disk_figures(self.store)), [])
        check = self.figure_check(A.verify(self.store))
        self.assertTrue(check["ok"], check)
        self.assertIn("as the block says", check["detail"])

    def test_a_stale_figure_fails_verify_and_the_check_names_it(self):
        cases = {
            "bytes.a": lambda block: block["bytes"].update(a=block["bytes"]["a"] + 1),
            "largest_shard": lambda block: block["largest_shard"].update(rows=block["largest_shard"]["rows"] + 1),
            "letter_files": lambda block: block.update(letter_files=block["letter_files"] + 1),
        }
        for label, change in cases.items():
            with self.subTest(figure=label):
                result = self.verify_with(change)
                check = self.figure_check(result)
                self.assertFalse(check["ok"], check)
                self.assertTrue(check["detail"].startswith(f"{label} is "), check["detail"])
                self.assertIn("on disk; rebuild the store", check["detail"])
                self.assertFalse(result["ok"])
                self.assertEqual([c["name"] for c in result["checks"] if not c["ok"]], [A.FIGURES_CHECK])

    def test_a_figure_the_block_lacks_is_named_as_missing(self):
        check = self.figure_check(self.verify_with(lambda block: block.pop("over_limit_shards")))
        self.assertFalse(check["ok"], check)
        self.assertIn("over_limit_shards is missing from the index", check["detail"])

    def test_files_that_cannot_be_read_fail_the_check_without_a_crash(self):
        with mock.patch.object(A, "disk_figures", side_effect=OSError("the folder was removed")):
            result = A.verify(self.store)
        check = self.figure_check(result)
        self.assertFalse(check["ok"], check)
        self.assertIn("could not be read for their figures", check["detail"])
        self.assertIn("the folder was removed", check["detail"])

    def test_refresh_figures_writes_the_files_figures_and_keeps_the_rest_of_the_block(self):
        block = read_index(self.store)["addresses"]
        stale = dict(block, bytes=dict(block["bytes"], a=1),
                     largest_shard={"name": "r0000_c0000", "bytes": 1, "rows": 1})
        fresh = A.refresh_figures(self.store, stale)
        self.assertEqual({key: fresh[key] for key in A.FIGURE_KEYS}, A.disk_figures(self.store))
        rest = {key: value for key, value in block.items() if key not in A.FIGURE_KEYS}
        self.assertEqual({key: value for key, value in fresh.items() if key not in A.FIGURE_KEYS}, rest)


# ---------------------------------------------------------------- the job's step (D9), the workflow and the pins

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def step(self, marker: str) -> str:
        """The text of the job step that holds marker, up to the next step."""
        start = self.text.index(marker)
        end = self.text.find("\n      - name:", start)
        return self.text[start:] if end == -1 else self.text[start:end]

    def test_the_addresses_steps_run_after_the_joins_and_before_the_pack(self):
        joins = self.text.index("Verify the joins")
        build = self.text.index("python -m website.addresses build")
        verify = self.text.index("python -m website.addresses verify")
        unavailable = self.text.index("python -m website.addresses unavailable")
        pack = self.text.index("Pack the store")
        self.assertLess(joins, build)
        self.assertLess(build, verify)
        self.assertLess(verify, unavailable)
        self.assertLess(unavailable, pack)

    def test_the_address_check_runs_before_the_outline_step_rewrites_the_address_files(self):
        verify = self.text.index("python -m website.addresses verify")
        outline = self.text.index("python -m website.buildings build")
        self.assertLess(verify, outline)

    def test_the_failure_branch_marks_the_list_unavailable_with_a_reason(self):
        step = self.step("name: Mark the address list unavailable")
        self.assertIn("steps.addr_build.outputs.built != 'true'", step)
        self.assertIn("steps.addr_verify.outputs.verified != 'true'", step)
        self.assertIn("python -m website.addresses unavailable --store store --reason", step)
        self.assertNotIn("address-restore", self.text)

    def test_the_address_build_and_its_check_cannot_stop_the_job(self):
        for marker in ("id: addr_build", "id: addr_verify"):
            self.assertIn("continue-on-error: true", self.step(marker), marker)

    def test_the_workflow_text_has_no_double_equals_anywhere(self):
        self.assertNotIn("==", self.text)

    @unittest.skipUnless(yaml is not None, "PyYAML is not installed")
    def test_the_workflow_parses_and_the_failure_branch_is_one_step(self):
        steps = yaml.safe_load(self.text)["jobs"]["store"]["steps"]
        failure = [s for s in steps if "website.addresses unavailable" in str(s.get("run", ""))]
        self.assertEqual(len(failure), 1)
        self.assertIn("addr_build.outputs.built", failure[0]["if"])
        by_id = {s["id"]: s for s in steps if "id" in s}
        self.assertIs(by_id["addr_build"]["continue-on-error"], True)
        self.assertIs(by_id["addr_verify"]["continue-on-error"], True)

    def test_pyproj_is_a_compatible_release_in_the_job(self):
        self.assertIn("pip install pyproj~=3.8", self.text)
        self.assertNotIn("==", self.text)

    def test_the_structures_cache_is_keyed_by_name_size_and_last_modified_and_the_month(self):
        self.assertIn("StructuresFramework_shp.zip", self.text)
        self.assertIn("steps.src.outputs.size", self.text)
        self.assertIn("steps.src.outputs.modified", self.text)
        self.assertIn("steps.src.outputs.month", self.text)

    def test_the_source_url_is_the_msl_download(self):
        self.assertIn("https://ftpgeoinfo.msl.mt.gov/Data/Spatial/MSDI/AddressStructures/StructuresFramework_shp.zip",
                      self.text)

    def test_the_build_step_has_its_own_timeout(self):
        step = self.text.split("name: Build the address shards", 1)[1].split("      - name:", 1)[0]
        self.assertRegex(step, r"timeout-minutes: \d+")

    def test_the_addresses_module_is_on_the_push_paths(self):
        self.assertIn('- "website/addresses.py"', self.text)

    def test_the_job_has_a_hundred_and_fifty_minutes(self):
        # The job's own timeout (D50, D51: B5's 60 minutes plus B3's 90); comment lines may sit between its two keys.
        self.assertRegex(self.text, r"\n  store:\n    runs-on: ubuntu-latest\n(?:    #[^\n]*\n)*    timeout-minutes: 150\n")

    def test_the_framework_header_read_cannot_stop_the_job_and_the_awk_test_is_a_regex(self):
        self.assertIn('test -n "$size" && test -n "$modified" || echo', self.text)
        self.assertIn("tolower($1) ~ /^content-length:$/", self.text)


# ---------------------------------------------------------------- the committed fixture (D10)

class FixtureTests(unittest.TestCase):
    def test_the_fixture_has_the_address_folder_and_a_matching_manifest(self):
        self.assertTrue((FIXTURE / "hail" / "a").is_dir())
        self.assertTrue(A.verify(FIXTURE)["ok"])

    def test_the_address_fixture_is_under_fifty_kilobytes_in_all(self):
        # D10: the address files (shards, cities.json, words.json, letter files) are under 50 KB in all. The folder as a
        # whole also holds the B2 sample (35,212 bytes at B2's head); test_hail and test_joins assert on that folder.
        total = sum(p.stat().st_size for p in (FIXTURE / "hail" / "a").rglob("*") if p.is_file())
        self.assertLess(total, 50 * 1024, total)

    def test_the_address_files_hold_only_the_dot_fields_and_no_owner_or_parcel_text(self):
        for path in (FIXTURE / "hail" / "a").rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text.lower(), r"owner|parcel|nguid|globalid|place_type|latitude|longitude")

    def test_the_fixture_index_says_the_addresses_are_a_sample_and_the_counts(self):
        index = json.loads((FIXTURE / "hail" / "index.json").read_text(encoding="utf-8"))
        block = index["addresses"]
        self.assertTrue(block.get("sample"))
        self.assertGreater(block["rows"], 0)

    def test_the_fixture_covers_the_billings_tile_of_401_north_27th(self):
        self.assertTrue((FIXTURE / "hail" / "a" / "r0092_c0214.json").is_file())

    def test_the_committed_fixture_block_has_the_figures_of_its_files(self):               # D49
        block = json.loads((FIXTURE / "hail" / "index.json").read_text(encoding="utf-8"))["addresses"]
        self.assertEqual(A.figure_differences(block, A.disk_figures(FIXTURE)), [])


# ---------------------------------------------------------------- the rules of the build (D1, D4, D20, D22)

LAST_MODIFIED = "Wed, 30 Sep 2026 12:00:00 GMT"


def build_rows_store(folder: Path, rows: list) -> Path:
    """A store made from the given synthetic rows: the B1 sample store with the address build on top (needs pyproj)."""
    folder.mkdir(parents=True, exist_ok=True)
    zip_path = make_zip(folder / "framework.zip", rows)
    store = folder / "store"
    hail.fixture_store(store)
    A.build(zip_path, store)
    return store


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class RuleBuildTests(TempFolderMixin, unittest.TestCase):
    def test_a_deleted_record_is_left_out_and_counted(self):
        rows = pair_rows() + [deleted_row("E", Add_Number=77, St_Name="Ghost", St_PosTyp="Street",
                                          Post_Comm="Red Lodge", Post_Code="59068")]
        store = build_rows_store(self.tmp / "deleted", rows)
        counts = read_index(store)["addresses"]
        self.assertEqual(counts["left_out_deleted"], 1)
        self.assertEqual(counts["rows"], 3)
        self.assertNotIn("Ghost", json.dumps(read_shards(store)))

    def test_a_record_with_no_city_is_left_out_and_counted_and_the_others_keep_their_positions(self):
        m, r, h = pair_rows()
        no_city = row("E", Add_Number=5, St_Name="Ash", St_PosTyp="Street", Inc_Muni="Unincorporated", County="")
        store = build_rows_store(self.tmp / "no-city", [m, no_city, r, h])
        block = read_index(store)["addresses"]
        self.assertEqual(block["state"], "loaded")
        self.assertEqual(block["left_out_no_city"], 1)
        dots = {line: (lon, lat) for doc in read_shards(store) for lon, lat, line, _city, _zip, _cls in doc["a"]}
        self.assertEqual(dots["1611 South Avenue West"], (round(POS["M"][2], 5), round(POS["M"][3], 5)))
        self.assertEqual(dots["500 Colony Road"], (round(POS["R"][2], 5), round(POS["R"][3], 5)))
        self.assertNotIn("5 Ash Street", dots)

    def test_an_out_of_state_label_does_not_remove_a_row(self):
        m, r, h = pair_rows()
        labelled = [row("B", Add_Number=9, St_Name="Ash", St_PosTyp="Street", Post_Comm="Billings",
                        Post_Code="59101", State="ID"),
                    row("D", Add_Number=4, St_Name="Ash", St_PosTyp="Street", Post_Comm="Medora",
                        Post_Code="58645", State="ND")]
        store = build_rows_store(self.tmp / "labels", [m, r, h] + labelled)
        self.assertEqual(read_index(store)["addresses"]["rows"], 5)
        dots = {line: (lon, lat, city) for doc in read_shards(store) for lon, lat, line, city, _zip, _cls in doc["a"]}
        self.assertEqual(dots["9 Ash Street"][:2], (round(POS["B"][2], 5), round(POS["B"][3], 5)))
        self.assertEqual(dots["4 Ash Street"][2], "Medora")
        self.assertNotIn('"ID"', json.dumps(read_shards(store)))
        self.assertNotIn('"ND"', json.dumps(read_shards(store)))

    def test_a_city_is_shown_in_the_spelling_the_file_uses_most(self):
        spellings = [row("E", Add_Number=n, St_Name="Main", St_PosTyp="Street", Post_Comm="Red Lodge",
                         Post_Code="59068") for n in (1, 2, 3, 4, 5)]
        spellings.append(row("E", Add_Number=9, St_Name="Main", St_PosTyp="Street", Post_Comm="Red lodge",
                             Post_Code="59068"))
        store = build_rows_store(self.tmp / "spelling", pair_rows() + spellings)
        dots = [item for doc in read_shards(store) for item in doc["a"] if item[2].endswith("Main Street")]
        self.assertEqual(len(dots), 6)
        self.assertEqual({item[3] for item in dots}, {"Red Lodge"})


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class PlacementBuildTests(TempFolderMixin, unittest.TestCase):
    """Each spelling of the Placement field is its class in the shards and the letter files, and verify counts the classes
    per county (D32)."""
    SPELLINGS = [("Structure", "S"), ("Property Access", "P"), ("PropertyAccess", "P"), ("Geocoding", "G"),
                 ("Parcel", "L"), ("Site", "T"), ("Unknown", "U"), ("", "U")]

    def setUp(self):
        super().setUp()
        rows = pair_rows() + [row("E", Add_Number=100 + k, St_Name="Placed", St_PosTyp="Way", Post_Comm="Red Lodge",
                                  Post_Code="59068", County="Carbon County", Placement=value)
                              for k, (value, _letter) in enumerate(self.SPELLINGS)]
        self.store = build_rows_store(self.tmp / "placement", rows)

    def test_each_spelling_is_its_class_in_the_shards(self):
        classes = {r[2]: r[5] for doc in read_shards(self.store) for r in doc["a"]}
        for k, (value, letter) in enumerate(self.SPELLINGS):
            self.assertEqual(classes[f"{100 + k} Placed Way"], letter, repr(value))

    def test_each_spelling_is_its_class_in_the_letter_file_of_its_street(self):
        letter = json.loads((self.store / "hail" / "a" / "idx" / "red-lodge" / "P.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(row[6] for row in letter["a"]), sorted(letter for _value, letter in self.SPELLINGS))

    def test_the_index_counts_the_classes_per_county_and_verify_checks_them(self):
        block = read_index(self.store)["addresses"]
        carbon = block["placement"]["by_county"]["Carbon County"]
        self.assertEqual(carbon, {"S": 1, "P": 2, "G": 1, "L": 1, "T": 1, "U": 2})
        result = A.verify(self.store)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["counts"]["placement_by_county"]["Carbon County"], carbon)

    def test_a_placement_count_that_does_not_add_up_fails_verify(self):
        index_path = self.store / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["addresses"]["placement"]["classes"]["U"] += 1
        index_path.write_text(json.dumps(index), encoding="utf-8")
        manifest_path = self.store / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["hail/index.json"] = {"bytes": index_path.stat().st_size,
                                                "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = A.verify(self.store)
        failed = [c["name"] for c in result["checks"] if not c["ok"]]
        self.assertIn("the placement classes add up to the kept rows and to the counties", failed)


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class OutsideGridTests(TempFolderMixin, unittest.TestCase):
    """D23: an address tile with no B1 shard is listed by verify as detail text (it is not a failure)."""

    def test_verify_lists_the_address_tiles_with_no_hail_grid_shard_as_detail_text(self):
        store = build_rows_store(self.tmp / "outside", base_rows())
        result = A.verify(store)
        check = next(c for c in result["checks"] if c["name"].startswith("address tiles with no hail grid shard"))
        self.assertTrue(check["ok"])
        self.assertIn("r0096_c0211", check["detail"])            # Red Lodge: the sample has no shard there
        self.assertNotIn("r0092_c0214", check["detail"])         # Billings: the sample holds that tile's shard
        self.assertEqual(result["counts"]["tiles_outside_hail_grid"]["r0096_c0211"], 1)
        self.assertTrue(result["ok"], result)


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class LetterLimitTests(TempFolderMixin, unittest.TestCase):
    def test_verify_flags_a_two_character_split_that_the_limit_does_not_justify(self):
        with mock.patch.object(A, "ROWS_LIMIT", 3):
            store = build_rows_store(self.tmp / "split", base_rows())
        with mock.patch.object(A, "ROWS_LIMIT", 10):
            result = A.verify(store)
        check = next(c for c in result["checks"] if c["name"].startswith("two-character letter files are used only"))
        self.assertFalse(check["ok"])
        self.assertIn("Billings: 2 is split to two characters but holds 6 rows", check["detail"])

    def test_verify_flags_a_two_character_letter_file_over_the_limit(self):
        # At a limit of 3, Billings' "27th" rows (six) are too many for one letter, so they are keyed "27" and that
        # two-character file is over the limit: verify must name it (D5; the check used to read one-character keys).
        with mock.patch.object(A, "ROWS_LIMIT", 3):
            store = build_rows_store(self.tmp / "limit", base_rows())
            result = A.verify(store)
        letters = next(c for c in result["checks"]
                       if c["name"] == "every letter file holds the rows its cities file says")
        self.assertFalse(letters["ok"])
        self.assertIn("27.json is over the limit", letters["detail"])


class FakeFetcher:
    """Stands in for website.sources.Fetcher (patched in by these tests): one HEAD answer (a status, a
    Last-Modified header, or an exception) and one body for the GET. It counts its requests, so a test can see a
    cache hit make no GET."""

    def __init__(self, body: bytes, *, status: int = 200, modified=LAST_MODIFIED, error=None, content_length=None):
        self.body, self.status, self.modified, self.error = body, status, modified, error
        self.content_length = len(body) if content_length is None else content_length
        self.timeout = 5
        self.heads = 0
        self.gets = 0
        self.s = self

    def head(self, url, allow_redirects=True, timeout=None):
        self.heads += 1
        if self.error is not None:
            raise self.error
        headers = {"Content-Length": str(self.content_length)}
        if self.modified is not None:
            headers["Last-Modified"] = self.modified
        return types.SimpleNamespace(status_code=self.status, headers=headers)

    def binary(self, url):
        self.gets += 1
        return self.body


class DownloadTests(TempFolderMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.body = make_zip(self.tmp / "source.zip", base_rows()).read_bytes()
        self.cache = self.tmp / "cache"
        self.url = "https://example.invalid/StructuresFramework_shp.zip"

    def download_with(self, fake):
        with mock.patch("website.sources.Fetcher", return_value=fake):
            return A.download(self.cache, self.url)

    def test_a_cache_hit_makes_one_head_and_no_get(self):
        path, _info = self.download_with(FakeFetcher(self.body))
        again = FakeFetcher(self.body)
        path_again, info_again = self.download_with(again)
        self.assertEqual((again.heads, again.gets), (1, 0))
        self.assertEqual(path, path_again)
        self.assertEqual(info_again["last_modified"], LAST_MODIFIED)
        self.assertEqual(info_again["sha256"], hashlib.sha256(self.body).hexdigest())

    def test_a_changed_last_modified_fetches_the_file_again(self):
        self.download_with(FakeFetcher(self.body))
        changed = FakeFetcher(self.body, modified="Thu, 15 Oct 2026 12:00:00 GMT")
        self.download_with(changed)
        self.assertEqual((changed.heads, changed.gets), (1, 1))

    def test_a_503_head_is_a_source_failure_and_no_get_is_made(self):
        fake = FakeFetcher(self.body, status=503)
        with self.assertRaises(A.SourceUnavailable) as caught:
            self.download_with(fake)
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertEqual(fake.gets, 0)

    def test_an_unreachable_host_is_a_source_failure_and_no_get_is_made(self):
        fake = FakeFetcher(self.body, error=ConnectionError("no route to host"))
        with self.assertRaises(A.SourceUnavailable) as caught:
            self.download_with(fake)
        self.assertIn("ConnectionError", str(caught.exception))
        self.assertEqual(fake.gets, 0)

    def test_a_body_that_is_not_a_zip_is_a_source_failure(self):
        with self.assertRaises(A.SourceUnavailable) as caught:
            self.download_with(FakeFetcher(b"<html>not the file</html>"))
        self.assertIn("not a zip", str(caught.exception))

    def test_a_body_of_another_size_than_the_server_gave_is_a_source_failure(self):
        with self.assertRaises(A.SourceUnavailable) as caught:
            self.download_with(FakeFetcher(self.body, content_length=len(self.body) + 5))
        self.assertIn("not the size", str(caught.exception))

    def test_a_fetcher_that_raises_on_the_body_is_a_source_failure_and_no_file_is_kept(self):
        fake = FakeFetcher(self.body)
        fake.binary = mock.Mock(side_effect=ConnectionError("connection reset"))
        with self.assertRaises(A.SourceUnavailable) as caught:
            self.download_with(fake)
        self.assertIn("ConnectionError", str(caught.exception))
        self.assertFalse((self.cache / A.ZIP_NAME).exists())

    def test_the_cache_is_keyed_by_name_size_and_last_modified(self):
        self.download_with(FakeFetcher(self.body))
        meta = json.loads((self.cache / (A.ZIP_NAME + ".meta.json")).read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], A.ZIP_NAME)
        self.assertEqual(meta["bytes"], len(self.body))
        self.assertEqual(meta["size"], len(self.body))
        self.assertEqual(meta["last_modified"], LAST_MODIFIED)


class LedgerVerbTests(TempFolderMixin, unittest.TestCase):
    """The download ledger names a cache hit CACHE, with no status, and a request GET, as the roads and outline modules
    do: a warm run makes no GET, and the last line of a cold run is the GET that fetched the file."""

    def setUp(self):
        super().setUp()
        self.cache = self.tmp / "cache"
        self.ledger = self.tmp / "ledger.jsonl"
        self.body = make_zip(self.tmp / "source.zip", base_rows()).read_bytes()

    def ledger_lines(self) -> list:
        return [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()]

    def test_a_cache_hit_is_logged_as_cache_with_no_status(self):
        A.download(self.cache, A.MSL_URL, fetcher=FakeFetcher(self.body))            # the cold run has no ledger
        warm = FakeFetcher(self.body)
        A.download(self.cache, A.MSL_URL, fetcher=warm, ledger=self.ledger)
        self.assertEqual((warm.heads, warm.gets), (1, 0))
        self.assertNotIn("GET", [line["method"] for line in self.ledger_lines()])
        last = self.ledger_lines()[-1]
        self.assertEqual((last["method"], last["cache"], last["status"]), ("CACHE", "hit", None))

    def test_a_fetch_is_logged_as_get_with_status_200(self):
        fake = FakeFetcher(self.body)
        A.download(self.cache, A.MSL_URL, fetcher=fake, ledger=self.ledger)
        self.assertEqual(fake.gets, 1)
        last = self.ledger_lines()[-1]
        self.assertEqual((last["method"], last["cache"], last["status"]), ("GET", "fetched", 200))


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class DownloadBuildTests(TempFolderMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.body = make_zip(self.tmp / "source.zip", base_rows()).read_bytes()
        self.store = self.tmp / "store"
        hail.fixture_store(self.store)
        self.cache = self.tmp / "cache"
        self.url = "https://example.invalid/StructuresFramework_shp.zip"

    def build_with(self, fake):
        with mock.patch("website.sources.Fetcher", return_value=fake):
            return A.build(None, self.store, cache=self.cache, url=self.url)

    def test_a_good_download_builds_the_list_and_a_second_run_uses_the_cache(self):
        self.assertEqual(self.build_with(FakeFetcher(self.body))["state"], "loaded")
        second = FakeFetcher(self.body)
        self.build_with(second)
        self.assertEqual((second.heads, second.gets), (1, 0))
        self.assertTrue(A.verify(self.store)["ok"])

    def test_a_503_head_marks_the_list_unavailable_from_its_source_and_the_store_still_verifies(self):
        with self.assertRaises(A.SourceUnavailable):
            self.build_with(FakeFetcher(self.body, status=503))
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIs(block["source_unavailable"], True)
        self.assertFalse((self.store / "hail" / "a").exists())
        result = A.verify(self.store)
        self.assertTrue(result["ok"], result)
        self.assertIn("the list is unavailable from its source; the sheet says so",
                      [c["name"] for c in result["checks"]])
        self.assertEqual(A.describe_addresses(read_index(self.store))["source"], WORDS["about_source_undated"])

    def test_an_unreachable_host_marks_the_list_unavailable_from_its_source(self):
        with self.assertRaises(A.SourceUnavailable):
            self.build_with(FakeFetcher(self.body, error=ConnectionError("no route to host")))
        self.assertIs(read_index(self.store)["addresses"]["source_unavailable"], True)
        self.assertTrue(A.verify(self.store)["ok"])


class MainTests(TempFolderMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = self.tmp / "store"
        hail.fixture_store(self.store)
        self.cache = self.tmp / "cache"

    def run_main(self, argv, fake):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("website.sources.Fetcher", return_value=fake), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = A.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_503_head_exits_zero_and_the_list_is_unavailable_from_its_source(self):
        code, _out, err = self.run_main(["build", "--store", str(self.store), "--cache", str(self.cache)],
                                        FakeFetcher(b"", status=503))
        self.assertEqual(code, 0, err)
        self.assertIn("unavailable", err)
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIs(block["source_unavailable"], True)
        self.assertFalse((self.store / "hail" / "a").exists())
        self.assertTrue(A.verify(self.store)["ok"])

    def test_an_unreachable_host_exits_zero_and_the_list_is_unavailable_from_its_source(self):
        code, _out, err = self.run_main(["build", "--store", str(self.store), "--cache", str(self.cache)],
                                        FakeFetcher(b"", error=ConnectionError("no route to host")))
        self.assertEqual(code, 0, err)
        self.assertIs(read_index(self.store)["addresses"]["source_unavailable"], True)
        self.assertFalse((self.store / "hail" / "a").exists())

    @unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job installs it)")
    def test_a_failure_that_is_not_a_source_failure_exits_one(self):
        zip_path = make_zip(self.tmp / "framework.zip", base_rows())
        with mock.patch.object(A, "_write_tree", side_effect=A.AddressesError("the shards could not be written")):
            code, _out, err = self.run_main(["build", "--store", str(self.store), "--zip", str(zip_path)],
                                            FakeFetcher(b""))
        self.assertEqual(code, 1)
        self.assertIn("error: the shards could not be written", err)
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIs(block["source_unavailable"], False)

    def test_a_changed_terms_sentence_exits_zero_and_the_list_is_unavailable_from_its_source(self):
        zip_path = make_zip(self.tmp / "terms.zip", base_rows(),
                            useconst=USECONST.replace("for informational purposes only", "for general purposes"))
        code, _out, err = self.run_main(["build", "--store", str(self.store), "--zip", str(zip_path)],
                                        FakeFetcher(b""))
        self.assertEqual(code, 0, err)
        self.assertIn("the list is marked unavailable", err)
        self.assertIs(read_index(self.store)["addresses"]["source_unavailable"], True)
        self.assertFalse((self.store / "hail" / "a").exists())

    @unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job installs it)")
    def test_verify_of_a_damaged_source_exits_one_when_the_file_cannot_be_read_back(self):
        good = make_zip(self.tmp / "good.zip", base_rows())
        self.run_main(["build", "--store", str(self.store), "--zip", str(good)], FakeFetcher(b""))
        self.assertTrue((self.store / "hail" / "a").is_dir())
        with zipfile.ZipFile(good) as zf:
            table = zf.read(DATA_DBF_NAME)
        # the header still reads, so the failure is in the recount: the table ends before its last record
        cut = copy_zip_with(good, self.tmp / "cut.zip", DATA_DBF_NAME, table[: len(table) // 2])
        code, out, err = self.run_main(["verify", str(self.store), "--zip", str(cut)], FakeFetcher(b""))
        self.assertEqual(code, 1)
        checks = {c["name"]: c["ok"] for c in json.loads(out)["checks"]}
        self.assertTrue(checks["the framework file reads as the one this build reads"])
        self.assertFalse(checks["the file recomputes to the index (counts, classes, merges and pairs)"])

    def test_a_missing_zip_exits_zero_and_the_list_is_unavailable_from_its_source(self):
        code, _out, err = self.run_main(["build", "--store", str(self.store), "--zip", str(self.tmp / "missing.zip")],
                                        FakeFetcher(b""))
        self.assertEqual(code, 0, err)
        self.assertIn("the list is marked unavailable", err)
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIs(block["source_unavailable"], True)
        self.assertIn("is not there", block["reason"])
        self.assertTrue(A.verify(self.store)["ok"])

    def test_an_unreadable_zip_exits_zero_and_the_list_is_unavailable_from_its_source(self):
        zip_path = make_zip(self.tmp / "framework.zip", base_rows())
        with mock.patch.object(A, "_sha256_file", side_effect=PermissionError(13, "Permission denied")):
            code, _out, err = self.run_main(["build", "--store", str(self.store), "--zip", str(zip_path)],
                                            FakeFetcher(b""))
        self.assertEqual(code, 0, err)
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIn("could not be read (PermissionError)", block["reason"])


# ---------------------------------------------------------------- the unavailable command and the failure branch (D36)

class UnavailableCommandTests(TempFolderMixin, unittest.TestCase):
    """`unavailable --store STORE --reason TEXT` (D36): the job's failure branch writes the unavailable block with the
    reason and removes the address files and any leftover of an interrupted build, so a crashed build or a failed check
    leaves a block, never a missing one."""

    def setUp(self):
        super().setUp()
        self.store = self.tmp / "store"
        shutil.copytree(FIXTURE, self.store)          # a store with a loaded SAMPLE address list and its a/ files
        self.assertTrue((self.store / "hail" / "a").is_dir())

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = A.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_the_command_writes_the_reason_and_removes_the_address_files(self):
        code, out, err = self.run_main(["unavailable", "--store", str(self.store), "--reason",
                                        "the address build did not pass"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["state"], "unavailable")
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["reason"], f"{A.UNAVAILABLE}: the address build did not pass")
        self.assertIs(block["source_unavailable"], True)
        self.assertFalse((self.store / "hail" / "a").exists())
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse([name for name in manifest["files"] if name.startswith("hail/a/")])
        hail.check_manifest(self.store)               # the store still checks against its manifest
        self.assertTrue(A.verify(self.store)["ok"])

    def test_a_reason_that_already_names_the_list_is_not_prefixed_twice_and_is_one_line(self):
        code, _out, err = self.run_main(["unavailable", "--store", str(self.store), "--reason",
                                         f"{A.UNAVAILABLE}:   the\npage"])
        self.assertEqual(code, 0, err)
        self.assertEqual(read_index(self.store)["addresses"]["reason"], f"{A.UNAVAILABLE}: the page")

    def test_a_stage_folder_and_a_temp_file_from_an_interrupted_build_are_removed(self):
        (self.store / "hail" / ".a-stage").mkdir()
        (self.store / "hail" / ".a-stage" / "r0092_c0214.json").write_text("{}", encoding="utf-8")
        (self.store / "hail" / ".addr-12345").write_bytes(b"part of an index")
        code, _out, err = self.run_main(["unavailable", "--store", str(self.store), "--reason",
                                         "the build was interrupted"])
        self.assertEqual(code, 0, err)
        self.assertFalse((self.store / "hail" / ".a-stage").exists())
        self.assertFalse((self.store / "hail" / ".addr-12345").exists())
        hail.check_manifest(self.store)               # nothing under hail/ is left that the manifest does not list

    def test_without_a_store_the_command_is_a_failure_and_writes_nothing(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        code, _out, err = self.run_main(["unavailable", "--store", str(empty), "--reason", "the build did not pass"])
        self.assertEqual(code, 1)
        self.assertIn("no hail index", err)
        self.assertFalse((empty / "hail").exists())

    def test_the_command_needs_a_reason_and_refuses_an_empty_one(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(["unavailable", "--store", str(self.store)])      # argparse: a missing --reason is exit 2
        self.assertEqual(caught.exception.code, 2)
        code, _out, err = self.run_main(["unavailable", "--store", str(self.store), "--reason", "   "])
        self.assertEqual(code, 2)
        self.assertIn("give the reason", err)
        self.assertTrue((self.store / "hail" / "a").is_dir())         # nothing was removed


class MissingProjectionTests(TempFolderMixin, unittest.TestCase):
    """D36: a missing projection library (the lazy import in _transformer) is the unavailable state with its reason, the
    command line exits 0 so the job goes on, and the check runs before the table is read (no stream first)."""

    def setUp(self):
        super().setUp()
        self.store = self.tmp / "store"
        hail.fixture_store(self.store)
        self.zip_path = make_zip(self.tmp / "framework.zip", base_rows())

    def test_the_missing_library_is_the_unavailable_state_with_its_reason_before_the_table_is_read(self):
        with projection_library_missing(), \
                mock.patch.object(A, "_collect", side_effect=AssertionError("the table was read first")):
            with self.assertRaises(A.SourceUnavailable) as caught:
                A.build(self.zip_path, self.store)
        self.assertIn("the projection library is not installed", str(caught.exception))
        block = read_index(self.store)["addresses"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIn("the projection library is not installed", block["reason"])
        self.assertIs(block["source_unavailable"], True)
        self.assertFalse((self.store / "hail" / "a").exists())
        self.assertTrue(A.verify(self.store)["ok"])

    def test_the_command_line_exits_zero_and_the_job_goes_on(self):
        out, err = io.StringIO(), io.StringIO()
        with projection_library_missing(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = A.main(["build", "--store", str(self.store), "--zip", str(self.zip_path)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("the list is marked unavailable", err.getvalue())
        self.assertIs(read_index(self.store)["addresses"]["source_unavailable"], True)


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class MissingProjectionVerifyTests(TempFolderMixin, unittest.TestCase):
    """verify --zip recomputes the positions, so without the projection library the recount fails as a check: verify
    returns its result and never passes silently (D36)."""

    def test_verify_with_the_zip_and_no_projection_library_fails_the_recount(self):
        zip_path = make_zip(self.tmp / "framework.zip", base_rows())
        store = self.tmp / "store"
        hail.fixture_store(store)
        A.build(zip_path, store)
        with projection_library_missing():
            result = A.verify(store, zip_path)
        self.assertFalse(result["ok"])
        failed = {c["name"]: c["detail"] for c in result["checks"] if not c["ok"]}
        name = "the file recomputes to the index (counts, classes, merges and pairs)"
        self.assertIn(name, failed)
        self.assertIn("the projection library is not installed", failed[name])


# ---------------------------------------------------------------- one placement class per merged group (D39)

class MergedGroupTests(unittest.TestCase):
    """D39: a merged group keeps its Structure row, and the merge report counts the groups by the classes they hold."""

    @staticmethod
    def make(lon5: int, lat5: int, cls: str) -> A.Row:
        return A.Row(lon5, lat5, "1 Main Street", "Billings", "59101", 1, "Main Street", "", 1, "M", cls, "")

    def groups(self) -> list:
        return [
            self.make(10, 20, "P"), self.make(10, 20, "S"),     # P and S: the Structure row is kept
            self.make(30, 40, "U"), self.make(30, 40, "S"),     # U and S: the Structure row is kept
            self.make(50, 60, "G"), self.make(50, 60, "P"),     # P and G, no Structure row: the earliest class is kept
            self.make(70, 80, "S"), self.make(70, 80, "S"),     # two Structure rows: one is kept
            self.make(90, 95, "L"),                             # a single row, not a merged group
        ]

    def test_the_merge_keeps_the_structure_row_and_otherwise_the_earliest_class(self):
        kept, _report = A._dedupe(self.groups())
        self.assertEqual({(r.lon5, r.lat5): r.cls for r in kept},
                         {(10, 20): "S", (30, 40): "S", (50, 60): "P", (70, 80): "S", (90, 95): "L"})

    def test_the_report_counts_the_groups_and_their_class_pairs(self):
        _kept, report = A._dedupe(self.groups())
        self.assertEqual(report, {"groups": 4, "merged_rows": 4, "two_classes": 3,
                                  "classes": {"P+G": 1, "S+P": 1, "S+U": 1},
                                  "with_structure": 3, "structure_kept": 3})

    def test_the_report_does_not_depend_on_the_order_of_the_rows(self):
        self.assertEqual(A._dedupe(self.groups()), A._dedupe(list(reversed(self.groups()))))

    def test_a_report_that_disagrees_with_itself_or_the_index_is_refused(self):
        _kept, report = A._dedupe(self.groups())
        self.assertTrue(A._merge_report_ok(report, 4))
        self.assertFalse(A._merge_report_ok(report, 5))
        self.assertFalse(A._merge_report_ok(dict(report, two_classes=2), 4))
        self.assertFalse(A._merge_report_ok(dict(report, structure_kept=2), 4))
        self.assertFalse(A._merge_report_ok(None, 4))


@unittest.skipUnless(HAVE_PYPROJ, "pyproj is not installed (the job pins it)")
class MergedGroupBuildTests(TempFolderMixin, unittest.TestCase):
    """D39 on a built store: the Structure row of a merged group is the dot kept, the index's merge report says so, and
    verify checks the report against its own arithmetic and, with the zip, against the file."""

    def setUp(self):
        super().setUp()
        same = dict(Add_Number=401, St_PreDir="North", St_Name="27th", St_PosTyp="Street", Post_Comm="Billings",
                    Post_Code="59101")
        rows = pair_rows() + [row("A", Placement="Property Access", **same), row("A", Placement="Structure", **same)]
        self.zip_path = make_zip(self.tmp / "merge.zip", rows)
        self.store = self.tmp / "store"
        hail.fixture_store(self.store)
        A.build(self.zip_path, self.store)

    def tamper_index(self, change) -> None:
        index_path = self.store / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        change(index["addresses"])
        index_path.write_text(json.dumps(index), encoding="utf-8")
        manifest_path = self.store / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["hail/index.json"] = {"bytes": index_path.stat().st_size,
                                                "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_the_structure_row_is_kept_and_the_report_counts_the_pair(self):
        self.assertEqual(read_index(self.store)["addresses"]["merged_groups"],
                         {"groups": 1, "merged_rows": 1, "two_classes": 1, "classes": {"S+P": 1},
                          "with_structure": 1, "structure_kept": 1})
        classes = {r[2]: r[5] for doc in read_shards(self.store) for r in doc["a"]}
        self.assertEqual(classes["401 North 27th Street"], "S")

    def test_verify_passes_with_the_zip_and_refuses_a_report_that_disagrees(self):
        result = A.verify(self.store, self.zip_path)
        self.assertTrue(result["ok"], [c for c in result["checks"] if not c["ok"]])
        self.assertEqual(result["counts"]["merged_groups"]["two_classes"], 1)
        self.tamper_index(lambda block: block["merged_groups"].update(two_classes=2))
        failed = [c["name"] for c in A.verify(self.store)["checks"] if not c["ok"]]
        self.assertIn("the merged groups keep the Structure row (D39)", failed)

    def test_the_zip_recount_catches_a_report_that_agrees_with_itself_but_not_with_the_file(self):
        self.tamper_index(lambda block: block["merged_groups"].update(with_structure=0, structure_kept=0))
        self.assertTrue(A.verify(self.store)["ok"])     # the store alone is consistent with itself
        failed = [c["name"] for c in A.verify(self.store, self.zip_path)["checks"] if not c["ok"]]
        self.assertIn("the merged groups match the file (D39)", failed)


class DocumentedDecisionTests(unittest.TestCase):
    """The module docstring records the decisions this module carries: D39 (a merged group keeps its Structure row), D40
    (the row formats carry the class) and D41 (Placement is the seventeenth allow-listed field), and the command that
    the job's failure branch runs."""

    def test_the_module_docstring_records_d39_d40_d41_and_the_unavailable_command(self):
        for text in ("D39", "D40", "D41", "unavailable --store DIR --reason TEXT"):
            self.assertIn(text, A.__doc__)


# ---------------------------------------------------------------- the real file's quoted sentences (D8, D24)

REAL_ZIP = os.environ.get("ADDRESS_FRAMEWORK_ZIP", "")


@unittest.skipUnless(REAL_ZIP and Path(REAL_ZIP).is_file(),
                     "set ADDRESS_FRAMEWORK_ZIP to the cached framework zip to check the quoted sentences against it")
class RealMetadataTests(unittest.TestCase):
    def test_the_quoted_sentences_are_the_files_own_metadata(self):
        facts = A.source_facts(REAL_ZIP)
        self.assertEqual(facts["accconst"], ACCCONST)
        self.assertEqual(facts["useconst"], USECONST)
        self.assertEqual(facts["purpose"], PURPOSE)


# ---------------------------------------------------------------- the command line

class CommandLineTests(unittest.TestCase):
    def test_the_command_line_has_build_verify_and_fixture(self):
        out = subprocess.run([sys.executable, "-m", "website.addresses", "--help"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        for command in ("build", "verify", "fixture", "unavailable"):
            self.assertIn(command, out.stdout)


if __name__ == "__main__":
    unittest.main()
