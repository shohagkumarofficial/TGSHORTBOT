import hmac
import hashlib
import json
import urllib.parse
from typing import Optional, Dict, Any
import config

def validate_telegram_init_data(init_data: str) -> Optional[Dict[str, Any]]:
    """
    Validates Telegram WebApp initData string using HMAC-SHA256 according to Telegram specifications.
    Returns parsed user dict if valid, None otherwise.
    """
    if not init_data:
        return None

    # For development/testing without bot token
    if not config.BOT_TOKEN:
        try:
            parsed = dict(urllib.parse.parse_qsl(init_data))
            if "user" in parsed:
                return json.loads(parsed["user"])
        except Exception:
            return None

    try:
        parsed = dict(urllib.parse.parse_qsl(init_data))
        if "hash" not in parsed:
            return None

        received_hash = parsed.pop("hash")
        
        # Sort key-value pairs alphabetically
        sorted_items = sorted(parsed.items())
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted_items])

        # Step 1: secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
        secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()

        # Step 2: computed_hash = HMAC_SHA256(key=secret_key, msg=data_check_string)
        computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if hmac.compare_digest(computed_hash, received_hash):
            if "user" in parsed:
                return json.loads(parsed["user"])
            return {}
        return None
    except Exception as e:
        print(f"Error validating initData: {e}")
        return None
