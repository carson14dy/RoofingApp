#!/usr/bin/env python3
"""Predeclared evaluation harness (evaluation/PREREGISTRATION.md). Standard library only.

    python3 evaluation/harness.py <decisions.jsonl> <outcomes.csv> [--towns FILE]
        [--split event|season|none] [--fraction 0.5] [--seed 20261016] [--min-days 30]
        [--resamples 2000]

decisions.jsonl: one JSON object per line with as_of, decision_time (both ISO 8601 with a zone),
arm (A, B or C), town (a slug from the town list), reporting_day (YYYY-MM-DD) and decision, an object
whose "warned" is true or false. Other keys in decision are kept by the writer and ignored here.

outcomes.csv: SPC filtered storm reports with two extra leading columns, day (YYYY-MM-DD) and kind
(hail or wind). The rest are SPC's columns: Time, Size or Speed, Location, County, State, Lat, Lon,
Comments.

Prints a markdown table with one row per arm. Outcomes are a proxy, not ground truth. Arms are never
pooled. Nothing here ranks a provider or model (D21).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
ARMS = ("A", "B", "C")
METRICS = ("miss_rate", "fa_ratio", "lead_h")
REQUIRED = ("as_of", "decision_time", "arm", "town", "reporting_day", "decision")
INSUFFICIENT = "insufficient data"
DEFAULT_TOWNS = Path(__file__).resolve().parent.parent / "website" / "towns.json"
# Predeclared thresholds (PREREGISTRATION sections 6 and 9). PROPOSED until Carson signs off.
HAIL_MIN_HUNDREDTHS = 100          # 1.00 in; SPC sizes are hundredths of an inch
WIND_MIN_MPH = 58
RADIUS_MI = 25.0
MIN_DAYS = 30
RESAMPLES = 2000
FRACTION = 0.5
SEED = 20261016
# The Montana box and margin of website/sources.py (parse_spc keeps reports near Montana only).
MT_BOX = (44.35, 49.01, -116.06, -104.03)
MARGIN = 0.75
SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
          6: "summer", 7: "summer", 8: "summer", 9: "fall", 10: "fall", 11: "fall"}


# ---------------------------------------------------------------- time and distance

def parse_utc(text, what: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None or dt.tzinfo is None:
        raise ValueError(f"{what} must be an ISO 8601 time with a zone, not {text!r}")
    return dt.astimezone(UTC)


def spc_time(day: date, hhmm: str) -> datetime:
    """HHMM UTC on an SPC reporting day (12:00 to 11:59 UTC), as website/sources.py does. A blank
    time is refused here; parse_spc would read it as 00:00 UTC."""
    s = str(hhmm).strip().zfill(4)
    if not str(hhmm).strip() or not (s.isdigit() and len(s) == 4 and int(s[:2]) <= 23 and int(s[2:]) <= 59):
        raise ValueError(f"bad SPC time {hhmm!r}")
    t = datetime(day.year, day.month, day.day, int(s[:2]), int(s[2:]), tzinfo=UTC)
    return t + timedelta(days=1) if t.hour < 12 else t


def near_montana(lat: float, lon: float) -> bool:
    return (MT_BOX[0] - MARGIN <= lat <= MT_BOX[1] + MARGIN
            and MT_BOX[2] - MARGIN <= lon <= MT_BOX[3] + MARGIN)


def miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(min(1.0, a)))


# ---------------------------------------------------------------- outcomes (SPC storm reports)

def load_outcomes(path) -> tuple[list[dict], int]:
    """SPC rows in and near Montana, with a qualifies flag, after duplicates are dropped the way
    website/sources.py parse_spc drops them. Returns the reports and how many rows were skipped
    for a bad time or position; skipped rows are reported, never silently scored as no report."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "day" not in reader.fieldnames or "kind" not in reader.fieldnames:
            raise ValueError("the outcomes CSV needs the columns day and kind, then SPC's columns")
        rows = list(reader)
    reports, skipped, seen = [], 0, set()
    for n, row in enumerate(rows, start=2):
        try:
            day = date.fromisoformat((row.get("day") or "").strip())
        except ValueError:
            raise ValueError(f"outcomes line {n}: day must be YYYY-MM-DD") from None
        kind = (row.get("kind") or "").strip()
        if kind not in ("hail", "wind"):
            raise ValueError(f"outcomes line {n}: kind must be hail or wind")
        try:
            lat, lon = float(row.get("Lat") or ""), float(row.get("Lon") or "")
            when = spc_time(day, row.get("Time") or "")
        except ValueError:
            skipped += 1
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)) or not near_montana(lat, lon):
            continue
        if kind == "hail":
            raw = (row.get("Size") or "").strip()
            hundredths = int(raw) if raw.isdigit() and int(raw) > 0 else None
            value = {"size_in": hundredths / 100 if hundredths else None, "mph": None}
            qualifies = hundredths is not None and hundredths >= HAIL_MIN_HUNDREDTHS
        else:
            raw = (row.get("Speed") or "").strip()
            mph = int(raw) if raw.isdigit() else None
            value = {"size_in": None, "mph": mph}
            qualifies = mph is not None and mph >= WIND_MIN_MPH
        key = (day, kind, when, round(lat, 2), round(lon, 2))
        if key in seen:
            continue
        seen.add(key)
        reports.append({"day": day, "kind": kind, "time": when, "lat": lat, "lon": lon,
                        "qualifies": qualifies, **value})
    return reports, skipped


