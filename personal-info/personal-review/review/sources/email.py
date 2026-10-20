"""消费配置时间生成的邮件摘要文件，不直接读取邮箱正文。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor, is_after_cursor
from review.sources.email_policy import EmailCandidatePolicy


class EmailBriefSource:
    """把现有邮件 MCP 产生的结构化摘要转换为候选事实。"""

    def __init__(self, directory: str | Path, policy: dict) -> None:
        """记录每日摘要目录并加载来源级过滤规则。"""

        self.directory = Path(directory)
        self.policy = EmailCandidatePolicy(policy)
        aggregation = policy["sources"]["aggregation"]
        self.github_sender_patterns = tuple(
            str(value).strip().lower() for value in aggregation["github_sender_patterns"] if str(value).strip()
        )
        self.github_subject_patterns = tuple(
            str(value).strip().lower() for value in aggregation["github_subject_patterns"] if str(value).strip()
        )
        self.github_max_subjects = int(aggregation["github_max_subjects"])

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """仅读取窗口结束日期对应的定时摘要。"""

        path = self.directory / f"{window.end.astimezone(window.start.tzinfo):%Y-%m-%d}.json"
        if not path.is_file():
            return SourceResult("email", warnings=["邮件摘要未就绪"])
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SourceResult("email", warnings=["邮件摘要无法解析"])
        items = payload.get("evidence", payload.get("important", [])) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return SourceResult("email", warnings=["邮件摘要结构不兼容"])

        evidence: list[Evidence] = []
        github_items: list[tuple[datetime, str, str, EvidenceKind]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_fact = str(item.get("fact") or item.get("summary") or "").strip()
            subject = str(item.get("subject") or "").strip()
            sender = str(item.get("sender") or "").strip()
            assessment = self.policy.assess(subject, sender, raw_fact)
            if assessment is None:
                continue
            occurred = self._parse_time(item.get("occurred_at"), window.end)
            source_ref = str(item.get("source_ref", path.name))
            if not is_after_cursor(occurred, source_ref, checkpoint):
                continue
            if self._is_github(sender, subject):
                # GitHub 通知按来源内聚合，避免一组 PR/Issue 通知挤占整份日报。
                github_items.append((occurred, source_ref, assessment.subject, assessment.kind))
                continue
            evidence.append(
                Evidence(
                    stable_evidence_id("email", occurred.isoformat(), assessment.fact),
                    "email",
                    assessment.kind,
                    occurred,
                    assessment.fact,
                    subject=assessment.subject,
                    source_ref=source_ref,
                )
            )
        if github_items:
            evidence.append(self._github_summary(github_items))
        return SourceResult("email", evidence, list(payload.get("errors", [])), encode_cursor(evidence))

    def _is_github(self, sender: str, subject: str) -> bool:
        """按发件域名或 GitHub 特有主题模式识别通知。"""

        normalized_sender = str(sender or "").strip().lower()
        normalized_subject = str(subject or "").strip().lower()
        return any(pattern in normalized_sender for pattern in self.github_sender_patterns) or any(
            pattern in normalized_subject for pattern in self.github_subject_patterns
        )

    def _github_summary(self, items: list[tuple[datetime, str, str, EvidenceKind]]) -> Evidence:
        """把同日 GitHub 通知浓缩成一条仍可判断的来源摘要。"""

        ordered = sorted(items, key=lambda value: (value[0], value[1]))
        subjects = list(dict.fromkeys(value[2] for value in ordered))
        shown = subjects[: self.github_max_subjects]
        omitted = max(0, len(subjects) - len(shown))
        details = "；".join(shown)
        if omitted:
            details += f"；另 {omitted} 个主题已折叠"
        fact = f"GitHub 通知摘要：{len(items)} 条"
        if details:
            fact += f"（{details}）"
        occurred, source_ref = ordered[-1][0], ordered[-1][1]
        kind = EvidenceKind.BLOCKER if any(value[3] == EvidenceKind.BLOCKER for value in ordered) else EvidenceKind.EXTERNAL_FEEDBACK
        return Evidence(
            stable_evidence_id("email", occurred.isoformat(), fact),
            "email",
            kind,
            occurred,
            fact,
            subject="GitHub 通知摘要",
            source_ref=f"github:{source_ref}",
            payload={"category": "github", "subjects": shown, "notification_count": len(items)},
        )

    @staticmethod
    def _parse_time(value: Any, fallback: datetime) -> datetime:
        """解析邮件事件时间，失败时使用冻结窗口末端。"""

        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=fallback.tzinfo)
            except ValueError:
                pass
        return fallback
