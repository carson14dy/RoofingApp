"""Build the Montana Hail Watch website into a folder of static files.

    python -m website.build --out _site                 # live data (needs internet)
    python -m website.build --out _site --sample        # labelled sample data, no network
    python -m website.build --out _site --require-live  # fail if any source failed (preview checks)
    python -m website.build --out _site --storm-layers  # also NOAA radar echo tops (text), the GOES satellite picture and the hail swath layers
    python -m website.build --out _site --hail-history  # also the five-year hail history (website/hail.py)
    python -m website.build --out _site --sample --hail-history --hail-store store.tar.gz  # a local store, not the download
    python -m website.build --out _site --hail-history --hail-addresses  # also the address dots, streets and building outlines (B3)
    python -m website.build --out _site --hail-history --hail-addresses --address-text off  # the same, with no address text (D35)

GitHub Actions runs the live build on a schedule set to every 10 minutes and publishes the folder with GitHub Pages
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

from . import addresses as ad
from . import basemap2 as b2
from . import buildings as bd
from . import hail as hs
from . import history_layers as hl
from . import labels as lb
from . import landmarks as lm
from . import summary as sm
from . import sources as src
from . import streets as st
from . import terrain as tr
from . import gridded as gd
from . import swath as sw

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
        self.hail_index: dict | None = None    # B6: the store's index as the copy holds it (data/base.json reads it), or None
        self.hail_problem: str | None = None   # B6: why the store did not load, in plain words (None when it did)
        self.replaced: set[str] = set()        # alert ids a newer message in this build's responses replaced

    def note(self, key, label, ok, detail="", when=None, words=None):
        self.status[key] = {"label": label, "ok": ok, "detail": detail, "when": src._iso(when or self.now)}
        if words:                  # a sentence the pages print after the detail (live-1: the all-clear line)
            self.status[key]["words"] = words

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
        """Put every alert a town's point check found into the statewide list, so the home page, the
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

    def swath(self, out_dir: Path, sample: bool, towns: list) -> tuple[dict, list]:
        """The live hail swath layers for the map (website/swath.py; --storm-layers only): the newest 60-minute and
        24-hour pictures, and their live files in hail/live/<window>/<stamp>/ (D14). Returns (the two layers for
        data/map.json, hail_60 and hail_1440, and the plain-words lines for the List and the panel). One status
        line for both layers, named "Hail swath (radar estimate)": it is ok only when both are fresh."""
        from . import swath as sw
        fetch = getattr(self.f, "binary", None)
        get = fetch if fetch else (lambda url, headers=None: (None, "no downloader"))
        frames, _files, states = sw.collect(self.now, None, out_dir, towns, get=get, sample=sample)
        blocks = sw.map_data_swath(frames)
        pieces = []
        for product in sw.PRODUCTS:
            block, frame = blocks[product.key], frames[product.key]
            # the legend's stops carry their size in inches with the class word (every colour with its word)
            block["legend"] = [{**e, "label": f"{e['value']:.2f} in, {e['label']}"} for e in block["legend"]]
            block["legend_uncoloured"] = sw.WORDS_SWATH["uncoloured"].format(window=product.window_word)   # its own line (map.css)
            block["window_word"] = product.window_word
            block["kind"] = "hail_swath"             # map.js: the layer's kind (its frame is "hail_swath" too)
            block["words"].update(SWATH_SITE_WORDS)
            pieces.append(self._swath_status(product, frame))
        ok = all(s["ok"] for s in states.values())
        self.note("hail_swath", sw.LABEL, ok, "; ".join(pieces),
                  words=None if ok else sw.WORDS_SWATH["all_clear"])
        lines = [{"title": sw.PRODUCT_BY_KEY[key].title, "lines": sw.describe(frames[key], self.now, towns)}
                 for key in ("hail_60", "hail_1440")]
        return blocks, lines

    @staticmethod
    def _swath_status(product, frame: dict) -> str:
        """One layer's part of the status line, in plain words: its state and when its file was made."""
        if frame.get("state") == "unavailable":
            return SWATH_SITE_WORDS["status_unavailable"].format(title=product.title, problem=frame.get("problem"))
        key = "status_stale" if frame.get("state") == "stale" else "status_fresh"
        return SWATH_SITE_WORDS[key].format(title=product.title, valid=frame["valid_text"], age=frame["age_min"],
                                            limit=int(product.fresh.total_seconds() // 60))

    def hail(self, out_dir: Path, sample: bool, store: str | None, towns: list, addresses: bool = False,
             address_text: str = "on") -> dict:
        """The five-year hail history (website/hail.py; --hail-history only). The store's hail/ files are copied
        into the site, and each town gets its words (town["hail"]). One status line, like the others: a store
        that doesn't load is a failed source, the pages say so in words, and the build goes on (--require-live
        then fails). Returns the map.json block. The copy is made only after the store's manifest checks out."""
        sampled = sample and store is None          # the SAMPLE fixture only; a --hail-store file is real data
        through = None                              # the newest grid day the store holds (the climate block)
        index, problem = None, None
        try:
            index = hail_store(out_dir, store, sample, self.f, addresses)
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
            if index.get("asset"):                  # the release asset the download took (the branch's, else main's)
                detail += f", from {index['asset']}"
            stale = not sampled and hs.is_stale(index["as_of"], self.now)    # a real store older than STALE_DAYS
            if stale:                               # the pages carry it with the stale line; the source counts as failed
                detail += f" (stale: more than {hs.STALE_DAYS} days old, the daily job has not published)"
            self.note("hail_history", HAIL_LABEL, not stale, ("SAMPLE store: " if sampled else "") + detail)
            if stale:                               # the map banner (D98(a)): the heading names the age; the sentence keeps what loaded
                self.status["hail_history"].update(heading=hs.WORDS["heading_stale"], sentence=hs.WORDS["stale_lead"].format_map(
                    {"as_of": hs.fmt_date(date.fromisoformat(index["as_of"]))}))
        except (hs.HailStoreError, OSError, ValueError, KeyError, TypeError) as e:
            problem = str(e) if isinstance(e, hs.HailStoreError) else f"the history files couldn't be read ({type(e).__name__})"
            self.note("hail_history", HAIL_LABEL, False, problem)       # the log keeps the technical detail
            shown = hs.plain_problem(problem)                             # the pages say it in plain words
            # the map banner (D98(a)): a load that failed reads "didn't load", and its sentence is the plain words, capitalised
            self.status["hail_history"].update(heading=hs.WORDS["heading_failed"], sentence=shown[:1].upper() + shown[1:] + ".")
            words = [hs.describe_unavailable(shown) for _ in towns]
            block = hs.map_data_unavailable(shown)
            block.pop("tiles", None)
            block["tile_split"] = {}                # no store, so no tile is known: the map says unavailable, not outside
            from . import joins as jn
            block["joins"] = join_block_unavailable(jn, shown)
            joins_views = [join_view_unavailable(jn) for _ in towns]
            block.update(b5_map_blocks(None))       # every B5 block says unavailable, with the reason
            summaries = [summary_unavailable(shown, t) for t in towns]
        for t, w, jv, s in zip(towns, words, joins_views, summaries):
            t["hail"] = {**w, "joins": jv, "summary": s, "view": history_view(s, jv, w, t, self.now, through)}
        block["words"].update(HAIL_SITE_WORDS)
        block["stale_days"] = HAIL_STALE_DAYS
        block["at_zoom"] = HAIL_AT_ZOOM
        block["tenths_per_mm"] = HAIL_TENTHS_PER_MM
        if addresses:                           # --hail-addresses only (B3): the address, street and outline layers
            block.update(self.layers(out_dir, index, problem, address_text))
        # B6: data/base.json reads the copied store (its base, history and recent folders and the blocks of its index)
        self.hail_index, self.hail_problem = (index, None) if problem is None else (None, problem)
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
    # D110(d) (B6): the credit row carries the same privacy words as the Map page's Imagery description and the About page
    "credit_line": ("Imagery: USDA, USGS, The National Map. Your IP address and the map area you view go to USGS while it "
                    "is on."),
    "failed_line": "Imagery didn't load from USGS. Outlines and towns are still shown."}


def map_data(now: datetime, sample: bool, layers: dict, towns: list, alerts: dict, reports: dict,
             status: dict, hail: dict | None = None, base: dict | None = None) -> dict:
    """Everything the map page draws, as one JSON document (data/map.json). The contract is in
    docs/DESIGN.md ("Interactive map"); website/static/map/map.js reads it. The "hail" block is there only in a
    --hail-history build (Collector.hail): no key otherwise. The "base" pointer (base_pointer) is always there (B6, D125(d)):
    the states, the base map's tile templates and zooms, and the name of data/base.json."""
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
        **(base or {}),                       # B6: base, history_layers, recent and labels (base_pointer)
    }


def _round(v):
    return None if v is None else round(v)


# ---------------------------------------------------------------- the words for the home page's map

def map_card(layers: dict, alerts: dict, towns: list, status: dict, now: datetime) -> dict:
    """The words for the map on the home page (index.html, the map's frame): its title, what it shows
    when it opens and what this update is missing. They follow the data, so a model forecast is never
    called the radar estimate and outlines or town numbers that didn't load are never described as shown
    (AGENTS.md rule 5). The map opens where map.js opens it (setLayer, buildTimeline): the precipitation
    layer's 12h timeline, or its only timeline with frames, at its now_index. Stale radar keeps its frames,
    so the picture is read from the frames, not the status."""
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
    words = _and(shown)
    return {"title": "Montana map: " + (_and(short) if short else "nothing loaded in this update"),
            "shown": words[:1].upper() + words[1:] + "." if words else "",
            "missing": f"Missing from this update: {_and(missing)}. This is not an all-clear." if missing else ""}


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
        return "-"
    dt = value if isinstance(value, datetime) else src.parse_iso(value)
    if dt is None:
        return "-"
    return strftime(dt.astimezone(tz), pattern).replace("AM", "am").replace("PM", "pm")


