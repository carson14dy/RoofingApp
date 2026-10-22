"""Stations (B5 Source 3): GHCN-Daily station readings, the station rule (D5), the season figures and hail/sd/.

A station reading is a value at a station, not at an address. Every row built from this module names its station,
its distance and its kind word ("Station reading", or "Data unavailable" with the reason). Nothing here states
damage, an all-clear, insurance or eligibility (AGENTS.md rule 5). A missing day is never zero.

Source (the research record snow-stations.json and its refuter; quoted terms are verbatim on the live pages):
  Station list    https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt
  Inventory       https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt
  Daily files     https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/<ID>.dly (the NCEI copy; the S3 by-station copies are
                  stale for SNOTEL and WBAN files: their last date is 2025-02-06 in S3, 2026-10-16 at NCEI)
  Units           SNOW and SNWD in millimetres (integers); PRCP in tenths of a millimetre; TMAX and TMIN in tenths of a
                  degree Celsius. The -9999 value is missing. A non-blank quality flag fails the value: it is excluded
                  from every sum, record and coverage count. The measurement flag T is a trace: 0 in sums, counted, and
                  said so.
  Timing          real-time values are replaced by archive values about 45 to 60 days after month end (NCEI product
                  page, quoted: "Generally, real-time replacement of updated data streams are replaced by archive-ready
                  data sources 45 to 60 days after the end of a month."). The newest report date is shown with each value.
  Cadence         daily: every NCEI .dly file was Last-Modified 2026-10-18 in the research check (481 of 481 Montana files).
  Licence         NOAA and federal records (COOP, SNOTEL, WBAN): public domain in the United States under NCEI-PD-10-2-02
                  section 4(a) ("These data are in the public domain in the United States."). CoCoRaHS records (source
                  flag N; file prefix US1) are released under CC BY 3.0 ("Unless otherwise noted, all CoCoRaHS content and
                  data are released under a Creative Commons Attribution 3.0 License") and ask users to acknowledge the source.
                  The NODD copy is CC0 (AWS registry: "NOAA data disseminated through NODD is made available under the
                  Creative Commons 1.0 Universal Public Domain Dedication (CC0-1.0) license"). Cite NCEI-PD-10-2-02.
  Missing list    a station file lists only the days it has values for; a day with no value is missing, never zero.

The station rule (D5 and D18, one constant per number; the owner's decisions O8 and the supervisor's rulings are
provisional):
  * candidates: Montana stations within RADIUS_MILES (40, great-circle) of the location;
  * currency, per element (D18): a candidate is current for an element when that element has an unflagged value within
    FRESH_DAYS (30) of the store's as_of date. The rule runs per element and location: a station current for TMAX is
    not thereby current for SNOW, and its SNOW share cannot pass on its TMAX report;
  * per element: coverage is the share of the COVER_DAYS (2,192) days from 2020-01-01 to 2025-12-31 with an unflagged
    value of that element, and it must be at least COVER_MIN (0.80);
  * the two nearest candidates that pass are chosen. Fewer than two: those that pass are shown and the words say so.
    None: "No station within 40 miles has enough reports for {element} from 2020 to 2025."
  * a candidate whose file did not load is never read, and it is never counted as a non-pass: its row says unavailable
    (pass null) and the walk goes past it. A failed candidate met before the walk stops makes the result incomplete
    (incomplete true, named in unread). With no station passing the state is "unavailable" (D16: "Data unavailable");
    with some passing, the passing stations are shown under the B2 partial pattern (DECISIONS.md, B2 "States"), and the
    words say the two nearest that pass are not known. The stations block keeps each failed candidate that the rule can
    reach as an entry with unread true and null counts, so the rule the sheet and the town pages run (point_rule) is the
    build's rule. failed_station_ids lists every failed file, uncapped (failures is capped at 50)
  * a season or calendar value shows only when at least SEASON_MIN (0.95) of its days have an unflagged value, and
    every station's share is shown.
Thresholds (D1, shared with the roof lines of B5): a 90 F day is a TMAX of at least 322 tenths of a degree C (32.2 C; GHCN
stores 90 F that way); a freeze-thaw day has TMAX above 0 C and TMIN below 0 C; a low below 32 F is TMIN below 0 C; a
1-inch snow depth is SNWD of at least 25 mm (GHCN stores 1 inch as 25 mm; the 25.4 mm test drops every 1-inch day).

Count keys: a count key is written for an element whenever the element has an unflagged value in
the period. ge1 (SNWD), ge90 (TMAX), lt32 (TMIN) and trace (PRCP, SNOW) are zero when no day reached the threshold or had a
trace, and absent only when the element has no unflagged value in the period. The pair counts FT and DL are written when a
day has both of their elements unflagged, with n = 0 when no day met the rule; the record is absent when no day had both.
Every reader goes through count_of() or pair_of(), which return None for an absent key: a missing count is never read as
zero, and an absent key is named as missing, never raised.

Refresh and time (B5 jobs, D26): --scope daily refreshes the station list and the inventory and the files of the chosen
stations of the last build (the index's chosen_station_ids). A cached file whose Last-Modified equals the date it was
downloaded with is not fetched: one HEAD request decides it, and the file is counted as unchanged. --scope monthly
refreshes every file the walk and the regression set read, the list and the inventory included, with no skip. Without a
scope, refresh is "none" (the cache is read; a missing or unusable file is requested), "all" (as monthly, with no scope
name) or a set of station ids (only those .dly files are re-read; the list and the inventory stay cached). The rule's
station ids of the last build are kept in the index as rule_station_ids; `python -m website.stations rule-ids` prints
them. A request that would start after the job's deadline is not made, and its file is "the source did not answer".
Every download is streamed: READ_TIMEOUT bounds each read and BODY_CAP_S bounds the whole file.

Store (format hail-stn-v1, see the module's functions):
  hail/sd/<id>.json   per station: its name and position, the newest unflagged date per element, the 2020-2025 coverage
                      counts, and per period (July to June seasons, calendar years, water years 2022 to 2026, all
                      October to September) per element: rep (days with a value), ok (days unflagged), trace days,
                      sum (SNOW mm, PRCP tenths of mm), max and max_d and max_n (the highest value, its first day and the
                      days at it: TMAX, SNWD) or min and min_d and min_n (TMIN), ge90 (TMAX of 322 or more), lt32 (TMIN
                      below 0), ge1 (SNWD of 25 mm or more); and the day pairs FT (freeze-thaw) and DL (snow of 1 inch or
                      more with a low below 32 F). Dates are yyyymmdd integers. A partial period ends at as_of.
  hail/index.json     gains "stations": the rule constants, the sources and their bytes, the counts, the per-station
                      summary used by the rule (lat, lon, name, network, current, newest, coverage), the 17 towns' rule
                      results and the gate points' results, the failures and the malformed-line count.
  hail/manifest.json  lists every hail/sd/ file with its bytes and SHA-256.
The site build reads these files; it never fetches them. Part B chooses stations for a tile centre with choose() over
the index's stations block, so every tile centre's choice is the same rule the build ran.

Tile centres (B2's definition, the midpoint of the tile's bounds): lat 54.950 - 0.1 * row_tile, lon -129.950 + 0.1 * col_tile.

Tile lists (D36; hail/tl/<tile>.json, format hail-stn-tiles-v1, one per B1 tile): for each element, the passing stations
within 40 miles of the tile centre, nearest first, up to six (TILE_LIST_CAP), with each station's name, position, miles from
the centre, unflagged days and share; and the candidates whose file did not load, named with their reason (D32). A passing
station is the rule's own test (current for the element, at least 80 percent). The sheet picks the two nearest to the cell
from the list; verify records the two picks at the Billings and Benchland points for every element (tile_picks).

Command line (run from the repository root):
    python -m website.stations build --store DIR --cache DIR [--procs 4] [--offline] [--scope daily|monthly]
                                    [--refresh all|none] [--refresh-ids FILE] [--deadline-at EPOCH]
    python -m website.stations rule-ids --store DIR        the daily refresh set (the last build's rule ids)
    python -m website.stations verify --store DIR          check the station figures and gates (exit 1 on a failure)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

FORMAT = "hail-stn-v1"               # hail/sd/<id>.json
INDEX_KEY = "stations"               # the block in hail/index.json
SD_PREFIX = "hail/sd/"
CORE = ("PRCP", "SNOW", "SNWD", "TMAX", "TMIN")
RADIUS_MILES = 40.0                  # D5: the candidate radius (great-circle)
FRESH_DAYS = 30                      # D5: a candidate reported an unflagged value within this many days of as_of
COVER_MIN = 0.80                     # D5: the share of COVER_DAYS with an unflagged value, per element
SEASON_MIN = 0.95                    # D5: the share of a season's or year's days that a value needs
COVER_FIRST = date(2020, 1, 1)
COVER_LAST = date(2025, 12, 31)
COVER_DAYS = 2192
HOT_TENTHS = 322                     # D1: TMAX of 90 F (32.2 C); GHCN stores 90 F as 322 tenths of a degree C
DEEP_MM = 25                         # D1: SNWD of 1 inch (25 mm, as GHCN stores it)
EARTH_KM = 6371.0088                 # the B2 joins' radius (the same haversine)
MILE_KM = 1.609344
PULL_FIRST = 6                       # the first candidates of every location are fetched in one batch (the walk
                                     # then asks for more only where the rule needs them)
PACE_S = 0.15                        # at least this long between two NCEI requests
READ_TIMEOUT = (20, 60)              # seconds to connect, and to wait for each read (the job clock and the read limits)
BODY_CAP_S = 300.0                   # a file's body must arrive within this many seconds in all
REASON_NO_ANSWER = "the source did not answer"     # a request the job's deadline stopped (the joins' wording, B2)
COUNT_KEYS = (("SNWD", "ge1"), ("TMAX", "ge90"), ("TMIN", "lt32"), ("PRCP", "trace"), ("SNOW", "trace"))
STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
INVENTORY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt"
DLY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{id}.dly"
USER_AGENT = "montana-hail-watch-stations/1 (+https://github.com/carson14dy/RoofingApp)"
NETWORK = {"C": "COOP", "1": "CoCoRaHS", "R": "RAWS", "S": "SNOTEL", "W": "WBAN"}
WATER_YEARS = (2022, 2023, 2024, 2025, 2026)     # October to September; the five the NOHRSC grid covers (snowgrid)
SEASON_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)   # July to June: 2026 is the partial 2026-27 season
CALENDAR_YEARS = (2020, 2021, 2022, 2023, 2024, 2025, 2026)   # 2026 is partial
MAX_ROWS_PER_FILE = 2_000_000
TOWNS_FILE = Path(__file__).resolve().parent / "towns.json"
TILE_LIST_PREFIX = "hail/tl/"        # D36: the tile lists, one file per B1 tile (the folder is rebuilt whole)
TILE_LIST_FORMAT = "hail-stn-tiles-v1"
TILE_LIST_CAP = 6                    # D36: up to six passing stations per element and tile
# Gate points (B5 gates B5-3 and B5-9): Billings as the research measured it, and Benchland's point (47.08, 110.02). The
# Benchland cell centre (47.075, 110.015) is checked too, in verify, and reported.
GATE_POINTS = {"billings": (45.7836, -108.5047), "benchland": (47.08, -110.02)}


class StationsError(Exception):
    """A file or figure that cannot be used. The message is plain words, lower case, with no full stop."""


WORDS = {
    "station_reading": ("Station reading: {inches} in of snow in the {season} season at {station}, {miles} miles away "
                        "({k} of {d} days with a value)."),
    "station_reading_plain": ("Station reading: {value} at {station}, {miles} miles away, for the {season} season "
                              "({k} of {d} days with a value)."),
    "caveat": ("This reading is from {station}, about {miles} miles from this address. A station reading is at the "
               "station, not at this address. Snow and rain can differ a lot over a short distance."),
    "missing": ("{station} reported {element} on {k} of {d} days from {start} to {end}. Days it did not report are left "
                "blank, not counted as zero."),
    "data_unavailable": ("Data unavailable for {season}: {station} has {k} of {d} days with a {element} value, so this "
                         "season is not shown; a missing value is not zero."),
    "snotel": "{station} is a SNOTEL site. It reports snow depth, not snowfall.",
    "stale": "The newest report from {station} is dated {date}.",
    "none": "No station within 40 miles has enough reports for {element} from 2020 to 2025.",
    "two_of_one": ("Only one station within 40 miles has enough reports for {element} from 2020 to 2025: {station}. "
                   "Stations that did not pass are not shown."),
    # D28 (B5 part B1): the D20 sentence the unavailable block carries in "problem"; the technical reason is "detail"
    "unavailable": ("Station readings could not be loaded in this update; that is not the same as no station reading. "
                    "This is not an all-clear."),
    # B5 job-1 and job-3: a candidate station whose file did not load. "element" is the plain element name.
    "unread_element": ("Data unavailable for {element}: {stations} did not load{reason}, so it is not known whether a "
                       "station within 40 miles has enough reports. This is not an all-clear."),
    "unread_partial": ("Data unavailable for some stations: {stations} did not load{reason}, so the two nearest stations "
                       "that pass are not known for {element}. This is not an all-clear."),
    # D32 (B5 part B1): a partial block names each candidate whose file did not load (the D20 sentence); the other failed
    # files are counted, never read as no station
    "unread_named": ("Station readings could not be loaded in this update for {names}; that is not the same as no station "
                     "reading. This is not an all-clear."),
    "unread_block": ("Some station files could not be loaded in this update ({count} {file}); that is not the same as "
                     "no station reading. This is not an all-clear."),
    "trace": "Traces are counted as zero in sums; a trace is a real but tiny amount of precipitation or snow.",
    "share": "{station}: {k} of {d} days ({share} percent) with a {element} value.",
    "lead": ("Station readings come from the two nearest stations within 40 miles that have enough reports; a reading "
             "is at the station, not at this address."),
    "not_shown": "{element} for {season} is not shown at {station}: {k} of {d} days have a value, under 95 percent.",
}


# ---------------------------------------------------------------- dates, periods and grid helpers

def season_of(day: date) -> str | None:
    """The July to June season label ("2021-22") of a day, or None outside SEASON_YEARS."""
    y = day.year if day.month >= 7 else day.year - 1
    if y not in SEASON_YEARS:
        return None
    return f"{y}-{str(y + 1)[2:]}"


def water_year_of(day: date) -> int | None:
    """The water year (October to September, named for the year it ends) of a day, or None outside WATER_YEARS."""
    y = day.year + 1 if day.month >= 10 else day.year
    return y if y in WATER_YEARS else None


def period_bounds(kind: str, label: str, as_of: date) -> tuple[date, date, bool]:
    """(start, end, partial) of a period; end is capped at as_of, and partial says so."""
    if kind == "season":
        y = int(label[:4])
        start, end = date(y, 7, 1), date(y + 1, 6, 30)
    elif kind == "calendar":
        y = int(label)
        start, end = date(y, 1, 1), date(y, 12, 31)
    elif kind == "water":
        y = int(label)
        start, end = date(y - 1, 10, 1), date(y, 9, 30)
    else:
        raise StationsError(f"unknown period kind {kind}")
    partial = end > as_of
    return start, min(end, as_of), partial


def tile_centre(tile_row: int, tile_col: int) -> tuple[float, float]:
    """The centre of a B1 tile (the midpoint of its bounds, as B2 uses it): lat 54.950 - 0.1 row, lon -129.950 + 0.1 col.

    Computed in whole thousandths of a degree and divided once."""
    return (54950 - 100 * int(tile_row)) / 1000, (-129950 + 100 * int(tile_col)) / 1000


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h))) / MILE_KM


def fmt_in(hundredths: int) -> str:
    """Inches from hundredths of an inch, one decimal, rounded half away from zero: 5029 gives "50.3"."""
    v = int(hundredths)
    sign = "-" if v < 0 else ""
    v = abs(v)
    tenths = (v + 5) // 10
    return f"{sign}{tenths // 10}.{tenths % 10}"


def mm_to_hundredths_in(mm: int) -> int:
    """Whole millimetres to hundredths of an inch, rounded half up, in integers (25.4 mm to the inch)."""
    return (int(mm) * 1000 + 127) // 254


def tenths_c_to_tenths_f(c10: int) -> int:
    """Tenths of a degree C to tenths of a degree F, rounded half up, in integers: F = C x 9/5 + 32, so
    (9 C10 + 1600) / 5 in tenths. 322 (32.2 C) gives 900 (90.0 F)."""
    return (9 * int(c10) + 1600 + 2) // 5


def date_int(day: date | None) -> int | None:
    return None if day is None else int(day.strftime("%Y%m%d"))


def count_of(period: dict | None, element: str, key: str) -> int | None:
    """One count of one element in a period record (ok, ge90, ge1, lt32, trace, sum, ...). None when the element record
    or the key is absent (no unflagged value in the period). Never zero for an absent key (the count-key rule)."""
    rec = (period or {}).get(element)
    if not isinstance(rec, dict):
        return None
    value = rec.get(key)
    return value if isinstance(value, int) else None


def pair_of(period: dict | None, pair: str) -> int | None:
    """The day-pair count n of FT (freeze-thaw) or DL (one inch of snow and a low below 32 F) in a period record: None
    when no day in the period had both of the pair's elements unflagged (the record is absent)."""
    rec = (period or {}).get(pair)
    if not isinstance(rec, dict):
        return None
    value = rec.get("n")
    return value if isinstance(value, int) else None


