"""Summary (B5 Product, part B1): the five-season table that leads the sheet and the town page, the roof reference lines,
and the words that go with them.

What it is. One table per spot, built from every part of the store: the radar history (B1), the reports, warnings, zone
products and station gusts (B2 and B5 joins), the NCEI point records, the county products (k/), the grid estimates (c/),
the station readings (sd/ and s/) and, on a town page only, the river gauge (g/). Every row names its kind of record
and its unit, and every number carries its unit. Nothing here is a finding about a roof or an address, and no sentence
says damage, risk, a probability, an insurance or eligibility matter, or an all-clear, except the fixed sentence "This is not an all-clear." (AGENTS rule 5; D13).

Rows (the brief's Product section, in its order). Each row is a plain dict: key, label, kind (the kind word), unit,
scale (the store's integer unit: inches in hundredths, degrees F in tenths, otherwise 1), decimals, source (the part),
values (five season integers or None), dates (yyyymmdd or None), texts (the words for each season), coverage (the
"n days missing" line or None), five, five_date, five_text, five_coverage, and notes (plain sentences). A value is an
integer or null, never a zero standing for a missing day (D2, D5). A season with no valid day has value None and the
text "Data unavailable"; a season with some missing days shows its value over the days present and its coverage line.

Seasons are July to June (2021-22 to 2025-26). The partial 2026-27 season is not a column: it is one line below the
table (D20), with its own counts. The radar and report rows cover the trailing 1,826 SPC days (B1 and B2's window), so
2021-22 shows its days before the window start as missing (D3). The snow analysis is not a row: it was checked against
station totals and left out (D7, D23).

Station rules (D5, D18): a station value shows only when at least 95 percent of the season's days have the element,
and the station is named with its distance from this spot. The snow and temperature stations come from the rule at the
spot's own cell centre (the sheet) or, on a town page, at the town point; every station is listed nearest first from
that point. The gust station is the nearer of the tile's two gust stations (B2's list), measured from this spot.

Gust records (B2 s/): a station file's days hold the days at 50 kt or more, and its periods.season[label] holds n (the
season's days) and ok (the days with a gust value). A season shows its gust figures only when ok is at least 95 percent
of n; a file without those counts shows Data unavailable for every gust figure (the interim, D5 and O8).

Zone products (B5 D27): the index's zone_unplaced_rows say which products could not be placed. Their Montana counts mark the
season cells of the same family (a zero there is Data unavailable; a count keeps its value, with the statement); the
reconfigured zones MTZ301 to MTZ330 are partial before September 7, 2022 (the NWS change log).

Thresholds (D1, D19; climate.THRESHOLDS): a 90 F day is a high of 32.15 C or more, rounded to the hundredth, shown as 32.2 C
and 90 F. A freeze-thaw day has a high above 32 F and a low below 32 F. Wind reports are the LSR codes G, D, N, A, O and M
(B2 brief). The town page's river gauge line is the nearest gauge with a flood stage within 10 miles (D6).

Words. WORDS_SUMMARY holds the table, the sheet strings and the section leads; WORDS_INDICATORS holds the 23 roof
indicator lines, the reference lines, the held lines and the roof section's sentences. Both are plain Python strings
with braces for the values; map_data_summary hands the same strings to the browser (part B2 fills them). The forbidden
list is tests/words_rules.py, the one list every word test uses; forbidden_hits() delegates to it.

Public functions:
    describe_summary(store, row, col, now, town=None) -> dict   the table, the roof section, the sections' leads, how made
    map_data_summary(index) -> dict                             the templates, row order, kind words and units for the browser
    forbidden_hits(text) -> list                                the forbidden terms a sentence uses (empty when none)

Failures (D16): a part that did not load in the build (index state "unavailable" or "partial" with no usable file) marks
its rows "Data unavailable" with the sentence the source's own words give (B2 D20); the other rows still build.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from . import climate, gauges, hail, joins, stations

FORMAT = "hail-summary-v1"
FIVE = climate.FIVE_SEASONS                       # ("2021-22", ..., "2025-26")
PARTIAL = climate.SEASONS[-1]                     # "2026-27": one line below the table, not a column (D20)
COLUMNS = FIVE + ("Five seasons",)
ONE_INCH_TENTHS = 254                             # 1.00 in in tenths of a mm (the NWS severe size)
FLOOR_TENTHS = hail.FLOOR_TENTHS                  # 0.25 in: the smallest radar estimate stored
GUST_KT = joins.STATION_KT                        # 50 kt (58 mph): the peak gust rows count days at or above it
WIND_CODES = ("G", "D", "N", "A", "O", "M")       # LSR wind types: gusts, damage, sustained, marine (B2 brief)
TOWN_RADIUS = stations.RADIUS_MILES               # 40 miles: the station candidates
SEASON_SHARE = stations.SEASON_MIN                # 95 percent of a season's days for a station value (D5)
STALE_DAYS = 3                                    # the newest radar day older than this shows the stale line

# ---------------------------------------------------------------- units and row order

UNIT_SPEC = {
    "in": {"scale": 100, "decimals": 2, "word": "inches", "note": "stored as hundredths of an inch"},
    "F": {"scale": 10, "decimals": 1, "word": "degrees Fahrenheit", "note": "stored as tenths of a degree F"},
    "days": {"scale": 1, "decimals": 0, "word": "days", "note": "whole days"},
    "count": {"scale": 1, "decimals": 0, "word": "count", "note": "whole reports, warnings or products"},
    "kt": {"scale": 1, "decimals": 0, "word": "knots", "note": "whole knots; the mph beside it is whole miles per hour"},
    "none": {"scale": 1, "decimals": 0, "word": "none", "note": "Data unavailable lines carry no number"},
}

KIND_RECORD = joins.WORDS_JOINS["kind_record"]                # "Record (NCEI)": the brief's kind word for NCEI records
KIND_WARNING = "Warning (NWS polygon, relayed by IEM)"        # the brief's kind word for a polygon warning
AUTO_SOURCES = ("Mesonet", "ASOS", "AWOS")                    # IEM SOURCE values of automated station reports (every wind count)

# The row order of the table. "town_only" rows are the two station rows a town page adds (D20 of the town brief).
ROWS = (
    {"key": "radar_max", "label": "Largest radar hail estimate at this cell", "kind": "Radar estimate", "unit": "in",
     "source": "B1"},
    {"key": "radar_1in", "label": "Days with a radar hail estimate of 1 inch or more", "kind": "Radar estimate",
     "unit": "days", "source": "B1"},
    {"key": "hail_max", "label": "Largest hail reported within 5 miles", "kind": "Report", "unit": "in",
     "source": "B2"},
    {"key": "hail_n", "label": "Hail reports within 5 miles", "kind": "Report", "unit": "count", "source": "B2"},
    {"key": "gust_days", "label": "Peak gust of 50 knots (58 mph) or more", "kind": "Station reading", "unit": "days",
     "source": "B2"},
    {"key": "gust_max", "label": "Strongest gust at that station", "kind": "Station reading", "unit": "kt",
     "source": "B2"},
    {"key": "wind_n", "label": "Wind reports within 5 miles", "kind": "Report", "unit": "count", "source": "B2"},
    {"key": "hw_zone", "label": "High wind watches and warnings for the zone", "kind": "Zone product", "unit": "count",
     "source": "B2"},
    {"key": "tmax", "label": "Highest temperature", "kind": "Grid estimate", "unit": "F", "source": "B5"},
    {"key": "tmin", "label": "Lowest temperature", "kind": "Grid estimate", "unit": "F", "source": "B5"},
    {"key": "tmax_station", "label": "Highest temperature at the station", "kind": "Station reading", "unit": "F",
     "source": "B5", "town_only": True},
    {"key": "tmin_station", "label": "Lowest temperature at the station", "kind": "Station reading", "unit": "F",
     "source": "B5", "town_only": True},
    {"key": "hot90", "label": "Days with a high of 90 F or more", "kind": "Grid estimate", "unit": "days",
     "source": "B5"},
    {"key": "frost32", "label": "Days with a low below 32 F", "kind": "Grid estimate", "unit": "days", "source": "B5"},
    {"key": "freeze_thaw", "label": "Freeze-thaw days", "kind": "Grid estimate", "unit": "days", "source": "B5"},
    {"key": "precip", "label": "Precipitation", "kind": "Grid estimate", "unit": "in", "source": "B5"},
    {"key": "precip_max", "label": "Largest one-day precipitation", "kind": "Grid estimate", "unit": "in",
     "source": "B5"},
    {"key": "snow", "label": "Snowfall, July to June", "kind": "Station reading", "unit": "in", "source": "B5",
     "decimals": 1},
    {"key": "snow_depth", "label": "Deepest snow on the ground", "kind": "Station reading", "unit": "in",
     "source": "B5", "decimals": 1},
    {"key": "freezing_rain_n", "label": "Freezing rain reports within 5 miles", "kind": "Report", "unit": "count",
     "source": "B2"},
    {"key": "ice_warn", "label": "Winter storm and ice storm warnings", "kind": "Zone product", "unit": "count",
     "source": "B5"},
    {"key": "flood_report_n", "label": "Flood and flash flood reports within 5 miles", "kind": "Report",
     "unit": "count", "source": "B2"},
    {"key": "flood_warn", "label": "Flood and flash flood warnings", "kind": KIND_WARNING, "unit": "count",
     "source": "B2"},
    {"key": "county_watch", "label": "Flood and flash flood watches for the county", "kind": "County product",
     "unit": "count", "source": "B5"},
    {"key": "held", "label": "Lightning, UV and sunlight, roof surface temperature, ponding", "kind": "Data unavailable",
     "unit": "none", "source": "held"},
)
ROW_KEYS = tuple(r["key"] for r in ROWS)

KIND_WORDS = (
    {"word": "Radar estimate", "means": "A radar-derived hail size estimate for a cell (NOAA MRMS MESH). Not a measurement at the ground."},
    {"word": "Radar detection", "means": "A hail signature the radar algorithm flagged (NCEI SWDI). Not hail on the ground."},
    {"word": "Report", "means": "What a spotter, a member of the public or a sensor sent to the National Weather Service (IEM local storm reports). Not a complete record and not an inspection."},
    {"word": KIND_RECORD, "means": "A NOAA Storm Events entry (NCEI). An event count, not a measurement at this address."},
    {"word": KIND_WARNING, "means": "A National Weather Service warning polygon that covered this cell or part of it (IEM archive). The tags are the forecast threat at issue time."},
    {"word": "Zone product", "means": "A National Weather Service product for a whole forecast zone, not this spot alone."},
    {"word": "County product", "means": "A National Weather Service product for a whole county, not this spot alone."},
    {"word": "Station reading", "means": "An observation at a named station, with its distance. Not a reading at this address."},
    {"word": "Grid estimate", "means": "A gridded estimate for a cell about 4.6 km across (NOAA nClimGrid-Daily). Not a reading at this address."},
    {"word": "River gauge", "means": "A river gauge's own flood stage and annual peaks. It does not say water reached this address."},
    {"word": "Reference", "means": "A statement from a public source about a stress on roofs. Not a finding about this address and not what a roof needs."},
    {"word": "Data unavailable", "means": "The source does not cover this place, this element or this time, or did not load. It is never shown as zero."},
)

# ---------------------------------------------------------------- sheet words (templates: braces are filled in Python;
# the browser fills the same strings)

WORDS_SUMMARY = {
    "plain": ("Five seasons of weather for this spot, from grid estimates, station readings and NWS records. Each row "
              "says what kind of record it is."),
    "table_title": "Five seasons, July to June",
    "radar_sentence": joins.WORDS_JOINS["radar_sentence"],
    "days": "{n} days",
    "in_on": "{inches} in on {date}",
    "in_plain": "{inches} in",
    "f_on": "{f} F on {date}",
    "f_plain": "{f} F",
    "gust": "{kt} kt ({mph} mph) on {date}",
    "gust_flagged": "{kt} kt ({mph} mph) on {date}, flagged for check",
    "station_days_one": "1 day at {station}",
    "station_days": "{n} days at {station}",
    "snow_at": "{inches} in at {station}",
    "snow_depth_at": "{inches} in on {date} at {station}",
    "temp_at": "{f} F on {date} at {station}",
    "none_radar": "No radar estimate of 0.25 in or more",
    "class_counts": "Radar days by size class in these five seasons: {items}.",
    "zero_unknown": "Data unavailable: some products could not be placed to a zone. This is not an all-clear.",
    "automated_one": "Of these {kind} in these five years, 1 is an automated station report (Mesonet, ASOS or AWOS), not a spotter report.",
    "automated_note": "Of these {kind} in these five years, {n} are automated station reports (Mesonet, ASOS or AWOS), not spotter reports.",
    "auto_roof_one": "; 1 is an automated station report (Mesonet, ASOS or AWOS), not a spotter report",
    "auto_roof_many": "; {n} are automated station reports (Mesonet, ASOS or AWOS), not spotter reports",
    "auto_lead": ", {n} of them automated",
    "auto_partial": " ({n} of them automated)",
    "gust_coverage_note": ("Only days of 50 kt or more are kept from each station's record, not its full daily record, so a 0 "
                           "means no such day among the days the station reported; it does not show that the station was calm."),
    "snotel_station": "{station} is a SNOTEL site. It reports snow depth, not snowfall.",
    "five_partial": "{count} in the seasons shown, not counting {seasons}",
    "zone_unplaced_note": ("Montana had {parts} that could not be placed to a zone, because their zone codes are not in the "
                           "zone maps this build reads. This build cannot say how many were this zone's. This is not an "
                           "all-clear."),
    "zone_flag": "Montana: {n} {noun} issued {when} could not be placed to a zone",
    "zone_reconfigured": ("This zone was reconfigured on {date} (NWS change log). This build has no placed product for it "
                          "before {first}, and its earlier products are not in the data."),
    "zone_reconfigured_none": ("This zone was reconfigured on {date} (NWS change log). This build has no placed product for "
                               "it, and its earlier products are not in the data."),
    "zone_before_change": ("Partial: {n} days before {date} not covered; this zone was reconfigured on {date} (NWS change log)"),
    "zone_before_change_all": ("Not covered: products before {date} are not in the data; this zone was reconfigured on {date} "
                               "(NWS change log)"),
    "none_hail": "No report of hail within 5 miles",
    "none_gust": "No day at 50 kt or more",
    "gust_floor_note": ("Only days with a gust of 50 kt or more are kept from each station's record, so a season with no such "
                        "day shows no value rather than a lower gust."),
    "gust_interim": ("Data unavailable: the gust record for {station} does not yet say how many of its days have a value, so "
                     "no gust count or maximum is shown; a missing value is not zero. This is not an all-clear."),
    "gust_season_short": ("Data unavailable: {station} has {k} of {d} days with a gust value, so this season is not shown; a "
                          "missing value is not zero. This is not an all-clear."),
    "none_station": "Data unavailable: no station has enough reports",
    "station_short": ("Data unavailable: {station} has {k} of {d} days with a {element} value, so this season is not shown; "
                      "a missing value is not zero. This is not an all-clear."),
    "coverage": "{n} days missing",
    "cell_unavailable": "Data unavailable",
    "season_unavailable": ("Data unavailable for {season}: no day of this season is in the {source}. This is not an "
                           "all-clear."),
    "five_unavailable": ("Data unavailable for the five seasons: {season} {verb} no usable value, so no five-season figure "
                         "is shown. This is not an all-clear."),
    "five_unavailable_all": ("Data unavailable for the five seasons: no season has a usable value, so no five-season figure "
                             "is shown. This is not an all-clear."),
    "five_stations": "{total}; {count} stations: {runs}",
    "passed_over": ("{station} has {pct} percent of the {season} days ({ok} of {n}), under the 95 percent rule, so {chosen} "
                    "is shown."),
    "station_season": ("Data unavailable for {season}: {station} has {k} of {d} days with a {element} value, so this "
                       "season is not shown; a missing value is not zero. This is not an all-clear."),
    "station_none": "No station within 40 miles has enough reports for {element} from 2020 to 2025.",
    "station_rule_town": ("Stations: the two nearest that have enough days with the element, measured from the town point. A "
                          "station value shows only when 95 percent of its season's days have the element."),
    "station_rule_spot": ("Stations: the two nearest from this spot that have enough days with the element. Distances are "
                          "from this spot."),
    "station_named": "{station}, {miles} miles from this spot",
    "station_named_town": "{station}, {miles} miles from the town",
    "gust_station": "Gust station: {station}, {miles} miles from this spot (the nearer of this tile's two gust stations).",
    "gust_none": "No station within 40 miles has gust records for this tile.",
    "window_radar": ("Radar history: {first} to {last}, 1,826 storm-report days (each from 12:00 to 12:00 UTC) ending {as_of}. "
                     "Days before {first} are not in it, so {season} shows them as missing."),
    "window_reports": ("Reports, warnings, zone products and gusts: {first} to {last} (the same 1,826 storm-report days). Days "
                       "before {first} are not in them."),
    "window_grid": ("Grid estimates: from July 1, 2021 to the newest grid day, {through}. Scaled months are NOAA's monthly "
                    "values; the newest days are preliminary."),
    "window_station": "Station readings: each season shows its days from the station's own record (2021-22 onward).",
    "partial_none": "No day of the {season} season is in the data yet. This is not an all-clear.",
    "partial_counts": ("Reports so far in {season} within 5 miles: {hail} hail {hail_word}, {wind} wind {wind_word}{auto}, "
                       "{flood} flood or flash flood {flood_word}. Radar estimate: {r1} {r1_word} with hail of 1 inch or "
                       "more so far."),
    "stale": "The newest radar day in this history is {as_of}; newer days have not been added yet. This is not an all-clear.",
    "unavailable_part": "{part} could not be loaded in this update; that is not the same as no {part_lower}. This is not an all-clear.",
    "lead_hail": "Radar estimate: {radar} with hail of 1 inch or more; Report: {reports} within 5 miles, in these five years.",
    "lead_wind": "Station reading: {gust} with a gust of 50 kt or more at {station}; Report: {wind} within 5 miles{auto}.",
    "lead_wind_unavailable": ("Station reading: Data unavailable for the days with a gust of 50 kt or more at {station}; Report: "
                              "{wind} within 5 miles{auto}. This is not an all-clear."),
    "lead_storms": "Zone product: {hw}; Warning: {sv} covered this cell or part of it.",
    "lead_temperature": "Grid estimate: highest {tmax}; lowest {tmin}, in these five seasons.",
    "lead_rain": ("Grid estimate: {precip} of precipitation in these five seasons, rain and melted snow together; the largest "
                  "one day {pmax}."),
    "lead_snow": "Station reading: {snow} of snowfall in the five seasons (the station named in each season); the deepest snow on the ground {depth}.",
    "lead_snow_two": ("Station reading: {snow} of snowfall in the five seasons, from {count} stations (the station named in each "
                      "season); the deepest snow on the ground {depth}."),
    "lead_flood": "Report: {flood} within 5 miles; Warning: {flood_w} covered this cell or part of it, in these five years.",
    "lead_ice": "Report: {fr} within 5 miles; Zone product: {ice}.",
    "lead_heat": "Grid estimate: {hot} with a high of 90 F or more in these five seasons; Report: {xheat} within 5 miles.",
    "lead_roof": ("Each line is a count or a measurement with its kind word, from the same records as the table; none of "
                  "them says what a roof needs."),
    "lead_made": "Where each number comes from, the distance and enough-days rules, the units and the licence sentences.",
    "section_titles": {
        "hail": "Hail", "wind": "Wind", "storms": "Storms and warnings", "temperature": "Temperature", "rain": "Rain",
        "snow": "Snow", "flooding": "Flooding", "ice": "Ice and winter", "heat": "Heat",
        "roof": "Weather that matters for a roof", "made": "How this was made",
    },
    "gauge_none": ("No gauge with an NWS flood stage is within 10 miles of {place}. That is not a statement that the river "
                   "did not flood there."),
    "analysis_held": ("The NOAA National Snow Analysis was checked against station season totals and left out: its amounts "
                      "did not match the station totals closely enough to show."),
}

WORDS_INDICATORS = {
    "section_lead": ("Weather that matters for a roof. These are weather conditions that roofing and building references "
                     "name as stresses on roofs. Each line says what the weather record shows near this spot and what kind "
                     "of record it is. Nothing here is a finding about any roof, and a count of days is not a count of "
                     "problems."),
    "kind_key": "Kind words: " + ", ".join(k["word"] for k in KIND_WORDS) + ".",
    "what_reports": ("A report is what a spotter, a member of the public or a sensor sent to the National Weather Service. A "
                     "report is not an inspection and not a finding about a roof. No report is not a finding that nothing "
                     "happened; reports are not a complete record."),
    "what_warnings": ("A warning is the National Weather Service polygon that covered this cell or part of it at issue time. Its tags are "
                      "the forecast threat, not what fell."),
    "what_station": "A station reading is at a named airport or cooperative site, with its distance. It is not a reading at this address.",
    "what_grid": ("A grid estimate is a gridded analysis of station observations for a cell about 4.6 km across (NOAA "
                  "nClimGrid-Daily). It is not a reading at this address."),
    "indicator_unavailable": "{label}. {why}",
    "lines": {
        "hail_size_days": ("Radar estimate: {count} with hail of 1 inch or more in these five years; the largest radar "
                           "estimate was {largest}."),
        "hail_reports": "Report: {count} within 5 miles in these five years; the largest hail reported was {largest}.",
        "hail_signatures": ("Radar detection: {count} within 2 miles in these five years; the detection list is not a "
                            "complete inventory."),
        "hail_warnings": "Warning: {count} covered this cell or part of it in these five years.",
        "wind_gust_days": ("Station reading: {count} with a peak gust of 50 knots (58 mph) or more in these five years at "
                           "{station}, {miles} miles from this spot."),
        "wind_reports": "Report: {count} within 5 miles in these five years{auto}.",
        "wind_zone_warnings": "Zone product: {count} for the zone in these five years.",
        "tornado_funnel": ("Report: {count} within 5 miles; Record: {count_nc}; Warning: {count_w} covered this cell or part of "
                           "it."),
        "freeze_thaw_days": "Grid estimate: {count} in these five seasons (a high above 32 F and a low below 32 F).",
        "days_low_below_32": "Grid estimate: {count} with a low below 32 F in these five seasons.",
        "days_high_90": ("Grid estimate: {count} with a high of 90 F or more in these five seasons (a site threshold, not an "
                         "NWS heat criterion)."),
        "temperature_extremes": "Grid estimate: highest {hi}; lowest {lo}, in these five seasons.",
        "snowfall_season": "Station reading: {total} of snowfall in the five seasons (the station named in each season).",
        "snow_depth": "Station reading: the deepest snow on the ground was {largest} in these five seasons.",
        "ice_dam_weather_days": ("Station reading: {count} with 1 inch or more of snow on the ground and a low below 32 F in "
                                 "these five seasons (weather that can form ice dams, not a count of ice dams)."),
        "freezing_rain_reports": "Report: {count} within 5 miles in these five years.",
        "ice_storm_warnings": "Zone product: {count} for the zone in these five years.",
        "winter_storm_warnings": "Zone product: {count} for the zone in these five years.",
        "precipitation_year": ("Grid estimate: {total} of precipitation in these five seasons: rain and the water from melted "
                               "snow. Snow counts here as water, not depth."),
        "largest_one_day_rain": "Grid estimate: largest one-day precipitation {largest} in these five seasons.",
        "rain_reports": "Report: {count} within 5 miles in these five years.",
        "flood_reports_warnings": "Report: {count} within 5 miles in these five years; Warning: {count_w} covered this cell or part of it.",
        "heat_reports_warnings": ("Zone product: {count_h} and {count_e} for the zone; Report: {count_x} within 5 miles; counts "
                                  "for these five years."),
        "heat_reports_warnings_partial": ("Zone product: {count_h}; {count_e} for the zone; Report: {count_x} within 5 miles; "
                                          "counts for these five years."),
    },
    "held": {
        "ponding": "Roof ponding: Data unavailable. No public weather record shows water on a roof.",
        "lightning": ("Lightning: Data unavailable. The national lightning network is commercial, and no free record of "
                      "lightning at this spot was used."),
        "uv_and_sun": "UV and sunlight: Data unavailable. No public UV or sunlight record for this spot was used in this history.",
        "roof_surface_temperature": ("Roof surface temperature: Data unavailable at this spot. Published roof temperatures "
                                     "come from test roofs, not from weather stations."),
        "fema_flood_zones": ("Flood zones (FEMA): Data unavailable. A FEMA flood zone is a regulatory map designation, not a "
                             "weather record, so it is not shown in this history."),
        "ground_snow_load": ("Ground snow load: Data unavailable. A design map value is not a measurement of snow on the "
                             "ground at this spot, so it is not shown."),
        "snotel": ("SNOTEL: Data unavailable. The NRCS SNOTEL service is not used in this history; the station records in "
                   "the GHCN files are the only station readings used."),
    },
    "refs": {
        "thresholds": ("R1", "R3", "R4", "R19"),
        "snow_and_ice": ("R5", "R6", "R7", "R10", "R11"),
        "wind_and_hail": ("R14", "R15"),
        "heat_and_rain": ("R8", "R12", "R16"),
        "lightning_and_sun": ("R18",),
    },
    "how_made_roof": [
        "Each roof line is a count or measurement from the same records as the table, over these five seasons.",
        "The thresholds are the ones stated on this page: 90 F, 32 F and 1 inch, as the grid and the station rules count them.",
        "The reference lines quote public sources in their own words; they are reference statements, not findings about this spot.",
    ],
}


# The reference lines: one quote per stressor from the public source the roof record names (verbatim, as its evidence
# quotes them). Kind "Reference" on every line. The url is the page the record fetched.
REFERENCE_LINES = {
    "R1": {"group": "thresholds", "source": "NWS Storm Prediction Center, severe thunderstorm FAQ", "url": "https://www.spc.noaa.gov/faq/",
           "quote": "A severe thunderstorm refers to a thunderstorm producing hail that is at least 1 inch in diameter or larger, and/or wind gusts of 58 mph or greater, and/or a tornado."},
    "R3": {"group": "thresholds", "source": "NWS Storm Data directive 10-1605", "url": "https://www.weather.gov/media/directives/010_pdfs/pd01016005curr.pdf",
           "quote": "Maximum sustained winds or wind gusts (measured or estimated) equal to or greater than 50 knots (58 mph) will always be entered."},
    "R4": {"group": "thresholds", "source": "NWS Storm Data directive 10-1605", "url": "https://www.weather.gov/media/directives/010_pdfs/pd01016005curr.pdf",
           "quote": "all reports of hail that is 3/4 of an inch or larger in diameter will be entered."},
    "R19": {"group": "thresholds", "source": "earthkit-climate, freeze-thaw cycles", "url": "https://earthkit-climate.readthedocs.io/en/latest/autoapi/earthkit/climate/indicators/daily_freezethaw_cycles.html",
            "quote": "A freeze-thaw cycle is defined as a day where maximum daily temperature is above a given threshold and minimum daily temperature is at or below a given threshold, usually 0°C for both."},
    "R5": {"group": "snow_and_ice", "source": "NWS Storm Data directive 10-1605 (heavy snow)", "url": "https://www.weather.gov/media/directives/010_pdfs/pd01016005curr.pdf",
           "quote": "Snow accumulation meeting or exceeding locally/regionally defined 12 and/or 24 hour warning criteria."},
    "R6": {"group": "snow_and_ice", "source": "NWS Storm Data directive 10-1605 (ice storm)", "url": "https://www.weather.gov/media/directives/010_pdfs/pd01016005curr.pdf",
           "quote": "Ice accretion meeting or exceeding locally/regionally defined warning criteria (typical value is 1/4 or 1/2 inch or more)."},
    "R7": {"group": "snow_and_ice", "source": "NWS glossary, ice storm warning", "url": "https://forecast.weather.gov/glossary.php?word=ice%20storm%20warning",
           "quote": "significant and possibly damaging accumulation of ice"},
    "R10": {"group": "snow_and_ice", "source": "Building America Solution Center (ice dam prevention)", "url": "https://basc.pnnl.gov/resource-guides/construct-roofs-and-attics-ice-dam-prevention",
            "quote": "Ice dams occur if snow is present on a roof and the roof deck under that snow reaches above freezing temperatures."},
    "R11": {"group": "snow_and_ice", "source": "NDSU Extension news release, January 2023", "url": "https://www.ag.ndsu.edu/news/newsreleases/2023/january/reduce-ice-dam-and-icicle-damage",
            "quote": "Ice dams and icicles are most common when snow is on the roof, heat is being lost through the roof and outdoor temperatures are just below freezing."},
    "R14": {"group": "wind_and_hail", "source": "FEMA P-804 Wind Retrofit Guide (map note)", "url": "https://www.wbdg.org/FFC/DHS/fema_p_804.pdf",
            "quote": "Note that the map is for illustration purposes only and should not be used to determine (basic) design wind speed."},
    "R15": {"group": "wind_and_hail", "source": "IBHS, hail and impact-resistant shingles", "url": "https://ibhs.org/hail-impact-resistant-shingle-ratings/",
            "quote": "Hail is one of the most damaging threats to homes."},
    "R8": {"group": "heat_and_rain", "source": "NWS Storm Data directive 10-1605 (heat)", "url": "https://www.weather.gov/media/directives/010_pdfs/pd01016005curr.pdf",
           "quote": "A Heat event occurs and is reported in Storm Data whenever heat index values meet or exceed locally/regionally established advisory thresholds."},
    "R12": {"group": "heat_and_rain", "source": "Asphalt Roofing Manufacturers Association, ponding water", "url": "https://www.asphaltroofing.org/ponding-water-basics/",
            "quote": "Ponding water is defined as the water which remains on a roof 48 hours or longer."},
    "R16": {"group": "heat_and_rain", "source": "IBHS, 2016 shingle temperature test report", "url": "https://ibhs.org/wp-content/uploads/member_docs/IBHS-Roof-Aging-Program-2016-Report_IBHS.pdf",
            "quote": "In general, maximum shingle temperatures of 170°-195°F were observed for the IBHS site (one specimen reached 198.5°F)"},
    "R18": {"group": "lightning_and_sun", "source": "NASA Earthdata, National Lightning Detection Network", "url": "https://www.earthdata.nasa.gov/data/platforms/land-based-platforms/nldn",
            "quote": "National Lightning Detection Network (NLDN) is a commercial lightning detection network operated by Vaisala."},
}

GROUPS = (("thresholds", "Thresholds"), ("snow_and_ice", "Snow and ice"), ("wind_and_hail", "Wind and hail"),
          ("heat_and_rain", "Heat and rain"), ("lightning_and_sun", "Lightning and sun"))

# Which of the 23 indicator lines sits under which group (the stressor it measures).
INDICATOR_GROUPS = {
    "thresholds": ("hail_size_days", "wind_gust_days", "days_high_90", "days_low_below_32", "freeze_thaw_days",
                   "ice_dam_weather_days"),
    "snow_and_ice": ("snowfall_season", "snow_depth", "freezing_rain_reports", "ice_storm_warnings",
                     "winter_storm_warnings"),
    "wind_and_hail": ("hail_reports", "hail_signatures", "hail_warnings", "wind_reports", "wind_zone_warnings",
                      "tornado_funnel"),
    "heat_and_rain": ("precipitation_year", "largest_one_day_rain", "rain_reports", "flood_reports_warnings",
                      "heat_reports_warnings", "temperature_extremes"),
    "lightning_and_sun": (),
}
HELD_GROUPS = {"heat_and_rain": ("ponding", "roof_surface_temperature", "fema_flood_zones"),
               "lightning_and_sun": ("lightning", "uv_and_sun"),
               "snow_and_ice": ("ground_snow_load", "snotel")}

# the zone-coded roof counts (their five-season total may be partial while zone products are unplaced)
ZONE_EXTRA = {"heat_advisory": "heat_advisory", "excessive_heat": "excessive_heat", "ice_storm": "ice_storm",
              "winter_storm": "winter_storm"}

# D13: the forbidden terms live in tests/words_rules.py, the one list every word test uses. "damage" is allowed only as a
# source type word, in quoted wording, or as "NWS damage threat tag"; "structure" only in proper names.


def forbidden_hits(text: str) -> list[str]:
    """The forbidden terms in one sentence, from tests/words_rules.py (the list the tests scan with): its stems after the
    allowed wording is removed (quotes, the two exempt phrases, the NWS damage threat tag, the source type words), and
    "no hail" outside its one allowed sentence. Only the tests call it; the list is imported when it is used."""
    import words_rules                      # the test folder's list (discover -s tests puts it on sys.path)
    hits = list(words_rules.forbidden_words(text))
    if words_rules.has_no_hail(text):
        hits.append("no hail")
    return sorted(set(hits))


# ---------------------------------------------------------------- small helpers

class SummaryError(Exception):
    """A part of the store the summary cannot read. The message is plain words, lower case, with no full stop."""


_JSON_CACHE: dict = {}


def _read_json(path: Path):
    """A store file as JSON, cached by its path, size and modification time. None when the file is missing or cannot be
    read (the caller says which part that is). The cached document is shared: callers never change it."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _JSON_CACHE:
        return _JSON_CACHE[key]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if len(_JSON_CACHE) > 96:
        _JSON_CACHE.clear()
    _JSON_CACHE[key] = doc
    return doc


