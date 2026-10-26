"""Public weather sources for the website: NWS alerts, forecasts and station readings, SPC storm
reports, NOAA radar.

Parsing functions take already-downloaded JSON or text, so tests run offline. `Fetcher` does the
network calls and records what happened to each request; nothing here invents a value when a
source fails.
"""
from __future__ import annotations

import csv
import io
import math
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

UTC = timezone.utc
NWS = "https://api.weather.gov"
SPC = "https://www.spc.noaa.gov/climo/reports/"
USER_AGENT = "MontanaHailWatch website (https://github.com/carson14dy/RoofingApp)"

MT_BOX = (44.35, 49.01, -116.06, -104.03)   # lat_min, lat_max, lon_min, lon_max
MARGIN = 0.75                               # degrees around Montana for storm reports and radar

KMH_TO_MPH = 0.621371
MS_TO_MPH = 2.236936
KT_TO_MPH = 1.150779
M_TO_FT = 3.280840

# Station readings (DECISIONS D29, built to the rules of D23 and D25).
OBS_STATIONS = 3        # nearest stations read for each town
FRESH_MINUTES = 75      # one hourly report cycle plus the ingest delay; older readings show as stale
# MADIS quality-control flags (codes.nws.noaa.gov/MADIS/QualityControlDescriptors), in plain words.
QC_WORDS = {"V": "verified", "S": "screened", "C": "basic check only", "Z": "not checked yet",
            "Q": "questioned", "G": "checked by hand", "T": "partly checked"}
QC_REJECTED = {"X": "failed quality control", "B": "marked bad on review"}

# Flag thresholds. These are placeholders until the company sets its own limits (DECISIONS D16).
LIMITS = {"wind_mph": 20, "gust_mph": 25, "pop_pct": 30, "cold_f": 40, "hot_f": 95}

# The county file's own use constraint (TIGER/Line 2026, tl_2026_us_county.shp.iso.xml), quoted verbatim: the
# acknowledgement the About page gives (B5 source 4; joins.py docstring).
CENSUS_TERMS = ("The TIGER/Line shapefile products are not copyrighted; however, TIGER/Line and Census TIGER are registered "
                "trademarks of the U.S. Census Bureau. These products are free to use in a product or publication, however "
                "acknowledgement must be given to the U.S. Census Bureau as the source.")

