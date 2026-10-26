"""Base map vectors (B6 product P2): areas, water, places and peaks under the hail layers.

What it is: the outlines and names the map draws under its layers, built from public-domain federal sources only.
Reservations and roads come from the Census Bureau's 2026 TIGER/Line files, forests from the Forest Service's
administrative forest boundaries (seven Montana forests), parks from the Protected Areas Database's fee layer (PAD-US
4.1), lakes and rivers with their GNIS names from the USGS National Hydrography Dataset (NHD), summit names from the
USGS Geographic Names file (GNIS), summit heights from the USGS 3D Elevation Program (3DEP, sampled at each summit's
position), and the places with their 2020 census counts. No address, owner, contact or attribute beyond the kind,
name, position and zoom of a feature is read or written.

Output, written into the store next to the other hail/ folders (store/hail/base/):
  v/a.json                    band A (zooms 5 to 7): one file. Reservations, forests, national park land, the large
                              lakes and rivers, and the interstate routes.
  v/b/<cell>.json             band B (zooms 8 to 10): one file per 2 by 2 degree cell, named by its south-west corner
                              ("n46w114" is 46 N, 114 W). State parks, US and state routes, the middle lakes and rivers.
  v/c/<cell>.json             band C (zooms 11 and 12): one file per 1 by 1 degree cell, named the same way. The small
                              lakes of 0.02 km2 and up (streams start in band B, see the river rule).
  w/<tile>.json               band D (zooms 13 and up): one shard per B1 tile (hail.tile_name), the named water
                              polygons and streams from the large-scale NHD layers, and the local parks.
  peaks.json                  summits with their heights, ranked by height, with their minimum zoom.
  places.json                 places with their 2020 population, a population rank and their minimum zoom.
  index.json                  this product's own index (the sources, the counts, the bytes and the budgets measured).
  hail/index.json             gains "base", whose "vector" entry mirrors the state, as_of, counts, sources and bytes.
  hail/manifest.json          lists every file above with its bytes and SHA-256 (the entries under this product's
                              prefixes are replaced; the other base products keep theirs).

A feature sits in the band of its minimum zoom: its kind, name, minimum zoom "z", label point "l" (areas only, the pole
of inaccessibility computed here, in whole degrees to five decimals), route shield "s" (routes only: interstate, us or
state), park code "d" (parks only), and the geometry "g": for areas a list of rings (outer rings and holes; draw with the
even-odd rule; a ring is not repeated at its end), for lines a list of paths. Coordinates are WGS 84 longitude and
latitude, rounded to 5 decimals (about 1 m). Kinds: reservation, forest, park, lake, river, route.

Simplification (Douglas-Peucker, in metres): band A 500 m, band B 150 m, band C 50 m, band D none (the shards keep the
source's vertices). Band D features are clipped to their tile; bands B and C to their cell, so a feature that crosses an
edge appears in each file it touches, with its label point only in the file that holds the label.

Minimum zoom rules (every rule is a constant below and is written into the index):
  reservation 5; forest 5; park NP 5; NM and NRA 7; SP, SREC and REC 9; LP and LREC 13.
  lake (NHD small-scale area, km2): 100 and up 5; 20 and up 7; 2 and up 8; 0.2 and up 9; 0.02 and up 11.
  river (NHD small-scale TotDASqKM, km2): 10,000 and up 5; 3,000 and up 6; 1,000 and up 7; 300 and up 8; 100 and up 9.
    The floor is 100 km2: the statewide query was 52,291 streams at 30 km2 and 121,622 at 3 km2, more than the band
    files can hold at their budgets, so a stream under 100 km2 is in no file.
  route: interstate 7; US 8; state 9 (TIGER primary and secondary roads, names "I- 90", "US Hwy 93", "State Hwy 200").
  band D: every named large-scale lake and river and the local parks at 13.
  place (places.json): 50,000 and up 5; 10,000 and up 7; 2,000 and up 8; 500 and up 9; the rest 10. The places already
    on the first-paint base map keep the minimum zoom that map gives them (website/static/map/basemap.json).
  peak (peaks.json): ranked by height. Zoom 8 for each summit at least 25 km from every higher zoom 8 summit; zoom 10 for
    each other summit at least 10 km from every summit already placed; the rest zoom 12.

Budgets (gzip bytes, measured with gzip level 9): band A under 150,000; each band B file under 100,000; each band C file
under 60,000; each band D shard under 30,000. A file over its budget drops its least visible features first (the highest
minimum zoom, then the smallest size); reservations and forests are never dropped. The drops are counted per file in the
index, and a file whose protected features alone exceed the budget is written whole and marked over budget. Verify
fails on an over-budget file.

Sources, terms and credit (quoted from the sources' own metadata where it was read; see the index for each source's
date, size and state):
  Census TIGER/Line 2026 (AIANNH, PRISECROADS, PLACE)   https://www2.census.gov/geo/tiger/TIGER2026/
      "The TIGER/Line Shapefile products are not copyrighted ... acknowledgement must be given to the U.S. Census Bureau
      as the source." Credit: "Source: U.S. Census Bureau, TIGER/Line 2026."
  Census 2020 redistricting file (population of each place)   https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/Montana/mt2020.pl.zip
      Credit: "Source: U.S. Census Bureau, 2020 Census, Public Law 94-171 counts."
  Forest Service administrative forest boundaries (EDW)   https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer/0
      The layer's copyright line is empty and its description says "intended for read-only use". No public domain
      sentence was found: OPEN, for counsel before the layer ships (the Forest Service terms are asked in writing).
      Credit: "Source: U.S. Forest Service, Forest System Boundaries."
  PAD-US 4.1 Fee layer (parks)   https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Managers_PADUS/FeatureServer/0
      "This content describes the PAD-US dataset which is in the public domain." Credit: "Source: Protected Areas
      Database of the United States (PAD-US) 4.1, U.S. Geological Survey."
  USGS National Hydrography Dataset (lakes and rivers)   https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer
      Credit: "Source: U.S. Geological Survey, National Hydrography Dataset." The layer's own terms line was not read in
      this build (OPEN, the counsel list); the USGS credit is given.
  USGS Geographic Names (summit names)   https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_MT_Text.zip
      Credit: "Source: U.S. Geological Survey, Geographic Names Information System."
  USGS 3D Elevation Program (summit heights)   https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples
      "All 3DEP products available through The National Map are in the public domain and may be used without
      restriction." Credit: "3DEP data courtesy of the U.S. Geological Survey."

Failures (D16): a request that fails is retried (three tries with a wait, a 20 s connect and 300 s read limit); a cached
copy that exists is then used and its reason is recorded in the index. A source with no usable copy fails alone: the
kinds it feeds are left out of the files, the index names each failed source and kind, and the state is "partial".
A file that cannot be read is a failed source, never a crash. Only a store that lists no tiles, or a build in which
every source fails, makes the whole product unavailable.

Unavailability (D20): when the product cannot be built, the index block carries state "unavailable", the sentence
WORDS["unavailable"] in "problem" and the technical reason in "detail", and this product's files are removed (the
other base products keep theirs). The site shows the sentence; no outline or name is ever shown as an all-clear.
A missing input never reads as zero: a place with no population shows "Data unavailable", a summit with no height is
not ranked and is counted.

Command line (run from the repository root):
    python -m website.basemap2 build --store DIR --cache DIR [--offline] [--refresh] [--box W,S,E,N] [--deadline-at EPOCH]
    python -m website.basemap2 verify --store DIR [--cache DIR]
    python -m website.basemap2 unavailable --store DIR --reason TEXT

--box limits the band D fetches and shards to a box (a test run); without it band D covers every tile the store lists.
The cache keeps every response (one file per page of each query, named by the source, a digest of the query's
parameters and the page's offset), so a second run reads the cache and makes no request for a query it has. Measures are written by the caller (the report); the module returns them in its result.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import io
import json
import math
import re
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import hail
from . import stations as S

FORMAT_BAND = "hail-base-vector-v1"
FORMAT_TILE = "hail-base-water-v1"
FORMAT_PEAKS = "hail-base-peaks-v1"
FORMAT_PLACES = "hail-base-places-v1"
FORMAT_INDEX = "hail-base-index-v1"
PRODUCT = "vector"                       # this product's key: hail/base/index.json and hail/index.json base.vector
INDEX_KEY = "base"                       # the block in hail/index.json (the other base products keep their keys)
BASE_DIR = "hail/base"
A_FILE = "hail/base/v/a.json"
B_PREFIX = "hail/base/v/b/"
C_PREFIX = "hail/base/v/c/"
W_PREFIX = "hail/base/w/"
PEAKS_FILE = "hail/base/peaks.json"
PLACES_FILE = "hail/base/places.json"
INDEX_FILE = "hail/base/index.json"
MY_PREFIXES = ("hail/base/v/", "hail/base/w/", PEAKS_FILE, PLACES_FILE, INDEX_FILE)
# the files this product replaces on a build (the index file is shared with the other base products)
REMOVE_PREFIXES = ("hail/base/v/", "hail/base/w/", PEAKS_FILE, PLACES_FILE)
PARTS = ("a", "b", "c", "d", "places", "peaks")

BAND_ZOOMS = {"A": (5, 7), "B": (8, 10), "C": (11, 12), "D": (13, 18)}
BAND_TOL_M = {"A": 500.0, "B": 150.0, "C": 50.0, "D": 0.0}
BAND_BUDGET = {"A": 150_000, "B": 100_000, "C": 60_000, "D": 30_000}   # gzip bytes per file (per shard for D)
MT_BOX = (-116.05, 44.36, -104.03, 49.01)     # west, south, east, north: the Montana box of the requests
CELL_DEG = {"B": 2, "C": 1}                   # cell sizes in whole degrees; the cells are aligned to whole degrees
SPACING_KM = {8: 25.0, 10: 10.0}              # peak spacing for zooms 8 and 10 (zoom 12 is the rest)
PEAK_CHECK = {"name": "McDonald Peak", "metres": 2993.1, "feet": 9820,
              "source": "9,820 ft (2,993 m), the published height of McDonald Peak in the Mission Mountains of Lake County"}
PEAK_TOLERANCE_M = 30.0
PLACE_CHECK = ("Lolo", "Frenchtown")
RESERVATION_COUNT = 7
FOREST_COUNT = 7
RIVER_CHECK = ("Clark Fork", "Bitterroot River")
PROTECTED_KINDS = frozenset({"reservation", "forest"})
ALLOWED_KEYS = frozenset({"k", "n", "z", "l", "g", "s", "d"})
PLACE_LSAD = {"25": "city", "43": "town", "47": "village", "57": "cdp"}
NAME_EXPAND = (("Riv", "River"), ("Crk", "Creek"), ("Lk", "Lake"), ("Mtn", "Mountain"), ("Natl", "National"))

# Forest Service forests whose share of their area inside Montana is at least half (the clip measured 2026-10-25:
# Beaverhead-Deerlodge 99.1, Bitterroot 70.8, Custer Gallatin 97.6, Flathead 100, Helena-Lewis and Clark 100, Kootenai
# 98.0, Lolo 99.1 percent; Idaho Panhandle 1.2 percent and the rest below half).
FOREST_NAMES = ("Beaverhead-Deerlodge National Forest", "Bitterroot National Forest", "Custer Gallatin National Forest",
                "Flathead National Forest", "Helena-Lewis and Clark National Forest", "Kootenai National Forest",
                "Lolo National Forest")

LAKE_RULES = ((100.0, 5), (20.0, 7), (2.0, 8), (0.2, 9), (0.02, 11))           # NHD AREASQKM, km2 -> minimum zoom
RIVER_RULES = ((10000.0, 5), (3000.0, 6), (1000.0, 7), (300.0, 8), (100.0, 9))
RIVER_FLOOR_KM2 = RIVER_RULES[-1][0]      # the smallest drainage area that is fetched (the last rule)
LAKE_FLOOR_KM2 = LAKE_RULES[-1][0]        # the smallest lake area that is fetched (the last rule)
PARK_RULES = {"NP": ("national park", 5), "NM": ("national monument", 7), "NRA": ("national recreation area", 7),
              "SP": ("state park", 9), "SREC": ("state recreation area", 9), "REC": ("recreation area", 9),
              "LP": ("local park", 13), "LREC": ("local recreation area", 13)}
ROUTE_ZOOM = {"interstate": 7, "us": 8, "state": 9}
ROUTE_PATTERNS = (("interstate", "I", re.compile(r"^I- ?(\d+)$"), "I-{}"),
                  ("us", "U", re.compile(r"^US Hwy (\d+)$"), "US-{}"),
                  ("state", "S", re.compile(r"^State Hwy (\d+)$"), "MT-{}"))
LARGE_ZOOM = 13                                              # band D: every named large-scale feature
PLACE_RULES = ((50000, 5), (10000, 7), (2000, 8), (500, 9))  # population -> minimum zoom; the rest are zoom 10

# The NHD layers the requests use. The fields differ by layer (the service answers 400 for an unknown field).
NHD = {
    "small_lines": {"layer": 4, "where": f"GNIS_NAME IS NOT NULL AND TotDASqKM >= {RIVER_FLOOR_KM2:g}",
                    "fields": "OBJECTID,GNIS_NAME,TotDASqKM,LENGTHKM,FTYPE,FCODE", "simplify": 0.0001, "page": 1000},
    "small_areas": {"layer": 10, "where": f"GNIS_NAME IS NOT NULL AND AREASQKM >= {LAKE_FLOOR_KM2:g}",
                    "fields": "OBJECTID,GNIS_NAME,AREASQKM,FTYPE,FCODE", "simplify": 0.0001, "page": 1000},
    "large_lines": {"layer": 6, "where": "gnis_name IS NOT NULL",
                    "fields": "OBJECTID,gnis_name,lengthkm,ftype,fcode", "simplify": 0.0, "page": 1000},
    "large_areas": {"layer": 12, "where": "GNIS_NAME IS NOT NULL",
                    "fields": "OBJECTID,GNIS_NAME,AREASQKM,FTYPE,FCODE", "simplify": 0.0, "page": 1000},
}
NHD_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/{layer}/query"
EDW_URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer/0/query"
PADUS_URL = ("https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Managers_PADUS/FeatureServer/0/query")
PADUS_WHERE = "State_Nm = 'MT' AND Des_Tp IN ('NP','NM','NRA','SP','SREC','REC','LP','LREC')"
DEM_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples"
AIANNH_URL = "https://www2.census.gov/geo/tiger/TIGER2026/AIANNH/tl_2026_us_aiannh.zip"
PLACE_URL = "https://www2.census.gov/geo/tiger/TIGER2026/PLACE/tl_2026_30_place.zip"
PRISEC_URL = "https://www2.census.gov/geo/tiger/TIGER2026/PRISECROADS/tl_2026_30_prisecroads.zip"
PL2020_URL = ("https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/"
              "Montana/mt2020.pl.zip")
GNIS_URL = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_MT_Text.zip")
USER_AGENT = "montana-hail-watch-basemap2/1 (+https://github.com/carson14dy/RoofingApp)"
READ_TIMEOUT = (20, 300)                                     # seconds to connect, and to wait for each response
PACE_S = {"hydro.nationalmap.gov": 0.5, "default": 0.2}
ATTEMPTS = 3
REASON_NO_ANSWER = S.REASON_NO_ANSWER

WORDS = {
    "unavailable": ("Map outlines and names could not be loaded in this update; that is not the same as no outline or "
                    "name. This is not an all-clear."),
    "part_unavailable": ("{Part} could not be loaded in this update; that is not the same as no {one}. This is not an "
                         "all-clear."),
    "partial_named": ("Some map outlines and names could not be loaded in this update for {names}; that is not the same "
                      "as none there. This is not an all-clear."),
    "peaks_unknown": ("The height of {count} summits could not be read in this update; they are not ranked, which is not "
                      "the same as no height. This is not an all-clear."),
    "population_unknown": ("The 2020 population of {count} places could not be read in this update; they show Data "
                           "unavailable."),
    "peak_note": ("A summit height is the 3D Elevation Program's value at the summit's position, in metres and feet. "
                  "A summit with no value shows Data unavailable."),
    "place_note": ("A place's population is the 2020 census count. A place with no count shows Data unavailable."),
    "route_note": "A route shield is an interstate, US or state route number from the Census road file.",
    "water_note": ("Lakes and rivers are the USGS National Hydrography Dataset with its Geographic Names; a stream or lake "
                   "shown here is not a statement about water at an address."),
    "park_note": "A park outline is from the Protected Areas Database; a park is not a statement about its use.",
    "coverage_box": ("Lake, river and park outlines are built only for the tiles in the box {box}; the tiles outside it "
                     "show Data unavailable until a build covers them. This is not an all-clear."),
}
PART_WORDS = {
    "reservation": ("Reservation outlines", "reservation outline"),
    "forest": ("Forest outlines", "forest outline"),
    "park": ("Park outlines", "park outline"),
    "water": ("Lake and river outlines and names", "lake or river name"),
    "route": ("Route shields", "route shield"),
    "place": ("Place names and populations", "place name"),
    "peak": ("Summit heights", "summit height"),
}


class BasemapError(S.StationsError):
    """A file or figure that cannot be used. The message is plain words, lower case, with no full stop. It is a
    StationsError, so a download that answers with it is a failed request (retried, then the cached copy), not a crash."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gzlen(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


