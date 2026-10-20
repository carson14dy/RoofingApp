"""Build the Montana Hail Watch website into a folder of static files.

    python -m website.build --out _site                 # live data (needs internet)
    python -m website.build --out _site --sample        # labelled sample data, no network
    python -m website.build --out _site --require-live  # fail if any source failed (preview checks)
    python -m website.build --out _site --storm-layers  # also NOAA radar echo tops (text) and the GOES satellite picture
    python -m website.build --out _site --hail-history  # also the five-year hail history (website/hail.py)
    python -m website.build --out _site --sample --hail-history --hail-store store.tar.gz  # a local store, not the download
    python -m website.build --out _site --hail-history --hail-addresses  # also the address dots, streets and building outlines (B3)
    python -m website.build --out _site --hail-history --hail-addresses --address-text off  # the same, with no address text (D35)

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import addresses as ad
from . import buildings as bd
from . import hail as hs
from . import sources as src
from . import streets as st

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

    def hail(self, out_dir: Path, sample: bool, store: str | None, towns: list, addresses: bool = False,
             address_text: str = "on") -> dict:
        """The five-year hail history (website/hail.py; --hail-history only). The store's hail/ files are copied
        into the site, and each town gets its words (town["hail"]). One status line, like the others: a store
        that doesn't load is a failed source, the pages say so in words, and the build goes on (--require-live
        then fails). Returns the map.json block. The copy is made only after the store's manifest checks out."""
        sampled = sample and store is None          # the SAMPLE fixture only; a --hail-store file is real data
        index, problem = None, None
        try:
            index = hail_store(out_dir, store, sample, self.f, addresses)
            tiles = hail_tiles(index, out_dir)
            cells = [hs.cell_events(out_dir, t["lat"], t["lon"]) for t in towns]
            words = [hs.describe(index, events, self.now, sample=sampled) for events in cells]
            block = hs.map_data(index, sample=sampled)
            block["tiles"] = tiles                  # the browser's outside test: a tile not listed has no Montana cell
            joins_block, joins_views = hail_joins(out_dir, index, towns, self.now, sampled)
            block["joins"] = joins_block            # the joined records behind the sheet (B2)
            detail = (f"{index['events']:,} events in {index['shards']} shard files, {index['days_present']} of "
                      f"{index['days_expected']} days, as of {index['as_of']}; joined records "
                      f"{joins_block['state']}")
            self.note("hail_history", HAIL_LABEL, True, ("SAMPLE store: " if sampled else "") + detail)
        except (hs.HailStoreError, OSError, ValueError, KeyError, TypeError) as e:
            problem = str(e) if isinstance(e, hs.HailStoreError) else f"the history files couldn't be read ({type(e).__name__})"
            self.note("hail_history", HAIL_LABEL, False, problem)
            words = [hs.describe_unavailable(problem) for _ in towns]
            block = hs.map_data_unavailable(problem)
            block["tiles"] = []                     # no store, so no tile is known: the map says unavailable, not outside
            from . import joins as jn
            block["joins"] = join_block_unavailable(jn, problem)
            joins_views = [join_view_unavailable(jn) for _ in towns]
        for t, w, jv in zip(towns, words, joins_views):
            t["hail"] = {**w, "joins": jv}
        block["words"].update(HAIL_SITE_WORDS)
        block["stale_days"] = HAIL_STALE_DAYS
        block["at_zoom"] = HAIL_AT_ZOOM
        block["tenths_per_mm"] = HAIL_TENTHS_PER_MM
        if addresses:                           # --hail-addresses only (B3): the address, street and outline layers
            block.update(self.layers(out_dir, index, problem, address_text))
        return block

    def layers(self, out_dir: Path, index: dict | None, problem: str | None, address_text: str) -> dict:
        """The address, street and building layers (B3; --hail-addresses only). Each module's map block goes into
        map.json (hail.addresses, hail.roads, hail.buildings) with the attribution lines of the layers that loaded
        (D29). One status line per layer: a layer that did not load is a failed source, the pages say so in words,
        and the build goes on (D36). In the off mode (D35) the address text is removed from the copied files; if that
        cannot be done, the address files are removed, so the site never shows text the mode leaves out."""
        found = b3_index(index, problem)
        try:
            if address_text == "off" and index is not None:
                strip_address_text(out_dir)
            blocks = b3_map_blocks(found, address_text)
        except (OSError, ValueError, KeyError, TypeError, hs.HailStoreError) as e:
            shutil.rmtree(out_dir / "hail" / "a", ignore_errors=True)
            shutil.rmtree(out_dir / "hail" / "b", ignore_errors=True)
            found = b3_index(None, f"the address files couldn't be prepared ({type(e).__name__})")
            blocks = b3_map_blocks(found, address_text)
        self.b3_index = found
        self.road_kind = found[st.INDEX_KEY].get("kind") if b3_loaded(found, st.INDEX_KEY) else None
        for key, label, mod in B3_LISTS:
            ok = b3_loaded(found, mod)
            self.note(key, label, ok, b3_detail(found, mod) if ok else b3_reason(found, mod))
        return blocks


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
HAIL_CONTRACTS = ("hail_history",) + JOIN_CONTRACTS  # on the About page only in a --hail-history build
ADDRESS_TEXT_MODES = ("on", "off")                 # --address-text (D35): off writes no address text at all
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


