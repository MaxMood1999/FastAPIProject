import pytest
from conftest import PASSWORD


def test_login_rotation_and_password_revocation(client, headers):
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    ).json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    me = client.get("/api/v1/auth/me", headers=h)
    assert me.status_code == 200
    assert "password_hash" not in me.json()
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=h,
            json={"old_password": PASSWORD, "new_password": "New-password-123456"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": r.json()["refresh_token"]}
        ).status_code
        == 401
    )


def test_invalid_login_throttled(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
        ).status_code
        == 429
    )


@pytest.mark.parametrize(
    "path", ["/users", "/students", "/groups", "/payments", "/invoices", "/audit-log", "/settings"]
)
def test_anonymous_denied(client, path):
    response = client.get("/api/v1" + path)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.parametrize(
    "path",
    [
        "/users",
        "/payments",
        "/invoices",
        "/debtors",
        "/leads",
        "/notifications",
        "/settings",
        "/audit-log",
        "/dashboard",
        "/reports/debts",
        "/reports/teachers",
    ],
)
def test_teacher_denied_financial_and_admin(client, headers, path):
    assert client.get("/api/v1" + path, headers=headers["teacher"]).status_code == 403


def test_user_lifecycle(client, headers):
    h = headers["admin"]
    data = {
        "username": "new_teacher",
        "full_name": "New Teacher",
        "password": PASSWORD,
        "role": "teacher",
    }
    r = client.post("/api/v1/users", json=data, headers=h)
    assert r.status_code == 201
    id = r.json()["id"]
    assert client.post("/api/v1/users", json=data, headers=h).status_code == 409
    assert (
        client.patch(f"/api/v1/users/{id}", json={"full_name": "Updated"}, headers=h).status_code
        == 200
    )
    assert client.delete(f"/api/v1/users/{id}", headers=h).json()["is_active"] is False
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "new_teacher", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert client.delete("/api/v1/users/1", headers=h).status_code == 409
    assert client.get("/api/v1/users", headers=headers["manager"]).status_code == 403


def test_logout_and_invalid_token(client, headers):
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    ).json()
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers=headers["admin"],
            json={"refresh_token": login["refresh_token"]},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=headers["admin"],
            json={"old_password": "wrong", "new_password": "long-new-password"},
        ).status_code
        == 400
    )
