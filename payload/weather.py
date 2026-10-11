"""
Weather data for the roofing app — provider adapters and labelled evidence
=========================================================================
Every piece of weather information becomes an ``Evidence`` record that keeps
what kind of evidence it is, who said it, when it was valid, how precise it
is, and the original values. Estimates, forecasts, reports, alerts and
inspections are never merged into one "hail score".

Sources (each is a small adapter, so a provider can change without touching
the screens):

    NWS alerts       official warnings, reconciled across updates/cancellations
    NWS forecasts    /points lookup -> hourly, gridpoint (gusts, rain) and 7-day
    NOAA radar       NEXRAD mosaic image; frame valid time read from the service
    SPC reports      preliminary hail/wind point reports, 12:00-11:59 UTC days
    Geocoding        US Census (street addresses), OpenStreetMap (cities, ZIPs)
    Hail footprint   configurable: not connected | demo fixture | GeoJSON feed
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

UTC = timezone.utc
DISPLAY_TZ = "America/Denver"   # Montana. Each job/property also stores its own zone from NWS.

# --------------------------------------------------------------------------
# Evidence model (mirrors the handoff's WeatherEvidence record)
# --------------------------------------------------------------------------
KIND_LABEL = {
    "forecast": "Forecast",
    "radar_estimate": "Estimated (radar)",
    "point_report": "Reported",
    "station_observation": "Measured at a station",
    "official_alert": "Official alert",
    "inspection": "Inspection-confirmed",
}
STATUSES = ("preliminary", "active", "updated", "expired", "cancelled", "archived")


@dataclass
class Evidence:
    id: str
    provider: str
    source_record_id: str
    kind: str
    hazard: str                       # hail | wind | rain | lightning | tornado | other
    issued_at: str | None             # ISO 8601 UTC
    valid_from: str
    valid_to: str | None
    received_at: str
    geometry: dict | None
    spatial_resolution_m: float | None
    magnitude: float | None
    unit: str | None
    provider_probability: float | None = None
    probability_meaning: str | None = None
    source_url: str | None = None
    status: str = "active"
    raw: dict = field(default_factory=dict)   # original values and units, untouched
    demo: bool = False
    label: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def kind_label(self) -> str:
        return ("DEMO · " if self.demo else "") + KIND_LABEL.get(self.kind, self.kind)


# --------------------------------------------------------------------------
# Time helpers — store UTC, show the zone of the place
# --------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat(timespec="seconds") if dt else None


def parse_iso(s) -> datetime | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DISPLAY_TZ)
    except Exception:
        return ZoneInfo(DISPLAY_TZ)


def fmt_local(dt, tz_name=None, with_date=True) -> str:
    dt = parse_iso(dt)
    if dt is None:
        return "—"
    local = dt.astimezone(zone(tz_name))
    fmt = "%b %d, %I:%M %p %Z" if with_date else "%I:%M %p %Z"
    return local.strftime(fmt).replace(" 0", " ").lstrip("0")


def age_text(dt, now: datetime | None = None) -> str:
    dt = parse_iso(dt)
    if dt is None:
        return "never"
    secs = max(0, int(((now or utcnow()) - dt).total_seconds()))
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{secs // 60} min ago"
    if secs < 172800:
        return f"{secs // 3600} hr ago"
    return f"{secs // 86400} days ago"


# --------------------------------------------------------------------------
# HTTP with provider caching, capped retries and plain-language errors
# --------------------------------------------------------------------------
class FeedError(Exception):
    """A feed couldn't be read. The message is shown to the user."""


class Http:
    def __init__(self, user_agent: str):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._cache: dict = {}
        self._lock = threading.Lock()

    def _get(self, url, *, params=None, headers=None, ttl=300, timeout=10, as_json=True, name="the provider"):
        key = (url, json.dumps(params, sort_keys=True), as_json)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1], hit[2]
        delays = (0.6, 1.8)
        for attempt in range(len(delays) + 1):
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=timeout)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < len(delays):
                    wait = r.headers.get("Retry-After")
                    time.sleep(min(float(wait), 5.0) if wait and wait.isdigit() else delays[attempt])
                    continue
                if r.status_code == 404:
                    raise FeedError(f"{name} has no data at that address (HTTP 404)")
                if r.status_code >= 400:
                    raise FeedError(f"{name} returned HTTP {r.status_code}")
                body = r.json() if as_json else r.text
                break
            except FeedError:
                raise
            except requests.Timeout:
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise FeedError(f"{name} didn't answer in time") from None
            except requests.ConnectionError:
                raise FeedError(f"no connection to {name}") from None
            except ValueError:
                raise FeedError(f"{name} sent data the app couldn't read") from None
        m = re.search(r"max-age=(\d+)", r.headers.get("Cache-Control", ""))
        keep = max(ttl, int(m.group(1))) if m else ttl      # honor the provider's caching
        fetched = utcnow()
        with self._lock:
            self._cache[key] = (now + keep, body, fetched)
        return body, fetched

    def json(self, url, **kw):
        return self._get(url, as_json=True, **kw)

    def text(self, url, **kw):
        return self._get(url, as_json=False, **kw)

    def forget(self, url_prefix: str):
        with self._lock:
            for k in [k for k in self._cache if k[0].startswith(url_prefix)]:
                self._cache.pop(k, None)


# --------------------------------------------------------------------------
# Feed freshness — every layer says live, stale, unavailable, demo, or not connected
# --------------------------------------------------------------------------
FRESH_SECONDS = {"radar": 15 * 60, "alerts": 10 * 60, "spc": 60 * 60, "forecast": 12 * 3600,
                 "geocode": 10 ** 9, "footprint": 6 * 3600}
STATE_LABEL = {"live": "Live", "stale": "Stale", "unavailable": "Unavailable", "demo": "Demo",
               "not_connected": "Not connected", "off": "Off", "subscription": "Needs subscription",
               "on_demand": "On demand"}


@dataclass
class Feed:
    key: str
    name: str
    provider: str
    url: str
    state: str = "unavailable"
    source_time: datetime | None = None    # when the data itself is valid (e.g. radar frame time)
    fetched_at: datetime | None = None     # when the app last read it successfully
    error: str | None = None
    detail: str = ""
    attribution: str = ""

    def judge(self, now=None) -> "Feed":
        """Recompute live/stale from age. Demo and not-connected never become live."""
        if self.state in ("demo", "not_connected", "off", "subscription", "on_demand"):
            return self
        ref = self.source_time or self.fetched_at
        if ref is None:
            self.state = "unavailable"
        elif self.error or ((now or utcnow()) - ref).total_seconds() > FRESH_SECONDS.get(self.key, 3600):
            self.state = "stale"
        else:
            self.state = "live"
        return self

    def view(self, tz_name=None) -> dict:
        self.judge()
        return {"key": self.key, "name": self.name, "provider": self.provider, "url": self.url,
                "state": self.state, "label": STATE_LABEL.get(self.state, self.state),
                "source_time": fmt_local(self.source_time, tz_name) if self.source_time else None,
                "source_age": age_text(self.source_time) if self.source_time else None,
                "fetched": fmt_local(self.fetched_at, tz_name) if self.fetched_at else None,
                "fetched_age": age_text(self.fetched_at) if self.fetched_at else None,
                "error": self.error, "detail": self.detail, "attribution": self.attribution}


