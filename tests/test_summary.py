"""Summary (B5 part B1): the five-season table, the roof section and the words, on a synthetic store the test writes.

The store has one spot near Billings (B1 cell row 921, column 2149; tile r0092_c0214) with every part the table reads:
radar estimates, LSR reports, polygon warnings, zone and county products, station gusts, grid records (one season with
31 missing days), station records (a season where the nearest station falls short of 95 percent and the second passes;
a season where neither passes), and the river gauge. Variants remove a part or the partial season. Nothing here is real
data: the real store is checked by the B5 verify and gate steps on the built store (read-only), not by these tests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the shared forbidden list)
from website import climate, gauges, hail, joins, stations  # noqa: E402
from website import summary as S  # noqa: E402

import words_rules  # noqa: E402

AS_OF = date(2026, 10, 16)
ROW, COL = 921, 2149                       # the B1 cell of Billings (the town point is 45.7833 N, 108.5007 W: towns.json)
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
        self.assertIn("Data unavailable for 2021-22: Billings Logan has 257 of 365 days with a gust value",
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
        self.assertEqual(one["texts"][2], "0 days")
        self.assertEqual(one["texts"][3], "3 days")
        # D82(c): 2021-22 has 108 days missing (257 of 365 with a value, under 95 percent): no zero is shown, so its count is
        # Data unavailable with the days missing, and the five-season total cannot leave that season out
        self.assertIsNone(one["values"][0])
        self.assertTrue(one["texts"][0].startswith("Data unavailable for 2021-22"), one["texts"][0])
        self.assertEqual(one["coverage"][0], "108 days missing")
        self.assertIsNone(one["five"])
        self.assertIn("Data unavailable for the five seasons: 2021-22 has no usable value", one["five_note"])

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
        # D57: the season's own text names its station, and the flag's words still close the cell (D12)
        self.assertEqual(gmax["texts"][3], "105 kt (121 mph) on Feb 20, 2025 at Billings Logan, flagged for check")
        self.assertEqual(gmax["stations"], ["Billings Logan"] * 5)
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

    def test_held_row_has_the_four_reasons(self):                                                       # D41, D88(b)
        held = self.rows["held"]
        self.assertEqual(held["kind"], "Data unavailable")
        self.assertTrue(all(v is None for v in held["values"]))
        keys = ("lightning", "uv_and_sun", "roof_surface_temperature", "ponding")
        self.assertEqual(held["notes"], [S.WORDS_INDICATORS["held"][k] for k in keys])
        for note, key in zip(held["notes"], keys):                  # the lead: the kind word, then the label, once each
            with self.subTest(held=key):
                self.assertTrue(note.startswith(f"{S.KIND_UNAVAILABLE}: {S.HELD_NAMES[key]}. "), note[:90])
                self.assertTrue(note.endswith(S.ALL_CLEAR), note[-40:])

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
        self.assertIsNone(lines["hail_size_days"]["value"])                 # D82(c): 2021-22 is short, so the five seasons are
        self.assertIn("Data unavailable", lines["hail_size_days"]["text"])
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
        sheet_indicators = {k: v for k, v in S.WORDS_INDICATORS.items() if k != "what_warnings_town"}
        for text in list(strings_of(sheet_words)) + list(strings_of(sheet_indicators)) + [k["means"] for k in S.KIND_WORDS]:
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
        self.assertTrue(hail.startswith("Radar estimate: Data unavailable for the days with hail of 1 inch or more in these five "
                                        "years; Report: 3 hail reports within 5 miles, in these five years. "), hail)
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
        self.assertIn("Data unavailable for 2022-23: Billings Logan has 146 of 365 days with a gust value, so this season is not shown; "
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

    def test_a_zone_statement_closes_its_line_with_the_all_clear_sentence_once(self):          # D98(b), D41
        """The zone statement's own words end with the all-clear sentence, so a coverage line, the five-season line and a
        roof line carry it once at their end, with no doubled full stop; the zero cell keeps its own unavailable sentence."""
        self.assertTrue(S.WORDS_SUMMARY["zone_flag"].endswith(" This is not an all-clear."))
        self.assertEqual(S.WORDS_SUMMARY["zone_flag"].count("This is not an all-clear."), 1)
        flag = S.WORDS_SUMMARY["zone_flag"].format(n="2", noun="high wind products", when="Dec 11, 2021 to Jan 2, 2022")
        self.assertEqual(S._cover(2, flag), "2 days missing; Montana: 2 high wind products issued Dec 11, 2021 to Jan 2, 2022 "
                         "could not be placed to a zone. This is not an all-clear.")
        self.assertEqual(S._cover(0, flag), "Montana: 2 high wind products issued Dec 11, 2021 to Jan 2, 2022 could not be "
                         "placed to a zone. This is not an all-clear.")
        self.assertEqual(S._joined_flags([{"flag": flag}, {"flag": flag}, {"flag": None}]),          # distinct, as clauses
                         "Montana: 2 high wind products issued Dec 11, 2021 to Jan 2, 2022 could not be placed to a zone")
        result, rows = FailureVariantTests()._rows("zones_unplaced")
        for key in ("hw_zone", "ice_warn"):
            for line in rows[key]["coverage"] + [rows[key]["five_coverage"]]:
                if line and "could not be placed" in line:
                    self.assertEqual(line.count("This is not an all-clear."), 1, line)
                    self.assertTrue(line.endswith("could not be placed to a zone. This is not an all-clear."), line)
                    self.assertNotIn("..", line)
        five = rows["hw_zone"]["five_coverage"]                 # the three flagged seasons, each statement once
        self.assertEqual(five.count("could not be placed to a zone"), 3, five)
        self.assertEqual(rows["hw_zone"]["texts"][0].count("This is not an all-clear."), 1)   # the zero cell's own sentence
        for x in (x for g in result["roof"]["groups"] for x in g["lines"]):
            cover = x.get("coverage") or ""
            if "could not be placed to a zone" in cover:
                self.assertEqual(cover.count("This is not an all-clear."), 1, (x["id"], cover))
                self.assertNotIn("..", cover)


class ReportTests(unittest.TestCase):
    """Automated station reports: one set for every wind count (Mesonet, ASOS or AWOS)."""

    def test_automated_sources_are_the_one_set(self):
        self.assertEqual(S.AUTO_SOURCES, ("Mesonet", "ASOS", "AWOS"))

    def test_the_gust_station_is_the_nearest_to_the_spot_and_its_distance_is_from_the_spot(self):      # D56, R6
        root, _ = build_store("full")
        try:
            station = (45.8077, -108.5429)                  # BIL, the synthetic store's gust station (s/BIL.json)

            def gust_note(town):
                result = S.describe_summary(root, ROW, COL, None, town=town)
                notes = {r["key"]: r for r in result["table"]["rows"]}["gust_days"]["notes"]
                return next(n for n in notes if n.startswith("Gust station: "))

            # the sheet measures from the grid cell's centre
            lat, lon = hail.cell_centre(ROW, COL)
            sheet = round(stations.haversine_miles(lat, lon, *station), 1)
            self.assertIn(f"Gust station: Billings Logan, {sheet:.1f} miles from this spot (the nearest gust station to this "
                          "spot).", gust_note(None))
            # a town page measures from the town point: a point 0.3 degrees north is a different distance from the station
            north = dict(BILLINGS, lat=BILLINGS["lat"] + 0.3)
            town = round(stations.haversine_miles(north["lat"], north["lon"], *station), 1)
            self.assertNotEqual(sheet, town)
            self.assertIn(f"Gust station: Billings Logan, {town:.1f} miles from this spot", gust_note(north))
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


    def test_every_unavailable_roof_line_leads_with_its_kind_word(self):                                    # F2, D41, D57, D82(d)
        root, _ = build_store("full")
        try:
            for town in (None, dict(BILLINGS)):
                result = S.describe_summary(root, ROW, COL, None, town=town)
                unavailable = [x for g in result["roof"]["groups"] for x in g["lines"] if x["value"] is None]
                self.assertTrue(unavailable, "the synthetic store has unavailable roof lines to check")
                for line in unavailable:
                    with self.subTest(line=line["id"], town=town is not None):
                        self.assertTrue(line["text"].startswith(f"{line['kind']}: "), line["text"][:90])
                        self.assertTrue(line["text"].endswith(S.ALL_CLEAR), line["text"][-60:])
                        self.assertEqual(line["text"].count(line["kind"]), 1, "the kind word is carried once (D87(a))")
                        self.assertNotRegex(line["label"], r"\b(radar estimate|station reading|grid estimate|record|report)\)")  # D87(a)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_an_unavailable_roof_line_is_its_kind_then_its_label_and_its_reason(self):                      # F2, D87(a)
        line = S._line("snowfall_season", "Snowfall, July to June (inches)", "Station reading", "in", None, None,
                       "Data unavailable for the five seasons: the seasons come from more than one station.")
        self.assertIsNone(line["value"])
        self.assertEqual(line["text"], "Station reading: Snowfall, July to June (inches). Data unavailable for "
                                       "the five seasons: the seasons come from more than one station. This is not an all-clear.")
        self.assertEqual(S.ROOF_LINES["wind_gust_days"][0], "Peak gust of 50 knots (58 mph) or more (days)")   # the unit word only

    def test_a_held_line_leads_with_its_kind_word_once(self):                                              # D41, D87(a), D88(b)
        """A held line leads with its kind word, then its label (the name in HELD_NAMES), then its reason, and ends with the
        all-clear sentence: "Data unavailable: Roof ponding. ... This is not an all-clear." (D88(b))."""
        self.assertEqual(sorted(S.HELD_NAMES), sorted(S.WORDS_INDICATORS["held"]))
        for key, text in S.WORDS_INDICATORS["held"].items():
            with self.subTest(held=key):
                self.assertTrue(text.startswith(f"{S.KIND_UNAVAILABLE}: {S.HELD_NAMES[key]}. "), text[:90])
                self.assertEqual(text.count(S.KIND_UNAVAILABLE), 1, text[:60])
                self.assertTrue(text.endswith(S.ALL_CLEAR), text[-40:])

    def test_the_built_held_lines_are_the_held_words_on_the_sheet_and_the_town_page(self):                  # R1-F1, D82, D87(a)
        """The built summary, not only the words: the roof section's held lines (every group) and the table's held row notes
        carry the held words as they are, with the kind word and the label, on the sheet and on a town page."""
        root, _ = build_store("full")
        try:
            for town in (None, dict(BILLINGS)):
                result = S.describe_summary(root, ROW, COL, None, town=town)
                held = {h["id"]: h for g in result["roof"]["groups"] for h in g["held"]}
                self.assertEqual(sorted(held), sorted(h for ids in S.HELD_GROUPS.values() for h in ids))
                for key, line in held.items():
                    with self.subTest(held=key, town=town is not None):
                        self.assertEqual(line["text"], S.WORDS_INDICATORS["held"][key])
                        self.assertEqual((line["kind"], line["label"]), (S.KIND_UNAVAILABLE, S.HELD_NAMES[key]))
                notes = next(r for r in result["table"]["rows"] if r["key"] == "held")["notes"]
                self.assertEqual(sorted(notes), sorted(S.WORDS_INDICATORS["held"][k] for k in
                                                       ("lightning", "uv_and_sun", "roof_surface_temperature", "ponding")))
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
        self.assertTrue(snow["texts"][0].startswith("Data unavailable for 2021-22: Billings WTP and Billings Logan did not load; "
                                                    "that is not the same as no snowfall reading"), snow["texts"][0])
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
        self.assertEqual(S.UNIT_SPEC["reason"]["word"], "no free public record was used in this history. This is not an all-clear.")
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
        block = {"centre": [45.75, -108.55], "margin_miles": 5.0, "passing": passing, "unread": list(unread),
                 "rejected": [], "capped": capped}
        doc = {"f": S.TILE_LIST_FORMAT, "tile": "r0092_c0214", "centre": [45.75, -108.55], "miles": 40.0,
               "margin_miles": 5.0, "elements": {element: block}}
        write_json(root / "hail" / "tl" / "r0092_c0214.json", doc)

    def test_the_two_nearest_passing_candidates_come_from_the_tile_list_at_the_point(self):
        root = self._variant("full")
        wtp = {"id": "USC00240802", "name": "Billings WTP", "lat": 45.78, "lon": -108.52, "miles": 0.0, "ok": 2000, "of": 2192,
               "share": 0.9124}
        logan = {"id": "USW00024033", "name": "Billings Intl AP", "lat": 45.8077, "lon": -108.5429, "miles": 0.0, "ok": 2100,
                 "of": 2192, "share": 0.9578}
        far = {"id": "US1MTYS0028", "name": "Billings 4.2 WSW", "lat": 45.7595, "lon": -108.6613, "miles": 0.0, "ok": 2000,
               "of": 2192, "share": 0.91}
        self._tile_list(root, [far, wtp, logan])                 # not nearest-first on purpose: the rule sorts by the point
        result = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
        self.assertEqual(result["town"]["stations"]["snow"][0]["name"], "Billings WTP")
        self.assertEqual([s["name"] for s in result["town"]["stations"]["snow"]], ["Billings WTP", "Billings Intl AP"])

    def test_an_unread_candidate_nearer_than_the_second_pick_is_named_and_never_skipped(self):
        root = self._variant("full")
        wtp = {"id": "USC00240802", "name": "Billings WTP", "lat": 45.78, "lon": -108.52, "miles": 0.0, "ok": 2000, "of": 2192,
               "share": 0.9124}
        logan = {"id": "USW00024033", "name": "Billings Intl AP", "lat": 45.8077, "lon": -108.5429, "miles": 0.0, "ok": 2100,
                 "of": 2192, "share": 0.9578}
        unread = [{"id": "US1MTBIL0001", "name": "Billings 1 N", "lat": 45.79, "lon": -108.5, "miles": 0.0,
                   "reason": "the file did not load"}]
        self._tile_list(root, [wtp, logan], unread=unread)
        spot = S._Spot(root, hail.load_index(root), ROW, COL, dict(BILLINGS))
        state, chosen, res = spot.chosen("SNOW")
        self.assertEqual([c["name"] for c in chosen], ["Billings WTP", "Billings Intl AP"])
        self.assertEqual([u["name"] for u in res["unread"]], ["Billings 1 N"])
        self.assertIn("Billings 1 N", " ".join(stations.station_words(res, "SNOW")))

    def test_a_capped_list_with_fewer_than_two_near_the_point_falls_back_to_the_station_block(self):
        root = self._variant("full")
        far = {"id": "USC00240802", "name": "Billings WTP", "lat": 46.5, "lon": -108.0, "miles": 0.0, "ok": 2000, "of": 2192,
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

    def test_the_ice_dam_line_leads_with_station_reading_in_every_state(self):        # D41, D57
        full = self._lines(self._summary("full"))["ice_dam_weather_days"]["text"]
        self.assertTrue(full.startswith("Station reading: "), full)
        for variant in ("stations_unavailable", "gust_empty", "no_partial"):
            line = self._lines(self._summary(variant))["ice_dam_weather_days"]
            self.assertTrue(line["text"].startswith("Station reading: "), (variant, line["text"]))
            if line["value"] is None:                 # a line with no figure says why, and ends with the all-clear
                self.assertTrue(line["text"].endswith("This is not an all-clear."), (variant, line["text"]))
        text = self._lines(self._summary("stations_unavailable"))["ice_dam_weather_days"]["text"]
        self.assertIn("Days with 1 inch or more on the ground and a low below 32 F (days; a measured pattern, not ice dams). ",
                      text)
        self.assertTrue(text.startswith("Station reading: Days with 1 inch or more on the ground"), text)

    def test_the_roof_snow_lines_give_the_reason_when_the_stations_did_not_load(self):  # D16, D20
        lines = self._lines(self._summary("stations_unavailable"))
        for key in ("snowfall_season", "snow_depth"):
            self.assertIn("Station readings could not be loaded in this update; that is not the same as no station readings.",
                          lines[key]["text"], key)
            self.assertTrue(lines[key]["text"].endswith("This is not an all-clear."), key)


class StationPicksAndNames(unittest.TestCase):
    """B5 D56, D57, D62, D63 (owner 2): the station picks and the gust station run at the station point (the town point on a
    town page, the cell centre on the sheet); where a tile list answers, its picks are the full rule's picks at the same
    point (stations.point_rule); and the words name each station where the rows say it."""

    SHEET_CELLS = ((753, 2230), (792, 1998), (797, 1986))      # the named cells of D61 and D63
    ELEMENTS = ("PRCP", "SNOW", "SNWD", "TMAX", "TMIN")

    @classmethod
    def _points(cls):
        """(label, town or None, row, col): the 17 towns at their own cells (towns.json) and the three named cells."""
        out = []
        for town in json.loads(stations.TOWNS_FILE.read_text(encoding="utf-8")):
            row, col = hail.cell_for(town["lat"], town["lon"])
            out.append((f"town {town['slug']}", town, row, col))
        for row, col in cls.SHEET_CELLS:
            out.append((f"cell {row},{col}", None, row, col))
        return out

    def _compare(self, root, label, town, row, col):
        """For every element: the summary's picks (chosen) equal the full rule's picks at the same point, and where the tile
        list answers (chosen_from_tile_list), its picks and state equal the rule's too. Returns (comparisons, answered)."""
        index = hail.load_index(root)
        spot = S._Spot(root, index, row, col, town)
        lat, lon = spot.station_point
        light = spot.sb.get("stations") or {}
        as_of = date.fromisoformat(spot.sb["as_of"]) if spot.sb.get("as_of") else spot.as_of
        checked = answered = 0
        for element in self.ELEMENTS:
            rule = stations.point_rule(light, lat, lon, element, as_of)
            if rule["state"] == "need":                  # a candidate with no summary: the rule itself stops there
                continue
            want = [c["id"] for c in rule["chosen"]]
            _state, picks, _res = spot.chosen(element)
            self.assertEqual([c["id"] for c in picks], want, (label, element))
            got = spot.chosen_from_tile_list(element)
            if got is not None:
                answered += 1
                self.assertEqual([c["id"] for c in got[1]], want, (label, element, "tile list"))
                self.assertEqual(got[0], rule["state"], (label, element, "tile list state"))
            checked += 1
        return checked, answered

    def _write_tile_list(self, root: Path) -> None:
        """hail/tl/<tile>.json for the spot's tile, built as stations.py builds it (D61): every station of the block that
        passes the coverage and currency test for an element, within the radius plus a margin of the tile centre, no cap."""
        tile_row, tile_col = ROW // hail.TILE, COL // hail.TILE
        tile = hail.tile_name(tile_row, tile_col)
        clat, clon = stations.tile_centre(tile_row, tile_col)
        light = hail.load_index(root)["stations"]["stations"]
        elements = {}
        for element in self.ELEMENTS:
            passing = []
            for sid, meta in light.items():
                ok = meta["cover"].get(element, 0)
                miles = stations.haversine_miles(clat, clon, meta["lat"], meta["lon"])
                if meta["current"].get(element) and ok / stations.COVER_DAYS >= stations.COVER_MIN and miles <= 45.0:
                    passing.append({"id": sid, "name": meta["name"], "lat": meta["lat"], "lon": meta["lon"],
                                    "miles": round(miles, 1), "ok": ok, "of": stations.COVER_DAYS,
                                    "share": round(ok / stations.COVER_DAYS, 4)})
            elements[element] = {"centre": [clat, clon], "margin_miles": 5.0, "passing": passing, "unread": [],
                                 "rejected": [], "capped": False}
        write_json(root / "hail" / "tl" / f"{tile}.json", {"f": S.TILE_LIST_FORMAT, "tile": tile, "centre": [clat, clon],
                                                           "miles": stations.RADIUS_MILES, "margin_miles": 5.0,
                                                           "elements": elements})

    def test_the_summary_picks_are_the_rule_and_the_tile_list_is_the_one_rule(self):      # D63, parity on a synthetic store
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        self._write_tile_list(root)
        for label, town in (("sheet", None), ("town", dict(BILLINGS))):
            with self.subTest(label):
                checked, answered = self._compare(root, label, town, ROW, COL)
                self.assertEqual((checked, answered), (5, 5))
        # the summary delegates: its picks are stations.tile_list_picks' picks at the same point, field for field
        spot = S._Spot(root, hail.load_index(root), ROW, COL, dict(BILLINGS))
        doc = spot.tile_list()
        lat, lon = spot.station_point
        for element in self.ELEMENTS:
            block = doc["elements"][element]
            want = stations.tile_list_picks(block, lat, lon, light=spot.sb.get("stations") or {},
                                            radius_miles=S.TOWN_RADIUS)
            got = spot.chosen_from_tile_list(element)
            self.assertEqual(got[1], want["picks"], element)
            self.assertEqual(got[0], want["state"], element)

    def test_a_canadian_candidate_is_said_not_read_and_never_failed_or_passing(self):   # D62
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        tile_row, tile_col = ROW // hail.TILE, COL // hail.TILE
        clat, clon = stations.tile_centre(tile_row, tile_col)
        canada = {"id": "CA000000001", "name": "Milk River", "lat": 45.95, "lon": -108.5, "reason": stations.CANADA_REASON}
        block = {"centre": [clat, clon], "margin_miles": 5.0, "rejected": [], "capped": False}
        elements = {el: dict(block, passing=[], unread=[]) for el in self.ELEMENTS}
        elements["SNOW"] = dict(block, passing=[], unread=[canada])
        write_json(root / "hail" / "tl" / f"{hail.tile_name(tile_row, tile_col)}.json",
                   {"f": S.TILE_LIST_FORMAT, "tile": hail.tile_name(tile_row, tile_col), "centre": [clat, clon],
                    "miles": stations.RADIUS_MILES, "margin_miles": 5.0, "elements": elements})
        result = S.describe_summary(root, ROW, COL, None, town=dict(BILLINGS))
        snow = {r["key"]: r for r in result["table"]["rows"]}["snow"]
        text = " ".join(snow["notes"])
        self.assertIn("Milk River is not read (in Canada; the terms for its data are under review)", text)
        self.assertNotIn("could not be loaded", text)
        self.assertNotIn("No station within 40 miles", text)           # a candidate not read is not an absence

    def test_an_older_list_without_a_margin_cannot_answer_so_the_station_block_gives_the_picks(self):   # D61
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        self._write_tile_list(root)
        path = root / "hail" / "tl" / f"{hail.tile_name(ROW // hail.TILE, COL // hail.TILE)}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        del doc["margin_miles"]                              # a list from before the D61 rebuild
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        spot = S._Spot(root, hail.load_index(root), ROW, COL, dict(BILLINGS))
        self.assertIsNone(spot.chosen_from_tile_list("SNOW"))  # it may miss a station: it does not answer "none"
        state, chosen, res = spot.chosen("SNOW")
        self.assertEqual(state, "two")
        self.assertEqual(len(chosen), 2)
        self.assertNotEqual(res.get("source"), "tile list")

    def test_the_gust_station_is_the_nearest_candidate_to_the_spot_and_every_season_names_it(self):   # D56, D57
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        result = S.describe_summary(root, ROW, COL, None, town=dict(BILLINGS))
        rows = {r["key"]: r for r in result["table"]["rows"]}
        peak = rows["gust_max"]
        self.assertEqual(len(peak["texts"]), 5)
        for text, station in zip(peak["texts"], peak["stations"]):
            self.assertEqual(station, "Billings Logan", peak["texts"])
            self.assertIn(station, text)                  # D57: each strongest-gust season cell names its station
        self.assertIn("at Billings Logan, flagged for check", peak["texts"][3])

    def test_the_five_season_snowfall_names_its_one_station_and_the_roof_line_says_so(self):          # D57
        root, _ = build_store("one_station")                # one station covers all five seasons, so a total shows
        self.addCleanup(shutil.rmtree, root, True)
        result = S.describe_summary(root, ROW, COL, None)
        snow = {r["key"]: r for r in result["table"]["rows"]}["snow"]
        names = {n for n in snow["stations"] if n}
        self.assertEqual(len(names), 1)
        (station,) = names
        line = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}["snowfall_season"]
        self.assertIsNotNone(line["value"])
        self.assertTrue(line["text"].startswith("Station reading: "), line["text"])
        self.assertTrue(line["text"].endswith(f"in the five seasons at {station}."), (line["text"], station))

    def test_the_how_made_station_rule_names_montana_and_the_neighbouring_states(self):           # D62
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        text = " ".join(S.describe_summary(root, ROW, COL, None)["how_made"])
        self.assertIn("Station rule: the candidates are stations in Montana and the neighbouring states within 40 miles;", text)
        self.assertIn("Canadian stations within 40 miles are named as not read and never count as passing.", text)
        self.assertNotIn("the candidates within 40 miles;", text)

    def test_the_fixture_carries_the_station_part_and_its_picks_are_the_rule(self):                 # D64, D63
        root = Path(__file__).resolve().parents[1] / "website" / "data" / "hail-fixture"
        # the fixture's three tiles: Billings and the gate and Benchland cells (753,2230 lies in a tile the fixture does not hold)
        wanted = [p for p in self._points() if p[0] in ("town billings", "cell 792,1998", "cell 797,1986")]
        self.assertEqual(len(wanted), 3)
        for label, town, row, col in wanted:
            with self.subTest(label):
                spot = S._Spot(root, hail.load_index(root), row, col, town)
                self.assertIsNotNone(spot.tile_list(), f"{label}: the fixture has no station tile list for this tile")
                self._compare(root, label, town, row, col)

    def test_the_real_store_picks_are_the_rule_at_the_17_towns_and_the_named_cells(self):          # D61, D63
        store = os.environ.get("HAIL_PARITY_STORE")
        if not store:
            self.skipTest("set HAIL_PARITY_STORE to a built store (the combined store) to check every town and named cell")
        checked = answered = 0
        for label, town, row, col in self._points():
            with self.subTest(label):
                c, a = self._compare(Path(store), label, town, row, col)
                checked, answered = checked + c, answered + a
        self.assertGreater(checked, 0)

    def test_the_real_store_names_are_the_display_names_the_store_gives_and_its_radar_is_partial(self):   # D78(c), D82(c)
        """The adopted store's own names (hail/tl/r0079_c0199.json: "Buffalo 1.7 E", "Harlowton 11NW"; hail/tl/r0092_c0214.json:
        "Billings WTP") reach the summary as given, never re-cased; 2021-22 has 109 days missing (108 before the window opens
        on 17 Oct 2021, and one inside it), so its 1-inch count is Data unavailable and its largest estimate is over the days
        present (D82(c), D87(i))."""
        store = os.environ.get("HAIL_PARITY_STORE")
        if not store:
            self.skipTest("set HAIL_PARITY_STORE to the adopted combined store (the names and the partial radar season)")
        now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        benchland = {r["key"]: r for r in S.describe_summary(Path(store), 792, 1998, now)["table"]["rows"]}
        snow = " ".join(benchland["snow"]["texts"] + benchland["snow"]["notes"])
        self.assertIn("Harlowton 11NW", snow)
        self.assertIn("Buffalo 1.7 E", snow)
        self.assertNotIn("HARLOWTON", snow)
        self.assertNotIn("BUFFALO", snow)
        billings = {r["key"]: r for r in S.describe_summary(Path(store), 921, 2149, now)["table"]["rows"]}
        self.assertIn("Billings WTP", " ".join(billings["snow"]["texts"] + billings["snow"]["notes"]))
        self.assertIn("Billings Intl AP, 2.5 miles from this spot", " ".join(billings["snow"]["notes"]))   # the store's own name (D84(b))
        self.assertNotIn("INTL", " ".join(billings["snow"]["notes"]))
        # the four names the adopted store gives (D78(c), D84(b)): the display name as written, the GHCN name beside it, never re-cased
        with open(Path(store) / "hail" / "index.json", encoding="utf-8") as fh:
            named = json.load(fh)["stations"]["stations"]
        pairs = {st["name"]: st["ghcn_name"] for st in named.values() if st.get("name") in
                 ("Billings Intl AP", "Moccasin Exp Stn", "Lister", "Great Falls 16St")}
        self.assertEqual(pairs, {"Billings Intl AP": "BILLINGS INTL AP", "Moccasin Exp Stn": "MOCCASIN EXP STN",
                                 "Lister": "LISTER", "Great Falls 16St": "GREAT FALLS 16ST"})
        moccasin = " ".join(benchland["snow"]["notes"])
        self.assertIn("Moccasin Exp Stn, 3.", moccasin)                    # D80(b): the distance from the spot, the name as given
        self.assertNotIn("EXP STN", moccasin)
        one = billings["radar_1in"]
        self.assertTrue(one["texts"][0].startswith("Data unavailable for 2021-22"), one["texts"][0])
        self.assertEqual(one["coverage"][0], "109 days missing")
        self.assertIsNone(one["values"][0])
        self.assertTrue(billings["radar_max"]["texts"][0].startswith("Data unavailable for 2021-22"))   # no day of 0.25 in or more
        self.assertIsNotNone(billings["radar_max"]["five"])                 # the largest over the days present ...
        self.assertEqual(billings["radar_max"]["five_coverage"], "109 days missing")                    # ... with its coverage


