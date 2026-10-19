"""Narrow HTTP protocol port of MIT workbuddy-helper; see provider-source.json."""
import hashlib
import http.client
import http.cookiejar
import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, HTTPCookieProcessor, build_opener

from .state import WorkBuddyError, validate_session
from common.details import number

BASES = {"cn": ("https://copilot.tencent.com", "https://www.codebuddy.cn"),
         "intl": ("https://www.workbuddy.ai", "https://www.codebuddy.ai")}
CN_UA = "WorkBuddy/5.8.3 WorkBuddy/5.8.3 CLI/2.161.0"
INTL_UA = "WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/2.137.1"
MODEL, PROMPT = "hy3", "only print:1"
MAX_BODY = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def classify(status, body):
    code = body.get("code") if isinstance(body, dict) else None
    if type(code) is not int:
        code = None
    message = str(body.get("msg", body.get("message", ""))).lower() if isinstance(body, dict) else ""
    if status == 401 or code in {401, 12153} or any(
            marker in message for marker in ("offline user session", "user session not found")):
        reason = "authentication_invalid"
    elif code == 14018 or any(marker in message for marker in (
            "credits exhausted", "insufficient credit", "quota exceeded", "积分不足", "额度不足")):
        reason = "credits_exhausted"
    elif status == 429:
        reason = "rate_limited"
    elif status == 403:
        reason = "access_denied"
    elif status == 404:
        reason = "api_not_found"
    elif status >= 500:
        reason = "platform_unavailable"
    elif code == 11217 or status in {400, 409} and code == 1001:
        reason = "authorization_pending"
    else:
        reason = "platform_rejected"
    return WorkBuddyError(reason, status=status, code=code)


class HTTP:
    def __init__(self, proxy=None):
        if proxy:
            p = urlsplit(proxy)
            if p.scheme not in {"http", "https"} or not p.hostname or p.fragment:
                raise WorkBuddyError("invalid_proxy")
        self.opener = build_opener(NoRedirect(),
            ProxyHandler({"http": proxy, "https": proxy} if proxy else {}),
            HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method, url, headers, payload=None):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else None
        request = Request(url, data=data, headers=headers, method=method)
        try:
            try:
                response = self.opener.open(request, timeout=30)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise WorkBuddyError("response_too_large")
                return response.status, raw
        except WorkBuddyError:
            raise
        except (OSError, URLError, ValueError, http.client.HTTPException):
            raise WorkBuddyError("transport_error") from None


def json_body(raw):
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except (ValueError, TypeError):
        raise WorkBuddyError("invalid_platform_response") from None


def envelope(status, raw):
    try:
        body = json_body(raw)
    except WorkBuddyError:
        if status not in range(200, 300):
            raise classify(status, {}) from None
        raise
    if status not in range(200, 300) or type(body.get("code")) is not int or body["code"] != 0:
        raise classify(status, body)
    if not isinstance(body.get("data"), dict):
        raise WorkBuddyError("invalid_platform_response")
    return body["data"]


def field(data, snake, camel):
    return data.get(snake, data.get(camel))


def boolean(value):
    if value is True or value == "true" or type(value) is int and value == 1:
        return True
    if value is False or value == "false" or type(value) is int and value == 0:
        return False
    return None


