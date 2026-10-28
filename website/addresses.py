"""Address dots and the typed-address search (B3): the data module.

Montana's public address list (the Montana State Library Structures and Addresses Framework, MSL file
StructuresFramework_shp.zip) becomes site files under hail/a/ of the hail store (docs/DECISIONS.md D34; the B3
brief, decisions D1 to D12, D32 to D36 and D39 to D41). Owner decision 6: no owner, parcel, place-type or building-use
field is ever read, stored or shown. The reader slices seventeen allow-listed fields and no others (ALLOWED_FIELDS).
D41 makes Placement the seventeenth: D1 listed sixteen, and Placement, the method that placed each point, is read for
the placement class (D32). It is not what the place is, and it is not an owner, parcel, place-type or building-use
field. Every other field of the table is skipped without being decoded.

Output, written into the store next to B1's shards and B2's joins (store/hail/):
  a/<tile name><digits>.json   one shard per quadtree leaf of a B1 tile (0.1 degree): split into quarters while a
                               shard holds more than 2,500 rows, depth cap 6. Names: the tile name plus one digit
                               per level (0 NW, 1 NE, 2 SW, 3 SE). {"f":"hail-addresses-v1","b":[w,s,e,n],
                               "n":rows,"a":[[lon,lat,"line","city","zip","class"],...]} with positions rounded to 5
                               decimals; "line" is the number, the street and the unit, in that order; "class" is the
                               placement class letter (S, P, G, L, T or U; D32).
  a/idx/cities.json            the city names, with their row counts and the file key counts for each city
  a/idx/<city dir>/<key>.json  one letter file per city and key (the first character of St_Name, upper-cased; two
                               characters when that one-character file would hold more than 2,500 rows):
                               {"f":"hail-address-idx-v1","a":[[number,"street","unit",lon,lat,"zip","class"],...]}
  a/idx/words.json             the abbreviations the search expands (directions, street types, US, MT, #)
  hail/index.json              gains "addresses": the state, the source (file, size, export date, pubdate and the
                               three metadata sentences quoted at build time), the counts, the measures, the
                               projection checks and the merge report (merged_groups, D39); hail/manifest.json lists
                               every a/ file with its size and SHA-256. The figures of hail/a in the block (the shard
                               count and bytes, the largest shard, the depths and the search index's figures) are the
                               files' own: the outline step rewrites the shards and writes the figures back (D49), and
                               verify compares them with the files (FIGURES_CHECK)

The row formats carry the class (D40): a shard row is [lon, lat, line, city, zip, class] and a letter row is
[number, street, unit, lon, lat, zip, class]. The class is the last element of each row (the sixth of a shard row,
the seventh of a letter row); the buildings module and the browser read it by position and never guess it.

Rules (the B3 brief): positions are the file's EPSG:6514 projected to EPSG:4326 (pyproj, always_xy) and rounded to 5
decimals. A row needs a position, a St_Name and a city; a row without one of them is left out and counted; exact
duplicate rows (same position, line, city and zip) are merged and counted (D22). A merged group keeps its Structure
row when it has one, so the dot sits on the building (D39); otherwise it keeps the row with the earliest class in
MERGE_PREFERENCE. On the 2026-09-30 file the 4,863 merged groups hold 6,744 merged rows, and 2,847 of the groups hold
rows of two placement classes (P and S in 2,841, S and U in 6); every group with a Structure row keeps it. The merge
report is written to index.json (merged_groups). verify checks it against its own arithmetic and, with --zip, against
the file. The line is the number (AddNum_Pre, Add_Number and AddNum_Suf; omitted when the number is 0 or blank), then
the street words in NENA order, then the unit when there is one. A unit whose first word is two or more letters (then
digits, if any) is kept as written and title-cased ("APT2" is "Apt2", "RM403" is "Rm403"); any other unit gets "Unit "
in front ("A1" is "Unit A1", "A" is "Unit A", "#3" is "Unit #3"). City: Post_Comm; when blank, Inc_Muni unless it reads
"Unincorporated", else County. Zip:
Post_Code when it is exactly five digits. A city name is shown in one spelling: the mixed-case spelling the file uses
most, so "LEWISTOWN" is "Lewistown" and "St. Ignatius" is "St Ignatius" (names that differ only in capitals or
punctuation are one city).

Placement (D32): the file's Placement value gives each row one class letter: S Structure; P Property Access and
PropertyAccess (one value); G Geocoding; L Parcel; T Site; U Unknown. A blank value is U (a method the file does not
state). Any other value is not the file this build reads. The class counts are recorded per county in index.json.

A changed file fails loudly (D36): every failure to read or validate the source (a failed HEAD or download, a wrong or
unreadable --zip path, a missing projection library, a file that will not decode, the field list, the header, the
projection, a placement value, a terms sentence that is not the one the site quotes, a record count that does not add
up) is a SourceUnavailable: the list is marked "unavailable" in index.json with its reason, the a/ files are removed,
the rest of the store is kept, and the build exits 0 so the job goes on. Any other failure (no store, a failed write)
exits 1, and verify exits 1 when a check fails. The job's failure branch then runs `unavailable` (below), so a failed
build or check leaves the store with an unavailable block and never without one. Nothing here reads a network address
except the download (build without --zip).

Command line (run from the repository root):
    python -m website.addresses build --store DIR [--zip FILE] [--cache DIR] [--url URL] [--ledger FILE]
    python -m website.addresses verify --store DIR [--zip FILE]
    python -m website.addresses fixture --store REAL_STORE [--out DIR]
    python -m website.addresses unavailable --store DIR --reason TEXT

pyproj is imported only when a position is projected (the daily job installs pyproj~=3.8, a compatible release, D19;
the tests skip without it). A missing pyproj is the unavailable state (D36), not a traceback. No other package is
needed: the reader is a stream over the zip.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import random
import re
import shutil
import struct
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections import Counter, defaultdict, namedtuple
from datetime import datetime, timezone
from pathlib import Path

from . import hail

FORMAT = "hail-addresses-v1"              # the shard files and the index block
CITIES_FORMAT = "hail-address-cities-v1"  # a/idx/cities.json
IDX_FORMAT = "hail-address-idx-v1"        # a/idx/<city dir>/<key>.json
WORDS_FORMAT = "hail-address-words-v1"    # a/idx/words.json
INDEX_KEY = "addresses"                   # the block in hail/index.json
ROWS_LIMIT = 2500                         # rows per shard and per letter file (D5)
DEPTH_CAP = 6                             # quadtree depth: 0.1 / 2**6 = 0.0015625 degree (D5)
SCALE = 100000                            # positions are whole units of 1e-5 degree (5 decimals)
TAP_RADIUS_PX = 12                       # a tap picks the nearest dot within this many pixels (D7)
ZOOM = {"dots": 15, "choose": 17}         # D27, D47: address dots from zoom 15; a chosen search row zooms to 17
DOT_RADIUS_PX = {"zoom": 13, "at_zoom": 2.5, "per_zoom": 0.5, "max": 4.0}   # D7: the dot radius at a zoom, capped at max
RESULT_CAP = 20                           # the search lists at most this many matches (D6)
PROJECTION_TOLERANCE_M = 2.0              # the three recorded pairs must agree within this (D2)
SUB = 64                                  # sub-units per 1e-5 degree: every quadtree edge to depth 6 is whole in these (B3R-07)
PLACEMENT_CLASS = {"Structure": "S", "Property Access": "P", "PropertyAccess": "P", "Geocoding": "G",
                   "Parcel": "L", "Site": "T", "Unknown": "U", "": "U"}   # the file's Placement values (D32)
CLASS_LETTERS = "SPGLTU"                  # the classes in the order the counts are written
CLASS_SET = frozenset(CLASS_LETTERS)      # the same, for membership tests
MERGE_PREFERENCE = "SPGLTU"               # a merged duplicate keeps the row with the earliest class here (D32, D39)
PLACEMENT_HOW = {                         # how a non-Structure point was placed, for its popup (D32)
    "P": "at the property entrance", "G": "along the road by its number", "L": "at the parcel",
    "T": "at the site", "U": "by a method the file does not state"}
MSL_URL = ("https://ftpgeoinfo.msl.mt.gov/Data/Spatial/MSDI/AddressStructures/"
           "StructuresFramework_shp.zip")
ZIP_NAME = "StructuresFramework_shp.zip"
PRJ_NAME = "NAD_1983_2011_StatePlane_Montana_FIPS_2500"
SHP_NAME = "SiteStructureAddressPoint.shp"
SHX_NAME = "SiteStructureAddressPoint.shx"
DBF_NAME = "SiteStructureAddressPoint.dbf"
PRJ_MEMBER = "SiteStructureAddressPoint.prj"
README_NAME = "_ReadMe.txt"
META_NAME = "StructuresFramework_metadata.xml"
EPSG_FROM = "EPSG:6514"                   # NAD83(2011) / Montana (metres), the file's projection
EPSG_TO = "EPSG:4326"
UNAVAILABLE = "Montana's address list is unavailable"

# The file's table: 51 fields in order, name, type and length (the header is checked against this at every read).
DBF_SPEC = (
    ("DiscrpAgID", "C", 100), ("DateUpdate", "D", 8), ("Effective", "D", 8), ("Expire", "D", 8),
    ("NGUID", "C", 254), ("Country", "C", 2), ("State", "C", 2), ("County", "C", 100), ("Inc_Muni", "C", 100),
    ("Uninc_Comm", "C", 100), ("Nbrhd_Comm", "C", 100), ("AddNum_Pre", "C", 15), ("Add_Number", "N", 10),
    ("AddNum_Suf", "C", 15), ("St_PreMod", "C", 15), ("St_PreDir", "C", 10), ("St_PreTyp", "C", 50),
    ("St_PreSep", "C", 20), ("St_Name", "C", 254), ("St_PosTyp", "C", 50), ("St_PosDir", "C", 10),
    ("St_PosMod", "C", 25), ("LSt_PreDir", "C", 2), ("LSt_Name", "C", 75), ("LSt_Typ", "C", 4),
    ("LSt_PosDir", "C", 2), ("Post_Comm", "C", 40), ("Post_Code", "C", 7), ("PostCodeEx", "C", 4),
    ("Building", "C", 75), ("Floor", "C", 75), ("Unit", "C", 75), ("Room", "C", 75), ("Seat", "C", 75),
    ("Addtl_Loc", "C", 225), ("LandmkName", "C", 150), ("Milepost", "C", 150), ("Place_Type", "C", 50),
    ("Placement", "C", 25), ("Longitude", "N", 19), ("Latitude", "N", 19), ("Elevation", "N", 10),
    ("MT_PlcType", "N", 10), ("ParcelID", "C", 17), ("LocalID", "C", 38), ("Addtl_Desc", "C", 254),
    ("GNIS_ID", "C", 10), ("DatasetTyp", "C", 25), ("ProcessID", "N", 10), ("ProcessDte", "D", 8),
    ("GlobalID", "C", 38),
)
DBF_FIELD_NAMES = tuple(name for name, _kind, _length in DBF_SPEC)

# The reader slices these seventeen fields and no others (decision 6, D1 and D32). Each is an address part, a unit, a
# post office or county name, or the placement (how the point was placed, not what the place is).
ALLOWED_FIELDS = ("Add_Number", "AddNum_Pre", "AddNum_Suf", "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
                  "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod", "Post_Comm", "Post_Code", "Inc_Muni", "County",
                  "Unit", "Placement")
# Never sliced, stored or shown (owner decision 6; the B3 brief's D1 list).
FORBIDDEN_FIELDS = ("ParcelID", "LocalID", "NGUID", "GlobalID", "Place_Type", "MT_PlcType", "LandmkName",
                    "Addtl_Desc", "Addtl_Loc", "GNIS_ID", "Latitude", "Longitude", "DiscrpAgID")
_ALLOWED_SET = frozenset(ALLOWED_FIELDS)


def _field_offsets() -> tuple[dict, int]:
    position, offsets = 1, {}                   # byte 0 of a record is the deletion flag
    for name, _kind, length in DBF_SPEC:
        offsets[name] = (position, position + length)
        position += length
    return offsets, position


_OFFSETS, DBF_RECORD_BYTES = _field_offsets()
FIELD_SLICES = {name: _OFFSETS[name] for name in ALLOWED_FIELDS}   # the reader's slice table: [start, end)

# The three recorded projection pairs (D2): the line and city of the record, and the live map service's lon and
# lat for the same record (msdi_structures_addresses_map_v1, outSR=4326, queried 2026-10-19). The build finds each
# record by its line and city and must find it once.
PROJECTION_PAIRS = (
    {"name": "1611 South Avenue West, Missoula", "line": "1611 South Avenue West", "city": "Missoula",
     "live": (-114.02079563702587, 46.84868711344614)},
    {"name": "500 Colony Road, Roundup", "line": "500 Colony Road", "city": "Roundup",
     "live": (-108.5003197130036, 46.71751092724771)},
    {"name": "1617 Euclid Avenue Unit 4, Helena", "line": "1617 Euclid Avenue Unit 4", "city": "Helena",
     "live": (-112.05998229436645, 46.6037470105732)},
)

# Search normalisation (D6): the browser lower-cases the typed text, expands these and matches the file's words.
_DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west", "ne": "northeast", "nw": "northwest",
               "se": "southeast", "sw": "southwest"}
_STREET_TYPES = {"st": "street", "ave": "avenue", "rd": "road", "dr": "drive", "ln": "lane", "ct": "court",
                 "trl": "trail", "blvd": "boulevard", "cir": "circle", "pl": "place", "hwy": "highway",
                 "pkwy": "parkway", "ter": "terrace", "sq": "square", "lp": "loop", "way": "way"}
_OTHER_WORDS = {"us": "united states", "mt": "montana", "#": "unit"}

# Every sentence the addresses layer shows (Python fills the braces; map.js fills them in the browser).
# The three metadata sentences are quoted exactly (D8); the exclusion sentence is quoted exactly too.
ACCCONST_TEXT = "None. All data contained in the Framework are publicly available and non-sensitive."
USE_DISCLAIMER_TEXT = ("DISCLAIMER: The Montana State Library Geographic Information Services provides this "
                       "product/service for informational purposes only. The Library did not produce it for, nor is "
                       "it suitable for legal, engineering, or surveying purposes.")
USE_CONVENIENCE_TEXT = ("The Library makes these data and services available as a convenience to the public, and for "
                        "no other purpose.")
PURPOSE_TEXT = ("To provide a statewide, standardized repository for structure and address point data. The "
                "Structures/Addresses Framework complies with the NENA Standard for NG9-1-1 GIS Data Model and is "
                "designed to support a wide range of public and private sector uses including: 9-1-1 and emergency "
                "response, elections management, broadband internet mapping, census programs, planning, natural "
                "resource studies, etc.")
EXCLUSION_TEXT = "Owner names and parcel identifiers are never read, stored or shown."

WORDS_ADDRESSES = {
    "title": "Find an address",
    "search_hint": "Type a street address and a town",
    "search_none": "No match in Montana's address list; try the street name alone",
    "search_capped": "Showing the first 20 matches. Type more of the address to narrow the list.",
    "privacy": "What you type stays in your browser.",
    "legend": "Dots are addresses from Montana's public address list; tap one for its history",
    "address_line": "{line}, {city} {zip}",
    "address_line_no_zip": "{line}, {city}",
    "same_point": "{n} addresses at this point",
    # D41: every unavailable line ends with the required sentence (the history's unavailable lines do the same)
    "unavailable": ("Montana's address list could not be loaded in this update; that is not the same as no "
                    "addresses. This is not an all-clear."),
    "sample": "SAMPLE data",
    "about_title": "Addresses",
    "about_source": ("Source: Montana State Library Structures and Addresses Framework, file dated {pubdate}, "
                     "exported {export_date}."),
    "about_source_undated": ("Source: Montana State Library Structures and Addresses Framework (file date not "
                             "available in this update)."),
    "about_access": "Access terms in the file's metadata: " + ACCCONST_TEXT,
    "about_use": ("Use terms in the file's metadata: " + USE_DISCLAIMER_TEXT + " [...] " + USE_CONVENIENCE_TEXT),
    "about_purpose": "The file's stated purpose: " + PURPOSE_TEXT,
    "about_exclusion": EXCLUSION_TEXT,
    "about_fields": ("The site reads only an address's number, street, unit, city, zip, county and placement from the "
                     "file, and draws each address as a dot with its address line."),
    "about_persons": ("This site publishes no list of persons. Montana Code Annotated 2-6-1017 concerns lists of "
                      "persons."),
    "about_coverage": "The list is of addresses, not of buildings, and its completeness varies from county to county.",
    "about_privacy": "What you type stays in your browser.",
    # D23: an address tile with no B1 shard is outside the hail grid; the dot says so and never says "no hail".
    "outside_grid": "This point is outside the hail grid's Montana outline; the history does not cover it.",
    # D32: a point that is not a Structure point says how it was placed ({how} is in PLACEMENT_HOW).
    "placed": "This address point was placed {how}, not on the building.",
    # D29 and D34: the building outline words for a building-outline dot (the site's templates fill the braces).
    "outline_legend": ("Each dot is one building outline. Tap a dot for its address, if one is on file, and the weather "
                       "history for its cell."),
    "outline_no_address": ("No address on file for this building. The weather history below is for this building's "
                           "cell."),
    "outline_units": "Units on file: {n}.",
    "outline_caveat": ("Outlines come from imagery dated 2008 to 2025 and are not surveys; sheds and barns are outlines "
                       "too."),
}

Row = namedtuple("Row", "lon5 lat5 line city zip number street unit add key cls county")   # cls: placement letter
_LETTERS = re.compile(r"[A-Za-z]{1,2}")
TILE_NAME_LEN = len(hail.tile_name(0, 0))


class AddressesError(Exception):
    """A list or file that cannot be used. The message is plain words, starting with what is unavailable, with no
    full stop (the state line in index.json shows it)."""


class SourceUnavailable(AddressesError):
    """The source did not answer, or the file is not the one the reader expects: a failed HEAD, download or size check,
    a file that will not decode, a changed field list, header, projection, placement value or terms sentence, or a
    record count that does not add up (D20, D36). The list is marked unavailable with the reason, the rest of the
    store is kept and the job goes on (exit 0). Any other AddressesError stops the build with exit 1."""


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


def _compact(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".addr-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- the reader (D1)

def _text(raw: bytes) -> str:
    """A field's text: UTF-8 with the stray bytes and no-break spaces the file holds turned into spaces, runs of
    spaces collapsed, and the ends stripped."""
    text = raw.decode("utf-8", errors="replace").replace("�", " ").replace(" ", " ")
    return " ".join(text.split())


def _slice(record: bytes, name: str) -> str:
    """The text of one allow-listed field of a DBF record. Any other name is refused before a byte is read."""
    if name not in _ALLOWED_SET:
        raise AddressesError(f"the reader is not allowed to read the field {name}")
    start, end = FIELD_SLICES[name]
    return _text(record[start:end])


class _Framework:
    """The validated members of one framework zip: the point positions (EPSG:6514, in file order) and the table's
    record count and lengths. The table itself is streamed by _records()."""

    def __init__(self, nrec, hlen, rlen, xs, ys, kinds):
        self.nrec, self.hlen, self.rlen = nrec, hlen, rlen
        self.xs, self.ys, self.kinds = xs, ys, kinds


def _unavailable(reason: str) -> SourceUnavailable:
    """The error for a source that is not the file this build reads (D36): the list is marked unavailable with it."""
    return SourceUnavailable(f"{UNAVAILABLE}: {reason}")


def _read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        raise _unavailable(f"the file has no {name} member") from None


def _check_dbf_header(head: bytes) -> tuple[int, int, int]:
    if len(head) < 32:
        raise _unavailable("the table header is short")
    nrec, hlen, rlen = struct.unpack_from("<IHH", head, 4)
    fields, pos = [], 32
    while head[pos:pos + 1] != b"\r":
        if len(head) < pos + 32:
            raise _unavailable("the table header is short")
        desc = head[pos:pos + 32]
        fields.append((desc[:11].split(b"\x00", 1)[0].decode("ascii", errors="replace"),
                       chr(desc[11]), desc[16]))
        pos += 32
    if [tuple(f) for f in fields] != [tuple(s) for s in DBF_SPEC]:
        raise _unavailable(
            "the table's field list (names, types and lengths) is not the 51 fields this build reads")
    if hlen != pos + 1 or rlen != DBF_RECORD_BYTES:
        raise _unavailable("the table's header or record length is not the one this build reads")
    return nrec, hlen, rlen


def _read_points(shp: bytes, shx: bytes) -> tuple[array.array, array.array, bytearray]:
    if len(shp) < 100 or struct.unpack_from(">i", shp, 0)[0] != 9994:
        raise _unavailable("the point file is not a shapefile")
    file_words = struct.unpack_from(">i", shp, 24)[0]
    version, shape_type = struct.unpack_from("<ii", shp, 28)
    if file_words * 2 != len(shp) or version != 1000 or shape_type != 1:
        raise _unavailable("the point file is not a version 1000 file of point records")
    xs, ys, kinds = array.array("d"), array.array("d"), bytearray()
    pos, number, end = 100, 0, len(shp)
    while pos < end:
        if pos + 8 > end:
            raise _unavailable("the point file ends inside a record")
        rec_no, words = struct.unpack_from(">ii", shp, pos)
        pos += 8
        size = words * 2
        if pos + size > end or size < 4:
            raise _unavailable("the point file ends inside a record")
        number += 1
        if rec_no != number:
            raise _unavailable("the point records are out of order")
        content_type = struct.unpack_from("<i", shp, pos)[0]
        if content_type == 0:
            kinds.append(0)
            xs.append(0.0)
            ys.append(0.0)
        elif content_type == 1 and size == 20:
            x, y = struct.unpack_from("<dd", shp, pos + 4)
            if not (math.isfinite(x) and math.isfinite(y)):
                raise _unavailable("a point position is not a number")
            kinds.append(1)
            xs.append(x)
            ys.append(y)
        else:
            raise _unavailable("the file holds shapes other than points")
        pos += size
    if len(shx) < 100 or (len(shx) - 100) // 8 != number:
        raise _unavailable("the index file does not list the same number of points")
    return xs, ys, kinds


def _open_framework(zip_path) -> _Framework:
    """Validate the zip's members, projection, table header and point file, and load the positions. Raises
    AddressesError with the plain reason when the file is not the one this build reads."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile):
        raise _unavailable("the framework file is not a zip file") from None
    with zf:
        prj = _read_member(zf, PRJ_MEMBER).decode("ascii", errors="replace")
        if PRJ_NAME not in prj:
            raise _unavailable(f"the file's projection is not {PRJ_NAME}")
        xs, ys, kinds = _read_points(_read_member(zf, SHP_NAME), _read_member(zf, SHX_NAME))
        with zf.open(DBF_NAME) as stream:
            head = _read_exact(stream, 32)
            if len(head) < 32:
                raise _unavailable("the table header is short")
            hlen = struct.unpack_from("<H", head, 8)[0]
            if hlen < 33 or hlen > 32 * 256:
                raise _unavailable("the table header length is not one this build reads")
            nrec, hlen, rlen = _check_dbf_header(head + _read_exact(stream, hlen - 32))
        if nrec != len(kinds):
            raise _unavailable("the table and the point file do not hold the same number of records")
    return _Framework(nrec, hlen, rlen, xs, ys, kinds)


