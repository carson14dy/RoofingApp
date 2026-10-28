"""B6 drawing, stage S2, the Python side (docs/DESIGN.md section 13; the architecture brief names each rule): the terrain tiles'
drawing rules and tile set (terrain.DRAW, terrain.compact_set), the zone layers' palettes and words (history_layers), and the
blocks the browser draws from (data/base.json). The browser side (map.js, map.css, tools/smoke_map.py) is checked in Chromium.

Everything here runs offline. The outline is the repository's basemap.json; the built sites use the B6 store that
tests/test_site.py writes (b6_store), so the words gate and the store helper are the same ones the other B6 tests use.
"""

import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))   # tests/words_rules.py (the one forbidden list)
from website import build as site  # noqa: E402
from website import history_layers as hl  # noqa: E402
from website import terrain as tr  # noqa: E402
import words_rules as W  # noqa: E402
from tests import test_site as ts  # noqa: E402   (b6_store and b6_words_hits; its TestCase classes are not collected here)

UTC = timezone.utc
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
COUNTS = {5: 4, 6: 9, 7: 22, 8: 56, 9: 178, 10: 612}     # the 881 tiles of the Montana outline, per zoom (terrain.tile_set)
HEX = re.compile(r"#[0-9a-f]{6}")
SHEET_PICTURE_FAILED = ("Data unavailable. The picture for this layer could not be loaded in this update; that is not the same as "
                        "no hail or no heat. This is not an all-clear.")


def expand(split: dict) -> dict:
    """The tiles a compact set names, as {zoom: {(x, y), ...}}: the browser's reading of base.json terrain.set."""
    return {int(z): {(x, int(y)) for y, runs in rows.items() for x0, x1 in runs for x in range(x0, x1 + 1)}
            for z, rows in split.items()}


def counts_of(split: dict) -> dict:
    return {int(z): sum(x1 - x0 + 1 for runs in rows.values() for x0, x1 in runs) for z, rows in split.items()}


class CompactSet(unittest.TestCase):
    """terrain.compact_set: the browser's split map of the tile set (the shape of map.json's tile_split, D144)."""

    def test_a_hand_made_set_gives_its_maximal_sorted_runs_per_row(self):
        tiles = {5: [(1, 2), (2, 2), (3, 2), (5, 2), (4, 3), (4, 4), (9, 4), (10, 4)]}
        self.assertEqual(tr.compact_set(tiles), {"5": {"2": [[1, 3], [5, 5]], "3": [[4, 4]], "4": [[4, 4], [9, 10]]}})

    def test_unsorted_and_repeated_tiles_give_the_same_runs_and_a_zoom_with_none_is_an_empty_map(self):
        self.assertEqual(tr.compact_set({7: [(3, 1), (1, 1), (2, 1), (2, 1)]}), {"7": {"1": [[1, 3]]}})
        self.assertEqual(tr.compact_set({6: []}), {"6": {}})
        self.assertEqual(tr.compact_set({}), {})

    def test_the_keys_are_strings_so_the_set_is_json(self):
        split = tr.compact_set({5: [(4, 6)]})
        self.assertEqual(json.loads(json.dumps(split)), {"5": {"6": [[4, 4]]}})

    def test_the_real_set_has_the_outline_counts_and_its_runs_are_sorted_disjoint_and_maximal(self):
        tiles = tr.tile_set(tr.montana_rings(), tr.ZOOMS)
        split = tr.compact_set(tiles)
        self.assertEqual(counts_of(split), COUNTS)
        self.assertEqual(sum(COUNTS.values()), 881)
        self.assertEqual(expand(split), {z: set(found) for z, found in tiles.items()})     # the runs name exactly the tile set
        for z, rows in split.items():
            for y, runs in rows.items():
                for x0, x1 in runs:
                    self.assertLessEqual(x0, x1, (z, y))
                for (a0, a1), (b0, b1) in zip(runs, runs[1:]):
                    # sorted and disjoint, and maximal: the next run starts past a gap, never at the next x
                    self.assertGreater(b0, a1 + 1, (z, y))


