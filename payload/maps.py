"""
Map building (Folium, all from Python). Each kind of evidence has its own
shape so the map never relies on color alone:

    ▲ triangle + size label   reported hail (SPC, preliminary)
    ● circle                  crew inspection finding (inspection-confirmed)
    ▒ translucent band        estimated hail (radar estimate) — DEMO when demo
    ─ solid / ┄ dashed line   official warning / watch or advisory (NWS)
    ■ square / ⌂ house        job / property you saved
    ┄ white dashed outline    your service territory
"""

from __future__ import annotations

import json
import time
from html import escape

import folium
from folium.plugins import Draw, Fullscreen, MousePosition

from . import weather as wx

MT_CENTER, MT_ZOOM = (47.0, -109.6), 6

SIZES = [
    {"key": "pea",    "max": 0.75, "repr": 0.50, "color": "#38b000", "label": "Pea–Dime",       "ref": '0.50"'},
    {"key": "penny",  "max": 1.00, "repr": 0.88, "color": "#ffd23f", "label": "Penny–Quarter",  "ref": '0.88"'},
    {"key": "walnut", "max": 1.50, "repr": 1.25, "color": "#ff9f1c", "label": "Quarter–Walnut", "ref": '1.25"'},
    {"key": "golf",   "max": 2.00, "repr": 1.75, "color": "#fb5607", "label": "Golf ball",      "ref": '1.75"'},
    {"key": "egg",    "max": 2.75, "repr": 2.50, "color": "#e5383b", "label": "Hen egg–Tennis", "ref": '2.50"'},
    {"key": "base",   "max": 99.0, "repr": 3.00, "color": "#b5179e", "label": "Baseball+",      "ref": '2.75"+'},
]
UNKNOWN = "#8ea6bf"


def size_class(inches):
    n = float(inches or 0)
    return next((s for s in SIZES if n < s["max"]), SIZES[-1])


def size_color(inches):
    return UNKNOWN if inches is None else size_class(inches)["color"]


def size_label(inches):
    return "size unknown" if inches is None else size_class(inches)["label"]


def new_map(center=None, zoom=None) -> folium.Map:
    m = folium.Map(location=center or MT_CENTER, zoom_start=zoom or MT_ZOOM, tiles=None,
                   control_scale=True, prefer_canvas=True)
    # Folium adds Bootstrap and icon fonts by default; they aren't used and fight the app's styles.
    m.default_css = [c for c in m.default_css if c[0] == "leaflet_css"]
    m.default_js = [j for j in m.default_js if j[0] in ("leaflet", "jquery")]
    # USGS The National Map: public domain, no API key. (CARTO's free tiles now require a key.)
    usgs = "https://basemap.nationalmap.gov/arcgis/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
    attr = "Base map: USGS The National Map"
    folium.TileLayer(tiles=usgs.format("USGSTopo"), attr=attr, name="Dark topo (USGS)", max_native_zoom=16,
                     max_zoom=19, class_name="hw-dark-base").add_to(m)
    folium.TileLayer(tiles=usgs.format("USGSTopo"), attr=attr, name="Topo (USGS)", max_native_zoom=16,
                     max_zoom=19, show=False, overlay=False).add_to(m)
    folium.TileLayer(tiles=usgs.format("USGSImageryTopo"), attr=attr, name="Imagery (USGS)", max_native_zoom=16,
                     max_zoom=19, show=False, overlay=False).add_to(m)
    return m


