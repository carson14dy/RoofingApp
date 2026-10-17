"""Seeded robustness checks for the feed parsers in website/sources.py and website/gridded.py.

Each check builds 200 inputs from fixed seeds (random.Random with a string seed), so a failure
reproduces exactly; the message names the seed. The inputs are what a feed could send wrong:
missing keys, nulls, numbers as text, text as numbers, unexpected units, absurd sizes, doubled or
cut-off rows, unreadable bytes.

The invariants come from AGENTS.md (rules 5 to 7) and the feed CONTRACTS:
  * a parser returns its records, or raises the module's own ValueError. The build catches only
    ValueError around each parser, so any other exception stops the whole build. A ValueError that
    Python raises from a bad value (int(), float()) also counts as a failure: one bad row then costs
    the whole file, and the caller cannot tell it from a real error.
  * a missing value comes back None (or the hour is left out), never 0;
  * a value comes out only in an expected unit: an unexpected unit is an error or None, never a guess;
  * a number that leaves a parser is finite.

A test marked expectedFailure fails on a seeded input. Its comment gives the smallest failing
input. When the parser is fixed, the test reports an unexpected success: remove the decorator then.
"""
import copy
import linecache
import math
import random
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import gridded as g  # noqa: E402
from website import sources as src  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
DAY = date(2026, 7, 1)
N = 200                                     # seeded inputs per check
MODULE_FILES = (src.__file__, g.__file__)
ABSENT = object()                           # a key left out of the document
START = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
KINDS = {"warning", "watch", "advisory", "statement"}
SQUARE = {"type": "Polygon", "coordinates": [[[-110, 45], [-109, 45], [-109, 46], [-110, 46], [-110, 45]]]}

# Values a feed could put where a number, text, list or object belongs.
JUNK = [None, True, False, 0, -1, 1.5, "", "x", "²", "9" * 400, [], [1], {}, {"a": 1},
        float("nan"), float("inf"), 1e308, "0001-01-01T00:00:00+01:00", "9999-12-31T23:30:00-01:00"]
NUMBER_SLOT_JUNK = [True, False, "40", [40], {"value": 40}]
WIND_SLOT_JUNK = [True, False, [40], {"value": 40}]     # windSpeed text is str()-ed: "40" would be a unit guess


# ---------------------------------------------------------------- harness

def module_error(exc) -> bool:
    """True when exc is the parsers' own ValueError: one raised by a `raise ValueError(...)` line in
    website/sources.py or website/gridded.py. A ValueError that Python raises from a bad value
    (int(), float(), math) is not one."""
    if type(exc) is not ValueError or exc.__traceback__ is None:
        return False
    tb = exc.__traceback__
    while tb.tb_next is not None:
        tb = tb.tb_next
    code = tb.tb_frame.f_code
    line = linecache.getline(code.co_filename, tb.tb_lineno)
    return code.co_filename in MODULE_FILES and line.lstrip().startswith("raise ValueError")


def call(fn, *args):
    """(value, None) when fn returns; (None, exception) when it raises."""
    try:
        return fn(*args), None
    except Exception as e:  # noqa: BLE001 - every exception type is a finding here
        return None, e


def unhandled(exc) -> str:
    return f"unhandled {type(exc).__name__}: {str(exc)[:70]}"


def failed(exc) -> str:
    """The problem for a valid input that a parser refused (its own error) or crashed on."""
    return f"valid input refused: {exc}" if module_error(exc) else unhandled(exc)


def rng_for(name: str, seed: int) -> random.Random:
    return random.Random(f"{name}:{seed}")     # a string seed gives the same stream on every machine


def sweep(name, make, check):
    """Build the N seeded inputs for this name and run check on each. Returns (seed, input, problem)
    for every input that broke the invariant."""
    found = []
    for seed in range(N):
        case = make(rng_for(name, seed))
        problem = check(case)
        if problem:
            found.append((seed, case, problem))
    return found


def short(x, limit=180) -> str:
    text = repr(x)
    return text if len(text) <= limit else text[:limit] + "..."


def report(found_by_name) -> str:
    lines = []
    for name, found in found_by_name.items():
        if found:
            seed, case, problem = min(found, key=lambda f: len(repr(f[1])))
            lines.append(f"{name}: {len(found)} of {N} seeded inputs broke the invariant. Shortest case: "
                         f"seed {seed}, {short(case)} -> {problem}")
    return "\n".join(lines)


def same(a, b) -> bool:
    """Equal numbers, or both None. 0 and None are different."""
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def put(d, key, value):
    if value is not ABSENT:
        d[key] = value


def _paths(node, prefix=()):
    out = [prefix]
    if isinstance(node, dict):
        for k, v in node.items():
            out += _paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _paths(v, prefix + (i,))
    return out


