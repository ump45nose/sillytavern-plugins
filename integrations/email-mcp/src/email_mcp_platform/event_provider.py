"""mcp-email-server 1.11.0 的受限头部适配；从不 FETCH 正文或修改标记。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.parser import BytesHeaderParser
from email.policy import default
from types import SimpleNamespace
from typing import Any

from .events import Cursor, HeaderMail, MailState, Observation, _key

HEADER_NAMES = (
    "SUBJECT", "FROM", "TO", "CC", "DATE", "MESSAGE-ID", "IN-REPLY-TO",
    "AUTO-SUBMITTED", "LIST-ID", "LIST-UNSUBSCRIBE", "PRECEDENCE",
)
MAX_HEADER_BYTES = 32_768
MAX_UID_WINDOW = 1_000
FETCH_HEADERS = (
    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (" + " ".join(HEADER_NAMES)
    + ")]<0." + str(MAX_HEADER_BYTES + 1) + ">)"
)

MINIMAL_FETCH_HEADERS = (
    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO IN-REPLY-TO "
    "AUTO-SUBMITTED LIST-ID LIST-UNSUBSCRIBE PRECEDENCE)]<0."
    + str(MAX_HEADER_BYTES + 1) + ">)"
)


class HeaderTooLarge(ValueError):
    def __init__(self, uid: int):
        super().__init__("Header exceeded bounded read")
        self.uid = uid


@dataclass(frozen=True)
class ProviderAccess:
    client: Any
    identity: str
    own_addresses: tuple[str, ...]
    allowed_senders: tuple[str, ...]


def parse_header_fetch(data, expected: set[int]) -> dict[int, HeaderMail]:
    """接受 UID 位于 literal 前或后的响应；超长独立分类，其余异常保留游标。"""
    if not isinstance(data, (list, tuple)):
        raise ValueError("Invalid header response")
    result = {}
    for index, item in enumerate(data):
        if not isinstance(item, bytes) or not re.search(rb"BODY\[HEADER\.FIELDS", item, re.I):
            continue
        if index + 1 >= len(data) or not isinstance(data[index + 1], (bytes, bytearray)):
            raise ValueError("Missing header literal")
        raw = bytes(data[index + 1])
        after = data[index + 2] if index + 2 < len(data) else b""
        protocol = item + b" " + (after if isinstance(after, bytes) else b"")
        match = re.search(rb"\bUID\s+([0-9]+)\b", protocol, re.I)
        if not match:
            raise ValueError("Missing header UID")
        uid = int(match[1])
        if uid not in expected or uid in result:
            raise ValueError("Unexpected or duplicate header UID")
        literal_size = re.search(rb"\{([0-9]+)\}\s*$", item)
        if literal_size is None or int(literal_size[1]) != len(raw):
            raise ValueError("Incomplete header literal")
        if len(raw) > MAX_HEADER_BYTES:
            raise HeaderTooLarge(uid)
        message = BytesHeaderParser(policy=default).parsebytes(raw)
        headers = {
            name.casefold(): ", ".join(str(value) for value in message.get_all(name, []))
            for name in HEADER_NAMES if name in message
        }
        flags_match = re.search(rb"\bFLAGS\s+\(([^)]*)\)", protocol, re.I)
        if flags_match is None:
            raise ValueError("Missing header flags")
        flags = tuple(flags_match[1].decode("ascii", errors="strict").split())
        if len(flags) > 100 or any(len(flag) > 256 for flag in flags):
            raise ValueError("Invalid header flags")
        result[uid] = HeaderMail(uid, headers, flags)
    if set(result) != expected:
        raise ValueError("Incomplete header observation")
    return result


class UpstreamHeaderProvider:
    """每次连接前重新核对上游 incoming authority；不枚举或自动绑定其他账号。"""

    def __init__(self, *, access_factory=None, protocol=None):
        self._access_factory = access_factory
        self._protocol = protocol
        self._modes = {}

    def _open(self, account: str) -> ProviderAccess:
        if self._access_factory:
            return self._access_factory(account)
        from mcp_email_server.adapters.authority import resolve_local_account
        from mcp_email_server.emails.classic import ClassicEmailHandler

        resolved = resolve_local_account(
            account, roles=("incoming",), expected_mode=self._modes.get(account)
        )
        self._modes[account] = resolved.mode
        incoming = resolved.account.incoming
        identity = _key(
            incoming.host.casefold(), incoming.port, incoming.user_name,
            resolved.account.email_address.casefold(),
        )
        return ProviderAccess(
            ClassicEmailHandler(resolved.account).incoming_client, identity,
            (resolved.account.email_address,), tuple(resolved.settings.allowed_senders),
        )

    def _helpers(self):
        if self._protocol:
            return self._protocol
        from mcp_email_server.config import sender_allowed
        from mcp_email_server.emails.classic import (
            _imap_login,
            _normalize_search_uids,
            _quote_mailbox,
            _raise_for_imap_command_failure,
            _send_imap_id,
        )

        return SimpleNamespace(
            login=_imap_login, send_id=_send_imap_id, quote=_quote_mailbox,
            check=_raise_for_imap_command_failure, normalize=_normalize_search_uids,
            sender_allowed=sender_allowed,
        )

    @staticmethod
    async def _fetch(imap, helper, chunk: list[int], *, minimal=False):
        fields = MINIMAL_FETCH_HEADERS if minimal else FETCH_HEADERS
        response = await imap.uid("fetch", ",".join(map(str, chunk)), fields)
        helper.check(response, "FETCH event headers")
        return parse_header_fetch(response[1], set(chunk))

    async def observe(self, account: str, mailbox: str, cursor: Cursor | None,
                      limit: int) -> Observation:
        if not 1 <= limit <= 100 or not mailbox or any(ord(c) < 32 for c in mailbox):
            raise ValueError("Invalid bounded observation request")
        access, helper = self._open(account), self._helpers()
        client = access.client
        imap = await client._connect_imap()
        try:
            await helper.login(
                imap, client.email_server.user_name,
                client.email_server.password.get_secret_value(),
            )
            await helper.send_id(imap)
            before = await client._status_mailbox(imap, mailbox)
            state = MailState(access.identity, before.uidvalidity, before.uidnext)
            if (cursor is None or cursor.identity != state.identity
                    or cursor.uidvalidity != state.uidvalidity
                    or state.uidnext - 1 <= cursor.last_uid):
                return Observation(state, (), state.uidnext - 1, access.own_addresses)
            response = await imap.examine(helper.quote(mailbox))
            helper.check(response, "EXAMINE event mailbox")
            high = min(state.uidnext - 1, cursor.last_uid + MAX_UID_WINDOW)
            response = await imap.uid_search(
                "UID", f"{cursor.last_uid + 1}:{high}", charset=None
            )
            helper.check(response, "SEARCH new event UIDs")
            uids = sorted(int(uid) for uid in helper.normalize(response[1]))
            if (len(uids) != len(set(uids))
                    or any(not cursor.last_uid < uid <= high for uid in uids)):
                raise ValueError("Provider returned UIDs outside the requested window")
            selected = uids[:limit]
            through = selected[-1] if len(uids) > limit else high
            headers = {}
            # 每次最多 8 个受限 literal，控制单个响应的体积。
            for index in range(0, len(selected), 8):
                chunk = selected[index:index + 8]
                try:
                    headers.update(await self._fetch(imap, helper, chunk))
                except HeaderTooLarge:
                    # 只降级确定收到的超长 literal；网络、缺 UID、截断响应仍失败留游标。
                    for uid in chunk:
                        try:
                            headers.update(await self._fetch(imap, helper, [uid], minimal=True))
                        except HeaderTooLarge as exc:
                            if exc.uid != uid:
                                raise
                            headers[uid] = HeaderMail(
                                uid, {}, observation_error="header_too_large"
                            )
            after = await client._status_mailbox(imap, mailbox)
            state = MailState(access.identity, after.uidvalidity, after.uidnext)
            if before.uidvalidity != after.uidvalidity or after.uidnext < before.uidnext:
                return Observation(state, (), state.uidnext - 1, access.own_addresses)
            # 上游发件人白名单仍是读取边界，不因事件功能而放宽。
            visible = tuple(
                headers[uid] for uid in selected
                if helper.sender_allowed(
                    headers[uid].headers.get("from", ""), list(access.allowed_senders)
                )
            )
            failures = tuple(
                (uid, headers[uid].observation_error) for uid in selected
                if headers[uid].observation_error
            )
            return Observation(state, visible, through, access.own_addresses, failures)
        except Exception:
            raise RuntimeError("Email header observation failed") from None
        finally:
            try:
                await imap.logout()
            except Exception:
                pass
