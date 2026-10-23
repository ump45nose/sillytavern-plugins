"""Google no-agent 采集脚本的代理安全边界测试。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts/work_google_daily_input.py"
SPEC = importlib.util.spec_from_file_location("work_google_daily_input", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GoogleInputTests(unittest.TestCase):
    """验证脚本只加载允许的代理字段。"""

    def test_proxy_loader_does_not_import_other_secrets(self) -> None:
        """Hermes ENV 中的 Token 等变量不得进入 Google 采集子进程。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "HTTPS_PROXY=http://127.0.0.1:7890\n"
                "NO_PROXY=127.0.0.1,localhost\n"
                "MCP_MEMOS_API_KEY=should-not-load\n",
                encoding="utf-8",
            )
            path.chmod(0o660)
            old_proxy = os.environ.pop("HTTPS_PROXY", None)
            old_no_proxy = os.environ.pop("NO_PROXY", None)
            old_secret = os.environ.pop("MCP_MEMOS_API_KEY", None)
            try:
                MODULE._load_proxy_environment(path)
                self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:7890")
                self.assertEqual(os.environ["NO_PROXY"], "127.0.0.1,localhost")
                self.assertNotIn("MCP_MEMOS_API_KEY", os.environ)
            finally:
                for key, value in (
                    ("HTTPS_PROXY", old_proxy),
                    ("NO_PROXY", old_no_proxy),
                    ("MCP_MEMOS_API_KEY", old_secret),
                ):
                    os.environ.pop(key, None)
                    if value is not None:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