SCOPES = ("daily", "monthly")


def scope_settings(scope, index: dict, refresh="none") -> tuple[bool, frozenset, bool, bool]:
    """(every_file, station_ids, skip_unchanged, list_refresh) for a job scope (D26), or for refresh when no scope is
    given. daily: the station list and the inventory are refreshed, and the files of the index's chosen stations are
    refreshed with the Last-Modified skip. monthly: every file the walk and the regression set read, the list and the
    inventory included, with no skip."""
    if scope is None:
        every, ids = refresh_set(refresh)
        return every, ids, False, every
    if scope == "monthly":
        return True, frozenset(), False, True
    if scope == "daily":
        block = index.get(INDEX_KEY) or {}
        chosen = frozenset(str(s) for s in (block.get("chosen_station_ids") or []) if str(s).strip())
        return False, chosen, True, True
    raise StationsError("the scope is not daily or monthly")


def refresh_set(refresh) -> tuple[bool, frozenset]:
    """(every_file, station_ids) for a refresh setting: "none" (or False), "all" (or True: every file, the monthly job),
    or a collection of station ids (only those daily files are re-read; the list and inventory stay cached)."""
    if refresh is None or refresh is False or refresh == "none":
        return False, frozenset()
    if refresh is True or refresh == "all":
        return True, frozenset()
    if isinstance(refresh, (set, frozenset, list, tuple)):
        return False, frozenset(str(x).strip() for x in refresh if str(x).strip())
    raise StationsError("the refresh setting is not none, all or a list of station ids")


# ---------------------------------------------------------------- fixed-width readers

def parse_station_list(text: str) -> dict[str, dict]:
    """ghcnd-stations.txt: the Montana stations as {id: {id, lat, lon, elev, name, net}} (fixed columns of the
    GHCN readme: ID 1-11, LATITUDE 13-20, LONGITUDE 22-30, ELEVATION 32-37, STATE 39-40, NAME 42-71)."""
    out = {}
    for raw in text.splitlines():
        line = raw.ljust(85)
        if line[38:40] != "MT":
            continue
        sid = line[0:11]
        out[sid] = {"id": sid, "lat": float(line[12:20]), "lon": float(line[21:30]),
                    "elev": float(line[31:37]), "name": line[41:71].strip(),
                    "net": NETWORK.get(sid[2:3], "other")}
    return out


def parse_inventory(text: str, ids) -> dict[str, dict]:
    """ghcnd-inventory.txt: {id: {element: (first_year, last_year)}} for the core elements of the stations in ids.
    FIRSTYEAR and LASTYEAR are the first and last years of unflagged data (a range, not a coverage count)."""
    keep = set(ids)
    out: dict[str, dict] = {}
    for raw in text.splitlines():
        if len(raw) < 45:
            continue
        sid = raw[0:11]
        if sid not in keep:
            continue
        element = raw[31:35]
        if element not in CORE:
            continue
        out.setdefault(sid, {})[element] = (int(raw[36:40]), int(raw[41:45]))
    return out


