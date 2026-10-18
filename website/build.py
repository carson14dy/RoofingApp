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
from datetime import datetime, timedelta, timezone
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
        try:
            index = hail_store(out_dir, store, sample, self.f)
            tiles = hail_tiles(index, out_dir)
            cells = [hs.cell_events(out_dir, t["lat"], t["lon"]) for t in towns]
            words = [hs.describe(index, events, self.now, sample=sampled) for events in cells]
            block = hs.map_data(index, sample=sampled)
            block["tiles"] = tiles                  # the browser's outside test: a tile not listed has no Montana cell
            detail = (f"{index['events']:,} events in {index['shards']} shard files, {index['days_present']} of "
                      f"{index['days_expected']} days, as of {index['as_of']}")
            self.note("hail_history", HAIL_LABEL, True, ("SAMPLE store: " if sampled else "") + detail)
        except (hs.HailStoreError, OSError, ValueError, KeyError, TypeError) as e:
            problem = str(e) if isinstance(e, hs.HailStoreError) else f"the history files couldn't be read ({type(e).__name__})"
            self.note("hail_history", HAIL_LABEL, False, problem)
            words = [hs.describe_unavailable(problem) for _ in towns]
            block = hs.map_data_unavailable(problem)
            block["tiles"] = []                     # no store, so no tile is known: the map says unavailable, not outside
        for t, w in zip(towns, words):
            t["hail"] = w
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
HAIL_CONTRACTS = ("hail_history",)                    # on the About page only in a --hail-history build
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


def _copy_hail(root: Path, out: Path, index: dict) -> dict:
    """Copy root/hail/ into the site as out/hail/ (the shards the map and the town pages read)."""
    shutil.copytree(root / "hail", out / "hail")
    return index


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
                          if (storm_layers or k not in STORM_CONTRACTS) and (hail_history or k not in HAIL_CONTRACTS)},
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
