"""Hail history store (B1): the grid, the size classes and words, the store readers, and the SAMPLE fixture.

The history is a radar estimate, not a measurement and not an inspection. Its source is NOAA MRMS MESH
(MESH_Max_1440min_00.50). The 12:00 UTC file stamped D+1 holds SPC report day D (12:00 UTC on D to 11:59 UTC
on D+1). MESH is in millimetres (NOAA GRIB2 user table, UserTable_MRMS_v12.2). The store keeps tenths of a
millimetre as integers. The codes -1 (missing) and -3 (no coverage) are never stored, and only values of
0.25 in (64 tenths) or more are stored. A cell with no stored value on a day is "no estimate", never "no hail".

Grid: 0.01 degree. Row 0 is centred on 54.995 N and column 0 on 129.995 W; there are 3,500 rows and 7,000
columns. A cell centre is (54.995 - row/100, -129.995 + col/100). A point on a cell edge goes to the cell to
the south (larger row) or to the east (larger column). That is round-half-up of the cell position, computed in
exact decimal arithmetic on the shortest decimal form of the input, so 47.08 N, 110.02 W is row 792, column 1998
and never depends on float rounding. Tiles are 10 by 10 cells. The shard for a cell is
hail/t/r{row//10:04d}_c{col//10:04d}.json, and the key inside it is (row % 10) * 10 + (col % 10).

Days are counted from 2020-01-01 (index 0). The index never moves, so the window can slide without renumbering.
The window is the 1,826 SPC days that end on as_of.

Words: every sentence the sheet and the town tables show is a template in WORDS, with its placeholders in
braces. describe() fills the templates in Python. map_data() hands the same templates to map.js, which fills
them in the browser. Sizes are shown to the hundredth of an inch, rounded down, with the millimetre value exact
(inches()); rounding down never moves a size into the next class. The size classes follow the NWS hail size
chart. The words never say damage, dry, clear, insurance, eligible or confirmed, and "no hail" appears only
inside a sentence that says it is not the conclusion.

Store layout (format hail-store-v1, see docs/DECISIONS.md D34): <store>/hail/index.json, <store>/hail/manifest.json
and the shards under <store>/hail/t/. A store directory is the directory that holds hail/. The release tar.gz
holds hail/ at its top level. Every tile that holds a Montana cell has a shard, with or without events; each
shard's state list holds the in-tile keys of its Montana cells, so the store alone says what is outside Montana.
The index's tiles list names the shards.

Command line (run from the repository root):
    python -m website.hail fixture [--out DIR] [--addresses-from STORE]
                                                                write the SAMPLE store (no network); with
                                                                --addresses-from, its address files too (D18)
    python -m website.hail build [--out store] [--cache DIR]    build the store from the NOAA archive
    python -m website.hail verify STORE                         check a built store
    python -m website.hail compare --store DIR --prototype DIR  compare with the prototype's store
    python -m website.hail fetch [--out DIR] [--url URL]        download and unpack the release store
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path, PurePosixPath

FORMAT = "hail-store-v1"
MANIFEST_FORMAT = "hail-manifest-v1"
SHARD_FORMAT = "hail-cells-v1"
FLOOR_TENTHS = 64                       # 0.25 in = 6.35 mm; the first tenth of a mm at or above it
FLOOR_IN = 0.25
NOTE_TENTHS = 1016                      # 4.00 in = 101.6 mm; the review note starts here
TENTHS_PER_INCH = 254                   # 25.4 mm per inch, in tenths of a mm
D0 = date(2020, 1, 1)                   # day index 0; fixed for ever
TILE = 10                               # cells per tile side (0.1 degree)
ROWS = 3500
COLS = 7000
CELL_DEG = 0.01
ROW0_LAT = 54.995                       # row 0 centre (the north edge of the grid)
COL0_LON = -129.995                     # column 0 centre
ROW0_LAT_E3 = 54995                     # the same two, in thousandths of a degree (exact integers)
COL0_LON_E3 = -129995
GRID = {"cell_deg": CELL_DEG, "tile_cells": TILE, "row0_lat": ROW0_LAT, "col0_lon": COL0_LON,
        "rows": ROWS, "cols": COLS}
WINDOW_DAYS = 1826                      # SPC days in the window, the last one being as_of
STALE_DAYS = 3                          # an as_of older than this shows the stale line
STATE = "Montana"
CELLS_IN_STATE = 450765                 # strict Montana mask on the grid (the prototype's count)
PRODUCT = "MESH_Max_1440min_00.50"
BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"
SOURCE_NAME = "NOAA MRMS MESH 24-hour maximum, 12:00 UTC files, NOAA Open Data on AWS."
UNITS_TABLE = "UserTable_MRMS_v12.2 (MESH mm; -1 missing; -3 no coverage)"
SPC_DAY_RULE = "the file stamped D+1 at 12:00 UTC holds SPC report day D (12:00 UTC D to 11:59 UTC D+1)"
SHARD_TEMPLATE = "hail/t/r{r}_c{c}.json"   # {r} and {c} are row//10 and col//10, four digits each
REPO = os.environ.get("GITHUB_REPOSITORY") or "carson14dy/RoofingApp"
STORE_ASSET_DEFAULT = "hail-store-main.tar.gz"     # main's asset; a branch build reads its own (HAIL_STORE_ASSET)


def store_url(asset: str | None = None) -> str:
    """The release asset the site build downloads. The daily job names the asset after the branch whose job
    publishes it (hail-store-<branch>.tar.gz, slashes as dashes; main's is hail-store-main.tar.gz), and each build
    reads its own branch's asset (the HAIL_STORE_ASSET variable, set by the website workflow), so a branch job
    never touches what main reads."""
    name = asset or os.environ.get("HAIL_STORE_ASSET") or STORE_ASSET_DEFAULT
    return f"https://github.com/{REPO}/releases/download/hail-store/{name}"


STORE_URL = store_url()


def store_urls() -> list[str]:
    """The release assets a build tries in order: its own branch's (HAIL_STORE_ASSET, which the website workflow sets
    to hail-store-<branch>.tar.gz), then main's. A branch whose store job never ran has no asset of its own and reads
    main's, as every branch did before the assets were named; a branch that changed the store code publishes its own
    asset, which comes first. On main the list is main's asset alone."""
    own = os.environ.get("HAIL_STORE_ASSET")
    names = [own] if own and own != STORE_ASSET_DEFAULT else []
    names.append(STORE_ASSET_DEFAULT)
    return [store_url(n) for n in names]
BENCHLAND = (47.08, -110.02)            # the Benchland point (Montana): the sample's town point, on a cell edge
# The check cell (owner decision 3, 2026-10-18). The point above lies on a cell edge and its own cell holds 185
# tenths (0.72 in) on GATE_DAY. The nearest cell that holds GATE_TENTHS on GATE_DAY is the one centred on
# GATE_POINT, about 10.6 km from the point, so the check reads 2.01 in (51.3 mm) there.
GATE_POINT = (47.025, -110.135)
GATE_DAY = date(2025, 6, 15)
GATE_TENTHS = 513
SLOTS_PER_DAY = 720                     # two-minute frames in a full SPC day (12:00 UTC to 12:00 UTC)
NEAR_DUPLICATE_S = 60                   # two frames less than this many seconds apart are one slot (a near copy)
FIXTURE_DIR = Path(__file__).resolve().parent / "data" / "hail-fixture"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class HailStoreError(Exception):
    """A store that cannot be read. The message is the plain words shown as the problem, in lower case,
    with no full stop, because the templates add it."""


# ---------------------------------------------------------------- size classes

# Stored values are tenths of a mm. The minimum of each class is the first tenth at or above its inch
# cut (ceiling of inches x 254); the maximum is the tenth before the next class starts. The top class
# has no maximum. Severe is 1.00 in and up (the NWS severe size).
CLASSES = (
    {"min_tenths": 64, "max_tenths": 190, "min_in": 0.25, "max_in": 0.74,
     "word": "pea to mothball", "severe": False},
    {"min_tenths": 191, "max_tenths": 253, "min_in": 0.75, "max_in": 0.99,
     "word": "penny to nickel", "severe": False},
    {"min_tenths": 254, "max_tenths": 380, "min_in": 1.00, "max_in": 1.49,
     "word": "quarter to half dollar", "severe": True},
    {"min_tenths": 381, "max_tenths": 507, "min_in": 1.50, "max_in": 1.99,
     "word": "ping-pong ball to golf ball", "severe": True},
    {"min_tenths": 508, "max_tenths": 698, "min_in": 2.00, "max_in": 2.74,
     "word": "hen egg to tennis ball", "severe": True},
    {"min_tenths": 699, "max_tenths": None, "min_in": 2.75, "max_in": None,
     "word": "baseball or larger", "severe": True},
)

# Every sentence template. Placeholders are in braces; "{in}" is the size in inches to the hundredth, rounded down,
# and "{mm}" the millimetres to a tenth. Two tags follow a row, joined with ", ": the severe tag and the note.
WORDS = {
    "title": "Hail history at this spot",
    "lead_many": ("{n} days with a radar-estimated hail size of 0.25 in or more between {start} and {end}. "
                  "Largest: {largest_in} in ({largest_mm} mm) on {largest_date}."),
    "lead_one": ("1 day with a radar-estimated hail size of 0.25 in or more between {start} and {end}. "
                 "Largest: {largest_in} in ({largest_mm} mm) on {largest_date}."),
    "lead_none": ("No day between {start} and {end} has a radar-estimated hail size of 0.25 in or more at this "
                  "spot. That is not the same as no hail: radar estimates miss some hail, and {missing} days "
                  "have no data."),
    "lead_none_one": ("No day between {start} and {end} has a radar-estimated hail size of 0.25 in or more at "
                      "this spot. That is not the same as no hail: radar estimates miss some hail, and 1 day "
                      "has no data."),
    "lead_none_plain": ("No day between {start} and {end} has a radar-estimated hail size of 0.25 in or more at "
                        "this spot. That is not the same as no hail: radar estimates miss some hail."),
    "row": "{date}: {in} in ({mm} mm), {class}",
    "severe_tag": "severe size",
    "large_note": "unusually large for a radar estimate; treat with care",
    "class_counts_title": "Days by size class",
    "class_count_one": "1 day: {word}",
    "class_count_many": "{days} days: {word}",
    "what_this_is": ("A radar estimate (NOAA MRMS MESH) of the largest hail over this cell, about 0.7 miles north "
                     "to south and 0.5 miles east to west, during the day. Sizes are shown to the hundredth of an "
                     "inch, rounded down, with the millimetre value exact. An estimate is not a measurement at the "
                     "ground and not an inspection. A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to "
                     "6 am Mountain daylight time, 5 am to 5 am in winter (the SPC reporting day). "
                     "Days not listed have no radar estimate of 0.25 in or more; that is not the same as no hail."),
    "missing": "Days with no data, not counted: {list}.",
    "outside": "Outside Montana. The history covers Montana only.",
    "sample_outside": ("Not in the SAMPLE data: this sample holds only a few places, so this spot has no history "
                       "here."),
    "unavailable": "Hail history is unavailable: {problem}. This is not the same as no hail.",
    "source": ("Source: NOAA MRMS MESH 24-hour maximum, 12:00 UTC files, NOAA Open Data on AWS. History as of "
               "{as_of}. The newest day is added by a job that starts at 12:43 UTC and shows here on the next "
               "rebuild."),
    "sample": "SAMPLE data",
    "stale": "The newest day in this history is {as_of}; newer days have not been added yet.",
    "loading": "Loading the hail history for this spot",
}


def class_for(tenths: int) -> dict:
    """The size class of a stored value (tenths of a mm), with the note for 4.00 in and up.

    Returns a copy of the class with "note" set to the review note, or None below 4.00 in. Raises
    ValueError below the 0.25 in floor, because nothing below it is stored."""
    t = int(tenths)
    if t < FLOOR_TENTHS:
        raise ValueError(f"{t} tenths is below the {FLOOR_IN:.2f} in floor")
    for cls in CLASSES:
        if cls["max_tenths"] is None or t <= cls["max_tenths"]:
            out = dict(cls)
            out["note"] = WORDS["large_note"] if t >= NOTE_TENTHS else None
            return out
    raise AssertionError("the class table has no top class")  # unreachable: the last class is open