# ---------------------------------------------------------------- requests and the cache (D16)

class _Ctx:
    """The request state of one build: the cache root, the offline and refresh flags, the pacing per host, the counts
    and the source records the index keeps."""

    def __init__(self, cache: Path, *, offline: bool, refresh: bool, deadline_at: float | None):
        self.cache = Path(cache)
        self.offline = offline
        self.refresh = refresh
        self.deadline_at = deadline_at
        self.last: dict[str, float] = {}
        self.requests = 0
        self.downloaded = 0
        self.sources: dict[str, dict] = {}
        self.failures: list[dict] = []

    def record(self, source: str, state: str, reason: str | None, nbytes: int = 0) -> None:
        """Counts one file of a source as fetched, read from the cache, or failed; the first three reasons are kept."""
        row = self.sources.setdefault(source, {"fetched": 0, "cache": 0, "failed": 0, "bytes": 0, "reasons": []})
        key = "fetched" if state == "fetched" else ("failed" if state == "failed" else "cache")
        row[key] += 1
        row["bytes"] += int(nbytes)
        if reason and len(row["reasons"]) < 3:
            row["reasons"].append(reason)

    def source_states(self) -> dict:
        """Each source's state for the index: fetched, cache (every file read from the cache), partial (some files
        failed) or failed (none usable)."""
        out = {}
        for name, row in self.sources.items():
            if row["failed"] and not (row["fetched"] or row["cache"]):
                state = "failed"
            elif row["failed"]:
                state = "partial"
            elif row["fetched"]:
                state = "fetched"
            else:
                state = "cache"
            out[name] = {"state": state, "files": row["fetched"] + row["cache"] + row["failed"],
                         "fetched": row["fetched"], "cache": row["cache"], "failed": row["failed"],
                         "bytes": row["bytes"], "reasons": row["reasons"]}
        return out

    def pace(self, host: str) -> None:
        gap = PACE_S.get(host, PACE_S["default"]) - (time.monotonic() - self.last.get(host, 0.0))
        if gap > 0:
            time.sleep(gap)
        self.last[host] = time.monotonic()
        self.requests += 1


def _host(url: str) -> str:
    return url.split("/")[2] if "//" in url else "default"


def fetch(ctx: _Ctx, source: str, url: str, name: str, check, *, params: dict | None = None,
          method: str = "GET") -> tuple[bytes | None, str, str | None]:
    """(bytes or None, state, reason). The cache file is name under the cache root. A cached file that passes check is
    read unless refresh is set. Offline, no request is made. Otherwise the request is tried ATTEMPTS times; a copy that
    passes check is kept. When the request fails and a cached copy exists, the cached copy is used and the reason is
    kept (D16). A response that fails check is never written."""
    import requests
    path = ctx.cache / name
    cached, corrupt = None, None
    if path.is_file():
        cached = path.read_bytes()
        try:
            check(cached)
        except S.StationsError as exc:
            corrupt, cached = str(exc), None
        else:
            if not ctx.refresh:
                ctx.record(source, "cache", None, len(cached))
                return cached, "cache", None
    if ctx.offline:
        if cached is not None:
            ctx.record(source, "offline", "offline: the cached copy was used and was not re-read", len(cached))
            return cached, "offline", "offline: the cached copy was used and was not re-read"
        reason = ("the cached copy is not usable and this build makes no requests" if corrupt
                  else "the cache has no copy and this build makes no requests")
        ctx.record(source, "failed", reason)
        return None, "failed", reason
    last = REASON_NO_ANSWER
    for attempt in range(1, ATTEMPTS + 1):
        if ctx.deadline_at is not None and time.monotonic() >= ctx.deadline_at:
            last = REASON_NO_ANSWER
            break
        ctx.pace(_host(url))
        try:
            if method == "POST":
                resp = requests.post(url, data=params or {}, headers={"User-Agent": USER_AGENT}, timeout=READ_TIMEOUT)
            else:
                resp = requests.get(url, params=params or {}, headers={"User-Agent": USER_AGENT}, timeout=READ_TIMEOUT)
            status, data = resp.status_code, resp.content
        except requests.RequestException as exc:
            last = type(exc).__name__
        else:
            if status == 200:
                try:
                    check(data)
                except S.StationsError as exc:
                    last = str(exc)
                else:
                    ctx.downloaded += len(data)
                    try:
                        S._write_atomic(path, data)
                    except OSError as exc:
                        note = f"the file could not be kept in the cache ({type(exc).__name__})"
                        ctx.record(source, "fetched", note, len(data))
                        return data, "fetched", note
                    note = "the cached copy was not usable and was replaced" if corrupt else None
                    ctx.record(source, "fetched", note, len(data))
                    return data, "fetched", note
            else:
                last = f"HTTP {status}"
                if status != 429 and status < 500:
                    break
        if attempt < ATTEMPTS:
            time.sleep(1.5 * attempt)
    if cached is not None:
        reason = f"served the cached copy after: {last}"
        ctx.record(source, "cache", reason, len(cached))
        return cached, "cache", reason
    ctx.record(source, "failed", last)
    return None, "failed", last


