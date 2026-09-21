#!/usr/bin/env python3
"""Repair XHS names allocated before detail metadata was available."""
import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from favsync.layout import component


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def detail_identity(data, fallback_author):
    author = str(data.get("作者昵称") or fallback_author or "作者未知")
    raw = str(data.get("发布时间") or "")
    published = raw[:10] if DATE_RE.match(raw[:10]) else ""
    if not published:
        try:
            stamp = float(data.get("时间戳") or 0)
            published = time.strftime("%Y-%m-%d", time.localtime(stamp)) if stamp else "日期未知"
        except (TypeError, ValueError, OSError):
            published = "日期未知"
    return author, published


def note_id_date(item_id):
    """XHS note IDs prefix the creation epoch as eight hex digits."""
    try:
        return datetime.fromtimestamp(int(item_id[:8], 16), ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return "日期未知"


def item_files(root, stem):
    pattern = re.compile(r"^" + re.escape(stem) + r"(?:_\d{3})?\.[^.]+$")
    return sorted(path for path in root.iterdir() if path.is_file() and pattern.match(path.name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="state/state.sqlite3")
    parser.add_argument("--cookies", default="state/xhs-cookie.txt")
    parser.add_argument("--output", default="/vol3/1000/Picture/Downloads/Xiaohongshu")
    parser.add_argument("--url", default="http://127.0.0.1:5556")
    args = parser.parse_args()
    db_path, root = Path(args.state), Path(args.output)
    cookie = Path(args.cookies).read_text().strip()
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    rows = db.execute("""SELECT i.rowid AS discovery_order,i.item_id,i.account,i.locator,
                                n.author,n.published,n.ordinal,n.stem
                         FROM items i JOIN xhs_names n
                           ON n.account=i.account AND n.item_id=i.item_id
                         WHERE i.platform='xhs' ORDER BY i.rowid""").fetchall()
    if not rows:
        print("No XHS names to migrate")
        return 0

    session = requests.Session()
    session.trust_env = False
    identities = []
    for number, row in enumerate(rows, 1):
        locator = json.loads(row["locator"])
        try:
            response = session.post(
                args.url.rstrip("/") + "/xhs/detail",
                json={"url": locator["url"], "download": False, "cookie": cookie,
                      "proxy": None, "check_record": False}, timeout=120)
            response.raise_for_status()
            data = response.json().get("data")
        except (requests.RequestException, ValueError):
            data = None
        if data:
            author, published = detail_identity(data, locator.get("author"))
        else:
            author, published = str(locator.get("author") or "作者未知"), note_id_date(row["item_id"])
            print(f"metadata fallback {number}/{len(rows)}", flush=True)
        identities.append((row, locator, author, published))
        print(f"metadata {number}/{len(rows)}", flush=True)

    ordinals = defaultdict(int)
    reserved = set()
    plans = []
    all_sources = set()
    for row, locator, author, published in identities:
        key = (row["account"], author, published)
        ordinals[key] += 1
        ordinal = ordinals[key]
        proposed = f"{component(author)}_{published}_{ordinal}"
        stem = proposed
        if (row["account"], stem) in reserved:
            stem += "_" + row["item_id"]
        reserved.add((row["account"], stem))
        sources = item_files(root, row["stem"])
        if not sources:
            raise RuntimeError(f"no media found for item {row['item_id']}")
        all_sources.update(sources)
        targets = [root / (stem + source.name[len(row["stem"]):]) for source in sources]
        plans.append((row, locator, author, published, ordinal, stem, sources, targets))

    all_targets = [target for plan in plans for target in plan[-1]]
    if len(set(all_targets)) != len(all_targets):
        raise RuntimeError("target filename collision")
    conflicts = [path for path in all_targets if path.exists() and path not in all_sources]
    if conflicts:
        raise RuntimeError("target path already exists")

    backup = db_path.with_name(f"state-before-xhs-name-migration-{int(time.time())}.sqlite3")
    with sqlite3.connect(backup) as destination:
        db.backup(destination)
    moves = []
    try:
        for plan in plans:
            for source, target in zip(plan[-2], plan[-1]):
                temporary = root / (".__favsync_xhs_" + uuid.uuid4().hex + source.suffix)
                os.replace(source, temporary)
                moves.append([source, temporary, target, False])
        for move in moves:
            os.replace(move[1], move[2])
            move[3] = True
        with db:
            for row, locator, author, published, ordinal, stem, _sources, _targets in plans:
                locator["author"] = author
                locator["published"] = published
                locator["naming"] = {"group": author, "date": published}
                db.execute("""UPDATE xhs_names SET author=?,published=?,ordinal=?,stem=?
                              WHERE account=? AND item_id=?""",
                           (author, published, ordinal, stem, row["account"], row["item_id"]))
                db.execute("""UPDATE items SET locator=? WHERE platform='xhs' AND account=? AND item_id=?""",
                           (json.dumps(locator, ensure_ascii=False), row["account"], row["item_id"]))
    except Exception:
        for source, temporary, target, completed in reversed(moves):
            current = target if completed else temporary
            if current.exists():
                os.replace(current, source)
        raise
    finally:
        db.close()
    print(f"Migrated {len(plans)} notes and {len(moves)} media files")
    print(f"Database backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