# What each feed sends and how this site treats it. Change the parser, this table and
# tests/test_site.py together (AGENTS.md rule 7). Shown on the About page.
CONTRACTS = {
    "alerts": {
        "name": "NWS alerts",
        "request": "api.weather.gov/alerts/active?area=MT, and ?point=lat,lon for each town",
        "units": "Times in ISO 8601 with an offset, shown in Montana time. Area as an outline, or none.",
        "timing": "Fetched at every build (a schedule set to every 10 minutes; each page says when it was built).",
        "missing": "No readable list means the check failed: the last verified list stays up with its time. "
                   "An alert without an outline is listed with a note. Test messages and updates that a later message has changed are left out.",
    },
    "points": {
        "name": "NWS forecast grid lookup",
        "request": "api.weather.gov/points/lat,lon",
        "units": "Links to the forecasts for the 2.5 km grid square, the NWS office and time zone.",
        "timing": "Every build; if a lookup does not work, the last good lookup is reused.",
        "missing": "No links means that town's forecast is unavailable.",
    },
    "hourly": {
        "name": "NWS hourly forecast",
        "request": "the point's forecastHourly link",
        "units": "°F (°C converted). Wind \"10 mph\" or \"10 to 15 mph\" (the higher number used). Chance of rain or snow in %.",
        "timing": "NWS updates it about hourly; the issue time is shown on the town page.",
        "missing": "A missing value shows as a dash. It never raises a flag and never passes one.",
    },
    "gusts": {
        "name": "NWS gust forecast",
        "request": "the point's forecastGridData link, windGust series",
        "units": "km/h or m/s, converted to whole mph. Each value covers a time span, spread to the hours in it.",
        "timing": "Updated with the grid forecast, several times a day.",
        "missing": "Hours without a value stay missing. Any other unit is an error, never a guess.",
    },
    "daily": {
        "name": "NWS 7-day forecast",
        "request": "the point's forecast link",
        "units": "12-hour periods paired into days: high, low, sky, wind and the higher chance of rain or snow.",
        "timing": "NWS updates it several times a day.",
        "missing": "A missing high or low shows as a dash.",
    },
    "stations": {
        "name": "NWS observation stations",
        "request": "the point's observationStations link: the stations NWS lists for the town's 2.5 km grid square",
        "units": "Station id, name, position and elevation in metres (shown in feet). The distance from this "
                 "spot is worked out here, in miles; the nearest three are read.",
        "timing": "Every build; if a list does not load, the last good list is reused.",
        "missing": "Never filtered by state: the nearest stations can be in Wyoming, Idaho or the Dakotas. "
                   "No list means no readings for that town, and the town page says so.",
    },
    "observations": {
        "name": "NWS station readings",
        "request": "api.weather.gov/stations/{id}/observations/latest, for the nearest three stations of each town",
        "units": "Temperature in °C, wind and gusts in km/h (m/s and knots converted), direction in degrees; "
                 "shown in °F, whole mph and compass points. Each value carries its MADIS quality flag.",
        "timing": f"Airport stations report about once an hour, near :55; road and mountain stations hourly or "
                  f"less. A reading older than {FRESH_MINUTES} minutes is shown as stale, with its age, never hidden.",
        "missing": "A missing gust beside a measured wind is \"no gust reported\", not a broken sensor. A value "
                   "flagged X (failed quality control) or B (marked bad) is withheld and kept in the record; other "
                   "flags are shown beside the value. Any other unit is an error, never a guess.",
    },
    "reports": {
        "name": "SPC storm reports",
        "request": "spc.noaa.gov/climo/reports/YYMMDD_rpts_filtered_hail.csv and _wind.csv",
        "units": "Hail size in hundredths of an inch (175 = 1.75 in). Wind in mph. Times HHMM UTC; "
                 "a reporting day runs 12:00 to 11:59 UTC (6 am to 5:59 am MDT).",
        "timing": "Preliminary; today's files appear once there are reports. Three days are shown.",
        "missing": "\"UNK\" wind stays unknown. A file that does not pass its check is listed as a problem; no report is not \"no hail\".",
    },
    "radar": {
        "name": "NOAA radar estimate (MRMS)",
        "request": "noaa-mrms-pds.s3.amazonaws.com, CONUS/PrecipRate_00.00, one GRIB2 file every 2 minutes",
        "units": "Precipitation rate in mm/h as liquid water, shown in in/h. A 0.01° latitude-longitude grid; "
                 "the map uses one frame every 10 minutes for the past hour.",
        "timing": "NOAA publishes a new grid every 2 minutes; a newest frame older than 30 minutes is reported as stale.",
        "missing": "Negative values mean no radar coverage: those areas are hatched, never drawn as a zero reading. "
                   "If the files don't load, the map says so and shows no radar.",
    },
    "forecast_model": {
        "name": "NOAA HRRR model forecast",
        "request": "noaa-hrrr-bdp-pds.s3.amazonaws.com, wrfsfcf and wrfsubhf GRIB2 files; single fields fetched "
                   "by byte range from each file's .idx",
        "units": "Precipitation rate (kg m-2 s-1, shown in in/h), 2 m temperature (K, shown in °F) and surface "
                 "gusts (m/s, shown in mph) on a 3 km Lambert grid.",
        "timing": "A new run every hour; the map uses the newest run whose files are complete: 15-minute steps "
                  "for the next hour and hourly steps to 12 hours.",
        "missing": "A model forecast, labelled as one. If the run can't be read, the timeline stops at now and "
                   "the map says why.",
    },
    "storm_levels": {
        "name": "NOAA radar echo tops (MRMS, 11 heights)",
        "request": "noaa-mrms-pds.s3.amazonaws.com, CONUS/MergedReflectivityQC at 0.50, 1.00, 2.00, 3.00, 4.00, "
                   "5.00, 6.00, 8.00, 10.00, 12.00 and 15.00 km: one GRIB2 file per height every 2 minutes, listed for "
                   "the last hour; the newest time with all 11 heights within 10 seconds is used, and each town's grid "
                   "cell is read",
        "units": "Reflectivity in dBZ, at heights above mean sea level from 500 to 15,000 m. The echo top is the "
                 "highest sampled height above ground with 35 dBZ or more, among heights that had radar data, in "
                 "metres above sea level; 'at least' when heights above it had no radar value. Ground height is the "
                 "NWS forecast grid point's elevation in metres, not a surveyed terrain height.",
        "timing": "A new set every 2 minutes. A set older than 30 minutes is reported as stale, the same limit as "
                  "the radar frames.",
        "missing": "-99 and -999 mean no radar value: -99 is missing and -999 is outside radar coverage (NOAA's MRMS GRIB2 "
                   "user table, versions 12.0 to 12.2). They are never a value, never 0. "
                   "Heights below the town's ground height are counted and not used. A town whose NWS grid height "
                   "didn't load gets 'Echo top not available', never a value. No echo at 35 dBZ does not rule out hail. "
                   "A radar estimate, not observed hail or damage.",
    },
    "satellite": {
        "name": "NOAA GOES satellite picture (band 13, observation)",
        "request": "noaa-goes19.s3.amazonaws.com (GOES-East; GOES-West noaa-goes18 if East is unavailable or has no scan in "
                   "the last hour), ABI-L2-CMIPC band 13: one NetCDF file per 5-minute CONUS scan; the newest scan "
                   "of the current or previous UTC hour",
        "units": "Infrared brightness temperature in kelvin at 2 km (nadir), drawn as one picture on the map's image box. "
                 "An observation: not a height, not a hail signal. An uncorrected cloud top is drawn away from the "
                 "satellite (north-west for GOES-East, north-east for GOES-West), about 3 to 4 km for a 2 km top and "
                 "20 to 33 km for a 12 to 15 km top",
        "timing": "A new scan every 5 minutes, on the bucket about 30 s after the scan ends. A newest scan older than "
                  "20 minutes is reported as stale; none within 60 minutes: no picture",
        "missing": "Fill values, raw values outside the file's valid range, quality flags other than 0 and cells outside "
                   "the satellite's grid are hatched as no satellite data, never drawn as cloud-free sky. If the file doesn't "
                   "load, the map says so and shows no satellite picture. This is not an all-clear.",
    },
    # --storm-layers builds only (build.py STORM_CONTRACTS): the live hail swath layers (B4)
    "hail_swath": {
        "name": "NOAA MRMS MESH hail swath, last hour and last 24 hours (radar estimates)",
        "request": "noaa-mrms-pds.s3.amazonaws.com, CONUS/MESH_Max_60min_00.50 (GRIB2 parameter 30, a file every 2 minutes) and CONUS/MESH_Max_1440min_00.50 (parameter 34, a file every 30 minutes). Each build lists today's folder (yesterday's when today's is empty, just after 00:00 UTC), takes the newest file of each product and downloads it once (a gzipped GRIB2 file). The grid is regular latitude and longitude, 7,000 by 3,500 cells of 0.01 degree, from 54.995 degrees north, 230.005 degrees east (stored 0 to 360) to 20.005 degrees north, 299.995 degrees east.",
        "units": "Millimetres (NOAA's GRIB2 user table, UserTable_MRMS_v12.2: MESH (maximum estimated size of hail) and its maxima), stored in tenths of a millimetre. Sizes are shown to the hundredth of an inch, rounded down, with the millimetre value exact (513 tenths: 2.01 in, 51.3 mm). Size classes start at 0.25 in (64 tenths), 0.75 in (191), 1.00 in (254), 1.50 in (381), 2.00 in (508) and 2.75 in (699). A radar estimate of the largest hail over each 0.01 degree cell, about 0.7 miles north to south and 0.5 miles east to west, in the last hour or the last 24 hours.",
        "timing": "The hour file is new every 2 minutes: fresh within 20 minutes of its valid time, stale to 60 minutes, then unavailable. The 24-hour file is new every 30 minutes: fresh within 60 minutes, stale to 120 minutes, then unavailable. The valid time is the header's date and time in UTC and must equal the file name's time. The valid time is the end of the window. The window comes from the parameter number (30 is 60 minutes, 34 is 1,440 minutes) and must match the folder. A stale picture is drawn and says so.",
        "missing": "-1 is missing and -3 is no radar coverage in NOAA's table; neither is stored as a value or as 0. An uncoloured cell means no radar hail estimate of 0.25 in or more in the last hour (hour layer) or the last 24 hours (24-hour layer), or no value; NOAA's data does not tell the two apart. Cells under 0.25 in (64 tenths) are not drawn and not written to the live files. A cell with no radar coverage is hatched, and its tile's live file lists it as no radar coverage. A file that is missing, unreadable, or does not match its time or window, and a request that does not work, make the layer unavailable with its reason and no picture. This is not an all-clear. An estimate, not observed hail and not an inspection.",
    },
    "basemap": {
        "name": "Map outlines and names",
        "request": "Natural Earth 10m (public domain) and US Census county lines (us-atlas 3.0.1), built into "
                   "static/map/basemap.json by tools/build_basemap.py",
        "units": "Longitude and latitude, rounded to 4 decimals and simplified for statewide viewing.",
        "timing": "Built by hand when the map changes; served by this site.",
        "missing": "Without the outlines the map still shows the weather layers and towns.",
    },
    "imagery": {
        "name": "USGS National Map imagery (ImageryTopo), base map",
        "request": "basemap.nationalmap.gov, USGSImageryTopo tiles, fetched by the viewer's browser only after they "
                   "switch the base map to Imagery, or open a link that starts on Imagery",
        "units": "Aerial photographs with roads, rivers, boundaries and place names, and at small scales a global "
                 "image; not weather and not evidence",
        "timing": "USGS's service says its data were refreshed in April 2026; its main source is leaf-on NAIP "
                  "imagery. This site shows no flight dates; the tiles are shown to zoom 16.",
        "missing": "A tile that doesn't load leaves a plain near-white background, with the Montana outline, state "
                   "lines and town bubbles, and the credit row says that imagery didn't load until a tile loads. The "
                   "base map's roads, lakes, rivers, counties and names stay hidden while Imagery is on. Outside the "
                   "United States, tiles above zoom 8 are blank or missing in the places checked.",
    },
    # --hail-history builds only (build.py HAIL_CONTRACTS); the store's format and words are in website/hail.py
    "hail_history": {
        "name": "NOAA MRMS MESH, five-year hail history (radar estimates)",
        "request": "NOAA Open Data on AWS (noaa-mrms-pds), MESH_Max_1440min_00.50, the 12:00 UTC file of each SPC day "
                   "(the file stamped the day after). A daily job turns the trailing 1,826 SPC days into one store on "
                   "GitHub Releases, named after the branch whose job built it (main's is hail-store-main.tar.gz), and each "
                   "build copies its own branch's store to this site, or main's when the branch has none. Where the NOAA copy and Iowa "
                   "State's archive copy of a file differ in size, the day is rebuilt as the maximum of its two-minute "
                   "frames. Where Iowa State's copy does not answer, the NOAA copy is used alone and the store's index "
                   "counts those days as skipped.",
        "units": "Millimetres (NOAA's GRIB2 user table, UserTable_MRMS_v12.2), stored in tenths of a millimetre. "
                 "Sizes are shown to the hundredth of an inch, rounded down, with the millimetre value exact "
                 "(513 tenths: 2.01 in, 51.3 mm). Values under 0.25 in (6.35 mm) are not stored; values of 4.00 in and "
                 "up carry a note. A radar estimate of the largest hail over this cell, about 0.7 miles north to south "
                 "and 0.5 miles east to west, during the day.",
        "timing": "A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to 6 am Mountain daylight time, 5 am to "
                  "5 am in winter (the SPC reporting day). The day is held by the file stamped the day after at "
                  "12:00 UTC, posted about 12:08 UTC. The newest day is added by a job that starts at 12:43 UTC and "
                  "shows here on the next rebuild. Each page shows the store's as-of date. A branch build "
                  "waits for its branch's latest store job before it reads the store (main does not wait). A store whose "
                  "last day is more than three days old is a failed source: the pages keep it with the stale line, and a "
                  "branch preview is marked as failed.",
        "missing": "-1 (missing) and -3 (no radar coverage) are never stored. A cell with no stored value on a day is no radar "
                   "estimate, and it never means that hail did not fall. A day with no file, or a file that does not pass "
                   "its check, is listed on the page and not counted, and it stays missing. An estimate is not a measurement "
                   "at the ground and not an inspection.",
    },
    # --hail-addresses builds only (build.py B3_ROWS and ROAD_ROWS): the address points, the road source built and the
    # building outlines of the B3 layers. The words are in website/addresses.py, streets.py and buildings.py (D8, D13,
    # D16, D17, D25, D29, D34); the road row shown is the source the store built (msl_roads, or census_roads when the
    # store is built with the Census fallback, D25).
    "msl_addresses": {
        "name": "Montana State Library address points (Structures and Addresses Framework)",
        "request": "The Montana State Library's address file, StructuresFramework_shp.zip (65.8 MB), from the Library's "
                   "download server. Each daily update reads the position of every address point and these parts of its "
                   "address: number, street, unit, city, zip, county and placement. No other field is read. The address "
                   "dots and the search come from this file.",
        "units": "Positions are longitude and latitude, converted from the file's Montana State Plane grid (metres) and "
                 "checked against three recorded points within 2 metres. Address lines follow the file's street words in "
                 "their standard order, with the unit title-cased. Each point carries the file's placement, which says how "
                 "the point was placed: on the building, at the property entrance, along the road by its number, at the "
                 "parcel, at the site, or by a method the file does not state. Only a point placed on its building joins a "
                 "building outline; a point placed anywhere other than on the building keeps its own dot and says how it "
                 "was placed.",
        "timing": "The Library exports the file monthly, around the end of the month. Each daily update checks the file's "
                  "size and last-changed date, reads the file again when either changes, and reads it once in each calendar "
                  "month. The file's date and export date are on the About page, with the file's name.",
        "missing": "A point with no street name is left out, a point with no city after the file's fallbacks is counted, "
                   "and exact duplicates are merged; each count is kept with the data. A missing or changed file, or a "
                   "terms sentence that is not the one quoted here, marks the list unavailable, and the map says so: an "
                   "unavailable list is never shown as no addresses. The file's access terms read: \"None. All data "
                   "contained in the Framework are publicly available and non-sensitive.\" Its terms say the Library makes "
                   "the data available as a convenience to the public, \"and for no other purpose.\" Owner names and "
                   "parcel identifiers are never read, stored or shown. The list is of addresses, not of buildings, and its "
                   "completeness varies from county to county.",
    },
    "msl_roads": {
        "name": "Montana State Library Transportation Framework, roads (the default street source)",
        "request": "The Montana State Library's Transportation Framework zip (RoadCenterLine, 258,208 segments) from the "
                   "Library's download server. The daily update reads the street name parts, the road class, the county "
                   "and the surface, and no other field. Kept: the centre lines, the street names, each line's road class "
                   "as one letter, and counts by county. The surface is read and not kept. The road lines are built from "
                   "them and copied to this site.",
        "units": "Lines are longitude and latitude, to 5 decimal places, simplified to within 2 metres. Drawn as "
                 "primary and secondary roads from zoom 13, and as ramps, local streets, service drives, alleys, private "
                 "roads and vehicular trails from zoom 15. A record of class Other is drawn as a local street when it is a "
                 "public road; a trail, a ferry, a private drive or an airfield surface among them is left out, and each "
                 "count is kept with the data. Where roads share one line, the line is drawn once with each name, joined by "
                 "a slash. Abbreviations are spelled out (Highway, Road, Street). Placeholder names are drawn without a label "
                 "and are never found by search.",
        "timing": "The Library publishes the file with its own date, which is on the About page. The daily update "
                  "reads it again only when its size or its last-changed date changes.",
        "missing": "A road with no name is drawn without a label; almost every road in this file has a name. A missing "
                   "file or a failed check marks the streets unavailable, and the map says so: unavailable is not the same "
                   "as no streets. The file's metadata says the Library makes the data \"available as a convenience to the "
                   "public, and for no other purpose.\" Its disclaimer says the data are provided for informational purposes "
                   "only and are not suitable for legal, engineering, or surveying purposes.",
    },
    "census_roads": {
        "name": "U.S. Census Bureau TIGER/Line 2026 roads (the fallback street source)",
        "request": "www2.census.gov/geo/tiger/TIGER2026/ROADS/, the 56 Montana county files (tl_2026_30XXX_roads.zip, about "
                   "88.9 MB). They are read by the daily update only when the site is built with this source, and the update "
                   "reads the centre lines, the names, the class code (MTFCC), the route type (RTTYP) and the line ID "
                   "(LINEARID), and no other field. Kept: the centre lines, the names, each line's class as one letter, and "
                   "counts of lines left out by class code. The route type and the line ID are read and not kept.",
        "units": "Lines are longitude and latitude, to 5 decimal places, simplified to within 2 metres. Drawn: primary roads, "
                 "secondary roads, local streets, 4-wheel-drive roads, ramps, service drives, alleys and private roads. Left "
                 "out and counted: the Census's internal roads (class S1750), parking lot roads (class S1780), and any other "
                 "class not drawn (in the 2026 county files, S1710, S1720, S1820 and S1830). Each count is kept with the "
                 "data. Features that share one line are drawn once, with each name joined by a slash.",
        "timing": "The Census Bureau publishes the 2026 files; the daily update reads them when the site is built with this "
                  "source. The date of the data is on the About page.",
        "missing": "Most vehicular features in the rural counties carry no name in these files, so many roads are drawn "
                   "without a label, and an unnamed road is never found by search. Placeholder names are drawn without a "
                   "label. The Census Bureau's metadata says \"acknowledgement must be given to the U.S. Census Bureau as the "
                   "source.\" It also says \"TIGER/Line and Census TIGER are registered trademarks of the U.S. Census "
                   "Bureau.\" The files \"may not be suitable for high-precision measurement applications such as engineering "
                   "problems, property transfers, or other uses that might require highly accurate measurements of the earth's "
                   "surface.\" A failed file marks the streets unavailable; unavailable is not the same as no streets.",
    },
    "usa_structures": {
        "name": "USA Structures, Oak Ridge National Laboratory and FEMA (building outlines)",
        "request": "FEMA's public data server, the Montana file MT_Structures_20260913.zip (173,088,786 bytes), with 918,052 "
                   "outlines in longitude and latitude. Only the outline geometry is read: no attribute column is read, so no "
                   "other field of the file is ever read, stored or shown.",
        "units": "Each outline is drawn from its exact edge, in longitude and latitude to 5 decimal places, with no "
                 "simplification. Each outline has one dot at a point inside it. The address points that the Montana list "
                 "places on an outline, or within 15 metres of its edge, are listed on that dot. A point placed anywhere other "
                 "than on the building keeps its own dot and says how it was placed. Dots from zoom 15, fills and hairlines "
                 "from zoom 16, and a heavier outline from zoom 17.",
        "timing": "The file is dated 2026-09-13, and its outlines come from imagery dated 2008 to 2025. Each daily update "
                  "checks the file's size and last-changed date and reads the file again when either changes, and once in each "
                  "calendar month. The file's date is on the About page.",
        "missing": "A county with no outlines in the file shows none; that is not the same as no buildings. Outlines are not "
                   "surveys, and the file does not separate other kinds of building, so sheds and barns are outlines too. The "
                   "attribution is \"Oak Ridge National Laboratory and FEMA, USA Structures.\"",
    },
    # --hail-addresses builds only (build.py B3_ROWS): the county boundary file the store job reads for the counts by county
    # (buildings.py, D34). Its only use is the labels of those counts; its own metadata is quoted in the row.
    "census_counties": {
        "name": "U.S. Census Bureau county boundaries, 2025 cartographic file (1:500,000)",
        "request": "www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_500k.zip (11.8 MB, last changed 2026-04-23 on the "
                   "server). The store job reads it for the counts by county: from its attributes only the county code and name, "
                   "and from its geometry the rings that place each building outline in a county. The address records are counted "
                   "by the County field of the address file, not by this file.",
        "units": "Whole counts: the building outlines and the address records in each county, kept beside each other. No area, "
                 "length or distance is computed from the file, and none is shown.",
        "timing": "The job keeps the file in a cache keyed by name and month, so it is downloaded once in each calendar month, "
                  "or when the cache is empty. A failed download marks the counts by county unavailable in that store; the "
                  "outlines and the addresses are kept.",
        "missing": "Unavailable is not the same as zero: when the file cannot be read, the counts by county are unavailable and "
                   "the outline and address totals are kept. At this file's scale of 1:500,000, a point near a county line can "
                   "fall on either side, so each county count is a label, not a measurement. The Census Bureau's metadata says: "
                   "\"These products are free to use in a product or publication, however acknowledgement must be given to the "
                   "U.S. Census Bureau as the source.\" It also says: \"Cartographic boundary files should not be used for "
                   "geographic analysis including area or perimeter calculation. Files should not be used for geocoding addresses. "
                   "Files should not be used for determining precise geographic area relationships.\"",
    },
    # --hail-history builds only (build.py HAIL_CONTRACTS): the joined records behind the history's sheet and tables
    # (B2). Each row says what its records are for the cell; the words built from them are in website/joins.py.
    "lsr": {
        "name": "NWS local storm reports (Iowa State archive)",
        "superseded_by": "iem_lsr",     # B5: the About page lists iem_lsr (every type read); this row stays for the record
        "request": "mesonet.agron.iastate.edu/cgi-bin/request/gis/lsr.py for Montana, one CSV per calendar month the window "
                   "touches (the count moves with the window); the last two months are read again each daily run. Every "
                   "window report is kept in the events table, and the sheet and town tables show those within 5 miles "
                   "of a cell's centre.",
        "units": "Hail in inches as reported. Thunderstorm wind gusts and sustained wind as the archive's magnitude, shown "
                 "in mph: the archive does not state its wind unit, and the research checked it against NCEI's knots. "
                 "Qualifier E is estimated, M measured and U unknown, in Iowa State's words. Times are UTC, shown in Montana "
                 "time. Source is in sentence case; the remark is shown to its first 160 characters.",
        "timing": "Each report carries the time it was valid, in UTC. The files are monthly, and the newest month grows as "
                  "reports arrive, so its last two months are read again each day.",
        "missing": "A magnitude of 'None' is missing, not zero; it appears on many type codes, for example D, O, E, F, "
                   "C, T, W and Z. A report is what someone sent the NWS, not a complete record: no report is not the same "
                   "as no hail. Known gaps: the wind "
                   "unit is inferred; Iowa State does not document the basis of qualifiers on reports from before September "
                   "2024.",
    },
    "ncei_storm_events": {
        "name": "NOAA NCEI Storm Events, bulk details files (hail and thunderstorm wind)",
        "request": "ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/StormEvents_details-ftp_v1.0_d<year>_c<creation>.csv.gz "
                   "for the window's years; the creation date is read from NCEI's directory listing, and each file is cached "
                   "by its name. Joined as points: Hail, Thunderstorm Wind, Flood, Flash Flood, Heavy Rain, Tornado, Funnel "
                   "Cloud, Lightning and Debris Flow rows with coordinates within 5 miles of a cell's centre. Zone-coded rows "
                   "(CZ_TYPE Z) of any event type, such as High Wind, Winter Storm, Heavy Snow, Blizzard and Drought, have no "
                   "coordinates and are joined by the cell's forecast zone. Other county-coded types are not joined as points.",
        "units": "Hail in inches (MAGNITUDE). Thunderstorm wind in knots, shown in knots and in mph (1 knot is 1.15078 mph). "
                 "MAGNITUDE_TYPE: MG measured gust, EG estimated gust, MS measured sustained, ES estimated sustained. The "
                 "point types flood, flash flood, heavy rain, tornado, funnel cloud, lightning and debris flow carry no magnitude "
                 "in these files and show their type word only. FLOOD_CAUSE is shown as written (for example \"Heavy Rain / Snow "
                 "Melt\" or \"Ice Jam\"). Begin times are local (MST-7, the file's CZ_TIMEZONE on every Montana row), converted to "
                 "UTC and then to Montana time.",
        "timing": "Yearly files that NCEI updates monthly. The sheet shows the newest event the database holds, so the lag is "
                  "stated on each page.",
        "missing": "A zone-coded row has no coordinates and is shown with its zone, not as a point. A county-coded row "
                   "with no coordinates is not joined. A blank magnitude is missing, not zero. Known gaps: NCEI's database "
                   "runs behind the other sources and has no "
                   "events after its newest event date (shown on the sheet); NCEI cuts source names at 20 characters. "
                   "NCEI's documentation checked does not say whether its begin times use daylight time. In summer 2025, "
                   "some NCEI begin times ran an hour before the matching LSR reports; the cause is not established.",
    },
    "swdi_nx3hail": {
        "name": "NCEI SWDI NEXRAD hail signatures (radar detections)",
        "request": "ncei.noaa.gov/swdiws/csv/nx3hail/<start>:<end>?bbox=-116.05,44.36,-104.04,49.00, one request per month "
                   "(start inclusive, end exclusive). Exact duplicate rows are dropped, and the three footer lines (summary, "
                   "count and time) are not rows. Detections within 2 miles of a cell's centre are joined, grouped by SPC day.",
        "units": "MAXSIZE in inches, in steps of a quarter inch. NOAA defines PROB as \"the probability of hail in percent\"; "
                 "this filtered product keeps PROB 100 with a maximum size above zero. A signature is the radar algorithm's detection for a "
                 "storm cell, not hail on the ground.",
        "timing": "Each detection is dated to the second, in UTC. The archive's inventory lagged the data by a median of "
                  "0.75 day from 1 September to 14 October 2026, but by 19.5 days (June 2025) and 64.4 days (February "
                  "2026) in the inventory samples checked. Its last-update times do not state a time zone, so the lags are "
                  "good to about 0.2 day. The sheet shows the newest detection date in this build, the last day with a "
                  "detection, not the archive's last day.",
        "missing": "The filtered product drops most signatures, so a day with none is not the same as no hail. A missing or "
                   "zero MAXSIZE is not shown as a size. Known gaps: the archive's inventory is not complete. On 2025-06-15 "
                   "it holds no signature in this box after 03:29 UTC, although its inventory lists the day as complete. "
                   "SWDI states a general spatial accuracy of 1 degree by 1 km, from 1 km to 4 km at 230 km from a radar.",
    },
    "nws_warnings_polygons": {
        "name": "NWS severe thunderstorm, tornado and flash flood warnings (Iowa State archive)",
        "superseded_by": "iem_watchwarn",   # B5: the About page lists iem_watchwarn (polygon, zone and county products)
        "request": "mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py for Montana, per year and one phenomenon per "
                   "request (SV, TO and FF are not returned together), with limitps=1 and the issuance polygons only. Expired "
                   "rows are skipped, and county rows (gtype C) are twins of polygon rows, also skipped. A cell is covered "
                   "when its centre lies inside a polygon.",
        "units": "Begin and end times are UTC, shown in Montana time. Tags as the archive gives them: hail in inches, wind in "
                 "mph, the tornado tag word and the NWS damage threat tag. Iowa State drops the '<' sign of a tag, so a tag "
                 "shows its number only.",
        "timing": "Each warning is dated by its issue and polygon times, in UTC. The newest year is read again each daily run.",
        "missing": "A new warning with no outline cannot be tied to a spot: it is counted, and the sheet says how many. "
                   "When no matched warning covers a spot and some warnings have no outline, the sheet says the warnings "
                   "cannot be checked, which is not the same as no warning. A missing tag is shown as not given, never as "
                   "zero. Tags are the forecast threat at issue time, not what fell. Known gaps: follow-up polygons are not "
                   "used, so a warning extended after issue shows at its issue polygon. In the five-year window the archive "
                   "gives both hail and wind tags for every severe thunderstorm warning checked.",
    },
    "nws_zone_products": {
        "name": "NWS zone-based warnings (Iowa State archive, zone rows)",
        "superseded_by": "iem_watchwarn",   # B5: the About page lists iem_watchwarn (polygon, zone and county products)
        "request": "mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py for Montana, zone rows (gtype C with a UGC "
                   "zone code), per year and one phenomenon per request with limitps=1, for ten products: HW.W (high "
                   "wind warning), WS.W (winter storm warning), BZ.W (blizzard warning), IS.W (ice storm warning), EC.W "
                   "(extreme cold warning), WC.W (wind chill warning), DS.W (dust storm warning), WI.Y (wind advisory), "
                   "FW.W (red flag warning) and FA.A (flood watch). A cell's forecast zone is its NWS public forecast "
                   "zone, found by point in "
                   "polygon at build time from the NWS zone file. Red flag warnings are matched to the cell's NWS fire "
                   "weather zone, a separate zone map, found the same way from the NWS fire zone file. Each product takes "
                   "the zone code of the public zone edition in force at its issue time. The NWS publishes two "
                   "editions: z_18mr25.zip (effective 18 March 2025) and z_16ap26.zip (effective 16 April 2026). The "
                   "six older editions named in the NWS change history were requested and are not published (HTTP 404 "
                   "when checked on 2026-10-19), so a product issued before 18 March 2025 is placed by the Iowa State zone "
                   "set in force at its issue time (the iem_ugcs row; D44), and a product of 7 to 13 September 2022 by the "
                   "set that holds its code.",
        "units": "Begin and end times are UTC, shown in Montana time. The product is named in words, for example 'High wind "
                 "warning'. No measurement is given: the product covered the whole zone.",
        "timing": "Each row has its issue and expiry times and a status (NEW, CON, EXT, EXA, EXB, UPG, EXP or CAN). A zone "
                  "event is one VTEC event: its key is the zone, the phenomenon, the significance, the issuing office, the "
                  "event number and the year, and rows with other issue times are updates of that event, never new events. "
                  "A span starts at the earliest issue time of its new or continued rows, or of its earliest row when it has "
                  "none. It ends at the earliest cancellation or upgrade time when the archive gives one (an upgrade ends the "
                  "lower product at the upgrade time, as NWS Instruction 10-1703 says, and the sheet says upgraded), else at "
                  "the latest expiry of its other rows. Its end is not recorded when neither is given. The newest year is "
                  "read again each daily run.",
        "missing": "A zone with no product in these five years is listed as none, which is not the same as no "
                   "wind. The product "
                   "covered the whole forecast zone, named, and not this spot alone. A product the build cannot place on a zone "
                   "(its code is in no zone of the edition in force) is counted, and the sheet says how many in Montana. "
                   "FL.W (flood warning) is a polygon product and is not joined in this version. Flood watches are joined "
                   "where the archive gives a zone code; county-only flood watches are not joined in this version. Known "
                   "gaps: zone "
                   "rows carry cancelled and expired statuses as the archive gives them. An event number that NWS "
                   "re-used for separate periods in one zone is one span here, which can hide a later period (four zones in "
                   "five years). NCEI names some zones by an "
                   "older name (Little Rocky Mountains under code MTZ060, for example); rows are placed by code, not by name.",
    },
    "asos_daily_gusts": {
        "name": "Iowa State daily summary, Montana airport stations (ASOS)",
        "request": "mesonet.agron.iastate.edu/cgi-bin/request/daily.py for the MT_ASOS network, one station and year per "
                   "request (max_wind_gust_kts). The two nearest stations to a tile's centre within 40 miles are joined. Each "
                   "station's file is cached by station and year, and the current year is read again each daily run.",
        "units": "Knots as the archive gives them, which are not always whole knots. Shown as whole knots and whole miles per "
                 "hour (1 knot is 1.15078 mph before rounding). Days with a maximum gust of 50 knots (58 mph) or more are "
                 "listed. Values of 130 knots or more are dropped as implausible for these sites and counted.",
        "timing": "One maximum per station per local day. The current year is read again each daily run.",
        "missing": "A station-day with no value is missing, not zero. A station reading is at the airport, not at this "
                   "address. Known gaps: the summary does not name the reading its gust comes from (a METAR gust or the peak "
                   "wind); about 39 percent of the values checked were not whole knots, and they match whole mph; 42 of the "
                   "network's 60 stations are ongoing, so some places have no station within 40 miles.",
    },
    # --hail-history builds only (build.py B6_CONTRACTS): the B6 base map (terrain, vectors, landmark points), the five-year
    # pictures, the zone counts and the recent radar hail. Each row's words are its module's (the B6 integration notes) with
    # the rulings applied: D112(c) and D121(a) credit lines in the "Source: ..." form, D113(c) grid words, D113(d) newest-warning
    # wording, D118(b) no figure of a held source, D124 no CC0 statement for NLCD 2021 (the record's own words are quoted).
    "terrain_shading": {
        "name": "USGS 3D Elevation Program (3DEP) hillshade, grey relief (rendering rule Hillshade Gray)",
        "request": "elevation.nationalmap.gov ImageServer exportImage, one 256 by 256 PNG per tile in EPSG:3857 for the 881 tiles "
                   "that overlap the Montana outline at zooms 5 to 10 (sun from 315 degrees, 45 degrees up); the service "
                   "description gives the data date, read at each build",
        "units": "8-bit grey, 0 to 255, stored as a grey JPEG at quality 80. Every grey value is kept as the service sends it.",
        "timing": "The monthly job passes --refresh-descriptions, not --refresh: the two service descriptions are read again, and a "
                  "tile is requested again only when its data month changed, through the cache key. A full --refresh runs only when "
                  "the owner asks. The build step is capped at 25 minutes and the check at 900 seconds. Otherwise a cached copy that "
                  "passes its check is used. The cache is keyed by the data month, and the other months are deleted after a build.",
        "missing": "A tile that does not load after three tries has no file, and the map shows paper there with 'Data "
                   "unavailable'. A service description that cannot be read makes the shading unavailable: that is not the same "
                   "as no shading. This is not an all-clear. Source: 3DEP data courtesy of the U.S. Geological Survey.",
    },
    "terrain_land_cover": {
        "name": "National Land Cover Database (NLCD) 2021, land cover (MRLC)",
        "request": "www.mrlc.gov geoserver, WCS 1.0.0 DescribeCoverage for mrlc_display:NLCD_2021_Land_Cover_L48 (read at each "
                   "build; its date keyword gives the cache month), then GetCoverage for the same 881 tiles, EPSG:3857, 256 by "
                   "256 GeoTIFF, nearest-neighbour sampling",
        "units": "NLCD class codes (2021 legend) in five tint colours: forest (41 to 43), shrub and grass (52, 71, 90 and 95; "
                 "woody and emergent wetlands take this class), developed (21 to 24), crop (81 and 82) and water (11). Barren "
                 "land (31 and 32) is transparent. Stored as palette PNGs with index 0 transparent; codes 0 and 255 are no data.",
        "timing": "The monthly job passes --refresh-descriptions, not --refresh, with the shading: the two service descriptions are "
                  "read again, and a tile is requested again only when its data month changed, through the cache key. A full "
                  "--refresh runs only when the owner asks. The build step is capped at 25 minutes and the check at 900 seconds. "
                  "The layer's date is read from the service at each build. A layer name that is no longer in the service makes "
                  "the land cover unavailable, with the reason in the block and on stderr.",
        "missing": "A tile that does not load after three tries has no file, and the map shows paper there with 'Data unavailable'. "
                   "A code outside the legend, or a truncated answer, is a failed try. The NLCD 2021 product record reads 'public "
                   "domain information', with access, use and fees none (doi 10.5066/P9JZ7AO3). Source: National Land Cover "
                   "Database 2021, U.S. Geological Survey and the Multi-Resolution Land Characteristics Consortium (public domain).",
    },
    "base_reservations": {
        "name": "U.S. Census Bureau TIGER/Line 2026 American Indian reservations (Montana)",
        "request": "www2.census.gov/geo/tiger/TIGER2026/AIANNH/tl_2026_us_aiannh.zip, read for its seven Montana reservations at every "
                   "zoom (the full-resolution file; the 1:500,000 cartographic file is never used)",
        "units": "Polygon rings in longitude and latitude (WGS 84), 5 decimals, simplified to 500 m in the statewide file. English "
                 "names, as the file gives them.",
        "timing": "Census TIGER 2026 release. The build reads the cached copy; the monthly job fetches it only when it is missing.",
        "missing": "If the file cannot be read, the reservation outlines are left out, the index names the source, and the map shows "
                   "the partial sentence rather than an empty map.",
    },
    "base_roads": {
        "name": "U.S. Census Bureau TIGER/Line 2026 primary and secondary roads (Montana), route shields",
        "request": "www2.census.gov/geo/tiger/TIGER2026/PRISECROADS/tl_2026_30_prisecroads.zip; interstate, US and state route "
                   "numbers only",
        "units": "Line paths in longitude and latitude (WGS 84), 5 decimals. The shield text (I-90, US-12, MT-200) is the route "
                 "number; the feature id is the road's LINEARID. A route-like local name (FAS 533, W US Hwy 12) carries no shield.",
        "timing": "Census TIGER 2026 release, read from the cache and fetched when missing.",
        "missing": "Without the file, or with no interstate, US or state route in it, the route shields are left out and the "
                   "index names them. Local roads are not part of this source.",
    },
    "base_places": {
        "name": "U.S. Census Bureau TIGER/Line 2026 places, with the 2020 Census counts (Montana)",
        "request": "www2.census.gov/geo/tiger/TIGER2026/PLACE/tl_2026_30_place.zip (names and points); the 2020 Census Public Law "
                   "94-171 Montana file, mt2020.pl.zip (population)",
        "units": "Points in longitude and latitude (WGS 84), 5 decimals. Population in persons, the 2020 count.",
        "timing": "The 2020 counts are fixed. TIGER 2026 is the Census annual release. Both are read from the cache.",
        "missing": "A place with no 2020 count shows Data unavailable, with the reason 'no census count under its code' in its row. "
                   "If the population file cannot be read, every place shows Data unavailable and the place kind is named. If the "
                   "place file cannot be read, places are left out and the index names them.",
    },
    "base_forests": {
        "name": "USDA Forest Service, Forest System Boundaries (the seven Montana national forests)",
        "request": "apps.fs.usda.gov, Forest System Boundaries map service, queried by the Montana envelope; outlines simplified to "
                   "about 20 m by the service",
        "units": "Polygon rings in longitude and latitude (WGS 84), 5 decimals. The forest name as the layer gives it.",
        "timing": "The layer's own update cycle. Read from the cache; a monthly run requests the query again only when its page is missing.",
        "missing": "If the query cannot be read, or names none of the seven forests, the forest outlines are left out and the index "
                   "names them. The layer's description says it is intended for read-only use; that is read as a usage note on a "
                   "federal work (public domain, 17 U.S.C. 105). The credit line ships with the first release, and counsel reads "
                   "the terms (counsel item 23).",
    },
    "base_parks": {
        "name": "PAD-US 4.1 Fee layer, Montana parks (national, state, recreation and local)",
        "request": "services.arcgis.com, PAD-US 4.1 Fee layer map service, where State_Nm = 'MT' and Des_Tp is one of NP, NM, NRA, "
                   "SP, SREC, REC, LP, LREC",
        "units": "Polygon rings in longitude and latitude (WGS 84), simplified to about 5 m by the service. Acres converted to km2 "
                 "for ranking; a park with no acreage has no size (null). The designation code is kept.",
        "timing": "PAD-US 4.1. Read from the cache; the monthly job requests the query again only when its page is missing.",
        "missing": "Without the query, or with no park of a known designation in it, no park outline is drawn and the index names the "
                   "source. A park with no name, a placeholder name or the managing agency's name keeps its outline and gets no name "
                   "and no label. A park that does not survive its band's simplification moves to the next finer band; one that does "
                   "not survive in the finest band it can reach is dropped and counted.",
    },
    "base_water": {
        "name": "U.S. Geological Survey National Hydrography Dataset, named lakes and rivers",
        "request": "hydro.nationalmap.gov, nhd map service: small scale lines (layer 4, drainage 100 km2 and up) and areas (layer 10, "
                   "0.02 km2 and up); large scale lines (layer 6) and areas (layer 12) for each 1 degree cell that holds a listed "
                   "tile, pages of 250 features; a query the service times out on (HTTP 504) is split into quarters, twice at most; "
                   "named features only",
        "units": "Lines and rings in longitude and latitude (WGS 84), 5 decimals. Drainage area in km2, length in km, lake area in km2. "
                 "Feature ids are the OBJECTID.",
        "timing": "The service as it stands when a page is requested. Each page is cached. The monthly job requests only the large-scale "
                  "cells missing from the cache and stops requesting at its deadline: a request that would start after the deadline is "
                  "not made, and the cells it leaves are listed with the reason 'deadline'. After a statewide online run in which no "
                  "request failed, the cache keeps the current cycle of each source and deletes the older files (the count is in the index).",
        "missing": "A cell whose water request still does not load after the quarter split, or is stopped by the deadline, leaves its "
                   "tiles unbuilt: no shard is written, and the index lists the cells and their reasons. Where a tile has no band D "
                   "shard, the browser keeps drawing band C's lakes and rivers at zoom 13 and up, and the sheet's water line for that "
                   "area reads 'Detailed water and local parks: Data unavailable for this area in this update. This is not an all-clear.' "
                   "A river with no drainage area is left out and counted. A lake or river wholly in another state is not drawn.",
    },
    "base_summit_names": {
        "name": "U.S. Geological Survey Geographic Names Information System, Montana summits",
        "request": "prd-tnm.s3.amazonaws.com, staged Domestic Names file for Montana (text), feature class Summit",
        "units": "Named points in decimal degrees (WGS 84). The file has no height.",
        "timing": "The staged file is read from the cache and fetched when missing.",
        "missing": "Without the file, or with no summit in it, no summit name is shown and the index names the source.",
    },
    "base_summit_heights": {
        "name": "U.S. Geological Survey 3D Elevation Program, summit heights at each summit's position",
        "request": "elevation.nationalmap.gov, 3DEP elevation image service, getSamples at each summit point in batches of 200",
        "units": "Metres at the summit's GNIS point (feet are metres divided by 0.3048). No-data values are missing.",
        "timing": "The 3DEP raster as the service holds it. Each batch is cached by its points.",
        "missing": "A summit with no sampled value is not ranked and is left out of the peak list; the index counts it as "
                   "peaks_no_height and the state is partial. If no summit has a value, the summit heights are named as not loaded.",
    },
    "nces_public": {
        "name": "National Center for Education Statistics, EDGE public school locations, 2024-25 (Montana)",
        "request": "nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0: the NAME, LAT "
                   "and LON fields where STFIP is 30. Duplicates of one name at one position are dropped.",
        "units": "Positions in decimal degrees (WGS 84) to five decimals, from the layer's own LAT and LON attributes. Counts of "
                 "schools. No distance is computed.",
        "timing": "The daily job reads the cache. The monthly job asks again for every file. NCES publishes a school year's file for "
                  "its own year.",
        "missing": "A request that does not load and has no cached copy, a layer description or page that is not in the form the build reads, or a "
                   "count below 600 rows makes the schools unavailable as a whole, so the sheet says Data unavailable. Unavailable is "
                   "not the same as zero. The layer says: \"All information contained in this file is in the public domain.\"",
    },
    "nces_private": {
        "name": "National Center for Education Statistics, EDGE private school locations, 2023-24 (Montana)",
        "request": "nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PRIVATESCH_2324/MapServer/0: NAME, LAT and "
                   "LON where STFIP is 30.",
        "units": "Positions in decimal degrees (WGS 84) to five decimals. Counts of schools.",
        "timing": "The daily job reads the cache; the monthly job asks again. The private school file is for its own year (2023-24).",
        "missing": "As for the public schools: a request that does not load with no cached copy, or a count below 80 rows, makes the "
                   "schools unavailable as a whole. The layer says: \"All information contained in this file is in the public domain.\"",
    },
    "usgs_hospitals": {
        "name": "USGS The National Map, hospitals and medical centers (Montana)",
        "request": "carto.nationalmap.gov/arcgis/rest/services/structures/MapServer/49: STATE 'MT', NAME and position (layer 14 "
                   "holds the same rows). The layer has no rights line: its copyright text is empty. The service root's copyright "
                   "line reads \"Data Refreshed October, 2026.\" (read 2026-10-26).",
        "units": "Positions in decimal degrees (WGS 84) to five decimals. Counts of hospitals.",
        "timing": "The daily job reads the cache; the monthly job asks again.",
        "missing": "This layer is the hospital source when it answers with named Montana rows. The HIFLD copy is read only when this "
                   "layer answers with no Montana rows. A request that does not load makes hospitals unavailable, never a silent "
                   "switch of source. The USGS terms page was not read in this build, so its licence is recorded as not read.",
    },
    "hifld_hospitals": {
        "name": "HIFLD copy of the state licensure list (hospitals, Montana, STATUS OPEN): fallback only",
        "request": "services2.arcgis.com/PYn6bWCjT6bhw1z3/arcgis/rest/services/HIFLD_Hospitals/FeatureServer/0. Read only when the USGS "
                   "layer answers with no Montana hospital row. The block records which source it used and why.",
        "units": "Positions in decimal degrees (WGS 84) to five decimals. Counts of hospitals.",
        "timing": "Read only in a run where the USGS layer has no rows; the monthly job asks again.",
        "missing": "Read only when the USGS layer answers with no Montana rows; a request that does not load makes hospitals "
                   "unavailable, never a silent switch of source. Its licence is not checked, so this copy is the fallback only.",
    },
    "faa_nasr": {
        "name": "FAA National Airspace System Resources, airport file (NASR 28-day cycle): public-use operational airports in Montana",
        "request": "nfdc.faa.gov/webContent/28DaySub/<cycle>/APT.zip, the cycle in force on the run date (28-day cycles anchored on "
                   "2026-10-01). Only the APT.txt member is read. Records kept: facility type AIRPORT, facility use PU, status O.",
        "units": "The airport reference point in decimal degrees (degrees, minutes and seconds in the file, converted). Names as "
                 "given, with the abbreviations written out and Airport added when no airport word is in the name.",
        "timing": "The cycle changes every 28 days; the build picks it from the run date. The cache keeps only the cycle in force: "
                  "the older zips are removed after a good build.",
        "missing": "A download that does not load with no cached copy, a file that is not a zip with an APT.txt member, or a file "
                   "with no Montana airport records makes the airports unavailable. There is no HIFLD fallback: its aviation copy is "
                   "an older cycle (2025/06/12).",
    },
    "usgs_fire": {
        "name": "USGS The National Map, fire and EMS stations (Montana)",
        "request": "carto.nationalmap.gov/arcgis/rest/services/structures/MapServer/51: STATE 'MT', NAME and position (layer 16 holds "
                   "the same rows). The layer has no rights line; the service root's copyright line is the one given for the "
                   "hospital layer.",
        "units": "Positions in decimal degrees (WGS 84) to five decimals. Counts of stations. The layer lists EMS stations with fire "
                 "stations.",
        "timing": "The daily job reads the cache; the monthly job asks again.",
        "missing": "A request that does not load with no cached copy, a layer description or page that is not in the form the build reads, or a count "
                   "below 300 makes the fire and EMS stations unavailable. Unavailable is not the same as no stations.",
    },
    "padus_local": {
        "name": "USGS Protected Areas Database of the United States (PAD-US) 4.1, local parks (Montana)",
        "request": "services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Managers_PADUS/FeatureServer/0: State_Nm 'MT' and "
                   "Des_Tp 'LP'. The layer was last edited 2026-04-22. The park points ship; the Census park list is held and is "
                   "not shown.",
        "units": "A label point for each park: the pole of inaccessibility of its polygon, the distance measured in degrees (about "
                 "1e-5 degree, about a metre of latitude). Names as the layer gives them, with the name rules of the landmarks "
                 "module. Counts of parks.",
        "timing": "The monthly job asks again; the daily job reads the cache. The polygon outlines for the map come from the base map "
                  "files, so the names here and there match.",
        "missing": "A request that does not load with no cached copy, a layer description or page that is not in the form the build reads, or a count "
                   "below 300 makes the parks unavailable. The layer's copyright line is the USGS citation with DOI 10.5066/P96WBCHS. "
                   "The layer does not say the data is in the public domain, and the PAD-US terms of use were not read: a counsel "
                   "question.",
    },
    "tiger_park": {
        "name": "U.S. Census Bureau TIGER/Line 2026, area landmarks: park (K2180) and incorporated place park (K2188), Montana "
                "(held for counsel: not shown or written to the store)",
        "request": "www2.census.gov/geo/tiger/TIGER2026/AREALM/tl_2026_30_arealm.zip. The named park points are held, so no count of "
                   "them is published. A park point that is the same park as a PAD-US park gives that PAD-US row an alternate name, "
                   "which is held with the points.",
        "units": "The Census interior point in decimal degrees (WGS 84) to five decimals. Named rows only.",
        "timing": "The Census vintage is 2026. The file is cached by its own name, and an older vintage is removed after a good build. "
                  "The daily job reads the cache; the monthly job asks again.",
        "missing": "Held for counsel, because the file's use constraints are for counsel to read before any text from it ships. A "
                   "missing shapefile reader stops this held source only; the PAD-US parks still ship.",
    },
    "fema_worship": {
        "name": "FEMA copy of an IRS-based places of worship list, point-address rows, Montana (held for counsel: not shown or written "
                "to the store)",
        "request": "services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/All_Places_Of_Worship__HiFLD_Open_/FeatureServer/42: "
                   "STATE 'MT' and LOC_NAME 'POINTADDRESS'. The layer was last edited 2025-09-04. No count of its rows is published.",
        "units": "Positions in decimal degrees (WGS 84) to five decimals while the kind is held; no count is published.",
        "timing": "Not shown while held. When the hold is lifted, the next build writes the kind.",
        "missing": "Held for counsel: the layer's copyright line says the points were geocoded by a commercial geocoder whose terms are "
                   "not read. While held, its rows are not shown and not written to the store; the store carries the state and the "
                   "reason only. A request that does not load leaves the kind held.",
    },
    "history_pictures": {
        "name": "Five-year radar and grid pictures: days with a radar estimate of 1 inch or more, and days at or above 90 F, Montana",
        "request": "The store's own files: hail/t/ (NOAA MRMS MESH radar estimates; see hail_history) and hail/c/ (NOAA nClimGrid-Daily "
                   "grid estimates; see nclimgrid_daily). No network request.",
        "units": "Days (whole). A radar cell is 1 km (0.01 degree). The grid cells are about 1/24 degree cells (roughly 4.6 by 3 km in "
                 "Montana). Radar values are stored in tenths of a millimetre and counted at 254 tenths (1.00 in).",
        "timing": "Built by the daily job after the store is packed; the store's as_of names the newest day in the pictures.",
        "missing": "A cell with no stored day at 1 inch or more is transparent. That is not the same as no hail. A climate cell with no "
                   "grid value is transparent. A listed shard that cannot be read makes its picture unavailable for that update, and "
                   "the page says so. Missing radar days in the store are named in the legend.",
    },
    "history_zone_counts": {
        "name": "Warnings, watches and advisories by public forecast zone, eight measures, five seasons",
        "request": "The store's zone rows (hail/z/), read from the IEM watchwarn zone file under the name nws_zone_products, and its "
                   "polygon rows (hail/j/events.json and the tile join files hail/j/r<tile>.json), read from the IEM watchwarn "
                   "shapefile under the name nws_warnings_polygons. The sources table lists both under iem_watchwarn. No network request.",
        "units": "Counts of products (whole): every warning, watch or advisory the store holds for the zone, including those later "
                 "cancelled, upgraded or expired early. A polygon product counts in a zone when it touches one of the zone's 1 km "
                 "cells. Times are UTC; the window is 12:00 UTC on the first SPC day to 12:00 UTC after the last.",
        "timing": "Built by the daily job. The newest warning in these counts is dated in the words shown with the counts "
                  "(newest_warning, taken from the counted rows).",
        "missing": "A zone whose product file is absent shows Data unavailable for its counts; a part of the joins that did not load "
                   "makes its measures Data unavailable for every zone, with the reason. A zero is a count only when the rows were read. "
                   "A joins row that names a warning the warnings file does not hold makes the zone counts unavailable; the pictures "
                   "and the outlines still build.",
    },
    "recent_radar_cells": {
        "name": "Cells with a radar estimate of 1 inch or more in the last 30 days",
        "request": "The store's radar shards (hail/t/). No network request.",
        "units": "A day index from 2020-01-01 and tenths of a millimetre, per cell (row and column of the 1 km grid).",
        "timing": "Built by the daily job with the store's as_of. A sentence is shown when the store is older than 3 days (hail.is_stale). "
                  "The switch Highlight recent radar hail shows these cells on the map.",
        "missing": "A cell not listed had no such day in the store. That is not the same as no hail. Missing radar days in the window "
                   "are named in the legend.",
    },
    "bubble_anchors": {
        "name": "Value bubble anchors on the building outlines (derived from the outlines and the radar store)",
        "request": "The store's building shards (hail/b/, from usa_structures) and radar shards (hail/t/). No network request.",
        "units": "Pixels at zoom 17 and 18 (256 px tiles) for the placement; bubble text in inches to the hundredth, rounded down.",
        "timing": "After every outline rebuild: the labels pass runs after the outlines step, every time.",
        "missing": "A cell with no stored estimate of 0.25 in or more reads \"Data unavailable\" and its bubble is a dash, never zero. "
                   "An outline whose cell lies outside its shard's tile gets no bubble and is counted. A shard that does not load "
                   "loses its flags, and the block reads partial.",
    },
    # --hail-history builds only (build.py HAIL_CONTRACTS): the B5 feeds behind the five-season table, the sections and the
    # roof lines (AGENTS.md rule 7; the terms are quoted from the module docstrings and the records named in each row).
    "nclimgrid_daily": {
        "name": "NOAA nClimGrid-Daily, daily temperature and rain grid (Montana cells)",
        "request": "The NOAA bucket noaa-nclimgrid-daily-pds (AWS Open Data, anonymous HTTPS): access/grids/YYYY/"
                   "ncdd-YYYYMM-grd-scaled.nc for each month (the scaled monthly files), and ncdd-YYYYMM-grd-prelim.nc only "
                   "where no scaled file exists yet. The variables prcp, tmax and tmin are read by whole month in the backfill "
                   "and the monthly update, and by HTTP Range for the newest prelim days. Each cell keeps monthly aggregates "
                   "(rain, the highest and lowest with their dates, days at or above 90 F, days at or below 0 F, freeze-thaw "
                   "days, days with a low below 32 F, missing days); a monthly file is deleted once its aggregates are written. "
                   "Terms, quoted from the file and the NOAA registry: the file attribute \"license = no restrictions\"; the "
                   "registry says \"NOAA requests attribution for the use or dissemination of unaltered NOAA data. However, it is "
                   "not permissible to state or imply endorsement by or affiliation with NOAA. If you modify NOAA data, you may "
                   "not state or imply that it is original, unaltered NOAA data.\" The page says \"US government data; NOAA "
                   "declares no restrictions; attribution requested\". No NOAA page checked says public domain for these grids, "
                   "so this site does not say so.",
        "units": "Rain: millimetres in the file, shown in inches (hundredths of an inch stored). Temperature: degrees Celsius "
                 "in the file, rounded to the hundredth of a degree and then to the tenth; shown in degrees Fahrenheit (tenths "
                 "stored). Days are whole days. Every value is a grid estimate for a cell about 4.6 km across (1/24 degree), "
                 "not a reading at the address. The grid holds no snow variable.",
        "timing": "Scaled months appear about 4 to 68 days after the month ends (median 66). The prelim days are valid to 2 to "
                  "3 days before the build. The daily job reads the new prelim days and the monthly job reads a new scaled "
                  "file. Each run compares the listing's ETags, because scaled files are revised (2026-06 to 2026-08 were "
                  "rewritten on 2026-10-19).",
        "missing": "NaN, -999.99 (a prelim day not yet available) and values outside the file's valid range are missing. A "
                   "missing input makes its day a missing day for that cell, and the page says \"n days missing\". A missing "
                   "value is never summed and never zero, and the -999.99 fill is never summed. 71 water cells have no land "
                   "value and read \"No land value for this grid cell\". Known gaps: the grid is about 4.6 km across, so a "
                   "cell and an airport can differ (at Billings the grid differed from the airport by 18.8 mm of rain in July "
                   "2025 and by 1.0 C on one day).",
    },
    "nohrsc_season_snowfall": {
        "name": "NOAA NOHRSC National Snow Analysis, season-total snowfall (water years)",
        "request": "The NOHRSC season-total snowfall GeoTIFF for each water year, sfav2_CONUS_<Y>093012_to_<Y+1>093012.tif, "
                   "from nohrsc.noaa.gov: 2021-22 to 2025-26 (water years 2022 to 2026), 11,562,084 bytes in all. The 2020-21 "
                   "file is missing upstream (HTTP 404 on 2026-10-19). The grid is 0.04 degree, about 3 to 4 km. The file "
                   "prints no units, so the build checks them against station season totals; the analysis is shown only if the "
                   "check passes. On 2026-10-19 it did not (slope 0.664, outside 0.85 to 1.15), so the analysis is not shown. "
                   "The NWS terms, quoted as the live page gives them: \"The information on National Weather Service (NWS) Web "
                   "pages are in the public domain, unless specifically noted otherwise, and may be used without charge for any "
                   "lawful purpose so long as you do not: 1) claim it is your own (e.g., by claiming copyright for NWS "
                   "information -- see below), 2) use it in a manner that implies an endorsement or affiliation with NOAA/NWS, or "
                   "3) modify its content and then present it as official government material.\" and \"As required by 17 U.S.C. "
                   "§ 403, third parties producing copyrighted works consisting predominantly of the material appearing in "
                   "NWS Web pages must provide notice with such work(s) identifying the NWS material incorporated and stating "
                   "that such material is not subject to copyright protection.\"",
        "units": "Inches only when the unit check passes; the store's index says whether it did. Water year: October 1 to "
                 "September 30, named for the year it ends. An analysis, not a measurement at this address.",
        "timing": "The 2025-26 file is checked with one request each run and fetched again when its Last-Modified time changes "
                  "(on 2026-10-19: Mon, 05 Oct 2026 14:33:16 GMT). The other files are not checked again after their fetch.",
        "missing": "Values below -9000 are no data (the file uses -99999). A negative value is missing, not zero. A water year "
                   "whose download does not pass its check is named as missing and the rest of the block builds. The analysis was checked against "
                   "station season totals and left out in this build: its amounts did not match the station totals closely "
                   "enough to show, and the About page says so.",
    },
    "ghcn_daily": {
        "name": "NOAA NCEI GHCN-Daily, station daily records (airport, cooperative and SNOTEL sites)",
        "request": "https://www.ncei.noaa.gov/pub/data/ghcn/daily/: ghcnd-stations.txt (the station list), ghcnd-inventory.txt "
                   "(what each station reports, by year) and all/<ID>.dly (each station's daily values, the NCEI copy). NOAA's "
                   "S3 by-station copies are not used: their SNOTEL and airport records end early in 2025. Stations in Montana "
                   "and the neighbouring states within 40 miles are candidates, and the station rule picks the two nearest that "
                   "pass, per element and place. Canadian stations (identifiers beginning CA) are candidates that are not read: "
                   "their files are never requested, because the terms for their data are under review. "
                   "The elements read are TMAX, TMIN, PRCP, SNOW and SNWD. The NRCS SNOTEL service is not used; the GHCN copies "
                   "of SNOTEL stations are station records like the others. Licence: NOAA and federal records are public domain "
                   "in the United States under NCEI-PD-10-2-02, section 4(a) (\"These data are in the public domain in the United "
                   "States.\"). CoCoRaHS records (file prefix US1) are released under CC BY 3.0 (\"Unless otherwise noted, all "
                   "CoCoRaHS content and data are released under a Creative Commons Attribution 3.0 License\") and ask users to "
                   "acknowledge the source. The NODD copy is CC0 (\"NOAA data disseminated through NODD is made available under "
                   "the Creative Commons 1.0 Universal Public Domain Dedication (CC0-1.0) license\"). Cite NCEI-PD-10-2-02.",
        "units": "SNOW and SNWD in millimetres (shown in inches; a 1-inch snow depth is 25 mm or more). PRCP in tenths of a "
                 "millimetre (shown in inches). TMAX and TMIN in tenths of a degree Celsius (shown in degrees Fahrenheit; a 90 F "
                 "day is a high of 32.2 C or more). A season shows only when at least 95 percent of its days have the element.",
        "timing": "The archive values take the place of the preliminary real-time values about 45 to 60 days after the end of a month (NCEI: "
                  "\"Generally, real-time replacement of updated data streams are replaced by archive-ready data sources 45 to 60 "
                  "days after the end of a month.\"). Each station shows its newest report date. The daily job refreshes the "
                  "list, the inventory and the files of the chosen stations whose Last-Modified time changed; the monthly job "
                  "refreshes every file the rule reads.",
        "missing": "-9999 and an absent day are missing, never zero. A value with a non-blank quality flag is excluded from every "
                   "sum, record and count. The measurement flag T (trace) counts as zero in sums, and the page says so. A station "
                   "is a candidate for an element only when it reported that element within 30 days of the as-of date and has at "
                   "least 80 percent of the days 2020 to 2025 with an unflagged value. A station reading is at the station, not at "
                   "the address, and its distance is shown on every row. Known gaps: the archive lags 45 to 60 days, so the newest "
                   "season can be partial.",
    },
    "iem_watchwarn": {
        "name": "NWS warnings, watches, advisories and zone products (Iowa State archive: polygons, zones and counties)",
        "request": "mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py for Montana. Polygon shapefiles: FL.W (flood "
                   "warning), FA.W (areal flood warning), FA.Y (areal flood advisory), FL.A (flood watch), FL.Y (flood advisory), "
                   "SQ.W (snow squall warning), and SV.W, TO.W and FF.W. Zone CSVs: HW.W, WS.W, BZ.W, IS.W, EC.W, WC.W, DS.W, WI.Y, "
                   "WW.Y, WS.A, HW.A, HT.Y, EH.W, EH.A, FR.Y, FZ.W, DU.Y and FA.A, and the county twins of FA.A and FF.A (the "
                   "county-only events). FW.W (red flag warning) is matched to the fire weather zones. Each request covers 1 "
                   "December of the year before to 31 January of the year after, and a row that two years' files share is kept "
                   "once. A cell is covered when a polygon intersects its square, and the centre rule is counted beside it. A zone "
                   "event is one VTEC event (its key is the zone, phenomenon, significance, office, event number and year). Its "
                   "periods open at a NEW, CON, EXT, EXA or EXB and close at a CAN, UPG or EXP, and each period is a span. Terms, "
                   "quoted from the Iowa State and NWS pages: \"The materials found on this website are in the public domain and "
                   "may be used freely by anyone for any lawful purpose.\" \"Attributing the Iowa Environmental Mesonet of Iowa "
                   "State University would be appreciated.\" \"We therefore provide this information without any warranty of "
                   "accuracy.\" \"The information on National Weather Service Web servers and Web sites is in the public domain, "
                   "unless specifically annotated otherwise, and may be used freely by the public.\" \"You also cannot present "
                   "information of your own in a way that makes it appear to be official government information.\"",
        "units": "Begin and end times are UTC (the feed's YYYYMMDDHHMM), shown in Montana time. Tags as the archive gives them: hail "
                 "in inches, wind in mph, the tornado tag word, and the NWS damage threat tag shown as the NWS's own label. Counts "
                 "are whole warnings, products or events.",
        "timing": "Each row carries its issue and expiry times and a status (NEW, CON, EXT, EXA, EXB, UPG, EXP or CAN). The "
                  "latest year is read again each daily run and earlier years are cached. The NWS publishes two zone editions, "
                  "z_18mr25.zip (effective 18 March 2025) and z_16ap26.zip (effective 16 April 2026); a product takes the zone "
                  "of the edition in force at its issue time when that edition is published. The six older editions named in the "
                  "NWS change history are not published (HTTP 404 when checked on 2026-10-19), so a product issued while one of "
                  "them was in force keeps its zone code and is checked against the current edition.",
        "missing": "A warning with no outline and no zone or county code cannot be tied to a spot: it is counted, the page says "
                   "how many, and it is never read as no warning. A row with a null or empty geometry joins by its zone or county "
                   "codes where the product carries them. A tag with no value is shown as not given, never as zero. Tags are the "
                   "forecast threat at issue time, not what fell. A warning extended after issue shows at its issue polygon, "
                   "because follow-up polygons are not used. A product the build cannot place on a zone is counted, and the page "
                   "says how many in Montana.",
    },
    "iem_ugcs": {
        "name": "Montana public forecast zones by date (Iowa State IEM ugcs service: simplified outlines)",
        "request": "mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson?state=MT&valid=<UTC>, for seven dates: 2021-09-15, "
                   "2022-06-01, 2022-09-10 and 2022-09-13 12:00Z (103 Montana zones), and 2022-09-13 18:00Z, 2023-06-01 and "
                   "2025-03-18 (83 zones). Each answer is a GeoJSON FeatureCollection; its MTZ features give the zone code, "
                   "name and outline. Terms, quoted from the IEM pages read: the API disclaimer says \"All of these services "
                   "are provided as-is and without warranty. You are free to use these services for any lawful purpose "
                   "(including commercial ...)\", and the OpenAPI description says \"This service is free to use for most any "
                   "legal purpose.\" The IEM site footer reads \"All rights reserved.\" The words \"public domain\" and "
                   "\"attribution appreciated\" were not found on the pages read, so the About page does not say them. The "
                   "ugcs snapshot of 2026-10-25 (valid=2026-10-25T00:00Z) gives the 83 public zone outlines only. The B6 zone "
                   "counts use the counted rows from the store's zone and polygon files.",
        "units": "Zone codes (MTZ and a number) and names as the snapshot gives them. Outlines are decimal degrees of longitude "
                 "and latitude, simplified by the IEM. Counts are zones.",
        "timing": "A snapshot is the zone set valid at the time asked. The 103 zones hold through 12:00Z on 13 September 2022 "
                  "and the 83 zones from 18:00Z that day. The NWS change log dates the change 7 September 2022, so the switch "
                  "date lies between 12:00Z and 18:00Z on 13 September; products issued from 7 September to 18:00Z on 13 "
                  "September are placed by the set that holds their code. The snapshots are historical: they are cached once "
                  "and not re-pulled. The B6 history layers read the ugcs snapshot of 2026-10-25 (valid=2026-10-25T00:00Z) from "
                  "the cache, and it gives the 83 public zone outlines only; the B6 zone counts use the counted rows from the "
                  "store's zone and polygon files. The snapshot is fetched "
                  "once; a new valid time or a changed zone set is a reviewed change. The build refuses any zone count other than "
                  "83, and a fetched page that is not that set is never cached.",
        "missing": "A zone that a snapshot does not hold is not in that zone set, so a product under its code is counted as "
                   "unplaced and never placed on a neighbouring zone. A snapshot that does not parse, has a zone with no "
                   "outline, or repeats a code is refused, and the products its set would place are counted as unplaced. The "
                   "outlines are simplified: the 20 zones removed on 13 September 2022 (MTZ008 to MTZ015 and MTZ044 to MTZ055) "
                   "and MTZ060 before that change use these outlines, and their rows say so. The 83 zones in force since then "
                   "keep the NWS outlines; the IEM outlines of those 83 zones lie within 0.014 degrees of the NWS file.",
    },
    "iem_lsr": {
        "name": "NWS local storm reports (Iowa State archive, the types the history reads)",
        "request": "mesonet.agron.iastate.edu/cgi-bin/request/gis/lsr.py for Montana, one CSV per calendar month the window "
                   "touches; the last two months are read again each daily run. The types read are FLASH FLOOD, FLOOD, HEAVY RAIN "
                   "and RAIN (the label changed in 2023), FREEZING RAIN, HEAVY SNOW and SNOW (the label changed in 2023), BLIZZARD, "
                   "EXTREME COLD and WIND CHILL (the type words changed over the window: the build keeps a dated table and shows the "
                   "word each report carries), EXTREME HEAT, LIGHTNING, NON-TSTM WND GST and NON-TSTM WND DMG, with the hail, "
                   "thunderstorm wind, tornado and funnel cloud reports read before. Each report within 5 miles of a cell's centre "
                   "is joined to it. The terms are the Iowa State terms quoted in the warnings row.",
        "units": "Hail, rain and snow in inches as reported (codes H, R and S). Gusts and sustained wind in mph (codes G, N and A; "
                 "the archive gives no unit, and the research read it as mph). Codes 5, 6, 7, I and J (freezing rain, extreme cold, "
                 "wind chill, extreme heat and fog) show no magnitude: their unit is not verified in the IEM documentation read, "
                 "so the remark is shown as written. Times are UTC (VALID), shown in Montana time.",
        "timing": "Each report carries its valid time in UTC. The files are monthly and the newest month grows as reports arrive, "
                  "so its last two months are read again each day. The type words in the store are listed with their first and "
                  "last dates.",
        "missing": "A magnitude of None is missing, not zero, and many type codes carry None. A report is what someone sent the "
                   "NWS, not a complete record. A missing report is not the same as no hail; the same holds for wind and flood. "
                   "Known gaps: the wind "
                   "unit is inferred; Iowa State does not document the basis of qualifiers on reports from before September 2024; "
                   "the magnitudes of codes 5, 6, 7, I and J are not shown until their units are verified.",
    },
    "nwps_gauges": {
        "name": "NWS National Water Prediction Service gauges (flood categories)",
        "request": "api.water.noaa.gov/nwps/v1: the gauge list for the Montana box (srid EPSG_4326; -117.0 to -103.5 W and 44.0 "
                   "to 49.5 N), and each gauge's detail: its flood categories (action, minor, moderate and major, in feet), state, "
                   "USGS number and position. The pool is every gauge in the box that defines an NWS flood stage (its minor "
                   "category), except gauges whose categories are elevations of 1,000 ft or more (Lake Pend Oreille at Hope, Idaho, "
                   "is the nearest such, 13.7 miles from a Montana grid point). The nearest pool gauge within 10 miles of a town "
                   "or tile centre gives the river gauge line (owner decision O4; 25 miles is the alternative). The NWS conditions "
                   "in the warnings row apply to these pages.",
        "units": "Flood stages in feet, two decimals, stored as hundredths of a foot. -9999 is not defined. Water years run "
                 "October 1 to September 30.",
        "timing": "The gauge list and each gauge's detail are read on the monthly job, and again when a gauge enters the pool. "
                  "The daily job reads the list and the details the job names. Flood categories change rarely.",
        "missing": "-9999 and an absent category are not defined. A reservoir gauge that defines only an action stage has no flood "
                   "stage and is not in the pool. A gauge whose detail could not be read is kept as a candidate by its position: "
                   "its line reads that the gauge could not be loaded, never none, and a farther gauge is not used instead. A "
                   "gauge with no USGS number has no peak series. The gauge line does not say that water reached the address.",
    },
    "usgs_water_api": {
        "name": "USGS Water Data API, annual peak stage at the river gauges",
        "request": "api.waterdata.usgs.gov (OGC API, collection peaks): monitoring_location_id=USGS-<number>, parameter_code=00065 "
                   "(gage height, feet), limit 1000, f=json; one request per USGS number in scope (104 series, 103 with peak rows). "
                   "The parameter code is required: without it the response mixes 99 discharge rows into 64 gage-height rows. "
                   "waterservices.usgs.gov is retired on 2027-02-22 and is not used. Credit: \"Observations courtesy of U.S. "
                   "Geological Survey\". Not all USGS site content is public domain (non-USGS photographs and graphics need "
                   "permission); the peaks are USGS data.",
        "units": "Gage height in feet, two decimals (the service returns text), stored as hundredths of a foot. Annual peak stage by "
                 "water year (October 1 to September 30, named for the year it ends). The service's qualifiers are shown as given.",
        "timing": "Read on the monthly job for every series in scope. The newest water year is read again when it changes.",
        "missing": "A series that could not be read is marked unavailable on its gauge's line, which never reads as no annual peak. "
                   "A water year with two USGS rows keeps both, each with its qualifiers. A gauge with no USGS number has no series.",
    },
    "census_tiger_counties": {
        "name": "US Census Bureau TIGER/Line 2026 county boundaries",
        "request": "www2.census.gov/geo/tiger/TIGER2026/COUNTY/tl_2026_us_county.zip (83,378,454 bytes), read once and kept. It "
                   "places each Montana cell in one of the state's 56 counties (the MTC codes), joins the county-only watches (FA.A "
                   "and FF.A) and the county-coded polygon products. A cell that no county polygon holds (177 cells, each within 2 km "
                   "of a county edge) takes the nearest county edge within 2 km. The county file's own use constraint, from its "
                   "metadata: \"The TIGER/Line shapefile products are not copyrighted; however, TIGER/Line and Census TIGER are "
                   "registered trademarks of the U.S. Census Bureau. These products are free to use in a product or publication, "
                   "however acknowledgement must be given to the U.S. Census Bureau as the source.\"",
        "units": "Boundaries as polygons in degrees, with the cell tests in exact decimal arithmetic. Counts are whole events.",
        "timing": "Read once per edition. TIGER/Line is issued each year; the 2026 edition is kept and the next edition is read when "
                  "it is published.",
        "missing": "A cell with no county is counted as unplaced, never given a county of its own. A county product without county "
                   "codes is counted and not joined. The acknowledgement is required, and this site gives it on the About page.",
    },
    "roof_references": {
        "name": "Public references for the roof lines (reference statements, not findings)",
        "request": "The research record roof-indicators.json holds R1 to R20, each a statement from a public source. The sheet "
                   "quotes fifteen of them on its roof lines: R1, R3, R4, R5, R6, R7, R8, R10, R11, R12, R14, R15, R16, R18 and R19. "
                   "Each quote is in the source's own words, and each line names its source and its address. R2, R9, R13, R17 and R20 "
                   "are not quoted, and the record gives the reason for each: R2 (the NWS glossary) repeats the thresholds that R1 "
                   "and R3 quote, with a missing space in its wording; R9 (FEMA P-957) describes a design value that the history "
                   "holds out; R13 (ARMA) gives no mph threshold and its quote is a test standard's title; R17 (drought.gov, SNOTEL) "
                   "concerns a network the history holds out; R20 is a secondary source found in search results and not fetched, "
                   "which the record treats as unverified.",
        "units": "Kind word \"Reference\" on every line. A reference is a quoted statement from its source and gives no measurement "
                 "for this place.",
        "timing": "The quotes were read from the source pages during the research (2026-10-19). A source that changes its page is "
                  "not read again by the build; the line names the source and its address.",
        "missing": "A reference with no quote is not shown. None of the reference lines says what a roof needs, and none is a "
                   "finding about any roof, weather event or address.",
    },
}


