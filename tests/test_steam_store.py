"""Current official catalog fixtures: no Steam accounts or external requests."""
import copy
from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from common.model import validate
from platforms.steam import adapter
from platforms.steam.candidates import eligibility
from platforms.steam.ipc import SteamError
from platforms.steam.store_discovery import CatalogClient, SearchResults, discover_current
from platforms.steam.workflow import Journal, run_workflow
from test_steam_e2e import FixtureService, STEAM_ID, HTML

NOW = datetime(2026, 10, 9, 7, tzinfo=timezone.utc)


def search_html(ids=(456,), total=None):
    total = len(ids) if total is None else total
    return f'<div class="search_results_count">{total} results match your search.</div><div id="search_result_container">' + ''.join(
        f'<a class="search_result_row ds_collapse_flag" data-ds-appid="{aid}" href="https://store.steampowered.com/app/{aid}/Test/"></a>'
        for aid in ids) + '</div>'


class OfficialFixture(CatalogClient):
    """Reconstructed public protocol, including promotional is_free=true."""
    def __init__(self, **options):
        super().__init__(**options)
        self.urls = []
        self.html = HTML
        self.search_html = search_html()
        self.fail = None
        self.item = {'item_type': 0, 'id': 456, 'appid': 456, 'success': 1, 'visible': True,
            'is_free': True, 'is_free_temporarily': True, 'best_purchase_option': {
                'packageid': 123, 'final_price_in_cents': '0', 'original_price_in_cents': '2200',
                'discount_pct': 100, 'is_free_to_keep': True, 'included_game_count': 1,
                'free_to_keep_ends': int((NOW + timedelta(days=3)).timestamp()), 'free_to_keep_base_package': 99}}
        self.package = {'name': 'Test promotional package', 'apps': [{'id': 456, 'name': 'Test game'}]}
        # Overall final price can be nonzero during a real FTK promotion; use the
        # selected purchase option plus its explicit free-license sub instead.
        self.app = {'steam_appid': 456, 'type': 'game', 'name': 'Test game', 'is_free': True,
            'price_overview': {'currency': 'CNY', 'initial': 2200, 'final': 2200, 'discount_percent': 100},
            'package_groups': [{'subs': [{'packageid': 123, 'is_free_license': True,
                                         'price_in_cents_with_discount': 0}]}]}

    def get(self, url, json_response=False):
        if self.fail:
            raise SteamError(self.fail)
        self.urls.append(url)
        parsed = urlsplit(url)
        if parsed.path == '/search/':
            return self.search_html
        if 'IStoreBrowseService' in parsed.path:
            return {'response': {'store_items': [copy.deepcopy(self.item)]}}
        if parsed.path == '/api/packagedetails/':
            return {'123': {'success': True, 'data': copy.deepcopy(self.package)}}
        if parsed.path == '/api/appdetails/':
            return {'456': {'success': True, 'data': copy.deepcopy(self.app)}}
        raise AssertionError(parsed.path)

    def page(self, app_id, region):
        self.urls.append(f'https://store.steampowered.com/app/{app_id}/?cc={region}&l=english')
        return self.html


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.store = OfficialFixture()

    def offer(self):
        return self.store.current_offer(456, 'CN', NOW)

    def test_regional_official_evidence_and_exact_epoch(self):
        row = self.offer()
        self.assertIsNone(eligibility(row, 'CN', NOW))
        self.assertEqual(row['package_id'], 123)
        self.assertEqual(row['app_ids'], [456])
        self.assertEqual(row['ends_at'], (NOW + timedelta(days=3)).isoformat())
        self.assertEqual(row['evidence']['package_url'], 'https://store.steampowered.com/sub/123/')
        for url in self.store.urls:
            parsed = urlsplit(url)
            self.assertIn(parsed.hostname, {'api.steampowered.com', 'store.steampowered.com'})
            query = parse_qs(parsed.query)
            if 'input_json' in query:
                self.assertEqual(json.loads(query['input_json'][0])['context']['country_code'], 'CN')
            else:
                self.assertEqual(query['cc'], ['CN'])

    def test_f2p_and_weekend_are_excluded_despite_free_price(self):
        for field, value in [('is_free_to_keep', False), ('is_free_to_keep', None)]:
            self.store.item['best_purchase_option'][field] = value
            self.assertIsNone(self.offer())
        self.store.item['best_purchase_option']['is_free_to_keep'] = True
        self.store.item['is_free_temporarily'] = False
        self.assertIsNone(self.offer())

    def test_missing_expiry_or_price_and_package_disagreement_are_held(self):
        for field, value in [('free_to_keep_ends', None), ('free_to_keep_ends', True),
                             ('final_price_in_cents', 1), ('original_price_in_cents', '0'),
                             ('discount_pct', 99), ('included_game_count', 2), ('packageid', 124)]:
            with self.subTest(field=field):
                original = self.store.item['best_purchase_option'][field]
                self.store.item['best_purchase_option'][field] = value
                with self.assertRaises(SteamError):
                    self.offer()
                self.store.item['best_purchase_option'][field] = original
        self.store.package['apps'][0]['id'] = 457
        with self.assertRaises(SteamError):
            self.offer()

    def test_expired_offer_and_non_game_are_excluded(self):
        self.store.app['type'] = 'dlc'
        self.assertIsNone(self.offer())
        self.store.app['type'] = 'game'
        self.store.item['best_purchase_option']['free_to_keep_ends'] = int(NOW.timestamp())
        self.assertIsNone(self.offer())

    def test_official_text_and_free_action_must_agree_with_package(self):
        for html in [HTML.replace('Free to keep', 'Play for free'), HTML.replace('value="123"', 'value="124"')]:
            self.store.html = html
            with self.assertRaises(SteamError):
                self.offer()

    def test_wrong_identity_or_malformed_api_not_empty_success(self):
        for field, value in [('appid', 457), ('id', True), ('item_type', False), ('success', True), ('visible', False)]:
            with self.subTest(field=field):
                original = self.store.item[field]; self.store.item[field] = value
                with self.assertRaises(SteamError):
                    self.offer()
                self.store.item[field] = original
        with patch.object(self.store, 'get', return_value={'response': []}):
            with self.assertRaises(SteamError):
                self.offer()

    def test_search_schema_does_not_turn_errors_into_zero_giveaways(self):
        for html in ['<html>Sign in</html>', search_html().replace('456/Test/', '457/Test/'),
                     search_html((456, 456)), search_html().replace('data-ds-appid="456"', '')]:
            parser = SearchResults()
            with self.assertRaises(SteamError):
                parser.feed(html); parser.result()
        parser = SearchResults(); parser.feed(search_html((), 0))
        self.assertEqual(parser.result(), {'app_ids': [], 'total': 0, 'other_rows': 0})

    def test_discovery_errors_and_coverage_bounds_visible(self):
        manifest, report = discover_current(self.store, 'CN', now=lambda: NOW)
        self.assertEqual(len(manifest['candidates']), 1)
        self.assertFalse(report['coverage_incomplete'])
        self.store.search_html = search_html((456, 457), 2)
        _, report = discover_current(self.store, 'CN', max_candidates=1, now=lambda: NOW)
        self.assertTrue(report['coverage_incomplete'])
        self.store.search_html = search_html(); self.store.html = '<html>Unavailable</html>'
        _, report = discover_current(self.store, 'CN', now=lambda: NOW)
        self.assertEqual(report['rejected'][0]['reason'], 'official_free_to_keep_evidence_missing')
        self.store.fail = 'store_rate_limited'
        with self.assertRaises(SteamError):
            discover_current(self.store, 'CN', now=lambda: NOW)

    def test_catalog_pagination_tracks_all_advertised_rows(self):
        with patch.object(self.store, 'search', side_effect=[
                {'app_ids': [456], 'total': 3, 'other_rows': 0},
                {'app_ids': [457], 'total': 3, 'other_rows': 1}]) as search, \
                patch.object(self.store, 'current_offer', return_value=None):
            _, report = discover_current(self.store, 'CN', now=lambda: NOW)
        self.assertFalse(report['coverage_incomplete'])
        self.assertEqual(search.call_count, 2)

    def test_verifier_binds_current_package_and_deadline(self):
        row = self.offer()
        self.assertIsNone(self.store.verify(row, 'CN', NOW))
        self.store.item['best_purchase_option']['free_to_keep_ends'] += 60
        self.assertEqual(self.store.verify(row, 'CN', NOW), 'promotion_changed')
        self.store.item['best_purchase_option']['is_free_to_keep'] = False
        self.assertEqual(self.store.verify(row, 'CN', NOW), 'promotion_no_longer_available')

    def test_http_429_never_retries_or_sends_authentication(self):
        client = CatalogClient()
        def limited(request, timeout):
            self.assertNotIn('Authentication', request.headers)
            self.assertNotIn('Cookie', request.headers)
            raise HTTPError(request.full_url, 429, 'limited', {}, io.BytesIO())
        with patch.object(client.opener, 'open', side_effect=limited) as opened:
            with self.assertRaisesRegex(SteamError, 'store_rate_limited'):
                client.search('CN')
        self.assertEqual(opened.call_count, 1)