class TerrainDrawing(unittest.TestCase):
    """terrain.map_data carries the draw rules and the tile set for a loaded (or partial) terrain part, and neither otherwise."""

    @staticmethod
    def index(state: str = "loaded") -> dict:
        return {"base": {"format": "hail-base-v1", "terrain": {
            "state": state, "problem": None, "zooms": list(tr.ZOOMS),
            "as_of": {"shading_date": "2026-09-28", "land_cover": "2023-06"},
            "layers": {"h": {"state": "loaded", "path": "hail/base/h/{z}/{x}/{y}.jpg", "missing": [], "files": 4, "problem": None},
                       "l": {"state": "loaded", "path": "hail/base/l/{z}/{x}/{y}.png", "missing": [], "files": 4, "problem": None}}}}}

    def test_a_loaded_index_carries_the_draw_rules_and_the_tile_set(self):
        data = tr.map_data(self.index())
        self.assertEqual(data["state"], "loaded")
        self.assertEqual(data["draw"], tr.DRAW)
        self.assertEqual(data["draw"], {"shade_opacity": 0.45, "tint_opacity": 0.9, "fade": {"11": 0.6, "12": 0.3}, "off_from": 13})
        self.assertEqual(counts_of(data["set"]), COUNTS)

    def test_a_partial_index_carries_them_too(self):
        data = tr.map_data(self.index("partial"))
        self.assertEqual(data["state"], "partial")
        self.assertEqual(data["draw"], tr.DRAW)
        self.assertEqual(counts_of(data["set"]), COUNTS)

    def test_an_unavailable_index_and_no_index_carry_neither(self):
        unavailable = {"base": {"format": "hail-base-v1", "terrain": {"state": "unavailable", "problem": tr.WORDS["unavailable"]}}}
        for index in (None, unavailable):
            data = tr.map_data(index)
            self.assertEqual(data["state"], "unavailable")
            self.assertNotIn("draw", data)
            self.assertNotIn("set", data)

    def test_the_draw_copy_is_not_the_module_rule(self):
        data = tr.map_data(self.index())
        data["draw"]["off_from"] = 99
        self.assertEqual(tr.DRAW["off_from"], 13)


