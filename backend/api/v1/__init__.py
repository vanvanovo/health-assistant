# backend/api/v1/__init__.py
# /api/v1 总路由聚合。

from fastapi import APIRouter

from backend.api.v1 import auth, chat, checkins, dashboard, plans

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(dashboard.router)
api_router.include_router(plans.router)
api_router.include_router(checkins.router)
