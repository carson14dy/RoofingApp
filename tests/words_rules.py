"""The forbidden words for the hail history's text: one list for every test module that scans words (F29, B5 D13).

The list is the research's own (research-b35/roof-indicators.json, measurements.forbidden_terms_added.words), written as
stems, plus the brief's D13 (nothing states damage, loss, a claim, coverage, insurance, eligibility, a probability, risk
or an all-clear) and the older test lists this list replaces (dry, clear, customers, guaranteed, approved, best, confirm).

A scan first removes what the brief allows, and nothing else: quoted wording (curly or straight quotation marks: a
remark, or a source's own words), the NWS damage threat tag label, the two required sentences "This is not an all-clear."
and "not the same as no hail", and the proper name that contains "structure" (USA Structures, the B3 attribution line).
It then fails any forbidden word left in the text, and any "no hail" left in it. "damage" is a forbidden stem, so a
source's type word that contains it has to be quoted, or be an abbreviation such as DMG, which the words never print
as a claim about this address.

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

# what the brief allows, and nothing else (each is removed before the scan)
EXEMPT = (
    re.compile(r"“[^”]*”"),        # quoted wording: a remark, or the source's own words
    re.compile(r'"[^"]*"'),                       # straight-quoted wording
    re.compile(r"NWS damage threat tag"),         # the label of the NWS's own product field (B2 D4)
    re.compile(r"This is not an all-clear\."),    # the required end of every stale or unavailable line
    re.compile(r"not the same as no hail"),       # the one allowed "no hail"
    re.compile(r"USA Structures"),                # a proper name (the B3 attribution line)
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
