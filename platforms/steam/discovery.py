"""Bounded PICS discovery plus explicit official-store free-to-keep evidence.

NoCost is only a prefilter. Never infer permanence from free price or ownership.
The discovery window is incomplete by design; failures remain visible.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
import re
import json
import ipaddress
import time
from pathlib import Path
from common.model import atomic_json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from .ipc import NoRedirect, SteamError
from .candidates import child, leaf, verify_package, verify_app


def validate_store_proxy(value):
    """Only an explicit local HTTP proxy, never credentials or environment proxy."""
    if not isinstance(value, str):
        raise SteamError('invalid_store_proxy')
    try:
        url = urlsplit(value)
        local = url.hostname == 'localhost' or ipaddress.ip_address(url.hostname).is_loopback
        if (url.scheme != 'http' or not local or url.username is not None or url.password is not None
                or url.path not in {'', '/'} or url.query or url.fragment
                or url.port is None or not 1 <= url.port <= 65535):
            raise ValueError()
    except (ValueError, TypeError):
        raise SteamError('invalid_store_proxy') from None
    return value.rstrip('/')


class StoreClient:
    def __init__(self, proxy_url=None):
        proxies = {'https': validate_store_proxy(proxy_url)} if proxy_url is not None else {}
        self.opener = build_opener(ProxyHandler(proxies), NoRedirect())

    def page(self, app_id, region):
        # Public store page only, no Steam cookies, keys, or ASF credentials.
        # Region remains the account's declared country even with a local proxy.
        url = f'https://store.steampowered.com/app/{app_id}/?' + urlencode({'cc': region, 'l': 'english'})
        for attempt in range(2):
            try:
                with self.opener.open(Request(url, headers={'Accept': 'text/html'}), timeout=10) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                break
            except HTTPError as error:
                if error.code == 429:
                    raise SteamError('store_rate_limited') from None
                if error.code not in {500, 502, 503, 504} or attempt:
                    raise SteamError('store_unavailable') from None
            except (URLError, OSError, TimeoutError, HTTPException):
                if attempt:
                    raise SteamError('store_unavailable') from None
            # Retry only this anonymous GET. IPC and license POSTs never retry.
            time.sleep(0.3)
        if len(raw) > 2 * 1024 * 1024:
            raise SteamError('store_response_too_large')
        try:
            return raw.decode('utf-8', errors='strict')
        except UnicodeError:
            raise SteamError('store_invalid_response') from None


class PurchaseBlocks(HTMLParser):
    """Keep text and license actions within the same purchase wrapper only."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.block = None
        self.depth = 0
        self.ignored = 0
        self.free_form = False
        self.promotion_text = False
        self.price_depth = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set((values.get('class') or '').split())
        if self.block is None and tag == 'div' and 'game_area_purchase_game' in classes:
            self.block = {'text': [], 'promotion_text': [], 'price_text': [],
                          'packages': set(), 'apps': set()}
            self.depth = 1
        elif self.block is not None and tag == 'div':
            self.depth += 1
        if self.block is not None:
            if tag == 'div' and 'game_purchase_price' in classes:
                self.price_depth = self.depth
            if tag == 'p':
                self.promotion_text = 'game_purchase_discount_quantity' in classes
            if tag == 'form':
                self.free_form = ((values.get('method') or '').lower() == 'post' and values.get('action') in {
                    'https://store.steampowered.com/checkout/addfreelicense/',
                    'https://store.steampowered.com/freelicense/addfreelicense/'})
            if tag == 'input' and self.free_form and values.get('name') == 'subid':
                value = values.get('value') or ''
                if re.fullmatch(r'[1-9][0-9]*', value):
                    self.block['packages'].add(int(value))
            if tag in {'script', 'style'}:
                self.ignored += 1
            # Exact well-known store free-license function, numeric first arg.
            # Any different DOM/handler means we do not claim that promotion.
            for key in ('onclick', 'href'):
                value = values.get(key, '') or ''
                for match in re.finditer(r'\bAddFreeLicense\s*\(\s*([1-9][0-9]*)\s*[,)]', value):
                    self.block['packages'].add(int(match.group(1)))
                for match in re.finditer(r'\bsteam://run/([1-9][0-9]*)\b', value):
                    self.block['apps'].add(int(match.group(1)))

    def handle_endtag(self, tag):
        if self.block is None:
            return
        if tag == 'p':
            self.promotion_text = False
        if tag == 'form':
            self.free_form = False
        if tag in {'script', 'style'}:
            self.ignored = max(0, self.ignored - 1)
        if tag == 'div':
            if self.depth == self.price_depth:
                self.price_depth = None
            self.depth -= 1
            if self.depth == 0:
                self.blocks.append(self.block)
                self.block = None
                self.ignored = 0
                self.free_form = False
                self.price_depth = None

    def handle_data(self, data):
        if self.block is not None and not self.ignored:
            self.block['text'].append(data)
            if self.promotion_text:
                self.block['promotion_text'].append(data)
            if self.price_depth is not None:
                self.block['price_text'].append(data)


