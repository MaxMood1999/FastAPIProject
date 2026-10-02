"""Run as a separate process: python -m app.worker. Safe with multiple workers."""

import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.common import APIError, advisory_lock, today
from app.config import get_settings
from app.db import get_engine
from app.services import (
    balance,
    debt_rows,
    generate_invoices,
    generate_lessons,
    invoice_debt,
    notify,
)

log = logging.getLogger(__name__)


def schedule(db):
    advisory_lock(db, "worker-schedule")
    current = today()
    try:
        with db.begin_nested():
            generate_lessons(db, current, current + timedelta(days=7))
    except APIError as exc:
        if exc.code != "schedule_conflict":
            raise
        log.warning("Automatic lesson generation needs schedule conflict resolution")
    generate_invoices(db, current.strftime("%Y-%m"))
    week = current.strftime("%G-%V")
    for invoice in db.scalars(
        select(m.Invoice).where(m.Invoice.due_date == current + timedelta(days=3))
    ):
        if invoice_debt(db, invoice) > 0 and balance(db, invoice.student_id)["debt"] > 0:
            notify(db, invoice.student_id, "due", f"due:{invoice.id}")
    for row in debt_rows(db):
        if row["overdue_days"] > 0 and db.get(m.Student, row["student_id"]).is_active:
            notify(db, row["student_id"], "debt", f"debt:{row['student_id']}:{week}")


def deliver_batch(db, client):
    cfg = get_settings()
    if not cfg.telegram_bot_token:
        return 0  # Remain pending until credentials are configured.
    rows = db.scalars(
        select(m.Notification)
        .where(m.Notification.status == "pending", m.Notification.next_attempt_at <= m.utcnow())
        .order_by(m.Notification.id)
        .limit(50)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        student = db.get(m.Student, row.student_id)
        if not student.telegram_chat_id:
            row.error = "telegram_not_linked"
            row.next_attempt_at = m.utcnow() + timedelta(hours=1)
            continue
        row.attempts += 1
        try:
            response = client.post(
                f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
                json={"chat_id": student.telegram_chat_id, "text": row.text},
                timeout=10,
            )
            response.raise_for_status()
            if response.json().get("ok") is not True:
                raise ValueError("telegram_rejected")
            row.status, row.sent_at, row.error = "sent", m.utcnow(), None
        except (httpx.HTTPError, ValueError):
            # Never persist exceptions containing the bot token or request URL.
            row.error = "telegram_delivery_failed"
            row.status = "failed" if row.attempts >= 5 else "pending"
            row.next_attempt_at = m.utcnow() + timedelta(minutes=2**row.attempts)
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    last_schedule = None
    with httpx.Client() as client:
        while True:
            try:
                if last_schedule != today():
                    with Session(get_engine()) as db, db.begin():
                        schedule(db)
                    last_schedule = today()
                with Session(get_engine()) as db, db.begin():
                    deliver_batch(db, client)
            except Exception as exc:
                log.error("Worker tick failed: %s", type(exc).__name__)
            time.sleep(10)


if __name__ == "__main__":
    main()
