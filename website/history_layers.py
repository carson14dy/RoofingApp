"""Five-year pictures, zone counts, recent radar hail cells and zone outlines for the Map page (B6 product P4).

What it is. Four products, all read from the store the B1 to B5 jobs write (hail/t/, hail/c/, hail/z/, hail/j/):
  hail/history/hail1.png    days with a radar estimate of 1 inch (254 tenths of a mm) or more, per 1 km cell, over the
                            five-season window of hail/index.json (1,826 SPC days). Four classes: 1 day, 2 days, 3 to 5
                            days, 6 days or more. A cell with no such day is transparent. Transparent is not "no hail":
                            a day with no stored value is "no estimate" (hail.py).
  hail/history/heat90.png   days at or above 90 F over the five seasons, from the climate grid (hail/c/, the five-season
                            record, index 9: days at or above 90 F). Six bands of 25 days: 0 to 24, 25 to 49, 50 to 74,
                            75 to 99, 100 to 124, 125 or more. A cell with no grid value is transparent.
  hail/history/zones.json   per NWS public forecast zone (the 83 zones of the current set and the 20 zones removed on
                            2022-09-13), the counts over the window of eight measures: high wind warnings, high wind watches
                            and wind advisories (zone products, hail/z/); flood watches, flood warnings and flood advisories
                            (the areal flood watch zone products in hail/z/, and the polygon products in hail/j/events.json);
                            and flash flood watches and flash flood warnings (the flash flood watch zone products in hail/z/,
                            and the polygon products in hail/j/events.json). A polygon counts in a zone when it touches one of
                            the zone's cells in a tile (the cover bits of hail/j/r<tile>.json, the touch rule of joins.py, D11).
  hail/recent/cells.json    the cells with a radar estimate of 1 inch or more on any day in the 30 days that end on as_of,
                            with each day (the day index from 2020-01-01 and tenths of a mm).
  hail/base/v/zones.json    the public zone outlines of the Iowa Environmental Mesonet ugcs service (83 MTZ zones),
                            simplified at 150 m (Douglas-Peucker on a local equirectangular projection), coordinates to five
                            decimals, with the zone code and name.

Source and terms. The radar and grid are the store's own (website/hail.py: NOAA MRMS MESH, NOAA Open Data on AWS; and
website/climate.py: NOAA nClimGrid-Daily, "US government data; NOAA declares no restrictions; attribution requested"). The
warnings are the joins' (website/joins.py: NWS and IEM archives). The zone outlines come from the Iowa Environmental
Mesonet's ugcs service. The IEM API disclaimer, as joins.py quotes it, reads "All of these services are provided as-is and
without warranty. You are free to use these services for any lawful purpose"; the outlines here are simplified.
Request: https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson?state=MT&valid=2026-10-25T00:00Z (the snapshot the research
measured: 475,411 bytes, 139 features, 83 MTZ zones; the file's SHA-256 is written into the outline file's source block).
Credit line: "Source: Iowa State University, Iowa Environmental Mesonet, ugcs service. The outlines are simplified."

Units. Radar sizes in tenths of a mm in the store (a size is shown in inches by hail.inches); days (whole); climate days
(whole); grid cells about 1 km (radar) and about 4.6 km (climate); zone counts (whole); outline coordinates in degrees (five
decimals); simplification in metres.

Missing rules (rule 5). A radar or climate shard the index lists that is missing or cannot be read makes its picture
unavailable for this update, with the reason, and the picture file is not written. A radar row that is not a day and a size
(a null size, for example) makes the radar shard unreadable; the five-season picture and the recent list come from the same
shards, so they are unavailable together. A climate cell whose days at or above 90 F are null has no grid value (climate.py
writes null where no day has a value), so it is transparent. A cell with no stored value is "no estimate", never a zero count
in the words. A zone whose product file is absent shows no count for its zone measures (null: "Data unavailable"). A measure
whose joins part did not load is null for every zone, with the reason. A joins row that names a warning the warnings file does
not hold makes the zone counts unavailable. The newest warning in the counts is the newest begin time of a counted row (a zone
row or a polygon row that touches a public zone in the window), shown as a Montana date; with no counted row, no date is
shown. Radar days the store lists as missing are named in the legends, since a cell can then count fewer days than it had.
A store older than STALE_DAYS
(hail.is_stale) keeps its pictures and its recent list, and each carries the stale sentence, as the sheet does.

Failures (D16, D20). Each part fails alone. The radar part (the five-season picture and the recent list) fails together,
because both are read from the radar shards. The climate part fails only the heat picture, the picture encoding fails only the
five-season picture, and the zone counts and the zone outlines fail on their own. The index block says which part failed and
why, in plain words. The unavailable command marks every part unavailable and removes the files they wrote.

Writes (L15). The files are written first, then the manifest (which records the index's new bytes), then the index, and the
removed files are deleted last. So no index block names a file that is not on disk.

Store (the B6 layout): hail/history/hail1.png and hail/history/heat90.png (palette PNG with alpha, on the gridded.IMAGE_BOUNDS
box), hail/history/index.json (format hail-history-pictures-v1: the classes, colours, legend words, as_of, and the bytes and
SHA-256 of each file), hail/history/zones.json (hail-zone-counts-v1), hail/recent/cells.json (hail-recent-v1), and
hail/base/v/zones.json (hail-zone-outlines-v1). hail/index.json gains "history_layers" and "recent". The manifest lists each
file with its bytes and SHA-256 (hail.check_manifest must pass).

Command line (run from the repository root):
    python -m website.history_layers build --store DIR [--cache DIR] [--zones FILE] [--offline] [--now ISO]
    python -m website.history_layers verify --store DIR [--cache DIR]
    python -m website.history_layers unavailable --store DIR --reason TEXT

numpy is imported when a picture or a count is built, and Pillow when a PNG is written or checked. The zone outlines need
no third-party reader.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import random
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import hail

FORMAT_PICTURES = "hail-history-pictures-v1"
FORMAT_ZONES = "hail-zone-counts-v1"
FORMAT_RECENT = "hail-recent-v1"
FORMAT_OUTLINES = "hail-zone-outlines-v1"
HAIL1_PATH = "hail/history/hail1.png"
HEAT_PATH = "hail/history/heat90.png"
SIDECAR_PATH = "hail/history/index.json"
ZONES_PATH = "hail/history/zones.json"
RECENT_PATH = "hail/recent/cells.json"
OUTLINE_PATH = "hail/base/v/zones.json"
INDEX_KEY = "history_layers"              # the block in hail/index.json
RECENT_KEY = "recent"                     # the block in hail/index.json
PICTURE_BOUNDS = ((43.0, -118.5), (50.5, -101.0))   # gridded.IMAGE_BOUNDS, written into the sidecar for the browser
HAIL_WIDTH = 1750                         # one pixel per 0.01 degree cell (about 1 km): the box spans 17.5 degrees
HEAT_WIDTH = 420                          # one pixel per 1/24 degree climate cell (about 4.6 km): 17.5 * 24
HAIL_ONE_INCH = hail.TENTHS_PER_INCH      # 254 tenths: 1.00 in, the NWS severe size
RECENT_DAYS = 30                          # the recent window: 30 SPC days that end on as_of
HEAT_DAYS = 90                            # 90 F, the climate record's index 9
CLIMATE_INDEX = 9                         # the position of "days at or above 90 F" in the 13-integer period record
CLIMATE_BAND_DAYS = 25                    # the heat bands are 25 days wide
CLIMATE_BANDS = 6                         # 0 to 24, 25 to 49, 50 to 74, 75 to 99, 100 to 124, 125 or more
CLIMATE_ROWS = 596                        # the nClimGrid-Daily grid: lat 24.5625 + i/24 (climate.py)
CLIMATE_COLS = 1385                       # lon -124.6875 + j/24
CLIMATE_LAT0 = 24.5625
CLIMATE_LON0 = -124.6875
CLIMATE_STEP = 24                         # cells per degree
HAIL_ALPHA = 217                          # 0.85 of 255: the colours sit over the basemap
HEAT_ALPHA = 209                          # 0.82 of 255
SIMPLIFY_M = 150.0                        # the zone outlines' Douglas-Peucker tolerance, in metres
PROJECT_LAT0 = 46.9                       # the latitude of the local projection used for the simplification
EARTH_RADIUS_M = 6371008.8
UGCS_URL = "https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson?state=MT&valid={valid}"
UGCS_VALID = "2026-10-25T00:00Z"          # the snapshot the research measured (the same file name and content)
UGCS_NAME = "ugcs-mt-valid-2026-10-25T00Z.geojson"
UGCS_ZONES = 83                           # the current public zone set (IEM's set since 2022-09-13 18:00Z)
SWITCH_UTC = "2022-09-13T18:00Z"          # the zone-set changeover (joins.IEM_SWITCH): before it the removed zones apply
USER_AGENT = "montana-hail-watch-history-layers/1 (+https://github.com/carson14dy/RoofingApp)"
TIMEOUT_S = 20
TRIES = 3
MONTANA_TZ = ZoneInfo("America/Denver")   # the company's zone: the newest warning date is shown as a Montana date (joins.py)

# The colours of the classes. Hail: the swath palette's yellow, amber, orange and red (gridded.HAIL_SWATH_BANDS), which here
# name days, not sizes. Heat: a warm ramp from pale to deep red. Each colour is a value of the picture's palette.
HAIL_CLASSES = (
    {"min": 1, "max": 1, "word": "1 day", "colour": "#f9d65c"},
    {"min": 2, "max": 2, "word": "2 days", "colour": "#f5a524"},
    {"min": 3, "max": 5, "word": "3 to 5 days", "colour": "#e8600f"},
    {"min": 6, "max": None, "word": "6 days or more", "colour": "#d1283b"},
)
HEAT_CLASSES = (
    {"min": 0, "max": 24, "word": "0 to 24 days", "colour": "#fff3c4"},
    {"min": 25, "max": 49, "word": "25 to 49 days", "colour": "#fde08a"},
    {"min": 50, "max": 74, "word": "50 to 74 days", "colour": "#fbb35a"},
    {"min": 75, "max": 99, "word": "75 to 99 days", "colour": "#f2843a"},
    {"min": 100, "max": 124, "word": "100 to 124 days", "colour": "#d6452f"},
    {"min": 125, "max": None, "word": "125 days or more", "colour": "#9e1c2b"},
)

# The eight zone measures. A measure's zone rows are (kind, significance) pairs in hail/z/; its polygon rows are pairs in
# hail/j/events.json. A flood watch is the areal flood watch (FA.A, zone rows) and the flood watch (FL.A, polygon rows). A
# flash flood watch is FF.A in both (the store holds FF.A zone rows; its polygon rows are none in the window, as joins.py
# records), and a flash flood warning is FF.W (polygon rows; the store holds no FF.W zone rows).
MEASURES = (
    {"key": "high_wind_warnings", "label": "High wind warnings", "kind": "Zone product",
     "zone": (("HW", "W"),), "polygon": ()},
    {"key": "high_wind_watches", "label": "High wind watches", "kind": "Zone product",
     "zone": (("HW", "A"),), "polygon": ()},
    {"key": "wind_advisories", "label": "Wind advisories", "kind": "Zone product",
     "zone": (("WI", "Y"),), "polygon": ()},
    {"key": "flood_watches", "label": "Flood watches", "kind": "Zone product and polygon warning",
     "zone": (("FA", "A"),), "polygon": (("FL", "A"),)},
    {"key": "flood_warnings", "label": "Flood warnings", "kind": "Polygon warning",
     "zone": (), "polygon": (("FL", "W"), ("FA", "W"))},
    {"key": "flood_advisories", "label": "Flood advisories", "kind": "Polygon warning",
     "zone": (), "polygon": (("FL", "Y"), ("FA", "Y"))},
    {"key": "flash_flood_watches", "label": "Flash flood watches", "kind": "Zone product and polygon warning",
     "zone": (("FF", "A"),), "polygon": (("FF", "A"),)},
    {"key": "flash_flood_warnings", "label": "Flash flood warnings", "kind": "Polygon warning",
     "zone": (), "polygon": (("FF", "W"),)},
)
PARTS = ("hail1", "heat90", "recent", "zones", "outlines")

WORDS = {
    "hail1_title": "Days with a radar hail estimate of 1 inch or more",
    "hail1_legend": ("Radar estimate of hail 1 inch or more: days per 1 km cell, {first} to {last}. A radar estimate, not "
                     "a measurement. A blank cell is not the same as no hail."),
    # D2 (D128(b), D117(b), D41): each unavailable or partial sentence leads with "Data unavailable." and closes with the
    # all-clear sentence, and keeps its wording
    "missing_one": ("Data unavailable. The store has no radar estimate for {day}, so a cell can count one day fewer than it "
                    "had. This is not an all-clear."),
    "missing_many": ("Data unavailable. The store has no radar estimate for {n} days, the first on {first}, so a cell can "
                     "count fewer days than it had. This is not an all-clear."),
    "heat90_title": "Days at or above 90 F",
    # D3 (D113(c), D130(a)): the grid in the ruling's words. The blank-cell sentence is a missing value (D2)
    "heat90_legend": ("Grid estimate of days at or above 90 F, July 1, 2021 to June 30, 2026, in about 1/24 degree cells "
                      "(roughly 4.6 by 3 km in Montana). Data unavailable. A blank cell has no grid value. This is not an "
                      "all-clear."),
    "zones_title": "Warnings, watches and advisories by forecast zone",
    "zones_legend": ("NWS warnings, watches and advisories by public forecast zone, {first} to {last}. Each count is every "
                     "warning, watch and advisory the store holds for the zone in that window, including those later "
                     "cancelled, upgraded or expired early. An event that stopped and then started again counts once for "
                     "each part. A polygon product counts in a zone when it touches the zone. {newest} A zero is a count of "
                     "products in the store. This is not an all-clear."),
    "zones_newest": "The newest warning in these counts is dated {date}.",
    "zones_newest_unknown": "No warning is counted in these counts, so no newest warning date is shown.",
    "recent_title": "Recent radar hail",
    "recent_legend": ("Radar estimate of hail 1 inch or more on a day in the last 30 days, {first} to {as_of}. A radar "
                      "estimate, not a measurement. Cells not listed had no such day in the store; that is not the same "
                      "as no hail."),
    # D1 (D128(a), D110(c)): the printed bubble legend, the one text build.py puts in labels.words.legend (the labels rule words
    # carry it too). D1 fixes this sentence, so the D2 lead and closing are not added to it
    "label_legend": ("-- means Data unavailable: no radar estimate of 0.25 in or more was stored for this cell; that is not "
                     "zero and not an all-clear."),
    "label_unavailable": "Data unavailable",
    "label_dash": "--",
    "unavailable": ("Data unavailable. {what} could not be built in this update: {reason}. This is not an all-clear."),
    "outline_unavailable": ("Data unavailable. Zone outlines could not be loaded in this update; that is not the same as having "
                            "no zones. This is not an all-clear."),
    "about_outlines": ("Source: Iowa State University, Iowa Environmental Mesonet, ugcs service. The outlines are "
                       "simplified."),
    "stale": hail.WORDS["stale"],
}


class HistoryError(Exception):
    """A part that cannot be built. The message is the plain reason shown in the block (no full stop: the template adds it)."""


# What a part may raise and still fail alone (rule 5, D16): the part's reason is named, and the other parts still build.
PART_ERRORS = (HistoryError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, ImportError)


def _reason(exc: BaseException, what: str) -> str:
    """The plain reason a failed part shows: the HistoryError's own words, or the part's name and the kind of error."""
    if isinstance(exc, HistoryError):
        return str(exc)
    return f"{what} could not be read ({type(exc).__name__})"


# ---------------------------------------------------------------- helpers

def _np():
    import numpy
    return numpy


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_now(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    text = str(now).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    value = datetime.fromisoformat(text)
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compact(doc) -> bytes:
    return (json.dumps(doc, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".history-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_index(store: Path) -> dict:
    try:
        doc = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HistoryError("the store index could not be read") from exc
    if not isinstance(doc, dict) or doc.get("format") != hail.FORMAT:
        raise HistoryError("the store index is not in the hail-store-v1 format")
    return doc


def _write_index(store: Path, index: dict) -> None:
    _write_atomic(store / "hail" / "index.json", _pretty(index))


def update_manifest(store: Path, written: dict, removed=(), index_bytes: bytes | None = None) -> None:
    """Replaces the manifest entries of the written files (bytes and SHA-256), drops the removed ones, and refreshes the
    entry of hail/index.json. The caller passes index_bytes when it writes the index after the manifest; otherwise the index
    file is read. Every other entry stays as it is."""
    path = store / "hail" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = dict(manifest.get("files", {}))
    for rel in removed:
        files.pop(rel, None)
    for rel, data in written.items():
        files[rel] = {"bytes": len(data), "sha256": _sha256(data)}
    if index_bytes is None:
        index_bytes = (store / "hail" / "index.json").read_bytes()
    files["hail/index.json"] = {"bytes": len(index_bytes), "sha256": _sha256(index_bytes)}
    manifest["files"] = {k: files[k] for k in sorted(files)}
    _write_atomic(path, _pretty(manifest))


def window_days(index: dict) -> tuple[date, date]:
    first, last = index["window"]
    return date.fromisoformat(first), date.fromisoformat(last)


def recent_window(as_of: date) -> tuple[date, date]:
    """The recent cells' window: the 30 SPC days that end on as_of (first, last)."""
    return as_of - timedelta(days=RECENT_DAYS - 1), as_of