def add_radar(m, feed: wx.Feed, tz=None):
    when = f" — frame {wx.fmt_local(feed.source_time, tz, with_date=False)}" if feed.source_time else ""
    layer = folium.raster_layers.WmsTileLayer(
        url=wx.RADAR_WMS, layers=wx.RADAR_LAYER, name=f"Radar reflectivity (NOAA){when}",
        fmt="image/png", transparent=True, version="1.3.0", opacity=0.72, overlay=True, control=True,
        attr="Radar &copy; NOAA / National Weather Service", cachebust=int(time.time() // 60))
    layer.add_to(m)
    return layer


def add_alerts(m, alerts, tz=None, name="Official alerts (NWS)"):
    fg = folium.FeatureGroup(name=name, show=True)
    for a in alerts:
        if not a.get("geometry"):
            continue
        warning = "Warning" in (a.get("event") or "")
        col = size_color(a["hail_in"]) if a.get("hail_in") else ("#ff6b6b" if warning else "#ffd23f")
        until = wx.fmt_local(a.get("ends") or a.get("expires"), tz)
        tip = (f"<b>{escape(a.get('event') or '')}</b> (official, NWS)<br>{escape(a.get('area') or '')}"
               f"<br>Until {escape(until)}" + (f"<br>Hail up to {a['hail_in']:g}″ per NWS" if a.get("hail_in") else ""))
        folium.GeoJson(
            a["geometry"],
            style_function=(lambda col, w: lambda _x: {"color": col, "weight": 2.5 if w else 2, "fillColor": col,
                                                        "fillOpacity": 0.08, "dashArray": None if w else "6 5"})(col, warning),
            tooltip=folium.Tooltip(tip)).add_to(fg)
    fg.add_to(m)


def add_zone_alerts(m, alerts, zone_geoms: dict, tz=None):
    """Alerts issued for whole forecast zones or counties (no polygon). Drawn
    from the zone boundaries so they don't vanish from the map."""
    shapes = [(a, url, zone_geoms[url]) for a in alerts for url in (a.get("zones") or []) if url in zone_geoms]
    if not shapes:
        return
    fg = folium.FeatureGroup(name="Official alerts by zone/county (NWS)", show=True)
    for a, url, geom in shapes:
        warning = "Warning" in (a.get("event") or "")
        col = "#ff6b6b" if warning else "#9fb4cc"
        until = wx.fmt_local(a.get("ends") or a.get("expires"), tz)
        tip = (f"<b>{escape(a.get('event') or '')}</b> (official, NWS)<br>Applies by zone "
               f"{escape(url.rsplit('/', 1)[-1])}<br>Until {escape(until)}")
        folium.GeoJson(geom, style_function=(lambda col: lambda _x: {
            "color": col, "weight": 1.2, "dashArray": "2 4", "fillColor": col, "fillOpacity": 0.05})(col),
            tooltip=folium.Tooltip(tip)).add_to(fg)
    fg.add_to(m)


def report_icon(ev: wx.Evidence) -> folium.DivIcon:
    col = size_color(ev.magnitude) if ev.hazard == "hail" else "#cfd8e3"
    if ev.hazard == "hail":
        text = f"{ev.magnitude:.2f}″" if ev.magnitude is not None else "?"
    else:
        text = f"{ev.magnitude:.0f} mph" if ev.magnitude is not None else "UNK"
    html = (f'<div class="mk mk-rep"><svg width="16" height="14" viewBox="0 0 16 14" aria-hidden="true">'
            f'<path d="M8 1 15 13H1Z" fill="{col}" stroke="#0c1622" stroke-width="1.3"/></svg>'
            f'<span>{escape(text)}</span></div>')
    return folium.DivIcon(html=html, icon_size=(80, 16), icon_anchor=(8, 8))


def add_reports(m, reports, tz=None, name="Reported hail (SPC, preliminary)", show=True):
    fg = folium.FeatureGroup(name=name, show=show)
    for ev in reports:
        lon, lat = ev.geometry["coordinates"][:2]
        when = wx.fmt_local(ev.valid_from, tz)
        mag = ("size unknown" if ev.magnitude is None else f"{ev.magnitude:.2f}″") if ev.hazard == "hail" \
            else ("speed unknown" if ev.magnitude is None else f"{ev.magnitude:.0f} mph gust")
        tip = (f"<b>Reported {escape(ev.hazard)}: {escape(mag)}</b> — SPC preliminary<br>{escape(ev.label)}"
               f"<br>{escape(when)} ({escape(ev.raw.get('time_utc_hhmm', ''))} UTC)"
               f"<br><i>{escape(ev.raw.get('comments', '')[:160])}</i>")
        folium.Marker([lat, lon], icon=report_icon(ev), tooltip=folium.Tooltip(tip)).add_to(fg)
    fg.add_to(m)


def add_footprints(m, footprints, name=None, fit=False):
    if not footprints:
        return
    if fit:
        boxes = [wx.bbox(f.geometry) for f in footprints if f.geometry]
        boxes = [b for b in boxes if b]
        if boxes:
            pad = 0.15
            m.fit_bounds([[min(b[1] for b in boxes) - pad, min(b[0] for b in boxes) - pad],
                          [max(b[3] for b in boxes) + pad, max(b[2] for b in boxes) + pad]])
    demo = any(f.demo for f in footprints)
    fg = folium.FeatureGroup(name=name or ("DEMO — estimated hail (fictional)" if demo else "Estimated hail (radar)"),
                             show=True)
    for f in sorted(footprints, key=lambda f: f.magnitude or 0):
        col = size_color(f.magnitude)
        res = f" · ~{f.spatial_resolution_m / 1000:g} km grid" if f.spatial_resolution_m else ""
        tip = f"<b>{escape(f.label)}</b><br>{escape(f.kind_label)} · {escape(f.provider)}{escape(res)}"
        folium.GeoJson(
            f.geometry,
            style_function=(lambda col, d: lambda _x: {"color": col, "weight": 1, "dashArray": "3 4" if d else None,
                                                        "fillColor": col, "fillOpacity": 0.30})(col, f.demo),
            tooltip=folium.Tooltip(tip)).add_to(fg)
    fg.add_to(m)


def place_icon(p) -> folium.DivIcon:
    glyph = ('<rect x="2" y="2" width="11" height="11" rx="1.5" fill="#e9f0f7" stroke="#0c1622" stroke-width="1.4"/>'
             if p["kind"] == "job" else
             '<path d="M7.5 1.5 14 7v6.5H1V7Z" fill="#e9f0f7" stroke="#0c1622" stroke-width="1.4"/>')
    # Name shows on hover (tooltip) — permanent labels collide at state-wide zoom.
    html = f'<div class="mk mk-place"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true">{glyph}</svg></div>'
    return folium.DivIcon(html=html, icon_size=(16, 16), icon_anchor=(7, 8))


def add_places(m, places):
    if not places:
        return
    fg = folium.FeatureGroup(name="Your jobs & properties", show=True)
    for p in places:
        kind = "Job" if p["kind"] == "job" else "Property"
        tip = (f"<b>{escape(p['name'])}</b> — {kind}<br>{escape(p.get('address') or '')}"
               f"<br>Located by {escape(p.get('located_by') or 'hand')} ({escape(p.get('precision') or 'point')})")
        folium.Marker([p["lat"], p["lng"]], icon=place_icon(p), tooltip=folium.Tooltip(tip)).add_to(fg)
    fg.add_to(m)


def add_territories(m, territories):
    if not territories:
        return
    fg = folium.FeatureGroup(name="Your service territories", show=True)
    for t in territories:
        folium.GeoJson(json.loads(t["geojson"]),
                       style_function=lambda _x: {"color": "#e9f0f7", "weight": 1.6, "dashArray": "8 6",
                                                  "fillOpacity": 0},
                       tooltip=escape(f"Territory: {t['name']}")).add_to(fg)
    fg.add_to(m)


def add_findings(m, findings, areas):
    if areas:
        fg = folium.FeatureGroup(name="Crew-observed hail areas", show=True)
        for h in areas:
            col = size_color(h["size_in"])
            folium.GeoJson(json.loads(h["geojson"]),
                           style_function=(lambda col: lambda _x: {"color": col, "weight": 2, "fillColor": col,
                                                                    "fillOpacity": 0.18})(col),
                           tooltip=escape(f"Crew-observed: {h['name'] or 'area'} — {h['size_in']:.2f}″ "
                                          f"(inspection-confirmed)")).add_to(fg)
        fg.add_to(m)
    if findings:
        fg = folium.FeatureGroup(name="Crew inspection findings", show=True)
        for r in findings:
            col = size_color(r["size_in"])
            e = escape
            popup = (f'<div style="font-family:system-ui;min-width:170px"><b style="color:{col}">'
                     f'{r["size_in"]:.2f}″ · {e(size_label(r["size_in"]))}</b><br>Inspection-confirmed (crew)'
                     f'<br>{e(r["hood"] or "")} {e(r["address"] or "")}<br>Observed {e(r["obs_date"] or "—")}'
                     f'<br>{e(r["notes"] or "")}</div>')
            folium.CircleMarker([r["lat"], r["lng"]], radius=max(6, min(20, 5 + r["size_in"] * 5)),
                                color="#0c1622", weight=1.5, fill_color=col, fill_opacity=0.9,
                                popup=folium.Popup(popup, max_width=260)).add_to(fg)
        fg.add_to(m)


def add_pin(m, lat, lon, label):
    folium.Marker([lat, lon], tooltip=escape(label),
                  icon=folium.DivIcon(html='<div class="mk mk-pin"></div>', icon_size=(18, 18),
                                      icon_anchor=(9, 9))).add_to(m)


def finish(m, draw=True):
    MousePosition(position="bottomleft", prefix="Lat, Lng:", num_digits=5, separator=" , ",
                  empty_string="Point at the map for coordinates").add_to(m)
    Fullscreen().add_to(m)
    if draw:
        Draw(export=False, show_geometry_on_click=False,
             draw_options={"polyline": False, "circle": False, "marker": False, "circlemarker": False,
                           "rectangle": True, "polygon": True},
             edit_options={"edit": False, "remove": False}).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)


def exposure_svg(candidate: dict, evidence: list, width=560, height=360) -> str:
    """A small, self-contained map for the printable exposure summary: the
    place, nearby report points and any estimate areas, with a scale bar and
    north arrow. No web tiles, so it prints and archives cleanly."""
    import math
    lat0, lon0 = candidate["place_lat"], candidate["place_lng"]
    kx, ky = 69.172 * math.cos(math.radians(lat0)), 69.0          # miles per degree

    def xy(lon, lat):
        return (lon - lon0) * kx, (lat - lat0) * ky

    pts = [xy(*e.geometry["coordinates"][:2]) for e in evidence if e.geometry and e.geometry.get("type") == "Point"]
    reach = max([1.5] + [math.hypot(x, y) * 1.25 for x, y in pts])
    reach = min(reach, 8.0)
    scale = min(width, height) / 2 / reach * 0.92
    cx, cy = width / 2, height / 2

    def sx(x, y):
        return cx + x * scale, cy - y * scale

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" '
           f'role="img" aria-label="Map of {escape(candidate["place_name"])} and nearby weather evidence">',
           f'<rect width="{width}" height="{height}" fill="#f4f7fa" stroke="#9fb0c2"/>']
    for e in evidence:
        if e.kind != "radar_estimate" or not e.geometry:
            continue
        col = size_color(e.magnitude)
        for rings in wx._polygons(e.geometry):
            d = " ".join(("M" if i == 0 else "L") + "{:.1f},{:.1f}".format(*sx(*xy(p[0], p[1])))
                         for i, p in enumerate(rings[0])) + " Z"
            out.append(f'<path d="{d}" fill="{col}" fill-opacity="0.35" stroke="{col}" '
                       f'stroke-dasharray="{"4 3" if e.demo else "none"}"/>')
    for e in evidence:
        if not e.geometry or e.geometry.get("type") != "Point":
            continue
        x, y = sx(*xy(*e.geometry["coordinates"][:2]))
        col = size_color(e.magnitude) if e.hazard == "hail" else "#7a8794"
        txt = (f"{e.magnitude:.2f}″" if e.magnitude is not None else "?") if e.hazard == "hail" else \
              (f"{e.magnitude:.0f} mph" if e.magnitude is not None else "UNK")
        out.append(f'<path d="M{x:.1f},{y - 7:.1f} L{x + 7:.1f},{y + 5:.1f} L{x - 7:.1f},{y + 5:.1f} Z" '
                   f'fill="{col}" stroke="#1c2c3f" stroke-width="1"/>'
                   f'<text x="{x + 9:.1f}" y="{y + 4:.1f}" font-size="11" font-family="Arial" fill="#1c2c3f">{escape(txt)}</text>')
    glyph = (f'<rect x="{cx - 7}" y="{cy - 7}" width="14" height="14" fill="#1c2c3f"/>' if candidate.get("place_kind") == "job"
             else f'<path d="M{cx},{cy - 9} L{cx + 9},{cy - 1} L{cx + 9},{cy + 8} L{cx - 9},{cy + 8} L{cx - 9},{cy - 1} Z" fill="#1c2c3f"/>')
    out.append(glyph + f'<text x="{cx + 13}" y="{cy - 10}" font-size="12" font-weight="bold" font-family="Arial" '
                       f'fill="#1c2c3f">{escape(candidate["place_name"])}</text>')
    bar_mi = 1 if reach < 4 else 2
    bx, by = 18, height - 22
    out.append(f'<line x1="{bx}" y1="{by}" x2="{bx + bar_mi * scale:.1f}" y2="{by}" stroke="#1c2c3f" stroke-width="3"/>'
               f'<text x="{bx}" y="{by - 6}" font-size="11" font-family="Arial" fill="#1c2c3f">{bar_mi} mi</text>'
               f'<text x="{width - 24}" y="26" font-size="13" font-weight="bold" font-family="Arial" fill="#1c2c3f">N</text>'
               f'<path d="M{width - 20},32 L{width - 14},46 L{width - 26},46 Z" fill="#1c2c3f"/></svg>')
    return "".join(out)


def render(m) -> dict:
    root = m.get_root()
    root.render()   # fills header/html/script before they're pulled apart
    return {"map_head": root.header.render(), "map_body": root.html.render(),
            "map_script": root.script.render(), "map_name": m.get_name()}