def hail_store(out: Path, store: str | None, sample: bool, fetch, addresses: bool = False) -> dict:
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
            return _copy_hail(root, out, hs.load_index(root), addresses)
    if sample:
        index = hs.load_index(hs.FIXTURE_DIR)
        hs.check_manifest(hs.FIXTURE_DIR)
        return _copy_hail(hs.FIXTURE_DIR, out, index, addresses)
    with tempfile.TemporaryDirectory(prefix="hail-store-") as tmp:
        index = hs.fetch_store(fetch.binary, tmp, hs.STORE_URL)
        return _copy_hail(Path(tmp), out, index, addresses)


B3_FOLDERS = ("a", "b", "r")     # the store's address, outline and road folders (B3): copied only with --hail-addresses
B3_FILES = ("counts.json",)      # the store's outline counts (buildings.py, B3): copied only with --hail-addresses
B3_INDEX = (ad.INDEX_KEY, st.INDEX_KEY, bd.INDEX_KEY)   # the index blocks the B3 modules write (addresses, roads, buildings)


def _copy_hail(root: Path, out: Path, index: dict, addresses: bool = False) -> dict:
    """Copy root/hail/ into the site as out/hail/ (the shards the map and the town pages read). The B3 folders and files
    are copied only with --hail-addresses (default off, D35): a build without the flag carries no address, outline or
    road file, its manifest lists none, and its index.json has none of the B3 blocks (the index is written again without
    them and its manifest entry is updated, so the copy still checks out). The copy is checked against the manifest."""
    if addresses:
        shutil.copytree(root / "hail", out / "hail")
        return index
    b3_names = B3_FOLDERS + B3_FILES

    def skip_b3(folder: str, names: list) -> list:
        return [name for name in names if Path(folder) == root / "hail" and name in b3_names]

    shutil.copytree(root / "hail", out / "hail", ignore=skip_b3)
    manifest_path = out / "hail" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def b3_entry(rel: str) -> bool:
        parts = rel.split("/")
        return len(parts) > 1 and parts[1] in b3_names

    manifest["files"] = {rel: entry for rel, entry in manifest.get("files", {}).items() if not b3_entry(rel)}
    kept = index
    if any(key in index for key in B3_INDEX):
        kept = {key: value for key, value in index.items() if key not in B3_INDEX}
        index_bytes = hs._pretty(kept)
        (out / "hail" / "index.json").write_bytes(index_bytes)
        manifest["files"]["hail/index.json"] = {"bytes": len(index_bytes),
                                                "sha256": hashlib.sha256(index_bytes).hexdigest()}
    manifest_path.write_bytes(hs._pretty(manifest))
    hs.check_manifest(out)                           # raises HailStoreError if the copy does not match
    return kept


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
            "note": " ".join(section["lines"]), "unavailable": section["unavailable"] or "",
            "show_all": JOIN_SITE_WORDS["show_all"].format(n=len(rows))}


