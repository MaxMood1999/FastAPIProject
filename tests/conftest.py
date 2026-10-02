import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

url = os.environ.get("TEST_DATABASE_URL")
if not url:
    raise RuntimeError("Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
if not make_url(url).database.endswith("_test"):
    raise RuntimeError("Tests require a dedicated database whose name ends in _test")
os.environ["DATABASE_URL"] = url
os.environ["JWT_SECRET"] = "test-only-secret-with-at-least-32-characters"
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
from app.db import Base, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import passwords  # noqa: E402

PASSWORD = "Testing-password-123"


@pytest.fixture(scope="session", autouse=True)
def migrated():
    from alembic.config import Config

    from alembic import command

    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def clean_database(migrated):
    with get_engine().begin() as connection:
        names = ", ".join('"' + t.name + '"' for t in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    hashed = passwords.hash(PASSWORD)
    with Session(get_engine()) as db, db.begin():
        for username, role in [
            ("admin", "admin"),
            ("manager", "manager"),
            ("teacher", "teacher"),
            ("other_teacher", "teacher"),
        ]:
            db.add(User(username=username, full_name=username, role=role, password_hash=hashed))


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def headers(client):
    result = {}
    for username in ("admin", "manager", "teacher", "other_teacher"):
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        result[username] = {"Authorization": "Bearer " + response.json()["access_token"]}
    return result


@pytest.fixture
def world(client, headers):
    from app.common import today

    h = headers["admin"]

    def post(path, data):
        response = client.post("/api/v1" + path, json=data, headers=h)
        assert response.status_code == 201, response.text
        return response.json()

    start = today().replace(day=1)
    course = post("/courses", {"name": "Python", "monthly_price": 310000, "duration_months": 12})
    group = post(
        "/groups",
        {
            "name": "Python-1",
            "course_id": course["id"],
            "teacher_id": 3,
            "days": ["mon", "wed", "fri"],
            "start_time": "15:00",
            "end_time": "16:30",
            "room": "A",
            "start_date": start.isoformat(),
            "capacity": 2,
        },
    )
    student = post("/students", {"full_name": "Jasur Aliyev", "phone": "+998901234567"})
    enrollment = post(
        f"/groups/{group['id']}/students",
        {"student_id": student["id"], "joined_on": start.isoformat()},
    )
    return {
        "course": course,
        "group": group,
        "student": student,
        "enrollment": enrollment,
        "period": start.strftime("%Y-%m"),
        "start": start,
        "post": post,
    }