class RoundTwoSiteTests(unittest.TestCase):
    """The round-2 site fixes (D69, D71, D76) on the synthetic store: a station the rule does not use is named with its reason
    (F6), a failed ice-dam count or roof says the D20 sentence (F1, F10), the five-season ice-dam count and the snowfall lead
    name their station (F3, F5), the season sentences name their season (F9), the words the browser asks for are in the
    summary block (F7), the sentences a town page's warnings use are the town point's (F4), and the unread-status words
    classify as the station module does (F13)."""

    TILE = "r0092_c0214"                            # the spot's tile (ROW // 10, COL // 10)
    TOWN_NOTE = "Stations: the two nearest that have enough days with the element, measured from this spot."     # D80(b)

    def _variant(self):
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def _write(self, root, passing, rejected=(), unread=()):
        """hail/tl/<tile>.json with the snowfall block: the tile centre and margin, the passing, the rejected and the unread."""
        clat, clon = 45.75, -108.55
        block = {"centre": [clat, clon], "margin_miles": 5.0, "passing": list(passing), "unread": list(unread),
                 "rejected": list(rejected), "capped": False}
        doc = {"f": S.TILE_LIST_FORMAT, "tile": self.TILE, "centre": [clat, clon], "miles": stations.RADIUS_MILES,
               "margin_miles": 5.0, "elements": {"SNOW": block}}
        write_json(root / "hail" / "tl" / f"{self.TILE}.json", doc)

    @staticmethod
    def _entry(sid, name, lat, lon, ok, current=True, newest=20260101):
        return {"id": sid, "name": name, "lat": lat, "lon": lon, "miles": 0.0, "ok": ok, "of": 2192,
                "share": round(ok / 2192, 4), "current": current, "newest": newest}

    def _passing(self):
        return [self._entry("USC00240802", "Billings WTP", 45.78, -108.52, 2000),
                self._entry("USW00024033", "Billings Intl AP", 45.8077, -108.5429, 2100)]

    @staticmethod
    def _miles_from_town(lat, lon):
        return f"{round(stations.haversine_miles(BILLINGS['lat'], BILLINGS['lon'], lat, lon), 1):.1f}"

    def _snow_notes(self, root):
        result = S.describe_summary(root, ROW, COL, None, town=dict(BILLINGS))
        return result, {r["key"]: r for r in result["table"]["rows"]}["snow"]["notes"]

    def test_a_station_the_rule_does_not_use_is_named_with_its_share_and_the_farther_ones_are_counted(self):    # D69, F6
        root = self._variant()
        moccasin = self._entry("USC00245761", "Moccasin Exp Stn", 45.79, -108.50, 324)     # 14.8 percent: under the rule
        far = self._entry("US1MTFAR0001", "Far Range 3 N", 45.95, -108.95, 900)            # 41 percent and farther
        self._write(root, self._passing(), rejected=[moccasin, far])
        result, notes = self._snow_notes(root)
        self.assertEqual([s["name"] for s in result["town"]["stations"]["snow"]], ["Billings WTP", "Billings Intl AP"])
        self.assertIn(f"Moccasin Exp Stn, {self._miles_from_town(45.79, -108.50)} miles from this spot, is not used: 14.8 "
                      "percent of the days 2020 to 2025 have a value for snowfall; the rule needs at least 80 percent.", notes)
        self.assertIn("1 more station within 40 miles does not pass the same rule; it is farther than the stations named here.",
                      notes)
        self.assertFalse(any("FAR RANGE" in n for n in notes), notes)     # counted, not named

    def test_a_station_that_is_not_current_is_named_with_the_date_of_its_newest_value(self):      # D69, F6
        root = self._variant()
        old = self._entry("US1MTOLD0001", "Old Canal 1 SW", 45.79, -108.50, 2100, current=False, newest=20240115)
        self._write(root, self._passing(), rejected=[old])
        _result, notes = self._snow_notes(root)
        self.assertIn(f"Old Canal 1 SW, {self._miles_from_town(45.79, -108.50)} miles from this spot, is not used: its newest "
                      "snowfall value is from Jan 15, 2024, and the rule needs one within 30 days of Oct 16, 2026.", notes)

    def test_a_town_page_says_from_this_spot_on_every_distance_and_never_from_the_town(self):             # D80(b), F5
        root = self._variant()
        moccasin = self._entry("USC00245761", "Moccasin Exp Stn", 45.79, -108.50, 324)
        self._write(root, self._passing(), rejected=[moccasin])
        _result, notes = self._snow_notes(root)
        self.assertTrue(any(n.startswith(self.TOWN_NOTE) for n in notes), notes[:1])
        self.assertTrue(any(n.startswith("Billings WTP, ") and n.endswith(" miles from this spot") for n in notes), notes)
        self.assertTrue(any(n.startswith("Moccasin Exp Stn, ") and " miles from this spot, is not used" in n for n in notes), notes)
        self.assertFalse(any("from the town" in n for n in notes), notes)

    def test_how_made_says_a_few_hundred_yards_apart_for_the_two_airport_positions(self):                   # D80(c), F4
        self.assertIn("A station's position comes from its source. Two sources can place one airport a few hundred yards apart, "
                      "so two rows may give slightly different distances to the same airport.", S._how_made())
        self.assertFalse(any("hundred feet" in line for line in S._how_made()))

    def test_a_share_under_the_rule_never_reads_as_the_rule_itself(self):                              # D5, F6
        self.assertEqual(S._share_text(0.14781), "14.8")
        self.assertEqual(S._share_text(0.79996), "79.9")
        self.assertEqual(S._share_text(0.8), "80.0")

    def test_a_failed_ice_dam_count_says_the_station_readings_did_not_load_and_names_no_station(self):   # F1, D16, D20
        root = self._variant()
        with mock.patch.object(S, "_dl_cells", side_effect=KeyError("boom")):
            result = S.describe_summary(root, ROW, COL, None, town=dict(BILLINGS))
        lines = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}
        text = lines["ice_dam_weather_days"]["text"]
        self.assertIn("Station readings could not be loaded in this update; that is not the same as no station readings. "
                      "This is not an all-clear.", text)
        self.assertNotIn("No station within 40 miles", text)
        self.assertIsNone(lines["ice_dam_weather_days"]["value"])
        self.assertEqual(result["state"], "partial")
        self.assertIn("ice dam days", result["problem"])

    def _dl_cells(self, names, values):
        return [S._cell(value=n, text=f"{n} days at {name}", valid=365, missing=0, station=name, miles=1.0, sid="X")
                for name, n in zip(names, values)]

    def test_the_ice_dam_five_season_count_names_one_station_that_gives_every_season(self):          # F5, D41
        root = self._variant()
        cells = self._dl_cells(["Billings WTP"] * 5, [55, 68, 22, 56, 21])
        with mock.patch.object(S, "_dl_cells", return_value=cells):
            result = S.describe_summary(root, ROW, COL, None, town=dict(BILLINGS))
        line = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}["ice_dam_weather_days"]
        self.assertEqual(line["value"], 222)
        self.assertEqual(line["text"], "Station reading: 222 days with 1 inch or more of snow on the ground and a low below 32 F "
                         "in these five seasons at Billings WTP: a measured pattern, not a count of ice dams.")

    def test_the_ice_dam_five_season_count_is_unavailable_when_more_than_one_station_gives_the_seasons(self):   # F5, D41
        root = self._variant()
        cells = self._dl_cells(["Billings WTP"] * 4 + ["Billings Logan"], [55, 68, 22, 56, 21])
        with mock.patch.object(S, "_dl_cells", return_value=cells):
            result = S.describe_summary(root, ROW, COL, None, town=dict(BILLINGS))
        line = {x["id"]: x for g in result["roof"]["groups"] for x in g["lines"]}["ice_dam_weather_days"]
        self.assertIsNone(line["value"])
        self.assertEqual(line["text"], "Station reading: Days with 1 inch or more on the ground and a low below 32 F (days; a "
                         "measured pattern, not ice dams). Data unavailable for the five seasons: the seasons come from more "
                         "than one station (Billings WTP 2021-22 to 2024-25, Billings Logan 2025-26), so no five-season count is "
                         "shown. This is not an all-clear.")
        self.assertEqual(cells[0]["text"], "55 days at Billings WTP")                         # each season names its station

    def test_a_failed_roof_section_says_the_roof_lines_did_not_load(self):                            # F10, D16, D20
        root = self._variant()
        with mock.patch.object(S, "_roof", side_effect=KeyError("boom")):
            result = S.describe_summary(root, ROW, COL, None, town=dict(BILLINGS))
        sentence = ("The roof lines could not be loaded in this update; that is not the same as no roof lines. "
                    "This is not an all-clear.")
        self.assertEqual(result["roof"]["groups"], [])
        self.assertEqual(result["roof"]["unavailable"], sentence)
        self.assertEqual([s["lead"] for s in result["sections"] if s["id"] == "roof"], [sentence])
        self.assertEqual(result["state"], "partial")

    def test_the_snowfall_lead_names_the_station_of_its_total_and_says_was_before_the_depth(self):      # F3, F15, D57
        rows = {"snow": {"five": 19190, "five_text": "191.9 in at Harlowton 11NW", "five_missing": 0,
                         "stations": ["Harlowton 11NW"] * 5},
                "snow_depth": {"five": 6500, "five_text": "65.0 in on Jan 24, 2025 at Crystal Lake", "five_missing": 0,
                               "stations": ["Crystal Lake"] * 5}}
        sections = S._sections(rows, {}, {}, None, None, None, None)
        lead = [s["lead"] for s in sections if s["id"] == "snow"][0]
        self.assertEqual(lead, "Station reading: 191.9 in of snowfall in the five seasons at Harlowton 11NW; the deepest snow on "
                         "the ground was 65.0 in on Jan 24, 2025 at Crystal Lake.")
        rows["snow"]["stations"] = ["Harlowton 11NW"] * 2 + ["Lewistown 11 SSE"] * 3
        rows["snow"]["five"] = None
        lead = [s["lead"] for s in S._sections(rows, {}, {}, None, None, None, None) if s["id"] == "snow"][0]
        self.assertIn("the deepest snow on the ground was 65.0 in on Jan 24, 2025 at Crystal Lake. This is not an all-clear.", lead)

    def test_every_season_unavailable_sentence_names_its_season(self):                                # F9, D32
        short = S.WORDS_SUMMARY["station_short"].format(season="2021-22", station="Billings WTP", k=300, d=365,
                                                        element="snowfall")
        self.assertEqual(short, "Data unavailable for 2021-22: Billings WTP has 300 of 365 days with a snowfall value, so this "
                         "season is not shown; a missing value is not zero. This is not an all-clear.")
        gust = S.WORDS_SUMMARY["gust_season_short"].format(season="2023-24", station="Billings Logan", k=146, d=365)
        self.assertTrue(gust.startswith("Data unavailable for 2023-24: Billings Logan has 146 of 365 days with a gust value"), gust)

    def test_a_town_page_explains_its_warnings_at_the_town_point_and_the_sheet_at_the_cell(self):   # F4, D38, D71
        from website import build
        self.assertIn("covered this spot", S.WORDS_INDICATORS["what_warnings_town"])
        self.assertNotIn("covered this cell", S.WORDS_INDICATORS["what_warnings_town"])
        self.assertIn("covered this cell or part of it", S.WORDS_INDICATORS["what_warnings"])
        self.assertNotIn("covered this spot", S.WORDS_INDICATORS["what_warnings"])
        self.assertEqual(build.kind_what(town=True)["Warning"], S.WORDS_INDICATORS["what_warnings_town"])
        self.assertEqual(build.kind_what()["Warning"], S.WORDS_INDICATORS["what_warnings"])

    def test_every_word_the_browser_asks_the_summary_for_is_in_the_summary_block(self):               # F7, D71, D72
        src = (Path(__file__).resolve().parents[1] / "website" / "static" / "map" / "map.js").read_text(encoding="utf-8")
        asked = set()
        for call in re.finditer(r'sumWord\(S, ([^)\n]*)\)', src):   # the key: a literal, or a ternary of two literals
            asked |= set(re.findall(r'"([a-zA-Z_0-9]+)"', call.group(1)))
        block = S.map_data_summary(None)
        self.assertEqual(sorted(k for k in asked if k not in block["words"]), [])
        for key in ("nouns", "report_types", "record_types", "auto_sources", "element_names", "family_nouns"):
            self.assertIn(key, block)
        for key in set(re.findall(r'own\(h\.summary, "([a-zA-Z_]+)"\)', src)):
            self.assertIn(key, block)
        self.assertEqual(block["report_types"]["hail_n"], "hail")
        self.assertEqual(block["element_names"]["SNOW"], "snowfall")
        self.assertEqual(block["family_nouns"]["flash_flood_watch"], "flash flood watch")

    def test_the_browser_station_conversions_are_the_station_module_conversions(self):                  # D36, F7
        conv = S.map_data_summary(None)["conv"]
        for mm in (0, 1, 25, 254, 1000, 12345):
            self.assertEqual((mm * conv["mm_scale"] + 127) // 254, stations.mm_to_hundredths_in(mm), mm)
        c = conv["c_to_f"]
        for c10 in (-400, -1, 0, 322, 400):
            self.assertEqual((c["mul"] * c10 + c["offset"] + c["round"]) // c["div"], stations.tenths_c_to_tenths_f(c10), c10)

    def test_the_unread_status_words_follow_the_station_module_classification(self):                  # F13, D32, D62
        cases = (([{"reason": "the file did not load"}], "did not load", "station_status_failed"),
                 ([{"reason": stations.CANADA_REASON}], "is not read", "station_status_not_read"),
                 ([{"reason": stations.CANADA_REASON}] * 2, "are not read", "station_status_not_read_many"),
                 ([{"reason": "the file did not load"}, {"reason": stations.CANADA_REASON}], "could not be read",
                  "station_status_both"))
        for unread, module_words, summary_key in cases:
            self.assertEqual(stations._unread_status(unread), module_words)
            self.assertEqual(S._unread_status(unread), S.WORDS_SUMMARY[summary_key])
        self.assertEqual(S.TILE_LIST_FORMAT, stations.TILE_LIST_FORMAT)
        self.assertEqual(S.TOWNS_FORMAT, joins.TOWNS_FORMAT)


class TownPartialSeasonTests(unittest.TestCase):
    """The town page's storm and flood counts name the five seasons and the partial season (2026-27 so far) apart (D79(b)),
    while the sheet's leads keep their own wording; the partial count is the count of the partial season's own days."""

    def _variant(self):
        root, _ = build_store("full")
        self.addCleanup(shutil.rmtree, root, True)
        return root

    @staticmethod
    def _section(result, sid):
        return next(sec for sec in result["sections"] if sec["id"] == sid)

    def test_the_town_storms_and_flooding_leads_name_the_five_seasons_and_the_partial_season_apart(self):   # D79(b)
        root = self._variant()
        town = S.describe_summary(root, ROW, COL, None, town=BILLINGS)
        storms = self._section(town, "storms")["lead"]
        flooding = self._section(town, "flooding")["lead"]
        for lead in (storms, flooding):
            self.assertIn("in the five seasons", lead)
            self.assertRegex(lead, r"(\d+ more|no more) in 2026-27 so far")
        self.assertRegex(storms, r"Warning: .* covered this (spot|cell or part of it) in the five seasons; ")   # D38: the file decides
        self.assertRegex(flooding, r"Report: \d+ flood or flash flood reports within 5 miles in the five seasons; ")

    def test_the_sheet_leads_keep_the_five_years_wording(self):                                                # D79(b)
        root = self._variant()
        sheet = S.describe_summary(root, ROW, COL, None)
        storms = self._section(sheet, "storms")["lead"]
        flooding = self._section(sheet, "flooding")["lead"]
        self.assertIn("in these five years", flooding)
        self.assertNotIn("2026-27", storms + flooding)
        self.assertNotIn("in the five seasons", storms + flooding)

    def test_the_town_roof_storm_and_flood_lines_name_the_partial_season_too(self):                            # D79(b)
        root = self._variant()
        roof = {line["id"]: line for group in S.describe_summary(root, ROW, COL, None, town=BILLINGS)["roof"]["groups"]
                for line in group["lines"]}
        self.assertRegex(roof["hail_warnings"]["text"],
                         r"^Warning: .* in the five seasons; (\d+ more|no more) in 2026-27 so far\. This is not an all-clear\.$")
        self.assertIn("in 2026-27 so far", roof["flood_reports_warnings"]["text"])
        self.assertTrue(roof["flood_reports_warnings"]["text"].endswith(" This is not an all-clear."))     # D87(b)

    def test_the_partial_clause_says_no_day_when_the_store_has_none_of_the_season(self):                       # D20, D79(b)
        text = S._town_five("3 warnings in the five seasons", {"n": 0, "valid": 0, "missing": 0})
        self.assertEqual(text, "3 warnings in the five seasons. No day of the 2026-27 season is in the data yet. "
                               "This is not an all-clear.")
        self.assertEqual(S._town_five("3 warnings in the five seasons", {"n": 2, "valid": 90, "missing": 0}),
                         "3 warnings in the five seasons; 2 more in 2026-27 so far. This is not an all-clear.")      # D87(b)
        self.assertEqual(S._town_five("3 warnings in the five seasons", {"n": 0, "valid": 90, "missing": 4}),
                         "3 warnings in the five seasons; no more in 2026-27 so far; 4 days missing in 2026-27. "
                         "This is not an all-clear.")

    def test_a_partial_season_with_no_valid_day_keeps_its_count_and_its_missing_days(self):                  # F6, D82
        self.assertEqual(S._town_five("3 warnings in the five seasons", {"n": 1, "valid": 0, "missing": 2}),
                         "3 warnings in the five seasons; 1 more in 2026-27 so far; 2 days missing in 2026-27. "
                         "No day of the 2026-27 season is in the data yet. This is not an all-clear.")
        self.assertEqual(S._town_five("3 warnings in the five seasons", {"n": 0, "valid": 0, "missing": 2}),
                         "3 warnings in the five seasons; 2 days missing in 2026-27. "
                         "No day of the 2026-27 season is in the data yet. This is not an all-clear.")
        self.assertNotIn("no more", S._town_five("3 warnings in the five seasons", {"n": 0, "valid": 0, "missing": 2}))  # no zero

    def test_a_zero_report_count_reads_as_its_no_report_sentence_without_the_full_stop(self):                # D41, D79(b)
        self.assertEqual(S._town_five_text("flood_report_n", 0, "within 5 miles"),
                         "No NWS local storm report of flood or flash flood within 5 miles in the five seasons; reports are not "
                         "a complete record")

    def test_the_candidate_store_gives_the_billings_partial_counts_it_holds(self):                            # D79(b), parity
        store = os.environ.get("HAIL_PARITY_STORE")
        if not store:
            self.skipTest("set HAIL_PARITY_STORE to a built store (the combined store) to read Billings' partial counts")
        town = S.describe_summary(Path(store), ROW, COL, None, town=BILLINGS)
        storms = self._section(town, "storms")["lead"]
        self.assertIn("Warning: 19 severe thunderstorm warnings covered this spot in the five seasons; 2 more in 2026-27 so far.",
                      storms)
        self.assertIn("Zone product: 23 high wind watches and warnings in the five seasons; no more in 2026-27 so far.", storms)
        self.assertIn("Report: 6 flood or flash flood reports within 5 miles in the five seasons; 1 more in 2026-27 so far.",
                      self._section(town, "flooding")["lead"])


class CountWordsTests(unittest.TestCase):
    """The count and coverage words put a thousands separator in every number of a thousand or more, as the section leads do
    (F8): "1,020 days", "1,826 days missing", "2,192 days at Billings WTP"; a number under a thousand reads as it did."""

    def test_counts_and_coverage_lines_use_the_thousands_separator(self):                                  # F8
        self.assertEqual(S._count_text("days", 1020), "1,020 days")
        self.assertEqual(S._count_text("days", 1073), "1,073 days")
        self.assertEqual(S._count_text("days", 108), "108 days")
        self.assertEqual(S._count_text("days", 1), "1 day")
        self.assertEqual(S._count_text("hail_n", 1500), "1,500 hail reports")
        self.assertEqual(S._missing_text(1826), "1,826 days missing")
        self.assertEqual(S._missing_text(108), "108 days missing")
        self.assertEqual(S._missing_text(1), "1 day missing")

    def test_a_station_day_count_uses_it_too(self):                                                       # F8
        self.assertEqual(S._days_at(2192, "Billings WTP"), "2,192 days at Billings WTP")
        self.assertEqual(S._days_at(1, "Billings WTP"), "1 day at Billings WTP")


class RadarCoverageTests(unittest.TestCase):
    """The radar rows at a partial season (D37, D82(c)): a zero, and the "No radar estimate" sentence, show only at 95 percent
    coverage; a season below that with no figure says Data unavailable and names its days; a five-season figure a short season
    leaves without a value is Data unavailable, and names the season."""

    class Spot:
        """The four things the radar rows read from a spot: the window, its missing days, the season cover and its days."""

        def __init__(self, cover: dict):
            self.first, self.last, self.as_of = date(2021, 10, 17), date(2026, 10, 16), date(2026, 10, 16)
            self.missing = set()
            self.cover = cover
            self.gust = None

        def in_window(self, day: date) -> bool:
            return self.first <= day <= self.last

        def season_cover(self, label: str, missing_days=None) -> tuple[int, int, int]:
            return self.cover[label]

    FULL = {label: (365, 365, 365) for label in S.FIVE}

    def rows(self, cover: dict, days=()):
        return S._radar_rows(self.Spot(cover), list(days))

    def test_a_complete_season_with_no_day_at_one_inch_shows_a_zero(self):                                      # D37
        big, one = self.rows(self.FULL)
        self.assertEqual(one["values"], [0, 0, 0, 0, 0])
        self.assertEqual(one["texts"][0], "0 days")
        self.assertEqual(one["five"], 0)
        self.assertEqual(big["texts"][0], S.WORDS_SUMMARY["none_radar"])                                       # complete: the sentence
        self.assertEqual(big["five_text"], S.WORDS_SUMMARY["none_radar"])

    def test_a_season_below_ninety_five_percent_with_no_day_is_data_unavailable_with_its_days_missing(self):   # D82(c)
        cover = dict(self.FULL, **{"2021-22": (365, 256, 256)})
        big, one = self.rows(cover)
        self.assertIsNone(one["values"][0])
        self.assertTrue(one["texts"][0].startswith("Data unavailable for 2021-22: the radar record has 256 of 365 days"),
                        one["texts"][0])
        self.assertEqual(one["coverage"][0], "109 days missing")
        self.assertIsNone(big["values"][0])
        self.assertTrue(big["texts"][0].startswith("Data unavailable for 2021-22"), big["texts"][0])
        self.assertNotIn(S.WORDS_SUMMARY["none_radar"], big["texts"][0])                                       # never the sentence
        self.assertEqual(big["coverage"][0], "109 days missing")

    def test_exactly_ninety_five_percent_still_shows_the_zero(self):                                            # D37, the boundary
        cover = dict(self.FULL, **{"2021-22": (100, 95, 95)})
        _big, one = self.rows(cover)
        self.assertEqual(one["values"][0], 0)
        self.assertEqual(one["texts"][0], "0 days")

    def test_a_positive_count_below_ninety_five_percent_is_shown_with_its_coverage(self):                      # D33, D82(c)
        cover = dict(self.FULL, **{"2021-22": (365, 256, 256)})
        _big, one = self.rows(cover, [(date(2021, 11, 2), 254)])                                               # 1.00 in
        self.assertEqual(one["values"][0], 1)
        self.assertEqual(one["texts"][0], "1 day")
        self.assertEqual(one["coverage"][0], "109 days missing")

    def test_the_largest_estimate_is_the_largest_over_the_days_present_with_its_coverage(self):                  # D82(c)
        cover = dict(self.FULL, **{"2021-22": (365, 256, 256)})
        big, _one = self.rows(cover, [(date(2021, 11, 2), 100)])                                               # 0.39 in
        self.assertEqual(big["values"][0], 39)
        self.assertEqual(big["texts"][0], "0.39 in on Nov 2, 2021")
        self.assertEqual(big["coverage"][0], "109 days missing")

    def test_a_five_season_count_with_a_short_season_is_data_unavailable_and_names_the_season(self):           # D41, D82(c)
        cover = dict(self.FULL, **{"2021-22": (365, 256, 256)})
        big, one = self.rows(cover)
        self.assertIsNone(one["five"])
        self.assertIn("Data unavailable for the five seasons: 2021-22 has no usable value", one["five_note"])
        self.assertIsNone(big["five"])
        self.assertIn("2021-22 has no usable value", big["five_note"])

    def test_the_five_season_largest_names_no_none_sentence_when_a_short_season_has_no_value(self):              # D82(c)
        cover = dict(self.FULL, **{"2021-22": (365, 0, 0)})
        big, _one = self.rows(cover)
        self.assertEqual(big["five_text"], S.WORDS_SUMMARY["cell_unavailable"])
        self.assertIn("2021-22", big["five_note"])


class SectionDataTests(unittest.TestCase):
    """summary.section_data (D83): the words, rules and tables the browser reads, written from the constants the Python
    sections use. The browser's rule for a joined row is replayed here from the data and must equal build._section_of."""

    @classmethod
    def setUpClass(cls):
        cls.sd = S.map_data_summary({"window": ["2020-01-01", "2026-10-16"]})["section_data"]

    def test_the_rules_replayed_from_the_data_cut_each_row_as_the_build_does(self):                         # D41, D82(d)
        from website import build as bd
        rules = self.sd["rules"]

        def sheet_section_of(label: str, body: str) -> str:
            if label in rules["by_label"]:
                return rules["by_label"][label]
            if label in rules["product_labels"]:
                m = re.search(rules["product_patterns"][0], body) or re.search(rules["product_patterns"][1], body)
                words = m.group(1) if m else body
            elif label in rules["zone_labels"]:
                words = re.split(rules["zone_split"], body)[0]
            else:
                t = re.search(rules["time_pattern"], body, re.I)
                words = re.split(rules["split"], t.group(1) if t else body)[0]
            for sid, pattern in rules["rules"]:
                if re.search(pattern, words, re.I):
                    return sid
            return rules["default"]

        cases = [("Station", "5:16 pm MDT: tstm wnd gst, 40 kt at Billings WTP"), ("Detection", "Jul 2, 2025: 1 hail signature"),
                 ("Warning", "Severe Thunderstorm Warning in effect: hail, 0.75 in, covered this cell or part of it; tags: hail"),
                 ("Warning", "Flood Advisory, FA.Y, covered this cell or part of it"),
                 ("Watch", "Flood Watch in effect: flash flood, covered this cell"),
                 ("Advisory", "Winter Weather Advisory in effect: freezing rain, covered this cell"),
                 ("Zone product", "High Wind Warning, fire weather zone 22: gusts 60 mph"),
                 ("County product", "Flood Watch, FA.A, Yellowstone County: flash flood"),
                 ("Report", "5:16 pm MDT: hail, 1.00 in, Billings (Lewistown)"),
                 ("Report", "3:02 pm MST: heat, 110 F"),
                 ("Record", "Jul 4, 2025: flash flood, NCEI cause heavy rain"),
                 ("Report", "9:00 am MDT: freezing rain, 0.10 in"),
                 ("Report", "10:30 am MDT: tornado, funnel cloud"),
                 ("Report", "no time here, only a debris flow"),
                 ("", "Unlabelled row about snow")]
        for label, body in cases:
            with self.subTest(label=label, body=body):
                self.assertEqual(sheet_section_of(label, body), bd._section_of(label, body))

    def test_the_part_sections_send_every_joined_part_to_a_section_of_the_sheet(self):                        # D82(d)
        sections = set(S.WORDS_SUMMARY["section_titles"])
        self.assertEqual(sorted(self.sd["part_sections"]), ["county", "detections", "fire", "records", "stations", "warnings", "zones"])
        self.assertTrue(set(self.sd["part_sections"].values()) <= sections)
        self.assertEqual(self.sd["part_sections"]["county"], "flooding")
        self.assertEqual(self.sd["part_sections"]["detections"], "hail")

    def test_the_roof_line_nouns_and_extra_codes_are_the_codes_the_counts_read(self):                         # D40, D41
        lines = self.sd["roof"]["lines"]
        self.assertEqual(sorted(lines), sorted(S.ROOF_LINES))
        for key, line in lines.items():
            self.assertTrue(line["noun"] is None or line["noun"] in S.NOUNS or line["noun"] == "days", key)
        extra = self.sd["roof"]["extra"]
        self.assertEqual(extra["hail_warnings"]["polygon"], list(S.CODES["polygon"]["sv"]))
        self.assertEqual(extra["tornado_warnings"]["polygon"], list(S.CODES["polygon"]["to"]))
        self.assertEqual(extra["ice_storm"]["zone"], list(S.CODES["zone"]["is"]))
        self.assertEqual(extra["ice_storm"]["family"], "winter_storm")
        self.assertIsNone(extra["excessive_heat"]["family"])
        self.assertEqual(extra["extreme_heat"]["reports"], [S.CODES["extreme_heat_kind"]])

    def test_the_section_data_is_plain_json_and_the_percent_rule_is_written(self):                            # D82(c)
        text = json.dumps(S.map_data_summary({"window": ["2020-01-01", "2026-10-16"]}))
        data = json.loads(text)
        self.assertEqual(data["rule"]["percent"], {"scale": 100, "decimals": 1, "step": 0.1})
        self.assertEqual(data["nouns"]["days"], ["day", "days"])
        self.assertEqual(data["units"]["in"]["station_decimals"], 1)
        self.assertEqual(data["section_data"]["partial_marker"], "not counting")

    def test_the_station_inches_have_the_one_decimal_the_station_module_writes(self):                         # D57
        self.assertEqual(S.UNIT_SPEC["in"]["station_decimals"], S.STATION_IN_DECIMALS)
        self.assertEqual(stations.fmt_in(5029), "50.3")
        self.assertEqual(len(stations.fmt_in(5029).split(".")[1]), S.STATION_IN_DECIMALS)

    def test_the_held_reason_ends_with_the_all_clear_sentence(self):                                          # D41, G14
        self.assertTrue(S.UNIT_SPEC["reason"]["word"].endswith(S.ALL_CLEAR))

    def test_an_unavailable_grid_names_each_rows_own_part_rain_or_temperature(self):                         # D41, D82(d)
        rows = S._climate_unavailable_rows()
        self.assertIn("Temperature could not be loaded in this update", rows["tmax"]["notes"][0])
        self.assertIn("Rain could not be loaded in this update", rows["precip"]["notes"][0])
        self.assertIn("Rain could not be loaded in this update", rows["precip_max"]["notes"][0])
        self.assertTrue(rows["precip"]["notes"][0].endswith(S.ALL_CLEAR))
        self.assertEqual(S.WORDS_SUMMARY["rain_part"], "Rain")
        self.assertEqual(S.WORDS_SUMMARY["rain_part_lower"], "rain")

    def test_the_reference_line_and_county_word_are_the_words_the_page_uses(self):                            # D74, D41
        self.assertEqual(self.sd["roof"]["reference_line"], S.REFERENCE_LINE)
        self.assertEqual(S.REFERENCE_LINE.format(source="S", quote="Q"), "S: \u201cQ\u201d")
        self.assertEqual(self.sd["words"]["county_word"], "County")


class SeasonRuleTests(unittest.TestCase):
    """summary.rule.season (D87(d)): the July 1 to June 30 bounds are written once, into map.json, and the browser reads them.
    The block equals summary.SEASON_RULE; season_bounds follows it; stations.season_of gives the same label on every day of
    the window and on both sides of each boundary (the season's first and last day)."""

    def test_the_season_block_is_written_and_equals_the_module_rule(self):                                  # D87(d)
        block = S.map_data_summary({"window": ["2020-01-01", "2026-10-16"]})["rule"]["season"]
        self.assertEqual(block, S.SEASON_RULE)
        self.assertEqual(block, {"start_month": 7, "start_day": 1, "end_month": 6, "end_day": 30})
        self.assertEqual(S.season_bounds("2021-22"), (date(2021, 7, 1), date(2022, 6, 30)))
        self.assertEqual(S.season_bounds("2026-27"), (date(2026, 7, 1), date(2027, 6, 30)))

    def test_the_bounds_agree_with_stations_season_of_on_every_day(self):                                  # D87(d), D83(b)
        labels = list(S.FIVE) + [S.PARTIAL]
        day = date(2021, 7, 1)
        for label in labels:
            first, last = S.season_bounds(label)
            self.assertEqual(first, day, label)                   # the seasons are consecutive: each starts the day after
            while day <= last:
                self.assertEqual(stations.season_of(day), label, day.isoformat())
                day += timedelta(days=1)
        self.assertEqual(stations.season_of(date(2021, 6, 30)), None)      # before the first season (no label)
        self.assertEqual(stations.season_of(date(2026, 7, 1)), "2026-27")
        self.assertEqual(stations.season_of(date(2026, 6, 30)), "2025-26")

    def test_the_words_test_names_the_block(self):                                                        # D87(d)
        self.assertIn("season: start_month 7, start_day 1, end_month 6, end_day 30", S.__doc__)


class SheetRowsTests(unittest.TestCase):
    """The sheet's rows and notes come from one function (summary.describe_sheet, D88(p), S-4) in the fixed section order
    (D87(g), D88(i)); the partial and unavailable lines keep their kind words and their all-clear sentence (D41, D87(a),
    D87(b), D88(b), D88(s))."""

    NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

    def test_the_section_order_is_the_keys_in_the_brief_order(self):                                    # D87(g), D88(i)
        self.assertEqual(S.SECTION_ORDER, tuple(S.SECTION_KEYS))
        self.assertEqual(S.SECTION_ORDER, ("hail", "wind", "storms", "temperature", "rain", "snow", "flooding", "ice",
                                           "heat", "roof", "made"))

    def test_describe_sheet_gives_the_rows_and_notes_of_the_eleven_sections(self):                      # D88(p), S-4
        root, _ = build_store("full")
        try:
            sheet = S.describe_sheet(root, ROW, COL, self.NOW)
            self.assertEqual(sorted(sheet), ["built", "joined", "radar", "section_order", "summary"])
            self.assertEqual(sheet["section_order"], list(S.SECTION_ORDER))
            self.assertEqual(list(sheet["built"]["rows"]), list(S.SECTION_ORDER))
            self.assertEqual(list(sheet["built"]["notes"]), list(S.SECTION_ORDER))
            self.assertTrue(sheet["built"]["rows"]["temperature"], "the grid rows of the five seasons are in the sheet")
            for sid, rows in sheet["built"]["rows"].items():
                for row in rows:
                    with self.subTest(section=sid):
                        self.assertIn("label", row)
                        self.assertIsInstance(row["text"], str)
            self.assertEqual(sheet["built"]["notes"]["made"][-1], S.TIMES_NOTE)              # How this was made ends with the times
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_partial_count_sentence_ends_with_the_words_all_clear(self):                             # D41, D87(b), D88(s)
        tail = S.SECTION_WORDS["all_clear"]
        self.assertEqual(tail, S.ALL_CLEAR)
        self.assertEqual(S.map_data_summary(None)["section_data"]["words"]["all_clear"], tail)
        text = S._town_five("19 severe thunderstorm warnings covered this spot in the five seasons",
                            {"n": 2, "valid": 300, "missing": 0})
        self.assertEqual(text, "19 severe thunderstorm warnings covered this spot in the five seasons; 2 more in 2026-27 "
                               "so far. This is not an all-clear.")
        self.assertEqual(text.count(tail), 1)

    def test_a_roof_label_keeps_its_unit_word_and_no_kind_word(self):                                  # D87(a), D88(b)
        kinds = {kind for _label, kind, _unit in S.ROOF_LINES.values()} | set(S.SECTION_KINDS.values()) | {S.KIND_UNAVAILABLE}
        for ind, (label, kind, unit) in S.ROOF_LINES.items():
            with self.subTest(line=ind):
                self.assertIn(kind, kinds, ind)
                for inside in re.findall(r"\(([^)]*)\)", label):
                    for word in kinds:
                        self.assertNotIn(word.lower(), inside.lower(), label)


if __name__ == "__main__":
    unittest.main()
