"""Safe normalization helpers for matching human-entered identifiers."""

import re


def normalize_text(value: str | None) -> str:
    """Return a case-insensitive alphanumeric matching key."""

    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())
