"""
Handoff acceptance checks for the weather module (no network needed).

    python -m unittest discover -s tests -v
"""

import csv
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
import updater as upd  # noqa: E402

PAYLOAD = upd.load_payload(ROOT / "payload", tag="test")
wx = sys.modules[PAYLOAD.__name__ + ".weather"]
store_mod = sys.modules[PAYLOAD.__name__ + ".store"]
UTC = timezone.utc


def feature(aid, event="Severe Thunderstorm Warning", mtype="Alert", refs=(), geometry=None, ugc=(),
            expires="2099-01-01T00:00:00+00:00", hail=None):
    params = {"maxHailSize": [str(hail)]} if hail else {}
    return {"id": f"https://api.weather.gov/alerts/{aid}", "geometry": geometry,
            "properties": {"id": aid, "event": event, "messageType": mtype, "areaDesc": "Test County",
                           "sent": "2026-06-15T20:00:00+00:00", "expires": expires, "ends": expires,
                           "references": [{"identifier": r} for r in refs], "parameters": params,
                           "geocode": {"UGC": list(ugc)},
                           "affectedZones": [f"https://api.weather.gov/zones/forecast/{u}" for u in ugc]}}


SQUARE = {"type": "Polygon", "coordinates": [[[-109, 45], [-108, 45], [-108, 46], [-109, 46], [-109, 45]]]}


class SPCReports(unittest.TestCase):
    def test_175_is_1_75_inches(self):
        self.assertEqual(wx.spc_hail_inches("175"), 1.75)
        self.assertEqual(wx.spc_hail_inches("100"), 1.0)
        self.assertIsNone(wx.spc_hail_inches(""))
        self.assertIsNone(wx.spc_hail_inches("0"))

    def test_unknown_wind_stays_unknown(self):
        self.assertIsNone(wx.spc_wind_mph("UNK"))
        self.assertEqual(wx.spc_wind_mph("62"), 62.0)
        rows = wx.parse_spc_csv("Time,Speed,Location,County,State,Lat,Lon,Comments\n"
                                "1253,UNK,Elmer,Jackson,OK,34.48,-99.35,Barn roof off\n", date(2025, 6, 15), "wind")
        self.assertIsNone(rows[0].magnitude)
        self.assertIsNone(rows[0].unit)

    def test_reporting_day_runs_12z_to_12z(self):
        d = date(2025, 6, 15)
        self.assertEqual(wx.spc_time_to_utc(d, "1200"), datetime(2025, 6, 15, 12, 0, tzinfo=UTC))
        self.assertEqual(wx.spc_time_to_utc(d, "0101"), datetime(2025, 6, 16, 1, 1, tzinfo=UTC))
        self.assertEqual(wx.spc_time_to_utc(d, "1159"), datetime(2025, 6, 16, 11, 59, tzinfo=UTC))
        self.assertEqual(wx.spc_day_for(datetime(2025, 6, 16, 11, 59, tzinfo=UTC)), date(2025, 6, 15))
        self.assertEqual(wx.spc_day_for(datetime(2025, 6, 16, 12, 0, tzinfo=UTC)), date(2025, 6, 16))

    def test_utc_and_local_midnight_keep_correct_dates(self):
        t = wx.spc_time_to_utc(date(2025, 6, 15), "0600")          # 06:00 UTC June 16
        local = t.astimezone(wx.zone("America/Denver"))
        self.assertEqual(local.date(), date(2025, 6, 16))           # local date: June 16, 00:00 MDT
        self.assertEqual(wx.spc_day_for(t), date(2025, 6, 15))      # but still SPC's June 15 reporting day
        self.assertIn("Jun 16, 12:00 AM MDT", wx.fmt_local(t, "America/Denver"))

    def test_daylight_saving_changes(self):
        # Fall back: 2025-11-02 08:00 UTC is 2:00 MDT -> 1:00 MST
        before = wx.spc_time_to_utc(date(2025, 11, 1), "0730")
        after = wx.spc_time_to_utc(date(2025, 11, 1), "0830")
        self.assertIn("1:30 AM MDT", wx.fmt_local(before, "America/Denver"))
        self.assertIn("1:30 AM MST", wx.fmt_local(after, "America/Denver"))
        self.assertNotEqual(before, after)                          # same wall clock, different instants
        # Spring forward: 2025-03-09 09:00 UTC is 2:00 MST -> 3:00 MDT
        self.assertIn("3:30 AM MDT", wx.fmt_local(wx.spc_time_to_utc(date(2025, 3, 8), "0930"), "America/Denver"))

    def test_duplicate_lines_and_commas_in_comments(self):
        text = ("Time,Size,Location,County,State,Lat,Lon,Comments\n"
                "2010,175,Benchland,Judith Basin,MT,47.08,-110.02,Golf ball, a few minutes\n"
                "2010,175,Benchland,Judith Basin,MT,47.08,-110.02,Golf ball, a few minutes\n")
        rows = wx.parse_spc_csv(text, date(2025, 6, 15), "hail")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].raw["comments"], "Golf ball, a few minutes")
        self.assertEqual(rows[0].kind, "point_report")
        self.assertEqual(rows[0].status, "preliminary")


