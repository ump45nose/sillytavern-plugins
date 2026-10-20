"""在 Mac 的单仓库检出中安装 Agent，保留原 launchd 身份与私有运行文件。"""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import time

repo = Path(__file__).resolve().parents[2]
home = Path.home()
support = home / "Library/Application Support/PersonalReview"
agents = home / "Library/LaunchAgents"
skysight = repo / "agents/mac/skysight"
backup = support / "backups/personal-data-hub-migration"
backup.mkdir(parents=True, exist_ok=True)
for name in ["run-skysight.py", "sync-skysight.mjs"]:
    old = support / name
    if old.exists() and not (backup / name).exists(): shutil.copy2(old, backup / name)
    shutil.copy2(skysight / name, old)
    old.chmod(0o700)
uid = str(os.getuid())
managed_python = repo / "apps/crm/.venv/bin/python"
if not managed_python.exists():
    raise RuntimeError("先安装 apps/crm 的 Python 环境")
subprocess.run([shutil.which("uv") or "uv", "pip", "install", "--python", str(managed_python),
                "-r", str(repo / "agents/mac/wechat-media-requirements.txt")], check=True)
for name in ["com.yuwk.personal-review-skysight", "com.personal-crm.wechat"]:
    path = agents / (name + ".plist")
    if not (backup / path.name).exists(): shutil.copy2(path, backup / path.name)
    data = plistlib.loads(path.read_bytes())
    target = "gui/" + uid + "/" + name
    previous_plist = path.read_bytes()
    subprocess.run(["launchctl", "bootout", target], check=False, capture_output=True)
    for attempt in range(25):
        if subprocess.run(["launchctl", "print", target], capture_output=True).returncode: break
        time.sleep(0.2)
    if "skysight" in name:
        data["StartInterval"] = 900
        data.pop("StartCalendarInterval", None)
    else:
        previous = Path(data["ProgramArguments"][0])
        managed_python = repo / "apps/crm/.venv/bin/python"
        python = managed_python if managed_python.exists() else previous.parent / "python"
        data["ProgramArguments"] = [str(python), "-c", "from personal_crm.connector.cli import main; main()", "--watch"]
        data["WorkingDirectory"] = str(repo / "apps/crm")
        data.setdefault("EnvironmentVariables", {})["PYTHONPATH"] = str(repo / "apps/crm/src")
        data["EnvironmentVariables"]["WECHAT_FACT_EXTRACTION"] = "false"
        data["EnvironmentVariables"].setdefault("CHATLOG_SCOPE_MODE", "all")
        data["EnvironmentVariables"]["WECHAT_MEDIA_ENABLED"] = "true"
        data["EnvironmentVariables"].setdefault("WECHAT_MEDIA_QUEUE", str(home / "Library/Application Support/personal-crm/wechat/media-queue.json"))
        # 旧凭据迁出旧仓库；checkpoint/client-id/白名单继续用原路径。
        old_env = Path(data["EnvironmentVariables"]["CRM_ENV_FILE"])
        new_env = home / "Library/Application Support/personal-crm/connector.env"
        if not new_env.exists(): shutil.copy2(old_env, new_env); new_env.chmod(0o600)
        data["EnvironmentVariables"]["CRM_ENV_FILE"] = str(new_env)
    path.write_bytes(plistlib.dumps(data))
    path.chmod(0o600)
    for attempt in range(5):
        loaded = subprocess.run(["launchctl", "bootstrap", "gui/" + uid, str(path)], capture_output=True)
        if loaded.returncode == 0: break
        time.sleep(0.5)
    if loaded.returncode:
        path.write_bytes(previous_plist)
        subprocess.run(["launchctl", "bootstrap", "gui/" + uid, str(path)], check=False, capture_output=True)
        raise RuntimeError("agent_bootstrap_failed:" + name)
receipt = {"repository": str(repo), "files": {name: hashlib.sha256((support / name).read_bytes()).hexdigest() for name in ["run-skysight.py", "sync-skysight.mjs"]}, "checkpoint_preserved": True}
(support / "hub-deployment.json").write_text(json.dumps(receipt, indent=2))
print("Mac collection agents installed; existing identities and checkpoints preserved")
