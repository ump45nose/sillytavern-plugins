"""Update only the packaged WeChat collector, preserving the installed UI and launch identity.

python update-wechat.py --prepare /absolute/candidate.app --connector-source /absolute/personal-crm/src/personal_crm/connector
python update-wechat.py --install /absolute/candidate.app
"""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
APP = Path.home() / 'Applications/Personal Data Hub.app'
SUPPORT = Path.home() / 'Library/Application Support/PersonalDataHub'
LABEL = 'com.personal-crm.wechat'


def prepare(candidate, source=None, media_deps=None):
    if candidate.exists():
        raise FileExistsError(candidate)
    source = source or ROOT.parent / 'crm/src/personal_crm/connector'
    if not (source / 'sync.py').is_file() or not (source / 'media.py').is_file():
        raise RuntimeError('connector_source_required')
    subprocess.run(['codesign', '--verify', '--strict', str(APP)], check=True)
    shutil.copytree(APP, candidate, symlinks=True)
    resources = candidate / 'Contents/Resources'
    replacements = {'packages/personal_crm/connector/' + p.name: p.read_bytes() for p in source.glob('*.py')}
    core = source.parent / 'core'
    for name in ('__init__.py', 'presentation.py'):
        replacements['packages/personal_crm/core/' + name] = (core / name).read_bytes()
    if media_deps:
        for folder in ('PIL', 'pilk'):
            for path in (media_deps / folder).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    replacements['packages/' + str(path.relative_to(media_deps))] = path.read_bytes()
        binaries = list((media_deps / 'imageio_ffmpeg/binaries').glob('ffmpeg-macos-*'))
        if len(binaries) != 1:
            raise RuntimeError('media_ffmpeg_binary_required')
        replacements['bin/ffmpeg'] = binaries[0].read_bytes()
    replacements['run-wechat.py'] = (ROOT / 'collection/run-wechat.py').read_bytes()
    output = resources / 'collection.new.tar.gz'
    with tarfile.open(resources / 'collection.tar.gz', 'r:gz') as old, tarfile.open(output, 'w:gz') as new:
        written = set()
        for item in old:
            if item.name in {'packages/personal_crm/connector/fact_extractor.py', 'packages/personal_crm/connector/presentation.py'}:
                continue
            data = replacements.get(item.name)
            if data is not None:
                item.size = len(data)
                if item.name == 'bin/ffmpeg': item.mode = 0o700
                new.addfile(item, io.BytesIO(data)); written.add(item.name)
            else:
                new.addfile(item, old.extractfile(item) if item.isfile() else None)
        for name, data in replacements.items():
            if name not in written:
                item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o700 if name == 'bin/ffmpeg' else 0o600
                new.addfile(item, io.BytesIO(data))
    output.replace(resources / 'collection.tar.gz')
    manifest_path = resources / 'collection.json'
    manifest = json.loads(manifest_path.read_text())
    # The installer uses this checksum as the signed payload's integrity requirement.
    with (resources / 'collection.tar.gz').open('rb') as f:
        manifest['archiveSHA256'] = hashlib.file_digest(f, 'sha256').hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    shutil.copy2(ROOT / 'install-agents.py', resources / 'install-agents.py')
    identity = SUPPORT / 'Signing/identity.json'
    if not identity.is_file():
        raise RuntimeError('existing_signing_identity_required')
    subprocess.run(['swift', '-suppress-warnings', str(ROOT / 'signing.swift'), str(candidate)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(candidate)], check=True)
    def requirement(app):
        result = subprocess.check_output(['codesign', '-d', '-r-', str(app)], stderr=subprocess.STDOUT, text=True)
        return next(line for line in result.splitlines() if line.startswith('designated =>'))
    if requirement(APP) != requirement(candidate):
        raise RuntimeError('installed_signing_identity_changed')
    print(json.dumps({'candidate': str(candidate), 'prepared': True}))


