"""Atomic JSONL storage and daily summaries for AutoAccounting bills."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any
from zoneinfo import ZoneInfo


ZONE = ZoneInfo("Asia/Shanghai")
VALID_STATES = {"Synced", "Edited", "Wait2Edit"}
VALID_TYPES = {
    "Expend", "ExpendReimbursement", "ExpendLending", "ExpendRepayment",
    "Income", "IncomeLending", "IncomeRepayment", "IncomeReimbursement",
    "IncomeRefund", "Transfer",
}
EXCLUDED_TYPES = VALID_TYPES - {"Income", "Expend", "IncomeRefund"}
EXPENSE_DESCRIPTION_FIELDS = ("shopItem", "cateName", "remark", "shopName")
MAX_EXPENSE_DESCRIPTIONS = 6
MAX_EXPENSE_DESCRIPTION_CHARS = 30


class BillValidationError(ValueError):
    pass


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise BillValidationError(f"{field} must be a finite number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BillValidationError(f"{field} must be a finite number") from None
    if not number.is_finite():
        raise BillValidationError(f"{field} must be a finite number")
    return number


def validate_bill(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BillValidationError("body must be an object")
    bill = dict(payload)
    bill_id = bill.get("id")
    if isinstance(bill_id, bool) or not isinstance(bill_id, int) or bill_id <= 0:
        raise BillValidationError("id must be a positive integer")
    if bill.get("state") not in VALID_STATES:
        raise BillValidationError("unknown state")
    if bill.get("type") not in VALID_TYPES:
        raise BillValidationError("unknown type")
    timestamp = bill.get("time")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
        raise BillValidationError("time must be a positive epoch millisecond value")
    _decimal(bill.get("money"), "money")
    _decimal(bill.get("fee"), "fee")
    flag = bill.get("flag", 0)
    if isinstance(flag, bool) or not isinstance(flag, int):
        raise BillValidationError("flag must be an integer")
    return bill


def _currency_code(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return "UNKNOWN"
    value = raw.strip()
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
            code = parsed.get("code") if isinstance(parsed, dict) else None
            if isinstance(code, str) and code.strip():
                return code.strip().upper()
        except json.JSONDecodeError:
            pass
    return value.upper()


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _expense_description(record: dict[str, Any]) -> str:
    """从账单中选择最接近“买了什么”的字段，并做空白归一化与限长。"""

    for field in EXPENSE_DESCRIPTION_FIELDS:
        raw = record.get(field)
        if not isinstance(raw, str):
            continue
        # 摘要只保留单行短文本，不带账户名、渠道或完整原始流水。
        value = " ".join(raw.split())
        if value:
            return value[:MAX_EXPENSE_DESCRIPTION_CHARS]
    return "未分类消费"


class BillStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.bills_dir = self.root / "bills"
        self.summary_dir = self.root / "summary"
        self.state_dir = self.root / ".state"
        for directory in (self.bills_dir, self.summary_dir, self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.state_dir / "store.lock"
        self.index_path = self.state_dir / "bill-index.json"

    @contextmanager
    def _lock(self):
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def import_bill(self, raw_payload: Any) -> dict[str, Any]:
        bill = validate_bill(raw_payload)
        day = datetime.fromtimestamp(bill["time"] / 1000, tz=ZONE).date().isoformat()
        now = datetime.now(tz=ZONE).isoformat()
        bill_id = str(bill["id"])
        with self._lock():
            index = self._read_index()
            old_day = index.get(bill_id)
            old_records = self._read_records(old_day) if old_day else {}
            previous = old_records.get(bill_id)
            first_seen = previous.get("first_seen_at") if previous else now
            action = "created" if previous is None else (
                "unchanged" if self._same_bill(previous, bill) and old_day == day else "updated"
            )

            if old_day and old_day != day:
                old_records.pop(bill_id, None)
                self._write_day(old_day, old_records)

            records = old_records if old_day == day else self._read_records(day)
            records[bill_id] = {**bill, "first_seen_at": first_seen, "last_seen_at": now}
            self._write_day(day, records)
            index[bill_id] = day
            self._atomic_json(self.index_path, index)
            summary = self._write_summary(day, records)
            if old_day and old_day != day:
                self._write_summary(old_day, old_records)

        return {
            "ok": True,
            "bill_id": bill["id"],
            "date": day,
            "action": action,
            "summary_updated_at": summary["generated_at"],
        }

    @staticmethod
    def _same_bill(record: dict[str, Any], bill: dict[str, Any]) -> bool:
        return {key: value for key, value in record.items() if key not in {"first_seen_at", "last_seen_at"}} == bill

    def _read_index(self) -> dict[str, str]:
        if not self.index_path.is_file():
            return {}
        value = json.loads(self.index_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("bill index is invalid")
        return {str(key): str(day) for key, day in value.items()}

    def _read_records(self, day: str | None) -> dict[str, dict[str, Any]]:
        if not day:
            return {}
        path = self.bills_dir / f"{day}.jsonl"
        if not path.is_file():
            return {}
        records: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            records[str(value["id"])] = value
        return records

    def _write_day(self, day: str, records: dict[str, dict[str, Any]]) -> None:
        data = "".join(
            json.dumps(records[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for key in sorted(records, key=int)
        ).encode("utf-8")
        self._atomic_bytes(self.bills_dir / f"{day}.jsonl", data)

    def _write_summary(self, day: str, records: dict[str, dict[str, Any]]) -> dict[str, Any]:
        state_counts = {"Synced": 0, "Edited": 0, "New": 0}
        currencies: dict[str, dict[str, Any]] = {}
        excluded: dict[str, dict[str, Any]] = {}
        expense_totals: dict[tuple[str, str], Decimal] = {}
        for record in records.values():
            state = "New" if record["state"] == "Wait2Edit" else record["state"]
            state_counts[state] += 1
            code = _currency_code(record.get("currency"))
            bucket = currencies.setdefault(code, {
                "income_money": Decimal(0),
                "expense_gross_money": Decimal(0),
                "refund_money": Decimal(0),
                "fee_total": Decimal(0),
                "fee_by_type": {},
            })
            bill_type = record["type"]
            money = _decimal(record["money"], "money")
            fee = _decimal(record["fee"], "fee")
            flag = record.get("flag", 0)
            if isinstance(flag, bool) or not isinstance(flag, int):
                raise BillValidationError("flag must be an integer")
            bucket["fee_total"] += fee
            bucket["fee_by_type"][bill_type] = bucket["fee_by_type"].get(bill_type, Decimal(0)) + fee
            excluded_from_cashflow = bill_type in EXCLUDED_TYPES or (flag & 1) != 0
            if excluded_from_cashflow:
                excluded_bucket = excluded.setdefault(bill_type, {"count": 0, "money_by_currency": {}})
                excluded_bucket["count"] += 1
                excluded_bucket["money_by_currency"][code] = (
                    excluded_bucket["money_by_currency"].get(code, Decimal(0)) + money
                )
            elif bill_type == "Income":
                bucket["income_money"] += money
            elif bill_type == "Expend":
                bucket["expense_gross_money"] += money
                description = _expense_description(record)
                expense_key = (description, code)
                expense_totals[expense_key] = expense_totals.get(expense_key, Decimal(0)) + money
            elif bill_type == "IncomeRefund":
                bucket["refund_money"] += money

        normalized: dict[str, Any] = {}
        for code, bucket in sorted(currencies.items()):
            net_expense = bucket["expense_gross_money"] - bucket["refund_money"]
            normalized[code] = {
                "income_money": _money(bucket["income_money"]),
                "expense_gross_money": _money(bucket["expense_gross_money"]),
                "refund_money": _money(bucket["refund_money"]),
                "expense_net_money": _money(net_expense),
                "net_money": _money(bucket["income_money"] - net_expense),
                "fee": {
                    "total": _money(bucket["fee_total"]),
                    "by_type": {key: _money(value) for key, value in sorted(bucket["fee_by_type"].items())},
                },
            }
        normalized_excluded = {
            key: {
                "count": value["count"],
                "money_by_currency": {code: _money(amount) for code, amount in sorted(value["money_by_currency"].items())},
            }
            for key, value in sorted(excluded.items())
        }
        bill_path = self.bills_dir / f"{day}.jsonl"
        source_bytes = bill_path.read_bytes()
        summary = {
            "schema_version": 2,
            "date": day,
            "timezone": "Asia/Shanghai",
            "generated_at": datetime.now(tz=ZONE).isoformat(),
            "record_count": len(records),
            "state_counts": state_counts,
            "currencies": normalized,
            "excluded": normalized_excluded,
            "expense_items": [
                {"label": label, "amount": _money(amount), "currency": currency}
                for (label, currency), amount in sorted(expense_totals.items())[:MAX_EXPENSE_DESCRIPTIONS]
            ],
            "source_jsonl_sha256": hashlib.sha256(source_bytes).hexdigest(),
        }
        self._atomic_json(self.summary_dir / f"{day}.json", summary)
        return summary

    def _atomic_json(self, path: Path, value: Any) -> None:
        data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        self._atomic_bytes(path, data)

    @staticmethod
    def _atomic_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
