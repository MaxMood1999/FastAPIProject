import calendar
from datetime import timedelta

import pytest
from conftest import PASSWORD
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.common import today
from app.db import get_engine
from app.services import invoice_amount


def test_future_departure_keeps_student_visible_and_reserves_capacity(client, headers, world):
    h, gid, sid = headers["admin"], world["group"]["id"], world["student"]["id"]
    departure = (today() + timedelta(days=40)).isoformat()
    assert (
        client.delete(
            f"/api/v1/groups/{gid}/students/{sid}?left_on={departure}", headers=h
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/groups/{gid}/students", headers=headers["teacher"]).json()["total"]
        == 1
    )
    assert client.get(f"/api/v1/students/{sid}", headers=headers["teacher"]).status_code == 200
    assert client.delete(f"/api/v1/students/{sid}", headers=h).status_code == 409
    assert client.delete(f"/api/v1/groups/{gid}", headers=h).status_code == 409


def test_archived_student_can_settle_historical_debt(client, headers, world):
    h, gid, sid = headers["admin"], world["group"]["id"], world["student"]["id"]
    with Session(get_engine()) as db, db.begin():
        db.get(m.Enrollment, world["enrollment"]["id"]).left_on = today()
        db.add(
            m.Invoice(
                student_id=sid,
                group_id=gid,
                period=world["period"],
                amount=100000,
                due_date=today(),
            )
        )
    assert client.delete(f"/api/v1/students/{sid}", headers=h).status_code == 200
    response = client.post(
        "/api/v1/payments",
        headers={**h, "Idempotency-Key": "archived-debt-settlement"},
        json={
            "student_id": sid,
            "group_id": gid,
            "period": world["period"],
            "amount": 100000,
            "method": "cash",
        },
    )
    assert response.status_code == 201
    assert client.get(f"/api/v1/students/{sid}/balance", headers=h).json()["debt"] == 0


def test_refresh_token_version_prevents_race_reuse(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    ).json()
    # Simulate a refresh session created by an in-flight request during password revocation.
    with Session(get_engine()) as db, db.begin():
        db.get(m.User, 1).token_version += 1
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + tokens["access_token"]}
        ).status_code
        == 401
    )


def test_rescheduled_generated_lesson_not_recreated(client, headers, world):
    h = headers["admin"]
    dates = {"starts_on": today().isoformat(), "ends_on": (today() + timedelta(days=6)).isoformat()}
    assert client.post("/api/v1/lessons/generate", headers=h, json=dates).json()["created"] == 3
    lessons = client.get("/api/v1/lessons", headers=h).json()["items"]
    first = lessons[0]
    assert (
        client.patch(
            f"/api/v1/lessons/{first['id']}",
            headers=h,
            json={"start_time": "10:00", "end_time": "11:00"},
        ).status_code
        == 200
    )
    assert client.post("/api/v1/lessons/generate", headers=h, json=dates).json()["created"] == 0
    assert client.get("/api/v1/lessons", headers=h).json()["total"] == 3


def test_corrected_absence_cancels_pending_notification(client, headers, world):
    h = headers["admin"]
    lesson = world["post"](
        "/lessons",
        {
            "group_id": world["group"]["id"],
            "date": today().isoformat(),
            "start_time": "15:00",
            "end_time": "16:00",
        },
    )
    for status in ["absent", "present"]:
        assert (
            client.put(
                f"/api/v1/lessons/{lesson['id']}/attendance",
                headers=h,
                json={"records": [{"student_id": world["student"]["id"], "status": status}]},
            ).status_code
            == 200
        )
    assert (
        client.get("/api/v1/notifications", headers=h).json()["items"][0]["status"] == "cancelled"
    )


@pytest.mark.parametrize(
    "price,kind,value,expected",
    [
        (310000, "amount", 100000, 210000),
        (310000, "amount", 999999, 0),
        (310000, "percent", 100, 0),
        (1, "percent", 50, 1),
    ],
)
def test_discount_amount_percent_and_half_up_rounding(
    client, headers, world, price, kind, value, expected
):
    start = world["start"]
    last = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    with Session(get_engine()) as db, db.begin():
        course = db.get(m.Course, world["course"]["id"])
        course.monthly_price = price
        db.add(
            m.Discount(
                student_id=world["student"]["id"],
                kind=kind,
                value=value,
                starts_on=start,
                ends_on=last,
            )
        )
        db.flush()
        assert (
            invoice_amount(
                db, db.get(m.Enrollment, world["enrollment"]["id"]), course, world["period"]
            )
            == expected
        )


def test_group_end_date_limits_invoice(client, headers, world):
    with Session(get_engine()) as db, db.begin():
        group = db.get(m.Group, world["group"]["id"])
        group.end_date = world["start"]
        course = db.get(m.Course, world["course"]["id"])
        days = calendar.monthrange(world["start"].year, world["start"].month)[1]
        assert (
            invoice_amount(
                db, db.get(m.Enrollment, world["enrollment"]["id"]), course, world["period"]
            )
            == (310000 + days // 2) // days
        )


@pytest.mark.parametrize(
    "path,data",
    [
        ("/courses", {"name": "New", "monthly_price": -1, "duration_months": 1}),
        ("/courses", {"name": "New", "monthly_price": 1.2, "duration_months": 1}),
        ("/courses", {"name": "New", "monthly_price": 1, "duration_months": 0}),
        ("/users", {"username": "new", "full_name": "New", "password": "short", "role": "admin"}),
        (
            "/users",
            {
                "username": "new",
                "full_name": "New",
                "password": "Long-password-123",
                "role": "root",
            },
        ),
    ],
)
def test_strict_input(client, headers, path, data):
    assert client.post("/api/v1" + path, headers=headers["admin"], json=data).status_code == 422


def test_templates_and_unconfigured_delivery(client, headers, world, monkeypatch):
    from app.config import get_settings
    from app.worker import deliver_batch

    h = headers["admin"]
    assert (
        client.put(
            "/api/v1/notifications/templates", headers=h, json={"absence": "Darsga kelmadi"}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/notifications/templates", headers=h).json()["absence"]
        == "Darsga kelmadi"
    )
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "")
    client.post(
        "/api/v1/notifications/send",
        headers=h,
        json={"student_id": world["student"]["id"], "text": "test"},
    )
    with Session(get_engine()) as db, db.begin():
        assert deliver_batch(db, None) == 0
        assert db.scalar(select(m.Notification)).status == "pending"


def test_filters_and_merged_patch(client, headers, world):
    h, sid, gid, cid = (
        headers["admin"],
        world["student"]["id"],
        world["group"]["id"],
        world["course"]["id"],
    )
    assert (
        client.get(f"/api/v1/students?status=active&group_id={gid}", headers=h).json()["total"] == 1
    )
    assert (
        client.get(f"/api/v1/groups?status=active&course_id={cid}&teacher_id=3", headers=h).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.patch(f"/api/v1/courses/{cid}", headers=h, json={"monthly_price": 400000}).json()[
            "monthly_price"
        ]
        == 400000
    )
    assert client.patch(f"/api/v1/courses/{cid}", headers=h, json={"name": ""}).status_code == 422
    assert (
        client.patch(f"/api/v1/students/{sid}", headers=h, json={"full_name": ""}).status_code
        == 422
    )
    assert client.patch("/api/v1/users/3", headers=h, json={"role": None}).status_code == 422
