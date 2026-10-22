#!/usr/bin/env python3
"""H1 prototype: a five-year daily hail-estimate store from NOAA MRMS MESH.

Input is the 12:00 UTC MESH_Max_1440min_00.50 file of each day. It holds the
24-hour maximum of MESH, a radar-based hail size estimate in millimetres (the
unit is read from the magnitudes, not from a unit field: see README.md). Each
file is stamped 12:00 UTC on day D and covers the window 12:00 UTC on D-1 to
12:00 UTC on D. That window is the SPC report day D-1 (AGENTS.md: SPC dates
follow 12:00 to 11:59 UTC reporting days), so this store is keyed by the SPC
report day and keeps the file stamp next to it.

Subcommands:
  fetch    download the 12:00 files; the IEM copy is tried when the bucket says 404
  decode   one file cut to the Montana cells (summary, optional .npz)
  build    all fetched days to the store (per-day arrays, events, counts, shards)
  lookup   a latitude and longitude to its cell and the stored radar estimates
  verify   Benchland and peak-day checks, a 2-minute frame comparison, code shares
  fixture  a small saved crop of one real file, used by the offline tests

Run as: python3 -I mesh_history.py COMMAND [options]   (see README.md)

This is not a damage record and not an inspection. A radar estimate at a cell
is not a measurement at an address. No report and no estimate do not mean no hail.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import re
import struct
import sys
import threading
import time
import zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------------------
# Sources and names
# ----------------------------------------------------------------------------
BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"
IEM = "https://mtarchive.geol.iastate.edu"
PRODUCT = "MESH_Max_1440min_00.50"     # 24-hour maximum, one file every 30 minutes
PRODUCT_2MIN = "MESH_00.50"            # 2-minute MESH frames (IEM folder MESH/)
USER_AGENT = "montana-hail-watch-h1-prototype/0.1 (research)"
MAX_WORKERS = 4                         # ceiling on concurrent network requests

DEFAULT_START = "2020-10-14"            # 12:00 UTC file dates (stamps), as requested
DEFAULT_END = "2026-10-16"
FIVE_YEAR_STAMPS = ("2021-10-17", "2026-10-16")

# ----------------------------------------------------------------------------
# Grid: 7000 x 3500 points at 0.01 degree, from the GRIB2 header of every file.
# Row 0 is the northern edge (jScansPositively 0). Column 0 is 230.005 east.
# Coordinates are kept in thousandths of a degree so the cut-offs are exact.
# ----------------------------------------------------------------------------
NI, NJ = 7000, 3500
STEP_E3 = 10
ROW0_LAT_E3 = 54995
COL0_LON_E3 = -129995
FRAME_LAT_E3 = (43000, 50500)           # the decode frame box from the brief
FRAME_LON_E3 = (-118500, -101000)
TILE = 10                               # grid cells per shard side (0.1 degree)
EARTH_R_KM = 6371.0088

# ----------------------------------------------------------------------------
# Units and thresholds. Stored values are tenths of a mm. One inch is 25.4 mm,
# so each inch cut-off is an exact integer in hundredths of a mm.
# ----------------------------------------------------------------------------
INCH_CLASSES = (0.25, 0.75, 1.00, 1.50, 2.00)
EVENT_MIN_INCH = 0.25


def inch_threshold_tenths(inches: float) -> int:
    """Smallest stored value (tenths of a mm) at or above `inches`."""
    hundredths_mm = round(inches * 2540)          # 1 inch = 2540 hundredths of a mm
    return -(-hundredths_mm // 10)                # ceiling division by 10


THRESH = {f"{c:.2f}": inch_threshold_tenths(c) for c in INCH_CLASSES}
EVENT_MIN_TENTHS = inch_threshold_tenths(EVENT_MIN_INCH)   # 64: raw 6.35 mm or more


def mm_to_inch(mm: float) -> float:
    return mm / 25.4


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_day(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def day_range(start: dt.date, end: dt.date):
    for i in range((end - start).days + 1):
        yield start + dt.timedelta(days=i)


def stamp_of_day(spc_day: dt.date) -> dt.date:
    """The 12:00 UTC file stamped D+1 holds SPC report day D."""
    return spc_day + dt.timedelta(days=1)


def day_of_stamp(stamp: dt.date) -> dt.date:
    """The SPC report day covered by the 12:00 UTC file stamped `stamp`."""
    return stamp - dt.timedelta(days=1)


def bucket_name(stamp: dt.date) -> str:
    return f"MRMS_{PRODUCT}_{stamp:%Y%m%d}-120000.grib2.gz"


def bucket_url(stamp: dt.date) -> str:
    return f"{BUCKET}/CONUS/{PRODUCT}/{stamp:%Y%m%d}/{bucket_name(stamp)}"


def iem_url(stamp: dt.date) -> str:
    # IEM names the folder without the "_00.50" suffix; the file keeps it.
    return f"{IEM}/{stamp:%Y/%m/%d}/mrms/ncep/MESH_Max_1440min/{PRODUCT}_{stamp:%Y%m%d}-120000.grib2.gz"


def shard_name(row: int, col: int) -> str:
    """Event shard for the 0.1 degree tile holding global grid cell (row, col)."""
    return f"r{row // TILE:04d}_c{col // TILE:04d}.json.gz"


def in_five_years(day_iso: str) -> bool:
    """True for SPC report days whose 12:00 UTC file is in the five-year stamp window."""
    stamp = stamp_of_day(dt.date.fromisoformat(day_iso))
    lo, hi = (dt.date.fromisoformat(x) for x in FIVE_YEAR_STAMPS)
    return lo <= stamp <= hi


def five_year_spc_days():
    """The five-year window expressed as SPC report days (first and last)."""
    lo, hi = (dt.date.fromisoformat(x) for x in FIVE_YEAR_STAMPS)
    return day_of_stamp(lo).isoformat(), day_of_stamp(hi).isoformat()


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=np.float64)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(a))


def frame_box():
    rows = [r for r in range(NJ) if FRAME_LAT_E3[0] <= ROW0_LAT_E3 - STEP_E3 * r <= FRAME_LAT_E3[1]]
    cols = [c for c in range(NI) if FRAME_LON_E3[0] <= COL0_LON_E3 + STEP_E3 * c <= FRAME_LON_E3[1]]
    assert rows == list(range(rows[0], rows[-1] + 1)) and cols == list(range(cols[0], cols[-1] + 1))
    return rows[0], len(rows), cols[0], len(cols)


# ----------------------------------------------------------------------------
# Montana mask
# ----------------------------------------------------------------------------
def load_state_ring(basemap_path: str | Path):
    """The Montana land polygon (properties.montana true) from the website basemap."""
    data = json.loads(Path(basemap_path).read_text(encoding="utf-8"))
    hits = [f for f in data["land"]["features"] if f.get("properties", {}).get("montana") is True]
    if len(hits) != 1 or hits[0]["geometry"]["type"] != "Polygon":
        raise ValueError("expected exactly one Montana Polygon in land features")
    rings = hits[0]["geometry"]["coordinates"]
    if len(rings) != 1:
        raise ValueError("expected a single ring for Montana")
    return [(float(x), float(y)) for x, y in rings[0]]


def polygon_masks(ring, row0: int, nrow: int, col0: int, ncol: int):
    """Strict and inclusive masks of grid cell centres inside the ring.

    Even-odd crossing test on the cell centres. A centre exactly on an edge is
    outside the strict mask and inside the inclusive mask. The strict mask is the
    rule used for the store (450,765 cells); the inclusive one is kept to size the
    tie cells on the Montana east edge (lon -104.045).
    """
    rows = np.arange(row0, row0 + nrow)
    cols = np.arange(col0, col0 + ncol)
    lat = (ROW0_LAT_E3 - STEP_E3 * rows).astype(np.float64) / 1000.0
    lon = (COL0_LON_E3 + STEP_E3 * cols).astype(np.float64) / 1000.0
    Y = lat[:, None]
    X = lon[None, :]
    inside = np.zeros((nrow, ncol), dtype=bool)
    on_edge = np.zeros((nrow, ncol), dtype=bool)
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if y1 == y2:
            continue
        cross = (y1 > Y) != (y2 > Y)                       # half-open in latitude
        if not cross.any():
            continue
        xi = x1 + (Y - y1) * ((x2 - x1) / (y2 - y1))       # longitude where the edge crosses this row
        inside ^= cross & (X < xi)                         # crossings east of the centre
        on_edge |= cross & (X == xi)
    return inside & ~on_edge, inside | on_edge


class Grid:
    """A rectangle of the MRMS grid with a boolean mask. Cell order is row-major."""

    def __init__(self, row0: int, col0: int, mask: np.ndarray):
        self.row0 = int(row0)
        self.col0 = int(col0)
        self.mask = np.ascontiguousarray(mask, dtype=bool)
        self.nrow, self.ncol = self.mask.shape
        flat = np.flatnonzero(self.mask)
        self.n = int(flat.size)
        index = np.full(self.mask.size, -1, dtype=np.int32)
        index[flat] = np.arange(self.n, dtype=np.int32)
        self.index_map = index.reshape(self.mask.shape)
        rr, cc = np.divmod(flat, self.ncol)
        self.rows = (rr + self.row0).astype(np.int32)      # global grid rows
        self.cols = (cc + self.col0).astype(np.int32)      # global grid columns
        self.lat = (ROW0_LAT_E3 - STEP_E3 * self.rows.astype(np.float64)) / 1000.0
        self.lon = (COL0_LON_E3 + STEP_E3 * self.cols.astype(np.float64)) / 1000.0

    def index_of(self, row: int, col: int) -> int:
        r, c = row - self.row0, col - self.col0
        if 0 <= r < self.nrow and 0 <= c < self.ncol:
            return int(self.index_map[r, c])
        return -1


def montana_grid(basemap_path: str | Path, inclusive: bool = False) -> Grid:
    row0, nrow, col0, ncol = frame_box()
    strict, incl = polygon_masks(load_state_ring(basemap_path), row0, nrow, col0, ncol)
    return Grid(row0, col0, incl if inclusive else strict)


# ----------------------------------------------------------------------------
# Reading GRIB2 and packing values
# ----------------------------------------------------------------------------
def gz_is_grib(path: Path):
    """Check a .grib2.gz file: gzip magic, a complete stream, GRIB at the start and 7777 at the end."""
    with open(path, "rb") as f:
        if f.read(2) != b"\x1f\x8b":
            return False, "no gzip magic"
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    head = b""
    tail = b""
    size = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                out = d.decompress(chunk)
                size += len(out)
                if len(head) < 4:
                    head = (head + out)[:4]
                tail = (tail + out)[-4:]
            out = d.flush()
            size += len(out)
            tail = (tail + out)[-4:]
    except zlib.error as exc:
        return False, f"gzip error: {exc}"
    if not d.eof:
        return False, "truncated gzip stream"
    if head != b"GRIB" or tail != b"7777":
        return False, "not a single GRIB2 message"
    return True, f"{size} bytes uncompressed"


def read_mesh_file(path: str | Path):
    """Decode one MESH GRIB2 file. Returns (values as float64 [NJ, NI], header metadata)."""
    import pygrib  # imported here so the offline tests do not need it

    raw = gzip.decompress(Path(path).read_bytes())
    if raw[:4] != b"GRIB":
        raise ValueError(f"{path}: not a GRIB2 message")
    msg = pygrib.fromstring(raw)
    values = msg.values
    if np.ma.isMaskedArray(values) and np.ma.count_masked(values):
        raise ValueError(f"{path}: bitmap has missing points; not expected for MESH")
    values = np.asarray(np.ma.getdata(values), dtype=np.float64)
    if values.shape != (NJ, NI):
        raise ValueError(f"{path}: grid {values.shape}, expected {(NJ, NI)}")
    meta = {k: (msg[k].item() if hasattr(msg[k], "item") else msg[k])
            for k in ("dataDate", "dataTime", "parameterNumber", "units", "bitsPerValue",
                      "packingType", "Ni", "Nj", "jScansPositively", "stepRange")}
    return values, meta


def crop_values(values: np.ndarray, grid: Grid, origin_row: int = 0, origin_col: int = 0) -> np.ndarray:
    """Raw values of the grid's cells from an array whose [0, 0] is (origin_row, origin_col)."""
    r0, c0 = grid.row0 - origin_row, grid.col0 - origin_col
    sub = values[r0:r0 + grid.nrow, c0:c0 + grid.ncol]
    if sub.shape != grid.mask.shape:
        raise ValueError(f"array does not cover the grid window: got {sub.shape}")
    return np.asarray(sub, dtype=np.float64)[grid.mask]