def _check_features(data: bytes) -> None:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BasemapError("the answer is not JSON") from exc
    if not isinstance(doc, dict):
        raise BasemapError("the answer is not an object")
    if "error" in doc:
        raise BasemapError("the service answered with an error")
    if not isinstance(doc.get("features"), list):
        raise BasemapError("the answer has no features list")


def _check_samples(data: bytes) -> None:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BasemapError("the elevation answer is not JSON") from exc
    if not isinstance(doc, dict) or "error" in doc or not isinstance(doc.get("samples"), list):
        raise BasemapError("the elevation answer has no samples list")


def _check_zip(*names: str):
    def check(data: bytes) -> None:
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise BasemapError("the file is not a zip archive") from exc
        members = z.namelist()
        for name in names:
            if not any(m.endswith(name) for m in members):
                raise BasemapError(f"the archive has no {name} member")
    return check


# ---------------------------------------------------------------- readers

def _shp_member(data: bytes, ext: str) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    for name in z.namelist():
        if name.lower().endswith(ext):
            return name
    raise BasemapError(f"the archive has no {ext} member")


def _shp_reader(data: bytes):
    """A pyshp reader over the zip's shapefile members (read in memory). pyshp is imported here only: the tests that
    need it skip without it."""
    import shapefile
    z = zipfile.ZipFile(io.BytesIO(data))
    stem = _shp_member(data, ".shp")[:-4]
    return shapefile.Reader(shp=io.BytesIO(z.read(stem + ".shp")), shx=io.BytesIO(z.read(stem + ".shx")),
                            dbf=io.BytesIO(z.read(stem + ".dbf")), encoding="utf-8")


def _shp_parts(shape) -> list[list[tuple[float, float]]]:
    pts = shape.points
    idx = list(shape.parts) + [len(pts)]
    return [[(float(x), float(y)) for x, y in pts[idx[i]:idx[i + 1]]] for i in range(len(shape.parts))]


def _num(value) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


_OUTLINE: list | None = None


def montana_outline() -> list[list[tuple[float, float]]]:
    """The Montana outline: the basemap's Montana land ring (website/static/map/basemap.json), read once."""
    global _OUTLINE
    if _OUTLINE is None:
        path = Path(__file__).resolve().parent / "static" / "map" / "basemap.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        rings = []
        for feat in doc["land"]["features"]:
            if feat["properties"].get("montana"):
                geom = feat["geometry"]
                polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
                for poly in polys:
                    rings.extend([[(float(x), float(y)) for x, y in ring] for ring in poly])
        _OUTLINE = rings
    return _OUTLINE


def in_montana(lon: float, lat: float) -> bool:
    """Even-odd point in polygon test against the Montana outline."""
    inside = False
    for ring in montana_outline():
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def read_reservations(data: bytes) -> list[dict]:
    """The reservations: the entities whose GEOID ends in R (trust lands end in T) and whose interior point lies in
    Montana. The LSAD code is not used: Montana's reservations carry 86 or 96 ("Indian Reservation")."""
    out = []
    reader = _shp_reader(data)
    for rec, shp in zip(reader.iterRecords(), reader.iterShapes()):
        d = rec.as_dict()
        if not str(d.get("GEOID") or "").strip().endswith("R"):
            continue
        lon, lat = _num(d.get("INTPTLON")), _num(d.get("INTPTLAT"))
        if lon is None or lat is None or not in_montana(lon, lat):
            continue
        out.append({"name": str(d.get("NAMELSAD") or d.get("NAME") or "").strip(), "parts": _shp_parts(shp),
                    "geoid": str(d.get("GEOID") or "")})
    return out


def route_name(fullname: str, rttyp: str) -> tuple[str, str] | None:
    """(class, shield text) for a TIGER road name: "I- 90" (I), "US Hwy 93" (U), "State Hwy 200" (S)."""
    text = (fullname or "").strip()
    for cls, code, pattern, shield in ROUTE_PATTERNS:
        if (rttyp or "").strip() == code:
            hit = pattern.match(text)
            if hit:
                return cls, shield.format(hit.group(1))
    return None


def read_routes(data: bytes) -> list[dict]:
    out = []
    reader = _shp_reader(data)
    for rec, shp in zip(reader.iterRecords(), reader.iterShapes()):
        d = rec.as_dict()
        named = route_name(str(d.get("FULLNAME") or ""), str(d.get("RTTYP") or ""))
        if named is None:
            continue
        out.append({"class": named[0], "ref": named[1], "parts": _shp_parts(shp)})
    return out


def read_places(data: bytes) -> list[dict]:
    out = []
    reader = _shp_reader(data)
    for rec in reader.iterRecords():
        d = rec.as_dict()
        lat, lon = _num(d.get("INTPTLAT")), _num(d.get("INTPTLON"))
        if lat is None or lon is None or not str(d.get("NAME") or "").strip():
            continue
        out.append({"name": str(d["NAME"]).strip(), "lat": lat, "lon": lon,
                    "placefp": str(d.get("PLACEFP") or "").strip(), "lsad": str(d.get("LSAD") or "").strip()})
    return out


