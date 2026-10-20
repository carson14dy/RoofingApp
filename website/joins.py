"""Hail history joins (B2, extended in B5): what else happened at each spot, joined to the B1 store's tiles.

Kinds of evidence sit beside the radar estimate (docs/DECISIONS.md D34 and D35; the B2 and B5 briefs), each with its own
kind word and never merged into another: a report (an NWS local storm report, IEM's LSR archive), an official record
(NCEI Storm Events: point records and zone-coded rows), a radar detection (NCEI's SWDI nx3hail signatures), a warning
(the NWS warning polygon that covered the spot, IEM's watchwarn archive), a zone product (an NWS product for the spot's
forecast zone, or a county product for its county) and a station reading (the nearest ASOS gusts, IEM's daily
summaries). Nothing here states damage, an all-clear, insurance or eligibility (AGENTS.md rule 5). A missing source says
so: "Data unavailable".

Output, written into the store next to B1's shards (store/hail/):
  j/events.json               every report (LSR), record (NCEI points) and warning (polygon) in the window, once each;
                              a report's twelfth field is its type word (B5, source 6); a record's fourteenth is NCEI's
                              FLOOD_CAUSE as written (B5)
  j/r{tr:04d}_c{tc:04d}.json  one per B1 tile: reports and records as indexes into events.json, warnings as [index, the
                              tile's 100-bit cover], detections in full, the zone map {zone code: [cell keys]}, the fire
                              weather zones {code: [keys]}, the counties {MTC code: [keys]} (B5: each Montana cell is in
                              one county, written here once), and the two nearest stations within 40 miles
  j/e/r{tr:04d}_c{tc:04d}.json  one per B1 tile (D30): the events that tile's file refers to, in the events table's own
                              row shapes and keyed by their index in events.json (format hail-events-tile-v1); the
                              browser fetches it on a tap (D22); the index's events_tiles block names the format and
                              the sizes, and verify checks every referenced event is in its tile's file
  z/MTZ###.json               one per current Montana forecast zone: its zone products, one event per period (D8; B2
                              D33 implemented in B5), and its NCEI zone-coded rows
  z/fire-MTZ###.json          one per fire weather zone: red flag warnings (D7), in the same event shape
  k/MTC###.json               one per Montana county (B5, source 4): the county-only events (FA.A and FF.A with county
                              codes and no zone code) and the outline-less polygons joined by county (D11)
  s/<id>.json                 one per MT_ASOS station: the days with a gust of 50 kt (58 mph) or more, as
                              [day index, mph, kt, flag] (B5: flag 1 is a reading flagged for check, D12)
  hail/index.json             gains a "joins" block (counts, parts, the request summary, the lags, the report types, the
                              type words, the zone editions, the cover counts, the counties, the VTEC counts, the town
                              point check and the malformed-row counts)
  hail/manifest.json          lists every j/, z/, s/ and k/ file with its bytes and SHA-256

Each report lies within five miles of about seven tiles, so the events table keeps each row once.

Units and conventions (the B2 brief; B5 additions): LSR hail, rain and snow in inches as reported; LSR gusts and sustained
wind in mph (the archive gives no unit; the research reads it as mph); LSR MAG "None" is missing. LSR magnitudes are shown
only for codes H, R, S (inches) and G, N, A (mph), the codes B2 verified; codes 5, 6, 7, I and J (freezing rain, extreme
cold, wind chill, extreme heat, fog) show no magnitude and show the remark as written. NCEI BEGIN times are MST-7 local
(UTC = local + 7 h; CZ_TIMEZONE is MST-7 on all 9,299 Montana rows) and every shown time is Montana time (MDT or MST). NCEI
wind is in knots, with mph = round(kt x 1.15078) beside it. NCEI hail is inches. The B5 point types (flood, flash flood,
heavy rain, tornado, funnel cloud, lightning, debris flow) carry no MAGNITUDE in these files and show their type word only.
SWDI MAXSIZE is inches, stored as hundredths (an integer), exact duplicate rows dropped. IEM daily gusts are knots:
many are whole knots, and nearly all the rest fit a whole mph multiplied by 0.8689762 (inferred from the values; the feed
does not document it). Station days are whole knots and whole mph, the mph from the unrounded knots (D18). Warning tags are the
NWS numbers as the archive gives them, in inches and mph. Times are UTC in the store.

Polygon cover (D11, B5): a polygon covers a cell when it intersects the cell's square (half a cell each way from the
centre: a polygon vertex in the square, or an edge across one of its sides, or the square inside the polygon). The
centre rule (the centre inside) is a subset and is counted beside it per product (cover_counts in the index). A town
point is tested by exact point-in-polygon against every polygon of 2021 to 2026 (town_checks; every disagreement with the
centre rule is listed). A polygon with no outline is never read as no warning: it joins by the MTC codes its product
carries, and is counted in polygon_nulls otherwise.

Zone periods (D8, B5): rows of one VTEC event (zone, phenomenon, significance, office, event number, year) are taken in
product order (utc_prodissue). A CAN, UPG or EXP closes the open period; a closing row with no open period starts one of its
own at its issue time; a NEW, CON, EXT, EXA or EXB opens a period when none is open and otherwise continues it. Each period
is a span: begin = the opening row's issue time (UTC), end = the closing row's expiry (a cancellation or upgrade time, even at
or before the begin: "cancelled at", D26, D31), else the latest expiry of its rows (None when not after the begin: "end not
recorded", D6). A tie in product time reads cancelled. The window takes a period by its begin. VTEC events (the key
without the zone; the earliest NEW or CON issue, else the earliest issue) are counted separately in vtec_counts.

Zone sets (D16, D27, D44): the NWS GIS page links two public zone editions, z_18mr25.zip (effective 18 March 2025) and
z_16ap26.zip (effective 16 April 2026); each date is the day and month in its file name. The NWS change history names six
older editions for 2021 to 2024 (ZONE_EDITION_ARCHIVE). Each is requested on every build, and on 2026-10-19 each returned
HTTP 404 at the NWS address, so the index records it as not published. For the years before 18 March 2025, D44 places every
zone product by the Montana public zone set that IEM's ugcs service gives for the product's issue time: 103 zones through
2022-09-13 12:00Z and 83 from 2022-09-13 18:00Z (seven dated snapshots, cached and checksummed in the index as iem_sets). A
product issued from 2022-09-07 to 2022-09-13 18:00Z is placed by the set that holds its code and counted as placed in the
changeover week. The 83 current zones keep the NWS outlines; the 20 zones removed on 13 September 2022 (MTZ008 to MTZ015 and
MTZ044 to MTZ055) and MTZ060 before that change use the IEM's simplified outlines, and their rows say so. A code the set in
force does not hold is counted as unplaced, with its reason (not_in_iem_set, set_unread, or not_in_current, retired_zone and
edition_unread for the NWS editions); zone_placement_table, zone_placement, zone_unplaced_rows, iem_sets and zones_before in
the index hold the counts, the checksums and the cell membership the removed zones take before the switch.

Requests (B5): each IEM watchwarn request (polygon shapefiles and zone CSVs, and the polygon CSVs for the county twins)
runs from 1 December of the year before to 31 January of the year after, and the copies of a row that two years' files
share are one row: D17 keeps one seen-set across every year and product of the zone requests (zone_row_copies in the
index), and the polygon copies are dropped as before (53 duplicates in the window, measured 2026-10-19). A year-only request lost the rows whose
product was issued in the year before, so B2's per-year zone counts were short (HW.W, WW.Y, HW.A and WC.W by 1 to 2 events
in the window). The cache folders are ww-m and zones-m, so no year-only file is mixed in.

Malformed rows (D21): a row whose date, position or magnitude cannot be read is skipped and counted (malformed_rows in
the index); a row with too few fields is counted as short (D10). Neither fails its file or the build.

Cache (D10, D15): a re-pull window (the last two months of LSR and SWDI, the current year of warnings, zone products and
station days, and in January the previous year too) is fetched fresh and written over the cached copy. The cached copy is
used only when the fresh request fails, and the index then says "served from cache since". --offline makes no request at
all: the cache is the only input, so two offline builds from one cache are byte-identical. The county file (TIGER 2026) is
fetched once and kept (annual or on change).

The window is the B1 store's window: SPC report days from window[0] to window[1], that is UTC instants from 12:00 UTC on the
first day up to 12:00 UTC on the day after the last. The research's own window (calendar days 2021-10-19 to 2026-10-19)
is counted separately from every row read (vtec_counts_research).

Sources and terms (B5, quoted from the records; each name is the source's own):
  IEM watchwarn, LSR and daily summaries: "The materials found on this website are in the public domain and may be used
  freely by anyone for any lawful purpose." "Attributing the Iowa Environmental Mesonet of Iowa State University would be
  appreciated." "We therefore provide this information without any warranty of accuracy."
  NWS warnings: "The information on National Weather Service Web servers and Web sites is in the public domain, unless
  specifically annotated otherwise, and may be used freely by the public." "You also cannot present information of your
  own in a way that makes it appear to be official government information."
  Census county boundaries (TIGER/Line 2026, the county file's own use constraints, as its ISO metadata gives them):
  "The TIGER/Line shapefile products are not copyrighted; however, TIGER/Line and Census TIGER are registered trademarks of
  the U.S. Census Bureau. These products are free to use in a product or publication, however acknowledgement must be given
  to the U.S. Census Bureau as the source." That is the county file's own wording (tl_2026_us_county.shp.iso.xml in the
  cached county zip: 50,509 bytes, SHA-256 828948a3ccab9bfbc2ab6987686790e421ca0c88e61aaecbabe826fa41ce1eb7).
  The 2025 state file's use constraint, as the research record legal-terms-review.json quotes it (sources 0, quotes 0):
  "The TIGER/Line Shapefile products are not copyrighted however TIGER/Line and Census TIGER are registered trademarks of
  the U.S. Census Bureau. These products are free to use in a product or publication, however acknowledgement must be given
  to the U.S. Census Bureau as the source."
  NCEI Storm Events: the licence text was not read in this run (the NCEI terms page returned 503 in the research).

Feed facts for the contract rows (B5):
  nws_warnings_polygons (IEM watchwarn shapefile, accept=shapefile): products FL.W, FA.W, FA.Y, FL.A, FL.Y, SQ.W (and
    SV.W, TO.W, FF.W from B2; FF.A's polygon); NEW rows with GTYPE P; POLY_BEG and POLY_END UTC (YYYYMMDDHHMM); tags
    HAILTAG (in), WINDTAG (mph), TORNTAG, DAMAGTAG (the NWS damage threat tag, shown as the NWS's: SQ.W and FF.W carry
    one); blank tags are missing; the research's note: only SV carries hail, wind or tornado tags among these products;
    cadence per request year (the current year and January's previous year fresh).
  nws_zone_products (IEM watchwarn CSV, accept=csv): products HW.W, WS.W, BZ.W, IS.W, EC.W, WC.W, FW.W (fire zones), DS.W,
    WI.Y, FA.A, WW.Y, WS.A, HW.A, HT.Y, EH.W, EH.A, FR.Y, FZ.W, DU.Y, FF.A; utc_issue, utc_expire and utc_prodissue UTC; a row
    with a zone code (MTZ) is a zone row, a row with a county code (MTC) is a county row; blank UGC rows are polygon rows.
  nws_county_products: FA.A and FF.A county-only events (MTC rows, no MTZ row of the same key): 18 and 2 in the research
    window; the county file is Census TIGER/Line 2026, 56 Montana counties; a cell no county polygon holds (177 cells, all
    within 2 km of a county edge) takes the nearest county edge within 2 km, the zone rule (D8).
  ncei_storm_events: point rows (BEGIN_LAT and BEGIN_LON present, CZ_TYPE C) of Hail, Thunderstorm Wind, Flood, Flash Flood,
    Heavy Rain, Tornado, Funnel Cloud, Lightning and Debris Flow, within 5 miles like hail; zone-coded rows (CZ_TYPE Z, any
    type) by their zone; BEGIN times MST-7; MAGNITUDE blank on the B5 types; FLOOD_CAUSE as written ("Heavy Rain",
    "Heavy Rain / Snow Melt", "Heavy Rain / Burn Area", "Ice Jam"); the 2020 to 2026 totals are Flood 76, Flash Flood 60,
    Heavy Rain 144, Tornado 17, Funnel Cloud 35, Lightning 8, Debris Flow 11 (351 rows); the window rows are in verify.
  iem_lsr: VALID is UTC; the type word of each row is kind (LSR_KIND_FOLD: HEAVY RAIN and RAIN are rain; HEAVY SNOW and SNOW
    are snow; EXTR WIND CHILL and WIND CHILL are wind chill; EXCESSIVE HEAT and EXTREME HEAT are extreme heat; all others
    their TYPETEXT in lower case). The labels and their first and last dates are in the index's type_words (the IEM
    documentation's own dates were not read in this run; the dates are the data's).
  station gusts (IEM daily, MT_ASOS): knots and mph whole; a reading of 130 kt or more is dropped and counted (D12: LWT
    182.5 kt on 2023-03-13 among three, 255.0 at SDY and 165.1 at DLN); HVR 105.1 kt on 2025-02-20 and MSO 86.0 kt on
    2025-05-09 are flagged for check (FLAG_CHECK, the two the brief names: the flag words are shown with them).
"""
from __future__ import annotations

import argparse
import collections
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

FORMAT = "hail-joins-v2"            # j/ files (B5: the touch rule D11, the counties map, a report's type word)
ZONE_FORMAT = "hail-zone-v1"        # z/ files (B5: one event per period, D8; the shape is B2's)
COUNTY_FORMAT = "hail-county-v1"    # k/ files: the county-only events and the polygon events joined by county (B5)
EVENTS_FORMAT = "hail-events-v2"    # j/events.json: every report, record and warning row once (B5: type word, cause)
EVENTS_NAME = "events.json"
# D30 (B5 part B1): hail/j/e/<tile>.json holds the events one tile refers to, in the events table's own row shapes and
# keyed by their index in events.json, so the tile file's indexes stay valid. The browser fetches it on a tap (D22).
TILE_EVENTS_FORMAT = "hail-events-tile-v1"
TOWNS_NAME = "towns.json"                    # D38: hail/j/towns.json, the polygon products that contain each town point
TOWNS_FORMAT = "hail-joins-towns-v1"
# D41: the label a warning row begins with, by the product's significance: a watch or an advisory is never a "Warning"
SIGNIFICANCE_LABEL = {"W": "Warning", "A": "Watch", "Y": "Advisory"}
# D37: the five July to June seasons the station gust files count (the rows the sheet shows; the partial 2026-27 season is
# a line below the table, not a season list entry, D20, and its gust days are not in the files)
SEASON_LABELS = tuple(f"{y}-{str(y + 1)[2:]}" for y in range(2021, 2026))
TILE_EVENTS_DIR = "e"                       # the folder beside events.json: hail/j/e/
TILE_EVENTS_BUDGET_GZIP = 100_000           # the largest tile events file, gzipped (100 KB, D30)
STATION_FORMAT = "hail-station-v3"  # s/ files (B5: a fourth element, 1 when the reading is flagged for check; D37: days reported per season)
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
# B5 (D11, D34, D35 and the B5 brief): the polygon products, read from IEM's watchwarn shapefiles, issuance polygons
# (NEW rows with GTYPE P). SV.W, TO.W and FF.W are B2's; FL.W, FA.W, FA.Y, FL.A, FL.Y and SQ.W are B5's; FF.A is read
# too, since its one polygon event is routed by its own rows (the window holds none; its other rows are zone and
# county rows). Each product is requested with its own significance.
POLYGON_PRODUCTS = (("SV", "W"), ("TO", "W"), ("FF", "W"), ("FL", "W"), ("FA", "W"), ("FA", "Y"), ("FL", "A"),
                    ("FL", "Y"), ("SQ", "W"), ("FF", "A"))
# The zone products, from IEM's zone rows (one request per product and year, with a margin of a month either side:
# B5, see MARGIN_MONTHS). B2's ten (D34, D35) and B5's ten (WW.Y, WS.A, HW.A, HT.Y, EH.W, EH.A, FR.Y, FZ.W, DU.Y, FF.A).
# FL.W is a polygon product (its rows have no zone code), so it is not a zone product; its county rows (MTC) go to the
# county path only when the event has no polygon.
ZONE_PRODUCTS = (("HW", "W"), ("WS", "W"), ("BZ", "W"), ("IS", "W"), ("EC", "W"), ("WC", "W"), ("FW", "W"),
                 ("DS", "W"), ("WI", "Y"), ("FA", "A"), ("WW", "Y"), ("WS", "A"), ("HW", "A"), ("HT", "Y"),
                 ("EH", "W"), ("EH", "A"), ("FR", "Y"), ("FZ", "W"), ("DU", "Y"), ("FF", "A"))
LSR_HEADER = ("VALID", "VALID2", "LAT", "LON", "MAG", "WFO", "TYPECODE", "TYPETEXT", "CITY", "COUNTY", "STATE",
              "SOURCE", "REMARK", "UGC", "UGCNAME", "QUALIFIER")
LSR_UNITS = {"H": "in", "R": "in", "S": "in", "G": "mph", "N": "mph", "A": "mph"}
LSR_QUALIFIERS = {"E": "estimated", "M": "measured", "U": "unknown"}
NCEI_QUALIFIERS = {"MG": "measured gust", "EG": "estimated gust", "MS": "measured sustained",
                   "ES": "estimated sustained"}
# B5 (source 5): NCEI county-coded points of these types join as records within 5 miles, like hail and thunderstorm
# wind. Their rows carry no MAGNITUDE in these files (checked: 351 rows), so they are typed rows (D19).
NCEI_POINT_TYPES = ("Hail", "Thunderstorm Wind", "Flood", "Flash Flood", "Heavy Rain", "Tornado", "Funnel Cloud",
                    "Lightning", "Debris Flow")
NCEI_WIND_TYPES = ("Thunderstorm Wind", "High Wind", "Strong Wind")
# D19: the type codes that carry a unit (a magnitude is shown only for these); every other code is typed (type word only).
NCEI_UNIT_CODES = frozenset(t.lower() for t in ("Hail",) + NCEI_WIND_TYPES)   # B5: not the new point types
UNIT_CODES = frozenset(LSR_UNITS) | NCEI_UNIT_CODES
# D48: the NCEI point types that are flood records (the records row "Flood and flash flood records within 5 miles")
FLOOD_RECORD_CODES = ("flood", "flash flood")
SWDI_HEADER = ("ZTIME", "WSR_ID", "CELL_ID", "PROB", "SEVPROB", "MAXSIZE", "LAT", "LON")
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
PRODUCT_NAMES = {
    "SV.W": "Severe thunderstorm warning", "TO.W": "Tornado warning", "FF.W": "Flash flood warning",
    "HW.W": "High wind warning", "HW.A": "High wind watch", "WS.W": "Winter storm warning",
    "BZ.W": "Blizzard warning", "IS.W": "Ice storm warning", "EC.W": "Extreme cold warning",
    "WC.W": "Wind chill warning", "FW.W": "Red flag warning", "FA.A": "Areal flood watch",
    "DS.W": "Dust storm warning", "WI.Y": "Wind advisory",
    # B5 (the polygon products, D11, and the zone products added in B5)
    "FL.W": "Flood warning", "FA.W": "Areal flood warning", "FA.Y": "Areal flood advisory", "FL.A": "Flood watch",
    "FL.Y": "Flood advisory", "SQ.W": "Snow squall warning", "FF.A": "Flash flood watch",
    "WW.Y": "Winter weather advisory", "WS.A": "Winter storm watch", "HT.Y": "Heat advisory",
    "EH.W": "Excessive heat warning", "EH.A": "Excessive heat watch", "FR.Y": "Frost advisory",
    "FZ.W": "Freeze warning", "DU.Y": "Blowing dust advisory",
}
# D29 (B5 part B1): the kind word of every product the store holds, by its NWS name in lower case, for the middle of a
# row ("flood advisory", never "FA warning"). Keyed by product code (phenomenon and significance). Derived from
# PRODUCT_NAMES; tests/test_joins.py lists every code in the store and asserts a name for each.
KIND_WORDS = {code: name[:1].lower() + name[1:] for code, name in PRODUCT_NAMES.items()}
# D29: the kind word the browser's warning rows take from the map block, by phenomenon only (the browser reads an
# event's phenomenon, not its significance). Each word covers every significance the phenomenon has in the store. Part
# B2 switches the browser to the product names (map block "products", keyed by code).
PHENOMENON_KIND_WORDS = {"SV": "severe thunderstorm warning", "TO": "tornado warning",
                         "FF": "flash flood warning or watch", "FL": "flood warning, watch or advisory",
                         "FA": "flood warning or advisory", "SQ": "snow squall warning"}
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
# B5 (D11): a polygon covers a cell when it intersects the cell's square, which runs this far each side of the centre
COVER_HALF_DEG = 0.005
# B5 (D8): a row whose status opens a period (when none is open) and one whose status closes the open period
OPEN_STATUS = ("NEW", "CON", "EXT", "EXA", "EXB")
CLOSE_STATUS = ("CAN", "UPG", "EXP")
# B5 (D8): the order of rows that share a product time
STATUS_ORDER = {"NEW": 0, "CON": 1, "EXT": 2, "EXA": 3, "EXB": 4, "CAN": 5, "UPG": 6, "EXP": 7}  # a tie: CAN first
# B5 (source 1 and D8): IEM's zone and polygon requests cover the year and a month either side. A request for the
# year alone loses the rows whose product was issued in the year before and whose event begins in the year (WW.Y 2,
# HW.A 1 and HW.W 1 in the window, measured 2026-10-19), so the margin is part of the request.
MARGIN_MONTHS = 1
# B5 (source 4 and the research): the research's own window, calendar days 2021-10-19 to 2026-10-19 (UTC), which the
# research's counts use; the store's window (B1's as_of) can end a few days earlier, so the counts are kept for both
RESEARCH_START = datetime(2021, 10, 19, tzinfo=timezone.utc)
RESEARCH_END = datetime(2026, 10, 19, tzinfo=timezone.utc)
# B5 (source 4): the Census county boundaries (TIGER 2026; 56 Montana counties), read from the cache
COUNTY_URL = "https://www2.census.gov/geo/tiger/TIGER2026/COUNTY/tl_2026_us_county.zip"
COUNTY_FILE = "counties/tl_2026_us_county.zip"
COUNTY_STATE = "30"                 # the FIPS state code of Montana
# B5 (D12): the station readings flagged for check: the two values the brief names (HVR 105.1 kt on 2025-02-20 and MSO
# 86.0 kt on 2025-05-09). Each is shown with the flag words; no other reading is flagged by this list.
FLAG_CHECK = {("HVR", "2025-02-20"), ("MSO", "2025-05-09")}
# B5 (source 6): the LSR type words that changed in 2023 and 2024 fold into one word per kind; every other label shows
# its own words, lower case. The labels and their dates are read from the store's table (type_words in the index).
LSR_KIND_FOLD = {"HEAVY RAIN": "rain", "RAIN": "rain", "HEAVY SNOW": "snow", "SNOW": "snow",
                 "EXTR WIND CHILL": "wind chill", "WIND CHILL": "wind chill", "EXCESSIVE HEAT": "extreme heat",
                 "EXTREME HEAT": "extreme heat"}