def pack_tenths(raw: np.ndarray):
    """Raw MESH values (mm) to uint16 tenths of a mm, with 0 for no data.

    Negative codes (-1, -3 and any others) and NaN are no data. Nothing is
    clamped: a value above the uint16 range raises. Exact zero is stored as 0,
    which is also no data; it is counted separately (n_zero).
    """
    raw = np.asarray(raw, dtype=np.float64)
    nan = np.isnan(raw)
    pos = raw > 0
    tenths_f = np.where(pos, np.rint(raw * 10.0), 0.0)
    top = float(tenths_f.max()) if tenths_f.size else 0.0
    if top > 65535:
        raise ValueError(f"value {top / 10:.1f} mm is above the uint16 range; not clamped")
    tenths = tenths_f.astype(np.uint16)
    stats = {
        "n_cells": int(raw.size),
        "n_pos": int(np.count_nonzero(tenths)),
        "n_pos_lost": int(np.count_nonzero(pos & (tenths == 0))),
        "n_minus1": int(np.count_nonzero(raw == -1.0)),
        "n_minus3": int(np.count_nonzero(raw == -3.0)),
        "n_other_neg": int(np.count_nonzero((raw < 0) & (raw != -1.0) & (raw != -3.0))),
        "n_nan": int(np.count_nonzero(nan)),
        "n_zero": int(np.count_nonzero(raw == 0.0)),
        "max_mm": round(float(raw[pos].max()), 4) if pos.any() else None,
        "quant_max_err_tenths": (float(np.abs(tenths_f[pos] - raw[pos] * 10.0).max()) if pos.any() else 0.0),
    }
    for c in INCH_CLASSES:
        stats[f"n_ge_{c:.2f}"] = int(np.count_nonzero(tenths >= THRESH[f"{c:.2f}"]))
    return tenths, stats


