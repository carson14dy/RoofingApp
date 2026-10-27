"""Base map vectors (B6 product P2): areas, water, places and peaks under the hail layers.

What it is: the outlines and names the map draws under its layers, built from public-domain federal sources only.
Reservations and roads come from the Census Bureau's 2026 TIGER/Line files, forests from the Forest Service's
administrative forest boundaries (seven Montana forests), parks from the Protected Areas Database's fee layer (PAD-US
4.1), lakes and rivers with their GNIS names from the USGS National Hydrography Dataset (NHD), summit names from the
USGS Geographic Names file (GNIS), summit heights from the USGS 3D Elevation Program (3DEP, sampled at each summit's
position), and the places with their 2020 census counts. No address, owner, contact or attribute beyond the kind,
name, source id, position, size and zoom of a feature is read or written.

Output, written into the store next to the other hail/ folders (store/hail/base/):
  v/a.json                    band A (zooms 5 to 7): one file. Reservations, forests, national park land, the large
                              lakes and rivers, and the interstate routes.
  v/b/<cell>.json             band B (zooms 8 to 10): one file per 2 by 2 degree cell, named by its south-west corner
                              ("n46w114" is 46 N, 114 W). State parks, US and state routes, the middle lakes and rivers.
  v/c/<cell>.json             band C (zooms 11 and 12): one file per 1 by 1 degree cell, named the same way. The small
                              lakes of 0.02 km2 and up (streams start in band B, see the river rule).
  w/<tile>.json               band D (zooms 13 and up): one shard per built B1 tile (hail.tile_name), the named water
                              polygons and streams from the large-scale NHD layers, and the local parks.
  peaks.json                  summits with their heights, ranked by height, with their minimum zoom.
  places.json                 places with their 2020 population, a population rank and their minimum zoom.
  index.json                  this product's own index (the sources, the counts, the bytes and the budgets measured).
  hail/index.json             gains "base", whose "vector" entry mirrors the state, as_of, counts, sources and bytes.
  hail/manifest.json          lists every file above with its bytes and SHA-256 (the entries under this product's
                              prefixes are replaced; the other base products keep theirs).

A feature sits in the band of its minimum zoom and carries: its kind, name, minimum zoom "z", source id "id" (the
source's OBJECTID; for a reservation its GEOID; for a road its LINEARID; a river or route joined from several reaches
takes the smallest id among them), label point "l" (areas only: the pole of inaccessibility, computed here, in degrees
to five decimals; a feature with no name has none), route shield "s" (routes only: interstate, us or state), park code
"d" (parks only), size "size" (km for a river or route, km2 for an area: the whole feature in band A and the piece in
bands B to D; null for a park with no acreage, in every band), and the geometry "g": for areas a list of rings (outer
rings and holes; draw with the even-odd rule; a ring is not repeated at its end), for lines a list of paths.
Coordinates are WGS 84 longitude and latitude, rounded to 5 decimals (about 1 m). Kinds: reservation, forest, park,
lake, river, route.

A browser labels each feature (its "id") once per view: an area on the piece that carries "l" (the piece whose box holds
the label point), a river or route on its longest piece in view ("size"). Two features with one name are two labels. A
feature with an empty name is drawn as an outline and is never labelled.

A river or a route is one feature for each name and minimum zoom: the reaches that share a name and a zoom are joined
as paths, so a river is not one feature per NHD reach. Lakes, parks and reservations stay one feature each. Water is kept
only where some vertex lies inside the Montana outline (the first-paint outline in website/static/map/basemap.json): a
stream or lake wholly in a neighbouring state is left out, and a river that crosses the line is kept whole.

Simplification (Douglas-Peucker, in metres): band A 500 m, band B 150 m, band C 50 m, band D none (the shards keep the
source's vertices). Band D features are clipped to their tile; bands B and C to their cell, so a feature that crosses an
edge appears in each file it touches, with its label point only in the file that holds the label. A piece's size is its
own: the length of a river or route piece, or the area of a lake, park or reservation piece. A feature whose geometry
collapses under its band's tolerance is not dropped: it moves to the next finer band, its minimum zoom raised to that
band's first zoom, and the index counts the moves by kind and band ("moved"). For example, a park of 0.02 km2 is a square
of about 141 m, which collapses at 150 m (band B) and is drawn in band C. A feature that collapses in band D, the finest
band, is dropped and counted in "unusable" ("collapsed").

Minimum zoom rules (every rule is a constant below and is written into the index):
  reservation 5; forest 5; park NP 5; NM and NRA 7; SP, SREC and REC 9; LP and LREC 13. A national unit or recreation area
    is named by its unit name (PAD-US gives the National Park Service's code, such as GLAC, in its location name); other
    parks by their location name. A blank name, a placeholder ("Unknown Park") or the state agency's own name is no name:
    the park keeps its outline and gets no name and no label.
  lake (NHD small-scale area, km2): 100 and up 5; 20 and up 7; 2 and up 8; 0.2 and up 9; 0.02 and up 11.
  river (NHD small-scale TotDASqKM, km2): 10,000 and up 5; 3,000 and up 6; 300 and up 8; 100 and up 9. No river starts at
    zoom 7: the rivers of 1,000 to 3,000 km2 do not fit band A's budget at its tolerance, so they start at zoom 8 in band
    B, where the budget has room. The floor is 100 km2: a smaller stream would take the band files past their budgets, so
    it is in no file. A river with no drainage area is left out and counted in the index.
  route: interstate 7; US 8; state 9 (TIGER primary and secondary roads, names "I- 90", "US Hwy 93", "State Hwy 200"). A
    route-like local name ("FAS 533", "W US Hwy 12") carries no shield and is not drawn as a route.
  band D: every named large-scale lake and river and the local parks at 13.
  place (places.json): 50,000 and up 5; 10,000 and up 7; 2,000 and up 8; 500 and up 9; the rest 10. The places already
    on the first-paint base map keep the minimum zoom that map gives them (website/static/map/basemap.json). Two of them
    have consolidated census names, and keep their first-paint names through FIRST_PAINT_NAMES: "Butte-Silver Bow
    (balance)" is Butte, and "Anaconda-Deer Lodge County" is Anaconda.
  peak (peaks.json): ranked by height. Zoom 8 for each summit at least 25 km from every higher zoom 8 summit; zoom 10 for
    each other summit at least 10 km from every summit already placed; the rest zoom 12.
  band D water is requested per 1 degree cell, not per tile: a cell answers in one request while the service answers,
    and a request per tile would take too long to finish serially (the decision and its estimate are in the P2 report).

Budgets (gzip bytes, measured with gzip level 9): band A under 150,000; each band B file under 100,000; each band C file
under 60,000; each band D shard under 30,000. A file over its budget drops its least visible features first: the
protected kinds are kept, then the highest minimum zoom goes, then the smallest size, and a feature with no size goes
first among its zoom. Reservations and forests are never dropped. A file whose protected features alone exceed the budget
is written whole and marked over budget. Verify fails on an over-budget file, a file whose bytes or SHA-256 differ from
the manifest, a count that does not match the files, a missing band B or C file, or a band D shard count that differs
from the built tiles. A named check (a reservation, a forest, a park, a route shield, a river, a place, the McDonald Peak
height) is not checked, and says why, when its source failed in the build, because the index already names that failure.
A check that is not checked is outside the pass count: verify's ok is computed over the checks that ran, and the count of
checks not checked is shown.

Sources, terms and credit (quoted from the sources' own metadata where it was read; the index holds each source's state,
file count, bytes and the reasons for any failure, and the build does not read a source's own release date):
  Census TIGER/Line 2026 (AIANNH, PRISECROADS, PLACE)   https://www2.census.gov/geo/tiger/TIGER2026/
      "The TIGER/Line Shapefile products are not copyrighted ... acknowledgement must be given to the U.S. Census Bureau
      as the source." Credit: "Source: U.S. Census Bureau, TIGER/Line 2026 (reservations, roads and place names)."
      The reservation outlines are the full-resolution file tl_2026_us_aiannh.zip at every zoom; the 1:500,000
      cartographic file is never used.
  Census 2020 redistricting file (population of each place)   https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/Montana/mt2020.pl.zip
      Credit: "Source: U.S. Census Bureau, 2020 Census, Public Law 94-171 counts (place populations)."
  Forest Service administrative forest boundaries (EDW)   https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer/0
      The layer's copyright line is empty and its description says "intended for read-only use". That sentence is read as a
      usage note on a federal work, which is in the public domain (17 U.S.C. 105). OPEN for counsel to confirm (counsel
      item 23); the layer ships with its credit line.
      Credit: "Source: USDA Forest Service, forest boundaries (national forests)."
  PAD-US 4.1 Fee layer (parks)   https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Managers_PADUS/FeatureServer/0
      "This content describes the PAD-US dataset which is in the public domain." Credit: "Source: Protected Areas
      Database of the United States (PAD-US) 4.1, U.S. Geological Survey (parks)."
  USGS National Hydrography Dataset (lakes and rivers)   https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer
      Credit: "Source: U.S. Geological Survey, National Hydrography Dataset (lakes and rivers)." The layer's own terms line
      was not read in this build. OPEN for counsel to confirm (counsel item 24); the layer ships with its credit line.
  USGS Geographic Names (summit names)   https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_MT_Text.zip
      Credit: "Source: U.S. Geological Survey, Geographic Names Information System (summit names)."
  USGS 3D Elevation Program (summit heights)   https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples
      "All 3DEP products available through The National Map are in the public domain and may be used without
      restriction." This statement is quoted from a secondary copy of the USGS text (the primary USGS page was not
      reachable to the check, as in website/terrain.py, which says the same). Credit: "3DEP data courtesy of the U.S.
      Geological Survey (summit heights)."

Failures (D16): a request that fails is retried (three tries with a wait, a 20 s connect and 300 s read limit; a heavy
query that is split gets one try above the last split level, see nhd_cell_features); a cached copy that exists is then
used and its reason is recorded in the index. A cache file that cannot be read is a failed copy, never a crash. A source
with no usable copy fails alone: the kinds it feeds are left out of the files, the index names each failed source and
kind, and the state is "partial". A kind whose source loads but holds nothing usable after its filters (no reservation,
no route, no park, no named river or lake, no summit height) is a failure too, so an empty layer is never shown as
loaded. Without pyshp (the shapefile reader) the kinds that read shapefiles (reservations, routes and places) fail with
the reason "the shapefile reader is not installed", and the state is partial.

The small-scale water (bands A to C) is read page by page, 2,000 features to a page (the page size is set in NHD). Each
page gets SMALL_TRIES (2) tries, and a try waits at most SMALL_READ_S (120) seconds for its answer, so one page that fails
costs at most about 280 seconds (two tries of a 20-second connect wait and a 120-second read wait, and the wait between them). A page that fails after its tries is skipped and the next page is asked for, so the pages
that answer still load: up to SMALL_SKIP_PAGES (2) failed pages in a row are skipped, and a third ends the query. The
query therefore spends at most about three failed pages (about 840 seconds) on failures, plus the pages that answer; on a slow
day that may not all fit inside the monthly budget, and the cache carries the pages read into the next run. The missed part is named as a partial source, and the pages that loaded are cached, so the next run asks only for
the pages it does not have.

Deadline (--deadline-at): no request starts after the deadline. A source whose next request would start then records the
reason "deadline", and a band D cell that needs such a request is listed as unbuilt with that reason (coverage
band_d_cell_reasons). A cell whose pages are all in the cache is still built. The monthly job's step cap is 20 minutes
(integration.md section 7); the cache carries the rest into the next run. A request still waiting for its response GRACE_S
(90) seconds after the deadline is cut (its connect wait, at most 20 seconds, counts too), so the build's own writing ends
inside the job's margin: the monthly step passes a deadline 120 seconds before its cap.

Band D coverage: a tile with no band D shard is "not built, the browser draws band C's water there". Concretely, where a
tile has no band D shard the browser keeps drawing band C's lakes and rivers at zoom 13 and up (they loaded statewide),
and the sheet's water line for that area reads "Detailed water and local parks: Data unavailable for this area in this
update. This is not an all-clear." (WORDS["water_line_unavailable"]). A cell whose water request fails leaves its tiles
unbuilt. The index counts the built and unbuilt tiles (coverage.tiles_built, tiles_unbuilt), the areas in coverage
(band_d_areas) and the cells that did not load (band_d_failed_cells, band_d_cell_reasons). When only band D water
failed, the sentence names the failed and the total areas (WORDS["band_d_water_partial"]).

Unavailability (D20): when the product cannot be built, the index block carries state "unavailable", the sentence
WORDS["unavailable"] in "problem" and the technical reason in "detail", and this product's files are removed (the other
base products keep theirs). The same happens for a store that lists no tiles, and for a build in which every source
fails. The site shows the sentence; no outline or name is ever shown as an all-clear. Every sentence in WORDS that says
a part is missing or partial begins with "Data unavailable." and ends with "This is not an all-clear." (D117(b),
D128(b)); the notes that explain a value or a source (peak_note, place_note, route_note, water_note, park_note) are not
such sentences. The water line (WORDS["water_line_unavailable"], D134(a)) is the one status sentence that does not begin
with the words: they sit inside it, after "Detailed water and local parks:". A missing input never reads as zero:
a place with no population shows "Data unavailable" with the reason "no census count under its code" in its row, a
summit with no height is not ranked and is counted, a park with no acreage has no size (null), and a river with no
drainage area is left out and counted.

Cache (D16, D112(m)): the cache keeps the newest cycle of each source: the TIGER 2026 files, the 2020 census file, the
GNIS file, and the EDW, PAD-US and NHD pages and the 3DEP batches of the current queries (every envelope of the statewide
plan, and its quarters). After a statewide online build in which no request failed, every other file in the source
folders is an older cycle and is deleted; the index counts them (cache files and bytes). An offline build and a test box
never delete anything. A response that fails its check is never written to the cache.

Shared index (B6 P1-F1 and P3-R8): hail/base/index.json is one document shared with the terrain and landmark parts. A
new document starts with "f": "hail-base-index-v1". This part writes only its own key ("vector") and keeps the other
blocks. A document whose "f" is another value, or that is not JSON, is refused before any file changes: the error names
the file and the format found, the file is kept, and verify reports the same. A base index written by the earlier build
of this part (before this pass) carries "format" and no "f", so it is refused: remove hail/base/index.json from
that store and rebuild the three base parts, since each part rewrites its own block.

Command line (run from the repository root):
    python -m website.basemap2 build --store DIR [--cache DIR] [--offline] [--refresh] [--box=W,S,E,N] [--deadline-at EPOCH]
    python -m website.basemap2 verify --store DIR [--cache DIR]
    python -m website.basemap2 unavailable --store DIR --reason TEXT

--cache defaults to a folder named basemap2-cache beside the store folder. --box limits the band D fetches and shards to
a box (a test run); without it band D covers every tile the store lists. A western longitude starts with a minus sign, so
write the box with the equals form: --box=-114.1,46.8,-113.9,47. The cache keeps every response (one file per page of
each query, named by the source, a digest of the query's parameters and the page's offset), so a second run reads the
cache and makes no request for a query it has. Measures are written by the caller (the report); the module returns them
in its result.
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
# the source folders of the download cache, and the files the statewide plan names (the cache pruning, D112(m))
CACHE_FOLDERS = ("census", "gnis", "edw", "padus", "nhd_small_lines", "nhd_small_areas", "nhd_large_lines",
                 "nhd_large_areas", "3dep")
TIGER_AIANNH = "census/tl_2026_us_aiannh.zip"
TIGER_PRISEC = "census/tl_2026_30_prisecroads.zip"
TIGER_PLACE = "census/tl_2026_30_place.zip"
CENSUS_PL = "census/mt2020.pl.zip"
GNIS_FILE = "gnis/DomesticNames_MT_Text.zip"
NEXT_BAND = {"A": "B", "B": "C", "C": "D"}          # where a feature that collapses under its band's tolerance moves
REASON_DEADLINE = "deadline"                         # the reason of a request that --deadline-at stopped
REASON_NO_SHAPEFILE = "the shapefile reader is not installed"
REASON_NO_CENSUS_COUNT = "no census count under its code"
SAMPLE_BATCH = 200                                   # summit points per 3DEP request
# The two first-paint towns whose census names are consolidated city-county names: (TIGER name, first-paint name). The
# first-paint base map (website/static/map/basemap.json) gives the names and minimum zooms; these rows keep them.
FIRST_PAINT_NAMES = (("Butte-Silver Bow (balance)", "Butte"), ("Anaconda-Deer Lodge County", "Anaconda"))
FIRST_PAINT_BY_TIGER = dict(FIRST_PAINT_NAMES)

BAND_ZOOMS = {"A": (5, 7), "B": (8, 10), "C": (11, 12), "D": (13, 18)}
BAND_TOL_M = {"A": 500.0, "B": 150.0, "C": 50.0, "D": 0.0}
BAND_BUDGET = {"A": 150_000, "B": 100_000, "C": 60_000, "D": 30_000}   # gzip bytes per file (per shard for D)
MT_BOX = (-116.05, 44.36, -104.03, 49.01)     # west, south, east, north: the Montana box of the requests
CELL_DEG = {"B": 2, "C": 1}                   # cell sizes in whole degrees; the cells are aligned to whole degrees
SPACING_KM = {8: 25.0, 10: 10.0}              # peak spacing for zooms 8 and 10 (zoom 12 is the rest)
PEAK_CHECK = {"name": "McDonald Peak", "metres": 2994.4, "feet": 9824,
              "also_listed_metres": 2993.0, "also_listed_feet": 9820,
              "source": ("Peakbagger peak 4705, as cited by the Wikipedia article 'McDonald Peak, Montana': the article's "
                         "infobox gives 9,824 ft (2,994.4 m) and its text gives 9,820 ft (2,993 m). The citation gives "
                         "16 January 2019 as Peakbagger's access date; the article was read on 25 October 2026. The datum "
                         "is not stated.")}
PEAK_TOLERANCE_M = 30.0
PLACE_CHECK = ("Lolo", "Frenchtown")
RESERVATION_COUNT = 7
FOREST_COUNT = 7
RIVER_CHECK = ("Clark Fork", "Bitterroot River")
PROTECTED_KINDS = frozenset({"reservation", "forest"})
ALLOWED_KEYS = frozenset({"k", "n", "z", "id", "l", "g", "s", "d", "size"})
PLACE_LSAD = {"25": "city", "43": "town", "47": "village", "57": "cdp"}
UNIT_NAME_CODES = frozenset({"NP", "NM", "NRA", "REC"})   # PAD-US gives these the unit's full name in Unit_Nm (Loc_Nm holds a code)
PLACEHOLDER_NAMES = frozenset({"unknown", "unknown park", "unnamed", "unnamed park", "no name", "none",
                               "n/a", "not applicable", "montana fish, wildlife and parks"})
NAME_EXPAND = (("Riv", "River"), ("Crk", "Creek"), ("Lk", "Lake"), ("Mtn", "Mountain"), ("Natl", "National"))

# Forest Service forests whose share of their area inside Montana is at least half (the clip measured 2026-10-25:
# Beaverhead-Deerlodge 99.1, Bitterroot 70.8, Custer Gallatin 97.6, Flathead 100, Helena-Lewis and Clark 100, Kootenai
# 98.0, Lolo 99.1 percent; Idaho Panhandle 1.2 percent and the rest below half).
FOREST_NAMES = ("Beaverhead-Deerlodge National Forest", "Bitterroot National Forest", "Custer Gallatin National Forest",
                "Flathead National Forest", "Helena-Lewis and Clark National Forest", "Kootenai National Forest",
                "Lolo National Forest")

LAKE_RULES = ((100.0, 5), (20.0, 7), (2.0, 8), (0.2, 9), (0.02, 11))           # NHD AREASQKM, km2 -> minimum zoom
RIVER_RULES = ((10000.0, 5), (3000.0, 6), (300.0, 8), (100.0, 9))   # no river at zoom 7 (see the docstring)
RIVER_FLOOR_KM2 = RIVER_RULES[-1][0]      # the smallest drainage area that is fetched (the last rule)
LAKE_FLOOR_KM2 = LAKE_RULES[-1][0]        # the smallest lake area that is fetched (the last rule)
PARK_RULES = {"NP": ("national park", 5), "NM": ("national monument", 7), "NRA": ("national recreation area", 7),
              "SP": ("state park", 9), "SREC": ("state recreation area", 9), "REC": ("recreation area", 9),
              "LP": ("local park", 13), "LREC": ("local recreation area", 13)}
ROUTE_ZOOM = {"interstate": 7, "us": 8, "state": 9}
# A directional suffix ("US Hwy 93 N") is the same numbered route. Business loops ("I- 90 Bus"), old routes and prefixed
# names ("W US Hwy 12") are not drawn as shields.
ROUTE_PATTERNS = (("interstate", "I", re.compile(r"^I- ?(\d+)$"), "I-{}"),
                  ("us", "U", re.compile(r"^US Hwy (\d+)(?: [NSEW])?$"), "US-{}"),
                  ("state", "S", re.compile(r"^State Hwy (\d+)(?: [NSEW])?$"), "MT-{}"))
LARGE_ZOOM = 13                                              # band D: every named large-scale feature
PLACE_RULES = ((50000, 5), (10000, 7), (2000, 8), (500, 9))  # population -> minimum zoom; the rest are zoom 10

# The NHD layers the requests use. The fields differ by layer (the service answers 400 for an unknown field).
NHD = {
    # the small-scale layers allow pages of 2,000 features (maxRecordCount in their layer descriptions, read on 2026-10-27).
    # A page is one request, so the page size sets how many requests the state query takes: 24 at 2,000 instead of 47 at
    # 1,000. In the 2026-10-27 measurements a 2,000-feature page took 1.2 to 1.5 s in a fast window and up to about 60 s in a
    # slow one, and some slow-window pages answered HTTP 504 after 180 s. No 1,000 and 2,000 pair was timed in one slow
    # window, so the page size is not claimed to change a request's time. The cache names a page by its offset, and the
    # paging advances by the features a page returns, so pages cached at 1,000 stay valid.
    "small_lines": {"layer": 4, "where": f"GNIS_NAME IS NOT NULL AND TotDASqKM >= {RIVER_FLOOR_KM2:g}",
                    "fields": "OBJECTID,GNIS_NAME,TotDASqKM,LENGTHKM,FTYPE,FCODE", "simplify": 0.0001, "page": 2000},
    "small_areas": {"layer": 10, "where": f"GNIS_NAME IS NOT NULL AND AREASQKM >= {LAKE_FLOOR_KM2:g}",
                    "fields": "OBJECTID,GNIS_NAME,AREASQKM,FTYPE,FCODE", "simplify": 0.0001, "page": 2000},
    # the large-scale pages are 250 features: a page of 1,000 dense features in one cell timed out at the service (HTTP 504)
    # after about 300 seconds. The cache names a page by its offset, not its size, and the paging advances by the number of
    # features a page returns, so the pages cached at 1,000 stay valid.
    "large_lines": {"layer": 6, "where": "gnis_name IS NOT NULL",
                    "fields": "OBJECTID,gnis_name,lengthkm,ftype,fcode", "simplify": 0.0, "page": 250},
    "large_areas": {"layer": 12, "where": "GNIS_NAME IS NOT NULL",
                    "fields": "OBJECTID,GNIS_NAME,AREASQKM,FTYPE,FCODE", "simplify": 0.0, "page": 250},
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
GRACE_S = 90.0                                               # a request still waiting this long after --deadline-at is cut
SMALL_SKIP_PAGES = 2                                         # state pages that fail in a row are skipped; the next one ends the query
SMALL_TRIES = 2                                              # tries for one small-scale state page (one failed page costs at most about 245 s)
SMALL_READ_S = 120.0                                         # seconds one try of a small-scale state page may wait for its answer
PACE_S = {"hydro.nationalmap.gov": 0.5, "default": 0.2}
ATTEMPTS = 3
REASON_NO_ANSWER = S.REASON_NO_ANSWER

WORDS = {
    "unavailable": ("Data unavailable. Map outlines and names could not be loaded in this update; that is not the "
                    "same as no outline or name. This is not an all-clear."),
    "part_unavailable": ("Data unavailable. {Part} could not be loaded in this update; that is not the same as no "
                         "{one}. This is not an all-clear."),
    "partial_named": ("Data unavailable. Some map outlines and names could not be loaded in this update for {names}; "
                      "that is not the same as none there. This is not an all-clear."),
    "peaks_unknown": ("Data unavailable. The height of {count} summits could not be read in this update; they are not "
                      "ranked, which is not the same as no height. This is not an all-clear."),
    "population_unknown": ("Data unavailable. The 2020 population of {count} places could not be read in this update; "
                           "they show Data unavailable. This is not an all-clear."),
    "peak_note": ("A summit height is the 3D Elevation Program's value at the summit's position, in metres and feet. "
                  "A summit whose height could not be read is left out of the list, and the number left out is noted."),
    "place_note": ("A place's population is the 2020 census count. A place with no count shows Data unavailable."),
    "route_note": "A route shield is an interstate, US or state route number from the Census road file.",
    "water_note": ("Lakes and rivers are the USGS National Hydrography Dataset with its Geographic Names; a stream or lake "
                   "shown here is not a statement about water at an address."),
    "park_note": "A park outline is from the Protected Areas Database; a park is not a statement about its use.",
    "coverage_box": ("Data unavailable. Detailed lake, river and park outlines at zoom 13 and up are built only for "
                     "the tiles in the area {area}. Elsewhere the browser keeps drawing band C's lakes and rivers at "
                     "zoom 13 and up, and the sheet's water line reads Data unavailable for that area. This is not an "
                     "all-clear."),
    "band_d_water_partial": ("Data unavailable. Detailed lake and river outlines at zoom 13 and up could not be "
                             "loaded for {failed} of {areas} areas in this update; lakes and rivers at zooms 5 to 12 "
                             "loaded statewide. This is not an all-clear."),
    # D134(a): the words "Data unavailable" sit inside this sentence, so it does not begin with them (UnavailableWordingTests)
    "water_line_unavailable": ("Detailed water and local parks: Data unavailable for this area in this update. This is not "
                               "an all-clear."),
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

    def past_deadline(self) -> bool:
        """True once --deadline-at has passed: no request starts after it (its source records REASON_DEADLINE)."""
        return self.deadline_at is not None and time.monotonic() >= self.deadline_at

    def request_timeout(self, read_cap: float | None = None) -> tuple[float, float]:
        """The (connect, read) timeout of the next request: READ_TIMEOUT, its read part at most read_cap when one is given.
        With a deadline, the time left to deadline + GRACE_S caps both parts, so a request started just before the deadline
        ends at most GRACE_S plus its connect wait after it. The read part applies to each wait for bytes, so a response
        that keeps sending bytes is not cut here."""
        read = READ_TIMEOUT[1] if read_cap is None else min(READ_TIMEOUT[1], read_cap)
        if self.deadline_at is None:
            return (READ_TIMEOUT[0], read)
        left = max(1.0, self.deadline_at + GRACE_S - time.monotonic())
        return (min(READ_TIMEOUT[0], left), min(read, left))

    def pace(self, host: str) -> None:
        gap = PACE_S.get(host, PACE_S["default"]) - (time.monotonic() - self.last.get(host, 0.0))
        if gap > 0:
            time.sleep(gap)
        self.last[host] = time.monotonic()


def _host(url: str) -> str:
    return url.split("/")[2] if "//" in url else "default"


def fetch(ctx: _Ctx, source: str, url: str, name: str, check, *, params: dict | None = None,
          method: str = "GET", attempts: int = ATTEMPTS,
          read_cap: float | None = None) -> tuple[bytes | None, str, str | None]:
    """(bytes or None, state, reason). The cache file is name under the cache root. A cached file that passes check is
    read unless refresh is set. Offline, no request is made. Otherwise the request is tried attempts times (ATTEMPTS
    unless a caller asks for fewer); a copy that passes check is kept. When the request fails and a cached copy exists,
    the cached copy is used and the reason is kept (D16). A cache file that cannot be read is a failed copy, never a
    crash. A response that fails check is never written. Past the deadline no request is made (the reason is "deadline");
    a cached copy is still read. A request still waiting for its response is cut GRACE_S seconds after the deadline
    (request_timeout); read_cap, when given, caps the wait for each response part."""
    import requests
    path = ctx.cache / name
    cached, corrupt = None, None
    if path.is_file():
        try:
            cached = path.read_bytes()
        except OSError as exc:
            corrupt = f"the cached copy could not be read ({type(exc).__name__})"
        else:
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
    for attempt in range(1, attempts + 1):
        ctx.pace(_host(url))
        if ctx.past_deadline():                 # checked after the pacing wait: no request starts after the deadline
            last = REASON_DEADLINE
            break
        ctx.requests += 1
        try:
            if method == "POST":
                resp = requests.post(url, data=params or {}, headers={"User-Agent": USER_AGENT},
                                     timeout=ctx.request_timeout(read_cap))
            else:
                resp = requests.get(url, params=params or {}, headers={"User-Agent": USER_AGENT},
                                    timeout=ctx.request_timeout(read_cap))
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
        if attempt < attempts:
            time.sleep(1.5 * attempt)
    if cached is not None:
        reason = f"served the cached copy after: {last}"
        ctx.record(source, "cache", reason, len(cached))
        return cached, "cache", reason
    ctx.record(source, "failed", last if not corrupt else f"{last}; {corrupt}")
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


def _text(value) -> str:
    """A source's identifier as text: "" when the source gives none."""
    return "" if value is None else str(value).strip()


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


