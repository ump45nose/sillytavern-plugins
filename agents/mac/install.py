"""在 Mac 的单仓库检出中安装 Agent，保留原 launchd 身份与私有运行文件。"""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import shutil
import subprocess

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
for name in ["com.yuwk.personal-review-skysight", "com.personal-crm.wechat"]:
    path = agents / (name + ".plist")
    if not (backup / path.name).exists(): shutil.copy2(path, backup / path.name)
    data = plistlib.loads(path.read_bytes())
    subprocess.run(["launchctl", "bootout", "gui/" + uid + "/" + name], check=False, capture_output=True)
    if "skysight" in name:
        data["StartInterval"] = 900
        data.pop("StartCalendarInterval", None)
    else:
        previous = Path(data["ProgramArguments"][0])
        python = previous.parent / "python"
        data["ProgramArguments"] = [str(python), "-c", "from personal_crm.connector.cli import main; main()", "--watch"]
        data["WorkingDirectory"] = str(repo / "apps/crm")
        data.setdefault("EnvironmentVariables", {})["PYTHONPATH"] = str(repo / "apps/crm/src")
        # 旧凭据迁出旧仓库；checkpoint/client-id/白名单继续用原路径。
        old_env = Path(data["EnvironmentVariables"]["CRM_ENV_FILE"])
        new_env = home / "Library/Application Support/personal-crm/connector.env"
        if not new_env.exists(): shutil.copy2(old_env, new_env); new_env.chmod(0o600)
        data["EnvironmentVariables"]["CRM_ENV_FILE"] = str(new_env)
    path.write_bytes(plistlib.dumps(data))
    subprocess.run(["launchctl", "bootstrap", "gui/" + uid, str(path)], check=True)
receipt = {"repository": str(repo), "files": {name: hashlib.sha256((support / name).read_bytes()).hexdigest() for name in ["run-skysight.py", "sync-skysight.mjs"]}, "checkpoint_preserved": True}
(support / "hub-deployment.json").write_text(json.dumps(receipt, indent=2))
print("Mac collection agents installed; existing identities and checkpoints preserved")
