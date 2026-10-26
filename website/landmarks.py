"""Landmark points (B6 P3): schools, hospitals, airports, fire and EMS stations and local parks, one small file per B1 tile.

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
                October 2026 refresh. The HIFLD copy is read only when the USGS layer answers with no Montana rows; a failed
                USGS request makes hospitals unavailable, never a silent switch of source. The HIFLD copy is the state
                licensure list (layer 0 of HIFLD_Hospitals, STATUS OPEN); its licence is not checked (no licence text in the item
                or the layer, and the source credit names the state licensure list). The build records which one it used and why.
  airports      FAA National Airspace System Resources, the 28-day NASR airport file APT.zip for the cycle in force on the run
                date (2026-10-01 on 2026-10-25). Public-use airports only: record type APT, facility type AIRPORT, facility use
                PU and status O. Position: the airport reference point (formatted degrees, minutes and seconds). Terms: U.S.
                government data; the subscription page has no rights line for the file (not verified in the file). The HIFLD
                aviation copy is not used: it is an older cycle (effective 2025/06/12 on its Montana rows).
  fire and EMS stations USGS The National Map, Fire Stations/EMS Stations (layer 51, state MT; layer 16 is the same 461 rows). Terms as
                for the hospitals.
  parks         Two lists. PAD-US 4.1 Fee layer, local parks (Des_Tp LP, State_Nm MT): the point is the pole of inaccessibility
                of the park polygon (its distance is measured in degrees, so the point is good to about 1e-5 degree), and the
                PAD-US name is kept. TIGER/Line 2026 area landmarks with MTFCC K2180 (Park) and K2188 (incorporated place park,
                forest or recreation area), at the Census interior point, named rows only. A named TIGER park point inside a
                PAD-US park polygon, or within 150 m of its label point, is the same park: the PAD-US row stands, and the TIGER
                name is its alternate name (the sixth element of the row) while the Census list is not held. So Rose Garden (the
                PAD-US name for a Missoula park that the Census list names differently) is the name shown; that is an open point
                for the owner. Two park rows with the same name within 150 m are one park. State parks (K2184 and the PAD-US state parks)
                are areas for the basemap part (P2), not points here. PAD-US terms: the layer's copyright line is the USGS citation
                with DOI 10.5066/P96WBCHS (read 2026-10-25); the layer does not say the data is in the public domain. TIGER terms:
                held; the file's use constraints are for counsel to read (the file's own notice is quoted in SOURCES only, marked
                as not read by counsel). The TIGER points are HELD (see the held rule below): built and counted, never written,
                and the parks shown are the PAD-US parks.
  places of worship (HELD)  The FEMA copy of an IRS-based places of worship list (layer 42), rows with the point-address match
                only (LOC_NAME POINTADDRESS, state MT). Its copyright line says the points were geocoded by a commercial geocoder
                whose terms are not read, so the kind is held for counsel. It is built and counted, but its rows are never written
                into the store while it is held: the store is published as files, so a held row written there would be published.

Held rule (B6 P3-R4, D118(b)): a held source (HELD_SOURCES, with its reason) is built and counted, and its rows and alternate
names are never written to the store. The index's "held" block lists the held kinds and sources with their reasons, and its
state; no figure of a held source is in the store index, the map data or the hail index mirror (each count is null). The held
figures (the rows, the merges, the alternate names) are in the build summary only, for report.md. A held source's failure does
not change the state of a kind that is shown: the parks come from the PAD-US list while the Census list is held.
A held source publishes its reason alone as its terms (D132(b)): no licence or use sentence of a held source reaches the
index, the mirror or the map data. A held kind has one reason sentence (HELD_KIND_REASONS, D132(d)), the same in the words,
the index, the mirror, the map data and the About page.

Units and names: positions are WGS 84 degrees, rounded to five decimals (about 1 metre). Names keep the source's words.
An all capital name is title-cased by the repository's rule (stations.display_name), and then the owner's casing rules apply
(D118(c), clean_name and school_name): a backslash is a slash; a possessive 'S after an apostrophe is 's (Shodair Children's
Hospital); an ordinal suffix is lower case (9th Street Park, 12th St W Park, 2nd, 4th, 1049th), and a suffix that is not the
number's own (16St) is left alone; Mc followed by a lower-case letter capitalises that letter (McCormick); a lower-case word
after a slash is capitalised (Kiwanis Park/Hamilton Athletic Fields). In a school name only: Hs at the end is High School, Ms at
the end is Middle School, Elem is Elementary, Sch and Schl are School, and Jr and Sr before High are Junior and Senior. Every
other abbreviation stays as the source gives it (ABBREVIATION_WORDS); report.md lists each with its count as an owner item.
An airport name with no airport word gets "Airport" (MISSOULA MONTANA is Missoula Montana Airport), and the abbreviations INTL,
RGNL, MUNI, FLD, MEM and MEML are written out. USFS stays an acronym, and "at" is lower case inside a name. The placeholders
"unknown", "unnamed", "none" and "n/a" are dropped, and so is a row with no name or no position. En dashes and apostrophes in a
source name are kept as the source gives them.

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
                            kind is one short code: s school, h hospital, a airport, f fire station, p park, c church (held;
                            never written). source is one of the source keys in SOURCES. A row has five elements, or six when a
                            PAD-US park has an alternate name (P3-R3): the sixth element is the TIGER name of that same park. It
                            is written only while tiger_park is not held, so no held source puts a sixth element in the store.
                            Rows are sorted by kind, name, position and source, so the same input gives the same bytes. Each file
                            is under BUDGET_GZIP bytes when gzip compressed (checked by verify).
  hail/base/index.json      the shared base index: {"f": "hail-base-index-v1", ...} (BASE_FORMAT). This part's key is "landmarks";
                            the other parts keep their keys. A document whose "f" is another value is a failure of this module:
                            it is reported, and it is kept, never overwritten. The cache keeps the newest cycle of each source
                            (_prune_cycles, after a build that wrote the block).
  hail/index.json           the store index: this module writes its mirror under its own key in the index's "base" block (C1,
                            D128(e)), as terrain and the vector part do: {"state", "problem", "as_of", "counts", "sources", "bytes",
                            "held"}, with the held block's counts null. The other parts' mirror blocks and every other key are kept.
  hail/manifest.json        lists every p file, the base index and hail/index.json with their bytes and SHA-256 (hail.check_manifest
                            must pass).

Command line (run from the repository root):
    python -m website.landmarks build --store DIR --cache DIR [--now ISO] [--offline] [--refresh] [--deadline-at EPOCH]
                                      [--metrics FILE]
    python -m website.landmarks verify --store DIR
    python -m website.landmarks unavailable --store DIR --reason TEXT
The build needs the hail store (hail/index.json and hail/manifest.json) for the tile list. It uses only the standard library, the
repository's stations helper for names, and the requests package for downloads (the store job installs it). pyshp reads the TIGER
file (the Website job and the store job install it; a missing pyshp fails only the parks source, D20). The build prints its
summary as JSON (stdout, and --metrics): the held figures are in that summary for report.md, and the store publishes none of them.
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
BASE_FORMAT = "hail-base-index-v1"      # the shared base index's format key ("f"), as terrain and the vector part use it
INDEX_KEY = "landmarks"                   # the block in hail/base/index.json (this module's key)
BASE_INDEX = "hail/base/index.json"
HAIL_INDEX = "hail/index.json"            # the store index: this module's mirror sits under its "base" block (C1, D128(e))
HAIL_BASE_KEY = "base"                    # the store index's block for the base map parts (terrain, vector, landmarks)
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
TIGER_HELD_REASON = "the file's use constraints are for counsel to read"
TIGER_HELD_SENTENCE = "The file's use constraints are for counsel to read."   # the same reason as a sentence (WORDS["held_parks"], F6)
# C4 (D132(d)): the one held sentence for places of worship. The About page (website/templates/about.html) composes the same
# sentence from HELD_REASON (build.py passes it as b6.held_church), so the words, the index, the mirror, the map data and the
# About page read one text. tests/test_landmarks.py checks both.
CHURCH_HELD = f"Places of worship are held and not shown: {HELD_REASON}. No church is drawn or named."
RULE_TEXT = ("A point is kept with its name, kind, position and source. Positions are rounded to five decimals. An all-capital "
             "name is title-cased (stations.display_name), then the owner's casing rules apply; an airport name gets Airport when "
             "no airport word is in it. A PAD-US park keeps its name and label point; a named TIGER park point inside such a "
             "polygon, or within 150 m of its label point, is the same park: the PAD-US name stands, and the TIGER name is kept as "
             "the alternate name while the Census list is not held. Parks with the same name within 150 m are one park. The Census "
             "park points are held (built and counted, never written). Each point sits in the B1 tile that holds its position "
             "(hail.cell_for). A kind with a failed source is unavailable as a whole, and a held source is never shown.")
TIGER_PARK_CODES = ("K2180", "K2188")    # Park; incorporated place park, forest or recreation area (state parks: P2)

KIND_CODE = {"school": "s", "hospital": "h", "airport": "a", "fire": "f", "park": "p", "church": "c"}
KIND_NAME = {code: kind for kind, code in KIND_CODE.items()}
KIND_ORDER = ("school", "hospital", "airport", "fire", "park", "church")
HELD = frozenset({"church"})              # the owner has not cleared these kinds: built and counted, never written
HELD_KIND_REASONS = {"church": CHURCH_HELD}   # the one reason sentence of each held kind (C4, D132(d))
KIND_LABEL = {"school": "Schools", "hospital": "Hospitals", "airport": "Airports", "fire": "Fire and EMS stations",
              "park": "Parks", "church": "Places of worship"}
KIND_PLURAL = {"school": "schools", "hospital": "hospitals", "airport": "airports", "fire": "fire and EMS stations",
               "park": "parks", "church": "places of worship"}

NATIONAL_MAP = "https://carto.nationalmap.gov/arcgis/rest/services/structures/MapServer"   # the USGS map service (layers below)
HOSPITAL_RULE = ("The HIFLD copy is read only when the USGS layer answers with no Montana rows; a failed USGS request "
                 "makes hospitals unavailable, never a silent switch of source.")
SOURCES = {
    "nces_public": {
        "kind": "school", "label": "NCES EDGE public school locations, 2024-25", "format": "arcgis",
        "url": "https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0",
        "query": {"where": "STFIP='30'", "outFields": "NAME,LAT,LON", "returnGeometry": "false"},
        "fields": ("NAME", "LAT", "LON"), "floor": 600, "as_of": "2024-25 school year",
        "credit": "Source: National Center for Education Statistics, EDGE public school locations, 2024-25 school year.",
        "terms": "All information contained in this file is in the public domain.",
    },
    "nces_private": {
        "kind": "school", "label": "NCES EDGE private school locations, 2023-24", "format": "arcgis",
        "url": "https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PRIVATESCH_2324/MapServer/0",
        "query": {"where": "STFIP='30'", "outFields": "NAME,LAT,LON", "returnGeometry": "false"},
        "fields": ("NAME", "LAT", "LON"), "floor": 80, "as_of": "2023-24 school year",
        "credit": "Source: National Center for Education Statistics, EDGE private school locations, 2023-24 school year.",
        "terms": "All information contained in this file is in the public domain.",
    },
    "usgs_hospitals": {
        "kind": "hospital", "label": "USGS The National Map, hospitals and medical centers", "format": "arcgis",
        "url": NATIONAL_MAP + "/49",
        "query": {"where": "STATE='MT'", "outFields": "NAME", "returnGeometry": "true", "outSR": "4326"},
        "fields": ("NAME",), "floor": 40, "as_of": "October 2026 refresh",
        "credit": "Source: USGS The National Map, hospitals and medical centers, October 2026 refresh.",
        "rule": HOSPITAL_RULE,
        "terms": ("The layer has no rights line: its copyright text is empty (read 2026-10-25). The service root's copyright "
                  "line gives the refresh as \"Data Refreshed October, 2026.\" (read 2026-10-26; the build does not read it "
                  "again). The USGS terms page was not read in this build."),
    },
    "hifld_hospitals": {
        "kind": "hospital", "label": "HIFLD copy of the state licensure list (hospitals)", "format": "arcgis",
        "url": "https://services2.arcgis.com/PYn6bWCjT6bhw1z3/arcgis/rest/services/HIFLD_Hospitals/FeatureServer/0",
        "query": {"where": "STATE='MT' AND STATUS='OPEN'", "outFields": "NAME,LATITUDE,LONGITUDE,STATUS",
                  "returnGeometry": "false"},
        "fields": ("NAME", "LATITUDE", "LONGITUDE", "STATUS"), "floor": 40, "as_of": None,
        "credit": "Source: Hospital list copied from the state licensure list (copy by the Homeland Infrastructure "
                  "Foundation-Level Data), {when}.",
        "rule": HOSPITAL_RULE,
        "terms": ("No licence text in the item or the layer; the source credit names the state licensure list. Its terms are "
                  "not checked, so this source is only the fallback."),
    },
    "faa_nasr": {
        "kind": "airport", "label": "FAA NASR airport file, the cycle in force on the run date", "format": "faa",
        "url": "https://nfdc.faa.gov/webContent/28DaySub/{cycle}/APT.zip",
        "floor": 50, "as_of": "the cycle's effective date",
        "credit": "Source: Federal Aviation Administration, National Airspace System Resources airport data, {when}.",
        "terms": ("U.S. government data. The subscription page has no rights line for the file; that is not verified in the file."),
    },
    "usgs_fire": {
        "kind": "fire", "label": "USGS The National Map, fire and EMS stations", "format": "arcgis",
        "url": NATIONAL_MAP + "/51",
        "query": {"where": "STATE='MT'", "outFields": "NAME", "returnGeometry": "true", "outSR": "4326"},
        "fields": ("NAME",), "floor": 300, "as_of": "October 2026 refresh",
        "credit": "Source: USGS The National Map, fire and EMS stations, October 2026 refresh.",
        "terms": ("The layer has no rights line: its copyright text is empty (read 2026-10-25). The service root's copyright "
                  "line gives the refresh as \"Data Refreshed October, 2026.\" (read 2026-10-26; the build does not read it "
                  "again). The USGS terms page was not read in this build."),
    },
    "padus_local": {
        "kind": "park", "label": "PAD-US 4.1 local parks (Fee layer, Des_Tp LP)", "format": "padus",
        "url": "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Managers_PADUS/FeatureServer/0",
        "query": {"where": "State_Nm='MT' AND Des_Tp='LP'", "outFields": "OBJECTID,Unit_Nm,Des_Tp,State_Nm",
                  "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "6"},
        "fields": ("Unit_Nm", "Des_Tp", "State_Nm"), "floor": 300, "as_of": None,
        "credit": "Source: USGS Gap Analysis Project, Protected Areas Database of the United States (PAD-US) 4.1, local parks, "
                  "{when}.",
        "terms": ("The layer's copyright line reads: \"U.S. Geological Survey (USGS) Gap Analysis Project (GAP), 2025, Protected "
                  "Areas Database of the United States (PAD-US) 4.1: U.S. Geological Survey data release, "
                  "https://doi.org/10.5066/P96WBCHS\" (layer read 2026-10-25). The layer's description does not say the data "
                  "is in the public domain. The PAD-US terms of use were not read in this build."),
    },
    "tiger_park": {
        "kind": "park", "label": "TIGER/Line 2026 area landmarks (park codes K2180 and K2188)", "format": "tiger",
        "url": "https://www2.census.gov/geo/tiger/TIGER2026/AREALM/tl_2026_30_arealm.zip",
        "floor": 40, "as_of": "TIGER/Line 2026",
        "credit": "Source: U.S. Census Bureau, TIGER/Line 2026 area landmarks.",
        "terms": ("Internal note, not published (D132(b)): the file's own notice, quoted and not read by counsel, reads \"Not "
                  "copyrighted; free to use in a product or publication. Acknowledgement to the U.S. Census Bureau as the source "
                  "is required.\" The published terms are the held reason alone (HELD_SOURCE_REASONS)."),
    },
    "fema_worship": {
        "kind": "church", "label": "FEMA copy of the places of worship list (point-address rows)", "format": "arcgis",
        "url": ("https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
                "All_Places_Of_Worship__HiFLD_Open_/FeatureServer/42"),
        "query": {"where": "STATE='MT' AND LOC_NAME='POINTADDRESS'", "outFields": "NAME,X,Y,LOC_NAME,STATE",
                  "returnGeometry": "false"},
        "fields": ("NAME", "X", "Y", "LOC_NAME", "STATE"), "floor": 300, "as_of": None,
        "credit": "Source: FEMA copy of an IRS-based places of worship list (held; not shown).",
        "terms": ("The layer's copyright line says the points were geocoded by a commercial geocoder whose terms are not read, "
                  "so the kind is held for counsel. The layer was read on 2026-10-25."),
    },
}
ORDER = ("nces_public", "nces_private", "usgs_hospitals", "usgs_fire", "faa_nasr", "padus_local", "tiger_park",
         "fema_worship")
KIND_SOURCES = {"school": ("nces_public", "nces_private"), "airport": ("faa_nasr",), "fire": ("usgs_fire",),
                "park": ("padus_local", "tiger_park"), "church": ("fema_worship",)}
HELD_SOURCE_REASONS = {"fema_worship": CHURCH_HELD, "tiger_park": TIGER_HELD_REASON}   # the held sources, with reasons (C4)
HELD_SOURCES = frozenset(HELD_SOURCE_REASONS)   # built and counted, never written: the church list and the Census parks
MISSOULA_CHECK = (("school", "Loyola Sacred Heart High School"), ("school", "Hellgate High School"),
                  ("airport", "Missoula Montana Airport"), ("hospital", "Community Medical Center"),
                  ("hospital", "Saint Patrick Hospital"))

WORDS = {
    "what": ("A landmark is a point from a public list: a school, a hospital, a public-use airport, a fire or EMS station or a "
             "local park. The point is where the list puts it. The list does not say that the place is open or staffed today."),
    "rule": ("Each point keeps its name, its kind, its position and the list it came from. Nothing else from a list is kept."),
    "parks": ("A park point sits near the middle of the park. The park outline comes from the protected areas list."),
    "airports": "Only public-use airports that are operational are shown. Heliports are not shown.",
    "held": CHURCH_HELD,                      # the one sentence of the held church kind (C4): the words, index, map data and About
    "held_parks": ("The Census park points and their names are held for counsel and not shown. " + TIGER_HELD_SENTENCE),
    "kind_unavailable": ("Data unavailable: {plural} could not be loaded in this update; that is not the same as no {plural}. "
                         "This is not an all-clear."),
    "all_unavailable": ("Data unavailable: landmarks could not be loaded in this update; that is not the same as no landmarks. "
                        "This is not an all-clear."),
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
AIRPORT_WORDS = {"Intl": "International", "Rgnl": "Regional", "Muni": "Municipal", "Fld": "Field", "Mem": "Memorial",
                 "Meml": "Memorial"}                 # the abbreviations as the casing rule writes them (see airport_name)
AIRPORT_WORD = re.compile(r"(?<![A-Za-z])(" + "|".join(AIRPORT_WORDS) + r")(?![A-Za-z])")
AIRPORT_TERMS = re.compile(r"\b(airport|airpark|air park|airfield|field|air base|aerodrome|airstrip|landing|base)\b",
                           re.IGNORECASE)


# The owner's casing rules (B6 P3, D118(c)), applied after the shared title case in clean_name.
POSSESSIVE_S = re.compile(r"(['\u2019])S(?![A-Za-z])")              # CHILDREN'S is Children's (the apostrophe stays as given)
ORDINAL_SUFFIX = re.compile(r"(?<![A-Za-z0-9])([0-9]+)(St|Nd|Rd|Th)(?![A-Za-z])")
MC_SURNAME = re.compile(r"(?<![A-Za-z])Mc([a-z])")                  # Mccormick is McCormick; Mcleod is McLeod
SLASH_WORD = re.compile(r"/([a-z])")                                # PARK/hamilton is PARK/Hamilton
# The abbreviations that stay as the source gives them. The owner decides on each; report.md lists them with their counts.
ABBREVIATION_WORDS = ("Ac", "Attn", "Ave", "Blnd", "Bn", "Chs", "Co", "Cos", "Csd", "Cthlc", "Ctr", "Dist", "El", "Facil",
                      "Hs", "Inc", "Jc", "Jfk", "Jr", "Mc", "Mt", "Ms", "Pakr", "Prk", "Sc", "Sda", "Sr", "St", "Uprr", "Us", "Va")
ABBREVIATION = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(ABBREVIATION_WORDS, key=len, reverse=True)) + r")(?![A-Za-z])")


def _ordinal_suffix(match) -> str:
    """A number with its suffix in lower case when the suffix is the number's own (9th, 12th, 2nd, 4th, 1049th). A suffix
    that is not the number's own (16St) is left as it is."""
    number, suffix = match.group(1), match.group(2)
    if int(number) % 100 in (11, 12, 13):
        own = "Th"
    else:
        own = {1: "St", 2: "Nd", 3: "Rd"}.get(int(number) % 10, "Th")
    return number + (suffix.lower() if suffix == own else suffix)


