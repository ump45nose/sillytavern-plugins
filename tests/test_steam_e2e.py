"""Local HTTP fixtures only. No Steam account, login, or external requests."""
import contextlib
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request
from platforms.steam import adapter
from platforms.steam.discovery import StoreClient, official_offer, discover
from platforms.steam.ipc import Client, SteamError
from common.model import validate

STEAM_ID = '76561198000000001'


def node(name, value=None, children=None):
    return {'Name': name, 'Value': value, 'Children': children or []}


# Minimal contract fixture reconstructed from a real historical purchase block:
# moonstar-x/free-games-crawler commit2322f553, test/crawlers/__mocks__/steam_page_game.txt.
# No historical session IDs or other user data are copied.
HTML = '''<div class="game_area_purchase_game">
<form action="https://store.steampowered.com/freelicense/addfreelicense/" method="POST">
<input type="hidden" name="subid" value="123"></form>
<p class="game_purchase_discount_quantity">Free to keep when you get it before 7 Oct @ 10:00am.</p>
<div class="game_purchase_action"><a href="javascript:addToCart(123)">Add to Account</a></div></div>'''


class FixtureService:
    def __init__(self):
        self.owned = set()
        self.posts = []
        self.requests = []
        self.authenticated = True
        self.changed = True
        self.grant = True
        self.detail = 0
        self.response_lost = False
        self.app_type = 'Game'
        self.html = HTML
        self.end = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        self.billing = '0'
        self.full_update = False
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                u = urlsplit(self.path)
                query = parse_qs(u.query)
                service.requests.append((self.command, u.path, query))
                if u.path.startswith('/store/'):
                    if self.headers.get('Authentication') is not None:
                        raise AssertionError('ASF password leaked to store')
                    self.send_response(200); self.end_headers(); self.wfile.write(service.html.encode()); return
                if self.headers.get('Authentication') != 'fixture-only-password' or not service.authenticated:
                    self.send_response(401); self.end_headers(); return
                if u.path == '/Api/Bot/Bot1':
                    data = {'Bot1': {'IsConnectedAndLoggedOn': True, 's_SteamID': STEAM_ID}}
                elif '/GetChangesSince/' in u.path:
                    data = {'CurrentChangeNumber': 100, 'RequiresFullUpdate': service.full_update,
                            'RequiresFullPackageUpdate': False,
                            'PackageChanges': {'123': {'ID': 123, 'ChangeNumber': 100, 'NeedsToken': False}} if service.changed else {}}
                elif u.path.endswith('/GetOwnedPackages'):
                    data = sorted(service.owned)
                elif u.path.endswith('/GetProductInfo'):
                    if 'packageIDs' in query:
                        tree = node('123', children=[node('billingtype', service.billing), node('licensetype', '1'),
                            node('status', '0'), node('appids', children=[node('0', '456')]),
                            node('extended', children=[node('expirytime', str(service.end))])])
                        data = [{'Packages': {'123': {'ID': 123, 'MissingToken': False, 'KeyValues': tree}}}]
                    else:
                        tree = node('appinfo', children=[node('appid', '456'), node('common', children=[node('type', service.app_type)])])
                        data = [{'Apps': {'456': {'ID': 456, 'MissingToken': False, 'KeyValues': tree}}}]
                elif u.path.endswith('/RequestFreeSubLicense') and self.command == 'POST':
                    pid = int(query['subID'][0])
                    service.posts.append(pid)
                    if service.grant:
                        service.owned.add(pid)
                    if service.response_lost:
                        self.connection.close(); return
                    data = {'Result': 1, 'PurchaseResultDetail': service.detail}
                else:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'Success': True, 'Message': 'OK', 'Result': data}).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def store(self):
        store = StoreClient()
        original = store.opener.open
        base = self.url
        # Test-only transport mapping; the production client has no endpoint
        # override or switch for insecure remote Steam pages.
        def local(request, timeout):
            u = urlsplit(request.full_url)
            assert u.hostname == 'store.steampowered.com'
            return original(Request(base + '/store/' + u.path.lstrip('/') + '?' + u.query,
                                    headers={'Accept': 'text/html'}), timeout=timeout)
        store.opener.open = local
        return store


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.service = FixtureService()
        sleep = patch('platforms.steam.workflow.time.sleep'); sleep.start(); self.addCleanup(sleep.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = self.root / 'config.json'
        self.settings.write_text(json.dumps({'ipc_url': self.service.url, 'ipc_password': 'fixture-only-password',
            'bot': 'Bot1', 'steam_id': STEAM_ID, 'region': 'US', 'discovery': {'source': 'pics'}}))
        self.settings.chmod(0o600)
        self.state = self.root / 'state' / 'steam' / 'account1'
        self.state.mkdir(parents=True)
        self.counter = 0

    def tearDown(self):
        self.service.close(); self.tmp.cleanup()

    def run_adapter(self, claim=True):
        self.counter += 1
        target = self.root / f'result-{self.counter}.json'
        context = {'run_id': f'fixture-{self.counter}', 'platform': 'steam', 'account': 'account1', 'business_date': '2026-10-06'}
        env = {'BENEFITS_' + k.upper(): v for k, v in context.items()}
        env.update(STEAM_CONFIG=str(self.settings), BENEFITS_RESULT_PATH=str(target), BENEFITS_STATE_DIR=str(self.state))
        with patch.dict(os.environ, env), patch.object(adapter, 'StoreClient', self.service.store), patch('sys.argv', ['adapter.py'] + (['--claim'] if claim else [])):
            adapter.main()
        raw = target.read_text()
        self.assertNotIn('fixture-only-password', raw)
        out = json.loads(raw)
        validate(out, context)
        return out

    def test_real_launcher_end_to_end_with_test_only_transport(self):
        # Production run.py, lifecycle supervisor, account lock, adapter, journal,
        # and atomic result paths all run. Only public store transport is mapped
        # to our loopback fixture by a temporary test interpreter shim.
        shim = self.root / 'fixture-python'
        repo = str(Path(__file__).resolve().parents[1])
        shim.write_text('#!' + sys.executable + '\n' + f"""
import sys, os, json
sys.path.insert(0, {repo!r})
from urllib.request import Request
from urllib.parse import urlsplit
from platforms.steam import adapter
from platforms.steam.discovery import StoreClient
from unittest.mock import patch
base = json.load(open(os.environ['STEAM_CONFIG']))['ipc_url']
def store():
    client = StoreClient()
    original = client.opener.open
    def local(request, timeout):
        u = urlsplit(request.full_url)
        assert u.hostname == 'store.steampowered.com'
        return original(Request(base + '/store/' + u.path.lstrip('/') + '?' + u.query), timeout=timeout)
    client.opener.open = local
    return client
with patch.object(adapter, 'StoreClient', store):
    adapter.main()
""")
        shim.chmod(0o700)
        env = dict(os.environ, STEAM_CONFIG=str(self.settings))
        proc = subprocess.run([sys.executable, 'platforms/steam/run.py', '--runtime-root', str(self.root),
                               '--account', 'account1', '--execute', '--claim', '--python', str(shim)],
                              env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out['business'], {'claim': 'complete', 'discovery': 'complete'})
        self.assertEqual(self.service.posts, [123])
        self.assertEqual(out, json.loads((self.root / 'results/steam/account1/latest.json').read_text()))
        self.assertEqual(out, json.loads((self.root / 'runs' / out['run_id'] / 'result.json').read_text()))
        self.assertNotIn('fixture-only-password', proc.stdout + proc.stderr)

    def test_discover_filter_claim_verify_result_and_idempotent_rerun(self):
        out = self.run_adapter()
        self.assertEqual(out['business'], {'claim': 'complete', 'discovery': 'complete'})
        self.assertEqual(self.service.posts, [123])
        self.assertEqual(out['details']['items'][0]['reason'], 'claimed_package_verified')
        self.assertEqual(self.run_adapter()['business']['claim'], 'not_applicable')
        self.assertEqual(self.service.posts, [123])
        self.assertTrue(any(path.endswith('GetChangesSince/0') for _, path, _ in self.service.requests))

    def test_dry_run_discovers_without_post(self):
        out = self.run_adapter(claim=False)
        self.assertEqual(out['details']['items'][0]['reason'], 'dry_run_eligible')
        self.assertEqual(self.service.posts, [])

    def test_no_candidates_is_normal_noop(self):
        self.service.changed = False
        out = self.run_adapter()
        self.assertEqual(out['reason'], 'no_candidates')
        self.assertEqual(out['business'], {'claim': 'not_applicable', 'discovery': 'complete'})
        self.assertEqual(self.service.posts, [])

    def test_uncertain_post_not_repeated_after_restart_or_expiry(self):
        self.service.grant = False; self.service.response_lost = True
        self.assertEqual(self.run_adapter()['business']['claim'], 'unknown')
        self.assertEqual(self.run_adapter()['business']['claim'], 'unknown')
        self.assertEqual(self.service.posts, [123])
        self.service.owned.add(123); self.service.end = 1; self.service.changed = False
        out = self.run_adapter()
        self.assertEqual(out['business']['claim'], 'complete')
        self.assertEqual(out['details']['items'][0]['reason'], 'previous_submission_owned_verified')
        self.assertEqual(self.service.posts, [123])

    def test_lost_post_response_with_ownership_is_verified(self):
        self.service.response_lost = True
        self.assertEqual(self.run_adapter()['business']['claim'], 'complete')
        self.assertEqual(self.service.posts, [123])

    def test_authentication_error_stops_once(self):
        self.service.authenticated = False
        out = self.run_adapter()
        self.assertEqual(out['reason'], 'ipc_authentication_failed')
        self.assertEqual(len(self.service.requests), 1)
        self.assertEqual(self.service.posts, [])

    def test_demo_beta_dlc_missing_permanent_evidence_are_held(self):
        for app_type in ['Demo', 'Beta', 'DLC']:
            self.service.app_type = app_type
            out = self.run_adapter()
            self.assertEqual(out['business'], {'claim': 'not_applicable', 'discovery': 'complete'})
            self.assertEqual(self.service.posts, [])
        self.service.app_type = 'Game'; self.service.html = HTML.replace('Free to keep when you get it before', 'Play for free until')
        out = self.run_adapter()
        self.assertEqual(out['details']['items'][0]['reason'], 'official_free_to_keep_evidence_missing')
        self.assertEqual(self.service.posts, [])

    def test_pics_coverage_gaps_are_visible(self):
        self.service.full_update = True
        out = self.run_adapter(claim=False)
        self.assertEqual(out['business']['discovery'], 'unknown')
        self.assertEqual(out['reason'], 'discovery_coverage_incomplete')

    def test_recovery_merge_is_bounded_instead_of_io_failure(self):
        from platforms.steam.workflow import Journal
        shared = self.state.parent / '_steam_ids'; shared.mkdir()
        journal = Journal(shared / (STEAM_ID + '.json'), STEAM_ID)
        journal.entries = {'1': {'attempted_at': datetime.now(timezone.utc).timestamp(), 'state': 'pending'}}
        journal.save()
        manifest = self.root / 'manifest.json'; manifest.write_text('{"schema_version":1,"candidates":[]}'); manifest.chmod(0o600)
        settings = json.loads(self.settings.read_text()); settings['candidates_path'] = str(manifest)
        settings.pop('discovery', None)
        self.settings.write_text(json.dumps(settings))
        def payload(start, end):
            return {'execution': 'ok', 'reason': 'claims_verified', 'business': {'claim': 'complete'},
                    'details': {'metrics': {}, 'items': [{'id': f'sub/{n}', 'name': 'Fixture',
                              'status': 'complete', 'reason': 'owned_package_verified'} for n in range(start, end)]}}
        with patch.object(adapter, 'run_workflow', side_effect=[payload(1, 51), payload(51, 151)]):
            out = self.run_adapter()
        self.assertEqual(out['execution_status'], 'ok')
        self.assertEqual(out['reason'], 'result_items_truncated')
        self.assertEqual(out['business']['claim'], 'unknown')
        self.assertEqual(len(out['details']['items']), 100)
        self.assertEqual(out['details']['metrics']['omitted_items']['current'], 50)

    def test_rate_limit_saved_across_restarts(self):
        self.service.detail = 53; self.service.grant = False
        self.assertEqual(self.run_adapter()['business']['claim'], 'unknown')
        journal = json.loads((self.state.parent / '_steam_ids' / (STEAM_ID + '.json')).read_text())
        self.assertGreater(journal['blocked_until'], datetime.now(timezone.utc).timestamp())
        self.run_adapter()
        self.assertEqual(self.service.posts, [123])


class ParserTests(unittest.TestCase):
    def test_known_real_form_contract(self):
        self.assertTrue(official_offer(HTML, 123))
        self.assertFalse(official_offer(HTML, 124))
        self.assertTrue(official_offer(HTML.replace('/freelicense/addfreelicense/', '/checkout/addfreelicense/'), 123))

    def test_unrelated_text_does_not_prove_offer(self):
        self.assertFalse(official_offer('<p>Free to keep when you get it before tomorrow</p><div class="game_area_purchase_game"><a href="javascript:AddFreeLicense(123)">Free</a></div>', 123))
        self.assertFalse(official_offer(HTML.replace('game_area_purchase_game', 'user_review'), 123))
        self.assertFalse(official_offer(HTML.replace('store.steampowered.com/freelicense', 'evil.example/freelicense'), 123))


class DiscoveryQueueTests(unittest.TestCase):
    def test_capped_batch_advances_and_retains_eligible_for_later_claim(self):
        from platforms.steam.discovery import DiscoveryState
        class IPC:
            def __init__(self):
                self.cursors, self.seen = [], []
            def changes(self, cursor):
                self.cursors.append(cursor)
                return {'CurrentChangeNumber': 100, 'RequiresFullUpdate': False, 'RequiresFullPackageUpdate': False,
                        'PackageChanges': ({str(n): {'ID': n, 'ChangeNumber': n, 'NeedsToken': False} for n in range(1, 4)} if cursor == 0 else {})}
            def package(self, pid):
                self.seen.append(pid)
                return node(str(pid), children=[node('billingtype', '1')])
        with tempfile.TemporaryDirectory() as directory:
            state = DiscoveryState(Path(directory) / 'discovery.json')
            ipc = IPC()
            for _ in range(3):
                discover(ipc, None, 'US', state=state, max_packages=1)
                state = DiscoveryState(state.path)
            self.assertEqual(ipc.seen, [1, 2, 3])
            self.assertEqual(ipc.cursors, [0, 100, 100])
            self.assertEqual(state.queue, [])


if __name__ == '__main__':
    unittest.main()
