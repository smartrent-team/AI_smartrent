import json
import re

# pyrefly: ignore [missing-import]
from google.genai import types

from core.ai import client
from core.config import GEMINI_API_KEY

PRIORITY_PROMPT = """Bạn là hệ thống phân tích sự cố nhà trọ thông minh.
Nhiệm vụ: dựa vào tiêu đề, mô tả và ảnh (nếu có) của sự cố, xác định mức độ ưu tiên xử lý.

Quy tắc phân loại:
- "high"   : Các sự cố nguy hiểm đe dọa tính mạng, an toàn hoặc khiến phòng không thể sinh hoạt. Ví dụ: chập cháy, chập điện, cháy nổ, hỏa hoạn, rò điện, rò rỉ gas, vỡ ống nước lớn gây ngập, mất điện toàn bộ phòng, khóa cửa chính bị hỏng không khóa được.
- "medium" : Các sự cố gây bất tiện lớn cho sinh hoạt nhưng không đe dọa an toàn ngay lập tức. Ví dụ: hỏng điều hòa/máy lạnh, bồn cầu tắc, mất nước sinh hoạt, hỏng đèn chiếu sáng chính, wifi hỏng/chập chờn.
- "low"    : Các vấn đề nhỏ, liên quan đến thẩm mỹ hoặc không cấp bách. Ví dụ: tường bong tróc sơn, cửa sổ kẹt nhẹ, hỏng bóng đèn trang trí, nội thất xước nhẹ.

Chỉ trả về 1 object JSON hợp lệ, không markdown:
{"priority":"low"|"medium"|"high","reason":"Lý do ngắn gọn bằng tiếng Việt (tối đa 20 từ)"}"""


ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/gif",
}


def _guess_mime_from_bytes(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] == b"GIF87a" or data[:6] == b"GIF89a":
        return "image/gif"
    return "image/jpeg"


def analyze_ticket_priority(
    title: str,
    description: str,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> dict:
    if not GEMINI_API_KEY:
        return {"success": False, "error": "Thiếu GEMINI_API_KEY", "data": None}

    user_text = f"Tiêu đề: {title.strip()}\nMô tả: {description.strip()}"

    contents: list = []

    # Thêm ảnh nếu có
    if image_bytes and len(image_bytes) > 0:
        resolved_mime = (image_mime or _guess_mime_from_bytes(image_bytes)).lower()
        if resolved_mime == "image/jpg":
            resolved_mime = "image/jpeg"
            
        if resolved_mime not in ALLOWED_MIME_TYPES or resolved_mime == "application/octet-stream":
            resolved_mime = _guess_mime_from_bytes(image_bytes)

        contents.append(
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=resolved_mime
            )
        )

    contents.append(user_text)
    contents.append(PRIORITY_PROMPT)

    models_to_try = [
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash-lite",
    ]
    response = None
    last_exc = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
            )
            break
        except Exception as exc:
            last_exc = exc
            print(f"Model {model_name} failed: {exc}. Trying next model...")
            continue

    if response is None:
        return {"success": False, "error": f"Lỗi AI (tất cả các model đều quá tải/hết quota): {last_exc}", "data": None}

    try:
        raw = (response.text or "").strip()
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw)
        match = re.search(r"\{[\s\S]*\}", cleaned)
        data = json.loads(match.group(0) if match else cleaned)

        priority = str(data.get("priority", "medium")).lower()
        if priority not in ("low", "medium", "high"):
            priority = "medium"

        return {
            "success": True,
            "error": None,
            "data": {
                "priority": priority,
                "reason": str(data.get("reason", "")).strip(),
            },
        }
    except Exception as exc:
        return {"success": False, "error": f"Lỗi phân tích phản hồi từ AI: {exc}", "data": None}