# ---------------------------------------------------------------- the radar and the climate, read once

class RadarScan:
    """The radar cells of the store, read once. ge1 holds the days at 1 inch or more over the window, and recent maps
    (row, col) to [[day index, tenths], ...] for the recent window. tiles counts the shards read. missing names the listed
    shards that are not in the store; problems names the listed shards that cannot be read or hold a malformed row (their
    cells are left out, and the caller leaves the radar parts out)."""

    def __init__(self, ge1, recent, tiles, missing, problems):
        self.ge1 = ge1
        self.recent = recent
        self.tiles = tiles
        self.missing = missing
        self.problems = problems


def _whole(value, what: str) -> int:
    """A whole number from a shard. A null, a text or a fraction is not one, so the row is malformed (rule 5)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoryError(f"a {what} in the store is not a whole number")
    return value


def _radar_cells(doc: dict) -> list:
    """The cells of one radar shard as (row, col, [[day, tenths], ...]). A row that is not a day and a size, such as a null
    size, raises HistoryError, so the whole shard is reported and none of its cells is counted."""
    r0 = _whole(doc["r"], "radar tile row") * hail.TILE
    c0 = _whole(doc["c"], "radar tile column") * hail.TILE
    cells = doc.get("cells")
    if not isinstance(cells, dict):
        raise HistoryError("a radar shard holds no cells object")
    out = []
    for key_text, rows in cells.items():
        if not isinstance(key_text, str) or not key_text.isdigit() or int(key_text) >= hail.TILE * hail.TILE:
            raise HistoryError("a radar shard holds a cell key outside its tile")
        if not isinstance(rows, list):
            raise HistoryError("a radar cell holds no list of days")
        clean = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 2:
                raise HistoryError("a radar cell holds a row that is not a day and a size")
            clean.append([_whole(row[0], "radar day"), _whole(row[1], "radar size")])
        key = int(key_text)
        out.append((r0 + key // hail.TILE, c0 + key % hail.TILE, clean))
    return out


def scan_radar(store: Path, index: dict, *, recent_first: date | None = None,
               recent_last: date | None = None) -> RadarScan:
    """The radar cells of the listed shards, over the window (the day counts) and the recent window (the recent days)."""
    np = _np()
    first, last = window_days(index)
    if recent_first is None or recent_last is None:
        recent_first, recent_last = recent_window(last)
    d_first, d_last = hail.day_index(first), hail.day_index(last)
    r_first, r_last = hail.day_index(recent_first), hail.day_index(recent_last)
    ge1 = np.zeros((hail.ROWS, hail.COLS), dtype=np.int16)
    recent: dict = {}
    missing: list = []
    problems: list = []
    tiles = 0
    for name in index.get("tiles", []):
        path = store / "hail" / "t" / f"{name}.json"
        try:
            doc = json.loads(path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            missing.append(name)
            continue
        except (OSError, ValueError):
            problems.append(name)
            continue
        if not isinstance(doc, dict) or doc.get("f") != hail.SHARD_FORMAT or doc.get("r") is None or doc.get("c") is None:
            problems.append(name)
            continue
        try:
            cells = _radar_cells(doc)
        except HistoryError:
            problems.append(name)
            continue
        tiles += 1
        for row, col, rows in cells:
            days = 0
            for day, tenths in rows:
                if d_first <= day <= d_last and tenths >= HAIL_ONE_INCH:
                    days += 1
                if r_first <= day <= r_last and tenths >= HAIL_ONE_INCH:
                    recent.setdefault((row, col), []).append([day, tenths])
            if days:
                ge1[row, col] = days
    for cell in recent:
        recent[cell].sort()
    return RadarScan(ge1, recent, tiles, missing, problems)


class ClimateScan:
    """The five-season "days at or above 90 F" of each climate cell: val[i, j], or -1 where no record is stored."""

    def __init__(self, val, cells, tiles, missing, problems):
        self.val = val
        self.cells = cells
        self.tiles = tiles
        self.missing = missing
        self.problems = problems


def _climate_records(doc: dict) -> list:
    """(i, j, days at or above 90 F) of each climate cell of one tile that holds a value. climate.py writes null where no day
    has a value, so a null days value is no grid value and the cell is left out (transparent). A record that is not the
    period's list of numbers raises HistoryError, so the tile is reported."""
    out = []
    for rec in doc["cells"].values():
        if not isinstance(rec, dict):
            raise HistoryError("a climate cell is not an object")
        five = rec.get("f")
        if five is None:
            continue
        if not isinstance(five, list) or len(five) <= CLIMATE_INDEX:
            raise HistoryError("a climate record is not the list of period numbers")
        i = _whole(rec.get("i"), "climate row")
        j = _whole(rec.get("j"), "climate column")
        if not (0 <= i < CLIMATE_ROWS and 0 <= j < CLIMATE_COLS):
            raise HistoryError("a climate cell lies outside the grid")
        value = five[CLIMATE_INDEX]
        if value is None:
            continue
        out.append((i, j, _whole(value, "climate day count")))
    return out


