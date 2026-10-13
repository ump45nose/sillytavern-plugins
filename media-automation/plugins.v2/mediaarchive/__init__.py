"""MoviePilot host entry. Business rules live in workflow.py."""
from copy import deepcopy

from fastapi import Depends, HTTPException
from app.plugins import _PluginBase
from app.db.user_oper import get_current_active_superuser_async
from app.core.config import settings


DEFAULTS = {
    "enabled": False, "dry_run": True, "cron": "0 3 * * *", "users": [],
    "emby_url": "", "emby_token_path": "/config/mediaarchive-emby.token",
    "source_roots": ["/Media"], "path_mappings": [], "downloader_path_mappings": [],
    "downloaders": [], "movie_path": "/Media/Movie", "tv_path": "/Media/TV_Show",
    "strm_root": "/Media/115_strm", "remux_output_dir": "/Media/Remux",
    "seed_rule": {"days": 30, "ratio": 1, "mode": "any"}, "site_rules": {},
    "high_ratio": 2, "high_days": 30, "backfill": False, "cleanup_enabled": False,
    "ffprobe": "ffprobe",
}


class MediaArchive(_PluginBase):
    plugin_name = "媒体收藏归档"
    plugin_desc = "按收藏与保种条件归档115，验证STRM和用户状态后清理本地"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "0.1.0"
    plugin_author = "yuwk"
    author_url = ""
    plugin_config_prefix = "mediaarchive_"
    plugin_order = 61
    auth_level = 1

    def init_plugin(self, config=None):
        self.stop_service()
        self.config = deepcopy(DEFAULTS)
        self.config.update({k: v for k, v in (config or {}).items() if k in DEFAULTS})
        self.application = self.worker = self.transport = None
        self.error = ""
        try:
            from media_capabilities.host import load_config, SingleWorker
            from media_capabilities.models import SeedRule
            from apscheduler.triggers.cron import CronTrigger
            self.config = load_config(DEFAULTS, config)
            SeedRule(**self.config["seed_rule"])
            CronTrigger.from_crontab(self.config["cron"], timezone=settings.TZ)
            if self.config["enabled"]:
                self._assemble()
                self.worker = SingleWorker()
        except Exception as exc:
            self.error = "请先在 MoviePilot 安装 media-capabilities wheel" if isinstance(exc, ModuleNotFoundError) \
                and (exc.name or "").startswith("media_capabilities") else \
                str(exc) if isinstance(exc, ValueError) else f"配置或公共能力依赖不可用：{type(exc).__name__}"

    def _assemble(self):
        from pathlib import Path
        from media_capabilities.emby import EmbyTransport, EmbyLibrary
        from media_capabilities.files import LocalFiles
        from media_capabilities.p115 import P115Gateway
        from media_capabilities.strm import P115StrmPublisher
        from media_capabilities.moviepilot import MoviePilotDownloader, MoviePilotRemux, expected_episodes
        from media_capabilities.store import PluginTaskStore
        from .workflow import ArchiveService
        if not self.config["emby_url"] or not self.config["users"]:
            raise ValueError("请配置 Emby 和收藏用户")
        token = Path(self.config["emby_token_path"]).read_text().strip()
        if not token:
            raise ValueError("Emby token 文件为空")
        self.transport = EmbyTransport(self.config["emby_url"], token)
        library = EmbyLibrary(self.transport, expected_episodes, self.config["path_mappings"])
        files = LocalFiles(self.config["source_roots"],
                           [self.config["strm_root"], self.config["remux_output_dir"]], self.config["ffprobe"])
        downloader_options = {**self.config, "path_mappings": self.config["downloader_path_mappings"]}
        downloader = MoviePilotDownloader(files, downloader_options)
        cloud = P115Gateway()
        self.application = ArchiveService(PluginTaskStore(self), library, downloader, files, cloud,
                                           P115StrmPublisher(cloud, files, self.config["strm_root"]),
                                           MoviePilotRemux(), self.config)

    def get_state(self):
        return bool(self.config.get("enabled"))

    def get_service(self):
        if not self.get_state() or not self.application:
            return []
        from apscheduler.triggers.cron import CronTrigger
        return [{"id": "MediaArchiveDaily", "name": "媒体收藏归档",
                 "trigger": CronTrigger.from_crontab(self.config["cron"], timezone=settings.TZ),
                 "func": self.run_once, "kwargs": {}}]

    def run_once(self, backfill=False, unit_keys=None):
        if not self.application or not self.worker:
            raise RuntimeError(self.error or "插件未启用")
        application, transport = self.application, self.transport
        def task():
            try:
                return application.run(backfill=backfill, unit_keys=unit_keys)
            finally:
                if application.stopped.is_set():
                    transport.close()
        return self.worker.submit("archive", task)

    def get_api(self):
        return [{"path": path, "endpoint": endpoint, "methods": methods, "auth": "bear"}
                for path, endpoint, methods in [
                    ("/settings", self.settings_get, ["GET"]),
                    ("/settings", self.settings_post, ["POST"]),
                    ("/users", self.users_get, ["GET"]),
                    ("/candidates", self.candidates_get, ["GET"]),
                    ("/jobs", self.jobs_get, ["GET"]),
                    ("/run", self.run_post, ["POST"]),
                    ("/retry_upload", self.retry_upload_post, ["POST"])]]

    def settings_get(self, admin=Depends(get_current_active_superuser_async)):
        return {"config": self.config, "error": self.error}

    def settings_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        if self.worker and self.worker.busy():
            raise HTTPException(409, "任务运行中，请完成后修改配置")
        try:
            from media_capabilities.host import load_config
            from media_capabilities.models import SeedRule
            from apscheduler.triggers.cron import CronTrigger
            config = load_config(DEFAULTS, {**self.config, **body})
            SeedRule(**config["seed_rule"])
            CronTrigger.from_crontab(config["cron"], timezone=settings.TZ)
            self.update_config(config)
            self.init_plugin(config)
            # Host scheduler is rebuilt on ordinary plugin configuration updates.
            from app.scheduler import Scheduler
            Scheduler().update_plugin_job("MediaArchive")
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, "配置格式错误") from exc
        return self.settings_get(admin)

    def users_get(self, admin=Depends(get_current_active_superuser_async)):
        try:
            from pathlib import Path
            from media_capabilities.emby import EmbyTransport
            with_client = EmbyTransport(self.config["emby_url"], Path(self.config["emby_token_path"]).read_text().strip())
            try:
                rows = with_client.get("/Users")
                return {"users": [{"id": str(r["Id"]), "name": r["Name"]} for r in rows]}
            finally:
                with_client.close()
        except Exception as exc:
            raise HTTPException(503, f"Emby 用户查询失败：{type(exc).__name__}") from exc

    def candidates_get(self, admin=Depends(get_current_active_superuser_async)):
        if not self.application:
            raise HTTPException(503, self.error or "插件未启用")
        try:
            return {"units": [u.dump() for u in self.application.library.discover(self.config["users"], resolve_episodes=False)]}
        except Exception as exc:
            raise HTTPException(503, f"收藏查询失败：{type(exc).__name__}") from exc

    def jobs_get(self, admin=Depends(get_current_active_superuser_async)):
        state = self.get_data("workflow_v1") or {}
        public = deepcopy(state)
        for job in public.get("jobs", {}).values():
            job.pop("user_states", None)
        return {**public, "error": self.error,
                "busy": bool(self.worker and self.worker.busy())}

    def run_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        try:
            unit_keys = body.get("unit_keys")
            if unit_keys is not None and (not isinstance(unit_keys, list) or not unit_keys or
                                          any(not isinstance(k, str) for k in unit_keys)):
                raise HTTPException(400, "请选择收藏作品")
            return {"queued": self.run_once(backfill=bool(body.get("backfill", False)), unit_keys=unit_keys)}
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    def retry_upload_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        if not self.application or self.worker.busy():
            raise HTTPException(409, "插件不可用或任务运行中")
        try:
            self.application.retry_upload(body["job_id"])
            return {"queued": self.run_once()}
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, "无法重试，请确认任务和云端对账状态") from exc

    @staticmethod
    def get_render_mode():
        return "vue", "dist"

    def get_form(self):
        return None, deepcopy(DEFAULTS)

    def get_page(self):
        return None

    def get_command(self):
        return []

    def get_sidebar_nav(self):
        return [{"title": "媒体收藏归档", "icon": "mdi-cloud-upload", "nav_key": "main",
                 "section": "organize", "permission": "manage"}]

    def stop_service(self):
        if getattr(self, "application", None):
            self.application.stop()
        if getattr(self, "worker", None):
            self.worker.stop()
        if getattr(self, "transport", None) and not (getattr(self, "worker", None) and self.worker.busy()):
            self.transport.close()
