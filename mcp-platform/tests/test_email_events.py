"""邮件事件仅用 fake provider / fake IMAP 和临时目录，不连接真实邮箱。"""

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "integrations/email-mcp/src"))

from email_mcp_platform.event_provider import (  # noqa: E402
    FETCH_HEADERS,
    MAX_HEADER_BYTES,
    ProviderAccess,
    UpstreamHeaderProvider,
    parse_header_fetch,
)
from email_mcp_platform.events import (  # noqa: E402
    EVENT_NAME,
    Cursor,
    EmailEventProducer,
    EventSettings,
    HeaderMail,
    ImportanceRules,
    MailState,
    Observation,
    _key,
    register_email_event,
)


def mail(uid, **headers):
    return HeaderMail(uid, {
        "from": "sender@sender.invalid", "to": "owner@owner.invalid",
        "subject": "Personal update", **headers,
    })


class FakeProvider:
    def __init__(self):
        self.state = MailState("identity", 1, 10)
        self.messages = ()
        self.error = False
        self.calls = []

    async def observe(self, account, mailbox, cursor, limit):
        self.calls.append((account, mailbox))
        if self.error:
            raise RuntimeError("provider detail must not be logged")
        last = cursor.last_uid if cursor else 0
        rows = tuple(m for m in self.messages if m.uid > last)[:limit]
        return Observation(
            self.state, rows, self.state.uidnext - 1, ("owner@owner.invalid",)
        )


class FakePublisher:
    def __init__(self):
        self.error = False
        self.records = {}
        self.calls = []

    async def publish(self, name, data, *, subject, event_id, timestamp=None):
        self.calls.append(event_id)
        if self.error:
            raise RuntimeError("delivery persistence unavailable")
        duplicate = event_id in self.records
        self.records.setdefault(event_id, (name, data, subject))
        return {"event_id": event_id, "duplicate": duplicate, "queued": int(not duplicate)}


def setup(tmp_path, **overrides):
    settings = replace(EventSettings(
        enabled=True, owner="owner", accounts=("bound-account",), state_path=tmp_path,
    ), **overrides)
    provider, publisher = FakeProvider(), FakePublisher()
    producer = EmailEventProducer(settings, {"owner", "other"}, provider, publisher)
    return settings, provider, publisher, producer


def cursor_for(producer, account="bound-account"):
    return producer.store.read(_key("owner", account, producer.settings.mailbox))


def test_disabled_by_default_and_explicit_owner_accounts(tmp_path):
    runtime = SimpleNamespace(
        authorized_usernames={"owner"}, development_no_auth=False, storage_path=str(tmp_path / "oauth")
    )
    assert EventSettings.from_env(runtime, {}).enabled is False
    base = {
        "EMAIL_EVENTS_ENABLED": "true", "EMAIL_EVENTS_OWNER": "owner",
        "EMAIL_EVENTS_ACCOUNTS_JSON": '["bound-account"]',
    }
    settings = EventSettings.from_env(runtime, base)
    assert settings.owner == "owner" and settings.accounts == ("bound-account",)
    assert settings.state_path == tmp_path / "email-events"
    for changes in (
        {"EMAIL_EVENTS_OWNER": "stranger"},
        {"EMAIL_EVENTS_OWNER": ""},
        {"EMAIL_EVENTS_ACCOUNTS_JSON": "[]"},
        {"EMAIL_EVENTS_ACCOUNTS_JSON": '["*"]'},
        {"EMAIL_EVENTS_POLL_SECONDS": "0"},
        {"EMAIL_EVENTS_MAX_PER_HOUR": "9999"},
        {"EMAIL_EVENTS_RULES_JSON": '{"priority_senders":"not-a-list"}'},
    ):
        with pytest.raises(ValueError):
            EventSettings.from_env(runtime, {**base, **changes})
    runtime.development_no_auth = True
    with pytest.raises(ValueError):
        EventSettings.from_env(runtime, base)


