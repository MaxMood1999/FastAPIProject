from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Query
from pydantic import ValidationError
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Audit

DB = Annotated[Session, Depends(get_db, scope="function")]


class APIError(Exception):
    def __init__(self, status, code, detail):
        self.status, self.code, self.detail = status, code, detail


def today():
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def fail(code, detail, status=409):
    raise APIError(status, code, detail)


def get(db, model, id, lock=False):
    stmt = select(model).where(model.id == id)
    if lock:
        stmt = stmt.with_for_update()
    obj = db.scalar(stmt)
    if obj is None:
        fail(f"{model.__name__.lower()}_not_found", "Ma'lumot topilmadi", 404)
    return obj


def active(obj):
    if not obj.is_active:
        fail("archived", "Ma'lumot arxivlangan")
    return obj


def dump(obj, exclude=()):
    hidden = {
        "password_hash",
        "token_version",
        "token_hash",
        "code_hash",
        "telegram_chat_id",
    } | set(exclude)
    return {
        c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key not in hidden
    }


class Pagination:
    def __init__(self, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
        self.page, self.size = page, size


Page = Annotated[Pagination, Depends()]


def paginate(db, stmt, paging):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.offset((paging.page - 1) * paging.size).limit(paging.size)).all()
    return {
        "items": [dump(r) for r in rows],
        "total": total,
        "page": paging.page,
        "size": paging.size,
    }


def audit(db, user, action, obj):
    db.flush()
    db.add(
        Audit(
            user_id=user.id if user else None,
            action=action,
            entity=obj.__tablename__,
            entity_id=obj.id,
        )
    )


def save(db, user, obj, action="create"):
    db.add(obj)
    db.flush()
    audit(db, user, action, obj)
    return dump(obj)


def patch_values(obj, data, schema):
    values = {k: getattr(obj, k) for k in schema.model_fields}
    values.update(data.model_dump(exclude_unset=True))
    try:
        return schema.model_validate(values).model_dump()
    except ValidationError:
        fail("validation_error", "Maydonlar yoki sana/vaqt oralig'i noto'g'ri", 422)


def apply_values(obj, values):
    for key, value in values.items():
        setattr(obj, key, value)


def advisory_lock(db, key):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
