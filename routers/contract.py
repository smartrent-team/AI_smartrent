from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from services.contract_service import (
    scan_contract_expiry_from_batch,
    scan_contract_expiry_from_base64,
    scan_contract_expiry_from_bytes,
)

router = APIRouter()


class ContractScanBase64Request(BaseModel):
    image_base64: str = Field(..., description="Ảnh hợp đồng encode base64")
    mime_type: Optional[str] = Field(
        default=None,
        description="image/jpeg | image/png | image/webp",
    )


class ContractScanBatchRequest(BaseModel):
    images_base64: list[str] = Field(..., description="Danh sách ảnh hợp đồng encode base64")
    mime_types: Optional[list[str]] = Field(
        default=None,
        description="Danh sách mime types tương ứng",
    )


@router.post("/scan-expiry")
async def scan_contract_expiry_upload(
    file: UploadFile = File(..., description="Ảnh hợp đồng giấy"),
):
    content_type = (file.content_type or "").lower()
    image_bytes = await file.read()
    result = scan_contract_expiry_from_bytes(image_bytes, content_type or None)

    if not result["success"]:
        status_code = 503 if result.get("retryable") else 422
        raise HTTPException(status_code=status_code, detail=result)

    return result


@router.post("/scan-expiry-base64")
def scan_contract_expiry_json(body: ContractScanBase64Request):
    result = scan_contract_expiry_from_base64(body.image_base64, body.mime_type)

    if not result["success"]:
        status_code = 503 if result.get("retryable") else 422
        raise HTTPException(status_code=status_code, detail=result)

    return result


@router.post("/scan-expiry-batch")
def scan_contract_expiry_batch_json(body: ContractScanBatchRequest):
    result = scan_contract_expiry_from_batch(body.images_base64, body.mime_types)

    if not result["success"]:
        status_code = 503 if result.get("retryable") else 422
        raise HTTPException(status_code=status_code, detail=result)

    return result