def read_population(data: bytes) -> dict[str, int]:
    """The 2020 population of each place, keyed by the five-digit place code. The layout is the census file's own:
    the geographic header's SUMLEV (field 2), LOGRECNO (field 7) and PLACE (field 29) and the segment's P0010001
    total (field 5, keyed by its LOGRECNO in field 4)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    geo = z.read("mtgeo2020.pl").decode("latin-1").splitlines()
    places = {}
    for line in geo:
        p = line.split("|")
        if len(p) > 29 and p[2] == "160":
            places[p[7]] = p[29]
    pops = {}
    for line in z.read("mt000012020.pl").decode("latin-1").splitlines():
        p = line.split("|")
        if len(p) > 5 and p[4] in places and p[5].strip().isdigit():
            pops[places[p[4]]] = int(p[5])
    return pops


def read_summits(data: bytes) -> list[dict]:
    """The GNIS Summit rows (feature class Summit): name, position and county. The file has no height."""
    z = zipfile.ZipFile(io.BytesIO(data))
    member = next(m for m in z.namelist() if m.endswith("DomesticNames_MT.txt"))
    lines = z.read(member).decode("utf-8", errors="replace").splitlines()
    header = [h.strip().lstrip("﻿") for h in lines[0].split("|")]
    idx = {h: i for i, h in enumerate(header)}
    out = []
    for line in lines[1:]:
        p = line.split("|")
        if len(p) < len(header) or p[idx["feature_class"]] != "Summit":
            continue
        lat, lon = _num(p[idx["prim_lat_dec"]]), _num(p[idx["prim_long_dec"]])
        name = p[idx["feature_name"]].strip()
        if lat is None or lon is None or not name:
            continue
        out.append({"name": name, "lat": lat, "lon": lon, "county": p[idx["county_name"]].strip(),
                    "feature_id": p[idx["feature_id"]].strip()})
    return out


def service_parts(geom: dict | None) -> list[list[tuple[float, float]]] | None:
    if not geom:
        return None
    if "rings" in geom:
        return [[(float(x), float(y)) for x, y in ring] for ring in geom["rings"]]
    if "paths" in geom:
        return [[(float(x), float(y)) for x, y in path] for path in geom["paths"]]
    return None


def _attrs(feature: dict) -> dict:
    return {str(k).upper(): v for k, v in (feature.get("attributes") or {}).items()}


def request_key(params: dict) -> str:
    """A short digest of one query's parameters. A page's cache file carries it, so a query that changes (its where
    clause, its fields or its tolerance) never reads a page of an older query."""
    return hashlib.sha1(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:10]


def page_name(source: str, key: str, params: dict, offset: int) -> str:
    """The cache file of one page of one query, relative to the cache root."""
    return f"{source}/{key}_{request_key(params)}_{offset:07d}.json"


def fetch_pages(ctx: _Ctx, source: str, url: str, key: str, params: dict, page: int) -> tuple[list[dict], list[str]]:
    """Every feature of one query, paged by OBJECTID. Each page is a cache file. A page that fails ends the query: the
    features read so far are kept and the failure is named (D16); the pages already cached are read next time."""
    feats, problems = [], []
    offset = 0
    while True:
        q = dict(params, orderByFields="OBJECTID", resultOffset=offset, resultRecordCount=page, f="json")
        data, state, reason = fetch(ctx, source, url, page_name(source, key, params, offset), _check_features, params=q)
        if data is None:
            problems.append(reason or REASON_NO_ANSWER)
            break
        doc = json.loads(data.decode("utf-8"))
        batch = doc.get("features", [])
        feats.extend(batch)
        if not doc.get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)
    return feats, problems


def nhd_params(source: str, env: tuple[float, float, float, float]) -> dict:
    """The query of one NHD layer over an envelope (west, south, east, north), without its paging."""
    spec = NHD[source]
    w, s, e, n = env
    params = {"where": spec["where"], "geometry": json.dumps({"xmin": w, "ymin": s, "xmax": e, "ymax": n,
                                                              "spatialReference": {"wkid": 4326}}),
              "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
              "outFields": spec["fields"], "returnGeometry": "true", "outSR": 4326, "geometryPrecision": 5}
    if spec["simplify"]:
        params["maxAllowableOffset"] = spec["simplify"]
    return params


def nhd_features(ctx: _Ctx, source: str, env: tuple[float, float, float, float], key: str) -> tuple[list[dict], list[str]]:
    spec = NHD[source]
    return fetch_pages(ctx, f"nhd_{source}", NHD_URL.format(layer=spec["layer"]), key, nhd_params(source, env),
                       spec["page"])


def padus_params() -> dict:
    """The park query: the Montana fee layer for the designations this product uses, with outlines simplified by the
    service at about 5 m."""
    return {"where": PADUS_WHERE, "outFields": "OBJECTID,Des_Tp,Unit_Nm,Loc_Nm,GIS_Acres", "returnGeometry": "true",
            "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.00005}


def padus_features(ctx: _Ctx) -> tuple[list[dict], list[str]]:
    return fetch_pages(ctx, "padus", PADUS_URL, "mt", padus_params(), 1000)


def forest_params() -> dict:
    """The forest query: every forest boundary that meets the Montana box, outlines simplified at about 20 m."""
    w, s, e, n = MT_BOX
    return {"where": "1=1", "geometry": json.dumps({"xmin": w, "ymin": s, "xmax": e, "ymax": n,
                                                     "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "outFields": "OBJECTID,forestname", "returnGeometry": "true", "outSR": 4326,
            "maxAllowableOffset": 0.0002, "geometryPrecision": 5}


def forest_features(ctx: _Ctx) -> tuple[list[dict], list[str]]:
    return fetch_pages(ctx, "edw", EDW_URL, "mt", forest_params(), 1000)


def sample_elevations(ctx: _Ctx, points: list[tuple[float, float]], batch: int = 200) -> tuple[list[float | None], list[str]]:
    """The 3DEP height in metres at each point, in batches (one request per batch, cached by its points)."""
    out: list[float | None] = [None] * len(points)
    problems = []
    for start in range(0, len(points), batch):
        chunk = points[start:start + batch]
        digest = hashlib.sha1(json.dumps(chunk).encode("utf-8")).hexdigest()[:12]
        params = {"geometry": json.dumps({"points": [[lon, lat] for lon, lat in chunk],
                                          "spatialReference": {"wkid": 4326}}),
                  "geometryType": "esriGeometryMultipoint", "returnFirstValueOnly": "true", "f": "json"}
        data, state, reason = fetch(ctx, "3dep", DEM_URL, f"3dep/samples_{start:05d}_{digest}.json", _check_samples,
                                    params=params, method="POST")
        if data is None:
            problems.append(reason or REASON_NO_ANSWER)
            continue
        doc = json.loads(data.decode("utf-8"))
        for sample in doc["samples"]:
            loc = int(sample.get("locationId", -1))
            if 0 <= loc < len(chunk):
                value = _num(sample.get("value"))
                out[start + loc] = value if value is not None and value > -9000 else None
    return out, problems


# ---------------------------------------------------------------- geometry

_KY = 110_574.0                                  # metres per degree of latitude (a local scale for tolerances)
_KX = 111_320.0 * math.cos(math.radians(46.9))   # metres per degree of longitude at Montana's middle latitude


def _dp(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker in metres; the first and last points are kept. tol 0 keeps every point."""
    if tol <= 0 or len(points) <= 2:
        return list(points)
    xy = [(lon * _KX, lat * _KY) for lon, lat in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        ax, ay = xy[i]
        bx, by = xy[j]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        best, pick = -1.0, -1
        for k in range(i + 1, j):
            px, py = xy[k]
            if length2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, pick = d, k
        if best > tol:
            keep[pick] = True
            stack.append((i, pick))
            stack.append((pick, j))
    return [p for p, k in zip(points, keep) if k]


def _tidy(parts: list[list[tuple[float, float]]], closed: bool) -> list[list[list[float]]]:
    """Rounds to 5 decimals, drops repeated points, and drops parts too short to draw (a ring needs 3 points, a path 2).
    A ring is returned without its closing point."""
    out = []
    for part in parts:
        pts: list[tuple[float, float]] = []
        for lon, lat in part:
            p = (round(lon, 5), round(lat, 5))
            if not pts or pts[-1] != p:
                pts.append(p)
        if closed:
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) < 3 or _ring_area_deg(pts) <= 1e-12:
                continue
        elif len(pts) < 2:
            continue
        out.append([[lon, lat] for lon, lat in pts])
    return out


def _ring_area_deg(ring) -> float:
    total = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def area_km2(parts: list[list[tuple[float, float]]]) -> float:
    """The area in km2 of rings (the absolute sum; a hole is counted as if it were land, which only ranks features)."""
    total = 0.0
    for ring in parts:
        n = len(ring)
        s = 0.0
        for i in range(n):
            x1, y1 = ring[i][0] * _KX, ring[i][1] * _KY
            x2, y2 = ring[(i + 1) % n][0] * _KX, ring[(i + 1) % n][1] * _KY
            s += x1 * y2 - x2 * y1
        total += abs(s) / 2.0
    return total / 1e6


def length_km(parts: list[list[tuple[float, float]]]) -> float:
    total = 0.0
    for path in parts:
        for (x1, y1), (x2, y2) in zip(path, path[1:]):
            total += math.hypot((x2 - x1) * _KX, (y2 - y1) * _KY)
    return total / 1000.0


def _signed_distance(x: float, y: float, rings: list[list[tuple[float, float]]]) -> float:
    inside = False
    best = math.inf
    for ring in rings:
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            ex, ey = xj - xi, yj - yi
            L2 = ex * ex + ey * ey
            if L2 == 0:
                d2 = (x - xi) ** 2 + (y - yi) ** 2
            else:
                t = max(0.0, min(1.0, ((x - xi) * ex + (y - yi) * ey) / L2))
                d2 = (x - (xi + t * ex)) ** 2 + (y - (yi + t * ey)) ** 2
            if d2 < best:
                best = d2
            j = i
    dist = math.sqrt(best) if best != math.inf else 0.0
    return dist if inside else -dist


def pole(rings: list[list[tuple[float, float]]]) -> tuple[float, float] | None:
    """The pole of inaccessibility (the point farthest inside the outline) in longitude and latitude, by the grid
    search with a priority queue that stops when no cell can beat the best by the precision (about 1% of the
    outline's width, at least 2 m). Holes are rings too (even-odd)."""
    metric = [[(lon * _KX, lat * _KY) for lon, lat in ring] for ring in rings if len(ring) >= 3]
    if not metric:
        return None
    xs = [x for r in metric for x, _ in r]
    ys = [y for r in metric for _, y in r]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    width, height = maxx - minx, maxy - miny
    if width <= 0 or height <= 0:
        x, y = metric[0][0]
        return x / _KX, y / _KY
    precision = max(2.0, min(width, height) / 100.0)
    size = min(width, height)
    half = size / 2.0
    root2 = math.sqrt(2.0)

    def cell(x: float, y: float, h: float):
        d = _signed_distance(x, y, metric)
        return (d, x, y, h, d + h * root2)

    queue: list = []
    counter = 0
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            c = cell(x + half, y + half, half)
            heapq.heappush(queue, (-c[4], counter, c))
            counter += 1
            y += size
        x += size
    best = cell((minx + maxx) / 2.0, (miny + maxy) / 2.0, 0.0)
    while queue:
        _, _, c = heapq.heappop(queue)
        if c[0] > best[0]:
            best = c
        if c[4] - best[0] <= precision:
            continue
        h = c[3] / 2.0
        for dx, dy in ((-h, -h), (h, -h), (-h, h), (h, h)):
            cc = cell(c[1] + dx, c[2] + dy, h)
            heapq.heappush(queue, (-cc[4], counter, cc))
            counter += 1
    return best[1] / _KX, best[2] / _KY


def _clip_ring(ring: list[tuple[float, float]], box: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    """Sutherland-Hodgman clip of one ring to the box (west, south, east, north) in longitude and latitude."""
    w, s, e, n = box
    pts = list(ring)
    tests = (
        (lambda p: p[0] >= w, lambda a, b: (w, a[1] + (w - a[0]) * (b[1] - a[1]) / (b[0] - a[0]))),
        (lambda p: p[0] <= e, lambda a, b: (e, a[1] + (e - a[0]) * (b[1] - a[1]) / (b[0] - a[0]))),
        (lambda p: p[1] >= s, lambda a, b: (a[0] + (s - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), s)),
        (lambda p: p[1] <= n, lambda a, b: (a[0] + (n - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), n)),
    )
    for inside, cross in tests:
        if not pts:
            return []
        out = []
        prev = pts[-1]
        for cur in pts:
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
            prev = cur
        pts = out
    return pts


def _clip_segment(p, q, box):
    w, s, e, n = box
    x0, y0 = p
    x1, y1 = q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - w), (dx, e - x0), (-dy, y0 - s), (dy, n - y0)):
        if pp == 0:
            if qq < 0:
                return None
            continue
        r = qq / pp
        if pp < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def _clip_path(path, box) -> list[list[tuple[float, float]]]:
    out, cur = [], []
    for a, b in zip(path, path[1:]):
        seg = _clip_segment(a, b, box)
        if seg is None:
            if len(cur) >= 2:
                out.append(cur)
            cur = []
            continue
        p, q = seg
        if cur and cur[-1] == p:
            cur.append(q)
        else:
            if len(cur) >= 2:
                out.append(cur)
            cur = [p, q]
    if len(cur) >= 2:
        out.append(cur)
    return out


def _bbox(parts) -> tuple[float, float, float, float]:
    xs = [x for part in parts for x, _ in part]
    ys = [y for part in parts for _, y in part]
    return min(xs), min(ys), max(xs), max(ys)


def owns(point, box) -> bool:
    """A label belongs to the box that holds it, the west and south edges in and the east and north edges out."""
    w, s, e, n = box
    return point is not None and w <= point[0] < e and s <= point[1] < n


# ---------------------------------------------------------------- rules

def lake_zoom(area: float | None) -> int | None:
    if area is None:
        return None
    for limit, zoom in LAKE_RULES:
        if area >= limit:
            return zoom
    return None


def river_zoom(total_km2: float | None) -> int | None:
    if total_km2 is None:
        return None
    for limit, zoom in RIVER_RULES:
        if total_km2 >= limit:
            return zoom
    return None


def band_of(zoom: int) -> str:
    for band, (lo, hi) in BAND_ZOOMS.items():
        if lo <= zoom <= hi:
            return band
    raise BasemapError(f"no band holds zoom {zoom}")


def expand_name(name: str) -> str:
    """The TIGER abbreviations the table expands (Riv, Crk, Lk, Mtn, Natl), as whole words."""
    out = name
    for short, full in NAME_EXPAND:
        out = re.sub(rf"\b{short}\b", full, out)
    return out


