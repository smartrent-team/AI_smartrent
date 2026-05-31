import json
import re

from google.genai import types

from core.ai import client
from core.config import GEMINI_API_KEY

PRIORITY_PROMPT = """Bạn là hệ thống phân tích sự cố nhà trọ thông minh.
Nhiệm vụ: dựa vào tiêu đề, mô tả và ảnh (nếu có) của sự cố, xác định mức độ ưu tiên xử lý.

Quy tắc phân loại:
- "high"   : Nguy hiểm, ảnh hưởng an toàn hoặc không thể sinh hoạt (rò điện, vỡ ống nước lớn, cháy, mất điện toàn phòng, khóa cửa hỏng)
- "medium" : Bất tiện đáng kể nhưng không nguy hiểm (điều hòa hỏng, bồn cầu tắc, đèn hỏng một phần, wifi chập chờn)
- "low"    : Vấn đề nhỏ, thẩm mỹ hoặc không cấp bách (tường bong sơn, cửa sổ kẹt nhẹ, bóng đèn trang trí hỏng)

Chỉ trả về 1 object JSON hợp lệ, không markdown:
{"priority":"medium","reason":"Lý do ngắn gọn bằng tiếng Việt (tối đa 20 từ)"}"""


def analyze_ticket_priority(
    title: str,
    description: str,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> dict:
    if not GEMINI_API_KEY:
        return {"success": False, "error": "Thiếu GEMINI_API_KEY", "data": None}

    user_text = f"Tiêu đề: {title.strip()}\nMô tả: {description.strip()}"

    parts: list = []

    # Thêm ảnh nếu có
    if image_bytes and len(image_bytes) > 0:
        mime = (image_mime or "image/jpeg").lower()
        if mime == "image/jpg":
            mime = "image/jpeg"
        parts.append(
            types.Part(
                inline_data=types.Blob(data=image_bytes, mime_type=mime)
            )
        )

    parts.append(types.Part(text=user_text))
    parts.append(types.Part(text=PRIORITY_PROMPT))

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=parts)],
        )
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
        return {"success": False, "error": f"Lỗi AI: {exc}", "data": None}