def clean_name(raw):
    """The display name of a source name: its words, one space between them, all-capital words title-cased (the
    repository's rule), USFS kept as an acronym, and "at" in lower case inside a name. Then the owner's casing rules: a
    backslash is a slash, a possessive 's, ordinal suffixes in lower case, Mc with a capital, a lower-case word after a
    slash is capitalised. None for an empty name or a placeholder."""
    if not isinstance(raw, str):
        return None
    text = " ".join(raw.split())
    if not text or PLACEHOLDER.search(text):
        return None
    text = S.display_name(text.replace("\\", "/"))
    text = re.sub(r"(?<![A-Za-z])Usfs(?![A-Za-z])", "USFS", text)      # an acronym the casing rule would title-case
    text = POSSESSIVE_S.sub(lambda match: match.group(1) + "s", text)
    text = ORDINAL_SUFFIX.sub(_ordinal_suffix, text)
    text = MC_SURNAME.sub(lambda match: "Mc" + match.group(1).upper(), text)
    text = SLASH_WORD.sub(lambda match: "/" + match.group(1).upper(), text)
    return re.sub(r"(?<=\S) At (?=\S)", " at ", text)                   # a small word: lower case inside a name


def school_name(raw):
    """clean_name for a school name, with the school words written out (B6 P3, D118(c)): Hs at the end is High School, Ms at
    the end is Middle School, Elem is Elementary, Sch and Schl are School, and Jr and Sr before High are Junior and Senior.
    None for an empty name or a placeholder."""
    text = clean_name(raw)
    if text is None:
        return None
    text = re.sub(r"(?<![A-Za-z])Hs$", "High School", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])Ms$", "Middle School", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])Elem(?![A-Za-z])", "Elementary", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])Schl?(?![A-Za-z])", "School", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])Jr(?=\s+High(?![A-Za-z]))", "Junior", text, flags=re.IGNORECASE)
    return re.sub(r"(?<![A-Za-z])Sr(?=\s+High(?![A-Za-z]))", "Senior", text, flags=re.IGNORECASE)


