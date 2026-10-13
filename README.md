# Employee Attendance & Analytics API

A FastAPI + MongoDB backend for employee attendance (punch-in / punch-out,
manual corrections with an audit trail) and attendance analytics built on
MongoDB aggregation pipelines.

All application code is in a single file: `app/main.py`.

## Requirements

- Python 3.11+
- MongoDB 6.0+ (local Docker container or MongoDB Atlas)

## How to run

1. Create a virtual environment and install the dependencies:

   ```
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # macOS / Linux
   pip install -r requirements.txt
   ```

2. Configure the database through environment variables. A local `.env`
   file also works, and real environment variables take priority over it:

   ```
   MONGO_URI=<your MongoDB connection string>
   MONGO_DB=<database name>
   ```

3. Start the server from the repository root:

   ```
   uvicorn app.main:app --port 8000
   ```

4. Open `http://127.0.0.1:8000/docs` for the interactive API docs.
   `GET /health` is the health check.

All indexes are created at startup, and the creation is idempotent.
Connection details are never hard-coded, and `.env` is git-ignored.

## Status

Nothing is missing. Every endpoint of the contract is implemented:

- `GET /health`
- `POST /employees`, `GET /employees`
- `POST /attendance/punch-in`, `POST /attendance/punch-out`, `GET /attendance`
- `PATCH /attendance/{emp_code}/{date}` (manual correction with audit trail)
- `GET /analytics/employees/{emp_code}/monthly`
- `GET /analytics/departments/summary`
- `GET /analytics/leaderboard/late`
- `GET /analytics/departments/{department}/trend`
- `GET /admin/explain/{endpoint}`

## Assumptions

- The trend range limit of 92 days counts both the `from` and the `to` day.
- For an overnight shift, a punch-in after midnight belongs to the previous
  day's shift, so its late minutes are measured from that shift's start.
- If `MONGO_URI` is not set, the app prints a warning and falls back to
  `mongodb://localhost:27017`.

## Other files

- `REVIEW.md`: defects found in the starter code and how each one was fixed.
- `DECISIONS.md`: short answers about indexes, concurrency, ties and headcount.
