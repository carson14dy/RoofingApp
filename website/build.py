"""Build the Montana Hail Watch website into a folder of static files.

    python -m website.build --out _site                 # live data (needs internet)
    python -m website.build --out _site --sample        # labelled sample data, no network
    python -m website.build --out _site --require-live  # fail if any source failed (preview checks)
    python -m website.build --out _site --storm-layers  # also NOAA radar echo tops (text) and the GOES satellite picture
    python -m website.build --out _site --hail-history  # also the five-year hail history (website/hail.py)
    python -m website.build --out _site --sample --hail-history --hail-store store.tar.gz  # a local store, not the download

GitHub Actions runs the live build every 10 minutes and publishes the folder with GitHub Pages
(.github/workflows/website.yml). Every page says when its data was fetched; nothing on a page is
newer than that time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import hail as hs
from . import sources as src

HERE = Path(__file__).resolve().parent
UTC = timezone.utc
MT = ZoneInfo("America/Denver")
TOWNS = json.loads((HERE / "towns.json").read_text(encoding="utf-8"))
OFFICES = [("Billings", "https://www.weather.gov/byz/"), ("Glasgow", "https://www.weather.gov/ggw/"),
           ("Great Falls", "https://www.weather.gov/tfx/"), ("Missoula", "https://www.weather.gov/mso/")]


# ---------------------------------------------------------------- gathering

class Collector:
    """Fetches every source once and records, per source, what happened and when."""

    def __init__(self, fetch: src.Fetcher, now: datetime, previous: dict | None = None):
        self.f, self.now, self.prev = fetch, now, previous or {}
        self.status: dict[str, dict] = {}
        self.replaced: set[str] = set()        # alert ids a newer message in this build's responses replaced

    def note(self, key, label, ok, detail="", when=None):
        self.status[key] = {"label": label, "ok": ok, "detail": detail, "when": src._iso(when or self.now)}

    def alerts(self):
        doc, err = self.f.json(f"{src.NWS}/alerts/active", {"area": "MT"})
        try:
            if err:
                raise ValueError(err)
            items = src.parse_alerts(doc)
            self.replaced |= src.alert_references(doc)
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
               "tz": "America/Denver", "office": None, "near": "", "grid_elev_ft": None}
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
                out["grid_elev_ft"] = src.grid_elevation_ft(doc)
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
            self.replaced |= src.alert_references(doc)
        except ValueError as e:
            out["errors"].append(f"Couldn't check official alerts for {t['name']} ({e}).")
        for h in out["hours"]:
            h["flags"] = src.flags_for(h)
        out["summary"] = src.summarize(out["hours"], self.now)
        out["obs"] = self.observations(t, point)
        return out

    def observations(self, t, point) -> dict:
        """The latest reading at the town's nearest NWS stations (D29). The station list comes from
        the point lookup and the last good list is reused if it fails, as the point is; each station
        that doesn't answer says so on the town page. Nothing is invented for a missing reading."""
        res = {"stations": [], "error": None, "now": None}
        stations, url = None, (point or {}).get("stations")
        if url:
            doc, err = self.f.json(url)
            try:
                if err:
                    raise ValueError(err)
                stations = src.parse_stations(doc, t["lat"], t["lon"])
            except ValueError as e:
                stations = (self.prev.get("stations") or {}).get(t["slug"])
                if not stations:
                    res["error"] = f"Couldn't look up the nearest weather stations ({e})."
        else:
            stations = (self.prev.get("stations") or {}).get(t["slug"])
            if not stations:
                res["error"] = ("Couldn't look up the nearest weather stations (the NWS grid lookup "
                                + ("had no station list)." if point else "didn't load)."))
        for s in stations or []:
            doc, err = self.f.json(f"{src.NWS}/stations/{s['id']}/observations/latest")
            try:
                if err:
                    raise ValueError(err)
                res["stations"].append({**s, "obs": src.parse_observation(doc, self.now), "error": None})
            except ValueError as e:
                res["stations"].append({**s, "obs": None, "error": str(e)})
        res["now"] = src.reading_now(res["stations"])
        return res

    def towns(self):
        towns = [self.town(t) for t in TOWNS]
        good = sum(1 for t in towns if t["hours"])
        self.note("forecasts", "NWS forecasts", good == len(towns), f"{good} of {len(towns)} towns")
        read = sum(1 for t in towns if t["obs"]["now"])
        fresh = sum(1 for t in towns if t["obs"]["now"] and t["obs"]["now"]["obs"]["current"])
        self.note("observations", "NWS station readings", read == len(towns),
                  f"{read} of {len(towns)} towns, {fresh} with a reading under {src.FRESH_MINUTES} minutes old")
        return towns

    def add_town_alerts(self, alerts: dict, towns: list) -> None:
        """Put every alert a town's point check found into the statewide list, so the Now page, the
        map (outlines, town sheets, List) and state.json name the same alerts the towns point to. The
        statewide request goes first, so a warning issued while the towns are checked is only in
        their answers; and when it failed, the list is the last verified one. A listed alert that a
        newer message replaced is dropped, as parse_alerts does within one answer, unless a town's
        check still returned it."""
        have = {a["id"] for a in alerts["items"]}
        found = [a for t in towns for a in t["alerts"] or []]
        added = []
        for a in found:
            if a["id"] not in have:
                have.add(a["id"])
                added.append(a)
        pointed = {a["id"] for a in found}
        items = [a for a in alerts["items"] + added if a["id"] not in self.replaced or a["id"] in pointed]
        alerts["items"] = sorted(items, key=src.alert_order)
        alerts["from_towns"] = len(added)
        if alerts["ok"]:
            self.note("alerts", "NWS alerts", True, f"{len(items)} active"
                      + (f" ({len(added)} found only by the town checks)" if added else ""))

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

    def gridded(self, out_dir: Path, sample: bool) -> dict:
        """Radar frames (NOAA MRMS) and model forecast frames (NOAA HRRR) for the map page."""
        from . import gridded
        fetch = getattr(self.f, "binary", None)
        get = fetch if fetch else (lambda url, headers=None: (None, "no downloader"))
        layers, status = gridded.build_gridded(out_dir, get, self.now, sample=sample)
        for key, label in (("radar", "NOAA radar"), ("forecast", "HRRR forecast")):
            st = status.get(key) or {}
            self.note(key, st.get("label") or label, bool(st.get("ok")), st.get("detail") or "not built")
        return layers

    def storm(self, towns: list, sample: bool) -> dict:
        """NOAA radar echo tops for each town (website/storm.py; --storm-layers only). One status line, like
        the others. The ground height is the NWS grid square's elevation (grid_elev_ft), in metres."""
        from . import storm as storm_mod
        fetch = getattr(self.f, "binary", None)
        get = fetch if fetch else (lambda url, headers=None: (None, "no downloader"))
        inputs = [{"slug": t["slug"], "name": t["name"], "lat": t["lat"], "lon": t["lon"],
                   "ground_m": None if t["grid_elev_ft"] is None else t["grid_elev_ft"] / src.M_TO_FT}
                  for t in towns]
        results, st = storm_mod.collect(get, self.now, inputs, sample=sample)
        self.note("storm", storm_mod.LABEL, st["ok"], st["detail"])
        return results

    def satellite(self, out_dir: Path, sample: bool) -> dict:
        """The GOES band 13 satellite picture for the map (website/satellite.py; --storm-layers only): the
        layer for data/map.json, with one frame or none. One status line, like the others."""
        from . import satellite as sat
        fetch = getattr(self.f, "binary", None)
        get = fetch if fetch else (lambda url, headers=None: (None, "no downloader"))
        layer, st = sat.build_satellite(out_dir, get, self.now, sample=sample)
        self.note("satellite", sat.LABEL, bool(st.get("ok")), st.get("detail") or "not built")
        return layer

    def hail(self, out_dir: Path, sample: bool, store: str | None, towns: list) -> dict:
        """The five-year hail history (website/hail.py; --hail-history only). The store's hail/ files are copied
        into the site, and each town gets its words (town["hail"]). One status line, like the others: a store
        that doesn't load is a failed source, the pages say so in words, and the build goes on (--require-live
        then fails). Returns the map.json block. The copy is made only after the store's manifest checks out."""
        sampled = sample and store is None          # the SAMPLE fixture only; a --hail-store file is real data
        through = None                              # the newest grid day the store holds (the climate block)
        try:
            index = hail_store(out_dir, store, sample, self.f)
            through = (index.get("climate") or {}).get("through")
            tiles = hail_tiles(index, out_dir)
            cells = [hs.cell_events(out_dir, t["lat"], t["lon"]) for t in towns]
            words = [hs.describe(index, events, self.now, sample=sampled) for events in cells]
            block = hs.map_data(index, sample=sampled)
            block.pop("tiles", None)                # D40: no block lists every tile; the split map says which tiles exist
            block["tile_split"] = tile_split(tiles) # the browser's outside test: a tile with no run has no Montana cell
            joins_block, joins_views = hail_joins(out_dir, index, towns, self.now, sampled)
            block["joins"] = joins_block            # the joined records behind the sheet (B2)
            block.update(b5_map_blocks(index))      # the five-season history's blocks (B5), beside the joins
            summaries = [town_summary(out_dir, t, self.now) for t in towns]
            # the counts the build log shows are the store's own, when its index holds them (a store without them builds too)
            counts = (f"{index['events']:,} events in {index['shards']} shard files, " if "events" in index and "shards" in index
                      else "")
            days = (f"{index['days_present']} of {index['days_expected']} days, " if "days_present" in index
                    and "days_expected" in index else "")
            detail = f"{counts}{days}as of {index['as_of']}; joined records {joins_block['state']}"
            self.note("hail_history", HAIL_LABEL, True, ("SAMPLE store: " if sampled else "") + detail)
        except (hs.HailStoreError, OSError, ValueError, KeyError, TypeError) as e:
            problem = str(e) if isinstance(e, hs.HailStoreError) else f"the history files couldn't be read ({type(e).__name__})"
            self.note("hail_history", HAIL_LABEL, False, problem)
            words = [hs.describe_unavailable(problem) for _ in towns]
            block = hs.map_data_unavailable(problem)
            block.pop("tiles", None)
            block["tile_split"] = {}                # no store, so no tile is known: the map says unavailable, not outside
            from . import joins as jn
            block["joins"] = join_block_unavailable(jn, problem)
            joins_views = [join_view_unavailable(jn) for _ in towns]
            block.update(b5_map_blocks(None))       # every B5 block says unavailable, with the reason
            summaries = [summary_unavailable(problem, t) for t in towns]
        for t, w, jv, s in zip(towns, words, joins_views, summaries):
            t["hail"] = {**w, "joins": jv, "summary": s, "view": history_view(s, jv, w, t, self.now, through)}
        block["words"].update(HAIL_SITE_WORDS)
        block["stale_days"] = HAIL_STALE_DAYS
        block["at_zoom"] = HAIL_AT_ZOOM
        block["tenths_per_mm"] = HAIL_TENTHS_PER_MM
        return block


