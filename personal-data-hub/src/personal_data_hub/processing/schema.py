"""Additive schema migration; shares the existing database and backup boundary."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, MetaData, String, Table, Text, insert, select, inspect, text, update

metadata = MetaData()
versions = Table("hub_processing_schema", metadata, Column("version", Integer, primary_key=True))
objects = Table("hub_content_objects", metadata,
    Column("id", String(64), primary_key=True), Column("processor", String, nullable=False),
    Column("scope_key", String, nullable=False), Column("source", String, nullable=False, index=True),
    Column("account", String, nullable=False), Column("type", String, nullable=False),
    Column("variant", String, nullable=False), Column("schema_version", Integer, nullable=False),
    Column("revision", Integer, nullable=False), Column("generation", Integer, nullable=False),
    Column("occurred_at", DateTime(timezone=True)), Column("timezone", String, nullable=False),
    Column("business_date", String),
    Column("title", Text, nullable=False), Column("preview", Text, nullable=False), Column("summary", Text),
    Column("state", String, nullable=False), Column("details", JSON, nullable=False),
    Column("warnings", JSON, nullable=False), Column("coverage", JSON, nullable=False),
    Column("published_at", DateTime(timezone=True)))
Index("ix_hub_content_time_id", objects.c.occurred_at, objects.c.id)
Index('ix_hub_content_reading_order', objects.c.occurred_at.desc().nulls_last(), objects.c.id).ddl_if(dialect='postgresql')
blocks = Table("hub_content_blocks", metadata,
    Column("object_id", ForeignKey("hub_content_objects.id", ondelete="CASCADE"), primary_key=True),
    # Block revision is its last replacement; the object revision governs read pagination.
    Column("ordinal", Integer, primary_key=True), Column("revision", Integer, nullable=False),
    Column("key", String, nullable=False), Column("type", String, nullable=False),
    Column("text", Text, nullable=False), Column("refs", JSON, nullable=False),
    Column("search_text", Text, nullable=False),
    Column("details", JSON, nullable=False))
search_index = Index('ix_hub_content_search_trgm', blocks.c.search_text, postgresql_using='gin',
                     postgresql_ops={'search_text': 'public.gin_trgm_ops'}).ddl_if(dialect='postgresql')
inputs = Table("hub_content_inputs", metadata,
    Column("object_id", ForeignKey("hub_content_objects.id", ondelete="CASCADE"), primary_key=True),
    Column("record_id", String(64), primary_key=True, index=True), Column("input_hash", String(64), nullable=False))
jobs = Table("hub_processing_jobs", metadata,
    Column("id", String(64), primary_key=True), Column("processor", String, nullable=False),
    Column("scope_key", String, nullable=False), Column("source", String, nullable=False),
    Column("desired_generation", Integer, nullable=False), Column("published_generation", Integer, nullable=False),
    Column("profile_version", Integer, nullable=False), Column("state", String, nullable=False, index=True),
    Column("lease_token", String), Column("lease_until", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False), Column("retry_at", DateTime(timezone=True)),
    Column("error_code", String), Column("updated_at", DateTime(timezone=True), nullable=False))
members = Table('hub_processing_members', metadata,
    Column('job_id', ForeignKey('hub_processing_jobs.id', ondelete='CASCADE'), primary_key=True),
    Column('record_id', String(64), primary_key=True, index=True))
model_calls = Table('hub_processing_model_calls', metadata,
    Column('id', String(64), primary_key=True), Column('job_id', String(64), nullable=False),
    Column('model', String, nullable=False), Column('state', String, nullable=False),
    Column('started_at', DateTime(timezone=True), nullable=False, index=True),
    Column('finished_at', DateTime(timezone=True)), Column('usage', JSON, nullable=False))
model_results = Table('hub_processing_model_results', metadata,
    Column('id', String(64), primary_key=True),
    Column('job_id', ForeignKey('hub_processing_jobs.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('result', JSON, nullable=False), Column('created_at', DateTime(timezone=True), nullable=False))


def migrate(store):
    # Serialize DDL across API and collector processes. Never migrate source tables.
    with store.writer_lock(), store.engine.begin() as c:
        if c.dialect.name == 'postgresql':
            c.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public'))
        metadata.create_all(c, checkfirst=True)
        current = c.scalar(select(versions.c.version).order_by(versions.c.version.desc()).limit(1)) or 0
        if current > 3:
            raise RuntimeError('processing_schema_newer_than_runtime')
        if c.scalar(select(versions.c.version).where(versions.c.version == 1)) is None:
            c.execute(insert(versions).values(version=1))
        # Early M1 collector processes could create v1 tables before the reading
        # columns were finalized. create_all does not add columns to existing tables.
        changed = False
        names = {col['name'] for col in inspect(c).get_columns(objects.name)}
        if 'business_date' not in names:
            c.execute(text('ALTER TABLE hub_content_objects ADD COLUMN business_date VARCHAR'))
            changed = True
        names = {col['name'] for col in inspect(c).get_columns(blocks.name)}
        if 'search_text' not in names:
            c.execute(text("ALTER TABLE hub_content_blocks ADD COLUMN search_text TEXT NOT NULL DEFAULT ''"))
            c.execute(update(blocks).values(search_text=blocks.c.text))
            changed = True
        if changed:
            # Rebuild only derived output. Existing leases are fenced, source facts untouched.
            c.execute(update(jobs).values(desired_generation=jobs.c.desired_generation + 1,
                state='pending', lease_token=None, lease_until=None, attempts=0, retry_at=None))
            c.execute(update(objects).where(objects.c.revision > 0).values(state='stale'))
        if c.dialect.name == 'postgresql':
            search_index.create(c, checkfirst=True)
        if c.scalar(select(versions.c.version).where(versions.c.version == 2)) is None:
            c.execute(insert(versions).values(version=2))
        if c.scalar(select(versions.c.version).where(versions.c.version == 3)) is None:
            # v3 only repaired the removed document processor's historical jobs.
            # Retain the schema marker without resuming that pipeline.
            c.execute(insert(versions).values(version=3))
