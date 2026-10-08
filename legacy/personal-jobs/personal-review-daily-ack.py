#!/usr/bin/env python3
"""根据 Hermes 成功投递状态提交对应日报的 pending checkpoint。"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3

from review.config import load_config
from review.state import StateRepository


DAILY_JOB_NAME = "personal-review-daily-2130"


def _daily_job(path: Path) -> dict:
    """读取唯一日报任务；重复或缺失时拒绝猜测投递结果。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = [job for job in payload.get("jobs", []) if job.get("name") == DAILY_JOB_NAME]
    if len(jobs) != 1:
        raise RuntimeError("Hermes 日报任务缺失或重复")
    return jobs[0]


def _latest_execution(path: Path, job_id: str) -> dict:
    """读取日报任务最新执行回执，只返回关联与时间字段。"""

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id,status,started_at,finished_at,error FROM executions "
            "WHERE job_id=? ORDER BY claimed_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Hermes 日报缺少执行回执")
    return dict(row)



def _assert_material_delivery(config, job: dict, execution: dict, day: str) -> None:
    """只有同一次执行的实际日报输出才能确认来源游标。"""

    started = datetime.fromisoformat(str(execution["started_at"]))
    finished = datetime.fromisoformat(str(execution["finished_at"]))
    directory = config.path("REVIEW_JOBS_FILE").parent / "output" / str(job["id"])
    matches = []
    for path in directory.glob("*.md"):
        try:
            stamp = datetime.strptime(path.stem, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=config.timezone)
        except ValueError:
            continue
        if started.timestamp() - 1 <= stamp.timestamp() <= finished.timestamp() + 1:
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError("日报执行输出缺失或不唯一，checkpoint 保持 pending")
    document = matches[0].read_text(encoding="utf-8")
    _, separator, response = document.rpartition("\n## Response\n")
    headline = response.strip().splitlines()[0] if separator and response.strip() else ""
    if headline.strip() != f"# 今日日报材料｜{day}":
        raise RuntimeError("日报执行仅有模型回复，未投递对应日期材料，checkpoint 保持 pending")


def main() -> int:
    """只在成功投递覆盖最新 pending 材料时原子确认 checkpoint。"""

    app_root = Path(os.environ.get("REVIEW_APP_ROOT", "/vol2/1000/Docker/personal-review"))
    config = load_config(app_root / ".env", app_root / "config/review.yaml")
    job = _daily_job(config.path("REVIEW_JOBS_FILE"))
    if job.get("last_status") != "ok" or job.get("last_delivery_error"):
        raise RuntimeError("Hermes 日报本次运行或投递未成功，checkpoint 保持 pending")
    if not job.get("last_run_at"):
        raise RuntimeError("Hermes 日报缺少成功运行时间，checkpoint 保持 pending")

    last_run_at = datetime.fromisoformat(str(job["last_run_at"]))
    execution = _latest_execution(config.path("REVIEW_HERMES_EXECUTIONS_DB"), str(job["id"]))
    if execution["status"] != "completed" or execution.get("error") or not execution.get("finished_at"):
        raise RuntimeError("Hermes 日报执行回执未完成，checkpoint 保持 pending")
    finished_at = datetime.fromisoformat(str(execution["finished_at"]))
    if abs((finished_at - last_run_at).total_seconds()) > 5:
        raise RuntimeError("Hermes 日报状态与执行回执不匹配，checkpoint 保持 pending")
    local_run = last_run_at.astimezone(config.timezone)
    session_id = f"daily:{local_run.date().isoformat()}"
    state = StateRepository(config.path("REVIEW_STATE_DB"))
    state.initialize()
    batch = state.pending_checkpoint_batch(session_id)
    if batch["pending"] == 0:
        print(json.dumps({"status": "skipped", "reason": "no-pending", "session_id": session_id}, ensure_ascii=False))
        return 0

    # finished_at 精确界定本次材料；比它新的 refresh 尚未被投递，绝不能误确认。
    prepared_at = datetime.fromisoformat(str(batch["latest_prepared_at"]))
    if prepared_at > finished_at:
        print(json.dumps({"status": "skipped", "reason": "pending-newer-than-delivery", "session_id": session_id}, ensure_ascii=False))
        return 0

    _assert_material_delivery(config, job, execution, local_run.date().isoformat())

    delivery_id = f"hermes-cron:{job['id']}:{execution['id']}"
    result = state.acknowledge_checkpoints(session_id, delivery_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
