"""Landmark points (B6 P3): schools, hospitals, airports, fire stations and local parks, one small file per B1 tile.

What it is: the points a reader looks for on the map, taken from public lists: the schools, hospitals, public-use airports,
fire and EMS stations and local parks named below. A point is where a list puts a place. It does not say that the place is
open, staffed or in use today, and no point is a rating of any kind. Each point keeps its name, its kind, its position and
its source list, and nothing else from the list (no owner, contact, address or other attribute: decision 6 in spirit).

Sources (read live on 2026-10-25; a second run reads the cache and makes no request):
  schools       NCES EDGE public school locations 2024-25 (layer 0 of EDGE_GEOCODE_PUBLICSCH_2425) and private school
                locations 2023-24 (EDGE_GEOCODE_PRIVATESCH_2324), state FIPS 30. Position: the layer's LAT and LON
                attributes. Terms: "All information contained in this file is in the public domain."
  hospitals     USGS The National Map, Hospitals/Medical Centers (layer 49 of the national structures map service, state MT;
                layer 14 is the same 63 rows). Terms: the layer has no rights line; the service's copyright line gives the
                October 2026 refresh. Used when that layer answers with named Montana rows. Only when it answers with no Montana
                rows does the rule use the HIFLD copy of the state licensure list (layer 0 of HIFLD_Hospitals, STATUS OPEN); that
                copy's licence is not confirmed (no licence text in the item or the layer, and the source credit names the state
                licensure list). The build records which one it used and why.
  airports      FAA National Airspace System Resources, the 28-day NASR airport file APT.zip for the cycle in force on the run
                date (2026-10-01 on 2026-10-25). Public-use airports only: record type APT, facility type AIRPORT, facility use
                PU and status O. Position: the airport reference point (formatted degrees, minutes and seconds). Terms: U.S.
                government data; the subscription page has no rights line for the file (not verified in the file). The HIFLD
                aviation copy is not used: it is an older cycle (effective 2025/06/12 on its Montana rows).
  fire stations USGS The National Map, Fire Stations/EMS Stations (layer 51, state MT; layer 16 is the same 461 rows). Terms as
                for the hospitals.
  parks         Two lists. PAD-US 4.1 Fee layer, local parks (Des_Tp LP, State_Nm MT): the point is the pole of inaccessibility
                of the park polygon, computed here to about 1 metre, and the PAD-US name is kept. TIGER/Line 2026 area landmarks
                with MTFCC K2180 (Park) and K2188 (incorporated place park, forest or recreation area), at the Census interior
                point, named rows only. A named TIGER park point inside a PAD-US park polygon, or within 150 m of its label point,
                is the same park and is not shown twice: the PAD-US row stands. So Rose Garden (the PAD-US name for the Missoula
                park that TIGER calls Rose Park) is the name shown; that is an open point for the owner. Two park rows with the same
                name within 150 m are one park. State parks (K2184 and the PAD-US state parks) are areas for the basemap part (P2),
                not points here. PAD-US terms: "This content describes the PAD-US dataset which is in the public domain." TIGER
                terms: not copyrighted; free to use with acknowledgement to the U.S. Census Bureau as the source.
  places of worship (HELD)  The FEMA copy of an IRS-based places of worship list (layer 42), rows with the point-address match only
                (LOC_NAME POINTADDRESS, state MT). Its copyright line says the points were geocoded by a commercial geocoder whose
                terms are not read, so the kind is held for counsel. It is built and counted, but its rows are never written into the
                store while it is held: the store is published as files, so a held row written there would be published. The index
                records the held count and the reason.

Units and names: positions are WGS 84 degrees, rounded to five decimals (about 1 metre). Names keep the source's words. An all
capital name is title-cased by the repository's rule (stations.display_name). An airport name with no airport word gets "Airport"
(MISSOULA MONTANA is Missoula Montana Airport), and the abbreviations INTL, RGNL, MUNI, FLD and MEM are written out. The
placeholders "unknown", "unnamed", "none" and "n/a" are dropped, and so is a row with no name or no position.

Missing and failures (D16, D20): a source that cannot be requested, read or checked (a failed request with no cached copy, an
answer that is not the expected JSON or zip, a missing field, a count below the source's floor) fails that source. Every kind that
uses a failed source is unavailable as a whole, because a list with one part missing would read as no school, hospital, airport,
fire station or park in that part. The index gives the kind "Data unavailable" words, the reason and the failing source. A kind
that is unavailable has no points in the store, and the browser must draw "Data unavailable", never an absence. Only a failure of
every kind makes the block unavailable, and the unavailable command removes this part's files. Nothing in this module reads an
AI, a vendor or a product name, and no sentence in it says that a place is safe, clear or in use.

Store (format hail-landmarks-v1), see the B6 brief:
  hail/base/p/<tile>.json   one file per B1 tile (hail.tile_name) that holds at least one shown point:
                            {"f": "hail-landmarks-v1", "t": "<tile>", "n": count, "i": [[lon, lat, kind, name, source], ...]}
                            kind is one short code: s school, h hospital, a airport, f fire station, p park. source is one of
                            the source keys in SOURCES. Rows are sorted by kind, name, position and source, so the same input gives
                            the same bytes. Each file is under BUDGET_GZIP bytes when gzip compressed (checked by verify).
  hail/base/index.json      this part's own index. The "landmarks" key belongs to this module; the other parts keep their keys.
  hail/manifest.json        lists every p file and the base index with its bytes and SHA-256 (hail.check_manifest must pass).
                            The integrator mirrors the block into hail/index.json as a "base" block (state, as_of, counts,
                            sources, bytes); this module does not write hail/index.json.

Command line (run from the repository root):
    python -m website.landmarks build --store DIR --cache DIR [--now ISO] [--offline] [--refresh] [--deadline-at EPOCH]
                                      [--metrics FILE]
    python -m website.landmarks verify --store DIR
    python -m website.landmarks unavailable --store DIR --reason TEXT
The build needs the hail store (hail/index.json and hail/manifest.json) for the tile list. It uses only the standard library, the
repository's stations helper for names, and the requests package for downloads (the store job installs it). pyshp reads the TIGER
file (the store job installs it; a missing pyshp fails only the parks source, D20).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import io
import itertools
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from . import hail
from . import stations as S

FORMAT = "hail-landmarks-v1"
INDEX_KEY = "landmarks"                   # the block in hail/base/index.json (this module's key)
BASE_INDEX = "hail/base/index.json"
P_PREFIX = "hail/base/p/"                 # the shard folder, rebuilt whole by each build
BUDGET_GZIP = 20_000                      # the brief: each shard under this many bytes gzip
MONTANA_BOX = (-116.2, 44.3, -103.9, 49.1)            # west, south, east, north (the state with a margin)
MISSOULA_BOX = (-114.15, 46.80, -113.90, 46.95)       # the box the verify check reads (the Missoula area)
MERGE_M = 150.0                           # a PAD-US park and a named TIGER park this close are one park
PACE_S = 0.2                              # at least this long between two requests
TRIES = 3                                 # a request is tried this many times (2 s, then 4 s between tries)
REQUEST_TIMEOUT = (20, 180)               # seconds to connect, and to wait for each read
MAX_PAGES = 50                            # a list is read in at most this many pages (no list is that long)
USER_AGENT = "montana-hail-watch-landmarks/1 (+https://github.com/carson14dy/RoofingApp)"
STATE_FIPS = "30"
FAA_ANCHOR = date(2026, 10, 1)            # an effective date of the 28-day NASR cycle (the subscription pages)
FAA_DAYS = 28
REASON_NO_ANSWER = "the source did not answer"
HELD_REASON = ("the geocoder's terms are a counsel question, so the rows are not written to the store while the kind is held")
RULE_TEXT = ("A point is kept with its name, kind, position and source. Positions are rounded to five decimals. An all-capital "
             "name is title-cased (stations.display_name); an airport name gets Airport when no airport word is in it. A PAD-US "
             "park keeps its name and label point; a named TIGER park point inside such a polygon, or within 150 m of its label "
             "point, is dropped as the same park, and parks with the same name within 150 m are one park. Each point sits in the "
             "B1 tile that holds its position (hail.cell_for). A kind with a failed source is unavailable as a whole.")
TIGER_PARK_CODES = ("K2180", "K2188")    # Park; incorporated place park, forest or recreation area (state parks: P2)

KIND_CODE = {"school": "s", "hospital": "h", "airport": "a", "fire": "f", "park": "p", "church": "c"}
KIND_NAME = {code: kind for kind, code in KIND_CODE.items()}
KIND_ORDER = ("school", "hospital", "airport", "fire", "park", "church")
HELD = frozenset({"church"})              # the owner has not cleared these kinds: built and counted, never written
KIND_LABEL = {"school": "Schools", "hospital": "Hospitals", "airport": "Airports", "fire": "Fire stations",
              "park": "Parks", "church": "Places of worship"}
KIND_PLURAL = {"school": "schools", "hospital": "hospitals", "airport": "airports", "fire": "fire stations",
               "park": "parks", "church": "places of worship"}

NATIONAL_MAP = "https://carto.nationalmap.gov/arcgis/rest/services/structures/MapServer"   # the USGS map service (layers below)
SOURCES = {
    "nces_public": {
        "kind": "school", "label": "NCES EDGE public school locations, 2024-25", "format": "arcgis",
        "url": "https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0",
        "query": {"where": "STFIP='30'", "outFields": "NAME,LAT,LON", "returnGeometry": "false"},
        "fields": ("NAME", "LAT", "LON"), "floor": 600, "as_of": "2024-25 school year",
        "credit": "National Center for Education Statistics, EDGE public school locations, 2024-25.",
        "terms": "All information contained in this file is in the public domain.",
    },
    "nces_private": {
        "kind": "school", "label": "NCES EDGE private school locations, 2023-24", "format": "arcgis",
        "url": "https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PRIVATESCH_2324/MapServer/0",
        "query": {"where": "STFIP='30'", "outFields": "NAME,LAT,LON", "returnGeometry": "false"},
        "fields": ("NAME", "LAT", "LON"), "floor": 80, "as_of": "2023-24 school year",
        "credit": "National Center for Education Statistics, EDGE private school locations, 2023-24.",
        "terms": "All information contained in this file is in the public domain.",
    },
    "usgs_hospitals": {
        "kind": "hospital", "label": "USGS The National Map, hospitals and medical centers", "format": "arcgis",
        "url": NATIONAL_MAP + "/49",
        "query": {"where": "STATE='MT'", "outFields": "NAME", "returnGeometry": "true", "outSR": "4326"},
        "fields": ("NAME",), "floor": 40, "as_of": "October 2026 refresh (service copyright line)",
        "credit": "USGS The National Map, hospitals and medical centers, October 2026 refresh.",
        "terms": ("The layer has no rights line. The service's copyright line gives the October 2026 refresh. "
                  "The USGS terms page was not read in this build."),
    },
    "hifld_hospitals": {
        "kind": "hospital", "label": "HIFLD copy of the state licensure list (hospitals)", "format": "arcgis",
        "url": "https://services2.arcgis.com/PYn6bWCjT6bhw1z3/arcgis/rest/services/HIFLD_Hospitals/FeatureServer/0",
        "query": {"where": "STATE='MT' AND STATUS='OPEN'", "outFields": "NAME,LATITUDE,LONGITUDE,STATUS",
                  "returnGeometry": "false"},
        "fields": ("NAME", "LATITUDE", "LONGITUDE", "STATUS"), "floor": 40, "as_of": "layer last edited, see meta",
        "credit": "Hospital list copied from the state licensure list (copy by the Homeland Infrastructure Foundation-Level Data).",
        "terms": ("No licence text in the item or the layer; the source credit names the state licensure list. Its terms are "
                  "not confirmed, so this source is only the fallback."),
    },
    "faa_nasr": {
        "kind": "airport", "label": "FAA NASR airport file, the cycle in force on the run date", "format": "faa",
        "url": "https://nfdc.faa.gov/webContent/28DaySub/{cycle}/APT.zip",
        "floor": 50, "as_of": "the cycle's effective date",
        "credit": "Federal Aviation Administration, National Airspace System Resources airport data, the cycle named in About.",
        "terms": ("U.S. government data. The subscription page has no rights line for the file; that is not verified in the file."),
    },
    "usgs_fire": {
        "kind": "fire", "label": "USGS The National Map, fire and EMS stations", "format": "arcgis",
        "url": NATIONAL_MAP + "/51",
        "query": {"where": "STATE='MT'", "outFields": "NAME", "returnGeometry": "true", "outSR": "4326"},
        "fields": ("NAME",), "floor": 300, "as_of": "October 2026 refresh (service copyright line)",
        "credit": "USGS The National Map, fire and EMS stations, October 2026 refresh.",
        "terms": ("The layer has no rights line. The service's copyright line gives the October 2026 refresh. "
                  "The USGS terms page was not read in this build."),
    },
    "padus_local": {
        "kind": "park", "label": "PAD-US 4.1 local parks (Fee layer, Des_Tp LP)", "format": "padus",
        "url": "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Managers_PADUS/FeatureServer/0",
        "query": {"where": "State_Nm='MT' AND Des_Tp='LP'", "outFields": "OBJECTID,Unit_Nm,Des_Tp,State_Nm",
                  "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "6"},
        "fields": ("Unit_Nm", "Des_Tp", "State_Nm"), "floor": 300, "as_of": "layer last edited, see meta",
        "credit": "USGS Gap Analysis Project, Protected Areas Database of the United States (PAD-US) 4.1, local parks.",
        "terms": ("The layer says: \"This content describes the PAD-US dataset which is in the public domain.\" The PAD-US terms "
                  "of use apply to the data."),
    },
    "tiger_park": {
        "kind": "park", "label": "TIGER/Line 2026 area landmarks (park codes K2180 and K2188)", "format": "tiger",
        "url": "https://www2.census.gov/geo/tiger/TIGER2026/AREALM/tl_2026_30_arealm.zip",
        "floor": 40, "as_of": "TIGER/Line 2026",
        "credit": "U.S. Census Bureau, TIGER/Line 2026 area landmarks.",
        "terms": ("Not copyrighted; free to use in a product or publication. Acknowledgement to the U.S. Census Bureau as the "
                  "source is required."),
    },
    "fema_worship": {
        "kind": "church", "label": "FEMA copy of the places of worship list (point-address rows)", "format": "arcgis",
        "url": ("https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
                "All_Places_Of_Worship__HiFLD_Open_/FeatureServer/42"),
        "query": {"where": "STATE='MT' AND LOC_NAME='POINTADDRESS'", "outFields": "NAME,X,Y,LOC_NAME,STATE",
                  "returnGeometry": "false"},
        "fields": ("NAME", "X", "Y", "LOC_NAME", "STATE"), "floor": 300, "as_of": "layer last edited, see meta",
        "credit": "FEMA copy of an IRS-based places of worship list (held; not shown).",
        "terms": ("The layer says the data has no use limitations. Its copyright line says the points were geocoded by a "
                  "commercial geocoder whose terms are not read, so the kind is held for counsel."),
    },
}
ORDER = ("nces_public", "nces_private", "usgs_hospitals", "usgs_fire", "faa_nasr", "padus_local", "tiger_park",
         "fema_worship")
KIND_SOURCES = {"school": ("nces_public", "nces_private"), "airport": ("faa_nasr",), "fire": ("usgs_fire",),
                "park": ("padus_local", "tiger_park"), "church": ("fema_worship",)}
MISSOULA_CHECK = (("school", "Loyola Sacred Heart High School"), ("school", "Hellgate High School"),
                  ("airport", "Missoula Montana Airport"), ("hospital", "Community Medical Center"),
                  ("hospital", "Saint Patrick Hospital"))

WORDS = {
    "what": ("A landmark is a point from a public list: a school, a hospital, a public-use airport, a fire or EMS station or a "
             "local park. The point is where the list puts it. The list does not say that the place is open or staffed today."),
    "rule": ("Each point keeps its name, its kind, its position and the list it came from. Nothing else from a list is kept."),
    "parks": ("A park point sits near the middle of the park. The park outline comes from the protected areas list."),
    "airports": "Only public-use airports that are operational are shown. Heliports are not shown.",
    "held": ("Places of worship are not shown on the map. Their list is under review, so no church is drawn or named."),
    "kind_unavailable": ("Data unavailable: {plural} could not be loaded in this update; that is not the same as no {plural}. "
                         "This is not an all-clear."),
    "all_unavailable": ("Data unavailable: landmarks could not be loaded in this update; that is not the same as no landmarks. "
                        "This is not an all-clear."),
    "source_item": "{label} ({as_of}). {credit}",
    "hospital_usgs": "Hospitals come from the USGS list of hospitals and medical centers.",
    "hospital_hifld": ("Hospitals come from a copy of the state licensure list, because the USGS list named no Montana "
                       "hospital in this update."),
}

class LandmarkError(Exception):
    """A file or figure that cannot be used. The message is plain words, lower case, with no full stop (the other parts'
    pattern)."""


class SourceFailure(LandmarkError):
    """A source that cannot be read. Its kinds are unavailable and the rest of the part stays (D20)."""


# ---------------------------------------------------------------- small helpers

def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _compact(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".lm-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)                  # mkstemp makes 0600 files; the store and cache files are ordinary files
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _check_store(root: Path) -> None:
    if not (root / "hail" / "index.json").is_file() or not (root / "hail" / "manifest.json").is_file():
        raise LandmarkError("the store has no hail index or manifest; build the hail store first")


def _attr(attrs, key: str):
    """The value of a field, matched without regard to case (the service writes some field names in lower case)."""
    if not isinstance(attrs, dict):
        return None
    if key in attrs:
        return attrs[key]
    wanted = key.lower()
    for name, value in attrs.items():
        if isinstance(name, str) and name.lower() == wanted:
            return value
    return None


def faa_cycle(day: date) -> date:
    """The NASR cycle in force on day: effective dates 28 days apart, anchored on FAA_ANCHOR (2026-10-01)."""
    return FAA_ANCHOR + timedelta(days=FAA_DAYS * ((day - FAA_ANCHOR).days // FAA_DAYS))


def _position(lon, lat):
    """(lon, lat) rounded to five decimals when both are finite numbers inside the Montana box, else None."""
    try:
        x = float(lon)
        y = float(lat)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    west, south, east, north = MONTANA_BOX
    if not (west <= x <= east and south <= y <= north):
        return None
    return round(x, 5), round(y, 5)


PLACEHOLDER = re.compile(r"\b(unknown|unnamed|none|n/a)\b", re.IGNORECASE)
AIRPORT_WORDS = {"INTL": "International", "RGNL": "Regional", "MUNI": "Municipal", "FLD": "Field", "MEM": "Memorial"}
AIRPORT_TERMS = re.compile(r"\b(airport|airpark|air park|airfield|field|air base|aerodrome|airstrip|landing|base)\b",
                           re.IGNORECASE)


def clean_name(raw):
    """The display name of a source name: its words, one space between them, all-capital words title-cased (the
    repository's rule), or None for an empty name or a placeholder."""
    if not isinstance(raw, str):
        return None
    text = " ".join(raw.split())
    if not text or PLACEHOLDER.search(text):
        return None
    return S.display_name(text)


def airport_name(raw):
    """clean_name for an airport, with the abbreviations written out and "Airport" added when no airport word is in the name."""
    if not isinstance(raw, str):
        return None
    text = clean_name(" ".join(AIRPORT_WORDS.get(word.upper(), word) for word in raw.split()))
    if text is None:
        return None
    return text if AIRPORT_TERMS.search(text) else f"{text} Airport"


def _metres(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """A local distance in metres (equirectangular at the mean latitude; a bound for the 150 m merge, not a survey)."""
    kx = 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.hypot((lon2 - lon1) * kx, (lat2 - lat1) * 110_574.0)


# ---------------------------------------------------------------- polygons: the label point and the containment test

def _signed_distance(x: float, y: float, rings) -> float:
    """Distance from (x, y) to the nearest edge of the polygon, positive inside. Inside is the even-odd rule over all
    rings, so holes and separate parts are handled the same way."""
    inside = False
    best = math.inf
    for ring in rings:
        if len(ring) < 2:
            continue
        ax, ay = ring[-1]
        for bx, by in ring:
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
            dx, dy = bx - ax, by - ay
            seg = dx * dx + dy * dy
            t = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg))
            px, py = ax + t * dx - x, ay + t * dy - y
            best = min(best, px * px + py * py)
            ax, ay = bx, by
    if best == math.inf:
        return 0.0
    return math.sqrt(best) if inside else -math.sqrt(best)