def amount(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 <= number <= 1e12 else None
    except (TypeError, ValueError):
        return None


def parse_status(data):
    active = boolean(field(data, "active", "Active"))
    checked = boolean(field(data, "today_checked_in", "todayCheckedIn"))
    if active is not False and checked is None:
        raise WorkBuddyError("checkin_state_unconfirmed")
    return {"active": active, "checked": checked,
            "reward": amount(field(data, "today_credit", "todayCredit")),
            "streak": amount(field(data, "streak_days", "streakDays"))}


def package_balance(row):
    """Use the provider's cycle/legacy capacity reconciliation, never missing=0."""
    if not isinstance(row, dict):
        raise ValueError()
    cycle_keys = ("CycleCapacityRemain", "CycleCapacityUsed", "CycleCapacitySize")
    cycle = any(number(row.get(key)) not in (None, 0) for key in cycle_keys)
    prefix = "CycleCapacity" if cycle else "Capacity"
    remain = number(row.get(prefix + "Remain"))
    size, used = number(row.get(prefix + "Size")), number(row.get(prefix + "Used"))
    if remain is None or size is not None and size < 0 or used is not None and used < 0:
        raise ValueError()
    remain = max(0, remain)
    if size is not None and (cycle or size > 0):
        remain = min(remain, size)
        if cycle and used is not None and size >= used > size - remain:
            remain = size - used
    return remain


class Client:
    def __init__(self, edition, session, save, transport=None, now=None):
        self.edition = edition
        self.session = validate_session(session, edition)
        self.save = save
        self.http = transport or HTTP()
        self.chat_base, self.billing_base = BASES[edition]
        self.refreshed = False
        self.now = now or datetime.now

    def headers(self, *, desktop=False):
        intl = self.edition == "intl"
        origin = BASES[self.edition][0] if intl else BASES["cn"][1]
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "Origin": origin, "Referer": origin + "/",
                   "User-Agent": "CLI/2.63.2 CodeBuddy/2.63.2" if intl else CN_UA}
        if self.session.get("access_token"):
            headers["Authorization"] = "Bearer " + self.session["access_token"]
        for source, target in (("uid", "X-User-Id"), ("enterprise_id", "X-Enterprise-Id"), ("domain", "X-Domain")):
            if self.session.get(source):
                headers[target] = self.session[source]
        if self.session.get("enterprise_id"):
            headers["X-Tenant-Id"] = self.session["enterprise_id"]
        if desktop or not intl:
            headers.update({"User-Agent": INTL_UA if intl else CN_UA, "X-Product": "SaaS",
                "X-IDE-Type": "WorkBuddy", "X-IDE-Name": "WorkBuddy",
                "X-IDE-Version": "5.5.2" if intl else "5.8.3"})
        if not intl:
            headers.update({"X-Requested-With": "XMLHttpRequest", "x-codebuddy-request": "1"})
        return headers

    def refresh(self):
        if self.refreshed or not self.session.get("refresh_token"):
            raise WorkBuddyError("authentication_invalid")
        self.refreshed = True
        headers = self.headers()
        headers.pop("Authorization", None)
        headers.update({"X-Refresh-Token": self.session["refresh_token"],
                        "X-Auth-Refresh-Source": "plugin" if self.edition == "intl" else "workbuddy"})
        data = envelope(*self.http.request("POST", self.chat_base + "/v2/plugin/auth/token/refresh", headers))
        candidate = {**self.session, "access_token": field(data, "access_token", "accessToken")}
        for snake, camel in (("refresh_token", "refreshToken"), ("domain", "domain")):
            if field(data, snake, camel):
                candidate[snake] = field(data, snake, camel)
        candidate = validate_session(candidate, self.edition)
        self.save(candidate)  # Rotating refresh tokens must be durable before more requests.
        self.session = candidate

    def api(self, path, payload=None, *, billing=False, read=False):
        base = self.billing_base if billing else self.chat_base
        try:
            return envelope(*self.http.request("POST", base + path, self.headers(), {} if payload is None else payload))
        except WorkBuddyError as error:
            if not read or error.reason != "authentication_invalid":
                raise
            self.refresh()
            return envelope(*self.http.request("POST", base + path, self.headers(), {} if payload is None else payload))

    def status(self):
        try:
            data = self.api("/v2/billing/meter/checkin-activity-status", billing=True, read=True)
        except WorkBuddyError as error:
            if error.status != 404:
                raise
            data = self.api("/v2/billing/meter/checkin-status", billing=True, read=True)
        return parse_status(data)

    def checkin(self):
        return self.api("/v2/billing/meter/daily-checkin", billing=True)

    def points(self):
        now, total, count, expected = self.now(), 0, 0, None
        for page in range(1, 101):
            data = self.api("/v2/billing/meter/get-user-resource", {
                "PageNumber": page, "PageSize": 100, "ProductCode": "p_tcaca", "Status": [0, 3],
                "PackageEndTimeRangeBegin": now.strftime("%Y-%m-%d %H:%M:%S"),
                "PackageEndTimeRangeEnd": (now + timedelta(days=101 * 365)).strftime("%Y-%m-%d %H:%M:%S")},
                billing=True, read=True)
            try:
                data = data["Response"]["Data"]
                rows = data["Accounts"]
                if not isinstance(rows, list) or len(rows) > 100:
                    raise ValueError()
                current_total = data.get("TotalCount")
                if current_total is not None:
                    if type(current_total) is not int or not 0 <= current_total <= 10000:
                        raise ValueError()
                    if expected is not None and expected != current_total:
                        raise ValueError()
                    expected = current_total
                for row in rows:
                    total += package_balance(row)
                    if total > 1e12:
                        raise ValueError()
                count += len(rows)
                if expected is not None:
                    if count > expected or not rows and count < expected:
                        raise ValueError()
                    if count == expected:
                        return total
                elif len(rows) < 100:
                    return total
            except (KeyError, TypeError, ValueError):
                raise WorkBuddyError("balance_unconfirmed") from None
        raise WorkBuddyError("balance_page_limit")

    def active(self):
        session_id, request_id = str(uuid.uuid4()), uuid.uuid4().hex
        headers = self.headers(desktop=True)
        headers["X-Request-ID"] = uuid.uuid4().hex
        now = int(time.time() * 1000)
        body = {"type": "local", "sessionId": session_id, "name": "新任务",
                "conversationOrigin": "legacy_workbuddy_local", "workDir": "", "isPlayground": 1,
                "createdAtMs": now, "updatedAtMs": now, "lastActivityAtMs": now,
                "clientContext": {"localStatus": "active", "hostId": hashlib.sha256(
                    ("benefits-workbuddy:" + os.uname().nodename).encode()).hexdigest(),
                    "sessionKind": "manual", "model": MODEL, "sourceMode": "", "permissionMode": "",
                    "expert": {"id": "", "locale": "", "runtimeIdentity": "", "marketplace": ""}}}
        conversation = envelope(*self.http.request("POST", self.chat_base + "/console/as/conversations/v2", headers, body))
        if not isinstance(conversation.get("id"), str) or not conversation["id"]:
            raise WorkBuddyError("conversation_unconfirmed")
        headers.update({"Accept": "text/event-stream", "X-Conversation-ID": conversation["id"],
            "X-Conversation-Request-ID": request_id, "X-Conversation-Message-ID": uuid.uuid4().hex,
            "X-Agent-Intent": "craft"})
        events = [{"eventCode": "chat_request_send", "id": session_id, "extra": {
            "inputLength": len(PROMPT), "requestModelId": MODEL, "requestModelName": MODEL,
            "mode": "craft", "command": "", "expertId": "", "recommendId": "", "skillId": "",
            "skillCount": 0, "totalCount": 0, "rootRequestId": request_id,
            "parentConversationId": session_id, "agentName": "craft", "agentType": "default"}}]
        body = {"model": MODEL, "stream": True, "max_tokens": 4096,
                "extra_vars": {"growthEvent": json.dumps(events, separators=(",", ":"))},
                "messages": [{"role": "system", "content": "You are a helpful assistant."},
                             {"role": "user", "content": [{"type": "text", "text": "<user_query> " + PROMPT + " </user_query>"}]}]}
        status, raw = self.http.request("POST", self.chat_base + "/v2/chat/completions", headers, body)
        if status not in range(200, 300):
            raise classify(status, json_body(raw))
        validate_chat(raw)


