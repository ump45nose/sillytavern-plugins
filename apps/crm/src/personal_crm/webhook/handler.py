"""Mac Connector 写入 NAS 的最小微信 Webhook。"""

from __future__ import annotations

import hmac
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


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

    return api


# 保留早期工厂名，避免部署脚本或扩展模块在升级时立即失效。
router = create_router
