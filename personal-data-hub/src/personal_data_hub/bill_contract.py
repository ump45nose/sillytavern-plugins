from __future__ import annotations

from decimal import Decimal, InvalidOperation

from typing import Any

VALID_STATES = {"Synced", "Edited", "Wait2Edit"}

VALID_TYPES = {
    "Expend", "ExpendReimbursement", "ExpendLending", "ExpendRepayment",
    "Income", "IncomeLending", "IncomeRepayment", "IncomeReimbursement",
    "IncomeRefund", "Transfer",
}

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
