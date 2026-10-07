"""安装统一 Mac 应用、迁移既有采集任务并注册登录启动。"""
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parent
subprocess.run(["bash", str(root / "build.sh")], check=True)
source = root / "dist/Personal Data Hub.app"
destination = Path.home() / "Applications/Personal Data Hub.app"
destination.parent.mkdir(exist_ok=True)
# 运行中的旧版本先正常退出，只影响查看端。
if destination.exists():
    subprocess.run(["osascript", "-e", 'tell application id "com.yuwk.personal-data-hub" to quit'],
                   capture_output=True, check=False)
backup = destination.with_name("Personal Data Hub.previous.app")
if destination.exists():
    if backup.exists(): shutil.rmtree(backup)
    destination.rename(backup)
try:
    shutil.copytree(source, destination)
    subprocess.run(["codesign", "--verify", "--strict", str(destination)], check=True)
    executable = destination / "Contents/MacOS/PersonalDataHub"
    login = subprocess.run([str(executable), "--enable-login"])
    if login.returncode not in (0, 2):
        raise RuntimeError("login_item_registration_failed")
    # Complete registration before changing live agents. The agent installer
    # restores its own state on failure; no fallible app setup follows migration.
    subprocess.run([str(executable), "--install-agents"], check=True)
except BaseException:
    if destination.exists(): shutil.rmtree(destination)
    if backup.exists(): backup.rename(destination)
    raise
subprocess.run(["open", str(destination), "--args", "--show"], check=True)
archive = root / "dist/Personal Data Hub.zip"
subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(source), str(archive)], check=True)
print(f"App installed: {destination}; packaged archive: {archive}")
