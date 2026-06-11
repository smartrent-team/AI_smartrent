import base64
import json
import re
from datetime import datetime

# pyrefly: ignore [missing-import]
from google.genai import types

from core.ai import client
from core.config import GEMINI_API_KEY

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BATCH_IMAGES = 10
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
CONTRACT_MODELS_TO_TRY = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
]
RETRYABLE_AI_ERROR_MARKERS = (
    "429",
    "503",
    "resource_exhausted",
    "unavailable",
    "high demand",
    "rate limit",
    "quota exceeded",
    "temporarily unavailable",
)

CONTRACT_EXPIRY_PROMPT = """Bạn là hệ thống OCR hợp đồng thuê nhà.
Nhiệm vụ: đọc ảnh hợp đồng và chỉ trích xuất ngày hết hạn hợp đồng.

Quy tắc:
- contract_end_date: trả về ngày hết hạn theo định dạng YYYY-MM-DD
- Nếu hợp đồng có nhiều ngày, chọn ngày kết thúc hợp đồng hoặc ngày hết hạn thuê phòng
- Nếu không thấy ngày hết hạn hoặc ảnh quá mờ: để contract_end_date là chuỗi rỗng và ghi error ngắn
- Chỉ trả về 1 object JSON hợp lệ, không markdown, không giải thích thêm

{ "contract_end_date": "", "error": "" }"""


def _guess_mime_from_bytes(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _normalize_date(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue

    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    if match:
        return match.group(0)

    match = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", value)
    if match:
        candidate = match.group(0).replace("-", "/")
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                parsed = datetime.strptime(candidate, fmt)
                return parsed.date().isoformat()
            except ValueError:
                continue

    return None


def parse_contract_expiry_ai_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", (text or "").strip())
    candidates = [cleaned]
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        candidates.insert(0, match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if not isinstance(data, dict):
                continue

            contract_end_date = _normalize_date(
                str(
                    data.get("contract_end_date")
                    or data.get("end_date")
                    or data.get("expiry_date")
                    or ""
                )
            )
            error = str(data.get("error", "")).strip() or None

            return {
                "contract_end_date": contract_end_date or "",
                "error": error,
            }
        except json.JSONDecodeError:
            continue

    fallback_date = _normalize_date(cleaned)
    if fallback_date:
        return {"contract_end_date": fallback_date, "error": None}

    return {
        "contract_end_date": "",
        "error": "Không phân tích được phản hồi AI",
    }


def _is_retryable_ai_error(exc: Exception | None) -> bool:
    if exc is None:
        return False

    message = str(exc).lower()
    return any(marker in message for marker in RETRYABLE_AI_ERROR_MARKERS)


def _generate_contract_analysis(contents):
    last_exc = None

    for model_name in CONTRACT_MODELS_TO_TRY:
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents,
            ), None
        except Exception as exc:
            last_exc = exc
            print(f"Model {model_name} failed: {exc}. Trying next model...")

    return None, last_exc


def scan_contract_expiry_from_bytes(image_bytes: bytes, mime_type: str | None = None) -> dict:
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

    response, last_exc = _generate_contract_analysis(
        [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        inline_data=types.Blob(
                            data=image_bytes,
                            mime_type=resolved_mime,
                        )
                    ),
                    types.Part(text=CONTRACT_EXPIRY_PROMPT),
                ],
            )
        ]
    )

    if response is None:
        return {
            "success": False,
            "error": f"Lỗi khi gọi AI: {last_exc}",
            "data": None,
            "retryable": _is_retryable_ai_error(last_exc),
        }

    parsed = parse_contract_expiry_ai_response(response.text or "")

    if parsed.get("error"):
        return {
            "success": False,
            "error": parsed["error"],
            "data": {"contract_end_date": parsed.get("contract_end_date", "")},
        }

    contract_end_date = parsed.get("contract_end_date", "")
    if not contract_end_date:
        return {
            "success": False,
            "error": "Không đọc được ngày hết hạn trong hợp đồng. Hãy chụp rõ phần ngày tháng.",
            "data": {"contract_end_date": ""},
        }

    return {
        "success": True,
        "error": None,
        "data": {
            "contract_end_date": contract_end_date,
        },
    }


