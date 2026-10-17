"""
Montana Hail Watch — the app (auto-updating payload)
====================================================
Live Storms, Storm History, inspection candidates, Crew Outlook, places and
data sources. This folder is the part that updates itself: bump the version in
manifest.json, push to GitHub, and every desktop install picks it up.

Contract with the desktop shell (SHELL_API 1)
---------------------------------------------
The shell imports this folder as a package (this file is its __init__) and
calls ``create_app(config)``:

    DATA_DIR   writable folder for this user's data
    DB_PATH    SQLite database file
    NETWORK    False during self-tests: no live calls; feeds show "Off"
    SHELL      desktop bridge (updates, save dialogs, notifications), or None in a browser
    TESTING    True during self-tests

The app registers ``app.extensions["hailwatch.stop"]``; the shell calls it
when a newer version takes over, so background work stops cleanly.

Rules that keep updates safe:
  * Import sibling modules relatively (``from . import weather``).
  * Database changes go at the end of store.MIGRATIONS, never edit shipped ones.
  * A new pip package needs a new desktop build — raise ``min_shell``.

Nothing in the alert path is AI-generated: every sentence is a fixed template
filled with values from a cited feed.

Develop in a browser:  python desktop/launcher.py --browser
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

from . import maps
from . import weather as wx
from .store import CANDIDATE_STATUSES, Store

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "manifest.json"), encoding="utf-8") as _f:
    MANIFEST = json.load(_f)
VERSION = MANIFEST["version"]
USER_AGENT = f"MontanaHailWatch/{VERSION} (roofing field tool)"
DEMO_FIXTURE = os.path.join(HERE, "fixtures", "demo_hail_footprint.geojson")

SIZES = maps.SIZES
SIZE_BY_KEY = {s["key"]: s for s in SIZES}
SIZE_MIN, SIZE_MAX = 0.10, 8.0
MT_BOX = (44.35, 49.01, -116.06, -104.03)
MT_AREA = (MT_BOX[0] - 0.75, MT_BOX[1] + 0.75, MT_BOX[2] - 0.75, MT_BOX[3] + 0.75)  # Montana + border margin
DISCLAIMER = ("Weather exposure does not confirm roof damage. This is an internal summary, "
              "not certified weather evidence.")

DEFAULTS = {
    "rules": dict(wx.DEFAULT_RULES),
    "targeting": dict(wx.DEFAULT_TARGETING),
    "notify": {"hail_in": 1.0, "radius_mi": 5.0, "os": "severe"},
    "footprint": {"source": "none", "url": ""},
    "spc": {"filtered": True, "area": "MT"},
    "display_tz": wx.DISPLAY_TZ,
}
ZONES = ["America/Denver", "America/Boise", "America/Chicago", "America/Los_Angeles", "America/Phoenix",
         "America/New_York", "UTC"]

REVIEW_SRC = "Independent review, Oct 11, 2026 — documented claims to verify in a trial"
CANDIDATE_FEEDS = [
    {"name": "Estimated hail size (MRMS MESH)", "provider": "NOAA / NSSL", "state": "not_connected", "kind": "Estimate",
     "detail": "Free ~1 km grids. MESH and 30/60-min swaths update every 2 min; 120–1440-min swaths every 30 min. "
               "A swath maximum belongs to its interval. Published as GRIB2 files, not map layers — needs a "
               "processing job; point the GeoJSON feed setting at it.",
     "question": "Cost and expertise of running the processing pipeline.",
     "url": "https://www.nssl.noaa.gov/projects/mrms/operational/tables.php"},
    {"name": "SPC outlooks with Conditional Intensity Groups", "provider": "NOAA SPC", "state": "candidate",
     "kind": "Forecast", "detail": "Probabilities describe events within 25 miles of a point — not a roof-hit "
                                  "probability. Intensity is conditional on an event occurring.",
     "question": "Incremental value over NWS alerts for scheduling.",
     "url": "https://origin-west-www-spc.woc.noaa.gov/about/outlooks/"},
    {"name": "ProbSevere v3", "provider": "NOAA / CIMSS", "state": "candidate", "kind": "Forecast",
     "detail": "Next-hour storm probabilities for identified storms (operational at NOAA since August 2025). "
               "Documented limits for shallow/low-lightning storms and squall lines. Never suppresses an official warning.",
     "question": "Lead time and false alarms on Montana storms.", "url": "https://cimss.ssec.wisc.edu/probsevere/ps/"},
    {"name": "LightningCast", "provider": "NOAA / CIMSS", "state": "candidate", "kind": "Forecast",
     "detail": "Predicts lightning from satellite (GLM-based target) — not a ground-strike observation feed. "
               "Confirm current deployment/version.", "question": "Seasonal and cloud-type limitations here.",
     "url": "https://cimss.ssec.wisc.edu/probsevere/wp-content/uploads/sites/29/2025/11/LightningCast_QuickGuide.pdf"},
    {"name": "Xweather (live, hail nowcast, hail archive, lightning)", "provider": "Xweather", "state": "subscription",
     "kind": "Forecast · Estimate", "detail": "Hail threats now to +60 min in 10-min steps; /hail/archive lists U.S. "
               "history from Jan 1, 2024, hourly updates, 24-h query increments. Published pay-as-you-go: $0.0006 base "
               "access, 15,000 free monthly accesses, 12× multiplier for hail (not a quote).",
     "question": "Coverage, latency, archive method, commercial rights and billable usage.",
     "url": "https://www.xweather.com/docs/weather-api/endpoints/hail-archive"},
    {"name": "HailZone", "provider": "The Weather Company", "state": "subscription", "kind": "Forecast",
     "detail": "CONUS 30-minute hail forecast, 1 km data, 5-minute refresh.",
     "question": "Independent value, upstream overlap, access terms and quote.",
     "url": "https://developer.weather.com/docs/openapi/hailzone-30-minute-2-0"},
    {"name": "Benchmark property weather history", "provider": "Verisk", "state": "subscription", "kind": "Estimate",
     "detail": "Estimated hail/wind history at and near an address. API brochure dated 2022 — not a current contract.",
     "question": "Current schemas, archive depth, corrections, bulk cost, export rights.",
     "url": "https://www.verisk.com/siteassets/media/downloads/property-estimating/benchmark-api-brochure-2022.pdf"},
    {"name": "Weather Verify (hail)", "provider": "Cotality", "state": "subscription", "kind": "Estimate",
     "detail": "Continental-U.S. hail reporting with API integration. Accuracy claims are marketing to test.",
     "question": "Structured API access, event finalization, accuracy evidence, rights.",
     "url": "https://content.cotality.com/product-docs/claims-weather-hail-verify/"},
    {"name": "Storm Events history", "provider": "NOAA NCEI", "state": "not_connected", "kind": "Report",
     "detail": "Historical event records for retrospective context.", "question": "Archive lag and coverage period.",
     "url": "https://www.ncei.noaa.gov/access/storm-events-database/"},
]

NOTES = {
    "finding-saved":     ("ok",    "Inspection finding saved."),
    "finding-saved-out": ("warn",  "Inspection finding saved. That spot is outside Montana — double-check the coordinates."),
    "finding-deleted":   ("ok",    "Finding deleted."),
    "finding-noloc":     ("error", "Set the location first: click the map, or type latitude and longitude."),
    "finding-size":      ("error", f"Hail size must be between {SIZE_MIN:g} and {SIZE_MAX:g} inches."),
    "finding-date":      ("error", "Use a real date for “Date observed.”"),
    "shape-saved":       ("ok",    "{what} saved."),
    "shape-deleted":     ("ok",    "{what} deleted."),
    "shape-discarded":   ("ok",    "Shape discarded."),
    "shape-bad":         ("error", "That shape couldn't be read. Trace it again with the polygon or rectangle tool."),
    "place-saved":       ("ok",    "{what} saved."),
    "place-deleted":     ("ok",    "Deleted."),
    "place-bad":         ("error", "Give it a name and a location (search, map click, or coordinates)."),
    "job-saved":         ("ok",    "Job details saved."),
    "job-bad":           ("error", "{msg}"),
    "cand-added":        ("ok",    "{n} added as inspection candidates, {m} already on the list (evidence refreshed)."),
    "cand-none":         ("error", "Pick at least one property or job."),
    "cand-saved":        ("ok",    "Candidate updated."),
    "cand-deleted":      ("ok",    "Candidate removed."),
    "exported":          ("ok",    "Saved {n} rows to {path}"),
    "saved-file":        ("ok",    "Saved to {path}"),
    "export-cancelled":  ("ok",    "Export cancelled."),
    "export-empty":      ("error", "Nothing to export yet."),
    "settings-saved":    ("ok",    "Settings saved."),
    "settings-bad":      ("error", "{msg}"),
    "review-saved":      ("ok",    "Supervisor review recorded."),
    "ack-saved":         ("ok",    "Crew acknowledgement recorded."),
    "signoff-bad":       ("error", "Enter a name."),
    "notices-read":      ("ok",    "Storm matches marked as read."),
    "updated":           ("ok",    "Updated to version {v}."),
    "update-failed":     ("error", "{msg}"),
    "rolled-back":       ("ok",    "{msg}"),
    "rollback-failed":   ("error", "{msg}"),
    "source-saved":      ("ok",    "Update source saved. Checking now…"),
    "source-bad":        ("error", "{msg}"),
    "no-shell":          ("error", "That only works in the desktop app."),
}


def read_note():
    key = request.args.get("note")
    if key not in NOTES:
        return None
    tone, text = NOTES[key]
    fields = {k: request.args.get(k, "") for k in ("n", "m", "path", "v", "msg", "what")}
    try:
        text = text.format(**fields)
    except (KeyError, IndexError):
        pass
    return {"tone": tone, "text": text}


def csv_safe(value) -> str:
    """Stop spreadsheet apps from running text that starts like a formula."""
    s = "" if value is None else str(value).replace("\r", " ").replace("\n", " ")
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def in_area(ev: wx.Evidence, area: str) -> bool:
    if area == "all":
        return True
    lon, lat = ev.geometry["coordinates"][:2]
    return MT_AREA[0] <= lat <= MT_AREA[1] and MT_AREA[2] <= lon <= MT_AREA[3]


def fnum(value, lo, hi, default=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if lo <= v <= hi else default


def worst(statuses) -> str:
    s = set(statuses)
    return "unavailable" if "unavailable" in s or not s else ("review" if "review" in s else "meets")


# --------------------------------------------------------------------------
def create_app(config: dict | None = None) -> Flask:
    cfg = {"NETWORK": True, "SHELL": None, "TESTING": False, "BACKGROUND": True, **(config or {})}
    cfg.setdefault("DATA_DIR", os.path.join(HERE, "..", ".devdata"))
    cfg.setdefault("DB_PATH", os.path.join(cfg["DATA_DIR"], "hailwatch.db"))

    app = Flask(__name__, root_path=HERE, template_folder="templates", static_folder=None)
    app.config.update(TESTING=bool(cfg["TESTING"]))
    store = Store(cfg["DB_PATH"])
    net = bool(cfg["NETWORK"])
    http = wx.Http(USER_AGENT)
    alerts = wx.AlertService(http, store.load_alerts, store.save_alerts, enabled=net)
    zones = wx.ZoneService(http, enabled=net)
    radar = wx.RadarService(http, enabled=net)
    spc = wx.SPCService(http, enabled=net)
    forecasts = wx.ForecastService(http, enabled=net)
    geocoder = wx.Geocoder(http, enabled=net)
    shell = cfg["SHELL"]
    pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="feeds")
    stop = threading.Event()
    match_lock = threading.Lock()

    def setting(key):
        return store.setting(key, DEFAULTS[key])

    def tz():
        return setting("display_tz")

    def footprint_source():
        fp = setting("footprint")
        if fp.get("source") == "demo":
            return wx.DemoFootprint(DEMO_FIXTURE)
        if fp.get("source") == "geojson" and fp.get("url"):
            return wx.GeoJSONFootprint(http, fp["url"], enabled=net)
        return wx.FootprintSource()

    def shell_call(name, *args, default=None):
        fn = getattr(shell, name, None) if shell is not None else None
        if fn is None:
            return default
        try:
            return fn(*args)
        except Exception:
            app.logger.exception("desktop call %s failed", name)
            return default

    def reports_for(day, kind):
        try:
            return spc.reports(day, kind, setting("spc").get("filtered", True)), None
        except wx.FeedError as e:
            return [], str(e)

    def deliver(name, data: bytes, mimetype, back, note="saved-file", **extra):
        saved = shell_call("save_file", name, data)
        if saved is None:     # browser mode: a normal download
            return Response(data, mimetype=mimetype, headers={"Content-Disposition": f"attachment; filename={name}"})
        if saved == "":
            return redirect(url_for(back, note="export-cancelled"))
        return redirect(url_for(back, note=note, path=saved, **extra))

    # ---------------- template helpers ----------------
    app.jinja_env.filters["local"] = lambda dt, tzname=None, with_date=True: wx.fmt_local(dt, tzname or tz(), with_date)
    app.jinja_env.filters["age"] = wx.age_text
    app.jinja_env.filters["sizecolor"] = maps.size_color
    app.jinja_env.filters["sizelabel"] = maps.size_label

    @app.context_processor
    def common():
        return {"app_version": VERSION, "desktop": shell is not None,
                "update": shell_call("update_status", default=None), "note": read_note(),
                "unread": store.unread_notices(), "sizes": SIZES, "disclaimer": DISCLAIMER,
                "outlook_label": wx.OUTLOOK_LABEL, "statuses": CANDIDATE_STATUSES, "display_tz": tz(),
                "phases": wx.PHASES, "phase_names": dict(wx.PHASES)}

    # ======================================================================
    # Alert geography + storm matches (deduplicated, never AI-written)
    # ======================================================================
    def ensure_place_codes(limit=5):
        """Look up each place's NWS forecast zone, county and fire zone (for
        alerts that have no polygon). Re-checked every 30 days."""
        for p in store.places_needing_codes()[:limit]:
            try:
                info = forecasts.point(p["lat"], p["lng"])
            except wx.FeedError:
                continue
            store.set_place_codes(p["id"], info.get("zone"), info.get("county"), info.get("fire_zone"), info.get("tz"))

    def alert_targets(a, places, shapes):
        hits, unknown = [], []
        for p in places:
            ok, how = wx.applies_to_place(a, p)
            if ok:
                hits.append((f"place:{p['id']}", p["name"], how))
            elif ok is None:
                unknown.append((p["name"], how))
        for t, g in shapes:
            ok, how = wx.applies_to_area(a, g, zones.geoms)
            if ok:
                hits.append((f"territory:{t['id']}", f"territory {t['name']}", how))
            elif ok is None:
                unknown.append((f"territory {t['name']}", how))
        return hits, unknown

    def run_matches(active, hail_reports):
        """Create notices for alerts and reports that touch your places. Returns
        the new ones (for desktop notifications). Safe to call repeatedly."""
        rule = setting("notify")
        thr, rad = rule["hail_in"], rule["radius_mi"]
        places = store.places()
        shapes = [(t, json.loads(t["geojson"])) for t in store.territories()]
        new = []
        with match_lock:
            for a in active:
                until = wx.fmt_local(a.get("ends") or a.get("expires"), tz())
                size = f" NWS lists hail up to {a['hail_in']:g}″." if a.get("hail_in") else ""
                hits, _ = alert_targets(a, places, shapes)
                for key, label, how in hits:
                    title = f"Official alert: {a['event']}"
                    body = f"Applies to {label} (matched by {how}).{size} Until {until}. Source: National Weather Service."
                    if store.add_notice(f"alert:{a['id']}:{key}", "official_alert", title, body):
                        new.append({"title": title, "body": body, "severe": bool(a.get("convective"))})
            for r in hail_reports:
                if r.magnitude is None or r.magnitude < thr:
                    continue
                lon, lat = r.geometry["coordinates"][:2]
                when = wx.fmt_local(r.valid_from, tz())
                for p in places:
                    d = wx.haversine_mi(p["lat"], p["lng"], lat, lon)
                    if d <= rad:
                        title = "Reported hail nearby"
                        body = (f"{r.magnitude:.2f}″ hail reported {d:.1f} mi from {p['name']} at {when} "
                                f"(SPC preliminary report — not a damage confirmation).")
                        if store.add_notice(f"spc:{r.source_record_id}:place:{p['id']}:rule{thr}/{rad}",
                                            "point_report", title, body):
                            new.append({"title": title, "body": body, "severe": True})
                for t, g in shapes:
                    if wx.point_in(g, lat, lon):
                        title = "Reported hail in your territory"
                        body = f"{r.magnitude:.2f}″ hail reported in {t['name']} at {when} (SPC preliminary report)."
                        if store.add_notice(f"spc:{r.source_record_id}:territory:{t['id']}:rule{thr}",
                                            "point_report", title, body):
                            new.append({"title": title, "body": body, "severe": True})
        mode = rule.get("os", "severe")
        for n in new:
            if mode == "all" or (mode == "severe" and n["severe"]):
                shell_call("notify", n["title"], n["body"])
        return new

    def poll_forever():
        """Official alerts reach you even when no one is looking at the map."""
        tick = 0
        while not stop.wait(3 if tick == 0 else 60):
            tick += 1
            try:
                alerts.refresh(wait=True)
                active = alerts.active()
                zones.ensure(active)
                ensure_place_codes()
                hail = []
                if tick % 10 == 1:
                    hail, _ = reports_for(wx.spc_day_for(wx.utcnow()), "hail")
                run_matches(active, hail)
            except Exception:
                app.logger.exception("background alert check")

    if net and cfg["BACKGROUND"] and not cfg["TESTING"]:
        threading.Thread(target=poll_forever, name="alerts", daemon=True).start()
    app.extensions["hailwatch.stop"] = stop.set

    # ======================================================================
    # Crew Outlook (also feeds the home screen)
    # ======================================================================
    def job_outlook(p, work_date=None):
        company = setting("rules")
        try:
            overrides = json.loads(p.get("rules") or "{}")
        except ValueError:
            overrides = {}
        rules, rule_src = wx.merge_rules(company, overrides)
        o = forecasts.outlook(p["lat"], p["lng"])
        if o.get("tz") and o["tz"] != p.get("tz"):
            store.set_place_tz(p["id"], o["tz"])
        tzname = o.get("tz") or p.get("tz") or tz()
        for h in o["hours"]:
            in_force = [a for a in o["alerts"] if (wx.parse_iso(a.get("ends") or a.get("expires")) or h["start"]) > h["start"]]
            h["eval"] = wx.evaluate_hour(h, rules, in_force, o.get("alerts_ok", False), rule_src)
        o["windows"] = wx.outlook_windows(o["hours"], tzname)
        o["tzname"], o["rules"], o["rule_src"] = tzname, rules, rule_src
        local_today = wx.utcnow().astimezone(wx.zone(tzname)).date()
        o["today"], o["tomorrow"] = local_today, local_today + timedelta(days=1)
        by_day = {}
        for h in o["hours"]:
            d = h["start"].astimezone(wx.zone(tzname)).date()
            if h.get("daytime") is not False or not rules.get("daylight_only"):
                by_day.setdefault(d, []).append(h)
        o["day_status"] = {d: worst(h["eval"]["status"] for h in hs) for d, hs in by_day.items()}
        need = (p.get("duration_h") or 0) + (p.get("dryin_h") or 0)
        wd = work_date or local_today
        o["work_date"] = wd
        o["work_status"] = o["day_status"].get(wd, "unavailable")
        o["fit"] = wx.phase_fit(o["hours"], need or None, tzname, wd)
        if o["fit"].get("fits") is False and o["work_status"] == "meets":
            o["work_status"] = "review"
        reasons = []
        for w in o["windows"]:
            if w["start"].astimezone(wx.zone(tzname)).date() == wd and w["status"] != "meets":
                reasons.append(f"{w['when']}: " + ("; ".join(w["triggers"] or ["missing " + ", ".join(w["missing"])])))
        if o["fit"].get("fits") is False:
            reasons.append(o["fit"]["reason"])
        o["work_reasons"] = reasons
        summary = reasons[0] if reasons else wx.OUTLOOK_LABEL[o["work_status"]]
        prev = store.log_outlook(p["id"], wd.isoformat(), o["work_status"], summary)
        o["changed_from"] = prev
        o["history"] = store.outlook_history(p["id"], wd.isoformat())
        return o

    def job_date(p, default):
        try:
            return date.fromisoformat(p["work_date"]) if p.get("work_date") else default
        except ValueError:
            return default

    # ======================================================================
    # Home: Live Storms — warnings, today's jobs, tomorrow's conflicts, candidates
    # ======================================================================
    @app.get("/")
    def live():
        now = wx.utcnow()
        day = wx.spc_day_for(now)
        area = setting("spc").get("area", "MT")
        jobs_f = {"alerts": pool.submit(alerts.refresh, True), "radar": pool.submit(radar.refresh),
                  "hail": pool.submit(reports_for, day, "hail"), "wind": pool.submit(reports_for, day, "wind")}
        for name in ("alerts", "radar"):
            try:
                jobs_f[name].result(timeout=25)
            except Exception as e:  # a slow feed shows as stale/unavailable, never blocks the page
                app.logger.warning("%s refresh: %s", name, e)
        hail, hail_err = jobs_f["hail"].result(timeout=25)
        wind, wind_err = jobs_f["wind"].result(timeout=25)
        hail = [r for r in hail if in_area(r, area)]
        wind = [r for r in wind if in_area(r, area)]
        active = alerts.active()
        pool.submit(zones.ensure, active)       # zone boundaries for alerts without a polygon (next refresh uses them)
        ensure_place_codes(limit=3)
        run_matches(active, hail)

        places, territories = store.places(), store.territories()
        shapes = [(t, json.loads(t["geojson"])) for t in territories]
        local_today = now.astimezone(wx.zone(tz())).date()
        warn_cards = []
        for a in active:
            hits, unknown = alert_targets(a, places, shapes)
            warn_cards.append({"a": a, "hits": hits, "unknown": unknown,
                               "scope": "warning polygon" if a.get("geometry") else
                               f"{len(a.get('ugc') or [])} forecast zone/county code(s)"})
        warn_cards.sort(key=lambda c: (not c["hits"], not c["a"].get("convective"), c["a"].get("event", "")))

        jobs = store.places("job")[:20]
        today_jobs = [p for p in jobs if job_date(p, local_today) == local_today]
        tomorrow_jobs = [p for p in jobs if p.get("work_date") and job_date(p, None) == local_today + timedelta(days=1)]
        outlooks = dict(zip([p["id"] for p in today_jobs], pool.map(job_outlook, today_jobs))) if today_jobs else {}
        tom = dict(zip([p["id"] for p in tomorrow_jobs],
                       pool.map(lambda p: job_outlook(p, local_today + timedelta(days=1)), tomorrow_jobs))) if tomorrow_jobs else {}
        today_cards = [{"p": p, "o": outlooks[p["id"]]} for p in today_jobs if outlooks[p["id"]]["work_status"] != "meets"]
        tomorrow_cards = [{"p": p, "o": tom[p["id"]]} for p in tomorrow_jobs if tom[p["id"]]["work_status"] != "meets"]
        cands = store.candidates()

        fp = footprint_source()
        live_fp = fp.footprints(day.isoformat()) if fp.key == "geojson" else []
        q = (request.args.get("q") or "").strip()
        results, search_error = geocoder.search(q) if q else ([], None)
        lat, lon = fnum(request.args.get("lat"), -90, 90), fnum(request.args.get("lon"), -180, 180)
        center = (lat, lon) if lat is not None and lon is not None else None

        m = maps.new_map(center, 12 if center else None)
        radar_layer = maps.add_radar(m, radar.feed, tz())
        maps.add_alerts(m, [a for a in active if a.get("geometry")], tz())
        maps.add_zone_alerts(m, [a for a in active if not a.get("geometry")], zones.geoms, tz())
        maps.add_footprints(m, live_fp)
        maps.add_reports(m, hail, tz())
        maps.add_reports(m, wind, tz(), name="Reported wind (SPC, preliminary)", show=False)
        maps.add_territories(m, territories)
        findings, areas = store.findings(), store.areas()
        maps.add_findings(m, findings, areas)
        maps.add_places(m, places)
        if center:
            maps.add_pin(m, lat, lon, request.args.get("label") or "Search result")
        maps.finish(m)
        for f in findings:
            f["color"], f["label"] = maps.size_color(f["size_in"]), maps.size_label(f["size_in"])
        start, end = wx.spc_window(day)
        return render_template(
            "live.html", page="live", **maps.render(m), radar_name=radar_layer.get_name(),
            feeds=[radar.feed.view(tz()), alerts.feed.view(tz()), spc.feed.view(tz()), fp.feed.view(tz())],
            alerts_feed=alerts.feed.view(tz()), warn_cards=warn_cards, today_cards=today_cards,
            tomorrow_cards=tomorrow_cards, today_jobs=today_jobs, tomorrow_jobs=tomorrow_jobs,
            cands=cands, cand_new=[c for c in cands if c["status"] == "not_contacted"][:3],
            cand_counts={k: sum(1 for c in cands if c["status"] == k) for k, _ in CANDIDATE_STATUSES},
            hail=sorted(hail, key=lambda r: -(r.magnitude or 0)), wind=wind, hail_err=hail_err, wind_err=wind_err,
            spc_day=day, spc_start=start, spc_end=end, area=area, notices=store.notices(12),
            findings=findings, places=places, territories=territories, areas=areas,
            q=q, results=results, search_error=search_error, today=date.today().isoformat(),
            zones_missing=sum(1 for c in warn_cards if not c["a"].get("geometry")
                              and any(u not in zones.geoms for u in c["a"].get("zones") or [])))

    @app.post("/notices/read")
    def notices_read():
        store.mark_notices_read()
        return redirect(url_for("live", note="notices-read"))

    # ---------------- crew inspection findings ----------------
    @app.post("/findings")
    def add_finding():
        f = request.form
        lat, lng = fnum(f.get("lat"), -90, 90), fnum(f.get("lng"), -180, 180)
        if lat is None or lng is None:
            return redirect(url_for("live", note="finding-noloc"))
        exact = (f.get("size_exact") or "").strip()
        size_in = fnum(exact, SIZE_MIN, SIZE_MAX) if exact else SIZE_BY_KEY.get(f.get("size_class"), SIZE_BY_KEY["penny"])["repr"]
        if size_in is None:
            return redirect(url_for("live", note="finding-size"))
        obs = (f.get("obs_date") or "").strip() or date.today().isoformat()
        try:
            date.fromisoformat(obs)
        except ValueError:
            return redirect(url_for("live", note="finding-date"))
        store.add_finding(lat, lng, size_in, obs, f.get("hood", "").strip(), f.get("address", "").strip(),
                          f.get("notes", "").strip())
        inside = MT_BOX[0] <= lat <= MT_BOX[1] and MT_BOX[2] <= lng <= MT_BOX[3]
        return redirect(url_for("live", note="finding-saved" if inside else "finding-saved-out"))

    @app.post("/findings/<int:rid>/delete")
    def delete_finding(rid):
        store.delete_finding(rid)
        return redirect(url_for("live", note="finding-deleted"))

    @app.post("/findings/export")
    def export_findings():
        rows = store.findings()
        if not rows:
            return redirect(url_for("live", note="export-empty"))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "evidence_kind", "obs_date", "latitude", "longitude", "hail_inches", "size_class",
                    "neighborhood", "address", "notes"])
        for r in rows:
            w.writerow([r["id"], "inspection (crew-confirmed)", r["obs_date"], r["lat"], r["lng"], r["size_in"],
                        maps.size_label(r["size_in"]), csv_safe(r["hood"]), csv_safe(r["address"]), csv_safe(r["notes"])])
        return deliver(f"inspection-findings-{date.today().isoformat()}.csv", buf.getvalue().encode("utf-8-sig"),
                       "text/csv", "live", note="exported", n=len(rows))

    # ---------------- drawn shapes: territory or crew-observed hail area ----------------
    def shape_page(geom, **extra):
        return render_template("shape.html", page="live", geojson=json.dumps(geom), area=wx.area_sq_mi(geom),
                               points=len(geom["coordinates"][0]) - 1, **extra)

    @app.post("/shapes/new")
    def name_shape():
        geom = wx.clean_polygon(request.form.get("geojson", ""))
        return redirect(url_for("live", note="shape-bad")) if geom is None else shape_page(geom)

    @app.post("/shapes")
    def save_shape():
        f = request.form
        if f.get("action") == "discard":
            return redirect(url_for("live", note="shape-discarded"))
        geom = wx.clean_polygon(f.get("geojson", ""))
        if geom is None:
            return redirect(url_for("live", note="shape-bad"))
        name = f.get("name", "").strip()
        if f.get("kind") == "territory":
            if not name:
                return shape_page(geom, error="Give the territory a name.", kind="territory")
            store.add_territory(name, geom)
            return redirect(url_for("live", note="shape-saved", what="Territory"))
        exact = (f.get("size_exact") or "").strip()
        size_in = fnum(exact, SIZE_MIN, SIZE_MAX) if exact else SIZE_BY_KEY.get(f.get("size_class"), SIZE_BY_KEY["penny"])["repr"]
        if size_in is None:
            return shape_page(geom, name=name, kind="area",
                              error=f"Hail size must be between {SIZE_MIN:g} and {SIZE_MAX:g} inches.")
        store.add_area(name, size_in, geom)
        return redirect(url_for("live", note="shape-saved", what="Crew-observed hail area"))

    @app.post("/areas/<int:aid>/delete")
    def delete_area(aid):
        store.delete_area(aid)
        return redirect(url_for("live", note="shape-deleted", what="Area"))

    @app.post("/territories/<int:tid>/delete")
    def delete_territory(tid):
        store.delete_territory(tid)
        return redirect(url_for("places", note="shape-deleted", what="Territory"))

    # ======================================================================
    # Storm History & inspection targeting
    # ======================================================================
    def event_context(event, kind="hail", min_size=0.0, area="MT"):
        now = wx.utcnow()
        fp = footprint_source()
        ctx = {"event": event, "kind": kind, "min_size": min_size, "area": area, "fp": fp, "errors": [],
               "reports": [], "shown": [], "footprints": [], "hidden_unknown": 0, "demo": event == "demo"}
        if ctx["demo"]:
            ctx.update(label="Demo event (fictional — not a real storm)", event_key="demo")
            if fp.key != "demo":
                ctx["errors"].append("The demo footprint is off. Turn it on under Data sources to try the demo event.")
            else:
                ctx["footprints"] = fp.footprints("demo")
            return ctx
        try:
            day = date.fromisoformat(event)
        except ValueError:
            day = wx.spc_day_for(now)
        day = min(day, wx.spc_day_for(now))
        start, end = wx.spc_window(day)
        ctx.update(day=day, start=start, end=end, event=day.isoformat(), event_key=f"spc:{day.isoformat()}",
                   label=f"SPC reporting day {day:%b %d, %Y}")
        hail, err = reports_for(day, "hail")
        if err:
            ctx["errors"].append(f"Hail reports unavailable: {err}")
        ctx["reports"] = [r for r in hail if in_area(r, area)]
        shown = ctx["reports"]
        if kind == "wind":
            wind, werr = reports_for(day, "wind")
            if werr:
                ctx["errors"].append(f"Wind reports unavailable: {werr}")
            shown = [r for r in wind if in_area(r, area)]
        elif min_size > 0:
            ctx["hidden_unknown"] = sum(1 for r in shown if r.magnitude is None)
            shown = [r for r in shown if r.magnitude is not None and r.magnitude >= min_size]
        ctx["shown"] = sorted(shown, key=lambda r: (-(r.magnitude or 0), r.valid_from))
        if fp.key == "geojson":
            ctx["footprints"] = fp.footprints(day.isoformat())
        return ctx

    @app.get("/history")
    def history():
        now = wx.utcnow()
        event = request.args.get("event") or wx.spc_day_for(now).isoformat()
        kind = "wind" if request.args.get("kind") == "wind" else "hail"
        min_size = fnum(request.args.get("min"), 0, 8, 0.0)
        area = "all" if request.args.get("area") == "all" else setting("spc").get("area", "MT")
        ctx = event_context(event, kind, min_size, area)
        targeting = setting("targeting")
        existing = {c["place_id"] for c in store.candidates() if c["event_key"] == ctx["event_key"]}
        rows = []
        for p in store.places():
            a = wx.assess_place(p, ctx["reports"], ctx["footprints"], targeting)
            rows.append({"place": p, **a, "already": p["id"] in existing})
        rows.sort(key=lambda r: (r["tier"] or 9, r["place"]["name"].lower()))
        terr = []
        for t in store.territories():
            g = json.loads(t["geojson"])
            inside = [r for r in ctx["reports"] if wx.point_in(g, r.geometry["coordinates"][1], r.geometry["coordinates"][0])]
            terr.append({"t": t, "count": len(inside), "max": max((r.magnitude or 0 for r in inside), default=0)})
        m = maps.new_map()
        maps.add_footprints(m, ctx["footprints"], fit=True)
        maps.add_reports(m, ctx["shown"], tz(), name=("Reported wind" if kind == "wind" else "Reported hail")
                         + " (SPC, preliminary)")
        maps.add_territories(m, store.territories())
        maps.add_places(m, store.places())
        maps.finish(m, draw=False)
        quick = [(wx.spc_day_for(now) - timedelta(days=i)) for i in range(0, 4)]
        return render_template("history.html", page="history", **maps.render(m), ctx=ctx, rows=rows, terr=terr,
                               quick=quick, targeting=targeting, spc_feed=spc.feed.view(tz()),
                               max_day=wx.spc_day_for(now).isoformat())

    @app.post("/candidates")
    def add_candidates():
        f = request.form
        ids = [int(x) for x in f.getlist("place_id") if x.isdigit()]
        if not ids:
            return redirect(url_for("history", event=f.get("event", ""), note="cand-none"))
        ctx = event_context(f.get("event", ""), "hail", 0.0, f.get("area", "MT"))
        targeting = setting("targeting")
        added = kept = 0
        for pid in ids:
            p = store.place(pid)
            if not p:
                continue
            a = wx.assess_place(p, ctx["reports"], ctx["footprints"], targeting)
            snapshot = {"evidence": a["evidence"], "assessed_at": wx.iso(wx.utcnow()),
                        "sources": sorted({e["provider"] for e in a["evidence"]}),
                        "event_window_utc": [wx.iso(ctx.get("start")), wx.iso(ctx.get("end"))] if ctx.get("start") else None,
                        "targeting": targeting}
            new = store.upsert_candidate(pid, ctx["event_key"], ctx["label"], a["tier"],
                                         a["reasons"] + ["Not yet inspected"], snapshot, ctx["demo"])
            added, kept = added + new, kept + (not new)
        return redirect(url_for("candidates", note="cand-added", n=added, m=kept))

    @app.get("/candidates")
    def candidates():
        status = request.args.get("status")
        rows = store.candidates(status if status in dict(CANDIDATE_STATUSES) else None)
        counts = {k: 0 for k, _ in CANDIDATE_STATUSES}
        for c in store.candidates():
            counts[c["status"]] = counts.get(c["status"], 0) + 1
        return render_template("candidates.html", page="candidates", rows=rows, counts=counts, status=status)

    @app.post("/candidates/<int:cid>")
    def update_candidate(cid):
        f = request.form
        try:
            store.update_candidate(cid, f.get("status", "not_contacted"), f.get("rep", "").strip(), f.get("notes", "").strip())
        except ValueError:
            abort(400)
        return redirect(url_for("candidates", note="cand-saved", status=request.args.get("status") or None))

    @app.post("/candidates/<int:cid>/delete")
    def delete_candidate(cid):
        store.delete_candidate(cid)
        return redirect(url_for("candidates", note="cand-deleted"))

    @app.post("/candidates/export")
    def export_candidates():
        rows = store.candidates()
        if not rows:
            return redirect(url_for("candidates", note="export-empty"))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["candidate_id", "place", "place_kind", "address", "latitude", "longitude", "location_precision",
                    "event", "demo", "tier", "reasons", "evidence", "status", "rep", "notes", "evidence_assessed_at",
                    "exported_at", "note"])
        stamp = wx.iso(wx.utcnow())
        for c in rows:
            ev = "; ".join(f"{wx.KIND_LABEL.get(e['kind'], e['kind'])}{' (DEMO)' if e.get('demo') else ''} · "
                           f"{e['provider']} · {e['magnitude'] if e['magnitude'] is not None else 'unknown'}"
                           f"{e['unit'] or ''} · {e['valid_from'] or 'no time'} · {e['source_url'] or ''}"
                           for e in c["evidence"].get("evidence", []))
            w.writerow([c["id"], csv_safe(c["place_name"]), c["place_kind"], csv_safe(c["place_address"]),
                        c["place_lat"], c["place_lng"], c["place_precision"], csv_safe(c["event_label"]),
                        "yes" if c["demo"] else "no", c["tier"] or "", csv_safe(" | ".join(c["reasons"])),
                        csv_safe(ev), dict(CANDIDATE_STATUSES)[c["status"]], csv_safe(c["rep"]),
                        csv_safe(c["notes"]), c["evidence"].get("assessed_at"), stamp, DISCLAIMER])
        return deliver(f"inspection-candidates-{date.today().isoformat()}.csv", buf.getvalue().encode("utf-8-sig"),
                       "text/csv", "candidates", note="exported", n=len(rows))

    def summary_html(c, saving=False) -> str:
        ev = [wx.Evidence(**{k: v for k, v in e.items() if k in wx.Evidence.__dataclass_fields__})
              for e in c["evidence"].get("evidence", [])]
        return render_template("summary.html", c=c, ev=ev, svg=maps.exposure_svg(c, ev),
                               generated=wx.utcnow(), tzname=c.get("place_tz") or tz(), saving=saving)

    @app.get("/candidates/<int:cid>/summary")
    def candidate_summary(cid):
        c = store.candidate(cid)
        if not c:
            abort(404)
        return summary_html(c)

    @app.post("/candidates/<int:cid>/summary")
    def save_summary(cid):
        c = store.candidate(cid)
        if not c:
            abort(404)
        safe = "".join(ch if ch.isalnum() else "-" for ch in c["place_name"]).strip("-")[:40] or "property"
        return deliver(f"weather-exposure-{safe}-{date.today().isoformat()}.html", summary_html(c, saving=True).encode("utf-8"),
                       "text/html", "candidates")

    # ======================================================================
    # Crew Outlook
    # ======================================================================
    @app.get("/outlook")
    def outlook():
        jobs = store.places("job")
        results = list(pool.map(lambda p: job_outlook(p, job_date(p, None)), jobs)) if jobs else []
        cards = [{"p": p, "o": o} for p, o in zip(jobs, results)]
        return render_template("outlook.html", page="outlook", cards=cards, rules=setting("rules"),
                               rule_fields=wx.RULE_FIELDS)

    @app.get("/outlook/<int:pid>")
    def outlook_job(pid):
        p = store.place(pid)
        if not p:
            abort(404)
        try:
            wd = date.fromisoformat(request.args["date"]) if request.args.get("date") else job_date(p, None)
        except ValueError:
            wd = None
        o = job_outlook(p, wd)
        reviews, acks = store.signoffs(pid, o["work_date"].isoformat())
        try:
            overrides = json.loads(p.get("rules") or "{}")
        except ValueError:
            overrides = {}
        return render_template("outlook_job.html", page="outlook", p=p, o=o, work_date=o["work_date"].isoformat(),
                               reviews=reviews, acks=acks, rule_fields=wx.RULE_FIELDS, overrides=overrides,
                               company=setting("rules"))

    @app.post("/outlook/<int:pid>/review")
    def outlook_review(pid):
        f = request.form
        if not f.get("reviewer", "").strip():
            return redirect(url_for("outlook_job", pid=pid, date=f.get("work_date"), note="signoff-bad"))
        store.add_review(pid, f.get("work_date", ""), f.get("outlook", ""), f["reviewer"].strip(),
                         f.get("decision", ""), f.get("note", "").strip())
        return redirect(url_for("outlook_job", pid=pid, date=f.get("work_date"), note="review-saved"))

    @app.post("/outlook/<int:pid>/ack")
    def outlook_ack(pid):
        f = request.form
        if not f.get("crew_member", "").strip():
            return redirect(url_for("outlook_job", pid=pid, date=f.get("work_date"), note="signoff-bad"))
        store.add_ack(pid, f.get("work_date", ""), f["crew_member"].strip())
        return redirect(url_for("outlook_job", pid=pid, date=f.get("work_date"), note="ack-saved"))

    @app.post("/outlook/<int:pid>/job")
    def save_job(pid):
        p = store.place(pid)
        if not p:
            abort(404)
        f = request.form
        wd = (f.get("work_date") or "").strip()
        try:
            if wd:
                date.fromisoformat(wd)
        except ValueError:
            return redirect(url_for("outlook_job", pid=pid, note="job-bad", msg="Use a real date for the work day."))
        dur, dry = fnum(f.get("duration_h"), 0, 240), fnum(f.get("dryin_h"), 0, 240)
        if (f.get("duration_h") and dur is None) or (f.get("dryin_h") and dry is None):
            return redirect(url_for("outlook_job", pid=pid, note="job-bad", msg="Hours must be numbers from 0 to 240."))
        overrides = {}
        for fld in wx.RULE_FIELDS:
            raw = (f.get("rule_" + fld["key"]) or "").strip()
            if raw:
                v = fnum(raw, -60, 200)
                if v is None:
                    return redirect(url_for("outlook_job", pid=pid, note="job-bad", msg=f"{fld['label']}: use a number."))
                overrides[fld["key"]] = v
        phase = f.get("phase") if f.get("phase") in dict(wx.PHASES) else None
        store.update_job(pid, f.get("roof_system", "").strip(), f.get("product", "").strip(), phase, wd or None,
                         dur, dry, f.get("site_checks", "").strip(), overrides)
        return redirect(url_for("outlook_job", pid=pid, note="job-saved"))

    # ======================================================================
    # Places
    # ======================================================================
    @app.get("/places")
    def places():
        q = (request.args.get("q") or "").strip()
        results, err = geocoder.search(q) if q else ([], None)
        return render_template("places.html", page="places", q=q, results=results, search_error=err,
                               jobs=store.places("job"), props=store.places("property"),
                               territories=store.territories())

    @app.post("/places")
    def add_place():
        f = request.form
        lat, lng = fnum(f.get("lat"), -90, 90), fnum(f.get("lng"), -180, 180)
        name = (f.get("name") or "").strip()
        back = f.get("back") if f.get("back") in ("live", "places") else "places"
        if not name or lat is None or lng is None or f.get("kind") not in ("job", "property"):
            return redirect(url_for(back, note="place-bad"))
        pid = store.add_place(f["kind"], name, f.get("address", "").strip(), lat, lng,
                              f.get("precision") or "typed", f.get("located_by") or "typed coordinates",
                              f.get("notes", "").strip())
        if net:
            try:   # its NWS zones, so zone/county alerts can match it right away
                info = forecasts.point(lat, lng)
                store.set_place_codes(pid, info.get("zone"), info.get("county"), info.get("fire_zone"), info.get("tz"))
            except wx.FeedError:
                pass  # the background check retries
        return redirect(url_for(back, note="place-saved", what="Job" if f["kind"] == "job" else "Property"))

    @app.post("/places/<int:pid>/delete")
    def delete_place(pid):
        store.delete_place(pid)
        return redirect(url_for("places", note="place-deleted"))

    # ======================================================================
    # Data sources & settings
    # ======================================================================
    @app.get("/sources")
    def sources():
        fp = footprint_source()
        live = [radar.feed.view(tz()), alerts.feed.view(tz()), spc.feed.view(tz()),
                wx.Feed("forecast", "Job forecasts", "National Weather Service", wx.NWS, state="on_demand" if net else "off",
                        detail="Hourly, gridpoint (gusts, rain amount, WBGT) and 7-day forecasts, fetched per job.").view(tz()),
                wx.Feed("geocode", "Address & place search", "U.S. Census geocoder · OpenStreetMap",
                        wx.Geocoder.CENSUS, state="on_demand" if net else "off",
                        detail="Street addresses from the Census Bureau; cities and ZIP codes from OpenStreetMap "
                               "(© OpenStreetMap contributors). Address precision is not weather precision.").view(tz()),
                fp.feed.view(tz())]
        return render_template("sources.html", page="sources", live=live, extra=CANDIDATE_FEEDS, review_src=REVIEW_SRC,
                               contracts=wx.CONTRACTS, coverage=wx.COVERAGE, footprint=setting("footprint"),
                               spc_cfg=setting("spc"), targeting=setting("targeting"), notify=setting("notify"),
                               zones=ZONES)

    @app.post("/settings/<name>")
    def save_settings(name):
        f = request.form
        back = "outlook" if name == "rules" else "sources"
        if name == "footprint":
            src, url = f.get("source"), (f.get("url") or "").strip()
            if src not in ("none", "demo", "geojson") or (src == "geojson" and not url.startswith("https://")):
                return redirect(url_for(back, note="settings-bad", msg="Choose a source; a GeoJSON feed needs an https:// address."))
            store.set_setting("footprint", {"source": src, "url": url})
        elif name == "spc":
            store.set_setting("spc", {"filtered": f.get("filtered") == "1", "area": "all" if f.get("area") == "all" else "MT"})
        elif name == "targeting":
            vals = {k: fnum(f.get(k), 0.1, 50) for k in wx.DEFAULT_TARGETING}
            if None in vals.values():
                return redirect(url_for(back, note="settings-bad", msg="Use numbers between 0.1 and 50."))
            store.set_setting("targeting", vals)
        elif name == "notify":
            vals = {"hail_in": fnum(f.get("hail_in"), 0.25, 5), "radius_mi": fnum(f.get("radius_mi"), 0.5, 50),
                    "os": f.get("os") if f.get("os") in ("severe", "all", "off") else "severe"}
            if vals["hail_in"] is None or vals["radius_mi"] is None:
                return redirect(url_for(back, note="settings-bad", msg="Hail 0.25–5 inches; distance 0.5–50 miles."))
            store.set_setting("notify", vals)
        elif name == "rules":
            vals = {}
            for fld in wx.RULE_FIELDS:
                raw = (f.get(fld["key"]) or "").strip()
                v = fnum(raw, -60, 200) if raw else None
                if raw and v is None:
                    return redirect(url_for(back, note="settings-bad", msg=f"{fld['label']}: use a number."))
                vals[fld["key"]] = v
            vals["daylight_only"] = f.get("daylight_only") == "1"
            store.set_setting("rules", vals)
        elif name == "tz":
            if f.get("tz") not in ZONES:
                return redirect(url_for(back, note="settings-bad", msg="Pick a time zone from the list."))
            store.set_setting("display_tz", f["tz"])
        else:
            abort(404)
        return redirect(url_for(back, note="settings-saved"))

    # ======================================================================
    # App & updates (desktop)
    # ======================================================================
    @app.get("/app")
    def app_page():
        db_size = os.path.getsize(cfg["DB_PATH"]) if os.path.exists(cfg["DB_PATH"]) else 0
        return render_template("app.html", page="app", info=shell_call("info", default={}) or {},
                               counts=store.counts(), db_size=db_size, db_path=cfg["DB_PATH"], schema=store.schema())

    @app.post("/app/check")
    def app_check():
        if shell is None:
            return redirect(url_for("app_page", note="no-shell"))
        shell_call("check_updates")
        return redirect(url_for("app_page"))

    @app.post("/app/update")
    def app_update():
        res = shell_call("apply_update", default={"ok": False, "message": "That only works in the desktop app."})
        if res.get("ok"):
            return redirect(url_for("live", note="updated", v=res.get("version", "")))
        return redirect(url_for("app_page", note="update-failed", msg=res.get("message", "")))

    @app.post("/app/rollback")
    def app_rollback():
        res = shell_call("rollback", default={"ok": False, "message": "That only works in the desktop app."})
        return redirect(url_for("app_page", note="rolled-back" if res.get("ok") else "rollback-failed",
                                msg=res.get("message", "")))

    @app.post("/app/source")
    def app_source():
        f = request.form
        res = shell_call("set_update_source", f.get("repo", ""), f.get("branch", ""), f.get("token", ""),
                         bool(f.get("clear_token")), default={"ok": False, "message": "That only works in the desktop app."})
        if res.get("ok"):
            shell_call("check_updates")
            return redirect(url_for("app_page", note="source-saved"))
        return redirect(url_for("app_page", note="source-bad", msg=res.get("message", "")))

    @app.post("/app/open-data")
    def app_open_data():
        shell_call("open_data_folder")
        return redirect(url_for("app_page"))

    @app.post("/app/quit")
    def app_quit():
        shell_call("quit")
        return "<p style='font-family:system-ui'>Montana Hail Watch has closed. You can close this tab.</p>"

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True, version=VERSION, schema=store.schema(), **store.counts())

    return app