def abbreviation_counts(names) -> dict:
    """The abbreviations that stay as the source gives them, with how many of the names hold each (report.md's owner list).
    Give it the names written to the store only, never the names of a held source."""
    counts: Counter = Counter()
    for name in names:
        for match in ABBREVIATION.finditer(name):
            counts[match.group(1)] += 1
    return dict(sorted(counts.items()))


def airport_name(raw):
    """clean_name for an airport, with the abbreviations written out (FLD Field, MEM and MEML Memorial, INTL, RGNL, MUNI)
    and "Airport" added when no airport word is in the name. The abbreviations are written out after the casing rule, so
    one joined to a slash ("FLD/GLASGOW") is still found."""
    text = clean_name(raw)
    if text is None:
        return None
    text = AIRPORT_WORD.sub(lambda match: AIRPORT_WORDS[match.group(1)], text)
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
    method. rings: the outer ring first, then the holes (and any further parts). Returns (lon, lat) or None. The distance
    is measured in degrees of longitude and latitude alike (not in metres, and not corrected for latitude), so the search
    stops at a precision in degrees: 1e-5 degree is about a metre of latitude, and a degree of longitude is shorter here."""
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


def _alternate(name: str, rows) -> str | None:
    """The alternate name of a PAD-US park: the TIGER name of a point that is the same park and differs from the PAD-US
    name (the first in casefold order), or None (B6 P3-R3)."""
    names = {row[1] for row in rows if row[1].casefold() != name.casefold()}
    return min(names, key=lambda text: (text.casefold(), text)) if names else None


def merge_parks(polys, tiger_rows):
    """(pad_rows, tiger_kept, tiger_merged). Every PAD-US local park is a row with its own name and label point (the name its
    polygon carries on the basemap). A named TIGER park point inside a PAD-US park polygon, or within MERGE_M of its label point,
    is the same park: it is not kept as a row, and its name becomes the alternate name of that PAD-US row (a sixth element,
    when it differs). The other TIGER park points are kept."""
    covering: dict = {}
    tiger_kept = []
    merged = 0
    for row in tiger_rows:
        hits = [i for i, poly in enumerate(polys)
                if point_in_rings(row[2], row[3], poly["rings"])
                or _metres(row[2], row[3], poly["pos"][0], poly["pos"][1]) <= MERGE_M]
        if hits:
            merged += 1
            for i in hits:
                covering.setdefault(i, []).append(row)
        else:
            tiger_kept.append(row)
    pad_rows = []
    for i, poly in enumerate(polys):
        row = ("park", poly["name"], poly["pos"][0], poly["pos"][1], "padus_local")
        alt = _alternate(poly["name"], covering.get(i, []))
        pad_rows.append(row + (alt,) if alt else row)
    return pad_rows, tiger_kept, merged


def dedupe_parks(rows):
    """(rows, dropped): a park with the same name as an earlier park within MERGE_M is the same park (a park that the source
    lists in two pieces, such as Scotty Park in two polygons). The alternate name of a dropped piece stays with the park."""
    kept: list = []
    dropped = 0
    for row in rows:
        same = next((i for i, k in enumerate(kept)
                     if k[1].casefold() == row[1].casefold() and _metres(k[2], k[3], row[2], row[3]) <= MERGE_M), None)
        if same is None:
            kept.append(row)
            continue
        dropped += 1
        if len(row) == 6 and len(kept[same]) == 5:
            kept[same] = kept[same] + (row[5],)
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
    """(rows, drops, counts) for the lines of the APT file. Only APT records are read; the columns are the 2026 APT layout's
    (1-based: record type 1-3, state 49-50, facility type 15-27, use 186-187, name 134-183, latitude 524-538, longitude
    551-565, status 841-842). No other column is read, the ownership code (184-185) included."""
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
    """(rows, drops, count) from the TIGER zip bytes. Raises SourceFailure when the zip, its parts, its fields or its records
    are not as expected, and when the reader cannot read them (a failure of this source only, D16)."""
    shapefile = _shapefile_reader()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = {Path(n).suffix.lower(): n for n in z.namelist() if not n.endswith("/")}
            if not all(ext in members for ext in (".shp", ".dbf", ".shx")):
                raise SourceFailure("the park file does not hold the shapefile parts the reader expects")
            reader = shapefile.Reader(shp=io.BytesIO(z.read(members[".shp"])),
                                      dbf=io.BytesIO(z.read(members[".dbf"])),
                                      shx=io.BytesIO(z.read(members[".shx"])))
            fields = {f[0] for f in reader.fields[1:]}
            missing = [name for name in TIGER_NEEDED if name not in fields]
            if missing:
                raise SourceFailure("the park file does not have the fields the reader expects (" + ", ".join(missing) + ")")
            records = []
            for rec in reader.iterRecords():
                d = rec.as_dict()
                records.append({k: d.get(k) for k in TIGER_NEEDED})
    except SourceFailure:
        raise
    except zipfile.BadZipFile:
        raise SourceFailure("the park file is not a zip file") from None
    except Exception as exc:                      # a damaged part that the reader cannot read: this source fails, not the build
        raise SourceFailure(f"the park file could not be read ({type(exc).__name__})") from None
    rows, drops = parse_tiger_records(records)
    return rows, drops, len(records)


# ---------------------------------------------------------------- the download (cache by name, every request logged)

def _parsed(parse, raw: bytes):
    """parse(raw), or the bytes themselves when there is no parse (a SourceFailure from parse passes through)."""
    return raw if parse is None else parse(raw)


def _usable(parse, raw: bytes) -> bool:
    """True when parse accepts the bytes (or there is no parse)."""
    try:
        _parsed(parse, raw)
    except SourceFailure:
        return False
    return True


def _remove(path: Path) -> None:
    """Removes a cached file and its description, so that the next request writes both again."""
    for item in (path, path.with_name(path.name + ".meta.json")):
        try:
            item.unlink()
        except FileNotFoundError:
            pass


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
        self.read_bytes = 0                    # the size of every file read, cached or downloaded
        self.used: set = set()                 # the cache files this run read (_prune_cycles keeps their cycle)
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

    def file(self, path: Path, url: str, what: str, parse=None):
        """The parsed content of one cached file (its bytes when parse is None). A cached file that parses is read without a
        request, and --offline makes no request at all. Otherwise the file is requested, and it is written to the cache only
        after parse accepts its bytes. parse raises SourceFailure for a body of the wrong kind (an error page, or an error JSON
        sent with HTTP 200), so such a body is never cached. A cached file that does not parse is removed and requested again.
        Under --refresh a failed request, or a body that does not parse, keeps the cached copy when that copy parses."""
        cached = path.read_bytes() if path.is_file() else None
        if cached is not None and (self.offline or not self.refresh):
            try:
                value = _parsed(parse, cached)
            except SourceFailure as exc:
                self._ledger("GET", url, None, len(cached), "invalid", str(exc))
                _remove(path)
                if self.offline:
                    raise SourceFailure(f"{what} in the cache is not usable ({exc}) and this run makes no request") from None
                cached = None
            else:
                self.hits += 1
                self.read_bytes += len(cached)
                self.used.add(path)
                self._ledger("GET", url, None, len(cached), "hit")
                return value
        if self.offline:
            raise SourceFailure(f"{what} is not in the cache and this run makes no request")
        try:
            data = self.get(url, what)
            try:
                value = _parsed(parse, data)
            except SourceFailure as exc:
                self._ledger("GET", url, 200, len(data), "rejected", str(exc))
                raise
        except SourceFailure as exc:
            if cached is None or not _usable(parse, cached):
                raise
            self._ledger("GET", url, None, len(cached), "fallback", str(exc))
            self.hits += 1
            self.read_bytes += len(cached)
            self.used.add(path)
            return _parsed(parse, cached)
        _atomic(path, data)
        _atomic(path.with_name(path.name + ".meta.json"),
                _compact({"url": url, "bytes": len(data), "sha256": _sha256(data), "fetched": _utc_now()}))
        self.read_bytes += len(data)
        self.used.add(path)
        return value

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


def _meta_key(spec: dict) -> str:
    """A short key for the layer description: its URL, so a new layer version has its own description file (P3-R7)."""
    return _sha256(spec["url"].encode("utf-8"))[:12]


def _fields(meta: dict) -> list:
    """The field descriptions of a layer, as dicts (anything else in the list is left out)."""
    fields = meta.get("fields") if isinstance(meta.get("fields"), list) else []
    return [f for f in fields if isinstance(f, dict)]


def _layer_meta(raw: bytes, spec: dict, label: str) -> dict:
    """The layer description, checked before it is cached: a JSON object with the fields the reader needs and a record count
    it can read. Any other answer is a SourceFailure, and nothing is written."""
    meta = _json_doc(raw, f"layer description of {label}")
    names = {str(f.get("name", "")).lower() for f in _fields(meta)}
    missing = [f for f in spec["fields"] if f.lower() not in names]
    if missing:
        raise SourceFailure(f"{label} does not have the fields the reader expects ({', '.join(missing)})")
    try:
        if int(meta.get("maxRecordCount") or 1000) < 1:
            raise ValueError("no records to a page")
    except (TypeError, ValueError):
        raise SourceFailure(f"{label} has no usable record count") from None
    return meta


def _page_doc(raw: bytes, label: str) -> dict:
    """One page of a layer query, checked before it is cached: a JSON object with a features list."""
    doc = _json_doc(raw, f"{label} list")
    if not isinstance(doc.get("features"), list):
        raise SourceFailure(f"the {label} list has no features list")
    return doc


def load_arcgis(fetch: Fetch, key: str, spec: dict) -> dict:
    """Every feature of a map service layer query, page by page, after the layer's own description is read and checked. Returns
    {"features", "meta", "as_of", "fetched", "pages", "copyright"}."""
    label = spec["label"]
    meta_path = fetch.cache / key / f"meta-{_meta_key(spec)}.json"      # the layer description, by its URL
    meta = fetch.file(meta_path, spec["url"] + "?f=pjson", f"the layer description of {label}",
                      parse=lambda raw: _layer_meta(raw, spec, label))
    oid_field = next((f.get("name") for f in _fields(meta) if f.get("type") == "esriFieldTypeOID"), None)
    oid = oid_field or meta.get("objectIdField") or "OBJECTID"
    per_page = min(2000, int(meta.get("maxRecordCount") or 1000))
    base = fetch.cache / key / _query_key(spec)
    features: list = []
    offset = 0
    pages = 0
    for page in range(MAX_PAGES):
        params = dict(spec.get("query", {}), f="json", orderByFields=oid, resultOffset=offset,
                      resultRecordCount=per_page)
        url = spec["url"] + "/query?" + urlencode(params)
        doc = fetch.file(base / f"p{page:03d}.json", url, f"the {label} list, page {page}",
                         parse=lambda raw: _page_doc(raw, label))
        pages += 1
        found = doc["features"]
        features.extend(found)
        if doc.get("exceededTransferLimit") and found:
            offset += len(found)
            continue
        break
    else:
        raise SourceFailure(f"the {label} list needs more than {MAX_PAGES} pages, which the reader does not read")
    as_of = spec.get("as_of")
    edited = meta.get("editingInfo", {}).get("lastEditDate") if isinstance(meta.get("editingInfo"), dict) else None
    if edited is None:
        edited = meta.get("lastEditDate")
    try:
        if isinstance(edited, (int, float)) and edited > 0:
            as_of = datetime.fromtimestamp(edited / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        pass                                  # an edit date the platform cannot show: the layer's own as-of stands
    return {"features": features, "meta": meta, "as_of": as_of, "fetched": fetch.fetched_at(base / "p000.json"),
            "pages": pages, "copyright": meta.get("copyrightText") or None}


def _faa_zip(raw: bytes) -> dict:
    """The airport rows of an APT zip, checked before it is cached: a zip with an APT.txt member and Montana airport records
    (SourceFailure otherwise, so a wrong file is never kept)."""
    if raw[:2] != b"PK":
        raise SourceFailure("the airport file is not a zip file")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            member = next((n for n in z.namelist() if n.upper().endswith("APT.TXT")), None)
            if member is None:
                raise SourceFailure("the airport file has no APT.txt member")
            with z.open(member) as fh:
                rows, drops, counts = parse_faa_lines(io.TextIOWrapper(fh, encoding="latin-1", newline=""))
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError):
        raise SourceFailure("the airport file is not a readable zip file") from None
    if counts.get("montana records", 0) == 0:
        raise SourceFailure("the airport file has no Montana airport records")
    return {"rows": rows, "drops": drops, "read": counts.get("apt records", 0), "counts": dict(counts)}


def _prune_cycles(folder: Path, used) -> int:
    """Removes the entries of one source's cache folder that the finished build did not read: the older cycles (an older
    airport cycle, an older Census vintage, an older layer version with its pages) and their descriptions. The cycle in force
    is kept. Called only for a source that loaded, after the block is written, so a failed build keeps the cache as it was
    (B6 P3-R7). Returns the number of entries removed."""
    if not folder.is_dir():
        return 0
    keep = set()
    for path in used:
        try:
            keep.add(path.relative_to(folder).parts[0])
        except ValueError:
            continue
    removed = 0
    for entry in sorted(folder.iterdir()):
        owner = entry.name[: -len(".meta.json")] if entry.name.endswith(".meta.json") else entry.name
        if entry.name in keep or owner in keep:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed += 1
    return removed


def load_faa(fetch: Fetch, cycle: date) -> dict:
    spec = SOURCES["faa_nasr"]
    url = spec["url"].format(cycle=cycle.isoformat())
    path = fetch.cache / "faa_nasr" / f"APT_{cycle.isoformat()}.zip"
    parsed = fetch.file(path, url, f"the airport file for the {cycle.isoformat()} cycle", parse=_faa_zip)
    return {"rows": parsed["rows"], "drops": parsed["drops"], "read": parsed["read"], "as_of": cycle.isoformat(),
            "fetched": fetch.fetched_at(path), "counts": parsed["counts"]}


def _shapefile_reader():
    """The pyshp module, or SourceFailure when it is not installed (D20: a missing reader fails the park points only)."""
    try:
        import shapefile                          # pyshp: the store job installs it
    except ImportError:
        raise SourceFailure("the shapefile reader is not installed, so the park points cannot be read") from None
    return shapefile


def load_tiger(fetch: Fetch) -> dict:
    spec = SOURCES["tiger_park"]
    _shapefile_reader()                           # a missing reader fails the parks before anything is downloaded
    path = fetch.cache / "tiger_park" / spec["url"].rsplit("/", 1)[-1]     # named by its vintage (the URL's file name)
    rows, drops, count = fetch.file(path, spec["url"], "the park landmark file", parse=read_tiger)
    return {"rows": rows, "drops": drops, "read": count, "as_of": spec["as_of"], "fetched": fetch.fetched_at(path)}


def load_padus(fetch: Fetch) -> dict:
    loaded = load_arcgis(fetch, "padus_local", SOURCES["padus_local"])
    polys, drops = polygons_from(loaded["features"])
    return {"polys": polys, "drops": drops, "read": len(loaded["features"]), "as_of": loaded["as_of"],
            "fetched": loaded["fetched"], "pages": loaded["pages"]}


def _points_source(fetch: Fetch, key: str, *, name_key: str, coords, keep=None, name_fn=clean_name) -> dict:
    spec = SOURCES[key]
    loaded = load_arcgis(fetch, key, spec)
    rows, drops = points_from(loaded["features"], spec["kind"], key, name_key=name_key, coords=coords, keep=keep,
                              name_fn=name_fn)
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
        return _points_source(fetch, key, name_key="NAME", coords=attr_coords("LON", "LAT"), name_fn=school_name)
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


def _credit(key: str, res) -> str:
    """The credit line of a source, with its own date worked in: the layer's last edit, the FAA cycle, or Data unavailable
    when the date is missing (a missing date is never left blank or made up). The About line carries the date once."""
    as_of = res.get("as_of") if isinstance(res, dict) else None
    if key == "faa_nasr":
        when = f"cycle effective {as_of}" if as_of else "Data unavailable"
    elif key in ("padus_local", "hifld_hospitals", "fema_worship"):
        when = f"layer last edited {as_of}" if as_of else "Data unavailable"
    else:
        when = ""
    return SOURCES[key]["credit"].format(when=when)


def _sources_block(results: dict) -> dict:
    """The sources entry of the index. A held source carries its state, its reason and its dates only: no count, size or
    request figure of a held file is published (B6 D118(b)), and its terms are its reason alone, so no licence text of the
    file is published (D132(b)). A shown source carries the figures of its read."""
    block = {}
    for key in ORDER + ("hifld_hospitals",):
        spec = SOURCES[key]
        res = results.get(key)
        terms = HELD_SOURCE_REASONS[key] if key in HELD_SOURCES else spec["terms"]
        entry = {"kind": spec["kind"], "label": spec["label"], "credit": _credit(key, res), "terms": terms}
        if key in HELD_SOURCES:
            entry.update({"state": "held", "reason": HELD_SOURCE_REASONS[key],
                          "as_of": res.get("as_of") if isinstance(res, dict) else None,
                          "fetched": res.get("fetched") if isinstance(res, dict) else None})
        elif res is None:
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
               "i": [[row[2], row[3], KIND_CODE[row[0]], row[1], row[4]] + list(row[5:6]) for row in items]}
        files[tile] = _compact(doc)
    return files


def _merge_manifest(store: Path, entries: dict) -> None:
    """Replaces this module's manifest entries (the p folder, the base index and hail/index.json) and keeps every other entry."""
    path = store / "hail" / "manifest.json"
    manifest = _read_json(path)
    files = {k: v for k, v in manifest.get("files", {}).items() if not k.startswith(P_PREFIX) and k != BASE_INDEX}
    files.update(entries)
    manifest["files"] = {k: files[k] for k in sorted(files)}
    _atomic(path, _pretty(manifest))


