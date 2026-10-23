import base64
import re
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator, model_validator

from .configuration import json_body
from .proxy import mutation, stream_response
from .memo_upload import read_upload, too_large
from .sources.memos import NotOwnAttachment, NotOwnMemo


AttachmentName = Annotated[str, Field(pattern=r'^attachments/[A-Za-z0-9_-]{1,64}$')]


class MemoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=100000)
    visibility: Literal['PRIVATE', 'PROTECTED', 'PUBLIC'] = 'PRIVATE'
    attachments: list[AttachmentName] = Field(default_factory=list, max_length=1000)


class MemoPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str | None = Field(default=None, min_length=1, max_length=100000)
    visibility: Literal['PRIVATE', 'PROTECTED', 'PUBLIC'] | None = None
    pinned: StrictBool | None = None
    attachments: list[AttachmentName] | None = Field(default=None, max_length=1000)
    state: Literal['NORMAL'] | None = None

    @field_validator('attachments', 'state')
    @classmethod
    def nonnull(cls, value):
        if value is None:
            raise ValueError('null is not supported')
        return value

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
        except NotOwnAttachment:
            raise HTTPException(422) from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise HTTPException(status if status in (400, 404, 409, 413, 422) else 502) from None
        except (httpx.RequestError, ValueError, KeyError, TypeError):
            raise HTTPException(502) from None

    async def body(request, model):
        try:
            return model.model_validate(await json_body(request, 131072)).model_dump(exclude_unset=True)
        except ValidationError as exc:
            status = 422 if any(e['loc'][0] in ('attachments', 'state') for e in exc.errors() if e['loc']) else 400
            raise HTTPException(status) from None

    async def attachments(payload):
        for name in payload.get('attachments', []):
            await invoke(lambda: memos.own_attachment(name))
        if 'attachments' in payload:
            payload['attachments'] = [{'name': name} for name in payload['attachments']]

    async def write(method, path, payload, params=None):
        async def forward():
            async with mutation(manager, 'memos'):
                return await memos.personal.request('memos', path, method=method, body=payload, params=params)
        return await invoke(forward)

    @app.get('/api/v1/memos', dependencies=[Depends(authenticated)])
    async def list_memos(page_size: int = Query(default=20, ge=1, le=100),
                         page_token: str = Query(default='', max_length=4096),
                         tag: str = Query(default='', max_length=256), q: str = Query(default='', max_length=1000),
                         pinned: bool | None = None, has_attachments: bool | None = None,
                         state: Literal['NORMAL', 'ARCHIVED'] = 'NORMAL'):
        if has_attachments is not None:
            return JSONResponse({'detail': 'Memos 0.30 暂不支持有附件筛选'}, status_code=501)
        return await invoke(lambda: memos.list(page_size, page_token, tag, q, pinned, state))

    # Register static attachment endpoints before the dynamic memo ID route.
    @app.post('/api/v1/memos/attachments', status_code=201, dependencies=[Depends(authenticated)])
    async def upload_attachment(request: Request):
        limit_mb = await invoke(memos.upload_limit_mb)
        upload = await read_upload(request, limit_mb)
        if isinstance(upload, Response):
            return upload
        filename, content = upload
        # Memos accepts protobuf JSON bytes (base64), not multipart. Let Memos
        # infer and normalize MIME from the unmodified filename/content.
        try:
            value = await write('POST', '/api/v1/attachments', {
                'filename': filename, 'content': base64.b64encode(content).decode('ascii')})
        except HTTPException as exc:
            if exc.status_code == 413:
                return too_large(limit_mb)
            raise
        return {**{k: value[k] for k in ('name', 'filename', 'type')}, 'size': int(value['size'])}

    @app.delete('/api/v1/memos/attachments/{name:path}', status_code=204, dependencies=[Depends(authenticated)])
    async def delete_attachment(name: str):
        name = name if name.startswith('attachments/') else 'attachments/'+name
        try:
            asset = await invoke(lambda: memos.own_attachment(name))
        except HTTPException as exc:
            if exc.status_code == 422:
                raise HTTPException(409) from None
            raise
        if asset.get('memo'):
            raise HTTPException(409)
        await write('DELETE', '/api/v1/'+name, None)
        return Response(status_code=204)

    @app.get('/api/v1/memos/{identifier}', dependencies=[Depends(authenticated)])
    async def get_memo(identifier: str):
        value = await invoke(lambda: memos.own(identifier))
        return memos.normalize(value)

    @app.post('/api/v1/memos', status_code=201, dependencies=[Depends(authenticated)])
    async def create_memo(request: Request):
        payload = await body(request, MemoInput)
        payload.setdefault('visibility', 'PRIVATE')
        await attachments(payload)
        value = await write('POST', '/api/v1/memos', payload)
        return memos.normalize(value)

    @app.patch('/api/v1/memos/{identifier}', dependencies=[Depends(authenticated)])
    async def update_memo(identifier: str, request: Request):
        payload = await body(request, MemoPatch)
        await invoke(lambda: memos.own(identifier))
        await attachments(payload)
        value = await write('PATCH', '/api/v1/memos/'+identifier, payload, {'update_mask': ','.join(payload)})
        return memos.normalize(value)

    @app.delete('/api/v1/memos/{identifier}', status_code=204, dependencies=[Depends(authenticated)])
    async def archive_memo(identifier: str):
        await invoke(lambda: memos.own(identifier))
        await write('PATCH', '/api/v1/memos/'+identifier, {'state': 'ARCHIVED'}, {'update_mask': 'state'})
        return Response(status_code=204)

    @app.get('/api/v1/memos/{identifier}/attachments/{name:path}', dependencies=[Depends(authenticated)])
    async def attachment(identifier: str, name: str, thumbnail: bool = False):
        match = re.fullmatch(r'(?:attachments/)?([A-Za-z0-9_-]{1,64})', name)
        if not match:
            raise HTTPException(404)
        value = await invoke(lambda: memos.own(identifier))
        asset = next((a for a in value.get('attachments', []) if a.get('name') == 'attachments/'+match[1]), None)
        if asset is None:
            raise HTTPException(404)
        # Never follow externalLink. Active and non-image formats download as files.
        media_type = asset.get('type')
        if not isinstance(media_type, str) or asset.get('externalLink'):
            raise HTTPException(404)
        filename = asset.get('filename')
        if not isinstance(filename, str) or filename in ('', '.', '..') or '/' in filename or '\\' in filename:
            raise HTTPException(404)
        path = '/file/attachments/'+match[1]+'/'+quote(filename, safe='')
        request = memos.personal.client.build_request('GET', settings.memos_url.rstrip('/')+path,
            headers={'Authorization': 'Bearer '+settings.memos_token.get_secret_value()},
            params={'thumbnail': 'true'} if thumbnail else None)
        try:
            upstream = await memos.personal.client.send(request, stream=True)
        except httpx.RequestError:
            raise HTTPException(502) from None
        if upstream.status_code != 200:
            status = upstream.status_code
            await upstream.aclose()
            raise HTTPException(404 if status == 404 else 502)
        media_type = upstream.headers.get('content-type', media_type)
        headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'X-Accel-Buffering': 'no'}
        if media_type.split(';', 1)[0] not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif', 'image/heic', 'image/heif'):
            headers['Content-Disposition'] = "attachment; filename*=UTF-8''"+quote(filename, safe='')
        return stream_response(upstream, headers={**headers, 'Content-Type': media_type})
