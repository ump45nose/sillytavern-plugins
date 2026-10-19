from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, field_validator, model_validator

ZONE = ZoneInfo("Asia/Shanghai")
BILL_TYPES = (
    "expense", "expense_reimbursement", "expense_lending", "expense_repayment",
    "income", "income_lending", "income_repayment", "income_reimbursement", "income_refund", "transfer",
)
SLEEP_STAGES = {0: "unknown", 1: "awake", 2: "sleeping", 3: "out_of_bed", 4: "light", 5: "deep", 6: "rem", 7: "awake_in_bed"}
ASLEEP = {"sleeping", "light", "deep", "rem"}
SCALARS = ("steps", "active_calories_kcal", "total_calories_kcal")
POINTS = {"heart_rate": "bpm", "resting_heart_rate": "bpm", "oxygen_saturation": "percentage", "basal_metabolic_rate": "watts"}
SERIES = (*POINTS, "sleep", "exercise")
HEALTH_FIELDS = (*SCALARS, *SERIES)


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


def now() -> str:
    return utc(datetime.now(timezone.utc))


def utc(value: str | datetime) -> str:
    if not isinstance(value, (str, datetime)):
        raise ValueError("timestamp must be an ISO timestamp with a timezone")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def instant(value: str) -> datetime:
    return datetime.fromisoformat(utc(value).replace("Z", "+00:00"))


def day(value: str) -> str:
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD")
    return value


def business_day(value: str) -> str:
    return instant(value).astimezone(ZONE).date().isoformat()


def date_window(start_date: str, end_date: str) -> tuple[str, str]:
    first, last = date.fromisoformat(day(start_date)), date.fromisoformat(day(end_date))
    if first > last:
        raise ValueError("start_date must not be after end_date")
    return utc(datetime.combine(first, datetime.min.time(), ZONE)), utc(datetime.combine(last + timedelta(days=1), datetime.min.time(), ZONE))


def money(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("money must be a finite decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("money must be a finite decimal") from None
    if not number.is_finite():
        raise ValueError("money must be a finite decimal")
    return format(number, "f")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def no_boolean_coercion(cls, value):
        if isinstance(value, bool):
            raise ValueError("boolean is not a measurement or business field")
        return value


class Provenance(Model):
    origin: str | None = None
    device: dict[str, Any] | str | None = None


class Point(Provenance):
    time: str
    _time = field_validator("time")(utc)


class HeartRate(Point):
    bpm: FiniteFloat = Field(gt=0)


class Oxygen(Point):
    percentage: FiniteFloat = Field(ge=0, le=100)


class MetabolicRate(Point):
    watts: FiniteFloat = Field(ge=0)


class Interval(Provenance):
    start: str
    end: str
    _times = field_validator("start", "end")(utc)

    @model_validator(mode="after")
    def valid_interval(self):
        if instant(self.start) >= instant(self.end):
            raise ValueError("interval end must be after start")
        return self


class Sleep(Interval):
    stage: Literal["unknown", "awake", "sleeping", "out_of_bed", "light", "deep", "rem", "awake_in_bed"]


class Exercise(Interval):
    type: str
    steps: StrictInt | None = Field(default=None, ge=0)
    avg_cadence_spm: FiniteFloat | None = Field(default=None, ge=0)


class HealthData(Model):
    steps: StrictInt | None = Field(default=None, ge=0)
    active_calories_kcal: FiniteFloat | None = Field(default=None, ge=0)
    total_calories_kcal: FiniteFloat | None = Field(default=None, ge=0)
    heart_rate: list[HeartRate] | None = None
    resting_heart_rate: list[HeartRate] | None = None
    oxygen_saturation: list[Oxygen] | None = None
    basal_metabolic_rate: list[MetabolicRate] | None = None
    sleep: list[Sleep] | None = None
    exercise: list[Exercise] | None = None

    def data(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


class HealthDay(HealthData):
    date: str
    _date = field_validator("date")(day)

    def data(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True, exclude={"date"})


class Bill(Model):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source: str = "manual"
    source_id: str | None = None
    occurred_at: str
    type: Literal["expense", "expense_reimbursement", "expense_lending", "expense_repayment", "income", "income_lending", "income_repayment", "income_reimbursement", "income_refund", "transfer"]
    amount: str
    currency: str
    fee: str = "0"
    book: str | None = None
    category: str | None = None
    account_from: str | None = None
    account_to: str | None = None
    merchant: str | None = None
    item: str | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: Literal["confirmed", "pending"] = "confirmed"

    _time = field_validator("occurred_at")(utc)
    _money = field_validator("amount", "fee", mode="before")(money)

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        return str(UUID(value))

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value):
        code = value.strip().upper()
        if len(code) != 3 or not code.isascii() or not code.isalpha():
            raise ValueError("currency must be a three-letter code")
        return code

    @model_validator(mode="after")
    def source_identity(self):
        if not self.source or self.source_id == "":
            raise ValueError("source identity must not be empty")
        if self.source != "manual" and not self.source_id:
            raise ValueError("source_id is required for imported bills")
        return self


def sample_key(sample: dict) -> str:
    return canonical([sample.get("time"), sample.get("start"), sample.get("end"), sample.get("origin"), sample.get("device")])


def merge_health(previous: dict, incoming: dict) -> dict:
    result = dict(previous)
    for name, value in incoming.items():
        if name in SERIES:
            combined = {sample_key(v): v for v in (*previous.get(name, []), *value)}
            result[name] = sorted(combined.values(), key=lambda v: (v.get("time", v.get("start")), sample_key(v)))
        else:
            result[name] = value
    return result