def _base_document(path: Path) -> dict:
    """The shared base index as a dict, checked before anything is written. A missing file starts a new document with the
    shared format key. A document with another format key, or one that is not JSON, is reported as a failure of this module
    and is kept as it is, never discarded (B6 P3-R8)."""
    if not path.is_file():
        return {"f": BASE_FORMAT}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise LandmarkError("hail/base/index.json is not JSON, so the landmarks are not written and the file is kept") from None
    found = doc.get("f") if isinstance(doc, dict) else None
    if found != BASE_FORMAT:
        shown = repr(found) if found is not None else "no format key"
        raise LandmarkError(f"hail/base/index.json is not a {BASE_FORMAT} document (its format key: {shown}), so the landmarks "
                            "are not written and the file is kept")
    return doc


def _mirror(block: dict) -> dict:
    """The block as hail/index.json carries it under its "base" block (C1, D128(e)), the same shape as the terrain and vector
    mirrors: the state and its problem, the as-of date, the counts, the sources, the bytes of the shard files, and the held
    block (its counts are null). The site reads the rest of the block from hail/base/index.json."""
    counts = block.get("counts") if isinstance(block.get("counts"), dict) else {}
    return {"state": block.get("state"), "problem": block.get("problem"), "as_of": block.get("as_of"), "counts": counts,
            "sources": block.get("sources", {}), "bytes": counts.get("bytes"), "held": block.get("held", {})}