# B5 (D15, gate 17): the hit-and-miss record. HIT_MISS_ROWS are named cases the table must hold: inside the store's
# window, and checked only when the store holds their tile (otherwise verify says why it did not run). KNOWN_HAIL_CASES
# are research values outside the window; verify writes them into the record as research_cases, never as table rows.
# D15 and gate 17 name Glendive 4.00 in (June 2021, before the window); Petrolia Lake (3.50 in, 2025) is the in-window case
# the record checks beside Lewistown (2.50 in at a 0.0 mm cell).
HIT_MISS_ROWS = (
    {"name": "Lewistown", "lat": 47.03, "lon": -109.42, "utc": "2025-06-15T22:48Z", "in": "2.50"},
    {"name": "Petrolia Lake", "lat": 46.93, "lon": -108.25, "utc": "2025-06-16T01:01Z", "in": "3.50"},
)
KNOWN_HAIL_CASES = (
    {"name": "Glendive", "lat": 47.09, "lon": -104.53, "utc": "2021-06-08T22:26Z", "in": "4.00",
     "mesh_mm_research": 14.4, "note": "a research value outside the window (June 2021); not a table row"},
)
TOWNS_FILE = Path(__file__).resolve().parent / "towns.json"
EDITION_DATE = date(2026, 4, 16)    # the effective date of the newest public zone edition the NWS page links (z_16ap26.zip,
                                    # read from its file name); each edition's own date comes from its name (D16)
# D27 (B5 part B1): the older public zone editions the NWS change history names (zone_ch_log.txt: "Effective ...
# (z_08se21.*)" and so on), oldest first. The GIS page links two editions, z_18mr25.zip (effective 18 March 2025) and
# z_16ap26.zip (16 April 2026). The six older names are requested on every build; on 2026-10-19 each returned HTTP 404
# at the NWS address, so the index records them as not published. A product issued while an unpublished edition was in
# force is placed by the IEM zone set in force at its issue time (D44; zone_placement_table and iem_sets in the index).
ZONE_EDITION_ARCHIVE = ("z_08se21.zip", "z_22mr22.zip", "z_07se22.zip", "z_13se22.zip", "z_08mr23.zip", "z_05mr24.zip")
ZONE_CHANGE_LOG_URL = "https://www.weather.gov/source/gis/Shapefiles/WSOM/zone_ch_log.txt"
# D44 (B5 part B1 completion): the Montana public zone set by date, from IEM's ugcs service ("free to use for any lawful
# purpose", as-is; simplified outlines). The set is 103 zones through 2022-09-13 12:00Z and 83 from 2022-09-13 18:00Z. The
# seven snapshots below are the ones the placement reads; the cache keeps each as iem-ugcs/valid-<time>/MT.geojson, and the
# index records its size and SHA-256. The NWS change log dates the change 7 September 2022: the products issued from then to
# 13 September 18:00Z are the changeover week.
IEM_UGCS_URL = "https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson?state=MT&valid={valid}"
IEM_UGCS_VALID = ("2021-09-15T12:00:00Z", "2022-06-01T12:00:00Z", "2022-09-10T12:00:00Z", "2022-09-13T12:00:00Z",
                  "2022-09-13T18:00:00Z", "2023-06-01T12:00:00Z", "2025-03-18T12:00:00Z")
IEM_CHANGEOVER_START = datetime(2022, 9, 7, tzinfo=timezone.utc)   # the NWS change log's date for the Montana zones (SCN 22-61)
IEM_SWITCH = datetime(2022, 9, 13, 18, 0, tzinfo=timezone.utc)     # the first set of 83 zones; the 103 set holds to 12:00Z
IEM_REMOVED_ZONES = tuple(f"MTZ{n:03d}" for n in list(range(8, 16)) + list(range(44, 56)))   # the 20 zones removed at the switch
IEM_OUTLINE_ZONES = IEM_REMOVED_ZONES + ("MTZ060",)   # placed with the IEM outline before the switch (its geometry changed)
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
    "records_what": ("Official records are NOAA's Storm Events entries. This list has the point records within 5 miles: "
                     "hail, thunderstorm wind, flood, flash flood, heavy rain, tornado, funnel cloud, lightning and debris "
                     "flow. Zone-coded records (high wind, winter storm, heavy snow and the other events NCEI codes to a "
                     "forecast zone) are for the spot's forecast zone and cover the whole zone, not this spot alone. "
                     "Wind magnitudes are in knots, with miles per hour beside them. A flood record shows NCEI's cause "
                     "as written. Records are not a complete account of every storm."),
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
    "records_cause": ", NCEI cause as written: {cause}",
    "records_row_b5": "Record: {date} {time}: {type}{cause}, {magnitude}{qualifier}, {source}, {miles} mi {bearing}",
    "records_row_here_b5": "Record: {date} {time}: {type}{cause}, {magnitude}{qualifier}, {source}, {miles} mi",
    "records_row_typed_b5": "Record: {date} {time}: {type}{cause}{qualifier}, {source}, {miles} mi {bearing}",
    "records_row_here_typed_b5": "Record: {date} {time}: {type}{cause}{qualifier}, {source}, {miles} mi",
    "records_zone_row": "Record: {date} {time}: {type}, {magnitude}{qualifier}, {source}, across zone {zone}",
    "records_zone_row_typed": "Record: {date} {time}: {type}{qualifier}, {source}, across zone {zone}",
    "records_unplaced_one": ("1 official zone record in Montana in these five years could not be placed on a zone; its "
                             "zone code is not in the zone set in force when it was issued (the IEM zone sets, About). "
                             "This is not an all-clear."),
    "records_unplaced_many": ("{n} official zone records in Montana in these five years could not be placed on a zone; "
                              "their zone codes are not in the zone set in force when they were issued (the IEM zone "
                              "sets, About). This is not an all-clear."),
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
                             "known gaps, so this is not the same as no hail."),
    "detections_row_many": "Detection: {date}: {n} detections, largest {in} in",
    "detections_row_one": "Detection: {date}: 1 detection, largest {in} in",
    # warnings
    "warnings_heading": "Warnings that covered this spot",
    "warnings_what": ("A warning is listed when its issuance polygon covered this cell or part of it when it was "
                      "issued. The times are when that polygon was in effect, which can differ from the warning's own "
                      "valid time; this sheet does not show the valid time. Tags are the forecast threat at issue time, "
                      "not what fell. The archive keeps the number only, so a value the text gave as less than shows as "
                      "that number. A report's remark and a warning's tag are the NWS's own words about the report or "
                      "the forecast threat, not a finding about this address."),
    "warnings_lag": "The newest warning in this build starts on {newest}.",
    "warnings_lag_none": "No warning start date is in this build.",
    "warnings_lead_many": "{n} warnings covered this spot between {start} and {end}.",
    "warnings_lead_one": "1 warning covered this spot between {start} and {end}.",
    "warnings_lead_none": ("No warning in the archive covered this spot between {start} and {end}. Warnings cover "
                           "areas, and a spot outside every polygon is not a statement that no storm reached it."),
    "warnings_lead_unknown": ("Warnings for this spot cannot be checked in this build, because some warnings in these "
                              "five years have no outline on file. That is not the same as no warning. This is not an "
                              "all-clear."),
    "warnings_no_outline_one": ("1 warning in these five years has no outline on file, so it cannot be matched to "
                                "this spot. This is not an all-clear."),
    "warnings_no_outline_many": ("{n} warnings in these five years have no outline on file, so they cannot be matched "
                                 "to this spot. This is not an all-clear."),
    "warnings_row": "Warning: {date} {begin} to {end}, issuance polygon in effect: {kind}, {office}; tags: {tags}",
    "warnings_tags_none": "none stated",
    # D41 (B5 part B1): the label is the significance (Warning, Watch or Advisory) and the product gives the kind word
    "warnings_row_b5": "{label}: {date} {span}: {product}, {office}, covered this cell or part of it; tags: {tags}",
    "warnings_span": "{begin} to {end}",
    "warnings_span_none": "{begin}, end not recorded",
    "warnings_tags": "; tags: {tags}",
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
    "zones_no_zone": "The forecast zone for this cell could not be determined. This is not an all-clear.",
    "zones_unplaced_one": ("1 zone product in Montana in these five years could not be placed on a zone: its zone code is "
                           "not in the zone set in force when it was issued (the IEM zone sets, About). This is not an all-clear."),
    "zones_unplaced_many": ("{n} zone products in Montana in these five years could not be placed on a zone: their zone "
                            "codes are not in the zone set in force when they were issued (the IEM zone sets, About). This is "
                            "not an all-clear."),
    # D44: a zone product placed with an IEM outline (the 20 zones removed on 13 September 2022 and MTZ060 before that change)
    # carries its note; the words of the changeover week and of the zones before the switch
    "zones_simplified": "placed with a simplified zone outline",
    "zones_simplified_suffix": " (placed with a simplified zone outline)",
    "zones_row_simplified": "Zone product: {product}, zone {zone_name} ({zone}), {note}: {events}",
    "zones_before_line_one": ("1 product for zone {zone_name} ({zone}) was issued before 13 September 2022, when that zone "
                              "changed. It is listed above and is placed with a simplified zone outline."),
    "zones_before_line_many": ("{n} products for zone {zone_name} ({zone}) were issued before 13 September 2022, when that "
                               "zone changed. They are listed above and are placed with a simplified zone outline."),
    # D48: NCEI flood and flash flood records within 5 miles, their own row (the summary reads the label and the kind)
    "flood_records_label": "Flood and flash flood records within 5 miles",
    "flood_records_kind": "Record (NCEI)",
    "flood_records_none": ("No NCEI flood or flash flood record within 5 miles in these five years. NCEI records are not a "
                           "complete record of floods."),
    "flood_records_line_one": ("1 of these is an NCEI flood or flash flood record within 5 miles; NCEI's cause is shown as "
                               "it is written."),
    "flood_records_line_many": ("{n} of these are NCEI flood or flash flood records within 5 miles; NCEI's cause is shown as "
                                "it is written."),
    # D44: the About credit for the IEM zone sets (quoted in part; the IEM's own words, with the footer's rights line)
    "about_iem_zones": ("The zone sets before 18 March 2025 and the zone outlines before 13 September 2022 come from Iowa State "
                        "University's Iowa Environmental Mesonet (IEM), from its ugcs service, which gives the public zone set "
                        "valid at a date. The IEM API disclaimer reads: \"All of these services are provided as-is and without "
                        "warranty. You are free to use these services for any lawful purpose\" (quoted in part). Its OpenAPI "
                        "description reads: \"This service is free to use for most any legal purpose.\" The IEM site footer reads "
                        "\"All rights reserved.\" The outlines of the 20 zones removed on 13 September 2022 and of MTZ060 before "
                        "that change are the IEM's simplified outlines, and their rows say so. The 83 zones in force since then "
                        "keep the NWS outlines. A product issued from 7 to 13 September 2022 is placed by the zone set that holds "
                        "its code, and is counted as placed in the changeover week."),
    "zones_fire_unavailable": ("Red flag warnings are not listed (fire weather zones were not available). "
                               "This is not an all-clear."),
    "zones_fire_none": "The fire weather zone for this cell could not be determined. This is not an all-clear.",
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
    "unavailable": ("{part} could not be loaded in this update; that is not the same as no {one}. "
                    "This is not an all-clear."),
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
    "reason_not_published": ("the NWS does not publish this zone edition at its address (HTTP 404 when checked on "
                             "2026-10-19)"),
    # B5: section headings, kind words, the radar sentence, the flag and county words, and the touch rule
    "section_flooding": "Flooding",
    "section_ice": "Ice and winter",
    "section_heat": "Heat",
    "kind_radar_estimate": "Radar estimate",
    "kind_radar_detection": "Radar detection",
    "kind_report": "Report",
    "kind_record": "Record (NCEI)",
    "kind_warning": "Warning (NWS polygon, relayed by IEM)",
    "kind_zone": "Zone product",
    "kind_county": "County product",
    "kind_station": "Station reading",
    "kind_analysis": "Analysis (NOHRSC)",
    "kind_gauge": "River gauge",
    "kind_grid": "Grid estimate",
    "kind_reference": "Reference",
    "kind_unavailable": "Data unavailable",
    "radar_sentence": "Radar estimates can miss hail that people reported and can show hail that no one reported.",
    "flag_check": "Flagged for check: this reading is high for the station and has not been checked against other sources.",
    "flag_suffix": " (flagged for check)",
    "flag_check_line": ("Readings flagged for check are shown with that flag. They are the station's own readings, not "
                        "checked against other stations."),
    "county_heading": "County products for {county_name} County ({county})",
    "county_what": ("These covered the whole county, not this spot alone. A county product is an NWS warning or watch "
                    "for a county, named by its product."),
    "county_lead_many": "{n} county products for {county_name} County between {start} and {end}.",
    "county_lead_one": "1 county product for {county_name} County between {start} and {end}.",
    "county_lead_none": ("No county product for {county_name} County between {start} and {end} is listed. That does not "
                         "mean the weather was calm."),
    "county_row": "County product: {product}, whole county {county_name} County: {events}",
    "county_unavailable": ("County products could not be loaded in this update; that is not the same as no county "
                           "products. This is not an all-clear."),
    "period_note": ("A product can show more than one span: a cancellation, upgrade or expiry closes a span, and a later "
                    "continuation or new issue opens the next."),
    "hit_miss_summary": ("At the report's own cell, radar estimates showed hail of one inch or more at fewer than half of "
                         "the NWS hail reports of one inch or more. Counting radar detections within 2 miles as well, most "
                         "reports had a radar value of one inch or more. A radar miss, where neither showed one inch or "
                         "more, is not a finding about the hail that fell."),
    "about_hit_miss": ("NWS hail reports of one inch or more were checked against the radar estimate and the radar "
                       "signatures near each report, for the same day. The radar missed many of them."),
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


def lsr_kind(typetext: str) -> str:
    """The type word a report row shows (source 6): one word for the two labels of a kind that NWS changed in 2023 and
    2024 (LSR_KIND_FOLD), otherwise the archive's own TYPETEXT in lower case."""
    text = " ".join(str(typetext).split()).upper()
    return LSR_KIND_FOLD.get(text, text.lower())


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
            "type": rec["TYPETEXT"].strip().lower(), "kind": lsr_kind(rec["TYPETEXT"]), "mag_text": mag, "unit": unit,
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
    (the nine NCEI_POINT_TYPES with coordinates: Hail, Thunderstorm Wind, Flood, Flash Flood, Heavy Rain, Tornado,
    Funnel Cloud, Lightning and Debris Flow), the zone-coded rows (CZ_TYPE Z, any type), the newest local event
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
                               "mag_kt": kt, "cause": " ".join((row.get("FLOOD_CAUSE") or "").split())})
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


def season_bounds(label: str, last: date) -> tuple[date, date]:
    """The first and last day of a July to June season (D37). last caps a season that is not complete."""
    year = int(label[:4])
    return date(year, 7, 1), min(date(year + 1, 6, 30), last)


def station_periods(rows, last: date) -> dict:
    """D37: the days each station reported, per July to June season: {"season": {label: {"n": days in the season,
    "ok": days with a peak gust value}}}, for the five seasons. n counts every day of the season (all of them are before the
    window's last day); ok counts the days with a number in the IEM daily file (kept, flagged or left out as implausible
    alike). A day with no value is missing, never reported."""
    reported = {day for day, _kt in rows}
    out = {}
    for label in SEASON_LABELS:
        first_day, end_day = season_bounds(label, last)
        out[label] = {"n": (end_day - first_day).days + 1,
                      "ok": sum(1 for day in reported if first_day <= day <= end_day)}
    return {"season": out}


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
        try:
            prod = datetime.strptime(row["utc_prodissue"].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, AttributeError):
            prod = issue                         # no product time: the issue time orders the rows (D8)
        out.append({"wfo": row["wfo"].strip(), "phen": row["phenomena"].strip(), "sig": row["significance"].strip(),
                    "eventid": row["eventid"].strip(), "status": row["status"].strip(),
                    "ugc": row["ugc"].strip(), "vtec_year": row["vtec_year"].strip(), "issue": issue,
                    "expire": expire, "gtype": row["gtype"].strip(), "prod": prod})
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


def parse_ww_shapefile(data: bytes, phen: str = "", sig: str = "") -> dict:
    """The issuance polygons of one IEM watchwarn shapefile (a zip): {"events": [...], "nulls": [...], "no_outline": n,
    "malformed": n}. Keeps NEW polygons (the issuance, not a continuation) of any polygon product (B5, D11) and skips
    county twins (GTYPE C) and EXP rows. POLY_BEG and POLY_END are UTC YYYYMMDDHHMM. A NEW polygon with no outline is
    kept in "nulls" with its codes: it never reads as no warning (D11), so the build joins it by its county codes where
    the product carries them, and counts it otherwise."""
    members = _zip_members(data)
    reader = _shape_reader(members)
    fields = [f[0] for f in reader.fields[1:]]
    need = {"WFO", "PHENOM", "GTYPE", "STATUS", "ETN", "POLY_BEG", "POLY_END", "HAILTAG", "WINDTAG",
            "TORNTAG", "DAMAGTAG", "VTEC_YR"}
    if not need <= set(fields):
        raise JoinsError(WORDS_JOINS["reason_format"])
    out, nulls, malformed = [], [], 0
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
        base = {
            "k": _s(rec["PHENOM"]) or phen, "s": _s(rec.get("SIG")) or sig, "b": beg,
            "e": end if end > beg else None,        # D6: an end not after the begin is not recorded (June 2022: 31)
            "o": _s(rec["WFO"]), "eventid": _s(rec["ETN"]), "vtec_year": _s(rec["VTEC_YR"]),
            "hail_in": hail_in, "wind_mph": wind_mph,
            "tornado": _s(rec["TORNTAG"]) or None, "damage": _s(rec["DAMAGTAG"]) or None,
        }
        rings = _rings(sr.shape)
        if not rings:
            nulls.append(base)
            continue
        base["rings"] = [[(float(x), float(y)) for x, y in ring] for ring in rings]
        out.append(base)
    return {"events": out, "nulls": nulls, "no_outline": len(nulls), "malformed": malformed}


def _s(value) -> str:
    """A DBF field as text; a blank (None) field is the empty string, never "None"."""
    return "" if value is None else str(value).strip()


