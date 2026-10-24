"""The forbidden words for the hail history's text: one list for every test module that scans words (F29, B5 D13).

The list is the research's own (research-b35/roof-indicators.json, measurements.forbidden_terms_added.words), written as
stems, plus the brief's D13 (nothing states damage, loss, a claim, coverage, insurance, eligibility, a probability, risk
or an all-clear) and the older test lists this list replaces (dry, clear, customers, guaranteed, approved, best, confirm).

A scan first removes what the brief allows, and nothing else: quoted wording (curly or straight quotation marks: a
remark, or a source's own words), the NWS damage threat tag label, the required "This is not an all-clear." (and "That
is not an all-clear.", the same sentence on the no-alerts line), the allowed "not the same as no hail", NOAA's term
"radar coverage" (D45), and the exact sentences and names listed in EXEMPT below, each with its ruling. It then fails
any forbidden word left in the text, and any "no hail" left in it. "damage" is a forbidden stem, so a source's type word
that contains it has to be quoted, or be an abbreviation such as DMG, which the words never print as a claim about this
address.

Imported by name: the test modules put tests/ on sys.path (discover -s tests)."""

import re

STEMS = (
    r"risks?", r"probab\w*", r"chances?", r"odds", r"likely", r"fails?", r"failures?", r"collaps\w*",
    r"structur\w*", r"replac\w*", r"repairs?", r"unsafe\w*", r"safe\w*", r"exceed\w*", r"overload\w*", r"agings?",
    r"aged", r"lifespan", r"useful life", r"brittle", r"degrad\w*", r"wear", r"worn", r"cracks?", r"cracked", r"leak\w*",
    r"intact", r"okay", r"fine", r"good condition", r"poor condition", r"claims?", r"adjusters?", r"loss\w*", r"lost",
    r"polic(?:y|ies)", r"warrant\w*", r"expect\w*", r"struck", r"strik\w*", r"no damage", r"\w*damag\w*", r"all[ -]clear",
    r"coverage", r"insur\w*", r"eligib\w*", r"confirm\w*", r"dry", r"clear\w*", r"customers?", r"guarantee\w*",
    r"approved", r"best",
)

FORBIDDEN = re.compile(r"\b(?:" + "|".join(STEMS) + r")\b", re.IGNORECASE)
NO_HAIL = re.compile(r"\bno hail\b", re.IGNORECASE)

# What the brief allows, and nothing else (each is removed before the scan). Order matters where one text holds another.
EXEMPT = (
    re.compile(r"“[^”]*”"),        # quoted wording: a remark, or the source's own words
    re.compile(r'"[^"]*"'),                       # straight-quoted wording
    re.compile(r"NWS damage threat tag"),         # the label of the NWS's own product field (B2 D4)
    re.compile(r"\b(?:This|That) is not an all-clear\b\.?"),   # the required sentence (D41), with its full stop when it has one;
    #                                                      "That" is the no-alerts form, which the index page follows with a caveat
    re.compile(r"not the same as no hail"),       # the one allowed "no hail"
    re.compile(r"radar coverage", re.IGNORECASE),  # NOAA's term, "no radar coverage" or "outside radar coverage" (D45, D81(c))
    # Source names and file names are citations (D86(e)), as "USA Structures" is:
    re.compile(r"USA Structures"),                # a proper name (the B3 attribution line)
    re.compile(r"Montana State Library Structures and Addresses Framework"),   # the State Library's name (D86(e))
    re.compile(r"Structures and Addresses Framework"),   # the same name as the rows and the attribution give it (D86(e))
    re.compile(r"StructuresFramework_shp\.zip"),  # the State Library's file name (D86(e); tests/test_joins.py sets it aside too)
    # Titles of the About references list (D46, D86(d)): these two titles, in that list only
    re.compile(r"FEMA P-957, Snow Load Safety Guide"),
    re.compile(r"freeze-thaw damage to roofs"),
    # Sentences a source or an earlier ruling keeps word for word (each cannot be reworded without changing what it says)
    re.compile(r"A radar estimate, not observed hail or damage\."),   # the storm_levels row (D78(b), D86(a))
    re.compile(r"Not observed hail or damage\."),                     # the storm layer's sentence on the town and map pages (D78(b))
    re.compile(r"Weather information only\. It does not confirm roof damage and it is not a decision to work or to stop "
               r"work: check the sky and the site\."),                # the site-wide footer (D52, D86(a))
    # the State Library's stated purpose, as its metadata gives it (D86(c); the site's B3 test exempts the same text)
    re.compile(re.escape(
        "To provide a statewide, standardized repository for structure and address point data. The "
        "Structures/Addresses Framework complies with the NENA Standard for NG9-1-1 GIS Data Model and is designed "
        "to support a wide range of public and private sector uses including: 9-1-1 and emergency response, "
        "elections management, broadband internet mapping, census programs, planning, natural resource studies, etc.")),
    # the NWS's own conditions, verbatim from weather.gov/disclaimer (D46, D86(c))
    re.compile(re.escape(
        "The information on National Weather Service (NWS) Web pages are in the public domain, unless specifically noted "
        "otherwise, and may be used without charge for any lawful purpose so long as you do not: 1) claim it is your own "
        "(e.g., by claiming copyright for NWS information -- see below), 2) use it in a manner that implies an endorsement "
        "or affiliation with NOAA/NWS, or 3) modify its content and then present it as official government material.")),
)


def residue(text: str) -> str:
    """The text with every allowed exemption removed: what the scan reads."""
    for pattern in EXEMPT:
        text = pattern.sub(" ", text)
    return text


def forbidden_words(text: str) -> list[str]:
    """The forbidden words in the text after the exemptions, lower case, sorted."""
    return sorted({match.group(0).lower() for match in FORBIDDEN.finditer(residue(text))})


def has_no_hail(text: str) -> bool:
    """True when "no hail" appears outside the one allowed sentence part."""
    return bool(NO_HAIL.search(residue(text)))


def assert_clean(test, text: str, where: str = "") -> None:
    """Fail the test with the words found when the text holds a forbidden word or a "no hail" that is not allowed."""
    found = forbidden_words(text)
    test.assertEqual(found, [], f"{where}: forbidden words {found} in {text!r}")
    test.assertFalse(has_no_hail(text), f"{where}: 'no hail' outside 'not the same as no hail' in {text!r}")
