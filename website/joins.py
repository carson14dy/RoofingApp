"""Hail history joins (B2): what else happened at each spot, joined to the B1 store's tiles.

Five kinds of evidence sit beside the radar estimate (docs/DECISIONS.md D34; the B2 brief), each with its own kind
word and never merged into another: a report (an NWS local storm report, IEM's LSR archive), an official record
(NCEI Storm Events: hail and thunderstorm wind points, and zone-coded rows; D34), a radar detection (NCEI's SWDI
nx3hail hail signatures), a warning (the NWS warning polygon
that covered the spot, IEM's watchwarn archive) and a zone product (an NWS zone-wide product for the spot's forecast
zone), plus a station reading (the nearest ASOS gusts, IEM's daily summaries). Nothing here states damage, an
all-clear, insurance or eligibility (AGENTS.md rule 5). A missing source says so: "Data unavailable".

Output, written into the store next to B1's shards (store/hail/):
  j/events.json               every report (LSR), record (NCEI hail and thunderstorm wind points) and warning
                              (SV, TO, FF) in the window, once each; the rows carry the fields of the B2 brief
  j/r{tr:04d}_c{tc:04d}.json  one per B1 tile, for the tile's bounds (the browser filters by the cell's distance):
                              reports and records as indexes into events.json, warnings as [index, 100-bit
                              cover], detections in full, the zone map as {zone code: [cell keys]}, the fire weather
                              zones as {fire zone code: [cell keys]}, and the two nearest stations within 40 miles
                              of the tile centre
  z/MTZ###.json               one per current Montana forecast zone: its zone products (the ten in ZONE_PRODUCTS;
                              FL.W is a polygon product and the county-only flood watches go to B5's county path,
                              D34, D35) and NCEI zone-coded rows. A
                              product's "b" is its begin (the earliest NEW or CON issue, else the issue time its rows
                              carry), "e" its end (the earliest cancellation (CAN) or upgrade (UPG) time, else the
                              latest expiry of its other rows; null when none is recorded; D26 keeps a cancellation or
                              upgrade time even when it is not after the begin) and "st": "cancelled" or "upgraded",
                              the status of the row that set the end (D6, D16, D26, D31)
  z/fire-MTZ###.json          one per fire weather zone: red flag warnings (D7), in the same event shape
  s/<id>.json                 one per MT_ASOS station: the days with a gust of 50 kt (58 mph) or more, as whole numbers
  hail/index.json             gains a "joins" block (counts, parts, the request summary, the lags, the report types,
                              the zone editions and the malformed-row counts)
  hail/manifest.json          lists every j/, z/ and s/ file with its bytes and SHA-256

Each report lies within five miles of about seven tiles, so the events table keeps each row once; the j/ files are
19.9 MB in the current build (the budget is 40 MB).

Units and conventions (the B2 brief): LSR hail and rain/snow in inches as reported; LSR gusts and sustained wind in
mph (the archive gives no unit; the research reads it as mph); LSR MAG "None" is missing. NCEI BEGIN times are MST-7
local (UTC = local + 7 h) and every shown time is Montana time (MDT or MST). NCEI wind is in knots, with mph =
round(kt x 1.15078) beside it. SWDI MAXSIZE is inches, stored as hundredths (an integer), exact duplicate rows
dropped. IEM daily gusts are knots: many are whole knots, and nearly all the rest fit a whole mph multiplied by
0.8689762 (inferred from the values; the feed does not document it). Station days are whole knots and whole mph, the
mph from the unrounded knots (D18). Warning tags are the NWS numbers as the archive gives them, in inches and mph.
Times are UTC in the store.

Zone editions (D16): every public zone edition the NWS page links is read (z_18mr25.zip and z_16ap26.zip; each date
is the day and month in its file name). A product takes the zone code of the edition in force on its issue day. The
two linked editions hold the same 83 zones with the same codes, names and outlines; the index records that. A code no
current zone holds is counted as unplaced (D11), and the zone sections say so for Montana as a whole.

Malformed rows (D21): a row whose date, position or magnitude cannot be read is skipped and counted (malformed_rows in
the index); a row with too few fields is counted as short (D10). Neither fails its file or the build.

Cache (D10, D15): a re-pull window (the last two months of LSR and SWDI, the current year of warnings, zone products
and station days, and in January the previous year too) is fetched fresh and written over the cached copy. The cached
copy is used only when the fresh request fails, and the index then says "served from cache since". --offline makes no
request at all: the cache is the only input, so two offline builds from one cache are byte-identical.

The window is the B1 store's window: SPC report days from window[0] to window[1], that is UTC instants from
12:00 UTC on the first day up to 12:00 UTC on the day after the last.

Command line (run from the repository root):
    python -m website.joins build --store DIR [--cache DIR] [--procs 4] [--today YYYY-MM-DD] [--offline]
    python -m website.joins verify DIR                      check the joins in a store (exit 1 on a failure)
    python -m website.joins compare DIR                    the research counts against this build
    python -m website.joins fixture [--out DIR] [--from-store DIR]   write the SAMPLE joins for the fixture
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from . import hail

FORMAT = "hail-joins-v1"            # j/ files
ZONE_FORMAT = "hail-zone-v1"        # z/ files
EVENTS_FORMAT = "hail-events-v1"    # j/events.json: every report, record and warning row once
EVENTS_NAME = "events.json"
STATION_FORMAT = "hail-station-v1"  # s/ files
INDEX_KEY = "joins"                 # the block in hail/index.json (and manifest["joins"])
MILE_KM = 1.609344
REPORT_MILES = 5.0
DETECT_MILES = 2.0
STATION_MILES = 40.0
MPH_PER_KT = 1.15078
KT_PER_MPH = 0.8689762              # IEM's daily gust conversion (whole mph x this = knots)
STATION_KT = 50                     # a station day counts at this peak gust or more
IMPLAUSIBLE_KT = 130                # values at or above this are dropped (the station list has no quality flag)
EARTH_KM = 6371.0088
MONTANA_TZ = ZoneInfo("America/Denver")
PARTS = ("reports", "records", "detections", "warnings", "zones", "stations")
REPULL_MONTHS = 2                   # LSR and SWDI months re-pulled daily: this month and the one before
MAX_AGE_S = 20 * 3600               # kept for callers that pass max_age_s; it is no cache test since D15: a re-pull
                                    # window always fetches, and the cached copy is used only when that request fails
ZONE_SAME_DEG = 1e-6                # two zone outlines are the same zone within this many degrees (vertex by vertex)
PACE_S = 0.25                       # at least this long between two requests (the IEM asks for no fixed rate)
USER_AGENT = "montana-hail-watch-joins/1 (+https://github.com/carson14dy/RoofingApp)"
LSR_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/lsr.py"
WW_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py"
DAILY_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py"
ASOS_URL = "https://mesonet.agron.iastate.edu/geojson/network/MT_ASOS.geojson"
NCEI_DIR = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
SWDI_URL = "https://www.ncei.noaa.gov/swdiws/csv/nx3hail/{start}:{end}"
SWDI_BBOX = "-116.05,44.36,-104.04,49.00"
NWS_GIS_URL = "https://www.weather.gov/gis/PublicZones"
NWS_BASE_URL = "https://www.weather.gov/source/gis/Shapefiles/WSOM/"
WARNING_PHENOMENA = ("SV", "TO", "FF")                     # significance W, issuance polygons only
# D34, D35: the zone products B2 reads, from IEM's zone rows (one request per product and year). Flood warnings (FL.W)
# are polygon products: their IEM rows have no zone code (polygon rows) or are county rows (MTC), so the zone path
# places no FL.W event and FL.W is not a zone product here; B5 joins it through the polygon path. Flood watches (FA.A)
# are zone products where IEM gives a zone code, so the zone-coded flood watches are joined. The 18 county-only flood
# watch events (county rows, MTC) go to B5's county path.
ZONE_PRODUCTS = (("HW", "W"), ("WS", "W"), ("BZ", "W"), ("IS", "W"), ("EC", "W"), ("WC", "W"), ("FW", "W"),
                 ("DS", "W"), ("WI", "Y"), ("FA", "A"))
LSR_HEADER = ("VALID", "VALID2", "LAT", "LON", "MAG", "WFO", "TYPECODE", "TYPETEXT", "CITY", "COUNTY", "STATE",
              "SOURCE", "REMARK", "UGC", "UGCNAME", "QUALIFIER")
LSR_UNITS = {"H": "in", "R": "in", "S": "in", "G": "mph", "N": "mph", "A": "mph"}
LSR_QUALIFIERS = {"E": "estimated", "M": "measured", "U": "unknown"}
NCEI_QUALIFIERS = {"MG": "measured gust", "EG": "estimated gust", "MS": "measured sustained",
                   "ES": "estimated sustained"}
NCEI_POINT_TYPES = ("Hail", "Thunderstorm Wind")
NCEI_WIND_TYPES = ("Thunderstorm Wind", "High Wind", "Strong Wind")
# D19: the type codes that carry a unit (a magnitude is shown only for these); every other code is typed (type word only).
NCEI_UNIT_CODES = frozenset(t.lower() for t in NCEI_POINT_TYPES + NCEI_WIND_TYPES)
UNIT_CODES = frozenset(LSR_UNITS) | NCEI_UNIT_CODES
SWDI_HEADER = ("ZTIME", "WSR_ID", "CELL_ID", "PROB", "SEVPROB", "MAXSIZE", "LAT", "LON")
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
PRODUCT_NAMES = {
    "SV.W": "Severe thunderstorm warning", "TO.W": "Tornado warning", "FF.W": "Flash flood warning",
    "HW.W": "High wind warning", "HW.A": "High wind watch", "WS.W": "Winter storm warning",
    "BZ.W": "Blizzard warning", "IS.W": "Ice storm warning", "EC.W": "Extreme cold warning",
    "WC.W": "Wind chill warning", "FW.W": "Red flag warning", "FA.A": "Flood watch",
    "DS.W": "Dust storm warning", "WI.Y": "Wind advisory",
}
KIND_WORDS = {"SV": "Severe thunderstorm", "TO": "Tornado", "FF": "Flash flood"}
# D31: the statuses that end a zone event (a cancellation or an upgrade), and the "st" word each one gives the event
ZONE_STOP_STATE = {"CAN": "cancelled", "UPG": "upgraded"}
# the WORDS_JOINS keys for an "st" word: the suffix after a span, and "{word} at {time}" for an end at or before
# the begin
ZONE_STOP_WORDS = {"cancelled": ("zones_cancelled", "zones_cancelled_at"),
                   "upgraded": ("zones_upgraded", "zones_upgraded_at")}
# The research counts the gate reads (docs/DECISIONS.md D34 and research/hail-history/validation-evidence/*.json).
RESEARCH_COUNTS = {
    "lsr_hail_window": 1347,            # point-reports-archives.json fact 16 (LSR H, five years)
    "lsr_g_window": 2733,               # point-reports-archives.json fact 16 (LSR G)
    "ncei_hail_by_year": {2021: 139, 2022: 233, 2023: 75, 2024: 96, 2025: 190},   # fact 26
    "swdi_distinct_window": 60357,      # swdi.json fact 15 (nx3hail, Montana polygon)
    "sv_events_window": 2240,           # warnings-archive.json fact 8 (NEW SV polygons)
    "to_events_window": 17,             # warnings-archive.json fact 9
    "station_days_50kt_by_year": {2021: 305, 2022: 285, 2023: 121, 2024: 238, 2025: 247},   # wind-history.json 24
}
BENCHLAND_GATE = {"cell": (797, 1986), "report_cell": (792, 1998), "day": "2025-06-15", "hhmm": 2010,
                  "in": "1.75"}     # B2 gate 1 (D1): the warnings and the zone at cell, the report at report_cell
ZONE_NEAR_KM = 2.0                  # D8: a Montana cell no public zone claims takes the nearest zone edge this close
EDITION_DATE = date(2026, 4, 16)    # the effective date of the newest public zone edition the NWS page links (z_16ap26.zip,
                                    # read from its file name); each edition's own date comes from its name (D16)
JOINS_DEADLINE_S = 35 * 60          # the joins' own limit from the start of the build (the job has 60 minutes; D34, D35)
NWS_FIRE_URL = "https://www.weather.gov/gis/FireZones"      # the fire weather zone editions (D7)

WORDS_JOINS = {
    "sample": "SAMPLE data",
    "times_note": "Times are Montana time, with the zone abbreviation (MDT or MST).",
    "time": "{hour}:{minute} {ampm} {zone}",
    "am": "am",
    "pm": "pm",
    # reports
    "reports_heading": "Reports within 5 miles",
    "reports_what": ("A report is what a spotter, a member of the public or a sensor sent to the National Weather "
                     "Service (an NWS local storm report). A report is not an inspection and not a finding about a "
                     "roof. Hail sizes are in inches as reported. Wind speeds are "
                     "read as miles per hour, because the archive does not state the unit. Estimated and measured "
                     "are the archive's own codes. Reports are not a complete record. A report's remark and a "
                     "warning's tag are the NWS's own words about the report or the forecast threat, not a finding "
                     "about this address."),
    "reports_lead_many": "{n} NWS local storm reports within 5 miles between {start} and {end}.",
    "reports_lead_one": "1 NWS local storm report within 5 miles between {start} and {end}.",
    "reports_lead_none": ("No NWS local storm report within 5 miles in these five years. Reports are what people "
                          "sent the NWS; they are not a complete record."),
    "reports_row": "Report: {date} {time}: {type}, {magnitude}{qualifier}, {source}, {miles} mi {bearing}",
    "reports_row_here": "Report: {date} {time}: {type}, {magnitude}{qualifier}, {source}, {miles} mi",
    "reports_row_typed": "Report: {date} {time}: {type}{qualifier}, {source}, {miles} mi {bearing}",
    "reports_row_here_typed": "Report: {date} {time}: {type}{qualifier}, {source}, {miles} mi",
    "qualifier_part": " ({qualifier})",
    "magnitude_none": "no size given",
    "magnitude_in": "{value} in",
    "magnitude_mph": "{value} mph",
    "magnitude_kt": "{value} kt",
    "magnitude_kt_mph": "{value} kt ({mph} mph)",
    "magnitude_unitless": "{value}",
    "remark_line": "Remark, as written: \u201c{remark}\u201d",
    # official records
    "records_heading": "Official records within 5 miles (NCEI Storm Events)",
    "records_what": ("Official records are NOAA's Storm Events entries. This list has hail and thunderstorm wind points "
                     "within 5 miles. Zone-coded records (high wind, winter storm, heavy snow and the other events "
                     "NCEI codes to a forecast zone) are for the spot's forecast zone and cover the whole zone, not this "
                     "spot alone. NCEI county-coded points of tornado, flood, flash flood, heavy rain, funnel cloud, "
                     "lightning and debris flow are not joined in this version; the NWS local storm reports of those "
                     "kinds are joined as reports. Wind magnitudes are in knots, with miles per hour beside them."),
    "records_lag": "NCEI's database runs to {newest}.",
    "records_lead_many": ("NCEI's database runs to {newest}. {n} official records for this spot or its zone between "
                          "{start} and {end}."),
    "records_lead_one": ("NCEI's database runs to {newest}. 1 official record for this spot or its zone between "
                         "{start} and {end}."),
    "records_lead_none": ("NCEI's database runs to {newest}. No official record for this spot or its zone between "
                          "{start} and {end}. Records are not a complete account of every storm."),
    "records_row": "Record: {date} {time}: {type}, {magnitude}{qualifier}, {source}, {miles} mi {bearing}",
    "records_row_here": "Record: {date} {time}: {type}, {magnitude}{qualifier}, {source}, {miles} mi",
    "records_row_typed": "Record: {date} {time}: {type}{qualifier}, {source}, {miles} mi {bearing}",
    "records_row_here_typed": "Record: {date} {time}: {type}{qualifier}, {source}, {miles} mi",
    "records_zone_row": "Record: {date} {time}: {type}, {magnitude}{qualifier}, {source}, across zone {zone}",
    "records_zone_row_typed": "Record: {date} {time}: {type}{qualifier}, {source}, across zone {zone}",
    "records_unplaced_one": ("1 official zone record in Montana in the window could not be placed on a zone; its zone "
                             "code is not in the public zone editions the NWS page links."),
    "records_unplaced_many": ("{n} official zone records in Montana in the window could not be placed on a zone; their "
                              "zone codes are not in the public zone editions the NWS page links."),
    # radar detections
    "detections_heading": "Radar hail detections within 2 miles",
    "detections_what": ("A detection is the radar algorithm's hail signature for a storm cell, not hail on the "
                        "ground. Detections are counted by SPC day (12:00 UTC to 12:00 UTC the next day). The "
                        "archive has known gaps and is not a complete inventory."),
    "detections_lag": "The newest detection in this build is from {newest}.",
    "detections_lag_none": "No detection date is in this build.",
    "detections_lead_many": "{n} radar hail detections within 2 miles between {start} and {end}.",
    "detections_lead_one": "1 radar hail detection within 2 miles between {start} and {end}.",
    "detections_lead_none": ("No radar hail detection within 2 miles between {start} and {end}. The archive has "
                             "known gaps, so this is not evidence of no hail."),
    "detections_row_many": "Detection: {date}: {n} detections, largest {in} in",
    "detections_row_one": "Detection: {date}: 1 detection, largest {in} in",
    # warnings
    "warnings_heading": "Warnings that covered this spot",
    "warnings_what": ("A warning is listed when its issuance polygon covered this spot when it was issued. The times are "
                      "when that polygon was in effect, which can differ from the warning's own valid time; this sheet "
                      "does not show the valid time. Tags are the forecast threat at issue time, not what fell. The "
                      "archive keeps the number only, so a value the text gave as less than shows as that number. A "
                      "report's remark and a warning's tag are the NWS's own words about the report or the forecast "
                      "threat, not a finding about this address."),
    "warnings_lag": "The newest warning in this build starts on {newest}.",
    "warnings_lag_none": "No warning start date is in this build.",
    "warnings_lead_many": "{n} warnings covered this spot between {start} and {end}.",
    "warnings_lead_one": "1 warning covered this spot between {start} and {end}.",
    "warnings_lead_none": ("No warning in the archive covered this spot between {start} and {end}. Warnings cover "
                           "areas, and a spot outside every polygon is not a statement that no storm reached it."),
    "warnings_lead_unknown": ("Warnings for this spot cannot be checked in this build, because some warnings in these "
                              "five years have no outline on file. That is not the same as no warning."),
    "warnings_no_outline_one": ("1 warning in these five years has no outline on file, so it cannot be matched to "
                                "this spot."),
    "warnings_no_outline_many": ("{n} warnings in these five years have no outline on file, so they cannot be matched "
                                 "to this spot."),
    "warnings_row": "Warning: {date} {begin} to {end}, issuance polygon in effect: {kind} warning, {office}; tags: {tags}",
    "warnings_tags_none": "none stated",
    "tag_hail": "hail {value} in",
    "tag_wind": "wind {value} mph",
    "tag_tornado": "tornado {value}",
    "tag_damage": "NWS damage threat tag: {value}",
    # zone products
    "zones_heading": "Zone products for {zone_name} ({zone})",
    "zones_heading_no_zone": "Zone products",
    "zones_what": ("These covered the whole zone, not this spot alone. A zone product is an NWS warning, watch or "
                   "advisory for a forecast zone, named by its product."),
    # D17: two leads, each with its own count; the public zone lead never counts a red flag warning and the reverse
    "zones_lead_many": "{n} products for zone {zone_name} ({zone}) between {start} and {end}.",
    "zones_lead_one": "1 product for zone {zone_name} ({zone}) between {start} and {end}.",
    "zones_lead_none": ("No product for zone {zone_name} ({zone}) between {start} and {end} is listed. That does not "
                        "mean the weather was calm."),
    "fire_lead_many": "{n} red flag warnings for fire weather zone {zone_name} ({zone}) between {start} and {end}.",
    "fire_lead_one": "1 red flag warning for fire weather zone {zone_name} ({zone}) between {start} and {end}.",
    "fire_lead_none": ("No red flag warning for fire weather zone {zone_name} ({zone}) between {start} and {end} is "
                       "listed. That does not mean the weather was calm."),
    "zones_row": "Zone product: {product}: {events}",
    "zones_event": "{date} {begin} to {end}",
    "zones_event_no_start": "start not recorded; end {end}",
    "zones_event_no_span": "start and end not recorded",
    "zones_end_unset": "end not recorded",
    "zones_cancelled": ", cancelled",
    "zones_cancelled_at": "cancelled at {time}",   # D26: a cancellation time at or before the begin
    "zones_upgraded": ", upgraded",                # D31: an upgrade ends the lower product at its upgrade time
    "zones_upgraded_at": "upgraded at {time}",     # D31: an upgrade time at or before the begin, as D26
    "zones_no_zone": "The forecast zone for this cell could not be determined.",
    "zones_unplaced_one": ("1 zone product in Montana in the window could not be placed on a zone; its zone code is "
                           "not in the public zone editions the NWS page links."),
    "zones_unplaced_many": ("{n} zone products in Montana in the window could not be placed on a zone; their zone codes "
                            "are not in the public zone editions the NWS page links."),
    "zones_fire_unavailable": "Red flag warnings are not listed (fire weather zones were not available).",
    "zones_fire_none": "The fire weather zone for this cell could not be determined.",
    "fire_product": "{product}, fire weather zone {zone_name} ({zone})",
    # station gusts
    "stations_heading": "Peak gusts at the nearest stations",
    "stations_what": ("A station reading is at the airport, not at this address. It is the highest gust the station "
                      "logged that day, in knots with miles per hour beside it."),
    "stations_lead_many": ("{n} days with a peak gust of {kt_min} kt ({mph_min} mph) or more at the nearest stations "
                           "between {start} and {end}."),
    "stations_lead_one": ("1 day with a peak gust of {kt_min} kt ({mph_min} mph) or more at the nearest stations "
                          "between {start} and {end}."),
    "stations_lead_none": ("No day between {start} and {end} at the nearest stations reached {kt_min} kt "
                           "({mph_min} mph). A station is one point, not this address."),
    "stations_row": "Station: {date}: {kt} kt ({mph} mph) at {station}, about {miles} miles away",
    "stations_none_near": "No station within {miles} miles of this spot.",
    "stations_dropped": "{n} readings of {kt} kt or more were left out as implausible.",
    "stations_dropped_one": "1 reading of {kt} kt or more was left out as implausible.",
    # missing data
    # D20: the sentence a part that did not load shows, exactly, in Python and in the browser. {part} and {one} come
    # from the part_ and one_ words below (the part's name, and its singular for "no {one}").
    "unavailable": "{part} could not be loaded in this update; that is not the same as no {one}.",
    "part_reports": "Reports", "one_reports": "report",
    "part_records": "Records", "one_records": "record",
    "part_detections": "Detections", "one_detections": "detection",
    "part_warnings": "Warnings", "one_warnings": "warning",
    "part_zones": "Zone products", "one_zones": "zone product",
    "part_stations": "Station readings", "one_stations": "station reading",
    "partial": ("Data unavailable for some periods: {feed} did not load for {periods} ({reason}). This is not an "
                "all-clear."),
    "source_reports": "Source: NWS local storm reports, Iowa Environmental Mesonet (IEM) archive.",
    "source_records": "Source: NOAA NCEI Storm Events Database, bulk CSV files.",
    "source_detections": "Source: NOAA NCEI Severe Weather Data Inventory (SWDI), NEXRAD hail signatures (nx3hail).",
    "source_warnings": "Source: NWS warning polygons, Iowa Environmental Mesonet (IEM) archive.",
    "source_zones": "Source: NWS warning products for forecast zones, IEM archive; NWS public forecast zones.",
    "source_stations": "Source: IEM daily summaries, Montana ASOS stations (MT_ASOS).",
    "feed_reports": "NWS local storm reports",
    "feed_records": "NCEI Storm Events",
    "feed_detections": "radar hail signatures (SWDI)",
    "feed_warnings": "NWS warning polygons",
    "feed_zones": "NWS zone products",
    "feed_stations": "station gusts (IEM)",
    "reason_no_answer": "the source did not answer",
    "reason_format": "the file was in an unexpected format",
    "reason_zone_map": "the NWS zone map could not be read",
    "reason_stale": "the newest copy did not load",
    "reason_events": "the joins table could not be read",
    "reason_no_file_year": "the NCEI file list has no file for this year",
    "reason_offline": "the file is not in the cache and this build does not fetch",
}
WORDS_JOINS["compass_words"] = list(COMPASS)
WORDS_JOINS["threshold_note"] = "A day counts at {kt} kt ({mph} mph) or more."


class JoinsError(Exception):
    """A file that cannot be used. The message is plain words, lower case, with no full stop."""


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _np():
    import numpy
    return numpy


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


def _compact(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".joins-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- HTTP, cache and ledger

class Result:
    """One request's outcome. reason is the plain words for a failure: the source did not answer, or the file
    came back in a format the parser refuses."""
    __slots__ = ("ok", "data", "state", "status", "error", "reason")

    def __init__(self, ok, data, state, status=None, error=None, reason=None):
        self.ok, self.data, self.state, self.status, self.error = ok, data, state, status, error
        self.reason = reason


class Fetcher:
    """Every request the joins make. A file is read from the cache when it is not due for a re-pull; a due or
    missing file is requested with retries (429 and 5xx, network errors); content is checked before it is kept;
    a failed request falls back to the cached copy when there is one. Each request is one ledger line
    (ledger/joins.jsonl in the store): url, status, bytes, and the cache state (cache, fetched, stale, failed)."""

    def __init__(self, cache_dir, ledger_path=None, *, procs: int = 4, max_age_s: float = MAX_AGE_S,
                 attempts: int = 4, pause: float = 2.0, deadline_s: float | None = None, offline: bool = False):
        self.cache = Path(cache_dir)
        self.ledger = Path(ledger_path) if ledger_path else None
        self.max_age_s = max_age_s              # not a cache test any more (D15); see MAX_AGE_S
        self.offline = bool(offline)            # True: no request is made; a file the cache lacks is a failed source
        self.attempts = attempts
        self.pause = pause
        self.procs = max(1, int(procs))
        self._lock = threading.Lock()
        self._pace_lock = threading.Lock()
        self._last = 0.0
        self._local = threading.local()
        self.stats: dict[str, dict[str, int]] = {}
        self.failures: list[dict] = []
        self.served_since: dict[str, str] = {}      # source -> the earliest day of a cached copy served in place
        # of a failed re-pull (D10: "served from cache since")
        self.deadline_at = None if deadline_s is None else time.monotonic() + deadline_s

    def _session(self):
        import requests
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
            self._local.session = session
        return session

    def _pace(self) -> None:
        with self._pace_lock:
            wait = PACE_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _download(self, url: str, params=None):
        import requests
        last, status = "no answer", None
        for attempt in range(1, self.attempts + 1):
            if self.deadline_at is not None and time.monotonic() >= self.deadline_at:
                return None, status, WORDS_JOINS["reason_no_answer"]    # the joins' time limit: no new request
            self._pace()
            try:
                resp = self._session().get(url, params=params, timeout=(20, 300),
                                           headers={"Accept-Encoding": "identity"})
            except requests.RequestException as exc:
                last = type(exc).__name__
            else:
                status = resp.status_code
                if status == 200:
                    return resp.content, status, None
                last = f"HTTP {status}"
                if status != 429 and status < 500:
                    break
            if attempt < self.attempts:
                time.sleep(self.pause * attempt)
        return None, status, last

    def _fetched_day(self, path: Path) -> str | None:
        meta = path.with_name(path.name + ".meta.json")
        try:
            return datetime.fromisoformat(json.loads(meta.read_text(encoding="utf-8"))["fetched"]).date().isoformat()
        except (OSError, ValueError, KeyError):
            return None

    def _log(self, source, url, status, nbytes, state, error=None):
        with self._lock:
            row = self.stats.setdefault(source, {"requests": 0, "cache": 0, "fetched": 0, "stale": 0, "failed": 0})
            row["requests"] += 1
            row[state] += 1
            if state == "failed":
                self.failures.append({"source": source, "url": url, "reason": error or "no answer"})
            if self.ledger is not None:
                self.ledger.parent.mkdir(parents=True, exist_ok=True)
                line = {"at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"), "source": source, "url": url,
                        "status": status, "bytes": nbytes, "cache": state, "error": error}
                with open(self.ledger, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(line, sort_keys=True) + "\n")

    def get(self, source: str, url: str, rel: str, *, refresh: bool = False, check=None, params=None) -> Result:
        """A re-pull (refresh) fetches fresh and writes the copy over the cached one (D15). A cached copy is served
        when the file is not due for a re-pull, and in place of a failed re-pull (see below). Offline, the cache is
        all there is: a file it lacks is a failed source."""
        path = self.cache / rel
        have = path.is_file()
        if have and (not refresh or self.offline):
            # a cached file was checked when it was written; the parsers still refuse a damaged one (see _take)
            data = path.read_bytes()
            self._log(source, url, None, len(data), "cache")
            return Result(True, data, "cache")
        if self.offline:
            self._log(source, url, None, None, "failed", WORDS_JOINS["reason_offline"])
            return Result(False, None, "failed", None, WORDS_JOINS["reason_offline"], WORDS_JOINS["reason_offline"])
        data, status, err = self._download(url, params)
        why = None
        if data is not None and check is not None:
            try:
                check(data)
            except JoinsError as exc:
                err, data, why = str(exc), None, str(exc) or WORDS_JOINS["reason_format"]
        if data is not None:
            _write_atomic(path, data)
            _write_atomic(path.with_name(path.name + ".meta.json"),
                          _compact({"fetched": _utc_now().isoformat(timespec="seconds"), "url": url,
                                    "bytes": len(data)}))
            self._log(source, url, status, len(data), "fetched")
            return Result(True, data, "fetched", status)
        if have:
            data = path.read_bytes()
            self._log(source, url, status, len(data), "stale", err)
            since = self._fetched_day(path)
            with self._lock:
                if since and (source not in self.served_since or since < self.served_since[source]):
                    self.served_since[source] = since
                self.failures.append({"source": source, "url": url, "reason": err or "no answer",
                                      "served_from_cache_since": since})
            return Result(True, data, "stale", status, err)
        self._log(source, url, status, None, "failed", err)
        return Result(False, None, "failed", status, err, why or WORDS_JOINS["reason_no_answer"])

    def run(self, jobs, fn=None):
        """Run the jobs (each a zero-argument callable returning a Result) with procs threads."""
        if self.procs == 1:
            return [job() for job in jobs]
        with ThreadPoolExecutor(max_workers=self.procs) as pool:
            return list(pool.map(lambda job: job(), jobs))


# ---------------------------------------------------------------- parsers (units, conventions, content checks)

def _text(data: bytes) -> str:
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None


def _sentence_case(text: str) -> str:
    """Sentence case for a source's own words: all-caps words of up to five letters stay (ASOS, CO-OP) and a
    word with an inner capital (CoCoRaHS) keeps it; the rest lower case, with the first letter capitalised."""
    text = " ".join(text.split())
    if not text:
        return ""
    words = []
    for word in text.split(" "):
        if word.isupper() and len(word.strip("-/")) <= 5:
            words.append(word)
        elif not word.isupper() and any(ch.isupper() for ch in word[1:]):
            words.append(word)
        else:
            words.append(word.lower())
    out = " ".join(words)
    return out[0].upper() + out[1:]


def _float(value, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise JoinsError(WORDS_JOINS["reason_format"]) from None
    if not math.isfinite(number):
        raise JoinsError(WORDS_JOINS["reason_format"])
    return number


def _lsr_mag(code: str, raw: str):
    """(mag_text, unit) for an LSR row. MAG "None" or blank is missing (empty text, empty unit)."""
    raw = (raw or "").strip()
    if raw in ("", "None", "none", "NONE"):
        return "", ""
    value = _float(raw, "MAG")
    unit = LSR_UNITS.get(code, "")
    if unit == "in":
        return f"{value:.2f}", "in"
    if unit == "mph":
        return str(int(round(value))), "mph"
    return f"{value:g}", ""


def parse_lsr_rows(data: bytes) -> dict:
    """The rows of one IEM LSR monthly CSV (state MT) as {"rows": [...], "short": n, "malformed": n}. A row with fewer
    fields than the header is skipped and counted as short (D10); a row whose time, position or magnitude cannot be
    read is skipped and counted as malformed (D21). Neither fails the month. Rows with an unquoted comma in CITY have
    17 or more fields: CITY is the fields between the eighth and the last seven (the research's fact 52)."""
    rows = list(csv.reader(io.StringIO(_text(data), newline="")))
    if not rows or tuple(rows[0][:len(LSR_HEADER)]) != LSR_HEADER:
        raise JoinsError(WORDS_JOINS["reason_format"])
    out, short, malformed = [], 0, 0
    for row in rows[1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) < len(LSR_HEADER):
            short += 1
            continue
        if len(row) > len(LSR_HEADER):
            n = len(row)
            row = row[:8] + [",".join(row[8:n - 7])] + row[n - 7:]
        rec = dict(zip(LSR_HEADER, row))
        try:
            utc = datetime.strptime(rec["VALID"].strip(), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            code = rec["TYPECODE"].strip().upper()
            mag, unit = _lsr_mag(code, rec["MAG"])
            lat, lon = _float(rec["LAT"], "LAT"), _float(rec["LON"], "LON")
        except (ValueError, JoinsError):
            malformed += 1
            continue
        qual = rec["QUALIFIER"].strip().upper()
        out.append({
            "utc": utc, "lat": lat, "lon": lon, "code": code,
            "type": rec["TYPETEXT"].strip().lower(), "mag_text": mag, "unit": unit,
            "qual": qual if qual in LSR_QUALIFIERS else "", "src": _sentence_case(rec["SOURCE"]),
            "city": " ".join(rec["CITY"].split()), "remark": " ".join(rec["REMARK"].split())[:160],
            "wfo": rec["WFO"].strip(),
        })
    return {"rows": out, "short": short, "malformed": malformed}


def parse_lsr(data: bytes) -> list[dict]:
    """The rows of one IEM LSR monthly CSV (see parse_lsr_rows)."""
    return parse_lsr_rows(data)["rows"]


def _ncei_rows(data: bytes):
    raw = data
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError):
            raise JoinsError(WORDS_JOINS["reason_format"]) from None
    reader = csv.DictReader(io.StringIO(_text(raw), newline=""))
    need = {"EVENT_TYPE", "STATE", "BEGIN_DATE_TIME", "CZ_TYPE", "CZ_FIPS", "BEGIN_LAT", "BEGIN_LON",
            "MAGNITUDE", "MAGNITUDE_TYPE", "SOURCE", "CZ_TIMEZONE", "BEGIN_LOCATION", "CZ_NAME", "WFO"}
    if reader.fieldnames is None or not need <= set(reader.fieldnames):
        raise JoinsError(WORDS_JOINS["reason_format"])
    return reader


def _ncei_utc(text: str, tz: str) -> tuple[datetime, datetime]:
    """(local naive time, UTC) for an NCEI BEGIN_DATE_TIME such as "11-MAY-25 17:23:00" and CZ_TIMEZONE such as
    "MST-7". Raises JoinsError when the zone is not a fixed offset."""
    try:
        local = datetime.strptime(text.strip(), "%d-%b-%y %H:%M:%S")
    except ValueError:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None
    match = re.fullmatch(r"[A-Z]{3}([+-]\d{1,2})", tz.strip())
    if not match:
        raise JoinsError(WORDS_JOINS["reason_format"])
    utc = local.replace(tzinfo=timezone.utc) - timedelta(hours=int(match.group(1)))
    return local, utc


def parse_ncei(data: bytes) -> dict:
    """The Montana rows of one NCEI Storm Events details file (bulk CSV, gzip or plain). Returns the point rows
    (Hail and Thunderstorm Wind with coordinates), the zone-coded rows (CZ_TYPE Z, any type), the newest local event
    time and the count of short rows skipped (D10). Narratives are not carried. The qualifier is kept as NCEI's code
    (MG, EG, MS, ES, or blank); the words come from NCEI_QUALIFIERS where a row is shown (D5)."""
    reader = _ncei_rows(data)
    points, zone_rows, newest, short, malformed = [], [], None, 0, 0
    for row in reader:
        if None in row.values():         # a short row: its missing fields are None
            short += 1
            continue
        if row.get("STATE", "").strip().upper() != "MONTANA":
            continue
        try:
            local, utc = _ncei_utc(row["BEGIN_DATE_TIME"], row["CZ_TIMEZONE"])
        except JoinsError:
            malformed += 1               # D21: a row with a bad date or zone is skipped and counted
            continue
        if newest is None or local > newest:
            newest = local
        try:
            kind = row["EVENT_TYPE"].strip()
            code = row["MAGNITUDE_TYPE"].strip().upper()
            qual = code if code in NCEI_QUALIFIERS else ""
            src = _sentence_case(row["SOURCE"])
            if row["CZ_TYPE"].strip().upper() == "Z":
                fips = row["CZ_FIPS"].strip()
                if not fips.isdigit():
                    continue
                mag, unit, mph, kt = _ncei_mag(kind, row["MAGNITUDE"])
                zone_rows.append({"zone": "MTZ" + fips.zfill(3), "utc": utc, "lat": None, "lon": None,
                                  "code": kind.lower(), "mag_text": mag, "unit": unit, "qual": qual, "src": src,
                                  "city": _sentence_case(row["CZ_NAME"]), "remark": "", "mag_mph": mph,
                                  "mag_kt": kt})
            elif kind in NCEI_POINT_TYPES and row["BEGIN_LAT"].strip() and row["BEGIN_LON"].strip():
                mag, unit, mph, kt = _ncei_mag(kind, row["MAGNITUDE"])
                points.append({"local_year": local.year, "utc": utc, "lat": _float(row["BEGIN_LAT"], "BEGIN_LAT"),
                               "lon": _float(row["BEGIN_LON"], "BEGIN_LON"), "code": kind.lower(), "mag_text": mag,
                               "unit": unit, "qual": qual, "src": src,
                               "city": _sentence_case(row["BEGIN_LOCATION"]), "remark": "", "mag_mph": mph,
                               "mag_kt": kt})
        except (JoinsError, ValueError):
            malformed += 1               # D21: a row whose position or magnitude cannot be read
    return {"points": points, "zone_rows": zone_rows, "newest_local": newest, "short": short,
            "malformed": malformed}


def _ncei_mag(kind: str, raw: str):
    """(mag_text, unit, mag_mph, mag_kt). Hail is inches to two decimals; wind is knots, with the mph beside it."""
    raw = (raw or "").strip()
    if kind == "Hail" and raw:
        value = _float(raw, "MAGNITUDE")
        return f"{value:.2f}", "in", None, None
    if kind in NCEI_WIND_TYPES and raw:
        kt = int(round(_float(raw, "MAGNITUDE")))
        return str(kt), "kt", int(round(kt * MPH_PER_KT)), kt
    return "", "", None, None


def parse_swdi(data: bytes) -> dict:
    """One SWDI nx3hail CSV (a month of the Montana box). Exact duplicate rows are dropped and MAXSIZE is inches,
    stored as whole hundredths. The archive answers a month with no detections with "summary", "count,0" and the
    time footer and no header: that is an empty month, not a fault. The footers and the one-word summary line are
    skipped everywhere else."""
    lines = _text(data).splitlines()
    footers = [line.strip() for line in lines if line.startswith(("count,", "totalTimeInSeconds,"))]
    data_lines = [line for line in lines[1:] if "," in line and not line.startswith(("count,", "totalTimeInSeconds,"))]
    if lines and lines[0].strip() == "summary":
        if data_lines or "count,0" not in footers:
            raise JoinsError(WORDS_JOINS["reason_format"])
        return {"rows": [], "duplicates": 0, "newest": None, "raw_lines": 0, "malformed": 0}
    if not lines or tuple(x.strip() for x in lines[0].split(",")) != SWDI_HEADER:
        raise JoinsError(WORDS_JOINS["reason_format"])
    seen, rows, dupes, newest, malformed = set(), [], 0, None, 0
    for line in lines[1:]:
        key = line.strip()
        if "," not in key or key.startswith(("count,", "totalTimeInSeconds,")):
            continue   # blank lines, the footer counts and the one-word "summary" line the archive ends with
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        parts = key.split(",")
        try:                                             # D21: a malformed row is skipped and counted
            if len(parts) != len(SWDI_HEADER):
                raise JoinsError(WORDS_JOINS["reason_format"])
            utc = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            size = int(round(_float(parts[5], "MAXSIZE") * 100))
            lat, lon = _float(parts[6], "LAT"), _float(parts[7], "LON")
        except (ValueError, JoinsError):
            malformed += 1
            continue
        if size <= 0 or parts[3].strip() != "100":      # the brief's filter: PROB 100 and a size above zero
            continue
        rows.append({"utc": utc, "lat": lat, "lon": lon, "size": size})
        if newest is None or utc > newest:
            newest = utc
    return {"rows": rows, "duplicates": dupes, "newest": newest, "raw_lines": len(seen) + dupes,
            "malformed": malformed}



def parse_daily(data: bytes) -> dict:
    """One IEM daily summary for a station and year: the calendar day (station local) and the peak gust in knots.
    "None" or blank is missing and is counted, not kept as a zero."""
    rows = list(csv.reader(io.StringIO(_text(data), newline="")))
    if not rows or [x.strip() for x in rows[0]][:3] != ["station", "day", "max_wind_gust_kts"]:
        raise JoinsError(WORDS_JOINS["reason_format"])
    out, missing, malformed = [], 0, 0
    for row in rows[1:]:
        if len(row) < 3 or not row[1].strip():
            continue
        raw = row[2].strip()
        try:                                             # D21: a bad date or value is skipped and counted
            day = date.fromisoformat(row[1].strip())
            if raw in ("", "None", "none"):
                missing += 1
                continue
            out.append((day, _float(raw, "max_wind_gust_kts")))
        except (ValueError, JoinsError):
            malformed += 1
    return {"days": out, "missing": missing, "malformed": malformed}


def station_day_kind(kt: float) -> str:
    """"dropped" for a peak gust at or above IMPLAUSIBLE_KT (kept out and counted), "keep" at or above STATION_KT,
    otherwise "below" (not stored)."""
    if kt >= IMPLAUSIBLE_KT:
        return "dropped"
    if kt >= STATION_KT:
        return "keep"
    return "below"


def _whole(value: float) -> int:
    """A number rounded half up to a whole number (not the banker's rounding of round())."""
    return int(math.floor(value + 0.5))


def station_day_row(day: date, kt: float) -> list:
    """[day index, mph, kt] for a station day, as whole numbers (D18): mph = round(kt x 1.15078) from the unrounded
    knots, and kt to a whole knot. The browser and the town pages print "{kt} kt ({mph} mph)" from these."""
    return [hail.day_index(day), _whole(kt * MPH_PER_KT), _whole(kt)]


def parse_asos_rows(data: bytes) -> dict:
    """The MT_ASOS station list from IEM's network JSON as {"stations": [...], "malformed": n}: id, name, position and
    the archive years. A station with no id or position is skipped and counted (D21)."""
    try:
        doc = json.loads(_text(data))
    except ValueError:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None
    features = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(features, list) or not features:
        raise JoinsError(WORDS_JOINS["reason_format"])
    out, malformed = [], 0
    for feat in features:
        try:
            props = feat.get("properties", {})
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            sid = str(props.get("sid", "")).strip()
            if not sid or len(coords) != 2:
                raise JoinsError(WORDS_JOINS["reason_format"])
            name = str(props.get("sname", sid)).strip()
            name = name.title() if name.isupper() else name     # IEM writes some names in capitals
            out.append({"id": sid, "name": name, "lon": _float(coords[0], "lon"),
                        "lat": _float(coords[1], "lat"), "archive_end": props.get("archive_end")})
        except (AttributeError, TypeError, ValueError, JoinsError):
            malformed += 1
    out.sort(key=lambda s: s["id"])
    return {"stations": out, "malformed": malformed}


def parse_asos(data: bytes) -> list[dict]:
    """The station list only (see parse_asos_rows)."""
    return parse_asos_rows(data)["stations"]


def parse_ww_csv(data: bytes) -> dict:
    """One IEM watchwarn CSV (zone products: rows with a UGC zone code): {"rows": [...], "short": n}. Times are UTC.
    A row with fewer fields than the header is skipped and counted (D10)."""
    reader = csv.DictReader(io.StringIO(_text(data), newline=""))
    need = {"wfo", "utc_issue", "utc_expire", "phenomena", "gtype", "significance", "eventid", "status", "ugc",
            "vtec_year", "hailtag", "windtag", "tornadotag", "damagetag"}
    if reader.fieldnames is None or not need <= set(reader.fieldnames):
        raise JoinsError(WORDS_JOINS["reason_format"])
    out, short, malformed = [], 0, 0
    for row in reader:
        if None in row.values():
            short += 1
            continue
        try:
            issue = datetime.strptime(row["utc_issue"].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            expire = datetime.strptime(row["utc_expire"].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            malformed += 1                       # D21: a row with a bad time is skipped and counted
            continue
        out.append({"wfo": row["wfo"].strip(), "phen": row["phenomena"].strip(), "sig": row["significance"].strip(),
                    "eventid": row["eventid"].strip(), "status": row["status"].strip(),
                    "ugc": row["ugc"].strip(), "vtec_year": row["vtec_year"].strip(), "issue": issue,
                    "expire": expire, "gtype": row["gtype"].strip()})
    return {"rows": out, "short": short, "malformed": malformed}


def _zip_members(data: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None
    members = {}
    for name in zf.namelist():
        stem, ext = os.path.splitext(name)
        if ext.lower() in (".shp", ".dbf", ".shx"):
            members[ext.lower()] = zf.read(name)
    if set(members) != {".shp", ".dbf", ".shx"}:
        raise JoinsError(WORDS_JOINS["reason_format"])
    return members


def _shape_reader(members: dict):
    try:
        import shapefile                    # pyshp: the daily job and tests only (no site build import)
    except ImportError:
        raise JoinsError("the shapefile reader is not installed") from None
    try:
        return shapefile.Reader(shp=io.BytesIO(members[".shp"]), dbf=io.BytesIO(members[".dbf"]),
                                shx=io.BytesIO(members[".shx"]))
    except Exception:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None


def _rings(shape) -> list:
    points = shape.points
    if not points:
        return []
    bounds = list(shape.parts) + [len(points)]
    out = []
    for i in range(len(bounds) - 1):
        ring = points[bounds[i]:bounds[i + 1]]
        if len(ring) >= 3:
            out.append(ring)
    return out


def parse_ww_shapefile(data: bytes) -> dict:
    """The issuance polygons of one IEM watchwarn shapefile (a zip): {"events": [...], "no_outline": n}. Keeps NEW
    polygons (the issuance, not a continuation), skips county twins (GTYPE C) and EXP rows; POLY_BEG and POLY_END are
    UTC YYYYMMDDHHMM. A NEW polygon with no outline cannot be tied to a spot, so it is counted and shown as such."""
    members = _zip_members(data)
    reader = _shape_reader(members)
    fields = [f[0] for f in reader.fields[1:]]
    need = {"WFO", "PHENOM", "GTYPE", "STATUS", "ETN", "POLY_BEG", "POLY_END", "HAILTAG", "WINDTAG",
            "TORNTAG", "DAMAGTAG", "VTEC_YR"}
    if not need <= set(fields):
        raise JoinsError(WORDS_JOINS["reason_format"])
    out, no_outline, malformed = [], 0, 0
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        if _s(rec["GTYPE"]) != "P" or _s(rec["STATUS"]) != "NEW":
            continue
        try:                                         # D21: a row with a bad time or tag is skipped and counted
            beg = datetime.strptime(_s(rec["POLY_BEG"]), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            end = datetime.strptime(_s(rec["POLY_END"]), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            hail_tag = _s(rec["HAILTAG"])
            wind_tag = _s(rec["WINDTAG"])
            hail_in = _float(hail_tag, "HAILTAG") if hail_tag else None
            wind_mph = _float(wind_tag, "WINDTAG") if wind_tag else None
        except (ValueError, JoinsError):
            malformed += 1
            continue
        rings = _rings(sr.shape)
        if not rings:
            no_outline += 1
            continue
        out.append({
            "k": _s(rec["PHENOM"]), "b": beg, "e": end, "o": _s(rec["WFO"]),
            "eventid": _s(rec["ETN"]), "vtec_year": _s(rec["VTEC_YR"]),
            "hail_in": hail_in, "wind_mph": wind_mph,
            "tornado": _s(rec["TORNTAG"]) or None, "damage": _s(rec["DAMAGTAG"]) or None,
            "rings": [[(float(x), float(y)) for x, y in ring] for ring in rings],
        })
    return {"events": out, "no_outline": no_outline, "malformed": malformed}


def _s(value) -> str:
    """A DBF field as text; a blank (None) field is the empty string, never "None"."""
    return "" if value is None else str(value).strip()


def check_ww_shapefile(data: bytes) -> None:
    """Content check for a download: the zip holds the shapefile and its fields are the archive's."""
    reader = _shape_reader(_zip_members(data))
    fields = {f[0] for f in reader.fields[1:]}
    if not {"WFO", "PHENOM", "GTYPE", "STATUS", "POLY_BEG", "POLY_END"} <= fields:
        raise JoinsError(WORDS_JOINS["reason_format"])


def parse_zone_map(data: bytes) -> list[dict]:
    """One edition of the NWS public forecast zones for Montana from its zone shapefile: the zone code (MTZ###), the
    name and the rings (lon, lat). Each edition carries its own codes; _edition_maps relates an older edition's codes
    to the current edition's zones (D16)."""
    members = _zip_members(data)
    reader = _shape_reader(members)
    fields = [f[0] for f in reader.fields[1:]]
    if not {"STATE", "ZONE", "NAME", "STATE_ZONE"} <= set(fields):
        raise JoinsError(WORDS_JOINS["reason_format"])
    out = []
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        if str(rec["STATE"]).strip() != "MT":
            continue
        code = "MTZ" + str(rec["ZONE"]).strip().zfill(3)
        rings = _rings(sr.shape)
        if not rings:
            raise JoinsError(WORDS_JOINS["reason_zone_map"])
        out.append({"zone": code, "name": " ".join(str(rec["NAME"]).split()),
                    "rings": [[(float(x), float(y)) for x, y in ring] for ring in rings]})
    if len(out) < 10:
        raise JoinsError(WORDS_JOINS["reason_zone_map"])
    out.sort(key=lambda z: z["zone"])
    return out


NWS_MONTHS = {"ja": 1, "fe": 2, "mr": 3, "ap": 4, "my": 5, "jn": 6, "jl": 7, "ag": 8, "se": 9, "oc": 10,
              "no": 11, "de": 12}


def zone_name_date(name: str) -> date:
    """The effective date of a public zone edition from its file name: the names carry the day, a two-letter month
    and the year (z_16ap26.zip is 16 April 2026, z_18mr25.zip is 18 March 2025). Raises JoinsError for any other name."""
    match = re.fullmatch(r"z_(\d{2})([a-z]{2})(\d{2})\.zip", name)
    if match is None or match.group(2) not in NWS_MONTHS:
        raise JoinsError(WORDS_JOINS["reason_format"])
    try:
        return date(2000 + int(match.group(3)), NWS_MONTHS[match.group(2)], int(match.group(1)))
    except ValueError:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None


def zone_zip_names(page: bytes) -> list[str]:
    """Every public zone edition the NWS GIS page links, oldest first (D16): each is read, so each product takes the
    zone code of the edition in force at its issue time. The last one is the current edition."""
    found = set()
    for stamp in re.findall(r"z_(\d{2}[a-z]{2}\d{2})\.zip", _text(page)):
        name = f"z_{stamp}.zip"
        try:
            found.add((zone_name_date(name), name))
        except JoinsError:
            continue
    if not found:
        raise JoinsError(WORDS_JOINS["reason_format"])
    return [name for _when, name in sorted(found)]


def zone_zip_name(page: bytes) -> str:
    """The current public zone edition on the NWS GIS page: the newest linked one (see zone_zip_names)."""
    return zone_zip_names(page)[-1]


def fire_zip_name(page: bytes) -> str:
    """The newest fire weather zone shapefile on the NWS fire zone page. The live names are fz16ap26.zip (the day,
    a two-letter month and the year; 16 April 2026), not fz_<ddmmyy>.zip as the brief first wrote them; the name is
    taken as the page links it."""
    best = None
    for match in set(re.findall(r"(fz_?\d{2}[a-z]{2}\d{2}\.zip)", _text(page))):
        digits = re.match(r"fz_?(\d{2})([a-z]{2})(\d{2})\.zip$", match)
        if digits is None:
            continue
        try:
            when = date(2000 + int(digits.group(3)), NWS_MONTHS[digits.group(2)], int(digits.group(1)))
        except (KeyError, ValueError):
            continue
        if best is None or when > best[0]:
            best = (when, match)
    if best is None:
        raise JoinsError(WORDS_JOINS["reason_format"])
    return best[1]


def check_fire_page(page: bytes) -> None:
    fire_zip_name(page)


def ncei_listing_names(page: bytes, years) -> dict:
    """The current NCEI details file for each requested year the listing has: the one with the newest creation
    stamp. A year with no file is left out, so only that year is missing (D10); a listing with no file for any
    requested year is not a listing and is refused."""
    text = _text(page)
    found: dict[int, tuple[str, str]] = {}
    for match in re.finditer(r"(StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz)", text):
        name, year, created = match.group(1), int(match.group(2)), match.group(3)
        if year not in found or created > found[year][1]:
            found[year] = (name, created)
    if not any(y in found for y in years):
        raise JoinsError(WORDS_JOINS["reason_format"])
    return {y: found[y][0] for y in years if y in found}


def check_listing(page: bytes) -> None:
    if b"StormEvents_details" not in page:
        raise JoinsError(WORDS_JOINS["reason_format"])


def check_zone_page(page: bytes) -> None:
    zone_zip_name(page)


# ---------------------------------------------------------------- geometry

def haversine_km(lat1, lon1, lat2, lon2):
    np = _np()
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass(deg: float) -> str:
    return COMPASS[int(((deg + 22.5) % 360.0) // 45.0)]


def points_in_rings(lon, lat, rings) -> "object":
    """Even-odd point-in-polygon for arrays of points against one or more rings (holes and parts alike)."""
    np = _np()
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    inside = np.zeros(lon.shape, dtype=bool)
    if lon.size == 0:
        return inside
    for ring in rings:
        arr = np.asarray(ring, dtype=float)
        if arr.shape[0] < 3:
            continue
        ax, ay = arr[:, 0], arr[:, 1]
        bx, by = np.roll(ax, -1), np.roll(ay, -1)
        for start in range(0, ax.size, 256):
            sx, sy = ax[start:start + 256], ay[start:start + 256]
            tx, ty = bx[start:start + 256], by[start:start + 256]
            cond = (sy[None, :] > lat[:, None]) != (ty[None, :] > lat[:, None])
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (tx - sx)[None, :] * (lat[:, None] - sy[None, :]) / (ty - sy)[None, :] + sx[None, :]
            hit = cond & (lon[:, None] < xint)
            inside ^= (hit.sum(axis=1) % 2) == 1
    return inside


def ring_bbox(rings) -> tuple[float, float, float, float]:
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def tile_bounds(tr: int, tc: int) -> tuple[float, float, float, float]:
    """(south, north, west, east) of a B1 tile: the outer edges of its 10 by 10 cells."""
    north = hail.cell_centre(10 * tr, 10 * tc)[0] + 0.005
    south = hail.cell_centre(10 * tr + 9, 10 * tc)[0] - 0.005
    west = hail.cell_centre(10 * tr, 10 * tc)[1] - 0.005
    east = hail.cell_centre(10 * tr, 10 * tc + 9)[1] + 0.005
    return south, north, west, east


def rect_distance_km(lat, lon, south, north, west, east):
    np = _np()
    clat = np.clip(lat, south, north)
    clon = np.clip(lon, west, east)
    return haversine_km(lat, lon, clat, clon)


def cover_hex(bits) -> str:
    """The 100-bit cover as 25 lower-case hex digits: bit k is cell key k (the key order of hail.cell_key)."""
    value = 0
    for key in bits:
        value |= 1 << int(key)
    return f"{value:025x}"


def cover_has(cover: str, key: int) -> bool:
    return bool((int(cover, 16) >> int(key)) & 1)


# ---------------------------------------------------------------- time

def montana_transitions(first_year: int, last_year: int) -> list:
    """[UTC instant, zone abbreviation] at every change of Montana's clock between the two years (inclusive)."""
    out, prev = [], None
    t = datetime(first_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(last_year + 1, 1, 1, tzinfo=timezone.utc)
    while t < end:
        abbr = t.astimezone(MONTANA_TZ).tzname()
        if abbr != prev:
            out.append([t.strftime("%Y-%m-%dT%H:%MZ"), abbr])
            prev = abbr
        t += timedelta(hours=1)
    return out


def _local(utc: datetime) -> datetime:
    return utc.astimezone(MONTANA_TZ)


def fmt_clock(utc: datetime) -> str:
    local = _local(utc)
    hour12 = local.hour % 12 or 12
    ampm = WORDS_JOINS["am"] if local.hour < 12 else WORDS_JOINS["pm"]
    return WORDS_JOINS["time"].format(hour=hour12, minute=f"{local.minute:02d}", ampm=ampm, zone=local.tzname())


def fmt_day(day: date) -> str:
    return hail.fmt_date(day)


def fmt_end(utc, begin) -> str:
    """The end of a span in Montana time: the clock alone on the begin's day, with its date when it falls later (and
    always with its date when there is no begin, D16). No end recorded reads as "end not recorded" (D6)."""
    if utc is None:
        return WORDS_JOINS["zones_end_unset"]
    if begin is not None and _local(utc).date() == _local(begin).date():
        return fmt_clock(utc)
    return f"{fmt_day(_local(utc).date())} {fmt_clock(utc)}"


def utc_from_row(d: int, t: int) -> datetime:
    """The UTC instant of a j/ row: day index d and time t as HHMM."""
    base = datetime(hail.D0.year, hail.D0.month, hail.D0.day, tzinfo=timezone.utc) + timedelta(days=int(d))
    return base + timedelta(hours=int(t) // 100, minutes=int(t) % 100)


def hhmm(utc: datetime) -> int:
    return utc.hour * 100 + utc.minute


def utc_day_index(utc: datetime) -> int:
    return (utc.date() - hail.D0).days


def iso_utc(utc: datetime) -> str:
    return utc.strftime("%Y-%m-%dT%H:%MZ")


def parse_iso_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def spc_day(utc: datetime) -> date:
    return (utc - timedelta(hours=12)).date()


# ---------------------------------------------------------------- the window and the pulls

def window_utc(index: dict) -> tuple[datetime, datetime, date, date]:
    """(first instant, end instant exclusive, first day, last day) of the B1 window."""
    first = date.fromisoformat(index["window"][0])
    last = date.fromisoformat(index["window"][1])
    start = datetime(first.year, first.month, first.day, 12, tzinfo=timezone.utc)
    end_day = last + timedelta(days=1)
    end = datetime(end_day.year, end_day.month, end_day.day, 12, tzinfo=timezone.utc)
    return start, end, first, last


def _months(first: date, last: date) -> list[date]:
    out = []
    cur = date(first.year, first.month, 1)
    while cur <= last:
        out.append(cur)
        cur = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)
    return out


def _next_month(day: date) -> date:
    return date(day.year + (day.month // 12), day.month % 12 + 1, 1)


def repull_due(month: date, today: date) -> bool:
    """True for the months re-pulled each day: the current month and the one before (REPULL_MONTHS)."""
    back = today.year * 12 + today.month - (REPULL_MONTHS - 1)
    return month.year * 12 + month.month >= back


def _lag_dates(ctx) -> dict:
    """The newest dates the lag sentences name: the newest NCEI event (its Montana local date), the newest detection
    (its SPC day, which is how detections are grouped) and the newest warning start (its Montana local date)."""
    return {
        "ncei": ctx.ncei_newest_local.date().isoformat() if ctx.ncei_newest_local else None,
        "swdi": spc_day(ctx.swdi_newest).isoformat() if ctx.swdi_newest else None,
        "warnings": _local(ctx.ww_newest).date().isoformat() if ctx.ww_newest else None,
    }


class Context:
    """Everything one build collects: the parsed sources, the parts, and the reasons for any part that did not load."""

    def __init__(self):
        self.lsr: list[dict] = []
        self.ncei_points: list[dict] = []
        self.ncei_zone_rows: list[dict] = []
        self.ncei_newest_local = None
        self.ncei_hail_by_year: dict[int, int] = {}
        self.ncei_files: dict[int, str] = {}
        self.swdi: list[dict] = []
        self.swdi_duplicates = 0
        self.swdi_newest = None
        self.ww_events: list[dict] = []
        self.ww_newest = None
        self.zone_rows: list[dict] = []
        self.zone_map: list[dict] = []
        self.zone_unmatched = 0
        self.zone_records_unmatched = 0
        self.stations: list[dict] = []
        self.station_days: dict[str, list] = {}
        self.station_missing = 0
        self.part_total: dict[str, int] = {p: 0 for p in PARTS}
        self.part_failures: dict[str, list[str]] = {p: [] for p in PARTS}
        self.part_reason: dict[str, str] = {}
        self.part_all_failed: dict[str, bool] = {p: False for p in PARTS}
        self.part_hard: dict[str, list[str]] = {p: [] for p in PARTS}    # the units that did not load at all
        self.short_rows: dict[str, int] = {"reports": 0, "records": 0, "zones": 0}     # D10: skipped, counted
        self.malformed: dict[str, int] = {p: 0 for p in PARTS}                       # D21: skipped, counted
        self.warnings_no_outline = 0                  # NEW polygons with no outline (rules-15)
        self.zone_can_midnight = 0                    # cancellation rows whose issue time is 00:00 UTC (data-2)
        self.zone_editions: list[dict] = []           # every public zone edition the NWS page links, oldest first (D16)
        self.zone_edition_maps: dict[str, dict] = {}  # an older edition's code -> the current code (None: no zone)
        self.zone_edition_report: list[dict] = []     # the index's record of each edition (D16, F-05)
        self.zone_products_unplaced = 0               # distinct in-window products no zone holds (D11)
        self.zone_products_renumbered = 0             # products placed under a code their edition renamed (D16)
        self.zone_products_fire_missing = 0           # red flag products when the fire zones did not load (D7)
        self.zone_records_renumbered = 0              # NCEI zone rows placed under a renamed code (D16)
        self.fire_map: list | None = None             # the fire weather zones (D7); None when they did not load
        self.fire_reason: str | None = None
        self.fire_events: dict[str, list] = {}        # fire zone code -> its red flag events in the window


def _take(result: Result, parser):
    """(parsed value, None) for a request that loaded and parsed; (None, reason words) otherwise."""
    if not result.ok:
        return None, result.reason or WORDS_JOINS["reason_no_answer"]
    try:
        return parser(result.data), None
    except JoinsError as exc:
        return None, str(exc) or WORDS_JOINS["reason_format"]


def _checker(parser):
    def check(data: bytes) -> None:
        parser(data)
    return check


def _refresh_year(year: int, today: date) -> bool:
    """D15: the current year's warnings, zone products and station days are re-pulled (fetched fresh, the cached copy
    used only when that fails); in January the previous year's too, since its last weeks are still being written."""
    return year >= today.year or (today.month == 1 and year == today.year - 1)


def _collect(fetcher: Fetcher, index: dict, today: date) -> Context:
    ctx = Context()
    start, end, first, last = window_utc(index)
    years = list(range(first.year, last.year + 1))
    months = _months(first, last + timedelta(days=1))

    page = fetcher.get("nws", NWS_GIS_URL, "nws/gis-page.html", refresh=True, check=check_zone_page)
    fire_page = fetcher.get("nws", NWS_FIRE_URL, "nws/fire-gis-page.html", refresh=True, check=check_fire_page)
    asos = fetcher.get("asos", ASOS_URL, "network/MT_ASOS.geojson", refresh=True,
                       check=_checker(parse_asos_rows))
    listing = fetcher.get("ncei", NCEI_DIR, "ncei/listing.html", refresh=True, check=check_listing)
    edition_names: list[str] = []
    if page.ok:
        edition_names, _why = _take(page, zone_zip_names)
        edition_names = edition_names or []
    zone_name = edition_names[-1] if edition_names else None     # the current edition: the newest linked (D16)
    fire_name, fire_why = _take(fire_page, fire_zip_name)
    # the listing is read whether or not it answered: _take gives the reason it did not (job-6, D10)
    ncei_names, listing_why = _take(listing, lambda d: ncei_listing_names(d, years))
    ncei_names = ncei_names or {}
    ctx.ncei_files = dict(ncei_names)
    stations: list[dict] = []
    if asos.ok:
        parsed_asos, _why = _take(asos, parse_asos_rows)
        parsed_asos = parsed_asos or {"stations": [], "malformed": 0}
        stations = parsed_asos["stations"]
        ctx.malformed["stations"] += parsed_asos["malformed"]
    ctx.stations = stations

    # 1. every request, concurrently (procs threads); each result is parsed below in one place
    jobs, tags = [], []

    def add(tag, fn):
        tags.append(tag)
        jobs.append(fn)

    for month in months:
        nxt = _next_month(month)
        a, b = max(month, first), min(nxt, last + timedelta(days=2))
        refresh = repull_due(month, today)
        params_lsr = {"state": "MT", "sts": f"{month.isoformat()}T00:00Z", "ets": f"{nxt.isoformat()}T00:00Z",
                      "fmt": "csv", "wfo": "ALL"}
        add(("reports", month), lambda m=month, p=params_lsr, r=refresh: fetcher.get(
            "lsr", LSR_URL, f"lsr/{m:%Y-%m}.csv", refresh=r, params=p, check=parse_lsr))
        swdi_url = SWDI_URL.format(start=a.strftime("%Y%m%d"), end=b.strftime("%Y%m%d")) + "?bbox=" + SWDI_BBOX
        add(("detections", month), lambda m=month, u=swdi_url, r=refresh: fetcher.get(
            "swdi", u, f"swdi/{m:%Y-%m}.csv", refresh=r, check=parse_swdi))
    for year in years:
        if year in ncei_names:
            add(("records", year), lambda n=ncei_names[year]: fetcher.get(
                "ncei", NCEI_DIR + n, f"ncei/{n}", check=_checker(parse_ncei)))
        for phen in WARNING_PHENOMENA:
            add(("warnings", (phen, year)), lambda ph=phen, y=year: fetcher.get(
                "ww", WW_URL, f"ww/{ph}-{y}.zip", refresh=_refresh_year(y, today),
                check=check_ww_shapefile, params=_ww_params(ph, "W", y, shapefile=True)))
        for phen, sig in ZONE_PRODUCTS:
            add(("zones", (phen, sig, year)), lambda ph=phen, sg=sig, y=year: fetcher.get(
                "zone_products", WW_URL, f"zones/{ph}{sg}-{y}.csv", refresh=_refresh_year(y, today),
                check=_checker(parse_ww_csv), params=_ww_params(ph, sg, y, shapefile=False)))
    for name in edition_names:          # every linked edition is read (D16); a file name is its own cache key
        add(("zone_map", name), lambda n=name: fetcher.get(
            "zone_map", NWS_BASE_URL + n, f"nws/{n}", check=_checker(parse_zone_map)))
    if fire_name is not None:
        add(("fire_map", fire_name), lambda n=fire_name: fetcher.get(
            "fire_zone_map", NWS_BASE_URL + n, f"nws/{n}", check=_checker(parse_zone_map)))
    for station in stations:
        for year in years:
            add(("stations", (station["id"], year)), lambda s=station, y=year: fetcher.get(
                "daily", DAILY_URL, f"daily/{s['id']}-{y}.csv", refresh=_refresh_year(y, today),
                check=_checker(parse_daily), params=_daily_params(s["id"], y)))
    results = fetcher.run([(lambda j=j: j()) for j in jobs])
    by_tag = dict(zip(tags, results))

    # 2. the parts: every unit is counted; a unit that did not load or parse is a failure with its reason
    def unit(part, label, value_or_none, why):
        ctx.part_total[part] += 1
        if value_or_none is None:
            ctx.part_failures[part].append(label)
            ctx.part_hard[part].append(label)
            ctx.part_reason.setdefault(part, why or WORDS_JOINS["reason_no_answer"])
            return False
        return True

    def stale(part, label, result):
        """A unit served from its cached copy after a failed re-pull: the part is partial, with the reason (D10)."""
        if result.state == "stale":
            ctx.part_failures[part].append(label)
            ctx.part_reason.setdefault(part, WORDS_JOINS["reason_stale"])

    for month in months:
        label = f"{month:%Y-%m}"
        parsed, why = _take(by_tag[("reports", month)], parse_lsr_rows)
        if unit("reports", label, parsed, why):
            stale("reports", label, by_tag[("reports", month)])
            ctx.short_rows["reports"] += parsed["short"]
            ctx.malformed["reports"] += parsed["malformed"]
            ctx.lsr.extend(r for r in parsed["rows"] if start <= r["utc"] < end)
        parsed, why = _take(by_tag[("detections", month)], parse_swdi)
        if unit("detections", label, parsed, why):
            stale("detections", label, by_tag[("detections", month)])
            ctx.malformed["detections"] += parsed["malformed"]
            ctx.swdi_duplicates += parsed["duplicates"]
            ctx.swdi.extend(r for r in parsed["rows"] if start <= r["utc"] < end)
            if parsed["newest"] is not None and (ctx.swdi_newest is None or parsed["newest"] > ctx.swdi_newest):
                ctx.swdi_newest = parsed["newest"]
    for year in years:
        label = str(year)
        if year not in ncei_names:
            why = WORDS_JOINS["reason_no_file_year"] if listing_why is None else listing_why
            unit("records", label, None, why)
            continue
        parsed, why = _take(by_tag[("records", year)], parse_ncei)
        if unit("records", label, parsed, why):
            stale("records", label, by_tag[("records", year)])
            ctx.short_rows["records"] += parsed["short"]
            ctx.malformed["records"] += parsed["malformed"]
            for r in parsed["points"]:
                if r["code"] == "hail":
                    ctx.ncei_hail_by_year[r["local_year"]] = ctx.ncei_hail_by_year.get(r["local_year"], 0) + 1
            ctx.ncei_points.extend(r for r in parsed["points"] if start <= r["utc"] < end)
            ctx.ncei_zone_rows.extend(r for r in parsed["zone_rows"] if start <= r["utc"] < end)
            newest = parsed["newest_local"]
            if newest is not None and (ctx.ncei_newest_local is None or newest > ctx.ncei_newest_local):
                ctx.ncei_newest_local = newest
    for year in years:
        for phen in WARNING_PHENOMENA:
            label = f"{phen} {year}"
            parsed, why = _take(by_tag[("warnings", (phen, year))], parse_ww_shapefile)
            if unit("warnings", label, parsed, why):
                stale("warnings", label, by_tag[("warnings", (phen, year))])
                ctx.warnings_no_outline += parsed["no_outline"]
                ctx.malformed["warnings"] += parsed["malformed"]
                for event in parsed["events"]:
                    if start <= event["b"] < end:
                        ctx.ww_events.append(event)
                    if ctx.ww_newest is None or event["b"] > ctx.ww_newest:
                        ctx.ww_newest = event["b"]
    for year in years:
        for phen, sig in ZONE_PRODUCTS:
            label = f"{phen} {year}"
            parsed, why = _take(by_tag[("zones", (phen, sig, year))], parse_ww_csv)
            if unit("zones", label, parsed, why):
                stale("zones", label, by_tag[("zones", (phen, sig, year))])
                ctx.short_rows["zones"] += parsed["short"]
                ctx.malformed["zones"] += parsed["malformed"]
                ctx.zone_rows.extend(dict(row, phen=phen, sig=sig) for row in parsed["rows"])
    for name in edition_names:
        zones, why = _take(by_tag[("zone_map", name)], parse_zone_map)
        ctx.zone_editions.append({"file": name, "date": zone_name_date(name), "zones": zones, "why": why})
    if zone_name is None:
        ctx.part_all_failed["zones"] = True
        ctx.part_reason["zones"] = WORDS_JOINS["reason_zone_map"]
    else:
        current = ctx.zone_editions[-1]
        if current["zones"] is None:
            ctx.part_all_failed["zones"] = True
            ctx.part_reason["zones"] = current["why"] or WORDS_JOINS["reason_zone_map"]
        else:
            ctx.zone_map = current["zones"]
    _edition_maps(ctx)
    if fire_name is None:
        ctx.fire_reason = fire_why or WORDS_JOINS["reason_zone_map"]
    else:
        fire, why = _take(by_tag[("fire_map", fire_name)], parse_zone_map)
        if fire is None:
            ctx.fire_reason = why or WORDS_JOINS["reason_zone_map"]
        else:
            ctx.fire_map = fire
    if not asos.ok or not stations:
        ctx.part_all_failed["stations"] = True
        ctx.part_reason["stations"] = (WORDS_JOINS["reason_no_answer"] if not asos.ok
                                       else WORDS_JOINS["reason_format"])
    for station in stations:
        for year in years:
            label = f"{station['id']} {year}"
            parsed, why = _take(by_tag[("stations", (station["id"], year))], parse_daily)
            if unit("stations", label, parsed, why):
                stale("stations", label, by_tag[("stations", (station["id"], year))])
                ctx.station_missing += parsed["missing"]
                ctx.malformed["stations"] += parsed["malformed"]
                ctx.station_days.setdefault(station["id"], []).extend(parsed["days"])
    # a part is unavailable only when every one of its units failed outright; a served-from-cache unit is partial
    for part in PARTS:
        failed = ctx.part_hard[part]
        if failed and len(failed) >= max(1, ctx.part_total[part]):
            ctx.part_all_failed[part] = True
    return ctx


def _ww_params(phen: str, sig: str, year: int, shapefile: bool) -> dict:
    params = {"simple": "1", "location_group": "states", "states[]": "MT", "timeopt": "1",
              "year1": str(year), "month1": "1", "day1": "1", "hour1": "0", "minute1": "0",
              "year2": str(year), "month2": "12", "day2": "31", "hour2": "23", "minute2": "59",
              "phenomena[]": phen, "significance[]": sig, "limitps": "1"}
    params["accept"] = "shapefile" if shapefile else "csv"
    return params


def _daily_params(sid: str, year: int) -> dict:
    return {"network": "MT_ASOS", "stations": sid, "year1": str(year), "month1": "1", "day1": "1",
            "year2": str(year), "month2": "12", "day2": "31", "var": "max_wind_gust_kts", "format": "comma"}


# ---------------------------------------------------------------- the joins

def load_tiles(store: Path, index: dict) -> list[dict]:
    """Each B1 tile with its Montana cell keys (the shard's state list): the cells the joins are made for."""
    tiles = []
    for name in index["tiles"]:
        tr, tc = int(name[1:5]), int(name[7:11])
        path = store / "hail" / "t" / f"{name}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        tiles.append({"name": name, "r": tr, "c": tc, "keys": [int(k) for k in doc.get("state", [])]})
    return tiles


def _montana_cells(tiles: list[dict]) -> list[tuple[int, int, float, float]]:
    out = []
    for tile in tiles:
        for key in tile["keys"]:
            row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
            lat, lon = hail.cell_centre(row, col)
            out.append((row, col, lat, lon))
    return out


def _nearest_edge_km(lat: float, lon: float, rings) -> float:
    """The distance in kilometres from a point to the nearest edge of the rings, on a flat map at the point's
    latitude (exact enough within a few kilometres of the point)."""
    np = _np()
    kx = 111.32 * math.cos(math.radians(lat))       # km per degree of longitude here
    ky = 110.574                                     # km per degree of latitude
    best = math.inf
    for ring in rings:
        arr = np.asarray(ring, dtype=float)
        if arr.shape[0] < 2:
            continue
        x = (arr[:, 0] - lon) * kx
        y = (arr[:, 1] - lat) * ky
        dx = np.roll(x, -1) - x
        dy = np.roll(y, -1) - y
        seg = dx * dx + dy * dy
        safe = np.where(seg > 0, seg, 1.0)
        t = np.where(seg > 0, np.clip((-x * dx - y * dy) / safe, 0.0, 1.0), 0.0)
        px, py = x + t * dx, y + t * dy
        best = min(best, float(np.sqrt(px * px + py * py).min()))
    return best


def assign_zones(cells, zone_map, near_km: float = ZONE_NEAR_KM) -> dict:
    """{(row, col): zone code} for every Montana cell whose centre lies inside one zone (the first zone in code order
    when two claim it). A cell no zone claims takes the code of the nearest zone whose edge is within near_km (D8);
    a cell farther than that stays unassigned. near_km of 0 turns the nearest rule off (the fire zones)."""
    np = _np()
    if not cells or not zone_map:
        return {}
    lat = np.array([c[2] for c in cells])
    lon = np.array([c[3] for c in cells])
    assigned = np.full(len(cells), -1)
    for zi, zone in enumerate(zone_map):
        minx, miny, maxx, maxy = ring_bbox(zone["rings"])
        cand = np.nonzero((lon >= minx) & (lon <= maxx) & (lat >= miny) & (lat <= maxy) & (assigned < 0))[0]
        if cand.size == 0:
            continue
        inside = points_in_rings(lon[cand], lat[cand], zone["rings"])
        assigned[cand[inside]] = zi
    if near_km > 0:
        boxes = [ring_bbox(zone["rings"]) for zone in zone_map]
        for idx in np.nonzero(assigned < 0)[0]:
            clat, clon = float(lat[idx]), float(lon[idx])
            best, best_zi = near_km, -1
            for zi, (minx, miny, maxx, maxy) in enumerate(boxes):
                gap_lat = max(miny - clat, 0.0, clat - maxy) * 110.574
                gap_lon = max(minx - clon, 0.0, clon - maxx) * 111.32 * math.cos(math.radians(clat))
                if math.hypot(gap_lat, gap_lon) > near_km:
                    continue
                dist = _nearest_edge_km(clat, clon, zone_map[zi]["rings"])
                if dist < best:
                    best, best_zi = dist, zi
            if best_zi >= 0:
                assigned[idx] = best_zi
    out = {}
    for idx in np.nonzero(assigned >= 0)[0]:
        row, col = cells[idx][0], cells[idx][1]
        out[(row, col)] = zone_map[int(assigned[idx])]["zone"]
    return out


def _station_near(stations: list[dict], lat: float, lon: float) -> list[dict]:
    """The two nearest stations within STATION_MILES of (lat, lon), nearest first."""
    if not stations:
        return []
    np = _np()
    dist = haversine_km(lat, lon, np.array([s["lat"] for s in stations]), np.array([s["lon"] for s in stations]))
    order = sorted(range(len(stations)), key=lambda i: (float(dist[i]), stations[i]["id"]))
    out = []
    for i in order:
        miles = float(dist[i]) / MILE_KM
        if miles > STATION_MILES:
            break
        out.append({"id": stations[i]["id"], "name": stations[i]["name"], "lat": stations[i]["lat"],
                    "lon": stations[i]["lon"], "miles": round(miles, 1)})
        if len(out) == 2:
            break
    return out


def _report_entry(row: dict, utc: datetime, record: bool) -> list:
    d = utc_day_index(utc)
    t = hhmm(utc)
    lat = None if row["lat"] is None else round(row["lat"], 5)
    lon = None if row["lon"] is None else round(row["lon"], 5)
    base = [d, t, lat, lon, row["code"], row["mag_text"], row["unit"], row["qual"], row["src"], row["city"],
            row["remark"]]
    if record:
        base += [row.get("mag_mph"), row.get("mag_kt")]
    return base


def _joins_for_tile(tile: dict, ctx: Context, prep: dict) -> dict:
    """One tile's file. A row is not repeated here: reports and records are indexes into the events table, and a
    warning is [index into the events table, the tile's 100-bit cover]. Detections (small) are written in full. The
    zone map lists each zone's cell keys."""
    np = _np()
    south, north, west, east = tile_bounds(tile["r"], tile["c"])
    doc = {"f": FORMAT, "r": tile["r"], "c": tile["c"], "d0": hail.D0.isoformat()}
    missing = {p: ctx.part_reason.get(p) or WORDS_JOINS["reason_no_answer"] for p in PARTS
               if ctx.part_all_failed.get(p)}
    partial = {p: ctx.part_failures[p] for p in PARTS if ctx.part_failures[p] and not ctx.part_all_failed.get(p)}
    if missing:
        doc["missing"] = missing
    if partial:
        doc["partial"] = partial
    report_table, record_table = prep["report_table"], prep["record_table"]
    warning_table = prep["warning_table"]

    refs = []
    rep = prep["report_arrays"]
    if rep["n"]:
        sel = np.nonzero((rep["lat"] >= south - 0.09) & (rep["lat"] <= north + 0.09)
                         & (rep["lon"] >= west - 0.12) & (rep["lon"] <= east + 0.12))[0]
        if sel.size:
            dist = rect_distance_km(rep["lat"][sel], rep["lon"][sel], south, north, west, east)
            refs = [ctx.lsr[int(i)]["ref"] for i in sel[dist <= REPORT_MILES * MILE_KM]]
    doc["reports"] = sorted(refs, key=lambda r: tuple(report_table[r][:5]))

    refs = []
    rec = prep["record_arrays"]
    if rec["n"]:
        sel = np.nonzero((rec["lat"] >= south - 0.09) & (rec["lat"] <= north + 0.09)
                         & (rec["lon"] >= west - 0.12) & (rec["lon"] <= east + 0.12))[0]
        if sel.size:
            dist = rect_distance_km(rec["lat"][sel], rec["lon"][sel], south, north, west, east)
            refs = [ctx.ncei_points[int(i)]["ref"] for i in sel[dist <= REPORT_MILES * MILE_KM]]
    doc["records"] = sorted(refs, key=lambda r: tuple(record_table[r][:5]))

    detections = []
    det = prep["detect_arrays"]
    if det["n"]:
        sel = np.nonzero((det["lat"] >= south - 0.05) & (det["lat"] <= north + 0.05)
                         & (det["lon"] >= west - 0.07) & (det["lon"] <= east + 0.07))[0]
        if sel.size:
            dist = rect_distance_km(det["lat"][sel], det["lon"][sel], south, north, west, east)
            for i in sel[dist <= DETECT_MILES * MILE_KM]:
                row = ctx.swdi[int(i)]
                utc = row["utc"]
                detections.append([utc_day_index(utc), hhmm(utc), round(row["lat"], 4), round(row["lon"], 4),
                                   row["size"]])
    doc["detections"] = sorted(detections, key=lambda r: (r[0], r[1], r[2], r[3]))

    keys_in_state = set(tile["keys"])
    warnings = []
    for idx in prep["warning_candidates"](south, north, west, east):
        event = ctx.ww_events[idx]
        bits = _tile_cover(event["rings"], tile)
        if not any(k in keys_in_state for k in bits):
            continue
        warnings.append([event["ref"], cover_hex(bits)])
    doc["warnings"] = sorted(warnings, key=lambda w: (warning_table[w[0]]["b"], warning_table[w[0]]["k"],
                                                      warning_table[w[0]]["o"]))

    by_zone: dict[str, list[int]] = {}
    zone_map = prep["zone_by_cell"]
    for key in tile["keys"]:
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        code = zone_map.get((row, col))
        if code:
            by_zone.setdefault(code, []).append(key)
    doc["zones"] = {code: sorted(keys) for code, keys in sorted(by_zone.items())}

    by_fire: dict[str, list[int]] = {}
    fire_by_cell = prep.get("fire_by_cell", {})
    for key in tile["keys"]:
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        code = fire_by_cell.get((row, col))
        if code:
            by_fire.setdefault(code, []).append(key)
    doc["fire"] = {code: sorted(keys) for code, keys in sorted(by_fire.items())}

    lat_c = (south + north) / 2
    lon_c = (west + east) / 2
    doc["stations"] = _station_near(ctx.stations, lat_c, lon_c)
    return doc



def _tile_cover(rings, tile) -> list[int]:
    """The keys (0 to 99) of the tile's cells whose centre lies inside the polygon."""
    np = _np()
    lats, lons, keys = [], [], []
    for key in range(100):
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        lat, lon = hail.cell_centre(row, col)
        lats.append(lat)
        lons.append(lon)
        keys.append(key)
    inside = points_in_rings(np.array(lons), np.array(lats), rings)
    return [keys[i] for i in range(100) if inside[i]]


def _warning_index(events: list[dict]):
    """A function that lists the indexes of warnings whose polygon bounding box overlaps a box."""
    np = _np()
    boxes = np.array([ring_bbox(e["rings"]) for e in events]) if events else np.zeros((0, 4))

    def candidates(south, north, west, east):
        if not events:
            return []
        hit = (boxes[:, 0] <= east) & (boxes[:, 2] >= west) & (boxes[:, 1] <= north) & (boxes[:, 3] >= south)
        return [int(i) for i in np.nonzero(hit)[0]]
    return candidates


def _prep(ctx: Context, tiles: list[dict]) -> dict:
    np = _np()
    lsr = ctx.lsr
    rep = {"n": len(lsr), "lat": np.array([r["lat"] for r in lsr]), "lon": np.array([r["lon"] for r in lsr])}
    order = np.argsort(rep["lat"], kind="stable") if rep["n"] else np.zeros(0, dtype=int)
    prep = {}
    lsr_order = [int(i) for i in order]
    ctx.lsr = [lsr[i] for i in lsr_order]
    rep = {"n": len(ctx.lsr), "lat": np.array([r["lat"] for r in ctx.lsr]),
           "lon": np.array([r["lon"] for r in ctx.lsr])}
    prep["report_arrays"] = rep
    pts = ctx.ncei_points
    rec = {"n": len(pts), "lat": np.array([r["lat"] for r in pts]), "lon": np.array([r["lon"] for r in pts])}
    prep["record_arrays"] = rec
    swdi = ctx.swdi
    det = {"n": len(swdi), "lat": np.array([r["lat"] for r in swdi]), "lon": np.array([r["lon"] for r in swdi])}
    prep["detect_arrays"] = det
    prep["warning_candidates"] = _warning_index(ctx.ww_events)
    cells = _montana_cells(tiles)
    by_tile: dict[str, list] = {}
    for row, col, lat, lon in cells:
        by_tile.setdefault(hail.tile_name(row // 10, col // 10), []).append((row, col, lat, lon))
    prep["cells_by_tile"] = by_tile
    prep["cells"] = cells
    prep["zone_by_cell"] = assign_zones(cells, ctx.zone_map)
    prep["fire_by_cell"] = assign_zones(cells, ctx.fire_map, near_km=0.0) if ctx.fire_map else {}
    return prep


def _sorted_report_rows(ctx: Context):
    ctx.lsr.sort(key=lambda r: (r["utc"], r["lat"], r["lon"], r["code"]))
    ctx.ncei_points.sort(key=lambda r: (r["utc"], r["lat"], r["lon"], r["code"]))
    ctx.swdi.sort(key=lambda r: (r["utc"], r["lat"], r["lon"], r["size"]))
    ctx.ww_events.sort(key=lambda e: (e["b"], e["k"], e["o"], e["eventid"]))


def _outline_diff(a: dict, b: dict) -> float | None:
    """The largest difference in degrees between two zone outlines, vertex by vertex (each ring's vertices are sorted
    first, so where a ring starts does not matter), or None when their ring or vertex counts differ."""
    ra = sorted(sorted(ring) for ring in a["rings"])
    rb = sorted(sorted(ring) for ring in b["rings"])
    if len(ra) != len(rb):
        return None
    worst = 0.0
    for pa, pb in zip(ra, rb):
        if len(pa) != len(pb):
            return None
        for (x1, y1), (x2, y2) in zip(pa, pb):
            worst = max(worst, abs(x1 - x2), abs(y1 - y2))
    return worst


def _same_zone(old: dict, new: dict) -> bool:
    """True when two editions' zones are the same zone: the same name (after _norm_zone_name) and the same outline
    within ZONE_SAME_DEG."""
    diff = _outline_diff(old, new)
    return diff is not None and diff <= ZONE_SAME_DEG and _norm_zone_name(old["name"]) == _norm_zone_name(new["name"])


def _map_edition(old: list[dict], current: list[dict]) -> tuple[dict, dict]:
    """(code map, record) for one older edition against the current edition (D16). A zone keeps its code when the
    current edition has the same zone under it; otherwise it maps to the one current zone with the same name and
    outline, and to None when there is no such zone or more than one. The record counts the codes that are the same
    and the largest outline difference among them (F-05: the 2025 and 2026 editions agree)."""
    by_code = {z["zone"]: z for z in current}
    mapping: dict[str, str | None] = {}
    renamed: dict[str, str | None] = {}
    same, worst = 0, 0.0
    for zone in old:
        code = zone["zone"]
        twin = by_code.get(code)
        if twin is not None and _same_zone(zone, twin):
            mapping[code] = code
            same += 1
            worst = max(worst, _outline_diff(zone, twin) or 0.0)
            continue
        found = [z["zone"] for z in current if _same_zone(zone, z)]
        mapping[code] = found[0] if len(found) == 1 else None
        renamed[code] = mapping[code]
    return mapping, {"same_codes": same, "renamed": renamed, "geometry_max_diff_deg": worst}


def _edition_maps(ctx: Context) -> None:
    """Fill ctx.zone_edition_maps and ctx.zone_edition_report from ctx.zone_editions (D16). The current edition is the
    last one. Each older edition that loaded is compared with it; one that did not load keeps its codes as they are,
    and the index says it was not read."""
    current = ctx.zone_editions[-1] if ctx.zone_editions else None
    report = []
    for ed in ctx.zone_editions:
        rec = {"file": ed["file"], "effective": ed["date"].isoformat(), "current": ed is current}
        if ed["zones"] is None:
            rec.update({"read": False, "reason": ed["why"] or WORDS_JOINS["reason_no_answer"]})
        else:
            rec.update({"read": True, "zones": len(ed["zones"])})
            if ed is not current and current is not None and current["zones"] is not None:
                mapping, detail = _map_edition(ed["zones"], current["zones"])
                ctx.zone_edition_maps[ed["file"]] = mapping
                rec.update(detail)
        report.append(rec)
    ctx.zone_edition_report = report


def _edition_in_force(editions: list[dict], day: date) -> dict | None:
    """The edition in force on a day (D16): the newest whose effective date is on or before it. A day before the
    oldest linked edition takes the oldest, since the NWS page links no earlier edition."""
    if not editions:
        return None
    chosen = editions[0]
    for ed in editions:
        if ed["date"] <= day:
            chosen = ed
    return chosen


def _place_code(ctx: Context, names: set, code: str, issued: datetime) -> str | None:
    """The current zone a row filed under code places on, given when it was issued (D16): the edition in force on the
    issue day (Montana time) maps the code; the current edition keeps it, and an edition that did not load keeps it
    too. None when the current edition holds no zone for it."""
    edition = _edition_in_force(ctx.zone_editions, _local(issued).date())
    mapping = None
    if edition is not None and ctx.zone_editions and edition is not ctx.zone_editions[-1]:
        mapping = ctx.zone_edition_maps.get(edition["file"])
    mapped = code if mapping is None else mapping.get(code)
    return mapped if mapped in names else None


def _zone_events(ctx: Context, start: datetime, end: datetime) -> dict:
    """{zone code: [event dicts]} for the IEM zone products in the window, one event per VTEC event (D30).

    The group key is (zone, phenomenon, significance, issuing office, event number, year). That is the VTEC event's
    identity: the office assigns the event number, so the key keeps the office. The key holds no issue time, so rows
    with other issue times (CON, EXT, EXA, EXB, UPG, EXP, CAN) are updates of their event, never new events; D30
    withdraws D25's split by issue time. In the cache no event (zone, phenomenon, significance, event number and year)
    has rows from two offices, so the office never splits an event, and 21 groups carry more than one issue time (their
    other-issue rows are updates).
    Known limit (DECISIONS D35, open items 15 and 16): an event number that NWS re-used for separate periods in one zone
    is one group, so its periods read as one span, and a period outside that span (after the earliest cancellation or
    upgrade) is not listed. Four zones in five years do this: MTZ004 WS 2024 event 1 (a CON on 11 January after a CAN on
    10 January is not shown), MTZ302 HW 2022 event 38 (its second cancelled period is not shown), MTZ320 WS 2023 event 4
    (the expiry period after the cancellation is not shown) and MTZ003 WS 2021 event 12 (its two periods are in one
    span). A broader check (a row issued after the group's earliest end) flags 19 groups in the window; B5's period rule
    (D33) covers them all.

    A product goes to its public zone (_place_code, D16); a red flag warning (FW) goes to its fire weather zone (D7). A
    product is counted, not placed (D11), when no current zone holds its code, or a red flag warning when the fire
    zones did not load. The span begins at the earliest issue time of the event's NEW and CON rows (D25). Most events
    have no NEW or CON row in the archive (the zone rows are mostly CAN and EXP), and every row of a group with a NEW
    row carries that group's issue time (the 110 zone groups with a NEW row, 69 public and 41 fire weather, and 113 NEW
    rows in the cache for the ten products), so an event without a NEW or CON row begins at the earliest issue time of
    its rows.

    It ends at the earliest cancellation (CAN) or upgrade (UPG) time (D26, D31). A cancellation's expire is the
    cancellation time, and an upgrade's expire is the time the lower event was upgraded (NWS Instruction 10-1703). The
    status of the row that sets the end is kept as "st" ("cancelled" or "upgraded"); a tie reads as cancelled. Without
    either, the end is the latest expiry of the other rows. A cancellation or upgrade time is the end even when it is
    not after the begin (D26); otherwise the end is null ("end not recorded") when no expiry is after the begin (D6).
    The window takes an event by its begin. Fire zone events go to ctx.fire_events."""
    zone_names = {z["zone"] for z in ctx.zone_map}
    fire_names = None if ctx.fire_map is None else {z["zone"] for z in ctx.fire_map}
    grouped: dict[tuple, dict] = {}
    for row in ctx.zone_rows:
        if row["gtype"] not in ("C", "Z", "P", ""):
            continue
        if not row["ugc"].startswith("MTZ"):
            continue
        key = (row["ugc"], row["phen"], row["sig"], row["wfo"], row["eventid"], row["vtec_year"])     # D30
        item = grouped.setdefault(key, {"issue": None, "start": None, "stop_end": None, "stop_status": None,
                                        "live_end": None})
        status, issue, expire = row["status"], row["issue"], row["expire"]
        if issue is not None and (item["issue"] is None or issue < item["issue"]):
            item["issue"] = issue
        if status in ("NEW", "CON") and issue is not None and (item["start"] is None or issue < item["start"]):
            item["start"] = issue
        if status in ZONE_STOP_STATE:       # D26, D31: a cancellation or an upgrade ends the event at its time
            earlier = item["stop_end"] is None or expire < item["stop_end"]
            tie_cancel = expire == item["stop_end"] and status == "CAN"     # a tie reads as cancelled
            if earlier or tie_cancel:
                item["stop_end"], item["stop_status"] = expire, status
        elif item["live_end"] is None or expire > item["live_end"]:
            item["live_end"] = expire
        if status == "CAN" and issue is not None and start <= issue < end and (issue.hour, issue.minute) == (0, 0):
            ctx.zone_can_midnight += 1
        if issue is not None and start <= issue < end:
            if row["phen"] != "FW" and _place_code(ctx, zone_names, row["ugc"], issue) is None:
                ctx.zone_unmatched += 1
            elif row["phen"] == "FW" and fire_names is not None and row["ugc"] not in fire_names:
                ctx.zone_unmatched += 1
    out: dict[str, list] = {}
    fire: dict[str, list] = {}
    unplaced, fire_missing = set(), set()
    renumbered = 0
    for key, item in grouped.items():
        zone, phen, sig, wfo, _eid, _yr = key
        begin = item["start"] if item["start"] is not None else item["issue"]
        if begin is None or not (start <= begin < end):
            continue
        end_at = item["stop_end"] if item["stop_end"] is not None else item["live_end"]
        # D26: a cancellation or upgrade time is the end even when it is not after the begin; a live expiry is not (D6)
        if item["stop_end"] is None and end_at is not None and end_at <= begin:
            end_at = None
        event = {"k": phen, "s": sig, "b": iso_utc(begin), "e": None if end_at is None else iso_utc(end_at), "o": wfo}
        if item["stop_status"] is not None:
            event["st"] = ZONE_STOP_STATE[item["stop_status"]]
        if phen == "FW":
            if fire_names is None:
                fire_missing.add(key)
            elif zone in fire_names:
                fire.setdefault(zone, []).append(event)
            else:
                unplaced.add(key)
            continue
        code = _place_code(ctx, zone_names, zone, begin)
        if code is None:
            unplaced.add(key)
            continue
        if code != zone:
            renumbered += 1
        out.setdefault(code, []).append(event)
    for group in (out, fire):
        for zone in group:
            group[zone].sort(key=lambda e: (e["b"], e["k"], e["o"]))
    ctx.zone_products_unplaced = len(unplaced)
    ctx.zone_products_renumbered = renumbered
    ctx.zone_products_fire_missing = len(fire_missing)
    ctx.fire_events = fire
    return out


def _zone_records(ctx: Context, start: datetime, end: datetime) -> dict:
    """{zone code: [rows]} for the NCEI zone-coded rows in the window. A row is placed on the current zone its
    edition's code maps to (_place_code, D16); a row no current zone holds is counted as unplaced (D11)."""
    zone_names = {z["zone"] for z in ctx.zone_map}
    out: dict[str, list] = {}
    unmatched = renumbered = 0
    for row in ctx.ncei_zone_rows:
        code = _place_code(ctx, zone_names, row["zone"], row["utc"])
        if code is None:
            unmatched += 1
            continue
        if code != row["zone"]:
            renumbered += 1
        out.setdefault(code, []).append(_report_entry(row, row["utc"], True))
    for zone in out:
        out[zone].sort(key=lambda r: (r[0], r[1], r[4], r[8]))
    ctx.zone_records_unmatched = unmatched
    ctx.zone_records_renumbered = renumbered
    return out


def build(store_dir, cache_dir=None, procs: int = 4, today=None, fetcher: Fetcher | None = None,
          max_age_s: float = MAX_AGE_S, log=_say, offline: bool = False) -> dict:
    """Build the joins into store_dir (a store with hail/index.json and its shards): pull (the re-pull windows fresh,
    D15; the rest from the cache), parse, write the events table (hail/j/events.json: every report, record and warning
    once), join each B1 tile (its file refers to the events by index), write z/ and s/, extend the index and the
    manifest. offline=True makes no request at all: the cache is the only input, so two offline builds from the same
    cache are byte-identical. A source that fails leaves its part unavailable or partial, never silently empty.
    Returns the index's joins block."""
    t0 = time.time()
    root = Path(store_dir)
    hail.check_manifest(root)
    index = hail.load_index(root)
    today = today or _utc_now().date()
    start, end, first, last = window_utc(index)
    if cache_dir is None:
        cache_dir = Path(".joins-cache")
    fetcher = fetcher or Fetcher(cache_dir, root / "ledger" / "joins.jsonl", procs=procs, max_age_s=max_age_s,
                                 deadline_s=JOINS_DEADLINE_S, offline=offline)
    log(f"joins: window {first} to {last}; {len(index['tiles'])} tiles; today {today}")
    tiles = load_tiles(root, index)
    ctx = _collect(fetcher, index, today)
    log(f"joins: pulled and parsed ({time.time() - t0:.0f} s); {len(ctx.lsr)} report rows, "
        f"{len(ctx.ncei_points)} record rows, {len(ctx.swdi)} detections, {len(ctx.ww_events)} warning events")
    _sorted_report_rows(ctx)
    prep = _prep(ctx, tiles)
    zone_events = _zone_events(ctx, start, end)
    zone_records = _zone_records(ctx, start, end)
    log(f"joins: zones assigned to {len(prep['zone_by_cell'])} of {len(prep['cells'])} Montana cells")

    report_table = []
    for i, row in enumerate(ctx.lsr):
        row["ref"] = i
        report_table.append(_report_entry(row, row["utc"], False))
    record_table = []
    for i, row in enumerate(ctx.ncei_points):
        row["ref"] = i
        record_table.append(_report_entry(row, row["utc"], True))
    warning_table = []
    for i, event in enumerate(ctx.ww_events):
        event["ref"] = i
        warning_table.append({"k": event["k"], "b": iso_utc(event["b"]), "e": iso_utc(event["e"]), "o": event["o"],
                              "tags": {"hail_in": event["hail_in"], "wind_mph": event["wind_mph"],
                                       "tornado": event["tornado"], "damage": event["damage"]}})
    prep["report_table"], prep["record_table"], prep["warning_table"] = report_table, record_table, warning_table
    events_bytes = _compact({"f": EVENTS_FORMAT, "d0": hail.D0.isoformat(), "reports": report_table,
                             "records": record_table, "warnings": warning_table})

    stage = Path(tempfile.mkdtemp(prefix=".joins-stage-", dir=str(root)))
    try:
        hail_dir = stage / "hail"
        for sub in ("j", "z", "s"):
            (hail_dir / sub).mkdir(parents=True)
        (hail_dir / "j" / EVENTS_NAME).write_bytes(events_bytes)
        tile_bytes = 0
        largest = (0, "")
        totals = {"reports": 0, "records": 0, "detections": 0, "warnings": 0, "tiles_with_warnings": 0}
        for tile in tiles:
            doc = _joins_for_tile(tile, ctx, prep)
            data = _compact(doc)
            name = f"{tile['name']}.json"
            (hail_dir / "j" / name).write_bytes(data)
            tile_bytes += len(data)
            if len(data) > largest[0]:
                largest = (len(data), name)
            totals["reports"] += len(doc["reports"])
            totals["records"] += len(doc["records"])
            totals["detections"] += len(doc["detections"])
            totals["warnings"] += len(doc["warnings"])
            totals["tiles_with_warnings"] += 1 if doc["warnings"] else 0
        log(f"joins: wrote {len(tiles)} tile files ({tile_bytes} bytes; largest {largest[1]} {largest[0]} bytes) "
            f"and the events table ({len(events_bytes)} bytes)")

        zone_list = [z["zone"] for z in ctx.zone_map]
        z_bytes = 0
        for zone in ctx.zone_map:
            doc = {"f": ZONE_FORMAT, "zone": zone["zone"], "name": zone["name"],
                   "events": zone_events.get(zone["zone"], []), "records": zone_records.get(zone["zone"], [])}
            data = _compact(doc)
            (hail_dir / "z" / f"{zone['zone']}.json").write_bytes(data)
            z_bytes += len(data)
        for zone in ctx.fire_map or []:
            doc = {"f": ZONE_FORMAT, "kind": "fire", "zone": zone["zone"], "name": zone["name"],
                   "events": ctx.fire_events.get(zone["zone"], []), "records": []}
            data = _compact(doc)
            (hail_dir / "z" / f"fire-{zone['zone']}.json").write_bytes(data)
            z_bytes += len(data)

        s_bytes = 0
        station_days_total = 0
        station_dropped = 0
        station_index = []
        for st in ctx.stations:
            days = []
            dropped = 0
            for day, kt in sorted(ctx.station_days.get(st["id"], []), key=lambda x: x[0]):
                if not (first <= day <= last):
                    continue
                kind = station_day_kind(kt)
                if kind == "dropped":
                    dropped += 1
                elif kind == "keep":
                    days.append(station_day_row(day, kt))
            station_dropped += dropped
            station_days_total += len(days)
            doc = {"f": STATION_FORMAT, "id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                   "days": days, "dropped": dropped}
            data = _compact(doc)
            (hail_dir / "s" / f"{st['id']}.json").write_bytes(data)
            s_bytes += len(data)
            station_index.append({"id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                                  "archive_end": st["archive_end"]})
        all_station_years: dict[int, int] = {}
        for rows in ctx.station_days.values():
            for day, kt in rows:
                if kt >= STATION_KT:
                    all_station_years[day.year] = all_station_years.get(day.year, 0) + 1

        counts = _counts(ctx, zone_events, first, last, start, end)
        block = _index_block(ctx, index, tiles, zone_list, station_index, totals,
                             {"tiles": tile_bytes, "events": len(events_bytes), "z": z_bytes, "s": s_bytes},
                             station_days_total, station_dropped, counts, all_station_years, today, fetcher, t0,
                             {"reports": len(report_table), "records": len(record_table),
                              "warnings": len(warning_table)})
        new_index = dict(index)
        new_index[INDEX_KEY] = block
        (hail_dir / "index.json").write_bytes(_pretty(new_index))
        _finish_manifest(root, stage, block)
        for sub in ("j", "z", "s"):
            target = root / "hail" / sub
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(hail_dir / sub), str(target))
        shutil.move(str(hail_dir / "index.json"), str(root / "hail" / "index.json"))
        shutil.move(str(hail_dir / "manifest.json"), str(root / "hail" / "manifest.json"))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    hail.check_manifest(root)
    log(f"joins: done in {time.time() - t0:.0f} s")
    return block



def _counts(ctx: Context, zone_events, first: date, last: date, start: datetime, end: datetime) -> dict:
    lsr_h = sum(1 for r in ctx.lsr if r["code"] == "H")
    lsr_g = sum(1 for r in ctx.lsr if r["code"] == "G")
    polygon = _montana_polygon()
    swdi_mt = None
    if polygon is not None and ctx.swdi:
        np = _np()
        lat = np.array([r["lat"] for r in ctx.swdi])
        lon = np.array([r["lon"] for r in ctx.swdi])
        swdi_mt = int(points_in_rings(lon, lat, polygon).sum())
    sv = sum(1 for e in ctx.ww_events if e["k"] == "SV")
    to = sum(1 for e in ctx.ww_events if e["k"] == "TO")
    ff = sum(1 for e in ctx.ww_events if e["k"] == "FF")
    return {"lsr_hail": lsr_h, "lsr_g": lsr_g,
            "ncei_hail_by_year": {str(k): v for k, v in sorted(ctx.ncei_hail_by_year.items())},
            "swdi_rows": len(ctx.swdi), "swdi_montana_polygon": swdi_mt,
            "sv_events": sv, "to_events": to, "ff_events": ff,
            "zone_events": sum(len(v) for v in zone_events.values()),
            "lsr_rows": len(ctx.lsr), "ncei_point_rows": len(ctx.ncei_points),
            "ncei_zone_rows": len(ctx.ncei_zone_rows)}



def _montana_polygon():
    """The Montana outline rings (lon, lat) from B1's basemap ring (hail.py), for the SWDI count against the
    research's Montana-polygon count."""
    try:
        ring = hail._montana_ring()
    except Exception:
        return None
    return [list(ring)]


def _index_block(ctx, index, tiles, zone_list, station_index, totals, bytes_by, station_days, station_dropped,
                 counts, all_station_years, today, fetcher, t0, events_counts) -> dict:
    parts = {}
    reasons = {}
    for part in PARTS:
        if ctx.part_all_failed.get(part):
            parts[part] = "unavailable"
            reasons[part] = ctx.part_reason.get(part) or WORDS_JOINS["reason_no_answer"]
        elif ctx.part_failures.get(part):
            parts[part] = "partial"
            reasons[part] = ctx.part_reason.get(part) or WORDS_JOINS["reason_no_answer"]
        else:
            parts[part] = "loaded"
    state = "loaded"
    if any(v == "unavailable" for v in parts.values()):
        state = "unavailable" if all(v == "unavailable" for v in parts.values()) else "partial"
    elif any(v == "partial" for v in parts.values()):
        state = "partial"
    first_utc, last_utc = window_utc(index)[0], window_utc(index)[1]
    total = bytes_by["tiles"] + bytes_by["events"] + bytes_by["z"] + bytes_by["s"]
    newest_ncei = _lag_dates(ctx)["ncei"]
    fire_list = sorted(z["zone"] for z in ctx.fire_map) if ctx.fire_map is not None else []
    win_first, win_last = window_utc(index)[2], window_utc(index)[3]
    repull = {"months": [m.isoformat() for m in _months(win_first, win_last + timedelta(days=1))
                         if repull_due(m, today)],
              "years": [y for y in range(win_first.year, win_last.year + 1) if _refresh_year(y, today)]}
    return {
        "format": FORMAT,
        "events_format": EVENTS_FORMAT,
        "built_at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_seconds": round(time.time() - t0, 1),
        "as_of": index["as_of"],
        "window": list(index["window"]),
        "sample": False,
        "state": state,
        "parts": parts,
        "reasons": reasons,
        "partial": {p: ctx.part_failures[p] for p in PARTS if ctx.part_failures[p]},
        "lags": _lag_dates(ctx),
        "types": _type_legend([(r["code"], r["type"]) for r in ctx.lsr]),
        "lsr_rows": counts["lsr_rows"],
        "ncei_rows": counts["ncei_point_rows"],
        "ncei_zone_rows": counts["ncei_zone_rows"],
        "ncei_zone_rows_unmatched": ctx.zone_records_unmatched,
        "ncei_zone_rows_renumbered": ctx.zone_records_renumbered,
        "ncei_newest_event": newest_ncei,
        "ncei_files": {str(k): v for k, v in sorted(ctx.ncei_files.items())},
        "swdi_rows": counts["swdi_rows"],
        "swdi_montana_polygon": counts["swdi_montana_polygon"],
        "swdi_duplicates_dropped": ctx.swdi_duplicates,
        "warnings": {"SV": counts["sv_events"], "TO": counts["to_events"], "FF": counts["ff_events"]},
        "warnings_no_outline": ctx.warnings_no_outline,
        "zone_events": counts["zone_events"],
        "zone_rows_unmatched": ctx.zone_unmatched,
        "zone_products_unplaced": ctx.zone_products_unplaced,
        "zone_products_renumbered": ctx.zone_products_renumbered,
        "zone_editions": ctx.zone_edition_report,
        "zone_edition_cutover": ctx.zone_editions[-1]["date"].isoformat() if ctx.zone_editions else None,
        "malformed_rows": dict(ctx.malformed),
        "repull": repull,
        "offline": bool(fetcher.offline),
        "zone_products_fire_missing": ctx.zone_products_fire_missing,
        "zone_can_midnight_rows": ctx.zone_can_midnight,
        "zones": len(zone_list),
        "zone_list": zone_list,
        "zone_names": {z["zone"]: z["name"] for z in ctx.zone_map},
        "fire_zones": {"state": "unavailable" if ctx.fire_map is None else "loaded",
                       "reason": None if ctx.fire_map is not None else ctx.fire_reason,
                       "zones": len(fire_list), "events": sum(len(v) for v in ctx.fire_events.values())},
        "fire_zone_list": fire_list,
        "fire_zone_names": {z["zone"]: z["name"] for z in (ctx.fire_map or [])},
        "short_rows": dict(ctx.short_rows),
        "stations": len(station_index),
        "station_list": [s["id"] for s in station_index],
        "station_days": station_days,
        "station_dropped": station_dropped,
        "station_missing": ctx.station_missing,
        "station_days_by_year": {str(k): v for k, v in sorted(all_station_years.items())},
        "tiles": len(tiles),
        "tiles_with_warnings": totals["tiles_with_warnings"],
        "bytes": {"tiles": bytes_by["tiles"], "events": bytes_by["events"], "z": bytes_by["z"],
                  "s": bytes_by["s"], "total": total},
        "counts": {"reports": totals["reports"], "records": totals["records"],
                   "detections": totals["detections"], "warnings": totals["warnings"]},
        "events": events_counts,
        "compare": counts,
        "shapes": {"report": ["d", "t", "lat", "lon", "code", "mag_text", "unit", "qual", "src", "city", "remark"],
                   "record": ["d", "t", "lat", "lon", "code", "mag_text", "unit", "qual", "src", "city", "remark",
                              "mag_mph", "mag_kt"],
                   "warning": ["k", "b", "e", "o", "tags"],
                   "detection": ["d", "t", "lat", "lon", "size_hundredths_in"],
                   "station_day": ["d", "mph", "kt"]},
        "tile": {"reports": "indexes into events.reports, sorted by the row's first five fields",
                 "records": "indexes into events.records, sorted the same way",
                 "warnings": "[index into events.warnings, cover]",
                 "detections": "[d, t, lat, lon, size_hundredths_in]",
                 "zones": "{zone code: [cell keys]}",
                 "fire": "{fire weather zone code: [cell keys]}",
                 "stations": "[{id, name, lat, lon, miles}]"},
        "cover": "25 lower-case hex digits; bit k (the cell key 0 to 99) is set when the cell centre is inside",
        "montana_time": montana_transitions(first_utc.year - 1, last_utc.year + 1),
        "sources": {src: dict(row, **({"served_from_cache_since": fetcher.served_since[src]}
                                      if src in fetcher.served_since else {}))
                    for src, row in fetcher.stats.items()},
        "failures": fetcher.failures[:50],
        "failure_count": len(fetcher.failures),
    }



def _finish_manifest(root: Path, stage: Path, block: dict) -> None:
    """Write the staged manifest: B1's entries that remain, the new j, z and s files, and the staged index (which
    build() wrote into the stage before this call)."""
    old = json.loads((root / "hail" / "manifest.json").read_text(encoding="utf-8"))
    files = {rel: meta for rel, meta in old.get("files", {}).items()
             if not rel.startswith(("hail/j/", "hail/z/", "hail/s/", "hail/index.json"))}
    hail_stage = stage / "hail"
    for sub in ("j", "z", "s"):
        for path in sorted((hail_stage / sub).rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                files[path.relative_to(stage).as_posix()] = {
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    index_data = (hail_stage / "index.json").read_bytes()
    files["hail/index.json"] = {"bytes": len(index_data), "sha256": hashlib.sha256(index_data).hexdigest()}
    manifest = dict(old)
    manifest["files"] = {k: files[k] for k in sorted(files)}
    manifest[INDEX_KEY] = {"format": FORMAT, "tiles": block["tiles"], "zones": block["zones"],
                           "stations": block["stations"], "bytes": block["bytes"], "state": block["state"]}
    (hail_stage / "manifest.json").write_bytes(_pretty(manifest))


def load_joins_index(store_dir) -> dict:
    index = hail.load_index(store_dir)
    block = index.get(INDEX_KEY)
    if not isinstance(block, dict):
        raise JoinsError("the joins are not in this store")
    return index


def _read_j(store_dir, tile_name: str) -> dict:
    path = Path(store_dir) / "hail" / "j" / f"{tile_name}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise JoinsError(WORDS_JOINS["reason_no_answer"]) from None
    if doc.get("f") != FORMAT:
        raise JoinsError(WORDS_JOINS["reason_format"])
    return doc


def _read_z(store_dir, zone: str) -> dict | None:
    path = Path(store_dir) / "hail" / "z" / f"{zone}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_s(store_dir, sid: str) -> dict | None:
    path = Path(store_dir) / "hail" / "s" / f"{sid}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_part_file(store_dir, rel: str, fmt: str) -> dict:
    """A zone or station file as the town page reads it (D27): a JSON object of this format whose row lists are lists.
    Raises JoinsError when the file is missing or cannot be read (the source did not answer), or is not one (the file
    was in an unexpected format). _read_z and _read_s return None instead; the build's checks use those."""
    path = Path(store_dir) / "hail" / rel
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise JoinsError(WORDS_JOINS["reason_no_answer"]) from None
    except ValueError:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None
    rows_ok = isinstance(doc, dict) and all(isinstance(doc.get(k, []), list) for k in ("events", "records", "days"))
    if not rows_ok or doc.get("f") != fmt:
        raise JoinsError(WORDS_JOINS["reason_format"])
    return doc


def _section(id_: str, heading: str, what: str, kind: str) -> dict:
    """One section: lead (the count sentence; None when the part did not load), fire_lead (the zone section's second
    lead, for red flag warnings; None elsewhere), rows, lines (extra sentences), source and unavailable (D20)."""
    return {"id": id_, "heading": heading, "what": what, "kind": kind, "lead": None, "fire_lead": None, "rows": [],
            "lines": [], "source": None, "unavailable": None}


def _unavailable_text(feed_key: str, reason: str | None, partial_periods: list | None = None) -> str:
    """The sentence a part shows when it did not load (D20: exactly "{Part} could not be loaded in this update; that is
    not the same as no {one}.", the same words in the browser), or the partial sentence when some periods did not.
    feed_key is the part's key (reports, records, detections, warnings, zones, stations)."""
    if partial_periods:
        return WORDS_JOINS["partial"].format(feed=WORDS_JOINS[f"feed_{feed_key}"],
                                             periods=", ".join(partial_periods),
                                             reason=reason or WORDS_JOINS["reason_no_answer"])
    return WORDS_JOINS["unavailable"].format(part=WORDS_JOINS[f"part_{feed_key}"],
                                             one=WORDS_JOINS[f"one_{feed_key}"])


def _read_events(store_dir) -> dict | None:
    """The events table of a store (hail/j/events.json): every report, record and warning row once. None when the
    store has no table or it is not in its format."""
    if store_dir is None:
        return None
    try:
        doc = json.loads((Path(store_dir) / "hail" / "j" / EVENTS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("f") != EVENTS_FORMAT:
        return None
    return doc


def _zone_for_key(tile_doc: dict, key: int, field: str = "zones") -> str | None:
    """The zone whose cell keys include this key, from the tile's zone map ({zone code: [keys]}; field "fire" for
    the fire weather zones)."""
    for zone, keys in (tile_doc.get(field) or {}).items():
        if int(key) in keys:
            return zone
    return None


def describe_joins(index: dict, tile_doc: dict, cell_row: int, cell_col: int, now=None, sample: bool = False,
                   store_dir=None, events: dict | None = None) -> dict:
    """The six sections for one cell, filled in Python (the town pages; the browser fills the same templates).

    tile_doc is the cell's j/ file as read. The events table (hail/j/events.json) holds the report, record and
    warning rows the tile refers to; it is read from store_dir unless events is given. store_dir also gives the zone,
    fire zone and station files. Each section is a dict: id, heading, what (the kind's sentence), kind, lead, rows
    (text, and the remark of a report), lines (extra sentences), source, and unavailable (the Data unavailable words
    when the part did not load, or the partial words when some periods did not). Rows are newest first; each row
    starts with its kind label (D3)."""
    block = index[INDEX_KEY]
    start, end = date.fromisoformat(index["window"][0]), date.fromisoformat(index["window"][1])
    w = WORDS_JOINS
    centre_lat, centre_lon = hail.cell_centre(cell_row, cell_col)
    key = hail.cell_key(cell_row, cell_col)
    span = {"start": fmt_day(start), "end": fmt_day(end)}
    lags = block.get("lags", {})
    newest_ncei = _fmt_iso_date(lags.get("ncei"))
    newest_swdi = _fmt_iso_date(lags.get("swdi"))
    newest_ww = _fmt_iso_date(lags.get("warnings"))
    parts = block.get("parts", {})
    reasons = block.get("reasons", {})
    partial = block.get("partial", {})
    if events is None:
        events = _read_events(store_dir)
    types = block.get("types", {})
    zone = _zone_for_key(tile_doc, key)
    fire = _zone_for_key(tile_doc, key, "fire")
    fire_state = block.get("fire_zones", {}).get("state", "unavailable")
    out = {"sample": w["sample"] if sample else None, "as_of": index["as_of"], "sections": [],
           "times_note": w["times_note"]}
    ftn = {"start": span["start"], "end": span["end"]}

    # reports
    sec = _section("reports", w["reports_heading"], w["reports_what"], "report")
    sec["source"] = w["source_reports"]
    if parts.get("reports") == "unavailable":
        sec["unavailable"] = _unavailable_text("reports", reasons.get("reports"))
    elif events is None:
        sec["unavailable"] = _unavailable_text("reports", w["reason_events"])
    else:
        rows = []
        for ref in tile_doc.get("reports", []):
            r = events["reports"][ref]
            utc = utc_from_row(r[0], r[1])
            dist = haversine_km(centre_lat, centre_lon, r[2], r[3]) / MILE_KM
            if dist > REPORT_MILES:
                continue
            rows.append((utc, r, float(dist)))
        rows.sort(key=lambda x: x[0], reverse=True)
        sec["lead"] = _lead(rows, "reports", ftn, w)
        for utc, r, dist in rows:
            remark = w["remark_line"].format(remark=r[10]) if r[10] else None
            sec["rows"].append({"text": _report_text(utc, r, dist, centre_lat, centre_lon, r[2], r[3], w, types),
                                "remark": remark, "utc": iso_utc(utc)})
        if parts.get("reports") == "partial":
            sec["unavailable"] = _unavailable_text("reports", reasons.get("reports"), partial.get("reports"))
    out["sections"].append(sec)

    # official records: the point rows near the cell, and the rows of the cell's zone (the whole zone)
    sec = _section("records", w["records_heading"], w["records_what"], "record")
    sec["source"] = w["source_records"]
    if parts.get("records") == "unavailable":
        sec["unavailable"] = _unavailable_text("records", reasons.get("records"))
    elif events is None:
        sec["unavailable"] = _unavailable_text("records", w["reason_events"])
    else:
        rows = []
        for ref in tile_doc.get("records", []):
            r = events["records"][ref]
            utc = utc_from_row(r[0], r[1])
            dist = haversine_km(centre_lat, centre_lon, r[2], r[3]) / MILE_KM
            if dist > REPORT_MILES:
                continue
            rows.append((utc, r, float(dist), None))
        zone_lost, zdoc = None, {}
        if zone and store_dir:
            try:
                zdoc = _read_part_file(store_dir, f"z/{zone}.json", ZONE_FORMAT)
            except JoinsError as exc:       # D27: the point rows stay; the zone part gets the partial sentence
                zone_lost = str(exc)
        for r in zdoc.get("records", []):
            rows.append((utc_from_row(r[0], r[1]), r, None, zone))
        rows.sort(key=lambda x: x[0], reverse=True)
        sec["lead"] = _records_lead(len(rows), newest_ncei, ftn, w)
        for utc, r, dist, zone_code in rows:
            if zone_code is None:
                text = _record_text(utc, r, dist, centre_lat, centre_lon, r[2], r[3], w)
            else:
                text = _zone_record_text(utc, r, zone_code, w)
            sec["rows"].append({"text": text, "remark": None, "utc": iso_utc(utc)})
        unplaced = block.get("ncei_zone_rows_unmatched", 0)
        if unplaced:
            sec["lines"].append(w["records_unplaced_one" if unplaced == 1 else "records_unplaced_many"].format(
                n=unplaced))
        if parts.get("records") == "partial":
            sec["unavailable"] = _unavailable_text("records", reasons.get("records"), partial.get("records"))
        if zone_lost:
            sec["unavailable"] = _unavailable_text("records", zone_lost, [zone])
    out["sections"].append(sec)

    # radar detections
    sec = _section("detections", w["detections_heading"], w["detections_what"], "radar detection")
    sec["source"] = w["source_detections"]
    if parts.get("detections") == "unavailable":
        sec["unavailable"] = _unavailable_text("detections", reasons.get("detections"))
    else:
        by_day: dict[date, list] = {}
        for d_, t_, lat, lon, size in tile_doc.get("detections", []):
            dist = haversine_km(centre_lat, centre_lon, lat, lon) / MILE_KM
            if dist > DETECT_MILES:
                continue
            by_day.setdefault(spc_day(utc_from_row(d_, t_)), []).append(size)
        n_det = sum(len(v) for v in by_day.values())
        sec["lead"] = _detections_lead(n_det, ftn, w)
        for day in sorted(by_day, reverse=True):
            sizes = by_day[day]
            largest = max(sizes)
            if len(sizes) == 1:
                text = w["detections_row_one"].format(date=fmt_day(day), **{"in": f"{largest / 100:.2f}"})
            else:
                text = w["detections_row_many"].format(date=fmt_day(day), n=len(sizes),
                                                       **{"in": f"{largest / 100:.2f}"})
            sec["rows"].append({"text": text, "remark": None, "utc": None})
        sec["lines"].append(w["detections_lag"].format(newest=newest_swdi) if newest_swdi
                            else w["detections_lag_none"])
        if parts.get("detections") == "partial":
            sec["unavailable"] = _unavailable_text("detections", reasons.get("detections"), partial.get("detections"))
    out["sections"].append(sec)

    # warnings: the tile's warnings whose cover includes this cell's key
    sec = _section("warnings", w["warnings_heading"], w["warnings_what"], "warning")
    sec["source"] = w["source_warnings"]
    if parts.get("warnings") == "unavailable":
        sec["unavailable"] = _unavailable_text("warnings", reasons.get("warnings"))
    elif events is None:
        sec["unavailable"] = _unavailable_text("warnings", w["reason_events"])
    else:
        rows = []
        for ref, cover in tile_doc.get("warnings", []):
            if not cover_has(cover, key):
                continue
            item = events["warnings"][ref]
            rows.append((parse_iso_utc(item["b"]), parse_iso_utc(item["e"]), item))
        rows.sort(key=lambda x: x[0], reverse=True)
        no_outline = block.get("warnings_no_outline", 0)
        sec["lead"] = (w["warnings_lead_unknown"] if (not rows and no_outline)
                       else _warnings_lead(len(rows), ftn, w))
        for b, e, item in rows:
            sec["rows"].append({"text": _warning_text(b, e, item, w), "remark": None, "utc": iso_utc(b)})
        sec["lines"].append(w["warnings_lag"].format(newest=newest_ww) if newest_ww else w["warnings_lag_none"])
        if no_outline:
            sec["lines"].append(w["warnings_no_outline_one" if no_outline == 1 else "warnings_no_outline_many"].format(
                n=no_outline))
        if parts.get("warnings") == "partial":
            sec["unavailable"] = _unavailable_text("warnings", reasons.get("warnings"), partial.get("warnings"))
    out["sections"].append(sec)

    # zone products: the cell's forecast zone (the whole zone) and its fire weather zone (red flag warnings, D7)
    zone_name = block.get("zone_names", {}).get(zone, zone) if zone else None
    fire_zone_name = block.get("fire_zone_names", {}).get(fire, fire) if fire else None
    heading = (w["zones_heading"].format(zone_name=zone_name, zone=zone) if zone else w["zones_heading_no_zone"])
    sec = _section("zones", heading, w["zones_what"], "zone product")
    sec["source"] = w["source_zones"]
    if parts.get("zones") == "unavailable":
        sec["unavailable"] = _unavailable_text("zones", reasons.get("zones"))
    else:
        # D17: the public zone lead counts public products; the fire lead counts red flag warnings. Each event carries
        # its begin (null: start not recorded), the time it is windowed and ordered by, and its end (null: not recorded).
        public_items, red_items = [], []
        zone_lost = fire_lost = None           # D27: a zone file that did not load (its reason, or None)
        if zone and store_dir:
            try:
                zdoc = _read_part_file(store_dir, f"z/{zone}.json", ZONE_FORMAT)
            except JoinsError as exc:
                zone_lost, zdoc = str(exc), {}
            for ev in zdoc.get("events", []):
                begin, end_at = _zone_span(ev)
                when = _zone_when(begin, end_at)
                if when is not None and start <= when.date() <= end:
                    public_items.append((begin, end_at, ev.get("st"), ev))
        if fire and store_dir:
            try:
                fdoc = _read_part_file(store_dir, f"z/fire-{fire}.json", ZONE_FORMAT)
            except JoinsError as exc:
                fire_lost, fdoc = str(exc), {}
            fire_zone_name = fdoc.get("name") or fire_zone_name
            for ev in fdoc.get("events", []):
                begin, end_at = _zone_span(ev)
                when = _zone_when(begin, end_at)
                if when is not None and start <= when.date() <= end:
                    red_items.append((begin, end_at, ev.get("st"), ev))
        sec["lead"] = w["zones_no_zone"] if not zone else _zone_lead(len(public_items), zone_name, zone, ftn, w)
        grouped: dict[str, list] = {}
        for begin, end_at, st, ev in public_items:
            name = PRODUCT_NAMES.get(f"{ev['k']}.{ev['s']}", f"{ev['k']}.{ev['s']}")
            grouped.setdefault(name, []).append((begin, end_at, st))
        for begin, end_at, st, ev in red_items:
            name = PRODUCT_NAMES.get(f"{ev['k']}.{ev['s']}", f"{ev['k']}.{ev['s']}")
            name = w["fire_product"].format(product=name, zone_name=fire_zone_name, zone=fire)
            grouped.setdefault(name, []).append((begin, end_at, st))
        for name in sorted(grouped, key=lambda n: min(_zone_when(x[0], x[1]) for x in grouped[n]), reverse=True):
            items = sorted(grouped[name], key=lambda x: _zone_when(x[0], x[1]))
            events_text = "; ".join(_zone_event_text(b, e, st, w) for b, e, st in items)
            sec["rows"].append({"text": w["zones_row"].format(product=name, events=events_text), "remark": None,
                                "utc": None})
        unplaced = block.get("zone_products_unplaced", 0)
        if unplaced:
            sec["lines"].append(w["zones_unplaced_one" if unplaced == 1 else "zones_unplaced_many"].format(n=unplaced))
        if fire_state != "loaded" or fire_lost:       # a fire zone file that did not load: no red flag lead
            sec["lines"].append(w["zones_fire_unavailable"])
        elif not fire:
            sec["lines"].append(w["zones_fire_none"])
        else:
            sec["fire_lead"] = _fire_lead(len(red_items), fire_zone_name, fire, ftn, w)
        if parts.get("zones") == "partial":
            sec["unavailable"] = _unavailable_text("zones", reasons.get("zones"), partial.get("zones"))
        if zone_lost:       # D27: no lead, rows or lines from a zone file that did not load; the section says so
            sec.update(lead=None, fire_lead=None, rows=[], lines=[], unavailable=_unavailable_text("zones", zone_lost))
    out["sections"].append(sec)

    # station gusts
    sec = _section("stations", w["stations_heading"], w["stations_what"], "station reading")
    sec["source"] = w["source_stations"]
    if parts.get("stations") == "unavailable":
        sec["unavailable"] = _unavailable_text("stations", reasons.get("stations"))
    else:
        stations = tile_doc.get("stations", [])
        station_lost = None                  # D27: a station file that did not load (its reason, or None)
        if not stations:
            sec["lead"] = w["stations_none_near"].format(miles=int(STATION_MILES))
        else:
            rows = []
            dropped = 0
            for st in stations:
                try:
                    sdoc = _read_part_file(store_dir, f"s/{st['id']}.json", STATION_FORMAT) if store_dir else None
                except JoinsError as exc:
                    station_lost = str(exc)
                    break
                for day_index, mph, kt in (sdoc or {}).get("days", []):
                    day = hail.day_of_index(day_index)
                    if start <= day <= end:
                        rows.append((day, mph, kt, st))
                dropped += (sdoc or {}).get("dropped", 0)
            rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
            sec["lead"] = _stations_lead(len(rows), ftn, w)
            for day, mph, kt, st in rows:
                sec["rows"].append({"text": w["stations_row"].format(date=fmt_day(day), mph=int(mph), kt=int(kt),
                                                                       station=st["name"],
                                                                       miles=f"{st['miles']:.1f}"),
                                    "remark": None, "utc": None})
            if dropped:
                key_name = "stations_dropped_one" if dropped == 1 else "stations_dropped"
                sec["lines"].append(w[key_name].format(n=dropped, kt=IMPLAUSIBLE_KT))
        if parts.get("stations") == "partial":
            sec["unavailable"] = _unavailable_text("stations", reasons.get("stations"), partial.get("stations"))
        if station_lost:      # D27: no lead, rows or lines from a station file that did not load
            sec.update(lead=None, rows=[], lines=[], unavailable=_unavailable_text("stations", station_lost))
    out["sections"].append(sec)
    return out



def _fmt_iso_date(text):
    if not text:
        return None
    return fmt_day(date.fromisoformat(text))


def _lead(rows, kind, ftn, w):
    n = len(rows)
    if n == 0:
        return w["reports_lead_none"]
    key = "reports_lead_one" if n == 1 else "reports_lead_many"
    return w[key].format(n=n, **ftn)


def _records_lead(n, newest, ftn, w):
    newest = newest or "an unknown date"
    if n == 0:
        return w["records_lead_none"].format(newest=newest, **ftn)
    key = "records_lead_one" if n == 1 else "records_lead_many"
    return w[key].format(newest=newest, n=n, **ftn)


def _detections_lead(n, ftn, w):
    if n == 0:
        return w["detections_lead_none"].format(**ftn)
    key = "detections_lead_one" if n == 1 else "detections_lead_many"
    return w[key].format(n=n, **ftn)


def _warnings_lead(n, ftn, w):
    if n == 0:
        return w["warnings_lead_none"].format(**ftn)
    key = "warnings_lead_one" if n == 1 else "warnings_lead_many"
    return w[key].format(n=n, **ftn)


def _zone_lead(n, zone_name, zone, ftn, w):
    """D17: the public zone lead. It counts public zone products only; red flag warnings have their own lead."""
    kw = dict(ftn, zone_name=zone_name, zone=zone)
    if n == 0:
        return w["zones_lead_none"].format(**kw)
    key = "zones_lead_one" if n == 1 else "zones_lead_many"
    return w[key].format(n=n, **kw)


def _fire_lead(n, zone_name, zone, ftn, w):
    """D17: the fire weather lead. It counts red flag warnings for the fire weather zone only."""
    kw = dict(ftn, zone_name=zone_name, zone=zone)
    if n == 0:
        return w["fire_lead_none"].format(**kw)
    key = "fire_lead_one" if n == 1 else "fire_lead_many"
    return w[key].format(n=n, **kw)


def _zone_span(ev: dict):
    """(begin, end) of a zone event as UTC datetimes (D6, D16). A begin of null is "start not recorded" in the
    contract; the build writes a begin on every event, since every row of an event carries its issue time. The end is
    None when none is recorded."""
    begin = parse_iso_utc(ev["b"]) if ev.get("b") else None
    end_at = parse_iso_utc(ev["e"]) if ev.get("e") else None
    return begin, end_at


def _zone_when(begin, end_at):
    """The time an event is windowed and ordered by: its begin, or its end when it has no begin."""
    return begin if begin is not None else end_at


def _zone_event_text(begin, end_at, st, w) -> str:
    """One zone event's span in words (D6, D16, D31): "{date} {begin} to {end}", with the end "end not recorded" when
    there is none; "start not recorded; end {end}" when there is no begin; ", cancelled" or ", upgraded" when a
    cancellation or an upgrade ended the product (st). A cancellation or upgrade at or before the begin reads
    "cancelled at {time}" or "upgraded at {time}" in place of the span (D26, D31)."""
    suffix_key, at_key = ZONE_STOP_WORDS.get(st, (None, None))
    if at_key is not None and begin is not None and end_at is not None and end_at <= begin:
        return w[at_key].format(time=fmt_end(end_at, None))
    if begin is None and end_at is None:
        text = w["zones_event_no_span"]
    elif begin is None:
        text = w["zones_event_no_start"].format(end=fmt_end(end_at, None))
    else:
        text = w["zones_event"].format(date=fmt_day(_local(begin).date()), begin=fmt_clock(begin),
                                       end=fmt_end(end_at, begin))
    return text + (w[suffix_key] if suffix_key is not None else "")


def _stations_lead(n, ftn, w):
    kw = dict(ftn, kt_min=STATION_KT, mph_min=int(round(STATION_KT * MPH_PER_KT)))
    if n == 0:
        return w["stations_lead_none"].format(**kw)
    key = "stations_lead_one" if n == 1 else "stations_lead_many"
    return w[key].format(n=n, **kw)


def _magnitude(r_text: str, unit: str, w: dict, mph: int | None = None, kt: int | None = None) -> str:
    """The magnitude of a row whose type carries a unit (D9, D19): inches, miles per hour, or knots with the miles per
    hour beside them. Only called for a unit code, so a number is never shown without its unit; a unit row with no
    number reads "no size given"."""
    if unit == "kt" and kt is not None:
        return w["magnitude_kt_mph"].format(value=kt, mph=mph)
    if unit == "kt" and r_text:
        return w["magnitude_kt"].format(value=r_text)
    if unit == "in" and r_text:
        return w["magnitude_in"].format(value=f"{float(r_text):.2f}")
    if unit == "mph" and r_text:
        return w["magnitude_mph"].format(value=r_text)
    return w["magnitude_none"]


def _qualifier(qual: str, w: dict) -> str:
    word = LSR_QUALIFIERS.get(qual) or NCEI_QUALIFIERS.get(qual) or ""
    return w["qualifier_part"].format(qualifier=word) if word else ""


def _place_bits(lat, lon, centre_lat, centre_lon, w):
    miles = haversine_km(centre_lat, centre_lon, lat, lon) / MILE_KM
    if miles < 0.05:
        return f"{miles:.1f}", None
    return f"{miles:.1f}", compass(bearing_deg(centre_lat, centre_lon, lat, lon))


def _report_text(utc, r, dist, clat, clon, lat, lon, w, types=None) -> str:
    """A report row: the label, the date and Montana time, the type word, the magnitude, the qualifier, the source,
    distance and bearing (D3). The type word is the archive's TYPETEXT in lower case, from the store's legend. A type
    the archive gives no unit for (LSR_UNITS) shows its type word and qualifier only, with no number (D9)."""
    kind = r[4]
    type_word = (types or {}).get(kind, kind.lower())
    miles, bearing = _place_bits(lat, lon, clat, clon, w)
    base = dict(date=fmt_day(_local(utc).date()), time=fmt_clock(utc), type=type_word,
                qualifier=_qualifier(r[7], w), source=r[8], miles=miles)
    if kind in LSR_UNITS:
        base["magnitude"] = _magnitude(r[5], r[6], w)
        key = "reports_row_here" if bearing is None else "reports_row"
    else:
        key = "reports_row_here_typed" if bearing is None else "reports_row_typed"
    if bearing is not None:
        base["bearing"] = bearing
    return w[key].format(**base)


def _record_text(utc, r, dist, clat, clon, lat, lon, w) -> str:
    """A record row (D3, D9, D19): the magnitude only when its type carries a unit; any other type is typed (its type
    word and qualifier, no number and no "no size given")."""
    miles, bearing = _place_bits(lat, lon, clat, clon, w)
    base = dict(date=fmt_day(_local(utc).date()), time=fmt_clock(utc), type=r[4],
                qualifier=_qualifier(r[7], w), source=r[8], miles=miles)
    if r[4] in UNIT_CODES:
        base["magnitude"] = _magnitude(r[5], r[6], w, mph=r[11], kt=r[12])
        key = "records_row_here" if bearing is None else "records_row"
    else:
        key = "records_row_here_typed" if bearing is None else "records_row_typed"
    if bearing is not None:
        base["bearing"] = bearing
    return w[key].format(**base)


def _zone_record_text(utc, r, zone, w) -> str:
    """A zone-coded record row (D9, D19): as _record_text, for the whole zone."""
    base = dict(date=fmt_day(_local(utc).date()), time=fmt_clock(utc), type=r[4],
                qualifier=_qualifier(r[7], w), source=r[8], zone=zone)
    if r[4] in UNIT_CODES:
        base["magnitude"] = _magnitude(r[5], r[6], w, mph=r[11], kt=r[12])
        return w["records_zone_row"].format(**base)
    return w["records_zone_row_typed"].format(**base)


def _warning_text(b, e, item, w) -> str:
    tags = []
    tg = item["tags"]
    if tg.get("hail_in") is not None:
        tags.append(w["tag_hail"].format(value=f"{tg['hail_in']:.2f}"))
    if tg.get("wind_mph") is not None:
        tags.append(w["tag_wind"].format(value=str(int(round(tg["wind_mph"])))))
    if tg.get("tornado"):
        tags.append(w["tag_tornado"].format(value=str(tg["tornado"]).lower()))
    if tg.get("damage"):
        tags.append(w["tag_damage"].format(value=str(tg["damage"]).lower()))
    tag_text = ", ".join(tags) if tags else w["warnings_tags_none"]
    return w["warnings_row"].format(date=fmt_day(_local(b).date()), begin=fmt_clock(b), end=fmt_end(e, b),
                                    kind=KIND_WORDS.get(item["k"], item["k"]), office=item["o"], tags=tag_text)


# ---------------------------------------------------------------- the map block (map.json["hail"]["joins"])

def map_data_joins(index: dict, sample: bool = False) -> dict:
    """map.json["hail"]["joins"] for a built store: the templates (every word), the radii and units, the cover rule,
    the Montana clock transitions, the lags and the parts. The browser fills the templates and filters by distance;
    it holds no word, radius or unit of its own."""
    block = index[INDEX_KEY]
    return {
        "state": "sample" if sample else block["state"],
        "as_of": index["as_of"],
        "window": list(index["window"]),
        "parts": dict(block["parts"]),
        "reasons": dict(block["reasons"]),
        "lags": dict(block["lags"]),
        "radius_miles": {"report": REPORT_MILES, "detection": DETECT_MILES, "station": STATION_MILES},
        "km_per_mile": MILE_KM,
        "mph_per_kt": MPH_PER_KT,
        "station_kt": STATION_KT,
        "station_mph": int(round(STATION_KT * MPH_PER_KT)),
        "implausible_kt": IMPLAUSIBLE_KT,
        "types": dict(block.get("types", {})),
        "kinds": dict(KIND_WORDS),
        "products": dict(PRODUCT_NAMES),
        "qualifiers": dict(LSR_QUALIFIERS),
        "ncei_qualifiers": dict(NCEI_QUALIFIERS),
        "compass": list(COMPASS),
        "cover": {"hex_digits": 25, "bits": 100, "rule": block["cover"]},
        "shapes": block["shapes"],
        "unit_codes": sorted(UNIT_CODES),           # D19: the codes that carry a unit (LSR and NCEI); all others are typed
        "fire_zone_names": dict(block.get("fire_zone_names", {})),
        "montana_time": block["montana_time"],
        "events": "hail/j/events.json",
        "events_format": EVENTS_FORMAT,
        "shards": {"j": "hail/j/{tile}.json", "z": "hail/z/{zone}.json", "s": "hail/s/{station}.json"},
        "words": dict(WORDS_JOINS),
        "problem": None,
    }


# ---------------------------------------------------------------- verify and compare

def _norm_zone_name(text: str) -> str:
    """A zone name with the three normalisations the NCEI comparison uses (data-3): spaces around "/", SE for
    SOUTHEAST, and PARK COUNTY for PARK. Upper case throughout."""
    text = " ".join(str(text).upper().split())
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\bSE\b", "SOUTHEAST", text)
    return text.replace("PARK COUNTY", "PARK")


def _name_disagreements(root: Path, block: dict) -> tuple[int, list]:
    """The NCEI zone-row names that disagree with the 2026 name of their code, after _norm_zone_name. Reported by
    verify, not failed: the names are the archive's own (data-3)."""
    count, examples = 0, []
    names = block.get("zone_names", {})
    for zone in sorted(names):
        zdoc = _read_z(root, zone) or {}
        want = _norm_zone_name(names[zone])
        for row in zdoc.get("records", []):
            city = row[9] if len(row) > 9 else ""
            if city and _norm_zone_name(city) != want:
                count += 1
                if len(examples) < 5:
                    examples.append(f"{zone}: {city!r} against {names[zone]!r}")
    return count, examples


def verify(store_dir) -> dict:
    """Check a built store's joins. Returns {"ok", "state", "parts", "checks", "gate"}: a failed check makes ok
    False; a part that did not load is reported, not failed. The gate holds B2 gate 1's Benchland rows as found (D1):
    the report and the record from the report cell's tile, the warnings and the zone from the gate cell's tile."""
    root = Path(store_dir)
    checks: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        return ok

    def out(ok, state=None, parts=None, gate=None):
        return {"ok": ok, "state": state, "parts": parts or {},
                "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks], "gate": gate or {}}

    try:
        hail.check_manifest(root)
        check("manifest hashes and counts", True)
    except hail.HailStoreError as exc:
        check("manifest hashes and counts", False, str(exc))
        return out(False)
    index = load_joins_index(root)
    block = index[INDEX_KEY]
    check("index format", block.get("format") == FORMAT)
    tiles = index["tiles"]
    events = _read_events(root)
    check("events table reads and is in its format", events is not None)
    tile_files = sorted((root / "hail" / "j").glob("r*_c*.json"))
    check("every tile has a j/ file", len(tile_files) == len(tiles) and all(
        (root / "hail" / "j" / f"{t}.json").is_file() for t in tiles), f"{len(tile_files)} files, {len(tiles)} tiles")
    zone_names = set(block.get("zone_list", []))
    fire_names = set(block.get("fire_zone_list", []))
    bad_ints = bad_refs = bad_cover = bad_zone = bad_fire = 0
    if events is not None:
        for kind in ("reports", "records"):
            for row in events[kind]:
                if not (isinstance(row[0], int) and isinstance(row[1], int)):
                    bad_ints += 1
                if kind == "records":
                    for value in row[11:13]:
                        if value is not None and not isinstance(value, int):
                            bad_ints += 1
        check("events counts match the index",
              block.get("events", {}).get("reports") == len(events["reports"])
              and block.get("events", {}).get("records") == len(events["records"])
              and block.get("events", {}).get("warnings") == len(events["warnings"]),
              str({k: len(events[k]) for k in ("reports", "records", "warnings")}))
    gate_tile = hail.tile_name(BENCHLAND_GATE["cell"][0] // 10, BENCHLAND_GATE["cell"][1] // 10)
    report_tile = hail.tile_name(BENCHLAND_GATE["report_cell"][0] // 10, BENCHLAND_GATE["report_cell"][1] // 10)
    docs: dict[str, dict] = {}
    for t in tiles:
        try:
            doc = _read_j(root, t)
        except JoinsError as exc:
            check(f"j/ file {t} reads", False, str(exc))
            continue
        docs[t] = doc
        if events is None:
            continue
        for ref in doc.get("reports", []):
            if not (isinstance(ref, int) and 0 <= ref < len(events["reports"])):
                bad_refs += 1
        for ref in doc.get("records", []):
            if not (isinstance(ref, int) and 0 <= ref < len(events["records"])):
                bad_refs += 1
        for ref, cover in doc.get("warnings", []):
            if not (isinstance(ref, int) and 0 <= ref < len(events["warnings"])):
                bad_refs += 1
            if not re.fullmatch(r"[0-9a-f]{25}", str(cover)):
                bad_cover += 1
        for code, keys in doc.get("zones", {}).items():
            if code not in zone_names or not all(isinstance(k, int) and 0 <= k < 100 for k in keys):
                bad_zone += 1
        for code, keys in doc.get("fire", {}).items():
            if code not in fire_names or not all(isinstance(k, int) and 0 <= k < 100 for k in keys):
                bad_fire += 1
        for det in doc.get("detections", []):
            if not (isinstance(det[0], int) and isinstance(det[1], int) and isinstance(det[4], int)):
                bad_ints += 1
        for st in doc.get("stations", []):
            if not isinstance(st.get("miles"), (int, float)):
                bad_ints += 1
    check("events and tile whole numbers", bad_ints == 0, f"{bad_ints} not whole")
    check("tile references point into the events table", bad_refs == 0, f"{bad_refs} bad")
    check("warning covers are 25 hex digits", bad_cover == 0, f"{bad_cover} bad")
    check("zone codes are current zones and keys are cells", bad_zone == 0, f"{bad_zone} bad")
    check("fire zone codes are current fire zones and keys are cells", bad_fire == 0, f"{bad_fire} bad")
    for zone in sorted(zone_names):
        if not (root / "hail" / "z" / f"{zone}.json").is_file():
            check(f"z/ file for {zone}", False)
            break
    else:
        check("every zone has a z/ file", True, f"{len(zone_names)} zones")
    for zone in sorted(fire_names):
        if not (root / "hail" / "z" / f"fire-{zone}.json").is_file():
            check(f"z/ file for fire zone {zone}", False)
            break
    else:
        check("every fire zone has a z/ file", True, f"{len(fire_names)} fire zones")
    for sid in block.get("station_list", []):
        if not (root / "hail" / "s" / f"{sid}.json").is_file():
            check(f"s/ file for {sid}", False)
            break
    else:
        check("every station has an s/ file", True, f"{len(block.get('station_list', []))} stations")
    manifest = json.loads((root / "hail" / "manifest.json").read_text(encoding="utf-8"))
    listed = [k for k in manifest["files"] if k.startswith(("hail/j/", "hail/z/", "hail/s/"))]
    on_disk = [p for sub in ("j", "z", "s") for p in (root / "hail" / sub).glob("*.json")]
    check("manifest lists every j, z and s file", len(listed) == len(on_disk), f"{len(listed)} listed, {len(on_disk)} files")
    disagree, examples = _name_disagreements(root, block)
    check("NCEI zone names against the 2026 names (reported, not failed)", True,
          f"{disagree} disagree after normalising" + (": " + "; ".join(examples) if examples else ""))
    # D16, D26 and D31: zone spans. Every event has a begin. Only a cancelled or upgraded span may end on or before its
    # begin: its end is the cancellation or upgrade time, which may be at or before its begin. An absent end time is
    # counted, not failed.
    span_bad, ends_recorded, stopped_no_end = 0, 0, 0
    for name in sorted(zone_names) + [f"fire-{z}" for z in sorted(fire_names)]:
        for ev in (_read_z(root, name) or {}).get("events", []):
            begin = parse_iso_utc(ev["b"]) if ev.get("b") else None
            if begin is None:
                span_bad += 1
            elif ev.get("e") and parse_iso_utc(ev["e"]) <= begin and ev.get("st") not in ZONE_STOP_WORDS:
                span_bad += 1
            if ev.get("e"):
                ends_recorded += 1
            elif ev.get("st") in ZONE_STOP_WORDS:
                stopped_no_end += 1
    check("zone spans: only a cancelled or upgraded span ends at or before its begin; every event has a begin",
          span_bad == 0, f"{span_bad} bad; {ends_recorded} events with an end; {stopped_no_end} cancelled or upgraded "
          "without one")
    # D16 and F-05: each older zone edition the page links is read and compared; reported, not failed.
    editions = block.get("zone_editions", [])
    compared = [e for e in editions if e.get("read") and not e.get("current") and "geometry_max_diff_deg" in e]
    check("zone editions: every linked edition is listed with its date (reported, not failed)", True,
          "; ".join(f"{e['file']} effective {e['effective']}: "
                    + (f"{e.get('same_codes')} codes the same, max difference {e.get('geometry_max_diff_deg')} deg, "
                       f"renamed {len(e.get('renamed', {}))}" if "geometry_max_diff_deg" in e
                       else ("not compared" if e.get("read") else f"not read ({e.get('reason')})"))
                    for e in editions) + f" (compared: {len(compared)}; the newest is effective "
          f"{editions[-1]['effective'] if editions else 'not known'}; EDITION_DATE {EDITION_DATE.isoformat()})")
    bad_station = 0
    for sid in block.get("station_list", []):
        for day in (_read_s(root, sid) or {}).get("days", []):
            if not (len(day) == 3 and all(isinstance(v, int) and not isinstance(v, bool) for v in day)):
                bad_station += 1
    check("station days are whole numbers (mph and kt, D18)", bad_station == 0, f"{bad_station} not whole")
    gate = {}
    gate_month = BENCHLAND_GATE["day"][:7]
    gate_month_loaded = (block["parts"].get("reports") != "unavailable"
                         and gate_month not in block.get("partial", {}).get("reports", []))
    if events is not None and docs.get(gate_tile) is not None and docs.get(report_tile) is not None \
            and gate_month_loaded:
        gate = _benchland_gate(root, index, docs[gate_tile], docs[report_tile], events)
        row = gate.get("lsr_row")
        check("gate 1: the LSR hail report of 1.75 in on 2025-06-15 at 20:10 UTC is within 5 miles of Benchland's "
              "cell (792, 1998)", row is not None and row["miles_from_cell"] <= REPORT_MILES, str(row))
        nrow = gate.get("ncei_hail_row")
        check("gate 1: the NCEI hail record of 1.75 in for the same event is within 5 miles of that cell",
              nrow is not None and nrow["miles_from_cell"] <= REPORT_MILES, str(nrow))
        if block["parts"].get("warnings") == "loaded":
            begins = {item["b"] for item in gate.get("warnings", []) if item["o"] == "TFX"}
            check("gate 1: the gate cell's TFX warnings include the 19:53 and 21:23 UTC polygons",
                  {"2025-06-15T19:53Z", "2025-06-15T21:23Z"} <= begins, str(sorted(begins)))
        else:
            check("gate 1: warnings part not loaded (not checked)", True, block["parts"].get("warnings"))
        if block["parts"].get("zones") == "loaded":
            check("gate 1: the gate cell's zone is MTZ313", gate.get("zone") == "MTZ313", str(gate.get("zone")))
        else:
            check("gate 1: zone part not loaded (not checked)", True, block["parts"].get("zones"))
    elif docs.get(gate_tile) is not None:
        check("gate 1: reports part not loaded (not checked)", True, block["parts"].get("reports"))
    return out(all(c[1] for c in checks), block["state"], block["parts"], gate)



def _benchland_gate(root: Path, index: dict, doc: dict, report_doc: dict, events: dict) -> dict:
    """The gate rows of B2 gate 1 (D1) as the store holds them. The LSR report and the NCEI record are the rows of the
    report cell's tile that fall on the gate's SPC day at the gate's hour and are 1.75 in hail; their distance is
    measured from the report cell's centre (Benchland's own cell), never from tile bounds. The warnings and the zone
    are read from the gate cell's tile (the gate cell's centre inside each polygon; the cell's zone)."""
    row, col = BENCHLAND_GATE["cell"]
    key = hail.cell_key(row, col)
    rrow, rcol = BENCHLAND_GATE["report_cell"]
    rlat, rlon = hail.cell_centre(rrow, rcol)
    day = date.fromisoformat(BENCHLAND_GATE["day"])
    gate: dict = {"cell": [row, col], "centre": list(hail.cell_centre(row, col)), "key": key,
                  "report_cell": [rrow, rcol], "report_centre": [rlat, rlon]}

    def miles(lat, lon):
        return round(float(haversine_km(rlat, rlon, lat, lon)) / MILE_KM, 2)

    found = None
    for ref in report_doc.get("reports", []):
        r = events["reports"][ref]
        utc = utc_from_row(r[0], r[1])
        if spc_day(utc) == day and hhmm(utc) == BENCHLAND_GATE["hhmm"] and r[4] == "H" and r[5] == BENCHLAND_GATE["in"]:
            found = {"utc": iso_utc(utc), "in": r[5], "miles_from_cell": miles(r[2], r[3]), "remark": r[10][:80]}
            break
    gate["lsr_row"] = found
    rec = None
    for ref in report_doc.get("records", []):
        r = events["records"][ref]
        utc = utc_from_row(r[0], r[1])
        if spc_day(utc) == day and hhmm(utc) == BENCHLAND_GATE["hhmm"] and r[4] == "hail" and r[5] == BENCHLAND_GATE["in"]:
            rec = {"utc": iso_utc(utc), "in": r[5], "miles_from_cell": miles(r[2], r[3]), "source": r[8]}
            break
    gate["ncei_hail_row"] = rec
    warnings = []
    for ref, cover in doc.get("warnings", []):
        item = events["warnings"][ref]
        if item["b"][:10] == BENCHLAND_GATE["day"] and cover_has(cover, key):
            warnings.append({"k": item["k"], "b": item["b"], "e": item["e"], "o": item["o"]})
    gate["warnings"] = warnings
    zone = _zone_for_key(doc, key)
    gate["zone"] = zone
    gate["zone_name"] = index[INDEX_KEY].get("zone_names", {}).get(zone) if zone else None
    gate["fire_zone"] = _zone_for_key(doc, key, "fire")
    if zone:
        zdoc = _read_z(root, zone) or {}
        gate["zone_high_wind_events"] = [e for e in zdoc.get("events", []) if e["k"] == "HW"]
    gate["stations"] = doc.get("stations", [])
    return gate



def compare(store_dir) -> dict:
    """This build's counts against the research (RESEARCH_COUNTS), with the window noted."""
    index = load_joins_index(store_dir)
    c = index[INDEX_KEY]["compare"]
    rows = []

    def row(name, ours, research, note):
        rows.append({"name": name, "ours": ours, "research": research,
                     "delta": (None if ours is None or research is None else ours - research), "note": note})

    row("LSR hail (H), five years", c["lsr_hail"], RESEARCH_COUNTS["lsr_hail_window"],
        "the research counted UTC days from 2021-10-17 to 2026-10-17; this build counts SPC days (12:00 UTC)")
    row("LSR thunderstorm wind gust (G), five years", c["lsr_g"], RESEARCH_COUNTS["lsr_g_window"], "as above")
    for year, research in RESEARCH_COUNTS["ncei_hail_by_year"].items():
        ours = c["ncei_hail_by_year"].get(str(year))
        row(f"NCEI hail {year} (calendar year)", ours, research, "by the local BEGIN date, the research's basis")
    row("SWDI nx3hail distinct detections in the window (Montana polygon)", c["swdi_montana_polygon"],
        RESEARCH_COUNTS["swdi_distinct_window"],
        "the research window ends 2026-10-17 00:00 UTC; this build's ends 12:00 UTC on that day")
    row("SV polygon events (NEW polygons)", c["sv_events"], RESEARCH_COUNTS["sv_events_window"],
        "the research counted issue dates in the window; this build counts polygon begin times")
    row("TO polygon events", c["to_events"], RESEARCH_COUNTS["to_events_window"], "as above")
    for year, research in RESEARCH_COUNTS["station_days_50kt_by_year"].items():
        ours = index[INDEX_KEY]["station_days_by_year"].get(str(year))
        row(f"Station days at or above 50 kt {year}", ours, research,
            "the IEM daily summary, station local days; the same CSV as the research")
    return {"rows": rows, "window": index["window"], "built_at": index[INDEX_KEY]["built_at"]}


# ---------------------------------------------------------------- the SAMPLE joins for the fixture

FIXTURE_DAYS = ("2025-06-14", "2025-06-15", "2025-06-16")


def fixture(out_dir, from_store) -> dict:
    """Write the SAMPLE joins for the fixture store (website/data/hail-fixture): the three fixture tiles' files, the
    events they refer to, and the zone and station files they name, cut to FIXTURE_DAYS, from a real joins build
    (from_store). hail.fixture_store writes the B1 sample first, so its index and manifest are regenerated the same way."""
    out = Path(out_dir)
    hail.fixture_store(out)
    src = Path(from_store)
    real_block = load_joins_index(src)[INDEX_KEY]
    real_events = _read_events(src)
    if real_events is None:
        raise JoinsError("the real build has no events table")
    sample = hail.load_index(out)
    days = {date.fromisoformat(d) for d in FIXTURE_DAYS}
    hail_out = out / "hail"
    for sub in ("j", "z", "s"):
        (hail_out / sub).mkdir(parents=True, exist_ok=True)
    new_events: dict[str, list] = {"reports": [], "records": [], "warnings": []}
    seen: dict[tuple, int] = {}

    def remap(kind: str, old: int) -> int:
        if (kind, old) not in seen:
            seen[(kind, old)] = len(new_events[kind])
            new_events[kind].append(real_events[kind][old])
        return seen[(kind, old)]

    def on_day(row) -> bool:
        return utc_from_row(row[0], row[1]).date() in days

    zones_needed, stations_needed, fires_needed = set(), set(), set()
    sample_tiles = sample["tiles"]
    for name in sample_tiles:
        doc = json.loads((src / "hail" / "j" / f"{name}.json").read_text(encoding="utf-8"))
        keep = dict(doc)
        refs = [remap("reports", r) for r in doc["reports"] if on_day(real_events["reports"][r])]
        keep["reports"] = sorted(refs, key=lambda r: tuple(new_events["reports"][r][:5]))
        refs = [remap("records", r) for r in doc["records"] if on_day(real_events["records"][r])]
        keep["records"] = sorted(refs, key=lambda r: tuple(new_events["records"][r][:5]))
        warnings = []
        for ref, cover in doc["warnings"]:
            item = real_events["warnings"][ref]
            if parse_iso_utc(item["b"]).date() in days or parse_iso_utc(item["e"]).date() in days:
                warnings.append([remap("warnings", ref), cover])
        keep["warnings"] = sorted(warnings, key=lambda w: (new_events["warnings"][w[0]]["b"],
                                                           new_events["warnings"][w[0]]["k"],
                                                           new_events["warnings"][w[0]]["o"]))
        keep["detections"] = [r for r in doc["detections"] if on_day(r)]
        keep["stations"] = [dict(s) for s in doc["stations"]]
        stations_needed.update(s["id"] for s in keep["stations"])
        zones_needed.update(doc["zones"].keys())
        fires_needed.update(doc.get("fire", {}).keys())
        (hail_out / "j" / f"{name}.json").write_bytes(_compact(keep))
    (hail_out / "j" / EVENTS_NAME).write_bytes(_compact({
        "f": EVENTS_FORMAT, "d0": hail.D0.isoformat(), "reports": new_events["reports"],
        "records": new_events["records"], "warnings": new_events["warnings"]}))
    for zone in sorted(zones_needed):
        doc = json.loads((src / "hail" / "z" / f"{zone}.json").read_text(encoding="utf-8"))
        doc["events"] = [e for e in doc["events"] if _zone_when(*_zone_span(e)).date() in days]
        doc["records"] = [r for r in doc["records"] if utc_from_row(r[0], r[1]).date() in days]
        (hail_out / "z" / f"{zone}.json").write_bytes(_compact(doc))
    for zone in sorted(fires_needed):
        doc = json.loads((src / "hail" / "z" / f"fire-{zone}.json").read_text(encoding="utf-8"))
        doc["events"] = [e for e in doc["events"] if _zone_when(*_zone_span(e)).date() in days]
        (hail_out / "z" / f"fire-{zone}.json").write_bytes(_compact(doc))
    station_list = sorted(stations_needed)
    for sid in station_list:
        doc = json.loads((src / "hail" / "s" / f"{sid}.json").read_text(encoding="utf-8"))
        doc["days"] = [d for d in doc["days"] if hail.day_of_index(d[0]) in days]
        (hail_out / "s" / f"{sid}.json").write_bytes(_compact(doc))
    events_counts = {k: len(v) for k, v in new_events.items()}
    block = {
        "format": FORMAT, "events_format": EVENTS_FORMAT,
        "built_at": real_block["built_at"], "as_of": sample["as_of"],     # the source build's time: deterministic
        "window": list(sample["window"]), "sample": True, "state": "sample",
        "parts": {p: "loaded" for p in PARTS}, "reasons": {}, "partial": {},
        "lags": dict(real_block["lags"]),
        "types": dict(real_block.get("types", {})),
        "zone_list": sorted(zones_needed),
        "zone_names": {z: real_block["zone_names"].get(z, "") for z in sorted(zones_needed)},
        "zones": len(zones_needed), "station_list": station_list, "stations": len(station_list),
        "fire_zone_list": sorted(fires_needed),
        "fire_zones": {"state": "loaded", "reason": None, "zones": len(fires_needed)},
        "fire_zone_names": {z: real_block.get("fire_zone_names", {}).get(z, "") for z in sorted(fires_needed)},
        "tiles": len(sample_tiles), "sample_days": list(FIXTURE_DAYS),
        "source": f"cut from the joins build of {real_block['built_at']} (days {', '.join(FIXTURE_DAYS)} only)",
        "cover": real_block["cover"], "shapes": real_block["shapes"], "tile": real_block["tile"],
        "montana_time": real_block["montana_time"], "events": events_counts,
        "compare": {}, "bytes": {}, "counts": {}, "station_days_by_year": {}, "station_dropped": 0,
        "station_days": 0, "station_missing": 0, "zone_rows_unmatched": 0, "ncei_zone_rows_unmatched": 0,
        "sources": {}, "failures": [], "failure_count": 0,
        "zone_editions": list(real_block.get("zone_editions", [])),
        "zone_edition_cutover": real_block.get("zone_edition_cutover"),
        "zone_products_unplaced": 0, "zone_products_renumbered": 0, "ncei_zone_rows_renumbered": 0,
        "malformed_rows": {p: 0 for p in PARTS}, "repull": {"months": [], "years": []}, "offline": True,
    }
    index_bytes = _pretty(dict(sample, **{INDEX_KEY: block}))
    (hail_out / "index.json").write_bytes(index_bytes)
    manifest = json.loads((hail_out / "manifest.json").read_text(encoding="utf-8"))
    files = {rel: meta for rel, meta in manifest["files"].items()
             if not rel.startswith(("hail/j/", "hail/z/", "hail/s/"))}
    for sub in ("j", "z", "s"):
        for path in sorted((hail_out / sub).rglob("*.json")):
            data = path.read_bytes()
            files[path.relative_to(out).as_posix()] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    files["hail/index.json"] = {"bytes": len(index_bytes), "sha256": hashlib.sha256(index_bytes).hexdigest()}
    manifest["files"] = {k: files[k] for k in sorted(files)}
    manifest[INDEX_KEY] = {"format": FORMAT, "tiles": sample_tiles, "zones": len(zones_needed),
                           "stations": len(station_list), "state": "sample"}
    (hail_out / "manifest.json").write_bytes(_pretty(manifest))
    hail.check_manifest(out)
    total = sum(p.stat().st_size for p in (out / "hail").rglob("*") if p.is_file())
    return {"out": str(out), "tiles": len(sample_tiles), "zones": len(zones_needed), "stations": len(station_list),
            "events": events_counts, "bytes_on_disk": total}



def _legend_for(real_block: dict, src: Path) -> dict:
    return dict(real_block.get("types", {}))


def _type_legend(pairs) -> dict:
    """{TYPECODE: type word} from (code, TYPETEXT lower-cased) pairs: the most common text for each code."""
    counts: dict[str, dict[str, int]] = {}
    for code, word in pairs:
        counts.setdefault(code, {}).setdefault(word, 0)
        counts[code][word] += 1
    return {code: max(words.items(), key=lambda kv: (kv[1], kv[0]))[0] for code, words in sorted(counts.items())}


# ---------------------------------------------------------------- command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.joins", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="pull (cache first), join each tile, write j/, z/, s/")
    b.add_argument("--store", required=True, help="the store directory that holds hail/ (the B1 store)")
    b.add_argument("--cache", default=None, help="the download cache directory (kept between runs)")
    b.add_argument("--procs", type=int, default=4, help="concurrent downloads")
    b.add_argument("--today", default=None, help="the build date (YYYY-MM-DD); default the UTC date")
    b.add_argument("--offline", action="store_true",
                   help="make no request: the cache is the only input (two such builds are byte-identical)")
    v = sub.add_parser("verify", help="check the joins in a store")
    v.add_argument("store")
    c = sub.add_parser("compare", help="this build's counts against the research counts")
    c.add_argument("store")
    f = sub.add_parser("fixture", help="write the SAMPLE joins into the fixture store")
    f.add_argument("--out", default=str(Path(__file__).resolve().parent / "data" / "hail-fixture"))
    f.add_argument("--from-store", required=True, help="a real joins build (its hail/ holds the j, z and s files)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        today = date.fromisoformat(args.today) if args.today else None
        block = build(args.store, args.cache, procs=args.procs, today=today, offline=args.offline)
        print(json.dumps({k: block[k] for k in ("state", "parts", "tiles", "bytes", "counts", "warnings",
                                                  "zones", "stations", "station_days", "sources")},
                         indent=1, sort_keys=True))
        return 0
    if args.command == "verify":
        result = verify(args.store)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0 if result["ok"] else 1
    if args.command == "compare":
        print(json.dumps(compare(args.store), indent=1, sort_keys=True, default=str))
        return 0
    if args.command == "fixture":
        print(json.dumps(fixture(args.out, args.from_store), indent=1, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