async def test_baseline_restart_and_uid_epoch_change(tmp_path):
    settings, provider, publisher, producer = setup(tmp_path)
    provider.messages = (mail(2), mail(9))
    assert (await producer.poll_once(now=100))["baselines"] == 1
    assert cursor_for(producer).last_uid == 9
    assert not publisher.records
    provider.state = MailState("identity", 1, 11)
    provider.messages = (mail(10),)
    assert (await producer.poll_once(now=101))["published"] == 1
    restarted = EmailEventProducer(settings, {"owner"}, provider, publisher)
    assert (await restarted.poll_once(now=102))["published"] == 0
    provider.state = MailState("identity", 2, 4)
    provider.messages = (mail(1), mail(3))
    assert (await restarted.poll_once(now=103))["baselines"] == 1
    assert len(publisher.records) == 1
    provider.state = MailState("identity", 2, 5)
    provider.messages = (mail(4),)
    assert (await restarted.poll_once(now=104))["published"] == 1
    assert len(publisher.records) == 2
    provider.state = MailState("rebound-account", 2, 7)
    provider.messages = (mail(6),)
    assert (await restarted.poll_once(now=105))["baselines"] == 1
    assert len(publisher.records) == 2


async def test_provider_and_publish_failures_retain_cursor(tmp_path, caplog):
    _, provider, publisher, producer = setup(tmp_path)
    await producer.poll_once(now=100)
    provider.state = MailState("identity", 1, 11)
    provider.messages = (mail(10),)
    provider.error = True
    assert (await producer.poll_once(now=101))["errors"] == 1
    assert cursor_for(producer).last_uid == 9
    assert "provider detail" not in caplog.text
    provider.error = False
    publisher.error = True
    assert (await producer.poll_once(now=102))["errors"] == 1
    assert cursor_for(producer).last_uid == 9
    publisher.error = False
    assert (await producer.poll_once(now=103))["published"] == 1
    assert publisher.calls[0] == publisher.calls[1]
    assert cursor_for(producer).last_uid == 10


async def test_publish_success_then_cursor_failure_is_deduplicated(tmp_path, monkeypatch):
    _, provider, publisher, producer = setup(tmp_path)
    await producer.poll_once(now=100)
    provider.state = MailState("identity", 1, 11)
    provider.messages = (mail(10),)
    original = producer.store.save

    def fail_before_cursor(namespace, cursor, publication=None):
        if publication is not None:
            raise OSError("simulated crash")
        return original(namespace, cursor, publication)

    monkeypatch.setattr(producer.store, "save", fail_before_cursor)
    assert (await producer.poll_once(now=101))["errors"] == 1
    assert cursor_for(producer).last_uid == 9
    monkeypatch.setattr(producer.store, "save", original)
    await producer.poll_once(now=102)
    assert len(publisher.records) == 1
    assert cursor_for(producer).last_uid == 10
    assert producer.store.counts(_key("owner"), 102) == (1, 0)


@pytest.mark.parametrize(("headers", "expected"), [
    ({}, "direct_personal"),
    ({"subject": "Please reply: decision"}, "action_required"),
    ({"subject": "Unusual login", "from": "noreply@sender.invalid"}, "security_alert"),
    ({"subject": "Newsletter promotion"}, None),
    ({"list-id": "discussion", "subject": "Deadline"}, None),
    ({"list-unsubscribe": "<https://sender.invalid/unsubscribe>"}, None),
    ({"precedence": "bulk"}, None),
    ({"auto-submitted": "auto-generated"}, None),
    ({"from": "noreply@sender.invalid"}, None),
    ({"from": "owner@owner.invalid"}, None),
    ({"to": "other@owner.invalid"}, None),
    ({"to": "other@owner.invalid", "in-reply-to": "<thread>"}, "thread_reply_needs_review"),
    ({"from": "a@sender.invalid, b@sender.invalid"}, None),
])
def test_header_importance_rules(headers, expected):
    classification = ImportanceRules().classify(mail(10, **headers), ("owner@owner.invalid",))
    assert (classification[1][0] if classification else None) == expected


