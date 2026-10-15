"""人物、交互和增量归档的单一入口。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Date,
    and_,
    cast,
    create_engine,
    delete,
    event,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.pool import StaticPool

from personal_crm.core.domain import ensure_utc, utcnow, uuid7

from .models import (
    attachment_links,
    attachments,
    clients,
    identities,
    interactions,
    messages,
    metadata,
    participants,
    people,
)
from .schemas import (
    IdentityInput,
    InteractionCreate,
    InteractionPatch,
    PersonCreate,
    PersonPatch,
    WechatBatch,
)

ZONE = ZoneInfo("Asia/Shanghai")


def sqlite_foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


def encode_cursor(values):
    return base64.urlsafe_b64encode(json.dumps(values, default=str).encode()).decode()


def decode_cursor(value, size):
    try:
        data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(data, list) or len(data) != size:
            raise ValueError()
        return data
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_cursor") from exc


def unique(values):
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


class Archive:
    def __init__(
        self,
        url="sqlite:///:memory:",
        asset_root="data/crm-assets",
        *,
        engine=None,
        gap_minutes=30,
        create_schema=True,
        asset_lock=nullcontext,
    ):
        if gap_minutes <= 0:
            raise ValueError("WECHAT_INTERACTION_GAP_MINUTES must be positive")
        if engine is None:
            options = (
                {"connect_args": {"check_same_thread": False, "timeout": 30}}
                if url.startswith("sqlite:")
                else {}
            )
            if url in ("sqlite://", "sqlite:///:memory:"):
                options["poolclass"] = StaticPool
            engine = create_engine(url, **options)

        self.engine = engine
        if engine.dialect.name == "sqlite":
            if not event.contains(engine, "connect", sqlite_foreign_keys):
                event.listen(engine, "connect", sqlite_foreign_keys)
            with engine.connect() as c:
                c.exec_driver_sql("PRAGMA foreign_keys=ON")
        self.root = Path(asset_root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.gap = timedelta(minutes=gap_minutes)
        self._mutex = threading.RLock()
        self._asset_lock = asset_lock
        if create_schema:
            metadata.create_all(engine)

    @contextmanager
    def write(self):
        # One transaction covers both text edits and append; never read-edit-write outside it.
        with self._mutex, self.engine.connect() as c:
            with c.begin():
                if c.dialect.name == "sqlite":
                    c.exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    c.execute(text("SELECT pg_advisory_xact_lock(214173813)"))
                yield c

    @staticmethod
    def _require(c, table, key):
        row = c.execute(select(table).where(table.c.id == key)).mappings().first()
        if row is None:
            raise NotFound(table.name + "_not_found")
        return dict(row)

    @staticmethod
    def _person_values(values):
        if values.get("name", "") is None:
            raise ValueError("name cannot be null")
        for key in ("aliases", "tags"):
            if key in values:
                values[key] = unique(values[key] or [])
        if "contacts" in values:
            values["contacts"] = [
                dict(type=k, value=v)
                for k, v in dict.fromkeys((x["type"], x["value"]) for x in values["contacts"] or [])
            ]
        if "notes" in values:
            values["notes"] = values["notes"] or ""
        return values

    def _local_day(self, column):
        return (
            func.date(column, "+8 hours")
            if self.engine.dialect.name == "sqlite"
            else cast(func.timezone("Asia/Shanghai", column), Date)
        )

    def _recent_columns(self):
        at = func.coalesce(interactions.c.ended_at, interactions.c.started_at)
        return func.coalesce(self._local_day(at), interactions.c.date), at

    def _person(self, c, pid):
        last_date, last_at = self._recent_columns()
        row = self._require(c, people, pid)
        row["identities"] = [
            dict(r)
            for r in c.execute(
                select(identities.c.source, identities.c.account, identities.c.external_id).where(
                    identities.c.person_id == pid
                )
            ).mappings()
        ]
        last = (
            c.execute(
                select(last_date.label("date"), interactions.c.started_at, interactions.c.ended_at)
                .join(participants, participants.c.interaction_id == interactions.c.id)
                .where(participants.c.person_id == pid)
                .order_by(last_date.desc(), last_at.desc().nulls_last(), interactions.c.id)
                .limit(1)
            )
            .mappings()
            .first()
        )
        row["last_interaction_date"] = last["date"] if last else None
        row["last_interaction_at"] = (last["ended_at"] or last["started_at"]) if last else None
        return row

    def create_person(self, data):
        values = self._person_values(PersonCreate.model_validate(data).model_dump())
        now, key = utcnow(), uuid7()
        with self.write() as c:
            c.execute(insert(people).values(id=key, **values, created_at=now, updated_at=now))
            return self._person(c, key)

    def get_person(self, person_id):
        with self.engine.connect() as c:
            return self._person(c, person_id)

    def update_person(self, person_id, data):
        values = self._person_values(
            PersonPatch.model_validate(data).model_dump(exclude_unset=True)
        )
        with self.write() as c:
            self._require(c, people, person_id)
            c.execute(
                update(people).where(people.c.id == person_id).values(**values, updated_at=utcnow())
            )
            return self._person(c, person_id)

    def bind_person_identity(self, person_id, data):
        values = IdentityInput.model_validate(data).model_dump()
        with self.write() as c:
            self._require(c, people, person_id)
            row = (
                c.execute(
                    select(identities).where(*(identities.c[k] == v for k, v in values.items()))
                )
                .mappings()
                .first()
            )
            if row:
                c.execute(
                    update(identities)
                    .where(identities.c.id == row["id"])
                    .values(person_id=person_id)
                )
                # Rebinding the source also corrects its history; shared participants survive.
                history = list(
                    c.scalars(
                        select(interactions.c.id).where(interactions.c.identity_id == row["id"])
                    )
                )
                for iid in history:
                    c.execute(
                        delete(participants).where(
                            participants.c.interaction_id == iid,
                            participants.c.person_id == row["person_id"],
                        )
                    )
                    if not c.scalar(
                        select(participants.c.person_id).where(
                            participants.c.interaction_id == iid,
                            participants.c.person_id == person_id,
                        )
                    ):
                        c.execute(
                            insert(participants).values(interaction_id=iid, person_id=person_id)
                        )
            else:
                c.execute(insert(identities).values(id=uuid7(), person_id=person_id, **values))
            return self._person(c, person_id)

    def merge_people(self, source_id, target_id):
        if source_id == target_id:
            raise ValueError("source and target must differ")
        with self.write() as c:
            source = self._require(c, people, source_id)
            target = self._require(c, people, target_id)
            values = dict(
                name=target["name"],
                relationship=target["relationship"] or source["relationship"],
                notes=target["notes"] or source["notes"],
                aliases=unique(target["aliases"] + source["aliases"] + [source["name"]]),
                tags=unique(target["tags"] + source["tags"]),
                contacts=target["contacts"] + source["contacts"],
            )
            c.execute(
                update(people)
                .where(people.c.id == target_id)
                .values(**self._person_values(values), updated_at=utcnow())
            )
            c.execute(
                update(identities)
                .where(identities.c.person_id == source_id)
                .values(person_id=target_id)
            )
            for iid in c.scalars(
                select(participants.c.interaction_id).where(participants.c.person_id == source_id)
            ):
                if not c.scalar(
                    select(participants.c.person_id).where(
                        participants.c.interaction_id == iid, participants.c.person_id == target_id
                    )
                ):
                    c.execute(insert(participants).values(interaction_id=iid, person_id=target_id))
            c.execute(delete(people).where(people.c.id == source_id))
            return self._person(c, target_id)

    def delete_person(self, person_id):
        with self.write() as c:
            self._require(c, people, person_id)
            ids = list(
                c.scalars(
                    select(participants.c.interaction_id).where(
                        participants.c.person_id == person_id
                    )
                )
            )
            for iid in ids:
                count = c.scalar(
                    select(func.count())
                    .select_from(participants)
                    .where(participants.c.interaction_id == iid)
                )
                if count == 1:
                    self._delete_interaction(c, iid)
            c.execute(delete(people).where(people.c.id == person_id))
            return {"deleted": True}

    @staticmethod
    def _interaction_values(data):
        for key in ("type", "date", "content", "source", "person_ids"):
            if key in data and data[key] is None:
                raise ValueError(key + " cannot be null")
        if data.get("ended_at") and not data.get("started_at"):
            raise ValueError("ended_at requires started_at")
        for key in ("started_at", "ended_at"):
            if data.get(key):
                if data[key].tzinfo is None:
                    raise ValueError(key + " requires a timezone")
                data[key] = ensure_utc(data[key])
        if (
            data.get("started_at")
            and data.get("ended_at")
            and data["ended_at"] < data["started_at"]
        ):
            raise ValueError("ended_at precedes started_at")
        return data

    def _set_links(self, c, iid, table, column, keys, target):
        keys = list(dict.fromkeys(keys or []))
        if table is participants and not keys:
            raise ValueError("person_ids must not be empty")
        if keys:
            found = set(c.scalars(select(target.c.id).where(target.c.id.in_(keys))))
            if set(keys) != found:
                raise NotFound(target.name + "_not_found")
        c.execute(delete(table).where(table.c.interaction_id == iid))
        if keys:
            c.execute(insert(table), [dict(interaction_id=iid, **{column: key}) for key in keys])

    def _interaction(self, c, iid, *, full=True):
        row = self._require(c, interactions, iid)
        row.pop("identity_id")
        row["person_ids"] = list(
            c.scalars(
                select(participants.c.person_id)
                .where(participants.c.interaction_id == iid)
                .order_by(participants.c.person_id)
            )
        )
        row["attachment_ids"] = list(
            c.scalars(
                select(attachment_links.c.attachment_id)
                .where(attachment_links.c.interaction_id == iid)
                .order_by(attachment_links.c.attachment_id)
            )
        )
        if not full:
            row["preview"] = row.pop("content")[:500]
            row["attachment_count"] = len(row.pop("attachment_ids"))
        return row

    def create_interaction(self, data):
        values = self._interaction_values(InteractionCreate.model_validate(data).model_dump())
        pids, aids = values.pop("person_ids"), values.pop("attachment_ids")
        now, key = utcnow(), uuid7()
        with self.write() as c:
            c.execute(insert(interactions).values(id=key, **values, created_at=now, updated_at=now))
            self._set_links(c, key, participants, "person_id", pids, people)
            self._set_links(c, key, attachment_links, "attachment_id", aids, attachments)
            return self._interaction(c, key)

    def get_interaction(self, interaction_id):
        with self.engine.connect() as c:
            return self._interaction(c, interaction_id)

    def update_interaction(self, interaction_id, data):
        patch = InteractionPatch.model_validate(data).model_dump(exclude_unset=True)
        with self.write() as c:
            old = self._require(c, interactions, interaction_id)
            self._interaction_values({**old, **patch})
            if "person_ids" in patch:
                self._set_links(
                    c, interaction_id, participants, "person_id", patch.pop("person_ids"), people
                )
            if "attachment_ids" in patch:
                self._set_links(
                    c,
                    interaction_id,
                    attachment_links,
                    "attachment_id",
                    patch.pop("attachment_ids"),
                    attachments,
                )
            self._interaction_values({**old, **patch})
            c.execute(
                update(interactions)
                .where(interactions.c.id == interaction_id)
                .values(**patch, updated_at=utcnow())
            )
            return self._interaction(c, interaction_id)

    @staticmethod
    def _delete_interaction(c, iid):
        # The FK keeps only the consumed message keys, so a retry cannot recreate text.
        c.execute(delete(interactions).where(interactions.c.id == iid))

    def delete_interaction(self, interaction_id):
        with self.write() as c:
            self._require(c, interactions, interaction_id)
            self._delete_interaction(c, interaction_id)
            return {"deleted": True}

    @staticmethod
    def _page(limit):
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

    def list_interactions(
        self,
        *,
        person_id=None,
        start=None,
        end=None,
        type=None,
        channel=None,
        source=None,
        query="",
        limit=50,
        cursor=None,
    ):
        self._page(limit)
        conditions = []
        if person_id:
            conditions.append(
                interactions.c.id.in_(
                    select(participants.c.interaction_id).where(
                        participants.c.person_id == person_id
                    )
                )
            )
        if start:
            conditions.append(
                or_(
                    (
                        func.date(interactions.c.ended_at, "+8 hours")
                        if self.engine.dialect.name == "sqlite"
                        else cast(
                            func.timezone("Asia/Shanghai", interactions.c.ended_at),
                            __import__("sqlalchemy").Date,
                        )
                    )
                    >= date.fromisoformat(str(start)),
                    and_(
                        interactions.c.ended_at.is_(None),
                        interactions.c.date >= date.fromisoformat(str(start)),
                    ),
                )
            )
        if end:
            conditions.append(interactions.c.date <= date.fromisoformat(str(end)))
        if start and end and str(start) > str(end):
            raise ValueError("start must not follow end")
        for key, value in (("type", type), ("channel", channel), ("source", source)):
            if value is not None:
                conditions.append(interactions.c[key] == value)
        if query:
            conditions.append(interactions.c.content.icontains(query, autoescape=True))
        if cursor:
            d, t, key = decode_cursor(cursor, 3)
            d, t = date.fromisoformat(d), datetime.fromisoformat(t) if t else None
            within = (
                or_(
                    interactions.c.started_at < t,
                    interactions.c.started_at.is_(None),
                    and_(interactions.c.started_at == t, interactions.c.id > key),
                )
                if t
                else and_(interactions.c.started_at.is_(None), interactions.c.id > key)
            )
            conditions.append(or_(interactions.c.date < d, and_(interactions.c.date == d, within)))
        with self.engine.connect() as c:
            columns = [col for col in interactions.c if col.name not in {"content", "identity_id"}]
            rows = list(
                c.execute(
                    select(*columns, func.substr(interactions.c.content, 1, 500).label("preview"))
                    .where(*conditions)
                    .order_by(
                        interactions.c.date.desc(),
                        interactions.c.started_at.desc().nulls_last(),
                        interactions.c.id,
                    )
                    .limit(limit + 1)
                ).mappings()
            )
            result = [dict(r, person_ids=[], attachment_count=0) for r in rows[:limit]]
            by_id = {r["id"]: r for r in result}
            if by_id:
                for iid, pid in c.execute(
                    select(participants)
                    .where(participants.c.interaction_id.in_(by_id))
                    .order_by(participants.c.person_id)
                ):
                    by_id[iid]["person_ids"].append(pid)
                for iid, count in c.execute(
                    select(attachment_links.c.interaction_id, func.count())
                    .where(attachment_links.c.interaction_id.in_(by_id))
                    .group_by(attachment_links.c.interaction_id)
                ):
                    by_id[iid]["attachment_count"] = count
        last = rows[limit - 1] if len(rows) > limit else None
        return {
            "items": result,
            "next_cursor": encode_cursor([last["date"], last["started_at"], last["id"]])
            if last
            else None,
        }

    def list_people(self, *, query="", tag=None, limit=50, cursor=None):
        self._page(limit)
        last_date, last_at = self._recent_columns()
        rank = (
            select(
                participants.c.person_id,
                last_date.label("last_date"),
                last_at.label("last_at"),
                interactions.c.ended_at.label("last_end"),
                func.row_number()
                .over(
                    partition_by=participants.c.person_id,
                    order_by=(last_date.desc(), last_at.desc().nulls_last(), interactions.c.id),
                )
                .label("rn"),
            )
            .join(interactions, interactions.c.id == participants.c.interaction_id)
            .subquery()
        )
        latest = select(rank).where(rank.c.rn == 1).subquery()
        conditions = []
        if query:
            pattern = (
                "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            if self.engine.dialect.name == "sqlite":
                alias_search = "EXISTS (SELECT 1 FROM json_each(crm_people.aliases) a WHERE a.value LIKE :pattern ESCAPE '\\')"
                contact_search = "EXISTS (SELECT 1 FROM json_each(crm_people.contacts) a WHERE json_extract(a.value, '$.value') LIKE :pattern ESCAPE '\\')"
            else:
                alias_search = "EXISTS (SELECT 1 FROM jsonb_array_elements_text(crm_people.aliases::jsonb) a(value) WHERE a.value ILIKE :pattern ESCAPE '\\')"
                contact_search = "EXISTS (SELECT 1 FROM jsonb_array_elements(crm_people.contacts::jsonb) a(value) WHERE a.value->>'value' ILIKE :pattern ESCAPE '\\')"
            conditions.append(
                or_(
                    people.c.name.icontains(query, autoescape=True),
                    people.c.notes.icontains(query, autoescape=True),
                    text(alias_search).bindparams(pattern=pattern),
                    text(contact_search).bindparams(pattern=pattern),
                )
            )
        if tag:
            expression = (
                "EXISTS (SELECT 1 FROM json_each(crm_people.tags) j WHERE j.value = :tag)"
                if self.engine.dialect.name == "sqlite"
                else "EXISTS (SELECT 1 FROM jsonb_array_elements_text(crm_people.tags::jsonb) j(value) WHERE j.value = :tag)"
            )
            conditions.append(text(expression).bindparams(tag=tag))
        if cursor:
            d, t, key = decode_cursor(cursor, 3)
            if d:
                d, t = date.fromisoformat(d), datetime.fromisoformat(t) if t else None
                within = (
                    or_(
                        latest.c.last_at < t,
                        latest.c.last_at.is_(None),
                        and_(latest.c.last_at == t, people.c.id > key),
                    )
                    if t
                    else and_(latest.c.last_at.is_(None), people.c.id > key)
                )
                conditions.append(
                    or_(
                        latest.c.last_date < d,
                        latest.c.last_date.is_(None),
                        and_(latest.c.last_date == d, within),
                    )
                )
            else:
                conditions.append(and_(latest.c.last_date.is_(None), people.c.id > key))
        with self.engine.connect() as c:
            rows = list(
                c.execute(
                    select(people, latest.c.last_date, latest.c.last_at, latest.c.last_end)
                    .outerjoin(latest, latest.c.person_id == people.c.id)
                    .where(*conditions)
                    .order_by(
                        latest.c.last_date.desc().nulls_last(),
                        latest.c.last_at.desc().nulls_last(),
                        people.c.id,
                    )
                    .limit(limit + 1)
                ).mappings()
            )
            result = []
            for item in rows[:limit]:
                row = dict(item)
                row["last_interaction_date"] = row.pop("last_date")
                row["last_interaction_at"] = row.pop("last_end") or row["last_at"]
                row.pop("last_at")
                row["identities"] = []
                result.append(row)
            by_id = {r["id"]: r for r in result}
            if by_id:
                for identity in c.execute(
                    select(identities).where(identities.c.person_id.in_(by_id))
                ).mappings():
                    by_id[identity["person_id"]]["identities"].append(
                        {k: identity[k] for k in ("source", "account", "external_id")}
                    )
        last = rows[limit - 1] if len(rows) > limit else None
        return {
            "items": result,
            "next_cursor": encode_cursor([last["last_date"], last["last_at"], last["id"]])
            if last
            else None,
        }

    def _asset(self, c, aid):
        row = self._require(c, attachments, aid)
        key = row.pop("file_key")
        row["available"] = key is not None and (self.root / key).is_file()
        partial = self.root / (".chunk-" + row["id"])
        if key is None and partial.exists():
            row["size"] = partial.stat().st_size
        return row

    def get_attachment(self, attachment_id):
        with self.engine.connect() as c:
            return self._asset(c, attachment_id)

    def read_attachment(self, attachment_id, offset_bytes=0, limit_bytes=65536):
        if offset_bytes < 0 or not 1 <= limit_bytes <= 262144:
            raise ValueError("invalid_attachment_page")
        with self.engine.connect() as c:
            row = self._require(c, attachments, attachment_id)
            info = self._asset(c, attachment_id)
        if not info["available"]:
            return {**info, "base64": None, "next_offset": None}
        with (self.root / row["file_key"]).open("rb") as f:
            f.seek(offset_bytes)
            block = f.read(limit_bytes)
        following = offset_bytes + len(block)
        return {
            **info,
            "offset_bytes": offset_bytes,
            "base64": base64.b64encode(block).decode(),
            "next_offset": following if following < row["size"] else None,
        }

    def _save_file(self, chunks, expected_hash=None):
        fd, filename = tempfile.mkstemp(dir=self.root, prefix=".upload-")
        digest, size = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, "wb") as f:
                for block in chunks:
                    size += len(block)
                    f.write(block)
                    digest.update(block)
            key = digest.hexdigest()
            if expected_hash and expected_hash != key:
                raise ValueError("attachment_hash_mismatch")
            # Same content-addressed layout as the existing attachment store.
            relative = key[:2] + "/" + key
            target = self.root / relative
            target.parent.mkdir(exist_ok=True, mode=0o700)
            if not target.exists():
                os.replace(filename, target)
            return relative, size
        finally:
            Path(filename).unlink(missing_ok=True)

    def upload_attachment(self, name, media_type, chunks):
        with self._asset_lock():
            key, size = self._save_file(chunks)
            aid = uuid7()
            with self.write() as c:
                c.execute(
                    insert(attachments).values(
                        id=aid,
                        name=Path(name.replace("\\", "/")).name or "attachment",
                        media_type=media_type,
                        size=size,
                        file_key=key,
                        created_at=utcnow(),
                    )
                )
                return self._asset(c, aid)

    def _ingest(self, c, batch):
        accepted = duplicates = 0
        seen = set(
            c.scalars(
                select(messages.c.key).where(messages.c.key.in_([m.key for m in batch.messages]))
            )
        )
        identity_cache = {}
        segments = {}
        for msg in sorted(batch.messages, key=lambda m: (m.sent_at, m.key)):
            if msg.key in seen:
                duplicates += 1
                continue
            identity_key = (msg.account, msg.peer)
            if identity_key not in identity_cache:
                identity_cache[identity_key] = (
                    c.execute(
                        select(identities).where(
                            identities.c.source == "wechat",
                            identities.c.account == msg.account,
                            identities.c.external_id == msg.peer,
                        )
                    )
                    .mappings()
                    .first()
                )
            identity = identity_cache[identity_key]
            now, sent = utcnow(), ensure_utc(msg.sent_at)
            if identity is None:
                pid, identity_id = uuid7(), uuid7()
                c.execute(
                    insert(people).values(
                        id=pid,
                        name=msg.name or msg.peer,
                        aliases=[],
                        relationship=None,
                        contacts=[],
                        tags=[],
                        notes="",
                        created_at=now,
                        updated_at=now,
                    )
                )
                c.execute(
                    insert(identities).values(
                        id=identity_id,
                        person_id=pid,
                        source="wechat",
                        account=msg.account,
                        external_id=msg.peer,
                    )
                )
                identity = {"id": identity_id, "person_id": pid}
                identity_cache[identity_key] = identity
            receipt = (
                c.execute(
                    select(messages.c.interaction_id, messages.c.sent_at)
                    .where(
                        messages.c.identity_id == identity["id"],
                        messages.c.sent_at >= sent - self.gap,
                        messages.c.sent_at <= sent + self.gap,
                        messages.c.interaction_id.is_not(None),
                    )
                    .order_by(
                        func.abs(func.extract("epoch", messages.c.sent_at) - sent.timestamp())
                        if c.dialect.name == "postgresql"
                        else func.abs(func.julianday(messages.c.sent_at) - func.julianday(sent)),
                        messages.c.key,
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            iid = receipt["interaction_id"] if receipt else None
            aid = None
            content = msg.content.replace("\x00", "")
            if msg.attachment:
                aid = uuid7()
                c.execute(
                    insert(attachments).values(
                        id=aid,
                        name=msg.attachment.name,
                        media_type=msg.attachment.media_type,
                        created_at=now,
                    )
                )
                content += f" [{msg.attachment.name}](attachment://{aid})"
            if iid:
                if iid not in segments:
                    segments[iid] = {**self._require(c, interactions, iid), "lines": []}
                old = segments[iid]
                first = min(old["started_at"] or sent, sent)
                last = max(old["ended_at"] or old["started_at"] or sent, sent)
                cross_day = first.astimezone(ZONE).date() != last.astimezone(ZONE).date()
            else:
                first = last = sent
                cross_day = False
            stamp = sent.astimezone(ZONE).strftime("%Y-%m-%d %H:%M" if cross_day else "%H:%M")
            line = f"{stamp} {'我' if msg.is_self else (msg.sender or msg.name or msg.peer)}：{content}"
            if iid:
                old["lines"].append(line)
                old["started_at"], old["ended_at"] = first, last
            else:
                iid = uuid7()
                c.execute(
                    insert(interactions).values(
                        id=iid,
                        type="chat",
                        channel="wechat",
                        date=sent.astimezone(ZONE).date(),
                        started_at=sent,
                        ended_at=sent,
                        content="",
                        source="wechat",
                        identity_id=identity["id"],
                        created_at=now,
                        updated_at=now,
                    )
                )
                c.execute(
                    insert(participants).values(interaction_id=iid, person_id=identity["person_id"])
                )
                segments[iid] = dict(content="", lines=[line], started_at=sent, ended_at=sent)
            if aid:
                c.execute(insert(attachment_links).values(interaction_id=iid, attachment_id=aid))
            c.execute(
                insert(messages).values(
                    key=msg.key,
                    identity_id=identity["id"],
                    interaction_id=iid,
                    attachment_id=aid,
                    sent_at=sent,
                )
            )
            accepted += 1
            seen.add(msg.key)
        for iid, segment in segments.items():
            content = "\n".join(
                ([segment["content"]] if segment["content"] else []) + segment["lines"]
            )
            c.execute(
                update(interactions)
                .where(interactions.c.id == iid)
                .values(
                    content=content,
                    date=segment["started_at"].astimezone(ZONE).date(),
                    started_at=segment["started_at"],
                    ended_at=segment["ended_at"],
                    updated_at=utcnow(),
                )
            )
        return accepted, duplicates

    def ingest_wechat(self, data):
        batch = WechatBatch.model_validate(data)
        with self.write() as c:
            accepted, duplicates = self._ingest(c, batch)
            old = (
                c.execute(select(clients).where(clients.c.id == batch.client_id)).mappings().first()
            )
            watermark = batch.synced_through
            if (
                old
                and old["synced_through"]
                and (watermark is None or old["synced_through"] > watermark)
            ):
                watermark = old["synced_through"]
            values = dict(synced_through=watermark, last_seen_at=utcnow())
            if old:
                c.execute(update(clients).where(clients.c.id == batch.client_id).values(**values))
            else:
                c.execute(insert(clients).values(id=batch.client_id, **values))
            return {"accepted": accepted, "duplicates": duplicates, "errors": []}

    def attach_wechat_media(self, key, chunks, name, media_type, expected_hash):
        with self._asset_lock():
            file_key, size = self._save_file(chunks, expected_hash)
            with self.write() as c:
                row = c.execute(select(messages).where(messages.c.key == key)).mappings().first()
                if row is None:
                    return {"status": "pending"}
                if row["interaction_id"] is None:
                    return {"status": "deleted"}
                aid = row["attachment_id"]
                if aid is None:
                    raise ValueError("message_has_no_attachment")
                c.execute(
                    update(attachments)
                    .where(attachments.c.id == aid)
                    .values(file_key=file_key, size=size, name=name, media_type=media_type)
                )
                return {"status": "attached", "attachment_id": aid}

    def list_sync_clients(self):
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(clients)).mappings()]

    def integrity_check(self):
        with self.engine.connect() as c:
            c.execute(select(people.c.id).limit(1))
        return "ok"

    def upload_attachment_chunk(
        self, name, media_type, content_base64, *, attachment_id=None, offset_bytes=0, final=True
    ):
        try:
            block = base64.b64decode(content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("invalid_base64") from exc
        if len(block) > 262144 or offset_bytes < 0:
            raise ValueError("invalid_upload_chunk")
        with self._asset_lock(), self.write() as c:
            if attachment_id is None:
                if offset_bytes != 0:
                    raise ValueError("new_upload_requires_zero_offset")
                attachment_id = uuid7()
                c.execute(
                    insert(attachments).values(
                        id=attachment_id,
                        name=Path(name.replace("\\", "/")).name or "attachment",
                        media_type=media_type,
                        created_at=utcnow(),
                    )
                )
            row = self._require(c, attachments, attachment_id)
            if row["file_key"] is not None:
                raise Conflict("upload_already_complete")
            path = self.root / (".chunk-" + row["id"])
            current = path.stat().st_size if path.exists() else 0
            if current != offset_bytes:
                raise Conflict("upload_offset_mismatch")
            with path.open("ab") as f:
                path.chmod(0o600)
                f.write(block)
            if final:
                with path.open("rb") as f:
                    key, size = self._save_file(iter(lambda: f.read(1024 * 1024), b""))
                c.execute(
                    update(attachments)
                    .where(attachments.c.id == attachment_id)
                    .values(file_key=key, size=size)
                )
                path.unlink()
            return {
                **self._asset(c, attachment_id),
                "next_offset": None if final else current + len(block),
            }