def _read_exact(stream, count: int) -> bytes:
    out = bytearray()
    while len(out) < count:
        chunk = stream.read(count - len(out))
        if not chunk:
            break
        out.extend(chunk)
    return bytes(out)


def _records(zip_path, fw: _Framework):
    """Yield (x, y, fields) for each table record in file order: x and y are None for a null shape, and fields is
    None for a deleted record. fields holds the allow-listed fields only."""
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(DBF_NAME) as stream:
            header = _read_exact(stream, fw.hlen)
            if len(header) != fw.hlen:
                raise _unavailable("the table ends inside its header")
            rlen, left, i = fw.rlen, fw.nrec, 0
            while left > 0:
                take = min(left, 4096)
                chunk = _read_exact(stream, rlen * take)
                if len(chunk) != rlen * take:
                    raise _unavailable("the table ends before its last record")
                for k in range(0, len(chunk), rlen):
                    record = chunk[k:k + rlen]
                    x = fw.xs[i] if fw.kinds[i] == 1 else None
                    y = fw.ys[i] if fw.kinds[i] == 1 else None
                    if record[0:1] == b"*":
                        yield x, y, None
                    else:
                        yield x, y, {name: _slice(record, name) for name in ALLOWED_FIELDS}
                    i += 1
                left -= take


