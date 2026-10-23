"""Small versioned user documents, controlled source references and app parameters."""
import json
import re
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .configuration import json_body

SECTIONS = ('profile', 'agenda_preferences', 'reader_preferences', 'layout')


class Extensible(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True, allow_inf_nan=False)
    schema_version: Literal[1]


class Profile(Extensible):
    display_name: str | None = Field(default=None, max_length=200)
    timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'


class AgendaResource(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    binding_version: int = Field(ge=1)
    today_list_ids: list[str] | None = Field(default=None, max_length=100)
    default_list_id: str | None = Field(default=None, max_length=1024)
    default_calendar_id: str | None = Field(default=None, max_length=1024)


class Agenda(Extensible):
    bindings: dict[str, AgendaResource] = Field(default_factory=dict, max_length=20)


class Reader(Extensible):
    default_currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    task_grouping: str | None = Field(default=None, max_length=64)
    font_family: str | None = Field(default=None, max_length=200)


class Binding(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    binding_id: str = Field(min_length=1, max_length=200)
    source_type: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    account_ref: str = Field(min_length=1, max_length=200)
    access: Literal['direct', 'hub']
    version: int = Field(default=1, ge=1)


class DesktopClient(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int = Field(ge=1)
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=512)
    auth_uri: Literal['https://accounts.google.com/o/oauth2/auth', 'https://accounts.google.com/o/oauth2/v2/auth'] = 'https://accounts.google.com/o/oauth2/v2/auth'
    token_uri: Literal['https://oauth2.googleapis.com/token'] = 'https://oauth2.googleapis.com/token'
    redirect_uris: list[str] = Field(default_factory=lambda: ['http://127.0.0.1'])


def reject_private(value, depth=0):
    if depth > 20:
        raise ValueError('document too deep')
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r'[^a-z0-9]', '', key.lower())
            if any(word in normalized for word in ('token', 'password', 'secret', 'keychain', 'authorizationcode', 'authcode', 'verifier', 'offlinequeue', 'pendingqueue', 'executionqueue', 'localdirectory', 'shortcut')):
                raise ValueError('device-private data')
            reject_private(child, depth+1)
    elif isinstance(value, list):
        if len(value)>1000:
            raise ValueError('array too large')
        for child in value:
            reject_private(child, depth+1)


def configured_bindings(settings, store):
    if settings.computer_history_root:
        devices=settings.computer_history_devices
        if (not devices or len(set(devices.values()))!=len(devices)
            or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', s) for pair in devices.items() for s in pair)):
            raise ValueError('history requires unique pinned archive device identities')
    if settings.google_desktop_client is not None:
        client = DesktopClient.model_validate(settings.google_desktop_client)
        if not client.redirect_uris or any(not re.fullmatch(r'http://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?(?:/callback)?', uri) for uri in client.redirect_uris):
            raise ValueError('desktop OAuth requires a loopback redirect')
    rows = [Binding.model_validate(row).model_dump() for row in settings.source_bindings]
    if len({r['binding_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate binding id')
    if any(r['access']!='direct' or r['source_type'] not in ('google_tasks','google_calendar') for r in rows):
        raise ValueError('only Google direct account references are configurable in this release')
    if store.owner_id:
        for source, enabled in {
            'records':settings.records_token, 'crm':settings.crm_token, 'plaud':settings.plaud_token,
            'memos':settings.memos_token, 'token':settings.token_secret, 'usage':settings.usage_token,
            'subscriptions':settings.subscriptions_token, 'review':settings.review_token,
            'github':settings.github_token, 'emby':settings.emby_token, 'navidrome':settings.navidrome_password,
            'moviepilot':settings.moviepilot_token, 'qbittorrent':settings.qbittorrent_password,
            'computer_history':settings.computer_history_root,
        }.items():
            if enabled:
                fields={k:(v.get_secret_value() if hasattr(v,'get_secret_value') else str(v))
                        for k,v in settings.__dict__.items() if k.startswith(source+'_')}
                if source=='computer_history':
                    fields['devices']=settings.computer_history_devices
                rows.append({'binding_id':str(uuid5(NAMESPACE_URL, store.instance_id+':'+source)), 'source_type':source,
                             'account_ref':'instance:'+source, 'access':'hub', 'version':1,
                             '_configuration_hash':store.digest(json.dumps(fields,sort_keys=True))})
    return rows


def validate_document(section, document, bindings):
    reject_private(document)
    if len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode()) > (65536 if section=='layout' else 16384):
        raise ValueError('document too large')
    if section=='layout':
        # Legacy LayoutDocument has its own version, not schema_version.
        if 'version' in document and (type(document['version']) is not int or document['version']!=1):
            raise ValueError('unsupported layout version')
        return document
    model = {'profile':Profile, 'agenda_preferences':Agenda, 'reader_preferences':Reader}[section]
    if type(document.get('schema_version')) is not int:
        raise ValueError('schema_version must be an integer')
    result = model.model_validate(document).model_dump(exclude_unset=True)
    if section=='profile':
        result['timezone']='Asia/Shanghai'
    if section=='agenda_preferences':
        current = {r['binding_id']:r for r in bindings['items']}
        for identifier, resource in result.get('bindings', {}).items():
            binding=current.get(identifier)
            if not binding or binding['access']!='direct' or binding['version']!=resource['binding_version']:
                raise ValueError('unknown or outdated binding')
            if any(len(s)>1024 for s in resource.get('today_list_ids') or []):
                raise ValueError('resource ID too long')
            if binding['source_type']=='google_tasks' and resource.get('default_calendar_id') is not None:
                raise ValueError('calendar resource on tasks binding')
            if binding['source_type']=='google_calendar' and (resource.get('today_list_ids') is not None or resource.get('default_list_id') is not None):
                raise ValueError('task resource on calendar binding')
    return result


def expected_version(value):
    if value is None:
        raise HTTPException(428)
    if len(value)>22:
        raise HTTPException(400)
    match=re.fullmatch(r'"?([0-9]{1,18})"?', value)
    if not match or value.startswith('"') != value.endswith('"'):
        raise HTTPException(400)
    return int(match[1])


def register(app, settings, store, authenticated, now):
    @app.middleware('http')
    async def state_cache_headers(request, call_next):
        response=await call_next(request)
        if (request.url.path in ('/api/v1/me', '/api/v1/source-bindings')
            or request.url.path.startswith(('/api/v1/user-state/', '/api/v1/sync/', '/api/v1/google/', '/api/v1/computer-history/'))):
            response.headers['Cache-Control']='no-store'
        return response

    def section_exists(section):
        if section not in SECTIONS:
            raise HTTPException(404)

    def response(row, status=200):
        return app.router.default_response_class(row, status_code=status, headers={'ETag':'"'+str(row['version'])+'"','Cache-Control':'no-store'})

    def commit(section, document, expected, identity):
        try:
            document=validate_document(section, document, store.bindings(identity['user_id']))
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(400) from None
        success, row=store.put_document(section, document, expected, now().isoformat(), identity['user_id'], identity['device_id'])
        if not success:
            return app.router.default_response_class({'error':{'code':'conflict','message':'conflict'},'current':row}, status_code=409)
        return response(row)

    @app.get('/api/v1/me')
    def me(identity=Depends(authenticated)):
        return {'hub_instance_id':store.instance_id, **identity, 'timezone':'Asia/Shanghai', 'capabilities':{
            'user_state':1, 'user_state_sections':list(SECTIONS), 'state_history':True,
            'source_bindings':1, 'google_desktop_client':settings.google_desktop_client is not None,
            'computer_history':bool(settings.computer_history_root and identity['user_id']==store.owner_id),
            'business_sources':identity['user_id']==store.owner_id}}

    @app.get('/api/v1/source-bindings')
    def bindings(identity=Depends(authenticated)):
        return store.bindings(identity['user_id'])

    @app.get('/api/v1/google/desktop-client')
    def google_client(identity=Depends(authenticated)):
        if settings.google_desktop_client is None:
            return app.router.default_response_class({'error':{'code':'google_desktop_client_unconfigured','message':'Desktop OAuth application is not configured'}},status_code=503)
        return app.router.default_response_class(DesktopClient.model_validate(settings.google_desktop_client).model_dump(exclude_none=True),headers={'Cache-Control':'no-store'})

    @app.get('/api/v1/sync/state')
    def state(identity=Depends(authenticated)):
        versions=store.versions(identity['user_id'])
        return {'sections':{s:versions.get(s, {'version':0,'updated_at':None,'updated_by':None}) for s in SECTIONS},
                'source_bindings_version':store.bindings(identity['user_id'])['version']}

    @app.get('/api/v1/user-state/{section}')
    def get_state(section:str, identity=Depends(authenticated)):
        section_exists(section)
        row=store.document(section, identity['user_id'])
        if row is None:
            raise HTTPException(404)
        if section=='agenda_preferences':
            bindings={r['binding_id']:r['version'] for r in store.bindings(identity['user_id'])['items']}
            row['invalid_binding_ids']=[k for k,v in row['document'].get('bindings',{}).items() if bindings.get(k)!=v.get('binding_version')]
        return response(row)

    @app.put('/api/v1/user-state/{section}')
    async def put_state(section:str, request:Request, if_match:str|None=Header(default=None), identity=Depends(authenticated)):
        section_exists(section)
        expected=expected_version(if_match)
        body=await json_body(request,69632)
        if set(body)!={'document'} or not isinstance(body['document'],dict):
            raise HTTPException(400)
        return commit(section, body['document'], expected, identity)

    @app.get('/api/v1/user-state/{section}/history')
    def history(section:str, identity=Depends(authenticated)):
        section_exists(section)
        return {'items':store.history(section, identity['user_id'])}

    @app.post('/api/v1/user-state/{section}/restore')
    async def restore(section:str, request:Request, if_match:str|None=Header(default=None), identity=Depends(authenticated)):
        section_exists(section)
        expected=expected_version(if_match)
        body=await json_body(request,1024)
        if set(body)!={'version'} or type(body['version']) is not int or body['version']<1:
            raise HTTPException(400)
        row=store.history(section, identity['user_id'], body['version'])
        if row is None:
            raise HTTPException(404)
        return commit(section,row['document'],expected,identity)
