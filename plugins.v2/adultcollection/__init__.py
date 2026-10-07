"""MoviePilot host entry for Adult favorites and JAV wash detection."""

from copy import deepcopy

from fastapi import Depends, HTTPException
from app.plugins import _PluginBase
from app.db.user_oper import get_current_active_superuser_async
from app.core.config import settings


DEFAULTS = {
    "enabled": False,
    "dry_run": True,
    "auto_upgrade": False,
    "public_route_enabled": False,
    "cron": "20 3 * * *",
    "users": [],
    "emby_url": "",
    "emby_token_path": "/config/adultcollection-emby.token",
    "source_roots": ["/Adult/JAV", "/Adult/Western"],
    "path_mappings": [],
    "downloader_path_mappings": [],
    "downloaders": [],
    "jav_root": "/Adult/JAV",
    "western_root": "/Adult/Western",
    "adult_strm_root": "/Adult/STRM",
    "vixen_markers": ["vixen"],
    "mteam_site_id": 0,
    "downloader": "",
    "javdb_binary": "javdb",
    "near_size_ratio": 0.10,
    "preflight_limit": 3,
    "javdb_limit": 12,
    "source_timeout": 30,
    "magnet_timeout": 25,
    "emby_migration_timeout": 120,
    "ffprobe": "ffprobe",
}


