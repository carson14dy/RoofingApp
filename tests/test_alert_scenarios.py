"""
Independent-review P0 suite: alert geography x lifecycle x message order.

Each scenario replays a sequence of NWS fetches through the same functions the
app uses, then checks: the right revision is active, an applicable severe or
tornado warning is never missed, nothing that doesn't apply is matched, and a
second replay creates no duplicate notifications.

Also replays a synthetic busy storm day with a 30-minute outage and checks the
result equals an uninterrupted replay (no lost or wrong records).
"""

import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
import updater as upd  # noqa: E402

PAYLOAD = upd.load_payload(ROOT / "payload", tag="scen")
wx = sys.modules[PAYLOAD.__name__ + ".weather"]
UTC = timezone.utc
NOW = datetime(2026, 6, 15, 21, 0, tzinfo=UTC)
OUTAGE = object()


def box(w, s, e, n):
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


SITE = {"lat": 45.50, "lng": -108.50, "nws_zone": "MTZ235", "nws_county": "MTC111", "nws_fire_zone": "MTZ130"}
GEOGRAPHY = [  # name, geometry, ugc, applies?
    ("polygon contains site", {"type": "Polygon", "coordinates": [box(-109, 45, -108, 46)]}, ["MTC111"], True),
    ("polygon elsewhere", {"type": "Polygon", "coordinates": [box(-107, 45, -106, 46)]}, ["MTC111"], False),
    ("no polygon, forecast zone", None, ["MTZ235"], True),
    ("no polygon, county", None, ["MTC111"], True),
    ("no polygon, fire zone", None, ["MTZ130"], True),
    ("no polygon, other zones", None, ["MTZ999", "MTC045"], False),
    ("just inside polygon edge", {"type": "Polygon", "coordinates": [box(-108.501, 45, -108, 46)]}, [], True),
    ("just outside polygon edge", {"type": "Polygon", "coordinates": [box(-108.499, 45, -108, 46)]}, [], False),
    ("second part of a multipolygon", {"type": "MultiPolygon", "coordinates": [[box(-107, 45, -106, 46)],
                                                                              [box(-108.6, 45.4, -108.4, 45.6)]]}, [], True),
    ("inside a polygon hole", {"type": "Polygon", "coordinates": [box(-109, 45, -108, 46), box(-108.6, 45.4, -108.4, 45.6)]}, [], False),
]


def feat(aid, event, geom, ugc, mtype="Alert", refs=(), expires="2099-01-01T00:00:00+00:00"):
    return {"id": f"https://api.weather.gov/alerts/{aid}", "geometry": geom,
            "properties": {"id": aid, "event": event, "messageType": mtype, "areaDesc": "x",
                           "sent": "2026-06-15T20:00:00+00:00", "expires": expires, "ends": expires,
                           "references": [{"identifier": r} for r in refs], "parameters": {},
                           "geocode": {"UGC": list(ugc)},
                           "affectedZones": [f"https://api.weather.gov/zones/forecast/{u}" for u in ugc]}}


def lifecycles(event, geom, ugc):
    A = lambda **k: feat("A", event, geom, ugc, **k)                                   # noqa: E731
    B = lambda **k: feat("B", event, geom, ugc, mtype="Update", refs=["A"], **k)      # noqa: E731
    C = feat("C", event, geom, ugc, mtype="Cancel", refs=["A"])
    return [  # name, batches, ids expected active at the end
        ("single alert", [[A()]], {"A"}),
        ("update supersedes", [[A()], [B()]], {"B"}),
        ("cancel", [[A()], [C]], set()),
        ("update listed before original", [[B(), A()]], {"B"}),
        ("update fetched before original", [[B()], [A(), B()]], {"B"}),
        ("duplicates", [[A(), A()], [A()]], {"A"}),
        ("outage in the middle", [[A()], OUTAGE, OUTAGE, [A()]], {"A"}),
        ("already expired", [[A(expires="2026-06-15T20:30:00+00:00")]], set()),
    ]


def run(batches, order):
    known, rng = {}, random.Random(7)
    for b in batches:
        if b is OUTAGE:          # failed request: the app makes no change at all
            continue
        b = list(b)
        if order == "reversed":
            b.reverse()
        elif order == "shuffled":
            rng.shuffle(b)
        known = wx.reconcile_alerts(known, b, NOW)
    return known


