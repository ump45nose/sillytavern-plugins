"""按消息身份读取本机原始媒体；只复用既有数据库密钥。"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


class MediaUnavailable(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class LocalMediaResolver:
    def __init__(self, config, spool=None):
        self.config = config
        self.spool = Path(spool) if spool is not None else None
        if self.spool is not None:
            self.spool.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.spool.chmod(0o700)
        self.readers = {}
        self.db = None

    def metadata(self, message):
        return self._metadata(self._reader(message.get("_media_account_id")), message)

    def _reader(self, account):
        if not account:
            raise MediaUnavailable("media_account_unavailable")
        if self.db is None:
            from chatlog_keeper import wechat_db

            self.db = wechat_db
            # 上游错误日志可能含数据库路径；常驻日志仅保留安全状态码。
            logging.getLogger("chatlog_keeper.wechat_db").setLevel(logging.CRITICAL)
        if account not in self.readers:
            reader = self.db.WeChatDBReader(account_id=account, allow_live_key_extract=False)
            if not reader.initialize() or not reader.wxid_dir or not reader.enc_keys:
                raise MediaUnavailable("media_cached_key_unavailable")
            self.readers[account] = reader
        return self.readers[account]

    def _metadata(self, reader, message):
        record = message["record"]
        cursor = None
        while True:
            page = reader.read_conversation_page(
                conversation_id=message["conversation_id"],
                since_ts=float(record["ts"]) - 1,
                until_ts=float(record["ts"]),
                page_size=200,
                cursor=cursor,
            )
            for item in page.messages:
                if (
                    str(item.server_id) == str(record["server_id"])
                    and item.chat_name == message["conversation_id"]
                    and int(item.timestamp.timestamp()) == int(record["ts"])
                    and int(item.msg_type) == int(record["msg_type"])
                ):
                    return item.attachment_meta
            if not page.has_more:
                raise MediaUnavailable("media_message_unavailable")
            if page.next_cursor is None or page.next_cursor == cursor:
                raise MediaUnavailable("media_page_incomplete")
            cursor = page.next_cursor

    @staticmethod
    def _voice(connection, conversation, server_id, timestamp):
        rows = connection.execute(
            "SELECT v.voice_data FROM VoiceInfo v JOIN Name2Id n ON n.rowid=v.chat_name_id "
            "WHERE n.user_name=? AND v.svr_id=? AND v.create_time=?",
            (conversation, str(server_id), int(timestamp)),
        ).fetchall()
        data = {bytes(row[0]) for row in rows if row[0]}
        if len(data) != 1:
            raise MediaUnavailable("media_voice_unavailable")
        return data.pop()

    def _voice_data(self, reader, message):
        # media_N.db 不在上游 message_N.db 列表；用既有缓存 key 逐一验证。
        directory = Path(reader.wxid_dir) / "db_storage/message"
        for path in sorted(directory.glob("media_*.db")):
            page = self.db._read_stable_page1(path)
            key = next(
                (
                    key
                    for key in reader.enc_keys.values()
                    if page and self.db._verify_key_v4(key, page)
                ),
                None,
            )
            if key is None:
                continue
            plain = self.db._decrypt_with_cache(path, key)
            if plain is None:
                continue
            with closing(
                sqlite3.connect(Path(plain).as_uri() + "?mode=ro", uri=True)
            ) as connection:
                try:
                    return self._voice(
                        connection,
                        message["conversation_id"],
                        message["record"]["server_id"],
                        message["record"]["ts"],
                    )
                except MediaUnavailable:
                    continue
        raise MediaUnavailable("media_voice_unavailable")

    @staticmethod
    def _safe_path(path, root):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root.resolve(strict=True))
            if not resolved.is_file():
                raise ValueError()
        except (OSError, ValueError):
            raise MediaUnavailable("media_path_unavailable") from None
        return resolved

    def _stage(self, blocks, name, media_type):
        fd, temporary = tempfile.mkstemp(prefix=".media-", dir=self.spool)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(fd, "wb") as output:
                for block in blocks:
                    size += len(block)
                    if size > 8 * 1024**3:
                        raise MediaUnavailable("media_too_large")
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if not size:
                raise MediaUnavailable("media_empty")
            identity = digest.hexdigest()
            os.replace(temporary, self.spool / identity)
            return {"id": identity, "name": name, "media_type": media_type}
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _stage_file(self, path, root, name, media_type, expected_md5=None, expected_size=None):
        path = self._safe_path(path, root)

        def blocks():
            before = path.stat()
            md5 = hashlib.md5()
            with path.open("rb") as source:
                opened = os.fstat(source.fileno())
                if (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev):
                    raise MediaUnavailable("media_file_changing")
                while block := source.read(1024 * 1024):
                    md5.update(block)
                    yield block
                after = os.fstat(source.fileno())
            current = path.stat()

            def signature(s):
                return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

            if signature(before) != signature(after) or signature(before) != signature(current):
                raise MediaUnavailable("media_file_changing")
            if expected_size and before.st_size != expected_size:
                raise MediaUnavailable("media_file_incomplete")
            if expected_md5 and md5.hexdigest() != expected_md5:
                raise MediaUnavailable("media_file_hash_mismatch")

        return self._stage(blocks(), name, media_type)

    def resolve(self, message):
        record = message["record"]
        if not str(record.get("server_id") or "").strip("0"):
            raise MediaUnavailable("media_message_identity_unavailable")
        reader = self._reader(message.get("_media_account_id"))
        if int(record["msg_type"]) == 34:
            data = self._voice_data(reader, message)
            from .formats import voice_wav

            return self._stage([voice_wav(data)], "voice.wav", "audio/wav")
        meta = self._metadata(reader, message)
        if not meta:
            if int(record["msg_type"]) == 49:
                return None
            raise MediaUnavailable("media_metadata_unavailable")
        root = Path(reader.wxid_dir) / "msg"
        kind = meta.get("kind")
        if kind in {"image", "video"}:
            md5 = str(meta.get("file_md5" if kind == "image" else "md5") or "").lower()
            if not re.fullmatch(r"[a-f0-9]{32}", md5):
                raise MediaUnavailable("media_locator_unavailable")
            candidates = (
                list((root / "attach").glob(f"**/Img/{md5}.dat"))
                if kind == "image"
                else list((root / "video").glob(f"**/{md5}.mp4"))
            )
            if len(candidates) != 1:
                raise MediaUnavailable("media_file_unavailable")
            path = self._safe_path(candidates[0], root)
            if kind == "image":
                from .formats import image_bytes

                data, extension, mime = image_bytes(path, reader.wxid_dir, self.config.image_uin)
                return self._stage([data], md5 + "." + extension, mime)
            return self._stage_file(path, root, md5 + ".mp4", "video/mp4")
        if kind == "file":
            name = str(meta.get("filename") or "")
            if not name or Path(name).name != name or "\\" in name:
                raise MediaUnavailable("media_locator_unavailable")
            size = int(meta.get("total_bytes") or 0)
            md5 = str(meta.get("md5") or "").lower()
            if not size or (md5 and not re.fullmatch(r"[a-f0-9]{32}", md5)):
                raise MediaUnavailable("media_locator_unavailable")
            candidates = [
                path
                for path in (root / "file").rglob("*")
                if path.name == name and path.is_file() and path.stat().st_size == size
            ]
            if len(candidates) != 1:
                raise MediaUnavailable("media_file_unavailable")
            return self._stage_file(
                candidates[0],
                root,
                name,
                mimetypes.guess_type(name)[0] or "application/octet-stream",
                md5 or None,
                size,
            )
        return None

    def close(self):
        self.readers.clear()
        if self.db is not None:
            self.db._decrypt_cache_clear(retry_failed=False)