class AlertLifecycle(unittest.TestCase):
    now = datetime(2026, 6, 15, 21, 0, tzinfo=UTC)

    def test_update_supersedes(self):
        k = wx.reconcile_alerts({}, [feature("A")], self.now)
        k = wx.reconcile_alerts(k, [feature("B", mtype="Update", refs=["A"])], self.now)
        self.assertEqual(k["A"]["status"], "updated")
        self.assertEqual(k["B"]["status"], "active")

    def test_cancel(self):
        k = wx.reconcile_alerts({}, [feature("A")], self.now)
        k = wx.reconcile_alerts(k, [feature("C", mtype="Cancel", refs=["A"])], self.now)
        self.assertEqual(k["A"]["status"], "cancelled")
        self.assertNotEqual(k["C"]["status"], "active")

    def test_update_before_original_in_one_batch(self):
        k = wx.reconcile_alerts({}, [feature("B", mtype="Update", refs=["A"]), feature("A")], self.now)
        self.assertEqual(k["A"]["status"], "updated")
        self.assertEqual(k["B"]["status"], "active")

    def test_update_seen_in_an_earlier_fetch_than_original(self):
        k = wx.reconcile_alerts({}, [feature("B", mtype="Update", refs=["A"])], self.now)
        k = wx.reconcile_alerts(k, [feature("B", mtype="Update", refs=["A"]), feature("A")], self.now)
        self.assertEqual(k["A"]["status"], "updated")

    def test_cancel_seen_before_original(self):
        k = wx.reconcile_alerts({}, [feature("C", mtype="Cancel", refs=["A"])], self.now)
        k = wx.reconcile_alerts(k, [feature("A")], self.now)
        self.assertEqual(k["A"]["status"], "cancelled")

    def test_duplicates_in_a_batch(self):
        k = wx.reconcile_alerts({}, [feature("A"), feature("A")], self.now)
        self.assertEqual([r["status"] for r in k.values()], ["active"])

    def test_expiry_and_disappearance(self):
        k = wx.reconcile_alerts({}, [feature("A", expires="2026-06-15T20:30:00+00:00")], self.now)
        self.assertEqual(k["A"]["status"], "expired")
        k = wx.reconcile_alerts({}, [feature("B")], self.now)
        k = wx.reconcile_alerts(k, [], self.now)           # successful fetch, no longer listed
        self.assertEqual(k["B"]["status"], "archived")

    def test_outage_never_clears_a_warning(self):
        saved = {}
        svc = wx.AlertService(wx.Http("test"), lambda: dict(saved), lambda d: saved.update(d))

        def fail(*a, **k):
            raise wx.FeedError("no connection to the National Weather Service")
        saved.update(wx.reconcile_alerts({}, [feature("A")], wx.utcnow()))
        svc.http.json = fail
        svc._refresh()
        self.assertEqual([a["id"] for a in svc.active()], ["A"])
        self.assertIn(svc.feed.judge().state, ("stale", "unavailable"))
        self.assertTrue(svc.feed.error)


