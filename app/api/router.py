from fastapi import APIRouter

from app.api.v1 import areas, auth, reservations, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(areas.router)
api_router.include_router(reservations.router)