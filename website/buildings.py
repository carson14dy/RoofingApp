"""Building outlines, one dot per building, and the address join (B3; docs/DECISIONS.md D14, D15, D26 to D28, D32, D34,
D39 and D40).

The outlines are the FEMA and ORNL "USA Structures" file for Montana (MT_Structures_20260913.zip: a file geodatabase in
WGS 84 with 918,052 building outlines). The layer is opened with no attribute columns, so no attribute of an outline is
ever decoded, stored or shown: the reader takes geometry only (decision 6, D12, D14). The county boundary file (the
Census Bureau's 2025 cartographic boundaries, 500k) is read for its geographic code and name only, to label the
per-county counts; it is optional, and its failure leaves the rest of the store as it is.

Output, written into the store next to the B1 shards and the address shards (store/hail/):
  b/<tile name><digits>.json   one shard per quadtree leaf of a B1 tile, split while its JSON is over 250,000 bytes
                               (D26; the depth cap and the leaf names are the addresses module's). Each outline is one
                               entry, {"p":[lon,lat],"g":[[[lon,lat],...],...],"l":["401 North 27th Street",...]}: p is the
                               dot point (the centroid when it is inside the outline, else the midpoint of the longest
                               interior chord through the centroid; strictly inside its rounded rings, D15), g the rings
                               (outer rings and holes, closed, rounded to 5 decimals, no simplification, D14) and l the
                               deduplicated address lines of the
                               Structure-placed address points inside the outline or within 15 m of its edge (D15, D32).
                               A line's city and zip are in z, parallel to l, as null when they are the shard's common
                               pair; z is absent when every line has the common pair. The shard header is
                               {"f":"hail-buildings-v1","b":[w,s,e,n],"n":outlines,"m":address rows matched in the shard,
                               "c":[city,zip] or null,"a":[...]}.
  a/<tile name><digits>.json   the address shards, rewritten to hold only the rows that sit on no building dot (D28; the
                               same leaves and bounds as the addresses module). The matched rows live in b/, and every row
                               stays in the search index (a/idx), so a search still finds an address on a building.
  counts.json                  {"f":"hail-building-counts-v1","tiles":{"<tile>":n,...},"total":n}: the outlines of each
                               B1 tile, by the tile of their dot point, for the zoom 13 and 14 count layer (D27). Every
                               tile that holds an outline is listed, inside the hail grid or not.
  hail/index.json              gains "buildings" (the state, the source, the counts of D15, D32 and D34, the measures and
                               the split map); hail/manifest.json lists every new file. The addresses block's figures
                               of hail/a are read back from the files at every write of the index (D49).

Where the brief and a later decision differ, this module follows the decision:
  - D28 over the brief's "u" lists: an unmatched address row is written once, to its a/ shard, where the address dots
    are drawn from. The b/ shards have no "u" key. Writing each unmatched row into b/ as well would store it twice
    (about 120,000 rows) and break "every row appears once" (gate 9 of the synthesis).
  - D32 over D15 on the join: only a Structure-placed point (class S) may join an outline. A point of any other class
    keeps its own dot, with its class, even when it sits inside an outline.
  - D39: merged address rows keep their Structure row (the addresses module merges them; this module reads the rows).

The join is computed here, in Python with numpy; the browser draws the shards and never joins. Distances are metres
from a local scale at the point's latitude. The outline file is checked before anything is read from it: its name,
size, layer name, geometry type, WGS 84 CRS and feature count must be the expected ones, and a changed file marks the
outlines unavailable with the reason (D20, D36). The rest of the store is kept, and the job goes on.

Command line (run from the repository root):
    python -m website.buildings build --store DIR [--gdb-zip FILE] [--cache DIR] [--url URL] [--ledger FILE]
                                      [--counties-zip FILE] [--counties-cache DIR]
    python -m website.buildings verify --store DIR [--gdb-zip FILE] [--counties-zip FILE]
    python -m website.buildings unavailable --store DIR --reason TEXT

pyogrio is imported only when the outlines are read (the daily job installs pyogrio~=0.13; the tests that need it skip
without it). numpy is imported only when a build or a check runs, so the site build can read the map data without it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import addresses, hail

FORMAT = "hail-buildings-v1"
COUNTS_FORMAT = "hail-building-counts-v1"
INDEX_KEY = "buildings"                   # the block in hail/index.json
SHARD_BYTES = 250_000                     # D26: a shard is split while its JSON is over this many bytes
DEPTH_CAP = addresses.DEPTH_CAP           # the leaves are the addresses module's quadtree, to the same depth
SUB = addresses.SUB                       # sub-units per 1e-5 degree (the quadtree's integer grid)
SCALE = addresses.SCALE                   # positions are whole units of 1e-5 degree (5 decimals, D14)
MATCH_M = 15.0                            # D15: a Structure point this close to an edge joins its outline
PAD_DEG = 0.0004                          # a search margin above 15 m at Montana's latitudes (about 30 m east-west)
CELL_DEG = 0.0005                         # the grid cell of the join's index (about 55 m)
ZOOM = {"counts": (13, 14), "dots": 15, "fills": 16, "emphasis": 17}      # D27
TAP_RADIUS_PX = 12
DOT_SEARCH_UNITS = 3                     # D15: a dot that rounding puts on an edge moves at most this far, per axis
# D7: 2.5 px at zoom 13, rising 0.5 px a zoom to 4 px from zoom 16 (the browser's rule is linear, capped at max)
DOT_RADIUS_PX = addresses.DOT_RADIUS_PX           # D7: one dot-radius rule for both layers (defined in addresses.py)
ZIP_NAME = "MT_Structures_20260913.zip"
ZIP_BYTES = 173088786
GDB_NAME = "MT_Structures.gdb"
LAYER = "MT_Structures"
GEOMETRY_TYPES = ("Polygon", "MultiPolygon")
EXPECTED_FEATURES = 918052
FILE_DATE = "2026-09-13"
SOURCE_URL = ("https://fema-femadata.s3.us-east-1.amazonaws.com/Partners/ORNL/USA_Structures/Montana/" + ZIP_NAME)
META_MEMBER = "MT_Structures_metadata.xml"
ATTRIBUTION = "Oak Ridge National Laboratory and FEMA, USA Structures"
LICENCE_READING = ("Data.gov lists the licence as U.S. government works (public domain) with public access. The hosted "
                   "copy of the layer is stated as CC BY 4.0 (attribution, no share-alike); the file's own metadata "
                   "states no constraints. The site credits ORNL and FEMA with the file date; FEMA is to confirm the "
                   "licence in writing (the counsel list).")
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_500k.zip"
COUNTY_NAME = "cb_2025_us_county_500k.zip"
COUNTY_ACK = ("U.S. Census Bureau, cartographic boundary file 2025 (500k); used to label the per-county counts only.")
CLASS_LETTERS = addresses.CLASS_LETTERS  # SPGLTU, the order the counts are written in
STRUCTURE = "S"
BOXES = {                                 # the two check boxes (degrees: west, south, east, north)
    "billings": (-108.51, 45.78, -108.50, 45.79),
    "sanders": None,                      # set by the Sanders check (SANDERS_BOX, below)
}
SANDERS_BOX = (-114.90, 47.44, -114.88, 47.46)     # Plains: 476 address points, 98 percent Geocoding-placed
# D46 and B3-10: the Billings box with its edges closed and the store's merged rows, on the 2026-09-30 address list. The
# synthesis's 869, 535, 313 and 21 were half-open and counted before the merge; 869 is reproduced only that way, and its
# split is reproduced under neither rule (the reviewer's recount, R-11).
BILLINGS_GATE = {"points": 864, "inside": 539, "within_15m": 305, "farther": 20}
BILLINGS_GATE_ADDRESS_DATE = "2026-09-30"          # the figures hold for this address list; verify makes no check for another


def billings_gate(box: dict, address_date) -> dict:
    """The D46 check of the Billings box (B3-10): the recomputed figures against BILLINGS_GATE, for the address list that
    the figures were measured on. Another list's date is recorded as not made and never fails the store, because the
    list is re-exported monthly."""
    figures = {"points": box["points"], "inside": box["points_inside_any"],
               "within_15m": box["points_within_15m_any"], "farther": box["points_farther_any"]}
    if address_date != BILLINGS_GATE_ADDRESS_DATE:
        return {"made": False, "note": f"not made: the address list is dated {address_date}; the stated figures are for "
                                       f"{BILLINGS_GATE_ADDRESS_DATE}"}
    g = BILLINGS_GATE
    return {"made": True, "ok": figures == BILLINGS_GATE,
            "name": (f"the Billings box gives {g['points']} points, {g['inside']} inside, {g['within_15m']} within 15 m "
                     f"and {g['farther']} farther (B3-10: closed box, merged rows)"),
            "detail": f"{figures} recomputed, {BILLINGS_GATE} stated"}
UNAVAILABLE = "The building outlines are unavailable"

# The words of the outline layer (D29, D32, D34). Every sentence the browser shows comes from here; the forbidden-word
# test covers these templates. "structure" appears only inside the two proper names of the source.
WORDS_BUILDINGS = {
    "title": "Building outlines",
    "legend": ("Each dot is one building outline. Tap a dot for its address, if one is on file, and the weather history "
               "for its cell."),
    "no_address": "No address on file for this building. The weather history below is for this building's cell.",
    "addresses_unavailable": ("Addresses for this building could not be loaded in this update; that is not the same as "
                              "no address."),
    "units": "Units on file: {n}.",
    "address_line": "{line}, {city} {zip}",
    "address_line_no_zip": "{line}, {city}",
    "placed": "This address point was placed {how}, not on the building.",
    "count_bubble": "{n} buildings",
    "count_one": "1 building",
    # D41: every unavailable line ends with the required sentence
    "unavailable": ("Building outlines could not be loaded in this update; that is not the same as no buildings. "
                    "This is not an all-clear."),
    "outside_grid": "This point is outside the hail grid's Montana outline; the history does not cover it.",
    "about_title": "Building outlines",
    # D45 (R-06): the outline caveat is said once, in about_caveat
    "about_source": "Building outlines: USA Structures, Oak Ridge National Laboratory and FEMA (file dated {file_date}).",
    "about_source_undated": ("Building outlines: USA Structures, Oak Ridge National Laboratory and FEMA (file date not "
                             "available in this update)."),
    "about_caveat": ("Outlines come from imagery dated 2008 to 2025 and are not surveys; sheds and barns are outlines "
                     "too."),
    "about_dot": ("Each building outline has one dot. Its address lines are the address points that the Montana list "
                  "places on the outline or within 15 meters of its edge. An address point placed some other way keeps "
                  "its own dot."),
}


class BuildingsError(Exception):
    """A build or a check that failed for a reason the store does not explain by itself. The command exits 1."""


class SourceUnavailable(BuildingsError):
    """The outline file did not answer, or it is not the file the reader expects (D20, D36). The outlines are marked
    unavailable with the reason, the rest of the store is kept, and the command exits 0 so the job goes on."""


# ---------------------------------------------------------------- helpers

def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _pretty(doc) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


def _compact(doc) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".bld-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _lead(line: str) -> int:
    """The street number at the front of a line, for the order of a building's lines (0 when there is none)."""
    match = re.match(r"\d+", line)
    return int(match.group()) if match else 0


def _np():
    import numpy
    return numpy


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _check_store(root: Path) -> None:
    if not (root / "hail" / "index.json").is_file() or not (root / "hail" / "manifest.json").is_file():
        raise BuildingsError("the store has no hail index or manifest; build the hail store first")


# ---------------------------------------------------------------- the download (cache by name, size and Last-Modified)

