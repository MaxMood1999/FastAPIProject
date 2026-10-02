from datetime import timedelta

import pytest

from app.common import today


def test_student_filters_permissions_and_profile(client, headers, world):
    sid, gid = world["student"]["id"], world["group"]["id"]
    own, other, admin = headers["teacher"], headers["other_teacher"], headers["admin"]
    assert (
        client.get("/api/v1/students?search=Jasur&page=1&size=1", headers=admin).json()["total"]
        == 1
    )
    assert client.get("/api/v1/students?search=%", headers=admin).json()["total"] == 0
    assert client.get("/api/v1/students", headers=other).json()["total"] == 0
    assert client.get(f"/api/v1/students/{sid}", headers=other).status_code == 403
    profile = client.get(f"/api/v1/students/{sid}", headers=own).json()
    assert "debt" not in profile and len(profile["groups"]) == 1
    assert client.get(f"/api/v1/groups/{gid}/students", headers=own).json()["total"] == 1
    assert client.get(f"/api/v1/groups/{gid}/students", headers=other).status_code == 403
    assert client.get("/api/v1/students?has_debt=true", headers=own).status_code == 403
    assert client.get("/api/v1/groups", headers=other).json()["total"] == 0
    assert (
        client.post(
            f"/api/v1/students/{sid}/parents",
            headers=admin,
            json={"full_name": "Parent", "phone": "+998901234567"},
        ).status_code
        == 201
    )
    assert (
        client.patch(f"/api/v1/students/{sid}", headers=admin, json={"note": "Updated"}).status_code
        == 200
    )
    assert client.delete(f"/api/v1/students/{sid}", headers=admin).status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": "", "phone": "+998901234567"},
        {"full_name": "Ali", "phone": "invalid"},
        {"full_name": "Ali", "phone": "+998901234567", "birth_date": "2099-01-01"},
        {"full_name": "Ali", "phone": "+998901234567", "is_active": True},
    ],
)
def test_student_validation(client, headers, payload):
    assert (
        client.post("/api/v1/students", headers=headers["admin"], json=payload).status_code == 422
    )


def test_enrollment_capacity_and_archive(client, headers, world):
    h, gid, sid = headers["admin"], world["group"]["id"], world["student"]["id"]
    assert (
        client.post(
            f"/api/v1/groups/{gid}/students", headers=h, json={"student_id": sid}
        ).status_code
        == 409
    )
    second = world["post"]("/students", {"full_name": "Second", "phone": "+998901234568"})
    third = world["post"]("/students", {"full_name": "Third", "phone": "+998901234569"})
    world["post"](f"/groups/{gid}/students", {"student_id": second["id"]})
    assert (
        client.post(
            f"/api/v1/groups/{gid}/students", headers=h, json={"student_id": third["id"]}
        ).status_code
        == 409
    )
    assert client.patch(f"/api/v1/groups/{gid}", headers=h, json={"capacity": 1}).status_code == 409
    assert client.delete(f"/api/v1/groups/{gid}", headers=h).status_code == 409
    assert client.delete(f"/api/v1/courses/{world['course']['id']}", headers=h).status_code == 409
    assert client.delete(f"/api/v1/groups/{gid}/students/{sid}", headers=h).status_code == 200
    assert (
        client.delete(f"/api/v1/groups/{gid}/students/{second['id']}", headers=h).status_code == 200
    )
    assert client.delete(f"/api/v1/students/{sid}", headers=h).json()["is_active"] is False
    assert client.delete(f"/api/v1/groups/{gid}", headers=h).json()["is_active"] is False
    assert (
        client.delete(f"/api/v1/courses/{world['course']['id']}", headers=h).json()["is_active"]
        is False
    )


def test_group_conflicts_and_patch_validation(client, headers, world):
    h, gid = headers["admin"], world["group"]["id"]
    values = {
        k: world["group"][k]
        for k in ("course_id", "teacher_id", "days", "start_time", "end_time", "room", "start_date")
    }
    values["name"] = "Conflicting"
    assert client.post("/api/v1/groups", headers=h, json=values).status_code == 409
    values["end_time"] = "14:00"
    assert client.post("/api/v1/groups", headers=h, json=values).status_code == 422
    assert (
        client.patch(f"/api/v1/groups/{gid}", headers=h, json={"start_time": "17:00"}).status_code
        == 422
    )
    assert client.patch(f"/api/v1/groups/{gid}", headers=h, json={"room": "B"}).status_code == 409
    assert (
        client.patch(f"/api/v1/groups/{gid}", headers=h, json={"name": "Renamed"}).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/students/{world['student']['id']}", headers=h, json={"phone": None}
        ).status_code
        == 422
    )
    assert client.delete("/api/v1/users/3", headers=h).status_code == 409


