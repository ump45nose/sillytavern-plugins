"""Exercise the MoviePilot proxy with a host stand-in, without importing MoviePilot."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx
import pytest


def proxy_types(monkeypatch, client_type, stream_type=None):
    path = Path(__file__).parents[1]/'moviepilot/plugins.v2/themestudio/__init__.py'
    tree = ast.parse(path.read_text())
    studio = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ThemeStudio')
    method = next(n for n in studio.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'proxy')
    audio = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WorkerAudioResponse')
    module = ast.Module(body=[audio, method], type_ignores=[])
    class Stream:
        def __init__(self, iterator, **kw): self.body_iterator, self.options = iterator, kw
        async def __call__(self, scope, receive, send):
            await send({'type': 'http.response.start'})
            async for chunk in self.body_iterator:
                await send({'type': 'http.response.body', 'body': chunk})
    env = {'re': __import__('re'), 'httpx': httpx, 'Request': object, 'Depends': lambda x: None,
           'get_current_active_superuser_async': None, 'StreamingResponse': stream_type or Stream,
           'CancelScope': anyio.CancelScope, 'HTTPException': RuntimeError}
    monkeypatch.setattr(httpx, 'AsyncClient', client_type)
    exec(compile(module, str(path), 'exec'), env)
    return env['proxy']


class Request:
    method = 'GET'
    async def stream(self):
        if False: yield b''


@pytest.mark.parametrize('disconnect', [None, 'headers', 'body'])
@pytest.mark.parametrize('close_error', [False, True])
def test_proxy_closes_resources_on_every_response_exit(monkeypatch, disconnect, close_error):
    closed, messages = [], []
    class Upstream:
        status_code = 200
        headers = {'content-type': 'audio/mpeg', 'content-length': '6'}
        async def aiter_bytes(self, size):
            assert size == 256*1024
            yield b'abc'
            yield b'def'
        async def aclose(self):
            closed.append('response')
            if close_error: raise RuntimeError('close failed')
        @property
        def content(self): raise AssertionError('audio proxy must not buffer content')
    class Client:
        def __init__(self, **kw): pass
        def build_request(self, *args): return args
        async def send(self, request, stream):
            assert stream is True
            return Upstream()
        async def aclose(self): closed.append('client')
    proxy = proxy_types(monkeypatch, Client)
    async def run():
        result = await proxy(SimpleNamespace(_enabled=True), 'audio/'+'a'*32, Request())
        assert result.options['headers']['Content-Length'] == '6'
        async def send(message):
            if disconnect == 'headers' or disconnect == 'body' and message['type'] == 'http.response.body':
                raise OSError('disconnected')
            messages.append(message)
        if disconnect or close_error:
            with pytest.raises((OSError, RuntimeError)):
                await result({}, None, send)
        else:
            await result({}, None, send)
            assert b''.join(m.get('body', b'') for m in messages) == b'abcdef'
        assert closed == ['response', 'client']
    asyncio.run(run())


def test_proxy_closes_client_if_stream_open_fails(monkeypatch):
    closed = []
    class Client:
        def __init__(self, **kw): pass
        def build_request(self, *args): return args
        async def send(self, *args, **kw): raise httpx.ReadTimeout('offline')
        async def aclose(self): closed.append('client')
    proxy = proxy_types(monkeypatch, Client)
    with pytest.raises(RuntimeError):
        asyncio.run(proxy(SimpleNamespace(_enabled=True), 'audio/'+'a'*32, Request()))
    assert closed == ['client']
