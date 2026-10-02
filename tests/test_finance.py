import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


def payment_data(world, amount=100000):
    return {
        "student_id": world["student"]["id"],
        "group_id": world["group"]["id"],
        "amount": amount,
        "method": "cash",
        "period": world["period"],
    }


def test_invoice_payment_refund_balance_and_receipt(client, headers, world):
    h, sid = headers["admin"], world["student"]["id"]
    generation = {"period": world["period"]}
    assert (
        client.post("/api/v1/invoices/generate", headers=h, json=generation).json()["created"] == 1
    )
    assert (
        client.post("/api/v1/invoices/generate", headers=h, json=generation).json()["created"] == 0
    )
    assert client.get(f"/api/v1/students/{sid}/balance", headers=h).json()["debt"] == 310000
    data = payment_data(world)
    ph = {**h, "Idempotency-Key": "payment-unique-1"}
    payment = client.post("/api/v1/payments", headers=ph, json=data)
    assert payment.status_code == 201
    pid = payment.json()["id"]
    assert client.post("/api/v1/payments", headers=ph, json=data).json()["id"] == pid
    assert (
        client.post("/api/v1/payments", headers=ph, json={**data, "amount": 1}).status_code == 409
    )
    assert client.get("/api/v1/payments", headers=h).json()["total"] == 1
    assert client.get(f"/api/v1/payments/{pid}/receipt", headers=h).json()["currency"] == "UZS"
    rh = {**h, "Idempotency-Key": "refund-unique-1"}
    payload = {"amount": 20000, "reason": "Qaytarish"}
    assert (
        client.post(f"/api/v1/payments/{pid}/refund", headers=rh, json=payload).status_code == 201
    )
    assert (
        client.post(f"/api/v1/payments/{pid}/refund", headers=rh, json=payload).status_code == 201
    )
    assert (
        client.post(
            f"/api/v1/payments/{pid}/refund",
            headers={**h, "Idempotency-Key": "refund-unique-2"},
            json={"amount": 90000, "reason": "Too much"},
        ).status_code
        == 409
    )
    values = client.get(f"/api/v1/students/{sid}/balance", headers=h).json()
    assert values == {
        "student_id": sid,
        "invoiced": 310000,
        "paid": 100000,
        "refunded": 20000,
        "balance": -230000,
        "debt": 230000,
    }
    assert client.get(f"/api/v1/payments/{pid}", headers=h).json()["net_amount"] == 80000
    assert client.get("/api/v1/debtors", headers=h).json()["items"][0]["debt"] == 230000
    assert client.get("/api/v1/students?has_debt=true", headers=h).json()["total"] == 1
    assert client.get(f"/api/v1/students/{sid}/payments", headers=h).json()["total"] == 1
    assert client.delete(f"/api/v1/payments/{pid}", headers=h).status_code == 405


@pytest.mark.parametrize("value", [0, -1, 1.5, "1000", True, 1000000000001])
def test_money_validation(client, headers, world, value):
    assert (
        client.post(
            "/api/v1/payments",
            headers={**headers["admin"], "Idempotency-Key": "valid-key-123"},
            json=payment_data(world, value),
        ).status_code
        == 422
    )


def test_payment_invalid_period_and_membership(client, headers, world):
    h = {**headers["admin"], "Idempotency-Key": "invalid-payment-key"}
    assert (
        client.post(
            "/api/v1/payments", headers=h, json={**payment_data(world), "period": "2026-13"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/payments", headers=headers["admin"], json=payment_data(world)
        ).status_code
        == 422
    )
    student = world["post"]("/students", {"full_name": "Other", "phone": "+998901234560"})
    assert (
        client.post(
            "/api/v1/payments", headers=h, json={**payment_data(world), "student_id": student["id"]}
        ).status_code
        == 422
    )


def test_freeze_discount_proration_and_billed_guard(client, headers, world):
    h, sid, gid, start = (
        headers["admin"],
        world["student"]["id"],
        world["group"]["id"],
        world["start"],
    )
    last = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    dates = {"starts_on": start.isoformat(), "ends_on": (start + timedelta(days=4)).isoformat()}
    assert (
        client.post(f"/api/v1/groups/{gid}/freeze/{sid}", headers=h, json=dates).status_code == 201
    )
    assert (
        client.post(f"/api/v1/groups/{gid}/freeze/{sid}", headers=h, json=dates).status_code == 409
    )
    discount = {
        "kind": "percent",
        "value": 10,
        "starts_on": start.isoformat(),
        "ends_on": last.isoformat(),
    }
    assert (
        client.post(f"/api/v1/students/{sid}/discounts", headers=h, json=discount).status_code
        == 201
    )
    assert (
        client.post(f"/api/v1/students/{sid}/discounts", headers=h, json=discount).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/invoices/generate", headers=h, json={"period": world["period"]}
        ).status_code
        == 200
    )
    expected = (310000 * 90 * (last.day - 5) + last.day * 50) // (last.day * 100)
    assert client.get("/api/v1/invoices", headers=h).json()["items"][0]["amount"] == expected
    assert (
        client.post(
            f"/api/v1/groups/{gid}/freeze/{sid}",
            headers=h,
            json={
                "starts_on": (start + timedelta(days=7)).isoformat(),
                "ends_on": last.isoformat(),
            },
        ).status_code
        == 409
    )
    assert client.delete(f"/api/v1/groups/{gid}/students/{sid}", headers=h).status_code == 409


def test_parallel_refunds_cannot_overdraw(client, headers, world):
    h = headers["admin"]
    p = client.post(
        "/api/v1/payments",
        headers={**h, "Idempotency-Key": "parallel-pay-1"},
        json=payment_data(world),
    ).json()

    def send(_):
        with TestClient(app) as c:
            return c.post(
                f"/api/v1/payments/{p['id']}/refund",
                headers={**h, "Idempotency-Key": str(uuid4())},
                json={"amount": 70000, "reason": "Concurrent refund"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(send, range(2)))
    assert sorted(codes) == [201, 409]
    assert client.get(f"/api/v1/payments/{p['id']}", headers=h).json()["net_amount"] == 30000


def test_parallel_idempotency_and_invoice_generation(client, headers, world):
    h = headers["admin"]

    def pay(_):
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/payments",
                headers={**h, "Idempotency-Key": "parallel-same-key"},
                json=payment_data(world),
            )
            assert r.status_code == 201, r.text
            return r.json()["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(pay, range(4)))
    assert len(set(ids)) == 1

    def bill(_):
        with TestClient(app) as c:
            r = c.post("/api/v1/invoices/generate", headers=h, json={"period": world["period"]})
            assert r.status_code == 200, r.text
            return r.json()["created"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(bill, range(2))) == [0, 1]