def parse_county_zip(data: bytes) -> list[dict]:
    """The Montana counties from the Census TIGER 2026 county file (a zip of the shapefile; B5 source 4): the IEM code
    of each county (MTC plus its three-digit FIPS code), its name and its rings (lon, lat). Refuses a file that does not
    hold the 56 Montana counties."""
    members = _zip_members(data)
    reader = _shape_reader(members)
    fields = [f[0] for f in reader.fields[1:]]
    if not {"STATEFP", "COUNTYFP", "NAME"} <= set(fields):
        raise JoinsError(WORDS_JOINS["reason_format"])
    out = []
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        if _s(rec["STATEFP"]).zfill(2) != COUNTY_STATE:
            continue
        rings = _rings(sr.shape)
        if not rings:
            raise JoinsError(WORDS_JOINS["reason_format"])
        out.append({"zone": "MTC" + _s(rec["COUNTYFP"]).zfill(3), "name": " ".join(_s(rec["NAME"]).split()),
                    "rings": [[(float(x), float(y)) for x, y in ring] for ring in rings]})
    if len(out) != 56:
        raise JoinsError(WORDS_JOINS["reason_format"])
    out.sort(key=lambda c: c["zone"])
    return out


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


def _iem_date(stamp: str) -> datetime:
    """The UTC instant of an IEM_UGCS_VALID stamp (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_iem_ugcs(data: bytes) -> list[dict]:
    """One IEM ugcs snapshot for Montana (D44): its MTZ zones as [{"zone", "name", "rings"}], sorted by code. The file is a
    GeoJSON FeatureCollection whose features carry ugc, name and state, with a Polygon or a MultiPolygon. Raises JoinsError
    when the file is not that, a zone has no outline, a code repeats, or fewer than 10 zones are read (the refusal the NWS
    zone map gets too)."""
    try:
        doc = json.loads(_text(data))
    except ValueError:
        raise JoinsError(WORDS_JOINS["reason_format"]) from None
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
        raise JoinsError(WORDS_JOINS["reason_format"])
    out, seen = [], set()
    try:
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
                raise JoinsError(WORDS_JOINS["reason_zone_map"])
            rings = []
            for poly in polys:
                for ring in poly or []:
                    pts = [(float(p[0]), float(p[1])) for p in ring]
                    if len(pts) >= 3:
                        rings.append(pts)
            code = str(props["ugc"])
            if not rings or code in seen:
                raise JoinsError(WORDS_JOINS["reason_zone_map"])
            seen.add(code)
            out.append({"zone": code, "name": " ".join(str(props.get("name", "")).split()), "rings": rings})
    except (TypeError, ValueError, IndexError, KeyError, AttributeError):
        raise JoinsError(WORDS_JOINS["reason_format"]) from None
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


def zone_row_key(row: dict) -> tuple:
    """D17: the identity of one zone row (a row of parse_ww_csv, with its product's phen and sig). The margin requests
    of two years share their December and January rows, so one row can come back from two requests; the key is the
    row's own fields (office, product, event, status, zone, the issue, expire and product times, gtype). Checked on the
    2021 to 2026 margin files (2026-10-19): every repeated key is an identical row, so dropping the copies changes no
    field the joins read."""
    return (row["wfo"], row["phen"], row["sig"], row["eventid"], row["status"], row["ugc"], row["vtec_year"],
            row["issue"], row["expire"], row["prod"], row["gtype"])


class Context:
    """Everything one build collects: the parsed sources, the parts, and the reasons for any part that did not load."""

    def __init__(self):
        self.window_bounds = (None, None)            # set by _collect's caller (the window's UTC instants)
        self.ncei_all_points: list[dict] = []        # every Montana point row read, for the totals (verify)
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
        self.zone_placement: dict = {}                # D27: product -> edition file -> how placed -> zone groups
        self.zone_unplaced_rows: list = []            # D27: [product, code, day, edition, reason] per unplaced group
        self.iem_sets: list[dict] = []                # D44: the IEM zone sets by date (_iem_sets), oldest first
        self.iem_outline: list[dict] = []             # D44: the removed zones and MTZ060 as the set before the switch draws them
        self.zone_simplified = 0                      # D44: zone products placed with an IEM outline
        self.zone_before_cells: dict = {}             # D44: the cells each removed zone (or MTZ060) claims before the switch
        self.zone_products_renumbered = 0             # products placed under a code their edition renamed (D16)
        self.zone_products_fire_missing = 0           # red flag products when the fire zones did not load (D7)
        self.zone_records_renumbered = 0              # NCEI zone rows placed under a renamed code (D16)
        self.fire_map: list | None = None             # the fire weather zones (D7); None when they did not load
        self.fire_reason: str | None = None
        self.fire_events: dict[str, list] = {}        # fire zone code -> its red flag events in the window
        # B5: the polygon events of every year read (for the town point check, D11), the outline-less polygons, the
        # county rows of the polygon products (a null polygon joins by them), the Montana counties, and the counts
        self.ww_all: list[dict] = []
        self.ww_nulls: list[dict] = []
        self.poly_rows: list[dict] = []
        self.polygon_duplicates = 0
        self.zone_row_copies = 0                      # D17: zone rows an overlapping request repeated (dropped)
        self.county_map: list | None = None           # the Montana counties (D-B5 source 4); None when not loaded
        self.county_reason: str | None = None
        self.county_events: dict[str, list] = {}      # county code -> its county-only events (and joined polygons)
        self.county_unplaced = 0
        self.null_polygons = {"window": 0, "joined": 0, "unjoined": 0}
        self.vtec_counts: dict[str, dict] = {}        # product -> {"zone", "county", "polygon", "window"} (VTEC events)
        self.zone_periods = 0                         # the spans (periods) kept in the window, zone and county
        self.vtec_counts_research: dict[str, dict] = {}   # the same counts over the research window (every row read)


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
    ctx.window_bounds = (start, end)
    years = list(range(first.year, last.year + 1))
    months = _months(first, last + timedelta(days=1))

    page = fetcher.get("nws", NWS_GIS_URL, "nws/gis-page.html", refresh=True, check=check_zone_page)
    fire_page = fetcher.get("nws", NWS_FIRE_URL, "nws/fire-gis-page.html", refresh=True, check=check_fire_page)
    asos = fetcher.get("asos", ASOS_URL, "network/MT_ASOS.geojson", refresh=True,
                       check=_checker(parse_asos_rows))
    listing = fetcher.get("ncei", NCEI_DIR, "ncei/listing.html", refresh=True, check=check_listing)
    counties = fetcher.get("counties", COUNTY_URL, COUNTY_FILE, check=_checker(parse_county_zip))
    page_names: list[str] = []
    if page.ok:
        page_names, _why = _take(page, zone_zip_names)
        page_names = page_names or []
    zone_name = page_names[-1] if page_names else None           # the current edition: the newest linked (D16)
    # D27: the older editions of the NWS change history are requested too; with no page there is no current edition
    edition_names = sorted(set(page_names) | set(ZONE_EDITION_ARCHIVE), key=zone_name_date) if page_names else []
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
        for phen, sig in POLYGON_PRODUCTS:
            add(("warnings", (phen, sig, year)), lambda ph=phen, sg=sig, y=year: fetcher.get(
                "ww", WW_URL, _ww_rel(ph, sg, y, True), refresh=_refresh_year(y, today),
                check=check_ww_shapefile, params=_ww_params(ph, sg, y, shapefile=True)))
            add(("polygon_rows", (phen, sig, year)), lambda ph=phen, sg=sig, y=year: fetcher.get(
                "ww", WW_URL, _ww_rel(ph, sg, y, False).replace("zones-m/", "ww-m/"),
                refresh=_refresh_year(y, today), check=_checker(parse_ww_csv),
                params=_ww_params(ph, sg, y, shapefile=False)))
        for phen, sig in ZONE_PRODUCTS:
            add(("zones", (phen, sig, year)), lambda ph=phen, sg=sig, y=year: fetcher.get(
                "zone_products", WW_URL, _ww_rel(ph, sg, y, False), refresh=_refresh_year(y, today),
                check=_checker(parse_ww_csv), params=_ww_params(ph, sg, y, shapefile=False)))
    for name in edition_names:          # every linked edition is read (D16); a file name is its own cache key
        add(("zone_map", name), lambda n=name: fetcher.get(
            "zone_map", NWS_BASE_URL + n, f"nws/{n}", check=_checker(parse_zone_map)))
    for stamp in IEM_UGCS_VALID:        # D44: the IEM zone sets by date (historical snapshots: cached, not re-pulled)
        add(("iem_ugcs", stamp), lambda s=stamp: fetcher.get(
            "iem_ugcs", IEM_UGCS_URL.format(valid=s), f"iem-ugcs/valid-{s}/MT.geojson",
            check=_checker(parse_iem_ugcs)))
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
            ctx.ncei_all_points.extend(parsed["points"])
            ctx.ncei_points.extend(r for r in parsed["points"] if start <= r["utc"] < end)
            ctx.ncei_zone_rows.extend(r for r in parsed["zone_rows"] if start <= r["utc"] < end)
            newest = parsed["newest_local"]
            if newest is not None and (ctx.ncei_newest_local is None or newest > ctx.ncei_newest_local):
                ctx.ncei_newest_local = newest
    for year in years:
        for phen, sig in POLYGON_PRODUCTS:
            label = f"{phen}.{sig} {year}"
            parsed, why = _take(by_tag[("warnings", (phen, sig, year))], lambda d, p=phen, s=sig: parse_ww_shapefile(d, p, s))
            if unit("warnings", label, parsed, why):
                stale("warnings", label, by_tag[("warnings", (phen, sig, year))])
                ctx.warnings_no_outline += parsed["no_outline"]
                ctx.malformed["warnings"] += parsed["malformed"]
                for event in parsed["events"]:
                    ctx.ww_all.append(event)
                    if start <= event["b"] < end:
                        ctx.ww_events.append(event)
                    if ctx.ww_newest is None or event["b"] > ctx.ww_newest:
                        ctx.ww_newest = event["b"]
                for event in parsed["nulls"]:
                    ctx.ww_nulls.append(event)
            rows_parsed, _why = _take(by_tag[("polygon_rows", (phen, sig, year))], parse_ww_csv)
            if rows_parsed is not None:
                ctx.poly_rows.extend(dict(row, phen=phen, sig=sig) for row in rows_parsed["rows"])
    seen_zone_rows: set = set()                 # D17: one seen-set across every year and product of the zone requests
    for year in years:
        for phen, sig in ZONE_PRODUCTS:
            label = f"{phen} {year}"
            parsed, why = _take(by_tag[("zones", (phen, sig, year))], parse_ww_csv)
            if unit("zones", label, parsed, why):
                stale("zones", label, by_tag[("zones", (phen, sig, year))])
                ctx.short_rows["zones"] += parsed["short"]
                ctx.malformed["zones"] += parsed["malformed"]
                for row in parsed["rows"]:
                    row = dict(row, phen=phen, sig=sig)
                    key = zone_row_key(row)
                    if key in seen_zone_rows:
                        ctx.zone_row_copies += 1        # a copy from the neighbouring year's request: kept once
                        continue
                    seen_zone_rows.add(key)
                    ctx.zone_rows.append(row)
    for name in edition_names:
        result = by_tag[("zone_map", name)]
        zones, why = _take(result, parse_zone_map)
        if zones is None and name in ZONE_EDITION_ARCHIVE and (
                result.status == 404 or (result.status is None and result.error == WORDS_JOINS["reason_offline"])):
            why = WORDS_JOINS["reason_not_published"]            # D27: the NWS does not publish it at its address
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
    _iem_sets(ctx, by_tag)              # D44: the IEM zone sets by date, from their snapshots
    if fire_name is None:
        ctx.fire_reason = fire_why or WORDS_JOINS["reason_zone_map"]
    else:
        fire, why = _take(by_tag[("fire_map", fire_name)], parse_zone_map)
        if fire is None:
            ctx.fire_reason = why or WORDS_JOINS["reason_zone_map"]
        else:
            ctx.fire_map = fire
    ctx.county_map, ctx.county_reason = _take(counties, parse_county_zip)
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
    _dedupe_polygons(ctx)
    if ctx.part_all_failed.get("zones"):       # D44: without the NWS zone part there are no removed-zone files either
        ctx.iem_outline = []
    return ctx


def _dedupe_polygons(ctx: Context) -> None:
    """One polygon event per VTEC event (wfo, phenomenon, significance, event number, year). The margin requests repeat
    a row that falls in two years' requests; the repeats are identical copies (checked 2026-10-19), so the first copy
    is kept and the rest are counted. The outline-less ones are de-duplicated the same way (ctx.ww_nulls)."""
    def dedupe(rows, key_of, keep_rings=True):
        seen, out, dupes = {}, [], 0
        for event in rows:
            key = key_of(event)
            if key in seen:
                dupes += 1
                if keep_rings and "rings" in event and "rings" not in out[seen[key]]:
                    out[seen[key]] = event
                continue
            seen[key] = len(out)
            out.append(event)
        return out, dupes

    def key_of(e):
        return (e["o"], e["k"], e["s"], e["eventid"], e["vtec_year"])
    ctx.ww_all, d1 = dedupe(sorted(ctx.ww_all, key=lambda e: (e["b"], key_of(e))), key_of)
    ctx.ww_events = [e for e in ctx.ww_all if _in_window(e["b"], ctx)]
    ctx.ww_nulls, d2 = dedupe(ctx.ww_nulls, key_of, keep_rings=False)
    ctx.polygon_duplicates = d1 + d2


def _in_window(when: datetime, ctx: Context) -> bool:
    start, end = ctx.window_bounds
    return start <= when < end


def _ww_params(phen: str, sig: str, year: int, shapefile: bool) -> dict:
    """The IEM watchwarn request for one product and one year. B5: the request runs from 1 December of the year before
    to 31 January of the year after (MARGIN_MONTHS on each side), since a request for the year alone loses the rows
    whose product was issued in the year before (see MARGIN_MONTHS). Rows that repeat across two years are one row."""
    params = {"simple": "1", "location_group": "states", "states[]": "MT", "timeopt": "1",
              "year1": str(year - 1), "month1": "12", "day1": "1", "hour1": "0", "minute1": "0",
              "year2": str(year + 1), "month2": "1", "day2": "31", "hour2": "23", "minute2": "59",
              "phenomena[]": phen, "significance[]": sig, "limitps": "1"}
    params["accept"] = "shapefile" if shapefile else "csv"
    return params


def _ww_rel(phen: str, sig: str, year: int, shapefile: bool) -> str:
    """The cache path of one watchwarn request (B5: the margin folders, so B2's year-only files are never mixed in)."""
    return f"ww-m/{phen}{sig}-{year}.zip" if shapefile else f"zones-m/{phen}{sig}-{year}.csv"


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


def _station_candidates(stations: list[dict], bounds: tuple) -> list[dict]:
    """D36: the stations a tile's file lists for the spot picks: every station within STATION_MILES of the tile's farthest
    corner distance beyond its centre (bounds is the tile's (south, north, west, east)), nearest the centre first, with id,
    name and position. Any point of the tile is within that corner distance of the centre, so the two nearest to any point
    of the tile that lie within STATION_MILES of it are in this list. The tile's own "stations" list stays the two nearest
    from the centre (the browser's list)."""
    if not stations:
        return []
    south, north, west, east = bounds
    lat, lon = (south + north) / 2, (west + east) / 2
    radius = max(haversine_km(lat, lon, la, lo) for la, lo in ((south, west), (south, east), (north, west), (north, east)))
    np = _np()
    dist = haversine_km(lat, lon, np.array([s["lat"] for s in stations]), np.array([s["lon"] for s in stations]))
    order = sorted(range(len(stations)), key=lambda i: (float(dist[i]), stations[i]["id"]))
    limit_km = STATION_MILES * MILE_KM + radius
    return [{"id": stations[i]["id"], "name": stations[i]["name"], "lat": stations[i]["lat"], "lon": stations[i]["lon"]}
            for i in order if float(dist[i]) <= limit_km]


def station_picks(tile_doc: dict, lat: float, lon: float) -> list[dict]:
    """D36: the two nearest gust stations within STATION_MILES of (lat, lon), nearest first, with their miles from that point
    (the town point on a town page, the cell centre on the sheet). Read from the tile's candidates when the file has them,
    else from its two-station list (a file from before D36)."""
    cands = tile_doc["station_candidates"] if "station_candidates" in tile_doc else tile_doc.get("stations", [])
    return _station_near(cands, lat, lon)


def zone_before_for_key(tile_doc: dict, key: int) -> str | None:
    """D44: the removed zone (or MTZ060) that claimed this cell before the switch, from the tile's zones_before map; None
    when no removed zone claims it."""
    return _zone_for_key(tile_doc, key, "zones_before")


def _before_names(ctx: Context) -> dict:
    """D44: the names of the zones the IEM set before the switch draws and the current set does not hold (the removed zones),
    {code: name}; MTZ060 is a current zone and is not listed here."""
    current = {z["zone"] for z in ctx.zone_map}
    return {z["zone"]: z["name"] for z in ctx.iem_outline if z["zone"] not in current}


def _placement_table(ctx: Context) -> dict:
    """D44: the zone products of the window by the way each was placed, and the unplaced count with its expected value. A
    product is one zone group (VTEC event) whose first issue is in the window; changeover counts the products issued from
    7 September 2022 to 13 September 18:00Z, placed by the set that holds their code."""
    hows = collections.Counter()
    for cells in ctx.zone_placement.values():
        for counts in cells.values():
            for how, n in counts.items():
                hows[how] += n
    unplaced = len(ctx.zone_unplaced_rows)
    return {"groups": sum(hows.values()) + unplaced, "current": hows["current"], "mapped": hows["mapped"],
            "iem_set": hows["iem"], "changeover_week": hows["changeover"], "unplaced": unplaced,
            "expected_unplaced": 0, "simplified_outline": ctx.zone_simplified}


def _report_entry(row: dict, utc: datetime, record: bool) -> list:
    """A row of the events table, in the shape the index names (shapes): a report carries its type word (kind, B5) as
    the twelfth field; a record carries its magnitude in mph and knots and its FLOOD_CAUSE as written (B5) as the
    fourteenth. Positions 0 to 10 are the same in every version of the format."""
    d = utc_day_index(utc)
    t = hhmm(utc)
    lat = None if row["lat"] is None else round(row["lat"], 5)
    lon = None if row["lon"] is None else round(row["lon"], 5)
    base = [d, t, lat, lon, row["code"], row["mag_text"], row["unit"], row["qual"], row["src"], row["city"],
            row["remark"]]
    if record:
        base += [row.get("mag_mph"), row.get("mag_kt"), row.get("cause", "")]
    else:
        base += [row.get("kind", row["code"])]
    return base


def _joins_for_tile(tile: dict, ctx: Context, prep: dict, stats: dict | None = None) -> dict:
    """One tile's file. A row is not repeated here: reports and records are indexes into the events table, and a
    warning is [index into the events table, the tile's 100-bit cover]. Detections (small) are written in full. The
    zone map lists each zone's cell keys, and the counties map each county's (B5). stats, when given, collects the
    cover counts per product (D11): the centre rule's cells and the touch rule's, for the Montana cells of the tile."""
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
        centre_keys, touched = _cover_sets(event["rings"], tile)          # D11: the touch rule
        touched_set = set(touched)
        mont_touched = [k for k in touched if k in keys_in_state]
        if not mont_touched:
            continue
        if stats is not None:
            row = stats.setdefault(f"{event['k']}.{event['s']}",
                                   {"centre": 0, "touched": 0, "centre_not_touched": 0})
            row["centre"] += sum(1 for k in centre_keys if k in keys_in_state)
            row["touched"] += len(mont_touched)
            row["centre_not_touched"] += sum(1 for k in centre_keys if k not in touched_set)
        warnings.append([event["ref"], cover_hex(touched)])
    doc["warnings"] = sorted(warnings, key=lambda w: (warning_table[w[0]]["b"], warning_table[w[0]]["k"],
                                                      warning_table[w[0]]["s"], warning_table[w[0]]["o"]))

    by_zone: dict[str, list[int]] = {}
    zone_map = prep["zone_by_cell"]
    for key in tile["keys"]:
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        code = zone_map.get((row, col))
        if code:
            by_zone.setdefault(code, []).append(key)
    doc["zones"] = {code: sorted(keys) for code, keys in sorted(by_zone.items())}

    by_before: dict[str, list[int]] = {}           # D44: the removed zones (and MTZ060) before the switch
    before_by_cell = prep.get("zone_before_by_cell", {})
    for key in tile["keys"]:
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        code = before_by_cell.get((row, col))
        if code:
            by_before.setdefault(code, []).append(key)
    doc["zones_before"] = {code: sorted(keys) for code, keys in sorted(by_before.items())}

    by_fire: dict[str, list[int]] = {}
    fire_by_cell = prep.get("fire_by_cell", {})
    for key in tile["keys"]:
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        code = fire_by_cell.get((row, col))
        if code:
            by_fire.setdefault(code, []).append(key)
    doc["fire"] = {code: sorted(keys) for code, keys in sorted(by_fire.items())}

    by_county: dict[str, list[int]] = {}
    county_by_cell = prep.get("county_by_cell", {})
    for key in tile["keys"]:
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        code = county_by_cell.get((row, col))
        if code:
            by_county.setdefault(code, []).append(key)
    doc["counties"] = {code: sorted(keys) for code, keys in sorted(by_county.items())}

    lat_c = (south + north) / 2
    lon_c = (west + east) / 2
    doc["stations"] = _station_near(ctx.stations, lat_c, lon_c)       # the two nearest from the centre (the browser's)
    doc["station_candidates"] = _station_candidates(ctx.stations, (south, north, west, east))     # D36
    return doc


def _tile_events(doc: dict, report_table: list, record_table: list, warning_table: list) -> dict:
    """D30: the events one tile's file refers to: its reports, records and warnings, each row as the events table holds
    it, keyed by the row's index in events.json (a string key, since JSON keys are strings)."""
    return {"f": TILE_EVENTS_FORMAT, "r": doc["r"], "c": doc["c"],
            "reports": {str(i): report_table[i] for i in doc["reports"]},
            "records": {str(i): record_table[i] for i in doc["records"]},
            "warnings": {str(ref): warning_table[ref] for ref, _cover in doc["warnings"]}}


def _events_tiles_block(entries: list, referenced: dict) -> dict:
    """D30: the index's events_tiles block from (file name, raw bytes, gzip bytes) of each tile's events file, and the
    counts of the events the tile files refer to (reports, records, warnings)."""
    raw_big = max(entries, key=lambda e: (e[1], e[0]), default=("", 0, 0))
    gz_big = max(entries, key=lambda e: (e[2], e[0]), default=("", 0, 0))
    return {"format": TILE_EVENTS_FORMAT, "dir": "hail/j/" + TILE_EVENTS_DIR + "/", "count": len(entries),
            "bytes": sum(e[1] for e in entries), "gzip_bytes": sum(e[2] for e in entries),
            "largest_raw": {"file": raw_big[0], "bytes": raw_big[1]},
            "largest_gzip": {"file": gz_big[0], "bytes": gz_big[2]},
            "budget_gzip": TILE_EVENTS_BUDGET_GZIP, "referenced": dict(referenced)}


def _read_tile_events(store_dir, tile_name: str) -> tuple:
    """D30: (the events file of one tile, its bytes). A missing or unreadable file, or one in another format, raises."""
    path = Path(store_dir) / "hail" / "j" / TILE_EVENTS_DIR / f"{tile_name}.json"
    try:
        data = path.read_bytes()
        doc = json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        raise JoinsError(WORDS_JOINS["reason_no_answer"]) from None
    if doc.get("f") != TILE_EVENTS_FORMAT:
        raise JoinsError(WORDS_JOINS["reason_format"])
    return doc, data


def _cover_sets(rings, tile) -> tuple[list[int], list[int]]:
    """(centre keys, touched keys) of one polygon for one B1 tile (D11). A cell is a centre key when its centre lies inside
    the polygon (the centre rule, B2). It is a touched key when the polygon intersects the cell's square: a polygon vertex
    lies in the square, or a polygon edge crosses one of the square's four sides, or the square lies inside the polygon
    (its centre is then inside). Every centre key is a touched key. The square is half a cell each way (COVER_HALF_DEG)."""
    np = _np()
    lats, lons = [], []
    for key in range(100):
        row, col = 10 * tile["r"] + key // 10, 10 * tile["c"] + key % 10
        lat, lon = hail.cell_centre(row, col)
        lats.append(lat)
        lons.append(lon)
    lat_a, lon_a = np.array(lats), np.array(lons)
    centre = points_in_rings(lon_a, lat_a, rings)
    south, north, west, east = tile_bounds(tile["r"], tile["c"])
    vx, vy, ex1, ey1, ex2, ey2 = [], [], [], [], [], []
    for ring in rings:
        arr = np.asarray(ring, dtype=float)
        if arr.shape[0] < 2:
            continue
        nxt = np.roll(arr, -1, axis=0)
        near_v = (arr[:, 0] >= west) & (arr[:, 0] <= east) & (arr[:, 1] >= south) & (arr[:, 1] <= north)
        vx.extend(arr[near_v, 0])
        vy.extend(arr[near_v, 1])
        lo_x, hi_x = np.minimum(arr[:, 0], nxt[:, 0]), np.maximum(arr[:, 0], nxt[:, 0])
        lo_y, hi_y = np.minimum(arr[:, 1], nxt[:, 1]), np.maximum(arr[:, 1], nxt[:, 1])
        near_e = (hi_x >= west) & (lo_x <= east) & (hi_y >= south) & (lo_y <= north)
        ex1.extend(arr[near_e, 0]); ey1.extend(arr[near_e, 1])
        ex2.extend(nxt[near_e, 0]); ey2.extend(nxt[near_e, 1])
    touched = centre.copy()
    h = COVER_HALF_DEG
    if vx:
        vxa, vya = np.array(vx), np.array(vy)
        inside = ((vxa[:, None] >= lon_a[None, :] - h) & (vxa[:, None] <= lon_a[None, :] + h)
                  & (vya[:, None] >= lat_a[None, :] - h) & (vya[:, None] <= lat_a[None, :] + h))
        touched |= inside.any(axis=0)
    if ex1:
        p1 = np.stack([np.array(ex1), np.array(ey1)], axis=1)
        p2 = np.stack([np.array(ex2), np.array(ey2)], axis=1)
        q1, q2 = [], []
        for lat, lon in zip(lat_a, lon_a):          # the four sides of each cell's square, in key order
            sw, se = (lon - h, lat - h), (lon + h, lat - h)
            ne, nw = (lon + h, lat + h), (lon - h, lat + h)
            for a, b in ((sw, se), (se, ne), (ne, nw), (nw, sw)):
                q1.append(a)
                q2.append(b)
        q1, q2 = np.array(q1), np.array(q2)
        hit = _segments_cross(p1, p2, q1, q2).reshape(p1.shape[0], 100, 4)
        touched |= hit.any(axis=(0, 2))
    centre_keys = [k for k in range(100) if centre[k]]
    touched_keys = [k for k in range(100) if touched[k]]
    return centre_keys, touched_keys


def _segments_cross(p1, p2, q1, q2):
    """(E, M) booleans: whether segment i of (p1, p2) meets segment j of (q1, q2), closed segments (touching counts)."""
    np = _np()
    P1, P2 = p1[:, None, :], p2[:, None, :]
    Q1, Q2 = q1[None, :, :], q2[None, :, :]

    def orient(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])

    d1, d2 = orient(Q1, Q2, P1), orient(Q1, Q2, P2)
    d3, d4 = orient(P1, P2, Q1), orient(P1, P2, Q2)
    hit = (d1 * d2 <= 0) & (d3 * d4 <= 0)
    hit &= (np.maximum(P1[..., 0], P2[..., 0]) >= np.minimum(Q1[..., 0], Q2[..., 0])) \
        & (np.maximum(Q1[..., 0], Q2[..., 0]) >= np.minimum(P1[..., 0], P2[..., 0]))
    hit &= (np.maximum(P1[..., 1], P2[..., 1]) >= np.minimum(Q1[..., 1], Q2[..., 1])) \
        & (np.maximum(Q1[..., 1], Q2[..., 1]) >= np.minimum(P1[..., 1], P2[..., 1]))
    return hit


def _tile_cover(rings, tile) -> list[int]:
    """The keys (0 to 99) of the tile's cells that the polygon touches (D11): the 100 bits of the cover."""
    return _cover_sets(rings, tile)[1]


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
    # D44: the cells each removed zone (and MTZ060, by its IEM outline) claims before the switch, like the zones path
    prep["zone_before_by_cell"] = assign_zones(cells, ctx.iem_outline) if ctx.iem_outline else {}
    prep["fire_by_cell"] = assign_zones(cells, ctx.fire_map, near_km=0.0) if ctx.fire_map else {}
    # B5 (source 4): the county of every Montana cell, by its centre; a cell no county polygon holds (the Census outline
    # and the state's outline differ along the border) takes the nearest county edge within ZONE_NEAR_KM, as a zone does
    prep["county_by_cell"], prep["county_nearest"] = {}, 0
    if ctx.county_map:
        strict = assign_zones(cells, ctx.county_map, near_km=0.0)
        missing = [c for c in cells if (c[0], c[1]) not in strict]
        near = assign_zones(missing, ctx.county_map, near_km=ZONE_NEAR_KM) if missing else {}
        prep["county_by_cell"] = {**strict, **near}
        prep["county_nearest"] = len(near)
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


def _iem_sets(ctx: Context, by_tag: dict) -> None:
    """Fill ctx.iem_sets (D44): one record per snapshot in IEM_UGCS_VALID, oldest first, with the zones it holds (None when
    it did not load, with the reason), its codes, its size and its SHA-256. A snapshot that did not load makes the zones part
    partial, and the products its set would place are counted as unplaced. ctx.iem_outline takes the zones the set before
    the switch draws for the removed zones and MTZ060 (their IEM outlines)."""
    for stamp in IEM_UGCS_VALID:
        result = by_tag[("iem_ugcs", stamp)]
        zones, why = _take(result, parse_iem_ugcs)
        data = result.data if result.ok else None
        snap = {"valid": stamp, "date": _iem_date(stamp), "file": f"iem-ugcs/valid-{stamp}/MT.geojson", "zones": zones,
                "why": why, "bytes": None if data is None else len(data),
                "sha256": None if data is None else hashlib.sha256(data).hexdigest(), "codes": set()}
        if zones is not None:
            snap["codes"] = {z["zone"] for z in zones}
        ctx.iem_sets.append(snap)
        if zones is None:
            ctx.part_failures["zones"].append(f"zone set valid {stamp[:16].replace('T', ' ')}Z")
            ctx.part_reason.setdefault("zones", why or WORDS_JOINS["reason_no_answer"])
    before = [s for s in ctx.iem_sets if s["zones"] is not None and s["date"] < IEM_SWITCH]
    if before:
        ctx.iem_outline = [z for z in before[-1]["zones"] if z["zone"] in IEM_OUTLINE_ZONES]


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


def _iem_in_force(ctx: Context, when: datetime) -> dict | None:
    """The IEM zone set in force at when (D44): the newest snapshot valid at or before it (of all the snapshots, loaded or
    not, so a set that failed is never replaced by an older one); a time before the first takes the first. None when
    there are no snapshots."""
    if not ctx.iem_sets:
        return None
    chosen = ctx.iem_sets[0]
    for snap in ctx.iem_sets:
        if snap["date"] <= when:
            chosen = snap
    return chosen


def _place_iem(ctx: Context, names: set, code: str, issued: datetime) -> dict:
    """D44: the placement of a zone code filed by a product issued while an IEM zone set is the one in force. The set in
    force at the issue time must hold the code. The outline is the IEM's (simplified) for the 20 zones removed on 13
    September 2022 and for MTZ060 before the switch; every other zone keeps the NWS outline of the current edition (names).
    A product from 7 September 2022 to 13 September 18:00Z is placed by the set that holds its code and counted as
    "changeover" (the set in force is the 103 set until 12:00Z, and it holds every code of the 83 set)."""
    snap = _iem_in_force(ctx, issued)
    how = "changeover" if IEM_CHANGEOVER_START <= issued <= IEM_SWITCH else "iem"
    if snap is None or snap["zones"] is None:
        return {"zone": None, "set": None if snap is None else snap["valid"], "how": how, "outline": None,
                "reason": "set_unread"}
    if code not in snap["codes"]:
        return {"zone": None, "set": snap["valid"], "how": how, "outline": None, "reason": "not_in_iem_set"}
    if code in IEM_OUTLINE_ZONES and issued < IEM_SWITCH:
        return {"zone": code, "set": snap["valid"], "how": how, "outline": "iem", "reason": None}
    if code not in names:
        return {"zone": None, "set": snap["valid"], "how": how, "outline": None, "reason": "not_in_current"}
    return {"zone": code, "set": snap["valid"], "how": how, "outline": "nws", "reason": None}


def _place(ctx: Context, names: set, code: str, issued: datetime) -> dict:
    """The placement of a zone code filed by a product issued at issued (D16, D27, D44). The edition in force on the issue
    day (Montana time) decides. The current edition places the code by name ("current"). A linked older edition that was
    read maps its code to a current zone ("mapped"). An archived edition the NWS does not publish is replaced by the IEM
    zone set in force (_place_iem). Any other edition that did not load leaves its products unplaced ("edition_unread").
    Returns {"zone", "set" (the edition file or the set's stamp), "how", "outline" ("nws" or "iem"), "reason"}; zone is None
    when the product is unplaced, and reason says why."""
    edition = _edition_in_force(ctx.zone_editions, _local(issued).date())
    if edition is None or not ctx.zone_editions or edition is ctx.zone_editions[-1]:
        zone = code if code in names else None
        return {"zone": zone, "set": ctx.zone_editions[-1]["file"] if ctx.zone_editions else None, "how": "current",
                "outline": "nws" if zone else None, "reason": None if zone else "not_in_current"}
    if edition["zones"] is not None:
        mapping = ctx.zone_edition_maps.get(edition["file"])
        if mapping is None:
            return {"zone": None, "set": edition["file"], "how": "mapped", "outline": None, "reason": "edition_unread"}
        mapped = mapping.get(code)
        zone = mapped if mapped in names else None
        return {"zone": zone, "set": edition["file"], "how": "mapped", "outline": "nws" if zone else None,
                "reason": None if zone else "retired_zone"}
    if edition["file"] in ZONE_EDITION_ARCHIVE:
        return _place_iem(ctx, names, code, issued)
    return {"zone": None, "set": edition["file"], "how": "mapped", "outline": None, "reason": "edition_unread"}


def _place_code(ctx: Context, names: set, code: str, issued: datetime) -> str | None:
    """The current zone a row filed under code places on, given when it was issued (D16, D44; see _place). None when no
    zone holds it."""
    return _place(ctx, names, code, issued)["zone"]


def _note_placed(ctx: Context, product: str, placement: dict) -> None:
    """D27, D44: one zone product (a VTEC group whose first issue is in the window) placed, counted per product, per set or
    edition in force and per way it was placed (the index's zone_placement). A product placed with an IEM outline is
    counted in zone_simplified."""
    cells = ctx.zone_placement.setdefault(product, {})
    counts = cells.setdefault("none" if placement["set"] is None else str(placement["set"]), {})
    counts[placement["how"]] = counts.get(placement["how"], 0) + 1
    if placement["outline"] == "iem":
        ctx.zone_simplified += 1


def _note_unplaced(ctx: Context, product: str, code: str, issued: datetime, placement: dict) -> None:
    """D27, D44: one zone product that stays unplaced, with its zone code, its issue day (Montana time), the set or edition
    in force and the reason: not_in_current (the current edition has no such zone), retired_zone (the edition in force maps
    the code to no current zone), edition_unread (an edition that did not load), not_in_iem_set (the IEM zone set in force
    does not hold the code) or set_unread (that IEM set did not load)."""
    ctx.zone_unplaced_rows.append([product, code, _local(issued).date().isoformat(),
                                   "none" if placement["set"] is None else str(placement["set"]),
                                   placement["reason"]])


def periods(rows: list[dict]) -> list[dict]:
    """D8 (B2 D33, implemented in B5): the periods of one VTEC event, from its rows in product order (the product's
    issue time, then the status order). A CAN, UPG or EXP closes the open period; a closing row with no open period
    starts one of its own, at its issue time. A NEW, CON, EXT, EXA or EXB opens a period when none is open and otherwise
    updates the open one. Each period is a span: its begin is the issue time of the row that opened it; its end is the
    expiry of the row that closed it (a cancellation or upgrade time, even at or before the begin, D26 and D31), else the
    latest expiry of its rows, or None when that is not after the begin (D6). Returns [{"begin", "end", "stop"}], where
    stop is the closing status (CAN, UPG or EXP) or None for an open period."""
    rows = sorted(rows, key=lambda r: (r["prod"], r["issue"], STATUS_ORDER.get(r["status"], 9)))
    out, cur = [], None
    for r in rows:
        status = r["status"]
        if status in OPEN_STATUS:
            if cur is None:
                cur = {"begin": r["issue"], "live": r["expire"], "stop": None, "end": None}
            elif r["expire"] is not None and (cur["live"] is None or r["expire"] > cur["live"]):
                cur["live"] = r["expire"]
        elif status in CLOSE_STATUS:
            if cur is None:
                cur = {"begin": r["issue"], "live": None, "stop": None, "end": None}
            cur["stop"], cur["end"] = status, r["expire"]
            out.append(cur)
            cur = None
        elif cur is not None and r["expire"] is not None and (cur["live"] is None or r["expire"] > cur["live"]):
            cur["live"] = r["expire"]
    if cur is not None:
        out.append(cur)
    result = []
    for p in out:
        if p["stop"] is not None:
            end = p["end"]
        else:
            end = p["live"] if (p["live"] is not None and p["live"] > p["begin"]) else None
        result.append({"begin": p["begin"], "end": end, "stop": p["stop"]})
    return result


def _zone_events(ctx: Context, start: datetime, end: datetime) -> dict:
    """{zone code: [event dicts]} for the zone-coded IEM products in the window: one event per period (D8). Rows are
    grouped by VTEC event (zone, phenomenon, significance, office, event number and year: D30); within a group the
    periods are found by periods() (B2 D33, B5). A zone product goes to its public zone (_place_code, D16); a red flag
    warning (FW) goes to its fire weather zone (D7, ctx.fire_events). A county-only event (its rows carry MTC codes and
    the same VTEC key has no zone row, B5 source 4) goes to its county (ctx.county_events). An event is counted, not
    placed, when no current zone holds its code (D11), or a red flag warning when the fire zones did not load.

    A period begins at its opening row's issue time (or at the closing row's when no row opened it), and ends at its
    cancellation, upgrade or expiry time (D26, D31) or at the latest expiry of its rows (D6). The window takes a period by
    its begin. ctx.vtec_counts counts the VTEC events (the key without the zone, B2's begin rule: the earliest NEW or CON
    issue, else the earliest issue of its rows) in the window, per product, zone-coded and county-only, which is the
    count the research gives. Known limit, now closed: an event number that NWS re-used for separate periods is one
    group, and its periods are now separate spans (D8)."""
    zone_names = {z["zone"] for z in ctx.zone_map}
    fire_names = None if ctx.fire_map is None else {z["zone"] for z in ctx.fire_map}
    county_names = None if ctx.county_map is None else {c["zone"] for c in ctx.county_map}
    groups: dict[tuple, list] = {}
    zone_keys: set = set()
    vtec: dict[tuple, dict] = {}
    for row in ctx.zone_rows:
        if row["gtype"] not in ("C", "Z", "P", ""):
            continue
        code = row["ugc"]
        if code.startswith("MTZ"):
            level = "zone"
        elif code.startswith("MTC"):
            level = "county"
        else:
            continue
        ekey = (row["phen"], row["sig"], row["wfo"], row["eventid"], row["vtec_year"])
        if level == "zone":
            zone_keys.add(ekey)
        groups.setdefault((level, code) + ekey, []).append(row)
        item = vtec.setdefault(ekey, {"issues": [], "new": [], "level": set()})
        item["issues"].append(row["issue"])
        if row["status"] in ("NEW", "CON"):
            item["new"].append(row["issue"])
        item["level"].add(level)
        if row["status"] == "CAN" and start <= row["issue"] < end and (row["issue"].hour, row["issue"].minute) == (0, 0):
            ctx.zone_can_midnight += 1
    counts: dict[str, dict] = {}
    research: dict[str, dict] = {}
    for ekey, item in vtec.items():
        begin = min(item["new"]) if item["new"] else min(item["issues"])
        name = f"{ekey[0]}.{ekey[1]}"
        if RESEARCH_START <= begin < RESEARCH_END:        # the research's own window, from every row read
            row = research.setdefault(name, {"zone": 0, "county": 0, "window": 0})
            row["window"] += 1
            row["zone" if "zone" in item["level"] else "county"] += 1
        if not (start <= begin < end):
            continue
        row = counts.setdefault(name, {"zone": 0, "county": 0, "window": 0})
        row["window"] += 1
        if "zone" in item["level"]:
            row["zone"] += 1
        else:
            row["county"] += 1
    ctx.vtec_counts = counts
    ctx.vtec_counts_research = research
    out: dict[str, list] = {}
    fire: dict[str, list] = {}
    county: dict[str, list] = {}
    unplaced, fire_missing = set(), set()
    renumbered = kept = 0
    for gkey in sorted(groups, key=lambda g: (g[0], g[1], g[2], g[3], g[4], g[5], g[6])):
        level, code, phen, sig, wfo, eid, yr = gkey
        rows = groups[gkey]
        if level == "county" and (phen, sig, wfo, eid, yr) in zone_keys:
            continue                              # a county twin of a zone-coded event: the zone rows carry it
        first_issue = min(r["issue"] for r in rows)
        if level == "zone":
            if phen == "FW":
                if fire_names is None:
                    fire_missing.add(gkey)
                    continue
                if code not in fire_names:
                    if start <= first_issue < end:
                        unplaced.add(gkey)
                    continue
                target, zone_code = fire, code
            else:
                placement = _place(ctx, zone_names, code, first_issue)
                zone_code = placement["zone"]
                in_window = start <= first_issue < end
                if zone_code is None:
                    if in_window:
                        unplaced.add(gkey)
                        _note_unplaced(ctx, f"{phen}.{sig}", code, first_issue, placement)
                    continue
                if in_window:
                    _note_placed(ctx, f"{phen}.{sig}", placement)
                if zone_code != code:
                    renumbered += 1
                target = out
        else:
            if county_names is None or code not in county_names:
                if start <= first_issue < end:
                    ctx.county_unplaced += 1
                continue
            target, zone_code = county, code
        for period in periods(rows):
            begin = period["begin"]
            if not (start <= begin < end):
                continue
            event = {"k": phen, "s": sig, "b": iso_utc(begin),
                     "e": None if period["end"] is None else iso_utc(period["end"]), "o": wfo}
            if period["stop"] in ZONE_STOP_STATE:
                event["st"] = ZONE_STOP_STATE[period["stop"]]
            target.setdefault(zone_code, []).append(event)
            kept += 1
    for group in (out, fire, county):
        for zone in group:
            group[zone].sort(key=lambda e: (e["b"], e["k"], e["o"]))
    ctx.zone_products_unplaced = len(unplaced)
    ctx.zone_products_renumbered = renumbered
    ctx.zone_products_fire_missing = len(fire_missing)
    ctx.fire_events = fire
    ctx.county_events = county
    ctx.zone_periods = kept
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


def _polygon_vtec(ctx: Context) -> None:
    """The polygon VTEC events of the window, per product (ctx.vtec_counts; the zone counts are set by _zone_events)."""
    for event in ctx.ww_events:
        name = f"{event['k']}.{event['s']}"
        row = ctx.vtec_counts.setdefault(name, {"zone": 0, "county": 0, "polygon": 0, "window": 0})
        row["polygon"] += 1
        row["window"] += 1
    for name, row in ctx.vtec_counts.items():
        row.setdefault("polygon", 0)


def _join_nulls(ctx: Context, start: datetime, end: datetime) -> None:
    """D11: a NEW polygon with no outline never reads as no warning. It joins by the county codes its product carries
    (the MTC rows of the same VTEC event in the product's own rows) and is counted otherwise (ctx.null_polygons)."""
    county_names = set() if ctx.county_map is None else {c["zone"] for c in ctx.county_map}
    codes: dict[tuple, set] = {}
    for row in ctx.poly_rows:
        if row["gtype"] not in ("C", "Z", "P", "") or not row["ugc"].startswith("MTC"):
            continue
        codes.setdefault((row["phen"], row["sig"], row["wfo"], row["eventid"], row["vtec_year"]), set()).add(row["ugc"])
    for event in sorted(ctx.ww_nulls, key=lambda e: (e["b"], e["k"], e["o"], e["eventid"])):
        if not (start <= event["b"] < end):
            continue
        ctx.null_polygons["window"] += 1
        key = (event["k"], event["s"], event["o"], event["eventid"], event["vtec_year"])
        found = sorted(codes.get(key, set()) & county_names)
        if not found:
            ctx.null_polygons["unjoined"] += 1
            continue
        ctx.null_polygons["joined"] += 1
        row = {"k": event["k"], "s": event["s"], "b": iso_utc(event["b"]),
               "e": None if event["e"] is None else iso_utc(event["e"]), "o": event["o"],
               "n": 1}
        for code in found:
            ctx.county_events.setdefault(code, []).append(dict(row))
    for group in ctx.county_events.values():
        group.sort(key=lambda e: (e["b"], e["k"], e["o"]))


def town_checks(ctx: Context, towns: list[dict]) -> dict:
    """D11, the town point check: each town's point against every polygon product event of 2021 to 2026, by the exact
    point-in-polygon test of the point and by the centre rule (the centre of the cell that holds the point). Every case
    where the two rules disagree is listed, with the product, the event and the cell."""
    np = _np()
    boxes = [(e, ring_bbox(e["rings"])) for e in ctx.ww_all]
    out = {"towns": [], "events_checked": len(ctx.ww_all), "pairs_tested": 0, "disagreements": []}
    for town in towns:
        lat, lon = float(town["lat"]), float(town["lon"])
        row, col = hail.cell_for(lat, lon)
        clat, clon = hail.cell_centre(row, col)
        hits_point = hits_centre = 0
        for event, (minx, miny, maxx, maxy) in boxes:
            near_point = minx <= lon <= maxx and miny <= lat <= maxy
            near_centre = minx <= clon <= maxx and miny <= clat <= maxy
            if not (near_point or near_centre):
                continue                          # outside the polygon's box, neither point is inside it
            out["pairs_tested"] += 1
            point_in = bool(points_in_rings(np.array([lon]), np.array([lat]), event["rings"])[0])
            centre_in = bool(points_in_rings(np.array([clon]), np.array([clat]), event["rings"])[0])
            hits_point += point_in
            hits_centre += centre_in
            if point_in != centre_in:
                out["disagreements"].append({
                    "town": town["name"], "product": f"{event['k']}.{event['s']}", "office": event["o"],
                    "eventid": event["eventid"], "vtec_year": event["vtec_year"], "begin": iso_utc(event["b"]),
                    "point_inside": point_in, "centre_inside": centre_in, "cell": [row, col]})
        out["towns"].append({"town": town["name"], "cell": [row, col], "point_inside": hits_point,
                             "centre_inside": hits_centre})
    return out


def _part_state(ctx: Context, part: str) -> str:
    """The state of one part as the index block names it: unavailable, partial or loaded (D16)."""
    if ctx.part_all_failed.get(part):
        return "unavailable"
    return "partial" if ctx.part_failures.get(part) else "loaded"


def towns_polygon_file(ctx: Context, towns: list[dict]) -> dict:
    """D38: for each town, every polygon product event of the window whose outline contains the town point (the exact
    point-in-polygon test, D11; no cell), with its event id (the index in the events table's warnings), the product code,
    the office, and the begin and the end (UTC; null when no end). The town pages count from this file ("covered this
    spot"); the sheet counts the cell covers ("covered this cell or part of it"); towns_file_check compares the two."""
    np = _np()
    boxes = [(e, ring_bbox(e["rings"])) for e in ctx.ww_events]
    state = _part_state(ctx, "warnings")
    out = {}
    for town in towns:
        lat, lon = float(town["lat"]), float(town["lon"])
        row, col = hail.cell_for(lat, lon)
        found = []
        for event, (minx, miny, maxx, maxy) in boxes:
            if not (minx <= lon <= maxx and miny <= lat <= maxy):
                continue
            if bool(points_in_rings(np.array([lon]), np.array([lat]), event["rings"])[0]):
                found.append([event["ref"], f"{event['k']}.{event['s']}", event["o"], iso_utc(event["b"]),
                              None if event["e"] is None else iso_utc(event["e"])])
        found.sort(key=lambda r: (r[3], r[1], r[2], r[0]))
        out[town["slug"]] = {"name": town["name"], "lat": lat, "lon": lon, "cell": [row, col], "events": found}
    # an unavailable or partial warnings part is said in the file: a town with no event here is not "no warning"
    reason = None if state == "loaded" else ctx.part_reason.get("warnings") or WORDS_JOINS["reason_no_answer"]
    return {"f": TOWNS_FORMAT, "d0": hail.D0.isoformat(), "state": state, "reason": reason, "towns": out}


def _towns_file_block(doc: dict, size: int) -> dict:
    """The index's towns_file block (D38): the format, the file, the towns, the town-event pairs and the bytes."""
    pairs = sum(len(town["events"]) for town in doc["towns"].values())
    return {"format": TOWNS_FORMAT, "file": f"hail/j/{TOWNS_NAME}", "towns": len(doc["towns"]), "events": pairs,
            "bytes": size}


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
    _polygon_vtec(ctx)
    for event in ctx.ww_all:                         # the research window, from every polygon read (B5)
        if RESEARCH_START <= event["b"] < RESEARCH_END:
            row = ctx.vtec_counts_research.setdefault(f"{event['k']}.{event['s']}",
                                                      {"zone": 0, "county": 0, "polygon": 0, "window": 0})
            row["polygon"] += 1
            row["window"] += 1
    _join_nulls(ctx, start, end)
    towns = json.loads(TOWNS_FILE.read_text(encoding="utf-8"))
    town_check = town_checks(ctx, towns) if ctx.ww_all else {"towns": [], "events_checked": 0, "pairs_tested": 0,
                                                              "disagreements": []}
    log(f"joins: zones assigned to {len(prep['zone_by_cell'])} of {len(prep['cells'])} Montana cells; "
        f"counties to {len(prep['county_by_cell'])}")

    ctx.zone_before_cells = dict(collections.Counter(prep["zone_before_by_cell"].values()))
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
        warning_table.append({"k": event["k"], "s": event["s"], "b": iso_utc(event["b"]),
                              "e": None if event["e"] is None else iso_utc(event["e"]),
                              "o": event["o"],
                              "tags": {"hail_in": event["hail_in"], "wind_mph": event["wind_mph"],
                                       "tornado": event["tornado"], "damage": event["damage"]}})
    prep["report_table"], prep["record_table"], prep["warning_table"] = report_table, record_table, warning_table
    events_bytes = _compact({"f": EVENTS_FORMAT, "d0": hail.D0.isoformat(), "reports": report_table,
                             "records": record_table, "warnings": warning_table})
    cover_stats: dict[str, dict] = {}
    county_names = {} if ctx.county_map is None else {c["zone"]: c["name"] for c in ctx.county_map}

    stage = Path(tempfile.mkdtemp(prefix=".joins-stage-", dir=str(root)))
    try:
        hail_dir = stage / "hail"
        for sub in ("j", "z", "s"):
            (hail_dir / sub).mkdir(parents=True)
        (hail_dir / "j" / EVENTS_NAME).write_bytes(events_bytes)
        tile_bytes = 0
        largest = (0, "")
        totals = {"reports": 0, "records": 0, "detections": 0, "warnings": 0, "tiles_with_warnings": 0}
        (hail_dir / "k").mkdir(parents=True)
        (hail_dir / "j" / TILE_EVENTS_DIR).mkdir(parents=True)
        events_tiles = {"entries": [], "referenced": {"reports": 0, "records": 0, "warnings": 0}}
        for tile in tiles:
            doc = _joins_for_tile(tile, ctx, prep, cover_stats)
            data = _compact(doc)
            name = f"{tile['name']}.json"
            (hail_dir / "j" / name).write_bytes(data)
            tile_bytes += len(data)
            if len(data) > largest[0]:
                largest = (len(data), name)
            # D30: the events this tile refers to, beside events.json (hail/j/e/<tile>.json)
            edata = _compact(_tile_events(doc, report_table, record_table, warning_table))
            egz = len(gzip.compress(edata, compresslevel=9, mtime=0))
            (hail_dir / "j" / TILE_EVENTS_DIR / name).write_bytes(edata)
            events_tiles["entries"].append((name, len(edata), egz))
            for kind, refs in (("reports", doc["reports"]), ("records", doc["records"]),
                               ("warnings", doc["warnings"])):
                events_tiles["referenced"][kind] += len(refs)
            totals["reports"] += len(doc["reports"])
            totals["records"] += len(doc["records"])
            totals["detections"] += len(doc["detections"])
            totals["warnings"] += len(doc["warnings"])
            totals["tiles_with_warnings"] += 1 if doc["warnings"] else 0
        log(f"joins: wrote {len(tiles)} tile files ({tile_bytes} bytes; largest {largest[1]} {largest[0]} bytes) "
            f"and the events table ({len(events_bytes)} bytes)")
        towns_doc = towns_polygon_file(ctx, towns)                    # D38: the town point test, written with the tiles
        towns_bytes = _compact(towns_doc)
        (hail_dir / "j" / TOWNS_NAME).write_bytes(towns_bytes)
        log(f"joins: wrote the town polygon file ({len(towns_bytes)} bytes; "
            f"{_towns_file_block(towns_doc, len(towns_bytes))['events']} town and polygon pairs)")

        zone_list = [z["zone"] for z in ctx.zone_map]
        z_bytes = 0
        for zone in ctx.zone_map:
            doc = {"f": ZONE_FORMAT, "zone": zone["zone"], "name": zone["name"],
                   "events": zone_events.get(zone["zone"], []), "records": zone_records.get(zone["zone"], [])}
            data = _compact(doc)
            (hail_dir / "z" / f"{zone['zone']}.json").write_bytes(data)
            z_bytes += len(data)
        for code, name in sorted(_before_names(ctx).items()):      # D44: the removed zones get their own files
            doc = {"f": ZONE_FORMAT, "zone": code, "name": name, "events": zone_events.get(code, []),
                   "records": zone_records.get(code, [])}
            data = _compact(doc)
            (hail_dir / "z" / f"{code}.json").write_bytes(data)
            z_bytes += len(data)
        for zone in ctx.fire_map or []:
            doc = {"f": ZONE_FORMAT, "kind": "fire", "zone": zone["zone"], "name": zone["name"],
                   "events": ctx.fire_events.get(zone["zone"], []), "records": []}
            data = _compact(doc)
            (hail_dir / "z" / f"fire-{zone['zone']}.json").write_bytes(data)
            z_bytes += len(data)

        k_bytes = 0
        county_files = 0
        for county in ctx.county_map or []:
            doc = {"f": COUNTY_FORMAT, "county": county["zone"], "name": county["name"],
                   "events": ctx.county_events.get(county["zone"], [])}
            data = _compact(doc)
            (hail_dir / "k" / f"{county['zone']}.json").write_bytes(data)
            k_bytes += len(data)
            county_files += 1
        s_bytes = 0
        station_days_total = 0
        station_dropped = 0
        station_index = []
        dropped_list, flagged_list = [], []
        for st in ctx.stations:
            days = []
            dropped = 0
            for day, kt in sorted(ctx.station_days.get(st["id"], []), key=lambda x: x[0]):
                if not (first <= day <= last):
                    continue
                kind = station_day_kind(kt)
                if kind == "dropped":
                    dropped += 1
                    dropped_list.append({"station": st["id"], "date": day.isoformat(), "kt": round(kt, 1)})
                elif kind == "keep":
                    flag = 1 if (st["id"], day.isoformat()) in FLAG_CHECK else 0
                    days.append(station_day_row(day, kt) + [flag])
                    if flag:
                        flagged_list.append({"station": st["id"], "date": day.isoformat(), "kt": round(kt, 1)})
            station_dropped += dropped
            station_days_total += len(days)
            doc = {"f": STATION_FORMAT, "id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                   "days": days, "dropped": dropped,
                   "periods": station_periods(ctx.station_days.get(st["id"], []), last)}
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
                             {"tiles": tile_bytes, "events": len(events_bytes), "z": z_bytes, "s": s_bytes,
                              "k": k_bytes},
                             station_days_total, station_dropped, counts, all_station_years, today, fetcher, t0,
                             {"reports": len(report_table), "records": len(record_table),
                              "warnings": len(warning_table)})
        block.update(_b5_block(ctx, cover_stats, county_names, county_files, k_bytes, town_check, dropped_list,
                               flagged_list))
        block["counties"]["cells_without_county"] = len(prep["cells"]) - len(prep["county_by_cell"])
        block["counties"]["cells_by_nearest_edge"] = prep["county_nearest"]
        block["vtec_counts_research"] = {k: dict(v) for k, v in sorted(ctx.vtec_counts_research.items())}
        block["research_window"] = [RESEARCH_START.date().isoformat(), RESEARCH_END.date().isoformat()]
        block["events_tiles"] = _events_tiles_block(events_tiles["entries"], events_tiles["referenced"])
        block["towns_file"] = _towns_file_block(towns_doc, len(towns_bytes))
        new_index = dict(index)
        new_index[INDEX_KEY] = block
        (hail_dir / "index.json").write_bytes(_pretty(new_index))
        _finish_manifest(root, stage, block)
        for sub in ("j", "z", "s", "k"):
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
        "unavailable_units": {p: ctx.part_hard[p] for p in PARTS if ctx.part_hard[p]},
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
        "zone_placement": {p: {e: dict(sorted(h.items())) for e, h in sorted(cells.items())}
                           for p, cells in sorted(ctx.zone_placement.items())},
        "zone_placement_table": _placement_table(ctx),
        "iem_sets": [{"valid": s["valid"], "file": s["file"], "bytes": s["bytes"], "sha256": s["sha256"],
                      "zones": None if s["zones"] is None else len(s["zones"]),
                      "state": "loaded" if s["zones"] is not None else "unavailable", "reason": s["why"]}
                     for s in ctx.iem_sets],
        "zones_before": {"codes": sorted(z["zone"] for z in ctx.iem_outline),
                         "cells": {code: n for code, n in sorted(ctx.zone_before_cells.items())}},
        "zone_unplaced_rows": sorted(ctx.zone_unplaced_rows, key=lambda r: (r[0], r[2], r[1], r[3])),
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
        "zone_list_before": sorted(_before_names(ctx)),
        "zone_names": {**_before_names(ctx), **{z["zone"]: z["name"] for z in ctx.zone_map}},
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
        "shapes": {"report": ["d", "t", "lat", "lon", "code", "mag_text", "unit", "qual", "src", "city", "remark",
                              "kind"],
                   "record": ["d", "t", "lat", "lon", "code", "mag_text", "unit", "qual", "src", "city", "remark",
                              "mag_mph", "mag_kt", "cause"],
                   "warning": ["k", "b", "e", "o", "tags", "s"],
                   "detection": ["d", "t", "lat", "lon", "size_hundredths_in"],
                   "station_day": ["d", "mph", "kt", "flag"],
                   "county_event": ["k", "s", "b", "e", "o", "st", "n"]},
        "tile": {"reports": "indexes into events.reports, sorted by the row's first five fields",
                 "records": "indexes into events.records, sorted the same way",
                 "warnings": "[index into events.warnings, cover]",
                 "detections": "[d, t, lat, lon, size_hundredths_in]",
                 "zones": "{zone code: [cell keys]}",
                 "fire": "{fire weather zone code: [cell keys]}",
                 "counties": "{county code (MTC plus FIPS): [cell keys]} (B5: each Montana cell is in one county)",
                 "stations": "[{id, name, lat, lon, miles}]"},
        "cover": ("25 lower-case hex digits; bit k (the cell key 0 to 99) is set when the polygon touches the cell's "
                  "square (D11: a vertex in it, an edge across its side, or its centre inside)"),
        "montana_time": montana_transitions(first_utc.year - 1, last_utc.year + 1),
        "sources": {src: dict(row, **({"served_from_cache_since": fetcher.served_since[src]}
                                      if src in fetcher.served_since else {}))
                    for src, row in fetcher.stats.items()},
        "failures": fetcher.failures[:50],
        "failure_count": len(fetcher.failures),
    }