class ZoneLayers(unittest.TestCase):
    """history_layers.ZONE_LAYERS: the two zone layers, their measures and classes, and the alpha (DESIGN 13.4, D115(b))."""

    def test_there_are_the_wind_and_the_flood_layers_with_the_brief_measures_and_titles(self):
        self.assertEqual(set(hl.ZONE_LAYERS), {"wind", "flood"})
        self.assertEqual(hl.ZONE_LAYERS["wind"]["measures"], ("high_wind_warnings", "high_wind_watches", "wind_advisories"))
        self.assertEqual(hl.ZONE_LAYERS["flood"]["measures"], ("flood_watches", "flood_warnings", "flood_advisories",
                                                               "flash_flood_watches", "flash_flood_warnings"))
        self.assertEqual(hl.ZONE_LAYERS["wind"]["title"], "High wind warnings and watches and wind advisories by forecast zone")
        self.assertEqual(hl.ZONE_LAYERS["flood"]["title"], "Flood and flash flood watches, warnings and advisories by forecast zone")
        self.assertIs(hl.ZONE_LAYERS["wind"]["classes"], hl.ZONE_WIND_CLASSES)
        self.assertIs(hl.ZONE_LAYERS["flood"]["classes"], hl.ZONE_FLOOD_CLASSES)

    def test_every_measure_of_a_layer_is_one_of_the_eight_zone_measures(self):
        keys = {m["key"] for m in hl.MEASURES}
        self.assertEqual(len(keys), 8)
        for key, layer in hl.ZONE_LAYERS.items():
            self.assertEqual(len(set(layer["measures"])), len(layer["measures"]), key)
            for measure in layer["measures"]:
                self.assertIn(measure, keys, key)

    def test_the_classes_cover_every_count_from_zero_with_no_gap_and_no_overlap(self):
        for key, layer in hl.ZONE_LAYERS.items():
            classes = layer["classes"]
            self.assertEqual((classes[0]["min"], classes[0]["max"]), (0, 0), key)
            for here, there in zip(classes, classes[1:]):
                self.assertEqual(here["max"] + 1, there["min"], (key, here["word"]))
            self.assertIsNone(classes[-1]["max"], key)
            for c in classes:
                if c["max"] is not None:
                    self.assertLessEqual(c["min"], c["max"], (key, c["word"]))

    def test_the_first_class_has_no_colour_and_every_other_class_has_a_hex_colour(self):
        for key, layer in hl.ZONE_LAYERS.items():
            first, rest = layer["classes"][0], layer["classes"][1:]
            self.assertIsNone(first["colour"], key)
            self.assertEqual(first["word"], "none in the archive files read", key)
            for c in rest:
                self.assertIsNotNone(HEX.fullmatch(c["colour"] or ""), (key, c["colour"]))

    def test_the_alpha_is_140_and_the_words_pass_the_words_rules(self):
        self.assertEqual(hl.ZONE_ALPHA, 140)
        for key, layer in hl.ZONE_LAYERS.items():
            W.assert_clean(self, layer["title"], key)
            for c in layer["classes"]:
                W.assert_clean(self, c["word"], f"{key} class")

    def test_the_zone_words_are_the_brief_sentences(self):
        self.assertEqual(hl.WORDS["zone_unavailable_key"], "No count for this zone: Data unavailable")
        self.assertEqual(hl.WORDS["zone_outline_failed"],
                         "Data unavailable. The zone outlines could not be loaded, so no zone is drawn; that is not the same as no "
                         "products. This is not an all-clear.")
        self.assertEqual(hl.WORDS["zones_sum"], "{title}: the sum of the counted products for each zone over {first} to {last}, in "
                                                "classes. A zone with no count reads Data unavailable. This is not an all-clear.")
        for key in ("zone_unavailable_key", "zone_outline_failed", "zones_sum"):
            W.assert_clean(self, hl.WORDS[key], key)


