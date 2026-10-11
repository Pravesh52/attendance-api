
# REVIEW.md

Defects found in the starter `app/main.py`. This file is updated as the review
progresses.

## Fixed

| # | Where | What is wrong | How you'd notice it | How I fixed it |
|---|---|---|---|---|
| 1 | `list_employees`, `skip` | `skip = page * page_size` ignores that `page` starts at 1, so page 1 skips the first `page_size` employees (off-by-one). | `GET /employees` with the default `page=1` returned `items: []` while the collection had 6 employees. `page=1&page_size=1` returned the second employee instead of the first. | `skip = (page - 1) * page_size`. |
| 2 | `list_employees`, `total` | `count_documents({})` counts the whole collection and ignores the `department` filter. The contract says `total` counts the filtered set. | `GET /employees?department=Sales` returned `total: 6` although only 2 employees are in Sales. | `count_documents(q)`, using the same filter as the query. |
| 3 | `list_employees`, sorting and validation | No sort, so the order is not guaranteed and pages can repeat or skip rows. `page` and `page_size` are not validated, so `page=0` gives a negative skip and `page_size=100000` is accepted. The contract requires sorting by `emp_code`, `page >= 1` and `1 <= page_size <= 100`. | `page=0` or `page_size=101` was accepted instead of returning 422. Row order was not guaranteed. | `.sort("emp_code", 1)`, and `Query(1, ge=1)` / `Query(20, ge=1, le=100)` for validation. Also `if department is not None` so an empty string is treated as a real filter. |
| 4 | `punch_in`, employee lookup | `find_one` returns `None` for an unknown `emp_code`, and the code then does `emp["shift_start"]`. The contract requires 404. | `POST /attendance/punch-in` with `{"emp_code": "EMP9999"}` returned 500 (`TypeError: 'NoneType' object is not subscriptable`). | Check `if emp is None` right after the lookup and raise `HTTPException(404)`. |
| 5 | `punch_in`, time zone and attendance date | `datetime.fromtimestamp(ms/1000)` and `datetime.now()` return naive local machine time. PyMongo treats naive datetimes as UTC, so the stored instant is shifted, and on a UTC server the `date` is the UTC date instead of the IST date (R1). | Punch-in at 02:00 IST on a UTC machine gets the previous day's `date`. On an IST laptop the stored UTC value is 5h30m off. | Convert epoch milliseconds to timezone-aware UTC datetimes, compute the IST date from `astimezone(IST)`, and store the aware UTC datetime. |
| 6 | `punch_in`, `punched_at` handling | Not truncated to whole seconds (R1). `if body.punched_at` treats `0` as missing. `Optional[int]` in lax mode silently accepts `"1784520600000"` and `1784520600000.0`, and accepts seconds-looking values like `1784520600` (a 1970 date). The contract requires 422 for all of these. | Send `punched_at` as a string, a float, or in seconds: the request succeeded instead of returning 422. Microseconds appear in the stored value when `punched_at` is omitted. | `punched_at: Optional[StrictInt] = Field(None, ge=100000000000, le=4102444800000)`, check `is not None`, and truncate with `ms // 1000` (or `replace(microsecond=0)` for "now"). |
| 7 | `punch_in`, `status` | `status: str` accepts any value, so `"HOLIDAY"` is stored. Only `PRESENT`, `WFH` and `ON_DUTY` are allowed here. | `{"emp_code": "EMP0006", "status": "HOLIDAY"}` returned 201. | `status: Literal["PRESENT", "WFH", "ON_DUTY"]`, so anything else gives 422. |
| 8 | `punch_in`, duplicate check | Check-then-insert (`find_one` then `insert_one`) is a race: two simultaneous requests both see no record and both insert, creating two records for one (`emp_code`, `date`). | Fire two parallel punch-ins for the same employee: two 201 responses and two documents, instead of one 201 and one 409. | Unique compound index on (`emp_code`, `date`), created at startup. The insert is wrapped in `try/except DuplicateKeyError` and returns 409. The `find_one` pre-check is removed. |
| 9 | `punch_in`, response | Returns `id` (`str(inserted_id)`), but `_id` must never appear in the API. `punch_in` is returned as a datetime (serialized as an ISO string), but the contract requires epoch milliseconds. | Response body contained `"id": "..."` and `"punch_in": "2026-10-11T..."`. | Build a separate response dict with no `id` and `punch_in` converted to epoch milliseconds (`utc_to_millis`). |
| 10 | `compute_late_minutes` | (a) Uses `punch_in.replace(hour=..., minute=...)` on a naive/UTC value, so shift start is not in IST. (b) It floors to whole minutes first and then checks `> 10`, so 09:40:30 on a 09:30 shift gives 0, but R2 says "strictly more than 10:00" (should be 10). (c) Overnight shifts are not handled: a 22:00-06:00 employee punching in at 03:00 uses the wrong shift start day. | Shift 09:30, punch-in 09:40:01 should give 10 but gives 0. | Replaced by `attendance_day_and_late`: works in IST, compares in seconds (`> 600`), then floors to minutes since shift start, and moves the shift start to the previous day for overnight punch-ins before `shift_end`. |

## Found, fix still pending

- **`MongoClient` default.** If `MONGO_URI` is missing, the code silently falls
  back to `mongodb://localhost:27017`. The failure then only appears after a
  30-second server selection timeout inside a request (seen as a 500 with
  `localhost:27017 ... refused`). Planned fix: fail fast at startup if the
  variable is missing, instead of using a silent default.
- **`create_employee`, `created_at`.** `datetime.now()` is a naive local time
  and is returned as an ISO string; the contract wants a UTC datetime stored
  in MongoDB and epoch milliseconds in the API.

## Looked at and decided it is fine

- `db.employees.find(q, {"_id": 0})`: the projection hides `_id`, which must
  never be returned by the API.
- `department` filter: the exact, case-sensitive match is what the contract
  asks for.