def _b5_block(ctx: Context, cover_stats: dict, county_names: dict, county_files: int, k_bytes: int,
              town_check: dict, dropped_list: list, flagged_list: list) -> dict:
    """The B5 additions to the index's joins block: the cover counts per product (D11), the counties (source 4), the
    VTEC and period counts (source 4, D8), the polygon null joins (D11), the town point check (D11), the type words of
    the LSR labels (source 6), the station readings dropped and flagged (D12), and the NCEI totals (source 5)."""
    vtec = {}
    for name in sorted(ctx.vtec_counts):
        vtec[name] = dict(ctx.vtec_counts[name])
    cover = {}
    for name in sorted(cover_stats):
        row = cover_stats[name]
        cover[name] = dict(row, added=row["touched"] - row["centre"])
    words: dict[str, dict] = {}
    for r in ctx.lsr:
        entry = words.setdefault(r["type"].upper(), {"word": r["kind"], "rows": 0, "first": None, "last": None})
        entry["rows"] += 1
        day = r["utc"].date().isoformat()
        entry["first"] = day if entry["first"] is None or day < entry["first"] else entry["first"]
        entry["last"] = day if entry["last"] is None or day > entry["last"] else entry["last"]
    return {
        "cover_counts": cover,
        "counties": {"state": "loaded" if ctx.county_map is not None else "unavailable",
                     "reason": None if ctx.county_map is not None else ctx.county_reason,
                     "count": len(ctx.county_map or []), "names": county_names, "bytes": k_bytes,
                     "files": county_files, "cells_without_county": None,
                     "county_events": sum(len(v) for v in ctx.county_events.values()),
                     "unplaced": ctx.county_unplaced},
        "vtec_counts": vtec,
        "zone_periods": ctx.zone_periods,
        "polygon_duplicates_dropped": ctx.polygon_duplicates,
        "zone_row_copies_dropped": ctx.zone_row_copies,
        "polygon_nulls": {"no_outline": len(ctx.ww_nulls), **ctx.null_polygons},
        "town_checks": town_check,
        "type_words": {k: words[k] for k in sorted(words)},
        "station_dropped_readings": dropped_list,
        "station_flagged_readings": flagged_list,
        "ncei_totals": _ncei_totals(ctx),
    }


