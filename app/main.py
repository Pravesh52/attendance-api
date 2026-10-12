"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
import calendar
from contextlib import asynccontextmanager
from datetime import date as date_type, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, StrictInt
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True)
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

def ensure_indexes():
    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("date", ASCENDING)],
        unique=True,
        name="uniq_emp_date",
    )
    db.attendance_logs.create_index(
        [("date", DESCENDING), ("emp_code", ASCENDING)],
        name="date_desc_emp",
    )
    db.attendance_logs.create_index(
        [("status", ASCENDING), ("date", DESCENDING), ("emp_code", ASCENDING)],
        name="status_date_emp",
    )
    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("punch_in", DESCENDING)],
        name="emp_punchin_desc",
    )
    db.employees.create_index("emp_code", unique=True, name="uniq_emp_code")
    db.employees.create_index(
        [("department", ASCENDING), ("joined_on", ASCENDING)],
        name="dept_joined",
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

def convert_value(v):
    return utc_to_millis(v) if isinstance(v, datetime) else v


def history_to_api(h: dict) -> dict:
    return {
        "at": utc_to_millis(h["at"]),
        "by": h["by"],
        "reason": h["reason"],
        "changes": {
            k: {"from": convert_value(c["from"]), "to": convert_value(c["to"])}
            for k, c in h["changes"].items()
        },
    }


def attendance_to_api(d: dict) -> dict:
    return {
        "emp_code": d["emp_code"],
        "date": d["date"],
        "status": d["status"],
        "punch_in": convert_value(d.get("punch_in")),
        "punch_out": convert_value(d.get("punch_out")),
        "work_hours": d.get("work_hours"),
        "late_minutes": d.get("late_minutes", 0),
        "overtime_minutes": d.get("overtime_minutes", 0),
        "half_day": d.get("half_day", False),
        "history": [history_to_api(h) for h in d.get("history", [])],
    }

PRESENT_STATUSES = ["PRESENT", "WFH", "ON_DUTY"]
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def month_bounds(month: str):
    year, mon = int(month[:4]), int(month[5:7])
    if year < 1:
        raise HTTPException(422, "invalid month")
    last_day = calendar.monthrange(year, mon)[1]
    return date_type(year, mon, 1), date_type(year, mon, last_day)


def count_weekdays(start: date_type, end: date_type) -> int:
    if end < start:
        return 0
    days = (end - start).days + 1
    return sum(1 for i in range(days) if (start + timedelta(days=i)).weekday() < 5)

def present_value_expr(p: str = "$"):
    """Aggregation expression: 1 / 0.5 / 0 present-day value of a log, Mon-Fri only (R5-R7)."""
    return {
        "$cond": [
            {
                "$and": [
                    {"$in": [f"{p}status", PRESENT_STATUSES]},
                    {"$lte": [{"$isoDayOfWeek": {"$dateFromString": {"dateString": f"{p}date"}}}, 5]},
                ]
            },
            {"$cond": [{"$eq": [{"$ifNull": [f"{p}half_day", False]}, True]}, 0.5, 1]},
            0,
        ]
    }

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = int((punch_out - punch_in).total_seconds())
    hours = Decimal(seconds) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(punch_out: datetime, shift_start: str, shift_end: str, date_str: str) -> int:
    start_t, end_t = parse_hhmm(shift_start), parse_hhmm(shift_end)
    end_day = date_type.fromisoformat(date_str)
    if end_t <= start_t:  # overnight shift: it ends on the next calendar day
        end_day += timedelta(days=1)
    shift_end_dt = datetime.combine(end_day, end_t, tzinfo=IST)
    minutes = int((punch_out - shift_end_dt).total_seconds() // 60)
    return minutes if minutes >= 30 else 0


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

AnyStatus = Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]

EpochMs = Annotated[StrictInt, Field(ge=100000000000, le=4102444800000)]


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[EpochMs] = None
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[EpochMs] = None


class RegularizeIn(BaseModel):
    status: Optional[AnyStatus] = None
    punch_in: Optional[EpochMs] = None
    punch_out: Optional[EpochMs] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., pattern=MONTH_PATTERN)):
    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")

    first, last = month_bounds(month)
    start = max(first, date_type.fromisoformat(emp["joined_on"]))
    working_days = count_weekdays(start, last)

    pipeline = [
        {"$match": {"emp_code": emp_code, "date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}}},
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$status", PRESENT_STATUSES]},
                                    {"$lte": [{"$isoDayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, 5]},
                                ]
                            },
                            {"$cond": [{"$eq": [{"$ifNull": ["$half_day", False]}, True]}, 0.5, 1]},
                            0,
                        ]
                    }
                },
                "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
                "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
                "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
            }
        },
    ]
    rows = list(db.attendance_logs.aggregate(pipeline))
    r = rows[0] if rows else {}

    present_days = float(r.get("present_days", 0))
    attendance_pct = None
    if working_days > 0:
        pct = Decimal(str(present_days)) / Decimal(working_days) * 100
        attendance_pct = float(pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": int(r.get("leave_days", 0)),
        "late_count": int(r.get("late_count", 0)),
        "total_late_minutes": int(r.get("total_late_minutes", 0)),
        "total_overtime_minutes": int(r.get("total_overtime_minutes", 0)),
        "attendance_pct": attendance_pct,
    }