def test_lead_conversion_atomic(client, headers, world):
    h = headers["admin"]
    lead = world["post"](
        "/leads",
        {
            "full_name": "Lead",
            "phone": "+998901234566",
            "source": "Telegram",
            "course_id": world["course"]["id"],
        },
    )
    assert (
        client.patch(f"/api/v1/leads/{lead['id']}", headers=h, json={"status": "trial"}).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/leads/{lead['id']}/convert",
            headers=h,
            json={"group_id": world["group"]["id"]},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/leads/{lead['id']}/convert",
            headers=h,
            json={"group_id": world["group"]["id"]},
        ).status_code
        == 409
    )
    lead2 = world["post"](
        "/leads", {"full_name": "Lead2", "phone": "+998901234560", "source": "Web"}
    )
    before = client.get("/api/v1/students", headers=h).json()["total"]
    assert (
        client.post(
            f"/api/v1/leads/{lead2['id']}/convert",
            headers=h,
            json={"group_id": world["group"]["id"]},
        ).status_code
        == 409
    )
    assert client.get("/api/v1/students", headers=h).json()["total"] == before


def test_attendance_lifecycle_and_scope(client, headers, world):
    h, gid, sid = headers["admin"], world["group"]["id"], world["student"]["id"]
    lesson = world["post"](
        "/lessons",
        {"group_id": gid, "date": today().isoformat(), "start_time": "15:00", "end_time": "16:00"},
    )
    path = f"/api/v1/lessons/{lesson['id']}/attendance"
    assert (
        client.put(
            path,
            headers=headers["other_teacher"],
            json={"records": [{"student_id": sid, "status": "present"}]},
        ).status_code
        == 403
    )
    assert (
        client.put(
            path, headers=h, json={"records": [{"student_id": 999, "status": "present"}]}
        ).status_code
        == 422
    )
    data = {"records": [{"student_id": sid, "status": "absent", "reason": "kasal"}]}
    assert client.put(path, headers=headers["teacher"], json=data).status_code == 200
    assert client.put(path, headers=h, json=data).status_code == 200
    assert client.get(path, headers=h).json()["total"] == 1
    assert client.get("/api/v1/notifications", headers=h).json()["total"] == 1
    assert (
        client.patch(
            f"/api/v1/lessons/{lesson['id']}", headers=h, json={"status": "cancelled"}
        ).status_code
        == 409
    )
    data["records"][0]["status"] = "present"
    assert client.put(path, headers=h, json=data).status_code == 200
    assert client.get(f"/api/v1/students/{sid}", headers=h).json()["attendance_percent"] == 100
    assert (
        client.get(f"/api/v1/groups/{gid}/attendance?month={world['period']}", headers=h).json()[
            "total"
        ]
        == 1
    )
    assert client.get(f"/api/v1/students/{sid}/attendance", headers=h).json()["total"] == 1


def test_lesson_generation_and_future_attendance(client, headers, world):
    h, gid = headers["admin"], world["group"]["id"]
    dates = {"starts_on": today().isoformat(), "ends_on": (today() + timedelta(days=6)).isoformat()}
    response = client.post("/api/v1/lessons/generate", headers=h, json=dates)
    assert response.status_code == 200
    assert response.json()["created"] == 3
    assert client.post("/api/v1/lessons/generate", headers=h, json=dates).json()["created"] == 0
    lesson = world["post"](
        "/lessons",
        {
            "group_id": gid,
            "date": (today() + timedelta(days=1)).isoformat(),
            "start_time": "10:00",
            "end_time": "11:00",
        },
    )
    assert (
        client.put(
            f"/api/v1/lessons/{lesson['id']}/attendance",
            headers=h,
            json={"records": [{"student_id": world["student"]["id"], "status": "present"}]},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/lessons/{lesson['id']}", headers=h, json={"status": "cancelled"}
        ).status_code
        == 200
    )
