from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Request

from .configuration import json_body
from .proxy import mutation


def register(app,review,settings,manager,authenticated):
    response_class=app.router.default_response_class

    def identifier(value):
        if not 1<=len(value)<=256: raise HTTPException(400)
        return quote(value,safe='')

    async def invoke(method,path,mutate=False,**kwargs):
        if not settings.review_token: raise HTTPException(503)
        try:
            async with mutation(manager, 'review', enabled=mutate):
                response=await review.request(method,path,**kwargs)
                payload=response.json()
        except (httpx.RequestError,ValueError):
            raise HTTPException(502) from None
        if response.is_success:
            return response_class(payload,status_code=response.status_code)
        if response.status_code in (400,404,409,422) and isinstance(payload,dict):
            error=payload.get('error')
            if isinstance(error,dict) and error.get('code') in ('bad_request','not_found','conflict','expired','validation') and isinstance(error.get('message'),str):
                return response_class({'error':{key:error.get(key) for key in ('code','message','field')}},status_code=response.status_code)
        raise HTTPException(502)

    @app.get('/api/v1/review/sessions',dependencies=[Depends(authenticated)])
    async def sessions(kind:str|None=None,limit:int=14):
        if kind not in (None,'daily','weekly') or not 1<=limit<=100: raise HTTPException(400)
        return await invoke('GET','/v1/reviews',params={'limit':limit,**({'kind':kind} if kind else {})})

    @app.get('/api/v1/review/sessions/{value}',dependencies=[Depends(authenticated)])
    async def detail(value:str):
        return await invoke('GET','/v1/reviews/'+identifier(value))

    @app.post('/api/v1/review/sessions/{value}/preview',dependencies=[Depends(authenticated)])
    async def preview(value:str,request:Request):
        return await invoke('POST','/v1/reviews/'+identifier(value)+'/preview',json=await json_body(request,131072))

    async def write(path,request):
        body=await json_body(request,131072)
        return await invoke('POST',path,json=body,mutate=body.get('dry_run') is not True,timeout=30)

    @app.post('/api/v1/review/sessions/{value}/finalize',dependencies=[Depends(authenticated)])
    async def finalize(value:str,request:Request):
        return await write('/v1/reviews/'+identifier(value)+'/finalize',request)

    @app.post('/api/v1/stage/goals/{value}/comments',dependencies=[Depends(authenticated)])
    async def comment(value:str,request:Request):
        return await write('/v1/stage/goals/'+identifier(value)+'/comments',request)

    @app.post('/api/v1/stage/cycles/{value}/close',dependencies=[Depends(authenticated)])
    async def close(value:str,request:Request):
        return await write('/v1/stage/cycles/'+identifier(value)+'/close',request)

    @app.post('/api/v1/stage/cycles',dependencies=[Depends(authenticated)])
    async def create_cycle(request:Request):
        return await write('/v1/stage/cycles',request)

    @app.post('/api/v1/stage/cycles/{value}/goals',dependencies=[Depends(authenticated)])
    async def create_goal(value:str,request:Request):
        return await write('/v1/stage/cycles/'+identifier(value)+'/goals',request)
