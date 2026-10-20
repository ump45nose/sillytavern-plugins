"""Read the precomputed AutoAccounting daily summary without touching JSONL."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor


class FinanceSource:
    """读取账单生产者生成的最小日汇总，不接触原始流水。"""

    def __init__(self, summary_dir: str | Path) -> None:
        """记录按业务日期保存 schema v1/v2 汇总的目录。"""

        self.summary_dir = Path(summary_dir)

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """校验当天汇总并转换为只含用途、金额和合计的证据。"""

        day = window.start.date().isoformat()
        path = self.summary_dir / f"{day}.json"
        if not path.is_file():
            return SourceResult("finance", warnings=["本日没有账单汇总"])
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
            self._validate(summary, day)
            occurred_at = datetime.fromisoformat(summary["generated_at"])
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=window.start.tzinfo)
            fact = self._format(summary)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
            return SourceResult("finance", warnings=["本日账单汇总格式无效"])
        evidence = Evidence(
            stable_evidence_id("finance", day, summary["source_jsonl_sha256"]),
            "finance",
            EvidenceKind.FINANCE_CHANGE,
            occurred_at,
            fact,
            subject="财务",
            source_ref=str(path),
            payload={
                "date": day,
                "record_count": summary["record_count"],
                "expense_items": self._expense_items(summary),
                "totals": self._totals(summary),
            },
        )
        return SourceResult("finance", [evidence], next_checkpoint=encode_cursor([evidence]))

    @staticmethod
    def _validate(summary: Any, day: str) -> None:
        """校验财务日汇总；消费描述为向后兼容的可选扩展字段。"""

        if not isinstance(summary, dict) or summary.get("schema_version") not in {1, 2}:
            raise ValueError("schema")
        if summary.get("date") != day or not isinstance(summary.get("currencies"), dict):
            raise ValueError("date/currencies")
        if not isinstance(summary.get("record_count"), int):
            raise ValueError("record_count")
        if not isinstance(summary.get("source_jsonl_sha256"), str):
            raise ValueError("hash")
        descriptions = summary.get("expense_descriptions")
        if descriptions is not None:
            if not isinstance(descriptions, dict):
                raise ValueError("expense_descriptions")
            items = descriptions.get("items")
            omitted_count = descriptions.get("omitted_count")
            if (
                not isinstance(items, list)
                or any(not isinstance(item, str) or not item.strip() for item in items)
                or isinstance(omitted_count, bool)
                or not isinstance(omitted_count, int)
                or omitted_count < 0
            ):
                raise ValueError("expense_descriptions")
        expense_items = summary.get("expense_items")
        if expense_items is not None:
            if not isinstance(expense_items, list):
                raise ValueError("expense_items")
            for item in expense_items:
                if not isinstance(item, dict):
                    raise ValueError("expense_item")
                if not all(isinstance(item.get(key), str) and item[key].strip() for key in ("label", "amount", "currency")):
                    raise ValueError("expense_item fields")

    @staticmethod
    def _format(summary: dict[str, Any]) -> str:
        """渲染只包含消费用途和必要非零收支的终稿摘要。"""

        parts: list[str] = []
        expense_items = FinanceSource._expense_items(summary)
        if expense_items:
            details = "、".join(
                f"{item['label']} {FinanceSource._money(item['amount'], item['currency'])}"
                for item in expense_items
            )
            parts.append(f"买了：{details}")
        totals = FinanceSource._totals(summary)
        for currency, values in sorted(totals.items()):
            if FinanceSource._nonzero(values["expense"]):
                parts.append(f"共花 {FinanceSource._money(values['expense'], currency)}")
            if FinanceSource._nonzero(values["income"]):
                parts.append(f"收入 {FinanceSource._money(values['income'], currency)}")
            if FinanceSource._nonzero(values["refund"]):
                parts.append(f"退款 {FinanceSource._money(values['refund'], currency)}")
        return "；".join(parts) if parts else "今天没有支出"

    @staticmethod
    def _expense_items(summary: dict[str, Any]) -> list[dict[str, str]]:
        """读取 schema v2 的逐项金额；旧汇总不猜测金额归属。"""

        values = summary.get("expense_items", [])
        return [dict(item) for item in values if isinstance(item, dict)] if isinstance(values, list) else []

    @staticmethod
    def _totals(summary: dict[str, Any]) -> dict[str, dict[str, str]]:
        """把上游币种字段压缩成用户展示需要的三项合计。"""

        result: dict[str, dict[str, str]] = {}
        for currency, values in summary.get("currencies", {}).items():
            if not isinstance(values, dict):
                continue
            result[str(currency)] = {
                "expense": str(values.get("expense_net_money") or "0"),
                "income": str(values.get("income_money") or "0"),
                "refund": str(values.get("refund_money") or "0"),
            }
        return result

    @staticmethod
    def _money(value: str, currency: str) -> str:
        """使用常见币种符号渲染金额。"""

        symbol = {"CNY": "¥", "USD": "$", "EUR": "€"}.get(currency, f"{currency} ")
        return f"{symbol}{value}"

    @staticmethod
    def _nonzero(value: str) -> bool:
        """判断金额文本是否为非零。"""

        try:
            return float(value) != 0
        except (TypeError, ValueError):
            return False
