"""保存并读取 GitHub MCP 预计算的每日 Git 活动汇总。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor


MAX_SUBJECTS_PER_REPOSITORY = 5


def _clean_subject(value: Any) -> str:
    """清理提交主题中的换行和多余空白，避免污染材料结构。"""

    return " ".join(str(value or "").split())[:180]


def _repository_summary(subjects: list[str]) -> str:
    """从有限提交主题确定性提炼仓库重点，不调用第二个模型。"""

    cleaned = list(dict.fromkeys(_clean_subject(value) for value in subjects if _clean_subject(value)))
    return "；".join(cleaned[:3])


def store_git_mcp_summary(
    summary_dir: str | Path,
    day: str,
    payload: Any,
    generated_at: datetime,
) -> dict[str, Any]:
    """校验 Agent 的最小 MCP 结果，并原子写成日报来源协议。"""

    if not isinstance(payload, dict) or not isinstance(payload.get("user"), str) or not payload["user"].strip():
        raise ValueError("Git MCP 汇总缺少认证用户")
    repositories = payload.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("Git MCP 汇总 repositories 必须是数组")
    grouped: dict[str, dict[str, Any]] = {}
    for item in repositories:
        if not isinstance(item, dict):
            raise ValueError("Git MCP 仓库项必须是对象")
        name = item.get("name")
        count = item.get("commit_count")
        if not isinstance(name, str) or not name.strip() or "/" not in name:
            raise ValueError("Git MCP 仓库名必须是 owner/repo")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("Git MCP commit_count 必须是正整数")
        subjects = item.get("subjects", [])
        if not isinstance(subjects, list) or any(not isinstance(value, str) for value in subjects):
            raise ValueError("Git MCP subjects 必须是字符串数组")
        key = name.strip()
        current = grouped.setdefault(key, {"commit_count": 0, "subjects": []})
        current["commit_count"] += count
        current["subjects"].extend(_clean_subject(value) for value in subjects if _clean_subject(value))
    rendered = [
        {
            "name": name,
            "commit_count": values["commit_count"],
            "subjects": list(dict.fromkeys(values["subjects"]))[:MAX_SUBJECTS_PER_REPOSITORY],
            "summary": _repository_summary(values["subjects"]),
        }
        for name, values in sorted(grouped.items())
    ]
    canonical = json.dumps(
        {"user": payload["user"].strip(), "date": day, "repositories": rendered},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    summary = {
        "schema_version": 2,
        "date": day,
        "user": payload["user"].strip(),
        "timezone": str(generated_at.tzinfo),
        "generated_at": generated_at.isoformat(),
        "repo_count": len(rendered),
        "commit_count": sum(item["commit_count"] for item in rendered),
        "repositories": rendered,
        "source_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    destination = Path(summary_dir) / f"{day}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)
    # 成功产物覆盖同日失败状态；状态文件从不保存远端错误正文。
    status_path = Path(summary_dir) / ".status" / f"{day}.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps({"date": day, "status": "success", "generated_at": generated_at.isoformat()}) + "\n",
        encoding="utf-8",
    )
    return {"date": day, "repo_count": summary["repo_count"], "commit_count": summary["commit_count"]}


def store_git_failure(summary_dir: str | Path, day: str, generated_at: datetime) -> dict[str, Any]:
    """记录一次不含错误正文的 Git 拉取失败，避免被误判为零提交。"""

    status_path = Path(summary_dir) / ".status" / f"{day}.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps({"date": day, "status": "failed", "generated_at": generated_at.isoformat()}) + "\n",
        encoding="utf-8",
    )
    return {"date": day, "status": "failed"}


def verify_git_summary(summary_dir: str | Path, day: str) -> dict[str, Any]:
    """以当日产物而非 Hermes 任务状态判定 Git 来源是否成功。"""

    path = Path(summary_dir) / f"{day}.json"
    if not path.is_file():
        raise ValueError("Git 当日产物不存在")
    summary = json.loads(path.read_text(encoding="utf-8"))
    GitActivitySource._validate(summary, day)
    return {
        "date": day,
        "status": "success",
        "repo_count": int(summary["repo_count"]),
        "commit_count": int(summary["commit_count"]),
    }


class GitActivitySource:
    """把一个业务日的 Git 汇总作为自动日报字段载入。"""

    def __init__(self, summary_dir: str | Path) -> None:
        """绑定只包含 GitHub MCP 派生 JSON 的目录。"""

        self.summary_dir = Path(summary_dir)

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """读取当天快照；缺失与零提交是两个不同且可见的状态。"""

        day = window.start.date().isoformat()
        path = self.summary_dir / f"{day}.json"
        if not path.is_file():
            status_path = self.summary_dir / ".status" / f"{day}.json"
            warning = "Git 来源拉取失败" if self._failed(status_path, day) else "Git 汇总未就绪"
            return SourceResult("git", warnings=[warning])
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
            self._validate(summary, day)
            occurred_at = datetime.fromisoformat(str(summary["generated_at"]))
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=window.start.tzinfo)
            fact = self._format(summary)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
            return SourceResult("git", warnings=["本日 Git 汇总格式无效"])

        evidence = Evidence(
            stable_evidence_id("git", day, str(summary["source_sha256"])),
            "git",
            EvidenceKind.GIT_ACTIVITY,
            occurred_at,
            fact,
            subject="Git",
            source_ref=str(path),
            payload={
                "date": day,
                "user": str(summary.get("user") or ""),
                "repo_count": summary["repo_count"],
                "commit_count": summary["commit_count"],
                "repositories": summary["repositories"],
            },
        )
        return SourceResult("git", [evidence], next_checkpoint=encode_cursor([evidence]))

    @staticmethod
    def _validate(summary: Any, day: str) -> None:
        """严格校验生产者协议，防止半写文件进入冻结材料。"""

        if not isinstance(summary, dict) or summary.get("schema_version") not in {1, 2}:
            raise ValueError("schema")
        if summary.get("date") != day or not isinstance(summary.get("repositories"), list):
            raise ValueError("date/repositories")
        if not isinstance(summary.get("repo_count"), int) or not isinstance(summary.get("commit_count"), int):
            raise ValueError("counts")
        if summary["repo_count"] != len(summary["repositories"]):
            raise ValueError("repo_count")
        if not isinstance(summary.get("source_sha256"), str) or len(summary["source_sha256"]) != 64:
            raise ValueError("hash")
        commit_total = 0
        for repository in summary["repositories"]:
            if not isinstance(repository, dict):
                raise ValueError("repository")
            if not isinstance(repository.get("name"), str) or not repository["name"].strip():
                raise ValueError("repository.name")
            if not isinstance(repository.get("commit_count"), int) or not isinstance(repository.get("subjects"), list):
                raise ValueError("repository.commits")
            if not all(isinstance(subject, str) and subject.strip() for subject in repository["subjects"]):
                raise ValueError("repository.subjects")
            commit_total += repository["commit_count"]
            if summary.get("schema_version") == 2 and not isinstance(repository.get("summary"), str):
                raise ValueError("repository.summary")
        if commit_total != summary["commit_count"]:
            raise ValueError("commit_count")

    @staticmethod
    def _format(summary: dict[str, Any]) -> str:
        """展示仓库级计数和有限重点，完整提交正文不进入日报。"""

        if summary["commit_count"] == 0:
            return "今日无已采集 Git 提交"
        repositories = "、".join(
            f"{repository['name']} {repository['commit_count']}"
            + (f"（{repository.get('summary')}）" if repository.get("summary") else "")
            for repository in summary["repositories"]
        )
        return f"{summary['repo_count']} 个仓库，共 {summary['commit_count']} 次提交：{repositories}"

    @staticmethod
    def _failed(path: Path, day: str) -> bool:
        """判断同日来源状态是否明确失败，坏状态文件按未就绪处理。"""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get("date") == day and payload.get("status") == "failed"
        except (OSError, json.JSONDecodeError, AttributeError):
            return False