def place_zoom(population: int | None) -> int:
    if population is None:
        return 10
    for limit, zoom in PLACE_RULES:
        if population >= limit:
            return zoom
    return 10


def cell_name(lat0: int, lon0: int) -> str:
    return f"{'n' if lat0 >= 0 else 's'}{abs(lat0)}{'e' if lon0 >= 0 else 'w'}{abs(lon0)}"


def cell_box(lat0: int, lon0: int, size: int) -> tuple[float, float, float, float]:
    return (float(lon0), float(lat0), float(lon0 + size), float(lat0 + size))


def cells_for_box(size: int, box=MT_BOX) -> list[tuple[int, int]]:
    """The south-west corners of the whole-degree cells of this size that touch the box."""
    w, s, e, n = box
    out = []
    for lat0 in range(math.floor(s / size) * size, math.ceil(n / size) * size, size):
        for lon0 in range(math.floor(w / size) * size, math.ceil(e / size) * size, size):
            out.append((lat0, lon0))
    return out


def tile_box(tile: str) -> tuple[float, float, float, float]:
    """The box of a B1 tile: the grid's 0.1 degree tile (10 cells of 0.01 degree). Row 0 is north of 55 N and column 0
    starts at 130 W, so tile r0079_c0199 spans 47.1 N to 47.0 N and 110.1 W to 110.0 W."""
    m = re.match(r"^r(\d{4})_c(\d{4})$", tile)
    if not m:
        raise BasemapError(f"the tile name {tile} is not a B1 tile name")
    tr, tc = int(m.group(1)), int(m.group(2))
    west = round(-130.0 + tc * 0.1, 6)
    north = round(55.0 - tr * 0.1, 6)
    return (west, round(north - 0.1, 6), round(west + 0.1, 6), north)


def tile_of(lat: float, lon: float) -> tuple[int, int]:
    row, col = hail.cell_for(lat, lon)
    return row // hail.TILE, col // hail.TILE


def tiles_for_bbox(bbox, names: set[str]) -> list[str]:
    """The listed tile names that a bounding box (west, south, east, north) touches."""
    w, s, e, n = bbox
    r0, c0 = tile_of(n, w)
    r1, c1 = tile_of(s, e)
    out = []
    for tr in range(r0, r1 + 1):
        for tc in range(c0, c1 + 1):
            name = hail.tile_name(tr, tc)
            if name in names:
                out.append(name)
    return out


def coverage_tiles(tiles: list[str], box) -> set[str]:
    """The listed tiles that touch the coverage box (the whole Montana box when no box is given)."""
    if box is None:
        return set(tiles)
    return set(tiles_for_bbox(box, set(tiles)))


# ---------------------------------------------------------------- features
# ---------------------------------------------------------------- features and budgets

def _rec(kind: str, name: str, zoom: int, parts, *, closed: bool, size: float, shield: str | None = None,
         code: str | None = None) -> dict:
    """A feature before its band's simplification: the raw parts in longitude and latitude."""
    return {"k": kind, "n": expand_name(name), "z": int(zoom), "p": parts, "closed": closed, "size": float(size), "s": shield,
            "d": code}


def finish(rec: dict, tol: float) -> dict | None:
    """The feature for one record: simplified at the band's tolerance in metres (Douglas-Peucker), rounded to 5 decimals,
    tidied, and given the pole of inaccessibility for an area (computed on the simplified rings). None when nothing is
    left to draw."""
    parts = [_dp(p, tol) for p in rec["p"]] if tol > 0 else rec["p"]
    g = _tidy(parts, rec["closed"])
    if not g:
        return None
    label = None
    if rec["closed"]:
        at = pole(g)
        if at is not None:
            label = [round(at[0], 5), round(at[1], 5)]
    return {"k": rec["k"], "n": rec["n"], "z": rec["z"], "l": label, "s": rec["s"], "d": rec["d"], "g": g,
            "size": rec["size"], "protect": rec["k"] in PROTECTED_KINDS}


def build_features(inputs: dict) -> dict[str, list[dict]]:
    """The features of each band. Each source's records go to the band of their minimum zoom, simplified at that band's
    tolerance. inputs holds the parsed sources (a missing source is an absent key or None)."""
    recs: list[dict] = []
    for r in inputs.get("reservations") or []:
        recs.append(_rec("reservation", r["name"], 5, r["parts"], closed=True, size=area_km2(r["parts"])))
    for fo in inputs.get("forests") or []:
        recs.append(_rec("forest", fo["name"], 5, fo["parts"], closed=True, size=area_km2(fo["parts"])))
    for pk in inputs.get("parks") or []:
        spec = PARK_RULES.get(pk["code"])
        if spec is not None:
            recs.append(_rec("park", pk["name"], spec[1], pk["parts"], closed=True, size=pk["size"], code=pk["code"]))
    for lk in inputs.get("lakes_small") or []:
        zoom = lake_zoom(lk["area"])
        if zoom is not None:
            recs.append(_rec("lake", lk["name"], zoom, lk["parts"], closed=True, size=lk["area"]))
    for rv in inputs.get("rivers_small") or []:
        zoom = river_zoom(rv["total"])
        if zoom is not None:
            recs.append(_rec("river", rv["name"], zoom, rv["parts"], closed=False, size=rv["length"]))
    for rt in inputs.get("routes") or []:
        recs.append(_rec("route", rt["ref"], ROUTE_ZOOM[rt["class"]], rt["parts"], closed=False,
                         size=length_km(rt["parts"]), shield=rt["class"]))
    for lk in inputs.get("lakes_large") or []:
        recs.append(_rec("lake", lk["name"], LARGE_ZOOM, lk["parts"], closed=True, size=lk["area"]))
    for rv in inputs.get("rivers_large") or []:
        recs.append(_rec("river", rv["name"], LARGE_ZOOM, rv["parts"], closed=False, size=rv["length"]))
    out: dict[str, list[dict]] = {band: [] for band in BAND_ZOOMS}
    for rec in recs:
        band = band_of(rec["z"])
        feature = finish(rec, BAND_TOL_M[band])
        if feature is not None:
            out[band].append(feature)
    return out


def encode(f: dict) -> dict:
    out = {"k": f["k"], "n": f["n"], "z": f["z"]}
    if f.get("l") is not None:
        out["l"] = f["l"]
    if f.get("s"):
        out["s"] = f["s"]
    if f.get("d"):
        out["d"] = f["d"]
    out["g"] = f["g"]
    return out


def _out_key(f: dict):
    first = f["g"][0][0] if f["g"] and f["g"][0] else [0.0, 0.0]
    return (f["z"], f["k"], f["n"] or "", first[0], first[1])


def doc_bytes(header: dict, feats: list[dict]) -> bytes:
    doc = dict(header)
    doc["n"] = len(feats)
    doc["features"] = [encode(f) for f in sorted(feats, key=_out_key)]
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fit(header: dict, feats: list[dict], budget: int) -> dict:
    """The file for these features within the budget. The least visible features go first: protected kinds (reservations
    and forests) are kept whatever their size; then the highest minimum zoom, then the smallest size. Returns the bytes,
    the kept features, the number dropped, the gzip and raw sizes, and whether the file is over budget."""
    order = sorted(feats, key=lambda f: (0 if f["protect"] else 1, f["z"], -f["size"], f["n"] or ""))
    protected = sum(1 for f in order if f["protect"])
    data = doc_bytes(header, order)
    if _gzlen(data) <= budget:
        return {"data": data, "kept": order, "dropped": 0, "over": False, "gzip": _gzlen(data), "raw": len(data)}
    lo, hi = protected, len(order)
    best = doc_bytes(header, order[:protected])
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = doc_bytes(header, order[:mid])
        if _gzlen(candidate) <= budget:
            lo, best = mid, candidate
        else:
            hi = mid - 1
    kept = order[:lo]
    gz = _gzlen(best)
    return {"data": best, "kept": kept, "dropped": len(order) - lo, "over": gz > budget, "gzip": gz,
            "raw": len(best)}


def _cell_keys(size: int):
    def keys(bbox):
        w, s, e, n = bbox
        out = []
        for lat0 in range(math.floor(s / size) * size, math.floor(n / size) * size + size, size):
            for lon0 in range(math.floor(w / size) * size, math.floor(e / size) * size + size, size):
                out.append((lat0, lon0))
        return out
    return keys


def _split(features: list[dict], keys_for, box_of) -> dict:
    """Each feature in every box it touches: whole when it lies inside the box, else clipped to it (rings by
    Sutherland-Hodgman, lines by Liang-Barsky). The label goes only to the piece whose box holds the label point."""
    out: dict = {}
    for f in features:
        bbox = _bbox(f["g"])
        for key in keys_for(bbox):
            box = box_of(key)
            w, s, e, n = box
            if bbox[0] >= w and bbox[1] >= s and bbox[2] <= e and bbox[3] <= n:
                pieces = f["g"]
            elif f["k"] in ("river", "route"):
                pieces = [seg for path in f["g"] for seg in _clip_path(path, box)]
            else:
                pieces = [ring for ring in (_clip_ring(r, box) for r in f["g"]) if len(ring) >= 3]
            tidy = _tidy(pieces, closed=f["k"] not in ("river", "route"))
            if not tidy:
                continue
            label = f["l"] if (f["l"] is not None and owns(f["l"], box)) else None
            out.setdefault(key, []).append(dict(f, g=tidy, l=label))
    return out


def peak_rank(summits: list[dict]) -> list[dict]:
    """The summits ranked by height, highest first, each with its minimum zoom: 8 for each summit at least 25 km from
    every zoom 8 summit above it; 10 for each other summit at least 10 km from every summit placed so far; 12 for the
    rest. A summit without a height is not here (the caller counts it)."""
    ranked = sorted(summits, key=lambda s: (-s["elev_m"], s["name"], s["lat"], s["lon"]))
    placed8: list[dict] = []
    for s in ranked:
        if all(haversine_km(s, a) >= SPACING_KM[8] for a in placed8):
            placed8.append(s)
            s["min_zoom"] = 8
    placed10: list[dict] = []
    for s in ranked:
        if "min_zoom" in s:
            continue
        if all(haversine_km(s, a) >= SPACING_KM[10] for a in placed8 + placed10):
            placed10.append(s)
            s["min_zoom"] = 10
    for s in ranked:
        s.setdefault("min_zoom", 12)
    return ranked


def haversine_km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = (math.radians(v) for v in (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, h)))


