from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import models as m
from app import schemas as s
from app.common import DB, Page, advisory_lock, audit, dump, fail, get, paginate, save
from app.security import Admin, Current, digest, dummy_hash, issue_tokens, passwords

router = APIRouter(tags=["Auth / Xodimlar"])


@router.post("/auth/login")
def login(data: s.Login, db: DB):
    key = digest(data.username.lower())
    db.execute(insert(m.LoginAttempt).values(key=key).on_conflict_do_nothing())
    attempt = db.scalar(select(m.LoginAttempt).where(m.LoginAttempt.key == key).with_for_update())
    now = m.utcnow()
    if now - attempt.window_at > timedelta(minutes=15):
        attempt.attempts, attempt.window_at = 0, now
    if attempt.attempts >= 10:
        fail("rate_limited", "15 daqiqadan so'ng urinib ko'ring", 429)
    user = db.scalar(select(m.User).where(m.User.username == data.username))
    valid = passwords.verify(data.password, user.password_hash if user else dummy_hash)
    if not user or not valid or not user.is_active:
        attempt.attempts += 1
        db.commit()  # Failed authentication must persist the throttle counter.
        fail("invalid_credentials", "Login yoki parol noto'g'ri", 401)
    attempt.attempts = 0
    audit(db, user, "login", user)
    return issue_tokens(db, user)


@router.post("/auth/refresh")
def refresh(data: s.Refresh, db: DB):
    row = db.scalar(
        select(m.RefreshSession)
        .where(m.RefreshSession.token_hash == digest(data.refresh_token))
        .with_for_update()
    )
    if not row or row.revoked or row.expires_at <= m.utcnow():
        fail("invalid_refresh", "Refresh token yaroqsiz", 401)
    user = db.get(m.User, row.user_id)
    if not user.is_active or row.token_version != user.token_version:
        fail("unauthorized", "Foydalanuvchi faol emas", 401)
    row.revoked = True
    return issue_tokens(db, user)


@router.post("/auth/logout")
def logout(data: s.Refresh, db: DB, user: Current):
    row = db.scalar(
        select(m.RefreshSession)
        .where(
            m.RefreshSession.token_hash == digest(data.refresh_token),
            m.RefreshSession.user_id == user.id,
        )
        .with_for_update()
    )
    if row:
        row.revoked = True
    return {"ok": True}


@router.get("/auth/me")
def me(user: Current):
    return dump(user)


@router.post("/auth/change-password")
def change_password(data: s.ChangePassword, db: DB, user: Current):
    user = get(db, m.User, user.id, True)
    if not passwords.verify(data.old_password, user.password_hash):
        fail("invalid_password", "Eski parol noto'g'ri", 400)
    user.password_hash = passwords.hash(data.new_password)
    revoke(db, user)
    audit(db, user, "change_password", user)
    return {"ok": True}


def revoke(db, user):
    user.token_version += 1
    for token in db.scalars(select(m.RefreshSession).where(m.RefreshSession.user_id == user.id)):
        token.revoked = True


@router.get("/users")
def users(db: DB, user: Admin, paging: Page):
    return paginate(db, select(m.User).order_by(m.User.id), paging)


@router.post("/users", status_code=201)
def create_user(data: s.UserCreate, db: DB, user: Admin):
    values = data.model_dump(exclude={"password"})
    return save(db, user, m.User(**values, password_hash=passwords.hash(data.password)))


@router.patch("/users/{id}")
def update_user(id: int, data: s.UserPatch, db: DB, user: Admin):
    advisory_lock(db, "users-admin")
    obj = get(db, m.User, id, True)
    values = data.model_dump(exclude_unset=True)
    disabling = values.get("is_active") is False or values.get("role", obj.role) != obj.role
    if disabling and obj.id == user.id:
        fail("self_change_forbidden", "O'z rolingizni yoki faolligingizni o'zgartira olmaysiz")
    if disabling and db.scalar(
        select(m.Group.id).where(m.Group.teacher_id == id, m.Group.is_active.is_(True)).limit(1)
    ):
        fail("teacher_has_groups", "Avval faol guruhlarga boshqa o'qituvchi tayinlang")
    for key, value in values.items():
        setattr(obj, key, value)
    if disabling:
        revoke(db, obj)
    return save(db, user, obj, "update")


@router.delete("/users/{id}")
def delete_user(id: int, db: DB, user: Admin):
    return update_user(id, s.UserPatch(is_active=False), db, user)
