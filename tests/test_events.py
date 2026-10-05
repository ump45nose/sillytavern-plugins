import asyncio
import base64
import json

import httpx
import pytest
from fastmcp.server.auth import AccessToken, TokenVerifier

from mcp_platform.auth import authorize
from mcp_platform.config import RuntimeConfig
from mcp_platform.events import (
    MAX_BODY_BYTES,
    META_CAPABILITIES,
    META_VERSION,
    PROTOCOL_VERSION,
    EventError,
    EventService,
    WebhookResponse,
    resolve_public_addresses,
    validate_callback_url,
    webhook_signature,
)
from mcp_platform.runtime import create_http_app, create_server

SECRET = "whsec_" + base64.b64encode(bytes(range(32))).decode()
CALLBACK = "https://callback.example.com/mcp-event"


class Clock:
    def __init__(self):
        self.now = 1_800_000_000

    def __call__(self):
        return self.now


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.statuses = []
        self.valid_challenge = True

    async def post(self, url, body, headers):
        self.calls.append((url, body, headers))
        data = json.loads(body)
        if data.get("type") == "verification":
            return WebhookResponse(200, json.dumps({"challenge": data["challenge"] if self.valid_challenge else "wrong"}).encode())
        return WebhookResponse(self.statuses.pop(0) if self.statuses else 202)


@pytest.fixture
def config(tmp_path):
    return RuntimeConfig(
        name="event-tests", public_base_url="https://events.example.com",
        oidc_discovery_url="https://identity.example.com/.well-known/openid-configuration",
        oidc_client_id="test", oidc_client_secret="test",
        jwt_signing_key="signing-material-" * 4, storage_encryption_key="storage-material-" * 4,
        storage_path=str(tmp_path / "oauth"), authorized_usernames={"alice", "bob"},
        read_only_usernames={"bob"}, audit_enabled=False,
    )


def service(config, transport=None, clock=None, **kwargs):
    events = EventService(config, transport=transport or FakeTransport(), clock=clock or Clock(), **kwargs)
    events.register_event(
        "report.ready", "报告已就绪", {"type": "object", "properties": {"kind": {"type": "string"}}, "additionalProperties": False},
        {"type": "object", "properties": {"kind": {"type": "string"}, "report_id": {"type": "string"}}, "required": ["kind", "report_id"], "additionalProperties": False},
    )
    return events


def params(secret=SECRET, **extra):
    return {"name": "report.ready", "arguments": {},
            "delivery": {"mode": "webhook", "url": CALLBACK, "secret": secret}, **extra}


def test_standard_webhooks_known_signature():
    assert webhook_signature(SECRET, "evt_fixture", 1700000000, b'{"data":"hello"}') == "v1,dEnL0TxePEfdV6/L3GTJCUVIoI681szTSmHAXqXQEfs="


@pytest.mark.parametrize("url", ["http://callback.example.com/x", "https://127.0.0.1/x", "https://[::1]/x", "https://169.254.169.254/x", "https://u:p@callback.example.com/x", "https://localhost/x", "https://callback.example.com/x#secret"])
def test_callback_rejects_nonpublic_or_ambiguous_urls(url):
    with pytest.raises(EventError):
        validate_callback_url(url)