def scan_contract_expiry_from_batch(
    images_base64: list[str],
    mime_types: list[str | None] | None = None,
) -> dict:
    if not images_base64:
        return {"success": False, "error": "Thiếu danh sách ảnh", "data": None}

    if len(images_base64) > MAX_BATCH_IMAGES:
        return {
            "success": False,
            "error": f"Quá nhiều ảnh (tối đa {MAX_BATCH_IMAGES})",
            "data": None,
        }

    if mime_types is None:
        mime_types = [None] * len(images_base64)

    if len(mime_types) < len(images_base64):
        mime_types = mime_types + [None] * (len(images_base64) - len(mime_types))

    if not GEMINI_API_KEY:
        return {
            "success": False,
            "error": "Thiếu GEMINI_API_KEY trong cấu hình server",
            "data": None,
        }

    image_parts = []
    for idx, raw in enumerate(images_base64):
        payload = (raw or "").strip()
        if not payload:
            continue

        if "," in payload and payload.startswith("data:"):
            header, _, encoded = payload.partition(",")
            if not mime_types[idx] and ";" in header:
                mime_types[idx] = header.split(";")[0].replace("data:", "")
            payload = encoded

        try:
            image_bytes = base64.b64decode(payload, validate=True)
        except Exception:
            return {"success": False, "error": f"Ảnh thứ {idx + 1} không hợp lệ", "data": None}

        resolved_mime = (mime_types[idx] or _guess_mime_from_bytes(image_bytes)).lower()
        if resolved_mime == "image/jpg":
            resolved_mime = "image/jpeg"
        if resolved_mime not in ALLOWED_MIME_TYPES:
            resolved_mime = _guess_mime_from_bytes(image_bytes)
        if resolved_mime not in ALLOWED_MIME_TYPES:
            return {
                "success": False,
                "error": f"Định dạng ảnh thứ {idx + 1} không hỗ trợ",
                "data": None,
            }

        image_parts.append(
            types.Part(
                inline_data=types.Blob(
                    data=image_bytes,
                    mime_type=resolved_mime,
                )
            )
        )

    if not image_parts:
        return {"success": False, "error": "Không có ảnh hợp lệ để quét", "data": None}

    response, last_exc = _generate_contract_analysis(
        [
            types.Content(
                role="user",
                parts=[
                    *image_parts,
                    types.Part(text=CONTRACT_EXPIRY_PROMPT),
                ],
            )
        ]
    )

    if response is None:
        return {
            "success": False,
            "error": f"Lỗi khi gọi AI: {last_exc}",
            "data": None,
            "retryable": _is_retryable_ai_error(last_exc),
        }

    parsed = parse_contract_expiry_ai_response(response.text or "")

    if parsed.get("error"):
        return {
            "success": False,
            "error": parsed["error"],
            "data": {"contract_end_date": parsed.get("contract_end_date", "")},
        }

    contract_end_date = parsed.get("contract_end_date", "")
    if not contract_end_date:
        return {
            "success": False,
            "error": "Không đọc được ngày hết hạn trong các ảnh hợp đồng. Hãy chụp rõ phần ngày tháng.",
            "data": {"contract_end_date": ""},
        }

    return {
        "success": True,
        "error": None,
        "data": {
            "contract_end_date": contract_end_date,
        },
    }


def scan_contract_expiry_from_base64(image_base64: str, mime_type: str | None = None) -> dict:
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

    return scan_contract_expiry_from_bytes(image_bytes, mime_type)


# ═══════════════════════════════════════════════════════════════════════
# QUÉT TIỀN CỌC TỪ ẢNH HỢP ĐỒNG
# ═══════════════════════════════════════════════════════════════════════

