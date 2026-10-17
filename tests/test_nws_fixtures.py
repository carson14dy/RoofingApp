"""
Real-data checks for the Now page's alerts (ROADMAP release gate: curated real Montana cases).

tests/fixtures/nws/ holds NWS responses captured once on 2026-10-17 (see the README there). The
expected answers come from a standalone check in this file: point-in-polygon for an alert with an
outline, and membership of the UGC codes (forecast zone, county, fire weather zone) for an alert
without one. This file does not call the website's matching code. The website's answers come from
website/build.py's Collector, the same code the build runs, fed the captured responses by a fetcher
that serves only what was captured.

Two cases are replays, and are labelled as such: NWS's answer for a point at a past time was not
captured, so one test builds that answer from a real captured alert to check how the website keeps
each town's answer apart. Nothing else is invented.
"""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "nws"
sys.path.insert(0, str(ROOT))
from website import build as site  # noqa: E402
from website import sources as src  # noqa: E402

CAPTURED = datetime(2026, 10, 17, 1, 26, 6, tzinfo=timezone.utc)   # the statewide request
STATEWIDE_KEY = f"{src.NWS}/alerts/active?area=MT"
CROSS_PAIRS = [("helena", "cross-helena"), ("butte", "cross-butte"),
               ("havre", "cross-havre"), ("bozeman", "cross-bozeman")]


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def points():
    """slug -> the captured /points document: the 14 towns and the 4 cross-county points."""
    return {f.name[len("points-"):-len(".json")]: json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(FIXTURES.glob("points-*.json"))}


def history():
    return load("alerts-history-p1.json")["features"] + load("alerts-history-p2.json")["features"]


def active():
    return load("alerts-active-mt.json")["features"]


def place_lat_lon(point_doc):
    lon, lat = point_doc["geometry"]["coordinates"]
    return lat, lon


def point_key(point_doc):
    lat, lon = place_lat_lon(point_doc)
    return f"{src.NWS}/points/{lat:.4f},{lon:.4f}"


def point_alerts_key(point_doc):
    lat, lon = place_lat_lon(point_doc)
    return f"{src.NWS}/alerts/active?point={lat:.4f},{lon:.4f}"


# ---------------------------------------------------------------- the standalone expectation

def point_in_polygon(lon, lat, geometry):
    """Even-odd ray casting over every ring of a Polygon or MultiPolygon, so holes count as holes."""
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    inside = False
    for rings in polygons:
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
    return inside


def place_codes(point_doc):
    """The NWS codes a place is filed under: forecast zone, county and fire weather zone."""
    p = point_doc["properties"]
    links = (p.get("forecastZone"), p.get("county"), p.get("fireWeatherZone"))
    return {link.rstrip("/").rsplit("/", 1)[-1] for link in links if link}


def covers(feature, point_doc):
    """Does this alert apply to this place? Its outline decides when it has one; without one, its
    UGC codes must include one of the place's codes."""
    if feature["geometry"] is not None:
        lat, lon = place_lat_lon(point_doc)
        return point_in_polygon(lon, lat, feature["geometry"])
    ugc = set((feature["properties"].get("geocode") or {}).get("UGC") or [])
    return bool(ugc & place_codes(point_doc))


def standing(features):
    """The messages NWS's own fields leave standing: Actual, not a Cancel, and not named in the
    references of another message in the same response (an update or a cancellation)."""
    named = {r["identifier"] for f in features for r in f["properties"].get("references") or []}
    return [f for f in features if f["properties"]["status"] == "Actual"
            and f["properties"]["messageType"] != "Cancel" and f["properties"]["id"] not in named]


def expected_for(point_doc, features):
    return {f["properties"]["id"] for f in standing(features) if covers(f, point_doc)}


# ---------------------------------------------------------------- the website, fed captured data

