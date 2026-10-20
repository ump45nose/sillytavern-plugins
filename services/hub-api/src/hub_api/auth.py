"""Authelia code flow, browser binding and device-side PKCE. No provider token persists."""
import asyncio
import base64
import hashlib
import hmac
import re
import secrets
from collections import OrderedDict
from urllib.parse import urlencode, urlsplit

import httpx
from authlib.oidc.core import CodeIDToken
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from joserfc import jwt
from joserfc.errors import InvalidKeyIdError
from joserfc.jwk import KeySet

from .configuration import json_body


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode()


def redirect_allowed(value):
    if value == 'personalhub://auth':
        return True
    match = re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})/callback', value)
    return bool(match and int(match[1]) <= 65535)


class OIDC:
    def __init__(self,settings,store,client,now):
        self.settings,self.store,self.client,self.now=settings,store,client,now
        self.metadata=None;self.keys=None;self.fetched=0;self.lock=asyncio.Lock()

    @property
    def callback(self): return self.settings.public_url.rstrip('/')+'/auth/callback'

    def enabled(self):
        return bool(self.settings.oidc_issuer and self.settings.oidc_client_secret and self.settings.allowed_subjects)

    async def discovery(self, force=False):
        async with self.lock:
            if not force and self.metadata and self.now().timestamp()-self.fetched<300: return self.metadata,self.keys
            issuer=self.settings.oidc_issuer.rstrip('/')
            response=await self.client.get(issuer+'/.well-known/openid-configuration')
            response.raise_for_status();metadata=response.json()
            if metadata['issuer']!=issuer: raise ValueError('invalid issuer')
            origin=urlsplit(issuer)
            for field in ('authorization_endpoint','token_endpoint','jwks_uri'):
                parsed=urlsplit(metadata[field])
                if parsed.scheme!='https' or parsed.hostname!=origin.hostname or parsed.username or parsed.password or parsed.fragment:
                    raise ValueError('invalid discovery endpoint')
            response=await self.client.get(metadata['jwks_uri']);response.raise_for_status()
            keys=KeySet.import_key_set(response.json())
            self.metadata,self.keys,self.fetched=metadata,keys,self.now().timestamp()
            return metadata,keys

    def validate(self, raw, keys, nonce):
        token=jwt.decode(raw['id_token'],key=keys,algorithms=['RS256'])
        claims=CodeIDToken(token.claims,token.header,options={
            'iss':{'essential':True,'value':self.settings.oidc_issuer.rstrip('/')},
            'aud':{'essential':True,'value':self.settings.oidc_client_id}},
            params={'nonce':nonce,'client_id':self.settings.oidc_client_id,'access_token':raw.get('access_token')})
        claims.validate(now=int(self.now().timestamp()),leeway=30)
        if claims['sub'] not in self.settings.allowed_subjects: raise PermissionError('subject not allowed')


def register(app,settings,store,client,now):
    oidc=OIDC(settings,store,client,now)
    app.state.oidc=oidc
    limits=OrderedDict()

    @app.middleware('http')
    async def auth_headers(request,call_next):
        if not request.url.path.startswith('/auth/'): return await call_next(request)
        stamp=now().timestamp();key=request.client.host if request.client else 'unknown'
        period=int(stamp//60);last,count=limits.pop(key,(period,0));count=count+1 if last==period else 1
        limits[key]=(period,count)
        if len(limits)>1024: limits.popitem(last=False)
        if count>30:
            response=app.router.default_response_class({'error':{'code':'bad_request','message':'rate_limited'}},status_code=429)
        else: response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['Pragma']='no-cache'
        response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.get('/auth/start')
    async def start(request:Request,device_name:str,redirect_uri:str,code_challenge:str,state:str):
        if not oidc.enabled(): raise HTTPException(503)
        if (not 1<=len(device_name.strip())<=200 or not 1<=len(state)<=1024 or not redirect_allowed(redirect_uri)
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}',code_challenge)):
            raise HTTPException(400)
        try: metadata,_=await oidc.discovery()
        except Exception: raise HTTPException(502) from None
        server_state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32)
        browser=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(32)
        # Temporary protocol state expires after ten minutes; only IDs/codes are hashed.
        payload={'device_name':device_name.strip(),'redirect_uri':redirect_uri,'client_state':state,'challenge':code_challenge,
                 'nonce':nonce,'verifier':verifier,'browser_hash':store.digest(browser)}
        if not store.save_login('oidc',server_state,payload,now().timestamp()+600,now().timestamp()): raise HTTPException(429)
        query={'client_id':settings.oidc_client_id,'redirect_uri':oidc.callback,'response_type':'code','scope':'openid profile',
               'state':server_state,'nonce':nonce,'code_challenge':challenge(verifier),'code_challenge_method':'S256'}
        response=RedirectResponse(metadata['authorization_endpoint']+'?'+urlencode(query),status_code=302)
        # One cookie per provider-state supports overlapping device login tabs.
        response.set_cookie('hub_login_'+server_state,browser,max_age=600,secure=True,httponly=True,samesite='lax',path='/auth/callback')
        return response

    @app.get('/auth/callback')
    async def callback(request:Request,state:str,code:str|None=None,error:str|None=None):
        if not oidc.enabled(): raise HTTPException(503)
        if not 1<=len(state)<=128 or not code or len(code)>4096 or error: raise HTTPException(400)
        payload=store.consume_login('oidc',state,now().timestamp())
        browser=request.cookies.get('hub_login_'+state,'')
        if not payload or not hmac.compare_digest(payload['browser_hash'],store.digest(browser)): raise HTTPException(400)
        try:
            metadata,keys=await oidc.discovery()
            response=await client.post(metadata['token_endpoint'],auth=httpx.BasicAuth(settings.oidc_client_id,settings.oidc_client_secret.get_secret_value()),
                data={'grant_type':'authorization_code','code':code,'redirect_uri':oidc.callback,'code_verifier':payload['verifier']})
            response.raise_for_status();raw=response.json()
            try:
                oidc.validate(raw,keys,payload['nonce'])
            except InvalidKeyIdError:
                _,keys=await oidc.discovery(force=True)
                oidc.validate(raw,keys,payload['nonce'])
        except PermissionError: raise HTTPException(403) from None
        except Exception: raise HTTPException(400) from None
        ticket=secrets.token_urlsafe(32)
        if not store.save_login('exchange',ticket,{'device_name':payload['device_name'],'challenge':payload['challenge']},now().timestamp()+60,now().timestamp()): raise HTTPException(429)
        response=RedirectResponse(payload['redirect_uri']+'?'+urlencode({'code':ticket,'state':payload['client_state']}),status_code=302)
        response.delete_cookie('hub_login_'+state,path='/auth/callback',secure=True,httponly=True,samesite='lax')
        return response

    @app.post('/auth/token')
    async def token(request:Request):
        if not oidc.enabled(): raise HTTPException(503)
        body=await json_body(request,4096)
        if set(body)!={'code','code_verifier'} or not isinstance(body['code'],str) or not 1<=len(body['code'])<=128 or not isinstance(body['code_verifier'],str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}',body['code_verifier']): raise HTTPException(400)
        pair=store.exchange_device(body['code'],challenge(body['code_verifier']),now().isoformat(),now().timestamp())
        if pair is None: raise HTTPException(401)
        return pair
