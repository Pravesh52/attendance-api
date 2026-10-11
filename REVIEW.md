
# REVIEW.md

Defects found in the starter `app/main.py`. This file is updated as the review
progresses.

## Fixed

| # | Where | What is wrong | How you'd notice it | How I fixed it |
|---|---|---|---|---|
| 1 | `list_employees`, `skip` | `skip = page * page_size` ignores that `page` starts at 1, so page 1 skips the first `page_size` employees (off-by-one). | `GET /employees` with the default `page=1` returned `items: []` while the collection had 6 employees. `page=1&page_size=1` returned the second employee instead of the first. | `skip = (page - 1) * page_size`. |
| 2 | `list_employees`, `total` | `count_documents({})` counts the whole collection and ignores the `department` filter. The contract says `total` counts the filtered set. | `GET /employees?department=Sales` returned `total: 6` although only 2 employees are in Sales. | `count_documents(q)`, using the same filter as the query. |
| 3 | `list_employees`, sorting and validation | No sort, so the order is not guaranteed and pages can repeat or skip rows. `page` and `page_size` are not validated, so `page=0` gives a negative skip and `page_size=100000` is accepted. The contract requires sorting by `emp_code`, `page >= 1` and `1 <= page_size <= 100`. | `page=0` or `page_size=101` was accepted instead of returning 422. Row order was not guaranteed. | `.sort("emp_code", 1)`, and `Query(1, ge=1)` / `Query(20, ge=1, le=100)` for validation. Also `if department is not None` so an empty string is treated as a real filter. |

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