def mutated(rng, doc):
    """A copy of doc with one to three values replaced by junk, or keys removed."""
    doc = copy.deepcopy(doc)
    for _ in range(rng.randint(1, 3)):
        path = rng.choice(_paths(doc))
        if not path:
            doc = copy.deepcopy(rng.choice(JUNK))
            continue
        parent = doc
        for key in path[:-1]:
            parent = parent[key]
        if isinstance(parent, dict) and rng.random() < 0.2:
            del parent[path[-1]]
        else:
            parent[path[-1]] = copy.deepcopy(rng.choice(JUNK))
    return doc


class Checks(unittest.TestCase):
    """Shared assertion: fail with the shortest failing seeded case for each parser."""

    def expect_clean(self, found_by_name):
        text = report(found_by_name)
        self.assertFalse(text, text)


# ---------------------------------------------------------------- SPC storm reports

SPC_TIMES = ["2215", "0105", "1159", "0000", "2400", "2360", "bad", "", "-1", "99", "1200"]
SPC_VALUES = {                                 # "²" passes isdigit() but int() rejects it; "５0" is fullwidth
    "hail": ["175", "0175", "175.0", "abc", "-175", "0", "", "UNK", "100", "1000", "1001", "99999",
             " 175 ", "²", "５0", "1" * 40, "1" * 4301],
    "wind": ["61", "61.0", "UNK", "-5", "0", "", "99999999", "²", "NaN", "1" * 4301],
}
MT_LATS = ["46.96", "47.72", "44.5", "49.0"]
MT_LONS = ["-104.16", "-108.0", "-116.5"]
JUNK_LATS = ["nan", "inf", "", "x", "-91", "12.0"]
JUNK_LONS = ["nan", "", "x", "-200", "-104.2"]
SPC_PLACES = ["2 SE Wibaux", "", "Glendive", "BIG, HAIL"]    # an unquoted comma shifts the columns


def spc_case(rng):
    kind = rng.choice(["hail", "wind"])
    cols = ["Time", "Size" if kind == "hail" else "Speed", "Location", "County", "State", "Lat", "Lon", "Comments"]
    if rng.random() < 0.1:
        cols.pop(rng.randrange(2, len(cols)))      # a missing column
    if rng.random() < 0.1:
        cols.append("Extra")
    rows = []
    for _ in range(rng.randint(0, 8)):
        if rows and rng.random() < 0.15:
            rows.append(rows[-1])                  # a duplicate row
            continue
        lat = rng.choice(MT_LATS) if rng.random() < 0.7 else rng.choice(MT_LATS + JUNK_LATS)
        lon = rng.choice(MT_LONS) if rng.random() < 0.7 else rng.choice(MT_LONS + JUNK_LONS)
        values = {"Time": rng.choice(SPC_TIMES), cols[1]: rng.choice(SPC_VALUES[kind]),
                  "Location": rng.choice(SPC_PLACES), "County": "Wibaux",
                  "State": rng.choice(["MT", "MT", "WY"]), "Lat": lat, "Lon": lon,
                  "Comments": "x" * 140000 if rng.random() < 0.02 else "(BYZ)"}     # csv's field limit is 131072
        row = [values.get(c, "x") for c in cols]
        if rng.random() < 0.05:
            row = row[:rng.randint(0, len(row) - 1)]  # a short row
        rows.append(",".join(row))
    eol = "\r\n" if rng.random() < 0.3 else "\n"
    text = eol.join([",".join(cols)] + rows) + eol
    if rng.random() < 0.1:
        text = "\ufeff" + text                       # a byte order mark
    return kind, text


def spc_parse(case):
    kind, text = case
    return call(src.parse_spc, text, DAY, kind)


def check_spc_rows(case):
    rows, exc = spc_parse(case)
    if exc is not None:
        return None if module_error(exc) else unhandled(exc)
    for r in rows:
        if not (math.isfinite(r["lat"]) and math.isfinite(r["lon"])) or not src.near_montana(r["lat"], r["lon"]):
            return f"row kept at {r['lat']}, {r['lon']}"
        if not str(r["time"]).endswith("Z"):
            return f"time {r['time']!r}"
    return None


def check_spc_hail(case):
    rows, exc = spc_parse(case)
    if exc is not None:
        return None                                # check_spc_rows reports these
    for r in rows:
        if r["size_in"] is not None and not 0 <= r["size_in"] <= 10:
            return f"hail {r['size_in']} in"
    return None


def check_spc_wind(case):
    rows, exc = spc_parse(case)
    if exc is not None:
        return None
    for r in rows:
        if r["mph"] is not None and type(r["mph"]) is not int:
            return f"wind {r['mph']!r} is not an integer"
    return None


