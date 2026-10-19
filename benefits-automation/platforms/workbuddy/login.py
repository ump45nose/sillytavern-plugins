#!/usr/bin/env python3
"""One-time official browser authorization or plaintext client-session import."""
import argparse
import json
import os
import sys
import time
from http.cookiejar import Cookie
from pathlib import Path
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.locks import Busy, Lease
from platforms.workbuddy.client import BASES, CN_UA, Client, HTTP, classify, envelope
from platforms.workbuddy.state import WorkBuddyError, credential_path, durable_json, read_private, validate_session


def authorization_url(value, edition):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        allowed = ("workbuddy.ai",) if edition == "intl" else ("codebuddy.cn", "copilot.tencent.com")
        if (parsed.scheme != "https" or parsed.username or parsed.password or
                parsed.port not in (None, 443) or not parsed.path or
                not any(host == x or host.endswith("." + x) for x in allowed)):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise WorkBuddyError("untrusted_authorization_url") from None


class Login:
    def __init__(self, edition, transport=None):
        self.edition, self.base = edition, BASES[edition][0]
        self.http = transport or HTTP()
        self.headers = {"Accept": "application/json", "Content-Type": "application/json",
            "Origin": self.base if edition == "intl" else BASES["cn"][1],
            "Referer": (self.base if edition == "intl" else BASES["cn"][1]) + "/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "CLI/2.63.2 CodeBuddy/2.63.2" if edition == "intl" else CN_UA}
        if edition == "cn":
            self.headers.update({"X-Product": "SaaS", "X-IDE-Type": "WorkBuddy", "X-IDE-Name": "WorkBuddy",
                                 "X-IDE-Version": "5.8.3", "x-codebuddy-request": "1"})
        self.state = None

    def start(self):
        headers = {**self.headers, "X-Domain": urlsplit(self.base).hostname}
        data = envelope(*self.http.request("POST", self.base + "/v2/plugin/auth/state?" +
            urlencode({"platform": "workbuddy-ai" if self.edition == "intl" else "CLI"}), headers, {}))
        if not isinstance(data.get("state"), str) or not data["state"]:
            raise WorkBuddyError("authorization_state_missing")
        url = authorization_url(data.get("authUrl"), self.edition)
        self.state = data["state"]
        return url

    def poll(self):
        if not self.state:
            raise WorkBuddyError("authorization_state_missing")
        query = "?" + urlencode({"state": self.state})
        token = envelope(*self.http.request("GET", self.base + "/v2/plugin/auth/token" + query, self.headers))
        if not isinstance(token.get("accessToken"), str) or not token["accessToken"]:
            raise WorkBuddyError("invalid_session")
        headers = {**self.headers, "Authorization": "Bearer " + token["accessToken"]}
        account = envelope(*self.http.request("GET", self.base + "/v2/plugin/login/account" + query, headers))
        return validate_session({"edition": self.edition, "access_token": token["accessToken"],
            "refresh_token": token.get("refreshToken") or "", "uid": account.get("uid"),
            "enterprise_id": account.get("enterpriseId") or "",
            "domain": token.get("domain") or ("www.workbuddy.ai" if self.edition == "intl" else "")}, self.edition)


def import_plaintext(value, edition):
    if "access_token" in value:
        return validate_session(value, edition)
    auth, account = value.get("auth"), value.get("account")
    if not isinstance(auth, dict) or not isinstance(account, dict):
        raise WorkBuddyError("invalid_client_session")
    if isinstance(auth.get("accessToken"), dict) or isinstance(auth.get("refreshToken"), dict):
        raise WorkBuddyError("encrypted_session_requires_client")
    return validate_session({"edition": edition, "access_token": auth.get("accessToken"),
        "refresh_token": auth.get("refreshToken") or "", "uid": account.get("uid"),
        "enterprise_id": account.get("enterpriseId") or "", "domain": auth.get("domain") or ""}, edition)


def cookiecloud_login(edition, config, transport=None, read_cookies=None):
    """Create an independent NAS session through the current official web login flow."""
    if read_cookies is None:
        try:
            from common.cookiecloud import browser_cookies
        except ImportError:
            raise WorkBuddyError("cookiecloud_dependency_missing") from None
        read_cookies = browser_cookies
    host = "www.workbuddy.cn" if edition == "cn" else "www.workbuddy.ai"
    origin = "https://" + host
    transport = transport or HTTP()
    try:
        rows = read_cookies(config, host)
    except ImportError:
        raise WorkBuddyError("cookiecloud_dependency_missing") from None
    except (ValueError, OSError):
        raise WorkBuddyError("web_session_unavailable") from None
    for row in rows:
        transport.cookies.set_cookie(Cookie(
            0, row["name"], row["value"], None, False, row["domain"], True,
            row["domain"].startswith("."), row["path"], True, row["secure"],
            None if row["expires"] < 0 else int(row["expires"]), False, None, None, {}))
    headers = {"Accept": "application/json,text/html", "User-Agent": "Mozilla/5.0",
               "Referer": origin + "/login/", "X-Domain": host}
    status, raw = transport.navigate(origin + "/console/accounts", headers, origin)
    if status != 200:
        if status in {301, 302, 303, 307, 308, 401, 403}:
            raise WorkBuddyError("web_authentication_required")
        raise classify(status, {})
    try:
        accounts = envelope(status, raw)["accounts"]
    except WorkBuddyError as error:
        if error.reason != "invalid_platform_response":
            raise
        raise WorkBuddyError("web_authentication_required") from None
    except KeyError:
        raise WorkBuddyError("web_authentication_required") from None
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise WorkBuddyError("web_account_selection_required")
    account = accounts[0]
    if (not isinstance(account, dict) or not isinstance(account.get("uid"), str)
            or not account["uid"] or account.get("pluginEnabled") is not True
            or account.get("type") != "personal" or account.get("enterpriseId")):
        raise WorkBuddyError("web_account_selection_required")
    login = Login(edition, transport)
    login.start()
    platform = "CLI" if edition == "cn" else "workbuddy-ai"
    headers.update({"Accept": "application/json", "X-Product-Code": platform})
    # The official web grant mints a new refresh token; never copy a desktop session.
    token = envelope(*transport.request("POST", origin + "/console/login/enterprise?" +
                                       urlencode({"state": login.state}), headers))
    switched = envelope(*transport.request("POST", origin + "/console/account/switch",
        {**headers, "Content-Type": "application/json"}, {}))
    if switched.get("switched") is not True:
        raise WorkBuddyError("web_account_switch_unconfirmed")
    session = validate_session({"edition": edition, "access_token": token.get("accessToken"),
        "refresh_token": token.get("refreshToken") or "", "uid": account["uid"],
        "domain": host}, edition)
    if not session.get("refresh_token"):
        raise WorkBuddyError("refresh_token_missing")
    # Validate the newly issued bearer independently of browser cookies.
    transport.cookies.clear()
    client = Client(edition, session, lambda value: None, transport)
    identity = envelope(*transport.request("GET", login.base + "/v2/plugin/login/account",
                                          client.headers()))
    if identity.get("uid") != session["uid"] or identity.get("enterpriseId"):
        raise WorkBuddyError("web_account_identity_mismatch")
    return session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=("cn", "intl"), required=True)
    parser.add_argument("--session-file", type=Path, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--import-client", type=Path)
    source.add_argument("--cookiecloud-config", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if (not args.session_file.is_absolute() or root == args.session_file.resolve()
            or root in args.session_file.resolve().parents or not 30 <= args.timeout <= 600):
        parser.error("session-file must be an absolute private path outside this source tree; timeout must be 30..600")
    os.umask(0o077)
    try:
        args.session_file = credential_path(args.session_file)
        with Lease(args.session_file.with_name(args.session_file.name + ".lock")):
            if args.import_client:
                session = import_plaintext(read_private(args.import_client), args.edition)
            elif args.cookiecloud_config:
                session = cookiecloud_login(args.edition, args.cookiecloud_config,
                                           HTTP(os.environ.get("WORKBUDDY_PROXY")))
            else:
                login = Login(args.edition, HTTP(os.environ.get("WORKBUDDY_PROXY")))
                print("请在浏览器完成官方授权：\n" + login.start(), file=sys.stderr, flush=True)
                deadline = time.monotonic() + args.timeout
                while True:
                    try:
                        session = login.poll()
                        break
                    except WorkBuddyError as error:
                        if error.reason != "authorization_pending":
                            raise
                        if time.monotonic() >= deadline:
                            raise WorkBuddyError("authorization_timeout") from None
                        time.sleep(min(3, max(0, deadline - time.monotonic())))
            durable_json(args.session_file, session)
        print(json.dumps({"status": "saved", "edition": args.edition}))
        return 0
    except (WorkBuddyError, Busy, OSError, ValueError) as error:
        reason = error.reason if isinstance(error, WorkBuddyError) else "credential_lock_busy" if isinstance(error, Busy) else "credential_write_failed"
        print(json.dumps({"status": "failed", "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
