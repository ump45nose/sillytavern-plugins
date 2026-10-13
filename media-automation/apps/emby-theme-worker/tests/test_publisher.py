"""Publication invariants shared by automatic upgrades and manual applications."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from emby_theme_worker.audio import AudioProcessor, sha256
from emby_theme_worker.config import Config
from emby_theme_worker.db import StateDB
from emby_theme_worker.models import Candidate, MediaItem
from emby_theme_worker.publisher import ThemePublisher
from emby_theme_worker.worker import Worker


@pytest.fixture
def publication(tmp_path):
    config = Config(database_path=str(tmp_path/'worker.db'), allowed_path=str(tmp_path), replacement_backup_path=str(tmp_path/'backups'))
    db = StateDB(config.database_path); db.initialize()
    media = tmp_path/'media'; media.mkdir()
    item = MediaItem('1', 'Movie', None, 2025, 'Movie', str(media))
    target = media/'theme.mp3'; target.write_bytes(b'old audio')
    expected = sha256(target)
    db.record_item(item, 'complete', provider='local_opening', output_path=str(target), output_sha256=expected)
    prepared = tmp_path/'prepared.mp3'; prepared.write_bytes(b'prepared audio')
    info = {'duration': 70, 'sha256': sha256(prepared)}
    audio = AudioProcessor(45, '192k', 30, {})
    emby = SimpleNamespace(refresh_and_verify=lambda *a, **kw: True)
    publisher = ThemePublisher(config, db, audio, emby)
    candidate = Candidate('youtube', 'Movie main theme', 'https://example.test/theme', score=90)
    def apply(manual=False):
        if manual:
            return publisher.apply_manual(item, prepared, info, expected_sha256=expected, adopt=False)
        replacement = db.start_replacement(item.id, candidate, expected, candidate.score)
        return publisher.replace_owned(item, prepared, info, candidate, expected_sha256=expected, replacement_id=replacement)
    return SimpleNamespace(**locals())


def latest(db):
    with db.connect() as conn:
        return dict(conn.execute('SELECT * FROM replacements ORDER BY id DESC LIMIT 1').fetchone())


@pytest.mark.parametrize('manual', [False, True])
def test_publish_success_keeps_protocol_state(publication, manual):
    p = publication
    result = p.apply(manual)
    assert result['sha256'] == p.info['sha256']
    assert p.target.read_bytes() == b'prepared audio'
    row = latest(p.db)
    assert row['status'] == 'complete' and row['old_provider'] == 'local_opening'
    assert row['old_sha256'] == p.expected and row['new_sha256'] == p.info['sha256']
    assert Path(row['backup_path']).read_bytes() == b'old audio'
    assert p.db.item_state(p.item.id)['source_provider'] == ('manual' if manual else 'youtube')
    assert bool(p.db.control(p.item.id)['locked']) is manual
    assert (p.media/'.theme.mp3.lock').exists()


@pytest.mark.parametrize('manual', [False, True])
def test_registration_failure_rolls_back_only_written_hash(publication, manual):
    p = publication
    p.emby.refresh_and_verify = lambda *a, **kw: False
    with pytest.raises(RuntimeError): p.apply(manual)
    assert p.target.read_bytes() == b'old audio'
    assert latest(p.db)['status'] == 'rolled_back'
    assert p.db.item_state(p.item.id)['output_sha256'] == p.expected


@pytest.mark.parametrize('manual', [False, True])
def test_external_edit_during_registration_is_never_rolled_back(publication, manual):
    p = publication
    def verify(*a, **kw):
        p.target.write_bytes(b'external edit')
        return True
    p.emby.refresh_and_verify = verify
    with pytest.raises(RuntimeError, match='theme changed'): p.apply(manual)
    assert p.target.read_bytes() == b'external edit'
    assert latest(p.db)['status'] == 'rollback_conflict'
    assert p.db.item_state(p.item.id)['output_sha256'] == p.expected


def test_preparation_lock_change_stops_auto_but_manual_remains_explicit(publication):
    p = publication
    p.db.set_control(p.item.id, locked=True)
    with pytest.raises(PermissionError, match='locked'): p.apply()
    assert p.target.read_bytes() == b'old audio'
    assert latest(p.db)['status'] == 'failed'
    assert p.apply(manual=True)['registered']


@pytest.mark.parametrize('changed', ['target', 'prepared'])
def test_preview_change_is_rejected_before_write(publication, changed):
    p = publication
    getattr(p, changed).write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'): p.apply(manual=True)
    assert p.target.read_bytes() == (b'changed' if changed == 'target' else b'old audio')
    with p.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM replacements').fetchone()[0] == 0


@pytest.mark.parametrize('manual', [False, True])
def test_db_commit_failure_restores_old_file(publication, monkeypatch, manual):
    p = publication
    def fail(*a, **kw): raise RuntimeError('database commit failed')
    monkeypatch.setattr(p.db, 'commit_application' if manual else 'complete_replacement', fail)
    with pytest.raises(RuntimeError, match='database'): p.apply(manual)
    assert p.target.read_bytes() == b'old audio'
    assert latest(p.db)['status'] == 'rolled_back'
    assert p.db.item_state(p.item.id)['output_sha256'] == p.expected


@pytest.mark.parametrize('manual', [False, True])
def test_interruption_leaves_existing_journal_recoverable(publication, manual):
    p = publication
    def interrupt(*a, **kw): raise KeyboardInterrupt()
    p.emby.refresh_and_verify = interrupt
    with pytest.raises(KeyboardInterrupt): p.apply(manual)
    assert latest(p.db)['status'] == 'applying'
    assert p.target.read_bytes() == b'prepared audio'
    worker = object.__new__(Worker); worker.db, worker.audio = p.db, p.audio
    worker._recover_replacements()
    assert p.target.read_bytes() == b'old audio'
    assert latest(p.db)['status'] == 'rolled_back'


@pytest.mark.parametrize('interrupt', [False, True])
def test_new_manual_file_remains_auditable_without_old_backup(publication, interrupt):
    p = publication
    p.target.unlink()
    def offline(*a, **kw):
        if interrupt: raise KeyboardInterrupt()
        raise ConnectionError('offline')
    p.emby.refresh_and_verify = offline
    with pytest.raises(KeyboardInterrupt if interrupt else ConnectionError):
        p.publisher.apply_manual(p.item, p.prepared, p.info, expected_sha256=None, adopt=False)
    assert p.target.read_bytes() == b'prepared audio'
    if interrupt:
        worker = object.__new__(Worker); worker.db, worker.audio = p.db, p.audio
        worker._recover_replacements()
        assert latest(p.db)['status'] == 'manual_review'
    else:
        assert latest(p.db)['status'] == 'pending_refresh'
        assert p.db.item_state(p.item.id)['output_sha256'] == p.info['sha256']
    assert not p.db.control(p.item.id)['locked']


def test_symlink_target_cannot_be_adopted(publication):
    p = publication
    p.target.unlink(); p.target.symlink_to(p.prepared)
    with pytest.raises(PermissionError): p.apply(manual=True)
    assert p.target.is_symlink() and p.prepared.read_bytes() == b'prepared audio'


def test_changed_staging_during_copy_rolls_back_actual_digest(publication, monkeypatch):
    p = publication
    atomic = p.audio.atomic_replace_owned
    def replace(prepared, *args):
        prepared.write_bytes(b'changed during copy')
        return atomic(prepared, *args)
    monkeypatch.setattr(p.audio, 'atomic_replace_owned', replace)
    with pytest.raises(ValueError, match='during publication'): p.apply()
    assert p.target.read_bytes() == b'old audio'
    assert latest(p.db)['status'] == 'rolled_back'


@pytest.mark.parametrize('manual', [False, True])
def test_error_after_atomic_rename_uses_write_ahead_hash(publication, monkeypatch, manual):
    p = publication
    atomic = p.audio.atomic_replace_owned
    def fail_after_rename(*args):
        atomic(*args)
        raise OSError('directory sync interrupted')
    monkeypatch.setattr(p.audio, 'atomic_replace_owned', fail_after_rename)
    with pytest.raises(OSError): p.apply(manual)
    assert p.target.read_bytes() == b'old audio'
    assert latest(p.db)['status'] == 'rolled_back'


def test_corrupt_backup_is_never_restored(publication):
    p = publication
    def verify(*a, **kw):
        backup = Path(latest(p.db)['backup_path'])
        backup.write_bytes(b'corrupt backup')
        return False
    p.emby.refresh_and_verify = verify
    with pytest.raises(RuntimeError, match='registration_failed'): p.apply()
    assert p.target.read_bytes() == b'prepared audio'
    assert latest(p.db)['status'] == 'rollback_conflict'


@pytest.mark.parametrize('finished_status', ['complete', 'rolled_back'])
@pytest.mark.parametrize('first_write', [False, True])
def test_recovery_rereads_journal_after_waiting_for_item_guard(publication, monkeypatch, finished_status, first_write):
    from contextlib import contextmanager
    p = publication
    if first_write:
        p.target.unlink()
    def interrupt(*a, **kw): raise KeyboardInterrupt()
    p.emby.refresh_and_verify = interrupt
    with pytest.raises(KeyboardInterrupt):
        p.publisher.apply_manual(p.item, p.prepared, p.info,
                                 expected_sha256=None if first_write else p.expected, adopt=False)
    row = latest(p.db)
    original_guard = p.db.item_guard
    @contextmanager
    def finish_before_lock(item_id):
        with original_guard(item_id):
            p.db.finish_replacement(row['id'], finished_status, new_sha256=p.info['sha256'], backup_path=row['backup_path'])
            yield
    monkeypatch.setattr(p.db, 'item_guard', finish_before_lock)
    worker = object.__new__(Worker); worker.db, worker.audio = p.db, p.audio
    worker._recover_replacements()
    assert p.target.read_bytes() == b'prepared audio'
    assert latest(p.db)['status'] == finished_status


def test_recovery_uses_refreshed_hash_fields(publication, monkeypatch):
    from contextlib import contextmanager
    p = publication
    def interrupt(*a, **kw): raise KeyboardInterrupt()
    p.emby.refresh_and_verify = interrupt
    with pytest.raises(KeyboardInterrupt): p.apply()
    row = latest(p.db)
    original_guard = p.db.item_guard
    @contextmanager
    def update_before_lock(item_id):
        with original_guard(item_id):
            p.target.write_bytes(b'updated intended audio')
            p.db.prepare_replacement(row['id'], sha256(p.target), row['backup_path'], str(p.target))
            yield
    monkeypatch.setattr(p.db, 'item_guard', update_before_lock)
    worker = object.__new__(Worker); worker.db, worker.audio = p.db, p.audio
    worker._recover_replacements()
    assert p.target.read_bytes() == b'old audio'
    assert latest(p.db)['status'] == 'rolled_back'
