import json
from datetime import date
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError


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


class Subscription(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    id: Annotated[str, Field(min_length=1,max_length=128)]
    name: Annotated[str, Field(min_length=1,max_length=200)]
    price: Annotated[float, Field(ge=0,le=100000000,multiple_of=0.01)]
    currency: Literal['CNY'] = 'CNY'
    cycle: Literal['month','year']
    next_renewal: date | None = None


def preferences(store):
    row = store.document('preferences')
    return Preferences.model_validate(row['document'] if row else {}).model_dump(mode='json')


def subscriptions(store):
    row = store.document('subscriptions')
    return row['document']['items'] if row else []


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


def register(app, store, manager, authenticated, now):
    @app.get('/api/v1/layout',dependencies=[Depends(authenticated)])
    def get_layout():
        row=store.document('layout')
        if row is None: raise HTTPException(404)
        return row

    @app.get('/api/v1/preferences',dependencies=[Depends(authenticated)])
    def get_preferences():
        row=store.document('preferences')
        return {**(row or {'version':0,'updated_at':None}), 'document':preferences(store)}

    async def put(request, name, if_match):
        if not if_match or (len(if_match)>20 or not if_match.isdecimal()): raise HTTPException(400)
        body=await json_body(request,69632)
        if set(body)!={'document'} or not isinstance(body['document'],dict): raise HTTPException(400)
        document=body['document']
        try:
            if len(json.dumps(document,ensure_ascii=False,allow_nan=False).encode())>65536: raise HTTPException(400)
            if name=='preferences': document=Preferences.model_validate(document).model_dump(mode='json')
        except (ValueError,RecursionError): raise HTTPException(400)
        previous=preferences(store) if name=='preferences' else None
        success,row=store.put_document(name,document,int(if_match),now().isoformat())
        if not success:
            if name=='preferences' and row is None:
                row={'version':0,'updated_at':None,'document':previous}
            return app.router.default_response_class({'error':{'code':'conflict','message':'conflict'},'current':row},status_code=409)
        if name=='preferences' and previous['cycle_start']!=document['cycle_start']:
            await manager.invalidate('crm','plaud')
        return row

    @app.put('/api/v1/layout',dependencies=[Depends(authenticated)])
    async def put_layout(request:Request,if_match:str|None=Header(default=None)):
        return await put(request,'layout',if_match)

    @app.put('/api/v1/preferences',dependencies=[Depends(authenticated)])
    async def put_preferences(request:Request,if_match:str|None=Header(default=None)):
        return await put(request,'preferences',if_match)

    @app.get('/api/v1/subscriptions',dependencies=[Depends(authenticated)])
    async def get_subscriptions():
        from .modules import modules
        return (await modules(manager,['subs']))['subs']['data']

    @app.put('/api/v1/subscriptions',dependencies=[Depends(authenticated)])
    async def put_subscriptions(request:Request):
        body=await json_body(request)
        if set(body)!={'items'} or not isinstance(body['items'],list) or len(body['items'])>100: raise HTTPException(400)
        try: items=[Subscription.model_validate(x).model_dump(mode='json') for x in body['items']]
        except ValidationError: raise HTTPException(400)
        if len({x['id'] for x in items})!=len(items): raise HTTPException(400)
        store.put_document('subscriptions',{'items':items},None,now().isoformat())
        await manager.invalidate('records_subscriptions')
        return await get_subscriptions()