def point_in_rings(x: float, y: float, rings) -> bool:
    """True when (x, y) is inside the polygon (even-odd over all rings)."""
    inside = False
    for ring in rings:
        if len(ring) < 2:
            continue
        ax, ay = ring[-1]
        for bx, by in ring:
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
            ax, ay = bx, by
    return inside


def _centroid(ring):
    """The area-weighted centroid of a ring (the vertex mean when the ring has no area)."""
    area = cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        f = x0 * y1 - x1 * y0
        area += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(area) < 1e-18:
        return sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n
    return cx / (3.0 * area), cy / (3.0 * area)


def pole_of_inaccessibility(rings, precision: float = 1e-5):
    """The point inside a polygon that is farthest from its edges (the label point), by the cell search of the polylabel
    method. rings: the outer ring first, then the holes (and any further parts). Returns (lon, lat) or None."""
    rings = [ring for ring in rings if len(ring) >= 3]
    if not rings:
        return None
    outer = rings[0]
    minx = min(p[0] for p in outer)
    maxx = max(p[0] for p in outer)
    miny = min(p[1] for p in outer)
    maxy = max(p[1] for p in outer)
    width, height = maxx - minx, maxy - miny
    cell = min(width, height)
    if cell <= 0:
        return (minx + width / 2.0, miny + height / 2.0)
    half = cell / 2.0
    counter = itertools.count()
    heap: list = []

    def push(cx: float, cy: float, h: float) -> None:
        d = _signed_distance(cx, cy, rings)
        heapq.heappush(heap, (-(d + h * math.sqrt(2.0)), next(counter), cx, cy, h, d))

    best_x, best_y = _centroid(outer)
    best_d = _signed_distance(best_x, best_y, rings)
    box_x, box_y = minx + width / 2.0, miny + height / 2.0
    box_d = _signed_distance(box_x, box_y, rings)
    if box_d > best_d:
        best_x, best_y, best_d = box_x, box_y, box_d
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            push(x + half, y + half, half)
            y += cell
        x += cell
    while heap:
        neg, _, x, y, h, d = heapq.heappop(heap)
        if d > best_d:
            best_x, best_y, best_d = x, y, d
        if -neg - best_d <= precision:           # no point in this cell can beat the best by more than the precision
            continue
        h2 = h / 2.0
        push(x - h2, y - h2, h2)
        push(x + h2, y - h2, h2)
        push(x - h2, y + h2, h2)
        push(x + h2, y + h2, h2)
    return best_x, best_y