def join_view_unavailable(jn) -> dict:
    """A town's six sections when their words cannot be written from the records: each part says why."""
    w = jn.WORDS_JOINS
    sections = []
    for part in jn.PARTS:
        sections.append({
            "key": part, "head": JOIN_HEADS[part], "heading": join_heading(jn, part), "lead": "", "fire_lead": "", "rows": [],
            "what": " ".join(x for x in (w[f"{part}_what"], w[f"source_{part}"]) if x), "note": "",
            "unavailable": jn._unavailable_text(part, None), "show_all": ""})
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


# ---------------------------------------------------------------- the address, street and outline layers (B3)

# --hail-addresses only. Each module (website/addresses.py, streets.py, buildings.py) writes its own map block and its
# words; this site build puts the blocks into data/map.json (hail.addresses, hail.roads, hail.buildings), renders the
# form, the legend lines and the About paragraphs, and removes the address text in the off mode (D35). The store keys
# are the modules' INDEX_KEY values.
B3_LISTS = (("address_list", "Montana address list", ad.INDEX_KEY),
            ("street_list", "Montana streets", st.INDEX_KEY),
            ("outline_list", "Building outlines", bd.INDEX_KEY))
ADDRESS_SEARCH_KEYS = ("cities", "letter", "words", "search_words", "dir", "file_key")   # map.json: the search index's names
# hail/index.json's addresses block: the letter-index counts and names, which describe the search files (D35, R-07)
ADDRESS_LETTER_KEYS = ("cities", "letter_files", "largest_letter", "two_character_files", "over_limit_letter_files")
# The drawing settings the browser's B3 layers read (map.json hail.draw). The label cap (300 names per view with the halo),
# the fit margin (the name's piece is at least its width plus 10 px) and the angle step (5 degrees) are measured in
# research-b35/rendering.json. The cache cap and the label grid cell are the site's own settings, not measured: 32 MiB of
# shard files held in the page, and 48 px label cells for the collision test.
B3_DRAW = {"cache_bytes": 32 * 1024 * 1024, "labels": {"per_view": 300, "fit_px": 10, "grid_px": 48, "angle_deg": 5}}
ADDRESS_FORM_WORDS = ("title", "search_hint", "search_none", "search_capped", "privacy")  # map.json: the form's words
FIND_BUTTON = "Find"                    # the form's button (the form's words are the module's; this one is the page's)
B3_ROWS = ("msl_addresses", "usa_structures", "census_counties")  # the About rows of a --hail-addresses build
ROAD_ROWS = {"msl": "msl_roads", "tiger": "census_roads"}        # the road row of the source the store built (D25)


def b3_index(index: dict | None, problem: str | None) -> dict:
    """The store's index as the three layer modules read it. Without a store, or with one that failed, each layer gets
    an unavailable block that carries the reason, so every page says why and never draws an empty layer."""
    if index is not None:
        return index
    reason = problem or "the store is not available"
    return {key: {"state": "unavailable", "reason": reason} for key in (ad.INDEX_KEY, st.INDEX_KEY, bd.INDEX_KEY)}


def b3_loaded(index: dict, key: str) -> bool:
    block = index.get(key)
    return isinstance(block, dict) and block.get("state") == "loaded"


def b3_reason(index: dict, key: str) -> str:
    block = index.get(key)
    return (block.get("reason") if isinstance(block, dict) else None) or "the list is not in the store"


def b3_detail(found: dict, key: str) -> str:
    """The short count a loaded layer's status line says (the build log and state.json)."""
    block = found.get(key) or {}
    if key == ad.INDEX_KEY:
        return f"{block.get('rows', 0):,} address rows in {block.get('shards', 0)} shard files"
    if key == st.INDEX_KEY:
        return f"{block.get('lines_in_shards', 0):,} road lines in {block.get('shards', 0)} shard files"
    return f"{block.get('footprints', (block.get('counts') or {}).get('footprints', 0)):,} outlines in {block.get('shards', 0)} shard files"


def b3_about_addresses(found: dict | None) -> dict:
    """describe_addresses (addresses.py) for the About page."""
    described = dict(ad.describe_addresses(found))
    return described


