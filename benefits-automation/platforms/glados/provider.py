"""GLaDOS HTTP protocol, implemented locally without importing upstream scripts."""

from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from common.details import number

MAX_BODY = 1024 * 1024
REQUEST_TIMEOUT = 20
ALREADY_MESSAGES = {
    "please try tomorrow",
    "today's observation logged. return tomorrow for more points.",
    "checkin repeats! please try tomorrow",
}


class ProviderError(Exception):
    """Only a fixed, non-sensitive reason crosses the HTTP boundary."""


def nonnegative(value):
    value = number(value)
    return value if value is not None and value >= 0 else None


def validate_settings(origin, cookie, user_agent, token="", proxy=None):
    try:
        if not isinstance(origin, str) or any(ord(c) < 33 or ord(c) > 126 for c in origin):
            raise ValueError
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment
                or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", parsed.hostname)):
            raise ValueError
    except (TypeError, ValueError):
        raise ProviderError("missing_or_invalid_origin") from None
    if (not isinstance(user_agent, str) or not user_agent.strip() or len(user_agent) > 2048
            or any(ord(c) < 32 or ord(c) > 126 for c in user_agent)):
        raise ProviderError("missing_or_invalid_user_agent")
    if (not isinstance(cookie, str) or not cookie or len(cookie) > 65536
            or any(ord(c) < 32 or ord(c) > 126 for c in cookie)):
        raise ProviderError("missing_or_invalid_cookie")
    fields = {}
    for part in cookie.split(";"):
        if not part.strip():
            continue
        name, sep, value = part.strip().partition("=")
        if not sep or name in fields or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z:-]+", name):
            raise ProviderError("missing_or_invalid_cookie")
        fields[name] = value
    complete = False
    for name in ("gld:sess", "koa:sess"):
        pair = name + ".sig"
        if name in fields or pair in fields:
            if not fields.get(name) or not fields.get(pair):
                raise ProviderError("missing_or_invalid_cookie")
            complete = True
    if not complete:
        raise ProviderError("missing_or_invalid_cookie")
    if (not isinstance(token, str) or len(token) > 256
            or any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ProviderError("invalid_checkin_token")
    if proxy:
        try:
            target = urlsplit(proxy)
            if target.scheme not in {"http", "https"} or not target.hostname or target.port is None:
                raise ValueError
        except (TypeError, ValueError):
            raise ProviderError("invalid_proxy") from None
    return "https://" + parsed.hostname, token or parsed.hostname


def failure(payload, status=200):
    if (status == 403 and payload.get("cloudflare_error") is True
            and type(payload.get("error_code")) is int and payload["error_code"] == 1010):
        return "cloudflare_browser_signature_banned"
    if payload.get("reason") == "device-mismatch":
        return "device_mismatch"
    message = payload.get("message")
    if isinstance(message, str) and "automated check-in" in message.lower():
        return "automated_checkin_rejected"
    if status == 401 or payload.get("code") == -2:
        return "authentication_invalid"
    if status == 403:
        return "access_denied"
    return "http_error" if status != 200 else "business_response_unrecognized"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("unexpected_redirect")


class Client:
    def __init__(self, origin, cookie, user_agent, token="", proxy=None, *, opener=None):
        self.origin, self.token = validate_settings(origin, cookie, user_agent, token, proxy)
        self.headers = {
            "Cookie": cookie, "User-Agent": user_agent, "Origin": self.origin,
            "Referer": self.origin + "/console/checkin", "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        self.opener = opener or build_opener(
            NoRedirect(), ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))

    def request(self, method, path, payload=None):
        headers = dict(self.headers)
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json;charset=UTF-8"
            data = json.dumps(payload).encode()
        req = Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            try:
                response = self.opener.open(req, timeout=REQUEST_TIMEOUT)
            except HTTPError as error:
                response = error
            with response:
                status = response.status
                if response.headers.get("cf-mitigated") == "challenge":
                    raise ProviderError("cloudflare_challenge")
                if 300 <= status < 400:
                    raise ProviderError("unexpected_redirect")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > MAX_BODY:
                    raise ProviderError("response_too_large")
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise ProviderError("response_too_large")
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                if status in (401, 403):
                    raise ProviderError("authentication_invalid" if status == 401 else "access_denied")
                raise ProviderError("invalid_response") from None
            if not isinstance(body, dict):
                raise ProviderError("invalid_response")
            if status != 200:
                raise ProviderError(failure(body, status))
            if type(body.get("code")) is not int:
                raise ProviderError("invalid_response")
            return body
        except ProviderError:
            raise
        except (URLError, TimeoutError, OSError, HTTPException):
            raise ProviderError("transport_error") from None
        except (ValueError, TypeError):
            raise ProviderError("invalid_response") from None

    def status(self):
        body = self.request("GET", "/api/user/status")
        if body["code"] != 0:
            raise ProviderError(failure(body))
        data = body.get("data")
        if not isinstance(data, dict):
            raise ProviderError("invalid_response")
        return nonnegative(data.get("leftDays"))

    def points(self):
        body = self.request("GET", "/api/user/points")
        if body["code"] != 0:
            raise ProviderError(failure(body))
        return body

    def checkin(self):
        return self.request("POST", "/api/user/checkin", {"token": self.token})


@dataclass(frozen=True)
class Points:
    balance: float | None
    streak: float | None
    signed: bool | None
    reward: float | None


def read_points(body, day, timezone):
    """Use the same business marker and timestamp calendar as the official UI."""
    rows = body.get("history")
    balance, streak = nonnegative(body.get("points")), nonnegative(body.get("streak"))
    if streak is not None and not streak.is_integer():
        streak = None
    if not isinstance(rows, list) or len(rows) > 1000:
        return Points(balance, streak, None, None)
    zone = ZoneInfo(timezone)
    valid, rewards = True, []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("business"), str):
            valid = False
            continue
        try:
            timestamp = row.get("time")
            if isinstance(timestamp, bool):
                raise ValueError
            timestamp = float(timestamp)
            if not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError
            date = datetime.fromtimestamp(timestamp / 1000, zone).date().isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            valid = False
            continue
        if "checkin" in row["business"].split(":") and date == day:
            change = nonnegative(row.get("change"))
            if number(row.get("change")) is not None and change is None:
                valid = False
                continue
            rewards.append(change)
    signed = True if rewards else False if valid else None
    return Points(balance, streak, signed, rewards[0] if len(rewards) == 1 else None)


def accepted(body):
    return type(body.get("code")) is int and (body.get("code") == 0 or
            body.get("code") == 1 and isinstance(body.get("message"), str)
            and body["message"].strip().lower() in ALREADY_MESSAGES)
