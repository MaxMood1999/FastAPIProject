from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select

from app import models as m
from app import schemas as s
from app.common import (
    DB,
    Page,
    advisory_lock,
    audit,
    dump,
    fail,
    get,
    paginate,
    save,
)
from app.config import get_settings
from app.security import Staff
from app.services import debt_rows, generate_invoices, notify

router = APIRouter(tags=["Moliya"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)]


def payment_query(student_id=None, start=None, end=None, method=None):
    if start and end and end < start:
        fail("invalid_range", "Sana oralig'i noto'g'ri", 422)
    stmt = select(m.Payment)
    zone = ZoneInfo(get_settings().timezone)
    if student_id:
        stmt = stmt.where(m.Payment.student_id == student_id)
    if start:
        stmt = stmt.where(m.Payment.created_at >= datetime.combine(start, time.min, zone))
    if end:
        stmt = stmt.where(
            m.Payment.created_at < datetime.combine(end + timedelta(days=1), time.min, zone)
        )
    if method:
        stmt = stmt.where(m.Payment.method == method)
    return stmt.order_by(m.Payment.id.desc())


@router.get("/payments")
def payments(
    db: DB,
    user: Staff,
    paging: Page,
    student_id: int | None = None,
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    method: Literal["cash", "card", "transfer"] | None = None,
):
    return paginate(db, payment_query(student_id, start, end, method), paging)


@router.post("/payments", status_code=201)
def create_payment(data: s.PaymentCreate, db: DB, user: Staff, key: Key):
    advisory_lock(db, f"payment:{key}")
    existing = db.scalar(select(m.Payment).where(m.Payment.idempotency_key == key))
    if existing:
        if any(getattr(existing, k) != v for k, v in data.model_dump().items()):
            fail("idempotency_conflict", "Bu kalit boshqa so'rov uchun ishlatilgan")
        return dump(existing)
    get(db, m.Student, data.student_id, True)
    get(db, m.Group, data.group_id)
    if not db.scalar(
        select(m.Enrollment.id).where(
            m.Enrollment.student_id == data.student_id, m.Enrollment.group_id == data.group_id
        )
    ):
        fail("not_enrolled", "O'quvchi guruhda yo'q", 422)
    obj = m.Payment(**data.model_dump(), created_by=user.id, idempotency_key=key)
    result = save(db, user, obj)
    notify(db, data.student_id, "payment", f"payment:{obj.id}")
    return result


@router.get("/payments/{id}")
def payment(id: int, db: DB, user: Staff):
    obj = get(db, m.Payment, id)
    result = dump(obj)
    result["refunds"] = [
        dump(r)
        for r in db.scalars(select(m.Refund).where(m.Refund.payment_id == id).order_by(m.Refund.id))
    ]
    result["net_amount"] = obj.amount - sum(r["amount"] for r in result["refunds"])
    return result


@router.post("/payments/{id}/refund", status_code=201)
def refund(id: int, data: s.RefundCreate, db: DB, user: Staff, key: Key):
    advisory_lock(db, f"refund:{key}")
    existing = db.scalar(select(m.Refund).where(m.Refund.idempotency_key == key))
    if existing:
        if (
            existing.payment_id != id
            or existing.amount != data.amount
            or existing.reason != data.reason
        ):
            fail("idempotency_conflict", "Bu kalit boshqa so'rov uchun ishlatilgan")
        return dump(existing)
    obj = get(db, m.Payment, id, True)
    refunded = db.scalar(
        select(func.coalesce(func.sum(m.Refund.amount), 0)).where(m.Refund.payment_id == id)
    )
    if refunded + data.amount > obj.amount:
        fail("excess_refund", "Qaytarish summasi qolgan to'lovdan oshdi")
    return save(
        db,
        user,
        m.Refund(payment_id=id, **data.model_dump(), created_by=user.id, idempotency_key=key),
    )


@router.get("/payments/{id}/receipt")
def receipt(id: int, db: DB, user: Staff):
    result = payment(id, db, user)
    return {
        "receipt_number": f"CRM-{id:08d}",
        "currency": "UZS",
        "payment": result,
        "student": dump(get(db, m.Student, result["student_id"]), {"note", "address"}),
    }


@router.get("/debtors")
def debtors(db: DB, user: Staff, paging: Page):
    rows = debt_rows(db)
    start = (paging.page - 1) * paging.size
    return {
        "items": rows[start : start + paging.size],
        "total": len(rows),
        "page": paging.page,
        "size": paging.size,
    }


@router.get("/invoices")
def invoices(
    db: DB,
    user: Staff,
    paging: Page,
    student_id: int | None = None,
    period: str | None = Query(None, pattern=r"^20[0-9]{2}-(0[1-9]|1[0-2])$"),
):
    stmt = select(m.Invoice)
    if student_id:
        stmt = stmt.where(m.Invoice.student_id == student_id)
    if period:
        stmt = stmt.where(m.Invoice.period == period)
    return paginate(db, stmt.order_by(m.Invoice.id.desc()), paging)


@router.post("/invoices/generate")
def generate(data: s.Generate, db: DB, user: Staff):
    count = generate_invoices(db, data.period)
    audit(db, user, "generate_invoices", user)
    return {"created": count, "period": data.period}