class ZoneLayersInTheSite(unittest.TestCase):
    """A built site with the B6 store (the same store tests/test_site.py's B6BaseMapData builds) and the default build: what
    data/base.json and data/map.json carry for the terrain drawing, the zone layers and the sheet's picture sentence."""

    @classmethod
    def setUpClass(cls):
        cls.default = Path(tempfile.mkdtemp(prefix="hailwatch-b6s2-default-"))
        cls.addClassCleanup(shutil.rmtree, cls.default, True)
        site.build(cls.default, None, NOW, sample=True)
        store = Path(tempfile.mkdtemp(prefix="hailwatch-b6s2-store-"))
        cls.addClassCleanup(shutil.rmtree, store, True)
        ts.b6_store(store)
        cls.loaded = Path(tempfile.mkdtemp(prefix="hailwatch-b6s2-loaded-"))
        cls.addClassCleanup(shutil.rmtree, cls.loaded, True)
        site.build(cls.loaded, None, NOW, sample=True, hail_history=True, hail_store_path=str(store))

    @staticmethod
    def base(out: Path) -> dict:
        return json.loads((out / "data" / "base.json").read_text(encoding="utf-8"))

    def test_the_loaded_terrain_block_carries_the_draw_rules_and_the_tile_set(self):
        terrain = self.base(self.loaded)["base"]["terrain"]
        self.assertEqual(terrain["state"], "loaded")
        self.assertEqual(terrain["draw"], tr.DRAW)
        self.assertEqual(counts_of(terrain["set"]), COUNTS)
        self.assertEqual(expand(terrain["set"]), {z: set(found) for z, found in tr.tile_set(tr.montana_rings(), tr.ZOOMS).items()})

    def test_the_default_build_has_no_draw_rules_and_no_tile_set(self):
        terrain = self.base(self.default)["base"]["terrain"]
        self.assertEqual(terrain["state"], "unavailable")
        self.assertNotIn("draw", terrain)
        self.assertNotIn("set", terrain)

    def test_the_loaded_zone_layers_carry_the_module_measures_title_classes_alpha_and_legend(self):
        layers = self.base(self.loaded)["history_layers"]["zone_layers"]
        self.assertEqual(set(layers), {"wind", "flood"})
        window = (hl._words_day(date(2021, 10, 17)), hl._words_day(date(2026, 10, 16)))     # the B6 store's window
        self.assertEqual(window, ("Oct 17, 2021", "Oct 16, 2026"))
        for key, module in hl.ZONE_LAYERS.items():
            block = layers[key]
            self.assertEqual(block["measures"], list(module["measures"]), key)
            self.assertEqual(block["title"], module["title"], key)
            self.assertEqual(block["classes"], [dict(c) for c in module["classes"]], key)
            self.assertEqual(block["alpha"], 140, key)
            self.assertEqual(block["legend"], hl.WORDS["zones_sum"].format(title=module["title"], first=window[0], last=window[1]), key)
            self.assertIn(module["title"], block["legend"])
            self.assertIn(f"{window[0]} to {window[1]}", block["legend"])

    def test_the_history_words_carry_the_two_zone_sentences(self):
        words = self.base(self.loaded)["history_layers"]["words"]
        self.assertEqual(words, {"zone_unavailable_key": hl.WORDS["zone_unavailable_key"],
                                 "zone_outline_failed": hl.WORDS["zone_outline_failed"]})

    def test_the_default_build_has_no_zone_layers_because_its_history_block_is_unavailable(self):
        history = self.base(self.default)["history_layers"]
        self.assertEqual(history["state"], "unavailable")
        self.assertNotIn("zone_layers", history)
        self.assertNotIn("words", history)

    def test_nothing_of_the_drawing_is_added_to_data_map_json(self):
        for out in (self.default, self.loaded):
            text = (out / "data" / "map.json").read_text(encoding="utf-8")
            doc = json.loads(text)
            self.assertNotIn("draw", doc["base"])
            self.assertNotIn("set", doc["base"])
            self.assertNotIn("zone_layers", text)

    def test_every_string_value_of_base_json_passes_the_words_gate(self):
        for out in (self.default, self.loaded):
            self.assertEqual(ts.b6_words_hits(self.base(out)), [], out.name)

    def test_the_sheet_carries_the_picture_failed_sentence_in_both_builds(self):
        for out in (self.default, self.loaded):
            self.assertEqual(self.base(out)["sheet"]["picture_failed"], SHEET_PICTURE_FAILED, out.name)


class SheetPictureFailed(unittest.TestCase):
    """build.SHEET_WORDS: the sentence a picture chip shows when its picture (hail or heat) fails to load (S2, DESIGN 13.6)."""

    def test_the_sheet_words_hold_the_picture_failed_sentence(self):
        self.assertEqual(site.SHEET_WORDS["picture_failed"], SHEET_PICTURE_FAILED)
        self.assertTrue(site.SHEET_WORDS["picture_failed"].startswith("Data unavailable. "))
        self.assertIn("not the same as no hail or no heat", site.SHEET_WORDS["picture_failed"])

    def test_the_picture_failed_sentence_passes_the_words_rules(self):
        W.assert_clean(self, site.SHEET_WORDS["picture_failed"], "sheet picture_failed")
        self.assertNotIn(chr(0x2014), site.SHEET_WORDS["picture_failed"])


if __name__ == "__main__":
    unittest.main()
