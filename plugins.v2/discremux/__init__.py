"""Standalone MoviePilot disc-preparation UI and asynchronous job host."""
from copy import deepcopy

from fastapi import Depends, HTTPException
from app.plugins import _PluginBase
from app.db.user_oper import get_current_active_superuser_async


DEFAULTS = {"enabled": False, "source_roots": ["/Media"], "output_dir": "",
            "delete_original": False, "makemkvcon": "makemkvcon", "ffprobe": "ffprobe",
            "timeout_seconds": 21600, "downloaders": [], "path_mappings": []}


class DiscRemux(_PluginBase):
    plugin_name = "原盘REMUX"
    plugin_desc = "分析ISO/BDMV，自动或人工选片，输出无损MKV文件"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "0.1.1"
    plugin_author = "yuwk"
    author_url = ""
    plugin_config_prefix = "discremux_"
    plugin_order = 62
    auth_level = 1

    def init_plugin(self, config=None):
        self.stop_service()
        self.application = self.worker = self.engine = self.files = None
        self.config = deepcopy(DEFAULTS)
        self.config.update({k: v for k, v in (config or {}).items() if k in DEFAULTS})
        self.error = ""
        try:
            from media_capabilities.host import load_config, SingleWorker
            self.config = load_config(DEFAULTS, config)
            if self.config["enabled"]:
                from media_capabilities.files import LocalFiles
                from media_capabilities.makemkv import MakeMKVEngine
                from media_capabilities.moviepilot import MoviePilotDownloader
                from media_capabilities.store import PluginTaskStore
                from .workflow import RemuxService
                output_roots = [self.config["output_dir"]] if self.config["output_dir"] else self.config["source_roots"]
                self.files = LocalFiles(self.config["source_roots"], output_roots, self.config["ffprobe"])
                self.engine = MakeMKVEngine(self.files, self.config["makemkvcon"], int(self.config["timeout_seconds"]))
                self.application = RemuxService(PluginTaskStore(self), self.files, self.engine,
                                                 MoviePilotDownloader(self.files, self.config), self.config)
                self.worker = SingleWorker()
                for job in self.application.snapshot().get("jobs", {}).values():
                    if job["stage"] not in {"DONE", "MANUAL", "FAILED"}:
                        self.worker.submit(job["id"], self.application.process, job["id"])
        except Exception as exc:
            self.error = "请先在 MoviePilot 安装 media-capabilities wheel" if isinstance(exc, ModuleNotFoundError) \
                and (exc.name or "").startswith("media_capabilities") else \
                str(exc) if isinstance(exc, ValueError) else f"配置或公共能力依赖不可用：{type(exc).__name__}"

    def get_state(self):
        return bool(self.config.get("enabled"))

    def submit_request(self, request):
        if not self.application or not self.worker:
            raise RuntimeError(self.error or "REMUX 插件未启用")
        job_id = self.application.submit(request)
        self.worker.submit(job_id, self.application.process, job_id)
        return job_id

    def get_api(self):
        return [{"path": path, "endpoint": endpoint, "methods": methods, "auth": "bear"}
                for path, endpoint, methods in [
                    ("/settings", self.settings_get, ["GET"]),
                    ("/settings", self.settings_post, ["POST"]),
                    ("/browse", self.browse_get, ["GET"]),
                    ("/jobs", self.jobs_get, ["GET"]),
                    ("/jobs", self.jobs_post, ["POST"]),
                    ("/select", self.select_post, ["POST"]),
                    ("/retry", self.retry_post, ["POST"]),
                    ("/restart", self.restart_post, ["POST"])]]

    def settings_get(self, admin=Depends(get_current_active_superuser_async)):
        return {"config": self.config, "error": self.error}

    def settings_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        if self.worker and self.worker.busy():
            raise HTTPException(409, "任务运行中，请完成后修改配置")
        try:
            from media_capabilities.host import load_config
            config = load_config(DEFAULTS, {**self.config, **body})
            self.update_config(config)
            self.init_plugin(config)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "配置格式错误") from exc
        return self.settings_get(admin)

    def browse_get(self, directory: str = "", admin=Depends(get_current_active_superuser_async)):
        if not self.files:
            raise HTTPException(503, self.error or "请先启用并配置插件")
        try:
            return {"roots": self.config["source_roots"],
                    "items": self.files.browse(directory or self.config["source_roots"][0])}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, "目录不可读取或超出配置范围") from exc

    def jobs_get(self, admin=Depends(get_current_active_superuser_async)):
        return {**(self.application.snapshot() if self.application else self.get_data("workflow_v1") or {}),
                "error": self.error, "busy": bool(self.worker and self.worker.busy())}

    def jobs_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        request = {k: body[k] for k in ("source", "kind", "title", "season", "episodes", "runtime_seconds") if k in body}
        try:
            return {"job_id": self.submit_request(request)}
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, "原盘路径或任务参数错误") from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    def select_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        if not self.application:
            raise HTTPException(503, self.error or "插件未启用")
        try:
            self.application.choose(body["job_id"], body["choices"])
            self.worker.submit(body["job_id"], self.application.process, body["job_id"])
            return {"queued": True}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, "标题选择或集序不符合目标媒体") from exc

    def retry_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        if not self.application:
            raise HTTPException(503, self.error or "插件未启用")
        try:
            self.application.retry(body["job_id"])
            self.worker.submit(body["job_id"], self.application.process, body["job_id"])
            return {"queued": True}
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, "任务不可重试") from exc

    def restart_post(self, body: dict, admin=Depends(get_current_active_superuser_async)):
        if not self.application:
            raise HTTPException(503, self.error or "插件未启用")
        if self.worker.busy():
            raise HTTPException(409, "请等待当前任务结束")
        try:
            self.application.restart(body["job_id"])
            self.worker.submit(body["job_id"], self.application.process, body["job_id"])
            return {"queued": True}
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, "原盘已变化或任务不可重新转换") from exc

    @staticmethod
    def get_render_mode():
        return "vue", "dist"

    def get_form(self):
        return None, deepcopy(DEFAULTS)

    def get_page(self):
        return None

    def get_command(self):
        return []

    def get_service(self):
        return []

    def get_sidebar_nav(self):
        return [{"title": "原盘REMUX", "icon": "mdi-disc", "nav_key": "main",
                 "section": "organize", "permission": "manage"}]

    def stop_service(self):
        if getattr(self, "application", None):
            self.application.stop()
        if getattr(self, "engine", None):
            self.engine.stop()
        if getattr(self, "worker", None):
            self.worker.stop()
