from datetime import date, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

Name = Annotated[str, Field(min_length=1, max_length=150)]
Phone = Annotated[str, Field(pattern=r"^\+?[0-9]{9,15}$")]
Money = Annotated[int, Field(strict=True, ge=0, le=10**12)]
PositiveMoney = Annotated[int, Field(strict=True, gt=0, le=10**12)]
Period = Annotated[str, Field(pattern=r"^20[0-9]{2}-(0[1-9]|1[0-2])$")]
Role = Literal["admin", "manager", "teacher"]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    username: Annotated[str, Field(min_length=1, max_length=80)]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class Refresh(Input):
    refresh_token: Annotated[str, Field(min_length=20, max_length=200)]


class ChangePassword(Input):
    old_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Annotated[str, Field(min_length=12, max_length=128)]


class UserCreate(Input):
    username: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{3,80}$")]
    full_name: Name
    password: Annotated[str, Field(min_length=12, max_length=128)]
    role: Role


class UserPatch(Input):
    full_name: Name | None = None
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def no_null(self):
        if any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("Null qiymat mumkin emas")
        return self


class StudentCreate(Input):
    full_name: Name
    phone: Phone
    birth_date: date | None = None
    parent_name: Name | None = None
    parent_phone: Phone | None = None
    address: Annotated[str, Field(max_length=500)] | None = None
    note: Annotated[str, Field(max_length=4000)] | None = None

    @model_validator(mode="after")
    def valid_birth(self):
        if self.birth_date and self.birth_date > date.today():
            raise ValueError("Tug'ilgan sana kelajakda bo'lishi mumkin emas")
        return self


class ParentCreate(Input):
    full_name: Name
    phone: Phone
    relationship: Annotated[str, Field(min_length=1, max_length=50)] = "parent"


class CourseCreate(Input):
    name: Name
    monthly_price: Money
    duration_months: Annotated[int, Field(ge=1, le=120)]


class GroupCreate(Input):
    name: Name
    course_id: Annotated[int, Field(gt=0)]
    teacher_id: Annotated[int, Field(gt=0)]
    days: Annotated[list[Day], Field(min_length=1, max_length=7)]
    start_time: time
    end_time: time
    room: Annotated[str, Field(min_length=1, max_length=80)]
    start_date: date
    end_date: date | None = None
    capacity: Annotated[int, Field(ge=1, le=500)] = 20

    @model_validator(mode="after")
    def valid_schedule(self):
        if self.end_time <= self.start_time or self.start_time.tzinfo or self.end_time.tzinfo:
            raise ValueError("Dars vaqti noto'g'ri")
        if len(set(self.days)) != len(self.days):
            raise ValueError("Kunlar takrorlanmasin")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("Sana oralig'i noto'g'ri")
        return self


class Enroll(Input):
    student_id: Annotated[int, Field(gt=0)]
    joined_on: date | None = None


class DateRange(Input):
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def valid_range(self):
        if self.ends_on < self.starts_on:
            raise ValueError("Sana oralig'i noto'g'ri")
        return self


class DiscountCreate(DateRange):
    kind: Literal["percent", "amount"]
    value: PositiveMoney

    @model_validator(mode="after")
    def valid_percent(self):
        if self.kind == "percent" and self.value > 100:
            raise ValueError("Foiz 100 dan oshmasin")
        return self


class LeadCreate(Input):
    full_name: Name
    phone: Phone
    course_id: Annotated[int, Field(gt=0)] | None = None
    source: Annotated[str, Field(min_length=1, max_length=80)]
    note: Annotated[str, Field(max_length=4000)] | None = None


class LeadPatch(Input):
    status: Literal["new", "contacted", "trial", "lost"] | None = None
    note: Annotated[str, Field(max_length=4000)] | None = None


class Convert(Input):
    group_id: Annotated[int, Field(gt=0)]


class LessonCreate(Input):
    group_id: Annotated[int, Field(gt=0)]
    date: date
    start_time: time
    end_time: time
    topic: Annotated[str, Field(max_length=250)] | None = None
    status: Literal["scheduled", "completed", "cancelled"] = "scheduled"

    @model_validator(mode="after")
    def valid_times(self):
        if self.end_time <= self.start_time or self.start_time.tzinfo or self.end_time.tzinfo:
            raise ValueError("Dars vaqti noto'g'ri")
        return self


class AttendanceRecord(Input):
    student_id: Annotated[int, Field(gt=0)]
    status: Literal["present", "absent", "late", "excused"]
    reason: Annotated[str, Field(max_length=500)] | None = None


class AttendancePut(Input):
    records: Annotated[list[AttendanceRecord], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def unique_students(self):
        ids = [r.student_id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("O'quvchi takrorlanmasin")
        return self


class PaymentCreate(Input):
    student_id: Annotated[int, Field(gt=0)]
    group_id: Annotated[int, Field(gt=0)]
    amount: PositiveMoney
    method: Literal["cash", "card", "transfer"]
    period: Period
    note: Annotated[str, Field(max_length=500)] | None = None


class RefundCreate(Input):
    amount: PositiveMoney
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class Generate(Input):
    period: Period


class NotificationSend(Input):
    student_id: Annotated[int, Field(gt=0)] | None = None
    group_id: Annotated[int, Field(gt=0)] | None = None
    text: Annotated[str, Field(min_length=1, max_length=4000)]

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.student_id is None) == (self.group_id is None):
            raise ValueError("Bitta student_id yoki group_id tanlang")
        return self


class CenterSettings(Input):
    name: Name = "O'quv markaz"
    phone: Phone | None = None
    payment_day: Annotated[int, Field(ge=1, le=28)] = 10


class Templates(Input):
    payment: Annotated[str, Field(min_length=1, max_length=3000)] = "To'lov qabul qilindi."
    absence: Annotated[str, Field(min_length=1, max_length=3000)] = (
        "Farzandingiz bugun darsga kelmadi."
    )
    due: Annotated[str, Field(min_length=1, max_length=3000)] = "To'lov muddati yaqinlashmoqda."
    debt: Annotated[str, Field(min_length=1, max_length=3000)] = (
        "To'lov bo'yicha qarzdorlik mavjud."
    )


def partial(schema):
    return create_model(
        schema.__name__.replace("Create", "Patch"),
        __base__=Input,
        **{k: (f.annotation | None, None) for k, f in schema.model_fields.items()},
    )


StudentPatch = partial(StudentCreate)
CoursePatch = partial(CourseCreate)
GroupPatch = partial(GroupCreate)
LessonPatch = partial(LessonCreate)
