import requests

URL = "http://127.0.0.1:8000"

# (method, path, json body, set of acceptable status codes)
CHECKS = [
    ("GET", "/health", None, {200}),
    ("GET", "/employees", None, {200}),
    ("GET", "/employees?department=Sales&page=1&page_size=1", None, {200}),
    ("GET", "/employees?page=0", None, {422}),
    ("POST", "/employees", {"emp_code": "bad", "name": "x", "email": "x", "department": "x", "joined_on": "x"}, {422}),
    ("GET", "/attendance", None, {200}),
    ("GET", "/attendance?status=HOLIDAY", None, {422}),
    ("GET", "/attendance?date_from=2026-07-08&date_to=2026-07-07", None, {422}),
    ("POST", "/attendance/punch-in", {"emp_code": "EMP9999"}, {404}),
    ("POST", "/attendance/punch-in", {"emp_code": "EMP0002", "punched_at": 1784692800000}, {201, 409}),
    ("POST", "/attendance/punch-in", {"emp_code": "EMP0002", "status": "HOLIDAY"}, {422}),
    ("POST", "/attendance/punch-out", {"emp_code": "EMP9999"}, {404}),
    ("POST", "/attendance/punch-out", {"emp_code": "EMP0006", "punched_at": 1783429800000}, {200, 409}),
    ("PATCH", "/attendance/EMP0001/2026-06-01", {"status": "WFH", "reason": "smoke test", "regularized_by": "smoke"}, {404}),
    ("PATCH", "/attendance/EMP0001/2026-07-07", {"punch_in": 1783397700000, "reason": "smoke test", "regularized_by": "smoke"}, {200, 422}),
    ("PATCH", "/attendance/EMP0001/2026-07-07", {"reason": "abc", "regularized_by": "smoke"}, {422}),
    ("GET", "/analytics/employees/EMP0001/monthly?month=2026-07", None, {200}),
    ("GET", "/analytics/employees/EMP9999/monthly?month=2026-07", None, {404}),
    ("GET", "/analytics/employees/EMP0001/monthly?month=2026-13", None, {422}),
    ("GET", "/analytics/departments/summary?month=2026-07", None, {200}),
    ("GET", "/analytics/departments/summary?month=2026-7", None, {422}),
    ("GET", "/analytics/leaderboard/late?month=2026-07", None, {200}),
    ("GET", "/analytics/leaderboard/late?month=2026-07&limit=0", None, {422}),
    ("GET", "/analytics/departments/Engineering/trend?from=2026-07-06&to=2026-07-14", None, {200}),
    ("GET", "/analytics/departments/Nope/trend?from=2026-07-06&to=2026-07-14", None, {404}),
    ("GET", "/analytics/departments/Engineering/trend?from=2026-07-14&to=2026-07-06", None, {422}),
    ("GET", "/admin/explain/attendance_list", None, {200}),
    ("GET", "/admin/explain/department_trend", None, {422}),
    ("GET", "/admin/explain/nonsense", None, {422}),
]

failed = 0
for method, path, body, ok in CHECKS:
    r = requests.request(method, URL + path, json=body)
    good = r.status_code in ok
    failed += 0 if good else 1
    print("PASS" if good else "FAIL", r.status_code, method, path)

print()
print("ALL PASSED" if failed == 0 else f"{failed} FAILED")