"""FastAPI router mounted by the existing personal-data webhook service."""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Request

from autoaccounting_store import BillStore, BillValidationError


router = APIRouter()
store = BillStore(os.environ.get("AUTOACCOUNTING_EXPORT_ROOT", "/home/hermes/.local/share/autoaccounting"))


def _token() -> str:
    inline = os.environ.get("AUTOACCOUNTING_WEBHOOK_TOKEN", "").strip()
    if inline:
        return inline
    token_file = os.environ.get(
        "AUTOACCOUNTING_WEBHOOK_TOKEN_FILE",
        "/home/hermes/.local/share/health-webhook/autoaccounting.token",
    )
    try:
        return open(token_file, encoding="utf-8").read().strip()
    except OSError:
        return ""


@router.post("/autoaccounting/v1/bills")
async def import_bill(request: Request, authorization: str | None = Header(default=None)):
    token = _token()
    expected = f"Bearer {token}"
    if not token or authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        payload = await request.json()
        return store.import_bill(payload)
    except BillValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=500, detail="storage failure") from None