# ---------------------------------------------------------------- decision records

def load_towns(path) -> dict:
    return {t["slug"]: t for t in json.loads(Path(path).read_text(encoding="utf-8"))}


def check_record(rec, towns: dict, where: str) -> dict:
    """Validates one decision record. A record whose as_of is later than its decision_time was
    written after the decision it claims to support, so it is rejected, as is one dated after its
    reporting day ended (12:00 UTC the next day)."""
    if not isinstance(rec, dict):
        raise ValueError(f"{where}: not a JSON object")
    missing = [k for k in REQUIRED if k not in rec]
    if missing:
        raise ValueError(f"{where}: missing {', '.join(missing)}")
    if rec["arm"] not in ARMS:
        raise ValueError(f"{where}: arm must be A, B or C, not {rec['arm']!r}")
    if not isinstance(rec["town"], str) or rec["town"] not in towns:
        raise ValueError(f"{where}: unknown town {rec['town']!r}")
    try:
        day = date.fromisoformat(str(rec["reporting_day"]))
    except ValueError:
        raise ValueError(f"{where}: reporting_day must be YYYY-MM-DD") from None
    as_of = parse_utc(rec["as_of"], f"{where}: as_of")
    decided = parse_utc(rec["decision_time"], f"{where}: decision_time")
    if as_of > decided:
        raise ValueError(f"{where}: rejected, as_of {rec['as_of']} is later than decision_time "
                         f"{rec['decision_time']}; the record was written after the decision")
    ended = datetime(day.year, day.month, day.day, 12, tzinfo=UTC) + timedelta(days=1)
    if decided >= ended:
        raise ValueError(f"{where}: rejected, decision_time {rec['decision_time']} is after reporting day "
                         f"{day.isoformat()} ended (12:00 UTC the next day)")
    decision = rec["decision"]
    if not isinstance(decision, dict) or not isinstance(decision.get("warned"), bool):
        raise ValueError(f"{where}: decision.warned must be true or false")
    return {"arm": rec["arm"], "town": rec["town"], "day": day, "as_of": as_of,
            "decision_time": decided, "warned": decision["warned"]}


def load_records(path, towns: dict) -> list[dict]:
    """One record per JSON line. A bad line stops the run: dropping a record would bias the result."""
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"decisions line {n}: not JSON ({e.msg})") from None
        out.append(check_record(rec, towns, f"decisions line {n}"))
    return out


# ---------------------------------------------------------------- split

def held_out_days(days, split: str = "event", fraction: float = FRACTION, seed: int = SEED) -> set:
    """Whole groups go to the held-out side: one reporting day (every town and build of an event day
    moves together) or one season. The choice is seeded, so the same inputs give the same split.
    No hour, town-row or pixel is ever split."""
    days = set(days)
    if split == "none":
        return days
    if split not in ("event", "season"):
        raise ValueError("split must be event, season or none")

    def group(d):
        return d if split == "event" else (d.year, SEASON[d.month])

    groups = sorted({group(d) for d in days})
    random.Random(seed).shuffle(groups)
    chosen = set(groups[:round(fraction * len(groups))])
    return {d for d in days if group(d) in chosen}