class StoreAdapterTests(unittest.TestCase):
    def setUp(self):
        self.service = FixtureService()
        self.wait = patch('platforms.steam.workflow.time.sleep'); self.wait.start(); self.addCleanup(self.wait.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = OfficialFixture()
        self.store.item['best_purchase_option']['free_to_keep_ends'] = int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
        self.settings = self.root / 'config.json'
        self.config = {'ipc_url': self.service.url, 'ipc_password': 'fixture-only-password',
                       'bot': 'Bot1', 'steam_id': STEAM_ID, 'region': 'CN'}
        self.state = self.root / 'state/steam/account1'; self.state.mkdir(parents=True)
        self.shared = self.state.parent / '_steam_ids'; self.shared.mkdir()
        self.old_discovery = self.shared / (STEAM_ID + '.discovery.json')
        self.old_discovery.write_text('old historical queue, not a current catalog')
        self.counter = 0

    def tearDown(self):
        self.service.close(); self.tmp.cleanup()

    def run_adapter(self, claim=True):
        self.settings.write_text(json.dumps(self.config)); self.settings.chmod(0o600)
        self.counter += 1; target = self.root / f'result-{self.counter}.json'
        context = {'run_id': f'fixture-{self.counter}', 'platform': 'steam', 'account': 'account1', 'business_date': '2026-10-09'}
        env = {'BENEFITS_' + k.upper(): v for k, v in context.items()}
        env.update(STEAM_CONFIG=str(self.settings), BENEFITS_RESULT_PATH=str(target), BENEFITS_STATE_DIR=str(self.state))
        with patch.dict(os.environ, env), patch.object(adapter, 'CatalogClient', return_value=self.store), \
                patch('sys.argv', ['adapter.py'] + (['--claim'] if claim else [])):
            adapter.main()
        raw = target.read_text(); self.assertNotIn('fixture-only-password', raw)
        out = json.loads(raw); validate(out, context)
        self.assertEqual(self.old_discovery.read_text(), 'old historical queue, not a current catalog')
        self.assertFalse(any('GetProductInfo' in path or 'GetChangesSince' in path for _, path, _ in self.service.requests))
        return out

    def test_default_store_claim_and_owned_readback_and_idempotence(self):
        out = self.run_adapter()
        self.assertEqual(out['business'], {'claim': 'complete', 'discovery': 'complete'})
        self.assertEqual(self.service.posts, [123])
        self.assertEqual(out['details']['items'][0]['reason'], 'claimed_package_verified')
        self.assertEqual(out['details']['items'][-1]['reason'], 'current_catalog_verified')
        self.assertEqual(self.run_adapter()['business']['claim'], 'complete')
        self.assertEqual(self.service.posts, [123])

    def test_owned_base_game_skips_duplicate_promotion(self):
        self.service.owned.add(99)
        self.assertEqual(self.run_adapter()['business']['claim'], 'complete')
        self.assertEqual(self.service.posts, [])

    def test_delayed_owned_readback_confirms_with_only_one_post(self):
        self.service.grant = False
        def grant_after_wait(_):
            self.service.owned.add(123)
        with patch('platforms.steam.workflow.time.sleep', side_effect=grant_after_wait) as waited:
            out = self.run_adapter()
        self.assertEqual(waited.call_count, 1)
        self.assertEqual(out['business']['claim'], 'complete')
        self.assertEqual(out['details']['items'][0]['reason'], 'claimed_package_verified')
        self.assertEqual(self.service.posts, [123])

    def test_fresh_promotion_check_before_intent_can_stop_claim(self):
        with patch.object(self.store, 'verify', side_effect=[None, 'promotion_changed']) as verified:
            out = self.run_adapter()
        self.assertEqual(verified.call_count, 2)
        self.assertEqual(out['details']['items'][0]['reason'], 'promotion_changed')
        self.assertEqual(self.service.posts, [])
        self.assertFalse((self.shared / (STEAM_ID + '.json')).exists())

    def test_missing_verifier_cannot_bypass_package_proof(self):
        row = self.store.current_offer(456, 'CN', datetime.now(timezone.utc))
        journal = Journal(self.shared / (STEAM_ID + '.json'), STEAM_ID)
        client = adapter.Client(self.service.url, 'fixture-only-password', 'Bot1', STEAM_ID)
        out = run_workflow(client, {'schema_version': 1, 'candidates': [row]}, 'CN', journal, claim=True)
        self.assertEqual(out['details']['items'][0]['reason'], 'official_store_verifier_required')
        self.assertEqual(self.service.posts, [])

    def test_uncertain_post_is_not_repeated_and_recovers_before_source_failure(self):
        self.service.grant = False; self.service.response_lost = True
        self.assertEqual(self.run_adapter()['business']['claim'], 'unknown')
        self.service.owned.add(99)  # Owning the base cannot confirm a pending POST.
        self.assertEqual(self.run_adapter()['business']['claim'], 'unknown')
        self.assertEqual(self.service.posts, [123])
        self.service.owned.add(123); self.store.fail = 'store_unavailable'
        out = self.run_adapter()
        self.assertEqual(out['execution_status'], 'failed')
        self.assertEqual(out['business']['claim'], 'complete')
        self.assertEqual(out['business']['discovery'], 'unknown')
        self.assertEqual(out['details']['items'][0]['reason'], 'previous_submission_owned_verified')
        self.assertEqual(self.service.posts, [123])

    def test_source_failure_never_reports_no_candidates(self):
        self.store.fail = 'store_unavailable'
        out = self.run_adapter()
        self.assertEqual(out['execution_status'], 'failed')
        self.assertEqual(out['business']['discovery'], 'unknown')
        self.assertEqual(self.service.posts, [])

    def test_valid_empty_catalog_is_complete_scoped_noop(self):
        self.store.search_html = search_html((), 0)
        out = self.run_adapter()
        self.assertEqual(out['business'], {'claim': 'not_applicable', 'discovery': 'complete'})
        self.assertEqual(out['reason'], 'no_candidates')
        self.assertEqual(self.service.posts, [])

    def test_manual_manifest_cannot_spoof_automatic_proof(self):
        row = self.store.current_offer(456, 'CN', datetime.now(timezone.utc))
        path = self.root / 'manifest.json'
        path.write_text(json.dumps({'schema_version': 1, 'candidates': [row]})); path.chmod(0o600)
        self.config['candidates_path'] = str(path)
        self.assertEqual(self.run_adapter()['reason'], 'reserved_automatic_evidence_method')
        self.assertEqual(self.service.posts, [])

    def test_invalid_source_or_limit_rejected(self):
        for discovery in [{'source': 'other'}, {'source': []}, {'source': 'store', 'max_candidates': 0},
                          {'source': 'store', 'max_candidates': True}]:
            with self.subTest(discovery=discovery):
                self.config['discovery'] = discovery
                self.assertEqual(self.run_adapter()['reason'], 'invalid_discovery_config')
                self.assertEqual(self.service.posts, [])


if __name__ == '__main__':
    unittest.main()
