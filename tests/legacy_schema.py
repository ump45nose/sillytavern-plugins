"""一次迁移的旧输入样本结构，不参与运行包或新库建表。"""

from sqlalchemy import JSON, Column, MetaData, String, Table, Text

from personal_crm.archive.models import UTCDateTime
from personal_crm.core.domain import utcnow

metadata = MetaData()
Table(
    "people",
    metadata,
    Column("id", String, primary_key=True),
    Column("display_name", Text),
    Column("aliases", JSON, default=list),
    Column("contact_methods", JSON, default=dict),
    Column("profile_notes", Text),
    Column("organizations", JSON, default=list),
    Column("pronouns", Text),
    Column("relationship_to_me", Text),
    Column("tags", JSON, default=list),
    Column("created_at", UTCDateTime(), default=utcnow),
    Column("updated_at", UTCDateTime(), default=utcnow),
)
Table(
    "interactions",
    metadata,
    Column("id", String, primary_key=True),
    Column("person_id", String),
    Column("occurred_at", UTCDateTime()),
    Column("interaction_type", Text),
    Column("channel", Text),
    Column("direction", Text),
    Column("summary", Text),
    Column("message", JSON),
    Column("source_type", Text),
    Column("source_event_key", Text),
    Column("source_message_key", Text),
    Column("created_at", UTCDateTime(), default=utcnow),
)
Table(
    "sync_clients",
    metadata,
    Column("source", String, primary_key=True),
    Column("client_id", String, primary_key=True),
    Column("synced_through", UTCDateTime()),
    Column("last_seen_at", UTCDateTime(), default=utcnow),
)
