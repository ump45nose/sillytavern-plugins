"""One-off NAS login; credentials stay in the interactive process only."""
import argparse
from contextlib import contextmanager
import getpass
import os
import sys
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .evidence import magnet_hash
from .public_index import IndexFailure, IndexStatus, LinuxBrowserTransport, Mini4KIndexer


DEFAULT_PROFILE = '/config/filmwatchlist-mini4k-cloak-browser'
DEFAULT_CANDIDATE = 'mini4k:v2:mini4k.io:torrents:71690:-'
LOGIN_URL = 'https://www.mini4k.com/user/login'


@contextmanager
def login_step(action):
    """Report a fixed phase and exception type, never the input-bearing message."""
    try:
        yield
    except IndexFailure:
        raise
    except Exception as exc:
        kind = type(exc).__name__
        detail = '超时' if kind == 'TimeoutError' else '失败（' + kind + '）'
        raise IndexFailure(IndexStatus.UNAVAILABLE, 'Mini4K ' + action + detail) from None


def submit_login(page, username: str, password: str):
    """Use the observed Drupal form, without recording credentials or HTML."""
    with login_step('定位登录表单'):
        if page.locator('#user-login-form').count() != 1:
            raise IndexFailure(IndexStatus.PARSE_CHANGED, 'Mini4K 登录表单不可识别')
    with login_step('填写账号字段'):
        page.locator('#edit-name').fill(username)
    with login_step('填写密码字段'):
        page.locator('#edit-pass').fill(password)
    with login_step('提交登录表单并等待导航'):
        # CloakBrowser's humanized click uses the mouse and returns before the
        # form navigation. Subscribe before clicking instead of checking the
        # already-loaded login page and interrupting its pending POST.
        with page.expect_navigation(wait_until='domcontentloaded', timeout=30000):
            page.locator('#user-login-form input[type="submit"]').click()


def probe_url(indexer, candidate_id):
    target = indexer._candidate_target(candidate_id)
    if target is None or not urlparse(target[0]).path.startswith('/torrents/') or target[1]:
        raise ValueError('登录核验需要 Mini4K 种子资源候选 ID')
    return target[0]


def verify_resource(indexer, candidate_id):
    probe_url(indexer, candidate_id)
    result = indexer.resolve(candidate_id)
    if result.status != IndexStatus.OK:
        raise IndexFailure(result.status, result.reason)
    if not any(link.kind in ('torrent', 'magnet') and link.info_hash for link in result.links):
        raise IndexFailure(IndexStatus.LINK_INVALID, '没有取得真实种子或有效磁力链接，登录尚未核实')
    return result


def login(browser, username: str, password: str, candidate_id: str = DEFAULT_CANDIDATE):
    if not username.strip() or not password:
        raise ValueError('账号和密码不能为空')
    indexer = Mini4KIndexer(browser=browser)
    resource_url = probe_url(indexer, candidate_id)
    with login_step('服务端浏览器登录流程'), browser.open_context() as context:
        page = context.pages[0] if context.pages else context.new_page()
        with login_step('访问主站登录页'):
            browser.navigate(context, page, LOGIN_URL, allow_login=True)
        submit_login(page, username, password)
        with login_step('访问登录核验资源页'):
            html = browser.navigate(context, page, resource_url)
        valid_link = False
        for anchor in BeautifulSoup(html, 'html.parser').select('a[href]'):
            href = anchor.get('href', '').strip()
            if href.startswith('magnet:?'):
                try:
                    magnet_hash(href)
                    valid_link = True
                except ValueError:
                    continue
            elif '.torrent' in urlparse(href).path.lower() and indexer._site_url(href):
                valid_link = True
        if not valid_link:
            raise IndexFailure(IndexStatus.AUTH_REQUIRED, '登录后仍未取得资源下载权限，请检查账号或登录验证')
    # Reopen the saved profile and parse real links, rather than trusting cookies.
    return verify_resource(indexer, candidate_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description='一次性登录 NAS Mini4K 浏览器并核验下载权限')
    parser.add_argument('--profile-dir', default=DEFAULT_PROFILE)
    parser.add_argument('--candidate-id', default=DEFAULT_CANDIDATE,
                        help='用于只读核验的种子候选 ID；默认核验《战狼》的一个资源')
    parser.add_argument('--verify-only', action='store_true', help='只检查已保存会话，不输入账号密码')
    args = parser.parse_args(argv)
    browser = LinuxBrowserTransport(args.profile_dir)
    password = ''
    try:
        # docker exec defaults to root, while the API runs as the profile owner.
        # Keep new cookies and lock files readable by that same service user.
        if browser.profile_dir.is_dir() and os.geteuid() == 0:
            owner = browser.profile_dir.stat()
            if owner.st_uid != 0:
                os.setgroups([])
                os.setgid(owner.st_gid)
                os.setuid(owner.st_uid)
        if args.verify_only:
            result = verify_resource(Mini4KIndexer(browser=browser), args.candidate_id)
        else:
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                print('请在交互终端运行（docker exec -it）；不接受管道、命令行密码或环境变量密码。',
                      file=sys.stderr)
                return 2
            username = input('Mini4K 账号：').strip()
            password = getpass.getpass('Mini4K 密码：')
            result = login(browser, username, password, args.candidate_id)
        print('OK：服务器持久会话已核实，可取得真实资源下载链接；未提交媒体下载。')
        for info_hash in dict.fromkeys(link.info_hash for link in result.links if link.info_hash):
            print('Hash：' + info_hash)
        return 0
    except IndexFailure as exc:
        print(exc.status.value + '：' + exc.reason, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('登录已取消。', file=sys.stderr)
        return 1
    except Exception:
        # Browser exceptions can contain typed input; never print their details.
        print('登录／核验失败，请检查账号、候选 ID 或服务器浏览器环境。', file=sys.stderr)
        return 1
    finally:
        password = ''


if __name__ == '__main__':
    raise SystemExit(main())