# --------------------------------------------------------------------------
# Geometry helpers (pure Python; enough for points, polygons and multipolygons)
# --------------------------------------------------------------------------
EARTH_MI = 3958.8


def haversine_mi(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MI * math.asin(min(1.0, math.sqrt(a)))


def _polygons(geom) -> list:
    """Return a list of polygons (each a list of rings) from any GeoJSON object."""
    if not geom:
        return []
    t = geom.get("type")
    if t == "Feature":
        return _polygons(geom.get("geometry"))
    if t == "FeatureCollection":
        return [p for f in geom.get("features", []) for p in _polygons(f)]
    if t == "GeometryCollection":
        return [p for g in geom.get("geometries", []) for p in _polygons(g)]
    if t == "Polygon":
        return [geom.get("coordinates") or []]
    if t == "MultiPolygon":
        return list(geom.get("coordinates") or [])
    return []


def _in_ring(x, y, ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-300) + x1:
            inside = not inside
    return inside


def point_in(geom, lat, lon) -> bool:
    for rings in _polygons(geom):
        if rings and _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:]):
            return True
    return False


def _segments(geom):
    for rings in _polygons(geom):
        for ring in rings:
            for a, b in zip(ring, ring[1:]):
                yield (a[0], a[1]), (b[0], b[1])


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _seg_hit(p1, p2, q1, q2) -> bool:
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def bbox(geom):
    xs, ys = [], []
    for rings in _polygons(geom):
        for ring in rings:
            for p in ring:
                xs.append(p[0])
                ys.append(p[1])
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def intersects(g1, g2) -> bool:
    b1, b2 = bbox(g1), bbox(g2)
    if not b1 or not b2 or b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1]:
        return False
    for rings in _polygons(g1):
        if rings and rings[0] and point_in(g2, rings[0][0][1], rings[0][0][0]):
            return True
    for rings in _polygons(g2):
        if rings and rings[0] and point_in(g1, rings[0][0][1], rings[0][0][0]):
            return True
    segs2 = list(_segments(g2))
    return any(_seg_hit(a, b, c, d) for a, b in _segments(g1) for c, d in segs2)


def area_sq_mi(geom) -> float:
    total = 0.0
    for rings in _polygons(geom):
        if not rings:
            continue
        ring = rings[0]
        lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
        xy = [(math.radians(p[0]) * EARTH_MI * math.cos(lat0), math.radians(p[1]) * EARTH_MI) for p in ring]
        total += abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:]))) / 2
    return total


def clean_polygon(raw) -> dict | None:
    """Accept a drawn shape (GeoJSON text) only if it is a sane polygon."""
    try:
        g = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if isinstance(g, dict) and g.get("type") == "Feature":
        g = g.get("geometry")
    if not isinstance(g, dict) or g.get("type") != "Polygon":
        return None
    rings = g.get("coordinates")
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list) or not 4 <= len(rings[0]) <= 5000:
        return None
    pts = []
    for p in rings[0]:
        try:
            lng, lat = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90):
            return None
        pts.append([round(lng, 6), round(lat, 6)])
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return {"type": "Polygon", "coordinates": [pts]}


# --------------------------------------------------------------------------
# NWS official alerts — reconciled, never cleared by a failed request
# --------------------------------------------------------------------------
NWS = "https://api.weather.gov"
CONVECTIVE = ("Tornado", "Severe Thunderstorm", "Hail", "Extreme Wind", "Special Weather Statement")


def _num(value):
    m = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(m.group()) if m else None


def alert_hazards(event: str, hail_in, wind_mph) -> list[str]:
    e = event or ""
    out = []
    if "Tornado" in e:
        out.append("tornado")
    if hail_in or "Hail" in e:
        out.append("hail")
    if wind_mph or "Wind" in e or "Severe Thunderstorm" in e:
        out.append("wind")
    if re.search(r"Flood|Rain", e):
        out.append("rain")
    return out or ["other"]


def normalize_alert(feature: dict, received_at: datetime) -> dict:
    p = feature.get("properties") or {}
    params = p.get("parameters") or {}
    hail = next((v for v in (_num(x) for x in params.get("maxHailSize") or []) if v and v > 0), None)
    gust_raw = (params.get("maxWindGust") or [None])[0]
    gust = _num(gust_raw)
    gust_mph = round(gust * 1.15078) if gust and "kt" in str(gust_raw).lower() else gust
    headline = p.get("headline") or (params.get("NWSheadline") or [None])[0]
    geocode = p.get("geocode") or {}
    return {
        "id": p.get("id") or feature.get("id"),
        "ugc": list(geocode.get("UGC") or []),          # zone/county codes, e.g. MTZ235, MTC111
        "zones": list(p.get("affectedZones") or []),    # URLs that say which kind of zone each code is
        "event": p.get("event", ""),
        "headline": headline,
        "area": p.get("areaDesc", ""),
        "sent": p.get("sent"), "effective": p.get("effective"), "onset": p.get("onset"),
        "expires": p.get("expires"), "ends": p.get("ends"),
        "severity": p.get("severity"), "certainty": p.get("certainty"), "urgency": p.get("urgency"),
        "sender": p.get("senderName"),
        "message_type": p.get("messageType") or "Alert",
        "references": [r.get("identifier") for r in p.get("references") or [] if r.get("identifier")],
        "hail_in": hail,
        "wind_raw": gust_raw, "wind_mph": gust_mph,
        "hazards": alert_hazards(p.get("event", ""), hail, gust_mph),
        "convective": any(k in (p.get("event") or "") for k in CONVECTIVE),
        "geometry": feature.get("geometry"),
        "source_url": feature.get("id") if str(feature.get("id", "")).startswith("http") else None,
        "received_at": iso(received_at),
    }


def _over(rec: dict, now: datetime) -> bool:
    end = parse_iso(rec.get("ends")) or parse_iso(rec.get("expires"))
    return bool(end and end <= now)