def season_bounds(label: str) -> tuple[date, date]:
    y = int(label[:4])
    return date(y, 7, 1), date(y + 1, 6, 30)


def window_store(label: str, first: date, last: date) -> tuple[int, int]:
    """(days of the season, days of the season inside the window [first, last]) for one season label."""
    start, end = season_bounds(label)
    total = (end - start).days + 1
    lo, hi = max(start, first), min(end, last)
    return total, ((hi - lo).days + 1 if hi >= lo else 0)


def _fmt_date(day: date) -> str:
    return hail.fmt_date(day)


def _yyyymmdd(day: date | None) -> int | None:
    return None if day is None else int(day.strftime("%Y%m%d"))


def _from_yyyymmdd(value) -> date | None:
    if value is None:
        return None
    text = str(int(value))
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _in_text(hundredths: int) -> str:
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def _hundredths_of_tenths_mm(tenths_mm: int) -> int:
    """Tenths of a mm to hundredths of an inch, rounded down (the same rule as the radar sizes: hail.inches)."""
    return (100 * int(tenths_mm)) // hail.TENTHS_PER_INCH


def _hundredths_from_decimal(text) -> int | None:
    """An LSR magnitude as written ("1.25") to hundredths of an inch; None when it is not a number (for example "None")."""
    try:
        value = Decimal(str(text).strip())
    except Exception:
        return None
    if not value.is_finite() or value < 0:
        return None
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _miles(lat1, lon1, lat2, lon2) -> float:
    return stations.haversine_miles(lat1, lon1, lat2, lon2)


