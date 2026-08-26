from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import datetime
import config
import database
from api.auth import validate_telegram_init_data

router = APIRouter(prefix="/api")

class GameStartRequest(BaseModel):
    game_id: str

class GameEndRequest(BaseModel):
    game_id: str
    score: int = 0
    result: str = "completed"  # 'won', 'lost', 'game_over', 'completed'

class AdRewardRequest(BaseModel):
    network: str = "adsgram"  # 'adsgram', 'monetag', 'gigapub', 'adsterra'

def get_authenticated_user(request: Request, x_telegram_init_data: Optional[str] = None) -> Dict[str, Any]:
    init_data = x_telegram_init_data or request.query_params.get("initData") or ""
    
    if init_data:
        user = validate_telegram_init_data(init_data)
        if user and "id" in user:
            return user

    # Fallback for browser preview / local dev testing
    dev_user_id = request.query_params.get("dev_user_id")
    if dev_user_id:
        try:
            uid = int(dev_user_id)
            return {"id": uid, "first_name": f"Tester_{uid}", "username": f"tester_{uid}"}
        except ValueError:
            pass

    if not config.BOT_TOKEN or config.HOST == "127.0.0.1":
        return {"id": 99999999, "first_name": "Demo Player", "username": "demo_player"}

    raise HTTPException(status_code=401, detail="Unauthorized Telegram WebApp data")

@router.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}

@router.get("/user/info")
async def get_user_info(
    request: Request,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data")
):
    user_data = get_authenticated_user(request, x_telegram_init_data)
    telegram_id = int(user_data["id"])
    first_name = user_data.get("first_name", "")
    last_name = user_data.get("last_name", "")
    username = user_data.get("username", "")

    user = await database.get_or_create_user(telegram_id, first_name, last_name, username)
    high_scores = await database.get_user_high_scores(telegram_id)
    settings = await database.get_all_settings()

    # Build active 9 games list
    games = []
    for g in config.DEFAULT_GAMES:
        game_key = f"game_{g['id']}"
        is_enabled = settings.get(game_key, "1") == "1"
        games.append({
            "id": g["id"],
            "name": g["name"],
            "enabled": is_enabled,
            "high_score": high_scores.get(g["id"], 0)
        })

    return {
        "success": True,
        "user": user,
        "high_scores": high_scores,
        "games": games,
        "settings": {
            "life_deduct_mode": settings.get("life_deduct_mode", "on_loss"),
            "ad_selection_mode": settings.get("ad_selection_mode", "round_robin"),
            "selected_ad_network": settings.get("selected_ad_network", "adsgram"),
            "adsgram_enabled": settings.get("adsgram_enabled", "1"),
            "adsgram_block_id": settings.get("adsgram_block_id", config.ADSGRAM_BLOCK_ID),
            "monetag_enabled": settings.get("monetag_enabled", "1"),
            "monetag_zone_id": settings.get("monetag_zone_id", config.MONETAG_ZONE_ID),
            "gigapub_enabled": settings.get("gigapub_enabled", "0"),
            "gigapub_project_id": settings.get("gigapub_project_id", config.GIGAPUB_PROJECT_ID),
            "adsterra_enabled": settings.get("adsterra_enabled", "0"),
            "adsterra_key": settings.get("adsterra_key", config.ADSTERRA_KEY),
            "ad_cooldown_seconds": int(settings.get("ad_cooldown_seconds", "20")),
            "regen_interval_minutes": int(settings.get("regen_interval_minutes", "30")),
            "max_free_lives": int(settings.get("max_free_lives", "3"))
        }
    }

@router.post("/game/start")
async def start_game(
    payload: GameStartRequest,
    request: Request,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data")
):
    user_data = get_authenticated_user(request, x_telegram_init_data)
    telegram_id = int(user_data["id"])
    
    settings = await database.get_all_settings()
    game_key = f"game_{payload.game_id}"
    if settings.get(game_key, "1") != "1":
        return {"success": False, "error": "game_disabled", "message": "This game is currently disabled by administrator."}

    user = await database.get_or_create_user(telegram_id, user_data.get("first_name", ""), user_data.get("last_name", ""), user_data.get("username", ""))
    
    if user["lives"] <= 0:
        return {
            "success": False,
            "error": "no_lives",
            "message": "Out of lives! Watch a short ad to get +1 life ❤️.",
            "lives": 0,
            "seconds_until_regen": user["seconds_until_regen"]
        }

    life_deduct_mode = settings.get("life_deduct_mode", "on_loss")
    remaining_lives = user["lives"]

    if life_deduct_mode == "on_start":
        success, remaining_lives = await database.deduct_life(telegram_id)
        if not success:
            return {"success": False, "error": "no_lives", "message": "Failed to deduct life."}

    return {
        "success": True,
        "lives": remaining_lives,
        "life_deduct_mode": life_deduct_mode,
        "seconds_until_regen": user["seconds_until_regen"]
    }

@router.post("/game/end")
async def end_game(
    payload: GameEndRequest,
    request: Request,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data")
):
    user_data = get_authenticated_user(request, x_telegram_init_data)
    telegram_id = int(user_data["id"])

    await database.record_game_session(telegram_id, payload.game_id, payload.score, payload.result)

    settings = await database.get_all_settings()
    life_deduct_mode = settings.get("life_deduct_mode", "on_loss")

    if life_deduct_mode == "on_loss" and payload.result in ["lost", "game_over"]:
        await database.deduct_life(telegram_id)

    user = await database.get_or_create_user(telegram_id, user_data.get("first_name", ""), user_data.get("last_name", ""), user_data.get("username", ""))
    high_scores = await database.get_user_high_scores(telegram_id)

    return {
        "success": True,
        "lives": user["lives"],
        "max_free_lives": user["max_free_lives"],
        "seconds_until_regen": user["seconds_until_regen"],
        "high_score": high_scores.get(payload.game_id, payload.score)
    }

@router.post("/ad/reward")
async def claim_ad_reward(
    payload: AdRewardRequest,
    request: Request,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data")
):
    user_data = get_authenticated_user(request, x_telegram_init_data)
    telegram_id = int(user_data["id"])

    can_claim, reason, cooldown_remaining = await database.can_claim_ad_reward(telegram_id)
    if not can_claim:
        return {
            "success": False,
            "message": reason,
            "cooldown_remaining": cooldown_remaining
        }

    # Grant unlimited stacked life
    success, new_lives = await database.add_life(telegram_id, 1)
    if not success:
        return {"success": False, "message": "Could not add life."}

    await database.record_ad_view(telegram_id, payload.network)
    user = await database.get_or_create_user(telegram_id, user_data.get("first_name", ""), user_data.get("last_name", ""), user_data.get("username", ""))

    return {
        "success": True,
        "message": f"🎉 +1 Life Added via {payload.network.upper()}! (Total: {new_lives} ❤️)",
        "lives": user["lives"],
        "max_free_lives": user["max_free_lives"],
        "seconds_until_regen": user["seconds_until_regen"]
    }

@router.get("/leaderboard")
async def get_leaderboard_route(game_id: Optional[str] = "all"):
    leaderboard = await database.get_leaderboard(game_id, limit=15)
    return {"success": True, "game_id": game_id, "leaderboard": leaderboard}
