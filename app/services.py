import calendar
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app import models as m
from app.common import active, advisory_lock, fail, get, today
from app.schemas import CenterSettings, Templates

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def open_enrollment():
    return or_(m.Enrollment.left_on.is_(None), m.Enrollment.left_on > today())


def month_bounds(period):
    year, month = map(int, period.split("-"))
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def group_access(db, user, id, lock=False):
    group = get(db, m.Group, id, lock)
    if user.role == "teacher" and group.teacher_id != user.id:
        fail("forbidden", "Bu guruh uchun ruxsat yo'q", 403)
    return group


def student_access(db, user, id):
    student = get(db, m.Student, id)
    if user.role == "teacher":
        found = db.scalar(
            select(m.Enrollment.id)
            .join(m.Group)
            .where(
                m.Enrollment.student_id == id,
                m.Group.teacher_id == user.id,
                m.Group.is_active.is_(True),
                open_enrollment(),
            )
        )
        if found is None:
            fail("forbidden", "Bu o'quvchi uchun ruxsat yo'q", 403)
    return student


def eligible(db, enrollment, day):
    if day < enrollment.joined_on or (enrollment.left_on and day >= enrollment.left_on):
        return False
    return not db.scalar(
        select(m.Freeze.id).where(
            m.Freeze.enrollment_id == enrollment.id,
            m.Freeze.starts_on <= day,
            m.Freeze.ends_on >= day,
        )
    )


def enroll(db, group_id, student_id, joined_on=None):
    group = active(get(db, m.Group, group_id, True))
    active(get(db, m.Student, student_id, True))
    old = db.scalar(
        select(m.Enrollment).where(
            m.Enrollment.group_id == group_id, m.Enrollment.student_id == student_id
        )
    )
    if old:
        fail("already_enrolled", "Bu guruhda o'quvchi uchun yozuv mavjud")
    count = db.scalar(
        select(func.count())
        .select_from(m.Enrollment)
        .where(m.Enrollment.group_id == group_id, open_enrollment())
    )
    if count >= group.capacity:
        fail("group_full", "Guruhda bo'sh joy yo'q")
    joined = joined_on or max(today(), group.start_date)
    if joined < group.start_date or (group.end_date and joined > group.end_date):
        fail("invalid_enrollment_date", "Qabul sanasi guruh muddati ichida bo'lsin", 422)
    obj = m.Enrollment(group_id=group_id, student_id=student_id, joined_on=joined)
    db.add(obj)
    db.flush()
    return obj


def validate_group(db, values, exclude_id=None):
    advisory_lock(db, "schedule")
    active(get(db, m.Course, values["course_id"], True))
    teacher = active(get(db, m.User, values["teacher_id"], True))
    if teacher.role != "teacher":
        fail("not_teacher", "Xodim o'qituvchi bo'lishi kerak", 422)
    candidates = db.scalars(
        select(m.Group).where(
            m.Group.is_active.is_(True),
            or_(m.Group.teacher_id == teacher.id, m.Group.room == values["room"]),
            m.Group.start_time < values["end_time"],
            m.Group.end_time > values["start_time"],
        )
    )
    for other in candidates:
        if other.id == exclude_id or not set(other.days) & set(values["days"]):
            continue
        if other.end_date and other.end_date < values["start_date"]:
            continue
        if values["end_date"] and values["end_date"] < other.start_date:
            continue
        fail("schedule_conflict", "Xona yoki o'qituvchi vaqti band")


def validate_lesson(db, values, exclude_id=None):
    advisory_lock(db, "schedule")
    group = active(get(db, m.Group, values["group_id"]))
    if values["date"] < group.start_date or (group.end_date and values["date"] > group.end_date):
        fail("invalid_lesson_date", "Dars sanasi guruh muddati ichida bo'lsin", 422)
    if values["status"] == "cancelled":
        return
    conflict = db.scalar(
        select(m.Lesson.id)
        .join(m.Group)
        .where(
            m.Lesson.date == values["date"],
            m.Lesson.status != "cancelled",
            m.Lesson.start_time < values["end_time"],
            m.Lesson.end_time > values["start_time"],
            or_(m.Group.teacher_id == group.teacher_id, m.Group.room == group.room),
            m.Lesson.id != (exclude_id or 0),
        )
    )
    if conflict:
        fail("schedule_conflict", "Xona yoki o'qituvchi vaqti band")