def _town_from(town) -> dict | None:
    """A town as a dict with slug, name, lat, lon: from a dict, or from towns.json by slug."""
    if town is None:
        return None
    if isinstance(town, dict):
        return {"slug": town["slug"], "name": town.get("name", town["slug"]), "lat": float(town["lat"]),
                "lon": float(town["lon"])}
    for entry in json.loads(stations.TOWNS_FILE.read_text(encoding="utf-8")):
        if entry["slug"] == town:
            return {"slug": entry["slug"], "name": entry["name"], "lat": float(entry["lat"]), "lon": float(entry["lon"])}
    raise SummaryError(f"the town {town} is not in towns.json")


# ---------------------------------------------------------------- nouns, cells and the five-season figure

NOUNS = {
    "sv": ("severe thunderstorm warning", "severe thunderstorm warnings"),
    "xheat": ("extreme heat report", "extreme heat reports"),
    "hail_n": ("hail report", "hail reports"),
    "wind_n": ("wind report", "wind reports"),
    "freezing_rain_n": ("freezing rain report", "freezing rain reports"),
    "rain_n": ("rain report", "rain reports"),
    "flood_report_n": ("flood or flash flood report", "flood or flash flood reports"),
    "flood_warn": ("flood or flash flood warning", "flood or flash flood warnings"),
    "hw_zone": ("high wind watch or warning", "high wind watches and warnings"),
    "ice_warn": ("winter storm or ice storm warning", "winter storm and ice storm warnings"),
    "county_watch": ("county flood or flash flood watch", "county flood or flash flood watches"),
    "heat_advisory": ("heat advisory", "heat advisories"),
    "excessive_heat": ("excessive heat warning", "excessive heat warnings"),
    "ice_storm": ("ice storm warning", "ice storm warnings"),
    "winter_storm": ("winter storm warning", "winter storm warnings"),
    "tornado": ("tornado, funnel cloud or landspout report", "tornado, funnel cloud or landspout reports"),
    "tornado_nc": ("NCEI tornado or funnel cloud record", "NCEI tornado or funnel cloud records"),
    "tor_warn": ("tornado warning", "tornado warnings"),
    "signature": ("day with a hail signature", "days with a hail signature"),
    "freeze": ("freeze-thaw day", "freeze-thaw days"),
}


def _count_text(key: str, n: int) -> str:
    """The words for a count: "1 hail report", "3 hail reports", "2 days" (the row's kind word is shown beside it)."""
    if key in NOUNS:
        one, many = NOUNS[key]
        return f"{n} {one if n == 1 else many}"
    return f"{n} {'day' if n == 1 else 'days'}"


def _fmt_in_on(hundredths: int, date_: int | None) -> str:
    """Hundredths of an inch with its date when it has one: "1.25 in on Jun 15, 2025"."""
    if date_:
        return WORDS_SUMMARY["in_on"].format(inches=_in_text(hundredths), date=_fmt_date(_from_yyyymmdd(date_)))
    return WORDS_SUMMARY["in_plain"].format(inches=_in_text(hundredths))


def _fmt_f_on(tenths_f: int, date_: int | None) -> str:
    text = climate._tenths_f_text(tenths_f)
    if date_:
        return WORDS_SUMMARY["f_on"].format(f=text, date=_fmt_date(_from_yyyymmdd(date_)))
    return WORDS_SUMMARY["f_plain"].format(f=text)


def _missing_text(n: int) -> str:
    """The coverage line for missing days: "1 day missing", "108 days missing"."""
    return "1 day missing" if n == 1 else WORDS_SUMMARY["coverage"].format(n=n)


def _cover(missing: int, flag: str | None = None) -> str | None:
    """The coverage line: the days missing (when there are any) and a zone's statements (which carry no full stop of their
    own; the line ends with one). None when there is neither."""
    if flag:
        parts = ([_missing_text(int(missing))] if missing else []) + [flag]
        return "; ".join(parts) + "."
    return _missing_text(int(missing)) if missing else None


def _joined_flags(cells: list[dict]) -> str | None:
    """The distinct zone statements of the cells, in season order."""
    seen: list[str] = []
    for c in cells:
        if c.get("flag") and c["flag"] not in seen:
            seen.append(c["flag"])
    return "; ".join(seen) or None


def _cell(value=None, text=None, date_=None, valid=0, missing=0, station=None, miles=None, sid=None, flag=None,
          unknown=False) -> dict:
    """One season's figure: the value (an integer, or None when no valid day carries it), its date (yyyymmdd), the words,
    the valid days and the days missing. A missing day is never counted as zero. The coverage line is set whenever days
    are missing, with or without a value: a value-less season's words do not say how many days are missing (brief lines
    98-99). flag is a zone's statement that some of its products could not be placed; unknown marks a season whose count
    is not known at all (the gust rule), which the five-season figure cannot use."""
    return {"value": None if value is None else int(value), "date": date_, "text": text, "valid": int(valid),
            "missing": int(missing), "station": station, "miles": miles, "sid": sid, "flag": flag,
            "unknown": bool(unknown), "coverage": _cover(int(missing), flag)}


def _unavailable_cell(text: str | None = None) -> dict:
    return _cell(text=text or WORDS_SUMMARY["cell_unavailable"])


def _five_unavailable_text(bad: list[str]) -> str:
    if len(bad) == len(FIVE):
        return WORDS_SUMMARY["five_unavailable_all"]
    return WORDS_SUMMARY["five_unavailable"].format(season=", ".join(bad), verb="has" if len(bad) == 1 else "have")


def _five(cells: list[dict], combine: str, fmt, source: str, none_text: str) -> dict:
    """The five-season figure from the five season cells.

    "sum": every season must have a valid day and a value, else None with the five-season sentence (a total never
    leaves a season out); the text is fmt(total) (or the plain number). "max" or "min": the extreme of the seasons that
    have one, with its own season text (the date and the station are in that text); the earliest season wins a tie.
    none_text when no season has one. The coverage is the days missing over the five seasons."""
    missing_total = sum(c["missing"] for c in cells)
    coverage = _cover(missing_total, _joined_flags(cells))
    unknown = [FIVE[k] for k, c in enumerate(cells) if c.get("unknown")]
    if unknown:
        return {"value": None, "date": None, "text": WORDS_SUMMARY["cell_unavailable"], "coverage": coverage,
                "note": _five_unavailable_text(unknown)}
    if combine == "sum":
        bad = [FIVE[k] for k, c in enumerate(cells) if c["valid"] <= 0 or c["value"] is None]
        if bad:
            return {"value": None, "date": None, "text": WORDS_SUMMARY["cell_unavailable"], "coverage": coverage,
                    "note": _five_unavailable_text(bad)}
        total = sum(c["value"] for c in cells)
        text = fmt(total) if fmt else str(total)
        return {"value": total, "date": None, "text": text, "coverage": coverage, "note": None}
    present = [c for c in cells if c["value"] is not None]
    if not present:
        return {"value": None, "date": None, "text": none_text, "coverage": coverage, "note": None}
    pick = max if combine == "max" else min
    best_value = pick(c["value"] for c in present)
    best = min((c for c in present if c["value"] == best_value),
               key=lambda c: (c["date"] is None, c["date"] or 0))
    return {"value": best_value, "date": best["date"], "text": best["text"], "coverage": coverage, "note": None}


def _row(spec: dict, cells: list[dict], five: dict, notes: list[str]) -> dict:
    """A table row as a plain dict (the module docstring lists its keys). stations names each season's station; five_note
    is the five-season figure's own sentence (or None); automated (wind and hail reports) is set by the report rows."""
    unit = UNIT_SPEC[spec["unit"]]
    out = {"key": spec["key"], "label": spec["label"], "kind": spec["kind"], "unit": spec["unit"],
           "scale": unit["scale"], "decimals": spec.get("decimals", unit["decimals"]), "source": spec["source"],
           "town_only": bool(spec.get("town_only")),
           "values": [c["value"] for c in cells], "dates": [c["date"] for c in cells],
           "texts": [c["text"] for c in cells], "coverage": [c["coverage"] for c in cells],
           "stations": [c.get("station") for c in cells],
           "five": five["value"], "five_date": five["date"], "five_text": five["text"],
           "five_coverage": five["coverage"], "five_note": five.get("note"), "notes": [n for n in notes if n]}
    if five.get("note"):
        out["notes"].append(five["note"])
    return out


def _unavailable_row(spec: dict, sentence: str) -> dict:
    """A row whose part did not load (D16): no figure in any season and the part's own sentence as its note."""
    cells = [_unavailable_cell() for _ in FIVE]
    five = {"value": None, "date": None, "text": WORDS_SUMMARY["cell_unavailable"], "coverage": None, "note": None}
    return _row(spec, cells, five, [sentence])


def _spec(key: str) -> dict:
    for row in ROWS:
        if row["key"] == key:
            return row
    raise KeyError(key)


def _block(index: dict, name: str) -> dict:
    block = index.get(name)
    return block if isinstance(block, dict) else {}


# ---------------------------------------------------------------- the spot: its files, read once

