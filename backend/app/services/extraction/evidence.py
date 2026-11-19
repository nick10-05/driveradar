"""Evidence check: does the model's quote really appear in the notice? (DESIGN §4.5 step 1)

Interview notes:
- A cheap, deterministic hallucination guard. The model must back each key value with a
  verbatim quote; if the quote isn't in the notice, the value gets a "verify" flag.
- Matching ignores case, Unicode look-alikes (NFKC: full-width digits, ligatures) and
  whitespace differences (line breaks in emails), but nothing else: a paraphrase is not
  a quote.
- It proves the quote exists, not that the value follows from it. So for numbers we also
  check the value appears inside the quote (see normaliser). Anything that slips through
  still meets the human review step.
"""

import re
import unicodedata

_SPACES = re.compile(r"\s+")


def _canonical(text: str) -> str:
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def quote_in_text(quote: str, raw_text: str) -> bool:
    needle = _canonical(quote)
    return bool(needle) and needle in _canonical(raw_text)
