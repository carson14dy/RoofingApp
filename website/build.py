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
import hashlib
import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

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

    def reports(self):
        """SPC storm reports (D13) for the last REPORT_DAYS reporting days, one day at a time: each day's
        hail and wind files are fetched on their own. The newest REPORT_REFRESH days are fetched in every
        build. An older day keeps the copy that loaded in the last published build (the same last-good
        rule as the alert and station lists), so a build fetches only the days with no good copy yet.
        A day whose file is missing or fails is "unavailable" for that day: it stays on the page and is
        never read as no reports (AGENTS.md rule 5)."""
        today = src.spc_day_for(self.now)
        kept = (self.prev.get("reports") or {}).get("days") or {}
        days = []
        for back in range(src.REPORT_DAYS):
            day = today - timedelta(days=back)
            copy = kept.get(day.isoformat())
            if back >= src.REPORT_REFRESH and isinstance(copy, dict) and isinstance(copy.get("items"), list):
                days.append({"day": day.isoformat(), "status": "loaded", "items": copy["items"], "problems": [],
                             "note": "", "loaded": copy.get("loaded"), "from_copy": True})
            else:
                days.append(self._report_day(day, back))
        recent = days[:src.REPORT_REFRESH]
        recent_problems = [f"{_label(d['day'])} {p}" for d in recent for p in d["problems"]]
        older = sum(1 for d in days[src.REPORT_REFRESH:] if d["status"] == "unavailable")
        items = sorted((r for d in recent for r in d["items"]), key=lambda r: r["time"], reverse=True)
        detail = "; ".join(recent_problems) if recent_problems else (
            f"{len(items)} reports in {src.REPORT_REFRESH} days"
            + (f"; {older} older day{'' if older == 1 else 's'} unavailable" if older else ""))
        self.note("reports", "SPC storm reports", not recent_problems, detail)
        return {"items": items,       # the newest three days only: the map and the build log read these
                "problems": [f"{_label(d['day'])} {p}" for d in days for p in d["problems"]],
                "days": days,         # every kept day, newest first
                "window": {"newest": today, "oldest": today - timedelta(days=src.REPORT_DAYS - 1)}}

    def _report_day(self, day: date, back: int) -> dict:
        items, problems, missing = [], [], []
        for kind in ("hail", "wind"):
            text, err = self.f.text(src.spc_url(day, kind))
            if err:
                if back == 0 and err.startswith("not published"):
                    missing.append(kind)                      # today's file is not posted yet
                else:
                    problems.append(f"{kind} file: {err}")
                continue
            try:
                items.extend(src.parse_spc(text, day, kind))
            except ValueError as e:
                problems.append(f"{kind} file: {e}")
        items.sort(key=lambda r: r["time"], reverse=True)
        if problems:
            status = "unavailable"
        elif len(missing) == 2:
            status = "not_published"
        else:
            status = "loaded"
        note = " ".join(f"The {k} file isn't posted yet." for k in missing) if status == "loaded" else ""
        return {"day": day.isoformat(), "status": status, "items": items, "problems": problems, "note": note,
                "loaded": src._iso(self.now) if status == "loaded" else None, "from_copy": False}

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


# ---------------------------------------------------------------- map page data

MAP_VIEW = {"bounds": [[44.35, -116.06], [49.01, -104.03]], "min_zoom": 5, "max_zoom": 11}


