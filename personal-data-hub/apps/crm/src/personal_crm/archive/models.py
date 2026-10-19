"""CRM 唯一业务存储；同步回执不保存消息正文。"""

from sqlalchemy import (
    JSON,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from personal_crm.storage.models import UTCDateTime

metadata = MetaData()
people = Table(
    "crm_people",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", Text, nullable=False),
    Column("aliases", JSON, nullable=False),
    Column("relationship", Text),
    Column("contacts", JSON, nullable=False),
    Column("tags", JSON, nullable=False),
    Column("notes", Text, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
)
identities = Table(
    "crm_identities",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "person_id", ForeignKey("crm_people.id", ondelete="CASCADE"), nullable=False, index=True
    ),
    Column("source", String(80), nullable=False),
    Column("account", Text, nullable=False),
    Column("external_id", Text, nullable=False),
    UniqueConstraint("source", "account", "external_id"),
)
interactions = Table(
    "crm_interactions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("type", Text, nullable=False),
    Column("channel", Text),
    Column("date", Date, nullable=False),
    Column("started_at", UTCDateTime()),
    Column("ended_at", UTCDateTime()),
    Column("content", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("identity_id", ForeignKey("crm_identities.id", ondelete="SET NULL"), index=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
)
Index("ix_crm_interaction_time", interactions.c.date, interactions.c.started_at, interactions.c.id)
participants = Table(
    "crm_interaction_people",
    metadata,
    Column(
        "interaction_id", ForeignKey("crm_interactions.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("person_id", ForeignKey("crm_people.id", ondelete="CASCADE"), primary_key=True),
)
Index("ix_crm_person_history", participants.c.person_id, participants.c.interaction_id)
attachments = Table(
    "crm_attachments",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("size", Integer),
    Column("file_key", Text),
    Column("created_at", UTCDateTime(), nullable=False),
)
attachment_links = Table(
    "crm_interaction_attachments",
    metadata,
    Column(
        "interaction_id", ForeignKey("crm_interactions.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("attachment_id", ForeignKey("crm_attachments.id"), primary_key=True),
)
messages = Table(
    "crm_message_receipts",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("identity_id", ForeignKey("crm_identities.id", ondelete="SET NULL"), index=True),
    Column("interaction_id", ForeignKey("crm_interactions.id", ondelete="SET NULL"), index=True),
    Column("attachment_id", ForeignKey("crm_attachments.id", ondelete="SET NULL")),
    Column("sent_at", UTCDateTime(), nullable=False),
)
Index("ix_crm_receipt_identity_time", messages.c.identity_id, messages.c.sent_at)
clients = Table(
    "crm_sync_clients",
    metadata,
    Column("id", Text, primary_key=True),
    Column("synced_through", UTCDateTime()),
    Column("last_seen_at", UTCDateTime(), nullable=False),
)
