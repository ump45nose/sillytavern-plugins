import copy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from platforms.steam.adapter import config, read_private_json
from platforms.steam.candidates import validate_manifest, eligibility, verify_package
from platforms.steam.ipc import Client, SteamError, validate_endpoint
from platforms.steam.workflow import Journal, run_workflow, classify_response

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
STEAM_ID = '76561198000000001'


def candidate(pid=123):
    return {'package_id': pid, 'app_ids': [456], 'name': 'Fixture game',
            'promotion_kind': 'limited_time_free_to_keep', 'permanent_license': True,
            'free_to_play': False, 'free_weekend': False, 'demo': False, 'playtest': False,
            'product_type': 'game', 'price_minor': 0, 'regular_price_minor': 999, 'currency': 'USD',
            'allowed_regions': ['US'], 'starts_at': (NOW - timedelta(hours=1)).isoformat(),
            'ends_at': (NOW + timedelta(hours=1)).isoformat(),
            'evidence': {'reviewed': True, 'checked_at': NOW.isoformat(),
                         'promotion_url': 'https://store.steampowered.com/app/456/',
                         'package_url': f'https://steamdb.info/sub/{pid}/',
                         'region_url': f'https://steamdb.info/sub/{pid}/'}}


def node(name, value=None, children=None):
    return {'Name': name, 'Value': value, 'Children': children or []}


def product(pid=123):
    return node(str(pid), children=[node('billingtype', '0'), node('licensetype', '1'),
        node('status', '0'), node('appids', children=[node('0', '456')])])


class FakeClient:
    def __init__(self):
        self.owned_packages = set()
        self.posts = []
        self.reads = 0
        self.response = {'Result': 1, 'PurchaseResultDetail': 0}
        self.grant = True
        self.error = None
        self.metadata = product()

    def session(self):
        self.reads += 1

    def owned(self):
        self.reads += 1
        return set(self.owned_packages)

    def package(self, pid):
        self.reads += 1
        metadata = copy.deepcopy(self.metadata)
        metadata['Name'] = str(pid)
        return metadata

    def app(self, app_id):
        self.reads += 1
        return node('appinfo', children=[node('appid', str(app_id)), node('common', children=[node('type', 'Game')])])

    def claim(self, pid):
        self.posts.append(pid)
        if self.grant:
            self.owned_packages.add(pid)
        if self.error:
            raise self.error
        return self.response


