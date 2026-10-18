"""一次转换已归档的微信缓存，保留附件 ID；仅在维护环境使用账号信息。"""

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import select, update

from personal_crm.app.settings import Settings
from personal_crm.archive import Archive
from personal_crm.archive.models import attachments
from personal_crm.archive.service import UNREADABLE_MEDIA
from personal_crm.connector.formats import image_bytes, voice_wav


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--legacy-root", type=Path, required=True)
    p.add_argument("--account", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    cfg = Settings()
    archive = Archive(cfg.database_url, cfg.crm_asset_root, create_schema=False)
    account = json.loads(args.account.read_text())
    with archive.engine.connect() as c:
        rows = [
            dict(r)
            for r in c.execute(
                select(attachments).where(
                    attachments.c.media_type.in_(UNREADABLE_MEDIA),
                    attachments.c.file_key.is_not(None),
                )
            ).mappings()
        ]
    backup = args.report.with_suffix(".before.json")
    with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump(rows, f, default=str, ensure_ascii=False)
    result = []
    for row in rows:
        try:
            source = args.legacy_root / row["file_key"]
            if row["media_type"] == "audio/silk":
                data, extension, mime = voice_wav(source.read_bytes()), "wav", "audio/wav"
            else:
                data, extension, mime = image_bytes(source, account["account"], account["uin"])
            with archive.write() as c:
                key, size = archive._save_file([data])
                c.execute(
                    update(attachments)
                    .where(attachments.c.id == row["id"])
                    .values(
                        file_key=key,
                        size=size,
                        media_type=mime,
                        name=Path(row["name"]).stem + "." + extension,
                    )
                )
            status = "converted"
        except Exception as exc:
            status = getattr(exc, "code", type(exc).__name__)
        result.append(dict(id=row["id"], status=status))
        if len(result) % 100 == 0:
            print(
                json.dumps(
                    dict(
                        processed=len(result),
                        converted=sum(x["status"] == "converted" for x in result),
                    )
                ),
                flush=True,
            )
    args.report.write_text(json.dumps(result))
    args.report.chmod(0o600)
    from collections import Counter

    print(
        json.dumps(
            dict(processed=len(result), statuses=dict(Counter(r["status"] for r in result)))
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
