"""Helpers for trustworthy human-correction audit records.

The browser may send the value it displayed before an edit, but the server's
stored extraction is the source of truth for training data.  These helpers
keep the persisted prediction/correction pair consistent across the document
and AP correction endpoints and exports.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def audit_value(value: Any) -> str | None:
    """Serialize a stored field value without losing numeric meaning."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def training_value(value: str | None) -> Any:
    """Recover JSON scalar values for correction-training exports.

    Dates and free-form text remain strings; numeric strings such as ``15800``
    become numbers so downstream evaluation can compare them numerically.
    """

    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
