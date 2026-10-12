import json

import requests

URL = "http://127.0.0.1:8000/admin/explain"
CASES = [
    ("attendance_list", {}),
    ("attendance_list", {"emp_code": "EMP0001"}),
    ("attendance_list", {"status": "WFH"}),
    ("attendance_list", {"date_from": "2026-07-01", "date_to": "2026-07-31"}),
    ("employee_monthly", {"emp_code": "EMP0001", "month": "2026-07"}),
    ("department_summary", {"month": "2026-07"}),
    ("department_summary", {"month": "2026-07", "department": "Sales"}),
    ("late_leaderboard", {"month": "2026-07"}),
    ("late_leaderboard", {"month": "2026-07", "department": "Sales"}),
    ("department_trend", {"department": "Engineering", "from": "2026-07-06", "to": "2026-07-14"}),
]

for name, params in CASES:
    r = requests.get(f"{URL}/{name}", params=params)
    if r.status_code != 200:
        print("FAIL", name, params, r.status_code, r.text[:100])
        continue
    text = json.dumps(r.json()["explain"])
    ok = "IXSCAN" in text and "COLLSCAN" not in text
    print("PASS" if ok else "FAIL", name, params)