"""Packaged WeChat entry point; access checks never export conversation data."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "packages"))
# The integrated client archives source data only. Legacy CRM settings must not
# re-enable automatic facts, which the collection-only server rejects.
os.environ["WECHAT_FACT_EXTRACTION"] = "false"

if sys.argv[1:] == ["--access-check"]:
    from personal_crm.connector.config import ConnectorConfig
    config = ConnectorConfig.from_env()
    root = Path(os.getenv("CHATLOG_WECHAT_DATA_ROOT") or str(
        Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"))
    try:
        list(root.iterdir())
        result = subprocess.run([config.chatlog_executable, "directory", "--source", "wechat"],
                                capture_output=True, text=True, timeout=config.timeout)
        directory = json.loads(result.stdout)
        readable = result.returncode == 0 and directory.get("available") is True
        print(json.dumps({"readable": readable, "error": None if readable else "wechat_unavailable"}), flush=True)
        raise SystemExit(0 if readable else 1)
    except PermissionError:
        print(json.dumps({"readable": False, "error": "authorization_required"}), flush=True)
        raise SystemExit(2)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print(json.dumps({"readable": False, "error": "wechat_unavailable"}), flush=True)
        raise SystemExit(1)

from personal_crm.connector.cli import main
raise SystemExit(main())
