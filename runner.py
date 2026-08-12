"""ASGI entry point for Render.

Render runs `uvicorn runner:app --host 0.0.0.0 --port $PORT`.
"""
from app import app  # noqa: F401