def official_free_game(html, app_id):
    """One explicitly selected F2P acceptance sample, not promotion discovery."""
    parser = PurchaseBlocks()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, RecursionError):
        return False
    return any(block['apps'] == {app_id}
               and ' '.join(' '.join(block['price_text']).split()).casefold() == 'free to play'
               and not re.search(r'\b(free weekend|free trial)\b', ' '.join(block['text']), re.IGNORECASE)
               for block in parser.blocks)


def official_offer(html, package_id):
    parser = PurchaseBlocks()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, RecursionError):
        return False
    for block in parser.blocks:
        text = ' '.join(' '.join(block['text']).split())
        promotion = ' '.join(' '.join(block['promotion_text']).split())
        if (block['packages'] == {package_id}
                and re.search(r'\bFree to keep when you get it before\b', promotion, re.IGNORECASE)
                and not re.search(r'\b(free weekend|play for free|free trial)\b', text, re.IGNORECASE)):
            return True
    return False


class DiscoveryState:
    """A durable rotating work queue; never advance a cursor without its work."""
    def __init__(self, path, initial_change=0):
        self.path = Path(path)
        self.cursor = initial_change
        self.queue = []
        self.history_gap = False
        if self.path.exists():
            try:
                if self.path.stat().st_size > 65536:
                    raise ValueError()
                value = json.loads(self.path.read_text())
                if (value['schema_version'] != 1 or value['initial_change'] != initial_change
                        or type(value['cursor']) is not int or not initial_change <= value['cursor'] < 2**32
                        or type(value['history_gap']) is not bool or not isinstance(value['queue'], list)
                        or len(value['queue']) > 4000
                        or any(type(pid) is not int or not 0 < pid < 2**32 for pid in value['queue'])
                        or len(set(value['queue'])) != len(value['queue'])):
                    raise ValueError()
                self.cursor, self.queue, self.history_gap = value['cursor'], value['queue'], value['history_gap']
            except (OSError, ValueError, KeyError, TypeError):
                raise SteamError('discovery_state_invalid') from None
        self.initial_change = initial_change

    def save(self):
        atomic_json(self.path, {'schema_version': 1, 'initial_change': self.initial_change,
                               'cursor': self.cursor, 'queue': self.queue, 'history_gap': self.history_gap})