def env() -> Environment:
    e = Environment(loader=FileSystemLoader(str(HERE / "templates")), autoescape=select_autoescape(["html"]),
                    trim_blocks=True, lstrip_blocks=True)
    e.filters["t"] = lambda v, p="%-I:%M %p": fmt_time(v, p)
    e.filters["when"] = lambda v: fmt_time(v)
    e.filters["day"] = lambda v: fmt_time(v, "%a %b %-d")
    e.filters["num"] = lambda v: "-" if v is None else f"{round(v)}"
    e.filters["ago"] = src.age_words
    e.filters["feet"] = lambda v: "-" if v is None else f"{round(v):,}"
    return e


# ---------------------------------------------------------------- build

# Files the pages load with ?v=<content hash>: a file keeps its address until its bytes change, so
# browsers and GitHub Pages reuse the unchanged ones across the 10-minute rebuilds (map.js, map.css,
# the 377 KB basemap and style.css change only with the code). data/map.json and the map card's
# address change every build, so they keep the build minute.
VERSIONED = ("style.css", "veor.css", "map/map.js", "map/map.css", "map/basemap.json")


STORM_JS = "map/storm.js"   # places the storm text in the Map's List and town sheets; --storm-layers only
# Feeds listed on the About page only in a --storm-layers build (their words and layers ship with the flag)
STORM_CONTRACTS = ("storm_levels", "satellite", "hail_swath")

# The five-year hail history (--hail-history only; website/hail.py holds the words and the store format)
HAIL_LABEL = "Hail history (radar estimates)"        # the status line's name
# the joined records (B2, website/joins.py) are on the About page only in a --hail-history build, with the store
JOIN_CONTRACTS = ("lsr", "ncei_storm_events", "swdi_nx3hail", "nws_warnings_polygons", "nws_zone_products",
                  "asos_daily_gusts")
ADDRESS_TEXT_MODES = ("on", "off")                 # --address-text (D35): off writes no address text at all
# the B5 feeds (sources.py rows, B5 brief): on the About page only in a --hail-history build. census_tiger_counties
# is the TIGER 2026 county file (B5); census_counties is the 1:500,000 county file of the outline counts (B3)
B5_CONTRACTS = ("nclimgrid_daily", "nohrsc_season_snowfall", "ghcn_daily", "iem_watchwarn", "iem_ugcs", "iem_lsr",
                "nwps_gauges", "usgs_water_api", "census_tiger_counties", "roof_references")   # the order of sources.py's rows
# the B6 feeds (sources.py rows, the B6 integration notes): the base map (terrain, vectors, landmark points), the five-year
# pictures, the zone counts and the recent radar hail. On the About page only in a --hail-history build; the rows sit before
# the B5 rows in sources.py, which the B5 order test keeps last.
B6_CONTRACTS = ("terrain_shading", "terrain_land_cover", "base_reservations", "base_roads", "base_places", "base_forests",
                "base_parks", "base_water", "base_summit_names", "base_summit_heights", "nces_public", "nces_private",
                "usgs_hospitals", "hifld_hospitals", "faa_nasr", "usgs_fire", "padus_local", "tiger_park", "fema_worship",
                "history_pictures", "history_zone_counts", "recent_radar_cells", "bubble_anchors")
HAIL_CONTRACTS = ("hail_history",) + JOIN_CONTRACTS + B5_CONTRACTS + B6_CONTRACTS  # on the About page only in a --hail-history build
# Words map.js fills that hail.WORDS doesn't hold: a shard that didn't load (the unavailable line's problem)
HAIL_SITE_WORDS = {"fetch_failed": "the history for this spot didn't load in this update"}
HAIL_STALE_DAYS = hs.STALE_DAYS    # map.js: an as_of older than this (in days) shows the stale line
HAIL_AT_ZOOM = 9                   # map.js: ?at=lat,lon opens at this zoom, or the current one if it is higher
HAIL_TENTHS_PER_MM = 10            # map.js: the store's tenths of a millimetre, for the millimetre text

# The hail swath layers (B4, --storm-layers only): the words the Map page shows that website/swath.py does not hold.
# map.js fills the {placeholders} from data/map.json "words" (the module's WORDS_SWATH and these), and writes none.
SWATH_SITE_WORDS = {
    "list_heading": "Hail swath (radar estimate)",
    "hatch_key": "No radar coverage",                    # the legend key for hatched cells (-3 in the product)
    "hatch_note": "Hatched areas have no radar coverage.",
    "hatch_key_out": "No radar coverage on this map",    # hatched cells with the band outside the picture in view
    "hatch_note_out": "Hatched areas have no radar coverage on this map.",
    "no_picture": "No picture in this update.",          # the timeline when the layer has no picture at all
    "live_loading": "Loading the live radar estimate for this spot.",
    "live_failed": "The live radar estimate for this spot could not be loaded. This is not an all-clear.",
    # the status line's parts (joined with "; "; the List and the banner add their own full stop)
    "status_fresh": "{title}: valid {valid}, {age} min ago",
    "status_stale": "{title}: valid {valid}, {age} min ago. That is more than {limit} minutes old, so it may be "
                    "out of date",
    "status_unavailable": "{title}: {problem}",
    "sample_credit": "SAMPLE: invented values, not NOAA data.",   # a sample build's List and panel
}


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
        index, url = hs.fetch_store_any(fetch.binary, tmp, hs.store_urls())   # the branch's asset, else main's
        index = dict(index, asset=url.rsplit("/", 1)[-1])
        return _copy_hail(Path(tmp), out, index, addresses)


B3_FOLDERS = ("a", "b", "r")     # the store's address, outline and road folders (B3): copied only with --hail-addresses
B3_FILES = ("counts.json",)      # the store's outline counts (buildings.py, B3): copied only with --hail-addresses
B3_INDEX = (ad.INDEX_KEY, st.INDEX_KEY, bd.INDEX_KEY)   # the index blocks the B3 modules write (addresses, roads, buildings)


# The store's folders the site copies (B2 and B5). hail/j/ holds the joined records and hail/j/e/ the per-tile event files
# (D30); hail/n/ (the snow analysis) is copied only when the index's snow block says it is shown (D7, D23).
HAIL_FILES = ("index.json", "manifest.json")
HAIL_FOLDERS = ("t", "j", "z", "s")              # B2: shards, joined records (with j/e), zone and station files
HAIL_FOLDERS_B5 = ("c", "sd", "g", "k", "tl")    # B5: grid tiles, station files, gauges, county files, station tile lists
# B6 (D125(d)): the base map (terrain tiles, band files, landmark shards, peaks, places, the zone outline file and the base
# index), the five-year pictures, the zone counts and the recent cells. A folder the store lacks is copied as nothing, and the
# data files say so (base_document): the copy never fails for a missing B6 folder.
HAIL_FOLDERS_B6 = ("base", "history", "recent")




def snow_shown(index: dict) -> bool:
    """True when the store's snow block says the analysis is shown (its unit check passed, D7)."""
    block = index.get("snow") if isinstance(index, dict) else None
    return isinstance(block, dict) and block.get("shown") is True


def _copy_hail(root: Path, out: Path, index: dict, addresses: bool = False) -> dict:
    """Copy the store's hail/ files into the site as out/hail/: the B2 folders, the B5 folders (c, sd, g, k, tl; j/e comes with
    j), the B6 folders (base, history, recent; each only when the store holds it), and hail/n only when the snow block says it
    is shown (D7, D23). The B3 folders and files (a, b, r, counts.json) are
    copied only with --hail-addresses (default off, D35); any other folder is not copied.
    The copy's manifest lists only the files it carries: a build without the flag carries no B3 file, folder, manifest
    entry or index block (the index is written again without them and its manifest entry is updated). The manifest is
    checked first, and the copy is checked against the manifest it was written with (hail.check_manifest). A store without
    a B5 folder (a B2-only store) copies what it has, and the pages say which part is unavailable. build() writes the swath's live files (hail/live, B4) after this copy: the manifest check at the end of this function runs first and refuses any file under hail/ that the store's manifest does not list, so the live files must not exist yet."""
    # D92(a), D75(a): the source may be a built site's own hail/ folder (the parity step reads _site as its store), which holds
    # B4's hail/live files; allow_live skips only those. The copy takes only the listed folders, and its own check stays strict.
    hs.check_manifest(root, allow_live=True)
    names = set(HAIL_FILES) | set(HAIL_FOLDERS) | set(HAIL_FOLDERS_B5) | set(HAIL_FOLDERS_B6)
    if snow_shown(index):
        names.add("n")
    if addresses:
        names |= set(B3_FOLDERS) | set(B3_FILES)
    (out / "hail").mkdir(parents=True)
    for name in sorted(names):
        source = root / "hail" / name
        if source.is_dir():
            shutil.copytree(source, out / "hail" / name)
        elif source.is_file():
            shutil.copy2(source, out / "hail" / name)
    manifest_path = out / "hail" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def carried(rel: str) -> bool:
        parts = rel.split("/")
        return len(parts) > 1 and parts[1] in names

    manifest["files"] = {rel: entry for rel, entry in manifest.get("files", {}).items() if carried(rel)}
    kept = index
    if not addresses and any(key in index for key in B3_INDEX):
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
    "show_all": sm.SHOW_ALL,
    "reason_no_store_joins": "the joined records are not in this history store",
}
JOIN_SHOW_FIRST = 10          # rows a section shows before "show all" (the sheet and the town tables)
JOIN_HERE_MILES = 0.05        # nearer than this to a report, no bearing is shown (joins._place_bits)
JOIN_SPC_HOURS = 12           # an SPC report day starts at 12:00 UTC (joins.spc_day)
JOIN_HUNDREDTHS = 100         # detection sizes are stored in hundredths of an inch (joins._joins_for_tile)
JOIN_HAIL_UNIT = "in"         # the unit a hail magnitude is written in (joins.LSR_UNITS)
JOIN_UNIT_WORDS = {"mph": "magnitude_mph", "kt": "magnitude_kt"}   # unit -> the words key that shows it
JOIN_HEADS = sm.JOIN_HEADS                   # the town tables' one column: the row labels of D3 (summary.py holds it)
# the section each joined part's lines are notes of (D82(d)): the freshness lines of detections and warnings, the NCEI flood
# cause line and the unplaced records, the zone-switch, unplaced and county (no county product) lines, the station flag and the
# implausible-count line. A part with no line in describe_joins (reports) has no entry. The browser reads it from the joins block.
JOIN_PART_SECTIONS = sm.PART_SECTIONS         # summary.py holds the map (section_data.part_sections reads it too)
# the lines that belong to a part of their own although describe_joins writes them in another part's section (the county
# product lines and the fire-zone lines sit in the zones section); each is matched by its words (joins.WORDS_JOINS)
JOIN_OWN_LINES = sm.JOIN_OWN_LINES