def _hail_index_doc(store: Path):
    """hail/index.json as a dict, or None when it is missing or is not a JSON object (verify reports that)."""
    try:
        doc = _read_json(store / HAIL_INDEX)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _hail_index_with_mirror(store: Path, block: dict) -> bytes:
    """hail/index.json with this module's mirror under its own key of the "base" block. Every other key of the index, and every
    other part's mirror block, is kept as it is. Built before any file changes: an index that is not a JSON object is a failure
    of this module, and the file is kept."""
    try:
        index = _read_json(store / HAIL_INDEX)
    except (OSError, UnicodeDecodeError, ValueError):
        raise LandmarkError("hail/index.json is not JSON, so the landmarks mirror is not written and the file is kept") from None
    if not isinstance(index, dict):
        raise LandmarkError("hail/index.json is not a JSON object, so the landmarks mirror is not written and the file is kept")
    base = index.get(HAIL_BASE_KEY) if isinstance(index.get(HAIL_BASE_KEY), dict) else {}
    base[INDEX_KEY] = _mirror(block)
    index[HAIL_BASE_KEY] = base
    return _pretty(index)


def _write_block(store: Path, block: dict, shards: dict) -> dict:
    """Writes the p folder (rebuilt whole), the base index with this block, this block's mirror in hail/index.json, and the
    manifest entries of all three. The base index is read first, and the hail index is built first: a document of another
    format stops the write before any file is changed. Only this module's keys change in either document."""
    base_path = store / BASE_INDEX
    base = _base_document(base_path)
    hail_bytes = _hail_index_with_mirror(store, block)
    p_dir = store / "hail" / "base" / "p"
    if p_dir.exists():
        shutil.rmtree(p_dir)                    # the shard folder is this module's alone
    entries = {}
    for tile, data in shards.items():
        rel = f"{P_PREFIX}{tile}.json"
        _atomic(store / rel, data)
        entries[rel] = {"bytes": len(data), "sha256": _sha256(data)}
    base[INDEX_KEY] = block
    data = _pretty(base)
    _atomic(base_path, data)
    entries[BASE_INDEX] = {"bytes": len(data), "sha256": _sha256(data)}
    _atomic(store / HAIL_INDEX, hail_bytes)
    entries[HAIL_INDEX] = {"bytes": len(hail_bytes), "sha256": _sha256(hail_bytes)}
    _merge_manifest(store, entries)
    return entries


