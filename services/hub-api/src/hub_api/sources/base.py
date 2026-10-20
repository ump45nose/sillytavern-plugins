import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable

import httpx


@dataclass
class Adapter:
    id: str
    name: str
    ttl: int
    fetch: Callable[[], Awaitable[dict]] | None = None


class SourceManager:
    def __init__(self, adapters, now, timeout=5):
        self.adapters = {a.id: a for a in adapters}
        self.now = now
        self.timeout = timeout
        self.cache = {}
        self.states = {}
        self.locks = {a.id: asyncio.Lock() for a in adapters}

    def status(self, identifier):
        adapter = self.adapters[identifier]
        state = self.states.get(identifier, {})
        # Reading status never performs source I/O.
        status = state.get("status", "unconfigured" if adapter.fetch is None else "stale")
        success = state.get("last_success")
        if success and (self.now() - datetime.fromisoformat(success)).total_seconds() > 86400:
            status = "error"
        return {"id": identifier, "name": adapter.name, "status": status,
                "last_success": success, "last_error": state.get("last_error"),
                "latency_ms": state.get("latency_ms")}

    async def get(self, identifier):
        adapter = self.adapters[identifier]
        if adapter.fetch is None:
            return {"id": identifier, "status": "unconfigured", "updated_at": None, "data": None}
        async with self.locks[identifier]:
            now = self.now()
            cached = self.cache.get(identifier)
            # Cache failures briefly too, so refreshes cannot hammer a failing source.
            state = self.states.get(identifier, {})
            if state.get("checked_at") and (now - state["checked_at"]).total_seconds() < adapter.ttl:
                return self.result(identifier)
            started = time.monotonic()
            error = None
            try:
                async with asyncio.timeout(self.timeout):
                    data = await adapter.fetch()
                self.cache[identifier] = {"data": data, "updated_at": now.isoformat()}
            except httpx.HTTPStatusError as exc:
                error = {"type": "http_status", "status_code": exc.response.status_code}
            except (httpx.TimeoutException, TimeoutError):
                error = {"type": "timeout", "status_code": None}
            except httpx.RequestError:
                error = {"type": "connection", "status_code": None}
            except (ValueError, TypeError, KeyError, AttributeError):
                error = {"type": "invalid_payload", "status_code": None}
            except Exception:
                error = {"type": "source_failure", "status_code": None}
            cached = self.cache.get(identifier)
            if cached and now - datetime.fromisoformat(cached["updated_at"]) > timedelta(hours=24):
                self.cache.pop(identifier)
                cached = None
            self.states[identifier] = {
                "checked_at": now, "status": "ok" if error is None else ("stale" if cached else "error"),
                "last_success": now.isoformat() if error is None else state.get("last_success"),
                "last_error": error, "latency_ms": round((time.monotonic() - started) * 1000),
                "failed_since": (state.get("failed_since") or now) if error else None,
            }
            return self.result(identifier)

    def result(self, identifier):
        cached = self.cache.get(identifier)
        if cached and (self.now() - datetime.fromisoformat(cached["updated_at"])).total_seconds() > 86400:
            self.cache.pop(identifier)
            cached = None
            self.states[identifier]["status"] = "error"
        return {"id": identifier, "status": self.states[identifier]["status"],
                "updated_at": cached["updated_at"] if cached else None,
                "data": cached["data"] if cached else None}