class AdultCollection(_PluginBase):
    plugin_name = "Adult 收藏与洗版"
    plugin_desc = "Vixen 4K 收藏归档，JAV 双源核验与洗版检测"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "0.1.0"
    plugin_author = "yuwk"
    author_url = ""
    plugin_config_prefix = "adultcollection_"
    plugin_order = 62
    auth_level = 1

    def init_plugin(self, config=None):
        self.stop_service()
        self.config = deepcopy(DEFAULTS)
        self.config.update({k: v for k, v in (config or {}).items() if k in DEFAULTS})
        self.application = self.worker = self.transport = None
        self.error = ""
        try:
            from media_capabilities.host import load_config, SingleWorker
            from apscheduler.triggers.cron import CronTrigger

            self.config = load_config(DEFAULTS, config)
            ratio = float(self.config["near_size_ratio"])
            if ratio < 0 or ratio > 0.5:
                raise ValueError("near_size_ratio 必须在 0 到 0.5 之间")
            if not self.config["jav_root"].startswith("/Adult/") or \
                    not self.config["western_root"].startswith("/Adult/"):
                raise ValueError("Adult 媒体目录必须位于 /Adult 下")
            CronTrigger.from_crontab(self.config["cron"], timezone=settings.TZ)
            if self.config["enabled"]:
                self._assemble()
                self.worker = SingleWorker()
        except Exception as exc:
            self.error = "请先安装 media-capabilities wheel" if isinstance(exc, ModuleNotFoundError) \
                and (exc.name or "").startswith("media_capabilities") else \
                str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else \
                f"AdultCollection 初始化失败：{type(exc).__name__}"

    def _assemble(self):
        from pathlib import Path
        from media_capabilities.emby import EmbyTransport, EmbyLibrary
        from media_capabilities.files import LocalFiles
        from media_capabilities.moviepilot import expected_episodes, MoviePilotDownloader
        from media_capabilities.store import PluginTaskStore
        from .workflow import AdultCollectionService

        if not self.config["emby_url"] or not self.config["users"]:
            raise ValueError("请配置 Emby 和收藏用户")
        token = Path(self.config["emby_token_path"]).read_text().strip()
        if not token:
            raise ValueError("Emby token 文件为空")
        self.transport = EmbyTransport(self.config["emby_url"], token)
        library = EmbyLibrary(self.transport, expected_episodes, self.config["path_mappings"])
        roots = list(dict.fromkeys([
            *self.config["source_roots"],
            self.config["jav_root"],
            self.config["western_root"],
        ]))
        files = LocalFiles(roots, roots, self.config["ffprobe"])
        downloader = MoviePilotDownloader(files, {
            "downloaders": self.config.get("downloaders") or [],
            "path_mappings": self.config.get("downloader_path_mappings") or [],
        })
        self.application = AdultCollectionService(
            PluginTaskStore(self), library, files, self.config,
            downloader=downloader)

    def get_state(self):
        return bool(self.config.get("enabled"))

    def get_service(self):
        if not self.get_state() or not self.application:
            return []
        from apscheduler.triggers.cron import CronTrigger
        return [{
            "id": "AdultCollectionDaily",
            "name": "Adult 收藏与洗版",
            "trigger": CronTrigger.from_crontab(self.config["cron"], timezone=settings.TZ),
            "func": self.run_once,
            "kwargs": {},
        }]

    def run_once(self, unit_keys=None):
        if not self.application or not self.worker:
            raise RuntimeError(self.error or "插件未启用")
        return self.worker.submit(
            "adult-collection",
            lambda: self.application.run(unit_keys=unit_keys))

    def get_api(self):
        return [
            {"path": "/settings", "endpoint": self.settings_get,
             "methods": ["GET"], "auth": "bear"},
            {"path": "/settings", "endpoint": self.settings_post,
             "methods": ["POST"], "auth": "bear"},
            {"path": "/users", "endpoint": self.users_get,
             "methods": ["GET"], "auth": "bear"},
            {"path": "/candidates", "endpoint": self.candidates_get,
             "methods": ["GET"], "auth": "bear"},
            {"path": "/jobs", "endpoint": self.jobs_get,
             "methods": ["GET"], "auth": "bear"},
            {"path": "/run", "endpoint": self.run_post,
             "methods": ["POST"], "auth": "bear"},
        ]

    def settings_get(self, admin=Depends(get_current_active_superuser_async)):
        safe = deepcopy(self.config)
        return {"config": safe, "error": self.error}

    def settings_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        if self.worker and self.worker.busy():
            raise HTTPException(409, "任务运行中，请完成后修改配置")
        try:
            from media_capabilities.host import load_config
            from apscheduler.triggers.cron import CronTrigger

            config = load_config(DEFAULTS, {**self.config, **body})
            ratio = float(config["near_size_ratio"])
            if ratio < 0 or ratio > 0.5:
                raise ValueError("near_size_ratio 必须在 0 到 0.5 之间")
            CronTrigger.from_crontab(config["cron"], timezone=settings.TZ)
            self.update_config(config)
            self.init_plugin(config)
            from app.scheduler import Scheduler
            Scheduler().update_plugin_job("AdultCollection")
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return self.settings_get(admin)

    def users_get(self, admin=Depends(get_current_active_superuser_async)):
        try:
            from pathlib import Path
            from media_capabilities.emby import EmbyTransport

            client = EmbyTransport(
                self.config["emby_url"],
                Path(self.config["emby_token_path"]).read_text().strip())
            try:
                rows = client.get("/Users")
                return {"users": [{"id": str(row["Id"]), "name": row["Name"]}
                                  for row in rows]}
            finally:
                client.close()
        except Exception as exc:
            raise HTTPException(
                503, f"Emby 用户查询失败：{type(exc).__name__}") from exc

    def candidates_get(self, admin=Depends(get_current_active_superuser_async)):
        if not self.application:
            raise HTTPException(503, self.error or "插件未启用")
        try:
            units = self.application.library.discover(
                self.config["users"], resolve_episodes=False)
            return {"units": [unit.dump() for unit in units]}
        except Exception as exc:
            raise HTTPException(
                503, f"收藏查询失败：{type(exc).__name__}") from exc

    def jobs_get(self, admin=Depends(get_current_active_superuser_async)):
        state = deepcopy(self.get_data("workflow_v1") or {})
        return {
            **state,
            "error": self.error,
            "busy": bool(self.worker and self.worker.busy()),
        }

    def run_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        unit_keys = body.get("unit_keys")
        if unit_keys is not None and (
                not isinstance(unit_keys, list)
                or any(not isinstance(key, str) for key in unit_keys)):
            raise HTTPException(400, "unit_keys 格式错误")
        try:
            return {"queued": self.run_once(unit_keys=unit_keys)}
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    def get_form(self):
        fields = [
            ("VSwitch", "enabled", "启用 Adult 收藏与洗版"),
            ("VSwitch", "dry_run", "仅检测，不迁移文件"),
            ("VSwitch", "auto_upgrade", "JAV 自动提交洗版任务"),
            ("VSwitch", "public_route_enabled", "允许 JavDB 公网磁力下载到 115"),
            ("VTextField", "cron", "扫描计划"),
            ("VTextField", "emby_url", "Emby 地址"),
            ("VTextField", "emby_token_path", "Emby token 文件"),
            ("VTextField", "jav_root", "JAV 媒体库目录"),
            ("VTextField", "western_root", "Western 媒体库目录"),
            ("VTextField", "adult_strm_root", "Adult STRM 目录"),
            ("VTextField", "mteam_site_id", "M-Team 站点 ID"),
            ("VTextField", "javdb_binary", "javdb-cli 路径"),
            ("VTextField", "near_size_ratio", "同档资源体积接近阈值"),
            ("VTextField", "emby_migration_timeout", "Emby 状态迁移等待秒数"),
        ]
        content = [{
            "component": "VRow",
            "content": [{
                "component": "VCol",
                "props": {"cols": 12, "md": 6},
                "content": [{
                    "component": component,
                    "props": {"model": key, "label": label},
                }],
            }],
        } for component, key, label in fields]
        return [{"component": "VForm", "content": content}], deepcopy(DEFAULTS)

    def get_page(self):
        text = self.error or (
            "默认 dry-run。Vixen 仅 4K+收藏迁移；JAV 需 M-Team 与 JavDB 双源核验。"
        )
        return [{"component": "VAlert", "props": {
            "type": "warning" if self.error else "info", "text": text}}]

    def get_command(self):
        return []

    def get_sidebar_nav(self):
        return []

    def stop_service(self):
        if getattr(self, "worker", None):
            self.worker.stop()
        if getattr(self, "transport", None) and not (
                getattr(self, "worker", None) and self.worker.busy()):
            self.transport.close()
