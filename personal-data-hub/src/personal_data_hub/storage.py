from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, MetaData, String, Table, Text, create_engine, delete, func, insert, select, text, update

from .contracts import Asset, Batch, digest, utcnow
from .source_policy import SOURCE_KINDS

metadata = MetaData()
# 原始 UI/AX 事件可能带 NUL；PostgreSQL JSONB 拒绝它，JSON 能原样归档转义值。
jtype = JSON()
sources = Table("hub_sources", metadata, Column("id", String, primary_key=True), Column("account", String, nullable=False), Column("adapter", String, nullable=False), Column("deletion_support", String, nullable=False))
records = Table("hub_records", metadata, Column("id", String(64), primary_key=True), Column("source", String, nullable=False, index=True), Column("external_id", Text, nullable=False), Column("kind", String, nullable=False, index=True), Column("occurred_at", DateTime(timezone=True), index=True), Column("updated_at", DateTime(timezone=True)), Column("observed_at", DateTime(timezone=True), nullable=False), Column("timezone", String, nullable=False), Column("hash", String(64), nullable=False), Column("raw", jtype, nullable=False), Column("normalized", jtype, nullable=False), Column("assets", jtype, nullable=False))
Index('ix_hub_records_source_observed_at', records.c.source, records.c.observed_at)
Index('ix_hub_records_kind_id_source', records.c.kind, records.c.id, records.c.source)
previews = Table("hub_record_previews", metadata, Column("record_id", ForeignKey("hub_records.id", ondelete="CASCADE"), primary_key=True), Column("title", Text, nullable=False), Column("preview", Text, nullable=False))
display_index = Table("hub_display_index", metadata, Column("record_id", ForeignKey("hub_records.id", ondelete="CASCADE"), primary_key=True), Column("source", String, nullable=False), Column("kind", String, nullable=False), Column("domain", String, nullable=False, index=True), Column("occurred_at", DateTime(timezone=True), index=True), Column("observed_at", DateTime(timezone=True), nullable=False), Column("title", String(160), nullable=False), Column("preview", String(500), nullable=False), Column("data", jtype, nullable=False))
revisions = Table("hub_revisions", metadata, Column("record_id", ForeignKey("hub_records.id", ondelete="CASCADE"), primary_key=True), Column("hash", String(64), primary_key=True), Column("observed_at", DateTime(timezone=True), nullable=False), Column("value", jtype, nullable=False))
assets = Table("hub_assets", metadata, Column("id", String(64), primary_key=True), Column("size", Integer, nullable=False))
asset_refs = Table("hub_asset_refs", metadata, Column("record_id", ForeignKey("hub_records.id", ondelete="CASCADE"), primary_key=True), Column("asset_id", ForeignKey("hub_assets.id"), primary_key=True))
checkpoints = Table("hub_checkpoints", metadata, Column("source", String, primary_key=True), Column("value", jtype, nullable=False), Column("updated_at", DateTime(timezone=True), nullable=False))
runs = Table("hub_runs", metadata, Column("id", String, primary_key=True), Column("source", String, nullable=False, index=True), Column("started_at", DateTime(timezone=True), nullable=False), Column("ended_at", DateTime(timezone=True)), Column("status", String, nullable=False), Column("records", Integer, nullable=False, default=0), Column("error", String))
tombstones = Table("hub_tombstones", metadata, Column("record_id", String(64), primary_key=True), Column("source", String, nullable=False), Column("deleted_at", DateTime(timezone=True), nullable=False))


def active_sources():
    return select(sources.c.id).where(sources.c.adapter.in_(SOURCE_KINDS))


