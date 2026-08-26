"""
TGSHORT Tasks — Django settings.

গুরুত্বপূর্ণ: এই প্রজেক্টে কোনো ডাটাবেজ ব্যবহার করা হয়নি।
সব ডাটা (users/tasks/withdrawals) RAM-এ থাকে — দেখুন core/store.py।
তাই django.contrib.auth, sessions, admin, contenttypes — এগুলো
INSTALLED_APPS এ রাখা হয়নি (এগুলো DB টেবিল আশা করে)।
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-insecure-secret-key-please-change-me"
)

DEBUG = os.environ.get("DEBUG", "False") == "True"

_hosts = os.environ.get("ALLOWED_HOSTS", "*")
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "core",
    "adminpanel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "tgshort_tasks.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "tgshort_tasks.wsgi.application"

# কোনো ডাটাবেজ নেই — ইচ্ছাকৃতভাবে খালি রাখা হয়েছে
DATABASES = {}

LANGUAGE_CODE = "bn"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- অ্যাপ-স্পেসিফিক এনভায়রনমেন্ট ভ্যারিয়েবল (docs হিসেবে এখানে তালিকাভুক্ত) ---
# BOT_TOKEN            -> Telegram বট টোকেন (@BotFather)
# OWNER_TELEGRAM_ID    -> শুধু এই telegram id অ্যাডমিন প্যানেল দেখতে পারবে
# MONETAG_ZONE_ID      -> Monetag SDK zone id
# GIGAPUB_PROJECT_ID   -> GigaPub project id
