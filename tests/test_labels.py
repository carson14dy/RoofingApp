"""Bubble anchors for the value bubbles (B6 product P4, website/labels.py).

Offline, on a small fixture store (tests/fixtures/labels: 60 outlines of one Missoula building shard in eight 1 km cells, with
the radar values of six of those cells; two cells have no stored value and read "Data unavailable"). A build runs in a
temporary copy. The label widths need Pillow with raqm and the site font: without them the width tests are skipped, and the
build test shows the block unavailable. Checked here: the label widths (0.38 in is 55.75 px in the measured font); the
box and the 2 px skip rule; the clusters (a dot joins the nearest leader within the cluster radius; the anchor is the member
nearest the middle); the greedy placement (value descending, a dash last, the skip rule); the flags and the kv of the fixture
shard; an outline outside its shard's tile gets no flag; a shard with no change renders to its own bytes; the build (manifest,
determinism, the unavailable path, the missing radar tile, a font that is absent) and verify (a changed shard is named).
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from website import hail
from website import history_layers as H
from website import labels as L

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "labels"
TILE = "r0081_c0160"
SHARD = "r0081_c016000.json"

import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
import words_rules as W  # noqa: E402

try:
    import numpy  # noqa: F401
    from PIL import ImageFont, features
    HAVE_FONT = features.check("raqm") and L.FONT_FILE.is_file()
except ImportError:                       # pragma: no cover
    HAVE_FONT = False

needs_font = unittest.skipUnless(HAVE_FONT, "Pillow with raqm (and numpy) is not installed")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_store(tmp: Path) -> Path:
    store = tmp / "store"
    shutil.copytree(FIXTURE, store)
    files = {}
    for path in sorted((store / "hail").rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            data = path.read_bytes()
            files[path.relative_to(store).as_posix()] = {"bytes": len(data), "sha256": _sha(data)}
    (store / "hail" / "manifest.json").write_text(json.dumps({"format": "hail-manifest-v1", "counts": {}, "files": files}),
                                                  encoding="utf-8")
    return store


def load_shard(store: Path) -> dict:
    return json.loads((store / "hail" / "b" / SHARD).read_text(encoding="utf-8"))


class Words(unittest.TestCase):
    def test_the_label_words_pass_the_forbidden_list(self):
        for key, text in H.WORDS.items():
            if isinstance(text, str) and key.startswith("label"):
                W.assert_clean(self, text, key)
        W.assert_clean(self, L.DASH, "dash")
        W.assert_clean(self, L.UNAVAILABLE_TEXT, "unavailable")

    def test_the_module_text_has_no_dash_characters(self):
        text = Path(L.__file__).read_text(encoding="utf-8")
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)


class TextAndKv(unittest.TestCase):
    def test_a_missing_value_is_a_dash_on_the_bubble_and_data_unavailable_in_the_header(self):
        self.assertEqual(L.label_text(None), "--")
        self.assertEqual(L.label_text(0), "--")
        self.assertEqual(L.kv_text(None), "Data unavailable")
        self.assertEqual(L.kv_text(0), "Data unavailable")

    def test_a_value_is_rounded_down_to_the_hundredth(self):
        self.assertEqual(L.label_text(100), "0.39 in")     # 100 tenths: 10.0 mm, 0.3937 in, shown 0.39
        self.assertEqual(L.kv_text(100), "0.39 in")
        self.assertEqual(L.label_text(99), "0.38 in")      # 9.9 mm: 0.3897 in, rounded down to 0.38


class Geometry(unittest.TestCase):
    @needs_font
    def test_the_reference_label_is_55_75_px(self):
        self.assertEqual(L.label_width("0.38 in"), 55.75)
        self.assertEqual(L.cluster_px(), 55.75)

    @needs_font
    def test_the_dash_is_the_minimum_width(self):
        self.assertEqual(L.label_width("--"), 30.0)

    @needs_font
    def test_a_box_sits_above_its_dot_with_its_pointer(self):
        box = L.box_for(100.0, 200.0, "0.38 in")
        self.assertEqual(box[3], 200.0 - 4.0 - 1.0)          # the tip: one px above the dot's top edge (dot radius 4)
        self.assertEqual(box[3] - box[1], 22.0 + 5.0)         # the body and the pointer
        self.assertAlmostEqual((box[0] + box[2]) / 2, 100.0)

    @needs_font
    def test_two_px_overlap_does_not_clash_but_more_does(self):
        a = (0.0, 0.0, 50.0, 20.0)
        self.assertFalse(L.clash(a, (48.0, 10.0, 90.0, 30.0)))     # 2 px in x: not more than 2
        self.assertTrue(L.clash(a, (47.5, 10.0, 90.0, 30.0)))      # 2.5 px in x and 10 px in y
        self.assertFalse(L.clash(a, (47.5, 19.0, 90.0, 30.0)))     # only 1 px in y: no clash


class Clusters(unittest.TestCase):
    @needs_font
    def test_a_dot_joins_the_leader_within_the_radius_only(self):
        items = [{"i": 0, "x": 0.0, "y": 0.0, "cell": (1, 1), "tenths": 100, "text": "0.39 in"},
                 {"i": 1, "x": 40.0, "y": 0.0, "cell": (1, 1), "tenths": 100, "text": "0.39 in"},
                 {"i": 2, "x": 100.0, "y": 0.0, "cell": (1, 1), "tenths": 100, "text": "0.39 in"}]
        clusters = L.clusters_for(items)
        self.assertEqual([c["members"] for c in clusters], [[0, 1], [2]])

    @needs_font
    def test_the_anchor_is_the_member_nearest_the_middle_and_ties_go_to_the_earlier(self):
        items = [{"i": 0, "x": 0.0, "y": 0.0, "cell": (1, 1), "tenths": 100, "text": "0.39 in"},
                 {"i": 1, "x": 40.0, "y": 0.0, "cell": (1, 1), "tenths": 100, "text": "0.39 in"}]
        clusters = L.clusters_for(items)
        self.assertEqual(clusters[0]["anchor"], 0)           # both are 20 px from the middle: the earlier one
        items[1]["x"] = 36.0
        items.append({"i": 2, "x": 18.0, "y": 0.0, "cell": (1, 1), "tenths": 100, "text": "0.39 in"})
        clusters = L.clusters_for(items)
        self.assertEqual(clusters[0]["anchor"], 2)           # the middle of the three is 18 px: the middle dot

    @needs_font
    def test_cells_never_share_a_cluster(self):
        items = [{"i": 0, "x": 0.0, "y": 0.0, "cell": (1, 1), "tenths": 100, "text": "0.39 in"},
                 {"i": 1, "x": 5.0, "y": 0.0, "cell": (1, 2), "tenths": 100, "text": "0.39 in"}]
        self.assertEqual(len(L.clusters_for(items)), 2)

    @needs_font
    def test_the_order_is_by_cell_and_then_by_position(self):
        items = [{"i": 3, "x": 5.0, "y": 9.0, "cell": (2, 2), "tenths": 1, "text": "x"},
                 {"i": 1, "x": 1.0, "y": 2.0, "cell": (1, 1), "tenths": 1, "text": "x"}]
        self.assertEqual([c["anchor"] for c in L.clusters_for(items)], [1, 3])


class Placement(unittest.TestCase):
    @needs_font
    def test_the_higher_value_is_placed_and_the_overlapping_one_is_skipped(self):
        clusters = [{"anchor": 0, "members": [0], "tenths": 100, "x": 50.0, "y": 50.0, "text": "0.39 in", "cell": (1, 1)},
                    {"anchor": 1, "members": [1], "tenths": 254, "x": 55.0, "y": 50.0, "text": "1.00 in", "cell": (1, 2)}]
        placed = [c["anchor"] for c in L.place(clusters)]
        self.assertEqual(placed, [1])

    @needs_font
    def test_a_dash_is_placed_last_and_only_when_nothing_clashes(self):
        clusters = [{"anchor": 0, "members": [0], "tenths": None, "x": 50.0, "y": 50.0, "text": "--", "cell": (1, 1)},
                    {"anchor": 1, "members": [1], "tenths": 100, "x": 300.0, "y": 50.0, "text": "0.39 in", "cell": (1, 2)}]
        self.assertEqual([c["anchor"] for c in L.place(clusters)], [1, 0])

    @needs_font
    def test_bubbles_far_apart_are_both_placed(self):
        clusters = [{"anchor": 0, "members": [0], "tenths": 100, "x": 50.0, "y": 50.0, "text": "0.39 in", "cell": (1, 1)},
                    {"anchor": 1, "members": [1], "tenths": 100, "x": 200.0, "y": 50.0, "text": "0.39 in", "cell": (1, 2)}]
        self.assertEqual(len(L.place(clusters)), 2)


@needs_font
class Shard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp)
        self.index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.doc = load_shard(self.store)
        self.values = L.TileValues(self.store, self.index)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def label(self, doc=None):
        doc = doc or self.doc
        tops = self.values.for_cells(L._shard_cells(doc))
        return L.label_shard(doc, tops, (81, 160)), tops

    def test_flags_mark_anchors_only_and_every_cell_has_its_text(self):
        result, tops = self.label()
        flagged = [i for i, f in enumerate(result["flags"]) if f != [0, 0]]
        self.assertGreater(len(flagged), 0)
        self.assertLess(len(flagged), len(self.doc["a"]))
        for z_index in range(2):
            for i, f in enumerate(result["flags"]):
                if f[z_index]:
                    self.assertTrue(f[z_index] in (0, 1))
        cells = {L.cell_of(o) for o in self.doc["a"]}
        self.assertEqual(set(result["kv"]), {str(hail.cell_key(*c)) for c in cells})
        texts = set(result["kv"].values())
        self.assertIn("Data unavailable", texts)
        self.assertTrue(any(t.endswith(" in") for t in texts))

    def test_a_cell_with_no_stored_value_reads_data_unavailable(self):
        result, tops = self.label()
        for outline in self.doc["a"]:
            cell = L.cell_of(outline)
            if cell not in tops:
                self.assertEqual(result["kv"][str(hail.cell_key(*cell))], "Data unavailable")

    def test_the_fixture_shard_places_the_same_clusters_each_time(self):
        first, _tops = self.label()
        second, _tops2 = self.label()
        self.assertEqual(first["flags"], second["flags"])
        self.assertEqual(first["kv"], second["kv"])

    def test_an_outline_outside_its_tile_gets_no_flag_and_is_counted(self):
        doc = json.loads(json.dumps(self.doc))
        doc["a"][0]["p"] = [-113.0, 46.9]                   # far from tile r0081_c0160 (cols 1600 to 1609)
        result, _tops = self.label(doc)
        self.assertEqual(result["flags"][0], [0, 0])
        self.assertEqual(result["stats"]["off_tile"], 1)

    def test_a_shard_rendered_without_flags_keeps_its_own_bytes(self):
        raw = (self.store / "hail" / "b" / SHARD).read_bytes()
        self.assertEqual(L.render(self.doc, None, None), raw)

    def test_the_rendered_flags_are_the_last_key_of_each_outline(self):
        result, _tops = self.label()
        data = L.render(self.doc, result["flags"], result["kv"])
        doc = json.loads(data)
        self.assertEqual([o["k"] for o in doc["a"]], result["flags"])
        self.assertEqual(list(doc.keys())[-1], "kv")
        self.assertEqual(list(doc["a"][0].keys())[-1], "k")


@needs_font
class BuildAndVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_build_writes_flags_and_the_manifest_and_verify_passes(self):
        block = L.build(self.store, tiles=[TILE], now="2026-10-17T12:00:00Z")
        self.assertEqual(block["state"], "loaded", block)
        raw = (self.store / "hail" / "b" / SHARD).read_bytes()
        doc = json.loads(raw)
        self.assertIn("kv", doc)
        self.assertTrue(all("k" in o for o in doc["a"]))
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        entry = manifest["files"][f"hail/b/{SHARD}"]
        self.assertEqual(entry["sha256"], _sha(raw))
        self.assertEqual(entry["bytes"], len(raw))
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index[L.INDEX_KEY]["state"], "loaded")
        result = L.verify(self.store, tiles=[TILE])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["shards_checked"], 1)

    def test_a_second_build_gives_the_same_bytes(self):
        L.build(self.store, tiles=[TILE], now="2026-10-17T12:00:00Z")
        first = (self.store / "hail" / "b" / SHARD).read_bytes()
        L.build(self.store, tiles=[TILE], now="2026-10-17T12:00:00Z")
        self.assertEqual((self.store / "hail" / "b" / SHARD).read_bytes(), first)

    def test_a_missing_radar_tile_is_partial_and_its_cells_read_data_unavailable(self):
        (self.store / "hail" / "t" / f"{TILE}.json").unlink()
        block = L.build(self.store, tiles=[TILE], now="2026-10-17T12:00:00Z")
        self.assertEqual(block["state"], "partial")
        self.assertTrue(any(TILE in f.get("tile", "") for f in block["failures"]))
        doc = json.loads((self.store / "hail" / "b" / SHARD).read_text(encoding="utf-8"))
        self.assertTrue(all(text == "Data unavailable" for text in doc["kv"].values()))

    def test_the_unavailable_command_removes_every_flag_and_verify_accepts_it(self):
        L.build(self.store, tiles=[TILE], now="2026-10-17T12:00:00Z")
        with redirect_stdout(io.StringIO()):
            L.main(["unavailable", "--store", str(self.store), "--reason", "the outlines were not in this update"])
        doc = json.loads((self.store / "hail" / "b" / SHARD).read_text(encoding="utf-8"))
        self.assertNotIn("kv", doc)
        self.assertTrue(all("k" not in o for o in doc["a"]))
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index[L.INDEX_KEY]["state"], "unavailable")
        self.assertTrue(L.verify(self.store)["ok"])

    def test_verify_names_a_shard_whose_flags_were_changed_by_hand(self):
        L.build(self.store, tiles=[TILE], now="2026-10-17T12:00:00Z")
        path = self.store / "hail" / "b" / SHARD
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["a"][0]["k"] = [1, 1]
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        result = L.verify(self.store, tiles=[TILE])
        self.assertFalse(result["ok"])

    def test_without_the_font_the_block_is_unavailable_and_no_shard_changes(self):
        before = (self.store / "hail" / "b" / SHARD).read_bytes()
        L._WIDTHS.clear()
        L._FONT.clear()
        with mock.patch.object(L, "FONT_FILE", Path(self.tmp) / "missing.woff2"):
            block = L.build(self.store, tiles=[TILE], now="2026-10-17T12:00:00Z")
        L._WIDTHS.clear()
        L._FONT.clear()
        self.assertEqual(block["state"], "unavailable")
        self.assertIn("font", block["problem"])
        self.assertEqual((self.store / "hail" / "b" / SHARD).read_bytes(), before)

    def test_measure_reads_the_store_and_writes_nothing(self):
        before = (self.store / "hail" / "b" / SHARD).read_bytes()
        out = self.tmp / "measure.json"
        result = L.measure(self.store, out=out)
        self.assertEqual(result["state"], "measured")
        self.assertEqual(result["shards"], 1)
        self.assertGreater(result["bubbles"]["17"], 0)
        self.assertGreater(result["bytes_added_total"], 0)
        self.assertEqual((self.store / "hail" / "b" / SHARD).read_bytes(), before)
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
