"""MCP Events on the existing authenticated endpoint, with a durable webhook queue.

The installed MCP 1.x SDK still handles legacy traffic and tool execution.  The
opt-in ASGI adapter implements the 2026-07-28 request envelope and Events methods;
it never replaces the bearer-token or component authorization middleware.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import fcntl
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpcore
from fastmcp.server.dependencies import get_access_token
from httpcore._backends.auto import AutoBackend
from jsonschema import Draft202012Validator, ValidationError
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import authorize, claims

PROTOCOL_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
MAX_BODY_BYTES = 256 * 1024
_LOG = logging.getLogger("mcp_platform.events")
_DIAGNOSTIC_LOG = logging.getLogger("mcp_platform.audit.events")
_DIAGNOSTIC_METHODS = frozenset({
    "initialize", "notifications/initialized", "server/discover", "tools/list", "tools/call",
    "events/list", "events/subscribe", "events/unsubscribe",
})
_DIAGNOSTIC_VERSIONS = frozenset({
    "2024-11-05", "2025-03-26", "2025-06-18", LEGACY_VERSION, PROTOCOL_VERSION,
})
_NETWORK_ERRORS = (OSError, TimeoutError, httpcore.NetworkError, httpcore.TimeoutException,
                   httpcore.ProtocolError, httpcore.ProxyError)


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _event_time(value, now):
    if value is None:
        return _iso(now)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Event timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class EventError(Exception):
    def __init__(self, code, message, *, status=400, data=None):
        super().__init__(message)
        self.code, self.message, self.status, self.data = code, message, status, data


def _secret_bytes(secret: str) -> bytes:
    if not isinstance(secret, str) or not secret.startswith("whsec_"):
        raise EventError(-32602, "Invalid webhook signing secret")
    try:
        decoded = base64.b64decode(secret[6:], validate=True)
    except (ValueError, binascii.Error):
        raise EventError(-32602, "Invalid webhook signing secret") from None
    if not 24 <= len(decoded) <= 64:
        raise EventError(-32602, "Invalid webhook signing secret")
    return decoded


def webhook_signature(secret: str, event_id: str, signed_at: int, body: bytes) -> str:
    """Standard Webhooks v1 HMAC over the exact bytes sent on the wire."""
    message = event_id.encode("ascii") + b"." + str(signed_at).encode() + b"." + body
    digest = hmac.new(_secret_bytes(secret), message, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode("ascii")


def validate_callback_url(url: str):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise EventError(-32602, "Invalid callback URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
    except ValueError:
        raise EventError(-32602, "Invalid callback URL") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or not 1 <= port <= 65535):
        raise EventError(-32602, "Callback requires an HTTPS URL without credentials")
    host = parsed.hostname
    if host.endswith("."):
        host = host[:-1]
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise EventError(-32602, "Callback must use a public address")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _public_address(address):
            raise EventError(-32602, "Callback must use a public address")
    return parsed


def _public_address(address):
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_global and not address.is_multicast and (mapped is None or mapped.is_global)


async def resolve_public_addresses(host: str, port: int) -> list[str]:
    results = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(item[4][0] for item in results))
    if not addresses or any(not _public_address(ipaddress.ip_address(a)) for a in addresses):
        raise EventError(-32015, "Callback address rejected", data={"reason": "invalid_address"})
    return addresses


class _PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """Pin DNS results at connect time; optional trusted proxy tunnels to that IP."""

    def __init__(self, proxy_url=None):
        self.backend = AutoBackend()
        self.proxy = None
        if proxy_url:
            p = urlsplit(proxy_url)
            if p.scheme != "http" or not p.hostname or p.path not in ("", "/") or p.query or p.fragment:
                raise ValueError("MCP_EVENTS_HTTPS_PROXY must be a trusted HTTP proxy URL")
            self.proxy = p

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        addresses = await resolve_public_addresses(host, port)
        last_error = None
        for address in addresses:
            stream = None
            try:
                target_host = self.proxy.hostname if self.proxy else address
                target_port = (self.proxy.port or 80) if self.proxy else port
                stream = await self.backend.connect_tcp(
                    target_host, target_port, timeout=timeout, local_address=local_address,
                    socket_options=socket_options,
                )
                if self.proxy:
                    authority = f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
                    headers = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
                    if self.proxy.username is not None:
                        from urllib.parse import unquote
                        credential = unquote(self.proxy.username) + ":" + unquote(self.proxy.password or "")
                        headers += "Proxy-Authorization: Basic " + base64.b64encode(credential.encode()).decode() + "\r\n"
                    await stream.write((headers + "\r\n").encode("ascii"), timeout=timeout)
                    response = b""
                    while b"\r\n\r\n" not in response:
                        part = await stream.read(4096, timeout=timeout)
                        if not part or len(response) + len(part) > 16384:
                            raise httpcore.ProxyError("Proxy CONNECT failed")
                        response += part
                    if response.split(b" ", 2)[1:2] != [b"200"]:
                        raise httpcore.ProxyError("Proxy CONNECT rejected")
                return stream
            except (OSError, httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProxyError) as exc:
                last_error = exc
                if stream is not None:
                    await stream.aclose()
        raise httpcore.ConnectError("Callback connection failed") from last_error

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("Unix sockets are not permitted for callbacks")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


@dataclass
class WebhookResponse:
    status: int
    body: bytes = b""


class SecureWebhookTransport:
    def __init__(self, proxy_url=None):
        self.backend = _PublicNetworkBackend(proxy_url)

    async def post(self, url: str, body: bytes, headers: dict) -> WebhookResponse:
        validate_callback_url(url)
        # A new pool for every attempt prevents reusing a connection after DNS/access changes.
        async with httpcore.AsyncConnectionPool(network_backend=self.backend, retries=0) as pool:
            async with asyncio.timeout(10):
                async with pool.stream("POST", url, headers=headers, content=body,
                                       extensions={"timeout": {"connect": 5, "read": 5, "write": 5, "pool": 5}}) as response:
                    chunks = bytearray()
                    async for part in response.aiter_stream():
                        chunks.extend(part)
                        if len(chunks) > 16384:
                            raise EventError(-32015, "Callback response too large",
                                             data={"reason": "response_too_large"})
                    return WebhookResponse(response.status, bytes(chunks))


@dataclass
class _Definition:
    name: str
    description: str
    input_schema: dict
    payload_schema: dict
    filter_fn: object
    subjects: set[str] | None


class EventService:
    """Per-service event catalog and encrypted, atomically saved subscription/outbox state.

    ``subject`` is the existing authorized OIDC preferred_username, never payload
    data. ``publish`` only persists; ``serve`` performs delivery. Producers may
    safely retry an identical event_id/data pair. No events are replayed to a new
    subscription; interrupted delivery to an existing subscription is retained.
    """

    def __init__(self, config, *, storage_path=None, transport=None, clock=time.time,
                 retention_days=30, max_events=10000, max_subscriptions=128,
                 max_outbox=20000, max_attempts=8):
        self.config, self.clock = config, clock
        self.directory = Path(storage_path or (Path(config.storage_path).parent / "events"))
        if self.directory.is_symlink():
            raise ValueError("Event storage must not be a symlink")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        raw = FileTreeStore(data_directory=self.directory / "records")
        material = config.storage_encryption_key.get_secret_value()
        if not material:
            raise ValueError("Event storage requires a persistent encryption key")
        self.store = FernetEncryptionWrapper(raw, source_material=material,
                                            salt=config.storage_salt + "-events-v1",
                                            raise_on_decryption_error=True)
        self.transport = transport or SecureWebhookTransport(os.getenv("MCP_EVENTS_HTTPS_PROXY"))
        self.retention = int(retention_days * 86400)
        self.max_events, self.max_subscriptions = max_events, max_subscriptions
        self.max_outbox, self.max_attempts = max_outbox, max_attempts
        self._definitions = {}
        self._local_lock = asyncio.Lock()
        self._wake = asyncio.Event()

    def register_event(self, name, description, input_schema, payload_schema, filter_fn=None,
                       *, subjects=None):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
            raise ValueError("Invalid event name")
        if name in self._definitions:
            raise ValueError("Event already registered")
        for schema in (input_schema, payload_schema):
            Draft202012Validator.check_schema(schema)
            if schema.get("type") != "object":
                raise ValueError("Event schemas must describe objects")
            def check_refs(value):
                if isinstance(value, dict):
                    if "$ref" in value and not str(value["$ref"]).startswith("#"):
                        raise ValueError("External schema references are not allowed")
                    for child in value.values():
                        check_refs(child)
                elif isinstance(value, list):
                    for child in value:
                        check_refs(child)
            check_refs(schema)
        self._definitions[name] = _Definition(
            name, description, json.loads(_json(input_schema)), json.loads(_json(payload_schema)),
            filter_fn or (lambda arguments, data: all(data.get(k) == v for k, v in arguments.items())),
            set(subjects) if subjects is not None else None,
        )

    def _check_subject(self, subject):
        if (not isinstance(subject, str) or not subject
                or not any(hmac.compare_digest(subject.encode(), u.encode())
                           for u in self.config.authorized_usernames)):
            raise EventError(-32001, "Event access denied", status=403)
        return subject

    def authenticated_subject(self):
        token = get_access_token()
        subject = claims(token).get("preferred_username")
        check = authorize("read", self.config)
        if token is None or (check is not None and not check(SimpleNamespace(token=token))):
            raise EventError(-32001, "Event access denied", status=403)
        return self._check_subject(subject)

    def _definition(self, name, subject):
        self._check_subject(subject)
        definition = self._definitions.get(name)
        if definition is None or (definition.subjects is not None and subject not in definition.subjects):
            raise EventError(-32602, "Unknown or unavailable event")
        return definition

    @staticmethod
    def _validate(schema, value):
        try:
            Draft202012Validator(schema).validate(value)
        except ValidationError:
            raise EventError(-32602, "Event arguments or payload do not match the schema") from None

    @asynccontextmanager
    async def _state(self):
        async with self._local_lock:
            fd = os.open(self.directory / "state.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            acquired = False
            try:
                # Nonblocking acquisition keeps cancellation from leaking a thread-held lock.
                while not acquired:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except BlockingIOError:
                        await asyncio.sleep(0.02)
                state = await self.store.get("state", collection="mcp-events-v1")
                if state is None:
                    state = {"version": 1, "subscriptions": {}, "events": {}, "outbox": {}}
                if state.get("version") != 1:
                    raise ValueError("Unsupported event storage version")
                yield state
                if len(_json(state)) > 32 * 1024 * 1024:
                    raise EventError(-32000, "Event storage capacity reached", status=503)
                await self.store.put("state", state, collection="mcp-events-v1")
            finally:
                if acquired:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _prune(self, state, now):
        for subscription in state["subscriptions"].values():
            if subscription["expires_at"] <= now:
                subscription["active"] = False
        for key, job in list(state["outbox"].items()):
            if job["status"] != "pending" and job["updated_at"] < now - self.retention:
                del state["outbox"][key]
        retained = {job["event_key"] for job in state["outbox"].values()}
        for key, event in list(state["events"].items()):
            if key not in retained and event["created_at"] < now - self.retention:
                del state["events"][key]
        for key, subscription in list(state["subscriptions"].items()):
            if not subscription["active"] and subscription["expires_at"] < now - self.retention:
                del state["subscriptions"][key]

    def list_events(self, subject, cursor=None):
        self._check_subject(subject)
        if cursor not in (None, ""):
            raise EventError(-32602, "Invalid event catalog cursor")
        return {"events": [{"name": d.name, "description": d.description, "delivery": ["webhook"],
                            "inputSchema": d.input_schema, "payloadSchema": d.payload_schema}
                           for d in sorted(self._definitions.values(), key=lambda d: d.name)
                           if d.subjects is None or subject in d.subjects]}

    def _subscription_id(self, subject, name, arguments, url):
        identity = _json([subject, name, arguments, url])
        key = self.config.jwt_signing_key.get_secret_value().encode()
        return "sub_" + hmac.new(key, identity, hashlib.sha256).hexdigest()

    async def _post_signed(self, subscription, event_id, body):
        signed_at = int(self.clock())
        signatures = [webhook_signature(subscription["secret"], event_id, signed_at, body)]
        if subscription.get("previous_secret") and subscription.get("rotation_until", 0) > self.clock():
            signatures.append(webhook_signature(subscription["previous_secret"], event_id, signed_at, body))
        headers = {"Content-Type": "application/json", "webhook-id": event_id,
                   "webhook-timestamp": str(signed_at), "webhook-signature": " ".join(signatures),
                   "X-MCP-Subscription-Id": subscription["id"]}
        return await self.transport.post(subscription["url"], body, headers)

    async def subscribe(self, subject, params):
        definition = self._definition(params.get("name"), subject)
        arguments, delivery = params.get("arguments", {}), params.get("delivery", {})
        self._validate(definition.input_schema, arguments)
        if not isinstance(delivery, dict) or delivery.get("mode") != "webhook":
            raise EventError(-32602, "Only webhook delivery is supported")
        url, secret = delivery.get("url"), delivery.get("secret")
        validate_callback_url(url)
        _secret_bytes(secret)
        if params.get("cursor") is not None:
            raise EventError(-32602, "This event does not support replay")
        ttl_ms = params.get("ttlMs", 86400000)
        if ttl_ms is None:
            ttl_ms = 86400000
        if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, (int, float)) or not math.isfinite(ttl_ms) or ttl_ms <= 0:
            raise EventError(-32602, "Invalid subscription lifetime")
        lifetime = max(60, min(ttl_ms / 1000, 7 * 86400))
        now = self.clock()
        identity = self._subscription_id(subject, definition.name, arguments, url)
        subscription = {"id": identity, "subject": subject, "name": definition.name,
                        "arguments": arguments, "url": url, "secret": secret,
                        "expires_at": now + lifetime, "active": True, "verified_at": now}
        async with self._state() as state:
            old = state["subscriptions"].get(identity)
            verified = old and old.get("verified_at", 0) > now - 600 and old.get("active")
            self._prune(state, now)
            if not old and len(state["subscriptions"]) >= self.max_subscriptions:
                raise EventError(-32000, "Subscription capacity reached", status=503)
        if not verified:
            challenge = secrets.token_urlsafe(32)
            body = _json({"type": "verification", "challenge": challenge})
            try:
                response = await self._post_signed(subscription, "verification_" + secrets.token_hex(16), body)
                echoed = json.loads(response.body).get("challenge") if 200 <= response.status < 300 else None
                if not isinstance(echoed, str) or not hmac.compare_digest(echoed.encode(), challenge.encode()):
                    raise EventError(-32015, "Callback verification failed", data={"reason": "challenge_failed"})
            except EventError:
                raise
            except (*_NETWORK_ERRORS, ValueError, AttributeError):
                raise EventError(-32015, "Callback verification failed", data={"reason": "timeout_or_invalid_response"}) from None
        async with self._state() as state:
            self._check_subject(subject)
            old = state["subscriptions"].get(identity)
            if not old and len(state["subscriptions"]) >= self.max_subscriptions:
                raise EventError(-32000, "Subscription capacity reached", status=503)
            if old and old["secret"] != secret:
                subscription["previous_secret"] = old["secret"]
                subscription["rotation_until"] = self.clock() + 300
            if verified:
                subscription["verified_at"] = old["verified_at"]
            state["subscriptions"][identity] = subscription
        return {"id": identity, "refreshBefore": _iso(subscription["expires_at"]), "cursor": None, "truncated": False}

    async def unsubscribe(self, subject, params):
        definition = self._definition(params.get("name"), subject)
        arguments, delivery = params.get("arguments", {}), params.get("delivery", {})
        self._validate(definition.input_schema, arguments)
        if not isinstance(delivery, dict) or delivery.get("mode") != "webhook":
            raise EventError(-32602, "Only webhook delivery is supported")
        validate_callback_url(delivery.get("url"))
        identity = self._subscription_id(subject, params["name"], arguments, delivery["url"])
        now = self.clock()
        async with self._state() as state:
            subscription = state["subscriptions"].get(identity)
            if subscription:
                subscription["active"] = False
                subscription["expires_at"] = now
                for job in state["outbox"].values():
                    if job["subscription_id"] == identity and job["status"] == "pending":
                        job.update(status="cancelled", updated_at=now)
        return {}

    async def publish(self, name, data, *, subject, event_id, timestamp=None):
        definition = self._definition(name, subject)
        self._validate(definition.payload_schema, data)
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 1024:
            raise ValueError("event_id must be a stable nonempty string")
        event_key = hashlib.sha256(_json([subject, name, event_id])).hexdigest()
        public_id = "evt_" + event_key
        now = self.clock()
        envelope = {"eventId": public_id, "name": name, "timestamp": _event_time(timestamp, now),
                    "data": data, "cursor": None}
        if len(_json(envelope)) > MAX_BODY_BYTES:
            raise ValueError("Event payload exceeds 256 KiB; publish a report reference")
        async with self._state() as state:
            self._prune(state, now)
            old = state["events"].get(event_key)
            if old:
                if _json(old["envelope"]["data"]) != _json(data):
                    raise ValueError("An existing event_id cannot be reused with different data")
                return {"event_id": public_id, "queued": 0, "duplicate": True}
            matching = [s for s in state["subscriptions"].values()
                        if s["active"] and s["expires_at"] > now and s["subject"] == subject
                        and s["name"] == name and definition.filter_fn(s["arguments"], data)]
            if len(state["events"]) >= self.max_events or len(state["outbox"]) + len(matching) > self.max_outbox:
                raise EventError(-32000, "Event queue capacity reached", status=503)
            state["events"][event_key] = {"envelope": envelope, "subject": subject, "created_at": now}
            for subscription in matching:
                key = hashlib.sha256((event_key + subscription["id"]).encode()).hexdigest()
                state["outbox"][key] = {"subscription_id": subscription["id"], "event_key": event_key,
                                        "status": "pending", "attempts": 0, "next_attempt": now,
                                        "lease_until": 0, "updated_at": now}
        self._wake.set()
        return {"event_id": public_id, "queued": len(matching), "duplicate": False}

    async def run_delivery_once(self, *, limit=20):
        counts = {"accepted": 0, "retry": 0, "stopped": 0}
        for _ in range(max(0, min(limit, 100))):
            selected = None
            now = self.clock()
            async with self._state() as state:
                self._prune(state, now)
                for key, job in state["outbox"].items():
                    if job["status"] != "pending" or job["next_attempt"] > now or job["lease_until"] > now:
                        continue
                    subscription = state["subscriptions"].get(job["subscription_id"])
                    try:
                        if not subscription or not subscription["active"] or subscription["expires_at"] <= now:
                            raise EventError(-32001, "Inactive subscription")
                        self._definition(subscription["name"], subscription["subject"])
                    except EventError:
                        job.update(status="cancelled", updated_at=now)
                        counts["stopped"] += 1
                        continue
                    lease = secrets.token_hex(16)
                    job.update(lease_until=now + 30, lease=lease, attempts=job["attempts"] + 1)
                    event = state["events"][job["event_key"]]["envelope"]
                    selected = (key, lease, json.loads(_json(subscription)), event)
                    break
            if selected is None:
                break
            key, lease, subscription, event = selected
            status, reason = None, "network_error"
            try:
                response = await self._post_signed(subscription, event["eventId"], _json(event))
                status = response.status
                reason = "http_" + str(status)
            except (*_NETWORK_ERRORS, EventError):
                pass
            now = self.clock()
            async with self._state() as state:
                job = state["outbox"].get(key)
                if not job or job.get("lease") != lease or job["status"] != "pending":
                    continue
                job.update(lease_until=0, updated_at=now, last_result=reason)
                if status is not None and 200 <= status < 300:
                    job["status"] = "accepted"
                    counts["accepted"] += 1
                elif (status is None or status in (408, 429) or status >= 500) and job["attempts"] < self.max_attempts:
                    job["next_attempt"] = now + min(3600, 30 * 2 ** (job["attempts"] - 1))
                    counts["retry"] += 1
                else:
                    job["status"] = "failed"
                    counts["stopped"] += 1
                    if status == 410:
                        state["subscriptions"][subscription["id"]]["active"] = False
                        for other in state["outbox"].values():
                            if other["subscription_id"] == subscription["id"] and other["status"] == "pending":
                                other.update(status="cancelled", updated_at=now)
        return counts

    async def serve(self, *, interval=5):
        while True:
            self._wake.clear()
            try:
                await self.run_delivery_once()
            except Exception as exc:
                _LOG.error("Event delivery iteration failed: %s", type(exc).__name__)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def status(self):
        async with self._state() as state:
            return {"events": len(state["events"]),
                    "subscriptions": sum(s["active"] and s["expires_at"] > self.clock()
                                         for s in state["subscriptions"].values()),
                    "pending": sum(j["status"] == "pending" for j in state["outbox"].values()),
                    "failed": sum(j["status"] == "failed" for j in state["outbox"].values())}

    async def diagnostics(self, subject):
        """Bounded owner-only metadata; never return callbacks, secrets or event payloads."""
        self._check_subject(subject)
        now = self.clock()

        def instant(value):
            return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None

        async with self._state() as state:
            subscriptions = [s for s in state["subscriptions"].values()
                             if s["subject"] == subject]
            subscription_ids = {s["id"] for s in subscriptions}
            events = {key: value for key, value in state["events"].items()
                      if value["subject"] == subject}
            jobs = [j for j in state["outbox"].values()
                    if j["subscription_id"] in subscription_ids and j["event_key"] in events]
            counts = {status: sum(j["status"] == status for j in jobs)
                      for status in ("pending", "accepted", "failed", "cancelled")}
            recent = sorted(jobs, key=lambda j: j["updated_at"], reverse=True)[:10]
            return {
                "checked_at": instant(now),
                "available_events": [e["name"] for e in self.list_events(subject)["events"]],
                "subscriptions": [{
                    "event": s["name"],
                    "active": bool(s["active"] and s["expires_at"] > now),
                    "expired": s["expires_at"] <= now,
                    "verified": bool(s.get("verified_at")),
                    "verified_at": instant(s.get("verified_at")),
                    "expires_at": instant(s["expires_at"]),
                } for s in sorted(subscriptions, key=lambda s: (s["name"], s["expires_at"]),
                                  reverse=True)],
                "retained_events": len(events),
                "last_published_at": instant(max((e["created_at"] for e in events.values()),
                                                  default=0)),
                "outbox": counts,
                "recent_deliveries": [{
                    "event": events[j["event_key"]]["envelope"]["name"],
                    "status": j["status"], "attempts": j["attempts"],
                    "last_result": j.get("last_result"),
                    "updated_at": instant(j["updated_at"]),
                } for j in recent],
                "note": "accepted 表示回调已接收，不能证明 ChatGPT 任务执行或通知已显示；新订阅不回放历史。",
            }

    def attach(self, app, server):
        """Insert inside the existing RequireAuthMiddleware, never add a public route."""
        matches = [r for r in app.routes if getattr(r, "path", None) == "/mcp"]
        if len(matches) != 1:
            raise ValueError("Expected exactly one existing MCP route")
        @server.tool(auth=authorize("read", self.config), annotations={
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        })
        async def get_mcp_event_status() -> dict:
            """查询当前账户的事件声明、订阅有效期、回调验证及最近投递结果；不返回正文或凭据。"""
            return await self.diagnostics(self.authenticated_subject())

        route = matches[0]
        if self.config.development_no_auth:
            route.app = _EventEndpoint(route.app, self, server)
        else:
            protected = route.app
            if not isinstance(protected, RequireAuthMiddleware):
                raise ValueError("MCP events must be mounted inside the existing authentication guard")
            protected.app = _EventEndpoint(protected.app, self, server)
        return app


def _decoded_header(value):
    if value is None:
        return None
    if value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
        except (ValueError, UnicodeError):
            raise EventError(-32020, "Invalid encoded MCP header") from None
    if value != value.strip() or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise EventError(-32020, "Invalid MCP header")
    return value


class _EventEndpoint:
    def __init__(self, delegate, service, server):
        self.delegate, self.service, self.server = delegate, service, server

    def _diagnose(self, method, protocol, status, event_count):
        if self.service.config.audit_enabled:
            # Never echo arbitrary client strings into logs, even for invalid requests.
            _DIAGNOSTIC_LOG.info(json.dumps({
                "method": method if isinstance(method, str) and method in _DIAGNOSTIC_METHODS else "unknown",
                "protocol": protocol if isinstance(protocol, str) and protocol in _DIAGNOSTIC_VERSIONS else "unknown",
                "status": status,
                "event_count": event_count,
            }))

    def _subject(self, scope):
        user = scope.get("user")
        token = getattr(user, "access_token", None)
        check = authorize("read", self.service.config)
        if token is None or (check is not None and not check(SimpleNamespace(token=token))):
            raise EventError(-32001, "Event access denied", status=403)
        return self.service._check_subject(claims(token).get("preferred_username"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.delegate(scope, receive, send)
        request = Request(scope, receive)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY_BYTES:
                return await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
        body = bytes(raw)
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        try:
            message = json.loads(body)
        except (ValueError, UnicodeError):
            return await self.delegate(scope, replay, send)
        if not isinstance(message, dict):
            return await self.delegate(scope, replay, send)
        method = message.get("method")
        params = message.get("params", {})
        meta = params.get("_meta", {}) if isinstance(params, dict) else {}
        version = meta.get(META_VERSION) if isinstance(meta, dict) else None
        header_version = request.headers.get("mcp-protocol-version")
        diagnostic_version = version or header_version
        if not diagnostic_version and method == "initialize" and isinstance(params, dict):
            diagnostic_version = params.get("protocolVersion")
        event_count = None
        original_send = send

        async def diagnostic_send(response):
            if response["type"] == "http.response.start":
                self._diagnose(method, diagnostic_version, response["status"], event_count)
            await original_send(response)

        send = diagnostic_send
        modern = version is not None or header_version == PROTOCOL_VERSION or method in (
            "server/discover", "events/list", "events/subscribe", "events/unsubscribe")
        if not modern:
            return await self.delegate(scope, replay, send)
        request_id = message.get("id")
        try:
            subject = self._subject(scope)
            if message.get("jsonrpc") != "2.0" or request_id is None or isinstance(request_id, bool):
                raise EventError(-32600, "Invalid JSON-RPC request")
            if not isinstance(params, dict) or not isinstance(meta, dict):
                raise EventError(-32602, "Invalid request metadata")
            if version != PROTOCOL_VERSION:
                raise EventError(-32022, "Unsupported protocol version",
                                 data={"supported": [PROTOCOL_VERSION, LEGACY_VERSION], "requested": version})
            if header_version != version or request.headers.get("mcp-method") != method:
                raise EventError(-32020, "Missing or mismatched MCP headers")
            if not isinstance(meta.get(META_CAPABILITIES), dict):
                raise EventError(-32602, "Client capabilities are required per request")
            if method == "tools/call" and _decoded_header(request.headers.get("mcp-name")) != params.get("name"):
                raise EventError(-32020, "Missing or mismatched MCP tool name")
            if "inputResponses" in params or "requestState" in params:
                raise EventError(-32602, "Multi-round input is not supported by this server")
            if method == "server/discover":
                result = {"supportedVersions": [PROTOCOL_VERSION, LEGACY_VERSION],
                          "capabilities": {"tools": {}, "events": {}},
                          "_meta": {"io.modelcontextprotocol/serverInfo": {
                              "name": self.service.config.name, "version": self.service.config.version}},
                          "ttlMs": 0, "cacheScope": "private"}
                instructions = getattr(self.server, "instructions", None)
                if instructions:
                    result["instructions"] = instructions
            elif method == "events/list":
                result = self.service.list_events(subject, params.get("cursor"))
                event_count = len(result["events"])
            elif method == "events/subscribe":
                result = await self.service.subscribe(subject, params)
            elif method == "events/unsubscribe":
                result = await self.service.unsubscribe(subject, params)
            elif method in ("tools/list", "tools/call"):
                return await self._legacy_tools(scope, replay, send, message)
            else:
                raise EventError(-32601, "Method not found", status=404)
            result["resultType"] = "complete"
            await JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})(scope, receive, send)
        except EventError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.data is not None:
                error["data"] = exc.data
            await JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error},
                               status_code=exc.status)(scope, receive, send)

    async def _legacy_tools(self, scope, receive, send, request_message):
        # Execute through the existing SDK: its token context, tool-specific auth,
        # policy timeout, output limits and audit all remain in force.
        headers = [(k, v) for k, v in scope["headers"] if k.lower() not in
                   (b"mcp-protocol-version", b"mcp-session-id", b"last-event-id")]
        headers.append((b"mcp-protocol-version", LEGACY_VERSION.encode()))
        adapted = dict(scope, headers=headers)
        buffer = bytearray()
        content_type = ""

        def complete(payload):
            value = json.loads(payload)
            if isinstance(value, dict) and isinstance(value.get("result"), dict):
                value["result"]["resultType"] = "complete"
                if request_message["method"] == "tools/list":
                    value["result"].update(ttlMs=0, cacheScope="private")
            return _json(value)

        async def adapt_send(message):
            nonlocal content_type
            if message["type"] == "http.response.start":
                content_type = dict(message.get("headers", [])).get(b"content-type", b"").decode()
                new_headers = [(k, v) for k, v in message.get("headers", [])
                               if k.lower() not in (b"content-length", b"mcp-session-id")]
                await send(dict(message, headers=new_headers))
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            buffer.extend(message.get("body", b""))
            if len(buffer) > max(MAX_BODY_BYTES * 2, self.service.config.max_output_bytes * 2):
                raise EventError(-32000, "Tool response exceeded adapter limit", status=502)
            if "text/event-stream" in content_type:
                normalized = bytes(buffer).replace(b"\r\n", b"\n")
                parts = normalized.split(b"\n\n")
                buffer[:] = parts.pop()
                for part in parts:
                    lines = part.split(b"\n")
                    data = b"\n".join(line[5:].lstrip(b" ") for line in lines if line.startswith(b"data:"))
                    if data:
                        value = json.loads(data)
                        # The adapter exposes no sampling/elicitation capabilities.
                        if "method" in value and "id" in value:
                            raise EventError(-32000, "Legacy server callbacks are unsupported", status=502)
                        if value.get("method") == "notifications/message" and "io.modelcontextprotocol/logLevel" not in request_message["params"]["_meta"]:
                            continue
                        other = [line for line in lines if not line.startswith(b"data:")]
                        part = b"\n".join(other + [b"data: " + complete(data)])
                    await send({"type": "http.response.body", "body": part + b"\n\n", "more_body": True})
                if not message.get("more_body", False):
                    await send({"type": "http.response.body", "body": bytes(buffer), "more_body": False})
                    buffer.clear()
            elif not message.get("more_body", False):
                payload = bytes(buffer)
                if "application/json" in content_type:
                    payload = complete(payload)
                await send(dict(message, body=payload))
                buffer.clear()

        await self.delegate(adapted, receive, adapt_send)