def check_spc_unique(case):
    rows, exc = spc_parse(case)
    if exc is not None:
        return None
    keys = [(r["kind"], r["time"], round(r["lat"], 2), round(r["lon"], 2)) for r in rows]
    return "a duplicate report was kept" if len(set(keys)) != len(keys) else None


def check_spc_line_endings(case):
    """The same file with CRLF or LF line endings must give the same rows (or the same error)."""
    kind, text = case
    a, ea = call(src.parse_spc, text, DAY, kind)
    b, eb = call(src.parse_spc, text.replace("\r\n", "\n"), DAY, kind)
    if (ea is None, type(ea), a) != (eb is None, type(eb), b):
        return "CRLF and LF files read differently"
    return None


class SpcRobustness(Checks):
    @unittest.expectedFailure
    def test_spc_rows_are_skipped_or_the_module_error_is_raised(self):
        # Smallest failing input: the file "Time,Size,Location,County,State,Lat,Lon,Comments" plus the
        # row "2215,²,X,X,MT,46.96,-104.16," (a hail file). int("²") raises ValueError, which is Python's
        # and not the module's, so the whole file is dropped instead of one row. Also: a Comments field
        # of 140,000 characters makes csv raise csv.Error, which build.py does not catch: the build stops.
        self.expect_clean({"parse_spc": sweep("spc", spc_case, check_spc_rows)})

    @unittest.expectedFailure
    def test_hail_sizes_stay_between_0_and_10_inches(self):
        # Smallest failing input: the same file with the row "2215,1001,X,X,MT,46.96,-104.16,"
        # (10.01 in, returned as is).
        self.expect_clean({"parse_spc": sweep("spc", spc_case, check_spc_hail)})

    def test_wind_is_an_integer_mph_or_none(self):
        self.expect_clean({"parse_spc": sweep("spc", spc_case, check_spc_wind)})

    def test_reports_are_unique(self):
        self.expect_clean({"parse_spc": sweep("spc", spc_case, check_spc_unique)})

    def test_line_endings_do_not_change_the_rows(self):
        self.expect_clean({"parse_spc": sweep("spc", spc_case, check_spc_line_endings)})


# ---------------------------------------------------------------- NWS alerts

EVENTS = ["Tornado Warning", "Severe Thunderstorm Warning", "Winter Storm Watch", "Wind Advisory",
          "Special Weather Statement", "Test Message", "", None, 5, ["Tornado Warning"]]
DATES = ["2026-10-14T15:00:00Z", "2026-10-14T09:00:00-06:00", "2026-10-14T15:00:00+00:00", "2026-13-45T00:00:00Z",
         "tomorrow", "", None, 1789, "9999-12-31T23:30:00-01:00", "0001-01-01T00:00:00+01:00"]
GEOMETRY = [SQUARE, None, {"type": "Point", "coordinates": [-110, 45]}, {"type": "Polygon", "coordinates": "x"},
            {"type": "MultiPolygon", "coordinates": []}, "junk", 5, {}]
REFERENCES = [[], None, [{"identifier": "urn:0"}], [{"identifier": ""}], [{"identifier": None}], [5], 5, "junk",
              [{"identifier": ["urn:x"]}]]


TEXT_EVENTS = [e for e in EVENTS if isinstance(e, str)]
DATES_SAFE = [d for d in DATES if not str(d).startswith(("0001", "9999"))]     # those overflow: a crash case
REFERENCES_SAFE = [[], None, [{"identifier": "urn:0"}], [{"identifier": ""}], [{"identifier": None}]]


def alert_feature(rng, i, junk=True):
    """One alert. junk=False keeps the fields the crash check covers (id, event, description,
    references, year-1 and year-9999 dates) well formed, so the shape check gets real records; the
    other fields still vary: status, messageType, severity, geometry, malformed dates, missing keys."""
    if junk:
        props = {"id": rng.choice([f"urn:{i}", f"urn:{i}", "", None, 7, ["urn:x"]]), "event": rng.choice(EVENTS),
                 "description": rng.choice(["Hail.", None, 5]), "references": rng.choice(REFERENCES),
                 "sent": rng.choice(DATES), "onset": rng.choice(DATES),
                 "ends": rng.choice(DATES), "expires": rng.choice(DATES)}
    else:
        props = {"id": rng.choice([f"urn:{i}", f"urn:{i}", "", None]), "event": rng.choice(TEXT_EVENTS),
                 "description": rng.choice(["Hail.", None]), "references": rng.choice(REFERENCES_SAFE),
                 "sent": rng.choice(DATES_SAFE), "onset": rng.choice(DATES_SAFE),
                 "ends": rng.choice(DATES_SAFE), "expires": rng.choice(DATES_SAFE)}
    props.update({
        "status": rng.choice(["Actual"] * 6 + ["Test", "Exercise", None]),
        "messageType": rng.choice(["Alert"] * 4 + ["Update", "Cancel", "Ack", None, 3]),
        "headline": rng.choice(["Warning text", None, 5]),
        "areaDesc": rng.choice(["Big Horn", None]),
        "severity": rng.choice(["Extreme", "Severe", "Unknown", "", None, 7, ["x"]]),
        "instruction": rng.choice(["Get inside.", None]),
    })
    for key in list(props):
        if rng.random() < 0.15:
            del props[key]                         # a missing key
    feature = {"type": "Feature", "id": f"urn:{i}", "geometry": rng.choice(GEOMETRY), "properties": props}
    if junk and rng.random() < 0.03:
        feature["properties"] = rng.choice([None, "x"])
    return feature