def scan_climate(store: Path, index: dict) -> ClimateScan:
    np = _np()
    block = index.get("climate") or {}
    if block.get("state") != "loaded":
        raise HistoryError(block.get("problem") or "the climate files did not load")
    names = block.get("tile_names")
    if not isinstance(names, list) or not names:
        raise HistoryError("the climate index lists no tiles")
    val = np.full((CLIMATE_ROWS, CLIMATE_COLS), -1, dtype=np.int16)
    cells = 0
    missing: list = []
    problems: list = []
    tiles = 0
    for name in names:
        path = store / "hail" / "c" / f"{name}.json"
        try:
            doc = json.loads(path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            missing.append(name)
            continue
        except (OSError, ValueError):
            problems.append(name)
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("cells"), dict):
            problems.append(name)
            continue
        try:
            records = _climate_records(doc)
        except HistoryError:
            problems.append(name)
            continue
        tiles += 1
        for i, j, value in records:
            val[i, j] = value
            cells += 1
    return ClimateScan(val, cells, tiles, missing, problems)


# ---------------------------------------------------------------- the pictures

def _geometry(width: int):
    """(height, row centre latitudes, column centre longitudes) of a picture on gridded.IMAGE_BOUNDS."""
    from . import gridded
    w, h = gridded.image_size(width)
    lats, lons = gridded.pixel_centers(width)
    if w != width or len(lats) != h or len(lons) != w:
        raise HistoryError("the picture grid does not match the frame geometry")
    return h, lats, lons


