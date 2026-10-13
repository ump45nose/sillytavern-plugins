"""复用既有官方 REST 和成熟 MCP，只读取，不注册替代 MCP。"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import yaml

from .contracts import Asset, Batch, Record, digest, instant, utcnow
from .google_read import GoogleReadClient, _load_proxy_environment


def read_env(path, keys):
    """只读取本适配器要求的键，不执行 dotenv 字符串。"""
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"): continue
        k, v = line.split("=", 1)
        if k.strip() in keys: values[k.strip()] = v.strip().strip("\"").strip("'")
    return values


@asynccontextmanager
async def mcp_session(name, settings):
    if name == "email" and settings.get("local_container"):
        from .email_bridge import local_email_session
        async with local_email_session(settings["local_container"]) as session: yield session
        return
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    profile = Path(settings.get("profile_root", "/home/hermes/.hermes/profiles/lingjun"))
    server = yaml.safe_load((profile / "config.yaml").read_text())["mcp_servers"][name]
    auth = None
    headers = {}
    if server.get("auth") == "oauth":
        import sys
        agent = settings.get("hermes_agent_root", "/home/hermes/.hermes/hermes-agent")
        if agent not in sys.path: sys.path.insert(0, agent)
        os.environ.setdefault("HERMES_HOME", str(profile))
        from tools.mcp_oauth import suppress_interactive_oauth
        from tools.mcp_oauth_manager import get_manager
        with suppress_interactive_oauth():
            auth = get_manager().get_or_build_provider(name, server["url"], server.get("oauth"))
        if auth is None: raise RuntimeError("mcp_oauth_unavailable")
    else:
        required = set()
        for value in server.get("headers", {}).values(): required.update(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(value)))
        values = read_env(settings.get("secret_env", "/home/hermes/.hermes/.env"), required)
        values.update({k: os.environ[k] for k in required if k in os.environ})
        for k, value in server.get("headers", {}).items():
            headers[k] = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: values[m[1]], str(value))
    # External MCPs need the same configured egress as the Google collector.
    # Local business MCPs retain their direct route and credentials.
    proxy = None
    if name in {'github', 'mem0'}:
        env_path = Path(settings.get('proxy_env', str(profile / '.env')))
        if env_path.is_file():
            _load_proxy_environment(env_path)
        proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    async with httpx.AsyncClient(auth=auth, headers=headers, timeout=60, trust_env=False, proxy=proxy) as http:
        url = server["url"].rstrip("/") + "/" if name == "mem0" else server["url"]
        async with streamable_http_client(url, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await asyncio.wait_for(session.initialize(), timeout=60)
                yield session


async def call(session, name, args):
    response = await asyncio.wait_for(session.call_tool(name, args), timeout=180)
    if response.isError:
        from .collection_errors import IsolatedSourceError
        reasons = {'auth': '邮件来源认证失败', 'timeout': '邮件来源请求超时',
                   'network': '邮件来源网络连接失败', 'read': '邮件来源读取失败'}
        for content in response.content:
            try:
                detail = json.loads(getattr(content, 'text', ''))
            except (ValueError, TypeError):
                continue
            if (isinstance(detail, dict) and detail.get('error_code') in reasons
                    and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', str(detail.get('error_type', '')))):
                raise IsolatedSourceError({'type': detail['error_type'], 'reason': reasons[detail['error_code']]})
        raise RuntimeError("upstream_mcp_error")
    if response.structuredContent:
        return response.structuredContent
    for content in response.content:
        if getattr(content, "type", None) == "text":
            try: return json.loads(content.text)
            except json.JSONDecodeError: continue
    raise ValueError("upstream_mcp_contract_changed")


class GoogleCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        if self.settings.get("proxy_env"): _load_proxy_environment(Path(self.settings["proxy_env"]))
        client = GoogleReadClient(Path(self.settings["credential_file"]))
        start = since or instant(cursor.get("window_start")) or utcnow() - timedelta(days=30)
        end = utcnow() + timedelta(days=max(1, min(3660, int(self.settings.get("calendar_future_days", 365)))))
        # 所有已授权账号范围内：primary Calendar、既有全部 tasklists。
        def pages(url, params):
            token = ""; tokens = set()
            for _ in range(10000):
                doc = client.get(url, {**params, **({"pageToken": token} if token else {})})
                yield doc.get("items", [])
                token = doc.get("nextPageToken")
                if not token: return
                if token in tokens: raise RuntimeError("google_pagination_stalled")
                tokens.add(token)
            raise RuntimeError("google_pagination_incomplete")
        calendars = [self.settings.get("calendar", "primary")]
        if self.settings.get("calendar_scope") == "owned":
            calendars = []
            for rows in pages("https://www.googleapis.com/calendar/v3/users/me/calendarList", {"maxResults": 250}):
                calendars.extend("primary" if r.get("primary") else r["id"] for r in rows if r.get("accessRole") == "owner")
        for calendar in calendars:
            for rows in pages("https://www.googleapis.com/calendar/v3/calendars/" + quote(calendar, safe="") + "/events", {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true", "showDeleted": "true", "maxResults": 2500}):
                batch = Batch()
                for row in rows:
                    eid = "calendar:" + calendar + ":" + row["id"]
                    if row.get("status") == "cancelled": batch.deletions.append(eid); continue
                    event = row.get("start", {})
                    batch.records.append(Record(eid, "calendar_event", row, {"title": row.get("summary"), "status": row.get("status"), "calendar": calendar}, instant(event.get("dateTime", event.get("date"))), instant(row.get("updated"))))
                yield batch
        # tasklists 的完整清单同时用于任务删除对账；归档/已完成任务仍保存。
        task_ids = []
        for rows in pages("https://tasks.googleapis.com/tasks/v1/users/@me/lists", {"maxResults": 100}):
            for tasklist in rows:
                lid = tasklist["id"]
                for tasks in pages("https://tasks.googleapis.com/tasks/v1/lists/" + quote(lid, safe="") + "/tasks", {"maxResults": 100, "showCompleted": "true", "showHidden": "true", "showDeleted": "true"}):
                    batch = Batch()
                    for row in tasks:
                        eid = "task:" + lid + ":" + row["id"]
                        if row.get("deleted"): batch.deletions.append(eid); continue
                        task_ids.append(eid)
                        batch.records.append(Record(eid, "google_task", {**row, "tasklist": tasklist}, {"title": row.get("title"), "status": row.get("status"), "tasklist_id": lid}, instant(row.get("completed", row.get("due"))), instant(row.get("updated"))))
                    yield batch
        # Calendar 时间窗口缺失不可判断删除；仅任务清单提供完全对账。
        yield Batch(next_cursor={"window_start": start.isoformat(), "collected_at": utcnow().isoformat(), "task_ids": task_ids}, deletions=list(set(cursor.get("task_ids", [])) - set(task_ids)))


class EmailCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        yield from asyncio.run(self._collect(cursor, since))

    async def _collect(self, cursor, since):
        from .email_policy import EmailCandidatePolicy
        policy = EmailCandidatePolicy(self.settings["policy"])
        start = since or instant(cursor.get("window_start")) or utcnow() - timedelta(days=30)
        end = utcnow()
        results = []
        async with mcp_session("email", self.settings) as session:
            for account in self.settings["accounts"]:
                page = 1; count = 0; known = set()
                while True:
                    doc = await call(session, "list_emails_metadata", {"account_name": account, "mailbox": "INBOX", "page": page, "page_size": 100, "since": start.isoformat(), "before": end.isoformat(), "order": "asc"})
                    rows = doc["emails"]
                    if not rows: break
                    for row in rows:
                        uid = str(row["email_id"])
                        if uid in known: raise RuntimeError("email_pagination_stalled")
                        known.add(uid); count += 1
                        if policy.assess(str(row.get("subject", "")), str(row.get("sender", ""))) is None: continue
                        offset = 0; parts = []; detail = None
                        while True:
                            body_doc = await call(session, "get_emails_content", {"account_name": account, "email_ids": [uid], "mailbox": "INBOX", "mark_as_read": False, "body_offset": offset, "max_body_length": 12000})
                            if body_doc.get("failed_ids") or len(body_doc.get("emails", [])) != 1: raise RuntimeError("email_body_incomplete")
                            detail = body_doc["emails"][0]; body = detail.get("body", "")
                            clipped = body.endswith("...[TRUNCATED]")
                            parts.append(body.removesuffix("...[TRUNCATED]") if clipped else body)
                            if not clipped: break
                            offset += 12000
                            if offset > 50_000_000: raise RuntimeError("email_body_too_large")
                        detail = {**detail, "body": "".join(parts)}
                        if policy.assess(str(row.get("subject", "")), str(row.get("sender", "")), detail["body"]) is None: continue
                        attachments = []
                        for filename in detail.get("attachments", []):
                            response = await session.call_tool("get_attachment_content", {"account_name": account, "email_id": uid, "mailbox": "INBOX", "attachment_name": filename})
                            if response.isError: raise RuntimeError("email_attachment_incomplete")
                            resources = [x.resource for x in response.content if getattr(x, "type", None) == "resource" and hasattr(x.resource, "blob")]
                            if len(resources) != 1: raise RuntimeError("email_attachment_contract_changed")
                            attachments.append(Asset(filename, content=base64.b64decode(resources[0].blob), media_type=resources[0].mimeType or "application/octet-stream"))
                        results.append(Batch(records=[Record(account + ":INBOX:" + uid, "email", {"account": account, "metadata": row, "message": detail}, {"subject": row.get("subject"), "sender": row.get("sender"), "body": detail["body"], "message_id": detail.get("message_id")}, instant(row.get("date")), assets=attachments)]))
                    if count >= int(doc["total"]): break
                    page += 1
                    if page > 10000: raise RuntimeError("email_pagination_incomplete")
        # 邮件窗口/过滤结果缺失不作为删除信号。
        results.append(Batch(next_cursor={"window_start": start.isoformat(), "collected_at": end.isoformat()}))
        return results


class Mem0Collector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None): yield from asyncio.run(self._collect())

    async def _collect(self):
        result = []; seen = []; signatures = set()
        async with mcp_session("mem0", self.settings) as session:
            names = [x.name for x in (await session.list_tools()).tools]
            name = next((x for x in names if x.endswith("get_memories")), None)
            if not name: raise RuntimeError("mem0_list_tool_missing")
            for page in range(1, 10001):
                body = await call(session, name, {"page": page, "page_size": 100})
                rows = body if isinstance(body, list) else body.get("results", body.get("memories", []))
                if not isinstance(rows, list): raise RuntimeError("mem0_schema_changed")
                if not rows: break
                signature = digest([x["id"] for x in rows])
                if signature in signatures: raise RuntimeError("mem0_pagination_stalled")
                signatures.add(signature)
                for row in rows:
                    eid = str(row["id"]); seen.append(eid)
                    result.append(Batch(records=[Record(eid, "memory", row, {"content": row.get("memory", row.get("content")), "metadata": row.get("metadata")}, instant(row.get("created_at")), instant(row.get("updated_at")))]))
            else: raise RuntimeError("mem0_pagination_incomplete")
        result.append(Batch(next_cursor={"collected_at": utcnow().isoformat()}, authoritative=True, seen_ids=seen))
        return result


class GitCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None): yield from asyncio.run(self._collect(cursor, since))

    async def _collect(self, cursor, since):
        from .git_activity import collect
        return await collect(self.settings, cursor, since)