def b3_map_blocks(found: dict, address_text: str) -> dict:
    """map.json's three layer blocks (each module's map_data), the attribution lines of the layers that loaded (the
    Leaflet attribution control, D29) and the address-text mode (D35). In the off mode the search index's names and the
    form's words are left out of the block."""
    addresses = ad.map_data_addresses(found)
    if address_text == "off":
        addresses = {k: v for k, v in addresses.items() if k not in ADDRESS_SEARCH_KEYS}
        if isinstance(addresses.get("templates"), dict):
            addresses["templates"] = {k: v for k, v in addresses["templates"].items() if k not in ADDRESS_FORM_WORDS}
    addresses["text"] = address_text
    roads = st.map_data_streets(found)
    outlines = bd.map_data_buildings(found)
    outlines["text"] = address_text
    lines = []
    if b3_loaded(found, ad.INDEX_KEY):
        lines.append(addresses_attribution(found))
    if b3_loaded(found, st.INDEX_KEY):
        lines.append(st.describe_streets(found)["attribution"])
    if b3_loaded(found, bd.INDEX_KEY):
        lines.append(bd.describe_buildings(found)["source"])
    return {"addresses": addresses, "roads": roads, "buildings": outlines, "attribution": lines, "draw": B3_DRAW}


# The map's attribution line for the address list (D17, D44): the Library, the file's date when the index read one (D24),
# and the use sentence quoted from the file's metadata (addresses.USE_CONVENIENCE_TEXT, quoted exactly in D8).
ADDRESS_ATTRIBUTION = ("Addresses: Montana State Library, Structures and Addresses Framework, file dated {pubdate}. Terms in the "
                       "file's metadata: \"{convenience}\"")
ADDRESS_ATTRIBUTION_UNDATED = ("Addresses: Montana State Library, Structures and Addresses Framework (file date not available in "
                               "this update). Terms in the file's metadata: \"{convenience}\"")


def addresses_attribution(found: dict) -> str:
    source = (found.get(ad.INDEX_KEY) or {}).get("source") or {}
    if "pubdate" in source:
        return ADDRESS_ATTRIBUTION.format(pubdate=source["pubdate"], convenience=ad.USE_CONVENIENCE_TEXT)
    return ADDRESS_ATTRIBUTION_UNDATED.format(convenience=ad.USE_CONVENIENCE_TEXT)


def b3_words(found: dict, address_text: str) -> dict:
    """The words the Map and About pages print for the three layers: the form, the legend lines and the About
    paragraphs, each from its module (D13, D17, D21, D29, D34, D35). No word names an owner or what a building is used
    for, and a layer that did not load gets its module's unavailable sentence in place of its words."""
    roads = st.describe_streets(found)
    addr_ok, road_ok, outline_ok = b3_loaded(found, ad.INDEX_KEY), b3_loaded(found, st.INDEX_KEY), \
        b3_loaded(found, bd.INDEX_KEY)
    sample = found.get(ad.INDEX_KEY)
    return {
        "text": address_text,
        "sample": isinstance(sample, dict) and sample.get("sample") is True,
        "sample_words": ad.WORDS_ADDRESSES["sample"],
        "unavailable": {"addresses": ad.WORDS_ADDRESSES["unavailable"], "roads": roads["unavailable"],
                        "outlines": bd.WORDS_BUILDINGS["unavailable"]},
        "attribution": [],                              # build() fills this from the map block (D29)
        "outlines_loaded": outline_ok,                  # the outlines' own legend line says what the dots are (D43, R-05)
        "form": {"title": ad.WORDS_ADDRESSES["title"], "hint": ad.WORDS_ADDRESSES["search_hint"],
                 "privacy": ad.WORDS_ADDRESSES["privacy"], "button": FIND_BUTTON},
        "legend": {
            "shapes": bd.WORDS_BUILDINGS["legend"] if outline_ok else bd.WORDS_BUILDINGS["unavailable"],
            "dots": ad.WORDS_ADDRESSES["legend"] if addr_ok else ad.WORDS_ADDRESSES["unavailable"],
            "streets": roads.get("legend") if road_ok else roads["unavailable"],
        },
        "about": {"addresses": b3_about_addresses(found), "roads": roads,
                  "outlines": bd.describe_buildings(found), "addresses_ok": addr_ok, "roads_ok": road_ok,
                  "outlines_ok": outline_ok, "counties": bd.COUNTY_ACK if counties_loaded(found) else ""},
    }