# ---------------------------------------------------------------- scoring

def evaluate(records: list[dict], reports: list[dict], towns: dict, split: str = "event",
             fraction: float = FRACTION, seed: int = SEED, min_days: int = MIN_DAYS,
             resamples: int = RESAMPLES) -> dict:
    """Scores each arm on the held-out days. Returns plain data; render() writes the table."""
    first: dict = {}          # (town, day) -> first qualifying report within the radius
    event_days: set = set()   # reporting days with such a report near any town; shared by all arms
    for rep in reports:
        if not rep["qualifies"]:
            continue
        for slug, town in towns.items():
            if miles(rep["lat"], rep["lon"], town["lat"], town["lon"]) <= RADIUS_MI:
                event_days.add(rep["day"])
                first[(slug, rep["day"])] = min(first.get((slug, rep["day"]), rep["time"]), rep["time"])
    held = sorted(held_out_days({r["day"] for r in records} | event_days, split, fraction, seed))
    index = {d: i for i, d in enumerate(held)}
    units: dict = {}          # (arm, town, day) -> earliest decision_time that warned, or None
    for r in records:
        if r["day"] not in index:
            continue
        key = (r["arm"], r["town"], r["day"])
        units.setdefault(key, None)
        if r["warned"] and (units[key] is None or r["decision_time"] < units[key]):
            units[key] = r["decision_time"]
    arms = {arm: score_arm(arm, units, first, held, event_days, min_days, seed, resamples) for arm in ARMS}
    return {"split": split, "fraction": fraction, "seed": seed, "min_days": min_days,
            "resamples": resamples, "held_days": len(held),
            "held_event_days": sum(d in event_days for d in held), "arms": arms}


def score_arm(arm, units, first, held, event_days, min_days, seed, resamples) -> dict:
    index = {d: i for i, d in enumerate(held)}
    n = len(held)
    cols = {k: [0] * n for k in ("units", "outcomes", "misses", "warned", "fa", "late")}
    leads: list[list[float]] = [[] for _ in range(n)]
    no_record = sum(1 for (slug, day) in first if day in index and (arm, slug, day) not in units)
    for (a, slug, day), warned_at in units.items():
        if a != arm:
            continue
        i = index[day]
        cols["units"][i] += 1
        cols["warned"][i] += int(warned_at is not None)
        if (slug, day) in first:
            cols["outcomes"][i] += 1
            if warned_at is None:
                cols["misses"][i] += 1
            else:
                lead = (first[(slug, day)] - warned_at).total_seconds() / 3600
                leads[i].append(lead)
                cols["late"][i] += int(lead < 0)
        elif warned_at is not None:
            cols["fa"][i] += 1
    with_units = [i for i in range(n) if cols["units"][i]]
    event_n = sum(1 for i in with_units if held[i] in event_days)
    quiet_n = len(with_units) - event_n
    total = {k: sum(v) for k, v in cols.items()}
    res = {"arm": arm, "event_days": event_n, "quiet_days": quiet_n, "units": total["units"],
           "outcomes": total["outcomes"], "misses": total["misses"], "hits": total["outcomes"] - total["misses"],
           "warned": total["warned"], "fa": total["fa"], "late": total["late"], "no_record": no_record,
           "status": INSUFFICIENT, "metrics": None}
    if n == 0 or event_n < min_days or quiet_n < min_days:
        return res
    res["status"] = "ok"
    point = _metrics(range(n), cols, leads)
    rng = random.Random(seed)
    boots = [_metrics([rng.randrange(n) for _ in range(n)], cols, leads) for _ in range(resamples)]
    res["metrics"] = {name: _interval(point[k], [b[k] for b in boots]) for k, name in enumerate(METRICS)}
    return res