CONVECTIVE = ("Tornado Warning", "Severe Thunderstorm Warning", "Flash Flood Warning", "Extreme Wind Warning")


# ---------------------------------------------------------------- time helpers

def parse_iso(text) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else None


_DUR = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?")


def duration_hours(text: str) -> int:
    """'PT6H' -> 6, 'P1DT2H' -> 26. Unknown shapes count as one hour."""
    m = _DUR.fullmatch(text or "")
    if not m or not any(m.groups()):
        return 1
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return max(1, d * 24 + h + (1 if mi else 0))


# ---------------------------------------------------------------- official alerts

def alert_kind(event: str) -> str:
    e = (event or "").lower()
    if e.endswith("warning") or e.endswith("emergency"):
        return "warning"
    if e.endswith("watch"):
        return "watch"
    if e.endswith("advisory"):
        return "advisory"
    return "statement"


_KIND_RANK = {"warning": 0, "watch": 1, "advisory": 2, "statement": 3}


def parse_alerts(doc) -> list[dict]:
    """NWS /alerts/active GeoJSON -> alerts sorted most urgent first.

    Raises ValueError when the response has no feature list: an unreadable response is
    "couldn't check", never "no alerts". Test and exercise messages are left out. A message
    that a newer active message references (an update it replaced) is dropped.
    """
    feats = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(feats, list):
        raise ValueError("the NWS alert response had no list of alerts")
    alerts = []
    for f in feats:
        if not isinstance(f, dict) or not isinstance(f.get("properties"), dict):
            raise ValueError("the NWS alert response had an unreadable alert")
        p = f["properties"]
        if p.get("status") != "Actual" or p.get("messageType") == "Cancel":
            continue
        geom = f.get("geometry")
        has_shape = isinstance(geom, dict) and geom.get("type") in ("Polygon", "MultiPolygon")
        event = p.get("event") or "Alert"
        until = parse_iso(p.get("ends")) or parse_iso(p.get("expires"))
        alerts.append({
            "id": p.get("id") or f.get("id") or "",
            "event": event,
            "kind": alert_kind(event),
            "headline": p.get("headline") or "",
            "area": p.get("areaDesc") or "",
            "severity": p.get("severity") or "",
            "sender": p.get("senderName") or "",
            "sent": _iso(parse_iso(p.get("sent"))),
            "onset": _iso(parse_iso(p.get("onset")) or parse_iso(p.get("effective"))),
            "until": _iso(until),
            "description": (p.get("description") or "").strip(),
            "instruction": (p.get("instruction") or "").strip(),
            "geometry": geom if has_shape else None,
        })
    replaced = alert_references(doc)
    alerts = [a for a in alerts if a["id"] not in replaced]
    alerts.sort(key=alert_order)
    return alerts


