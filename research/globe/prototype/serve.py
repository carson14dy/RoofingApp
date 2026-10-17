#!/usr/bin/env python3
"""3D storm view prototype: local server (research only; not part of the app).

Standard library only. The browser draws what this server returns. Every fetch, time check,
freshness state, PNG check and alert geometry decision is made here, and the page's JavaScript
(globe.js) only draws what it is given.

    python serve.py [--port 0] [--offline]

Prints PORT=<n> on stdout once listening (port 0 picks a free port). --offline makes no network
calls at all: every live layer reports state "off" with the text "Live feeds are off", the same
text the app's self-test uses.

Endpoints: / (index.html), /globe.js, /globe.css, /api/layers.json, /api/alerts.json,
/api/places.json, /api/radar.json.
"""
import argparse
import itertools
import json
import math
import os
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - without zoneinfo the times show UTC only
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE = os.path.normpath(os.path.join(HERE, "..", "validation-evidence"))
PARALLAX_JSON = os.path.join(EVIDENCE, "parallax.json")
PLACES_JSON = os.path.join(HERE, "fixtures", "places.json")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/globe.js": ("globe.js", "text/javascript; charset=utf-8"),
    "/globe.css": ("globe.css", "text/css; charset=utf-8"),
}

# NWS asks for an identifying User-Agent on api.weather.gov requests.
USER_AGENT = "RoofingApp-globe-prototype (research)"
HTTP_TIMEOUT = 15
PROBE_TIMEOUT = 8
OFFLINE_TEXT = "Live feeds are off"
LOCAL_ZONE = "America/Denver"  # Montana

MONTANA = {"west": -116.8, "south": 43.6, "east": -103.3, "north": 49.75}

# Freshness limits. PROPOSALS for this prototype, not D12 (D12: radar 15 min, alerts 10 min).
LIMIT_MIN = {"goes": 15, "radar": 15, "alerts": 10}

# GIBS serves GOES frames every 10 minutes, about 30-40 minutes behind real time
# (validation-evidence/gibs.json). The probe walks back from now until the Montana tile is imagery.
GIBS_WMTS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
GIBS_CAPS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml"
GOES_LAYERS = [
    {"id": "goes_east_geocolor", "name": "GOES-East GeoColor", "layer": "GOES-East_ABI_GeoColor",
     "matrix": "GoogleMapsCompatible_Level7", "max_zoom": 7, "default_on": True},
    {"id": "goes_east_band13", "name": "GOES-East Band 13 infrared",
     "layer": "GOES-East_ABI_Band13_Clean_Infrared", "matrix": "GoogleMapsCompatible_Level6",
     "max_zoom": 6, "default_on": False},
]
PROBE_STEP_MIN = 10
PROBE_STEPS = 12
PROBE_BUDGET_S = 25


def tile_for(lon, lat, z):
    """Web Mercator tile (x, y) that holds a point, the XYZ scheme GIBS and USGS use."""
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


PROBE_ZOOM = 3
PROBE_TILE = tile_for(-110.0, 47.0, PROBE_ZOOM)  # (1, 2): covers Montana

# NWS radar: the app's own query for the valid time, and the MapServer export for the image.
RADAR_BASE = ("https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
              "radar/radar_base_reflectivity/MapServer")
RADAR_QUERY = RADAR_BASE + "/2/query"
RADAR_EXPORT = RADAR_BASE + "/export"
APP_RADAR_QUERY = {"where": "1=1", "outFields": "idp_validtime,name", "returnGeometry": "false",
                   "orderByFields": "idp_validtime DESC", "resultRecordCount": 1, "f": "json"}
CONUS_RADAR_QUERY = dict(APP_RADAR_QUERY, where="name LIKE 'CONUS%'")
# Same aspect as the Montana box in degrees (13.5 x 6.15), so the image maps linearly onto it.
RADAR_PX = (1280, 583)
EXPORT_PARAMS = {
    "bbox": f"{MONTANA['west']},{MONTANA['south']},{MONTANA['east']},{MONTANA['north']}",
    "bboxSR": "4326", "imageSR": "4326", "size": f"{RADAR_PX[0]},{RADAR_PX[1]}",
    "format": "png", "transparent": "true", "layers": "show:3", "f": "image",
}

NWS_ALERTS = "https://api.weather.gov/alerts/active?area=MT"
NWS_ZONE = "https://api.weather.gov/zones/{kind}/{zid}"
ZONE_FETCH_CAP = 20          # zone outline fetches per alerts request
ZONE_OUTLINE_MAX = 64        # outlines kept in memory (centroids are kept for longer)
ZONE_RETRY_S = 300           # a failed zone is not asked for again for five minutes
ZONE_URL = re.compile(r"^https://api\.weather\.gov/zones/([a-z]+)/([A-Z]{2}[CZ]\d{3})$")
SEVERITY_COLOUR = {"Extreme": "#ff5d5d", "Severe": "#ff8b8b", "Moderate": "#e0a93c", "Minor": "#8ea6bf"}
DEFAULT_COLOUR = "#e9f0f7"

