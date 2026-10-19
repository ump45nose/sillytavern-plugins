"""Presentation, transport and delivery checkpoint checks without business effects."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hermes/reports"))
sys.path.insert(0, str(ROOT / "hermes"))


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


favsync = module("favsync_report", "hermes/reports/favsync/daily_report.py")
benefits = module("benefits_report", "hermes/reports/benefits-automation/daily_report.py")
media = module("daily_report", "hermes/reports/media-automation/daily_report.py")
media_entry = module("media_entry", "hermes/reports/media-automation/cron_entrypoint.py")
telegram = module("telegram_notice_test", "hermes/reports/common/telegram_notice.py")
policy = module("notification_policy", "hermes/apply_notification_policy.py")
watchtower = module("watchtower_report", "hermes/watchtower_monthly_update.py")
episode = module("episode_report", "model/episode_daily.py")
learning = module("learning_report", "model/learning_candidates.py")
welfare = module("welfare_report", "hermes/welfare_monitor.py")
etf = module("etf_report", "hermes/etf_premium_alert.py")
health = module("health_report", "hermes/health-data-freshness.py")
NOW = datetime(2026, 10, 11, 17, 0, tzinfo=media.TIMEZONE)


class FavsyncTests(unittest.TestCase):
    def test_only_platform_and_problem(self):
        status = {"sources": [{"name": "x_bookmarks", "scan_status": "failed", "error": "x_account_changed"}],
                  "execution_history": [{"result": "failed", "kind": "content", "finished_at": NOW.timestamp()}]}
        output = StringIO()
        with patch.object(favsync, "load_status", return_value=status), redirect_stdout(output):
            self.assertEqual(favsync.main(), 0)
        self.assertEqual(output.getvalue(), "- X书签：x_account_changed\n")

    def test_recovered_history_and_known_exclusions_are_silent(self):
        status = {"sources": [{"name": "xhs_creators", "scan_status": "cached"}],
                  "download_errors": [{"platform": "x", "error": "content_unavailable"}],
                  "bundle_errors": [{"bundle_status": "skipped_invalid"}],
                  "execution_history": [{"result": "failed"}]}
        self.assertEqual(favsync.collect_problems(status), [])

    def test_duplicate_platform_issues_are_grouped(self):
        row = {"platform": "pixiv", "error": "authorization_required", "count": 500}
        self.assertEqual(favsync.collect_problems({"bundle_errors": [row, row], "download_errors": [row]}),
                         [("pixiv", "authorization_required")])


class BenefitsTests(unittest.TestCase):
    def row(self, **fields):
        return {"platform": "rewards", "business_date": NOW.date().isoformat(), "execution_status": "ok",
                "business": {"daily": "complete"}, "reason": "success", **fields}

    def test_success_silent_and_failed_login_not_repeated(self):
        self.assertIsNone(benefits.issue_for("rewards", self.row(), NOW.date().isoformat()))
        row = self.row(execution_status="failed", reason="authentication_invalid", business={"daily": "blocked"})
        self.assertEqual(benefits.issue_for("rewards", row, NOW.date().isoformat()), "登录失效")

    def test_actionable_unconfirmed_items_are_preserved(self):
        row = self.row(business={"daily": "unknown"}, details={"items": [
            {"name": "Offer A", "reason": "offer_not_credited"},
            {"name": "Topic B", "reason": "search_topic_unsupported"}]})
        issue = benefits.issue_for("rewards", row, NOW.date().isoformat())
        self.assertIn("未确认", issue)
        self.assertIn("Offer A", issue)
        self.assertIn("Topic B", issue)

    def test_epic_browser_timeout_is_distinct_from_a_failed_challenge(self):
        row = self.row(platform="epic", execution_status="failed", reason="browser_timeout",
                       business={"claim": "unknown"})
        self.assertEqual(benefits.issue_for("epic", row, NOW.date().isoformat()), "浏览器操作超时")

    def test_rewards_streak_alert_names_the_unfinished_daily_task(self):
        row = self.row(business={"daily_streaks": "incomplete"}, details={"items": [
            {"id": "bing_streak", "name": "必应连续打卡", "status": "incomplete", "reason": "fresh_readback"},
            {"id": "app_streak", "name": "APP连续打卡", "status": "complete", "reason": "fresh_readback"}]})
        issue = benefits.issue_for("rewards", row, NOW.date().isoformat())
        self.assertIn("必应连续打卡未完成", issue)
        self.assertNotIn("APP连续打卡", issue)

    def test_rewards_reset_alert_explains_the_new_task_cycle(self):
        row = self.row(execution_status="failed", reason="full_task_cycle_changed", business={"daily": "unknown"})
        self.assertEqual(benefits.issue_for("rewards", row, NOW.date().isoformat()),
                         "平台任务已重置，需核查新一轮")

    def test_desktop_weekly_alerts_uncredited_tasks_but_not_future_locked_days(self):
        row = self.row(business={"desktop_app_weekly": "unknown"}, details={"items": [
            {"name": "桌面 App 周二活动", "status": "unknown", "reason": "offer_not_credited"}]})
        issue = benefits.issue_for("rewards", row, NOW.date().isoformat())
        self.assertIn("桌面APP周任务未确认", issue)
        self.assertIn("桌面 App 周二活动", issue)
        row = self.row(business={"desktop_app_weekly": "complete"}, details={"items": [
            {"name": "桌面 App 周三活动", "status": "blocked", "reason": "platform_locked"},
            {"name": "本周积分20/70", "status": "incomplete", "reason": "weekly_progress"}]})
        self.assertIsNone(benefits.issue_for("rewards", row, NOW.date().isoformat()))

    def test_report_omits_timestamps_and_disabled_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime/delivery"
            root.mkdir(parents=True)
            deployment = root.parents[1] / "benefits-deployment.json"
            deployment.write_text(json.dumps({"tasks": {"aliyun": {"enabled": False}}}))
            with patch.object(benefits, "DELIVERY_ROOT", root), \
                    patch.object(benefits, "TASKS", {"rewards": "Rewards", "aliyun": "Aliyun"}), \
                    patch.object(benefits, "load_result", return_value=(self.row(reason="authentication_invalid"), None)):
                report = benefits.build_report(NOW.date().isoformat())
            self.assertEqual(report, "**福利任务异常**\n- Rewards：登录失效")


class MediaTests(unittest.TestCase):
    def test_unstable_theme_snapshot_retries_but_never_becomes_fake_success(self):
        with patch.object(media, "_theme_worker_rows_once", side_effect=[RuntimeError("snapshot changed"), []]) as read, \
                patch.object(media.time, "sleep"):
            self.assertEqual(media.theme_worker_rows(), [])
            self.assertEqual(read.call_count, 2)
        with patch.object(media, "_theme_worker_rows_once", side_effect=RuntimeError("snapshot changed")) as read, \
                patch.object(media.time, "sleep"):
            with self.assertRaises(RuntimeError):
                media.theme_worker_rows()
            self.assertEqual(read.call_count, 3)

    def prepare(self, previous=None, downloads=None, records=None, themes=None, jobs=None, issues=None):
        with patch.object(media, "moviepilot_rows", return_value=(downloads or [], records or [])), \
                patch.object(media, "theme_worker_rows", return_value=themes or []), \
                patch.object(media, "moviepilot_job_snapshots", return_value=(
                    jobs or {"MediaArchive": [], "DiscRemux": []}, issues or [], "private-token")):
            return media.prepare_report(NOW, previous)

    def test_first_observation_is_not_a_new_task(self):
        message, _, baseline = self.prepare(jobs={"MediaArchive": [
            {"id": "old", "stage": "DONE", "unit": {"title": "Old film"}}]})
        self.assertEqual(message, "")
        self.assertIn("old", baseline["plugins"]["MediaArchive"])
        self.assertEqual(self.prepare(previous=baseline, jobs={"MediaArchive": [
            {"id": "old", "stage": "DONE", "unit": {"title": "Old film"}}]})[0], "")

    def test_new_changed_removed_and_unchanged_tasks(self):
        old = [{"id": "same", "stage": "DONE", "unit": {"title": "Same"}},
               {"id": "change", "stage": "UPLOADING", "unit": {"title": "Changed"}},
               {"id": "gone", "stage": "DONE", "unit": {"title": "Gone"}}]
        _, _, baseline = self.prepare(jobs={"MediaArchive": old})
        new = [old[0], {**old[1], "stage": "DONE"},
               {"id": "new", "stage": "CHECKING", "unit": {"title": "New"}}]
        message, _, _ = self.prepare(previous=baseline, jobs={"MediaArchive": new})
        self.assertNotIn("Same", message)
        self.assertIn("上传中 → 已完成", message)
        self.assertIn("新增，检查中", message)
        self.assertIn("任务记录移除", message)
        self.assertNotIn("阶段汇总", message)

    def test_only_timestamped_period_changes_and_no_release_dump(self):
        downloads = [{"title": "Recent", "date": (NOW - timedelta(minutes=10)).isoformat(),
                      "download_hash": "hash", "torrent_name": "giant.release.debug"},
                     {"title": "Old", "date": (NOW - timedelta(days=2)).isoformat()},
                     {"title": "Future", "date": (NOW + timedelta(hours=1)).isoformat()}]
        records = [{"title": "Recent", "download_hash": "hash", "status": "完成",
                    "updated_at": (NOW - timedelta(minutes=5)).isoformat()}]
        message, _, baseline = self.prepare(downloads=downloads, records=records)
        self.assertEqual(message, "**影视变更 · 10-11**\n- 下载 《Recent》：已提交")
        self.assertEqual(self.prepare(previous=baseline, downloads=downloads, records=records)[0], "")

    def test_initial_refreshed_state_records_are_not_changes(self):
        row = {"film_id": "film", "title": "Old film", "status": "跳过", "updated_at": NOW.isoformat()}
        message, _, baseline = self.prepare(records=[row])
        self.assertEqual(message, "")
        baseline["checked_at"] = (NOW - timedelta(hours=1)).isoformat()
        row["status"] = "已下载"
        self.assertIn("- 片单 《Old film》：已下载", self.prepare(previous=baseline, records=[row])[0])

    def test_api_failure_keeps_its_baseline_and_recovers_without_fake_new_tasks(self):
        jobs = {"MediaArchive": [{"id": "old", "stage": "DONE"}]}
        _, _, baseline = self.prepare(jobs=jobs)
        message, _, failed = self.prepare(previous=baseline, jobs={"MediaArchive": None}, issues=["MediaArchive HTTP 503"])
        self.assertIn("HTTP 503", message)
        self.assertEqual(failed["plugins"], baseline["plugins"])
        self.assertEqual(self.prepare(previous=failed, jobs=jobs)[0], "")

    def test_refreshed_timestamp_without_business_change_is_silent(self):
        row = {"emby_id": "1", "name": "Theme", "status": "done", "source_provider": "provider",
               "updated_at": (NOW - timedelta(days=2)).isoformat()}
        _, _, baseline = self.prepare(themes=[row])
        baseline["checked_at"] = (NOW - timedelta(hours=1)).isoformat()
        row["updated_at"] = (NOW - timedelta(minutes=10)).isoformat()
        self.assertEqual(self.prepare(previous=baseline, themes=[row])[0], "")
        row["status"] = "failed"
        self.assertIn("failed", self.prepare(previous=baseline, themes=[row])[0])

    def test_checkpoint_contains_no_api_token_or_paths(self):
        _, _, value = self.prepare(jobs={"DiscRemux": [{"id": "abc", "stage": "FAILED", "request": {
            "title": "A", "source": "/private/media/path"}, "reason": "private-token unavailable"}]})
        text = json.dumps(value)
        self.assertNotIn("private-token", text)
        self.assertNotIn("/private/media/path", text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state/checkpoint.json"
            media.save_checkpoint(value, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(media.load_checkpoint(path), value)

    def test_delivery_failure_does_not_advance_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(media_entry, "CHECKPOINT", Path(tmp) / "report.json"), \
                patch.object(media_entry, "load_checkpoint", return_value=None), \
                patch.object(media_entry, "prepare_report", return_value=("actual changes", 0, {})), \
                patch.object(media_entry, "save_checkpoint") as save, \
                patch.object(media_entry, "deliver_report", side_effect=RuntimeError("delivery failed")):
            with self.assertRaises(RuntimeError):
                media_entry.main()
            save.assert_not_called()

    def test_empty_baseline_and_successful_report_commit(self):
        for message in ("", "changes"):
            with tempfile.TemporaryDirectory() as tmp, \
                    patch.object(media_entry, "CHECKPOINT", Path(tmp) / "report.json"), \
                    patch.object(media_entry, "load_checkpoint", return_value=None), \
                    patch.object(media_entry, "prepare_report", return_value=(message, 0, {"schema": 1})), \
                    patch.object(media_entry, "save_checkpoint") as save, \
                    patch.object(media_entry, "deliver_report", return_value=0) as send:
                self.assertEqual(media_entry.main(), 0)
                send.assert_called_once_with("media-automation", message)
                save.assert_called_once_with({"schema": 1})


class TelegramTests(unittest.TestCase):
    def test_markdown_and_literal_error_codes(self):
        parts = telegram.markdown_parts("**异常**\n- X书签：x_account_changed\n- `a_b` [网页](https://example.com/a)")
        self.assertEqual(len(parts), 1)
        self.assertIn("*异常*", parts[0])
        self.assertIn("x\\_account\\_changed", parts[0])
        self.assertIn("`a_b`", parts[0])
        self.assertIn("[网页](https://example.com/a)", parts[0])

    def test_utf16_sized_messages_and_code_fences(self):
        text = "**Long report**\n" + "\n".join("- name：" + "\U0001f7e2" * 80 for _ in range(100))
        parts = telegram.markdown_parts(text)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part.encode("utf-16-le")) // 2, telegram.MAX_MESSAGE_CHARS)
            self.assertNotRegex(part, r" \(\d+/\d+\)$")
        self.assertEqual(telegram.markdown_parts(" \n"), [])
        for part in telegram.markdown_parts("```\n" + "\n".join("literal_text" * 30 for _ in range(60)) + "\n```"):
            self.assertEqual(part.count("```"), 2)

    def test_verified_markdown_delivery_and_bot_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"notice_bot_username": "expected"}))
            sent = {"ok": True, "result": {"chat": {"id": -100}, "message_thread_id": 42, "is_topic_message": True}}
            with patch.object(telegram, "LOCAL_CONFIG", path), patch.object(telegram, "_token", return_value="private"), \
                    patch.object(telegram, "_api", side_effect=[{"result": {"username": "expected"}}, sent]) as api:
                self.assertEqual(telegram.send_report("-100", "42", "**Notice**\n- literal_error"), 1)
                self.assertEqual(api.call_args.args[2]["parse_mode"], "MarkdownV2")
            with patch.object(telegram, "LOCAL_CONFIG", path), patch.object(telegram, "_token", return_value="private"), \
                    patch.object(telegram, "_api", return_value={"result": {"username": "wrong"}}) as api:
                with self.assertRaises(RuntimeError):
                    telegram.send_report("-100", "42", "report")
                self.assertEqual(api.call_count, 1)
            sent["result"]["message_thread_id"] = 99
            with patch.object(telegram, "LOCAL_CONFIG", path), patch.object(telegram, "_token", return_value="private"), \
                    patch.object(telegram, "_api", side_effect=[{"result": {"username": "expected"}}, sent]):
                with self.assertRaises(RuntimeError):
                    telegram.send_report("-100", "42", "report")

    def test_empty_report_never_reads_secrets_or_calls_api(self):
        with patch.object(telegram, "_token") as token, patch.object(telegram, "_api") as api:
            self.assertEqual(telegram.send_report("-100", "42", ""), 0)
            token.assert_not_called()
            api.assert_not_called()


class OtherNotificationsTests(unittest.TestCase):
    def test_prompt_policy_changes_only_prompt_and_is_idempotent(self):
        value = {"job_names": ["report"], "prompt_suffix": "Markdown concise"}
        job = {"id": "existing", "name": "report", "prompt": "Keep facts", "enabled": False,
               "deliver": "telegram", "schedule": {"kind": "cron"}, "no_agent": False}
        update = Mock()
        self.assertEqual(policy.apply([job], value, update), ["report"])
        self.assertEqual(set(update.call_args.args[1]), {"prompt"})
        job["prompt"] = update.call_args.args[1]["prompt"]
        self.assertEqual(policy.apply([job], value, update), [])
        self.assertIn("Keep facts", job["prompt"])
        self.assertFalse(job["enabled"])

    def test_monthly_updates_only_show_changed_images(self):
        self.assertEqual(watchtower.changes({"same": "old", "updated": "old"}, {"same": "old", "updated": "new"}),
                         ["- updated：镜像已更新"])

    def test_monthly_updater_preserves_targets_and_keeps_logs_off_stdout(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({"container_proxy_url": "http://local.proxy"}))
            output = StringIO()
            responses = [subprocess.CompletedProcess([], 0, "same\nupdated\n"),
                         subprocess.CompletedProcess([], 0),
                         subprocess.CompletedProcess([], 0, "same\nupdated\n")]
            with patch.object(watchtower, "LOG_FILE", Path(tmp) / "update.log"), \
                    patch.dict(watchtower.os.environ, {"CRON_LOCAL_CONFIG": str(config)}), \
                    patch.object(watchtower, "inspect_images", side_effect=[
                        {"same": "old", "updated": "old"}, {"same": "old", "updated": "new"}]), \
                    patch.object(watchtower.subprocess, "run", side_effect=responses) as run, redirect_stdout(output):
                self.assertEqual(watchtower.main(), 0)
            self.assertEqual(output.getvalue(), "**容器更新**\n- updated：镜像已更新\n")
            command = run.call_args_list[1].args[0]
            self.assertEqual(command[-3:], ["--cleanup", "same", "updated"])
            self.assertIn("--run-once", command)
            self.assertIn("label=com.centurylinklabs.watchtower.enable=false", run.call_args_list[0].args[0])

    def test_health_alert_keeps_diagnostics_only_in_state(self):
        output = StringIO()
        with patch("sys.argv", ["health", "--now", NOW.isoformat()]), \
                patch.object(health, "inspect", return_value=("unhealthy", "stale", "large internal diagnostic")), \
                patch.object(health, "_load_state", return_value={"status": "healthy"}), \
                patch.object(health, "_save_state") as save, redirect_stdout(output):
            self.assertEqual(health.main(), 0)
        self.assertEqual(output.getvalue(), "- 健康数据：超过 3 小时未收到新数据\n")
        self.assertEqual(save.call_args.args[1]["detail"], "large internal diagnostic")

    def test_episode_summary_omits_internal_report_and_noops(self):
        value = {"succeeded": 0, "memory_writes": 0, "profiles": {}}
        self.assertEqual(episode.render(value), "")
        value.update(succeeded=3, profiles={"lingjun": {"backlog": 10, "memory_backlog": 2}})
        self.assertEqual(episode.render(value), "**Episode 同步**\n- 已归档 3 条\n- lingjun：待处理 12 条")

    def test_learning_actions_and_receipts_remain_complete(self):
        value = {"failed": 0, "ready": []}
        self.assertEqual(learning.render(value), "")
        value["ready"] = [{"kind": "skill", "profile": "lingjun", "candidate_id": 17,
                           "version": "abc", "evidence": 3, "title": "A skill", "summary": "Useful facts"}]
        text = learning.render(value)
        self.assertIn("`批准 skill lingjun:17 abc`", text)
        self.assertIn("`拒绝 skill lingjun:17 abc`", text)
        self.assertNotIn("扫描", text)
        self.assertIn(learning._DELIVERY_RECEIPT_PREFIX, learning.delivery_receipt(value, Path('/tmp/unused')))

    def test_welfare_links_are_compact_and_errors_deduplicated(self):
        item = welfare.Item("source", "1", "id", "Offer", "https://example.com", labels={"Steam"})
        self.assertEqual(welfare.format_output([item], []), "**福利新增**\n- [Offer](https://example.com)（Steam）")
        self.assertEqual(welfare.format_output([], ["source: HTTP 429", "source: HTTP 429"]),
                         "**福利采集异常**\n- source: HTTP 429")

    def test_etf_keeps_quote_time_and_estimate_boundary(self):
        row = {"code": "000000", "name": "ETF", "premium_pct": 0.1, "amount_yuan": 100000,
               "quote_time": "14:42", "estimate_time": "14:40"}
        text = etf.format_alert([row], {}, complete=True, received=1, expected=1)
        self.assertIn("估算溢价", text)
        self.assertIn("14:42", text)
        self.assertIn("14:40", text)
        self.assertIn("交易前请复核", text)
        self.assertEqual(len(text.splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