def alert_case(rng, junk=True):
    if junk and rng.random() < 0.04:
        return rng.choice([None, [], "x", {"features": None}, {"features": "x"}, {"features": [None]}])
    return {"features": [alert_feature(rng, i, junk) for i in range(rng.randint(0, 5))]}


def shape_case(rng):
    return alert_case(rng, junk=False)


def check_alert_crash(doc):
    _, exc = call(src.parse_alerts, doc)
    if exc is None or module_error(exc):
        return None
    return unhandled(exc)


def check_alert_shape(doc):
    recs, exc = call(src.parse_alerts, doc)
    if exc is not None:
        return None
    for r in recs:
        if r["kind"] not in KINDS:
            return f"kind {r['kind']!r}"
        if not isinstance(r["event"], str):
            return f"event {r['event']!r}"
        geom = r["geometry"]
        if geom is not None and (not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon")):
            return f"geometry {short(geom, 60)}"
        for k in ("sent", "onset", "until"):
            if r[k] is not None and not str(r[k]).endswith("Z"):
                return f"{k} {r[k]!r} is not UTC"
    keys = [src.alert_order(r) for r in recs]
    return None if keys == sorted(keys) else "not most urgent first"


class AlertRobustness(Checks):
    @unittest.expectedFailure
    def test_alerts_return_records_or_the_module_error_only(self):
        # Smallest failing input: {"features": [{"properties": {"status": "Actual", "event": 5}}]}
        # -> AttributeError (alert_kind calls .lower()). Other failures in the same 200 inputs:
        # a list as id or as a reference identifier -> TypeError (set membership); references that
        # are not a list -> TypeError; a non-text description -> AttributeError; a date in year 1
        # or 9999 with an offset -> OverflowError inside parse_iso.
        self.expect_clean({"parse_alerts": sweep("alerts", alert_case, check_alert_crash)})

    def test_alert_records_have_a_known_kind_and_plain_fields(self):
        self.expect_clean({"parse_alerts": sweep("shape", shape_case, check_alert_shape)})


# ---------------------------------------------------------------- forecast and station values

def point_doc():
    base = f"{src.NWS}/gridpoints/BYZ/1,1"
    return {"properties": {"forecast": base + "/forecast", "forecastHourly": base + "/forecast/hourly",
                           "forecastGridData": base, "observationStations": base + "/stations", "gridId": "BYZ",
                           "gridX": 1, "gridY": 1, "timeZone": "America/Denver",
                           "relativeLocation": {"properties": {"city": "Billings", "state": "MT"}}}}


def hourly_doc():
    periods = [{"startTime": f"2026-10-14T{h:02d}:00:00-06:00", "temperature": 50, "temperatureUnit": "F",
                "windSpeed": "10 to 15 mph", "windDirection": "W", "isDaytime": True,
                "probabilityOfPrecipitation": {"value": 20}, "shortForecast": "Sunny"} for h in (15, 16, 17)]
    return {"properties": {"updateTime": "2026-10-14T12:00:00Z", "periods": periods}}


def gridpoint_doc():
    """The gridpoint document: the grid elevation and the windGust series (km/h)."""
    return {"properties": {"elevation": {"unitCode": "wmoUnit:m", "value": 1088},
                           "windGust": {"uom": "wmoUnit:km_h-1", "values": [
                               {"validTime": "2026-10-14T15:00:00+00:00/PT3H", "value": 40.2},
                               {"validTime": "2026-10-14T18:00:00+00:00/PT1H", "value": 20}]}}}


def daily_doc():
    def period(name, day, temp, pop):
        return {"name": name, "startTime": "2026-10-14T06:00:00-06:00", "isDaytime": day,
                "temperature": temp, "temperatureUnit": "F", "windSpeed": "5 to 10 mph", "windDirection": "W",
                "probabilityOfPrecipitation": {"value": pop}, "shortForecast": "Sunny", "detailedForecast": ""}
    return {"properties": {"periods": [period("Today", True, 60, 10), period("Tonight", False, 35, 0)]}}


def stations_doc():
    feats = [{"geometry": {"type": "Point", "coordinates": [-111.0 - i * 0.1, 44.6]},
              "properties": {"stationIdentifier": f"K{i}", "name": f"STATION {i}",
                             "elevation": {"unitCode": "wmoUnit:m", "value": 1100},
                             "county": f"{src.NWS}/zones/county/MTC111"}} for i in range(3)]
    return {"type": "FeatureCollection", "features": feats}


def obs_doc():
    return {"properties": {
        "timestamp": (NOW - timedelta(minutes=10)).isoformat(), "textDescription": "Clear",
        "elevation": {"unitCode": "wmoUnit:m", "value": 1088},
        "temperature": {"unitCode": "wmoUnit:degC", "value": 5.0, "qualityControl": "V"},
        "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": 16.7, "qualityControl": "V"},
        "windGust": {"unitCode": "wmoUnit:km_h-1", "value": None, "qualityControl": "Z"},
        "windDirection": {"unitCode": "wmoUnit:degree_(angle)", "value": 190, "qualityControl": "V"}}}