def test_configured_rules_and_junk_flags():
    rules = ImportanceRules.from_json(json.dumps({
        "priority_senders": ["boss@sender.invalid"],
        "blocked_senders": ["blocked@sender.invalid"],
        "recipient_aliases": ["alias@owner.invalid"],
        "include_direct_personal": True,
    }))
    assert rules.classify(mail(1, **{"from": "boss@sender.invalid", "to": "other@owner.invalid"}),
                          ("owner@owner.invalid",))[1] == ("configured_sender",)
    assert rules.classify(mail(1, **{"from": "blocked@sender.invalid", "subject": "Security alert"}),
                          ("owner@owner.invalid",)) is None
    assert rules.classify(mail(1, to="alias@owner.invalid"),
                          ("owner@owner.invalid",))[1] == ("direct_personal",)
    assert rules.classify(replace(mail(1), flags=("$Junk",)), ("owner@owner.invalid",)) is None


async def test_global_limit_is_persistent_and_important_is_deferred(tmp_path):
    settings, provider, publisher, producer = setup(
        tmp_path, accounts=("first", "second"), max_per_hour=1
    )
    await producer.poll_once(now=100)
    provider.state = MailState("identity", 1, 11)
    provider.messages = (mail(10),)
    result = await producer.poll_once(now=101)
    assert result["published"] == 1 and result["deferred"] == 1
    assert cursor_for(producer, "second").last_uid == 9
    restarted = EmailEventProducer(settings, {"owner"}, provider, publisher)
    assert (await restarted.poll_once(now=102))["deferred"] == 1
    # 第一账号持续有新信时，下一窗口仍优先服务上次未获额度的第二账号。
    provider.state = MailState("identity", 1, 12)
    provider.messages = (mail(10), mail(11))
    assert (await restarted.poll_once(now=3702))["published"] == 1
    assert len(publisher.records) == 2
    assert list(publisher.records.values())[-1][1]["account_name"] == "second"
    assert cursor_for(restarted, "first").last_uid == 10


async def test_review_limit_does_not_block_important_mail(tmp_path):
    _, provider, publisher, producer = setup(tmp_path, review_max_per_hour=0)
    await producer.poll_once(now=100)
    provider.state = MailState("identity", 1, 12)
    provider.messages = (
        mail(10, to="other@owner.invalid", **{"in-reply-to": "<thread>"}),
        mail(11, subject="Action required"),
    )
    result = await producer.poll_once(now=101)
    assert result["suppressed"] == 1 and result["published"] == 1
    assert cursor_for(producer).last_uid == 11


async def test_owner_binding_revocation_and_metadata_only(tmp_path):
    settings, provider, publisher, producer = setup(tmp_path)
    with pytest.raises(ValueError):
        EmailEventProducer(replace(settings, owner="stranger"), {"owner"}, provider, publisher)
    await producer.poll_once(now=100)
    provider.state = MailState("identity", 1, 11)
    provider.messages = (mail(10, body="must never enter the event"),)
    await producer.poll_once(now=101)
    name, payload, subject = next(iter(publisher.records.values()))
    assert name == EVENT_NAME and subject == "owner"
    assert "body" not in payload and payload["metadata_only"] is True
    assert provider.calls == [("bound-account", "INBOX")] * 2
    producer.authorized_usernames.clear()
    with pytest.raises(ValueError):
        await producer.poll_once(now=102)
    assert len(provider.calls) == 2
    calls = []
    register_email_event(SimpleNamespace(register_event=lambda *a, **kw: calls.append((a, kw))),
                         "owner")
    assert calls[0][1]["subjects"] == {"owner"}


