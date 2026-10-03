from __future__ import annotations

import dataclasses
import io
import json
import subprocess
import sys

import httpx
import pytest

from emby_theme_worker import db as db_module, providers as providers_module, search_pipeline
from emby_theme_worker.config import Config
from emby_theme_worker.models import Candidate, MediaItem
from emby_theme_worker.providers import ProviderBlocked, ProviderParserError
from emby_theme_worker.search_pipeline import SearchFailure, SearchResult
from emby_theme_worker.ytdlp_runner import YtDlpServiceError, YtDlpTimeout


def media() -> MediaItem:
    return MediaItem("search-item", "Example Film", "Example Film", 2025, "Movie", "/Media/Example/film.mkv")


class FakeDB:
    def __init__(self):
        self.diagnostics = []
        self.successes = []
        self.failures = []

    def diagnostic(self, *args):
        self.diagnostics.append(args)

    def provider_success(self, *args):
        self.successes.append(args)

    def provider_failure(self, *args):
        self.failures.append(args)


def http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/?token=do-not-serialize")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("secret upstream error", request=request, response=response)


@pytest.mark.parametrize(
    ("error", "category", "reason"),
    [
        (http_error(429), "rate_limit", "blocked"),
        (http_error(403), "transient", "blocked"),
        (http_error(503), "transient", "request_failed"),
        (httpx.ReadTimeout("secret upstream error"), "transient", "request_failed"),
        (httpx.ConnectError("secret upstream error"), "transient", "request_failed"),
        (ProviderBlocked("HTTP 429"), "rate_limit", "blocked"),
        (ProviderBlocked("anti-bot challenge"), "transient", "blocked"),
        (YtDlpServiceError("transport_blocked_or_unavailable"), "transient", "blocked"),
        (YtDlpTimeout("secret upstream error"), "transient", "request_failed"),
        (ProviderParserError("secret upstream error"), "transient", "parser_error"),
        (ValueError("secret upstream error"), "transient", "parser_error"),
        (KeyError("secret upstream error"), "transient", "parser_error"),
    ],
)
def test_provider_failures_are_typed_and_redacted(error, category, reason):
    failure = search_pipeline._provider_failure("youtube", error, "Example Film theme")
    assert failure.category == category
    assert failure.reason == reason
    assert failure.error_type == type(error).__name__
    assert failure.query == "Example Film theme"
    assert "secret" not in json.dumps(dataclasses.asdict(failure))
    assert "do-not-serialize" not in json.dumps(dataclasses.asdict(failure))


def test_search_result_remains_a_candidate_list():
    candidate = Candidate("archive", "theme", "https://example.test/theme")
    transient = SearchFailure("archive", "transient", "request_failed")
    limited = SearchFailure("youtube", "rate_limit", "blocked")
    result = SearchResult([candidate], [transient, limited])
    assert isinstance(result, list)
    assert result == [candidate]
    assert list(result) == [candidate]
    assert result.failures == (transient, limited)
    assert result.complete
    assert result.failure_class == "rate_limit"
    assert SearchResult(failures=[transient]).failure_class == "transient"
    assert SearchResult().failure_class is None


def run_child(monkeypatch, capsys, *, enabled=(), results=None, circuits=(), metadata_error=None, item_override=None, network_concurrency=2):
    database = FakeDB()
    config = Config()
    config.providers.enabled = list(enabled)
    config.limits.network_concurrency = network_concurrency
    instances = []

    class FakeProviders:
        def __init__(self, selected, *args):
            self.enabled = set(selected)
            self.closed = False
            self.calls = []
            instances.append(self)

        def _enabled(self, name):
            return name in self.enabled and name not in circuits

        def __getattr__(self, name):
            def execute(item):
                self.calls.append((name, item.search_text))
                outcome = (results or {}).get(name, [])
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            return execute

        def close(self):
            self.closed = True

    def metadata(_item):
        if metadata_error:
            raise metadata_error
        return []

    payload = {"config": dataclasses.asdict(config), "item": dataclasses.asdict(item_override or media())}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(db_module, "StateDB", lambda _path: database)
    monkeypatch.setattr(providers_module, "Providers", FakeProviders)
    monkeypatch.setattr(search_pipeline, "musicbrainz", metadata)
    search_pipeline.child()
    assert instances[0].closed
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1] == {"type": "complete"}
    return events[:-1], database, instances[0]


