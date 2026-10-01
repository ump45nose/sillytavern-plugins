"""Run with the separately installed pinned provider environment. No network."""

from platforms.v2ex.provider import V2ex
from platforms.v2ex.adapter import classify


class Response:
    def __init__(self, text):
        self.text = text


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/balance"):
            return Response(
                '<td class="d"><span class="gray">20261001 每日登录奖励</span></td><td class="d" style="text-align: right;">1.00</td><a href="/member/test" class="top">fixture</a>'
            )
        return Response(
            '<input type="button" class="super normal button" value="领取" onclick="location.href = \'/mission/daily/redeem?once=fixture\';" /><div class="cell">1天</div>'
        )


session = FakeSession()
assert classify(V2ex.sign(session), "2026-10-01")
assert len(session.calls) == 4
print("Pinned dailycheckin provider fake-session contract passed; no network")
