"""Mac Connector 写入 NAS 的最小微信 Webhook。"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool


class WebhookInteraction(BaseModel):
    """保留线上互动契约；带明确前缀的消息内容可由已有客户端补齐。"""

    model_config = ConfigDict(extra="forbid")

    person_name: str = Field(min_length=1, max_length=200)
    wxid: str | None = Field(default=None, max_length=200)
    occurred_at: datetime
    interaction_type: str = "message"
    channel: str = "wechat"
    direction: str
    summary: str = Field(min_length=1)
    message: dict[str, Any] | None = None
    source_reference: str | None = Field(default=None, max_length=1000)
    source_event_key: str = Field(min_length=1, max_length=128)
    source_message_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class WebhookFact(BaseModel):
    """连接器自动确认的人物事实。"""

    model_config = ConfigDict(extra="forbid")

    person_name: str = Field(min_length=1, max_length=200)
    wxid: str | None = Field(default=None, max_length=200)
    fact_type: str
    content: str = Field(min_length=1, max_length=2000)
    observed_at: datetime
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_event_key: str | None = Field(default=None, max_length=128)


class WebhookPayload(BaseModel):
    """连接器批量同步契约。"""

    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    source: str = Field(min_length=1, max_length=80)
    client_id: str = Field(default="legacy", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    synced_through: datetime | None = None
    interactions: list[WebhookInteraction] = Field(default_factory=list, max_length=1000)
    facts: list[WebhookFact] = Field(default_factory=list, max_length=1000)


def create_router(repository, secret: str) -> APIRouter:
    """创建带共享密钥与整批事务语义的路由。"""

    api = APIRouter()

    def authenticate(token: str | None) -> None:
        """同步和状态查询共用 Webhook 令牌鉴权。"""

        if not secret:
            raise HTTPException(status_code=503, detail="webhook is not configured")
        if not token or not hmac.compare_digest(token, secret):
            raise HTTPException(status_code=401, detail="invalid webhook token")

    @api.get("/api/v1/webhooks/wechat/clients")
    def clients(x_webhook_token: str | None = Header(default=None)):
        """提供受保护的多客户端同步状态，便于核验每台设备的成功水位。"""

        authenticate(x_webhook_token)
        return {"clients": repository.list_sync_clients()}

    @api.post("/api/v1/webhooks/wechat")
    def receive(
        payload: WebhookPayload,
        x_webhook_token: str | None = Header(default=None),
    ):
        """令牌通过后原子导入；任何业务错误都不接受部分数据。"""

        authenticate(x_webhook_token)
        try:
            accepted, duplicates = repository.import_wechat_batch(
                payload.source,
                [item.model_dump() for item in payload.interactions],
                [item.model_dump() for item in payload.facts],
                client_id=payload.client_id,
                batch_id=str(payload.batch_id),
                synced_through=payload.synced_through,
            )
        except (ValueError, TypeError) as error:
            # 仅回传错误类别，不回显可能包含私人内容的输入值。
            return JSONResponse(
                status_code=422,
                content={
                    "batch_id": str(payload.batch_id),
                    "accepted": 0,
                    "duplicates": 0,
                    "errors": [type(error).__name__],
                },
            )
        return {
            "batch_id": str(payload.batch_id),
            "client_id": payload.client_id,
            "accepted": accepted,
            "duplicates": duplicates,
            "errors": [],
        }

    @api.put("/api/v1/webhooks/wechat/media/{event_key}")
    async def media(
        event_key: str, request: Request,
        name: str = Query(min_length=1, max_length=255),
        message_key: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$"),
        x_webhook_token: str | None = Header(default=None),
        x_content_sha256: str = Header(default=""),
    ):
        """复用微信出站令牌，流式上传并绑定既有微信消息。"""
        authenticate(x_webhook_token)
        if repository.hub_store is None:
            raise HTTPException(503, "media_archive_unavailable")
        if not re.fullmatch(r"[a-f0-9]{64}", event_key) or not re.fullmatch(r"[a-f0-9]{64}", x_content_sha256):
            raise HTTPException(422, "invalid_media_identity")
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        if not name or "\x00" in name or name in {".", ".."}:
            raise HTTPException(422, "invalid_media_name")
        media_type = request.headers.get("Content-Type", "application/octet-stream")
        if not re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", media_type):
            raise HTTPException(422, "invalid_media_type")
        from personal_data_hub.contracts import Asset
        fd, filename = tempfile.mkstemp(prefix=".wechat-upload-", dir=repository.hub_store.root)
        path = Path(filename)
        try:
            digest = hashlib.sha256(); size = 0
            with os.fdopen(fd, "wb") as output:
                async for block in request.stream():
                    size += len(block)
                    if size > 8 * 1024 ** 3:
                        raise HTTPException(413, "media_too_large")
                    digest.update(block); output.write(block)
                output.flush(); os.fsync(output.fileno())
            if not size or not hmac.compare_digest(digest.hexdigest(), x_content_sha256):
                raise HTTPException(422, "media_hash_mismatch")
            try:
                result = await run_in_threadpool(repository.attach_wechat_media, event_key, message_key, Asset(name, path=path, media_type=media_type))
            except ValueError:
                raise HTTPException(422, "media_binding_failed") from None
            return JSONResponse(status_code=404 if result["status"] == "pending" else 200, content=result)
        finally:
            path.unlink(missing_ok=True)

    return api


# 保留早期工厂名，避免部署脚本或扩展模块在升级时立即失效。
router = create_router
