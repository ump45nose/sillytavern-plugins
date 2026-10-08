#!/usr/bin/env python3
"""Continuous companion planning with deterministic slots and date idempotency."""
import argparse
from datetime import datetime, time, timedelta
import fcntl
import json
import os
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hermes"))
from companion_runtime import PROFILE, TZ, config, database, history, operational_error, sync_materials, reconcile_responses
from companion_planner import curate, inventory, plan_day

REPO = Path("/home/hermes/.hermes/hermes-agent")
PYTHON = REPO / "venv/bin/python"


def slots_for(target):
    rng = random.Random(f"lingjun-companion:{target.isoformat()}")
    count = rng.randint(2, 4)
    candidates = [datetime.combine(target, time(9), TZ)+timedelta(minutes=30*i) for i in range(28)]
    rng.shuffle(candidates)
    selected = []
    for candidate in candidates:
        if all(abs((candidate-x).total_seconds()) >= 7200 for x in selected):
            selected.append(candidate)
            if len(selected) == count:
                break
    return [{"run_at": stamp.isoformat(), "image": rng.random() < .75} for stamp in sorted(selected)]


def prompt(image):
    text = ("读取预运行脚本提供的单份嘉颖生活上下文与30天记录，结合最新用户回应自然分享本次生活片段。"
            "维持SOUL身份和外貌，自己的生活不要写入用户长期记忆。不要复述素材来源或系统状态。"
            "用户近期已经拒绝或结束这个话题、无新分享角度、事件标记silent时，仅输出[SILENT]。"
            "当天最多一项活动推进，不越过生活状态。已送达内容不重述，失败或待确认不假设用户看过。")
    if image:
        return text + ("直接调用profile_selfie生成嘉颖本人当前活动照片，具体动作、环境与机位由本次片段决定，"
                       "保持成人本人形象，避免证件照式正脸、文字水印和拼图。不要先搜索工具或改用image_generate。"
                       "生成成功最终第一行原样复制工具返回的delivery值，空一行后一句简短自然中文分享；"
                       "不把本地路径写成Markdown图片。如果失败仅输出[SILENT]，不向陪伴话题汇报工具错误。")
    return text + "只输出一到两句自然中文生活分享或回应，不追问、不使用喝水休息模板。"


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-materials", action="store_true", help="Sync/screen cache without creating jobs")
    args = parser.parse_args()
    cfg = config()
    if not cfg.get("enabled", False):
        print(json.dumps({"status": "disabled"})); return 0
    os.environ["HERMES_HOME"] = str(PROFILE)
    sys.path.insert(0, str(REPO))
    from cron.jobs import create_job, list_jobs, update_job
    root = PROFILE / "companion"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / "planner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with database() as db:
            try:
                sync_materials(db)
            except Exception as exc:
                operational_error("materials cached fallback", exc)
            try:
                while curate(db):
                    pass
            except Exception as exc:
                db.rollback()
                operational_error("curation cache retained", exc)
            if args.prepare_materials:
                print(json.dumps(inventory(db), ensure_ascii=False)); return 0
            observed = history(db)
            reconcile_responses(db, observed)
            target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(TZ).date()+timedelta(days=1)
            if target < datetime.now(TZ).date():
                raise ValueError("past companion date")
            slots = slots_for(target)
            prefix = f"lingjun-companion-{target.isoformat()}-"
            existing = {j["name"]:j for j in list_jobs(include_disabled=True) if str(j.get("name", "")).startswith(prefix)}
            if existing and not db.execute("SELECT 1 FROM plans WHERE day=?", (target.isoformat(),)).fetchone():
                ordered = sorted(existing.values(), key=lambda j:j["name"])
                slots = [{"run_at": j["schedule"]["run_at"], "image": "profile_selfie" in (j.get("prompt") or "")} for j in ordered]
            plan = plan_day(db, target.isoformat(), slots, observed, cfg.get("extra_context_tokens", 12000))
            if "activation_at" not in plan:
                available = [slot["run_at"] for index, slot in enumerate(plan["slots"],1)
                             if datetime.fromisoformat(slot["run_at"]) > datetime.now(TZ)
                             and (f"{prefix}{index:02d}" not in existing or
                                  existing[f"{prefix}{index:02d}"].get("state") == "scheduled")]
                plan["activation_at"] = min(available) if available else datetime.combine(target,time(23,59),TZ).isoformat()
                if not available:
                    plan["advancement"] = None
            if args.dry_run:
                print(json.dumps({"plan": plan, "inventory": inventory(db), "history": {k:v for k,v in observed.items() if k!='messages'}}, ensure_ascii=False, indent=2))
                return 0
            db.execute("INSERT OR IGNORE INTO plans(day,payload) VALUES(?,?)", (target.isoformat(), json.dumps(plan, ensure_ascii=False)))
            for key in plan.get("paused", []):
                row = db.execute("SELECT payload FROM activities WHERE id=?", (key,)).fetchone()
                state = json.loads(row[0]); state["status"] = "paused"
                db.execute("UPDATE activities SET payload=? WHERE id=?", (json.dumps(state, ensure_ascii=False), key))
            db.commit()
            created = updated = 0
            for index, (slot, event) in enumerate(zip(plan["slots"], plan["events"]), 1):
                name = f"{prefix}{index:02d}"
                job = existing.get(name)
                eligible = datetime.fromisoformat(slot["run_at"]) > datetime.now(TZ)
                if not eligible or (job and (not job.get("enabled") or job.get("state") != "scheduled")):
                    # Never attach a new life event to an old, completed delivery.
                    continue
                data = {**event, "image": slot["image"], "date": target.isoformat()}
                db.execute("INSERT OR IGNORE INTO events VALUES(?,?,NULL,?,?)",
                           (name, target.isoformat(), slot["run_at"], json.dumps(data, ensure_ascii=False)))
                db.commit()
                changes = {"prompt": prompt(slot["image"]), "script": "companion_pre_run.py", "attach_to_session": False,
                           "context_from": None}
                if job and eligible and job.get("enabled") and job.get("state") == "scheduled":
                    update_job(job["id"], changes); updated += 1
                elif not job and eligible:
                    job = create_job(schedule=slot["run_at"], name=name, repeat=1, deliver=cfg["delivery"],
                                     model="grok-4.7", provider="custom:cpa-local", **changes)
                    created += 1
                if job:
                    db.execute("UPDATE events SET job_id=? WHERE name=?", (job["id"], name)); db.commit()
            print(json.dumps({"date": target.isoformat(), "created": created, "updated": updated, "inventory": inventory(db)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if sys.executable != str(PYTHON):
        os.execv(str(PYTHON), [str(PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
    try:
        raise SystemExit(main())
    except Exception as exc:
        operational_error("planning skipped", exc)
        raise SystemExit(1)
