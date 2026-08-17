"""Shared input validators.

Kept as a standalone module (rather than duplicated inline in app.py and
bot.py) so the bot's conversational flow and the panel's API enforce the
*exact* same rule for what counts as a real bKash/Nagad account number —
previously the withdrawal form accepted any non-empty text in the account
number field.

bKash and Nagad personal accounts in Bangladesh are both just an 11-digit
mobile number: `01` followed by an operator digit (3-9) and 8 more
digits, e.g. 017XXXXXXXX / 013XXXXXXXX / ... / 019XXXXXXXX. That's the
only shape this module checks for — it does not (and can't) confirm the
number is actually registered with bKash/Nagad or reachable.
"""
from __future__ import annotations

import re
from typing import Optional

BD_MOBILE_RE = re.compile(r"^01[3-9]\d{8}$")


def normalize_bd_mobile_number(raw: str) -> str:
    """Strips spaces/dashes and collapses a leading +880/880 country code
    down to the local 0-prefixed form. Does not validate the result —
    call is_valid_bd_mobile_number (or bd_mobile_validation_error) on the
    output before trusting it.
    """
    s = re.sub(r"[\s\-]", "", raw or "")
    if s.startswith("+880"):
        s = "0" + s[4:]
    elif s.startswith("880") and len(s) == 13:
        s = "0" + s[3:]
    return s


def is_valid_bd_mobile_number(raw: str) -> bool:
    """True if `raw` normalizes to exactly 11 digits starting 013-019."""
    return bool(BD_MOBILE_RE.match(normalize_bd_mobile_number(raw)))


def bd_mobile_validation_error(raw: str) -> Optional[str]:
    """Returns a human-readable (Bengali) error string if `raw` is not a
    valid bKash/Nagad number, or None if it's valid. Centralizing the
    message text here keeps the bot and the panel API in sync.
    """
    s = normalize_bd_mobile_number(raw)
    if not s:
        return "অ্যাকাউন্ট নম্বর দিতে হবে।"
    if not s.isdigit():
        return "অ্যাকাউন্ট নম্বরে শুধু সংখ্যা থাকতে হবে (যেমন: 017XXXXXXXX)।"
    if len(s) != 11:
        return f"বিকাশ/নগদ নম্বর অবশ্যই ১১ ডিজিটের হতে হবে (দিয়েছেন {len(s)} ডিজিট)।"
    if not s.startswith("01") or s[2] not in "3456789":
        return "সঠিক বিকাশ/নগদ নম্বর দিন — 013, 014, 015, 016, 017, 018 অথবা 019 দিয়ে শুরু হতে হবে।"
    return None