def encode_tenths(tenths: np.ndarray) -> bytes:
    """One day as bytes: a format byte, then the smaller of dense and sparse zlib."""
    dense = zlib.compress(tenths.astype("<u2").tobytes(), 9)
    idx = np.flatnonzero(tenths)
    if idx.size:
        gaps = (np.diff(idx, prepend=-1) - 1).astype("<u4")
        body = gaps.tobytes() + tenths[idx].astype("<u2").tobytes()
    else:
        body = b""
    sparse = struct.pack("<I", int(idx.size)) + zlib.compress(body, 9)
    if len(sparse) < len(dense):
        return b"\x01" + sparse
    return b"\x00" + dense


def decode_tenths(blob: bytes, n: int) -> np.ndarray:
    enc, body = blob[0], blob[1:]
    if enc == 0:
        arr = np.frombuffer(zlib.decompress(body), dtype="<u2").astype(np.uint16)
        if arr.size != n:
            raise ValueError(f"dense day has {arr.size} cells, expected {n}")
        return arr
    if enc == 1:
        (count,) = struct.unpack("<I", body[:4])
        raw = zlib.decompress(body[4:])
        gaps = np.frombuffer(raw[: 4 * count], dtype="<u4").astype(np.int64)
        vals = np.frombuffer(raw[4 * count:], dtype="<u2")
        out = np.zeros(n, dtype=np.uint16)
        if count:
            out[np.cumsum(gaps + 1) - 1] = vals
        return out
    raise ValueError(f"unknown day encoding {enc}")


# ----------------------------------------------------------------------------
# fetch
# ----------------------------------------------------------------------------
_tls = threading.local()


def _session():
    import requests

    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers["User-Agent"] = USER_AGENT
        _tls.session = sess
    return sess


def get_to_file(url: str, dest: Path, max_tries: int = 4) -> dict:
    """GET url into dest through a .part file. Retries 429, 5xx and network errors."""
    import requests

    part = dest.with_name(dest.name + ".part")
    last_err = None
    for attempt in range(1, max_tries + 1):
        try:
            with _session().get(url, stream=True, timeout=(20, 180)) as resp:
                status = resp.status_code
                if status != 200:
                    if status == 429 or status >= 500:
                        last_err = f"HTTP {status}"
                        time.sleep(2 ** attempt)
                        continue
                    return {"http_status": status, "error": None if status == 404 else f"HTTP {status}"}
                digest = hashlib.sha256()
                nbytes = 0
                with open(part, "wb") as fh:
                    for chunk in resp.iter_content(1 << 20):
                        if chunk:
                            fh.write(chunk)
                            digest.update(chunk)
                            nbytes += len(chunk)
                last_modified = resp.headers.get("Last-Modified")
            ok, detail = gz_is_grib(part)
            if not ok:
                part.unlink(missing_ok=True)
                last_err = f"invalid file: {detail}"
                time.sleep(2 ** attempt)
                continue
            os.replace(part, dest)
            return {"http_status": 200, "bytes": nbytes, "sha256": digest.hexdigest(),
                    "last_modified": last_modified, "error": None, "content_check": detail}
        except requests.RequestException as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            part.unlink(missing_ok=True)
            time.sleep(2 ** attempt)
    part.unlink(missing_ok=True)
    return {"http_status": None, "error": last_err or "unknown error"}


def fetch_stamp(stamp: dt.date, cache: Path) -> dict:
    name = bucket_name(stamp)
    dest = cache / "files" / name
    entry = {"stamp": stamp.isoformat(), "day_spc": day_of_stamp(stamp).isoformat(),
             "file": f"files/{name}", "bucket_url": bucket_url(stamp), "iem_url": iem_url(stamp),
             "bucket_status": None, "iem_status": None}
    try:
        b = get_to_file(bucket_url(stamp), dest)
        entry["bucket_status"] = b.get("http_status")
        if b.get("http_status") == 200:
            entry.update(source="bucket", bytes=b["bytes"], sha256=b["sha256"],
                         last_modified=b["last_modified"], content_check=b["content_check"], error=None)
            return entry
        if b.get("http_status") != 404:
            entry.update(source="error", error=b.get("error"))
            return entry
        i = get_to_file(iem_url(stamp), dest)
        entry["iem_status"] = i.get("http_status")
        if i.get("http_status") == 200:
            entry.update(source="iem", bytes=i["bytes"], sha256=i["sha256"],
                         last_modified=i["last_modified"], content_check=i["content_check"], error=None)
        elif i.get("http_status") == 404:
            entry.update(source="missing", error=None)
        else:
            entry.update(source="error", error=i.get("error"))
    except Exception as exc:  # keep the pool going; the ledger records the failure
        entry.update(source="error", error=f"{type(exc).__name__}: {exc}")
    return entry


def read_ledger(path: Path) -> dict:
    entries = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue            # a line cut off by an interrupted run
            entries[e["stamp"]] = e
    return entries


def settled(entry, cache: Path) -> bool:
    if entry is None:
        return False
    if entry["source"] == "missing":
        return True
    if entry["source"] in ("bucket", "iem"):
        f = cache / entry["file"]
        return f.exists() and f.stat().st_size == entry["bytes"]
    return False


def cmd_fetch(args) -> int:
    if not 1 <= args.workers <= MAX_WORKERS:
        raise SystemExit(f"--workers must be between 1 and {MAX_WORKERS}")
    start, end = parse_day(args.start), parse_day(args.end)
    cache = Path(args.cache)
    (cache / "files").mkdir(parents=True, exist_ok=True)
    ledger_path = cache / "ledger.jsonl"
    ledger = read_ledger(ledger_path)
    stamps = list(day_range(start, end))

    def needs_fetch(s):
        entry = ledger.get(s.isoformat())
        if args.recheck_missing and entry is not None and entry["source"] == "missing":
            return True
        return not settled(entry, cache)

    todo = [s for s in stamps if needs_fetch(s)]
    print(f"stamps {len(stamps)}; settled {len(stamps) - len(todo)}; to fetch {len(todo)}", flush=True)
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool, ledger_path.open("a", encoding="utf-8") as lf:
        futures = [pool.submit(fetch_stamp, s, cache) for s in todo]
        for fut in as_completed(futures):
            entry = fut.result()
            entry["fetched_utc"] = utc_now()
            lf.write(json.dumps(entry, sort_keys=True) + "\n")
            lf.flush()
            ledger[entry["stamp"]] = entry
            done += 1
            if done % 100 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} done, {time.time() - t0:.0f} s", flush=True)
    write_manifest(cache, ledger, start, end, time.time() - t0)
    return 0


def write_manifest(cache: Path, ledger: dict, start: dt.date, end: dt.date, wall_s: float) -> None:
    rows = [ledger[s.isoformat()] for s in day_range(start, end) if s.isoformat() in ledger]
    counts = {}
    nbytes = {}
    for r in rows:
        counts[r["source"]] = counts.get(r["source"], 0) + 1
        if r["source"] in ("bucket", "iem"):
            nbytes[r["source"]] = nbytes.get(r["source"], 0) + r["bytes"]
    out = {"product": PRODUCT, "requested": [start.isoformat(), end.isoformat()],
           "generated_utc": utc_now(), "this_run_wall_s": round(wall_s, 1),
           "counts_by_source": counts, "bytes_by_source": nbytes,
           "missing_stamps": [r["stamp"] for r in rows if r["source"] == "missing"],
           "error_stamps": [r["stamp"] for r in rows if r["source"] == "error"],
           "entries": rows}
    tmp = cache / "manifest.json.part"
    tmp.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, cache / "manifest.json")
    print(json.dumps({k: out[k] for k in ("counts_by_source", "bytes_by_source", "missing_stamps",
                                           "error_stamps")}, indent=1), flush=True)