def _ledger(ledger, method: str, url: str, status, nbytes, state: str, error=None) -> None:
    if ledger is None:
        return
    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"at": _utc_now(), "method": method, "url": url, "status": status, "bytes": nbytes, "cache": state,
            "error": error}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def fetch_cached(cache_dir, name: str, url: str, *, session=None, ledger=None, expect_bytes: int | None = None,
                 what: str = "the outline file", attempts: int = 3) -> tuple[Path, dict]:
    """Return (path, facts) for a file in cache_dir. A HEAD request gives the size and Last-Modified; a cached copy is
    used when its name, size and Last-Modified match, and otherwise the file is fetched, streamed to a temporary file and
    renamed. The GET is tried up to `attempts` times: a dropped connection, a timeout, a cut-off body or an HTTP 5xx is
    tried again after 2 s times the attempt number (D20's source schedule); any other answer fails at once. Each request
    writes one ledger line. A failed request, a file of another size, or a file that is not a zip is a SourceUnavailable
    with the plain reason."""
    import requests                       # the transport and its errors (the retry names them)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    if session is None:
        import requests
        from . import sources
        session = requests.Session()
        session.headers["User-Agent"] = sources.USER_AGENT
    dest = cache / name
    meta_path = cache / (name + ".meta.json")
    try:
        head = session.head(url, allow_redirects=True, timeout=60)
        status = head.status_code
        size = int(head.headers.get("Content-Length", "-1"))
        modified = head.headers.get("Last-Modified")
    except Exception as exc:              # the network: a failed HEAD is the source not answering (D20)
        _ledger(ledger, "HEAD", url, None, None, "failed", type(exc).__name__)
        raise SourceUnavailable(f"{UNAVAILABLE}: the request for {what} failed ({type(exc).__name__})") from None
    _ledger(ledger, "HEAD", url, status, size if size >= 0 else None, "checked")
    if status != 200:
        raise SourceUnavailable(f"{UNAVAILABLE}: the request for {what} answered HTTP {status}")
    if expect_bytes is not None and size >= 0 and size != expect_bytes:
        raise SourceUnavailable(f"{UNAVAILABLE}: {what} is {size} bytes, not the {expect_bytes} the reader expects")
    info = {"name": name, "url": url, "last_modified": modified, "size": size if size >= 0 else None}
    if dest.is_file() and meta_path.is_file():
        try:
            meta = _read_json(meta_path)
        except (OSError, ValueError):
            meta = {}
        if meta.get("name") == name and meta.get("bytes") == dest.stat().st_size and \
                (size < 0 or meta.get("size") == size) and meta.get("last_modified") == modified:
            _ledger(ledger, "GET", url, None, dest.stat().st_size, "hit")
            info.update(bytes=dest.stat().st_size, sha256=_sha256_file(dest), fetched=False)
            return dest, info
    part = cache / (".bld-part-" + name)
    for attempt in range(1, attempts + 1):
        try:
            with session.get(url, stream=True, timeout=900, allow_redirects=True) as response:
                status = response.status_code
                if status == 200:
                    with open(part, "wb") as fh:
                        for chunk in response.iter_content(chunk_size=1 << 20):
                            if chunk:
                                fh.write(chunk)
                    break
                _ledger(ledger, "GET", url, status, None, "failed", f"attempt {attempt}: status {status}")
                if status < 500 or attempt == attempts:
                    raise SourceUnavailable(f"{UNAVAILABLE}: the download of {what} answered HTTP {status}")
        except SourceUnavailable:
            if part.exists():
                part.unlink()
            raise
        except requests.RequestException as exc:     # a dropped connection, a timeout or a cut-off body: tried again
            if part.exists():
                part.unlink()
            _ledger(ledger, "GET", url, None, None, "failed", f"attempt {attempt}: {type(exc).__name__}")
            if attempt == attempts:
                raise SourceUnavailable(f"{UNAVAILABLE}: the download of {what} failed ({type(exc).__name__})") from None
        except Exception as exc:
            if part.exists():
                part.unlink()
            _ledger(ledger, "GET", url, None, None, "failed", type(exc).__name__)
            raise SourceUnavailable(f"{UNAVAILABLE}: the download of {what} failed ({type(exc).__name__})") from None
        time.sleep(2.0 * attempt)                    # the source schedule: 2 s, then 4 s
    nbytes = part.stat().st_size
    if size >= 0 and nbytes != size:
        part.unlink()
        _ledger(ledger, "GET", url, 200, nbytes, "failed", "size")
        raise SourceUnavailable(f"{UNAVAILABLE}: the download of {what} is not the size the server gave")
    with open(part, "rb") as fh:
        magic = fh.read(2)
    if magic != b"PK":
        part.unlink()
        _ledger(ledger, "GET", url, 200, nbytes, "failed", "not a zip")
        raise SourceUnavailable(f"{UNAVAILABLE}: the download of {what} is not a zip file")
    os.replace(part, dest)
    digest = _sha256_file(dest)
    _atomic(meta_path, _compact({"name": name, "url": url, "bytes": nbytes, "size": size if size >= 0 else None,
                                 "last_modified": modified, "sha256": digest, "fetched": _utc_now()}))
    _ledger(ledger, "GET", url, 200, nbytes, "fetched")
    info.update(bytes=nbytes, sha256=digest, fetched=True)
    return dest, info


def download(cache_dir, url: str = SOURCE_URL, *, session=None, ledger=None) -> tuple[Path, dict]:
    """The outline zip in the cache: one HEAD, then up to three GETs (a retry on a dropped connection or an HTTP 5xx) only
    when the cached copy does not match."""
    return fetch_cached(cache_dir, ZIP_NAME, url, session=session, ledger=ledger, expect_bytes=ZIP_BYTES,
                        what="the outline file")


# ---------------------------------------------------------------- the zip: the geodatabase folder and the metadata

def check_zip(zip_path) -> Path:
    """The zip on this machine, checked by name and size (D36): a wrong or changed file is a SourceUnavailable."""
    path = Path(zip_path)
    if not path.is_file():
        raise SourceUnavailable(f"{UNAVAILABLE}: the outline file {zip_path} is not there")
    if path.stat().st_size != ZIP_BYTES:
        raise SourceUnavailable(f"{UNAVAILABLE}: the outline file is {path.stat().st_size} bytes, not {ZIP_BYTES}")
    return path


def extract_gdb(zip_path, folder) -> Path:
    """Extract the geodatabase folder of the zip into folder (the cache, never next to the code). Members are written
    as streams; a name that climbs out of the folder, is absolute or uses a backslash is refused. A member already
    there at its size is kept."""
    root = Path(folder) / GDB_NAME
    prefix = GDB_NAME + "/"
    with zipfile.ZipFile(zip_path) as zf:
        members = [info for info in zf.infolist() if info.filename.startswith(prefix) or info.filename == GDB_NAME]
        if not any(info.filename.startswith(prefix) and not info.is_dir() for info in members):
            raise SourceUnavailable(f"{UNAVAILABLE}: the outline zip holds no {GDB_NAME} folder")
        for info in members:
            name = info.filename
            parts = PurePosixPath(name).parts
            if "\\" in name or name.startswith("/") or ".." in parts:
                raise SourceUnavailable(f"{UNAVAILABLE}: the outline zip holds a member outside its folder")
            target = Path(folder) / name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.is_file() and target.stat().st_size == info.file_size:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(".bld-" + target.name)
            with zf.open(info) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            os.replace(tmp, target)
    if not root.is_dir():
        raise SourceUnavailable(f"{UNAVAILABLE}: the geodatabase folder did not extract")
    return root


def metadata_facts(zip_path) -> dict:
    """The access and use constraints and the publication date of the layer, read from the zip's metadata member."""
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read(META_MEMBER)
    root = ET.fromstring(raw)

    def text(tag: str):
        el = root.find(f".//{tag}")
        return " ".join(el.text.split()) if el is not None and el.text and el.text.strip() else None

    return {"access_constraints": text("accconst"), "use_constraints": text("useconst"),
            "metadata_pubdate": text("pubdate")}


# ---------------------------------------------------------------- the reader: geometry only (D14)

def _read_header(buf: bytes, pos: int):
    endian = "<" if buf[pos] == 1 else ">"
    (code,) = struct.unpack_from(endian + "I", buf, pos + 1)
    pos += 5
    flags = code & 0xF0000000
    base = code & 0x0FFFFFFF
    if flags & 0x20000000:
        pos += 4                          # an SRID follows the type in extended WKB
    iso, kind = divmod(base, 1000)
    hasz = bool(flags & 0x80000000) or iso in (1, 3)
    hasm = bool(flags & 0x40000000) or iso in (2, 3)
    return endian, kind, 2 + int(hasz) + int(hasm), pos


def _polygon_body(buf: bytes, pos: int, endian: str, dim: int, np, out: list) -> int:
    (nrings,) = struct.unpack_from(endian + "I", buf, pos)
    pos += 4
    for _ in range(nrings):
        (npts,) = struct.unpack_from(endian + "I", buf, pos)
        pos += 4
        ring = np.frombuffer(buf, dtype=endian + "f8", count=npts * dim, offset=pos).reshape(npts, dim)[:, :2]
        pos += npts * dim * 8
        out.append(ring)
    return pos


def wkb_polygons(buf: bytes, np, out: list) -> int:
    """Append the rings of one WKB Polygon or MultiPolygon (2D or 3D) to out; return its number of polygons."""
    endian, kind, dim, pos = _read_header(buf, 0)
    if kind == 3:
        _polygon_body(buf, pos, endian, dim, np, out)
        return 1
    if kind == 6:
        (npoly,) = struct.unpack_from(endian + "I", buf, pos)
        pos += 4
        for _ in range(npoly):
            e2, k2, d2, p2 = _read_header(buf, pos)
            if k2 != 3:
                raise SourceUnavailable(f"{UNAVAILABLE}: a part of the outlines is not a polygon")
            pos = _polygon_body(buf, p2, e2, d2, np, out)
        return npoly
    raise SourceUnavailable(f"{UNAVAILABLE}: the outline geometry type {kind} is not a polygon")


def _pyogrio():
    try:
        import pyogrio
        import pyogrio.raw  # noqa: F401
    except ImportError:
        raise SourceUnavailable(f"{UNAVAILABLE}: the geometry reader is not installed (pyogrio)") from None
    return pyogrio


class Geo:
    """The outlines' rings: fx, fy (every vertex, closed rings, degrees), ring_start (R+1 offsets into the vertices),
    feat_ring_start (F+1 offsets into the rings) and polygons (the number of polygons of each outline)."""

    def __init__(self, fx, fy, ring_start, feat_ring_start, polygons, stats):
        self.fx, self.fy = fx, fy
        self.ring_start, self.feat_ring_start = ring_start, feat_ring_start
        self.polygons = polygons
        self.stats = stats

    @property
    def count(self) -> int:
        return len(self.feat_ring_start) - 1


def geo_from_rings(rings, feat_ring_counts, polygons, np, stats: dict | None = None) -> Geo:
    """Build the arrays from rings (each an (n, 2) array of lon, lat). A ring that does not close is closed here and
    counted; a ring with fewer than four points after that is counted as short (it stays, so no vertex is lost)."""
    closed = []
    fixed = short = 0
    for ring in rings:
        arr = np.asarray(ring, dtype=np.float64).reshape(-1, 2)
        if len(arr) and (arr[0, 0] != arr[-1, 0] or arr[0, 1] != arr[-1, 1]):
            arr = np.vstack([arr, arr[:1]])
            fixed += 1
        if len(arr) < 4:
            short += 1
        closed.append(arr)
    lens = np.array([len(r) for r in closed], dtype=np.int64)
    coords = np.concatenate(closed) if closed else np.zeros((0, 2))
    ring_start = np.concatenate([[0], np.cumsum(lens)]).astype(np.int64)
    feat_ring_start = np.concatenate([[0], np.cumsum(np.asarray(feat_ring_counts, dtype=np.int64))]).astype(np.int64)
    out_stats = dict(stats or {})
    out_stats.update(rings=len(closed), rings_closed_in_source=len(closed) - fixed,
                     rings_not_closed_in_source=fixed, rings_short=short, vertices=int(len(coords)))
    return Geo(coords[:, 0].copy(), coords[:, 1].copy(), ring_start, feat_ring_start,
               np.asarray(polygons, dtype=np.int64), out_stats)


