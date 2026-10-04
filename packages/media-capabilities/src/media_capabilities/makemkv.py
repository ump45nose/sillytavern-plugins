"""MakeMKV CLI adapter. Lossless conversion, bounded output and owned processes."""
import csv
import json
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import subprocess
from threading import Event, Thread
import time

from .models import DiscTitle, FileAsset


class MakeMKVEngine:
    def __init__(self, files, binary="makemkvcon", timeout_seconds=21600):
        self.files, self.binary, self.timeout = files, binary, timeout_seconds
        self.cancelled = Event()

    def stop(self):
        self.cancelled.set()

    def _run(self, args, *, timeout, progress=None):
        if self.cancelled.is_set():
            raise RuntimeError("转换已停止")
        process = subprocess.Popen([self.binary, *args], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        messages = Queue(maxsize=128)
        def reader():
            try:
                while True:
                    line = process.stdout.readline(65537)
                    if not line:
                        break
                    messages.put(line)
            finally:
                messages.put(None)
        thread = Thread(target=reader, daemon=True)
        thread.start()
        output, total, deadline = [], 0, time.monotonic() + timeout
        try:
            while True:
                if self.cancelled.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError("MakeMKV 已停止或超时")
                try:
                    line = messages.get(timeout=.25)
                except Empty:
                    continue
                if line is None:
                    break
                total += len(line)
                if len(line) > 65536 or total > 16 * 1024 * 1024:
                    raise ValueError("MakeMKV 输出超过限制")
                text = line.decode("utf-8", errors="replace").strip()
                output.append(text)
                if progress and text.startswith("PRGV:"):
                    values = text[5:].split(",")
                    if len(values) == 3 and int(values[2]) > 0:
                        progress(int(values[1]) * 100 // int(values[2]))
            if process.wait(timeout=5) != 0:
                raise RuntimeError("MakeMKV 执行失败")
            return output
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            process.stdout.close()
            # Drain to release a reader blocked while the process was cancelled.
            while thread.is_alive():
                try:
                    messages.get(timeout=.1)
                except Empty:
                    pass
                thread.join(timeout=.1)

    def _source(self, source):
        path = self.files.checked(source)
        if path.suffix.lower() == ".iso":
            return "iso:" + str(path)
        index = path / "index.bdmv" if path.name.upper() == "BDMV" else path / "BDMV/index.bdmv"
        if not index.is_file():
            raise ValueError("缺少 BDMV index.bdmv")
        return "file:" + str(index)

    def inspect(self, source):
        lines = self._run(["--robot", "--noscan", "--cache=128", "--minlength=0",
                           "info", self._source(source)], timeout=600)
        titles = {}
        for line in lines:
            if line.startswith("TINFO:"):
                values = next(csv.reader([line[6:]], escapechar="\\"))
                title_id, attribute = int(values[0]), int(values[1])
                title = titles.setdefault(title_id, DiscTitle(title_id))
                value = values[3]
                if attribute == 9:
                    parts = [float(p) for p in value.split(":")]
                    title.duration = sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
                elif attribute in {8, 11}:
                    setattr(title, "chapters" if attribute == 8 else "size", int(value))
                elif attribute in {2, 16, 27}:
                    setattr(title, {2: "name", 16: "source_file", 27: "output_name"}[attribute], value)
                elif attribute == 26:
                    title.segments = value
            elif line.startswith("SINFO:"):
                values = next(csv.reader([line[6:]], escapechar="\\"))
                title_id, stream_id, attribute = map(int, values[:3])
                title = titles.setdefault(title_id, DiscTitle(title_id))
                stream = next((s for s in title.streams if s["id"] == stream_id), None)
                if stream is None:
                    stream = {"id": stream_id, "attributes": {}, "codes": {}}
                    title.streams.append(stream)
                stream["attributes"][str(attribute)] = values[4]
                stream["codes"][str(attribute)] = int(values[3])
        if not titles:
            raise ValueError("未能读取原盘标题")
        return [t.dump() for t in titles.values()]

    def convert(self, job, progress):
        root = Path(job["output_dir"]).resolve() / ".discremux" / job["id"]
        if job.get("attempt", 1) > 1:
            root /= f"attempt-{int(job['attempt'])}"
        self.files.checked(root, output=True)
        root.mkdir(parents=True, exist_ok=True)
        # Select every source stream; defaults may omit languages and HD audio.
        profile = root / "lossless.mmcp.xml"
        profile.write_text('<profile><name lang="eng">Lossless</name>'
                           '<outputSettings name="copy" outputFormat="directCopy" />'
                           '<trackSettings input="default"><output outputSettingsName="copy" '
                           'defaultSelection="+sel:all" /></trackSettings>'
                           '</profile>', encoding="utf-8")
        outputs = []
        for index, title in enumerate(job["selection"]):
            directory = root / str(title["id"])
            directory.mkdir(exist_ok=True)
            receipt = directory / "ready.json"
            if receipt.exists():
                row = json.loads(receipt.read_text())
                self.files.verify([FileAsset(**row["asset"])])
                outputs.append(row)
                continue
            converted = directory / "converted.json"
            if converted.exists():
                asset = FileAsset(**json.loads(converted.read_text()))
                self.files.verify([asset])
                found = [Path(asset.path)]
            else:
                # Unreceipted files are incomplete outputs owned by this task only.
                for existing in directory.iterdir():
                    if existing.is_file() and existing.suffix.lower() == ".mkv":
                        existing.unlink()
                self._run(["--robot", "--noscan", "--cache=512", "--minlength=0",
                           "--progress=-same", f"--profile={profile}", "mkv",
                           self._source(job["request"]["source"]), str(title["id"]), str(directory)],
                          timeout=self.timeout,
                          progress=lambda n: progress((index * 100 + n) // len(job["selection"])))
                found = list(directory.glob("*.mkv"))
                if len(found) != 1:
                    raise ValueError("转换产物数量不符合所选标题")
                temporary = converted.with_suffix(".tmp")
                temporary.write_text(json.dumps(self.files.asset(found[0]).dump()), encoding="utf-8")
                temporary.replace(converted)
            info = self.files.inspect_media(str(found[0]))
            duration = float(info["format"]["duration"])
            if abs(duration-title["duration"]) > max(2, title["duration"] * .005):
                raise ValueError("转换产物时长不匹配")
            for code, kind in ((6201, "video"), (6202, "audio"), (6203, "subtitle")):
                # MakeMKV also lists virtual "forced only" subtitle filters.
                # Empty derived filters may be dropped; their full source track
                # must still be present in the output.
                expected = sum(s.get("codes", {}).get("1") == code and not (
                    kind == "subtitle" and int(s.get("attributes", {}).get("22") or 0) & 6144 == 6144)
                    for s in title.get("streams", []))
                actual = sum(s.get("codec_type") == kind for s in info.get("streams", []))
                if actual < expected:
                    raise ValueError("转换产物缺少原盘媒体流")
            if len(info.get("chapters", [])) < int(title.get("chapters") or 0):
                raise ValueError("转换产物缺少章节")
            asset = self.files.describe([self.files.asset(found[0], episode=title.get("episode"))])[0]
            row = {"title_id": title["id"], "asset": asset.dump()}
            temporary = receipt.with_suffix(".tmp")
            temporary.write_text(json.dumps(row), encoding="utf-8")
            temporary.replace(receipt)
            outputs.append(row)
        return outputs
