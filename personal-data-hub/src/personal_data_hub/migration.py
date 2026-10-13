"""旧 CRM SQLite 的原始 ID 和 JSON 类型迁入已有 PostgreSQL。"""
from __future__ import annotations

import json

from sqlalchemy import DateTime, JSON, insert, select

from .collectors import snapshot
from .contracts import instant


def import_crm(store, path, overwrite=False):
    from personal_crm.storage.models import Base
    Base.metadata.create_all(store.engine)
    counts = {}
    with snapshot(path) as legacy, store.lock("crm-migration"), store.engine.begin() as c:
        for name in ("people", "interactions", "facts", "reminders", "sync_clients"):
            table = Base.metadata.tables[name]
            count = 0
            for old in legacy.execute('SELECT * FROM "' + name + '"'):
                values = dict(old)
                from .storage import tombstones
                identity = store.identity("crm", name + ":" + str(values.get("id", "")))
                if c.scalar(select(tombstones.c.record_id).where(tombstones.c.record_id == identity)): continue
                if values.get("person_id") and c.scalar(select(tombstones.c.record_id).where(tombstones.c.record_id == store.identity("crm", "people:" + values["person_id"]))): continue
                for col in table.columns:
                    if values.get(col.name) is None: continue
                    if isinstance(col.type, JSON): values[col.name] = json.loads(values[col.name])
                    elif isinstance(col.type, DateTime) or col.type.__class__.__name__ == "UTCDateTime": values[col.name] = instant(values[col.name])
                where = [col == values[col.name] for col in table.primary_key]
                if c.execute(select(table).where(*where)).first():
                    # 初次导入后必须停旧写入再做最后追平；不能覆盖新服务的写入。
                    if overwrite:
                        from sqlalchemy import update
                        c.execute(update(table).where(*where).values(**values))
                    continue
                c.execute(insert(table).values(**values)); count += 1
            counts[name] = count
    return counts


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
                for table in [*metadata.sorted_tables, *processing_metadata.sorted_tables, *Base.metadata.sorted_tables]:
                    for row in c.execute(select(table)).mappings():
                        out.write(canonical({"table": table.name, "row": dict(row)}) + "\n"); count += 1
            out.flush(); os.fsync(out.fileno())
        os.replace(name, target)
    finally: Path(name).unlink(missing_ok=True)
    return {"rows": count, "path": str(target)}