class Captured:
    """Serves the captured responses the way the fetcher would. Anything not captured fails."""

    def __init__(self, docs):
        self.docs = docs

    def json(self, url, params=None):
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
        if key in self.docs:
            return self.docs[key], None
        return None, "not in the captured fixtures"

    def text(self, url):
        return None, "not in the captured fixtures"


def captured_docs():
    docs = {STATEWIDE_KEY: load("alerts-active-mt.json")}
    for slug, doc in points().items():
        docs[point_key(doc)] = doc
        docs[point_alerts_key(doc)] = load(f"alerts-point-{slug}.json")
    return docs


def places():
    """(slug, place dict for the build, /points document) for the 14 towns and the 4 cross points."""
    pts = points()
    towns = json.loads((ROOT / "website" / "towns.json").read_text(encoding="utf-8"))
    out = []
    for t in towns:
        lat, lon = place_lat_lon(pts[t["slug"]])
        out.append((t["slug"], {"slug": t["slug"], "name": t["name"], "lat": lat, "lon": lon}, pts[t["slug"]]))
    for slug in sorted(pts):
        if slug.startswith("cross-"):
            lat, lon = place_lat_lon(pts[slug])
            out.append((slug, {"slug": slug, "name": slug, "lat": lat, "lon": lon}, pts[slug]))
    return out


def run_alert_checks(docs):
    """The build's alert code, no network: the statewide check, then each place's point check, then
    the merge into the statewide list (what build.py does for the 14 towns)."""
    c = site.Collector(Captured(docs), CAPTURED)
    statewide = c.alerts()
    answers = {}
    for slug, place, _ in places():
        answers[slug] = c.town(place)
    towns = [answers[slug] for slug, _, _ in places() if not slug.startswith("cross-")]
    c.add_town_alerts(statewide, towns)
    return statewide, answers


def ids(alerts):
    return {a["id"] for a in alerts}


# ---------------------------------------------------------------- tests

class Fixtures(unittest.TestCase):
    def test_folder_is_under_2_mb_and_has_every_request(self):
        names = {f.name for f in FIXTURES.glob("*.json")}
        total = sum(f.stat().st_size for f in FIXTURES.glob("*.json"))
        self.assertLess(total, 2 * 1024 * 1024)
        self.assertLessEqual({"alerts-active-mt.json", "alerts-history-p1.json", "alerts-history-p2.json"}, names)
        for slug, _, _ in places():
            self.assertIn(f"points-{slug}.json", names)
            self.assertIn(f"alerts-point-{slug}.json", names)

    def test_the_fourteen_towns_are_captured_at_their_current_coordinates(self):
        pts = points()
        for t in json.loads((ROOT / "website" / "towns.json").read_text(encoding="utf-8")):
            with self.subTest(town=t["slug"]):
                lat, lon = place_lat_lon(pts[t["slug"]])
                self.assertEqual((f"{lat:.4f}", f"{lon:.4f}"), (f"{t['lat']:.4f}", f"{t['lon']:.4f}"))


class TownsAgreeWithNWS(unittest.TestCase):
    """For every place, the build's answer equals the standalone expectation (live captured data)."""

    @classmethod
    def setUpClass(cls):
        cls.statewide, cls.answers = run_alert_checks(captured_docs())
        cls.live = active()

    def test_each_town_gets_the_alerts_its_codes_and_outline_put_it_under(self):
        for slug, _, doc in places():
            if slug.startswith("cross-"):
                continue
            with self.subTest(town=slug):
                out = self.answers[slug]
                self.assertNotIn("Couldn't check official alerts", " ".join(out["errors"]))
                self.assertIsNotNone(out["alerts"])
                self.assertEqual(ids(out["alerts"]), expected_for(doc, self.live))

    def test_each_cross_county_point_gets_the_alerts_its_codes_and_outline_put_it_under(self):
        for slug, _, doc in places():
            if not slug.startswith("cross-"):
                continue
            with self.subTest(point=slug):
                out = self.answers[slug]
                self.assertNotIn("Couldn't check official alerts", " ".join(out["errors"]))
                self.assertEqual(ids(out["alerts"]), expected_for(doc, self.live))

    def test_the_statewide_list_names_every_standing_alert(self):
        self.assertEqual(ids(self.statewide["items"]), {f["properties"]["id"] for f in standing(self.live)})
        self.assertEqual(len(self.statewide["items"]), 3)

    def test_there_is_a_match_in_the_capture(self):
        # Kalispell (MTZ003) is the one place the capture covers, so the checks above are not empty.
        self.assertEqual({slug for slug, _, _ in places() if self.answers[slug]["alerts"]}, {"kalispell"})


