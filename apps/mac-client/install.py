"""构建并安装本地客户端，不重启、不复制或新增采集 Agent。"""
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
except BaseException:
    if destination.exists(): shutil.rmtree(destination)
    if backup.exists(): backup.rename(destination)
    raise
print(f"Client installed: {destination}; collection agents unchanged")