@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=MONTH_PATTERN),
    department: Optional[str] = None,
):

    first, last = month_bounds(month)
    emp_filter = {"joined_on": {"$lte": last.isoformat()}}
    if department is not None:
        emp_filter["department"] = department

    has_wh = {"$and": [{"$in": ["$logs.status", PRESENT_STATUSES]}, {"$isNumber": "$logs.work_hours"}]}
    pipeline = [
        {"$match": emp_filter},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$code"]},
                                    {"$gte": ["$date", first.isoformat()]},
                                    {"$lte": ["$date", last.isoformat()]},
                                ]
                            }
                        }
                    }
                ],
                "as": "logs",
            }
        },
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {
            "$group": {
                "_id": "$department",
                "emps": {"$addToSet": "$emp_code"},
                "present_days": {"$sum": present_value_expr("$logs.")},
                "wh_sum": {"$sum": {"$cond": [has_wh, "$logs.work_hours", 0]}},
                "wh_count": {"$sum": {"$cond": [has_wh, 1, 0]}},
                "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]}, 1, 0]}},
                "total_late_minutes": {"$sum": {"$ifNull": ["$logs.late_minutes", 0]}},
                "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}},
                "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    items = []
    for r in db.employees.aggregate(pipeline):
        avg = None
        if r["wh_count"] > 0:
            mean = Decimal(str(round(r["wh_sum"], 2))) / Decimal(r["wh_count"])
            avg = float(mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        items.append(
            {
                "department": r["_id"],
                "headcount": len(r["emps"]),
                "present_days": float(r["present_days"]),
                "avg_work_hours": avg,
                "late_count": int(r["late_count"]),
                "total_late_minutes": int(r["total_late_minutes"]),
                "leave_count": int(r["leave_count"]),
                "on_duty_count": int(r["on_duty_count"]),
            }
        )
    return {"month": month, "items": items}

@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=MONTH_PATTERN),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    first, last = month_bounds(month)
    pipeline = [
        {"$match": {"date": {"$gte": first.isoformat(), "$lte": last.isoformat()}}},
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
            }
        },
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "emp"}},
        {"$unwind": "$emp"},  # no preserve: logs of unknown employees are dropped
    ]
    if department is not None:
        pipeline.append({"$match": {"emp.department": department}})  # rank inside the department only
    pipeline += [
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$emp.name",
                "department": "$emp.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
    ]
    items = [
        {
            "rank": int(r["rank"]),
            "emp_code": r["emp_code"],
            "name": r["name"],
            "department": r["department"],
            "total_late_minutes": int(r["total_late_minutes"]),
            "late_count": int(r["late_count"]),
        }
        for r in db.attendance_logs.aggregate(pipeline)
    ]
    return {"month": month, "items": items}

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
    date_from: Optional[date_type] = None,
    date_to: Optional[date_type] = None,
    status: Optional[AnyStatus] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")

    q = {}
    if emp_code is not None:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from.isoformat()
        if date_to:
            q["date"]["$lte"] = date_to.isoformat()
    if status is not None:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)
    cursor = (
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", DESCENDING), ("emp_code", ASCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [attendance_to_api(d) for d in cursor],
        "total": total,
        "page": page,
        "page_size": page_size,
    }

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")

    if body.punched_at is not None:
        ts = millis_to_utc(body.punched_at)
    else:
        ts = datetime.now(timezone.utc).replace(microsecond=0)

    # most recent record whose punch_in is at or before punched_at
    # (null punch_in, i.e. ABSENT/LEAVE, never matches $lte)
    rec = db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "punch_in": {"$lte": ts}},
        sort=[("punch_in", DESCENDING)],
    )
    if rec is None:
        raise HTTPException(404, "no punch-in found")
    if rec.get("punch_out") is not None:
        raise HTTPException(409, "already punched out")

    punch_in_ts = rec["punch_in"]
    if ts <= punch_in_ts or ts - punch_in_ts > timedelta(hours=24):
        raise HTTPException(422, "punched_at must be after punch_in and within 24 hours of it")

    work_hours = compute_work_hours(punch_in_ts, ts)
    overtime = compute_overtime(ts, emp["shift_start"], emp["shift_end"], rec["date"])

    updated = db.attendance_logs.find_one_and_update(
        {
            "emp_code": body.emp_code,
            "date": rec["date"],
            "punch_in": punch_in_ts,
            "punch_out": None,  # matches null or missing: only an open record
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime,
                "half_day": work_hours < 4.5,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:  # someone else closed it between our read and our write
        raise HTTPException(409, "already punched out")

    return attendance_to_api(updated)

@app.patch("/attendance/{emp_code}/{date}")
def regularize(emp_code: str, date: date_type, body: RegularizeIn):
    date_str = date.isoformat()
    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")
    rec = db.attendance_logs.find_one({"emp_code": emp_code, "date": date_str})
    if rec is None:
        raise HTTPException(404, "no record for that date")

    old_status = rec["status"]
    old_in = rec.get("punch_in")
    old_out = rec.get("punch_out")

    # 1) the final status and punch times
    new_status = body.status if body.status is not None else old_status
    if new_status in ("ABSENT", "LEAVE"):
        if body.punch_in is not None or body.punch_out is not None:
            raise HTTPException(422, "ABSENT/LEAVE cannot have punch times")
        new_in, new_out = None, None
    else:
        new_in = millis_to_utc(body.punch_in) if body.punch_in is not None else old_in
        new_out = millis_to_utc(body.punch_out) if body.punch_out is not None else old_out
        if new_in is None:
            raise HTTPException(422, "a presence status requires a punch_in")

    if new_status == old_status and new_in == old_in and new_out == old_out:
        raise HTTPException(422, "request changes nothing")

    # 2) validate and recompute the derived fields (R2-R5)
    if new_status in ("ABSENT", "LEAVE"):
        derived = {"late_minutes": 0, "work_hours": None, "overtime_minutes": 0, "half_day": False}
    else:
        att_date, late = attendance_day_and_late(new_in, emp["shift_start"], emp["shift_end"])
        if body.punch_in is not None and att_date != date_str:
            raise HTTPException(422, "punch_in must stay on the record's attendance date")
        if new_out is None:
            derived = {"late_minutes": late, "work_hours": None, "overtime_minutes": 0, "half_day": False}
        else:
            if new_out <= new_in or new_out - new_in > timedelta(hours=24):
                raise HTTPException(422, "punch_out must be after punch_in and within 24 hours")
            hours = compute_work_hours(new_in, new_out)
            derived = {
                "late_minutes": late,
                "work_hours": hours,
                "overtime_minutes": compute_overtime(new_out, emp["shift_start"], emp["shift_end"], date_str),
                "half_day": hours < 4.5,
            }

    # 3) only the fields that actually changed go into history
    new_doc = {"status": new_status, "punch_in": new_in, "punch_out": new_out, **derived}
    old_doc = {
        "status": old_status,
        "punch_in": old_in,
        "punch_out": old_out,
        "work_hours": rec.get("work_hours"),
        "late_minutes": rec.get("late_minutes", 0),
        "overtime_minutes": rec.get("overtime_minutes", 0),
        "half_day": rec.get("half_day", False),
    }
    changes = {
        k: {"from": old_doc[k], "to": new_doc[k]} for k in new_doc if new_doc[k] != old_doc[k]
    }
    entry = {
        "at": datetime.now(timezone.utc),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    # 4) write only if the record is exactly as we read it (optimistic locking)
    cond = {
        "emp_code": emp_code,
        "date": date_str,
        "status": old_status,
        "punch_in": old_in,
        "punch_out": old_out,
    }
    old_history = rec.get("history") or []
    if old_history:
        cond["history"] = {"$size": len(old_history)}
    else:
        cond["$or"] = [{"history": {"$exists": False}}, {"history": {"$size": 0}}]

    updated = db.attendance_logs.find_one_and_update(
        cond,
        {"$set": new_doc, "$push": {"history": entry}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "record was modified concurrently, please retry")
    return attendance_to_api(updated)


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