# ---------------------------------------------------------------- map page data

MAP_VIEW = {"bounds": [[44.35, -116.06], [49.01, -104.03]], "min_zoom": 5, "max_zoom": 11}

# The imagery base map (D32): USGS The National Map's aerial imagery with roads and names, as 256 px tiles.
# The browser asks for tiles only while Imagery is on (map.js setBase): after a switch, or when the address
# starts on it. The full address is set in one place; the host name also appears in the feed text (sources.py)
# and in the browser check (tools/smoke_map.py). The two lines are the words the credit row shows (map.js):
# the credit with the privacy words while Imagery is on, and the line that replaces it while tiles fail.
IMAGERY = {
    "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}",
    "max_zoom": 16, "host": "basemap.nationalmap.gov",
    "credit_line": "Imagery: USDA, USGS, The National Map. Your IP address and the map area you view go to USGS.",
    "failed_line": "Imagery didn't load from USGS. Outlines and towns are still shown."}


def map_data(now: datetime, sample: bool, layers: dict, towns: list, alerts: dict, reports: dict,
             status: dict, hail: dict | None = None) -> dict:
    """Everything the map page draws, as one JSON document (data/map.json). The contract is in
    docs/DESIGN.md ("Interactive map"); website/static/map/map.js reads it. The "hail" block is there only in a
    --hail-history build (Collector.hail): no key otherwise."""
    from . import gridded
    radar_times = [f["time"] for f in (layers.get("precip") or {}).get("frames", []) if f.get("kind") == "radar"]
    first, last = now - timedelta(hours=1, minutes=10), now + timedelta(hours=14)
    out_towns = []
    for t in towns:
        hours = [{"time": src._iso(h["start"]), "temp_f": _round(h.get("temp_f")),
                  "wind_mph": _round(h.get("wind_mph")), "wind_dir": h.get("wind_dir") or "",
                  "gust_mph": _round(h.get("gust_mph")), "precip": _round(h.get("precip")),
                  "sky": h.get("sky") or "", "flags": h.get("flags") or []}
                 for h in t["hours"] if first <= h["start"] <= last]
        out_towns.append({"slug": t["slug"], "name": t["name"], "lat": t["lat"], "lon": t["lon"],
                          "label": t.get("label", "right"), "minor": bool(t.get("minor")),
                          # the zoom a town shows from (towns.json; tools/build_basemap.py town_min_zoom: same rule)
                          "min_zoom": t.get("min_zoom", 7 if t.get("minor") else 5),
                          "url": f"town/{t['slug']}.html", "office": t.get("office"), "hours": hours,
                          "alert_ids": None if t["alerts"] is None else [a["id"] for a in t["alerts"]],
                          **({"storm": t["storm"]} if "storm" in t else {})})
    (s_, w_), (n_, e_) = gridded.IMAGE_BOUNDS
    return {
        "version": 1, "built": src._iso(now), "sample": sample, "tz": "America/Denver",
        "image_bounds": [[s_, w_], [n_, e_]], "view": MAP_VIEW, "imagery": IMAGERY,
        "now": radar_times[-1] if radar_times else src._iso(now),
        "layers": layers, "status": status, "towns": out_towns,
        "alerts": {"ok": alerts["ok"], "checked": alerts["checked"], "last_known": alerts.get("last_known"),
                   "items": alerts["items"]},
        "reports": reports["items"],
        **({"hail": hail} if hail is not None else {}),
    }


def _round(v):
    return None if v is None else round(v)


# ---------------------------------------------------------------- the map card on the Now page

def map_card(layers: dict, alerts: dict, towns: list, status: dict, now: datetime) -> dict:
    """The words with the map card on the Now page (index.html): the frame's title, what the card
    shows, what this update is missing, and what the full map can play. They follow the data, so a
    model forecast is never called the radar estimate and outlines or town numbers that didn't load
    are never described as shown (AGENTS.md rule 5). The card opens where map.js opens it (setLayer,
    buildTimeline): the precipitation layer's 12h timeline, or its only timeline with frames, at its
    now_index. Stale radar keeps its frames, so the picture is read from the frames, not the status."""
    precip = layers.get("precip") or {}
    frames, modes = precip.get("frames") or [], precip.get("modes") or {}
    mode = "12h" if modes.get("12h") else next((m for m, idx in modes.items() if idx), None)
    frame = None
    if mode:
        idx = modes[mode]
        frame = frames[idx[min(max((precip.get("now_index") or {}).get(mode) or 0, 0), len(idx) - 1)]]
    shown, short, missing = [], [], []
    sample = frame is not None and str(frame.get("source") or "").startswith("SAMPLE")
    if frame is None:
        missing.append("the radar and model pictures")
    else:
        at = _clock(frame["time"], now)
        if frame["kind"] == "radar":
            stale = not sample and not (status.get("radar") or {}).get("ok")
            shown.append("the latest sample radar picture (invented, not NOAA radar)" if sample else
                         "the latest NOAA radar estimate" + (f" (from {at}, older than usual)" if stale else ""))
            short.append("sample radar" if sample else "latest radar")
        else:
            model = "sample model forecast" if sample else "HRRR model forecast"
            shown.append(f"the {model} for {at}" + (" (invented, not the HRRR model)" if sample else ""))
            short.append(f"{model} for {at}")
            missing.append("NOAA radar")
    if alerts.get("ok"):
        shown.append("NWS warning outlines")
        short.append("warning outlines")
    elif alerts.get("items"):               # the last verified list (and what the town checks found)
        shown.append("the outlines of the NWS alerts listed on this page")
        short.append("warning outlines")
    else:
        missing.append("NWS warning outlines")
    have = sum(1 for t in towns if t.get("hours"))
    if have:
        shown.append("the NWS forecast temperature for each town"
                     + ("" if have == len(towns) else " whose forecast loaded"))
        short.append("town temperatures")
    else:
        missing.append("town temperatures")
    kinds = {f["kind"] for f in frames} if len(frames) > 1 else set()
    plays = [w for k, w in (("radar", "the past hour of sample radar" if sample else "the past hour of radar"),
                            ("forecast", "the sample model forecast" if sample else "the HRRR model forecast"))
             if k in kinds]
    switch = [w for k, w in (("temp", "temperature"), ("wind", "wind gusts")) if (layers.get(k) or {}).get("frames")]
    if plays:
        then = "to play " + _and(plays) + (", or switch to " + _and(switch) if switch else "")
    else:
        then = "to switch to " + _and(switch) if switch else "for the List of alerts and towns"
    words = _and(shown)
    return {"title": "Montana map: " + (_and(short) if short else "nothing loaded in this update"),
            "shown": words[:1].upper() + words[1:] + "." if words else "",
            "missing": f"Missing from this update: {_and(missing)}. This is not an all-clear." if missing else "",
            "then": then}