def generate_lessons(db, start, end):
    advisory_lock(db, "schedule")
    count = 0
    for group in db.scalars(select(m.Group).where(m.Group.is_active.is_(True))):
        day = max(start, group.start_date)
        last = min(end, group.end_date or end)
        while day <= last:
            if DAYS[day.weekday()] in group.days:
                exists = db.scalar(
                    select(m.Lesson.id).where(
                        m.Lesson.group_id == group.id,
                        or_(
                            (m.Lesson.date == day) & (m.Lesson.start_time == group.start_time),
                            (m.Lesson.scheduled_date == day)
                            & (m.Lesson.scheduled_time == group.start_time),
                        ),
                    )
                )
                if not exists:
                    values = dict(
                        group_id=group.id,
                        date=day,
                        start_time=group.start_time,
                        end_time=group.end_time,
                        status="scheduled",
                    )
                    validate_lesson(db, values)
                    db.add(m.Lesson(**values, scheduled_date=day, scheduled_time=group.start_time))
                    db.flush()
                    count += 1
            day += timedelta(days=1)
    return count


def setting(db, key, schema):
    row = db.get(m.Setting, key)
    return schema.model_validate(row.value) if row else schema()


def enqueue(db, student_id, text, key):
    db.execute(
        insert(m.Notification)
        .values(student_id=student_id, text=text, dedupe_key=key)
        .on_conflict_do_update(
            index_elements=["dedupe_key"],
            set_={"status": "pending", "text": text, "next_attempt_at": m.utcnow()},
            where=m.Notification.status == "cancelled",
        )
    )


def notify(db, student_id, kind, key):
    enqueue(db, student_id, getattr(setting(db, "templates", Templates), kind), key)


