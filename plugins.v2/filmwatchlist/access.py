"""Distinguish a Cloudflare interstitial from normal pages and login forms."""

from urllib.parse import urlparse

from bs4 import BeautifulSoup


def page_access_status(html: str) -> str | None:
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text(' ', strip=True).casefold() if soup.title else ''
    # A normal page may embed Turnstile. Its script URL alone is not a challenge.
    if (title.startswith(('just a moment', '请稍候'))
            or soup.select_one('#challenge-running, #challenge-stage, #cf-challenge-running')
            or 'window._cf_chl_opt' in html):
        return 'CF_CHALLENGE'
    if soup.select_one('input[type="password"]'):
        return 'AUTH_REQUIRED'
    return None


def download_requires_login(html: str) -> bool:
    soup = BeautifulSoup(html, 'html.parser')
    return any(urlparse(a.get('href', '')).path == '/user/login'
               and '下载' in a.get_text(' ', strip=True)
               for a in soup.select('a[href]'))


def has_download_link(html: str) -> bool:
    soup = BeautifulSoup(html, 'html.parser')
    return any(a.get('href', '').startswith('magnet:?')
               or '.torrent' in urlparse(a.get('href', '')).path.casefold()
               or urlparse(a.get('href', '')).hostname in
               ('115.com', 'www.115.com', 'pan.115.com', 'pan.quark.cn',
                'pan.baidu.com', 'www.alipan.com', 'pan.xunlei.com')
               for a in soup.select('a[href]'))
