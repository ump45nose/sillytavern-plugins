import argparse
import json
import logging
import os
import signal
import shutil
from pathlib import Path
import requests

from .adapters import TelegramAdapter
from .common import SyncError, process_lock
from .config import load, telegram_accounts, telegram_config
from .engine import Engine
from .store import Store


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Telegram / X / EH / 小红书收藏自动下载器")
    parser.add_argument("--config", default="config.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "sync-once", "status"):
        commands.add_parser(name)
    commands.add_parser("telegram-accounts")
    commands.add_parser('telegram-relayout', help='migrate existing Telegram downloads to the configured flat directory')
    review = commands.add_parser('x-review', help='download an explicit review sample without changing the likes baseline')
    review.add_argument('--source', choices=('likes', 'bookmarks'), default='likes')
    selection = review.add_mutually_exclusive_group()
    selection.add_argument('--limit', type=int, default=30)
    selection.add_argument('--all', action='store_true', help='explicitly download all interface-visible items, including history')
    login = commands.add_parser("telegram-login")
    login.add_argument("--mode", choices=("qr", "code"), default="qr")
    login.add_argument("--account", help="Telegram account label from config")
    login.add_argument("--replace", action="store_true", help="replace this account's session after successful login; keep backup")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = load(args.config)
        if args.command == "telegram-accounts":
            print(json.dumps([{"account": p["account"], "enabled": p["enabled"],
                               "start_date": str(p["start_date"]),
                               "session_exists": (Path(cfg["state_dir"]) / "tdl" / p["account"]).is_file()}
                              for p in telegram_accounts(cfg)], ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            db = Store(cfg["state_dir"])
            try:
                result = db.status()
                result["configured_enabled"] = {s: cfg[s]["enabled"] for s in (
                    "telegram", "x_bookmarks", "x_likes", "eh_favorites", "xhs_favorites", "xhs_likes",
                    "pixiv_art_public", "pixiv_art_private", "pixiv_novel_public", "pixiv_novel_private",
                    "wallabag_entries")}
                result["telegram_accounts"] = [{"account": p["account"], "enabled": p["enabled"]} for p in telegram_accounts(cfg)]
                try:
                    result["storage"].update({"free_bytes": shutil.disk_usage(cfg["download_dir"]).free,
                                              "min_free_bytes": cfg["storage"]["min_free_bytes"],
                                              "resume_free_bytes": cfg["storage"]["resume_free_bytes"]})
                except OSError:
                    result["storage"]["error"] = "filesystem_error"
                session = requests.Session(); session.trust_env = False
                try:
                    response = session.get(cfg["xhs"]["downloader_url"].rstrip("/") + "/docs", timeout=3)
                    result["external_services"] = {"xhs_downloader": "ok" if response.ok else "http_error"}
                except requests.RequestException:
                    result["external_services"] = {"xhs_downloader": "unreachable"}
                try:
                    response = session.get(cfg["wallabag"]["base_url"].rstrip("/") + "/", timeout=3)
                    result["external_services"]["wallabag"] = "ok" if response.ok else "http_error"
                except requests.RequestException:
                    result["external_services"]["wallabag"] = "unreachable"
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                db.close()
            return 0
        def terminate(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, terminate)
        with process_lock(cfg["state_dir"]):
            if args.command == "telegram-login":
                account = args.account or cfg["telegram"]["account"]
                return TelegramAdapter(telegram_config(cfg, account)).login(args.mode, replace=args.replace)
            engine = Engine(cfg)
            try:
                if args.command == 'telegram-relayout':
                    from .migrate import relayout
                    print(json.dumps(relayout(engine), ensure_ascii=False, indent=2))
                    return 0
                elif args.command == 'x-review':
                    if not args.all and not 1 <= args.limit <= 100:
                        raise ValueError('review limit must be between 1 and 100')
                    if not engine.cookie_sync():
                        return 1
                    account = cfg['x_likes']['account']
                    engine.check_x(account)
                    adapter = engine.adapters['x']
                    records, _ = adapter.scan('x_' + args.source)
                    if not args.all:
                        records = records[:args.limit]
                    source = 'x_review_' + args.source
                    engine.store.source(source, account)
                    engine.store.ingest(source, account, records)
                    # Persist the exact ordered sample for review and crash recovery.
                    engine.store.setting(source + ':ids', json.dumps([r['id'] for r in records]))
                    ok = True
                    for number, record in enumerate(records, 1):
                        logging.info('x-review: task=%d/%d item=%s', number, len(records), record['id'])
                        if not engine.drain(source, account, adapter, [record['id']]):
                            ok = False
                    logging.info('x-review: selected=%d requested=%s', len(records), 'all-visible' if args.all else args.limit)
                    return 0 if ok and (args.all or len(records) == args.limit) else 1
                elif args.command == "run":
                    engine.run()
                else:
                    cookie_ok = engine.cookie_sync()
                    cycle_ok = engine.cycle()
                    return 0 if cookie_ok and cycle_ok else 1
            finally:
                engine.store.close()
    except KeyboardInterrupt:
        return 130
    except SyncError as exc:
        logging.error("%s", exc.code)
        return 1
    except Exception as exc:
        logging.error("configuration/runtime error (%s); check config, paths and permissions", type(exc).__name__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
