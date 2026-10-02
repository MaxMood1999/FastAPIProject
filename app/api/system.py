import secrets
from datetime import date, timedelta
from io import BytesIO
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response
from openpyxl import Workbook
from sqlalchemy import func, select

from app import models as m
from app import schemas as s
from app.api.finance import payment_query
from app.common import DB, Page, active, audit, fail, get, paginate, today
from app.config import get_settings
from app.security import Admin, Staff, digest
from app.services import debt_rows, enqueue, group_access, open_enrollment, setting

router = APIRouter(tags=["Tizim / Hisobotlar / Telegram"])


@router.get("/version")
def version():
    return {"version": "1.0.0", "api": "v1"}


@router.get("/settings")
def settings(db: DB, user: Admin):
    return {
        **setting(db, "center", s.CenterSettings).model_dump(),
        "telegram_configured": bool(get_settings().telegram_bot_token),
    }


def put_setting(db, user, key, data):
    obj = db.get(m.Setting, key)
    if obj:
        obj.value = data.model_dump()
    else:
        db.add(m.Setting(key=key, value=data.model_dump()))
    audit(db, user, f"update_{key}", user)
    return data.model_dump()


@router.put("/settings")
def update_settings(data: s.CenterSettings, db: DB, user: Admin):
    return put_setting(db, user, "center", data)


@router.get("/audit-log")
def audit_log(db: DB, user: Admin, paging: Page):
    return paginate(db, select(m.Audit).order_by(m.Audit.id.desc()), paging)


@router.get("/notifications/templates")
def templates(db: DB, user: Staff):
    return setting(db, "templates", s.Templates)


@router.put("/notifications/templates")
def update_templates(data: s.Templates, db: DB, user: Staff):
    return put_setting(db, user, "templates", data)


@router.get("/notifications")
def notifications(db: DB, user: Staff, paging: Page):
    return paginate(db, select(m.Notification).order_by(m.Notification.id.desc()), paging)


@router.post("/notifications/send", status_code=202)
def send_notification(data: s.NotificationSend, db: DB, user: Staff):
    if data.student_id:
        active(get(db, m.Student, data.student_id))
        ids = [data.student_id]
    else:
        active(group_access(db, user, data.group_id))
        ids = db.scalars(
            select(m.Enrollment.student_id).where(
                m.Enrollment.group_id == data.group_id, open_enrollment()
            )
        ).all()
    batch = secrets.token_hex(16)
    for id in ids:
        enqueue(db, id, data.text, f"manual:{batch}:{id}")
    audit(db, user, "queue_notifications", user)
    return {"queued": len(ids)}


@router.post("/students/{id}/telegram-link")
def telegram_link(id: int, db: DB, user: Staff):
    active(get(db, m.Student, id, True))
    cfg = get_settings()
    if not cfg.telegram_bot_username or not cfg.telegram_webhook_secret:
        fail("telegram_not_configured", "Telegram sozlanmagan", 503)
    for old in db.scalars(select(m.TelegramLink).where(m.TelegramLink.student_id == id)):
        old.used = True
    code = secrets.token_urlsafe(24)
    db.add(
        m.TelegramLink(
            student_id=id, code_hash=digest(code), expires_at=m.utcnow() + timedelta(minutes=30)
        )
    )
    audit(db, user, "telegram_link", get(db, m.Student, id))
    return {"url": f"https://t.me/{cfg.telegram_bot_username}?start={code}", "expires_in": 1800}


@router.post("/telegram/webhook")
def webhook(
    data: dict,
    db: DB,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
):
    expected = get_settings().telegram_webhook_secret
    if not expected or not secret or not secrets.compare_digest(secret, expected):
        fail("forbidden", "Webhook kaliti noto'g'ri", 403)
    message = data.get("message")
    if not isinstance(message, dict):
        return {"ok": True}
    chat, text = message.get("chat"), message.get("text")
    if not isinstance(chat, dict) or chat.get("type") != "private" or not isinstance(text, str):
        return {"ok": True}
    pieces = text.split()
    if len(pieces) != 2 or pieces[0] != "/start":
        return {"ok": True}
    row = db.scalar(
        select(m.TelegramLink)
        .where(m.TelegramLink.code_hash == digest(pieces[1]))
        .with_for_update()
    )
    if not row or row.used or row.expires_at <= m.utcnow():
        return {"ok": True}
    chat_id = chat.get("id")
    if not isinstance(chat_id, int) or isinstance(chat_id, bool) or chat_id <= 0:
        return {"ok": True}
    student = active(get(db, m.Student, row.student_id, True))
    student.telegram_chat_id, row.used = str(chat_id), True
    audit(db, None, "telegram_linked", student)
    return {"ok": True}


