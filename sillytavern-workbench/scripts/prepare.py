"""Prepare isolated fixtures. Never reads production chats, settings, or secrets."""
from pathlib import Path
import hashlib
import json
import os
import secrets
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / 'baseline.lock.json').read_text())
UPSTREAM = ROOT / 'upstream' / 'SillyTavern'

if not UPSTREAM.exists():
    subprocess.run(['git', 'clone', '--depth', '1', '--branch', LOCK['upstream']['release'],
                    LOCK['upstream']['repository'], str(UPSTREAM)], check=True)
actual = subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip()
if actual != LOCK['upstream']['commit']:
    raise SystemExit('Upstream checkout differs from baseline.lock.json; refusing to prepare.')
image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', LOCK['image']['reference']], text=True))[0]
if image['Config']['Labels']['org.opencontainers.image.revision'] != actual:
    raise SystemExit('Official image revision does not match the checked-out release.')

env_path = ROOT / '.env'
if not env_path.exists():
    env_path.write_text('\n'.join([
        'WB_BIND_ADDRESS=192.168.31.201',
        f'WB_UID={os.getuid()}', f'WB_GID={os.getgid()}',
        'WB_USERNAME=workbench', f'WB_PASSWORD={secrets.token_urlsafe(24)}', '',
    ]))
    env_path.chmod(0o600)
env = dict(line.split('=', 1) for line in env_path.read_text().splitlines() if '=' in line and not line.startswith('#'))

for name in ['baseline', 'validation']:
    directory = ROOT / 'runtime' / name
    for sub in ['config', 'data/default-user', 'backups', 'plugins', 'extensions']:
        (directory / sub).mkdir(parents=True, exist_ok=True)
    if name == 'validation':
        # Nested read-only bind mounts need their mountpoint in the parent bind.
        (directory / 'extensions/workbench-probe').mkdir(exist_ok=True)
    config_path = directory / 'config/config.yaml'
    if not config_path.exists():
        config_path.write_text(f'''dataRoot: ./data
listen: true
port: 8000
browserLaunch:
  enabled: false
whitelistMode: false
basicAuthMode: true
basicAuthUser:
  username: {json.dumps(env['WB_USERNAME'])}
  password: {json.dumps(env['WB_PASSWORD'])}
enableUserAccounts: false
enableServerPlugins: false
enableServerPluginsAutoUpdate: false
extensions:
  enabled: true
  autoUpdate: false
  models:
    autoDownload: false
''')
        config_path.chmod(0o600)
    settings_path = directory / 'data/default-user/settings.json'
    if not settings_path.exists():
        settings = json.loads((UPSTREAM / 'default/content/settings.json').read_text())
        settings['firstRun'] = False
        settings['main_api'] = 'openai'
        settings['oai_settings'].update({
            'chat_completion_source': 'custom', 'custom_url': 'http://mock-model:4010/v1',
            'custom_model': 'workbench-fixture', 'stream_openai': True,
        })
        settings['extension_settings']['disabledExtensions'] = []
        settings['extension_settings']['notifyUpdates'] = False
        settings['enableAutoUpdate'] = False
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2))

source = Path(os.environ.get('WB_HELPER_SOURCE', LOCK['helper']['source']))
target = ROOT / 'runtime/validation/extensions/JS-Slash-Runner'
if not target.exists():
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest['version'] != LOCK['helper']['version']:
        raise SystemExit('Installed helper version changed; review lock before preparing a new snapshot.')
    target.mkdir(parents=True)
    for sub in ['dist', 'lib', 'i18n']:
        shutil.copytree(source / sub, target / sub)
    shutil.copy2(source / 'manifest.json', target / 'manifest.json')
    shutil.copy2(source / 'LICENSE', target / 'LICENSE')
snapshot = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(target.rglob('*')) if p.is_file()}
snapshot_text = json.dumps(snapshot, indent=2)
expected = LOCK['helper'].get('snapshotSha256')
if expected and hashlib.sha256(snapshot_text.encode()).hexdigest() != expected:
    raise SystemExit('Helper snapshot differs from the validated baseline; refusing silent version drift.')
(ROOT / 'runtime/helper-snapshot.json').write_text(snapshot_text)
print(f'Prepared official {LOCK["upstream"]["release"]} ({actual[:12]}), isolated fixtures, and helper {LOCK["helper"]["version"]}.')
print('Credentials stored only in .env and isolated runtime configuration.')
