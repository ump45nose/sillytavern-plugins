from __future__ import annotations

import hashlib
import fcntl
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .audio import AudioProcessor, sha256, temporary_directory
from .config import Config
from .db import StateDB
from .emby import EmbyClient
from .models import Candidate, MediaItem
from .publisher import ThemePublisher
from .security import redact
from .ytdlp_runner import YtDlpServiceError, YtDlpTimeout


LOG = logging.getLogger(__name__)


def transport_key(candidate: Candidate) -> str:
    transport = candidate.transport or "direct_http"
    return f"direct_http:{urlsplit(candidate.source_url).hostname}" if transport == "direct_http" else transport


class Worker:
    def __init__(self, config: Config, db: StateDB, emby: EmbyClient):
        self.config = config
        self.db = db
        self.emby = emby
        self.audio = AudioProcessor(
            config.target_seconds,
            config.output_bitrate,
            config.providers.timeout_seconds,
            config.providers.cookies,
            config.providers.ytdlp_download_timeout_seconds,
        )

    def close(self) -> None:
        self.emby.close()

    def preview(self, item_id: str | None = None) -> dict:
        items = [self.emby.get_item(item_id)] if item_id else list(self.emby.iter_missing())
        eligible: list[MediaItem] = []
        disk_theme_skips = 0
        for item in items:
            if (item.directory / "theme.mp3").exists():
                disk_theme_skips += 1
            else:
                eligible.append(item)
        emby_theme_count = int(self.emby.theme_visible(items[0].id)) if item_id and items else len(list(self.emby.iter_themed()))
        return {
            "allowed_path": self.config.allowed_path,
            "adult_paths_mounted": False,
            "eligible_missing": len(eligible),
            "existing_theme_skips": emby_theme_count + disk_theme_skips,
            "emby_theme_count": emby_theme_count,
            "unindexed_disk_theme_count": disk_theme_skips,
            "provider_routes": {
                "anime": ["animethemes", "themerrdb", "plex_tv", "televisiontunes", "fuzzy", "intro_markers"],
                "series": ["themerrdb", "plex_tv", "televisiontunes", "fuzzy", "intro_markers"],
                "movie": ["themerrdb", "fuzzy"],
            },
            "items": [
                {"id": item.id, "name": item.name, "type": item.item_type, "year": item.year, "anime": item.is_anime}
                for item in eligible
            ],
        }

    def probe(self, item_id: str) -> dict:
        item = self.emby.get_item(item_id)
        exact = self._resolve_exact(item)
        fuzzy = self._resolve_fuzzy(item)
        return {
            "item": {"id": item.id, "name": item.name, "type": item.item_type, "year": item.year},
            "exact": [candidate.public_dict() for candidate in exact],
            "fuzzy": [candidate.public_dict() for candidate in fuzzy],
            "eligible": [candidate.public_dict() for candidate in exact + fuzzy if candidate.exact or candidate.score >= self.config.providers.threshold],
        }

    def run(self, *, item_id: str | None = None, limit: int | None = None) -> dict:
        bootstrap = self.db.get_meta("bootstrap_complete", "false") != "true"
        mode = "manual_item" if item_id else ("bootstrap" if bootstrap else "scheduled")
        run_id = self.db.start_run(mode)
        attempts = successes = 0
        completed_scan = True
        library_scan = "not_requested"
        try:
            items = [self.emby.get_item(item_id)] if item_id else list(self.emby.iter_missing())
            attempt_cap = limit
            success_cap: int | None = None
            if item_id is None and limit is None:
                if bootstrap:
                    attempt_cap = self.config.limits.bootstrap_attempts or None
                else:
                    attempt_cap = self.config.limits.regular_attempts
                    success_cap = self.config.limits.regular_successes
            for item in items:
                if attempt_cap is not None and attempt_cap > 0 and attempts >= attempt_cap:
                    completed_scan = False
                    break
                if success_cap is not None and success_cap > 0 and successes >= success_cap:
                    completed_scan = False
                    break
                # An explicit operator retry is authoritative. Scheduled scans
                # still honor per-item backoff and terminal skip states.
                if item_id is None and not self.db.is_due(item.id):
                    continue
                attempts += 1
                result = self.process(item)
                if result["status"] == "complete":
                    successes += 1
            if item_id is None and self.db.pending_item_ids() and self.config.refresh.full_scan_after_scheduled_run:
                library_scan, registered = self._register_pending()
                successes += registered
            pending = len(self.db.pending_item_ids())
            if item_id is None and bootstrap and completed_scan and pending == 0:
                self.db.set_meta("bootstrap_complete", "true")
                self.db.set_meta("bootstrap_completed_at", __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat())
            self.db.finish_run(run_id, attempts, successes, "complete")
            return {
                "run_id": run_id,
                "mode": mode,
                "attempts": attempts,
                "successes": successes,
                "scan_complete": completed_scan,
                "library_scan": library_scan,
                "pending_refresh": pending,
            }
        except Exception as exc:
            self.db.finish_run(run_id, attempts, successes, "failed", redact(exc))
            raise

    def process(self, item: MediaItem) -> dict:
        self._download_attempts = set()
        if self.db.control(item.id)["locked"]:
            return {"item_id": item.id, "status": "locked"}
        LOG.info("processing item=%s type=%s", item.id, item.item_type)
        target = item.directory / "theme.mp3"
        if target.is_symlink():
            raise PermissionError('theme symlinks are not managed')
        state = self.db.item_state(item.id)
        if self.emby.theme_visible(item.id):
            if state and state.get("source_provider") and state.get("output_sha256") and target.exists() and sha256(target) == state["output_sha256"]:
                verified = self.emby.verify_theme_resource(item.id, str(target), state['output_sha256'])
                self.db.record_item(
                    item, "complete" if verified else "pending_refresh", provider=state.get("source_provider"), score=state.get("score"),
                    output_path=str(target), output_sha256=state["output_sha256"],
                )
                if verified and state.get('status')=='pending_refresh' and state.get('source_provider')=='manual':
                    self.db.set_control(item.id,locked=True)
                return {"item_id": item.id, "status": "complete" if verified else "pending_refresh", "provider": state.get("source_provider")}
            self.db.record_item(item, "skipped_existing")
            return {"item_id": item.id, "status": "skipped_existing"}
        if target.exists():
            owned = bool(
                state
                and state.get("output_sha256")
                and state.get("status") in {"pending_refresh", "failed"}
                and sha256(target) == state["output_sha256"]
            )
            if owned:
                # A prior full scan may have missed this sidecar.  Retry the
                # item's documented Default -> FullRefresh route before adding
                # it to another (expensive) library-wide scan.
                try:
                    registered=self.emby.refresh_and_verify(item.id, expected_path=str(target), expected_sha256=state['output_sha256'])
                except Exception as exc:
                    registered=False
                    self.db.diagnostic(item.id,'registration','emby','registration_failed',{'error':type(exc).__name__})
                if registered:
                    self.db.provider_success("resolver", state.get("source_provider") or "local_opening")
                    self.db.record_item(
                        item, "complete", provider=state.get("source_provider"), score=state.get("score"),
                        output_path=str(target), output_sha256=state["output_sha256"],
                    )
                    if state.get('source_provider')=='manual':self.db.set_control(item.id,locked=True)
                    return {"item_id": item.id, "status": "complete", "provider": state.get("source_provider")}
                self.db.record_item(
                    item, "pending_refresh", provider=state.get("source_provider"), score=state.get("score"),
                    output_path=str(target), output_sha256=state["output_sha256"],
                )
                return {"item_id": item.id, "status": "pending_refresh", "path": str(target)}
            self.db.record_item(item, "skipped_existing_unindexed", output_path=str(target), output_sha256=sha256(target))
            return {"item_id": item.id, "status": "skipped_existing_unindexed"}

        errors: list[str] = []
        exact = self._resolve_exact(item)
        result = self._try_candidates(item, exact, errors, route="exact")
        if result:
            return result

        # An exact database match identifies the desired theme, but it does not
        # guarantee that the referenced transport (usually YouTube) is usable.
        # Search the independent providers after a transport failure instead of
        # skipping directly to local opening extraction.
        fuzzy = self._resolve_fuzzy(item)
        eligible = [candidate for candidate in fuzzy if candidate.score >= self.config.providers.threshold]
        result = self._try_candidates(item, eligible, errors, route="fuzzy")
        if result:
            return result

        try:
            return self._from_local(item)
        except Exception as exc:
            errors.append(f"local:{exc.__class__.__name__}")
            search_result = getattr(self, '_search_results', ())
            failures = getattr(search_result, 'failures', ())
            errors.extend(f"resolver:{f.provider}:{f.category}:{f.reason}" for f in failures)
            error_class = "low_score" if fuzzy and not eligible else "not_found"
            if getattr(search_result, 'failure_class', None):
                error_class = 'rate_limit' if search_result.failure_class == 'rate_limit' else 'network'
            if any('RateLimitError' in error for error in errors):
                error_class = 'rate_limit'
            if error_class != 'rate_limit' and any(any(kind in err for kind in ("HTTP", "Timeout", "ServiceError", "CircuitOpen")) for err in errors):
                error_class = "network"
            if error_class in {"network", "rate_limit"}:
                failures = self.db.failure_count(item.id)
                hours = (self.config.backoff["network_hours"], 24, 72, 168)[min(failures, 3)]
                retry = self.db.backoff_until(hours=hours)
            elif error_class == "low_score":
                retry = self.db.backoff_until(days=self.config.backoff["low_score_days"])
            else:
                retry = self.db.backoff_until(days=self.config.backoff["not_found_days"])
            self.db.record_item(item, "failed", error_class=error_class, error=";".join(errors), retry_after=retry)
            return {"item_id": item.id, "status": "failed", "error_class": error_class, "errors": errors}

    def _record_candidates(self, item: MediaItem, candidates: list[Candidate]) -> None:
        for candidate in candidates:
            url_hash = hashlib.sha256(candidate.source_url.encode()).hexdigest()
            self.db.record_candidate(item.id, candidate, url_hash)

    def _resolve(self, item: MediaItem) -> tuple[list[Candidate], list[Candidate]]:
        return self._resolve_exact(item), self._resolve_fuzzy(item)

    def _resolve_exact(self, item: MediaItem) -> list[Candidate]:
        return [c for c in self._search(item) if c.exact]

    def _resolve_fuzzy(self, item: MediaItem) -> list[Candidate]:
        return [c for c in self._search(item) if not c.exact]

    def _search(self, item: MediaItem) -> list[Candidate]:
        key = (item.id, item.search_text)
        if getattr(self, "_search_key", None) != key:
            from .search_pipeline import search
            self._search_results = search(self.config, self.db, item)
            import hashlib
            with self.db.connect() as conn:
                feedback = {r['candidate_hash']: r['verdict'] for r in conn.execute('SELECT candidate_hash,verdict FROM feedback WHERE emby_id=? ORDER BY id', (item.id,))}
            for candidate in self._search_results:
                verdict = feedback.get(hashlib.sha256(candidate.source_url.encode()).hexdigest())
                candidate.metadata['user_feedback'] = verdict
                if verdict == 'wrong':
                    candidate.score = 0
                    candidate.exact = False
                    candidate.metadata.update(automatic_eligible=False, rejection='user_rejected')
            self._search_key = key
            self._record_candidates(item, self._search_results)
            for candidate in self._search_results:
                self.db.diagnostic(item.id, "score", candidate.provider, "eligible" if candidate.score >= self.config.providers.threshold else "low_score", candidate.public_dict())
        return self._search_results

    def _try_candidates(
        self,
        item: MediaItem,
        candidates: list[Candidate],
        errors: list[str],
        *,
        route: str,
    ) -> dict | None:
        for candidate in candidates:
            if not candidate.exact and candidate.metadata.get('automatic_eligible') is False:
                continue
            transport = transport_key(candidate)
            if not self.db.provider_available("transport", transport):
                errors.append(f"{transport}:CircuitOpen")
                continue
            if not self._permit_attempt(candidate):
                continue
            LOG.info(
                "candidate attempt item=%s route=%s provider=%s transport=%s score=%s",
                item.id, route, candidate.provider, transport, candidate.score,
            )
            try:
                return self._from_candidate(item, candidate)
            except Exception as exc:
                errors.append(f"{transport}:{exc.__class__.__name__}")
                LOG.warning(
                    "candidate failed item=%s route=%s provider=%s transport=%s error=%s",
                    item.id, route, candidate.provider, transport, exc.__class__.__name__,
                )
        return None

    def _from_candidate(self, item: MediaItem, candidate: Candidate) -> dict:
        with temporary_directory() as work:
            workdir = Path(work)
            source = self._fetch_candidate(candidate, workdir, item.id)
            prepared = workdir / "prepared.mp3"
            try:
                selection = self.audio.normalize_online(source, prepared)
            except Exception as exc:
                self.db.diagnostic(item.id,'audio',candidate.provider,'audio_failed',{'error':type(exc).__name__})
                raise
            self.db.diagnostic(item.id,'audio',candidate.provider,'prepared',selection)
            info = self.audio.validate_full(prepared, expected_duration=selection['duration'])
            result = self._commit(item, prepared, candidate.resolver or candidate.provider, candidate.transport or "direct_http", candidate.score, info)
            if result['status'] in {'complete','pending_refresh'}:
                self.db.set_control(item.id, quality='search_match')
            return result

    def _permit_attempt(self, candidate: Candidate) -> bool:
        if not hasattr(self, "_download_attempts"):
            self._download_attempts = set()
        if candidate.source_url in self._download_attempts or len(self._download_attempts) >= 3:
            return False
        self._download_attempts.add(candidate.source_url)
        return True

    def _fetch_candidate(self, candidate: Candidate, workdir: Path, item_id: str = '') -> Path:
        key = transport_key(candidate)
        try:
            result = self.audio.fetch_candidate(candidate, workdir)
        except Exception as exc:
            self.db.diagnostic(item_id,'transport',key,'download_failed',{'error':type(exc).__name__})
            service_failure = isinstance(exc, (httpx.TransportError, YtDlpServiceError, YtDlpTimeout))
            if isinstance(exc, httpx.HTTPStatusError):
                service_failure = exc.response.status_code in {401, 403, 429} or exc.response.status_code >= 500
            if service_failure:
                self.db.provider_failure("transport", key, exc.__class__.__name__)
            raise
        self.db.provider_success("transport", key)
        self.db.diagnostic(item_id,'transport',key,'download_success')
        return result

    def _from_local(self, item: MediaItem) -> dict:
        with temporary_directory() as work:
            prepared = Path(work) / "prepared.mp3"
            info, details = self.prepare_local(item, prepared)
            result = self._commit(item, prepared, "smart_extract", "local_media", 50, info)
            self.db.set_control(item.id, quality="extracted_"+details["quality"], extraction=details)
            self.db.defer_local_migration(item.id)
            return result

    def prepare_local(self, item: MediaItem, prepared: Path) -> tuple[dict, dict]:
        intro = self.emby.representative_intro(item.id) if item.item_type == "Series" else None
        if intro:
            self.audio.extract_intro(intro["path"], prepared, intro["start"], intro["end"])
            details = {k: intro[k] for k in ("episode_id", "start", "end")}
            details.update(quality="high", method="intro_markers")
        else:
            options = []
            with temporary_directory() as temp:
                for index, source in enumerate(self.emby.extraction_sources(item)):
                    target = Path(temp)/f"option-{index}.mp3"
                    try:
                        detail = self.audio.smart_extract(source["path"], target, source["ranges"])
                        detail["episode_id"] = source["episode_id"]
                        options.append((detail, target))
                    except Exception as exc:
                        self.db.diagnostic(item.id, "extraction", "local_media", "audio_failed", {"error": type(exc).__name__})
                if not options:
                    raise ValueError("no decodable local source")
                details, selected = max(options, key=lambda pair: (pair[0]["quality"] == "high", pair[0].get("shares", {}).get("music", 0)))
                import shutil
                shutil.copyfile(selected, prepared)
        return self.audio.validate(prepared, min_duration=1, max_duration=62), details

    def _commit(self, item: MediaItem, prepared: Path, provider: str, transport: str, score: int, info: dict) -> dict:
        if self.db.control(item.id)['locked']:
            raise PermissionError('theme is locked by user')
        return ThemePublisher(self.config, self.db, self.audio, self.emby).publish_new(
            item, prepared, provider, transport, score, info)

    def migrate_local(self, *, dry_run: bool, item_type: str | None = None, limit: int = 25, item_id: str | None = None) -> dict:
        with (self.db.path.parent / ".migration.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"dry_run": dry_run, "attempted": 0, "results": [], "status": "busy"}
            if not dry_run:
                self._recover_replacements()
            return self._migrate_local(dry_run=dry_run, item_type=item_type, limit=limit, item_id=item_id)

    def _recover_replacements(self) -> None:
        for snapshot in self.db.interrupted_replacements():
            with self.db.item_guard(str(snapshot['emby_id'])):
                # The snapshot can become stale while waiting behind an apply.
                # Re-read both status and payload before deciding to roll back.
                row = self.db.applying_replacement(snapshot['id'])
                if row is None:
                    continue
                if not row['output_path'] or not row['old_sha256']:
                    self.db.finish_replacement(row['id'], 'manual_review', new_sha256=row['new_sha256'], error='interrupted_new_file_retained')
                    continue
                target, backup = Path(row['output_path']), Path(row['backup_path'])
                status = 'rollback_conflict'
                if not target.is_symlink() and target.exists() and sha256(target) == row['old_sha256']:
                    status = 'interrupted'
                elif backup.exists() and self.audio.restore_replacement(target, backup, row['new_sha256'], row['old_sha256']):
                    status = 'rolled_back'
                self.db.finish_replacement(row['id'], status, new_sha256=row['new_sha256'], backup_path=str(backup), error='interrupted_before_commit')
                self.db.defer_local_migration(row['emby_id'], blocked=status == 'rollback_conflict', hours=6)

    def _migrate_local(self, *, dry_run: bool, item_type: str | None = None, limit: int = 25, item_id: str | None = None) -> dict:
        if item_id:
            state = self.db.item_state(item_id)
            rows = [state] if state and state.get("source_provider") in {"local_opening", "smart_extract", "intro_markers"} else []
        else:
            rows = self.db.local_opening_items(item_type)[:limit]
        results: list[dict] = []
        for state in rows:
            self._download_attempts = set()
            now = datetime.now(ZoneInfo(self.config.timezone))
            if not dry_run and (getattr(self, "should_stop", lambda: False)() or 1 <= now.hour < 9 or (now.hour == 0 and now.minute >= 45)):
                break
            try:
                item = self.emby.get_item(str(state["emby_id"]))
                target = item.directory / "theme.mp3"
                expected = str(state["output_sha256"])
                if target.is_symlink() or not target.exists() or sha256(target) != expected:
                    results.append({"item_id": item.id, "status": "changed_or_missing"})
                    if not dry_run:
                        self.db.defer_local_migration(item.id, blocked=True)
                    continue
                exact = self._resolve_exact(item)
                if dry_run:
                    fuzzy = [] if exact else self._resolve_fuzzy(item)
                    candidates = exact + [c for c in fuzzy if c.score >= self.config.providers.replacement_threshold]
                    if candidates:
                        results.append({"item_id": item.id, "name": item.name, "status": "ready", "candidate": candidates[0].public_dict()})
                    else:
                        results.append({"item_id": item.id, "status": "no_better_candidate"})
                    continue
                errors: list[str] = []
                completed = self._try_replacement_candidates(item, state, exact, errors, "exact")
                if not completed:
                    fuzzy = [c for c in self._resolve_fuzzy(item) if c.score >= self.config.providers.replacement_threshold]
                    completed = self._try_replacement_candidates(item, state, fuzzy, errors, "fuzzy")
                if not completed and state.get('source_provider') == 'local_opening':
                    # A legacy opening is the only fallback that may be replaced
                    # without a better online candidate. Never downgrade a search hit.
                    try:
                        completed = self._replace_local(item, state, Candidate('smart_extract', 'Intelligent local segment', 'local', score=50, transport='local_media'))
                        self.db.defer_local_migration(item.id)
                    except Exception as exc:
                        errors.append('extraction:'+type(exc).__name__)
                if completed:
                    results.append(completed)
                else:
                    results.append({"item_id": item.id, "status": "failed", "errors": errors})
                    search_failed = bool(getattr(getattr(self, '_search_results', ()), 'failures', ()))
                    self.db.defer_local_migration(item.id, hours=6 if search_failed or any("CircuitOpen" in e or "Timeout" in e or "ServiceError" in e or "RateLimitError" in e for e in errors) else 168)
            except Exception as exc:
                results.append({"item_id": str(state["emby_id"]), "status": "failed", "error": exc.__class__.__name__})
                if not dry_run:
                    missing = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404
                    self.db.defer_local_migration(str(state["emby_id"]), blocked=missing, hours=6)
        return {"dry_run": dry_run, "attempted": len(results), "results": results}

    def _try_replacement_candidates(self, item: MediaItem, state: dict, candidates: list[Candidate], errors: list[str], route: str) -> dict | None:
        for candidate in candidates:
            if not candidate.exact and candidate.metadata.get('automatic_eligible') is False:
                continue
            transport = transport_key(candidate)
            if not self.db.provider_available("transport", transport):
                errors.append(f"{route}:{transport}:CircuitOpen")
                continue
            if not self._permit_attempt(candidate):
                continue
            try:
                return self._replace_local(item, state, candidate)
            except Exception as exc:
                errors.append(f"{route}:{transport}:{exc.__class__.__name__}")
        return None

    def _replace_local(self, item: MediaItem, state: dict, candidate: Candidate) -> dict:
        expected = str(state['output_sha256'])
        replacement_id = self.db.start_replacement(item.id, candidate, expected, candidate.score)
        with temporary_directory() as work:
            workdir = Path(work)
            prepared = workdir / 'prepared.mp3'
            detail = None
            try:
                if candidate.provider == 'smart_extract' and candidate.transport == 'local_media':
                    info, detail = self.prepare_local(item, prepared)
                else:
                    source = self._fetch_candidate(candidate, workdir, item.id)
                    selection = self.audio.normalize_online(source, prepared)
                    info = self.audio.validate_full(prepared, expected_duration=selection['duration'])
            except Exception as exc:
                self.db.finish_replacement(replacement_id, 'failed', error=type(exc).__name__)
                raise
            return ThemePublisher(self.config, self.db, self.audio, self.emby).replace_owned(
                item, prepared, info, candidate, expected_sha256=expected,
                replacement_id=replacement_id, detail=detail)

    def _register_pending(self) -> tuple[str, int]:
        pending = self.db.pending_item_ids()
        if not pending:
            return "not_requested", 0
        LOG.info("requesting one Emby media-library scan for %s pending theme(s)", len(pending))
        self.emby.trigger_library_scan()
        finished = self.emby.wait_library_scan(
            self.config.refresh.library_scan_timeout_seconds,
            self.config.refresh.task_poll_seconds,
        )
        if not finished:
            return "timeout", 0
        completed = 0
        for item_id in pending:
            state = self.db.item_state(item_id) or {}
            if not state.get('output_sha256') or not self.emby.verify_theme_resource(item_id, state['output_path'], state['output_sha256']):
                # Do not claim completion without ThemeSongs readback.  These
                # files remain on disk for audit/manual intervention, but a
                # bounded registration failure must not restart bootstrap
                # indefinitely.
                self.db.record_registration_failure(
                    item_id,
                    self.db.backoff_until(days=self.config.backoff["registration_days"]),
                )
                LOG.warning("theme remains unindexed after refresh and library scan item=%s", item_id)
                continue
            item = self.emby.get_item(item_id)
            state = self.db.item_state(item_id) or {}
            self.db.record_item(
                item, "complete", provider=state.get("source_provider"), score=state.get("score"),
                output_path=state.get("output_path"), output_sha256=state.get("output_sha256"),
            )
            if state.get('source_provider')=='manual':self.db.set_control(item_id,locked=True)
            completed += 1
        return "complete", completed
