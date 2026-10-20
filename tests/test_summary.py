"""Summary (B5 part B1): the five-season table, the roof section and the words, on a synthetic store the test writes.

The store has one spot near Billings (B1 cell row 921, column 2149; tile r0092_c0214) with every part the table reads:
radar estimates, LSR reports, polygon warnings, zone and county products, station gusts, grid records (one season with
31 missing days), station records (a season where the nearest station falls short of 95 percent and the second passes;
a season where neither passes), and the river gauge. Variants remove a part or the partial season. Nothing here is real
data: the real store is checked by the B5 verify and gate steps on the built store (read-only), not by these tests.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the shared forbidden list)
from website import climate, gauges, hail, joins, stations  # noqa: E402
from website import summary as S  # noqa: E402

import words_rules  # noqa: E402

AS_OF = date(2026, 10, 16)
ROW, COL = 921, 2149                       # the B1 cell of Billings (45.7836 N, 108.5007 W)
BILLINGS = {"slug": "billings", "name": "Billings", "lat": 45.7833, "lon": -108.5007}
SHEET_ROWS = [k for k in S.ROW_KEYS if not any(r["key"] == k and r.get("town_only") for r in S.ROWS)]


def day_index(day: date) -> int:
    return (day - hail.D0).days


def hhmm_utc(stamp: str) -> tuple[int, int]:
    d = datetime.strptime(stamp, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    return day_index(d.date()), int(d.strftime("%H%M"))


def yyyymmdd(day: date) -> int:
    return int(day.strftime("%Y%m%d"))


def period(label: str, n: int, extra: dict) -> dict:
    """A station period record (the shape stations.summarize writes), with its elements and pairs."""
    y = int(label[:4])
    start, end = date(y, 7, 1), date(y + 1, 6, 30)
    rec = {"start": yyyymmdd(start), "end": yyyymmdd(end), "n": n, "partial": False}
    rec.update(extra)
    return rec


def write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def store_fixture(root: Path, *, variant: str = "full") -> dict:
    """Write the synthetic store under root (a directory that holds hail/) and return the facts the tests use."""
    first = AS_OF - timedelta(days=hail.WINDOW_DAYS - 1)
    tile = hail.tile_name(ROW // hail.TILE, COL // hail.TILE)
    key = hail.cell_key(ROW, COL)
    ci, cj = climate.climate_cell_for(*hail.cell_centre(ROW, COL))
    ctr, ctc, ckey = climate.climate_tile(ci, cj)
    hdir = root / "hail"

    # --- B1: the radar index, shard and the tile list
    radar = {hail.cell_key(ROW, COL): [(date(2021, 11, 2), 100), (date(2022, 6, 1), 80), (date(2023, 5, 20), 120),
                                       (date(2024, 7, 8), 254), (date(2025, 6, 15), 513), (date(2025, 6, 16), 300)]}
    cells = {str(k): [[day_index(d), t] for d, t in rows] for k, rows in radar.items()}
    write_json(hdir / "t" / f"{tile}.json", {"f": hail.SHARD_FORMAT, "d0": hail.D0.isoformat(),
                                             "r": ROW // hail.TILE, "c": COL // hail.TILE,
                                             "state": [key, 0, 1, 2], "cells": cells})
    index = {"format": hail.FORMAT, "d0": hail.D0.isoformat(), "grid": dict(hail.GRID), "as_of": AS_OF.isoformat(),
             "window": [first.isoformat(), AS_OF.isoformat()], "missing_days": ["2024-03-10"],
             "floor_tenths": hail.FLOOR_TENTHS, "tiles": [tile], "state": "loaded", "source": hail.SOURCE_NAME}

    # --- the grid (B5 c/): five seasons, the partial season, one season with 31 missing days
    def rec(days, missing, rain, rmax, rdate, tmax, tdate, tmin, mdate, hot, cold, frz, below):
        return [days, missing, rain, rmax, rdate, tmax, tdate, tmin, mdate, hot, cold, frz, below]
    seasons = [
        rec(365, 0, 1540, 210, yyyymmdd(date(2022, 6, 6)), 1003, yyyymmdd(date(2022, 7, 15)), -150,
            yyyymmdd(date(2022, 1, 2)), 22, 3, 60, 120),
        rec(365, 0, 1310, 165, yyyymmdd(date(2023, 1, 9)), 985, yyyymmdd(date(2023, 7, 16)), -230,
            yyyymmdd(date(2022, 12, 22)), 18, 2, 58, 118),
        rec(365, 31, 1210, 150, yyyymmdd(date(2023, 10, 10)), 1062, yyyymmdd(date(2024, 7, 25)), -332,
            yyyymmdd(date(2024, 1, 13)), 15, 1, 50, 110),
        rec(366, 0, 1490, 230, yyyymmdd(date(2025, 9, 18)), 1011, yyyymmdd(date(2025, 6, 15)), -145,
            yyyymmdd(date(2024, 12, 31)), 20, 2, 66, 122),
        rec(365, 0, 1280, 190, yyyymmdd(date(2026, 5, 2)), 1032, yyyymmdd(date(2026, 7, 13)), -96,
            yyyymmdd(date(2026, 1, 20)), 24, 3, 62, 115),
        rec(107, 0, 330, 80, yyyymmdd(date(2026, 8, 14)), 1126, yyyymmdd(date(2026, 7, 13)), 320,
            yyyymmdd(date(2026, 7, 2)), 9, 0, 14, 0),
    ]
    if variant == "no_partial":
        seasons[5] = rec(0, 0, None, None, None, None, None, None, None, None, None, None, None)
    if variant == "no_land":
        seasons = None
    five = rec(sum(r[0] for r in seasons[:5]) if seasons else 0, 31, 6770, 230, yyyymmdd(date(2025, 9, 18)),
               1062, yyyymmdd(date(2024, 7, 25)), -332, yyyymmdd(date(2024, 1, 13)), 90, 9, 302, 563) if seasons else None
    if seasons:
        cells_c = {str(ckey): {"i": ci, "j": cj, "f": five, "s": seasons, "c": seasons, "w": seasons}}
        state = [ckey]
    else:
        cells_c, state = {}, [ckey]
    climate_tile = {"f": climate.FORMAT, "r": ctr, "c": ctc, "state": state, "cells": cells_c}
    write_json(hdir / "c" / f"{hail.tile_name(ctr, ctc)}.json", climate_tile)
    index["climate"] = {"format": climate.FORMAT, "state": "loaded" if variant != "climate_unavailable" else "unavailable",
                        "problem": None if variant != "climate_unavailable" else "the climate tile could not be read",
                        "through": "2026-10-15", "tile_names": [hail.tile_name(ctr, ctc)], "months_missing": ["2023-11"],
                        "month_problems": {"2023-11": "no_file"}, "partial_line": None}

    # --- the joins (B2 and B5): reports, warnings, detections, zone and county maps, stations
    rep = []
    def add_report(stamp, lat, lon, code, mag, unit, qual, src, kind):
        d, t = hhmm_utc(stamp)
        rep.append([d, t, lat, lon, code, mag, unit, qual, src, "BILLINGS", "", kind])
    add_report("2025-06-15T22:48Z", 45.80, -108.50, "H", "1.75", "in", "E", "Trained Spotter", "hail")
    add_report("2024-07-08T20:10Z", 45.78, -108.60, "H", "None", "", "", "Public", "hail")
    add_report("2023-05-20T19:00Z", 45.84, -108.45, "H", "1.00", "in", "E", "Public", "hail")
    add_report("2025-02-20T00:30Z", 45.75, -108.52, "G", "60", "mph", "M", "ASOS", "tstm wnd gst")
    if variant != "no_damage":
        add_report("2024-08-02T21:00Z", 45.78, -108.45, "D", "None", "", "", "Public", "tstm wnd dmg")
    add_report("2023-02-01T15:00Z", 45.79, -108.50, "5", "0.10", "in", "E", "Public", "freezing rain")
    add_report("2022-06-10T18:00Z", 45.76, -108.53, "E", "None", "", "", "Public", "flood")
    add_report("2022-06-14T03:00Z", 45.81, -108.49, "F", "None", "", "", "Public", "flash flood")
    add_report("2024-05-20T14:00Z", 45.77, -108.55, "R", "1.20", "in", "E", "Public", "rain")
    add_report("2023-12-05T10:00Z", 45.79, -108.50, "N", "58", "mph", "", "Mesonet", "non-tstm wnd gst")
    add_report("2022-01-10T12:00Z", 45.79, -108.50, "G", "55", "mph", "", "AWOS", "tstm wnd gst")         # an AWOS station
    add_report("2026-09-20T12:00Z", 45.75, -108.52, "G", "50", "mph", "", "ASOS", "tstm wnd gst")         # the partial season
    add_report("2024-07-19T23:00Z", 45.79, -108.50, "I", "105", "F", "E", "Public", "extreme heat")
    rep_refs = list(range(len(rep)))
    warn = []
    def add_warning(k, s, begin, end, covered):
        warn.append({"k": k, "s": s, "b": begin, "e": end, "o": "BYZ", "tags": {}})
        return len(warn) - 1
    w_ff = add_warning("FF", "W", "2022-06-14T03:00Z", "2022-06-14T12:00Z", True)
    w_fl = add_warning("FL", "W", "2022-06-13T10:00Z", "2022-06-13T20:00Z", True)
    w_sv = add_warning("SV", "W", "2024-06-01T21:00Z", "2024-06-01T22:00Z", True)
    w_far = add_warning("FL", "W", "2023-03-03T10:00Z", "2023-03-03T20:00Z", False)
    w_fa = add_warning("FA", "W", "2022-06-12T05:00Z", "2022-06-12T19:15Z", True)      # an areal flood warning (B5 D3)
    w_fay = add_warning("FA", "Y", "2025-01-10T12:00Z", "2025-01-10T18:00Z", True)     # an advisory, not a warning
    cover_in = joins.cover_hex([key])
    cover_out = joins.cover_hex([99])
    tile_warnings = [[w_ff, cover_in], [w_fl, cover_in], [w_sv, cover_in], [w_far, cover_out], [w_fa, cover_in],
                     [w_fay, cover_in]]
    det = [[day_index(date(2025, 6, 15)), 2100, 45.79, -108.50, 175], [day_index(date(2024, 7, 8)), 1900, 45.90, -108.20, 120],
           [day_index(date(2025, 6, 15)), 2000, 45.80, -108.49, 130]]          # a second row on the same SPC day
    stations_near = [{"id": "BIL", "name": "Billings Logan", "lat": 45.8077, "lon": -108.5429, "miles": 4.1}]
    # D48: the NCEI records of the cell: one flood record about 2.2 miles from the spot (the flood_record variant only)
    recs = [[day_index(date(2022, 6, 10)), 1800, 45.76, -108.53, "flood", "", "", "", "Public", "Billings", "", None, None,
             "Heavy Rain / Snow Melt"]] if variant == "flood_record" else []
    joins_tile = {"f": joins.FORMAT, "r": ROW // hail.TILE, "c": COL // hail.TILE, "d0": hail.D0.isoformat(),
                  "reports": rep_refs, "records": list(range(len(recs))), "detections": det, "warnings": tile_warnings,
                  "zones": {"MTZ313": [key, 20, 21]}, "fire": {}, "counties": {"MTC111": [key]},
                  "stations": stations_near}
    write_json(hdir / "j" / f"{tile}.json", joins_tile)
    write_json(hdir / "j" / joins.EVENTS_NAME, {"f": joins.EVENTS_FORMAT, "d0": hail.D0.isoformat(), "reports": rep,
                                                "records": recs, "warnings": warn})
    zone_events = [
        {"k": "HW", "s": "W", "b": "2024-01-18T12:00Z", "e": "2024-01-18T23:00Z", "o": "BYZ"},
        {"k": "HW", "s": "A", "b": "2025-03-02T18:00Z", "e": "2025-03-03T06:00Z", "o": "BYZ"},
        {"k": "WS", "s": "W", "b": "2024-02-06T12:00Z", "e": "2024-02-07T12:00Z", "o": "BYZ"},
        {"k": "IS", "s": "W", "b": "2023-12-10T12:00Z", "e": "2023-12-11T00:00Z", "o": "BYZ"},
        {"k": "HT", "s": "Y", "b": "2024-07-18T12:00Z", "e": "2024-07-19T00:00Z", "o": "BYZ"},
    ]
    if variant != "zones_unavailable":
        write_json(hdir / "z" / "MTZ313.json", {"f": joins.ZONE_FORMAT, "zone": "MTZ313", "name": "Billings area",
                                                 "events": zone_events, "records": []})
    write_json(hdir / "k" / "MTC111.json", {"f": joins.COUNTY_FORMAT, "county": "MTC111", "name": "Yellowstone County",
                                            "events": [{"k": "FA", "s": "A", "b": "2025-05-12T12:00Z",
                                                        "e": "2025-05-12T23:00Z", "o": "BYZ", "n": 1},
                                                       {"k": "FF", "s": "A", "b": "2024-06-30T12:00Z",
                                                        "e": "2024-07-01T00:00Z", "o": "BYZ", "n": 1}]})
    gust_days = []
    for day, mph, kt, flag in ((date(2025, 6, 15), 69, 60, 0), (date(2025, 2, 20), 121, 105, 1),
                               (date(2022, 7, 1), 58, 50, 0), (date(2023, 1, 5), 40, 35, 0)):
        if kt >= 50:
            gust_days.append([day_index(day), mph, kt, flag])
    # the station's own day counts (B5 D11 gust rule): days with a gust value and the season's day count, per season.
    # 2021-22 has 257 of 365 days (70 percent: below the 95 percent share); the other seasons are complete.
    if variant == "gust_empty":
        gust_days = []
    gust_periods = {}
    for label, n, ok in (("2021-22", 365, 257), ("2022-23", 365, 365), ("2023-24", 366, 366), ("2024-25", 365, 365),
                         ("2025-26", 365, 365)):
        if variant == "gust_40" and label == "2022-23":
            ok = 146                                       # 40 percent
        if variant == "gust_empty":
            ok = 0
        gust_periods[label] = {"n": n, "ok": ok}
    gust_doc = {"f": joins.STATION_FORMAT, "id": "BIL", "name": "Billings Logan", "lat": 45.8077, "lon": -108.5429,
                "days": gust_days, "dropped": 2}
    if variant != "gust_interim":
        gust_doc["periods"] = {"season": gust_periods}
    write_json(hdir / "s" / "BIL.json", gust_doc)
    unplaced_rows = []
    if variant == "zones_unplaced":                         # Montana's products the joins could not place (index rows)
        unplaced_rows = [
            ["HW.W", "MTZ008", "2021-12-11", "z_08se21.zip", "edition_unpublished"],
            ["HW.W", "MTZ008", "2022-01-02", "z_08se21.zip", "edition_unpublished"],
            ["HW.A", "MTZ009", "2022-07-18", "z_07se22.zip", "edition_unpublished"],
            ["HW.A", "MTZ009", "2024-10-01", "z_05mr24.zip", "edition_unpublished"],
            ["WS.W", "MTZ009", "2021-12-20", "z_08se21.zip", "edition_unpublished"],
            ["HT.Y", "MTZ008", "2022-08-04", "z_07se22.zip", "edition_unpublished"],
            ["FA.A", "MTZ009", "2022-03-01", "z_22mr22.zip", "edition_unpublished"],
            ["FF.A", "MTZ009", "2021-12-11", "z_08se21.zip", "edition_unpublished"],
        ]
    index["joins"] = {"format": joins.FORMAT, "events_format": joins.EVENTS_FORMAT, "state": "loaded",
                      "zone_products_unplaced": 1230 if variant == "zones_unplaced" else 0,
                      "zone_unplaced_rows": unplaced_rows,
                      "as_of": AS_OF.isoformat(), "window": index["window"],
                      "parts": {p: "loaded" for p in joins.PARTS}, "reasons": {}, "partial": {},
                      "counties": {"state": "loaded", "names": {"MTC111": "Yellowstone County"}, "count": 1},
                      "zone_names": {"MTZ313": "Billings area"}}
    if variant == "reports_unavailable":
        index["joins"]["parts"]["reports"] = "unavailable"
        index["joins"]["reasons"]["reports"] = "the source did not answer"
    if variant == "stations_unavailable_joins":
        index["joins"]["parts"]["stations"] = "unavailable"
        index["joins"]["reasons"]["stations"] = "the source did not answer"
    if variant == "warnings_unavailable":
        index["joins"]["parts"]["warnings"] = "unavailable"
        index["joins"]["reasons"]["warnings"] = "the source did not answer"

    # --- the station records (B5 sd/): a nearest station short in 2023-24 and a second that passes; both current
    light = {
        "USC00240802": {"name": "Billings WTP", "lat": 45.78, "lon": -108.52, "elev": 1000.0, "net": "SNOTEL",
                        "current": {e: True for e in stations.CORE}, "newest": {e: 20261015 for e in stations.CORE},
                        "cover": {e: 1900 for e in stations.CORE}},
        "USW00024033": {"name": "Billings Logan", "lat": 45.8077, "lon": -108.5429, "elev": 1090.0, "net": "W",
                        "current": {e: True for e in stations.CORE}, "newest": {e: 20261015 for e in stations.CORE},
                        "cover": {e: 2100 for e in stations.CORE}},
        "US1MTYL0001": {"name": "Far Away 1 SE", "lat": 46.60, "lon": -108.50, "elev": 1100.0, "net": "CoCoRaHS",
                        "current": {e: True for e in stations.CORE}, "newest": {e: 20261015 for e in stations.CORE},
                        "cover": {e: 2000 for e in stations.CORE}},
    }
    if variant == "one_station":
        light.pop("USW00024033")                            # a town with one station in the rule's list
    if variant == "snow_none":
        for sid in ("USC00240802", "USW00024033"):
            light[sid]["cover"]["SNOW"] = 100
    seasons_sd = [("2021-22", 365), ("2022-23", 365), ("2023-24", 365), ("2024-25", 366), ("2025-26", 365),
                  ("2026-27", 107)]
    for sid, meta in light.items():
        per = {}
        for label, n in seasons_sd:
            ok_snow = n if sid != "USW00024033" else n
            if sid == "USC00240802" and label == "2023-24":
                ok_snow = 300                          # 82 percent: short of 95 percent
            if sid == "USW00024033" and label == "2023-24":
                ok_snow = 350                          # 96 percent: passes
            if variant == "snow_none" and label == "2023-24":
                ok_snow = 200
            if variant == "one_station":
                ok_snow = n
            base = {"SNOW": {"rep": n, "ok": ok_snow, "sum": 1200 + (5 if sid == "USW00024033" else 0), "trace": 2},
                    "SNWD": {"rep": n, "ok": n, "max": 300, "max_d": yyyymmdd(date(2025, 2, 18) if label == "2024-25" else date(2024, 2, 16)),
                             "max_n": 1, "ge1": 80},
                    "TMAX": {"rep": n, "ok": n, "max": 310, "max_d": yyyymmdd(date(2025, 7, 15)), "max_n": 1, "ge90": 12},
                    "TMIN": {"rep": n, "ok": n, "min": -200, "min_d": yyyymmdd(date(2024, 12, 30)), "min_n": 1, "lt32": 120},
                    "DL": {"ev": n, "n": 40}}
            per[label] = period(label, n, base)
        write_json(hdir / "sd" / f"{sid}.json", {"f": stations.FORMAT, "id": sid, "name": meta["name"], "lat": meta["lat"],
                                                 "lon": meta["lon"], "elev": meta["elev"], "net": meta["net"],
                                                 "as_of": AS_OF.isoformat(), "current": meta["current"],
                                                 "newest": meta["newest"], "cover": meta["cover"],
                                                 "periods": {"season": per, "calendar": {}, "water": {}}})
    index["stations"] = {"state": "loaded", "as_of": AS_OF.isoformat(), "stations": light, "towns": {}, "gates": {},
                         "rule": {}}
    if variant == "stations_unavailable":
        index["stations"] = {"state": "unavailable", "problem": "the station list did not load"}

    # --- the gauge (town page only)
    write_json(hdir / "g" / "06214500.json", {"f": gauges.FORMAT, "usgs": "06214500", "lids": ["BLLM8"],
                                              "name": "Yellowstone River at Billings", "state": "MT", "lat": 45.78,
                                              "lon": -108.50, "unit": "hundredths of a foot",
                                              "stages": {"action": 1100, "minor": 1200, "moderate": 1400, "major": 1600},
                                              "peaks": [[2022, "2022-06-15", 1637, ""], [2019, "2019-05-30", 1100, ""]],
                                              "rows": 2, "water_years": [2019, 2022], "source": "USGS"})
    town_gauge = {"lid": "BLLM8", "usgs": "06214500", "name": "Yellowstone River at Billings", "state": "MT",
                  "lat": 45.78, "lon": -108.50, "miles": 1.8, "minor_ft": 12.0, "peaks": "loaded"}
    if variant == "gauge_none":
        town_gauge = {"none": True}
    if variant == "gauge_unavailable":
        town_gauge = {"unavailable": True, "lid": "BLLM8", "name": "Yellowstone River at Billings", "miles": 1.8}
    index["gauges"] = {"state": "loaded", "towns": {"billings": town_gauge}}
    if variant == "gauge_block_absent":
        index.pop("gauges")
    elif variant == "gauge_unavailable_block":
        index["gauges"] = {"state": "unavailable", "problem": "the gauge list did not load"}
    elif variant == "gauge_town_missing":
        index["gauges"] = {"state": "loaded", "towns": {}}
    elif variant == "gauge_file_missing":
        index["gauges"] = {"state": "loaded", "towns": {"billings": dict(town_gauge, usgs="00000000")}}
    if variant == "as_of_old":
        index["as_of"] = (AS_OF - timedelta(days=10)).isoformat()
    write_json(hdir / "index.json", index)
    return {"tile": tile, "index": index, "first": first, "key": key}


def build_store(variant: str = "full") -> tuple[Path, dict]:
    root = Path(tempfile.mkdtemp(prefix="summary-test-"))
    return root, store_fixture(root, variant=variant)


def strings_of(obj):
    """Every string in a nested dict or list of words (the values, not the keys)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings_of(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings_of(v)


def filled(template: str) -> str:
    """A template with every brace filled by a plain value, so the words can be scanned as sentences."""
    return re.sub(r"\{(\w+)\}", "3", template)


def all_text(obj):
    """Every sentence in a result. A URL is an address, not a sentence, so its key is skipped."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k != "url":
                yield from all_text(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from all_text(v)


class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.fixture = build_store("full")
        cls.result = S.describe_summary(cls.root, ROW, COL, datetime(2026, 10, 16, tzinfo=timezone.utc))
        cls.rows = {r["key"]: r for r in cls.result["table"]["rows"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_rows_in_brief_order_and_kinds(self):
        keys = [r["key"] for r in self.result["table"]["rows"]]
        self.assertEqual(keys, SHEET_ROWS)
        self.assertEqual(len(keys), 24)                # the 23 rows of the brief and the NCEI flood records row (D48)
        kinds = {k["word"] for k in S.KIND_WORDS}
        for row in self.result["table"]["rows"]:
            self.assertIn(row["kind"], kinds, row["key"])
            self.assertIn(row["unit"], S.UNIT_SPEC, row["key"])
            self.assertEqual(len(row["values"]), 5, row["key"])
            self.assertEqual(len(row["texts"]), 5, row["key"])

    def test_every_value_is_an_integer_or_null(self):
        for row in self.result["table"]["rows"]:
            for v in row["values"] + [row["five"]]:
                self.assertTrue(v is None or (isinstance(v, int) and not isinstance(v, bool)), (row["key"], v))

    def test_no_zero_stands_for_missing(self):
        # the 2023-24 station snowfall: the nearest station has 82 percent, the second 96 percent: the second shows
        snow = self.rows["snow"]
        self.assertIsNotNone(snow["values"][2])
        self.assertIn("Billings Logan", snow["texts"][2])
        # a season with too few days with a gust value shows Data unavailable, never a zero: 257 of 365 days in 2021-22
        self.assertIsNone(self.rows["gust_max"]["values"][0])
        self.assertIn("Data unavailable: Billings Logan has 257 of 365 days with a gust value",
                      self.rows["gust_max"]["texts"][0])
        self.assertNotIn("No day at 50 kt", self.rows["gust_max"]["texts"][0])
        self.assertIsNone(self.rows["gust_days"]["values"][0])
        # the coverage line counts every missing day of a season, with or without a value (brief lines 98-99)
        self.assertEqual(self.rows["gust_max"]["coverage"][0], "108 days missing")
        self.assertEqual(self.rows["gust_days"]["coverage"][0], "108 days missing")
        self.assertEqual(self.rows["hail_max"]["coverage"][0], "108 days missing")
        for key in ("hail_max", "gust_max"):
            self.assertTrue(self.rows[key]["coverage"][0].endswith("days missing"), key)
        # the five-season figure needs every season: one short season makes it Data unavailable, with its reason
        self.assertIsNone(self.rows["gust_days"]["five"])
        self.assertIn("2021-22 has no usable value", " ".join(self.rows["gust_days"]["notes"]))
        # the five-season total of snowfall needs one station for all five seasons (D41, B5-16): the fixture has two, so
        # there is no total, and the cell says why
        self.assertIsNone(snow["five"])
        self.assertIn("the seasons come from more than one station", snow["five_text"])
        self.assertTrue(snow["five_text"].endswith("This is not an all-clear."), snow["five_text"])

    def test_radar_largest_and_one_inch_days(self):
        radar = self.rows["radar_max"]
        self.assertEqual(radar["values"][3], 201)                         # 2024-25: 2.01 in (513 tenths)
        self.assertEqual(radar["texts"][3], "2.01 in on Jun 15, 2025")
        self.assertEqual(radar["dates"][3], 20250615)
        one = self.rows["radar_1in"]
        self.assertEqual(one["values"][3], 3)                             # 2024-25: 2024-07-08 (1.00 in), 2025-06-15, 2025-06-16
        self.assertEqual(one["values"][2], 0)                             # 2023-24: a real zero, the season is complete
        self.assertEqual(one["five"], 3)
        self.assertEqual(one["texts"][3], "3 days")

    def test_radar_partial_first_season_is_labelled(self):
        cov = self.rows["radar_max"]["coverage"][0]
        self.assertIsNotNone(cov)
        self.assertTrue(cov.endswith("days missing"), cov)
        self.assertIn("Oct 17, 2021", " ".join(self.rows["radar_max"]["notes"]))

    def test_missing_months_show_a_coverage_line(self):
        tmax = self.rows["tmax"]
        self.assertEqual(tmax["values"][2], 1062)                         # the season's highest, over the days present
        self.assertEqual(tmax["coverage"][2], "31 days missing")
        self.assertIn("106.2 F on Jul 25, 2024", tmax["texts"][2])
        self.assertEqual(self.rows["tmin"]["values"][2], -332)
        self.assertEqual(self.rows["tmin"]["coverage"][2], "31 days missing")

    def test_grid_rows_use_the_grid_kind_word(self):
        for key in ("tmax", "tmin", "hot90", "frost32", "freeze_thaw", "precip", "precip_max"):
            self.assertEqual(self.rows[key]["kind"], "Grid estimate", key)
        self.assertEqual(self.rows["hot90"]["values"][1], 18)
        self.assertEqual(self.rows["precip"]["values"][0], 1540)           # hundredths of an inch: 15.40 in

    def test_station_rows_name_the_station_and_are_station_readings(self):
        for key in ("snow", "snow_depth", "gust_days", "gust_max"):
            self.assertEqual(self.rows[key]["kind"], "Station reading", key)
        self.assertIn("Billings WTP", "".join(self.rows["snow"]["notes"]) + self.rows["snow"]["texts"][0])
        self.assertEqual(self.rows["snow"]["texts"][2].split(" at ")[-1], "Billings Logan")

    def test_gust_flagged_reading_is_said(self):
        gmax = self.rows["gust_max"]
        self.assertEqual(gmax["values"][3], 105)
        self.assertEqual(gmax["texts"][3], "105 kt (121 mph) on Feb 20, 2025, flagged for check")
        self.assertEqual(self.rows["gust_days"]["values"][3], 2)
        self.assertEqual(self.rows["gust_days"]["values"][1], 1)          # 2022-07-01 at 50 kt, in 2022-23
        self.assertEqual(self.rows["gust_days"]["texts"][3], "2 days at Billings Logan")

    def test_report_rows_are_reports_with_counts_and_sizes(self):
        hail_max = self.rows["hail_max"]
        self.assertEqual(hail_max["values"][3], 175)                      # 1.75 in in 2024-25
        self.assertEqual(hail_max["texts"][3], "1.75 in on Jun 15, 2025")
        self.assertEqual(self.rows["hail_n"]["values"][3], 2)             # the 2024-25 hail reports (one with no size)
        self.assertEqual(self.rows["wind_n"]["values"][3], 2)             # G and D
        self.assertEqual(self.rows["freezing_rain_n"]["values"][1], 1)
        self.assertEqual(self.rows["flood_report_n"]["values"][0], 2)     # 2022-06-10 flood and 2022-06-14 flash flood
        self.assertEqual(self.rows["hail_n"]["kind"], "Report")

    def test_warning_and_zone_rows(self):
        self.assertEqual(self.rows["flood_warn"]["kind"], S.KIND_WARNING)
        self.assertEqual(self.rows["flood_warn"]["values"][0], 3)        # FF.W, FL.W and FA.W in 2021-22 (the far one is not covered)
        self.assertEqual(self.rows["flood_warn"]["values"][3], 0)        # FA.Y 2025-01-10 is an advisory, not a warning
        self.assertEqual(self.rows["hw_zone"]["kind"], "Zone product")
        self.assertEqual(self.rows["hw_zone"]["values"][2], 1)           # HW.W 2024-01 in 2023-24; HW.A 2025-03 in 2024-25
        self.assertEqual(self.rows["hw_zone"]["values"][3], 1)
        self.assertEqual(self.rows["ice_warn"]["values"][2], 2)          # IS.W 2023-12 and WS.W 2024-02, both 2023-24
        self.assertEqual(self.rows["county_watch"]["kind"], "County product")
        self.assertEqual(self.rows["county_watch"]["values"][2], 1)      # FF.A 2024-06-30 is 2023-24
        self.assertEqual(self.rows["county_watch"]["values"][3], 1)      # FA.A 2025-05-12 is 2024-25

    def test_held_row_has_the_four_reasons(self):
        held = self.rows["held"]
        self.assertEqual(held["kind"], "Data unavailable")
        self.assertTrue(all(v is None for v in held["values"]))
        text = " ".join(held["notes"])
        for word in ("Lightning", "UV and sunlight", "Roof surface temperature", "ponding"):
            self.assertIn(word, text)

    def test_partial_season_line_below_the_table(self):
        partial = self.result["table"]["partial"]
        self.assertEqual(partial["label"], "2026-27")
        self.assertIn("2026-27 so far, 107 days to Oct 15, 2026", partial["text"])
        self.assertIn("preliminary", partial["text"])
        self.assertNotIn("2026-27", self.result["table"]["columns"])

    def test_radar_sentence_and_plain_sentence(self):
        self.assertEqual(self.result["radar_sentence"], S.WORDS_SUMMARY["radar_sentence"])
        self.assertIn("Radar estimates can miss hail that people reported", self.result["radar_sentence"])
        self.assertTrue(self.result["plain"].startswith("Five seasons of weather for this spot"))

    def test_roof_section_has_23_lines_and_7_held(self):
        roof = self.result["roof"]
        lines = [line for g in roof["groups"] for line in g["lines"]]
        self.assertEqual(len(lines), 23)
        self.assertEqual([g["name"] for g in roof["groups"]],
                         ["Thresholds", "Snow and ice", "Wind and hail", "Heat and rain", "Lightning and sun"])
        held = [h for g in roof["groups"] for h in g["held"]]
        self.assertEqual(len(held), 7)
        refs = [r for g in roof["groups"] for r in g["references"]]
        self.assertEqual(len(refs), 15)
        for r in refs:
            self.assertEqual(r["kind"], "Reference")
            self.assertTrue(r["url"].startswith("https://"))
        for line in lines:
            self.assertIn(line["kind"], {k["word"] for k in S.KIND_WORDS}, line["id"])
            self.assertTrue(line["text"], line["id"])
            self.assertTrue(line["value"] is None or isinstance(line["value"], int))

    def test_roof_lines_name_their_kind_and_say_unavailable_when_missing(self):
        lines = {line["id"]: line for g in self.result["roof"]["groups"] for line in g["lines"]}
        self.assertIn("Radar estimate:", lines["hail_size_days"]["text"])
        self.assertEqual(lines["hail_size_days"]["value"], 3)
        self.assertIn("Report:", lines["hail_reports"]["text"])
        self.assertIn("Station reading:", lines["snow_depth"]["text"])
        self.assertIsInstance(lines["ice_dam_weather_days"]["value"], int)

    def test_forbidden_terms_are_absent_from_every_sentence(self):
        for text in all_text(self.result):
            hits = S.forbidden_hits(text)
            self.assertEqual(hits, [], f"{hits} in {text[:140]!r}")

    def test_every_template_passes_the_forbidden_list(self):
        for name, template in list(S.WORDS_SUMMARY.items()) + list(S.WORDS_INDICATORS["lines"].items()):
            if not isinstance(template, str):
                continue
            words_rules.assert_clean(self, filled(template), name)
        for text in list(strings_of(S.WORDS_SUMMARY)) + list(strings_of(S.WORDS_INDICATORS)):
            words_rules.assert_clean(self, filled(text), text[:60])

    def test_how_made_and_about_carry_the_sources(self):
        how = " ".join(self.result["how_made"])
        for phrase in ("NOAA nClimGrid-Daily", "Iowa Environmental Mesonet", "NCEI-PD-10-2-02", "TIGER/Line",
                       "Observations courtesy of U.S. Geological Survey", "National Snow Analysis", "95 percent"):
            self.assertIn(phrase, how)
        about = " ".join(self.result["about"])
        self.assertIn("checked against station season totals and left out", about)

    def test_sections_in_the_brief_order_each_with_a_lead(self):
        ids = [s["id"] for s in self.result["sections"]]
        self.assertEqual(ids, ["hail", "wind", "storms", "temperature", "rain", "snow", "flooding", "ice", "heat",
                               "roof", "made"])
        for s in self.result["sections"]:
            self.assertTrue(s["lead"], s["id"])
            self.assertTrue(s["heading"], s["id"])

    def test_town_rows_are_absent_on_the_sheet(self):
        self.assertNotIn("tmax_station", self.rows)
        self.assertIsNone(self.result["town"])

    def test_map_data_has_templates_order_kind_words_and_units(self):
        data = S.map_data_summary(self.fixture["index"])
        self.assertEqual(data["row_order"], list(S.ROW_KEYS))
        self.assertEqual(len(data["rows"]), len(S.ROWS))
        self.assertEqual(data["units"]["in"]["scale"], 100)
        self.assertIn("lead_hail", data["words"])
        self.assertIn("Grid estimate", [k["word"] for k in data["kind_words"]])
        self.assertEqual(S.map_data_summary(None)["state"], "unavailable")


class SummaryVariantTests(unittest.TestCase):
    def test_town_page_adds_the_station_rows_and_the_gauge_line(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
            keys = [r["key"] for r in result["table"]["rows"]]
            self.assertIn("tmax_station", keys)
            self.assertIn("tmin_station", keys)
            self.assertEqual(len(keys), 26)                # the sheet's 24 rows and the two town station rows (D48 adds one)
            gauge = " ".join(result["town"]["gauge"])
            self.assertIn("River flood record at the Yellowstone River at Billings gauge, 1.8 miles away; it does not say "
                          "water reached this address.", gauge)
            self.assertIn("water year 2022, peak 16.37 ft on Jun 15, 2022", gauge)
            self.assertEqual(result["town"]["stations"]["tmax"][0]["name"], "Billings WTP")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_unavailable_stations_mark_their_rows_and_keep_the_rest(self):
        root, _ = build_store("stations_unavailable")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            rows = {r["key"]: r for r in result["table"]["rows"]}
            self.assertTrue(all(v is None for v in rows["snow"]["values"]))
            self.assertIn("Station readings could not be loaded in this update", " ".join(rows["snow"]["notes"]))
            self.assertIsNotNone(rows["tmax"]["values"][0])
            self.assertEqual(result["state"], "partial")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_unavailable_reports_say_so_with_the_d16_sentence(self):
        root, _ = build_store("reports_unavailable")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            rows = {r["key"]: r for r in result["table"]["rows"]}
            self.assertTrue(all(v is None for v in rows["hail_n"]["values"]))
            self.assertIn("Reports could not be loaded in this update", " ".join(rows["hail_n"]["notes"]))
            self.assertIsNotNone(rows["radar_max"]["values"][3])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_partial_season_with_no_day_says_the_no_day_sentence(self):
        root, fixture = build_store("no_partial")
        try:
            index = dict(fixture["index"])
            index["as_of"] = "2026-06-20"
            index["window"] = [(date(2026, 6, 20) - timedelta(days=1825)).isoformat(), "2026-06-20"]
            spot = S._Spot(root, index, ROW, COL, None)
            text = S._partial(spot, None, None, [], [])
            self.assertEqual(text, "No day of the 2026-27 season is in the data yet. This is not an all-clear.")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_cell_outside_the_store_is_outside(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, 100, 100, None)
            self.assertEqual(result["state"], "outside")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_stale_line_when_the_radar_is_old(self):
        root, _ = build_store("as_of_old")
        try:
            result = S.describe_summary(root, ROW, COL, datetime(2026, 10, 19, tzinfo=timezone.utc))
            self.assertIsNotNone(result["stale"])
            self.assertIn("This is not an all-clear.", result["stale"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_snow_none_when_no_station_passes(self):
        root, _ = build_store("snow_none")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            snow = {r["key"]: r for r in result["table"]["rows"]}["snow"]
            self.assertIsNone(snow["values"][2])
            self.assertIsNone(snow["five"])
            # no station passes on a loaded block: the no-station sentence, with every day of the season missing (D33)
            self.assertIn("No station within 40 miles has enough reports for snowfall from 2020 to 2025.", snow["texts"][2])
            self.assertIn("days missing", snow["coverage"][2])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class FailureVariantTests(unittest.TestCase):
    """Each part that can fail marks its own rows (D16) and the rest of the table still builds."""

    def _rows(self, variant, town=None):
        root, _ = build_store(variant)
        try:
            result = S.describe_summary(root, ROW, COL, None, town=town)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        return result, {r["key"]: r for r in result["table"]["rows"]}

    def test_climate_unavailable_marks_the_grid_rows(self):
        result, rows = self._rows("climate_unavailable")
        self.assertIn("Temperature could not be loaded in this update; that is not the same as no temperature.",
                      " ".join(rows["tmax"]["notes"]))
        self.assertTrue(all(v is None for v in rows["precip"]["values"]))
        self.assertIsNotNone(rows["hail_n"]["values"][3])            # reports still build
        self.assertEqual(result["state"], "partial")
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIsNone(lines["temperature_extremes"]["value"])
        # the roof line carries the part's own D20 sentence, which says the reason (D16, D20), not the bare word
        self.assertIn("Temperature could not be loaded in this update; that is not the same as no temperature.",
                      lines["temperature_extremes"]["text"])
        self.assertTrue(lines["temperature_extremes"]["text"].endswith("This is not an all-clear."))

    def test_no_land_cell_says_no_land_value_not_zero(self):
        result, rows = self._rows("no_land")
        self.assertTrue(all(v is None for v in rows["tmin"]["values"]))
        self.assertIn("No land value for this grid cell", " ".join(rows["tmin"]["notes"]))

    def test_missing_zone_file_marks_the_zone_rows(self):
        result, rows = self._rows("zones_unavailable")
        self.assertTrue(all(v is None for v in rows["hw_zone"]["values"]))
        self.assertIn("could not be loaded in this update", " ".join(rows["hw_zone"]["notes"]))
        self.assertIsNone(rows["ice_warn"]["five"])
        self.assertIsNotNone(rows["gust_days"]["values"][3])        # gusts still build
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIsNone(lines["wind_zone_warnings"]["value"])

    def test_unavailable_gust_stations_say_so(self):
        result, rows = self._rows("stations_unavailable_joins")
        self.assertTrue(all(v is None for v in rows["gust_days"]["values"]))
        self.assertIn("could not be loaded in this update", " ".join(rows["gust_max"]["notes"]))
        self.assertIsNotNone(rows["snow"]["values"][0])            # the station rows do not depend on the joins

    def test_unplaced_zone_products_mark_their_family_and_season(self):
        result, rows = self._rows("zones_unplaced")
        # high wind: products unplaced in 2021-22 and 2022-23 (and 2024-25): a zero there is unknown, a count keeps its value
        self.assertEqual(rows["hw_zone"]["values"], [None, None, 1, 1, 0])
        self.assertEqual(rows["hw_zone"]["texts"][0],
                         "Data unavailable: some products could not be placed to a zone. This is not an all-clear.")
        self.assertIn("Montana: 2 high wind products issued Dec 11, 2021 to Jan 2, 2022 could not be placed to a zone",
                      rows["hw_zone"]["coverage"][0])
        self.assertTrue(rows["hw_zone"]["coverage"][0].endswith("could not be placed to a zone. This is not an all-clear."),
                        rows["hw_zone"]["coverage"][0])
        self.assertIn("Montana: 1 high wind product issued Jul 18, 2022 could not be placed to a zone",
                      rows["hw_zone"]["coverage"][1])
        self.assertNotIn("Partial", rows["hw_zone"]["coverage"][1])          # no reconfiguration partial (D44)
        self.assertTrue(rows["hw_zone"]["coverage"][1].endswith("This is not an all-clear."), rows["hw_zone"]["coverage"][1])
        self.assertIn("Montana: 1 high wind product issued Oct 1, 2024 could not be placed to a zone.",
                      rows["hw_zone"]["coverage"][3])
        self.assertIsNone(rows["hw_zone"]["coverage"][2])             # 2023-24 has no unplaced product: no statement
        self.assertEqual(rows["hw_zone"]["five"], 2)                  # the seasons shown, not all five
        self.assertIn("not counting 2021-22, 2022-23", rows["hw_zone"]["five_text"])
        note = " ".join(rows["hw_zone"]["notes"])
        self.assertIn("Montana had 2 high wind products in 2021-22, 1 high wind product in 2022-23 and 1 high wind product "
                      "in 2024-25 that could not be placed to a zone", note)
        self.assertIn("This build cannot say how many were this zone's.", note)
        self.assertNotIn("1,230", note)
        self.assertNotIn("first placed product", note)
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIn("not counting", lines["wind_zone_warnings"]["text"])
        # winter storm: unplaced in 2021-22 only, so that zero is unknown and a real 2022-23 zero stays a zero
        self.assertEqual(rows["ice_warn"]["values"][0], None)
        self.assertEqual(rows["ice_warn"]["values"][1], 0)
        self.assertEqual(rows["ice_warn"]["values"][2], 2)
        self.assertIn("Montana: 1 winter storm product issued Dec 20, 2021 could not be placed to a zone",
                      rows["ice_warn"]["coverage"][0])
        self.assertTrue(rows["ice_warn"]["coverage"][0].endswith("This is not an all-clear."))
        # heat advisories: unplaced in 2022-23, so the roof's heat line keeps its statement
        heat = [x for g in result["roof"]["groups"] for x in g["lines"] if x["id"] == "heat_reports_warnings"][0]
        self.assertIn("Montana: 1 heat advisory product issued Aug 4, 2022 could not be placed to a zone", heat["coverage"])
        # the heat and flooding sections carry the same Montana statements
        sections = {s["id"]: s for s in result["sections"]}
        self.assertIn("1 heat advisory product in 2022-23", " ".join(sections["heat"]["notes"]))
        flood = " ".join(sections["flooding"]["notes"])
        self.assertIn("1 flood watch product in 2021-22 and 1 flash flood watch product in 2021-22", flood)

    def test_automated_reports_and_gust_coverage_are_said(self):
        result, rows = self._rows("full")
        self.assertEqual(rows["wind_n"]["values"][2], 1)              # the Mesonet gust report in 2023-24
        self.assertEqual(rows["wind_n"]["automated"], 3)              # Mesonet 2023-24, AWOS 2021-22, ASOS 2024-25; not the Public one
        self.assertIn("Of these wind reports in these five years, 3 are automated station reports (Mesonet, ASOS or AWOS), "
                      "not spotter reports.", " ".join(rows["wind_n"]["notes"]))
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertEqual(lines["wind_reports"]["text"],
                         "Report: 4 wind reports within 5 miles in these five years; 3 are automated station reports "
                         "(Mesonet, ASOS or AWOS), not spotter reports.")
        wind = [s["lead"] for s in result["sections"] if s["id"] == "wind"][0]
        self.assertIn("Report: 4 wind reports within 5 miles, 3 of them automated.", wind)
        self.assertIn("Only days of 50 kt or more are kept from each station's record", " ".join(rows["gust_days"]["notes"]))
        self.assertIn("Billings WTP is a SNOTEL site. It reports snow depth, not snowfall.",
                      " ".join(rows["snow"]["notes"]))

    def test_automated_sentence_singular_and_plural(self):
        self.assertEqual(S._automated_sentence(1, "wind reports"),
                         "Of these wind reports in these five years, 1 is an automated station report (Mesonet, ASOS or AWOS), "
                         "not a spotter report.")
        self.assertEqual(S._automated_sentence(100, "wind reports"),
                         "Of these wind reports in these five years, 100 are automated station reports (Mesonet, ASOS or AWOS), "
                         "not spotter reports.")

    def test_a_town_with_no_damage_rows_counts_its_wind_reports(self):
        result, rows = self._rows("no_damage")
        self.assertEqual(rows["wind_n"]["values"][3], 1)              # only the ASOS gust in 2024-25
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertNotIn("TSTM WND DMG", lines["wind_reports"]["text"])
        self.assertIn("Report: 3 wind reports within 5 miles in these five years", lines["wind_reports"]["text"])

    def test_partial_line_counts_automated_wind_reports_so_far(self):
        result, _ = self._rows("full")
        self.assertIn("1 wind report (1 of them automated)", result["table"]["partial"]["text"])

    def test_unavailable_warnings_blank_the_warning_lines(self):
        result, rows = self._rows("warnings_unavailable")
        self.assertTrue(all(v is None for v in rows["flood_warn"]["values"]))
        self.assertIn("could not be loaded in this update", " ".join(rows["flood_warn"]["notes"]))
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIsNone(lines["hail_warnings"]["value"])
        self.assertIn("could not be loaded in this update", lines["hail_warnings"]["text"])
        self.assertIsNotNone(lines["hail_reports"]["value"])         # the reports part is intact

    def test_town_gauge_none_and_unavailable_words(self):
        result, _ = self._rows("gauge_none", town=BILLINGS)
        self.assertEqual(result["town"]["gauge"], [
            "No gauge with an NWS flood stage is within 10 miles of Billings. That is not a statement that the river did "
            "not flood there."])
        result, _ = self._rows("gauge_unavailable", town=BILLINGS)
        self.assertEqual(result["town"]["gauge"], [
            "The river gauge line could not be loaded in this update; that is not the same as no river flood record. "
            "This is not an all-clear."])



class ForbiddenTests(unittest.TestCase):
    def test_forbidden_hits_rules(self):
        # the one list (tests/words_rules.py) with the same examples the summary's own check used
        self.assertTrue(words_rules.has_no_hail("No hail report"))
        self.assertFalse(words_rules.has_no_hail("This is not the same as no hail."))
        self.assertEqual(words_rules.forbidden_words("This is not an all-clear."), [])
        self.assertEqual(words_rules.forbidden_words("Data unavailable. This is not an all-clear, and an all-clear is not given."),
                         ["all-clear"])
        self.assertEqual(words_rules.forbidden_words("Hail is “one of the most damaging threats to homes.”"), [])
        self.assertEqual(words_rules.forbidden_words("NWS damage threat tag: considerable"), [])
        self.assertEqual(words_rules.forbidden_words("Report: 3 TSTM WND DMG reports"), [])
        self.assertEqual(words_rules.forbidden_words("The damage at this address was high."), ["damage"])
        self.assertEqual(words_rules.forbidden_words("The structure of the roof."), ["structure"])
        self.assertEqual(words_rules.forbidden_words("Billings Logan: a structure fire."), ["structure"])
        self.assertEqual(words_rules.forbidden_words("A risk of 5 percent."), ["risk"])
        self.assertEqual(words_rules.forbidden_words("Insurance eligibility."), ["eligibility", "insurance"])
        # the summary's own check delegates to the same list
        self.assertEqual(S.forbidden_hits("No hail report"), ["no hail"])
        self.assertEqual(S.forbidden_hits("A risk of 5 percent."), ["risk"])

    def test_the_six_refuter_strings_are_clean_now(self):
        sentences = ["Data unavailable: never shown as zero. This is not an all-clear.",
                     "Radar estimate: no radar hail; not the same as no hail.",
                     "Hail reports: 1 within 5 miles.",
                     "No report of hail within 5 miles",
                     "Station reading: nearest station, not the same as no station."]
        for text in sentences:
            self.assertEqual(S.forbidden_hits(text), [], text)


class WordsTests(unittest.TestCase):
    """The kind words, the polygon sentences, the developer word, the one forbidden list, and the lead and roof wording."""

    @classmethod
    def setUpClass(cls):
        cls.root, _ = build_store("full")
        cls.result = S.describe_summary(cls.root, ROW, COL, None)
        cls.town = S.describe_summary(cls.root, ROW, COL, None, town=BILLINGS)
        cls.rows = {r["key"]: r for r in cls.result["table"]["rows"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_kind_words_are_the_brief_list(self):
        # the brief's kind-word list (lines 201-202), without Analysis (NOHRSC, not shown) and with County product (the rows)
        self.assertEqual([k["word"] for k in S.KIND_WORDS],
                         ["Radar estimate", "Radar detection", "Report", "Record (NCEI)",
                          "Warning (NWS polygon, relayed by IEM)", "Zone product", "County product", "Station reading",
                          "Grid estimate", "River gauge", "Reference", "Data unavailable"])
        self.assertEqual(S.KIND_RECORD, "Record (NCEI)")
        key = S.WORDS_INDICATORS["kind_key"]
        for word in ("Record (NCEI)", "River gauge", "County product", "Warning (NWS polygon, relayed by IEM)"):
            self.assertIn(word, key)
        self.assertNotIn("Official record", key)
        self.assertEqual(self.rows["flood_warn"]["kind"], S.KIND_WARNING)

    def test_tornado_line_uses_the_short_record_label(self):
        lines = {x["id"]: x for g in self.result["roof"]["groups"] for x in g["lines"]}
        self.assertIn("; Record: ", lines["tornado_funnel"]["text"])

    def test_polygon_sentences_say_cell_or_part_of_it(self):
        for result in (self.result, self.town):
            text = " ".join(all_text(result))
            for phrase in ("covered this spot", "covering the spot", "covered the spot"):
                self.assertNotIn(phrase, text)
        self.assertIn("covered this cell or part of it", " ".join(all_text(self.result)))
        # the town variant (D38) is the one place "covered this spot" is written; the sheet's words never say it
        sheet_words = {k: v for k, v in S.WORDS_SUMMARY.items()
                       if k != "covered_town" and not k.startswith("town_warnings")}
        for text in list(strings_of(sheet_words)) + list(strings_of(S.WORDS_INDICATORS)) + [k["means"] for k in S.KIND_WORDS]:
            for phrase in ("covered this spot", "covering the spot", "covered the spot"):
                self.assertNotIn(phrase, text)

    def test_no_developer_word_store_in_the_sheet_words(self):
        for text in list(strings_of(S.WORDS_SUMMARY)) + list(strings_of(S.WORDS_INDICATORS)):
            self.assertIsNone(re.search(r"\bstore[sd]?\b", filled(text), re.IGNORECASE), text[:80])
        for text in all_text({"rows": self.result["table"]["rows"], "sections": self.result["sections"],
                              "roof": self.result["roof"]}):
            self.assertIsNone(re.search(r"\bstore[sd]?\b", re.sub(r"“[^”]*”", " ", text), re.IGNORECASE), text[:80])

    def test_summary_words_pass_the_one_forbidden_list(self):
        for text in list(strings_of(S.WORDS_SUMMARY)) + list(strings_of(S.WORDS_INDICATORS)):
            words_rules.assert_clean(self, filled(text), text[:60])
        for text in all_text(self.result):
            words_rules.assert_clean(self, text, text[:60])

    def test_hail_lead_names_the_report_with_its_kind_label(self):
        hail = [s["lead"] for s in self.result["sections"] if s["id"] == "hail"][0]
        self.assertIn("with hail of 1 inch or more; Report: ", hail)
        self.assertTrue(hail.startswith("Radar estimate: 3 days with hail of 1 inch or more; Report: 3 hail reports within "
                                        "5 miles, in these five years. "), hail)
        self.assertIn("days missing in these five seasons, the most in any row of this section.", hail)   # D33

    def test_precipitation_wording_says_what_the_total_is(self):
        lines = {x["id"]: x for g in self.result["roof"]["groups"] for x in g["lines"]}
        self.assertIn("rain and the water from melted snow. Snow counts here as water, not depth.",
                      lines["precipitation_year"]["text"])
        rain = [s["lead"] for s in self.result["sections"] if s["id"] == "rain"][0]
        self.assertIn("of precipitation in these five seasons, rain and melted snow together; the largest one day", rain)

    def test_radar_and_window_words_use_storm_report_days(self):
        notes = " ".join(self.rows["radar_max"]["notes"])
        self.assertIn("1,826 storm-report days (each from 12:00 to 12:00 UTC)", notes)
        self.assertNotIn("SPC", " ".join(all_text(self.result["how_made"])).replace("SPC report day", ""))

    def test_size_legend_is_in_how_made(self):
        how = " ".join(self.result["how_made"])
        self.assertIn("Size classes, inches: pea to mothball 0.25 to 0.74; penny to nickel 0.75 to 0.99; quarter to half dollar "
                      "1.00 to 1.49; ping-pong ball to golf ball 1.50 to 1.99; hen egg to tennis ball 2.00 to 2.74; baseball "
                      "or larger 2.75 or more.", how)

    def test_five_season_unavailable_words(self):
        self.assertEqual(S._five_unavailable_text(["2021-22"]),
                         "Data unavailable for the five seasons: 2021-22 has no usable value, so no five-season figure is "
                         "shown. This is not an all-clear.")
        self.assertNotIn("value to add", " ".join(strings_of(S.WORDS_SUMMARY)))

    def test_partial_and_station_wording_has_no_coverage_word(self):
        for text in list(strings_of(S.WORDS_SUMMARY)) + list(strings_of(S.WORDS_INDICATORS)):
            self.assertNotIn("coverage", text.lower(), text[:60])


class StationTests(unittest.TestCase):
    """The station rule at the cell centre on a sheet, the town point on a town page, nearest first, the passed-over share,
    and the five-season snowfall that names its stations."""

    def test_the_sheet_rule_runs_at_the_cell_centre_and_the_town_at_the_town_point(self):
        root, _ = build_store("full")
        try:
            index = S.hail.load_index(root)
            spot = S._Spot(root, index, ROW, COL, None)
            self.assertEqual(spot.station_point, (spot.lat, spot.lon))
            self.assertEqual(spot.anchor, (spot.lat, spot.lon))
            town = S._Spot(root, index, ROW, COL, BILLINGS)
            self.assertEqual(town.station_point, (BILLINGS["lat"], BILLINGS["lon"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_sheet_stations_are_named_nearest_first_from_the_spot(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            snow = {r["key"]: r for r in result["table"]["rows"]}["snow"]
            named = []
            for note in snow["notes"]:
                m = re.match(r"^(.+), ([\d.]+) miles from this spot$", note)
                if m:
                    named.append((m.group(1), float(m.group(2))))
            self.assertEqual([n for n, _ in named], ["Billings WTP", "Billings Logan"])
            self.assertEqual([miles for _, miles in named], sorted(miles for _, miles in named))
            self.assertIn("Stations: the two nearest from this spot that have enough days with the element. Distances are "
                          "from this spot.", snow["notes"])
            self.assertNotIn("tile centre", " ".join(snow["notes"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_five_season_snowfall_names_both_stations_and_the_passed_over_share(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            snow = {r["key"]: r for r in result["table"]["rows"]}["snow"]
            self.assertEqual(snow["five_text"], "Data unavailable for the five seasons: the seasons come from more than one "
                                                "station, so no five-season total is shown. This is not an all-clear.")
            self.assertEqual([s for s in snow["stations"] if s], ["Billings WTP"] * 2 + ["Billings Logan"] + ["Billings WTP"] * 2)
            self.assertIn("Billings WTP has 82.2 percent of the 2023-24 days (300 of 365), under the 95 percent rule, so "
                          "Billings Logan is shown.", " ".join(snow["notes"]))
            lead = [s["lead"] for s in result["sections"] if s["id"] == "snow"][0]
            self.assertIn("each season's snowfall is from the station named in it, and no five-season total is shown", lead)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_single_station_adds_nothing_to_the_five_season_text(self):
        root, _ = build_store("one_station")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            snow = {r["key"]: r for r in result["table"]["rows"]}["snow"]
            self.assertIsNotNone(snow["five"])
            self.assertNotIn("stations", snow["five_text"])
            self.assertNotIn("passed over", " ".join(snow["notes"]))
            self.assertNotIn("under the 95 percent rule", " ".join(snow["notes"]))
            lead = [s["lead"] for s in result["sections"] if s["id"] == "snow"][0]
            self.assertNotIn("from two stations", lead)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class GustTests(unittest.TestCase):
    """The gust rows follow the station record's own day counts: 95 percent, the coverage of every missing day, no zero for a
    record that cannot say."""

    def _rows(self, variant):
        root, _ = build_store(variant)
        try:
            result = S.describe_summary(root, ROW, COL, None)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        return result, {r["key"]: r for r in result["table"]["rows"]}

    def test_a_season_below_ninety_five_percent_is_data_unavailable(self):
        result, rows = self._rows("gust_40")
        self.assertIsNone(rows["gust_days"]["values"][1])
        self.assertIn("Data unavailable: Billings Logan has 146 of 365 days with a gust value, so this season is not shown; "
                      "a missing value is not zero. This is not an all-clear.", rows["gust_days"]["texts"][1])
        self.assertEqual(rows["gust_days"]["coverage"][1], "219 days missing")
        self.assertIsNone(rows["gust_days"]["five"])
        self.assertEqual(rows["gust_days"]["values"][3], 2)           # the complete seasons keep their counts

    def test_a_record_without_day_counts_never_shows_zero(self):
        result, rows = self._rows("gust_interim")
        for key in ("gust_days", "gust_max"):
            self.assertTrue(all(v is None for v in rows[key]["values"]), key)
            self.assertTrue(all(t == "Data unavailable" for t in rows[key]["texts"]), key)
            self.assertIn("does not yet say how many of its days have a value", " ".join(rows[key]["notes"]))
            self.assertIsNone(rows[key]["five"])
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIsNone(lines["wind_gust_days"]["value"])
        self.assertIn("Billings Logan", lines["wind_gust_days"]["text"])

    def test_an_empty_gust_record_with_no_valid_days_never_shows_zero(self):
        result, rows = self._rows("gust_empty")
        self.assertTrue(all(v is None for v in rows["gust_days"]["values"]))
        self.assertTrue(all("Data unavailable" in t for t in rows["gust_days"]["texts"]))
        self.assertNotIn("No day at 50 kt", " ".join(rows["gust_max"]["texts"]))

    def test_the_gust_lead_says_the_days_are_unavailable(self):
        result, _ = self._rows("gust_interim")
        wind = [s["lead"] for s in result["sections"] if s["id"] == "wind"][0]
        self.assertIn("Station reading: Data unavailable for the days with a gust of 50 kt or more at Billings Logan", wind)
        self.assertIn("This is not an all-clear.", wind)


class ZoneTests(unittest.TestCase):
    """Zone products: the statements for products that could not be placed; no zone is called reconfigured (D44)."""

    def test_a_zone_in_both_iem_sets_carries_no_reconfiguration_claim(self):
        # MTZ313 is in the 103-zone and the 83-zone sets (D44): no statement says it was reconfigured, and a zero with no
        # unplaced product in its season is a count (0 in 2021-22 and 2022-23), not Data unavailable
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            rows = {r["key"]: r for r in result["table"]["rows"]}
            text = json.dumps(result)
            self.assertNotIn("reconfigured", text)
            self.assertNotIn("not covered", text)
            self.assertEqual(rows["hw_zone"]["values"][:2], [0, 0])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_no_montana_total_of_all_families_is_in_the_zone_notes(self):
        result, rows = FailureVariantTests()._rows("zones_unplaced")
        for key in ("hw_zone", "ice_warn"):
            self.assertNotIn("1,230", " ".join(rows[key]["notes"]))

    def test_a_count_in_a_flagged_season_keeps_its_value_and_names_the_products(self):
        result, rows = FailureVariantTests()._rows("zones_unplaced")
        self.assertEqual(rows["hw_zone"]["values"][3], 1)
        self.assertIn("Montana: 1 high wind product issued Oct 1, 2024 could not be placed to a zone.",
                      rows["hw_zone"]["coverage"][3])

    def test_the_roof_zone_lines_carry_the_statement_and_the_partial_total(self):
        result, _ = FailureVariantTests()._rows("zones_unplaced")
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIn("not counting 2021-22, 2022-23", lines["wind_zone_warnings"]["text"])
        self.assertIn("Montana: 2 high wind products issued Dec 11, 2021 to Jan 2, 2022 could not be placed to a zone",
                      lines["wind_zone_warnings"]["coverage"])
        self.assertIn("could not be placed to a zone", lines["heat_reports_warnings"]["coverage"] or "")


class ReportTests(unittest.TestCase):
    """Automated station reports: one set for every wind count (Mesonet, ASOS or AWOS)."""

    def test_automated_sources_are_the_one_set(self):
        self.assertEqual(S.AUTO_SOURCES, ("Mesonet", "ASOS", "AWOS"))

    def test_the_gust_station_is_named_as_the_nearer_of_the_tiles_two(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            notes = {r["key"]: r for r in result["table"]["rows"]}["gust_days"]["notes"]
            self.assertIn("Gust station: Billings Logan, ", " ".join(notes))
            self.assertIn("(the nearer of this tile's two gust stations)", " ".join(notes))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_the_partial_line_names_its_automated_wind_reports(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            self.assertIn("(1 of them automated)", result["table"]["partial"]["text"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class RoofTests(unittest.TestCase):
    def test_a_day_with_two_detections_counts_once(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
            self.assertEqual(lines["hail_signatures"]["value"], 1)     # 2025-06-15: two rows, one SPC day
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_flood_warning_under_an_areal_flood_warning_counts(self):
        root, _ = build_store("full")
        try:
            result = S.describe_summary(root, ROW, COL, None)
            rows = {r["key"]: r for r in result["table"]["rows"]}
            self.assertEqual(rows["flood_warn"]["values"][0], 3)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class GaugeFailureTests(unittest.TestCase):
    """Each failure of the river gauge line is said as the unavailable sentence and marks the result partial (D16)."""

    def test_gauge_failures_are_partial_and_never_read_as_no_flood(self):
        for variant in ("gauge_block_absent", "gauge_unavailable_block", "gauge_town_missing", "gauge_unavailable",
                        "gauge_file_missing"):
            root, _ = build_store(variant)
            try:
                result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
            finally:
                shutil.rmtree(root, ignore_errors=True)
            gauge = " ".join(result["town"]["gauge"])
            self.assertNotIn("No gauge with an NWS flood stage", gauge, variant)
            self.assertIn("The river gauge line could not be loaded in this update", gauge, variant)
            self.assertTrue(gauge.endswith("This is not an all-clear."), variant)
            self.assertEqual(result["state"], "partial", variant)
            self.assertTrue(any(p.startswith("river gauge: ") for p in (result["problem"] or "").split("; ")), variant)
            flooding = [s for s in result["sections"] if s["id"] == "flooding"][0]
            self.assertEqual(flooding.get("lines"), result["town"]["gauge"], variant)

    def test_a_gauge_with_no_flood_stage_says_so_without_marking_the_result(self):
        root, _ = build_store("gauge_none")
        try:
            result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
            self.assertEqual(result["state"], "loaded")
            self.assertIsNone(result["problem"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ReviewFixTests(unittest.TestCase):
    """The B1 review's fixes (D32 to D41) on the synthetic store: a failed station or gust file is named, never read as no
    record or skipped; a zero report reads as the no-report sentence; the all-clear sentence ends every unavailable and
    partial line; the town page counts its polygon warnings at the town point when the towns file is there (D38)."""

    def _variant(self, variant: str = "full"):
        root, _ = build_store(variant)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_a_chosen_station_whose_record_did_not_load_is_named_and_never_read_as_no_reading(self):
        root = self._variant("full")
        (root / "hail" / "sd" / "USC00240802.json").unlink()          # the nearer passing station's file is gone
        result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
        snow = {r["key"]: r for r in result["table"]["rows"]}["snow"]
        self.assertIn("Billings Logan", snow["texts"][0])              # the farther station is shown, and says so
        self.assertIn("Billings WTP's record for 2021-22 could not be loaded in this update, so Billings Logan is shown; "
                      "that is not the same as no snowfall reading. This is not an all-clear.", " ".join(snow["notes"]))
        self.assertNotIn("no station has enough reports", " ".join(snow["texts"]))

    def test_no_station_figure_from_failed_files_is_the_failed_sentence_not_a_no_station_claim(self):
        root = self._variant("full")
        for sid in ("USC00240802", "USW00024033"):
            (root / "hail" / "sd" / f"{sid}.json").unlink()
        snow = {r["key"]: r for r in S.describe_summary(root, ROW, COL, None, town=BILLINGS)["table"]["rows"]}["snow"]
        self.assertTrue(snow["texts"][0].startswith("Data unavailable for 2021-22: Billings WTP and Billings Logan could not be "
                                                    "loaded in this update"), snow["texts"][0])
        self.assertTrue(snow["texts"][0].endswith("This is not an all-clear."), snow["texts"][0])
        self.assertFalse(any("No station within 40 miles" in t for t in snow["texts"]), snow["texts"])
        self.assertIsNone(snow["five"])

    def test_a_gust_file_that_did_not_load_is_named_failed_and_the_rule_does_not_skip_it(self):
        root = self._variant("full")
        (root / "hail" / "s" / "BIL.json").unlink()
        rows = {r["key"]: r for r in S.describe_summary(root, ROW, COL, None)["table"]["rows"]}
        self.assertTrue(rows["gust_days"]["texts"][0].startswith("Data unavailable: Billings Logan could not be loaded"),
                        rows["gust_days"]["texts"][0])
        self.assertTrue(rows["gust_days"]["texts"][0].endswith("This is not an all-clear."))
        self.assertIsNone(rows["gust_days"]["five"])

    def test_a_no_report_count_reads_as_the_no_report_sentence_never_as_zero_reports(self):
        root = self._variant("full")
        result = S.describe_summary(root, ROW, COL, None)
        for row in result["table"]["rows"]:
            if row["kind"] != "Report":                  # warnings and zone products keep their counts
                continue
            for text in row["texts"] + [row["five_text"]]:
                self.assertFalse(re.match(r"^0 (hail|wind|freezing|flood|rain|tornado|extreme)", text or ""), (row["key"], text))
        hail_n = {r["key"]: r for r in result["table"]["rows"]}["hail_n"]
        self.assertIn("No NWS local storm report of hail within 5 miles in 2021-22; reports are not a complete record.",
                      hail_n["texts"][0])
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIn("No NWS local storm report of tornado, funnel cloud or landspout within 5 miles in these five years; "
                      "reports are not a complete record", lines["tornado_funnel"]["text"])

    def test_every_unavailable_partial_and_held_line_ends_with_the_all_clear_sentence(self):
        for variant in ("full", "snow_none", "gauge_unavailable", "stations_unavailable", "warnings_unavailable",
                        "reports_unavailable", "zones_unplaced", "one_station", "climate_unavailable"):
            root, _ = build_store(variant)
            try:
                result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
            finally:
                shutil.rmtree(root, ignore_errors=True)
            for text in all_text(result):
                if len(text) > 60 and not text.startswith("Kind words") and (
                        "Data unavailable" in text or "could not be loaded in this update" in text or text.startswith("Partial")):
                    self.assertTrue(text.endswith("This is not an all-clear."), (variant, text[-160:]))
            self.assertTrue(result["table"]["partial"]["text"].endswith("This is not an all-clear."), variant)

    def test_the_held_row_names_its_reason_in_the_unit_slot_and_no_unit_reads_none(self):
        root = self._variant("full")
        held = {r["key"]: r for r in S.describe_summary(root, ROW, COL, None)["table"]["rows"]}["held"]
        self.assertEqual(held["unit"], "reason")
        self.assertEqual(S.UNIT_SPEC["reason"]["word"], "no free public record was used in this history")
        self.assertNotIn("none", [u["word"] for u in S.UNIT_SPEC.values()])

    def test_a_town_page_counts_its_polygon_warnings_at_the_town_point_when_the_towns_file_is_there(self):
        root = self._variant("full")
        towns = {"f": joins.TOWNS_FORMAT if hasattr(joins, "TOWNS_FORMAT") else "hail-joins-towns-v1", "d0": "2020-01-01",
                 "state": "loaded", "reason": None, "towns": {"billings": {
                     "name": "Billings", "lat": 45.7833, "lon": -108.5007, "cell": [ROW, COL],
                     "events": [[0, "FF.W", "TFX", "2022-06-14T10:00Z", None],
                                [1, "FL.W", "TFX", "2024-06-14T10:00Z", None],
                                [2, "SV.W", "TFX", "2023-05-20T00:00Z", None]]}}}
        write_json(root / "hail" / "j" / "towns.json", towns)
        result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
        flood = {r["key"]: r for r in result["table"]["rows"]}["flood_warn"]
        self.assertEqual(flood["texts"][0], "1 flood or flash flood warning")       # 2021-22: the town's FF.W (June 2022)
        self.assertEqual(flood["texts"][2], "1 flood or flash flood warning")       # 2023-24: the town's FL.W (June 2024)
        self.assertEqual(flood["five"], 2)
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        self.assertIn("covered this spot", lines["hail_warnings"]["text"])
        self.assertIn("covered this spot", " ".join(s["lead"] for s in result["sections"] if s["id"] == "flooding"))
        sheet = S.describe_summary(root, ROW, COL, None)                              # the sheet keeps the cell's words
        self.assertIn("covered this cell or part of it", " ".join(s["lead"] for s in sheet["sections"] if s["id"] == "flooding"))

    def test_a_towns_file_that_did_not_load_says_so_and_a_partial_one_says_why(self):
        root = self._variant("full")
        towns = {"f": "hail-joins-towns-v1", "d0": "2020-01-01", "state": "unavailable", "reason": "the warnings part did not answer",
                 "towns": {}}
        write_json(root / "hail" / "j" / "towns.json", towns)
        result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
        flood = {r["key"]: r for r in result["table"]["rows"]}["flood_warn"]
        self.assertIsNone(flood["five"])
        self.assertEqual(flood["five_text"], "Data unavailable")
        self.assertTrue(" ".join(flood["notes"]).endswith("This is not an all-clear."), flood["notes"])
        towns["state"] = "partial"
        towns["towns"] = {"billings": {"name": "Billings", "lat": BILLINGS["lat"], "lon": BILLINGS["lon"], "cell": [ROW, COL],
                                       "events": [[0, "FF.W", "TFX", "2022-06-14T10:00Z", None]]}}
        write_json(root / "hail" / "j" / "towns.json", towns)
        result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
        notes = " ".join({r["key"]: r for r in result["table"]["rows"]}["flood_warn"]["notes"])
        self.assertIn("Warnings for this spot were only partly checked in this update (the warnings part did not answer)", notes)
        self.assertIn("Each count is a warning whose polygon covered this spot", notes)

    def _tile_list(self, root, passing, unread=(), capped=False, element="SNOW"):
        """Writes hail/tl/<tile>.json (stations.py's tile list, D36) for the spot's tile with these entries for one element."""
        doc = {"f": S.TILE_LIST_FORMAT, "tile": "r0092_c0214", "centre": [45.75, -108.55], "miles": 40.0, "cap": 6,
               "elements": {element: {"passing": passing, "unread": list(unread), "capped": capped}}}
        write_json(root / "hail" / "tl" / "r0092_c0214.json", doc)

    def test_the_two_nearest_passing_candidates_come_from_the_tile_list_at_the_point(self):
        root = self._variant("full")
        wtp = {"id": "USC00240802", "name": "BILLINGS WTP", "lat": 45.78, "lon": -108.52, "miles": 0.0, "ok": 2000, "of": 2192,
               "share": 0.9124}
        logan = {"id": "USW00024033", "name": "BILLINGS INTL AP", "lat": 45.8077, "lon": -108.5429, "miles": 0.0, "ok": 2100,
                 "of": 2192, "share": 0.9578}
        far = {"id": "US1MTYS0028", "name": "BILLINGS 4.2 WSW", "lat": 45.7595, "lon": -108.6613, "miles": 0.0, "ok": 2000,
               "of": 2192, "share": 0.91}
        self._tile_list(root, [far, wtp, logan])                 # not nearest-first on purpose: the rule sorts by the point
        result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
        self.assertEqual(result["town"]["stations"]["snow"][0]["name"], "BILLINGS WTP")
        self.assertEqual([s["name"] for s in result["town"]["stations"]["snow"]], ["BILLINGS WTP", "BILLINGS INTL AP"])

    def test_an_unread_candidate_nearer_than_the_second_pick_is_named_and_never_skipped(self):
        root = self._variant("full")
        wtp = {"id": "USC00240802", "name": "BILLINGS WTP", "lat": 45.78, "lon": -108.52, "miles": 0.0, "ok": 2000, "of": 2192,
               "share": 0.9124}
        logan = {"id": "USW00024033", "name": "BILLINGS INTL AP", "lat": 45.8077, "lon": -108.5429, "miles": 0.0, "ok": 2100,
                 "of": 2192, "share": 0.9578}
        unread = [{"id": "US1MTBIL0001", "name": "BILLINGS 1 N", "lat": 45.79, "lon": -108.5, "miles": 0.0,
                   "reason": "the file did not load"}]
        self._tile_list(root, [wtp, logan], unread=unread)
        spot = S._Spot(root, hail.load_index(root), ROW, COL, dict(BILLINGS))
        state, chosen, res = spot.chosen("SNOW")
        self.assertEqual([c["name"] for c in chosen], ["BILLINGS WTP", "BILLINGS INTL AP"])
        self.assertEqual([u["name"] for u in res["unread"]], ["BILLINGS 1 N"])
        self.assertIn("BILLINGS 1 N", " ".join(stations.station_words(res, "SNOW")))

    def test_a_capped_list_with_fewer_than_two_near_the_point_falls_back_to_the_station_block(self):
        root = self._variant("full")
        far = {"id": "USC00240802", "name": "BILLINGS WTP", "lat": 46.5, "lon": -108.0, "miles": 0.0, "ok": 2000, "of": 2192,
               "share": 0.9124}
        self._tile_list(root, [far], capped=True)
        spot = S._Spot(root, hail.load_index(root), ROW, COL, dict(BILLINGS))
        self.assertIsNone(spot.chosen_from_tile_list("SNOW"))
        state, chosen, _res = spot.chosen("SNOW")
        self.assertEqual(state, "two")                            # the station block answers, as before

    def test_the_partial_season_grid_values_are_preliminary_and_never_a_record(self):
        root = self._variant("full")
        partial = S.describe_summary(root, ROW, COL, None)["table"]["partial"]["text"]
        grid = partial.split(" Reports so far")[0]
        self.assertTrue(grid.startswith("Preliminary grid estimate: 2026-27 so far"), grid)
        self.assertNotIn("record", grid.lower())
        self.assertIn("The newest days are preliminary and provisional until NOAA publishes the scaled month.", grid)

    def test_gauge_lines_carry_one_river_gauge_label_each_and_the_gauge_is_read_once(self):
        root = self._variant("full")
        gauge = S.describe_summary(root, ROW, COL, None, town=BILLINGS)["town"]["gauge"]
        for line in gauge:
            self.assertFalse(line.startswith("River gauge"), line)
            self.assertNotIn("River gauge", line)
        self.assertTrue(any(line.startswith("NWS flood stage") for line in gauge), gauge)

    def test_a_season_with_missing_days_names_them_once_on_its_coverage_line(self):
        root = self._variant("full")
        rows = {r["key"]: r for r in S.describe_summary(root, ROW, COL, None)["table"]["rows"]}
        for key in ("tmax", "tmin"):
            for cov in rows[key]["coverage"]:
                if cov:
                    self.assertEqual(cov.count("days missing"), 1, cov)


class RoundTwoWordsTests(unittest.TestCase):
    """The second round's rulings (B5 D45 to D48 and the second completion list): the NCEI flood records as their own row,
    the R20 title only in the About citations, the all-clear on the one-station line, the five-season gust cells that name
    their station, and the roof lines' kind words and reasons in every state."""

    def _summary(self, variant: str = "full") -> dict:
        root, _ = build_store(variant)
        self.addCleanup(shutil.rmtree, root, True)
        return S.describe_summary(root, ROW, COL, None)

    @staticmethod
    def _rows(result: dict) -> dict:
        return {r["key"]: r for r in result["table"]["rows"]}

    @staticmethod
    def _lines(result: dict) -> dict:
        return {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}

    def test_the_r20_title_is_only_in_the_about_citations(self):                  # D46
        text = S.not_quoted_text()
        self.assertNotIn("freeze-thaw damage", text)
        self.assertIn("R20 (its title is in the references list above)", text)
        self.assertEqual([c["id"] for c in S.citations()], ["R20"])
        self.assertEqual(S.citations()[0]["source"], "freeze-thaw damage to roofs")
        result = self._summary("full")
        words = " ".join((x["text"] or "") for x in self._lines(result).values())
        words += " ".join(ref["text"] for g in result["roof"]["groups"] for ref in g["references"])
        self.assertNotIn("freeze-thaw damage", words)

    def test_the_flood_records_are_their_own_row_and_lead_the_flooding_section(self):  # D48
        result = self._summary("flood_record")
        rows = self._rows(result)
        record = rows["flood_record_n"]
        self.assertEqual(record["kind"], S.KIND_RECORD)
        self.assertEqual(record["unit"], "count")
        self.assertEqual(record["values"][0], 1)                       # 2021-22: the June 10, 2022 flood record
        self.assertEqual(record["texts"][0], "1 flood or flash flood record")
        self.assertNotIn("Record (NCEI)", rows["flood_report_n"]["texts"][0])     # the report row carries no record
        flooding = [s for s in result["sections"] if s["id"] == "flooding"][0]
        self.assertIn("Record (NCEI): 1 flood or flash flood record within 5 miles in these five years", flooding["lead"])

    def test_a_zero_flood_record_count_reads_as_the_no_record_sentence(self):    # D48, D41
        rows = self._rows(self._summary("full"))
        self.assertEqual(rows["flood_record_n"]["texts"][0],
                         "No NOAA Storm Events record of flood or flash flood within 5 miles in 2021-22 "
                         "(records are not a complete list).")
        self.assertEqual(rows["flood_record_n"]["five_text"],
                         "No NOAA Storm Events record of flood or flash flood within 5 miles in these five years "
                         "(records are not a complete list).")

    def test_the_one_station_partial_line_ends_with_the_all_clear(self):         # D47
        rows = self._rows(self._summary("one_station"))
        notes = [n for key in ("snow", "snow_depth") for n in rows[key]["notes"] if n.startswith("Only one station")]
        self.assertTrue(notes, "the one_station variant should give the one-station line")
        for note in notes:
            self.assertTrue(note.endswith("This is not an all-clear."), note)

    def test_the_five_season_gust_cells_name_their_station(self):                # B5-16, D41
        # the fixture's 2021-22 gust record is short (257 of 365 days), so its five-season cell says why; with every season
        # complete (set in the store file here) the five-season cells name the station and the flagged peak keeps its flag
        short = self._rows(self._summary("full"))["gust_days"]
        self.assertIsNone(short["five"])
        self.assertEqual(short["five_text"], "Data unavailable")
        self.assertTrue(short["five_note"].startswith("Data unavailable for the five seasons"), short["five_note"])
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        station = root / "hail" / "s" / "BIL.json"
        doc = json.loads(station.read_text(encoding="utf-8"))
        for per in doc["periods"]["season"].values():
            per["ok"] = per["n"]
        station.write_text(json.dumps(doc), encoding="utf-8")
        rows = self._rows(S.describe_summary(root, ROW, COL, None))
        days, peak = rows["gust_days"], rows["gust_max"]
        self.assertEqual(days["five"], 3)                       # 2022-07-01, 2025-02-20 and 2025-06-15 at 50 kt or more
        self.assertEqual(days["five_text"], "3 days at Billings Logan")
        self.assertEqual(peak["five_text"], "105 kt (121 mph) on Feb 20, 2025 at Billings Logan, flagged for check")

    def test_the_ice_dam_line_carries_its_kind_word_in_every_state(self):        # D41
        full = self._lines(self._summary("full"))["ice_dam_weather_days"]["text"]
        self.assertTrue(full.startswith("Station reading: "), full)
        for variant in ("stations_unavailable",):
            text = self._lines(self._summary(variant))["ice_dam_weather_days"]["text"]
            self.assertIn("(days, station reading; a measured pattern, not ice dams)", text, variant)
            self.assertTrue(text.endswith("This is not an all-clear."), text)

    def test_the_roof_snow_lines_give_the_reason_when_the_stations_did_not_load(self):  # D16, D20
        lines = self._lines(self._summary("stations_unavailable"))
        for key in ("snowfall_season", "snow_depth"):
            self.assertIn("Station readings could not be loaded in this update; that is not the same as no station readings.",
                          lines[key]["text"], key)
            self.assertTrue(lines[key]["text"].endswith("This is not an all-clear."), key)


if __name__ == "__main__":
    unittest.main()