_line_pattern = sm._line_pattern
_line_part = sm._line_part
join_view = sm.join_view


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
                  "unit_words": dict(JOIN_UNIT_WORDS), "show_first": JOIN_SHOW_FIRST, "part_sections": dict(JOIN_PART_SECTIONS),
                  "partial": dict(store.get("partial", {})), "zone_names": dict(store.get("zone_names", {})),
                  "counts": {key: int(store.get(key, 0)) for key in JOIN_COUNTS},
                  "fire_state": store.get("fire_zones", {}).get("state", "unavailable")})
    block["words"] = {**block["words"], **JOIN_SITE_WORDS}
    # the zone products the joins could not place (D27): the rows the summary's unplaced statements count (the browser reads them)
    block["zone_unplaced_rows"] = [list(row) for row in store.get("zone_unplaced_rows") or []]
    block["shards"] = {**block["shards"], "fire": JOIN_FIRE_SHARD}
    block["section_order"] = list(JOIN_HEADS)           # the six joined sections in the order the town page shows them
    # the words, codes, switch and formats the browser reads beside the block's words (the values are joins.py's constants)
    block["significance"] = dict(jn.SIGNIFICANCE_LABEL)                    # the label of each significance letter (D41)
    block["kind_words"] = dict(jn.KIND_WORDS)                              # the kind word of each product code (D29)
    block["flood_record_codes"] = list(jn.FLOOD_RECORD_CODES)              # the NCEI codes that count as flood records (D48)
    block["iem_switch"] = jn.IEM_SWITCH.strftime("%Y-%m-%dT%H:%M:%SZ")     # the zone set changes here (D44)
    block["iem_outline_zones"] = list(jn.IEM_OUTLINE_ZONES)                # the zones drawn with the IEM outline before it (D44)
    block["formats"] = {"joins": jn.FORMAT, "events": jn.EVENTS_FORMAT, "events_tile": jn.TILE_EVENTS_FORMAT,
                        "zone": jn.ZONE_FORMAT, "fire": jn.ZONE_FORMAT, "county": jn.COUNTY_FORMAT,
                        "station": jn.STATION_FORMAT, "towns": jn.TOWNS_FORMAT}   # the "f" each file carries (the browser checks it)
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
            # D56: the town page's station picks and gust station run at the town point, not at the grid cell's centre
            words = jn.describe_joins(index, tile, row, col, now, sample=sample, store_dir=out, events=events,
                                      spot=(t["lat"], t["lon"]))
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


# ---------------------------------------------------------------- the five-season history (B5; --hail-history only)
# summary.py holds the table, the roof lines and their sentences; the functions here join them with the joined records
# (joins.describe_joins), the radar words (hail.describe) and the river gauge into the town page's view, and build the
# map.json blocks the browser fills. Every word the page shows is written in Python (AGENTS rule 4).

HISTORY_SHOW_FIRST = 10     # rows a section shows before its "show all" (the joined tables' count)
HISTORY_WORDS = {
    "unavailable": "Weather history could not be loaded in this update: {problem}. That is not the same as no weather history. This is not an all-clear.",
    "outside": "This spot is outside Montana, so the weather history does not cover it.",
    "no_reason": "No reason was recorded for this value in this update.",
    "show_all": sm.SHOW_ALL,
    "town_title": "Five years of weather at {town}",
    # the radar rows are for the radar cell (hail.CELL_DEG), the grid rows for the 1/24 degree grid cell (climate.py's words)
    "cell": ("The radar rows are for the radar cell at the town's centre, about 0.7 miles north to south and 0.5 miles east "
             "to west. The grid rows are for the grid cell there, about 4.6 km north to south and about 3 km east to west. "
             "Each station row names its station and its distance from this spot."),
    "footnotes": "Why a cell reads Data unavailable",
    "table_caption": "Five seasons, July to June, at {town}: each row names its kind of record and its unit.",
    "gauge_label": sm.GAUGE_ROW,
    "reference_label": "Reference",
    "times": sm.TIMES_NOTE,
}
HISTORY_SECTIONS = sm.SECTION_ORDER          # the eleven sections in the brief's order (summary.py holds the tuple)
# the kind label, the section rules and the words that cut a joined row are summary.py's (section_data reads the same ones)
_split_kind = sm._split_kind
_section_of = sm._section_of


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
            "tile_list": "hail/tl/{tile}.json", "tile_list_format": stations.TILE_LIST_FORMAT,
            "canada_reason": stations.CANADA_REASON,
            # the rule's words, and the four verbs of the candidates not read (stations.py's own words, D71 F8)
            "words": {**stations.WORDS, **summary_status_words()}}


def summary_status_words() -> dict:
    """The station status verbs (summary.STATUS_WORDS: stations.py's own function, written once there), for the stations block."""
    from . import summary
    return dict(summary.STATUS_WORDS)


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
    names = dict(counties.get("names") or {})
    # the name without the word County, by the rule joins.py applies to a row's county (the browser's county line and the
    # county products' note read this, so the page never adds a second County)
    return {"state": counties.get("state", "unavailable"),
            "problem": _clear_words(counties.get("reason") or (None if counties else "the county files are not in this store")),
            "count": counties.get("count"), "names": names,
            "short_names": {code: name.replace(f" {sm.COUNTY_WORD}", "") for code, name in names.items()},
            "tile": "hail/k/{county}.json",
            "words": {k: v for k, v in jn.WORDS_JOINS.items() if k.startswith("county_")}}


# the phone view at zoom 15 with every layer on stays under this many gzip bytes (B5-12, D42, D70, D82(b)): 700,000 bytes. It was
# 650 KB (665,600 bytes) before the browser's sections landed; the sheet's words and sections now come from map.json, and B3's
# tile membership sets are 80,186 bytes gzip (D66), so the budget is restated with that reason and no words or rows are cut.
# The browser and the smoke read it from map.json hail.budget.
PHONE_GZIP_BUDGET = 700_000


def b5_map_blocks(index: dict | None) -> dict:
    """The map.json["hail"] blocks of the five-season history: climate (climate.map_data_climate), summary
    (summary.map_data_summary) and the snow, stations, gauges and county blocks. None gives every block unavailable.
    D40: the climate block lists no tile names; it carries the URL pattern and the compact split map of its tiles, and
    the stations, gauges and county blocks carry their URL patterns only."""
    from . import climate, summary
    climate_block = climate.map_data_climate(index)
    names = climate_block.pop("tile_names", [])
    climate_block["tile_split"] = tile_split(names)
    from . import joins as jn
    summary_block = summary.map_data_summary(index)
    summary_block["section_order"] = list(summary.SECTION_ORDER)   # the eleven ids in the sheet's and the town page's order (D88(i))
    return {"climate": climate_block, "summary": summary_block,
            "snow": snow_map_block(index), "stations": stations_map_block(index),
            "gauges": gauges_map_block(index), "county": county_map_block(index),
            # the sizes the viewer keeps to (B5-12, D30): the phone view's gzip total, and the largest per-tile events file
            "budget": {"phone_gzip_bytes": PHONE_GZIP_BUDGET, "tile_events_gzip_bytes": jn.TILE_EVENTS_BUDGET_GZIP}}


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


def kind_what(town: bool = False) -> dict:
    """The sentence each kind of record opens with on its section (summary.kind_what): the town page's warnings are counted
    at the town point (D38, D71 F4), so its "Warning" sentence says so."""
    return sm.kind_what(town)


# the rows and notes of the sheet and the town page: summary.sheet_rows (one function; D88(p))
history_sections = sm.sheet_rows
_joined_coverage = sm._joined_coverage
_per_season = sm._per_season
_window_lines = sm._window_lines


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
    built = history_sections(s, jv, radar, town_page=True, through=through)
    entries = {sec["id"]: sec for sec in s.get("sections", [])}
    for sid in HISTORY_SECTIONS:
        entry = entries.get(sid, {"heading": W["section_titles"][sid], "lead": "", "kind": ""})
        rows = built["rows"][sid]
        sec = {"id": sid, "heading": entry["heading"], "lead": entry["lead"], "kind": entry["kind"],
               "rows": rows, "notes": built["notes"][sid] if sid != "roof" else [],
               "show_all": H["show_all"].format(n=len(rows))}
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
            "geometry; the 83 zone outlines are the Iowa State copy, simplified, within 0.014 degrees of the NWS file. A product "
            "issued in the changeover week, 7 to 13 September 2022, is placed by the zone set that holds its code."]},
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
            "terms": about_terms(), "terms_lead": TERMS_LEAD, "not_quoted": sm.not_quoted_text(), "citations": sm.citations()}