def _problem_for(kinds: dict) -> str | None:
    """The D20 words for the kinds that are unavailable (held kinds never count: they are not shown either way)."""
    lost = [kind for kind in KIND_ORDER if kind not in HELD and kinds.get(kind, {}).get("state") == "unavailable"]
    return " ".join(WORDS["kind_unavailable"].format(plural=KIND_PLURAL[kind]) for kind in lost) or None


def _held(source: str) -> bool:
    """True while a source is held: its rows are built and counted, and never written. Read at call time, so a test can
    release a source for its own run."""
    return source in HELD_SOURCES


def _shown_sources(kind: str) -> tuple:
    """The sources of a kind whose rows can be shown: a held source is left out (the kind's points come from the others)."""
    return tuple(key for key in KIND_SOURCES[kind] if not _held(key))


def build(store, cache, *, now: datetime | None = None, offline: bool = False, refresh: bool = False,
          deadline_at: float | None = None, session=None, floors: dict | None = None, sleep=time.sleep) -> dict:
    """Read every source (the cache first, then the network unless offline), build the points of each kind, write the shards
    and the block, then keep only the cycle in force in each source's cache folder, and return the summary. A source failure
    marks its kinds unavailable and the build goes on. Raises LandmarkError only when the hail store is not there, or when the
    shared base index is of another format (the file is then kept). A count is null when its input did not load (never zero).
    A held source publishes no figure in the block; its figures are in the summary (report.md)."""
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
        before = (fetch.requests, fetch.downloaded, fetch.hits, fetch.read_bytes)
        try:
            res = _load_checked(fetch, key, floor_map, today, allow_zero=allow_zero)
            res["ok"] = True
        except SourceFailure as exc:
            res = {"ok": False, "reason": str(exc), "rows": [], "drops": {}}
            _say(f"landmarks: {SOURCES[key]['label']} could not be used ({exc})")
        except Exception as exc:                  # any other error in one source is that source's failure (D16)
            reason = f"the source could not be read ({type(exc).__name__})"
            res = {"ok": False, "reason": reason, "rows": [], "drops": {}}
            _say(f"landmarks: {SOURCES[key]['label']} could not be used ({reason})")
        res["requests"] = fetch.requests - before[0]
        res["downloaded"] = fetch.downloaded - before[1]
        res["hits"] = fetch.hits - before[2]
        res["bytes"] = fetch.read_bytes - before[3]        # the size of the files this source read (cached or downloaded)
        results[key] = res
        return res

    for key in ORDER:
        run(key, allow_zero=(key == "usgs_hospitals"))

    # Hospitals: the USGS layer where it carries Montana hospitals (named rows). The HIFLD copy is read only when that layer
    # answers with no Montana hospital at all; a layer that cannot be read is a failure, not a reason to change source.
    tnm = results["usgs_hospitals"]
    hifld_tried = False
    if tnm["ok"] and tnm["rows"]:
        hospital_key = "usgs_hospitals"
        hospital_why = f"{WORDS['hospital_usgs']} The layer carries {len(tnm['rows'])} named Montana hospitals."
    elif tnm["ok"]:
        hifld_tried = True
        hifld = run("hifld_hospitals")
        hospital_key = "hifld_hospitals" if hifld["ok"] else None
        hospital_why = (WORDS["hospital_hifld"] if hifld["ok"] else
                        "the USGS layer named no Montana hospital, and the HIFLD copy could not be used")
    else:
        hospital_key = None
        hospital_why = f"the USGS layer could not be used ({tnm.get('reason')})"

    # Parks: the PAD-US local parks, and the named TIGER park points that no PAD-US park holds (merge_parks); parks with the
    # same name within MERGE_M are one park (dedupe_parks). While the Census park list is held, its points and its alternate
    # names are built and counted, never shown: the parks shown are the PAD-US parks alone. The park counts stay null unless
    # the PAD-US list loaded.
    park_rows: list = []
    park_same = None
    tiger_merged = tiger_kept_rows = alt_names = None
    if results["padus_local"]["ok"]:
        polys = results["padus_local"]["polys"]
        if results["tiger_park"]["ok"]:
            pad_rows, tiger_kept, tiger_merged = merge_parks(polys, results["tiger_park"]["rows"])
            tiger_kept_rows = len(tiger_kept)
            alt_names = sum(1 for row in pad_rows if len(row) == 6)
        else:
            pad_rows = [("park", poly["name"], poly["pos"][0], poly["pos"][1], "padus_local") for poly in polys]
            tiger_kept = []
        if _held("tiger_park"):
            park_rows, park_same = dedupe_parks([row[:5] for row in pad_rows])
        else:
            park_rows, park_same = dedupe_parks(pad_rows + tiger_kept)

    kinds: dict = {}
    rows_by_kind: dict = {}
    for kind in KIND_ORDER:
        if kind == "hospital":
            used = [hospital_key] if hospital_key else ["usgs_hospitals"] + (["hifld_hospitals"] if hifld_tried else [])
            failed = [] if hospital_key else (["hifld_hospitals"] if tnm["ok"] else ["usgs_hospitals"])
        elif kind in HELD:
            used = list(KIND_SOURCES[kind])
            failed = []
        else:
            used = list(_shown_sources(kind))
            failed = [key for key in used if not results[key]["ok"]]
        entry = {"code": KIND_CODE[kind], "held": kind in HELD, "sources": used}
        if kind in HELD:
            # built and counted for the summary, never shown: the index carries the state and the reason, and no count
            if all(results[key]["ok"] for key in used):
                rows, _ = dedupe([row for key in used for row in results[key]["rows"]])
                rows_by_kind[kind] = rows
            kinds[kind] = dict(entry, state="held", count=None, reason=HELD_KIND_REASONS[kind])
            continue
        if failed:
            reason = hospital_why if kind == "hospital" else results[failed[0]].get("reason", REASON_NO_ANSWER)
            kinds[kind] = dict(entry, state="unavailable", count=None, reason=reason, failed=failed)
            continue
        if kind == "hospital":
            rows = list(results[hospital_key]["rows"])
        elif kind == "park":
            rows = list(park_rows)
        else:
            rows = [row for key in used for row in results[key]["rows"]]
        rows, dup = dedupe(rows)
        rows_by_kind[kind] = rows
        kinds[kind] = dict(entry, state="loaded", count=len(rows), dropped=dup)

    shown_kinds = [kind for kind in KIND_ORDER if kind not in HELD]
    if not any(kinds[kind]["state"] == "loaded" for kind in shown_kinds):
        state = "unavailable"
    elif any(kinds[kind]["state"] == "unavailable" for kind in shown_kinds):
        state = "partial"
    else:
        state = "loaded"
    unavailable = state == "unavailable"
    shown = [row for kind in KIND_ORDER if kind in rows_by_kind and kind not in HELD for row in rows_by_kind[kind]]
    files = shard_files(shown)
    gz = {tile: _gzip_size(data) for tile, data in files.items()}
    largest = max(gz, key=gz.get) if gz else None
    outside = sum(1 for row in shown if _tile_of(row[2], row[3]) not in tiles)
    if unavailable:
        files = {}
        gz = {}
        largest = None
    problem = {"loaded": None, "partial": _problem_for(kinds), "unavailable": WORDS["all_unavailable"]}[state]
    failures = [{"source": key, "reason": res.get("reason")} for key, res in results.items() if not res.get("ok")]
    # the run's request, download and cache counts: the sources that are shown (a held source's fetches are not published)
    shown_results = [res for key, res in results.items() if not _held(key)]
    run_requests = sum(res["requests"] for res in shown_results)
    run_downloaded = sum(res["downloaded"] for res in shown_results)
    run_hits = sum(res["hits"] for res in shown_results)
    held_report = {"church_rows": len(rows_by_kind["church"]) if "church" in rows_by_kind else None,
                   "tiger_rows": tiger_kept_rows, "tiger_merged": tiger_merged, "alt_names": alt_names}
    block = {
        "format": FORMAT,
        "state": state,
        "problem": problem,
        "built_at": _utc_now(),
        "as_of": today.isoformat(),
        "faa_cycle": faa_cycle(today).isoformat(),
        "kinds": kinds,
        "held": {"kinds": {kind: {"held": True, "state": "held", "count": None, "reason": HELD_KIND_REASONS[kind]}
                           for kind in sorted(HELD)},
                 "sources": {key: {"held": True, "state": "held", "count": None, "reason": HELD_SOURCE_REASONS[key]}
                             for key in sorted(HELD_SOURCES)}},
        "sources": _sources_block(results),
        "hospital_source": {"used": hospital_key, "why": hospital_why},
        "tiles": None if unavailable else sorted(files),
        "counts": {
            "points": None if unavailable else len(shown),
            "kinds": {kind: kinds[kind]["count"] for kind in shown_kinds},
            "sources_written": None if unavailable else dict(Counter(row[4] for row in shown)),
            "tiger_merged": None if _held("tiger_park") else tiger_merged,
            "park_same_name": park_same,
            "held_rows": None,
            "shards": None if unavailable else len(files),
            "bytes": None if unavailable else sum(len(v) for v in files.values()),
            "gzip_bytes": None if unavailable else sum(gz.values()),
            "largest_gzip": gz[largest] if largest else None,
            "largest_tile": largest,
            "outside_tiles": None if unavailable else outside,
            "requests": run_requests,
            "downloaded_bytes": run_downloaded,
            "cache_hits": run_hits,
        },
        "budget": {"shard_gzip_bytes": BUDGET_GZIP, "largest_gzip_bytes": gz[largest] if largest else None,
                   "within": None if unavailable else all(v < BUDGET_GZIP for v in gz.values())},
        "rule": RULE_TEXT,
        "failures": failures[:50],
        "words": {"what": WORDS["what"], "rule": WORDS["rule"]},
    }
    _write_block(store, block, files)
    pruned = sum(_prune_cycles(fetch.cache / key, fetch.used) for key, res in results.items() if res.get("ok"))
    counts = block["counts"]
    return {"state": state, "points": counts["points"], "kinds": counts["kinds"], "held": held_report,
            "abbreviations": abbreviation_counts([row[1] for row in shown]),
            "shards": counts["shards"], "bytes": counts["bytes"], "gzip_bytes": counts["gzip_bytes"],
            "largest_gzip": counts["largest_gzip"], "largest_tile": largest, "budget_within": block["budget"]["within"],
            "failures": failures, "requests": run_requests, "downloaded_bytes": run_downloaded, "cache_hits": run_hits,
            "cache_entries_pruned": pruned, "seconds": round(time.monotonic() - t0, 2),
            "outside_tiles": counts["outside_tiles"]}


