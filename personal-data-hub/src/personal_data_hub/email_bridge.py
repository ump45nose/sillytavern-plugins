"""本机复用现有邮件服务的三项只读工具，不复制其实现或账户凭据。"""
import asyncio
import json
import subprocess
from contextlib import asynccontextmanager

from mcp.types import CallToolResult

BRIDGE = r'''
import asyncio, datetime, json, sys
from mcp_email_server import app
allowed = {"list_emails_metadata", "get_emails_content", "get_attachment_content"}
async def main():
    for line in sys.stdin:
        try:
            request = json.loads(line)
            name, args = request["name"], request["args"]
            if name not in allowed or args.get("mark_as_read", False):
                raise ValueError("read_only_bridge")
            for key in ("since", "before"):
                if args.get(key): args[key] = datetime.datetime.fromisoformat(args[key].replace("Z", "+00:00"))
            value = await getattr(app, name)(**args)
            doc = value.model_dump(mode="json", by_alias=True, exclude_none=True)
            if "content" not in doc: doc = {"content": [], "structuredContent": doc}
        except Exception as error:
            # Carry a safe cause across the container boundary, never raw
            # IMAP/server messages that can contain accounts or credentials.
            text = str(error).lower()
            code = ("auth" if any(x in text for x in ("authenticationfailed", "authentication failed", "login failed"))
                    else "timeout" if isinstance(error, TimeoutError)
                    else "network" if isinstance(error, (ConnectionError, OSError)) else "read")
            detail = {"error_type": type(error).__name__, "error_code": code}
            doc = {"content": [{"type":"text", "text":json.dumps(detail)}], "isError": True}
        sys.__stdout__.write(json.dumps(doc, ensure_ascii=False) + "\n")
        sys.__stdout__.flush()
asyncio.run(main())
'''


class LocalEmailSession:
    def __init__(self, container):
        self.process = subprocess.Popen(["docker", "exec", "-i", container, "python", "-u", "-c", BRIDGE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    async def call_tool(self, name, args):
        def exchange():
            self.process.stdin.write(json.dumps({"name": name, "args": args}) + "\n"); self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line: raise RuntimeError("email_bridge_disconnected")
            return CallToolResult.model_validate(json.loads(line))
        return await asyncio.wait_for(asyncio.to_thread(exchange), timeout=180)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()


@asynccontextmanager
async def local_email_session(container):
    session = LocalEmailSession(container)
    try: yield session
    finally: session.close()