# ---------------------------------------------------------------- the B6 base map: data/base.json and map.json's pointer
# (D125(d)). map.json carries only the first-paint pointer: each block's state, the base map's as_of, its tile templates
# and zooms, and the name of data/base.json. data/base.json, written by the same build, carries the rest: the three base
# parts (terrain, vector, landmarks) with their words, credit lines, bands, cells, held kinds and sources and budgets; the
# five-year pictures and the zone counts; the recent cells; the label rule and words; the sheet's words; and the budgets.
# The modules' own words (WORDS, CREDIT, the credit lines) are imported; only the sentences no module holds are written here.

BASE_DATA = "data/base.json"                                   # the second data file; map.json names it (D125(d))
BASE_ZOOMS = (tr.ZOOMS[0], tr.ZOOMS[-1])                       # the terrain tiles: zooms 5 to 10 (terrain.ZOOMS)
BASE_TILES = {"h": "hail/base/h/{z}/{x}/{y}.jpg", "l": "hail/base/l/{z}/{x}/{y}.png"}   # the terrain tile files (terrain.py)
LABEL_SHARD_GZIP = 100_000                                     # D66: a building shard, with its bubble flags, stays under this
# The sentences no module holds (rule 5: "Data unavailable" leads, the D20 sentence follows).
BASE_UNAVAILABLE = ("Data unavailable. The base map could not be loaded in this update; that is not the same as no base map. "
                    "This is not an all-clear.")
NO_DATE = "Data unavailable"          # the words for a date the index does not carry (F2, F12): never a count, never "not recorded"
# D110(a), (b), (g) and DESIGN section 13.6: every word the options sheet (#map-options, templates/map.html) shows or sets as an
# attribute. The template takes them as sheet.<key>; data/base.json carries the whole block as its "sheet" key; the browser
# prints only what the page and that block hold (AGENTS.md rule 4; tests/test_site.py pins the keys and the map script's
# silence). A sentence another module already holds is imported, not retyped: the imagery credit line (IMAGERY), the live
# legend notes (gridded.LAYER_TEXT, swath.WORDS_SWATH: DESIGN section 11) and the held church sentence (landmarks.CHURCH_HELD).
SHEET_WORDS = {
    "points_of_interest": "Landmark dots and names, for the kinds chosen above",
    "five_year_history": "Past records from the last five years. Not a forecast.",
    "highlight_recent_hail": "Highlight recent radar hail",
    # F3 (D122(b), D131(c)): the water line for an area whose tile has no band D shard, the vector module's own words
    "water_line_unavailable": b2.WORDS["water_line_unavailable"],
    # F3 (DESIGN section 13.6, item 5): the sub-line the sheet shows under the Landmarks heading
    "landmarks_sub_line": ("Schools, parks, hospitals, airports, and fire and EMS stations, from the public lists named under "
                           "About."),
    # the header, the close button and the group headings
    "options_title": "Map options",
    "close_label": "Close map options",
    "base_heading": "Base map",
    "live_heading": "Live weather",
    "history_heading": "Five-year history",
    "landmarks_heading": "Landmarks",
    # the base map cards, and the labels of the live, five-year and landmark chips
    "map_card": "Map",
    "imagery_card": "Imagery",
    "precipitation": "Precipitation",
    "temperature": "Temperature",
    "wind_gusts": "Wind gusts",
    "hail_last_hour": "Hail, last hour",
    "hail_last_day": "Hail, last 24 hours",
    "hail_history": "Hail",
    "heat_history": "Heat",
    "wind_history": "Wind",
    "flood_history": "Flood",
    "fire_smoke": "Fire and smoke",
    "school": "Schools",
    "park": "Parks",
    "hospital": "Hospitals",
    "airport": "Airports",
    "fire_ems": "Fire and EMS stations",
    "church": "Churches",
    # the kind names inside the landmark line, which opens with them (their lower-case forms, EMS kept)
    "name_school": "schools",
    "name_park": "parks",
    "name_hospital": "hospitals",
    "name_airport": "airports",
    "name_fire_ems": "fire and EMS stations",
    "landmark_line": "{kinds} from the public lists named under About, shown as dots with their names.",
    "list_and": " and ",
    "list_comma": ", ",
    "list_last": ", and ",
    # the chip states: the tag words, the coming and waiting lines, and the reasons a chip opens
    "coming": "Coming",
    "held": "Held",
    "unavailable": lb.UNAVAILABLE_TEXT,
    "coming_fire": "Coming later: fire is not in the map yet.",
    "coming_smoke": "Coming later: smoke is not in the map yet.",
    "waiting": "Turn on Points of interest to show these.",
    "held_church": lm.CHURCH_HELD,
    # base.json did not load: the chips that need it say so (map.json carries states, not sentences)
    "base_failed": ("Data unavailable. The map's details could not be loaded in this update; that is not the same as no hail, "
                    "no landmarks and no base map. This is not an all-clear."),
    # a five-year part that loaded in part: its chip is unavailable with this sentence (a zero may be a missing count)
    "partial_history": ("Data unavailable. Some counts for this layer could not be made in this update, so a zero may mean "
                        "a count is missing. This is not an all-clear."),
    # the legend lines (a chip's data-legend, shown when it is on)
    "legend_precipitation": ("Rate as liquid water. Radar estimate up to now, High-Resolution Rapid Refresh (HRRR) model "
                             "forecast after."),
    "legend_temperature": "HRRR model temperature, in \u00b0F. Town numbers are the National Weather Service (NWS) forecast.",
    "legend_wind": gd.LAYER_TEXT["wind"]["legend_note"],                       # "HRRR model. Roofing limit 25 mph."
    "legend_hail_last_hour": " ".join((sw.WORDS_SWATH["legend_note"].format(window="hour"),
                                       sw.WORDS_SWATH["uncoloured"].format(window="hour"))),
    "legend_hail_last_day": " ".join((sw.WORDS_SWATH["legend_note"].format(window="24 hours"),
                                      sw.WORDS_SWATH["uncoloured"].format(window="24 hours"))),
    "legend_imagery": IMAGERY["credit_line"],                                  # D110(d): the same words as the credit row
    "legend_recent": ("Buildings in cells where radar estimated 1 in or more in the last 30 days are highlighted. Buildings in "
                      "other cells are not; that is not the same as no hail. Radar estimate, not a measurement at the ground."),
    "legend_reports": "No report is not \u201cno hail\u201d.",
    # the switches: each name and its 14 px description
    "points_of_interest_name": "Points of interest",
    "recent_description": "Radar estimate of 1 in or more, last 30 days",
    "warnings": "Warnings",
    "warnings_description": "NWS outlines",
    "storm_reports": "Storm reports",
    "storm_reports_description": "Storm Prediction Center (SPC), last 3 days",
    # Reset
    "reset": "Reset",
    "reset_line": "Back to Map and Precipitation, with Points of interest and Warnings on. Everything else off.",
}
# The words the browser prints from the first paint, outside the sheet: the map page's banners and the reports and picture
# lines. The template renders them as JSON in <script id="map-words"> (map.html context: map_words), and map.js reads them
# once, so no sentence is a literal in the script (AGENTS.md rule 4; tests/test_site.py pins the keys and the values).
# A {name} is filled by the script from the data (a layer's title, a detail), never by a word of its own.
PAGE_WORDS = {
    "reports_failed": "<strong>Storm reports didn't all load</strong> ({detail}). ",
    "reports_none": "No SPC storm reports in or near Montana in the last 3 days. ",
    "no_reports": "No reports. ",
    "nothing_to_show": "Nothing to show for {layer}",
    "no_layer_pictures": "No {layer} pictures in this update{why}. This is not an all-clear.",
    "no_layer_picture": "No {layer} picture in this update. This is not an all-clear.",
    "radar_reason": "radar: {detail}",
    "satellite_reason": "satellite: {detail}",
    "forecast_reason": "model forecast: {detail}",
}
# The sheet's words the browser needs before data/base.json has answered: its chips' reasons and notes, the waiting line
# and the landmark list joins.
FIRST_PAINT_SHEET = ("base_failed", "unavailable", "held", "waiting", "partial_history", "list_and", "list_comma", "list_last")
MAP_WORDS = {**PAGE_WORDS, **{key: SHEET_WORDS[key] for key in FIRST_PAINT_SHEET}}
# D141 (the About words of this round): fixed sentences the About page prints that no module holds. The held sentences and
# the partial bubble sentence are the modules' own (landmarks, labels); tests/test_site.py pins the About text against them.
TERMS_LEAD = "Each line below quotes the source's own words where the build read them, and says so where it did not."
WATER_AROUND = ("Where an area's detailed water did not load, the statewide lakes and rivers still show, and the map's "
                "information sheet says:")
ZONES_WHAT = hl.ZONES_WHAT          # one source for the eight measures (D141(c))
# D110(c), D135(a), D138(a): the bubble's one legend text. It must equal history_layers.WORDS["label_legend"] (the About page
# and the map's labels carry this copy; tests/test_site.py pins the equality)
BUBBLE_LEGEND = (f"{lb.DASH} means {lb.UNAVAILABLE_TEXT}: no radar estimate of 0.25 in or more was stored for this cell; that "
                 "is not zero and not an all-clear.")