def validate_chat(raw):
    try:
        text = raw.decode("utf-8")
        sse = any(line.startswith(("data:", "event:")) for line in text.splitlines())
        packets, done = [], not sse
        if sse:
            event, lines = "", []
            for line in (text.replace("\r\n", "\n") + "\n\n").split("\n"):
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    lines.append(line[5:].strip())
                elif not line:
                    if event == "error":
                        raise WorkBuddyError("active_response_error")
                    if lines:
                        data = "\n".join(lines)
                        if data == "[DONE]":
                            done = True
                        else:
                            packets.append(json.loads(data))
                    event, lines = "", []
        else:
            packets = [json.loads(text)]
        answer = False
        for packet in packets:
            if not isinstance(packet, dict):
                raise ValueError()
            if "error" in packet and packet["error"] is not None:
                raise classify(200, packet["error"] if isinstance(packet["error"], dict) else {})
            if "code" in packet and (type(packet["code"]) is not int or packet["code"] != 0):
                raise classify(200, packet)
            for choice in packet.get("choices", []):
                if choice.get("finish_reason") is not None:
                    done = True
                for value in (choice.get("delta", {}), choice.get("message", {})):
                    for key in ("content", "reasoning_content", "reasoning"):
                        content = value.get(key)
                        if isinstance(content, str) and content.strip():
                            answer = True
                        if isinstance(content, list) and any(
                                isinstance(x, dict) and isinstance(x.get("text"), str) and x["text"].strip() for x in content):
                            answer = True
        if not answer or not done:
            raise WorkBuddyError("active_response_unconfirmed")
    except WorkBuddyError:
        raise
    except (ValueError, TypeError, AttributeError):
        raise WorkBuddyError("invalid_active_response") from None
