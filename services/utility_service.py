from core.db import get_connection
from core.ai import client
import json
import re


def get_utility_data(room_id: str):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            room_id,
            electric_old,
            electric_new,
            electric_usage,
            water_old,
            water_new,
            water_usage,
            month,
            year,
            ai_analysis,
            id
        FROM utility_logs
        WHERE room_id = %s
        ORDER BY year DESC, month DESC
        LIMIT 6
    """, (room_id,))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


def calc_avg(rows, index):
    values = [r[index] for r in rows if r[index] is not None]
    return round(sum(values) / len(values), 1) if values else 0


def calc_diff(curr, prev):
    if not prev or prev <= 0:
        return 0

    return round(((curr - prev) / prev) * 100, 1)


def parse_ai_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text.strip())

    candidates = [cleaned]
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        candidates.insert(0, match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return {
                    "summary": str(data.get("summary", "")).strip(),
                    "possible_causes": [
                        str(item).strip()
                        for item in data.get("possible_causes", [])
                        if str(item).strip()
                    ][:2],
                    "recommendations": [
                        str(item).strip()
                        for item in data.get("recommendations", [])
                        if str(item).strip()
                    ][:2],
                }
        except json.JSONDecodeError:
            continue

    return {
        "summary": "Không thể phân tích dữ liệu. Vui lòng thử lại sau.",
        "possible_causes": [],
        "recommendations": [],
    }


def analyze_utility(room_id: str):
    rows = get_utility_data(room_id)

    if len(rows) < 2:
        return {
            "status": "insufficient_data"
        }

    current = rows[0]
    previous = rows[1]

    curr_elec = current[3]
    prev_elec = previous[3]

    curr_water = current[6]
    prev_water = previous[6]

    elec_diff = calc_diff(curr_elec, prev_elec)
    water_diff = calc_diff(curr_water, prev_water)

    avg_elec = calc_avg(rows, 3)
    avg_water = calc_avg(rows, 6)

    warnings = []

    elec_status = "normal"
    water_status = "normal"

    if elec_diff > 50:
        elec_status = "warning"
        warnings.append(
            f"Lượng điện tăng {elec_diff}% so với tháng trước"
        )

    if water_diff > 50:
        water_status = "warning"
        warnings.append(
            f"Lượng nước tăng {water_diff}% so với tháng trước"
        )

    ai_comment = None

    # Lấy phân tích từ database nếu đã tồn tại
    if current[9] is not None:
        if isinstance(current[9], dict):
            ai_comment = current[9]
        elif isinstance(current[9], str):
            try:
                ai_comment = json.loads(current[9])
            except:
                pass

    def build_history(usage_index):
        return [
            {
                "month": r[7],
                "year": r[8],
                "label": f"T{r[7]}",
                "usage": r[usage_index],
            }
            for r in reversed(rows)
        ]

    result = {
        "room_id": room_id,
        "month": current[7],
        "year": current[8],

        "summary": {
            "critical": 0,
            "warning": len(warnings)
        },

        "electric": {
            "status": elec_status,
            "meter_old": current[1],
            "meter_new": current[2],
            "current_usage": curr_elec,
            "previous_usage": prev_elec,
            "change_percent": elec_diff,
            "average_6_months": avg_elec,
            "history": [r[3] for r in reversed(rows)],
            "history_detail": build_history(3),
        },

        "water": {
            "status": water_status,
            "meter_old": current[4],
            "meter_new": current[5],
            "current_usage": curr_water,
            "previous_usage": prev_water,
            "change_percent": water_diff,
            "average_6_months": avg_water,
            "history": [r[6] for r in reversed(rows)],
            "history_detail": build_history(6),
        },

        "warnings": warnings,
        "ai_analysis": ai_comment
    }

    return result 


def trigger_utility_ai_analysis(room_id: str):
    rows = get_utility_data(room_id)
    if len(rows) < 2:
        return {"success": False, "error": "Không đủ dữ liệu lịch sử để phân tích"}

    current = rows[0]
    previous = rows[1]
    log_id = current[10]

    curr_elec = current[3]
    prev_elec = previous[3]
    curr_water = current[6]
    prev_water = previous[6]

    elec_diff = calc_diff(curr_elec, prev_elec)
    water_diff = calc_diff(curr_water, prev_water)

    avg_elec = calc_avg(rows, 3)
    avg_water = calc_avg(rows, 6)

    warnings = []
    if elec_diff > 50:
        warnings.append(f"Lượng điện tăng {elec_diff}% so với tháng trước")
    if water_diff > 50:
        warnings.append(f"Lượng nước tăng {water_diff}% so với tháng trước")

    if not warnings:
        return {"success": True, "ai_analysis": None, "message": "Điện nước bình thường, không cần phân tích"}

    warning_text = "; ".join(warnings)
    prompt = f"""Bạn là chuyên gia phân tích tiêu thụ điện nước cho phòng trọ.

Dữ liệu tháng này:
- Điện: {curr_elec} kWh (thay đổi {elec_diff}% so tháng trước, TB 6 tháng: {avg_elec} kWh)
- Nước: {curr_water} m³ (thay đổi {water_diff}% so tháng trước, TB 6 tháng: {avg_water} m³)
- Cảnh báo: {warning_text}

Viết tiếng Việt, ngắn gọn, dễ đọc trên app mobile.

Quy tắc bắt buộc:
- Chỉ trả về 1 object JSON hợp lệ, không markdown, không text thừa
- summary: tối đa 2 câu, nêu rõ điện/nước bình thường hay bất thường
- possible_causes: tối đa 2 mục, mỗi mục tối đa 12 từ
- recommendations: tối đa 2 mục, mỗi mục tối đa 12 từ, hành động cụ thể

Format:
{{"summary":"...","possible_causes":["..."],"recommendations":["..."]}}"""

    # Gọi AI với cơ chế chuyển đổi dự phòng tránh lỗi 429/503
    models_to_try = [
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
                contents=prompt
            )
            break
        except Exception as exc:
            last_exc = exc
            print(f"Model {model_name} failed: {exc}. Trying next model...")
            continue

    if response is None:
        return {"success": False, "error": f"Lỗi AI: {last_exc}"}

    try:
        ai_comment = parse_ai_response(response.text)
        
        # Lưu vào database
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE utility_logs
            SET ai_analysis = %s
            WHERE id = %s
        """, (json.dumps(ai_comment), log_id))
        conn.commit()
        cur.close()
        conn.close()

        return {"success": True, "ai_analysis": ai_comment}
    except Exception as e:
        return {"success": False, "error": f"Lỗi lưu kết quả AI vào database: {e}"}