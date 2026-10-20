"""迁移装配必须保留显式启用的聊天事件，仍关闭未授权的提醒和复盘。"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from personal_crm.app.settings import Settings
from personal_data_hub.server import create_app

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    configuration = {'database_url': 'sqlite:///' + str(root / 'archive.sqlite'),
                     'asset_root': str(root / 'assets'), 'sources': {}}
    for enabled in (False, True):
        settings = Settings(chat_events_enabled=enabled, reminder_scheduler_enabled=True,
                            daily_review_events_enabled=True)
        observed = []
        def assemble(runtime, repository, hub_store):
            observed.append(runtime)
            app = FastAPI()
            app.mount('/', FastAPI())
            return app
        with patch('personal_crm.app.server.create_app', assemble):
            create_app(configuration, crm_settings=settings)
        assert observed[0].chat_events_enabled is enabled
        assert not observed[0].reminder_scheduler_enabled
        assert not observed[0].daily_review_events_enabled
print('event_migration_smoke_ok explicit_chat_setting_preserved')