def invoice_amount(db, enrollment, course, period):
    first, last = month_bounds(period)
    group = db.get(m.Group, enrollment.group_id)
    discounts = db.scalars(
        select(m.Discount).where(
            m.Discount.student_id == enrollment.student_id,
            m.Discount.starts_on <= last,
            m.Discount.ends_on >= first,
        )
    ).all()
    freezes = db.scalars(
        select(m.Freeze).where(
            m.Freeze.enrollment_id == enrollment.id,
            m.Freeze.starts_on <= last,
            m.Freeze.ends_on >= first,
        )
    ).all()
    # Daily proration, integer rational arithmetic, one final half-up rounding.
    hundredths = 0
    day = first
    while day <= last:
        if (
            day >= max(group.start_date, enrollment.joined_on)
            and (group.end_date is None or day <= group.end_date)
            and (enrollment.left_on is None or day < enrollment.left_on)
            and not any(f.starts_on <= day <= f.ends_on for f in freezes)
        ):
            day_price = course.monthly_price * 100
            for discount in discounts:
                if discount.starts_on <= day <= discount.ends_on:
                    reduction = (
                        course.monthly_price * discount.value
                        if discount.kind == "percent"
                        else discount.value * 100
                    )
                    day_price = max(0, day_price - reduction)
            hundredths += day_price
        day += timedelta(days=1)
    denominator = last.day * 100
    return (hundredths + denominator // 2) // denominator


def generate_invoices(db, period):
    advisory_lock(db, "billing")
    first, last = month_bounds(period)
    if first > today().replace(day=1):
        fail("future_billing", "Kelajak oyi uchun hisob yaratilmadi", 422)
    due_day = setting(db, "center", CenterSettings).payment_day
    count = 0
    rows = db.execute(
        select(m.Enrollment, m.Course)
        .join(m.Group, m.Group.id == m.Enrollment.group_id)
        .join(m.Course, m.Course.id == m.Group.course_id)
        .join(m.Student, m.Student.id == m.Enrollment.student_id)
        .where(
            m.Student.is_active.is_(True),
            m.Group.is_active.is_(True),
            m.Enrollment.joined_on <= last,
            or_(m.Enrollment.left_on.is_(None), m.Enrollment.left_on > first),
        )
    )
    for enrollment, course in rows:
        amount = invoice_amount(db, enrollment, course, period)
        result = db.execute(
            insert(m.Invoice)
            .values(
                student_id=enrollment.student_id,
                group_id=enrollment.group_id,
                period=period,
                amount=amount,
                due_date=first.replace(day=due_day),
            )
            .on_conflict_do_nothing(index_elements=["student_id", "group_id", "period"])
            .returning(m.Invoice.id)
        )
        count += result.scalar() is not None
    return count


def ensure_unbilled(db, student_id, start, end, group_id=None):
    advisory_lock(db, "billing")
    stmt = select(m.Invoice.id).where(
        m.Invoice.student_id == student_id,
        m.Invoice.period >= start.strftime("%Y-%m"),
        m.Invoice.period <= end.strftime("%Y-%m"),
    )
    if group_id:
        stmt = stmt.where(m.Invoice.group_id == group_id)
    if db.scalar(stmt.limit(1)):
        fail("period_already_billed", "Hisob yaratilgan oyga o'zgartirish kiritilmaydi")


def balance_statement():
    billed = (
        select(m.Invoice.student_id, func.sum(m.Invoice.amount).label("amount"))
        .group_by(m.Invoice.student_id)
        .subquery()
    )
    paid = (
        select(m.Payment.student_id, func.sum(m.Payment.amount).label("amount"))
        .group_by(m.Payment.student_id)
        .subquery()
    )
    refunded = (
        select(m.Payment.student_id, func.sum(m.Refund.amount).label("amount"))
        .join(m.Refund)
        .group_by(m.Payment.student_id)
        .subquery()
    )
    invoiced = func.coalesce(billed.c.amount, 0)
    received = func.coalesce(paid.c.amount, 0)
    returned = func.coalesce(refunded.c.amount, 0)
    return (
        select(
            m.Student.id.label("student_id"),
            m.Student.full_name,
            invoiced.label("invoiced"),
            received.label("paid"),
            returned.label("refunded"),
            (received - returned - invoiced).label("balance"),
            func.greatest(0, invoiced - received + returned).label("debt"),
        )
        .outerjoin(billed, billed.c.student_id == m.Student.id)
        .outerjoin(paid, paid.c.student_id == m.Student.id)
        .outerjoin(refunded, refunded.c.student_id == m.Student.id)
    )


def balance(db, student_id):
    row = dict(db.execute(balance_statement().where(m.Student.id == student_id)).mappings().one())
    row.pop("full_name")
    return row


def debt_rows(db):
    balances = balance_statement().subquery()
    rows = [
        dict(r)
        for r in db.execute(
            select(balances).where(balances.c.debt > 0).order_by(balances.c.student_id)
        ).mappings()
    ]
    by_student = {}
    for invoice in db.scalars(
        select(m.Invoice)
        .where(m.Invoice.student_id.in_([r["student_id"] for r in rows]))
        .order_by(m.Invoice.due_date, m.Invoice.id)
    ):
        by_student.setdefault(invoice.student_id, []).append(invoice)
    for row in rows:
        credit = row["paid"] - row["refunded"]
        row["overdue_days"] = 0
        for invoice in by_student.get(row["student_id"], []):
            if credit >= invoice.amount:
                credit -= invoice.amount
            else:
                row["overdue_days"] = max(0, (today() - invoice.due_date).days)
                break
    return rows


def invoice_debt(db, invoice):
    payments = db.scalars(
        select(m.Payment).where(
            m.Payment.student_id == invoice.student_id,
            m.Payment.group_id == invoice.group_id,
            m.Payment.period == invoice.period,
        )
    ).all()
    paid = sum(p.amount for p in payments)
    refunds = db.scalar(
        select(func.coalesce(func.sum(m.Refund.amount), 0)).where(
            m.Refund.payment_id.in_([p.id for p in payments])
        )
    )
    return max(0, invoice.amount - paid + refunds)