def map_data(now: datetime, sample: bool, layers: dict, towns: list, alerts: dict, reports: dict,
             status: dict) -> dict:
    """Everything the map page draws, as one JSON document (data/map.json). The contract is in
    docs/DESIGN.md ("Interactive map"); website/static/map/map.js reads it."""
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
                          "url": f"town/{t['slug']}.html", "office": t.get("office"), "hours": hours,
                          "alert_ids": None if t["alerts"] is None else [a["id"] for a in t["alerts"]]})
    (s_, w_), (n_, e_) = gridded.IMAGE_BOUNDS
    return {
        "version": 1, "built": src._iso(now), "sample": sample, "tz": "America/Denver",
        "image_bounds": [[s_, w_], [n_, e_]], "view": MAP_VIEW,
        "now": radar_times[-1] if radar_times else src._iso(now),
        "layers": layers, "status": status, "towns": out_towns,
        "alerts": {"ok": alerts["ok"], "checked": alerts["checked"], "last_known": alerts.get("last_known"),
                   "items": alerts["items"]},
        "reports": reports["items"],
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


# ---------------------------------------------------------------- the Storm reports page (D30)

# The plain words of the Storm reports page. reports.html's script fills the same placeholders in the
# browser (it reads them from its report-config), so every sentence about a range is written here once.
# A day that is unavailable or not yet published is never counted as having no reports (AGENTS.md rule 5).
REPORT_WORDS = {
    "missing": "Choose a start day and an end day.",
    "format": "Use a date like {example}.",
    "order": "The end day is before the start day. Choose an end day on or after the start day.",
    "long": "That range is {days} reporting days. The page shows up to {max} at a time. Choose a shorter range.",
    "window": "Only the last {max} reporting days are on this page, {first} to {last}. Choose days within them.",
    "fallback": "Showing the last {default} reporting days instead.",
    "showing": "Showing {range} ({days}).",
    "found": "{count} hail or wind {noun} in or near Montana.",
    "empty": "No hail or wind reports in or near Montana for {days}. No report is not evidence that no hail fell.",
    "all_unavailable": "Data unavailable for every day in this range. This is not an all-clear.",
    "some_unavailable": "Data unavailable for {unavailable} of {days}. Missing reports are not an all-clear.",
    "all_unpublished": "Not yet published. This reporting day is still open.",
    "some_unpublished": "Not yet published for {unpublished} of {days}: that reporting day is still open.",
    "day_one": "reporting day", "day_many": "reporting days",
    "report_one": "report", "report_many": "reports",
}


def _label(day: str) -> str:
    """'2026-10-14' -> 'Oct 14', as the page writes a reporting day."""
    d = date.fromisoformat(day)
    return f"{d:%b} {d.day}"


def report_summary(days: list[dict], words: dict = REPORT_WORDS) -> str:
    """The sentences above a range of reporting days: the range, what it found, and what is unavailable or
    not yet published. reports.html's script writes the same sentences for a range a reader picks."""
    n = len(days)
    if not n:
        return ""
    ordered = sorted(days, key=lambda d: d["day"])
    first, last = ordered[0]["label"], ordered[-1]["label"]
    span = f"{n} {words['day_one'] if n == 1 else words['day_many']}"
    lines = [words["showing"].format(range=first if first == last else f"{first} to {last}", days=span)]
    unavailable = sum(d["status"] == "unavailable" for d in days)
    unpublished = sum(d["status"] == "not_published" for d in days)
    loaded = n - unavailable - unpublished
    found = sum(d["count"] for d in days)          # every report listed, including a partly loaded day's
    if unavailable == n:
        lines.append(words["all_unavailable"])
    elif unpublished == n:
        lines.append(words["all_unpublished"])
    else:
        if found:
            lines.append(words["found"].format(count=found, noun=words["report_one"] if found == 1 else words["report_many"]))
        elif loaded:
            lines.append(words["empty"].format(days=f"{loaded} {words['day_one'] if loaded == 1 else words['day_many']}"))
        if unavailable:
            lines.append(words["some_unavailable"].format(unavailable=unavailable, days=span))
        if unpublished:
            lines.append(words["some_unpublished"].format(unpublished=unpublished, days=span))
    return " ".join(lines)


def day_status_text(d: dict) -> str:
    """The status line under a reporting day's heading: loaded (and whose copy), not yet published, or
    unavailable with the file that failed."""
    if d["status"] == "loaded":
        text = f"Loaded {fmt_time(d['loaded'])}."
        if d["from_copy"]:
            text += " Kept from the last published build."
        return f"{text} {d['note']}".strip()
    if d["status"] == "not_published":
        return REPORT_WORDS["all_unpublished"]
    text = "Data unavailable. " + " ".join(p[:1].upper() + p[1:] + "." for p in d["problems"])
    text += " Missing reports are not an all-clear."
    return text + (" The reports listed are the ones that loaded." if d["items"] else "")


def preset_href(newest: date, n: int) -> str:
    """The address of the last n reporting days; the default is the page's own address."""
    if n == src.REPORT_DEFAULT:
        return "reports.html"
    start = newest - timedelta(days=n - 1)
    a, b = src.parse_report_range(start.isoformat(), newest.isoformat(), newest)   # the page must accept it
    return f"reports.html?start={a.isoformat()}&end={b.isoformat()}"


def range_page(reports: dict) -> dict:
    """What the Storm reports page shows: every kept reporting day (newest first) with its heading, status
    line and table rows, the default summary, the quick ranges, and the config its script reads."""
    newest, oldest = reports["window"]["newest"], reports["window"]["oldest"]
    days = []
    for d in reports["days"]:
        n = len(d["items"])
        suffix = {"loaded": f" ({n} report{'' if n == 1 else 's'})", "not_published": " (not yet published)",
                  "unavailable": " (Data unavailable)"}[d["status"]]
        start = fmt_time(f"{d['day']}T12:00:00Z", "%a %b %-d at %-I %p %Z")
        days.append({"day": d["day"], "label": _label(d["day"]), "status": d["status"], "count": n,
                     "items": d["items"], "heading": f"Reporting day starting {start}{suffix}",
                     "status_text": day_status_text(d)})
    # the script's copy of the days: no rows, just what a range needs to say about each day
    light = [{k: v[k] for k in ("day", "label", "status", "count")} for v in days]
    return {
        "days": days,
        "summary": report_summary(light[:src.REPORT_DEFAULT]),
        "presets": [{"label": label, "href": preset_href(newest, n)} for n, label in
                    ((src.REPORT_DEFAULT, "Last 3 days"), (7, "Last 7 days"), (src.REPORT_DAYS, "Last 31 days"))],
        "newest_label": _label(newest.isoformat()), "oldest_label": _label(oldest.isoformat()),
        "config": {"max": src.REPORT_DAYS, "default": src.REPORT_DEFAULT, "newest": newest.isoformat(),
                   "oldest": oldest.isoformat(), "days": light, "words": REPORT_WORDS},
    }


# ---------------------------------------------------------------- build

# Files the pages load with ?v=<content hash>: a file keeps its address until its bytes change, so
# browsers and GitHub Pages reuse the unchanged ones across the 10-minute rebuilds (map.js, map.css,
# the 377 KB basemap and style.css change only with the code). data/map.json and the map card's
# address change every build, so they keep the build minute.
VERSIONED = ("style.css", "map/map.js", "map/map.css", "map/basemap.json")


def asset_versions(static: Path) -> dict:
    """Short content hash per versioned static file (VERSIONED), for the pages' ?v= query."""
    return {name: hashlib.sha256((static / name).read_bytes()).hexdigest()[:12] for name in VERSIONED}


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
    c.add_town_alerts(alerts, towns)
    reports = c.reports()
    layers = c.gridded(out, sample)

    base = {"built": now, "built_ms": int(now.timestamp() * 1000), "asset_v": asset_versions(out / "static"),
            "status": c.status, "sample": sample,
            "limits": src.LIMITS, "offices": OFFICES, "towns_nav": [(t["slug"], t["name"]) for t in TOWNS],
            "contracts": src.CONTRACTS, "fresh_min": src.FRESH_MINUTES, "qc_words": src.QC_WORDS,
            "qc_rejected": src.QC_REJECTED}
    e = env()
    pages = {
        "index.html": ("index.html", {"page": "now", "root": "", "alerts": alerts, "towns": towns,
                                      "card": map_card(layers, alerts, towns, c.status, now)}),
        "map.html": ("map.html", {"page": "map", "root": ""}),
        "reports.html": ("reports.html", {"page": "reports", "root": "", "reports": reports,
                                          "view": range_page(reports)}),
        "about.html": ("about.html", {"page": "about", "root": ""}),
    }
    for name, (tpl, ctx) in pages.items():
        (out / name).write_text(e.get_template(tpl).render(**base, **ctx), encoding="utf-8")
    for t in towns:
        html = e.get_template("town.html").render(**base, page="town", root="../", town=t, now=now,
                                                 delta_hour=timedelta(hours=1))
        (out / "town" / f"{t['slug']}.html").write_text(html, encoding="utf-8")

    (out / "data" / "map.json").write_text(
        json.dumps(map_data(now, sample, layers, towns, alerts, reports, c.status), separators=(",", ":")),
        encoding="utf-8")
    state = {"built": src._iso(now), "sample": sample, "status": c.status,
             "alerts": {k: v for k, v in alerts.items() if k not in ("error", "from_towns")},
             "points": {t["slug"]: t["point"] for t in towns if t.get("point")},
             # the station lists, for reuse when a lookup fails; the readings themselves, with their
             # raw values and flags, as a record of what each town showed (D29)
             "stations": {t["slug"]: [{k: v for k, v in s.items() if k not in ("obs", "error")}
                                      for s in t["obs"]["stations"]] for t in towns if t["obs"]["stations"]},
             "readings": {t["slug"]: [{"id": s["id"], "obs": s["obs"], "error": s["error"]}
                                      for s in t["obs"]["stations"]] for t in towns if t["obs"]["stations"]},
             # the storm reports that loaded, day by day: the next build keeps an older day's copy (D30)
             "reports": {"days": {d["day"]: {"loaded": d["loaded"], "items": d["items"]}
                                  for d in reports["days"] if d["status"] == "loaded" and d["loaded"]}}}
    (out / "data" / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"status": c.status, "alerts": len(alerts["items"]),
            "alerts_null_geometry": sum(1 for a in alerts["items"] if not a["geometry"]),
            "towns_with_forecast": sum(1 for t in towns if t["hours"]),
            "towns_with_gusts": sum(1 for t in towns if t["summary"]["gusts_known"]),
            "towns_with_readings": sum(1 for t in towns if t["obs"]["now"]),
            "reports": len(reports["items"]), "map": map_summary(layers),
            "content": content_sample(alerts, towns, reports)}


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


def content_sample(alerts, towns, reports) -> dict:
    """What the pages say, in brief, for the build log: rule 7 asks for a look at the content,
    not just a 200. The workflow prints the town table in the run summary."""
    return {
        "alert_events": [f"{a['event']} until {fmt_time(a['until'])}" for a in alerts["items"][:10]],
        "towns": {t["name"]: {"lo": t["summary"]["lo"], "hi": t["summary"]["hi"], "gust": t["summary"]["gust"],
                              "wind": t["summary"]["wind"], "precip": t["summary"]["precip"],
                              "flagged": t["summary"]["flagged"], "issued": fmt_time(t["updated"]),
                              "office": t["office"], "alerts": None if t["alerts"] is None else len(t["alerts"]),
                              "now": reading_sample(t["obs"]["now"])}
                  for t in towns},
        "reports_by_day": {d["day"]: len(d["items"]) for d in reports["days"][:src.REPORT_REFRESH]},
    }


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
