"""Streets (B3 roads layer): the data module (docs/DECISIONS.md D25, D16, D16a, D26, D27, D33; the B3 brief).

Two sources build the same shards under hail/r/ of the hail store. The default is the Montana State Library's
Transportation Framework (--roads-source msl, D25; its use sentence and counsel gate are the address layer's). The
fallback is the U.S. Census Bureau's TIGER/Line 2026 All Roads county files (--roads-source tiger, D16; the Census
acknowledgement is shown when it is built). Both readers stream the zip or county files, keep the vehicular classes,
merge concurrent features, clean the names, simplify each line to 2 m and split the shards by bytes.

Output (store/hail/):
  r/<tile name><digits>.json   one shard per 0.1-degree B1 tile, split into quarters while its JSON is over 150,000 B
                               (depth cap 6). Names: the tile name plus one digit per level (0 NW, 1 NE, 2 SW, 3 SE).
                               {"f":"hail-roads-v1","b":[west,south,east,north],"n":lines,"names":["..."],
                                "r":[[class, name_index or -1, [[lon,lat],...]], ...]}
                               Lines are clipped to the shard bounds, so a line appears in every shard it crosses.
                               Classes (one letter, the browser maps a width from map.json): p primary, s secondary,
                               r ramp, l local street, d service drive, a alley, v private road, t trail.
  index.json                   gains "roads": the state, the source built (file, size, date, checksums, or the TIGER
                               edition and its 56 files), the terms sentences quoted from the file, the counts, the
                               shards, the bytes, the split map and the tiles.
  manifest.json                lists every r/ file with its size and SHA-256 (the other entries are kept).

Rules (the brief's D16, D16a, D25, D26, D33):
  - Vehicular classes only. Library RoadClass: Primary, Secondary, Local, Ramp, Service Drive, Alley, Private and
    Vehicular Trail keep their letters. RoadClass "Other" (15,416 records) is classified from its name and type words:
    a public road keeps the local style ("l"); a trail, a ferry, a private drive and an airfield surface are left out and
    counted. The Census classes S1100 to S1740 map as in TIGER_CLASS; S1750 (internal Census use) and S1780 (parking lot
    road) are left out with their counts, and so is every other non-vehicular code. Nothing is dropped silently.
  - Concurrent features (D16): every line is split into pieces of at most 25 m; a piece is covered when each of its three
    sample points (ends and middle) lies within 3 m of a parallel piece of a feature that comes earlier in the file.
    A covered piece is not drawn again; the names of the pieces it duplicates are joined into the line that covers it
    with " / ", so no name is lost. The line takes the most prominent class among the features it merges.
  - Names (D16a): a blank name, or a placeholder ("Internal", "Driveway", "Dwy", "Unknown", "Unnamed", "No Name",
    "Not Named"), leaves the line unnamed: drawn, never labelled, never searchable. TIGER abbreviations are spelled out
    for display with the table ABBREVIATIONS, which extends the address search's words (addresses.search_words()).
  - Simplification (D16, D48): Douglas-Peucker runs before the positions are rounded to 5 decimals, in the source's
    metric projection (EPSG:6514 for the Library, the NAD83 Montana projection EPSG:32100 for TIGER, both with pyproj),
    with a 2 m gate: the removed points are measured in those metres against the stored (5-decimal) positions of their
    two kept neighbours, so each removed point lies within 2 m of the stored line, which is the only line the store
    keeps and draws. Rounding moves a position by at most ROUND_MOVE_M (0.7 m) anywhere in Montana. After rounding, the
    largest distance from a source line to the drawn lines, measured on the Library file, is POST_ROUNDING_MAX_M
    (2.48 m, the supervisor's measure, D48). That is above the gate. The cause was not isolated; the concurrency merge
    (COVER_M, 3 m) is one candidate, and verify states the figure without recomputing it.
  - A failed source (D20, D36) never stops the store: every failure to read or validate a source (a missing or
    unreadable file, a changed field list, a changed terms sentence, a projection the file does not name) raises
    SourceUnavailable; build() marks the roads "unavailable" with its reason, removes r/ and exits 0.
  - Owner decision 6 and D12: the reader slices only the fields in its allow-list. The Library's Ownership field (an
    owner type), LocalID, NGUID and GlobalID are never read. The TIGER reader reads LINEARID, FULLNAME, RTTYP and MTFCC.

Command line (run from the repository root):
    python -m website.streets build --store DIR [--roads-source msl|tiger] [--cache DIR] [--url URL]
                                    [--tiger-edition 2026] [--ledger FILE]
    python -m website.streets verify --store DIR [--roads-source msl|tiger] [--cache DIR]
    python -m website.streets unavailable --store DIR --reason TEXT

pyproj is imported only when a position is projected (the daily job installs pyproj~=3.8, D19; the tests skip without
it). numpy is imported only by the builder (the site build never imports this module's builder).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import addresses, hail

FORMAT = "hail-roads-v1"
INDEX_KEY = "roads"                    # the block in hail/index.json
SHARD_DIR = "r"                        # hail/r/<name>.json
SHARD_LIMIT = 150_000                  # bytes per shard JSON before a split (D26)
DEPTH_CAP = 6                          # quadtree depth cap (as the address shards)
CHUNK_M = 25.0                         # the longest piece of a line that is tested for concurrency
COVER_M = 3.0                          # two features share geometry within this distance (D16)
GRID_M = 12.0                          # cell size of the candidate grid for the concurrency test
PARALLEL_DEG = 10.0                    # two pieces are parallel within this angle
MIN_DIR_M = 0.5                        # a piece shorter than this has no direction and cannot cover another
DP_TOL_M = 2.0                         # Douglas-Peucker tolerance in metres (D16), before the rounding to 5 decimals
ROUND_MOVE_M = 0.7                     # most a position moves in the rounding to 5 decimals, anywhere in Montana (D48)
POST_ROUNDING_MAX_M = 2.48             # largest distance from a source line to the drawn lines, measured (D48)
SCALE = 100_000                        # positions are whole units of 1e-5 degree (5 decimals)
TILE_UNITS = 10_000                    # one B1 tile (0.1 degree) in 1e-5 degree units
ROW_TOP = 5_500_000                    # the north edge of the B1 grid in 1e-5 degree units (row 0)
COL_LEFT = -13_000_000                 # the west edge of the B1 grid in 1e-5 degree units (column 0)
TILE_NAME_LEN = len(hail.tile_name(0, 0))   # "r0000_c0000" is 11 characters; a shard's leaf name adds digits
ZOOM = {"arterials": 13, "local": 15, "names": 16, "outline": 17}     # D27
CLASS_ORDER = "psrldavt"               # prominence, most first: a merged line takes the first class it merges
CLASSES = {                            # the browser's widths in CSS pixels and the zoom each class starts at (D27)
    "p": {"name": "primary road", "width": 4.0, "min_zoom": 13},
    "s": {"name": "secondary road", "width": 3.0, "min_zoom": 13},
    "r": {"name": "ramp", "width": 2.0, "min_zoom": 15},
    "l": {"name": "local street", "width": 1.5, "min_zoom": 15},
    "d": {"name": "service drive", "width": 1.5, "min_zoom": 15},
    "a": {"name": "alley", "width": 1.25, "min_zoom": 15},
    "v": {"name": "private road", "width": 1.25, "min_zoom": 15},
    "t": {"name": "trail", "width": 1.25, "min_zoom": 15},
}
UNAVAILABLE = "Montana's street list is unavailable"

# ---------------------------------------------------------------- the Library's table (D1 pattern, D16, D25)

# The table's 51 fields in order (name, type, length), as the file's header gives them (checked at every read).
LIBRARY_DBF_SPEC = (
    ("DiscrpAgID", "C", 100), ("DateUpdate", "D", 8), ("Effective", "D", 8), ("Expire", "D", 8), ("NGUID", "C", 254),
    ("AdNumPre_L", "C", 15), ("AdNumPre_R", "C", 15), ("FromAddr_L", "N", 10), ("ToAddr_L", "N", 10),
    ("FromAddr_R", "N", 10), ("ToAddr_R", "N", 10), ("Parity_L", "C", 1), ("Parity_R", "C", 1),
    ("St_PreMod", "C", 15), ("St_PreDir", "C", 10), ("St_PreTyp", "C", 50), ("St_PreSep", "C", 20),
    ("St_Name", "C", 254), ("St_PosTyp", "C", 50), ("St_PosDir", "C", 10), ("St_PosMod", "C", 25),
    ("LSt_PreDir", "C", 2), ("LSt_Name", "C", 75), ("LSt_Typ", "C", 4), ("LSt_PosDir", "C", 2),
    ("Country_L", "C", 2), ("Country_R", "C", 2), ("State_L", "C", 2), ("State_R", "C", 2),
    ("County_L", "C", 100), ("County_R", "C", 100), ("IncMuni_L", "C", 100), ("IncMuni_R", "C", 100),
    ("UnincCom_L", "C", 100), ("UnincCom_R", "C", 100), ("NbrhdCom_L", "C", 100), ("NbrhdCom_R", "C", 100),
    ("PostCode_L", "C", 7), ("PostCode_R", "C", 7), ("PostComm_L", "C", 40), ("PostComm_R", "C", 40),
    ("RoadClass", "C", 24), ("OneWay", "C", 2), ("SpeedLimit", "N", 5), ("LocalID", "C", 38),
    ("SurfaceTyp", "C", 15), ("Access", "C", 50), ("Ownership", "C", 15), ("ProcessID", "N", 10),
    ("ProcessDte", "D", 8), ("GlobalID", "C", 38),
)
LIBRARY_HEADER_BYTES = 1665
LIBRARY_RECORD_BYTES = 2075
# The reader slices these fields and no others: the county, the street words, the road class and the surface.
LIBRARY_ALLOWED = ("County_L", "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_Name", "St_PosTyp",
                   "St_PosDir", "St_PosMod", "RoadClass", "SurfaceTyp")
# Owner decision 6: never read, stored or shown (Ownership is the owner type; LocalID and GlobalID are identifiers).
LIBRARY_NEVER = ("Ownership", "LocalID", "NGUID", "GlobalID", "DiscrpAgID", "ProcessID")
LIBRARY_PRJ = "NAD_1983_2011_StatePlane_Montana_FIPS_2500"
LIBRARY_CRS = "EPSG:6514"              # NAD83(2011) / Montana (metres), the file's projection
LIBRARY_LONLAT = "EPSG:4326"
LIBRARY_SHP = "RoadCenterLine.shp"
LIBRARY_SHX = "RoadCenterLine.shx"
LIBRARY_DBF = "RoadCenterLine.dbf"
LIBRARY_PRJ_MEMBER = "RoadCenterLine.prj"
LIBRARY_META = "TransportationFramework_metadata.xml"
LIBRARY_README = "_ReadMe.txt"
LIBRARY_ZIP_NAME = "TransportationFramework_shp.zip"
LIBRARY_URL = ("https://ftpgeoinfo.msl.mt.gov/Data/Spatial/MSDI/Transportation/TransportationFramework_shp.zip")
LIBRARY_CLASS = {"Primary": "p", "Secondary": "s", "Local": "l", "Ramp": "r", "Service Drive": "d",
                 "Alley": "a", "Private": "v", "Vehicular Trail": "t"}
# The terms the site quotes (D8, D25): checked in the file's own metadata at every build (D36).
LIBRARY_CONVENIENCE = ("The Library makes these data and services available as a convenience to the public, and for no "
                       "other purpose.")
LIBRARY_DISCLAIMER = ("The Library did not produce it for, nor is it suitable for legal, engineering, or surveying "
                      "purposes.")

# ---------------------------------------------------------------- the Census table (D16)

TIGER_DBF_SPEC = (("LINEARID", "C", 22), ("FULLNAME", "C", 100), ("RTTYP", "C", 1), ("MTFCC", "C", 5))
TIGER_HEADER_BYTES = 161
TIGER_RECORD_BYTES = 129
TIGER_ALLOWED = ("LINEARID", "FULLNAME", "RTTYP", "MTFCC")
TIGER_CRS = "EPSG:32100"               # NAD83 / Montana (metres): the TIGER datum without a shift
TIGER_GEO = "EPSG:4269"                # NAD83 (degrees), the datum of the county files
TIGER_CLASS = {"S1100": "p", "S1200": "s", "S1400": "l", "S1500": "t", "S1630": "r", "S1640": "d", "S1730": "a",
               "S1740": "v"}
TIGER_LEFT_OUT = {"S1750": "internal Census use road (left out, D33)", "S1780": "parking lot road (left out, D33)"}
TIGER_ACK = "acknowledgement must be given to the U.S. Census Bureau as the source."
TIGER_TRADEMARK = "TIGER/Line and Census TIGER are registered trademarks of the U.S. Census Bureau."
TIGER_ACCURACY = ("may not be suitable for high-precision measurement applications such as engineering problems, "
                  "property transfers, or other uses that might require highly accurate measurements of the earth's "
                  "surface.")
TIGER_FIPS = {
    "30001": "Beaverhead", "30003": "Big Horn", "30005": "Blaine", "30007": "Broadwater", "30009": "Carbon",
    "30011": "Carter", "30013": "Cascade", "30015": "Chouteau", "30017": "Custer", "30019": "Daniels",
    "30021": "Dawson", "30023": "Deer Lodge", "30025": "Fallon", "30027": "Fergus", "30029": "Flathead",
    "30031": "Gallatin", "30033": "Garfield", "30035": "Glacier", "30037": "Golden Valley", "30039": "Granite",
    "30041": "Hill", "30043": "Jefferson", "30045": "Judith Basin", "30047": "Lake", "30049": "Lewis and Clark",
    "30051": "Liberty", "30053": "Lincoln", "30055": "McCone", "30057": "Madison", "30059": "Meagher",
    "30061": "Mineral", "30063": "Missoula", "30065": "Musselshell", "30067": "Park", "30069": "Petroleum",
    "30071": "Phillips", "30073": "Pondera", "30075": "Powder River", "30077": "Powell", "30079": "Prairie",
    "30081": "Ravalli", "30083": "Richland", "30085": "Roosevelt", "30087": "Rosebud", "30089": "Sanders",
    "30091": "Sheridan", "30093": "Silver Bow", "30095": "Stillwater", "30097": "Sweet Grass", "30099": "Teton",
    "30101": "Toole", "30103": "Treasure", "30105": "Valley", "30107": "Wheatland", "30109": "Wibaux",
    "30111": "Yellowstone",
}
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER{edition}/ROADS/tl_{edition}_{fips}_roads.zip"

# ---------------------------------------------------------------- names, abbreviations and placeholders (D16a)

PLACEHOLDERS = frozenset({"driveway", "dwy", "unknown", "unnamed", "no name", "not named", "internal"})
# The abbreviation table: the address search's words (directions, street types, US, MT and #) plus the road words the
# Census file uses. The browser and the display read the same table (map.json carries it).
ABBREVIATIONS = {**addresses.search_words(), "hwy": "highway", "co": "county", "byp": "bypass", "rte": "route"}
_SPELL_DIRECTION = {"n": "North", "s": "South", "e": "East", "w": "West", "ne": "Northeast", "nw": "Northwest",
                    "se": "Southeast", "sw": "Southwest"}
_SPELL_TYPE = {"st": "Street", "ave": "Avenue", "rd": "Road", "dr": "Drive", "ln": "Lane", "ct": "Court",
               "trl": "Trail", "blvd": "Boulevard", "cir": "Circle", "pl": "Place", "hwy": "Highway",
               "pkwy": "Parkway", "ter": "Terrace", "sq": "Square", "lp": "Loop", "byp": "Bypass", "co": "County"}
_SPELL_ROUTE = {"us": "United States", "mt": "Montana"}
_ROUTE_NEXT = {"hwy", "highway", "rte", "route"}

_TYPE_WORDS = frozenset(_SPELL_TYPE)
TOKEN_SPACE = re.compile(r"\s+")


class StreetsError(Exception):
    """A build or check that cannot finish. The message is plain words (the command line exits 1)."""


class SourceUnavailable(StreetsError):
    """The source did not answer, or the file is not the one the reader expects (D20, D36). The roads are marked
    unavailable with the reason, the rest of the store is kept and the command exits 0."""


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _np():
    import numpy                          # lazy: only the builder needs it (numpy is in the site and job installs)
    return numpy


def _unavailable(reason: str) -> SourceUnavailable:
    return SourceUnavailable(f"{UNAVAILABLE}: {reason}")


def _text(raw: bytes) -> str:
    """A field's text: UTF-8 with stray bytes turned into spaces, runs of spaces collapsed, the ends stripped."""
    return TOKEN_SPACE.sub(" ", raw.decode("utf-8", errors="replace").replace("�", " ")).strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compact(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".streets-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def expand_name(name: str) -> str:
    """The display form of a Census road name: abbreviations spelled out (ABBREVIATIONS), so "Co Rd 308" is
    "County Road 308", "US Hwy 87" is "United States Highway 87" and "13th St W" is "13th Street West". A direction
    is spelled only where it is a street direction (first word before a name, or last word after a street type)."""
    tokens = name.split()
    out = []
    for i, token in enumerate(tokens):
        low = token.lower().rstrip(".")
        nxt = tokens[i + 1].lower().rstrip(".") if i + 1 < len(tokens) else ""
        prev = tokens[i - 1].lower().rstrip(".") if i > 0 else ""
        if low in _SPELL_ROUTE and nxt in _ROUTE_NEXT:
            out.append(_SPELL_ROUTE[low])
        elif low in _SPELL_TYPE and (i > 0 or len(tokens) > 1):
            out.append(_SPELL_TYPE[low])
        elif low in _SPELL_DIRECTION and ((i == 0 and len(tokens) > 1) or (i == len(tokens) - 1 and prev in _TYPE_WORDS)):
            out.append(_SPELL_DIRECTION[low])
        else:
            out.append(token)
    return " ".join(out)


def is_placeholder(name: str) -> bool:
    """True when a name is blank or a placeholder that must never be drawn as a label (D16a)."""
    return (not name) or name.casefold() in PLACEHOLDERS


def library_name(fields: dict) -> str:
    """The road's name in the file's NENA order, single spaces (St_PreMod St_PreDir St_PreTyp St_PreSep St_Name
    St_PosTyp St_PosDir St_PosMod). The Library spells the words out, so no abbreviation is expanded."""
    order = ("St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod")
    return " ".join(fields[name] for name in order if fields[name])


_WORD = re.compile(r"[A-Za-z]+")


def classify_library(road_class: str, fields: dict) -> tuple[str | None, str | None]:
    """(class letter, None) for a kept road, or (None, reason) for a line left out (D33). Other is classified here."""
    if road_class in LIBRARY_CLASS:
        return LIBRARY_CLASS[road_class], None
    if road_class == "Other":
        return _classify_other(fields)
    if road_class == "":
        return None, "no road class"
    return None, road_class


def _classify_other(fields: dict) -> tuple[str | None, str | None]:
    """RoadClass "Other" (D33): a public road keeps the local-street style. A trail, a ferry, a private drive and an
    airfield surface are left out, each with its own count. The name and type words are the attributes used; the
    Ownership field is never read (decision 6)."""
    name = library_name(fields)
    low = name.casefold()
    pos = fields["St_PosTyp"].casefold()
    pre = fields["St_PreTyp"].casefold()
    if pos in ("trail", "track") or pre in ("trail", "track"):
        return None, "Other: trail"
    if pos == "ferry" or pre == "ferry" or low == "ferry":      # a ferry route; "Greers Ferry Road" is a road
        return None, "Other: ferry"
    if low in ("driveway", "dwy") or re.fullmatch(r"pvt\d*", low) or low.startswith("private"):
        return None, "Other: private drive"
    if pre == "runway" or pos in ("taxiway", "runway") or low in ("taxiway", "runway"):
        return None, "Other: airfield surface"
    return "l", None


def classify_tiger(mtfcc: str) -> tuple[str | None, str | None]:
    if mtfcc in TIGER_CLASS:
        return TIGER_CLASS[mtfcc], None
    if mtfcc in TIGER_LEFT_OUT:
        return None, mtfcc
    return None, (mtfcc or "(blank)")


# ---------------------------------------------------------------- words (D17, D24, D29, D33)

WORDS_STREETS = {
    "msl": {
        "legend": ("Streets from the Montana State Library's Transportation Framework; unnamed roads are drawn "
                   "without a label"),
        "attribution": ("Roads: Montana State Library, Transportation Framework, file dated {pubdate}. Terms in the "
                        "file's metadata: \"{convenience}\""),
        "attribution_undated": ("Roads: Montana State Library, Transportation Framework (file date not available in "
                                "this update). Terms in the file's metadata: \"{convenience}\""),
        "caveat": "The file's metadata says: \"{disclaimer}\"",
        # D41, D89(d): the unavailable line ends with the required sentence, as addresses.py and buildings.py do
        "unavailable": ("Streets could not be loaded in this update; that is not the same as having no streets. "
                        "This is not an all-clear."),
    },
    "tiger": {
        "legend": ("Streets from the U.S. Census Bureau's 2026 road files; unnamed roads are drawn without a label"),
        "attribution": ("Roads: U.S. Census Bureau, TIGER/Line 2026 road files. The file's metadata says: "
                        "\"{acknowledgement}\" It also says: \"{trademark}\" This site does not put those names in "
                        "any product name."),
        "attribution_undated": ("Roads: U.S. Census Bureau, TIGER/Line 2026 road files. The file's metadata says: "
                                "\"{acknowledgement}\" It also says: \"{trademark}\" This site does not put those "
                                "names in any product name."),
        "caveat": "The Census Bureau's metadata says the files \"{accuracy}\"",
        # D41, D89(d): the unavailable line ends with the required sentence, as addresses.py and buildings.py do
        "unavailable": ("Streets could not be loaded in this update; that is not the same as having no streets. "
                        "This is not an all-clear."),
    },
}


def _quoted_ok(text: str, sentence: str) -> bool:
    return " ".join(sentence.split()) in " ".join(text.split())


def wording(kind: str, facts: dict) -> dict:
    """The sentences for the source built, filled from the quotes the file gave (D24: a quote is the file's own words,
    checked at build; an undated source never shows a date the index did not read)."""
    base = WORDS_STREETS[kind]
    quotes = facts.get("quotes", {})
    if kind == "msl":
        filled = {"convenience": quotes.get("convenience", LIBRARY_CONVENIENCE),
                  "disclaimer": quotes.get("disclaimer", LIBRARY_DISCLAIMER)}
        attribution = (base["attribution"].format(pubdate=facts["pubdate"], **filled) if facts.get("pubdate")
                       else base["attribution_undated"].format(**filled))
        caveat = base["caveat"].format(**filled)
    else:
        filled = {"acknowledgement": quotes.get("acknowledgement", TIGER_ACK),
                  "trademark": quotes.get("trademark", TIGER_TRADEMARK),
                  "accuracy": quotes.get("accuracy", TIGER_ACCURACY)}
        attribution = base["attribution"].format(**filled)
        caveat = base["caveat"].format(**filled)
    return {"legend": base["legend"], "attribution": attribution, "caveat": caveat,
            "unavailable": base["unavailable"]}


# ---------------------------------------------------------------- downloads (D20, D24: name, size and Last-Modified)

def _fetcher():
    from . import sources
    return sources.Fetcher(timeout=120, attempts=3, pause=2.0)


def _ledger_line(ledger, url, method, status, nbytes, state, error=None):
    if ledger is None:
        return
    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"at": _utc_now(), "method": method, "url": url, "status": status, "bytes": nbytes,
            "cache": state, "error": error}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def download_one(cache_dir, name: str, url: str, *, fetcher=None, ledger=None) -> tuple[Path, dict]:
    """Return (path, facts) for one source file. A HEAD gives the size and Last-Modified. A cached copy is used only
    when its meta file matches (name, size, Last-Modified); otherwise the file is fetched once through the site's HTTP
    helper and its meta file is written. A failed request or a file of another size is SourceUnavailable with the plain
    reason."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or _fetcher()
    dest = cache / name
    meta_path = cache / (name + ".meta.json")
    try:
        head = fetcher.s.head(url, allow_redirects=True, timeout=fetcher.timeout)
        status = head.status_code
        size = int(head.headers.get("Content-Length", "-1"))
        modified = head.headers.get("Last-Modified")
    except Exception as exc:                 # the network: a failed HEAD is the source not answering (D20)
        _ledger_line(ledger, url, "HEAD", None, None, "failed", type(exc).__name__)
        raise _unavailable(f"the download of {name} did not answer ({type(exc).__name__})") from None
    _ledger_line(ledger, url, "HEAD", status, size if size >= 0 else None, "checked")
    if status != 200:
        raise _unavailable(f"the download of {name} answered HTTP {status}")
    info = {"name": name, "url": url, "server_bytes": size if size >= 0 else None, "last_modified": modified}
    if dest.is_file():
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        if meta:
            if meta.get("name") == name and meta.get("bytes") == dest.stat().st_size and \
                    (size < 0 or meta.get("size") == size) and meta.get("last_modified") == modified:
                _ledger_line(ledger, url, "CACHE", None, dest.stat().st_size, "hit")
                info.update(cache="hit", bytes=dest.stat().st_size, sha256=_sha256_file(dest))
                return dest, info
    try:
        response = fetcher.binary(url)
    except Exception as exc:                 # a fetcher that raises: the source did not answer (D36)
        _ledger_line(ledger, url, "GET", None, None, "failed", type(exc).__name__)
        raise _unavailable(f"the download of {name} failed ({type(exc).__name__})") from None
    data, error = response if isinstance(response, tuple) else (response, None)
    if data is None:
        _ledger_line(ledger, url, "GET", None, None, "failed", error)
        raise _unavailable(f"the download of {name} failed ({error or 'no data'})")
    if size >= 0 and len(data) != size:
        _ledger_line(ledger, url, "GET", 200, len(data), "failed", "size")
        raise _unavailable(f"the download of {name} is not the size the server gave")
    if data[:2] != b"PK":
        _ledger_line(ledger, url, "GET", 200, len(data), "failed", "not a zip")
        raise _unavailable(f"the download of {name} is not a zip file")
    _write_atomic(dest, data)
    digest = _sha256(data)
    _write_atomic(meta_path, _compact({"name": name, "url": url, "bytes": len(data),
                                       "size": size if size >= 0 else None, "last_modified": modified,
                                       "sha256": digest, "fetched": _utc_now()}))
    _ledger_line(ledger, url, "GET", 200, len(data), "fetched")
    info.update(cache="fetched", bytes=len(data), sha256=digest)
    return dest, info


# ---------------------------------------------------------------- the readers (D25 Library, D16 TIGER)

class Network:
    """The vehicular features of one source, ready to clean: every vertex of every kept part in the source's metric
    projection, the part table (feature id, first vertex, vertex count) and the feature table (class rank, name id,
    county id). Features are numbered in file order; a lower number wins a concurrency tie (the earlier line stays)."""

    def __init__(self, kind: str, crs: str, geo: str, facts: dict):
        self.kind = kind
        self.crs = crs
        self.geo = geo
        self.facts = facts
        self.xs: list = []                  # per-part numpy arrays (metres), concatenated later
        self.ys: list = []
        self.part_fid: list = []
        self.part_n: list = []
        self.fid_rank: list = []            # index into CLASS_ORDER
        self.fid_name: list = []            # display name or None (unnamed)
        self.fid_county: list = []          # county name ("" when blank)
        self.fid_surface: list = []
        self.counts: Counter = Counter()
        self.left_out: Counter = Counter()
        self.left_out_by_county: dict = defaultdict(Counter)
        self.raw_blank: int = 0
        self.raw_placeholder: Counter = Counter()
        self.parts_single_point: int = 0
        self.vertices_read: int = 0          # every vertex of every part of the kept features, before cleaning
        self.segments_read: int = 0
        self.arrays: dict = {}

    def keep_feature(self, cls: str, name: str | None, county: str, surface: str = "") -> int:
        fid = len(self.fid_rank)
        self.fid_rank.append(CLASS_ORDER.index(cls))
        self.fid_name.append(name)
        self.fid_county.append(county)
        self.fid_surface.append(surface)
        return fid

    def add_part(self, fid: int, x, y) -> None:
        n = len(x)
        if n < 2:
            self.parts_single_point += 1
            return
        self.xs.append(x)
        self.ys.append(y)
        self.part_fid.append(fid)
        self.part_n.append(n)
        self.vertices_read += n
        self.segments_read += n - 1


def _member(zf, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        raise _unavailable(f"the file has no {name} member") from None


def _check_header(head: bytes, spec, header_bytes: int, record_bytes: int, label: str) -> int:
    """The DBF header against the spec: names, types and lengths, the header length and the record length (D36)."""
    if len(head) < 32:
        raise _unavailable(f"the {label} table header is short")
    nrec, hlen, rlen = struct.unpack_from("<IHH", head, 4)
    fields, pos = [], 32
    while pos < len(head) and head[pos:pos + 1] != b"\r":
        desc = head[pos:pos + 32]
        if len(desc) < 32:
            raise _unavailable(f"the {label} table header is short")
        fields.append((desc[:11].split(b"\x00", 1)[0].decode("ascii", errors="replace"), chr(desc[11]), desc[16]))
        pos += 32
    if [tuple(f) for f in fields] != [tuple(s) for s in spec]:
        raise _unavailable(f"the {label} table's field list (names, types and lengths) is not the one this build "
                           "reads")
    if hlen != header_bytes or rlen != record_bytes:
        raise _unavailable(f"the {label} table's header or record length is not the one this build reads")
    return nrec


def _offsets(spec) -> dict:
    position, offsets = 1, {}                   # byte 0 of a record is the deletion flag
    for name, _kind, length in spec:
        offsets[name] = (position, position + length)
        position += length
    return offsets


def _shape_parts(shp: bytes, pos: int) -> tuple[int, list, list]:
    """(shape type, part starts, points) of the polyline record whose header starts at pos."""
    np = _np()
    content = pos + 8
    stype = struct.unpack_from("<i", shp, content)[0]
    if stype == 0:
        return 0, [], np.zeros((0, 2))
    if stype != 3:
        raise _unavailable("the road file holds shapes other than polylines")
    numparts, numpoints = struct.unpack_from("<ii", shp, content + 36)
    if numparts < 1 or numpoints < 0:
        raise _unavailable("a road record has no parts")
    parts = np.frombuffer(shp, dtype="<i4", count=numparts, offset=content + 44)
    pts = np.frombuffer(shp, dtype="<f8", count=2 * numpoints, offset=content + 44 + 4 * numparts).reshape(-1, 2)
    starts = [int(v) for v in parts]
    if starts[0] != 0 or any(b <= a for a, b in zip(starts, starts[1:])) or (numpoints and starts[-1] >= numpoints):
        raise _unavailable("a road record's parts are not in order")
    return 3, starts, pts


def _parse_shapes(shp: bytes, shx: bytes, label: str):
    """Validate the shapefile header and its index against the record count; yields (record index, record start)."""
    if len(shp) < 100 or struct.unpack_from(">i", shp, 0)[0] != 9994:
        raise _unavailable(f"the {label} file is not a shapefile")
    if struct.unpack_from(">i", shp, 24)[0] * 2 != len(shp):
        raise _unavailable(f"the {label} shapefile's length does not match its header")
    if struct.unpack_from("<i", shp, 32)[0] != 3:
        raise _unavailable(f"the {label} file holds shapes other than polylines")
    return (len(shx) - 100) // 8


def read_library(zip_path) -> Network:
    """The Library's Transportation Framework (D25): the validated zip, the vehicular features with their names,
    classes and counties (the allow-list only), in EPSG:6514 metres. Raises SourceUnavailable on any mismatch."""
    np = _np()
    path = Path(zip_path)
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        raise _unavailable("the roads download is not a zip file") from None
    with zf:
        prj = _member(zf, LIBRARY_PRJ_MEMBER).decode("ascii", errors="replace")
        if LIBRARY_PRJ not in prj:
            raise _unavailable(f"the file's projection is not {LIBRARY_PRJ}")
        meta_bytes = _member(zf, LIBRARY_META)
        readme = _member(zf, LIBRARY_README).decode("utf-8", errors="replace")
        shp = _member(zf, LIBRARY_SHP)
        shx = _member(zf, LIBRARY_SHX)
        facts = library_facts(path, meta_bytes, readme)
        nrec_shx = _parse_shapes(shp, shx, "road")
        with zf.open(LIBRARY_DBF) as stream:
            head = _read_exact(stream, 32)
            hlen = struct.unpack_from("<H", head, 8)[0] if len(head) >= 10 else 0
            if hlen < 33 or hlen > 32 * 256:
                raise _unavailable("the table header length is not one this build reads")
            nrec = _check_header(head + _read_exact(stream, hlen - 32), LIBRARY_DBF_SPEC, LIBRARY_HEADER_BYTES,
                                 LIBRARY_RECORD_BYTES, "road")
            if nrec != nrec_shx:
                raise _unavailable("the road table and the shapefile index do not hold the same number of records")
            net = Network("msl", LIBRARY_CRS, LIBRARY_LONLAT, facts)
            offsets = _offsets(LIBRARY_DBF_SPEC)
            slices = [(name,) + offsets[name] for name in LIBRARY_ALLOWED]
            if set(LIBRARY_ALLOWED) & set(LIBRARY_NEVER):
                raise _unavailable("the reader's field list includes an owner or identifier field")
            pos = 100
            for i in range(nrec):
                rec = _read_exact(stream, LIBRARY_RECORD_BYTES)
                if len(rec) != LIBRARY_RECORD_BYTES:
                    raise _unavailable("the road table ends before its last record")
                stype, starts, pts = _shape_parts(shp, pos)
                rec_words = struct.unpack_from(">i", shp, pos + 4)[0]
                pos += 8 + 2 * rec_words
                if rec[0:1] == b"*":
                    net.counts["deleted records"] += 1
                    continue
                net.counts["records"] += 1
                if stype == 0:
                    net.left_out["no geometry"] += 1
                    continue
                fields = {name: _text(rec[a:b]) for name, a, b in slices}
                cls, reason = classify_library(fields["RoadClass"], fields)
                county = fields["County_L"] or "(blank)"
                if cls is None:
                    net.left_out[reason or "(blank)"] += 1
                    net.left_out_by_county[county][reason or "(blank)"] += 1
                    continue
                name = library_name(fields)
                if not name:
                    net.raw_blank += 1
                    name = None
                elif is_placeholder(name):
                    net.raw_placeholder[name] += 1
                    name = None
                fid = net.keep_feature(cls, name, county, fields["SurfaceTyp"] or "(blank)")
                ends = starts[1:] + [len(pts)]
                for a, b in zip(starts, ends):
                    net.add_part(fid, pts[a:b, 0], pts[a:b, 1])
                net.counts["kept features"] += 1
            if pos != len(shp):
                raise _unavailable("the road shapefile holds bytes after its last record")
    return _finish(net, np)


def library_facts(path: Path, meta_bytes: bytes, readme: str) -> dict:
    """The file's facts from its own members: the export date (_ReadMe.txt), the metadata's pubdate and its terms,
    quoted and checked (D8, D24, D36)."""
    match = re.search(r"exported[^.]*?\bon\s+(\d{8})", readme, re.S)
    if not match:
        raise _unavailable("the file's README gives no export date")
    export = match.group(1)
    export_date = f"{export[0:4]}-{export[4:6]}-{export[6:8]}"
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
    useconst = first("useconst")
    if not (_quoted_ok(useconst, LIBRARY_CONVENIENCE) and _quoted_ok(useconst, LIBRARY_DISCLAIMER)):
        raise _unavailable("the terms sentences in the file's metadata are not the ones the site quotes")
    return {
        "kind": "msl",
        "name": "Montana State Library Transportation Framework",
        "url": LIBRARY_URL,
        "file": LIBRARY_ZIP_NAME,
        "bytes": path.stat().st_size,
        "export_date": export_date,
        "pubdate": pubdate,
        "accconst": first("accconst"),
        "useconst_sentences": [LIBRARY_CONVENIENCE, LIBRARY_DISCLAIMER],
        "purpose": first("purpose"),
        "projection": LIBRARY_PRJ,
        "dbf_fields": len(LIBRARY_DBF_SPEC),
        "fields_read": list(LIBRARY_ALLOWED),
        "quotes": {"convenience": LIBRARY_CONVENIENCE, "disclaimer": LIBRARY_DISCLAIMER},
    }


def _read_exact(stream, count: int) -> bytes:
    out = bytearray()
    while len(out) < count:
        chunk = stream.read(count - len(out))
        if not chunk:
            break
        out.extend(chunk)
    return bytes(out)


def read_tiger(paths, *, strict: bool = True) -> Network:
    """The Census county road files (D16): each zip is validated (the field list, the GCS_North_American_1983 datum
    in degrees, the polylines), and its vehicular features are kept with their FULLNAME. Coordinates are NAD83
    degrees, projected to NAD83 / Montana metres (EPSG:32100) for the cleaning. strict requires all 56 counties
    (the tests read two synthetic counties with strict False)."""
    np = _np()
    net = Network("tiger", TIGER_CRS, TIGER_GEO, {})
    editions = set()
    per_file = []
    iso_checked = []
    for path in sorted(paths, key=lambda p: Path(p).name):
        path = Path(path)
        match = re.fullmatch(r"tl_(\d{4})_(\d{5})_roads\.zip", path.name)
        if not match or match.group(2) not in TIGER_FIPS:
            raise _unavailable(f"{path.name} is not a Montana county road file")
        editions.add(match.group(1))
        fips = match.group(2)
        county = f"{TIGER_FIPS[fips]} County"
        try:
            zf = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile):
            raise _unavailable(f"{path.name} is not a zip file") from None
        with zf:
            base = path.name[:-len(".zip")]
            prj = _member(zf, base + ".prj").decode("ascii", errors="replace")
            if "GCS_North_American_1983" not in prj or "PROJCS" in prj:
                raise _unavailable(f"{path.name} is not in NAD83 degrees")
            iso = _member(zf, base + ".shp.iso.xml").decode("utf-8", errors="replace")
            if not (_quoted_ok(iso, TIGER_ACK) and _quoted_ok(iso, TIGER_TRADEMARK) and _quoted_ok(iso, TIGER_ACCURACY)):
                raise _unavailable(f"{path.name}'s metadata does not carry the Census terms the site quotes")
            iso_checked.append(path.name)
            shp = _member(zf, base + ".shp")
            shx = _member(zf, base + ".shx")
            dbf = _member(zf, base + ".dbf")
        nrec_shx = _parse_shapes(shp, shx, path.name)
        nrec = _check_header(dbf[:TIGER_HEADER_BYTES] if len(dbf) >= TIGER_HEADER_BYTES else dbf, TIGER_DBF_SPEC,
                             TIGER_HEADER_BYTES, TIGER_RECORD_BYTES, path.name)
        if nrec != nrec_shx:
            raise _unavailable(f"{path.name}: the table and the shapefile index do not hold the same number of records")
        offsets = _offsets(TIGER_DBF_SPEC)
        slices = [(name,) + offsets[name] for name in TIGER_ALLOWED]
        pos = 100
        file_counts = Counter()
        for i in range(nrec):
            start = TIGER_HEADER_BYTES + i * TIGER_RECORD_BYTES
            rec = dbf[start:start + TIGER_RECORD_BYTES]
            if len(rec) != TIGER_RECORD_BYTES:
                raise _unavailable(f"{path.name}: the table ends before its last record")
            stype, starts, pts = _shape_parts(shp, pos)
            rec_words = struct.unpack_from(">i", shp, pos + 4)[0]
            pos += 8 + 2 * rec_words
            if rec[0:1] == b"*":
                file_counts["deleted records"] += 1
                continue
            file_counts["records"] += 1
            if stype == 0:
                net.left_out["no geometry"] += 1
                continue
            fields = {name: _text(rec[a:b]) for name, a, b in slices}
            cls, reason = classify_tiger(fields["MTFCC"])
            if cls is None:
                net.left_out[f"MTFCC {reason}"] += 1
                net.left_out_by_county[county][f"MTFCC {reason}"] += 1
                continue
            raw = fields["FULLNAME"]
            if not raw:
                net.raw_blank += 1
                name = None
            elif is_placeholder(raw):
                net.raw_placeholder[raw] += 1
                name = None
            else:
                name = expand_name(raw)
            fid = net.keep_feature(cls, name, county, "")
            ends = starts[1:] + [len(pts)]
            for a, b in zip(starts, ends):
                lon = pts[a:b, 0]
                lat = pts[a:b, 1]
                x, y = _forward(TIGER_GEO, TIGER_CRS, lon, lat)
                net.add_part(fid, x, y)
            net.counts["kept features"] += 1
        if pos != len(shp):
            raise _unavailable(f"{path.name}: the shapefile holds bytes after its last record")
        for key, value in file_counts.items():
            net.counts[key] += value
        per_file.append({"file": path.name, "county": county, "records": file_counts["records"]})
    if len(editions) != 1:
        raise _unavailable("the county files are not one TIGER edition")
    if strict and len(per_file) != len(TIGER_FIPS):
        raise _unavailable(f"the county files are {len(per_file)} of the 56 Montana counties")
    net.facts = {"kind": "tiger", "edition": editions.pop(), "files": per_file, "iso_checked": iso_checked,
                 "quotes": {"acknowledgement": TIGER_ACK, "trademark": TIGER_TRADEMARK, "accuracy": TIGER_ACCURACY},
                 "name": "U.S. Census Bureau TIGER/Line All Roads, county files"}
    return _finish(net, np)


def _forward(src: str, dst: str, lon, lat):
    transformer = _transformer(src, dst)
    x, y = transformer.transform(lon, lat)
    return _np().asarray(x, dtype="float64"), _np().asarray(y, dtype="float64")


_TRANSFORMERS: dict = {}


def _transformer(src: str, dst: str):
    key = (src, dst)
    if key not in _TRANSFORMERS:
        try:
            from pyproj import Transformer      # lazy: the job installs pyproj~=3.8 (D19)
        except ImportError:
            raise _unavailable("the projection library is not installed") from None
        _TRANSFORMERS[key] = Transformer.from_crs(src, dst, always_xy=True)
    return _TRANSFORMERS[key]


def pyproj_version() -> str:
    import pyproj
    return pyproj.__version__


def _finish(net: Network, np) -> Network:
    """Concatenate the kept parts' vertices into the network's arrays (in the order of the part table)."""
    if net.xs:
        net.arrays = {"x": np.concatenate(net.xs), "y": np.concatenate(net.ys)}
    else:
        net.arrays = {"x": np.zeros(0), "y": np.zeros(0)}
    net.xs, net.ys = [], []
    n = np.asarray(net.part_n, dtype=np.int64)
    net.arrays["part_n"] = n
    net.arrays["part_start"] = np.concatenate(([0], np.cumsum(n)[:-1])) if len(n) else np.zeros(0, dtype=np.int64)
    net.arrays["part_fid"] = np.asarray(net.part_fid, dtype=np.int64)
    net.arrays["fid_rank"] = np.asarray(net.fid_rank, dtype=np.int64)
    return net


# ---------------------------------------------------------------- cleaning: pieces, concurrency, names (D16, D16a)

def _chunks(net: Network, np):
    """Split every segment of every part into chunks of at most CHUNK_M metres. Returns the chunk arrays and the
    count of zero-length segments left out."""
    x, y = net.arrays["x"], net.arrays["y"]
    part_start, part_n, part_fid = net.arrays["part_start"], net.arrays["part_n"], net.arrays["part_fid"]
    nseg = part_n - 1
    seg_part = np.repeat(np.arange(len(part_n)), nseg)
    within = np.arange(int(nseg.sum())) - np.repeat(np.cumsum(nseg) - nseg, nseg)
    v0 = part_start[seg_part] + within
    v1 = v0 + 1
    dx = x[v1] - x[v0]
    dy = y[v1] - y[v0]
    length = np.hypot(dx, dy)
    keep = length > 0.0
    zero = int((~keep).sum())
    v0, v1, dx, dy, length, seg_part = v0[keep], v1[keep], dx[keep], dy[keep], length[keep], seg_part[keep]
    k = np.maximum(1, np.ceil(length / CHUNK_M).astype(np.int64))
    total = int(k.sum())
    chunk_seg = np.repeat(np.arange(len(k)), k)
    j = np.arange(total) - np.repeat(np.cumsum(k) - k, k)
    kk = k[chunk_seg]
    last = j + 1 == kk
    t0 = j / kk
    t1 = (j + 1) / kk
    x0 = x[v0[chunk_seg]] + t0 * dx[chunk_seg]
    y0 = y[v0[chunk_seg]] + t0 * dy[chunk_seg]
    x1 = np.where(last, x[v1[chunk_seg]], x[v0[chunk_seg]] + t1 * dx[chunk_seg])
    y1 = np.where(last, y[v1[chunk_seg]], y[v0[chunk_seg]] + t1 * dy[chunk_seg])
    x0 = np.where(j == 0, x[v0[chunk_seg]], x0)
    y0 = np.where(j == 0, y[v0[chunk_seg]], y0)
    chunks = {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "part": seg_part[chunk_seg],
              "fid": part_fid[seg_part[chunk_seg]]}
    return chunks, zero


def _segment_distance(px, py, ax, ay, bx, by):
    np = _np()
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(length2 > 0, ((px - ax) * dx + (py - ay) * dy) / length2, 0.0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _cover(chunks, np):
    """For every chunk, the lowest-numbered chunk of an earlier feature that covers each of its three samples (ends and
    middle) within COVER_M and parallel within PARALLEL_DEG; -1 when no chunk does. Returns (best per sample, covered)."""
    x0, y0, x1, y1, fid = chunks["x0"], chunks["y0"], chunks["x1"], chunks["y1"], chunks["fid"]
    count = len(x0)
    ux, uy = x1 - x0, y1 - y0
    ulen = np.hypot(ux, uy)
    samples = 3 * count
    sx = np.empty(samples)
    sy = np.empty(samples)
    sx[0::3], sy[0::3] = x0, y0
    sx[1::3], sy[1::3] = (x0 + x1) / 2, (y0 + y1) / 2
    sx[2::3], sy[2::3] = x1, y1
    lo_x = np.minimum(x0, x1) - COVER_M
    hi_x = np.maximum(x0, x1) + COVER_M
    lo_y = np.minimum(y0, y1) - COVER_M
    hi_y = np.maximum(y0, y1) + COVER_M
    ix0 = np.floor(lo_x / GRID_M).astype(np.int64)
    ix1 = np.floor(hi_x / GRID_M).astype(np.int64)
    iy0 = np.floor(lo_y / GRID_M).astype(np.int64)
    iy1 = np.floor(hi_y / GRID_M).astype(np.int64)
    nx = ix1 - ix0 + 1
    ny = iy1 - iy0 + 1
    cells = nx * ny
    entries = int(cells.sum())
    owner = np.repeat(np.arange(count), cells)
    local = np.arange(entries) - np.repeat(np.cumsum(cells) - cells, cells)
    nxr = nx[owner]
    cx = ix0[owner] + local % nxr
    cy = iy0[owner] + local // nxr
    offset = 1 << 20
    big = 1 << 22
    key = (cx + offset) * big + (cy + offset)
    order = np.argsort(key, kind="stable")
    sorted_keys = key[order]
    sorted_chunks = owner[order]
    del owner, local, nxr, cx, cy, key, order
    qx = np.floor(sx / GRID_M).astype(np.int64)
    qy = np.floor(sy / GRID_M).astype(np.int64)
    qkey = (qx + offset) * big + (qy + offset)
    lo = np.searchsorted(sorted_keys, qkey, side="left")
    hi = np.searchsorted(sorted_keys, qkey, side="right")
    cnt = hi - lo
    best = np.full(samples, count, dtype=np.int64)
    csum = np.cumsum(cnt)
    cos_limit = math.cos(math.radians(PARALLEL_DEG))
    start = 0
    limit = 20_000_000
    while start < samples:
        base = int(csum[start - 1]) if start else 0
        end = int(np.searchsorted(csum, base + limit, side="right"))
        end = max(end, start + 1)
        c = cnt[start:end]
        total = int(c.sum())
        if total:
            sid = np.repeat(np.arange(start, end), c)
            offs = np.arange(total) - np.repeat(np.cumsum(c) - c, c)
            cand = sorted_chunks[np.repeat(lo[start:end], c) + offs]
            tid = sid // 3
            ok = fid[cand] < fid[tid]
            ok &= cand != tid
            ok &= ulen[tid] >= MIN_DIR_M
            ok &= ulen[cand] >= MIN_DIR_M
            sid, cand, tid = sid[ok], cand[ok], tid[ok]
            dot = np.abs(ux[tid] * ux[cand] + uy[tid] * uy[cand])
            par = dot >= cos_limit * ulen[tid] * ulen[cand]
            sid, cand = sid[par], cand[par]
            d = _segment_distance(sx[sid], sy[sid], x0[cand], y0[cand], x1[cand], y1[cand])
            near = d <= COVER_M
            if near.any():
                np.minimum.at(best, sid[near], cand[near])
        start = end
    covered = (best[0::3] < count) & (best[1::3] < count) & (best[2::3] < count)
    return best, covered


def _roots(best, covered, count, np):
    parent = np.arange(count, dtype=np.int64)
    parent[covered] = best[0::3][covered]
    while True:
        jump = parent[parent]
        if np.array_equal(jump, parent):
            break
        parent = jump
    return parent


def clean_network(net: Network) -> dict:
    """The cleaning of one source (D16, D16a): chunks, concurrency, roots, names and classes, the lines as pieces and
    their simplified coordinates. Returns the pieces (in lon/lat degrees and metres) and the cleaning counts."""
    np = _np()
    started = time.time()
    counts = Counter(net.counts)
    counts.update({"left out " + k: v for k, v in net.left_out.items()})
    if not len(net.arrays["part_n"]):
        return {"pieces": [], "counts": dict(counts), "names": [], "county_names": []}
    chunks, zero = _chunks(net, np)
    counts["zero-length segments"] = zero
    count = len(chunks["x0"])
    counts["chunks"] = count
    best, covered = _cover(chunks, np)
    covered_n = int(covered.sum())
    counts["covered chunks"] = covered_n
    fid = chunks["fid"]
    per_feature = np.bincount(fid, minlength=len(net.fid_name))
    per_feature_covered = np.bincount(fid, weights=covered.astype(np.float64), minlength=len(net.fid_name))
    counts["features with a covered piece"] = int(((per_feature_covered > 0) & (per_feature > 0)).sum())
    counts["features fully covered by earlier features"] = int(((per_feature_covered == per_feature)
                                                                & (per_feature > 0)).sum())
    counts["vertices before cleaning (kept parts)"] = int(net.vertices_read)
    counts["segments before cleaning (kept parts)"] = int(net.segments_read)
    counts["parts before cleaning"] = int(len(net.arrays["part_n"]))
    counts["parts with one point (left out)"] = int(net.parts_single_point)
    counts["blank names (kept features)"] = int(net.raw_blank)
    counts["placeholder names (kept features)"] = int(sum(net.raw_placeholder.values()))
    counts["placeholder names by value (kept features)"] = dict(net.raw_placeholder)
    parent = _roots(best, covered, count, np)
    root_of_chunk = parent
    # the names and the most prominent class of each root: its own feature and the features it covers
    fid_rank = net.arrays["fid_rank"]
    name_index: dict = {}
    names: list = []
    fid_name_id = np.full(len(net.fid_name), -1, dtype=np.int64)
    for i, label in enumerate(net.fid_name):
        if label is not None:
            if label not in name_index:
                name_index[label] = len(names)
                names.append(label)
            fid_name_id[i] = name_index[label]
    fid_county_list = sorted(set(net.fid_county))
    county_index = {name: i for i, name in enumerate(fid_county_list)}
    fid_county_id = np.asarray([county_index[c] for c in net.fid_county], dtype=np.int64)
    rank = fid_rank[fid]
    best_rank = rank.copy()
    cov_idx = np.flatnonzero(covered)
    absorbed_rows = []
    if cov_idx.size:
        for k in range(3):
            target = root_of_chunk[best[k::3][cov_idx]]
            absorbed_rows.append((target, cov_idx))
        for target, members in absorbed_rows:
            np.minimum.at(best_rank, target, rank[members])
    # the name set of each root: the root's own name plus the names of the chunks that it covers
    extra = {}
    pairs_root = []
    pairs_name = []
    for target, members in absorbed_rows:
        pairs_root.append(target)
        pairs_name.append(fid_name_id[fid[members]])
    if pairs_root:
        proot = np.concatenate(pairs_root)
        pname = np.concatenate(pairs_name)
        keep = pname >= 0
        proot, pname = proot[keep], pname[keep]
        own = fid_name_id[fid[proot]]
        differs = pname != own
        proot, pname = proot[differs], pname[differs]
        for r, nm in sorted(set(zip(proot.tolist(), pname.tolist()))):
            extra.setdefault(r, set()).add(nm)
    roots = np.flatnonzero(parent == np.arange(count))
    set_key_of: dict = {}
    set_names: list = []
    key = np.full(count, -1, dtype=np.int64)
    own_name = fid_name_id[fid]
    key[roots] = own_name[roots]
    for r, extra_names in extra.items():
        base_name = int(own_name[r])
        members = set(extra_names) | ({base_name} if base_name >= 0 else set())
        tup = tuple(sorted(members))
        if tup not in set_key_of:
            set_key_of[tup] = len(names) + len(set_names)
            set_names.append(tup)
        key[r] = set_key_of[tup]
    counts["chunk roots that absorbed another name"] = len(extra)
    # pieces: the kept chunks, in order, grouped where they are contiguous in one part with one class and name set
    kept = np.flatnonzero(parent == np.arange(count))
    part = chunks["part"]
    rank_of_root = best_rank
    if kept.size == 0:
        return {"pieces": [], "counts": dict(counts), "names": names, "county_names": fid_county_list}
    brk = np.ones(kept.size, dtype=bool)
    brk[1:] = (kept[1:] != kept[:-1] + 1) | (part[kept[1:]] != part[kept[:-1]]) | \
        (key[kept[1:]] != key[kept[:-1]]) | (rank_of_root[kept[1:]] != rank_of_root[kept[:-1]])
    starts = np.flatnonzero(brk)
    ends = np.append(starts[1:], kept.size) - 1
    first_chunk = kept[starts]
    last_chunk = kept[ends]
    x0, y0, x1, y1 = chunks["x0"], chunks["y0"], chunks["x1"], chunks["y1"]
    pieces_xy = []
    piece_meta = []
    for f, l, st in zip(first_chunk.tolist(), last_chunk.tolist(), starts.tolist()):
        px = np.concatenate(([x0[f]], x1[f:l + 1]))
        py = np.concatenate(([y0[f]], y1[f:l + 1]))
        pieces_xy.append((px, py))
        piece_meta.append((int(key[f]), int(rank_of_root[f]), int(fid[f])))
    counts["lines before simplification"] = len(pieces_xy)
    counts["vertices after cleaning"] = int(sum(len(p[0]) for p in pieces_xy))
    counts["segments after cleaning"] = int(sum(len(p[0]) - 1 for p in pieces_xy))
    counts["chunks drawn"] = int(kept.size)
    # Douglas-Peucker at DP_TOL_M in metres, measured to the stored (5-decimal) positions; the kept points keep their
    # source positions until the rounding below
    simplified = []
    for (px, py) in pieces_xy:
        sx, sy = _stored_metres(net, px, py, np)
        keep_mask = _dp_keep(px, py, DP_TOL_M, np, sx, sy)
        simplified.append((px[keep_mask], py[keep_mask]))
    counts["vertices after simplification"] = int(sum(len(p[0]) for p in simplified))
    counts["segments after simplification"] = int(sum(len(p[0]) - 1 for p in simplified))
    # coordinates: one projection call for all kept points, then back to lon/lat rounded to 5 decimals
    allx = np.concatenate([p[0] for p in simplified]) if simplified else np.zeros(0)
    ally = np.concatenate([p[1] for p in simplified]) if simplified else np.zeros(0)
    dst = LIBRARY_LONLAT if net.kind == "msl" else TIGER_GEO
    lon, lat = _forward_inverse(net.crs, dst, allx, ally)
    lon5 = np.rint(lon * SCALE).astype(np.int64)
    lat5 = np.rint(lat * SCALE).astype(np.int64)
    pieces = []
    cursor = 0
    name_cache: dict = {}
    dropped_short = 0
    joined = 0
    for (px, py), (k_key, k_rank, k_fid) in zip(simplified, piece_meta):
        n = len(px)
        xs_i = lon5[cursor:cursor + n]
        ys_i = lat5[cursor:cursor + n]
        cursor += n
        if n < 2:
            dropped_short += 1
            continue
        # drop consecutive duplicates after rounding to 5 decimals
        same = np.concatenate(([False], (xs_i[1:] == xs_i[:-1]) & (ys_i[1:] == ys_i[:-1])))
        if same.any():
            xs_i, ys_i = xs_i[~same], ys_i[~same]
        if len(xs_i) < 2:
            dropped_short += 1
            continue
        if k_key in name_cache:
            name_label = name_cache[k_key]
        else:
            if k_key < 0:
                name_label = None
            elif k_key < len(names):
                name_label = names[k_key]
            else:
                tup = set_names[k_key - len(names)]
                name_label = " / ".join(sorted((names[t] for t in tup), key=str.casefold))
                joined += 1
            name_cache[k_key] = name_label
        length = float(np.hypot(np.diff(px), np.diff(py)).sum()) if n > 1 else 0.0
        pieces.append({"cls": CLASS_ORDER[k_rank], "name": name_label, "lon5": xs_i, "lat5": ys_i,
                       "county": int(fid_county_id[k_fid]), "metres": length, "fid": k_fid})
    counts["lines drawn"] = len(pieces)
    counts["lines dropped (under two points)"] = dropped_short
    counts["lines with names joined"] = joined
    counts["vertices drawn"] = int(sum(len(p["lon5"]) for p in pieces))
    counts["segments drawn"] = int(sum(len(p["lon5"]) - 1 for p in pieces))
    counts["cleaning seconds"] = round(time.time() - started, 1)
    final_names = names + [" / ".join(sorted((names[t] for t in tup), key=str.casefold)) for tup in set_names]
    return {"pieces": pieces, "counts": dict(counts), "names": final_names, "county_names": fid_county_list,
            "fid_county": net.fid_county, "fid_name": net.fid_name, "fid_rank": net.arrays["fid_rank"].tolist()}


def _forward_inverse(src: str, dst: str, x, y):
    transformer = _transformer(src, dst)
    lon, lat = transformer.transform(x, y)
    np = _np()
    return np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64")


def _stored_metres(net: Network, x, y, np):
    """The stored positions of x and y in metres: the build's own round trip, the lon/lat rounded to 5 decimals as the
    store keeps them (D14), projected back. The simplification measures against these positions."""
    dst = LIBRARY_LONLAT if net.kind == "msl" else TIGER_GEO
    lon, lat = _forward_inverse(net.crs, dst, x, y)
    return _forward_inverse(dst, net.crs, np.rint(lon * SCALE) / SCALE, np.rint(lat * SCALE) / SCALE)


def _dp_keep(xs, ys, tol: float, np, sx=None, sy=None):
    """Douglas-Peucker: the mask of the kept points of one polyline. Every removed point lies within tol of the kept
    polyline (measured to the segment that spans it, in the same metres). sx and sy are the stored positions of the
    points (default: the points themselves); each segment is measured between the stored positions of its two kept
    ends, so the stored line is the one that lies within tol of every point it replaces."""
    if sx is None:
        sx, sy = xs, ys
    n = len(xs)
    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        d = _segment_distance(xs[i + 1:j], ys[i + 1:j], sx[i], sy[i], sx[j], sy[j])
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m))
            stack.append((m, j))
    return keep


def max_deviation(xs, ys, keep) -> float:
    """The largest distance (metres) from a removed point to the kept polyline (the test and the verify use it)."""
    np = _np()
    kept_idx = np.flatnonzero(keep)
    worst = 0.0
    for a, b in zip(kept_idx[:-1], kept_idx[1:]):
        if b - a < 2:
            continue
        d = _segment_distance(xs[a + 1:b], ys[a + 1:b], xs[a], ys[a], xs[b], ys[b])
        if len(d):
            worst = max(worst, float(d.max()))
    return worst


# ---------------------------------------------------------------- shards (D26): lines clipped to tile and quarter boxes

def _clip_seg(x0, y0, x1, y1, box):
    west, south, east, north = box
    t0, t1 = 0.0, 1.0
    dx, dy = x1 - x0, y1 - y0
    for p, q in ((-dx, x0 - west), (dx, east - x0), (-dy, y0 - south), (dy, north - y0)):
        if p == 0:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return None
                if r < t1:
                    t1 = r
    ax = x0 + t0 * dx
    ay = y0 + t0 * dy
    bx = x0 + t1 * dx
    by = y0 + t1 * dy
    return (round(ax), round(ay)), (round(bx), round(by))


def clip_line(xs, ys, box):
    """The parts of a polyline (integer units) inside a box (west, south, east, north), as (xs, ys) lists."""
    west, south, east, north = box
    if all(west <= x <= east and south <= y <= north for x, y in zip(xs, ys)):
        return [(xs, ys)]
    out = []
    cx = cy = None
    for i in range(len(xs) - 1):
        seg = _clip_seg(xs[i], ys[i], xs[i + 1], ys[i + 1], box)
        if seg is None:
            if cx is not None and len(cx) > 1:
                out.append((cx, cy))
            cx = cy = None
            continue
        (ax, ay), (bx, by) = seg
        if cx is None:
            cx, cy = [ax, bx], [ay, by]
        elif (ax, ay) != (cx[-1], cy[-1]):
            if len(cx) > 1:
                out.append((cx, cy))
            cx, cy = [ax, bx], [ay, by]
        else:
            cx.append(bx)
            cy.append(by)
    if cx is not None and len(cx) > 1:
        out.append((cx, cy))
    return out


def _bbox(xs, ys):
    return min(xs), min(ys), max(xs), max(ys)


def _overlaps(bb, box) -> bool:
    west, south, east, north = box
    return bb[2] >= west and bb[0] <= east and bb[3] >= south and bb[1] <= north


def _shard_bytes(box, lines, names) -> bytes:
    local: dict = {}
    table: list = []
    rows = []
    for cls, nid, xs, ys in lines:
        if nid < 0:
            idx = -1
        else:
            idx = local.get(nid)
            if idx is None:
                idx = len(table)
                local[nid] = idx
                table.append(names[nid])
        rows.append([cls, idx, [[x / SCALE, y / SCALE] for x, y in zip(xs, ys)]])
    west, south, east, north = box
    doc = {"f": FORMAT, "b": [west / SCALE, south / SCALE, east / SCALE, north / SCALE], "n": len(rows),
           "names": table, "r": rows}
    return _compact(doc)


def _children(box):
    west, south, east, north = box
    mx = (west + east) / 2
    my = (south + north) / 2
    fx, cxh = math.floor(mx), math.ceil(mx)
    fy, cyh = math.floor(my), math.ceil(my)
    return {"0": (west, fy, cxh, north), "1": (fx, fy, east, north),
            "2": (west, south, cxh, cyh), "3": (fx, south, east, cyh)}


def write_shards(stage: Path, pieces: list, names: list) -> dict:
    """Write the shards of every B1 tile into stage (a folder of this build). Returns the measures: the shard names,
    the tiles, the split map, the depth histogram, the sizes and the largest shard."""
    tiles: dict = defaultdict(list)
    for index, piece in enumerate(pieces):
        xs, ys = piece["lon5"], piece["lat5"]
        minx, miny = int(xs.min()), int(ys.min())
        maxx, maxy = int(xs.max()), int(ys.max())
        tr0 = (ROW_TOP - maxy) // TILE_UNITS
        tr1 = (ROW_TOP - miny) // TILE_UNITS
        tc0 = (minx - COL_LEFT) // TILE_UNITS
        tc1 = (maxx - COL_LEFT) // TILE_UNITS
        for tr in range(int(tr0), int(tr1) + 1):
            for tc in range(int(tc0), int(tc1) + 1):
                tiles[(tr, tc)].append(index)
    leaves = []
    lines_total = 0
    for (tr, tc) in sorted(tiles):
        tile = hail.tile_name(tr, tc)
        west = COL_LEFT + tc * TILE_UNITS
        north = ROW_TOP - tr * TILE_UNITS
        box = (west, north - TILE_UNITS, west + TILE_UNITS, north)
        lines = []
        for index in tiles[(tr, tc)]:
            piece = pieces[index]
            xs, ys = piece["lon5"].tolist(), piece["lat5"].tolist()
            nid = piece["name_id"]
            for cx, cy in clip_line(xs, ys, box):
                lines.append((piece["cls"], nid, cx, cy))
        if lines:
            _emit(stage, tile, box, lines, 0, names, leaves)
            lines_total += len(lines)
    split: dict = defaultdict(list)
    for leaf in leaves:
        split[leaf["name"][:TILE_NAME_LEN]].append(leaf["name"])
    depths = Counter(leaf["depth"] for leaf in leaves)
    largest = max(leaves, key=lambda leaf: (leaf["bytes"], leaf["name"])) if leaves else None
    return {
        "shards": len(leaves),
        "names": sorted(leaf["name"] for leaf in leaves),
        "tiles": sorted({leaf["name"][:TILE_NAME_LEN] for leaf in leaves}),
        "split": {tile: sorted(names_) for tile, names_ in sorted(split.items()) if len(names_) > 1},
        "lines_in_leaves": sum(leaf["lines"] for leaf in leaves),
        "depths": {str(d): depths[d] for d in sorted(depths)},
        "bytes": sum(leaf["bytes"] for leaf in leaves),
        "lines_in_shards": sum(leaf["lines"] for leaf in leaves),
        "points_in_shards": sum(leaf["points"] for leaf in leaves),
        "largest": ({k: largest[k] for k in ("name", "bytes", "lines", "depth")} if largest else None),
        "over_limit": sorted(leaf["name"] for leaf in leaves if leaf["bytes"] > SHARD_LIMIT),
        "at_cap_over_limit": sorted(leaf["name"] for leaf in leaves if leaf["bytes"] > SHARD_LIMIT
                                    and leaf["depth"] >= DEPTH_CAP),
    }


def _emit(stage: Path, name: str, box, lines, depth: int, names, leaves) -> None:
    data = _shard_bytes(box, lines, names)
    if len(data) <= SHARD_LIMIT or depth >= DEPTH_CAP:
        (stage / f"{name}.json").write_bytes(data)
        leaves.append({"name": name, "depth": depth, "bytes": len(data), "lines": len(lines),
                       "points": sum(len(xs) for _c, _n, xs, _y in lines), "box": list(box)})
        return
    for digit, sub in _children(box).items():
        part = [(c, n, xs, ys) for c, n, xs, ys in lines if _overlaps(_bbox(xs, ys), sub)]
        clipped = []
        for c, n, xs, ys in part:
            for cx, cy in clip_line(xs, ys, sub):
                clipped.append((c, n, cx, cy))
        if clipped:
            _emit(stage, name + digit, sub, clipped, depth + 1, names, leaves)


# ---------------------------------------------------------------- the block, the store and the manifest

def _store_paths(root: Path) -> tuple[Path, Path, Path]:
    return root / "hail" / "index.json", root / "hail" / "manifest.json", root / "hail" / SHARD_DIR


def _check_store(root: Path) -> None:
    index_path, manifest_path, _r = _store_paths(root)
    if not index_path.is_file() or not manifest_path.is_file():
        raise StreetsError("the store has no hail index or manifest; build the hail store first")


def _wire(root: Path, block: dict) -> None:
    """Write the roads block into hail/index.json and the r/ entries and index hash into hail/manifest.json. Every
    other block and every other manifest entry (the B1, B2, address and building files) is kept as it is."""
    index_path, manifest_path, r_dir = _store_paths(root)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index[INDEX_KEY] = block
    index_bytes = _pretty(index)
    _write_atomic(index_path, index_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {rel: meta for rel, meta in manifest.get("files", {}).items()
             if not rel.startswith("hail/r/") and rel != "hail/index.json"}
    if r_dir.is_dir():
        for path in sorted(r_dir.rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                files[path.relative_to(root).as_posix()] = {"bytes": len(data), "sha256": _sha256(data)}
    files["hail/index.json"] = {"bytes": len(index_bytes), "sha256": _sha256(index_bytes)}
    manifest["files"] = {key: files[key] for key in sorted(files)}
    _write_atomic(manifest_path, _pretty(manifest))


def _remove_shards(root: Path) -> None:
    _i, _m, r_dir = _store_paths(root)
    if r_dir.exists():
        shutil.rmtree(r_dir)


def _clear_leftovers(root: Path) -> None:
    """Remove what an interrupted roads build left under hail/: its staging folder (hail/.r-stage) and the temp files of
    an interrupted write (hail/.streets-*). check_manifest refuses any file under hail/ that the manifest does not list,
    so none of them may stay (the address module's rule, D36)."""
    hail_dir = root / "hail"
    for path in [hail_dir / ".r-stage", *sorted(hail_dir.glob(".streets-*"))]:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.is_symlink() or path.exists():
            path.unlink()


def mark_unavailable(store_dir, reason: str, *, source: bool = True) -> dict:
    """Remove the r/ shards and any leftover of an interrupted build, and write the unavailable state with its reason
    into hail/index.json (D36, D39 pattern): the rest of the store is kept, and the job goes on."""
    root = Path(store_dir)
    _check_store(root)
    _remove_shards(root)
    _clear_leftovers(root)
    block = {"format": FORMAT, "state": "unavailable", "reason": reason, "source_unavailable": bool(source),
             "built_at": _utc_now(), "sample": False}
    _wire(root, block)
    return block


# ---------------------------------------------------------------- build

def _measures(net_counts: dict, shards: dict, source: dict, pieces: list, names: list, county_names: list,
              fid_county: list, fid_name: list, fid_rank: list, extra: dict) -> dict:
    counts = dict(net_counts)
    per_county: dict = {}
    named_length: Counter = Counter()
    total_length: Counter = Counter()
    for piece in pieces:
        county = county_names[piece["county"]] if piece["county"] < len(county_names) else "(blank)"
        total_length[county] += piece["metres"]
        if piece["name"] is not None:
            named_length[county] += piece["metres"]
    feature_total: Counter = Counter()
    feature_named: Counter = Counter()
    for fid, county in enumerate(fid_county):
        feature_total[county] += 1
        if fid_name[fid] is not None:
            feature_named[county] += 1
    for county in sorted(feature_total):
        per_county[county] = {
            "features": feature_total[county],
            "named_features": feature_named[county],
            "named_share_features": round(feature_named[county] / feature_total[county], 4),
            "named_share_length": round(named_length[county] / total_length[county], 4) if total_length[county] else None,
            "left_out": dict(extra.get("left_out_by_county", {}).get(county, {})),
        }
    total_feat = sum(feature_total.values())
    total_named = sum(feature_named.values())
    counts["named share features"] = round(total_named / total_feat, 4) if total_feat else None
    counts["named share length"] = round(sum(named_length.values()) / sum(total_length.values()), 4) \
        if sum(total_length.values()) else None
    counts["named features"] = total_named
    counts["unnamed features"] = total_feat - total_named
    counts["lines by class"] = dict(Counter(p["cls"] for p in pieces))
    counts["drawn metres"] = round(sum(total_length.values()), 1)
    return {"counts": counts, "per_county": per_county}


def _unique_lines_bytes(pieces, names) -> int:
    lines = [(p["cls"], -1 if p["name"] is None else p["name_id"], p["lon5"].tolist(), p["lat5"].tolist())
             for p in pieces]
    return len(_shard_bytes((0, 0, 1, 1), lines, names))


def build(store_dir, *, source: str = "msl", cache=None, url: str | None = None, ledger=None,
          zip_path=None, tiger_paths=None, tiger_edition: str = "2026", fetcher=None) -> dict:
    """Build the road shards and the roads block into store_dir (a store with hail/index.json and manifest.json).
    source is "msl" (the Library's zip; a download into cache when zip_path is None) or "tiger" (the 56 county files
    in tiger_paths, or downloaded into cache). Returns the roads block written to hail/index.json. A source that does
    not read leaves the roads "unavailable" in the index (SourceUnavailable) and the rest of the store as it was."""
    if source not in ("msl", "tiger"):
        raise StreetsError("the roads source must be msl or tiger")
    root = Path(store_dir)
    _check_store(root)
    started = time.time()
    cache_dir = Path(cache or "roads-cache")
    try:
        if source == "msl":
            if zip_path is None:
                path, info = download_one(cache_dir, LIBRARY_ZIP_NAME, url or LIBRARY_URL, fetcher=fetcher,
                                          ledger=ledger)
            else:
                path = Path(zip_path)
                if not path.is_file():
                    raise _unavailable(f"the roads file {path} is not there")
                info = {"name": path.name, "cache": "given"}
            net = read_library(path)
            facts = dict(net.facts, cache=info.get("cache"), last_modified=info.get("last_modified"),
                         url=info.get("url", net.facts.get("url")), sha256=_sha256_file(path))
        else:
            files = []
            if tiger_paths is None:
                tiger_paths = []
                for fips in sorted(TIGER_FIPS):
                    name = f"tl_{tiger_edition}_{fips}_roads.zip"
                    dest, info = download_one(cache_dir, name, TIGER_URL.format(edition=tiger_edition, fips=fips),
                                              fetcher=fetcher, ledger=ledger)
                    tiger_paths.append(dest)
                    files.append(info)
            net = read_tiger(tiger_paths)
            facts = dict(net.facts)
            info_by_name = {f["name"]: f for f in files}
            merged = []
            for entry, path in zip(facts["files"], sorted(tiger_paths, key=lambda p: Path(p).name)):
                info = info_by_name.get(Path(path).name, {})
                merged.append(dict(entry, bytes=Path(path).stat().st_size, sha256=_sha256_file(Path(path)),
                                   server_bytes=info.get("server_bytes"), last_modified=info.get("last_modified"),
                                   cache=info.get("cache", "given")))
            facts["files"] = merged
        cleaned = clean_network(net)
    except SourceUnavailable as exc:
        mark_unavailable(root, str(exc), source=True)
        raise
    except (zipfile.BadZipFile, EOFError, struct.error, UnicodeError) as exc:
        reason = f"{UNAVAILABLE}: the source could not be decoded ({type(exc).__name__})"
        mark_unavailable(root, reason, source=True)
        raise SourceUnavailable(reason) from exc
    pieces = cleaned["pieces"]
    names = cleaned["names"]
    name_ids = {name: i for i, name in enumerate(names)}
    for piece in pieces:
        piece["name_id"] = -1 if piece["name"] is None else name_ids[piece["name"]]
    _say(f"streets: {len(pieces):,d} lines from {net.counts.get('kept features', 0):,d} features "
         f"({time.time() - started:.1f}s)")
    stage = root / "hail" / ".r-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        shards = write_shards(stage, pieces, names)
        target = root / "hail" / SHARD_DIR
        if target.exists():
            shutil.rmtree(target)
        os.replace(stage, target)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    measures = _measures(cleaned["counts"], shards, facts, pieces, names, cleaned["county_names"],
                         cleaned.get("fid_county", []), cleaned.get("fid_name", []), cleaned.get("fid_rank", []),
                         {"left_out_by_county": {k: dict(v) for k, v in net.left_out_by_county.items()}})
    counts = measures["counts"]
    block = {
        "format": FORMAT,
        "state": "loaded",
        "sample": False,
        "built_at": _utc_now(),
        "source": {k: v for k, v in facts.items() if k != "quotes"},
        "kind": source,
        "quotes": facts.get("quotes", {}),
        "wording": wording(source, facts),
        "counts": counts,
        "per_county": measures["per_county"],
        "shards": shards["shards"],
        "lines_in_shards": shards["lines_in_leaves"],
        "tiles": shards["tiles"],
        "split": shards["split"],
        "depths": shards["depths"],
        "bytes": {"shards": shards["bytes"], "lines_unclipped_json": _unique_lines_bytes(pieces, names)},
        "largest_shard": shards["largest"],
        "over_limit": shards["over_limit"],
        "at_cap_over_limit": shards["at_cap_over_limit"],
        "classes": {letter: counts["lines by class"].get(letter, 0) for letter in CLASS_ORDER},
        "limits": {"shard_bytes": SHARD_LIMIT, "depth_cap": DEPTH_CAP, "chunk_m": CHUNK_M, "cover_m": COVER_M,
                   "parallel_deg": PARALLEL_DEG, "dp_m": DP_TOL_M, "scale": SCALE},
        "pyproj": pyproj_version(),
        "build_seconds": round(time.time() - started, 1),
        "names": len(names),
    }
    _wire(root, block)
    return block


# ---------------------------------------------------------------- verify

def verify(store_dir, *, source: str | None = None, zip_path=None, tiger_paths=None) -> dict:
    """Check the roads in a store: the manifest hashes, the shard format, the bounds, the line and name counts, the byte
    limit (except at the depth cap), the split map, the classes and the name table; the Census or Library terms and
    the field list (when the source is given); for the Library, that Madrid Drive, Billings, is named in a shard; and the
    simplification gate with its measured post-rounding maximum (D48).
    Returns {"ok": bool, "checks": [...], "counts": {...}}; a failed check names its file."""
    root = Path(store_dir)
    index_path, manifest_path, r_dir = _store_paths(root)
    checks: list = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "checks": [{"check": "index and manifest read", "ok": False, "detail": str(exc)}],
                "counts": {}}
    block = index.get(INDEX_KEY)
    if not isinstance(block, dict):
        check("roads block present", False, "hail/index.json has no roads block")
        return {"ok": False, "checks": checks, "counts": {}}
    if block.get("state") == "unavailable":
        check("roads state", True, "unavailable: " + str(block.get("reason")))
        return {"ok": True, "checks": checks, "counts": {}}
    check("roads state", block.get("state") == "loaded", str(block.get("state")))
    listed = {rel: meta for rel, meta in manifest.get("files", {}).items() if rel.startswith("hail/r/")}
    on_disk = sorted(p.relative_to(root).as_posix() for p in r_dir.rglob("*") if p.is_file()) if r_dir.is_dir() else []
    check("manifest lists every r/ file", sorted(listed) == on_disk,
          f"{len(listed)} listed, {len(on_disk)} on disk")
    bad = []
    for rel, meta in sorted(listed.items()):
        path = root / rel
        if not path.is_file():
            bad.append(rel + " (missing)")
            continue
        data = path.read_bytes()
        if len(data) != meta["bytes"] or _sha256(data) != meta["sha256"]:
            bad.append(rel)
    check("manifest hashes match", not bad, ", ".join(bad[:5]))
    lines_total = 0
    names_seen: set = set()
    over = []
    shard_bytes = 0
    largest = (0, "")
    bounds_bad = []
    format_bad = []
    for rel in sorted(listed):
        path = root / rel
        name = path.name[:-5]
        data = path.read_bytes()
        shard_bytes += len(data)
        largest = max(largest, (len(data), name))
        try:
            doc = json.loads(data)
        except ValueError:
            format_bad.append(name)
            continue
        if doc.get("f") != FORMAT or not isinstance(doc.get("r"), list) or doc.get("n") != len(doc["r"]):
            format_bad.append(name)
            continue
        west, south, east, north = (round(v * SCALE) for v in doc["b"])
        table = doc.get("names", [])
        names_seen.update(table)
        depth = len(name) - TILE_NAME_LEN
        if len(data) > SHARD_LIMIT and depth < DEPTH_CAP:
            over.append(name)
        for cls, idx, pts in doc["r"]:
            lines_total += 1
            if cls not in CLASS_ORDER or not (idx == -1 or 0 <= idx < len(table)) or len(pts) < 2:
                format_bad.append(name)
                break
            for lon, lat in pts:
                if not (west - 1 <= round(lon * SCALE) <= east + 1 and south - 1 <= round(lat * SCALE) <= north + 1):
                    bounds_bad.append(name)
                    break
    check("shard format, classes and name indexes", not format_bad, ", ".join(sorted(set(format_bad))[:5]))
    check("shard bounds hold their lines", not bounds_bad, ", ".join(sorted(set(bounds_bad))[:5]))
    check("every shard within the byte limit or at the depth cap", not over, ", ".join(over[:5]))
    check("line count in shards matches the block", lines_total == block.get("lines_in_shards"),
          f"{lines_total} lines in shards, {block.get('lines_in_shards')} in the block")
    split_ok = True
    for tile, leaves in block.get("split", {}).items():
        if not all((r_dir / f"{leaf}.json").is_file() for leaf in leaves):
            split_ok = False
    check("split map names existing shards", split_ok)
    shard_tiles = {p.stem[:TILE_NAME_LEN] for p in r_dir.glob("*.json")} if r_dir.is_dir() else set()
    check("tiles list every shard's tile", set(block.get("tiles", [])) == shard_tiles,
          f"{len(block.get('tiles', []))} tiles in the block, {len(shard_tiles)} on disk")
    check("largest shard recorded", (block.get("largest_shard") or {}).get("bytes") == largest[0],
          f"recorded {(block.get('largest_shard') or {}).get('bytes')}, found {largest[0]}")
    if block.get("kind") == "msl":
        joined = {part for name in names_seen for part in name.split(" / ")}
        check("Madrid Drive, Billings is named in a shard (D33)", "Madrid Drive" in joined)
    counts = {"shards": len(listed), "lines_in_shards": lines_total, "shard_bytes": shard_bytes,
              "largest_shard": largest[0], "names": len(names_seen)}
    if source and zip_path is not None:
        net = read_library(zip_path) if source == "msl" else None
        if net is not None:
            recomputed = dict(net.counts)
            check("source record count matches the block",
                  recomputed.get("records") == block["counts"].get("records"),
                  f"{recomputed.get('records')} records in the file, {block['counts'].get('records')} in the block")
            check("source kept features match the block",
                  recomputed.get("kept features") == block["counts"].get("kept features"),
                  f"{recomputed.get('kept features')} kept features in the file")
    check(f"simplification: the gate is {DP_TOL_M:g} m before rounding; the largest distance after rounding was "
          f"{POST_ROUNDING_MAX_M:g} m when measured (D48)", DP_TOL_M == 2.0,
          f"gate {DP_TOL_M:g} m; {POST_ROUNDING_MAX_M:g} m measured by the supervisor, not recomputed by verify")
    counts["simplify_gate_m"] = DP_TOL_M
    counts["post_rounding_max_m_measured"] = POST_ROUNDING_MAX_M
    ok = all(item["ok"] for item in checks)
    return {"ok": ok, "checks": checks, "counts": counts}


