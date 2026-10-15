"""验证公开列表的载荷边界及本轮采集与历史数据异常的区别。"""
import asyncio
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from personal_data_hub.contracts import Asset, Batch, Record, canonical, instant
from personal_data_hub.mcp import register_tools
from personal_data_hub.runner import run
from personal_data_hub.server import create_app


async def check_mcp(store):
    server = FastMCP("archive-query-smoke")
    register_tools(server, store, None)
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == "list_data_records")
        assert tool.inputSchema["properties"]["include_content"]["default"] is False
        args = {"source": "large", "limit": 2}
        result = (await client.call_tool("list_data_records", args)).structured_content
        assert len(result["records"]) == 2 and result["next_offset"] is None
        assert len(canonical(result)) < 2500
        assert not {"raw", "normalized", "assets"} & result["records"][0].keys()
        explicit = (await client.call_tool("list_data_records", {**args, "include_content": False})).structured_content
        assert explicit == result
        complete = (await client.call_tool("list_data_records", {**args, "include_content": True})).structured_content
        assert len(canonical(complete)) > 800_000
        assert complete["records"][0]["normalized"]["content"] == "long body " * 45_000
        detail = (await client.call_tool("get_data_record", {"record_id": result["records"][0]["id"]})).structured_content["result"]
        assert detail["raw"]["events"] == "AX\x00" * 100_000
        timed = (await client.call_tool("list_data_records", {**args, "start": "2026-10-07T00:00:00Z"})).structured_content
        assert timed["records"] == []


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "viewer").write_text("read-smoke")
    config = {
        "database_url": "sqlite:///" + str(root / "archive.sqlite"),
        "asset_root": str(root / "assets"),
        "hub_viewer_token_file": str(root / "viewer"),
        "sources": {"large": {"adapter": "skysight"}},
    }
    app = create_app(config, webhook_only=True)
    store = app.state.hub_store
    store.ingest("large", Batch(records=[
        Record(str(i), "computer_summary", {"title": "huge " + str(i), "events": "AX\x00" * 100_000},
               {"content": "long body " * 45_000}, instant("2026-10-06T01:00:00Z"),
               assets=[Asset("note.txt", content=b"original")]) for i in range(2)
    ]))
    client = TestClient(app)
    headers = {"Authorization": "Bearer read-smoke"}
    assert client.get("/api/v1/records").status_code == 401
    response = client.get("/api/v1/records?source=large&limit=2", headers=headers)
    page = response.json()
    assert response.status_code == 200 and len(response.content) < 2500
    assert page["total"] == 2 and page["next_offset"] is None
    assert not {"raw", "normalized", "assets"} & page["records"][0].keys()
    assert all(len(row["title"]) <= 160 and len(row["preview"]) <= 500 for row in page["records"])
    assert client.get("/api/v1/records?limit=1", headers=headers).json()["next_offset"] == 1
    assert client.get("/api/v1/records?limit=1&offset=1", headers=headers).json()["next_offset"] is None
    full = client.get("/api/v1/records?limit=2&include_content=true", headers=headers)
    assert full.status_code == 200 and len(full.content) > 800_000
    rid = page["records"][0]["id"]
    detail = client.get("/api/v1/records/" + rid, headers=headers).json()
    assert detail["raw"]["events"] == "AX\x00" * 100_000 and detail["assets"][0]["name"] == "note.txt"
    for query in ["limit=0", "offset=-1", "include_content=invalid", "start=2026-10-06", "start=2026-10-07T00:00:00Z&end=2026-10-06T00:00:00Z"]:
        assert client.get("/api/v1/records?" + query, headers=headers).status_code == 422
    assert client.get("/api/v1/records?start=2026-10-07T00:00:00Z", headers=headers).json()["total"] == 0
    asyncio.run(check_mcp(store))

    segments = root / "segments"
    segment = segments / "old"
    segment.mkdir(parents=True)
    metadata = segment / "metadata.json"
    metadata.write_text("invalid historical json")
    settings = {"adapter": "skysight", "path": str(segments), "patterns": ["**/metadata.json"]}
    result = run(store, "skysight-raw", settings)
    status = next(row for row in store.status() if row["id"] == "skysight-raw")
    assert result["invalid"] == 1 and status["last_run"]["status"] == "partial"
    assert status["last_run"]["error"] == "segment_invalid"
    assert status["quality_warnings"] == [{"code": "historical_segment_invalid", "count": 1}]
    result = run(store, "skysight-raw", settings)
    status = next(row for row in store.status() if row["id"] == "skysight-raw")
    assert result["invalid"] == 0 and result["historical_invalid"] == 1
    assert status["last_run"]["status"] == "ok" and status["last_run"]["error"] is None
    assert status["quality_warnings"][0]["count"] == 1
    # 缓存消失不能抹掉归档中的质量提示或历史内容。
    metadata.unlink()
    run(store, "skysight-raw", settings)
    assert next(row for row in store.status() if row["id"] == "skysight-raw")["quality_warnings"][0]["count"] == 1
    # 来源修复后同一稳定 ID 更新为有效片段，提示才消失。
    metadata.write_text(json.dumps({"startedAt": "2026-10-06T00:00:00Z", "endedAt": "2026-10-06T00:10:00Z", "eventCount": 1}))
    (segment / "events.jsonl").write_text('{"event":"closed"}\n')
    run(store, "skysight-raw", settings)
    status = next(row for row in store.status() if row["id"] == "skysight-raw")
    assert status["last_run"]["status"] == "ok" and status["quality_warnings"] == []
    assert store.get_record(store.identity("skysight-raw", "old/metadata.json"))["kind"] == "computer_segment"
    print("smoke_ok: HTTP/MCP bounded defaults, explicit content, complete detail, paging, time filters, new invalid partial, historical warning, cache retention, repaired source")
