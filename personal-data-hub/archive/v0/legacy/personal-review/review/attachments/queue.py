"""在 Telegram 临时缓存失效前保存图片并可靠排队上传。"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import shutil
from typing import Any

from review.ledger import MemosClient, MemosError
from review.state import StateRepository


class AttachmentQueue:
    """保证文本先发布、附件按稳定 ID 异步补充且不重复。"""

    def __init__(
        self,
        state: StateRepository,
        spool: str | Path,
        retention_days: int = 30,
        retry_max: int = 5,
        worker_batch: int = 10,
        max_bytes: int = 25 * 1024 * 1024,
        allowed_mime_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"),
    ) -> None:
        """绑定状态库、持久目录、保留天数、重试策略和图片白名单。"""

        self.state = state
        self.spool = Path(spool)
        self.retention_days = retention_days
        self.retry_max = retry_max
        self.worker_batch = worker_batch
        self.max_bytes = max_bytes
        self.allowed_mime_types = frozenset(allowed_mime_types)

    def enqueue(self, message_id: str, source: str | Path) -> dict:
        """复制附件到持久队列，并用消息 ID 与 SHA-256 去重。"""

        if not str(message_id or "").strip():
            raise ValueError("message_id 不能为空")
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if source_path.stat().st_size > self.max_bytes:
            raise ValueError("图片超过允许的最大字节数")
        detected_mime = self._detect_image_mime(source_path)
        if detected_mime not in self.allowed_mime_types:
            raise ValueError("附件不是允许的图片格式")
        digest = self._file_digest(source_path)
        suffix = source_path.suffix.lower() or ".bin"
        stored = self.spool / digest[:2] / f"{digest}{suffix}"
        stored.parent.mkdir(parents=True, exist_ok=True)
        if not stored.exists():
            temporary = stored.with_suffix(stored.suffix + ".tmp")
            shutil.copy2(source_path, temporary)
            temporary.replace(stored)
        now = datetime.now().astimezone().isoformat()
        with self.state.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO attachments(message_id,sha256,source_path,stored_path,status,created_at,updated_at) "
                "VALUES(?,?,?,?,'pending',?,?)",
                (message_id, digest, str(source_path), str(stored), now, now),
            )
        return {"message_id": message_id, "sha256": digest, "stored_path": str(stored)}

    def link(self, message_id: str, memo_name: str) -> int:
        """在文本 Memo 成功发布后关联队列；不创建或修改第二条 Memo。"""

        if not memo_name.startswith("memos/"):
            raise ValueError("memo_name 必须是 memos/UID")
        now = datetime.now().astimezone().isoformat()
        with self.state.connect() as connection:
            cursor = connection.execute(
                "UPDATE attachments SET memo_name=?,updated_at=? "
                "WHERE message_id=? AND status IN ('pending','failed','manual')",
                (memo_name, now, message_id),
            )
            exists = connection.execute(
                "SELECT 1 FROM attachments WHERE message_id=? AND memo_name=? LIMIT 1",
                (message_id, memo_name),
            ).fetchone()
        if cursor.rowcount == 0 and not exists:
            raise ValueError("没有找到可关联的附件")
        return cursor.rowcount

    def pending(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """列出队列和人工处理清单，不读取图片内容。"""

        sql = "SELECT id,message_id,sha256,stored_path,memo_name,status,attempts,created_at,updated_at,error FROM attachments"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY id LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self.state.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def retry(self, attachment_id: int) -> dict:
        """把 failed/manual 项显式恢复为 pending，但保留尝试次数。"""

        with self.state.connect() as connection:
            row = connection.execute("SELECT status FROM attachments WHERE id=?", (attachment_id,)).fetchone()
            if not row:
                raise ValueError("附件队列项不存在")
            if row["status"] not in {"failed", "manual"}:
                raise ValueError("只有 failed/manual 附件可以重试")
            connection.execute(
                "UPDATE attachments SET status='pending',error=NULL,updated_at=? WHERE id=?",
                (datetime.now().astimezone().isoformat(), attachment_id),
            )
        return {"id": attachment_id, "status": "pending"}

    def upload_message(self, message_id: str, memo_name: str, memos: MemosClient) -> list[dict]:
        """关联并上传指定消息的待处理附件。"""

        self.link(message_id, memo_name)
        with self.state.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM attachments WHERE message_id=? AND memo_name=? "
                "AND status IN ('pending','failed') AND attempts<? ORDER BY id",
                (message_id, memo_name, self.retry_max),
            ).fetchall()
        return [self._upload_row(dict(row), memos) for row in rows]

    def process_pending(self, memos: MemosClient) -> list[dict]:
        """批量处理已关联项目，并回收超时 uploading lease。"""

        stale = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
        with self.state.connect() as connection:
            connection.execute(
                "UPDATE attachments SET status='failed',error='upload lease expired' "
                "WHERE status='uploading' AND updated_at<?",
                (stale,),
            )
            rows = connection.execute(
                "SELECT * FROM attachments WHERE memo_name IS NOT NULL "
                "AND status IN ('pending','failed') AND attempts<? ORDER BY id LIMIT ?",
                (self.retry_max, self.worker_batch),
            ).fetchall()
        return [self._upload_row(dict(row), memos) for row in rows]

    def expire(self, now: datetime) -> int:
        """把超期未上传项目转为人工处理，不删除原文件。"""

        threshold = (now - timedelta(days=self.retention_days)).isoformat()
        with self.state.connect() as connection:
            cursor = connection.execute(
                "UPDATE attachments SET status='manual',updated_at=? "
                "WHERE status IN ('pending','failed') AND created_at<?",
                (now.isoformat(), threshold),
            )
            return cursor.rowcount

    def _upload_row(self, row: dict[str, Any], memos: MemosClient) -> dict:
        """领取并上传单项，稳定 attachment_id 防止崩溃后重复创建。"""

        attachment_id = int(row["id"])
        now = datetime.now().astimezone().isoformat()
        with self.state.connect() as connection:
            claimed = connection.execute(
                "UPDATE attachments SET status='uploading',attempts=attempts+1,updated_at=? "
                "WHERE id=? AND status IN ('pending','failed') AND attempts<?",
                (now, attachment_id, self.retry_max),
            )
        if claimed.rowcount != 1:
            return {"id": attachment_id, "status": "skipped"}
        stored = Path(str(row["stored_path"]))
        try:
            if not stored.is_file() or self._file_digest(stored) != row["sha256"]:
                raise ValueError("持久附件缺失或 SHA-256 不一致")
            mime_type = self._detect_image_mime(stored)
            stable_uid = "pr-" + hashlib.sha256(
                f"{row['message_id']}\0{row['sha256']}".encode("utf-8")
            ).hexdigest()[:24]
            try:
                created = memos.create_attachment(
                    stored.name, mime_type, stored.read_bytes(), str(row["memo_name"]), stable_uid
                )
            except MemosError as exc:
                if "HTTP 409" not in str(exc):
                    raise
                created = memos.get_attachment(f"attachments/{stable_uid}")
            with self.state.connect() as connection:
                connection.execute(
                    "UPDATE attachments SET status='uploaded',updated_at=?,error=NULL WHERE id=?",
                    (datetime.now().astimezone().isoformat(), attachment_id),
                )
            return {"id": attachment_id, "status": "uploaded", "attachment_name": created["name"]}
        except Exception as exc:
            with self.state.connect() as connection:
                current = connection.execute("SELECT attempts FROM attachments WHERE id=?", (attachment_id,)).fetchone()
                attempts = int(current["attempts"] if current else self.retry_max)
                status = "manual" if attempts >= self.retry_max else "failed"
                error = f"{type(exc).__name__}: {str(exc)[:240]}"
                connection.execute(
                    "UPDATE attachments SET status=?,updated_at=?,error=? WHERE id=?",
                    (status, datetime.now().astimezone().isoformat(), error, attachment_id),
                )
            return {"id": attachment_id, "status": status, "error": error}

    @staticmethod
    def _file_digest(path: Path) -> str:
        """流式计算附件 SHA-256，避免大图片一次性读入校验内存。"""

        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _detect_image_mime(path: Path) -> str:
        """按文件头识别允许的图片，避免只依赖可伪造的扩展名。"""

        with path.open("rb") as stream:
            header = stream.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if header.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            return "image/webp"
        if len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in {b"heic", b"heix", b"mif1", b"msf1"}:
            return "image/heic"
        # 给出稳定拒绝值，调用方不得回退到扩展名猜测。
        return "application/octet-stream"