def read_points(zip_path):
    """Validate the framework zip (raises AddressesError, "unavailable", when it is not the file this build reads)
    and return an iterator of (x, y, fields) for every record: x and y in EPSG:6514 metres (None for a null shape),
    fields the allow-listed values (None for a deleted record)."""
    fw = _open_framework(zip_path)
    return _records(zip_path, fw)


def source_facts(zip_path) -> dict:
    """The file's facts from its own members: the export date (_ReadMe.txt) and the metadata's pubdate, accconst,
    useconst and purpose, quoted with their whitespace collapsed (D8)."""
    path = Path(zip_path)
    with zipfile.ZipFile(path) as zf:
        readme = _read_member(zf, README_NAME).decode("utf-8", errors="replace")
        meta_bytes = _read_member(zf, META_NAME)
    match = re.search(r"exported[^.]*?\bon\s+(\d{4})(\d{2})(\d{2})", readme, re.S)
    if not match:
        raise _unavailable("the file's README gives no export date")
    export_date = "-".join(match.groups())
    try:
        root = ET.fromstring(meta_bytes)
    except ET.ParseError:
        raise _unavailable("the file's metadata is not readable XML") from None

    def first(tag: str) -> str:
        for element in root.iter(tag):
            return " ".join((element.text or "").split())
        raise _unavailable(f"the file's metadata has no {tag}")

    pub = first("pubdate")
    pubdate = f"{pub[0:4]}-{pub[4:6]}-{pub[6:8]}" if re.fullmatch(r"\d{8}", pub) else pub
    return {
        "name": "Montana State Library Structures and Addresses Framework",
        "url": MSL_URL,
        "file": path.name,
        "bytes": path.stat().st_size,
        "export_date": export_date,
        "pubdate": pubdate,
        "accconst": first("accconst"),
        "useconst": first("useconst"),
        "purpose": first("purpose"),
        "projection": PRJ_NAME,
        "dbf_fields": len(DBF_SPEC),
        "fields_read": list(ALLOWED_FIELDS),
    }


# ---------------------------------------------------------------- projection (D2)

_TRANSFORMER = {}


def _transformer():
    if "t" not in _TRANSFORMER:
        try:
            from pyproj import Transformer      # lazy: the job installs pyproj (D19); the site build never needs it
        except ImportError:
            raise _unavailable("the projection library is not installed") from None
        _TRANSFORMER["t"] = Transformer.from_crs(EPSG_FROM, EPSG_TO, always_xy=True)
    return _TRANSFORMER["t"]


def to_lonlat(x: float, y: float) -> tuple[float, float]:
    """(lon, lat) in degrees for a position in the file's metres (EPSG:6514 to EPSG:4326, always_xy). Not rounded."""
    lon, lat = _transformer().transform(float(x), float(y))
    return float(lon), float(lat)


def pyproj_version() -> str:
    import pyproj
    return pyproj.__version__


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- the address line, city and zip (D3, D4)

def number_text(prefix: str, number: int, suffix: str) -> str:
    """The number part of a line: "401", "M5" (a one-or-two-letter prefix or suffix joins without a space), "401 1/2"
    (anything else is set off with a space). Blank when the number is 0 or blank."""
    if number <= 0:
        return ""
    text = str(number)
    if prefix:
        text = prefix + ("" if _LETTERS.fullmatch(prefix) else " ") + text
    if suffix:
        text = text + ("" if _LETTERS.fullmatch(suffix) else " ") + suffix
    return text


def _title_word(word: str) -> str:
    """A word title-cased: its letters capitalised and its digits, if any, kept ("APT2" is "Apt2", "A1" is "A1")."""
    match = re.fullmatch(r"([A-Za-z]+)(\d*)", word)
    return match.group(1).capitalize() + match.group(2) if match else word


def unit_text(unit: str) -> str:
    """The unit as written, title-cased ("UNIT A" -> "Unit A", "APT 1" -> "Apt 1", "APT2" -> "Apt2", "RM403" ->
    "Rm403"). A unit whose first word is two or more letters (then digits, if any) keeps no prefix; any other unit gets
    "Unit " in front ("A" -> "Unit A", "A1" -> "Unit A1", "#3" -> "Unit #3")."""
    words = unit.split()
    if not words:
        return ""
    shown = " ".join(_title_word(word) for word in words)
    if re.fullmatch(r"[A-Za-z]{2,}\d*", words[0]):
        return shown
    return "Unit " + shown


def street_text(parts: dict) -> str:
    """The street words in NENA order, single spaces, blanks skipped."""
    order = ("St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod")
    return " ".join(parts[name] for name in order if parts[name])


def city_raw(post_comm: str, inc_muni: str, county: str) -> str:
    if post_comm:
        return post_comm
    if inc_muni and inc_muni.lower() != "unincorporated":
        return inc_muni
    return county


def zip_text(post_code: str) -> str:
    return post_code if re.fullmatch(r"\d{5}", post_code) else ""


def placement_class(value: str) -> str:
    """The one-letter placement class of a row (D32): S, P, G, L, T or U. A blank value is U (a method the file does not
    state). Any other value is not one this build reads, so the list is unavailable (D36)."""
    if value not in PLACEMENT_CLASS:
        raise _unavailable(f"the file's placement value {value!r} is not one this build reads")
    return PLACEMENT_CLASS[value]


def placement_counts(keep: list) -> dict:
    """The placement classes of the kept records (before the merge), statewide and per county (D32). The counts add up to
    the kept records, and a blank value is counted as Unknown (blank_as_unknown)."""
    classes: Counter = Counter()
    by_county: dict[str, Counter] = defaultdict(Counter)
    for fields in keep:
        cls = placement_class(fields["Placement"])
        classes[cls] += 1
        by_county[fields["County"] or "(blank)"][cls] += 1
    return {"classes": {letter: classes.get(letter, 0) for letter in CLASS_LETTERS},
            "blank_as_unknown": sum(1 for fields in keep if not fields["Placement"]),
            "by_county": {county: {letter: counts.get(letter, 0) for letter in CLASS_LETTERS}
                          for county, counts in sorted(by_county.items())}}


def add_value(number: str) -> int:
    match = re.match(r"\d+", number)
    return int(match.group()) if match else 0


def city_key(name: str) -> str:
    """The grouping key of a city name: letters and digits only, in lower case ("St. Ignatius" and "St Ignatius")."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def canonical_cities(names) -> dict:
    """One display spelling per city, whatever the capitals or punctuation: the mixed-case spelling the file uses most
    (else each word capitalised when the file writes the name only in capitals). Pass the list of every row's city, not
    a set: each use of a spelling counts (D22)."""
    groups: dict[str, Counter] = defaultdict(Counter)
    for name in names:
        groups[city_key(name)][name] += 1
    out = {}
    for spellings in groups.values():
        mixed = [(count, name) for name, count in spellings.items() if name != name.upper()]
        if mixed:
            best = max(mixed)[1]
        else:
            best = " ".join(word.capitalize() for word in max(spellings, key=lambda n: (spellings[n], n)).split(" "))
        for name in spellings:
            out[name] = best
    return out


def _first_char(street_name: str) -> str:
    return street_name[:1].upper()


def _two_chars(street_name: str) -> str:
    return (street_name[:2] if len(street_name) >= 2 else street_name[:1] + " ").upper()


def key_plan(pairs) -> set:
    """The (city, first character) pairs whose one-character file would hold more than 2,500 rows (D5): these are
    keyed by two characters instead."""
    counts = Counter((city, _first_char(name)) for city, name in pairs)
    return {pair for pair, n in counts.items() if n > ROWS_LIMIT}


def city_keys(pairs) -> dict:
    """{city: {key: rows}} for (city, St_Name) pairs: the key is the first character of St_Name upper-cased (digits
    stay digits), or two characters where key_plan() splits it."""
    pairs = list(pairs)
    split = key_plan(pairs)
    out: dict[str, dict[str, int]] = {}
    for city, name in pairs:
        key = _two_chars(name) if (city, _first_char(name)) in split else _first_char(name)
        bucket = out.setdefault(city, {})
        bucket[key] = bucket.get(key, 0) + 1
    return {city: dict(sorted(keys.items())) for city, keys in sorted(out.items())}


def slug(name: str) -> str:
    """The folder name of a city: lower-case ASCII words joined with dashes ("St. Ignatius" -> "st-ignatius")."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "city"


def file_key(key: str) -> str:
    """The file name of a letter key: letters and digits as they are, any other character as _ and its four hex
    digits (so "#" is _0023 and a space is _0020). The browser applies the same rule."""
    return "".join(ch if (ch.isascii() and ch.isalnum()) else f"_{ord(ch):04x}" for ch in key)


def search_words() -> dict:
    """The abbreviations the search expands to the file's spelled-out words (D6), lower-cased."""
    return {**_DIRECTIONS, **_STREET_TYPES, **_OTHER_WORDS}


# ---------------------------------------------------------------- tiles and the quadtree (D5)

def tile_of(lat5: int, lon5: int) -> tuple[int, int]:
    """The B1 tile of a position given in 1e-5 degree units, by the grid's rule: row = floor(5500 - 100 lat),
    col = floor(100 lon + 13000), then // 10 (hail.cell_for gives the same cell; the tests compare them)."""
    row = (5500000 - lat5) // 1000
    col = (lon5 + 13000000) // 1000
    return row // hail.TILE, col // hail.TILE


def tile_box(tile_row: int, tile_col: int) -> tuple[int, int, int, int]:
    """(west, south, east, north) of a B1 tile in sub-units (SUB per 1e-5 degree), from the same integer rule as tile_of:
    the north edge is row 10 * tile_row of the grid, the west edge is column 10 * tile_col. A tile holds the points with
    west <= lon < east and south < lat <= north (the grid's rule: a point on an edge goes south or east)."""
    north5 = 5500000 - tile_row * 10000
    west5 = -13000000 + tile_col * 10000
    return west5 * SUB, (north5 - 10000) * SUB, (west5 + 10000) * SUB, north5 * SUB


def quarter(bounds, lon: int, lat: int) -> str:
    """The quarter digit of a point in a box (0 NW, 1 NE, 2 SW, 3 SE). The middle lines are compared in whole sub-units:
    the point goes east when 2 * lon >= west + east, and north when 2 * lat > south + north (the grid's half-open rule,
    longitude [west, east) and latitude (south, north]). Exact for every box the quadtree makes (B3R-07)."""
    west, south, east, north = bounds
    east_half = 2 * lon >= west + east
    if 2 * lat > south + north:
        return "1" if east_half else "0"
    return "3" if east_half else "2"


def quadtree(name: str, bounds, points, depth: int = 0) -> list:
    """Split a tile into quarters while a shard would hold more than 2,500 points, to the depth cap. bounds are
    (west, south, east, north) and each point is (lon, lat, payload), all whole numbers of sub-units (SUB per 1e-5
    degree), so the halving is exact (every edge down to the depth cap is whole). Returns [(leaf name, leaf bounds,
    leaf points)] for the leaves that hold points. The quarter of a point is quarter(), so a point on a middle line
    files in one quarter, the same one every time."""
    if len(points) <= ROWS_LIMIT or depth >= DEPTH_CAP:
        return [(name, tuple(bounds), points)]
    west, south, east, north = bounds
    if (west + east) % 2 or (south + north) % 2:
        raise AssertionError(f"the box {name} has a middle line that is not a whole sub-unit")
    mid_lon, mid_lat = (west + east) // 2, (south + north) // 2
    boxes = {"0": (west, mid_lat, mid_lon, north), "1": (mid_lon, mid_lat, east, north),
             "2": (west, south, mid_lon, mid_lat), "3": (mid_lon, south, east, mid_lat)}
    parts: dict[str, list] = {digit: [] for digit in boxes}
    for point in points:
        parts[quarter(bounds, point[0], point[1])].append(point)
    out = []
    for digit in "0123":
        if parts[digit]:
            out.extend(quadtree(name + digit, boxes[digit], parts[digit], depth + 1))
    return out


