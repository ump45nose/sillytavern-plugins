"""Standalone disc application service; no media-library interaction."""
from copy import deepcopy
from threading import Event, RLock

from media_capabilities.models import FileAsset, stable_id
from media_capabilities.policies import select_titles


class RemuxService:
    def __init__(self, store, files, engine, downloader, options):
        self.store, self.files, self.engine, self.downloader = store, files, engine, downloader
        self.options = options
        self.lock = RLock()
        self.stopped = Event()

    def stop(self):
        self.stopped.set()

    def submit(self, request):
        with self.lock:
            if request.get("kind", "movie") not in {"movie", "tv"}:
                raise ValueError("媒体类型错误")
            source = request["source"]
            if not self.files.is_disc(source):
                raise ValueError("请选择 ISO 或 BDMV 原盘")
            self.files.validate_output(source, self.options["output_dir"])
            manifest = self.files.capture([source])
            key = stable_id([request.get("idempotency_key") or request,
                             self.options["output_dir"], [a.dump() for a in manifest]])
            state = self.store.read()
            jobs = state.setdefault("jobs", {})
            if key not in jobs:
                output_root = self.options["output_dir"]
                if not output_root:
                    raise ValueError("请配置 REMUX 产物保存目录")
                jobs[key] = {"id": key, "stage": "ANALYZING", "request": deepcopy(request),
                             "source": [a.dump() for a in manifest], "output_dir": output_root,
                             "delete_original": bool(request.get("delete_original",
                                                           self.options.get("delete_original", False))),
                             "reason": "", "progress": 0, "outputs": []}
                if request.get("owner") == "MediaArchive":
                    jobs[key]["delete_original"] = False
                self.store.write(state)
            return key

    def snapshot(self):
        with self.lock:
            return self.store.read()

    def status(self, job_id):
        with self.lock:
            return self.store.read()["jobs"][job_id]

    def _save(self, job):
        with self.lock:
            state = self.store.read()
            state.setdefault("jobs", {})[job["id"]] = deepcopy(job)
            self.store.write(state)

    def process(self, job_id):
        if self.stopped.is_set():
            return
        job = self.status(job_id)
        if job["stage"] in {"DONE", "MANUAL", "FAILED"}:
            return
        try:
            source = [FileAsset(**row) for row in job["source"]]
            if job["stage"] != "CLEANING":
                self.files.verify(source)
            if job["stage"] == "ANALYZING":
                job["titles"] = self.engine.inspect(job["request"]["source"])
                selection, reason = select_titles(job["titles"], job["request"].get("kind", "movie"),
                                                   job["request"].get("runtime_seconds"),
                                                   job["request"].get("episodes"))
                # A known single-episode ISO can use the unique feature directly.
                if not selection and job["request"].get("kind") == "tv" and \
                        len(job["request"].get("episodes", [])) == 1:
                    selection, reason = select_titles(job["titles"], "movie",
                                                       job["request"].get("runtime_seconds"))
                    for title in selection:
                        title["episode"] = job["request"]["episodes"][0]
                job.update(selection=selection, stage="CONVERTING" if selection else "MANUAL",
                           reason=reason)
                self._save(job)
            if job["stage"] == "CONVERTING":
                def progress(value):
                    job["progress"] = int(value)
                    self._save(job)
                outputs = self.engine.convert(job, progress)
                self.files.verify(source)
                job["prepared"] = outputs
                job["stage"] = "COMMITTING"
                self._save(job)
            if self.stopped.is_set():
                return
            if job["stage"] == "COMMITTING":
                job["outputs"] = self.files.commit_outputs(job, job["prepared"])
                job["stage"] = "CLEANING"
                self._save(job)
            if job["stage"] == "CLEANING":
                if self.stopped.is_set():
                    return
                self.files.verify([FileAsset(**row) for row in job["outputs"]])
                if job["delete_original"]:
                    if self.downloader.deletion_allowed(source):
                        self.files.remove(source)
                    else:
                        job["reason"] = "REMUX 已完成；原盘存在做种/共享引用或无法确认，已保留"
                job.update(stage="DONE", progress=100)
                self._save(job)
        except Exception as exc:
            job["resume_stage"] = job["stage"]
            job.update(stage="FAILED", reason=f"处理失败：{type(exc).__name__}")
            self._save(job)

    def choose(self, job_id, choices):
        with self.lock:
            job = self.status(job_id)
            if job["stage"] != "MANUAL":
                raise ValueError("当前任务不等待人工选择")
            known = {t["id"]: t for t in job["titles"]}
            selection = []
            for choice in choices:
                title = deepcopy(known[int(choice["id"])])
                title["episode"] = choice.get("episode")
                selection.append(title)
            if not selection or len({t["id"] for t in selection}) != len(selection):
                raise ValueError("请选择不重复的标题")
            if job["request"].get("kind", "movie") == "movie" and len(selection) != 1:
                raise ValueError("电影需要选择一个主片标题")
            if job["request"].get("kind") == "tv":
                actual = [t["episode"] for t in selection]
                expected = job["request"].get("episodes", [])
                if not actual or any(not isinstance(e, int) or e <= 0 for e in actual) or \
                        len(set(actual)) != len(actual) or (expected and set(actual) != set(expected)):
                    raise ValueError("请为全部目标集指定唯一集序")
            job.update(selection=selection, stage="CONVERTING", reason="", progress=0)
            self._save(job)

    def retry(self, job_id):
        with self.lock:
            job = self.status(job_id)
            if job["stage"] != "FAILED":
                raise ValueError("任务不是失败状态")
            job.update(stage=job.pop("resume_stage", "ANALYZING"), reason="")
            self._save(job)

    def restart(self, job_id):
        """Start an explicit new attempt without reusing prior conversion receipts."""
        with self.lock:
            job = self.status(job_id)
            if job["stage"] not in {"DONE", "FAILED"} or job["request"].get("owner") == "MediaArchive":
                raise ValueError("只有独立终止任务可以重新转换")
            self.files.verify([FileAsset(**row) for row in job["source"]])
            job.setdefault("attempts", []).append({k: deepcopy(job[k]) for k in
                ("stage", "reason", "outputs", "selection") if k in job} | {"attempt": job.get("attempt", 1)})
            job.update(attempt=job.get("attempt", 1) + 1, stage="ANALYZING", reason="", progress=0, outputs=[])
            for key in ("titles", "selection", "prepared", "resume_stage"):
                job.pop(key, None)
            self._save(job)
