"""每日推送：对象分组、今日样本、完整账单分页、事件快照与鉴权。"""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from personal_crm.archive import Archive
from personal_crm.events import ChatEventProducer
from personal_data_hub.contracts import Batch, Record, instant
from personal_data_hub.daily_push import DailyPushData, daily_push_page
from personal_data_hub.mcp import register_tools
from personal_data_hub.server import create_app


class Sink:
    def __init__(self):
        self.subject = "owner"
        self.fail = False
        self.sent = []
    def register_event(self, *args, **kwargs): pass
    def authenticated_subject(self): return self.subject
    async def publish(self, name, data, **kwargs):
        if self.fail: raise ConnectionError("retry")
        self.sent.append(data)
        return {"queued": 0}


async def check():
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "viewer").write_text("daily-read")
        config = {"database_url": "sqlite:///" + str(root / "hub.db"),
                  "asset_root": str(root / "assets"), "hub_viewer_token_file": str(root / "viewer"),
                  "sources": {}}
        app = create_app(config, webhook_only=True)
        store = app.state.hub_store
        repo = Archive(engine=store.engine, asset_root=store.root)
        a, b = repo.create_person({"name":"同名联系人"}), repo.create_person({"name":"同名联系人"})
        long_text = "完整正文🙂\n" * 2200 + "尾字符"
        for person, stamp, text, direction in [
            (a, "2026-10-09T08:00:00+08:00", "消息一", "inbound"),
            (b, "2026-10-09T08:01:00+08:00", "另一对象", "outbound"),
            (a, "2026-10-09T09:00:00+08:00", long_text, "outbound"),
            (b, "2026-10-08T09:00:00+08:00", "昨天聊天", "inbound"),
            (b, "2026-10-10T00:00:00+08:00", "明天聊天", "inbound"),
        ]:
            repo.create_interaction({"person_ids":[person["id"]],"date":stamp[:10],"started_at":instant(stamp),"ended_at":instant(stamp),
                "type":"chat","channel":"wechat","content":text,"source":"wechat"})
        def put(eid, kind, raw, normal=None, stamp="2026-10-09T12:00:00+08:00"):
            store.ingest("daily-test", Batch(records=[Record(eid, kind, raw, normal or {}, instant(stamp))]))
        payload = {"steps": [{"count": 900, "start_time": "2026-10-09T00:00:00+08:00", "end_time": "2026-10-09T12:00:00+08:00"}],
                   "sleep": [{"duration_seconds": 28800, "session_end_time": "2026-10-09T07:00:00+08:00"}],
                   "resting_heart_rate": [{"bpm": 66, "time": "2026-10-08T08:00:00+08:00"}],
                   "heart_rate": [{"bpm": 70, "time": "2026-10-09T12:00:00+08:00"}]}
        put("health-a", "health_payloads", {}, {"payload": payload})
        put("health-b", "health_payloads", {}, {"payload": payload})
        for i in range(12):
            put("bill-" + str(i), "bill", {"bill": {"money": "0.10", "currency": "CNY",
                "type": "Expend", "state": "Synced", "shopName": "商店", "remark": str(i)}})
        for eid, stamp, typ, state, amount, currency in [
            ("yesterday", "2026-10-08T23:59:59+08:00", "Income", "Synced", "999", "CNY"),
            ("tomorrow", "2026-10-10T00:00:00+08:00", "Expend", "Synced", "999", "CNY"),
            ("pending", "2026-10-09T08:00:00+08:00", "Expend", "Wait2Edit", "99", "CNY"),
            ("transfer", "2026-10-09T08:00:00+08:00", "Transfer", "Synced", "30", "CNY"),
            ("usd", "2026-10-09T08:00:00+08:00", "Income", "Edited", "2.25", "USD"),
            ("unknown", "2026-10-09T08:00:00+08:00", "Unknown", "Synced", "40", "CNY"),
        ]:
            put(eid, "bill", {"currency": currency, "money": amount, "type": typ, "state": state}, stamp=stamp)
        daily = DailyPushData(store, repo)
        snapshot = daily.snapshot("2026-10-09", cutoff="2026-10-09T23:00:00+08:00")
        assert snapshot["crm"]["total_contacts"] == 2 and snapshot["crm"]["total_messages"] == 3
        assert "昨天聊天" not in json.dumps(snapshot, ensure_ascii=False)
        metrics = {m["metric"]: m for m in snapshot["health"]["metrics"]}
        assert metrics["steps"]["value"] == 900 and metrics["sleep"]["value"] == 8
        assert metrics["heart_rate"]["sample_count"] == 1
        assert "resting_heart_rate" in snapshot["health"]["missing_metrics"]
        assert "resting_heart_rate" not in metrics
        totals = {t["currency"]: t for t in snapshot["finance"]["totals"]}
        assert totals["CNY"]["expense"] == "1.20" and totals["CNY"]["income"] == "0"
        assert totals["CNY"]["transfer"] == "30" and totals["CNY"]["pending_count"] == 1
        assert totals["CNY"]["unclassified_count"] == 1 and totals["USD"]["income"] == "2.25"
        offset, messages, bills = 0, [], []
        while True:
            page = daily_push_page(snapshot, offset, 2)
            assert len(json.dumps(page).encode()) < 65536
            messages.extend(m for c in page["crm"]["contacts"] for m in c["messages"])
            bills.extend(page["finance"]["bills"])
            offset = page["next_offset"]
            if offset is None: break
        chunks = sorted([m for m in messages if "text_offset" in m], key=lambda m: m["text_offset"])
        assert "".join(m["text"] for m in chunks) == long_text
        assert len(bills) == 16
        client = TestClient(app)
        assert client.get("/api/v1/daily-push").status_code == 401
        headers = {"Authorization": "Bearer daily-read"}
        assert client.get("/api/v1/daily-push", params={"day": "2026-10-09"}, headers=headers).status_code == 200
        for params in ({"day": "bad"}, {"tz": "bad/zone"}, {"limit": 0}, {"offset": -1}):
            assert client.get("/api/v1/daily-push", params=params, headers=headers).status_code == 422
        sink = Sink()
        producer = ChatEventProducer(repo, sink, owner="owner", storage_path=str(root / "events"), daily_data=daily)
        sink.fail = True
        try:
            await producer.run_once(instant("2026-10-09T23:00:00+08:00"))
        except ConnectionError: pass
        else: raise AssertionError("publish should fail")
        pending = producer._load_state()["pending_report"]
        frozen = producer.read_daily_push(pending, subject="owner")
        put("later-bill", "bill", {"money": "999", "type": "Income", "currency": "CNY"})
        sink.fail = False
        await producer.run_once(instant("2026-10-09T23:05:00+08:00"))
        assert producer.read_daily_push(pending, subject="owner") == frozen
        assert sink.sent[0]["read_tool"] == "get_daily_push_data"
        assert await producer.run_once(instant("2026-10-09T23:06:00+08:00")) is None
        server = FastMCP("daily-push-smoke")
        register_tools(server, store, None, chat_reports=producer)
        async with Client(server) as mcp:
            actual = (await mcp.call_tool("get_daily_push_data", {"report_id": pending})).structured_content
            assert actual == frozen
            sink.subject = "another-owner"
            try:
                await mcp.call_tool("get_daily_push_data", {"report_id": pending})
            except (ToolError, PermissionError): pass
            else: raise AssertionError("cross-owner read must fail")
        # 新增展示字段不能改变旧消息版本，从而重发整段历史。
        record = producer._all_records(instant("2026-10-09T23:00:00+08:00"))[0][0]
        assert producer._version(record) == producer._version({k: v for k, v in record.items() if k != "sender"})
        # 升级前报告以 sidecar 冻结；不修改原报告和生产水位。
        path = producer.reports / (pending + ".json")
        original = json.loads(path.read_text()); original.pop("_daily_push")
        producer._write(path, original)
        before = path.read_bytes(), producer._load_state()
        first = producer.read_daily_push(pending, subject="owner")
        put("after-sidecar", "bill", {"money": "3", "type": "Income", "currency": "CNY"})
        assert producer.read_daily_push(pending, subject="owner") == first
        assert (path.read_bytes(), producer._load_state()) == before
        assert daily.snapshot("2026-10-10")["health"]["empty_day"] is True
        # 没有聊天但有当日账单，事件仍有需要读取的数据。
        bill_only = ChatEventProducer(repo, sink, owner="owner",
            storage_path=str(root / "bill-only"), daily_data=daily)
        await bill_only.run_once(instant("2026-10-11T20:00:00+08:00"))
        put("bill-only-day", "bill", {"money": "1", "type": "Expend", "currency": "CNY"},
            stamp="2026-10-11T12:00:00+08:00")
        await bill_only.run_once(instant("2026-10-11T23:00:00+08:00"))
        assert sink.sent[-1]["daily_count"] == 0 and sink.sent[-1]["empty_day"] is False
        print("daily_push_smoke_ok: grouped chats, lossless pages, same-day health/finance, exact totals, immutable retry, HTTP/MCP auth")


asyncio.run(check())
