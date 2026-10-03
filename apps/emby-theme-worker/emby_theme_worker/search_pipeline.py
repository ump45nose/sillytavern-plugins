"""Bounded child process: upstream calls and yt-dlp cannot outlive the search budget."""
from __future__ import annotations
import dataclasses
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Iterable, Literal
import httpx
from rapidfuzz.fuzz import partial_ratio
from .models import Candidate, MediaItem
from .scoring import normalize, score_all, score_candidate


@dataclasses.dataclass(frozen=True, slots=True)
class SearchFailure:
    """A resolver failure without upstream messages, URLs, or credentials."""

    provider: str
    category: Literal["transient", "rate_limit"]
    reason: str
    query: str | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.category not in {"transient", "rate_limit"}:
            raise ValueError("invalid search failure category")


class SearchResult(list[Candidate]):
    """List-compatible candidates plus failures that must not become no-result."""

    def __init__(self, candidates: Iterable[Candidate] = (), failures: Iterable[SearchFailure] = (), *, complete: bool = True):
        super().__init__(candidates)
        self.failures = tuple(failures)
        self.complete = complete

    @property
    def failure_class(self) -> Literal["transient", "rate_limit"] | None:
        if any(failure.category == "rate_limit" for failure in self.failures):
            return "rate_limit"
        return "transient" if self.failures else None


def _provider_failure(name: str, exc: Exception, query: str | None = None) -> SearchFailure:
    from .providers import ProviderBlocked, ProviderParserError
    from .ytdlp_runner import YtDlpServiceError, YtDlpRateLimitError

    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    blocked = status in {401, 403, 429} or isinstance(exc, (ProviderBlocked, YtDlpServiceError))
    # Some providers replace HTTPStatusError with a redacted service exception.
    # Only classify an explicit 429 as rate limiting; a generic block/timeout is
    # transient. Never serialize the upstream error text.
    rate_limited = status == 429 or isinstance(exc, YtDlpRateLimitError) or (
        isinstance(exc, (ProviderBlocked, YtDlpServiceError)) and bool(re.search(r"\b429\b", str(exc)))
    )
    parser_error = isinstance(exc, (ProviderParserError, ValueError, KeyError, TypeError))
    reason = "blocked" if blocked else ("parser_error" if parser_error else "request_failed")
    return SearchFailure(name, "rate_limit" if rate_limited else "transient", reason, query, type(exc).__name__)

def queries(item: MediaItem, tracks: list[dict] = (), provider: str | None = None) -> list[str]:
    from .scoring import THEME
    from .query_policy import MOVIE_QUERY_PROFILES
    title = item.original_title or item.name
    if item.item_type == 'Movie' and provider in MOVIE_QUERY_PROFILES:
        values = [item.search_text] if item.search_text else []
        track=next((t for t in tracks if THEME.search(t['title'])),None)
        if track:values.append(f"{track['title']} {track['artist']} {title}")
        values += [template.format(title=title,local=item.name,year=item.year or '') for template in MOVIE_QUERY_PROFILES[provider]]
        values += [f'{alias} theme' for alias in item.aliases]
        return list(dict.fromkeys(' '.join(value.split()) for value in values if value))[:4]
    intent = "opening theme OP1" if item.is_anime else ("main theme" if item.item_type == "Movie" else "opening theme")
    values = [item.search_text] if item.search_text else []
    values += [f"{title} {item.year or ''} {intent}", f"{item.name} {'主题曲' if item.item_type == 'Movie' else '片头曲'}"]
    theme_track = next((t for t in tracks if THEME.search(t['title'])), None)
    if theme_track:
        values.append(f"{theme_track['title']} {theme_track['artist']} {title}")
    elif item.aliases:
        values.append(f"{item.aliases[0]} {intent}")
    values += [f"{title} {'end credits' if item.item_type == 'Movie' else 'theme song'}", f"{item.aliases[0] if item.aliases else title} main titles"]
    values += [f"{alias} {intent}" for alias in item.aliases]
    return list(dict.fromkeys(v.strip() for v in values if v))[:4]