def _ncei_totals(ctx: Context) -> dict:
    """The NCEI Montana point rows of the new types, by type: every year read (the totals) and the window."""
    out: dict[str, dict] = {}
    for row in ctx.ncei_all_points:
        name = row["code"]
        entry = out.setdefault(name, {"total": 0, "window": 0})
        entry["total"] += 1
    for row in ctx.ncei_points:
        out[row["code"]]["window"] = out.get(row["code"], {}).get("window", 0) + 1
    return {k: out[k] for k in sorted(out)}


def _finish_manifest(root: Path, stage: Path, block: dict) -> None:
    """Write the staged manifest: B1's entries that remain, the new j, z and s files, and the staged index (which
    build() wrote into the stage before this call)."""
    old = json.loads((root / "hail" / "manifest.json").read_text(encoding="utf-8"))
    files = {rel: meta for rel, meta in old.get("files", {}).items()
             if not rel.startswith(("hail/j/", "hail/z/", "hail/s/", "hail/k/", "hail/index.json"))}
    hail_stage = stage / "hail"
    for sub in ("j", "z", "s", "k"):
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
                           "stations": block["stations"], "bytes": block["bytes"], "state": block["state"],
                           "counties": block.get("counties", {}).get("count", 0),
                           "events_tiles": block.get("events_tiles", {}).get("count", 0)}
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
                   store_dir=None, events: dict | None = None, spot: tuple | None = None) -> dict:
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
    zone_before = zone_before_for_key(tile_doc, key)
    fire = _zone_for_key(tile_doc, key, "fire")
    county = _zone_for_key(tile_doc, key, "counties")
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
        if zone_before and zone_before != zone and store_dir:      # D44: the removed zone's records before the switch
            try:
                bdoc = _read_part_file(store_dir, f"z/{zone_before}.json", ZONE_FORMAT)
            except JoinsError as exc:
                zone_lost, bdoc = str(exc), {}
            for r in bdoc.get("records", []):
                when = utc_from_row(r[0], r[1])
                if when < IEM_SWITCH:
                    rows.append((when, r, None, zone_before))
        rows.sort(key=lambda x: x[0], reverse=True)
        sec["lead"] = _records_lead(len(rows), newest_ncei, ftn, w)
        for utc, r, dist, zone_code in rows:
            if zone_code is None:
                text = _record_text(utc, r, dist, centre_lat, centre_lon, r[2], r[3], w)
            else:
                text = _zone_record_text(utc, r, zone_code, w)
                if zone_code in IEM_OUTLINE_ZONES and utc < IEM_SWITCH:
                    text += w["zones_simplified_suffix"]
            sec["rows"].append({"text": text, "remark": None, "utc": iso_utc(utc)})
        flood_n = sum(1 for _utc, r, _dist, zc in rows if zc is None and r[4] in FLOOD_RECORD_CODES)     # D48
        if flood_n:
            sec["lines"].append(w["flood_records_line_one" if flood_n == 1 else "flood_records_line_many"]
                                .format(n=flood_n))
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
            rows.append((parse_iso_utc(item["b"]), None if item["e"] is None else parse_iso_utc(item["e"]), item))
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
        public_items, red_items, county_items = [], [], []
        zone_lost = fire_lost = county_lost = None     # D27: a zone or county file that did not load (its reason)
        before_items = []                              # D44: the removed zone's products before the switch
        if zone and store_dir:
            try:
                zdoc = _read_part_file(store_dir, f"z/{zone}.json", ZONE_FORMAT)
            except JoinsError as exc:
                zone_lost, zdoc = str(exc), {}
            for ev in zdoc.get("events", []):
                begin, end_at = _zone_span(ev)
                when = _zone_when(begin, end_at)
                if when is not None and start <= when.date() <= end:
                    if zone in IEM_OUTLINE_ZONES and when < IEM_SWITCH:     # D44: MTZ060 before the switch, IEM outline
                        before_items.append((begin, end_at, ev.get("st"), ev, zone))
                    else:
                        public_items.append((begin, end_at, ev.get("st"), ev))
        if zone_before and zone_before != zone and store_dir:
            try:
                bzdoc = _read_part_file(store_dir, f"z/{zone_before}.json", ZONE_FORMAT)
            except JoinsError as exc:
                zone_lost, bzdoc = str(exc), {}
            for ev in bzdoc.get("events", []):
                begin, end_at = _zone_span(ev)
                when = _zone_when(begin, end_at)
                if when is not None and start <= when.date() <= end and when < IEM_SWITCH:
                    before_items.append((begin, end_at, ev.get("st"), ev, zone_before))
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
        county_name = (block.get("counties", {}).get("names", {}).get(county, county)).replace(" County", "") \
            if county else None
        if county and store_dir:           # B5: the cell's county products (whole-county, not this spot alone)
            try:
                kdoc = _read_part_file(store_dir, f"k/{county}.json", COUNTY_FORMAT)
            except JoinsError as exc:
                county_lost, kdoc = str(exc), {}
            for ev in kdoc.get("events", []):
                begin, end_at = _zone_span(ev)
                when = _zone_when(begin, end_at)
                if when is not None and start <= when.date() <= end:
                    county_items.append((begin, end_at, ev.get("st"), ev))
        sec["lead"] = (w["zones_no_zone"] if not zone else
                       _zone_lead(len(public_items) + sum(1 for x in before_items if x[4] == zone), zone_name, zone, ftn, w))
        grouped: dict[str, list] = {}
        for begin, end_at, st, ev in public_items:
            name = PRODUCT_NAMES.get(f"{ev['k']}.{ev['s']}", f"{ev['k']}.{ev['s']}")
            grouped.setdefault(name, []).append((begin, end_at, st))
        before_grouped: dict[tuple, list] = {}
        before_codes: dict[str, int] = {}
        for begin, end_at, st, ev, bcode in before_items:
            name = PRODUCT_NAMES.get(f"{ev['k']}.{ev['s']}", f"{ev['k']}.{ev['s']}")
            before_grouped.setdefault((name, bcode), []).append((begin, end_at, st))
            before_codes[bcode] = before_codes.get(bcode, 0) + 1
        for begin, end_at, st, ev in red_items:
            name = PRODUCT_NAMES.get(f"{ev['k']}.{ev['s']}", f"{ev['k']}.{ev['s']}")
            name = w["fire_product"].format(product=name, zone_name=fire_zone_name, zone=fire)
            grouped.setdefault(name, []).append((begin, end_at, st))
        for name in sorted(grouped, key=lambda n: min(_zone_when(x[0], x[1]) for x in grouped[n]), reverse=True):
            items = sorted(grouped[name], key=lambda x: _zone_when(x[0], x[1]))
            events_text = "; ".join(_zone_event_text(b, e, st, w) for b, e, st in items)
            sec["rows"].append({"text": w["zones_row"].format(product=name, events=events_text), "remark": None,
                                "utc": None})
        for key in sorted(before_grouped, key=lambda k: min(_zone_when(x[0], x[1]) for x in before_grouped[k]),
                          reverse=True):
            name, bcode = key
            items = sorted(before_grouped[key], key=lambda x: _zone_when(x[0], x[1]))
            events_text = "; ".join(_zone_event_text(b, e, st, w) for b, e, st in items)
            bname = block.get("zone_names", {}).get(bcode, bcode)
            sec["rows"].append({"text": w["zones_row_simplified"].format(product=name, zone_name=bname, zone=bcode,
                                                                         note=w["zones_simplified"],
                                                                         events=events_text),
                                "remark": None, "utc": None})
        for bcode, n in sorted(before_codes.items()):
            bname = block.get("zone_names", {}).get(bcode, bcode)
            key_name = "zones_before_line_one" if n == 1 else "zones_before_line_many"
            sec["lines"].append(w[key_name].format(n=n, zone_name=bname, zone=bcode))
        unplaced = block.get("zone_products_unplaced", 0)
        if unplaced:
            sec["lines"].append(w["zones_unplaced_one" if unplaced == 1 else "zones_unplaced_many"].format(
                n=f"{unplaced:,}"))
        if county:
            if block.get("counties", {}).get("state") != "loaded" or county_lost:
                sec["lines"].append(w["county_unavailable"])
            else:
                county_grouped: dict[str, list] = {}
                for begin, end_at, st, ev in county_items:
                    name = PRODUCT_NAMES.get(f"{ev['k']}.{ev['s']}", f"{ev['k']}.{ev['s']}")
                    county_grouped.setdefault(name, []).append((begin, end_at, st))
                county_n = len(county_items)
                ckw = dict(ftn, county_name=county_name, county=county)
                if county_n == 0:
                    sec["lines"].append(w["county_lead_none"].format(**ckw))
                else:
                    key_name = "county_lead_one" if county_n == 1 else "county_lead_many"
                    sec["lines"].append(w[key_name].format(n=county_n, **ckw))
                for name in sorted(county_grouped, key=lambda n: min(_zone_when(x[0], x[1]) for x in county_grouped[n]),
                                   reverse=True):
                    items = sorted(county_grouped[name], key=lambda x: _zone_when(x[0], x[1]))
                    events_text = "; ".join(_zone_event_text(b, e, st, w) for b, e, st in items)
                    sec["rows"].append({"text": w["county_row"].format(product=name, county_name=county_name,
                                                                       events=events_text), "remark": None,
                                        "utc": None})
        if fire_state != "loaded" or fire_lost:       # a fire zone file that did not load: no red flag lead
            sec["lines"].append(w["zones_fire_unavailable"])
        elif not fire:
            sec["lines"].append(w["zones_fire_none"])
        else:
            sec["fire_lead"] = _fire_lead(len(red_items), fire_zone_name, fire, ftn, w)
        if parts.get("zones") == "partial":
            sec["unavailable"] = _unavailable_text("zones", reasons.get("zones"), partial.get("zones"))
        if county_lost:
            sec["lines"].append(w["county_unavailable"])
        if zone_lost:       # D27: no lead, rows or lines from a zone file that did not load; the section says so
            sec.update(lead=None, fire_lead=None, rows=[], lines=[], unavailable=_unavailable_text("zones", zone_lost))
    out["sections"].append(sec)

    # station gusts
    sec = _section("stations", w["stations_heading"], w["stations_what"], "station reading")
    sec["source"] = w["source_stations"]
    if parts.get("stations") == "unavailable":
        sec["unavailable"] = _unavailable_text("stations", reasons.get("stations"))
    else:
        stations = station_picks(tile_doc, *(spot or (centre_lat, centre_lon)))     # D36: picked from the spot
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
                for item in (sdoc or {}).get("days", []):
                    day = hail.day_of_index(item[0])          # B5: [day, mph, kt] and the flag (0 or 1)
                    if start <= day <= end:
                        rows.append((day, item[1], item[2], st, item[3] if len(item) > 3 else 0))
                dropped += (sdoc or {}).get("dropped", 0)
            rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
            sec["lead"] = _stations_lead(len(rows), ftn, w)
            for day, mph, kt, st, flag in rows:
                text = w["stations_row"].format(date=fmt_day(day), mph=int(mph), kt=int(kt), station=st["name"],
                                                miles=f"{st['miles']:.1f}")
                sec["rows"].append({"text": text + (w["flag_suffix"] if flag else ""), "remark": None, "utc": None})
            if any(row[4] for row in rows):
                sec["lines"].append(w["flag_check_line"])
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
    type_word = r[11] if len(r) > 11 and r[11] else (types or {}).get(kind, kind.lower())
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
    word and qualifier, no number and no "no size given"). NCEI's cause as written (r[13], the FLOOD_CAUSE field of a flood
    record; B5 source 5) joins the row when the record has one, in the WORDS_JOINS "_b5" templates. The browser's records
    rows take the same templates when part B2 switches map.js (the sheet and the town page then say the same words)."""
    miles, bearing = _place_bits(lat, lon, clat, clon, w)
    cause = " ".join(str(r[13]).split()) if len(r) > 13 and r[13] else ""
    base = dict(date=fmt_day(_local(utc).date()), time=fmt_clock(utc), type=r[4],
                qualifier=_qualifier(r[7], w), source=r[8], miles=miles,
                cause=w["records_cause"].format(cause=cause) if cause else "")
    if r[4] in UNIT_CODES:
        base["magnitude"] = _magnitude(r[5], r[6], w, mph=r[11], kt=r[12])
        key = "records_row_here_b5" if bearing is None else "records_row_b5"
    else:
        key = "records_row_here_typed_b5" if bearing is None else "records_row_typed_b5"
    if bearing is not None:
        base["bearing"] = bearing
    return w[key].format(**base)


def _zone_record_text(utc, r, zone, w) -> str:
    """A zone-coded record row (D9, D19): as _record_text, for the whole zone."""
    base = dict(date=fmt_day(_local(utc).date()), time=fmt_clock(utc), type=r[4],
                qualifier=_qualifier(r[7], w), source=r[8], zone=zone, cause="")
    if r[4] in UNIT_CODES:
        base["magnitude"] = _magnitude(r[5], r[6], w, mph=r[11], kt=r[12])
        return w["records_zone_row"].format(**base)
    return w["records_zone_row_typed"].format(**base)


def _kind_word(item: dict) -> str:
    """D29: the NWS name of a warning row's product (KIND_WORDS by code), never the bare code."""
    code = f"{item['k']}.{item['s']}"
    return KIND_WORDS.get(code, code)


