"""Authenticated browser API. MoviePilot credentials never reach the browser."""
import argparse
from contextlib import asynccontextmanager
import hashlib
import hmac
from pathlib import Path
import time

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from media_capabilities.acquisition.client import BridgeClient, ConnectionSettings, read_secret


def create_app(settings, bridge=None):
    if not settings.access_token_file:
        raise ValueError("网页需要 access_token_file")
    read_secret(settings.access_token_file)
    bridge = bridge or BridgeClient(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        bridge.close()

    app = FastAPI(title="Media Search", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.public_hosts))

    def token():
        return read_secret(settings.access_token_file)

    def signature(value):
        return hmac.new(token().encode(), value.encode(), hashlib.sha256).hexdigest()

    def authenticate(request: Request):
        authorization = request.headers.get('authorization', '')
        if authorization.startswith('Bearer ') and hmac.compare_digest(authorization[7:], token()):
            return
        value = request.cookies.get('media_session', '')
        try:
            expires, signed = value.split('.', 1)
            valid = int(expires) > time.time() and hmac.compare_digest(signed, signature(expires))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise HTTPException(401, "需要登录")
        if request.method not in ('GET', 'HEAD'):
            # SameSite cookies plus an explicit same-origin header protect cookie writes.
            if request.headers.get('x-media-request') != '1':
                raise HTTPException(403, "请求缺少同源标识")
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                raise HTTPException(403, "请求来源不匹配")

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.post('/api/session')
    def login(payload: dict, response: Response):
        value = payload.get('token')
        if not isinstance(value, str) or not hmac.compare_digest(value, token()):
            raise HTTPException(401, "令牌不正确")
        expires = str(int(time.time()) + 12 * 3600)
        response.set_cookie('media_session', expires + '.' + signature(expires),
            httponly=True, secure=settings.secure_cookie, samesite='strict', max_age=12*3600)
        return {'status': 'ok'}

    @app.get('/api/session', dependencies=[Depends(authenticate)])
    def session():
        return {'status': 'ok'}

    @app.delete('/api/session', dependencies=[Depends(authenticate)])
    def logout(response: Response):
        response.delete_cookie('media_session')
        return {'status': 'ok'}

    @app.post('/api/search', dependencies=[Depends(authenticate)])
    def search(payload: dict):
        try:
            return bridge.start_search(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get('/api/search/{session_id}', dependencies=[Depends(authenticate)])
    def search_status(session_id: str):
        return bridge.search_status(session_id)

    @app.post('/api/search/{session_id}/more', dependencies=[Depends(authenticate)])
    def more(session_id: str, payload: dict):
        return bridge.more(session_id, payload.get('source_id', ''))

    @app.post('/api/download', dependencies=[Depends(authenticate)])
    def download(payload: dict):
        try:
            return bridge.download(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get('/api/download/{task_id}', dependencies=[Depends(authenticate)])
    def status(task_id: str):
        return bridge.status(task_id)

    static = Path(__file__).with_name('static')
    if (static / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')

    @app.get('/')
    def index():
        if not (static / 'index.html').is_file():
            raise HTTPException(503, "请先构建查询页面")
        return FileResponse(static / 'index.html')

    return app


def main():
    parser = argparse.ArgumentParser(description='独立聚合媒体查询网页')
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    settings = ConnectionSettings.load(args.config)
    import uvicorn
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
