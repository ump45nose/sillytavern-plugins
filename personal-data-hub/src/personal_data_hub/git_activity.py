"""有上界、可推进的 GitHub 提交和本人创建的 PR 采集。"""
from datetime import timedelta
from urllib.parse import urlparse

from .contracts import Batch, Record, digest, instant, utcnow


def stamp(value):
    return value.isoformat(timespec='seconds').replace('+00:00', 'Z')


async def search_windows(session, tool, query, date_field, start, end, sort, fields=None):
    from .remote import call
    windows = [(start, end)]
    found = []
    while windows:
        left, right = windows.pop()
        if left >= right: continue
        args = dict(query=f'{query} {date_field}:{stamp(left)}..{stamp(right - timedelta(seconds=1))}',
                    page=1, perPage=100, sort=sort, order='asc')
        if fields: args['fields'] = fields
        first = await call(session, tool, args)
        count = first['total_count']
        if count > 1000 or first.get('incomplete_results'):
            seconds = int((right - left).total_seconds())
            if seconds <= 1: raise RuntimeError('github_search_limit_requires_repository_scope')
            middle = left + timedelta(seconds=seconds // 2)
            windows.extend([(middle, right), (left, middle)])
            continue
        rows = list(first['items'])
        signatures = {digest(rows)}
        for page in range(2, (count + 99) // 100 + 1):
            more = await call(session, tool, dict(args, page=page))
            if more.get('incomplete_results'): raise RuntimeError('github_search_incomplete')
            items = more['items']
            signature = digest(items)
            if not items or signature in signatures: raise RuntimeError('github_pagination_stalled')
            signatures.add(signature)
            rows.extend(items)
        if len(rows) < count: raise RuntimeError('github_pagination_incomplete')
        found.extend(rows)
    return found


async def collect(settings, cursor, since):
    from .remote import call, mcp_session
    end = utcnow().replace(microsecond=0)
    overlap = timedelta(seconds=settings.get('overlap_seconds', 259200))
    history = timedelta(days=settings.get('history_days', 30))
    last_reconcile = instant(cursor.get('reconciled_at'))
    reconcile = last_reconcile is None or end - last_reconcile >= timedelta(days=settings.get('reconcile_interval_days', 7))
    commit_watermark = instant(cursor.get('completed_through', cursor.get('collected_at')))
    pr_watermark = instant(cursor.get('pr_completed_through'))
    def start(watermark):
        if since is not None: return instant(since).replace(microsecond=0)
        value = watermark - overlap if watermark else end - history
        if reconcile: value = min(value, end - timedelta(days=settings.get('reconcile_days', 30)))
        return value.replace(microsecond=0)
    batches = []
    async with mcp_session('github', settings) as session:
        me = await call(session, 'get_me', {})
        login = me.get('login', (me.get('user') or {}).get('login'))
        if not login: raise RuntimeError('github_identity_missing')
        # Repository qualifiers are optional; the existing scope is this author's visible default-branch commits.
        scopes = settings.get('repositories') or [None]
        commits, prs = {}, {}
        for repo in scopes:
            qualifier = f'author:{login}' + (f' repo:{repo}' if repo else '')
            rows = await search_windows(session, 'search_commits', qualifier, 'committer-date', start(commit_watermark), end, 'committer-date')
            for row in rows:
                repository = row['repository']['full_name']
                eid = repository + ':' + row['sha']
                commits[eid] = Record(eid, 'git_commit', row,
                    {'repo': repository, 'sha': row['sha'], 'message': row['commit']['message'],
                     'collection_scope': 'author_default_branch', 'time_basis': 'committer_date'},
                    instant(row['commit']['committer']['date']))
            if settings.get('collect_pull_requests', True):
                rows = await search_windows(session, 'search_pull_requests', qualifier + ' is:pr', 'updated', start(pr_watermark), end, 'updated',
                                            ['number', 'html_url', 'updated_at'])
                for item in rows:
                    owner, repository = urlparse(item['html_url']).path.strip('/').split('/')[:2]
                    full_name = owner + '/' + repository
                    key = full_name + ':pr:' + str(item['number'])
                    if key in prs: continue
                    row = await call(session, 'pull_request_read', dict(method='get', owner=owner, repo=repository, pullNumber=item['number']))
                    prs[key] = Record(key, 'git_pull_request', row,
                        {'repo': full_name, 'number': row['number'], 'title': row['title'], 'body': row.get('body') or '',
                         'state': row['state'], 'draft': row.get('draft'), 'merged': row.get('merged'),
                         'created_at': row['created_at'], 'updated_at': row['updated_at'],
                         'closed_at': row.get('closed_at'), 'merged_at': row.get('merged_at'), 'url': row['html_url'],
                         'collection_scope': 'authored_pull_requests', 'history': 'observed_object_versions'},
                        instant(row['created_at']), instant(row['updated_at']))
        for record in list(commits.values()) + list(prs.values()): batches.append(Batch(records=[record]))
    next_cursor = dict(completed_through=end.isoformat(), collected_at=end.isoformat(),
                       reconciled_at=end.isoformat() if reconcile else cursor.get('reconciled_at'),
                       scope='author_default_branch_and_authored_pull_requests')
    if settings.get('collect_pull_requests', True): next_cursor['pr_completed_through'] = end.isoformat()
    elif cursor.get('pr_completed_through'): next_cursor['pr_completed_through'] = cursor['pr_completed_through']
    batches.append(Batch(next_cursor=next_cursor))
    return batches
