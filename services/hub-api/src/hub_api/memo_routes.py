import re
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator
from starlette.background import BackgroundTask

from .configuration import json_body
from .sources.memos import NotOwnMemo


class MemoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=100000)
    visibility: Literal['PRIVATE', 'PROTECTED', 'PUBLIC'] = 'PRIVATE'


class MemoPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str | None = Field(default=None, min_length=1, max_length=100000)
    visibility: Literal['PRIVATE', 'PROTECTED', 'PUBLIC'] | None = None
    pinned: StrictBool | None = None

    @model_validator(mode='after')
    def provided(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError('nonempty patch required')
        return self


def register(app, settings, memos, authenticated, manager):
    async def invoke(operation):
        if not settings.memos_token:
            raise HTTPException(503)
        try:
            return await operation()
        except NotOwnMemo:
            raise HTTPException(404) from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise HTTPException(status if status in (400, 404, 409, 422) else 502) from None
        except (httpx.RequestError, ValueError, KeyError, TypeError):
            raise HTTPException(502) from None

    async def body(request, model):
        try:
            return model.model_validate(await json_body(request, 131072)).model_dump(exclude_unset=True)
        except ValidationError:
            raise HTTPException(400) from None

    async def write(method, path, payload, params=None):
        async def forward():
            try:
                return await memos.personal.request('memos', path, method=method, body=payload, params=params)
            finally:
                # A timeout/5xx may follow a successful write; never keep the old module cache.
                await manager.invalidate('memos')
        return await invoke(forward)

    @app.get('/api/v1/memos', dependencies=[Depends(authenticated)])
    async def list_memos(page_size: int = Query(default=20, ge=1, le=100),
                         page_token: str = Query(default='', max_length=4096),
                         tag: str = Query(default='', max_length=256), q: str = Query(default='', max_length=1000)):
        return await invoke(lambda: memos.list(page_size, page_token, tag, q))

    @app.get('/api/v1/memos/{identifier}', dependencies=[Depends(authenticated)])
    async def get_memo(identifier: str):
        value = await invoke(lambda: memos.own(identifier))
        return memos.normalize(value)

    @app.post('/api/v1/memos', status_code=201, dependencies=[Depends(authenticated)])
    async def create_memo(request: Request):
        payload = await body(request, MemoInput)
        payload.setdefault('visibility', 'PRIVATE')
        value = await write('POST', '/api/v1/memos', payload)
        return memos.normalize(value)

    @app.patch('/api/v1/memos/{identifier}', dependencies=[Depends(authenticated)])
    async def update_memo(identifier: str, request: Request):
        payload = await body(request, MemoPatch)
        await invoke(lambda: memos.own(identifier))
        value = await write('PATCH', '/api/v1/memos/'+identifier, payload, {'update_mask': ','.join(payload)})
        return memos.normalize(value)

    @app.delete('/api/v1/memos/{identifier}', status_code=204, dependencies=[Depends(authenticated)])
    async def archive_memo(identifier: str):
        await invoke(lambda: memos.own(identifier))
        await write('PATCH', '/api/v1/memos/'+identifier, {'state': 'ARCHIVED'}, {'update_mask': 'state'})
        return Response(status_code=204)

    @app.get('/api/v1/memos/{identifier}/attachments/{name:path}', dependencies=[Depends(authenticated)])
    async def attachment(identifier: str, name: str):
        match = re.fullmatch(r'(?:attachments/)?([A-Za-z0-9_-]{1,64})', name)
        if not match:
            raise HTTPException(404)
        value = await invoke(lambda: memos.own(identifier))
        asset = next((a for a in value.get('attachments', []) if a.get('name') == 'attachments/'+match[1]), None)
        if asset is None:
            raise HTTPException(404)
        # Local image attachments only. Never follow externalLink or return active HTML/SVG.
        media_type = asset.get('type')
        if media_type not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif', 'image/heic', 'image/heif') or asset.get('externalLink'):
            raise HTTPException(404)
        filename = asset.get('filename')
        if not isinstance(filename, str) or filename in ('', '.', '..') or '/' in filename or '\\' in filename:
            raise HTTPException(404)
        path = '/file/attachments/'+match[1]+'/'+quote(filename, safe='')
        request = memos.personal.client.build_request('GET', settings.memos_url.rstrip('/')+path,
            headers={'Authorization': 'Bearer '+settings.memos_token.get_secret_value()})
        try:
            upstream = await memos.personal.client.send(request, stream=True)
        except httpx.RequestError:
            raise HTTPException(502) from None
        if upstream.status_code != 200:
            status = upstream.status_code
            await upstream.aclose()
            raise HTTPException(404 if status == 404 else 502)
        async def chunks():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
        return StreamingResponse(chunks(), media_type=media_type,
            headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'},
            background=BackgroundTask(upstream.aclose))
