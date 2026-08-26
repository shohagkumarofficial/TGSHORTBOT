from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # প্রসেস স্টার্ট হওয়ার সময় স্টোর খালি থাকলে একটা ডিফল্ট ডেইলি টাস্ক বসিয়ে দেয়
        from . import store
        store.seed_default_tasks()