class AlertGeography(unittest.TestCase):
    """Independent review P0: polygon, county, zone and null-geometry matching."""
    place = {"lat": 45.5, "lng": -108.5, "nws_zone": "MTZ235", "nws_county": "MTC111", "nws_fire_zone": "MTZ130"}

    def rec(self, **kw):
        return wx.normalize_alert(feature("X", **kw), datetime.now(UTC))

    def test_polygon(self):
        self.assertEqual(wx.applies_to_place(self.rec(geometry=SQUARE), self.place), (True, "warning polygon"))
        far = {**self.place, "lat": 47.0}
        self.assertEqual(wx.applies_to_place(self.rec(geometry=SQUARE), far)[0], False)

    def test_null_geometry_by_zone_county_and_fire_zone(self):
        self.assertEqual(wx.applies_to_place(self.rec(ugc=["MTZ235"]), self.place), (True, "forecast zone MTZ235"))
        self.assertEqual(wx.applies_to_place(self.rec(ugc=["MTC111"]), self.place), (True, "county MTC111"))
        self.assertEqual(wx.applies_to_place(self.rec(ugc=["MTZ130"]), self.place)[0], True)
        self.assertEqual(wx.applies_to_place(self.rec(ugc=["MTZ999"]), self.place)[0], False)

    def test_null_geometry_is_never_no_alert(self):
        unknown_place = {"lat": 45.5, "lng": -108.5}
        self.assertIsNone(wx.applies_to_place(self.rec(ugc=["MTZ235"]), unknown_place)[0])
        self.assertIsNone(wx.applies_to_place(self.rec(), self.place)[0])     # no polygon and no zones

    def test_hole_and_edge(self):
        holey = {"type": "Polygon", "coordinates": [SQUARE["coordinates"][0],
                                                     [[-108.7, 45.3], [-108.3, 45.3], [-108.3, 45.7], [-108.7, 45.7], [-108.7, 45.3]]]}
        self.assertFalse(wx.point_in(holey, 45.5, -108.5))
        self.assertTrue(wx.point_in(holey, 45.1, -108.9))
        self.assertTrue(wx.point_in(SQUARE, 45.0001, -108.9999))   # just inside the corner
        self.assertFalse(wx.point_in(SQUARE, 44.9999, -108.5))     # just outside the edge

    def test_territory_by_zone_boundary(self):
        terr = {"type": "Polygon", "coordinates": [[[-108.6, 45.4], [-108.4, 45.4], [-108.4, 45.6], [-108.6, 45.6], [-108.6, 45.4]]]}
        a = self.rec(ugc=["MTZ235"])
        url = a["zones"][0]
        self.assertEqual(wx.applies_to_area(a, terr, {})[0], None)              # boundary not loaded: "can't tell"
        self.assertEqual(wx.applies_to_area(a, terr, {url: SQUARE})[0], True)
        far = {"type": "Polygon", "coordinates": [[[-100, 40], [-99, 40], [-99, 41], [-100, 41], [-100, 40]]]}
        self.assertEqual(wx.applies_to_area(a, terr, {url: far})[0], False)