def build_places(rows: list[dict], pops: dict[str, int], basemap: dict[str, int]) -> dict:
    """places.json: every Montana place with its 2020 population, a rank (1 is the largest) and its minimum zoom. A place
    already on the first-paint base map keeps that map's minimum zoom."""
    items = []
    for r in rows:
        pop = pops.get(r["placefp"])
        known = r["name"] in basemap
        items.append({"kind": "place", "name": r["name"], "lat": round(r["lat"], 5), "lon": round(r["lon"], 5),
                      "population": pop, "type": PLACE_LSAD.get(r["lsad"], "place"),
                      "min_zoom": basemap[r["name"]] if known else place_zoom(pop),
                      "zoom_rule": "basemap" if known else "population"})
    items.sort(key=lambda p: (-(p["population"] if p["population"] is not None else -1), p["name"]))
    for i, p in enumerate(items):
        p["rank"] = i + 1 if p["population"] is not None else None
    return {"f": FORMAT_PLACES, "n": len(items), "population_unavailable": sum(1 for p in items if p["population"] is None),
            "places": items}


def build_peaks(ranked: list[dict], no_height: int) -> dict:
    return {"f": FORMAT_PEAKS, "n": len(ranked), "no_height": no_height,
            "rule": {"order": "height, highest first", "zoom_8_spacing_km": SPACING_KM[8],
                     "zoom_10_spacing_km": SPACING_KM[10], "rest_zoom": 12},
            "peaks": [{"kind": "peak", "name": s["name"], "lat": round(s["lat"], 5), "lon": round(s["lon"], 5),
                       "elev_m": round(s["elev_m"], 1), "elev_ft": int(round(s["elev_m"] / 0.3048)),
                       "min_zoom": s["min_zoom"]} for s in ranked]}


# ---------------------------------------------------------------- the store files

def _rel_files(store: Path, prefixes) -> list[str]:
    root = store / "hail"
    out = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(store).as_posix()
            if rel.startswith(prefixes):
                out.append(rel)
    return out


def _remove_mine(store: Path) -> None:
    for rel in _rel_files(store, REMOVE_PREFIXES):
        (store / rel).unlink()


