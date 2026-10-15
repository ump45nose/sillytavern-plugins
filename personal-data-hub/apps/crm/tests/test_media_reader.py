"""原格式读取、精确关联与增量媒体队列。"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from personal_crm.connector.chatlog import SourceBatch
from personal_crm.connector.checkpoint import load, save
from personal_crm.connector.config import ConnectorConfig
from personal_crm.connector.media import MediaQueue
from personal_crm.connector.media_reader import LocalMediaResolver, MediaUnavailable
from personal_crm.connector.sync import WeChatConnector
from tests.archive.test_connector import FakeClient, FakeResponse, source_event


def test_voice_requires_server_conversation_and_time():
    connection = sqlite3.connect(":memory:")
    connection.executescript("CREATE TABLE Name2Id(user_name TEXT); "
                             "CREATE TABLE VoiceInfo(chat_name_id INTEGER,create_time INTEGER,svr_id INTEGER,voice_data BLOB);")
    connection.executemany("INSERT INTO Name2Id VALUES(?)", [("a",), ("b",)])
    connection.executemany("INSERT INTO VoiceInfo VALUES(?,?,?,?)", [
        (1, 100, 7, b"#!SILK_original"), (2, 100, 7, b"other-conversation"),
        (1, 101, 7, b"other-time"), (1, 100, 8, b"other-id"),
    ])
    assert LocalMediaResolver._voice(connection, "a", "7", 100) == b"#!SILK_original"
    with pytest.raises(MediaUnavailable):
        LocalMediaResolver._voice(connection, "c", "7", 100)
    connection.close()


def test_image_keeps_encrypted_bytes_and_does_not_guess_xml_md5(tmp_path, monkeypatch):
    resolver = LocalMediaResolver(ConnectorConfig(), tmp_path / "spool")
    root = tmp_path / "account"
    image = root / "msg/attach/chat/month/Img" / ("a" * 32 + ".dat")
    image.parent.mkdir(parents=True)
    data = b"\x07\x08V2encrypted-original"
    image.write_bytes(data)
    monkeypatch.setattr(resolver, "_reader", lambda account: SimpleNamespace(wxid_dir=root))
    meta = {"kind": "image", "file_md5": "a" * 32, "md5": "b" * 32}
    monkeypatch.setattr(resolver, "_metadata", lambda *args: meta)
    message = {"record": {"msg_type": 3, "server_id": "1"}}
    result = resolver.resolve(message)
    assert result["media_type"] == "application/vnd.wechat.encrypted-image"
    assert (resolver.spool / result["id"]).read_bytes() == data
    meta.pop("file_md5")
    with pytest.raises(MediaUnavailable, match="locator"):
        resolver.resolve(message)


def test_file_spool_rejects_escape_incomplete_and_content_mismatch(tmp_path):
    resolver = LocalMediaResolver(ConnectorConfig(), tmp_path / "spool")
    root = tmp_path / "msg"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"abc")
    link = root / "link"
    link.symlink_to(outside)
    with pytest.raises(MediaUnavailable, match="path"):
        resolver._stage_file(link, root, "f", "application/octet-stream")
    source = root / "file"
    source.write_bytes(b"abc")
    with pytest.raises(MediaUnavailable, match="incomplete"):
        resolver._stage_file(source, root, "f", "application/octet-stream", expected_size=4)
    with pytest.raises(MediaUnavailable, match="hash"):
        resolver._stage_file(source, root, "f", "application/octet-stream", expected_md5="0" * 32)
    assert not list(resolver.spool.iterdir())


def _queued(tmp_path, event=None):
    cfg = ConnectorConfig(media_enabled=True, checkpoint_path=str(tmp_path / "cp"),
                          webhook_url="http://nas/hook", webhook_token="secret")
    queue = MediaQueue(cfg)
    queue.initialize()
    with queue.state() as state:
        state["enabled_since"] = "2026-09-03T00:00:00+00:00"
    event = event or source_event(typ=34)
    source = SimpleNamespace(read=lambda state: SourceBatch([event], datetime(2026, 9, 5, tzinfo=UTC)))
    connector = WeChatConnector(cfg, FakeClient([FakeResponse(body={"accepted": 1, "duplicates": 0})]), source)
    return cfg, queue, connector


def test_only_future_media_enqueued_and_dry_run_does_not_create_queue(tmp_path):
    cfg, queue, connector = _queued(tmp_path)
    with queue.state() as state:
        state["enabled_since"] = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    assert connector.sync_once().sent
    assert json.loads(queue.path.read_text())["jobs"] == {}
    queue.path.unlink()
    connector.sync_once(dry_run=True)
    assert not queue.path.exists()


def test_media_retry_spool_survives_source_loss_and_text_watermark(tmp_path):
    cfg, queue, connector = _queued(tmp_path)
    assert connector.sync_once().sent
    original_cp = load(cfg.checkpoint_path)
    job = next(iter(json.loads(queue.path.read_text())["jobs"].values()))
    assert job["message"]["_media_account_id"] == "local-account"
    assert "_media_account_id" not in connector.client.posted[0][1]["messages"][0]
    data = b"\x02#!SILK_original"
    identity = hashlib.sha256(data).hexdigest()
    def resolve(message):
        (queue.spool / identity).write_bytes(data)
        return {"id": identity, "name": "voice.silk", "media_type": "audio/silk"}
    resolver = SimpleNamespace(resolve=resolve, close=lambda: None)
    def put(*args, **kwargs):
        assert b"".join(kwargs["content"]) == data
        raise OSError("offline")
    assert queue.run_once(SimpleNamespace(put=put), resolver)["retry"] == 1
    assert load(cfg.checkpoint_path) == original_cp
    assert (queue.spool / identity).read_bytes() == data
    with queue.state() as state:
        next(iter(state["jobs"].values()))["next_retry"] = 0
    resolver.resolve = lambda message: pytest.fail("staged file must be reused")
    result = queue.run_once(SimpleNamespace(put=lambda *a, **kw: FakeResponse(body={"status": "attached"})), resolver)
    assert result == {"attached": 1, "pending": 0}
    assert not (queue.spool / identity).exists()


def test_corrupt_queue_does_not_advance_text_checkpoint(tmp_path):
    cfg, queue, connector = _queued(tmp_path)
    save(cfg.checkpoint_path, {"last_synced_at": "2026-09-03T00:00:00Z"})
    queue.path.write_text("invalid")
    result = connector.sync_once()
    assert result.errors == ["media_queue_unavailable"]
    assert load(cfg.checkpoint_path)["last_synced_at"] == "2026-09-03T00:00:00Z"