def mark_unavailable(store, reason: str) -> dict:
    """The landmarks are unavailable with the plain reason (D20). The shard folder is removed; the base index keeps the other
    parts' keys, and hail/index.json keeps the other parts' mirror blocks (this module's mirror says unavailable, with null
    counts); the manifest keeps every other entry. The counts are null: nothing is shown, so there is no count to give."""
    root = Path(store)
    _check_store(root)
    text = " ".join(str(reason).split())
    if not text:
        raise LandmarkError("give the reason the landmarks are unavailable (--reason TEXT)")
    block = {"format": FORMAT, "state": "unavailable", "problem": WORDS["all_unavailable"], "detail": text,
             "built_at": _utc_now(), "kinds": {}, "held": {}, "sources": {}, "counts": {"points": None, "shards": None}}
    _write_block(root, block, {})
    return {"state": "unavailable", "reason": text}


# ---------------------------------------------------------------- the words for the page (About, the chips, the unavailable text)

def describe_landmarks(index: dict | None = None) -> dict:
    """The About text of the landmark points: what a point is, one credit line for each shown source that loaded with rows
    (the credit carries the source's own date), the held kind and the rule. A held kind's source is never listed as shown.
    index is the parsed hail/base/index.json (or None)."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    loaded = []
    if isinstance(block, dict):
        sources = block.get("sources") if isinstance(block.get("sources"), dict) else {}
        for key in ORDER + ("hifld_hospitals",):
            entry = sources.get(key) if isinstance(sources.get(key), dict) else {}
            if key in HELD_SOURCES or entry.get("state") != "loaded" or not entry.get("kept"):
                continue
            if entry.get("credit"):
                loaded.append(entry["credit"])
    return {"title": "Landmarks", "what": WORDS["what"], "rule": WORDS["rule"], "parks": WORDS["parks"],
            "airports": WORDS["airports"], "held": WORDS["held"], "held_parks": WORDS["held_parks"],
            "sources": loaded}


def map_data_landmarks(index: dict) -> dict:
    """The map.json block for the landmark chips: the state, the shard names and the words. The chips read a shard per
    tile and never a request for a tile that is not listed. The counts list the kinds that loaded only: an unavailable kind
    has no count, which is not the same as zero."""
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
    counts = dict(block.get("counts") or {})
    counts["kinds"] = {kind: n for kind, n in (counts.get("kinds") or {}).items() if n is not None}
    return {"state": block.get("state"), "problem": block.get("problem"), "shard": "hail/base/p/{name}.json",
            "tiles": sorted(block.get("tiles") or []), "kinds": kinds, "templates": templates,
            "counts": counts, "sources": describe_landmarks(index)["sources"]}


# ---------------------------------------------------------------- verify

def _norm_name(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", str(text).lower()).split()
    return " ".join("saint" if w == "st" else w for w in words if w != "the")


def _held_figures_null(block: dict) -> bool:
    """True when every figure of a held kind or source in the block is null (B6 D118(b))."""
    for kind in HELD:
        entry = block.get("kinds", {}).get(kind, {})
        if entry.get("count") is not None or entry.get("dropped") is not None:
            return False
    counts = block.get("counts", {})
    if counts.get("held_rows") is not None:
        return False
    if _held("tiger_park") and counts.get("tiger_merged") is not None:
        return False
    for key in HELD_SOURCES:
        entry = block.get("sources", {}).get(key, {})
        if any(entry.get(field) is not None for field in ("read", "kept", "drops", "requests", "bytes")):
            return False
    return True


def _held_terms_are_reasons(sources) -> bool:
    """True when each held source publishes its reason alone as its terms (B6 D132(b)): no licence or use sentence of the file
    is in the published entry. sources is a sources block (the index's, or the mirror's)."""
    if not isinstance(sources, dict):
        return False
    for key in HELD_SOURCES:
        entry = sources.get(key)
        if not (isinstance(entry, dict) and entry.get("terms") == HELD_SOURCE_REASONS[key]):
            return False
    return True


def _held_block_named(block: dict) -> bool:
    """True when the held block names each held kind and source with state "held", its reason and a null count (B6 D120(c)).
    The kind's reason is its one sentence (C4, D132(d)). The figures themselves are checked by _held_figures_null."""
    held = block.get("held") if isinstance(block.get("held"), dict) else {}
    kinds = held.get("kinds") if isinstance(held.get("kinds"), dict) else {}
    sources = held.get("sources") if isinstance(held.get("sources"), dict) else {}
    for kind in HELD:
        entry = kinds.get(kind)
        if not (isinstance(entry, dict) and entry.get("state") == "held" and entry.get("reason") == HELD_KIND_REASONS[kind]
                and "count" in entry and entry["count"] is None):
            return False
    for key in HELD_SOURCES:
        entry = sources.get(key)
        if not (isinstance(entry, dict) and entry.get("state") == "held" and entry.get("reason") == HELD_SOURCE_REASONS[key]
                and "count" in entry and entry["count"] is None):
            return False
    return True


