"""Read only the points endpoints evidenced by the official points page.

The frontend still declares a legacy sign API, but its current sign handler
opens the app. This client deliberately has no sign or reward-claim operation.
No official bundle or third-party script is imported or executed.
"""

import json
from http.client import HTTPException
from http.cookies import CookieError, SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common.details import number

ORIGIN = "https://m.you.163.com"
PAGE = ORIGIN + "/points/index"
LOGIN_PATH = "/xhr/common/checklogin.json"
POINTS_PATH = "/xhr/points/index.json"
MAX_RESPONSE = 1024 * 1024
REQUEST_TIMEOUT = 15


class QueryError(Exception):
    """Only a fixed reason crosses the result/log boundary."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise QueryError("unexpected_redirect")


def _header(value, maximum):
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and not any(ord(char) < 32 or ord(char) > 126 for char in value)
    )


def _csrf(cookie):
    parsed = SimpleCookie()
    try:
        parsed.load(cookie)
    except CookieError:
        raise QueryError("missing_or_invalid_cookie") from None
    token = parsed.get("yx_csrf")
    if token is None or not token.value:
        raise QueryError("csrf_cookie_missing")
    # The official _$getCookie uses unescape before appendURL encodes the value.
    decoded = unquote(token.value, encoding="latin-1")
    if not _header(decoded, 4096):
        raise QueryError("csrf_cookie_invalid")
    return decoded


def _points(value):
    try:
        parsed = number(value)
    except OverflowError:
        return None
    return parsed if parsed is not None and parsed >= 0 else None


def _success(response):
    if not isinstance(response, dict):
        raise QueryError("response_schema_unconfirmed")
    code = response.get("code")
    if code in (401, 403, "401", "403"):
        # A rejection does not prove that a token expired; CSRF can also fail.
        raise QueryError("authentication_rejected")
    if code not in (200, "200"):
        raise QueryError("points_query_rejected")
    return response.get("data")


def parse_points(response):
    data = _success(response)
    if not isinstance(data, dict):
        raise QueryError("response_schema_unconfirmed")
    info = data.get("userPointSimpleInfo")
    if not isinstance(info, dict):
        raise QueryError("points_balance_unconfirmed")
    balance = _points(info.get("totalPoint"))
    if balance is None:
        raise QueryError("points_balance_unconfirmed")
    return {
        "balance": balance,
        "pending_points": _points(info.get("unReceivedPoint")),
        "available_points": _points(data.get("availablePoint")),
    }


class Client:
    def __init__(self, cookie, *, user_agent="Mozilla/5.0", proxy=None, opener=None):
        if not _header(cookie, 65536):
            raise QueryError("missing_or_invalid_cookie")
        if not _header(user_agent, 4096):
            raise QueryError("invalid_user_agent")
        self.csrf = _csrf(cookie)
        self.headers = {
            "Cookie": cookie,
            "User-Agent": user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "identity",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": ORIGIN,
            "Referer": PAGE,
        }
        proxies = {}
        if proxy:
            try:
                target = urlsplit(proxy)
            except ValueError:
                raise QueryError("invalid_proxy") from None
            if target.scheme not in {"http", "https"} or not target.hostname:
                raise QueryError("invalid_proxy")
            proxies = {"http": proxy, "https": proxy}
        self.opener = opener if opener is not None else build_opener(
            ProxyHandler(proxies), NoRedirect()
        )

    def _request(self, path, method):
        # POST is the official points-index read operation, not a write action.
        if (path, method) not in {(LOGIN_PATH, "GET"), (POINTS_PATH, "POST")}:
            raise QueryError("unsupported_operation")
        headers = dict(self.headers)
        body = None
        if method == "POST":
            body = b""
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        request = Request(
            ORIGIN + path + "?" + urlencode({"csrf_token": self.csrf}),
            data=body, headers=headers, method=method,
        )
        try:
            with self.opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    raise QueryError("unexpected_http_status")
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        size = int(length)
                    except ValueError:
                        raise QueryError("invalid_response_length") from None
                    if not 0 <= size <= MAX_RESPONSE:
                        raise QueryError("response_too_large")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise QueryError("response_too_large")
        except HTTPError as error:
            status = error.code
            error.close()
            raise QueryError(
                "authentication_rejected" if status in {401, 403}
                else "unexpected_http_status"
            ) from None
        except (OSError, URLError, HTTPException):
            raise QueryError("points_transport_error") from None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise QueryError("invalid_json_response") from None

    def snapshot(self):
        logged_in = _success(self._request(LOGIN_PATH, "GET"))
        if logged_in is False:
            raise QueryError("authentication_invalid")
        if logged_in is not True:
            raise QueryError("authentication_unconfirmed")
        return parse_points(self._request(POINTS_PATH, "POST"))