def alert_references(doc) -> set[str]:
    """The ids of the messages that the active messages of an NWS alert response (as parse_alerts
    reads it) replace: an update names the message it replaces in "references"."""
    out = set()
    for f in doc.get("features") or []:
        p = f.get("properties") or {}
        if p.get("status") != "Actual" or p.get("messageType") == "Cancel":
            continue
        for ref in p.get("references") or []:
            if isinstance(ref, dict) and ref.get("identifier"):
                out.add(ref["identifier"])
    return out


def alert_order(a: dict) -> tuple:
    """Sort key, most urgent first: warnings (convective events first, then by end time), watches,
    advisories, statements."""
    return _KIND_RANK[a["kind"]], 0 if a["event"] in CONVECTIVE else 1, a["until"] or "9999"


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None


# ---------------------------------------------------------------- forecasts

def parse_point(doc) -> dict:
    p = (doc or {}).get("properties") or {}
    needed = ("forecast", "forecastHourly", "forecastGridData")
    if not all(isinstance(p.get(k), str) and p[k].startswith(NWS + "/") for k in needed):
        raise ValueError("the NWS point lookup had no forecast links")
    rel = ((p.get("relativeLocation") or {}).get("properties") or {})
    stations = p.get("observationStations")
    return {"forecast": p["forecast"], "hourly": p["forecastHourly"], "grid": p["forecastGridData"],
            "stations": stations if isinstance(stations, str) and stations.startswith(NWS + "/") else None,
            "office": p.get("gridId"), "grid_x": p.get("gridX"), "grid_y": p.get("gridY"),
            "tz": p.get("timeZone") or "America/Denver",
            "near": ", ".join(x for x in (rel.get("city"), rel.get("state")) if x)}


