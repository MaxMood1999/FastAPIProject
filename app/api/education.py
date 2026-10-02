from datetime import date
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import func, or_, select

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
    balance,
    balance_statement,
    enroll,
    ensure_unbilled,
    group_access,
    open_enrollment,
    student_access,
    validate_group,
)

router = APIRouter(tags=["O'quv jarayoni"])


def student_query(user):
    stmt = select(m.Student)
    if user.role == "teacher":
        stmt = stmt.where(
            m.Student.id.in_(
                select(m.Enrollment.student_id)
                .join(m.Group)
                .where(
                    m.Group.teacher_id == user.id,
                    m.Group.is_active.is_(True),
                    open_enrollment(),
                )
            )
        )
    return stmt


@router.get("/students")
def students(
    db: DB,
    user: Current,
    paging: Page,
    search: str | None = None,
    status: Literal["active", "archived"] | None = None,
    group_id: int | None = None,
    has_debt: bool | None = None,
):
    stmt = student_query(user)
    if search:
        stmt = stmt.where(
            or_(
                m.Student.full_name.icontains(search, autoescape=True),
                m.Student.phone.contains(search, autoescape=True),
            )
        )
    if status:
        stmt = stmt.where(m.Student.is_active.is_(status == "active"))
    if group_id:
        group_access(db, user, group_id)
        stmt = stmt.where(
            m.Student.id.in_(
                select(m.Enrollment.student_id).where(
                    m.Enrollment.group_id == group_id, open_enrollment()
                )
            )
        )
    if has_debt is not None:
        if user.role == "teacher":
            fail("forbidden", "Moliyaviy filtr uchun ruxsat yo'q", 403)
        balances = balance_statement().subquery()
        stmt = stmt.where(
            m.Student.id.in_(select(balances.c.student_id).where((balances.c.debt > 0) == has_debt))
        )
    return paginate(db, stmt.order_by(m.Student.id), paging)


@router.post("/students", status_code=201)
def create_student(data: s.StudentCreate, db: DB, user: Staff):
    return save(db, user, m.Student(**data.model_dump()))


@router.get("/students/{id}")
def student_detail(id: int, db: DB, user: Current):
    obj = student_access(db, user, id)
    groups = select(m.Group).join(m.Enrollment).where(m.Enrollment.student_id == id)
    attendance = (
        select(m.Attendance).join(m.Lesson).join(m.Group).where(m.Attendance.student_id == id)
    )
    if user.role == "teacher":
        groups = groups.where(m.Group.teacher_id == user.id)
        attendance = attendance.where(m.Group.teacher_id == user.id)
    records = db.scalars(attendance).all()
    result = dump(obj)
    result["groups"] = [dump(g) for g in db.scalars(groups)]
    result["parents"] = [
        dump(p) for p in db.scalars(select(m.Parent).where(m.Parent.student_id == id))
    ]
    result["attendance_percent"] = (
        round(100 * sum(r.status in ("present", "late") for r in records) / len(records), 2)
        if records
        else None
    )
    if user.role != "teacher":
        result.update(balance(db, id))
    return result


@router.patch("/students/{id}")
def update_student(id: int, data: s.StudentPatch, db: DB, user: Staff):
    obj = active(get(db, m.Student, id, True))
    apply_values(obj, patch_values(obj, data, s.StudentCreate))
    return save(db, user, obj, "update")


@router.delete("/students/{id}")
def archive_student(id: int, db: DB, user: Staff):
    obj = get(db, m.Student, id, True)
    if db.scalar(
        select(m.Enrollment.id).where(m.Enrollment.student_id == id, open_enrollment()).limit(1)
    ):
        fail("active_enrollments", "Avval o'quvchini faol guruhlardan chiqaring")
    obj.is_active = False
    return save(db, user, obj, "archive")


@router.post("/students/{id}/parents", status_code=201)
def parent(id: int, data: s.ParentCreate, db: DB, user: Staff):
    active(get(db, m.Student, id))
    return save(db, user, m.Parent(student_id=id, **data.model_dump()))


@router.get("/students/{id}/attendance")
def student_attendance(id: int, db: DB, user: Current, paging: Page):
    student_access(db, user, id)
    stmt = select(m.Attendance).join(m.Lesson).join(m.Group).where(m.Attendance.student_id == id)
    if user.role == "teacher":
        stmt = stmt.where(m.Group.teacher_id == user.id)
    return paginate(db, stmt.order_by(m.Lesson.date.desc(), m.Attendance.id), paging)