def test_child_emits_failure_and_preserves_other_provider_candidates(monkeypatch, capsys):
    candidate = Candidate("archive", "Example Film 2025 Main Theme", "https://example.test/theme", duration=120)
    events, database, _ = run_child(
        monkeypatch, capsys, enabled=["themerrdb", "archive"],
        results={"themerrdb": http_error(429), "archive": [candidate]},
    )
    failures = [event["failure"] for event in events if event.get("type") == "failure"]
    candidates = [event for event in events if event.get("type") != "failure"]
    assert len(failures) == len(candidates) == 1
    assert failures[0]["category"] == "rate_limit"
    assert failures[0]["provider"] == "themerrdb"
    assert candidates[0]["source_url"] == candidate.source_url
    assert ("resolver", "archive") in database.successes
    assert database.failures == [("resolver", "themerrdb", "HTTPStatusError")]


def test_disabled_providers_are_not_failures_but_open_circuits_are(monkeypatch, capsys):
    events, database, instance = run_child(monkeypatch, capsys, enabled=["themerrdb"], circuits=["themerrdb"])
    assert instance.calls == []
    assert len(events) == 1
    assert events[0]["failure"]["category"] == "transient"
    assert events[0]["failure"]["reason"] == "circuit_open"
    assert events[0]["failure"]["provider"] == "themerrdb"
    assert any(entry[2] == "archive" and entry[4]["reason"] == "disabled" for entry in database.diagnostics)


def test_successful_empty_audio_search_ignores_optional_metadata_failure(monkeypatch, capsys):
    events, database, instance = run_child(
        monkeypatch, capsys, enabled=["themerrdb", "archive"],
        metadata_error=httpx.ReadTimeout("optional metadata unavailable"),
    )
    assert events == []
    assert len(instance.calls) == 2
    assert len(database.successes) == 2
    assert any(entry[1:4] == ("metadata", "musicbrainz", "request_failed") for entry in database.diagnostics)


def test_child_parser_errors_are_transmitted(monkeypatch, capsys):
    events, _, _ = run_child(
        monkeypatch, capsys, enabled=["themerrdb"],
        results={"themerrdb": ProviderParserError("missing audio link")},
    )
    assert events[0]["failure"]["category"] == "transient"
    assert events[0]["failure"]["reason"] == "parser_error"


def run_search(monkeypatch, script, *, budget=3, complete=True):
    """Use a local stdlib-only child, never a live resolver or download."""
    real_popen = subprocess.Popen
    completion = "; print('{\"type\":\"complete\"}', flush=True)" if complete else ""

    def start(_command, **kwargs):
        return real_popen([sys.executable, "-c", "import sys; sys.stdin.read(); " + script + completion], **kwargs)

    monkeypatch.setattr(search_pipeline.subprocess, "Popen", start)
    config = Config()
    config.providers.search_budget_seconds = budget
    database = FakeDB()
    return search_pipeline.search(config, database, media()), database


def candidate_record():
    return json.dumps(dataclasses.asdict(Candidate(
        "archive", "Example Film 2025 Main Theme", "https://example.test/theme", duration=120,
    )))


def test_parent_roundtrips_typed_failure_and_scores_partial_candidates(monkeypatch):
    failure = SearchFailure("youtube", "rate_limit", "blocked", error_type="HTTPStatusError")
    event = json.dumps({"type": "failure", "failure": dataclasses.asdict(failure)})
    script = f"print({candidate_record()!r}, flush=True); print({event!r}, flush=True)"
    result, _ = run_search(monkeypatch, script)
    assert len(result) == 1 and result[0].score > 0
    assert result.failures == (failure,)
    assert result.failure_class == "rate_limit"
    assert result.complete


def test_parent_successful_empty_search_remains_genuine_empty(monkeypatch):
    result, _ = run_search(monkeypatch, "pass")
    assert result == []
    assert result.failure_class is None
    assert result.failures == ()
    assert result.complete


