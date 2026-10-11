#!/usr/bin/env python3
"""发现、准备、自动校验并提交合规的 MCP 社区贡献。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


TARGET_LOGIN = "ump45nose"
OFFICIAL_ORGS = ("modelcontextprotocol", "modelcontextprotocol-community")
STATE_VERSION = 1
MAX_CANDIDATES = 3
MAX_REMOTE_INSPECTIONS = 12
MAX_BODY_CHARS = 800
AI_DISCLOSURE = (
    "AI assistance disclosure: AI was used to discover this opportunity and draft "
    "the change or text. The submission was checked against the prepared artifact "
    "and recorded verification evidence."
)
SECURITY_WORDS = ("security", "vulnerability", "cve", "exploit", "安全", "漏洞")
SECURITY_PHRASES = (
    "auth boundary bypass",
    "authentication bypass",
    "authorization bypass",
    "confused deputy",
    "path traversal",
    "privilege escalation",
    "remote code execution",
    "server side request forgery",
)
DISCUSSION_WORDS = (
    "sep",
    "schema",
    "protocol",
    "breaking",
    "feature",
    "enhancement",
    "new api",
    "example",
    "规范",
    "协议",
    "功能",
)
POSITIVE_LABELS = {
    "help wanted": 5,
    "good first issue": 4,
    "ready for work": 5,
    "bug": 3,
    "documentation": 3,
    "tests": 2,
}
BLOCKED_LABELS = {"duplicate", "deferred", "invalid", "wontfix"}
UNCONFIRMED_LABELS = {
    "awaiting feedback",
    "needs confirmation",
    "needs more info",
    "needs-more-info",
    "question",
    "triage",
}
READY_LABELS = {"good first issue", "help wanted", "ready for work"}
MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
MAINTAINER_REQUEST_PHRASES = (
    "contributions welcome",
    "please add",
    "please fix",
    "please implement",
    "please update",
    "pr welcome",
    "ready for work",
    "欢迎提交 pr",
    "请实现",
    "需要修复",
)
AUTHOR_WORK_PHRASES = (
    "already implemented",
    "branch is pushed",
    "implemented this",
    "implementation is complete",
    "opened a pr",
    "pushed a commit",
    "submitted a fix",
    "working implementation",
)


class SkillError(RuntimeError):
    """表示工作流必须停止并向用户报告的可预期错误。"""


def utc_now() -> str:
    """返回带时区的 UTC ISO 时间。"""

    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def default_state_path() -> Path:
    """返回用户级状态路径，并允许测试通过专用变量覆盖。"""

    configured = os.environ.get("MCP_MEMBER_STATE_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".codex" / "state" / "mcp-member-contributor" / "state.json"


def new_state() -> dict[str, Any]:
    """创建最小状态，并记录用户确认的 GitHub 2FA。"""

    return {
        "version": STATE_VERSION,
        "profile": {
            "login": TARGET_LOGIN,
            "two_factor_confirmed": True,
            "two_factor_source": "user-confirmed",
        },
        "allow_repos": [],
        "candidates": {},
        "activities": [],
        "updated_at": utc_now(),
    }


def load_state(path: Path) -> dict[str, Any]:
    """读取并验证状态；损坏时停止且不覆盖原文件。"""

    if not path.exists():
        return new_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"状态文件损坏或不可读，已保留原文件：{path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise SkillError(f"不支持的状态格式，已停止且未修改：{path}")
    if not isinstance(state.get("candidates"), dict) or not isinstance(
        state.get("activities"), list
    ):
        raise SkillError(f"状态字段无效，已停止且未修改：{path}")
    return state


def save_state(path: Path, state: dict[str, Any], dry_run: bool) -> None:
    """原子保存状态；dry-run 时完全不写磁盘。"""

    if dry_run:
        return
    state["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件与目标同目录，确保 os.replace 是原子操作。
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix="state."
    ) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def emit(payload: dict[str, Any]) -> None:
    """输出稳定 JSON，方便小模型与调度器解析。"""

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def run_command(
    args: list[str], *, cwd: Path | None = None, allow_failure: bool = False
) -> subprocess.CompletedProcess[str]:
    """无 shell 执行命令，避免插值执行和意外泄露。"""

    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode and not allow_failure:
        detail = (result.stderr or result.stdout).strip()
        raise SkillError(f"命令失败：{args[0]}（exit {result.returncode}）：{detail}")
    return result


def run_read_command(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """仅对瞬时网络错误重试只读命令，最多三次。"""

    transient = ("eof", "timeout", "timed out", "502", "503", "connection reset", "temporary")
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(3):
        last = run_command(args, cwd=cwd, allow_failure=True)
        if last.returncode == 0:
            return last
        detail = (last.stderr or last.stdout).lower()
        if not any(marker in detail for marker in transient):
            break
        if attempt < 2:
            time.sleep(0.5)
    detail = ((last.stderr or last.stdout) if last else "unknown error").strip()
    raise SkillError(f"只读命令失败：{args[0]}：{detail}")


def require_environment() -> None:
    """检查依赖与当前 GitHub 身份。"""

    missing = [name for name in ("gh", "git") if shutil.which(name) is None]
    if missing:
        raise SkillError(f"缺少依赖：{', '.join(missing)}")
    login = run_read_command(["gh", "api", "user", "--jq", ".login"]).stdout.strip()
    if login != TARGET_LOGIN:
        raise SkillError(f"GitHub 登录必须是 {TARGET_LOGIN}，当前为 {login or 'unknown'}")


def parse_json(result: subprocess.CompletedProcess[str], source: str) -> Any:
    """解析外部 JSON，并标明异常来源。"""

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SkillError(f"{source} 返回无效 JSON：{exc}") from exc


def stable_id(url: str) -> str:
    """根据 URL 生成跨运行稳定的 12 位候选 ID。"""

    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:12]


def compact_text(value: Any) -> str:
    """限制候选正文长度，避免小模型被长 Issue 占满上下文。"""

    text = str(value or "").strip()
    return text if len(text) <= MAX_BODY_CHARS else f"{text[:MAX_BODY_CHARS].rstrip()}…"


def searchable_text(*values: Any) -> str:
    """规范化判定文本，兼容连字符、斜杠和多余空白。"""

    text = " ".join(str(value or "") for value in values).lower()
    return re.sub(r"\s+", " ", re.sub(r"[-_/]+", " ", text)).strip()


def normalize_labels(raw_labels: Any) -> list[str]:
    """兼容 REST 和离线输入，将标签统一为小写字符串。"""

    labels: list[str] = []
    for label in raw_labels or []:
        value = label.get("name") if isinstance(label, dict) else label
        if value:
            labels.append(str(value).strip().lower())
    return labels


def normalize_rest_item(item: dict[str, Any]) -> dict[str, Any]:
    """将 GitHub Search Issue/PR 转为统一候选。"""

    url = str(item.get("html_url") or item.get("url") or "").strip()
    repository_url = str(item.get("repository_url") or "")
    repo = repository_url.split("/repos/", 1)[-1] if "/repos/" in repository_url else ""
    author = str((item.get("user") or {}).get("login") or "")
    is_pr = bool(item.get("pull_request"))
    candidate_type = "review" if is_pr and author != TARGET_LOGIN else "own_pr" if is_pr else "issue"
    return {
        "id": stable_id(url),
        "url": url,
        "repo": repo,
        "number": item.get("number"),
        "type": candidate_type,
        "title": str(item.get("title") or "").strip(),
        "body": compact_text(item.get("body")),
        "author": author,
        "author_association": str(item.get("author_association") or "").upper(),
        "comment_count": int(item.get("comments") or 0),
        "state": str(item.get("state") or "open").lower(),
        "labels": normalize_labels(item.get("labels")),
        "assignees": [
            str(entry.get("login"))
            for entry in item.get("assignees") or []
            if isinstance(entry, dict) and entry.get("login")
        ],
        "updated_at": str(item.get("updated_at") or ""),
        "existing_pr": None,
        "source": "github-search",
    }


def normalize_discussion(item: dict[str, Any]) -> dict[str, Any]:
    """将 GraphQL Discussion 转为统一候选。"""

    url = str(item.get("url") or "").strip()
    return {
        "id": stable_id(url),
        "url": url,
        "repo": str((item.get("repository") or {}).get("nameWithOwner") or ""),
        "number": item.get("number"),
        "node_id": item.get("id"),
        "type": "discussion",
        "title": str(item.get("title") or "").strip(),
        "body": compact_text(item.get("body")),
        "author": str((item.get("author") or {}).get("login") or ""),
        "author_association": str(item.get("authorAssociation") or "").upper(),
        "state": "open",
        "labels": [],
        "assignees": [],
        "updated_at": str(item.get("updatedAt") or ""),
        "existing_pr": None,
        "source": "github-discussions",
    }


def normalize_fixture(item: dict[str, Any]) -> dict[str, Any]:
    """验证并规范化测试或离线候选。"""

    missing = [key for key in ("url", "repo", "title", "type") if not item.get(key)]
    if missing:
        raise SkillError(f"离线候选缺少字段：{', '.join(missing)}")
    value = dict(item)
    value.update(
        {
            "id": stable_id(str(item["url"])),
            "state": str(item.get("state") or "open").lower(),
            "labels": normalize_labels(item.get("labels")),
            "assignees": list(item.get("assignees") or []),
            "body": compact_text(item.get("body")),
            "author_association": str(item.get("author_association") or "").upper(),
            "updated_at": str(item.get("updated_at") or utc_now()),
            "existing_pr": item.get("existing_pr"),
            "source": str(item.get("source") or "offline-input"),
        }
    )
    return value


def load_fixture_candidates(path_value: str) -> list[dict[str, Any]]:
    """从同一离线 JSON 中读取候选，支持连续 dry-run。"""

    try:
        raw = json.loads(Path(path_value).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"无法读取离线候选：{exc}") from exc
    if not isinstance(raw, list):
        raise SkillError("离线候选必须是 JSON 数组")
    return [normalize_fixture(item) for item in raw]


def search_issues(query: str) -> list[dict[str, Any]]:
    """通过 REST Search 获取公开 Issue 和 PR。"""

    # Fine-grained PAT 对 Search API 要求显式指定类型；拆分查询后再合并，
    # 保留原有同时发现 Issue 与 PR 的行为，并避免 HTTP 422。
    items: list[dict[str, Any]] = []
    for type_qualifier in ("is:issue", "is:pull-request"):
        result = run_read_command(
            [
                "gh",
                "api",
                "-X",
                "GET",
                "search/issues",
                "-f",
                f"q={query} {type_qualifier}",
                "-f",
                "per_page=50",
            ]
        )
        items.extend(parse_json(result, f"GitHub search ({type_qualifier})").get("items", []))
    return [normalize_rest_item(item) for item in items]


def search_discussions(query: str) -> list[dict[str, Any]]:
    """通过一次 GraphQL Search 获取近期 Discussion。"""

    graphql = (
        "query($q:String!){search(query:$q,type:DISCUSSION,first:25){nodes{"
        "... on Discussion{id number title url body updatedAt authorAssociation author{login} "
        "repository{nameWithOwner}}}}}"
    )
    result = run_read_command(
        ["gh", "api", "graphql", "-f", f"query={graphql}", "-f", f"q={query}"]
    )
    nodes = (((parse_json(result, "Discussion search").get("data") or {}).get("search") or {}).get("nodes") or [])
    return [normalize_discussion(item) for item in nodes if item]


def has_security_signal(candidate: dict[str, Any]) -> bool:
    """识别应离开公开贡献路径的高置信安全信号。"""

    labels = candidate.get("labels") or []
    text = searchable_text(candidate.get("title"), candidate.get("body"), *labels)
    if "not a security issue" in text and not any(phrase in text for phrase in SECURITY_PHRASES):
        return False
    return any(word in text for word in SECURITY_WORDS) or any(
        phrase in text for phrase in SECURITY_PHRASES
    )


def has_request_text(*values: Any) -> bool:
    """判断文本是否含维护者明确可执行请求。"""

    text = searchable_text(*values)
    return any(phrase in text for phrase in MAINTAINER_REQUEST_PHRASES)


def has_author_work_text(value: Any) -> bool:
    """判断 Issue 作者是否声明已有实现、提交或分支。"""

    text = searchable_text(value)
    return any(phrase in text for phrase in AUTHOR_WORK_PHRASES) or bool(
        re.search(r"\bbranch\s+(?:is|at|:)\s*[\w.-]+[:/]", text)
    )


def has_maintainer_signal(candidate: dict[str, Any]) -> bool:
    """只接受强标签或维护者本人给出的明确请求。"""

    labels = set(candidate.get("labels") or [])
    if labels & READY_LABELS or candidate.get("maintainer_requested"):
        return True
    association = str(candidate.get("author_association") or "").upper()
    return association in MAINTAINER_ASSOCIATIONS and has_request_text(
        candidate.get("title"), candidate.get("body")
    )


def candidate_score(candidate: dict[str, Any]) -> int:
    """用简单规则衡量维护者意图、证据完整度和近期活跃度。"""

    score = sum(POSITIVE_LABELS.get(label, 0) for label in candidate["labels"])
    score += 2 if len(candidate.get("body") or "") >= 120 else 0
    score += 3 if has_maintainer_signal(candidate) else 0
    try:
        updated = dt.datetime.fromisoformat(candidate["updated_at"].replace("Z", "+00:00"))
        score += 2 if dt.datetime.now(dt.timezone.utc) - updated <= dt.timedelta(days=30) else 0
    except (KeyError, TypeError, ValueError):
        pass
    score += 1 if candidate.get("type") in {"review", "own_pr", "discussion"} else 0
    return score


def read_json_list(result: subprocess.CompletedProcess[str], source: str) -> list[dict[str, Any]]:
    """解析 GitHub 列表响应并在结构异常时 fail-closed。"""

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        # 兼容旧版 gh：--paginate --jq '.[]' 按行输出每个对象，空结果为空文本。
        payload = []
        for line_number, line in enumerate(result.stdout.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SkillError(f"{source} 第 {line_number} 行返回无效 JSON：{exc}") from exc
            payload.append(item)
    if isinstance(payload, dict):
        # 恰好一条记录时，旧版 gh 输出单个对象而不是 JSONL 序列。
        payload = [payload]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise SkillError(f"{source} 返回的不是对象数组")
    return payload


def inspect_issue_evidence(candidate: dict[str, Any]) -> None:
    """读取关联 PR 和评论，识别重复工作、作者实现与维护者请求。"""

    if candidate.get("type") != "issue":
        return
    if candidate.get("source") == "offline-input":
        # 离线测试直接使用 fixture 内的证据字段，不访问网络。
        if "related_prs" not in candidate:
            existing_pr = candidate.get("existing_pr")
            candidate["related_prs"] = (
                [{"url": existing_pr, "state": "unknown", "author": ""}]
                if existing_pr
                else []
            )
        return

    repo = candidate["repo"]
    number = str(candidate["number"])
    # 每轮都清空可变证据，避免已删除评论或旧状态继续放行/阻塞。
    for key in ("author_work_url", "maintainer_requested", "maintainer_request_url"):
        candidate.pop(key, None)
    timeline_result = run_read_command(
        [
            "gh",
            "api",
            "--paginate",
            "-X",
            "GET",
            f"repos/{repo}/issues/{number}/timeline",
            "-f",
            "per_page=100",
            "--jq",
            ".[]",
        ]
    )
    timeline = read_json_list(timeline_result, "Issue timeline")
    related_prs: list[dict[str, Any]] = []
    for event in timeline:
        source_issue = ((event.get("source") or {}).get("issue") or {})
        if event.get("event") != "cross-referenced" or not source_issue.get("pull_request"):
            continue
        related_prs.append(
            {
                "url": str(source_issue.get("html_url") or ""),
                "state": str(source_issue.get("state") or "unknown"),
                "author": str((source_issue.get("user") or {}).get("login") or ""),
            }
        )
    candidate["related_prs"] = related_prs
    candidate["existing_pr"] = related_prs[0]["url"] if related_prs else None

    comments_result = run_read_command(
        [
            "gh",
            "api",
            "--paginate",
            "-X",
            "GET",
            f"repos/{repo}/issues/{number}/comments",
            "-f",
            "per_page=100",
            "--jq",
            ".[]",
        ]
    )
    comments = read_json_list(comments_result, "Issue comments")
    for comment in comments:
        author = str((comment.get("user") or {}).get("login") or "")
        association = str(comment.get("author_association") or "").upper()
        body = str(comment.get("body") or "")
        url = str(comment.get("html_url") or candidate.get("url") or "")
        if author == candidate.get("author") and has_author_work_text(body):
            candidate["author_work_url"] = url
        if association in MAINTAINER_ASSOCIATIONS and has_request_text(body):
            candidate["maintainer_requested"] = True
            candidate["maintainer_request_url"] = url


def set_blocked(candidate: dict[str, Any], status: str, reason: str, evidence_url: str = "") -> None:
    """记录稳定阻塞状态，供小模型直接报告而无需自行推断。"""

    candidate["status"] = status
    candidate["blocked_reason"] = reason
    if evidence_url:
        candidate["blocked_evidence_url"] = evidence_url


def static_block(candidate: dict[str, Any]) -> tuple[str, str, str] | None:
    """执行不依赖额外远端请求的硬阻塞检查。"""

    labels = set(candidate.get("labels") or [])
    if candidate.get("state") != "open":
        return "blocked_closed", "远端事项已关闭", candidate.get("url") or ""
    if labels & BLOCKED_LABELS:
        return "blocked_label", "存在 duplicate/deferred/invalid/wontfix 标签", candidate.get("url") or ""
    if candidate.get("source") in {"github-search", "github-discussions"} and has_security_signal(candidate):
        return "blocked_public_security", "公开安全相关事项不得进入自动公开贡献路径", candidate.get("url") or ""
    if labels & UNCONFIRMED_LABELS:
        return "blocked_unconfirmed", "仍在确认或分流阶段，尚未 ready for work", candidate.get("url") or ""
    if candidate.get("type") == "issue" and candidate.get("assignees"):
        return "blocked_assigned", "已有 assignee，避免重复工作", candidate.get("url") or ""
    return None


def evidence_block(candidate: dict[str, Any]) -> tuple[str, str, str] | None:
    """根据关联工作与维护者信号决定候选是否可行动。"""

    related_prs = candidate.get("related_prs") or []
    if related_prs:
        return "blocked_related_pr", "已有开放、关闭或合并的关联 PR", str(related_prs[0].get("url") or "")
    if candidate.get("type") == "issue" and has_author_work_text(candidate.get("body")):
        return "blocked_author_work", "Issue 作者已在正文声明存在实现、提交或分支", candidate.get("url") or ""
    if candidate.get("author_work_url"):
        return "blocked_author_work", "Issue 作者已声明存在实现、提交或分支", str(candidate["author_work_url"])
    if candidate.get("type") in {"issue", "discussion", "review"} and not has_maintainer_signal(candidate):
        return "blocked_no_maintainer_signal", "没有 help wanted/ready for work 或维护者明确请求", candidate.get("url") or ""
    return None


def route_action(candidate: dict[str, Any]) -> str:
    """按风险和对象类型选择唯一发布动作。"""

    body = (candidate.get("body") or "").lower()
    explicit_private_report = any(
        phrase in body
        for phrase in ("responsible disclosure", "private vulnerability report", "security advisory")
    ) and "not a security" not in body
    if has_security_signal(candidate) or explicit_private_report:
        return "private_report"
    if candidate.get("type") in {"review", "own_pr", "discussion"}:
        return "github_reply"
    # 讨论路由只看标题和标签，避免正文中的普通 “example” 误伤小型文档修复。
    routing_text = " ".join(
        [candidate.get("title") or "", *candidate.get("labels", [])]
    ).lower()
    if any(word in routing_text for word in DISCUSSION_WORDS):
        return "discussion"
    return "pull_request"


def merge_candidate(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """刷新远端字段，同时保留本地 workspace、artifact 和状态。"""

    merged = dict(previous or {})
    local = {key: merged[key] for key in ("workspace", "artifact", "status") if key in merged}
    merged.update(current)
    merged.update(local)
    merged["score"] = candidate_score(merged)
    merged["recommended_action"] = route_action(merged)
    merged["last_seen_at"] = utc_now()
    return merged


def discover(args: argparse.Namespace, state: dict[str, Any], state_path: Path) -> None:
    """发现、去重并输出最多三个可行动候选。"""

    warnings: list[str] = []
    if args.input_json:
        found = load_fixture_candidates(args.input_json)
    else:
        found: list[dict[str, Any]] = []
        allow_repos = sorted(set(state.get("allow_repos", [])) | set(args.allow_repo or []))
        for repo in allow_repos:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
                raise SkillError(f"无效 allowlist 仓库：{repo}")
        queries = [f"org:{org} is:open" for org in OFFICIAL_ORGS]
        queries += [f"repo:{repo} is:open" for repo in allow_repos]
        for query in queries:
            found.extend(search_issues(query))
            try:
                found.extend(search_discussions(query))
            except SkillError as exc:
                # Discussion 查询失败必须显式报告，但不丢弃已取得的 Issue/PR。
                warnings.append(f"Discussion 搜索失败：{query}: {exc}")
        state["allow_repos"] = allow_repos

    deduped = {item["id"]: item for item in found if item.get("url")}
    refreshed: list[dict[str, Any]] = []
    for candidate_id, item in deduped.items():
        merged = merge_candidate(state["candidates"].get(candidate_id), item)
        state["candidates"][candidate_id] = merged
        refreshed.append(merged)

    selected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    remote_inspections = 0
    for candidate in sorted(refreshed, key=lambda item: (-item["score"], item["id"])):
        if candidate.get("status") in {"prepared", "submitted", "awaiting_private_submission"}:
            continue
        blocker = static_block(candidate)
        if not blocker and candidate.get("type") == "issue":
            if not args.input_json and remote_inspections >= MAX_REMOTE_INSPECTIONS:
                blocker = (
                    "blocked_unverified",
                    f"本轮远端深检已达到 {MAX_REMOTE_INSPECTIONS} 项上限",
                    candidate.get("url") or "",
                )
            else:
                try:
                    inspect_issue_evidence(candidate)
                    if not args.input_json:
                        remote_inspections += 1
                except SkillError as exc:
                    warnings.append(f"候选资格检查失败：{candidate['url']}: {exc}")
                    blocker = ("blocked_unverified", "无法完成远端资格检查", candidate.get("url") or "")
        blocker = blocker or evidence_block(candidate)
        if blocker:
            set_blocked(candidate, *blocker)
            blocked.append(
                {
                    "id": candidate["id"],
                    "url": candidate.get("url"),
                    "status": candidate["status"],
                    "reason": candidate["blocked_reason"],
                    "evidence_url": candidate.get("blocked_evidence_url"),
                }
            )
            continue
        candidate.pop("blocked_reason", None)
        candidate.pop("blocked_evidence_url", None)
        candidate["status"] = "selected"
        selected.append(candidate)
        if len(selected) >= args.limit:
            break

    save_state(state_path, state, args.dry_run)
    emit(
        {
            "command": "discover",
            "dry_run": args.dry_run,
            "selected": selected,
            "selected_count": len(selected),
            "blocked_count": len(blocked),
            "top_blocked": blocked[:5],
            "warnings": warnings,
        }
    )


def repo_default_branch(repo: str) -> str:
    """读取默认分支，禁止硬编码猜测。"""

    branch = run_read_command(["gh", "api", f"repos/{repo}", "--jq", ".default_branch"]).stdout.strip()
    if not branch:
        raise SkillError(f"无法确定默认分支：{repo}")
    return branch


def ensure_workspace(candidate: dict[str, Any], state_path: Path, dry_run: bool) -> tuple[Path, str, bool]:
    """创建仅含只读 upstream 的隔离工作区和贡献分支。"""

    workspace = Path(candidate.get("workspace") or state_path.parent / "work" / candidate["id"])
    base_branch = str(candidate.get("base_branch") or repo_default_branch(candidate["repo"]))
    created = False
    if not workspace.exists():
        if dry_run:
            return workspace, base_branch, True
        workspace.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                "git",
                "clone",
                "--origin",
                "upstream",
                "--depth",
                "50",
                f"https://github.com/{candidate['repo']}.git",
                str(workspace),
            ]
        )
        run_command(
            ["git", "switch", "-c", f"contrib/{candidate['id']}", f"upstream/{base_branch}"],
            cwd=workspace,
        )
        # 禁用 upstream 推送；通过自动校验后只能配置个人 fork 为 origin。
        run_command(["git", "remote", "set-url", "--push", "upstream", "DISABLED"], cwd=workspace)
        created = True
    if not (workspace / ".git").exists():
        raise SkillError(f"workspace 不是 Git 仓库：{workspace}")
    branch = run_command(["git", "branch", "--show-current"], cwd=workspace).stdout.strip()
    if branch in {base_branch, "main", "master", "develop"}:
        raise SkillError(f"禁止在默认或受保护分支准备贡献：{branch}")
    expected_branch = f"contrib/{candidate['id']}"
    if branch != expected_branch:
        raise SkillError(f"贡献分支必须是 {expected_branch}，当前为 {branch}")
    candidate.update(
        {"workspace": str(workspace), "base_branch": base_branch, "branch": branch}
    )
    return workspace, base_branch, created


def workspace_diff(
    workspace: Path, base_branch: str, *, update_index: bool = True
) -> tuple[str, str, str]:
    """返回相对 upstream 默认分支的 diff、哈希和 HEAD。"""

    if update_index:
        # intent-to-add 让未跟踪文件进入 diff；dry-run 禁止执行此索引更新。
        run_command(["git", "add", "--intent-to-add", "--all"], cwd=workspace)
    diff_text = run_command(
        ["git", "diff", "--binary", f"upstream/{base_branch}", "--"], cwd=workspace
    ).stdout
    diff_hash = hashlib.sha256(diff_text.encode()).hexdigest()
    head_sha = run_command(["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    return diff_text, diff_hash, head_sha


def read_body(path_value: str | None) -> str:
    """读取待发布正文文件。"""

    if not path_value:
        return ""
    path = Path(path_value).expanduser().resolve()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SkillError(f"无法读取正文文件：{path}: {exc}") from exc


def append_disclosure(body: str) -> str:
    """确保公开正文只附加一次固定 AI 披露。"""

    if AI_DISCLOSURE.lower() in body.lower():
        return body
    return f"{body.rstrip()}\n\n> {AI_DISCLOSURE}".strip()


def hash_artifact(artifact: dict[str, Any]) -> str:
    """对不含自身哈希的准备产物计算稳定 SHA-256。"""

    content = {key: value for key, value in artifact.items() if key != "hash"}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def prepare(args: argparse.Namespace, state: dict[str, Any], state_path: Path) -> None:
    """创建 workspace，或把改动/正文封装成可自动提交的产物。"""

    candidate = state["candidates"].get(args.candidate)
    if not candidate and args.input_json:
        candidate = next(
            (item for item in load_fixture_candidates(args.input_json) if item["id"] == args.candidate),
            None,
        )
        if candidate:
            candidate = merge_candidate(None, candidate)
            state["candidates"][candidate["id"]] = candidate
    if not candidate:
        raise SkillError(f"未知候选：{args.candidate}，请先运行 discover")
    # 每次重新计算动作，不信任可被手工修改的缓存字段。
    recommended_action = route_action(candidate)
    candidate["recommended_action"] = recommended_action
    action = args.action or recommended_action
    if recommended_action in {"private_report", "discussion"} and action != recommended_action:
        raise SkillError(f"高风险候选只能使用 {recommended_action}，禁止覆盖为 {action}")
    body = read_body(args.body_file)
    workspace: Path | None = None
    diff_hash = hashlib.sha256(b"").hexdigest()
    head_sha = ""

    if action == "pull_request":
        workspace, base_branch, created = ensure_workspace(candidate, state_path, args.dry_run)
        if args.dry_run and created:
            emit(
                {
                    "command": "prepare",
                    "dry_run": True,
                    "status": "would_create_workspace",
                    "candidate": candidate["id"],
                    "workspace": str(workspace),
                }
            )
            return
        diff_text, diff_hash, head_sha = workspace_diff(
            workspace, base_branch, update_index=not args.dry_run
        )
        if not diff_text.strip():
            candidate["status"] = "workspace_ready"
            save_state(state_path, state, args.dry_run)
            emit(
                {
                    "command": "prepare",
                    "dry_run": args.dry_run,
                    "status": "ready_to_edit",
                    "candidate": candidate["id"],
                    "workspace": str(workspace),
                    "branch": candidate["branch"],
                }
            )
            return
        if not args.summary or not args.tests:
            raise SkillError("检测到代码改动；必须提供 --summary 和 --tests")
        if not body:
            body = (
                f"## Summary\n\n{args.summary}\n\n"
                f"## Verification\n\n{args.tests}\n\nRelated to {candidate['url']}"
            )
    else:
        if not body:
            raise SkillError(f"{action} 必须通过 --body-file 提供待发布正文")
        args.summary = args.summary or candidate.get("title") or action

    artifact = {
        "candidate_id": candidate["id"],
        "action": action,
        "repo": candidate.get("repo"),
        "number": candidate.get("number"),
        "title": args.summary,
        "body": append_disclosure(body),
        "tests": args.tests or "not-applicable",
        "workspace": str(workspace) if workspace else None,
        "branch": candidate.get("branch"),
        "base_branch": candidate.get("base_branch"),
        "head_sha": head_sha,
        "diff_sha256": diff_hash,
        "created_at": utc_now(),
    }
    artifact["hash"] = hash_artifact(artifact)
    candidate.update({"artifact": artifact, "status": "prepared"})
    save_state(state_path, state, args.dry_run)
    emit(
        {
            "command": "prepare",
            "dry_run": args.dry_run,
            "status": "ready_to_submit",
            "candidate": candidate,
            "artifact": artifact,
            "next": f"submit --candidate {candidate['id']}",
        }
    )


def revalidate(candidate: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """重新验证准备产物、workspace diff 和远端开放状态。"""

    artifact = candidate.get("artifact")
    expected_hash = artifact.get("hash") if isinstance(artifact, dict) else None
    if not expected_hash or hash_artifact(artifact) != expected_hash:
        raise SkillError("准备产物或哈希已变化，停止提交")
    if artifact.get("candidate_id") != candidate.get("id") or artifact.get("repo") != candidate.get("repo"):
        raise SkillError("候选身份或目标仓库已变化，停止提交")
    if artifact.get("number") != candidate.get("number"):
        raise SkillError("候选编号已变化，停止提交")
    if artifact.get("workspace"):
        _, diff_hash, head_sha = workspace_diff(
            Path(artifact["workspace"]), artifact["base_branch"], update_index=not dry_run
        )
        if diff_hash != artifact["diff_sha256"] or head_sha != artifact["head_sha"]:
            raise SkillError("workspace diff 或 HEAD 已变化，请重新 prepare")
    if candidate.get("type") != "discussion":
        result = run_read_command(
            ["gh", "api", f"repos/{candidate['repo']}/issues/{candidate['number']}"]
        )
        current_payload = parse_json(result, "Remote issue")
        if not isinstance(current_payload, dict):
            raise SkillError("远端 Issue/PR 返回结构无效，停止提交")
        current = normalize_rest_item(current_payload)
        # 仅刷新远端资格字段，保留本地 artifact、workspace 与贡献分支。
        for key in (
            "author",
            "author_association",
            "body",
            "comment_count",
            "labels",
            "assignees",
            "state",
            "title",
        ):
            candidate[key] = current[key]
        blocker = static_block(candidate)
        if not blocker and candidate.get("type") == "issue":
            inspect_issue_evidence(candidate)
            blocker = evidence_block(candidate)
        if blocker:
            _, reason, evidence_url = blocker
            suffix = f"：{evidence_url}" if evidence_url else ""
            raise SkillError(f"候选已不满足提交资格：{reason}{suffix}")
    return artifact


def ensure_fork(repo: str, workspace: Path) -> str:
    """确保个人 fork 存在，并将 origin 指向个人仓库。"""

    repo_name = repo.split("/", 1)[1]
    fork = f"{TARGET_LOGIN}/{repo_name}"
    check = run_command(["gh", "api", f"repos/{fork}"], allow_failure=True)
    if check.returncode:
        detail = (check.stderr or check.stdout).lower()
        if "404" not in detail and "not found" not in detail:
            raise SkillError(f"无法确认个人 fork 状态：{detail.strip()}")
        run_command(["gh", "repo", "fork", repo, "--clone=false"])
    url = f"https://github.com/{fork}.git"
    remotes = run_command(["git", "remote"], cwd=workspace).stdout.split()
    command = ["git", "remote", "set-url" if "origin" in remotes else "add", "origin", url]
    run_command(command, cwd=workspace)
    return fork


def publish_pr(candidate: dict[str, Any], artifact: dict[str, Any]) -> str:
    """推送已校验分支到个人 fork，并创建 ready PR。"""

    # 推送前再读一次 timeline，缩小 revalidate 与公开写入间的竞态窗口。
    inspect_issue_evidence(candidate)
    related_prs = candidate.get("related_prs") or []
    if related_prs:
        raise SkillError(f"已存在关联 PR：{related_prs[0].get('url')}")
    workspace = Path(artifact["workspace"])
    ensure_fork(candidate["repo"], workspace)
    run_command(["git", "push", "origin", f"HEAD:{artifact['branch']}"], cwd=workspace)
    result = run_command(
        [
            "gh",
            "pr",
            "create",
            "-R",
            candidate["repo"],
            "--base",
            artifact["base_branch"],
            "--head",
            f"{TARGET_LOGIN}:{artifact['branch']}",
            "--title",
            artifact["title"],
            "--body",
            artifact["body"],
        ]
    )
    return result.stdout.strip()


def publish_discussion(candidate: dict[str, Any], artifact: dict[str, Any]) -> str:
    """为需共识的改动创建 Issue；仓库可再将其转入 Discussion。"""

    result = run_command(
        [
            "gh",
            "issue",
            "create",
            "-R",
            candidate["repo"],
            "--title",
            artifact["title"],
            "--body",
            artifact["body"],
        ]
    )
    return result.stdout.strip()


def publish_reply(candidate: dict[str, Any], artifact: dict[str, Any]) -> str:
    """发布单条 Issue、PR Review 或 Discussion 回复。"""

    if candidate.get("type") == "review":
        run_command(
            [
                "gh",
                "pr",
                "review",
                str(candidate["number"]),
                "-R",
                candidate["repo"],
                "--comment",
                "--body",
                artifact["body"],
            ]
        )
        return candidate["url"]
    if candidate.get("type") == "own_pr":
        result = run_command(
            [
                "gh",
                "pr",
                "comment",
                str(candidate["number"]),
                "-R",
                candidate["repo"],
                "--body",
                artifact["body"],
            ]
        )
        return result.stdout.strip() or candidate["url"]
    if candidate.get("type") == "discussion" and candidate.get("node_id"):
        mutation = (
            "mutation($id:ID!,$body:String!){addDiscussionComment(input:{discussionId:$id,body:$body})"
            "{comment{url}}}"
        )
        result = run_command(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={mutation}",
                "-f",
                f"id={candidate['node_id']}",
                "-f",
                f"body={artifact['body']}",
            ]
        )
        payload = parse_json(result, "Discussion reply")
        return payload["data"]["addDiscussionComment"]["comment"]["url"]
    result = run_command(
        [
            "gh",
            "issue",
            "comment",
            str(candidate["number"]),
            "-R",
            candidate["repo"],
            "--body",
            artifact["body"],
        ]
    )
    return result.stdout.strip() or candidate["url"]


def submit(args: argparse.Namespace, state: dict[str, Any], state_path: Path) -> None:
    """自动验证准备产物，并执行一个公开动作或输出外部交接。"""

    candidate_id = args.candidate
    candidate = state["candidates"].get(candidate_id)
    if not candidate:
        raise SkillError(f"未知候选：{candidate_id}")
    artifact = candidate.get("artifact")
    expected_hash = artifact.get("hash") if isinstance(artifact, dict) else None
    if not expected_hash:
        raise SkillError("候选尚未完成 prepare，停止提交")
    completed = next(
        (
            item
            for item in state["activities"]
            if item.get("candidate_id") == candidate_id
            and item.get("artifact_hash") == expected_hash
        ),
        None,
    )
    if completed:
        emit(
            {
                "command": "submit",
                "status": "already_submitted",
                "candidate": candidate_id,
                "action": completed.get("action"),
                "url": completed.get("url"),
            }
        )
        return
    artifact = revalidate(candidate, dry_run=args.dry_run)
    action = artifact["action"]
    if args.dry_run:
        emit(
            {
                "command": "submit",
                "dry_run": True,
                "status": "would_submit",
                "candidate": candidate_id,
                "action": action,
                "body": artifact["body"],
            }
        )
        return

    if action == "pull_request":
        url, status = publish_pr(candidate, artifact), "submitted"
    elif action == "discussion":
        url, status = publish_discussion(candidate, artifact), "submitted"
    elif action == "github_reply":
        url, status = publish_reply(candidate, artifact), "submitted"
    elif action in {"private_report", "discord_reply"}:
        url = args.external_url
        status = "submitted" if url else "external_handoff_ready"
    else:
        raise SkillError(f"不支持的动作：{action}")

    if status == "external_handoff_ready":
        emit(
            {
                "command": "submit",
                "status": status,
                "candidate": candidate_id,
                "action": action,
                "handoff_body": artifact["body"],
                "next": "由调用 agent 发送，再追加 --external-url 记账",
            }
        )
        return

    candidate["status"] = status
    state["activities"].append(
        {
            "candidate_id": candidate_id,
            "action": action,
            "url": url,
            "artifact_hash": expected_hash,
            "created_at": utc_now(),
        }
    )
    save_state(state_path, state, False)
    emit(
        {
            "command": "submit",
            "dry_run": False,
            "status": status,
            "candidate": candidate_id,
            "action": action,
            "url": url,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    """构建仅含 discover、prepare、submit 的 CLI。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=default_state_path())
    parser.add_argument("--dry-run", action="store_true", help="只读演练")
    commands = parser.add_subparsers(dest="command", required=True)

    discover_parser = commands.add_parser("discover")
    discover_parser.add_argument("--allow-repo", action="append", default=[])
    discover_parser.add_argument("--limit", type=int, choices=(1, 2, 3), default=MAX_CANDIDATES)
    discover_parser.add_argument("--input-json")

    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--candidate", required=True)
    prepare_parser.add_argument("--summary")
    prepare_parser.add_argument("--tests")
    prepare_parser.add_argument("--body-file")
    prepare_parser.add_argument("--input-json", help="连续 dry-run 使用的离线候选 JSON")
    prepare_parser.add_argument(
        "--action",
        choices=("pull_request", "discussion", "private_report", "github_reply", "discord_reply"),
    )

    submit_parser = commands.add_parser("submit")
    submit_parser.add_argument("--candidate", required=True)
    submit_parser.add_argument("--external-url")
    return parser


def main() -> int:
    """执行环境、状态和命令检查，并返回机器可读结果。"""

    args = build_parser().parse_args()
    try:
        require_environment()
        state_path = args.state.expanduser().resolve()
        state = load_state(state_path)
        if state.get("profile", {}).get("login") != TARGET_LOGIN:
            raise SkillError("状态文件目标账号不是 ump45nose")
        if args.command == "discover":
            discover(args, state, state_path)
        elif args.command == "prepare":
            prepare(args, state, state_path)
        else:
            submit(args, state, state_path)
        return 0
    except SkillError as exc:
        emit({"status": "error", "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