def fetch_response(uid=10, raw=None, *, uid_after=False):
    raw = raw or b"From: sender@sender.invalid\r\nTo: owner@owner.invalid\r\nSubject: Hello\r\n\r\n"
    prefix = b"1 (FLAGS () " + (b"" if uid_after else f"UID {uid} ".encode())
    prefix += b"BODY[HEADER.FIELDS (FROM TO SUBJECT)]<0> {" + str(len(raw)).encode() + b"}"
    tail = (f" UID {uid})" if uid_after else ")").encode()
    return [prefix, bytearray(raw), tail]


@pytest.mark.parametrize("uid_after", [False, True])
def test_header_parser_bounded_and_missing_uid(uid_after):
    parsed = parse_header_fetch(fetch_response(uid_after=uid_after), {10})
    assert parsed[10].headers["subject"] == "Hello"
    with pytest.raises(ValueError):
        parse_header_fetch(fetch_response(), {10, 11})
    with pytest.raises(ValueError):
        parse_header_fetch(fetch_response(raw=b"x" * (MAX_HEADER_BYTES + 1)), {10})
    with pytest.raises(ValueError):
        parse_header_fetch(fetch_response() + fetch_response(), {10})


async def test_upstream_adapter_uses_examine_uid_and_header_peek_only():
    calls = []
    current = SimpleNamespace(uidvalidity=1, uidnext=10)

    class Imap:
        async def examine(self, mailbox):
            calls.append(("examine", mailbox))
            return "OK", []

        async def uid_search(self, *args, **kwargs):
            calls.append(("search", args, kwargs))
            return "OK", [b"10"]

        async def uid(self, *args):
            calls.append(("uid", args))
            return "OK", fetch_response()

        async def logout(self):
            calls.append(("logout",))

    imap = Imap()

    class Client:
        email_server = SimpleNamespace(
            user_name="fake", password=SimpleNamespace(get_secret_value=lambda: "fake")
        )

        async def _connect_imap(self):
            return imap

        async def _status_mailbox(self, imap, mailbox):
            calls.append(("status", mailbox))
            return current

    async def login(*args):
        pass

    def check(response, _):
        assert response[0] == "OK"

    access = ProviderAccess(Client(), "identity", ("owner@owner.invalid",), ())
    protocol = SimpleNamespace(
        login=login, send_id=login, quote=lambda name: '"' + name + '"', check=check,
        normalize=lambda data: data[0].decode().split(),
        sender_allowed=lambda sender, patterns: not patterns or sender in patterns,
    )
    adapter = UpstreamHeaderProvider(access_factory=lambda _: access, protocol=protocol)
    initial = await adapter.observe("bound-account", "INBOX", None, 50)
    assert initial.messages == () and initial.through_uid == 9
    assert calls == [("status", "INBOX"), ("logout",)]
    calls.clear()
    current = SimpleNamespace(uidvalidity=1, uidnext=11)
    observed = await adapter.observe("bound-account", "INBOX", Cursor("identity", 1, 9), 50)
    assert [m.uid for m in observed.messages] == [10]
    assert ("examine", '"INBOX"') in calls
    assert ("search", ("UID", "10:10"), {"charset": None}) in calls
    assert ("uid", ("fetch", "10", FETCH_HEADERS)) in calls
    assert "BODY.PEEK[HEADER.FIELDS" in FETCH_HEADERS
    assert "RFC822" not in FETCH_HEADERS and "BODY[]" not in FETCH_HEADERS
    access = replace(access, allowed_senders=("different@sender.invalid",))
    observed = await adapter.observe("bound-account", "INBOX", Cursor("identity", 1, 9), 50)
    assert observed.messages == () and observed.through_uid == 10


