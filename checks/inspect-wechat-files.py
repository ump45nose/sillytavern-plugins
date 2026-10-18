"""为已有消息补充文件元数据和媒体定位；不重投正文或推进水位。"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from personal_crm.connector.chatlog import ChatlogMessageSource
from personal_crm.connector.config import ConnectorConfig, as_datetime
from personal_crm.connector.media_reader import LocalMediaResolver, MediaUnavailable


def main():
    p = argparse.ArgumentParser()
    p.add_argument("candidates", type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    cfg = ConnectorConfig.from_env()
    source = ChatlogMessageSource(cfg)
    scopes = {s["conversation_id"]: s for s in source._scopes()}
    rows = json.loads(args.candidates.read_text())
    groups = defaultdict(list)
    for row in rows:
        if not row["record"].get("server_id"):
            groups[(row["account"], row["peer"], row["sent_at"][:10])].append(row)
    for (account, peer, _), group in groups.items():
        if peer not in scopes:
            continue
        dates = [as_datetime(r["sent_at"]) for r in group]
        events = source._read_chunk(
            Path(cfg.chatlog_executable),
            [dict(scopes[peer], account_namespace=account)],
            min(dates) - timedelta(seconds=1),
            max(dates),
        )
        found = {e.get("source_message_key"): e for e in events}
        for row in group:
            event = found.get(row["key"])
            if event:
                row["record"] = {
                    k: event["message"]["record"][k] for k in ["ts", "server_id", "msg_type"]
                }
                row["placeholder"] = event["content"]
    files, media, counts = [], [], Counter()
    resolver = LocalMediaResolver(cfg)
    try:
        for row in rows:
            try:
                if row["peer"] not in scopes or not row["record"].get("server_id"):
                    raise MediaUnavailable("media_message_unavailable")
                if int(row["record"].get("msg_type") or 0) == 49:
                    meta = resolver.metadata(
                        dict(
                            conversation_id=row["peer"],
                            record=row["record"],
                            _media_account_id=scopes[row["peer"]]["account_id"],
                        )
                    )
                    if not meta or meta.get("kind") != "file":
                        counts["not_file"] += 1
                        continue
                    files.append(
                        dict(
                            key=row["key"],
                            name=meta["filename"],
                            placeholder=row.get("placeholder", ""),
                        )
                    )
                media.append(row)
                counts["located"] += 1
            except MediaUnavailable as exc:
                counts[exc.code] += 1
    finally:
        resolver.close()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, data in [("files.json", files), ("media.json", media)]:
        path = args.output / name
        path.write_text(json.dumps(data, ensure_ascii=False))
        path.chmod(0o600)
    print(json.dumps(dict(counts), ensure_ascii=False))


if __name__ == "__main__":
    main()