def _warning_text(b, e, item, w) -> str:
    """A warning row (D4, B2; B5 D41): the significance label (Warning, Watch or Advisory: never "Warning" for a watch or
    an advisory), the begin and end (Montana time, the end's date only on a later day), the product's own kind word
    (KIND_WORDS), the office and the tags the archive gives (hail, wind, tornado, and the NWS damage threat tag where the
    product has one). The row is WORDS_JOINS["warnings_row_b5"]; the B2 template the browser fills
    (WORDS_JOINS["warnings_row"]) stays until part B2 switches map.js."""
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
    span = w["warnings_span"].format(begin=fmt_clock(b), end=fmt_end(e, b))
    return w["warnings_row_b5"].format(label=SIGNIFICANCE_LABEL.get(item["s"], "Product"),
                                       date=fmt_day(_local(b).date()), span=span,
                                       product=_kind_word(item), office=item["o"], tags=tag_text)


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
        "kinds": dict(PHENOMENON_KIND_WORDS),
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
        "events_tiles": "hail/j/e/{tile}.json",          # D30: the tile's events file (the browser fetches it on a tap)
        "events_tiles_format": TILE_EVENTS_FORMAT,
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
    current = set(block.get("zone_list", []))
    names = {z: n for z, n in block.get("zone_names", {}).items() if z in current}     # the 2026 names (D44: not the removed zones)
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


# ---------------------------------------------------------------- B5 checks (verify reads the store and the cache only)

RESEARCH_B5 = {                       # source 4: the window counts the research gives (VTEC events; the zone ones and the
    "FL.W": 43, "FA.W": 37, "FA.Y": 548, "FL.A": 35, "FL.Y": 10, "SQ.W": 78,              # county ones by key)
    "WW.Y": 865, "WS.A": 226, "HW.A": 277, "HT.Y": 58, "EH.W": 4, "EH.A": 3, "FR.Y": 14, "FZ.W": 4, "DU.Y": 3,
    "FF.A": 20,
}
RESEARCH_B5_COUNTY = {"FA.A": 18, "FF.A": 2}             # county-only events in the window
# rules-F26: the HW.A window note the compare step records. HW.A has no NEW rows (its rows are CON, UPG, CAN and EXT), so
# its events begin at the earliest CON issue, or at the earliest issue when an event has no CON row (B2's begin rule).
# The research counts from the earliest issue; its refuter found the window count the same under either rule.
B5_WINDOW_NOTES = {
    "HW.A": ("HW.A has no NEW rows in the archive (its rows are CON, UPG, CAN and EXT). This build begins an event at its "
             "earliest CON issue, or at its earliest issue when it has no CON row; the research begins at the earliest issue, "
             "and its window count is the same under both rules."),
}
RESEARCH_NCEI_TOTALS = {"Flood": 76, "Flash Flood": 60, "Heavy Rain": 144, "Tornado": 17, "Funnel Cloud": 35,
                        "Lightning": 8, "Debris Flow": 11}          # 2020 to 2026 totals (rows, Montana)
RESEARCH_NCEI_WINDOW = {"Flood": 60, "Flash Flood": 52, "Heavy Rain": 85, "Tornado": 13, "Funnel Cloud": 30,
                        "Lightning": 6, "Debris Flow": 10}          # the window's rows (the research's 256)
# D8's four named cases: zone, product, office, expected spans (begin, end, status) as the z/ file holds them
PERIOD_CASES = (
    ("MTZ004", "WS.W", "MSO", "2024-01-09T00:00Z", "2024-01-10T15:22Z", "cancelled",
     "MTZ004 WS 2024 event 1: cancelled on 10 January, continued from 11 January"),
    ("MTZ004", "WS.W", "MSO", "2024-01-11T12:00Z", "2024-01-12T12:00Z", None, "the continuation from 11 January"),
    ("MTZ302", "HW.W", "TFX", "2022-12-26T18:00Z", "2022-12-27T07:19Z", "cancelled", "MTZ302 HW 2022 event 38: first period"),
    ("MTZ302", "HW.W", "TFX", "2022-12-27T15:00Z", "2022-12-28T15:29Z", "cancelled", "MTZ302 HW 2022 event 38: second period"),
    ("MTZ320", "WS.W", "TFX", "2023-02-19T18:00Z", "2023-02-22T10:54Z", "cancelled", "MTZ320 WS 2023 event 4: cancelled"),
    ("MTZ320", "WS.W", "TFX", "2023-02-22T18:58Z", "2023-02-23T01:00Z", None, "MTZ320 WS 2023 event 4: the expiry after it"),
    ("MTZ003", "WS.W", "MSO", "2021-12-19T04:00Z", "2021-12-19T15:00Z", None, "MTZ003 WS 2021 event 12: first period (expired)"),
    ("MTZ003", "WS.W", "MSO", "2021-12-19T18:00Z", "2021-12-20T03:27Z", "cancelled", "MTZ003 WS 2021 event 12: second period"),
)
JUNE_2022_PLACES = (("Red Lodge", 45.1677, -109.2503), ("Gardiner (Yellowstone River at Corwin Springs)", 45.1121194,
                                                          -110.7936667), ("Billings", None, None))
GLENTANA = {"lat": 48.85, "lon": -106.25, "utc": "2022-07-18T23:47Z", "office": "NCEI tornado 1043279"}
HAYS = {"day": "2021-07-07", "lat": 48.01, "lon": -108.79}


def _mesh_in(root: Path, index: dict, lat: float, lon: float, day: date) -> float:
    """The B1 MESH value at the cell that holds (lat, lon) on one SPC day, in inches; 0.0 when the day has no stored value
    (below the floor of 0.25 in, B1)."""
    rows = hail.cell_events(root, lat, lon, index) or []
    for d, tenths in rows:
        if d == day:
            return tenths / hail.TENTHS_PER_INCH
    return 0.0


def _floor_hundredths(inches: float) -> float:
    """A radar value in inches to the hundredth, rounded down (the B1 display rule, decision 10). A value of 0.996 in
    shows 0.99, so a row never prints 1.00 for a value the hit test counts as a miss."""
    return math.floor(inches * 100 + 1e-7) / 100


