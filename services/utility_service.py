from core.db import get_connection
from core.ai import client


def get_utility_data(room_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
    """
        SELECT electric_old, electric_new, electric_usage, water_old, water_new, water_usage, month, year
        FROM utility_logs
        WHERE room_id = %s
        ORDER BY year DESC, month DESC
        LIMIT 2
    """, (room_id,)
    )

    rows = cur.fetchall()
    cur.close()
    return rows

def analyze_utility(room_id: str):
    rows = get_utility_data(room_id)

    if len(rows) < 2:
        return {"status": "ok", "warning": [], "ai_comment": None}
    
    current = rows[0]
    previous = rows[1]
    warnings = []

    curr_elec = current[2]
    prev_elec = previous[2]
    curr_water = current[5]
    prev_water = previous[5]

    if prev_elec and prev_elec > 0:
        elec_diff = ((curr_elec - prev_elec) / prev_elec) * 100
        if elec_diff > 50:
            warnings.append(f"Điện tăng {elec_diff:.1f}% so với tháng trước")

    if prev_water and prev_water > 0:
        water_diff = ((curr_water - prev_water) / prev_water) * 100
        if water_diff > 50:
            warnings.append(f"Nước tăng {water_diff:.1f}% so với tháng trước")

    ai_comment = None
    if warnings:
        prompt = f"""
            Bạn là hệ thống cảnh báo tiêu thụ điện nước.

            CHỈ được trả lời theo format sau, tối đa 6 dòng:

            MoM:
            - Điện: %
            - Nước: %

            YoY:
            - Điện: chỉ ghi "N/A nếu không có dữ liệu"
            - Nước: chỉ ghi "N/A nếu không có dữ liệu"

            Nguyên nhân: 1-2 ý ngắn
            Hành động: 2-3 gạch đầu dòng

            Không giải thích dài. Không ví dụ. Không mở rộng.
            Dữ liệu:
            {', '.join(warnings)}
        """
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        ai_comment = response.text

    if warnings:
        save_anomaly(rows[0], warnings)

    return {
        "status": "warning" if warnings else "ok",
        "warnings": warnings,
        "ai_comment": ai_comment,
    }

def save_anomaly(utility_log, warnings: list):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM utility_logs
        WHERE room_id = %s AND month = %s AND year = %s
    """, (utility_log[0], utility_log[6], utility_log[7]))

    log = cur.fetchone()
    if not log:
        return

    for warning in warnings:
        cur.execute("""
            INSERT INTO utility_anomalies 
                (id, utility_log_id, type, severity, message, resolved)
            VALUES 
                (gen_random_uuid(), %s, 'usage_spike', 'high', %s, false)
        """, (log[0], warning))

    conn.commit()
    cur.close()
    conn.close()