# ----------------------------------------------------------------------------
# decode
# ----------------------------------------------------------------------------
def cmd_decode(args) -> int:
    grid = montana_grid(args.basemap)
    values, meta = read_mesh_file(args.file)
    raw = crop_values(values, grid)
    tenths, stats = pack_tenths(raw)
    out = {"file": str(args.file), "meta": meta, "crop": {"row0": grid.row0, "col0": grid.col0,
           "nrow": grid.nrow, "ncol": grid.ncol}, "state_cells": grid.n, "stats": stats}
    if args.npz:
        np.savez_compressed(args.npz, raw=raw, tenths=tenths, rows=grid.rows, cols=grid.cols)
        out["npz"] = str(args.npz)
    print(json.dumps(out, indent=1))
    return 0


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="download the 12:00 UTC MESH 24-hour files")
    f.add_argument("--start", default=DEFAULT_START)
    f.add_argument("--end", default=DEFAULT_END)
    f.add_argument("--cache", required=True)
    f.add_argument("--workers", type=int, default=MAX_WORKERS)
    f.add_argument("--recheck-missing", action="store_true",
                   help="fetch again the stamps recorded as missing (after a fix to the IEM path)")
    f.set_defaults(func=cmd_fetch)

    d = sub.add_parser("decode", help="decode one file to the Montana cells")
    d.add_argument("--file", required=True)
    d.add_argument("--basemap", default=str(default_basemap()))
    d.add_argument("--npz")
    d.set_defaults(func=cmd_decode)

    b = sub.add_parser("build", help="build the store from the fetched 12:00 UTC files")
    b.add_argument("--start", default=DEFAULT_START, help="first file date (stamp)")
    b.add_argument("--end", default=DEFAULT_END, help="last file date (stamp)")
    b.add_argument("--cache", required=True)
    b.add_argument("--store", required=True)
    b.add_argument("--procs", type=int, default=MAX_WORKERS)
    b.add_argument("--basemap", default=str(default_basemap()))
    b.add_argument("--allow-gaps", action="store_true", help="build even when a day is missing or errored")
    b.set_defaults(func=cmd_build)

    lk = sub.add_parser("lookup", help="a latitude and longitude to the stored radar estimates")
    lk.add_argument("--store", required=True)
    lk.add_argument("--lat", type=float, required=True)
    lk.add_argument("--lon", type=float, required=True)
    lk.add_argument("--all-days", action="store_true", help="also scan every stored day (slower)")
    lk.add_argument("--json", action="store_true")
    lk.set_defaults(func=cmd_lookup)

    v = sub.add_parser("verify", help="Benchland, peak day, 2-minute frame check, code shares")
    v.add_argument("--store", required=True)
    v.add_argument("--cache", required=True)
    v.add_argument("--out", required=True)
    v.add_argument("--basemap", default=str(default_basemap()))
    v.add_argument("--frame-stamps", default="2025-06-16,2025-06-26,2022-07-09")
    v.set_defaults(func=cmd_verify)

    x = sub.add_parser("fixture", help="save a small crop of one real file for the tests")
    x.add_argument("--file", required=True)
    x.add_argument("--row0", type=int, required=True)
    x.add_argument("--col0", type=int, required=True)
    x.add_argument("--nrow", type=int, required=True)
    x.add_argument("--ncol", type=int, required=True)
    x.add_argument("--out", required=True)
    x.set_defaults(func=cmd_fixture)
    return p


# ----------------------------------------------------------------------------
# build: day arrays (one year file each), events, counts, shards, stats
# ----------------------------------------------------------------------------
_W: dict = {}


def _init_worker(mask, row0, col0):
    _W["grid"] = Grid(row0, col0, mask)


def _process_day(job):
    """Worker: one SPC day to packed tenths, a day blob, statistics and events.

    job = (kind, payload, day, stamp). kind "grib": payload is a .grib2.gz path.
    kind "raw": payload is the raw values already in the grid's cell order (tests).
    """
    kind, payload, day, stamp = job
    grid = _W["grid"]
    if kind == "grib":
        values, _meta = read_mesh_file(payload)
        raw = crop_values(values, grid)
    else:
        raw = np.asarray(payload, dtype=np.float64)
    if raw.shape != (grid.n,):
        raise ValueError(f"{day}: {raw.shape} values for {grid.n} cells")
    tenths, stats = pack_tenths(raw)
    blob = encode_tenths(tenths)
    ev = np.flatnonzero(tenths >= EVENT_MIN_TENTHS)
    return {"day": day, "stamp": stamp, "blob": blob, "stats": stats,
            "ev_cell": ev.astype(np.int32), "ev_tenths": tenths[ev].copy(),
            "tenths": tenths if in_five_years(day) else None}