# the reasons a part gives when the copy lacks its files (plain words; the data file keeps them as "reason"; no printed
# sentence carries them, D138(b): a printed sentence for a missing part is history_layers' WORDS["missing"])
REASON_NO_STORE = "this build does not include the hail store"
REASON_NO_BASE = "the store has no base map files"
REASON_NO_HISTORY = "the store has no five-year picture files"
REASON_NO_RECENT = "the store has no recent radar hail files"
REASON_NO_LABELS = "the store has no bubble values"


def _json_file(path: Path):
    """A JSON file of the copy, or None when it is absent or cannot be read (its block then says why)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _shard_names(folder: Path) -> list[str]:
    """The shard names a folder of the copy holds, sorted (the band cells and the band D tiles); none when it is absent."""
    return sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []


def _first_paint(block: dict) -> dict:
    """A block's entry in map.json: its state only (the words and the reasons are in data/base.json)."""
    return {"state": block["state"]}


def _safely(build, fallback, what: str) -> dict:
    """A block that cannot be read gives its unavailable block with the reason, so one part fails alone (D16, D20)."""
    try:
        return build()
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OSError) as e:
        return fallback(f"{what} ({type(e).__name__})")


def _part(build, unavailable, what: str) -> dict:
    """One base part through its module's map function. A part that cannot be read gives the module's unavailable block with
    the reason, and the other parts still build (D16, D20)."""
    try:
        return build()
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        block = unavailable()
        block["reason"] = f"the {what} could not be read ({type(e).__name__})"
        return block


PAD_US_VECTOR = "padus"                        # basemap2's source key for the PAD-US fee layer (its park outlines; padus_features)
PAD_US_READ = ("fetched", "cache", "partial")   # the basemap2 source states that mean the layer was read (source_states)
HOSPITAL_SENTENCE = {"usgs_hospitals": lm.WORDS["hospital_usgs"], "hifld_hospitals": lm.WORDS["hospital_hifld"]}
# T5 (D134(b)): a credit line prints only for a source the store read. A terrain layer is read when its index state is loaded
# or partial; a vector source when basemap2 lists it fetched, cache or partial (PAD_US_READ names the same states); a landmark
# source when it is shown (loaded, with rows kept: landmarks.describe_landmarks). basemap2.CREDIT holds one line per vector
# source in this order, so its seven lines unpack here (a change to the tuple fails at import).
TERRAIN_READ = ("loaded", "partial")
TERRAIN_LINES = {"h": ("shading", "Relief: "), "l": ("land_cover", "Land cover: ")}   # the credit key and the labelled form
VECTOR_READ = PAD_US_READ
TIGER_LINE, PL2020_LINE, FOREST_LINE, PADUS_VECTOR_LINE, NHD_LINE, GNIS_LINE, DEM_LINE = b2.CREDIT
# each vector credit line and the index keys of the sources it names; the line prints when one of them was read
VECTOR_LINE_SOURCES = (
    (TIGER_LINE, ("tiger_aiannh", "tiger_prisec", "tiger_place")),
    (PL2020_LINE, ("census_pl2020",)),
    (FOREST_LINE, ("edw",)),
    (PADUS_VECTOR_LINE, ("padus",)),
    (NHD_LINE, ("nhd_small_lines", "nhd_small_areas", "nhd_large_lines", "nhd_large_areas")),
    (GNIS_LINE, ("gnis",)),
    (DEM_LINE, ("3dep",)),
)


def read_vector_lines(rows) -> list[str]:
    """The vector credit lines whose sources the store read (T5, D134(b)). rows is the vector part's "sources", keyed by source:
    a source that is absent, or that basemap2 did not read, names no line. The lines come in basemap2.CREDIT's order."""
    rows = rows if isinstance(rows, dict) else {}
    return [line for line, keys in VECTOR_LINE_SOURCES
            if any(isinstance(rows.get(key), dict) and rows[key].get("state") in VECTOR_READ for key in keys)]


def terrain_line(terrain, name: str) -> str | None:
    """A terrain layer's credit line in the labelled form the module gives ("Relief: ...", "Land cover: ...") when the store read
    the layer and the module names its source; None otherwise (T5, D134(b)). terrain is the terrain part's block (terrain.map_data)."""
    key, label = TERRAIN_LINES[name]
    layer = ((terrain or {}).get("layers") or {}).get(name)
    line = ((terrain or {}).get("credits") or {}).get(key)
    read = isinstance(layer, dict) and layer.get("state") in TERRAIN_READ
    return line if read and isinstance(line, str) and line.startswith(label) else None


def _entry(block, key: str) -> dict:
    """The row of one source in an index block's "sources" (an absent or non-dict row is an empty dict)."""
    rows = block.get("sources") if isinstance(block, dict) else None
    row = rows.get(key) if isinstance(rows, dict) else None
    return row if isinstance(row, dict) else {}


def landmark_line(key: str, as_of) -> str:
    """A landmark source's credit line (landmarks.SOURCES) with its own date (F2): the FAA cycle, or the layer's last edit, as
    the index's as_of gives it. Where the index carries no date the date reads Data unavailable; no line says a date was
    not recorded."""
    text = lm.SOURCES[key]["credit"]
    if "{when}" not in text:
        return text
    if key == "faa_nasr":
        when = f"cycle effective {as_of}" if as_of else NO_DATE
    else:
        when = f"layer last edited {as_of}" if as_of else NO_DATE
    return text.format(when=when)


def _landmark_words(base_index: dict | None, vector_block: dict | None) -> dict:
    """The landmark words that data/base.json and the About page carry (F1, F2, F10; D130(b)).
    sources: the credit line of each landmark source the store read and shows, the list describe_landmarks picks, with this
    module's date words (landmark_line). hospital: the hospital source the store used, read from kinds.hospital.sources, which
    names a source only when the kind loaded, so a source that was tried and not used is never named; its sentence is the
    landmarks module's words for that source (or the unavailable words), and its credit is that source's line and no other.
    credits: the FAA line, printed only when its source was read, and the PAD-US line, printed when either part read the
    layer (the landmark list, or the park outlines in the vector part). lines: the credit line of each shown source,
    by its key (the About page's school and fire lines, T5).
    """
    block = base_index.get(lm.INDEX_KEY) if isinstance(base_index, dict) else None
    block = block if isinstance(block, dict) else {}
    kinds = block.get("kinds") if isinstance(block.get("kinds"), dict) else {}
    hospital_kind = kinds.get("hospital") if isinstance(kinds.get("hospital"), dict) else {}
    shown = [key for key in lm.ORDER + ("hifld_hospitals",)
             if key not in lm.HELD_SOURCES and _entry(block, key).get("state") == "loaded" and _entry(block, key).get("kept")]
    lines = {key: landmark_line(key, _entry(block, key).get("as_of")) for key in shown}
    listed = hospital_kind.get("sources") if isinstance(hospital_kind.get("sources"), list) else []
    used = [key for key in listed if key in HOSPITAL_SENTENCE] if hospital_kind.get("state") == "loaded" else []
    source = used[0] if len(used) == 1 and used[0] in lines else None
    padus_read = "padus_local" in lines or _entry(vector_block, PAD_US_VECTOR).get("state") in PAD_US_READ
    padus = lines.get("padus_local") or (
        landmark_line("padus_local", _entry(block, "padus_local").get("as_of")) if padus_read else None)
    return {"sources": [lines[key] for key in shown], "lines": lines,
            "hospital": {"state": "loaded" if source else "unavailable", "source": source,
                         "sentence": (HOSPITAL_SENTENCE[source] if source else
                                      lm.WORDS["kind_unavailable"].format(plural=lm.KIND_PLURAL["hospital"])),
                         "credit": lines.get(source) if source else None},
            "credits": {"faa_nasr": lines.get("faa_nasr"), "padus": padus}}


def _base_block(out: Path, base_index: dict | None, why: str | None) -> dict:
    """The base map: its three parts, each through its module's own map function (terrain.map_data, basemap2.map_data_vector,
    landmarks.map_data_landmarks), which give the module's unavailable block and words for a part the index lacks."""
    terrain_block = (base_index or {}).get("terrain")          # the part's key in hail/base/index.json (terrain.py)
    terrain = _part(lambda: tr.map_data({tr.INDEX_KEY: {"terrain": terrain_block}} if isinstance(terrain_block, dict) else None),
                    lambda: tr.map_data(None), "terrain files")
    vector = _part(lambda: b2.map_data_vector((base_index or {}).get(b2.PRODUCT)), lambda: b2.map_data_vector(None),
                   "vector files")
    landmark_block = (base_index or {}).get(lm.INDEX_KEY)
    vector_block = (base_index or {}).get(b2.PRODUCT)
    landmarks = _part(lambda: lm.map_data_landmarks(base_index or {}), lambda: lm.map_data_landmarks({}), "landmark files")
    landmarks["as_of"] = landmark_block.get("as_of") if isinstance(landmark_block, dict) else None
    # F1, F2, F10 (D130(b)): the credit lines, the hospital source the store used, and the words the About page prints for them
    landmarks.update(_landmark_words(None if landmarks["state"] == "unavailable" else base_index, vector_block))
    states = [terrain["state"], vector["state"], landmarks["state"]]
    if all(s == "loaded" for s in states):
        state = "loaded"
    elif any(s in ("loaded", "partial") for s in states):
        state = "partial"
    else:
        state = "unavailable"
    # T5 (D134(b)): the credit lists name the sources the store read, the rule the About page follows
    vector_rows = vector_block.get("sources") if isinstance(vector_block, dict) else None
    if "credit" in vector:
        vector["credit"] = read_vector_lines(vector_rows)
    credit: list[str] = [line for line in (terrain_line(terrain, "h"), terrain_line(terrain, "l")) if line]
    credit += read_vector_lines(vector_rows)
    if landmarks["state"] != "unavailable":
        credit += landmarks["sources"]
    held = (landmark_block or {}).get("held") if isinstance(landmark_block, dict) else None
    cells = {"B": _shard_names(out / "hail/base/v/b"), "C": _shard_names(out / "hail/base/v/c"),
             "D": _shard_names(out / "hail/base/w")} if base_index else {"B": [], "C": [], "D": []}
    reason = None if state != "unavailable" else (why or "none of the base map parts could be read")
    return {"state": state, "problem": BASE_UNAVAILABLE if state == "unavailable" else None, "reason": reason,
            "as_of": {"terrain": terrain.get("as_of") or None, "vector": vector.get("as_of"), "landmarks": landmarks["as_of"]},
            "sources": {"terrain": _source_dates(terrain_block), "vector": _source_dates(vector_block),
                        "landmarks": _source_dates(landmark_block)},
            "tiles": dict(BASE_TILES), "zooms": list(BASE_ZOOMS), "terrain": terrain, "vector": vector,
            "landmarks": landmarks, "cells": cells, "held": held or {"kinds": {}, "sources": {}}, "credit": credit}


