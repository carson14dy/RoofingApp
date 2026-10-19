"""River gauges (B5 Source 7): NWS flood stages (NWPS) and USGS annual peak stages, the nearest gauge within 10 miles (D6).

What it is: the river flood record at the nearest gauge that has an NWS flood stage, from two federal sources: the NWS
flood categories (action, minor, moderate, major, in feet) and the USGS annual peak stage by water year. It is a
record at a river gauge, not a statement about the address. The gauge does not say whether water reached the address,
and no daily flood-day count is made (there is no daily stage series for these gauges; B5 brief, source 7).

Source (the research record river-flood-gauges.json and its refuter; quoted terms are verbatim on the live pages):
  Gauge list   https://api.water.noaa.gov/nwps/v1/gauges?srid=EPSG_4326&bbox.xmin=-117.0&bbox.ymin=44.0&bbox.xmax=-103.5&bbox.ymax=49.5
               (the list has 486 gauges in this box: 277 in Montana; each entry gives the LID, name, state and position,
               which place a gauge whose detail could not be read). The NWPS swagger lists no terms field.
  Gauge detail https://api.water.noaa.gov/nwps/v1/gauges/<LID>: flood.categories.{action,minor,moderate,major}.stage in
               feet (-9999 is not defined), state.abbreviation, usgsId, latitude, longitude, dataAttribution.
  Peaks        https://api.waterdata.usgs.gov/ogcapi/v1/collections/peaks/items?monitoring_location_id=USGS-<usgs>&parameter_code=00065&limit=1000&f=json
               The parameter_code is required: without it the response mixes 99 discharge rows into 64 gage-height rows.
               waterservices.usgs.gov is retired on 2027-02-22; api.waterdata.usgs.gov is the replacement.
               Live on 2026-10-19 for 06214500 (Billings): 64 features, all parameter 00065 in ft, 2022-06-15 16.37 ft.
  Terms        NWS Web pages are public domain on three conditions (weather.gov/disclaimer; quoted in snowgrid.py). USGS
               credit: "Observations courtesy of U.S. Geological Survey" (the NWPS attribution text). Not all USGS site
               content is public domain (non-USGS photographs and graphics need permission); the peaks are USGS data.
  Units        flood stages and peaks in feet, two decimals (USGS values are strings with two decimals); stored as
               hundredths of a foot. Water years run October 1 to September 30 (named for the year they end).
  Missing      -9999 and absent categories are "not defined" (a reservoir gauge may define only an action stage: it has no
               flood stage and is not in the pool). A gauge with no USGS number stays in the pool (no peak series).

The pool (D6): every NWPS gauge in the box that defines an NWS flood stage (the minor category), in any state, except
gauges whose categories are elevations (any defined category of 1,000 ft or more: Lake Pend Oreille at Hope, Idaho, is
the nearest such to a Montana grid point, 13.7 miles away). The rule: the nearest pool gauge within RADIUS_MILES (10,
one constant; the owner's open decision O4, with 25 miles the alternative) gives the gauge line. A listed gauge whose
detail could not be read is a candidate too: when it is the nearest (or the only one) within 10 miles, the line is
"could not be loaded" with its name and distance, never "none" and never a farther gauge. Beyond 10 miles there is no
gauge line. The peaks are keyed by USGS number, since CBMM8 and CLRM8 share 06185110.

Scope of the store: one file per USGS number in the scope, which is every Montana pool gauge plus
the nearest pool gauge in any state to each town, gate point and tile centre, when that gauge lies within 10 miles of the
point. An out-of-state gauge that is not the nearest to any of those points is not kept. The count is 104 files
(103 with peak rows; one Montana file, GLWM8's USGS series, has none); B5 brief lines 58 and 193 say 97 and must follow.

Failures (D16): a gauge file that cannot be read is a failure of that gauge only. A bad
download (a page that is not JSON, an answer that is not the expected shape, a row that is not gage height in feet)
is retried by stations.fetch, then the cached copy is used with its reason, else the gauge or series fails. The
town's line then says the gauge could not be loaded, or its peaks could not be loaded (the peaks field is "unavailable"),
so a gauge line beside no peaks cannot read as "no annual peak". Only a list that cannot be read at all makes the whole
gauge section unavailable.

Store (format hail-gauge-v1), see the B5 brief:
  hail/g/<usgs>.json  one per USGS number in the scope: name, position, the stages in hundredths of a foot, the LIDs that
                      share the number, and the annual peak rows [water year, date, hundredths, qualifiers]; a water year
                      with two rows (two USGS rows, as WY1987 and WY2023 have) keeps both, each with its qualifiers.
  hail/index.json     gains "gauges": the rule, the sources, the counts, the pool (every pool gauge's id, USGS number,
                      name, position, state, stages and peaks status), each of the 17 towns' nearest gauge, the Billings
                      check and the failures.
  hail/manifest.json  lists every hail/g/ file with its bytes and SHA-256.

Command line (run from the repository root):
    python -m website.gauges build --store DIR --cache DIR [--offline] [--refresh] [--procs 3] [--deadline-at EPOCH]
    python -m website.gauges verify --store DIR --cache DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from . import stations as S

FORMAT = "hail-gauge-v1"
INDEX_KEY = "gauges"
G_PREFIX = "hail/g/"
RADIUS_MILES = 10.0                    # D6: the one constant for the nearest-gauge rule
ELEVATION_FT = 1000.0                  # categories at or above this are elevations, not stages (excluded)
NODATA_FT = -9000.0
LIST_URL = ("https://api.water.noaa.gov/nwps/v1/gauges?srid=EPSG_4326&bbox.xmin=-117.0&bbox.ymin=44.0"
            "&bbox.xmax=-103.5&bbox.ymax=49.5")
DETAIL_URL = "https://api.water.noaa.gov/nwps/v1/gauges/{lid}"
PEAKS_URL = ("https://api.waterdata.usgs.gov/ogcapi/v1/collections/peaks/items?monitoring_location_id=USGS-{usgs}"
             "&parameter_code=00065&limit=1000&f=json")
PARAMETER = "00065"
CATEGORIES = ("action", "minor", "moderate", "major")
PROCS_DEFAULT = 3                      # NWPS refused some TLS handshakes under four parallel connections (refuter)
PACE_S = 0.2                           # at least this long between two gauge requests
USER_AGENT = "montana-hail-watch-gauges/1 (+https://github.com/carson14dy/RoofingApp)"
BILLINGS_CHECK = {"usgs": "06214500", "water_year": 2022, "date": "2022-06-15", "hundredths": 1637,
                  "minor_hundredths": 1350}


class GaugeError(S.StationsError):
    """A file or figure that cannot be used. The message is plain words, lower case, with no full stop. It is a
    StationsError, so a download that answers with it is a failed request (retried, then the cached copy), not a crash."""


WORDS = {
    "lead": ("River flood record at the {name} gauge, {miles} miles away; it does not say water reached this address."),
    "stages": ("River gauge: NWS flood stage {minor} ft (action {action} ft, moderate {moderate} ft, major {major} ft) "
               "at this gauge."),
    "peak": "River gauge: water year {wy}, peak {ft} ft on {date}{qual}, at or above the {minor} ft flood stage.",
    "peak_qual": " (USGS qualifier: {qual})",
    "no_peaks": ("No annual peak at or above the {minor} ft flood stage is listed for water years {first} to {last} "
                 "at this gauge."),
    "none_near": ("No gauge with an NWS flood stage is within 10 miles of {place}. That is not a statement that the "
                  "river did not flood there."),
    "gauge_unavailable": "{Part} could not be loaded in this update; that is not the same as no {one}.",
    "peaks_unavailable": "{Part} could not be loaded in this update; that is not the same as no {one}.",
    "unavailable": "{part} could not be loaded in this update; that is not the same as no {part}.",
    "source": ("Source: NWS river gauges (National Water Prediction Service flood categories) and USGS annual peak "
               "stage, water years. Observations courtesy of U.S. Geological Survey."),
    "stage_note": "Flood stage is the NWS minor category. Stages are in feet at the gauge.",
    "peak_note": ("An annual peak is the highest gage height the USGS lists for a water year (October 1 to September 30). "
                  "A qualifier is shown as the USGS wrote it."),
    "what": ("A river gauge measures the water level at one point on a river. The record here is the gauge's own flood "
             "stage and its annual peaks, not the water at this address."),
}


# ---------------------------------------------------------------- readers

def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= NODATA_FT:
        return None
    return number


def _obj(value) -> dict:
    """The value when it is a JSON object, else an empty object (a shape the file does not have reads as absent)."""
    return value if isinstance(value, dict) else {}


def parse_detail(doc) -> dict | None:
    """One NWPS gauge detail as the pool needs it, or None when the document is not a gauge. Returns the stages in feet
    (None when not defined), the state, the USGS number and the position. Any part of the wrong shape reads as absent."""
    if not isinstance(doc, dict) or not isinstance(doc.get("lid"), str) or not doc.get("lid"):
        return None
    cats = _obj(_obj(doc.get("flood")).get("categories"))
    stages = {name: _num(_obj(cats.get(name)).get("stage")) for name in CATEGORIES}
    state = _obj(doc.get("state")).get("abbreviation")
    usgs = doc.get("usgsId") or None
    try:
        lat, lon = float(doc["latitude"]), float(doc["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    name = doc.get("name") if isinstance(doc.get("name"), str) and doc.get("name") else doc["lid"]
    wfo = _obj(doc.get("wfo")).get("abbreviation")
    return {"lid": doc["lid"], "name": name, "usgs": str(usgs) if usgs else None,
            "state": state if isinstance(state, str) else None, "lat": lat, "lon": lon, "stages": stages,
            "wfo": wfo if isinstance(wfo, str) else None}


def _parse_detail_bytes(data: bytes) -> dict | None:
    try:
        return parse_detail(json.loads(data.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, TypeError, AttributeError, KeyError):
        return None


def _listing(entry: dict) -> dict | None:
    """A listed gauge's name, position and state from the NWPS list: what places a gauge whose detail could not be read."""
    try:
        lat, lon = float(entry["latitude"]), float(entry["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    name = entry.get("name") if isinstance(entry.get("name"), str) and entry.get("name") else entry.get("lid")
    state = _obj(entry.get("state")).get("abbreviation")
    return {"name": name, "lat": lat, "lon": lon, "state": state if isinstance(state, str) else None}


def pool_status(gauge: dict) -> str:
    """"pool", "no_flood_stage" (the minor category is not defined) or "elevation" (a defined category is 1,000 ft or
    more). The elevation test comes first: a gauge with an elevation scale is removed whatever else it defines."""
    stages = [v for v in gauge["stages"].values() if v is not None]
    if any(v >= ELEVATION_FT for v in stages):
        return "elevation"
    if gauge["stages"].get("minor") is None:
        return "no_flood_stage"
    return "pool"


def parse_peaks(doc, usgs: str) -> list[list]:
    """The USGS annual peak rows as [water year, "YYYY-MM-DD", hundredths of a foot, [qualifiers]], sorted by water year
    and date. A row that is not parameter 00065 in feet, is not for this site, or is not a row at all raises GaugeError
    (the series then fails; the rest of the build goes on)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("features"), list):
        raise GaugeError(f"the USGS peaks for {usgs} are not in the expected format")
    rows = []
    for feature in doc["features"]:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            raise GaugeError(f"a USGS row for {usgs} has no properties")
        if props.get("parameter_code") != PARAMETER or props.get("unit_of_measure") != "ft":
            raise GaugeError(f"a USGS row for {usgs} is not gage height in feet")
        if props.get("monitoring_location_id") != f"USGS-{usgs}":
            raise GaugeError(f"a USGS row for {usgs} names another site")
        try:
            wy = int(props["water_year"])
            day = date.fromisoformat(str(props["time"])[:10])
            value = (Decimal(str(props["value"])) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise GaugeError(f"a USGS row for {usgs} cannot be read ({type(exc).__name__})") from exc
        qual = props.get("qualifier")
        if qual is None or qual == []:
            qual_list = []
        elif isinstance(qual, list):
            qual_list = sorted(str(q) for q in qual)
        else:
            qual_list = [str(qual)]
        rows.append([wy, day.isoformat(), int(value), qual_list])
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return rows


def hundredths(value: float | None) -> int | None:
    if value is None:
        return None
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gauge_doc(usgs: str, lids: list[str], first: dict, peaks: list[list]) -> dict:
    """The g/ file for one USGS number: the first gauge's name and position (the LIDs share one series) and the peaks."""
    stages = {name: hundredths(first["stages"].get(name)) for name in CATEGORIES}
    years = [row[0] for row in peaks]
    return {"f": FORMAT, "usgs": usgs, "lids": sorted(lids), "name": first["name"], "state": first["state"],
            "lat": first["lat"], "lon": first["lon"], "unit": "hundredths of a foot", "stages": stages,
            "peaks": peaks, "rows": len(peaks),
            "water_years": [min(years), max(years)] if years else None,
            "source": "USGS water data API, annual peaks, parameter 00065; NWS flood categories (NWPS)"}


def _pool_line(gauge: dict, miles: float) -> dict:
    return {"lid": gauge["lid"], "usgs": gauge["usgs"], "name": gauge["name"], "state": gauge["state"],
            "miles": round(miles, 1), "minor_ft": gauge["stages"]["minor"]}


def nearest(pool: list[dict], lat: float, lon: float, radius: float = RADIUS_MILES) -> dict | None:
    """The nearest pool gauge within radius miles (distance, then LID), or None."""
    best = None
    for gauge in pool:
        miles = S.haversine_miles(lat, lon, gauge["lat"], gauge["lon"])
        if miles <= radius and (best is None or (miles, gauge["lid"]) < (best[0], best[1]["lid"])):
            best = (miles, gauge)
    if best is None:
        return None
    miles, gauge = best
    return _pool_line(gauge, miles)


def nearest_listed(pool: list[dict], failed: list[dict], lat: float, lon: float,
                   radius: float = RADIUS_MILES) -> dict | None:
    """The nearest candidate within radius miles among the pool and the listed gauges whose detail could not be read
    (failed: dicts with lid, name, lat, lon), by distance then LID. A failed gauge that is the nearest, or the only
    candidate, gives an unavailable line (with its name, distance and the words "could not be loaded"); it never gives
    a farther pool gauge, and never "none"."""
    candidates = []
    for gauge in pool:
        miles = S.haversine_miles(lat, lon, gauge["lat"], gauge["lon"])
        if miles <= radius:
            candidates.append((miles, gauge["lid"], gauge, False))
    for entry in failed:
        miles = S.haversine_miles(lat, lon, entry["lat"], entry["lon"])
        if miles <= radius:
            candidates.append((miles, entry["lid"], entry, True))
    if not candidates:
        return None
    miles, lid, item, is_failed = min(candidates, key=lambda c: (c[0], c[1]))
    if not is_failed:
        return _pool_line(item, miles)
    part = f"The {item['name']} gauge, {round(miles, 1)} miles away"
    return {"unavailable": True, "lid": lid, "name": item["name"], "miles": round(miles, 1),
            "reason": "the gauge could not be loaded in this update",
            "sentence": WORDS["gauge_unavailable"].format(Part=part, one="river flood record at that gauge")}


# ---------------------------------------------------------------- fetching

def _check_json(kind: str):
    """The check a download must pass to be kept (and a cached copy must pass to be read): a JSON object of the kind's
    shape. Anything else is a GaugeError, which stations.fetch treats as a failed request."""
    def check(data: bytes) -> None:
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise GaugeError(f"the {kind} is not JSON") from exc
        if not isinstance(doc, dict):
            raise GaugeError(f"the {kind} is not an object")
        if kind == "list" and not isinstance(doc.get("gauges"), list):
            raise GaugeError("the gauge list has no gauges")
        if kind == "peaks" and not isinstance(doc.get("features"), list):
            raise GaugeError("the peaks have no features list")
    return check


def collect(cache: Path, *, offline: bool, refresh: bool, procs: int, deadline_at: float | None = None) -> dict:
    """The NWPS list and every detail in it. Each file is cached. A detail that cannot be read is a failed gauge (its
    line says so) rather than a failed build; only a list that cannot be read raises GaugeError."""
    from concurrent.futures import ThreadPoolExecutor
    pacer = S._Pacer(PACE_S)
    root = cache / "nwps"
    failures: list[dict] = []
    raw, state, reason = S.fetch(LIST_URL, root / "gauges_list_wide.json", _check_json("list"), offline=offline,
                                 refresh=refresh, pacer=pacer, deadline_at=deadline_at)
    if raw is None:
        raise GaugeError(f"the NWPS gauge list could not be read ({reason})")
    if reason:
        failures.append({"source": "nwps list", "reason": reason})
    try:
        listed = json.loads(raw.decode("utf-8"))["gauges"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise GaugeError("the NWPS gauge list could not be read (it is not the expected list)") from exc
    if not isinstance(listed, list):
        raise GaugeError("the NWPS gauge list could not be read (it is not the expected list)")
    entries: dict[str, dict] = {}
    for item in listed:
        if isinstance(item, dict) and isinstance(item.get("lid"), str) and item["lid"]:
            entries.setdefault(item["lid"], item)
    lids = sorted(entries)
    details: dict[str, dict] = {}
    failed: dict[str, str] = {}

    def one(lid: str):
        return lid, S.fetch(DETAIL_URL.format(lid=lid), root / "detail" / f"{lid}.json", _check_json("detail"),
                            offline=offline, refresh=refresh, pacer=pacer, deadline_at=deadline_at)

    with ThreadPoolExecutor(max_workers=max(1, procs)) as pool:
        for lid, (data, state_d, reason_d) in pool.map(one, lids):
            if data is None:
                failed[lid] = reason_d or S.REASON_NO_ANSWER
                failures.append({"source": "nwps detail", "lid": lid, "reason": failed[lid]})
                continue
            if reason_d:
                failures.append({"source": "nwps detail", "lid": lid, "reason": reason_d})
            parsed = _parse_detail_bytes(data)
            if parsed is None:
                failed[lid] = "the gauge detail could not be read"
                failures.append({"source": "nwps detail", "lid": lid, "reason": failed[lid]})
                continue
            details[lid] = parsed
    listing = {lid: _listing(entries[lid]) for lid in sorted(failed)}
    return {"listed": len(listed), "lids": lids, "details": details, "failed": failed,
            "failed_listing": {lid: dict(info, lid=lid) for lid, info in listing.items() if info is not None},
            "failures": failures, "pacer": pacer}


def fetch_peaks(usgs_numbers: list[str], cache: Path, *, offline: bool, refresh: bool, pacer, procs: int,
                deadline_at: float | None = None):
    from concurrent.futures import ThreadPoolExecutor
    out: dict[str, tuple] = {}

    def one(usgs: str):
        url = PEAKS_URL.format(usgs=usgs)
        return usgs, S.fetch(url, cache / "usgs" / "peaks" / f"{usgs}.json", _check_json("peaks"), offline=offline,
                             refresh=refresh, pacer=pacer, deadline_at=deadline_at)

    with ThreadPoolExecutor(max_workers=max(1, procs)) as pool:
        for usgs, (data, state, reason) in pool.map(one, usgs_numbers):
            out[usgs] = (data, state, reason)
    return out


def _towns() -> list[dict]:
    return json.loads(S.TOWNS_FILE.read_text(encoding="utf-8"))


def _peaks_status(usgs, peaks_failed: set, written: set) -> str:
    if not usgs:
        return "no USGS number"
    if usgs in peaks_failed:
        return "unavailable"
    return "available" if usgs in written else "not in the store"


def build(store: Path, cache: Path, *, offline: bool = False, refresh="none", procs: int = PROCS_DEFAULT,
          deadline_at: float | None = None) -> dict:
    store = Path(store)
    t0 = time.monotonic()
    every = refresh in (True, "all")
    try:
        got = collect(Path(cache), offline=offline, refresh=every, procs=procs, deadline_at=deadline_at)
    except GaugeError as exc:
        for old in (store / G_PREFIX).glob("*.json") if (store / G_PREFIX).is_dir() else []:
            old.unlink()
        _merge_index(store, {"state": "unavailable", "problem": str(exc), "rule": _rule()})
        S._merge_manifest(store, {}, prefixes=(G_PREFIX,))
        return {"state": "unavailable", "problem": str(exc)}
    details = got["details"]
    failed = got["failed"]
    status = {lid: pool_status(g) for lid, g in details.items()}
    pool = [dict(g, lid=lid) for lid, g in sorted(details.items()) if status[lid] == "pool"]
    mt_pool = [g for g in pool if g["state"] == "MT"]
    scope = _scope(pool, store)
    usgs_numbers = sorted({g["usgs"] for g in scope if g["usgs"]})
    failures = list(got["failures"])
    for lid in sorted(failed):
        # a failed detail is the only source of its USGS number, so its peak series cannot be requested
        failures.append({"source": "usgs peaks", "lid": lid, "reason": "its USGS number is not known because its gauge "
                         "detail could not be read, so its peak series was not requested"})
    peaks = fetch_peaks(usgs_numbers, Path(cache), offline=offline, refresh=every, pacer=got["pacer"], procs=procs,
                        deadline_at=deadline_at)
    # this module's folder is rebuilt whole: a series that left the scope must not stay on disk
    for old in (store / G_PREFIX).glob("*.json") if (store / G_PREFIX).is_dir() else []:
        old.unlink()
    files: dict[str, dict] = {}
    total = 0
    series = 0
    rows_total = 0
    peaks_failed: set[str] = set()
    written: set[str] = set()
    for usgs in usgs_numbers:
        data, state_p, reason_p = peaks[usgs]
        if data is None:
            peaks_failed.add(usgs)
            failures.append({"source": "usgs peaks", "usgs": usgs, "reason": reason_p or S.REASON_NO_ANSWER})
            continue
        if reason_p:
            failures.append({"source": "usgs peaks", "usgs": usgs, "reason": reason_p})
        try:
            rows = parse_peaks(json.loads(data.decode("utf-8")), usgs)
        except (GaugeError, UnicodeDecodeError, ValueError):
            peaks_failed.add(usgs)
            failures.append({"source": "usgs peaks", "usgs": usgs, "reason": "the USGS peaks could not be read"})
            continue
        members = [g for g in pool if g["usgs"] == usgs]
        first = sorted(members, key=lambda g: g["lid"])[0]
        doc = gauge_doc(usgs, [g["lid"] for g in members], first, rows)
        out = (json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
        rel = f"{G_PREFIX}{usgs}.json"
        S._write_atomic(store / rel, out)
        files[rel] = {"bytes": len(out), "sha256": hashlib.sha256(out).hexdigest()}
        written.add(usgs)
        total += len(out)
        series += 1
        rows_total += len(rows)
    listed_failed = [got["failed_listing"][lid] for lid in sorted(got["failed_listing"])]
    towns = {}
    for town in _towns():
        found = nearest_listed(pool, listed_failed, town["lat"], town["lon"])
        if found is None:
            towns[town["slug"]] = {"none": True}
        elif found.get("unavailable"):
            towns[town["slug"]] = found
        else:
            line = dict(found, peaks=_peaks_status(found["usgs"], peaks_failed, written))
            if line["peaks"] == "unavailable":          # the gauge line must not read as "no annual peak" (AGENTS rule 5)
                line["peaks_sentence"] = WORDS["peaks_unavailable"].format(
                    Part="The annual peaks at this gauge", one="annual peak")
            towns[town["slug"]] = line
    gates = {}
    billings = towns.get("billings", {})
    gates["billings_nearest"] = billings
    gates["billings_peak"] = _billings_peak(store, peaks_failed)
    state = "partial" if failures or failed else "loaded"
    block = {
        "state": state,
        "problem": None if state == "loaded" else "some gauge files did not load (see failures)",
        "rule": _rule(),
        "sources": {"list": LIST_URL, "detail": DETAIL_URL, "peaks": PEAKS_URL,
                    "terms": "NWS public domain with conditions; USGS credit line"},
        "counts": {
            "listed": got["listed"], "mt_listed": sum(1 for g in details.values() if g["state"] == "MT"),
            "detail_files": len(details), "failed_details": len(failed),
            "elevation_excluded": sum(1 for s in status.values() if s == "elevation"),
            "no_flood_stage": sum(1 for s in status.values() if s == "no_flood_stage"),
            "pool": len(pool), "pool_mt": len(mt_pool),
            "pool_out_of_state": len(pool) - len(mt_pool),
            "pool_usgs_numbers": len({g["usgs"] for g in pool if g["usgs"]}),
            "scope": len(scope), "scope_usgs_numbers": len(usgs_numbers),
            "g_files": series, "g_bytes": total, "g_rows": rows_total, "peaks_failed": len(peaks_failed),
            "requests": got["pacer"].requests, "downloaded_bytes": got["pacer"].downloaded,
        },
        "pool": [{"lid": g["lid"], "usgs": g["usgs"], "name": g["name"], "state": g["state"], "lat": g["lat"],
                  "lon": g["lon"], "stages": {k: g["stages"][k] for k in CATEGORIES},
                  "peaks": _peaks_status(g["usgs"], peaks_failed, written)} for g in pool],
        "towns": towns,
        "gates": gates,
        "failures": failures[:50],
    }
    _merge_index(store, block)
    S._merge_manifest(store, files, prefixes=(G_PREFIX,))
    return {"state": state, "seconds": round(time.monotonic() - t0, 1), "pool": len(pool), "pool_mt": len(mt_pool),
            "g_files": series, "g_bytes": total, "peak_rows": rows_total, "failures": len(failures),
            "failed_lids": len(failed), "peaks_failed": len(peaks_failed), "towns": towns.get("billings")}


def _scope(pool: list[dict], store: Path) -> list[dict]:
    """The pool gauges whose USGS series the store holds (the scope rule): every Montana pool gauge, and the nearest pool gauge
    in any state to each town, gate point and tile centre, when that gauge is within RADIUS_MILES of the point."""
    index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    points = [(t["lat"], t["lon"]) for t in _towns()] + list(S.GATE_POINTS.values())
    for name in index.get("tiles", []):
        points.append(S.tile_centre(int(name[1:5]), int(name[7:11])))
    keep = {g["lid"] for g in pool if g["state"] == "MT"}
    for lat, lon in points:
        near = nearest(pool, lat, lon)
        if near is not None:
            keep.add(near["lid"])
    return [g for g in pool if g["lid"] in keep]


def _rule() -> dict:
    return {"radius_miles": RADIUS_MILES, "elevation_ft": ELEVATION_FT, "parameter": PARAMETER,
            "pool": "an NWS flood stage (minor) defined and no category at or above 1,000 ft; any state",
            "scope": "every Montana pool gauge, and the nearest pool gauge in any state to each town, gate point and tile "
                     "centre within the radius",
            "unit": "feet; stored as hundredths of a foot", "water_years": "October 1 to September 30"}


def _billings_peak(store: Path, peaks_failed: set) -> dict:
    if BILLINGS_CHECK["usgs"] in peaks_failed:
        return {"found": False, "peaks": "unavailable"}
    rel = f"{G_PREFIX}{BILLINGS_CHECK['usgs']}.json"
    path = store / rel
    if not path.is_file():
        return {"found": False}
    doc = json.loads(path.read_text(encoding="utf-8"))
    hit = [row for row in doc["peaks"] if row[0] == BILLINGS_CHECK["water_year"]]
    return {"found": bool(hit), "rows": hit}


def _merge_index(store: Path, block: dict) -> None:
    path = store / "hail" / "index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    index[INDEX_KEY] = block
    S._write_atomic(path, (json.dumps(index, indent=1, ensure_ascii=True) + "\n").encode("utf-8"))


# ---------------------------------------------------------------- verify

def verify(store: Path, cache: Path | None = None) -> dict:
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    block = index.get(INDEX_KEY)
    check("gauges block present", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    check("gauges state is loaded, partial or unavailable", block.get("state") in ("loaded", "partial", "unavailable"))
    if block.get("state") == "unavailable":
        return {"ok": True, "checks": checks, "note": block.get("problem")}
    rule = block.get("rule", {})
    check("radius is 10 miles (D6)", rule.get("radius_miles") == 10.0)
    manifest = json.loads((store / "hail" / "manifest.json").read_text(encoding="utf-8"))
    bad = 0
    files = sorted((store / G_PREFIX).glob("*.json")) if (store / G_PREFIX).is_dir() else []
    for path in files:
        data = path.read_bytes()
        entry = manifest["files"].get(path.relative_to(store).as_posix())
        if entry is None or entry["bytes"] != len(data) or entry["sha256"] != hashlib.sha256(data).hexdigest():
            bad += 1
    check("manifest lists each g file with its bytes and SHA-256", bad == 0, f"{bad} mismatches")
    check("g file count matches the counts", len(files) == block["counts"]["g_files"], f"{len(files)} files")
    nonint = 0
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for row in doc["peaks"]:
            if not (isinstance(row[0], int) and isinstance(row[2], int)):
                nonint += 1
        for value in doc["stages"].values():
            if value is not None and not isinstance(value, int):
                nonint += 1
    check("g figures are integers (hundredths of a foot)", nonint == 0, f"{nonint} problems")
    billings = block.get("gates", {}).get("billings_peak", {})
    peak_ok = any(row[1] == BILLINGS_CHECK["date"] and row[2] == BILLINGS_CHECK["hundredths"]
                  for row in billings.get("rows", []))
    check("Billings gauge peak 16.37 ft on 2022-06-15 is in the record", peak_ok)
    flood = block.get("gates", {}).get("billings_nearest", {})
    check("Billings nearest gauge with a flood stage is BILM8 within 10 miles",
          flood.get("lid") == "BILM8" and flood.get("miles", 99) <= 10.0, json.dumps(flood))
    if cache is not None and (Path(cache) / "usgs" / "peaks" / "06214500.json").is_file():
        try:
            doc = json.loads((Path(cache) / "usgs" / "peaks" / "06214500.json").read_text(encoding="utf-8"))
            rows = parse_peaks(doc, "06214500")
            check("cached Billings peaks parse to the same record", any(r[0] == 2022 and r[2] == 1637 for r in rows))
        except (GaugeError, UnicodeDecodeError, ValueError) as exc:
            check("cached Billings peaks parse to the same record", False,
                  f"the cached copy could not be read ({type(exc).__name__})")
    ok = all(c["pass"] for c in checks)
    return {"ok": ok, "checks": checks, "counts": block.get("counts")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.gauges", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build hail/g/ and the gauges block")
    b.add_argument("--store", required=True)
    b.add_argument("--cache", required=True)
    b.add_argument("--offline", action="store_true")
    b.add_argument("--refresh", action="store_true", help="re-read the list and every detail and series (the yearly "
                                                         "and monthly job)")
    b.add_argument("--procs", type=int, default=PROCS_DEFAULT)
    b.add_argument("--deadline-at", type=float, default=None,
                   help="epoch seconds: no request starts after this time (the job's clock)")
    v = sub.add_parser("verify", help="check the gauges block and the g files")
    v.add_argument("--store", required=True)
    v.add_argument("--cache", default=None)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "build":
        deadline_at = None
        if args.deadline_at is not None:
            deadline_at = time.monotonic() + (args.deadline_at - time.time())
        print(json.dumps(build(Path(args.store), Path(args.cache), offline=args.offline,
                               refresh="all" if args.refresh else "none", procs=args.procs,
                               deadline_at=deadline_at), indent=1, sort_keys=True, default=str))
        return 0
    result = verify(Path(args.store), Path(args.cache) if args.cache else None)
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