def reconcile_alerts(known: dict, features: list, now: datetime, history: list = ()) -> dict:
    """Merge a *successful* NWS response into what we already knew.

    * Update  -> the new message is active; the ones it references become 'updated'.
    * Cancel  -> referenced messages become 'cancelled' (the cancel itself is not a warning).
    * A message that is past its end time becomes 'expired'.
    * An active message NWS no longer lists becomes 'archived' (or 'expired' if past its end).
    Callers must NOT call this after a failed request: then nothing changes.
    ``history`` holds messages backfilled after a gap (from /alerts?start=…):
    they settle references and record alerts that came and went during an
    outage, but only ``features`` (the active list) can make an alert active.
    """
    out = {k: dict(v) for k, v in known.items()}
    past = sorted((r for r in (normalize_alert(f, now) for f in history) if r["id"]), key=lambda r: r.get("sent") or "")
    current = [r for r in (normalize_alert(f, now) for f in features) if r["id"]]
    batch = past + current
    listed = {r["id"] for r in current}
    # Resolve references across the whole batch first, so message order doesn't matter.
    cancelled = {ref for r in batch if r["message_type"] == "Cancel" for ref in r["references"]}
    superseded = {ref: r["id"] for r in batch if r["message_type"] == "Update" for ref in r["references"]}
    for rec in batch:
        prior = out.get(rec["id"], {})
        rec["first_seen"] = prior.get("first_seen") or iso(now)
        rec["last_seen"] = iso(now)
        if rec["message_type"] == "Cancel" or rec["id"] in cancelled or prior.get("status") == "cancelled":
            rec["status"] = "cancelled"
        elif rec["id"] in superseded or prior.get("status") == "updated":
            rec["status"] = "updated"
            rec["superseded_by"] = superseded.get(rec["id"]) or prior.get("superseded_by")
        else:
            rec["status"] = "expired" if _over(rec, now) else "active"
        out[rec["id"]] = {**prior, **rec}
    for ref in cancelled:                       # messages we knew from earlier fetches…
        out.setdefault(ref, {"id": ref, "placeholder": True, "first_seen": iso(now), "last_seen": iso(now)})["status"] = "cancelled"
    for ref, newer in superseded.items():       # …or haven't seen yet (out-of-order delivery)
        rec = out.setdefault(ref, {"id": ref, "placeholder": True, "status": "active", "first_seen": iso(now), "last_seen": iso(now)})
        if rec.get("status") in ("active", "archived", "expired"):
            rec["status"], rec["superseded_by"] = "updated", newer
    for aid, rec in out.items():
        if rec.get("status") == "active" and (aid not in listed or _over(rec, now)):
            rec["status"] = "expired" if _over(rec, now) else "archived"
    return out


def alert_evidence(rec: dict) -> Evidence:
    hazard = "hail" if "hail" in rec.get("hazards", []) else (rec.get("hazards") or ["other"])[0]
    return Evidence(
        id=f"nws:{rec['id']}", provider="NWS", source_record_id=rec["id"], kind="official_alert",
        hazard=hazard, issued_at=rec.get("sent"), valid_from=rec.get("effective") or rec.get("sent") or "",
        valid_to=rec.get("ends") or rec.get("expires"), received_at=rec.get("received_at") or "",
        geometry=rec.get("geometry"), spatial_resolution_m=None,
        magnitude=rec.get("hail_in") if hazard == "hail" else rec.get("wind_mph"),
        unit="in" if hazard == "hail" else ("mph" if rec.get("wind_mph") else None),
        source_url=rec.get("source_url"), status=rec.get("status", "active"),
        raw={k: rec.get(k) for k in ("event", "headline", "message_type", "references", "wind_raw", "severity")},
        label=rec.get("event", ""))


