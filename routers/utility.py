from fastapi import APIRouter
from services.utility_service import analyze_utility

router = APIRouter()

@router.get("/analyze/{room_id}")
def analyze(room_id: str):
    return analyze_utility(room_id)