def parse_dly(data: bytes | str, station_id: str, first_year: int = 2020) -> dict:
    """One GHCN-Daily .dly file read for the core elements from first_year on.

    Returns {"obs": {element: [(ordinal, value, ok, trace), ...]}, "malformed": n}. Each row is one day with a value
    (any flag): ok is True when the quality flag is blank, trace when the measurement flag is T. Missing values (-9999)
    and days that do not exist in their month are not returned. A line of another station, or one that cannot be read,
    counts as malformed; it never fails the file."""
    text = data.decode("latin-1") if isinstance(data, bytes) else data
    obs: dict[str, list] = {e: [] for e in CORE}
    malformed = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        line = raw.ljust(269)
        if line[0:11] != station_id:
            malformed += 1
            continue
        try:
            year = int(line[11:15])
            month = int(line[15:17])
        except ValueError:
            malformed += 1
            continue
        element = line[17:21]
        if element not in CORE or year < first_year:
            continue
        for d in range(1, 32):
            pos = 21 + 8 * (d - 1)
            try:
                value = int(line[pos:pos + 5])
            except ValueError:
                malformed += 1
                continue
            if value == -9999:
                continue
            try:
                day = date(year, month, d)
            except ValueError:
                malformed += 1
                continue
            mflag = line[pos + 5]
            qflag = line[pos + 6]
            obs[element].append((day.toordinal(), value, qflag == " ", mflag == "T"))
    return {"obs": obs, "malformed": malformed}


# ---------------------------------------------------------------- the per-station summary

def summarize(meta: dict, parsed: dict, as_of: date) -> dict:
    """The hail/sd file content for one station (without the file's own envelope): its position, the newest unflagged
    date per element, the 2020-2025 coverage counts, the current flag per element (D18), and every period's figures
    (see the module doc).

    Pure: the same parsed file and as_of always give the same dict (the byte-identical gate depends on it)."""
    obs = parsed["obs"]
    present = [e for e in CORE if obs.get(e)]
    newest: dict[str, int | None] = {e: None for e in CORE}
    cover: dict[str, int] = {}
    periods: dict[str, dict[str, dict]] = {"season": {}, "calendar": {}, "water": {}}
    labels = {"season": [f"{y}-{str(y + 1)[2:]}" for y in SEASON_YEARS],
              "calendar": [str(y) for y in CALENDAR_YEARS],
              "water": [str(y) for y in WATER_YEARS]}
    slots: dict[tuple[str, str], dict] = {}
    for kind, names in labels.items():
        for label in names:
            start, end, partial = period_bounds(kind, label, as_of)
            if end < start:
                continue
            n = (end - start).days + 1
            rec = {"start": date_int(start), "end": date_int(end), "n": n, "partial": partial}
            periods[kind][label] = rec
            slots[(kind, label)] = rec
    ok_by_day: dict[str, dict[int, tuple[int, bool]]] = {}
    for element in CORE:
        rows = sorted(obs.get(element, []))
        ok_by_day[element] = {}
        for ordinal, value, ok, trace in rows:
            day = date.fromordinal(ordinal)
            if day > as_of:
                continue
            ok_by_day[element][ordinal] = (value, ok)
            if ok and (newest[element] is None or ordinal > newest[element]):
                newest[element] = ordinal
            if ok and COVER_FIRST <= day <= COVER_LAST:
                cover[element] = cover.get(element, 0) + 1
            for key in _memberships(day):
                rec = slots.get(key)
                if rec is None:
                    continue
                e = rec.setdefault(element, {"rep": 0, "ok": 0})
                e["rep"] += 1
                if not ok:
                    continue
                e["ok"] += 1
                if element in ("PRCP", "SNOW"):
                    e["sum"] = e.get("sum", 0) + value
                    if trace:
                        e["trace"] = e.get("trace", 0) + 1
                elif element == "SNWD":
                    _track(e, value, ordinal, high=True)
                    if value >= DEEP_MM:
                        e["ge1"] = e.get("ge1", 0) + 1
                elif element == "TMAX":
                    _track(e, value, ordinal, high=True)
                    if value >= HOT_TENTHS:
                        e["ge90"] = e.get("ge90", 0) + 1
                elif element == "TMIN":
                    _track(e, value, ordinal, high=False)
                    if value < 0:
                        e["lt32"] = e.get("lt32", 0) + 1
    # the pair figures: freeze-thaw (TMAX and TMIN on one day) and the one-inch snow days with a low below 32 F
    for pair_key, first in (("FT", "TMAX"), ("DL", "SNWD")):
        days_a = ok_by_day.get(first, {})
        days_b = ok_by_day.get("TMIN", {})
        for ordinal in sorted(set(days_a) & set(days_b)):
            a_value, a_ok = days_a[ordinal]
            b_value, b_ok = days_b[ordinal]
            if not (a_ok and b_ok):
                continue
            day = date.fromordinal(ordinal)
            for kind, label in _memberships(day):
                rec = slots.get((kind, label))
                if rec is None:
                    continue
                pair = rec.setdefault(pair_key, {"ev": 0, "n": 0})
                pair["ev"] += 1
                if pair_key == "FT":
                    hit = a_value > 0 and b_value < 0
                else:
                    hit = a_value >= DEEP_MM and b_value < 0
                if hit:
                    pair["n"] += 1
    # a count key is written for an element that has an unflagged value in the period: zero when no day reached the
    # threshold (or had a trace). Written only where ok is above zero, so a zero is never a false zero (the count-key rule).
    for kind in periods:
        for rec in periods[kind].values():
            for element, key in COUNT_KEYS:
                elem = rec.get(element)
                if elem and elem.get("ok", 0) > 0:
                    elem.setdefault(key, 0)
    for kind in periods:
        for label, rec in periods[kind].items():
            for element in CORE:
                if element in rec:
                    rec[element] = _clean(rec[element])
    out = {
        "f": FORMAT, "id": meta["id"], "name": meta["name"], "lat": meta["lat"], "lon": meta["lon"],
        "elev": meta["elev"], "net": meta["net"], "as_of": as_of.isoformat(),
        "current": {e: bool(newest_current({e: newest[e]}, as_of)) for e in CORE},
        "newest": {e: date_int(date.fromordinal(newest[e])) if newest[e] is not None else None for e in CORE},
        "cover": {e: cover.get(e, 0) for e in present},
        "periods": periods,
    }
    return out


def newest_current(newest: dict, as_of: date) -> bool:
    limit = as_of - timedelta(days=FRESH_DAYS)
    return any(v is not None and date.fromordinal(v) >= limit for v in newest.values())


def _memberships(day: date) -> list[tuple[str, str]]:
    out = []
    season = season_of(day)
    if season:
        out.append(("season", season))
    if COVER_FIRST.year <= day.year <= 2026:
        out.append(("calendar", str(day.year)))
    wy = water_year_of(day)
    if wy:
        out.append(("water", str(wy)))
    return out


def _track(e: dict, value: int, ordinal: int, high: bool) -> None:
    """Keep the highest (or lowest) value of a period, its first day and how many days share it."""
    key = "max" if high else "min"
    current = e.get(key)
    if current is None or (value > current if high else value < current):
        e[key] = value
        e[key + "_d"] = ordinal
        e[key + "_n"] = 1
    elif value == current:
        e[key + "_n"] += 1


def _clean(e: dict) -> dict:
    """Ordinals become yyyymmdd integers; empty optional fields are dropped (so the JSON has only what was measured)."""
    out = {}
    for key, value in e.items():
        if key.endswith("_d") and value is not None:
            out[key] = date_int(date.fromordinal(value))
        elif value is None:
            continue
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------- the station rule

def within_radius(stations: dict, lat: float, lon: float) -> list[tuple[float, str]]:
    """Every station in stations within RADIUS_MILES of (lat, lon), nearest first (distance, then id)."""
    out = []
    for sid, meta in stations.items():
        miles = haversine_miles(lat, lon, meta["lat"], meta["lon"])
        if miles <= RADIUS_MILES:
            out.append((miles, sid))
    out.sort()
    return out


def ordered_candidates(base: list[tuple[float, str]], inventory: dict, element: str) -> list[tuple[float, str]]:
    """The candidates for one element from within_radius(): the stations whose inventory lists the element."""
    return [(miles, sid) for miles, sid in base if element in inventory.get(sid, {})]


def choose(candidates: list[tuple[float, str]], summaries: dict, element: str, as_of: date,
           failed=frozenset()) -> dict:
    """The rule for one location and element. candidates is ordered_candidates(); summaries holds the station summaries
    (by id) the walk has; a candidate without a summary stops the walk with state "need" and names it.

    failed holds the ids whose file did not load: a set, or a mapping from id to the reason. A candidate that is in
    failed, or whose summary is an unread entry of a stations block, is never read: its row says unavailable with pass
    None, and the walk goes past it, because it might have passed (B5 job-1 and job-3).

    Returns {"state": "two" | "one" | "unavailable" | "none" | "need", "chosen": [...], "examined": [...],
    "need": id or None, "candidates": n, "unread": [{"id", "name", "miles", "reason"}], "incomplete": bool}.
    "unavailable": no station passes and a candidate was not read. "one" or "two" with unread candidates are
    incomplete: the two nearest that pass are not known, and station_words says so. Each examined row carries its id,
    miles, ok, of, share, pass, current; a row for a candidate that did not load carries unavailable true and pass
    None. The walk stops at two passing stations, so the examined rows are exactly the stations the rule read."""
    chosen, examined, unread = [], [], []
    for miles, sid in candidates:
        entry = summaries.get(sid) or {}
        if sid in failed or entry.get("unread"):
            reason = failed[sid] if isinstance(failed, Mapping) and sid in failed else entry.get("reason")
            examined.append({"id": sid, "miles": round(miles, 1), "unavailable": True, "pass": None})
            unread.append({"id": sid, "name": entry.get("name") or sid, "miles": round(miles, 1), "reason": reason})
            continue
        if sid not in summaries:
            return {"state": "need", "need": sid, "chosen": chosen, "examined": examined,
                    "candidates": len(candidates), "unread": unread, "incomplete": bool(unread)}
        sd = summaries[sid]
        ok = sd["cover"].get(element, 0)
        share = ok / COVER_DAYS
        current = bool(sd["current"].get(element))          # D18: current for this element only
        passed = current and share >= COVER_MIN
        row = {"id": sid, "name": sd["name"], "net": sd["net"], "miles": round(miles, 1), "ok": ok,
               "of": COVER_DAYS, "share": round(share, 4), "current": current, "pass": passed}
        examined.append(row)
        if passed:
            chosen.append({"id": sid, "name": sd["name"], "net": sd["net"], "miles": round(miles, 1), "ok": ok,
                           "of": COVER_DAYS, "share": round(share, 4)})
            if len(chosen) == 2:
                break
    if len(chosen) == 2:
        state = "two"
    elif chosen:
        state = "one"
    else:
        state = "unavailable" if unread else "none"
    return {"state": state, "chosen": chosen, "examined": examined, "need": None, "candidates": len(candidates),
            "unread": unread, "incomplete": bool(unread)}


