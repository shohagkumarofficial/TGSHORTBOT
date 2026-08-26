"""
Telegram Mini App এর initData ভেরিফাই করার লজিক।

Telegram ডকুমেন্টেশন অনুযায়ী অ্যালগরিদম:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

1. initData কে query-string হিসেবে পার্স করা হয়
2. 'hash' ফিল্ড বাদ দিয়ে বাকি key=value গুলো key অনুযায়ী sort করে
   "\n" দিয়ে জোড়া দিয়ে data_check_string বানানো হয়
3. secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
4. computed_hash = HMAC_SHA256(key=secret_key, msg=data_check_string)
5. computed_hash == received hash হলে ডাটা authentic
"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_TELEGRAM_ID = os.environ.get("OWNER_TELEGRAM_ID", "")

# initData কতক্ষণ পুরনো হলে আর গ্রহণযোগ্য না (সেকেন্ডে) — 24 ঘন্টা
MAX_INIT_DATA_AGE = 86400


def validate_init_data(init_data, bot_token=None, max_age_seconds=MAX_INIT_DATA_AGE):
    """initData স্ট্রিং যাচাই করে Telegram user dict রিটার্ন করে, নাহলে None।"""
    bot_token = bot_token or BOT_TOKEN
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = pairs.get("auth_date")
    if auth_date and max_age_seconds:
        try:
            if time.time() - int(auth_date) > max_age_seconds:
                return None
        except ValueError:
            pass

    user_json = pairs.get("user")
    try:
        user = json.loads(user_json) if user_json else {}
    except json.JSONDecodeError:
        user = {}

    return user or None


def _extract_init_data(request):
    """Header, query string, form-data বা JSON body — যেখান থেকেই আসুক, initData খুঁজে বের করে।"""
    init_data = request.headers.get("X-Telegram-Init-Data")
    if init_data:
        return init_data

    init_data = request.GET.get("init_data")
    if init_data:
        return init_data

    if request.method == "POST":
        content_type = request.content_type or ""
        if "application/json" in content_type:
            try:
                body = json.loads(request.body or "{}")
                if body.get("init_data"):
                    return body["init_data"]
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        init_data = request.POST.get("init_data")
        if init_data:
            return init_data

    return None


def authenticate_request(request):
    """Django request থেকে verified Telegram user dict রিটার্ন করে, নাহলে None।"""
    init_data = _extract_init_data(request)
    if not init_data:
        return None
    return validate_init_data(init_data)


def is_owner(user):
    if not user or "id" not in user or not OWNER_TELEGRAM_ID:
        return False
    return str(user["id"]) == str(OWNER_TELEGRAM_ID)