async def test_real_event_service_encrypted_queue_owner_scope_and_fake_delivery(tmp_path):
    import base64

    from pydantic import SecretStr

    from mcp_platform import RuntimeConfig
    from mcp_platform.events import EventError, EventService

    deliveries = []

    class Transport:
        async def post(self, url, body, headers):
            value = json.loads(body)
            if value.get("type") == "verification":
                response = {"challenge": value["challenge"]}
            else:
                deliveries.append((url, value))
                response = {}
            return SimpleNamespace(status=200, body=json.dumps(response).encode())

    config = RuntimeConfig(
        name="email-events-test", development_no_auth=True, authorized_usernames={"owner", "other"},
        storage_path=str(tmp_path / "oauth"), storage_encryption_key=SecretStr("test-key-" * 8),
        jwt_signing_key=SecretStr("test-signing-" * 8),
    )
    service = EventService(config, storage_path=tmp_path / "deliveries", transport=Transport())
    register_email_event(service, "owner")
    assert service.list_events("other") == {"events": []}
    params = {
        "name": EVENT_NAME, "arguments": {},
        "delivery": {"mode": "webhook", "url": "https://callback.example.invalid/email",
                     "secret": "whsec_" + base64.b64encode(b"t" * 32).decode()},
    }
    with pytest.raises(EventError):
        await service.subscribe("other", params)
    await service.subscribe("owner", params)
    settings, provider, _, _ = setup(tmp_path / "producer")
    producer = EmailEventProducer(settings, {"owner"}, provider, service)
    await producer.poll_once(now=100)
    provider.state = MailState("identity", 1, 11)
    provider.messages = (mail(10),)
    assert (await producer.poll_once(now=101))["published"] == 1
    assert (await service.status())["pending"] == 1
    assert deliveries == []
    assert (await service.run_delivery_once())["accepted"] == 1
    assert len(deliveries) == 1
    assert deliveries[0][1]["data"]["email_id"] == "10"
    assert deliveries[0][1]["data"]["metadata_only"] is True
    restored = EventService(config, storage_path=tmp_path / "deliveries", transport=Transport())
    register_email_event(restored, "owner")
    restarted = EmailEventProducer(settings, {"owner"}, provider, restored)
    await restarted.poll_once(now=102)
    assert (await restored.run_delivery_once())["accepted"] == 0
    assert len(deliveries) == 1
    for path in (tmp_path / "deliveries").rglob("*"):
        if path.is_file():
            assert b"sender@sender.invalid" not in path.read_bytes()