_EDGES = None


def _outline_edges():
    """The Montana outline's edges as numpy arrays (x1, y1, x2, y2), read once."""
    global _EDGES
    if _EDGES is None:
        import numpy as np
        x1, y1, x2, y2 = [], [], [], []
        for ring in montana_outline():
            n = len(ring)
            for i in range(n):
                (ax, ay), (bx, by) = ring[i - 1], ring[i]
                x1.append(ax)
                y1.append(ay)
                x2.append(bx)
                y2.append(by)
        _EDGES = tuple(np.array(v, dtype=float) for v in (x1, y1, x2, y2))
    return _EDGES


def in_montana_many(lons, lats):
    """The even-odd test of many points at once (numpy, in chunks), the same rule as in_montana."""
    import numpy as np
    x1, y1, x2, y2 = _outline_edges()
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    out = np.zeros(lons.shape[0], dtype=bool)
    dy = y2 - y1
    dx = x2 - x1
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(dy != 0, dx / np.where(dy != 0, dy, 1.0), 0.0)
    step = 4096
    for start in range(0, lons.shape[0], step):
        lo = lons[start:start + step, None]
        la = lats[start:start + step, None]
        crosses = ((y1 > la) != (y2 > la)) & (lo < (la - y1) * slope + x1)
        out[start:start + step] = (crosses.sum(axis=1) % 2) == 1
    return out


