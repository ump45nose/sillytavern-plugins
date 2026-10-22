from fastapi import Depends, Header, HTTPException, Request
from .configuration import json_body


def register(app, source, settings, manager, authenticated):
    async def proxy(method, path, body=None, version=None):
        write = method != 'GET'
        if not (settings.subscriptions_write_token if write else settings.subscriptions_token): raise HTTPException(503)
        options = {'json': body} if body is not None else {}
        if version is not None: options['headers'] = {'If-Match': version}
        response = await source.request(method, path, write=write, **options)
        if response.status_code >= 400:
            raise HTTPException(response.status_code if response.status_code in (400,404,409,413,422,428,429) else 502)
        if write: await manager.invalidate('subscriptions')
        return response.json()

    @app.get('/api/v1/subscriptions/sources', dependencies=[Depends(authenticated)])
    async def sources(): return await proxy('GET', 'sources')

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
