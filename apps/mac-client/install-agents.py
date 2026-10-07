"""Install the app's collection payload using existing private device identities."""

import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import time

LABELS = ["com.personal-crm.wechat", "com.yuwk.personal-review-skysight"]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(arguments, check=True):
    result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError("collection_command_failed:" + Path(arguments[0]).name)
    return result


def stop_job(target, label):
    name = target + "/" + label
    if run(["/bin/launchctl", "print", name], False).returncode:
        return
    run(["/bin/launchctl", "bootout", name])
    for attempt in range(50):
        if run(["/bin/launchctl", "print", name], False).returncode:
            return
        time.sleep(0.2)
    raise RuntimeError("collection_stop_failed")


def safe_extract(archive, target):
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        seen = set()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.name in seen:
                raise RuntimeError("invalid_collection_archive")
            seen.add(member.name)
            if not (member.isfile() or member.isdir() or member.issym()):
                raise RuntimeError("invalid_collection_member")
            if member.issym():
                link = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
                if member.linkname.startswith("/") or link == ".." or link.startswith("../"):
                    raise RuntimeError("invalid_collection_link")
        # Hash and app signature were verified; links are confined to this payload.
        tar.extractall(target, members=members)


def background_preflight(target, environment, authorized_python, version):
    """Test the actual launchd responsibility chain before touching either live job."""
    code = (
        "import json,subprocess,sys;sys.path.insert(0,sys.argv[1]);"
        "from personal_crm.connector.config import ConnectorConfig;"
        "c=ConnectorConfig.from_env();"
        "r=subprocess.run([c.chatlog_executable,'directory','--source','wechat'],"
        "capture_output=True,text=True,timeout=c.timeout);"
        "d=json.loads(r.stdout);"
        "print(json.dumps({'readable':r.returncode==0 and d.get('available') is True}),flush=True)"
    )
    label = "com.yuwk.personal-data-hub-preflight." + str(os.getpid())
    with tempfile.TemporaryDirectory(prefix=".preflight-", dir=version.parent.parent) as temporary:
        folder = Path(temporary)
        output = folder / "result.json"
        config = {
            "Label": label, "RunAtLoad": True, "WorkingDirectory": str(version),
            "EnvironmentVariables": {**environment, "CHATLOG_EXECUTABLE": str(version / "bin/chatlog-keeper")},
            "ProgramArguments": [str(authorized_python), "-I", str(version / "launch-wechat.py"),
                                 str(version / "python/bin/python3.12"), "-I", "-c", code, str(version / "packages")],
            "StandardOutPath": str(output), "StandardErrorPath": str(folder / "error.log"),
        }
        path = folder / "preflight.plist"
        path.write_bytes(plistlib.dumps(config))
        path.chmod(0o600)
        try:
            run(["/bin/launchctl", "bootstrap", target, str(path)])
            for attempt in range(180):
                if output.exists():
                    try:
                        result = json.loads(output.read_text())
                    except ValueError:
                        result = None
                    if result is not None:
                        if result.get("readable") is True:
                            return
                        break
                time.sleep(1)
            raise RuntimeError("collection_background_read_preflight_failed")
        finally:
            stop_job(target, label)


