from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import shutil
import re
import logging
from zoneinfo import ZoneInfo

from .common import SyncError, classify, command, safe_extension, atomic_write
from .config import proxy_url


def timestamp(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        result = dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
        return result if 1142899200 <= result <= time.time() + 300 else None
    except (ValueError, OverflowError):
        return None


def parse_x(data, timezone='Asia/Taipei'):
    if not isinstance(data, list):
        raise SyncError("invalid_export")
    posts = {}
    for message in data:
        if message[0] == -1:
            raise SyncError(classify(json.dumps(message[1])))
        if message[0] not in (2, 3):
            raise SyncError("unexpected_child_extractor")
        meta = message[-1]
        item_id = str(meta["tweet_id"])
        if not item_id.isdigit():
            raise SyncError("invalid_export")
        author = meta.get('author') or {}
        posted = timestamp(meta.get('date'))
        naming = {'group': author.get('nick') or author.get('name') or '作者未知',
                  'date': datetime.fromtimestamp(posted, ZoneInfo(timezone)).strftime('%Y-%m-%d') if posted else '日期未知',
                  'tags': meta.get('hashtags') or re.findall(r'(?<!\w)#[\w]+', meta.get('content', '')),
                  'topic': ''}
        post = posts.setdefault(item_id, {
            "id": item_id, "text": meta.get("content", ""),
            "action_time": timestamp(meta.get("date_bookmarked")),
            "locator": {"url": f"https://x.com/i/web/status/{item_id}", 'naming': naming},
            "assets": [], "expected": int(meta.get("count", 0)),
        })
        if message[0] == 3:
            number = int(meta["num"])
            if number < 1:
                raise SyncError("invalid_export")
            post["assets"].append((number, f"{number:03d}.{safe_extension(meta['extension'])}"))
    for post in posts.values():
        if len(post["assets"]) != post.pop("expected"):
            raise SyncError("incomplete_media_list")
    return list(posts.values())


class XAdapter:
    def __init__(self, cfg):
        self.cfg = cfg

    @contextmanager
    def config_file(self, destination=None):
        xcfg = {
            "cookies": str(Path(self.cfg["state_dir"]) / "x-cookies.txt"),
            "expand": False, "conversations": False, "quoted": False,
            "replies": True, "retweets": False, "cards": False,
            "articles": False, "twitpic": False, "pinned": False,
            "tweet-endpoint": "restid", "showmore": False, "showreplies": False,
            "text-tweets": True, "videos": True, "previews": False,
            "ratelimit": "abort", "retries-api": 1, "locked": "abort",
            "timeline": "tweets", "skip": True,
            "proxy-env": False,
        }
        if proxy := proxy_url(self.cfg, "x"):
            # requests' socks5 scheme resolves locally; let the configured proxy
            # resolve X hostnames instead, preserving domain-based routing.
            if proxy.startswith("socks5://"):
                proxy = "socks5h://" + proxy[len("socks5://"):]
            xcfg["proxy"] = proxy
        if destination:
            xcfg.update({"base-directory": str(destination), "directory": [],
                         "filename": "{num:03}.{extension}"})
        cfg = {"extractor": {"twitter": xcfg, "timeout": 30, "retries": 1},
               "output": {"progress": False, "mode": "null"},
               "cache": {"file": str(Path(self.cfg["state_dir"]) / "gallery-cache.sqlite3")}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=self.cfg["state_dir"]) as f:
            json.dump(cfg, f)
            f.flush()
            yield f.name

    def scan(self, source, cursor=0, start=None):
        if source == "x_likes":
            username = self.cfg["x"]["username"]
            if not username:
                raise SyncError("x_username_required")
            url = f"https://x.com/{username}/likes"
        else:
            url = "https://x.com/i/bookmarks"
        with self.config_file() as config, tempfile.TemporaryFile() as result:
            command([sys.executable, "-m", "gallery_dl", "--config-ignore", "-c", config, "-j", url],
                    self.cfg["command_timeout_seconds"], result)
            result.seek(0)
            try:
                # DataJob returns zero on extraction errors: parse -1 events too.
                return parse_x(json.load(result), self.cfg['timezone']), None
            except (ValueError, KeyError, TypeError, IndexError):
                raise SyncError("invalid_export") from None

    def download(self, item, asset, staging):
        target = staging / asset['filename']
        # gallery-dl leaves unfinished transfers as .part and only promotes
        # successful files to this name. Reuse siblings fetched by this post's
        # preceding invocation, including recovery after an interrupted run.
        if target.is_file() and target.stat().st_size:
            return target
        url = json.loads(item["locator"])["url"]
        numbers = item.get('_pending_numbers', [asset['number']])
        with self.config_file(staging) as config:
            command([sys.executable, "-m", "gallery_dl", "--config-ignore", "-c", config,
                     "--post-filter", f"tweet_id == {int(item['item_id'])}",
                     "--filter", f"num in {numbers}", url],
                    self.cfg["command_timeout_seconds"], warnings_are_errors=False)
        return target


class TelegramAdapter:
    def __init__(self, cfg):
        self.cfg = cfg

    def base(self, storage=None):
        args = [self.cfg["telegram"].get("tdl_binary", "tdl"),
                "--storage", f"type=bolt,path={storage or Path(self.cfg['state_dir']) / 'tdl'}"]
        if proxy := proxy_url(self.cfg, "telegram"):
            args += ["--proxy", proxy]
        return args + ["-n", self.cfg["telegram"]["account"]]

    def login(self, mode, replace=False):
        account = self.cfg["telegram"]["account"]
        destination = Path(self.cfg["state_dir"]) / "tdl" / account
        if destination.exists() and not replace:
            raise SyncError("telegram_session_exists_use_new_account_or_replace")
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise SyncError("telegram_login_requires_interactive_terminal")
        # Authenticate in isolated storage; failed/cancelled login cannot corrupt
        # an existing session or leave a half-login in the active namespace.
        with tempfile.TemporaryDirectory(prefix="telegram-login-", dir=self.cfg["state_dir"]) as directory:
            result = subprocess.call(self.base(directory) + ["login", "-T", mode])
            if result:
                return result
            session = Path(directory) / account
            if not session.is_file() or not session.stat().st_size:
                raise SyncError("telegram_login_session_missing")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = Path(self.cfg["state_dir"]) / "session-backups"
                backup.mkdir(mode=0o700, exist_ok=True)
                shutil.copy2(destination, backup / f"{account}-{time.time_ns()}.bak")
            session.chmod(0o600)
            session.replace(destination)
            print(f"Telegram account '{account}' session saved. Login complete.")
            return 0

    def scan(self, source, cursor=0, start=None):
        with tempfile.TemporaryDirectory(dir=self.cfg["state_dir"]) as directory:
            target = Path(directory) / "export.json"
            args = self.base() + ["chat", "export", "--all", "--with-content", "--raw", "-o", str(target)]
            notice = source == "telegram_notice"
            if notice:
                args += ["-c", self.cfg["telegram_notice"]["chat"]]
            if cursor:
                args += ["-T", "id", "-i", f"{cursor + 1},2147483646"]
            else:
                args += ["-T", "time", "-i", f"{int(start)},{int(time.time())}"]
            command(args, self.cfg["command_timeout_seconds"])
            try:
                data = json.loads(target.read_text())
                dialog = str(int(data["id"]))
                self.account_id = dialog
                records = []
                maximum = cursor
                wanted = {self.origin(m.get('raw', {}))[0] for m in data['messages']} if not notice else set()
                names = self.chat_names(wanted - {None}) if not notice else {}
                for msg in data["messages"]:
                    item_id = str(int(msg["id"]))
                    maximum = max(maximum, int(item_id))
                    created = int(msg["date"])
                    if created < start:
                        continue
                    if notice and not (msg.get("raw") or {}).get("Out", msg.get("out", False)):
                        continue
                    filename = msg.get("file", "")
                    assets = [(1, "001." + safe_extension(Path(filename).suffix))] if filename else []
                    naming = (self.naming(msg, names) if not notice else
                              {"date": datetime.fromtimestamp(created, ZoneInfo(self.cfg["timezone"])).strftime("%Y-%m-%d"),
                               "tags": list(dict.fromkeys(re.findall(r'(?<!\w)#[\w]+', msg.get("text", "")))),
                               "group": "notice_bot", "topic": ""})
                    records.append({"id": item_id, "text": msg.get("text", ""),
                                    "action_time": created, "assets": assets,
                                    "locator": {"dialog": dialog, "message": int(item_id),
                                                "naming": naming}})
                return records, maximum
            except (OSError, ValueError, KeyError, TypeError):
                raise SyncError("invalid_export") from None

    @staticmethod
    def origin(raw):
        forward = raw.get('FwdFrom') or {}
        # SavedFromPeer preserves the actual group even when the author is a user.
        for peer in (forward.get('SavedFromPeer'), raw.get('SavedPeerID'), forward.get('FromID')):
            if isinstance(peer, dict):
                for kind in ('ChannelID', 'ChatID'):
                    if peer.get(kind):
                        return str(peer[kind]), forward.get('SavedFromMsgID') or forward.get('ChannelPost')
        return None, None

    def chat_names(self, wanted):
        if not wanted:
            return {}
        cache = Path(self.cfg['state_dir']) / ('telegram-names-' + self.cfg['telegram']['account'] + '.json')
        try:
            saved = json.loads(cache.read_text())
        except (OSError, ValueError):
            saved = {}
        if wanted <= saved.keys():
            return saved
        try:
            with tempfile.TemporaryFile() as output:
                command(self.base() + ['chat', 'ls', '-o', 'json'], self.cfg['command_timeout_seconds'], output)
                output.seek(0)
                dialogs = json.load(output)
            for dialog in dialogs:
                key = str(dialog['id'])
                if key in wanted and dialog['type'] in ('group', 'channel'):
                    saved[key] = {'title': dialog.get('visible_name', ''),
                                  'topics': {str(t['id']): t['title'] for t in dialog.get('topics', [])}}
            atomic_write(cache, json.dumps(saved, ensure_ascii=False).encode())
        except (SyncError, ValueError, KeyError, TypeError):
            logging.getLogger('favsync').warning('telegram: group_name_lookup_unavailable; using source ID')
        return saved

    def naming(self, message, names):
        raw = message.get('raw') or {}
        group_id, original_id = self.origin(raw)
        group = names.get(group_id, {})
        topic = ''
        topics = group.get('topics', {})
        if topics and original_id:
            # Only fetch the exact forwarded message to obtain its topic pointer;
            # no thread, replies, attachments, or original message text is saved.
            try:
                with tempfile.TemporaryDirectory(dir=self.cfg['state_dir']) as directory:
                    target = Path(directory) / 'topic.json'
                    command(self.base() + ['chat', 'export', '-c', group_id, '--all', '--raw',
                                          '-T', 'id', '-i', f'{original_id},{original_id}', '-o', str(target)],
                            self.cfg['command_timeout_seconds'])
                    original = json.loads(target.read_text())['messages']
                    if original:
                        reply = original[0].get('raw', {}).get('ReplyTo') or {}
                        topic_id = reply.get('ReplyToTopID') or (reply.get('ReplyToMsgID') if reply.get('ForumTopic') else None)
                        topic = topics.get(str(topic_id), '')
            except (SyncError, OSError, ValueError, KeyError, TypeError):
                logging.getLogger('favsync').warning('telegram: topic_name_unavailable; omitted')
        text = message.get('text', '')
        return {'date': datetime.fromtimestamp(int(message['date']), ZoneInfo(self.cfg['timezone'])).strftime('%Y-%m-%d'),
                'tags': list(dict.fromkeys(re.findall(r'(?<!\w)#[\w]+', text))),
                'group': group.get('title') or (f'来源群组-{group_id}' if group_id else '收藏夹'),
                'topic': topic}

    def download(self, item, asset, staging):
        locator = json.loads(item["locator"])
        # One message per invocation. No --group expansion, no channel traversal.
        # tdl's JSON reader filters out messages without a nonempty file/photo field.
        # This is a media marker, not the path used for fetching (it fetches by ID).
        export = {"id": int(locator["dialog"]), "messages": [
            {"id": locator["message"], "type": "message", "file": asset["filename"]}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=self.cfg["state_dir"]) as f:
            json.dump(export, f)
            f.flush()
            command(self.base() + ["dl", "-f", f.name, "-d", str(staging),
                                   "--template", asset["filename"], "--restart"],
                    self.cfg["command_timeout_seconds"])
        return staging / asset["filename"]
