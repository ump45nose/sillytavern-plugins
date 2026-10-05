import asyncio
import copy
import json
import logging
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dingtalk_events.client import SourceError, _CredentialFilter, unwrap_result
from dingtalk_events.producer import DingTalkProducer, load_config


NOW = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)


def todo(record_id="1", title="task", due=None, priority=20):
    return {"taskId": record_id, "subject": title, "dueTime": due, "priority": priority}


class Bus:
    def __init__(self):
        self.events = {}
        self.registrations = []
        self.fail_after_accept_once = False

    def register_event(self, *args):
        self.registrations.append(args[0])

    async def publish(self, name, data, **kwargs):
        self.events[kwargs["event_id"]] = {"name": name, "data": data, **kwargs}
        if self.fail_after_accept_once:
            self.fail_after_accept_once = False
            raise RuntimeError("simulated delivery interruption")
        return {"queued": 1}


class Client:
    def __init__(self):
        self.pages = {"todo": [{"todoCards": [], "hasMore": False}], "approval": [{"values": []}]}
        self.calls = []

    @asynccontextmanager
    async def session(self, source):
        async def call(args):
            self.calls.append((source, args))
            page = int(args.get("pageNum", args.get("pageNumber", 1)))
            response = self.pages[source][page - 1]
            if isinstance(response, Exception):
                raise response
            return copy.deepcopy(response)
        yield call


class EventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {"subject": "owner", "sources": {"todo": {}, "approval": {}}}
        self.client, self.bus = Client(), Bus()
        self.producer = DingTalkProducer(self.bus, config=self.config, storage_path=self.temp.name, client=self.client)

    async def poll(self, now=NOW):
        return await self.producer.poll_once(now=now, force=True)

    async def test_initial_baseline_suppresses_history_then_new_records_emit(self):
        self.client.pages["todo"] = [{"todoCards": [todo(due=int((NOW - timedelta(days=1)).timestamp() * 1000))], "hasMore": False}]
        await self.poll()
        self.assertFalse(self.bus.events)
        await self.poll(NOW + timedelta(minutes=5))
        self.assertFalse(self.bus.events)
        self.client.pages["todo"][0]["todoCards"].append(todo("2"))
        self.client.pages["approval"] = [{"values": [{"taskId": "a1", "processInstanceId": "p1", "title": "review"}]}]
        await self.poll()
        self.assertEqual({e["name"] for e in self.bus.events.values()}, {"dingtalk.todo.assigned", "dingtalk.approval.pending"})
        self.assertTrue(all(e["subject"] == "owner" for e in self.bus.events.values()))

    async def test_due_threshold_emits_once_and_uses_timezone(self):
        due = NOW + timedelta(hours=25)
        self.client.pages["todo"] = [{"todoCards": [todo(due=int(due.timestamp() * 1000))], "hasMore": False}]
        await self.poll()
        await self.poll(NOW + timedelta(hours=1))
        await self.poll(NOW + timedelta(hours=2))
        self.assertEqual(len(self.bus.events), 1)
        event = next(iter(self.bus.events.values()))
        self.assertEqual(event["name"], "dingtalk.todo.due")
        self.assertTrue(event["timestamp"].endswith("+08:00"))
        await self.poll(due + timedelta(seconds=1))
        self.assertEqual(len(self.bus.events), 2)

    async def test_field_reversion_has_distinct_event_id(self):
        self.client.pages["todo"] = [{"todoCards": [todo()], "hasMore": False}]
        await self.poll()
        self.client.pages["todo"][0]["todoCards"][0]["subject"] = "changed"
        await self.poll()
        self.client.pages["todo"][0]["todoCards"][0]["subject"] = "task"
        await self.poll()
        self.assertEqual(len(self.bus.events), 2)

    async def test_failed_later_page_keeps_previous_snapshot(self):
        self.client.pages["todo"] = [{"todoCards": [todo()], "hasMore": False}]
        await self.poll()
        self.client.pages["todo"] = [{"todoCards": [todo("2")], "hasMore": True}, SourceError("upstream_timeout")]
        result = await self.poll()
        self.assertEqual(result["sources"]["todo"]["status"], "degraded")
        self.assertEqual(set(self.producer.state["sources"]["todo"]["records"]), {"1"})
        self.assertFalse(self.bus.events)

    async def test_crash_after_enqueue_restarts_with_same_event_id(self):
        await self.poll()
        self.client.pages["todo"][0]["todoCards"] = [todo()]
        self.bus.fail_after_accept_once = True
        with self.assertRaises(RuntimeError):
            await self.poll()
        self.assertEqual(len(self.bus.events), 1)
        self.producer = DingTalkProducer(self.bus, config=self.config, storage_path=self.temp.name, client=self.client)
        await self.poll()
        self.assertEqual(len(self.bus.events), 1)
        self.assertEqual(self.producer.status(subject="owner")["pending_events"], 0)

    async def test_subject_binding_and_invalid_response_fail_closed(self):
        await self.poll()
        with self.assertRaises(PermissionError):
            self.producer.status(subject="another")
        with self.assertRaises(PermissionError):
            self.producer.list_recent(subject="another")
        with self.assertRaises(PermissionError):
            self.producer.detail("unknown", subject="another")
        self.client.pages["todo"] = [{"todoCards": [{}], "hasMore": False}]
        response = await self.poll()
        self.assertEqual(response["sources"]["todo"]["error"], "todo_record_schema_changed")
        config = copy.deepcopy(self.config)
        config["subject"] = "different"
        with self.assertRaises(ValueError):
            DingTalkProducer(self.bus, config=config, storage_path=self.temp.name, client=self.client)

    async def test_calendar_blank_object_does_not_create_baseline(self):
        self.producer.sources["calendar"] = {"calendar_id": "primary"}
        self.client.pages["calendar"] = [{"events": [{"attendees": None}], "hasMore": False}]
        result = await self.poll()
        self.assertEqual(result["sources"]["calendar"]["error"], "calendar_record_schema_changed")
        self.assertFalse(result["sources"]["calendar"]["initialized"])


class ConfigTests(unittest.TestCase):
    def test_config_private_and_upstream_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = {"subject": "owner", "sources": {"todo": {"url": "https://mcp-gw.dingtalk.com/mcp"}}}
            path.write_text(json.dumps(config))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_config(path)
            path.chmod(0o600)
            self.assertEqual(load_config(path)["subject"], "owner")
            config["sources"]["todo"]["url"] = "https://untrusted.invalid/mcp"
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_error_response_and_transport_log_do_not_leak_credentials(self):
        with self.assertRaises(SourceError):
            unwrap_result({"success": "false", "result": {"values": []}})
        url = "https://mcp-gw.dingtalk.com/mcp?key=secret-value"
        record = logging.LogRecord("httpx", 20, __file__, 1, "HTTP Request: POST %s", (url,), None)
        _CredentialFilter([url]).filter(record)
        self.assertNotIn("secret-value", record.getMessage())


if __name__ == "__main__":
    unittest.main()