def read_outlines(gdb_path, np) -> Geo:
    """Every outline of the layer, geometry only. The layer's name, geometry type, WGS 84 CRS and feature count are
    checked first (D36): a changed file is a SourceUnavailable. No attribute column is requested."""
    pyogrio = _pyogrio()
    try:
        layers = pyogrio.list_layers(str(gdb_path))
        names = [str(row[0]) for row in layers]
        info = pyogrio.read_info(str(gdb_path), layer=LAYER)
    except Exception as exc:
        raise SourceUnavailable(f"{UNAVAILABLE}: the geodatabase did not open ({type(exc).__name__})") from None
    if names != [LAYER]:
        raise SourceUnavailable(f"{UNAVAILABLE}: the geodatabase layers are {names}, not {[LAYER]}")
    if info.get("geometry_type") not in GEOMETRY_TYPES:
        raise SourceUnavailable(f"{UNAVAILABLE}: the layer's geometry is {info.get('geometry_type')}")
    if "4326" not in str(info.get("crs")):
        raise SourceUnavailable(f"{UNAVAILABLE}: the layer's CRS is {info.get('crs')}, not WGS 84 (EPSG:4326)")
    if int(info.get("features", -1)) != EXPECTED_FEATURES:
        raise SourceUnavailable(f"{UNAVAILABLE}: the layer has {info.get('features')} features, not {EXPECTED_FEATURES}")
    _meta, _fids, geom, fields = pyogrio.raw.read(str(gdb_path), layer=LAYER, columns=[], read_geometry=True)
    if len(fields) != 0:
        raise SourceUnavailable(f"{UNAVAILABLE}: the reader received attribute columns it did not ask for")
    if len(geom) != EXPECTED_FEATURES:
        raise SourceUnavailable(f"{UNAVAILABLE}: the reader read {len(geom)} outlines, not {EXPECTED_FEATURES}")
    return _geo_from_wkb(geom, np)


def _geo_from_wkb(geom, np) -> Geo:
    rings: list = []
    feat_counts: list = []
    polys: list = []
    nulls = empties = 0
    for buf in geom:
        if buf is None or len(buf) == 0:
            nulls += 1
            continue
        start = len(rings)
        npoly = wkb_polygons(bytes(buf), np, rings)
        if len(rings) == start:
            empties += 1
            continue
        feat_counts.append(len(rings) - start)
        polys.append(npoly)
    if nulls or empties:
        raise SourceUnavailable(f"{UNAVAILABLE}: {nulls} outlines have no geometry and {empties} are empty")
    return geo_from_rings(rings, feat_counts, polys, np,
                          stats={"features": len(feat_counts), "polygons": int(sum(polys)),
                                 "multipart": int(sum(1 for p in polys if p > 1)), "max_polygons": int(max(polys))
                                 if polys else 0})


# ---------------------------------------------------------------- the derived arrays: area, centroid, dot, edges

_DIRS = ((1.0, 0.0), (0.0, 1.0), (math.sqrt(0.5), math.sqrt(0.5)), (-math.sqrt(0.5), math.sqrt(0.5)))
HOW = ("centroid", "chord", "chord-fallback", "vertex")


def _longest_chord(ex1, ey1, ex2, ey2, cx, cy, dirs, np):
    """(length, (x, y)): the longest interior interval of the lines through (cx, cy) in the given directions, and its
    midpoint; None when no line crosses the outline."""
    best = None
    for dx, dy in dirs:
        s1 = dx * (ey1 - cy) - dy * (ex1 - cx)
        s2 = dx * (ey2 - cy) - dy * (ex2 - cx)
        crossing = (s1 > 0) != (s2 > 0)
        if not crossing.any():
            continue
        a = s1[crossing]
        b = s2[crossing]
        frac = a / (a - b)
        qx = ex1[crossing] + (ex2[crossing] - ex1[crossing]) * frac
        qy = ey1[crossing] + (ey2[crossing] - ey1[crossing]) * frac
        t = np.sort((qx - cx) * dx + (qy - cy) * dy)
        for i in range(0, len(t) - 1, 2):      # even-odd: the intervals between crossings 0-1, 2-3, ... are interior
            length = float(t[i + 1] - t[i])
            if best is None or length > best[0]:
                tm = float((t[i] + t[i + 1]) / 2.0)
                best = (length, (cx + tm * dx, cy + tm * dy))
    return best


def _dot_for(ex1, ey1, ex2, ey2, cx, cy, vx, vy, np):
    """The dot of an outline whose centroid is outside it: the midpoint of the longest interior chord through the
    centroid (four directions); if no line through the centroid crosses it (parts apart), the midpoint nearest the
    centroid of the chords on horizontal lines through its vertices; the first vertex only if nothing else exists."""
    best = _longest_chord(ex1, ey1, ex2, ey2, cx, cy, _DIRS, np)
    if best is not None:
        return best[1][0], best[1][1], HOW[1]
    nearest = None
    for y in np.unique(np.concatenate([ey1, ey2])):
        found = _longest_chord(ex1, ey1, ex2, ey2, cx, float(y), ((1.0, 0.0),), np)
        if found is not None:
            d = (found[1][0] - cx) ** 2 + (found[1][1] - cy) ** 2
            if nearest is None or d < nearest[0]:
                nearest = (d, found[1])
    if nearest is not None:
        return nearest[1][0], nearest[1][1], HOW[2]
    return float(vx[0]), float(vy[0]), HOW[3]


# ---------------------------------------------------------------- the dot on the rounded rings (D15, exact)

def _edge_test(der: "Derived", eidx, qx, qy, local, n: int, np):
    """The exact test of one point per edge against the rounded rings, in 5-decimal integers (D15). eidx are the
    edges (their first vertex is der.ek[eidx]), qx and qy the point of each edge's outline, and local the outline
    number of each edge (0 to n - 1). Returns, per outline, whether its point is strictly inside: on no edge, and
    crossed an odd number of times by the edges (the even-odd rule over all rings, D14). Integer arithmetic only,
    so a point on an edge is never counted as inside."""
    v0 = der.ek[eidx]
    x1 = der.vx5[v0]
    y1 = der.vy5[v0]
    x2 = der.vx5[v0 + 1]
    y2 = der.vy5[v0 + 1]
    ex = x2 - x1
    ey = y2 - y1
    dxq = qx - x1
    dyq = qy - y1
    on = (((ex * dyq - ey * dxq) == 0) & (qx >= np.minimum(x1, x2)) & (qx <= np.maximum(x1, x2))
          & (qy >= np.minimum(y1, y2)) & (qy <= np.maximum(y1, y2)))
    lhs = dxq * ey
    rhs = dyq * ex
    hit = ((y1 > qy) != (y2 > qy)) & np.where(ey > 0, lhs < rhs, lhs > rhs)
    on_n = np.bincount(local, weights=on.astype(np.float64), minlength=n)
    hit_n = np.bincount(local, weights=hit.astype(np.float64), minlength=n)
    return (on_n == 0) & (np.mod(hit_n, 2) == 1)


def _lattice_strict_for(der: "Derived", fs, qx, qy, np):
    """For the outlines fs and one point each (qx, qy, in 5-decimal units): whether each point is strictly inside its
    outline's rounded rings (see _edge_test)."""
    counts = der.e_count[fs]
    total = int(counts.sum())
    local = np.repeat(np.arange(len(fs), dtype=np.int64), counts)
    within = np.arange(total, dtype=np.int64) - np.repeat(np.cumsum(counts) - counts, counts)
    eidx = np.repeat(der.e_start[fs], counts) + within
    return _edge_test(der, eidx, qx[local], qy[local], local, len(fs), np)


def _lattice_strict(der: "Derived", lon5, lat5, np, step: int = 100_000):
    """For every outline, whether its point (lon5, lat5, one per outline) is strictly inside its rounded rings."""
    out = np.zeros(der.count, dtype=bool)
    for a in range(0, der.count, step):
        b = min(der.count, a + step)
        out[a:b] = _lattice_strict_for(der, np.arange(a, b, dtype=np.int64), lon5[a:b], lat5[a:b], np)
    return out


def _settle_dots(der: "Derived", np) -> None:
    """Move each dot that rounding put on an edge, or outside, of its own rounded rings (D15, the exact check). The
    new dot is the nearest 5-decimal point strictly inside, within DOT_SEARCH_UNITS on each axis of the rounded dot (the
    square of that radius); the search is nearest first, then by the x and then the y offset. An outline with no such
    point keeps its rounded dot and is counted as an exception (der.dot_exception). der.dots_moved counts the dots
    that moved."""
    der.dot_exception = np.zeros(der.count, dtype=bool)
    der.dots_moved = 0
    bad = np.nonzero(~_lattice_strict(der, der.dot_lon5, der.dot_lat5, np))[0]
    if not len(bad):
        return
    r = DOT_SEARCH_UNITS
    offsets = sorted(((dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)),
                     key=lambda o: (o[0] * o[0] + o[1] * o[1], o[0], o[1]))
    offs = np.array(offsets, dtype=np.int64)
    found = np.full(len(bad), -1, dtype=np.int64)
    for k, (dx, dy) in enumerate(offsets):
        pending = np.nonzero(found < 0)[0]
        if not len(pending):
            break
        fs = bad[pending]
        ok = _lattice_strict_for(der, fs, der.dot_lon5[fs] + dx, der.dot_lat5[fs] + dy, np)
        found[pending[ok]] = k
    moved = found >= 0
    fs = bad[moved]
    der.dot_lon5[fs] += offs[found[moved], 0]
    der.dot_lat5[fs] += offs[found[moved], 1]
    der.dot_exception[bad[~moved]] = True
    der.dots_moved = int(moved.sum())


class Derived:
    """Per outline: area, centroid, the dot (absolute degrees), its method, the bounding box, the edges (absolute
    degrees, edge k runs from vertex ek[k] to vertex ek[k] + 1), and the outline's first edge and edge count."""


def derive(geo: Geo, np) -> Derived:
    fx, fy = geo.fx, geo.fy
    nv = len(fx)
    nr = len(geo.ring_start) - 1
    nf = geo.count
    ox = float(fx.mean()) if nv else 0.0
    oy = float(fy.mean()) if nv else 0.0
    rx = fx - ox
    ry = fy - oy
    ring_len = np.diff(geo.ring_start)
    ring_of_v = np.repeat(np.arange(nr, dtype=np.int64), ring_len)
    feat_of_ring = np.repeat(np.arange(nf, dtype=np.int64), np.diff(geo.feat_ring_start))
    feat_of_v = feat_of_ring[ring_of_v]
    end_of_v = geo.ring_start[1:][ring_of_v]
    ek = np.nonzero(np.arange(nv, dtype=np.int64) + 1 < end_of_v)[0]
    ex1, ey1, ex2, ey2 = rx[ek], ry[ek], rx[ek + 1], ry[ek + 1]
    e_ring = ring_of_v[ek]
    e_feat = feat_of_ring[e_ring]
    e_start = np.searchsorted(e_feat, np.arange(nf + 1, dtype=np.int64)).astype(np.int64)
    cross = ex1 * ey2 - ex2 * ey1
    ring_area = 0.5 * np.bincount(e_ring, weights=cross, minlength=nr)
    ring_mx = np.bincount(e_ring, weights=(ex1 + ex2) * cross, minlength=nr) / 6.0
    ring_my = np.bincount(e_ring, weights=(ey1 + ey2) * cross, minlength=nr) / 6.0
    absA = np.abs(ring_area)
    fmax = np.maximum.reduceat(absA, geo.feat_ring_start[:-1])
    top = np.nonzero(absA == fmax[feat_of_ring])[0]
    uf, first = np.unique(feat_of_ring[top], return_index=True)
    sign = np.ones(nf)
    sign[uf] = np.where(ring_area[top[first]] < 0, -1.0, 1.0)     # the largest ring of each outline is positive
    o_r = sign[feat_of_ring]
    area = np.bincount(feat_of_ring, weights=ring_area * o_r, minlength=nf)
    mx = np.bincount(feat_of_ring, weights=ring_mx * o_r, minlength=nf)
    my = np.bincount(feat_of_ring, weights=ring_my * o_r, minlength=nf)
    vcount = np.maximum(np.bincount(feat_of_v, minlength=nf), 1).astype(np.float64)
    vmx = np.bincount(feat_of_v, weights=rx, minlength=nf) / vcount
    vmy = np.bincount(feat_of_v, weights=ry, minlength=nf) / vcount
    with np.errstate(divide="ignore", invalid="ignore"):
        cx = mx / area
        cy = my / area
    degenerate = ~(np.isfinite(cx) & np.isfinite(cy) & (np.abs(area) > 0))
    cx = np.where(degenerate, vmx, cx)
    cy = np.where(degenerate, vmy, cy)
    cyf = cy[e_feat]
    cxf = cx[e_feat]
    crossing = (ey1 > cyf) != (ey2 > cyf)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = ex1 + (cyf - ey1) * (ex2 - ex1) / (ey2 - ey1)
    hits = (crossing & (cxf < xint)).astype(np.float64)
    inside = (np.bincount(e_feat, weights=hits, minlength=nf) % 2) == 1
    dot_x = cx.copy()
    dot_y = cy.copy()
    how = np.zeros(nf, dtype=np.int8)
    how[degenerate] = 3
    chord_needed = np.nonzero((~inside) & (~degenerate))[0]
    for f in chord_needed:
        s, e = int(e_start[f]), int(e_start[f + 1])
        v0, v1 = int(geo.ring_start[geo.feat_ring_start[f]]), int(geo.ring_start[geo.feat_ring_start[f + 1]])
        x, y, name = _dot_for(ex1[s:e], ey1[s:e], ex2[s:e], ey2[s:e], float(cx[f]), float(cy[f]),
                              rx[v0:v1], ry[v0:v1], np)
        dot_x[f], dot_y[f] = x, y
        how[f] = HOW.index(name)
    for f in np.nonzero(degenerate)[0]:
        if how[f] == 3:
            v0 = int(geo.ring_start[geo.feat_ring_start[f]])
            dot_x[f], dot_y[f] = rx[v0], ry[v0]
    v_first = geo.ring_start[geo.feat_ring_start[:-1]]
    der = Derived()
    der.count = nf
    der.ox, der.oy = ox, oy
    der.ek = ek
    der.e_start = e_start
    der.e_count = np.diff(e_start)
    der.dot_lon5 = np.rint((dot_x + ox) * SCALE).astype(np.int64)
    der.dot_lat5 = np.rint((dot_y + oy) * SCALE).astype(np.int64)
    der.how = how
    der.inside_centroid = inside
    der.degenerate = degenerate
    der.area = area * 1.0
    der.bbox = (np.minimum.reduceat(fx, v_first), np.minimum.reduceat(fy, v_first),
                np.maximum.reduceat(fx, v_first), np.maximum.reduceat(fy, v_first))
    der.edge_x1, der.edge_y1 = fx[ek], fy[ek]
    der.edge_x2, der.edge_y2 = fx[ek + 1], fy[ek + 1]
    der.vx5 = np.rint(fx * SCALE).astype(np.int64)
    der.vy5 = np.rint(fy * SCALE).astype(np.int64)
    _settle_dots(der, np)
    return der