def write_shards(grid: Grid, cells: np.ndarray, days_ev: np.ndarray, tenths: np.ndarray, store: Path) -> list:
    """Write one gzip JSON shard per 0.1 degree tile that has events. Returns the shard sizes."""
    sizes = []
    if cells.size == 0:
        return sizes
    key = (grid.rows[cells] // TILE).astype(np.int64) * 100000 + (grid.cols[cells] // TILE)
    order = np.lexsort((cells, days_ev, key))           # tile, then day, then cell
    key_sorted = key[order]
    for part in np.split(order, np.flatnonzero(np.diff(key_sorted)) + 1):
        k = int(key[part[0]])
        tr, tc = divmod(k, 100000)
        events = [[int(cells[i]), int(days_ev[i]), int(tenths[i]) / 10.0] for i in part]
        body = json.dumps({"format": "mesh-events-v1", "unit": "mm", "tile_size": TILE,
                           "tile_row": tr, "tile_col": tc, "events": events}, separators=(",", ":"))
        data = gzip.compress(body.encode("utf-8"), compresslevel=9, mtime=0)
        name = f"r{tr:04d}_c{tc:04d}.json.gz"
        (store / "shards" / name).write_bytes(data)
        sizes.append(len(data))
    return sizes


def build_store(grid: Grid, rows: list, store: Path, procs: int, extra: dict, log=print) -> dict:
    """Write the store for `rows`: one dict per requested SPC day.

    Keys: day (ISO SPC report day), stamp (ISO file date), job (None when there is
    no file, else (kind, payload)), source, bytes, sha256, last_modified.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if store.exists() and any(store.iterdir()):
        raise SystemExit(f"{store} is not empty; remove it first")
    (store / "days").mkdir(parents=True, exist_ok=True)
    (store / "shards").mkdir(parents=True, exist_ok=True)
    stored = [r for r in rows if r["job"] is not None]
    stored_days = [r["day"] for r in stored]
    day_ord = {d: i for i, d in enumerate(stored_days)}
    n = grid.n
    cnt_pos = np.zeros(n, dtype=np.int32)
    cnt_cls = {f"{c:.2f}": np.zeros(n, dtype=np.int32) for c in INCH_CLASSES}
    index, stats_by_day = {}, {}
    ev_cells, ev_days, ev_tens = [], [], []
    jobs = [(r["job"][0], r["job"][1], r["day"], r["stamp"]) for r in stored]
    t0 = time.time()
    year, fh, offset = None, None, 0
    pool = None
    if procs > 0:
        pool = ProcessPoolExecutor(max_workers=procs, initializer=_init_worker,
                                   initargs=(grid.mask, grid.row0, grid.col0))
        results = pool.map(_process_day, jobs, chunksize=1)
    else:
        _init_worker(grid.mask, grid.row0, grid.col0)
        results = (_process_day(j) for j in jobs)
    try:
        for k, res in enumerate(results):
            day = res["day"]
            y = day[:4]
            if y != year:
                if fh:
                    fh.close()
                fh = open(store / "days" / f"{y}.bin", "wb")
                year, offset = y, 0
            blob = res["blob"]
            index[day] = {"year": int(y), "offset": offset, "length": len(blob),
                          "enc": blob[0], "stamp": res["stamp"]}
            fh.write(blob)
            offset += len(blob)
            stats_by_day[day] = {**res["stats"], "enc": blob[0], "blob_bytes": len(blob)}
            if res["ev_cell"].size:
                ev_cells.append(res["ev_cell"])
                ev_days.append(np.full(res["ev_cell"].size, day_ord[day], dtype=np.int32))
                ev_tens.append(res["ev_tenths"])
            if res["tenths"] is not None:
                t = res["tenths"]
                cnt_pos += (t > 0)
                for c in INCH_CLASSES:
                    cnt_cls[f"{c:.2f}"] += (t >= THRESH[f"{c:.2f}"])
            if (k + 1) % 200 == 0:
                log(f"  built {k + 1}/{len(jobs)} days, {time.time() - t0:.0f} s")
    finally:
        if fh:
            fh.close()
        if pool is not None:
            pool.shutdown()
    build_s = time.time() - t0

    cells = np.concatenate(ev_cells) if ev_cells else np.zeros(0, dtype=np.int32)
    days_ev = np.concatenate(ev_days) if ev_days else np.zeros(0, dtype=np.int32)
    tens = np.concatenate(ev_tens) if ev_tens else np.zeros(0, dtype=np.uint16)

    # events table (cell_index, day, mm), sorted by day then cell
    day_dates = np.array(stored_days, dtype="datetime64[D]")
    events = pa.table({
        "cell_index": pa.array(cells, type=pa.int32()),
        "day": pa.array(day_dates[days_ev] if days_ev.size else np.zeros(0, dtype="datetime64[D]"),
                        type=pa.date32()),
        "mm": pa.array(tens.astype(np.float64) / 10.0, type=pa.float64()),
    })
    pq.write_table(events, store / "events.parquet", compression="zstd", row_group_size=500000)

    # per-cell day counts, five-year window only
    counts = pa.table({
        "cell_index": pa.array(np.arange(n, dtype=np.int32)),
        "row": pa.array(grid.rows.astype(np.int32)),
        "col": pa.array(grid.cols.astype(np.int32)),
        "n_pos_days": pa.array(cnt_pos.astype(np.uint16)),
        **{f"n_ge_{c:.2f}in": pa.array(cnt_cls[f"{c:.2f}"].astype(np.uint16)) for c in INCH_CLASSES},
    })
    pq.write_table(counts, store / "cell_counts.parquet", compression="zstd", row_group_size=50000)

    shard_sizes = write_shards(grid, cells, days_ev, tens, store)

    daily = []
    for r in rows:
        row = {"day": r["day"], "stamp": r["stamp"], "source": r["source"], "file_bytes": r.get("bytes"),
               "sha256": r.get("sha256"), "last_modified": r.get("last_modified"),
               "present": r["day"] in stats_by_day, "five_year": in_five_years(r["day"])}
        if r["day"] in stats_by_day:
            row.update(stats_by_day[r["day"]])
        daily.append(row)
    (store / "daily_stats.json").write_text(json.dumps(daily, sort_keys=True, separators=(",", ":")),
                                            encoding="utf-8")
    (store / "days" / "index.json").write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
    (store / "mask.bin").write_bytes(np.packbits(grid.mask.ravel()).tobytes())
    fy_lo, fy_hi = five_year_spc_days()
    meta = {
        "format": "mesh-h1-store-v1",
        "product": PRODUCT,
        "units": "stored: uint16 tenths of a mm per cell, 0 = no data; outputs show mm and inches (mm / 25.4)",
        "day_key": "SPC report day D: the 12:00 UTC file stamped D+1 (window 12:00 UTC D to 11:59 UTC D+1)",
        "crop": {"row0": grid.row0, "col0": grid.col0, "nrow": grid.nrow, "ncol": grid.ncol},
        "n_cells": grid.n,
        "cell_order": "row-major over the crop mask; cell_index is the position among mask cells",
        "mask_file": "mask.bin (np.packbits of the crop mask, row-major)",
        "tile_size_cells": TILE,
        "thresholds_tenths": THRESH,
        "event_min_tenths": EVENT_MIN_TENTHS,
        "five_year_spc_days": [fy_lo, fy_hi],
        "days": stored_days,
        "missing_or_unfetched_days": [r["day"] for r in rows if r["job"] is None],
        "encodings": {"0": "dense: zlib(level 9) of little-endian uint16 per cell",
                      "1": "sparse: uint32 count, then zlib(level 9) of uint32 gaps and uint16 values"},
        "built_utc": utc_now(),
        "build_seconds": round(build_s, 1),
        **extra,
    }
    (store / "grid.json").write_text(json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
    return {"stored_days": len(stored_days), "events": int(cells.size), "shards": len(shard_sizes),
            "build_seconds": round(build_s, 1)}


def cmd_build(args) -> int:
    cache, store = Path(args.cache), Path(args.store)
    grid = montana_grid(args.basemap)
    ledger = read_ledger(cache / "ledger.jsonl")
    start, end = parse_day(args.start), parse_day(args.end)
    rows, problems = [], []
    for s in day_range(start, end):
        e = ledger.get(s.isoformat())
        row = {"day": day_of_stamp(s).isoformat(), "stamp": s.isoformat(), "job": None,
               "source": None, "bytes": None, "sha256": None, "last_modified": None}
        if e is None:
            row["source"] = "not fetched"
            problems.append(f"{s}: not fetched")
        elif e["source"] == "missing":
            row["source"] = "missing"
        elif e["source"] == "error":
            row["source"] = "error"
            problems.append(f"{s}: fetch error {e.get('error')}")
        elif not settled(e, cache):
            row["source"] = "file absent"
            problems.append(f"{s}: file missing from cache")
        else:
            row.update(job=("grib", str(cache / e["file"])), source=e["source"], bytes=e["bytes"],
                       sha256=e["sha256"], last_modified=e.get("last_modified"))
        rows.append(row)
    if problems and not args.allow_gaps:
        raise SystemExit("refusing to build with gaps (use --allow-gaps):\n  " + "\n  ".join(problems[:20]))
    extra = {"requested_stamps": [start.isoformat(), end.isoformat()],
             "basemap_sha256": sha256_file(args.basemap),
             "source": "NOAA MRMS bucket noaa-mrms-pds (IEM mirror only where the bucket is 404)"}
    summary = build_store(grid, rows, store, args.procs, extra)
    print(json.dumps(summary, indent=1), flush=True)
    return 0


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------
# lookup: the read side of the store
# ----------------------------------------------------------------------------
class Store:
    """Read side of the store: grid mask, day list, event shards, cell counts, day blobs."""

    def __init__(self, path):
        self.path = Path(path)
        self.meta = json.loads((self.path / "grid.json").read_text(encoding="utf-8"))
        c = self.meta["crop"]
        bits = np.frombuffer((self.path / "mask.bin").read_bytes(), dtype=np.uint8)
        mask = np.unpackbits(bits)[: c["nrow"] * c["ncol"]].reshape(c["nrow"], c["ncol"]).astype(bool)
        self.grid = Grid(c["row0"], c["col0"], mask)
        self.days = self.meta["days"]
        self.five_lo, self.five_hi = self.meta["five_year_spc_days"]
        self._index = None

    @property
    def index(self) -> dict:
        if self._index is None:
            self._index = json.loads((self.path / "days" / "index.json").read_text(encoding="utf-8"))
        return self._index

    def shard_events(self, row: int, col: int) -> list:
        f = self.path / "shards" / shard_name(row, col)
        if not f.exists():
            return []
        doc = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
        return doc["events"]

    def cell_counts(self, idx: int) -> dict:
        import pyarrow.parquet as pq

        t = pq.read_table(self.path / "cell_counts.parquet", filters=[("cell_index", "=", int(idx))])
        if t.num_rows != 1:
            raise ValueError(f"cell {idx}: {t.num_rows} rows in cell_counts")
        return {name: int(t.column(name)[0].as_py()) for name in t.column_names}

    def day_tenths(self, day: str) -> np.ndarray:
        ent = self.index[day]
        with open(self.path / "days" / f"{ent['year']}.bin", "rb") as fh:
            fh.seek(ent["offset"])
            blob = fh.read(ent["length"])
        return decode_tenths(blob, self.grid.n)

    def cell_all_days(self, idx: int) -> list:
        """Every stored day with a positive value at cell idx: [(day, tenths)]. Reads every day blob."""
        out = []
        by_year: dict = {}
        for day, ent in self.index.items():
            by_year.setdefault(ent["year"], []).append((ent["offset"], ent["length"], day))
        for year in sorted(by_year):
            with open(self.path / "days" / f"{year}.bin", "rb") as fh:
                for offset, length, day in sorted(by_year[year]):
                    fh.seek(offset)
                    t = decode_tenths(fh.read(length), self.grid.n)[idx]
                    if t > 0:
                        out.append((day, int(t)))
        return sorted(out)


def nearest_cell(grid: Grid, lat: float, lon: float):
    """The Montana cell whose centre is nearest to (lat, lon), from the four surrounding centres."""
    rf = (ROW0_LAT_E3 / 1000.0 - lat) / (STEP_E3 / 1000.0)
    cf = (lon - COL0_LON_E3 / 1000.0) / (STEP_E3 / 1000.0)
    best = None
    for r in (math.floor(rf), math.floor(rf) + 1):
        for c in (math.floor(cf), math.floor(cf) + 1):
            idx = grid.index_of(r, c)
            if idx < 0:
                continue
            d = float(haversine_km(lat, lon, grid.lat[idx], grid.lon[idx]))
            if best is None or d < best[1]:
                best = (idx, d)
    return best


def lookup_point(store: Store, lat: float, lon: float, all_days: bool = False) -> dict:
    g = store.grid
    near = nearest_cell(g, lat, lon)
    out = {"query": {"lat": lat, "lon": lon}, "window_spc_days": [store.five_lo, store.five_hi]}
    if near is None:
        out["cell"] = None
        out["wording"] = ["No stored radar estimate: the point is not in a Montana grid cell of this store. "
                          "This is not the same as no hail."]
        return out
    idx, dist = near
    row, col = int(g.rows[idx]), int(g.cols[idx])
    events = [e for e in store.shard_events(row, col) if e[0] == idx]
    five = []
    for _cell, dayord, mm in events:
        day = store.days[dayord]
        if store.five_lo <= day <= store.five_hi:
            five.append({"day": day, "file_stamp": (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat(),
                         "mm": mm, "in": round(mm / 25.4, 2)})
    five.sort(key=lambda x: x["day"])
    counts = store.cell_counts(idx)
    ge = {}
    for c in INCH_CLASSES:
        key = f"{c:.2f}"
        ge[key] = sum(1 for x in five if round(x["mm"] * 10) >= THRESH[key])
    top = sorted(five, key=lambda x: (-x["mm"], x["day"]))[:5]
    out.update({
        "cell": {"cell_index": idx, "row": row, "col": col, "lat": round(float(g.lat[idx]), 3),
                 "lon": round(float(g.lon[idx]), 3), "distance_km": round(dist, 2)},
        "tile_shard": shard_name(row, col),
        "events_five_year": five,
        "day_counts_five_year": {"positive_any": counts["n_pos_days"],
                                 **{f"at_or_above_{k}_in": v for k, v in ge.items()}},
        "top_five_year": top,
    })
    if all_days:
        allpos = store.cell_all_days(idx)
        out["all_days_positive"] = {"count": len(allpos), "first": allpos[0][0] if allpos else None,
                                    "last": allpos[-1][0] if allpos else None}
    out["wording"] = wording_for(out)
    return out


def wording_for(res: dict) -> list:
    cell = res["cell"]
    lines = [f"Radar estimate (NOAA MRMS MESH, 24-hour maximum per SPC report day): nearest grid cell centre "
             f"{cell['lat']:.3f} N, {abs(cell['lon']):.3f} W, {cell['distance_km']:.1f} km from the point."]
    if res["top_five_year"]:
        t = res["top_five_year"][0]
        lines.append(f"Largest stored estimate in the five years: {t['in']:.2f} in ({t['mm']:.1f} mm) on SPC "
                     f"day {t['day']} (file stamped {t['file_stamp']} 12:00 UTC).")
    else:
        lines.append("No stored estimate at or above 0.25 in in the five years for this cell.")
    c = res["day_counts_five_year"]
    lines.append(f"Days at or above 0.25 in: {c['at_or_above_0.25_in']}; 0.75 in: {c['at_or_above_0.75_in']}; "
                 f"1.00 in: {c['at_or_above_1.00_in']}; 1.50 in: {c['at_or_above_1.50_in']}; "
                 f"2.00 in: {c['at_or_above_2.00_in']}. Days with any positive estimate: {c['positive_any']}.")
    lines.append("Not listed: days with estimates under 0.25 in, and cells with no data. Not the same as no hail.")
    lines.append("This is a radar estimate for one 0.01 degree cell (about 0.8 km by 1.1 km). It is not a report, "
                 "not an inspection, and not a finding about any roof.")
    return lines


def cmd_lookup(args) -> int:
    store = Store(args.store)
    res = lookup_point(store, args.lat, args.lon, all_days=args.all_days)
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        for line in res["wording"]:
            print(line)
        if res.get("events_five_year"):
            print("Days at or above 0.25 in (SPC report day, file stamp, mm, in):")
            for e in res["events_five_year"]:
                print(f"  {e['day']}  {e['file_stamp']}  {e['mm']:.1f} mm  {e['in']:.2f} in")
        if "all_days_positive" in res:
            print(f"All stored days with any positive estimate: {res['all_days_positive']['count']}")
    return 0


# ----------------------------------------------------------------------------
# verify
# ----------------------------------------------------------------------------
def disk_max(grid: Grid, tenths: np.ndarray, lat: float, lon: float, km: float) -> dict:
    d = haversine_km(lat, lon, grid.lat, grid.lon)
    sel = np.flatnonzero(d <= km)
    vals = tenths[sel].astype(np.int64)
    res = {"centre": [lat, lon], "radius_km": km, "cells_in_disk": int(sel.size),
           "cells_no_data": int(np.count_nonzero(vals == 0)), "cells_positive": int(np.count_nonzero(vals))}
    if sel.size and vals.max() > 0:
        k = int(np.argmax(vals))
        i = int(sel[k])
        res.update(max_mm=round(int(vals[k]) / 10.0, 1), max_cell_lat=round(float(grid.lat[i]), 4),
                   max_cell_lon=round(float(grid.lon[i]), 4), max_cell_km=round(float(d[i]), 2))
    else:
        res.update(max_mm=None)
    return res


def compare_tenths(grid: Grid, a: np.ndarray, b: np.ndarray) -> dict:
    """a: the 12:00 file, b: the maximum of the 2-minute frames (both tenths, 0 = no data)."""
    diff = a.astype(np.int32) - b.astype(np.int32)
    res = {"state_cells": int(a.size), "cells_equal": int(np.count_nonzero(diff == 0)),
           "cells_file_higher": int(np.count_nonzero(diff > 0)), "cells_file_lower": int(np.count_nonzero(diff < 0)),
           "file_positive_cells": int(np.count_nonzero(a)), "frames_max_positive_cells": int(np.count_nonzero(b))}
    if np.any(diff):
        worst = np.argsort(-np.abs(diff))[:3]
        res["largest_differences"] = [
            {"lat": round(float(grid.lat[i]), 4), "lon": round(float(grid.lon[i]), 4),
             "file_mm": int(a[i]) / 10.0, "frames_max_mm": int(b[i]) / 10.0} for i in worst]
        res["max_abs_diff_mm"] = round(float(np.abs(diff).max()) / 10.0, 1)
    else:
        res["max_abs_diff_mm"] = 0.0
    return res


def iem_frames(stamp: dt.date) -> list:
    """2-minute MESH frames in the window 12:00 UTC on stamp-1 to 12:00 UTC on stamp (IEM listings)."""
    import requests  # noqa: F401  (the session is requests-based)

    start = dt.datetime.combine(stamp - dt.timedelta(days=1), dt.time(12, 0))
    end = dt.datetime.combine(stamp, dt.time(12, 0))
    frames = []
    for d in (stamp - dt.timedelta(days=1), stamp):
        url = f"{IEM}/{d:%Y/%m/%d}/mrms/ncep/MESH/"
        resp = _session().get(url, timeout=(20, 120))
        resp.raise_for_status()
        for name, d8, t6 in re.findall(r'href="(MESH_00\.50_(\d{8})-(\d{6})\.grib2\.gz)"', resp.text):
            t = dt.datetime.strptime(d8 + t6, "%Y%m%d%H%M%S")
            if start <= t < end:
                frames.append((t, name, url + name))
    frames.sort()
    return frames


def _frame_chunk_max(paths: list):
    grid = _W["grid"]
    acc = np.zeros(grid.n, dtype=np.uint16)
    done, errors = 0, []
    for p in paths:
        try:
            values, _meta = read_mesh_file(p)
            tenths, _stats = pack_tenths(crop_values(values, grid))
            np.maximum(acc, tenths, out=acc)
            done += 1
        except Exception as exc:  # recorded, not hidden: the count of errors is reported
            errors.append(f"{Path(p).name}: {exc}")
    return acc, done, errors


def frames_max(pool, paths: list, nproc: int):
    chunks = [paths[i::nproc] for i in range(nproc)]
    acc = np.zeros(_W["grid"].n, dtype=np.uint16)
    done, errors = 0, []
    for part_acc, n_done, errs in pool.map(_frame_chunk_max, chunks):
        np.maximum(acc, part_acc, out=acc)
        done += n_done
        errors.extend(errs)
    return acc, done, errors


def file_tenths(grid: Grid, cache: Path, ledger: dict, stamp: str):
    e = ledger[stamp]
    values, meta = read_mesh_file(cache / e["file"])
    return pack_tenths(crop_values(values, grid)) + (meta,)


def season_of(month: int) -> str:
    return {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
            6: "JJA", 7: "JJA", 8: "JJA"}.get(month, "SON")


def cmd_verify(args) -> int:
    store = Store(args.store)
    cache = Path(args.cache)
    ledger = read_ledger(cache / "ledger.jsonl")
    grid = store.grid
    report: dict = {"checked_utc": utc_now(), "store": str(store.path)}
    t_total = time.time()
    _init_worker(grid.mask, grid.row0, grid.col0)

    # A. Benchland: the store against the raw file, and the two points (see README)
    spc, stamp = "2025-06-15", "2025-06-16"
    t_store = store.day_tenths(spc)
    t_file, st_file, _meta = file_tenths(grid, cache, ledger, stamp)
    bench = {"spc_day": spc, "file_stamp": stamp, "store_equals_file": bool(np.array_equal(t_store, t_file))}
    bench["points"] = {
        "brief_point_46.9N_109.9W": disk_max(grid, t_file, 46.9, -109.9, 15.0),
        "spc_report_point_47.08N_110.02W": disk_max(grid, t_file, 47.08, -110.02, 15.0),
    }
    bench["points"]["brief_point_46.9N_109.9W"]["store_max_mm"] = disk_max(grid, t_store, 46.9, -109.9, 15.0)["max_mm"]
    bench["points"]["spc_report_point_47.08N_110.02W"]["store_max_mm"] = disk_max(grid, t_store, 47.08, -110.02, 15.0)["max_mm"]
    bench["context_previous_spc_day_2025-06-14_stamp_2025-06-15"] = disk_max(
        grid, file_tenths(grid, cache, ledger, "2025-06-15")[0], 46.9, -109.9, 15.0)
    report["benchland"] = bench

    # B. Peak day 2022-07-09 (file stamp), SPC day 2022-07-08
    daily = {r["day"]: r for r in json.loads((store.path / "daily_stats.json").read_text(encoding="utf-8"))}
    peak_day, peak_stamp = "2022-07-08", "2022-07-09"
    incl_grid = montana_grid(args.basemap, inclusive=True)
    values_pk, _m = read_mesh_file(cache / ledger[peak_stamp]["file"])
    raw_incl = crop_values(values_pk, incl_grid)
    _t_incl, st_incl = pack_tenths(raw_incl)
    report["peak_day"] = {
        "spc_day": peak_day, "file_stamp": peak_stamp,
        "positive_cells_strict_store": daily[peak_day]["n_pos"],
        "positive_cells_inclusive_mask": st_incl["n_pos"],
        "tie_cells_positive": st_incl["n_pos"] - daily[peak_day]["n_pos"],
        "inclusive_state_cells": incl_grid.n,
        "max_mm": daily[peak_day]["max_mm"],
    }

    # C. Three days: the 12:00 file against the maximum of the IEM 2-minute frames
    pool = ProcessPoolExecutor(max_workers=MAX_WORKERS, initializer=_init_worker,
                               initargs=(grid.mask, grid.row0, grid.col0))
    three = []
    try:
        for s in args.frame_stamps.split(","):
            stamp_d = dt.date.fromisoformat(s)
            frames = iem_frames(stamp_d)
            vdir = cache / "verify-2min" / s
            vdir.mkdir(parents=True, exist_ok=True)
            fetched, dl_fail = [], []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as tp:
                futs = {tp.submit(get_to_file, url, vdir / name): (name, url) for _t, name, url in frames}
                for fut in as_completed(futs):
                    name, url = futs[fut]
                    res = fut.result()
                    if res.get("http_status") == 200:
                        fetched.append(str(vdir / name))
                    else:
                        dl_fail.append({"name": name, "status": res.get("http_status"), "error": res.get("error")})
            fetched.sort()
            t1 = time.time()
            acc, n_dec, errs = frames_max(pool, fetched, MAX_WORKERS)
            file_t, st_file12, _m = file_tenths(grid, cache, ledger, s)
            comp = compare_tenths(grid, file_t, acc)
            comp.update({"stamp": s, "spc_day": day_of_stamp(stamp_d).isoformat(),
                         "window_utc": [f"{day_of_stamp(stamp_d)}T12:00", f"{s}T12:00"],
                         "frames_listed": len(frames), "frames_downloaded": len(fetched),
                         "frames_decoded": n_dec, "frame_download_failures": dl_fail[:5],
                         "frame_download_failure_count": len(dl_fail), "frame_decode_errors": errs[:5],
                         "frame_decode_error_count": len(errs), "decode_seconds": round(time.time() - t1, 1)})
            three.append(comp)
            print(f"  {s}: frames {n_dec}/{len(frames)}, equal {comp['cells_equal']}, "
                  f"file higher {comp['cells_file_higher']}, lower {comp['cells_file_lower']}", flush=True)
    finally:
        pool.shutdown()
    report["two_minute_check"] = three

    # D. Code shares by season (state cells, from the daily statistics)
    seas: dict = {}
    for r in daily.values():
        if not r["present"]:
            continue
        m = dt.date.fromisoformat(r["day"]).month
        s = seas.setdefault(season_of(m), {"days": 0, "cells": 0, "minus1": 0, "minus3": 0, "other_neg": 0, "zero": 0})
        s["days"] += 1
        s["cells"] += r["n_cells"]
        s["minus1"] += r["n_minus1"]
        s["minus3"] += r["n_minus3"]
        s["other_neg"] += r["n_other_neg"]
        s["zero"] += r["n_zero"]
    report["code_shares_by_season"] = {
        k: {**v, "share_minus1_pct": round(100.0 * v["minus1"] / v["cells"], 2),
            "share_minus3_pct": round(100.0 * v["minus3"] / v["cells"], 4),
            "share_other_neg_pct": round(100.0 * v["other_neg"] / v["cells"], 6)} for k, v in sorted(seas.items())}

    # E. Round trip: store day arrays against a fresh decode of the file
    rng = np.random.default_rng(20261017)
    present = [d for d in store.days]
    picks = [present[i] for i in sorted(rng.choice(len(present), size=3, replace=False))]
    rt = []
    for d in picks:
        stamp_s = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
        t_f, _st, _m = file_tenths(grid, cache, ledger, stamp_s)
        rt.append({"spc_day": d, "equal": bool(np.array_equal(store.day_tenths(d), t_f))})
    report["round_trip"] = rt

    # F. Lookup timings (in-process, after the first call warms the caches)
    lr = np.random.default_rng(7)
    cells = lr.choice(grid.n, size=200, replace=False)
    lookup_times = []
    for i in cells:
        la, lo = float(grid.lat[i]), float(grid.lon[i])
        t0 = time.perf_counter()
        lookup_point(store, la, lo)
        lookup_times.append((time.perf_counter() - t0) * 1000.0)
    lookup_times.sort()
    all_times = []
    for i in cells[:3]:
        t0 = time.perf_counter()
        lookup_point(store, float(grid.lat[i]), float(grid.lon[i]), all_days=True)
        all_times.append((time.perf_counter() - t0) * 1000.0)
    report["lookup_ms"] = {"n": len(lookup_times), "p50": round(lookup_times[len(lookup_times) // 2], 2),
                           "p95": round(lookup_times[int(len(lookup_times) * 0.95)], 2),
                           "max": round(lookup_times[-1], 2),
                           "all_days_scan_ms_three_points": [round(x, 1) for x in all_times]}

    # G. Store sizes by format
    report["store_bytes"] = store_sizes(store.path)
    report["seconds"] = round(time.time() - t_total, 1)
    Path(args.out).write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("benchland", "peak_day")}, indent=1)[:3000], flush=True)
    print(f"verify written to {args.out}", flush=True)
    return 0


def store_sizes(path: Path) -> dict:
    def total(paths):
        sizes = [p.stat().st_size for p in paths]
        return {"count": len(sizes), "total": sum(sizes),
                "median": int(np.median(sizes)) if sizes else 0, "max": max(sizes) if sizes else 0}
    days = sorted((path / "days").glob("*.bin"))
    shards = sorted((path / "shards").glob("*.json.gz"))
    out = {
        "per_day_arrays_by_year": {p.name: p.stat().st_size for p in days},
        "per_day_arrays_total": sum(p.stat().st_size for p in days),
        "events_parquet": (path / "events.parquet").stat().st_size,
        "cell_counts_parquet": (path / "cell_counts.parquet").stat().st_size,
        "json_shards": total(shards),
        "daily_stats_json": (path / "daily_stats.json").stat().st_size,
        "day_index_json": (path / "days" / "index.json").stat().st_size,
        "grid_json": (path / "grid.json").stat().st_size,
        "mask_bin": (path / "mask.bin").stat().st_size,
    }
    out["store_total"] = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return out


# ----------------------------------------------------------------------------
# fixture: a small saved crop of one real file, for the offline tests
# ----------------------------------------------------------------------------
def cmd_fixture(args) -> int:
    values, meta = read_mesh_file(args.file)
    block = values[args.row0:args.row0 + args.nrow, args.col0:args.col0 + args.ncol]
    doc = {
        "about": "Raw MESH values (file units, read as mm; codes -1 and -3 are no data) cut from one real "
                 "12:00 UTC MESH_Max_1440min_00.50 file. Made by mesh_history.py fixture.",
        "source_file": Path(args.file).name,
        "source_sha256": sha256_file(args.file),
        "source_bytes": Path(args.file).stat().st_size,
        "meta": meta,
        "row0": args.row0, "col0": args.col0, "nrow": args.nrow, "ncol": args.ncol,
        "values": [[round(float(x), 4) for x in row] for row in block],
    }
    Path(args.out).write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"out": args.out, "cells": args.nrow * args.ncol, "bytes": Path(args.out).stat().st_size}))
    return 0


def default_basemap() -> Path:
    # research/hail-history/prototype -> repository root -> website/static/map/basemap.json
    return Path(__file__).resolve().parents[3] / "website" / "static" / "map" / "basemap.json"


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
