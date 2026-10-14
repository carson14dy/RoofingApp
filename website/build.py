"""Build the Montana Hail Watch website into a folder of static files.

    python -m website.build --out _site                 # live data (needs internet)
    python -m website.build --out _site --sample        # labelled sample data, no network
    python -m website.build --out _site --require-live  # fail if any source failed (preview checks)

GitHub Actions runs the live build every 10 minutes and publishes the folder with GitHub Pages
(.github/workflows/website.yml). Every page says when its data was fetched; nothing on a page is
newer than that time.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import folium
from branca.element import MacroElement
from folium.raster_layers import ImageOverlay
from folium.template import Template
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import sources as src

HERE = Path(__file__).resolve().parent
UTC = timezone.utc
MT = ZoneInfo("America/Denver")
TOWNS = json.loads((HERE / "towns.json").read_text(encoding="utf-8"))
OFFICES = [("Billings", "https://www.weather.gov/byz/"), ("Glasgow", "https://www.weather.gov/ggw/"),
           ("Great Falls", "https://www.weather.gov/tfx/"), ("Missoula", "https://www.weather.gov/mso/")]
USGS_TOPO = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}"
KIND_STYLE = {"warning": "#c0262d", "watch": "#c26100", "advisory": "#a07800", "statement": "#4b5d72"}

# Styles for the map pages. Leaflet's stylesheet loads after this block, so each selector here is
# one step more specific than Leaflet's own (html .leaflet-container, .leaflet-tooltip.town-label).
# Maps narrower than 546 px open at zoom 5 (phones). There, the "minor" towns in towns.json are
# hidden, dot and label, so the main towns' labels have room; every town still has its card.
# Below 273 px the map opens at zoom 4 and no labels fit.
MAP_CSS = """
html, body, html .leaflet-container { background: #eef1f4; }
html .leaflet-container { font: 14px/1.4 'Atkinson Hyperlegible Next', system-ui, sans-serif; }
.base-tiles { filter: grayscale(1) contrast(.85) brightness(1.06); }
.leaflet-tooltip.town-label { background: none; border: 0; box-shadow: none; padding: 0 3px;
  font-size: 13px; font-weight: 700; color: #0e1a27; text-shadow: 0 0 2px #fff, 0 0 3px #fff, 0 0 4px #fff; }
.leaflet-tooltip.town-label::before { display: none; }
@media (max-width: 545px) { .leaflet-tooltip.town-label.minor, .town-dot.minor { display: none; } }
@media (max-width: 272px) { .leaflet-tooltip.town-label { display: none; } }
@media (prefers-color-scheme: dark) {
  html, body, html .leaflet-container { background: #0f151c; }
  .base-tiles { filter: grayscale(1) invert(1) brightness(.78) contrast(.9); }
  .leaflet-tooltip.town-label { color: #e8edf2; text-shadow: 0 0 2px #000, 0 0 3px #000, 0 0 4px #000; }
}
"""


# ---------------------------------------------------------------- gathering

class Collector:
    """Fetches every source once and records, per source, what happened and when."""

    def __init__(self, fetch: src.Fetcher, now: datetime, previous: dict | None = None):
        self.f, self.now, self.prev = fetch, now, previous or {}
        self.status: dict[str, dict] = {}

    def note(self, key, label, ok, detail="", when=None):
        self.status[key] = {"label": label, "ok": ok, "detail": detail, "when": src._iso(when or self.now)}

    def alerts(self):
        doc, err = self.f.json(f"{src.NWS}/alerts/active", {"area": "MT"})
        try:
            if err:
                raise ValueError(err)
            items = src.parse_alerts(doc)
            self.note("alerts", "NWS alerts", True, f"{len(items)} active")
            return {"items": items, "ok": True, "checked": src._iso(self.now), "last_known": None}
        except ValueError as e:
            last = self.prev.get("alerts") or {}
            self.note("alerts", "NWS alerts", False, str(e))
            # Never clear a warning after a failed request: keep the last list we did verify.
            return {"items": last.get("items") or [], "ok": False, "checked": src._iso(self.now),
                    "last_known": last.get("checked") if last.get("ok") else last.get("last_known"),
                    "error": str(e)}

    def town(self, t):
        out = {**t, "errors": [], "hours": [], "days": [], "alerts": None, "updated": None,
               "tz": "America/Denver", "office": None, "near": ""}
        point = None
        doc, err = self.f.json(f"{src.NWS}/points/{t['lat']:.4f},{t['lon']:.4f}")
        try:
            if err:
                raise ValueError(err)
            point = src.parse_point(doc)
        except ValueError as e:
            point = (self.prev.get("points") or {}).get(t["slug"])
            if not point:
                out["errors"].append(f"Couldn't look up the NWS forecast grid ({e}).")
        if point:
            out.update(point=point, tz=point["tz"], office=point["office"], near=point["near"])
            doc, err = self.f.json(point["hourly"])
            try:
                if err:
                    raise ValueError(err)
                out["hours"], out["updated"] = src.parse_hourly(doc)
            except ValueError as e:
                out["errors"].append(f"Hourly forecast didn't load ({e}).")
            doc, err = self.f.json(point["grid"])
            try:
                if err:
                    raise ValueError(err)
                gusts = src.parse_gusts(doc)
                for h in out["hours"]:
                    h["gust_mph"] = gusts.get(h["start"])
            except ValueError as e:
                out["errors"].append(f"Gust forecast didn't load ({e}).")
            doc, err = self.f.json(point["forecast"])
            try:
                if err:
                    raise ValueError(err)
                out["days"] = src.pair_days(src.parse_daily(doc))
            except ValueError as e:
                out["errors"].append(f"7-day forecast didn't load ({e}).")
        doc, err = self.f.json(f"{src.NWS}/alerts/active", {"point": f"{t['lat']:.4f},{t['lon']:.4f}"})
        try:
            if err:
                raise ValueError(err)
            out["alerts"] = src.parse_alerts(doc)
        except ValueError as e:
            out["errors"].append(f"Couldn't check official alerts for {t['name']} ({e}).")
        for h in out["hours"]:
            h["flags"] = src.flags_for(h)
        out["summary"] = src.summarize(out["hours"], self.now)
        return out

    def towns(self):
        towns = [self.town(t) for t in TOWNS]
        good = sum(1 for t in towns if t["hours"])
        self.note("forecasts", "NWS forecasts", good == len(towns), f"{good} of {len(towns)} towns")
        return towns

    def reports(self, days=3):
        today = src.spc_day_for(self.now)
        out, problems = [], []
        for back in range(days):
            day = today - timedelta(days=back)
            for kind in ("hail", "wind"):
                text, err = self.f.text(src.spc_url(day, kind))
                if err:
                    if not (back == 0 and err.startswith("not published")):
                        problems.append(f"{kind} {strftime(day, '%b %-d')}: {err}")
                    continue
                try:
                    out.extend(src.parse_spc(text, day, kind))
                except ValueError as e:
                    problems.append(f"{kind} {strftime(day, '%b %-d')}: {e}")
        out.sort(key=lambda r: r["time"], reverse=True)
        self.note("reports", "SPC storm reports", not problems,
                  "; ".join(problems) if problems else f"{len(out)} reports in 3 days")
        return {"items": out, "problems": problems, "days": [(today - timedelta(days=b)).isoformat()
                                                             for b in range(days)]}

    def radar(self, out_dir: Path):
        doc, err = self.f.json(src.RADAR_TIME, {"where": "1=1", "outFields": "idp_validtime",
                                                 "returnGeometry": "false", "orderByFields": "idp_validtime DESC",
                                                 "resultRecordCount": 1, "f": "json"})
        try:
            if err:
                raise ValueError(err)
            frame = src.parse_radar_time(doc)
        except ValueError as e:
            self.note("radar", "NOAA radar", False, str(e))
            return None
        params, w, h = src.radar_request()
        png, err = self.f.png(src.RADAR_WMS, params)
        if err:
            self.note("radar", "NOAA radar", False, err)
            return None
        (out_dir / "radar.png").write_bytes(png)
        size = src.png_size(png)
        if size != (w, h):
            self.note("radar", "NOAA radar", False, f"image was {size}, expected {(w, h)}")
            return None
        age = (self.now - frame).total_seconds() / 60
        self.note("radar", "NOAA radar", age <= 15, f"frame {round(age)} min old", when=frame)
        return {"frame": src._iso(frame), "bytes": len(png), "colored": colored_fraction(png)}


def colored_fraction(png: bytes) -> float | None:
    """Share of non-transparent pixels, for the build log only (needs Pillow; optional)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    import io
    try:
        hist = Image.open(io.BytesIO(png)).convert("RGBA").getchannel("A").histogram()
    except Exception:   # logging only: never fail a build over it
        return None
    return round(1 - hist[0] / sum(hist), 4)


# ---------------------------------------------------------------- maps

class LinkPopup(MacroElement):
    """A Leaflet popup with fixed HTML. Folium's own Popup needs jQuery, which this site doesn't load."""
    _template = Template("{% macro script(this, kwargs) %}"
                         "{{ this._parent.get_name() }}.bindPopup({{ this.html|tojson }});"
                         "{% endmacro %}")

    def __init__(self, html: str):
        super().__init__()
        self._name = "LinkPopup"
        self.html = html


def new_map(height_note: str = "") -> folium.Map:
    (s, w), (n, e) = src.radar_bounds()
    m = folium.Map(location=[46.9, -109.6], zoom_start=6, tiles=None, control_scale=True,
                   min_zoom=4, max_bounds=True,
                   min_lat=s - 3, max_lat=n + 3, min_lon=w - 6, max_lon=e + 6)
    # Serve Leaflet from this site, not a CDN, and drop the CSS/JS Folium adds by default.
    m.default_js = [("leaflet", "static/leaflet/leaflet.js")]
    m.default_css = [("leaflet_css", "static/leaflet/leaflet.css")]
    folium.TileLayer(USGS_TOPO, attr="USGS The National Map", name="Base map (USGS topo)",
                     max_native_zoom=16, max_zoom=18, class_name="base-tiles").add_to(m)
    m.get_root().header.add_child(folium.Element(
        f'<link rel="stylesheet" href="static/fonts/fonts.css"><style>{MAP_CSS}</style>'))
    m.fit_bounds([[src.MT_BOX[0], src.MT_BOX[2]], [src.MT_BOX[1], src.MT_BOX[3]]])
    return m


def add_radar(m, radar, built):
    if not radar:
        return
    overlay = ImageOverlay(image="data:image/png;base64,", bounds=[list(b) for b in src.radar_bounds()],
                           opacity=0.72, name=f"Radar, frame {fmt_time(radar['frame'])}", interactive=False)
    overlay.url = f"radar.png?v={built:%Y%m%d%H%M}"   # served beside the map, not embedded
    overlay.add_to(m)


def add_alerts(m, alerts):
    shapes = [a for a in alerts if a.get("geometry")]
    if not shapes:
        return
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": a["geometry"],
         "properties": {"event": a["event"], "until": "until " + fmt_time(a["until"]) if a["until"] else "",
                        "color": KIND_STYLE[a["kind"]]}} for a in shapes]}
    folium.GeoJson(fc, name="Warning areas (NWS)",
                   style_function=lambda f: {"color": f["properties"]["color"], "weight": 2.5,
                                             "fillColor": f["properties"]["color"], "fillOpacity": 0.14},
                   tooltip=folium.GeoJsonTooltip(fields=["event", "until"], labels=False)).add_to(m)


def add_towns(m, towns, prefix=""):
    group = folium.FeatureGroup(name="Towns")
    for t in towns:
        link = f'<a href="{prefix}town/{t["slug"]}.html" target="_top">{t["name"]} forecast</a>'
        # Label side and "minor" (no dot or label on narrow maps) are set per town in towns.json
        # so labels never cover each other or another town's dot (tests/test_site.py checks it).
        minor = " minor" if t.get("minor") else ""
        marker = folium.CircleMarker([t["lat"], t["lon"]], radius=5, color="#0e1a27", weight=2, fill=True,
                                     fill_color="#ffffff", fill_opacity=1, class_name="town-dot" + minor,
                                     tooltip=folium.Tooltip(t["name"], permanent=True,
                                                            direction=t.get("label", "right"),
                                                            class_name="town-label" + minor))
        LinkPopup(link).add_to(marker)
        marker.add_to(group)
    group.add_to(m)


def add_reports(m, reports):
    group = folium.FeatureGroup(name="Storm reports (SPC)")
    for r in reports:
        if r["kind"] == "hail":
            size = r["size_in"]
            radius = 4 + 4 * (size or 0.5)
            label = f"Hail {size:.2f} in" if size else "Hail, size not given"
            color = "#6b3fa0"
        else:
            radius = 6
            label = f"Wind {r['mph']} mph" if r["mph"] else "Wind damage, speed unknown"
            color = "#0b6e6e"
        tip = f"{label} · {fmt_time(r['time'], '%a %-I:%M %p')} · {r['place']}, {r['county']} Co. {r['state']}"
        folium.CircleMarker([r["lat"], r["lon"]], radius=radius, color=color, weight=2, fill=True,
                            fill_color=color, fill_opacity=0.35, tooltip=tip).add_to(group)
    group.add_to(m)


def save_map(m, path: Path):
    folium.LayerControl(collapsed=True).add_to(m)
    m.save(str(path))


# ---------------------------------------------------------------- rendering helpers

def strftime(dt, pattern: str) -> str:
    """strftime with %-I and %-d (no leading zero) on every platform; Windows lacks them."""
    pattern = pattern.replace("%-I", str(int(dt.strftime("%I")))).replace("%-d", str(dt.day))
    return dt.strftime(pattern)


def fmt_time(value, pattern="%a %-I:%M %p %Z", tz=MT) -> str:
    """UTC instant -> Montana local text, e.g. 'Tue 7:40 am MDT'. Unknown stays a dash."""
    if value is None:
        return "—"
    dt = value if isinstance(value, datetime) else src.parse_iso(value)
    if dt is None:
        return "—"
    return strftime(dt.astimezone(tz), pattern).replace("AM", "am").replace("PM", "pm")


def env() -> Environment:
    e = Environment(loader=FileSystemLoader(str(HERE / "templates")), autoescape=select_autoescape(["html"]),
                    trim_blocks=True, lstrip_blocks=True)
    e.filters["t"] = lambda v, p="%-I:%M %p": fmt_time(v, p)
    e.filters["when"] = lambda v: fmt_time(v)
    e.filters["day"] = lambda v: fmt_time(v, "%a %b %-d")
    e.filters["num"] = lambda v: "—" if v is None else f"{round(v)}"
    return e


# ---------------------------------------------------------------- build

def build(out: Path, fetch: src.Fetcher | None, now: datetime, previous: dict | None = None,
          sample: bool = False) -> dict:
    if out.exists():
        shutil.rmtree(out)
    (out / "town").mkdir(parents=True)
    (out / "data").mkdir()
    shutil.copytree(HERE / "static", out / "static")

    if sample:
        from . import sample as sample_data
        fetch = sample_data.SampleFetcher(now)
    c = Collector(fetch, now, previous)
    alerts = c.alerts()
    towns = c.towns()
    reports = c.reports()
    radar = None if sample else c.radar(out)
    if sample:
        c.note("radar", "NOAA radar", False, "not loaded in sample builds")

    m = new_map()
    add_radar(m, radar, now)
    add_alerts(m, alerts["items"])
    add_towns(m, towns)
    save_map(m, out / "map-now.html")
    m = new_map()
    add_reports(m, reports["items"])
    add_towns(m, towns)
    save_map(m, out / "map-reports.html")

    base = {"built": now, "built_ms": int(now.timestamp() * 1000), "status": c.status, "sample": sample,
            "limits": src.LIMITS, "offices": OFFICES, "towns_nav": [(t["slug"], t["name"]) for t in TOWNS],
            "contracts": src.CONTRACTS}
    e = env()
    pages = {
        "index.html": ("index.html", {"page": "now", "root": "", "alerts": alerts, "towns": towns, "radar": radar}),
        "reports.html": ("reports.html", {"page": "reports", "root": "", "reports": reports}),
        "about.html": ("about.html", {"page": "about", "root": ""}),
    }
    for name, (tpl, ctx) in pages.items():
        (out / name).write_text(e.get_template(tpl).render(**base, **ctx), encoding="utf-8")
    for t in towns:
        html = e.get_template("town.html").render(**base, page="town", root="../", town=t, now=now,
                                                 delta_hour=timedelta(hours=1))
        (out / "town" / f"{t['slug']}.html").write_text(html, encoding="utf-8")

    state = {"built": src._iso(now), "sample": sample, "status": c.status,
             "alerts": {k: v for k, v in alerts.items() if k != "error"},
             "points": {t["slug"]: t["point"] for t in towns if t.get("point")}}
    (out / "data" / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"status": c.status, "alerts": len(alerts["items"]),
            "alerts_null_geometry": sum(1 for a in alerts["items"] if not a["geometry"]),
            "towns_with_forecast": sum(1 for t in towns if t["hours"]),
            "towns_with_gusts": sum(1 for t in towns if t["summary"]["gusts_known"]),
            "reports": len(reports["items"]), "radar": radar}


def load_previous(url: str | None) -> dict | None:
    if not url:
        return None
    data, err = src.Fetcher(timeout=10).json(url.rstrip("/") + "/data/state.json")
    if err or not isinstance(data, dict) or data.get("sample"):
        return None
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Montana Hail Watch website")
    ap.add_argument("--out", default="_site", help="output folder (replaced)")
    ap.add_argument("--sample", action="store_true", help="use labelled sample data; no network")
    ap.add_argument("--previous", help="URL of the live site, for last-known alerts if NWS fails")
    ap.add_argument("--require-live", action="store_true", help="exit 1 if any source failed")
    ap.add_argument("--now", help="build time (ISO, UTC); default: now")
    a = ap.parse_args(argv)
    now = src.parse_iso(a.now) if a.now else datetime.now(UTC).replace(microsecond=0)
    out = Path(a.out)
    result = build(out, None if a.sample else src.Fetcher(), now,
                   None if a.sample else load_previous(a.previous), sample=a.sample)
    print(json.dumps(result, indent=1, default=str))
    failed = [k for k, v in result["status"].items() if not v["ok"]]
    if a.require_live and failed:
        print("Sources that failed or were stale: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
