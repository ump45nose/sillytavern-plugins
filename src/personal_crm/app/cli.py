"""数据库初始化、完整性检查和备份命令。"""

from __future__ import annotations

import argparse

from personal_crm.storage import CrmRepository

from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    """执行个人 CRM 运维命令。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init-db", "integrity", "backup"])
    parser.add_argument("path", nargs="?")
    args = parser.parse_args(argv)
    repository = CrmRepository(Settings().database_url)
    if args.command == "integrity":
        print(repository.integrity_check())
    elif args.command == "backup":
        if not args.path:
            parser.error("backup requires path")
        print(repository.backup(args.path))
    else:
        print("initialized")
    return 0