BASE_LAYERS = [
    {"id": "usgs_imagery", "name": "USGS imagery (base map, lower 48)",
     "tile_template": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}",
     "max_zoom": 16, "default_on": True,
     "source": {"name": "USGS National Map, USGS Imagery Only",
                "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer"},
     "legend": ("Base map for orientation: USGS imagery, lower 48 states only. It is not an observation, "
                "so it has no valid time.")},
    {"id": "bluemarble", "name": "NASA Blue Marble (base map, worldwide)",
     "tile_template": GIBS_WMTS + "/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
     "max_zoom": 8, "default_on": True,
     "source": {"name": "NASA GIBS, BlueMarble shaded relief", "url": GIBS_CAPS},
     "legend": ("Base map for orientation: NASA Blue Marble shaded relief, shown at low zoom. It is not an "
                "observation, so it has no valid time.")},
]


class FeedError(Exception):
    """A feed could not be read. The message is plain text and is shown to the user."""


def utcnow():
    return datetime.now(timezone.utc)


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value):
    """ISO 8601 text (NWS, with offsets) or ArcGIS epoch milliseconds, as an aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, timezone.utc)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_text(dt):
    """'02:10 UTC (20:10 MDT)' for the panel. UTC only when zoneinfo is missing."""
    text = dt.astimezone(timezone.utc).strftime("%H:%M UTC")
    if ZoneInfo is not None:
        try:
            text += " (" + dt.astimezone(ZoneInfo(LOCAL_ZONE)).strftime("%H:%M %Z") + ")"
        except Exception:  # missing tz data: keep the UTC text
            pass
    return text


def floor10(dt):
    dt = dt.replace(second=0, microsecond=0)
    return dt - timedelta(minutes=dt.minute % 10)


def host(url):
    return urllib.parse.urlsplit(url).hostname or url


def load_parallax_wording():
    with open(PARALLAX_JSON, encoding="utf-8") as f:
        return json.load(f)["wording"]["ui_legend_uncorrected_phase1"]


def load_places():
    with open(PLACES_JSON, encoding="utf-8") as f:
        doc = json.load(f)
    places = [{"name": p["name"], "lat": float(p["lat"]), "lon": float(p["lon"])} for p in doc["places"]]
    return places, doc.get("provenance", {})


PARALLAX_WORDING = load_parallax_wording()
PARALLAX_SOURCE = "validation-evidence/parallax.json, wording.ui_legend_uncorrected_phase1"

GOES_LEGEND = {
    "goes_east_geocolor": ("Satellite imagery, an observation. GeoColor is a day and night composite of GOES-East "
                           "ABI bands. It is not a hail or damage signal. Cloud base is not observed from "
                           "satellite, so this shows the top surface only. ") + PARALLAX_WORDING,
    "goes_east_band13": ("Satellite infrared brightness temperature (band 13, 10.3 micrometres), an observation. "
                         "It is a temperature, not a cloud height, and not a hail or damage signal. Cloud-top "
                         "height is a separate satellite estimate; this prototype does not draw it. ")
                        + PARALLAX_WORDING,
}
RADAR_LEGEND = ("Radar base reflectivity in dBZ. dBZ is the strength of a radar echo, not hail size and not "
                "damage. No echo here is not clear: a blank area means the radar returned no echo in this "
                "image. Montana has four radars, so coverage has gaps.")
ALERTS_LEGEND = ("Official NWS alerts. An outline is the alert's own polygon, or the forecast-zone outline when "
                 "NWS sent no polygon. A point marks a zone whose outline did not load. Alerts are official "
                 "warnings, not damage reports.")
PLACES_LEGEND = ("Prototype places from the research brief (five points). They are not the app's job or "
                 "property list.")
LIMITS_NOTE = ("Freshness limits (GOES 15 min, radar 15 min, alerts 10 min) are proposals for this prototype, "
               "not D12. Imagery daily is also a proposal; no layer uses it, because a base map carries no "
               "valid time.")


# ----------------------------------------------------------------------------
# Time and state logic (pure: no network, the clock only through `now`)
# ----------------------------------------------------------------------------
def layer_state(valid_time, now, limit_min, *, offline=False, error=None, had_good=False):
    """Return (state, age_min, text). States: live | stale | unavailable | off.

    off: serve.py is offline. unavailable: no valid time, or a failed refresh with nothing good to show.
    stale: the newest data is older than the limit, or a refresh failed and the last good data is shown.
    live: the newest data is within the limit. A failed refresh never shows as live.
    """
    if offline:
        return "off", None, OFFLINE_TEXT
    if valid_time is None:
        return "unavailable", None, "Data unavailable: the source gave no valid time"
    age_min = (now - valid_time).total_seconds() / 60.0
    if age_min < -2.0:
        return "unavailable", age_min, "Data unavailable: the source's valid time is in the future"
    if error:
        if had_good:
            return ("stale", age_min,
                    f"Last refresh failed ({error}); showing the last good data, {age_min:.0f} min old")
        return "unavailable", age_min, f"Data unavailable: {error}"
    if age_min <= limit_min:
        return "live", age_min, f"{age_min:.0f} min old, within the {limit_min}-min limit (proposal)"
    return "stale", age_min, f"{age_min:.0f} min old, over the {limit_min}-min limit (proposal)"


# ----------------------------------------------------------------------------
# PNG reader (standard library): 8-bit, non-interlaced, colour types 0, 2, 3, 4 and 6
# ----------------------------------------------------------------------------
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _unfilter(kind, line, prev, bpp):
    n = len(line)
    if kind == 0:
        return
    if kind == 1:
        for i in range(bpp, n):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif kind == 2:
        for i in range(n):
            line[i] = (line[i] + prev[i]) & 0xFF
    elif kind == 3:
        for i in range(n):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif kind == 4:
        for i in range(n):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = (line[i] + pred) & 0xFF
    else:
        raise ValueError(f"unknown PNG filter {kind}")


def _rgba_pixels(buf, colour, palette, trns):
    if colour == 6:
        return zip(buf[0::4], buf[1::4], buf[2::4], buf[3::4])
    if colour == 2:
        return zip(buf[0::3], buf[1::3], buf[2::3], itertools.repeat(255))
    if colour == 0:
        return zip(buf, buf, buf, itertools.repeat(255))
    if colour == 4:
        return zip(buf[0::2], buf[0::2], buf[0::2], buf[1::2])
    count = len(palette) // 3
    alphas = list(trns or b"")
    table = [(palette[3 * i], palette[3 * i + 1], palette[3 * i + 2], alphas[i] if i < len(alphas) else 255)
             for i in range(count)]
    return (table[i] if i < count else (0, 0, 0, 0) for i in buf)


def png_stats(data):
    """Describe a PNG's pixels with the standard library only. Raises ValueError for anything it
    cannot read, so a caller can say that instead of guessing."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG")
    pos, ihdr, palette, trns, idat = 8, None, None, None, []
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if ihdr is None or not idat:
        raise ValueError("header or image data missing")
    width, height, depth, colour, _, _, interlace = ihdr
    if depth != 8 or colour not in PNG_CHANNELS or interlace != 0:
        raise ValueError(f"unsupported PNG (bit depth {depth}, colour type {colour}, interlace {interlace})")
    if colour == 3 and palette is None:
        raise ValueError("palette missing")
    channels = PNG_CHANNELS[colour]
    stride = width * channels
    raw = zlib.decompress(b"".join(idat))
    if len(raw) < height * (stride + 1):
        raise ValueError("image data is short")
    out = bytearray(height * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        kind = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += stride + 1
        _unfilter(kind, line, prev, channels)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    total = width * height
    opaque = nonblack = 0
    luma_sum = 0.0
    colours = set()
    for r, g, b, a in _rgba_pixels(out, colour, palette, trns):
        colours.add((r, g, b, a))
        if a:
            opaque += 1
            luma_sum += 0.299 * r + 0.587 * g + 0.114 * b
            if r + g + b > 30:
                nonblack += 1
    return {
        "width": width, "height": height, "colour_type": colour, "pixels": total,
        "opaque_fraction": round(opaque / total, 4) if total else 0.0,
        "nonblack_opaque_fraction": round(nonblack / total, 4) if total else 0.0,
        "distinct_colours": len(colours),
        "mean_luma_opaque": round(luma_sum / opaque, 1) if opaque else 0.0,
    }


# ----------------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------------
def http_fetch(url, accept=None, timeout=HTTP_TIMEOUT):
    """GET. Returns (status, body) for any HTTP status. Raises FeedError only if the host is unreachable."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if e.fp else b"")
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise FeedError(f"could not reach {host(url)} ({type(reason).__name__})") from None


def http_json(url, accept="application/json"):
    status, body = http_fetch(url, accept=accept)
    if status != 200:
        raise FeedError(f"HTTP {status} from {host(url)}")
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise FeedError(f"{host(url)} sent a response that is not JSON") from None


# ----------------------------------------------------------------------------
# GOES: find the newest GIBS frame whose Montana tile is imagery
# ----------------------------------------------------------------------------
def goes_probe(spec, t):
    """Fetch one GIBS tile over Montana for time t. Returns (ok, info). The content is checked, not only
    the status: a 200 with a black or flat tile is not imagery (validation-evidence/gibs.json)."""
    x, y = PROBE_TILE
    url = f"{GIBS_WMTS}/{spec['layer']}/default/{iso_z(t)}/{spec['matrix']}/{PROBE_ZOOM}/{y}/{x}.png"
    status, body = http_fetch(url, timeout=PROBE_TIMEOUT)
    info = {"status": status, "bytes": len(body)}
    if status != 200:
        return False, info
    try:
        stats = png_stats(body)
    except ValueError as e:
        info["content"] = {"verdict": f"not checkable ({e})"}
        return False, info
    info["content"] = {k: stats[k] for k in ("width", "height", "opaque_fraction", "distinct_colours",
                                              "mean_luma_opaque")}
    ok = (stats["width"] == 256 and stats["height"] == 256 and stats["opaque_fraction"] >= 0.5
          and stats["distinct_colours"] >= 64 and stats["mean_luma_opaque"] >= 8)
    info["content"]["verdict"] = "imagery" if ok else "not imagery"
    return ok, info


def find_goes_frame(spec, now, probe, budget_s=PROBE_BUDGET_S):
    """Walk back from `now` in 10-minute steps (at most PROBE_STEPS). Returns (time or None, steps)."""
    base = floor10(now)
    started = time.time()
    steps = []
    for k in range(PROBE_STEPS):
        if time.time() - started > budget_s:
            steps.append({"stopped": "probe time budget used"})
            break
        t = base - timedelta(minutes=PROBE_STEP_MIN * k)
        try:
            ok, info = probe(spec, t)
        except FeedError as e:
            ok, info = False, {"error": str(e)}
        steps.append({"t": iso_z(t), **info, "ok": ok})
        if ok:
            return t, steps
    return None, steps


def compact_steps(steps):
    out = []
    for s in steps or []:
        item = {k: s[k] for k in ("t", "status", "ok", "error", "stopped") if k in s}
        content = s.get("content")
        if isinstance(content, dict):
            item["verdict"] = content.get("verdict")
        out.append(item)
    return out


def missing_frame_text(steps):
    errors = [s["error"] for s in steps if "error" in s]
    if steps and len(errors) == len(steps):
        return errors[-1]
    return f"no GIBS imagery frame in the last {len(steps)} ten-minute steps"


def goes_template(spec, t):
    return GIBS_WMTS + "/" + spec["layer"] + "/default/" + iso_z(t) + "/" + spec["matrix"] + "/{z}/{y}/{x}.png"


# ----------------------------------------------------------------------------
# Feeds: each keeps its last good value; a failed refresh never clears it
# ----------------------------------------------------------------------------
class FeedCache:
    """Last-good cache for one feed. get() returns (value, error, ok_at, detail). A failed refresh
    keeps the last good value, so a warning is never cleared by a failed request."""
    ttl = 60

    def __init__(self):
        self.lock = threading.Lock()
        self.value = None
        self.error = None
        self.ok_at = None
        self.tried_at = None
        self.detail = None

    def refresh(self):
        raise NotImplementedError

    def get(self):
        with self.lock:
            if self.tried_at is None or time.time() - self.tried_at >= self.ttl:
                self.tried_at = time.time()
                try:
                    self.value = self.refresh()
                    self.error, self.ok_at = None, utcnow()
                except FeedError as e:
                    self.error = str(e)
            return self.value, self.error, self.ok_at, self.detail


class GoesFeed(FeedCache):
    ttl = 120

    def __init__(self, spec, probe=None):
        super().__init__()
        self.spec = spec
        self.probe = probe or goes_probe

    def refresh(self):
        t, steps = find_goes_frame(self.spec, utcnow(), self.probe)
        self.detail = steps
        if t is None:
            raise FeedError(missing_frame_text(steps))
        return {"t": t}


class RadarFeed(FeedCache):
    ttl = 60

    def refresh(self):
        app = self._newest(APP_RADAR_QUERY)
        conus = self._newest(CONUS_RADAR_QUERY)
        if conus is None:
            raise FeedError("NOAA's radar service gave no CONUS footprint time, so the Montana frame time is unknown")
        image_url = RADAR_EXPORT + "?" + urllib.parse.urlencode(EXPORT_PARAMS)
        status, body = http_fetch(image_url, accept="image/png")
        if status != 200:
            raise FeedError(f"HTTP {status} for the radar image")
        try:
            stats = png_stats(body)
        except ValueError as e:
            raise FeedError(f"radar image is not a PNG this check can read ({e})") from None
        return {
            "valid": conus[0], "conus_name": conus[1],
            "app_newest": app[0] if app else None, "app_newest_name": app[1] if app else None,
            "image_url": image_url,
            "content": {"width": stats["width"], "height": stats["height"], "bytes": len(body),
                        "echo_share": stats["opaque_fraction"], "distinct_colours": stats["distinct_colours"]},
        }

    @staticmethod
    def _newest(query):
        data = http_json(RADAR_QUERY + "?" + urllib.parse.urlencode(query))
        feats = data.get("features") or []
        if not feats:
            return None
        attrs = feats[0].get("attributes") or {}
        if not attrs.get("idp_validtime"):
            return None
        return parse_time(attrs["idp_validtime"]), attrs.get("name")


class AlertsFeed(FeedCache):
    ttl = 60

    def __init__(self, zones):
        super().__init__()
        self.zones = zones

    def refresh(self):
        fc = http_json(NWS_ALERTS, accept="application/geo+json")
        raw = fc.get("features") if isinstance(fc, dict) else None
        if not isinstance(raw, list):
            raise FeedError("NWS sent an alert list with no features")
        budget = {"left": ZONE_FETCH_CAP}
        features = [safe_alert_feature(f, self.zones, budget) for f in raw]  # every alert is kept
        counts = {"polygon": 0, "zone": 0, "none": 0}
        for f in features:
            counts[f["properties"]["geometry_source"]] += 1
        # Zones named by this feed that still have no outline, and why (so a gap explains itself).
        named = {url for f in raw if isinstance(f, dict)
                 for _kind, _zid, url in zone_refs(f.get("properties") or {})}
        zone_errors = [{"zone": url.rsplit("/", 1)[-1], "error": self.zones.last_error[url]}
                       for url in sorted(named)
                       if url in self.zones.last_error and url not in self.zones.outlines]
        updated = fc.get("updated")
        return {"features": features, "input_count": len(raw), "counts": counts,
                "updated": parse_time(updated) if updated else None,
                "zone_fetches": ZONE_FETCH_CAP - budget["left"], "zone_errors": zone_errors}


# ----------------------------------------------------------------------------
# Alerts: geometry_source is polygon | zone | none; no alert is dropped
# ----------------------------------------------------------------------------
def is_polygonal(geom):
    return isinstance(geom, dict) and geom.get("type") in ("Polygon", "MultiPolygon") and bool(geom.get("coordinates"))


def polygons_of(geom):
    if geom.get("type") == "Polygon":
        return [geom["coordinates"]]
    return list(geom["coordinates"])


def bbox_centre(geom):
    xs, ys = [], []

    def walk(a):
        if a and isinstance(a[0], (int, float)):
            xs.append(a[0])
            ys.append(a[1])
        else:
            for b in a:
                walk(b)

    walk(geom.get("coordinates") or [])
    if not xs:
        return None
    return [round((min(xs) + max(xs)) / 2, 5), round((min(ys) + max(ys)) / 2, 5)]


def zone_refs(props):
    """(kind, zone id, url) for each zone an alert names. affectedZones first; UGC codes otherwise."""
    refs, seen = [], set()
    for url in props.get("affectedZones") or []:
        m = ZONE_URL.match(url or "")
        if m and url not in seen:
            refs.append((m.group(1), m.group(2), url))
            seen.add(url)
    if not refs:
        for ugc in (props.get("geocode") or {}).get("UGC") or []:
            kind = "county" if len(ugc) > 2 and ugc[2] == "C" else "forecast"
            url = NWS_ZONE.format(kind=kind, zid=ugc)
            if url not in seen:
                refs.append((kind, ugc, url))
                seen.add(url)
    return refs


def fetch_zone_live(url):
    feature = http_json(url, accept="application/geo+json")
    return feature if isinstance(feature, dict) else {}


class ZoneOutlines:
    """Forecast-zone and county outlines from api.weather.gov, cached in memory. A request may fetch at
    most its budget of zones; cached outlines and centroids cost nothing."""

    def __init__(self, fetch=None):
        self.fetch = fetch or fetch_zone_live
        self.lock = threading.Lock()
        self.outlines = OrderedDict()
        self.centroids = {}
        self.failed = {}
        self.last_error = {}  # url -> why the latest attempt gave no outline (shown in alerts.json)

    def lookup(self, url, budget):
        """Return (outline geometry or None, centroid [lon, lat] or None)."""
        with self.lock:
            if url in self.outlines:
                self.outlines.move_to_end(url)
                return self.outlines[url], self.centroids.get(url)
            last_fail = self.failed.get(url)
            if (last_fail and time.time() - last_fail < ZONE_RETRY_S) or budget["left"] <= 0:
                return None, self.centroids.get(url)
            budget["left"] -= 1
        try:
            geom = (self.fetch(url) or {}).get("geometry")
            error = None if is_polygonal(geom) else "the zone record has no polygon"
        except FeedError as e:
            geom, error = None, str(e)
        with self.lock:
            if is_polygonal(geom):
                self.outlines[url] = geom
                self.outlines.move_to_end(url)
                self.centroids[url] = bbox_centre(geom)
                self.failed.pop(url, None)
                self.last_error.pop(url, None)
                while len(self.outlines) > ZONE_OUTLINE_MAX:
                    self.outlines.popitem(last=False)
                return geom, self.centroids[url]
            self.failed[url] = time.time()
            self.last_error[url] = error
            return None, self.centroids.get(url)


def alert_feature(raw, zones, budget):
    p = raw.get("properties") or {}
    geom = raw.get("geometry")
    source, text, out, matched, outlined = "none", "", None, 0, 0
    if is_polygonal(geom):
        source, text, out = "polygon", "NWS alert polygon", geom
    else:
        refs = zone_refs(p)
        matched = len(refs)
        outlines, centroids = [], []
        for _kind, _zid, url in refs:
            outline, centroid = zones.lookup(url, budget)
            if outline is not None:
                outlines.append(outline)
                outlined += 1
            if centroid is not None:
                centroids.append(centroid)
        if outlines:
            source = "zone"
            out = {"type": "MultiPolygon", "coordinates": [poly for g in outlines for poly in polygons_of(g)]}
            text = "zone outline" if outlined == matched else f"zone outline, partial: {outlined} of {matched} zones"
        elif not refs:
            text = "no zone codes in the alert, so it cannot be placed on the map"
        else:
            text = "zone match, outline not loaded"
            if centroids:
                lon = sum(c[0] for c in centroids) / len(centroids)
                lat = sum(c[1] for c in centroids) / len(centroids)
                out = {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}
    if source == "polygon":
        marker = None
    elif out and out["type"] == "Point":
        marker = out["coordinates"]
    else:
        marker = bbox_centre(out) if out else None
    sev = p.get("severity")
    return {
        "type": "Feature", "id": p.get("id") or raw.get("id"), "geometry": out,
        "properties": {
            "event": p.get("event"), "headline": p.get("headline"), "severity": sev,
            "onset": p.get("onset"), "ends": p.get("ends") or p.get("expires"), "sent": p.get("sent"),
            "area": p.get("areaDesc"), "zones_matched": matched, "zones_outlined": outlined,
            "geometry_source": source, "text": text, "marker": marker,
            "style": {"outline": SEVERITY_COLOUR.get(sev, DEFAULT_COLOUR)},
        },
    }


def safe_alert_feature(raw, zones, budget):
    try:
        return alert_feature(raw, zones, budget)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        p = raw.get("properties") if isinstance(raw, dict) else None
        p = p if isinstance(p, dict) else {}
        return {
            "type": "Feature", "id": p.get("id"), "geometry": None,
            "properties": {"event": p.get("event"), "headline": p.get("headline"), "severity": p.get("severity"),
                           "onset": p.get("onset"), "ends": p.get("ends"), "sent": p.get("sent"),
                           "area": p.get("areaDesc"), "zones_matched": 0, "zones_outlined": 0,
                           "geometry_source": "none", "text": "could not read this alert's geometry",
                           "marker": None, "style": {"outline": DEFAULT_COLOUR}},
        }


# ----------------------------------------------------------------------------
# Services and documents
# ----------------------------------------------------------------------------
class Service:
    def __init__(self, offline=False, probe=None, fetch_zone=None):
        self.offline = offline
        self.started = utcnow()
        self.places, self.places_provenance = load_places()
        self.zones = ZoneOutlines(fetch_zone)
        self.goes = {spec["id"]: GoesFeed(spec, probe) for spec in GOES_LAYERS}
        self.radar = RadarFeed()
        self.alerts = AlertsFeed(self.zones)


def safe_get(feed):
    try:
        return feed.get()
    except Exception as e:  # a bug must not take the page down; say what happened
        return None, f"unexpected error ({type(e).__name__})", None, None


def gather(svc):
    """Every live feed, refreshed in parallel. Empty when offline: nothing is fetched."""
    if svc.offline:
        return {}
    jobs = {spec["id"]: svc.goes[spec["id"]] for spec in GOES_LAYERS}
    jobs["nws_radar"] = svc.radar
    jobs["nws_alerts"] = svc.alerts
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {key: pool.submit(safe_get, feed) for key, feed in jobs.items()}
        return {key: fut.result() for key, fut in futures.items()}


def bounds_list():
    return [MONTANA["west"], MONTANA["south"], MONTANA["east"], MONTANA["north"]]


def goes_layer(spec, res, now, offline):
    layer = {
        "id": spec["id"], "name": spec["name"], "kind": "observation", "default_on": spec["default_on"],
        "source": {"name": f"NASA GIBS: {spec['layer']}", "url": GIBS_CAPS},
        "legend": GOES_LEGEND[spec["id"]], "max_zoom": spec["max_zoom"],
        "freshness_limit_min": LIMIT_MIN["goes"], "age_min": None, "valid_time_utc": None,
        "valid_text": None, "retrieved_time_utc": None, "retrieved_text": None, "tile_template": None,
    }
    if offline or res is None:
        layer.update(state="off", state_text=OFFLINE_TEXT)
        return layer
    value, error, ok_at, steps = res
    t = value["t"] if value else None
    state, age, text = layer_state(t, now, LIMIT_MIN["goes"], error=error, had_good=value is not None)
    # Latency: how far behind real time the newest frame was when the probe found it (GIBS says ~40 min).
    latency = round((ok_at - t).total_seconds() / 60.0, 1) if (t and ok_at) else None
    layer.update(
        state=state, state_text=text, age_min=round(age, 1) if age is not None else None,
        valid_time_utc=iso_z(t) if t else None, valid_text=clock_text(t) if t else None,
        retrieved_time_utc=iso_z(ok_at) if ok_at else None,
        retrieved_text=clock_text(ok_at) if ok_at else None,
        latency_min_at_probe=latency,
        tile_template=goes_template(spec, t) if t and state in ("live", "stale") else None,
        probe={"zoom": PROBE_ZOOM, "tile": list(PROBE_TILE), "steps": compact_steps(steps)},
    )
    return layer


def radar_layer(res, now, offline):
    layer = {
        "id": "nws_radar", "name": "NWS base reflectivity (radar)", "kind": "radar estimate",
        "default_on": True, "source": {"name": "NOAA / NWS radar base reflectivity (MapServer)", "url": RADAR_BASE},
        "legend": RADAR_LEGEND, "freshness_limit_min": LIMIT_MIN["radar"], "detail_url": "/api/radar.json",
        "image_url": None, "bounds": bounds_list(), "age_min": None, "valid_time_utc": None,
        "valid_text": None, "retrieved_time_utc": None, "retrieved_text": None, "content": None,
        "content_text": None, "app_newest_valid_time_utc": None,
    }
    if offline or res is None:
        layer.update(state="off", state_text=OFFLINE_TEXT)
        return layer
    value, error, ok_at, _ = res
    valid = value["valid"] if value else None
    state, age, text = layer_state(valid, now, LIMIT_MIN["radar"], error=error, had_good=value is not None)
    content = value["content"] if value else None
    echo = content["echo_share"] if content else None
    layer.update(
        state=state, state_text=text, age_min=round(age, 1) if age is not None else None,
        valid_time_utc=iso_z(valid) if valid else None, valid_text=clock_text(valid) if valid else None,
        retrieved_time_utc=iso_z(ok_at) if ok_at else None,
        retrieved_text=clock_text(ok_at) if ok_at else None,
        image_url=value["image_url"] if value and state in ("live", "stale") else None,
        content=content,
        content_text=(f"Echo pixels in this image: {echo * 100:.1f}% of the Montana box. A blank box is not an "
                      f"all-clear.") if echo is not None else None,
        app_newest_valid_time_utc=iso_z(value["app_newest"]) if value and value.get("app_newest") else None,
    )
    return layer


def alerts_layer(res, now, offline):
    layer = {
        "id": "nws_alerts", "name": "NWS official alerts, Montana", "kind": "official alert",
        "default_on": True, "source": {"name": "National Weather Service, active alerts (area=MT)", "url": NWS_ALERTS},
        "legend": ALERTS_LEGEND, "freshness_limit_min": LIMIT_MIN["alerts"], "features_url": "/api/alerts.json",
        "age_min": None, "valid_time_utc": None, "valid_text": None, "retrieved_time_utc": None,
        "retrieved_text": None, "counts": {"polygon": 0, "zone": 0, "none": 0}, "items": [],
    }
    if offline or res is None:
        layer.update(state="off", state_text=OFFLINE_TEXT)
        return layer
    value, error, ok_at, _ = res
    valid = (value.get("updated") or ok_at) if value else None
    state, age, text = layer_state(valid, now, LIMIT_MIN["alerts"], error=error, had_good=value is not None)
    features = value["features"] if value else []
    layer.update(
        state=state, state_text=text, age_min=round(age, 1) if age is not None else None,
        valid_time_utc=iso_z(valid) if valid else None, valid_text=clock_text(valid) if valid else None,
        retrieved_time_utc=iso_z(ok_at) if ok_at else None,
        retrieved_text=clock_text(ok_at) if ok_at else None,
        counts=value["counts"] if value else layer["counts"],
        input_count=value["input_count"] if value else 0,
        items=[{"event": f["properties"]["event"], "severity": f["properties"]["severity"],
                "ends": f["properties"]["ends"], "geometry_source": f["properties"]["geometry_source"],
                "text": f["properties"]["text"]} for f in features],
    )
    return layer


def places_layer(svc):
    return {
        "id": "places", "name": "Places (prototype fixture)", "kind": "places", "default_on": True,
        "source": {"name": "fixtures/places.json (coordinates from the research brief)", "url": None},
        "legend": PLACES_LEGEND, "state": "live",
        "state_text": "Prototype fixture: five points from the research brief. Not the app's places.",
        "freshness_limit_min": None, "age_min": None, "valid_time_utc": None,
        "valid_text": "No valid time (fixture)", "retrieved_time_utc": iso_z(svc.started),
        "retrieved_text": clock_text(svc.started), "features_url": "/api/places.json",
        "items": [{"name": p["name"], "lat": p["lat"], "lon": p["lon"]} for p in svc.places],
    }


def base_layer(spec):
    return {
        "id": spec["id"], "name": spec["name"], "kind": "base map", "default_on": spec["default_on"],
        "state": "live", "state_text": "Base map: not timed. The browser loads these tiles directly from the provider.",
        "source": spec["source"], "legend": spec["legend"], "tile_template": spec["tile_template"],
        "max_zoom": spec["max_zoom"], "freshness_limit_min": None, "age_min": None,
        "valid_time_utc": None, "valid_text": "No valid time (base map)",
        "retrieved_time_utc": None, "retrieved_text": None,
    }


def layers_doc(svc):
    t0 = time.time()
    now = utcnow()
    res = gather(svc)
    layers = [goes_layer(spec, res.get(spec["id"]), now, svc.offline) for spec in GOES_LAYERS]
    layers.append(radar_layer(res.get("nws_radar"), now, svc.offline))
    layers.append(alerts_layer(res.get("nws_alerts"), now, svc.offline))
    layers.append(places_layer(svc))
    layers.extend(base_layer(spec) for spec in BASE_LAYERS)
    return {
        "generated_utc": iso_z(now), "generated_text": clock_text(now), "offline": svc.offline,
        "montana_box": MONTANA, "bounds": bounds_list(), "limits_note": LIMITS_NOTE,
        "parallax_source": PARALLAX_SOURCE, "layers": layers,
        "build_ms": round((time.time() - t0) * 1000),
    }


def alerts_doc(svc):
    now = utcnow()
    res = None if svc.offline else safe_get(svc.alerts)
    layer = alerts_layer(res, now, svc.offline)
    value = res[0] if res else None
    return {
        "type": "FeatureCollection", "features": value["features"] if value else [],
        "state": layer["state"], "state_text": layer["state_text"],
        "valid_time_utc": layer["valid_time_utc"], "retrieved_time_utc": layer["retrieved_time_utc"],
        "counts": layer["counts"], "input_count": layer.get("input_count", 0),
        "zone_fetches": value.get("zone_fetches") if value else 0,
        "zone_errors": value.get("zone_errors", []) if value else [],
        "source": layer["source"], "legend": ALERTS_LEGEND,
    }


def radar_doc(svc):
    now = utcnow()
    res = None if svc.offline else safe_get(svc.radar)
    layer = radar_layer(res, now, svc.offline)
    return {key: layer.get(key) for key in (
        "state", "state_text", "valid_time_utc", "valid_text", "app_newest_valid_time_utc",
        "retrieved_time_utc", "image_url", "bounds", "content", "content_text", "age_min",
        "freshness_limit_min", "source", "legend")}


def places_doc(svc):
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                      "properties": {"name": p["name"]}} for p in svc.places],
        "source": svc.places_provenance, "state": "live",
    }


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
def make_handler(svc):
    routes = {
        "/api/layers.json": lambda: layers_doc(svc),
        "/api/alerts.json": lambda: alerts_doc(svc),
        "/api/places.json": lambda: places_doc(svc),
        "/api/radar.json": lambda: radar_doc(svc),
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "GlobePrototype/0.1"

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            if path in STATIC:
                name, ctype = STATIC[path]
                with open(os.path.join(HERE, name), "rb") as f:
                    return self._send(200, f.read(), ctype)
            if path in routes:
                try:
                    doc = routes[path]()
                except Exception as e:
                    return self._json(500, {"error": f"unexpected error ({type(e).__name__})"})
                return self._json(200, doc)
            return self._json(404, {"error": "not found"})

        def _json(self, code, doc):
            body = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # stdout carries only the PORT line
            pass

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="3D storm view prototype server (research only).")
    ap.add_argument("--port", type=int, default=0, help="port on 127.0.0.1; 0 picks a free port")
    ap.add_argument("--offline", action="store_true", help="make no network calls; live layers show Off")
    args = ap.parse_args(argv)
    svc = Service(offline=args.offline)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(svc))
    httpd.daemon_threads = True
    print(f"PORT={httpd.server_address[1]}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
