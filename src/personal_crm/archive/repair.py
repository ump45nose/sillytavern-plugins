"""一次性修整旧微信展示文本；不重新同步、不修改消息身份。"""

import json
import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select, update

from personal_crm.connector.presentation import clean_chat, directory_name, short_name
from personal_crm.core.domain import utcnow

from .models import identities, interactions, people


def repair_wechat(archive, directory, *, accounts, backup=None, apply=False):
    names = {
        item["conversation_id"]: directory_name(item)
        for item in directory["conversations"]
        if item.get("conversation_type") == "direct"
        and not item["conversation_id"].endswith("@chatroom")
    }
    with archive.write() as c:
        people_by_id = {p["id"]: dict(p) for p in c.execute(select(people)).mappings()}
        by_person = defaultdict(list)
        identity_people = {}
        for identity in c.execute(
            select(identities).where(
                identities.c.source == "wechat", identities.c.account.in_(accounts)
            )
        ).mappings():
            by_person[identity["person_id"]].append(identity["external_id"])
            identity_people[identity["id"]] = identity["person_id"]
        person_changes, replacements = [], {}
        for pid, peers in by_person.items():
            person = people_by_id[pid]
            candidates = list(dict.fromkeys(names[p] for p in sorted(peers) if p in names))
            old = person["name"]
            # 只改复合展示标签或技术身份；可读的手工姓名保持原样。
            new = short_name(old)
            technical = peers + [
                contact["value"]
                for contact in person["contacts"]
                if contact["type"] in {"wechat", "wechat_id", "wxid"}
            ]
            if len(candidates) == 1 and (old in technical or new != old):
                new = candidates[0]
            if new != old:
                person_changes.append(
                    {"id": pid, "name": old, "new": new, "updated_at": person["updated_at"]}
                )
            chosen = new
            replacements[pid] = {name: chosen for name in [old, *peers]}
        interaction_changes = []
        for row in c.execute(
            select(interactions).where(
                interactions.c.source == "wechat", interactions.c.type == "chat"
            )
        ).mappings():
            content = clean_chat(
                row["content"], replacements.get(identity_people.get(row["identity_id"]), {})
            )
            if content != row["content"]:
                interaction_changes.append(
                    {
                        "id": row["id"],
                        "content": row["content"],
                        "updated_at": row["updated_at"],
                        "new": content,
                    }
                )
        result = {
            "people": len(person_changes),
            "interactions": len(interaction_changes),
            "applied": apply,
        }
        if not apply:
            return result
        if not backup:
            raise ValueError("backup_path_required")
        path = Path(backup)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 先持久备份，后修改；不覆盖上一轮备份。
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "people": [{k: v for k, v in r.items() if k != "new"} for r in person_changes],
                    "interactions": [
                        {k: v for k, v in r.items() if k != "new"} for r in interaction_changes
                    ],
                },
                f,
                ensure_ascii=False,
                default=str,
            )
            f.flush()
            os.fsync(f.fileno())
        now = utcnow()
        for row in person_changes:
            c.execute(
                update(people)
                .where(people.c.id == row["id"])
                .values(name=row["new"], updated_at=now)
            )
        for row in interaction_changes:
            c.execute(
                update(interactions)
                .where(interactions.c.id == row["id"])
                .values(content=row["new"], updated_at=now)
            )
        return result
