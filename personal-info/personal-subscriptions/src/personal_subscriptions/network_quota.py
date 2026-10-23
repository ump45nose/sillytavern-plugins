"""Read only subscription quota headers; never consume or store proxy configurations."""

import ipaddress
import logging
import socket
from datetime import datetime, timezone

import httpx


class QuotaError(Exception):
    pass


def parse_userinfo(value):
    info = {}
    for part in value.split(';'):
        key, separator, number = part.strip().partition('=')
        key, number = key.strip().lower(), number.strip()
        if key not in ('upload', 'download', 'total', 'expire'):
            continue
        if not separator or not number.isascii() or not number.isdecimal() or len(number) > 19 or key in info:
            raise QuotaError('invalid_quota_header')
        info[key] = int(number)
        if info[key] > 2**63 - 1:
            raise QuotaError('invalid_quota_header')
    if not info:
        raise QuotaError('quota_header_missing')
    return info


def origin(url):
    return url.scheme, url.host, url.port


def target(url, trusted_base=None):
    if url.scheme not in ('http', 'https') or not url.host or url.username or url.password or url.fragment:
        raise QuotaError('invalid_quota_url')
    trusted = trusted_base is not None and origin(url) == origin(httpx.URL(trusted_base))
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(
        url.host, url.port or (443 if url.scheme == 'https' else 80), type=socket.SOCK_STREAM)))
    if not addresses or any('%' in address for address in addresses):
        raise QuotaError('blocked_quota_url')
    if not trusted and any(not ipaddress.ip_address(address).is_global or
                           ipaddress.ip_address(address).is_multicast for address in addresses):
        raise QuotaError('blocked_quota_url')
    # Pin the validated DNS result; preserve the original HTTP host and TLS SNI.
    return url.copy_with(host=addresses[0])


def fetch_userinfo(raw_url, *, trusted_base=None):
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    try:
        url = httpx.URL(str(raw_url))
        for hop in range(4):
            pinned = target(url, trusted_base)
            # A fresh connection per hop prevents TLS/Host reuse across redirect origins.
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                with client.stream('GET', pinned,
                    headers={'Host': url.netloc.decode('ascii'), 'User-Agent': 'Clash.Meta', 'Accept-Encoding': 'identity'},
                    extensions={'sni_hostname': url.host}) as response:
                    if response.is_redirect:
                        if hop == 3 or not response.headers.get('location'):
                            raise QuotaError('quota_redirect_limit')
                        redirected = url.join(response.headers['location'])
                        if url.scheme == 'https' and redirected.scheme != 'https':
                            raise QuotaError('blocked_quota_url')
                        url = redirected
                        continue
                    response.raise_for_status()
                    info = parse_userinfo(response.headers.get('subscription-userinfo', ''))
                    return {'id': 'subscription_url', 'userinfo': info,
                            'observed_at': datetime.now(timezone.utc).isoformat()}
    except httpx.TimeoutException:
        raise QuotaError('timeout') from None
    except httpx.HTTPStatusError as exc:
        raise QuotaError('authentication' if exc.response.status_code in (401, 403) else 'source_http_error') from None
    except (httpx.RequestError, OSError):
        raise QuotaError('connection') from None
    except (httpx.InvalidURL, ValueError, TypeError):
        raise QuotaError('invalid_quota_url') from None