class FeedsAndOutlook(unittest.TestCase):
    def test_feed_states(self):
        f = wx.Feed("radar", "Radar", "NOAA", "")
        self.assertEqual(f.judge().state, "unavailable")
        f.source_time = wx.utcnow()
        self.assertEqual(f.judge().state, "live")
        f.source_time = wx.utcnow() - timedelta(hours=2)
        self.assertEqual(f.judge().state, "stale")
        f.source_time, f.error = wx.utcnow(), "timeout"
        self.assertEqual(f.judge().state, "stale")
        self.assertEqual(wx.Feed("footprint", "x", "x", "", state="demo").judge().state, "demo")

    def test_missing_input_is_never_an_all_clear(self):
        hour = {"temp_f": 60, "precip_pct": 0, "wind_mph": 5, "gust_mph": None, "daytime": True}
        self.assertEqual(wx.evaluate_hour(hour, wx.DEFAULT_RULES)["status"], "unavailable")
        hour["gust_mph"] = 10
        self.assertEqual(wx.evaluate_hour(hour, wx.DEFAULT_RULES)["status"], "meets")
        self.assertEqual(wx.evaluate_hour(hour, wx.DEFAULT_RULES, alerts_ok=False)["status"], "unavailable")
        self.assertEqual(wx.evaluate_hour(hour, wx.DEFAULT_RULES, alerts=[{"event": "Wind Advisory"}])["status"], "review")

    def test_job_rules_override_company_rules(self):
        rules, src = wx.merge_rules(wx.DEFAULT_RULES, {"min_temp_f": 50})
        ev = wx.evaluate_hour({"temp_f": 45, "precip_pct": 0, "wind_mph": 5, "gust_mph": 5, "daytime": True}, rules, source=src)
        self.assertEqual(ev["status"], "review")
        self.assertIn("(job rule)", ev["triggers"][0])

    def test_units(self):
        self.assertEqual(wx.wind_range_mph("10 to 15 mph"), (10, 15))
        self.assertEqual(wx.duration_hours("PT6H"), 6)
        self.assertEqual(wx.duration_hours("P1DT6H"), 30)
        series = wx.expand_series({"values": [{"validTime": "2026-10-11T06:00:00+00:00/PT2H", "value": 40}]},
                                  lambda v: v * wx.KMH_TO_MPH)
        self.assertEqual(len(series), 2)
        self.assertAlmostEqual(list(series.values())[0], 24.85, places=1)
        self.assertAlmostEqual(wx._to_f({"uom": "wmoUnit:degC"})(30), 86.0)

    def test_window_length(self):
        t0 = datetime(2026, 6, 15, 15, tzinfo=UTC)
        hours = [{"start": t0 + timedelta(hours=i), "eval": {"status": "meets" if i < 4 else "review"}} for i in range(8)]
        self.assertTrue(wx.phase_fit(hours, 4)["fits"])
        self.assertFalse(wx.phase_fit(hours, 6)["fits"])
        self.assertIsNone(wx.phase_fit(hours, None)["fits"])


class Targeting(unittest.TestCase):
    place = {"lat": 47.085, "lng": -110.03}

    def report(self, size, lat=47.08, lon=-110.02):
        return wx.Evidence(id="r", provider="SPC", source_record_id="r", kind="point_report", hazard="hail",
                           issued_at=None, valid_from="2025-06-15T20:10:00+00:00", valid_to=None, received_at="",
                           geometry={"type": "Point", "coordinates": [lon, lat]}, spatial_resolution_m=None,
                           magnitude=size, unit="in", status="preliminary")

    def test_estimates_and_reports_stay_distinct(self):
        demo = wx.DemoFootprint(ROOT / "payload" / "fixtures" / "demo_hail_footprint.geojson")
        est = demo.footprints("demo")
        inside = {"lat": 45.785, "lng": -108.585}
        a = wx.assess_place(inside, [self.report(1.0, 45.79, -108.59)], est, {})
        kinds = [e["kind"] for e in a["evidence"]]
        self.assertIn("radar_estimate", kinds)
        self.assertIn("point_report", kinds)
        self.assertTrue(any("estimated" in r for r in a["reasons"]))
        self.assertTrue(any("report" in r for r in a["reasons"]))

    def test_no_report_is_not_an_all_clear(self):
        a = wx.assess_place(self.place, [], [], {})
        self.assertIsNone(a["tier"])
        self.assertIn("not evidence that no hail fell", a["reasons"][0])

    def test_tiers(self):
        self.assertEqual(wx.assess_place(self.place, [self.report(1.75)], [], {})["tier"], 1)
        self.assertEqual(wx.assess_place(self.place, [self.report(1.0)], [], {})["tier"], 2)
        self.assertEqual(wx.assess_place(self.place, [self.report(0.5)], [], {})["tier"], 3)

    def test_demo_never_appears_for_a_real_date(self):
        demo = wx.DemoFootprint(ROOT / "payload" / "fixtures" / "demo_hail_footprint.geojson")
        self.assertEqual(demo.footprints("2025-06-15"), [])
        self.assertTrue(all(f.demo for f in demo.footprints("demo")))
        self.assertEqual(demo.feed.judge().state, "demo")