class NullGeometry(unittest.TestCase):
    def test_an_alert_without_an_outline_is_never_reported_as_no_alert(self):
        statewide, answers = run_alert_checks(captured_docs())
        covered = 0
        for f in active():
            if f["geometry"] is not None:
                continue
            for slug, _, doc in places():
                if not covers(f, doc):
                    continue
                covered += 1
                with self.subTest(alert=f["properties"]["event"], place=slug):
                    self.assertIn(f["properties"]["id"], ids(answers[slug]["alerts"]))
                    self.assertIn(f["properties"]["id"], ids(statewide["items"]))
        self.assertGreaterEqual(covered, 1)

    def test_a_town_whose_point_check_fails_shows_not_checked_not_an_empty_list(self):
        docs = captured_docs()
        kalispell = points()["kalispell"]
        del docs[point_alerts_key(kalispell)]
        _, answers = run_alert_checks(docs)
        self.assertIsNone(answers["kalispell"]["alerts"])
        self.assertIn("Couldn't check official alerts", " ".join(answers["kalispell"]["errors"]))


class CountyLines(unittest.TestCase):
    def test_each_cross_point_is_in_another_county_and_forecast_zone(self):
        pts = points()
        for town, cross in CROSS_PAIRS:
            with self.subTest(pair=(town, cross)):
                a, b = pts[town]["properties"], pts[cross]["properties"]
                self.assertNotEqual(a["county"], b["county"])
                self.assertNotEqual(a["forecastZone"], b["forecastZone"])

    def test_each_side_of_a_county_line_gets_the_right_answer_live(self):
        # The live capture has no alert that covers one side only, so both sides are expected empty.
        # The replay below is the case that separates them.
        statewide, answers = run_alert_checks(captured_docs())
        pts = points()
        for town, cross in CROSS_PAIRS:
            for slug in (town, cross):
                with self.subTest(place=slug):
                    self.assertEqual(ids(answers[slug]["alerts"]), expected_for(pts[slug], active()))

    def test_replay_a_real_alert_covering_one_side_of_the_helena_line(self):
        """REPLAY. NWS's answer for Helena while this alert stood was not captured. The point answer
        below is that alert alone: a Winter Storm Warning sent 2026-10-11 10:29 MDT with UGC codes
        MTZ319, MTZ324 and MTZ325 and no outline. Helena (MTZ319) is covered; Jefferson County
        across the line (cross-helena: MTC043, MTZ322) is not. The alert expired and was superseded
        at 23:30 that day; the replay only tests how the website keeps the two answers apart."""
        alert = [f for f in history() if f["properties"]["event"] == "Winter Storm Warning"
                 and f["properties"]["sent"].startswith("2026-10-11T10:29")
                 and f["properties"]["messageType"] == "Alert"
                 and f["geometry"] is None
                 and set((f["properties"].get("geocode") or {}).get("UGC") or []) == {"MTZ319", "MTZ324", "MTZ325"}]
        self.assertEqual(len(alert), 1)
        pts = points()
        docs = captured_docs()
        docs[point_alerts_key(pts["helena"])] = {"type": "FeatureCollection", "features": alert}
        statewide, answers = run_alert_checks(docs)
        self.assertEqual(ids(answers["helena"]["alerts"]), expected_for(pts["helena"], alert))
        self.assertEqual(ids(answers["helena"]["alerts"]), {alert[0]["properties"]["id"]})
        self.assertEqual(ids(answers["cross-helena"]["alerts"]), expected_for(pts["cross-helena"], alert))
        self.assertEqual(ids(answers["cross-helena"]["alerts"]), set())
        self.assertIn(alert[0]["properties"]["id"], ids(statewide["items"]))