class AlertScenarios(unittest.TestCase):
    def test_geography_x_lifecycle_x_order(self):
        count = 0
        for gi, (gname, geom, ugc, applies) in enumerate(GEOGRAPHY):
            event = "Tornado Warning" if gi % 2 else "Severe Thunderstorm Warning"
            for lname, batches, expected in lifecycles(event, geom, ugc):
                for order in ("as sent", "reversed", "shuffled"):
                    count += 1
                    with self.subTest(geography=gname, lifecycle=lname, order=order):
                        known = run(batches, order)
                        active = {a for a, r in known.items() if r.get("status") == "active"}
                        self.assertEqual(active, expected)
                        notices = set()
                        for _ in range(2):        # second replay must add nothing
                            known2 = run(batches, order)
                            new = 0
                            for aid in [a for a, r in known2.items() if r.get("status") == "active"]:
                                ok, how = wx.applies_to_place(known2[aid], SITE)
                                self.assertIsNotNone(ok, f"couldn't decide ({how})")
                                self.assertEqual(ok, applies, how)         # never missed, never wrongly matched
                                if ok and f"alert:{aid}:site" not in notices:
                                    notices.add(f"alert:{aid}:site")
                                    new += 1
                            if _ == 1:
                                self.assertEqual(new, 0)
        self.assertGreaterEqual(count, 100)
        print(f"\n  {count} alert geography/lifecycle scenarios")

    def test_replay_busy_day_with_30_minute_outage(self):
        """A synthetic busy day: 160 warnings, half updated, some cancelled,
        fetched every 5 minutes. A 30-minute outage followed by the app's
        history backfill must end in exactly the same records as no outage."""
        rng = random.Random(42)
        storms = []
        for i in range(160):
            start, dur = rng.randrange(0, 260), rng.randrange(3, 30)
            st = {"id": f"S{i}", "start": start, "end": start + dur, "upd": None, "can": None}
            if rng.random() < 0.5:
                st["upd"] = start + rng.randrange(1, min(4, dur))      # revisions happen while it's live
            if rng.random() < 0.25:
                st["can"] = start + rng.randrange(1, min(6, dur))
            storms.append(st)
        # warnings that exist only inside the outage window (cycles 100-105)
        storms += [{"id": "G1", "start": 101, "end": 104, "upd": None, "can": None},
                   {"id": "G2", "start": 100, "end": 105, "upd": 102, "can": None},
                   {"id": "G3", "start": 101, "end": 105, "upd": None, "can": 103}]

        def messages():
            """Every message with the fetch cycle it was sent in."""
            out = []
            for st in storms:
                out.append((st["start"], feat(st["id"], "Severe Thunderstorm Warning", None, ["MTZ235"])))
                cur = st["id"]
                if st["upd"] is not None and (st["can"] is None or st["upd"] < st["can"]):
                    out.append((st["upd"], feat(cur + "u", "Severe Thunderstorm Warning", None, ["MTZ235"],
                                                mtype="Update", refs=[cur])))
                    cur = cur + "u"
                if st["can"] is not None:
                    out.append((st["can"], feat(st["id"] + "c", "Severe Thunderstorm Warning", None, ["MTZ235"],
                                                mtype="Cancel", refs=[cur])))
            return out

        MSGS = messages()

        def active_at(t):
            """What /alerts/active returns at fetch cycle t."""
            feats = []
            for st in storms:
                if not st["start"] <= t <= st["end"]:
                    continue
                if st["can"] is not None and st["can"] <= t:
                    feats.append(next(m for at, m in MSGS if m["properties"]["id"] == st["id"] + "c"))
                    continue
                cur = st["id"] + "u" if st["upd"] is not None and st["upd"] <= t and (st["can"] is None or st["upd"] < st["can"]) else st["id"]
                feats.append(next(m for at, m in MSGS if m["properties"]["id"] == cur))
            return feats

        def history(since, until):
            return [m for at, m in MSGS if since < at <= until]

        def replay(gap=None, backfill_on=True):
            known, last = {}, None
            for t in range(0, 300):
                if gap and gap[0] <= t < gap[1]:
                    continue                                   # outage: nothing changes
                backfill = history(last - 2, t) if backfill_on and last is not None and t - last > 2 else []
                known = wx.reconcile_alerts(known, active_at(t), NOW, backfill)
                last = t
            return known

        status = lambda k: {a: r["status"] for a, r in k.items() if not r.get("placeholder")}  # noqa: E731
        full = replay()
        gapped = replay(gap=(100, 106))                        # 6 checks x 5 min = 30 minutes
        self.assertEqual(status(gapped), status(full))
        self.assertEqual(len(status(full)), len({m["properties"]["id"] for _, m in MSGS}))   # nothing lost
        self.assertEqual(status(wx.reconcile_alerts(full, active_at(299), NOW)), status(full))  # idempotent
        without = status(replay(gap=(100, 106), backfill_on=False))
        self.assertTrue({"G1", "G2", "G2u", "G3", "G3c"} - set(without))   # proves the backfill is what saves them
        self.assertEqual({k: v for k, v in status(gapped).items() if k.startswith("G")},
                         {"G1": "archived", "G2": "updated", "G2u": "archived", "G3": "cancelled", "G3c": "cancelled"})
        short_lived = [st for st in storms if 100 <= st["start"] and st["end"] < 106]
        print(f"\n  replayed {len(MSGS)} messages; {len(short_lived)} warnings existed only during the outage and were recovered")


if __name__ == "__main__":
    unittest.main()