def install(candidate, check_only=False):
    spec = importlib.util.spec_from_file_location('agent_install', ROOT / 'install-agents.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    subprocess.run(['codesign', '--verify', '--strict', str(candidate)], check=True)
    resources = candidate / 'Contents/Resources'
    manifest = json.loads((resources / 'collection.json').read_text())
    if helper.digest(resources / 'collection.tar.gz') != manifest['archiveSHA256']:
        raise RuntimeError('collection_payload_integrity_failed')
    version = SUPPORT / 'Agents/versions' / manifest['archiveSHA256']
    if not version.exists():
        version.mkdir(mode=0o700)
        helper.safe_extract(resources / 'collection.tar.gz', version)
    plist_path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    old_plist = plist_path.read_bytes(); config = plistlib.loads(old_plist)
    old_version = config['WorkingDirectory']
    env = config.setdefault('EnvironmentVariables', {})
    # Preserve the existing native launcher or explicit Python wrapper as installed.
    config['ProgramArguments'] = [x.replace(old_version, str(version)) for x in config['ProgramArguments']]
    config['WorkingDirectory'] = str(version)
    env['CHATLOG_EXECUTABLE'] = str(version / 'bin/chatlog-keeper')
    env.pop('WECHAT_FACT_EXTRACTION', None)
    target = 'gui/' + str(os.getuid())
    # Copy an existing approved wrapper if the installed launch path uses one.
    for item in config['ProgramArguments']:
        if item.startswith(str(version)) and not Path(item).exists():
            previous = Path(item.replace(str(version), old_version, 1))
            if previous.is_file() and previous.name == 'launch-wechat.py':
                shutil.copy2(previous, item)
    if config['ProgramArguments'][0].endswith('/PersonalDataHub'):
        helper._background_check(target, 'wechat', env, [], candidate / 'Contents/MacOS/PersonalDataHub', version)
    else:
        # Check the actual existing Python launcher, not an unrelated native route.
        import tempfile, time
        label = 'com.yuwk.crm-collector-check.' + str(os.getpid())
        with tempfile.TemporaryDirectory(prefix='crm-check-') as tmp:
            folder = Path(tmp); output = folder / 'output.json'
            check = dict(config)
            check['Label'] = label
            check['ProgramArguments'] = [x if x != '--watch' else '--access-check' for x in config['ProgramArguments']]
            check['KeepAlive'] = False; check['RunAtLoad'] = True
            check['StandardOutPath'] = str(output); check['StandardErrorPath'] = str(folder / 'error')
            path = folder / 'check.plist'; path.write_bytes(plistlib.dumps(check))
            try:
                helper.run(['launchctl', 'bootstrap', target, str(path)])
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and not (output.exists() and output.stat().st_size):
                    time.sleep(0.2)
                if not output.exists() or json.loads(output.read_text()).get('readable') is not True:
                    raise RuntimeError('existing_launcher_access_check_failed')
            finally:
                helper.stop_job(target, label)
    if check_only:
        print(json.dumps({'collector_access': True, 'runtime': str(version)}))
        return
    backup = SUPPORT / 'backups' / ('crm-collector-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, mode=0o700)
    (backup / 'wechat.plist').write_bytes(old_plist)
    receipt_path = SUPPORT / 'Agents/current.json'
    old_receipt = receipt_path.read_bytes()
    (backup / 'current.json').write_bytes(old_receipt)
    helper.stop_job(target, LABEL)
    checkpoint = Path(env['CRM_CHECKPOINT']).expanduser()
    if checkpoint.exists():
        shutil.copy2(checkpoint, backup / 'checkpoint.json')
    swapped = False
    try:
        APP.rename(backup / APP.name)
        swapped = True
        shutil.copytree(candidate, APP, symlinks=True)
        plist_path.write_bytes(plistlib.dumps(config)); plist_path.chmod(0o600)
        receipt = json.loads(old_receipt)
        receipt.update(archiveSHA256=manifest['archiveSHA256'], runtime=str(version), backup=str(backup), app=str(APP))
        receipt_path.write_text(json.dumps(receipt, indent=2)); receipt_path.chmod(0o600)
        subprocess.run(['launchctl','bootstrap',target,str(plist_path)], check=True)
    except BaseException:
        helper.stop_job(target, LABEL)
        if swapped:
            if APP.exists(): shutil.rmtree(APP)
            (backup / APP.name).rename(APP)
        plist_path.write_bytes(old_plist); receipt_path.write_bytes(old_receipt)
        subprocess.run(['launchctl','bootstrap',target,str(plist_path)], check=True)
        raise
    print(json.dumps({'installed': True, 'backup': str(backup), 'runtime': str(version)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', type=Path)
    group.add_argument('--install', type=Path)
    group.add_argument('--check', type=Path)
    parser.add_argument('--app', type=Path, default=APP)
    parser.add_argument('--connector-source', type=Path)
    parser.add_argument('--media-deps', type=Path)
    args = parser.parse_args()
    APP = args.app.resolve()
    if args.prepare:
        prepare(args.prepare.resolve(), args.connector_source.resolve() if args.connector_source else None, args.media_deps.resolve() if args.media_deps else None)
    else:
        install((args.install or args.check).resolve(), check_only=args.check is not None)
