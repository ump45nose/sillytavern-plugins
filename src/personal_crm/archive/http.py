"""HTTP 只装配验证、认证和归档调用。"""

from __future__ import annotations

import hmac
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .schemas import (
    IdentityInput,
    Input,
    InteractionCreate,
    InteractionPatch,
    PersonCreate,
    PersonPatch,
    WechatBatch,
)
from .service import Conflict, NotFound


class MergeInput(Input):
    source_person_id: str


def register_errors(app):
    @app.exception_handler(NotFound)
    async def missing(_, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(Conflict)
    async def conflict(_, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        # Validation details omit submitted data (private messages / contacts).
        detail = "invalid_input" if isinstance(exc, ValidationError) else str(exc)
        return JSONResponse(status_code=422, content={"detail": detail})


def create_router(archive, authenticate, webhook_secret):
    router = APIRouter(prefix="/api/v1/crm")

    def read(authorization: str | None = Header(default=None)):
        authenticate(authorization, readonly=True)

    def write(authorization: str | None = Header(default=None)):
        authenticate(authorization, readonly=False)

    def collector(x_webhook_token: str | None = Header(default=None)):
        if not webhook_secret:
            raise HTTPException(503, "wechat_ingest_not_configured")
        if not hmac.compare_digest(x_webhook_token or "", webhook_secret):
            raise HTTPException(401, "unauthorized")

    @router.get("/people", dependencies=[Depends(read)])
    def list_people(
        query: str = "", tag: str | None = None, limit: int = 50, cursor: str | None = None
    ):
        return archive.list_people(query=query, tag=tag, limit=limit, cursor=cursor)

    @router.post("/people", dependencies=[Depends(write)], status_code=201)
    def create_person(data: PersonCreate):
        return archive.create_person(data.model_dump())

    @router.get("/people/{person_id}", dependencies=[Depends(read)])
    def get_person(person_id: str):
        return archive.get_person(person_id)

    @router.patch("/people/{person_id}", dependencies=[Depends(write)])
    def update_person(person_id: str, data: PersonPatch):
        return archive.update_person(person_id, data.model_dump(exclude_unset=True))

    @router.delete("/people/{person_id}", dependencies=[Depends(write)])
    def delete_person(person_id: str):
        return archive.delete_person(person_id)

    @router.post("/people/{person_id}/merge", dependencies=[Depends(write)])
    def merge_person(person_id: str, data: MergeInput):
        return archive.merge_people(data.source_person_id, person_id)

    @router.put("/people/{person_id}/identities", dependencies=[Depends(write)])
    def bind(person_id: str, data: IdentityInput):
        return archive.bind_person_identity(person_id, data.model_dump())

    @router.get("/interactions", dependencies=[Depends(read)])
    def list_interactions(
        person_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        type: str | None = None,
        channel: str | None = None,
        source: str | None = None,
        query: str = "",
        limit: int = 50,
        cursor: str | None = None,
    ):
        return archive.list_interactions(
            person_id=person_id,
            start=start,
            end=end,
            type=type,
            channel=channel,
            source=source,
            query=query,
            limit=limit,
            cursor=cursor,
        )

    @router.post("/interactions", dependencies=[Depends(write)], status_code=201)
    def create_interaction(data: InteractionCreate):
        return archive.create_interaction(data.model_dump())

    @router.get("/interactions/{interaction_id}", dependencies=[Depends(read)])
    def get_interaction(interaction_id: str):
        return archive.get_interaction(interaction_id)

    @router.patch("/interactions/{interaction_id}", dependencies=[Depends(write)])
    def update_interaction(interaction_id: str, data: InteractionPatch):
        return archive.update_interaction(interaction_id, data.model_dump(exclude_unset=True))

    @router.delete("/interactions/{interaction_id}", dependencies=[Depends(write)])
    def delete_interaction(interaction_id: str):
        return archive.delete_interaction(interaction_id)

    @router.post("/attachments", dependencies=[Depends(write)], status_code=201)
    def upload(file: UploadFile):
        return archive.upload_attachment(
            file.filename or "attachment",
            file.content_type or "application/octet-stream",
            iter(lambda: file.file.read(1024 * 1024), b""),
        )

    @router.get("/attachments/{attachment_id}", dependencies=[Depends(read)])
    def attachment(attachment_id: str):
        return archive.get_attachment(attachment_id)

    @router.get("/attachments/{attachment_id}/content", dependencies=[Depends(read)])
    def attachment_content(attachment_id: str):
        from sqlalchemy import select

        from .models import attachments

        info = archive.get_attachment(attachment_id)
        if not info["available"]:
            raise HTTPException(404, "attachment_not_archived")
        with archive.engine.connect() as c:
            key = c.scalar(select(attachments.c.file_key).where(attachments.c.id == attachment_id))
        return FileResponse(
            archive.root / key, filename=info["name"], media_type=info["media_type"]
        )

    @router.post("/ingest/wechat", dependencies=[Depends(collector)])
    def ingest(data: WechatBatch):
        return archive.ingest_wechat(data.model_dump())

    @router.get("/ingest/wechat/clients", dependencies=[Depends(collector)])
    def clients():
        return {"clients": archive.list_sync_clients()}

    @router.put("/ingest/wechat/media/{event_key}", dependencies=[Depends(collector)])
    async def media(
        event_key: str,
        request: Request,
        name: str,
        message_key: str | None = None,
        x_content_sha256: str = Header(default=""),
    ):
        import re

        if not re.fullmatch(r"[a-f0-9]{64}", x_content_sha256):
            raise HTTPException(422, "invalid_media_hash")
        with tempfile.TemporaryFile(dir=archive.root) as file:
            async for block in request.stream():
                file.write(block)
            file.seek(0)
            result = await run_in_threadpool(
                archive.attach_wechat_media,
                message_key or event_key,
                iter(lambda: file.read(1024 * 1024), b""),
                Path(name.replace("\\", "/")).name,
                request.headers.get("Content-Type", "application/octet-stream"),
                x_content_sha256,
            )
        return JSONResponse(
            status_code=404 if result["status"] == "pending" else 200, content=result
        )

    return router