def musicbrainz(item: MediaItem) -> list[dict]:
    title = item.original_title or item.name
    with httpx.Client(timeout=12, headers={"User-Agent": "EmbyThemeWorker/0.3 (https://github.com/ump45nose/media-automation)"}) as client:
        data = client.get("https://musicbrainz.org/ws/2/release/", params={"query": f'release:"{title}" AND secondarytype:soundtrack', "fmt": "json", "limit": 5}).raise_for_status().json()
        def related_release(release):
            evidence = ' '.join(str(release.get(k, '')) for k in ('title', 'disambiguation', 'release-group'))
            if any(word in evidence.casefold() for word in ('video game', 'game soundtrack', 'xbox', 'playstation')):
                return False
            if partial_ratio(normalize(title), normalize(release.get('title'))) < 90:
                return False
            date = str(release.get('date') or '')[:4]
            # A same-name, undated album is not evidence of this film's identity.
            return not item.year or (date.isdigit() and abs(int(date)-item.year) <= 1)
        release = next((r for r in data.get("releases", []) if related_release(r)), None)
        if not release:
            return []
        time.sleep(1.1)
        album = client.get(f"https://musicbrainz.org/ws/2/release/{release['id']}", params={"inc": "recordings+artist-credits", "fmt": "json"}).raise_for_status().json()
        result = []
        for medium in album.get("media", []):
            for track in medium.get("tracks", []):
                recording = track.get("recording", {})
                result.append({"title": recording.get("title", track.get("title", "")), "artist": " ".join(a.get("name", "") for a in recording.get("artist-credit", album.get("artist-credit", [])) if isinstance(a, dict)), "album_title": album.get("title"), "recording_id": recording.get("id")})
        from .scoring import THEME
        return sorted(result, key=lambda t: bool(THEME.search(t["title"])), reverse=True)[:10]

