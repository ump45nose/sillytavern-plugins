import re

import httpx
from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import Response
from .configuration import json_body
from .proxy import mutation


def register(app, source, settings, manager, authenticated):
    async def proxy(method, path, body=None, version=None, timeout=None, mutate=None):
        write = method != 'GET'
        mutate = write if mutate is None else mutate
        if not (settings.subscriptions_write_token if write else settings.subscriptions_token): raise HTTPException(503)
        options = {'json': body} if body is not None else {}
        if version is not None: options['headers'] = {'If-Match': version}
        if timeout is not None: options['timeout'] = timeout
        try:
            async with mutation(manager, 'subscriptions', enabled=mutate):
                response = await source.request(method, path, write=write, **options)
        except httpx.RequestError:
            raise HTTPException(502) from None
        if response.status_code >= 400:
            raise HTTPException(response.status_code if response.status_code in (400,404,409,413,422,428,429) else 502)
        try:
            return response.json()
        except ValueError:
            raise HTTPException(502) from None

    @app.get('/api/v1/subscriptions/sources', dependencies=[Depends(authenticated)])
    async def sources(): return await proxy('GET', 'sources')

    @app.post('/api/v1/net/quota-preview', dependencies=[Depends(authenticated)])
    async def preview_quota(request: Request):
        return await proxy('POST', 'subscriptions/quota-preview', await json_body(request), timeout=45, mutate=False)

    @app.get('/api/v1/subscriptions/brands', dependencies=[Depends(authenticated)])
    async def brands(): return await proxy('GET', 'subscriptions/brands')

    @app.get('/api/v1/subscriptions/icons/{service_key}.png', dependencies=[Depends(authenticated)])
    async def icon(service_key: str):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', service_key): raise HTTPException(404)
        if not settings.subscriptions_token: raise HTTPException(503)
        response = await source.request('GET', 'subscriptions/icons/'+service_key+'.png')
        if response.status_code == 404: raise HTTPException(404)
        if response.status_code != 200 or not response.content.startswith(b'\x89PNG\r\n\x1a\n') or len(response.content) > 262144:
            raise HTTPException(502)
        return Response(response.content, media_type='image/png',
                        headers={'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/v1/subscriptions/records', dependencies=[Depends(authenticated)])
    async def listing(offset: int = 0, limit: int = 50):
        if offset < 0 or not 1 <= limit <= 200: raise HTTPException(400)
        return await proxy('GET', f'subscriptions?offset={offset}&limit={limit}')

    @app.post('/api/v1/subscriptions/records', dependencies=[Depends(authenticated)], status_code=201)
    async def create(request: Request): return await proxy('POST', 'subscriptions', await json_body(request))

    @app.get('/api/v1/subscriptions/records/{identifier}', dependencies=[Depends(authenticated)])
    async def detail(identifier: str): return await proxy('GET', 'subscriptions/'+identifier)

    @app.patch('/api/v1/subscriptions/records/{identifier}', dependencies=[Depends(authenticated)])
    async def update(identifier: str, request: Request, if_match: str | None = Header(default=None)):
        if not if_match: raise HTTPException(428)
        return await proxy('PATCH', 'subscriptions/'+identifier, await json_body(request), if_match)

    @app.delete('/api/v1/subscriptions/records/{identifier}', dependencies=[Depends(authenticated)])
    async def delete(identifier: str, if_match: str | None = Header(default=None)):
        if not if_match: raise HTTPException(428)
        return await proxy('DELETE', 'subscriptions/'+identifier, version=if_match)