def verify(store) -> dict:
    """Checks the landmark files in a store: the shared base index format, the hail index mirror (this key, and the held block
    in it), the manifest entries, each file's shape (five or six elements a row), the counts recounted from the files, the held
    kinds and sources (none written, no held figure in the block, the held block names each one with its state, reason and a
    null count, and each held source's terms are its reason alone), the alternate names (written only while the Census list is
    released), the shard budget, the tile list, the Missoula check and hail.check_manifest."""
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    base_path = store / BASE_INDEX
    base = _read_json(base_path) if base_path.is_file() else {}
    block = base.get(INDEX_KEY) if isinstance(base, dict) else None
    check("the base index is the shared format (hail-base-index-v1)", isinstance(base, dict) and base.get("f") == BASE_FORMAT)
    check("landmarks block present in hail/base/index.json", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    check("state is loaded, partial or unavailable", block.get("state") in ("loaded", "partial", "unavailable"))
    hail_doc = _hail_index_doc(store)
    hail_base = hail_doc.get(HAIL_BASE_KEY) if isinstance(hail_doc, dict) else None
    mirror = hail_base.get(INDEX_KEY) if isinstance(hail_base, dict) else None
    check("hail/index.json base mirror matches the block (this key only; the other parts' keys are kept)",
          isinstance(mirror, dict) and mirror == _mirror(block))
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
    alt_bad = []
    out_of_tiles = 0
    missoula: set = set()
    tiger_held = _held("tiger_park")
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
            if not (isinstance(row, list) and len(row) in (5, 6) and isinstance(row[0], (int, float))
                    and isinstance(row[1], (int, float)) and row[2] in KIND_NAME and isinstance(row[3], str)
                    and row[3] and row[4] in SOURCES):
                shape_bad.append(path.name)
                continue
            kind = KIND_NAME[row[2]]
            if kind in HELD or _held(row[4]):
                held_seen.append(path.name)
            if len(row) == 6 and (tiger_held or row[4] != "padus_local" or not isinstance(row[5], str) or not row[5]):
                alt_bad.append(path.name)
            if _position(row[0], row[1]) is None:
                coords_bad += 1
            recount[kind] += 1
            by_source[row[4]] += 1
            if MISSOULA_BOX[0] <= row[0] <= MISSOULA_BOX[2] and MISSOULA_BOX[1] <= row[1] <= MISSOULA_BOX[3]:
                missoula.add((kind, _norm_name(row[3])))
    check("every shard parses to the expected shape", not shape_bad, f"{len(shape_bad)} problems")
    check("every position is inside the Montana box", coords_bad == 0, f"{coords_bad} outside")
    check("no held kind or source is written to a shard", not held_seen, f"{len(held_seen)} rows of a held kind or source")
    check("an alternate name is written only on a PAD-US park while the Census list is released", not alt_bad,
          f"{len(alt_bad)} rows")
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
    check("every figure of a held kind or source in the block is null", _held_figures_null(block))
    check("the held block names each held kind and source with its state, its reason and a null count", _held_block_named(block))
    check("held sources publish their reason alone as terms, in the index and the mirror (no licence text)",
          _held_terms_are_reasons(block.get("sources")) and _held_terms_are_reasons((mirror or {}).get("sources")))
    check("the hail index mirror names each held kind and source with a null count, and holds no held figure",
          isinstance(mirror, dict) and _held_block_named({"held": mirror.get("held")}) and _held_figures_null(mirror))
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