@router.get("/students/{id}/payments")
def student_payments(id: int, db: DB, user: Staff, paging: Page):
    get(db, m.Student, id)
    return paginate(
        db,
        select(m.Payment).where(m.Payment.student_id == id).order_by(m.Payment.id.desc()),
        paging,
    )


@router.get("/students/{id}/balance")
def student_balance(id: int, db: DB, user: Staff):
    get(db, m.Student, id)
    return balance(db, id)


@router.post("/students/{id}/discounts", status_code=201)
def discount(id: int, data: s.DiscountCreate, db: DB, user: Staff):
    active(get(db, m.Student, id, True))
    ensure_unbilled(db, id, data.starts_on, data.ends_on)
    overlap = db.scalar(
        select(m.Discount.id).where(
            m.Discount.student_id == id,
            m.Discount.starts_on <= data.ends_on,
            m.Discount.ends_on >= data.starts_on,
        )
    )
    if overlap:
        fail("discount_overlap", "Bu muddat uchun chegirma mavjud")
    return save(db, user, m.Discount(student_id=id, **data.model_dump()))


@router.get("/courses")
def courses(db: DB, user: Current, paging: Page):
    return paginate(db, select(m.Course).order_by(m.Course.id), paging)


@router.post("/courses", status_code=201)
def create_course(data: s.CourseCreate, db: DB, user: Staff):
    return save(db, user, m.Course(**data.model_dump()))


@router.patch("/courses/{id}")
def update_course(id: int, data: s.CoursePatch, db: DB, user: Staff):
    obj = active(get(db, m.Course, id, True))
    apply_values(obj, patch_values(obj, data, s.CourseCreate))
    return save(db, user, obj, "update")


@router.delete("/courses/{id}")
def archive_course(id: int, db: DB, user: Staff):
    obj = get(db, m.Course, id, True)
    if db.scalar(
        select(m.Group.id).where(m.Group.course_id == id, m.Group.is_active.is_(True)).limit(1)
    ):
        fail("course_has_groups", "Kursda faol guruhlar bor")
    obj.is_active = False
    return save(db, user, obj, "archive")


@router.get("/groups")
def groups(
    db: DB,
    user: Current,
    paging: Page,
    teacher_id: int | None = None,
    course_id: int | None = None,
    status: Literal["active", "archived"] | None = None,
):
    stmt = select(m.Group)
    if user.role == "teacher":
        stmt = stmt.where(m.Group.teacher_id == user.id)
    if teacher_id:
        stmt = stmt.where(m.Group.teacher_id == teacher_id)
    if course_id:
        stmt = stmt.where(m.Group.course_id == course_id)
    if status:
        stmt = stmt.where(m.Group.is_active.is_(status == "active"))
    return paginate(db, stmt.order_by(m.Group.id), paging)


@router.post("/groups", status_code=201)
def create_group(data: s.GroupCreate, db: DB, user: Staff):
    values = data.model_dump()
    validate_group(db, values)
    return save(db, user, m.Group(**values))


@router.get("/groups/{id}")
def group_detail(id: int, db: DB, user: Current):
    return dump(group_access(db, user, id))


@router.patch("/groups/{id}")
def update_group(id: int, data: s.GroupPatch, db: DB, user: Staff):
    obj = active(get(db, m.Group, id, True))
    values = patch_values(obj, data, s.GroupCreate)
    validate_group(db, values, id)
    count = db.scalar(
        select(func.count())
        .select_from(m.Enrollment)
        .where(m.Enrollment.group_id == id, open_enrollment())
    )
    if values["capacity"] < count:
        fail("capacity_too_small", "Sig'im o'quvchilar sonidan kam")
    schedule_fields = {
        "course_id",
        "teacher_id",
        "days",
        "start_time",
        "end_time",
        "room",
        "start_date",
        "end_date",
    }
    if any(values[k] != getattr(obj, k) for k in schedule_fields):
        if db.scalar(select(m.Lesson.id).where(m.Lesson.group_id == id).limit(1)) or db.scalar(
            select(m.Enrollment.id).where(m.Enrollment.group_id == id).limit(1)
        ):
            fail(
                "schedule_in_use",
                "Guruh ishlatilmoqda; darslarni alohida ko'chiring yoki yangi guruh oching",
            )
    apply_values(obj, values)
    return save(db, user, obj, "update")


@router.delete("/groups/{id}")
def archive_group(id: int, db: DB, user: Staff):
    obj = get(db, m.Group, id, True)
    if db.scalar(
        select(m.Enrollment.id).where(m.Enrollment.group_id == id, open_enrollment()).limit(1)
    ):
        fail("active_enrollments", "Guruhda faol o'quvchilar bor")
    obj.is_active = False
    for lesson in db.scalars(
        select(m.Lesson).where(
            m.Lesson.group_id == id, m.Lesson.date >= today(), m.Lesson.status == "scheduled"
        )
    ):
        lesson.status = "cancelled"
    return save(db, user, obj, "archive")


