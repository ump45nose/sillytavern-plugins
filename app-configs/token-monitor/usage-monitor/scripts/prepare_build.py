#!/usr/bin/env python3
"""校验已构建的三个 wheel，准备仓库外离线构建目录；不构建或启动镜像。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_changes(baseline, revision):
    """Compare the original package tree with its current monorepo location."""
    prefix = command("git", "rev-parse", "--show-prefix")
    paths = ("src/usage_monitor_mcp", "pyproject.toml", "uv.lock")
    old_prefix = next(candidate for candidate in (prefix, "apps/usage-monitor/", "")
                      if subprocess.run(
                          ["git", "cat-file", "-e", baseline + ":" + candidate + "pyproject.toml"],
                          cwd=ROOT, capture_output=True,
                      ).returncode == 0)
    return [path for path in paths if command(
        "git", "rev-parse", baseline + ":" + old_prefix + path
    ) != command("git", "rev-parse", revision + ":" + prefix + path)]


def verify_wheel(path, name, record):
    path = path.resolve(strict=True)
    require(path.suffix == ".whl", "必须提供 wheel 文件")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require(digest == record["sha256"], name + " wheel SHA256 与已审定记录不符")
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        require(len(names) == 1, name + " wheel metadata 数量无效")
        metadata = BytesParser().parsebytes(archive.read(names[0]))
    actual_name = re.sub(r"[-_.]+", "-", metadata["Name"]).lower()
    require(actual_name == name and metadata["Version"] == record["version"], name + " wheel 名称或版本不符")
    require(not any(" @ " in v for v in metadata.get_all("Requires-Dist", [])),
            name + " wheel 含直接 URL 依赖，不能用于此离线流程")
    return {**record, "filename": path.name, "path": str(path), "sha256": digest}


def prepare(args):
    require(not command("git", "status", "--porcelain", "--untracked-files=normal"),
            "业务仓库必须干净；先审核并提交本次发布内容")
    revision = command("git", "rev-parse", "HEAD")
    locks = json.loads((ROOT / "deployment/wheels.lock.json").read_text())
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked_packages = {p["name"]: p for p in uv_lock["package"]}
    for name in ("mcp-platform", "dingtalk-events"):
        spec = locks["wheels"][name]
        locked = locked_packages[name]
        source = urlsplit(locked["source"]["git"])
        require(locked["version"] == spec["version"] and source.fragment == spec["source_commit"],
                name + " wheel 来源与 uv.lock 不符")
        require(source._replace(query="", fragment="").geturl() == spec["repository"],
                name + " wheel 仓库来源不符")
        require(parse_qs(source.query).get("subdirectory", [""])[0] == spec.get("subdirectory", ""),
                name + " wheel 子目录来源不符")
    own = locks["wheels"]["usage-monitor-mcp"]
    own_project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    require(own_project["version"] == own["version"], "业务 wheel 版本过期")
    # 发布流程与文档可在旧 wheel 后更新；Python 源码或依赖改变必须重建 wheel。
    changed = source_changes(own["source_commit"], revision)
    require(not changed, "业务 wheel 之后源码或依赖已改变；请重建并更新 wheel 记录")
    paths = {"mcp-platform": args.platform_wheel, "dingtalk-events": args.dingtalk_wheel,
             "usage-monitor-mcp": args.usage_wheel}
    wheels = {name: verify_wheel(path, name, locks["wheels"][name]) for name, path in paths.items()}
    base = locks["base_image"]
    require(command("docker", "image", "inspect", "--format", "{{.Id}}", base["tag"]) == base["id"],
            "本地基础镜像 ID 与已核验记录不符")
    require(args.build_dir.is_absolute(), "build-dir 必须是绝对路径")
    destination = args.build_dir.resolve()
    require(not destination.exists(), "build-dir 已存在；不会覆盖既有构建")
    require(not destination.is_relative_to(ROOT), "build-dir 必须位于仓库之外")
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9._/:+-]*", args.image_tag)), "镜像 tag 格式无效")
    tracked = command("git", "ls-files", "-z").split("\0")
    allowed = {"Dockerfile", "pyproject.toml", "uv.lock", "README.md", "deployment/wheels.lock.json"}
    files = [p for p in tracked if p and (p in allowed or p.startswith("src/"))]
    for name in files:
        require(not (ROOT / name).is_symlink(), "构建源码不得包含符号链接")
    record = {
        "schema_version": 1, "source_repository": own["repository"], "source_commit": revision,
        "source_subdirectory": command("git", "rev-parse", "--show-prefix").rstrip("/"),
        "source_clean": True, "base_image": base, "image_tag": args.image_tag,
        "build_directory": str(destination), "wheels": wheels,
        "source_files": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files},
        "build_command": ["docker", "build", "--pull=false", "--network=none", "--build-arg",
                          "MCP_RUNTIME_IMAGE=" + base["tag"], "--tag", args.image_tag, str(destination)],
    }
    if not args.check_only:
        destination.mkdir(parents=True, mode=0o700)
        (destination / "wheels").mkdir(mode=0o700)
        for name in files:
            target = destination / name
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        for item in wheels.values():
            shutil.copyfile(item["path"], destination / "wheels" / item["filename"])
        (destination / "build-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "validated" if args.check_only else "prepared", **record}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--platform-wheel", type=Path, required=True)
    parser.add_argument("--dingtalk-wheel", type=Path, required=True)
    parser.add_argument("--usage-wheel", type=Path, required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--check-only", action="store_true")
    try:
        prepare(parser.parse_args())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        parser.exit(1, "准备构建失败：" + str(error) + "\n")


if __name__ == "__main__":
    main()
