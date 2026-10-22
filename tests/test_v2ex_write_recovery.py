"""Smoke: an ambiguous redemption is reconciled without a second write."""

import tempfile
import unittest
from pathlib import Path

from platforms.v2ex.adapter import execute
from test_v2ex import Cookies


class RecoverySmoke(unittest.TestCase):
    def test_redeem_error_reads_balance_without_repeating_write(self):
        calls = []
        context = {
            "run_id": "smoke",
            "platform": "v2ex",
            "account": "default",
            "business_date": "2026-10-03",
        }

        class Session:
            headers = {}
            proxies = {}
            cookies = Cookies()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        class Provider:
            @staticmethod
            def sign(session, *, read_only=False, before_write=None, on_balance=None):
                calls.append(read_only)
                if not read_only:
                    before_write()
                    raise ValueError("unexpected_redirect")
                rows = [{"name": "今日签到", "value": "20261003 的每日登录奖励"}]
                on_balance(rows)
                return rows

        with tempfile.TemporaryDirectory() as directory:
            output = execute(
                context, Provider, Session, "A2=session-cookie", state_dir=Path(directory)
            )
        self.assertEqual(calls, [False, True])
        self.assertEqual(output["execution_status"], "ok")
        self.assertEqual(output["business"]["reward"], "complete")


if __name__ == "__main__":
    unittest.main()