def _source_dates(block) -> dict:
    """Each source of a base part with its date: the as_of its row carries (the terrain layers and the landmark sources carry
    one). A row with no as_of has no date, and its date reads Data unavailable. The vector part's rows carry a file count and a
    byte count, not a date, and basemap2 does not read a source's own release date, so a count or a fetch time is never read
    as a date (F12). A source's state is kept where its row has one; a held source's reason is in the held block."""
    rows = block.get("sources") if isinstance(block, dict) else None
    if not isinstance(rows, dict):
        return {}
    dates = {}
    for key, row in rows.items():
        if isinstance(row, dict):
            entry = {"state": row.get("state"), "as_of": row.get("as_of") or NO_DATE}
            dates[key] = {name: value for name, value in entry.items() if value is not None}
    return dates


# D136(a): the names history_layers gives its five-year parts in its own unavailable sentences (its index's problem words:
# history_layers.py lines 973, 976, 1037 and 1074). The About page formats WORDS["unavailable"] with these names, and, for a
# part the index recorded no reason for, WORDS["missing"] (D138(b)). history_layers' title words (hail1_title, heat90_title,
# recent_title, zones_title) name the same parts in its titles; the names here are kept as they are.
HISTORY_WHAT = {"hail1": "The five-year hail picture", "heat90": "The days at or above 90 F picture",
                "recent": "The recent radar hail list", "zones": "The zone counts"}