class EvidenceTests(unittest.TestCase):
    def test_complete_fixture(self):
        self.assertIsNone(eligibility(candidate(), 'US', NOW))
        self.assertIsNone(verify_package(product(), candidate(), NOW))

    def test_exclusions_and_unknown(self):
        for field in ['free_to_play', 'free_weekend', 'demo', 'playtest']:
            for value in [True, None, 'false', 0]:
                row = candidate(); row[field] = value
                self.assertIsNotNone(eligibility(row, 'US', NOW), (field, value))
        for field, value in [('promotion_kind', 'free'), ('permanent_license', False),
                             ('price_minor', False), ('regular_price_minor', 0),
                             ('app_ids', []), ('product_type', 'dlc')]:
            row = candidate(); row[field] = value
            self.assertIsNotNone(eligibility(row, 'US', NOW))

    def test_regions_windows_and_freshness(self):
        row = candidate()
        self.assertEqual(eligibility(row, 'CN', NOW), 'region_not_verified')
        self.assertEqual(eligibility(row, 'US', NOW + timedelta(hours=1)), 'promotion_expired')
        self.assertEqual(eligibility(row, 'US', NOW - timedelta(hours=2)), 'promotion_not_active')
        row['evidence']['checked_at'] = (NOW - timedelta(hours=2)).isoformat()
        self.assertEqual(eligibility(row, 'US', NOW), 'promotion_evidence_stale')
        row['evidence']['checked_at'] = NOW.replace(tzinfo=None).isoformat()
        self.assertEqual(eligibility(row, 'US', NOW), 'promotion_time_unverified')

    def test_package_and_urls_must_match(self):
        for url in ['https://evil.example/sub/123/', 'https://steamdb.info/sub/999/',
                    'https://steamdb.info/sub/123/?password=x']:
            row = candidate(); row['evidence']['package_url'] = url
            self.assertIsNotNone(eligibility(row, 'US', NOW))
        for name in ['billingtype', 'licensetype', 'status', 'appids']:
            tree = product(); tree['Children'] = [n for n in tree['Children'] if n['Name'] != name]
            self.assertIsNotNone(verify_package(tree, candidate(), NOW))
        tree = product(); tree['Children'].append(node('extended', children=[node('freeweekend', '1')]))
        self.assertEqual(verify_package(tree, candidate(), NOW), 'free_weekend_excluded')
        row = candidate(); row['app_ids'] = [789]
        self.assertEqual(verify_package(product(), row, NOW), 'package_contents_changed')

    def test_duplicate_package_invalidates_whole_manifest(self):
        with self.assertRaises(SteamError):
            validate_manifest({'schema_version': 1, 'candidates': [candidate(), candidate()]}, 'US', NOW)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / 'journal.json', STEAM_ID)
        self.client = FakeClient()

    def tearDown(self):
        self.tmp.cleanup()

    def run_flow(self, rows=None, claim=True, clock=None):
        return run_workflow(self.client, {'schema_version': 1, 'candidates': rows if rows is not None else [candidate()]},
                            'US', self.journal, claim=claim, now=clock or (lambda: NOW))

    def test_dry_run_no_post_or_intent(self):
        out = self.run_flow(claim=False)
        self.assertEqual(out['details']['items'][0]['reason'], 'dry_run_eligible')
        self.assertEqual(self.client.posts, [])
        self.assertFalse(self.journal.path.exists())

    def test_success_requires_readback_and_persists_before_post(self):
        original = self.client.claim
        def claim(pid):
            self.assertEqual(json.loads(self.journal.path.read_text())['entries']['123']['state'], 'pending')
            return original(pid)
        self.client.claim = claim
        out = self.run_flow()
        self.assertEqual(out['business']['claim'], 'complete')
        self.assertEqual(self.client.posts, [123])
        self.assertEqual(self.journal.entries['123']['state'], 'confirmed')
        self.run_flow()
        self.assertEqual(self.client.posts, [123])

    def test_success_envelope_without_ownership_unknown_no_retry(self):
        self.client.grant = False
        out = self.run_flow()
        self.assertEqual(out['business']['claim'], 'unknown')
        self.run_flow()
        self.assertEqual(self.client.posts, [123])
        self.client.owned_packages.add(123)
        out = self.run_flow()
        self.assertEqual(out['business']['claim'], 'complete')
        self.assertEqual(self.client.posts, [123])

    def test_post_timeout_with_and_without_readback(self):
        self.client.error = SteamError('ipc_transport_uncertain')
        self.assertEqual(self.run_flow()['business']['claim'], 'complete')
        self.client.owned_packages.clear()
        self.assertEqual(self.run_flow()['business']['claim'], 'unknown')
        self.assertEqual(self.client.posts, [123])

    def test_rate_limit_inside_success_stops_all_calls(self):
        self.client.grant = False
        self.client.response = {'Result': 1, 'PurchaseResultDetail': 53}
        out = self.run_flow([candidate(), candidate(124)])
        self.assertEqual(self.client.posts, [123])
        self.assertEqual(out['details']['items'][0]['reason'], 'rate_limited')
        self.assertEqual(out['details']['items'][1]['status'], 'blocked')

    def test_auth_post_does_not_retry_or_readback(self):
        self.client.error = SteamError('ipc_authentication_failed')
        out = self.run_flow()
        self.assertEqual(out['details']['items'][0]['reason'], 'ipc_authentication_failed')
        self.assertEqual(self.client.reads, 6)

    def test_submit_failure_stops_rest(self):
        self.client.grant = False
        self.client.response = {'Result': 1, 'PurchaseResultDetail': 13}
        out = self.run_flow([candidate(), candidate(124)])
        self.assertEqual(out['business']['claim'], 'unknown')
        self.assertEqual(self.client.posts, [123])

    def test_rejected_evidence_never_calls_ipc(self):
        row = candidate(); row['free_weekend'] = True
        out = self.run_flow([row])
        self.assertEqual(out['business']['claim'], 'blocked')
        self.assertEqual(self.client.reads, 0)

    def test_expiry_before_submit(self):
        times = iter([NOW, NOW, NOW, NOW + timedelta(hours=2)])
        self.run_flow(clock=lambda: next(times))
        self.assertEqual(self.client.posts, [])

    def test_local_rate_limit_and_clock_reversal(self):
        self.journal.intent(99, NOW.timestamp())
        out = self.run_flow()
        self.assertEqual(out['details']['items'][0]['reason'], 'local_rate_limited')
        self.assertEqual(self.client.posts, [])
        self.assertEqual(self.journal.rate_reason(NOW.timestamp()-1), 'clock_moved_backwards')
        for n in range(25):
            self.journal.entries[str(n+1)] = {'attempted_at': NOW.timestamp()-100, 'state': 'confirmed'}
        self.assertEqual(self.journal.rate_reason(NOW.timestamp()), 'local_rate_limited')

    def test_journal_corruption_blocks(self):
        self.journal.path.write_text('{}')
        with self.assertRaises(SteamError):
            Journal(self.journal.path, STEAM_ID)

    def test_journal_write_failure_prevents_post(self):
        with patch.object(self.journal, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.run_flow()
        self.assertEqual(self.client.posts, [])


class IPCTests(unittest.TestCase):
    def client(self):
        return Client('http://127.0.0.1:1242', 'secret-fixture', 'Bot1', STEAM_ID)

    def test_endpoint_and_bot_restrictions(self):
        for url in ['http://remote.example', 'https://user:secret@host', 'https://host/path', 'https://host?token=x', 'file:///etc/passwd']:
            with self.assertRaises(SteamError):
                validate_endpoint(url)
        for bot in ['ASF', 'Bot1,Bot2', 'x/../y', 'Bot1\nBot2']:
            with self.assertRaises(SteamError):
                Client('http://localhost:1242', 'password', bot, STEAM_ID)

    def test_exact_wire_contract(self):
        client = self.client()
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"Success":true,"Result":{"Result":1,"PurchaseResultDetail":0}}'
        with patch.object(client.opener, 'open', return_value=response) as call:
            self.assertEqual(client.claim(123)['Result'], 1)
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:1242/Api/FreePackages/Bot1/RequestFreeSubLicense?subID=123')
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.get_header('Authentication'), 'secret-fixture')
        self.assertIsNone(request.data)

    def test_login_identity_owned_and_product_schemas(self):
        client = self.client()
        with patch.object(client, 'request', return_value={'Bot1': {'IsConnectedAndLoggedOn': True, 'SteamID': int(STEAM_ID)}}):
            client.session()
        for response in [{'Bot1': {'IsConnectedAndLoggedOn': False}}, {'Bot1': {'IsConnectedAndLoggedOn': True, 'SteamID': 123}}]:
            with patch.object(client, 'request', return_value=response), self.assertRaises(SteamError):
                client.session()
        for data in [{}, ['123'], [True], [0]]:
            with patch.object(client, 'request', return_value=data), self.assertRaises(SteamError):
                client.owned()
        with patch.object(client, 'request', return_value=[{'Packages': {'123': {'ID': 123, 'MissingToken': False, 'KeyValues': product()}}}]):
            self.assertEqual(client.package(123), product())

    def test_auth_and_redirects_are_not_retried(self):
        for status, reason in [(401, 'ipc_authentication_failed'), (403, 'ipc_authentication_failed'), (429, 'rate_limited'), (302, 'ipc_redirect_rejected')]:
            client = self.client()
            with patch.object(client.opener, 'open', side_effect=HTTPError('url', status, 'secret', {}, None)) as call:
                with self.assertRaisesRegex(SteamError, '^' + reason + '$'):
                    client.owned()
                self.assertEqual(call.call_count, 1)

    def test_both_steam_enums_required(self):
        self.assertEqual(classify_response({'Result': 1, 'PurchaseResultDetail': 53}), 'rate_limited')
        self.assertEqual(classify_response({'Result': True, 'PurchaseResultDetail': 0}), 'claim_response_unverified')
        self.assertEqual(classify_response({'Result': 1}), 'claim_response_unverified')


