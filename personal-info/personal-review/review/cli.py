"""reviewctl 命令入口。"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import sys
from typing import Iterable

from review.attachments import AttachmentQueue
from review.annual import AnnualReviewService
from review.config import AppConfig, ConfigError, load_config
from review.daily import DailyReviewService
from review.domain import Evidence, TimeWindow
from review.evidence import EvidencePipeline
from review.jobs import CronPlanner
from review.ledger import MemosClient, MemosError
from review.observability import StructuredLogger
from review.projections import CurrentStateProjection, ProjectionOutbox, StageWritebackProjection, UserMdProjection
from review.sources.email import EmailBriefSource
from review.sources.google import GoogleCalendarBriefSource, GoogleTasksBriefSource
from review.sources.health import HealthSource
from review.sources.finance import FinanceSource
from review.sources.git_activity import (
    GitActivitySource,
    store_git_failure,
    store_git_mcp_summary,
    verify_git_summary,
)
from review.sources.crm_activity import CrmActivitySource
from review.sources.memos import MemosSource
from review.sources.skysight import SkysightSummarySource
from review.stages import StageService
from review.state import StateRepository
from review.weekly import WeeklyReviewService


def _parser() -> argparse.ArgumentParser:
    """构建稳定 CLI，所有副作用命令都支持显式 dry-run。"""

    parser = argparse.ArgumentParser(prog="reviewctl")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--policy-file", default="config/review.yaml")
    commands = parser.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config")
    config.add_argument("action", choices=["validate"])
    commands.add_parser("doctor")
    serve = commands.add_parser('serve')
    serve.add_argument('--host', default='192.168.31.201')
    serve.add_argument('--port', type=int, default=18191)
    serve.add_argument('--token-hash-file', required=True)
    status = commands.add_parser('review')
    status.add_argument('action', choices=['status'])
    status.add_argument('--id', required=True)

    cron = commands.add_parser("cron")
    cron.add_argument("action", choices=["diff", "apply"])
    cron.add_argument("--dry-run", action="store_true")

    git_input = commands.add_parser("git")
    git_input.add_argument("action", choices=["import", "verify", "fail"])
    git_input.add_argument("--date", required=True, help="GitHub MCP 查询对应的业务日期")
    git_input.add_argument("--content-file", help="MCP 聚合后的最小 JSON")

    crm = commands.add_parser("crm")
    crm.add_argument("action", choices=["read"])
    crm.add_argument("--date", required=True, help="日报材料的业务日期，只读本机 CRM API")

    daily = commands.add_parser("daily")
    daily.add_argument("action", choices=["prepare", "refresh", "acknowledge", "finalize"])
    daily.add_argument("--date", help="YYYY-MM-DD，默认业务时区今天")
    daily.add_argument("--session-id")
    daily.add_argument("--content-file")
    daily.add_argument("--delivery-id", help="成功投递后返回的稳定消息或运行标识")
    daily.add_argument("--dry-run", action="store_true")

    weekly = commands.add_parser("weekly")
    weekly.add_argument("action", choices=["prepare", "finalize"])
    weekly.add_argument("--date", help="周报窗口结束日期")
    weekly.add_argument("--session-id")
    weekly.add_argument("--content-file")
    weekly.add_argument("--dry-run", action="store_true")

    annual = commands.add_parser("annual")
    annual.add_argument("action", choices=["prepare", "finalize"])
    annual.add_argument("--year", type=int)
    annual.add_argument("--session-id")
    annual.add_argument("--content-file")
    annual.add_argument("--dry-run", action="store_true")

    stage = commands.add_parser("stage")
    stage.add_argument(
        "action",
        choices=["publish-mainline", "create-cycle", "add-goal", "publish-goal", "comment-goal", "prepare-close", "enforce", "reconcile", "close"],
    )
    stage.add_argument("--goal-id")
    stage.add_argument("--cycle-id")
    stage.add_argument("--domain")
    stage.add_argument("--payload-file")
    stage.add_argument("--content-file")
    stage.add_argument("--outcomes-file")
    stage.add_argument("--dry-run", action="store_true")

    projections = commands.add_parser("projections")
    projections.add_argument(
        "action",
        choices=["pending", "complete", "retry", "user-md", "sync-user-md", "apply-stage-writeback", "observe-task"],
    )
    projections.add_argument("--destination")
    projections.add_argument("--id", type=int)
    projections.add_argument("--success", action="store_true")
    projections.add_argument("--error")
    projections.add_argument("--external-id")
    projections.add_argument("--receipt-file")
    projections.add_argument("--content-file")
    projections.add_argument("--mapping-key")
    projections.add_argument("--title")
    projections.add_argument("--status")
    projections.add_argument("--occurred-at")
    projections.add_argument("--dry-run", action="store_true")

    attachment = commands.add_parser("attachment")
    attachment.add_argument("action", choices=["enqueue", "link", "pending", "upload", "process", "retry", "expire"])
    attachment.add_argument("--id", type=int)
    attachment.add_argument("--message-id")
    attachment.add_argument("--source")
    attachment.add_argument("--memo-name")
    attachment.add_argument("--status")
    return parser

def _runtime(config: AppConfig) -> tuple[StateRepository, MemosClient | None]:
    """初始化状态库；Memos 未配置好时允许只读 dry-run 路径继续。"""

    state = StateRepository(config.path("REVIEW_STATE_DB"))
    state.initialize()
    try:
        memos_policy = config.policy["memos"]
        memos = MemosClient(
            config.values["REVIEW_MEMOS_BASE_URL"],
            config.path("REVIEW_MEMOS_TOKEN_FILE"),
            timeout=int(memos_policy["request_timeout_seconds"]),
            read_retries=int(memos_policy["read_retries"]),
            retry_backoff_seconds=float(memos_policy["retry_backoff_seconds"]),
        )
    except (OSError, MemosError):
        memos = None
    return state, memos


def _day_window(config: AppConfig, value: str | None) -> TimeWindow:
    """构造业务日 `[00:00, 21:30)` 冻结窗口。"""

    now = datetime.now(config.timezone)
    day = datetime.strptime(value, "%Y-%m-%d").date() if value else now.date()
    hour, minute = map(int, config.policy["daily"]["cutoff"].split(":"))
    start = datetime.combine(day, time.min, config.timezone)
    end = datetime.combine(day, time(hour, minute), config.timezone)
    return TimeWindow(start, end)


def _week_window(config: AppConfig, value: str | None) -> TimeWindow:
    """构造周一零点至指定周日晚执行时刻的窗口。"""

    end_day = datetime.strptime(value, "%Y-%m-%d").date() if value else datetime.now(config.timezone).date()
    end = datetime.combine(end_day, time(21, 50), config.timezone)
    start_day = end_day - timedelta(days=end_day.weekday())
    start = datetime.combine(start_day, time.min, config.timezone)
    return TimeWindow(start, end)


def _collect(
    config: AppConfig,
    state: StateRepository,
    memos: MemosClient | None,
    window: TimeWindow,
    scope: str,
    weekly: bool = False,
    use_checkpoints: bool = True,
) -> tuple[list[Evidence], list[str], dict[str, str], set[str]]:
    """按配置调用来源；refresh 可显式忽略已提交游标重读完整窗口。"""

    metrics = config.policy["health"]["weekly_metrics" if weekly else "daily_metrics"]
    source_flags = config.policy["sources"]
    adapters: list[tuple[str, object, TimeWindow]] = []
    if source_flags["memos"] and memos is not None:
        adapters.append(("memos", MemosSource(memos, config.policy["memos"]["tags"]), window))
    if source_flags["skysight"]:
        source_window = window
        if scope == "daily":
            hour, minute = map(int, config.policy["daily"]["skysight_cutoff"].split(":"))
            cutoff = datetime.combine(window.start.date(), time(hour, minute), window.start.tzinfo)
            source_window = TimeWindow(window.start, min(window.end, cutoff))
        adapters.append(("skysight", SkysightSummarySource(config.path("REVIEW_SKYSIGHT_ARCHIVE_ROOT"), config.values.get("REVIEW_SKYSIGHT_READER")), source_window))
    if source_flags["email"]:
        adapters.append(("email", EmailBriefSource(config.path("REVIEW_EMAIL_BRIEF_DIR"), config.policy), window))
    if source_flags["health"]:
        adapters.append(("health", HealthSource(metrics), window))
    if source_flags["finance"] and not weekly:
        adapters.append(("finance", FinanceSource(), window))
    if source_flags["git"] and not weekly:
        adapters.append(("git", GitActivitySource(config.path("REVIEW_GIT_SUMMARY_DIR")), window))
    if source_flags["crm"] and not weekly:
        adapters.append(("crm", CrmActivitySource(config.values["REVIEW_CRM_API_URL"], config.path("REVIEW_CRM_TOKEN_FILE")), window))
    if source_flags["google_tasks"]:
        adapters.append(
            (
                "google_tasks",
                GoogleTasksBriefSource(config.path("REVIEW_GOOGLE_BRIEF_DIR"), config.policy),
                window,
            )
        )
    if source_flags["google_calendar"]:
        adapters.append(("google_calendar", GoogleCalendarBriefSource(config.path("REVIEW_GOOGLE_BRIEF_DIR")), window))
    evidence: list[Evidence] = []
    warnings: list[str] = []
    checkpoints: dict[str, str] = {}
    completed_sources: set[str] = set()
    if source_flags["memos"] and memos is None:
        warnings.append("Memos 来源跳过：客户端不可用")
    if source_flags["mem0"]:
        warnings.append("Mem0 是确认内容镜像，不作为日报事实来源")
    for source_name, adapter, source_window in adapters:
        checkpoint_key = f"{scope}:{source_name}"
        try:
            checkpoint = state.checkpoint(checkpoint_key) if use_checkpoints else None
            result = adapter.collect(source_window, checkpoint)
            # 只有成功返回的全窗口来源才有资格在 refresh 时替换旧快照；异常来源保留旧材料。
            completed_sources.add(source_name)
            evidence.extend(result.evidence)
            warnings.extend(result.warnings)
            if result.next_checkpoint:
                checkpoints[checkpoint_key] = result.next_checkpoint
        except Exception as exc:  # 单源失败不能阻断复盘；只暴露类型和短原因。
            warnings.append(f"{source_name} 跳过：{type(exc).__name__}: {str(exc)[:160]}")
    return EvidencePipeline(config.policy).process(evidence), warnings, checkpoints, completed_sources


def _read_required(path: str | None, label: str) -> str:
    """读取用户显式提供的文本文件，禁止猜测会话内容。"""

    if not path:
        raise ValueError(f"{label} 需要 --content-file 或对应 JSON 文件")
    return Path(path).read_text(encoding="utf-8")


def _json_print(value: object) -> None:
    """统一输出可供 Hermes 解析的 UTF-8 JSON。"""

    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def run(argv: Iterable[str] | None = None) -> int:
    """执行 reviewctl 并返回适合 cron 的退出码。"""

    args = _parser().parse_args(list(argv) if argv is not None else None)
    logger: StructuredLogger | None = None
    try:
        config = load_config(args.env_file, args.policy_file)
        logger = StructuredLogger(config.path("REVIEW_LOG_DIR"))
        logger.emit("reviewctl.command", "started", command=args.command, action=getattr(args, "action", None))
        if args.command == "config":
            _json_print({"status": "ok", "schema_version": config.policy["schema_version"], "flags": config.flags.__dict__})
            return 0
        if args.command == "crm":
            source = CrmActivitySource(config.values["REVIEW_CRM_API_URL"], config.path("REVIEW_CRM_TOKEN_FILE"))
            _json_print(source.read_conversations(_day_window(config, args.date)))
            return 0
        state, memos = _runtime(config)
        if args.command == 'serve':
            from review.http import serve
            serve(config, state, memos, args.host, args.port, args.token_hash_file)
            return 0
        if args.command == 'review':
            from review.http import ReviewAPI
            _json_print(ReviewAPI(config,state,memos).review_status(args.id))
            return 0
        if args.command == "doctor":
            _json_print(_doctor(config, state, memos))
            return 0
        if args.command == "cron":
            planner = CronPlanner(config)
            if args.action == "diff":
                _json_print(planner.diff())
            else:
                _json_print(planner.apply(args.dry_run))
            return 0
        if args.command == "git":
            # Git 成功以通过校验的当日产物为准，不能用 Agent 最终回复代替。
            day = datetime.strptime(args.date, "%Y-%m-%d").date().isoformat()
            if args.action == "import":
                payload = json.loads(_read_required(args.content_file, "Git MCP 汇总"))
                result = store_git_mcp_summary(
                    config.path("REVIEW_GIT_SUMMARY_DIR"),
                    day,
                    payload,
                    datetime.now(config.timezone),
                )
                _json_print({"status": "imported", **result})
            elif args.action == "verify":
                _json_print(verify_git_summary(config.path("REVIEW_GIT_SUMMARY_DIR"), day))
            else:
                _json_print(store_git_failure(config.path("REVIEW_GIT_SUMMARY_DIR"), day, datetime.now(config.timezone)))
            return 0
        if args.command == "daily":
            service = DailyReviewService(
                state, config.policy, memos, config.flags.tasks,
                user_memory_path=config.path("REVIEW_USER_MD"),
            )
            if args.action == "prepare":
                window = _day_window(config, args.date)
                session_id = f"daily:{window.start.date().isoformat()}"
                if state.load_session(session_id) is not None:
                    _json_print({
                        "session_id": session_id,
                        "mode": "replay",
                        "material": service.material_snapshot(session_id),
                        "text": service.replay(session_id),
                    })
                    return 0
                evidence, warnings, checkpoints, _ = _collect(
                    config,
                    state,
                    memos,
                    window,
                    "daily",
                    use_checkpoints=not args.dry_run,
                )
                if args.dry_run:
                    # 上线前允许读取完整来源并渲染，但不冻结会话或暂存 checkpoint。
                    bundle = service.build_material(window, evidence, warnings)
                    _json_print({
                        "session_id": session_id,
                        "mode": "dry-run",
                        "material": bundle.to_dict(),
                        "text": bundle.to_markdown(),
                    })
                    return 0
                session_id, text = service.prepare(window, evidence, warnings)
                state.record_evidence(session_id, evidence)
                pending = state.stage_checkpoints(session_id, checkpoints)
                _json_print({
                    "session_id": session_id,
                    "mode": "prepared",
                    "pending_checkpoints": pending,
                    "material": service.material_snapshot(session_id),
                    "text": text,
                })
            elif args.action == "refresh":
                window = _day_window(config, args.date)
                evidence, warnings, checkpoints, completed_sources = _collect(
                    config,
                    state,
                    memos,
                    window,
                    "daily",
                    use_checkpoints=False,
                )
                session_id, text, merged = service.refresh(
                    window,
                    evidence,
                    warnings,
                    replace_sources=completed_sources,
                )
                state.record_evidence(session_id, merged)
                pending = state.stage_checkpoints(session_id, checkpoints)
                _json_print({
                    "session_id": session_id,
                    "mode": "refreshed",
                    "pending_checkpoints": pending,
                    "material": service.material_snapshot(session_id),
                    "text": text,
                })
            elif args.action == "acknowledge":
                if not args.session_id:
                    raise ValueError("daily acknowledge 需要 --session-id")
                _json_print(state.acknowledge_checkpoints(args.session_id, args.delivery_id))
            else:
                content = _read_required(args.content_file, "日报终稿")
                _json_print(service.finalize(args.session_id, content, args.dry_run))
            return 0
        if args.command == "weekly":
            service = WeeklyReviewService(state, config.policy, memos, config.flags.tasks)
            if args.action == "prepare":
                window = _week_window(config, args.date)
                evidence, warnings, checkpoints, _ = _collect(config, state, memos, window, "weekly", weekly=True)
                session_id, text = service.prepare(window, evidence, warnings)
                state.record_evidence(session_id, evidence)
                state.commit_checkpoints(checkpoints)
                _json_print({"session_id": session_id, "text": text})
            else:
                content = _read_required(args.content_file, "周报终稿")
                _json_print(service.finalize(args.session_id, content, args.dry_run))
            return 0
        if args.command == "annual":
            service = AnnualReviewService(state, config.policy, memos)
            if args.action == "prepare":
                year = args.year or datetime.now(config.timezone).year
                session_id, text = service.prepare(year, datetime.now(config.timezone))
                _json_print({"session_id": session_id, "text": text})
            else:
                content = _read_required(args.content_file, "年度总结")
                _json_print(service.finalize(args.session_id, content, args.dry_run))
            return 0
        if args.command == "stage":
            service = StageService(state, config.policy, memos, config.flags.tasks)
            if args.action == "publish-mainline":
                payload = json.loads(_read_required(args.payload_file, "主线 JSON"))
                _json_print(service.publish_mainline(args.domain, payload, args.dry_run))
            elif args.action == "create-cycle":
                _json_print({"cycle_id": service.create_cycle(datetime.now(config.timezone))})
            elif args.action == "add-goal":
                payload = json.loads(_read_required(args.payload_file, "阶段目标 JSON"))
                _json_print({"goal_id": service.add_goal(args.cycle_id, args.domain, payload)})
            elif args.action == "publish-goal":
                _json_print(service.publish_goal(args.goal_id, args.dry_run))
            elif args.action == "comment-goal":
                content = _read_required(args.content_file, "阶段评论")
                _json_print(service.comment_goal(args.goal_id, content, args.dry_run))
            elif args.action == "prepare-close":
                _json_print({"materials": service.prepare_close(datetime.now(config.timezone))})
            elif args.action == "enforce":
                _json_print({"frozen": service.enforce_deadlines(datetime.now(config.timezone))})
            elif args.action == "reconcile":
                _json_print(service.reconcile(args.dry_run))
            else:
                outcomes = json.loads(_read_required(args.outcomes_file, "阶段结果 JSON"))
                content = _read_required(args.content_file, "阶段总结")
                _json_print(service.close_cycle(args.cycle_id, content, outcomes, args.dry_run))
            return 0
        if args.command == "projections":
            outbox = ProjectionOutbox(state, config.policy)
            if args.action == "pending":
                enabled = {
                    "user_md": config.flags.user_md,
                    "stage_writeback": config.flags.stages,
                    "mem0": config.flags.mem0,
                    "google_tasks": config.flags.tasks,
                }
                if args.destination:
                    if args.destination not in enabled:
                        raise ValueError("未知投影 destination")
                    _json_print(outbox.pending(args.destination) if enabled[args.destination] else [])
                else:
                    operations = [
                        item
                        for destination, active in enabled.items()
                        if active
                        for item in outbox.pending(destination)
                    ]
                    _json_print(sorted(operations, key=lambda item: item["id"]))
            elif args.action == "complete":
                receipt = json.loads(_read_required(args.receipt_file, "投影回执 JSON")) if args.receipt_file else {}
                _json_print(outbox.complete(args.id, args.success, args.error, args.external_id, receipt))
            elif args.action == "retry":
                _json_print(outbox.retry(args.id))
            elif args.action == "user-md":
                if not config.flags.user_md and not args.dry_run:
                    raise ValueError("REVIEW_ENABLE_USER_MD=false，拒绝更新 USER.md")
                content = _read_required(args.content_file, "USER.md 当前状态")
                updated = UserMdProjection(config.path("REVIEW_USER_MD")).apply(content, args.dry_run)
                _json_print({"status": "dry-run" if args.dry_run else "updated", "bytes": len(updated.encode())})
            elif args.action == "sync-user-md":
                if not config.flags.user_md and not args.dry_run:
                    raise ValueError("REVIEW_ENABLE_USER_MD=false，拒绝同步 USER.md")
                targets = [config.path("REVIEW_USER_MD"), config.path("REVIEW_COMPANION_USER_MD")]
                projections = [CurrentStateProjection(state, path) for path in dict.fromkeys(targets)]
                # 先对所有 Agent 的受管区块做哈希预检，任一冲突都不开始本轮写入。
                previews = [projection.apply(True) for projection in projections]
                if args.dry_run:
                    result = {"status": "dry-run", "targets": [str(path) for path in dict.fromkeys(targets)], "preview": previews[0]["content"]}
                else:
                    applied = [projection.apply(False) for projection in projections]
                    result = {"status": "updated", "targets": [str(path) for path in dict.fromkeys(targets)], "bytes": [item["bytes"] for item in applied]}
                if not args.dry_run:
                    for operation in outbox.pending("user_md", limit=200):
                        outbox.complete(operation["id"], True, external_id=";".join(str(path) for path in dict.fromkeys(targets)))
                _json_print(result)
            elif args.action == "apply-stage-writeback":
                if not config.flags.stages and not args.dry_run:
                    raise ValueError("REVIEW_ENABLE_STAGES=false，拒绝写回阶段进度")
                operation = outbox.get(args.id)
                if operation["destination"] != "stage_writeback":
                    raise ValueError("投影操作不是 stage_writeback")
                service = StageService(state, config.policy, memos, config.flags.tasks)
                worker = StageWritebackProjection(state, service)
                try:
                    updates = worker.apply(str(operation["payload"].get("content", "")), args.dry_run)
                    if not args.dry_run:
                        outbox.complete(args.id, True, external_id=f"stage-writeback:{args.id}")
                    _json_print({"status": "dry-run" if args.dry_run else "completed", "updates": updates})
                except Exception as exc:
                    if not args.dry_run:
                        outbox.complete(args.id, False, error=f"{type(exc).__name__}: {str(exc)[:240]}")
                    raise
            else:
                if not config.flags.tasks:
                    raise ValueError("REVIEW_ENABLE_TASKS=false，拒绝记录 Tasks 状态")
                if not all([args.mapping_key, args.external_id, args.title, args.status, args.occurred_at]):
                    raise ValueError("observe-task 需要 mapping-key、external-id、title、status、occurred-at")
                occurred = datetime.fromisoformat(args.occurred_at.replace("Z", "+00:00"))
                _json_print(outbox.observe_task(args.mapping_key, args.external_id, args.title, args.status, occurred))
            return 0
        if args.command == "attachment":
            queue = AttachmentQueue(
                state,
                config.path("REVIEW_ATTACHMENT_SPOOL"),
                int(config.policy["retention"]["attachment_pending_days"]),
                int(config.policy["attachments"]["retry_max"]),
                int(config.policy["attachments"]["worker_batch"]),
                int(config.policy["attachments"]["max_bytes"]),
                tuple(config.policy["attachments"]["allowed_mime_types"]),
            )
            if args.action == "enqueue":
                if not config.flags.attachments:
                    raise ValueError("REVIEW_ENABLE_ATTACHMENTS=false，拒绝接收附件")
                if not args.message_id or not args.source:
                    raise ValueError("attachment enqueue 需要 --message-id 和 --source")
                _json_print(queue.enqueue(args.message_id, args.source))
            elif args.action == "link":
                if not args.message_id or not args.memo_name:
                    raise ValueError("attachment link 需要 --message-id 和 --memo-name")
                _json_print({"linked": queue.link(args.message_id, args.memo_name)})
            elif args.action == "pending":
                _json_print(queue.pending(args.status))
            elif args.action == "upload":
                if not config.flags.attachments:
                    raise ValueError("REVIEW_ENABLE_ATTACHMENTS=false，拒绝上传附件")
                if memos is None:
                    raise ValueError("Memos 客户端不可用")
                if not args.message_id or not args.memo_name:
                    raise ValueError("attachment upload 需要 --message-id 和 --memo-name")
                _json_print(queue.upload_message(args.message_id, args.memo_name, memos))
            elif args.action == "process":
                if not config.flags.attachments:
                    raise ValueError("REVIEW_ENABLE_ATTACHMENTS=false，拒绝处理附件")
                if memos is None:
                    raise ValueError("Memos 客户端不可用")
                _json_print(queue.process_pending(memos))
            elif args.action == "retry":
                if args.id is None:
                    raise ValueError("attachment retry 需要 --id")
                _json_print(queue.retry(args.id))
            else:
                _json_print({"moved_to_manual": queue.expire(datetime.now(config.timezone))})
            return 0

    except (ConfigError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        if logger is not None:
            logger.emit("reviewctl.command", "error", command=args.command, error_type=type(exc).__name__)
        print(json.dumps({"status": "error", "type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 1


def _doctor(config: AppConfig, state: StateRepository, memos: MemosClient | None) -> dict:
    """执行不泄露凭据的部署自检。"""

    paths = {
        "state_parent": config.path("REVIEW_STATE_DB").parent,
        "jobs_file": config.path("REVIEW_JOBS_FILE"),
        "skysight_input": Path(config.values.get("REVIEW_SKYSIGHT_READER") or config.values["REVIEW_SKYSIGHT_ARCHIVE_ROOT"]),
        "attachment_spool": config.path("REVIEW_ATTACHMENT_SPOOL"),
        "log_dir": config.path("REVIEW_LOG_DIR"),
        "user_md_parent": config.path("REVIEW_USER_MD").parent,
    }
    checks = {name: {"exists": path.exists(), "path": str(path)} for name, path in paths.items()}
    checks["memos_client"] = {"configured": memos is not None}
    checks["state_db"] = {"exists": state.path.exists(), "path": str(state.path)}
    # 只聚合状态数量，不输出附件路径、用户正文、邮件或健康原始值。
    with state.connect() as connection:
        projection_rows = connection.execute(
            "SELECT status,COUNT(*) AS count FROM projection_outbox GROUP BY status"
        ).fetchall()
        attachment_rows = connection.execute(
            "SELECT status,COUNT(*) AS count FROM attachments GROUP BY status"
        ).fetchall()
        frozen_cycles = connection.execute(
            "SELECT COUNT(*) AS count FROM stage_cycles WHERE status='awaiting_close'"
        ).fetchone()
        integrity = connection.execute("PRAGMA quick_check").fetchone()
    queues = {
        "projections": {str(row["status"]): int(row["count"]) for row in projection_rows},
        "attachments": {str(row["status"]): int(row["count"]) for row in attachment_rows},
        "frozen_cycles": int(frozen_cycles["count"]),
    }
    checks["sqlite_integrity"] = {"ok": bool(integrity and integrity[0] == "ok")}
    required = ("state_db", "state_parent", "jobs_file", "skysight_input", "log_dir")
    healthy = checks["sqlite_integrity"]["ok"] and all(checks[name]["exists"] for name in required)
    return {
        "status": "ok" if healthy else "error",
        "checks": checks,
        "queues": queues,
        "flags": config.flags.__dict__,
    }


def main() -> None:
    """console_scripts 入口。"""

    raise SystemExit(run())


if __name__ == "__main__":
    main()
