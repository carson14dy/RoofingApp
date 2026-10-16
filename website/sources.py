"""Public weather sources for the website: NWS alerts and forecasts, SPC storm reports, NOAA radar.

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

# Flag thresholds. These are placeholders until the company sets its own limits (DECISIONS D16).
LIMITS = {"wind_mph": 20, "gust_mph": 25, "pop_pct": 30, "cold_f": 40, "hot_f": 95}

# What each feed sends and how this site treats it. Change the parser, this table and
# tests/test_site.py together (AGENTS.md rule 7). Shown on the About page.
CONTRACTS = {
    "alerts": {
        "name": "NWS alerts",
        "request": "api.weather.gov/alerts/active?area=MT, and ?point=lat,lon for each town",
        "units": "Times in ISO 8601 with an offset, shown in Montana time. Area as an outline, or none.",
        "timing": "Fetched at every build (about every 10 minutes).",
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
    "basemap": {
        "name": "Map outlines and names",
        "request": "Natural Earth 10m (public domain) and US Census county lines (us-atlas 3.0.1), built into "
                   "static/map/basemap.json by tools/build_basemap.py",
        "units": "Longitude and latitude, rounded to 4 decimals and simplified for statewide viewing.",
        "timing": "Built by hand when the map changes; served by this site.",
        "missing": "Without the outlines the map still shows the weather layers and towns.",
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
    return {"forecast": p["forecast"], "hourly": p["forecastHourly"], "grid": p["forecastGridData"],
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