@router.get("/dashboard")
def dashboard(db: DB, user: Staff):
    current = today()
    payments = db.scalars(payment_query(start=current.replace(day=1), end=current)).all()
    refunds = db.scalar(
        select(func.coalesce(func.sum(m.Refund.amount), 0)).where(
            func.date(m.Refund.created_at.op("AT TIME ZONE")(get_settings().timezone))
            >= current.replace(day=1),
            func.date(m.Refund.created_at.op("AT TIME ZONE")(get_settings().timezone)) <= current,
        )
    )
    return {
        "active_students": db.scalar(
            select(func.count()).select_from(m.Student).where(m.Student.is_active.is_(True))
        ),
        "today_lessons": db.scalar(
            select(func.count())
            .select_from(m.Lesson)
            .where(m.Lesson.date == current, m.Lesson.status != "cancelled")
        ),
        "monthly_income": sum(p.amount for p in payments) - refunds,
        "total_debt": sum(r["debt"] for r in debt_rows(db)),
    }


@router.get("/reports/income")
def income(
    db: DB,
    user: Staff,
    start: date = Query(alias="from"),
    end: date = Query(alias="to"),
    interval: Literal["day", "month"] = "day",
):
    if end < start or (end - start).days > 366:
        fail("invalid_range", "Hisobot oralig'i 0–366 kun bo'lsin", 422)
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(get_settings().timezone)
    values = {}

    def add(when, amount, refund=False):
        day = when.astimezone(zone).date()
        if start <= day <= end:
            key = day.strftime("%Y-%m" if interval == "month" else "%Y-%m-%d")
            row = values.setdefault(key, {"period": key, "received": 0, "refunded": 0, "net": 0})
            row["refunded" if refund else "received"] += amount
            row["net"] += -amount if refund else amount

    for payment in db.scalars(payment_query(start=start, end=end)):
        add(payment.created_at, payment.amount)
    for refund in db.scalars(
        select(m.Refund).where(
            func.date(m.Refund.created_at.op("AT TIME ZONE")(get_settings().timezone)).between(
                start, end
            )
        )
    ):
        add(refund.created_at, refund.amount, True)
    return {
        "items": [values[k] for k in sorted(values)],
        "total_net": sum(r["net"] for r in values.values()),
    }


@router.get("/reports/debts")
def debts(db: DB, user: Staff, paging: Page):
    rows = debt_rows(db)
    start = (paging.page - 1) * paging.size
    return {
        "items": rows[start : start + paging.size],
        "total": len(rows),
        "page": paging.page,
        "total_debt": sum(r["debt"] for r in rows),
    }


@router.get("/reports/attendance")
def attendance_report(db: DB, user: Staff, paging: Page):
    result = paginate(db, select(m.Group).order_by(m.Group.id), paging)
    for row in result["items"]:
        records = db.scalars(
            select(m.Attendance).join(m.Lesson).where(m.Lesson.group_id == row["id"])
        ).all()
        row["attendance_percent"] = (
            round(100 * sum(r.status in ("present", "late") for r in records) / len(records), 2)
            if records
            else None
        )
    return result


@router.get("/reports/teachers")
def teachers_report(db: DB, user: Admin, paging: Page):
    result = paginate(
        db, select(m.User).where(m.User.role == "teacher").order_by(m.User.id), paging
    )
    for row in result["items"]:
        groups = db.scalars(
            select(m.Group).where(m.Group.teacher_id == row["id"], m.Group.is_active.is_(True))
        ).all()
        row["groups_count"] = len(groups)
        row["weekly_minutes"] = sum(
            (
                (g.end_time.hour * 60 + g.end_time.minute)
                - (g.start_time.hour * 60 + g.start_time.minute)
            )
            * len(g.days)
            for g in groups
        )
    return result


@router.get("/reports/export")
def export(
    db: DB,
    user: Staff,
    type: Literal["payments"] = "payments",
    format: Literal["xlsx"] = "xlsx",
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
):
    stmt = payment_query(start=start, end=end)
    if db.scalar(select(func.count()).select_from(stmt.subquery())) > 10000:
        fail("export_too_large", "Sana filtrini toraytiring: eng ko'pi 10000 yozuv", 422)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Payments")
    sheet.append(["ID", "Student ID", "Group ID", "Amount UZS", "Method", "Period", "Note"])
    for p in db.scalars(stmt):
        note = p.note or ""
        # Prevent spreadsheet formula injection from user-authored cells.
        if note.startswith(("=", "+", "-", "@", "\t", "\r")):
            note = "'" + note
        sheet.append([p.id, p.student_id, p.group_id, p.amount, p.method, p.period, note])
    output = BytesIO()
    workbook.save(output)
    return Response(
        output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="payments.xlsx"'},
    )
