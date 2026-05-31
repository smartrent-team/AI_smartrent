from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from services.cccd_service import scan_cccd_from_base64, scan_cccd_from_bytes

router = APIRouter()


class CccdScanBase64Request(BaseModel):
    image_base64: str = Field(..., description="Ảnh CCCD encode base64 (có hoặc không prefix data:image/...)")
    mime_type: Optional[str] = Field(
        default=None,
        description="image/jpeg | image/png | image/webp",
    )


@router.post("/scan")
async def scan_cccd_upload(file: UploadFile = File(..., description="Ảnh mặt trước CCCD/CMND")):
    """
    Quét ảnh CCCD (multipart): trả họ tên và số CCCD/CMND.
    """
    content_type = (file.content_type or "").lower()
    image_bytes = await file.read()
    result = scan_cccd_from_bytes(image_bytes, content_type or None)

    if not result["success"]:
        raise HTTPException(status_code=422, detail=result)

    return result


@router.post("/scan-base64")
def scan_cccd_json(body: CccdScanBase64Request):
    """
    Quét ảnh CCCD (JSON base64): tiện cho mobile gửi ảnh đã encode.
    """
    result = scan_cccd_from_base64(body.image_base64, body.mime_type)

    if not result["success"]:
        raise HTTPException(status_code=422, detail=result)

    return result