def test_clean_exit_without_completion_is_not_proven_empty(monkeypatch):
    result, _ = run_search(monkeypatch, "pass", complete=False)
    assert result == []
    assert result.failure_class == "transient"
    assert not result.complete
    assert result.failures[0].reason == "child_completion_missing"


def test_search_deadline_preserves_partial_success_and_is_transient(monkeypatch):
    script = f"print({candidate_record()!r}, flush=True); import time; time.sleep(30)"
    result, database = run_search(monkeypatch, script, budget=0.5)
    assert len(result) == 1
    assert result.failure_class == "transient"
    assert not result.complete
    assert [failure.reason for failure in result.failures] == ["deadline_exceeded"]
    assert any(entry[3] == "deadline_exceeded" for entry in database.diagnostics)


def test_nonzero_child_exit_is_transient_even_with_partial_success(monkeypatch):
    script = f"print({candidate_record()!r}, flush=True); sys.exit(4)"
    result, database = run_search(monkeypatch, script)
    assert len(result) == 1
    assert result.failure_class == "transient"
    assert not result.complete
    assert result.failures[0].reason == "child_exit_failed"
    assert database.diagnostics[0][4] == {"returncode": 4}


@pytest.mark.parametrize("invalid", ["not JSON", "null", '{"type":"failure","failure":{}}'])
def test_invalid_child_output_is_not_mistaken_for_no_result(monkeypatch, invalid):
    result, _ = run_search(monkeypatch, f"print({invalid!r}, flush=True); print({candidate_record()!r}, flush=True)")
    assert len(result) == 1
    assert result.failure_class == "transient"
    assert result.failures[0].reason == "invalid_child_output"


def test_child_launch_failure_is_transient(monkeypatch):
    def start(*args, **kwargs):
        raise OSError("secret local details")

    monkeypatch.setattr(search_pipeline.subprocess, "Popen", start)
    result = search_pipeline.search(Config(), FakeDB(), media())
    assert result == []
    assert result.failure_class == "transient"
    assert result.failures[0].reason == "child_start_failed"
    assert result.failures[0].error_type == "OSError"


def test_ytdlp_rate_limit_retains_typed_status_after_redaction():
    from emby_theme_worker.ytdlp_runner import classify_error
    error = classify_error('HTTP Error 429 from https://example.test/?token=secret')
    failure = search_pipeline._provider_failure('youtube', error)
    assert failure.category == 'rate_limit'
    assert 'secret' not in str(error)


@pytest.mark.parametrize('field,value', [('duration', 'bad'), ('duration', float('nan')), ('year', 'bad'), ('source_url', []), ('title', 123), ('exact', 'yes'), ('metadata', []), ('media_type', [])])
def test_invalid_candidate_values_preserve_healthy_partial_results(monkeypatch, field, value):
    invalid = json.loads(candidate_record())
    invalid[field] = value
    script = f"print({json.dumps(invalid)!r}, flush=True); print({candidate_record()!r}, flush=True)"
    result, _ = run_search(monkeypatch, script)
    assert len(result) == 1
    assert result.failure_class == 'transient'
    assert result.failures[0].reason == 'invalid_child_output'



def test_only_search_pipeline_collects_all_exact_resolvers(monkeypatch, capsys):
    item = media(); item.item_type = 'Series'
    names = ['themerrdb', 'plex_tv', 'televisiontunes']
    outcomes = {name: Candidate(name, item.name+' theme', 'https://example.test/'+name, exact=name != 'televisiontunes') for name in names}
    events, database, instance = run_child(monkeypatch, capsys, enabled=names, results=outcomes, item_override=item)
    assert {event['provider'] for event in events} == set(names)
    assert set(database.successes) == {('resolver', name) for name in names}
    assert {name for name, _ in instance.calls} == set(names)


@pytest.mark.parametrize('configured,expected', [(0, 1), (1, 1), (2, 2), (8, 2)])
def test_search_pipeline_honors_bounded_network_concurrency(monkeypatch, capsys, configured, expected):
    widths = []
    class Pool:
        def __init__(self, max_workers): widths.append(max_workers)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def map(self, fn, values): return map(fn, values)
    monkeypatch.setattr(search_pipeline, 'ThreadPoolExecutor', Pool)
    run_child(monkeypatch, capsys, network_concurrency=configured)
    assert widths == [expected, expected]
