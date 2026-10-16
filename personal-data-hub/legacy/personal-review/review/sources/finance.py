"""Financial evidence from Personal Records; no daily files or raw payloads."""
from datetime import timedelta
import hashlib
import json
from personal_records.client import RecordsClient
from review.domain import Evidence, EvidenceKind
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor


class FinanceSource:
    def __init__(self, client=None): self.client = client

    def collect(self, window, checkpoint):
        client = self.client or RecordsClient.from_file()
        first, last = window.start.date().isoformat(), (window.end-timedelta(microseconds=1)).date().isoformat()
        data = client.bill_summary(first, last)
        if not data["count"] and not data["pending_count"]:
            return SourceResult("finance", warnings=["本日没有账单记录"])
        items = [{"label": b.get("item") or b.get("merchant") or b.get("category") or "消费", "amount": b["amount"], "currency": b["currency"]}
            for b in client.iter_bills(first, last, type="expense", status="confirmed")]
        parts = [f"{r['type']} {r['amount']} {r['currency']}（{r['count']} 笔）" for r in data["totals"]]
        if data["pending_count"]: parts.append(f"待确认 {data['pending_count']} 笔")
        digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        evidence = Evidence(stable_evidence_id("finance", first, digest), "finance", EvidenceKind.FINANCE_CHANGE,
            window.end-timedelta(microseconds=1), "；".join(parts), subject="财务", source_ref=client.base_url+"/api/v1/bills/summary",
            payload={**data, "expense_items": items})
        return SourceResult("finance", [evidence], next_checkpoint=encode_cursor([evidence]))