@router.get("/groups/{id}/students")
def group_students(id: int, db: DB, user: Current, paging: Page):
    group_access(db, user, id)
    return paginate(
        db,
        select(m.Student)
        .join(m.Enrollment)
        .where(m.Enrollment.group_id == id, open_enrollment())
        .order_by(m.Student.id),
        paging,
    )


@router.post("/groups/{id}/students", status_code=201)
def add_student(id: int, data: s.Enroll, db: DB, user: Staff):
    return save(db, user, enroll(db, id, data.student_id, data.joined_on))


@router.delete("/groups/{id}/students/{student_id}")
def remove_student(id: int, student_id: int, db: DB, user: Staff, left_on: date | None = None):
    get(db, m.Group, id, True)
    obj = db.scalar(
        select(m.Enrollment)
        .where(m.Enrollment.group_id == id, m.Enrollment.student_id == student_id)
        .with_for_update()
    )
    if not obj:
        fail("enrollment_not_found", "O'quvchi guruhda yo'q", 404)
    day = left_on or today()
    if day < obj.joined_on:
        fail("invalid_date", "Chiqish sanasi qabul sanasidan oldin", 422)
    if obj.left_on:
        return dump(obj)
    ensure_unbilled(db, student_id, day, date(2099, 12, 31), id)
    obj.left_on = day
    return save(db, user, obj, "leave")


@router.post("/groups/{id}/freeze/{student_id}", status_code=201)
def freeze(id: int, student_id: int, data: s.DateRange, db: DB, user: Staff):
    active(get(db, m.Group, id, True))
    obj = db.scalar(
        select(m.Enrollment)
        .where(m.Enrollment.group_id == id, m.Enrollment.student_id == student_id)
        .with_for_update()
    )
    if not obj or obj.left_on:
        fail("enrollment_not_found", "Faol qabul topilmadi", 404)
    if data.starts_on < obj.joined_on:
        fail("invalid_date", "Muzlatish qabul sanasidan oldin", 422)
    ensure_unbilled(db, student_id, data.starts_on, data.ends_on, id)
    if db.scalar(
        select(m.Freeze.id).where(
            m.Freeze.enrollment_id == obj.id,
            m.Freeze.starts_on <= data.ends_on,
            m.Freeze.ends_on >= data.starts_on,
        )
    ):
        fail("freeze_overlap", "Muzlatish muddatlari kesishadi")
    return save(db, user, m.Freeze(enrollment_id=obj.id, **data.model_dump()))


@router.get("/leads")
def leads(
    db: DB,
    user: Staff,
    paging: Page,
    status: Literal["new", "contacted", "trial", "enrolled", "lost"] | None = None,
):
    stmt = select(m.Lead)
    if status:
        stmt = stmt.where(m.Lead.status == status)
    return paginate(db, stmt.order_by(m.Lead.id.desc()), paging)


@router.post("/leads", status_code=201)
def create_lead(data: s.LeadCreate, db: DB, user: Staff):
    if data.course_id:
        active(get(db, m.Course, data.course_id))
    return save(db, user, m.Lead(**data.model_dump()))


@router.patch("/leads/{id}")
def update_lead(id: int, data: s.LeadPatch, db: DB, user: Staff):
    obj = get(db, m.Lead, id, True)
    if obj.student_id:
        fail("lead_converted", "Lid allaqachon o'quvchiga aylantirilgan")
    values = data.model_dump(exclude_unset=True)
    if "status" in values and values["status"] is None:
        fail("validation_error", "Status bo'sh bo'lmasin", 422)
    apply_values(obj, values)
    return save(db, user, obj, "update")


@router.post("/leads/{id}/convert", status_code=201)
def convert_lead(id: int, data: s.Convert, db: DB, user: Staff):
    obj = get(db, m.Lead, id, True)
    if obj.student_id:
        fail("lead_converted", "Lid allaqachon o'quvchiga aylantirilgan")
    group = active(get(db, m.Group, data.group_id, True))
    if obj.course_id and group.course_id != obj.course_id:
        fail("course_mismatch", "Guruh lid tanlagan kursga mos emas")
    student = m.Student(full_name=obj.full_name, phone=obj.phone, note=obj.note)
    db.add(student)
    db.flush()
    enroll(db, data.group_id, student.id)
    obj.student_id, obj.status = student.id, "enrolled"
    audit(db, user, "convert", obj)
    return save(db, user, student)
