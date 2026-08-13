import json
import os
import threading
from typing import List, Optional, Dict
from datetime import datetime, timezone
from uuid import UUID

from pydantic import TypeAdapter

from models import Admin, Link, View, CPMSetting, WithdrawRequest, CPMAuditLog

STORE_PATH = os.path.join(os.path.dirname(__file__), "data", "store.json")

class Storage:
    """Thread-safe JSON file storage for the bot."""
    def __init__(self, store_path: str = STORE_PATH):
        self.store_path = store_path
        self._lock = threading.Lock()
        self._ensure_store_exists()

    def _ensure_store_exists(self):
        """Creates the data folder and store.json with default structure if not exist."""
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        if not os.path.exists(self.store_path):
            initial_data = {
                "admins": {},
                "links": {},
                "views": [],
                "cpm_setting": None,
                "withdraw_requests": [],
                "cpm_audit_log": []
            }
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(initial_data, f)

    def _load(self) -> dict:
        """Loads data from JSON file."""
        with open(self.store_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict):
        """Saves data to JSON file."""
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str, indent=2)

    # --- Admin Methods ---
    def get_admin(self, telegram_id: int) -> Optional[Admin]:
        with self._lock:
            data = self._load()
            admin_data = data["admins"].get(str(telegram_id))
            if admin_data:
                return Admin.model_validate(admin_data)
            return None

    def upsert_admin(self, admin: Admin):
        with self._lock:
            data = self._load()
            data["admins"][str(admin.telegram_id)] = admin.model_dump(mode="json")
            self._save(data)

    def get_all_admins(self) -> List[Admin]:
        with self._lock:
            data = self._load()
            return [Admin.model_validate(a) for a in data["admins"].values()]

    def ban_admin(self, telegram_id: int):
        with self._lock:
            data = self._load()
            if str(telegram_id) in data["admins"]:
                data["admins"][str(telegram_id)]["status"] = "banned"
                self._save(data)

    def unban_admin(self, telegram_id: int):
        with self._lock:
            data = self._load()
            if str(telegram_id) in data["admins"]:
                data["admins"][str(telegram_id)]["status"] = "active"
                self._save(data)

    # --- Link Methods ---
    def create_link(self, link: Link):
        with self._lock:
            data = self._load()
            data["links"][link.short_code] = link.model_dump(mode="json")
            self._save(data)

    def get_link(self, short_code: str) -> Optional[Link]:
        with self._lock:
            data = self._load()
            link_data = data["links"].get(short_code)
            if link_data:
                return Link.model_validate(link_data)
            return None

    def get_links_by_admin(self, telegram_id: int) -> List[Link]:
        with self._lock:
            data = self._load()
            return [Link.model_validate(l) for l in data["links"].values() if l["owner_telegram_id"] == telegram_id]

    def get_all_links(self) -> List[Link]:
        with self._lock:
            data = self._load()
            return [Link.model_validate(l) for l in data["links"].values()]

    def get_pending_links(self) -> List[Link]:
        with self._lock:
            data = self._load()
            return [Link.model_validate(l) for l in data["links"].values() if l["verification_status"] == "pending"]

    def update_link_proof(self, short_code: str, proof_url: str):
        with self._lock:
            data = self._load()
            if short_code in data["links"]:
                data["links"][short_code]["proof_url"] = proof_url
                self._save(data)

    def verify_link(self, short_code: str, status: str):
        with self._lock:
            data = self._load()
            if short_code in data["links"]:
                data["links"][short_code]["verification_status"] = status
                self._save(data)

    # --- View Methods ---
    def log_view(self, view: View):
        with self._lock:
            data = self._load()
            data["views"].append(view.model_dump(mode="json"))
            self._save(data)

    def is_duplicate_view(self, short_code: str, viewer_telegram_id: int) -> bool:
        with self._lock:
            data = self._load()
            for v in data["views"]:
                if v["short_code"] == short_code and v["viewer_telegram_id"] == viewer_telegram_id:
                    return True
            return False

    def get_views_by_link(self, short_code: str) -> List[View]:
        with self._lock:
            data = self._load()
            return [View.model_validate(v) for v in data["views"] if v["short_code"] == short_code]

    def get_views_by_status(self, status: str) -> List[View]:
        with self._lock:
            data = self._load()
            return [View.model_validate(v) for v in data["views"] if v["counted_status"] == status]

    def update_view_status(self, view_id: UUID, status: str, earned_amount: Optional[float] = None):
        with self._lock:
            data = self._load()
            view_id_str = str(view_id)
            for v in data["views"]:
                if v["view_id"] == view_id_str:
                    v["counted_status"] = status
                    if earned_amount is not None:
                        v["earned_amount"] = earned_amount
                    break
            self._save(data)

    def get_pending_payout_views(self, cycle_id: str) -> List[View]:
        with self._lock:
            data = self._load()
            return [View.model_validate(v) for v in data["views"] if v["counted_status"] == "pending_payout" and v.get("cpm_cycle_id") == cycle_id]

    def count_views_by_link(self, short_code: str) -> int:
        with self._lock:
            data = self._load()
            return sum(1 for v in data["views"] if v["short_code"] == short_code)

    # --- CPM Setting Methods ---
    def get_cpm_setting(self) -> Optional[CPMSetting]:
        with self._lock:
            data = self._load()
            if data["cpm_setting"]:
                return CPMSetting.model_validate(data["cpm_setting"])
            return None

    def update_cpm_setting(self, setting: CPMSetting):
        with self._lock:
            data = self._load()
            data["cpm_setting"] = setting.model_dump(mode="json")
            self._save(data)

    def init_cpm_setting(self, owner_id: int):
        with self._lock:
            data = self._load()
            if not data["cpm_setting"]:
                setting = CPMSetting(updated_by=owner_id)
                data["cpm_setting"] = setting.model_dump(mode="json")
                self._save(data)

    # --- Withdrawal Methods ---
    def create_withdraw_request(self, request: WithdrawRequest):
        with self._lock:
            data = self._load()
            data["withdraw_requests"].append(request.model_dump(mode="json"))
            self._save(data)

    def get_pending_withdrawals(self) -> List[WithdrawRequest]:
        with self._lock:
            data = self._load()
            return [WithdrawRequest.model_validate(r) for r in data["withdraw_requests"] if r["status"] == "pending"]

    def get_withdrawals_by_admin(self, telegram_id: int) -> List[WithdrawRequest]:
        with self._lock:
            data = self._load()
            return [WithdrawRequest.model_validate(r) for r in data["withdraw_requests"] if r["admin_telegram_id"] == telegram_id]

    def resolve_withdrawal(self, request_id: UUID, status: str, reason: Optional[str] = None):
        with self._lock:
            data = self._load()
            req_id_str = str(request_id)
            for r in data["withdraw_requests"]:
                if r["request_id"] == req_id_str:
                    r["status"] = status
                    r["resolved_at"] = datetime.now(timezone.utc).isoformat()
                    if reason:
                        r["reject_reason"] = reason
                    break
            self._save(data)

    # --- Audit Log Methods ---
    def add_audit_log(self, log_entry: CPMAuditLog):
        with self._lock:
            data = self._load()
            data["cpm_audit_log"].append(log_entry.model_dump(mode="json"))
            self._save(data)

    # --- Balance Management ---
    def credit_admin_balance(self, telegram_id: int, amount: float, balance_type: str):
        with self._lock:
            data = self._load()
            tid_str = str(telegram_id)
            if tid_str in data["admins"]:
                if balance_type == 'confirmed':
                    data["admins"][tid_str]["balance_confirmed"] += amount
                elif balance_type == 'pending':
                    data["admins"][tid_str]["balance_pending"] += amount
                self._save(data)

    def move_pending_to_confirmed(self, telegram_id: int):
        with self._lock:
            data = self._load()
            tid_str = str(telegram_id)
            if tid_str in data["admins"]:
                pending_amt = data["admins"][tid_str]["balance_pending"]
                data["admins"][tid_str]["balance_confirmed"] += pending_amt
                data["admins"][tid_str]["balance_pending"] = 0.0
                self._save(data)

    def debit_admin_balance(self, telegram_id: int, amount: float):
        with self._lock:
            data = self._load()
            tid_str = str(telegram_id)
            if tid_str in data["admins"]:
                data["admins"][tid_str]["balance_confirmed"] -= amount
                self._save(data)

    def get_analytics_data(self, telegram_id: int, period: str = "24h", start_date_str: Optional[str] = None, end_date_str: Optional[str] = None) -> dict:
        with self._lock:
            data = self._load()
            user_links = {l["short_code"] for l in data["links"].values() if l["owner_telegram_id"] == telegram_id}
            user_views = [v for v in data["views"] if v["short_code"] in user_links]
            user_withdrawals = [w for w in data["withdraw_requests"] if w["admin_telegram_id"] == telegram_id]
            
            total_withdrawn = sum(w["amount"] for w in user_withdrawals if w["status"] == "paid")
            
            now = datetime.now(timezone.utc)
            filtered_views = []
            
            for v in user_views:
                v_time_str = v.get("created_at")
                if not v_time_str:
                    continue
                try:
                    v_time = datetime.fromisoformat(str(v_time_str).replace("Z", "+00:00"))
                    if v_time.tzinfo is None:
                        v_time = v_time.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                if period == "24h":
                    if (now - v_time).total_seconds() <= 86400:
                        filtered_views.append((v, v_time))
                elif period == "7d":
                    if (now - v_time).total_seconds() <= 7 * 86400:
                        filtered_views.append((v, v_time))
                elif period == "30d":
                    if (now - v_time).total_seconds() <= 30 * 86400:
                        filtered_views.append((v, v_time))
                elif period == "custom" and start_date_str and end_date_str:
                    try:
                        s_dt = datetime.fromisoformat(start_date_str).replace(tzinfo=timezone.utc)
                        e_dt = datetime.fromisoformat(end_date_str).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                        if s_dt <= v_time <= e_dt:
                            filtered_views.append((v, v_time))
                    except Exception:
                        pass
                else:
                    filtered_views.append((v, v_time))

            daily_dict = {}
            total_period_earned = 0.0
            for v, v_time in filtered_views:
                day_key = v_time.strftime("%Y-%m-%d")
                earned = v.get("earned_amount", 0.0)
                total_period_earned += earned
                
                if day_key not in daily_dict:
                    daily_dict[day_key] = {"date": day_key, "views": 0, "earned": earned}
                else:
                    daily_dict[day_key]["views"] += 1
                    daily_dict[day_key]["earned"] += earned

            daily_breakdown = sorted(daily_dict.values(), key=lambda x: x["date"], reverse=True)
            
            return {
                "period": period,
                "period_views": len(filtered_views),
                "period_earnings": total_period_earned,
                "total_withdrawn": total_withdrawn,
                "daily_breakdown": daily_breakdown
            }
