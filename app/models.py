from datetime import date, datetime, time, timezone
from datetime import date as DateValue

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Record:
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Record, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role in ('admin','manager','teacher')"),)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)


class RefreshSession(Record, Base):
    __tablename__ = "refresh_sessions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    window_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Student(Record, Base):
    __tablename__ = "students"
    full_name: Mapped[str] = mapped_column(String(150), index=True)
    phone: Mapped[str] = mapped_column(String(20))
    birth_date: Mapped[date | None] = mapped_column(Date)
    parent_name: Mapped[str | None] = mapped_column(String(150))
    parent_phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(40))


class Parent(Record, Base):
    __tablename__ = "parents"
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(20))
    relationship: Mapped[str] = mapped_column(String(50))


class Course(Record, Base):
    __tablename__ = "courses"
    __table_args__ = (CheckConstraint("monthly_price >= 0"), CheckConstraint("duration_months > 0"))
    name: Mapped[str] = mapped_column(String(150), unique=True)
    monthly_price: Mapped[int] = mapped_column(BigInteger)
    duration_months: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Group(Record, Base):
    __tablename__ = "groups"
    __table_args__ = (CheckConstraint("end_time > start_time"), CheckConstraint("capacity > 0"))
    name: Mapped[str] = mapped_column(String(150), unique=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    days: Mapped[list] = mapped_column(JSON)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    room: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    capacity: Mapped[int] = mapped_column(Integer, default=20)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Enrollment(Record, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("group_id", "student_id"),
        CheckConstraint("left_on IS NULL OR left_on >= joined_on"),
    )
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    joined_on: Mapped[date] = mapped_column(Date)
    left_on: Mapped[date | None] = mapped_column(Date)


class Freeze(Record, Base):
    __tablename__ = "freezes"
    __table_args__ = (CheckConstraint("ends_on >= starts_on"),)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"), index=True)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)


class Lead(Record, Base):
    __tablename__ = "leads"
    __table_args__ = (CheckConstraint("status in ('new','contacted','trial','enrolled','lost')"),)
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(20))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    source: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="new")
    note: Mapped[str | None] = mapped_column(Text)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), unique=True)


class Lesson(Record, Base):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("group_id", "date", "start_time"),
        UniqueConstraint(
            "group_id", "scheduled_date", "scheduled_time", name="uq_lesson_source_slot"
        ),
        CheckConstraint("end_time > start_time"),
        CheckConstraint("status in ('scheduled','completed','cancelled')"),
    )
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    topic: Mapped[str | None] = mapped_column(String(250))
    scheduled_date: Mapped[DateValue | None] = mapped_column(Date, nullable=True)
    scheduled_time: Mapped[time | None] = mapped_column(Time)


class Attendance(Record, Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("lesson_id", "student_id"),
        CheckConstraint("status in ('present','absent','late','excused')"),
    )
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(500))


class Discount(Record, Base):
    __tablename__ = "discounts"
    __table_args__ = (
        CheckConstraint("kind in ('percent','amount')"),
        CheckConstraint("value > 0 AND (kind != 'percent' OR value <= 100)"),
        CheckConstraint("ends_on >= starts_on"),
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    value: Mapped[int] = mapped_column(BigInteger)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)


class Invoice(Record, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("student_id", "group_id", "period"),
        CheckConstraint("amount >= 0"),
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    due_date: Mapped[date] = mapped_column(Date)


class Payment(Record, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0"),
        CheckConstraint("method in ('cash','card','transfer')"),
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(7), index=True)
    note: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Refund(Record, Base):
    __tablename__ = "refunds"
    __table_args__ = (CheckConstraint("amount > 0"),)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Notification(Record, Base):
    __tablename__ = "notifications"
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    text: Mapped[str] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    dedupe_key: Mapped[str] = mapped_column(String(150), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    error: Mapped[str | None] = mapped_column(String(250))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramLink(Record, Base):
    __tablename__ = "telegram_links"
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Audit(Record, Base):
    __tablename__ = "audit_log"
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int] = mapped_column(Integer)
