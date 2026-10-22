from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NotFound(Exception): pass
class Conflict(Exception): pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Binding(Model):
    collector: Literal["token_monitor", "subboost"]
    provider: Annotated[str, Field(min_length=1, max_length=80)]
    account: Annotated[str, Field(min_length=1, max_length=256)]
    account_email: Annotated[str, Field(max_length=256)] = ""
    profile: Annotated[str, Field(max_length=200)] = ""


class Subscription(Model):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    account_label: Annotated[str, Field(max_length=200)] = ""
    category: Literal["ai", "network", "membership", "other"] = "other"
    plan: Annotated[str, Field(max_length=200)] = ""
    price: Annotated[Decimal, Field(ge=0, le=100000000, max_digits=14, decimal_places=4)] | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "CNY"
    cycle: Literal["day", "week", "month", "year", "one_time"] | None = None
    frequency: Annotated[int, Field(ge=1, le=3650)] = 1
    next_renewal: date | None = None
    expires_on: date | None = None
    payer: Literal["self", "company", "other", "none", "unknown"] = "unknown"
    auto_renew: bool = False
    active: bool = True
    note: Annotated[str, Field(max_length=4000)] = ""
    binding: Binding | None = None

    @model_validator(mode="after")
    def valid_binding(self):
        if self.binding:
            if self.category not in ("ai", "network"):
                raise ValueError("only AI and network records collect quotas")
            if (self.binding.collector == "subboost") != (self.category == "network"):
                raise ValueError("network bindings must use subboost")
        return self


class Window(Model):
    id: Annotated[str, Field(min_length=1, max_length=256)]
    label: Annotated[str, Field(max_length=200)]
    unit: Annotated[str, Field(max_length=32)] | None = None
    used: Annotated[float, Field(ge=0)] | None = None
    limit: Annotated[float, Field(ge=0)] | None = None
    remaining: Annotated[float, Field(ge=0)] | None = None
    used_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    resets_at: datetime | None = None
    expires_at: datetime | None = None
    observed_at: datetime

    @field_validator("observed_at", "resets_at", "expires_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("observation timestamps require a timezone")
        return value


class Reading(Model):
    windows: Annotated[list[Window], Field(max_length=100)] = []
    observed_at: datetime
    expires_at: datetime | None = None
    stale: bool = False
    valid_for_seconds: Annotated[int, Field(ge=1, le=86400)] = 900

    @field_validator("observed_at", "expires_at")
    @classmethod
    def timezone_required(cls, value):
        return Window.timezone_required(value)