# Each parser with the document it reads and how the build calls it.
PARSERS = [
    ("parse_point", point_doc, src.parse_point),
    ("parse_hourly", hourly_doc, src.parse_hourly),
    ("parse_gusts", gridpoint_doc, src.parse_gusts),
    ("grid_elevation_ft", gridpoint_doc, src.grid_elevation_ft),
    ("parse_daily", daily_doc, src.parse_daily),
    ("parse_stations", stations_doc, lambda d: src.parse_stations(d, 44.66, -111.10)),
    ("parse_observation", obs_doc, lambda d: src.parse_observation(d, NOW)),
]


def check_only_module_error(parse, doc):
    _, exc = call(parse, doc)
    if exc is None or module_error(exc):
        return None
    return unhandled(exc)


def missing_case(rng):
    """Documents with some values null or left out, and the value each must read as."""
    hourly, want = hourly_doc(), {"temp": [], "wind": [], "precip": []}
    periods = []
    for h in (15, 16, 17):
        t = rng.choice([50, 20.0, None, ABSENT])
        w, w_want = rng.choice([("10 mph", 10), ("10 to 15 mph", 15), ("", None), (None, None)])
        q = rng.choice([40, 0, None, ABSENT])
        p = {"startTime": f"2026-10-14T{h:02d}:00:00-06:00", "temperatureUnit": "F", "isDaytime": True,
             "shortForecast": "Sunny"}                 # no value keys: each one is put in or left out below
        put(p, "temperature", t)
        put(p, "windSpeed", w)
        put(p, "probabilityOfPrecipitation", ABSENT if q is ABSENT else {"value": q})
        periods.append(p)
        want["temp"].append(None if t in (None, ABSENT) else t)
        want["wind"].append(w_want)
        want["precip"].append(None if q in (None, ABSENT) else q)
    hourly["properties"]["periods"] = periods
    gust_items, want_gust = [], {}
    for h in (15, 16, 17):
        v = rng.choice([40.2, None, ABSENT])
        item = {"validTime": f"2026-10-14T{h:02d}:00:00+00:00/PT1H"}
        put(item, "value", v)
        gust_items.append(item)
        want_gust[datetime(2026, 10, 14, h, tzinfo=UTC)] = (None if v in (None, ABSENT)
                                                              else int(v * src.KMH_TO_MPH + 0.5))
    gusts = {"properties": {"windGust": {"uom": "wmoUnit:km_h-1", "values": gust_items}}}
    obs, tv, wv, gv = obs_doc(), rng.choice([5.0, None]), rng.choice([16.7, None]), rng.choice([15.0, None])
    obs["properties"]["temperature"]["value"] = tv
    obs["properties"]["windSpeed"]["value"] = wv
    obs["properties"]["windGust"]["value"] = gv
    return {"hourly": (hourly, want), "gusts": (gusts, want_gust), "obs": (obs, (tv, wv, gv))}


def check_missing(case):
    hourly, want = case["hourly"]
    out, exc = call(src.parse_hourly, hourly)
    if exc is not None:
        return failed(exc)
    got = {"temp": [h["temp_f"] for h in out[0]], "wind": [h["wind_mph"] for h in out[0]],
           "precip": [h["precip"] for h in out[0]]}
    for k in got:
        if any(not same(a, b) for a, b in zip(got[k], want[k])):
            return f"hourly {k}: got {got[k]}, want {want[k]}"
    gusts, want_gust = case["gusts"]
    values, exc = call(src.parse_gusts, gusts)
    if exc is not None:
        return failed(exc)
    for hour, expected in want_gust.items():
        if not same(values.get(hour), expected):
            return f"gust at {hour:%H}:00 is {values.get(hour)!r}, want {expected!r}"
    obs, (tv, wv, gv) = case["obs"]
    r, exc = call(src.parse_observation, obs, NOW)
    if exc is not None:
        return None if (tv, wv, gv) == (None, None, None) and module_error(exc) else failed(exc)
    if not same(r["temp"]["value"], None if tv is None else tv * 9 / 5 + 32):
        return f"observation temperature {r['temp']['value']!r}"
    if not same(r["wind"]["value"], None if wv is None else wv * src.KMH_TO_MPH):
        return f"observation wind {r['wind']['value']!r}"
    if not same(r["gust"]["value"], None if gv is None else gv * src.KMH_TO_MPH):
        return f"observation gust {r['gust']['value']!r}"
    return None