def keep_in_montana(items: list[dict]) -> list[dict]:
    """The items (each with "parts") that have at least one vertex inside the Montana outline. Water that lies wholly in a
    neighbouring state is not drawn on the Montana map; a river or lake that crosses the line is kept whole."""
    import numpy as np
    if not items:
        return []
    lons, lats, owner = [], [], []
    for i, item in enumerate(items):
        for part in item["parts"]:
            for lon, lat in part:
                lons.append(lon)
                lats.append(lat)
                owner.append(i)
    keep = np.zeros(len(items), dtype=bool)
    if owner:
        inside = in_montana_many(lons, lats)
        keep[np.asarray(owner, dtype=np.int64)[inside]] = True
    return [item for item, k in zip(items, keep) if k]


def _is_placeholder(text: str) -> bool:
    """A blank name, a placeholder ("Unknown Park") or the state fish and parks agency's name in a unit field."""
    low = text.strip().casefold()
    return not low or low in PLACEHOLDER_NAMES or "wildlife and parks" in low


def park_name(code: str, attrs: dict) -> str:
    """The name a park shows, or "" when it has none. PAD-US gives the National Park Service's four-letter code (GLAC,
    YELL, BICA) in the location name of its federal units, so a national unit or recreation area takes its unit name
    first; every other park takes its location name first. A blank name, a placeholder and an agency's name are no name
    (the park keeps its outline and gets no label). A code is used only when no other name is there."""
    unit = str(attrs.get("UNIT_NM") or "").strip()
    loc = str(attrs.get("LOC_NM") or "").strip()
    first, second = (unit, loc) if code in UNIT_NAME_CODES else (loc, unit)
    names = [n for n in (first, second) if not _is_placeholder(n)]
    for name in names:
        if not (name.isupper() and len(name) <= 5):
            return name
    return names[0] if names else ""


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
        out.append({"class": named[0], "ref": named[1], "parts": _shp_parts(shp),
                    "oid": str(d.get("LINEARID") or "").strip()})
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