# ---------------------------------------------------------------- parsers (pure: no network, no files)

def points_from(features, kind: str, source: str, *, name_key: str, coords, keep=None, name_fn=clean_name):
    """(rows, drops) for a list of features. coords(feature, attributes) gives (lon, lat) or None; keep(attributes) can
    refuse a row that the server's where clause should already have left out. A row is (kind, name, lon, lat, source)."""
    rows = []
    drops: Counter = Counter()
    for feature in features:
        if not isinstance(feature, dict):
            drops["not a feature"] += 1
            continue
        attrs = feature.get("attributes") if isinstance(feature.get("attributes"), dict) else {}
        if keep is not None and not keep(attrs):
            drops["not a point-address match"] += 1
            continue
        name = name_fn(_attr(attrs, name_key))
        if name is None:
            drops["no name or placeholder name"] += 1
            continue
        xy = coords(feature, attrs)
        pos = _position(*xy) if xy is not None else None
        if pos is None:
            drops["no position or outside Montana"] += 1
            continue
        rows.append((kind, name, pos[0], pos[1], source))
    return rows, drops


def attr_coords(lon_key: str, lat_key: str):
    def coords(feature, attrs):
        return _attr(attrs, lon_key), _attr(attrs, lat_key)
    return coords


def geometry_coords(feature, attrs):
    geom = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    return geom.get("x"), geom.get("y")


