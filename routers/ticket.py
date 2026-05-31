from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from services.ticket_service import analyze_ticket_priority

router = APIRouter()


class TicketPriorityTextRequest(BaseModel):
    title: str
    description: str
    image_url: Optional[str] = None  # reserved, không dùng server-side fetch


@router.post("/analyze-priority")
async def analyze_priority_multipart(
    title: str = Form(...),
    description: str = Form(...),
    image: Optional[UploadFile] = File(default=None),
):
    """
    Phân tích mức độ ưu tiên sự cố từ tiêu đề, mô tả và ảnh (tuỳ chọn).
    Trả về: { priority: "low"|"medium"|"high", reason: "..." }
    """
    image_bytes: bytes | None = None
    image_mime: str | None = None

    if image is not None:
        image_bytes = await image.read()
        image_mime = image.content_type or "image/jpeg"

    result = analyze_ticket_priority(
        title=title,
        description=description,
        image_bytes=image_bytes,
        image_mime=image_mime,
    )

    if not result["success"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=result)

    return result
