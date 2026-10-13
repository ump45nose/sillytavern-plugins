"""Current regional Steam giveaways, verified against public official sources."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from .discovery import StoreClient, official_offer
from .candidates import CATALOG_EVIDENCE_METHOD
from .ipc import SteamError

EVIDENCE_METHOD = CATALOG_EVIDENCE_METHOD
MAX_CANDIDATES = 50
MAX_BYTES = 2 * 1024 * 1024


def integer(value, positive=False):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value):
        value = int(value)
    if type(value) is not int or not (1 if positive else 0) <= value < 1e12:
        raise SteamError('store_metadata_unverified')
    return value


class SearchResults(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.app_ids = []
        self.container_seen = False
        self.count_text = []
        self.count_depth = 0
        self.other_rows = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get('class') or '').split())
        if a.get('id') in {'search_results', 'search_resultsRows', 'search_result_container'}:
            self.container_seen = True
        if tag == 'div':
            if self.count_depth:
                self.count_depth += 1
            elif 'search_results_count' in classes:
                self.count_depth = 1
        if tag != 'a' or 'search_result_row' not in classes:
            return
        raw = a.get('data-ds-appid', '')
        if not re.fullmatch(r'[1-9][0-9]{0,9}', raw):
            # Bundles are outside the single-game discovery scope. An unknown
            # row must not silently become an excluded product.
            if re.fullmatch(r'[1-9][0-9]{0,9}', a.get('data-ds-bundleid', '')):
                self.other_rows += 1
                return
            raise SteamError('catalog_identity_unverified')
        u = urlsplit(a.get('href', ''))
        if (u.scheme != 'https' or u.hostname != 'store.steampowered.com'
                or u.username or u.password or u.port not in (None, 443)
                or not re.match(r'^/app/' + raw + r'(?:/|$)', u.path)):
            raise SteamError('catalog_identity_unverified')
        app_id = int(raw)
        if app_id in self.app_ids or app_id >= 2**32:
            raise SteamError('catalog_identity_unverified')
        self.app_ids.append(app_id)

    def handle_endtag(self, tag):
        if tag == 'div' and self.count_depth:
            self.count_depth -= 1

    def handle_data(self, data):
        if self.count_depth:
            self.count_text.append(data)

    def result(self):
        matches = re.findall(r'([0-9][0-9,]*) results? match(?:es)? your search',
                             ' '.join(self.count_text), re.IGNORECASE)
        if not self.container_seen or len(matches) != 1:
            raise SteamError('catalog_schema_unverified')
        total = int(matches[0].replace(',', ''))
        if total < len(self.app_ids) + self.other_rows:
            raise SteamError('catalog_schema_unverified')
        return {'app_ids': self.app_ids, 'total': total, 'other_rows': self.other_rows}


class CatalogClient(StoreClient):
    def get(self, url, json_response=False):
        u = urlsplit(url)
        if (u.scheme != 'https' or u.hostname not in {'store.steampowered.com', 'api.steampowered.com'}
                or u.username or u.password or u.port not in (None, 443)):
            raise SteamError('invalid_store_endpoint')
        for attempt in range(2):
            try:
                request = Request(url, headers={'Accept': 'application/json' if json_response else 'text/html'})
                with self.opener.open(request, timeout=10) as response:
                    raw = response.read(MAX_BYTES + 1)
                break
            except HTTPError as error:
                if error.code == 429:
                    raise SteamError('store_rate_limited') from None
                if error.code not in {500, 502, 503, 504} or attempt:
                    raise SteamError('store_unavailable') from None
            except (URLError, OSError, TimeoutError, HTTPException):
                if attempt:
                    raise SteamError('store_unavailable') from None
            time.sleep(0.3)
        if len(raw) > MAX_BYTES:
            raise SteamError('store_response_too_large')
        try:
            return json.loads(raw) if json_response else raw.decode('utf-8', errors='strict')
        except (ValueError, UnicodeError):
            raise SteamError('store_invalid_response') from None

    def search(self, region, start=0):
        query = urlencode({'maxprice': 'free', 'specials': '1', 'category1': '998',
                           'cc': region, 'l': 'english', 'count': MAX_CANDIDATES, 'start': start})
        parser = SearchResults()
        parser.feed(self.get('https://store.steampowered.com/search/?' + query))
        parser.close()
        return parser.result()

    def details(self, kind, item_id, region):
        query = urlencode({kind + 'ids': item_id, 'cc': region, 'l': 'english'})
        data = self.get(f'https://store.steampowered.com/api/{kind}details/?' + query, True)
        row = data.get(str(item_id)) if isinstance(data, dict) else None
        if not isinstance(row, dict) or row.get('success') is not True or not isinstance(row.get('data'), dict):
            raise SteamError('store_metadata_unavailable')
        return row['data']

    def browse(self, app_id, region):
        payload = {'ids': [{'appid': app_id}], 'context': {'country_code': region, 'language': 'english'},
                   'data_request': {'include_purchase_options': True}}
        query = urlencode({'input_json': json.dumps(payload, separators=(',', ':'))})
        data = self.get('https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?' + query, True)
        response = data.get('response') if isinstance(data, dict) else None
        rows = response.get('store_items') if isinstance(response, dict) else None
        if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
                or type(rows[0].get('appid')) is not int or rows[0]['appid'] != app_id
                or type(rows[0].get('item_type')) is not int or rows[0]['item_type'] != 0
                or type(rows[0].get('id')) is not int or rows[0]['id'] != app_id
                or type(rows[0].get('success')) is not int or rows[0]['success'] != 1
                or rows[0].get('visible') is not True):
            raise SteamError('store_item_identity_unverified')
        return rows[0]

    def current_offer(self, app_id, region, now):
        item = self.browse(app_id, region)
        option = item.get('best_purchase_option')
        if not isinstance(option, dict):
            raise SteamError('store_purchase_option_unverified')
        if option.get('is_free_to_keep') is not True or item.get('is_free_temporarily') is not True:
            # Explicitly not a current permanent giveaway, rather than unknown metadata.
            return None
        pid = integer(option.get('packageid'), True)
        end_epoch = integer(option.get('free_to_keep_ends'), True)
        if pid >= 2**32 or end_epoch >= 253402300799:
            raise SteamError('store_metadata_unverified')
        end = datetime.fromtimestamp(end_epoch, timezone.utc)
        if now >= end:
            return None
        if (integer(option.get('final_price_in_cents')) != 0
                or integer(option.get('original_price_in_cents'), True) <= 0
                or type(option.get('discount_pct')) is not int or option['discount_pct'] != 100):
            raise SteamError('price_evidence_unverified')
        package = self.details('package', pid, region)
        apps = package.get('apps')
        if (not isinstance(apps, list) or not 1 <= len(apps) <= 5
                or any(not isinstance(a, dict) or type(a.get('id')) is not int
                       or not 0 < a['id'] < 2**32 for a in apps)):
            raise SteamError('package_contents_unverified')
        app_ids = [a['id'] for a in apps]
        if (len(set(app_ids)) != len(app_ids) or app_id not in app_ids
                or integer(option.get('included_game_count'), True) != len(app_ids)):
            raise SteamError('package_contents_changed')
        main = None
        for aid in app_ids:
            info = self.details('app', aid, region)
            if info.get('steam_appid') != aid or type(info.get('steam_appid')) is not int:
                raise SteamError('app_metadata_mismatch')
            if info.get('type') != 'game':
                return None
            if aid == app_id:
                main = info
        name = main.get('name')
        if not isinstance(name, str) or not 0 < len(name) <= 200 or any(ord(c) < 32 for c in name):
            raise SteamError('invalid_candidate_name')
        groups = main.get('package_groups')
        if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('subs'), list) for g in groups):
            raise SteamError('store_purchase_option_unverified')
        subs = [sub for g in groups for sub in g['subs']
                if isinstance(sub, dict) and type(sub.get('packageid')) is int and sub['packageid'] == pid]
        if (len(subs) != 1 or subs[0].get('is_free_license') is not True
                or integer(subs[0].get('price_in_cents_with_discount')) != 0):
            raise SteamError('store_license_price_unverified')
        prices = main.get('price_overview')
        currency = prices.get('currency') if isinstance(prices, dict) else None
        if not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
            raise SteamError('price_evidence_unverified')
        if not official_offer(self.page(app_id, region), pid):
            raise SteamError('official_free_to_keep_evidence_missing')
        base = option.get('free_to_keep_base_package')
        if base is not None and (type(base) is not int or not 0 < base < 2**32):
            raise SteamError('store_metadata_unverified')
        url = f'https://store.steampowered.com/app/{app_id}/'
        return {'package_id': pid, 'app_ids': app_ids, 'store_app_id': app_id,
                'store_base_package_id': base, 'name': name,
                'promotion_kind': 'limited_time_free_to_keep', 'permanent_license': True,
                'free_to_play': False, 'free_weekend': False, 'demo': False, 'playtest': False,
                'product_type': 'game', 'price_minor': 0,
                'regular_price_minor': integer(option['original_price_in_cents'], True),
                'currency': currency, 'allowed_regions': [region],
                'starts_at': now.isoformat(), 'ends_at': end.isoformat(),
                'evidence': {'reviewed': True, 'method': EVIDENCE_METHOD, 'checked_at': now.isoformat(),
                             'promotion_url': url, 'package_url': f'https://store.steampowered.com/sub/{pid}/',
                             'region_url': url}}

    def verify(self, row, region, now):
        app_id = row.get('store_app_id')
        if type(app_id) is not int or app_id not in row['app_ids']:
            return 'store_item_identity_unverified'
        fresh = self.current_offer(app_id, region, now)
        if fresh is None:
            return 'promotion_no_longer_available'
        for key in ['package_id', 'app_ids', 'store_base_package_id', 'ends_at']:
            if fresh[key] != row.get(key):
                return 'promotion_changed'
        return None


def discover_current(store, region, max_candidates=MAX_CANDIDATES, now=None):
    clock = now or (lambda: datetime.now(timezone.utc))
    listing = store.search(region)
    ids = list(listing['app_ids'])
    other_rows = listing['other_rows']
    # Follow only advertised result pages; never enumerate unrelated package IDs.
    while len(ids) + other_rows < listing['total'] and len(ids) < max_candidates:
        page = store.search(region, len(ids) + other_rows)
        if page['total'] != listing['total'] or not page['app_ids'] or set(ids) & set(page['app_ids']):
            break
        ids.extend(page['app_ids'])
        other_rows += page['other_rows']
    complete = len(ids) + other_rows == listing['total'] and len(ids) <= max_candidates
    candidates, rejected = [], []
    seen = set()
    for app_id in ids[:max_candidates]:
        try:
            row = store.current_offer(app_id, region, clock())
            if row is None:
                continue
            if row['package_id'] in seen:
                continue
            seen.add(row['package_id'])
            candidates.append(row)
        except SteamError as error:
            if error.reason in {'store_rate_limited', 'store_unavailable'}:
                raise
            rejected.append({'id': f'app/{app_id}', 'name': f'Steam app {app_id}',
                             'status': 'blocked', 'reason': error.reason})
    return {'schema_version': 1, 'candidates': candidates}, {
        'rejected': rejected, 'scanned': min(len(ids), max_candidates),
        'coverage_incomplete': not complete,
        'source': 'steam_store_current_catalog', 'catalog_total': listing['total']}