def _install(app, status=False):
    home = Path.home()
    support = home / "Library/Application Support/PersonalDataHub"
    receipt_path = support / "Agents/current.json"
    resources = app / "Contents/Resources"
    manifest = json.loads((resources / "collection.json").read_text())
    target = "gui/" + str(os.getuid())
    loaded = {label: run(["/bin/launchctl", "print", target + "/" + label], False).returncode == 0 for label in LABELS}
    if status:
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        print(json.dumps({"packaged": True, "installed": receipt.get("archiveSHA256") == manifest["archiveSHA256"], "agents_loaded": loaded}))
        return
    run(["/usr/bin/codesign", "--verify", "--strict", str(app)])
    archive = resources / "collection.tar.gz"
    if manifest["schema"] != 1 or digest(archive) != manifest["archiveSHA256"]:
        raise RuntimeError("collection_payload_integrity_failed")
    # Updating code never creates replacement device credentials or resets cursors.
    agent_paths = {label: home / "Library/LaunchAgents" / (label + ".plist") for label in LABELS}
    if not all(path.is_file() for path in agent_paths.values()):
        raise RuntimeError("existing_collection_configuration_required")
    originals = {label: path.read_bytes() for label, path in agent_paths.items()}
    configs = {label: plistlib.loads(value) for label, value in originals.items()}
    wechat = configs[LABELS[0]]
    env = wechat.setdefault("EnvironmentVariables", {})
    activity = configs[LABELS[1]]
    args = activity.get("ProgramArguments", [])
    if not env.get("CRM_CHECKPOINT") or len(args) < 4:
        raise RuntimeError("existing_collection_configuration_unsupported")
    # Resolve private state relative to its old working directory before changing it.
    for name in ["CRM_CHECKPOINT", "CRM_ENV_FILE", "WECHAT_MEDIA_QUEUE"]:
        if env.get(name):
            path = Path(env[name]).expanduser()
            if not path.is_absolute():
                working = Path(wechat.get("WorkingDirectory", ""))
                if not working.is_absolute():
                    raise RuntimeError("existing_collection_configuration_unsupported")
                path = working / path
            env[name] = str(path)
    versions = support / "Agents/versions"
    versions.mkdir(parents=True, exist_ok=True, mode=0o700)
    version = versions / manifest["archiveSHA256"]
    current = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    # TCC is bound to the existing interpreter's identity/path. Its tiny wrapper
    # starts the bundled environment; neither executable depends on a repo path.
    authorized_python = Path(current.get("authorizedWechatPython") or wechat["ProgramArguments"][0]).resolve()
    if not authorized_python.is_file():
        raise RuntimeError("approved_collection_launcher_required")
    python = version / "python/bin/python3.12"
    wechat_arguments = [str(authorized_python), "-I", str(version / "launch-wechat.py"),
                        str(python), "-I", str(version / "run-wechat.py"), "--watch"]
    activity_arguments = list(args)
    activity_arguments[1] = str(version / "skysight/run-skysight.py")
    activity_arguments[3] = str(version / "skysight/sync-skysight.mjs")
    code_paths_match = (wechat["ProgramArguments"] == wechat_arguments and args == activity_arguments
                        and env.get("CHATLOG_EXECUTABLE") == str(version / "bin/chatlog-keeper")
                        and env.get("CHATLOG_EXPECTED_SHA256") == manifest["chatlogSHA256"])
    if current.get("archiveSHA256") == manifest["archiveSHA256"] and all(loaded.values()) and code_paths_match:
        print(json.dumps({"collection_installed": True, "unchanged": True, "agents": len(LABELS)}))
        return
    if not version.exists():
        staging = Path(tempfile.mkdtemp(prefix=".collection-", dir=versions))
        try:
            safe_extract(archive, staging)
            staging.rename(version)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    # Relocated interpreter and all imports must work before stopping a live job.
    check_code = "import sys;sys.path.insert(0,sys.argv[1]);import httpx,dotenv,numpy,PIL,Crypto,zstandard;from personal_crm.connector.cli import main;from chatlog_keeper import wechat_db;assert sys.version.startswith('3.12.')"
    run([str(python), "-I", "-c", check_code, str(version / "packages")])
    if digest(version / "bin/chatlog-keeper") != manifest["chatlogSHA256"]:
        raise RuntimeError("chatlog_checksum_mismatch")
    private_helper = support / "Personal Data Hub Credentials.app"
    helper_binary = "Contents/MacOS/PersonalDataHubCredentialReader"
    if not private_helper.is_dir() or digest(private_helper / helper_binary) != manifest["credentialReader"]["binarySHA256"]:
        raise RuntimeError("approved_credential_reader_required")
    background_preflight(target, env, authorized_python, version)
    # Preserve the approved helper byte for byte, including Keychain partition ACLs.
    backup = support / "backups" / ("collection-app-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(parents=True, mode=0o700)
    for label, value in originals.items():
        (backup / (label + ".plist")).write_bytes(value)
    old_receipt = receipt_path.read_bytes() if receipt_path.exists() else None
    checkpoints = {}
    try:
        for label in LABELS:
            if loaded[label]:
                stop_job(target, label)
        checkpoint = Path(env["CRM_CHECKPOINT"])
        paths = [checkpoint, home / "Library/Application Support/PersonalReview/skysight-checkpoint.json"]
        if env.get("WECHAT_MEDIA_QUEUE"):
            paths.append(Path(env["WECHAT_MEDIA_QUEUE"]).expanduser())
        for index, path in enumerate(paths):
            if path.exists():
                checkpoints[path] = path.read_bytes()
                (backup / ("checkpoint-" + str(index) + ".json")).write_bytes(checkpoints[path])
        env.pop("PYTHONPATH", None)
        env["CHATLOG_EXECUTABLE"] = str(version / "bin/chatlog-keeper")
        env["CHATLOG_EXPECTED_SHA256"] = manifest["chatlogSHA256"]
        wechat["ProgramArguments"] = wechat_arguments
        wechat["WorkingDirectory"] = str(version)
        # Keep the existing TCC-authorized Python and ChatGPT Node, change code only.
        args[1] = str(version / "skysight/run-skysight.py")
        args[3] = str(version / "skysight/sync-skysight.mjs")
        activity["WorkingDirectory"] = str(support)
        for label, config in configs.items():
            agent_paths[label].write_bytes(plistlib.dumps(config))
            agent_paths[label].chmod(0o600)
        if any(path.read_bytes() != value for path, value in checkpoints.items()):
            raise RuntimeError("collection_checkpoint_changed_during_install")
        for label in LABELS:
            run(["/bin/launchctl", "bootstrap", target, str(agent_paths[label])])
        receipt = {"archiveSHA256": manifest["archiveSHA256"], "runtime": str(version),
                   "app": str(app), "checkpoint_preserved": True, "backup": str(backup),
                   "authorizedWechatPython": str(authorized_python),
                   "credential_reader_preserved": True, "activity_authorized_runtimes_preserved": True}
        receipt_path.write_text(json.dumps(receipt, indent=2))
        receipt_path.chmod(0o600)
        print(json.dumps({"collection_installed": True, "checkpoint_preserved": True, "agents": len(LABELS)}))
    except BaseException:
        restored = True
        # bootout completion is asynchronous; wait before reusing the same label.
        for label in LABELS:
            try:
                stop_job(target, label)
            except Exception:
                restored = False
        for label in LABELS:
            try:
                agent_paths[label].write_bytes(originals[label])
                if loaded[label] and run(["/bin/launchctl", "bootstrap", target, str(agent_paths[label])], False).returncode:
                    restored = False
            except Exception:
                restored = False
        try:
            if old_receipt is not None:
                receipt_path.write_bytes(old_receipt)
            elif receipt_path.exists():
                receipt_path.unlink()
        except Exception:
            restored = False
        if not restored:
            raise RuntimeError("collection_rollback_incomplete")
        raise


def install(app, status=False):
    if status:
        return _install(app, True)
    folder = Path.home() / "Library/Application Support/PersonalDataHub/Agents"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / ".install.lock").open("a") as lock:
        Path(lock.name).chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _install(app)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        install(args.app.resolve(), args.status)
    except Exception as error:
        # Private configs and subprocess stderr must never enter UI/terminal logs.
        print("collection_install_failed:" + (str(error) if isinstance(error, RuntimeError) else type(error).__name__))
        raise SystemExit(1)