CONTRACT_DEPOSIT_PROMPT = """Bạn là hệ thống OCR hợp đồng thuê nhà.
Nhiệm vụ: đọc ảnh hợp đồng và chỉ trích xuất số tiền đặt cọc (tiền cọc).

Quy tắc:
- deposit_amount: trả về số tiền đặt cọc (chỉ số nguyên, không có dấu chấm, dấu phẩy, không có đơn vị tiền tệ)
- Tìm các từ khóa: "tiền cọc", "tiền đặt cọc", "đặt cọc", "khoản cọc", "deposit"
- Nếu hợp đồng ghi "2.000.000 đồng" thì trả về 2000000
- Nếu hợp đồng ghi "2 triệu" thì trả về 2000000
- Nếu không thấy tiền cọc hoặc ảnh quá mờ: để deposit_amount là 0 và ghi error ngắn
- Chỉ trả về 1 object JSON hợp lệ, không markdown, không giải thích thêm

{ "deposit_amount": 0, "error": "" }"""


def _normalize_deposit_amount(raw) -> int:
    """Chuẩn hóa giá trị tiền cọc từ kết quả AI."""
    if raw is None:
        return 0

    if isinstance(raw, (int, float)):
        return max(0, int(raw))

    value = str(raw).strip().lower()
    if not value:
        return 0

    # Xóa đơn vị tiền tệ
    for unit in ("đồng", "đ", "vnd", "vnđ", "dong"):
        value = value.replace(unit, "")

    # Xóa dấu chấm, dấu phẩy phân cách hàng nghìn
    value = value.replace(".", "").replace(",", "").strip()

    # Xử lý "triệu"
    if "triệu" in value or "trieu" in value:
        value = re.sub(r"(triệu|trieu)", "", value).strip()
        try:
            return max(0, int(float(value) * 1_000_000))
        except ValueError:
            return 0

    try:
        return max(0, int(float(value)))
    except ValueError:
        # Thử tìm chuỗi số trong text
        match = re.search(r"\d+", value)
        if match:
            return max(0, int(match.group(0)))
        return 0


def parse_contract_deposit_ai_response(text: str) -> dict:
    """Parse JSON response từ AI cho tiền cọc."""
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", (text or "").strip())
    candidates = [cleaned]
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        candidates.insert(0, match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if not isinstance(data, dict):
                continue

            deposit_amount = _normalize_deposit_amount(
                data.get("deposit_amount")
                or data.get("tien_coc")
                or data.get("deposit")
                or 0
            )
            error = str(data.get("error", "")).strip() or None

            return {
                "deposit_amount": deposit_amount,
                "error": error,
            }
        except json.JSONDecodeError:
            continue

    return {
        "deposit_amount": 0,
        "error": "Không phân tích được phản hồi AI",
    }


def scan_contract_deposit_from_bytes(image_bytes: bytes, mime_type: str | None = None) -> dict:
    """Quét tiền cọc từ ảnh hợp đồng (bytes)."""
    if not GEMINI_API_KEY:
        return {"success": False, "error": "Thiếu GEMINI_API_KEY trong cấu hình server", "data": None}

    if not image_bytes:
        return {"success": False, "error": "Ảnh trống", "data": None}

    if len(image_bytes) > MAX_IMAGE_BYTES:
        return {"success": False, "error": "Ảnh quá lớn (tối đa 8MB)", "data": None}

    resolved_mime = (mime_type or _guess_mime_from_bytes(image_bytes)).lower()
    if resolved_mime == "image/jpg":
        resolved_mime = "image/jpeg"
    if resolved_mime not in ALLOWED_MIME_TYPES:
        return {"success": False, "error": "Định dạng ảnh không hỗ trợ (jpeg, png, webp)", "data": None}

    response, last_exc = _generate_contract_analysis(
        [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        inline_data=types.Blob(
                            data=image_bytes,
                            mime_type=resolved_mime,
                        )
                    ),
                    types.Part(text=CONTRACT_DEPOSIT_PROMPT),
                ],
            )
        ]
    )

    if response is None:
        return {
            "success": False,
            "error": f"Lỗi khi gọi AI: {last_exc}",
            "data": None,
            "retryable": _is_retryable_ai_error(last_exc),
        }

    parsed = parse_contract_deposit_ai_response(response.text or "")

    if parsed.get("error"):
        return {
            "success": False,
            "error": parsed["error"],
            "data": {"deposit_amount": parsed.get("deposit_amount", 0)},
        }

    deposit_amount = parsed.get("deposit_amount", 0)
    if deposit_amount <= 0:
        return {
            "success": False,
            "error": "Không đọc được tiền cọc trong hợp đồng. Hãy chụp rõ phần tiền cọc.",
            "data": {"deposit_amount": 0},
        }

    return {
        "success": True,
        "error": None,
        "data": {"deposit_amount": deposit_amount},
    }


