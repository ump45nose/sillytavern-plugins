"""Mac Connector 写入 NAS 的最小微信 Webhook。"""

from __future__ import annotations

import hmac
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class WebhookInteraction(BaseModel):
    """只允许互动摘要字段，主动拒绝 raw/text/content 等完整正文。"""

    model_config = ConfigDict(extra="forbid")

    person_name: str = Field(min_length=1, max_length=200)
    wxid: str | None = Field(default=None, max_length=200)
    occurred_at: datetime
    interaction_type: str = "message"
    channel: str = "wechat"
    direction: str
    summary: str = Field(min_length=1, max_length=1000)
    source_reference: str | None = Field(default=None, max_length=1000)
    source_event_key: str = Field(min_length=1, max_length=128)


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
    interactions: list[WebhookInteraction] = Field(default_factory=list, max_length=1000)
    facts: list[WebhookFact] = Field(default_factory=list, max_length=1000)


def create_router(repository, secret: str) -> APIRouter:
    """创建带共享密钥与整批事务语义的路由。"""

    api = APIRouter()

    @api.post("/api/v1/webhooks/wechat")
    def receive(
        payload: WebhookPayload,
        x_webhook_token: str | None = Header(default=None),
    ):
        """令牌通过后原子导入；任何业务错误都不接受部分数据。"""

        if not secret:
            raise HTTPException(status_code=503, detail="webhook is not configured")
        if not x_webhook_token or not hmac.compare_digest(x_webhook_token, secret):
            raise HTTPException(status_code=401, detail="invalid webhook token")
        try:
            accepted, duplicates = repository.import_wechat_batch(
                payload.source,
                [item.model_dump() for item in payload.interactions],
                [item.model_dump() for item in payload.facts],
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
            "accepted": accepted,
            "duplicates": duplicates,
            "errors": [],
        }

    return api


# 保留早期工厂名，避免部署脚本或扩展模块在升级时立即失效。
router = create_router
