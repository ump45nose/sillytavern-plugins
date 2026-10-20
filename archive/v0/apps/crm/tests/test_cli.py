"""Personal CRM 运维 CLI 的确定性输出测试。"""

import json

from personal_crm.app.cli import main


def test_daily_summary_cli_returns_body_free_aggregate(tmp_path, monkeypatch, capsys):
    """每日汇总 CLI 应返回可导入结构，空库也不能伪造关系正文。"""

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'crm.db'}")
    result = main(["daily-summary", "--date", "2026-09-06", "--timezone", "Asia/Shanghai"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["date"] == "2026-09-06"
    assert payload["interactions"]["count"] == 0
    assert payload["facts"]["count"] == 0
    assert payload["reminder_changes"]["count"] == 0
