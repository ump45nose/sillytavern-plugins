"""API 与 MCP 共用的输入，不附带 AI 决策规则。"""

from datetime import date as Date
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Contact(Input):
    type: Nonempty
    value: Nonempty


class PersonCreate(Input):
    name: Nonempty
    aliases: list[str] = Field(default_factory=list)
    relationship: str | None = None
    contacts: list[Contact] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class PersonPatch(Input):
    name: Nonempty | None = None
    aliases: list[str] | None = None
    relationship: str | None = None
    contacts: list[Contact] | None = None
    tags: list[str] | None = None
    notes: str | None = None


class IdentityInput(Input):
    source: Nonempty = "wechat"
    account: Nonempty
    external_id: Nonempty


class InteractionCreate(Input):
    person_ids: list[str] = Field(min_length=1)
    type: Nonempty = "other"
    channel: str | None = None
    date: Date
    started_at: datetime | None = None
    ended_at: datetime | None = None
    content: str = ""
    source: Nonempty = "manual"
    attachment_ids: list[str] = Field(default_factory=list)


class InteractionPatch(Input):
    person_ids: list[str] | None = Field(default=None, min_length=1)
    type: Nonempty | None = None
    channel: str | None = None
    date: Date | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    content: str | None = None
    source: Nonempty | None = None
    attachment_ids: list[str] | None = None


class MediaInput(Input):
    name: Nonempty
    media_type: Nonempty = "application/octet-stream"


class MessageInput(Input):
    key: Nonempty
    account: Nonempty
    peer: Nonempty
    name: str = ""
    sent_at: datetime
    sender: str = ""
    is_self: bool = False
    content: str
    attachment: MediaInput | None = None

    @model_validator(mode="after")
    def direct_only(self):
        if self.peer.endswith("@chatroom"):
            raise ValueError("only direct WeChat conversations are accepted")
        if self.sent_at.tzinfo is None:
            raise ValueError("sent_at requires a timezone")
        return self


class WechatBatch(Input):
    messages: list[MessageInput] = Field(default_factory=list, max_length=500)
    client_id: Nonempty = "legacy"
    synced_through: datetime | None = None

    @model_validator(mode="after")
    def watermark_timezone(self):
        if self.synced_through is not None and self.synced_through.tzinfo is None:
            raise ValueError("synced_through requires a timezone")
        return self