# ---------------------------------------------------------------- grid and days

def _finite(value: float, name: str) -> Decimal:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return Decimal(repr(number))


def cell_for(lat: float, lon: float) -> tuple[int, int]:
    """(row, col) of the grid cell that holds (lat, lon).

    row = round-half-up((54.995 - lat) * 100) = floor(5500 - 100 * lat) and
    col = round-half-up((lon + 129.995) * 100) = floor(100 * lon + 13000), in exact decimal arithmetic.
    A point on an edge goes to the cell to the south or east. The result can lie outside the grid;
    use in_grid() to check."""
    lat_d = _finite(lat, "lat")
    lon_d = _finite(lon, "lon")
    row = math.floor(Decimal(5500) - Decimal(100) * lat_d)
    col = math.floor(Decimal(100) * lon_d + Decimal(13000))
    return int(row), int(col)


def cell_centre(row: int, col: int) -> tuple[float, float]:
    """(lat, lon) of the centre of cell (row, col): lat = 54.995 - row/100, lon = -129.995 + col/100.

    Computed in whole thousandths of a degree and divided once, so every centre is the nearest float to
    its decimal value."""
    return (ROW0_LAT_E3 - 10 * int(row)) / 1000, (COL0_LON_E3 + 10 * int(col)) / 1000


def in_grid(row: int, col: int) -> bool:
    return 0 <= int(row) < ROWS and 0 <= int(col) < COLS


def tile_name(tile_row: int, tile_col: int) -> str:
    """The name of a tile in the index's tiles list and in its shard's file name, such as "r0079_c0199"."""
    return f"r{int(tile_row):04d}_c{int(tile_col):04d}"


def shard_path(row: int, col: int) -> str:
    """The path of the shard for the tile holding cell (row, col), relative to the store directory."""
    return f"hail/t/{tile_name(int(row) // TILE, int(col) // TILE)}.json"


def cell_key(row: int, col: int) -> int:
    """The key of a cell inside its shard: (row % 10) * 10 + (col % 10), 0 to 99."""
    return (int(row) % TILE) * TILE + (int(col) % TILE)


def day_index(spc_day: date) -> int:
    """The day index of an SPC report day: its number of days after 2020-01-01."""
    return (spc_day - D0).days


def day_of_index(d: int) -> date:
    return D0 + timedelta(days=int(d))


def window_for(as_of: date) -> tuple[date, date]:
    """The window: the 1,826 SPC days that end on as_of (first, last)."""
    return as_of - timedelta(days=WINDOW_DAYS - 1), as_of


def stamp_for_day(spc_day: date) -> date:
    """The date of the 12:00 UTC file that holds SPC report day spc_day."""
    return spc_day + timedelta(days=1)


def day_for_stamp(stamp: date) -> date:
    """The SPC report day that the 12:00 UTC file stamped `stamp` holds."""
    return stamp - timedelta(days=1)


# ---------------------------------------------------------------- values and words

def inches(tenths: int) -> str:
    """The size in inches, shown to the hundredth of an inch and rounded down, as text: "2.01" for 513 tenths
    (51.3 mm), "0.72" for 185, "0.99" for 253, "1.00" for 254. Rounding down never moves a size into the next
    class: each class starts at its own inch cut (CLASSES), and the largest size below a cut shows below it.
    The millimetres are kept beside it (mm_text)."""
    t = int(tenths)
    if t < 0:
        raise ValueError("a size cannot be negative")
    hundredths = (100 * t) // TENTHS_PER_INCH
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def mm_text(tenths: int) -> str:
    """Millimetres to one decimal place, from tenths of a mm: 513 gives "51.3"."""
    t = int(tenths)
    if t < 0:
        raise ValueError("a size cannot be negative")
    return f"{t // 10}.{t % 10}"


def fmt_date(day: date) -> str:
    """A date as the sheet and the tables show it: "Jun 15, 2025" (no leading zero on the day)."""
    return f"{MONTHS[day.month - 1]} {day.day}, {day.year}"


def _pairs(events) -> list[tuple[date, int]]:
    out = []
    for when, tenths in events or []:
        day = when if isinstance(when, date) else date.fromisoformat(str(when))
        out.append((day, int(tenths)))
    return out


def _window_dates(index: dict) -> tuple[date, date]:
    first, last = index["window"]
    return date.fromisoformat(first), date.fromisoformat(last)


def is_stale(as_of, now) -> bool:
    """True when the store's last day is more than STALE_DAYS before now's UTC day: the pages show the stale line
    and the build counts the store as a failed source (--require-live then fails). as_of is a date or an ISO day."""
    day = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    today = _utc_day(now)
    return today is not None and (today - day).days > STALE_DAYS


def _utc_day(now) -> date | None:
    if now is None:
        return None
    if isinstance(now, datetime):
        if now.tzinfo is not None:
            now = now.astimezone(timezone.utc)
        return now.date()
    return now


def _empty(state: str) -> dict:
    return {"state": state, "title": WORDS["title"], "sample": None, "lead": None, "rows": [],
            "class_title": None, "class_lines": [], "what_this_is": None, "missing": None, "stale": None,
            "source": None, "outside": None, "unavailable": None, "window": None, "as_of": None}


def describe(index: dict, events, now, sample: bool = False) -> dict:
    """The words for one cell, filled in Python.

    index is the loaded store index. events is a list of (SPC day, tenths) for the cell, as cell_events()
    returns it, or None when the point lies outside Montana (no fetch, the outside words). now is a UTC
    datetime or date, used only for the stale line; None skips it. sample=True adds the SAMPLE label.

    Rows are newest first. Days outside the window and values below the floor are ignored. Missing days
    in the window are listed and never counted as days without hail."""
    start, end = _window_dates(index)
    as_of = date.fromisoformat(index["as_of"])
    out = _empty("loaded")
    out["sample"] = WORDS["sample"] if sample else None
    out["window"] = [start.isoformat(), end.isoformat()]
    out["as_of"] = as_of.isoformat()
    if events is None:
        out["state"] = "outside"
        out["outside"] = WORDS["sample_outside"] if sample else WORDS["outside"]
        return out

    best: dict[date, int] = {}
    for when, tenths in _pairs(events):
        if start <= when <= end and tenths >= FLOOR_TENTHS:
            best[when] = max(best.get(when, 0), tenths)
    rows = []
    for when, tenths in sorted(best.items(), reverse=True):
        cls = class_for(tenths)
        text = WORDS["row"].format_map({"date": fmt_date(when), "in": inches(tenths),
                                        "mm": mm_text(tenths), "class": cls["word"]})
        tags = ([WORDS["severe_tag"]] if cls["severe"] else []) + ([cls["note"]] if cls["note"] else [])
        if tags:
            text += ", " + ", ".join(tags)
        rows.append({"iso": when.isoformat(), "date": fmt_date(when), "tenths": tenths, "in": inches(tenths),
                     "mm": mm_text(tenths), "class": cls["word"], "severe": cls["severe"],
                     "note": cls["note"], "text": text})
    out["rows"] = rows

    missing = [date.fromisoformat(d) for d in index.get("missing_days", [])]
    missing = sorted(d for d in missing if start <= d <= end)
    common = {"start": fmt_date(start), "end": fmt_date(end)}
    if rows:
        largest = max(rows, key=lambda r: (r["tenths"], r["iso"]))
        fill = dict(common, n=len(rows), largest_in=largest["in"], largest_mm=largest["mm"],
                    largest_date=largest["date"])
        out["lead"] = (WORDS["lead_one"] if len(rows) == 1 else WORDS["lead_many"]).format_map(fill)
    elif not missing:
        out["lead"] = WORDS["lead_none_plain"].format_map(common)
    elif len(missing) == 1:
        out["lead"] = WORDS["lead_none_one"].format_map(common)
    else:
        out["lead"] = WORDS["lead_none"].format_map(dict(common, missing=len(missing)))

    if missing:
        out["missing"] = WORDS["missing"].format_map({"list": ", ".join(fmt_date(d) for d in missing)})

    if not sample and is_stale(as_of, now):       # the SAMPLE fixture's as_of is fixed: never stale
        out["stale"] = WORDS["stale"].format_map({"as_of": fmt_date(as_of)})

    out["source"] = WORDS["source"].format_map({"as_of": fmt_date(as_of)})
    out["what_this_is"] = WORDS["what_this_is"]

    lines = []
    for cls in CLASSES:
        count = sum(1 for r in rows if r["class"] == cls["word"])
        if count:
            key = "class_count_one" if count == 1 else "class_count_many"
            lines.append(WORDS[key].format_map({"days": count, "word": cls["word"]}))
    if lines:
        out["class_title"] = WORDS["class_counts_title"]
        out["class_lines"] = lines
    return out


def describe_unavailable(problem) -> dict:
    """The words when the store cannot be read. `problem` is plain lower-case words, such as
    "the history index file is missing"."""
    out = _empty("unavailable")
    out["unavailable"] = WORDS["unavailable"].format_map({"problem": str(problem)})
    return out


_CLASS_FIELDS = ("min_tenths", "max_tenths", "min_in", "max_in", "word", "severe")


def map_data(index: dict, sample: bool = False) -> dict:
    """The map.json["hail"] block for a loaded store (the browser does the click, the fetch and the fill).

    "shard" is a template: {r} and {c} are row//10 and col//10 written with four digits. "tiles" is the index's
    list of tiles that hold a Montana cell: a tile not in it is outside Montana, with no fetch. "tenths_per_inch"
    is the divisor map.js uses, so no unit literal lives in the script; map.js shows a size as
    Math.floor(tenths * 100 / tenths_per_inch) / 100 with two decimals. "words" holds every template."""
    return {
        "state": "sample" if sample else "loaded",
        "as_of": index["as_of"],
        "window": list(index["window"]),
        "d0": D0.isoformat(),
        "missing_days": list(index.get("missing_days", [])),
        "grid": dict(index["grid"]),
        "shard": SHARD_TEMPLATE,
        "tiles": list(index["tiles"]),
        "floor_tenths": FLOOR_TENTHS,
        "floor_in": FLOOR_IN,
        "tenths_per_inch": TENTHS_PER_INCH,
        "large_note_tenths": NOTE_TENTHS,
        "classes": [{k: c[k] for k in _CLASS_FIELDS} for c in CLASSES],
        "words": dict(WORDS),
        "source": SOURCE_NAME,
        "problem": None,
    }


def map_data_unavailable(problem) -> dict:
    """The map.json["hail"] block when the store cannot be read: the same words and classes, no as_of, no tiles."""
    return {
        "state": "unavailable",
        "as_of": None,
        "window": None,
        "d0": D0.isoformat(),
        "missing_days": [],
        "grid": dict(GRID),
        "shard": SHARD_TEMPLATE,
        "tiles": [],
        "floor_tenths": FLOOR_TENTHS,
        "floor_in": FLOOR_IN,
        "tenths_per_inch": TENTHS_PER_INCH,
        "large_note_tenths": NOTE_TENTHS,
        "classes": [{k: c[k] for k in _CLASS_FIELDS} for c in CLASSES],
        "words": dict(WORDS),
        "source": SOURCE_NAME,
        "problem": str(problem),
    }


# ---------------------------------------------------------------- readers

def _read_json(path: Path, missing_message: str):
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise HailStoreError(missing_message) from None
    except OSError:
        raise HailStoreError(f"the history file {path.name} could not be read") from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HailStoreError(f"the history file {path.name} is not valid JSON") from None


def load_index(store_dir) -> dict:
    """The index of the store in store_dir (the directory that holds hail/). Raises HailStoreError."""
    doc = _read_json(Path(store_dir) / "hail" / "index.json", "the history index file is missing")
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise HailStoreError("the history index is not in the hail-store-v1 format")
    if doc.get("d0") != D0.isoformat() or doc.get("grid") != GRID:
        raise HailStoreError("the history grid does not match this site's grid")
    for key in ("as_of", "window", "missing_days", "floor_tenths", "tiles"):
        if key not in doc:
            raise HailStoreError(f"the history index has no {key}")
    if not isinstance(doc["tiles"], list):
        raise HailStoreError("the history index has no tiles list")
    return doc


