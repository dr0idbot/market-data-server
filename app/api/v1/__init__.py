from fastapi import APIRouter

from app.api.v1 import bulk, health, tickers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tickers.router)
api_router.include_router(bulk.router)