# ---------------------------------------------------------------- the address rows (read from the store, never the zip)

def load_rows(root: Path, np, expect: int | None) -> list:
    """Every address row of the store, from the search index's letter files (a/idx), which keep every row (D28): a
    list of (lon5, lat5, line, city, zip, class) sorted by position, line, city and zip, the order the addresses
    module writes its shards in. expect is the row count of the addresses block; a different count is an error."""
    idx = root / "hail" / "a" / "idx"
    cities = _read_json(idx / "cities.json")["cities"]
    rows = []
    for city, entry in cities.items():
        folder = idx / entry.get("dir", addresses.slug(city))
        for key in entry["keys"]:
            doc = _read_json(folder / f"{addresses.file_key(key)}.json")
            for number, street, unit, lon, lat, zip_code, cls in doc["a"]:
                line = " ".join(text for text in (number, street, unit) if text)
                rows.append((round(lon * SCALE), round(lat * SCALE), line, city, zip_code, cls))
    rows.sort()
    if expect is not None and len(rows) != expect:
        raise BuildingsError(f"the address rows in the search index are {len(rows)}, not the {expect} the list holds")
    return rows


# ---------------------------------------------------------------- the join (D15, D32)

def join(der: Derived, lon5, lat5, cls_codes, np, geo: Geo):
    """Join the address points to the outlines. Returns (match, in_any, near_any): match[i] is the outline of row i
    when row i is a Structure point inside an outline or within MATCH_M of its edge (inside wins; then the nearest; ties to
    the lower outline number), else -1; in_any[i] is the lowest outline containing row i (any class), else count;
    near_any[i] the nearest outline within MATCH_M (any class, not inside), else count."""
    P = len(lon5)
    nf = der.count
    match = np.full(P, -1, dtype=np.int64)
    in_any = np.full(P, nf, dtype=np.int64)
    near_any = np.full(P, nf, dtype=np.int64)
    if P == 0 or nf == 0:
        return match, in_any, near_any
    px = lon5 / SCALE
    py = lat5 / SCALE
    minx, miny, maxx, maxy = der.bbox
    pad, G = PAD_DEG, CELL_DEG
    X0 = float(minx.min()) - pad
    Y0 = float(miny.min()) - pad
    cx0 = np.floor((minx - pad - X0) / G).astype(np.int64)
    cx1 = np.floor((maxx + pad - X0) / G).astype(np.int64)
    cy0 = np.floor((miny - pad - Y0) / G).astype(np.int64)
    cy1 = np.floor((maxy + pad - Y0) / G).astype(np.int64)
    nxc = cx1 - cx0 + 1
    nyc = cy1 - cy0 + 1
    cnt = nxc * nyc
    total = int(cnt.sum())
    fidr = np.repeat(np.arange(nf, dtype=np.int64), cnt)
    local = np.arange(total, dtype=np.int64) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    ix = cx0[fidr] + local // nyc[fidr]
    iy = cy0[fidr] + local % nyc[fidr]
    NY = int(cy1.max()) + 2
    NX = int(cx1.max()) + 1
    key = ix * NY + iy
    order = np.argsort(key, kind="stable")
    key_s = key[order]
    fid_s = fidr[order]
    pix = np.floor((px - X0) / G).astype(np.int64)
    piy = np.floor((py - Y0) / G).astype(np.int64)
    valid = (pix >= 0) & (pix < NX) & (piy >= 0) & (piy < NY - 1)
    pkey = np.where(valid, pix * NY + piy, -1)
    ex1, ey1, ex2, ey2 = der.edge_x1, der.edge_y1, der.edge_x2, der.edge_y2
    CH = 50_000
    for a in range(0, P, CH):
        b = min(P, a + CH)
        n = b - a
        k = pkey[a:b]
        lo = np.searchsorted(key_s, k, side="left")
        hi = np.searchsorted(key_s, k, side="right")
        cnt_p = hi - lo
        tot = int(cnt_p.sum())
        if tot == 0:
            continue
        pid = np.repeat(np.arange(n, dtype=np.int64), cnt_p)
        pos = np.arange(tot, dtype=np.int64) - np.repeat(np.cumsum(cnt_p) - cnt_p, cnt_p) + np.repeat(lo, cnt_p)
        pf = fid_s[pos]
        pxp = px[a:b][pid]
        pyp = py[a:b][pid]
        keep = (pxp >= minx[pf] - pad) & (pxp <= maxx[pf] + pad) & (pyp >= miny[pf] - pad) & (pyp <= maxy[pf] + pad)
        pid, pf, pxp, pyp = pid[keep], pf[keep], pxp[keep], pyp[keep]
        if len(pf) == 0:
            continue
        ne = der.e_count[pf]
        tote = int(ne.sum())
        poff = np.cumsum(ne) - ne
        pe = np.repeat(np.arange(len(pf), dtype=np.int64), ne)
        eidx = np.arange(tote, dtype=np.int64) - np.repeat(poff, ne) + np.repeat(der.e_start[pf], ne)
        X1, Y1, X2, Y2 = ex1[eidx], ey1[eidx], ex2[eidx], ey2[eidx]
        pxe = pxp[pe]
        pye = pyp[pe]
        cond = (Y1 > pye) != (Y2 > pye)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = X1 + (pye - Y1) * (X2 - X1) / (Y2 - Y1)
        hit = (cond & (pxe < xint)).astype(np.float64)
        inside_pair = (np.bincount(pe, weights=hit, minlength=len(pf)) % 2) == 1
        lat_r = np.radians(pyp)
        mlat = (111132.954 - 559.822 * np.cos(2 * lat_r) + 1.175 * np.cos(4 * lat_r))[pe]
        mlon = (111412.84 * np.cos(lat_r) - 93.5 * np.cos(3 * lat_r))[pe]
        ax = (X1 - pxe) * mlon
        ay = (Y1 - pye) * mlat
        ddx = (X2 - pxe) * mlon - ax
        ddy = (Y2 - pye) * mlat - ay
        L2 = ddx * ddx + ddy * ddy
        safe = np.where(L2 > 0, L2, 1.0)
        t = np.clip(np.where(L2 > 0, -(ax * ddx + ay * ddy) / safe, 0.0), 0.0, 1.0)
        dist_pair = np.minimum.reduceat(np.hypot(ax + t * ddx, ay + t * ddy), poff)
        in_fid = np.full(n, nf, dtype=np.int64)
        if inside_pair.any():
            np.minimum.at(in_fid, pid[inside_pair], pf[inside_pair])
        near_ok = (~inside_pair) & (dist_pair <= MATCH_M)
        dmin = np.full(n, np.inf)
        if near_ok.any():
            np.minimum.at(dmin, pid[near_ok], dist_pair[near_ok])
        cand = near_ok & (dist_pair == dmin[pid])
        near_fid = np.full(n, nf, dtype=np.int64)
        if cand.any():
            np.minimum.at(near_fid, pid[cand], pf[cand])
        has_in = in_fid < nf
        has_near = near_fid < nf
        in_any[a:b] = in_fid
        near_any[a:b] = np.where(has_in, nf, near_fid)
        chosen = np.where(has_in, in_fid, np.where(has_near, near_fid, -1))
        match[a:b] = np.where(cls_codes[a:b] == 0, chosen, -1)     # class 0 is S: only Structure points join
    return match, in_any, near_any


# ---------------------------------------------------------------- the shards: b/ (outlines) and a/ (unmatched addresses)

def _tile_arrays(lat5, lon5, np):
    row = (5500000 - lat5) // 1000
    col = (lon5 + 13000000) // 1000
    return row // hail.TILE, col // hail.TILE


class _Render:
    """The text of each outline's entry, built once; the lines and the common city and zip are added per shard."""

    def __init__(self, geo: Geo, der: Derived, lines_of: dict, rows_of: list, np):
        self.lines_of = lines_of
        self.rows_of = rows_of
        self.core = [None] * der.count
        vx = der.vx5 / SCALE
        vy = der.vy5 / SCALE
        self.xs = (der.dot_lon5 * SUB).tolist()
        self.ys = (der.dot_lat5 * SUB).tolist()
        rs = geo.ring_start.tolist()
        fr = geo.feat_ring_start.tolist()
        dlon = (der.dot_lon5 / SCALE).tolist()
        dlat = (der.dot_lat5 / SCALE).tolist()
        for f in range(der.count):
            rings = []
            for r in range(fr[f], fr[f + 1]):
                s, e = rs[r], rs[r + 1]
                rings.append([[x, y] for x, y in zip(vx[s:e].tolist(), vy[s:e].tolist())])
            self.core[f] = '{"p":%s,"g":%s' % (json.dumps([dlon[f], dlat[f]]), json.dumps(rings))

    def shard(self, name: str, box, items) -> bytes:
        counter: Counter = Counter()
        m = 0
        for f in items:
            m += self.rows_of[f]
            for _line, city, zip_code in self.lines_of.get(f, ()):
                counter[(city, zip_code)] += 1
        common = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if counter else None
        parts = []
        for f in items:
            lines = self.lines_of.get(f, ())
            if not lines:
                parts.append(self.core[f] + ',"l":[]}')
                continue
            tail = ',"l":' + json.dumps([line for line, _c, _z in lines])
            zs = [None if (c, z) == common else [c, z] for _line, c, z in lines]
            if any(v is not None for v in zs):
                tail += ',"z":' + json.dumps(zs)
            parts.append(self.core[f] + tail + "}")
        west, south, east, north = box
        bounds = [addresses._out_floor(west), addresses._out_floor(south), addresses._out_ceil(east),
                  addresses._out_ceil(north)]
        header = '{"f":"%s","b":%s,"n":%d,"m":%d,"c":%s,"a":[' % (
            FORMAT, json.dumps(bounds), len(items), m, json.dumps(list(common)) if common else "null")
        return (header + ",".join(parts) + "]}").encode("utf-8")


