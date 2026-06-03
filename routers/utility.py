from fastapi import APIRouter
from services.utility_service import analyze_utility, trigger_utility_ai_analysis

router = APIRouter()

@router.get("/analyze/{room_id}")
def analyze(room_id: str):
    return analyze_utility(room_id)

@router.post("/analyze/{room_id}/trigger")
def trigger_analysis(room_id: str):
    return trigger_utility_ai_analysis(room_id)