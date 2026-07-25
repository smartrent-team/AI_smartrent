from core.db import get_connection


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
        warnings.append(f"Lượng điện tăng {elec_diff}% so với tháng trước")

    if water_diff > 50:
        water_status = "warning"
        warnings.append(f"Lượng nước tăng {water_diff}% so với tháng trước")

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
    }

    return result
