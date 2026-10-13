"""MoviePilot-only bindings, including cautious qB provenance and cleanup."""
from pathlib import Path
from urllib.parse import urlsplit

from .files import VIDEO_SUFFIXES, sha1_file
from .models import FileAsset, SeedRule, TorrentSnapshot
from .policies import seed_decision


KEEP_TAG = "MediaArchive_KEEP"


def expected_episodes(providers, season):
    from app.chain.media import MediaChain
    from app.schemas.types import MediaType
    if not providers.get("tmdb"):
        return []
    media = MediaChain().recognize_media(mtype=MediaType.TV, tmdbid=int(providers["tmdb"]))
    seasons = getattr(media, "seasons", {}) or {}
    return [int(e) for e in seasons.get(season, seasons.get(str(season), []))]


class MoviePilotRemux:
    def _service(self):
        from app.core.plugin import PluginManager
        service = PluginManager().get_plugin_attr("DiscRemux", "application")
        if not service:
            raise RuntimeError("DiscRemux 插件未启用或依赖不可用")
        return service

    def submit(self, request):
        from app.core.plugin import PluginManager
        submit = PluginManager().get_plugin_attr("DiscRemux", "submit_request")
        if not submit:
            raise RuntimeError("DiscRemux 接口不可用")
        return submit(request)

    def status(self, job_id):
        return self._service().status(job_id)


