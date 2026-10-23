"""Synthetic migration and archive safety checks; never touch live launchd state."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / "apps/mac-client/install-agents.py"
spec = importlib.util.spec_from_file_location("installer", source)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class BundleTests(unittest.TestCase):
    def test_archive_rejects_escape_and_external_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, link in [("../outside", None), ("inside", "/private/outside"), ("inside/link", "../../outside")]:
                archive = root / "payload.tar"
                with tarfile.open(archive, "w") as tar:
                    info = tarfile.TarInfo(name)
                    if link:
                        info.type = tarfile.SYMTYPE
                        info.linkname = link
                        tar.addfile(info)
                    else:
                        info.size = 1
                        tar.addfile(info, io.BytesIO(b"x"))
                with self.assertRaises(RuntimeError):
                    installer.safe_extract(archive, root / "target")
            self.assertFalse((root.parent / "outside").exists())

    def _fixture(self, root):
        app = root / "Applications/Hub.app"
        resources = app / "Contents/Resources"
        resources.mkdir(parents=True)
        (app / "Contents/MacOS").mkdir()
        (app / "Contents/MacOS/PersonalDataHub").write_bytes(b"signed-client")
        archive = resources / "collection.tar.gz"
        payload = {"bin/chatlog-keeper": b"reader", "run-wechat.py": b"runner", "bin/node": b"node"}
        with tarfile.open(archive, "w:gz") as tar:
            for name, data in payload.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        support = root / "Library/Application Support/PersonalDataHub"
        binary = support / "Personal Data Hub Credentials.app/Contents/MacOS/PersonalDataHubCredentialReader"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"approved-reader")
        manifest = {"schema": 1, "archiveSHA256": installer.digest(archive),
                    "chatlogSHA256": hashlib.sha256(b"reader").hexdigest(),
                    "nodeSHA256": hashlib.sha256(b"node").hexdigest(),
                    "credentialReader": {"binarySHA256": installer.digest(binary)}}
        (resources / "collection.json").write_text(json.dumps(manifest))
        checkpoint = root / "private/checkpoint.json"
        checkpoint.parent.mkdir()
        checkpoint.write_bytes(b'{"last_synced_at":"2026-10-07T05:39:23Z"}')
        agent_folder = root / "Library/LaunchAgents"
        agent_folder.mkdir()
        authorized_python = root / "approved-python"
        authorized_python.write_bytes(b"authorized-runtime")
        for label in installer.LABELS:
            config = {"Label": label, "ProgramArguments": [str(authorized_python), "old-wrapper", "approved-node", "sync-skysight.mjs", "--host", "nas"],
                      "WorkingDirectory": str(root / "old-checkout"), "EnvironmentVariables": {"CRM_CHECKPOINT": str(checkpoint), "CRM_CLIENT_ID": "existing-device", "CRM_ACCOUNT_NAMESPACE": "existing-account", "CHATLOG_SCOPE_MODE": "all_direct", "CRM_ENV_FILE": str(root / "private-existing.env"), "PYTHONPATH": "old-checkout", "WECHAT_FACT_EXTRACTION": "true"}, "RunAtLoad": True}
            (agent_folder / (label + ".plist")).write_bytes(plistlib.dumps(config))
        return app, checkpoint, agent_folder

    def test_migration_preserves_state_authority_and_rolls_back_on_failure(self):
        for fail in [False, True]:
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app, checkpoint, agents = self._fixture(root)
                originals = {label: (agents / (label + ".plist")).read_bytes() for label in installer.LABELS}
                checkpoint_before = checkpoint.read_bytes()
                loaded = {label: True for label in installer.LABELS}
                failed = False
                def run(args, check=True):
                    nonlocal failed
                    if args[0] == "/bin/launchctl":
                        label = args[-1].split("/")[-1].removesuffix(".plist")
                        if args[1] == "print":
                            return SimpleNamespace(returncode=0 if loaded[label] else 1)
                        if args[1] == "bootout":
                            loaded[label] = False
                        if args[1] == "bootstrap":
                            if fail and not failed:
                                failed = True
                                raise RuntimeError("bootstrap_failed")
                            loaded[label] = True
                    return SimpleNamespace(returncode=0)
                with patch.object(Path, "home", return_value=root), patch.object(installer, "run", side_effect=run), patch.object(installer, "background_preflight"):
                    if fail:
                        with self.assertRaises(RuntimeError):
                            installer.install(app)
                    else:
                        installer.install(app)
                self.assertEqual(checkpoint.read_bytes(), checkpoint_before)
                self.assertTrue(all(loaded.values()))
                for label in installer.LABELS:
                    current = (agents / (label + ".plist")).read_bytes()
                    if fail:
                        self.assertEqual(current, originals[label])
                    else:
                        config = plistlib.loads(current)
                        self.assertEqual(config["EnvironmentVariables"]["CRM_CLIENT_ID"], "existing-device")
                        self.assertEqual(config["EnvironmentVariables"]["CRM_ACCOUNT_NAMESPACE"], "existing-account")
                        self.assertEqual(config["EnvironmentVariables"]["CHATLOG_SCOPE_MODE"], "all_direct")
                        self.assertEqual(config["EnvironmentVariables"]["CRM_ENV_FILE"], str(root / "private-existing.env"))
                        self.assertNotIn("PYTHONPATH", config["EnvironmentVariables"] if label == installer.LABELS[0] else {})
                        if label == installer.LABELS[1]:
                            self.assertEqual(config["ProgramArguments"], [str(app / "Contents/MacOS/PersonalDataHub"), "--collect-activity", "--host", "nas"])
                        else:
                            self.assertEqual(config["ProgramArguments"], [str(app / "Contents/MacOS/PersonalDataHub"), "--collect-wechat"])
                            self.assertEqual(config["EnvironmentVariables"]["WECHAT_FACT_EXTRACTION"], "false")

    def test_relative_state_paths_preserved_and_unsupported_config_stays_loaded(self):
        for unsupported in [False, True]:
            with self.subTest(unsupported=unsupported), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app, checkpoint, agents = self._fixture(root)
                path = agents / (installer.LABELS[0] + ".plist")
                config = plistlib.loads(path.read_bytes())
                config["WorkingDirectory"] = str(checkpoint.parent)
                config["EnvironmentVariables"]["CRM_CHECKPOINT"] = checkpoint.name
                config["EnvironmentVariables"]["WECHAT_MEDIA_QUEUE"] = "queue.json"
                config["EnvironmentVariables"]["CRM_ENV_FILE"] = "connector.env"
                if unsupported:
                    del config["EnvironmentVariables"]["CRM_CHECKPOINT"]
                path.write_bytes(plistlib.dumps(config))
                loaded = {label: True for label in installer.LABELS}
                def run(args, check=True):
                    if args[0] == "/bin/launchctl":
                        label = args[-1].split("/")[-1].removesuffix(".plist")
                        if args[1] == "print":
                            return SimpleNamespace(returncode=0 if loaded[label] else 1)
                        if args[1] == "bootout":
                            loaded[label] = False
                        if args[1] == "bootstrap":
                            loaded[label] = True
                    return SimpleNamespace(returncode=0)
                with patch.object(Path, "home", return_value=root), patch.object(installer, "run", side_effect=run) as command, patch.object(installer, "background_preflight"):
                    if unsupported:
                        with self.assertRaisesRegex(RuntimeError, "configuration_unsupported"):
                            installer.install(app)
                        self.assertFalse(any(call.args[0][1] == "bootout" for call in command.call_args_list))
                    else:
                        installer.install(app)
                        env = plistlib.loads(path.read_bytes())["EnvironmentVariables"]
                        self.assertEqual(env["CRM_CHECKPOINT"], str(checkpoint))
                        self.assertEqual(env["WECHAT_MEDIA_QUEUE"], str(checkpoint.parent / "queue.json"))
                        self.assertEqual(env["CRM_ENV_FILE"], str(checkpoint.parent / "connector.env"))

    def test_background_access_failure_does_not_stop_existing_agents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, checkpoint, agents = self._fixture(root)
            originals = {path: path.read_bytes() for path in agents.iterdir()}
            with patch.object(Path, "home", return_value=root), patch.object(installer, "run", return_value=SimpleNamespace(returncode=0)) as command, patch.object(installer, "background_preflight", side_effect=RuntimeError("collection_authorization_required")):
                with self.assertRaisesRegex(RuntimeError, "authorization_required"):
                    installer.install(app)
                self.assertFalse(any(call.args[0][1] == "bootout" for call in command.call_args_list))
            self.assertTrue(all(path.read_bytes() == value for path, value in originals.items()))

    def test_console_wechat_and_direct_node_migrate_without_old_interpreters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, checkpoint, agents = self._fixture(root)
            for label, arguments in [(installer.LABELS[0], ["/removed/.venv/bin/personal-crm-wechat", "--watch"]),
                                     (installer.LABELS[1], ["/removed/node", "/old/sync-skysight.mjs", "--host", "existing-nas"])]:
                path = agents / (label + ".plist")
                config = plistlib.loads(path.read_bytes())
                config["ProgramArguments"] = arguments
                path.write_bytes(plistlib.dumps(config))
            loaded = set(installer.LABELS)
            def run(args, check=True):
                if args[0] == "/bin/launchctl":
                    label = args[-1].split("/")[-1].removesuffix(".plist")
                    if args[1] == "print": return SimpleNamespace(returncode=0 if label in loaded else 1)
                    if args[1] == "bootout": loaded.discard(label)
                    if args[1] == "bootstrap": loaded.add(label)
                return SimpleNamespace(returncode=0)
            with patch.object(Path, "home", return_value=root), patch.object(installer, "run", side_effect=run) as command, patch.object(installer, "background_preflight"):
                installer.install(app)
                command.reset_mock()
                installer.install(app)
                self.assertFalse(any(call.args[0][0] == "/bin/launchctl" and call.args[0][1] in ["bootout", "bootstrap"] for call in command.call_args_list))
                command.reset_mock()
                with patch.object(installer, "background_preflight", side_effect=RuntimeError("collection_authorization_required")):
                    with self.assertRaisesRegex(RuntimeError, "authorization_required"):
                        installer.install(app)
                self.assertEqual(loaded, set(installer.LABELS))
                self.assertFalse(any(call.args[0][0] == "/bin/launchctl" and call.args[0][1] in ["bootout", "bootstrap"] for call in command.call_args_list))
            for label in installer.LABELS:
                config = plistlib.loads((agents / (label + ".plist")).read_bytes())
                self.assertEqual(config["ProgramArguments"][0], str(app / "Contents/MacOS/PersonalDataHub"))
            self.assertEqual(config["ProgramArguments"][2:], ["--host", "existing-nas"])


if __name__ == "__main__":
    unittest.main()