def nonnumber_case(rng):
    """One document with one number slot holding something that is not a number."""
    kind = rng.choice(["temperature", "pop", "wind", "daily pop", "gust"])
    junk = copy.deepcopy(rng.choice(WIND_SLOT_JUNK if kind == "wind" else NUMBER_SLOT_JUNK))
    if kind == "gust":
        doc = gridpoint_doc()
        doc["properties"]["windGust"]["values"][0]["value"] = junk
    elif kind == "daily pop":
        doc = daily_doc()
        doc["properties"]["periods"][0]["probabilityOfPrecipitation"] = {"value": junk}
    else:
        doc = hourly_doc()
        p = doc["properties"]["periods"][0]
        if kind == "temperature":
            p["temperature"] = junk
        elif kind == "pop":
            p["probabilityOfPrecipitation"] = {"value": junk}
        else:
            p["windSpeed"] = junk
    return kind, doc


def check_nonnumber(case):
    kind, doc = case
    if kind == "gust":
        values, exc = call(src.parse_gusts, doc)
        got = None if exc or values is None else values.get(START)
    elif kind == "daily pop":
        rows, exc = call(src.parse_daily, doc)
        got = None if exc else rows[0]["precip"]
    else:
        out, exc = call(src.parse_hourly, doc)
        first = None if exc else out[0][0]
        got = None if exc else {"temperature": first["temp_f"], "pop": first["precip"],
                                "wind": first["wind_mph"]}[kind]
    if exc is not None:
        return None                                # check_only_module_error reports these
    return None if got is None else f"{kind} slot read as {got!r}"


def unit_case(rng):
    """An hourly period with one temperature unit and one wind text, and what each must read as."""
    unit = rng.choice(["F", "C", "K", "degF", "degC", ""])
    text = rng.choice(["10 mph", "10 to 15 mph", "16 km/h", "9 kt", "3 m/s", ""])
    doc = hourly_doc()
    p = doc["properties"]["periods"][0]
    p["temperature"], p["temperatureUnit"], p["windSpeed"] = 20, unit, text
    want_t = {"F": 20, "C": 68.0}.get(unit)
    want_w = {"10 mph": 10, "10 to 15 mph": 15}.get(text)
    return unit, text, doc, want_t, want_w


def check_hourly_units(case):
    unit, text, doc, want_t, want_w = case
    out, exc = call(src.parse_hourly, doc)
    if exc is not None:
        return failed(exc)
    first = out[0][0]
    if not same(first["temp_f"], want_t):
        return f"temperature unit {unit!r} read as {first['temp_f']!r}"
    if not same(first["wind_mph"], want_w):
        return f"wind text {text!r} read as {first['wind_mph']!r} mph"
    return None


def gust_unit_case(rng):
    uom = rng.choice(["wmoUnit:km_h-1", "wmoUnit:m_s-1", "wmoUnit:mi_h-1", "wmoUnit:kt", ""])
    doc = gridpoint_doc()
    doc["properties"]["windGust"]["uom"] = uom
    factor = {"wmoUnit:km_h-1": src.KMH_TO_MPH, "wmoUnit:m_s-1": src.MS_TO_MPH}.get(uom)
    return uom, doc, factor


def check_gust_units(case):
    uom, doc, factor = case
    values, exc = call(src.parse_gusts, doc)
    if factor is None:
        if exc is None:
            return f"gust unit {uom!r} read as numbers"
        return None if module_error(exc) else unhandled(exc)
    if exc is not None:
        return failed(exc)
    if values.get(START) != int(40.2 * factor + 0.5):
        return f"gust unit {uom!r} read as {values.get(START)!r}"
    return None


def obs_unit_case(rng):
    tu = rng.choice(["wmoUnit:degC", "wmoUnit:degF", "wmoUnit:K", "wmoUnit:degR", ""])
    wu = rng.choice(["wmoUnit:km_h-1", "wmoUnit:m_s-1", "wmoUnit:kt", "wmoUnit:mi_h-1",
                     "wmoUnit:furlong_fortnight-1", ""])
    doc = obs_doc()
    doc["properties"]["temperature"] = {"unitCode": tu, "value": 5.0, "qualityControl": "V"}
    doc["properties"]["windSpeed"] = {"unitCode": wu, "value": 16.7, "qualityControl": "V"}
    return tu, wu, doc


