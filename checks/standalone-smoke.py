"""在已安装的环境中验证独立进程和真实 HTTP/MCP；来源为隔离的模拟私聊。"""

import asyncio
import base64
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastmcp import Client

from personal_crm.connector.chatlog import ChatlogMessageSource, SourceBatch
from personal_crm.connector.config import ConnectorConfig
from personal_crm.connector.sync import WeChatConnector


def check():
    assert importlib.util.find_spec("personal_data_hub") is None, "run without Hub installed"
    with tempfile.TemporaryDirectory(prefix="crm-standalone-") as tmp:
        root = Path(tmp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "DATABASE_URL": "sqlite:///" + str(root / "db/crm.db"),
            "CRM_ASSET_ROOT": str(root / "assets"),
            "MCP_DEVELOPMENT_NO_AUTH": "true",
            "CRM_API_TOKEN": "smoke-write",
            "CRM_VIEWER_TOKEN": "smoke-read",
            "WECHAT_WEBHOOK_SECRET": "smoke-collector",
            "PUBLIC_BASE_URL": "",
            "OIDC_DISCOVERY_URL": "",
            "OIDC_CLIENT_SECRET": "",
        }
        command = Path(sys.executable).parent / "personal-crm"
        server = command.with_name("personal-crm-server")
        subprocess.run(
            [str(command), "migrate"], env=env, cwd=root, check=True, capture_output=True
        )
        base = f"http://127.0.0.1:{port}"
        with (root / "server.log").open("w+") as log:
            process = subprocess.Popen([str(server)], env=env, cwd=root, stdout=log, stderr=log)
            try:
                with httpx.Client(base_url=base, trust_env=False, timeout=10) as http:
                    for _ in range(200):
                        if process.poll() is not None:
                            raise RuntimeError("standalone server exited")
                        try:
                            if http.get("/healthz").status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("standalone server did not become ready")
                    url = "/api/v1/crm"
                    read = {"Authorization": "Bearer smoke-read"}
                    write = {"Authorization": "Bearer smoke-write"}
                    assert http.get(url + "/people").status_code == 401
                    assert (
                        http.post(
                            url + "/people", headers=read, json={"name": "denied"}
                        ).status_code
                        == 401
                    )
                    config = ConnectorConfig(
                        webhook_url=base + url + "/ingest/wechat",
                        webhook_token="smoke-collector",
                        checkpoint_path=str(root / "checkpoint.json"),
                    )
                    reader = ChatlogMessageSource(config)
                    scope = dict(
                        account_id="smoke",
                        account_namespace="smoke",
                        conversation_id="peer",
                        requested_id="peer",
                        person_name="小王",
                        conversation_type="direct",
                    )
                    start = datetime.fromisoformat("2026-10-15T10:00:00+08:00")
                    events = [
                        reader._event(
                            dict(
                                ts=start.timestamp() + i * 60,
                                content=text,
                                msg_type=1,
                                is_self=i == 0,
                                server_id=str(i + 1),
                            ),
                            scope,
                        )
                        for i, text in enumerate(["今天有空吗？", "有，下午见。"])
                    ]
                    source = SimpleNamespace(read=lambda _: SourceBatch(events, start))
                    connector = WeChatConnector(config, client=http, source=source)
                    result = connector.sync_once()
                    assert result.sent and result.accepted == 2
                    assert connector.sync_once().duplicates == 2
                    rows = http.get(url + "/interactions", headers=read).json()["items"]
                    assert len(rows) == 1
                    iid = rows[0]["id"]
                    assert (
                        http.patch(
                            url + "/interactions/" + iid,
                            headers=write,
                            json={"content": "人工编辑后的正文"},
                        ).status_code
                        == 200
                    )
                    events.append(
                        reader._event(
                            dict(
                                ts=start.timestamp() + 120,
                                content="新增消息",
                                msg_type=1,
                                is_self=False,
                                server_id="3",
                            ),
                            scope,
                        )
                    )
                    result = connector.sync_once()
                    assert result.accepted == 1 and result.duplicates == 2
                    content = http.get(url + "/interactions/" + iid, headers=read).json()["content"]
                    assert content.startswith("人工编辑后的正文\n") and "新增消息" in content

                    async def mcp():
                        async with Client(base + "/mcp") as client:
                            assert len(await client.list_tools()) == 14
                            got = (
                                await client.call_tool("get_interaction", {"interaction_id": iid})
                            ).data
                            assert got["content"] == content
                            person = (
                                await client.call_tool("create_person", {"data": {"name": "李四"}})
                            ).data
                            shared = (
                                await client.call_tool(
                                    "create_interaction",
                                    {
                                        "data": {
                                            "person_ids": [rows[0]["person_ids"][0], person["id"]],
                                            "date": "2026-10-15",
                                            "content": "三人吃饭",
                                        }
                                    },
                                )
                            ).data
                            assert len(shared["person_ids"]) == 2
                            attachment = (
                                await client.call_tool(
                                    "upload_attachment",
                                    {
                                        "name": "sample.txt",
                                        "media_type": "text/plain",
                                        "content_base64": base64.b64encode(
                                            b"standalone attachment"
                                        ).decode(),
                                    },
                                )
                            ).data
                            download = http.get(
                                url + "/attachments/" + attachment["id"] + "/content", headers=read
                            )
                            assert download.content == b"standalone attachment"

                    asyncio.run(mcp())
                    print(
                        "standalone_smoke_ok: no Hub, CLI migration/server, HTTP auth, collector append/dedup, 14 MCP tools, shared interactions, attachments"
                    )
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read()[-4000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    check()
