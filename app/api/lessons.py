from datetime import date as Date

from fastapi import APIRouter, Query
from sqlalchemy import select

from app import models as m
from app import schemas as s
from app.common import (
    DB,
    Page,
    active,
    apply_values,
    audit,
    dump,
    fail,
    get,
    paginate,
    patch_values,
    save,
    today,
)
from app.security import Current, Staff
from app.services import (
    eligible,
    generate_lessons,
    group_access,
    month_bounds,
    notify,
    validate_lesson,
)

router = APIRouter(tags=["Darslar / Davomat"])


@router.get("/lessons")
def lessons(
    db: DB, user: Current, paging: Page, date: Date | None = None, teacher_id: int | None = None
):
    stmt = select(m.Lesson).join(m.Group)
    if date:
        stmt = stmt.where(m.Lesson.date == date)
    if user.role == "teacher":
        stmt = stmt.where(m.Group.teacher_id == user.id)
    if teacher_id:
        stmt = stmt.where(m.Group.teacher_id == teacher_id)
    return paginate(db, stmt.order_by(m.Lesson.date, m.Lesson.start_time, m.Lesson.id), paging)


@router.post("/lessons/generate")
def generate(data: s.DateRange, db: DB, user: Staff):
    if (data.ends_on - data.starts_on).days > 31:
        fail("range_too_large", "Eng ko'pi 31 kun", 422)
    count = generate_lessons(db, data.starts_on, data.ends_on)
    audit(db, user, "generate_lessons", user)
    return {"created": count}


@router.post("/lessons", status_code=201)
def create_lesson(data: s.LessonCreate, db: DB, user: Staff):
    validate_lesson(db, data.model_dump())
    return save(db, user, m.Lesson(**data.model_dump()))


def accessible(db, user, id, lock=False):
    lesson = get(db, m.Lesson, id, lock)
    group_access(db, user, lesson.group_id)
    return lesson


@router.get("/lessons/{id}")
def detail(id: int, db: DB, user: Current):
    return dump(accessible(db, user, id))


@router.patch("/lessons/{id}")
def update_lesson(id: int, data: s.LessonPatch, db: DB, user: Staff):
    obj = get(db, m.Lesson, id, True)
    if db.scalar(select(m.Attendance.id).where(m.Attendance.lesson_id == id).limit(1)):
        fail("attendance_exists", "Davomat yozilgan darsni ko'chirish mumkin emas")
    values = patch_values(obj, data, s.LessonCreate)
    if values["group_id"] != obj.group_id:
        fail("group_change_forbidden", "Darsni boshqa guruhga o'tkazish mumkin emas", 422)
    validate_lesson(db, values, id)
    apply_values(obj, values)
    return save(db, user, obj, "update")


@router.get("/lessons/{id}/attendance")
def attendance(id: int, db: DB, user: Current, paging: Page):
    accessible(db, user, id)
    return paginate(
        db,
        select(m.Attendance).where(m.Attendance.lesson_id == id).order_by(m.Attendance.student_id),
        paging,
    )


@router.put("/lessons/{id}/attendance")
def put_attendance(id: int, data: s.AttendancePut, db: DB, user: Current):
    lesson = accessible(db, user, id, True)
    active(get(db, m.Group, lesson.group_id))
    if lesson.status == "cancelled" or lesson.date > today():
        fail("invalid_lesson", "Bekor qilingan yoki kelajak darsiga davomat yozilmaydi")
    enrollments = db.scalars(
        select(m.Enrollment).where(m.Enrollment.group_id == lesson.group_id)
    ).all()
    allowed = {e.student_id for e in enrollments if eligible(db, e, lesson.date)}
    if {r.student_id for r in data.records} != allowed:
        fail("invalid_roster", "Davomat dars kunidagi barcha faol o'quvchilarni qamrasin", 422)
    for record in data.records:
        obj = db.scalar(
            select(m.Attendance).where(
                m.Attendance.lesson_id == id, m.Attendance.student_id == record.student_id
            )
        )
        if obj is None:
            obj = m.Attendance(lesson_id=id, **record.model_dump())
            db.add(obj)
        else:
            apply_values(obj, record.model_dump())
        if record.status == "absent":
            notify(db, record.student_id, "absence", f"absence:{id}:{record.student_id}")
        else:
            pending = db.scalar(
                select(m.Notification)
                .where(
                    m.Notification.dedupe_key == f"absence:{id}:{record.student_id}",
                    m.Notification.status == "pending",
                )
                .with_for_update()
            )
            if pending:
                pending.status = "cancelled"
    lesson.status = "completed"
    audit(db, user, "attendance", lesson)
    return {"saved": len(data.records)}


@router.get("/groups/{id}/attendance")
def group_attendance(
    id: int,
    db: DB,
    user: Current,
    paging: Page,
    month: str = Query(pattern=r"^20[0-9]{2}-(0[1-9]|1[0-2])$"),
):
    group_access(db, user, id)
    first, last = month_bounds(month)
    return paginate(
        db,
        select(m.Attendance)
        .join(m.Lesson)
        .where(m.Lesson.group_id == id, m.Lesson.date.between(first, last))
        .order_by(m.Lesson.date, m.Attendance.student_id),
        paging,
    )