def dedupe(rows):
    """(rows, dropped): a row with the same kind, name and position as an earlier row is dropped."""
    seen = set()
    out = []
    dropped = 0
    for row in rows:
        key = (row[0], row[1].casefold(), row[2], row[3])
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(row)
    return out, dropped


def polygons_from(features):
    """(polygons, drops) for the PAD-US local park features. A polygon is {"name", "rings", "pos"} where pos is the label
    point (the pole of inaccessibility) inside Montana."""
    polys = []
    drops: Counter = Counter()
    for feature in features:
        if not isinstance(feature, dict):
            drops["not a feature"] += 1
            continue
        attrs = feature.get("attributes") if isinstance(feature.get("attributes"), dict) else {}
        name = clean_name(_attr(attrs, "Unit_Nm"))
        if name is None:
            drops["no name or placeholder name"] += 1
            continue
        geom = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        try:
            rings = [[(float(p[0]), float(p[1])) for p in ring] for ring in geom.get("rings", []) if len(ring) >= 3]
        except (TypeError, ValueError, IndexError):
            rings = []
        if not rings:
            drops["no polygon"] += 1
            continue
        label = pole_of_inaccessibility(rings)
        pos = _position(*label) if label is not None else None
        if pos is None:
            drops["no position or outside Montana"] += 1
            continue
        polys.append({"name": name, "rings": rings, "pos": pos})
    return polys, drops


def merge_parks(polys, tiger_rows):
    """(pad_rows, tiger_kept, tiger_merged). Every PAD-US local park is a row with its own name and label point (the name its
    polygon carries on the basemap). A named TIGER park point inside a PAD-US park polygon, or within MERGE_M of its label point,
    is the same park and is dropped; the other TIGER park points are kept."""
    pad_rows = [("park", poly["name"], poly["pos"][0], poly["pos"][1], "padus_local") for poly in polys]
    tiger_kept = []
    merged = 0
    for row in tiger_rows:
        covered = any(point_in_rings(row[2], row[3], poly["rings"])
                      or _metres(row[2], row[3], poly["pos"][0], poly["pos"][1]) <= MERGE_M for poly in polys)
        if covered:
            merged += 1
        else:
            tiger_kept.append(row)
    return pad_rows, tiger_kept, merged


def dedupe_parks(rows):
    """(rows, dropped): a park with the same name as an earlier park within MERGE_M is the same park (a park that the source
    lists in two pieces, such as Scotty Park in two polygons)."""
    kept = []
    dropped = 0
    for row in rows:
        same = any(k[1].casefold() == row[1].casefold() and _metres(k[2], k[3], row[2], row[3]) <= MERGE_M for k in kept)
        if same:
            dropped += 1
        else:
            kept.append(row)
    return kept, dropped


DMS = re.compile(r"^\s*(\d{1,3})-(\d{1,2})-(\d{1,2}(?:\.\d+)?)([NSEW])\s*$")


def dms_value(text: str, axis: str):
    """Degrees from a formatted "46-54-58.7000N" (axis "lat": N or S) or "114-05-26.0000W" (axis "lon": E or W)."""
    match = DMS.match(text or "")
    if not match:
        return None
    deg, minutes, seconds, hemi = match.groups()
    if (axis == "lat") != (hemi in "NS"):
        return None
    value = int(deg) + int(minutes) / 60.0 + float(seconds) / 3600.0
    return -value if hemi in "SW" else value


def parse_faa_lines(lines):
    """(rows, drops, counts) for the lines of the APT file. Only APT records are read; the fields are the 2026 APT layout's
    columns (1-based start in the layout: state 49-50, facility type 15-27, use 186-187, ownership 184-185, name 134-183,
    latitude 524-538, longitude 551-565, status 841-842)."""
    rows = []
    drops: Counter = Counter()
    counts: Counter = Counter()
    for line in lines:
        if not line.startswith("APT"):
            continue
        counts["apt records"] += 1
        if line[48:50] != "MT":
            continue
        counts["montana records"] += 1
        if line[14:27].strip() != "AIRPORT":
            drops["not an airport (facility type)"] += 1
            continue
        if line[185:187].strip() != "PU":
            drops["not public use"] += 1
            continue
        if line[840:842].strip() != "O":
            drops["not operational"] += 1
            continue
        name = airport_name(line[133:183].strip())
        if name is None:
            drops["no name or placeholder name"] += 1
            continue
        lat = dms_value(line[523:538], "lat")
        lon = dms_value(line[550:565], "lon")
        pos = _position(lon, lat) if lat is not None and lon is not None else None
        if pos is None:
            drops["no position or outside Montana"] += 1
            continue
        rows.append(("airport", name, pos[0], pos[1], "faa_nasr"))
    return rows, drops, counts


def parse_tiger_records(records):
    """(rows, drops) for TIGER area landmark records (dicts with STATEFP, MTFCC, FULLNAME, INTPTLAT, INTPTLON). Only the
    park codes are kept, and only with a name; the position is the Census interior point."""
    rows = []
    drops: Counter = Counter()
    for rec in records:
        if str(rec.get("STATEFP", "")).strip() != STATE_FIPS:
            drops["not Montana"] += 1
            continue
        if str(rec.get("MTFCC", "")).strip() not in TIGER_PARK_CODES:
            continue
        name = clean_name(rec.get("FULLNAME"))
        if name is None:
            drops["no name or placeholder name"] += 1
            continue
        try:
            lon = float(str(rec.get("INTPTLON")).strip())
            lat = float(str(rec.get("INTPTLAT")).strip())
        except (TypeError, ValueError):
            lon = lat = None
        pos = _position(lon, lat) if lon is not None else None
        if pos is None:
            drops["no position or outside Montana"] += 1
            continue
        rows.append(("park", name, pos[0], pos[1], "tiger_park"))
    return rows, drops


TIGER_NEEDED = ("STATEFP", "MTFCC", "FULLNAME", "INTPTLAT", "INTPTLON")


def read_tiger(data: bytes):
    """(rows, drops, count) from the TIGER zip bytes. Raises SourceFailure when the zip or its fields are not as expected."""
    try:
        import shapefile                          # pyshp: the store job installs it (D20: a missing reader fails this source)
    except ImportError:
        raise SourceFailure("the shapefile reader is not installed, so the park points cannot be read") from None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = {Path(n).suffix.lower(): n for n in z.namelist() if not n.endswith("/")}
            if not all(ext in members for ext in (".shp", ".dbf", ".shx")):
                raise SourceFailure("the park file does not hold the shapefile parts the reader expects")
            reader = shapefile.Reader(shp=io.BytesIO(z.read(members[".shp"])),
                                      dbf=io.BytesIO(z.read(members[".dbf"])),
                                      shx=io.BytesIO(z.read(members[".shx"])))
    except zipfile.BadZipFile:
        raise SourceFailure("the park file is not a zip file") from None
    except (shapefile.ShapefileException, OSError, ValueError) as exc:
        raise SourceFailure(f"the park file could not be read ({type(exc).__name__})") from None
    fields = {f[0] for f in reader.fields[1:]}
    missing = [name for name in TIGER_NEEDED if name not in fields]
    if missing:
        raise SourceFailure("the park file does not have the fields the reader expects (" + ", ".join(missing) + ")")
    records = []
    for rec in reader.iterRecords():
        d = rec.as_dict()
        records.append({k: d.get(k) for k in TIGER_NEEDED})
    rows, drops = parse_tiger_records(records)
    return rows, drops, len(records)


# ---------------------------------------------------------------- the download (cache by name, every request logged)

