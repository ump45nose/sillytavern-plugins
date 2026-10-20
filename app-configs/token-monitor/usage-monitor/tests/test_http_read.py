import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from usage_monitor_mcp.config import Settings
from usage_monitor_mcp.http_read import attach_read_routes, network_snapshot
from test_usage import traffic_database


class Routes:
    def __init__(self): self.routes = []
    def custom_route(self, path, methods):
        def decorate(fn):
            self.routes.append(Route(path, fn, methods=methods))
            return fn
        return decorate


class ReadHTTPTests(unittest.TestCase):
    def test_auth_readonly_hourly_and_no_business_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'traffic.sqlite3'
            traffic_database(path)
            token = root / 'read.token'
            token.write_text('SENTINEL-HTTP-READ')
            settings = Settings(traffic_db=path, http_read_token_file=str(token))
            before = path.read_bytes()
            now = datetime.fromisoformat('2026-10-05T12:00:00+08:00')
            value = network_snapshot(settings, now)
            self.assertEqual(len(value['data']['hourly']), 24)
            self.assertIsNone(value['data']['pools'])
            self.assertEqual(value['data']['today'], {'up_bytes': 20, 'down_bytes': 30})
            self.assertEqual(value['data']['month_bytes'], 1850)
            self.assertEqual(value['data']['hourly'][0]['bytes'], 50)
            self.assertIsNone(value['data']['hourly'][1]['bytes'])
            self.assertIsNone(value['data']['hourly'][23]['bytes'])
            self.assertEqual(before, path.read_bytes())
            routes = Routes()
            attach_read_routes(routes, settings)
            with TestClient(Starlette(routes=routes.routes)) as client:
                self.assertEqual(client.get('/api/v1/net').status_code, 401)
                headers = {'Authorization': 'Bearer SENTINEL-HTTP-READ'}
                self.assertEqual(client.get('/api/v1/net', headers=headers).status_code, 200)
                self.assertEqual(client.post('/api/v1/net', headers=headers).status_code, 405)
                with patch('usage_monitor_mcp.http_read._read_stats', return_value=({'limits': {'providers': []}}, 'ok')):
                    response = client.get('/api/v1/limits', headers=headers)
                    self.assertEqual(response.json()['limits'], [])
                    self.assertNotIn('SENTINEL-HTTP-READ', response.text)
                with patch('usage_monitor_mcp.http_read._read_stats', return_value=(None, 'SENTINEL-HTTP-READ')):
                    response = client.get('/api/v1/limits', headers=headers)
                    self.assertEqual(response.status_code, 502)
                    self.assertNotIn('SENTINEL-HTTP-READ', response.text)

    def test_missing_token_is_not_anonymous_access(self):
        routes = Routes()
        attach_read_routes(routes, Settings())
        with TestClient(Starlette(routes=routes.routes)) as client:
            self.assertEqual(client.get('/api/v1/net').status_code, 503)
