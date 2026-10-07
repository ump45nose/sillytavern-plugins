"""Small FreePackages IPC client. No redirect, proxy, retry, or raw response logging."""
import json
from http.client import HTTPException
import re
import ipaddress
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class SteamError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_endpoint(value):
    if not isinstance(value, str):
        raise SteamError('invalid_ipc_endpoint')
    try:
        u = urlsplit(value)
        loopback = u.hostname == 'localhost' or ipaddress.ip_address(u.hostname).is_loopback
    except ValueError:
        loopback = False
    try:
        if (u.scheme not in {'http', 'https'} or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path not in {'', '/'}
                or (u.scheme == 'http' and not loopback) or not (1 <= (u.port or 80) <= 65535)):
            raise SteamError('invalid_ipc_endpoint')
    except (ValueError, UnboundLocalError):
        raise SteamError('invalid_ipc_endpoint') from None
    return value.rstrip('/')


def validate_tree(tree, depth=0, budget=None):
    budget = budget if budget is not None else [30000]
    budget[0] -= 1
    if (depth > 30 or budget[0] < 0 or not isinstance(tree, dict)
            or not isinstance(tree.get('Name'), str) or tree.get('Value') is not None and not isinstance(tree.get('Value'), str)
            or not isinstance(tree.get('Children'), list)):
        raise SteamError('ipc_invalid_product_tree')
    names = [child.get('Name') if isinstance(child, dict) else None for child in tree['Children']]
    if any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise SteamError('ipc_invalid_product_tree')
    for child in tree['Children']:
        validate_tree(child, depth + 1, budget)
    return tree


class Client:
    def __init__(self, endpoint, password, bot, steam_id, timeout=15):
        self.endpoint = validate_endpoint(endpoint)
        if not isinstance(bot, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', bot) or bot.lower() == 'asf':
            raise SteamError('invalid_bot_name')
        if not isinstance(password, str) or not password or len(password) > 1024 or any(ord(c) < 32 for c in password):
            raise SteamError('invalid_ipc_password')
        self.password, self.bot, self.steam_id, self.timeout = password, bot, steam_id, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, route, method='GET', query=None):
        url = self.endpoint + route + ('?' + urlencode(query) if query else '')
        request = Request(url, method=method, headers={'Authentication': self.password, 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except HTTPError as error:
            reason = ('ipc_authentication_failed' if error.code in (401, 403) else
                      'rate_limited' if error.code == 429 else
                      'ipc_redirect_rejected' if 300 <= error.code < 400 else 'ipc_http_error')
            raise SteamError(reason) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise SteamError('ipc_transport_uncertain') from None
        if len(raw) > 4 * 1024 * 1024:
            raise SteamError('ipc_response_too_large')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SteamError('ipc_invalid_response') from None
        if not isinstance(data, dict) or data.get('Success') is not True or 'Result' not in data:
            raise SteamError('ipc_operation_failed')
        return data['Result']

    def session(self):
        data = self.request('/Api/Bot/' + self.bot)
        if not isinstance(data, dict) or set(data) != {self.bot} or not isinstance(data.get(self.bot), dict):
            raise SteamError('ipc_invalid_bot_response')
        bot = data[self.bot]
        if bot.get('IsConnectedAndLoggedOn') is not True:
            raise SteamError('steam_login_required')
        if str(bot.get('s_SteamID', bot.get('SteamID'))) != self.steam_id:
            raise SteamError('steam_account_mismatch')

    def owned(self):
        data = self.request('/Api/FreePackages/' + self.bot + '/GetOwnedPackages')
        if not isinstance(data, list) or any(type(n) is not int or not 0 < n < 2**32 for n in data):
            raise SteamError('ipc_invalid_owned_response')
        return set(data)

    def claim(self, package_id):
        # Query parameter, not a guessed JSON request body. Never queue: queued work
        # could outlive the promotion window and bypass our final checks.
        return self.request('/Api/FreePackages/' + self.bot + '/RequestFreeSubLicense',
                            'POST', {'subID': package_id})

    def package(self, package_id):
        data = self.request('/Api/FreePackages/' + self.bot + '/GetProductInfo',
                            query={'packageIDs': package_id})
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise SteamError('ipc_invalid_product_response')
        packages = data[0].get('Packages')
        row = packages.get(str(package_id)) if isinstance(packages, dict) else None
        if not isinstance(row, dict) or type(row.get('ID')) is not int or row.get('ID') != package_id or row.get('MissingToken') is not False:
            raise SteamError('package_metadata_unavailable')
        tree = row.get('KeyValues')
        if not isinstance(tree, dict):
            raise SteamError('package_metadata_unavailable')
        return validate_tree(tree)

    def changes(self, change_number=0):
        data = self.request('/Api/FreePackages/' + self.bot + '/GetChangesSince/' + str(change_number),
                            query={'showAppChanges': 'false', 'showPackageChanges': 'true'})
        if not isinstance(data, dict) or not isinstance(data.get('PackageChanges'), dict):
            raise SteamError('ipc_invalid_changes_response')
        return data

    def app(self, app_id):
        data = self.request('/Api/FreePackages/' + self.bot + '/GetProductInfo', query={'appIDs': app_id})
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise SteamError('ipc_invalid_product_response')
        apps = data[0].get('Apps')
        row = apps.get(str(app_id)) if isinstance(apps, dict) else None
        if not isinstance(row, dict) or type(row.get('ID')) is not int or row.get('ID') != app_id or row.get('MissingToken') is not False or not isinstance(row.get('KeyValues'), dict):
            raise SteamError('app_metadata_unavailable')
        return validate_tree(row['KeyValues'])