def wind_mph(text) -> float | None:
    """'10 mph' -> 10, '10 to 15 mph' -> 15 (the higher number). No number -> unknown."""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(text or ""))]
    return max(nums) if nums else None


def _temp_f(value, unit):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return value if unit in (None, "F") else value * 9 / 5 + 32


def parse_hourly(doc) -> tuple[list[dict], str | None]:
    props = (doc or {}).get("properties") or {}
    periods = props.get("periods")
    if not isinstance(periods, list) or not periods:
        raise ValueError("the NWS hourly forecast had no hours")
    hours = []
    for p in periods:
        start = parse_iso(p.get("startTime"))
        if start is None:
            continue
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value")
        hours.append({"start": start, "temp_f": _temp_f(p.get("temperature"), p.get("temperatureUnit")),
                      "wind_mph": wind_mph(p.get("windSpeed")), "wind_dir": p.get("windDirection") or "",
                      "precip": pop if isinstance(pop, (int, float)) else None,
                      "sky": p.get("shortForecast") or "", "day": bool(p.get("isDaytime")),
                      "gust_mph": None})
    if not hours:
        raise ValueError("the NWS hourly forecast had no readable hours")
    return hours, _iso(parse_iso(props.get("updateTime")) or parse_iso(props.get("generatedAt")))


