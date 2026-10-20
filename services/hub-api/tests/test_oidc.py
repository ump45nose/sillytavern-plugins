from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs,urlsplit
import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr
from hub_api.app import create_app
from hub_api.auth import challenge,redirect_allowed
from test_records import NOW

@pytest.fixture
def oidc(settings):
    settings.dev_token=None
    settings.oidc_issuer='https://idp.test'
    settings.public_url='https://hub.test'
    settings.oidc_client_secret=SecretStr('SENTINEL-OIDC-CLIENT')
    settings.allowed_subjects=['owner-subject']
    key=RSAKey.generate_key(2048,parameters={'kid':'test'})
    state={'claims':{},'clock':NOW,'nonce':None,'provider_calls':[]}
    def provider(request):
        state['provider_calls'].append(request)
        if request.url.path=='/.well-known/openid-configuration':
            return httpx.Response(200,json={'issuer':'https://idp.test','authorization_endpoint':'https://idp.test/authorize','token_endpoint':'https://idp.test/token','jwks_uri':'https://idp.test/keys'})
        if request.url.path=='/keys':return httpx.Response(200,json={'keys':[state.get('published_key',key).as_dict(private=False)]})
        assert request.url.path=='/token' and request.method=='POST'
        body=parse_qs(request.content.decode())
        assert body['redirect_uri']==['https://hub.test/auth/callback']
        assert challenge(body['code_verifier'][0])==state['provider_challenge']
        claims={'iss':'https://idp.test','sub':'owner-subject','aud':'personal-hub','iat':int(state['clock'].timestamp()),'exp':int(state['clock'].timestamp())+300,'nonce':state['nonce'],**state['claims']}
        return httpx.Response(200,json={'access_token':'PROVIDER-ACCESS-TOKEN','id_token':jwt.encode({'alg':'RS256','kid':state.get('signing_key',key).kid},claims,state.get('signing_key',key))})
    app=create_app(settings,adapters=[],now=lambda:state['clock'],transport=httpx.MockTransport(provider))
    with TestClient(app,base_url='https://hub.test') as client:yield client,app,state,settings

def start(oidc,redirect='http://127.0.0.1:49152/callback'):
    client,app,state,settings=oidc;verifier='v'*43
    r=client.get('/auth/start',params={'device_name':'Mac','redirect_uri':redirect,'code_challenge':challenge(verifier),'state':'client-state'},follow_redirects=False)
    assert r.status_code==302 and r.headers['cache-control']=='no-store'
    params=parse_qs(urlsplit(r.headers['location']).query)
    state['nonce']=params['nonce'][0];state['provider_challenge']=params['code_challenge'][0]
    return params['state'][0],verifier

def callback(oidc,state):return oidc[0].get('/auth/callback',params={'state':state,'code':'provider-code'},follow_redirects=False)

def test_oidc_flow_replay_hash_revocation_and_concurrent_exchange(oidc,caplog):
    client,app,state,settings=oidc
    server_state,verifier=start(oidc);r=callback(oidc,server_state)
    assert r.status_code==302
    params=parse_qs(urlsplit(r.headers['location']).query)
    assert params['state']==['client-state'];ticket=params['code'][0]
    assert callback(oidc,server_state).status_code==400
    def exchange(_):return client.post('/auth/token',json={'code':ticket,'code_verifier':verifier})
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(exchange,[1,2]))
    assert sorted(r.status_code for r in responses)==[200,401]
    pair=next(r.json() for r in responses if r.status_code==200)
    assert len(pair['token'])==43
    h={'Authorization':'Bearer '+pair['token']}
    assert client.get('/api/v1/status',headers=h).status_code==200
    with app.state.store.connection() as db:
        rows=str([tuple(r) for r in db.execute('SELECT * FROM devices')])
        pending=db.execute('SELECT count(*) FROM login_pending').fetchone()[0]
    assert pair['token'] not in rows and pending==0
    assert client.delete('/api/v1/devices/'+pair['device_id'],headers=h).status_code==204
    assert client.get('/api/v1/status',headers=h).status_code==401
    assert settings.oidc_client_secret.get_secret_value() not in caplog.text+str(rows)
    assert 'PROVIDER-ACCESS-TOKEN' not in caplog.text+str(rows)

@pytest.mark.parametrize('claims',[{'nonce':'wrong'},{'iss':'https://evil.test'},{'aud':'wrong'},{'sub':'intruder'},{'exp':int((NOW-timedelta(minutes=1)).timestamp())},{'iat':int((NOW+timedelta(minutes=5)).timestamp())}])
def test_oidc_rejects_invalid_claims(oidc,claims):
    server_state,_=start(oidc);oidc[2]['claims']=claims
    assert callback(oidc,server_state).status_code in (400,403)
    assert oidc[1].state.store.devices()==[]

def test_browser_pkce_expiry_redirects_and_rate_limit(oidc):
    client,app,state,_=oidc
    server_state,verifier=start(oidc);client.cookies.clear()
    assert callback(oidc,server_state).status_code==400
    server_state,verifier=start(oidc,'personalhub://auth')
    ticket=parse_qs(urlsplit(callback(oidc,server_state).headers['location']).query)['code'][0]
    assert client.post('/auth/token',json={'code':ticket,'code_verifier':'wrong'*10}).status_code==401
    assert client.post('/auth/token',json={'code':ticket,'code_verifier':verifier}).status_code==401
    server_state,verifier=start(oidc)
    ticket=parse_qs(urlsplit(callback(oidc,server_state).headers['location']).query)['code'][0]
    state['clock']+=timedelta(seconds=61)
    assert client.post('/auth/token',json={'code':ticket,'code_verifier':verifier}).status_code==401
    server_state,_=start(oidc);state['clock']+=timedelta(minutes=11)
    assert callback(oidc,server_state).status_code==400
    for value in ['http://localhost:1/callback','http://127.0.0.1/callback','http://127.0.0.1:1/other','http://user@127.0.0.1:1/callback','http://127.0.0.1:1/callback?x=y','personalhub://auth/','https://evil.test/callback']:assert not redirect_allowed(value)
    responses=[client.post('/auth/token',json={}) for _ in range(31)]
    assert responses[-1].status_code==429 and responses[-1].headers['cache-control']=='no-store'


def test_key_rotation_and_invalid_signature(oidc):
    client,app,state,_=oidc
    server_state,_=start(oidc)
    key=RSAKey.generate_key(2048,parameters={'kid':'rotated'})
    state['signing_key']=key;state['published_key']=key
    assert callback(oidc,server_state).status_code==302
    assert len([r for r in state['provider_calls'] if r.url.path=='/keys'])==2
    server_state,_=start(oidc)
    state['signing_key']=RSAKey.generate_key(2048,parameters={'kid':'rotated'})
    assert callback(oidc,server_state).status_code==400
    assert app.state.store.devices()==[]


def test_development_token_cannot_coexist_with_oidc(settings):
    settings.oidc_issuer='https://idp.test'
    with pytest.raises(ValueError):create_app(settings)