class AppLevel(unittest.TestCase):
    """Matching, dedupe, idempotency and exports through the real app."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = []
        test = self

        class Shell:
            notes = []

            def notify(self, t, b):
                self.notes.append((t, b))

            def save_file(self, name, data):
                p = Path(test.tmp) / name
                p.write_bytes(data)
                test.saved.append(p)
                return str(p)

        self.shell = Shell()
        self.app = PAYLOAD.create_app({"DATA_DIR": self.tmp, "NETWORK": False, "SHELL": self.shell,
                                       "TESTING": True, "BACKGROUND": False})
        self.c = self.app.test_client()
        self.store = store_mod.Store(str(Path(self.tmp) / "hailwatch.db"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_matching_dedupe_and_idempotent_candidates(self):
        pid = self.store.add_place("job", "Grand Ave", "", 45.78, -108.57, "address", "test")
        self.store.set_place_codes(pid, "MTZ235", "MTC111", None, "America/Denver")
        now = wx.utcnow()
        self.store.save_alerts(wx.reconcile_alerts({}, [
            feature("Z1", event="Winter Storm Warning", ugc=["MTZ235"]),                 # zone alert, no polygon
            feature("P1", geometry=SQUARE, hail=1.75),                                    # polygon alert
            feature("N1", event="Wind Advisory", ugc=["MTZ999"])], now))                  # elsewhere
        self.c.get("/")
        notices = self.store.notices()
        titles = sorted(n["title"] for n in notices)
        self.assertEqual(titles, ["Official alert: Severe Thunderstorm Warning", "Official alert: Winter Storm Warning"])
        self.assertTrue(any("matched by forecast zone MTZ235" in n["body"] for n in notices))
        self.assertEqual(len(self.shell.notes), 1)              # desktop pop-up only for the severe one
        self.c.get("/")
        self.assertEqual(len(self.store.notices()), 2)          # repeated ingestion: no duplicates
        self.assertEqual(len(self.shell.notes), 1)

        self.assertTrue(self.store.upsert_candidate(pid, "spc:2025-06-15", "day", 1, ["r"], {"evidence": []}, False))
        cid = self.store.candidates()[0]["id"]
        self.store.update_candidate(cid, "scheduled", "Rep", "")
        self.assertFalse(self.store.upsert_candidate(pid, "spc:2025-06-15", "day", 2, ["r2"], {"evidence": []}, False))
        rows = self.store.candidates()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "scheduled")       # re-adding never resets progress

    def test_exports_keep_sources_and_timestamps(self):
        pid = self.store.add_place("property", "Benchland", "", 47.085, -110.03, "typed", "test")
        ev = Targeting().report(1.75)
        ev.source_url = "https://www.spc.noaa.gov/climo/reports/250615_rpts.html"
        self.store.upsert_candidate(pid, "spc:2025-06-15", "SPC reporting day Jun 15, 2025", 1, ["Nearest report 1.75″"],
                                    {"evidence": [ev.to_dict()], "assessed_at": wx.iso(wx.utcnow()), "sources": ["SPC"],
                                     "targeting": wx.DEFAULT_TARGETING, "event_window_utc": None}, False)
        self.c.post("/candidates/export")
        rows = list(csv.DictReader(io.StringIO(self.saved[-1].read_text(encoding="utf-8-sig"))))
        self.assertIn("spc.noaa.gov", rows[0]["evidence"])
        self.assertTrue(rows[0]["exported_at"] and rows[0]["evidence_assessed_at"])
        self.assertIn("does not confirm roof damage", rows[0]["note"])
        html = self.c.get("/candidates/1/summary").get_data(as_text=True)
        for must in ("does not confirm roof damage", "Reported hail (SPC, preliminary)", "generated", "<svg", "Sources and timing"):
            self.assertIn(must, html)

    def test_every_page_renders_offline(self):
        for path in json.loads((ROOT / "payload" / "manifest.json").read_text())["selftest"]:
            self.assertLess(self.c.get(path).status_code, 400, path)


class Wording(unittest.TestCase):
    def test_never_claims_damage_eligibility_or_probability(self):
        text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "payload").rglob("*") if p.suffix in (".py", ".html"))
        for pattern in (r"confirm(?:ed|s)? (?:roof )?damage", r"damage (?:is )?confirmed", r"insurance eligib",
                        r"(?:probability|chance|likelihood) of damage", r"damage probability", r"damaged roofs?"):
            for m in re.finditer(pattern, text, re.I):
                before = text[max(0, m.start() - 40):m.start()].lower()
                self.assertTrue(re.search(r"\b(not|never|no|nothing|does not|doesn't)\b", before),
                                f"unqualified claim: …{text[m.start() - 40:m.end() + 20]}…")


if __name__ == "__main__":
    unittest.main()