def _b_leaves(name: str, box, items, depth: int, render: _Render, xs, ys) -> list:
    data = render.shard(name, box, items)
    if len(data) <= SHARD_BYTES or depth >= DEPTH_CAP or len(items) <= 1:
        return [(name, box, items, data)]
    west, south, east, north = box
    mid_lon, mid_lat = (west + east) // 2, (south + north) // 2
    boxes = {"0": (west, mid_lat, mid_lon, north), "1": (mid_lon, mid_lat, east, north),
             "2": (west, south, mid_lon, mid_lat), "3": (mid_lon, south, east, mid_lat)}
    parts = {digit: [] for digit in boxes}
    for f in items:
        parts[addresses.quarter(box, xs[f], ys[f])].append(f)
    out = []
    for digit in "0123":
        if parts[digit]:
            out.extend(_b_leaves(name + digit, boxes[digit], parts[digit], depth + 1, render, xs, ys))
    return out


def _a_files(rows: list, match, keep_all: bool, np) -> dict:
    """The address shards (addresses.py's quadtree and bounds; the rows that stay are the unmatched ones unless keep_all).
    Returns {"a/<name>.json": bytes} for every leaf of the full set, so every name of the addresses module is kept."""
    by_tile: dict = defaultdict(list)
    for i, row in enumerate(rows):
        by_tile[addresses.tile_of(row[1], row[0])].append(i)
    files = {}
    for tile_row, tile_col in sorted(by_tile):
        tile = hail.tile_name(tile_row, tile_col)
        points = [(rows[i][0] * SUB, rows[i][1] * SUB, i) for i in by_tile[(tile_row, tile_col)]]
        for name, bounds, leaf_points in addresses.quadtree(tile, addresses.tile_box(tile_row, tile_col), points):
            kept = [p[2] for p in leaf_points if keep_all or int(match[p[2]]) < 0]
            west, south, east, north = bounds
            doc = {"f": addresses.FORMAT,
                   "b": [addresses._out_floor(west), addresses._out_floor(south), addresses._out_ceil(east),
                         addresses._out_ceil(north)],
                   "n": len(kept),
                   "a": [[rows[i][0] / SCALE, rows[i][1] / SCALE, rows[i][2], rows[i][3], rows[i][4], rows[i][5]]
                         for i in kept]}
            files[f"a/{name}.json"] = addresses._compact(doc)
    return files


def _overhang(der: Derived, items, box, np) -> float:
    west, south, east, north = box
    minx, miny, maxx, maxy = der.bbox
    idx = np.asarray(items, dtype=np.int64)
    w = west / (SUB * SCALE)
    s = south / (SUB * SCALE)
    e = east / (SUB * SCALE)
    n = north / (SUB * SCALE)
    over = np.maximum.reduce([np.zeros(len(idx)), w - minx[idx], maxx[idx] - e, s - miny[idx], maxy[idx] - n])
    return float(over.max()) if len(over) else 0.0


# ---------------------------------------------------------------- the plan: every file, and the measures

def _lines_for(rows, match, np) -> tuple[dict, list]:
    lines_of: dict = defaultdict(list)
    idx = np.nonzero(match >= 0)[0]
    for i in idx.tolist():
        f = int(match[i])
        lines_of[f].append((rows[i][2], rows[i][3], rows[i][4]))
    for f in list(lines_of):
        unique = sorted(set(lines_of[f]), key=lambda t: (_lead(t[0]), t[0], t[1], t[2]))
        lines_of[f] = unique
    return lines_of, idx


def plan(geo: Geo, der: Derived, rows: list, b1_tiles: set, np, *, counties=None, addresses_ok: bool = True,
         address_block: dict | None = None, boxes=None) -> tuple[dict, dict]:
    """Compute every file of the store part and its measures. Returns (files, stats); files maps store-relative names
    ("b/<name>.json", "a/<name>.json", "counts.json") to their bytes. Nothing is written here."""
    t0 = time.time()
    nf = der.count
    lon5 = np.array([r[0] for r in rows], dtype=np.int64)
    lat5 = np.array([r[1] for r in rows], dtype=np.int64)
    cls_codes = np.array([CLASS_LETTERS.index(r[5]) for r in rows], dtype=np.int64)
    match, in_any, near_any = join(der, lon5, lat5, cls_codes, np, geo) if addresses_ok else (
        np.full(len(rows), -1, dtype=np.int64), np.full(len(rows), nf, dtype=np.int64),
        np.full(len(rows), nf, dtype=np.int64))
    t_join = time.time() - t0
    lines_of, matched_idx = _lines_for(rows, match, np)
    rows_of = [0] * nf
    for i in matched_idx.tolist():
        rows_of[int(match[i])] += 1
    render = _Render(geo, der, lines_of, rows_of, np)
    t_render = time.time() - t0 - t_join
    tile_row, tile_col = _tile_arrays(der.dot_lat5, der.dot_lon5, np)
    order = np.lexsort((np.arange(nf), der.dot_lat5, der.dot_lon5, tile_col, tile_row))
    files: dict = {}
    b_leaves = []
    split = {}
    tiles_b = []
    per_tile_count = Counter()
    overhang = 0.0
    tr_o = tile_row[order]
    tc_o = tile_col[order]
    starts = np.nonzero(np.r_[True, (tr_o[1:] != tr_o[:-1]) | (tc_o[1:] != tc_o[:-1])])[0].tolist() + [nf]
    order_l = order.tolist()
    for g in range(len(starts) - 1):
        s, e = starts[g], starts[g + 1]
        items = order_l[s:e]
        trow, tcol = int(tr_o[s]), int(tc_o[s])
        tile = hail.tile_name(trow, tcol)
        per_tile_count[tile] = len(items)
        tiles_b.append(tile)
        leaves = _b_leaves(tile, addresses.tile_box(trow, tcol), items, 0, render, render.xs, render.ys)
        if len(leaves) > 1:
            split[tile] = leaves
        for name, box, leaf_items, data in leaves:
            files[f"b/{name}.json"] = data
            b_leaves.append((name, tile, box, leaf_items, data))
            overhang = max(overhang, _overhang(der, leaf_items, box, np))
    t_shards = time.time() - t0 - t_join - t_render
    # the address shards: the unmatched rows (D28), with every leaf of the full set
    if addresses_ok:
        a_files = _a_files(rows, match, False, np)
        files.update(a_files)
        a_rows_kept = int((match < 0).sum())
    else:
        a_files = {}
        a_rows_kept = 0
    counts_tiles = {tile: n for tile, n in sorted(per_tile_count.items())}
    files["counts.json"] = _compact({"f": COUNTS_FORMAT, "tiles": counts_tiles, "total": nf})
    # the measures
    depth = Counter()
    largest = None
    b_bytes = 0
    for name, tile, box, leaf_items, data in b_leaves:
        depth[len(name) - len(tile)] += 1
        b_bytes += len(data)
        if largest is None or (len(data), name) > (largest["bytes"], largest["name"]):
            largest = {"name": name, "bytes": len(data), "outlines": len(leaf_items)}
    a_bytes = sum(len(v) for v in a_files.values())
    a_largest = max(((len(v), k) for k, v in a_files.items()), default=(0, ""))
    empty_a = sum(1 for v in a_files.values() if v.endswith(b'"a":[]}'))
    stats = _measure(geo, der, lon5, lat5, rows, match, in_any, near_any, cls_codes, b1_tiles, counts_tiles,
                     np, boxes or {}, counties)
    stats["shards"] = {"count": len(b_leaves), "bytes": b_bytes, "largest": largest,
                       "depths": {str(k): v for k, v in sorted(depth.items())}}
    stats["a"] = {"shards": len(a_files), "bytes": a_bytes, "rows": a_rows_kept,
                  "largest": {"name": a_largest[1], "bytes": a_largest[0]}, "empty": empty_a}
    stats["overhang_deg"] = round(overhang, 6)
    stats["seconds"] = {"join": round(t_join, 1), "render": round(t_render, 1), "shards": round(t_shards, 1),
                        "total": round(time.time() - t0, 1)}
    stats["tiles"] = tiles_b
    stats["split_tiles"] = sorted(split)
    stats["split_names"] = {tile: [leaf[0] for leaf in leaves] for tile, leaves in split.items()}
    stats["split_boxes"] = {tile: [[leaf[0], [addresses._out_floor(leaf[1][0]), addresses._out_floor(leaf[1][1]),
                                              addresses._out_ceil(leaf[1][2]), addresses._out_ceil(leaf[1][3])]]
                                   for leaf in leaves] for tile, leaves in split.items()}
    return files, stats


def _measure(geo, der, lon5, lat5, rows, match, in_any, near_any, cls_codes, b1_tiles, counts_tiles, np,
             boxes, counties) -> dict:
    nf = der.count
    P = len(rows)
    is_s = cls_codes == 0
    inside_any = in_any < nf
    near_only = near_any < nf
    matched = match >= 0
    unmatched = ~matched
    by_class = {letter: int((cls_codes == i).sum()) for i, letter in enumerate(CLASS_LETTERS)}
    unmatched_by_class = {letter: int(((cls_codes == i) & unmatched).sum()) for i, letter in enumerate(CLASS_LETTERS)}
    fp_inside_s = np.zeros(nf, dtype=bool)
    fp_near_s = np.zeros(nf, dtype=bool)
    if matched.any():
        ins = matched & inside_any
        fp_inside_s[match[ins]] = True
        fp_near_s[match[matched & ~inside_any]] = True
    tiles_b1 = set(b1_tiles)
    outside_fp = 0
    outside_names = Counter()
    for name, count in counts_tiles.items():
        if name not in tiles_b1:
            outside_fp += count
            outside_names[name] = count
    outside_rows = 0
    if P:
        rt, rc = _tile_arrays(lat5, lon5, np)
        outside_rows = sum(1 for a, b in zip(rt.tolist(), rc.tolist()) if hail.tile_name(a, b) not in tiles_b1)
    multipart = int((geo.polygons > 1).sum())
    counts = {
        "footprints": nf,
        "polygons": int(geo.polygons.sum()),
        "multipart": multipart,
        "rings": int(len(geo.ring_start) - 1),
        "vertices": int(len(geo.fx)),
        "closed_in_source": int(geo.stats.get("rings_closed_in_source", 0)),
        "rings_not_closed_in_source": int(geo.stats.get("rings_not_closed_in_source", 0)),
        "rings_short": int(geo.stats.get("rings_short", 0)),
        "centroid_inside": int(der.inside_centroid.sum()),
        "dot_method": {HOW[i]: int((der.how == i).sum()) for i in range(len(HOW))},
        "with_address_inside": int(fp_inside_s.sum()),
        "with_address_within_15m_only": int((fp_near_s & ~fp_inside_s).sum()),
        "with_addresses": int((fp_inside_s | fp_near_s).sum()),
        "without_address": int(nf - (fp_inside_s | fp_near_s).sum()),
        "points": P,
        "points_by_class": by_class,
        "points_inside_any": int(inside_any.sum()),
        "points_within_15m_any": int(near_only.sum()),
        "points_farther_any": int((~inside_any & ~near_only).sum()),
        "structure_inside": int((is_s & inside_any).sum()),
        "structure_within_15m": int((is_s & near_only & ~inside_any).sum()),
        "structure_farther": int((is_s & ~inside_any & ~near_only).sum()),
        "matched_rows": int(matched.sum()),
        "unmatched_rows": int(unmatched.sum()),
        "unmatched_by_class": unmatched_by_class,
        "non_structure_inside_any": int((~is_s & inside_any).sum()),
        "outside_grid": {"tiles": len(outside_names), "footprints": outside_fp, "rows": outside_rows,
                         "names": sorted(outside_names)},
        "outline_tiles": len(counts_tiles),
    }
    boxes_out = {}
    for label, box in boxes.items():
        if box is None:
            continue
        boxes_out[label] = _box_stats(box, geo, der, lon5, lat5, cls_codes, in_any, near_any, match, np)
    # D15: the stored dot against the stored rounded rings, exactly (integers). An exception keeps its rounded dot and is
    # counted apart, so dots_outside_outline holds the dots that are neither strictly inside nor exceptions (expect 0).
    strict = _lattice_strict(der, der.dot_lon5, der.dot_lat5, np)
    counts["dots_inside_outline"] = int(strict.sum())
    counts["dot_exceptions"] = int(der.dot_exception.sum())
    counts["dots_outside_outline"] = int((~strict & ~der.dot_exception).sum())
    counts["dots_moved"] = int(der.dots_moved)
    out = {"counts": counts, "boxes": boxes_out, "geometry": dict(geo.stats)}
    out["counties"] = _county_block(counties, der, np) if counties is not None else {
        "state": "unavailable", "reason": "the county boundary file was not given to this run"}
    return out


