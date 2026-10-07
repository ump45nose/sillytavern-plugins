"""Steam entry adapter; configuration and candidate evidence live outside source."""
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.locks import Lease, Busy
from common.model import atomic_json, result
from common.details import metric
from platforms.steam.discovery import discover, StoreClient, DiscoveryState, validate_store_proxy
from platforms.steam.ipc import Client, SteamError
from platforms.steam.workflow import Journal, run_workflow

ROOT = Path(__file__).resolve().parents[2]


def read_private_json(raw_path, limit=65536):
    if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
        raise SteamError('private_file_requires_absolute_path')
    path = Path(raw_path).resolve()
    if path == ROOT or ROOT in path.parents:
        raise SteamError('private_file_must_be_outside_source')
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_mode & 0o077 or stat.st_uid != os.getuid() or stat.st_size > limit:
            raise SteamError('private_file_permissions_or_size')
        return json.loads(path.read_text())
    except (OSError, ValueError, UnicodeError):
        raise SteamError('private_file_unreadable') from None


def config(value):
    required = {'ipc_url', 'ipc_password', 'bot', 'steam_id', 'region'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'candidates_path', 'discovery', 'store_proxy_url'}:
        raise SteamError('invalid_steam_config')
    if not isinstance(value['steam_id'], str) or not re.fullmatch(r'7656119[0-9]{10}', value['steam_id']):
        raise SteamError('invalid_steam_id')
    if not isinstance(value['region'], str) or not re.fullmatch(r'[A-Z]{2}', value['region']):
        raise SteamError('invalid_steam_region')
    if 'store_proxy_url' in value:
        validate_store_proxy(value['store_proxy_url'])
    if 'candidates_path' in value and 'discovery' in value:
        raise SteamError('choose_one_candidate_source')
    discovery = value.get('discovery', {})
    if (not isinstance(discovery, dict) or set(discovery) - {'change_number', 'max_packages'}
            or type(discovery.get('change_number', 0)) is not int or not 0 <= discovery.get('change_number', 0) < 2**32
            or type(discovery.get('max_packages', 30)) is not int or not 1 <= discovery.get('max_packages', 30) <= 50):
        raise SteamError('invalid_discovery_config')
    return value


