from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, MetaData, String, Table, Text, create_engine, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import JSONB

from .contracts import Asset, Batch, Record, canonical, digest, utcnow

metadata = MetaData()
# 原始 UI/AX 事件可能带 NUL；PostgreSQL JSONB 拒绝它，JSON 能原样归档转义值。
jtype = JSON()
sources = Table("hub_sources", metadata, Column("id", String, primary_key=True), Column("account", String, nullable=False), Column("adapter", String, nullable=False), Column("deletion_support", String, nullable=False))
records = Table("hub_records", metadata, Column("id", String(64), primary_key=True), Column("source", String, nullable=False, index=True), Column("external_id", Text, nullable=False), Column("kind", String, nullable=False, index=True), Column("occurred_at", DateTime(timezone=True), index=True), Column("updated_at", DateTime(timezone=True)), Column("observed_at", DateTime(timezone=True), nullable=False), Column("timezone", String, nullable=False), Column("hash", String(64), nullable=False), Column("raw", jtype, nullable=False), Column("normalized", jtype, nullable=False), Column("assets", jtype, nullable=False))
revisions = Table("hub_revisions", metadata, Column("record_id", ForeignKey("hub_records.id", ondelete="CASCADE"), primary_key=True), Column("hash", String(64), primary_key=True), Column("observed_at", DateTime(timezone=True), nullable=False), Column("value", jtype, nullable=False))
assets = Table("hub_assets", metadata, Column("id", String(64), primary_key=True), Column("size", Integer, nullable=False))
asset_refs = Table("hub_asset_refs", metadata, Column("record_id", ForeignKey("hub_records.id", ondelete="CASCADE"), primary_key=True), Column("asset_id", ForeignKey("hub_assets.id"), primary_key=True))
checkpoints = Table("hub_checkpoints", metadata, Column("source", String, primary_key=True), Column("value", jtype, nullable=False), Column("updated_at", DateTime(timezone=True), nullable=False))
runs = Table("hub_runs", metadata, Column("id", String, primary_key=True), Column("source", String, nullable=False, index=True), Column("started_at", DateTime(timezone=True), nullable=False), Column("ended_at", DateTime(timezone=True)), Column("status", String, nullable=False), Column("records", Integer, nullable=False, default=0), Column("error", String))
tombstones = Table("hub_tombstones", metadata, Column("record_id", String(64), primary_key=True), Column("source", String, nullable=False), Column("deleted_at", DateTime(timezone=True), nullable=False))


class Store:
    def __init__(self, database_url: str, asset_root: str | Path):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.root = Path(asset_root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata.create_all(self.engine)

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
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
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

    def ingest(self, source: str, batch: Batch, connection=None) -> dict:
        changed = duplicate = ignored = removed = 0
        with self.writer_lock(connection):
            with (self.engine.begin() if connection is None else contextlib.nullcontext(connection)) as c:
                for item in batch.records:
                    rid = self.identity(source, item.external_id)
                    if c.scalar(select(tombstones.c.record_id).where(tombstones.c.record_id == rid)):
                        ignored += 1
                        continue  # 旧备份/离线重放不能复活已删除内容。
                    attachments = [self.put_asset(a) for a in item.assets]
                    body = dict(raw=item.raw, normalized=item.normalized, assets=attachments, occurred_at=item.occurred_at.isoformat() if item.occurred_at else None, updated_at=item.updated_at.isoformat() if item.updated_at else None, kind=item.kind, timezone=item.timezone)
                    key = digest(body)
                    old = c.execute(select(records).where(records.c.id == rid)).mappings().first()
                    now = utcnow()
                    if old and old["hash"] == key:
                        c.execute(update(records).where(records.c.id == rid).values(observed_at=now))
                        duplicate += 1
                        continue
                    values = dict(id=rid, source=source, external_id=str(item.external_id), hash=key, occurred_at=item.occurred_at, updated_at=item.updated_at, observed_at=now, kind=item.kind, timezone=item.timezone, raw=item.raw, normalized=item.normalized, assets=attachments)
                    if old:
                        c.execute(update(records).where(records.c.id == rid).values(**values))
                    else:
                        c.execute(insert(records).values(**values))
                    if not c.scalar(select(revisions.c.hash).where(revisions.c.record_id == rid, revisions.c.hash == key)):
                        c.execute(insert(revisions).values(record_id=rid, hash=key, observed_at=now, value=body))
                    for a in attachments:
                        if not c.scalar(select(assets.c.id).where(assets.c.id == a["id"])):
                            c.execute(insert(assets).values(id=a["id"], size=a["size"]))
                        if not c.scalar(select(asset_refs.c.asset_id).where(asset_refs.c.record_id == rid, asset_refs.c.asset_id == a["id"])):
                            c.execute(insert(asset_refs).values(record_id=rid, asset_id=a["id"]))
                    changed += 1
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
            if connection is None: self._gc()
        return dict(changed=changed, duplicates=duplicate, tombstoned=ignored, deleted=removed)

    def _gc(self):
        with self.engine.begin() as c:
            for key in c.scalars(select(assets.c.id).where(~assets.c.id.in_(select(asset_refs.c.asset_id)))):
                (self.root / key[:2] / key).unlink(missing_ok=True)
                c.execute(delete(assets).where(assets.c.id == key))

    def list_records(self, source=None, kind=None, offset=0, limit=100, start=None, end=None):
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid_pagination")
        statement = select(records).order_by(records.c.occurred_at.desc().nulls_last(), records.c.id).offset(offset).limit(limit)
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
            for row in c.execute(select(sources)).mappings():
                source = row["id"]
                latest = c.execute(select(runs).where(runs.c.source == source).order_by(runs.c.started_at.desc()).limit(1)).mappings().first()
                result.append({**dict(row), "count": c.scalar(select(func.count()).select_from(records).where(records.c.source == source)), "last_observed_at": c.scalar(select(func.max(records.c.observed_at)).where(records.c.source == source)), "last_run": dict(latest) if latest else None})
            return result
