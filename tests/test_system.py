from datetime import timedelta
from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.common import today
from app.config import get_settings
from app.db import get_engine
from app.worker import deliver_batch, schedule


def test_settings_reports_export_and_audit(client, headers, world):
    h, sid = headers["admin"], world["student"]["id"]
    assert (
        client.put(
            "/api/v1/settings", headers=h, json={"name": "Test Center", "payment_day": 15}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/settings", headers=h).json()["name"] == "Test Center"
    assert client.put("/api/v1/settings", headers=h, json={"payment_day": 32}).status_code == 422
    p = client.post(
        "/api/v1/payments",
        headers={**h, "Idempotency-Key": "export-payment-key"},
        json={
            "student_id": sid,
            "group_id": world["group"]["id"],
            "amount": 100000,
            "period": world["period"],
            "method": "card",
            "note": '=HYPERLINK("https://invalid")',
        },
    )
    assert p.status_code == 201
    assert (
        client.post(
            f"/api/v1/payments/{p.json()['id']}/refund",
            headers={**h, "Idempotency-Key": "export-refund-key"},
            json={"amount": 10000, "reason": "test"},
        ).status_code
        == 201
    )
    day = today().isoformat()
    assert (
        client.get(f"/api/v1/reports/income?from={day}&to={day}", headers=h).json()["total_net"]
        == 90000
    )
    assert client.get("/api/v1/dashboard", headers=h).json()["monthly_income"] == 90000
    assert (
        client.get("/api/v1/reports/teachers", headers=h).json()["items"][0]["weekly_minutes"]
        == 270
    )
    assert client.get("/api/v1/reports/teachers", headers=headers["manager"]).status_code == 403
    assert client.get("/api/v1/reports/attendance", headers=h).json()["total"] == 1
    response = client.get("/api/v1/reports/export?type=payments&format=xlsx", headers=h)
    assert response.status_code == 200
    book = load_workbook(BytesIO(response.content))
    assert book.active["G2"].data_type == "s"
    assert book.active["G2"].value.startswith("'=")
    logs = client.get("/api/v1/audit-log?size=100", headers=h).json()["items"]
    assert any(r["entity"] == "payments" for r in logs)
    assert "password" not in str(logs)


def test_telegram_secure_single_use_link_and_queue(client, headers, world, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "telegram_bot_username", "test_bot")
    monkeypatch.setattr(cfg, "telegram_webhook_secret", "test-webhook-secret")
    h, sid = headers["admin"], world["student"]["id"]
    link = client.post(f"/api/v1/students/{sid}/telegram-link", headers=h)
    assert link.status_code == 200
    code = link.json()["url"].split("start=")[1]
    message = {"message": {"chat": {"id": 12345, "type": "private"}, "text": "/start " + code}}
    assert client.post("/api/v1/telegram/webhook", json=message).status_code == 403
    webhook_headers = {"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"}
    assert (
        client.post("/api/v1/telegram/webhook", headers=webhook_headers, json=message).status_code
        == 200
    )
    message["message"]["chat"]["id"] = 9999
    assert (
        client.post("/api/v1/telegram/webhook", headers=webhook_headers, json=message).status_code
        == 200
    )
    with Session(get_engine()) as db:
        assert db.get(m.Student, sid).telegram_chat_id == "12345"
    assert (
        client.post(
            "/api/v1/notifications/send", headers=h, json={"student_id": sid, "text": "Hello"}
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/api/v1/notifications/send",
            headers=h,
            json={"group_id": world["group"]["id"], "text": "Group"},
        ).json()["queued"]
        == 1
    )
    assert (
        client.post("/api/v1/notifications/send", headers=h, json={"text": "No target"}).status_code
        == 422
    )
    monkeypatch.setattr(cfg, "telegram_bot_token", "fake-token")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as sender,
        Session(get_engine()) as db,
        db.begin(),
    ):
        assert deliver_batch(db, sender) == 2
    assert len(calls) == 2
    assert all(
        n["status"] == "sent"
        for n in client.get("/api/v1/notifications", headers=h).json()["items"]
    )


def test_notification_retry_no_secret_leak(client, headers, world, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "telegram_bot_token", "secret-test-token")
    sid = world["student"]["id"]
    with Session(get_engine()) as db, db.begin():
        db.get(m.Student, sid).telegram_chat_id = "12345"
        db.add(m.Notification(student_id=sid, text="hello", dedupe_key="retry-test"))

    def handler(request):
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as sender:
        for attempt in range(5):
            with Session(get_engine()) as db, db.begin():
                row = db.scalar(select(m.Notification))
                row.next_attempt_at = m.utcnow() - timedelta(seconds=1)
                db.flush()
                deliver_batch(db, sender)
    with Session(get_engine()) as db:
        row = db.scalar(select(m.Notification))
        assert row.status == "failed" and row.attempts == 5
        assert cfg.telegram_bot_token not in row.error


def test_worker_idempotent(client, headers, world):
    for _ in range(2):
        with Session(get_engine()) as db, db.begin():
            schedule(db)
    with Session(get_engine()) as db:
        assert len(db.scalars(select(m.Invoice)).all()) == 1
        lessons = db.scalars(select(m.Lesson)).all()
        assert len(
            {(lesson.group_id, lesson.date, lesson.start_time) for lesson in lessons}
        ) == len(lessons)


@pytest.mark.parametrize(
    "path",
    [
        "/students?page=0",
        "/students?size=101",
        "/groups/1/attendance?month=bad",
        "/payments?from=bad",
    ],
)
def test_pagination_date_validation(client, headers, path):
    response = client.get("/api/v1" + path, headers=headers["admin"])
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_health_openapi_and_missing(client, headers):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").json()["database"] == "postgresql"
    assert client.get("/openapi.json").status_code == 200
    assert (
        client.get("/api/v1/students/999", headers=headers["admin"]).json()["code"]
        == "student_not_found"
    )
    assert client.get("/unknown").json()["code"] == "http_404"