class AlertService:
    """Montana-wide official alerts. Known alerts live in the database so a
    restart or a dropped connection never silently clears a warning."""

    def __init__(self, http: Http, load_known, save_known, area="MT", enabled=True):
        self.http, self.load_known, self.save_known = http, load_known, save_known
        self.area, self.enabled = area, enabled
        self.url = f"{NWS}/alerts/active?area={area}"
        self.feed = Feed("alerts", "Official alerts", "National Weather Service", self.url,
                         detail="Warnings, watches and advisories for Montana.",
                         attribution="National Weather Service")
        self._lock = threading.Lock()
        self._busy = False
        self._last_try = 0.0
        self.last_success: datetime | None = None
        self.backfilled: int | None = None

    def refresh(self, wait=True):
        if not self.enabled:
            self.feed.state, self.feed.error = "off", "Live feeds are off during a self-test."
            return
        if time.time() - self._last_try < 50:
            return
        with self._lock:
            if self._busy:
                return
            self._busy = True
            self._last_try = time.time()
        if wait or self.feed.fetched_at is None:
            self._refresh()
        else:
            threading.Thread(target=self._refresh, daemon=True).start()

    def _backfill(self, since: datetime) -> list:
        """Messages issued since `since` — catches alerts that were issued and
        ended while the app couldn't reach NWS."""
        url = f"{NWS}/alerts"
        params = {"area": self.area, "start": (since - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        out = []
        for _ in range(5):                    # pages
            data, _ = self.http.json(url, params=params, headers={"Accept": "application/geo+json"}, ttl=30,
                                     timeout=10, name="the NWS alert history")
            out += data.get("features", [])
            nxt = (data.get("pagination") or {}).get("next")
            if not nxt or not data.get("features"):
                break
            url, params = nxt, None
        return out

    def _refresh(self):
        try:
            data, fetched = self.http.json(self.url, headers={"Accept": "application/geo+json"},
                                           ttl=30, timeout=8, name="the National Weather Service")
            history, problem = [], None
            last = self.last_success
            if last and (fetched - last).total_seconds() > 150:     # we missed at least two checks
                try:
                    history = self._backfill(last)
                    self.backfilled = len(history)
                except FeedError as e:
                    problem = f"couldn't backfill alerts issued during the gap ({e})"
            merged = reconcile_alerts(self.load_known(), data.get("features", []), utcnow(), history)
            self.save_known(merged)
            self.last_success = fetched
            self.feed.fetched_at, self.feed.source_time, self.feed.error = fetched, fetched, problem
        except FeedError as e:
            self.feed.error = str(e)          # keep every known warning; the screen says it's stale
        finally:
            with self._lock:
                self._busy = False

    def records(self) -> list[dict]:
        recs = list(self.load_known().values())
        now = utcnow()
        for r in recs:      # time can end a warning even when the network is down
            if r.get("status") == "active" and _over(r, now):
                r["status"] = "expired"
        return recs

    def active(self) -> list[dict]:
        recs = [r for r in self.records() if r.get("status") == "active"]
        recs.sort(key=lambda r: (not r.get("convective"), -(r.get("hail_in") or 0), r.get("event", "")))
        return recs


# --------------------------------------------------------------------------
# Which alerts apply where (independent review, P0)
#
#   1. The alert has a polygon        -> applies if the place is inside it.
#   2. No polygon (zone/county alert) -> applies if the alert's UGC codes include
#      the place's NWS forecast zone, county, or fire-weather zone (from /points).
#   3. Can't tell (codes not known)   -> "unknown", shown as "check this alert".
# A missing polygon never means "no alert".
# --------------------------------------------------------------------------
def applies_to_place(alert: dict, place: dict) -> tuple[bool | None, str]:
    geom = alert.get("geometry")
    if geom:
        return point_in(geom, place["lat"], place["lng"]), "warning polygon"
    codes = set(alert.get("ugc") or [])
    if not codes:
        return None, "the alert lists no zones"
    own = {"forecast zone": place.get("nws_zone"), "county": place.get("nws_county"),
           "fire-weather zone": place.get("nws_fire_zone")}
    if not any(own.values()):
        return None, "this place's NWS zones aren't looked up yet"
    for label, code in own.items():
        if code and code in codes:
            return True, f"{label} {code}"
    return False, "zones/counties"


def applies_to_area(alert: dict, area_geom: dict, zone_geoms: dict) -> tuple[bool | None, str]:
    geom = alert.get("geometry")
    if geom:
        return intersects(geom, area_geom), "warning polygon"
    unknown = False
    for url in alert.get("zones") or []:
        g = zone_geoms.get(url)
        if g is None:
            unknown = True
        elif intersects(g, area_geom):
            return True, f"zone {url.rsplit('/', 1)[-1]}"
    if unknown or not alert.get("zones"):
        return None, "zone boundaries not loaded yet"
    return False, "zones/counties"


class ZoneService:
    """Boundaries of NWS forecast zones and counties, for alerts that have no
    polygon. Cached for a day (boundaries change occasionally)."""

    def __init__(self, http: Http, enabled=True):
        self.http, self.enabled = http, enabled
        self.geoms: dict[str, dict] = {}
        self.names: dict[str, str] = {}

    def ensure(self, alerts: list[dict], limit=60) -> int:
        if not self.enabled:
            return 0
        fetched = 0
        for a in alerts:
            if a.get("geometry"):
                continue
            for url in a.get("zones") or []:
                if url in self.geoms or fetched >= limit or not url.startswith(NWS + "/zones/"):
                    continue
                try:
                    data, _ = self.http.json(url, ttl=24 * 3600, timeout=10, name="the NWS zone service")
                except FeedError:
                    continue
                if data.get("geometry"):
                    self.geoms[url] = data["geometry"]
                    self.names[url] = (data.get("properties") or {}).get("name", "")
                fetched += 1
        return fetched


# --------------------------------------------------------------------------
# NOAA radar — the frame's own valid time, so the screen can show its age
# --------------------------------------------------------------------------
RADAR_WMS = ("https://mapservices.weather.noaa.gov/eventdriven/services/"
             "radar/radar_base_reflectivity/MapServer/WMSServer")
RADAR_LAYER = "1"   # WMS layer "1" is the radar image ("3" is "Boundary" and draws nothing)
RADAR_META = ("https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
              "radar/radar_base_reflectivity/MapServer/2/query")


class RadarService:
    def __init__(self, http: Http, enabled=True):
        self.http, self.enabled = http, enabled
        self.feed = Feed("radar", "Radar reflectivity", "NOAA / NWS NEXRAD mosaic", RADAR_WMS,
                         detail="Base reflectivity mosaic. Colors show precipitation echoes, not hail size or wind at a roof.",
                         attribution="NOAA / National Weather Service")

    def refresh(self):
        if not self.enabled:
            self.feed.state, self.feed.error = "off", "Live feeds are off during a self-test."
            return
        try:
            data, fetched = self.http.json(RADAR_META, params={
                "where": "1=1", "outFields": "idp_validtime,name", "returnGeometry": "false",
                "orderByFields": "idp_validtime DESC", "resultRecordCount": 1, "f": "json"},
                ttl=60, timeout=8, name="NOAA's radar service")
            ms = max((f["attributes"].get("idp_validtime") or 0) for f in data.get("features") or [{"attributes": {}}])
            if not ms:
                raise FeedError("NOAA's radar service didn't report a frame time")
            self.feed.source_time = datetime.fromtimestamp(ms / 1000, UTC)
            self.feed.fetched_at, self.feed.error = fetched, None
        except (FeedError, KeyError, TypeError) as e:
            self.feed.error = str(e)


# --------------------------------------------------------------------------
# SPC preliminary storm reports
# --------------------------------------------------------------------------
SPC = "https://www.spc.noaa.gov/climo/reports/"


def spc_day_for(dt: datetime) -> date:
    """SPC reporting days run 12:00 UTC to 11:59 UTC the next day."""
    return (parse_iso(dt).astimezone(UTC) - timedelta(hours=12)).date()


def spc_window(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    return start, start + timedelta(hours=23, minutes=59)


def spc_time_to_utc(day: date, hhmm: str) -> datetime:
    s = str(hhmm).strip().zfill(4)
    if not s.isdigit() or len(s) != 4:
        raise ValueError(f"bad SPC time {hhmm!r}")
    h, m = int(s[:2]), int(s[2:])
    if h > 23 or m > 59:
        raise ValueError(f"bad SPC time {hhmm!r}")
    t = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(hours=h, minutes=m)
    return t + timedelta(days=1) if h < 12 else t


def spc_hail_inches(size) -> float | None:
    """SPC hail sizes are hundredths of an inch: 175 means 1.75 inches."""
    try:
        n = int(str(size).strip())
    except (TypeError, ValueError):
        return None
    return n / 100 if n > 0 else None


def spc_wind_mph(speed) -> float | None:
    """SPC wind gusts are in mph; 'UNK' (unknown) stays unknown — never zero."""
    s = str(speed or "").strip()
    return float(s) if s.isdigit() else None


def spc_url(day: date, kind: str, filtered=True) -> str:
    return f"{SPC}{day:%y%m%d}_rpts_{'filtered_' if filtered else ''}{kind}.csv"


def parse_spc_csv(text: str, day: date, kind: str, received_at: datetime | None = None) -> list[Evidence]:
    rows = list(csv.reader(io.StringIO(text)))
    out, seen = [], set()
    received = iso(received_at or utcnow())
    page = f"{SPC}{day:%y%m%d}_rpts.html"
    for row in rows[1:]:
        if len(row) < 7 or not row[0].strip():
            continue
        try:
            when = spc_time_to_utc(day, row[0])
            lat, lon = float(row[5]), float(row[6])
        except ValueError:
            continue
        comments = ",".join(row[7:]).strip()
        if kind == "hail":
            mag, unit, hazard = spc_hail_inches(row[1]), "in", "hail"
        elif kind == "wind":
            mag, unit, hazard = spc_wind_mph(row[1]), "mph", "wind"
        else:
            mag, unit, hazard = None, None, "tornado"
        rid = f"{day:%Y%m%d}:{kind}:{row[0].strip()}:{lat:.2f}:{lon:.2f}:{row[1].strip()}"
        if rid in seen:          # the same line twice in one file is one report
            continue
        seen.add(rid)
        place = f"{row[2].strip()}, {row[3].strip()} Co., {row[4].strip()}"
        out.append(Evidence(
            id=f"spc:{rid}", provider="SPC", source_record_id=rid, kind="point_report", hazard=hazard,
            issued_at=None, valid_from=iso(when), valid_to=None, received_at=received,
            geometry={"type": "Point", "coordinates": [lon, lat]}, spatial_resolution_m=None,
            magnitude=mag, unit=unit if mag is not None else None, source_url=page, status="preliminary",
            raw={"time_utc_hhmm": row[0].strip(), "value": row[1].strip(), "location": row[2].strip(),
                 "county": row[3].strip(), "state": row[4].strip(), "comments": comments,
                 "reporting_day": day.isoformat()},
            label=place))
    return out


class SPCService:
    def __init__(self, http: Http, enabled=True):
        self.http, self.enabled = http, enabled
        self.feed = Feed("spc", "Reported hail & wind", "NOAA Storm Prediction Center", SPC,
                         detail="Preliminary reports — points near where someone reported, not continuous swaths. "
                                "Subject to revision.", attribution="NOAA Storm Prediction Center")

    def reports(self, day: date, kind="hail", filtered=True) -> list[Evidence]:
        if not self.enabled:
            self.feed.state, self.feed.error = "off", "Live feeds are off during a self-test."
            return []
        today = spc_day_for(utcnow())
        ttl = 600 if day >= today - timedelta(days=1) else 6 * 3600
        url = spc_url(day, kind, filtered)
        try:
            text, fetched = self.http.text(url, ttl=ttl, timeout=10, name="the Storm Prediction Center")
        except FeedError as e:
            self.feed.error = str(e)
            raise
        self.feed.fetched_at, self.feed.source_time, self.feed.error = fetched, fetched, None
        return parse_spc_csv(text, day, kind, fetched)


# --------------------------------------------------------------------------
# NWS forecasts for a job: hourly, gridpoint (gusts, rain), 7-day, alerts at the point
# --------------------------------------------------------------------------
_DUR = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?")


def duration_hours(text: str) -> int:
    m = _DUR.fullmatch(text or "")
    if not m:
        return 1
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return max(1, d * 24 + h + (1 if mi else 0))


def expand_series(prop: dict, convert=lambda v: v) -> dict:
    """NWS gridpoint series ('2026-10-11T06:00:00+00:00/PT6H') -> {hour_utc: value}."""
    out = {}
    for item in (prop or {}).get("values") or []:
        start_s, _, dur = str(item.get("validTime", "")).partition("/")
        start, value = parse_iso(start_s), item.get("value")
        if start is None or value is None:
            continue
        start = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        for i in range(duration_hours(dur)):
            out[start + timedelta(hours=i)] = convert(value)
    return out


def wind_range_mph(text) -> tuple[float | None, float | None]:
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(text or ""))]
    return (min(nums), max(nums)) if nums else (None, None)


KMH_TO_MPH = 0.621371


def _to_f(prop):
    """Gridpoint temperatures come in the unit named by 'uom' (normally degC)."""
    if "degF" in str((prop or {}).get("uom", "")):
        return lambda v: v
    return lambda v: v * 9 / 5 + 32
MM_TO_IN = 1 / 25.4


class ForecastService:
    def __init__(self, http: Http, enabled=True):
        self.http, self.enabled = http, enabled

    def point(self, lat, lon) -> dict:
        if not self.enabled:
            raise FeedError("live feeds are off during a self-test")
        data, _ = self.http.json(f"{NWS}/points/{lat:.4f},{lon:.4f}", ttl=24 * 3600, timeout=10,
                                 name="the National Weather Service")
        p = data.get("properties") or {}
        rel = ((p.get("relativeLocation") or {}).get("properties") or {})
        code = lambda url: (url or "").rstrip("/").rsplit("/", 1)[-1] or None  # noqa: E731
        return {"grid": f"{p.get('gridId')} {p.get('gridX')},{p.get('gridY')}", "tz": p.get("timeZone"),
                "zone": code(p.get("forecastZone")), "county": code(p.get("county")),
                "fire_zone": code(p.get("fireWeatherZone")),
                "forecast": p.get("forecast"), "hourly": p.get("forecastHourly"), "griddata": p.get("forecastGridData"),
                "near": ", ".join(x for x in (rel.get("city"), rel.get("state")) if x)}

    def outlook(self, lat, lon, hours=48) -> dict:
        """Everything Crew Outlook needs for one place. Missing pieces are
        reported, never filled in."""
        res = {"hours": [], "days": [], "qpf": [], "alerts": [], "errors": [], "tz": None, "grid": None,
               "updated": None, "feed": Feed("forecast", "Job forecast", "National Weather Service",
                                             f"{NWS}/points/{lat:.4f},{lon:.4f}",
                                             attribution="National Weather Service")}
        if not self.enabled:
            res["feed"].state = "off"
            res["errors"].append("Live feeds are off during a self-test.")
            return res
        try:
            info = self.point(lat, lon)
        except FeedError as e:
            res["errors"].append(f"Forecast lookup failed: {e}")
            res["feed"].error = str(e)
            return res
        res["tz"], res["grid"], res["near"] = info["tz"], info["grid"], info["near"]
        gusts, wbgt, heat_index, qpf_hours = {}, {}, {}, []
        try:
            grid, fetched = self.http.json(info["griddata"], ttl=1800, timeout=12, name="the NWS forecast grid")
            gp = grid.get("properties") or {}
            gusts = expand_series(gp.get("windGust"), lambda v: v * KMH_TO_MPH)
            wbgt = expand_series(gp.get("wetBulbGlobeTemperature"), _to_f(gp.get("wetBulbGlobeTemperature")))
            heat_index = expand_series(gp.get("heatIndex"), _to_f(gp.get("heatIndex")))
            for item in (gp.get("quantitativePrecipitation") or {}).get("values") or []:
                start_s, _, dur = str(item.get("validTime", "")).partition("/")
                start = parse_iso(start_s)
                if start and item.get("value") is not None:
                    qpf_hours.append({"start": start, "hours": duration_hours(dur),
                                      "inches": round(item["value"] * MM_TO_IN, 2)})
            res["updated"] = parse_iso(gp.get("updateTime"))
            res["feed"].fetched_at = fetched
        except FeedError as e:
            res["errors"].append(f"Gusts and rain amounts unavailable: {e}")
        try:
            hourly, fetched = self.http.json(info["hourly"], ttl=1800, timeout=12, name="the NWS hourly forecast")
            hp = hourly.get("properties") or {}
            res["updated"] = res["updated"] or parse_iso(hp.get("updateTime"))
            res["feed"].fetched_at = res["feed"].fetched_at or fetched
            for p in (hp.get("periods") or [])[:hours]:
                start = parse_iso(p.get("startTime"))
                if start is None:
                    continue
                key = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
                lo, hi = wind_range_mph(p.get("windSpeed"))
                temp = p.get("temperature")
                if temp is not None and str(p.get("temperatureUnit", "F")).upper() == "C":
                    temp = temp * 9 / 5 + 32
                res["hours"].append({
                    "start": start, "temp_f": temp,
                    "precip_pct": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                    "wind_mph": hi, "wind_text": p.get("windSpeed"), "wind_dir": p.get("windDirection"),
                    "gust_mph": round(gusts[key]) if key in gusts else None,
                    "wbgt_f": round(wbgt[key]) if key in wbgt else None,
                    "heat_index_f": round(heat_index[key]) if key in heat_index else None,
                    "humidity": (p.get("relativeHumidity") or {}).get("value"),
                    "daytime": p.get("isDaytime"), "short": p.get("shortForecast")})
        except FeedError as e:
            res["errors"].append(f"Hourly forecast unavailable: {e}")
        try:
            daily, _ = self.http.json(info["forecast"], ttl=1800, timeout=12, name="the NWS 7-day forecast")
            for p in (daily.get("properties") or {}).get("periods") or []:
                lo, hi = wind_range_mph(p.get("windSpeed"))
                res["days"].append({"name": p.get("name"), "start": parse_iso(p.get("startTime")),
                                    "temp_f": p.get("temperature"), "daytime": p.get("isDaytime"),
                                    "precip_pct": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                                    "wind_text": p.get("windSpeed"), "wind_mph": hi,
                                    "short": p.get("shortForecast"), "detail": p.get("detailedForecast")})
        except FeedError as e:
            res["errors"].append(f"7-day forecast unavailable: {e}")
        try:
            al, _ = self.http.json(f"{NWS}/alerts/active", params={"point": f"{lat:.4f},{lon:.4f}"},
                                   headers={"Accept": "application/geo+json"}, ttl=120, timeout=8,
                                   name="the NWS alerts service")
            now = utcnow()
            res["alerts"] = [r for r in reconcile_alerts({}, al.get("features", []), now).values()
                             if r.get("status") == "active"]
            res["alerts_ok"] = True
        except FeedError as e:
            res["alerts_ok"] = False
            res["errors"].append(f"Alerts for this location unavailable: {e}")
        start = res["hours"][0]["start"] if res["hours"] else utcnow()
        res["qpf"] = [q for q in qpf_hours if q["start"] + timedelta(hours=q["hours"]) > start][:12]
        res["feed"].source_time = res["updated"]
        if res["errors"]:
            res["feed"].error = "; ".join(res["errors"])
        return res


# --------------------------------------------------------------------------
# Crew Outlook rules — company settings and per-job criteria, not safety standards
# --------------------------------------------------------------------------
RULE_FIELDS = [
    {"key": "max_wind_mph", "label": "Highest sustained wind", "unit": "mph", "default": 20},
    {"key": "max_gust_mph", "label": "Highest gust", "unit": "mph", "default": 25},
    {"key": "max_pop", "label": "Highest chance of rain or snow", "unit": "%", "default": 30},
    {"key": "min_temp_f", "label": "Lowest temperature", "unit": "°F", "default": 40},
    {"key": "max_temp_f", "label": "Highest temperature", "unit": "°F", "default": 95},
    {"key": "max_wbgt_f", "label": "Forecast WBGT heat threshold (your heat procedure)", "unit": "°F", "default": None},
]
DEFAULT_RULES = {f["key"]: f["default"] for f in RULE_FIELDS} | {"daylight_only": True}
OUTLOOK_LABEL = {"meets": "Forecast meets configured conditions", "review": "Weather review needed",
                 "unavailable": "Data unavailable"}
PHASES = [("inspection", "Inspection"), ("tear_off", "Tear-off"), ("installation", "Installation"),
          ("adhesion", "Adhesion / coating"), ("staging", "Staging / delivery")]


def merge_rules(company: dict, overrides: dict | None) -> tuple[dict, dict]:
    """Job criteria override company defaults field by field. Thresholds are
    never copied between products — a blank job field means the company rule."""
    rules, source = dict(company), {k: "company" for k in company}
    for k, v in (overrides or {}).items():
        if v is not None and v != "":
            rules[k], source[k] = v, "job"
    return rules, source


def _describe(f: dict, lo=None, hi=None) -> str:
    if "text" in f:
        return f["text"]
    lo = f["value"] if lo is None else lo
    hi = f["value"] if hi is None else hi
    sep = "" if f["unit"] in ("%", "°F") else " "
    val = f"{lo:.0f}{sep}{f['unit']}" if round(lo) == round(hi) else f"{lo:.0f}–{hi:.0f}{sep}{f['unit']}"
    return f"{f['name']} {val} {f['tail']}"


def evaluate_hour(h: dict, rules: dict, alerts: list | None = None, alerts_ok: bool = True,
                  source: dict | None = None) -> dict:
    """Never returns an all-clear when a critical input is missing."""
    found, missing = [], []
    src = lambda k: " (job rule)" if (source or {}).get(k) == "job" else ""  # noqa: E731
    checks = [("wind_mph", "max_wind_mph", ">", "Sustained wind", "mph", "is above the {r:.0f} mph limit"),
              ("gust_mph", "max_gust_mph", ">", "Gusts", "mph", "are above the {r:.0f} mph limit"),
              ("precip_pct", "max_pop", ">", "Chance of precipitation", "%", "is above the {r:.0f}% limit"),
              ("temp_f", "min_temp_f", "<", "Temperature", "°F", "is below the {r:.0f}°F minimum"),
              ("temp_f", "max_temp_f", ">", "Temperature", "°F", "is above the {r:.0f}°F maximum"),
              ("wbgt_f", "max_wbgt_f", ">=", "Forecast WBGT", "°F",
               "is at or above the {r:.0f}°F heat threshold — follow your heat procedure")]
    names = {"wind_mph": "sustained wind", "gust_mph": "gusts", "precip_pct": "precipitation chance",
             "temp_f": "temperature", "wbgt_f": "forecast WBGT"}
    for field_, rule, op, name, unit, tail in checks:
        r = rules.get(rule)
        if r is None:
            continue
        v = h.get(field_)
        if v is None:
            if names[field_] not in missing:
                missing.append(names[field_])
            continue
        if (op == ">" and v > r) or (op == "<" and v < r) or (op == ">=" and v >= r):
            found.append({"code": rule, "name": name, "unit": unit, "value": float(v), "tail": tail.format(r=r) + src(rule)})
    if rules.get("daylight_only") and h.get("daytime") is False:
        found.append({"code": "night", "text": "Outside daylight hours (NWS night period)"})
    if not alerts_ok:
        missing.append("official alerts")
    for a in alerts or []:
        found.append({"code": f"alert:{a.get('event')}", "text": f"Official alert in effect: {a.get('event')}"})
    status = "unavailable" if missing else ("review" if found else "meets")
    return {"status": status, "label": OUTLOOK_LABEL[status], "found": found,
            "triggers": [_describe(f) for f in found], "missing": missing}


def outlook_windows(hours: list[dict], tz_name: str | None) -> list[dict]:
    """Group consecutive hours with the same status (split at local midnight)
    into windows, merging repeated reasons into ranges."""
    out = []
    z = zone(tz_name)
    for h in hours:
        ev = h["eval"]
        day = h["start"].astimezone(z).date()
        if out and out[-1]["status"] == ev["status"] and out[-1]["end"] == h["start"] and out[-1]["day"] == day:
            w = out[-1]
            w["end"] = h["start"] + timedelta(hours=1)
        else:
            w = {"status": ev["status"], "label": ev["label"], "start": h["start"], "day": day,
                 "end": h["start"] + timedelta(hours=1), "agg": {}, "missing": []}
            out.append(w)
        for f in ev.get("found", []):
            a = w["agg"].setdefault(f["code"], {"f": f, "lo": f.get("value"), "hi": f.get("value")})
            if "value" in f:
                a["lo"], a["hi"] = min(a["lo"], f["value"]), max(a["hi"], f["value"])
        for m in ev["missing"]:
            if m not in w["missing"]:
                w["missing"].append(m)
    for w in out:
        w["triggers"] = [_describe(a["f"], a["lo"], a["hi"]) for a in w.pop("agg").values()]
        w["hours"] = int((w["end"] - w["start"]).total_seconds() // 3600)
        same_day = w["end"].astimezone(z).date() == w["day"] or w["end"].astimezone(z).hour == 0
        w["when"] = f"{fmt_local(w['start'], tz_name)} – {fmt_local(w['end'], tz_name, with_date=not same_day)}"
    return out


def phase_fit(hours: list[dict], need_hours: float | None, tz_name=None, on_date=None) -> dict:
    """Is there an uninterrupted stretch that meets the configured conditions
    long enough for the work plus the time to make the roof weather-tight?
    A forecast window does not establish a dry deck or ready adhesive."""
    if not need_hours:
        return {"fits": None, "reason": "Set the job's work hours and dry-in time to check the window length."}
    pool = [h for h in hours if on_date is None or h["start"].astimezone(zone(tz_name)).date() == on_date]
    if not pool:
        return {"fits": None, "reason": "No hourly forecast covers that day yet (NWS hourly goes out about 6 days; "
                                        "the app reads 48 hours)."}
    best, run = None, []
    for h in pool:
        if h["eval"]["status"] == "meets" and (not run or run[-1]["start"] + timedelta(hours=1) == h["start"]):
            run.append(h)
        elif h["eval"]["status"] == "meets":
            run = [h]
        else:
            run = []
        if run and (best is None or len(run) > len(best)):
            best = list(run)
    if any(h["eval"]["status"] == "unavailable" for h in pool) and (best is None or len(best) < need_hours):
        return {"fits": None, "need": need_hours, "reason": "Some forecast inputs are missing — can't confirm a window."}
    if best is None:
        return {"fits": False, "need": need_hours, "reason": "No hours meet the configured conditions."}
    span = f"{fmt_local(best[0]['start'], tz_name)} – {fmt_local(best[-1]['start'] + timedelta(hours=1), tz_name, with_date=False)}"
    return {"fits": len(best) >= need_hours, "need": need_hours, "longest": len(best), "span": span,
            "reason": (f"Longest stretch meeting conditions: {span} ({len(best)} h); this phase needs {need_hours:g} h.")}


# --------------------------------------------------------------------------
# Search: street addresses (US Census) and cities/ZIPs (OpenStreetMap)
# --------------------------------------------------------------------------
class Geocoder:
    CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
    OSM = "https://nominatim.openstreetmap.org/search"

    def __init__(self, http: Http, enabled=True):
        self.http, self.enabled = http, enabled
        self._last_osm = 0.0

    def search(self, q: str) -> tuple[list[dict], str | None]:
        q = (q or "").strip()
        if not q:
            return [], None
        if not self.enabled:
            return [], "Search is off during a self-test."
        results, errors = [], []
        if re.match(r"^\d+\s+\S", q):          # looks like a street address
            try:
                data, _ = self.http.json(self.CENSUS, params={"address": q, "benchmark": "Public_AR_Current",
                                                              "format": "json"}, ttl=86400, timeout=10,
                                         name="the Census geocoder")
                for m in (data.get("result") or {}).get("addressMatches") or []:
                    c = m.get("coordinates") or {}
                    results.append({"label": m.get("matchedAddress"), "lat": c.get("y"), "lon": c.get("x"),
                                    "precision": "address", "source": "U.S. Census Bureau geocoder"})
            except FeedError as e:
                errors.append(str(e))
        if not results:
            wait = 1.1 - (time.time() - self._last_osm)      # OpenStreetMap asks for ≤1 request/second
            if wait > 0:
                time.sleep(wait)
            self._last_osm = time.time()
            try:
                data, _ = self.http.json(self.OSM, params={"q": q, "countrycodes": "us", "format": "jsonv2",
                                                           "limit": 5}, ttl=86400, timeout=10,
                                         name="OpenStreetMap search")
                for m in data or []:
                    kind = m.get("addresstype") or m.get("type") or "place"
                    results.append({"label": m.get("display_name"), "lat": float(m["lat"]), "lon": float(m["lon"]),
                                    "precision": "address" if kind in ("house", "building") else kind,
                                    "source": "© OpenStreetMap contributors"})
            except (FeedError, KeyError, ValueError) as e:
                errors.append(str(e))
        return results, ("; ".join(errors) if errors and not results else None)


# --------------------------------------------------------------------------
# Estimated hail footprints — a configurable slot
# --------------------------------------------------------------------------
class FootprintSource:
    """Returns radar-estimate Evidence polygons for an event. The default is
    'not connected'. A live MRMS MESH source needs server-side processing of
    gridded data; a commercial provider needs a subscription."""
    key = "none"

    def __init__(self):
        self.feed = Feed("footprint", "Estimated hail footprint", "Not connected", "", state="not_connected",
                         detail="Connect MRMS MESH (needs a processing backend) or a licensed hail provider.")

    def events(self) -> list[dict]:
        return []

    def footprints(self, event_key: str) -> list[Evidence]:
        return []


class DemoFootprint(FootprintSource):
    key = "demo"

    def __init__(self, fixture: Path):
        super().__init__()
        self.data = json.loads(Path(fixture).read_text(encoding="utf-8"))
        self.feed = Feed("footprint", "Estimated hail footprint", "DEMO fixture (fictional)", str(fixture),
                         state="demo", detail="Fictional shapes for trying the workflow. Never shown for a real date.")

    def events(self):
        e = self.data.get("event", {})
        return [{"key": "demo", "label": e.get("label", "Demo event (fictional)")}]

    def footprints(self, event_key):
        if event_key != "demo":
            return []
        out = []
        for i, f in enumerate(self.data.get("features", [])):
            p = f.get("properties") or {}
            out.append(Evidence(
                id=f"demo:{i}", provider="DEMO", source_record_id=str(i), kind="radar_estimate", hazard="hail",
                issued_at=None, valid_from=p.get("valid_from", ""), valid_to=p.get("valid_to"),
                received_at=iso(utcnow()), geometry=f.get("geometry"),
                spatial_resolution_m=p.get("resolution_m"), magnitude=p.get("mesh_in"), unit="in",
                source_url=None, status="archived", raw=p, demo=True,
                label=f"DEMO estimated hail ≥ {p.get('mesh_in')}″"))
        return out


class GeoJSONFootprint(FootprintSource):
    """For a footprint service you run (for example an MRMS MESH job that
    publishes GeoJSON contours). Expects a FeatureCollection whose features
    carry mesh_in, valid_from, valid_to, resolution_m and event (YYYY-MM-DD)."""
    key = "geojson"

    def __init__(self, http: Http, url: str, enabled=True):
        super().__init__()
        self.http, self.url, self.enabled = http, url, enabled
        self.feed = Feed("footprint", "Estimated hail footprint", "Your GeoJSON feed", url,
                         detail="Radar-based estimates from the feed you configured.")

    def footprints(self, event_key):
        if not self.enabled:
            return []
        try:
            data, fetched = self.http.json(self.url, ttl=900, timeout=15, name="the hail footprint feed")
        except FeedError as e:
            self.feed.error = str(e)
            return []
        self.feed.fetched_at, self.feed.error = fetched, None
        out = []
        for i, f in enumerate(data.get("features", []) if isinstance(data, dict) else []):
            p = f.get("properties") or {}
            if str(p.get("event", "")) != event_key or p.get("mesh_in") is None:
                continue
            out.append(Evidence(
                id=f"feed:{event_key}:{i}", provider=p.get("provider", "Custom feed"), source_record_id=str(i),
                kind="radar_estimate", hazard="hail", issued_at=None, valid_from=p.get("valid_from", ""),
                valid_to=p.get("valid_to"), received_at=iso(fetched), geometry=f.get("geometry"),
                spatial_resolution_m=p.get("resolution_m"), magnitude=float(p["mesh_in"]), unit="in",
                source_url=self.url, status="archived", raw=p, label=f"Estimated hail ≥ {p['mesh_in']}″"))
        return out


# --------------------------------------------------------------------------
# Inspection targeting — explainable tiers, never a damage probability
# --------------------------------------------------------------------------
DEFAULT_TARGETING = {"radius_mi": 5.0, "tier1_in": 1.75, "tier1_mi": 1.0, "tier2_in": 1.0, "tier2_mi": 3.0}


def assess_place(place: dict, reports: list[Evidence], footprints: list[Evidence], cfg: dict) -> dict:
    """Why this place might deserve an inspection, in words. Estimates and
    reports are listed separately; nothing here confirms damage."""
    cfg = {**DEFAULT_TARGETING, **(cfg or {})}
    lat, lon = place["lat"], place["lng"]
    nearby = []
    for r in reports:
        if r.hazard != "hail" or not r.geometry:
            continue
        rlon, rlat = r.geometry["coordinates"][:2]
        d = haversine_mi(lat, lon, rlat, rlon)
        if d <= cfg["radius_mi"]:
            nearby.append((d, r))
    nearby.sort(key=lambda x: x[0])
    inside = [f for f in footprints if f.magnitude is not None and point_in(f.geometry, lat, lon)]
    est = max(inside, key=lambda f: f.magnitude) if inside else None
    best = max((r for _, r in nearby if r.magnitude is not None), key=lambda r: r.magnitude, default=None)
    best_d = next((d for d, r in nearby if r is best), None)

    tier = None
    if (est and est.magnitude >= cfg["tier1_in"]) or (best and best.magnitude >= cfg["tier1_in"] and best_d <= cfg["tier1_mi"]):
        tier = 1
    elif (est and est.magnitude >= cfg["tier2_in"]) or (best and best.magnitude >= cfg["tier2_in"] and best_d <= cfg["tier2_mi"]):
        tier = 2
    elif nearby or est:
        tier = 3

    reasons = []
    if est:
        where = "fictional demo data" if est.demo else est.provider
        reasons.append(f"Inside {'DEMO ' if est.demo else ''}estimated {est.magnitude:g}″ hail area "
                       f"({where}{f', ~{est.spatial_resolution_m / 1000:g} km grid' if est.spatial_resolution_m else ''})")
    if nearby:
        d, r = nearby[0]
        size = f"{r.magnitude:.2f}″" if r.magnitude is not None else "size unknown"
        reasons.append(f"Nearest report {size} at {d:.1f} mi (SPC preliminary)")
        if best is not None and best is not r:
            reasons.append(f"Largest report within {cfg['radius_mi']:g} mi: {best.magnitude:.2f}″ at {best_d:.1f} mi")
    if not reasons:
        reasons.append(f"No reports within {cfg['radius_mi']:g} mi and no estimate here — "
                       "that is not evidence that no hail fell")
    return {"tier": tier, "reasons": reasons, "nearby": nearby, "estimate": est,
            "evidence": ([est.to_dict()] if est else []) + [r.to_dict() for _, r in nearby[:5]]}


# --------------------------------------------------------------------------
# Feed contracts — what each parser assumes (units, timing, cadence, missing values).
# If a provider changes any of these, the parser and this table change together.
# --------------------------------------------------------------------------
CONTRACTS = [
    {"feed": "NWS official alerts", "endpoint": "api.weather.gov/alerts/active?area=MT (GeoJSON)",
     "units": "Hail: parameters.maxHailSize, inches. Gust: parameters.maxWindGust, text with MPH or KT.",
     "time": "sent/effective/onset/expires/ends are ISO 8601 with offset; stored in UTC.",
     "cadence": "Polled every 60 s by the app (provider caching honored).",
     "missing": "geometry may be null → match by UGC zone/county codes, never treat as no alert. "
                "messageType Update/Cancel reconcile earlier messages by reference ID. After a gap of more than "
                "two checks, /alerts?area=MT&start=… backfills messages issued during the outage."},
    {"feed": "NWS point lookup", "endpoint": "api.weather.gov/points/{lat},{lon}",
     "units": "—", "time": "timeZone gives the job's IANA zone.",
     "cadence": "Cached 24 h; zone codes re-checked every 30 days.",
     "missing": "forecastZone, county, fireWeatherZone are the place's alert-matching codes."},
    {"feed": "NWS hourly forecast", "endpoint": "gridpoints/{wfo}/{x},{y}/forecast/hourly",
     "units": "temperature °F; windSpeed text like '10 to 15 mph' (the higher number is used for rules); "
              "probabilityOfPrecipitation %.", "time": "startTime with local offset; ~2.5 km grid.",
     "cadence": "Cached 30 min (Cache-Control honored).",
     "missing": "null probability or wind = missing input → 'Data unavailable', never treated as zero."},
    {"feed": "NWS gridpoint data", "endpoint": "gridpoints/{wfo}/{x},{y}",
     "units": "windGust km/h (wmoUnit:km_h-1) → mph; quantitativePrecipitation mm per validTime interval → in; "
              "wetBulbGlobeTemperature and heatIndex °C → °F (forecast values, not measurements).",
     "time": "validTime = ISO start + duration (e.g. PT6H); a rain amount belongs to its whole interval.",
     "cadence": "Cached 30 min.", "missing": "Hours with no value stay missing."},
    {"feed": "NOAA radar mosaic", "endpoint": "mapservices.weather.noaa.gov … radar_base_reflectivity WMS, layer \"1\"",
     "units": "Reflectivity colors (dBZ ramp) — precipitation echoes, not hail size or wind at a roof.",
     "time": "Frame valid time from the service's idp_validtime (ms since epoch, UTC).",
     "cadence": "New frames every few minutes; frame time and retrieval time are shown separately.",
     "missing": "No frame time → radar shown as unavailable/stale, never as current."},
    {"feed": "SPC preliminary reports", "endpoint": "spc.noaa.gov/climo/reports/YYMMDD_rpts_[filtered_]{hail|wind}.csv",
     "units": "Hail size in hundredths of an inch (175 = 1.75 in). Wind gusts in mph; UNK = unknown (kept null).",
     "time": "HHMM UTC within a reporting day 12:00 UTC → 11:59 UTC next day (times before 12:00 are the next date).",
     "cadence": "Cached 10 min for the current and previous day, 6 h for older days.",
     "missing": "No reports ≠ no hail. Reports are points near where someone reported, not swaths."},
    {"feed": "Hail footprint (GeoJSON feed)", "endpoint": "Your URL (for an MRMS MESH job or a licensed provider)",
     "units": "properties.mesh_in inches; resolution_m metres.",
     "time": "valid_from/valid_to: the swath maximum belongs to that interval, not to the latest timestamp.",
     "cadence": "Cached 15 min.", "missing": "Features without mesh_in are ignored and counted as missing."},
    {"feed": "Address search", "endpoint": "geocoding.geo.census.gov (benchmark Public_AR_Current); nominatim.openstreetmap.org",
     "units": "WGS84 lat/lon.", "time": "—", "cadence": "On demand; cached 24 h; OpenStreetMap ≤ 1 request/s.",
     "missing": "City/ZIP results are area centers — address precision is not weather precision."},
]

COVERAGE = [
    ("NWS alerts & forecasts", "United States and territories"),
    ("NOAA radar mosaic", "CONUS and nearby (NEXRAD)"),
    ("SPC preliminary reports", "United States"),
    ("MRMS MESH (not connected)", "CONUS, ~1 km grid"),
    ("Census geocoder", "United States street addresses"),
]
