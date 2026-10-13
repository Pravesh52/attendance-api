import threading
import time

import requests

URL = "http://127.0.0.1:8000"
code = f"EMP{int(time.time()) % 900000 + 100000}"
body = {"emp_code": code, "name": "Race Test", "email": "race@example.com", "department": "Sales", "joined_on": "2026-07-15"}

codes = []


def hit():
    codes.append(requests.post(f"{URL}/employees", json=body).status_code)


threads = [threading.Thread(target=hit) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print(sorted(codes))