def _passing_list(candidates: list[tuple[float, str]], summaries: dict, element: str, as_of: date,
                  failed=frozenset(), where: dict | None = None, cap: int = TILE_LIST_CAP) -> dict:
    """D36: the candidates for one element and one tile centre, nearest first, walked as choose() walks them but up to
    cap passing stations (choose() stops at two). A passing station is current for the element with at least COVER_MIN of
    COVER_DAYS (the rule's own test). A candidate whose file did not load is listed in unread with its name, position and
    reason, and the walk goes past it (D32: never silently). where maps an id to its (lat, lon, name) for the unread entries.
    Returns {"passing": [...], "unread": [...], "capped": bool, "need": id or None}; need names a candidate with no summary
    yet, and the caller pulls it and walks again."""
    passing, unread = [], []
    where = where or {}
    for miles, sid in candidates:
        entry = summaries.get(sid) or {}
        if sid in failed or entry.get("unread"):
            reason = failed[sid] if isinstance(failed, Mapping) and sid in failed else entry.get("reason")
            lat, lon, name = where.get(sid, (None, None, None))
            unread.append({"id": sid, "name": entry.get("name") or name or sid, "lat": lat, "lon": lon,
                           "miles": round(miles, 1), "reason": reason})
            continue
        if sid not in summaries:
            return {"passing": passing, "unread": unread, "capped": False, "need": sid}
        sd = summaries[sid]
        ok = sd["cover"].get(element, 0)
        share = ok / COVER_DAYS
        if bool(sd["current"].get(element)) and share >= COVER_MIN:
            passing.append({"id": sid, "name": sd["name"], "lat": sd["lat"], "lon": sd["lon"],
                            "miles": round(miles, 1), "ok": ok, "of": COVER_DAYS, "share": round(share, 4)})
            if len(passing) >= cap:
                return {"passing": passing, "unread": unread, "capped": True, "need": None}
    return {"passing": passing, "unread": unread, "capped": False, "need": None}


def unread_of(light: dict) -> dict[str, str | None]:
    """The candidates whose file did not load, as {id: reason}: the entries of a stations block with unread true."""
    return {sid: row.get("reason") for sid, row in light.items() if row.get("unread")}


def point_rule(light: dict, lat: float, lon: float, element: str, as_of: date) -> dict:
    """The rule at one point (a town, a gate or a tile centre) from a stations block's entries: the walk the build ran,
    with the unread candidates as failed. The site's summary reads the sheet's tile centres and the town points this
    way, so every point's choice is the build's rule (the tile centres are not stored in the block)."""
    base = within_radius(light, lat, lon)
    inventory = {sid: row.get("cover", {}) for sid, row in light.items()}
    return choose(ordered_candidates(base, inventory, element), light, element, as_of, failed=unread_of(light))


def tile_list_picks(block: dict | None, lat: float, lon: float, light: dict | None = None,
                    radius_miles: float = RADIUS_MILES) -> dict | None:
    """D36, the shared rule for the picks at a point: the two nearest passing stations of one element's tile list to the
    point (the cell centre on the sheet, the town point on a town page). This is the Python side of the rule; the sheet's
    browser is to run the same rule on the same tile files (hail/tl/<tile>.json) in part B2, and the summary's
    chosen_from_tile_list gives the same picks (checked on the combined store's tile lists: no difference).

    block is the tile list's block for the element: "passing" (up to TILE_LIST_CAP stations that pass the coverage and
    currency test, nearest the tile centre first, each with id, name, lat, lon, miles and share), "unread" (candidates whose
    file did not load, with their position when known) and "capped" (the list stopped at the cap). The rule: the passing
    entries within radius_miles of the point, nearest first (ties by id); the first two are the picks. An unread candidate
    nearer than the second pick (any unread candidate when there are fewer than two picks, or no position) is named as
    failed and never skipped (D32). When the list is capped and fewer than two passing entries lie within radius_miles, the
    list cannot answer (a station it does not hold might be nearer), and the result is None.

    light is the stations block's entries by id; it supplies each pick's net type (COOP, CoCoRaHS, ...). Returns {"state":
    "two" | "one" | "unavailable" | "none", "picks": [{"id", "name", "net", "miles"}], "unread": [{"id", "name", "miles",
    "reason"}], "candidates": n, "incomplete": bool} with miles rounded to a tenth. "unavailable": no pick and an unread
    candidate; "none": no passing station within the radius."""
    if not block:
        return None
    rows = []
    for entry in block.get("passing", []):
        miles = haversine_miles(lat, lon, entry["lat"], entry["lon"])
        if miles <= radius_miles:
            rows.append((miles, entry))
    rows.sort(key=lambda r: (r[0], r[1]["id"]))
    if block.get("capped") and len(rows) < 2:
        return None
    picks = rows[:2]
    cut = picks[-1][0] if len(picks) == 2 else radius_miles
    unread = []
    for entry in block.get("unread", []):
        miles = haversine_miles(lat, lon, entry["lat"], entry["lon"]) if entry.get("lat") is not None else None
        if miles is None or miles <= cut:
            unread.append({"id": entry["id"], "name": entry.get("name") or entry["id"],
                           "miles": None if miles is None else round(miles, 1), "reason": entry.get("reason")})
    out = []
    for miles, entry in picks:
        row = (light or {}).get(entry["id"]) or {}
        out.append({"id": entry["id"], "name": entry.get("name") or row.get("name", entry["id"]),
                    "net": row.get("net"), "miles": round(miles, 1)})
    state = "two" if len(out) == 2 else "one" if out else ("unavailable" if unread else "none")
    return {"state": state, "picks": out, "unread": unread, "candidates": len(rows), "incomplete": bool(unread)}


UNREAD_NAMES_SHOWN = 3       # the nearest unread stations named in a sentence; the rest are counted


