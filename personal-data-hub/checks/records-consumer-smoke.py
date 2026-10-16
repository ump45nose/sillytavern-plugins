"""Real HTTP client → SQLite-backed service → report and freshness consumers."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import time

import uvicorn
from mcp_platform import RuntimeConfig
from personal_records.api import create_app
from personal_records.client import RecordsClient
from personal_records.settings import Settings
from personal_data_hub.daily_push import DailyPushData

with TemporaryDirectory() as temp:
    root = Path(temp)
    token = root/'read.token'; token.write_text('reader')
    settings = Settings(str(root/'records.sqlite'), RuntimeConfig(name='consumer-smoke', development_no_auth=True), 'reader', 'writer', 'health', 'accounting')
    app = create_app(settings)
    service = app.state.service
    service.store.ingest('health', {'steps': [{'count': 200, 'start_time': '2026-10-15T16:00:00Z', 'end_time': '2026-10-16T16:00:00Z'}]})
    for i in range(205):
        service.create_bill({'occurred_at': '2026-10-16T01:00:00Z', 'type': 'expense', 'amount': '0.01', 'currency': 'CNY'})
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); worker.start()
    try:
        deadline = time.monotonic()+10
        while not server.started:
            if time.monotonic() > deadline: raise RuntimeError('test server did not start')
            time.sleep(.01)
        reader = RecordsClient(f'http://127.0.0.1:{sock.getsockname()[1]}', str(token))
        snapshot = DailyPushData(None, records_client=reader).snapshot('2026-10-16', chats=[])
        assert snapshot['health']['metrics']['steps']['total'] == 200
        assert snapshot['finance']['count'] == 205 and snapshot['finance']['totals'][0]['amount'] == '2.05'
        assert len(snapshot['finance']['bills']) == 205
        path = Path(__file__).resolve().parents[2]/'nas-cron-jobs/hermes/health-data-freshness.py'
        spec = importlib.util.spec_from_file_location('health_freshness', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        assert module.inspect(reader, datetime.now(timezone.utc), 3)[0] == 'healthy'
        assert module.inspect(reader, datetime(2100, 1, 1, tzinfo=timezone.utc), 3)[1] == 'stale'
    finally:
        server.should_exit = True; worker.join(timeout=10); sock.close()
        assert not worker.is_alive()
print('records_consumer_smoke_ok: HTTP summaries, multi-page bills, source freshness')
