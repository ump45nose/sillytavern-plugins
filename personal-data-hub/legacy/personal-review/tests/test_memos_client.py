"""Memos REST 客户端的网络恢复与副作用边界测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from review.ledger.memos import MemosClient, MemosError


class _FakeResponse:
    """提供 urllib response 所需的最小上下文管理接口。"""

    def __init__(self, payload: dict) -> None:
        """保存待返回的 JSON 对象。"""

        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        """进入模拟网络响应上下文。"""

        return self

    def __exit__(self, *args: object) -> None:
        """退出模拟网络响应上下文，无需释放外部资源。"""

        return None

    def read(self) -> bytes:
        """返回序列化响应体。"""

        return self.raw


class MemosClientTests(unittest.TestCase):
    """验证只读请求可恢复而写请求不会盲目重放。"""

    def _client(self, root: Path) -> MemosClient:
        """创建使用临时令牌的零退避客户端。"""

        token_file = root / "memos.token"
        token_file.write_text("test-token", encoding="utf-8")
        return MemosClient(
            "http://127.0.0.1:5230",
            token_file,
            timeout=1,
            read_retries=3,
            retry_backoff_seconds=0,
        )

    def test_list_memos_retries_transient_timeout(self) -> None:
        """首次读取超时后应自动重试，并返回第二次的正常列表。"""

        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory))
            with patch(
                "review.ledger.memos.urlopen",
                side_effect=[TimeoutError("timed out"), _FakeResponse({"memos": [{"name": "memos/1"}]})],
            ) as mocked:
                result = client.list_memos()

        self.assertEqual(result, [{"name": "memos/1"}])
        self.assertEqual(mocked.call_count, 2)

    def test_create_memo_does_not_retry_timeout(self) -> None:
        """创建请求超时后的远端状态未知，客户端不得自动重复创建。"""

        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory))
            with patch("review.ledger.memos.urlopen", side_effect=TimeoutError("timed out")) as mocked:
                with self.assertRaises(MemosError):
                    client.create_memo("#日报\n测试")

        self.assertEqual(mocked.call_count, 1)

    def test_list_memos_reads_all_pages(self) -> None:
        """超过 100 条时必须携带 nextPageToken 继续读取。"""

        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory))
            responses = [
                _FakeResponse({"memos": [{"name": "memos/1"}], "nextPageToken": "next token"}),
                _FakeResponse({"memos": [{"name": "memos/2"}]}),
            ]
            with patch("review.ledger.memos.urlopen", side_effect=responses) as mocked:
                result = client.list_memos()

        self.assertEqual([item["name"] for item in result], ["memos/1", "memos/2"])
        self.assertIn("page_token=next+token", mocked.call_args_list[1].args[0].full_url)

    def test_list_memos_rejects_repeated_page_token(self) -> None:
        """服务端不推进分页 token 时必须停止，不能无限请求。"""

        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory))
            with patch(
                "review.ledger.memos.urlopen",
                side_effect=[
                    _FakeResponse({"memos": [], "nextPageToken": "same"}),
                    _FakeResponse({"memos": [], "nextPageToken": "same"}),
                ],
            ):
                with self.assertRaisesRegex(MemosError, "token 未前进"):
                    client.list_memos()


if __name__ == "__main__":
    unittest.main()