class MoviePilotDownloader:
    def __init__(self, files, options=None):
        self.files, self.options = files, options or {}
        self.default_rule = SeedRule(**self.options.get("seed_rule", {}))
        self.site_rules = {str(k): SeedRule(**v) for k, v in self.options.get("site_rules", {}).items()}

    def _clients(self, *, include_all=False):
        from app.helper.downloader import DownloaderHelper
        helper = DownloaderHelper()
        services = helper.get_services()
        clients = {}
        for name, service in services.items():
            if not include_all and self.options.get("downloaders") and name not in self.options["downloaders"]:
                continue
            client = getattr(service.instance, "qbc", None)
            if client is not None:
                clients[name] = client
        if include_all:
            expected = {name for name, config in helper.get_configs().items()
                        if config.type == "qbittorrent"}
            if expected - set(clients):
                raise RuntimeError("部分启用的 qB 无法核实引用关系，禁止清理")
        if not clients:
            raise RuntimeError("MoviePilot 没有可用的 qB 下载器")
        return clients

    def _local(self, value):
        path = Path(value)
        for mapping in sorted(self.options.get("path_mappings", []),
                              key=lambda m: len(m["downloader"]), reverse=True):
            prefix = Path(mapping["downloader"])
            if path.is_relative_to(prefix):
                return str(Path(mapping["local"]) / path.relative_to(prefix))
        return str(path)

    def _inventory(self, *, include_all=False):
        result = []
        for name, client in self._clients(include_all=include_all).items():
            for torrent in client.torrents_info():
                file_rows = client.torrents_files(torrent_hash=torrent["hash"])
                paths = [self._local(str(Path(torrent["save_path"]) / row["name"])) for row in file_rows]
                result.append({"downloader": name, "client": client, "raw": torrent,
                               "files": paths, "file_rows": file_rows})
        return result

    @staticmethod
    def _same_file(left, right):
        try:
            a, b = Path(left).stat(), Path(right).stat()
            return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
        except OSError:
            return False

    def _history(self, asset):
        from app.db.transferhistory_oper import TransferHistoryOper
        record = TransferHistoryOper().get_by_dest(asset.path)
        if record and getattr(record, "status", False) and getattr(record, "download_hash", None):
            return record
        return None

    def _site_rule(self, row):
        from app.db.downloadhistory_oper import DownloadHistoryOper
        raw, client = row["raw"], row["client"]
        trackers = client.torrents_trackers(torrent_hash=raw["hash"])
        hosts = sorted({urlsplit(t.get("url", "")).hostname for t in trackers
                        if urlsplit(t.get("url", "")).scheme in {"http", "https", "udp"}
                        and urlsplit(t.get("url", "")).hostname})
        history = DownloadHistoryOper().get_by_hash(raw["hash"])
        site = str(getattr(history, "torrent_site", None) or "")
        if not site and len(hosts) == 1:
            site = hosts[0]
        rule = self.site_rules.get(site)
        configured = [self.site_rules[h] for h in hosts if h in self.site_rules]
        if rule is None and len(configured) == 1:
            rule = configured[0]
        # Host/site rule representations vary. Only a normalized, explicit rule
        # is trusted; qB's automatic stop limits are not tracker requirements.
        note = getattr(history, "note", None) or {}
        if rule is None and isinstance(note, dict) and isinstance(note.get("seed_rule"), dict):
            rule = SeedRule(**note["seed_rule"])
        if len(hosts) > 1 and not site:
            return "", self.default_rule
        return site, rule or self.default_rule

    def _snapshot(self, row, matched):
        raw = row["raw"]
        props = row["client"].torrents_properties(torrent_hash=raw["hash"])
        site, rule = self._site_rule(row)
        seconds = props.get("seeding_time", raw.get("seeding_time"))
        ratio = props.get("share_ratio", raw.get("ratio"))
        tags = {t.strip() for t in str(raw.get("tags") or "").split(",")}
        source = self.files.capture(matched) if matched else []
        return TorrentSnapshot(row["downloader"], raw["hash"], site, row["files"],
                               int(seconds) if seconds is not None else None,
                               float(ratio) if ratio is not None else None,
                               float(raw.get("progress", 0)) == 1, rule, KEEP_TAG in tags,
                               matched, [a.dump() for a in source])

    def associate(self, unit, files):
        inventory = self._inventory()
        matched, covered = {}, set()
        essential = [a for a in files if Path(a.path).suffix.lower() in VIDEO_SUFFIXES | {".iso", ".bdmv", ".mpls"}]
        if not essential:
            return []
        for asset in essential:
            history = self._history(asset)
            for index, row in enumerate(inventory):
                direct = [p for p in row["files"] if self._same_file(asset.path, p)]
                if not direct and history and history.download_hash == row["raw"]["hash"] and \
                        history.downloader == row["downloader"]:
                    source_path = self._local(str(history.src))
                    if source_path in row["files"]:
                        path = self.files.checked(source_path)
                        if path.stat().st_size == asset.size and sha1_file(path) == sha1_file(Path(asset.path)):
                            direct = [source_path]
                if direct:
                    covered.add(asset.path)
                    matched.setdefault(index, set()).update(direct)
        if covered != {a.path for a in essential}:
            return []
        return [self._snapshot(inventory[index], sorted(paths)) for index, paths in matched.items()]

    def mark_retained(self, torrent):
        client = self._clients(include_all=True)[torrent.downloader]
        client.torrents_add_tags(torrent_hashes=[torrent.info_hash], tags=KEEP_TAG)
        rows = client.torrents_info(torrent_hashes=[torrent.info_hash])
        if not rows or KEEP_TAG not in {s.strip() for s in str(rows[0].get("tags", "")).split(",")}:
            raise RuntimeError("保留标记尚未回读确认")

    def deletion_allowed(self, files):
        try:
            inventory = self._inventory(include_all=True)
            return all(Path(a.path).stat().st_nlink == 1 and not any(
                self._same_file(a.path, p) for row in inventory for p in row["files"]) for a in files)
        except Exception:
            return False

    def cleanup(self, job, checkpoint):
        inventory = self._inventory(include_all=True)
        by_key = {f"{r['downloader']}:{r['raw']['hash']}": r for r in inventory}
        saved = {f"{t['downloader']}:{t['info_hash']}": t for t in job["torrents"]}
        candidates, removable, retained = {}, [], set(job["retained"])
        for key, torrent in saved.items():
            current = by_key.get(key)
            if current is None:
                # Only an owned, persisted deletion intent permits missing task recovery.
                if key not in job.get("deletion_intents", []):
                    return {"complete": False, "reason": "种子消失但没有清理意图，保留本地"}
            else:
                snapshot = self._snapshot(current, torrent["matched_files"])
                eligible, keep = seed_decision(snapshot, self.options.get("high_ratio", 2),
                                               self.options.get("high_days", 30))
                if keep or key in retained:
                    retained.add(key)
                    if key not in job["retained"]:
                        job["retained"].append(key)
                        checkpoint()
                    self.mark_retained(snapshot)
                    continue
                if not eligible:
                    return {"complete": False, "reason": "清理前保种状态无法确认或条件未满足"}
                if set(snapshot.files) != set(torrent["matched_files"]):
                    retained.add(key)
                    continue
            removable.append(key)
            for asset in torrent["source_files"]:
                candidates[asset["path"]] = FileAsset(**asset)
        for asset in job["source"]:
            candidates[asset["path"]] = FileAsset(**asset)
        protected_paths = {p for row in inventory if f"{row['downloader']}:{row['raw']['hash']}" not in removable
                           for p in row["files"]}
        allowed = []
        for asset in candidates.values():
            if not Path(asset.path).exists():
                continue
            self.files.verify([asset])
            if any(self._same_file(asset.path, path) for path in protected_paths):
                continue
            references = {path for path in candidates if self._same_file(asset.path, path)}
            if Path(asset.path).stat().st_nlink > len(references):
                continue
            allowed.append(asset)
        # No filesystem deletion until every candidate has passed all checks.
        for key in removable:
            if key not in job.setdefault("deletion_intents", []):
                job["deletion_intents"].append(key)
                checkpoint()
            if key in by_key:
                row = by_key[key]
                row["client"].torrents_delete(torrent_hashes=[row["raw"]["hash"]], delete_files=False)
                if row["client"].torrents_info(torrent_hashes=[row["raw"]["hash"]]):
                    return {"complete": False, "reason": "下载器删除尚未确认"}
        self.files.remove(allowed)
        return {"complete": True, "removed": [a.path for a in allowed],
                "retained": sorted(retained), "reason": "归档完成；受保留/共享约束的文件已保留" if retained else "归档完成"}
