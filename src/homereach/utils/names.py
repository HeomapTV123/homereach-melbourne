from __future__ import annotations

import re
import unicodedata

import pandas as pd


def normalise_name(value: object) -> str | None:
    """
    Create a conservative geographic-name key.

    The function removes punctuation and repeated spaces, but it does not
    guess that two different place names are equivalent. Use a reviewed
    crosswalk instead of an automatic fuzzy join for final geography.
    """
    if value is None or pd.isna(value):
        return None

    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper().strip()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
