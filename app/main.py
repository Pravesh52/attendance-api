"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, StrictInt
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

def ensure_indexes():
    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("date", ASCENDING)],
        unique=True,
        name="uniq_emp_date",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_indexes()
    yield


app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def parse_hhmm(value: str) -> time:
    h, m = map(int, value.split(":"))
    return time(h, m)


def millis_to_utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms // 1000, tz=timezone.utc)  # // truncates to whole seconds


def utc_to_millis(dt: datetime) -> int:
    if dt.tzinfo is None:  # PyMongo returns naive datetimes that are really UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp()) * 1000


def attendance_day_and_late(punch_utc: datetime, shift_start: str, shift_end: str):
    """R1 + R2. Returns (attendance date 'YYYY-MM-DD', late_minutes)."""
    start_t, end_t = parse_hhmm(shift_start), parse_hhmm(shift_end)
    punch_ist = punch_utc.astimezone(IST)
    day = punch_ist.date()
    if end_t <= start_t and punch_ist.time() < end_t:  # overnight shift, belongs to previous day
        day = day - timedelta(days=1)
    shift_start_dt = datetime.combine(day, start_t, tzinfo=IST)
    late_seconds = (punch_ist - shift_start_dt).total_seconds()
    late_minutes = int(late_seconds // 60) if late_seconds > 600 else 0
    return day.isoformat(), late_minutes


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = Field(default=None, ge=100000000000, le=4102444800000)
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = {}
    if department is not None:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")

    if body.punched_at is not None:
        ts = millis_to_utc(body.punched_at)
    else:
        ts = datetime.now(timezone.utc).replace(microsecond=0)

    date_str, late = attendance_day_and_late(ts, emp["shift_start"], emp["shift_end"])
    doc = {
        "emp_code": body.emp_code,
        "date": date_str,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date")

    return {
        "emp_code": body.emp_code,
        "date": date_str,
        "status": body.status,
        "punch_in": utc_to_millis(ts),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
