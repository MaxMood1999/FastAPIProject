from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app import models as m
from app.common import today
from app.config import Settings, get_settings
from app.db import get_engine
from app.main import app
from app.worker import deliver_batch, schedule


def test_cli_creates_admin_without_plaintext_password(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["cli", "create-admin", "--username", "owner", "--name", "Owner"]
    )
    monkeypatch.setattr("getpass.getpass", lambda _: PASSWORD)
    cli.main()
    assert "Admin yaratildi" in capsys.readouterr().out
    with Session(get_engine()) as db:
        owner = db.scalar(select(m.User).where(m.User.username == "owner"))
        assert owner.role == "admin" and owner.password_hash != PASSWORD
    with pytest.raises(SystemExit, match="Login band"):
        cli.main()


def test_cli_password_confirmation(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cli", "create-admin"])
    values = iter([PASSWORD, "different"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(values))
    with pytest.raises(SystemExit, match="Parollar mos emas"):
        cli.main()


def test_postgresql_required():
    with pytest.raises(ValueError, match="postgresql"):
        Settings(database_url="sqlite://", jwt_secret="x" * 40)


def test_concurrent_enrollments_obey_capacity(client, headers, world):
    students = [
        world["post"]("/students", {"full_name": name, "phone": "+998901234567"})
        for name in ("Second", "Third")
    ]

    def request(student):
        with TestClient(app) as c:
            return c.post(
                f"/api/v1/groups/{world['group']['id']}/students",
                headers=headers["admin"],
                json={"student_id": student["id"]},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request, students)) == [201, 409]
    assert (
        client.get(
            f"/api/v1/groups/{world['group']['id']}/students", headers=headers["admin"]
        ).json()["total"]
        == 2
    )


def test_concurrent_refresh_only_one_succeeds(client):
    refresh = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    ).json()["refresh_token"]

    def request(_):
        with TestClient(app) as c:
            return c.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request, range(2))) == [200, 401]


def test_reminders_ignore_paid_old_debt_and_dedupe(client, headers, world):
    sid, gid, current = world["student"]["id"], world["group"]["id"], today()
    previous = (current.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    with Session(get_engine()) as db, db.begin():
        db.add_all(
            [
                m.Invoice(
                    student_id=sid,
                    group_id=gid,
                    period=previous,
                    amount=100000,
                    due_date=current - timedelta(days=20),
                ),
                m.Invoice(
                    student_id=sid,
                    group_id=gid,
                    period=world["period"],
                    amount=100000,
                    due_date=current + timedelta(days=3),
                ),
                m.Payment(
                    student_id=sid,
                    group_id=gid,
                    period=previous,
                    amount=100000,
                    method="cash",
                    created_by=1,
                    idempotency_key="old-invoice-covered",
                ),
            ]
        )
    for _ in range(2):
        with Session(get_engine()) as db, db.begin():
            schedule(db)
    with Session(get_engine()) as db, db.begin():
        notifications = db.scalars(select(m.Notification)).all()
        assert len(notifications) == 1 and notifications[0].dedupe_key.startswith("due:")
        db.scalar(
            select(m.Payment)
        ).amount = 50000  # Fixture setup: simulate an unpaid older balance.
    for _ in range(2):
        with Session(get_engine()) as db, db.begin():
            schedule(db)
    with Session(get_engine()) as db:
        notifications = db.scalars(select(m.Notification)).all()
        assert len(notifications) == 2
        assert any(n.dedupe_key.startswith("debt:") for n in notifications)


def test_schedule_conflict_does_not_block_billing(client, headers, world, caplog):
    from app.services import DAYS

    day = today()
    while DAYS[day.weekday()] not in world["group"]["days"]:
        day += timedelta(days=1)
    world["post"](
        "/lessons",
        {
            "group_id": world["group"]["id"],
            "date": day.isoformat(),
            "start_time": "15:15",
            "end_time": "16:45",
        },
    )
    with Session(get_engine()) as db, db.begin():
        schedule(db)
    with Session(get_engine()) as db:
        assert db.scalar(select(m.Invoice)) is not None
    assert "schedule conflict" in caplog.text


def test_unlinked_delivery_waits_without_spending_attempts(client, headers, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "mock-only")
    with Session(get_engine()) as db, db.begin():
        db.add(
            m.Notification(student_id=world["student"]["id"], text="hello", dedupe_key="unlinked")
        )
    with Session(get_engine()) as db, db.begin():
        assert deliver_batch(db, None) == 1
        row = db.scalar(select(m.Notification))
        assert row.attempts == 0 and row.error == "telegram_not_linked" and row.status == "pending"


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"message": "bad"},
        {"message": {"chat": {"type": "group"}, "text": "/start bad"}},
        {"message": {"chat": {"type": "private", "id": 123}, "text": "/help"}},
    ],
)
def test_telegram_irrelevant_updates_acknowledged(client, monkeypatch, message):
    monkeypatch.setattr(get_settings(), "telegram_webhook_secret", "secret")
    assert (
        client.post(
            "/api/v1/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json=message,
        ).status_code
        == 200
    )
