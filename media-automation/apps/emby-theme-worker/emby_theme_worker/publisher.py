"""Theme-specific publication shared by automatic tasks and Studio applications.

Audio preparation stays with the caller. This boundary owns the guarded takeover,
write-ahead replacement record, Emby hash verification and conditional rollback.
The existing SQLite rows, backup layout and AudioProcessor atomic operations stay
in place, so interrupted work remains recoverable without a state migration.
"""
from __future__ import annotations

from pathlib import Path

from .audio import sha256
from .models import Candidate, MediaItem
from .security import contained


class ThemePublisher:
    def __init__(self, config, db, audio, emby):
        self.config, self.db, self.audio, self.emby = config, db, audio, emby

    def _target(self, item: MediaItem) -> Path:
        target = item.directory / 'theme.mp3'
        if target.is_symlink() or not contained(str(target), self.config.allowed_path):
            raise PermissionError('theme path is outside managed files')
        return target

    def publish_new(self, item: MediaItem, prepared: Path, provider: str, transport: str, score: int, info: dict) -> dict:
        """Automatic missing-theme publication; never adopt an existing file."""
        with self.db.item_guard(item.id):
            if self.db.control(item.id)['locked']:
                raise PermissionError('theme is locked by user')
            self._target(item)
            if self.emby.theme_visible(item.id):
                self.db.record_item(item, 'skipped_existing')
                return {'item_id': item.id, 'status': 'skipped_existing'}
            created, target, digest = self.audio.atomic_commit(prepared, item.directory)
            if not created:
                self.db.record_item(item, 'skipped_existing', output_path=str(target), output_sha256=digest)
                return {'item_id': item.id, 'status': 'skipped_existing'}
            # Persist ownership before calling Emby: a new unregistered file is
            # retained for a later scan rather than deleted or called unrelated.
            self.db.record_item(item, 'pending_refresh', provider=provider, score=score, output_path=str(target), output_sha256=digest)
            try:
                registered = self.emby.refresh_and_verify(item.id, expected_path=str(target), expected_sha256=digest)
            except Exception as exc:
                registered = False
                self.db.diagnostic(item.id, 'registration', 'emby', 'registration_failed', {'error': type(exc).__name__})
            if not registered:
                self.db.set_meta('theme_registration_mode', 'full_scan')
            self.db.provider_success('resolver', provider)
            self.db.provider_success('transport', transport)
            status = 'complete' if registered else 'pending_refresh'
            self.db.record_item(item, status, provider=provider, score=score, output_path=str(target), output_sha256=digest)
            return {'item_id': item.id, 'status': status, 'provider': provider, 'score': score,
                    'path': str(target), 'sha256': digest, 'duration': info['duration']}

    def apply_manual(self, item: MediaItem, prepared: Path, info: dict, *, expected_sha256: str | None, adopt: bool) -> dict:
        candidate = Candidate('manual', 'User selected theme', 'manual', score=100, exact=True, transport='local_media')
        result = self._publish_selected(item, prepared, info, candidate, expected_sha256,
                                        manual=True, adopt=adopt)
        return {'registered': result['registered'], 'locked': result['registered'], 'sha256': result['sha256']}

    def replace_owned(self, item: MediaItem, prepared: Path, info: dict, candidate: Candidate,
                      *, expected_sha256: str, replacement_id: int, detail: dict | None = None) -> dict:
        result = self._publish_selected(item, prepared, info, candidate, expected_sha256,
                                        manual=False, adopt=False, replacement_id=replacement_id, detail=detail)
        return {'item_id': item.id, 'status': 'complete', 'provider': candidate.resolver or candidate.provider,
                'transport': candidate.transport or 'direct_http', 'sha256': result['sha256'],
                'duration': info['duration'], 'backup': result['backup']}

    def _publish_selected(self, item, prepared, info, candidate, expected, *, manual, adopt,
                          replacement_id=None, detail=None):
        # Keep the item guard through rollback too. No other application can
        # update this item's journal between the write and its recovery decision.
        with self.db.item_guard(item.id):
            target, backup = None, None
            digest = info['sha256']
            written = False
            write_started = False
            try:
                if not manual and self.db.control(item.id)['locked']:
                    raise PermissionError('theme locked during preparation')
                target = self._target(item)
                current = sha256(target) if target.exists() else None
                if current != expected:
                    raise ValueError('theme changed after preview' if manual else 'theme changed since it was audited')
                state = self.db.item_state(item.id) or {}
                if current and (not state.get('source_provider') or state.get('output_sha256') != current) and not adopt:
                    raise PermissionError('explicit takeover required')
                if sha256(prepared) != digest:
                    raise ValueError('prepared audio changed after preview')
                if replacement_id is None:
                    replacement_id = self.db.start_replacement(item.id, candidate, current or '', candidate.score)
                backup = Path(self.config.replacement_backup_path) / item.id / f'{current}.mp3'
                self.db.prepare_replacement(replacement_id, digest, str(backup), str(target))
                write_started = True
                if current:
                    actual, _ = self.audio.atomic_replace_owned(prepared, target, current, backup)
                else:
                    created, _, actual = self.audio.atomic_commit(prepared, item.directory)
                    if not created:
                        write_started = False
                        raise ValueError('theme appeared during apply')
                written = True
                if actual != digest:
                    # Rollback must compare the bytes actually installed, not a
                    # stale preview hash if the staging file changed mid-copy.
                    digest = actual
                    raise ValueError('prepared audio changed during publication')
                registered = self.emby.refresh_and_verify(item.id, expected_path=str(target), expected_sha256=digest)
                if not registered and current:
                    raise RuntimeError('registration_failed')
                if target.is_symlink() or not target.exists() or sha256(target) != digest:
                    raise RuntimeError('theme changed during registration')
                if manual:
                    self.db.commit_application(item, replacement_id, digest, target, registered)
                else:
                    self.db.provider_success('resolver', candidate.resolver or candidate.provider)
                    self.db.provider_success('transport', candidate.transport or 'direct_http')
                    self.db.complete_replacement(replacement_id, item.id, candidate.resolver or candidate.provider, candidate.score, digest,
                                                 quality='extracted_'+detail['quality'] if detail else 'search_match', extraction=detail)
                return {'registered': registered, 'sha256': digest, 'backup': str(backup)}
            except Exception as exc:
                if replacement_id is not None:
                    # A failure after rename/fsync can occur before the atomic
                    # helper returns. The persisted intent and exact new hash
                    # still identify the file this operation may restore.
                    if write_started and not written and target and not target.is_symlink() and target.exists():
                        written = sha256(target) == digest and digest != expected
                    outcome = 'failed'
                    if written and expected:
                        try:
                            restored = self.audio.restore_replacement(target, backup, digest, expected)
                        except Exception as rollback_error:
                            restored = False
                            self.db.diagnostic(item.id, 'rollback', 'publisher', 'rollback_conflict', {'error': type(rollback_error).__name__})
                        outcome = 'rolled_back' if restored else 'rollback_conflict'
                    elif written:
                        # No previous file exists. Retain the new file and its
                        # ownership so registration can be retried safely.
                        self.db.commit_application(item, replacement_id, digest, target, False)
                        outcome = 'pending_refresh'
                    self.db.finish_replacement(replacement_id, outcome,
                                               new_sha256=digest if written else None,
                                               backup_path=str(backup) if backup and backup.exists() else None,
                                               error=type(exc).__name__)
                raise
