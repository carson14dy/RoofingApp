# H1 prototype: a daily radar hail-estimate store for Montana

This folder holds a prototype that turns the 12:00 UTC `MESH_Max_1440min_00.50` files
from the NOAA MRMS archive into a per-day, per-cell store for the Montana grid cells,
with the tables and tiles a lookup needs. The measurements are in
`../validation-evidence/h1-mesh-store.json`.

It is a prototype for measurement. It is not a product, not a damage record, not an
inspection, and not a finding about any roof or address. A radar estimate for a cell is
not a measurement at a house. No report and no estimate do not mean no hail.

## Files

| File | What it is |
| --- | --- |
| `mesh_history.py` | The tool: `fetch`, `decode`, `build`, `lookup`, `verify`, `fixture`. |
| `tests/test_mesh_history.py` | 30 offline tests (no network, no pygrib). The 3 store tests need pyarrow and are skipped without it. |
| `tests/fixtures/mesh1440_20250616_benchland_8x10.json` | 8 rows by 10 columns of raw values cut from the real 2025-06-16 12:00 UTC file (80 cells, 964 bytes), made by `fixture`. It holds the 35.7 mm Benchland peak and 5 cells coded -1. |
| `README.md` | This file. |

## Environment

- System Python 3.13.16 with numpy 2.5.3, pygrib 2.1.8, eccodes 2.50.0 and requests 2.34.2.
- pyarrow 26.0.0 is not in the system Python. It was installed into a virtual environment
  kept outside the repository, with system packages visible:
  `python3 -m venv --system-site-packages <scratch>/hail-venv` then
  `<scratch>/hail-venv/bin/pip install pyarrow`. Nothing else was installed.
- Python 3.12 is also on the machine, but it has no numpy or pygrib, so the tests were run
  on 3.13 only. The code was not run on 3.12.
- Downloads, the store and all verification output were written under the session scratchpad,
  not in the repository.

## How to run

Use the virtual environment interpreter for `build`, `lookup`, `verify` and the tests (they
need pyarrow). `fetch`, `decode` and `fixture` run with the system `python3`. Always run with `-I`,
because the downloaded GRIB files are untrusted data.

```bash
P=research/hail-history/prototype
S=<scratchpad>
PY=$S/hail-venv/bin/python
$PY -I $P/mesh_history.py fetch --start 2020-10-14 --end 2026-10-16 --cache $S/hail-dl/mesh-backfill --workers 4
$PY -I $P/mesh_history.py build --start 2020-10-14 --end 2026-10-16 --cache $S/hail-dl/mesh-backfill --store $S/hail-store/h1-mesh --procs 4
$PY -I $P/mesh_history.py lookup --store $S/hail-store/h1-mesh --lat 47.085 --lon -110.045 --all-days
$PY -I $P/mesh_history.py verify --store $S/hail-store/h1-mesh --cache $S/hail-dl/mesh-backfill --out $S/hail-store/verify.json
$PY -I $P/mesh_history.py decode --file <one .grib2.gz> --npz <out.npz>
cd $P && $PY -I -m unittest discover -s tests -v
```

`fetch` reads the bucket first. Only when the bucket answers 404 does it try the IEM copy.
It is resumable: a ledger (`ledger.jsonl`) records each stamp, and a manifest (`manifest.json`)
is written at the end with the URL status, bytes, sha256 and Last-Modified of every file.
At most four requests run at once. `--recheck-missing` fetches again the stamps recorded as missing.
`build` refuses to run when a requested day was never fetched or errored, unless `--allow-gaps` is
given. A day that both sources answer with 404 is recorded as missing and built without.

## Dates and keys

- A file stamped 12:00 UTC on day D covers 12:00 UTC on D-1 to 12:00 UTC on D.
- The store is keyed by the SPC report day D-1, which follows AGENTS.md (SPC reporting days run
  12:00 to 11:59 UTC). A report dated 2025-06-15 is the file stamped 2025-06-16.
- The five-year window is SPC report days 2021-10-16 to 2026-10-15 (files stamped 2021-10-17 to
  2026-10-16). The store also holds the earlier files stamped 2020-10-15 to 2021-10-16, which the
  lookup leaves out unless asked.

## Grid, mask and units