def _hit_and_miss(root: Path, index: dict, events: dict) -> dict:
    """D15: every LSR hail report of 1.00 in or more in the window, against the B1 MESH maximum at the report's cell on its
    SPC day and the SWDI MAXSIZE of the detections within 2 miles of the report on that day. A hit is a radar value of
    1.00 in or more (MESH or SWDI); a miss is not. under_by is the report's size less the larger radar value, when that is
    positive."""
    rows = []
    for ref in range(len(events["reports"])):
        r = events["reports"][ref]
        if r[4] != "H" or r[6] != "in" or not r[5]:
            continue
        size = float(r[5])
        if size < 1.0:
            continue
        utc = utc_from_row(r[0], r[1])
        day = spc_day(utc)
        mesh = _mesh_in(root, index, r[2], r[3], day)
        swdi = _swdi_in(root, index, r[2], r[3], day)
        radar = max(mesh, swdi)
        rows.append({"utc": iso_utc(utc), "place": r[9], "lat": r[2], "lon": r[3], "report_in": round(size, 2),
                     "mesh_in": _floor_hundredths(mesh), "swdi_in": _floor_hundredths(swdi),
                     "hit": bool(radar >= 1.0), "under_by_in": round(max(0.0, size - radar), 2),
                     "remark": r[10][:80]})
    misses = [x for x in rows if not x["hit"]]
    unders = sorted(x["under_by_in"] for x in misses)
    summary = {"reports": len(rows), "hits": len(rows) - len(misses), "misses": len(misses),
               "misses_under_by_median_in": unders[len(unders) // 2] if unders else None,
               "misses_under_by_max_in": unders[-1] if unders else None}
    return {"summary": summary, "rows": rows}


def _swdi_in(root: Path, index: dict, lat: float, lon: float, day: date) -> float:
    """The largest SWDI MAXSIZE (inches) of the detections within 2 miles of (lat, lon) on one SPC day, from the j/ file of
    the tile that holds the point (its detections include every one within 2 miles of any point in the tile)."""
    row, col = hail.cell_for(lat, lon)
    tile = hail.tile_name(row // 10, col // 10)
    try:
        doc = _read_j(root, tile)
    except JoinsError:
        return 0.0
    best = 0.0
    for d_, t_, dlat, dlon, size in doc.get("detections", []):
        if spc_day(utc_from_row(d_, t_)) != day:
            continue
        if haversine_km(lat, lon, dlat, dlon) / MILE_KM <= DETECT_MILES:
            best = max(best, size / 100.0)
    return best


def _ncei_pairs(events: dict) -> dict:
    """D10: NCEI hail records matched to LSR hail reports (the same size to 0.01 in, within 10 km and 3 hours, nearest in
    time, each row used once). Each pair's offset is the LSR time less the NCEI time as the store holds it (the store's
    NCEI time is MST-7 converted to UTC, so 0 hours is the MST rule). Pairs off 0 hours are listed, not explained."""
    reports = [r for r in events["reports"] if r[4] == "H" and r[5]]
    records = [r for r in events["records"] if r[4] == "hail" and r[5]]
    used: set = set()
    pairs = []
    for ri, rec in enumerate(records):
        best = None
        rt = utc_from_row(rec[0], rec[1])
        for li, lsr in enumerate(reports):
            if li in used or float(lsr[5]) != float(rec[5]):
                continue
            lt = utc_from_row(lsr[0], lsr[1])
            gap = (lt - rt).total_seconds() / 3600.0
            if abs(gap) > 3.0:
                continue
            dist = float(haversine_km(rec[2], rec[3], lsr[2], lsr[3]))
            if dist > 10.0:
                continue
            key = (abs(gap), dist)
            if best is None or key < best[0]:
                best = (key, li, gap, dist)
        if best is not None:
            used.add(best[1])
            lsr = reports[best[1]]
            pairs.append({"ncei_utc": iso_utc(rt), "lsr_utc": iso_utc(utc_from_row(lsr[0], lsr[1])),
                          "offset_h": round(best[2], 2), "km": round(best[3], 2), "in": rec[5],
                          "place": lsr[9]})
    off = collections.Counter(p["offset_h"] for p in pairs)
    off_rule = [p for p in pairs if abs(p["offset_h"]) >= 0.5]          # not within half an hour of the MST rule
    return {"pairs": len(pairs), "offsets": {str(k): v for k, v in sorted(off.items())},
            "on_rule": len(pairs) - len(off_rule), "off_rule": off_rule}


def _june_2022(root: Path, index: dict, events: dict) -> dict:
    """B5 gate 5 (E01): the flood warnings (FL.W and FA.W) and the NCEI flood records over Red Lodge, Gardiner and
    Billings in June 2022, read from the tile files of the cells that hold the places."""
    out = {}
    towns = {t["name"]: t for t in json.loads(TOWNS_FILE.read_text(encoding="utf-8"))}
    places = [(name, lat, lon) for name, lat, lon in JUNE_2022_PLACES if lat is not None]
    if "Billings" in towns:
        places.append(("Billings", towns["Billings"]["lat"], towns["Billings"]["lon"]))
    for name, lat, lon in places:
        row, col = hail.cell_for(lat, lon)
        key = hail.cell_key(row, col)
        clat, clon = hail.cell_centre(row, col)
        tile = hail.tile_name(row // 10, col // 10)
        if tile not in set(index["tiles"]):
            out[name] = {"cell": [row, col], "not_in_store": True}      # the store holds no tile here: not checked
            continue
        doc = _read_j(root, tile)
        warnings = []
        for ref, cover in doc.get("warnings", []):
            item = events["warnings"][ref]
            if not cover_has(cover, key):
                continue
            if item["b"][:7] == "2022-06" or (item["e"] or "")[:7] == "2022-06":
                warnings.append({"product": f"{item['k']}.{item.get('s', '')}", "b": item["b"], "e": item["e"],
                                 "o": item["o"]})
        floods = []
        for ref in doc.get("records", []):
            r = events["records"][ref]
            utc = utc_from_row(r[0], r[1])
            if utc.strftime("%Y-%m") == "2022-06" and r[4] in ("flood", "flash flood"):
                miles = float(haversine_km(clat, clon, r[2], r[3])) / MILE_KM
                floods.append({"utc": iso_utc(utc), "type": r[4], "cause": r[13] if len(r) > 13 else "",
                               "miles": round(miles, 2)})
        out[name] = {"cell": [row, col], "fl_fa_warnings_june_2022": sorted(warnings, key=lambda w: w["b"]),
                     "ncei_flood_records_june_2022": floods}
    return out


def _periods_check(root: Path) -> list:
    """D8: the four named cases, as the z/ files hold them (the begin is exact; the end and status too)."""
    out = []
    for zone, product, office, begin, end, st, label in PERIOD_CASES:
        zdoc = _read_z(root, zone) or {}
        phen, sig = product.split(".")
        found = [e for e in zdoc.get("events", []) if e["k"] == phen and e["s"] == sig and e["o"] == office
                 and e["b"] == begin]
        ok = bool(found) and found[0].get("e") == end and found[0].get("st") == st
        out.append({"case": label, "zone": zone, "begin": begin, "expected_end": end, "expected_st": st,
                    "found": None if not found else {"e": found[0].get("e"), "st": found[0].get("st")},
                    "ok": ok, "in_window": True})
    return out


def _county_cells(root: Path, index: dict) -> dict:
    """The county of every Montana cell is written once: each cell appears under exactly one county in the j/ files."""
    block = index[INDEX_KEY]
    seen: dict[tuple, str] = {}
    twice = 0
    for t in index["tiles"]:
        doc = _read_j(root, t)
        for code, keys in doc.get("counties", {}).items():
            for k in keys:
                cell = (t, k)
                if cell in seen:
                    twice += 1
                seen[cell] = code
    expected = sum(len(tile["keys"]) for tile in load_tiles(root, index))
    files = sorted((root / "hail" / "k").glob("MTC*.json"))
    return {"cells_with_county": len(seen), "cells_in_state": expected, "cells_listed_twice": twice,
            "county_files": len(files), "counties_in_index": len(block.get("counties", {}).get("names", {})),
            "unassigned": expected - len(seen)}


def _county_name_check(root: Path, index: dict) -> list:
    block = index[INDEX_KEY]
    out = []
    for code, name in sorted(block.get("counties", {}).get("names", {}).items()):
        path = root / "hail" / "k" / f"{code}.json"
        if not path.is_file():
            out.append(f"{code}: no k/ file")
    return out


def _research_compare(block: dict, research: bool = True) -> list:
    """The research's window counts beside this build's: the VTEC events of the research window (research=True: every
    row read, 2021-10-19 to 2026-10-19), or of the store's window (research=False)."""
    rows = []
    vt = block.get("vtec_counts_research" if research else "vtec_counts", {})
    for name, want in sorted(RESEARCH_B5.items()):
        ours = vt.get(name, {}).get("window")
        rows.append({"product": name, "ours_window_vtec_events": ours, "research_window": want,
                     "delta": None if ours is None else ours - want})
    for name, want in sorted(RESEARCH_B5_COUNTY.items()):
        ours = vt.get(name, {}).get("county")
        rows.append({"product": name + " (county-only)", "ours_window_vtec_events": ours,
                     "research_window": want, "delta": None if ours is None else ours - want})
    return rows


def _cover_counts_check(block: dict) -> dict:
    cc = block.get("cover_counts", {})
    bad = {k: v["centre_not_touched"] for k, v in cc.items() if v.get("centre_not_touched")}
    return {"products": {k: {"centre_rule": v["centre"], "touch_rule": v["touched"], "added": v["added"]}
                         for k, v in sorted(cc.items())},
            "centre_not_touched": bad}


def _gusts_check(block: dict) -> dict:
    dropped = block.get("station_dropped_readings", [])
    flagged = block.get("station_flagged_readings", [])
    return {"dropped": dropped, "flagged": flagged,
            "lwt_182_5_dropped": any(d["station"] == "LWT" and d["date"] == "2023-03-13" for d in dropped),
            "hvr_flagged": any(f["station"] == "HVR" and f["date"] == "2025-02-20" for f in flagged),
            "mso_flagged": any(f["station"] == "MSO" and f["date"] == "2025-05-09" for f in flagged)}


def towns_file_check(root: Path, index_tiles) -> dict:
    """D38, verify: hail/j/towns.json against the cell covers. For each town, the events its polygon file lists are compared
    with the events whose cover holds the town's cell (the touch rule, D11), in the tile file that holds the cell. Returns
    the counts and up to five examples of each kind of disagreement: a town event the cover lacks (town_not_cover, which
    must be zero) and a cover event the town point is not in (cover_not_town, recorded)."""
    try:
        doc = json.loads((root / "hail" / "j" / TOWNS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"error": f"the town polygon file could not be read ({exc})"}
    if doc.get("f") != TOWNS_FORMAT:
        return {"error": "the town polygon file is not in its format"}
    tiles, out = {}, {"towns": {}, "town_not_cover": 0, "cover_not_town": 0, "examples": [], "not_in_store": []}
    for slug, town in sorted(doc["towns"].items()):
        row, col = town["cell"]
        name = hail.tile_name(row // hail.TILE, col // hail.TILE)
        if name not in index_tiles:
            out["not_in_store"].append(slug)           # a store cut to some tiles (the test and sample stores)
            continue
        if name not in tiles:
            try:
                tiles[name] = json.loads((root / "hail" / "j" / f"{name}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return {"error": f"the tile file {name} could not be read ({exc})"}
        covers = {int(ref): cover for ref, cover in tiles[name]["warnings"]}
        key = hail.cell_key(row, col)
        cover_refs = {ref for ref, cover in covers.items() if cover_has(cover, key)}
        town_refs = {event[0] for event in town["events"]}
        missing, extra = sorted(town_refs - cover_refs), sorted(cover_refs - town_refs)
        out["towns"][slug] = {"cell": [row, col], "events": len(town_refs), "cover": len(cover_refs),
                              "town_not_cover": missing, "cover_not_town": extra}
        out["town_not_cover"] += len(missing)
        out["cover_not_town"] += len(extra)
        for ref in missing[:2]:
            out["examples"].append({"town": slug, "kind": "town point inside, cover lacks it", "event": ref})
    return out


def station_periods_check(root: Path, index: dict) -> dict:
    """D37, verify: every s/ file has periods.season for the six seasons, n the days of the season up to the window's last
    day, and ok an integer from 0 to n. Returns the file count, the problem count and up to five examples."""
    last = date.fromisoformat(index["window"][1])
    files = sorted((root / "hail" / "s").glob("*.json")) if (root / "hail" / "s").is_dir() else []
    bad = []
    for path in files:
        seasons = ((json.loads(path.read_text(encoding="utf-8")).get("periods") or {}).get("season")) or {}
        for label in SEASON_LABELS:
            rec = seasons.get(label)
            first_day, end_day = season_bounds(label, last)
            n = (end_day - first_day).days + 1
            if not rec or rec.get("n") != n or not isinstance(rec.get("ok"), int) or not 0 <= rec["ok"] <= n:
                bad.append(f"{path.stem} {label}")
    return {"files": len(files), "seasons": len(SEASON_LABELS), "bad": len(bad), "examples": bad[:5]}


def verify(store_dir, cache_dir=None) -> dict:
    """Check a built store's joins. Returns {"ok", "state", "parts", "checks", "gate", "b5"}: a failed check makes ok
    False; a part that did not load is reported, not failed. The gate holds B2 gate 1's Benchland rows as found (D1):
    the report and the record from the report cell's tile, the warnings and the zone from the gate cell's tile. The "b5"
    block is the B5 record (D8, D10, D11, D12, D15, source 4 to 6): the counts, the tables and the cases, each as found.
    cache_dir (optional) is the joins cache, read only for the NCEI 2020 file (the 2020 to 2026 totals)."""
    root = Path(store_dir)
    checks: list[tuple[str, bool, str]] = []
    not_run: list[dict] = []        # F15: a check that did not run is named with its reason and never passes

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        return ok

    def skip(name, reason):
        not_run.append({"name": name, "reason": reason})

    def out(ok, state=None, parts=None, gate=None, b5=None):
        return {"ok": ok, "state": state, "parts": parts or {},
                "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks],
                "not_run": list(not_run), "gate": gate or {}, "b5": b5 or {}}

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
    before_names = set(block.get("zones_before", {}).get("codes", []))     # D44: the 21 codes the tiles may name
    fire_names = set(block.get("fire_zone_list", []))
    county_names = set(block.get("counties", {}).get("names", {}))
    bad_ints = bad_refs = bad_cover = bad_zone = bad_fire = bad_county = bad_before = 0
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
        for code, keys in doc.get("zones_before", {}).items():         # D44
            if code not in before_names or not all(isinstance(k, int) and 0 <= k < 100 for k in keys):
                bad_before += 1
        for code, keys in doc.get("fire", {}).items():
            if code not in fire_names or not all(isinstance(k, int) and 0 <= k < 100 for k in keys):
                bad_fire += 1
        for code, keys in doc.get("counties", {}).items():
            if code not in county_names or not all(isinstance(k, int) and 0 <= k < 100 for k in keys):
                bad_county += 1
        for det in doc.get("detections", []):
            if not (isinstance(det[0], int) and isinstance(det[1], int) and isinstance(det[4], int)):
                bad_ints += 1
        for st in doc.get("stations", []):
            if not isinstance(st.get("miles"), (int, float)):
                bad_ints += 1
    check("events and tile whole numbers", bad_ints == 0, f"{bad_ints} not whole")
    check("tile references point into the events table", bad_refs == 0, f"{bad_refs} bad")
    # D30: every event a tile refers to is in that tile's events file, as the events table holds it; the file's size
    tile_missing, tile_extra, tile_files_n = 0, 0, 0
    largest_raw, largest_gzip = (0, ""), (0, "")
    for t, doc in docs.items():
        try:
            edoc, edata = _read_tile_events(root, t)
        except JoinsError:
            tile_missing += 1
            continue
        tile_files_n += 1
        egz = len(gzip.compress(edata, compresslevel=9, mtime=0))
        largest_raw = max(largest_raw, (len(edata), t))
        largest_gzip = max(largest_gzip, (egz, t))
        for kind, refs in (("reports", doc.get("reports", [])), ("records", doc.get("records", [])),
                           ("warnings", [ref for ref, _cover in doc.get("warnings", [])])):
            held = edoc.get(kind, {})
            if events is not None:
                for ref in refs:
                    if str(ref) not in held or held[str(ref)] != events[kind][ref]:
                        tile_missing += 1
            if set(held) != {str(ref) for ref in refs}:
                tile_extra += 1
    check("every event a tile refers to is in its tile's events file", tile_missing == 0 and tile_extra == 0,
          f"{tile_missing} missing or different, {tile_extra} extra keys")
    check("every tile has an events file in its format", tile_files_n == len(docs) == len(tiles),
          f"{tile_files_n} files for {len(tiles)} tiles")
    check("tile events files are within the gzip budget", largest_gzip[0] <= TILE_EVENTS_BUDGET_GZIP,
          f"largest {largest_gzip[1]}: {largest_gzip[0]} bytes gzip (budget {TILE_EVENTS_BUDGET_GZIP}); "
          f"largest raw {largest_raw[0]} bytes ({largest_raw[1]})")
    check("the index names the tile events format and count",
          block.get("events_tiles", {}).get("format") == TILE_EVENTS_FORMAT
          and block.get("events_tiles", {}).get("count") == tile_files_n,
          str(block.get("events_tiles", {}).get("count")))
    check("warning covers are 25 hex digits", bad_cover == 0, f"{bad_cover} bad")
    check("zone codes are current zones and keys are cells", bad_zone == 0, f"{bad_zone} bad")
    check("zones before the switch: the codes are the removed zones and MTZ060, keys are cells (D44)",
          bad_before == 0, f"{bad_before} bad")
    check("fire zone codes are current fire zones and keys are cells", bad_fire == 0, f"{bad_fire} bad")
    check("county codes are the Montana counties and keys are cells", bad_county == 0, f"{bad_county} bad")
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
    listed = [k for k in manifest["files"] if k.startswith(("hail/j/", "hail/z/", "hail/s/", "hail/k/"))]
    on_disk = [p for sub in ("j", "z", "s", "k") for p in (root / "hail" / sub).rglob("*.json")]     # D30: j/e/ too
    check("manifest lists every j, z, s and k file", len(listed) == len(on_disk),
          f"{len(listed)} listed, {len(on_disk)} files")
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
    table = block.get("zone_placement_table")
    if table is not None:
        check("zone placement: the table adds up (current, mapped, IEM set, changeover week and unplaced make the groups)",
              table["current"] + table["mapped"] + table["iem_set"] + table["changeover_week"] + table["unplaced"]
              == table["groups"], str(table))
        if all(s.get("state") == "loaded" for s in (block.get("iem_sets") or [])) and table["unplaced"] == 0:
            check("zone placement: every zone product in the window is placed (expected 0 unplaced, D44)",
                  table["unplaced"] == table["expected_unplaced"]
                  and len(block.get("zone_unplaced_rows", [])) == table["unplaced"],
                  f"{table['unplaced']} unplaced of {table['groups']} groups; expected {table['expected_unplaced']}")
        elif table["unplaced"] == 0:
            check("zone placement: every zone product in the window is placed (expected 0 unplaced, D44)",
                  len(block.get("zone_unplaced_rows", [])) == 0, f"{table['groups']} groups placed")
        else:
            skip("zone placement: every zone product in the window is placed (expected 0 unplaced, D44)",
                 f"{table['unplaced']} groups unplaced, and a zone set or edition did not load (reported, not failed)")
    iem = block.get("iem_sets")
    if iem is not None:
        loaded_all = all(s.get("state") == "loaded" for s in iem)
        reason = "a zone set did not load: " + ", ".join(s["valid"] for s in iem if s.get("state") != "loaded")
        counts = [s.get("zones") for s in iem]
        if loaded_all:
            check("IEM zone sets: seven snapshots, 103 zones through 2022-09-13 12:00Z and 83 from 18:00Z (D44)",
                  counts == [103, 103, 103, 103, 83, 83, 83], str(counts))
        else:
            skip("IEM zone sets: seven snapshots, 103 zones through 2022-09-13 12:00Z and 83 from 18:00Z (D44)", reason)
        if cache_dir is None:
            skip("IEM zone sets: each cached snapshot matches its SHA-256 (D44)", "no joins cache was given")
        else:
            bad, blobs = [], {}
            for s in iem:
                if s.get("state") != "loaded":
                    continue
                path = Path(cache_dir) / s["file"]
                data = path.read_bytes() if path.is_file() else None
                blobs[s["valid"]] = data
                if data is None or s.get("sha256") != hashlib.sha256(data).hexdigest():
                    bad.append(s["valid"])
            if blobs:
                check("IEM zone sets: each cached snapshot matches its recorded SHA-256 (D44)", not bad,
                      ", ".join(bad) or f"{len(blobs)} snapshots match")
            else:
                skip("IEM zone sets: each cached snapshot matches its recorded SHA-256 (D44)", reason)
            if {"2022-09-13T12:00:00Z", "2022-09-13T18:00:00Z"} <= {k for k, v in blobs.items() if v is not None}:
                try:
                    before_set = {z["zone"] for z in parse_iem_ugcs(blobs["2022-09-13T12:00:00Z"])}
                    after_set = {z["zone"] for z in parse_iem_ugcs(blobs["2022-09-13T18:00:00Z"])}
                    removed = sorted(before_set - after_set)
                    check("IEM zone sets: the zones removed at the switch are the 20 the placement names (D44)",
                          tuple(removed) == IEM_REMOVED_ZONES and after_set < before_set,
                          f"{len(removed)} removed; {len(before_set)} before, {len(after_set)} after")
                except JoinsError as exc:
                    check("IEM zone sets: the zones removed at the switch are the 20 the placement names (D44)",
                          False, f"a snapshot did not read: {exc}")
            else:
                skip("IEM zone sets: the zones removed at the switch are the 20 the placement names (D44)", reason)
    zb = block.get("zones_before")
    if zb is not None:
        if iem is not None and all(s.get("state") == "loaded" for s in iem) and block["parts"].get("zones") != "unavailable":
            check("zones before the switch: the 21 codes are the 20 removed zones and MTZ060 (D44)",
                  sorted(zb.get("codes", [])) == sorted(IEM_OUTLINE_ZONES), str(zb.get("codes")))
        else:
            skip("zones before the switch: the 21 codes are the 20 removed zones and MTZ060 (D44)",
                 "a zone set did not load")
        missing_before = [z for z in block.get("zone_list_before", []) if not (root / "hail" / "z" / f"{z}.json").is_file()]
        check("zones before the switch: every removed zone has its z/ file (D44)", not missing_before,
              ", ".join(missing_before) or f"{len(block.get('zone_list_before', []))} files")
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
            if not (len(day) in (3, 4) and all(isinstance(v, int) and not isinstance(v, bool) for v in day)):
                bad_station += 1
    check("station days are whole numbers (mph and kt, D18; the flag, B5)", bad_station == 0,
          f"{bad_station} not whole")
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
            skip("gate 1: the gate cell's TFX warnings include the 19:53 and 21:23 UTC polygons",
                 _part_reason(block, "warnings"))
        if block["parts"].get("zones") == "loaded":
            check("gate 1: the gate cell's zone is MTZ313", gate.get("zone") == "MTZ313", str(gate.get("zone")))
        else:
            skip("gate 1: the gate cell's zone is MTZ313", _part_reason(block, "zones"))
    elif docs.get(gate_tile) is not None:
        skip("gate 1: the LSR and NCEI hail rows at Benchland", _part_reason(block, "reports"))
    else:
        skip("gate 1: the LSR and NCEI hail rows at Benchland", "this store has no tile for Benchland's gate cell")

    b5: dict = {}
    if events is not None:
        b5 = _verify_b5(root, index, events, block, check, cache_dir, skip)
    b5["not_run"] = list(not_run)
    b5["windows"] = {"store": [window_utc(index)[0].strftime("%Y-%m-%dT%H:%MZ"),
                               window_utc(index)[1].strftime("%Y-%m-%dT%H:%MZ")],
                     "research": [RESEARCH_START.strftime("%Y-%m-%dT%H:%MZ"), RESEARCH_END.strftime("%Y-%m-%dT%H:%MZ")]}
    return out(all(c[1] for c in checks), block["state"], block["parts"], gate, b5)


def _part_reason(block: dict, part: str) -> str:
    """Why a check that needs this part did not run (verify's not_run, F15): the part is unavailable, or partial with the
    files that did not load (their years, for the warnings), or loaded with no tile in this store for the check."""
    state = block.get("parts", {}).get(part)
    if state == "unavailable":
        return f"{part} part unavailable"
    if state == "partial":
        labels = block.get("unavailable_units", {}).get(part, [])
        names = sorted({lab.split()[-1] if " " in lab else lab for lab in labels})
        if names:
            return f"{part} part partial: the files for {', '.join(names)} did not load, so those years are not checked"
        return f"{part} part partial: some files were served from the cache after a failed request"
    return f"{part} part loaded, but this store has no tile for this check"


def _counties_reason(block: dict) -> str:
    counties = block.get("counties", {})
    if counties.get("state") == "sample":
        return "this store is the three-day fixture, so it does not hold every Montana cell's county"
    if counties.get("reason"):
        return f"the county file did not load: {counties['reason']}"
    return "the county file did not load"


def _verify_b5(root: Path, index: dict, events: dict, block: dict, check, cache_dir, skip) -> dict:
    """The B5 checks and the record (D8, D10, D11, D12, D15; sources 4 to 6). A failed check is the gate's; the tables and
    the research comparison are recorded as found."""
    b5: dict = {}

    def guarded(name, fn, default=None):
        try:
            return fn()
        except (JoinsError, hail.HailStoreError, KeyError, IndexError, ValueError, TypeError) as exc:
            check(f"B5 record: {name} could not be read", False, str(exc))
            return default
    cover = _cover_counts_check(block)
    b5["cover"] = cover
    check("D11: every centre-rule cell is also a touch-rule cell (per product)", not cover["centre_not_touched"],
          str(cover["centre_not_touched"]))
    town = block.get("town_checks")
    town_record = town or {}
    b5["town_point_check"] = {"towns": town_record.get("towns", []), "events_checked": town_record.get("events_checked"),
                              "pairs_tested": town_record.get("pairs_tested"),
                              "disagreements": town_record.get("disagreements", [])}
    town_name = "D11: the town point check for the 17 towns (every polygon product, 2021 to 2026)"
    if town is None:                    # the fixture cut and any store written before the check existed
        skip(town_name, "this store has no town_checks block")
    elif block["parts"].get("warnings") != "loaded":
        skip(town_name, _part_reason(block, "warnings"))
    elif not town.get("events_checked"):
        skip(town_name, "no polygon event was read in this store")
    else:
        check("D11: the town point check ran for the 17 towns", len(town.get("towns", [])) == 17,
              f"{len(town.get('towns', []))} towns; {len(town.get('disagreements', []))} disagreements listed")
    # D38: towns.json against the cell covers. A polygon that holds a town point touches the town's cell, so every such
    # event must be in the cover; the cover-only events are the cell rule's wider reach and are recorded, not failed.
    towns_name = "D38: the town polygon file agrees with the cell covers"
    if block.get("towns_file") is None:             # a store written before D38 (the committed fixture until it is cut)
        skip(towns_name, "this store has no towns file")
    elif block["parts"].get("warnings") != "loaded":
        skip(towns_name, _part_reason(block, "warnings"))
    else:
        towns_file = towns_file_check(root, set(index["tiles"]))
        if towns_file.get("error"):
            check(towns_name, False, towns_file["error"])
        else:
            check("D38: every polygon event that holds a town point is in that town's cell cover",
                  towns_file["town_not_cover"] == 0,
                  f"{towns_file['town_not_cover']} missing from the covers; {towns_file['cover_not_town']} cover-only "
                  f"(the cell rule is wider than the point rule); {len(towns_file['not_in_store'])} towns not in this store")
            b5["towns_file"] = towns_file
    # D37: each station gust file carries the days it reported, per season, for the six seasons
    if block["parts"].get("stations") == "unavailable":
        skip("D37: every station gust file carries days reported per season", _part_reason(block, "stations"))
    else:
        gust_periods = station_periods_check(root, index)
        check("D37: every station gust file carries days reported per season (n days, ok days, 0 to n)",
              gust_periods["bad"] == 0 and gust_periods["files"] > 0,
              f"{gust_periods['files']} files; {gust_periods['bad']} problems {gust_periods['examples']}")
        b5["station_periods"] = gust_periods
    nulls = block.get("polygon_nulls", {})
    check("D11: every outline-less polygon is joined by county or counted otherwise",
          nulls.get("window", 0) == nulls.get("joined", 0) + nulls.get("unjoined", 0),
          str({k: nulls.get(k) for k in ("no_outline", "window", "joined", "unjoined")}))
    b5["polygon_nulls"] = nulls
    counties = guarded("county cells", lambda: _county_cells(root, index), {"cells_listed_twice": 0,
                                                                              "unassigned": 0, "county_files": 0})
    b5["counties"] = dict(counties, state=block.get("counties", {}).get("state"),
                          reason=block.get("counties", {}).get("reason"))
    if block.get("counties", {}).get("state") == "loaded":
        check("source 4: every Montana cell has one county, written once",
              counties["cells_listed_twice"] == 0 and counties["unassigned"] == 0 and counties["county_files"] == 56,
              str(counties))
    else:
        skip("source 4: every Montana cell has one county, written once", _counties_reason(block))
    b5["vtec_counts"] = block.get("vtec_counts", {})
    b5["research_window_counts"] = _research_compare(block, research=True)
    b5["store_window_counts"] = _research_compare(block, research=False)
    b5["zone_periods"] = block.get("zone_periods")
    b5["periods"] = guarded("period cases", lambda: _periods_check(root), [])
    present = [p for p in b5["periods"] if p["zone"] in set(block.get("zone_list", []))]
    check("D8: the named period cases are as the rows give (for the zones the store holds)",
          all(p["ok"] for p in present) if present else True,
          "; ".join(f"{p['case']}: {'ok' if p['ok'] else 'not as expected'}" for p in present) or "no case in store")
    b5["june_2022"] = guarded("June 2022", lambda: _june_2022(root, index, events), {})
    b5["hit_and_miss"] = guarded("hit and miss", lambda: _hit_and_miss(root, index, events), {})
    hm = b5["hit_and_miss"]
    hm["research_cases"] = [dict(c) for c in KNOWN_HAIL_CASES]          # research values outside the window
    store_start = window_utc(index)[0]
    early = [r for r in hm.get("rows", []) if parse_iso_utc(r["utc"]) < store_start]
    check("D15: the hit-and-miss table holds no report before the window start", not early,
          f"{len(early)} before {store_start:%Y-%m-%d %H:%M} UTC")
    for case in HIT_MISS_ROWS:
        name = f"D15: the named case {case['name']} ({case['in']} in, {case['utc']}) is in the table"
        row_cell = hail.cell_for(case["lat"], case["lon"])
        if hail.tile_name(row_cell[0] // 10, row_cell[1] // 10) not in set(index["tiles"]):
            skip(name, f"this store has no tile for {case['name']}")
            continue
        found = [r for r in hm.get("rows", []) if r["utc"] == case["utc"] and case["name"] in (r["place"] or "")
                 and r["report_in"] == float(case["in"])]
        check(name, len(found) == 1, f"{len(found)} rows")
    b5["ncei_pairs"] = guarded("NCEI pairs", lambda: _ncei_pairs(events), {})
    b5["gusts"] = _gusts_check(block)
    stations = set(block.get("station_list", []))
    if {"LWT", "HVR", "MSO"} <= stations:
        check("D12: the LWT 182.5 kt reading is dropped and counted; HVR and MSO are flagged",
              b5["gusts"]["lwt_182_5_dropped"] and b5["gusts"]["hvr_flagged"] and b5["gusts"]["mso_flagged"],
              str({k: b5["gusts"][k] for k in ("lwt_182_5_dropped", "hvr_flagged", "mso_flagged")}))
    else:
        skip("D12: LWT 182.5 kt is dropped and counted; HVR and MSO are flagged",
             "this store has no station file for " + ", ".join(sorted({"LWT", "HVR", "MSO"} - stations)))
    b5["type_words"] = block.get("type_words", {})
    b5["ncei_totals_store"] = block.get("ncei_totals", {})
    totals = {}
    if cache_dir is not None:
        totals = _ncei_totals_2020(Path(cache_dir))
    store_totals = block.get("ncei_totals", {})          # keyed by the lower-case type word the rows carry
    b5["ncei_totals_2020_2026"] = {
        k: {"2020": totals.get(k, 0),
            "2021_2026": store_totals.get(k.lower(), {}).get("total", 0),
            "total": totals.get(k, 0) + store_totals.get(k.lower(), {}).get("total", 0),
            "window": store_totals.get(k.lower(), {}).get("window", 0),
            "research_total": RESEARCH_NCEI_TOTALS.get(k)}
        for k in sorted(RESEARCH_NCEI_TOTALS)}
    glen_tile = hail.tile_name(*(c // 10 for c in hail.cell_for(GLENTANA["lat"], GLENTANA["lon"])))
    b5["glentana"] = guarded("Glentana", lambda: _glentana_check(root, index), {"found": None})
    if glen_tile in set(index["tiles"]):
        check("gate 7: Glentana (T04, 2022-07-18 23:47 UTC) is a record within 5 miles of its point",
              b5["glentana"]["found"], str(b5["glentana"]))
    else:
        skip("gate 7: Glentana (T04, 2022-07-18 23:47 UTC) is a record within 5 miles of its point",
             "this store has no tile for its point")
    b5["hays_excluded"] = _hays_check(events, window_utc(index)[0])
    check("gate 7: the Hays tornado (2021-07-07) is outside the window and no record holds it",
          b5["hays_excluded"]["absent"] and b5["hays_excluded"]["outside_window"], str(b5["hays_excluded"]))
    return b5


def _ncei_totals_2020(cache: Path) -> dict:
    """The NCEI 2020 Montana point rows of the new types, from the 2020 details file in the cache (or {} when absent)."""
    found = sorted((cache / "ncei").glob("StormEvents_details-ftp_v1.0_d2020_*.csv.gz"))
    if not found:
        return {}
    counts: dict[str, int] = {}
    reader = _ncei_rows(found[-1].read_bytes())
    for row in reader:
        if None in row.values() or row.get("STATE", "").strip().upper() != "MONTANA":
            continue
        kind = row["EVENT_TYPE"].strip()
        if kind in RESEARCH_NCEI_TOTALS and row["CZ_TYPE"].strip().upper() == "C" and row["BEGIN_LAT"].strip():
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _glentana_check(root: Path, index: dict) -> dict:
    """Gate 7: the NCEI tornado of Glentana at 2022-07-18 23:47 UTC, found in the records of the tile of its point and
    within five miles of that cell's centre."""
    row, col = hail.cell_for(GLENTANA["lat"], GLENTANA["lon"])
    tile = hail.tile_name(row // 10, col // 10)
    if tile not in set(index["tiles"]):
        return {"found": None, "cell": [row, col], "in_store": False}
    doc = _read_j(root, tile)
    clat, clon = hail.cell_centre(row, col)
    records = (_read_events(root) or {}).get("records", [])
    for ref in doc.get("records", []):
        r = records[ref]
        if iso_utc(utc_from_row(r[0], r[1])) == GLENTANA["utc"] and r[4] == "tornado":
            miles = float(haversine_km(clat, clon, r[2], r[3])) / MILE_KM
            return {"found": miles <= REPORT_MILES, "cell": [row, col], "miles": round(miles, 2), "record": r[:11]}
    return {"found": False, "cell": [row, col]}


def _hays_check(events: dict, window_start: datetime) -> dict:
    """Gate 7: the Hays tornado is in no record, and its day is before the store's window start (the caller passes the
    store's first instant, window_utc, not a constant)."""
    hits = [r for r in events["records"] if r[4] == "tornado" and iso_utc(utc_from_row(r[0], r[1])).startswith(
        HAYS["day"])]
    when = datetime.fromisoformat(HAYS["day"] + "T00:11").replace(tzinfo=timezone.utc)
    return {"absent": not hits, "outside_window": when < window_start, "rows_on_day": len(hits)}


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
    for item in _research_compare(index[INDEX_KEY], research=True):
        note = ("VTEC events (the key without the zone) that begin in the research window, "
                f"{RESEARCH_START:%Y-%m-%d %H:%M} UTC to {RESEARCH_END:%Y-%m-%d %H:%M} UTC (the research's own count); "
                f"the store window ({window_utc(index)[0]:%Y-%m-%d %H:%M} UTC to {window_utc(index)[1]:%Y-%m-%d %H:%M} UTC) "
                "is compared in verify.")
        if item["product"] in B5_WINDOW_NOTES:
            note += " " + B5_WINDOW_NOTES[item["product"]]
        row(f"B5 window events {item['product']}", item["ours_window_vtec_events"], item["research_window"], note)
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
    for sub in ("j", "z", "s", "k"):
        (hail_out / sub).mkdir(parents=True, exist_ok=True)
    (hail_out / "j" / TILE_EVENTS_DIR).mkdir(parents=True, exist_ok=True)
    ref_counts = {"reports": 0, "records": 0, "warnings": 0}
    new_events: dict[str, list] = {"reports": [], "records": [], "warnings": []}
    seen: dict[tuple, int] = {}

    def remap(kind: str, old: int) -> int:
        if (kind, old) not in seen:
            seen[(kind, old)] = len(new_events[kind])
            new_events[kind].append(real_events[kind][old])
        return seen[(kind, old)]

    def on_day(row) -> bool:
        return utc_from_row(row[0], row[1]).date() in days

    zones_needed, stations_needed, fires_needed, counties_needed = set(), set(), set(), set()
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
            if parse_iso_utc(item["b"]).date() in days or (item["e"] and parse_iso_utc(item["e"]).date() in days):
                warnings.append([remap("warnings", ref), cover])
        keep["warnings"] = sorted(warnings, key=lambda w: (new_events["warnings"][w[0]]["b"],
                                                           new_events["warnings"][w[0]]["k"],
                                                           new_events["warnings"][w[0]]["o"]))
        keep["detections"] = [r for r in doc["detections"] if on_day(r)]
        keep["stations"] = [dict(s) for s in doc["stations"]]
        stations_needed.update(s["id"] for s in keep["stations"])
        zones_needed.update(doc["zones"].keys())
        fires_needed.update(doc.get("fire", {}).keys())
        counties_needed.update(doc.get("counties", {}).keys())
        (hail_out / "j" / f"{name}.json").write_bytes(_compact(keep))
        (hail_out / "j" / TILE_EVENTS_DIR / f"{name}.json").write_bytes(_compact(
            _tile_events(keep, new_events["reports"], new_events["records"], new_events["warnings"])))
        for kind in ref_counts:
            ref_counts[kind] += len(keep[kind])
    # D38: the towns of the cut whose cells are in the sample tiles; their events are the tiles' own warnings (the same
    # polygons, cut to the same days), so the references map to the rows the tiles already hold
    towns_real = json.loads((src / "hail" / "j" / TOWNS_NAME).read_text(encoding="utf-8"))
    towns_keep = {}
    for slug, town in sorted(towns_real["towns"].items()):
        row, col = town["cell"]
        if hail.tile_name(row // hail.TILE, col // hail.TILE) not in sample_tiles:
            continue
        kept = [[remap("warnings", ref), code, office, begin, end]
                for ref, code, office, begin, end in town["events"]
                if parse_iso_utc(begin).date() in days or (end and parse_iso_utc(end).date() in days)]
        towns_keep[slug] = dict(town, events=sorted(kept, key=lambda r: (r[3], r[1], r[2], r[0])))
    towns_doc = {"f": TOWNS_FORMAT, "d0": hail.D0.isoformat(), "state": towns_real["state"],
                 "reason": towns_real.get("reason"), "towns": towns_keep}
    towns_bytes = _compact(towns_doc)
    (hail_out / "j" / TOWNS_NAME).write_bytes(towns_bytes)
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
    for county in sorted(counties_needed):
        doc = json.loads((src / "hail" / "k" / f"{county}.json").read_text(encoding="utf-8"))
        doc["events"] = [e for e in doc["events"] if _zone_when(*_zone_span(e)).date() in days]
        (hail_out / "k" / f"{county}.json").write_bytes(_compact(doc))
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
        "counties": {"state": "sample", "names": {c: real_block.get("counties", {}).get("names", {}).get(c, "")
                                                  for c in sorted(counties_needed)},
                     "count": len(counties_needed)},
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
        "zone_placement": {}, "zone_placed_by_code_alone": 0, "zone_unplaced_rows": [],
        "malformed_rows": {p: 0 for p in PARTS}, "repull": {"months": [], "years": []}, "offline": True,
    }
    e_entries = []
    for path in sorted((hail_out / "j" / TILE_EVENTS_DIR).glob("*.json")):
        raw = path.read_bytes()
        e_entries.append((path.name, len(raw), len(gzip.compress(raw, compresslevel=9, mtime=0))))
    block["events_tiles"] = _events_tiles_block(e_entries, ref_counts)
    block["towns_file"] = _towns_file_block(towns_doc, len(towns_bytes))
    index_bytes = _pretty(dict(sample, **{INDEX_KEY: block}))
    (hail_out / "index.json").write_bytes(index_bytes)
    manifest = json.loads((hail_out / "manifest.json").read_text(encoding="utf-8"))
    files = {rel: meta for rel, meta in manifest["files"].items()
             if not rel.startswith(("hail/j/", "hail/z/", "hail/s/", "hail/k/"))}
    for sub in ("j", "z", "s", "k"):
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
            "counties": len(counties_needed),
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
    v.add_argument("--cache", default=None, help="the joins cache (for the NCEI 2020 totals; optional)")
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
        result = verify(args.store, args.cache)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        for item in result.get("not_run", []):
            print(f"not run: {item['name']}: {item['reason']}", file=sys.stderr)
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
