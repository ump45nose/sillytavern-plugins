"""Explicit, restart-safe migration of the former Telegram directory layout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import zipfile

from .adapters import TelegramAdapter
from .common import atomic_write, SyncError
from .config import telegram_accounts, start_timestamp
from .layout import paths
from .journal import append_entry


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relayout(engine):
    cfg, store = engine.cfg, engine.store
    # Refresh only Saved Messages, plus the names needed by their filenames.
    for profile in telegram_accounts(cfg):
        if not profile['enabled']:
            continue
        start = start_timestamp(profile['start_date'], cfg['timezone'])
        if start is None:
            continue
        adapter = TelegramAdapter({**cfg, 'telegram': profile})
        records, cursor = adapter.scan('telegram', start=start)
        previous = store.setting('tg_identity:' + profile['account'])
        if previous and previous != adapter.account_id:
            raise SyncError('telegram_account_changed')
        store.source('telegram', profile['account'])
        store.ingest('telegram', profile['account'], records, cursor=cursor, start_date=str(profile['start_date']))

    backup = Path(cfg['state_dir']) / 'layout-backups' / str(time.time_ns())
    backup.mkdir(parents=True, mode=0o700)
    migrated = text_count = empty_count = fallback_count = 0
    with (backup / 'manifest.jsonl').open('a') as manifest, zipfile.ZipFile(backup / 'old-texts.zip', 'w', zipfile.ZIP_DEFLATED) as texts:
        for item in store.db.execute("SELECT * FROM items WHERE platform='telegram'").fetchall():
            old = Path(cfg['download_dir']) / 'telegram' / item['account'] / item['item_id']
            naming = json.loads(item['locator']).get('naming', {})
            if not naming or naming.get('group', '').startswith('来源群组-'):
                fallback_count += 1
            for asset in store.assets(item):
                if asset['status'] != 'done':
                    continue
                source, target = old / asset['filename'], paths(cfg, item, asset)
                target.parent.mkdir(parents=True, exist_ok=True)
                if source == target:
                    continue
                if not source.exists():
                    if target.is_file() and target.stat().st_size == asset['size']:
                        continue
                    raise SyncError('migration_source_missing')
                checksum = digest(source)
                if source.stat().st_size != asset['size']:
                    raise SyncError('migration_size_mismatch')
                if target.exists():
                    if digest(target) != checksum:
                        raise SyncError('migration_target_conflict')
                else:
                    fd, name = tempfile.mkstemp(prefix='.migrate-', dir=target.parent)
                    temp = Path(name)
                    try:
                        with os.fdopen(fd, 'wb') as output, source.open('rb') as stream:
                            shutil.copyfileobj(stream, output)
                            output.flush()
                            os.fsync(output.fileno())
                        if digest(temp) != checksum:
                            raise SyncError('migration_checksum_mismatch')
                        os.replace(temp, target)
                    finally:
                        temp.unlink(missing_ok=True)
                manifest.write(json.dumps({'old': str(source), 'new': str(target), 'sha256': checksum}, ensure_ascii=False) + '\n')
                manifest.flush()
                os.fsync(manifest.fileno())
                source.unlink()
                migrated += 1
            text = old / 'text.txt'
            if text.is_file():
                content = text.read_bytes()
                texts.writestr(item['account'] + '/' + item['item_id'] + '/text.txt', content)
                if content.strip():
                    text_count += 1
                else:
                    empty_count += 1
                # Text originals remain until the zip has been finalized below.
            try:
                (old / '.partial').rmdir()
            except OSError:
                pass
            assets = store.assets(item)
            if all(a['status'] == 'done' for a in assets):
                append_entry(cfg, item, assets)
                store.text_done(item)
    with zipfile.ZipFile(backup / 'old-texts.zip') as archive:
        for name in archive.namelist():
            old = Path(cfg['download_dir']) / 'telegram' / name
            if old.exists() and old.read_bytes() == archive.read(name):
                old.unlink()
                try:
                    old.parent.rmdir()
                except OSError:
                    pass
    return {'media_moved': migrated, 'nonempty_texts_archived': text_count,
            'empty_texts_archived': empty_count, 'metadata_fallback_items': fallback_count,
            'manifest': str(backup / 'manifest.jsonl')}
