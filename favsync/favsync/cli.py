import argparse
import json
import logging
import os
import signal
import shutil
from pathlib import Path
import requests

from .common import SyncError, process_lock
from .config import load, telegram_accounts, telegram_config
from .store import Store
from .database import migrate
from .sources import SOURCES


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Telegram / X / EH / 小红书收藏自动下载器")
    parser.add_argument("--config", default="config.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "sync-once", "status"):
        cmd = commands.add_parser(name)
        if name == "sync-once":
            cmd.add_argument("--source", choices=SOURCES)
    commands.add_parser("film-api", help="serve the authenticated film watchlist API")
    commands.add_parser("telegram-accounts")
    commands.add_parser("pixiv-login", help="authorize Pixiv once and persist token plus UID automatically")
    xhs_resume = commands.add_parser("xhs-resume", help="manually clear the persistent Xiaohongshu safety fuse")
    xhs_resume.add_argument("--account", default="personal")
    login = commands.add_parser("telegram-login")
    login.add_argument("--mode", choices=("qr", "code"), default="qr")
    login.add_argument("--account", help="Telegram account label from config")
    login.add_argument("--replace", action="store_true", help="replace this account's session after successful login; keep backup")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = load(args.config, mode=args.command, source=getattr(args, "source", None))
        if args.command == "pixiv-login":
            from .pixiv_auth import login as pixiv_login
            with process_lock(cfg["state_dir"]):
                return pixiv_login(cfg)
        if args.command == "telegram-accounts":
            print(json.dumps([{"account": p["account"], "enabled": p["enabled"],
                               "start_date": str(p["start_date"]),
                               "session_exists": (Path(cfg["state_dir"]) / "tdl" / p["account"]).is_file()}
                              for p in telegram_accounts(cfg)], ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            db = Store(cfg["state_dir"], readonly=True)
            try:
                result = db.status()
                result["configured_enabled"] = {s: cfg[s]["enabled"] for s in SOURCES}
                result["telegram_accounts"] = [{"account": p["account"], "enabled": p["enabled"]} for p in telegram_accounts(cfg)]
                try:
                    result["storage"].update({"free_bytes": shutil.disk_usage(cfg["download_dir"]).free,
                                              "min_free_bytes": cfg["storage"]["min_free_bytes"],
                                              "resume_free_bytes": cfg["storage"]["resume_free_bytes"]})
                except OSError:
                    result["storage"]["error"] = "filesystem_error"
                result["external_services"] = {}
                checks = {}
                if cfg["xhs_favorites"]["enabled"] or cfg["xhs_likes"]["enabled"]:
                    checks["xhs_downloader"] = cfg["xhs"]["downloader_url"].rstrip("/") + "/docs"
                if cfg["wallabag_entries"]["enabled"]:
                    checks["wallabag"] = cfg["wallabag"]["base_url"].rstrip("/") + "/"
                if cfg["film_watchlist"]["enabled"]:
                    checks["film_api"] = f"http://{cfg['film_api']['bind_host']}:{cfg['film_api']['port']}/health"
                with requests.Session() as session:
                    session.trust_env = False
                    for name, url in checks.items():
                        try:
                            with session.get(url, timeout=3) as response:
                                result["external_services"][name] = "ok" if response.ok else "http_error"
                        except requests.RequestException:
                            result["external_services"][name] = "unreachable"
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                db.close()
            return 0
        if args.command == "film-api":
            from .film_api import serve
            migrate(cfg["state_dir"])
            serve(cfg)
            return 0
        if args.command == "xhs-resume":
            migrate(cfg["state_dir"])
            db = Store(cfg["state_dir"])
            try:
                previous = db.xhs_fuse(args.account)
                db.clear_xhs_fuse(args.account)
                print(json.dumps({"account": args.account, "cleared": bool(previous),
                                  "previous": previous}, ensure_ascii=False))
            finally:
                db.close()
            return 0
        def terminate(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, terminate)
        if args.command == "telegram-login":
            from .adapters import TelegramAdapter
            account = args.account or cfg["telegram"]["account"]
            with process_lock(cfg["state_dir"]):
                return TelegramAdapter(telegram_config(cfg, account)).login(args.mode, replace=args.replace)
        from .engine import Engine
        engine = Engine(cfg)
        try:
            if args.command == "run":
                engine.run()
            else:
                cookie_ok = True if args.source == "film_watchlist" else engine.cookie_sync()
                cycle_ok = engine.cycle(args.source)
                return 0 if cookie_ok and cycle_ok else 1
        finally:
            engine.close()
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