class EntryTests(unittest.TestCase):
    def test_offline_entry_and_claim_requires_execute(self):
        with tempfile.TemporaryDirectory() as runtime:
            proc = subprocess.run([sys.executable, 'platforms/steam/run.py', '--runtime-root', runtime], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data['reason'], 'execution_not_requested')
            self.assertEqual(data['platform'], 'steam')
            self.assertTrue((Path(runtime) / 'runs' / data['run_id'] / 'result.json').exists())
            proc = subprocess.run([sys.executable, 'platforms/steam/run.py', '--runtime-root', runtime, '--claim'], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 2)

    def test_private_config_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'; path.write_text('{}'); path.chmod(0o644)
            with self.assertRaises(SteamError):
                read_private_json(str(path))
            path.chmod(0o600)
            self.assertEqual(read_private_json(str(path)), {})


class SafetyRegressionTests(unittest.TestCase):
    def test_malformed_http_exception_is_sanitized(self):
        from http.client import BadStatusLine
        client = Client('http://127.0.0.1:1242', 'secret-fixture', 'Bot1', STEAM_ID)
        with patch.object(client.opener, 'open', side_effect=BadStatusLine('secret-fixture')):
            with self.assertRaisesRegex(SteamError, '^ipc_transport_uncertain$'):
                client.owned()

    def test_explicit_region_beta_and_demo_conflicts(self):
        from platforms.steam.candidates import verify_app
        for key in ['betatesterpackage', 'deactivated_demo']:
            tree = product(); tree['Children'].append(node('extended', children=[node(key, '1')]))
            self.assertEqual(verify_package(tree, candidate(), NOW, 'US'), 'beta_or_demo_package_excluded')
        for field, flag in [('restrictedcountries', 'onlyallowrestrictedcountries'), ('purchaserestrictedcountries', 'allowpurchasefromrestrictedcountries')]:
            tree = product(); tree['Children'].append(node('extended', children=[node(field, 'US CN')]))
            self.assertEqual(verify_package(tree, candidate(), NOW, 'US'), 'region_restricted')
            tree['Children'][-1]['Children'].append(node(flag, '1'))
            self.assertIsNone(verify_package(tree, candidate(), NOW, 'US'))
            self.assertEqual(verify_package(tree, candidate(), NOW, 'JP'), 'region_restricted')
        app = node('appinfo', children=[node('appid', '456'), node('common', children=[node('type', 'Game')]),
                    node('extended', children=[node('isfreeapp', '1')])])
        self.assertEqual(verify_app(app, 456, 'US'), 'free_to_play_or_unknown_app_excluded')
        app['Children'][-1]['Children'] = [node('playtest_type', '0')]
        self.assertEqual(verify_app(app, 456, 'US'), 'playtest_app_excluded')
        app['Children'][-1]['Children'] = []
        app['Children'][1]['Children'].append(node('restricted_countries', 'US,CN'))
        self.assertEqual(verify_app(app, 456, 'US'), 'region_restricted')

    def test_partial_batch_not_complete_before_later_item(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / 'journal.json', STEAM_ID)
            client = FakeClient(); client.owned_packages = {123}
            original = client.package
            def package(pid):
                if pid == 124:
                    raise KeyboardInterrupt()
                return original(pid)
            client.package = package
            published = []
            with self.assertRaises(KeyboardInterrupt):
                run_workflow(client, {'schema_version': 1, 'candidates': [candidate(), candidate(124)]}, 'US', journal,
                             now=lambda: NOW, publish=published.append)
            self.assertEqual(published[-1]['business']['claim'], 'unknown')
            self.assertEqual(published[-1]['details']['items'][0]['status'], 'complete')

    def test_recovery_not_starved_after_fifty_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / 'journal.json', STEAM_ID)
            journal.entries = {str(i): {'attempted_at': NOW.timestamp(), 'state': 'pending'} for i in range(1, 52)}
            journal.save()
            client = FakeClient(); client.owned_packages = {51}
            run_workflow(client, {'schema_version': 1, 'candidates': []}, 'US', journal, now=lambda: NOW)
            self.assertEqual(Journal(journal.path, STEAM_ID).entries['51']['state'], 'confirmed')
            self.assertEqual(client.posts, [])

    def test_product_tree_duplicate_optional_key_is_invalid(self):
        from platforms.steam.ipc import validate_tree
        with self.assertRaises(SteamError):
            validate_tree(node('123', children=[node('extended'), node('extended')]))


if __name__ == '__main__':
    unittest.main()
