"""安装统一 Mac 应用、迁移既有采集任务并注册登录启动。"""
from pathlib import Path
import argparse
import shutil
import subprocess

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--viewer-only", action="store_true", help="update the viewer using installed resources; preserve collectors and login registration")
parser.add_argument("--destination", type=Path)
args = parser.parse_args()
destination = args.destination or (Path("/Applications/Personal Data Hub.app") if args.viewer_only and Path("/Applications/Personal Data Hub.app").exists() else Path.home() / "Applications/Personal Data Hub.app")
destination = destination.expanduser().resolve()
build = ["bash", str(root / "build.sh")]
if args.viewer_only: build += ["--viewer-only", str(destination)]
subprocess.run(build, check=True)
source = root / "dist/Personal Data Hub.app"
destination.parent.mkdir(exist_ok=True)
# 运行中的旧版本先正常退出，只影响查看端。
if destination.exists():
    subprocess.run([str(source / "Contents/MacOS/PersonalDataHub"), "--prepare-update", str(destination)], check=True)
backup = destination.with_name("Personal Data Hub.previous.app")
if destination.exists():
    if backup.exists(): shutil.rmtree(backup)
    destination.rename(backup)
try:
    shutil.copytree(source, destination)
    subprocess.run(["codesign", "--verify", "--strict", str(destination)], check=True)
    executable = destination / "Contents/MacOS/PersonalDataHub"
    if not args.viewer_only:
        login = subprocess.run([str(executable), "--enable-login"])
        if login.returncode not in (0, 2):
            raise RuntimeError("login_item_registration_failed")
        # Complete registration before changing live agents. The agent installer
        # restores its own state on failure; no fallible app setup follows migration.
        collection = subprocess.run([str(executable), "--install-agents"])
        if collection.returncode not in (0, 2):
            raise RuntimeError("collection_install_failed")
    # First installation can finish before the user grants the client's access.
    # The app guides authorization and retries; existing jobs stay loaded meanwhile.
except BaseException:
    if destination.exists(): shutil.rmtree(destination)
    if backup.exists(): backup.rename(destination)
    raise
launch = ["open", str(destination), "--args", "--show"]
if args.viewer_only: launch.append("--viewer-only")
subprocess.run(launch, check=True)
archive = root / "dist/Personal Data Hub.zip"
subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(source), str(archive)], check=True)
print(f"App installed: {destination}; packaged archive: {archive}")