def counties_loaded(found: dict) -> bool:
    """Whether the counts by county were made (the county file was read): the About line names its Census file only then."""
    if not b3_loaded(found, bd.INDEX_KEY):
        return False
    counties = found[bd.INDEX_KEY].get("counties")
    return isinstance(counties, dict) and counties.get("state") == "loaded"


def strip_address_text(out: Path) -> None:
    """--address-text off (D35): the copied site files carry no address text. The search index (hail/a/idx/) is removed.
    Each unmatched address row keeps its position and class and loses its line, city and zip. Each building outline
    loses its address lines ("l" and "z") and the shard's common city and zip ("c"); positions, rings, classes and
    counts stay. hail/manifest.json is rewritten to list the files as they now are, and the site's copy is checked."""
    root = out / "hail"
    shutil.rmtree(root / "a" / "idx", ignore_errors=True)
    rewritten = {}
    for path in sorted((root / "a").glob("*.json")):          # the unmatched address shards, hail/a/<name>.json
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["a"] = [[row[0], row[1], "", "", "", row[5]] for row in doc.get("a", [])]
        rewritten[path] = doc
    for path in sorted((root / "b").glob("*.json")):          # the building shards, hail/b/<name>.json
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["c"] = None
        for entry in doc.get("a", []):
            entry.pop("l", None)
            entry.pop("z", None)
        rewritten[path] = doc
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    files = {rel: entry for rel, entry in manifest.get("files", {}).items() if not rel.startswith("hail/a/idx/")}
    shard_sizes = {}
    for path, doc in rewritten.items():
        data = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        path.write_bytes(data)
        files[path.relative_to(out).as_posix()] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if path.parent == root / "a":
            shard_sizes[path.stem] = len(data)
    index_path = root / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    block = index.get(ad.INDEX_KEY)
    if isinstance(block, dict):                       # R-07: the letter files are gone, so their counts leave the block
        for key in ADDRESS_LETTER_KEYS:
            block.pop(key, None)
        total = sum(shard_sizes.values())             # the shard files are the rewritten ones: their sizes are now these
        block["bytes"] = {"shards": total, "a": total}
        if shard_sizes and isinstance(block.get("largest_shard"), dict):
            name = max(shard_sizes, key=lambda n: (shard_sizes[n], n))
            block["largest_shard"] = {**block["largest_shard"], "name": name, "bytes": shard_sizes[name]}
        index_bytes = hs._pretty(index)
        index_path.write_bytes(index_bytes)
        files[index_path.relative_to(out).as_posix()] = {"bytes": len(index_bytes),
                                                         "sha256": hashlib.sha256(index_bytes).hexdigest()}
    manifest["files"] = files
    (root / "manifest.json").write_bytes(hs._pretty(manifest))
    hs.check_manifest(out)                                       # raises HailStoreError if the copy does not match


# The totals the B3 files are measured against (D38, D42): 60 MB each for the address dot shards and the letter files, 250 MB
# for the outline shards. The road shards have no total of their own (their size per file is the rule, D26).
B3_BUDGETS = {"outline_shards": 250 * 10 ** 6, "address_shards": 60 * 10 ** 6, "search_files": 60 * 10 ** 6}


def b3_sizes(out: Path) -> dict:
    """What the B3 budgets are measured against (D38), for the build's record: the outline shards (hail/b), the unmatched
    address shards (hail/a, not the search files), the search files (hail/a/idx) and the road shards (hail/r), each with
    its file count, its total bytes and its largest file."""
    groups = {"outline_shards": out / "hail" / "b", "address_shards": out / "hail" / "a",
              "search_files": out / "hail" / "a" / "idx", "road_shards": out / "hail" / "r"}
    result = {}
    for key, folder in groups.items():
        files = [p for p in folder.rglob("*.json") if p.is_file()] if folder.is_dir() else []
        if key == "address_shards":
            files = [p for p in files if "idx" not in p.relative_to(folder).parts]
        sizes = [p.stat().st_size for p in files]
        largest = max(files, key=lambda p: p.stat().st_size) if files else None
        budget = B3_BUDGETS.get(key)
        result[key] = {"files": len(files), "bytes": sum(sizes), "largest": largest.name if largest else None,
                       "largest_bytes": max(sizes) if sizes else 0, "budget_bytes": budget,
                       "within_budget": budget is None or sum(sizes) <= budget}
    return result