def search(config, db, item: MediaItem) -> SearchResult:
    payload = {"config": dataclasses.asdict(config), "item": dataclasses.asdict(item)}
    try:
        process = subprocess.Popen([sys.executable, "-m", __name__], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    except OSError as exc:
        failure = SearchFailure("all", "transient", "child_start_failed", error_type=type(exc).__name__)
        db.diagnostic(item.id, "search", "all", failure.reason, {"error": failure.error_type})
        return SearchResult(failures=[failure], complete=False)
    found: list[Candidate] = []
    failures: list[SearchFailure] = []
    lock = threading.Lock()
    completed = threading.Event()

    def fail(reason: str, error_type: str | None = None) -> None:
        with lock:
            failures.append(SearchFailure("all", "transient", reason, error_type=error_type))

    def consume():
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("invalid search event")
                    if event.get("type") == "complete":
                        completed.set()
                    elif event.get("type") == "failure":
                        failure = SearchFailure(**event["failure"])
                        with lock:
                            failures.append(failure)
                    else:
                        # Candidate records retain the original wire format.
                        candidate = Candidate(**event)
                        if not all(isinstance(getattr(candidate, key), str) for key in ('provider', 'title', 'source_url')):
                            raise ValueError('invalid candidate text')
                        if any(getattr(candidate, key) is not None and not isinstance(getattr(candidate, key), str) for key in ('media_type', 'resolver', 'transport')):
                            raise ValueError('invalid candidate source metadata')
                        if not isinstance(candidate.exact, bool) or not isinstance(candidate.metadata, dict):
                            raise ValueError('invalid candidate evidence')
                        if candidate.duration is not None and (not isinstance(candidate.duration, (float, int)) or not math.isfinite(candidate.duration)):
                            raise ValueError('invalid candidate duration')
                        if candidate.year is not None and not isinstance(candidate.year, int):
                            raise ValueError('invalid candidate year')
                        # Validate metadata consumed by scoring while this record
                        # can still be isolated from healthy partial candidates.
                        score_candidate(candidate, item)
                        with lock:
                            found.append(candidate)
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    fail("invalid_child_output", type(exc).__name__)
        except (OSError, UnicodeError) as exc:
            fail("child_output_failed", type(exc).__name__)

    def stop() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    terminated = False
    try:
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
        process.wait(timeout=config.providers.search_budget_seconds)
    except subprocess.TimeoutExpired:
        terminated = True
        stop()
        fail("deadline_exceeded", "TimeoutExpired")
        db.diagnostic(item.id, "search", "all", "deadline_exceeded")
    except OSError as exc:
        terminated = True
        stop()
        fail("child_input_failed", type(exc).__name__)
        db.diagnostic(item.id, "search", "all", "child_input_failed", {"error": type(exc).__name__})
    finally:
        if not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
    if process.returncode and not terminated:
        fail("child_exit_failed")
        db.diagnostic(item.id, "search", "all", "child_exit_failed", {"returncode": process.returncode})
    reader.join(timeout=5)
    if reader.is_alive():
        # Descendants may still hold the output pipe after the child exits.
        # An incomplete stream is not proof of an empty upstream result.
        fail("child_output_incomplete")
        stop()
        reader.join(timeout=1)
    if not reader.is_alive():
        process.stdout.close()
    complete = completed.is_set() and process.returncode == 0 and not reader.is_alive()
    if not completed.is_set() and process.returncode == 0:
        # A successful process exit alone does not prove all providers ran.
        # Require an explicit end-of-search record before claiming no result.
        fail("child_completion_missing")
        db.diagnostic(item.id, "search", "all", "child_completion_missing")
    with lock:
        return SearchResult(score_all(list(found), item), failures, complete=complete)

def child():
    from .config import Config, Limits, ProviderSettings, RefreshSettings
    from .db import StateDB
    from .providers import Providers
    payload = json.load(sys.stdin)
    raw = payload["config"]
    config = Config(**{**raw, "limits": Limits(**raw["limits"]), "providers": ProviderSettings(**raw["providers"]), "refresh": RefreshSettings(**raw["refresh"])})
    db, item = StateDB(config.database_path), MediaItem(**payload["item"])
    # Honor lower configured concurrency while retaining the documented global
    # two-request bound used to avoid bursty provider traffic.
    concurrency = max(1, min(2, config.limits.network_concurrency))
    providers = Providers(config.providers.enabled, min(15, config.providers.timeout_seconds), db, config.providers.cookies, min(30, config.providers.ytdlp_search_timeout_seconds))
    lock = threading.Lock()
    tracks = []

    def emit_failure(failure: SearchFailure) -> None:
        with lock:
            print(json.dumps({"type": "failure", "failure": dataclasses.asdict(failure)}), flush=True)

    def execute(name, method, query=None):
        if name not in providers.enabled:
            db.diagnostic(item.id, "resolver", name, "not_executed", {"reason": "disabled"})
            return
        if not providers._enabled(name):
            emit_failure(SearchFailure(name, "transient", "circuit_open", query, "CircuitOpen"))
            db.diagnostic(item.id, "resolver", name, "not_executed", {"reason": "circuit_open"})
            return
        try:
            result = method(replace(item, search_text=query))
            candidates = result if isinstance(result, list) else ([result] if result else [])
            db.diagnostic(item.id, "resolver", name, "hit" if candidates else "no_result", {"query": query, "count": len(candidates)})
            db.provider_success("resolver", name)
            for candidate in candidates:
                candidate.metadata["query"] = query
                for track in tracks:
                    if normalize(track['title']) in normalize(candidate.title) and track['artist'] and partial_ratio(normalize(track['artist']), normalize(candidate.title)) >= 85:
                        candidate.metadata.update(album_title=track['album_title'], track_evidence=track)
                        break
                with lock:
                    print(json.dumps(dataclasses.asdict(candidate)), flush=True)
        except Exception as exc:
            failure = _provider_failure(name, exc, query)
            emit_failure(failure)
            db.diagnostic(item.id, "resolver", name, failure.reason, {"error": failure.error_type, "category": failure.category})
            if failure.reason == "blocked" or isinstance(exc, httpx.TransportError):
                db.provider_failure("resolver", name, type(exc).__name__)
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            exact = ["themerrdb"] + (["animethemes"] if item.is_anime else []) + (["plex_tv", "televisiontunes"] if item.item_type == "Series" else [])
            list(pool.map(lambda name: execute(name, getattr(providers, name)), exact))
        tracks = []
        try:
            tracks = musicbrainz(item)
            db.diagnostic(item.id, "metadata", "musicbrainz", "hit" if tracks else "no_result", {"tracks": tracks})
        except Exception as exc:
            # MusicBrainz only enriches queries. Title-based audio resolvers
            # still run, so metadata failure does not invalidate their empties.
            db.diagnostic(item.id, "metadata", "musicbrainz", "request_failed", {"error": type(exc).__name__})
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            by_source={name:queries(item,tracks,provider=name) for name in ('youtube','bilibili','netease','qqmusic')}
            work=[(name,values[round_index]) for round_index in range(4) for name,values in by_source.items() if round_index<len(values)]
            work.insert(0, ("archive", None))
            list(pool.map(lambda pair: execute(pair[0], getattr(providers, pair[0]), pair[1]), work))
    finally:
        providers.close()
    with lock:
        print(json.dumps({"type": "complete"}), flush=True)

if __name__ == "__main__":
    child()