- Grid: 7000 by 3500 points at 0.01 degree (from the GRIB2 header). Row 0 is the northern edge.
- Decode crop: the frame box 43.0 to 50.5 N, 118.5 to 101.0 W (750 rows by 1,750 columns).
- State mask: a cell is in the store when its centre lies inside the Montana land polygon in
  `website/static/map/basemap.json` (one ring, 212 vertices). Points exactly on an edge are out.
  That gives 450,765 cells. The 216 cells on the east edge at lon -104.045 are the difference
  from the inclusive count of 450,981.
- Units: the GRIB unit key reads "unknown". The values are read as millimetres because of their
  size (up to 457.4 in one file) and their 0.1 step. This is not checked against a NOAA code table,
  which could not be read here. Inch equivalents assume millimetres.
- Codes: -1 and -3 are no data. Their meaning is not verified, so the daily statistics keep a count
  of each. Other negative values and NaN are no data too, and are counted.
- Stored value: uint16 tenths of a millimetre, with 0 for no data. An exact 0.0 is also stored as 0
  and counted separately (`n_zero`). No value is clamped: a value above 6553.5 mm raises an error.
- Inch cut-offs: 0.25 in is 6.35 mm, so the first stored tenth at or above it is 6.4 mm; 0.75 in is
  19.05 mm (stored from 19.1 mm); 1.00 in is 25.4 mm; 1.50 in is 38.1 mm; 2.00 in is 50.8 mm.

## What each output is

Everything is under the store folder (`<scratch>/hail-store/h1-mesh`).

- `grid.json`: the crop, cell order, thresholds, the list of stored days, the missing days, the
  encodings, the build time and the sha256 of the basemap used.
- `mask.bin`: the crop mask, packed bits, row-major (750 by 1,750).
- `days/YYYY.bin` and `days/index.json`: one blob per stored day, in one file per year. Each blob
  is a format byte, then zlib data: format 0 is the dense uint16 array, format 1 is the sparse list
  (gaps as uint32, then values as uint16). The build writes whichever is smaller for each day.
- `events.parquet`: rows of `(cell_index, day, mm)` for every cell at or above 0.25 in (6.4 mm stored),
  sorted by day then cell.
- `cell_counts.parquet`: per cell, over the five-year window: days with any positive value
  (`n_pos_days`) and days at or above 0.25, 0.75, 1.00, 1.50 and 2.00 in.
- `shards/rRRRR_cCCCC.json.gz`: the events of one 0.1 degree tile (10 by 10 cells, aligned to the
  MRMS grid). Tile row is the global row divided by 10, and tile column is the global column divided
  by 10, both rounded down. Contents: `{"format": "mesh-events-v1", "unit": "mm", "events": [[cell_index, day_index, mm], ...]}`,
  where `day_index` is the position in `days` in `grid.json`. Tiles with no events have no file.
- `daily_stats.json`: one row for every requested SPC day: file stamp, source (`bucket`, `iem` or
  `missing`), bytes, sha256, Last-Modified, the counts above, the code counts, the maximum, the
  quantisation error, the encoding and the blob size.

## Lookup wording

`lookup` returns the nearest of the four surrounding cell centres inside the mask, its five-year
events at 0.25 in or more, the counts per class, and a short text that calls the value a radar
estimate for one cell. It says that no stored value is not the same as no hail.

## What it is not

- Not a damage record and not an inspection. Not a finding about any roof, address or insurance.
- Not a measurement at a house. One cell is about 0.8 km by 1.1 km.
- Not a report, and not validated against reports. Validation is W10's job (`docs/ROADMAP.md`).
- Not proof that the 12:00 UTC file is the 24-hour maximum everywhere. `verify` compares the file with
  the 2-minute frames of three days, and the results are in the evidence JSON.
- No stored value is not "no hail". Cells with no data, values under 0.25 in and days that are
  not stored are all missing from the events table.

## Tests

`tests/test_mesh_history.py` covers the units and inch cut-offs, the no-data rule, the encodings,
the Montana mask (the full count, the east-edge tie block and the fixture block), the shard
addressing, the date mapping, the file checks, and an end-to-end path from the saved fixture through
build and lookup (including a no-data cell and a point outside the grid). The mask tests read the
website's `basemap.json` from this repository.
