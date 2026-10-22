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

# What each feed sends and how this site treats it. Change the parser, this table and
# tests/test_site.py together (AGENTS.md rule 7). Shown on the About page.
CONTRACTS = {
    "alerts": {
        "name": "NWS alerts",
        "request": "api.weather.gov/alerts/active?area=MT, and ?point=lat,lon for each town",
        "units": "Times in ISO 8601 with an offset, shown in Montana time. Area as an outline, or none.",
        "timing": "Fetched at every build (a schedule set to every 10 minutes; each page says when it was built).",
        "missing": "No readable list means the check failed: the last verified list stays up with its time. "
                   "An alert without an outline is listed with a note. Test messages and replaced updates are left out.",
    },
    "points": {
        "name": "NWS forecast grid lookup",
        "request": "api.weather.gov/points/lat,lon",
        "units": "Links to the forecasts for the 2.5 km grid square, the NWS office and time zone.",
        "timing": "Every build; the last good lookup is reused if it fails.",
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
        "units": "Station id, name, position and elevation in metres (shown in feet). The distance from the "
                 "town is worked out here, in miles; the nearest three are read.",
        "timing": "Every build; the last good list is reused if it fails.",
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
        "missing": "\"UNK\" wind stays unknown. A file that fails is listed as a problem; no report is not \"no hail\".",
    },
    "radar": {
        "name": "NOAA radar estimate (MRMS)",
        "request": "noaa-mrms-pds.s3.amazonaws.com, CONUS/PrecipRate_00.00, one GRIB2 file every 2 minutes",
        "units": "Precipitation rate in mm/h as liquid water, shown in in/h. A 0.01° latitude-longitude grid; "
                 "the map uses one frame every 10 minutes for the past hour.",
        "timing": "NOAA publishes a new grid every 2 minutes; a newest frame older than 30 minutes is reported as stale.",
        "missing": "Negative values mean no radar coverage: those areas are hatched, never drawn as dry. "
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
        "missing": "-99 and -999 mean no radar value; their meaning is not verified, and they are never a value or 0. "
                   "Heights below the town's ground height are counted and not used. A town whose NWS grid height "
                   "didn't load gets 'Echo top not available', never a value. No echo at 35 dBZ is not an all-clear. "
                   "A radar estimate, not observed hail or damage.",
    },
    "satellite": {
        "name": "NOAA GOES satellite picture (band 13, observation)",
        "request": "noaa-goes19.s3.amazonaws.com (GOES-East; GOES-West noaa-goes18 if East fails or has no scan in "
                   "the last hour), ABI-L2-CMIPC band 13: one NetCDF file per 5-minute CONUS scan; the newest scan "
                   "of the current or previous UTC hour",
        "units": "Infrared brightness temperature in kelvin at 2 km (nadir), drawn as one picture on the map's image box. "
                 "An observation: not a height, not a hail signal. An uncorrected cloud top is drawn away from the "
                 "satellite (north-west for GOES-East, north-east for GOES-West), about 3 to 4 km for a 2 km top and "
                 "20 to 33 km for a 12 to 15 km top",
        "timing": "A new scan every 5 minutes, on the bucket about 30 s after the scan ends. A newest scan older than "
                  "20 minutes is reported as stale; none within 60 minutes: no picture",
        "missing": "Fill values, raw values outside the file's valid range, quality flags other than 0 and cells outside "
                   "the satellite's grid are hatched as no satellite data, never drawn as clear sky. If the file doesn't "
                   "load, the map says so and shows no satellite picture. Not an all-clear.",
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
                  "shows here on the next rebuild. Each page shows the store's as-of date. A build "
                  "waits for the store job of its own commit before it reads the store. A store whose last day is more "
                  "than three days old is a failed source: the pages keep it with the stale line, and a branch preview "
                  "fails.",
        "missing": "-1 (missing) and -3 (no coverage) are never stored. A cell with no stored value on a day is no radar "
                   "estimate, never 'no hail'. A day with no file is listed on the page and not counted, and a day that "
                   "fails stays missing. An estimate is not a measurement at the ground and not an inspection.",
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