def _poly_meets_box(f: int, geo: Geo, der: Derived, box, np) -> bool:
    w, s, e, n = box
    minx, miny, maxx, maxy = der.bbox
    if maxx[f] < w or minx[f] > e or maxy[f] < s or miny[f] > n:
        return False
    r0, r1 = int(geo.feat_ring_start[f]), int(geo.feat_ring_start[f + 1])
    v0, v1 = int(geo.ring_start[r0]), int(geo.ring_start[r1])
    x = geo.fx[v0:v1]
    y = geo.fy[v0:v1]
    if ((x >= w) & (x <= e) & (y >= s) & (y <= n)).any():
        return True
    ring_s = geo.ring_start[r0:r1 + 1] - v0
    ex1 = x[:-1]
    ey1 = y[:-1]
    ex2 = x[1:]
    ey2 = y[1:]
    keep = np.ones(len(ex1), dtype=bool)
    keep[(ring_s[1:] - 1)[:-1]] = False            # no edge runs from one ring's last vertex to the next ring
    ex1, ey1, ex2, ey2 = ex1[keep], ey1[keep], ex2[keep], ey2[keep]
    cxm, cym = (w + e) / 2, (s + n) / 2
    cond = (ey1 > cym) != (ey2 > cym)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = ex1 + (cym - ey1) * (ex2 - ex1) / (ey2 - ey1)
    if (np.count_nonzero(cond & (cxm < xint)) % 2) == 1:
        return True
    for (ax, ay, bx, by) in ((w, s, e, s), (e, s, e, n), (e, n, w, n), (w, n, w, s)):
        d1x, d1y = bx - ax, by - ay
        o1 = d1x * (ey1 - ay) - d1y * (ex1 - ax)
        o2 = d1x * (ey2 - ay) - d1y * (ex2 - ax)
        d2x, d2y = ex2 - ex1, ey2 - ey1
        q1 = d2x * (ay - ey1) - d2y * (ax - ex1)
        q2 = d2x * (by - ey1) - d2y * (bx - ex1)
        with np.errstate(divide="ignore", invalid="ignore"):
            if ((o1 * o2 <= 0) & (q1 * q2 <= 0)).any():
                return True
    return False


def _points_in_outline(f: int, geo: Geo, xs, ys, np):
    """Which of the points lie inside outline f (even-odd over all its rings, the stored coordinates)."""
    r0, r1 = int(geo.feat_ring_start[f]), int(geo.feat_ring_start[f + 1])
    v0, v1 = int(geo.ring_start[r0]), int(geo.ring_start[r1])
    x = geo.fx[v0:v1]
    y = geo.fy[v0:v1]
    ex1, ey1, ex2, ey2 = x[:-1], y[:-1], x[1:], y[1:]
    keep = np.ones(len(ex1), dtype=bool)
    ring_end = geo.ring_start[r0 + 1:r1 + 1] - v0
    keep[(ring_end - 1)[:-1]] = False                  # no edge runs from one ring's end to the next ring
    ex1, ey1, ex2, ey2 = ex1[keep], ey1[keep], ex2[keep], ey2[keep]
    cond = (ey1[None, :] > ys[:, None]) != (ey2[None, :] > ys[:, None])
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = ex1[None, :] + (ys[:, None] - ey1[None, :]) * (ex2 - ex1)[None, :] / (ey2 - ey1)[None, :]
    hit = cond & (xs[:, None] < xint)
    return (np.count_nonzero(hit, axis=1) % 2) == 1


def _box_stats(box, geo, der, lon5, lat5, cls_codes, in_any, near_any, match, np) -> dict:
    """The check figures of a box: the outlines that meet it and the address points in it, counted for every class
    (the research's method) and for Structure points alone (the join's method). The box is closed (D46): a point on any
    of its edges is inside, and the points are the store's merged rows (D22, D39)."""
    nf = der.count
    w, s, e, n = box
    px = lon5 / SCALE
    py = lat5 / SCALE
    sel = np.nonzero((px >= w) & (px <= e) & (py >= s) & (py <= n))[0]
    minx, miny, maxx, maxy = der.bbox
    cand = np.nonzero((maxx >= w) & (minx <= e) & (maxy >= s) & (miny <= n))[0]
    inter = [int(f) for f in cand if _poly_meets_box(int(f), geo, der, box, np)]
    dot_in = int(sum(1 for f in inter if w <= der.dot_lon5[f] / SCALE <= e and s <= der.dot_lat5[f] / SCALE <= n))
    is_s = cls_codes[sel] == 0
    ia = in_any[sel]
    na = near_any[sel]
    inside_any = ia < nf
    near_sel = (na < nf) & ~inside_any
    farther_any = ~inside_any & ~near_sel
    fp_with_inside = set()                              # every outline that holds a point (not only the lowest)
    fp_with_match = set(int(v) for v in match[match >= 0].tolist())     # the join is global: any row may match
    for f in inter:                                     # every row, not only the box's: an outline may reach past it
        inb = np.nonzero((px >= minx[f]) & (px <= maxx[f]) & (py >= miny[f]) & (py <= maxy[f]))[0]
        if len(inb) and _points_in_outline(f, geo, px[inb], py[inb], np).any():
            fp_with_inside.add(f)
    return {
        "box": [w, s, e, n],
        "footprints_bbox": int(len(cand)),
        "footprints_intersecting": len(inter),
        "footprints_dot_in_box": dot_in,
        "points": int(len(sel)),
        "points_inside_any": int(inside_any.sum()),
        "points_within_15m_any": int(near_sel.sum()),
        "points_farther_any": int(farther_any.sum()),
        "footprints_no_point_inside_any": sum(1 for f in inter if f not in fp_with_inside),
        "structure_points": int(is_s.sum()),
        "structure_inside": int((is_s & inside_any).sum()),
        "structure_within_15m": int((is_s & near_sel).sum()),
        "structure_farther": int((is_s & farther_any).sum()),
        "footprints_no_structure_match": sum(1 for f in inter if f not in fp_with_match),
    }


def _county_block(counties, der, np) -> dict:
    """Outlines per county (by the county of the dot) beside the address records of the county (the addresses block's
    placement counts). counties is (names, polygons) as the reader makes it: a list of (geoid, name, rings)."""
    names = []
    counts = []
    dx = der.dot_lon5 / SCALE
    dy = der.dot_lat5 / SCALE
    assigned = np.zeros(der.count, dtype=bool)
    for geoid, name, rings in counties:
        xs = []
        ys = []
        for ring in rings:
            xs.append(ring[:, 0])
            ys.append(ring[:, 1])
        x = np.concatenate(xs)
        y = np.concatenate(ys)
        ring_lens = [len(r) for r in rings]
        x1, y1 = x[:-1].copy(), y[:-1].copy()
        x2, y2 = x[1:].copy(), y[1:].copy()
        ok = np.ones(len(x1), dtype=bool)
        ok[(np.cumsum(ring_lens) - 1)[:-1]] = False
        x1, y1, x2, y2 = x1[ok], y1[ok], x2[ok], y2[ok]
        bx0, by0, bx1, by1 = x.min(), y.min(), x.max(), y.max()
        cand = np.nonzero((~assigned) & (dx >= bx0) & (dx <= bx1) & (dy >= by0) & (dy <= by1))[0]
        inside_count = 0
        for start in range(0, len(cand), 4000):
            chunk = cand[start:start + 4000]
            px = dx[chunk][:, None]
            py = dy[chunk][:, None]
            cond = (y1[None, :] > py) != (y2[None, :] > py)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = x1[None, :] + (py - y1[None, :]) * (x2[None, :] - x1[None, :]) / (y2[None, :] - y1[None, :])
            parity = (np.count_nonzero(cond & (px < xint), axis=1) % 2) == 1
            hit = chunk[parity]
            assigned[hit] = True
            inside_count += int(parity.sum())
        names.append((geoid, name))
        counts.append(inside_count)
    return {"state": "loaded", "source": COUNTY_ACK, "file": COUNTY_NAME,
            "outlines_assigned": int(assigned.sum()), "outlines_unassigned": int(der.count - assigned.sum()),
            "by_county": [{"geoid": g, "name": n, "outlines": c} for (g, n), c in zip(names, counts)]}


def read_counties(zip_path, np) -> list:
    """(geoid, name, rings) of the Montana counties in the Census 500k file. The reader asks for the code and the
    name only, and keeps the Montana counties (the code starts with 30)."""
    pyogrio = _pyogrio()
    # The county file's only attribute reads are GEOID and NAMELSAD, for the per-county labels (D34). D14 covers the
    # footprint file only; the outline reader reads no attribute.
    try:
        info = pyogrio.read_info(str(zip_path))
        _meta, _fids, geom, fields = pyogrio.raw.read(str(zip_path), columns=["GEOID", "NAMELSAD"],
                                                      read_geometry=True)
    except Exception as exc:
        raise SourceUnavailable(f"the county file did not read ({type(exc).__name__})") from None
    if info.get("geometry_type") not in GEOMETRY_TYPES:
        raise SourceUnavailable("the county file's geometry is not a polygon")
    geoids = [str(v) for v in fields[0]]
    names_ = [str(v) for v in fields[1]]
    out = []
    for geoid, name, buf in zip(geoids, names_, geom):
        if not geoid.startswith("30"):
            continue
        rings: list = []
        wkb_polygons(bytes(buf), np, rings)
        out.append((geoid, name, [np.asarray(r, dtype=np.float64).reshape(-1, 2) for r in rings]))
    if not out:
        raise SourceUnavailable("the county file holds no Montana county")
    return out


# ---------------------------------------------------------------- the store: write, wire, restore, unavailable

def _files_on_disk(root: Path, sub: str) -> dict:
    base = root / "hail" / sub
    out = {}
    if base.is_dir():
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.name.startswith(".bld-"):
                data = path.read_bytes()
                out[path.relative_to(root).as_posix()] = {"bytes": len(data), "sha256": _sha256(data)}
    return out


def _clear_leftovers(root: Path) -> None:
    hail_dir = root / "hail"
    for folder in (hail_dir, hail_dir / "a", hail_dir / "b"):
        if folder.is_dir():
            for path in folder.glob(".bld-*"):
                if path.is_file() or path.is_symlink():
                    path.unlink()


def _refresh_address_figures(root: Path, index: dict) -> None:
    """Write the addresses block's figures of hail/a back from the files (D49). The outline step rewrites the shards
    (D28), so the figures that the address build wrote no longer describe them. A list that is not loaded has no
    figures, and a store with no hail/a folder has none to read, so the block is left as it is."""
    block = index.get(addresses.INDEX_KEY)
    if not isinstance(block, dict) or block.get("state") != "loaded" or not (root / "hail" / "a").is_dir():
        return
    try:
        index[addresses.INDEX_KEY] = addresses.refresh_figures(root, block)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BuildingsError(f"the address figures could not be read back from hail/a ({exc})") from exc


def _wire(root: Path, block: dict) -> None:
    """Write the buildings block into hail/index.json, with the addresses figures read back from hail/a (D49), and the
    manifest's entries for the index and for the a/, b/ and counts files."""
    index_path = root / "hail" / "index.json"
    manifest_path = root / "hail" / "manifest.json"
    index = _read_json(index_path)
    index[INDEX_KEY] = block
    _refresh_address_figures(root, index)
    index_bytes = _pretty(index)
    _atomic(index_path, index_bytes)
    manifest = _read_json(manifest_path)
    files = {rel: meta for rel, meta in manifest.get("files", {}).items()
             if not rel.startswith(("hail/a/", "hail/b/")) and rel not in ("hail/index.json", "hail/counts.json")}
    files.update(_files_on_disk(root, "a"))
    files.update(_files_on_disk(root, "b"))
    counts = root / "hail" / "counts.json"
    if counts.is_file():
        data = counts.read_bytes()
        files["hail/counts.json"] = {"bytes": len(data), "sha256": _sha256(data)}
    files["hail/index.json"] = {"bytes": len(index_bytes), "sha256": _sha256(index_bytes)}
    manifest["files"] = {key: files[key] for key in sorted(files)}
    _atomic(manifest_path, _pretty(manifest))


