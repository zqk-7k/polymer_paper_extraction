"""Conservative presentation normalization for polymer sample labels."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


def normalize_sample_label(value: Any) -> str:
    """Remove proven markup while retaining token-separating whitespace.

    Subscripts are attached to the preceding token because that whitespace is
    introduced by HTML/TeX presentation.  Other internal whitespace is kept,
    so composition labels such as ``C4 25%`` and ``C42 5%`` cannot collapse to
    the same key.
    """

    text = unicodedata.normalize("NFKC", html.unescape(str(value or "")))
    text = text.replace("$", "").replace("\\(", "").replace("\\)", "")
    text = re.sub(
        r"\s*<\s*sub\s*>(.*?)<\s*/\s*sub\s*>",
        lambda match: match.group(1),
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"\s*<\s*sup\s*>(.*?)<\s*/\s*sup\s*>",
        lambda match: f"⟦sup:{match.group(1)}⟧",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s*_\s*\{([^{}]*)\}", lambda match: match.group(1), text)
    text = re.sub(r"\s*_\s*([A-Za-z0-9])", r"\1", text)
    text = re.sub(
        r"\s*\^\s*\{([^{}]*)\}",
        lambda match: f"⟦sup:{match.group(1)}⟧",
        text,
    )
    style = re.compile(r"\\(?:mathrm|text|mathbf|mathit|operatorname)\s*\{([^{}]*)\}")
    while style.search(text):
        text = style.sub(r"\1", text)
    text = re.sub(r"\s*_\s*\{([^{}]*)\}", lambda match: match.group(1), text)
    text = re.sub(r"\s*_\s*([A-Za-z0-9])", r"\1", text)
    text = re.sub(
        r"\s*\^\s*\{([^{}]*)\}",
        lambda match: f"⟦sup:{match.group(1)}⟧",
        text,
    )
    text = text.replace("{", "").replace("}", "")
    text = text.translate(
        str.maketrans({
            "‐": "-",
            "‑": "-",
            "‒": "-",
            "–": "-",
            "—": "-",
            "−": "-",
        })
    )
    text = re.sub(r"\s*([-/*(),|])\s*", r"\1", text)
    text = re.sub(r"\s*%\s*", "%", text)
    return re.sub(r"\s+", " ", text.casefold()).strip()
