"""Validates Telegram Mini App `initData` per Telegram's documented HMAC
scheme: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Every Mini App API call must go through this before trusting the caller's
Telegram identity — the PRD's security note in Section 9.4 is treated as
a hard requirement here, not a suggestion.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict:
    """Returns {"raw": {...}, "user": {...}} on success.

    Raises InitDataError if the signature is missing, invalid, or stale.
    """
    if not init_data:
        raise InitDataError("empty init data")

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as e:
        raise InitDataError(f"malformed init data: {e}") from e

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise InitDataError("missing hash field")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise InitDataError("signature mismatch")

    auth_date_raw = parsed.get("auth_date")
    if max_age_seconds and auth_date_raw:
        try:
            auth_date = int(auth_date_raw)
        except ValueError:
            raise InitDataError("invalid auth_date")
        if time.time() - auth_date > max_age_seconds:
            raise InitDataError("init data expired")

    user: Optional[dict] = None
    if "user" in parsed:
        try:
            user = json.loads(parsed["user"])
        except json.JSONDecodeError as e:
            raise InitDataError(f"invalid user field: {e}") from e

    return {"raw": parsed, "user": user}
