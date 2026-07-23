"""Dutch text normalizer for WER/cpWER scoring. VERSIONED — see CLAUDE.md.

Applied to BOTH reference and hypothesis before scoring. Policy (v1):
  - unicode NFKC, lowercase
  - remove non-lexical tokens: xxx (unintelligible), g{3,} (IFADV laughter), and
    hesitation fillers {uh, uhm, eh, ehm, hm(m), mm(m)} — Whisper drops these
    inconsistently, so scoring them adds noise, not signal. "hè"/"hé" are kept (real words).
  - digits -> Dutch words via num2words (Whisper writes "27", IFADV writes "zevenentwintig");
    ordinals like "27e"/"3de"/"1ste" -> Dutch ordinal words
  - punctuation stripped; apostrophes INSIDE tokens kept ('k, d'r, z'n); hyphens -> space
  - whitespace collapsed

Never change behavior without bumping NORMALIZER_VERSION and re-running baselines.
"""
from __future__ import annotations

import re
import unicodedata

from num2words import num2words

NORMALIZER_VERSION = "1"

_FILLERS = {"uh", "uhm", "eh", "ehm", "hm", "hmm", "mm", "mmm", "xxx"}
_CLITICS = {"k", "t", "n", "s", "m", "r", "ie"}
_LAUGH = re.compile(r"^g{3,}$")
_ORDINAL = re.compile(r"^(\d+)(?:e|de|ste)$")
_INT = re.compile(r"^\d+$")
# strip everything except letters, digits, apostrophe; hyphen handled before tokenizing
_PUNCT = re.compile(r"[^\w']", flags=re.UNICODE)


def _num_to_dutch(token: str) -> str:
    m = _ORDINAL.match(token)
    try:
        if m:
            return num2words(int(m.group(1)), lang="nl", to="ordinal")
        if _INT.match(token):
            return num2words(int(token), lang="nl")
    except (ValueError, OverflowError, NotImplementedError):
        pass
    return token


def normalize_dutch(text: str) -> str:
    """Return the normalized form of `text` for scoring."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("-", " ").replace("/", " ")
    out = []
    for raw in text.split():
        tok = _PUNCT.sub("", raw).strip("_").rstrip("'")
        # keep the leading apostrophe of Dutch clitics ('k, 't, 's, 'n, 'm, 'r, 'ie),
        # strip it when it's a quote mark
        if tok.startswith("'") and tok[1:] not in _CLITICS:
            tok = tok.lstrip("'")
        if not tok:
            continue
        tok = _num_to_dutch(tok)
        if tok in _FILLERS or _LAUGH.match(tok):
            continue
        out.append(tok)
    return " ".join(out)
