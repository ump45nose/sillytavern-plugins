"""Transport DTOs and credential handling shared by the independent entrypoints."""
from dataclasses import dataclass
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid

import httpx

from .models import AcquisitionRequest


def read_secret(path):
    file = Path(path)
    if not file.is_file() or file.stat().st_mode & 0o077:
        raise ValueError("令牌需要普通文件且权限为 0600")
    value = file.read_text().strip()
    if not value or '\n' in value or '\r' in value:
        raise ValueError("令牌文件为空或包含换行")
    return value


@dataclass(frozen=True)
class ConnectionSettings:
    moviepilot_url: str
    moviepilot_token_file: str
    access_token_file: str | None = None
    host: str = "127.0.0.1"
    port: int = 8090
    public_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    secure_cookie: bool = False

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        if 'public_hosts' in data:
            data['public_hosts'] = tuple(data['public_hosts'])
        settings = cls(**data)
        parsed = urlsplit(settings.moviepilot_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username \
                or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("moviepilot_url 必须是无凭据的 HTTP(S) 地址")
        return settings


class BridgeClient:
    def __init__(self, settings: ConnectionSettings, transport=None):
        self.settings = settings
        self.http = httpx.Client(timeout=httpx.Timeout(125, connect=10), transport=transport,
                                 follow_redirects=False)

    def _call(self, operation, method='GET', payload=None, **params):
        url = self.settings.moviepilot_url.rstrip('/') + '/api/v1/plugin/MediaCapabilities/acquisition_' + operation
        try:
            token = read_secret(self.settings.moviepilot_token_file)
        except (OSError, ValueError):
            return {'status': 'unavailable', 'reason': '请检查服务端令牌文件及权限'}
        def uncertain():
            return {'status': 'pending', 'task_id': payload['request_id'],
                    'reason': '宿主提交响应不明，请用任务 ID 查询，勿重新提交'}
        try:
            response = self.http.request(method, url, params=params, json=payload,
                headers={'Authorization': 'Bearer ' + token})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if operation == 'download' and exc.response.status_code >= 500:
                return uncertain()
            return {'status': 'unavailable', 'reason': '宿主连接或鉴权失败，请检查服务端配置'}
        except (httpx.RequestError, ValueError):
            if operation == 'download':
                return uncertain()
            return {'status': 'unavailable', 'reason': '宿主查询响应不可用'}

    def start_search(self, payload):
        AcquisitionRequest.parse(payload)
        return self._call('search', 'POST', payload)

    def search_status(self, session_id):
        return self._call('search_status', session_id=session_id)

    def more(self, session_id, source_id):
        return self._call('more', 'POST', {'session_id': session_id, 'source_id': source_id})

    def search(self, payload, wait=20):
        result = self.start_search(payload)
        deadline = time.monotonic() + wait
        while result.get('status') == 'pending' and not result.get('candidates') and time.monotonic() < deadline:
            time.sleep(0.2)
            result = self.search_status(result['session_id'])
        return result

    def download(self, payload):
        AcquisitionRequest.parse(payload)
        payload = {**payload, 'request_id': payload.get('request_id') or uuid.uuid4().hex}
        return self._call('download', 'POST', payload)

    def status(self, task_id):
        return self._call('status', task_id=task_id)

    def close(self):
        self.http.close()
