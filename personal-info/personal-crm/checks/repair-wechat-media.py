"""按缺失附件清单补文件，不重投正文或推进文字水位。

在已有 Mac 采集环境运行，沿用 CRM_ENV_FILE / CHATLOG_* / CRM_WEBHOOK_*。
输入每项为 key、peer、sent_at、record（ts/server_id/msg_type），不包含正文或密钥。
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

import httpx

from personal_crm.connector.chatlog import ChatlogMessageSource
from personal_crm.connector.config import ConnectorConfig, as_datetime
from personal_crm.connector.media_reader import LocalMediaResolver, MediaUnavailable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    config = ConnectorConfig.from_env()
    source = ChatlogMessageSource(config)
    scopes = {s["conversation_id"]: s for s in source._scopes()}
    counts = Counter()
    report = []
    resolver = LocalMediaResolver(config, args.report.with_suffix(".files"))
    try:
        with httpx.Client(timeout=max(config.timeout, 300)) as client:
            for item in json.loads(args.manifest.read_text()):
                key, peer = item["key"], item["peer"]
                try:
                    scope = scopes.get(peer)
                    if scope is None:
                        raise MediaUnavailable("media_conversation_unavailable")
                    record = item["record"]
                    if not record.get("server_id"):
                        sent = as_datetime(item["sent_at"])
                        events = source._read_chunk(
                            Path(config.chatlog_executable),
                            [dict(scope, account_namespace=item["account"])],
                            sent - timedelta(seconds=1),
                            sent,
                        )
                        event = next(
                            (e for e in events if e.get("source_message_key") == key), None
                        )
                        if event is None:
                            raise MediaUnavailable("media_message_unavailable")
                        record = event["message"]["record"]
                    message = dict(
                        conversation_id=peer, record=record, _media_account_id=scope["account_id"]
                    )
                    file = resolver.resolve(message)
                    if file is None:
                        raise MediaUnavailable("media_metadata_unavailable")
                    path = resolver.spool / file["id"]
                    with path.open("rb") as data:
                        response = client.put(
                            config.webhook_url.rstrip("/")
                            + "/media/"
                            + hashlib.sha256(key.encode()).hexdigest(),
                            params=dict(name=file["name"], message_key=key),
                            headers={
                                "X-Webhook-Token": config.webhook_token,
                                "X-Content-SHA256": file["id"],
                                "Content-Type": file["media_type"],
                            },
                            content=iter(lambda: data.read(1024 * 1024), b""),
                        )
                    response.raise_for_status()
                    status = response.json()["status"]
                    if status not in {"attached", "deleted"}:
                        raise ValueError("media_receipt_invalid")
                    path.unlink()
                except MediaUnavailable as exc:
                    status = exc.code
                except httpx.HTTPStatusError as exc:
                    status = "upload_http_" + str(exc.response.status_code)
                except Exception as exc:
                    status = type(exc).__name__
                counts[status] += 1
                report.append(dict(key=key, status=status))
                if len(report) % 50 == 0:
                    print(json.dumps(dict(processed=len(report), counts=counts)), flush=True)
    finally:
        resolver.close()
        args.report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.report.write_text(json.dumps(report))
        args.report.chmod(0o600)
    print(json.dumps(dict(processed=len(report), counts=counts)), flush=True)


if __name__ == "__main__":
    main()