def contract_shown(key: str, storm_layers: bool, hail_history: bool, hail_addresses: bool, road_row: str | None) -> bool:
    """Whether a feed's About row is on the page: the storm and hail rows with their flags, the address and outline rows
    with --hail-addresses, and the road row only for the source the store built."""
    if key in STORM_CONTRACTS:
        return storm_layers
    if key in HAIL_CONTRACTS:
        return hail_history
    if key in B3_ROWS:
        return hail_addresses and hail_history
    if key in ROAD_ROWS.values():
        return hail_addresses and hail_history and key == road_row
    return True


def build(out: Path, fetch: src.Fetcher | None, now: datetime, previous: dict | None = None,
          sample: bool = False, storm_layers: bool = False, hail_history: bool = False,
          hail_store_path: str | None = None, hail_addresses: bool = False, address_text: str = "on") -> dict:
    if hail_addresses and not hail_history:
        raise ValueError("--hail-addresses needs --hail-history")
    if address_text not in ADDRESS_TEXT_MODES:
        raise ValueError("--address-text is on or off")
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
    hail_block = c.hail(out, sample, hail_store_path, towns, addresses=hail_addresses,
                        address_text=address_text) if hail_history else None
    b3 = b3_words(c.b3_index, address_text) if hail_addresses else None
    if b3 is not None:
        b3["attribution"] = hail_block["attribution"]
    road_row = ROAD_ROWS.get(c.road_kind) if hail_addresses else None

    base = {"built": now, "built_ms": int(now.timestamp() * 1000),
            "asset_v": asset_versions(out / "static", VERSIONED + ((STORM_JS,) if storm_layers else ())),
            "status": c.status, "sample": sample, "storm_layers": storm_layers, "satellite_text": satellite_text,
            "hail_history": hail_history, "hail_words": hs.WORDS if hail_history else None,
            "hail_addresses": hail_addresses, "address_text": address_text, "b3": b3,
            "limits": src.LIMITS, "imagery": IMAGERY, "offices": OFFICES,
            "towns_nav": [(t["slug"], t["name"]) for t in TOWNS],
            "contracts": {k: v for k, v in src.CONTRACTS.items()
                          if contract_shown(k, storm_layers, hail_history, hail_addresses, road_row)},
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
    return {**({"b3_sizes": b3_sizes(out)} if hail_addresses else {}),
            "status": c.status, "alerts": len(alerts["items"]),
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
    ap.add_argument("--hail-addresses", action="store_true",
                    help="with --hail-history: also the address dots, the street lines and the building outlines "
                         "(B3, the store's hail/a, hail/r and hail/b); off by default")
    ap.add_argument("--address-text", choices=ADDRESS_TEXT_MODES, default="on",
                    help="with --hail-addresses: off builds the dots with no address text and no search (D35)")
    ap.add_argument("--now", help="build time (ISO, UTC); default: now")
    a = ap.parse_args(argv)
    if a.hail_store and not a.hail_history:
        ap.error("--hail-store needs --hail-history")
    if a.hail_addresses and not a.hail_history:
        ap.error("--hail-addresses needs --hail-history")
    if a.address_text != "on" and not a.hail_addresses:
        ap.error("--address-text off needs --hail-addresses")
    now = src.parse_iso(a.now) if a.now else datetime.now(UTC).replace(microsecond=0)
    out = Path(a.out)
    result = build(out, None if a.sample else src.Fetcher(), now,
                   None if a.sample else load_previous(a.previous), sample=a.sample,
                   storm_layers=a.storm_layers, hail_history=a.hail_history, hail_store_path=a.hail_store,
                   hail_addresses=a.hail_addresses, address_text=a.address_text)
    print(json.dumps(result, indent=1, default=str))
    failed = [k for k, v in result["status"].items() if not v["ok"]]
    if a.require_live and failed:
        print("Sources that failed or were stale: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