def _out_floor(value: int) -> float:
    """A west or south edge in sub-units, rounded outwards (down) to whole 1e-5 degrees, as a float."""
    return (value // SUB) / SCALE


def _out_ceil(value: int) -> float:
    """An east or north edge in sub-units, rounded outwards (up) to whole 1e-5 degrees, as a float."""
    return (-((-value) // SUB)) / SCALE


# ---------------------------------------------------------------- building the rows

def _collect(zip_path, fw: _Framework, counts: Counter) -> tuple[list, array.array, array.array]:
    """Stream the table and keep the rows that have a position, a street and a city. Counts the rest. A record with
    no city is counted, not a list failure (D20)."""
    keep, xs, ys = [], array.array("d"), array.array("d")
    for x, y, fields in _records(zip_path, fw):
        if fields is None:
            counts["left_out_deleted"] += 1
            continue
        if x is None:
            counts["left_out_no_position"] += 1
            continue
        if not fields["St_Name"]:
            counts["left_out_no_street"] += 1
            continue
        if not city_raw(fields["Post_Comm"], fields["Inc_Muni"], fields["County"]):
            counts["left_out_no_city"] += 1
            continue
        xs.append(x)
        ys.append(y)
        keep.append(fields)
    return keep, xs, ys


def _project(xs: array.array, ys: array.array) -> tuple[list, list]:
    transformer = _transformer()
    lons, lats = [], []
    for start in range(0, len(xs), 100000):
        lo, la = transformer.transform(xs[start:start + 100000].tolist(), ys[start:start + 100000].tolist())
        lons.extend(lo)
        lats.extend(la)
    if not all(math.isfinite(v) for v in lons) or not all(math.isfinite(v) for v in lats):
        raise _unavailable("a position does not project to a longitude and latitude")
    return lons, lats


def _make_rows(keep: list, lons: list, lats: list, pair_lines: dict) -> tuple[list, dict]:
    """The row for each kept record (before the merge), with its city resolved and its key planned. pair_lines maps
    (line, city) to the record index for the projection pairs; those records are returned with their positions."""
    raw_cities = []
    parts = []
    for fields in keep:
        raw_cities.append(city_raw(fields["Post_Comm"], fields["Inc_Muni"], fields["County"]))
        number = fields["Add_Number"]
        num = int(number) if number.isdigit() else 0
        street = street_text({name: fields[name] for name in ("St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
                                                                "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod")})
        parts.append((num, fields["AddNum_Pre"], fields["AddNum_Suf"], street, fields["St_Name"],
                      unit_text(fields["Unit"]), zip_text(fields["Post_Code"]), placement_class(fields["Placement"]),
                      fields["County"]))
    names = canonical_cities(raw_cities)                  # every row counts, so the most-used spelling wins (D22)
    cities = [names[raw] for raw in raw_cities]
    split = key_plan((city, part[4]) for city, part in zip(cities, parts))
    rows, found = [], {}
    for index, (city, part) in enumerate(zip(cities, parts)):
        num, pre, suf, street, st_name, unit, zip_code, cls, county = part
        number = number_text(pre, num, suf)
        line = " ".join(text for text in (number, street, unit) if text)
        key = _two_chars(st_name) if (city, _first_char(st_name)) in split else _first_char(st_name)
        rows.append(Row(round(lons[index] * SCALE), round(lats[index] * SCALE), line, city, zip_code, number,
                        street, unit, num, key, cls, county))
        if (line, city) in pair_lines:
            found.setdefault((line, city), []).append(index)
    return rows, found


def _ident(row) -> tuple:
    """The identity of a merged row: its position, line, city and zip (D22)."""
    return (row.lon5, row.lat5, row.line, row.city, row.zip)


def _merge_report() -> dict:
    """An empty merge report (D39): the merged groups and their merged rows, the groups that hold two or more placement
    classes (counted by their class pair), the groups with a Structure row and the groups that keep it."""
    return {"groups": 0, "merged_rows": 0, "two_classes": 0, "classes": {}, "with_structure": 0, "structure_kept": 0}


def _count_group(report: dict, group: list) -> None:
    """Count one merged group (two or more rows with one identity) into the report. group is in MERGE_PREFERENCE order,
    so group[0] is the row the merge keeps (D39)."""
    report["groups"] += 1
    report["merged_rows"] += len(group) - 1
    classes = {row.cls for row in group}
    if len(classes) > 1:
        report["two_classes"] += 1
        pair = "+".join(letter for letter in CLASS_LETTERS if letter in classes)
        report["classes"][pair] = report["classes"].get(pair, 0) + 1
    if "S" in classes:
        report["with_structure"] += 1
        if group[0].cls == "S":
            report["structure_kept"] += 1


def _dedupe(rows: list) -> tuple[list, dict]:
    """The merged rows (D22) and the merge report (D39). One row per position, line, city and zip: the kept row is the
    one with the earliest class in MERGE_PREFERENCE, so a Structure point is kept over every other class at its spot
    (a Structure point before a Parcel point, and so on) and the dot sits on the building."""
    rows.sort(key=lambda r: (r.lon5, r.lat5, r.line, r.city, r.zip, MERGE_PREFERENCE.index(r.cls)))
    out, report = [], _merge_report()
    start = 0
    while start < len(rows):
        end = start + 1
        while end < len(rows) and _ident(rows[end]) == _ident(rows[start]):
            end += 1
        out.append(rows[start])
        if end - start > 1:
            _count_group(report, rows[start:end])
        start = end
    report["classes"] = dict(sorted(report["classes"].items()))
    return out, report


def _merge_report_ok(report, merged_rows: int) -> bool:
    """Whether a recorded merge report agrees with itself and with the index's merged rows (D39): the merged rows
    are the same, the two-class groups are the class pairs it counts, every group with a Structure row keeps it, and
    no count is more than the groups."""
    if not isinstance(report, dict) or set(report) != set(_merge_report()) or not isinstance(report["classes"], dict):
        return False
    try:
        return (report["merged_rows"] == merged_rows
                and report["two_classes"] == sum(report["classes"].values())
                and report["two_classes"] <= report["groups"] <= merged_rows
                and report["structure_kept"] == report["with_structure"] <= report["groups"])
    except TypeError:
        return False


def _merge_text(report: dict) -> str:
    """The merge report in words, for verify's detail: the two-class groups and the Structure rows kept (D39)."""
    return (f"{report['two_classes']:,} two-class groups of {report['groups']:,} merged groups; "
            f"{report['structure_kept']:,} of the {report['with_structure']:,} groups with a Structure row keep it")


def _write_tree(root: Path, rows: list) -> dict:
    """Write hail/a/ under root from the merged rows (sorted by position, line, city, zip). The tree is staged in
    a folder of this module's own and moved into place; the old a/ tree is replaced. Returns the measures."""
    hail_dir = root / "hail"
    stage = hail_dir / ".a-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        measures = _write_stage(stage, rows)
        target = hail_dir / "a"
        if target.exists():
            shutil.rmtree(target)
        os.replace(stage, target)
        return measures
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _write_stage(stage: Path, rows: list) -> dict:
    by_tile: dict[tuple[int, int], list] = defaultdict(list)
    for row in rows:
        by_tile[tile_of(row.lat5, row.lon5)].append(row)
    shard_names = []
    shard_bytes = {}
    split = {}
    depths = Counter()
    tiles = []
    for tile_row, tile_col in sorted(by_tile):
        tile = hail.tile_name(tile_row, tile_col)
        tiles.append(tile)
        points = [(row.lon5 * SUB, row.lat5 * SUB, row) for row in by_tile[(tile_row, tile_col)]]
        leaves = quadtree(tile, tile_box(tile_row, tile_col), points)
        if len(leaves) > 1:
            split[tile] = sorted(name for name, _b, _p in leaves)
        for name, bounds, leaf_points in leaves:
            leaf_rows = [point[2] for point in leaf_points]
            west, south, east, north = bounds
            doc = {"f": FORMAT,
                   "b": [_out_floor(west), _out_floor(south), _out_ceil(east), _out_ceil(north)],
                   "n": len(leaf_rows),
                   "a": [[row.lon5 / SCALE, row.lat5 / SCALE, row.line, row.city, row.zip, row.cls]
                         for row in leaf_rows]}
            data = _compact(doc)
            (stage / f"{name}.json").write_bytes(data)
            shard_names.append(name)
            shard_bytes[name] = (len(data), len(leaf_rows))
            depths[len(name) - len(tile)] += 1
    idx = stage / "idx"
    idx.mkdir()
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        groups[(row.city, row.key)].append(row)
    cities: dict[str, dict] = {}
    for city, key in groups:
        cities.setdefault(city, {"n": 0, "keys": {}})
    for (city, key), group in groups.items():
        cities[city]["n"] += len(group)
        cities[city]["keys"][key] = len(group)
    dirs = _city_dirs(sorted(cities))
    letter_bytes = {}
    for (city, key), group in sorted(groups.items()):
        group.sort(key=lambda r: (r.street.lower(), r.add, r.number, r.unit, r.lon5, r.lat5))
        doc = {"f": IDX_FORMAT,
               "a": [[row.number, row.street, row.unit, row.lon5 / SCALE, row.lat5 / SCALE, row.zip, row.cls]
                     for row in group]}
        data = _compact(doc)
        folder = idx / dirs[city]
        folder.mkdir(exist_ok=True)
        (folder / f"{file_key(key)}.json").write_bytes(data)
        letter_bytes[(city, key)] = (len(data), len(group), dirs[city], file_key(key))
    cities_doc = {"f": CITIES_FORMAT,
                  "cities": {}}
    for city in sorted(cities):
        entry = {"n": cities[city]["n"], "keys": dict(sorted(cities[city]["keys"].items()))}
        if dirs[city] != slug(city):
            entry["dir"] = dirs[city]
        cities_doc["cities"][city] = entry
    cities_bytes = _compact(cities_doc)
    (idx / "cities.json").write_bytes(cities_bytes)
    words_bytes = _compact({"f": WORDS_FORMAT, "words": search_words()})
    (idx / "words.json").write_bytes(words_bytes)
    largest_shard = max(shard_bytes.items(), key=lambda kv: (kv[1][0], kv[0])) if shard_bytes else None
    largest_letter = max(letter_bytes.items(), key=lambda kv: (kv[1][0], kv[0])) if letter_bytes else None
    return {
        "shards": len(shard_names),
        "shard_names": sorted(shard_names),
        "tiles": tiles,
        "split": split,
        "depths": {str(k): v for k, v in sorted(depths.items())},
        "shard_bytes": sum(size for size, _n in shard_bytes.values()),
        "largest_shard": ({"name": largest_shard[0], "bytes": largest_shard[1][0], "rows": largest_shard[1][1]}
                          if largest_shard else None),
        "cities": len(cities),
        "letter_files": len(letter_bytes),
        "letter_bytes": sum(size for size, _n, _d, _f in letter_bytes.values()),
        "largest_letter": ({"city": largest_letter[0][0], "key": largest_letter[0][1],
                            "rows": largest_letter[1][1], "bytes": largest_letter[1][0],
                            "file": f"hail/a/idx/{largest_letter[1][2]}/{largest_letter[1][3]}.json"}
                           if largest_letter else None),
        "cities_bytes": len(cities_bytes),
        "words_bytes": len(words_bytes),
        "two_character_files": sum(1 for (_c, k) in letter_bytes if len(k) == 2),
        "over_limit_letter_files": sorted(
            f"{c}/{k}" for (c, k), (_s, n, _d, _f) in letter_bytes.items() if n > ROWS_LIMIT),
        "over_limit_shards": sorted(name for name, (_s, n) in shard_bytes.items() if n > ROWS_LIMIT),
    }


def _city_dirs(names: list) -> dict:
    """The folder of each city: its slug, with -2, -3 ... added when two names share one (the first name keeps it)."""
    out, taken = {}, set()
    for name in sorted(names):
        base = slug(name)
        candidate, n = base, 1
        while candidate in taken:
            n += 1
            candidate = f"{base}-{n}"
        taken.add(candidate)
        out[name] = candidate
    return out


def _files_on_disk(root: Path) -> dict:
    """{store-relative path: (bytes, sha256)} for every file under hail/a/."""
    base = root / "hail" / "a"
    out = {}
    if base.is_dir():
        for path in sorted(base.rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                out[path.relative_to(root).as_posix()] = {"bytes": len(data), "sha256": _sha256(data)}
    return out


def _wire(root: Path, block: dict) -> None:
    """Write the addresses block into hail/index.json and the a/ entries and index hash into hail/manifest.json.
    The B1 and B2 blocks and counts are kept as they are."""
    index_path = root / "hail" / "index.json"
    manifest_path = root / "hail" / "manifest.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index[INDEX_KEY] = block
    index_bytes = _pretty(index)
    _write_atomic(index_path, index_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {rel: meta for rel, meta in manifest.get("files", {}).items()
             if not rel.startswith("hail/a/") and rel != "hail/index.json"}
    files.update(_files_on_disk(root))
    files["hail/index.json"] = {"bytes": len(index_bytes), "sha256": _sha256(index_bytes)}
    manifest["files"] = {key: files[key] for key in sorted(files)}
    _write_atomic(manifest_path, _pretty(manifest))


def _check_store(root: Path) -> None:
    if not (root / "hail" / "index.json").is_file() or not (root / "hail" / "manifest.json").is_file():
        raise AddressesError("the store has no hail index or manifest; build the hail store first")


def _clear_leftovers(root: Path) -> None:
    """Remove what an interrupted build left under hail/: its staging folder (hail/.a-stage) and the temp files of
    an interrupted write (hail/.addr-*). check_manifest refuses any file under hail/ that the manifest does not list,
    so none of them may stay (D36)."""
    hail_dir = root / "hail"
    for path in [hail_dir / ".a-stage", *sorted(hail_dir.glob(".addr-*"))]:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.is_symlink() or path.exists():
            path.unlink()


def _mark_unavailable(root: Path, reason: str, *, source: bool = False) -> None:
    """Remove any a/ tree and any leftover of an interrupted build, and write the unavailable state into the index and
    manifest, so the store never carries address files with a failed list. source is True for a SourceUnavailable
    (D20): the job goes on, and the sheet says the list is unavailable from its source."""
    target = root / "hail" / "a"
    if target.exists():
        shutil.rmtree(target)
    _clear_leftovers(root)
    block = {"format": FORMAT, "state": "unavailable", "reason": reason, "source_unavailable": source,
             "built_at": _utc_now(), "sample": False}
    _wire(root, block)


def _measures_block(root: Path, facts: dict, fw: _Framework, counts: Counter, rows: list, tree: dict,
                    pairs: list, built_at: str, sample: bool, extra: dict | None = None) -> dict:
    points = fw.nrec
    left_no_pos = counts["left_out_no_position"]
    left_no_street = counts["left_out_no_street"]
    left_no_city = counts["left_out_no_city"]
    left_deleted = counts["left_out_deleted"]
    merged = counts["merged_duplicates"]
    block = {
        "format": FORMAT,
        "state": "loaded",
        "sample": sample,
        "built_at": built_at,
        "source": dict(facts, sha256=extra.get("sha256") if extra else None,
                       last_modified=extra.get("last_modified") if extra else None),
        "points": points,
        "left_out_no_position": left_no_pos,
        "left_out_no_street": left_no_street,
        "left_out_no_city": left_no_city,
        "left_out_deleted": left_deleted,
        "merged_duplicates": merged,
        "rows": len(rows),
        "shards": tree["shards"],
        "tiles": tree["tiles"],
        "split": tree["split"],
        "depths": tree["depths"],
        "largest_shard": tree["largest_shard"],
        "cities": tree["cities"],
        "letter_files": tree["letter_files"],
        "largest_letter": tree["largest_letter"],
        "two_character_files": tree["two_character_files"],
        "over_limit_shards": tree["over_limit_shards"],
        "over_limit_letter_files": tree["over_limit_letter_files"],
        "bytes": {"shards": tree["shard_bytes"], "letters": tree["letter_bytes"],
                  "cities": tree["cities_bytes"], "words": tree["words_bytes"],
                  "idx": tree["letter_bytes"] + tree["cities_bytes"] + tree["words_bytes"],
                  "a": tree["shard_bytes"] + tree["letter_bytes"] + tree["cities_bytes"] + tree["words_bytes"]},
        "fields_read": list(ALLOWED_FIELDS),
        "projection": {"from": EPSG_FROM, "to": EPSG_TO, "always_xy": True, "decimals": 5},
        "pyproj": extra.get("pyproj") if extra else None,
        "projection_pairs": pairs,
        "limits": {"rows": ROWS_LIMIT, "depth_cap": DEPTH_CAP},
    }
    if extra and extra.get("sample_of"):
        block["sample_of"] = extra["sample_of"]
    return block


def _pairs_check(found: dict, lonlat_of) -> list:
    """The three recorded projection pairs (D2): each record found once, its position projected, the offset in
    metres. Raises AddressesError when a pair is missing, repeated or more than 2 m out."""
    out = []
    for pair in PROJECTION_PAIRS:
        indexes = found.get((pair["line"], pair["city"]), [])
        if len(indexes) != 1:
            raise _unavailable(
                f"the projection check record for {pair['name']} was found {len(indexes)} times, not once")
        lon, lat = lonlat_of(indexes[0])
        metres = haversine_m(lon, lat, pair["live"][0], pair["live"][1])
        if metres >= PROJECTION_TOLERANCE_M:
            raise _unavailable(
                f"the projection check for {pair['name']} is {metres:.2f} m from the live service")
        out.append({"name": pair["name"], "file": [round(lon, 5), round(lat, 5)],
                    "live": [round(pair["live"][0], 5), round(pair["live"][1], 5)], "metres": round(metres, 3)})
    return out


def _build(zip_path, root: Path, extra: dict) -> dict:
    started = time.time()
    facts = source_facts(zip_path)
    if not (ACCCONST_TEXT == facts["accconst"] and USE_DISCLAIMER_TEXT in facts["useconst"]
            and USE_CONVENIENCE_TEXT in facts["useconst"] and PURPOSE_TEXT == facts["purpose"]):
        raise _unavailable("the terms sentences in the file's metadata are not the ones the site quotes")
    _transformer()                      # the projection library is checked before the table is read (D36)
    fw = _open_framework(zip_path)
    counts: Counter = Counter()
    keep, xs, ys = _collect(zip_path, fw, counts)
    if len(keep) + counts["left_out_no_position"] + counts["left_out_no_street"] + counts["left_out_deleted"] \
            + counts["left_out_no_city"] != fw.nrec:
        raise _unavailable("the records do not add up to the table's count")
    placement = placement_counts(keep)          # every placement value is checked before anything is written (D32)
    lons, lats = _project(xs, ys)
    pair_lines = {(p["line"], p["city"]): True for p in PROJECTION_PAIRS}
    rows, found = _make_rows(keep, lons, lats, pair_lines)
    before = len(rows)
    rows, merge_report = _dedupe(rows)                  # D22 and D39
    counts["merged_duplicates"] = before - len(rows)
    _say(f"addresses: {fw.nrec:,d} points, {len(rows):,d} rows after the merge ({time.time() - started:.1f}s)")

    def lonlat_of(index: int) -> tuple[float, float]:
        return lons[index], lats[index]

    pairs = _pairs_check(found, lonlat_of)
    tree = _write_tree(root, rows)
    built_at = _utc_now()
    block = _measures_block(root, facts, fw, counts, rows, tree, pairs, built_at, sample=False,
                            extra=dict(extra, pyproj=pyproj_version()))
    block["placement"] = placement
    block["merged_groups"] = merge_report               # D39: the merge report, checked by verify
    block["build_seconds"] = round(time.time() - started, 1)
    _wire(root, block)
    return block


def _local_file(zip_path) -> tuple[Path, str]:
    """The framework file on this machine and its SHA-256 (D36). A path that is not there, is not a file, or cannot be
    read is a source failure: the list is unavailable with the plain reason, and the job goes on."""
    path = Path(zip_path)
    if not path.exists():
        raise _unavailable(f"the framework file {zip_path} is not there")
    if not path.is_file():
        raise _unavailable(f"the framework file {zip_path} is not a file")
    try:
        return path, _sha256_file(path)
    except OSError as exc:
        raise _unavailable(f"the framework file {zip_path} could not be read ({type(exc).__name__})") from None


def build(zip_path, store_dir, *, cache=None, url: str | None = None, ledger=None) -> dict:
    """Build the address shards and index files into store_dir (a store with hail/index.json and hail/manifest.json).
    zip_path is the framework zip (a download is made into cache when zip_path is None; see download()). Returns the
    addresses block written to hail/index.json. A source failure (D20, D36), which includes a wrong or unreadable zip
    path and a missing projection library, marks the list unavailable with its reason and raises SourceUnavailable
    (source_unavailable is True in the index). Any other failure marks the list unavailable with source_unavailable
    False and raises AddressesError. The command line exits 0 for a SourceUnavailable and 1 for any other failure."""
    root = Path(store_dir)
    _check_store(root)
    extra: dict = {}
    try:
        if zip_path is None:
            zip_path, info = download(cache or Path("address-cache"), url or MSL_URL, ledger=ledger)
            extra.update(info)
        path, digest = _local_file(zip_path)          # a wrong or unreadable path is a source failure (D36)
        extra.setdefault("sha256", digest)
        return _build(path, root, extra)
    except AddressesError as exc:
        text = str(exc)
        _mark_unavailable(root, text if text.startswith(UNAVAILABLE) else f"{UNAVAILABLE}: {text}",
                          source=isinstance(exc, SourceUnavailable))
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, struct.error, UnicodeError) as exc:
        # a source file that will not decode (a damaged download or table) is a source failure too (D36)
        reason = f"{UNAVAILABLE}: the framework file could not be decoded ({type(exc).__name__})"
        _mark_unavailable(root, reason, source=True)
        raise SourceUnavailable(reason) from exc


def mark_unavailable(store_dir, reason: str) -> dict:
    """The job's failure branch (D36): write the unavailable state, with the plain reason, into the store's index and
    manifest, and remove the address files and any leftover of an interrupted build. It is the state a source failure
    writes (source_unavailable is True), so verify passes it and the job goes on. A store with no index or manifest
    cannot take the block: AddressesError (exit 1)."""
    root = Path(store_dir)
    _check_store(root)
    text = " ".join(str(reason).split())
    if not text:
        raise AddressesError("give the reason the list is unavailable (--reason TEXT)")
    if not text.startswith(UNAVAILABLE):
        text = f"{UNAVAILABLE}: {text}"
    _mark_unavailable(root, text, source=True)
    return {"state": "unavailable", "reason": text}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- the download (cache by name, size and Last-Modified)

def download(cache_dir, url: str = MSL_URL, *, fetcher=None, ledger=None) -> tuple[Path, dict]:
    """Return (path to the framework zip, facts about the download). A HEAD request gives the size and the
    Last-Modified date; a cached copy is used when its name, size and Last-Modified match, and otherwise the file is
    fetched through the site's HTTP helper (its user agent). Each request writes one ledger line (JSON) when a ledger
    path is given. A failed request or a file of another size is an error with the plain reason."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    if fetcher is None:
        from . import sources
        fetcher = sources.Fetcher(timeout=120, attempts=3, pause=2.0)
    dest = cache / ZIP_NAME
    meta_path = cache / (ZIP_NAME + ".meta.json")

    def log(method, status, nbytes, state, error=None):
        if ledger is None:
            return
        ledger_path = Path(ledger)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        line = {"at": _utc_now(), "method": method, "url": url, "status": status, "bytes": nbytes,
                "cache": state, "error": error}
        with open(ledger_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")

    try:
        head = fetcher.s.head(url, allow_redirects=True, timeout=fetcher.timeout)
        status = head.status_code
        size = int(head.headers.get("Content-Length", "-1"))
        modified = head.headers.get("Last-Modified")
    except Exception as exc:          # the network: a failed HEAD is the source not answering (D20)
        log("HEAD", None, None, "failed", type(exc).__name__)
        raise _unavailable(f"the framework download's HEAD request failed ({type(exc).__name__})") from None
    log("HEAD", status, size if size >= 0 else None, "checked")
    if status != 200:
        raise _unavailable(f"the framework download answered HTTP {status}")
    info = {"last_modified": modified, "url": url}
    if dest.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        if meta.get("name") == ZIP_NAME and meta.get("bytes") == dest.stat().st_size and \
                (size < 0 or meta.get("size") == size) and meta.get("last_modified") == modified:
            log("CACHE", None, dest.stat().st_size, "hit")
            info["sha256"] = _sha256_file(dest)
            return dest, info
    try:
        response = fetcher.binary(url)
    except Exception as exc:          # a fetcher that raises instead of answering: the source did not answer (D36)
        log("GET", None, None, "failed", type(exc).__name__)
        raise _unavailable(f"the framework download failed ({type(exc).__name__})") from None
    data, error = response if isinstance(response, tuple) else (response, None)
    if data is None:
        log("GET", None, None, "failed", error)
        raise _unavailable(f"the framework download failed ({error or 'no data'})")
    if size >= 0 and len(data) != size:
        log("GET", 200, len(data), "failed", "size")
        raise _unavailable("the framework download is not the size the server gave")
    if data[:2] != b"PK":
        log("GET", 200, len(data), "failed", "not a zip")
        raise _unavailable("the framework download is not a zip file")
    _write_atomic(dest, data)
    digest = _sha256(data)
    _write_atomic(meta_path, _compact({"name": ZIP_NAME, "url": url, "bytes": len(data),
                                       "size": size if size >= 0 else None, "last_modified": modified,
                                       "sha256": digest, "fetched": _utc_now()}))
    log("GET", 200, len(data), "fetched")
    info["sha256"] = digest
    return dest, info


# ---------------------------------------------------------------- verify

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _matched_rows(root: Path) -> tuple[int, list]:
    """The matched rows the outline step wrote (D28): the sum of the whole-number "m" counts in hail/b/ (the buildings
    module writes one in every shard). A store with no hail/b/ has none, because the job verifies before the outline
    step. Returns (the sum, the problems found reading the files)."""
    total, problems = 0, []
    b_dir = root / "hail" / "b"
    for path in (sorted(b_dir.glob("*.json")) if b_dir.is_dir() else []):
        try:
            doc = _read_json(path)
        except (OSError, ValueError):
            problems.append(f"{path.name} is not JSON")
            continue
        count = doc.get("m") if isinstance(doc, dict) else None
        if not isinstance(count, int) or isinstance(count, bool):
            problems.append(f"{path.name} has no whole-number matched count")
            continue
        total += count
    return total, problems


# ---------------------------------------------------------------- the figures of hail/a in the block (D49)

FIGURES_CHECK = "the figures in the addresses block match the files on disk (D49)"
FIGURE_KEYS = ("shards", "tiles", "split", "depths", "largest_shard", "over_limit_shards", "cities", "letter_files",
               "largest_letter", "two_character_files", "over_limit_letter_files", "bytes")
BYTE_KEYS = ("shards", "letters", "cities", "words", "idx", "a")


def disk_figures(root) -> dict:
    """The figures of the addresses block that describe hail/a, read from the files on disk (D49). The shards are the
    top-level files of hail/a; the search index is hail/a/idx (cities.json, words.json and the letter files that
    cities.json names). The arithmetic is the one _write_stage uses, so a build writes these figures and verify
    compares them with the files. Raises OSError, ValueError, KeyError or TypeError when a file the store names is
    missing, is not JSON or does not have the expected shape."""
    a_dir = Path(root) / "hail" / "a"
    shards = {}                                        # name: (bytes, rows)
    for path in sorted(a_dir.glob("*.json")):
        data = path.read_bytes()
        shards[path.stem] = (len(data), len(json.loads(data)["a"]))
    idx = a_dir / "idx"
    cities_raw = (idx / "cities.json").read_bytes()
    cities = json.loads(cities_raw)["cities"]
    words_raw = (idx / "words.json").read_bytes()
    letters = []                                       # (city, key, bytes, rows, the file's path in the store)
    for city in sorted(cities):
        folder = cities[city].get("dir", slug(city))
        for key in sorted(cities[city]["keys"]):
            name = f"{file_key(key)}.json"
            data = (idx / folder / name).read_bytes()
            letters.append((city, key, len(data), len(json.loads(data)["a"]), f"hail/a/idx/{folder}/{name}"))
    by_tile: dict = defaultdict(list)
    for name in shards:
        by_tile[name[:TILE_NAME_LEN]].append(name)
    depths = Counter(len(name) - TILE_NAME_LEN for name in shards)
    shard_total = sum(size for size, _rows in shards.values())
    letter_total = sum(item[2] for item in letters)
    index_total = letter_total + len(cities_raw) + len(words_raw)
    largest = max(shards.items(), key=lambda kv: (kv[1][0], kv[0])) if shards else None
    largest_letter = max(letters, key=lambda item: (item[2], item[0], item[1])) if letters else None
    return {
        "shards": len(shards),
        "tiles": sorted(by_tile),
        "split": {tile: sorted(names) for tile, names in sorted(by_tile.items()) if len(names) > 1},
        "depths": {str(depth): count for depth, count in sorted(depths.items())},
        "largest_shard": ({"name": largest[0], "bytes": largest[1][0], "rows": largest[1][1]} if largest else None),
        "over_limit_shards": sorted(name for name, (_size, rows) in shards.items() if rows > ROWS_LIMIT),
        "cities": len(cities),
        "letter_files": len(letters),
        "largest_letter": ({"city": largest_letter[0], "key": largest_letter[1], "rows": largest_letter[3],
                            "bytes": largest_letter[2], "file": largest_letter[4]} if largest_letter else None),
        "two_character_files": sum(1 for item in letters if len(item[1]) == 2),
        "over_limit_letter_files": sorted(f"{item[0]}/{item[1]}" for item in letters if item[3] > ROWS_LIMIT),
        "bytes": {"shards": shard_total, "letters": letter_total, "cities": len(cities_raw),
                  "words": len(words_raw), "idx": index_total, "a": shard_total + index_total},
    }


def refresh_figures(root, block: dict) -> dict:
    """The block with its figures of hail/a set to the figures on disk (D49). The rest of the block is kept."""
    out = dict(block)
    out.update(disk_figures(root))
    return out


def figure_differences(block: dict, disk: dict) -> list:
    """Each figure of the block that is missing or differs from the figure on disk, in words with both values (D49).
    An empty list means the block describes the files."""
    out = []
    have = block.get("bytes") if isinstance(block.get("bytes"), dict) else {}
    for name in BYTE_KEYS:
        if name not in have:
            out.append(f"bytes.{name} is missing from the index")
        elif have[name] != disk["bytes"][name]:
            out.append(f"bytes.{name} is {_shown(have[name])} in the index and {_shown(disk['bytes'][name])} on disk")
    for key in FIGURE_KEYS:
        if key == "bytes":
            continue
        if key not in block:
            out.append(f"{key} is missing from the index")
        elif block[key] != disk[key]:
            out.append(f"{key} is {_shown(block[key])} in the index and {_shown(disk[key])} on disk")
    return out


def _shown(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return text if len(text) <= 120 else text[:117] + "..."


def verify(store_dir, zip_path=None) -> dict:
    """Check the addresses in a store: the manifest hashes, the counts (rows equal points minus the left-out and
    merged rows; after the outline step the unmatched rows in hail/a and the matched rows in hail/b add up to the rows,
    D28), every shard's format, bounds, count, class and size limit (except at the depth cap), the split map,
    the tiles with no hail grid shard (listed as detail, D23), the cities and letter files (their counts add up to the
    rows, the two-character files are split only where the limit requires it), 200 random rows found in their city's
    letter file, the words file, the allow-list, the placement classes per county (D32), the figures of hail/a in the
    block against the files (D49), and the projection pairs.
    With zip_path, the counts, the placement classes, the merges and the pairs are recomputed from the file. Returns
    {"ok", "checks", "counts"}; a failed check names its file."""
    root = Path(store_dir)
    checks: list[dict] = []
    counts: dict = {}

    def check(name: str, ok: bool, detail: str = "") -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def result() -> dict:
        return {"ok": all(c["ok"] for c in checks), "checks": checks, "counts": counts}

    try:
        hail.check_manifest(root)
        check("manifest hashes and counts", True)
    except hail.HailStoreError as exc:
        check("manifest hashes and counts", False, str(exc))
        return result()
    try:
        index = hail.load_index(root)
    except hail.HailStoreError as exc:
        check("hail index", False, str(exc))
        return result()
    block = index.get(INDEX_KEY)
    if not isinstance(block, dict):
        check("addresses block in the index", False, "hail/index.json has no addresses block")
        return result()
    if block.get("state") == "unavailable" and block.get("source_unavailable"):
        check("the list is unavailable from its source; the sheet says so", True, str(block.get("reason", "")))
        return result()
    if not check("addresses state", block.get("state") == "loaded",
                 f"state {block.get('state')}: {block.get('reason', '')}"):
        return result()
    rows = block["rows"]
    check("rows equal points minus the left-out and merged rows",
          rows == block["points"] - block["left_out_no_position"] - block["left_out_no_street"]
          - block["left_out_deleted"] - block["left_out_no_city"] - block["merged_duplicates"],
          f"{rows} rows, {block['points']} points")
    check("the allow-list holds no forbidden field and no owner, parcel or place-type field",
          not (set(ALLOWED_FIELDS) & set(FORBIDDEN_FIELDS)) and set(block["fields_read"]) == set(ALLOWED_FIELDS)
          and not any(re.search(r"(?i)owner|parcel|place_?type|nguid|global|local|landmark|addtl|gnis|latitude|longitude",
                                name) for name in ALLOWED_FIELDS),
          ", ".join(block["fields_read"]))
    check("the fields read are the allow-list", tuple(block["source"]["fields_read"]) == ALLOWED_FIELDS)
    pair_ok = all(p["metres"] < PROJECTION_TOLERANCE_M for p in block["projection_pairs"]) and \
        len(block["projection_pairs"]) == len(PROJECTION_PAIRS)
    check("the three projection pairs agree within 2 m", pair_ok,
          ", ".join(f"{p['name']}: {p['metres']} m" for p in block["projection_pairs"]))
    a_dir = root / "hail" / "a"
    shard_rows = []
    shard_count = 0
    depth_hist = Counter()
    names_seen = set()
    bad = []
    tiles = set(block["tiles"])
    for path in sorted(a_dir.glob("*.json")):
        shard_count += 1
        try:
            doc = _read_json(path)
        except (OSError, ValueError):
            bad.append(f"{path.name} is not JSON")
            continue
        name = path.stem
        names_seen.add(name)
        tile = name[:TILE_NAME_LEN]
        if doc.get("f") != FORMAT or tile not in tiles or not re.fullmatch(r"r\d{4}_c\d{4}\d*", name):
            bad.append(f"{path.name} has the wrong format or name")
            continue
        depth = len(name) - len(tile)
        depth_hist[depth] += 1
        west, south, east, north = doc["b"]
        if doc["n"] != len(doc["a"]) or (len(doc["a"]) > ROWS_LIMIT and depth < DEPTH_CAP):
            bad.append(f"{path.name} holds {len(doc['a'])} rows (the limit is {ROWS_LIMIT})")
        last = None
        for record in doc["a"]:
            if not (isinstance(record, list) and len(record) == 6 and isinstance(record[5], str)
                    and record[5] in CLASS_SET):
                bad.append(f"{path.name} has a row that is not six values ending in a placement class")
                break
            lon, lat, line, city, zip_code, _cls = record
            if not (isinstance(lon, float) and isinstance(lat, float)) or not (
                    west <= lon <= east and south <= lat <= north):
                bad.append(f"{path.name} has a position outside its bounds")
                break
            if round(lon * SCALE) / SCALE != lon or round(lat * SCALE) / SCALE != lat:
                bad.append(f"{path.name} has a position with more than 5 decimals")
                break
            if not all(isinstance(v, str) for v in (line, city, zip_code)) or not line or not city:
                bad.append(f"{path.name} has a row without a line or city")
                break
            ident = (round(lon * SCALE), round(lat * SCALE), line, city, zip_code)
            if last is not None and ident <= last:
                bad.append(f"{path.name} is not in order or repeats a row")
                break
            last = ident
            shard_rows.append((path.name, city, lon, lat, line, zip_code))
    check("every shard parses, has its name, bounds, order and count, and stays within the limit",
          not bad and shard_count == block["shards"], "; ".join(bad[:5]) or f"{shard_count} shards")
    counts["shards"] = shard_count
    matched, b_problems = _matched_rows(root)
    # D28: once the outline step has split the rows, hail/a holds the rows its block records (buildings a rows) and
    # hail/b holds the rest; before the split (no outline block, or one that did not load) hail/a holds every row.
    buildings = index.get("buildings") if isinstance(index.get("buildings"), dict) else {}
    split = buildings.get("state") == "loaded" and buildings.get("addresses") == "loaded"
    a_block = buildings.get("a") if split and isinstance(buildings.get("a"), dict) else {}
    expect_a = a_block.get("rows") if split else rows
    check("the shard count matches the index: hail/a holds the rows the outline block records (or every row before the "
          "split), and the matched rows in hail/b make up the rest (D28)",
          not b_problems and isinstance(expect_a, int) and not isinstance(expect_a, bool)
          and len(shard_rows) == expect_a and matched == rows - expect_a and shard_count == block["shards"],
          "; ".join(b_problems[:3]) or
          f"{len(shard_rows)} unmatched rows in hail/a and {matched} matched in hail/b, {rows} in the index")
    check("the depths match the index", {str(k): v for k, v in sorted(depth_hist.items())} == block["depths"],
          str(dict(sorted(depth_hist.items()))))
    # D49: the figures of the block that describe hail/a are the files' own. The outline step rewrites the shards (D28)
    # and writes these figures back, so a figure that differs from the files is named here, with both values.
    try:
        disk = disk_figures(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check(FIGURES_CHECK, False, f"the files in hail/a could not be read for their figures ({exc})")
    else:
        stale = figure_differences(block, disk)
        detail = ("; ".join(stale[:4]) + "; rebuild the store (the figures are written from hail/a)" if stale
                  else f"{disk['shards']:,} shards and {disk['letter_files']:,} letter files, as the block says")
        check(FIGURES_CHECK, not stale, detail)
    split_ok = True
    for tile, leaves in block["split"].items():
        if sorted(leaves) != sorted(n for n in names_seen if n.startswith(tile) and len(n) > len(tile)):
            split_ok = False
    check("the split map names the shards of each split tile", split_ok)
    rows_by_tile = Counter(item[0][:TILE_NAME_LEN] for item in shard_rows)
    outside = [tile for tile in sorted(block["tiles"]) if not (root / "hail" / "t" / f"{tile}.json").is_file()]
    counts["tiles_outside_hail_grid"] = {tile: rows_by_tile[tile] for tile in outside}
    check("address tiles with no hail grid shard (their dots say they are outside the grid; D23)", True,
          "; ".join(f"{tile}: {rows_by_tile[tile]} row{'' if rows_by_tile[tile] == 1 else 's'}" for tile in outside)
          or "none")
    idx = a_dir / "idx"
    try:
        cities = _read_json(idx / "cities.json")
        words = _read_json(idx / "words.json")
    except (OSError, ValueError) as exc:
        check("the search index files read", False, str(exc))
        return result()
    check("the cities file and the words file have their formats",
          cities.get("f") == CITIES_FORMAT and words.get("f") == WORDS_FORMAT and
          words.get("words") == search_words())
    city_total = sum(entry["n"] for entry in cities["cities"].values())
    keys_ok = all(sum(entry["keys"].values()) == entry["n"] for entry in cities["cities"].values())
    check("the city counts add up to the rows", city_total == rows and keys_ok,
          f"{city_total} rows in the cities file, {rows} in the index")
    letters = defaultdict(set)
    letter_rows = 0
    letter_bad = []
    for city, entry in cities["cities"].items():
        folder = idx / entry.get("dir", slug(city))
        for key, count in entry["keys"].items():
            path = folder / f"{file_key(key)}.json"
            try:
                doc = _read_json(path)
            except (OSError, ValueError):
                letter_bad.append(f"{path} is missing")
                continue
            if doc.get("f") != IDX_FORMAT or len(doc["a"]) != count:
                letter_bad.append(f"{path} does not hold {count} rows")
                continue
            if any(not (isinstance(r, list) and len(r) == 7 and isinstance(r[6], str) and r[6] in CLASS_SET)
                   for r in doc["a"]):
                letter_bad.append(f"{path} has a row that is not seven values ending in a placement class")
                continue
            if count > ROWS_LIMIT:
                letter_bad.append(f"{path} is over the limit")
            for number, street, unit, lon, lat, zip_code, _cls in doc["a"]:
                line = " ".join(text for text in (number, street, unit) if text)
                letters[city].add((round(lon * SCALE), round(lat * SCALE), line, zip_code))
                letter_rows += 1
    check("every letter file holds the rows its cities file says", not letter_bad and letter_rows == rows,
          "; ".join(letter_bad[:5]) or f"{letter_rows} letter rows")
    # The limit on two-character letter files (D5): a letter is keyed by two characters only when its one-character
    # file would hold more than the limit, and then it has no one-character file.
    split_bad = []
    for city, entry in cities["cities"].items():
        two: Counter = Counter()
        one = set()
        for key, count in entry["keys"].items():
            if len(key) == 2:
                two[key[0]] += count
            elif len(key) == 1:
                one.add(key)
        for first, total in sorted(two.items()):
            if first in one:
                split_bad.append(f"{city}: {first} has a one-character file and two-character files")
            elif total <= ROWS_LIMIT and not block.get("sample"):
                # a sample keeps the real store's keys (the browser names the same files), so only a real build's
                # counts can justify a split
                split_bad.append(f"{city}: {first} is split to two characters but holds {total} rows")
    check("two-character letter files are used only where their letter holds more than the limit",
          not split_bad, "; ".join(split_bad[:5]) or f"{sum(1 for e in cities['cities'].values() for k in e['keys'] if len(k) == 2)} two-character files")
    rng = random.Random(20261019)
    sample = rng.sample(shard_rows, min(200, len(shard_rows)))
    missing = [s for s in sample if (round(s[2] * SCALE), round(s[3] * SCALE), s[4], s[5]) not in letters[s[1]]]
    check("200 random rows are in their city's letter files", not missing,
          f"{len(sample) - len(missing)} of {len(sample)} found")
    counts.update({"rows": rows, "cities": len(cities["cities"]), "letter_rows": letter_rows})
    placement = block.get("placement")
    if not isinstance(placement, dict):
        check("the placement classes are recorded per county", False, "the addresses block has no placement counts")
    else:
        classes, by_county = placement["classes"], placement["by_county"]
        totals_ok = sum(classes.values()) == rows + block["merged_duplicates"] and set(classes) == set(CLASS_LETTERS)
        counties_ok = all(sum(c.get(letter, 0) for c in by_county.values()) == classes.get(letter, 0)
                          for letter in CLASS_LETTERS)
        check("the placement classes add up to the kept rows and to the counties", totals_ok and counties_ok,
              f"{sum(classes.values())} kept records, {rows} rows and {block['merged_duplicates']} merged")
        counts["placement_classes"] = classes
        counts["placement_by_county"] = by_county
    if not block.get("sample"):              # a SAMPLE block has no merge report (its rows are cut from the file)
        report = block.get("merged_groups")
        agrees = _merge_report_ok(report, block["merged_duplicates"])
        check("the merged groups keep the Structure row (D39)", agrees,
              _merge_text(report) if agrees else "the index has no merge report that agrees with its merged rows")
        if agrees:
            counts["merged_groups"] = report
    if zip_path is not None:
        _verify_against_zip(zip_path, block, check, counts)
    return result()


def _verify_against_zip(zip_path, block: dict, check, counts: dict) -> None:
    """Recompute the counts, the placement classes, the merged rows and the projection pairs from the framework file
    (verify --zip). Any failure to read or recompute the file fails the check; it never passes silently."""
    try:
        fw = _open_framework(zip_path)
    except AddressesError as exc:
        check("the framework file reads as the one this build reads", False, str(exc))
        return
    check("the framework file reads as the one this build reads", True)
    try:
        recount: Counter = Counter()
        keep, xs, ys = _collect(zip_path, fw, recount)
        check("the points, the left-out rows and the rows match the file",
              fw.nrec == block["points"] and recount["left_out_no_position"] == block["left_out_no_position"]
              and recount["left_out_no_street"] == block["left_out_no_street"]
              and recount["left_out_deleted"] == block["left_out_deleted"]
              and recount["left_out_no_city"] == block["left_out_no_city"] and len(keep) == fw.nrec
              - block["left_out_no_position"] - block["left_out_no_street"] - block["left_out_deleted"]
              - block["left_out_no_city"],
              f"file: {fw.nrec} points, {recount['left_out_no_street']} with no street, "
              f"{recount['left_out_no_city']} with no city")
        check("the placement classes match the file", placement_counts(keep) == block.get("placement"),
              "per county, as the index records them")
        lons, lats = _project(xs, ys)
        pair_lines = {(p["line"], p["city"]): True for p in PROJECTION_PAIRS}
        rows, found = _make_rows(keep, lons, lats, pair_lines)
        _kept, report = _dedupe(rows)
        merged = report["merged_rows"]
        check("the merged rows match the file", merged == block["merged_duplicates"], f"{merged} merged")
        check("the merged groups match the file (D39)", report == block.get("merged_groups"), _merge_text(report))
        pairs = _pairs_check(found, lambda index: (lons[index], lats[index]))
        check("the projection pairs agree with the file", all(p["metres"] < PROJECTION_TOLERANCE_M for p in pairs))
    except AddressesError as exc:
        check("the file recomputes to the index (counts, classes, merges and pairs)", False, str(exc))


# ---------------------------------------------------------------- words and map data (D6, D7, D8)

def describe_addresses(index: dict | None = None, sample: bool = False) -> dict:
    """The About paragraphs for the terms (D8): the source and file date, the three metadata sentences quoted, the
    allow-list sentence, the no-list-of-persons sentence, the coverage caveat and the privacy sentence. The quotes
    come from the index's source block when one is given (copied from the file at build time). The source line gives
    a file date only when the index read one (D24)."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    source = (block.get("source") or {}) if isinstance(block, dict) else {}
    dated = "export_date" in source and "pubdate" in source     # the file date only when the index read it (D24)
    accconst = source.get("accconst", ACCCONST_TEXT)
    purpose = source.get("purpose", PURPOSE_TEXT)
    source_line = (WORDS_ADDRESSES["about_source"].format(pubdate=source["pubdate"], export_date=source["export_date"])
                   if dated else WORDS_ADDRESSES["about_source_undated"])
    out = {
        "title": WORDS_ADDRESSES["about_title"],
        "source": source_line,
        "access": "Access terms in the file's metadata: " + accconst,
        "use": WORDS_ADDRESSES["about_use"],
        "purpose": "The file's stated purpose: " + purpose,
        "fields": WORDS_ADDRESSES["about_fields"],
        "exclusion": WORDS_ADDRESSES["about_exclusion"],
        "persons": WORDS_ADDRESSES["about_persons"],
        "coverage": WORDS_ADDRESSES["about_coverage"],
        "privacy": WORDS_ADDRESSES["about_privacy"],
    }
    if sample:
        out["sample"] = WORDS_ADDRESSES["sample"]
    return out


def map_data_addresses(index: dict) -> dict:
    """The map.json["hail"]["addresses"] block (D7): the state, the counts, the shard URL pattern, the tiles that hold
    addresses (build.b3_map_blocks turns the list into the compact tile_split, D40), the split map (a tile with more than one shard names its shards; a tile not listed has one shard of its
    own name), the letter file pattern, the words, the limits and every template. Positions and the search text
    never leave the browser; the requests carry only shard and key names. The zoom rules (zoom: dots 15, choose 17) and
    the dot radius rule are carried in every state (D47), so the browser never reads an absent rule."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    if not isinstance(block, dict) or block.get("state") != "loaded":
        problem = block.get("reason") if isinstance(block, dict) else "the address list is not in the store"
        return {"state": "unavailable", "problem": problem or "the address list is not in the store",
                "zoom": dict(ZOOM), "dot_radius_px": dict(DOT_RADIUS_PX),
                "templates": {**WORDS_ADDRESSES, "placed_how": dict(PLACEMENT_HOW)}}
    return {
        "state": "sample" if block.get("sample") else "loaded",
        "problem": None,
        "count": block["rows"],
        "points": block["points"],
        "shards": block["shards"],
        "shard": "hail/a/{name}.json",
        "tiles": list(block["tiles"]),
        "split": {tile: list(names) for tile, names in sorted(block["split"].items())},
        "cities": "hail/a/idx/cities.json",
        "letter": "hail/a/idx/{dir}/{key}.json",
        "dir": "the city's own dir in cities.json when it has one, else its slug (lower-case words joined with dashes)",
        "file_key": "letters and digits as they are; any other character as _ and four lower-case hex digits",
        "words": "hail/a/idx/words.json",
        "search_words": search_words(),
        "limits": {"tap_radius_px": TAP_RADIUS_PX, "result_cap": RESULT_CAP,
                   "rows_per_file": ROWS_LIMIT},
        "zoom": dict(ZOOM),                     # D47: the browser's zoom rules for the address layer
        "dot_radius_px": dict(DOT_RADIUS_PX),   # D7: the dot radius rule (the building layer reads the same rule)
        "classes": CLASS_LETTERS,
        "templates": {**WORDS_ADDRESSES, "placed_how": dict(PLACEMENT_HOW)},
        "source": {"export_date": block["source"]["export_date"], "pubdate": block["source"]["pubdate"]},
    }


# ---------------------------------------------------------------- the fixture (D10)

FIXTURE_PER_TILE = 20          # real rows sampled evenly from each fixture tile
FIXTURE_NEAREST = 300          # the rows nearest 401 North 27th Street, Billings (D10)
ANCHOR = ("401 North 27th Street", "Billings")


def _read_real_rows(store: Path) -> list:
    """Every row of a built store's letter files, as Row tuples (the file key is the real one)."""
    idx = store / "hail" / "a" / "idx"
    cities = _read_json(idx / "cities.json")
    out = []
    for city, entry in sorted(cities["cities"].items()):
        folder = idx / entry.get("dir", slug(city))
        for key in sorted(entry["keys"]):
            doc = _read_json(folder / f"{file_key(key)}.json")
            for number, street, unit, lon, lat, zip_code, cls in doc["a"]:
                line = " ".join(text for text in (number, street, unit) if text)
                out.append(Row(round(lon * SCALE), round(lat * SCALE), line, city, zip_code, number, street, unit,
                               add_value(number), key, cls, ""))
    return out


def _sample_placement(chosen: list) -> dict:
    """The placement counts of the SAMPLE rows (the sample keeps no county, so its counts form one group)."""
    classes = {letter: sum(1 for row in chosen if row.cls == letter) for letter in CLASS_LETTERS}
    return {"classes": classes, "blank_as_unknown": 0, "by_county": {"(sample)": dict(classes)}}


def _fixture_rows(real: list, tiles: list, per_tile: int, nearest: int) -> list:
    wanted = set(tiles)
    chosen = set()
    by_tile: dict[str, list] = defaultdict(list)
    for row in real:
        tile_row, tile_col = tile_of(row.lat5, row.lon5)
        name = hail.tile_name(tile_row, tile_col)
        if name in wanted:
            by_tile[name].append(row)
    for name in sorted(by_tile):
        rows = sorted(by_tile[name], key=lambda r: (r.lon5, r.lat5, r.line, r.city, r.zip))
        if len(rows) <= per_tile:
            picked = rows
        else:
            picked = [rows[(k * len(rows)) // per_tile] for k in range(per_tile)]
        chosen.update((r.lon5, r.lat5, r.line, r.city, r.zip) for r in picked)
    anchors = sorted((r for r in real if r.line == ANCHOR[0] and r.city == ANCHOR[1]),
                     key=lambda r: (r.lon5, r.lat5))
    if not anchors:
        raise AddressesError(f"the real store has no {ANCHOR[0]}, {ANCHOR[1]} row for the fixture")
    anchor = anchors[0]
    lat0 = anchor.lat5 / SCALE
    cos0 = math.cos(math.radians(lat0))

    def gap(row) -> tuple:
        dx = (row.lon5 - anchor.lon5) / SCALE * cos0
        dy = (row.lat5 - anchor.lat5) / SCALE
        return (dx * dx + dy * dy, row.lon5, row.lat5, row.line, row.city, row.zip)

    for row in sorted(real, key=gap)[:nearest]:
        chosen.add((row.lon5, row.lat5, row.line, row.city, row.zip))
    by_ident = {(r.lon5, r.lat5, r.line, r.city, r.zip): r for r in real}
    return [by_ident[ident] for ident in sorted(chosen)]


def fixture(out_dir, from_store, *, per_tile: int = FIXTURE_PER_TILE, nearest: int = FIXTURE_NEAREST) -> dict:
    """Write the SAMPLE address files into the fixture folder out_dir (website/data/hail-fixture, D18): the real rows of
    the fixture's tiles (per_tile evenly spread rows each) and the nearest rows to 401 North 27th Street, Billings, from
    the real store at from_store, under hail/a/. out_dir must already hold the B1 and B2 fixture (hail/index.json and
    hail/manifest.json, written by hail.fixture_store and joins.fixture); this writer never clears hail/. Deterministic:
    the same real store gives the same bytes."""
    out = Path(out_dir)
    if not (out / "hail" / "index.json").is_file() or not (out / "hail" / "manifest.json").is_file():
        raise AddressesError("the fixture folder has no hail index or manifest; write the B1 and B2 fixture first")
    sample_index = hail.load_index(out)
    real_store = Path(from_store)
    real_index = hail.load_index(real_store)
    real_block = real_index.get(INDEX_KEY)
    if not isinstance(real_block, dict) or real_block.get("state") != "loaded":
        raise AddressesError("the real store has no loaded address block; build it first")
    real = _read_real_rows(real_store)
    chosen = _fixture_rows(real, list(sample_index["tiles"]), per_tile, nearest)
    tree = _write_tree(out, chosen)
    block = {
        "format": FORMAT,
        "state": "loaded",
        "sample": True,
        "built_at": real_block["built_at"],
        "sample_of": real_block["built_at"],
        "source": dict(real_block["source"], note="SAMPLE: a few rows of the real file, cut for the fixture"),
        "points": len(chosen),
        "left_out_no_position": 0,
        "left_out_no_street": 0,
        "left_out_no_city": 0,
        "left_out_deleted": 0,
        "merged_duplicates": 0,
        "rows": len(chosen),
        "shards": tree["shards"],
        "tiles": tree["tiles"],
        "split": tree["split"],
        "depths": tree["depths"],
        "largest_shard": tree["largest_shard"],
        "cities": tree["cities"],
        "letter_files": tree["letter_files"],
        "largest_letter": tree["largest_letter"],
        "two_character_files": tree["two_character_files"],
        "over_limit_shards": tree["over_limit_shards"],
        "over_limit_letter_files": tree["over_limit_letter_files"],
        "bytes": {"shards": tree["shard_bytes"], "letters": tree["letter_bytes"],
                  "cities": tree["cities_bytes"], "words": tree["words_bytes"],
                  "idx": tree["letter_bytes"] + tree["cities_bytes"] + tree["words_bytes"],
                  "a": tree["shard_bytes"] + tree["letter_bytes"] + tree["cities_bytes"] + tree["words_bytes"]},
        "fields_read": list(ALLOWED_FIELDS),
        "projection": {"from": EPSG_FROM, "to": EPSG_TO, "always_xy": True, "decimals": 5},
        "pyproj": real_block.get("pyproj"),
        "projection_pairs": real_block["projection_pairs"],
        "limits": {"rows": ROWS_LIMIT, "depth_cap": DEPTH_CAP},
        "placement": _sample_placement(chosen),
    }
    _wire(out, block)
    hail.check_manifest(out)
    address_bytes = sum(p.stat().st_size for p in (out / "hail" / "a").rglob("*") if p.is_file())
    return {"out": str(out), "rows": len(chosen), "shards": tree["shards"], "tiles": tree["tiles"],
            "address_bytes": address_bytes, "sample_tiles": sample_index["tiles"]}


# ---------------------------------------------------------------- the command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.addresses",
                                     description="Address dots and the typed-address search (B3, data module).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="read the framework file, write hail/a/ and the addresses block")
    b.add_argument("--store", required=True, help="the store directory that holds hail/ (B1 and B2 built)")
    b.add_argument("--zip", default=None, help="the framework zip (skips the download)")
    b.add_argument("--cache", default="address-cache", help="the download cache (kept between runs)")
    b.add_argument("--url", default=MSL_URL, help="the download address (default: the MSL file)")
    b.add_argument("--ledger", default=None, help="a JSON-lines ledger of the requests (default: the cache's)")
    v = sub.add_parser("verify", help="check the addresses in a store (exit 1 on a failure)")
    v.add_argument("store_dir", nargs="?", metavar="STORE", help="the store directory (the same as --store)")
    v.add_argument("--store", dest="store_opt", default=None)
    v.add_argument("--zip", default=None, help="also recompute the counts and pairs from this framework zip")
    u = sub.add_parser("unavailable", help="mark the address list unavailable with a reason and remove its files (D36)")
    u.add_argument("--store", required=True, help="the store directory that holds hail/ (the job's failure branch)")
    u.add_argument("--reason", required=True, help="the plain reason the list is unavailable, without a full stop")
    f = sub.add_parser("fixture", help="write the SAMPLE address files into the B1 and B2 fixture folder")
    f.add_argument("--store", required=True, help="a built store with real address files (its hail/a/)")
    f.add_argument("--out", default=str(hail.FIXTURE_DIR), help="the shared fixture folder (website/data/hail-fixture)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            started = time.time()
            ledger = args.ledger
            if ledger is None and args.zip is None:
                ledger = str(Path(args.cache) / "ledger.jsonl")
            block = build(args.zip, args.store, cache=args.cache, url=args.url, ledger=ledger)
            summary = {k: block[k] for k in ("points", "left_out_no_street", "left_out_no_position",
                                             "merged_duplicates", "rows", "shards", "cities", "letter_files")}
            summary.update(largest_shard=block["largest_shard"], largest_letter=block["largest_letter"],
                           bytes=block["bytes"], depths=block["depths"], projection_pairs=block["projection_pairs"],
                           placement_classes=block["placement"]["classes"],
                           wall_seconds=round(time.time() - started, 1))
            print(json.dumps(summary, indent=1, ensure_ascii=False))
            return 0
        if args.command == "verify":
            store = args.store_opt or args.store_dir
            if not store:
                print("error: give the store directory (verify STORE or --store STORE)", file=sys.stderr)
                return 2
            result = verify(store, args.zip)
            print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
            return 0 if result["ok"] else 1
        if args.command == "unavailable":
            if not args.reason.strip():
                print("error: give the reason the list is unavailable (--reason TEXT)", file=sys.stderr)
                return 2
            print(json.dumps(mark_unavailable(args.store, args.reason), indent=1, ensure_ascii=False))
            return 0
        if args.command == "fixture":
            print(json.dumps(fixture(args.out, args.store), indent=1, ensure_ascii=False))
            return 0
    except SourceUnavailable as exc:
        if args.command != "build":          # verify and fixture: a source that does not read is a failure
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"warning: {exc}; the list is marked unavailable and the rest of the store is kept", file=sys.stderr)
        return 0
    except (AddressesError, hail.HailStoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
