"""Health report evidence from the canonical business API."""
from datetime import timedelta
import hashlib
import json
from personal_records.client import RecordsClient
from review.domain import Evidence, EvidenceKind
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor


class HealthSource:
    def __init__(self, metrics=None, client=None):
        self.metrics = metrics
        self.client = client

    def collect(self, window, checkpoint):
        client = self.client or RecordsClient.from_file()
        first, last = window.start.date().isoformat(), (window.end-timedelta(microseconds=1)).date().isoformat()
        data = client.health_summary(first, last)
        if not data["days"]:
            return SourceResult("health", warnings=["本日没有健康记录"])
        values, parts = {}, []
        fields = {"steps": ("steps", "步数", "步", "total", 1),
            "active_calories": ("active_calories_kcal", "活动热量", "千卡", "total", 1),
            "total_calories": ("total_calories_kcal", "总热量", "千卡", "total", 1),
            "heart_rate": ("heart_rate", "平均心率", "次/分", "average", 1),
            "resting_heart_rate": ("resting_heart_rate", "静息心率", "次/分", "average", 1),
            "oxygen_saturation": ("oxygen_saturation", "血氧", "%", "average", 1),
            "sleep": ("sleep", "睡眠", "小时", "duration_seconds", 3600),
            "exercise": ("exercise", "运动", "分钟", "duration_seconds", 60)}
        for name, (metric, label, unit, stat, divisor) in fields.items():
            if self.metrics and name not in self.metrics and metric not in self.metrics: continue
            value = data["metrics"][metric].get(stat)
            if value is not None:
                values[name] = value/divisor
                parts.append(f"{label} {value/divisor:g} {unit}")
        if not parts: return SourceResult("health", warnings=["本日没有所选健康指标"])
        digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        evidence = Evidence(stable_evidence_id("health", first, digest), "health", EvidenceKind.HEALTH_CHANGE,
            window.end-timedelta(microseconds=1), "；".join(parts), subject="健康", source_ref=client.base_url+"/api/v1/health/summary",
            payload={**values, "summary": data})
        return SourceResult("health", [evidence], next_checkpoint=encode_cursor([evidence]))
