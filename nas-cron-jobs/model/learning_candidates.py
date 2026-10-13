#!/usr/bin/env python3
"""Three-day Profile-local Skill/Tool candidate consolidation."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path

from agent.knowledge_distillation import consolidate_profile_candidates
from hermes_state import SessionDB


_DELIVERY_RECEIPT_PREFIX = "HERMES_CRON_DELIVERY_RECEIPT="


def _failure_detail(*, profile: str, stage: str, error: object, error_type: str = "") -> dict:
    return {
        "profile": profile,
        "stage": stage,
        "error_type": str(error_type or "RuntimeError"),
        "error": str(error or "unknown error").strip()[:500] or "unknown error",
        "retryable": True,
    }


def _enabled(home: Path) -> bool:
    try:
        import yaml

        config = yaml.safe_load((home / "config.yaml").read_text()) or {}
        return (
            ((config.get("episode_memory") or {}).get("distillation") or {}).get(
                "enabled"
            )
            is True
        )
    except Exception:
        return False


@contextmanager
def _profile(home: Path):
    previous = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(home)
    from agent.secret_scope import (
        build_profile_secret_scope,
        reset_secret_scope,
        set_secret_scope,
    )

    secret_token = set_secret_scope(build_profile_secret_scope(home))
    try:
        yield
    finally:
        reset_secret_scope(secret_token)
        if previous is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous


def run(root: Path, limit: int) -> dict:
    report = {
        "profiles": 0,
        "processed": 0,
        "updates": 0,
        "failed": 0,
        "failures": [],
    }
    ready: list[dict] = []
    for home in sorted((root / "profiles").iterdir()):
        path = home / "state.db"
        if not home.is_dir() or not path.exists() or not _enabled(home):
            continue
        try:
            db = SessionDB(db_path=path)
        except Exception as exc:
            report["profiles"] += 1
            report["failed"] += 1
            report["failures"].append(
                _failure_detail(
                    profile=home.name,
                    stage="state_db_open",
                    error=exc,
                    error_type=type(exc).__name__,
                )
            )
            continue
        try:
            with _profile(home):
                # Keep each model request small enough to finish behind the
                # auxiliary provider's gateway timeout. Successful batches
                # record dispositions, so the next iteration advances to the
                # next Episode set without reprocessing the same rows.
                remaining = limit
                while remaining > 0:
                    result = consolidate_profile_candidates(
                        db, profile=home.name, limit=min(10, remaining)
                    )
                    processed = int(result.get("processed") or 0)
                    report["processed"] += processed
                    report["updates"] += int(result.get("updates") or 0)
                    if result.get("status") == "failed":
                        report["failed"] += 1
                        report["failures"].append(
                            _failure_detail(
                                profile=home.name,
                                stage="candidate_consolidation",
                                error=result.get("error"),
                                error_type=str(result.get("error_type") or ""),
                            )
                        )
                        break
                    if processed <= 0:
                        break
                    remaining -= processed
            report["profiles"] += 1
            rows = db.list_learning_candidates(
                statuses=("ready_for_review",), limit=50
            )
            for row in rows:
                if row.get("last_notified_version") == row.get("version_hash"):
                    continue
                payload = json.loads(row.get("payload_json") or "{}")
                ready.append(
                    {
                        "profile": home.name,
                        "candidate_id": int(row["id"]),
                        "kind": row["kind"],
                        "version": row["version_hash"],
                        "title": row["title"],
                        "evidence": (
                            row["successful_run_count"]
                            if row["kind"] == "skill"
                            else max(
                                row["repeated_failure_count"],
                                row["successful_run_count"],
                            )
                        ),
                        "summary": str(
                            payload.get("symptom")
                            or payload.get("trigger")
                            or payload.get("description")
                            or ""
                        )[:240],
                    }
                )
            # The scheduler owns delivery and does not provide an atomic
            # callback into this process. Do not mark a version as notified
            # before Telegram has actually accepted it; an undelivered review
            # must remain eligible for the next three-day digest.
        except Exception as exc:
            report["failed"] += 1
            report["failures"].append(
                _failure_detail(
                    profile=home.name,
                    stage="candidate_result_collection",
                    error=exc,
                    error_type=type(exc).__name__,
                )
            )
        finally:
            db.close()
    report["ready"] = ready
    return report


def render(report: dict) -> str:
    lines = [
        "Hermes Skill/Tool 学习候选审核",
        (
            f"扫描 {report['profiles']} 个 Profile，处理 {report['processed']} 条 "
            f"Episode，更新 {report['updates']} 个候选。"
        ),
    ]
    if report["failed"]:
        lines.append(f"失败 Profile：{report['failed']}（已保留待下次重试）")
        for failure in report.get("failures") or []:
            lines.append(
                "失败详情：{profile} {stage} {error_type}: {error}（可重试）".format(
                    **failure
                )
            )
    if not report["ready"]:
        lines.append("本轮没有新的 ready_for_review 候选。")
        return "\n".join(lines)
    for item in report["ready"]:
        lines.extend(
            [
                "",
                (
                    f"[{item['kind']}] {item['profile']}:{item['candidate_id']} "
                    f"v={item['version']} 证据={item['evidence']}"
                ),
                item["title"],
                item["summary"],
            ]
        )
    lines.extend(
        [
            "",
            "回复示例：",
            "批准 skill <profile>:<candidate_id> <version>",
            "拒绝 tool <profile>:<candidate_id> <version>",
            "批准只进入前台修改流程，cron 不会直接修改 Skill 或 Tool。",
        ]
    )
    return "\n".join(lines)


def delivery_receipt(report: dict, root: Path) -> str | None:
    """Encode candidates that may be acknowledged after successful delivery.

    This is an internal trailing stdout record. The scheduler removes it
    before sending the human-facing body, verifies the no-agent cron job id
    and canonical root, then calls
    :func:`confirm_delivery_receipt` only after the platform accepts delivery.
    A failed consolidation deliberately emits no receipt and remains a cron
    business failure; it must not be relabelled as success just to send a
    partial digest.
    """
    if report.get("failed") or not report.get("ready"):
        return None
    candidates = [
        {
            "profile": item["profile"],
            "candidate_id": item["candidate_id"],
            "version": item["version"],
        }
        for item in report["ready"]
    ]
    return _DELIVERY_RECEIPT_PREFIX + json.dumps(
        {
            "kind": "learning_candidates",
            "job_id": os.environ.get("HERMES_CRON_JOB_ID", ""),
            "root": str(root),
            "candidates": candidates,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def confirm_delivery_receipt(receipt: dict, *, expected_root: Path) -> int:
    """Persist de-dup state for candidates whose digest was delivered.

    The scheduler invokes this after, never before, delivery confirmation.
    Validation keeps a malformed stdout marker from widening the Profile scope.
    """
    if receipt.get("kind") != "learning_candidates":
        raise ValueError("unsupported delivery receipt")
    root = Path(str(receipt.get("root") or "")).resolve()
    expected_root = expected_root.resolve()
    if root != expected_root:
        raise ValueError("learning-candidate receipt root does not match scheduler root")
    profiles_root = (root / "profiles").resolve()
    if not root.is_dir() or not profiles_root.is_dir():
        raise ValueError("invalid learning-candidate receipt root")

    grouped: dict[str, list[tuple[int, str]]] = {}
    for item in receipt.get("candidates") or []:
        if not isinstance(item, dict):
            raise ValueError("invalid learning-candidate receipt item")
        profile = str(item.get("profile") or "")
        if not profile or Path(profile).name != profile:
            raise ValueError("invalid learning-candidate profile")
        candidate_id = int(item["candidate_id"])
        version = str(item["version"] or "")
        if candidate_id <= 0 or not version:
            raise ValueError("invalid learning-candidate identity")
        grouped.setdefault(profile, []).append((candidate_id, version))

    marked = 0
    for profile, values in grouped.items():
        state_db = profiles_root / profile / "state.db"
        if not state_db.is_file():
            raise ValueError(f"missing candidate state database for {profile}")
        db = SessionDB(db_path=state_db)
        try:
            marked += db.mark_learning_candidates_notified(values)
        finally:
            db.close()
    return marked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/hermes/.hermes"))
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    report = run(args.root, max(1, args.limit))
    print(render(report))
    receipt = delivery_receipt(report, args.root)
    if receipt:
        print(receipt)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