class Fetch:
    """Requests and cache reads for one build. A cached file is read without a request; --refresh asks again for every file;
    --offline makes no request at all. Each request is one ledger line in the cache folder."""

    def __init__(self, cache, *, offline: bool = False, refresh: bool = False, session=None, deadline_at=None,
                 sleep=time.sleep):
        self.cache = Path(cache)
        self.offline = offline
        self.refresh = refresh
        self.session = session
        self.deadline_at = deadline_at
        self.sleep = sleep
        self.requests = 0
        self.downloaded = 0
        self.hits = 0
        self.last = 0.0

    def _ledger(self, method: str, url: str, status, nbytes, state: str, error=None) -> None:
        self.cache.mkdir(parents=True, exist_ok=True)
        line = {"at": _utc_now(), "method": method, "url": url, "status": status, "bytes": nbytes, "cache": state,
                "error": error}
        with open(self.cache / "ledger.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")

    def _http(self):
        if self.session is None:
            import requests
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
            self.session = session
        return self.session

    def _pace(self) -> None:
        wait = PACE_S - (time.monotonic() - self.last)
        if wait > 0:
            self.sleep(wait)
        self.last = time.monotonic()

    def get(self, url: str, what: str) -> bytes:
        """The body of one successful request. Retries a dropped connection, a timeout or an HTTP 5xx, then fails."""
        if self.deadline_at is not None and time.monotonic() > self.deadline_at:
            raise SourceFailure(f"the request for {what} was not made: the job's time limit was reached")
        session = self._http()
        reason = REASON_NO_ANSWER
        for attempt in range(1, TRIES + 1):
            self._pace()
            self.requests += 1
            try:
                with session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True) as response:
                    status = response.status_code
                    if status == 200:
                        body = response.content
                        self.downloaded += len(body)
                        self._ledger("GET", url, 200, len(body), "fetched")
                        return body
                    self._ledger("GET", url, status, None, "failed", f"attempt {attempt}: status {status}")
                    reason = f"HTTP {status}"
                    if status < 500:
                        raise SourceFailure(f"the request for {what} answered HTTP {status}")
            except SourceFailure:
                raise
            except Exception as exc:              # a dropped connection, a timeout or a cut-off body: tried again
                self._ledger("GET", url, None, None, "failed", f"attempt {attempt}: {type(exc).__name__}")
                reason = type(exc).__name__
            if attempt < TRIES:
                self.sleep(2.0 * attempt)
        raise SourceFailure(f"the request for {what} failed ({reason})")

    def file(self, path: Path, url: str, what: str) -> bytes:
        """The bytes of one cached file, fetched and stored when the file is not in the cache (or --refresh is set)."""
        if path.is_file() and not self.refresh:
            self.hits += 1
            self._ledger("GET", url, None, path.stat().st_size, "hit")
            return path.read_bytes()
        if self.offline:
            raise SourceFailure(f"{what} is not in the cache and this run makes no request")
        data = self.get(url, what)
        _atomic(path, data)
        _atomic(path.with_name(path.name + ".meta.json"),
                _compact({"url": url, "bytes": len(data), "sha256": _sha256(data), "fetched": _utc_now()}))
        return data

    def fetched_at(self, path: Path) -> str | None:
        meta = path.with_name(path.name + ".meta.json")
        try:
            return _read_json(meta).get("fetched")
        except (OSError, ValueError, AttributeError):
            return None


def _json_doc(raw: bytes, what: str):
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SourceFailure(f"the {what} is not JSON") from None
    if not isinstance(doc, dict):
        raise SourceFailure(f"the {what} is not a JSON object")
    if isinstance(doc.get("error"), dict):
        raise SourceFailure(f"the {what} is a service error ({str(doc['error'].get('message', 'no message'))[:80]})")
    return doc


def _query_key(spec: dict) -> str:
    """A short key for the query (the URL and the where clause), so a changed query never reads an old page."""
    text = spec["url"] + "?" + json.dumps(spec.get("query", {}), sort_keys=True)
    return _sha256(text.encode("utf-8"))[:12]