def hail_indices(ge1, width: int = HAIL_WIDTH):
    """Palette indices of the hail picture (0 transparent, 1 to 4 the classes) and the picture's height. A pixel takes the
    cell that holds its centre: row = floor(5500 - 100 lat), col = floor(100 lon + 13000) (hail.cell_for)."""
    np = _np()
    h, lats, lons = _geometry(width)
    rows = np.floor(5500.0 - 100.0 * lats).astype(np.int64)
    cols = np.floor(100.0 * lons + 13000.0).astype(np.int64)
    ok_r = (rows >= 0) & (rows < hail.ROWS)
    ok_c = (cols >= 0) & (cols < hail.COLS)
    rows = np.clip(rows, 0, hail.ROWS - 1)
    cols = np.clip(cols, 0, hail.COLS - 1)
    values = ge1[np.ix_(rows, cols)].astype(np.int32)
    values[~ok_r, :] = 0
    values[:, ~ok_c] = 0
    idx = np.zeros((h, width), dtype=np.uint8)
    for k, cls in enumerate(HAIL_CLASSES, start=1):
        hi = cls["max"] if cls["max"] is not None else 10 ** 6
        idx[(values >= cls["min"]) & (values <= hi)] = k
    return idx, h


def heat_indices(val, width: int = HEAT_WIDTH):
    """Palette indices of the heat picture (0 with no grid value, 1 to 6 the bands) and the picture's height. A pixel takes
    the climate cell nearest its centre (the cells are 1/24 degree, and the picture has one pixel per cell)."""
    np = _np()
    h, lats, lons = _geometry(width)
    ii = np.rint((lats - CLIMATE_LAT0) * CLIMATE_STEP).astype(np.int64)
    jj = np.rint((lons - CLIMATE_LON0) * CLIMATE_STEP).astype(np.int64)
    ok_i = (ii >= 0) & (ii < CLIMATE_ROWS)
    ok_j = (jj >= 0) & (jj < CLIMATE_COLS)
    ii = np.clip(ii, 0, CLIMATE_ROWS - 1)
    jj = np.clip(jj, 0, CLIMATE_COLS - 1)
    values = val[np.ix_(ii, jj)].astype(np.int32)
    values[~ok_i, :] = -1
    values[:, ~ok_j] = -1
    idx = np.zeros((h, width), dtype=np.uint8)
    has = values >= 0
    band = np.minimum(values // CLIMATE_BAND_DAYS, CLIMATE_BANDS - 1)
    idx[has] = (band[has] + 1).astype(np.uint8)
    return idx, h


def encode_png(idx, classes: tuple, alpha: int, width: int) -> bytes:
    """A palette PNG: index 0 is transparent, index k the k-th class colour at the class alpha (per-index alpha in tRNS)."""
    from PIL import Image
    np = _np()
    rgb = [0, 0, 0]
    alphas = [0]
    for cls in classes:
        colour = cls["colour"]
        rgb += [int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)]
        alphas.append(alpha)
    h = idx.shape[0]
    img = Image.frombytes("P", (width, h), np.ascontiguousarray(idx, dtype=np.uint8).tobytes())
    img.putpalette(bytes(rgb))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, transparency=bytes(alphas))
    return buf.getvalue()


def class_counts(values, classes: tuple) -> dict:
    """Cells per class word, from a cell array of values (a value below the first class's minimum is in no class)."""
    out = {}
    for cls in classes:
        hi = cls["max"] if cls["max"] is not None else 10 ** 9
        out[cls["word"]] = int(((values >= cls["min"]) & (values <= hi)).sum())
    return out


# ---------------------------------------------------------------- the zone counts

def _zone_public_codes(index: dict) -> list[str]:
    joins = index.get("joins") or {}
    codes = set(joins.get("zone_list") or []) | set(joins.get("zone_list_before") or [])
    if not codes:
        raise HistoryError("the index lists no public forecast zones")
    return sorted(codes)


def _window_strings(first: date, last: date) -> tuple[str, str]:
    """The window in the store's time text: 12:00 UTC on the first SPC day to 12:00 UTC after the last (the store's window)."""
    return f"{first.isoformat()}T12:00Z", f"{(last + timedelta(days=1)).isoformat()}T12:00Z"


def _event_rows(rows, what: str, need_begin: bool) -> list:
    """The events of a file as product rows: each a dict whose k and s are text, and whose b is text when present (it is
    required for the polygon rows, which the window tests). A row that is not one raises HistoryError (rule 5)."""
    if not isinstance(rows, list):
        raise HistoryError(f"{what} holds no list of events")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("k"), str) or not isinstance(row.get("s"), str):
            raise HistoryError(f"{what} holds an event row without its product")
        begin = row.get("b")
        if need_begin and not isinstance(begin, str):
            raise HistoryError(f"{what} holds a warning row without its begin time")
        if begin is not None and not isinstance(begin, str):
            raise HistoryError(f"{what} holds an event row whose begin time is not text")
    return rows


def _zone_cell_map(value, what: str) -> dict:
    """A joins tile's zone map: {zone code: [in-tile cell key, ...]}, with whole-number keys below the tile's 100 cells."""
    if not isinstance(value, dict):
        raise HistoryError(f"{what} is not a map of zones")
    for code, keys in value.items():
        if not isinstance(keys, list) or not all(
                isinstance(k, int) and not isinstance(k, bool) and 0 <= k < hail.TILE * hail.TILE for k in keys):
            raise HistoryError(f"{what} holds a zone whose cells are not keys")
    return value