def cell_events(store_dir, lat: float, lon: float, index: dict | None = None) -> list[tuple[date, int]] | None:
    """The stored (SPC day, tenths) for the cell that holds (lat, lon), oldest first; None when the point is outside
    Montana.

    The store decides what is outside. A point whose tile is not in the index's tiles list is outside, and so is a
    point whose in-tile key is not in its shard's state list; neither reads a shard. A Montana cell with no stored
    value on any day gives [] (no estimate, never "no hail"). A tile the index lists must have its shard, and a
    missing one is refused. index is the loaded index; load_index() is called when it is None."""
    row, col = cell_for(lat, lon)
    if not in_grid(row, col):
        return None
    if index is None:
        index = load_index(store_dir)
    if tile_name(row // TILE, col // TILE) not in index["tiles"]:
        return None
    path = Path(store_dir) / shard_path(row, col)
    doc = _read_json(path, f"the history shard {path.name} is missing")
    if (not isinstance(doc, dict) or doc.get("f") != SHARD_FORMAT or doc.get("d0") != D0.isoformat()
            or doc.get("r") != row // TILE or doc.get("c") != col // TILE):
        raise HailStoreError(f"the history shard {path.name} is not in the expected format")
    key = cell_key(row, col)
    if key not in doc.get("state", []):
        return None
    rows = doc.get("cells", {}).get(str(key), [])
    return [(day_of_index(int(d)), int(t)) for d, t in rows]


# D75: B4's live swath files (website/swath.py, hail/live/<window minutes>/<valid time>/<tile>.json). The build writes
# them into a built site after the site's copy of the store is checked, and the manifest never lists them.
LIVE_PREFIX = "hail/live/"


def check_manifest(store_dir, allow_live: bool = False) -> dict:
    """Check that every file the manifest lists is under hail/ and has its listed size and SHA-256, that no other
    file is under hail/ (any type of file, not only JSON), that no link is under hail/, and that the manifest's
    counts equal the index's counts.
    allow_live (D75) skips the unlisted-file check for the files under hail/live/: a built site's own copy of the
    store carries them, and no store does. The default is strict (an archive, the build's copy, a store folder).
    A link under hail/live/ is refused either way.
    Returns the manifest. Raises HailStoreError."""
    root = Path(store_dir)
    manifest = _read_json(root / "hail" / "manifest.json", "the history manifest file is missing")
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
        raise HailStoreError("the history manifest is not in the expected format")
    listed = manifest.get("files", {})
    for rel, expect in sorted(listed.items()):
        parts = PurePosixPath(rel).parts
        if rel.startswith("/") or not parts or parts[0] != "hail" or ".." in parts:
            raise HailStoreError(f"the history manifest lists a file outside hail/: {rel}")
        path = root / rel
        if not path.is_file():
            raise HailStoreError(f"the history file {rel} is missing")
        data = path.read_bytes()
        if len(data) != expect["bytes"] or hashlib.sha256(data).hexdigest() != expect["sha256"]:
            raise HailStoreError(f"the history file {rel} does not match the manifest")
    known = set(listed) | {"hail/manifest.json"}
    for path in sorted((root / "hail").rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise HailStoreError(f"the history has a link, which is not allowed: {rel}")
        if path.is_dir():
            continue
        if rel not in known and not (allow_live and rel.startswith(LIVE_PREFIX)):
            raise HailStoreError(f"the history has a file the manifest does not list: {rel}")
    index = load_index(root)
    for key, value in manifest.get("counts", {}).items():
        if index.get(key) != value:
            raise HailStoreError(f"the history {key} does not match the manifest")
    return manifest


# ---------------------------------------------------------------- SAMPLE fixture

SAMPLE_AS_OF = "2026-10-15"
SAMPLE_BUILT_AT = "2026-10-18T00:00:00Z"
# SPC day 2022-06-08: its 12:00 UTC file (stamped 2022-06-09) is absent from the bucket and from IEM
# (research review rc11). Missing days are SPC days, because the window and the counts are SPC days.
SAMPLE_MISSING = ("2022-06-08",)
SAMPLE_SOURCE = {"product": PRODUCT, "bucket": BUCKET, "file_time": "12:00 UTC",
                 "spc_day_rule": SPC_DAY_RULE, "units_table": UNITS_TABLE}
# The SAMPLE events (the three tiles' real values on the listed days) are in website/hail_fixture_data.py.
# fixture_store() imports that module when it writes the SAMPLE store; a normal build never loads it.


def _compact(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


def _shard_bytes(tile_row: int, tile_col: int, state: list, cells: dict) -> bytes:
    """One tile's shard as compact JSON, fields in the order of docs/DECISIONS.md D34 (hail-cells-v1)."""
    return _compact({"f": SHARD_FORMAT, "r": int(tile_row), "c": int(tile_col), "d0": D0.isoformat(),
                     "u": "tenths of a mm", "state": state, "cells": cells})


ADDRESSES_KEY = "addresses"     # the index block of the address part (addresses.INDEX_KEY, D18)


def _kept_address_part(root: Path) -> tuple:
    """The address part of an earlier write under root (D18): the index's addresses block and every file under
    hail/a/, as (block, [(store-relative path, bytes)]). (None, []) when the index has no such block."""
    try:
        earlier = json.loads((root / "hail" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    block = earlier.get(ADDRESSES_KEY) if isinstance(earlier, dict) else None
    if not isinstance(block, dict):
        return None, []
    files = []
    base = root / "hail" / "a"
    if base.is_dir():
        for path in sorted(base.rglob("*")):
            if path.is_file():
                files.append((path.relative_to(root).as_posix(), path.read_bytes()))
    return block, files


def fixture_store(dest_dir, addresses_from=None) -> dict:
    """Write the SAMPLE store (three tiles, labelled sample) under dest_dir/hail/ and return its index.

    The tiles are the ones hail_fixture_data.SAMPLE_EVENTS names. Each shard's state list comes from the Montana mask,
    so the sample answers the outside words, the no-estimate words and the rows as the store does. The index lists only
    these tiles, so every other point reads as outside in a sample build (the sheet and the tables say SAMPLE).
    Deterministic: the same call writes the same bytes. It replaces the B1 files under dest_dir/hail/ and keeps the
    address part of an earlier write (hail/a/ and the index's addresses block, D18), so the joins' rewrite never drops
    it. With addresses_from (a built store with real address files), the address writer writes that part instead."""
    from . import hail_fixture_data     # the SAMPLE events, imported here only: a normal build never loads them
    root = Path(dest_dir)
    hail = root / "hail"
    kept_block, kept_files = (None, []) if addresses_from is not None else _kept_address_part(root)
    if hail.exists():
        shutil.rmtree(hail)
    cells_by_tile: dict[tuple[int, int], dict[int, list]] = {}
    for row, col, days in hail_fixture_data.SAMPLE_EVENTS:
        cells = cells_by_tile.setdefault((row // TILE, col // TILE), {})
        cells.setdefault(cell_key(row, col), []).extend(
            [day_index(date.fromisoformat(d)), int(t)] for d, t in days)
    states = {(tr, tc): keys for tr, tc, keys in _tile_states(montana_mesh())}
    shards = []
    for tr, tc in sorted(cells_by_tile):
        if (tr, tc) not in states:
            raise AssertionError(f"the sample tile {tile_name(tr, tc)} holds no Montana cell")
        cells = {str(k): sorted(v) for k, v in sorted(cells_by_tile[(tr, tc)].items())}
        data = _shard_bytes(tr, tc, states[(tr, tc)], cells)
        rel = shard_path(tr * TILE, tc * TILE)
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
        shards.append((rel, data))
    as_of = date.fromisoformat(SAMPLE_AS_OF)
    start, end = window_for(as_of)
    events = sum(len(v) for _rel, data in shards for v in json.loads(data)["cells"].values())
    shard_bytes = sum(len(data) for _rel, data in shards)
    index = {
        "format": FORMAT,
        "built_at": SAMPLE_BUILT_AT,
        "as_of": as_of.isoformat(),
        "window": [start.isoformat(), end.isoformat()],
        "d0": D0.isoformat(),
        "grid": dict(GRID),
        "state": STATE,
        "cells_in_state": CELLS_IN_STATE,
        "floor_tenths": FLOOR_TENTHS,
        "floor_in": FLOOR_IN,
        "days_expected": WINDOW_DAYS,
        "days_present": WINDOW_DAYS - len(SAMPLE_MISSING),
        "missing_days": list(SAMPLE_MISSING),
        "events": events,
        "shards": len(shards),
        "bytes": shard_bytes,
        "tiles": [tile_name(tr, tc) for tr, tc in sorted(cells_by_tile)],
        "source": dict(SAMPLE_SOURCE),
        "copy_check": {"days_checked": 0, "days_differed": [], "rederived": [],
                       "skipped": "sample store: the copy rule was not run", "frames": {}, "coverage": {},
                       "partial": []},
        "sample": True,
    }
    if kept_block is not None:
        index[ADDRESSES_KEY] = kept_block
    index_bytes = _pretty(index)
    (hail / "index.json").write_bytes(index_bytes)
    for rel, data in kept_files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    files = [("hail/index.json", index_bytes)] + shards + kept_files
    manifest = {
        "format": MANIFEST_FORMAT,
        "as_of": index["as_of"],
        "sample": True,
        "counts": {"days_expected": index["days_expected"], "days_present": index["days_present"],
                   "events": events, "shards": index["shards"], "bytes": shard_bytes},
        "files": {rel: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for rel, data in files},
    }
    (hail / "manifest.json").write_bytes(_pretty(manifest))
    if addresses_from is not None:
        from . import addresses     # the address writer (D18): it replaces hail/a/ and the addresses block
        try:
            addresses.fixture(root, addresses_from)
        except addresses.AddressesError as exc:
            raise HailStoreError(f"the fixture's address files were not written: {exc}") from exc
        return load_index(root)
    return index


# ---------------------------------------------------------------- reading a downloaded store

def _install_store(data: bytes, dest: Path) -> None:
    """Unpack the hail/ tree of a release archive into dest. dest/hail is replaced only when every file matches
    the manifest and its counts match the index. Raises HailStoreError."""
    if bytes(data[:2]) != b"\x1f\x8b":
        raise HailStoreError("the history download is not a gzip file")
    dest.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".hail-unpack-", dir=str(dest)))
    try:
        _unpack_hail(data, stage)
        check_manifest(stage)
        target = dest / "hail"
        if target.exists():
            shutil.rmtree(target)
        os.replace(stage / "hail", target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _unpack_hail(data: bytes, stage: Path) -> None:
    """Write the hail/ members of a gzip tar under stage. Other members are skipped. A name that climbs out of
    the archive, a link, a special file, a repeated name or an archive over the size limits is refused."""
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except (tarfile.TarError, OSError, EOFError, zlib.error):
        raise HailStoreError("the history download is not a tar.gz archive") from None
    seen: set[str] = set()
    files = 0
    total = 0
    try:
        with archive:
            for member in archive:
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                parts = PurePosixPath(name).parts
                if name.startswith("/") or ".." in parts:
                    raise HailStoreError("the history archive holds a name that is not allowed")
                if not parts or parts[0] != "hail":
                    continue
                if member.isdir():
                    continue
                if not member.isfile():
                    raise HailStoreError(f"the history archive holds a link or special file: {name}")
                if name in seen:
                    raise HailStoreError(f"the history archive holds {name} twice")
                seen.add(name)
                files += 1
                total += member.size
                if files > MAX_UNPACK_FILES or total > MAX_UNPACK_BYTES:
                    raise HailStoreError("the history archive is larger than the limits allow")
                source = archive.extractfile(member)
                body = source.read() if source is not None else b""
                target = stage.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
    except (tarfile.TarError, EOFError, zlib.error, OSError):
        raise HailStoreError("the history archive could not be read") from None
    if not files:
        raise HailStoreError("the history archive has no store files")


def fetch_store(get, dest_dir, url: str = STORE_URL) -> dict:
    """Download the release tar.gz, check its manifest and unpack hail/ into dest_dir. Returns the index.

    get(url, headers=None) -> (bytes | None, error | None) is the build's binary fetcher (sources.Fetcher.binary).
    Raises HailStoreError with the plain reason when the download, the archive, a hash or a count is wrong."""
    data, error = get(url, headers=None)
    if data is None:
        raise HailStoreError(f"the history download failed: {error or 'no data'}")
    if not isinstance(data, (bytes, bytearray)):
        raise HailStoreError("the history download is not bytes")
    _install_store(bytes(data), Path(dest_dir))
    return load_index(dest_dir)


def fetch_store_any(get, dest_dir, urls) -> tuple[dict, str]:
    """fetch_store over the assets in order (store_urls): the first whose download answers is unpacked and checked,
    and its URL is returned with the index. Only an asset that is not published (HTTP 404) is passed over for the
    next one; any other failure raises at once, so a branch's own asset that is down is never replaced by main's
    without a word, and an archive that downloads but does not check out raises too. Raises HailStoreError naming
    the failed downloads."""
    failures = []
    for n, url in enumerate(urls):
        data, error = get(url, headers=None)
        if data is None:
            failures.append(f"{url.rsplit('/', 1)[-1]}: {error or 'no data'}")
            if n + 1 < len(urls) and "(HTTP 404)" in (error or ""):
                continue                        # the branch has no asset of its own: read the next one
            raise HailStoreError("the history download failed: " + "; ".join(failures))
        if not isinstance(data, (bytes, bytearray)):
            raise HailStoreError("the history download is not bytes")
        _install_store(bytes(data), Path(dest_dir))
        return load_index(dest_dir), url
    raise HailStoreError("the history download failed: " + "; ".join(failures))


def plain_problem(problem: str) -> str:
    """The page's words for a store problem. A download failure names files and HTTP codes for the build log; the
    page says what happened in plain words. Every other problem is already a plain sentence."""
    if problem.startswith("the history download failed"):
        return "the history store could not be downloaded in this update"
    return problem


def load_store(path, dest_dir=None) -> Path:
    """The directory that holds a verified hail/ tree, from a store directory or a release tar.gz (--hail-store).

    A directory is checked in place and returned. It may be a built site's own hail/ copy: the live swath files under
    hail/live/ are skipped (D75). A tar.gz is unpacked into dest_dir (a new temporary directory when None) and that
    directory is returned; an archive is checked strictly, since it never carries live files. Read the index with
    load_index() and the cells with cell_events(). Raises HailStoreError."""
    source = Path(path)
    if source.is_dir():
        check_manifest(source, allow_live=True)
        return source
    if source.is_file():
        dest = Path(dest_dir) if dest_dir is not None else Path(tempfile.mkdtemp(prefix="hail-store-"))
        _install_store(source.read_bytes(), dest)
        return dest
    raise HailStoreError(f"the history store is not at {source}")


# ---------------------------------------------------------------- the store builder

BUCKET_FOLDER = "CONUS"
FRAME_PRODUCT = "MESH_00.50"                  # the two-minute frames: CONUS/MESH_00.50/<YYYYMMDD>/
IEM = "https://mtarchive.geol.iastate.edu"    # the IEM copy of the 12:00 files (folder MESH_Max_1440min)
USER_AGENT = "montana-hail-watch-hail-store/1 (+https://github.com/carson14dy/RoofingApp)"
BASEMAP = Path(__file__).resolve().parent / "static" / "map" / "basemap.json"
FRAME_LAT_E3 = (43000, 50500)                 # the prototype's decode box, in thousandths of a degree
FRAME_LON_E3 = (-118500, -101000)
MIN_FRAMES = 700                              # a re-derived day needs this many of its 720 two-minute frames
MAX_MISSING_DAYS = 20                         # a build with more gaps than this is refused (a bad listing, say)
# The limits an unpacked release may reach (D42). The B3 store (the address, outline and road files under hail/) is
# 372,880,597 bytes in 31,129 files (the fresh job store, measured at the site re-check on 2026-10-19), and the earlier
# 300 MiB and 20,000-file limits refused it. These leave about 2.2 times the bytes and about 1.9 times the files; the
# bulk files stay in the store until the data-site decision (D31).
MAX_UNPACK_BYTES = 800 * 1024 * 1024
MAX_UNPACK_FILES = 60000
EPOCH = date(1970, 1, 1)
STAMP_NAME = re.compile(r"MRMS_" + re.escape(PRODUCT) + r"_(\d{8})-120000\.grib2\.gz")
FRAME_NAME = re.compile(r"MRMS_" + re.escape(FRAME_PRODUCT) + r"_(\d{8})-(\d{6})\.grib2\.gz")
SOURCE = {"product": PRODUCT, "bucket": BUCKET, "file_time": "12:00 UTC", "spc_day_rule": SPC_DAY_RULE,
          "units_table": UNITS_TABLE}
_PARQUET_HELPER = (
    "import sys\n"
    "import numpy as np\n"
    "import pyarrow.parquet as pq\n"
    "t = pq.read_table(sys.argv[1], columns=['cell_index', 'day', 'mm'])\n"
    "days = t.column('day').to_numpy().astype('datetime64[D]').astype(np.int64)\n"
    "np.savez(sys.argv[2], cell_index=t.column('cell_index').to_numpy().astype(np.int64), day=days,\n"
    "         mm=t.column('mm').to_numpy().astype(np.float64))\n"
)


def _np():
    """numpy, imported only where a mask or a decode needs it (describe() and the readers do not)."""
    import numpy
    return numpy


def _utc_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _day_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def bucket_name(stamp: date) -> str:
    """The NOAA file name of the 12:00 UTC MESH_Max_1440min file stamped `stamp`."""
    return f"MRMS_{PRODUCT}_{stamp:%Y%m%d}-120000.grib2.gz"


def bucket_url(stamp: date) -> str:
    return f"{BUCKET}/{BUCKET_FOLDER}/{PRODUCT}/{stamp:%Y%m%d}/{bucket_name(stamp)}"


def iem_url(stamp: date) -> str:
    """The IEM copy. The folder is named without the _00.50 suffix; the file keeps it."""
    return f"{IEM}/{stamp:%Y/%m/%d}/mrms/ncep/MESH_Max_1440min/{PRODUCT}_{stamp:%Y%m%d}-120000.grib2.gz"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_decision(bucket_bytes, iem_bytes) -> str:
    """The copy rule for one 12:00 UTC file, from the byte sizes that the two copies answer with.

    None means the copy did not answer (no file, or an error). The results:
    "same": both copies answer with the same size; the bucket copy is used.
    "rederive": both answer and the sizes differ; the day is re-derived as the maximum of its two-minute frames.
    "skipped": the bucket copy answers and IEM does not; the bucket copy is used and the day is listed as skipped.
    "iem": the bucket has no file and IEM does; the IEM copy is used.
    "missing": neither copy has the file; the day is listed as missing and is never written as zero."""
    if bucket_bytes is None:
        return "missing" if iem_bytes is None else "iem"
    if iem_bytes is None:
        return "skipped"
    return "same" if int(bucket_bytes) == int(iem_bytes) else "rederive"


def _frame_box() -> tuple[int, int, int, int]:
    """(row0, nrow, col0, ncol) of the decode box: the prototype's box, a rectangle of grid rows and columns."""
    rows = [r for r in range(ROWS) if FRAME_LAT_E3[0] <= ROW0_LAT_E3 - 10 * r <= FRAME_LAT_E3[1]]
    cols = [c for c in range(COLS) if FRAME_LON_E3[0] <= COL0_LON_E3 + 10 * c <= FRAME_LON_E3[1]]
    if rows != list(range(rows[0], rows[-1] + 1)) or cols != list(range(cols[0], cols[-1] + 1)):
        raise HailStoreError("the decode box is not a rectangle of grid cells")
    return rows[0], len(rows), cols[0], len(cols)


def _montana_ring(basemap_path=BASEMAP) -> list[tuple[float, float]]:
    """The Montana land polygon (properties.montana true) from the website basemap, as (lon, lat) pairs."""
    data = json.loads(Path(basemap_path).read_text(encoding="utf-8"))
    hits = [f for f in data["land"]["features"] if f.get("properties", {}).get("montana") is True]
    if len(hits) != 1 or hits[0]["geometry"]["type"] != "Polygon" or len(hits[0]["geometry"]["coordinates"]) != 1:
        raise ValueError("expected exactly one Montana polygon with one ring in the basemap")
    return [(float(x), float(y)) for x, y in hits[0]["geometry"]["coordinates"][0]]


def _strict_mask(ring, row0: int, nrow: int, col0: int, ncol: int):
    """Cell centres strictly inside the ring, by even-odd crossings; a centre on an edge is outside. This is the
    prototype's polygon_masks (its strict mask, 450,765 cells for Montana)."""
    np = _np()
    rows = np.arange(row0, row0 + nrow)
    cols = np.arange(col0, col0 + ncol)
    lat = (ROW0_LAT_E3 - 10 * rows).astype(np.float64) / 1000.0
    lon = (COL0_LON_E3 + 10 * cols).astype(np.float64) / 1000.0
    Y = lat[:, None]
    X = lon[None, :]
    inside = np.zeros((nrow, ncol), dtype=bool)
    on_edge = np.zeros((nrow, ncol), dtype=bool)
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if y1 == y2:
            continue
        cross = (y1 > Y) != (y2 > Y)
        if not cross.any():
            continue
        xi = x1 + (Y - y1) * ((x2 - x1) / (y2 - y1))
        inside ^= cross & (X < xi)
        on_edge |= cross & (X == xi)
    return inside & ~on_edge


class Mesh:
    """The Montana cells of the grid. The decoded values are in the order of the mask's row-major cells, and
    rows and cols give each of those cells' global grid row and column."""

    def __init__(self, row0: int, col0: int, mask):
        np = _np()
        self.row0 = int(row0)
        self.col0 = int(col0)
        self.mask = np.ascontiguousarray(mask, dtype=bool)
        self.nrow, self.ncol = self.mask.shape
        flat = np.flatnonzero(self.mask)
        self.n = int(flat.size)
        rr, cc = np.divmod(flat, self.ncol)
        self.rows = (rr + self.row0).astype(np.int64)
        self.cols = (cc + self.col0).astype(np.int64)


@lru_cache(maxsize=2)
def montana_mesh(basemap_path=BASEMAP) -> Mesh:
    """The Montana mesh from the website basemap (cached for the process; do not change it)."""
    row0, nrow, col0, ncol = _frame_box()
    return Mesh(row0, col0, _strict_mask(_montana_ring(basemap_path), row0, nrow, col0, ncol))


def pack_tenths(raw):
    """Raw MESH values (mm) to uint16 tenths of a mm, 0 for no data. Port of the prototype's pack_tenths.

    The codes -1 (missing) and -3 (no coverage), any other negative value and NaN are no data and are never
    stored. Exact zero is no data too. Positive values are rounded with np.rint (halves go to the even tenth).
    Nothing is clamped: a value above the uint16 range raises. Returns the array and the counts for the ledger."""
    np = _np()
    raw = np.asarray(raw, dtype=np.float64)
    pos = raw > 0
    tenths_f = np.where(pos, np.rint(raw * 10.0), 0.0)
    top = float(tenths_f.max()) if tenths_f.size else 0.0
    if top > 65535:
        raise ValueError(f"a value of {top / 10:.1f} mm is above the stored range; it is not clamped")
    tenths = tenths_f.astype(np.uint16)
    stats = {
        "n_cells": int(raw.size),
        "n_pos": int(np.count_nonzero(tenths)),
        "n_pos_lost": int(np.count_nonzero(pos & (tenths == 0))),
        "n_minus1": int(np.count_nonzero(raw == -1.0)),
        "n_minus3": int(np.count_nonzero(raw == -3.0)),
        "n_other_neg": int(np.count_nonzero((raw < 0) & (raw != -1.0) & (raw != -3.0))),
        "n_nan": int(np.count_nonzero(np.isnan(raw))),
        "n_zero": int(np.count_nonzero(raw == 0.0)),
        "n_ge_floor": int(np.count_nonzero(tenths >= FLOOR_TENTHS)),
        "max_mm": round(float(raw[pos].max()), 4) if pos.any() else None,
    }
    return tenths, stats


def _gz_is_grib(path: Path) -> tuple[bool, str]:
    """Gzip magic, a complete stream, GRIB at the start and 7777 at the end (port of the prototype's check)."""
    with open(path, "rb") as fh:
        if fh.read(2) != b"\x1f\x8b":
            return False, "no gzip magic"
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    head = b""
    tail = b""
    size = 0
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                out = decoder.decompress(chunk)
                size += len(out)
                if len(head) < 4:
                    head = (head + out)[:4]
                tail = (tail + out)[-4:]
            out = decoder.flush()
            size += len(out)
            tail = (tail + out)[-4:]
    except zlib.error as exc:
        return False, f"gzip error: {exc}"
    if not decoder.eof:
        return False, "truncated gzip stream"
    if head != b"GRIB" or tail != b"7777":
        return False, "not a single GRIB2 message"
    return True, f"{size} bytes uncompressed"


def _decode_mask_values(path, mesh: Mesh):
    """One GRIB2 file's values for the mesh cells, in mask order, as float64 mm (codes unchanged).

    The same reading as the prototype: the message's values, the bitmap must be complete, the grid must be
    3,500 by 7,000, then the decode box and the mask. pygrib is imported here, so the readers need not have it."""
    import gzip
    try:
        import pygrib
    except ImportError:
        raise HailStoreError("pygrib is not installed; the store builder needs it to read the GRIB2 files") from None
    np = _np()
    name = Path(path).name
    raw = gzip.decompress(Path(path).read_bytes())
    if raw[:4] != b"GRIB":
        raise ValueError(f"{name} is not a GRIB2 message")
    message = pygrib.fromstring(raw)
    values = message.values
    if np.ma.isMaskedArray(values) and np.ma.count_masked(values):
        raise ValueError(f"{name} has missing points in its bitmap, which MESH does not have")
    data = np.ma.getdata(values)
    if data.shape != (ROWS, COLS):
        raise ValueError(f"{name} is {data.shape[0]} by {data.shape[1]} points, expected {ROWS} by {COLS}")
    block = np.asarray(data[mesh.row0:mesh.row0 + mesh.nrow, mesh.col0:mesh.col0 + mesh.ncol], dtype=np.float64)
    return block[mesh.mask]


# Worker state: each process (or this process, when there is no pool) holds the mesh and the decoder.
_W: dict = {}


def _set_worker(mesh: Mesh, decode) -> None:
    _W["mesh"] = mesh
    _W["decode"] = decode


def _init_worker(row0: int, col0: int, mask) -> None:
    _set_worker(Mesh(row0, col0, mask), _decode_mask_values)


def _day_job(job):
    """Worker: one SPC day's file to its events. job = (ISO SPC day, path); returns (day, cell indexes, tenths,
    stats). Only values of FLOOR_TENTHS or more are events."""
    np = _np()
    day, path = job
    try:
        tenths, stats = pack_tenths(_W["decode"](path, _W["mesh"]))
    except HailStoreError:
        raise
    except Exception as exc:
        raise HailStoreError(f"{Path(path).name} could not be read: {exc}") from None
    ev = np.flatnonzero(tenths >= FLOOR_TENTHS)
    return day, ev.astype(np.int64), tenths[ev].astype(np.int64), stats


def _frame_job(paths):
    """Worker: the maximum of a chunk of two-minute frames, as uint16 tenths over the mesh cells, and the count."""
    np = _np()
    mesh = _W["mesh"]
    acc = np.zeros(mesh.n, dtype=np.uint16)
    done = 0
    for path in paths:
        try:
            tenths, _stats = pack_tenths(_W["decode"](path, mesh))
        except HailStoreError:
            raise
        except Exception as exc:
            raise HailStoreError(f"{Path(path).name} could not be read: {exc}") from None
        np.maximum(acc, tenths, out=acc)
        done += 1
    return acc, done


class _Runner:
    """Runs the per-file jobs in a pool of processes (procs > 1) or in this process. Pools use spawn, so no
    thread state is inherited."""

    def __init__(self, mesh: Mesh, procs: int, decode=None):
        self.mesh = mesh
        self.procs = max(1, int(procs or 1))
        self.pool = None
        if self.procs > 1 and decode is None:
            import multiprocessing
            from concurrent.futures import ProcessPoolExecutor
            context = multiprocessing.get_context("spawn")
            self.pool = ProcessPoolExecutor(max_workers=self.procs, mp_context=context, initializer=_init_worker,
                                            initargs=(mesh.row0, mesh.col0, mesh.mask))
        else:
            _set_worker(mesh, decode or _decode_mask_values)

    def map(self, fn, items) -> list:
        items = list(items)
        if self.pool is None:
            return [fn(item) for item in items]
        return list(self.pool.map(fn, items, chunksize=1))

    def close(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=True)
            self.pool = None


class _Http:
    """The builder's HTTP: HEAD, streamed downloads and bucket listings, with retries on 429, 5xx and network
    errors. Each thread has its own session. Requests ask for identity encoding, so sizes are file sizes."""

    def __init__(self, attempts: int = 4, pause: float = 2.0, timeout=(20, 180)):
        self.attempts = attempts
        self.pause = pause
        self.timeout = timeout
        self._local = threading.local()

    def _session(self):
        import requests
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
            self._local.session = session
        return session

    def _send(self, method: str, url: str, params=None, stream: bool = False):
        import requests
        last = "no answer"
        for attempt in range(1, self.attempts + 1):
            try:
                resp = self._session().request(method, url, params=params, stream=stream, timeout=self.timeout,
                                               allow_redirects=True, headers={"Accept-Encoding": "identity"})
            except requests.RequestException as exc:
                last = type(exc).__name__
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = f"HTTP {resp.status_code}"
                    resp.close()
                else:
                    return resp, None
            if attempt < self.attempts:
                time.sleep(self.pause * attempt)
        return None, last

    def head(self, url: str) -> dict:
        resp, err = self._send("HEAD", url)
        if resp is None:
            return {"status": None, "bytes": None, "etag": None, "last_modified": None, "error": err}
        try:
            status = resp.status_code
            size = resp.headers.get("Content-Length")
            nbytes = int(size) if status == 200 and size and size.isdigit() else None
            error = None
            if status not in (200, 404):
                error = f"HTTP {status}"
            elif status == 200 and nbytes is None:
                error = "no Content-Length"
            return {"status": status, "bytes": nbytes, "etag": resp.headers.get("ETag"),
                    "last_modified": resp.headers.get("Last-Modified"), "error": error}
        finally:
            resp.close()

    def download(self, url: str, dest: Path, expect_bytes: int | None = None) -> dict:
        import requests
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        error = "no answer"
        for attempt in range(1, self.attempts + 1):
            resp, err = self._send("GET", url, stream=True)
            if resp is None:
                error = err or error
            elif resp.status_code != 200:
                resp.close()
                return {"status": resp.status_code, "bytes": None, "sha256": None, "etag": None,
                        "last_modified": None, "error": None if resp.status_code == 404 else f"HTTP {resp.status_code}"}
            else:
                try:
                    digest = hashlib.sha256()
                    count = 0
                    with part.open("wb") as fh:
                        for chunk in resp.iter_content(1 << 20):
                            if chunk:
                                fh.write(chunk)
                                digest.update(chunk)
                                count += len(chunk)
                    etag = resp.headers.get("ETag")
                    modified = resp.headers.get("Last-Modified")
                except (requests.RequestException, OSError) as exc:
                    error = type(exc).__name__
                else:
                    if expect_bytes is None or count == expect_bytes:
                        os.replace(part, dest)
                        return {"status": 200, "bytes": count, "sha256": digest.hexdigest(), "etag": etag,
                                "last_modified": modified, "error": None}
                    error = f"{count} bytes received, {expect_bytes} expected"
                finally:
                    resp.close()
                part.unlink(missing_ok=True)
            if attempt < self.attempts:
                time.sleep(self.pause * attempt)
        part.unlink(missing_ok=True)
        return {"status": None, "bytes": None, "sha256": None, "etag": None, "last_modified": None, "error": error}

    def list_keys(self, prefix: str) -> list[str]:
        """Every key under a prefix of the NOAA bucket (S3 ListObjectsV2, all pages)."""
        keys: list[str] = []
        token = None
        while True:
            params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                params["continuation-token"] = token
            resp, err = self._send("GET", BUCKET + "/", params=params)
            if resp is None or resp.status_code != 200:
                status = resp.status_code if resp is not None else err
                raise HailStoreError(f"the NOAA bucket listing for {prefix} did not answer ({status})")
            text = resp.text
            resp.close()
            keys.extend(html.unescape(key) for key in re.findall(r"<Key>([^<]+)</Key>", text))
            found = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
            if not found:
                return keys
            token = html.unescape(found.group(1))


def newest_stamp(http, today: date) -> date:
    """The stamp of the newest 12:00 UTC file the bucket lists for today or yesterday."""
    stamps = []
    for day in (today, today - timedelta(days=1)):
        for key in http.list_keys(f"{BUCKET_FOLDER}/{PRODUCT}/{day:%Y%m%d}/"):
            found = STAMP_NAME.fullmatch(key.rsplit("/", 1)[-1])
            if found:
                stamps.append(datetime.strptime(found.group(1), "%Y%m%d").date())
    if not stamps:
        raise HailStoreError("the NOAA bucket lists no 12:00 UTC file for today or yesterday")
    return max(stamps)


def _frames_for_day(http, day: date) -> list[tuple[datetime, str]]:
    """The two-minute frames of SPC day `day`: the bucket keys stamped from 12:00 UTC on `day` up to, not
    including, 12:00 UTC on the next day (720 on a full day), sorted by time."""
    start = datetime(day.year, day.month, day.day, 12, 0)
    end = start + timedelta(days=1)
    found: dict[str, tuple[datetime, str]] = {}
    for folder in (day, day + timedelta(days=1)):
        for key in http.list_keys(f"{BUCKET_FOLDER}/{FRAME_PRODUCT}/{folder:%Y%m%d}/"):
            name = key.rsplit("/", 1)[-1]
            match = FRAME_NAME.fullmatch(name)
            if not match:
                continue
            when = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
            if start <= when < end:
                found[name] = (when, key)
    return sorted(found.values())


def _fetch_checked(http, url: str, dest: Path, nbytes: int | None = None) -> dict:
    """Download one GRIB2 file and check that it is complete. Raises HailStoreError."""
    res = http.download(url, dest, expect_bytes=nbytes)
    if res.get("error") or res.get("status") != 200:
        raise HailStoreError(f"{dest.name} could not be downloaded: {res.get('error') or 'no answer'}")
    ok, detail = _gz_is_grib(dest)
    if not ok:
        dest.unlink(missing_ok=True)
        raise HailStoreError(f"{dest.name} is not a complete GRIB2 file ({detail})")
    return res


def _ensure_file(http, url: str, dest: Path, nbytes: int) -> dict:
    """The file at dest with the expected size: the cached copy when it has that size, else a download."""
    if dest.is_file() and dest.stat().st_size == nbytes:
        return {"cached": True, "bytes": nbytes, "sha256": _sha256(dest), "etag": None, "last_modified": None}
    res = _fetch_checked(http, url, dest, nbytes)
    return {"cached": False, "bytes": res["bytes"], "sha256": res["sha256"], "etag": res["etag"],
            "last_modified": res["last_modified"]}


_COVERAGE_KEYS = ("listed", "near_duplicate_pairs", "distinct_slots", "largest_gap_s")


def _frame_coverage(frames) -> dict:
    """Coverage of a re-derived day from its listed two-minute frames, (when, key) pairs sorted by time.

    A near-duplicate is a frame less than NEAR_DUPLICATE_S seconds after the one before it: the near-identical copies
    1 to 5 s apart that 2026-05-25 carries (fifteen of them). Each near-duplicate pair counts once, so distinct_slots
    (the listed frames less the pairs) is the number of two-minute slots the frames fill; a full day has SLOTS_PER_DAY.
    With this rule 2025-06-25 has 717 slots and 2026-05-25 has 720. largest_gap_s is the longest wait between two
    consecutive frames, in seconds."""
    times = [when for when, _key in frames]
    gaps = [int((later - earlier).total_seconds()) for earlier, later in zip(times, times[1:])]
    near = sum(1 for gap in gaps if gap < NEAR_DUPLICATE_S)
    return {"listed": len(frames), "near_duplicate_pairs": near, "distinct_slots": len(frames) - near,
            "largest_gap_s": max(gaps) if gaps else 0}


def _derive_day(http, runner: _Runner, cache: Path, day: date, bucket_bytes: int, iem_bytes: int) -> dict:
    """Re-derive one SPC day as the maximum of its two-minute frames (the copy rule, for copies of different size).

    The result is cached in cache/derived with the two sizes it was derived for and its frame coverage, so a rerun
    with the same copies does not download the frames again. A cache entry without the coverage is a miss.
    Raises HailStoreError when fewer than MIN_FRAMES frames can be read."""
    np = _np()
    name = day.isoformat()
    derived = cache / "derived"
    npy = derived / f"{name}.npy"
    meta_file = derived / f"{name}.json"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    coverage = meta.get("coverage")
    if (meta.get("bucket_bytes") == bucket_bytes and meta.get("iem_bytes") == iem_bytes and npy.is_file()
            and isinstance(coverage, dict) and set(coverage) == set(_COVERAGE_KEYS)):
        try:
            tenths = np.load(npy)
        except (OSError, ValueError):
            tenths = None
        if tenths is not None and tenths.dtype == np.uint16 and tenths.shape == (runner.mesh.n,):
            return {"tenths": tenths, "frames": int(meta["frames"]), "listed": int(meta["listed"]),
                    "coverage": {key: int(coverage[key]) for key in _COVERAGE_KEYS}, "cached": True}
    frames = _frames_for_day(http, day)
    if len(frames) < MIN_FRAMES:
        raise HailStoreError(f"only {len(frames)} two-minute frames are listed for {name}; "
                             f"{MIN_FRAMES} are needed to re-derive it")
    folder = cache / "frames" / name
    folder.mkdir(parents=True, exist_ok=True)
    try:
        def fetch(item):
            _when, key = item
            dest = folder / key.rsplit("/", 1)[-1]
            _fetch_checked(http, f"{BUCKET}/{key}", dest)
            return dest

        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = sorted(pool.map(fetch, frames))
        chunks = [paths[i::runner.procs] for i in range(runner.procs)]
        parts = runner.map(_frame_job, [chunk for chunk in chunks if chunk])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    acc = np.zeros(runner.mesh.n, dtype=np.uint16)
    done = 0
    for part, count in parts:
        np.maximum(acc, part, out=acc)
        done += count
    if done < MIN_FRAMES:
        raise HailStoreError(f"only {done} two-minute frames could be read for {name}; {MIN_FRAMES} are needed")
    derived.mkdir(parents=True, exist_ok=True)
    tmp = derived / f"{name}.tmp.npy"
    np.save(tmp, acc)
    os.replace(tmp, npy)
    coverage = _frame_coverage(frames)
    meta_file.write_text(json.dumps({"day": name, "bucket_bytes": bucket_bytes, "iem_bytes": iem_bytes,
                                     "listed": len(frames), "frames": done, "coverage": coverage},
                                    sort_keys=True), encoding="utf-8")
    return {"tenths": acc, "frames": done, "listed": len(frames), "coverage": coverage, "cached": False}


def _heads(http, days: list[date]) -> dict:
    """The HEAD answers of the bucket copy and of the IEM copy of every day's 12:00 UTC file."""
    result: dict = {d: {} for d in days}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for d in days:
            stamp = stamp_for_day(d)
            futures[pool.submit(http.head, bucket_url(stamp))] = (d, "bucket")
            futures[pool.submit(http.head, iem_url(stamp))] = (d, "iem")
        for future in as_completed(futures):
            d, which = futures[future]
            result[d][which] = future.result()
    return result


def _tile_states(mesh: Mesh) -> list[tuple[int, int, list[int]]]:
    """Every tile that holds a Montana cell, in tile order: (tile row, tile column, sorted in-tile keys of its
    Montana cells). These lists are the state lists of the shards, so they decide what is outside Montana."""
    np = _np()
    tr = mesh.rows // TILE
    tc = mesh.cols // TILE
    key = (mesh.rows % TILE) * TILE + (mesh.cols % TILE)
    order = np.lexsort((key, tc, tr))
    tr, tc, key = tr[order], tc[order], key[order]
    tile_id = tr * 1000 + tc
    bounds = [0] + (np.flatnonzero(np.diff(tile_id)) + 1).tolist() + [int(tile_id.size)]
    return [(int(tr[a]), int(tc[a]), key[a:b].tolist()) for a, b in zip(bounds[:-1], bounds[1:])]


def _write_shards(t_dir: Path, mesh: Mesh, per_day: dict) -> tuple[list, int]:
    """Write one shard for every tile that holds a Montana cell, with or without events (the state list says which
    of its cells are Montana). Returns the shard entries, in tile order, and the event count.

    Events are sorted by tile, then cell key, then day, so the same events always give the same bytes."""
    np = _np()
    day_parts, row_parts, col_parts, val_parts = [], [], [], []
    for day_iso in sorted(per_day):
        ev, values = per_day[day_iso]
        if ev.size == 0:
            continue
        index = day_index(date.fromisoformat(day_iso))
        day_parts.append(np.full(ev.size, index, dtype=np.int64))
        row_parts.append(mesh.rows[ev])
        col_parts.append(mesh.cols[ev])
        val_parts.append(np.asarray(values, dtype=np.int64))
    if day_parts:
        day = np.concatenate(day_parts)
        row = np.concatenate(row_parts)
        col = np.concatenate(col_parts)
        val = np.concatenate(val_parts)
    else:
        day = row = col = val = np.zeros(0, dtype=np.int64)
    tr = row // TILE
    tc = col // TILE
    key = (row % TILE) * TILE + (col % TILE)
    order = np.lexsort((day, key, tc, tr))
    day, val, tr, tc, key = day[order], val[order], tr[order], tc[order], key[order]
    tile_id = tr * 1000 + tc
    entries = []
    for r, c, state in _tile_states(mesh):
        tid = r * 1000 + c
        a = int(np.searchsorted(tile_id, tid, side="left"))
        b = int(np.searchsorted(tile_id, tid, side="right"))
        cells = {}
        if b > a:
            cuts = [a] + (a + np.flatnonzero(np.diff(key[a:b])) + 1).tolist() + [b]
            for x, y in zip(cuts[:-1], cuts[1:]):
                cells[str(int(key[x]))] = np.stack([day[x:y], val[x:y]], axis=1).tolist()
        data = _shard_bytes(r, c, state, cells)
        rel = shard_path(r * TILE, c * TILE)
        (t_dir / Path(rel).name).write_bytes(data)
        entries.append({"rel": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "events": int(b - a)})
    return entries, int(day.size)


def _skipped_words(plan: dict, skipped: list) -> str | None:
    """The copy_check.skipped sentence. An HTTP 404 from IEM says it has no copy; a network error does not say
    which, so the sentence covers both. The bucket copy is used either way."""
    if not skipped:
        return None
    if len(skipped) == 1:
        count, when = "1 day", f"on {skipped[0].isoformat()}; that day uses the bucket copy"
    else:
        count = f"{len(skipped)} days"
        when = f"from {skipped[0].isoformat()} to {skipped[-1].isoformat()}; those days use the bucket copy"
    if all(plan[d]["iem_status"] == 404 for d in skipped):
        return f"IEM has no copy of {count} (HTTP 404), {when}"
    return f"IEM has no copy or did not answer for {count}, {when}"


def _run_build(out_dir, start: date, end: date, http, cache: Path, procs: int, mesh: Mesh, decode=None,
               max_missing: int | None = None, log=None) -> dict:
    """The build proper. build() wires in the NOAA client and the GRIB reader; tests inject fakes.

    Writes out_dir/hail (index, manifest, shards) and out_dir/ledger (one line per 12:00 file, and run.json).
    Returns the index. Raises HailStoreError before writing anything when a copy cannot be read."""
    np = _np()
    say = log or (lambda text: None)
    started = time.time()
    if end < start:
        raise HailStoreError("the last day is before the first day")
    days = _day_range(start, end)
    out = Path(out_dir)
    cache = Path(cache)
    for sub in ("files", "iem", "derived"):
        (cache / sub).mkdir(parents=True, exist_ok=True)
    say(f"checking the bucket and IEM for {len(days)} days, {start.isoformat()} to {end.isoformat()}")
    heads = _heads(http, days)
    plan = {}
    for d in days:
        stamp = stamp_for_day(d)
        bucket, iem = heads[d]["bucket"], heads[d]["iem"]
        if bucket["status"] not in (200, 404) or (bucket["status"] == 200 and bucket["bytes"] is None):
            raise HailStoreError(f"the NOAA bucket did not answer for the 12:00 UTC file stamped "
                                 f"{stamp.isoformat()} ({bucket.get('error') or 'no answer'})")
        bucket_bytes = bucket["bytes"] if bucket["status"] == 200 else None
        iem_bytes = iem["bytes"] if (iem["status"] == 200 and iem["bytes"] is not None) else None
        plan[d] = {"stamp": stamp, "decision": copy_decision(bucket_bytes, iem_bytes),
                   "bucket_bytes": bucket_bytes, "iem_bytes": iem_bytes, "iem_status": iem["status"]}
    missing = [d for d in days if plan[d]["decision"] == "missing"]
    if max_missing is not None and len(missing) > max_missing:
        raise HailStoreError(f"{len(missing)} days have no file in the bucket or at IEM, more than the "
                             f"{max_missing} allowed; the store is not written")

    jobs = []
    for d in days:
        p = plan[d]
        if p["decision"] in ("same", "skipped"):
            jobs.append((d, bucket_url(p["stamp"]), cache / "files" / bucket_name(p["stamp"]), p["bucket_bytes"],
                         "bucket"))
        elif p["decision"] == "iem":
            jobs.append((d, iem_url(p["stamp"]), cache / "iem" / bucket_name(p["stamp"]), p["iem_bytes"], "iem"))
    say(f"downloading or reusing {len(jobs)} files")
    acquired: dict = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_ensure_file, http, url, dest, nbytes): (d, dest, source)
                   for d, url, dest, nbytes, source in jobs}
        for future in as_completed(futures):
            d, dest, source = futures[future]
            acquired[d] = dict(future.result(), source=source, path=dest)

    derived: dict = {}
    runner = _Runner(mesh, procs, decode)
    try:
        for d in days:
            if plan[d]["decision"] == "rederive":
                say(f"re-deriving {d.isoformat()} from its two-minute frames (the copies differ in size)")
                derived[d] = _derive_day(http, runner, cache, d, plan[d]["bucket_bytes"], plan[d]["iem_bytes"])
        decode_jobs = [(d.isoformat(), str(acquired[d]["path"])) for d in days if d in acquired]
        say(f"decoding {len(decode_jobs)} files")
        results = runner.map(_day_job, decode_jobs)
    finally:
        runner.close()

    per_day: dict = {}
    stats_by_day: dict = {}
    for day_iso, ev, values, stats in results:
        per_day[day_iso] = (ev, values)
        stats_by_day[day_iso] = stats
    for d, res in derived.items():
        tenths = res["tenths"]
        ev = np.flatnonzero(tenths >= FLOOR_TENTHS)
        per_day[d.isoformat()] = (ev, tenths[ev].astype(np.int64))

    stage = out / f".stage-{os.getpid()}"
    shutil.rmtree(stage, ignore_errors=True)
    t_dir = stage / "hail" / "t"
    t_dir.mkdir(parents=True)
    entries, events = _write_shards(t_dir, mesh, per_day)

    compared = [d for d in days if plan[d]["bucket_bytes"] is not None and plan[d]["iem_bytes"] is not None]
    skipped = [d for d in days if plan[d]["decision"] == "skipped"]
    coverage = {d.isoformat(): derived[d]["coverage"] for d in days if d in derived}
    partial = [{"day": day, "frames": coverage[day]["distinct_slots"], "expected": SLOTS_PER_DAY}
               for day in coverage if coverage[day]["distinct_slots"] < SLOTS_PER_DAY]
    for item in partial:
        say(f"{item['day']} is partial: {item['frames']} of {SLOTS_PER_DAY} two-minute slots are filled; "
            "it is stored as the maximum of the frames that exist")
    copy_check = {
        "days_checked": len(compared),
        "days_differed": [d.isoformat() for d in days if plan[d]["decision"] == "rederive"],
        "rederived": [d.isoformat() for d in days if d in derived],
        "skipped": _skipped_words(plan, skipped),
        "frames": {d.isoformat(): derived[d]["frames"] for d in days if d in derived},
        "coverage": coverage,
        "partial": partial,
    }
    shard_bytes = sum(e["bytes"] for e in entries)
    index = {
        "format": FORMAT,
        "built_at": _utc_text(),
        "as_of": end.isoformat(),
        "window": [start.isoformat(), end.isoformat()],
        "d0": D0.isoformat(),
        "grid": dict(GRID),
        "state": STATE,
        "cells_in_state": mesh.n,
        "floor_tenths": FLOOR_TENTHS,
        "floor_in": FLOOR_IN,
        "days_expected": len(days),
        "days_present": len(days) - len(missing),
        "missing_days": [d.isoformat() for d in missing],
        "events": events,
        "shards": len(entries),
        "bytes": shard_bytes,
        "tiles": [Path(entry["rel"]).name[:-len(".json")] for entry in entries],
        "source": dict(SOURCE),
        "copy_check": copy_check,
    }
    index_bytes = _pretty(index)
    (stage / "hail" / "index.json").write_bytes(index_bytes)
    files = {"hail/index.json": {"bytes": len(index_bytes), "sha256": hashlib.sha256(index_bytes).hexdigest()}}
    for entry in entries:
        files[entry["rel"]] = {"bytes": entry["bytes"], "sha256": entry["sha256"]}
    manifest = {
        "format": MANIFEST_FORMAT,
        "as_of": index["as_of"],
        "counts": {"days_expected": index["days_expected"], "days_present": index["days_present"],
                   "events": events, "shards": index["shards"], "bytes": shard_bytes},
        "files": dict(sorted(files.items())),
    }
    (stage / "hail" / "manifest.json").write_bytes(_pretty(manifest))

    out.mkdir(parents=True, exist_ok=True)
    target = out / "hail"
    if target.exists():
        shutil.rmtree(target)
    os.replace(stage / "hail", target)
    shutil.rmtree(stage, ignore_errors=True)

    ledger_dir = out / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    # The builder's own re-decode of each re-derived day: the frame maximum over the mesh cells, as the events the
    # store holds for that day. compare checks the store against these files.
    rederived_dir = ledger_dir / "rederived"
    rederived_dir.mkdir(parents=True, exist_ok=True)
    for d in sorted(derived):
        tenths = derived[d]["tenths"]
        ev = np.flatnonzero(tenths >= FLOOR_TENTHS)
        np.savez_compressed(rederived_dir / f"{d.isoformat()}.npz", row=mesh.rows[ev].astype(np.int32),
                            col=mesh.cols[ev].astype(np.int32), tenths=tenths[ev].astype(np.int32),
                            frames=np.int64(derived[d]["frames"]))
    with (ledger_dir / "fetch.jsonl").open("w", encoding="utf-8") as fh:
        for d in days:
            p = plan[d]
            a = acquired.get(d)
            record = {
                "stamp": p["stamp"].isoformat(),
                "spc_day": d.isoformat(),
                "decision": p["decision"],
                "bucket": heads[d]["bucket"],
                "iem": heads[d]["iem"],
                "source": "frames" if d in derived else (a["source"] if a else "missing"),
                "file": str(a["path"].relative_to(cache)) if a else None,
                "file_bytes": a["bytes"] if a else None,
                "sha256": a["sha256"] if a else None,
                "cached": a["cached"] if a else None,
                "frames": ({"listed": derived[d]["listed"], "decoded": derived[d]["frames"]}
                           if d in derived else None),
                "positive_cells": stats_by_day[d.isoformat()]["n_pos"] if d.isoformat() in stats_by_day else None,
            }
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    try:
        import importlib.metadata as metadata
        pygrib_version = metadata.version("pygrib")
    except Exception:
        pygrib_version = None
    run = {
        "built_utc": _utc_text(),
        "window": index["window"],
        "as_of": index["as_of"],
        "requested_end": end.isoformat(),
        "procs": runner.procs,
        "cache": str(cache),
        "wall_seconds": round(time.time() - started, 1),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pygrib": pygrib_version,
        "downloads": sum(1 for a in acquired.values() if not a["cached"]),
        "reused": sum(1 for a in acquired.values() if a["cached"]),
        "events": events,
        "shards": index["shards"],
        "bytes": shard_bytes,
        "days_present": index["days_present"],
        "missing_days": index["missing_days"],
        "copy_check": copy_check,
    }
    (ledger_dir / "run.json").write_text(json.dumps(run, indent=1, sort_keys=True), encoding="utf-8")
    say(f"wrote {index['days_present']} days, {events} events in {index['shards']} shards")
    return index


def build(out_dir, start: date | None = None, end: date | None = None, cache=None, procs: int = 4) -> dict:
    """Build the store for the trailing window into out_dir/hail/: the daily job and the backfill.

    start and end are SPC days. By default the window is the 1,826 SPC days that end on the day before the newest
    12:00 UTC file the bucket lists (for today or yesterday). cache is a directory of downloaded GRIB2 files
    (reused when present), and procs the number of worker processes. Returns the index."""
    http = _Http()
    if end is None:
        end = day_for_stamp(newest_stamp(http, _today_utc()))
    if start is None:
        start = end - timedelta(days=WINDOW_DAYS - 1)
    mesh = montana_mesh()
    if mesh.n != CELLS_IN_STATE:
        raise HailStoreError(f"the Montana mask has {mesh.n} cells, not {CELLS_IN_STATE}; the basemap has changed")
    return _run_build(out_dir, start, end, http, Path(cache or "hail-cache"), procs, mesh,
                      max_missing=MAX_MISSING_DAYS, log=_say)


# ---------------------------------------------------------------- verify and compare

def verify(store_dir) -> dict:
    """Check a built store: the manifest hashes and counts; each shard's format, whole numbers, day order and range;
    each shard's state list (sorted cell keys) and that every cell with events is in it, and that no cell list is
    empty; the tiles list (the shard files, sorted); on a built store (not a sample, with the Montana cell count) that
    the tiles and their state lists are the Montana mask's; the window and the missing days; and the check cell for
    SPC day 2025-06-15 (see "benchland").

    The check cell is run on a built store whose window holds that day; it must hold GATE_TENTHS there, and a store
    that does not raises HailStoreError, so the daily job keeps the last release. A sample store or a window without
    that day reports it as not checked. Partial days (copy_check.partial) are listed in the report, never failed.

    Returns the report. Raises HailStoreError when the store is wrong."""
    root = Path(store_dir)
    manifest = check_manifest(root)
    index = load_index(root)
    start, end = _window_dates(index)
    if date.fromisoformat(index["as_of"]) != end:
        raise HailStoreError("the history as-of date is not the last day of its window")
    expected = (end - start).days + 1
    missing = sorted({date.fromisoformat(d) for d in index.get("missing_days", [])})
    if index.get("days_expected") != expected or index.get("days_present") != expected - len(missing):
        raise HailStoreError("the history day counts do not match its window and its missing days")
    if any(not (start <= d <= end) for d in missing):
        raise HailStoreError("a missing day lies outside the window")
    missing_set = set(missing)
    shard_paths = sorted((root / "hail" / "t").glob("*.json"))
    tiles = index["tiles"]
    if tiles != sorted(set(tiles)):
        raise HailStoreError("the history tiles list is not sorted, or it names a tile twice")
    if tiles != [path.stem for path in shard_paths]:
        raise HailStoreError("the history tiles list does not match the shard files")
    events = 0
    nbytes = 0
    state_cells = 0
    states: dict[str, list] = {}
    for path in shard_paths:
        data = path.read_bytes()
        nbytes += len(data)
        try:
            doc = json.loads(data.decode("utf-8"))
        except ValueError:
            raise HailStoreError(f"the history shard {path.name} is not valid JSON") from None
        try:
            name = tile_name(int(doc["r"]), int(doc["c"]))
        except (KeyError, TypeError, ValueError):
            raise HailStoreError(f"the history shard {path.name} is not in the expected format") from None
        state = doc.get("state")
        cells = doc.get("cells")
        if (doc.get("f") != SHARD_FORMAT or doc.get("d0") != D0.isoformat() or doc.get("u") != "tenths of a mm"
                or path.name != f"{name}.json" or not isinstance(state, list) or not isinstance(cells, dict)):
            raise HailStoreError(f"the history shard {path.name} is not in the expected format")
        if state != sorted(set(state)) or not all(type(k) is int and 0 <= k < TILE * TILE for k in state):
            raise HailStoreError(f"the history shard {path.name} has a state list that is not sorted cell keys")
        states[name] = state
        state_cells += len(state)
        for key, rows in cells.items():
            if not (key.isdigit() and 0 <= int(key) < TILE * TILE and int(key) in state):
                raise HailStoreError(f"the history shard {path.name} holds cells outside its state list")
            if not isinstance(rows, list):
                raise HailStoreError(f"the history shard {path.name} holds a cell that is not a list of days")
            if not rows:
                raise HailStoreError(f"the history shard {path.name} lists a cell with no events")
            last = None
            for pair in rows:
                if not (isinstance(pair, list) and len(pair) == 2):
                    raise HailStoreError(f"the history shard {path.name} holds a day and value that are not a pair")
                day_i, tenths = pair
                if type(day_i) is not int or type(tenths) is not int:
                    raise HailStoreError(f"the history shard {path.name} holds a number that is not a whole number")
                when = day_of_index(day_i)
                if not (start <= when <= end) or when in missing_set:
                    raise HailStoreError(f"the history shard {path.name} holds a day outside the window "
                                         "or a day with no data")
                if not (FLOOR_TENTHS <= tenths <= 65535) or (last is not None and day_i <= last):
                    raise HailStoreError(f"the history shard {path.name} holds a value below the floor "
                                         "or out of day order")
                last = day_i
                events += 1
    if events != index.get("events") or len(shard_paths) != index.get("shards") or nbytes != index.get("bytes"):
        raise HailStoreError("the history counts do not match its shards")
    if not index.get("sample") and index.get("cells_in_state") == CELLS_IN_STATE:
        if state_cells != CELLS_IN_STATE:
            raise HailStoreError("the history state lists do not hold the Montana cells")
        mask = {tile_name(r, c): keys for r, c, keys in _tile_states(montana_mesh())}
        if states != mask:
            raise HailStoreError("the history tiles and state lists do not match the Montana mask")
    row, col = cell_for(*GATE_POINT)
    value = dict(cell_events(root, *GATE_POINT, index=index) or []).get(GATE_DAY)
    checked = bool(start <= GATE_DAY <= end) and not index.get("sample")
    if checked and value != GATE_TENTHS:
        raise HailStoreError(f"the history does not hold {inches(GATE_TENTHS)} in on {fmt_date(GATE_DAY)} "
                             "at the check cell")
    benchland = {
        "point": list(GATE_POINT),
        "cell": [row, col],
        "spc_day": GATE_DAY.isoformat(),
        "tenths": value,
        "mm": None if value is None else mm_text(value),
        "gate_expected_tenths": GATE_TENTHS,
        "checked": checked,
        "matches_gate_expectation": value == GATE_TENTHS,
        "note": ("the check cell is the centre of the cell nearest Benchland (47.08 N, 110.02 W) that holds 2.01 in "
                 "on Jun 15, 2025, about 10.6 km from that point; it is checked on a built store whose window "
                 "holds that day, not on the sample"),
    }
    return {
        "ok": True,
        "format": FORMAT,
        "as_of": index["as_of"],
        "window": index["window"],
        "days_expected": index["days_expected"],
        "days_present": index["days_present"],
        "missing_days": index.get("missing_days", []),
        "events": events,
        "shards": len(shard_paths),
        "tiles": len(tiles),
        "state_cells": state_cells,
        "bytes": nbytes,
        "manifest_files": len(manifest["files"]),
        "partial_days": index.get("copy_check", {}).get("partial", []),
        "benchland": benchland,
        "checked_utc": _utc_text(),
    }


def _store_events(root: Path):
    """Every stored (day index, row, column, tenths) of a store, read from its shards."""
    np = _np()
    day_parts, row_parts, col_parts, val_parts = [], [], [], []
    for path in sorted((root / "hail" / "t").glob("*.json")):
        doc = json.loads(path.read_bytes().decode("utf-8"))
        r, c = int(doc["r"]), int(doc["c"])
        for key, rows in doc["cells"].items():
            if not rows:
                continue
            k = int(key)
            arr = np.asarray(rows, dtype=np.int64).reshape(-1, 2)
            day_parts.append(arr[:, 0])
            val_parts.append(arr[:, 1])
            row_parts.append(np.full(arr.shape[0], r * TILE + k // TILE, dtype=np.int64))
            col_parts.append(np.full(arr.shape[0], c * TILE + k % TILE, dtype=np.int64))
    if not day_parts:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, empty, empty
    return (np.concatenate(day_parts), np.concatenate(row_parts), np.concatenate(col_parts),
            np.concatenate(val_parts))


def _prototype_events(parquet: Path, python: str) -> dict:
    """The prototype's events.parquet as arrays (cell_index, day as days since 1970-01-01, mm), read by pyarrow in
    a subprocess under `python`, so this module never imports pyarrow."""
    np = _np()
    if not parquet.is_file():
        raise HailStoreError("the prototype has no events.parquet")
    with tempfile.TemporaryDirectory(prefix="hail-compare-") as tmp:
        out = Path(tmp) / "events.npz"
        proc = subprocess.run([python, "-I", "-c", _PARQUET_HELPER, str(parquet), str(out)],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not out.is_file():
            last = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
            raise HailStoreError(f"the prototype events could not be read by {python} ({last[0]})")
        with np.load(out) as data:
            return {name: data[name] for name in data.files}


def _match(keys_a, keys_b):
    """For each key in keys_a: whether keys_b holds it, and where. Both arrays are sorted and unique."""
    np = _np()
    if keys_b.size == 0:
        return np.zeros(keys_a.size, dtype=bool), np.zeros(keys_a.size, dtype=np.int64)
    pos = np.minimum(np.searchsorted(keys_b, keys_a), keys_b.size - 1)
    return keys_b[pos] == keys_a, pos


def _differences(keys_a, vals_a, keys_b, vals_b) -> int:
    """The cells that differ between two sets of one day's values: held by one side only, or by both with different
    tenths. Keys are cell keys (row * COLS + column), one per cell and day."""
    np = _np()
    oa = np.argsort(keys_a, kind="stable")
    ob = np.argsort(keys_b, kind="stable")
    ka, va, kb, vb = keys_a[oa], vals_a[oa], keys_b[ob], vals_b[ob]
    in_b, where_b = _match(ka, kb)
    in_a, _where_a = _match(kb, ka)
    differs = int(np.count_nonzero(in_b & (vb[where_b] != va))) if (ka.size and kb.size) else 0
    return int(np.count_nonzero(~in_b)) + int(np.count_nonzero(~in_a)) + differs


def compare(store_dir, prototype_dir, python: str | None = None) -> dict:
    """Compare a built store with the prototype's store cell by cell, on every day both hold.

    Mismatches are cells in one store only, or in both with different tenths, on the days both hold. The copy rule
    re-derives some days (copy_check.rederived): on those the store holds the maximum of the two-minute frames, which
    differs from the prototype's bucket copy by design, so their prototype mismatches are reported apart. The gate
    (passed) is: at least one overlapping day, and zero mismatches against the prototype on every overlapping day
    that was not re-derived; the same mask; and, on every re-derived day, the store equal to the frame maximum the
    builder recorded in ledger/rederived beside the store. Partial days (copy_check.partial) are listed and do not
    fail the gate.
    python is the interpreter that has pyarrow (default: this one)."""
    np = _np()
    root, proto = Path(store_dir), Path(prototype_dir)
    index = load_index(root)
    mesh = montana_mesh()
    try:
        grid_doc = json.loads((proto / "grid.json").read_text(encoding="utf-8"))
        crop = grid_doc["crop"]
    except (OSError, ValueError, KeyError):
        raise HailStoreError("the prototype's grid.json cannot be read") from None
    bits = np.frombuffer((proto / "mask.bin").read_bytes(), dtype=np.uint8)
    pmask = np.unpackbits(bits)[: crop["nrow"] * crop["ncol"]].reshape(crop["nrow"], crop["ncol"]).astype(bool)
    pmesh = Mesh(crop["row0"], crop["col0"], pmask)
    mask_equal = bool(pmesh.n == mesh.n and np.array_equal(pmesh.rows, mesh.rows)
                      and np.array_equal(pmesh.cols, mesh.cols))
    raw_events = _prototype_events(proto / "events.parquet", python or sys.executable)
    p_day = raw_events["day"] - (D0 - EPOCH).days
    p_tenths = np.rint(raw_events["mm"] * 10.0).astype(np.int64)
    p_row = pmesh.rows[raw_events["cell_index"]]
    p_col = pmesh.cols[raw_events["cell_index"]]

    proto_idx = np.array(sorted(day_index(date.fromisoformat(d)) for d in grid_doc.get("days", [])), dtype=np.int64)
    start, end = _window_dates(index)
    window_idx = np.arange(day_index(start), day_index(end) + 1, dtype=np.int64)
    overlap = np.intersect1d(window_idx, proto_idx)

    s_day, s_row, s_col, s_val = _store_events(root)
    keep_s = np.isin(s_day, overlap)
    keep_p = np.isin(p_day, overlap)
    grid_size = ROWS * COLS
    key_s = (s_day[keep_s] * ROWS + s_row[keep_s]) * COLS + s_col[keep_s]
    key_p = (p_day[keep_p] * ROWS + p_row[keep_p]) * COLS + p_col[keep_p]
    order_s = np.argsort(key_s, kind="stable")
    order_p = np.argsort(key_p, kind="stable")
    ks, vs = key_s[order_s], s_val[keep_s][order_s]
    kp, vp = key_p[order_p], p_tenths[keep_p][order_p]

    in_p, where_p = _match(ks, kp)
    in_s, _where_s = _match(kp, ks)
    value_differs = in_p & (vp[where_p] != vs) if kp.size else np.zeros(ks.size, dtype=bool)
    only_store = ks[~in_p]
    only_proto = kp[~in_s]
    differing = ks[value_differs]
    matched = int(np.count_nonzero(in_p & ~value_differs))
    bad = np.concatenate([only_store, only_proto, differing])
    bad_days = bad // grid_size
    copy_check = index.get("copy_check", {})
    rederived = sorted(copy_check.get("rederived", []))
    partial = list(copy_check.get("partial", []))
    rederived_idx = [day_index(date.fromisoformat(d)) for d in rederived]
    on_rederived = int(np.count_nonzero(np.isin(bad_days, rederived_idx))) if rederived_idx else 0
    counts = sorted(zip(*(x.tolist() for x in np.unique(bad_days, return_counts=True))), key=lambda t: -t[1])
    days_with = {day_of_index(int(d)).isoformat(): int(c) for d, c in counts[:20]}

    record_missing = []
    record_mismatches = 0
    for d in rederived:
        path = root / "ledger" / "rederived" / f"{d}.npz"
        if not path.is_file():
            record_missing.append(d)
            continue
        with np.load(path) as rec:
            rec_keys = rec["row"].astype(np.int64) * COLS + rec["col"].astype(np.int64)
            rec_vals = rec["tenths"].astype(np.int64)
        sel = s_day == day_index(date.fromisoformat(d))
        record_mismatches += _differences(s_row[sel] * COLS + s_col[sel], s_val[sel], rec_keys, rec_vals)

    total = int(bad.size)
    return {
        "store": str(root),
        "prototype": str(proto),
        "overlap_days": int(overlap.size),
        "store_days_not_in_prototype": int(np.setdiff1d(window_idx, proto_idx).size),
        "prototype_days_not_in_window": int(np.setdiff1d(proto_idx, window_idx).size),
        "mask_cells": {"store": mesh.n, "prototype": pmesh.n},
        "mask_equal": mask_equal,
        "basemap_sha256": {"prototype": grid_doc.get("basemap_sha256"), "here": _sha256(BASEMAP)},
        "events_in_overlap": {"store": int(ks.size), "prototype": int(kp.size)},
        "matched": matched,
        "only_in_store": int(only_store.size),
        "only_in_prototype": int(only_proto.size),
        "value_differs": int(differing.size),
        "mismatches": total,
        "mismatches_on_rederived_days": on_rederived,
        "mismatches_on_other_days": total - on_rederived,
        "rederived_days": rederived,
        "rederived_record_missing": record_missing,
        "rederived_record_mismatches": record_mismatches,
        "partial_days": partial,
        "days_with_mismatches": days_with,
        "gate": ("at least one overlapping day; zero mismatches against the prototype on every overlapping day that "
                 "was not re-derived; the same mask; and on every re-derived day the store equal to the frame maximum "
                 "the builder recorded"),
        "passed": (overlap.size > 0 and total - on_rederived == 0 and mask_equal and not record_missing
                   and record_mismatches == 0),
    }


# ---------------------------------------------------------------- command line

def _binary_get(url: str, headers=None):
    """The build's binary fetcher, imported only when a download is attempted (requests is not needed before)."""
    from . import sources as src
    return src.Fetcher().binary(url, headers)


def _iso_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date: {text!r} (use YYYY-MM-DD)") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.hail",
                                     description="The five-year hail history store (radar estimates).")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="build the store for the trailing window from the NOAA archive")
    p.add_argument("--out", default="store", help="store directory to write (default: store)")
    p.add_argument("--start", type=_iso_day, help="first SPC day, YYYY-MM-DD (default: 1,826 days before --end)")
    p.add_argument("--end", type=_iso_day,
                   help="last SPC day, YYYY-MM-DD (default: the day before the newest 12:00 UTC file)")
    p.add_argument("--cache", help="download cache directory, reused when present (default: hail-cache)")
    p.add_argument("--procs", type=int, default=4, help="worker processes (default: 4)")
    p = sub.add_parser("verify", help="check a built store: hashes, counts, shards and the Benchland cell")
    p.add_argument("store", help="store directory that holds hail/")
    p = sub.add_parser("compare", help="compare a built store with the prototype's store, cell by cell")
    p.add_argument("--store", required=True)
    p.add_argument("--prototype", required=True, help="the prototype's store directory")
    p.add_argument("--python", help="an interpreter that has pyarrow, to read the prototype (default: this one)")
    p = sub.add_parser("fixture", help="write the SAMPLE store (no network)")
    p.add_argument("--out", default=str(FIXTURE_DIR), help=f"directory to write (default: {FIXTURE_DIR})")
    p.add_argument("--addresses-from", metavar="STORE", default=None,
                   help="a built store with real address files: its address files are written into the fixture (D18)")
    p = sub.add_parser("fetch", help="download and unpack the release store")
    p.add_argument("--out", default="store", help="directory to unpack into (default: store)")
    p.add_argument("--url", default=STORE_URL)
    return parser


def _summary(index: dict) -> dict:
    keys = ("as_of", "window", "days_expected", "days_present", "missing_days", "events", "shards", "bytes",
            "copy_check")
    return {key: index[key] for key in keys}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "fixture":
            index = fixture_store(args.out, addresses_from=args.addresses_from)
            print(json.dumps({"out": str(Path(args.out).resolve()), "events": index["events"],
                              "shards": index["shards"], "as_of": index["as_of"]}))
        elif args.command == "build":
            started = time.time()
            index = build(args.out, start=args.start, end=args.end, cache=args.cache, procs=args.procs)
            print(json.dumps(dict(_summary(index), out=str(Path(args.out).resolve()),
                                  wall_seconds=round(time.time() - started, 1)), indent=1))
        elif args.command == "verify":
            print(json.dumps(verify(args.store), indent=1))
        elif args.command == "compare":
            report = compare(args.store, args.prototype, python=args.python)
            print(json.dumps(report, indent=1))
            return 0 if report["passed"] else 1
        elif args.command == "fetch":
            index = fetch_store(_binary_get, args.out, args.url)
            print(json.dumps(dict(_summary(index), out=str(Path(args.out).resolve())), indent=1))
    except HailStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