def _read_json(path: Path, missing: str):
    if not path.is_file():
        raise BasemapError(missing)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_doc(store: Path, rel: str, data: bytes, files: dict) -> None:
    S._write_atomic(store / rel, data)
    files[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_vector(store: Path, feats: dict[str, list[dict]], cover: set[str]) -> dict:
    """Writes band A, every band B and C cell (empty cells too, so a missing file always means not built) and the band D
    shards of the covered tiles. Returns the files (for the manifest) and the measures per file."""
    files: dict[str, dict] = {}
    measures: dict[str, dict] = {"A": {}, "B": {}, "C": {}, "D": {}}
    kinds_count: dict[str, Counter] = {band: Counter() for band in BAND_ZOOMS}
    # band A: one file
    res = fit({"f": FORMAT_BAND, "band": "A", "zooms": list(BAND_ZOOMS["A"]), "tol_m": BAND_TOL_M["A"]},
              feats["A"], BAND_BUDGET["A"])
    _write_doc(store, A_FILE, res["data"], files)
    measures["A"] = {"file": A_FILE, "n": len(res["kept"]), "dropped": res["dropped"], "gzip": res["gzip"],
                     "raw": res["raw"], "over": res["over"]}
    for f in res["kept"]:
        kinds_count["A"][f["k"]] += 1
    # bands B and C: one file per cell
    for band, size, prefix in (("B", CELL_DEG["B"], B_PREFIX), ("C", CELL_DEG["C"], C_PREFIX)):
        by_cell = _split(feats[band], _cell_keys(size), lambda key, size=size: cell_box(key[0], key[1], size))
        for lat0, lon0 in cells_for_box(size):
            name = cell_name(lat0, lon0)
            header = {"f": FORMAT_BAND, "band": band, "zooms": list(BAND_ZOOMS[band]), "tol_m": BAND_TOL_M[band],
                      "cell": name, "box": list(cell_box(lat0, lon0, size))}
            res = fit(header, by_cell.get((lat0, lon0), []), BAND_BUDGET[band])
            rel = f"{prefix}{name}.json"
            _write_doc(store, rel, res["data"], files)
            measures[band][name] = {"file": rel, "n": len(res["kept"]), "dropped": res["dropped"],
                                    "gzip": res["gzip"], "raw": res["raw"], "over": res["over"]}
            for f in res["kept"]:
                kinds_count[band][f["k"]] += 1
    # band D: one shard per covered tile
    by_tile = _split(feats["D"], lambda bbox: tiles_for_bbox(bbox, cover), tile_box)
    for tile in sorted(cover):
        header = {"f": FORMAT_TILE, "tile": tile, "box": list(tile_box(tile)), "zooms": list(BAND_ZOOMS["D"])}
        res = fit(header, by_tile.get(tile, []), BAND_BUDGET["D"])
        rel = f"{W_PREFIX}{tile}.json"
        _write_doc(store, rel, res["data"], files)
        measures["D"][tile] = {"file": rel, "n": len(res["kept"]), "dropped": res["dropped"], "gzip": res["gzip"],
                               "raw": res["raw"], "over": res["over"]}
        for f in res["kept"]:
            kinds_count["D"][f["k"]] += 1
    return {"files": files, "measures": measures, "kinds": {b: dict(c) for b, c in kinds_count.items()}}


def _summarise(measures: dict) -> dict:
    out = {}
    for band in ("A", "B", "C", "D"):
        rows = [m for m in (measures[band].values() if band != "A" else [measures["A"]]) if m]
        gz = [m["gzip"] for m in rows]
        out[band] = {"files": len(rows), "gzip_total": sum(gz), "gzip_largest": max(gz) if gz else 0,
                     "raw_total": sum(m["raw"] for m in rows), "features": sum(m["n"] for m in rows),
                     "dropped": sum(m["dropped"] for m in rows), "over_budget": sum(1 for m in rows if m["over"]),
                     "budget": BAND_BUDGET[band]}
    return out


def write_index(store: Path, block: dict, files: dict, *, mirror_keys=("state", "as_of", "counts", "sources", "bytes")) -> None:
    """hail/base/index.json (this product's block under its key; the other base products keep theirs) and the mirror in
    hail/index.json's base block. The manifest is then rewritten for this product's prefixes (S._merge_manifest)."""
    base_path = store / INDEX_FILE
    doc = json.loads(base_path.read_text(encoding="utf-8")) if base_path.is_file() else {"format": "hail-base-index-v1"}
    doc[PRODUCT] = block
    data = _pretty(doc)
    S._write_atomic(base_path, data)
    files[INDEX_FILE] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    hail_path = store / "hail" / "index.json"
    index = json.loads(hail_path.read_text(encoding="utf-8"))
    mirror = {k: block.get(k) for k in mirror_keys}
    base = index.get(INDEX_KEY) if isinstance(index.get(INDEX_KEY), dict) else {}
    base[PRODUCT] = mirror
    index[INDEX_KEY] = base
    S._write_atomic(hail_path, _pretty(index))
    S._merge_manifest(store, files, prefixes=MY_PREFIXES)


def _named(kinds: list[str]) -> str:
    return S._named_list([PART_WORDS[k][0].lower() for k in kinds])


def mark_unavailable(store, reason: str) -> dict:
    """The D20 block for a store whose vector part cannot be built: state unavailable, the sentence in problem and the
    technical reason in detail. This product's files are removed; the rest of the store is kept."""
    store = Path(store)
    index = _read_json(store / "hail" / "index.json", "the store index is missing")
    block = {"format": FORMAT_INDEX, "state": "unavailable", "as_of": index.get("as_of"), "built_at": _utc_now(),
             "problem": WORDS["unavailable"], "detail": reason}
    _remove_mine(store)
    write_index(store, block, {})
    return block


# ---------------------------------------------------------------- the build

ALL_KINDS = ("reservation", "forest", "park", "water", "route", "place", "peak")


def build(store, cache, *, offline: bool = False, refresh: bool = False, box: tuple | None = None,
          deadline_at: float | None = None) -> dict:
    """Builds the vector base part into the store. A source that fails is named in the index and its kinds are left
    out (D16). Only when every kind fails is the block marked unavailable (D20)."""
    t0 = time.monotonic()
    store = Path(store)
    index = _read_json(store / "hail" / "index.json", "the store index is missing")
    tiles = list(index.get("tiles") or [])
    if not tiles:
        raise BasemapError("the store index lists no tiles")
    as_of = index.get("as_of")
    ctx = _Ctx(Path(cache), offline=offline, refresh=refresh, deadline_at=deadline_at)
    cover = coverage_tiles(tiles, box)
    inputs: dict = {}
    failed: dict[str, list[str]] = {k: [] for k in ALL_KINDS}

    def attempt(kind: str, fn):
        try:
            return fn()
        except BasemapError as exc:
            failed[kind].append(str(exc))
        except (S.StationsError, OSError, ValueError, KeyError, TypeError, IndexError, StopIteration) as exc:
            failed[kind].append(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
        return None

    def tiger(name: str, url: str, rel: str, ext: tuple[str, ...]):
        data, state, reason = fetch(ctx, name, url, rel, _check_zip(*ext))
        if data is None:
            raise BasemapError(reason or REASON_NO_ANSWER)
        return data

    # reservations (TIGER 2026 AIANNH)
    data = attempt("reservation", lambda: tiger("tiger_aiannh", AIANNH_URL, "census/tl_2026_us_aiannh.zip",
                                                (".shp", ".shx", ".dbf")))
    if data is not None:
        res = attempt("reservation", lambda: read_reservations(data))
        if res is not None:
            inputs["reservations"] = res
    # roads (TIGER 2026 primary and secondary roads)
    data = attempt("route", lambda: tiger("tiger_prisec", PRISEC_URL, "census/tl_2026_30_prisecroads.zip",
                                          (".shp", ".shx", ".dbf")))
    if data is not None:
        rt = attempt("route", lambda: read_routes(data))
        if rt is not None:
            inputs["routes"] = rt
    # places (TIGER 2026 PLACE) and their 2020 counts
    data = attempt("place", lambda: tiger("tiger_place", PLACE_URL, "census/tl_2026_30_place.zip",
                                          (".shp", ".shx", ".dbf")))
    pl_data, _, pl_reason = fetch(ctx, "census_pl2020", PL2020_URL, "census/mt2020.pl.zip",
                                  _check_zip("mtgeo2020.pl", "mt000012020.pl"))
    pops: dict[str, int] = {}
    if pl_data is not None:
        pops = attempt("place", lambda: read_population(pl_data)) or {}
    elif pl_reason:
        ctx.failures.append({"source": "census_pl2020", "reason": pl_reason})
    if data is not None:
        rows = attempt("place", lambda: read_places(data))
        if rows is not None:
            inputs["place_rows"] = rows
            inputs["pops"] = pops
    # forests (Forest Service administrative forest boundaries)
    res = attempt("forest", lambda: forest_features(ctx))
    feats, probs = res if res is not None else ([], [])
    failed["forest"].extend(probs)
    if feats:
        forests = []
        for f in feats:
            at = _attrs(f)
            parts = service_parts(f.get("geometry"))
            if at.get("FORESTNAME") in FOREST_NAMES and parts:
                forests.append({"name": at["FORESTNAME"], "parts": parts})
        inputs["forests"] = forests
    elif not failed["forest"]:
        failed["forest"].append("the forest query returned no features")
    # parks (PAD-US fee layer)
    res = attempt("park", lambda: padus_features(ctx))
    feats, probs = res if res is not None else ([], [])
    failed["park"].extend(probs)
    if feats:
        parks = []
        for f in feats:
            at = _attrs(f)
            code = str(at.get("DES_TP") or "").strip()
            parts = service_parts(f.get("geometry"))
            name = str(at.get("LOC_NM") or at.get("UNIT_NM") or "").strip()
            if parts and name and code in PARK_RULES:
                parks.append({"code": code, "name": name, "parts": parts,
                              "size": (_num(at.get("GIS_ACRES")) or 0.0) * 0.00404686})
        inputs["parks"] = parks
    elif not failed["park"]:
        failed["park"].append("the park query returned no features")
    # water: NHD small-scale lines and areas over Montana, large-scale per 1 degree cell (band D)
    bad_water: list[str] = []
    lines, probs = nhd_features(ctx, "small_lines", MT_BOX, "mt")
    bad_water.extend(probs)
    rivers_small = []
    for f in lines:
        at, parts = _attrs(f), service_parts(f.get("geometry"))
        name = str(at.get("GNIS_NAME") or "").strip()
        if parts and name:
            rivers_small.append({"name": name, "total": _num(at.get("TOTDASQKM")) or 0.0,
                                 "length": _num(at.get("LENGTHKM")) or length_km(parts), "parts": parts})
    areas, probs = nhd_features(ctx, "small_areas", MT_BOX, "mt")
    bad_water.extend(probs)
    lakes_small = []
    for f in areas:
        at, parts = _attrs(f), service_parts(f.get("geometry"))
        name = str(at.get("GNIS_NAME") or "").strip()
        if parts and name:
            area = _num(at.get("AREASQKM"))
            lakes_small.append({"name": name, "parts": parts,
                                "area": area if area is not None else area_km2(parts)})
    inputs["rivers_small"] = rivers_small
    inputs["lakes_small"] = lakes_small
    lakes_large, rivers_large = [], []
    seen: set = set()
    # band D: one request per 1 degree cell (a full run), or one request for the test box
    if box is not None:
        envelopes = [(tuple(box), "box_" + "_".join(f"{v:g}" for v in box))]
    else:
        envelopes = [(cell_box(lat0, lon0, 1), f"{lat0}_{lon0}") for lat0, lon0 in cells_for_box(1)]
    for env_box, key in envelopes:
        for source, layer_key in (("large_areas", "lakes"), ("large_lines", "rivers")):
            feats, probs = nhd_features(ctx, source, env_box, key)
            bad_water.extend(probs)
            for f in feats:
                at = _attrs(f)
                ident = (source, at.get("OBJECTID"))
                if ident in seen:
                    continue
                seen.add(ident)
                parts = service_parts(f.get("geometry"))
                name = str(at.get("GNIS_NAME") or "").strip()
                if not parts or not name:
                    continue
                if layer_key == "lakes":
                    area = _num(at.get("AREASQKM"))
                    lakes_large.append({"name": name, "parts": parts,
                                        "area": area if area is not None else area_km2(parts)})
                else:
                    rivers_large.append({"name": name, "parts": parts,
                                         "length": _num(at.get("LENGTHKM")) or length_km(parts)})
    inputs["lakes_large"] = lakes_large
    inputs["rivers_large"] = rivers_large
    if bad_water:
        failed["water"].extend(bad_water[:50])
    if not (lakes_small or rivers_small or lakes_large or rivers_large):
        if not bad_water:
            failed["water"].append("the water query returned no named features")
    # summits: GNIS names and the 3DEP height at each
    summits_src = attempt("peak", lambda: tiger("gnis", GNIS_URL, "gnis/DomesticNames_MT_Text.zip",
                                                 ("DomesticNames_MT.txt",)))
    peaks_ranked, no_height = [], 0
    if summits_src is not None:
        summits = attempt("peak", lambda: read_summits(summits_src)) or []
        heights, probs = sample_elevations(ctx, [(s["lon"], s["lat"]) for s in summits])
        if probs:
            failed["peak"].extend(probs[:20])
        withh = []
        for s, h in zip(summits, heights):
            if h is None:
                no_height += 1
            else:
                s["elev_m"] = h
                withh.append(s)
        peaks_ranked = peak_rank(withh)
        inputs["peaks"] = peaks_ranked
    # the features and the files
    with_failures = {k: v for k, v in failed.items() if v}
    all_failed = all(k in with_failures for k in ALL_KINDS)
    if all_failed:
        reason = "; ".join(f"{k}: {v[0]}" for k, v in with_failures.items())[:600]
        mark_unavailable(store, reason)
        return {"state": "unavailable", "problem": WORDS["unavailable"], "detail": reason,
                "seconds": round(time.monotonic() - t0, 1)}
    basemap_zoom = {}
    if inputs.get("place_rows") is not None:
        for p in _basemap_places():
            basemap_zoom[p["name"]] = p["min_zoom"]
    # remove this product's files before the new ones are written (a file that left the scope must not stay)
    _remove_mine(store)
    feats = build_features(inputs)
    written = write_vector(store, feats, cover)
    files = written["files"]
    if inputs.get("place_rows") is not None:
        places = build_places(inputs["place_rows"], inputs.get("pops") or {}, basemap_zoom)
        places_bytes = _pretty(places)
        S._write_atomic(store / PLACES_FILE, places_bytes)
        files[PLACES_FILE] = {"bytes": len(places_bytes), "sha256": hashlib.sha256(places_bytes).hexdigest()}
    if inputs.get("peaks") is not None:
        peaks = build_peaks(inputs["peaks"], no_height)
        peaks_bytes = _pretty(peaks)
        S._write_atomic(store / PEAKS_FILE, peaks_bytes)
        files[PEAKS_FILE] = {"bytes": len(peaks_bytes), "sha256": hashlib.sha256(peaks_bytes).hexdigest()}
    summary = _summarise(written["measures"])
    problems = []
    for kind, reasons in with_failures.items():
        problems.append(kind)
    # a test box builds band D for its own tiles only: the rest of the state is not built, so the block is partial
    state = "partial" if (problems or box is not None) else "loaded"
    parts_problem = WORDS["partial_named"].format(names=_named(problems)) if problems else None
    cover_problem = (WORDS["coverage_box"].format(box=", ".join(f"{v:g}" for v in box))
                     if box is not None else None)
    problem_text = " ".join(p for p in (parts_problem, cover_problem) if p) or None
    counts = {"bands": written["kinds"], "A_features": summary["A"]["features"],
              "tiles_in_coverage": len(cover), "cells_B": len(cells_for_box(2)), "cells_C": len(cells_for_box(1)),
              "reservations": sum(1 for f in feats["A"] if f["k"] == "reservation"),
              "forests": sum(1 for f in feats["A"] if f["k"] == "forest"),
              "places": len(inputs.get("place_rows") or []), "peaks": len(inputs.get("peaks") or []),
              "peaks_no_height": no_height, "summits_listed": len(inputs.get("peaks") or []) + no_height}
    budgets = {"A": {"limit": BAND_BUDGET["A"], "gzip": summary["A"]["gzip_total"],
                     "ok": not summary["A"]["over_budget"]},
               "B": {"limit": BAND_BUDGET["B"], "gzip_largest": summary["B"]["gzip_largest"],
                     "over_budget": summary["B"]["over_budget"], "files": summary["B"]["files"]},
               "C": {"limit": BAND_BUDGET["C"], "gzip_largest": summary["C"]["gzip_largest"],
                     "over_budget": summary["C"]["over_budget"], "files": summary["C"]["files"]},
               "D": {"limit": BAND_BUDGET["D"], "gzip_largest": summary["D"]["gzip_largest"],
                     "over_budget": summary["D"]["over_budget"], "shards": summary["D"]["files"]}}
    block = {
        "format": FORMAT_INDEX,
        "state": state,
        "as_of": as_of,
        "built_at": _utc_now(),
        "problem": None if state == "loaded" else problem_text,
        "detail": None if state == "loaded" else "; ".join(f"{k}: {v[0]}" for k, v in with_failures.items())[:600],
        "coverage": {"bands_a_to_c": "every cell touching Montana", "band_d": ("every listed tile" if box is None
                                                                             else f"the tiles touching {list(box)}"),
                     "tiles_listed": len(tiles), "tiles_in_coverage": len(cover)},
        "rule": {"zooms": {k: list(v) for k, v in BAND_ZOOMS.items()}, "tolerance_m": BAND_TOL_M,
                 "budget_gzip": BAND_BUDGET, "lake_rules_km2": LAKE_RULES, "river_rules_km2": RIVER_RULES,
                 "park_rules": {k: {"name": v[0], "min_zoom": v[1]} for k, v in PARK_RULES.items()},
                 "route_zoom": ROUTE_ZOOM, "place_rules": PLACE_RULES, "peak_spacing_km": SPACING_KM,
                 "forests": list(FOREST_NAMES)},
        "sources": ctx.source_states(),
        "counts": counts,
        "bytes": {"A": summary["A"]["gzip_total"], "B_total": summary["B"]["gzip_total"],
                  "C_total": summary["C"]["gzip_total"], "D_total": summary["D"]["gzip_total"],
                  "raw_total": sum(v["raw_total"] for v in summary.values()),
                  "gzip_total": sum(v["gzip_total"] for v in summary.values())},
        "budgets": budgets,
        "trimmed": {band: summary[band]["dropped"] for band in ("A", "B", "C", "D")},
        "failures": [{"kind": k, "reasons": v[:5]} for k, v in with_failures.items()] + ctx.failures[:20],
        "timing": {"seconds": round(time.monotonic() - t0, 1), "requests": ctx.requests,
                   "downloaded_bytes": ctx.downloaded},
    }
    write_index(store, block, files)
    return {"state": state, "problem": block["problem"], "seconds": block["timing"]["seconds"],
            "counts": counts, "bytes": block["bytes"], "budgets": budgets, "trimmed": block["trimmed"],
            "requests": ctx.requests, "downloaded_bytes": ctx.downloaded, "failures": block["failures"]}


def _basemap_places() -> list[dict]:
    path = Path(__file__).resolve().parent / "static" / "map" / "basemap.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [p for p in doc["places"] if p.get("state") == "MT"]



# ---------------------------------------------------------------- verify, the map and the command line

RESERVATION_NAMES = ("Blackfeet Indian Reservation", "Crow Reservation", "Flathead Reservation",
                     "Fort Belknap Reservation", "Fort Peck Indian Reservation", "Northern Cheyenne Indian Reservation",
                     "Rocky Boy's Reservation")
CREDIT = (
    "Source: U.S. Census Bureau, TIGER/Line 2026 (reservations and roads).",
    "Source: U.S. Census Bureau, 2020 Census, Public Law 94-171 counts (place populations).",
    "Source: U.S. Forest Service, Forest System Boundaries (national forests).",
    "Source: Protected Areas Database of the United States (PAD-US) 4.1, U.S. Geological Survey (parks).",
    "Source: U.S. Geological Survey, National Hydrography Dataset (lakes and rivers).",
    "Source: U.S. Geological Survey, Geographic Names Information System (summit names).",
    "3DEP data courtesy of the U.S. Geological Survey (summit heights).",
)


def verify(store, cache: Path | None = None) -> dict:
    """Checks the vector block, its files and their budgets, the counts (recounted from the files), the named features
    the part must hold, and that no feature carries a key beyond the map's own. cache is accepted for the same command
    shape as the other store parts; the check reads the store only."""
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    index = _read_json(store / "hail" / "index.json", "the store index is missing")
    holder = index.get(INDEX_KEY) if isinstance(index.get(INDEX_KEY), dict) else {}
    block = holder.get(PRODUCT)
    check("the vector block is in the store index", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    check("the state is loaded, partial or unavailable", block.get("state") in ("loaded", "partial", "unavailable"),
          str(block.get("state")))
    # the store index carries only the mirror; the full block (coverage, budgets, problem) is this product's own index
    full = _read_json(store / INDEX_FILE, "the vector index file is missing").get(PRODUCT)
    check("the vector index file holds the block the store index mirrors",
          isinstance(full, dict) and full.get("state") == block.get("state") and full.get("as_of") == block.get("as_of"))
    if not isinstance(full, dict):
        return {"ok": False, "checks": checks}
    block = full
    if block.get("state") == "unavailable":
        return {"ok": True, "checks": checks, "note": block.get("problem")}
    manifest = _read_json(store / "hail" / "manifest.json", "the store manifest is missing")
    listed = manifest.get("files", {})
    mine = _rel_files(store, MY_PREFIXES)
    bad = [rel for rel in mine
           if listed.get(rel) is None or listed[rel]["bytes"] != (store / rel).stat().st_size
           or listed[rel]["sha256"] != hashlib.sha256((store / rel).read_bytes()).hexdigest()]
    gone = [rel for rel in listed if rel.startswith(MY_PREFIXES) and not (store / rel).is_file()]
    check("the manifest lists each file of this product with its bytes and SHA-256", not bad and not gone,
          f"{len(bad)} mismatches, {len(gone)} listed files missing")
    counted = {band: Counter() for band in BAND_ZOOMS}
    names = {band: set() for band in BAND_ZOOMS}
    stray_keys = 0
    gz_by_band: dict[str, list[tuple[str, int]]] = {band: [] for band in BAND_ZOOMS}

    def read_band(rel: str, band: str) -> None:
        nonlocal stray_keys
        data = (store / rel).read_bytes()
        gz_by_band[band].append((rel, _gzlen(data)))
        for f in json.loads(data.decode("utf-8")).get("features", []):
            counted[band][f["k"]] += 1
            names[band].add(f["n"])
            stray_keys += len(set(f) - ALLOWED_KEYS)

    a_path = store / A_FILE
    check("band A is written", a_path.is_file())
    if a_path.is_file():
        read_band(A_FILE, "A")
    for band, prefix, size in (("B", B_PREFIX, CELL_DEG["B"]), ("C", C_PREFIX, CELL_DEG["C"])):
        expected = {f"{prefix}{cell_name(lat0, lon0)}.json" for lat0, lon0 in cells_for_box(size)}
        have = {(store / p).relative_to(store).as_posix() for p in (store / prefix).glob("*.json")} if (store / prefix).is_dir() else set()
        check(f"every band {band} cell has a file", expected <= have, f"{len(expected - have)} cells missing")
        for rel in sorted(have):
            read_band(rel, band)
    tiles_listed = set(index.get("tiles") or [])
    shards = sorted((store / W_PREFIX).glob("*.json")) if (store / W_PREFIX).is_dir() else []
    check("every covered tile has a band D shard", len(shards) == block["coverage"]["tiles_in_coverage"],
          f"{len(shards)} shards, {block['coverage']['tiles_in_coverage']} tiles in coverage")
    for path in shards:
        rel = path.relative_to(store).as_posix()
        if path.stem not in tiles_listed:
            check("every band D shard is a tile the store lists", False, rel)
            break
        read_band(rel, "D")
    check("no feature carries a key beyond the map's own", stray_keys == 0, f"{stray_keys} stray keys")
    over = [(rel, gz) for band, limit in (("A", BAND_BUDGET["A"]), ("B", BAND_BUDGET["B"]), ("C", BAND_BUDGET["C"]),
                                          ("D", BAND_BUDGET["D"])) for rel, gz in gz_by_band[band] if gz > limit]
    check("every file is within its gzip budget", not over,
          "; ".join(f"{rel} {gz} bytes" for rel, gz in over[:5]))
    recount = {band: dict(c) for band, c in counted.items()}
    check("the counts equal the counts recounted from the files", recount == block["counts"]["bands"],
          json.dumps(recount, sort_keys=True)[:300])
    check("band A holds the seven reservations", set(RESERVATION_NAMES) <= names["A"],
          f"{len(set(RESERVATION_NAMES) & names['A'])} of {RESERVATION_COUNT} named reservations")
    check("band A holds the seven national forests", set(FOREST_NAMES) <= names["A"],
          f"{len(set(FOREST_NAMES) & names['A'])} of {FOREST_COUNT} named forests")
    everywhere = names["A"] | names["B"] | names["C"] | names["D"]
    for river in RIVER_CHECK:
        check(f"the river {river} is in the files", river in everywhere)
    places_doc = _read_json(store / PLACES_FILE, "places.json is missing") if (store / PLACES_FILE).is_file() else {}
    place_names = {p["name"] for p in places_doc.get("places", [])}
    for place in PLACE_CHECK:
        check(f"{place} is in places.json", place in place_names)
    peaks_doc = _read_json(store / PEAKS_FILE, "peaks.json is missing") if (store / PEAKS_FILE).is_file() else {"peaks": []}
    mc = [p for p in peaks_doc.get("peaks", []) if p["name"] == PEAK_CHECK["name"]]
    check(f"{PEAK_CHECK['name']} is in peaks.json within {PEAK_TOLERANCE_M:.0f} m of the published height",
          bool(mc) and abs(mc[0]["elev_m"] - PEAK_CHECK["metres"]) <= PEAK_TOLERANCE_M,
          f"{mc[0]['elev_m'] if mc else 'absent'} m, published {PEAK_CHECK['source']}")
    ok = all(c["pass"] for c in checks)
    return {"ok": ok, "checks": checks, "counts": block.get("counts"), "budgets": block.get("budgets")}


def map_data_vector(block: dict | None) -> dict:
    """map.json["base"]["vector"]: the state, the as_of date, the file patterns, the zooms, the budgets, the credit lines
    and the words. A block that is absent or unavailable gives the unavailable state with its sentence (D20)."""
    if not isinstance(block, dict) or block.get("state") not in ("loaded", "partial"):
        return {"state": "unavailable", "problem": WORDS["unavailable"], "as_of": (block or {}).get("as_of")}
    return {"state": block["state"], "as_of": block.get("as_of"), "problem": block.get("problem"),
            "tiles": {"a": A_FILE, "b": B_PREFIX + "{cell}.json", "c": C_PREFIX + "{cell}.json",
                      "w": W_PREFIX + "{tile}.json", "peaks": PEAKS_FILE, "places": PLACES_FILE},
            "zooms": {k: list(v) for k, v in BAND_ZOOMS.items()}, "budgets": block.get("budgets"),
            "credit": list(CREDIT), "words": dict(WORDS), "part_words": {k: list(v) for k, v in PART_WORDS.items()}}


def describe_vector(block: dict | None) -> dict:
    """The About page's lines for this product: the sources with their state and the credit lines."""
    sources = (block or {}).get("sources", {})
    return {"credit": list(CREDIT), "state": (block or {}).get("state", "unavailable"),
            "as_of": (block or {}).get("as_of"), "sources": {k: v.get("state") for k, v in sources.items()}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.basemap2", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the vector base map (hail/base/v, w, peaks.json, places.json) and its block")
    b.add_argument("--store", required=True)
    b.add_argument("--cache", required=True)
    b.add_argument("--offline", action="store_true", help="make no request; use the cache only")
    b.add_argument("--refresh", action="store_true", help="re-read every cached response")
    b.add_argument("--box", default=None, help="W,S,E,N: band D shards and fetches only in this box (a test run)")
    b.add_argument("--deadline-at", type=float, default=None,
                   help="epoch seconds: no request starts after this time (the job's clock)")
    v = sub.add_parser("verify", help="check the vector block, its files and budgets")
    v.add_argument("--store", required=True)
    v.add_argument("--cache", default=None)
    u = sub.add_parser("unavailable", help="mark the vector block unavailable (D20) and remove its files")
    u.add_argument("--store", required=True)
    u.add_argument("--reason", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "build":
        box = tuple(float(x) for x in args.box.split(",")) if args.box else None
        deadline_at = None
        if args.deadline_at is not None:
            deadline_at = time.monotonic() + (args.deadline_at - time.time())
        result = build(Path(args.store), Path(args.cache), offline=args.offline, refresh=args.refresh, box=box,
                       deadline_at=deadline_at)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0
    if args.cmd == "verify":
        result = verify(Path(args.store), Path(args.cache) if args.cache else None)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0 if result["ok"] else 1
    block = mark_unavailable(Path(args.store), args.reason)
    print(json.dumps(block, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
