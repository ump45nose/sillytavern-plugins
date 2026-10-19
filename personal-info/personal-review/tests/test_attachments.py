"""附件队列与 Memos 上传测试。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from review.attachments import AttachmentQueue
from review.state import StateRepository


class FakeMemos:
    """模拟 Memos 附件服务并记录调用。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.calls: list[tuple[str, str, bytes, str, str | None]] = []

    def create_attachment(
        self,
        filename: str,
        mime_type: str,
        content: bytes,
        memo_name: str,
        attachment_id: str | None = None,
    ) -> dict:
        """记录上传并返回规范附件名。"""

        self.calls.append((filename, mime_type, content, memo_name, attachment_id))
        return {"name": f"attachments/{attachment_id or 'test'}"}

    def get_attachment(self, name: str) -> dict:
        """模拟冲突恢复时读取稳定附件。"""

        return {"name": name}


class AttachmentQueueTests(unittest.TestCase):
    """验证持久化、消息级上传与幂等状态。"""

    def test_upload_message_does_not_repeat_uploaded_attachment(self) -> None:
        """同一消息上传成功后再次运行不得重复调用 Memos。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = StateRepository(root / "state.db")
            state.initialize()
            source = root / "moment.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"stable-test-payload")
            queue = AttachmentQueue(state, root / "spool")
            queue.enqueue("telegram-1", source)
            memos = FakeMemos()
            first = queue.upload_message("telegram-1", "memos/daily", memos)
            second = queue.upload_message("telegram-1", "memos/daily", memos)
            self.assertEqual(first[0]["status"], "uploaded")
            self.assertEqual(second, [])
            self.assertEqual(len(memos.calls), 1)

    def test_enqueue_rejects_non_image_content(self) -> None:
        """伪装扩展名的非图片不得进入长期附件队列。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = StateRepository(root / "state.db")
            state.initialize()
            source = root / "fake.png"
            source.write_bytes(b"plain text")
            with self.assertRaises(ValueError):
                AttachmentQueue(state, root / "spool").enqueue("telegram-2", source)


if __name__ == "__main__":
    unittest.main()