def scan_contract_deposit_from_batch(
    images_base64: list[str],
    mime_types: list[str | None] | None = None,
) -> dict:
    """Quét tiền cọc từ nhiều ảnh hợp đồng cùng lúc."""
    if not images_base64:
        return {"success": False, "error": "Thiếu danh sách ảnh", "data": None}

    if len(images_base64) > MAX_BATCH_IMAGES:
        return {"success": False, "error": f"Quá nhiều ảnh (tối đa {MAX_BATCH_IMAGES})", "data": None}

    if mime_types is None:
        mime_types = [None] * len(images_base64)
    if len(mime_types) < len(images_base64):
        mime_types = mime_types + [None] * (len(images_base64) - len(mime_types))

    if not GEMINI_API_KEY:
        return {"success": False, "error": "Thiếu GEMINI_API_KEY trong cấu hình server", "data": None}

    image_parts = []
    for idx, raw in enumerate(images_base64):
        payload = (raw or "").strip()
        if not payload:
            continue

        if "," in payload and payload.startswith("data:"):
            header, _, encoded = payload.partition(",")
            if not mime_types[idx] and ";" in header:
                mime_types[idx] = header.split(";")[0].replace("data:", "")
            payload = encoded

        try:
            image_bytes = base64.b64decode(payload, validate=True)
        except Exception:
            return {"success": False, "error": f"Ảnh thứ {idx + 1} không hợp lệ", "data": None}

        resolved_mime = (mime_types[idx] or _guess_mime_from_bytes(image_bytes)).lower()
        if resolved_mime == "image/jpg":
            resolved_mime = "image/jpeg"
        if resolved_mime not in ALLOWED_MIME_TYPES:
            resolved_mime = _guess_mime_from_bytes(image_bytes)
        if resolved_mime not in ALLOWED_MIME_TYPES:
            return {"success": False, "error": f"Định dạng ảnh thứ {idx + 1} không hỗ trợ", "data": None}

        image_parts.append(
            types.Part(
                inline_data=types.Blob(
                    data=image_bytes,
                    mime_type=resolved_mime,
                )
            )
        )

    if not image_parts:
        return {"success": False, "error": "Không có ảnh hợp lệ để quét", "data": None}

    response, last_exc = _generate_contract_analysis(
        [
            types.Content(
                role="user",
                parts=[
                    *image_parts,
                    types.Part(text=CONTRACT_DEPOSIT_PROMPT),
                ],
            )
        ]
    )

    if response is None:
        return {
            "success": False,
            "error": f"Lỗi khi gọi AI: {last_exc}",
            "data": None,
            "retryable": _is_retryable_ai_error(last_exc),
        }

    parsed = parse_contract_deposit_ai_response(response.text or "")

    if parsed.get("error"):
        return {
            "success": False,
            "error": parsed["error"],
            "data": {"deposit_amount": parsed.get("deposit_amount", 0)},
        }

    deposit_amount = parsed.get("deposit_amount", 0)
    if deposit_amount <= 0:
        return {
            "success": False,
            "error": "Không đọc được tiền cọc trong các ảnh hợp đồng.",
            "data": {"deposit_amount": 0},
        }

    return {
        "success": True,
        "error": None,
        "data": {"deposit_amount": deposit_amount},
    }
