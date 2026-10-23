import json
from datetime import date
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    token_limit_percent: Annotated[float, Field(ge=0,le=100)] = 80
    traffic_remaining_percent: Annotated[float, Field(ge=0,le=100)] = 10
    traffic_expiry_days: Annotated[int, Field(ge=0,le=3650)] = 3
    git_reply_hours: Annotated[int, Field(ge=0,le=87600)] = 24
    pr_blocked_days: Annotated[int, Field(ge=0,le=3650)] = 3
    subs_renew_days: Annotated[int, Field(ge=0,le=3650)] = 7
    stale_contact_days: Annotated[int, Field(ge=0,le=3650)] = 30
    cycle_start: date | None = None
    month_budget: Annotated[float, Field(ge=0,multiple_of=0.01)] | None = None
    step_goal: Annotated[int, Field(gt=0)] = 8600
    kcal_goal: Annotated[float, Field(gt=0)] = 520
    exercise_goal: Annotated[float, Field(gt=0)] = 45


def preferences(store, user_id=None):
    row = store.document('preferences', user_id)
    return Preferences.model_validate(row['document'] if row else {}).model_dump(mode='json')


async def json_body(request, limit=65536):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit: raise HTTPException(400)
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError): raise HTTPException(400)
    if not isinstance(value,dict): raise HTTPException(400)
    return value


def register(app, store, context, authenticated, now, source_authenticated):
    manager = context.sources
    @app.get('/api/v1/net/plans', dependencies=[Depends(authenticated)])
    @app.put('/api/v1/net/plans', dependencies=[Depends(authenticated)])
    async def retired_net_plans():
        raise HTTPException(410, 'network subscriptions are managed by Personal Subscriptions')

    @app.get('/api/v1/layout',dependencies=[Depends(authenticated)])
    def get_layout(identity=Depends(authenticated)):
        row=store.document('layout', identity['user_id'])
        if row is None: raise HTTPException(404)
        return {k:v for k,v in row.items() if k!='updated_by'}

    @app.get('/api/v1/preferences',dependencies=[Depends(authenticated)])
    def get_preferences(identity=Depends(authenticated)):
        user_id=identity['user_id']
        row=store.document('preferences', user_id)
        return {**({k:v for k,v in row.items() if k!='updated_by'} if row else {'version':0,'updated_at':None}), 'document':preferences(store, user_id)}

    async def put(request, name, if_match, identity):
        user_id=identity['user_id']
        if not if_match or (len(if_match)>20 or not if_match.isdecimal()): raise HTTPException(400)
        body=await json_body(request,69632)
        if set(body)!={'document'} or not isinstance(body['document'],dict): raise HTTPException(400)
        document=body['document']
        try:
            if len(json.dumps(document,ensure_ascii=False,allow_nan=False).encode())>65536: raise HTTPException(400)
            if name=='preferences': document=Preferences.model_validate(document).model_dump(mode='json')
        except (ValueError,RecursionError): raise HTTPException(400)
        previous=preferences(store, user_id) if name=='preferences' else None
        success,row=store.put_document(name,document,int(if_match),now().isoformat(), user_id, identity['device_id'])
        if not success:
            if name=='preferences' and row is None:
                row={'version':0,'updated_at':None,'document':previous}
            return app.router.default_response_class({'error':{'code':'conflict','message':'conflict'},'current':{k:v for k,v in row.items() if k!='updated_by'} if row else None},status_code=409)
        if name=='preferences' and user_id==store.owner_id and previous['cycle_start']!=document['cycle_start']:
            await manager.invalidate('crm','plaud')
        return {k:v for k,v in row.items() if k!='updated_by'}

    @app.put('/api/v1/layout',dependencies=[Depends(authenticated)])
    async def put_layout(request:Request,if_match:str|None=Header(default=None),identity=Depends(authenticated)):
        return await put(request,'layout',if_match,identity)

    @app.put('/api/v1/preferences',dependencies=[Depends(authenticated)])
    async def put_preferences(request:Request,if_match:str|None=Header(default=None),identity=Depends(authenticated)):
        return await put(request,'preferences',if_match,identity)

    @app.get('/api/v1/subscriptions',dependencies=[Depends(source_authenticated)])
    async def get_subscriptions():
        from .modules import modules
        return (await modules(context,['subs']))['subs']['data']

    @app.put('/api/v1/subscriptions',dependencies=[Depends(authenticated)])
    async def retired_subscriptions():
        raise HTTPException(410, 'use per-record subscription operations')