def count_zones(store: Path, index: dict, codes: list[str]) -> dict:
    """Counts for each public zone code: {code: {measure: count or None}}. The zone rows are read from hail/z/; the polygon
    rows from hail/j/events.json and the cover bits of each hail/j/r<tile>.json. unavailable names the measures that could
    not be counted at all (their joins part did not load), with the reason; missing_zone_files names the zones whose
    product file is absent. A malformed row, or a joins row that names a warning the warnings file does not hold, raises
    HistoryError, so the zone counts are unavailable and no other part is affected."""
    joins = index.get("joins") or {}
    parts = joins.get("parts") or {}
    reasons = joins.get("reasons") or {}
    first, last = window_days(index)
    w0, w1 = _window_strings(first, last)
    zone_kinds = {pair: m["key"] for m in MEASURES for pair in m["zone"]}
    poly_kinds = {pair: m["key"] for m in MEASURES for pair in m["polygon"]}
    unavailable: dict = {}
    zone_ok = parts.get("zones") == "loaded"
    poly_ok = parts.get("warnings") == "loaded"
    for m in MEASURES:
        if m["zone"] and not zone_ok:
            unavailable[m["key"]] = reasons.get("zones") or "the zone products did not load"
        if m["polygon"] and not poly_ok:
            unavailable[m["key"]] = reasons.get("warnings") or "the warnings did not load"
    zone_counts: dict = {}
    missing_zone_files: list = []
    newest_begin = None                       # the newest begin time of a counted row (zone or polygon), UTC text
    for code in codes:
        if not zone_ok:
            zone_counts[code] = None
            continue
        try:
            doc = json.loads((store / "hail" / "z" / f"{code}.json").read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("the zone file is not an object")
        except (OSError, ValueError):
            zone_counts[code] = None
            missing_zone_files.append(code)
            continue
        counts = {m["key"]: 0 for m in MEASURES if m["zone"]}
        for ev in _event_rows(doc.get("events", []), f"the zone file for {code}", need_begin=False):
            key = zone_kinds.get((ev["k"], ev["s"]))
            begin = ev.get("b") or ""
            if key and w0 <= begin < w1:
                counts[key] += 1
                newest_begin = max(newest_begin or "", begin)
        zone_counts[code] = counts
    touches = {(code, m["key"]): set() for code in codes for m in MEASURES if m["polygon"]}
    if poly_ok:
        code_set = set(codes)
        events = _event_rows(json.loads((store / "hail" / "j" / "events.json").read_text(encoding="utf-8"))["warnings"],
                             "the warnings file", need_begin=True)
        for tile in index.get("tiles", []):
            try:
                doc = json.loads((store / "hail" / "j" / f"{tile}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise HistoryError(f"the joins tile {tile} could not be read") from exc
            if not isinstance(doc, dict):
                raise HistoryError(f"the joins tile {tile} could not be read")
            rows = doc.get("warnings") or []
            if not isinstance(rows, list):
                raise HistoryError(f"the joins tile {tile} holds no list of warnings")
            if not rows:
                continue
            now_zones = _zone_cell_map(doc.get("zones") or {}, f"the joins tile {tile}")
            before_zones = _zone_cell_map(doc.get("zones_before") or {}, f"the joins tile {tile} (before the switch)")
            for row in rows:
                if not isinstance(row, list) or len(row) != 2:
                    raise HistoryError(f"the joins tile {tile} holds a row that is not a warning and a cover")
                ref, cover = row
                if isinstance(ref, bool) or not isinstance(ref, int) or not 0 <= ref < len(events):
                    raise HistoryError(f"the joins tile {tile} names warning {ref}, which the warnings file does not hold")
                event = events[ref]
                begin = event["b"]
                if not (w0 <= begin < w1):
                    continue
                key = poly_kinds.get((event["k"], event["s"]))
                if key is None:
                    continue
                try:
                    bits = int(cover, 16)
                except (TypeError, ValueError) as exc:
                    raise HistoryError(f"the joins tile {tile} holds a cover that is not hexadecimal") from exc
                zone_map = now_zones if begin >= SWITCH_UTC else {**now_zones, **before_zones}
                touched = False
                for code, cell_keys in zone_map.items():
                    if code in code_set and any((bits >> k) & 1 for k in cell_keys):
                        touches[(code, key)].add(ref)
                        touched = True
                if touched:
                    newest_begin = max(newest_begin or "", begin)
    out = {}
    for code in codes:
        row = {}
        for m in MEASURES:
            key = m["key"]
            if key in unavailable or (m["zone"] and zone_counts[code] is None):
                row[key] = None
                continue
            total = zone_counts[code][key] if m["zone"] else 0
            if m["polygon"]:
                total += len(touches[(code, key)])
            row[key] = total
        out[code] = row
    return {"zones": out, "unavailable": unavailable, "missing_zone_files": missing_zone_files,
            "window": [first.isoformat(), last.isoformat()], "newest_begin": newest_begin}


# ---------------------------------------------------------------- the zone outlines

def _project(lon: float, lat: float) -> tuple[float, float]:
    rad = math.radians(PROJECT_LAT0)
    return math.radians(lon) * EARTH_RADIUS_M * math.cos(rad), math.radians(lat) * EARTH_RADIUS_M


def _dp_keep(xy: list, start: int, end: int, tol: float) -> list[int]:
    """Douglas-Peucker over xy[start..end], both ends kept. Iterative, so the recursion limit never applies."""
    keep = {start, end}
    stack = [(start, end)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = xy[a]
        bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        worst, where = -1.0, -1
        for k in range(a + 1, b):
            px, py = xy[k]
            if length == 0.0:
                dist = math.hypot(px - ax, py - ay)
            else:
                dist = abs(dy * (px - ax) - dx * (py - ay)) / length
            if dist > worst:
                worst, where = dist, k
        if worst > tol:
            keep.add(where)
            stack.append((a, where))
            stack.append((where, b))
    return sorted(keep)


def simplify_ring(ring: list, tol: float = SIMPLIFY_M) -> list:
    """A closed ring simplified at tol metres. The ring is cut at the point farthest from its first point, so each half has
    two fixed ends. Coordinates are rounded to five decimals. A ring that would keep fewer than three points is kept whole."""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    rounded = [[round(x, 5), round(y, 5)] for x, y in pts]
    if n <= 3:
        return rounded + [list(rounded[0])]
    xy = [_project(x, y) for x, y in pts]
    far = max(range(1, n), key=lambda k: (math.hypot(xy[k][0] - xy[0][0], xy[k][1] - xy[0][1]), -k))
    ext = xy + [xy[0]]
    seq = _dp_keep(ext, 0, far, tol) + _dp_keep(ext, far, n, tol)[1:]
    idx: list = []
    for k in seq:
        k = 0 if k == n else k
        if not idx or idx[-1] != k:
            idx.append(k)
    if len(idx) > 1 and idx[-1] == idx[0]:
        idx.pop()
    if len(idx) < 3:
        return rounded + [list(rounded[0])]
    out = [[round(pts[k][0], 5), round(pts[k][1], 5)] for k in idx]
    out.append(list(out[0]))
    return out


def zone_outlines_from_bytes(raw: bytes) -> list[dict]:
    """The MTZ features of an IEM ugcs snapshot, read from its bytes (see read_zone_outlines)."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HistoryError("the zone file could not be read") from exc
    return _zones_from_doc(doc)


def read_zone_outlines(path: Path) -> list[dict]:
    """The MTZ features of an IEM ugcs snapshot: [{"zone", "name", "polygons": [[ring, ...], ...]}], sorted by code. Raises
    HistoryError when the file is not a feature collection, a zone has no polygon, a code repeats, or the zone count is not
    the current set's (a changed set needs a reviewed change, so it is refused rather than counted)."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise HistoryError("the zone file could not be read") from exc
    return zone_outlines_from_bytes(raw)


def _zones_from_doc(doc) -> list[dict]:
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
        raise HistoryError("the zone file is not a feature collection")
    zones: dict = {}
    for feat in doc["features"]:
        props = feat.get("properties") if isinstance(feat, dict) else None
        if not isinstance(props, dict) or not str(props.get("ugc", "")).startswith("MTZ"):
            continue
        geom = feat.get("geometry") or {}
        if geom.get("type") == "MultiPolygon":
            polys = geom.get("coordinates") or []
        elif geom.get("type") == "Polygon":
            polys = [geom.get("coordinates")]
        else:
            raise HistoryError("a zone outline is not a polygon")
        code = str(props["ugc"])
        if code in zones:
            raise HistoryError("a zone code repeats in the zone file")
        kept = [[ring for ring in poly if isinstance(ring, list) and len(ring) >= 4] for poly in polys]
        kept = [poly for poly in kept if poly]
        if not kept:
            raise HistoryError("a zone has no outline")
        zones[code] = {"zone": code, "name": str(props.get("name", "")), "polygons": kept}
    if len(zones) != UGCS_ZONES:
        raise HistoryError(f"the zone file holds {len(zones)} public zones, not the {UGCS_ZONES} of the current set")
    return [zones[k] for k in sorted(zones)]


def outline_doc(zones: list[dict], *, source: dict) -> dict:
    out = []
    for zone in zones:
        polys = [[simplify_ring(ring) for ring in poly] for poly in zone["polygons"]]
        out.append({"zone": zone["zone"], "name": zone["name"], "g": polys})
    return {"f": FORMAT_OUTLINES, "source": source, "simplify_m": SIMPLIFY_M,
            "projection": f"local equirectangular at {PROJECT_LAT0} N, metres", "zones": out}


def _ugcs_source(raw: bytes, zones: int) -> dict:
    return {"name": "Iowa Environmental Mesonet (Iowa State University), ugcs service",
            "request": UGCS_URL.format(valid=UGCS_VALID), "valid": UGCS_VALID, "bytes": len(raw),
            "sha256": _sha256(raw), "zones": zones,
            "terms": ("IEM API disclaimer, as joins.py quotes it (D44): \"All of these services are provided as-is and without "
                      "warranty. You are free to use these services for any lawful purpose\""),
            "credit": WORDS["about_outlines"]}


def _drop(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def get_zone_file(cache, zones_file, offline: bool):
    """The zone file as (path, reason): the file named, else the cache copy, else a fetch kept in the cache. A cached copy that
    is not the current zone set is removed and fetched once more. A fetched body is checked before it is written to the cache,
    so a page that is not the zone file is never kept. The path is None when the file cannot be had, and the reason is then
    plain words."""
    if zones_file is not None:
        path = Path(zones_file)
        return (path, None) if path.is_file() else (None, "the zone file named does not exist")
    if cache is None:
        return None, "no cache directory was given for the zone outlines"
    target = Path(cache) / UGCS_NAME
    if target.is_file():
        try:
            zone_outlines_from_bytes(target.read_bytes())
            return target, None
        except (HistoryError, OSError):
            _drop(target)
    if offline:
        return None, "the zone file is not in the cache and this build does not fetch"
    import requests
    last = "no answer"
    for attempt in range(1, TRIES + 1):
        try:
            resp = requests.get(UGCS_URL.format(valid=UGCS_VALID), timeout=TIMEOUT_S,
                                headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200 and resp.content:
                zone_outlines_from_bytes(resp.content)
                _write_atomic(target, resp.content)
                return target, None
            last = f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            last = type(exc).__name__
        except HistoryError as exc:
            last = f"the answer was not usable ({exc})"
        time.sleep(2 * attempt)
    return None, f"the zone file could not be fetched ({last})"


# ---------------------------------------------------------------- the recent cells

def recent_doc(scan: RadarScan, index: dict, now: datetime) -> dict:
    as_of = date.fromisoformat(index["as_of"])
    first, last = recent_window(as_of)
    rows = [[row, col, days] for (row, col), days in sorted(scan.recent.items())]
    stale = WORDS["stale"].format(as_of=as_of.isoformat()) if hail.is_stale(as_of, now) else None
    return {"f": FORMAT_RECENT, "d0": hail.D0.isoformat(), "as_of": as_of.isoformat(),
            "window": [first.isoformat(), last.isoformat()], "floor_tenths": HAIL_ONE_INCH, "u": "tenths of a mm",
            "cells": len(rows), "days": sum(len(days) for _r, _c, days in rows), "stale": stale, "rows": rows}


# ---------------------------------------------------------------- build

def _missing_days(index: dict, first: date, last: date) -> list[str]:
    """The store's listed missing radar days that fall in the window, as ISO dates, oldest first (the store lists them in its
    index, so the legends can name them: a cell can count fewer days than it had)."""
    return sorted(str(text) for text in (index.get("missing_days") or []) if first.isoformat() <= str(text) <= last.isoformat())


def _missing_sentence(days: list[str]) -> str:
    """The sentence that names the missing radar days in a legend, or "" when none is missing."""
    if not days:
        return ""
    if len(days) == 1:
        return WORDS["missing_one"].format(day=days[0])
    return WORDS["missing_many"].format(n=len(days), first=days[0])


def _montana_date(begin) -> str | None:
    """The Montana calendar date of a UTC begin time (2026-10-10T21:00Z is 2026-10-10 in Montana), or None when there is
    no begin time. joins.py shows its own lag dates the same way (its Montana local date)."""
    if not begin:
        return None
    text = str(begin).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MONTANA_TZ).date().isoformat()


def _newest_sentence(newest) -> str:
    """The sentence that names the newest warning date in the zone counts, or says that no counted warning is there."""
    return WORDS["zones_newest"].format(date=newest) if newest else WORDS["zones_newest_unknown"]


def _zones_legend(first: date, last: date, newest) -> str:
    return WORDS["zones_legend"].format(first=first.isoformat(), last=last.isoformat(), newest=_newest_sentence(newest))


def build(store, *, cache=None, zones_file=None, offline: bool = False, now=None) -> dict:
    """Writes the pictures, their sidecar, the zone counts, the recent cells and the zone outlines, the two index blocks and
    the manifest entries. Each part either builds or records its reason; the summary says which. The writes go in this order:
    the files, then the manifest (it records the index's new bytes), then the index, and the removed files last (L15)."""
    store = Path(store)
    t0 = time.monotonic()
    now_dt = _parse_now(now)
    built_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    index = _read_index(store)
    as_of = date.fromisoformat(index["as_of"])
    first, last = window_days(index)
    rfirst, rlast = recent_window(as_of)
    written: dict = {}
    removed: list = []
    failures: list = []
    pictures: dict = {}

    radar = None
    radar_reason = None
    try:
        radar = scan_radar(store, index, recent_first=rfirst, recent_last=rlast)
        if radar.missing or radar.problems:
            names = radar.missing or radar.problems
            verb = "is missing" if radar.missing else "could not be read"
            radar_reason = f"the radar file for {', '.join(names[:5])} {verb}"
    except PART_ERRORS as exc:
        radar = None
        radar_reason = _reason(exc, "the radar files")
    if radar is None or radar_reason:
        radar_reason = radar_reason or "the radar files could not be read"
        failures.append({"part": "hail1", "reason": radar_reason})
        failures.append({"part": "recent", "reason": radar_reason})
        pictures["hail1"] = {"state": "unavailable", "problem": WORDS["unavailable"].format(
            what="The five-year hail picture", reason=radar_reason)}
        removed += [HAIL1_PATH, RECENT_PATH]
        recent_block = {"state": "unavailable", "problem": WORDS["unavailable"].format(
            what="The recent radar hail list", reason=radar_reason)}
    else:
        try:
            idx, h = hail_indices(radar.ge1, HAIL_WIDTH)
            png = encode_png(idx, HAIL_CLASSES, HAIL_ALPHA, HAIL_WIDTH)
            legend = [WORDS["hail1_legend"].format(first=first.isoformat(), last=last.isoformat()),
                      _missing_sentence(_missing_days(index, first, last))]
            pictures["hail1"] = {
                "state": "loaded", "file": HAIL1_PATH, "width": HAIL_WIDTH, "height": h, "bytes": len(png),
                "sha256": _sha256(png), "cell_deg": hail.CELL_DEG, "unit": "days",
                "window": [first.isoformat(), last.isoformat()],
                "cells_with_day": int((radar.ge1 > 0).sum()),
                "cells_by_class": class_counts(radar.ge1, HAIL_CLASSES),
                "classes": [dict(c, alpha=HAIL_ALPHA) for c in HAIL_CLASSES],
                "words": {"title": WORDS["hail1_title"], "legend": " ".join(text for text in legend if text),
                          "transparent": "A blank cell is not the same as no hail."}}
            written[HAIL1_PATH] = png
        except PART_ERRORS as exc:
            reason = _reason(exc, "the five-year picture")
            failures.append({"part": "hail1", "reason": reason})
            pictures["hail1"] = {"state": "unavailable", "problem": WORDS["unavailable"].format(
                what="The five-year hail picture", reason=reason)}
            removed.append(HAIL1_PATH)
        try:
            recent = recent_doc(radar, index, now_dt)
            data = _compact(recent)
            legend = [WORDS["recent_legend"].format(first=rfirst.isoformat(), as_of=as_of.isoformat()),
                      _missing_sentence(_missing_days(index, rfirst, rlast))]
            recent_block = {"state": "loaded", "file": RECENT_PATH, "bytes": len(data), "sha256": _sha256(data),
                            "as_of": recent["as_of"], "window": recent["window"], "cells": recent["cells"],
                            "days": recent["days"], "stale": recent["stale"], "floor_tenths": HAIL_ONE_INCH,
                            "words": {"title": WORDS["recent_title"],
                                      "legend": " ".join(text for text in legend if text)}}
            written[RECENT_PATH] = data
        except PART_ERRORS as exc:
            reason = _reason(exc, "the recent radar hail list")
            failures.append({"part": "recent", "reason": reason})
            recent_block = {"state": "unavailable", "problem": WORDS["unavailable"].format(
                what="The recent radar hail list", reason=reason)}
            removed.append(RECENT_PATH)

    try:
        climate = scan_climate(store, index)
        if climate.missing or climate.problems:
            names = climate.missing or climate.problems
            verb = "is missing" if climate.missing else "could not be read"
            raise HistoryError(f"the climate file for {', '.join(names[:5])} {verb}")
        idx, h = heat_indices(climate.val, HEAT_WIDTH)
        png = encode_png(idx, HEAT_CLASSES, HEAT_ALPHA, HEAT_WIDTH)
        pictures["heat90"] = {
            "state": "loaded", "file": HEAT_PATH, "width": HEAT_WIDTH, "height": h, "bytes": len(png),
            "sha256": _sha256(png), "cell_deg": 1.0 / CLIMATE_STEP, "unit": "days",
            "window": ["2021-07-01", "2026-06-30"], "cells_with_record": climate.cells,
            "cells_by_class": class_counts(climate.val, HEAT_CLASSES),
            "classes": [dict(c, alpha=HEAT_ALPHA) for c in HEAT_CLASSES],
            "words": {"title": WORDS["heat90_title"], "legend": WORDS["heat90_legend"]}}
        written[HEAT_PATH] = png
    except PART_ERRORS as exc:
        reason = _reason(exc, "the climate files")
        failures.append({"part": "heat90", "reason": reason})
        pictures["heat90"] = {"state": "unavailable", "problem": WORDS["unavailable"].format(
            what="The days at or above 90 F picture", reason=reason)}
        removed.append(HEAT_PATH)

    zones_block: dict
    try:
        codes = _zone_public_codes(index)
        names = dict((index.get("joins") or {}).get("zone_names") or {})
        current = set((index.get("joins") or {}).get("zone_list") or [])
        counted = count_zones(store, index, codes)
        newest = _montana_date(counted["newest_begin"])     # from the counted rows, never the joins lag (D125(a))
        rows = {}
        for code in codes:
            row = {"name": names.get(code, code), "current": code in current}
            row.update(counted["zones"][code])
            rows[code] = row
        zones_doc = {"f": FORMAT_ZONES, "built_at": built_at, "as_of": index["as_of"],
                     "window": [first.isoformat(), last.isoformat()],
                     "newest_warning": {"date": newest, "words": _newest_sentence(newest)},
                     "measures": [{"key": m["key"], "label": m["label"], "kind": m["kind"]} for m in MEASURES],
                     "outline": {"file": OUTLINE_PATH, "format": FORMAT_OUTLINES},
                     "unavailable": counted["unavailable"] or None,
                     "missing_zone_files": counted["missing_zone_files"] or None,
                     "words": {"title": WORDS["zones_title"], "legend": _zones_legend(first, last, newest)},
                     "zones": rows}
        zdata = _compact(zones_doc)
        partial = bool(counted["unavailable"] or counted["missing_zone_files"])
        zones_block = {"state": "partial" if partial else "loaded", "file": ZONES_PATH, "bytes": len(zdata),
                       "sha256": _sha256(zdata), "zones": len(codes), "newest_warning": newest,
                       "unavailable": counted["unavailable"] or None,
                       "missing_zone_files": counted["missing_zone_files"] or None}
        written[ZONES_PATH] = zdata
        if partial:
            failures.append({"part": "zones", "reason": "some zone counts could not be made, as the block says"})
    except PART_ERRORS as exc:
        reason = _reason(exc, "the zone files")
        failures.append({"part": "zones", "reason": reason})
        zones_block = {"state": "unavailable", "problem": WORDS["unavailable"].format(
            what="The zone counts", reason=reason)}
        removed.append(ZONES_PATH)

    try:
        zone_path, why = get_zone_file(cache, zones_file, offline)
        if zone_path is None:
            raise HistoryError(why or "the zone file is not available")
        raw = zone_path.read_bytes()
        zones = zone_outlines_from_bytes(raw)
        doc = outline_doc(zones, source=_ugcs_source(raw, len(zones)))
        data = _compact(doc)
        outline_block = {"state": "loaded", "file": OUTLINE_PATH, "bytes": len(data), "sha256": _sha256(data),
                         "zones": len(zones), "simplify_m": SIMPLIFY_M, "source": doc["source"]}
        written[OUTLINE_PATH] = data
    except PART_ERRORS as exc:
        reason = _reason(exc, "the zone outlines")
        failures.append({"part": "outlines", "reason": reason})
        outline_block = {"state": "unavailable", "problem": WORDS["outline_unavailable"], "detail": reason}
        removed.append(OUTLINE_PATH)

    state = "loaded" if not failures else ("unavailable" if len(failures) >= len(PARTS) else "partial")
    stale = WORDS["stale"].format(as_of=as_of.isoformat()) if hail.is_stale(as_of, now_dt) else None
    sidecar = {"f": FORMAT_PICTURES, "built_at": built_at, "as_of": index["as_of"],
               "window": [first.isoformat(), last.isoformat()], "bounds": [list(p) for p in PICTURE_BOUNDS],
               "sample": False, "state": state, "stale": stale, "pictures": pictures,
               "missing_days": _missing_days(index, first, last),
               "classes": {"hail1": [dict(c, alpha=HAIL_ALPHA) for c in HAIL_CLASSES],
                           "heat90": [dict(c, alpha=HEAT_ALPHA) for c in HEAT_CLASSES]},
               "failures": failures, "words": WORDS}
    sdata = _pretty(sidecar)
    written[SIDECAR_PATH] = sdata
    block = {"state": state,
             "problem": None if state == "loaded" else WORDS["unavailable"].format(
                 what="Part of the five-year history layers", reason="; ".join(f["reason"] for f in failures)),
             "as_of": index["as_of"], "window": [first.isoformat(), last.isoformat()], "built_at": built_at,
             "sidecar": {"file": SIDECAR_PATH, "bytes": len(sdata), "sha256": _sha256(sdata)},
             "pictures": {k: {kk: vv for kk, vv in v.items() if kk not in ("classes", "words", "cells_by_class")}
                          for k, v in pictures.items()},
             "zones": zones_block, "outlines": outline_block, "failures": failures,
             "seconds": round(time.monotonic() - t0, 1)}
    index[INDEX_KEY] = block
    index[RECENT_KEY] = recent_block
    index_bytes = _pretty(index)
    for rel, data in written.items():
        _write_atomic(store / rel, data)
    update_manifest(store, written, removed=removed, index_bytes=index_bytes)
    _write_atomic(store / "hail" / "index.json", index_bytes)
    for rel in removed:
        if rel not in written and (store / rel).is_file():
            (store / rel).unlink()
    return {"state": state, "pictures": {k: v.get("state") for k, v in pictures.items()},
            "zones": zones_block.get("state"), "outlines": outline_block.get("state"),
            "recent": recent_block.get("state"), "failures": failures,
            "seconds": round(time.monotonic() - t0, 1), "bytes": {k: len(v) for k, v in sorted(written.items())}}


def unavailable(store, reason: str) -> dict:
    """Marks every part unavailable with the reason and removes the files they wrote (D20). The manifest is written before the
    index (it records the index's bytes), and the removed files go last, so no block names a file that is not on disk."""
    store = Path(store)
    text = " ".join(str(reason).split())
    if not text:
        raise HistoryError("give the reason the history layers are unavailable (--reason TEXT)")
    index = _read_index(store)
    problem = WORDS["unavailable"].format(what="The five-year history layers", reason=text)
    index[INDEX_KEY] = {"state": "unavailable", "problem": problem, "as_of": index.get("as_of"),
                        "built_at": _utc_now(), "failures": [{"part": "all", "reason": text}]}
    index[RECENT_KEY] = {"state": "unavailable", "problem": WORDS["unavailable"].format(
        what="The recent radar hail list", reason=text)}
    removed = [HAIL1_PATH, HEAT_PATH, SIDECAR_PATH, ZONES_PATH, RECENT_PATH, OUTLINE_PATH]
    index_bytes = _pretty(index)
    update_manifest(store, {}, removed=removed, index_bytes=index_bytes)
    _write_atomic(store / "hail" / "index.json", index_bytes)
    for rel in removed:
        if (store / rel).is_file():
            (store / rel).unlink()
    return {"state": "unavailable", "problem": problem}


# ---------------------------------------------------------------- verify

def verify(store, sample: int = 20, seed: int = 6) -> dict:
    """Checks the files the index names: their sizes and SHA-256 against the manifest; the PNG sizes, modes and
    transparency; the outline set (83 zones, closed rings); the zone counts recounted for a sample of zones; and the recent
    cells recounted from the shards. A block that says unavailable is checked for its removed files only."""
    store = Path(store)
    checks: list = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    index = _read_index(store)
    block = index.get(INDEX_KEY)
    check("history block present", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    manifest = json.loads((store / "hail" / "manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    if block.get("state") == "unavailable":
        for rel in (HAIL1_PATH, HEAT_PATH, SIDECAR_PATH, ZONES_PATH, RECENT_PATH, OUTLINE_PATH):
            check(f"{rel} is removed while unavailable", not (store / rel).exists())
        return {"ok": all(c["pass"] for c in checks), "checks": checks, "note": block.get("problem")}
    for rel in (HAIL1_PATH, HEAT_PATH, SIDECAR_PATH, ZONES_PATH, RECENT_PATH, OUTLINE_PATH):
        path = store / rel
        entry = files.get(rel)
        if entry is None:
            check(f"{rel} is not listed, so it is not on disk", not path.exists())
            continue
        if not path.is_file():
            check(f"{rel} present", False, "the manifest lists the file but it is missing")
            continue
        data = path.read_bytes()
        check(f"{rel} listed with its bytes and SHA-256",
              entry["bytes"] == len(data) and entry["sha256"] == _sha256(data))
    try:
        from PIL import Image
        for rel, width in ((HAIL1_PATH, HAIL_WIDTH), (HEAT_PATH, HEAT_WIDTH)):
            if (store / rel).is_file():
                with Image.open(store / rel) as img:
                    check(f"{rel} is a palette PNG {width} px wide with transparency",
                          img.size[0] == width and img.mode == "P" and img.info.get("transparency") is not None,
                          str(img.size))
    except ImportError:
        check("PNG checks", True, "Pillow is not installed; the PNG checks were skipped")
    if (store / ZONES_PATH).is_file():
        zdoc = json.loads((store / ZONES_PATH).read_text(encoding="utf-8"))
        codes = sorted(zdoc["zones"])
        picked = random.Random(seed).sample(codes, min(sample, len(codes)))
        counted = count_zones(store, index, picked)
        differ = [c for c in picked
                  if counted["zones"][c] != {k: v for k, v in zdoc["zones"][c].items() if k not in ("name", "current")}]
        check("zone counts recounted for a sample of zones", not differ, f"{len(picked)} zones; differing: {differ[:5]}")
    if (store / OUTLINE_PATH).is_file():
        odoc = json.loads((store / OUTLINE_PATH).read_text(encoding="utf-8"))
        check("outline file holds the current 83 zones", len(odoc.get("zones", [])) == UGCS_ZONES,
              str(len(odoc.get("zones", []))))
        closed = all(ring[0] == ring[-1] for z in odoc["zones"] for poly in z["g"] for ring in poly)
        check("every outline ring is closed", closed)
    if (store / RECENT_PATH).is_file():
        rdoc = json.loads((store / RECENT_PATH).read_text(encoding="utf-8"))
        scan = scan_radar(store, index, recent_first=date.fromisoformat(rdoc["window"][0]),
                          recent_last=date.fromisoformat(rdoc["window"][1]))
        # Each cell with its days, as recent_doc writes them (L17): a changed day size fails, not only a changed cell.
        expect = [[row, col, days] for (row, col), days in sorted(scan.recent.items())]
        check("recent cells and their days recounted from the shards", expect == rdoc["rows"],
              f"{len(rdoc['rows'])} cells")
    dashes = [name for name, text in WORDS.items() if isinstance(text, str) and ("\u2014" in text or "\u2013" in text)]
    check("no em or en dash in the words", not dashes, ", ".join(dashes))
    return {"ok": all(c["pass"] for c in checks), "checks": checks,
            "block": {k: block.get(k) for k in ("state", "as_of", "window")}}


# ---------------------------------------------------------------- command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.history_layers", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the pictures, the zone counts, the recent cells and the zone outlines")
    b.add_argument("--store", required=True)
    b.add_argument("--cache", default=None, help="the cache for the zone outline file (kept under its own name)")
    b.add_argument("--zones", default=None, help="the zone file to read (skips the cache and the fetch)")
    b.add_argument("--offline", action="store_true")
    b.add_argument("--now", default=None, help="the build clock, ISO 8601 (default: the current time)")
    v = sub.add_parser("verify", help="check the files and recount a sample")
    v.add_argument("--store", required=True)
    u = sub.add_parser("unavailable", help="mark the history layers unavailable with a reason")
    u.add_argument("--store", required=True)
    u.add_argument("--reason", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "build":
            result = build(Path(args.store), cache=Path(args.cache) if args.cache else None,
                           zones_file=Path(args.zones) if args.zones else None, offline=args.offline, now=args.now)
            print(json.dumps(result, indent=1, sort_keys=True, default=str))
            return 0
        if args.cmd == "verify":
            result = verify(Path(args.store))
            print(json.dumps(result, indent=1, sort_keys=True, default=str))
            return 0 if result["ok"] else 1
        result = unavailable(Path(args.store), args.reason)
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    except HistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