# ---------------------------------------------------------------- site words and map data (D27, D29)

def describe_streets(index: dict | None = None) -> dict:
    """The About paragraphs for the roads (the source built, its terms and its caveat, D17)."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    if not isinstance(block, dict) or block.get("state") != "loaded":
        reason = block.get("reason") if isinstance(block, dict) else None
        return {"title": "Streets", "state": "unavailable", "problem": reason or "the street list is not in the store",
                "unavailable": WORDS_STREETS["msl"]["unavailable"]}
    kind = block.get("kind", "msl")
    words = block.get("wording") or wording(kind, {"quotes": block.get("quotes", {})})
    return {"title": "Streets", "state": "loaded", "kind": kind, "legend": words["legend"],
            "attribution": words["attribution"], "caveat": words["caveat"], "unavailable": words["unavailable"]}


def map_data_streets(index: dict) -> dict:
    """The map.json["hail"]["streets"] block: the shard pattern, the tiles (build.b3_map_blocks turns the list into the
    compact tile_split, D40) and the split map, the class widths and zoom rules (D27),
    the abbreviation table, and the sentences for the source built (Python fills them, the browser only places them)."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    zoom = {"arterials_from": ZOOM["arterials"], "local_from": ZOOM["local"], "names_from": ZOOM["names"],
            "outline_emphasis_from": ZOOM["outline"]}
    if not isinstance(block, dict) or block.get("state") != "loaded":
        problem = block.get("reason") if isinstance(block, dict) else "the street list is not in the store"
        return {"state": "unavailable", "problem": problem or "the street list is not in the store",
                "templates": {"unavailable": WORDS_STREETS["msl"]["unavailable"]}}
    kind = block.get("kind", "msl")
    words = block.get("wording") or wording(kind, {"quotes": block.get("quotes", {})})
    return {
        "state": "loaded",
        "problem": None,
        "kind": kind,
        "shard": "hail/r/{name}.json",
        "tiles": list(block["tiles"]),
        "split": {tile: list(names) for tile, names in sorted(block["split"].items())},
        "shards": block["shards"],
        "lines": block["counts"].get("lines drawn"),
        "classes": {letter: dict(CLASSES[letter], order=i) for i, letter in enumerate(CLASS_ORDER)},
        "class_order": CLASS_ORDER,
        "zoom": zoom,
        "abbreviations": dict(sorted(ABBREVIATIONS.items())),
        "placeholders": sorted(PLACEHOLDERS),
        "name_join": " / ",
        "templates": {"legend": words["legend"], "attribution": words["attribution"], "caveat": words["caveat"],
                      "unavailable": words["unavailable"]},
        "source": {"file": block["source"].get("file"), "pubdate": block["source"].get("pubdate"),
                   "edition": block["source"].get("edition")},
        "limits": {"shard_bytes": SHARD_LIMIT, "depth_cap": DEPTH_CAP},
    }


