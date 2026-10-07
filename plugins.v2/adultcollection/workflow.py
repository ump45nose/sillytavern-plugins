"""Adult favorites: Vixen collection moves and JAV wash decisions."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from media_capabilities.acquisition.adult import classify_adult, collection_path
from media_capabilities.acquisition.evidence import magnet_evidence, torrent_evidence
from media_capabilities.acquisition.javdb_cli import JavDbCli, normalize_jav_number
from media_capabilities.acquisition.quality_selection import MediaCandidate
from media_capabilities.acquisition.upgrade import decide_upgrade, facts_from_library, is_4k


def _same_code(value: str, code: str) -> bool:
    try:
        return normalize_jav_number(value) == code
    except ValueError:
        return False


class AdultSourceSearch:
    """Resolve verified M-Team and JavDB candidates without media metadata matching."""

    def __init__(self, config):
        self.config = config
        self.javdb = JavDbCli(config.get("javdb_binary", "javdb"),
                              config.get("source_timeout", 30))

    def _mteam(self, code):
        from app.chain.download import DownloadChain
        from app.chain.search import SearchChain

        site_id = int(self.config.get("mteam_site_id") or 0)
        if not site_id:
            try:
                from media_capabilities.acquisition.runtime import get_runtime
                site_id = int(get_runtime(readonly=True).settings.site_id)
            except Exception:
                site_id = 0
        if not site_id:
            return "UNAVAILABLE", [], "未配置 M-Team 站点"

        try:
            rows = SearchChain().search_by_title(code, sites=[site_id], page=0) or []
        except Exception as exc:
            return "UNAVAILABLE", [], f"M-Team 搜索失败：{type(exc).__name__}"

        rows = [row for row in rows
                if getattr(row, "torrent_info", None)
                and str(getattr(row.torrent_info, "site", "")) == str(site_id)
                and _same_code(str(getattr(row.torrent_info, "title", "")), code)]
        if not rows:
            return "NO_RESULTS", [], ""

        rows.sort(key=lambda row: (
            int(getattr(row.torrent_info, "size", 0) or 0),
            int(getattr(row.torrent_info, "seeders", 0) or 0)), reverse=True)
        result = []
        for context in rows[:max(1, int(self.config.get("preflight_limit", 3)))]:
            torrent = context.torrent_info
            try:
                content, _, _ = DownloadChain().download_torrent(
                    torrent, source="AdultCollection")
                evidence = torrent_evidence(content, torrent.title)
            except Exception:
                continue
            result.append(MediaCandidate(
                "pt", torrent.title, evidence.video_bytes, evidence.total_bytes,
                "mteam:" + evidence.info_hash, info_hash=evidence.info_hash,
                torrent_content=content, context=context, files=evidence.files,
                evidence={"seeders": int(getattr(torrent, "seeders", 0) or 0)}))
        if not result:
            return "UNVERIFIED", [], "M-Team 有结果但无法核实文件信息"
        return "OK", result, ""

    def _javdb(self, code):
        if self.javdb.health()["status"] != "OK":
            return "UNAVAILABLE", [], "javdb-cli 不可用"
        try:
            rows = self.javdb.magnets(
                code, limit=max(3, int(self.config.get("javdb_limit", 12))))
        except Exception as exc:
            return "UNAVAILABLE", [], f"JavDB 搜索失败：{type(exc).__name__}"
        if not rows:
            return "NO_RESULTS", [], ""

        rows.sort(key=lambda row: (
            int(row.hd), int(row.cnsub), row.size_bytes), reverse=True)
        result = []
        for row in rows[:max(1, int(self.config.get("preflight_limit", 3)))]:
            try:
                evidence = magnet_evidence(
                    row.magnet, row.title or code,
                    timeout=int(self.config.get("magnet_timeout", 25)))
            except ValueError:
                continue
            if evidence.private:
                continue
            result.append(MediaCandidate(
                "public_bt", row.title or code, evidence.video_bytes,
                evidence.total_bytes, "javdb:" + evidence.info_hash,
                info_hash=evidence.info_hash, link=row.magnet,
                files=evidence.files,
                evidence={"cnsub": row.cnsub, "hd": row.hd}))
        if not result:
            return "UNVERIFIED", [], "JavDB 有结果但磁力元数据无法核实"
        return "OK", result, ""

    def search(self, code):
        m_status, m_items, m_reason = self._mteam(code)
        j_status, j_items, j_reason = self._javdb(code)
        return {
            "mteam": {"status": m_status, "reason": m_reason,
                      "candidates": m_items},
            "javdb": {"status": j_status, "reason": j_reason,
                      "candidates": j_items},
        }

    def submit(self, candidate):
        if candidate.source == "pt":
            from app.helper.downloader import DownloaderHelper

            helper = DownloaderHelper()
            services = helper.get_services()
            configured = str(self.config.get("downloader") or "")
            choices = [(name, service) for name, service in services.items()
                       if not configured or name == configured]
            for name, service in choices:
                instance = getattr(service, "instance", None)
                add = getattr(instance, "add_torrent", None)
                if not callable(add):
                    continue
                okay, ids = add(
                    content=candidate.torrent_content,
                    download_dir=self.config.get("jav_root", "/Adult/JAV"),
                    tag="AdultWash")
                if okay:
                    return {"status": "submitted", "route": "pt",
                            "downloader": name,
                            "download_hash": (ids or [candidate.info_hash])[0]}
            return {"status": "pending", "route": "pt",
                    "reason": "没有可接收 Adult 洗版任务的下载器"}

        if candidate.source == "public_bt":
            if not self.config.get("public_route_enabled", False):
                return {"status": "pending", "route": "public_bt",
                        "reason": "JavDB 公网自动下载路由未启用"}
            from media_capabilities.acquisition.p115_task_adapter import P115TaskAdapter
            adapter = P115TaskAdapter(
                self.config.get("jav_root", "/Adult/JAV"),
                self.config.get("western_root", "/Adult/Western"),
                self.config.get("adult_strm_root", "/Adult/STRM"),
                allowed_roots=("/Adult",))
            adapter.validate_target("movie")
            accepted = bool(adapter.offline_task(candidate.info_hash)) or \
                adapter.submit_magnet(candidate.link, "movie")
            return {"status": "submitted" if accepted else "pending",
                    "route": "public_bt",
                    "download_hash": candidate.info_hash}
        raise ValueError("未知 Adult 洗版下载路由")


class AdultCollectionService:
    def __init__(self, store, library, files, config, sources=None, downloader=None):
        self.store, self.library, self.files, self.config = store, library, files, config
        self.sources = sources or AdultSourceSearch(config)
        self.downloader = downloader

    def _state(self):
        state = self.store.read() or {}
        state.setdefault("jobs", {})
        return state

    def _write(self, state):
        self.store.write(state)

    def _record(self, state, unit, **values):
        record = state["jobs"].setdefault(unit.key, {
            "id": uuid4().hex, "unit_key": unit.key, "title": unit.title})
        record.update(values)
        self._write(state)
        return record

    def _asset(self, unit):
        paths = [row.get("path") for row in unit.items if row.get("path")]
        if len(paths) != 1:
            raise ValueError("Adult 收藏项当前只支持单视频文件")
        assets = self.files.capture(paths)
        videos = [asset for asset in assets
                  if Path(asset.path).suffix.casefold() in {".mkv", ".mp4"}]
        if len(videos) != 1:
            raise ValueError("Adult 收藏项没有唯一可核实的视频文件")
        return videos[0]

    def _move(self, state, unit, asset, target, kind):
        if str(Path(asset.path)) == str(Path(target)):
            return self._record(state, unit, kind=kind, status="COLLECTED",
                                path=asset.path, target=target)
        if self.downloader is None or not self.downloader.deletion_allowed([asset]):
            return self._record(
                state, unit, kind=kind, status="WAIT_REFERENCE",
                path=asset.path, target=target,
                reason="文件仍被下载器/硬链接引用，禁止迁移以免破坏保种")

        user_states = self.library.capture_movie_states(
            unit, self.config.get("users") or [])
        self._record(
            state, unit, kind=kind, status="MOVING",
            path=asset.path, source_path=asset.path, target=target,
            user_states=user_states)
        moved = self.files.relocate(asset, target)
        self._record(
            state, unit, kind=kind, status="MIGRATION_PENDING",
            path=moved.path, source_path=asset.path, target=target,
            user_states=user_states)
        try:
            receipts = self.library.restore_relocated_movie(
                moved.path, user_states,
                timeout=int(self.config.get("emby_migration_timeout", 120)))
        except Exception as exc:
            return self._record(
                state, unit, kind=kind, status="MIGRATION_PENDING",
                path=moved.path, source_path=asset.path, target=target,
                user_states=user_states,
                reason=f"文件已安全迁移，等待 Emby 状态恢复：{type(exc).__name__}")
        return self._record(
            state, unit, kind=kind, status="COLLECTED",
            path=moved.path, source_path=asset.path, target=target,
            user_states=user_states, migration_receipts=receipts,
            reason="文件迁移完成，收藏/已看状态已回读确认")

    def _recover_relocations(self, state):
        recovered = []
        for record in state["jobs"].values():
            if record.get("status") not in ("MOVING", "MIGRATION_PENDING"):
                continue
            source = Path(record.get("source_path") or "")
            target = Path(record.get("target") or "")
            if not target.is_absolute() or not target.exists() or source.exists():
                continue
            try:
                receipts = self.library.restore_relocated_movie(
                    str(target), record.get("user_states") or {},
                    timeout=int(self.config.get("emby_migration_timeout", 120)))
            except Exception as exc:
                record["status"] = "MIGRATION_PENDING"
                record["reason"] = (
                    "文件已迁移，Emby 状态恢复仍待完成：" + type(exc).__name__)
                self._write(state)
                recovered.append(record)
                continue
            record.update(
                status="COLLECTED", path=str(target),
                migration_receipts=receipts,
                reason="恢复完成，收藏/已看状态已回读确认")
            self._write(state)
            recovered.append(record)
        return recovered

    def _vixen(self, state, unit, asset, probe):
        root = self.config.get("western_root", "/Adult/Western")
        target = collection_path(asset.path, root)
        if not is_4k(probe, Path(asset.path).name):
            return self._record(state, unit, kind="vixen", status="SKIP",
                                path=asset.path, reason="收藏项不是 4K")
        if asset.path == target:
            return self._record(state, unit, kind="vixen", status="COLLECTED",
                                path=asset.path, target=target)
        if self.config.get("dry_run", True):
            return self._record(state, unit, kind="vixen", status="WOULD_COLLECT",
                                path=asset.path, target=target,
                                reason="4K + liked，满足 Vixen 收藏规则")
        return self._move(state, unit, asset, target, "vixen")

    def _jav(self, state, unit, asset, probe):
        code = normalize_jav_number(" ".join((unit.title, Path(asset.path).name)))
        current = facts_from_library(Path(asset.path).name, asset.size, probe)
        searched = self.sources.search(code)

        for source in ("mteam", "javdb"):
            if searched[source]["status"] != "OK":
                return self._record(
                    state, unit, kind="jav", status="WAIT_SOURCE",
                    path=asset.path, code=code, current=current.dump(),
                    sources={key: {"status": value["status"], "reason": value["reason"]}
                             for key, value in searched.items()},
                    reason="M-Team 与 JavDB 都需要至少一个已核实候选，暂不归档")

        per_source = {}
        all_candidates = []
        for source in ("mteam", "javdb"):
            candidates = searched[source]["candidates"]
            all_candidates.extend(candidates)
            per_source[source] = decide_upgrade(
                current, candidates, strategy="resolution_size",
                near_size_ratio=float(self.config.get("near_size_ratio", 0.10)))

        combined = decide_upgrade(
            current, all_candidates, strategy="resolution_size",
            near_size_ratio=float(self.config.get("near_size_ratio", 0.10)))

        if any(decision.upgrade for decision in per_source.values()):
            values = {
                "kind": "jav", "status": "NEEDS_UPGRADE", "path": asset.path,
                "code": code, "current": current.dump(),
                "decision": combined.dump(),
                "sources": {key: value.dump() for key, value in per_source.items()},
            }
            record = self._record(state, unit, **values)
            if self.config.get("auto_upgrade", False):
                candidate = next((item for item in all_candidates
                                  if item.candidate_id == combined.candidate_id), None)
                if candidate:
                    receipt = self.sources.submit(candidate)
                    record = self._record(
                        state, unit, **values,
                        status="UPGRADE_SUBMITTED" if receipt.get("status") == "submitted"
                        else "UPGRADE_PENDING",
                        receipt=receipt)
            return record

        root = self.config.get("jav_root", "/Adult/JAV")
        target = collection_path(asset.path, root)
        if asset.path == target:
            return self._record(state, unit, kind="jav", status="COLLECTED",
                                path=asset.path, target=target, code=code,
                                sources={key: value.dump() for key, value in per_source.items()})
        if self.config.get("dry_run", True):
            return self._record(state, unit, kind="jav", status="WOULD_COLLECT",
                                path=asset.path, target=target, code=code,
                                reason="M-Team 与 JavDB 均未发现明显更优版本",
                                sources={key: value.dump() for key, value in per_source.items()})
        return self._move(state, unit, asset, target, "jav")

    def run(self, unit_keys=None):
        state = self._state()
        result = self._recover_relocations(state)
        units = self.library.discover(
            self.config.get("users") or [], unit_keys=unit_keys,
            resolve_episodes=False)
        for unit in units:
            if unit.kind != "movie" or not unit.items:
                continue
            try:
                asset = self._asset(unit)
                row = unit.items[0]
                kind = classify_adult(
                    unit.title, asset.path, row.get("studios") or (),
                    jav_root=self.config.get("jav_root", "/Adult/JAV"),
                    western_root=self.config.get("western_root", "/Adult/Western"),
                    vixen_markers=tuple(self.config.get("vixen_markers") or ["vixen"]))
                if not kind:
                    continue
                probe = self.files.inspect_media(asset.path)
                record = self._vixen(state, unit, asset, probe) if kind == "vixen" \
                    else self._jav(state, unit, asset, probe)
            except Exception as exc:
                record = self._record(state, unit, status="ERROR",
                                      reason=f"{type(exc).__name__}: {exc}")
            result.append(record)
        return result
