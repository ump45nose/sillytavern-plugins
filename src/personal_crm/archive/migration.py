"""一次转换既有 CRM 表；不从微信回填，也不修改旧记录。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from sqlalchemy import MetaData, Table, func, insert, inspect, select, update

from personal_crm.core.domain import ensure_utc, utcnow, uuid7

from .models import (
    attachment_links,
    attachments,
    clients,
    identities,
    interactions,
    messages,
    participants,
    people,
)
from .schemas import MessageInput, WechatBatch
from .service import ZONE


def instant(value):
    return ensure_utc(datetime.fromisoformat(value) if isinstance(value, str) else value)


def migrate_legacy(archive, *, source_schema=None):
    """新归档必须为空；整次转换在一个事务内完成，失败可修复后重跑。"""
    names = set(inspect(archive.engine).get_table_names(schema=source_schema))
    if not {"people", "interactions"} <= names:
        return {"people": 0, "messages": 0, "manual": 0, "skipped": 0, "interactions": 0}
    legacy = MetaData()
    old_people = Table("people", legacy, autoload_with=archive.engine, schema=source_schema)
    old_interactions = Table(
        "interactions", legacy, autoload_with=archive.engine, schema=source_schema
    )
    hub = (
        Table("hub_records", legacy, autoload_with=archive.engine, schema=source_schema)
        if "hub_records" in names
        else None
    )
    old_clients = (
        Table("sync_clients", legacy, autoload_with=archive.engine, schema=source_schema)
        if "sync_clients" in names
        else None
    )
    counts = Counter(people=0, messages=0, manual=0, skipped=0, interactions=0)
    with archive.write() as c:
        if c.scalar(select(people.c.id).limit(1)) or c.scalar(select(messages.c.key).limit(1)):
            raise ValueError("archive_not_empty: migration runs once before new writes")
        # Materialize small contact metadata once, stream the larger message table in time order.
        persons = {r["id"]: dict(r) for r in c.execute(select(old_people)).mappings()}
        asset_map = {}
        if hub is not None:
            for row in c.execute(
                select(hub.c.external_id, hub.c.assets).where(
                    hub.c.source == "crm", hub.c.kind == "interactions"
                )
            ).mappings():
                asset_map[row["external_id"].removeprefix("interactions:")] = row["assets"]

        def person(pid):
            if c.scalar(select(people.c.id).where(people.c.id == pid)):
                return
            old = persons[pid]
            contacts = [
                {"type": typ, "value": str(value)}
                for typ, values in (old.get("contact_methods") or {}).items()
                for value in values
                if value and typ != "wxid"
            ]
            notes = [old.get("profile_notes") or ""]
            if old.get("organizations"):
                notes.append("组织：" + json.dumps(old["organizations"], ensure_ascii=False))
            if old.get("pronouns"):
                notes.append("称谓：" + old["pronouns"])
            c.execute(
                insert(people).values(
                    id=pid,
                    name=old["display_name"],
                    aliases=old.get("aliases") or [],
                    relationship=old.get("relationship_to_me"),
                    contacts=contacts,
                    tags=old.get("tags") or [],
                    notes="\n".join(x for x in notes if x),
                    created_at=instant(old["created_at"]),
                    updated_at=instant(old["updated_at"]),
                )
            )
            counts["people"] += 1

        for row in c.execute(
            select(old_interactions).order_by(old_interactions.c.occurred_at, old_interactions.c.id)
        ).mappings():
            pid, message = row["person_id"], row.get("message") or {}
            if pid not in persons:
                counts["skipped"] += 1
                continue
            wxids = (persons[pid].get("contact_methods") or {}).get("wxid", [])
            if message.get("conversation_type") == "group" or (
                not message and wxids and all(x.endswith("@chatroom") for x in wxids)
            ):
                counts["skipped"] += 1
                continue
            original = message.get("record") or {}
            content = original.get("content")
            if content is None and row["summary"].startswith("消息内容："):
                content = row["summary"][len("消息内容：") :]
            is_wechat = row["channel"] == "wechat"
            if is_wechat and content is None:
                counts["skipped"] += 1
                continue
            if not is_wechat and not row["summary"].strip():
                counts["skipped"] += 1
                continue
            person(pid)
            if is_wechat:
                account = message.get("account_namespace") or "legacy"
                peer = message.get("conversation_id") or (wxids[0] if len(wxids) == 1 else pid)
                identity = (
                    c.execute(
                        select(identities).where(
                            identities.c.source == "wechat",
                            identities.c.account == account,
                            identities.c.external_id == peer,
                        )
                    )
                    .mappings()
                    .first()
                )
                if identity is None:
                    c.execute(
                        insert(identities).values(
                            id=uuid7(),
                            person_id=pid,
                            source="wechat",
                            account=account,
                            external_id=peer,
                        )
                    )
                key = row.get("source_message_key") or row.get("source_event_key") or row["id"]
                old_assets = asset_map.get(row["id"], [])
                typ = int(original.get("msg_type") or 0)
                placeholder = (
                    {
                        "name": old_assets[0]["name"]
                        if old_assets
                        else {3: "图片", 34: "语音", 43: "视频", 49: "文件"}.get(typ, "附件"),
                        "media_type": old_assets[0]["media_type"]
                        if old_assets
                        else "application/octet-stream",
                    }
                    if old_assets or typ in {3, 34, 43}
                    else None
                )
                msg = MessageInput(
                    key=key,
                    account=account,
                    peer=peer,
                    name=persons[pid]["display_name"],
                    sent_at=instant(row["occurred_at"]),
                    is_self=row["direction"] == "outbound",
                    content=content,
                    attachment=placeholder,
                )
                accepted, _ = archive._ingest(c, WechatBatch(messages=[msg]))
                counts["messages"] += accepted
                receipt = c.execute(select(messages).where(messages.c.key == key)).mappings().one()
                for position, asset in enumerate(old_assets):
                    aid = receipt["attachment_id"] if position == 0 else uuid7()
                    relative = asset["id"][:2] + "/" + asset["id"]
                    values = dict(
                        name=asset["name"],
                        media_type=asset["media_type"],
                        size=asset["size"],
                        file_key=relative,
                    )
                    if position == 0:
                        c.execute(
                            update(attachments).where(attachments.c.id == aid).values(**values)
                        )
                    else:
                        c.execute(insert(attachments).values(id=aid, **values, created_at=utcnow()))
                        c.execute(
                            insert(attachment_links).values(
                                interaction_id=receipt["interaction_id"], attachment_id=aid
                            )
                        )
                        current = c.scalar(
                            select(interactions.c.content).where(
                                interactions.c.id == receipt["interaction_id"]
                            )
                        )
                        c.execute(
                            update(interactions)
                            .where(interactions.c.id == receipt["interaction_id"])
                            .values(content=current + f"\n[{asset['name']}](attachment://{aid})")
                        )
            else:
                when = instant(row["occurred_at"])
                c.execute(
                    insert(interactions).values(
                        id=row["id"],
                        type=row["interaction_type"],
                        channel=row["channel"],
                        date=when.astimezone(ZONE).date(),
                        started_at=when,
                        ended_at=when,
                        content=row["summary"],
                        source=row["source_type"],
                        created_at=instant(row["created_at"]),
                        updated_at=instant(row["created_at"]),
                    )
                )
                c.execute(insert(participants).values(interaction_id=row["id"], person_id=pid))
                counts["manual"] += 1
        # Keep useful standalone/manual profiles; never introduce group placeholders.
        for pid, old in persons.items():
            useful = (
                old.get("profile_notes")
                or old.get("relationship_to_me")
                or old.get("organizations")
                or old.get("tags")
            )
            wxids = (old.get("contact_methods") or {}).get("wxid", [])
            if useful and not (wxids and all(x.endswith("@chatroom") for x in wxids)):
                person(pid)
        if old_clients is not None:
            for old in c.execute(select(old_clients)).mappings():
                key = old["client_id"]
                existing = c.execute(select(clients).where(clients.c.id == key)).mappings().first()
                stamp = instant(old["synced_through"]) if old["synced_through"] else None
                if existing:
                    if stamp and (
                        not existing["synced_through"] or stamp > existing["synced_through"]
                    ):
                        c.execute(
                            update(clients).where(clients.c.id == key).values(synced_through=stamp)
                        )
                else:
                    c.execute(
                        insert(clients).values(
                            id=key, synced_through=stamp, last_seen_at=instant(old["last_seen_at"])
                        )
                    )
        counts["interactions"] = c.scalar(select(func.count()).select_from(interactions))
    return dict(counts)