def parse_gusts(doc) -> dict:
    """NWS gridpoint windGust series -> {hour start (UTC): gust mph}. Missing hours stay missing."""
    prop = (((doc or {}).get("properties") or {}).get("windGust")) or {}
    uom = str(prop.get("uom", ""))
    if "km_h" in uom:
        conv = KMH_TO_MPH
    elif "m_s" in uom:
        conv = MS_TO_MPH
    elif not prop.get("values"):
        return {}
    else:
        raise ValueError(f"unexpected gust unit {uom!r}")
    out = {}
    for item in prop.get("values") or []:
        start_s, _, dur = str(item.get("validTime", "")).partition("/")
        start, value = parse_iso(start_s), item.get("value")
        if start is None or not isinstance(value, (int, float)):
            continue
        start = start.replace(minute=0, second=0, microsecond=0)
        for i in range(duration_hours(dur)):
            out[start + timedelta(hours=i)] = int(value * conv + 0.5)
    return out


def parse_daily(doc) -> list[dict]:
    periods = ((doc or {}).get("properties") or {}).get("periods")
    if not isinstance(periods, list) or not periods:
        raise ValueError("the NWS 7-day forecast had no periods")
    out = []
    for p in periods:
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value")
        out.append({"name": p.get("name") or "", "start": parse_iso(p.get("startTime")),
                    "day": bool(p.get("isDaytime")),
                    "temp_f": _temp_f(p.get("temperature"), p.get("temperatureUnit")),
                    "wind": p.get("windSpeed") or "", "wind_dir": p.get("windDirection") or "",
                    "precip": pop if isinstance(pop, (int, float)) else None,
                    "sky": p.get("shortForecast") or "", "detail": p.get("detailedForecast") or ""})
    return out


