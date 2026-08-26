"""
Telegram Bot API কল — মূলত channel/group membership যাচাই করার জন্য।

⚠️ শর্ত: বটকে অবশ্যই সংশ্লিষ্ট চ্যানেল/গ্রুপে admin হিসেবে যোগ করতে হবে,
নাহলে getChatMember কল সঠিক status রিটার্ন করবে না।
"""

import os

import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

_VALID_MEMBER_STATUSES = {"member", "administrator", "creator"}


def check_channel_membership(chat_id, user_id, timeout=8):
    """chat_id (যেমন '@mychannel' বা -1001234567890) তে user_id মেম্বার কিনা চেক করে।"""
    if not BOT_TOKEN or not chat_id:
        return False
    try:
        resp = requests.get(
            f"{API_BASE}/getChatMember",
            params={"chat_id": chat_id, "user_id": user_id},
            timeout=timeout,
        )
        data = resp.json()
        if not data.get("ok"):
            return False
        status = data.get("result", {}).get("status")
        return status in _VALID_MEMBER_STATUSES
    except requests.RequestException:
        return False


def send_message(chat_id, text, timeout=8):
    """সাধারণ মেসেজ পাঠানোর হেল্পার (যেমন withdraw approve হলে ইউজারকে নোটিফাই করতে)।"""
    if not BOT_TOKEN:
        return False
    try:
        resp = requests.post(
            f"{API_BASE}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=timeout,
        )
        return resp.json().get("ok", False)
    except requests.RequestException:
        return False