def check_obs_units(case):
    tu, wu, doc = case
    known_t = tu in ("wmoUnit:degC", "wmoUnit:degF")
    known_w = wu in ("wmoUnit:km_h-1", "wmoUnit:m_s-1", "wmoUnit:kt", "wmoUnit:mi_h-1")
    r, exc = call(src.parse_observation, doc, NOW)
    if not (known_t and known_w):
        return None if exc is not None and module_error(exc) else f"units {tu!r}, {wu!r} read as values"
    if exc is not None:
        return failed(exc)
    want_t = 5.0 * 9 / 5 + 32 if tu == "wmoUnit:degC" else 5.0
    factor = {"wmoUnit:km_h-1": src.KMH_TO_MPH, "wmoUnit:m_s-1": src.MS_TO_MPH,
              "wmoUnit:kt": src.KT_TO_MPH, "wmoUnit:mi_h-1": 1.0}[wu]
    if not same(r["temp"]["value"], want_t) or not same(r["wind"]["value"], 16.7 * factor):
        return f"units {tu!r}, {wu!r} read as {r['temp']['value']!r}, {r['wind']['value']!r}"
    return None


def big_case(rng):
    hourly = hourly_doc()
    hourly["properties"]["periods"][0]["windSpeed"] = rng.choice(["9" * 309, "10 mph"])
    obs = obs_doc()
    obs["properties"]["temperature"]["value"] = rng.choice([1e308, 5.0])
    obs["properties"]["windSpeed"] = {"unitCode": "wmoUnit:m_s-1", "value": rng.choice([1e308, 16.7]),
                                      "qualityControl": "V"}
    return hourly, obs


def check_finite(case):
    hourly, obs = case
    out, exc = call(src.parse_hourly, hourly)
    if exc is None:
        for key in ("temp_f", "wind_mph", "precip"):
            v = out[0][0][key]
            if v is not None and not math.isfinite(v):
                return f"hourly {key} {v}"
    r, exc = call(src.parse_observation, obs, NOW)
    if exc is None:
        for key in ("temp", "wind", "gust"):
            v = r[key]["value"]
            if v is not None and not math.isfinite(v):
                return f"observation {key} {v}"
    return None


class ForecastAndStationRobustness(Checks):
    def test_missing_values_come_back_none_never_zero(self):
        self.expect_clean({"hourly, gusts, observation": sweep("missing", missing_case, check_missing)})

    @unittest.expectedFailure
    def test_only_the_module_error_escapes_the_forecast_and_station_parsers(self):
        # Smallest failing input: src.parse_point(1) -> AttributeError (the document is not a dict).
        # parse_point, parse_hourly, parse_gusts, grid_elevation_ft and parse_daily fail the same way;
        # parse_stations and parse_observation check the type and raise the module's own error.
        # Also: a windGust "values" that is a number -> TypeError; a gust value of inf -> OverflowError,
        # NaN -> ValueError from int(); a non-dict item in periods -> AttributeError; an observation
        # timestamp in year 1 with an offset -> OverflowError.
        found = {}
        for name, base, parse in PARSERS:
            found[name] = sweep(name, lambda rng, base=base: mutated(rng, base()),
                                lambda doc, parse=parse: check_only_module_error(parse, doc))
        self.expect_clean(found)

    @unittest.expectedFailure
    def test_non_numbers_never_become_numbers(self):
        # Smallest failing input: a period with windSpeed [40] reads as 40 mph, because the text is
        # str()-ed. Also: probabilityOfPrecipitation {"value": true} reads as a chance of True (1),
        # and a gust value of true reads as 1 mph.
        self.expect_clean({"non-numbers": sweep("nonnumbers", nonnumber_case, check_nonnumber)})

    @unittest.expectedFailure
    def test_units_are_read_only_when_expected(self):
        # Smallest failing input: a period with windSpeed "16 km/h" reads as 16 mph. Also: temperature
        # 20 with temperatureUnit "K" (or "degF") reads as 68 °F, because anything that is not F is
        # treated as C.
        self.expect_clean({
            "hourly": sweep("hourly units", unit_case, check_hourly_units),
            "gusts": sweep("gust units", gust_unit_case, check_gust_units),
            "observation": sweep("obs units", obs_unit_case, check_obs_units),
        })

    @unittest.expectedFailure
    def test_numbers_that_leave_the_parsers_are_finite(self):
        # Smallest failing input: an observation with temperature {"unitCode": "wmoUnit:degC",
        # "value": 1e308}: the multiplication by 9 overflows to inf, and build.py's _round() then raises
        # OverflowError, which build.py does not catch. Also: a 309-digit windSpeed reads as inf.
        self.expect_clean({"forecast and observation": sweep("finite", big_case, check_finite)})