def discover(client, store, region, now=None, change_number=0, max_packages=30, state=None, confirmed=None):
    clock = now or (lambda: datetime.now(timezone.utc))
    changes = client.changes(state.cursor if state else change_number)
    if (type(changes.get('CurrentChangeNumber')) is not int
            or any(type(changes.get(k)) is not bool for k in ('RequiresFullUpdate', 'RequiresFullPackageUpdate'))):
        raise SteamError('ipc_invalid_changes_response')
    pending = []
    for key, row in changes['PackageChanges'].items():
        if (not isinstance(key, str) or not key.isdecimal() or not isinstance(row, dict)
                or type(row.get('ID')) is not int or str(row['ID']) != key or not 0 < row['ID'] < 2**32
                or type(row.get('ChangeNumber')) is not int or type(row.get('NeedsToken')) is not bool):
            raise SteamError('ipc_invalid_changes_response')
        pending.append(row)
    pending.sort(key=lambda r: (r['ChangeNumber'], r['ID']))
    newly_changed = {row['ID']: row for row in pending}
    queue = list(dict.fromkeys((state.queue if state else []) + [row['ID'] for row in pending]))
    confirmed = confirmed or set()
    queue = [pid for pid in queue if pid not in confirmed]
    if len(queue) > 4000:
        raise SteamError('discovery_queue_capacity_requires_review')
    history_gap = (state.history_gap if state else False) or changes['RequiresFullUpdate'] or changes['RequiresFullPackageUpdate']
    if state:
        if changes['CurrentChangeNumber'] < state.cursor:
            raise SteamError('discovery_cursor_moved_backwards')
        state.cursor, state.queue, state.history_gap = changes['CurrentChangeNumber'], queue, history_gap
        state.save()
    batch, remaining = queue[:max_packages], queue[max_packages:]
    truncated = bool(remaining)
    candidates, rejected, retained = [], [], []
    for pid in batch:
        changed = newly_changed.get(pid, {})
        reason = None
        try:
            if changed.get('NeedsToken'):
                raise SteamError('package_token_required')
            tree = client.package(pid)
            if leaf(tree, 'billingtype') != '0':
                # Non-NoCost packages are positively outside the chosen scope.
                # Missing metadata is an unknown, not a confirmed exclusion.
                if leaf(tree, 'billingtype') is None:
                    raise SteamError('package_metadata_unavailable')
                continue
            extended = child(tree, 'extended')
            expiry = leaf(extended, 'expirytime')
            if not isinstance(expiry, str) or not expiry.isdecimal() or not 0 < int(expiry) < 253402300799:
                raise SteamError('promotion_deadline_unverified')
            end = datetime.fromtimestamp(int(expiry), timezone.utc)
            current = clock()
            if end <= current:
                continue
            app_tree = child(tree, 'appids')
            app_nodes = app_tree.get('Children') if isinstance(app_tree, dict) else None
            if not isinstance(app_nodes, list) or not 1 <= len(app_nodes) <= 5:
                raise SteamError('package_contents_unverified')
            app_ids = []
            for node in app_nodes:
                value = node.get('Value') if isinstance(node, dict) else None
                if not isinstance(value, str) or not value.isdecimal() or not 0 < int(value) < 2**32:
                    raise SteamError('package_contents_unverified')
                app_ids.append(int(value))
            row = {'package_id': pid, 'app_ids': app_ids, 'name': f'Steam package {pid}',
                   'promotion_kind': 'limited_time_free_to_keep', 'permanent_license': True,
                   'free_to_play': False, 'free_weekend': False, 'demo': False, 'playtest': False,
                   'product_type': 'game', 'price_minor': 0, 'regular_price_minor': None, 'currency': None,
                   'allowed_regions': [region], 'starts_at': current.isoformat(), 'ends_at': end.isoformat(),
                   'evidence': {'reviewed': True, 'method': 'official_store_free_to_keep',
                       'checked_at': current.isoformat(), 'promotion_url': f'https://store.steampowered.com/app/{app_ids[0]}/',
                       'package_url': f'https://steamdb.info/sub/{pid}/',
                       'region_url': f'https://store.steampowered.com/app/{app_ids[0]}/'}}
            reason = verify_package(tree, row, current, region)
            if reason:
                raise SteamError(reason)
            for app_id in app_ids:
                app = client.app(app_id)
                reason = verify_app(app, app_id, region)
                if reason:
                    raise SteamError(reason)
            # Official copy and exact package action must occur in one purchase
            # block; names/discount badges/user reviews are never sufficient.
            if not official_offer(store.page(app_ids[0], region), pid):
                raise SteamError('official_free_to_keep_evidence_missing')
            current = clock()
            row['evidence']['checked_at'] = current.isoformat()
            if current >= end:
                raise SteamError('promotion_expired')
            candidates.append(row)
            retained.append(pid)
        except SteamError as error:
            if error.reason in {'ipc_authentication_failed', 'rate_limited', 'store_rate_limited', 'ipc_transport_uncertain'}:
                raise
            reason = error.reason
            retained.append(pid)
        if reason:
            rejected.append({'id': f'sub/{pid}', 'name': f'Steam package {pid}', 'status': 'blocked', 'reason': reason})
    if state:
        state.queue = remaining + retained
        state.save()
    return {'schema_version': 1, 'candidates': candidates}, {
        'rejected': rejected, 'scanned': len(batch),
        'change_number': changes['CurrentChangeNumber'],
        'coverage_incomplete': truncated or history_gap,
    }