def pair_days(periods: list[dict]) -> list[dict]:
    """NWS 12-hour periods -> one row per day: the daytime period with the night after it.
    A forecast that starts at night ("Tonight") gets a row with only a low."""
    rows, i = [], 0
    while i < len(periods):
        p = periods[i]
        night = None
        if p["day"] and i + 1 < len(periods) and not periods[i + 1]["day"]:
            night = periods[i + 1]
        day = p if p["day"] else None
        n = night if day else p
        chances = [x["precip"] for x in (day, n) if x and x.get("precip") is not None]
        rows.append({"name": (day or n)["name"], "hi": day["temp_f"] if day else None,
                     "lo": n["temp_f"] if n else None, "sky": (day or n)["sky"],
                     "night_sky": n["sky"] if (day and n) else "",
                     "precip": max(chances) if chances else None,
                     "wind": (day or n)["wind"], "wind_dir": (day or n)["wind_dir"],
                     "detail": (day or n)["detail"]})
        i += 2 if (day and night) else 1
    return rows


def flags_for(hour: dict, limits=LIMITS) -> list[str]:
    """Plain-words reasons an hour needs a look. Missing values never raise a flag and never pass one."""
    f = []
    if hour.get("gust_mph") is not None and hour["gust_mph"] >= limits["gust_mph"]:
        f.append(f"Gusts {round(hour['gust_mph'])}\u00a0mph")
    if hour.get("wind_mph") is not None and hour["wind_mph"] >= limits["wind_mph"]:
        f.append(f"Wind {round(hour['wind_mph'])}\u00a0mph")
    if hour.get("precip") is not None and hour["precip"] >= limits["pop_pct"]:
        f.append(f"{round(hour['precip'])}% chance of rain or snow")
    if hour.get("temp_f") is not None and hour["temp_f"] < limits["cold_f"]:
        f.append(f"{round(hour['temp_f'])}\u00a0°F")
    if hour.get("temp_f") is not None and hour["temp_f"] > limits["hot_f"]:
        f.append(f"{round(hour['temp_f'])}\u00a0°F")
    return f