# ---------------------------------------------------------------- gridded files: index, listing, GRIB

KEYS = ["CONUS/PrecipRate_00.00/20261014/MRMS_PrecipRate_00.00_20261014-150000.grib2.gz",
        "CONUS/PrecipRate_00.00/20261014/MRMS_PrecipRate_00.00_20261014-151200.grib2.gz",
        "CONUS/PrecipRate_00.00/20261014/MRMS_PrecipRate_00.00_20261340-999999.grib2.gz",
        "CONUS/PrecipRate_00.00/20261014/other.txt",
        "CONUS/PrecipRate_00.00/20261014/MRMS_PrecipRate_00.00_20261014-1500&amp;00.grib2.gz"]


def idx_case(rng):
    lines = []
    for _ in range(rng.randint(0, 6)):
        if rng.random() < 0.1:
            lines.append("")
            continue
        parts = [rng.choice(["1", "2", "²", "", "x"]), rng.choice(["0", "1234", "²", "-1", "", "x", "00", "9" * 30]),
                 "d=2026101521", rng.choice(["UGRD", "PRATE", ""]), rng.choice(["10 m above ground", "surface"]),
                 rng.choice(["1 hour fcst", "anl", "15 min fcst"]), ""]
        if rng.random() < 0.1:
            parts = parts[:rng.randint(0, 5)]      # a short line
        lines.append(":".join(parts))
    return "\n".join(lines)


def check_idx(text):
    recs, exc = call(g.parse_idx, text)
    if exc is not None:
        return None if module_error(exc) else unhandled(exc)
    for r in recs:
        if not isinstance(r["offset"], int) or r["offset"] < 0:
            return f"offset {r['offset']!r}"
    return None


def listing_case(rng):
    keys = [rng.choice(KEYS) for _ in range(rng.randint(0, 6))]
    body = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys)
    truncated = rng.choice(["true", "false", "junk", ""])
    token = rng.choice(["", "tok&amp;1", "x"])
    xml = (f"<ListBucketResult>{body}<IsTruncated>{truncated}</IsTruncated>"
           + (f"<NextContinuationToken>{token}</NextContinuationToken>" if token else "") + "</ListBucketResult>")
    if rng.random() < 0.9:
        return xml.encode()
    return rng.choice([b"", b"\xff\xfe junk", b"<html>"])


def check_listing(data):
    out, exc = call(g.parse_listing, data)
    if exc is not None:
        return None if module_error(exc) else unhandled(exc)
    recs, _token = out
    times = [t for t, _ in recs]
    if times != sorted(times):
        return "file times not sorted"
    for t, key in recs:
        if t.utcoffset() != timedelta(0) or g.MRMS_KEY.search(key) is None:
            return f"kept {key!r}"
    return None


def grib_case(rng):
    total = rng.choice([0, 15, 16, 20, 40, 1 << 40, rng.randint(16, 200)])
    head = b"GRIB\x00\x00" + bytes([rng.randrange(3), rng.choice([2, 2, 1])]) + total.to_bytes(8, "big")
    body = bytes(rng.randrange(256) for _ in range(rng.randint(0, 120)))
    return head + body + (b"7777" if rng.random() < 0.5 else b"")


def check_grib(data):
    out, exc = call(g.grib_message, data)
    if exc is not None:
        return None if module_error(exc) else unhandled(exc)
    total = int.from_bytes(data[8:16], "big")
    if len(out) != total or not out.endswith(b"7777") or not out.startswith(b"GRIB"):
        return "returned bytes that are not a whole message"
    return None


class GriddedFileRobustness(Checks):
    @unittest.expectedFailure
    def test_index_lines_are_skipped_or_the_module_error_is_raised(self):
        # Smallest failing input: the index line "1:²:::::" (ValueError from int(); gridded.py catches
        # it one level up, so the whole HRRR run is discarded as unreadable).
        self.expect_clean({"parse_idx": sweep("idx", idx_case, check_idx)})

    def test_listing_keys_are_sorted_and_utc_or_the_module_error_is_raised(self):
        self.expect_clean({"parse_listing": sweep("listing", listing_case, check_listing)})

    def test_grib_bytes_are_a_whole_message_or_the_module_error_is_raised(self):
        self.expect_clean({"grib_message": sweep("grib", grib_case, check_grib)})


class HowErrorsAreTold(unittest.TestCase):
    def test_module_error_is_told_apart_from_python_errors(self):
        _, own = call(src.parse_spc, "<html>Not found</html>", DAY, "hail")
        _, stray = call(int, "²")                  # the error comes from int(), a Python function
        self.assertTrue(module_error(own))
        self.assertFalse(module_error(stray))
        self.assertFalse(module_error(None))


if __name__ == "__main__":
    unittest.main()