async def test_server_wires_public_events_and_cancels_both_workers(tmp_path, monkeypatch):
    import asyncio
    from types import ModuleType

    import email_mcp_platform.server as server_module
    from pydantic import SecretStr

    from mcp_platform import RuntimeConfig
    from mcp_platform.events import EventService

    upstream = ModuleType("mcp_email_server.app")
    upstream.mcp = object()
    runtime = ModuleType("mcp_email_server.runtime")
    runtime.get_application_runtime = lambda: SimpleNamespace(management=SimpleNamespace(
        legacy_compatibility=SimpleNamespace(validate_runtime=lambda: None)
    ))
    monkeypatch.setitem(sys.modules, "mcp_email_server.app", upstream)
    monkeypatch.setitem(sys.modules, "mcp_email_server.runtime", runtime)
    monkeypatch.setattr(server_module, "version", lambda _: "1.11.0")
    captured, started, stopped = {}, [asyncio.Event(), asyncio.Event()], []

    async def delivery_worker(self):
        started[0].set()
        try:
            await asyncio.Future()
        finally:
            stopped.append("delivery")

    async def producer_worker(self):
        started[1].set()
        try:
            await asyncio.Future()
        finally:
            stopped.append("producer")

    def create_server(config, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(mount=lambda _: None, add_middleware=lambda _: None)

    def create_app(server, config, *, events):
        captured["events"] = events
        return SimpleNamespace(state=SimpleNamespace())

    monkeypatch.setattr(EventService, "serve", delivery_worker)
    monkeypatch.setattr(EmailEventProducer, "serve", producer_worker)
    monkeypatch.setattr(server_module, "create_server", create_server)
    monkeypatch.setattr(server_module, "create_proxy", lambda _: object())
    monkeypatch.setattr(server_module, "create_http_app", create_app)
    monkeypatch.setenv("EMAIL_EVENTS_ENABLED", "true")
    monkeypatch.setenv("EMAIL_EVENTS_OWNER", "owner")
    monkeypatch.setenv("EMAIL_EVENTS_ACCOUNTS_JSON", '["bound-account"]')
    monkeypatch.setenv("EMAIL_EVENTS_STATE_PATH", str(tmp_path / "producer"))
    config = RuntimeConfig.model_construct(
        name="test", development_no_auth=False, authorized_usernames={"owner"},
        storage_path=str(tmp_path / "oauth"), storage_encryption_key=SecretStr("test-key-" * 8),
        jwt_signing_key=SecretStr("test-signing-" * 8),
    )
    app, server, _ = server_module.create_app(config)
    assert app.state.email_events is captured["events"]
    assert app.state.email_event_producer.settings.owner == "owner"
    async with captured["lifespan"](server):
        async with asyncio.timeout(2):
            await asyncio.gather(*(event.wait() for event in started))
    assert set(stopped) == {"producer", "delivery"}


@pytest.mark.parametrize("fault", ["oversized", "incomplete"])
async def test_oversized_header_is_isolated_but_transient_incomplete_fetch_is_retained(tmp_path, fault):
    state = SimpleNamespace(uidvalidity=1, uidnext=10)
    fetches = []

    class Imap:
        async def examine(self, mailbox):
            return "OK", []

        async def uid_search(self, *args, **kwargs):
            low, high = map(int, args[-1].split(":"))
            return "OK", [" ".join(str(uid) for uid in (10, 11) if low <= uid <= high).encode()]

        async def uid(self, command, uids, fields):
            fetches.append((uids, fields))
            data = []
            for uid in map(int, uids.split(",")):
                if uid == 10:
                    if fault == "incomplete":
                        continue
                    data.extend(fetch_response(uid, raw=b"x" * (MAX_HEADER_BYTES + 1)))
                else:
                    data.extend(fetch_response(uid))
            return "OK", data

        async def logout(self):
            pass

    imap = Imap()

    class Client:
        email_server = SimpleNamespace(
            user_name="fake", password=SimpleNamespace(get_secret_value=lambda: "fake")
        )

        async def _connect_imap(self):
            return imap

        async def _status_mailbox(self, imap, mailbox):
            return state

    async def noop(*args):
        pass

    def check(response, _):
        assert response[0] == "OK"

    access = ProviderAccess(Client(), "identity", ("owner@owner.invalid",), ())
    protocol = SimpleNamespace(
        login=noop, send_id=noop, quote=lambda name: '"' + name + '"', check=check,
        normalize=lambda data: data[0].decode().split(),
        sender_allowed=lambda sender, patterns: not patterns or sender in patterns,
    )
    adapter = UpstreamHeaderProvider(access_factory=lambda _: access, protocol=protocol)
    settings, _, publisher, _ = setup(tmp_path, review_max_per_hour=0)
    producer = EmailEventProducer(settings, {"owner"}, adapter, publisher)
    await producer.poll_once(now=100)
    state = SimpleNamespace(uidvalidity=1, uidnext=12)
    result = await producer.poll_once(now=101)
    if fault == "incomplete":
        assert result["errors"] == 1
        assert cursor_for(producer).last_uid == 9
        assert producer.store.header_failure_count() == 0
        assert len(fetches) == 1
        assert not publisher.records
    else:
        assert result["published"] == 1 and result["suppressed"] == 1
        assert cursor_for(producer).last_uid == 11
        assert producer.store.header_failure_count() == 1
        assert list(publisher.records.values())[0][1]["email_id"] == "11"
        assert len(fetches) == 3  # 一个批量请求，只对该批次做一次单 UID 降级。
        access = replace(access, allowed_senders=("sender@sender.invalid",))
        observation = await adapter.observe(
            "bound-account", "INBOX", Cursor("identity", 1, 9), 50
        )
        assert [message.uid for message in observation.messages] == [11]
        assert observation.metadata_failures == ((10, "header_too_large"),)
