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
from uuid import uuid4

LABELS = ["com.personal-crm.wechat", "com.yuwk.personal-review-skysight"]
NETWORK_LABEL = "com.yuwk.personal-data-hub-network"


def install_network(app, enabled=None):
    home = Path.home(); support = home / "Library/Application Support/PersonalDataHub"
    folder = support / "Network"; path = folder / "config.json"
    if enabled is None and not path.exists(): return
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = json.loads(path.read_text()) if path.exists() else {}
    config.setdefault("device_id", uuid4().hex)
    # Reuse this machine's existing NAS route, never bundle SSH credentials.
    activity = plistlib.loads((home / "Library/LaunchAgents" / (LABELS[1] + ".plist")).read_bytes())
    arguments = activity_parameters(activity["ProgramArguments"])
    host = arguments[arguments.index("--host") + 1] if "--host" in arguments else activity.get("EnvironmentVariables", {}).get("SKYSIGHT_SSH_HOST", "yuwk-201")
    config.setdefault("host", host); config.setdefault("timezone", "Asia/Shanghai")
    if enabled is not None: config["enabled"] = enabled
    temporary = path.with_suffix(".tmp"); temporary.write_text(json.dumps(config, indent=2)); temporary.chmod(0o600); temporary.replace(path)
    target = "gui/" + str(os.getuid())
    agent_path = home / "Library/LaunchAgents" / (NETWORK_LABEL + ".plist")
    launcher = app / "Contents/MacOS/PersonalDataHub"
    if not config.get("enabled"):
        stop_job(target, NETWORK_LABEL); return
    runtime_hash = json.loads((app / "Contents/Resources/collection.json").read_text())["archiveSHA256"]
    agent = {"Label": NETWORK_LABEL, "ProgramArguments": [str(launcher), "--collect-network"], "EnvironmentVariables": {"PDH_NETWORK_RUNTIME": runtime_hash},
             "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30,
             "WorkingDirectory": str(support), "StandardOutPath": str(folder / "agent.log"), "StandardErrorPath": str(folder / "agent-error.log")}
    loaded = run(["/bin/launchctl", "print", target + "/" + NETWORK_LABEL], False).returncode == 0
    old = plistlib.loads(agent_path.read_bytes()) if agent_path.exists() else None
    if loaded and old == agent: return
    stop_job(target, NETWORK_LABEL)
    agent_path.write_bytes(plistlib.dumps(agent)); agent_path.chmod(0o600)
    run(["/bin/launchctl", "bootstrap", target, str(agent_path)])


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


def activity_parameters(arguments):
    """Accept both legacy Node and Python wrappers, and our own app entry point."""
    if len(arguments) >= 2 and arguments[1] == "--collect-activity":
        return arguments[2:]
    for index, argument in enumerate(arguments):
        if Path(argument).name == "sync-skysight.mjs":
            return arguments[index + 1:]
    raise RuntimeError("existing_collection_configuration_unsupported")


def background_preflight(target, configurations, launcher, version):
    """Check each source under the client's actual background identity."""
    for source, environment, parameters in configurations:
        _background_check(target, source, environment, parameters, launcher, version)


def _background_check(target, source, environment, parameters, launcher, version):
    label = "com.yuwk.personal-data-hub-preflight." + str(os.getpid())
    with tempfile.TemporaryDirectory(prefix=".preflight-", dir=version.parent.parent) as temporary:
        folder = Path(temporary)
        output = folder / "result.json"
        config = {
            "Label": label, "RunAtLoad": True, "WorkingDirectory": str(version),
            "EnvironmentVariables": {**environment, "CHATLOG_EXECUTABLE": str(version / "bin/chatlog-keeper")},
            "ProgramArguments": [str(launcher), "--collection-check-" + source, *parameters],
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
                        if result.get("error") == "authorization_required":
                            raise RuntimeError("collection_authorization_required")
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
    collection_only = env.get("WECHAT_FACT_EXTRACTION") == "false"
    env["WECHAT_FACT_EXTRACTION"] = "false"
    activity = configs[LABELS[1]]
    args = activity.get("ProgramArguments", [])
    if not env.get("CRM_CHECKPOINT"):
        raise RuntimeError("existing_collection_configuration_unsupported")
    parameters = activity_parameters(args)
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
    launcher = app / "Contents/MacOS/PersonalDataHub"
    if not launcher.is_file():
        raise RuntimeError("collection_launcher_unavailable")
    python = version / "python/bin/python3.12"
    wechat_arguments = [str(launcher), "--collect-wechat"]
    activity_arguments = [str(launcher), "--collect-activity", *parameters]
    code_paths_match = (collection_only and wechat["ProgramArguments"] == wechat_arguments and args == activity_arguments
                        and env.get("CHATLOG_EXECUTABLE") == str(version / "bin/chatlog-keeper")
                        and env.get("CHATLOG_EXPECTED_SHA256") == manifest["chatlogSHA256"])
    if (current.get("archiveSHA256") == manifest["archiveSHA256"]
            and current.get("launcher") == str(launcher) and all(loaded.values()) and code_paths_match):
        # A matching receipt does not prove macOS still allows background reads.
        # Probe temporary jobs without restarting either live collector.
        background_preflight(target, [("wechat", env, []),
                                     ("activity", activity.get("EnvironmentVariables", {}), parameters)], launcher, version)
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
    if digest(version / "bin/node") != manifest["nodeSHA256"]:
        raise RuntimeError("node_checksum_mismatch")
    background_preflight(target, [("wechat", env, []),
                                 ("activity", activity.get("EnvironmentVariables", {}), parameters)], launcher, version)
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
        activity["ProgramArguments"] = activity_arguments
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
                   "launcher": str(launcher), "authorization_subject": "com.yuwk.personal-data-hub",
                   "credential_reader_preserved": True}
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
        result = _install(app)
        install_network(app)
        return result


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--network", choices=["enable", "disable"])
    args = parser.parse_args()
    try:
        if args.network: install_network(args.app.resolve(), args.network == "enable")
        else: install(args.app.resolve(), args.status)
    except Exception as error:
        # Private configs and subprocess stderr must never enter UI/terminal logs.
        print("collection_install_failed:" + (str(error) if isinstance(error, RuntimeError) else type(error).__name__))
        raise SystemExit(2 if str(error) == "collection_authorization_required" else 1)
