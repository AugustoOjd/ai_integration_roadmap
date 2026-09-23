"""How tool results become the string the model reads."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any


def _json_default(value: Any) -> str:
    # Decimal as a string, not a float: "38500.00" keeps the exact amount.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def to_json(payload: Any) -> str:
    # Tools return str on purpose. Returning the dict would make LangChain try
    # json.dumps, fail on Decimal/datetime, and silently fall back to str() —
    # the model would read Python reprs like `Decimal('38500.00')`.
    return json.dumps(payload, default=_json_default, ensure_ascii=False)