def _write_files(root: Path, files: dict) -> None:
    hail_dir = root / "hail"
    b_dir = hail_dir / "b"
    if b_dir.exists():
        shutil.rmtree(b_dir)                # the outline folder is this module's alone
    b_dir.mkdir(parents=True)
    for rel in sorted(files):
        if rel.startswith("b/"):
            _atomic(hail_dir / rel, files[rel])
    _atomic(hail_dir / "counts.json", files["counts.json"])
    for rel in sorted(files):
        if rel.startswith("a/"):
            _atomic(hail_dir / rel, files[rel])


def _load_addresses(root: Path, np, index: dict):
    """(rows, state) of the address list for the join. An unavailable list gives no rows: the outlines are built with
    no address lines, and the block says the addresses are unavailable."""
    block = index.get(addresses.INDEX_KEY)
    if not isinstance(block, dict) or block.get("state") != "loaded":
        return [], "unavailable"
    return load_rows(root, np, int(block["rows"])), "loaded"


def _restore_addresses(root: Path, np) -> None:
    """Write the full address shards back (D28): used when the outlines are unavailable after an address rewrite."""
    index = hail.load_index(root)
    block = index.get(addresses.INDEX_KEY)
    if not isinstance(block, dict) or block.get("state") != "loaded" or not (root / "hail" / "a").is_dir():
        return
    rows = load_rows(root, np, int(block["rows"]))
    files = _a_files(rows, None, True, np)
    for rel, data in files.items():
        _atomic(root / "hail" / rel, data)


def _source_block(zip_path, info: dict, facts: dict) -> dict:
    return {"name": "USA Structures (Montana file geodatabase)", "file": ZIP_NAME, "bytes": ZIP_BYTES,
            "file_date": FILE_DATE, "url": info.get("url", SOURCE_URL), "last_modified": info.get("last_modified"),
            "sha256": info.get("sha256"), "attribution": ATTRIBUTION, "licence_reading": LICENCE_READING,
            "metadata": facts, "layer": LAYER, "geometry": "MultiPolygon or Polygon", "crs": "EPSG:4326",
            "fields_read": []}


def mark_unavailable(store_dir, reason: str, *, source: bool = True) -> dict:
    """The outlines are unavailable with the plain reason (D20). The outline files are removed, the full address shards
    are written back when an address rewrite had changed them, and the store keeps every other file."""
    root = Path(store_dir)
    _check_store(root)
    text = " ".join(str(reason).split())
    if not text:
        raise BuildingsError("give the reason the outlines are unavailable (--reason TEXT)")
    if not text.startswith(UNAVAILABLE):
        text = f"{UNAVAILABLE}: {text}"
    _clear_leftovers(root)
    b_dir = root / "hail" / "b"
    if b_dir.exists():
        shutil.rmtree(b_dir)
    counts = root / "hail" / "counts.json"
    if counts.exists():
        counts.unlink()
    np = _np()
    try:
        _restore_addresses(root, np)
    except (BuildingsError, OSError, ValueError, KeyError) as exc:
        _say(f"buildings: the full address shards could not be written back ({type(exc).__name__}); see the address build")
    block = {"format": FORMAT, "state": "unavailable", "reason": text, "source_unavailable": bool(source),
             "built_at": _utc_now(), "sample": False}
    _wire(root, block)
    return {"state": "unavailable", "reason": text}


def _block(stats: dict, source: dict, addresses_state: str, built_at: str, seconds: dict,
           counties_facts: dict | None, b_files: dict) -> dict:
    counts = stats["counts"]
    return {
        "format": FORMAT,
        "state": "loaded",
        "sample": False,
        "built_at": built_at,
        "addresses": addresses_state,
        "source": source,
        "counts": counts,
        "boxes": stats["boxes"],
        "geometry": stats["geometry"],
        "counties": stats["counties"],
        "shards": stats["shards"]["count"],
        "bytes": stats["shards"]["bytes"],
        "largest_shard": stats["shards"]["largest"],
        "depths": stats["shards"]["depths"],
        "split": stats["split_names"],
        "split_boxes": stats["split_boxes"],
        "tiles": stats["tiles"],
        "outside_grid": counts["outside_grid"],
        "a": stats["a"],
        "counts_file": {"file": "hail/counts.json", "tiles": len(stats.get("tile_counts", {})) or None,
                        "total": counts["footprints"]},
        "overhang_deg": stats["overhang_deg"],
        "limits": {"shard_bytes": SHARD_BYTES, "match_m": MATCH_M, "precision_decimals": 5,
                   "depth_cap": DEPTH_CAP, "rows_per_address_shard": addresses.ROWS_LIMIT},
        "rule": ("dot: the centroid when inside the outline, else the midpoint of the longest interior chord through "
                 "the centroid (four directions); a Structure point joins an outline when inside or within 15 m of "
                 "its edge (nearest, ties to the lower outline); other classes keep their own dots (D32)"),
        "seconds": seconds,
    }


def build(gdb_zip, store_dir, *, cache=None, url: str = SOURCE_URL, ledger=None, counties_zip=None,
          counties_cache=None, session=None) -> dict:
    """Build the outline shards, the counts file and the a/ rewrite into store_dir, then check the store. Returns the
    block written to hail/index.json. A source failure marks the outlines unavailable and raises SourceUnavailable; any
    other failure marks them unavailable and raises BuildingsError. The check runs on the written store and removes
    the outlines again if it fails (the rollback restores the full address shards first)."""
    root = Path(store_dir)
    _check_store(root)
    started = time.time()
    try:
        np = _np()
        if gdb_zip is None:
            zip_path, info = download(cache or Path("structures-fema"), url, session=session, ledger=ledger)
        else:
            zip_path, info = check_zip(gdb_zip), {"url": url, "last_modified": None}
        info["sha256"] = info.get("sha256") or _sha256_file(Path(zip_path))
        facts = metadata_facts(zip_path)
        gdb = extract_gdb(zip_path, Path(zip_path).parent)
        geo = read_outlines(gdb, np)
        t_read = round(time.time() - started, 1)
        index = hail.load_index(root)
        rows, addresses_state = _load_addresses(root, np, index)
        b1_tiles = set(index["tiles"])
        counties = None
        counties_block = {"state": "unavailable", "reason": "the county boundary file was not given to this run"}
        if counties_zip is not None or counties_cache is not None:
            try:
                cz = Path(counties_zip) if counties_zip else fetch_cached(
                    counties_cache, COUNTY_NAME, COUNTY_URL, session=session, ledger=ledger, what="the county file")[0]
                counties = read_counties(cz, np)
            except (SourceUnavailable, BuildingsError) as exc:
                counties_block = {"state": "unavailable", "reason": str(exc)}
                _say(f"buildings: the counts by county are unavailable ({exc}); the outlines are kept")
        der = derive(geo, np)
        t_derive = round(time.time() - started, 1)
        boxes = {"billings": BOXES["billings"], "sanders": SANDERS_BOX}
        files, stats = plan(geo, der, rows, b1_tiles, np, counties=counties, addresses_ok=addresses_state == "loaded",
                            address_block=index.get(addresses.INDEX_KEY), boxes=boxes)
        if counties is None:
            stats["counties"] = counties_block
        else:
            # D34: each county's outline count beside its address records (the addresses block's placement counts,
            # which count every record before the merge)
            placement = (index.get(addresses.INDEX_KEY) or {}).get("placement", {}).get("by_county", {})
            for row in stats["counties"].get("by_county", []):
                row["address_records"] = (sum(placement[row["name"]].values()) if row["name"] in placement else None)
            stats["counties"]["address_counties_unmatched"] = sorted(
                set(placement) - {row["name"] for row in stats["counties"].get("by_county", [])})
        stats["seconds"].update({"read": t_read, "derive": t_derive})
        if addresses_state == "loaded":
            _say(f"buildings: {stats['counts']['footprints']:,d} outlines, {stats['counts']['matched_rows']:,d} rows "
                 f"matched in {stats['seconds']['total']}s")
        source = _source_block(zip_path, info, facts)
        source["fields_read"] = []
        block = _block(stats, source, addresses_state, _utc_now(), stats["seconds"], None, files)
        block["counts_file"]["tiles"] = len(json.loads(files["counts.json"].decode("utf-8"))["tiles"])
        _clear_leftovers(root)
        _write_files(root, files)
        _wire(root, block)
        checked = verify(root)
        if not checked["ok"]:
            failed = [c["name"] for c in checked["checks"] if not c["ok"]]
            raise BuildingsError("the outline check did not pass after the write: " + "; ".join(failed[:3]))
        return block
    except SourceUnavailable as exc:
        mark_unavailable(root, str(exc), source=True)
        raise
    except BuildingsError as exc:
        mark_unavailable(root, f"{UNAVAILABLE}: {exc}", source=False)
        raise


# ---------------------------------------------------------------- verify