class History(unittest.TestCase):
    """The 30-day history: no point answers exist for past times, so these checks use the standalone
    expectation and the NWS fields, not the per-town answers."""

    def test_point_in_polygon_helper(self):
        square = {"type": "Polygon", "coordinates": [
            [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
            [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]]}
        self.assertTrue(point_in_polygon(0.2, 0.2, square))
        self.assertFalse(point_in_polygon(1, 1, square))      # inside the hole
        self.assertFalse(point_in_polygon(3, 1, square))
        multi = {"type": "MultiPolygon", "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]], [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]]]}
        self.assertTrue(point_in_polygon(5.5, 5.5, multi))
        self.assertFalse(point_in_polygon(3, 3, multi))

    def test_the_one_outline_in_30_days_is_a_polygon_no_place_is_inside(self):
        outlined = [f for f in history() if f["geometry"] is not None]
        self.assertEqual(len(outlined), 1)
        ring = outlined[0]["geometry"]["coordinates"][0]
        lon = (min(p[0] for p in ring) + max(p[0] for p in ring)) / 2
        lat = (min(p[1] for p in ring) + max(p[1] for p in ring)) / 2
        self.assertTrue(point_in_polygon(lon, lat, outlined[0]["geometry"]))
        for slug, _, doc in places():
            with self.subTest(place=slug):
                self.assertFalse(covers(outlined[0], doc))

    def test_the_website_keeps_an_outline_and_leaves_missing_outlines_missing(self):
        nws = {f["properties"]["id"]: f for f in history()}
        for a in src.parse_alerts({"features": history()}):
            with self.subTest(alert=a["id"]):
                self.assertEqual(a["geometry"] is None, nws[a["id"]]["geometry"] is None)

    def test_the_website_never_drops_a_message_the_nws_fields_leave_standing(self):
        listed = ids(src.parse_alerts({"features": history()}))
        self.assertLessEqual({f["properties"]["id"] for f in standing(history())}, listed)

    @unittest.expectedFailure
    def test_a_message_a_cancel_names_is_not_listed(self):
        # DISAGREES WITH NWS FIELDS. website/sources.py parse_alerts() and alert_references() skip
        # Cancel messages, so a Cancel's "references" never remove the message it cancels.
        # Input: tests/fixtures/nws/alerts-history-p1.json, read as one active list. 21 listed
        # messages are named by a Cancel in the same response (for example a Winter Storm Warning
        # Update sent 2026-10-11 12:25, cancelled 2026-10-12 03:48).
        cancelled = {r["identifier"] for f in history() if f["properties"]["messageType"] == "Cancel"
                     for r in f["properties"].get("references") or []}
        listed = ids(src.parse_alerts({"features": history()}))
        self.assertEqual(listed & cancelled, set())


class StandaloneExpectation(unittest.TestCase):
    """The expectation must not depend on website code: none of its functions may reference the
    website's modules or its matching functions."""

    def test_the_expectation_references_no_website_names(self):
        forbidden = {"src", "site", "Collector", "parse_alerts", "alert_references", "town",
                     "add_town_alerts", "alerts", "reading_now", "Fetcher"}
        for fn in (point_in_polygon, place_codes, place_lat_lon, covers, standing, expected_for):
            with self.subTest(fn=fn.__name__):
                names = set(fn.__code__.co_names) | set(fn.__code__.co_freevars)
                self.assertFalse(names & forbidden, names & forbidden)


if __name__ == "__main__":
    unittest.main()