def summarize(hours: list[dict], now: datetime, span=12) -> dict:
    """The next `span` hours from now: highs, lows and the first hour that needs a look."""
    upcoming = [h for h in hours if h["start"] + timedelta(hours=1) > now][:span]
    def top(key):
        vals = [h[key] for h in upcoming if h.get(key) is not None]
        return max(vals) if vals else None
    temps = [h["temp_f"] for h in upcoming if h.get("temp_f") is not None]
    flagged = [h for h in upcoming if h.get("flags")]
    return {"hours": len(upcoming), "gust": top("gust_mph"), "wind": top("wind_mph"), "precip": top("precip"),
            "lo": min(temps) if temps else None, "hi": max(temps) if temps else None,
            "flagged": len(flagged), "first_flag": flagged[0] if flagged else None,
            "gusts_known": any(h.get("gust_mph") is not None for h in upcoming)}


# ---------------------------------------------------------------- station readings (D29)

def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def miles_between(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(min(1.0, a)))


def length_ft(q) -> float | None:
    """{"unitCode": "wmoUnit:m", "value": 1088} -> feet. Missing stays None; any other unit is an
    error, never a guess."""
    if not isinstance(q, dict) or not _number(q.get("value")):
        return None
    unit = str(q.get("unitCode") or "").split(":")[-1]
    if unit == "m":
        return q["value"] * M_TO_FT
    if unit == "ft":
        return float(q["value"])
    raise ValueError(f"unexpected elevation unit {q.get('unitCode')!r}")


def grid_elevation_ft(doc) -> float | None:
    """The elevation of a forecast grid square (the gridpoint document's "elevation"), in feet."""
    try:
        return length_ft(((doc or {}).get("properties") or {}).get("elevation"))
    except ValueError:
        return None


def parse_stations(doc, lat, lon, limit=OBS_STATIONS) -> list[dict]:
    """NWS observationStations list -> the `limit` stations nearest (lat, lon), nearest first.

    Never filtered by state (D25: West Yellowstone's nearest stations are in Wyoming). The state
    comes from the station's county zone ("…/zones/county/WYC029" -> "WY"), for the label only."""
    feats = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(feats, list):
        raise ValueError("the NWS station list had no stations")
    out = []
    for f in feats:
        f = f if isinstance(f, dict) else {}
        p = f.get("properties") if isinstance(f.get("properties"), dict) else {}
        coords = (f.get("geometry") or {}).get("coordinates") if isinstance(f.get("geometry"), dict) else None
        sid = p.get("stationIdentifier")
        if not isinstance(sid, str) or not sid or not isinstance(coords, list) or len(coords) < 2 \
                or not (_number(coords[0]) and _number(coords[1])):
            continue
        try:
            elev = length_ft(p.get("elevation"))
        except ValueError:
            elev = None
        zone = str(p.get("county") or p.get("forecast") or "").rstrip("/").rsplit("/", 1)[-1]
        name = str(p.get("name") or sid).strip()
        out.append({"id": sid, "name": name.title() if name.isupper() else name,
                    "lat": coords[1], "lon": coords[0], "elev_ft": elev,
                    "miles": miles_between(lat, lon, coords[1], coords[0]),
                    "state": zone[:2] if len(zone) >= 2 and zone[:2].isalpha() else ""})
    if not out:
        raise ValueError("the NWS station list had no usable stations")
    out.sort(key=lambda s: s["miles"])
    return out[:limit]


_CONVERT = {
    "temp": {"degC": lambda v: v * 9 / 5 + 32, "degF": float},
    "speed": {"km_h-1": lambda v: v * KMH_TO_MPH, "m_s-1": lambda v: v * MS_TO_MPH, "kt": lambda v: v * KT_TO_MPH,
              "mi_h-1": float},
    "angle": {"degree_(angle)": float},
}


def measured(q, kind: str) -> dict:
    """One value of an observation, e.g. {"unitCode": "wmoUnit:degC", "value": 5, "qualityControl": "V"}
    -> {"value": 41.0 (°F, mph or degrees), "qc": "V", "withheld": False, "raw": 5, "unit": ...}.

    Missing stays None. A value flagged X or B is withheld (value None) and kept raw. Any other
    unit is an error, never a guess."""
    if not isinstance(q, dict):
        return {"value": None, "qc": None, "withheld": False, "raw": None, "unit": None}
    raw, unit, qc = q.get("value"), str(q.get("unitCode") or ""), q.get("qualityControl")
    qc = qc if isinstance(qc, str) and qc else None
    value = None
    if _number(raw):
        conv = _CONVERT[kind].get(unit.split(":")[-1])
        if conv is None:
            raise ValueError(f"unexpected {kind} unit {unit!r}")
        value = conv(raw)
    withheld = value is not None and qc in QC_REJECTED
    return {"value": None if withheld else value, "qc": qc, "withheld": withheld, "raw": raw, "unit": unit or None}


_POINTS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def compass(degrees) -> str:
    """190 -> 'S'. Unknown stays ''."""
    return _POINTS[int((degrees % 360) / 22.5 + 0.5) % 16] if _number(degrees) else ""


def parse_observation(doc, now: datetime) -> dict:
    """NWS /stations/{id}/observations/latest -> one reading in °F and mph, with its age.

    A reading older than FRESH_MINUTES is kept and marked stale, never hidden (D25). A missing gust
    beside a measured wind is "no gust reported": airport stations report a gust only when the
    peak beats the sustained wind by a margin. No time, or no readable values, is no reading."""
    p = doc.get("properties") if isinstance(doc, dict) else None
    if not isinstance(p, dict):
        raise ValueError("the station reading was unreadable")
    when = parse_iso(p.get("timestamp"))
    if when is None:
        raise ValueError("the station reading had no time")
    temp, wind = measured(p.get("temperature"), "temp"), measured(p.get("windSpeed"), "speed")
    gust, direction = measured(p.get("windGust"), "speed"), measured(p.get("windDirection"), "angle")
    if all(m["value"] is None and not m["withheld"] for m in (temp, wind, gust)):
        raise ValueError("the latest report had no temperature or wind")
    age = max(0.0, (now - when).total_seconds() / 60)
    try:
        elev = length_ft(p.get("elevation"))
    except ValueError:
        elev = None
    sky = p.get("textDescription")
    return {"time": _iso(when), "age_min": int(age + 0.5), "current": age <= FRESH_MINUTES,
            "temp": temp, "wind": wind, "gust": gust,
            "dir": compass(direction["value"]) if wind["value"] else ("calm" if wind["value"] == 0 else ""),
            "no_gust": gust["value"] is None and not gust["withheld"] and wind["value"] is not None,
            "sky": sky.strip() if isinstance(sky, str) else "", "elev_ft": elev}


def reading_now(stations: list[dict]) -> dict | None:
    """The station a town card quotes: the nearest current reading with a temperature or a wind,
    else the nearest current reading (a road sensor may send only a gust), else the nearest reading
    of any age (shown as stale), else None. Stations come nearest first."""
    read = [s for s in stations if s.get("obs")]
    def core(s):
        return s["obs"]["temp"]["value"] is not None or s["obs"]["wind"]["value"] is not None
    for test in (lambda s: s["obs"]["current"] and core(s), lambda s: s["obs"]["current"], lambda s: True):
        hit = next((s for s in read if test(s)), None)
        if hit:
            return hit
    return None


def age_words(minutes: int | None) -> str:
    """12 -> '12 min ago', 80 -> '1 h 20 min ago', 1500 -> '1 day ago'."""
    if minutes is None:
        return ""
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 24 * 60:
        h, m = divmod(minutes, 60)
        return f"{h} h {m} min ago" if m else f"{h} h ago"
    d = minutes // (24 * 60)
    return f"{d} day{'s' if d > 1 else ''} ago"


# ---------------------------------------------------------------- SPC storm reports

def spc_day_for(dt: datetime) -> date:
    """SPC reporting days run 12:00 UTC to 11:59 UTC the next day."""
    return (dt.astimezone(UTC) - timedelta(hours=12)).date()


def spc_url(day: date, kind: str) -> str:
    return f"{SPC}{day:%y%m%d}_rpts_filtered_{kind}.csv"


def spc_time_to_utc(day: date, hhmm: str) -> datetime:
    s = str(hhmm).strip().zfill(4)
    if not s.isdigit() or len(s) != 4 or int(s[:2]) > 23 or int(s[2:]) > 59:
        raise ValueError(f"bad SPC time {hhmm!r}")
    t = datetime(day.year, day.month, day.day, int(s[:2]), int(s[2:]), tzinfo=UTC)
    return t + timedelta(days=1) if t.hour < 12 else t


def near_montana(lat, lon) -> bool:
    return (MT_BOX[0] - MARGIN <= lat <= MT_BOX[1] + MARGIN
            and MT_BOX[2] - MARGIN <= lon <= MT_BOX[3] + MARGIN)


def parse_spc(text: str, day: date, kind: str) -> list[dict]:
    """SPC filtered CSV -> reports in and near Montana. Hail sizes are hundredths of an inch
    (175 = 1.75 in); wind is mph and 'UNK' stays unknown."""
    if not text or not text.lstrip().startswith("Time,"):
        raise ValueError("the SPC file did not look like a storm-report CSV")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            lat, lon = float(row.get("Lat") or ""), float(row.get("Lon") or "")
            when = spc_time_to_utc(day, row.get("Time", ""))
        except ValueError:
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)) or not near_montana(lat, lon):
            continue
        rep = {"kind": kind, "time": _iso(when), "day": day.isoformat(), "lat": lat, "lon": lon,
               "place": (row.get("Location") or "").strip(), "county": (row.get("County") or "").strip(),
               "state": (row.get("State") or "").strip(), "comments": (row.get("Comments") or "").strip(),
               "size_in": None, "mph": None}
        if kind == "hail":
            raw = str(row.get("Size") or "").strip()
            rep["size_in"] = int(raw) / 100 if raw.isdigit() and int(raw) > 0 else None
        else:
            raw = str(row.get("Speed") or "").strip()
            rep["mph"] = int(raw) if raw.isdigit() else None
        out.append(rep)
    seen, unique = set(), []
    for r in out:
        key = (r["kind"], r["time"], round(r["lat"], 2), round(r["lon"], 2))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ---------------------------------------------------------------- network

class Fetcher:
    """Thin wrapper over requests that never raises: each call returns (value, error text).

    Server errors and dropped connections are retried twice with a short pause; the NWS
    gridpoint endpoints often fail once and then answer."""

    def __init__(self, session=None, timeout=20, attempts=3, pause=1.5):
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.timeout, self.attempts, self.pause = timeout, attempts, pause

    def _get(self, url, params=None, accept=None):
        headers = {"Accept": accept} if accept else {}
        last = None
        for attempt in range(self.attempts):
            if attempt:
                time.sleep(self.pause * attempt)
            try:
                r = self.s.get(url, params=params, headers=headers, timeout=self.timeout)
                if r.status_code == 404:
                    return r, "not published (HTTP 404)"
                if r.status_code >= 500:
                    last = f"server error (HTTP {r.status_code})"
                    continue
                if r.status_code != 200:
                    return r, f"HTTP {r.status_code}"
                return r, None
            except requests.RequestException as e:
                last = type(e).__name__
        return None, last

    def json(self, url, params=None):
        r, err = self._get(url, params, "application/geo+json, application/json")
        if err:
            return None, err
        try:
            return r.json(), None
        except ValueError:
            return None, "the response was not JSON"

    def text(self, url):
        r, err = self._get(url)
        return (None, err) if err else (r.text, None)

    def binary(self, url, headers=None):
        """Raw bytes, for GRIB files and S3 listings. `headers` may carry a Range for one field."""
        last = None
        for attempt in range(self.attempts):
            if attempt:
                time.sleep(self.pause * attempt)
            try:
                r = self.s.get(url, headers=headers or {}, timeout=self.timeout)
                if r.status_code == 404:
                    return None, "not published (HTTP 404)"
                if r.status_code >= 500:
                    last = f"server error (HTTP {r.status_code})"
                    continue
                if r.status_code not in (200, 206):
                    return None, f"HTTP {r.status_code}"
                return r.content, None
            except requests.RequestException as e:
                last = type(e).__name__
        return None, last