async def test_dns_rebinding_mixed_answers_rejected(monkeypatch):
    async def answers(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", answers)
    with pytest.raises(EventError, match="address rejected"):
        await resolve_public_addresses("callback.example.com", 443)


async def test_verification_filters_owner_and_durable_duplicate(config):
    transport, clock = FakeTransport(), Clock()
    events = service(config, transport, clock)
    subscription = await events.subscribe("alice", params(arguments={"kind": "daily"}))
    assert subscription["id"].startswith("sub_")
    assert len(transport.calls) == 1
    first = await events.publish("report.ready", {"kind": "daily", "report_id": "r1"}, subject="alice", event_id="report:1")
    assert first["queued"] == 1
    assert len(transport.calls) == 1, "publish must not perform network delivery"
    other = await events.publish("report.ready", {"kind": "daily", "report_id": "r1"}, subject="bob", event_id="report:1")
    assert other["queued"] == 0
    filtered = await events.publish("report.ready", {"kind": "hourly", "report_id": "r2"}, subject="alice", event_id="report:2")
    assert filtered["queued"] == 0
    restarted = service(config, transport, clock)
    result = await restarted.publish("report.ready", {"report_id": "r1", "kind": "daily"}, subject="alice", event_id="report:1")
    assert result["duplicate"]
    assert result["event_id"] == first["event_id"]
    assert (await restarted.run_delivery_once())["accepted"] == 1
    sent = json.loads(transport.calls[-1][1])
    assert sent["data"] == {"kind": "daily", "report_id": "r1"}
    assert sent["eventId"] == transport.calls[-1][2]["webhook-id"]
    persisted = b"".join(p.read_bytes() for p in events.directory.rglob("*.json"))
    assert SECRET.encode() not in persisted and CALLBACK.encode() not in persisted


async def test_failed_verification_and_invalid_schema_do_not_subscribe(config):
    transport = FakeTransport()
    transport.valid_challenge = False
    events = service(config, transport)
    with pytest.raises(EventError, match="verification failed"):
        await events.subscribe("alice", params())
    assert (await events.status())["subscriptions"] == 0
    for invalid in (params(secret="bad"), params(arguments={"unexpected": True})):
        with pytest.raises(EventError):
            await events.subscribe("alice", invalid)
    assert len(transport.calls) == 1
    with pytest.raises(EventError):
        await events.subscribe("mallory", params())


async def test_refresh_rotation_and_unsubscribe(config):
    transport, clock = FakeTransport(), Clock()
    events = service(config, transport, clock)
    original = await events.subscribe("alice", params(ttlMs=60000))
    clock.now += 10
    changed = "whsec_" + base64.b64encode(b"b" * 32).decode()
    refreshed = await events.subscribe("alice", params(secret=changed, ttlMs=120000))
    assert refreshed["id"] == original["id"]
    assert refreshed["refreshBefore"] > original["refreshBefore"]
    assert len(transport.calls) == 1
    await events.publish("report.ready", {"kind": "daily", "report_id": "r1"}, subject="alice", event_id="r1")
    await events.run_delivery_once()
    assert len(transport.calls[-1][2]["webhook-signature"].split()) == 2
    await events.publish("report.ready", {"kind": "daily", "report_id": "r2"}, subject="alice", event_id="r2")
    await events.unsubscribe("alice", params())
    await events.unsubscribe("alice", params())
    before = len(transport.calls)
    await events.run_delivery_once()
    assert len(transport.calls) == before
    assert (await events.status())["subscriptions"] == 0


async def test_retry_and_lease_survive_restart(config):
    transport, clock = FakeTransport(), Clock()
    transport.statuses = [503, 202]
    events = service(config, transport, clock)
    await events.subscribe("alice", params())
    await events.publish("report.ready", {"kind": "daily", "report_id": "r1"}, subject="alice", event_id="r1")
    assert (await events.run_delivery_once())["retry"] == 1
    first_headers = transport.calls[-1][2]
    restarted = service(config, transport, clock)
    assert (await restarted.run_delivery_once())["accepted"] == 0
    clock.now += 31
    assert (await restarted.run_delivery_once())["accepted"] == 1
    second_headers = transport.calls[-1][2]
    assert first_headers["webhook-id"] == second_headers["webhook-id"]
    assert first_headers["webhook-timestamp"] != second_headers["webhook-timestamp"]
    assert first_headers["webhook-signature"] != second_headers["webhook-signature"]


@pytest.mark.parametrize("status", [410, 413])
async def test_permanent_failures_are_not_retried(config, status):
    transport, clock = FakeTransport(), Clock()
    transport.statuses = [status]
    events = service(config, transport, clock)
    await events.subscribe("alice", params())
    await events.publish("report.ready", {"kind": "daily", "report_id": "r1"}, subject="alice", event_id="r1")
    assert (await events.run_delivery_once())["stopped"] == 1
    before = len(transport.calls)
    clock.now += 3601
    await events.run_delivery_once()
    assert len(transport.calls) == before
    if status == 410:
        assert (await events.status())["subscriptions"] == 0


async def test_subject_revocation_stops_pending_delivery(config):
    transport = FakeTransport()
    events = service(config, transport)
    await events.subscribe("alice", params())
    await events.publish("report.ready", {"kind": "daily", "report_id": "r1"}, subject="alice", event_id="r1")
    config.authorized_usernames.remove("alice")
    assert (await events.run_delivery_once())["stopped"] == 1
    assert len(transport.calls) == 1


async def test_concurrent_producers_and_payload_limits(config):
    events, other = service(config), service(config)
    results = await asyncio.gather(*[(events if i % 2 else other).publish("report.ready", {"kind": "daily", "report_id": "r1"}, subject="alice", event_id="r1") for i in range(6)])
    assert sum(not r["duplicate"] for r in results) == 1
    with pytest.raises(ValueError, match="different data"):
        await events.publish("report.ready", {"kind": "daily", "report_id": "changed"}, subject="alice", event_id="r1")
    with pytest.raises(ValueError, match="256 KiB"):
        await events.publish("report.ready", {"kind": "daily", "report_id": "中" * MAX_BODY_BYTES}, subject="alice", event_id="huge")


class TestVerifier(TokenVerifier):
    __test__ = False

    async def verify_token(self, token):
        if token not in {"alice-token", "bob-token", "mallory-token"}:
            return None
        return AccessToken(token=token, client_id="tests", scopes=[],
                           claims={"sub": "opaque-subject", "preferred_username": token[:-6]})


def rpc(method, arguments=None, id=1):
    p = {"_meta": {META_VERSION: PROTOCOL_VERSION, META_CAPABILITIES: {}}}
    p.update(arguments or {})
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": p}


def headers(method, token="alice-token", name=None):
    h = {"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": method,
         "Accept": "application/json, text/event-stream"}
    if token:
        h["Authorization"] = "Bearer " + token
    if name:
        h["Mcp-Name"] = name
    return h


def response_json(response):
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        return [message for message in data if "result" in message or "error" in message][-1]
    return response.json()


async def test_authenticated_mcp2_and_legacy_tools_keep_permissions(config, monkeypatch):
    monkeypatch.setattr("mcp_platform.runtime.build_provider", lambda cfg: (TestVerifier(), None))
    events = service(config)
    server = create_server(config)
    writes = []

    @server.tool
    def read_subject() -> str:
        return events.authenticated_subject()

    @server.tool(auth=authorize("write", config))
    def write_record() -> str:
        writes.append(True)
        return "written"

    app = create_http_app(server, config, events=events)
    async with app.lifespan(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://events.example.com") as client:
            anonymous = await client.post("/mcp", json=rpc("server/discover"), headers=headers("server/discover", token=None))
            assert anonymous.status_code == 401
            denied = await client.post("/mcp", json=rpc("events/list"), headers=headers("events/list", token="mallory-token"))
            assert denied.status_code == 403
            discovered = await client.post("/mcp", json=rpc("server/discover"), headers=headers("server/discover"))
            assert discovered.status_code == 200
            assert discovered.json()["result"]["capabilities"]["events"] == {}
            listed = await client.post("/mcp", json=rpc("tools/list"), headers=headers("tools/list", token="bob-token"))
            tools = response_json(listed)["result"]
            assert tools["resultType"] == "complete"
            assert [t["name"] for t in tools["tools"]] == ["read_subject"]
            called = await client.post("/mcp", json=rpc("tools/call", {"name": "read_subject", "arguments": {}}), headers=headers("tools/call", name="read_subject"))
            result = response_json(called)["result"]
            assert result["resultType"] == "complete" and result["content"][0]["text"] == "alice"
            blocked = await client.post("/mcp", json=rpc("tools/call", {"name": "write_record", "arguments": {}}), headers=headers("tools/call", token="bob-token", name="write_record"))
            assert response_json(blocked).get("error") or response_json(blocked).get("result", {}).get("isError")
            assert writes == []
            mismatched = await client.post("/mcp", json=rpc("tools/call", {"name": "write_record", "arguments": {}}), headers=headers("tools/call", name="read_subject"))
            assert mismatched.status_code == 400 and mismatched.json()["error"]["code"] == -32020
            legacy = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}}, headers={"Authorization": "Bearer alice-token", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"})
            assert "resultType" not in response_json(legacy)["result"]
            initialized = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "legacy", "version": "1"}}}, headers={"Authorization": "Bearer alice-token", "Accept": "application/json, text/event-stream"})
            assert response_json(initialized)["result"]["protocolVersion"] == "2025-11-25"
