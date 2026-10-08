"""Bounded local file operations and atomic, recoverable artifact publication."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .models import FileAsset


VIDEO_SUFFIXES = {".mkv", ".mp4", ".m2ts", ".ts", ".avi", ".mov"}


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def safe_name(value: str) -> str:
    return re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", value).strip(" .")[:150] or "Media"


class LocalFiles:
    def __init__(self, roots: list[str], output_roots: list[str] | None = None, ffprobe="ffprobe"):
        if not roots:
            raise ValueError("请配置允许读取的媒体目录")
        self.roots = [Path(p).resolve() for p in roots]
        self.output_roots = [Path(p).resolve() for p in (output_roots or roots)]
        self.ffprobe = ffprobe

    def checked(self, value: str | Path, *, output=False, allow_root=False) -> Path:
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("需要允许目录内的绝对路径")
        resolved = path.resolve()
        roots = self.output_roots if output else self.roots + self.output_roots
        if not any((allow_root or resolved != root) and resolved.is_relative_to(root) for root in roots):
            raise ValueError("路径超出配置目录或指向目录根")
        # Do not follow a symbolic link during destructive or preparation work.
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError("不处理符号链接")
        return resolved

    def is_disc(self, value):
        path = self.checked(value)
        return path.is_file() and path.suffix.lower() == ".iso" or path.is_dir() and (
            (path / "BDMV" / "index.bdmv").is_file() or
            path.name.upper() == "BDMV" and (path / "index.bdmv").is_file())

    def validate_output(self, source, directory):
        original = self.checked(source)
        # ISO files stay beside their source; MKVs stay beside BDMV in a disc folder.
        in_place = not directory
        target = directory or (original if original.is_dir() and original.name.upper() != "BDMV"
                               else original.parent)
        output = self.checked(target, output=True, allow_root=True)
        if original.is_dir() and output.is_relative_to(original) and not (in_place and output == original):
            raise ValueError("输出目录不允许位于所选原盘内")
        return str(output)

    def browse(self, directory: str) -> list[dict]:
        path = Path(directory).resolve()
        if path not in self.roots:
            path = self.checked(directory)
        if not path.is_dir():
            raise ValueError("请选择目录")
        result = []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
            if child.is_symlink():
                continue
            if child.is_dir() or child.suffix.lower() == ".iso":
                result.append({"path": str(child), "name": child.name,
                               "directory": child.is_dir(), "disc": self.is_disc(str(child))})
            if len(result) >= 500:
                break
        return result

    def asset(self, path: Path, *, relative="", episode=None):
        stat = path.stat()
        if not path.is_file() or (stat.st_size <= 0 and path.suffix.lower() in VIDEO_SUFFIXES | {".iso"}):
            raise ValueError("文件为空或不是普通文件")
        return FileAsset(str(path), stat.st_size, mtime_ns=stat.st_mtime_ns,
                         device=stat.st_dev, inode=stat.st_ino, relative=relative, episode=episode)

    def capture(self, paths):
        assets = {}
        for value in paths:
            path = self.checked(value)
            if path.is_dir():
                if not self.is_disc(value):
                    raise ValueError("只允许展开原盘目录")
                # Working receipts and sibling MKVs are not part of a Blu-ray disc.
                # Exclude them so repeat submissions and cleanup never claim outputs.
                children = sorted(child for child in path.rglob("*")
                                  if ".discremux" not in child.relative_to(path).parts
                                  and not (child.parent == path and child.suffix.lower() == ".mkv"))
                if len(children) > 10000:
                    raise ValueError("原盘目录超过文件数量限制")
                for child in children:
                    self.checked(child)
                    if child.is_file():
                        assets[str(child)] = self.asset(child, relative=str(child.relative_to(path)))
            else:
                assets[str(path)] = self.asset(path, relative=path.name)
        if not assets:
            raise ValueError("源文件清单为空")
        return list(assets.values())

    def verify(self, files):
        for asset in files:
            path = self.checked(asset.path)
            current = self.asset(path)
            if (current.size, current.mtime_ns, current.device, current.inode) != (
                    asset.size, asset.mtime_ns, asset.device, asset.inode):
                raise ValueError("文件身份或内容已变化")

    def describe(self, files):
        self.verify(files)
        for asset in files:
            asset.sha1 = sha1_file(Path(asset.path))
        self.verify(files)
        return files

    def inspect_media(self, path):
        result = subprocess.run([self.ffprobe, "-v", "error", "-show_format", "-show_streams",
                                 "-show_chapters", "-of", "json", path],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=90, check=True)
        if len(result.stdout) > 4 * 1024 * 1024:
            raise ValueError("媒体信息超过大小限制")
        info = json.loads(result.stdout)
        if not any(s.get("codec_type") == "video" for s in info.get("streams", [])) or \
                float(info.get("format", {}).get("duration", 0)) <= 0:
            raise ValueError("未检测到有效视频流或时长")
        return info

    def commit_outputs(self, job, outputs):
        root = self.checked(job["output_dir"], output=True, allow_root=True)
        request = job["request"]
        in_place = job.get("in_place", False)
        directory = root if in_place else root / (
            safe_name(request.get("title") or Path(request["source"]).stem) + "-" + job["id"][:10])
        if not in_place and job.get("attempt", 1) > 1:
            directory = directory.with_name(directory.name + f"-r{int(job['attempt'])}")
        self.checked(directory, output=True, allow_root=True)
        directory.mkdir(parents=True, exist_ok=True)
        result = []
        for row in outputs:
            asset = FileAsset(**row["asset"])
            source = self.checked(asset.path)
            self.verify([asset])
            name = safe_name(request.get("title") or Path(request["source"]).stem)
            if asset.episode is not None:
                name += f".S{int(request.get('season') or 1):02d}E{asset.episode:02d}"
            if in_place and job.get("attempt", 1) > 1:
                name += f"-{job['id'][:10]}-r{int(job['attempt'])}"
            target = self.checked(directory / (name + ".mkv"), output=True)
            # A hard link is an atomic no-overwrite commit on the output volume.
            try:
                os.link(source, target)
            except FileExistsError:
                if target.stat().st_size != asset.size or sha1_file(target) != asset.sha1:
                    raise FileExistsError("目标存在不同文件，禁止覆盖")
            committed = self.asset(target, relative=target.name, episode=asset.episode)
            committed.sha1 = asset.sha1
            result.append(committed.dump())
        # Validate the whole set before removing any staging link.
        self.verify([FileAsset(**r) for r in result])
        return result

    def remove(self, files):
        existing = [asset for asset in files if Path(asset.path).exists()]
        self.verify(existing)
        parents = set()
        for asset in existing:
            path = self.checked(asset.path)
            path.unlink()
            parents.update(path.parents)
        for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
            if parent in self.roots + self.output_roots or not any(
                    parent.is_relative_to(root) for root in self.roots + self.output_roots):
                continue
            try:
                parent.rmdir()
            except OSError:
                pass
