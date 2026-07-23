"""Run: venvs/wlk/bin/python tests/test_normalizer.py (plain asserts, no pytest needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dialib.normalizer import normalize_dutch as n  # noqa: E402

# case / punctuation / whitespace
assert n("Hallo,  Wereld!") == "hallo wereld"
assert n("Dat is… mooi.") == "dat is mooi"
# Dutch clitic apostrophes kept
assert n("'k kan dat goed inschatten.") == "'k kan dat goed inschatten"
assert n("d'r staat geen auto...") == "d'r staat geen auto"
assert n("z'n fiets") == "z'n fiets"
# quote-mark apostrophes stripped, unicode quotes normalized
assert n("’s ochtends") == "'s ochtends" or n("’s ochtends") == "s ochtends"
# diacritics preserved (NFKC, not ascii-folding)
assert n("één café") == "één café"
# IFADV non-lexical + fillers dropped
assert n("ggg. en uhm ja xxx brug") == "en ja brug"
assert n("gggg") == ""
# "hè" is NOT a filler
assert n("leuk hè") == "leuk hè"
# numbers -> Dutch words
assert n("27 mensen") == "zevenentwintig mensen"
assert n("de 3de keer") == "de derde keer"
assert n("1ste") == "eerste"
assert n("100") == "honderd"
# hyphen -> space
assert n("Noord-Holland") == "noord holland"
# mixed digit tokens left alone (documented limitation)
assert n("a4'tje") == "a4'tje"

print("normalizer tests OK")