def load_arcgis(fetch: Fetch, key: str, spec: dict) -> dict:
    """Every feature of a map service layer query, page by page, after the layer's own description is read and checked. Returns
    {"features", "meta", "as_of", "fetched", "pages"}."""
    label = spec["label"]
    meta_path = fetch.cache / key / "meta.json"
    meta = _json_doc(fetch.file(meta_path, spec["url"] + "?f=pjson", f"the layer description of {label}"),
                     f"layer description of {label}")
    names = {str(f.get("name", "")).lower() for f in meta.get("fields", []) if isinstance(f, dict)}
    missing = [f for f in spec["fields"] if f.lower() not in names]
    if missing:
        raise SourceFailure(f"{label} does not have the fields the reader expects ({', '.join(missing)})")
    oid = next((f.get("name") for f in meta.get("fields", []) if isinstance(f, dict)
                and f.get("type") == "esriFieldTypeOID"), None) or meta.get("objectIdField") or "OBJECTID"
    per_page = min(2000, int(meta.get("maxRecordCount") or 1000))
    base = fetch.cache / key / _query_key(spec)
    features: list = []
    offset = 0
    pages = 0
    for page in range(MAX_PAGES):
        params = dict(spec.get("query", {}), f="json", orderByFields=oid, resultOffset=offset,
                      resultRecordCount=per_page)
        url = spec["url"] + "/query?" + urlencode(params)
        raw = fetch.file(base / f"p{page:03d}.json", url, f"the {label} list, page {page}")
        pages += 1
        doc = _json_doc(raw, f"{label} list")
        found = doc.get("features")
        if not isinstance(found, list):
            raise SourceFailure(f"the {label} list has no features list")
        features.extend(found)
        if doc.get("exceededTransferLimit") and found:
            offset += len(found)
            continue
        break
    else:
        raise SourceFailure(f"the {label} list needs more than {MAX_PAGES} pages, which the reader does not read")
    as_of = spec["as_of"]
    edited = meta.get("editingInfo", {}).get("lastEditDate") if isinstance(meta.get("editingInfo"), dict) else None
    if edited is None:
        edited = meta.get("lastEditDate")
    if isinstance(edited, (int, float)) and edited > 0:
        as_of = datetime.fromtimestamp(edited / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d") + " (layer last edited)"
    return {"features": features, "as_of": as_of, "fetched": fetch.fetched_at(base / "p000.json"), "pages": pages,
            "copyright": meta.get("copyrightText") or None}


def load_faa(fetch: Fetch, cycle: date) -> dict:
    spec = SOURCES["faa_nasr"]
    url = spec["url"].format(cycle=cycle.isoformat())
    path = fetch.cache / "faa_nasr" / f"APT_{cycle.isoformat()}.zip"
    data = fetch.file(path, url, f"the airport file for the {cycle.isoformat()} cycle")
    if data[:2] != b"PK":
        raise SourceFailure("the airport file is not a zip file")
    try:
        with zipfile.ZipFile(path) as z:
            member = next((n for n in z.namelist() if n.upper().endswith("APT.TXT")), None)
            if member is None:
                raise SourceFailure("the airport file has no APT.txt member")
            with z.open(member) as fh:
                rows, drops, counts = parse_faa_lines(io.TextIOWrapper(fh, encoding="latin-1", newline=""))
    except zipfile.BadZipFile:
        raise SourceFailure("the airport file is not a readable zip file") from None
    if counts.get("montana records", 0) == 0:
        raise SourceFailure("the airport file has no Montana airport records")
    return {"rows": rows, "drops": drops, "read": counts.get("apt records", 0), "as_of": cycle.isoformat(),
            "fetched": fetch.fetched_at(path), "counts": dict(counts)}


def load_tiger(fetch: Fetch) -> dict:
    spec = SOURCES["tiger_park"]
    path = fetch.cache / "tiger_park" / "tl_2026_30_arealm.zip"
    data = fetch.file(path, spec["url"], "the park landmark file")
    rows, drops, count = read_tiger(data)
    return {"rows": rows, "drops": drops, "read": count, "as_of": spec["as_of"], "fetched": fetch.fetched_at(path),
            "bytes": len(data)}


def load_padus(fetch: Fetch) -> dict:
    loaded = load_arcgis(fetch, "padus_local", SOURCES["padus_local"])
    polys, drops = polygons_from(loaded["features"])
    return {"polys": polys, "drops": drops, "read": len(loaded["features"]), "as_of": loaded["as_of"],
            "fetched": loaded["fetched"], "pages": loaded["pages"]}


def _points_source(fetch: Fetch, key: str, *, name_key: str, coords, keep=None) -> dict:
    spec = SOURCES[key]
    loaded = load_arcgis(fetch, key, spec)
    rows, drops = points_from(loaded["features"], spec["kind"], key, name_key=name_key, coords=coords, keep=keep)
    rows, dup = dedupe(rows)
    if dup:
        drops["duplicate of an earlier row"] += dup
    return {"rows": rows, "drops": drops, "read": len(loaded["features"]), "as_of": loaded["as_of"],
            "fetched": loaded["fetched"], "pages": loaded["pages"]}


def _fema_keep(attrs) -> bool:
    return str(_attr(attrs, "LOC_NAME") or "").upper() == "POINTADDRESS" and str(_attr(attrs, "STATE") or "") == "MT"


def load_source(fetch: Fetch, key: str, today: date) -> dict:
    """One source's rows (or its failure). Returns {"rows", "drops", "read", "as_of", "fetched", ...} and raises
    SourceFailure with the plain reason when the source cannot be used."""
    if key in ("nces_public", "nces_private"):
        return _points_source(fetch, key, name_key="NAME", coords=attr_coords("LON", "LAT"))
    if key in ("usgs_hospitals", "usgs_fire"):
        return _points_source(fetch, key, name_key="NAME", coords=geometry_coords)
    if key == "hifld_hospitals":
        return _points_source(fetch, key, name_key="NAME", coords=attr_coords("LONGITUDE", "LATITUDE"))
    if key == "fema_worship":
        return _points_source(fetch, key, name_key="NAME", coords=attr_coords("X", "Y"), keep=_fema_keep)
    if key == "faa_nasr":
        return load_faa(fetch, faa_cycle(today))
    if key == "tiger_park":
        return load_tiger(fetch)
    if key == "padus_local":
        return load_padus(fetch)
    raise LandmarkError(f"no source named {key}")


# ---------------------------------------------------------------- the build

def _floors(overrides) -> dict:
    floors = {key: spec.get("floor", 1) for key, spec in SOURCES.items()}
    floors.update(overrides or {})
    return floors


def _count_floor(key: str, rows: int, floors: dict) -> None:
    floor = floors.get(key, 1)
    if rows < floor:
        raise SourceFailure(f"{SOURCES[key]['label']} gave {rows} rows, below the {floor} the reader expects")


def _load_checked(fetch: Fetch, key: str, floors: dict, today: date, allow_zero: bool = False) -> dict:
    """load_source with the floor applied: a count below the floor is a failure of the source. allow_zero lets a source
    answer with no rows (the USGS hospital layer, which then hands the hospital rule to the HIFLD copy)."""
    result = load_source(fetch, key, today)
    rows = len(result["polys"]) if key == "padus_local" else len(result["rows"])
    if not (allow_zero and rows == 0):
        _count_floor(key, rows, floors)
    return result


def _sources_block(results: dict) -> dict:
    block = {}
    for key in ORDER + ("hifld_hospitals",):
        spec = SOURCES[key]
        res = results.get(key)
        entry = {"kind": spec["kind"], "label": spec["label"], "credit": spec["credit"], "terms": spec["terms"]}
        if res is None:
            entry.update({"state": "not used"})
        elif res.get("ok"):
            entry.update({"state": "loaded", "as_of": res.get("as_of"), "fetched": res.get("fetched"),
                          "read": res.get("read"), "kept": len(res.get("rows", [])) if "rows" in res
                          else len(res.get("polys", [])), "drops": dict(res.get("drops", {})),
                          "requests": res.get("requests"), "bytes": res.get("bytes")})
        else:
            entry.update({"state": "unavailable", "reason": res.get("reason")})
        block[key] = entry
    return block


def _gzip_size(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def _tile_of(lon: float, lat: float) -> str:
    """The B1 tile name that holds a position (hail.cell_for, exact decimal rounding; the tile is 10 by 10 cells)."""
    r, c = hail.cell_for(lat, lon)
    return hail.tile_name(r // hail.TILE, c // hail.TILE)


def shard_files(rows) -> dict:
    """{tile name: compact JSON bytes} for the rows, one file per B1 tile (hail.tile_name), each file's rows sorted."""
    by_tile = defaultdict(list)
    for row in rows:
        by_tile[_tile_of(row[2], row[3])].append(row)
    files = {}
    for tile in sorted(by_tile):
        items = sorted(by_tile[tile], key=lambda row: (KIND_CODE[row[0]], row[1].casefold(), row[2], row[3], row[4]))
        doc = {"f": FORMAT, "t": tile, "n": len(items),
               "i": [[row[2], row[3], KIND_CODE[row[0]], row[1], row[4]] for row in items]}
        files[tile] = _compact(doc)
    return files


def _merge_manifest(store: Path, entries: dict) -> None:
    """Replaces this module's manifest entries (the p folder and the base index) and keeps every other entry."""
    path = store / "hail" / "manifest.json"
    manifest = _read_json(path)
    files = {k: v for k, v in manifest.get("files", {}).items() if not k.startswith(P_PREFIX) and k != BASE_INDEX}
    files.update(entries)
    manifest["files"] = {k: files[k] for k in sorted(files)}
    _atomic(path, _pretty(manifest))


def _write_block(store: Path, block: dict, shards: dict) -> dict:
    """Writes the p folder (rebuilt whole), the base index with this block, and the manifest entries."""
    p_dir = store / "hail" / "base" / "p"
    if p_dir.exists():
        shutil.rmtree(p_dir)                    # the shard folder is this module's alone
    entries = {}
    for tile, data in shards.items():
        rel = f"{P_PREFIX}{tile}.json"
        _atomic(store / rel, data)
        entries[rel] = {"bytes": len(data), "sha256": _sha256(data)}
    base_path = store / BASE_INDEX
    base = _read_json(base_path) if base_path.is_file() else {}
    base[INDEX_KEY] = block
    data = _pretty(base)
    _atomic(base_path, data)
    entries[BASE_INDEX] = {"bytes": len(data), "sha256": _sha256(data)}
    _merge_manifest(store, entries)
    return entries


def _problem_for(kinds: dict) -> str | None:
    """The D20 words for the kinds that are unavailable (held kinds never count: they are not shown either way)."""
    lost = [kind for kind in KIND_ORDER if kind not in HELD and kinds.get(kind, {}).get("state") == "unavailable"]
    return " ".join(WORDS["kind_unavailable"].format(plural=KIND_PLURAL[kind]) for kind in lost) or None


def build(store, cache, *, now: datetime | None = None, offline: bool = False, refresh: bool = False,
          deadline_at: float | None = None, session=None, floors: dict | None = None, sleep=time.sleep) -> dict:
    """Read every source (the cache first, then the network unless offline), build the points of each kind, write the shards
    and the block, and return the summary. A source failure marks its kinds unavailable and the build goes on. Raises
    LandmarkError only when the hail store is not there."""
    t0 = time.monotonic()
    store = Path(store)
    _check_store(store)
    tiles = set(hail.load_index(store)["tiles"])
    now = now or datetime.now(timezone.utc)
    today = now.date()
    fetch = Fetch(cache, offline=offline, refresh=refresh, session=session, deadline_at=deadline_at, sleep=sleep)
    floor_map = _floors(floors)
    results: dict = {}

    def run(key: str, allow_zero: bool = False) -> dict:
        before = (fetch.requests, fetch.downloaded)
        try:
            res = _load_checked(fetch, key, floor_map, today, allow_zero=allow_zero)
            res["ok"] = True
        except SourceFailure as exc:
            res = {"ok": False, "reason": str(exc), "rows": [], "drops": {}}
            _say(f"landmarks: {SOURCES[key]['label']} could not be used ({exc})")
        res["requests"] = fetch.requests - before[0]
        res["bytes"] = fetch.downloaded - before[1]
        results[key] = res
        return res

    for key in ORDER:
        run(key, allow_zero=(key == "usgs_hospitals"))

    # Hospitals: the USGS layer where it carries Montana hospitals (named rows). The HIFLD copy is read only when that layer
    # answers with no Montana hospital at all; a layer that cannot be read is a failure, not a reason to change source.
    tnm = results["usgs_hospitals"]
    if tnm["ok"] and tnm["rows"]:
        hospital_key = "usgs_hospitals"
        hospital_why = f"{WORDS['hospital_usgs']} The layer carries {len(tnm['rows'])} named Montana hospitals."
    elif tnm["ok"]:
        hifld = run("hifld_hospitals")
        hospital_key = "hifld_hospitals" if hifld["ok"] else None
        hospital_why = (WORDS["hospital_hifld"] if hifld["ok"] else
                        "the USGS layer named no Montana hospital, and the HIFLD copy could not be used")
    else:
        hospital_key = None
        hospital_why = f"the USGS layer could not be used ({tnm.get('reason')})"

    # Parks: the PAD-US local parks, plus the named TIGER park points that no PAD-US park holds (merge_parks); parks with the
    # same name within MERGE_M are one park (dedupe_parks).
    park_rows: list = []
    tiger_merged = 0
    park_same = 0
    if results["padus_local"]["ok"] and results["tiger_park"]["ok"]:
        pad_rows, tiger_kept, tiger_merged = merge_parks(results["padus_local"]["polys"], results["tiger_park"]["rows"])
        park_rows, park_same = dedupe_parks(pad_rows + tiger_kept)

    kinds: dict = {}
    rows_by_kind: dict = {}
    for kind in KIND_ORDER:
        if kind == "hospital":
            used = [hospital_key] if hospital_key else []
            failed = [] if hospital_key else ["usgs_hospitals"]
        else:
            used = list(KIND_SOURCES[kind])
            failed = [key for key in used if not results[key]["ok"]]
        entry = {"code": KIND_CODE[kind], "held": kind in HELD, "sources": used}
        if failed:
            reason = hospital_why if kind == "hospital" else results[failed[0]].get("reason", REASON_NO_ANSWER)
            kinds[kind] = dict(entry, state="unavailable", count=0, reason=reason, failed=failed)
            continue
        if kind == "hospital":
            rows = list(results[hospital_key]["rows"])
        elif kind == "park":
            rows = list(park_rows)
        else:
            rows = [row for key in used for row in results[key]["rows"]]
        rows, dup = dedupe(rows)
        rows_by_kind[kind] = rows
        kinds[kind] = dict(entry, state="held" if kind in HELD else "loaded", count=len(rows), dropped=dup)

    shown = [row for kind in KIND_ORDER if kind in rows_by_kind and kind not in HELD for row in rows_by_kind[kind]]
    held_counts = {kind: len(rows_by_kind[kind]) for kind in HELD if kind in rows_by_kind}
    files = shard_files(shown)
    gz = {tile: _gzip_size(data) for tile, data in files.items()}
    largest = max(gz, key=gz.get) if gz else None
    outside = sum(1 for row in shown if _tile_of(row[2], row[3]) not in tiles)
    shown_kinds = [kind for kind in KIND_ORDER if kind not in HELD]
    if not any(kinds[kind]["state"] == "loaded" for kind in shown_kinds):
        state = "unavailable"
    elif any(kinds[kind]["state"] == "unavailable" for kind in shown_kinds):
        state = "partial"
    else:
        state = "loaded"
    if state == "unavailable":
        files = {}
        gz = {}
        largest = None
    problem = {"loaded": None, "partial": _problem_for(kinds), "unavailable": WORDS["all_unavailable"]}[state]
    failures = [{"source": key, "reason": res.get("reason")} for key, res in results.items() if not res.get("ok")]
    block = {
        "format": FORMAT,
        "state": state,
        "problem": problem,
        "built_at": _utc_now(),
        "as_of": today.isoformat(),
        "faa_cycle": faa_cycle(today).isoformat(),
        "kinds": kinds,
        "held": {kind: {"held": True, "rows": held_counts.get(kind, 0), "reason": HELD_REASON} for kind in HELD},
        "sources": _sources_block(results),
        "hospital_source": {"used": hospital_key, "why": hospital_why},
        "tiles": sorted(files),
        "counts": {
            "points": len(shown),
            "kinds": {kind: kinds[kind]["count"] for kind in shown_kinds},
            "sources_written": dict(Counter(row[4] for row in shown)),
            "tiger_merged": tiger_merged,
            "park_same_name": park_same,
            "held_rows": sum(held_counts.values()),
            "shards": len(files),
            "bytes": sum(len(v) for v in files.values()),
            "gzip_bytes": sum(gz.values()),
            "largest_gzip": gz[largest] if largest else 0,
            "largest_tile": largest,
            "outside_tiles": outside,
            "requests": fetch.requests,
            "downloaded_bytes": fetch.downloaded,
            "cache_hits": fetch.hits,
        },
        "budget": {"shard_gzip_bytes": BUDGET_GZIP, "largest_gzip_bytes": gz[largest] if largest else 0,
                   "within": all(v < BUDGET_GZIP for v in gz.values())},
        "rule": RULE_TEXT,
        "failures": failures[:50],
        "words": {"what": WORDS["what"], "rule": WORDS["rule"]},
    }
    _write_block(store, block, files)
    return {"state": state, "points": len(shown), "kinds": block["counts"]["kinds"],
            "held_rows": block["counts"]["held_rows"], "shards": len(files), "bytes": block["counts"]["bytes"],
            "gzip_bytes": block["counts"]["gzip_bytes"], "largest_gzip": block["counts"]["largest_gzip"],
            "largest_tile": largest, "budget_within": block["budget"]["within"], "failures": failures,
            "requests": fetch.requests, "downloaded_bytes": fetch.downloaded, "cache_hits": fetch.hits,
            "seconds": round(time.monotonic() - t0, 2), "outside_tiles": outside}



def mark_unavailable(store, reason: str) -> dict:
    """The landmarks are unavailable with the plain reason (D20). The shard folder is removed; the base index keeps the other
    parts' keys; the manifest keeps every other entry."""
    root = Path(store)
    _check_store(root)
    text = " ".join(str(reason).split())
    if not text:
        raise LandmarkError("give the reason the landmarks are unavailable (--reason TEXT)")
    block = {"format": FORMAT, "state": "unavailable", "problem": WORDS["all_unavailable"], "detail": text,
             "built_at": _utc_now(), "kinds": {}, "held": {}, "sources": {}, "counts": {"points": 0, "shards": 0}}
    _write_block(root, block, {})
    return {"state": "unavailable", "reason": text}


# ---------------------------------------------------------------- the words for the page (About, the chips, the unavailable text)

def describe_landmarks(index: dict | None = None) -> dict:
    """The About text of the landmark points: what a point is, each loaded source with its credit and as-of date, the held
    kind and the rule. index is the parsed hail/base/index.json (or None)."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    loaded = []
    if isinstance(block, dict):
        for key in ORDER:
            entry = block.get("sources", {}).get(key, {})
            if entry.get("state") == "loaded":
                loaded.append(WORDS["source_item"].format(label=entry.get("label", key), as_of=entry.get("as_of") or
                                                          "date not recorded", credit=entry.get("credit", "")))
    return {"title": "Landmarks", "what": WORDS["what"], "rule": WORDS["rule"], "parks": WORDS["parks"],
            "airports": WORDS["airports"], "held": WORDS["held"], "sources": loaded}


def map_data_landmarks(index: dict) -> dict:
    """The map.json block for the landmark chips: the state, the shard names and the words. The chips read a shard per
    tile and never a request for a tile that is not listed."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    templates = dict(WORDS)
    if not isinstance(block, dict) or block.get("state") not in ("loaded", "partial"):
        problem = block.get("problem") if isinstance(block, dict) else None
        return {"state": "unavailable", "problem": problem or WORDS["all_unavailable"], "templates": templates}
    kinds = {}
    for kind in KIND_ORDER:
        entry = block.get("kinds", {}).get(kind, {})
        state = entry.get("state", "unavailable")
        kinds[kind] = {"code": KIND_CODE[kind], "label": KIND_LABEL[kind], "state": state,
                       "held": bool(entry.get("held")),
                       "problem": (WORDS["held"] if entry.get("held") else
                                   WORDS["kind_unavailable"].format(plural=KIND_PLURAL[kind])
                                   if state == "unavailable" else None)}
    return {"state": block.get("state"), "problem": block.get("problem"), "shard": "hail/base/p/{name}.json",
            "tiles": sorted(block.get("tiles", [])), "kinds": kinds, "templates": templates,
            "counts": block.get("counts", {}), "sources": describe_landmarks(index)["sources"]}


# ---------------------------------------------------------------- verify

def _norm_name(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", str(text).lower()).split()
    return " ".join("saint" if w == "st" else w for w in words if w != "the")


def verify(store) -> dict:
    """Checks the landmark files in a store: the manifest entries, each file's shape, the counts recounted from the files,
    the held kinds (none written), the shard budget, the tile list, the Missoula check and hail.check_manifest."""
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    base_path = store / BASE_INDEX
    base = _read_json(base_path) if base_path.is_file() else {}
    block = base.get(INDEX_KEY) if isinstance(base, dict) else None
    check("landmarks block present in hail/base/index.json", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    check("state is loaded, partial or unavailable", block.get("state") in ("loaded", "partial", "unavailable"))
    p_dir = store / "hail" / "base" / "p"
    files = sorted(p_dir.glob("*.json")) if p_dir.is_dir() else []
    if block.get("state") == "unavailable":
        check("an unavailable block has no shard files", not files, f"{len(files)} files")
        return {"ok": all(c["pass"] for c in checks), "checks": checks, "note": block.get("problem")}
    manifest = _read_json(store / "hail" / "manifest.json")
    listed = manifest.get("files", {})
    bad = []
    for path in files + [base_path]:
        rel = path.relative_to(store).as_posix()
        data = path.read_bytes()
        entry = listed.get(rel)
        if entry is None or entry.get("bytes") != len(data) or entry.get("sha256") != _sha256(data):
            bad.append(rel)
    check("manifest lists each p file and the base index with its bytes and SHA-256", not bad, f"{len(bad)} mismatches")
    absent = [k for k in listed if k.startswith(P_PREFIX) and not (store / k).is_file()]
    check("every p file the manifest lists exists", not absent, f"{len(absent)} missing")
    counts = block.get("counts", {})
    check("shard count matches the block", len(files) == counts.get("shards"),
          f"{len(files)} files, block says {counts.get('shards')}")
    check("the block's tile list matches the shard files", sorted(block.get("tiles", [])) == [p.stem for p in files])
    tiles = set(hail.load_index(store)["tiles"]) if (store / "hail" / "index.json").is_file() else None
    recount: Counter = Counter()
    by_source: Counter = Counter()
    total = 0
    gz_sizes = []
    shape_bad = []
    coords_bad = 0
    held_seen = []
    out_of_tiles = 0
    missoula: set = set()
    for path in files:
        data = path.read_bytes()
        total += len(data)
        gz_sizes.append((_gzip_size(data), path.stem))
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            shape_bad.append(path.name)
            continue
        rows = doc.get("i") if isinstance(doc, dict) else None
        if not (isinstance(doc, dict) and doc.get("f") == FORMAT and doc.get("t") == path.stem
                and isinstance(rows, list) and doc.get("n") == len(rows)):
            shape_bad.append(path.name)
            continue
        if tiles is not None and path.stem not in tiles:
            out_of_tiles += 1
        for row in rows:
            if not (isinstance(row, list) and len(row) == 5 and isinstance(row[0], (int, float))
                    and isinstance(row[1], (int, float)) and row[2] in KIND_NAME and isinstance(row[3], str)
                    and row[3] and row[4] in SOURCES):
                shape_bad.append(path.name)
                continue
            kind = KIND_NAME[row[2]]
            if kind in HELD:
                held_seen.append(path.name)
            if _position(row[0], row[1]) is None:
                coords_bad += 1
            recount[kind] += 1
            by_source[row[4]] += 1
            if MISSOULA_BOX[0] <= row[0] <= MISSOULA_BOX[2] and MISSOULA_BOX[1] <= row[1] <= MISSOULA_BOX[3]:
                missoula.add((kind, _norm_name(row[3])))
    check("every shard parses to the expected shape", not shape_bad, f"{len(shape_bad)} problems")
    check("every position is inside the Montana box", coords_bad == 0, f"{coords_bad} outside")
    check("no held kind is written to a shard", not held_seen, f"{len(held_seen)} rows of a held kind")
    check("points recounted from the files match the block", sum(recount.values()) == counts.get("points"),
          f"{sum(recount.values())} recounted")
    kind_ok = True
    for kind in KIND_ORDER:
        if kind in HELD:
            continue
        entry = block.get("kinds", {}).get(kind, {})
        expect = entry.get("count", 0) if entry.get("state") == "loaded" else 0
        if recount.get(kind, 0) != expect:
            kind_ok = False
    check("per-kind counts recounted from the files match the block (an unavailable kind holds none)", kind_ok)
    check("per-source counts recounted from the files match the block",
          dict(by_source) == counts.get("sources_written", {}), f"{sum(by_source.values())} rows")
    largest = max(gz_sizes) if gz_sizes else (0, "")
    check("each shard is under the gzip budget", largest[0] < BUDGET_GZIP,
          f"largest {largest[0]} bytes gzip ({largest[1]})")
    check("the shard bytes match the block", total == counts.get("bytes", total), f"{total} bytes")
    check("every shard's tile is in the hail tile list", tiles is None or out_of_tiles == 0,
          f"{out_of_tiles} outside the list")
    loaded = {k for k, v in block.get("kinds", {}).items() if isinstance(v, dict) and v.get("state") == "loaded"}
    expected = [(k, _norm_name(n)) for k, n in MISSOULA_CHECK if k in loaded]
    absent = [f"{kind} {name}" for kind, name in expected if (kind, name) not in missoula]
    left_out = sorted({k for k, _ in MISSOULA_CHECK if k not in loaded})
    detail = ("missing: " + "; ".join(absent)) if absent else (
        ("kinds not loaded, so not checked: " + ", ".join(left_out)) if left_out else "")
    check("the Missoula area holds each named point of a loaded kind", not absent, detail)
    check("the hospital source and its reason are recorded", bool(block.get("hospital_source", {}).get("why")))
    try:
        hail.check_manifest(store)
        manifest_ok, manifest_detail = True, ""
    except hail.HailStoreError as exc:
        manifest_ok, manifest_detail = False, str(exc)
    check("hail.check_manifest passes on the store", manifest_ok, manifest_detail)
    return {"ok": all(c["pass"] for c in checks), "checks": checks, "counts": counts,
            "largest_gzip": largest[0], "largest_tile": largest[1]}



# ---------------------------------------------------------------- command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.landmarks", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="read the sources, write hail/base/p/ and the landmarks block")
    b.add_argument("--store", required=True, help="the store directory that holds hail/ (the hail store)")
    b.add_argument("--cache", required=True, help="the download cache folder (one folder per source)")
    b.add_argument("--now", default=None, help="the run's UTC time as ISO text (default: now); it picks the FAA cycle")
    b.add_argument("--offline", action="store_true", help="read only the cache; no request is made")
    b.add_argument("--refresh", action="store_true", help="ask again for every cached file (the monthly job)")
    b.add_argument("--deadline-at", type=float, default=None, help="epoch seconds: no request starts after this time")
    b.add_argument("--metrics", default=None, help="write the summary as JSON to this file")
    v = sub.add_parser("verify", help="check the landmark files in a store (exit 1 on a failure)")
    v.add_argument("--store", required=True)
    u = sub.add_parser("unavailable", help="mark the landmarks unavailable with a reason and remove their files")
    u.add_argument("--store", required=True)
    u.add_argument("--reason", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "build":
            now = None
            if args.now:
                now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
                if now.tzinfo is None:
                    now = now.replace(tzinfo=timezone.utc)
            deadline_at = None
            if args.deadline_at is not None:
                deadline_at = time.monotonic() + (args.deadline_at - time.time())
            summary = build(args.store, args.cache, now=now, offline=args.offline, refresh=args.refresh,
                            deadline_at=deadline_at)
            text = json.dumps(summary, indent=1, sort_keys=True, default=str)
            if args.metrics:
                Path(args.metrics).parent.mkdir(parents=True, exist_ok=True)
                Path(args.metrics).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.cmd == "verify":
            result = verify(args.store)
            print(json.dumps(result, indent=1, sort_keys=True, default=str))
            return 0 if result["ok"] else 1
        result = mark_unavailable(args.store, args.reason)
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    except (LandmarkError, hail.HailStoreError) as exc:
        _say(f"landmarks: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