def main():
    os.umask(0o077)
    context = {k: os.environ['BENEFITS_' + k.upper()] for k in ('run_id', 'platform', 'account', 'business_date')}
    destination = os.environ['BENEFITS_RESULT_PATH']
    latest = None

    def publish(payload):
        nonlocal latest
        if len(payload['details']['items']) > 100:
            payload = {**payload, 'business': {**payload['business'], 'claim': 'unknown'},
                       'reason': 'result_items_truncated',
                       'details': {'metrics': {**payload['details']['metrics'],
                                  'omitted_items': metric('count', current=len(payload['details']['items']) - 100)},
                                   'items': sorted(payload['details']['items'], key=lambda item: item['status'] == 'complete')[:100]}}
        latest = result(context, payload['execution'], payload['reason'], payload['business'], payload['details'])
        atomic_json(destination, latest)

    def fail(reason):
        value = latest or result(context, 'failed', reason, {'claim': 'unknown'})
        value.update(execution_status='failed', reason=reason)
        atomic_json(destination, value)

    try:
        settings = config(read_private_json(os.environ.get('STEAM_CONFIG')))
        manifest = read_private_json(settings['candidates_path']) if 'candidates_path' in settings else None
        if manifest is not None and isinstance(manifest, dict):
            for row in manifest.get('candidates', []):
                if isinstance(row, dict) and isinstance(row.get('evidence'), dict) and row['evidence'].get('method') == 'official_store_free_to_keep':
                    raise SteamError('reserved_automatic_evidence_method')
        state = Path(os.environ['BENEFITS_STATE_DIR'])
        # Shared across account aliases: two aliases targeting one Steam ID must
        # not bypass locks, the journal, or the rolling attempt budget.
        shared = state.parent / '_steam_ids'
        shared.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(shared.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        with Lease(shared / (settings['steam_id'] + '.lock'), 0):
            journal = Journal(shared / (settings['steam_id'] + '.json'), settings['steam_id'])
            client = Client(settings['ipc_url'], settings['ipc_password'], settings['bot'], settings['steam_id'])
            discovery_report = None
            recovery_items = []
            automatic = manifest is None

            def recovery_progress(payload):
                if automatic:
                    payload['business']['discovery'] = 'unknown'
                publish(payload)

            # New discovery cannot block reconciliation of an earlier POST.
            if any(entry['state'] == 'pending' for entry in journal.entries.values()):
                recovered = run_workflow(client, {'schema_version': 1, 'candidates': []}, settings['region'], journal,
                                         claim=False, publish=recovery_progress)
                recovery_items = recovered['details']['items']
                recovery_progress(recovered)
            elif automatic:
                publish({'execution': 'ok', 'reason': 'discovery_in_progress',
                         'business': {'claim': 'unknown', 'discovery': 'unknown'},
                         'details': {'metrics': {}, 'items': []}})
            if manifest is None:
                client.session()
                discovery_settings = settings.get('discovery', {})
                discovery_state = DiscoveryState(shared / (settings['steam_id'] + '.discovery.json'),
                                                 discovery_settings.get('change_number', 0))
                store_options = {'proxy_url': settings['store_proxy_url']} if 'store_proxy_url' in settings else {}
                manifest, discovery_report = discover(client, StoreClient(**store_options), settings['region'],
                    state=discovery_state, confirmed={int(pid) for pid, entry in journal.entries.items() if entry['state'] == 'confirmed'},
                    **discovery_settings)

            def deliver(payload):
                payload = {**payload, 'business': dict(payload['business']),
                           'details': {'metrics': dict(payload['details']['metrics']), 'items': list(payload['details']['items'])}}
                if recovery_items:
                    merged = {item['id']: item for item in recovery_items}
                    merged.update({item['id']: item for item in payload['details']['items']})
                    payload['details']['items'] = list(merged.values())
                    if any(item['status'] == 'unknown' for item in recovery_items):
                        payload['business']['claim'] = 'unknown'
                    elif payload['business']['claim'] == 'not_applicable':
                        payload['business']['claim'] = 'complete'
                        payload['reason'] = 'previous_submissions_reconciled'
                if discovery_report is not None:
                    payload = dict(payload)
                    payload['business'] = dict(payload['business'])
                    payload['business']['discovery'] = ('unknown' if discovery_report['coverage_incomplete'] or discovery_report['rejected'] else 'complete')
                    payload['details'] = {'metrics': dict(payload['details']['metrics']),
                                          'items': payload['details']['items'] + [item for item in discovery_report['rejected']
                                              if item['id'] not in {row['id'] for row in payload['details']['items']}]}
                    payload['details']['metrics']['discovered_packages'] = metric('count', current=len(manifest['candidates']))
                    payload['details']['metrics']['scanned_packages'] = metric('count', current=discovery_report['scanned'])
                    if discovery_report['coverage_incomplete']:
                        payload['reason'] = 'discovery_coverage_incomplete'
                    elif discovery_report['rejected']:
                        payload['reason'] = 'discovery_candidates_require_review'
                publish(payload)

            deliver(run_workflow(client, manifest, settings['region'], journal,
                                 claim='--claim' in sys.argv[1:], publish=deliver))
    except Busy:
        atomic_json(destination, result(context, 'busy', 'steam_account_lock_busy', {'claim': 'blocked'}))
    except SteamError as error:
        fail(error.reason)
    except (OSError, ValueError, TypeError, KeyError):
        # Never print config values, exceptions, response bodies, or credentials.
        fail('steam_configuration_or_io_error')


if __name__ == '__main__':
    main()
