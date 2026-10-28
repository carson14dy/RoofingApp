"""The browser side of B6 stage S2 (website/static/map/map.js, map.css): the B6 drawing section keeps the literal rules of the B3
section (AGENTS.md rule 4: words, numbers and colours come from data or from map.css tokens), the script calls its functions
and names no sentence of the sheet, and the stylesheet carries its tokens and rules in both colour schemes. The drawing
itself is checked in a browser by tools/smoke_map.py (check_b6_terrain_pictures_zones)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import build as site  # noqa: E402
from website import history_layers as hl  # noqa: E402
from website import terrain as tr  # noqa: E402

MAP_JS = ROOT / "website" / "static" / "map" / "map.js"
MAP_CSS = ROOT / "website" / "static" / "map" / "map.css"
B3_BEGIN, B3_END = "// B3 layers: begin", "// B3 layers: end"
B6_BEGIN, B6_END = "// B6 drawing: begin", "// B6 drawing: end"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def body(js: str, header: str, stop: str) -> str:
    """The text of one function: from its header to the next function's header (stop)."""
    start = js.index(header)
    return js[start:js.index(stop, start)]


class B6Browser(unittest.TestCase):

    def test_the_b6_section_sits_after_the_b3_section_between_its_markers(self):
        js = read(MAP_JS)
        for marker in (B3_BEGIN, B3_END, B6_BEGIN, B6_END):
            self.assertEqual(js.count(marker), 1, marker)
        self.assertLess(js.index(B3_END), js.index(B6_BEGIN))
        self.assertLess(js.index(B6_BEGIN), js.index(B6_END))

    def test_the_credit_control_sits_before_the_b3_section_and_the_b3_lines_use_it(self):
        js = read(MAP_JS)
        self.assertLess(js.index("function creditControl("), js.index(B3_BEGIN))
        self.assertLess(js.index("function creditLift("), js.index(B3_BEGIN))
        self.assertEqual(js.count("L.control.attribution("), 0, "the credit control is the page's own (CreditControl)")
        self.assertEqual(js.count("new CreditControl()"), 1, "one credit control: creditControl makes it")
        ctl = body(js, "var CreditControl = L.Control.extend({", "function creditControl()")
        for name in ("addAttribution:", "removeAttribution:", "toggle:", "_attributions", "PW.credits_show", "PW.credits_hide",
                     '"aria-expanded"', "credits-toggle", "credits-lines"):
            self.assertIn(name, ctl, name)
        self.assertEqual(site.PAGE_WORDS["credits_show"], "Sources")
        self.assertEqual(site.PAGE_WORDS["credits_hide"], "Hide sources")
        b3 = body(js, "function b3Credits()", "function b3Queue()")
        self.assertIn("creditControl().addAttribution(esc(line))", b3)
        self.assertNotIn("b3Lift", js, "the lift is creditLift (the one control's helper)")

    def test_map_script_b6_section_holds_no_sentence_unit_radius_zoom_cap_width_or_colour_literal(self):
        js = read(MAP_JS)
        self.assertIsNone(re.search(r"\b(houses?|residences?|dwellings?)\b", js, re.I))
        begin, end = js.find(B6_BEGIN), js.find(B6_END)
        self.assertTrue(begin >= 0 and end > begin, "map.js needs the B6 section between the two markers")
        block = js[begin:end]
        code = re.sub(r"/\*.*?\*/|//[^\n]*", " ", block, flags=re.S)  # comments may hold the words of the design
        literals = re.findall(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`([^`]*)`', code)
        for group in literals:
            text = group[0] or group[1] or group[2]
            words = text.split()
            self.assertFalse(len(words) >= 3, f"a sentence in the B6 section: {text!r}")
            self.assertIsNone(re.search(r"\b(mph|mm|inch|inches|miles?|metres?|kt|knots?)\b|%|°", text), text)
            self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", text), text)
        bare = re.sub(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`[^`]*`', " ", code)
        # A number on a line about a zoom, a radius, a width, a cap, a limit or a grid is a display rule and must come from
        # map.json (here: base.json). Geometry constants (0, 1, 2, 0.5, 180, 256, 360: the half turn, the tile size, the full
        # turn) are allowed. The layer order of the B6 panes is a drawing order, not a rule (as B3_PANE is).
        rule_words = re.compile(r"radius|width|\bcap\b|zoom|\bz\b|\bZ\.|tap|\bpx\b|limit|per_view|grid|min_|max_|from\b")
        allowed = {"0", "1", "2", "0.5", "180", "256", "360"}
        flagged = []
        for line in bare.splitlines():
            if rule_words.search(line):
                flagged += [n for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", line) if n not in allowed]
        self.assertEqual(sorted(set(flagged)), [], "a display rule written in map.js (it must come from base.json)")
        # the words the B6 modules write never appear in the script (their sentences come from base.json)
        words = [*tr.WORDS.values(), *hl.WORDS.values()]
        for text in words:
            if isinstance(text, str) and "{" not in text and len(text) > 25:
                self.assertNotIn(text, js, text)

    def test_map_script_defines_the_b6_functions_and_the_hook_and_calls_them_from_the_page(self):
        js = read(MAP_JS)
        for name in ("creditControl", "creditLift", "b6Start", "b6Base", "b6Terrain", "b6Apply", "b6Keys", "b6Legend",
                     "b6Pictures", "b6Zones", "b6Fail", "b6Tiles"):
            self.assertRegex(js, rf"function {name}\(", name)
        self.assertIn("window.b6MapTest = {", js)
        for key in ("base:", "view:", "terrain:", "pictures:", "zones:", "credits:", "fetches:"):
            self.assertIn(key, body(js, "window.b6MapTest = {", "// B6 drawing: end"), key)
        start = body(js, "function start(mapData)", "function createMap(")
        self.assertIn("b6Start();", start)
        self.assertLess(start.index("b3Start();"), start.index("b6Start();"))
        render = body(js, "function renderOptions()", "function setLive(")
        self.assertIn("b6Apply();", render)
        self.assertIn(".then(b6Base);", body(js, "function loadBase()", "function trapOptionsFocus("))
        self.assertIn("H_ = state.layer ? null : b6Legend();", body(js, "function renderLegend()", "function thinStops("))
        self.assertIn("keys = keys.concat(b6Keys());", body(js, "function renderKeys()", "function noOutlineCount("))

    def test_the_b6_zone_line_is_a_token_in_both_colour_schemes(self):
        css = read(MAP_CSS)
        light = css[css.index(":root {"):]
        light = light[:light.index("\n}")]
        dark = css[css.index("@media (prefers-color-scheme: dark) {"):]
        dark = dark[dark.index(":root {"):]
        dark = dark[:dark.index("\n  }")]
        self.assertRegex(light, r"--b6-zone-line:\s*var\(--m-grey-\d\);")
        self.assertRegex(dark, r"--b6-zone-line:\s*var\(--m-grey-\d\);")

    def test_the_b6_css_rules_hold_and_use_no_hex_value(self):
        css = read(MAP_CSS)
        start = css.index("/* ---------------------------------------------------------------- B6 drawing")
        block = css[start:css.index("/* ---------------------------------------------------------------- card mode", start)]
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", block), [], "a hex value in a B6 rule")
        for rule in ("#app.has-terrain .bm-land.bm-mt { fill-opacity: 0; }",
                     ".leaflet-terrain-pane .b6-shade { mix-blend-mode: multiply; }",
                     "#app.is-imagery .leaflet-terrain-pane { display: none; }",
                     "path.b6-zone { stroke: var(--b6-zone-line); stroke-width: 1px; }",
                     "path.b6-zone-none { fill: none; stroke-dasharray: 4 3; }"):
            self.assertIn(rule, block, rule)
        self.assertIn("@media (prefers-color-scheme: dark) { #app.has-terrain .bm-land.bm-mt { fill-opacity: 1; } }", block)

    def test_the_credit_control_passes_no_taps_to_the_map_under_its_lines(self):
        css = read(MAP_CSS)
        rule = re.search(r"\.leaflet-container \.leaflet-control-attribution \{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        self.assertIn("pointer-events: none;", rule.group(1))
        self.assertIn(".credits-toggle { pointer-events: auto; min-height: 44px;", css)   # the one part that takes taps

    def test_the_map_script_names_no_sentence_of_the_sheet_outside_the_b6_section(self):
        js = read(MAP_JS)
        outside = js[:js.index(B6_BEGIN)] + js[js.index(B6_END):]
        for key, text in site.SHEET_WORDS.items():
            if isinstance(text, str) and "{" not in text and len(text) > 25:
                self.assertNotIn(text, outside, key)


if __name__ == "__main__":
    unittest.main()