def _join_names(names: list[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _unread_text(unread: list[dict]) -> tuple[str, str]:
    """(the station names, the reason in brackets or ""): the nearest UNREAD_NAMES_SHOWN unread stations by name, then
    the count of the others. The list is nearest first, as the rule walks it."""
    names = [str(u.get("name") or u["id"]) for u in unread]
    more = len(names) - UNREAD_NAMES_SHOWN
    listed = _join_names(names[:UNREAD_NAMES_SHOWN])
    if more > 0:
        listed = f"{', '.join(names[:UNREAD_NAMES_SHOWN])} and {more} more {'station' if more == 1 else 'stations'}"
    reasons = sorted({str(u["reason"]) for u in unread if u.get("reason")})
    return listed, (f" ({'; '.join(reasons)})" if reasons else "")


def station_words(result: dict, element: str) -> list[str]:
    """The plain lines for a rule result (D5). A candidate whose file did not load comes first (B5 job-1 and job-3):
    "unavailable" says a station within 40 miles may pass, and "one" or "two" with an unread candidate says the two
    nearest that pass are not known, so neither reads as "no station" or "only one station". Without one, the none
    sentence, or the one-station sentence."""
    lines = []
    name = element_name(element)
    unread = result.get("unread") or []
    if unread:
        names, reason = _unread_text(unread)
        key = "unread_element" if result["state"] == "unavailable" else "unread_partial"
        lines.append(WORDS[key].format(element=name, stations=names, reason=reason))
    elif result["state"] == "none":
        lines.append(WORDS["none"].format(element=name))
    elif result["state"] == "one":
        only = result["chosen"][0]
        lines.append(WORDS["two_of_one"].format(element=name, station=only["name"]))
    return lines


def element_name(element: str) -> str:
    """The plain name of an element in the sentences (never the bare code)."""
    return {"PRCP": "precipitation", "SNOW": "snowfall", "SNWD": "snow depth", "TMAX": "daily highs",
            "TMIN": "daily lows"}[element]


# ---------------------------------------------------------------- caching and fetching

class _Pacer:
    """Spaces the requests of one build and counts them (the job's request and byte counts are recorded)."""

    def __init__(self, pause: float):
        self.pause = pause
        self.lock = threading.Lock()
        self.last = 0.0
        self.requests = 0
        self.downloaded = 0

    def wait(self) -> None:
        with self.lock:
            gap = self.pause - (time.monotonic() - self.last)
            if gap > 0:
                time.sleep(gap)
            self.last = time.monotonic()
            self.requests += 1

    def add_bytes(self, n: int) -> None:
        with self.lock:
            self.downloaded += int(n)


def _get(url: str, headers: dict) -> tuple[int, bytes | None, dict]:
    """One GET of a file: (status, body or None, response headers). The body is read in chunks and must arrive within
    BODY_CAP_S, so a transfer that stalls or trickles is a failed request; READ_TIMEOUT bounds each read. Raises
    requests.RequestException on a network error and StationsError when the body is too slow."""
    import requests
    resp = requests.get(url, timeout=READ_TIMEOUT, headers=headers, stream=True)
    try:
        if resp.status_code != 200:
            return resp.status_code, None, dict(resp.headers or {})
        began = time.monotonic()
        parts = []
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                parts.append(chunk)
            if time.monotonic() - began > BODY_CAP_S:
                raise StationsError("the download took longer than the time allowed")
        return 200, b"".join(parts), dict(resp.headers or {})
    finally:
        resp.close()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".stations-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)                    # mkstemp makes 0600 files; the store and cache files are ordinary files
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _lastmod_path(path: Path) -> Path:
    return path.with_name(path.name + ".lastmod")


def _read_lastmod(path: Path) -> str | None:
    """The Last-Modified value a cached file was downloaded with (D26), or None when none was kept."""
    try:
        value = _lastmod_path(path).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    return value or None


def _write_lastmod(path: Path, value: str | None) -> None:
    """Keeps the Last-Modified value of a file just written; with no header value, the old record is removed so that a
    stale date is never compared. A record that cannot be kept only means the file is requested again next time."""
    try:
        if value:
            _write_atomic(_lastmod_path(path), (value + "\n").encode("utf-8"))
        elif _lastmod_path(path).is_file():
            _lastmod_path(path).unlink()
    except OSError:
        pass


def _head_last_modified(url: str, pacer: _Pacer) -> str | None:
    """One HEAD request (D26): the Last-Modified header, or None when there is none, the status is not 200, or the
    request fails (the caller then requests the file in full, as it would without this check)."""
    import requests
    pacer.wait()
    try:
        resp = requests.head(url, timeout=READ_TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    value = (resp.headers or {}).get("Last-Modified")
    return str(value) if value else None


def fetch(url: str, path: Path, check, *, offline: bool, refresh: bool, pacer: _Pacer, attempts: int = 3,
          deadline_at: float | None = None, skip_unchanged: bool = False):
    """(data or None, state, reason). A cached file is read unless refresh is set. A cached file must pass check too:
    an unusable copy is requested again (or, offline, reported as unusable). A download is kept only when check passes.
    offline, no request is made: a refresh then serves the cached copy and says so; a file the cache lacks fails.
    deadline_at (a time.monotonic() value): a request that would start after it is not made, and the file fails with
    REASON_NO_ANSWER (or serves its cached copy). skip_unchanged (D26): a refresh of a cached file that has a kept
    Last-Modified first asks for the header with one HEAD request; when it equals the kept value, the file is not
    fetched and the state is "unchanged". Never writes a file it has not checked."""
    import requests
    cached, corrupt = None, None
    if path.is_file():
        cached = path.read_bytes()
        try:
            check(cached)
        except StationsError as exc:
            corrupt, cached = str(exc), None
        else:
            if not refresh:
                return cached, "cache", None
    if offline:
        if cached is not None:
            return cached, "cache", "offline: the cached copy was used and was not re-read"
        if corrupt:
            return None, "failed", f"the cached copy is not usable ({corrupt}), and this build makes no requests"
        return None, "failed", "the cache has no copy and this build makes no requests"
    if skip_unchanged and cached is not None:
        kept = _read_lastmod(path)
        if kept and (deadline_at is None or time.monotonic() < deadline_at):
            if _head_last_modified(url, pacer) == kept:
                return cached, "unchanged", None
    last = REASON_NO_ANSWER
    for attempt in range(1, attempts + 1):
        if deadline_at is not None and time.monotonic() >= deadline_at:
            last = REASON_NO_ANSWER
            break
        pacer.wait()
        try:
            status, data, headers = _get(url, {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        except requests.RequestException as exc:
            last = type(exc).__name__
        except StationsError as exc:
            last = str(exc)
        else:
            if status == 200:
                try:
                    check(data)
                except StationsError as exc:
                    last = str(exc)
                else:
                    pacer.add_bytes(len(data))
                    try:
                        _write_atomic(path, data)
                    except OSError as exc:          # a file that cannot be kept is a note, not a failed source
                        note = f"the file could not be kept in the cache ({type(exc).__name__})"
                        return data, "fetched", note
                    _write_lastmod(path, _header_value(headers, "Last-Modified"))
                    return data, "fetched", ("the cached copy was not usable and was replaced" if corrupt else None)
            else:
                last = f"HTTP {status}"
                if status != 429 and status < 500:
                    break
        if attempt < attempts:
            time.sleep(1.5 * attempt)
    if cached is not None:
        return cached, "cache", f"served the cached copy after: {last}"
    return None, "failed", last


def _header_value(headers: dict, name: str) -> str | None:
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == wanted:
            return str(value)
    return None


def _check_list(data: bytes) -> None:
    if data.count(b"\n") < 100000:
        raise StationsError("the station list has fewer lines than the GHCN list")


def _check_inventory(data: bytes) -> None:
    if data.count(b"\n") < 500000:
        raise StationsError("the inventory has fewer lines than the GHCN inventory")


def _check_dly(sid: str):
    def check(data: bytes) -> None:
        if len(data) < 269 or data[:11] != sid.encode("ascii"):
            raise StationsError(f"the file for {sid} is not a GHCN-Daily file")
    return check


# ---------------------------------------------------------------- the build

def _tile_names(index: dict) -> list[str]:
    tiles = index.get("tiles")
    if not isinstance(tiles, list) or not tiles:
        raise StationsError("the index lists no tiles")
    return list(tiles)


def _locations(index: dict) -> list[dict]:
    towns = json.loads(TOWNS_FILE.read_text(encoding="utf-8"))
    locs = [{"key": f"town:{t['slug']}", "name": t["name"], "lat": float(t["lat"]), "lon": float(t["lon"])}
            for t in towns]
    for name, (lat, lon) in GATE_POINTS.items():
        locs.append({"key": f"gate:{name}", "name": name, "lat": lat, "lon": lon})
    for name in _tile_names(index):
        tr, tc = int(name[1:5]), int(name[7:11])
        lat, lon = tile_centre(tr, tc)
        locs.append({"key": f"tile:{name}", "name": name, "lat": lat, "lon": lon})
    return locs


def collect(index: dict, cache: Path, *, offline: bool = False, refresh="none", procs: int = 4,
            deadline_at: float | None = None, scope: str | None = None) -> dict:
    """Fetch (or read the cache for) the station list, the inventory and every daily file the rule and the snow check
    need, and summarise them. Returns the summaries, the byte counts, the request counts and the failures. The walk
    pulls the nearest few candidates of every location first, then only what the rule asks for. refresh is refresh_set's
    setting: "all" re-reads the list, the inventory and every file; a set of ids re-reads only those .dly files."""
    as_of = date.fromisoformat(index["as_of"])
    current_min_year = (as_of - timedelta(days=FRESH_DAYS)).year
    every, ids, skip, lists_refresh = scope_settings(scope, index, refresh)
    pacer = _Pacer(PACE_S)
    failures: list[dict] = []
    unchanged: set[str] = set()
    raw_list, state, reason = fetch(STATIONS_URL, cache / "ghcn" / "ghcnd-stations.txt", _check_list,
                                    offline=offline, refresh=lists_refresh, pacer=pacer, deadline_at=deadline_at,
                                    skip_unchanged=skip)
    if raw_list is None:
        raise StationsError(f"the station list could not be read ({reason})")
    if reason:
        failures.append({"source": "stations", "reason": reason})
    stations = parse_station_list(raw_list.decode("latin-1"))
    raw_inv, state_i, reason_i = fetch(INVENTORY_URL, cache / "ghcn" / "ghcnd-inventory.txt", _check_inventory,
                                       offline=offline, refresh=lists_refresh, pacer=pacer, deadline_at=deadline_at,
                                       skip_unchanged=skip)
    if raw_inv is None:
        raise StationsError(f"the station inventory could not be read ({reason_i})")
    if reason_i:
        failures.append({"source": "inventory", "reason": reason_i})
    inventory = parse_inventory(raw_inv.decode("latin-1"), stations.keys())
    # the stations that could ever be a candidate (any core element reaching the current year)
    alive = {sid: meta for sid, meta in stations.items()
             if sid in inventory and any(last >= current_min_year for _f, last in inventory[sid].values())}
    # the regression set (D7): every Montana station with a SNOW record that overlaps the five water years
    regression = sorted(sid for sid, inv in inventory.items()
                        if "SNOW" in inv and inv["SNOW"][0] <= WATER_YEARS[-1] and inv["SNOW"][1] >= WATER_YEARS[0] - 1)
    locs = _locations(index)
    lists = {}
    for loc in locs:
        base = within_radius(alive, loc["lat"], loc["lon"])
        lists[loc["key"]] = {element: ordered_candidates(base, inventory, element) for element in CORE}
    summaries: dict[str, dict] = {}
    sizes: dict[str, int] = {}
    failed: set[str] = set()
    fails_by_id: dict[str, str] = {}
    malformed = 0
    rule_pulled: set[str] = set()

    def pull(sids: list[str]) -> None:
        nonlocal malformed
        todo = [s for s in sids if s not in summaries and s not in failed]
        if not todo:
            return
        jobs = []
        for sid in todo:
            path = cache / "ghcn" / "dly" / f"{sid}.dly"
            jobs.append((sid, path))
        results = {}
        if procs > 1 and not offline:
            with ThreadPoolExecutor(max_workers=procs) as pool:
                futs = {pool.submit(fetch, DLY_URL.format(id=sid), path, _check_dly(sid), offline=offline,
                                    refresh=(every or sid in ids), pacer=pacer, deadline_at=deadline_at,
                                    skip_unchanged=skip and sid in ids): sid
                        for sid, path in jobs}
                for fut in futs:
                    results[futs[fut]] = fut.result()
        else:
            for sid, path in jobs:
                results[sid] = fetch(DLY_URL.format(id=sid), path, _check_dly(sid), offline=offline,
                                     refresh=(every or sid in ids), pacer=pacer, deadline_at=deadline_at,
                                     skip_unchanged=skip and sid in ids)
        for sid, _path in jobs:
            data, state_d, reason_d = results[sid]
            if data is None:
                failed.add(sid)
                fails_by_id[sid] = reason_d or "no answer"
                failures.append({"source": "daily", "station": sid, "reason": fails_by_id[sid]})
                continue
            sizes[sid] = len(data)
            if state_d == "unchanged":
                unchanged.add(sid)
            parsed = parse_dly(data, sid)
            malformed += parsed["malformed"]
            summaries[sid] = summarize(dict(stations[sid], id=sid), parsed, as_of)
            if reason_d:
                failures.append({"source": "daily", "station": sid, "reason": reason_d})

    # first batch: the nearest candidates of every location, so the walk seldom needs a second request
    first = []
    for loc in locs:
        for element in CORE:
            first.extend(sid for _m, sid in lists[loc["key"]][element][:PULL_FIRST])
    pull(sorted(set(first)))
    rule_pulled |= set(summaries) | failed
    # the walk: ask for the next file each location and element needs, until every one is settled
    while True:
        needs = set()
        results: dict[str, dict[str, dict]] = {}
        for loc in locs:
            results[loc["key"]] = {}
            for element in CORE:
                res = choose(lists[loc["key"]][element], summaries, element, as_of, fails_by_id)
                results[loc["key"]][element] = res
                if res["state"] == "need":
                    needs.add(res["need"])
        if not needs:
            break
        pull(sorted(needs))
        rule_pulled |= set(summaries) | failed
    # D36: the tile lists (up to TILE_LIST_CAP passing stations per element and tile). The walk pulls the files they need,
    # and every file it reads joins the rule set (the daily refresh set) and the chosen set.
    tile_keys = [loc["key"] for loc in locs if loc["key"].startswith("tile:")]
    where = {sid: (meta["lat"], meta["lon"], meta["name"]) for sid, meta in alive.items()}
    while True:
        needs = set()
        tile_lists = {key: {element: _passing_list(lists[key][element], summaries, element, as_of, fails_by_id, where)
                            for element in CORE} for key in tile_keys}
        for per in tile_lists.values():
            for res in per.values():
                if res["need"]:
                    needs.add(res["need"])
        if not needs:
            break
        pull(sorted(needs))
        rule_pulled |= set(summaries) | failed
    rule_ids = sorted(rule_pulled)
    # the regression set (D7): pull and summarise every Montana station with a SNOW record in the five water years
    regression_pulled = [s for s in regression if s not in rule_pulled]
    pull(sorted(regression))
    rule_bytes = sum(sizes.get(s, 0) for s in rule_ids)
    chosen_ids = sorted({c["id"] for loc in locs for element in CORE for c in results[loc["key"]][element]["chosen"]}
                        | {p["id"] for per in tile_lists.values() for res in per.values() for p in res["passing"]})
    return {"as_of": as_of, "stations": stations, "alive": alive, "regression": regression,
            "regression_extra": regression_pulled, "summaries": summaries, "sizes": sizes, "failed": failed,
            "failures": failures, "malformed": malformed, "results": results, "rule_ids": rule_ids,
            "rule_bytes": rule_bytes, "locs": locs, "chosen_ids": chosen_ids, "requests": pacer.requests,
            "downloaded": pacer.downloaded,
            "refresh": scope or ("all" if every else ("ids" if ids else "none")), "refresh_ids": len(ids),
            "unchanged": sorted(unchanged), "inventory": inventory, "fails_by_id": dict(fails_by_id),
            "tile_lists": tile_lists}


def sd_bytes(sd: dict) -> bytes:
    return (json.dumps(sd, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def write_sd(store: Path, summaries: dict) -> dict[str, dict]:
    """Writes every hail/sd/<id>.json (deterministic bytes) and returns {relative path: {bytes, sha256}}."""
    out = {}
    for sid in sorted(summaries):
        data = sd_bytes(summaries[sid])
        rel = f"{SD_PREFIX}{sid}.json"
        _write_atomic(store / rel, data)
        out[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return out


def tile_list_bytes(name: str, lists: dict) -> bytes:
    """One tile list file (D36): the tile, its centre, the radius and the cap, and per element the passing and unread entries."""
    tr, tc = int(name[1:5]), int(name[7:11])
    lat, lon = tile_centre(tr, tc)
    doc = {"f": TILE_LIST_FORMAT, "tile": name, "centre": [lat, lon], "miles": RADIUS_MILES, "cap": TILE_LIST_CAP,
           "elements": {element: {"passing": res["passing"], "unread": res["unread"], "capped": res["capped"]}
                        for element, res in sorted(lists.items())}}
    return (json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def write_tile_lists(store: Path, tile_lists: dict) -> dict[str, dict]:
    """Writes hail/tl/<tile>.json for every tile of the walk (deterministic bytes) and returns {relative path: {bytes,
    sha256}}. The folder is rebuilt whole, so a tile that left the index leaves no file."""
    folder = Path(store) / TILE_LIST_PREFIX.rstrip("/")
    if folder.is_dir():
        for old in folder.glob("*.json"):
            old.unlink()
    out = {}
    for key in sorted(tile_lists):
        name = key[len("tile:"):]
        data = tile_list_bytes(name, tile_lists[key])
        rel = f"{TILE_LIST_PREFIX}{name}.json"
        _write_atomic(Path(store) / rel, data)
        out[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return out


def _tile_block(tl_files: dict, tile_lists: dict) -> dict:
    """The index's tile_lists block: the format, the cap and radius, the file count and bytes, the lists that reached
    the cap, the longest list, and the unread entries the walk met (D32)."""
    results = [res for per in tile_lists.values() for res in per.values()]
    return {"format": TILE_LIST_FORMAT, "cap": TILE_LIST_CAP, "miles": RADIUS_MILES, "files": len(tl_files),
            "bytes": sum(v["bytes"] for v in tl_files.values()),
            "capped": sum(1 for res in results if res["capped"]),
            "longest": max((len(res["passing"]) for res in results), default=0),
            "unread": sum(len(res["unread"]) for res in results)}


def _light(sd: dict) -> dict:
    return {"name": sd["name"], "lat": sd["lat"], "lon": sd["lon"], "elev": sd["elev"], "net": sd["net"],
            "current": sd["current"], "newest": sd["newest"], "cover": sd["cover"]}


def _towns_block(results: dict, summaries: dict, locs: list[dict], as_of: date) -> dict:
    out = {}
    for loc in locs:
        if not loc["key"].startswith("town:"):
            continue
        slug = loc["key"][5:]
        out[slug] = {e: _rule_row(results[loc["key"]][e], e) for e in CORE}
    return out


def _rule_row(res: dict, element: str) -> dict:
    return {"state": res["state"], "chosen": [c["id"] for c in res["chosen"]],
            "examined": [{k: v for k, v in row.items() if k != "name"} for row in res["examined"]],
            "incomplete": bool(res.get("incomplete")), "unread": [u["id"] for u in res.get("unread", [])]}


def _unread_entries(got: dict) -> dict[str, dict]:
    """The stations block's entries for the candidates whose file did not load (B5 job-1 and job-3): the name, the
    position and the network the rule needs, unread true, the reason, and null counts for each element the inventory
    lists (a missing count is never read as zero). Only the failed stations the rule can reach (alive) are kept."""
    out = {}
    for sid in sorted(got["failed"]):
        meta = got["alive"].get(sid)
        if meta is None:
            continue
        out[sid] = {"name": meta["name"], "lat": meta["lat"], "lon": meta["lon"], "elev": meta["elev"],
                    "net": meta["net"], "unread": True, "reason": got["fails_by_id"].get(sid),
                    "cover": {element: None for element in sorted(got["inventory"].get(sid, {}))}}
    return out


def _partial_problem(unread: list[dict], failures: list[dict]) -> str:
    """The D20 sentence for a stations block that is partial (D28, D32). Each candidate station whose file did not load
    is named in it, with its id, in the order given (build gives id order); with no candidate failed, the failed files
    are counted."""
    if unread:
        names = [f"{u['name']} ({u['id']})" for u in unread]
        return WORDS["unread_named"].format(names=_named_list(names))
    n = len(failures)
    return WORDS["unread_block"].format(count=n, file="file" if n == 1 else "files")


def _named_list(names: list[str]) -> str:
    """The names: the first UNREAD_NAMES_SHOWN in full, the rest counted (a named failure, never a bare count)."""
    more = len(names) - UNREAD_NAMES_SHOWN
    if more <= 0:
        return _join_names(names)
    return f"{', '.join(names[:UNREAD_NAMES_SHOWN])} and {more} more {'station' if more == 1 else 'stations'}"


def _failure_detail(failures: list[dict]) -> str:
    """The technical reason beside the partial sentence (D28): each failure's station or source, and its reason."""
    return "; ".join(f"{f.get('station') or f.get('source')}: {f.get('reason')}" for f in failures[:50])


def build(store: Path, cache: Path, *, offline: bool = False, refresh="none", procs: int = 4,
          deadline_at: float | None = None, scope: str | None = None) -> dict:
    """Builds hail/sd/ and the index's stations block for the store at store (a directory that holds hail/). The daily
    job re-reads the rule's files (refresh = the rule_station_ids of the last build, see rule_ids_of); the monthly job
    re-reads everything (refresh = "all")."""
    store = Path(store)
    index_path = store / "hail" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    t0 = time.monotonic()
    if scope is not None and scope not in SCOPES:
        raise StationsError("the scope is not daily or monthly")
    try:
        got = collect(index, Path(cache), offline=offline, refresh=refresh, procs=procs, deadline_at=deadline_at,
                      scope=scope)
    except StationsError as exc:
        # the station side is marked unavailable and the rest of the store builds (D16); the files of an earlier
        # build are removed, because the manifest must not list files this build did not make
        for old in (store / SD_PREFIX).glob("*.json") if (store / SD_PREFIX).is_dir() else []:
            old.unlink()
        for old in (store / TILE_LIST_PREFIX.rstrip("/")).glob("*.json") if (store / TILE_LIST_PREFIX.rstrip("/")).is_dir() else []:
            old.unlink()
        block = {"state": "unavailable", "problem": WORDS["unavailable"], "detail": str(exc), "rule": _rule_constants()}
        _merge_index(store, block)
        _merge_manifest(store, {}, prefixes=(SD_PREFIX, TILE_LIST_PREFIX))
        return {"state": "unavailable", "problem": WORDS["unavailable"], "detail": str(exc)}
    as_of = got["as_of"]
    sd_files = write_sd(store, got["summaries"])
    tl_files = write_tile_lists(store, got["tile_lists"])
    unread_entries = _unread_entries(got)
    towns = _towns_block(got["results"], got["summaries"], got["locs"], as_of)
    gates = {}
    for name, (lat, lon) in GATE_POINTS.items():
        gates[name] = {e: _rule_row(got["results"][f"gate:{name}"][e], e) for e in CORE}
    state = "partial" if got["failures"] else "loaded"
    block = {
        "state": state,
        "problem": None if state == "loaded" else _partial_problem(
            [{"id": sid, "name": row["name"]} for sid, row in sorted(unread_entries.items())], got["failures"]),
        "detail": None if state == "loaded" else _failure_detail(got["failures"]),
        "as_of": as_of.isoformat(),
        "rule": _rule_constants(),
        "sources": {
            "stations": {"url": STATIONS_URL, "bytes": len(_read_bytes(cache / "ghcn" / "ghcnd-stations.txt"))},
            "inventory": {"url": INVENTORY_URL, "bytes": len(_read_bytes(cache / "ghcn" / "ghcnd-inventory.txt"))},
            "daily": {"example": DLY_URL.format(id="USC00240802"),
                      "note": "one file per station: the station id is the file name, followed by .dly"},
        },
        "counts": {
            "mt_stations": len(got["stations"]),
            "mt_current_candidates": len(got["alive"]),
            "rule_files": len(got["rule_ids"]),
            "rule_bytes": got["rule_bytes"],
            "regression_files": len(got["regression"]),
            "regression_extra_files": len(got["regression_extra"]),
            "sd_files": len(sd_files),
            "sd_bytes": sum(v["bytes"] for v in sd_files.values()),
            "locations": len(got["locs"]),
            "failed_files": len(got["failed"]),
            "chosen_files": len(got["chosen_ids"]),
            "chosen_bytes": sum(got["sizes"].get(s, 0) for s in got["chosen_ids"]),
            "requests": got["requests"],
            "downloaded_bytes": got["downloaded"],
        },
        "refresh": {"mode": got["refresh"], "ids": got["refresh_ids"], "unchanged": len(got["unchanged"])},
        "unchanged_station_ids": got["unchanged"],
        "rule_station_ids": got["rule_ids"],
        "chosen_station_ids": got["chosen_ids"],
        "malformed": got["malformed"],
        "failures": got["failures"][:50],
        "failed_station_ids": sorted(got["failed"]),
        "towns": towns,
        "gates": gates,
        "tile_lists": _tile_block(tl_files, got["tile_lists"]),
        "stations": {**{sid: _light(got["summaries"][sid]) for sid in sorted(got["summaries"])},
                     **unread_entries},
    }
    _merge_index(store, block)
    _merge_manifest(store, {**sd_files, **tl_files}, prefixes=(SD_PREFIX, TILE_LIST_PREFIX))
    return {"state": state, "seconds": round(time.monotonic() - t0, 1), "files": len(sd_files), "bytes": block["counts"]["sd_bytes"],
            "rule_files": block["counts"]["rule_files"], "rule_bytes": block["counts"]["rule_bytes"],
            "failures": len(got["failures"]), "malformed": got["malformed"]}


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.is_file() else b""


def rule_ids_of(store: Path) -> list[str]:
    """The station ids the last build's rule read: the daily refresh set (466 files at as_of 2026-10-16). [] when the
    index holds no stations block with that list."""
    index = json.loads((Path(store) / "hail" / "index.json").read_text(encoding="utf-8"))
    block = index.get(INDEX_KEY) or {}
    return [str(s) for s in (block.get("rule_station_ids") or [])]


def _rule_constants() -> dict:
    return {"radius_miles": RADIUS_MILES, "fresh_days": FRESH_DAYS, "cover_min": COVER_MIN,
            "current": "per element: an unflagged value of the element within fresh_days of as_of (D18)",
            "season_min": SEASON_MIN, "cover_days": COVER_DAYS, "cover_window": "2020-01-01 to 2025-12-31",
            "hot_tenths": HOT_TENTHS, "deep_mm": DEEP_MM, "pull_first": PULL_FIRST}


def _merge_index(store: Path, block: dict) -> None:
    path = store / "hail" / "index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    index[INDEX_KEY] = block
    _write_atomic(path, (json.dumps(index, indent=1, ensure_ascii=True) + "\n").encode("utf-8"))


def _merge_manifest(store: Path, new_files: dict, prefixes: tuple) -> None:
    """Replaces this module's entries (every path under prefixes) and refreshes hail/index.json's own entry."""
    path = store / "hail" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = {k: v for k, v in manifest.get("files", {}).items() if not k.startswith(prefixes)}
    files.update(new_files)
    index_bytes = (store / "hail" / "index.json").read_bytes()
    files["hail/index.json"] = {"bytes": len(index_bytes), "sha256": hashlib.sha256(index_bytes).hexdigest()}
    manifest["files"] = {k: files[k] for k in sorted(files)}
    _write_atomic(path, (json.dumps(manifest, indent=1, ensure_ascii=True) + "\n").encode("utf-8"))


# ---------------------------------------------------------------- verify

def verify(store: Path) -> dict:
    """Checks the stations block, the sd files, the gate rows and the manifest. Returns {"ok", "checks": [...]}."""
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    block = index.get(INDEX_KEY)
    check("index block present", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    check("index state is loaded or partial", block.get("state") in ("loaded", "partial"), str(block.get("state")))
    manifest = json.loads((store / "hail" / "manifest.json").read_text(encoding="utf-8"))
    sd_dir = store / "hail" / "sd"
    files = sorted(sd_dir.glob("*.json")) if sd_dir.is_dir() else []
    loaded = [sid for sid, row in block.get("stations", {}).items() if not row.get("unread")]
    unread = sorted(sid for sid, row in block.get("stations", {}).items() if row.get("unread"))
    check("sd files match the stations block", len(files) == len(loaded),
          f"{len(files)} files, {len(loaded)} stations loaded, {len(unread)} unread")
    failed_ids = set(block.get("failed_station_ids", []))
    check("failed files are listed, and none has an sd file",
          set(unread) <= failed_ids and not any((sd_dir / f"{sid}.json").exists() for sid in failed_ids),
          f"{len(failed_ids)} failed, {len(unread)} unread entries")
    bad = 0
    for path in files:
        data = path.read_bytes()
        rel = path.relative_to(store).as_posix()
        entry = manifest["files"].get(rel)
        if entry is None or entry["bytes"] != len(data) or entry["sha256"] != hashlib.sha256(data).hexdigest():
            bad += 1
    check("manifest lists each sd file with its bytes and SHA-256", bad == 0, f"{bad} mismatches")
    idx_entry = manifest["files"].get("hail/index.json", {})
    idx_bytes = (store / "hail" / "index.json").read_bytes()
    check("manifest index entry is current", idx_entry.get("sha256") == hashlib.sha256(idx_bytes).hexdigest())
    # every sd file: the periods are complete and the counts are integers
    nonint = 0
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for kind in doc["periods"].values():
            for rec in kind.values():
                for key in ("n",):
                    if not isinstance(rec.get(key), int):
                        nonint += 1
                for element in CORE:
                    got = rec.get(element)
                    if got is None:
                        continue
                    for key, value in got.items():
                        if not isinstance(value, int):
                            nonint += 1
        if doc.get("f") != FORMAT:
            nonint += 1
    check("sd figures are integers and the format is hail-stn-v1", nonint == 0, f"{nonint} problems")
    stations_doc = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in files}
    # gate B5-3: Billings and Benchland
    rules = _verify_gates(block, stations_doc, check)
    # gate B5-9: the corrected roof series, reproduced under D1 from the Billings airport file (USW00024033); the
    # second corrected series (Stanford, USC00247864, the 1-inch and low-below-32 F days) is checked too
    _verify_roof_series(stations_doc, check)
    # the 17 towns: the count of seasons with at least 95 percent of days, per element
    towns_lines = []
    for slug, per in sorted(block.get("towns", {}).items()):
        counts = {}
        for element in CORE:
            row = per.get(element, {})
            seasons = 0
            for chosen in row.get("chosen", []):
                sd = stations_doc.get(chosen)
                if sd is None:
                    continue
                for label in (f"{y}-{str(y + 1)[2:]}" for y in SEASON_YEARS[:-1]):
                    rec = sd["periods"]["season"].get(label)
                    ok = count_of(rec, element, "ok")
                    if rec and ok is not None and ok >= SEASON_MIN * rec["n"]:
                        seasons += 1
            counts[element] = seasons
        # station-seasons that pass the 95 percent rule, out of the five seasons at each chosen station
        towns_lines.append(f"{slug}: " + ", ".join(
            f"{e} {counts[e]} of {5 * len(per.get(e, {}).get('chosen', []))}" for e in CORE))
    check("towns: five seasons counted per element at the two stations", len(towns_lines) == 17,
          f"{len(towns_lines)} towns")
    picks = _verify_tile_lists(store, index, block, manifest, check)
    ok = all(c["pass"] for c in checks)
    return {"ok": ok, "checks": checks, "towns_seasons_95": towns_lines, "gate_rules": rules,
            "tile_picks": picks}


def _verify_tile_lists(store: Path, index: dict, block: dict, manifest: dict, check) -> dict:
    """D36, verify. One tile list per index tile, in its format and under the cap, nearest first, with every passing entry
    current at COVER_MIN (checked against the stations block); the manifest entries. Then, for the Billings and Benchland
    points, the two nearest passing stations for every element, from the tile list of the tile that holds the point
    (tile_picks). The gate picks of GATE_STATIONS must hold, and no failed candidate may be nearer than the second pick:
    a failed candidate that is nearer leaves the picks not known (D32)."""
    from . import hail
    folder = store / TILE_LIST_PREFIX.rstrip("/")
    tiles = [str(t) for t in index.get("tiles", [])]
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    docs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in files}
    check("tile lists: one file per index tile", sorted(docs) == sorted(tiles),
          f"{len(docs)} files for {len(tiles)} tiles")
    bad = 0
    for path in files:
        data = path.read_bytes()
        entry = manifest["files"].get(path.relative_to(store).as_posix())
        if entry is None or entry["bytes"] != len(data) or entry["sha256"] != hashlib.sha256(data).hexdigest():
            bad += 1
    check("manifest lists each tile list with its bytes and SHA-256", bad == 0, f"{bad} mismatches")
    problems = 0
    stations_rows = block.get("stations", {})
    for name, doc in docs.items():
        if doc.get("f") != TILE_LIST_FORMAT or doc.get("tile") != name or doc.get("cap") != TILE_LIST_CAP:
            problems += 1
        for element, res in doc.get("elements", {}).items():
            passing = res.get("passing", [])
            if len(passing) > TILE_LIST_CAP or [p["miles"] for p in passing] != sorted(p["miles"] for p in passing):
                problems += 1
            for p in passing:
                row = stations_rows.get(p["id"], {})
                if row.get("unread") or not (row.get("current") or {}).get(element) or p["share"] < COVER_MIN:
                    problems += 1
    check("tile lists: format, the cap of six, nearest first, every passing entry current at 80 percent",
          problems == 0, f"{problems} problems")
    picks: dict = {}
    for place, (lat, lon) in GATE_POINTS.items():
        row, col = hail.cell_for(lat, lon)
        doc = docs.get(hail.tile_name(row // hail.TILE, col // hail.TILE))
        picks[place] = {}
        for element in CORE:
            res = ((doc or {}).get("elements") or {}).get(element) or {"passing": [], "unread": []}
            ranked = sorted(res["passing"], key=lambda p: (haversine_miles(lat, lon, p["lat"], p["lon"]), p["id"]))
            two = ranked[:2]
            cut = haversine_miles(lat, lon, two[1]["lat"], two[1]["lon"]) if len(two) == 2 else float("inf")
            failed_nearer = [u["id"] for u in res["unread"]
                             if u.get("lat") is None or haversine_miles(lat, lon, u["lat"], u["lon"]) < cut]
            picks[place][element] = {"picks": [p["id"] for p in two],
                                     "miles": [round(haversine_miles(lat, lon, p["lat"], p["lon"]), 1) for p in two],
                                     "failed_nearer": failed_nearer}
            want = GATE_STATIONS.get((place, element))
            if want is not None:
                got = picks[place][element]["picks"]
                check(f"tile picks at the {place} point, {element} (D36, gate B5-3)",
                      sorted(got) == sorted(want) and not failed_nearer, ", ".join(got) or "none")
    return picks


GATE_STATIONS = {
    # gate B5-3 (brief): the two stations the rule picks, per element, at the gate points
    ("billings", "TMAX"): ["USC00240802", "USW00024033"],
    ("billings", "TMIN"): ["USC00240802", "USW00024033"],
    ("billings", "PRCP"): ["USC00240802", "USW00024033"],
    ("billings", "SNOW"): ["USC00240802", "USW00024033"],
    ("billings", "SNWD"): ["USC00240802", "USW00024033"],
    ("benchland", "SNOW"): ["US1MTFG0003", "USC00243947"],     # D18: see GATE_REPLACED
    ("benchland", "SNWD"): ["USC00247864", "USS0009C01S"],
}
# D18 replacements: the station the per-element rule no longer picks, the station it picks, and the reason the verify
# record gives (the old station's examined row must read current false for the element)
GATE_REPLACED = {
    ("benchland", "SNOW"): {
        "was": "USC00244978", "now": "USC00243947",
        "why": ("Lewistown 11 SSE (31.1 miles, 90.0 percent) has no SNOW report in the 30 days before the as_of date: its "
                "last SNOW report is 2026-05-18. Its PRCP and TMAX are current, which the old any-element rule accepted. "
                "Harlowton 11NW (34.8 miles, 99.5 percent, SNOW reported 2026-10-12) is the next station that passes."),
    },
}


ROOF_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")
ROOF_YEARS = (2021, 2022, 2023, 2024, 2025)
ROOF_EXPECT = {
    # the refuter's corrected counts (roof-indicators-refuter.json: M6-90F, M6-snowdays, M6-freezethaw, M6-low, M10)
    "USW00024033": {"hot": [45, 42, 27, 35, 25], "deep": [55, 70, 30, 53, 25], "ft": [86, 102, 88, 88, 85],
                    "lt32": [121, 154, 118, 126, 103], "deep_low": [40, 66, 39, 25, 57]},
    "USC00247864": {"deep_low": [34, 63, 34, 32, 60]},
}


def _verify_roof_series(docs: dict, check) -> None:
    """Gate B5-9: the counts the roof lines use, under D1 (90 F is TMAX of 322 tenths or more; 1 inch of snow on the
    ground is SNWD of 25 mm or more; freeze-thaw is TMAX above 0 and TMIN below 0; a low below 32 F is TMIN below 0)."""
    airport = docs.get("USW00024033")
    if airport:
        exp = ROOF_EXPECT["USW00024033"]
        seasons = airport["periods"]["season"]
        calendar = airport["periods"]["calendar"]
        hot = [count_of(seasons.get(s), "TMAX", "ge90") for s in ROOF_SEASONS]
        deep = [count_of(seasons.get(s), "SNWD", "ge1") for s in ROOF_SEASONS]
        ft = [pair_of(seasons.get(s), "FT") for s in ROOF_SEASONS]
        lt32 = [count_of(seasons.get(s), "TMIN", "lt32") for s in ROOF_SEASONS]
        deep_low = [pair_of(calendar.get(str(y)), "DL") for y in ROOF_YEARS]
        _check_series(check, "gate B5-9 Billings highs of 90 F by season (D1)", hot, exp["hot"])
        _check_series(check, "gate B5-9 Billings days with 1 inch of snow on the ground by season", deep, exp["deep"])
        _check_series(check, "Billings freeze-thaw days by season (refuter M6)", ft, exp["ft"])
        _check_series(check, "Billings days with a low below 32 F by season (refuter M6)", lt32, exp["lt32"])
        _check_series(check, "gate B5-9 Billings snow of 1 inch with a low below 32 F by calendar year (refuter M10)",
                      deep_low, exp["deep_low"])
    else:
        check("gate B5-9 Billings airport file present", False, "USW00024033 has no sd file")
    stanford = docs.get("USC00247864")
    if stanford:
        deep_low = [pair_of(stanford["periods"]["calendar"].get(str(y)), "DL") for y in ROOF_YEARS]
        _check_series(check, "gate B5-9 Stanford snow of 1 inch with a low below 32 F by calendar year (refuter M10)",
                      deep_low, ROOF_EXPECT["USC00247864"]["deep_low"])


def _check_series(check, name: str, got: list, want: list) -> None:
    """One series of counts against the expected values. A missing count is a named failure, never an error and
    never a zero (the count-key rule)."""
    if any(v is None for v in got):
        check(name, False, "no value for this season; not zero")
    else:
        check(name, got == want, str(got))


def _verify_gates(block: dict, docs: dict, check) -> dict:
    """Gate B5-3: the rule's stations at Billings and Benchland, element by element, against the brief's list. A pick
    that D18 changed is checked against its recorded reason: the station it replaced must read not current for that
    element in the rule's own examined rows."""
    out = {}
    gates = block.get("gates", {})
    for (place, element), want in sorted(GATE_STATIONS.items()):
        got = list(gates.get(place, {}).get(element, {}).get("chosen", []))
        check(f"gate B5-3 {place} {element}", sorted(got) == sorted(want), ", ".join(got) or "none")
        out[f"{place}_{element}"] = got
        change = GATE_REPLACED.get((place, element))
        if change:
            examined = {row["id"]: row for row in gates.get(place, {}).get(element, {}).get("examined", [])}
            old = examined.get(change["was"], {})
            check(f"gate B5-3 {place} {element}: {change['was']} replaced by {change['now']} under D18",
                  change["now"] in got and change["was"] not in got and old.get("current") is False
                  and old.get("pass") is False, change["why"])
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.stations", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build hail/sd/ and the stations block into a store")
    b.add_argument("--store", required=True)
    b.add_argument("--cache", required=True, help="the cache root: ghcn/ holds the list, the inventory and dly/")
    b.add_argument("--procs", type=int, default=4)
    b.add_argument("--offline", action="store_true", help="no request is made; a refresh serves the cached copy")
    b.add_argument("--scope", choices=SCOPES, default=None,
                   help="daily: the list, the inventory and the chosen stations' files, skipping a file whose "
                        "Last-Modified is unchanged; monthly: every file the rule and the regression set read (D26)")
    b.add_argument("--refresh", choices=("none", "all"), default=None,
                   help="all: re-read the list, the inventory and every file (the earlier monthly job)")
    b.add_argument("--refresh-ids", default=None,
                   help="a file of station ids, one per line: re-read those .dly files only (the earlier daily job)")
    b.add_argument("--deadline-at", type=float, default=None,
                   help="epoch seconds: no request starts after this time (the job's clock)")
    v = sub.add_parser("verify", help="check the stations block and the sd files")
    v.add_argument("--store", required=True)
    r = sub.add_parser("rule-ids", help="print the station ids the last build's rule read, one per line")
    r.add_argument("--store", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "rule-ids":
        print("\n".join(rule_ids_of(Path(args.store))))
        return 0
    if args.cmd == "build":
        if args.scope and (args.refresh or args.refresh_ids):
            build_parser().error("--scope cannot be combined with --refresh or --refresh-ids")
        refresh: object = args.refresh or "none"
        if args.refresh_ids:
            refresh = frozenset(line.strip() for line in Path(args.refresh_ids).read_text(encoding="utf-8").split()
                                if line.strip())
        deadline_at = None
        if args.deadline_at is not None:
            deadline_at = time.monotonic() + (args.deadline_at - time.time())
        result = build(Path(args.store), Path(args.cache), offline=args.offline, refresh=refresh,
                       procs=args.procs, deadline_at=deadline_at, scope=args.scope)
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    result = verify(Path(args.store))
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