class _Spot:
    """One spot (a B1 cell) and the parts of the store its rows read. On a town page the station rule runs at the town
    point and the gauge line is read; on the sheet the rule runs at the spot's 0.1 degree tile centre (the build ran the
    same rule for every tile centre), and every distance is from the spot itself."""

    def __init__(self, root: Path, index: dict, row: int, col: int, town: dict | None):
        self.root = root
        self.index = index
        self.row, self.col = row, col
        self.lat, self.lon = hail.cell_centre(row, col)
        self.key = hail.cell_key(row, col)
        self.tile = hail.tile_name(row // hail.TILE, col // hail.TILE)
        self.first, self.last = (date.fromisoformat(x) for x in index["window"])
        self.as_of = date.fromisoformat(index["as_of"])
        self.missing = {date.fromisoformat(d) for d in index.get("missing_days", [])}
        self.town = town
        if town:
            self.station_point = (town["lat"], town["lon"])
            self.anchor = (town["lat"], town["lon"])
        else:
            self.station_point = (self.lat, self.lon)      # the sheet's station rule runs at the spot's own cell centre
            self.anchor = (self.lat, self.lon)
        self.jb = _block(index, "joins")
        self.cb = _block(index, "climate")
        self.sb = _block(index, "stations")
        self.gb = _block(index, "gauges")
        self.gust = None                  # set by the gust rows: {"name", "miles"} of the gust station
        self.gauge_problem = None         # set by gauge_line when the river gauge line could not be read (D16)
        self._unplaced_cache = None
        self._tile_doc = None
        self._tile_loaded = False

    def unplaced_index(self) -> dict:
        """(family, season label) -> {"n", "first", "last"}: the zone products the joins could not place (the index's
        zone_unplaced_rows: [product, zone code, issue day, edition, reason]), counted for Montana, because those rows carry
        no zone name (B5 D27)."""
        if self._unplaced_cache is None:
            fam_of = {product: fam for fam, products, _noun in UNPLACED_FAMILIES for product in products}
            out: dict = {}
            for row in (self.jb.get("zone_unplaced_rows") or []):
                try:
                    product, day = row[0], date.fromisoformat(row[2])
                except (TypeError, ValueError, IndexError):
                    continue
                fam = fam_of.get(product)
                label = stations.season_of(day)
                if fam is None or label not in FIVE:
                    continue
                rec = out.setdefault((fam, label), {"n": 0, "first": day, "last": day})
                rec["n"] += 1
                rec["first"] = min(rec["first"], day)
                rec["last"] = max(rec["last"], day)
            self._unplaced_cache = out
        return self._unplaced_cache

    def in_window(self, day: date) -> bool:
        return self.first <= day <= self.last

    def season_cover(self, label: str, missing_days: set | None = None) -> tuple[int, int, int]:
        """(days of the season, days present in the window, valid days) for one season label. Days before the window
        are not in the store, so they are missing (D3); the store's missing days are missing too (B1)."""
        total, store = window_store(label, self.first, self.last)
        miss = 0
        if missing_days:
            miss = sum(1 for d in missing_days if stations.season_of(d) == label and self.in_window(d))
        return total, store, store - miss

    # --- the joins
    def joins_part(self, part: str) -> tuple[str, str, list]:
        """(state, reason, partial periods) of one joins part: "loaded", "partial" or "unavailable"."""
        if not self.jb or self.jb.get("format") != joins.FORMAT:
            return "unavailable", "the joins are missing from the index", []
        state = (self.jb.get("parts") or {}).get(part, "unavailable")
        reason = (self.jb.get("reasons") or {}).get(part) or joins.WORDS_JOINS["reason_no_answer"]
        periods = list((self.jb.get("partial") or {}).get(part) or [])
        return state, reason, periods

    def joins_tile(self) -> dict | None:
        if not self._tile_loaded:
            self._tile_doc = _read_json(self.root / "hail" / "j" / f"{self.tile}.json")
            self._tile_loaded = True
        return self._tile_doc

    def events(self) -> dict | None:
        return _read_json(self.root / "hail" / "j" / joins.EVENTS_NAME)

    def lsr_within(self, events: dict) -> list[dict]:
        """The LSR rows within 5 miles of the spot: day (Montana time), code, kind word, magnitude text and unit."""
        tile = self.joins_tile() or {}
        out = []
        for ref in tile.get("reports", []):
            r = events["reports"][ref]
            miles = joins.haversine_km(self.lat, self.lon, r[2], r[3]) / joins.MILE_KM
            if miles > joins.REPORT_MILES:
                continue
            out.append({"day": joins._local(joins.utc_from_row(r[0], r[1])).date(), "code": r[4], "mag": r[5],
                        "unit": r[6], "kind": r[11] if len(r) > 11 else r[4], "miles": round(miles, 2), "src": r[8]})
        return out

    def records_within(self, events: dict) -> list[dict]:
        """The NCEI point records within 5 miles of the spot: day (Montana time), and the NCEI type (lower case)."""
        tile = self.joins_tile() or {}
        out = []
        for ref in tile.get("records", []):
            r = events["records"][ref]
            miles = joins.haversine_km(self.lat, self.lon, r[2], r[3]) / joins.MILE_KM
            if miles <= joins.REPORT_MILES:
                out.append({"day": joins._local(joins.utc_from_row(r[0], r[1])).date(), "code": r[4]})
        return out

    def polygons_covering(self, events: dict, kinds: tuple, sig: str) -> list[date]:
        """The begin days (Montana time) of the polygon warnings of these products that covered the spot's cell (the
        cover of B2 and B5's D11: the cell is touched by the polygon)."""
        tile = self.joins_tile() or {}
        days = []
        for ref, cover in tile.get("warnings", []):
            if not joins.cover_has(cover, self.key):
                continue
            item = events["warnings"][ref]
            if item.get("k") in kinds and item.get("s") == sig:
                days.append(joins._local(joins.parse_iso_utc(item["b"])).date())
        return days

    def zone_events(self, tile: dict, kinds: tuple, sigs: tuple) -> list[date] | None:
        """The begin days of the spot's forecast zone's products with these codes and significance letters; None when
        the zone file did not load (or the zone is not in the tile's map)."""
        code = joins._zone_for_key(tile, self.key, "zones")
        if not code:
            return None
        doc = _read_json(self.root / "hail" / "z" / f"{code}.json")
        if doc is None:
            return None
        days = []
        for ev in doc.get("events", []):
            if ev.get("k") in kinds and ev.get("s") in sigs and ev.get("b"):
                days.append(joins._local(joins.parse_iso_utc(ev["b"])).date())
        return days

    def zone_first(self, tile: dict) -> date | None:
        """The day of the zone's earliest placed product (any kind) in the store, or None when the zone has none."""
        code = joins._zone_for_key(tile, self.key, "zones")
        doc = _read_json(self.root / "hail" / "z" / f"{code}.json") if code else None
        days = [joins._local(joins.parse_iso_utc(ev["b"])).date() for ev in (doc or {}).get("events", []) if ev.get("b")]
        return min(days) if days else None

    def gust_station(self, tile: dict) -> tuple | None:
        """(miles from the spot, station row, gust file) for the nearest station of the tile's list (B2's list: the two
        nearest within 40 miles of the tile centre) that has a gust file, or None."""
        best = None
        for st in tile.get("stations", []):
            doc = _read_json(self.root / "hail" / "s" / f"{st['id']}.json")
            if doc is None:
                continue
            miles = _miles(self.lat, self.lon, st["lat"], st["lon"])
            if best is None or miles < best[0]:
                best = (miles, st, doc)
        return best

    # --- the grid
    def climate_cell(self) -> tuple[str, object]:
        """(status, record): "ok" with the cell's record (climate.py's six seasons and its five-season and calendar
        lists), "no_land" (a water cell), "outside", or "unavailable" with the reason as the problem text."""
        cb = self.cb
        if not cb or cb.get("format") != climate.FORMAT or cb.get("state") == "unavailable":
            return "unavailable", (cb or {}).get("problem") or "the climate grid could not be read"
        cell = climate.climate_cell_for(self.lat, self.lon)
        if cell is None:
            return "outside", None
        i, j = cell
        tr, tc, key = climate.climate_tile(i, j)
        doc = _read_json(self.root / "hail" / "c" / f"{hail.tile_name(tr, tc)}.json")
        if doc is None:
            if hail.tile_name(tr, tc) in cb.get("tile_names", []):
                return "unavailable", cb.get("problem") or "the climate tile could not be read"
            return "outside", None
        if key not in doc.get("state", []):
            return "outside", None
        rec = doc.get("cells", {}).get(str(key))
        if rec is None:
            return "no_land", None
        return "ok", rec

    # --- the stations
    def chosen(self, element: str) -> tuple[str, list[dict], dict]:
        """(state, the chosen stations nearest first, the rule's result) for one element at the station point (D5, D18).
        The rule is the build's: the candidates within 40 miles of the point, with the inventory, the coverage and the
        currency for that element."""
        light = self.sb.get("stations") or {}
        as_of = date.fromisoformat(self.sb["as_of"]) if self.sb.get("as_of") else self.as_of
        lat, lon = self.station_point
        base = stations.within_radius(light, lat, lon)
        inventory = {sid: row.get("cover", {}) for sid, row in light.items()}
        cands = stations.ordered_candidates(base, inventory, element)
        res = stations.choose(cands, light, element, as_of)
        out = []
        for c in res["chosen"]:
            row = light[c["id"]]
            out.append({"id": c["id"], "name": row["name"], "net": row.get("net"),
                        "miles": round(_miles(self.anchor[0], self.anchor[1], row["lat"], row["lon"]), 1)})
        return res["state"], out, res

    def station_file(self, sid: str) -> dict | None:
        return _read_json(self.root / "hail" / "sd" / f"{sid}.json")

    def station_season(self, element: str, label: str, chosen: list[dict], conv) -> dict:
        """One season's station figure: the first chosen station (nearest first) whose season has at least 95 percent of
        its days with the element (D5). The nearer stations that fell short that season are named on the cell (passed_over),
        so the sheet can say why another station is shown. Otherwise the Data unavailable words name the nearest station
        with a record for the season, and its counts."""
        if not chosen:
            return _unavailable_cell(WORDS_SUMMARY["none_station"])
        short: list[dict] = []
        for st in chosen:
            doc = self.station_file(st["id"])
            period = ((doc or {}).get("periods") or {}).get("season", {}).get(label)
            if not period:
                continue
            n = int(period["n"])
            rec = period.get(element_key(element)) or {}
            ok = int(rec.get("ok", 0))
            if n > 0 and ok * 100 >= n * int(round(SEASON_SHARE * 100)):
                value, date_ = conv(rec)
                if value is not None:
                    cell = _cell(value=value, date_=date_, valid=ok, missing=n - ok, station=st["name"],
                                 miles=st["miles"], sid=st["id"])
                    cell["season"] = label
                    cell["passed_over"] = list(short)
                    return cell
            short.append({"station": st["name"], "n": n, "ok": ok, "miles": st["miles"], "sid": st["id"]})
        if not short:
            return _unavailable_cell(WORDS_SUMMARY["none_station"])
        first = short[0]
        text = WORDS_SUMMARY["station_short"].format(station=first["station"], k=first["ok"], d=first["n"],
                                                     element=stations.element_name(element))
        return _cell(value=None, text=text, valid=0, missing=first["n"] - first["ok"], station=first["station"],
                     miles=first["miles"], sid=first["sid"])

    # --- the gauge (town pages only, D6)
    def gauge_line(self, slug: str, name: str) -> list[str]:
        """The town's river gauge lines (D6). Every failure is said as one line (D16) and sets gauge_problem: the gauges
        block did not load, the gauge list has no entry for the town, the entry is marked unavailable, or its gauge file
        cannot be read. Only an entry marked none says that no gauge with a flood stage is near."""
        def problem(reason: str) -> list[str]:
            self.gauge_problem = reason
            return [WORDS_SUMMARY["unavailable_part"].format(part="The river gauge line", part_lower="river flood record")]

        if not self.gb or self.gb.get("state") == "unavailable":
            return problem("the gauges block did not load")
        towns = self.gb.get("towns")
        block = towns.get(slug) if isinstance(towns, dict) else None
        if not isinstance(block, dict):
            return problem("the gauge list has no entry for this town")
        if block.get("none"):
            return [WORDS_SUMMARY["gauge_none"].format(place=name)]
        if block.get("unavailable"):
            return problem("the gauge list marks this town unavailable")
        usgs = block.get("usgs")
        doc = _read_json(self.root / "hail" / "g" / f"{usgs}.json") if usgs else None
        if doc is None or not doc.get("stages") or doc["stages"].get("minor") is None or block.get("miles") is None:
            return problem("the gauge file for this town could not be read")
        minor = doc["stages"]["minor"]
        lines = [gauges.WORDS["lead"].format(name=doc["name"], miles=f"{block['miles']:.1f}"),
                 gauges.WORDS["stages"].format(minor=f"{minor / 100:.2f}",
                                               action=f"{(doc['stages'].get('action') or 0) / 100:.2f}",
                                               moderate=f"{(doc['stages'].get('moderate') or 0) / 100:.2f}",
                                               major=f"{(doc['stages'].get('major') or 0) / 100:.2f}")]
        floods = []
        for wy, day, hund, qual in doc.get("peaks", []):
            if hund is not None and hund >= minor:
                floods.append(gauges.WORDS["peak"].format(
                    wy=wy, ft=f"{hund / 100:.2f}", date=_fmt_date(date.fromisoformat(day)),
                    qual=(gauges.WORDS["peak_qual"].format(qual=qual) if qual else ""), minor=f"{minor / 100:.2f}"))
        if floods:
            lines.extend(floods)
        else:
            years = doc.get("water_years") or [None, None]
            lines.append(gauges.WORDS["no_peaks"].format(minor=f"{minor / 100:.2f}", first=years[0], last=years[1]))
        return lines


def element_key(element: str) -> str:
    """The station record key of a GHCN element (the same name in sd/ files)."""
    return element


# ---------------------------------------------------------------- the radar (B1) and the reports (B2)

def _radar_rows(spot: _Spot, days: list[tuple[date, int]]) -> tuple[dict, dict]:
    """The radar rows: the largest estimate with its date, and the days at 1 inch or more (B1, radar estimate)."""
    by_season: dict[str, dict[date, int]] = {lab: {} for lab in FIVE}
    for day, tenths in days:
        label = stations.season_of(day)
        if label in by_season and spot.in_window(day):
            by_season[label][day] = max(by_season[label].get(day, 0), tenths)
    cells_max, cells_one = [], []
    season_notes: list[str] = []
    for label in FIVE:
        total, store, valid = spot.season_cover(label, spot.missing)
        missing = total - valid
        if valid <= 0:
            text = WORDS_SUMMARY["season_unavailable"].format(season=label, source="radar history")
            cells_max.append(_unavailable_cell(WORDS_SUMMARY["cell_unavailable"]))
            cells_one.append(_unavailable_cell(WORDS_SUMMARY["cell_unavailable"]))
            season_notes.append(text)
            continue
        vals = by_season[label]
        big = [(t, d) for d, t in vals.items() if t >= FLOOR_TENTHS]
        if big:
            tenths, day = max(big, key=lambda x: (x[0], -x[1].toordinal()))
            hund = _hundredths_of_tenths_mm(tenths)
            cells_max.append(_cell(value=hund, text=_fmt_in_on(hund, _yyyymmdd(day)), date_=_yyyymmdd(day),
                                   valid=valid, missing=missing))
        else:
            cells_max.append(_cell(value=None, text=WORDS_SUMMARY["none_radar"], valid=valid, missing=missing))
        n_one = sum(1 for t in vals.values() if t >= ONE_INCH_TENTHS)
        cells_one.append(_cell(value=n_one, text=_count_text("days", n_one), valid=valid, missing=missing))
    five_max = _five(cells_max, "max", None, "radar history", WORDS_SUMMARY["none_radar"])
    five_one = _five(cells_one, "sum", lambda v: _count_text("days", v), "radar history", "")
    class_note = _class_note(by_season)
    notes = season_notes + [WORDS_SUMMARY["window_radar"].format(first=_fmt_date(spot.first), last=_fmt_date(spot.last),
                                                  as_of=_fmt_date(spot.as_of), season=FIVE[0])]
    return _row(_spec("radar_max"), cells_max, five_max, notes), _row(_spec("radar_1in"), cells_one, five_one,
                                                                       [class_note] if class_note else [])


def _class_note(by_season: dict) -> str | None:
    """The radar days by size class over the five seasons (B1's classes, hail.CLASSES): "2 days penny to nickel (0.75 to
    0.99 in); 1 day quarter to half dollar (1.00 to 1.49 in)". None when no day has an estimate of 0.25 in or more."""
    counts: dict[str, int] = {}
    for vals in by_season.values():
        for tenths in vals.values():
            if tenths >= FLOOR_TENTHS:
                counts[hail.class_for(tenths)["word"]] = counts.get(hail.class_for(tenths)["word"], 0) + 1
    items = []
    for cls in hail.CLASSES:
        n = counts.get(cls["word"], 0)
        if not n:
            continue
        if cls["max_in"] is None:
            span = f"{cls['min_in']:.2f} in or more"
        else:
            span = f"{cls['min_in']:.2f} to {cls['max_in']:.2f} in"
        items.append(f"{_count_text('days', n)} {cls['word']} ({span})")
    if not items:
        return None
    return WORDS_SUMMARY["class_counts"].format(items="; ".join(items))


def _lsr_cells(spot: _Spot, lsr: list[dict]) -> dict:
    """The per-season cells of the report rows: hail (largest and count), wind, freezing rain and flood (B2 LSR)."""
    picks = {
        "hail_n": lambda r: r["code"] == "H",
        "wind_n": lambda r: r["code"] in WIND_CODES,
        "freezing_rain_n": lambda r: r["kind"] == "freezing rain",
        "flood_report_n": lambda r: r["kind"] in ("flood", "flash flood"),
    }
    out = {key: [] for key in picks}
    out["hail_max"] = []
    for label in FIVE:
        total, store, valid = spot.season_cover(label)
        missing = total - valid
        for key, pick in picks.items():
            if valid <= 0:
                out[key].append(_unavailable_cell(WORDS_SUMMARY["season_unavailable"].format(season=label, source="report archive")))
                continue
            members = [r for r in lsr if pick(r) and stations.season_of(r["day"]) == label and spot.in_window(r["day"])]
            out[key].append(_cell(value=len(members), text=_count_text(key, len(members)), valid=valid, missing=missing))
        if valid <= 0:
            out["hail_max"].append(_unavailable_cell(WORDS_SUMMARY["season_unavailable"].format(season=label, source="report archive")))
            continue
        best = None
        for r in lsr:
            if r["code"] != "H" or r["unit"] != "in" or stations.season_of(r["day"]) != label or not spot.in_window(r["day"]):
                continue
            hund = _hundredths_from_decimal(r["mag"])
            if hund is None:
                continue
            if best is None or hund > best[0] or (hund == best[0] and r["day"] < best[1]):
                best = (hund, r["day"])
        if best is None:
            out["hail_max"].append(_cell(value=None, text=WORDS_SUMMARY["none_hail"], valid=valid, missing=missing))
        else:
            out["hail_max"].append(_cell(value=best[0], text=_fmt_in_on(best[0], _yyyymmdd(best[1])),
                                         date_=_yyyymmdd(best[1]), valid=valid, missing=missing))
    return out


def _count_cells(spot: _Spot, days: list[date], key: str) -> list[dict]:
    """One count per season from the days of its items (the day of each item, Montana time), with the window coverage."""
    cells = []
    for label in FIVE:
        total, store, valid = spot.season_cover(label)
        if valid <= 0:
            cells.append(_unavailable_cell(WORDS_SUMMARY["season_unavailable"].format(season=label, source="record archive")))
            continue
        n = sum(1 for d in days if stations.season_of(d) == label and spot.in_window(d))
        cells.append(_cell(value=n, text=_count_text(key, n), valid=valid, missing=total - valid))
    return cells


def _gust_rows(spot: _Spot, tile: dict) -> tuple[dict, dict]:
    """The gust rows (B2's station gust records, IEM daily gusts): the days at 50 kt or more and the strongest gust, at the
    nearer of the tile's two gust stations. A season shows its figures only when at least 95 percent of its days have a
    gust value (D5, O8). The station record's own counts say how many do (periods.season: n days and ok days with a
    value, the season's whole record). A record without those counts shows Data unavailable for every gust figure: a 0
    cannot then be told from a season with no record. The station is named in every row."""
    got = spot.gust_station(tile)
    if got is None:
        none = [_unavailable_cell(WORDS_SUMMARY["gust_none"]) for _ in FIVE]
        five = {"value": None, "date": None, "text": WORDS_SUMMARY["cell_unavailable"], "coverage": None, "note": None}
        return (_row(_spec("gust_days"), none, five, [WORDS_SUMMARY["gust_none"]]),
                _row(_spec("gust_max"), none, five, [WORDS_SUMMARY["gust_none"]]))
    miles, st, doc = got
    name = st["name"]
    spot.gust = {"name": name, "miles": f"{miles:.1f}"}
    miles_text = round(miles, 1)
    note = WORDS_SUMMARY["gust_station"].format(station=name, miles=f"{miles:.1f}")
    seasons = ((doc or {}).get("periods") or {}).get("season")
    unavailable = WORDS_SUMMARY["cell_unavailable"]
    if not isinstance(seasons, dict):
        interim = WORDS_SUMMARY["gust_interim"].format(station=name)
        cells_days = [_cell(text=unavailable, unknown=True, station=name, miles=miles_text, sid=st["id"]) for _ in FIVE]
        cells_max = [_cell(text=unavailable, unknown=True, station=name, miles=miles_text, sid=st["id"]) for _ in FIVE]
        return (_row(_spec("gust_days"), cells_days, _five(cells_days, "sum", None, "gust record", ""),
                     [note, interim, WORDS_SUMMARY["gust_coverage_note"]]),
                _row(_spec("gust_max"), cells_max, _five(cells_max, "max", None, "gust record", WORDS_SUMMARY["none_gust"]),
                     [note, interim, WORDS_SUMMARY["gust_floor_note"]]))
    share = int(round(SEASON_SHARE * 100))
    cells_days, cells_max = [], []
    for label in FIVE:
        per = seasons.get(label) or {}
        n_days = int(per.get("n") or 0)
        ok = int(per.get("ok") or 0)
        if n_days <= 0:
            cells_days.append(_cell(text=unavailable, unknown=True, station=name, miles=miles_text, sid=st["id"]))
            cells_max.append(_cell(text=unavailable, unknown=True, station=name, miles=miles_text, sid=st["id"]))
            continue
        missing = max(0, n_days - ok)
        if ok * 100 < n_days * share:
            text = WORDS_SUMMARY["gust_season_short"].format(station=name, k=ok, d=n_days)
            cells_days.append(_cell(text=text, valid=ok, missing=missing, unknown=True, station=name, miles=miles_text,
                                    sid=st["id"]))
            cells_max.append(_cell(text=text, valid=ok, missing=missing, unknown=True, station=name, miles=miles_text,
                                   sid=st["id"]))
            continue
        members = []
        for item in doc.get("days", []):
            day = hail.day_of_index(int(item[0]))
            if stations.season_of(day) == label:
                members.append((day, int(item[1]), int(item[2]), int(item[3]) if len(item) > 3 else 0))
        n = len(members)
        text = (WORDS_SUMMARY["station_days_one"] if n == 1 else WORDS_SUMMARY["station_days"]).format(n=n, station=name)
        cells_days.append(_cell(value=n, text=text, valid=ok, missing=missing, station=name, miles=miles_text,
                                sid=st["id"]))
        if members:
            day, mph, kt, flag = max(members, key=lambda m: (m[2], -m[0].toordinal()))
            wording = WORDS_SUMMARY["gust_flagged" if flag else "gust"]
            cells_max.append(_cell(value=kt, text=wording.format(kt=kt, mph=mph, date=_fmt_date(day)),
                                   date_=_yyyymmdd(day), valid=ok, missing=missing, station=name, miles=miles_text,
                                   sid=st["id"]))
        else:
            cells_max.append(_cell(value=None, text=WORDS_SUMMARY["none_gust"], valid=ok, missing=missing, station=name,
                                   miles=miles_text, sid=st["id"]))
    five_days = _five(cells_days, "sum", lambda v: _count_text("days", v), "gust record", "")
    five_max = _five(cells_max, "max", None, "gust record", WORDS_SUMMARY["none_gust"])
    return (_row(_spec("gust_days"), cells_days, five_days, [note, WORDS_SUMMARY["gust_coverage_note"]]),
            _row(_spec("gust_max"), cells_max, five_max, [note, WORDS_SUMMARY["gust_floor_note"]]))


# ---------------------------------------------------------------- the grid (B5 c/)

CLIMATE_KEYS = ("tmax", "tmin", "hot90", "frost32", "freeze_thaw", "precip", "precip_max")
TEMP_KEYS = ("tmax", "tmin", "hot90", "frost32", "freeze_thaw")


def _clim_cells(label: str, r: list) -> dict:
    """One season's grid figures from its period record (climate.py's thirteen fields): highest and lowest temperature
    with their dates, the day counts, the precipitation and the largest one-day precipitation with its date."""
    days, missing = int(r[0]), int(r[1])
    valid = days - missing
    if valid <= 0:
        return {key: _unavailable_cell(WORDS_SUMMARY["season_unavailable"].format(season=label, source="grid"))
                for key in CLIMATE_KEYS}
    out = {}
    out["tmax"] = _cell(value=r[5], text=_fmt_f_on(r[5], r[6]) if r[5] is not None else None, date_=r[6],
                        valid=valid, missing=missing)
    out["tmin"] = _cell(value=r[7], text=_fmt_f_on(r[7], r[8]) if r[7] is not None else None, date_=r[8],
                        valid=valid, missing=missing)
    for key, idx in (("hot90", 9), ("frost32", 12), ("freeze_thaw", 11)):
        out[key] = _cell(value=r[idx], text=_count_text("days", r[idx]) if r[idx] is not None else None,
                         valid=valid, missing=missing)
    out["precip"] = _cell(value=r[2], text=WORDS_SUMMARY["in_plain"].format(inches=_in_text(r[2])) if r[2] is not None
                          else None, valid=valid, missing=missing)
    out["precip_max"] = _cell(value=r[3], text=_fmt_in_on(r[3], r[4]) if r[3] is not None else None, date_=r[4],
                              valid=valid, missing=missing)
    return out


def _climate_part(spot: _Spot) -> dict:
    """The grid rows: highest and lowest temperature with dates, the day counts, precipitation and the largest one-day
    precipitation. Five seasons: each season's cells and the five-season figure from them."""
    status, rec = spot.climate_cell()
    out = {}
    if status == "unavailable":
        for key in CLIMATE_KEYS:
            part = "Temperature" if key in TEMP_KEYS else "Rain"
            out[key] = _unavailable_row(_spec(key), climate.WORDS_CLIMATE["unavailable"].format(part=part, part_lower=part.lower()))
        return out
    if status != "ok":
        sentence = climate.WORDS_CLIMATE["no_land"] if status == "no_land" else climate.WORDS_CLIMATE["not_in_store"]
        for key in CLIMATE_KEYS:
            out[key] = _unavailable_row(_spec(key), sentence)
        return out
    through = spot.cb.get("through")
    per = {key: [] for key in CLIMATE_KEYS}
    for k, label in enumerate(FIVE):
        cells = _clim_cells(label, rec["s"][k])
        for key in CLIMATE_KEYS:
            per[key].append(cells[key])
    grid_notes = [climate.WORDS_CLIMATE["cell_sentence"]]
    if through:
        grid_notes.append(WORDS_SUMMARY["window_grid"].format(through=_fmt_date(date.fromisoformat(through))))
    counts = lambda key: (lambda v: _count_text("days", v))
    fmt_sum = {"hot90": counts("hot90"), "frost32": counts("frost32"), "freeze_thaw": counts("freeze_thaw"),
               "precip": lambda v: WORDS_SUMMARY["in_plain"].format(inches=_in_text(v))}
    combine = {"tmax": "max", "tmin": "min", "precip_max": "max"}
    for key in CLIMATE_KEYS:
        five = _five(per[key], combine.get(key, "sum"), fmt_sum.get(key), "grid", WORDS_SUMMARY["cell_unavailable"])
        notes = list(grid_notes) if key in ("tmax", "precip") else []
        out[key] = _row(_spec(key), per[key], five, notes)
    return out


# ---------------------------------------------------------------- the stations (B5 sd/)

STATION_CONV = {
    "SNOW": lambda rec: (stations.mm_to_hundredths_in(rec["sum"]) if "sum" in rec else None, None),
    "SNWD": lambda rec: (stations.mm_to_hundredths_in(rec["max"]) if "max" in rec else None, rec.get("max_d")),
    "TMAX": lambda rec: (stations.tenths_c_to_tenths_f(rec["max"]) if "max" in rec else None, rec.get("max_d")),
    "TMIN": lambda rec: (stations.tenths_c_to_tenths_f(rec["min"]) if "min" in rec else None, rec.get("min_d")),
}


def _station_text(element: str, value: int, date_: int | None, name: str) -> str:
    if element == "SNOW":
        return WORDS_SUMMARY["snow_at"].format(inches=stations.fmt_in(value), station=name)
    if element == "SNWD":
        return WORDS_SUMMARY["snow_depth_at"].format(inches=stations.fmt_in(value),
                                                     date=_fmt_date(_from_yyyymmdd(date_)), station=name)
    return WORDS_SUMMARY["temp_at"].format(f=climate._tenths_f_text(value), date=_fmt_date(_from_yyyymmdd(date_)),
                                           station=name)


def _number_word(n: int) -> str:
    return {2: "two", 3: "three", 4: "four", 5: "five"}.get(n, str(n))


def _station_runs(cells: list[dict]) -> str:
    """The stations named by the seasons they gave: "Billings WTP 2021-22 to 2024-25, Billings Logan 2025-26"."""
    runs: list[list] = []
    for k, cell in enumerate(cells):
        name = cell.get("station")
        if not name:
            continue
        if runs and runs[-1][0] == name and runs[-1][2] == k - 1:
            runs[-1][2] = k
        else:
            runs.append([name, k, k])
    parts = []
    for name, first, last in runs:
        span = FIVE[first] if first == last else f"{FIVE[first]} to {FIVE[last]}"
        parts.append(f"{name} {span}")
    return ", ".join(parts)


def _station_row(spot: _Spot, key: str, element: str, combine: str) -> dict:
    """A station row: each season from the first chosen station that passes the season share (D5), named in its text. A
    five-season total across more than one station names them with the seasons they gave, and a season where a nearer
    station fell short says so with its share."""
    state, chosen, res = spot.chosen(element)
    cells = []
    for label in FIVE:
        cell = spot.station_season(element, label, chosen, STATION_CONV[element])
        if cell["value"] is not None:
            cell["text"] = _station_text(element, cell["value"], cell["date"], cell["station"])
        cells.append(cell)
    five = _five(cells, combine, (lambda v: WORDS_SUMMARY["in_plain"].format(inches=stations.fmt_in(v)))
                 if combine == "sum" else None, "station record", WORDS_SUMMARY["none_station"])
    names = {c["station"] for c in cells if c.get("station")}
    if combine == "sum" and five["value"] is not None and len(names) > 1:
        five["text"] = WORDS_SUMMARY["five_stations"].format(total=five["text"], count=_number_word(len(names)),
                                                             runs=_station_runs(cells))
    notes = []
    if state == "none" or not chosen:
        notes.append(WORDS_SUMMARY["station_none"].format(element=stations.element_name(element)))
    else:
        notes.append(WORDS_SUMMARY["station_rule_town" if spot.town else "station_rule_spot"])
        for st in chosen:
            notes.append(WORDS_SUMMARY["station_named_town" if spot.town else "station_named"].format(
                station=st["name"], miles=f"{st['miles']:.1f}"))
            if st.get("net") == "SNOTEL":
                notes.append(WORDS_SUMMARY["snotel_station"].format(station=st["name"]))
        notes.extend(stations.station_words(res, element))
    for label, cell in zip(FIVE, cells):
        for po in cell.get("passed_over") or []:
            pct = f"{po['ok'] * 100 / po['n']:.1f}" if po["n"] else "0.0"
            notes.append(WORDS_SUMMARY["passed_over"].format(station=po["station"], pct=pct, season=label, ok=po["ok"],
                                                             n=po["n"], chosen=cell["station"]))
    notes.append(WORDS_SUMMARY["window_station"])
    return _row(_spec(key), cells, five, notes)


def _station_part(spot: _Spot) -> dict:
    """The station rows: snowfall and the deepest snow everywhere; the two temperature rows on a town page."""
    keys = ["snow", "snow_depth"] + (["tmax_station", "tmin_station"] if spot.town else [])
    if not spot.sb or spot.sb.get("state") == "unavailable" or not spot.sb.get("stations"):
        sentence = WORDS_SUMMARY["unavailable_part"].format(part="Station readings", part_lower="station readings")
        return {key: _unavailable_row(_spec(key), sentence) for key in keys}
    out = {"snow": _station_row(spot, "snow", "SNOW", "sum"),
           "snow_depth": _station_row(spot, "snow_depth", "SNWD", "max")}
    if spot.town:
        out["tmax_station"] = _station_row(spot, "tmax_station", "TMAX", "max")
        out["tmin_station"] = _station_row(spot, "tmin_station", "TMIN", "min")
    return out


def _dl_cells(spot: _Spot):
    """Days with 1 inch or more of snow on the ground and a low below 32 F, per season: the pair count of the station
    that passes the snow-depth share for that season (D5). None when no station passes."""
    if not spot.sb or spot.sb.get("state") == "unavailable" or not spot.sb.get("stations"):
        return WORDS_SUMMARY["unavailable_part"].format(part="Station readings", part_lower="station readings")
    state, chosen, _ = spot.chosen("SNWD")
    if state == "none" or not chosen:
        return None
    cells = []
    for label in FIVE:
        cell = spot.station_season("SNWD", label, chosen, STATION_CONV["SNWD"])
        if cell["valid"] <= 0 or cell["sid"] is None:
            cells.append(_unavailable_cell(WORDS_SUMMARY["cell_unavailable"]))
            continue
        doc = spot.station_file(cell["sid"])
        period = ((doc or {}).get("periods") or {}).get("season", {}).get(label) or {}
        pair = period.get("DL")
        if not pair:
            cells.append(_unavailable_cell(WORDS_SUMMARY["cell_unavailable"]))
            continue
        n = int(pair["n"])
        cells.append(_cell(value=n, text=_count_text("days", n), valid=cell["valid"], missing=cell["missing"],
                           station=cell["station"], miles=cell["miles"], sid=cell["sid"]))
    return cells


# ---------------------------------------------------------------- the zones, the warnings and the counties

def _partial_five(cells: list[dict], key: str) -> dict | None:
    """The five-season total of a count when some seasons are unknown (zone products not placed): the total of the seasons
    shown, with the seasons it leaves out named, so it cannot read as a total of all five. None when no season is shown."""
    shown = [c["value"] for c in cells if c["value"] is not None]
    if not shown:
        return None
    skipped = [FIVE[k] for k, c in enumerate(cells) if c["value"] is None]
    total = sum(shown)
    missing_total = sum(c["missing"] for c in cells)
    return {"value": total, "date": None,
            "text": WORDS_SUMMARY["five_partial"].format(count=_count_text(key, total), seasons=", ".join(skipped)),
            "coverage": _cover(missing_total, _joined_flags(cells)), "note": None}


def _extra_five(cells: list[dict], key: str) -> dict:
    """The five-season figure of a roof count from season cells: the total, or, for a zone-coded count with some seasons
    unknown, the total of the seasons shown, with those left out named."""
    five = _five(cells, "sum", None, "record archive", "")
    if five["value"] is None and key in ZONE_EXTRA and any(c["value"] is not None for c in cells):
        five = _partial_five(cells, ZONE_EXTRA[key]) or five
    return five


# The zone products the joins could not place (index zone_unplaced_rows), by the row family that counts them (B5 D27).
UNPLACED_FAMILIES = (
    ("high_wind", ("HW.W", "HW.A"), "high wind"),
    ("winter_storm", ("WS.W",), "winter storm"),
    ("heat_advisory", ("HT.Y",), "heat advisory"),
    ("flood_advisory", ("FA.A",), "flood advisory"),
    ("flash_flood_advisory", ("FF.A",), "flash flood advisory"),
)
RECONFIGURED = range(301, 331)        # the zones MTZ301 to MTZ330 (the NWS change log: reconfigured on RECONFIG_DAY)
RECONFIG_DAY = date(2022, 9, 7)


def _family_noun(key: str) -> str:
    for fam, _products, noun in UNPLACED_FAMILIES:
        if fam == key:
            return noun
    raise KeyError(key)


def _product_words(noun: str, n: int) -> str:
    return f"{noun} product" if n == 1 else f"{noun} products"


def _zone_number(code: str | None) -> int | None:
    if code and code.startswith("MTZ") and code[3:].isdigit():
        return int(code[3:])
    return None


def _when(rec: dict) -> str:
    """"Jul 18, 2022" for one day, "Jul 18, 2022 to Sep 7, 2022" for a span of days."""
    if rec["first"] == rec["last"]:
        return _fmt_date(rec["first"])
    return f"{_fmt_date(rec['first'])} to {_fmt_date(rec['last'])}"


def _zone_flag(spot: _Spot, family: str | None, label: str) -> str | None:
    """Montana's unplaced products of the family in the season, as a zone cell's coverage statement: "Montana: 59 high wind
    products issued Jul 18, 2022 to Sep 7, 2022 could not be placed to a zone." None when there are none."""
    if family is None:
        return None
    rec = spot.unplaced_index().get((family, label))
    if rec is None:
        return None
    return WORDS_SUMMARY["zone_flag"].format(n=f"{rec['n']:,}", noun=_product_words(_family_noun(family), rec["n"]),
                                             when=_when(rec))


def _change_text(number: int | None, label: str) -> tuple[str, bool] | None:
    """For a reconfigured zone (MTZ301 to MTZ330): the coverage text of a season that the change shortens, and whether a
    zero in it is unknown. A season wholly before RECONFIG_DAY has no products in the data (a zero is unknown); 2022-23 is
    partial before the change day (from the NWS change log; inferred, as the store holds no older zone edition)."""
    if number not in RECONFIGURED:
        return None
    start, end = season_bounds(label)
    if start >= RECONFIG_DAY:
        return None
    if end < RECONFIG_DAY:
        return WORDS_SUMMARY["zone_before_change_all"].format(date=_fmt_date(RECONFIG_DAY)), True
    return WORDS_SUMMARY["zone_before_change"].format(n=(RECONFIG_DAY - start).days, date=_fmt_date(RECONFIG_DAY)), False


def _zone_cells(spot: _Spot, tile: dict, days: list, key: str, family: str | None) -> list[dict]:
    """The season cells of a zone-coded count (its own products, _count_cells). Montana's unplaced products of the family
    mark the seasons they fall in: a zero there is Data unavailable, and a count keeps its value with the statement on its
    coverage line. The reconfigured zones (MTZ301 to MTZ330) mark the seasons before the change (B5 D27)."""
    cells = _count_cells(spot, days, key)
    number = _zone_number(joins._zone_for_key(tile, spot.key, "zones"))
    out = []
    for label, cell in zip(FIVE, cells):
        flags = []
        flagged = _zone_flag(spot, family, label)
        if flagged:
            flags.append(flagged)
        change = _change_text(number, label)
        if change:
            flags.append(change[0])
        if cell["value"] == 0 and (flagged or (change and change[1])):
            out.append(_cell(text=WORDS_SUMMARY["zero_unknown"], valid=0, missing=cell["missing"],
                             flag="; ".join(flags) or None))
            continue
        if flags:
            cell = dict(cell)
            cell["flag"] = "; ".join(flags)
            cell["coverage"] = _cover(cell["missing"], cell["flag"])
        out.append(cell)
    return out


def _unplaced_note(spot: _Spot, families: tuple) -> str | None:
    """The Montana statement for a zone row or section: how many of its families' products could not be placed, by season.
    There is no per-zone count (the store cannot say whose they were; B5 D27). None when there are none."""
    unp = spot.unplaced_index()
    parts = []
    for fam in families:
        for label in FIVE:
            rec = unp.get((fam, label))
            if rec:
                parts.append(f"{rec['n']:,} {_product_words(_family_noun(fam), rec['n'])} in {label}")
    if not parts:
        return None
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return WORDS_SUMMARY["zone_unplaced_note"].format(parts=listed)


def _reconfigured_note(spot: _Spot, tile: dict) -> str | None:
    """The per-zone line for MTZ301 to MTZ330: the change day and the first placed product (no older product is in the data)."""
    if _zone_number(joins._zone_for_key(tile, spot.key, "zones")) not in RECONFIGURED:
        return None
    first = spot.zone_first(tile)
    if first is None:
        return WORDS_SUMMARY["zone_reconfigured_none"].format(date=_fmt_date(RECONFIG_DAY))
    return WORDS_SUMMARY["zone_reconfigured"].format(date=_fmt_date(RECONFIG_DAY), first=_fmt_date(first))


def _automated_sentence(n: int, kind: str) -> str:
    """The automated-report sentence of a count: one set for every wind count (IEM SOURCE Mesonet, ASOS or AWOS)."""
    if n == 1:
        return WORDS_SUMMARY["automated_one"].format(kind=kind)
    return WORDS_SUMMARY["automated_note"].format(n=n, kind=kind)


def _section_notes(spot: _Spot) -> dict:
    """The Montana statements of unplaced zone products in the sections that carry zone products (B5 D27)."""
    return {"heat": _unplaced_note(spot, ("heat_advisory",)),
            "flooding": _unplaced_note(spot, ("flood_advisory", "flash_flood_advisory"))}


def _zone_rows(spot: _Spot, tile: dict | None) -> dict:
    """High wind watches and warnings, and winter storm and ice storm warnings, for the spot's forecast zone (zone
    products: the whole zone, not this spot alone). A season whose family has products that could not be placed says so
    on its coverage line (B5 D27): a zero there is Data unavailable, and a count keeps its value."""
    state, reason, periods = spot.joins_part("zones")
    if state == "unavailable" or tile is None:
        sentence = joins._unavailable_text("zones", reason)
        return {key: _unavailable_row(_spec(key), sentence) for key in ("hw_zone", "ice_warn")}
    partial_note = joins._unavailable_text("zones", reason, periods) if state == "partial" else None
    shared = [n for n in (partial_note, _reconfigured_note(spot, tile)) if n]
    out = {}
    for key, kinds, sigs, family in (("hw_zone", ("HW",), ("W", "A"), "high_wind"),
                                     ("ice_warn", ("WS", "IS"), ("W",), "winter_storm")):
        days = spot.zone_events(tile, kinds, sigs)
        if days is None:
            out[key] = _unavailable_row(_spec(key), joins._unavailable_text("zones", "the zone file did not load"))
            continue
        cells = _zone_cells(spot, tile, days, key, family)
        five = _five(cells, "sum", lambda v, key=key: _count_text(key, v), "zone archive", "")
        if five["value"] is None and any(c["value"] is not None for c in cells):
            five = _partial_five(cells, key) or five
        notes = shared + [n for n in (_unplaced_note(spot, (family,)),) if n]
        out[key] = _row(_spec(key), cells, five, notes)
    return out


def _warning_rows(spot: _Spot, events: dict | None) -> dict:
    """Flood and flash flood warnings (polygons, B2 and B5 j/): FF.W, FL.W and FA.W that covered the spot's cell or part of
    it (D11). Advisories (FA.Y, FA.A) are not warnings and are not counted."""
    state, reason, periods = spot.joins_part("warnings")
    if state == "unavailable" or events is None:
        return {"flood_warn": _unavailable_row(_spec("flood_warn"), joins._unavailable_text("warnings", reason))}
    note = joins._unavailable_text("warnings", reason, periods) if state == "partial" else None
    cells = _count_cells(spot, spot.polygons_covering(events, ("FF", "FL", "FA"), "W"), "flood_warn")
    five = _five(cells, "sum", lambda v: _count_text("flood_warn", v), "warning archive", "")
    return {"flood_warn": _row(_spec("flood_warn"), cells, five, [note] if note else [])}


def _county_rows(spot: _Spot, tile: dict | None) -> dict:
    """The county products (B5 k/): the county-only flood and flash flood watches (FA.A, FF.A) for the spot's county."""
    unavailable = {"county_watch": _unavailable_row(_spec("county_watch"), joins.WORDS_JOINS["county_unavailable"])}
    block = spot.jb.get("counties") or {}
    if block.get("state") != "loaded" or tile is None:
        return unavailable
    code = joins._zone_for_key(tile, spot.key, "counties")
    doc = _read_json(spot.root / "hail" / "k" / f"{code}.json") if code else None
    if doc is None:
        return unavailable
    days = [joins._local(joins.parse_iso_utc(ev["b"])).date() for ev in doc.get("events", [])
            if ev.get("k") in ("FA", "FF") and ev.get("s") == "A" and ev.get("b")]
    cells = _count_cells(spot, days, "county_watch")
    five = _five(cells, "sum", lambda v: _count_text("county_watch", v), "county archive", "")
    county = (block.get("names") or {}).get(code, code)
    return {"county_watch": _row(_spec("county_watch"), cells, five,
                                 [f"{county.replace(' County', '')} County: the whole county, not this spot alone."])}


def _held_row() -> dict:
    """The held items (D14) that the table carries as one row: lightning, UV and sunlight, roof surface temperature and
    ponding, each with its reason (the roof section also lists FEMA flood zones, ground snow load and SNOTEL)."""
    cells = [_unavailable_cell() for _ in FIVE]
    five = {"value": None, "date": None, "text": WORDS_SUMMARY["cell_unavailable"], "coverage": None, "note": None}
    held = WORDS_INDICATORS["held"]
    return _row(_spec("held"), cells, five, [held["lightning"], held["uv_and_sun"],
                                             held["roof_surface_temperature"], held["ponding"]])


# ---------------------------------------------------------------- the reports (B2 LSR, B5 records) and the partial season

def _reports_rows(spot: _Spot, events: dict | None) -> dict:
    """The report rows: hail (largest and count), wind, freezing rain and flood (B2 LSR, within 5 miles). The hail and wind
    counts carry how many of their reports are automated station reports (IEM SOURCE Mesonet, ASOS or AWOS; the row's
    automated key), and say so in a note."""
    state, reason, periods = spot.joins_part("reports")
    keys = ("hail_max", "hail_n", "wind_n", "freezing_rain_n", "flood_report_n")
    if state == "unavailable" or events is None:
        sentence = joins._unavailable_text("reports", reason if events is not None else joins.WORDS_JOINS["reason_events"])
        return {key: _unavailable_row(_spec(key), sentence) for key in keys}
    lsr = spot.lsr_within(events)
    note = joins._unavailable_text("reports", reason, periods) if state == "partial" else None
    cells = _lsr_cells(spot, lsr)
    out = {}
    five_max = _five(cells["hail_max"], "max", None, "report archive", WORDS_SUMMARY["none_hail"])
    out["hail_max"] = _row(_spec("hail_max"), cells["hail_max"], five_max, [note] if note else [])
    in_five = lambda r: stations.season_of(r["day"]) in FIVE and spot.in_window(r["day"])
    for key, pick, kind in (("hail_n", lambda r: r["code"] == "H", "hail reports"),
                            ("wind_n", lambda r: r["code"] in WIND_CODES, "wind reports")):
        automated = sum(1 for r in lsr if pick(r) and in_five(r) and r.get("src") in AUTO_SOURCES)
        extra_notes = [note] if note else []
        if automated:
            extra_notes.append(_automated_sentence(automated, kind))
        five = _five(cells[key], "sum", lambda v, key=key: _count_text(key, v), "report archive", "")
        out[key] = _row(_spec(key), cells[key], five, extra_notes)
        out[key]["automated"] = automated
    for key in ("freezing_rain_n", "flood_report_n"):
        five = _five(cells[key], "sum", lambda v, key=key: _count_text(key, v), "report archive", "")
        out[key] = _row(_spec(key), cells[key], five, [note] if note else [])
    return out


def _partial(spot: _Spot, climate_rec, through, lsr, radar_days) -> str:
    """The one line below the table for 2026-27 (D20): the grid's own sentence for the days so far, and the report and
    radar counts so far. When the store holds no day of the season, the no-day sentence says so."""
    store_days = spot.season_cover(PARTIAL)[1]
    grid_days = int(climate_rec[0]) if climate_rec else 0
    if store_days <= 0 and grid_days <= 0:
        return WORDS_SUMMARY["partial_none"].format(season=PARTIAL)
    parts = []
    if climate_rec and grid_days > 0 and through:
        parts.append(climate._partial_text(climate._record_row(climate_rec), PARTIAL, through))
    if lsr is not None and radar_days is not None:
        def count(pick):
            return sum(1 for r in lsr if pick(r) and stations.season_of(r["day"]) == PARTIAL and spot.in_window(r["day"]))
        hail_n = count(lambda r: r["code"] == "H")
        wind_n = count(lambda r: r["code"] in WIND_CODES)
        wind_auto = count(lambda r: r["code"] in WIND_CODES and r.get("src") in AUTO_SOURCES)
        flood_n = count(lambda r: r["kind"] in ("flood", "flash flood"))
        one = sum(1 for d, t in radar_days if stations.season_of(d) == PARTIAL and t >= ONE_INCH_TENTHS)
        auto = WORDS_SUMMARY["auto_partial"].format(n=wind_auto) if (wind_n and wind_auto) else ""
        parts.append(WORDS_SUMMARY["partial_counts"].format(
            season=PARTIAL, hail=hail_n, hail_word="report" if hail_n == 1 else "reports",
            wind=wind_n, wind_word="report" if wind_n == 1 else "reports", auto=auto,
            flood=flood_n, flood_word="report" if flood_n == 1 else "reports",
            r1=one, r1_word="day" if one == 1 else "days"))
    return " ".join(parts) if parts else WORDS_SUMMARY["partial_none"].format(season=PARTIAL)


# ---------------------------------------------------------------- the roof section

def _line(ind: str, label: str, kind: str, unit: str, value, text, why=None, coverage=None) -> dict:
    """One roof indicator line: its label, kind word, unit and scale (the store's integer unit), the five-season value (an
    integer or None) and its words. A line with no value says Data unavailable beside its label, with the reason."""
    if value is None or text is None:
        text = WORDS_INDICATORS["indicator_unavailable"].format(label=label, why=why or WORDS_SUMMARY["cell_unavailable"])
    return {"id": ind, "label": label, "kind": kind, "unit": unit, "scale": UNIT_SPEC[unit]["scale"],
            "value": None if value is None else int(value), "text": text, "coverage": coverage}


def _gust_why(rows: dict) -> str | None:
    """Why the gust line has no figure: the station's own unavailable sentence when the row has one, else the five-season note."""
    row = rows.get("gust_days") or {}
    return next((n for n in row.get("notes") or [] if n.startswith("Data unavailable")), None) or row.get("five_note")


def _roof(spot: _Spot, rows: dict, extra: dict, dl_cells) -> dict:
    """The roof section: the 23 indicator lines under the five headings (each with its kind word and its five-season
    count or measurement, from the same records as the table), the reference lines (quotes from the public sources the
    roof record names, one per stressor) and the held lines (D14, and the two items the record marks not shown)."""
    L = WORDS_INDICATORS["lines"]
    lines = {}

    def rv(key):
        row = rows.get(key)
        if row is None:
            return None, None, None
        return row["five"], row["five_text"], row["five_coverage"]

    def ext(key):
        cells = extra.get(key)
        if isinstance(cells, str):
            return {"value": None, "note": cells, "coverage": None}
        return None if cells is None else _extra_five(cells, key)

    def from_cells(ind, label, kind, unit, key, noun, template, **more):
        f = ext(key)
        if f is None:
            return _line(ind, label, kind, unit, None, None, WORDS_SUMMARY["cell_unavailable"])
        if f["value"] is None:
            return _line(ind, label, kind, unit, None, None, f.get("note"), f.get("coverage"))
        if f.get("text") and "not counting" in f["text"]:
            text = f"{kind}: {f['text']}."
        else:
            text = template.format(count=_count_text(noun, f["value"]), **more)
        return _line(ind, label, kind, unit, f["value"], text, None, f.get("coverage"))

    def counted(ind, label, kind, unit, key, noun, template, **more):
        n, t, c = rv(key)
        text = template.format(count=_count_text(noun, n), **more) if n is not None else None
        if n is not None and t and "not counting" in t:
            text = f"{kind}: {t}."
        return _line(ind, label, kind, unit, n, text, t, c)

    n1, t1, c1 = rv("radar_1in")
    big_t = rv("radar_max")[1]
    lines["hail_size_days"] = _line(
        "hail_size_days", "Hail of 1 inch or more (days, radar estimate)", "Radar estimate", "days", n1,
        L["hail_size_days"].format(count=_count_text("days", n1), largest=big_t) if n1 is not None else None, t1, c1)
    lines["hail_reports"] = counted("hail_reports", "Hail reports within 5 miles (count)", "Report", "count", "hail_n",
                                    "hail_n", "Report: {count} within 5 miles in these five years")
    if lines["hail_reports"]["value"] is not None:
        lines["hail_reports"]["text"] = L["hail_reports"].format(count=_count_text("hail_n", lines["hail_reports"]["value"]),
                                                                 largest=rv("hail_max")[1])
    lines["hail_signatures"] = from_cells("hail_signatures", "Radar detections within 2 miles (days)", "Radar detection",
                                          "days", "hail_signatures", "signature", L["hail_signatures"])
    lines["hail_warnings"] = from_cells("hail_warnings", "Severe thunderstorm warnings covering this cell or part of it (count)",
                                        KIND_WARNING, "count", "hail_warnings", "sv", L["hail_warnings"])
    gust = spot.gust or {"name": "the nearest station", "miles": "?"}
    ng, tg, cg = rv("gust_days")
    lines["wind_gust_days"] = _line(
        "wind_gust_days", "Peak gust of 50 knots (58 mph) or more (days, station reading)", "Station reading", "days", ng,
        L["wind_gust_days"].format(count=_count_text("days", ng), station=gust["name"], miles=gust["miles"])
        if ng is not None else None, _gust_why(rows) or tg, cg)
    wind_auto = int((rows.get("wind_n") or {}).get("automated") or 0)
    auto_text = (WORDS_SUMMARY["auto_roof_one"] if wind_auto == 1
                 else WORDS_SUMMARY["auto_roof_many"].format(n=wind_auto) if wind_auto > 1 else "")
    lines["wind_reports"] = counted("wind_reports", "Wind reports within 5 miles (count)", "Report", "count", "wind_n",
                                    "wind_n", L["wind_reports"], auto=auto_text)
    lines["wind_zone_warnings"] = counted("wind_zone_warnings", "High wind watches and warnings for the zone (count)",
                                          "Zone product", "count", "hw_zone", "hw_zone", L["wind_zone_warnings"])
    tf = [ext("tornado_reports"), ext("records_tornado"), ext("tornado_warnings")]
    if all(f is not None and f["value"] is not None for f in tf):
        lines["tornado_funnel"] = _line(
            "tornado_funnel", "Tornado, funnel cloud and landspout reports (count)", "Report", "count", tf[0]["value"],
            L["tornado_funnel"].format(count=_count_text("tornado", tf[0]["value"]),
                                       count_nc=_count_text("tornado_nc", tf[1]["value"]),
                                       count_w=_count_text("tor_warn", tf[2]["value"])))
    else:
        why = next((f["note"] for f in tf if f and f.get("note")), None)
        lines["tornado_funnel"] = _line("tornado_funnel", "Tornado, funnel cloud and landspout reports (count)", "Report",
                                        "count", None, None, why)
    lines["freeze_thaw_days"] = counted("freeze_thaw_days", "Freeze-thaw days", "Grid estimate", "days", "freeze_thaw",
                                        "freeze", L["freeze_thaw_days"])
    lines["days_low_below_32"] = counted("days_low_below_32", "Days with a low below 32 F", "Grid estimate", "days",
                                         "frost32", "days", L["days_low_below_32"])
    lines["days_high_90"] = counted("days_high_90", "Days with a high of 90 F or more", "Grid estimate", "days", "hot90",
                                    "days", L["days_high_90"])
    tx, tn = rows.get("tmax"), rows.get("tmin")
    if tx and tn and tx["five"] is not None and tn["five"] is not None:
        lines["temperature_extremes"] = _line(
            "temperature_extremes", "Highest high and lowest low (F, with date)", "Grid estimate", "F", tx["five"],
            L["temperature_extremes"].format(hi=tx["five_text"], lo=tn["five_text"]))
    else:
        why = (tx or {}).get("five_text") or (tn or {}).get("five_text")
        lines["temperature_extremes"] = _line("temperature_extremes", "Highest high and lowest low (F, with date)",
                                              "Grid estimate", "F", None, None, why)
    ns, ts, cs = rv("snow")
    lines["snowfall_season"] = _line(
        "snowfall_season", "Snowfall, July to June (inches, station reading)", "Station reading", "in", ns,
        L["snowfall_season"].format(total=WORDS_SUMMARY["in_plain"].format(inches=stations.fmt_in(ns)))
        if ns is not None else None, ts, cs)
    nd, td, cd = rv("snow_depth")
    lines["snow_depth"] = _line(
        "snow_depth", "Deepest snow on the ground (inches, station reading)", "Station reading", "in", nd,
        L["snow_depth"].format(largest=td) if nd is not None else None, td, cd)
    if isinstance(dl_cells, str):
        lines["ice_dam_weather_days"] = _line("ice_dam_weather_days",
                                              "Days with 1 inch or more on the ground and a low below 32 F", "Station reading",
                                              "days", None, None, dl_cells)
    elif dl_cells is not None:
        dl = _five(dl_cells, "sum", None, "station record", "")
        lines["ice_dam_weather_days"] = _line(
            "ice_dam_weather_days", "Days with 1 inch or more on the ground and a low below 32 F", "Station reading", "days",
            dl["value"], L["ice_dam_weather_days"].format(count=_count_text("days", dl["value"])) if dl["value"] is not None
            else None, dl.get("note"), dl.get("coverage"))
    else:
        lines["ice_dam_weather_days"] = _line("ice_dam_weather_days",
                                              "Days with 1 inch or more on the ground and a low below 32 F", "Station reading",
                                              "days", None, None, WORDS_SUMMARY["none_station"])
    lines["freezing_rain_reports"] = counted("freezing_rain_reports", "Freezing rain reports within 5 miles (count)", "Report",
                                             "count", "freezing_rain_n", "freezing_rain_n", L["freezing_rain_reports"])
    lines["ice_storm_warnings"] = from_cells("ice_storm_warnings", "Ice storm warnings for the zone (count)", "Zone product",
                                             "count", "ice_storm", "ice_storm", L["ice_storm_warnings"])
    lines["winter_storm_warnings"] = from_cells("winter_storm_warnings", "Winter storm warnings for the zone (count)",
                                                "Zone product", "count", "winter_storm", "winter_storm",
                                                L["winter_storm_warnings"])
    npr, tpr, cpr = rv("precip")
    lines["precipitation_year"] = _line(
        "precipitation_year", "Precipitation (inches, grid estimate)", "Grid estimate", "in", npr,
        L["precipitation_year"].format(total=tpr) if npr is not None else None, tpr, cpr)
    npm, tpm, cpm = rv("precip_max")
    lines["largest_one_day_rain"] = _line(
        "largest_one_day_rain", "Largest one-day precipitation (inches, grid estimate)", "Grid estimate", "in", npm,
        L["largest_one_day_rain"].format(largest=tpm) if npm is not None else None, tpm, cpm)
    lines["rain_reports"] = from_cells("rain_reports", "Rain reports within 5 miles (count)", "Report", "count",
                                       "rain_reports", "rain_n", L["rain_reports"])
    nfl, tfl, cfl = rv("flood_report_n")
    nfw, tfw, cfw = rv("flood_warn")
    lines["flood_reports_warnings"] = _line(
        "flood_reports_warnings", "Flood and flash flood reports and warnings (count)", "Report", "count", nfl,
        L["flood_reports_warnings"].format(count=_count_text("flood_report_n", nfl), count_w=_count_text("flood_warn", nfw))
        if nfl is not None and nfw is not None else None, tfl or tfw, cfl)
    heat = [ext("heat_advisory"), ext("excessive_heat"), ext("extreme_heat")]
    if all(h is not None and h["value"] is not None for h in heat):
        partial_h = "not counting" in (heat[0].get("text") or "")
        heat_text = (L["heat_reports_warnings_partial"].format(count_h=heat[0]["text"],
                                                               count_e=_count_text("excessive_heat", heat[1]["value"]),
                                                               count_x=_count_text("xheat", heat[2]["value"]))
                     if partial_h else
                     L["heat_reports_warnings"].format(count_h=_count_text("heat_advisory", heat[0]["value"]),
                                                       count_e=_count_text("excessive_heat", heat[1]["value"]),
                                                       count_x=_count_text("xheat", heat[2]["value"])))
        lines["heat_reports_warnings"] = _line(
            "heat_reports_warnings", "Heat advisories, excessive heat warnings and extreme heat reports (count)",
            "Zone product", "count", heat[0]["value"], heat_text, None, heat[0].get("coverage"))
    else:
        why = next((h["note"] for h in heat if h and h.get("note")), None)
        lines["heat_reports_warnings"] = _line(
            "heat_reports_warnings", "Heat advisories, excessive heat warnings and extreme heat reports (count)",
            "Zone product", "count", None, None, why)
    held = WORDS_INDICATORS["held"]
    held_names = {"ponding": "Water ponding on a roof", "roof_surface_temperature": "Roof surface temperature at this spot",
                  "fema_flood_zones": "Flood zones (FEMA)", "lightning": "Lightning", "uv_and_sun": "UV and sunlight",
                  "ground_snow_load": "Ground snow load (design map value)",
                  "snotel": "Snow water equivalent at a SNOTEL site"}
    groups = []
    for gkey, gname in GROUPS:
        refs = []
        for rid in WORDS_INDICATORS["refs"].get(gkey, ()):
            ref = REFERENCE_LINES[rid]
            refs.append({"id": rid, "kind": "Reference", "source": ref["source"], "url": ref["url"],
                         "text": f"{ref['source']}: “{ref['quote']}”"})
        groups.append({"key": gkey, "name": gname,
                       "lines": [lines[i] for i in INDICATOR_GROUPS.get(gkey, ())],
                       "references": refs,
                       "held": [{"id": h, "kind": "Data unavailable", "label": held_names[h], "text": held[h]}
                                for h in HELD_GROUPS.get(gkey, ())]})
    return {"title": WORDS_SUMMARY["section_titles"]["roof"], "lead": WORDS_INDICATORS["section_lead"],
            "kind_key": WORDS_INDICATORS["kind_key"], "groups": groups,
            "how_made": list(WORDS_INDICATORS["how_made_roof"]),
            "lines": sum(len(g["lines"]) for g in groups)}


def _extra(spot: _Spot, events: dict | None, tile: dict | None, lsr: list[dict] | None) -> dict:
    """The roof counts the table does not carry, as season cells. A count whose part did not load is that part's own
    sentence instead (D16): never a count of nothing."""
    out = {}
    tile = tile or {}
    lsr = lsr or []

    def blocked(part: str):
        state, reason, _periods = spot.joins_part(part)
        if state == "unavailable":
            return joins._unavailable_text(part, reason)
        if not tile:
            return joins._unavailable_text(part, joins.WORDS_JOINS["reason_no_answer"])
        if part in ("reports", "records", "warnings") and events is None:
            return joins._unavailable_text(part, joins.WORDS_JOINS["reason_events"])
        return None

    def put(key: str, part: str, make) -> None:
        msg = blocked(part)
        out[key] = msg if msg else make()

    def detection_days() -> list:
        """The SPC report days of the hail signatures within 2 miles; a day counts once, however many rows it has."""
        return sorted({joins.spc_day(joins.utc_from_row(d_, t_))
                       for d_, t_, lat, lon, _size in tile.get("detections", [])
                       if joins.haversine_km(spot.lat, spot.lon, lat, lon) / joins.MILE_KM <= joins.DETECT_MILES})

    put("hail_signatures", "detections", lambda: _count_cells(spot, detection_days(), "days"))
    put("hail_warnings", "warnings",
        lambda: _count_cells(spot, spot.polygons_covering(events, ("SV",), "W"), "sv"))
    put("tornado_warnings", "warnings",
        lambda: _count_cells(spot, spot.polygons_covering(events, ("TO",), "W"), "tornado"))
    put("records_tornado", "records",
        lambda: _count_cells(spot, [r["day"] for r in spot.records_within(events)
                                    if r["code"] in ("tornado", "funnel cloud")], "tornado_nc"))
    put("tornado_reports", "reports",
        lambda: _count_cells(spot, [r["day"] for r in lsr if r["kind"] in ("tornado", "funnel cloud", "landspout")],
                             "tornado"))
    put("rain_reports", "reports", lambda: _count_cells(spot, [r["day"] for r in lsr if r["kind"] == "rain"], "rain_n"))
    put("extreme_heat", "reports",
        lambda: _count_cells(spot, [r["day"] for r in lsr if r["kind"] == "extreme heat"], "xheat"))

    def zone_cells(kinds: tuple, sigs: tuple, noun: str, family: str | None):
        msg = blocked("zones")
        if msg:
            return msg
        days = spot.zone_events(tile, kinds, sigs)
        if days is None:
            return joins._unavailable_text("zones", "the zone file did not load")
        return _zone_cells(spot, tile, days, noun, family)

    out["heat_advisory"] = zone_cells(("HT",), ("Y",), "heat_advisory", "heat_advisory")
    out["excessive_heat"] = zone_cells(("EH",), ("W",), "excessive_heat", None)
    out["ice_storm"] = zone_cells(("IS",), ("W",), "ice_storm", None)
    out["winter_storm"] = zone_cells(("WS",), ("W",), "winter_storm", "winter_storm")
    return out


def _sections(rows: dict, roof: dict, extra: dict, gauge_lines, gust=None, section_notes=None) -> list[dict]:
    """The eleven sections in the brief's order: a heading, one lead sentence with its kind word (the five-season figures
    of the table and the roof lines), and the sentence's kind. The rows under each heading are built by the page from the
    same records. On a town page the flooding section also carries the river gauge lines (D6); the heat and flooding
    sections carry the Montana statement of zone products that could not be placed (section_notes; B5 D27)."""
    W = WORDS_SUMMARY
    T = W["section_titles"]

    def five_text(key: str) -> str:
        row = rows.get(key)
        if row is None or row.get("five") is None:
            return WORDS_SUMMARY["cell_unavailable"]
        return row["five_text"]

    def count_text(noun: str, key: str) -> str:
        row = rows.get(key)
        if row is None or row.get("five") is None:
            return WORDS_SUMMARY["cell_unavailable"]
        if "not counting" in (row.get("five_text") or ""):
            return row["five_text"]
        return _count_text(noun, row["five"])

    def extra_count(noun: str, key: str) -> str:
        cells = extra.get(key)
        if cells is None or isinstance(cells, str):
            return WORDS_SUMMARY["cell_unavailable"]
        five = _extra_five(cells, key)
        if five is None or five["value"] is None:
            return WORDS_SUMMARY["cell_unavailable"]
        if "not counting" in five["text"]:
            return five["text"]
        return _count_text(noun, five["value"])

    def auto_clause(key: str) -> str:
        n = int((rows.get(key) or {}).get("automated") or 0)
        return W["auto_lead"].format(n=n) if n else ""

    station_name = (gust or {}).get("name", "the nearest station")
    if (rows.get("gust_days") or {}).get("five") is None:
        wind_lead = W["lead_wind_unavailable"].format(station=station_name, wind=count_text("wind_n", "wind_n"),
                                                      auto=auto_clause("wind_n"))
    else:
        wind_lead = W["lead_wind"].format(gust=count_text("days", "gust_days"), station=station_name,
                                          wind=count_text("wind_n", "wind_n"), auto=auto_clause("wind_n"))
    snow_row = rows.get("snow") or {}
    snow_names = {s for s in (snow_row.get("stations") or []) if s}
    if snow_row.get("five") is not None and len(snow_names) > 1:
        snow_lead = W["lead_snow_two"].format(snow=W["in_plain"].format(inches=stations.fmt_in(snow_row["five"])),
                                              count=_number_word(len(snow_names)), depth=five_text("snow_depth"))
    else:
        snow_lead = W["lead_snow"].format(snow=five_text("snow"), depth=five_text("snow_depth"))

    leads = {
        "hail": W["lead_hail"].format(radar=count_text("days", "radar_1in"), reports=count_text("hail_n", "hail_n")),
        "wind": wind_lead,
        "storms": W["lead_storms"].format(hw=count_text("hw_zone", "hw_zone"),
                                          sv=extra_count("sv", "hail_warnings")),
        "temperature": W["lead_temperature"].format(tmax=five_text("tmax"), tmin=five_text("tmin")),
        "rain": W["lead_rain"].format(precip=five_text("precip"), pmax=five_text("precip_max")),
        "snow": snow_lead,
        "flooding": W["lead_flood"].format(flood=count_text("flood_report_n", "flood_report_n"),
                                           flood_w=count_text("flood_warn", "flood_warn")),
        "ice": W["lead_ice"].format(fr=count_text("freezing_rain_n", "freezing_rain_n"),
                                    ice=count_text("ice_warn", "ice_warn")),
        "heat": W["lead_heat"].format(hot=count_text("days", "hot90"), xheat=extra_count("xheat", "extreme_heat")),
        "roof": W["lead_roof"],
        "made": W["lead_made"],
    }
    kinds = {"hail": "Radar estimate", "wind": "Station reading", "storms": "Zone product",
             "temperature": "Grid estimate", "rain": "Grid estimate", "snow": "Station reading", "flooding": "Report",
             "ice": "Report", "heat": "Grid estimate", "roof": "Reference", "made": "Reference"}
    notes = section_notes or {}
    out = []
    for sid in ("hail", "wind", "storms", "temperature", "rain", "snow", "flooding", "ice", "heat", "roof", "made"):
        entry = {"id": sid, "heading": T[sid], "lead": leads[sid], "kind": kinds[sid]}
        if sid == "flooding" and gauge_lines:
            entry["lines"] = list(gauge_lines)
        if notes.get(sid):
            entry["notes"] = [notes[sid]]
        out.append(entry)
    return out


def _how_made() -> list[str]:
    """How this was made: the sources and their terms (quoted where the source gives its words), the distance and
    coverage rules, the units and the licence sentences. Plain words; the page shows them under its own heading."""
    lines = list(climate.WORDS_CLIMATE["how_made"])
    lines += [
        "Radar: NOAA MRMS MESH, the 24-hour maximum, 12:00 UTC files (NOAA Open Data on AWS). A day is a storm-report day, from 12:00 UTC to 12:00 UTC. Sizes are in inches to the hundredth, rounded down. A radar estimate can miss hail that people reported and can show hail that no one reported.",
        "Reports and warnings: NWS local storm reports, warnings and zone products from the Iowa Environmental Mesonet. “The materials found on this website are in the public domain and may be used freely by anyone for any lawful purpose.” “Attributing the Iowa Environmental Mesonet of Iowa State University would be appreciated.”",
        "Warnings and zones: “The information on National Weather Service Web servers and Web sites is in the public domain, unless specifically annotated otherwise, and may be used freely by the public.” “You also cannot present information of your own in a way that makes it appear to be official government information.”",
        "Records: NOAA Storm Events (NCEI) point and zone rows. The use terms of this copy were not read in this build, so they are not quoted.",
        "Gusts: IEM daily summaries of the airport stations. Gusts of 130 kt or more are dropped and counted as implausible; two readings are flagged for check, and the flag shows with them.",
        "Stations: NOAA GHCN-Daily from NCEI, public domain in the United States under NCEI-PD-10-2-02, section 4(a). CoCoRaHS records are released under CC BY 3.0 and ask for acknowledgement. A station value shows only when 95 percent of its season's days have the element; a missing day is never zero.",
        "Station rule: the candidates within 40 miles; a station is current for an element when it reported that element within 30 days of the newest date; at least 80 percent of the days 2020 to 2025 have an unflagged value; the two nearest that pass.",
        "Gauges: NWS flood stages (National Water Prediction Service) and USGS annual peaks. Observations courtesy of U.S. Geological Survey. The nearest gauge with a flood stage within 10 miles; it does not say water reached this address.",
        "Counties: US Census Bureau TIGER/Line 2026 county boundaries. “The TIGER/Line shapefile products are not copyrighted; however, TIGER/Line and Census TIGER are registered trademarks of the U.S. Census Bureau. These products are free to use in a product or publication, however acknowledgement must be given to the U.S. Census Bureau as the source.”",
        _size_legend(),
        WORDS_SUMMARY["analysis_held"],
    ]
    return lines


def _size_legend() -> str:
    """The radar and report size classes in inches, from hail.CLASSES (the same classes the radar counts use)."""
    items = []
    for cls in hail.CLASSES:
        span = f"{cls['min_in']:.2f} or more" if cls["max_in"] is None else f"{cls['min_in']:.2f} to {cls['max_in']:.2f}"
        items.append(f"{cls['word']} {span}")
    return "Size classes, inches: " + "; ".join(items) + "."


def _about() -> list[str]:
    return [WORDS_SUMMARY["analysis_held"], joins.WORDS_JOINS["about_hit_miss"]]


# ---------------------------------------------------------------- the public functions

def _result(state: str, problem, spot_place: dict, index: dict | None, table: dict, roof: dict | None,
            sections: list, town_block: dict | None, stale: str | None) -> dict:
    return {
        "format": FORMAT,
        "state": state,
        "problem": problem,
        "place": spot_place,
        "as_of": (index or {}).get("as_of"),
        "window": list((index or {}).get("window") or []),
        "title": WORDS_SUMMARY["table_title"],
        "plain": WORDS_SUMMARY["plain"],
        "table": table,
        "radar_sentence": WORDS_SUMMARY["radar_sentence"],
        "roof": roof,
        "sections": sections,
        "how_made": _how_made(),
        "about": _about(),
        "town": town_block,
        "stale": stale,
    }


def _empty_table() -> dict:
    return {"columns": list(COLUMNS), "rows": [], "partial": None, "held": None}


def describe_summary(store, row: int, col: int, now, town=None) -> dict:
    """The summary for the B1 cell (row, col) of the store in `store` (the directory that holds hail/).

    now is a UTC datetime or date (for the stale line) or None. town is a town slug, or a dict with slug, name, lat and
    lon, for a town page: the station rule then runs at the town point, the two temperature rows are added, and the gauge
    line is read. Returns a plain dict: state ("loaded", "partial", "unavailable" or "outside"), problem, place, as_of,
    window, the table (columns, rows, the partial line and the held row), the radar sentence, the roof section, the
    sections' leads, how made, about, the town block and the stale line. Every number in the table is an integer or
    null, and each row says its kind word and unit; nothing in the result says damage, risk or an all-clear except the
    fixed sentence "This is not an all-clear."."""
    root = Path(store)
    town_doc = _town_from(town)
    place = {"row": row, "col": col, "town": town_doc["slug"] if town_doc else None,
             "name": town_doc["name"] if town_doc else None, "lat": None, "lon": None, "tile": None}
    try:
        index = hail.load_index(root)
    except hail.HailStoreError as exc:
        return _result("unavailable", str(exc), place, None, _empty_table(), None, [], None, None)
    if not hail.in_grid(row, col):
        return _result("outside", hail.WORDS["outside"], place, index,
                       _empty_table(), None, [], None, None)
    spot = _Spot(root, index, row, col, town_doc)
    place.update(lat=round(spot.lat, 5), lon=round(spot.lon, 5), tile=spot.tile)
    problems: list[str] = []
    rows: dict[str, dict] = {}

    def guard(name, fn):
        try:
            return fn()
        except (hail.HailStoreError, SummaryError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            problems.append(f"{name}: {exc}")
            return None

    try:
        days = hail.cell_events(root, spot.lat, spot.lon, index)
    except hail.HailStoreError as exc:
        days = None
        problems.append(f"radar: {exc}")
        rows.update({k: _unavailable_row(_spec(k), hail.WORDS["unavailable"].format(problem=str(exc)))
                     for k in ("radar_max", "radar_1in")})
    else:
        if days is None:
            return _result("outside", "the spot is outside Montana", place, index, _empty_table(), None, [], None, None)
        radar = guard("radar", lambda: _radar_rows(spot, days))
        if radar is None:
            rows.update({k: _unavailable_row(_spec(k), hail.WORDS["unavailable"].format(problem="the radar rows could not be built"))
                         for k in ("radar_max", "radar_1in")})
        else:
            rows["radar_max"], rows["radar_1in"] = radar
    tile = guard("joins tile", spot.joins_tile)
    events = guard("joins events", spot.events)
    reports = guard("reports", lambda: _reports_rows(spot, events))
    if reports is None:
        reports = {k: _unavailable_row(_spec(k), joins.WORDS_JOINS["unavailable"].format(
            part=joins.WORDS_JOINS["part_reports"], one=joins.WORDS_JOINS["one_reports"]))
            for k in ("hail_max", "hail_n", "wind_n", "freezing_rain_n", "flood_report_n")}
    rows.update(reports)
    gstate, greason, gperiods = spot.joins_part("stations")
    if gstate == "unavailable" or tile is None:
        sentence = joins._unavailable_text("stations", greason if tile is not None else joins.WORDS_JOINS["reason_no_answer"])
        rows["gust_days"] = _unavailable_row(_spec("gust_days"), sentence)
        rows["gust_max"] = _unavailable_row(_spec("gust_max"), sentence)
    else:
        gusts = guard("gusts", lambda: _gust_rows(spot, tile))
        if gusts is None:
            sentence = joins._unavailable_text("stations", joins.WORDS_JOINS["reason_no_answer"])
            gusts = (_unavailable_row(_spec("gust_days"), sentence), _unavailable_row(_spec("gust_max"), sentence))
        rows["gust_days"], rows["gust_max"] = gusts
        if gstate == "partial":
            note = joins._unavailable_text("stations", greason, gperiods)
            rows["gust_days"]["notes"].append(note)
            rows["gust_max"]["notes"].append(note)
    rows.update(guard("warnings", lambda: _warning_rows(spot, events)) or
                {"flood_warn": _unavailable_row(_spec("flood_warn"), joins._unavailable_text("warnings", joins.WORDS_JOINS["reason_no_answer"]))})
    rows.update(guard("zones", lambda: _zone_rows(spot, tile)) or
                {k: _unavailable_row(_spec(k), joins._unavailable_text("zones", joins.WORDS_JOINS["reason_no_answer"]))
                 for k in ("hw_zone", "ice_warn")})
    rows.update(guard("counties", lambda: _county_rows(spot, tile)) or
                {"county_watch": _unavailable_row(_spec("county_watch"), joins.WORDS_JOINS["county_unavailable"])})
    climate_rows = guard("grid", lambda: _climate_part(spot))
    if climate_rows is None:
        climate_rows = {k: _unavailable_row(_spec(k), climate.WORDS_CLIMATE["unavailable"].format(part="Temperature", part_lower="temperature"))
                        for k in CLIMATE_KEYS}
    rows.update(climate_rows)
    station_rows = guard("stations", lambda: _station_part(spot))
    if station_rows is None:
        station_rows = {k: _unavailable_row(_spec(k), WORDS_SUMMARY["unavailable_part"].format(part="Station readings", part_lower="station readings"))
                        for k in ("snow", "snow_depth")}
    rows.update(station_rows)
    rows["held"] = _held_row()

    # the partial season (D20) and the roof section, from the same records
    grid = spot.climate_cell()
    partial_rec = grid[1]["s"][5] if grid[0] == "ok" else None
    through = spot.cb.get("through")
    reports_state = spot.joins_part("reports")
    lsr_all = None
    if events is not None and reports_state[0] != "unavailable" and tile:
        lsr_all = guard("reports list", lambda: spot.lsr_within(events))
    radar_days = days if isinstance(days, list) else None
    partial_text = guard("partial", lambda: _partial(spot, partial_rec, through, lsr_all, radar_days)) or ""
    if reports_state[0] == "unavailable" or lsr_all is None and events is None:
        partial_text = (partial_text + " " if partial_text else "") + joins._unavailable_text(
            "reports", reports_state[1] if reports_state[0] == "unavailable" else joins.WORDS_JOINS["reason_events"])
    extra = guard("roof counts", lambda: _extra(spot, events, tile, lsr_all)) or {}
    dl = guard("ice dam days", lambda: _dl_cells(spot))
    roof = guard("roof", lambda: _roof(spot, rows, extra, dl))
    if roof is None:
        roof = {"title": WORDS_SUMMARY["section_titles"]["roof"], "lead": WORDS_INDICATORS["section_lead"],
                "kind_key": WORDS_INDICATORS["kind_key"], "groups": [], "how_made": [], "lines": 0}
        problems.append("roof: the roof lines could not be built")

    # the table, in the brief's order (the town rows only on a town page)
    table_rows = []
    for key in ROW_KEYS:
        spec = _spec(key)
        if spec.get("town_only") and not town_doc:
            continue
        row_obj = rows.get(key)
        if row_obj is None:
            row_obj = _unavailable_row(spec, WORDS_SUMMARY["cell_unavailable"])
        table_rows.append(row_obj)
    gauge_lines = None
    town_block = None
    if town_doc:
        gauge_lines = spot.gauge_line(town_doc["slug"], town_doc["name"])
        if spot.gauge_problem:
            problems.append("river gauge: " + spot.gauge_problem)
        snow_state, snow_chosen, _ = spot.chosen("SNOW")
        tmax_state, tmax_chosen, _ = spot.chosen("TMAX")
        tmin_state, tmin_chosen, _ = spot.chosen("TMIN")
        town_block = {"slug": town_doc["slug"], "name": town_doc["name"],
                      "point": {"lat": town_doc["lat"], "lon": town_doc["lon"]},
                      "stations": {"snow": snow_chosen, "tmax": tmax_chosen, "tmin": tmin_chosen},
                      "gauge": gauge_lines}
    partial = {"label": PARTIAL, "text": partial_text or WORDS_SUMMARY["partial_none"].format(season=PARTIAL)}
    table = {"columns": list(COLUMNS), "rows": table_rows, "partial": partial, "held": WORDS_INDICATORS["held"]["lightning"]}
    sections = _sections(rows, roof, extra, gauge_lines, spot.gust, _section_notes(spot))
    stale = None
    if now is not None and index.get("as_of"):
        today = now.date() if isinstance(now, datetime) else now
        if today - date.fromisoformat(index["as_of"]) > timedelta(days=STALE_DAYS):
            stale = WORDS_SUMMARY["stale"].format(as_of=_fmt_date(date.fromisoformat(index["as_of"])))
    partial_state = any(r.get("notes") and any("could not be loaded" in n for n in r["notes"]) for r in table_rows)
    state = "partial" if (problems or partial_state) else "loaded"
    return _result(state, "; ".join(problems) if problems else None, place, index, table, roof, sections, town_block, stale)


def map_data_summary(index: dict | None) -> dict:
    """The summary's words, row order, kind words and units for the browser (part B2 fills them). The templates are the
    same strings Python uses; the browser divides each integer by the row's scale and shows it to its decimals."""
    loaded = isinstance(index, dict) and bool(index.get("window"))
    return {
        "format": FORMAT,
        "state": "loaded" if loaded else "unavailable",
        "seasons": list(FIVE),
        "partial": PARTIAL,
        "columns": list(COLUMNS),
        "rows": [{"key": r["key"], "label": r["label"], "kind": r["kind"], "unit": r["unit"],
                  "scale": UNIT_SPEC[r["unit"]]["scale"], "decimals": r.get("decimals", UNIT_SPEC[r["unit"]]["decimals"]),
                  "source": r["source"], "town_only": bool(r.get("town_only"))} for r in ROWS],
        "row_order": list(ROW_KEYS),
        "kind_words": list(KIND_WORDS),
        "units": UNIT_SPEC,
        "words": dict(WORDS_SUMMARY),
        "indicators": {"words": WORDS_INDICATORS, "groups": [list(g) for g in GROUPS],
                       "indicator_groups": {k: list(v) for k, v in INDICATOR_GROUPS.items()},
                       "held_groups": {k: list(v) for k, v in HELD_GROUPS.items()},
                       "references": REFERENCE_LINES},
        "thresholds": climate.THRESHOLDS,
        "rule": {"radius_miles": TOWN_RADIUS, "fresh_days": stations.FRESH_DAYS, "cover_min": stations.COVER_MIN,
                 "season_min": SEASON_SHARE, "gust_kt": GUST_KT, "one_inch_tenths": ONE_INCH_TENTHS,
                 "floor_tenths": FLOOR_TENTHS, "wind_codes": list(WIND_CODES)},
    }