def fetch_pages(ctx: _Ctx, source: str, url: str, key: str, params: dict, page: int,
                attempts: int = ATTEMPTS, skip_pages: int = 0,
                read_cap: float | None = None) -> tuple[list[dict], list[str]]:
    """Every feature of one query, paged by OBJECTID. Each page is a cache file. A page that fails after its tries ends the
    query: the features read so far are kept and the failure is named (D16); the pages already cached are read next time.
    With skip_pages (the small-scale state query), a failed page is skipped instead: the next page is asked for at offset
    plus page, so the pages that answer still load and the missed one is named. Up to skip_pages failed pages in a row are
    skipped; the next failure ends the query, and so does the deadline. Each page is tried attempts times."""
    feats, problems = [], []
    offset = 0
    misses = 0                                  # failed pages in a row
    while True:
        q = dict(params, orderByFields="OBJECTID", resultOffset=offset, resultRecordCount=page, f="json")
        data, state, reason = fetch(ctx, source, url, page_name(source, key, params, offset), _check_features,
                                    params=q, attempts=attempts, read_cap=read_cap)
        if data is None:
            problems.append(reason or REASON_NO_ANSWER)
            misses += 1
            if reason == REASON_DEADLINE or misses > skip_pages:
                break
            offset += page                      # the page is missed; the service answers pages of page features
            continue
        misses = 0
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


def nhd_features(ctx: _Ctx, source: str, env: tuple[float, float, float, float], key: str,
                 attempts: int = ATTEMPTS, skip_pages: int = 0,
                 read_cap: float | None = None) -> tuple[list[dict], list[str]]:
    spec = NHD[source]
    return fetch_pages(ctx, f"nhd_{source}", NHD_URL.format(layer=spec["layer"]), key, nhd_params(source, env),
                       spec["page"], attempts=attempts, skip_pages=skip_pages, read_cap=read_cap)


SPLIT_DEPTH = 2   # a failed envelope is split into quarters, and a quarter that fails again into quarters once more


def nhd_cell_features(ctx: _Ctx, source: str, env: tuple[float, float, float, float], key: str,
                      depth: int = 0) -> tuple[list[dict], list[str]]:
    """The features of one envelope. The service answers a query that is heavy at its offset with HTTP 504, and the time a
    page takes grows with its offset, so a query that fails part way is split into four smaller envelopes (the quarters),
    and a quarter that fails is split again, down to SPLIT_DEPTH levels. A feature that lies across a split is returned by
    each part it touches; the caller drops the repeats by OBJECTID. When every part answers, the envelope is complete and
    the problems of the query that was split are dropped (the parts say what did not load). A query that the deadline
    stopped is not split: splitting it would only ask again after the deadline."""
    # a query above the last level gets one attempt: a heavy query times out again on a retry, and a split is the remedy
    feats, probs = nhd_features(ctx, source, env, key, attempts=1 if depth < SPLIT_DEPTH else ATTEMPTS)
    if not probs or depth >= SPLIT_DEPTH or all(p == REASON_DEADLINE for p in probs):
        return feats, probs
    w, s, e, n = env
    mx, my = (w + e) / 2.0, (s + n) / 2.0
    quarters = ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n))
    out, problems = list(feats), []
    for i, quarter in enumerate(quarters):
        part, part_probs = nhd_cell_features(ctx, source, quarter, f"{key}q{depth + 1}{i}", depth + 1)
        out.extend(part)
        problems.extend(part_probs)
    return out, problems


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


def _sample_name(start: int, chunk) -> str:
    """The cache file of one 3DEP batch: the index of its first point and a digest of its points."""
    digest = hashlib.sha1(json.dumps(chunk).encode("utf-8")).hexdigest()[:12]
    return f"3dep/samples_{start:05d}_{digest}.json"


