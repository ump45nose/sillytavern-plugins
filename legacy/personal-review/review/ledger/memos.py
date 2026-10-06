"""Memos 0.30 REST 客户端，只承载确认后的账本操作。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MemosError(RuntimeError):
    """表示 Memos 网络、认证或响应契约错误。"""


class MemosClient:
    """以最小 REST 面积访问 Memos，日志永不暴露令牌。"""

    def __init__(
        self,
        base_url: str,
        token_file: str | Path,
        timeout: int = 15,
        read_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        """读取受限 PAT 文件并初始化带只读重试的客户端。"""

        self.base_url = base_url.rstrip("/")
        token_path = Path(token_file)
        self.token = token_path.read_text(encoding="utf-8").strip()
        if not self.token:
            raise MemosError("Memos token 文件为空")
        if timeout < 1 or read_retries < 1 or retry_backoff_seconds < 0:
            raise MemosError("Memos 超时和重试配置必须为正值")
        self.timeout = timeout
        self.read_retries = read_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送 JSON 请求并把远端错误压缩成不含凭据的异常。"""

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        # 只有 GET 可以安全自动重试；POST/PATCH 的远端结果可能已经落账，盲目重试会制造重复记录。
        attempts = self.read_retries if method == "GET" else 1
        raw = b""
        for attempt in range(1, attempts + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                break
            except HTTPError as exc:
                retryable = method == "GET" and exc.code in {502, 503, 504} and attempt < attempts
                if retryable:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise MemosError(f"Memos HTTP {exc.code}: {detail}") from exc
            except (TimeoutError, URLError) as exc:
                if attempt < attempts:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                reason = exc.reason if isinstance(exc, URLError) else "请求超时"
                raise MemosError(f"Memos 不可达：{reason}") from exc
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MemosError("Memos 返回了非 JSON 响应") from exc
        if not isinstance(body, dict):
            raise MemosError("Memos 返回结构不是对象")
        return body

    def list_memos(self, page_size: int = 100, state: str = "NORMAL") -> list[dict[str, Any]]:
        """分页读取确认账本，防止主线或阶段目标落在第一页之外。"""

        result: list[dict[str, Any]] = []
        page_token = ""
        seen_tokens: set[str] = set()
        for _ in range(1000):
            values = {"page_size": page_size, "state": state}
            if page_token:
                values["page_token"] = page_token
            body = self._request("GET", f"/api/v1/memos?{urlencode(values)}")
            items = body.get("memos", body.get("items", []))
            if isinstance(items, list):
                result.extend(item for item in items if isinstance(item, dict))
            next_token = str(body.get("nextPageToken") or body.get("next_page_token") or "")
            if not next_token:
                return result
            if next_token == page_token or next_token in seen_tokens:
                raise MemosError("Memos 分页 token 未前进")
            seen_tokens.add(next_token)
            page_token = next_token
        raise MemosError("Memos 分页超过安全上限")

    def create_memo(self, content: str, visibility: str = "PRIVATE") -> dict[str, Any]:
        """创建一条用户已经确认的终稿 Memo。"""

        if not content.strip():
            raise MemosError("拒绝创建空 Memo")
        return self._request("POST", "/api/v1/memos", {"content": content, "visibility": visibility})

    def update_memo(self, name: str, content: str) -> dict[str, Any]:
        """更新指定 Memo 正文；调用方必须先完成用户授权判断。"""

        path = self._memo_path(name)
        return self._request("PATCH", f"{path}?update_mask=content", {"name": name, "content": content})

    def pin_memo(self, name: str, pinned: bool = True) -> dict[str, Any]:
        """更新主线或活跃阶段目标的置顶状态。"""

        path = self._memo_path(name)
        return self._request("PATCH", f"{path}?update_mask=pinned", {"name": name, "pinned": pinned})

    def archive_memo(self, name: str) -> dict[str, Any]:
        """归档已结案目标，绝不删除历史。"""

        path = self._memo_path(name)
        return self._request("PATCH", f"{path}?update_mask=state", {"name": name, "state": "ARCHIVED"})

    def comment(self, parent_name: str, content: str) -> dict[str, Any]:
        """以 COMMENT relation 创建阶段进度或决定日志。"""

        path = self._memo_path(parent_name)
        return self._request("POST", f"{path}/comments", {"content": content, "visibility": "PRIVATE"})

    def set_reference(self, name: str, related_name: str) -> dict[str, Any]:
        """把阶段目标关联到主线；该操作只设置可变 REFERENCE relation。"""

        path = self._memo_path(name)
        payload = {
            "name": name,
            "relations": [
                {
                    "memo": {"name": name},
                    "relatedMemo": {"name": related_name},
                    "type": "REFERENCE",
                }
            ],
        }
        return self._request("PATCH", f"{path}/relations", payload)

    def create_attachment(
        self,
        filename: str,
        mime_type: str,
        content: bytes,
        memo_name: str,
        attachment_id: str | None = None,
    ) -> dict[str, Any]:
        """按 Memos 0.30 AttachmentService 契约上传并直接关联终稿。"""

        if not filename.strip() or not mime_type.strip() or not content:
            raise MemosError("附件文件名、类型和内容不能为空")
        if not memo_name.startswith("memos/"):
            raise MemosError("附件必须关联规范的 memos/UID")
        # Proto 的 HTTP 映射是 body: "attachment"，因此 REST body 直接是 Attachment，
        # 不能再包一层 {"attachment": ...}。
        payload = {
            "filename": filename,
            "type": mime_type,
            "content": base64.b64encode(content).decode("ascii"),
            "memo": memo_name,
        }
        path = "/api/v1/attachments"
        if attachment_id:
            path += "?" + urlencode({"attachment_id": attachment_id})
        result = self._request("POST", path, payload)
        if not str(result.get("name", "")).startswith("attachments/"):
            raise MemosError("Memos 附件响应缺少规范 name")
        return result

    def get_attachment(self, name: str) -> dict[str, Any]:
        """读取一个稳定附件，供网络成功但本地回执中断后的幂等恢复。"""

        uid = name.removeprefix("attachments/").strip("/")
        if not uid:
            raise MemosError("Attachment name 不能为空")
        return self._request("GET", f"/api/v1/attachments/{uid}")

    @staticmethod
    def _memo_path(name: str) -> str:
        """把 `memos/UID` 或 UID 规范为 API 路径。"""

        uid = name.removeprefix("memos/").strip("/")
        if not uid:
            raise MemosError("Memo name 不能为空")
        return f"/api/v1/memos/{uid}"