def _and(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _clock(value, now: datetime) -> str:
    """'2 am' on the hour, else '1:40 am', Montana time, as map.js clock() writes a frame's time (with
    the zone when it differs from the build time's: the night the clocks fall back has two 1 ams)."""
    dt = src.parse_iso(value).astimezone(MT)
    text = fmt_time(dt, "%-I %p" if dt.minute == 0 else "%-I:%M %p")
    return text + ("" if dt.tzname() == now.astimezone(MT).tzname() else f" {dt.tzname()}")


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
    e.filters["ago"] = src.age_words
    e.filters["feet"] = lambda v: "—" if v is None else f"{round(v):,}"
    return e


# ---------------------------------------------------------------- build

# Files the pages load with ?v=<content hash>: a file keeps its address until its bytes change, so
# browsers and GitHub Pages reuse the unchanged ones across the 10-minute rebuilds (map.js, map.css,
# the 377 KB basemap and style.css change only with the code). data/map.json and the map card's
# address change every build, so they keep the build minute.
VERSIONED = ("style.css", "map/map.js", "map/map.css", "map/basemap.json")


STORM_JS = "map/storm.js"   # places the storm text in the Map's List and town sheets; --storm-layers only
# Feeds listed on the About page only in a --storm-layers build (their words and layers ship with the flag)
STORM_CONTRACTS = ("storm_levels", "satellite")

# The five-year hail history (--hail-history only; website/hail.py holds the words and the store format)
HAIL_LABEL = "Hail history (radar estimates)"        # the status line's name
# the joined records (B2, website/joins.py) are on the About page only in a --hail-history build, with the store
JOIN_CONTRACTS = ("lsr", "ncei_storm_events", "swdi_nx3hail", "nws_warnings_polygons", "nws_zone_products",
                  "asos_daily_gusts")
# the B5 feeds (sources.py rows, B5 brief): on the About page only in a --hail-history build
B5_CONTRACTS = ("nclimgrid_daily", "nohrsc_season_snowfall", "ghcn_daily", "iem_watchwarn", "iem_ugcs", "iem_lsr",
                "nwps_gauges", "usgs_water_api", "census_counties", "roof_references")   # the order of sources.py's rows
HAIL_CONTRACTS = ("hail_history",) + JOIN_CONTRACTS + B5_CONTRACTS  # on the About page only in a --hail-history build
# Words map.js fills that hail.WORDS doesn't hold: a shard that didn't load (the unavailable line's problem)
HAIL_SITE_WORDS = {"fetch_failed": "the history for this spot didn't load in this update"}
HAIL_STALE_DAYS = hs.STALE_DAYS    # map.js: an as_of older than this (in days) shows the stale line
HAIL_AT_ZOOM = 9                   # map.js: ?at=lat,lon opens at this zoom, or the current one if it is higher
HAIL_TENTHS_PER_MM = 10            # map.js: the store's tenths of a millimetre, for the millimetre text


def asset_versions(static: Path, names=VERSIONED) -> dict:
    """Short content hash per versioned static file, for the pages' ?v= query."""
    return {name: hashlib.sha256((static / name).read_bytes()).hexdigest()[:12] for name in names}


def _unbuilt_static(storm_layers: bool):
    """shutil.copytree's ignore: the storm script is copied only in a --storm-layers build, so the default
    build's static files are the same as before the storm text existed."""
    def ignore(directory, names):
        if not storm_layers and Path(directory) == HERE / "static" / "map":
            return [n for n in names if n == "storm.js"]
        return []
    return ignore


def hail_store(out: Path, store: str | None, sample: bool, fetch) -> dict:
    """Copy the hail store's hail/ files into out/hail/ and return the store's index. Where the store comes from:
    --hail-store (a folder or a hail-store.tar.gz), else the SAMPLE fixture with --sample, else the release
    download (hail.fetch_store through the build's fetcher). Raises hail.HailStoreError with the problem in plain
    words. The copy is made only after the manifest has checked out."""
    if store is not None:
        path = Path(store)
        if not path.exists():
            raise hs.HailStoreError(f"the history store file {path.name} is missing")
        with tempfile.TemporaryDirectory(prefix="hail-store-") as tmp:
            root = hs.load_store(path, tmp)          # a folder is checked in place; an archive is unpacked into tmp
            return _copy_hail(root, out, hs.load_index(root))
    if sample:
        index = hs.load_index(hs.FIXTURE_DIR)
        hs.check_manifest(hs.FIXTURE_DIR)
        return _copy_hail(hs.FIXTURE_DIR, out, index)
    with tempfile.TemporaryDirectory(prefix="hail-store-") as tmp:
        index = hs.fetch_store(fetch.binary, tmp, hs.STORE_URL)
        return _copy_hail(Path(tmp), out, index)


# The store's folders the site copies (B2 and B5). hail/j/ holds the joined records and hail/j/e/ the per-tile event files
# (D30); hail/n/ (the snow analysis) is copied only when the index's snow block says it is shown (D7, D23).
HAIL_FILES = ("index.json", "manifest.json")
HAIL_FOLDERS = ("t", "j", "z", "s")              # B2: shards, joined records (with j/e), zone and station files
HAIL_FOLDERS_B5 = ("c", "sd", "g", "k")          # B5: grid tiles, station files, gauges, county files


def snow_shown(index: dict) -> bool:
    """True when the store's snow block says the analysis is shown (its unit check passed, D7)."""
    block = index.get("snow") if isinstance(index, dict) else None
    return isinstance(block, dict) and block.get("shown") is True


def _copy_hail(root: Path, out: Path, index: dict) -> dict:
    """Copy the store's hail/ files into the site as out/hail/: the B2 folders, the B5 folders (c, sd, g, k; j/e comes with
    j), and hail/n only when the snow block says it is shown. The manifest is checked first, so every copied file is one the
    manifest lists and its bytes match (hail.check_manifest). A store without a B5 folder (a B2-only store) copies what it
    has, and the pages say which part is unavailable."""
    hs.check_manifest(root)
    (out / "hail").mkdir(parents=True)
    for name in HAIL_FILES:
        shutil.copy2(root / "hail" / name, out / "hail" / name)
    folders = HAIL_FOLDERS + HAIL_FOLDERS_B5 + (("n",) if snow_shown(index) else ())
    for name in folders:
        if (root / "hail" / name).is_dir():
            shutil.copytree(root / "hail" / name, out / "hail" / name)
    return index


# The joined records (B2): website/joins.py writes them and holds their rules and words. These are the site's own
# words and the few values the browser needs that the module does not export (map.json hail.joins).
JOIN_SITE_WORDS = {
    "show_all": "Show all {n} rows",
    "unknown_date": "an unknown date",       # a missing NCEI lag reads so (joins._records_lead writes the same words)
    "reason_no_store_joins": "the joined records are not in this history store",
}
JOIN_SHOW_FIRST = 10          # rows a section shows before "show all" (the sheet and the town tables)
JOIN_HERE_MILES = 0.05        # nearer than this to a report, no bearing is shown (joins._place_bits)
JOIN_SPC_HOURS = 12           # an SPC report day starts at 12:00 UTC (joins.spc_day)
JOIN_HUNDREDTHS = 100         # detection sizes are stored in hundredths of an inch (joins._joins_for_tile)
JOIN_HAIL_UNIT = "in"         # the unit a hail magnitude is written in (joins.LSR_UNITS)
JOIN_UNIT_WORDS = {"mph": "magnitude_mph", "kt": "magnitude_kt"}   # unit -> the words key that shows it
JOIN_HEADS = {"reports": "Report", "records": "Record", "detections": "Detection", "warnings": "Warning",
              "zones": "Zone product", "stations": "Station"}     # the town tables' one column: the row labels of D3


# the store's counts that the sheet's lines read (joins.describe_joins): the browser takes the same values from the block
JOIN_FIRE_SHARD = "hail/z/fire-{zone}.json"   # a fire weather zone's file (joins writes it under fire-<zone>)
JOIN_COUNTS = ("warnings_no_outline", "ncei_zone_rows_unmatched", "zone_products_unplaced")


def join_block(jn, index: dict, sample: bool) -> dict:
    """map.json["hail"]["joins"] for a store with the records: joins.map_data_joins, plus the values the browser needs
    beside it (the earth radius the module writes its distances on, the partial periods, the zone names, the counts
    the lines say, and whether the fire weather zones loaded)."""
    block = jn.map_data_joins(index, sample=sample)
    store = index[jn.INDEX_KEY]
    block.update({"earth_radius_km": jn.EARTH_KM, "here_miles": JOIN_HERE_MILES, "spc_hours": JOIN_SPC_HOURS,
                  "hundredths_per_inch": JOIN_HUNDREDTHS, "hail_unit": JOIN_HAIL_UNIT,
                  "unit_words": dict(JOIN_UNIT_WORDS), "show_first": JOIN_SHOW_FIRST,
                  "partial": dict(store.get("partial", {})), "zone_names": dict(store.get("zone_names", {})),
                  "counts": {key: int(store.get(key, 0)) for key in JOIN_COUNTS},
                  "fire_state": store.get("fire_zones", {}).get("state", "unavailable")})
    block["words"] = {**block["words"], **JOIN_SITE_WORDS}
    block["shards"] = {**block["shards"], "fire": JOIN_FIRE_SHARD}
    return block


def join_block_unavailable(jn, problem: str) -> dict:
    """map.json["hail"]["joins"] when the store holds no records: every part says why, and the browser fetches nothing."""
    parts = {part: "unavailable" for part in jn.PARTS}
    fake = {"as_of": "", "window": ["", ""], jn.INDEX_KEY: {
        "state": "unavailable", "parts": parts, "reasons": {part: problem for part in jn.PARTS}, "lags": {},
        "partial": {}, "zone_names": {}, "types": {}, "cover": "", "shapes": {}, "montana_time": []}}
    block = join_block(jn, fake, False)
    block.update({"state": "unavailable", "problem": problem})
    return block


def join_heading(jn, part: str) -> str:
    if part == "zones":        # the zone is not known here, so the heading names no zone (the module's words)
        return jn.WORDS_JOINS["zones_heading_no_zone"]
    return jn.WORDS_JOINS[f"{part}_heading"]


def join_view(section: dict) -> dict:
    """One section of a town's hail history, as the town page shows it (joins.describe_joins)."""
    rows = [{"text": r["text"], "note": r.get("remark") or ""} for r in section["rows"]]
    return {"key": section["id"], "head": JOIN_HEADS[section["id"]], "heading": section["heading"],
            "lead": section["lead"] or "", "fire_lead": section.get("fire_lead") or "", "rows": rows,
            "what": " ".join(x for x in (section["what"], section["source"]) if x),
            "note": " ".join(section["lines"]), "unavailable": _clear_words(section["unavailable"] or ""),
            "show_all": JOIN_SITE_WORDS["show_all"].format(n=len(rows))}


def join_view_unavailable(jn) -> dict:
    """A town's six sections when their words cannot be written from the records: each part says why."""
    w = jn.WORDS_JOINS
    sections = []
    for part in jn.PARTS:
        sections.append({
            "key": part, "head": JOIN_HEADS[part], "heading": join_heading(jn, part), "lead": "", "fire_lead": "", "rows": [],
            "what": " ".join(x for x in (w[f"{part}_what"], w[f"source_{part}"]) if x), "note": "",
            "unavailable": _clear_words(jn._unavailable_text(part, None)), "show_all": ""})
    return {"show_first": JOIN_SHOW_FIRST, "times": w["times_note"], "sections": sections}


def hail_joins(out: Path, index: dict, towns: list, now: datetime, sample: bool) -> tuple[dict, list]:
    """The joined records (B2): the map block (map.json hail.joins) and each town's six sections. A store without the
    records, or a tile whose record file is missing or unreadable, gives the unavailable words for the part, never an
    empty section. Returns (block, one view per town)."""
    from . import joins as jn
    if not isinstance(index.get(jn.INDEX_KEY), dict):
        problem = JOIN_SITE_WORDS["reason_no_store_joins"]
        return join_block_unavailable(jn, problem), [join_view_unavailable(jn) for _ in towns]
    block = join_block(jn, index, sample)
    events = jn._read_events(out)             # the events table, read once for every town
    views = []
    for t in towns:
        row, col = hs.cell_for(t["lat"], t["lon"])
        name = hs.tile_name(row // hs.TILE, col // hs.TILE)
        try:
            tile = json.loads((out / "hail" / "j" / f"{name}.json").read_text(encoding="utf-8"))
            words = jn.describe_joins(index, tile, row, col, now, sample=sample, store_dir=out, events=events)
            views.append({"show_first": JOIN_SHOW_FIRST, "times": words["times_note"],
                          "sections": [join_view(s) for s in words["sections"]]})
        except OSError:
            views.append(join_view_unavailable(jn))
        except (ValueError, KeyError, TypeError, IndexError, jn.JoinsError):
            views.append(join_view_unavailable(jn))
    return block, views


TILE_NAME = re.compile(r"r\d{4}_c\d{4}")


def hail_tiles(index: dict, out: Path) -> list[str]:
    """The tile names the store holds (hail/index.json "tiles"), sorted and unique. The browser's outside test reads
    this list (map.json hail.tiles), so every name must have its shard file under out/hail/t/: a name without one is
    a broken store, a failed source, never a tile with no Montana cell. Raises hail.HailStoreError."""
    tiles = index.get("tiles")
    if not isinstance(tiles, list) or not all(isinstance(t, str) and TILE_NAME.fullmatch(t) for t in tiles):
        raise hs.HailStoreError("the history index has no list of tile names")
    if tiles != sorted(set(tiles)):
        raise hs.HailStoreError("the history tile names are not sorted and unique")
    for name in tiles:
        if not (out / "hail" / "t" / f"{name}.json").is_file():
            raise hs.HailStoreError(f"the history has no shard file for tile {name}")
    return tiles


# ---------------------------------------------------------------- the five-season history (B5; --hail-history only)
# summary.py holds the table, the roof lines and their sentences; the functions here join them with the joined records
# (joins.describe_joins), the radar words (hail.describe) and the river gauge into the town page's view, and build the
# map.json blocks the browser fills. Every word the page shows is written in Python (AGENTS rule 4).

HISTORY_SHOW_FIRST = 10     # rows a section shows before its "show all" (the joined tables' count)
HISTORY_WORDS = {
    "unavailable": "Weather history could not be loaded in this update: {problem}. That is not the same as no weather history. This is not an all-clear.",
    "outside": "This spot is outside Montana, so the weather history does not cover it.",
    "no_reason": "No reason was recorded for this value in this update.",
    "show_all": "Show all {n} rows",
    "town_title": "Five years of weather at {town}",
    "cell": ("The table is for the grid cell at the town's centre, about 0.7 miles north to south and 0.5 miles east to west. "
             "The grid and radar rows are for that cell; each station row names its station and its distance from the town."),
    "footnotes": "Data unavailable, with the reason",
    "table_caption": "Five seasons, July to June, at {town}: each row names its kind of record and its unit.",
    "gauge_label": "River gauge",
    "reference_label": "Reference",
    "times": "Times are Montana time, with the zone abbreviation (MDT or MST).",
}
HISTORY_SECTIONS = ("hail", "wind", "storms", "temperature", "rain", "snow", "flooding", "ice", "heat", "roof", "made")
# the kind label a joins row starts with (B2 D3); the rest of the row is the joins' own words
_KIND_LABEL = re.compile(r"^(Report|Record|Detection|Warning|Watch|Advisory|Zone product|County product|Station): (.*)$", re.S)
# the sections a joins row can go to, by its type or product words (the first rule that matches decides; a row no rule
# matches is a storm or warning row, so no joined row is dropped)
_SECTION_RULES = (
    ("ice", re.compile(r"\b(freezing|sleet|ice|winter|blizzard|wind chill|extreme cold|frost|freeze|cold)\b", re.I)),
    ("heat", re.compile(r"\bheat\b", re.I)),
    ("flooding", re.compile(r"\b(flood|flash|debris)\b", re.I)),
    ("snow", re.compile(r"\bsnow", re.I)),
    ("hail", re.compile(r"\bhail\b", re.I)),
    ("rain", re.compile(r"\b(rain|drought)\b", re.I)),
    ("wind", re.compile(r"\b(winds?|wnd|gusts?|dust)\b", re.I)),
)


def _split_kind(text: str) -> tuple[str, str]:
    """A joined row's kind label and its words: "Report: ..." gives ("Report", "...")."""
    m = _KIND_LABEL.match(text)
    return (m.group(1), m.group(2)) if m else ("", text)


def _section_of(label: str, body: str) -> str:
    """The section a joined row belongs to, from its kind and its type or product words (B5): a station row is wind, a
    detection is hail, a warning, watch, advisory or zone row takes its product's name, and a report or record takes its type word."""
    if label == "Station":
        return "wind"
    if label == "Detection":
        return "hail"
    if label in ("Warning", "Watch", "Advisory"):
        # the product's name only: a B5 row reads "...: flood watch, TFX, covered this cell or part of it; tags: ...", so
        # the tags (hail, wind) never move a warning, watch or advisory to another section (D41)
        m = re.search(r"in effect: ([^,;]+)", body) or re.search(r": ([^:,;]+), [A-Z0-9]{2,4}, covered", body)
        words = m.group(1) if m else body
    elif label in ("Zone product", "County product"):
        words = re.split(r", fire weather zone|:", body, maxsplit=1)[0]
    else:
        m = re.search(r"\d{1,2}:\d{2} ?[ap]m(?: [A-Z]{2,4})?: (.*)$", body, re.I)     # "5:16 pm MDT: tstm wnd gst, ..."
        words = re.split(r", | \(", m.group(1) if m else body, maxsplit=1)[0]
    for key, rule in _SECTION_RULES:
        if rule.search(words):
            return key
    return "storms"


def snow_map_block(index: dict | None) -> dict:
    """map.json["hail"]["snow"]: the snow analysis's state, its unit check and its words (D7, D23). The grid files
    (hail/n/) are in the site only when the check passes; the browser reads this block for the words."""
    from . import snowgrid
    block = index.get("snow") if isinstance(index, dict) else None
    block = block if isinstance(block, dict) else None
    shown = snow_shown(index or {})
    return {"state": block.get("state", "unavailable") if block else "unavailable", "shown": shown,
            "problem": _clear_words((block or {}).get("problem") or (None if block else "the snow analysis is not in this store")),
            "water_years": list((block or {}).get("water_years") or []), "tile": "hail/n/{tile}.json",
            "terms": snowgrid.TERMS_NOTE, "words": dict(snowgrid.WORDS), "check": (block or {}).get("check") if shown else None}


def stations_map_block(index: dict | None) -> dict:
    """map.json["hail"]["stations"]: the station rule's constants, the counts and the words (D5, D18). The per-station
    files are hail/sd/; the rule's results for each town stay in the index."""
    from . import stations
    block = index.get("stations") if isinstance(index, dict) else None
    block = block if isinstance(block, dict) else None
    return {"state": (block or {}).get("state", "unavailable"),
            "problem": _clear_words((block or {}).get("problem") or (None if block else "the station files are not in this store")),
            "as_of": (block or {}).get("as_of"), "rule": (block or {}).get("rule"), "counts": (block or {}).get("counts"),
            "radius_miles": stations.RADIUS_MILES, "fresh_days": stations.FRESH_DAYS, "cover_min": stations.COVER_MIN,
            "season_min": stations.SEASON_MIN, "cover_days": stations.COVER_DAYS, "tile": "hail/sd/{station}.json",
            "words": dict(stations.WORDS)}


def gauges_map_block(index: dict | None) -> dict:
    """map.json["hail"]["gauges"]: the river gauge rule, its counts and the words (D6, D21). The gauge files are hail/g/."""
    from . import gauges
    block = index.get("gauges") if isinstance(index, dict) else None
    block = block if isinstance(block, dict) else None
    return {"state": (block or {}).get("state", "unavailable"),
            "problem": _clear_words((block or {}).get("problem") or (None if block else "the river gauge files are not in this store")),
            "rule": (block or {}).get("rule"), "counts": (block or {}).get("counts"),
            "radius_miles": gauges.RADIUS_MILES, "tile": "hail/g/{usgs}.json", "words": dict(gauges.WORDS)}


def county_map_block(index: dict | None) -> dict:
    """map.json["hail"]["county"]: the county names and the county words (B5 source 4, D11); the county files are hail/k/."""
    from . import joins as jn
    joins_block = index.get(jn.INDEX_KEY) if isinstance(index, dict) else None
    counties = (joins_block or {}).get("counties") if isinstance(joins_block, dict) else None
    counties = counties if isinstance(counties, dict) else {}
    return {"state": counties.get("state", "unavailable"),
            "problem": _clear_words(counties.get("reason") or (None if counties else "the county files are not in this store")),
            "count": counties.get("count"), "names": dict(counties.get("names") or {}), "tile": "hail/k/{county}.json",
            "words": {k: v for k, v in jn.WORDS_JOINS.items() if k.startswith("county_")}}


def b5_map_blocks(index: dict | None) -> dict:
    """The map.json["hail"] blocks of the five-season history: climate (climate.map_data_climate), summary
    (summary.map_data_summary) and the snow, stations, gauges and county blocks. None gives every block unavailable.
    D40: the climate block lists no tile names; it carries the URL pattern and the compact split map of its tiles, and
    the stations, gauges and county blocks carry their URL patterns only."""
    from . import climate, summary
    climate_block = climate.map_data_climate(index)
    names = climate_block.pop("tile_names", [])
    climate_block["tile_split"] = tile_split(names)
    return {"climate": climate_block, "summary": summary.map_data_summary(index),
            "snow": snow_map_block(index), "stations": stations_map_block(index),
            "gauges": gauges_map_block(index), "county": county_map_block(index)}


TILE_PARTS = re.compile(r"r(\d{4})_c(\d{4})")


def tile_split(names) -> dict:
    """The tiles a store holds, as a compact split map (D40): {"<tile row>": [[first column, last column], ...]}, the
    tile indices as the tile names write them (r0060_c0139 is row "60", column 139). No block lists every tile name
    (the names are 4,597 and 4,569 strings); a tile with no run is not in the store, so it has no Montana cell."""
    rows: dict[str, list[list[int]]] = {}
    for name in sorted({n for n in names if isinstance(n, str)}):
        m = TILE_PARTS.fullmatch(name)
        if m is None:
            continue
        r, c = int(m.group(1)), int(m.group(2))
        runs = rows.setdefault(str(r), [])
        if runs and runs[-1][1] == c - 1:
            runs[-1][1] = c
        else:
            runs.append([c, c])
    return rows


def _clear_words(text: str) -> str:
    """A line the page shows as unavailable, partial or held, with the all-clear sentence at its end (D41)."""
    from . import summary as sm
    return sm._clear(text) if text else text


def summary_unavailable(problem: str, town: dict | None = None) -> dict:
    """The summary's shape when the store cannot give it: state unavailable, the reason and no rows (D16)."""
    from . import summary as sm
    return {"format": sm.FORMAT, "state": "unavailable", "problem": str(problem), "place": {"town": (town or {}).get("slug")},
            "as_of": None, "window": [], "title": sm.WORDS_SUMMARY["table_title"], "plain": sm.WORDS_SUMMARY["plain"],
            "table": {"columns": list(sm.COLUMNS), "rows": [], "partial": None, "held": None},
            "radar_sentence": sm.WORDS_SUMMARY["radar_sentence"], "roof": None, "sections": [], "how_made": [], "about": [],
            "town": None, "stale": None}


def town_summary(out: Path, town: dict, now: datetime) -> dict:
    """The five-season summary at a town's grid cell (summary.describe_summary, with the town point for the stations and the
    river gauge). A store that cannot be read gives the unavailable shape with its reason."""
    from . import summary
    row, col = hs.cell_for(town["lat"], town["lon"])
    point = {"slug": town["slug"], "name": town["name"], "lat": town["lat"], "lon": town["lon"]}
    try:
        return summary.describe_summary(out, row, col, now, town=point)
    except (hs.HailStoreError, OSError, ValueError, KeyError, TypeError, IndexError) as e:
        return summary_unavailable(f"the summary could not be built ({type(e).__name__})", town)


def _table_view(s: dict, foot) -> list[dict]:
    """The table's rows as the page shows them: every season and the five-season column with its unit's words; a cell that
    is Data unavailable carries a footnote number, and its reason is listed under the table (foot)."""
    from . import summary as sm
    out = []
    for r in s["table"]["rows"]:
        if r["key"] == "held":          # the four held items: one line, its reason in a footnote
            reason = " ".join(r["notes"]) or HISTORY_WORDS["no_reason"]     # the four held items, as one footnote
            out.append({"label": r["label"], "kind": r["kind"], "unit": r["unit"], "unit_word": sm.UNIT_SPEC[r["unit"]]["word"],
                        "held": True, "foot": foot(reason), "cells": [], "five": None, "town_only": False})
            continue
        notes = r["notes"]

        def cell(text, cov):
            text = text or sm.WORDS_SUMMARY["cell_unavailable"]
            if text.startswith(sm.WORDS_SUMMARY["cell_unavailable"]):
                reason = text if text != sm.WORDS_SUMMARY["cell_unavailable"] else (notes[0] if notes else HISTORY_WORDS["no_reason"])
                return {"text": sm.WORDS_SUMMARY["cell_unavailable"], "foot": foot(reason), "cov": cov or ""}
            return {"text": text, "foot": None, "cov": cov or ""}
        out.append({"label": r["label"], "kind": r["kind"], "unit": r["unit"], "unit_word": sm.UNIT_SPEC[r["unit"]]["word"],
                    "held": False, "town_only": bool(r.get("town_only")),
                    "cells": [cell(t, c) for t, c in zip(r["texts"], r["coverage"])],
                    "five": cell(r["five_text"], r["five_coverage"]), "foot": None})
    return out


def _joined_coverage(pairs: list[tuple[str, str]]) -> str:
    """The coverage lines of one season's figures as one phrase: the same line once, or each row's line named by its word
    when the rows differ (highest and lowest, two stations), so "n days missing" is written once for each count."""
    texts = list(dict.fromkeys(text for _word, text in pairs))
    if len(texts) == 1:
        return texts[0]
    return "; ".join(f"{word}: {text}" for word, text in pairs)


def _per_season(rows: dict, label: str, keys: tuple, names: tuple) -> list[dict]:
    """One row per season from the table's own words for these keys (highest and lowest, a count, a depth), with the
    coverage line of any missing days (never a zero for a missing day)."""
    from . import summary as sm
    out = []
    for k, season in enumerate(sm.FIVE):
        parts, cov = [], []
        for key, word in zip(keys, names):
            row = rows.get(key)
            if row is None:
                continue
            text = row["texts"][k] or sm.WORDS_SUMMARY["cell_unavailable"]
            if text.startswith(sm.WORDS_SUMMARY["cell_unavailable"]):   # a season that did not load says so in the table's footnotes
                continue
            parts.append(f"{word} {text}")
            if row["coverage"][k]:
                cov.append((word, row["coverage"][k]))
        if parts:
            out.append({"label": label, "text": f"{season}: " + "; ".join(parts) + (f" ({_joined_coverage(cov)})" if cov else "")})
    return out


def _window_lines(s: dict, through: str | None) -> list[str]:
    """How the periods are counted: the radar and report windows, the grid's newest day and the station window."""
    from . import summary as sm
    W = sm.WORDS_SUMMARY
    lines = []
    if s.get("window") and s.get("as_of"):
        first, last = (hs.fmt_date(date.fromisoformat(x)) for x in s["window"])
        as_of = hs.fmt_date(date.fromisoformat(s["as_of"]))
        lines.append(W["window_radar"].format(first=first, last=last, as_of=as_of, season=sm.FIVE[0]))
        lines.append(W["window_reports"].format(first=first, last=last))
    if through:
        lines.append(W["window_grid"].format(through=hs.fmt_date(date.fromisoformat(through))))
    lines.append(W["window_station"])
    return lines


def kind_what() -> dict:
    """The sentence each kind of record opens with on its section: the words the modules already hold (hail.WORDS,
    summary.WORDS_INDICATORS, joins.WORDS_JOINS), keyed by the row label the section shows."""
    from . import joins as jn, summary as sm
    W = sm.WORDS_INDICATORS
    return {"Radar estimate": hs.WORDS["what_this_is"], "Report": W["what_reports"],
            "Record": jn.WORDS_JOINS["records_what"], "Detection": jn.WORDS_JOINS["detections_what"],
            "Warning": W["what_warnings"], "Zone product": jn.WORDS_JOINS["zones_what"],
            "County product": jn.WORDS_JOINS["county_what"], "Station": W["what_station"],
            "Station reading": W["what_station"], "Grid estimate": W["what_grid"]}


def history_view(s: dict, jv: dict, radar: dict, town: dict, now, through: str | None) -> dict:
    """One town's five-season history as the page shows it: the notices, the table (with footnotes), the partial line, the
    radar sentence and the sections in the brief's order, each with its lead, its kind word, its rows (each starting with its
    kind label) and its notes. s is summary.describe_summary's result, jv the joined records' view and radar the radar
    words (hail.describe); all three are plain dicts, so an unavailable part shows its words without a crash."""
    from . import summary as sm
    W, H = sm.WORDS_SUMMARY, HISTORY_WORDS
    view = {"state": s.get("state"), "problem": s.get("problem"), "title": H["town_title"].format(town=town["name"]),
            "plain": W["plain"], "cell": H["cell"], "notices": [], "table": None, "partial": None,
            "radar_sentence": W["radar_sentence"], "footnotes": [], "sections": [], "stale": s.get("stale"),
            "sample": radar.get("sample"), "show_first": HISTORY_SHOW_FIRST,
            "table_caption": H["table_caption"].format(town=town["name"]), "footnote_title": H["footnotes"]}
    if s.get("state") == "unavailable":
        view["notices"] = [H["unavailable"].format(problem=s.get("problem") or "the store could not be read")]
        return view
    if s.get("state") == "outside":                   # the radar words say which: the sample's, or Montana's outside line
        view["notices"] = [radar.get("outside") or H["outside"]]
        return view
    notes_foot: list[str] = []

    def foot(reason: str) -> int:
        if reason not in notes_foot:
            notes_foot.append(reason)
        return notes_foot.index(reason) + 1      # the footnote number; the list is set at the end

    view["table"] = {"columns": list(s["table"]["columns"]), "rows": _table_view(s, foot)}
    view["partial"] = s["table"]["partial"]
    view["notices"] += [sec["unavailable"] for sec in jv.get("sections", []) if sec.get("unavailable")]
    if radar.get("unavailable"):
        view["notices"].append(_clear_words(radar["unavailable"]))
    rows = {r["key"]: r for r in s["table"]["rows"]}

    # the rows of each section: the grid and station rows (per season), the radar days and the joined rows by kind
    bucket: dict[str, list[dict]] = {k: [] for k in HISTORY_SECTIONS}
    bucket["temperature"] += _per_season(rows, "Grid estimate", ("tmax", "tmin"), ("highest", "lowest"))
    bucket["temperature"] += _per_season(rows, "Station reading", ("tmax_station", "tmin_station"), ("highest", "lowest"))
    bucket["rain"] += _per_season(rows, "Grid estimate", ("precip", "precip_max"), ("precipitation", "largest one day"))
    bucket["snow"] += _per_season(rows, "Station reading", ("snow", "snow_depth"), ("snowfall", "deepest snow"))
    bucket["ice"] += _per_season(rows, "Grid estimate", ("freeze_thaw", "frost32"), ("freeze-thaw", "low below 32 F"))
    bucket["heat"] += _per_season(rows, "Grid estimate", ("hot90",), ("high of 90 F or more",))
    if radar.get("state") == "loaded":
        bucket["hail"] += [{"label": "Radar estimate", "text": r["text"]} for r in radar.get("rows", [])]
    for sec in jv.get("sections", []):
        for row in sec.get("rows", []):
            label, body = _split_kind(row["text"])
            bucket[_section_of(label, body)].append({"label": label, "text": body, "note": row.get("note") or ""})
    bucket["flooding"] = [{"label": H["gauge_label"], "text": line} for line in (s.get("town") or {}).get("gauge") or []] \
        + bucket["flooding"]

    notes = {k: [] for k in bucket}
    for sec_id, keys in (("hail", ("radar_max", "radar_1in", "hail_max", "hail_n")), ("wind", ("gust_days", "gust_max", "wind_n", "hw_zone")),
                         ("storms", ("hail_warnings", "flood_warn")), ("temperature", ("tmax", "tmin")),
                         ("rain", ("precip", "precip_max")), ("snow", ("snow", "snow_depth")),
                         ("flooding", ("flood_report_n", "flood_record_n", "flood_warn", "county_watch")),
                         ("ice", ("freezing_rain_n", "ice_warn", "freeze_thaw")), ("heat", ("hot90",))):
        for key in keys:
            for note in (rows.get(key) or {}).get("notes", []):
                if note not in notes[sec_id]:
                    notes[sec_id].append(note)
    notes["snow"].append(W["analysis_held"])                    # D23: the analysis was checked and left out
    notes["made"] = list(s.get("how_made") or []) + _window_lines(s, through) + [H["times"]]
    # each section opens with what its kinds of record are (the words each kind has, per section, once)
    what = kind_what()
    for sid in HISTORY_SECTIONS:
        kinds = list(dict.fromkeys(row["label"] for row in bucket[sid]))
        notes[sid] = [what[k] for k in kinds if k in what] + notes[sid]
    entries = {sec["id"]: sec for sec in s.get("sections", [])}
    for sid in HISTORY_SECTIONS:
        entry = entries.get(sid, {"heading": W["section_titles"][sid], "lead": "", "kind": ""})
        sec = {"id": sid, "heading": entry["heading"], "lead": entry["lead"], "kind": entry["kind"],
               "rows": bucket[sid], "notes": notes[sid] if sid != "roof" else [],
               "show_all": H["show_all"].format(n=len(bucket[sid]))}
        if sid == "roof" and s.get("roof"):
            sec["groups"] = [{"name": g["name"], "lines": [{"label": ln["label"], "text": ln["text"], "kind": ln["kind"]}
                                                           for ln in g["lines"]],
                              "references": [{"label": H["reference_label"], "text": r["text"]} for r in g["references"]],
                              "held": [{"label": h["label"], "text": h["text"], "kind": h["kind"]} for h in g["held"]]}
                             for g in s["roof"]["groups"]]
            sec["notes"] = list(s["roof"].get("how_made") or [])
        view["sections"].append(sec)
    view["footnotes"] = list(notes_foot)
    return view


NOAA_REGISTRY_QUOTE = ("NOAA requests attribution for the use or dissemination of unaltered NOAA data. However, it is not "
                       "permissible to state or imply endorsement by or affiliation with NOAA. If you modify NOAA data, you "
                       "may not state or imply that it is original, unaltered NOAA data.")


def about_terms() -> list[dict]:
    """The licence and attribution sentences of the new sources, quoted from the module docstrings and the records (B5,
    D41): each source's own words, in order. Where a source's use terms were not read, the page says so."""
    from . import joins as jn, snowgrid
    return [
        {"source": "NOAA nClimGrid-Daily (daily temperature and rain grid)", "terms": [
            "The file attribute reads \"license = no restrictions\". The NOAA registry reads: \"" + NOAA_REGISTRY_QUOTE + "\" "
            "The page says \"US government data; NOAA declares no restrictions; attribution requested\". No NOAA page checked "
            "says public domain for these grids, so this site does not say so."]},
        {"source": "NOAA NOHRSC National Snow Analysis (season snowfall)", "terms": [
            snowgrid.PUBLIC_DOMAIN_TEXT, snowgrid.SECTION_403_TEXT]},
        {"source": "NOAA NCEI GHCN-Daily (station records)", "terms": [
            "\"These data are in the public domain in the United States.\" (NCEI-PD-10-2-02, section 4(a)). CoCoRaHS records: "
            "\"Unless otherwise noted, all CoCoRaHS content and data are released under a Creative Commons Attribution 3.0 "
            "License\", and the source is to be acknowledged. Cite NCEI-PD-10-2-02."]},
        {"source": "Iowa State IEM archive (warnings, zone products and local storm reports)", "terms": [
            "\"The materials found on this website are in the public domain and may be used freely by anyone for any lawful "
            "purpose.\" \"Attributing the Iowa Environmental Mesonet of Iowa State University would be appreciated.\" \"We "
            "therefore provide this information without any warranty of accuracy.\"",
            "\"The information on National Weather Service Web servers and Web sites is in the public domain, unless "
            "specifically annotated otherwise, and may be used freely by the public.\" \"You also cannot present information "
            "of your own in a way that makes it appear to be official government information.\""]},
        {"source": "Iowa State IEM zone outlines (the Montana public forecast zones by date)", "terms": [
            "The IEM API disclaimer reads: \"All of these services are provided as-is and without warranty. You are free to "
            "use these services for any lawful purpose\" (quoted in part). The outlines of the 20 zones removed on 13 "
            "September 2022 (MTZ008 to MTZ015 and MTZ044 to MTZ055) and of MTZ060 before that change are the IEM's simplified "
            "geometry; the 83 zones in force since then keep the NWS outlines. A product issued in the changeover week, 7 to "
            "13 September 2022, is placed by the zone set that holds its code."]},
        {"source": "NOAA NCEI Storm Events (point and zone records)", "terms": [
            "The use terms of this copy were not read in this build, so they are not quoted."]},
        {"source": "NWS National Water Prediction Service and USGS (river gauges)", "terms": [
            "\"Observations courtesy of U.S. Geological Survey\" (the NWPS attribution text). Not all USGS site content is "
            "public domain; the peaks are USGS data."]},
        {"source": "US Census Bureau TIGER/Line 2026 counties", "terms": [src.CENSUS_TERMS]},
    ]


def about_hail_context() -> dict:
    """The About page's words for the five-year history (--hail-history only): the snow analysis left out (D23), the
    hit-and-miss sentence (B5 D15), the Census acknowledgement, the new sources' terms (about_terms), the held items and
    the roof reference lines, with the five references the sheet does not quote and the reason (D41)."""
    from . import joins as jn, summary as sm
    refs = [{"id": rid, "source": ref["source"], "url": ref["url"], "quote": ref["quote"]}
            for rid, ref in sorted(sm.REFERENCE_LINES.items(), key=lambda kv: int(kv[0][1:]))]
    return {"analysis": sm.WORDS_SUMMARY["analysis_held"], "hit_miss": jn.WORDS_JOINS["about_hit_miss"],
            "census": src.CENSUS_TERMS, "refs": refs, "held": sm.WORDS_INDICATORS["held"],
            "terms": about_terms(), "not_quoted": sm.not_quoted_text(), "citations": sm.citations()}


def build(out: Path, fetch: src.Fetcher | None, now: datetime, previous: dict | None = None,
          sample: bool = False, storm_layers: bool = False, hail_history: bool = False,
          hail_store_path: str | None = None) -> dict:
    if out.exists():
        shutil.rmtree(out)
    (out / "town").mkdir(parents=True)
    (out / "data").mkdir()
    shutil.copytree(HERE / "static", out / "static", ignore=_unbuilt_static(storm_layers))

    if sample:
        from . import sample as sample_data
        fetch = sample_data.SampleFetcher(now)
    c = Collector(fetch, now, previous)
    alerts = c.alerts()
    towns = c.towns()
    c.add_town_alerts(alerts, towns)
    reports = c.reports()
    layers = c.gridded(out, sample)
    satellite_text = None
    if storm_layers:
        from . import satellite as sat
        layers["satellite"] = c.satellite(out, sample)
        satellite_text = sat.describe(layers["satellite"], c.status["satellite"], now)
    if storm_layers:
        storms = c.storm(towns, sample)
        for t in towns:
            t["storm"] = storms[t["slug"]]
    hail_block = c.hail(out, sample, hail_store_path, towns) if hail_history else None

    base = {"built": now, "built_ms": int(now.timestamp() * 1000),
            "asset_v": asset_versions(out / "static", VERSIONED + ((STORM_JS,) if storm_layers else ())),
            "status": c.status, "sample": sample, "storm_layers": storm_layers, "satellite_text": satellite_text,
            "hail_history": hail_history, "hail_words": hs.WORDS if hail_history else None,
            "limits": src.LIMITS, "imagery": IMAGERY, "offices": OFFICES,
            "towns_nav": [(t["slug"], t["name"]) for t in TOWNS],
            "contracts": {k: v for k, v in src.CONTRACTS.items()
                          if (storm_layers or k not in STORM_CONTRACTS) and (hail_history or k not in HAIL_CONTRACTS)
                          # a row a B5 row replaces is listed once, as the B5 row (sources.py superseded_by)
                          and not (hail_history and v.get("superseded_by"))},
            "about_hail": about_hail_context() if hail_history else None,
            "fresh_min": src.FRESH_MINUTES, "qc_words": src.QC_WORDS,
            "qc_rejected": src.QC_REJECTED}
    e = env()
    pages = {
        "index.html": ("index.html", {"page": "now", "root": "", "alerts": alerts, "towns": towns,
                                      "card": map_card(layers, alerts, towns, c.status, now)}),
        "map.html": ("map.html", {"page": "map", "root": "", "towns": towns}),
        "reports.html": ("reports.html", {"page": "reports", "root": "", "reports": reports}),
        "about.html": ("about.html", {"page": "about", "root": ""}),
    }
    for name, (tpl, ctx) in pages.items():
        (out / name).write_text(e.get_template(tpl).render(**base, **ctx), encoding="utf-8")
    for t in towns:
        html = e.get_template("town.html").render(**base, page="town", root="../", town=t, now=now,
                                                 delta_hour=timedelta(hours=1))
        (out / "town" / f"{t['slug']}.html").write_text(html, encoding="utf-8")

    (out / "data" / "map.json").write_text(
        json.dumps(map_data(now, sample, layers, towns, alerts, reports, c.status, hail=hail_block),
                   separators=(",", ":")),
        encoding="utf-8")
    state = {"built": src._iso(now), "sample": sample, "status": c.status,
             "alerts": {k: v for k, v in alerts.items() if k not in ("error", "from_towns")},
             "points": {t["slug"]: t["point"] for t in towns if t.get("point")},
             # the station lists, for reuse when a lookup fails; the readings themselves, with their
             # raw values and flags, as a record of what each town showed (D29)
             "stations": {t["slug"]: [{k: v for k, v in s.items() if k not in ("obs", "error")}
                                      for s in t["obs"]["stations"]] for t in towns if t["obs"]["stations"]},
             "readings": {t["slug"]: [{"id": s["id"], "obs": s["obs"], "error": s["error"]}
                                      for s in t["obs"]["stations"]] for t in towns if t["obs"]["stations"]}}
    (out / "data" / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    content = content_sample(alerts, towns, reports, satellite_text)
    if hail_history:                         # --hail-history only: each town's hail line, for the build log
        content["hail"] = {t["name"]: t["hail"]["lead"] or t["hail"]["unavailable"] or t["hail"]["outside"]
                           for t in towns}
    return {"status": c.status, "alerts": len(alerts["items"]),
            "alerts_null_geometry": sum(1 for a in alerts["items"] if not a["geometry"]),
            "towns_with_forecast": sum(1 for t in towns if t["hours"]),
            "towns_with_gusts": sum(1 for t in towns if t["summary"]["gusts_known"]),
            "towns_with_readings": sum(1 for t in towns if t["obs"]["now"]),
            "reports": len(reports["items"]), "map": map_summary(layers),
            "content": content}


def map_summary(layers: dict) -> dict:
    """Frame counts and sources per map layer, for the build log and the run summary."""
    out = {}
    for key, layer in layers.items():
        frames = layer.get("frames", [])
        radar = [f for f in frames if f.get("kind") == "radar"]
        fcst = [f for f in frames if f.get("kind") == "forecast"]
        out[key] = {"frames": len(frames), "radar": len(radar), "forecast": len(fcst),
                    "first": frames[0]["time"] if frames else None, "last": frames[-1]["time"] if frames else None,
                    "run": next((f.get("run") for f in fcst if f.get("run")), None)}
    return out


def content_sample(alerts, towns, reports, satellite_text: str | None = None) -> dict:
    """What the pages say, in brief, for the build log: rule 7 asks for a look at the content,
    not just a 200. The workflow prints the town table in the run summary."""
    out = {
        "alert_events": [f"{a['event']} until {fmt_time(a['until'])}" for a in alerts["items"][:10]],
        "towns": {t["name"]: {"lo": t["summary"]["lo"], "hi": t["summary"]["hi"], "gust": t["summary"]["gust"],
                              "wind": t["summary"]["wind"], "precip": t["summary"]["precip"],
                              "flagged": t["summary"]["flagged"], "issued": fmt_time(t["updated"]),
                              "office": t["office"], "alerts": None if t["alerts"] is None else len(t["alerts"]),
                              "now": reading_sample(t["obs"]["now"]),
                              **({"storm": t["storm"]["text"]} if "storm" in t else {})}
                  for t in towns},
        "reports_by_day": {d: sum(1 for r in reports["items"] if r["day"] == d) for d in reports["days"]},
    }
    if satellite_text:                       # --storm-layers only
        out["satellite"] = satellite_text
    return out


def reading_sample(s: dict | None) -> dict | None:
    """A town card's station reading in brief, for the build log and the run summary."""
    if not s:
        return None
    o = s["obs"]
    return {"station": s["id"], "miles": round(s["miles"]), "temp_f": _round(o["temp"]["value"]),
            "wind_mph": _round(o["wind"]["value"]), "dir": o["dir"], "gust_mph": _round(o["gust"]["value"]),
            "no_gust": o["no_gust"], "age_min": o["age_min"], "current": o["current"]}


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
    ap.add_argument("--storm-layers", action="store_true",
                    help="also read NOAA radar echo tops for each town (text only) and the GOES satellite "
                         "picture for the map; off by default")
    ap.add_argument("--hail-history", action="store_true",
                    help="also the five-year hail history: the store's files, a cell history on the map and a "
                         "section on each town page; off by default")
    ap.add_argument("--hail-store", metavar="PATH",
                    help="with --hail-history: a folder or hail-store.tar.gz holding hail/, used instead of the "
                         "download (local checks and the daily job's file)")
    ap.add_argument("--now", help="build time (ISO, UTC); default: now")
    a = ap.parse_args(argv)
    if a.hail_store and not a.hail_history:
        ap.error("--hail-store needs --hail-history")
    now = src.parse_iso(a.now) if a.now else datetime.now(UTC).replace(microsecond=0)
    out = Path(a.out)
    result = build(out, None if a.sample else src.Fetcher(), now,
                   None if a.sample else load_previous(a.previous), sample=a.sample,
                   storm_layers=a.storm_layers, hail_history=a.hail_history, hail_store_path=a.hail_store)
    print(json.dumps(result, indent=1, default=str))
    failed = [k for k, v in result["status"].items() if not v["ok"]]
    if a.require_live and failed:
        print("Sources that failed or were stale: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
