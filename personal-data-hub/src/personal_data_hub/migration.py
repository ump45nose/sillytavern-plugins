"""旧 CRM SQLite 的原始 ID 和 JSON 类型迁入已有 PostgreSQL。"""
from __future__ import annotations

import json

from sqlalchemy import DateTime, JSON, insert, select

from .collectors import snapshot
from .contracts import instant


def backup(store, destination):
    import os, tempfile
    from pathlib import Path
    from personal_crm.storage.models import Base
    from .contracts import canonical
    from .storage import metadata
    from .processing.schema import metadata as processing_metadata
    target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".hub-backup-")
    count = 0
    try:
        isolation = "REPEATABLE READ" if store.engine.dialect.name == "postgresql" else "SERIALIZABLE"
        with os.fdopen(fd, "w") as out, store.engine.connect().execution_options(isolation_level=isolation) as c:
            with c.begin():
                out.write(canonical({"schema_version": 1, "format": "hub-jsonl", "assets": "stored_separately"}) + "\n")
                from personal_crm.archive.models import metadata as crm_metadata
                for table in [*metadata.sorted_tables, *processing_metadata.sorted_tables, *Base.metadata.sorted_tables, *crm_metadata.sorted_tables]:
                    for row in c.execute(select(table)).mappings():
                        out.write(canonical({"table": table.name, "row": dict(row)}) + "\n"); count += 1
            out.flush(); os.fsync(out.fileno())
        os.replace(name, target)
    finally: Path(name).unlink(missing_ok=True)
    return {"rows": count, "path": str(target)}