def _index_failures(block) -> list[dict]:
    """The failures the index recorded for a block: its {part, reason} rows, where "all" is a failure of the whole layer. The
    About page formats each part's unavailable sentence with the reason the index gave it (D136(a))."""
    rows = block.get("failures") if isinstance(block, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def _history_block(out: Path, store_index: dict | None, why: str | None) -> dict:
    """The five-year pictures and the zone counts: the store index's history_layers block, the picture sidecar (the classes,
    words and bounds) and zones.json (the eight measures and the newest-warning date with its words)."""
    block = (store_index or {}).get(hl.INDEX_KEY)
    if not isinstance(block, dict) or block.get("state") not in ("loaded", "partial"):
        # D138(b): with no problem recorded the sentence names the part only; the copy's reason (why) stays in the data file
        problem = block.get("problem") if isinstance(block, dict) else None
        return {"state": "unavailable", "reason": why, "failures": _index_failures(block),
                "problem": problem or hl.WORDS["missing"].format(what="The five-year history layers")}
    sidecar = _json_file(out / hl.SIDECAR_PATH) or {}
    zones_doc = _json_file(out / hl.ZONES_PATH) or {}
    pictures = {}
    for key, path in (("hail1", hl.HAIL1_PATH), ("heat90", hl.HEAT_PATH)):
        info = (sidecar.get("pictures") or {}).get(key) or {}
        if info.get("state") == "loaded":
            pictures[key] = {"url": path, "state": "loaded", "width": info["width"], "height": info["height"],
                             "bounds": sidecar.get("bounds"), "classes": info["classes"], "window": info["window"],
                             "words": info["words"]}
        else:
            pictures[key] = {"url": path, "state": "unavailable",
                             "problem": info.get("problem") or hl.WORDS["missing"].format(what=HISTORY_WHAT[key])}
    zones_block = block.get("zones") or {}
    zones = {"state": zones_block.get("state", "unavailable"), "url": hl.ZONES_PATH}
    if zones_block.get("state") in ("loaded", "partial") and zones_doc:
        zones.update(measures=zones_doc.get("measures"), newest_warning=zones_doc.get("newest_warning"),
                     words=zones_doc.get("words"), unavailable=zones_doc.get("unavailable"),
                     missing_zone_files=zones_doc.get("missing_zone_files"))
    else:
        zones["problem"] = zones_block.get("problem") or hl.WORDS["missing"].format(what="The zone counts")
    outlines = block.get("outlines") or {}
    outline = {"state": outlines.get("state", "unavailable"), "url": hl.OUTLINE_PATH, "credit": hl.WORDS["about_outlines"]}
    if outline["state"] not in ("loaded", "partial"):
        outline["problem"] = outlines.get("problem") or hl.WORDS["outline_unavailable"]
    return {"state": block["state"], "problem": block.get("problem"), "as_of": block.get("as_of"),
            "window": block.get("window"), "stale": sidecar.get("stale"), "pictures": pictures, "zones": zones,
            "outlines": outline, "failures": _index_failures(block)}


def _recent_block(store_index: dict | None, why: str | None) -> dict:
    """The recent radar hail cells: the store index's recent block (the window, the as_of, the stale sentence and the words).
    The cells themselves are in hail/recent/cells.json, which the copy holds and the browser reads."""
    block = (store_index or {}).get(hl.RECENT_KEY)
    if not isinstance(block, dict) or block.get("state") not in ("loaded", "partial"):
        problem = block.get("problem") if isinstance(block, dict) else None
        return {"state": "unavailable", "reason": why,
                "problem": problem or hl.WORDS["missing"].format(what="The recent radar hail list")}
    return {"state": block["state"], "problem": block.get("problem"), "url": hl.RECENT_PATH, "as_of": block.get("as_of"),
            "window": block.get("window"), "stale": block.get("stale"), "cells": block.get("cells"), "days": block.get("days"),
            "floor_tenths": block.get("floor_tenths"), "words": block.get("words")}


def _label_words() -> dict:
    """The labels words block: the glyph, the unavailable words, the legend line (D110(c)) and the sentence that says what a
    bubble value is (D141(d): history_layers' label_what, which the About page prints before the legend; None only if the
    module drops the key, and tests/test_site.py pins it)."""
    return {"dash": lb.DASH, "unavailable": lb.UNAVAILABLE_TEXT, "legend": BUBBLE_LEGEND, "what": hl.WORDS.get("label_what")}


def _labels_block(store_index: dict | None, why: str | None) -> dict:
    """The bubble rule and its words (labels.py): the glyph, the unavailable words and the legend line (D110(c)); the shard
    budgets (D66) and the buildings module's raw split threshold."""
    block = (store_index or {}).get(lb.INDEX_KEY)
    words = _label_words()
    budget = {"shard_gzip": LABEL_SHARD_GZIP, "shard_raw_split": bd.SHARD_BYTES}
    if not isinstance(block, dict) or block.get("state") not in ("loaded", "partial"):
        problem = block.get("problem") if isinstance(block, dict) else None
        return {"state": "unavailable", "reason": why, "zooms": list(lb.ZOOMS), "rule": {}, "words": words, "budget": budget,
                "problem": problem or hl.WORDS["missing"].format(what="The bubble values on the building outlines")}
    rule = {k: v for k, v in (block.get("rule") or {}).items() if k != "words"}     # the module's legend is replaced (D110(c))
    return {"state": block["state"], "problem": block.get("problem"), "zooms": list(lb.ZOOMS), "rule": rule,
            "words": words, "budget": budget}


def _budget_block(base_index: dict | None) -> dict:
    """The budgets the browser and the smoke read (D125(d)): the base tiles' statewide bytes against their budget, the per-band
    budgets (basemap2's own figures) and the landmark shard budget. The phone budget stays in map.json (hail.budget)."""
    terrain_budget = ((base_index or {}).get("terrain") or {}).get("budget") or {}
    landmark = ((base_index or {}).get("landmarks") or {}).get("budget") or {}
    return {"base_tiles": {"zooms": "5 to 10", "bytes": terrain_budget.get("bytes"), "limit_bytes": tr.BUDGET_BYTES,
                           "under_budget": terrain_budget.get("under_budget")},
            "bands": ((base_index or {}).get("vector") or {}).get("budgets"),
            "landmark_shard": {"limit_gzip": lm.BUDGET_GZIP, "largest_gzip": landmark.get("largest_gzip_bytes")}}


def base_document(out: Path, store_index: dict | None, store_problem: str | None, now: datetime) -> dict:
    """data/base.json (D125(d)), from the copy out/hail/ and the store index. A build without the store (no --hail-history, or
    a store that did not load) or without a B6 folder writes each block as unavailable with its reason, so the file is always
    there with the same keys (the identity rule: the default build and the sample build both carry it)."""
    absent = store_problem or REASON_NO_STORE
    base_index = _json_file(out / "hail" / "base" / "index.json") if store_index is not None else None
    base_index = base_index if isinstance(base_index, dict) else None
    base_why = absent if store_index is None else (None if base_index else REASON_NO_BASE)
    history_why = absent if store_index is None else (
        None if isinstance(store_index.get(hl.INDEX_KEY), dict) else REASON_NO_HISTORY)
    recent_why = absent if store_index is None else (
        None if isinstance(store_index.get(hl.RECENT_KEY), dict) else REASON_NO_RECENT)
    labels_why = absent if store_index is None else (
        None if isinstance(store_index.get(lb.INDEX_KEY), dict) else REASON_NO_LABELS)
    doc = {"version": 1, "built": src._iso(now), "as_of": (store_index or {}).get("as_of"),
           "base": _safely(lambda: _base_block(out, base_index, base_why), lambda r: _base_block(out, None, r),
                           "the base map files could not be read"),
           "history_layers": _safely(lambda: _history_block(out, store_index, history_why),
                                     lambda r: {"state": "unavailable", "reason": r, "problem": hl.WORDS["missing"].format(
                                         what="The five-year history layers")},
                                     "the five-year history files could not be read"),
           "recent": _safely(lambda: _recent_block(store_index, recent_why),
                             lambda r: {"state": "unavailable", "reason": r, "problem": hl.WORDS["missing"].format(
                                 what="The recent radar hail list")},
                             "the recent radar hail files could not be read"),
           "labels": _safely(lambda: _labels_block(store_index, labels_why),
                             lambda r: {"state": "unavailable", "reason": r, "zooms": list(lb.ZOOMS), "rule": {},
                                        "words": _label_words(),
                                        "budget": {"shard_gzip": LABEL_SHARD_GZIP, "shard_raw_split": bd.SHARD_BYTES},
                                        "problem": hl.WORDS["missing"].format(
                                            what="The bubble values on the building outlines")},
                             "the bubble values could not be read"),
           "sheet": dict(SHEET_WORDS), "budget": _budget_block(base_index)}
    return _rule5_blocks(doc)


def _layer_sentence(text: str) -> str:
    """A sentence the browser prints for a layer that did not load carries the words "Data unavailable" (rule 5, D117(b)). A
    sentence that has them is kept; any other (a module's own D20 sentence) is kept after them, unchanged."""
    return text if "Data unavailable" in text else f"Data unavailable. {text}"


def _rule5(block):
    """The rule above, on one block: a block that did not load (state other than loaded) and has a problem sentence gets it."""
    if isinstance(block, dict) and block.get("state") != "loaded" and isinstance(block.get("problem"), str):
        block["problem"] = _layer_sentence(block["problem"])
    return block


def _rule5_blocks(doc: dict) -> dict:
    """Rule 5 on every layer-level sentence of data/base.json: the base map and its three parts, the picture, zone and outline
    blocks, the recent cells and the labels. Only the words "Data unavailable" are added; no module sentence is rewritten."""
    base = doc["base"]
    for block in (base, base["terrain"], base["vector"], base["landmarks"], doc["history_layers"], doc["recent"], doc["labels"]):
        _rule5(block)
    for block in list((doc["history_layers"].get("pictures") or {}).values()) + [doc["history_layers"].get("zones"),
                                                                                doc["history_layers"].get("outlines")]:
        _rule5(block)
    return doc


def base_pointer(doc: dict) -> dict:
    """map.json's first-paint pointer (D125(d)): each block's state, the base map's as_of, its tile templates and zooms, and the
    name of data/base.json. The words stay in that file, so map.json keeps its raw gate (D82(a))."""
    return {"base": {"state": doc["base"]["state"], "as_of": doc["as_of"], "file": BASE_DATA, "zooms": list(BASE_ZOOMS),
                     "tiles": dict(BASE_TILES)},
            "history_layers": _first_paint(doc["history_layers"]), "recent": _first_paint(doc["recent"]),
            "labels": _first_paint(doc["labels"])}


def _sentence_from(text, lead: str) -> str | None:
    """The part of a module's own text that starts at lead, to its end: a legend's closing sentence (the blank-cell sentence
    of heat90_legend, the zero sentence of zones_legend), printed as the module words it (D141(i)). None when the text lacks it."""
    if not isinstance(text, str) or lead not in text:
        return None
    return text[text.index(lead):]


def about_b6_context(doc: dict) -> dict:
    """The words of the B6 About sentences that depend on the built data (--hail-history only; data/base.json, D121(a)).
    Each part of the About page has a credit line, printed only when the store read its source (T5, D134(b)), and an
    unavailable sentence, printed only when the store did not read it (rule 5, D136(a)). A source is read by the states of the
    base index (a terrain layer, a vector source, a landmark kind) or by its block (the five-year pictures, the zone counts,
    the zone outlines and the recent cells). Every unavailable sentence is a module's own words: terrain's and basemap2's
    part names, landmarks' kind plurals, history_layers' WORDS["unavailable"] with the reason the index recorded, or, for a
    part the index recorded no reason for, its WORDS["missing"] with the part's name only (D138(b)), or its outline words.
    The newest-warning sentence of the zone counts is taken from the counted rows (D125(a)); the hospital sentence and credit
    line are those of the source the store used (D130(b)); the FAA and PAD-US lines follow the same rule (F2). The sheet's
    water line is the vector module's words (D134(a)). The held sentences are landmarks' own (D136(a)). The value bubbles
    print the one legend text (D138(a)), and the labels block's own problem sentence when the block is not loaded or partial.
    The 90 F count is read as "counted over" only when its picture was read (D138(c)). D141: the hail legend and its window
    are the picture's index words; the blank-cell and zero sentences are the closing sentences of the module's legends; the
    fixed sentences of the round are this module's constants; the basemap notes and the base map's PAD-US line are basemap2's."""
    base, history = doc["base"], doc["history_layers"]
    labels = doc.get("labels") or {}
    terrain = base.get("terrain") or {}
    landmarks = base.get("landmarks") or {}
    hospital = landmarks.get("hospital") or {}
    lines = landmarks.get("credits") or {}
    shown = landmarks.get("lines") or {}          # the credit line of each shown landmark source, by its key (T5)
    kinds = landmarks.get("kinds") or {}          # each landmark kind's state (landmarks.map_data_landmarks)
    rows = (base.get("sources") or {}).get("vector") or {}      # basemap2's rows: a state for each vector source (T5)
    vector = read_vector_lines(rows)
    zones = history.get("zones") or {}
    pictures = history.get("pictures") or {}
    outlines = history.get("outlines") or {}
    recent = doc.get("recent") or {}
    # the reasons the index recorded for the five-year history, by part ("all" is a failure of the whole layer)
    recorded = {row.get("part"): row.get("reason") for row in history.get("failures") or []}

    def about_terrain(name: str) -> str | None:
        line = terrain_line(terrain, name)
        return None if line is None else "Source: " + line[len(TERRAIN_LINES[name][1]):]

    def about_vector(line: str) -> str | None:
        return line if line in vector else None

    def terrain_read(name: str) -> bool:
        layer = ((terrain or {}).get("layers") or {}).get(name)
        return isinstance(layer, dict) and layer.get("state") in TERRAIN_READ

    def terrain_unavailable(name: str) -> str | None:
        """terrain's sentence for a layer that did not load, with the part name terrain gives it (its LAYER_WORDS)."""
        return None if terrain_read(name) else tr.WORDS["part_unavailable"].format(**tr.LAYER_WORDS[name])

    def vector_read(*keys: str) -> bool:
        """True when the store read one of these vector sources (the states basemap2 gives a file that was read)."""
        return any(isinstance(rows.get(key), dict) and rows[key].get("state") in VECTOR_READ for key in keys)

    def vector_unavailable(kind: str) -> str:
        """basemap2's sentence for one vector part, with the part name basemap2 uses in its index and sheet words."""
        part, one = b2.PART_WORDS[kind]
        return b2.WORDS["part_unavailable"].format(Part=part, one=one)

    def kind_unavailable(kind: str) -> str | None:
        """landmarks' sentence for a kind that did not load, with the plural landmarks uses; None when the kind loaded."""
        loaded = isinstance(kinds.get(kind), dict) and kinds[kind].get("state") == "loaded"
        return None if loaded else lm.WORDS["kind_unavailable"].format(plural=lm.KIND_PLURAL[kind])

    def history_unavailable(part: str, block: dict | None) -> str | None:
        """history_layers' sentence for a five-year part that did not load: its WORDS["unavailable"], formatted with the part's
        name and the reason the index recorded for it (or for the whole layer, "all"). With no reason recorded, the sentence the
        module wrote in the index stands: the part's own problem, else the layer's."""
        reason = recorded.get(part) or recorded.get("all")
        if reason:
            return hl.WORDS["unavailable"].format(what=HISTORY_WHAT[part], reason=reason)
        # D138(b): with no problem in the index, the part's name alone (WORDS["missing"]); a missing part never prints nothing
        return (block or {}).get("problem") or history.get("problem") or hl.WORDS["missing"].format(what=HISTORY_WHAT[part])

    def window_words(window) -> str | None:
        """A window of two ISO dates in the About page's form: October 17, 2021 to October 16, 2026."""
        try:
            first, last = (date.fromisoformat(day) for day in window)
        except (TypeError, ValueError):
            return None
        return f"{first:%B} {first.day}, {first.year} to {last:%B} {last.day}, {last.year}"

    zones_read = zones.get("state") in ("loaded", "partial")
    outline_read = outlines.get("state") in ("loaded", "partial")
    recent_read = recent.get("state") in ("loaded", "partial")
    mrms_read = (pictures.get("hail1") or {}).get("state") == "loaded"
    heat_read = (pictures.get("heat90") or {}).get("state") == "loaded"
    newest = (zones.get("newest_warning") or {}).get("words") if zones_read else None
    heat = (pictures.get("heat90") or {}).get("window")
    return {"relief": about_terrain("h"), "relief_unavailable": terrain_unavailable("h"),
            "land_cover": about_terrain("l"), "land_cover_unavailable": terrain_unavailable("l"),
            "tiger": about_vector(TIGER_LINE),
            "reservations_unavailable": None if vector_read("tiger_aiannh") else vector_unavailable("reservation"),
            "roads_unavailable": None if vector_read("tiger_prisec") else vector_unavailable("route"),
            "places_2020": about_vector(PL2020_LINE),
            "place_unavailable": None if vector_read("tiger_place") and vector_read("census_pl2020")
            else vector_unavailable("place"),
            "forests": about_vector(FOREST_LINE),
            "forests_unavailable": None if vector_read("edw") else vector_unavailable("forest"),
            "padus_credit": lines.get("padus"),
            "pad_us_unavailable": None if vector_read("padus") else vector_unavailable("park"),
            "local_parks_unavailable": kind_unavailable("park"),
            "lakes": about_vector(NHD_LINE),
            "lakes_unavailable": None if vector_read(*dict(VECTOR_LINE_SOURCES)[NHD_LINE]) else vector_unavailable("water"),
            "summits": about_vector(GNIS_LINE),
            "summits_unavailable": None if vector_read("gnis") else vector_unavailable("peak"),
            "heights": about_vector(DEM_LINE),
            "heights_unavailable": None if vector_read("3dep") else vector_unavailable("peak"),
            "public_schools": shown.get("nces_public"), "public_schools_unavailable": kind_unavailable("school"),
            "private_schools": shown.get("nces_private"), "private_schools_unavailable": kind_unavailable("school"),
            "fire_ems": shown.get("usgs_fire"), "fire_ems_unavailable": kind_unavailable("fire"),
            "faa_credit": lines.get("faa_nasr"), "faa_unavailable": kind_unavailable("airport"),
            # the sheet's water line for an area with no detailed water (D134(a)): the vector module's own words
            "water_line": SHEET_WORDS["water_line_unavailable"],
            # the history lines of the B6 folders (hail/history, hail/recent): the pictures (MRMS, nClimGrid), the zone counts
            # (warnings), the zone outlines (ugcs) and the recent cells (MRMS)
            "mrms_pictures": mrms_read, "iem_warnings": zones_read, "nclimgrid": heat_read,
            "ugcs": hl.WORDS["about_outlines"] if outline_read else None,
            "ugcs_unavailable": None if outline_read else hl.WORDS["outline_unavailable"],
            "mrms_recent": recent_read,
            "hail1_unavailable": None if mrms_read else history_unavailable("hail1", pictures.get("hail1")),
            "heat90_unavailable": None if heat_read else history_unavailable("heat90", pictures.get("heat90")),
            "newest": newest or (hl.WORDS["zones_newest_unknown"] if zones_read else None),
            "zone_window": window_words(history.get("window")) if zones_read else None,
            "heat_window": window_words(heat) if heat_read and heat else None,      # D138(c): counted over only when it was read
            "zones_unavailable": None if zones_read else history_unavailable("zones", zones),
            "recent_unavailable": None if recent_read else history_unavailable("recent", recent),
            "hospital_sentence": hospital.get("sentence") or lm.WORDS["kind_unavailable"].format(
                plural=lm.KIND_PLURAL["hospital"]),
            "hospital_credit": hospital.get("credit"),
            # the two held sentences as landmarks words them, printed as they are (D136(a))
            "held_church": lm.CHURCH_HELD, "held_park": lm.WORDS["held_parks"],
            # D138(a): the value bubbles' one legend (the text the map's labels carry too), and the labels block's own problem
            # sentence, printed after the first sentence, when the block is not loaded or partial (its words: _labels_block)
            "bubble_legend": BUBBLE_LEGEND,
            "bubble_unavailable": None if labels.get("state") == "loaded" else (
                labels.get("problem") or hl.WORDS["missing"].format(what="The bubble values on the building outlines")),
            # D141: the five-year sentences from the index words and the module's own legends. The hail legend (with its
            # missing-day sentence) is the picture's index words; its window is the picture's own (October 17, 2021 to
            # October 16, 2026, not seasons). The blank-cell and zero sentences are the closing sentences of the two legends.
            "hail_window": window_words((pictures.get("hail1") or {}).get("window")) if mrms_read else None,
            "hail1_legend": ((pictures.get("hail1") or {}).get("words") or {}).get("legend") if mrms_read else None,
            "heat90_blank": _sentence_from(hl.WORDS["heat90_legend"], "Data unavailable. A blank cell") if heat_read else None,
            "zero_legend": _sentence_from(hl.WORDS["zones_legend"], "A zero means") if zones_read else None,
            "zones_what": ZONES_WHAT,
            "label_what": (labels.get("words") or {}).get("what"),         # the labels words block (D141(d))
            "water_around": WATER_AROUND,
            # D141(h), (k): basemap2's own notes, and the PAD-US line of the base map's credits (the landmarks' line is "padus")
            "peak_note": b2.WORDS["peak_note"], "place_note": b2.WORDS["place_note"], "route_note": b2.WORDS["route_note"],
            "padus_base_credit": about_vector(PADUS_VECTOR_LINE)}

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
    swath_text = None
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
    # the live swath layers (B4) are written after the store copy: the copy's manifest check sees the store's files only
    if storm_layers:
        swath_layers, swath_text = c.swath(out, sample, towns) # hail_60 and hail_1440 (B4)
        layers.update(swath_layers)
    b3 = b3_words(c.b3_index, address_text) if hail_addresses else None
    if b3 is not None:
        b3["attribution"] = hail_block["attribution"]
    road_row = ROAD_ROWS.get(c.road_kind) if hail_addresses else None

    # B6 (D125(d)): data/base.json is built before the pages, so the About page's B6 sentences read the words it holds.
    base_doc = base_document(out, c.hail_index, c.hail_problem, now)
    base = {"built": now, "built_ms": int(now.timestamp() * 1000), "alerts": alerts, "towns": towns,   # the shell's status
            "asset_v": asset_versions(out / "static", VERSIONED + ((STORM_JS,) if storm_layers else ())),
            "status": c.status, "sample": sample, "storm_layers": storm_layers, "satellite_text": satellite_text,
            "swath_text": swath_text, "swath_site": SWATH_SITE_WORDS,
            "hail_history": hail_history, "hail_words": hs.WORDS if hail_history else None,
            "hail_addresses": hail_addresses, "address_text": address_text, "b3": b3,
            "limits": src.LIMITS, "imagery": IMAGERY, "offices": OFFICES,
            "towns_nav": [(t["slug"], t["name"]) for t in TOWNS],
            "contracts": {k: v for k, v in src.CONTRACTS.items()
                          if contract_shown(k, storm_layers, hail_history, hail_addresses, road_row)
                          # a row a B5 row replaces is listed once, as the B5 row (sources.py superseded_by)
                          and not (hail_history and v.get("superseded_by"))},
            "about_hail": about_hail_context() if hail_history else None,
            "b6": about_b6_context(base_doc) if hail_history else None,
            "fresh_min": src.FRESH_MINUTES, "qc_words": src.QC_WORDS,
            "qc_rejected": src.QC_REJECTED}
    e = env()
    pages = {
        "index.html": ("index.html", {"page": "now", "root": "",
                                      "card": map_card(layers, alerts, towns, c.status, now)}),
        "map.html": ("map.html", {"page": "map", "root": "", "sheet": SHEET_WORDS,     # towns come with the shell's base
                                   # the satellite reason is a word of the storm-layer build only (the flag-off page has none)
                                   "map_words": {k: v for k, v in MAP_WORDS.items() if storm_layers or not k.startswith("satellite")},
                                   "satellite_title": (layers.get("satellite") or {}).get("title") or ""}),
        "reports.html": ("reports.html", {"page": "reports", "root": "", "reports": reports}),
        "about.html": ("about.html", {"page": "about", "root": ""}),
    }
    for name, (tpl, ctx) in pages.items():
        (out / name).write_text(e.get_template(tpl).render(**base, **ctx), encoding="utf-8")
    for t in towns:
        html = e.get_template("town.html").render(**base, page="town", root="../", town=t, now=now,
                                                 delta_hour=timedelta(hours=1))
        (out / "town" / f"{t['slug']}.html").write_text(html, encoding="utf-8")

    # B6 (D125(d)): data/base.json is written beside map.json, and map.json carries its pointer. Both carry this build's time.
    (out / BASE_DATA).write_text(json.dumps(base_doc, separators=(",", ":")), encoding="utf-8")
    (out / "data" / "map.json").write_text(
        json.dumps(map_data(now, sample, layers, towns, alerts, reports, c.status, hail=hail_block,
                            base=base_pointer(base_doc)),
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
    content = content_sample(alerts, towns, reports, satellite_text, swath_text)
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


def content_sample(alerts, towns, reports, satellite_text: str | None = None, swath_text: list | None = None) -> dict:
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
    if swath_text:                           # --storm-layers only: the two hail swath layers' lines (B4)
        out["hail_swath"] = {layer["title"]: layer["lines"] for layer in swath_text}
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
                    help="also read NOAA radar echo tops for each town (text only), the GOES satellite "
                         "picture and the live hail swath layers (last hour, last 24 hours) for the map; "
                         "off by default")
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