def _metrics(sample, cols: dict, leads: list) -> tuple:
    """Miss rate, false-alarm ratio and median lead time over the sampled reporting days (a day may
    repeat in a bootstrap sample). None where the denominator is zero: never a zero."""
    sample = list(sample)
    outs = sum(cols["outcomes"][i] for i in sample)
    miss = sum(cols["misses"][i] for i in sample)
    warned = sum(cols["warned"][i] for i in sample)
    fa = sum(cols["fa"][i] for i in sample)
    lead = [x for i in sample for x in leads[i]]
    return (miss / outs if outs else None,
            fa / warned if warned else None,
            statistics.median(lead) if lead else None)


def _interval(point, values):
    """Point estimate and 95% percentile interval, or None when the point is undefined."""
    if point is None:
        return None
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    m = len(vals)
    return point, vals[int(0.025 * m)], vals[min(m - 1, int(0.975 * m))]


# ---------------------------------------------------------------- output

def _cell(metric, fmt=lambda x: f"{x:.2f}") -> str:
    if metric is None:
        return INSUFFICIENT
    point, lo, hi = metric
    return f"{fmt(point)} [{fmt(lo)}, {fmt(hi)}]"


def render(result: dict) -> str:
    lines = [
        "# Predeclared evaluation: proxy outcomes, not ground truth",
        "",
        f"Outcome: SPC storm reports within {RADIUS_MI:g} miles of a town on its reporting day: hail of "
        f"{HAIL_MIN_HUNDREDTHS / 100:.2f} in or more, or wind of {WIND_MIN_MPH} mph or more (PROPOSED).",
        f"Split: {result['split']} (held-out fraction {result['fraction']:.2f}, seed {result['seed']}); "
        f"held-out reporting days {result['held_days']}, of which event days {result['held_event_days']}.",
        f"Minimum sample per arm: {result['min_days']} event and {result['min_days']} quiet days (PROPOSED). "
        f"Intervals: 95% percentile bootstrap over reporting days, {result['resamples']} resamples.",
        "",
        "| Arm | Event days | Quiet days | Town-days | Outcomes | Misses | Miss rate [95% CI] | "
        "False-alarm ratio [95% CI] | Median lead, h [95% CI] | Late hits | No record |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, r in result["arms"].items():
        ok = r["status"] == "ok"
        m = r["metrics"] or {}

        def cell(name, fmt=lambda x: f"{x:.2f}"):
            return _cell(m.get(name), fmt) if ok else INSUFFICIENT

        misses = f"{r['misses']} of {r['outcomes']}" if r["outcomes"] else INSUFFICIENT
        lines.append(f"| {arm} | {r['event_days']} | {r['quiet_days']} | {r['units']} | {r['outcomes']} | "
                     f"{misses} | {cell('miss_rate')} | {cell('fa_ratio')} | "
                     f"{cell('lead_h', lambda x: f'{x:.1f}')} | {r['late']} | {r['no_record']} |")
    lines += [
        "",
        f"Skipped outcome rows (bad time or position, not scored): {result.get('skipped', 0)}.",
        "No record: town-days with a qualifying outcome that the arm has no decision record for (not scored).",
        "Arms are never pooled. A metric is shown only when its sample meets the minimum; "
        f"\"{INSUFFICIENT}\" is never a zero.",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score decision records against SPC storm-report outcomes.")
    ap.add_argument("decisions", type=Path, help="decision records, JSON Lines")
    ap.add_argument("outcomes", type=Path, help="SPC storm reports with day and kind columns, CSV")
    ap.add_argument("--towns", type=Path, default=DEFAULT_TOWNS, help="town list (default website/towns.json)")
    ap.add_argument("--split", choices=("event", "season", "none"), default="event")
    ap.add_argument("--fraction", type=float, default=FRACTION)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--min-days", type=int, default=MIN_DAYS)
    ap.add_argument("--resamples", type=int, default=RESAMPLES)
    a = ap.parse_args(argv)
    try:
        towns = load_towns(a.towns)
        records = load_records(a.decisions, towns)
        reports, skipped = load_outcomes(a.outcomes)
        result = evaluate(records, reports, towns, a.split, a.fraction, a.seed, a.min_days, a.resamples)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"error: {e!r}" if isinstance(e, (KeyError, TypeError)) else f"error: {e}", file=sys.stderr)
        return 1
    result["skipped"] = skipped
    print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
