"""Favorite archive application service. All effects go through injected ports."""
from copy import deepcopy
from threading import Event, Lock

from media_capabilities.models import FileAsset, MediaUnit, stable_id
from media_capabilities.policies import complete_unit, seed_decision


class ArchiveService:
    def __init__(self, store, library, downloader, files, cloud, strm, remux, options):
        self.store, self.library, self.downloader, self.files = store, library, downloader, files
        self.cloud, self.strm, self.remux, self.options = cloud, strm, remux, options
        self.lock = Lock()
        self.stopped = Event()

    def stop(self):
        self.stopped.set()

    def snapshot(self):
        return self.store.read()

    def run(self, *, backfill=False, unit_keys=None):
        if not self.lock.acquire(blocking=False):
            return {"busy": True}
        try:
            state = self.store.read()
            state.setdefault("schema", 1)
            jobs = state.setdefault("jobs", {})
            state.pop("scan_error", None)
            # Recovery does not depend on current favorite enumeration succeeding.
            for job in list(jobs.values()):
                if job["stage"] != "DONE" and (unit_keys is None or job["unit"]["key"] in unit_keys):
                    self._advance(state, job)
            try:
                baseline = state.setdefault("baseline", {})
                initial = self.library.discover(self.options["users"], resolve_episodes=False) if any(
                    user not in baseline for user in self.options["users"]) else []
                for user in self.options["users"]:
                    if user not in baseline:
                        baseline[user] = [u.key for u in initial if user in u.favored_by]
                self.store.write(state)
                units = self.library.discover(self.options["users"], unit_keys=unit_keys)
                for unit in units:
                    if unit_keys is not None and unit.key not in unit_keys:
                        continue
                    if not (backfill or self.options.get("backfill")) and not any(
                            unit.key not in baseline[user] for user in unit.favored_by):
                        continue
                    if any(j["unit"]["key"] == unit.key for j in jobs.values()):
                        continue
                    job_id = stable_id(unit.key)
                    job = {"id": job_id, "unit": unit.dump(), "stage": "CHECKING",
                           "reason": "", "retained": [], "uploads": {}, "remux_jobs": {}}
                    jobs[job_id] = job
                    self.store.write(state)
                    self._advance(state, job)
            except Exception as exc:
                state["scan_error"] = f"收藏扫描未完成：{type(exc).__name__}"
            self.store.write(state)
            return deepcopy(state)
        finally:
            self.lock.release()

    def _save(self, state, job, stage=None, reason=""):
        if stage:
            job["stage"] = stage
        job["reason"] = reason
        self.store.write(state)

    def _advance(self, state, job):
        try:
            self._process(state, job)
        except Exception as exc:
            # Never persist upstream exception text: it can contain credentials.
            self._save(state, job, reason=f"本阶段等待重试：{type(exc).__name__}")

    def _process(self, state, job):
        if self.stopped.is_set():
            return
        unit = MediaUnit(**job["unit"])
        if not complete_unit(unit):
            # Allow an incomplete favorite season to become complete later.
            current = next((u for u in self.library.discover(self.options["users"])
                            if u.key == unit.key), None)
            if current and complete_unit(current):
                unit = current
                job["unit"] = unit.dump()
            else:
                self._save(state, job, reason="电影版本或目标完整季尚未核实")
                return
        if job["stage"] in {"CHECKING", "SEED_WAIT", "PREVIEW"}:
            source = self.files.capture([i["path"] for i in unit.items])
            torrents = self.downloader.associate(unit, source)
            if not torrents:
                self._save(state, job, "CHECKING", "无法确认对应种子及站点，保留本地")
                return
            eligible = True
            for torrent in torrents:
                okay, retain = seed_decision(torrent, self.options.get("high_ratio", 2),
                                              self.options.get("high_days", 30))
                eligible &= okay
                key = f"{torrent.downloader}:{torrent.info_hash}"
                if retain and key not in job["retained"]:
                    job["retained"].append(key)
            job["source"] = [a.dump() for a in source]
            job["torrents"] = [t.dump() for t in torrents]
            if self.options.get("dry_run", True):
                self._save(state, job, "PREVIEW", "可归档" if eligible else "保种要求未满足或无法确认")
                return
            for torrent in torrents:
                if f"{torrent.downloader}:{torrent.info_hash}" in job["retained"]:
                    # Persist intent before writing the downloader tag.
                    self.store.write(state)
                    self.downloader.mark_retained(torrent)
            if not eligible:
                self._save(state, job, "SEED_WAIT", "保种要求未满足或统计无法确认")
                return
            job["user_states"] = self.library.capture_states(unit, self.options["users"])
            self._save(state, job, "PREPARING")
        if self.options.get("dry_run", True):
            return
        if job["stage"] == "PREPARING":
            source = [FileAsset(**a) for a in job["source"]]
            self.files.verify(source)
            assets = []
            disc_paths = list(dict.fromkeys(i["path"] for i in unit.items
                                           if self.files.is_disc(i["path"])))
            for path in disc_paths:
                episodes = [i["episode"] for i in unit.items
                            if i["path"] == path and i.get("episode") is not None]
                request = {"source": path, "kind": unit.kind, "title": unit.title,
                           "season": unit.season, "episodes": episodes,
                           "runtime_seconds": unit.runtime_seconds, "delete_original": False,
                           "owner": "MediaArchive", "idempotency_key": stable_id([job["id"], path])}
                if path not in job["remux_jobs"]:
                    self.store.write(state)
                    job["remux_jobs"][path] = self.remux.submit(request)
                    self.store.write(state)
                result = self.remux.status(job["remux_jobs"][path])
                if result["stage"] != "DONE":
                    self._save(state, job, reason=result.get("reason") or "等待 REMUX 产物")
                    return
                assets.extend(FileAsset(**row) for row in result["outputs"])
            ordinary = [i for i in unit.items if i["path"] not in disc_paths]
            for item in ordinary:
                for asset in source:
                    if asset.path == item["path"]:
                        asset.episode = item.get("episode")
                        assets.append(asset)
            if not assets or (unit.kind == "tv" and
                              {a.episode for a in assets} != set(unit.expected_episodes)):
                raise ValueError("归档视频清单不完整")
            assets = self.files.describe(assets)
            job["assets"] = [a.dump() for a in assets]
            self._save(state, job, "UPLOADING")
        if job["stage"] == "UPLOADING":
            assets = [FileAsset(**a) for a in job["assets"]]
            self.files.verify(assets)
            for asset in assets:
                if self.stopped.is_set():
                    return
                key = stable_id([asset.path, asset.sha1])
                previous = job["uploads"].get(key)
                directory = self.options["movie_path" if unit.kind == "movie" else "tv_path"]
                directory += "/" + job["id"][:20]
                name = asset.path.replace("\\", "/").rsplit("/", 1)[-1]
                if asset.episode is not None:
                    name = f"S{unit.season:02d}E{asset.episode:02d}-" + name
                if previous and previous.get("receipt"):
                    continue
                if previous:
                    directory, name = previous["directory"], previous["name"]
                observed = self.cloud.find(asset, directory, name)
                if observed is None:
                    if previous:
                        # A timeout or crash after submission does not prove failure.
                        self._save(state, job, reason="上传结果不明，等待云端对账或人工重试")
                        return
                    job["uploads"][key] = {"intent": True, "asset": asset.dump(),
                                            "directory": directory, "name": name}
                    self.store.write(state)
                    observed = self.cloud.upload(asset, directory, name)
                self.cloud.verify(asset, observed)
                job["uploads"][key] = {"asset": asset.dump(), "receipt": observed}
                self.store.write(state)
            self._save(state, job, "CLOUD_VERIFY")
        if self.stopped.is_set():
            return
        if job["stage"] == "CLOUD_VERIFY":
            for upload in job["uploads"].values():
                self.cloud.verify(FileAsset(**upload["asset"]), upload["receipt"])
            self._save(state, job, "STRM_VERIFY")
        if job["stage"] == "STRM_VERIFY":
            artifacts = self.strm.publish(job)
            self.strm.verify(artifacts)
            job["artifacts"] = artifacts
            self._save(state, job, "MIGRATING")
        if job["stage"] == "MIGRATING":
            # A pending library scan may resume much later. Re-check owned
            # playback links before publishing identity or changing user state.
            self.strm.verify(job["artifacts"])
            if not job.get("migration_started"):
                job["user_states"] = self.library.capture_states(unit, self.options["users"])
                job["migration_started"] = True
                self.store.write(state)
            self.library.migrate(job, job["artifacts"], lambda: self.store.write(state))
            self.library.verify_migration(job, job["artifacts"])
            self._save(state, job, "CLEANING")
        if job["stage"] == "CLEANING":
            if not self.options.get("cleanup_enabled", False):
                self._save(state, job, reason="归档及状态迁移完成，等待启用本地清理")
                return
            for upload in job["uploads"].values():
                self.cloud.verify(FileAsset(**upload["asset"]), upload["receipt"])
            self.strm.verify(job["artifacts"])
            self.library.verify_migration(job, job["artifacts"])
            if self.stopped.is_set():
                return
            result = self.downloader.cleanup(job, lambda: self.store.write(state))
            job["cleanup"] = result
            self._save(state, job, "DONE" if result.get("complete") else None,
                       result.get("reason", ""))

    def retry_upload(self, job_id: str):
        """Explicit operator retry after cloud reconciliation; never automatic."""
        with self.lock:
            state = self.store.read()
            job = state["jobs"][job_id]
            if job["stage"] != "UPLOADING":
                raise ValueError("任务不是上传待核实状态")
            for key, intent in list(job["uploads"].items()):
                if not intent.get("receipt"):
                    if self.cloud.find(FileAsset(**intent["asset"]), intent["directory"], intent["name"]):
                        raise ValueError("云端已有文件，请先继续任务对账")
                    del job["uploads"][key]
            self.store.write(state)
