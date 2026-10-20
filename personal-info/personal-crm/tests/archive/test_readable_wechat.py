import json
from types import SimpleNamespace

from checks.repair_archive import repair_wechat
from personal_crm.connector.chatlog import ChatlogMessageSource
from personal_crm.connector.config import ConnectorConfig
from personal_crm.core.presentation import clean_chat, directory_name
from tests.archive.test_archive import msg as base_msg


def msg(key="1", at="2026-10-15T10:00:00+08:00", **kw):
    return dict(base_msg(key, at), **kw)


def test_directory_name_priority_and_old_override_ignored(tmp_path, monkeypatch):
    item = dict(
        account_id="me",
        conversation_id="you",
        conversation_type="direct",
        label="备注：小王 · 昵称：王同学",
    )
    assert directory_name(item) == "小王"
    assert directory_name(dict(item, remark="王老师")) == "王老师"
    assert directory_name(dict(item, label="昵称：王同学")) == "王同学"
    assert directory_name(dict(item, label="备注/昵称：小王")) == "小王"
    assert directory_name(dict(item, label="", nickname="昵称")) == "昵称"
    assert directory_name(dict(item, label="")) == "you"
    pinned = tmp_path / "scopes.json"
    pinned.write_text(json.dumps([dict(item, person_name="旧姓名")]))
    monkeypatch.setattr(
        "personal_crm.connector.chatlog.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout=json.dumps(dict(available=True, conversations=[item]))
        ),
    )
    scopes = ChatlogMessageSource(
        ConnectorConfig(chatlog_executable=__file__, chatlog_scopes_path=str(pinned))
    )._scopes()
    assert scopes[0]["person_name"] == "小王"


def test_ingest_short_speaker_single_placeholder_and_caption(archive):
    archive.ingest_wechat(
        dict(
            messages=[
                msg(
                    name="备注：小王 · 昵称：王同学",
                    sender="备注：小王 · 昵称：王同学",
                    content="[图片]",
                    attachment=dict(name="图片"),
                )
            ]
        )
    )
    person = archive.list_people()["items"][0]
    assert person["name"] == "小王"
    iid = archive.list_interactions()["items"][0]["id"]
    row = archive.get_interaction(iid)
    assert row["content"].startswith("10:00 小王：[图片](attachment://")
    archive.update_person(person["id"], dict(name="手工姓名"))
    archive.update_interaction(iid, dict(content="人工修改，不要重建"))
    archive.ingest_wechat(
        dict(
            messages=[
                msg(
                    "2",
                    "2026-10-15T10:01:00+08:00",
                    name="备注：小王 · 昵称：王同学",
                    content="实际说明",
                    attachment=dict(name="图片"),
                )
            ]
        )
    )
    assert archive.get_person(person["id"])["name"] == "手工姓名"
    content = archive.get_interaction(iid)["content"]
    assert content.startswith("人工修改，不要重建\n10:01 小王：实际说明 [图片](")


def test_repair_scoped_machine_names_preserves_manual_and_idempotent(archive, tmp_path):
    archive.ingest_wechat(dict(messages=[msg(name="you", content="旧内容")]))
    p = archive.list_people()["items"][0]
    iid = archive.list_interactions()["items"][0]["id"]
    old = (
        "人工整理\n10:00 备注：小王 · 昵称：王同学：正文保留：冒号\n"
        "2026-10-16 00:01 you：[图片] [图片](attachment://abc-123)\n"
        "10:01 我：[语音 3s] [语音](attachment://xyz)\n"
        "正文提到备注：某人 · 昵称：某某，不要改。"
    )
    archive.update_interaction(iid, dict(content=old))
    directory = dict(
        conversations=[
            dict(
                conversation_id="you", label="备注：小王 · 昵称：王同学", conversation_type="direct"
            )
        ]
    )
    assert repair_wechat(archive, directory, accounts=["me"]) == dict(
        people=1, interactions=1, applied=False
    )
    assert archive.get_interaction(iid)["content"] == old
    backup = tmp_path / "repair.json"
    result = repair_wechat(archive, directory, accounts=["me"], backup=backup, apply=True)
    assert result == dict(people=1, interactions=1, applied=True)
    assert json.loads(backup.read_text())["interactions"][0]["content"] == old
    assert archive.get_person(p["id"])["name"] == "小王"
    content = archive.get_interaction(iid)["content"]
    assert "10:00 小王：正文保留：冒号" in content
    assert "00:01 小王：[图片](attachment://" in content
    assert "[语音 3s]" in content
    assert content.endswith("正文提到备注：某人 · 昵称：某某，不要改。")
    assert repair_wechat(archive, directory, accounts=["me"]) == dict(
        people=0, interactions=0, applied=False
    )
    archive.update_person(p["id"], dict(name="人工姓名"))
    assert repair_wechat(archive, directory, accounts=["me"])["people"] == 0
    assert (
        clean_chat("10:00 我：保留 [图片] 不相邻\n普通文本", {})
        == "10:00 我：保留 [图片] 不相邻\n普通文本"
    )
    assert clean_chat("10:00 备注/昵称：小王：正文", {}) == "10:00 小王：正文"


def test_media_enabled_by_default(monkeypatch):
    monkeypatch.delenv("WECHAT_MEDIA_ENABLED", raising=False)
    assert ConnectorConfig.from_env().media_enabled is True
    monkeypatch.setenv("WECHAT_MEDIA_ENABLED", "false")
    assert ConnectorConfig.from_env().media_enabled is False


def test_repair_missing_file_metadata_preserves_content_and_idempotent(archive, tmp_path):
    from checks.repair_archive import repair_file_attachments

    archive.ingest_wechat(dict(messages=[msg(content="[文件：方案.pdf]")]))
    row = archive.list_interactions()["items"][0]
    before = archive.get_interaction(row["id"])["content"]
    archive.update_interaction(row["id"], dict(content="人工备注\n" + before))
    rows = [dict(key="1", name="方案.pdf", placeholder="[文件：方案.pdf]")]
    result = repair_file_attachments(archive, rows, tmp_path / "before.json")
    assert result == dict(attached_metadata=1)
    result = archive.get_interaction(row["id"])
    assert result["content"].startswith("人工备注\n10:00 ")
    assert "[文件：方案.pdf]" not in result["content"]
    assert "[方案.pdf](attachment://" in result["content"]
    assert len(result["attachment_ids"]) == 1
    assert repair_file_attachments(archive, rows, tmp_path / "unused.json") == dict(
        attached_metadata=0
    )