class Store:
    def __init__(self, database_url: str, asset_root: str | Path, *, initialize=True):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.root = Path(asset_root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if initialize:
            metadata.create_all(self.engine)
            from .processing.schema import migrate
            migrate(self)

    @contextlib.contextmanager
    def lock(self, key: str):
        """跨进程锁：共享数据库的所有采集进程使用相同锁域。"""
        number = self.lock_id(key)
        if self.engine.dialect.name == "postgresql":
            with self.engine.connect() as connection:
                if key == "hub-asset-and-record-writer":
                    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": number})
                    ok = True
                else:
                    ok = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": number})
                connection.commit()
                if not ok:
                    raise RuntimeError("collector_busy")
                try:
                    yield
                finally:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": number})
                    connection.commit()
        else:
            path = self.root / (digest(key) + ".lock")
            with path.open("a") as handle:
                mode = fcntl.LOCK_EX if key == "hub-asset-and-record-writer" else fcntl.LOCK_EX | fcntl.LOCK_NB
                fcntl.flock(handle, mode)
                yield

    @staticmethod
    def lock_id(key: str) -> int:
        return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)

    @contextlib.contextmanager
    def writer_lock(self, connection=None):
        if connection is not None and self.engine.dialect.name == "postgresql":
            # CRM 的归档和原表共用事务；锁必须留到该事务提交，不能另开连接。
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": self.lock_id("hub-asset-and-record-writer")})
            yield
        else:
            with self.lock("hub-asset-and-record-writer"):
                yield

    def identity(self, source: str, external_id: str) -> str:
        # source 注册 ID 包含账户，不能跨账户去重。
        return digest([source, str(external_id)])

    def register(self, source: str, account: str, adapter: str, deletion_support: str):
        if adapter not in SOURCE_KINDS:
            raise ValueError("unsupported_source_adapter")
        values = dict(id=source, account=account, adapter=adapter, deletion_support=deletion_support)
        with self.engine.begin() as c:
            existing = c.execute(select(sources).where(sources.c.id == source)).mappings().first()
            if existing:
                if existing["account"] != account: raise ValueError("source_account_cannot_change")
                c.execute(update(sources).where(sources.c.id == source).values(**values))
            else:
                c.execute(insert(sources).values(**values))

    def cursor(self, source: str) -> dict:
        with self.engine.connect() as c:
            return c.scalar(select(checkpoints.c.value).where(checkpoints.c.source == source)) or {}

    def put_asset(self, asset: Asset) -> dict:
        if (asset.path is None) == (asset.content is None):
            raise ValueError("asset_requires_exactly_one_input")
        h = hashlib.sha256()
        with tempfile.NamedTemporaryFile(dir=self.root, prefix=".asset-", delete=False) as out:
            tmp = Path(out.name)
            os.chmod(tmp, 0o600)
            try:
                if asset.path is not None:
                    with asset.path.open("rb") as src:
                        for block in iter(lambda: src.read(1024 * 1024), b""):
                            h.update(block); out.write(block)
                else:
                    h.update(asset.content); out.write(asset.content)
                out.flush(); os.fsync(out.fileno())
                size = out.tell()
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        key = h.hexdigest()
        final = self.root / key[:2] / key
        final.parent.mkdir(exist_ok=True, mode=0o700)
        if os.geteuid() == 0:
            owner = self.root.stat()
            # Docker 和宿主采集器共用目录，文件归持久目录的原所有者。
            os.chown(tmp, owner.st_uid, owner.st_gid)
            os.chown(final.parent, owner.st_uid, owner.st_gid)
        try:
            if final.exists():
                tmp.unlink()
            else:
                os.replace(tmp, final)
                fd = os.open(final.parent, os.O_DIRECTORY)
                try: os.fsync(fd)
                finally: os.close(fd)
        finally:
            tmp.unlink(missing_ok=True)
        return dict(id=key, size=size, name=Path(asset.name).name, media_type=asset.media_type)

    def _purge(self, c, source: str, external_id: str):
        rid = self.identity(source, external_id)
        from .processing.repository import ProcessingRepository
        ProcessingRepository(self).removed(c, rid)
        if source == "crm" and ":" in external_id:
            from personal_crm.storage.models import Base
            table_name, key = external_id.split(":", 1)
            if table_name in {"people", "interactions", "facts", "reminders"}:
                table = Base.metadata.tables[table_name]
                if table_name == "interactions":
                    row = c.execute(select(table).where(table.c.id == key)).mappings().first()
                    if row:
                        for alias in self.crm_event_aliases(row["source_type"], row["source_event_key"], row["source_message_key"]):
                            self._purge(c, source, alias)
                if table_name == "people":
                    for child_name in ("interactions", "facts", "reminders"):
                        child = Base.metadata.tables[child_name]
                        for child_id in list(c.scalars(select(child.c.id).where(child.c.person_id == key))):
                            self._purge(c, source, child_name + ":" + child_id)
                c.execute(delete(table).where(table.c.id == key))
        c.execute(delete(display_index).where(display_index.c.record_id == rid))
        c.execute(delete(previews).where(previews.c.record_id == rid))
        c.execute(delete(asset_refs).where(asset_refs.c.record_id == rid))
        c.execute(delete(revisions).where(revisions.c.record_id == rid))
        c.execute(delete(records).where(records.c.id == rid))
        if not c.scalar(select(tombstones.c.record_id).where(tombstones.c.record_id == rid)):
            c.execute(insert(tombstones).values(record_id=rid, source=source, deleted_at=utcnow()))

    @staticmethod
    def crm_event_aliases(source, event_key, message_key=None):
        return [prefix + digest([source, value]) for prefix, value in [("event:", event_key), ("message:", message_key)] if value]

    def crm_event_deleted(self, connection, source, event_key, message_key=None):
        keys = [self.identity("crm", alias) for alias in self.crm_event_aliases(source, event_key, message_key)]
        return bool(keys and connection.scalar(select(tombstones.c.record_id).where(tombstones.c.record_id.in_(keys)).limit(1)))

    def ingest(self, source: str, batch: Batch, connection=None, *, refresh_unchanged=True) -> dict:
        with (self.engine.connect() if connection is None else contextlib.nullcontext(connection)) as c:
            adapter = c.scalar(select(sources.c.adapter).where(sources.c.id == source))
        if adapter not in SOURCE_KINDS:
            raise ValueError('unsupported_source')
        if any(item.kind not in SOURCE_KINDS[adapter] for item in batch.records):
            raise ValueError('unsupported_record_kind')
        changed = duplicate = ignored = removed = 0
        with self.writer_lock(connection):
            with (self.engine.begin() if connection is None else contextlib.nullcontext(connection)) as c:
                identities = [self.identity(source, item.external_id) for item in batch.records]
                existing = {row['id']: row for row in c.execute(select(records.c.id, records.c.hash, records.c.assets, records.c.kind).where(records.c.id.in_(identities))).mappings()} if identities else {}
                deleted_ids = set(c.scalars(select(tombstones.c.record_id).where(tombstones.c.record_id.in_(identities)))) if identities else set()
                duplicates = []
                for item in batch.records:
                    rid = self.identity(source, item.external_id)
                    if rid in deleted_ids:
                        ignored += 1
                        continue  # 旧备份/离线重放不能复活已删除内容。
                    old = existing.get(rid)
                    attachments = [self.put_asset(a) for a in item.assets]
                    if source == "crm" and item.kind == "interactions" and old:
                        # 正文镜像和周期采集不撤销独立补齐的微信媒体。
                        retained = {a["id"]: a for a in old["assets"]}
                        for attachment in attachments:
                            retained.setdefault(attachment["id"], attachment)
                        attachments = list(retained.values())
                    body = dict(raw=item.raw, normalized=item.normalized, assets=attachments, occurred_at=item.occurred_at.isoformat() if item.occurred_at else None, updated_at=item.updated_at.isoformat() if item.updated_at else None, kind=item.kind, timezone=item.timezone)
                    key = digest(body)
                    now = utcnow()
                    if old and old["hash"] == key:
                        duplicates.append(rid)
                        duplicate += 1
                        continue
                    values = dict(id=rid, source=source, external_id=str(item.external_id), hash=key, occurred_at=item.occurred_at, updated_at=item.updated_at, observed_at=now, kind=item.kind, timezone=item.timezone, raw=item.raw, normalized=item.normalized, assets=attachments)
                    if old:
                        c.execute(update(records).where(records.c.id == rid).values(**values))
                    else:
                        c.execute(insert(records).values(**values))
                    self._put_preview(c, rid, item.kind, item.external_id, item.raw, item.normalized)
                    from .processing.registry import PROFILES
                    supported_kinds = {kind for profile in PROFILES.values() for kind in (*profile.KINDS, *getattr(profile, 'DEPENDENCY_KINDS', ()))}
                    if item.kind in supported_kinds or (old and old['kind'] in supported_kinds):
                        from .processing.repository import ProcessingRepository
                        ProcessingRepository(self).changed(c, values)
                    if not c.scalar(select(revisions.c.hash).where(revisions.c.record_id == rid, revisions.c.hash == key)):
                        c.execute(insert(revisions).values(record_id=rid, hash=key, observed_at=now, value=body))
                    for a in attachments:
                        if not c.scalar(select(assets.c.id).where(assets.c.id == a["id"])):
                            c.execute(insert(assets).values(id=a["id"], size=a["size"]))
                        if not c.scalar(select(asset_refs.c.asset_id).where(asset_refs.c.record_id == rid, asset_refs.c.asset_id == a["id"])):
                            c.execute(insert(asset_refs).values(record_id=rid, asset_id=a["id"]))
                    changed += 1
                    existing[rid] = values
                if duplicates and refresh_unchanged:
                    # Explicit observations/pushes can refresh per-record freshness.
                    # Periodic collectors record checks in hub_runs instead.
                    now = utcnow()
                    c.execute(update(records).where(records.c.id.in_(duplicates)).values(observed_at=now))
                    c.execute(update(display_index).where(display_index.c.record_id.in_(duplicates)).values(observed_at=now))
                deletions = set(batch.deletions)
                if batch.authoritative:
                    if batch.seen_ids is None:
                        raise ValueError("authoritative_inventory_requires_seen_ids")
                    all_ids = set(c.scalars(select(records.c.external_id).where(records.c.source == source)))
                    deletions.update(all_ids - set(batch.seen_ids))
                for external_id in deletions:
                    self._purge(c, source, external_id); removed += 1
                if batch.next_cursor is not None:
                    values = dict(source=source, value=batch.next_cursor, updated_at=utcnow())
                    if c.scalar(select(checkpoints.c.source).where(checkpoints.c.source == source)):
                        c.execute(update(checkpoints).where(checkpoints.c.source == source).values(**values))
                    else:
                        c.execute(insert(checkpoints).values(**values))
            # 文件清理失败可重试；数据库中的内容已经被清理，不回退删除账本。
            if connection is None and removed: self._gc()
        return dict(changed=changed, duplicates=duplicate, tombstoned=ignored, deleted=removed)

    def _gc(self):
        with self.engine.begin() as c:
            for key in c.scalars(select(assets.c.id).where(~assets.c.id.in_(select(asset_refs.c.asset_id)))):
                (self.root / key[:2] / key).unlink(missing_ok=True)
                c.execute(delete(assets).where(assets.c.id == key))

    def list_records(self, source=None, kind=None, offset=0, limit=100, start=None, end=None):
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid_pagination")
        statement = select(records).where(records.c.source.in_(active_sources())).order_by(records.c.occurred_at.desc().nulls_last(), records.c.id).offset(offset).limit(limit)
        if source: statement = statement.where(records.c.source == source)
        if kind: statement = statement.where(records.c.kind == kind)
        if start: statement = statement.where(records.c.occurred_at >= start)
        if end: statement = statement.where(records.c.occurred_at < end)
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(statement).mappings()]

    def get_record(self, record_id):
        with self.engine.connect() as c:
            row = c.execute(select(records).where(records.c.id == record_id)).mappings().first()
            return dict(row) if row else None

    def browse(self, source=None, kind=None, query="", offset=0, limit=50, start=None, end=None):
        """只投影可读字段，列表不传输原始 AX 事件和长正文。"""
        if offset < 0 or not 1 <= limit <= 100 or len(query) > 200:
            raise ValueError("invalid_browse_parameters")
        return self.record_page(source, kind, offset, limit, start, end, query=query)

    def record_page(self, source=None, kind=None, offset=0, limit=100, start=None, end=None, include_content=False, query=""):
        """公共列表默认只读有界摘要；显式选择正文时才读取原始载荷。"""
        if offset < 0 or not 1 <= limit <= 1000 or len(query) > 200:
            raise ValueError("invalid_pagination")
        # 不在 SQL 中解析原始 JSON：PG JSON 的 ->> 也会拒绝 AX 中的 NUL。
        title = func.coalesce(previews.c.title, records.c.kind)
        preview = func.coalesce(previews.c.preview, records.c.external_id)
        joined = records.outerjoin(previews, records.c.id == previews.c.record_id)
        conditions = [records.c.source.in_(active_sources())]
        if source: conditions.append(records.c.source == source)
        if kind: conditions.append(records.c.kind == kind)
        if start: conditions.append(records.c.occurred_at >= start)
        if end: conditions.append(records.c.occurred_at < end)
        if query:
            conditions.append((title + " " + preview).icontains(query, autoescape=True))
        columns = [records.c.id, records.c.source, records.c.kind, records.c.occurred_at,
                   records.c.observed_at, records.c.timezone,
                   func.substr(title, 1, 160).label("title"), func.substr(preview, 1, 500).label("preview")]
        statement = select(*columns).select_from(joined).where(*conditions).order_by(records.c.occurred_at.desc().nulls_last(), records.c.id).offset(offset).limit(limit + 1)
        with self.engine.connect() as c:
            rows = [dict(r) for r in c.execute(statement).mappings()]
            total = c.scalar(select(func.count()).select_from(joined).where(*conditions))
            page = rows[:limit]
            if include_content and page:
                # 探测下一页只读摘要，不额外读取一条可能很大的原始载荷。
                full = {r["id"]: dict(r) for r in c.execute(select(records).where(records.c.id.in_([r["id"] for r in page]))).mappings()}
                page = [full[r["id"]] for r in page if r["id"] in full]
        return {"records": page, "total": total, "next_offset": offset + limit if len(rows) > limit else None}

    @staticmethod
    def preview_fields(kind, external_id, raw, normalized):
        def first(*values):
            return next((value for value in values if isinstance(value, str) and value.strip()), "")
        bill = raw.get("bill", {}) if isinstance(raw.get("bill"), dict) else {}
        amount = str(normalized.get("amount", ""))
        title = first(normalized.get("title"), normalized.get("subject"), raw.get("title"), raw.get("display_name"), raw.get("name"), kind)
        preview = first(normalized.get("content"), normalized.get("message"), raw.get("summary"), raw.get("content"), normalized.get("body"), bill.get("remark"), raw.get("path"), str(external_id))
        if kind == "recording":
            title = "Plaud 录音 · " + str(normalized.get("date", ""))
            preview = first(normalized.get("summary"), normalized.get("transcript"), f"{int(normalized.get('duration_ms', 0) / 60000)} 分钟")
        if kind == "bill": preview = " ".join(x for x in [str(normalized.get("type", bill.get("type", ""))), amount, str(normalized.get("currency") or ""), preview] if x)
        return {"title": title[:160].replace("\x00", ""), "preview": preview[:500].replace("\x00", "")}

    def _put_preview(self, connection, rid, kind, external_id, raw, normalized):
        values = self.preview_fields(kind, external_id, raw, normalized)
        if connection.scalar(select(previews.c.record_id).where(previews.c.record_id == rid)):
            connection.execute(update(previews).where(previews.c.record_id == rid).values(**values))
        else:
            connection.execute(insert(previews).values(record_id=rid, **values))
        from .display import index_value
        row = connection.execute(select(records.c.source, records.c.occurred_at, records.c.observed_at).where(records.c.id == rid)).mappings().one()
        value = index_value(kind, external_id, raw, normalized)
        indexed = dict(record_id=rid, source=row["source"], kind=kind, occurred_at=row["occurred_at"], observed_at=row["observed_at"], **value)
        if connection.scalar(select(display_index.c.record_id).where(display_index.c.record_id == rid)):
            connection.execute(update(display_index).where(display_index.c.record_id == rid).values(**indexed))
        else:
            connection.execute(insert(display_index).values(**indexed))

    def backfill_display(self, rebuild=False, kind=None):
        if rebuild:
            with self.writer_lock(), self.engine.begin() as c:
                statement = delete(display_index)
                if kind: statement = statement.where(display_index.c.kind == kind)
                c.execute(statement)
        count = 0
        while True:
            with self.engine.connect() as c:
                statement = select(records.c.id).outerjoin(display_index, records.c.id == display_index.c.record_id).where(display_index.c.record_id.is_(None), records.c.source.in_(active_sources()))
                if kind: statement = statement.where(records.c.kind == kind)
                ids = list(c.scalars(statement.order_by(records.c.id).limit(100)))
            if not ids: return count
            with self.writer_lock(), self.engine.begin() as c:
                from .display import index_value
                values = []
                for row in c.execute(select(records).outerjoin(display_index, records.c.id == display_index.c.record_id).where(records.c.id.in_(ids), display_index.c.record_id.is_(None))).mappings():
                    value = index_value(row["kind"], row["external_id"], row["raw"], row["normalized"])
                    values.append(dict(record_id=row["id"], source=row["source"], kind=row["kind"], occurred_at=row["occurred_at"], observed_at=row["observed_at"], **value))
                if values: c.execute(insert(display_index), values)
                count += len(values)

    def backfill_previews(self):
        """已有归档一次性补齐；小批次锁避免长期阻塞推送，不改变原始内容。"""
        count = 0
        while True:
            with self.engine.connect() as c:
                rows = list(c.execute(select(records).outerjoin(previews, records.c.id == previews.c.record_id).where(previews.c.record_id.is_(None), records.c.source.in_(active_sources())).order_by(records.c.id).limit(20)).mappings())
            if not rows: return count
            with self.writer_lock():
                with self.engine.begin() as c:
                    for row in rows:
                        current = c.scalar(select(records.c.hash).where(records.c.id == row["id"]))
                        if current == row["hash"] and not c.scalar(select(previews.c.record_id).where(previews.c.record_id == row["id"])):
                            self._put_preview(c, row["id"], row["kind"], row["external_id"], row["raw"], row["normalized"])
                            count += 1

    def recording_content(self, record_id):
        row = self.get_record(record_id)
        if not row or row["kind"] != "recording": return None
        n = row["normalized"]
        daily_id = n.get("daily_report_external_id")
        daily = self.get_record(self.identity(row["source"], daily_id)) if daily_id else None
        return {"record_id": row["id"], "recording_id": row["external_id"], "date": n.get("date"),
                "duration_ms": n.get("duration_ms"), **{key: n.get(key) for key in
                ("transcript", "transcript_engine", "transcription_status", "transcript_is_draft", "transcripts", "summary", "summary_scope", "summary_status", "processing")},
                "daily_report": {"record_id": daily["id"], **daily["normalized"]} if daily else None}

    def kinds(self, source=None):
        statement = select(records.c.kind, func.count().label("count")).where(records.c.source.in_(active_sources())).group_by(records.c.kind).order_by(records.c.kind)
        if source: statement = statement.where(records.c.source == source)
        with self.engine.connect() as c:
            return [dict(row) for row in c.execute(statement).mappings()]

    def asset_path(self, asset_id: str):
        if len(asset_id) != 64 or any(x not in "0123456789abcdef" for x in asset_id):
            return None
        with self.engine.connect() as c:
            if not c.scalar(select(asset_refs.c.asset_id).where(asset_refs.c.asset_id == asset_id).limit(1)):
                return None
        path = self.root / asset_id[:2] / asset_id
        return path if path.is_file() else None

    def status(self):
        with self.engine.connect() as c:
            result = []
            # The status endpoint is polled by collectors and clients. Aggregate
            # narrow columns once instead of rescanning each source twice.
            statistics = {row['source']: row for row in c.execute(
                select(records.c.source, func.count().label('count'),
                       func.max(records.c.observed_at).label('last_observed_at')).where(records.c.source.in_(active_sources())).group_by(records.c.source)).mappings()}
            ranked = select(runs, func.row_number().over(partition_by=runs.c.source,
                            order_by=(runs.c.started_at.desc(), runs.c.id.desc())).label('position')).subquery()
            latest_runs = {row['source']: {k:v for k,v in row.items() if k != 'position'}
                           for row in c.execute(select(ranked).where(ranked.c.position == 1)).mappings()}
            invalid_counts = dict(c.execute(select(records.c.source, func.count()).where(records.c.kind == "computer_segment_invalid").group_by(records.c.source)).all())
            for row in c.execute(select(sources).where(sources.c.id.in_(active_sources()))).mappings():
                source = row["id"]
                latest = latest_runs.get(source)
                stats = statistics.get(source, {'count':0, 'last_observed_at':None})
                warnings = [{"code": "historical_segment_invalid", "count": invalid_counts[source]}] if invalid_counts.get(source) else []
                result.append({**dict(row), **{key:stats[key] for key in ('count','last_observed_at')}, "last_run": dict(latest) if latest else None, "quality_warnings": warnings})
            return result