def verify(store_dir, gdb_zip=None, counties_zip=None) -> dict:
    """Check the outlines in a store: the manifest hashes; every outline shard's format, name, bounds, entries, rings
    (at least four points, closed), size limit (except at the depth cap) and split map; the counts file against the
    shards; every address row once (the a/ shards and the matched lines); and, with gdb_zip, the whole part recomputed
    from the file: the same bytes, the same measures and the Billings and Sanders figures. Returns {"ok","checks","counts"};
    a failed check names what failed."""
    root = Path(store_dir)
    checks: list = []
    counts: dict = {}

    def check(name: str, ok: bool, detail: str = "") -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def result() -> dict:
        return {"ok": all(c["ok"] for c in checks), "checks": checks, "counts": counts}

    try:
        hail.check_manifest(root)
        check("manifest hashes and counts", True)
    except hail.HailStoreError as exc:
        check("manifest hashes and counts", False, str(exc))
        return result()
    index = hail.load_index(root)
    block = index.get(INDEX_KEY)
    if not isinstance(block, dict):
        check("buildings block in the index", False, "hail/index.json has no buildings block")
        return result()
    if block.get("state") == "unavailable" and block.get("source_unavailable"):
        check("the outlines are unavailable from their source; the sheet says so", True, str(block.get("reason", "")))
        return result()
    if not check("buildings state", block.get("state") == "loaded", f"state {block.get('state')}"):
        return result()
    np = _np()
    b_dir = root / "hail" / "b"
    total = 0
    tile_totals: Counter = Counter()
    line_pairs = set()
    bad: list = []
    depth_hist: Counter = Counter()
    shard_names: list = []
    b_rows_matched = 0
    tile_names = set(index["tiles"])
    split = block.get("split", {})
    for path in sorted(b_dir.glob("*.json")):
        shard_names.append(path.stem)
        try:
            doc = _read_json(path)
        except (OSError, ValueError):
            bad.append(f"{path.name} is not JSON")
            continue
        name = path.stem
        tile = name[:len(hail.tile_name(0, 0))]
        if doc.get("f") != FORMAT or not re.fullmatch(r"r\d{4}_c\d{4}\d*", name):
            bad.append(f"{path.name} has the wrong format or name")
            continue
        depth = len(name) - len(tile)
        depth_hist[depth] += 1
        west, south, east, north = doc["b"]
        if doc["n"] != len(doc["a"]) or not isinstance(doc.get("m"), int):
            bad.append(f"{path.name} has a count that is not its entries")
        if path.stat().st_size > SHARD_BYTES and depth < DEPTH_CAP:
            bad.append(f"{path.name} is {path.stat().st_size} bytes (the limit is {SHARD_BYTES})")
        for entry in doc["a"]:
            lon, lat = entry["p"]
            if not (west <= lon <= east and south <= lat <= north):
                bad.append(f"{path.name} has a dot outside its bounds")
                break
            for ring in entry["g"]:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    bad.append(f"{path.name} has a ring that is not closed or has fewer than four points")
                    break
            lines = entry["l"]
            zs = entry.get("z")
            if zs is not None and len(zs) != len(lines):
                bad.append(f"{path.name} has z that does not match l")
            for i, line in enumerate(lines):
                cz = zs[i] if zs is not None and zs[i] is not None else doc["c"]
                if cz is None:
                    bad.append(f"{path.name} has a line with no city and zip")
                    break
                line_pairs.add((line, cz[0], cz[1]))
        total += len(doc["a"])
        tile_totals[tile] += len(doc["a"])
        b_rows_matched += int(doc.get("m", 0))
    counts["shards"] = len(shard_names)
    counts["footprints"] = total
    counts["matched_rows"] = b_rows_matched
    check("every outline shard parses, has its name, bounds, rings and count, and stays within the limit",
          not bad, "; ".join(bad[:4]) or f"{len(shard_names)} shards")
    check("the outline total equals the index", total == block["counts"]["footprints"],
          f"{total} in the shards, {block['counts']['footprints']} in the index")
    check("the depths match the index", {str(k): v for k, v in sorted(depth_hist.items())} == block["depths"],
          str(dict(sorted(depth_hist.items()))))
    split_ok = all(sorted(leaves) == sorted(x for x in shard_names if x.startswith(tile) and len(x) > len(tile))
                   for tile, leaves in split.items())
    check("the split map names the outline shards of each split tile", split_ok)
    counts_doc = _read_json(root / "hail" / "counts.json")
    check("counts.json sums to the footprint total and matches each tile",
          counts_doc.get("total") == total and sum(counts_doc["tiles"].values()) == total and
          all(tile_totals[t] == n for t, n in counts_doc["tiles"].items()) and sum(tile_totals.values()) == total,
          f"{sum(counts_doc['tiles'].values())} in counts.json")
    a_dir = root / "hail" / "a"
    a_total = 0
    a_seen: Counter = Counter()
    a_bad: list = []
    a_idents = set()
    for path in sorted(a_dir.glob("*.json")):
        doc = _read_json(path)
        if doc.get("f") != addresses.FORMAT or doc["n"] != len(doc["a"]):
            a_bad.append(f"{path.name} has the wrong format or count")
            continue
        for row in doc["a"]:
            if not (isinstance(row, list) and len(row) == 6 and row[5] in CLASS_LETTERS):
                a_bad.append(f"{path.name} has a row that is not six values")
                break
            ident = (round(row[0] * SCALE), round(row[1] * SCALE), row[2], row[3], row[4])
            if ident in a_idents:
                a_bad.append(f"{path.name} repeats a row")
            a_idents.add(ident)
        a_total += len(doc["a"])
    counts["unmatched_rows"] = a_total
    check("the address shards hold the unmatched rows only, each once", not a_bad,
          "; ".join(a_bad[:3]) or f"{a_total} rows in a/")
    addr_rows = int(index[addresses.INDEX_KEY]["rows"]) if isinstance(index.get(addresses.INDEX_KEY), dict) else None
    if block.get("addresses") == "loaded" and addr_rows is not None:
        check("matched rows plus unmatched rows equal the address rows once each",
              b_rows_matched + a_total == addr_rows,
              f"{b_rows_matched} matched + {a_total} unmatched, {addr_rows} rows")
        rows_now = load_rows(root, np, addr_rows)
        letter_ids = set((r[2], r[3], r[4]) for r in rows_now)
        strays = [p for p in line_pairs if p not in letter_ids]
        check("every matched line is an address row of the list", not strays,
              f"{len(strays)} lines not in the list")
        check("every unmatched row is an address row of the list",
              a_idents <= {(r[0], r[1], r[2], r[3], r[4]) for r in rows_now}, f"{len(a_idents)} unmatched rows")
    if gdb_zip is not None:
        try:
            zip_path = check_zip(gdb_zip)
            facts = metadata_facts(zip_path)
            gdb = extract_gdb(zip_path, Path(zip_path).parent)
            geo = read_outlines(gdb, np)
            der = derive(geo, np)
            rows, addresses_state = _load_addresses(root, np, index)
            counties = None
            if counties_zip is not None:
                counties = read_counties(counties_zip, np)
            boxes = {"billings": BOXES["billings"], "sanders": SANDERS_BOX}
            files, stats = plan(geo, der, rows, tile_names, np, counties=counties,
                                addresses_ok=addresses_state == "loaded", boxes=boxes)
            mismatched = []
            for rel, data in files.items():
                path = root / "hail" / rel
                if not path.is_file() or path.read_bytes() != data:
                    mismatched.append(rel)
            check("recomputed from the file: every outline and address shard and the counts file are the same bytes",
                  not mismatched, "; ".join(mismatched[:4]) or f"{len(files)} files")
            present = set(f"b/{p.name}" for p in b_dir.glob("*.json"))
            check("no outline shard is in the store that the file does not give",
                  present == {k for k in files if k.startswith("b/")})
            measured = stats["counts"]
            indexed_counts = block["counts"] if isinstance(block.get("counts"), dict) else {}
            for key in ("footprints", "multipart", "points", "matched_rows", "unmatched_rows",
                        "with_address_inside", "with_address_within_15m_only", "without_address",
                        "structure_inside", "structure_within_15m", "structure_farther",
                        "dots_outside_outline", "dot_exceptions"):
                # R-08 (D48): an index written before a count existed has no such key; that is a failed check that says
                # what to do, never a KeyError
                indexed = indexed_counts.get(key)
                if indexed is None:
                    check(f"recomputed {key} equals the index", False,
                          f"{measured.get(key)} recomputed; the index has no count of that name, so rebuild the store")
                else:
                    check(f"recomputed {key} equals the index", measured.get(key) == indexed,
                          f"{measured.get(key)} recomputed, {indexed} in the index")
            for label in ("billings", "sanders"):
                counts[label] = stats["boxes"][label]
            # D46 and B3-10: the Billings figures are checked against the stated gate for the address list they were
            # measured on; another address list date is recorded as not made (the monthly list must not fail the store)
            addr_block = index.get(addresses.INDEX_KEY)
            address_date = (addr_block.get("source") or {}).get("pubdate") if isinstance(addr_block, dict) else None
            gate = billings_gate(stats["boxes"]["billings"], address_date)
            if gate["made"]:
                check(gate["name"], gate["ok"], gate["detail"])
            else:
                counts["billings_gate"] = gate["note"]
            counts["recomputed"] = measured
            counts["metadata"] = facts
        except (SourceUnavailable, BuildingsError) as exc:
            check("the outline file recomputes", False, str(exc))
    return result()


# ---------------------------------------------------------------- the words of the site: the About text and the map data

def describe_buildings(index: dict | None = None) -> dict:
    """The About text of the outlines (D17, D29, D34): the source line, the caveat and the one-dot rule. The source line
    carries the file date only when the index read one (D24); otherwise it says the date is not available."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    dated = isinstance(block, dict) and block.get("state") == "loaded" and block.get("source", {}).get("file_date")
    source = (WORDS_BUILDINGS["about_source"].format(file_date=block["source"]["file_date"]) if dated
              else WORDS_BUILDINGS["about_source_undated"])
    return {
        "title": WORDS_BUILDINGS["about_title"],
        "source": source,
        "caveat": WORDS_BUILDINGS["about_caveat"],
        "dot": WORDS_BUILDINGS["about_dot"],
    }


def map_data_buildings(index: dict) -> dict:
    """The map.json["hail"]["buildings"] block (D7, D27): the state, the counts the words need, the tile names (build.b3_map_blocks
    turns the list into the compact tile_split, D40), the split map (each tile's leaf names; the browser derives each leaf's bounds from its quadtree digits, as it does for
    the roads and the addresses: map.js b3NameBox), the count file, the zoom thresholds, the dot and tap radii and every
    template. Positions, text and the search never leave the browser; a request names a shard and nothing else."""
    block = index.get(INDEX_KEY) if isinstance(index, dict) else None
    templates = {**WORDS_BUILDINGS, "placed_how": dict(addresses.PLACEMENT_HOW)}
    if not isinstance(block, dict) or block.get("state") != "loaded":
        problem = block.get("reason") if isinstance(block, dict) else "the outlines are not in the store"
        return {"state": "unavailable", "problem": problem or "the outlines are not in the store",
                "templates": templates}
    return {
        "state": "loaded",
        "problem": None,
        "footprints": block["counts"]["footprints"],
        "counts": {k: block["counts"][k] for k in ("multipart", "with_addresses", "without_address",
                                                    "matched_rows", "unmatched_rows", "unmatched_by_class")},
        "addresses": block.get("addresses", "loaded"),
        "shard": "hail/b/{name}.json",
        "tiles": list(block.get("tiles", [])),
        "split": {tile: [name for name, box in leaves] for tile, leaves in block.get("split_boxes", {}).items()},
        "unmatched": "hail/a/{name}.json",
        "counts_file": "hail/counts.json",
        "zoom": {"counts": list(ZOOM["counts"]), "dots": ZOOM["dots"], "fills": ZOOM["fills"],
                 "emphasis": ZOOM["emphasis"]},
        "dot_radius_px": dict(DOT_RADIUS_PX),
        "tap_radius_px": TAP_RADIUS_PX,
        "overhang_deg": block.get("overhang_deg", 0.0),
        "classes": CLASS_LETTERS,
        "templates": templates,
        "source": {"file_date": block["source"]["file_date"], "attribution": ATTRIBUTION,
                   "licence_reading": LICENCE_READING},
        "counties": block.get("counties", {}),
    }


# ---------------------------------------------------------------- command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.buildings",
                                     description="Building outlines, one dot per building, and the address join (B3).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="read the outline file, write hail/b/, the counts and the a/ rewrite, then check")
    b.add_argument("--store", required=True, help="the store directory that holds hail/ (B1, the addresses built)")
    b.add_argument("--gdb-zip", default=None, help="the outline zip (skips the download)")
    b.add_argument("--cache", default="structures-fema", help="the download cache for the outline zip")
    b.add_argument("--url", default=SOURCE_URL, help="the download address (default: the FEMA file)")
    b.add_argument("--ledger", default=None, help="a JSON-lines ledger of the requests (default: the cache's)")
    b.add_argument("--counties-zip", default=None, help="the Census county file (optional; skips its download)")
    b.add_argument("--counties-cache", default=None, help="the cache for the county file (download when missing)")
    v = sub.add_parser("verify", help="check the outlines in a store (exit 1 on a failure)")
    v.add_argument("store_dir", nargs="?", metavar="STORE", help="the store directory (the same as --store)")
    v.add_argument("--store", dest="store_opt", default=None)
    v.add_argument("--gdb-zip", default=None, help="also recompute the whole part from this outline zip")
    v.add_argument("--counties-zip", default=None, help="the county file for the per-county counts")
    u = sub.add_parser("unavailable", help="mark the outlines unavailable with a reason and remove their files")
    u.add_argument("--store", required=True, help="the store directory that holds hail/ (the job's failure branch)")
    u.add_argument("--reason", required=True, help="the plain reason the outlines are unavailable")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            started = time.time()
            ledger = args.ledger
            if ledger is None and args.gdb_zip is None:
                ledger = str(Path(args.cache) / "ledger.jsonl")
            block = build(args.gdb_zip, args.store, cache=args.cache, url=args.url, ledger=ledger,
                          counties_zip=args.counties_zip, counties_cache=args.counties_cache)
            summary = {"state": block["state"], "footprints": block["counts"]["footprints"],
                       "matched_rows": block["counts"]["matched_rows"],
                       "unmatched_rows": block["counts"]["unmatched_rows"],
                       "shards": block["shards"], "bytes": block["bytes"], "largest_shard": block["largest_shard"],
                       "a": block["a"], "depths": block["depths"], "wall_seconds": round(time.time() - started, 1)}
            print(json.dumps(summary, indent=1, ensure_ascii=False))
            return 0
        if args.command == "verify":
            store = args.store_opt or args.store_dir
            if not store:
                print("error: give the store directory (verify STORE or --store STORE)", file=sys.stderr)
                return 2
            result = verify(store, args.gdb_zip, args.counties_zip)
            print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
            return 0 if result["ok"] else 1
        if args.command == "unavailable":
            if not args.reason.strip():
                print("error: give the reason the outlines are unavailable (--reason TEXT)", file=sys.stderr)
                return 2
            print(json.dumps(mark_unavailable(args.store, args.reason), indent=1, ensure_ascii=False))
            return 0
    except SourceUnavailable as exc:
        if args.command != "build":
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"warning: {exc}; the outlines are marked unavailable and the rest of the store is kept", file=sys.stderr)
        return 0
    except BuildingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except hail.HailStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
