from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Personal Records 服务、迁移与在线备份")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    for name in ("status", "backup"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--database", default=os.getenv("RECORDS_DATABASE", "/data/records.sqlite"))
        if name == "backup": cmd.add_argument("--destination", required=True)
    migrate = commands.add_parser("migrate-hub")
    migrate.add_argument("--source-config", required=True)
    migrate.add_argument("--database", required=True)
    migrate.add_argument("--report")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        from .settings import Settings
        settings = Settings.from_env()
        uvicorn.run(create_app(settings), host=settings.runtime.host, port=settings.runtime.port, access_log=False)
        return
    if args.command == "migrate-hub":
        from .migration import migrate_hub
        print(json.dumps(migrate_hub(args.source_config, args.database, args.report), ensure_ascii=False, indent=2))
        return
    path = Path(args.database).resolve()
    if not path.is_file(): parser.error("database does not exist")
    if args.command == "backup":
        from .store import Store
        Store(path).backup(args.destination)
        print(json.dumps({"backup": args.destination}))
        return
    with sqlite3.connect(path.as_uri()+"?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        print(json.dumps({"integrity": integrity, "health_days": db.execute("SELECT count(*) FROM health_days").fetchone()[0], "bills": db.execute("SELECT count(*) FROM bills").fetchone()[0]}))
        if integrity != "ok": raise SystemExit(1)


if __name__ == "__main__": main()
