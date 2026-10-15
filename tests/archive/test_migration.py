from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from personal_crm.archive.migration import migrate_legacy
from tests.legacy_schema import metadata


def test_simple_legacy_conversion_and_replay(archive):
    metadata.create_all(archive.engine)
    old = metadata.tables
    now = datetime(2026, 10, 15, 2, tzinfo=UTC)
    with archive.engine.begin() as c:
        for pid, name, wxid in [
            ("a", "小王", "you"),
            ("b", "群", "123@chatroom"),
            ("c", "手工", "manual"),
        ]:
            c.execute(
                insert(old["people"]).values(
                    id=pid,
                    display_name=name,
                    contact_methods={"wxid": [wxid]},
                    profile_notes="资料" if pid == "a" else None,
                    organizations=[{"name": "公司"}] if pid == "a" else [],
                )
            )
        for i, pid, summary, raw in [
            (
                "1",
                "a",
                "消息内容：第一句",
                {
                    "account_namespace": "me",
                    "conversation_id": "you",
                    "conversation_type": "direct",
                    "record": {"content": "第一句", "msg_type": 1},
                },
            ),
            (
                "2",
                "a",
                "消息内容：第二句",
                {
                    "account_namespace": "me",
                    "conversation_id": "you",
                    "conversation_type": "direct",
                    "record": {"content": "第二句", "msg_type": 1},
                },
            ),
            ("3", "a", "发生了一次互动", None),
            (
                "4",
                "b",
                "消息内容：群内容",
                {"conversation_type": "group", "record": {"content": "群内容"}},
            ),
            ("5", "c", "一起吃饭", None),
        ]:
            c.execute(
                insert(old["interactions"]).values(
                    id=i,
                    person_id=pid,
                    occurred_at=now,
                    interaction_type="meeting" if i == "5" else "message",
                    channel="in_person" if i == "5" else "wechat",
                    direction="inbound",
                    summary=summary,
                    message=raw,
                    source_type="manual" if i == "5" else "chatlog",
                    source_message_key=i,
                )
            )
        c.execute(
            insert(old["sync_clients"]).values(
                source="chatlog", client_id="mac", synced_through=now
            )
        )
    result = migrate_legacy(archive)
    assert result == {"people": 2, "messages": 2, "manual": 1, "skipped": 2, "interactions": 2}
    assert "资料" in archive.get_person("a")["notes"] and "公司" in archive.get_person("a")["notes"]
    assert len(archive.list_interactions(person_id="a")["items"]) == 1
    assert (
        archive.ingest_wechat(
            {"messages": [dict(key="1", account="me", peer="you", sent_at=now, content="第一句")]}
        )["duplicates"]
        == 1
    )
    assert len(archive.list_sync_clients()) == 2
    assert len(archive.list_people()["items"]) == 2
    with pytest.raises(ValueError, match="archive_not_empty"):
        migrate_legacy(archive)
