"""The one forbidden list (tests/words_rules.py): what it allows and what it still flags (D13, D41, D45, D46, D52, D78(b),
D86(a) to (e), D89(a)). Each allowance is an exact sentence or name, so each test pins the text it allows, the nearby text it
must still flag, and (where the text lives in a source file) that the allowed text is still in that file."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the one forbidden list, D81(c))
import words_rules as W  # noqa: E402


class RequiredSentenceTests(unittest.TestCase):
    def test_the_required_all_clear_sentences_pass(self):
        for text in ("This is not an all-clear.", "That is not an all-clear.",
                     "No active NWS alerts for this location at 6:00 am. That is not an all-clear.",
                     "That is not an all-clear: storms can form between updates."):
            self.assertEqual(W.forbidden_words(text), [], text)
            self.assertFalse(W.has_no_hail(text), text)

    def test_a_claim_of_an_all_clear_is_still_flagged(self):
        self.assertEqual(W.forbidden_words("An all-clear is given."), ["all-clear"])
        self.assertEqual(W.forbidden_words("This is not an all-clear, and an all-clear is not given."), ["all-clear"])

    def test_not_the_same_as_no_hail_passes_and_a_bare_no_hail_is_flagged(self):
        self.assertFalse(W.has_no_hail("Days not listed are not the same as no hail."))
        self.assertTrue(W.has_no_hail("No hail fell here."))


class NoaaTermTests(unittest.TestCase):
    def test_radar_coverage_is_NOAAs_term_and_passes(self):              # D45, D81(c)
        for text in ("Hatched: no radar coverage.", "Outside radar coverage.", "-999 means outside radar coverage."):
            self.assertEqual(W.forbidden_words(text), [], text)

    def test_any_other_coverage_is_still_flagged(self):                    # the D13 stem
        self.assertEqual(W.forbidden_words("Insurance coverage."), ["coverage", "insurance"])
        self.assertEqual(W.forbidden_words("Full coverage for the roof."), ["coverage"])


class NameAndCitationTests(unittest.TestCase):
    def test_the_state_library_name_and_its_file_name_are_citations(self):  # D86(e)
        for text in ("Montana State Library Structures and Addresses Framework",
                     "Structures and Addresses Framework", "StructuresFramework_shp.zip", "USA Structures"):
            self.assertEqual(W.forbidden_words(text), [], text)

    def test_a_bare_structure_word_is_still_flagged(self):
        self.assertEqual(W.forbidden_words("The structure of the roof."), ["structure"])
        self.assertEqual(W.forbidden_words("Structures Framework."), ["structures"])

    def test_the_two_references_titles_pass_only_in_full(self):           # D46, D86(d)
        self.assertEqual(W.forbidden_words("FEMA P-957, Snow Load Safety Guide"), [])
        self.assertEqual(W.forbidden_words("freeze-thaw damage to roofs (R20, not quoted)"), [])
        self.assertEqual(W.forbidden_words("Snow Load Safety"), ["safety"])
        self.assertEqual(W.forbidden_words("freeze-thaw damage"), ["damage"])


class WordForWordTests(unittest.TestCase):
    def test_the_storm_sentence_passes_word_for_word_only(self):         # D78(b), D86(a)
        self.assertEqual(W.forbidden_words("A radar estimate, not observed hail or damage."), [])
        self.assertEqual(W.forbidden_words("A radar estimate, not observed hail or loss."), ["loss"])
        self.assertEqual(W.forbidden_words("Not observed hail or damage."), [])
        self.assertEqual(W.forbidden_words("It is not observed hail or damage, and it is high."), ["damage"])

    def test_the_site_footer_passes_word_for_word_only(self):           # D52
        footer = ("Weather information only. It does not confirm roof damage and it is not a decision to work or to stop "
                  "work: check the sky and the site.")
        self.assertEqual(W.residue(footer).strip(), "")
        # an altered footer is no longer the exempt sentence: its "confirm" and its new word are both flagged
        self.assertEqual(W.forbidden_words(footer.replace("roof damage", "roof loss")), ["confirm", "loss"])

    def test_the_state_library_purpose_passes_word_for_word_only(self):   # D86(c)
        purpose = ("To provide a statewide, standardized repository for structure and address point data. The "
                   "Structures/Addresses Framework complies with the NENA Standard for NG9-1-1 GIS Data Model and is designed "
                   "to support a wide range of public and private sector uses including: 9-1-1 and emergency response, "
                   "elections management, broadband internet mapping, census programs, planning, natural resource studies, etc.")
        self.assertEqual(W.residue(purpose).strip(), "")
        self.assertEqual(W.forbidden_words("To provide a structure for the roof."), ["structure"])

    def test_the_nws_conditions_pass_word_for_word_only(self):           # D46, D86(c)
        nws = ("The information on National Weather Service (NWS) Web pages are in the public domain, unless specifically "
               "noted otherwise, and may be used without charge for any lawful purpose so long as you do not: 1) claim it is "
               "your own (e.g., by claiming copyright for NWS information -- see below), 2) use it in a manner that implies "
               "an endorsement or affiliation with NOAA/NWS, or 3) modify its content and then present it as official "
               "government material.")
        self.assertEqual(W.residue(nws).strip(), "")
        self.assertEqual(W.forbidden_words("You may claim it as your own."), ["claim"])


class ForecastWordsTests(unittest.TestCase):
    """The NWS forecast and observation wording is the forecast product's own, not history text (D89(a)), so the scan
    reads it as clean. Each exemption is a whole field or a whole part of a line, so the same words in history text are
    still flagged (D13)."""

    def test_the_nws_condition_and_chance_wording_passes(self):           # D89(a)
        for text in ("Clear", "Clear.", "Chance Rain Showers", "chance rain showers", "40% chance of rain or snow",
                     "Chance of rain or snow"):
            with self.subTest(text=text):
                W.assert_clean(self, text, text)

    def test_the_observation_line_passes(self):                           # D89(a): the town page's "Read at" line
        for text in ("Read at 5:48 am, 12 min ago \u00b7 SAMPLE Clear", "Read at 5:48 am, 12 min ago \u00b7 Clear",
                     "Read at 3:30 am, 2 h 30 min ago \u00b7 stale \u00b7 SAMPLE Clear"):
            with self.subTest(text=text):
                W.assert_clean(self, text, text)

    def test_the_day_line_passes(self):                                   # D89(a): the town page's day line
        for text in (
            "Sunday High 61\u00b0 / low 39\u00b0 Sunny \u00b7 10% rain or snow \u00b7 wind 5 to 10 mph W "
            "\u00b7 night: clear SAMPLE. High near 61. Winds 5 to 10 mph.",
            "Sunny \u00b7 10% rain or snow \u00b7 wind 5 to 10 mph W \u00b7 night: clear",
            "Sunny \u00b7 10% rain or snow \u00b7 wind 5 to 10 mph W \u00b7 night: clear "
            "SAMPLE. High near 61. Winds 5 to 10 mph.",
            "Today High 62\u00b0 / low 40\u00b0 Chance Rain Showers \u00b7 40% rain or snow \u00b7 wind 5 to 10 mph W "
            "\u00b7 night: chance rain showers SAMPLE. High near 62. Winds 5 to 10 mph.",
        ):
            with self.subTest(text=text):
                W.assert_clean(self, text, text)

    def test_the_same_words_in_history_text_are_still_flagged(self):      # D13: a field, not a word
        self.assertEqual(W.forbidden_words("Clear sky over the roof."), ["clear"])
        self.assertEqual(W.forbidden_words("A clear view of the roof."), ["clear"])
        self.assertEqual(W.forbidden_words("Clear Creek"), ["clear"])
        self.assertEqual(W.forbidden_words("clear"), ["clear"])
        self.assertEqual(W.forbidden_words("Clear. High near 61."), ["clear"])
        self.assertEqual(W.forbidden_words("Chance of hail this week."), ["chance"])
        self.assertEqual(W.forbidden_words("The chance of hail is high."), ["chance"])
        self.assertEqual(W.forbidden_words("Chance of hail or rain or snow."), ["chance"])
        self.assertEqual(W.forbidden_words("Chance of hail or damage this week."), ["chance", "damage"])

    def test_the_observation_and_day_lines_still_flag_history_words(self):   # D89(a) with D13
        self.assertEqual(W.forbidden_words("Read at 5:48 am, 12 min ago \u00b7 Clear sky over the roof"), ["clear"])
        self.assertEqual(W.forbidden_words("Sunny \u00b7 night: clear skies were seen."), ["clear"])
        self.assertEqual(W.forbidden_words("Chance of rain or snow, and a risk of hail."), ["risk"])


class OutsideGridTests(unittest.TestCase):
    def test_the_outside_grid_sentence_says_the_history_does_not_cover_the_point(self):   # D86(f)
        self.assertEqual(W.forbidden_words("This point is outside the hail grid's Montana outline; the history does not "
                                           "cover it."), [])
        self.assertFalse(W.has_no_hail("This point is outside the hail grid's Montana outline; the history does not "
                                       "cover it."))
        self.assertTrue(W.has_no_hail("This point is outside the hail grid's Montana outline; no hail history is kept here."))


class SourceTextTests(unittest.TestCase):
    """The exact text each allowance names is still in the file it cites (so an edit that changes it fails here)."""

    def read(self, *parts):
        return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_the_footer_sentence_is_in_the_base_template(self):
        found = re.search(r"<p>(Weather information only\. [^<]*)</p>", self.read("website", "templates", "base.html"))
        self.assertIsNotNone(found)
        self.assertEqual(W.residue(found.group(1)).strip(), "")

    def test_the_storm_sentences_are_in_the_rows_and_the_pages(self):
        self.assertIn("A radar estimate, not observed hail or damage.", self.read("website", "sources.py"))
        for part in (("website", "templates", "town.html"), ("website", "templates", "map.html")):
            self.assertIn("Not observed hail or damage.", self.read(*part))

    def test_the_two_titles_are_in_the_references_list(self):
        summary = self.read("website", "summary.py")
        self.assertIn('"FEMA P-957, Snow Load Safety Guide"', summary)
        self.assertIn('"freeze-thaw damage to roofs"', summary)

    def test_the_purpose_and_the_names_are_the_addresses_module_text(self):
        from website import addresses
        self.assertEqual(W.residue(addresses.PURPOSE_TEXT).strip(), "")
        # the State Library's name is the citation; the dates around it are not, so only the name is removed
        source = addresses.WORDS_ADDRESSES["about_source"].format(pubdate="2026-09-30", export_date="2026-09-30")
        self.assertEqual(W.forbidden_words(source), [])
        self.assertNotIn("Structures", W.residue(source))
        for key in ("about_source", "about_source_undated", "about_access", "about_use", "about_purpose"):
            W.assert_clean(self, addresses.WORDS_ADDRESSES[key], key)

    def test_the_nws_conditions_are_the_snow_module_text(self):
        from website import snowgrid
        self.assertEqual(W.residue(snowgrid.PUBLIC_DOMAIN_TEXT).strip(), "")

    def test_the_nws_forecast_wording_is_in_the_files_that_show_it(self):   # D89(a): a dropped wording fails here
        for part, needle in ((("website", "sources.py"), "chance of rain or snow"),
                             (("website", "templates", "index.html"), "chance of rain or snow"),
                             (("website", "static", "map", "map.js"), "chance of rain or snow"),
                             (("website", "templates", "town.html"), "Read at "),
                             (("website", "sample.py"), "Chance Rain Showers"),
                             (("website", "sample.py"), "SAMPLE Clear")):
            self.assertIn(needle.lower(), self.read(*part).lower(), f"{needle!r} is not in {'/'.join(part)}")

    def test_the_building_words_pass_the_one_list(self):
        from website import buildings
        for key, text in buildings.WORDS_BUILDINGS.items():
            if key == "about_source":
                text = text.format(file_date="2026-09-30")
            W.assert_clean(self, text, key)
        # D41: the unavailable line says why and ends with the required sentence
        self.assertTrue(buildings.WORDS_BUILDINGS["unavailable"].endswith(" This is not an all-clear."))


if __name__ == "__main__":
    unittest.main()
