import base64
import json
import re

# pyrefly: ignore [missing-import]
from google.genai import types

from core.ai import client
from core.config import GEMINI_API_KEY

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

CCCD_PROMPT = """Bạn là hệ thống OCR căn cước công dân Việt Nam (CCCD hoặc CMND).
Nhiệm vụ: đọc ảnh mặt trước thẻ (có ảnh chân dung, họ tên, số định danh cá nhân).

Quy tắc:
- full_name: họ và tên đầy đủ như trên thẻ (giữ dấu tiếng Việt, viết hoa từng từ nếu trên thẻ là chữ hoa)
- cccd_number: CHỈ chữ số, bỏ dấu cách và ký tự khác (CMND 9 số hoặc CCCD 12 số)
- Nếu ảnh mờ, không phải thẻ, hoặc không đọc được: để full_name và cccd_number rỗng, ghi error ngắn

Chỉ trả về 1 object JSON hợp lệ, không markdown:
{"full_name":"","cccd_number":"","error":""}"""


def _guess_mime_from_bytes(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def normalize_cccd_number(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())


def normalize_full_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", (raw or "").strip())
    return name


def is_valid_cccd_number(number: str) -> bool:
    return len(number) in (9, 12) and number.isdigit()


def parse_cccd_ai_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", (text or "").strip())
    candidates = [cleaned]
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        candidates.insert(0, match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return {
                    "full_name": normalize_full_name(str(data.get("full_name", ""))),
                    "cccd_number": normalize_cccd_number(str(data.get("cccd_number", ""))),
                    "error": str(data.get("error", "")).strip() or None,
                }
        except json.JSONDecodeError:
            continue

    return {"full_name": "", "cccd_number": "", "error": "Không phân tích được phản hồi AI"}


def scan_cccd_from_bytes(image_bytes: bytes, mime_type: str | None = None) -> dict:
    if not GEMINI_API_KEY:
        return {
            "success": False,
            "error": "Thiếu GEMINI_API_KEY trong cấu hình server",
            "data": None,
        }

    if not image_bytes:
        return {
            "success": False,
            "error": "Ảnh trống",
            "data": None,
        }

    if len(image_bytes) > MAX_IMAGE_BYTES:
        return {
            "success": False,
            "error": "Ảnh quá lớn (tối đa 8MB)",
            "data": None,
        }

    resolved_mime = (mime_type or _guess_mime_from_bytes(image_bytes)).lower()
    if resolved_mime == "image/jpg":
        resolved_mime = "image/jpeg"
    if resolved_mime not in ALLOWED_MIME_TYPES:
        return {
            "success": False,
            "error": "Định dạng ảnh không hỗ trợ (jpeg, png, webp)",
            "data": None,
        }

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=image_bytes,
                                mime_type=resolved_mime,
                            )
                        ),
                        types.Part(text=CCCD_PROMPT),
                    ],
                )
            ],
        )
        parsed = parse_cccd_ai_response(response.text or "")
    except Exception as exc:
        return {
            "success": False,
            "error": f"Lỗi khi gọi AI: {exc}",
            "data": None,
        }

    if parsed.get("error"):
        return {
            "success": False,
            "error": parsed["error"],
            "data": {"full_name": "", "cccd_number": ""},
        }

    full_name = parsed["full_name"]
    cccd_number = parsed["cccd_number"]

    if not full_name or not cccd_number:
        return {
            "success": False,
            "error": "Không đọc được họ tên hoặc số CCCD trên ảnh. Chụp rõ mặt trước thẻ.",
            "data": {"full_name": full_name, "cccd_number": cccd_number},
        }

    if not is_valid_cccd_number(cccd_number):
        return {
            "success": False,
            "error": "Số CCCD/CMND không hợp lệ (cần 9 hoặc 12 chữ số)",
            "data": {"full_name": full_name, "cccd_number": cccd_number},
        }

    return {
        "success": True,
        "error": None,
        "data": {
            "full_name": full_name,
            "cccd_number": cccd_number,
        },
    }


def scan_cccd_from_base64(image_base64: str, mime_type: str | None = None) -> dict:
    raw = (image_base64 or "").strip()
    if not raw:
        return {"success": False, "error": "Thiếu image_base64", "data": None}

    if "," in raw and raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        if not mime_type and ";" in header:
            mime_type = header.split(";")[0].replace("data:", "")
        raw = payload

    try:
        image_bytes = base64.b64decode(raw, validate=True)
    except Exception:
        return {"success": False, "error": "image_base64 không hợp lệ", "data": None}

    return scan_cccd_from_bytes(image_bytes, mime_type)