# ---------------------------------------------------------------- command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.streets",
                                     description="Streets for the hail store (B3, data module).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="read the roads source, write hail/r/ and the roads block")
    b.add_argument("--store", required=True, help="the store directory that holds hail/ (B1 and B2 built)")
    b.add_argument("--roads-source", choices=("msl", "tiger"), default="msl",
                   help="msl: the Library's Transportation Framework (default, D25); tiger: the Census county files")
    b.add_argument("--cache", default="roads-cache", help="the download cache (kept between runs)")
    b.add_argument("--url", default=None, help="the download address of the Library file (default: the MSL file)")
    b.add_argument("--zip", default=None, help="the Library zip (skips the download)")
    b.add_argument("--tiger-edition", default="2026", help="the TIGER/Line edition of the county files")
    b.add_argument("--ledger", default=None, help="a JSON-lines ledger of the requests (default: the cache's)")
    v = sub.add_parser("verify", help="check the roads in a store (exit 1 on a failure)")
    v.add_argument("store_dir", nargs="?", metavar="STORE", help="the store directory (the same as --store)")
    v.add_argument("--store", dest="store_opt", default=None)
    v.add_argument("--roads-source", choices=("msl", "tiger"), default="msl")
    v.add_argument("--zip", default=None, help="also recount the Library file's records")
    u = sub.add_parser("unavailable", help="write the roads as unavailable with a reason (the job's failure branch)")
    u.add_argument("--store", required=True)
    u.add_argument("--reason", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            started = time.time()
            ledger = args.ledger
            if ledger is None:
                ledger = str(Path(args.cache) / "ledger.jsonl")
            block = build(args.store, source=args.roads_source, cache=args.cache, url=args.url, ledger=ledger,
                          zip_path=args.zip, tiger_edition=args.tiger_edition)
            summary = {k: block["counts"].get(k) for k in (
                "records", "kept features", "left out no geometry", "chunks", "covered chunks",
                "features with a covered piece", "lines drawn", "vertices after cleaning",
                "vertices after simplification", "vertices drawn", "segments drawn", "named share features",
                "named share length")}
            summary["left out no geometry"] = block["counts"].get("left out no geometry", 0)   # absent: none left out
            summary.update(shards=block["shards"], largest_shard=block["largest_shard"], bytes=block["bytes"],
                           depths=block["depths"], over_limit=block["over_limit"],
                           at_cap_over_limit=block["at_cap_over_limit"], wall_seconds=round(time.time() - started, 1))
            print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
            return 0
        if args.command == "verify":
            store = args.store_opt or args.store_dir
            if not store:
                print("error: give the store directory (verify STORE or --store STORE)", file=sys.stderr)
                return 2
            result = verify(store, source=args.roads_source, zip_path=args.zip)
            print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
            return 0 if result["ok"] else 1
        if args.command == "unavailable":
            block = mark_unavailable(args.store, args.reason, source=True)
            print(json.dumps(block, indent=1, ensure_ascii=False))
            return 0
    except SourceUnavailable as exc:
        if args.command != "build":
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"warning: {exc}; the roads are marked unavailable and the rest of the store is kept", file=sys.stderr)
        return 0
    except (StreetsError, addresses.AddressesError, hail.HailStoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