def sample_elevations(ctx: _Ctx, points: list[tuple[float, float]],
                      batch: int = SAMPLE_BATCH) -> tuple[list[float | None], list[str]]:
    """The 3DEP height in metres at each point, in batches (one request per batch, cached by its points)."""
    out: list[float | None] = [None] * len(points)
    problems = []
    for start in range(0, len(points), batch):
        chunk = points[start:start + batch]
        params = {"geometry": json.dumps({"points": [[lon, lat] for lon, lat in chunk],
                                          "spatialReference": {"wkid": 4326}}),
                  "geometryType": "esriGeometryMultipoint", "returnFirstValueOnly": "true", "f": "json"}
        data, state, reason = fetch(ctx, "3dep", DEM_URL, _sample_name(start, chunk), _check_samples,
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
    """The listed tile names that a bounding box (west, south, east, north) touches. A box that ends exactly on a tile
    edge does not touch the tile beyond that edge: the corners are taken a hair inside the box (1e-9 degree), so a cell
    that ends at 44 N does not claim the tiles of the cell to its south."""
    w, s, e, n = bbox
    eps = 1e-9
    if e - w > 2 * eps and n - s > 2 * eps:
        r0, c0 = tile_of(n - eps, w + eps)
        r1, c1 = tile_of(s + eps, e - eps)
    else:
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

def _rec(kind: str, name: str, zoom: int, parts, *, closed: bool, size: float | None, shield: str | None = None,
         code: str | None = None, oid: str = "") -> dict:
    """A feature before its band's simplification: the raw parts in longitude and latitude, its source id (oid) and its
    size (None when the source gives none)."""
    return {"k": kind, "n": expand_name(name), "z": int(zoom), "p": parts, "closed": closed,
            "size": None if size is None else float(size), "s": shield, "d": code, "id": str(oid or "")}


def finish(rec: dict, tol: float) -> dict | None:
    """The feature for one record: simplified at the band's tolerance in metres (Douglas-Peucker), rounded to 5 decimals,
    tidied, and given the pole of inaccessibility for a named area (computed on the simplified rings). None when nothing is
    left to draw. A feature with no name gets no label point."""
    parts = [_dp(p, tol) for p in rec["p"]] if tol > 0 else rec["p"]
    g = _tidy(parts, rec["closed"])
    if not g:
        return None
    label = None
    if rec["closed"] and rec["n"]:
        at = pole(g)
        if at is not None:
            label = [round(at[0], 5), round(at[1], 5)]
    return {"k": rec["k"], "n": rec["n"], "z": rec["z"], "l": label, "s": rec["s"], "d": rec["d"], "g": g,
            "size": rec["size"], "protect": rec["k"] in PROTECTED_KINDS, "id": rec["id"]}


def _merge_lines(recs: list[dict]) -> list[dict]:
    """Joins the reaches of one river (or one route number) that share a minimum zoom into one feature with a path per
    reach. NHD splits a river into hundreds of reaches, so this keeps one named feature per river and zoom instead of one
    per reach. The joined feature takes the smallest id among its reaches. Areas are never joined: each lake, park and
    reservation stays its own feature."""
    joined: dict = {}
    rest: list[dict] = []
    for r in recs:
        if r["k"] not in ("river", "route"):
            rest.append(r)
            continue
        key = (r["k"], r["n"], r["z"], r["s"])
        if key in joined:
            joined[key]["p"].extend(r["p"])
            joined[key]["size"] += r["size"]
            joined[key]["id"] = min(joined[key]["id"], r["id"], key=lambda s: (len(s), s))
        else:
            joined[key] = dict(r, p=list(r["p"]))
    return rest + list(joined.values())


def build_features(inputs: dict, stats: dict | None = None) -> dict[str, list[dict]]:
    """The features of each band. Each source's records go to the band of their minimum zoom, simplified at that band's
    tolerance. A feature whose geometry collapses under that tolerance moves to the next finer band, its minimum zoom
    raised to that band's first zoom (it is not dropped); one that collapses in band D, the finest band, is dropped.
    stats (optional) receives "moved" (kind -> {"B to C": n}) and "collapsed" (the features dropped). inputs holds the
    parsed sources (a missing source is an absent key or None)."""
    stats = {} if stats is None else stats
    stats.setdefault("moved", {})
    stats.setdefault("collapsed", 0)
    recs: list[dict] = []
    for r in inputs.get("reservations") or []:
        recs.append(_rec("reservation", r["name"], 5, r["parts"], closed=True, size=area_km2(r["parts"]),
                         oid=r["geoid"]))
    for fo in inputs.get("forests") or []:
        recs.append(_rec("forest", fo["name"], 5, fo["parts"], closed=True, size=area_km2(fo["parts"]), oid=fo["oid"]))
    for pk in inputs.get("parks") or []:
        spec = PARK_RULES.get(pk["code"])
        if spec is not None:
            recs.append(_rec("park", pk["name"], spec[1], pk["parts"], closed=True, size=pk["size"], code=pk["code"],
                             oid=pk["oid"]))
    for lk in inputs.get("lakes_small") or []:
        zoom = lake_zoom(lk["area"])
        if zoom is not None:
            recs.append(_rec("lake", lk["name"], zoom, lk["parts"], closed=True, size=lk["area"], oid=lk["oid"]))
    for rv in inputs.get("rivers_small") or []:
        zoom = river_zoom(rv["total"])
        if zoom is not None:
            recs.append(_rec("river", rv["name"], zoom, rv["parts"], closed=False, size=rv["length"], oid=rv["oid"]))
    for rt in inputs.get("routes") or []:
        recs.append(_rec("route", rt["ref"], ROUTE_ZOOM[rt["class"]], rt["parts"], closed=False,
                         size=length_km(rt["parts"]), shield=rt["class"], oid=rt["oid"]))
    for lk in inputs.get("lakes_large") or []:
        recs.append(_rec("lake", lk["name"], LARGE_ZOOM, lk["parts"], closed=True, size=lk["area"], oid=lk["oid"]))
    for rv in inputs.get("rivers_large") or []:
        recs.append(_rec("river", rv["name"], LARGE_ZOOM, rv["parts"], closed=False, size=rv["length"], oid=rv["oid"]))
    out: dict[str, list[dict]] = {band: [] for band in BAND_ZOOMS}
    for rec in _merge_lines(recs):
        band = band_of(rec["z"])
        feature = finish(rec, BAND_TOL_M[band])
        while feature is None and band in NEXT_BAND:
            nxt = NEXT_BAND[band]
            moves = stats["moved"].setdefault(rec["k"], {})
            moves[f"{band} to {nxt}"] = moves.get(f"{band} to {nxt}", 0) + 1
            rec = dict(rec, z=max(rec["z"], BAND_ZOOMS[nxt][0]))
            band = nxt
            feature = finish(rec, BAND_TOL_M[band])
        if feature is None:
            stats["collapsed"] += 1
        else:
            out[band].append(feature)
    return out


def encode(f: dict) -> dict:
    """The feature as a band file writes it. "id" is the source id; "size" is the piece's own size (km for a river or
    route, km2 for an area), or null when the source gives none (a park with no acreage, in every band)."""
    out = {"k": f["k"], "n": f["n"], "z": f["z"], "id": f.get("id") or ""}
    if f.get("l") is not None:
        out["l"] = f["l"]
    if f.get("s"):
        out["s"] = f["s"]
    if f.get("d"):
        out["d"] = f["d"]
    out["size"] = None if f.get("size") is None else round(float(f["size"]), 4)
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


def _visibility(f: dict) -> tuple:
    """The order in which an over-budget file drops features, the least visible last: protected kinds first, then the
    lower minimum zoom, then the larger size. A feature with no size is ranked after every feature of its zoom."""
    size = f["size"]
    return (0 if f["protect"] else 1, f["z"], math.inf if size is None else -size, f["n"] or "")


def fit(header: dict, feats: list[dict], budget: int) -> dict:
    """The file for these features within the budget. The least visible features go first: protected kinds (reservations
    and forests) are kept whatever their size; then the highest minimum zoom, then the smallest size. Returns the bytes,
    the kept features, the number dropped, the gzip and raw sizes, and whether the file is over budget."""
    order = sorted(feats, key=_visibility)
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
        closed = f["k"] not in ("river", "route")
        per_key: dict = {}
        # each part (a ring or a path) goes to the boxes it touches, so a joined river costs no more than its reaches
        for part in f["g"]:
            pbox = _bbox([part])
            for key in keys_for(pbox):
                box = box_of(key)
                w, s, e, n = box
                if pbox[0] >= w and pbox[1] >= s and pbox[2] <= e and pbox[3] <= n:
                    pieces = [part]
                elif closed:
                    clipped = _clip_ring(part, box)
                    pieces = [clipped] if len(clipped) >= 3 else []
                else:
                    pieces = _clip_path(part, box)
                if pieces:
                    per_key.setdefault(key, []).extend(pieces)
        for key, parts in per_key.items():
            box = box_of(key)
            tidy = _tidy(parts, closed=closed)
            if not tidy:
                continue
            label = f["l"] if (f["l"] is not None and owns(f["l"], box)) else None
            # the piece's own size, which the budget ranks by; a feature with no size (a park with no acreage) keeps none
            size = None if f["size"] is None else (area_km2(tidy) if closed else length_km(tidy))
            out.setdefault(key, []).append(dict(f, g=tidy, l=label, size=size))
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
    already on the first-paint base map keeps that map's name and minimum zoom: a consolidated census name takes its
    first-paint name first (FIRST_PAINT_NAMES). A place with no census count carries its reason in its row (D112(h))."""
    items = []
    for r in rows:
        name = FIRST_PAINT_BY_TIGER.get(r["name"], r["name"])
        pop = pops.get(r["placefp"])
        known = name in basemap
        item = {"kind": "place", "name": expand_name(name), "lat": round(r["lat"], 5), "lon": round(r["lon"], 5),
                "population": pop, "type": PLACE_LSAD.get(r["lsad"], "place"),
                "min_zoom": basemap[name] if known else place_zoom(pop),
                "zoom_rule": ("basemap" if known else ("population" if pop is not None else "no population"))}
        if pop is None:
            item["reason"] = REASON_NO_CENSUS_COUNT
        items.append(item)
    items.sort(key=lambda p: (-(p["population"] if p["population"] is not None else -1), p["name"]))
    for i, p in enumerate(items):
        p["rank"] = i + 1 if p["population"] is not None else None
    return {"f": FORMAT_PLACES, "n": len(items), "population_unavailable": sum(1 for p in items if p["population"] is None),
            "places": items}


def build_peaks(ranked: list[dict], no_height: int) -> dict:
    return {"f": FORMAT_PEAKS, "n": len(ranked), "no_height": no_height,
            "rule": {"order": "height, highest first", "zoom_8_spacing_km": SPACING_KM[8],
                     "zoom_10_spacing_km": SPACING_KM[10], "rest_zoom": 12},
            "peaks": [{"kind": "peak", "name": expand_name(s["name"]), "lat": round(s["lat"], 5), "lon": round(s["lon"], 5),
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


def write_vector(store: Path, feats: dict[str, list[dict]], built: set[str]) -> dict:
    """Writes band A, every band B and C cell (empty cells too, so a missing file always means not built) and the band D
    shards of the built tiles: the tiles whose water and park inputs loaded (a tile whose request failed has no shard, so
    the browser draws band C's water there: it keeps drawing band C's lakes and rivers at zoom 13 and up, and the sheet's
    water line reads Data unavailable for that area). Returns the files (for the manifest) and the measures per file."""
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
    by_tile = _split(feats["D"], lambda bbox: tiles_for_bbox(bbox, built), tile_box)
    for tile in sorted(built):
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


def _base_document(store) -> dict:
    """The shared base index (hail/base/index.json) as a dict, read before anything is written (B6 P2-R7, as the terrain
    and landmark parts do). A missing file starts a new document with the shared format key "f". A file that is not
    JSON, or whose "f" is another value or missing, is refused: BasemapError names the file and the format found, and the
    file is kept as it is (never discarded), so the write stops before any file changes."""
    path = Path(store) / INDEX_FILE
    if not path.is_file():
        return {"f": FORMAT_INDEX}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise BasemapError(f"{INDEX_FILE} is not JSON, so the vector part is not written and the file is kept") from None
    found = doc.get("f") if isinstance(doc, dict) else None
    if found != FORMAT_INDEX:
        shown = repr(found) if found is not None else "no format key"
        raise BasemapError(f"{INDEX_FILE} is not a {FORMAT_INDEX} document (its format key: {shown}), so the vector part "
                           "is not written and the file is kept")
    return doc


def write_index(store: Path, block: dict, files: dict, *, mirror_keys=("state", "as_of", "counts", "sources", "bytes")) -> None:
    """hail/base/index.json (this product's block under its key; the other base products keep theirs) and the mirror in
    hail/index.json's base block. The manifest is then rewritten for this product's prefixes (S._merge_manifest). The
    shared document is read first (_base_document): another format stops the write and the file is kept."""
    base_path = store / INDEX_FILE
    doc = _base_document(store)
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


def _kinds_text(kinds: list[str]) -> str:
    """The failed kinds in words, every one of them named (there are seven at most): "a, b and c". No count and no cap."""
    names = [PART_WORDS[k][0].lower() for k in kinds]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _box_words(box) -> str:
    """A box in words, west and east, then south and north: "from 114.1 W to 113.9 W and from 46.8 N to 47 N"."""
    w, s, e, n = box

    def degrees(value: float, plus: str, minus: str) -> str:
        return f"{abs(value):g} {plus if value >= 0 else minus}"
    return (f"from {degrees(w, 'E', 'W')} to {degrees(e, 'E', 'W')} and "
            f"from {degrees(s, 'N', 'S')} to {degrees(n, 'N', 'S')}")


def mark_unavailable(store, reason: str) -> dict:
    """The D20 block for a store whose vector part cannot be built: state unavailable, the sentence in problem and the
    technical reason in detail. This product's files are removed; the rest of the store is kept. A shared index of
    another format stops it before any file changes (_base_document)."""
    store = Path(store)
    _base_document(store)
    index = _read_json(store / "hail" / "index.json", "the store index is missing")
    block = {"format": FORMAT_INDEX, "state": "unavailable", "as_of": index.get("as_of"), "built_at": _utc_now(),
             "problem": WORDS["unavailable"], "detail": reason}
    _remove_mine(store)
    write_index(store, block, {})
    return block


# ---------------------------------------------------------------- the build

ALL_KINDS = ("reservation", "forest", "park", "water", "route", "place", "peak")


def default_cache(store) -> Path:
    """The download cache when --cache is not given: a folder named basemap2-cache beside the store folder."""
    return Path(store).parent / "basemap2-cache"


def _failed_kinds(block: dict) -> set[str]:
    """The kinds a block names as failed. A failure row that names no kind names none (it is not counted as one)."""
    return {str(row["kind"]) for row in (block.get("failures") or []) if isinstance(row, dict) and row.get("kind")}


def _envelope_tree(env: tuple[float, float, float, float], key: str, depth: int = 0) -> list[tuple]:
    """A query's envelope and each envelope it can be split into (its quarters, and their quarters, up to SPLIT_DEPTH
    levels), with the keys nhd_cell_features gives them."""
    out = [(env, key)]
    if depth < SPLIT_DEPTH:
        w, s, e, n = env
        mx, my = (w + e) / 2.0, (s + n) / 2.0
        quarters = ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n))
        for i, quarter in enumerate(quarters):
            out.extend(_envelope_tree(quarter, f"{key}q{depth + 1}{i}", depth + 1))
    return out


def cache_plan(envelopes: list[tuple], points: list[tuple[float, float]]) -> tuple[set[str], set[str]]:
    """The cache names of the statewide plan (D112(m)): the exact files (the TIGER 2026 and 2020 census files, the GNIS
    file, and the 3DEP batches of these points) and the prefixes of the queries (the small-scale water, the forests, the
    parks, and each large-scale envelope with its quarters). A page is kept under its query's prefix, at any offset."""
    exact = {TIGER_AIANNH, TIGER_PRISEC, TIGER_PLACE, CENSUS_PL, GNIS_FILE}
    prefixes = {f"nhd_small_lines/mt_{request_key(nhd_params('small_lines', MT_BOX))}_",
                f"nhd_small_areas/mt_{request_key(nhd_params('small_areas', MT_BOX))}_",
                f"edw/mt_{request_key(forest_params())}_",
                f"padus/mt_{request_key(padus_params())}_"}
    for env, key in envelopes:
        for tenv, tkey in _envelope_tree(env, key):
            for source in ("large_lines", "large_areas"):
                prefixes.add(f"nhd_{source}/{tkey}_{request_key(nhd_params(source, tenv))}_")
    for start in range(0, len(points), SAMPLE_BATCH):
        exact.add(_sample_name(start, points[start:start + SAMPLE_BATCH]))
    return exact, prefixes


def prune_cache(cache: Path, exact: set[str], prefixes: set[str]) -> dict:
    """Deletes the files of the source folders that the plan does not name: the older cycles (D112(m)). A file outside the
    source folders is not touched. Returns the number of files and the bytes removed."""
    cache = Path(cache)
    files = nbytes = 0
    for folder in CACHE_FOLDERS:
        root = cache / folder
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(cache).as_posix()
            if rel in exact or any(rel.startswith(prefix) for prefix in prefixes):
                continue
            nbytes += path.stat().st_size
            path.unlink()
            files += 1
    return {"files": files, "bytes": nbytes}


def build(store, cache, *, offline: bool = False, refresh: bool = False, box: tuple | None = None,
          deadline_at: float | None = None) -> dict:
    """Builds the vector base part into the store. A source that fails is named in the index and its kinds are left
    out (D16). A kind whose source loads but holds nothing usable after its filters is a failure too, so an empty layer
    is never shown as loaded. Only when every kind fails is the block marked unavailable (D20), and so is a store that
    lists no tiles. A shared index of another format is refused before any file changes (_base_document). After a
    statewide online build in which no request failed, the cache keeps the current cycle only (cache_plan, prune_cache)."""
    t0 = time.monotonic()
    store = Path(store)
    _base_document(store)
    index = _read_json(store / "hail" / "index.json", "the store index is missing")
    tiles = list(index.get("tiles") or [])
    if not tiles:
        return mark_unavailable(store, "the store index lists no tiles")
    as_of = index.get("as_of")
    ctx = _Ctx(Path(cache), offline=offline, refresh=refresh, deadline_at=deadline_at)
    cover = coverage_tiles(tiles, box)
    inputs: dict = {}
    failed: dict[str, list[str]] = {k: [] for k in ALL_KINDS}
    notes: list[str] = []                       # sentences for missing inputs that are not a failed source
    unusable = {"rivers_no_drainage_area": 0, "parks_no_acreage": 0, "collapsed": 0}
    moves: dict = {"moved": {}, "collapsed": 0}

    def attempt(kind: str, fn):
        try:
            return fn()
        except ImportError as exc:
            # pyshp is the only import a reader makes: without it the kinds that read shapefiles are named as failed
            if getattr(exc, "name", None) not in ("shapefile", None):
                raise
            failed[kind].append(REASON_NO_SHAPEFILE)
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

    # reservations (TIGER 2026 AIANNH: the full-resolution file, never the 1:500,000 cartographic file)
    data = attempt("reservation", lambda: tiger("tiger_aiannh", AIANNH_URL, TIGER_AIANNH, (".shp", ".shx", ".dbf")))
    if data is not None:
        res = attempt("reservation", lambda: read_reservations(data))
        if res is not None:
            inputs["reservations"] = res
            if not res:
                failed["reservation"].append("the reservation file gave no Montana reservations")
    # roads (TIGER 2026 primary and secondary roads)
    data = attempt("route", lambda: tiger("tiger_prisec", PRISEC_URL, TIGER_PRISEC, (".shp", ".shx", ".dbf")))
    if data is not None:
        rt = attempt("route", lambda: read_routes(data))
        if rt is not None:
            inputs["routes"] = rt
            if not rt:
                failed["route"].append("the road file gave no interstate, US or state routes")
    # places (TIGER 2026 PLACE) and their 2020 counts
    data = attempt("place", lambda: tiger("tiger_place", PLACE_URL, TIGER_PLACE, (".shp", ".shx", ".dbf")))
    pl_data, _, pl_reason = fetch(ctx, "census_pl2020", PL2020_URL, CENSUS_PL,
                                  _check_zip("mtgeo2020.pl", "mt000012020.pl"))
    pops: dict[str, int] = {}
    pops_failed = False
    if pl_data is not None:
        got = attempt("place", lambda: read_population(pl_data))
        pops_failed = got is None
        pops = got or {}
    else:
        # the population file is missing: the place kind is named, and no place has a population (D16)
        pops_failed = True
        note = pl_reason or REASON_NO_ANSWER
        failed["place"].append(f"the 2020 population file did not load: {note}")
        ctx.failures.append({"kind": "place", "source": "census_pl2020", "reason": note})
    if data is not None:
        rows = attempt("place", lambda: read_places(data))
        if rows is not None:
            inputs["place_rows"] = rows
            inputs["pops"] = pops
            if not rows:
                failed["place"].append("the place file gave no named places")
            elif pops_failed:
                notes.append(WORDS["population_unknown"].format(count=len(rows)))
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
                forests.append({"name": at["FORESTNAME"], "parts": parts, "oid": _text(at.get("OBJECTID"))})
        inputs["forests"] = forests
        if not forests:
            failed["forest"].append("the forest query gave none of the seven national forests")
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
            if not parts or code not in PARK_RULES:
                continue
            acres = _num(at.get("GIS_ACRES"))
            if acres is None:
                unusable["parks_no_acreage"] += 1     # the outline stays, with no size (null), and is counted
            # a park with no name keeps its outline: park_name gives "" for a blank or placeholder name
            parks.append({"code": code, "name": park_name(code, at), "parts": parts, "oid": _text(at.get("OBJECTID")),
                          "size": None if acres is None else acres * 0.00404686})
        inputs["parks"] = parks
        if not parks:
            failed["park"].append("the park query gave no parks with a known designation")
    elif not failed["park"]:
        failed["park"].append("the park query returned no features")
    # water, small scale: NHD lines and areas over Montana (bands A to C), page by page; a page that fails is skipped
    lines, line_probs = nhd_features(ctx, "small_lines", MT_BOX, "mt", attempts=SMALL_TRIES, read_cap=SMALL_READ_S,
                                     skip_pages=SMALL_SKIP_PAGES)
    rivers_small = []
    for f in lines:
        at, parts = _attrs(f), service_parts(f.get("geometry"))
        name = str(at.get("GNIS_NAME") or "").strip()
        if not (parts and name):
            continue
        total = _num(at.get("TOTDASQKM"))
        if total is None:
            unusable["rivers_no_drainage_area"] += 1  # left out: a river with no drainage area has no band (never 0)
            continue
        rivers_small.append({"name": name, "total": total, "oid": _text(at.get("OBJECTID")),
                             "length": _num(at.get("LENGTHKM")) or length_km(parts), "parts": parts})
    areas, area_probs = nhd_features(ctx, "small_areas", MT_BOX, "mt", attempts=SMALL_TRIES, read_cap=SMALL_READ_S,
                                     skip_pages=SMALL_SKIP_PAGES)
    lakes_small = []
    for f in areas:
        at, parts = _attrs(f), service_parts(f.get("geometry"))
        name = str(at.get("GNIS_NAME") or "").strip()
        if parts and name:
            area = _num(at.get("AREASQKM"))
            lakes_small.append({"name": name, "parts": parts, "oid": _text(at.get("OBJECTID")),
                                "area": area if area is not None else area_km2(parts)})
    # water outside Montana is not drawn on the Montana map (a river that crosses the line is kept whole)
    inputs["rivers_small"] = keep_in_montana(rivers_small)
    inputs["lakes_small"] = keep_in_montana(lakes_small)
    bad_water: list[str] = list(line_probs) + list(area_probs)
    small_failed = bool(bad_water)
    if not small_failed and not inputs["rivers_small"]:
        failed["water"].append("the small-scale river layer gave no named rivers in Montana")
        small_failed = True
    if not small_failed and not inputs["lakes_small"]:
        failed["water"].append("the small-scale lake layer gave no named lakes in Montana")
        small_failed = True
    # water, large scale: NHD lines and areas per 1 degree cell that holds a covered tile (band D), or one request for the box
    lakes_large, rivers_large = [], []
    seen: set = set()
    if box is not None:
        envelopes = [(tuple(box), "box_" + "_".join(f"{v:g}" for v in box))]
    else:
        envelopes = []
        for lat0, lon0 in cells_for_box(1):
            env = cell_box(lat0, lon0, 1)
            if tiles_for_bbox(env, cover):
                envelopes.append((env, f"{lat0}_{lon0}"))
    unbuilt: set[str] = set()
    failed_cells: list[str] = []
    cell_reasons: dict[str, str] = {}
    for env_box, key in envelopes:
        env_problems: list[str] = []
        for source, layer_key in (("large_areas", "lakes"), ("large_lines", "rivers")):
            feats, probs = nhd_cell_features(ctx, source, env_box, key)
            env_problems.extend(probs)
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
                oid = _text(at.get("OBJECTID"))
                if layer_key == "lakes":
                    area = _num(at.get("AREASQKM"))
                    lakes_large.append({"name": name, "parts": parts, "oid": oid,
                                        "area": area if area is not None else area_km2(parts)})
                else:
                    rivers_large.append({"name": name, "parts": parts, "oid": oid,
                                         "length": _num(at.get("LENGTHKM")) or length_km(parts)})
        if env_problems:
            # a cell whose water did not load (or was stopped by the deadline) has no shard: its tiles are not built
            bad_water.extend(env_problems)
            unbuilt.update(tiles_for_bbox(env_box, cover))
            failed_cells.append(key)
            cell_reasons[key] = env_problems[0]
    inputs["lakes_large"] = keep_in_montana(lakes_large)
    inputs["rivers_large"] = keep_in_montana(rivers_large)
    # the bands whose water did not load: the small-scale layers feed A to C, the large-scale layers feed D
    water_bands = (["A", "B", "C"] if small_failed else []) + (["D"] if failed_cells else [])
    if bad_water:
        failed["water"].extend(bad_water[:50])
    # summits: GNIS names and the 3DEP height at each
    summits_src = attempt("peak", lambda: tiger("gnis", GNIS_URL, GNIS_FILE, ("DomesticNames_MT.txt",)))
    peaks_ranked, no_height = [], 0
    plan_points: list[tuple[float, float]] = []
    if summits_src is not None:
        summits = attempt("peak", lambda: read_summits(summits_src))
        if summits is None:
            summits = []                              # the failure is named already
        elif not summits:
            failed["peak"].append("the names file gave no summits")
        plan_points = [(s["lon"], s["lat"]) for s in summits]
        heights, probs = sample_elevations(ctx, plan_points)
        if probs:
            failed["peak"].extend(probs[:20])
        withh = []
        for s, h in zip(summits, heights):
            if h is None:
                no_height += 1
            else:
                s["elev_m"] = h
                withh.append(s)
        if summits and not withh and not probs:
            failed["peak"].append("the 3DEP answer gave no height for any summit")
        if no_height:
            notes.append(WORDS["peaks_unknown"].format(count=no_height))
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
    feats = build_features(inputs, moves)
    unusable["collapsed"] = moves["collapsed"]
    built = cover - unbuilt
    written = write_vector(store, feats, built)
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
    problems = list(with_failures)
    # partial: a failed kind, a missing input named in a note, or a test box (which builds band D for its own tiles only)
    state = "partial" if (problems or notes or box is not None) else "loaded"
    sentences: list[str] = []
    if problems == ["water"] and water_bands == ["D"]:
        # only the detailed water of band D failed: the sentence names the cells, and says what still loaded (D122(d))
        sentences.append(WORDS["band_d_water_partial"].format(failed=len(failed_cells), areas=len(envelopes)))
    elif len(problems) == 1:
        kind = problems[0]
        sentences.append(WORDS["part_unavailable"].format(Part=PART_WORDS[kind][0], one=PART_WORDS[kind][1]))
    elif problems:
        sentences.append(WORDS["partial_named"].format(names=_kinds_text(problems)))
    sentences.extend(notes)
    if box is not None:
        sentences.append(WORDS["coverage_box"].format(area=_box_words(box)))
    problem_text = " ".join(sentences) or None
    counts = {"bands": written["kinds"], "A_features": summary["A"]["features"],
              "tiles_in_coverage": len(cover), "tiles_built": len(built),
              "cells_B": len(cells_for_box(2)), "cells_C": len(cells_for_box(1)),
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
    # the cache (D112(m)): after a statewide online build with no failed request, the older cycles are deleted. An
    # offline build reads the cache and changes nothing in it; a test box is not a statewide cycle.
    cache_info = {"files": 0, "bytes": 0, "skipped": None}
    if offline or box is not None:
        cache_info["skipped"] = "offline build" if offline else "test box"
    elif any(row["failed"] for row in ctx.sources.values()):
        cache_info["skipped"] = "a request failed in this build"
    else:
        exact, prefixes = cache_plan(envelopes, plan_points)
        removed = prune_cache(ctx.cache, exact, prefixes)
        cache_info.update(files=removed["files"], bytes=removed["bytes"])
    small_note = "without lakes and rivers: the small-scale lake and river layers did not load"
    block = {
        "format": FORMAT_INDEX,
        "state": state,
        "as_of": as_of,
        "built_at": _utc_now(),
        "problem": None if state == "loaded" else problem_text,
        "detail": None if state == "loaded" else ("; ".join(f"{k}: {v[0]}" for k, v in with_failures.items())[:600] or None),
        # the coverage is counts and the cells that did not load, never a claim the counts contradict (D122(a))
        "coverage": {"bands_a_to_c": "every cell touching Montana" if not small_failed else small_note,
                     "tiles_listed": len(tiles), "tiles_in_coverage": len(cover), "tiles_built": len(built),
                     "tiles_unbuilt": len(cover - built), "band_d_areas": len(envelopes),
                     "band_d_failed_cells": failed_cells[:200], "band_d_failed_cell_count": len(failed_cells),
                     "band_d_cell_reasons": {k: cell_reasons[k] for k in failed_cells[:200]},
                     "band_d_reason_counts": dict(Counter(cell_reasons.values()))},
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
        "unusable": unusable,
        "moved": moves["moved"],
        "cache": cache_info,
        "water_bands_failed": water_bands,
        "failures": [{"kind": k, "reasons": v[:5]} for k, v in with_failures.items()] + ctx.failures[:20],
        "timing": {"seconds": round(time.monotonic() - t0, 1), "requests": ctx.requests,
                   "downloaded_bytes": ctx.downloaded},
    }
    write_index(store, block, files)
    return {"state": state, "problem": block["problem"], "seconds": block["timing"]["seconds"],
            "counts": counts, "bytes": block["bytes"], "budgets": budgets, "trimmed": block["trimmed"],
            "unusable": unusable, "moved": moves["moved"], "cache": cache_info, "water_bands_failed": water_bands,
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
    "Source: U.S. Census Bureau, TIGER/Line 2026 (reservations, roads and place names).",
    "Source: U.S. Census Bureau, 2020 Census, Public Law 94-171 counts (place populations).",
    "Source: USDA Forest Service, forest boundaries (national forests).",
    "Source: Protected Areas Database of the United States (PAD-US) 4.1, U.S. Geological Survey (parks).",
    "Source: U.S. Geological Survey, National Hydrography Dataset (lakes and rivers).",
    "Source: U.S. Geological Survey, Geographic Names Information System (summit names).",
    "3DEP data courtesy of the U.S. Geological Survey (summit heights).",
)


def _safe_json(path: Path):
    """The parsed JSON of a file, or None when the file is missing or is not JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def verify(store, cache: Path | None = None) -> dict:
    """Checks the vector block, its files and their budgets, the counts (recounted from the files), the named features the
    part must hold, the shared index's format and that no feature carries a key beyond the map's own. A check whose source
    failed in the build is not checked: it says why, and it is outside the pass count (D122(d)). ok is computed over the checks
    that ran, and the count of checks not checked is shown. cache is accepted for the same command shape as the other
    store parts; the check reads the store only."""
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed, detail: str = "", skipped: bool = False) -> None:
        if skipped:
            checks.append({"check": name, "state": "not checked", "pass": None, "skipped": True, "detail": detail})
        else:
            checks.append({"check": name, "state": "passed" if passed else "failed", "pass": bool(passed),
                           "skipped": False, "detail": detail})

    def finish(**extra) -> dict:
        ran = [c for c in checks if not c["skipped"]]
        return dict({"ok": all(c["pass"] for c in ran), "checks": checks,
                     "passed": sum(1 for c in ran if c["pass"]), "failed": sum(1 for c in ran if not c["pass"]),
                     "not_checked": len(checks) - len(ran)}, **extra)

    index = _read_json(store / "hail" / "index.json", "the store index is missing")
    holder = index.get(INDEX_KEY) if isinstance(index.get(INDEX_KEY), dict) else {}
    block = holder.get(PRODUCT)
    check("the vector block is in the store index", isinstance(block, dict))
    if not isinstance(block, dict):
        return finish()
    check("the state is loaded, partial or unavailable", block.get("state") in ("loaded", "partial", "unavailable"),
          str(block.get("state")))
    # the shared document: its format key, then this product's block (the store index carries only the mirror)
    shared = _safe_json(store / INDEX_FILE)
    shared_ok = isinstance(shared, dict) and shared.get("f") == FORMAT_INDEX
    check(f"hail/base/index.json is the shared format ({FORMAT_INDEX})", shared_ok,
          "" if shared_ok else "the file is missing, is not JSON, or has another format key")
    full = shared.get(PRODUCT) if isinstance(shared, dict) else None
    check("the vector index file holds the block the store index mirrors",
          isinstance(full, dict) and full.get("state") == block.get("state") and full.get("as_of") == block.get("as_of"))
    if not isinstance(full, dict):
        return finish()
    block = full
    if block.get("state") == "unavailable":
        return finish(note=block.get("problem"))
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
    shields: set = set()
    stray_keys = 0
    gz_by_band: dict[str, list[tuple[str, int]]] = {band: [] for band in BAND_ZOOMS}

    def read_band(rel: str, band: str) -> None:
        nonlocal stray_keys
        data = (store / rel).read_bytes()
        gz_by_band[band].append((rel, _gzlen(data)))
        for f in json.loads(data.decode("utf-8")).get("features", []):
            counted[band][f["k"]] += 1
            names[band].add(f["n"])
            if f["k"] == "route":
                shields.add(f.get("s"))
            stray_keys += len(set(f) - ALLOWED_KEYS)

    a_path = store / A_FILE
    check("band A is written", a_path.is_file())
    if a_path.is_file():
        read_band(A_FILE, "A")
        a_lines = [(f["k"], f["n"], f["z"]) for f in json.loads(a_path.read_text(encoding="utf-8")).get("features", [])
                   if f["k"] in ("river", "route")]
        check("band A holds one river or route feature per name and zoom", len(a_lines) == len(set(a_lines)),
              f"{len(a_lines) - len(set(a_lines))} repeated names")
    for band, prefix, size in (("B", B_PREFIX, CELL_DEG["B"]), ("C", C_PREFIX, CELL_DEG["C"])):
        expected = {f"{prefix}{cell_name(lat0, lon0)}.json" for lat0, lon0 in cells_for_box(size)}
        # the glob already yields paths under store (store/hail/...), so they are made relative to it, not joined to it again
        have = ({p.relative_to(store).as_posix() for p in (store / prefix).glob("*.json")}
                if (store / prefix).is_dir() else set())
        check(f"every band {band} cell has a file", expected <= have, f"{len(expected - have)} cells missing")
        for rel in sorted(have):
            read_band(rel, band)
    tiles_listed = set(index.get("tiles") or [])
    shards = sorted((store / W_PREFIX).glob("*.json")) if (store / W_PREFIX).is_dir() else []
    cov = block["coverage"]
    built_count = cov.get("tiles_built", cov["tiles_in_coverage"])
    unbuilt_count = cov.get("tiles_unbuilt")
    check("the band D tiles add up: built and not built make the tiles in coverage",
          isinstance(unbuilt_count, int) and built_count + unbuilt_count == cov["tiles_in_coverage"],
          f"{built_count} built and {unbuilt_count} not built, of {cov['tiles_in_coverage']} in coverage")
    check("every built tile has a band D shard", len(shards) == built_count,
          f"{len(shards)} shards, {built_count} tiles built of {cov['tiles_in_coverage']} in coverage")
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
    # The named-feature checks hold for a build whose sources all loaded. A source that failed in this build is named in
    # the index, so its check is not checked (and says why): a partial build passes verify and is shown as partial, while
    # a file mismatch, a count or a budget still fails (the workflow then marks the part unavailable, D20).
    failed_kinds = _failed_kinds(block)
    water_bands = set(block.get("water_bands_failed") or [])
    # The small-scale water layers feed bands A to C and the large-scale layers feed band D. Water that failed with no
    # band named is taken to cover A to C, so the river checks are not checked rather than failed.
    small_water_failed = "water" in failed_kinds and (not water_bands or bool(water_bands & {"A", "B", "C"}))
    reasons: dict[str, str] = {}
    for row in block.get("failures") or []:
        if isinstance(row, dict) and row.get("kind") and row.get("reasons"):
            reasons.setdefault(str(row["kind"]), str(row["reasons"][0]))

    def named(name: str, kinds: set, passed: bool, detail: str = "") -> None:
        missing = sorted(kinds & failed_kinds)
        if missing:
            why = reasons.get(missing[0], "")
            check(name, None, f"not checked: {', '.join(missing)} did not load in this build"
                  + (f" ({why})" if why else ""), skipped=True)
        else:
            check(name, passed, detail)

    named("band A holds the seven reservations", {"reservation"}, set(RESERVATION_NAMES) <= names["A"],
          f"{len(set(RESERVATION_NAMES) & names['A'])} of {RESERVATION_COUNT} named reservations")
    named("band A holds the seven national forests", {"forest"}, set(FOREST_NAMES) <= names["A"],
          f"{len(set(FOREST_NAMES) & names['A'])} of {FOREST_COUNT} named forests")
    named("the files hold route shields for interstates, US routes and state routes", {"route"},
          {"interstate", "us", "state"} <= shields, f"route classes {sorted(str(s) for s in shields)}")
    park_total = sum(counted[band]["park"] for band in BAND_ZOOMS)
    named("the files hold park outlines", {"park"}, park_total > 0, f"{park_total} park outlines")
    named("band A holds Glacier National Park", {"park"}, "Glacier National Park" in names["A"])
    everywhere = names["A"] | names["B"] | names["C"] | names["D"]
    for river in RIVER_CHECK:
        name = f"the river {river} is in the files"
        if small_water_failed:
            check(name, None, "not checked: the small-scale water layers did not load in this build", skipped=True)
        else:
            check(name, river in everywhere)
    places_doc = _read_json(store / PLACES_FILE, "places.json is missing") if (store / PLACES_FILE).is_file() else {}
    place_names = {p["name"] for p in places_doc.get("places", [])}
    for place in PLACE_CHECK:
        named(f"{place} is in places.json", {"place"}, place in place_names)
    peaks_doc = _read_json(store / PEAKS_FILE, "peaks.json is missing") if (store / PEAKS_FILE).is_file() else {"peaks": []}
    mc = [p for p in peaks_doc.get("peaks", []) if p["name"] == PEAK_CHECK["name"]]
    named(f"{PEAK_CHECK['name']} is in peaks.json within {PEAK_TOLERANCE_M:.0f} m of the published height", {"peak"},
          bool(mc) and abs(mc[0]["elev_m"] - PEAK_CHECK["metres"]) <= PEAK_TOLERANCE_M,
          f"{mc[0]['elev_m'] if mc else 'absent'} m, published {PEAK_CHECK['source']}")
    return finish(counts=block.get("counts"), budgets=block.get("budgets"))


def map_data_vector(block: dict | None) -> dict:
    """map.json["base"]["vector"]: the state, the as_of date, the file patterns, the zooms, the budgets, the credit lines
    and the words. A block that is absent or unavailable gives the unavailable state with its sentence (D20). failed_kinds
    names the kinds that did not load (a failure row that names no kind names none)."""
    if not isinstance(block, dict) or block.get("state") not in ("loaded", "partial"):
        return {"state": "unavailable", "problem": WORDS["unavailable"], "as_of": (block or {}).get("as_of")}
    cov = block.get("coverage") or {}
    return {"state": block["state"], "as_of": block.get("as_of"), "problem": block.get("problem"),
            "tiles": {"a": A_FILE, "b": B_PREFIX + "{cell}.json", "c": C_PREFIX + "{cell}.json",
                      "w": W_PREFIX + "{tile}.json", "peaks": PEAKS_FILE, "places": PLACES_FILE},
            "zooms": {k: list(v) for k, v in BAND_ZOOMS.items()}, "budgets": block.get("budgets"),
            # the kinds that did not load, and the band D tiles with no shard: a tile with no shard is not built, and the
            # browser draws band C's water there (the browser keeps drawing band C's lakes and rivers at zoom 13 and up,
            # and the sheet's water line reads WORDS["water_line_unavailable"] for that area)
            "failed_kinds": sorted(_failed_kinds(block)),
            "coverage": {"tiles_built": cov.get("tiles_built"), "tiles_unbuilt": cov.get("tiles_unbuilt"),
                         "band_d_areas": cov.get("band_d_areas"),
                         "band_d_failed_cells": list(cov.get("band_d_failed_cells") or []),
                         "band_d_cell_reasons": dict(cov.get("band_d_cell_reasons") or {})},
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
    b.add_argument("--cache", default=None,
                   help="the download cache folder (default: a folder named basemap2-cache beside the store)")
    b.add_argument("--offline", action="store_true", help="make no request; use the cache only")
    b.add_argument("--refresh", action="store_true", help="re-read every cached response")
    b.add_argument("--box", default=None,
                   help="W,S,E,N: band D shards and fetches only in this box (a test run); write it as --box=W,S,E,N")
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
        store = Path(args.store)
        cache = Path(args.cache) if args.cache else default_cache(store)
        try:
            result = build(store, cache, offline=args.offline, refresh=args.refresh, box=box, deadline_at=deadline_at)
        except BasemapError as exc:
            # a build that cannot run is unavailable (D20), with its reason, not a traceback. A shared index of another
            # format is refused before any file changes: the reason is printed and the command exits 1 (P2-R7)
            try:
                result = mark_unavailable(store, str(exc))
            except BasemapError as again:
                print(f"error: the vector base map was not written: {again}", file=sys.stderr)
                return 1
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0
    if args.cmd == "verify":
        result = verify(Path(args.store), Path(args.cache) if args.cache else None)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0 if result["ok"] else 1
    try:
        block = mark_unavailable(Path(args.store), args.reason)
    except BasemapError as exc:
        print(f"error: the vector base map was not marked unavailable: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(block, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
