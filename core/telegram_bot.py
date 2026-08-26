"""
Telegram Bot API কল — মূলত channel/group membership যাচাই করার জন্য।

⚠️ শর্ত: বটকে অবশ্যই সংশ্লিষ্ট চ্যানেল/গ্রুপে admin হিসেবে যোগ করতে হবে,
নাহলে getChatMember কল সঠিক status রিটার্ন করবে না।
"""

import json
import os

import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Render নিজে থেকেই RENDER_EXTERNAL_URL সেট করে দেয়; না থাকলে MINI_APP_URL ফলব্যাক
MINI_APP_URL = os.environ.get("MINI_APP_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")

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


def send_start_message(chat_id, first_name="", timeout=8):
    """/start কমান্ডের রিপ্লাই — স্বাগত বার্তা + Mini App খোলার বাটন।"""
    if not BOT_TOKEN:
        return False

    greeting = f"👋 স্বাগতম{', ' + first_name if first_name else ''}!"
    text = (
        f"{greeting}\n\n"
        "🎯 <b>TGSHORT Tasks</b> এ আপনি যা করতে পারবেন:\n"
        "• ছোট ছোট টাস্ক শেষ করে কয়েন ইনকাম\n"
        "• অ্যাড দেখে প্রতিদিন ফ্রি কয়েন\n"
        "• রোজ চেক-ইন করে বোনাস স্ট্রিক রিওয়ার্ড\n"
        "• জমানো কয়েন bKash/Nagad এ উইথড্র\n\n"
        "নিচের বাটনে ট্যাপ করে শুরু করুন 👇"
    )
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if MINI_APP_URL:
        payload["reply_markup"] = json.dumps(
            {
                "inline_keyboard": [
                    [{"text": "🚀 অ্যাপ খুলুন", "web_app": {"url": MINI_APP_URL}}]
                ]
            }
        )
    try:
        resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=timeout)
        return resp.json().get("ok", False)
    except requests.RequestException:
        return False
