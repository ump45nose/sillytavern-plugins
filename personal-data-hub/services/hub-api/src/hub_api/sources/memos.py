import asyncio
import json
import re
import time

from .personal import local_time


class NotOwnMemo(LookupError):
    pass


class Memos:
    def __init__(self, personal):
        self.personal = personal
        self.cached_owner = None
        self.owner_lock = asyncio.Lock()

    async def owner(self):
        async with self.owner_lock:
            if self.cached_owner and time.monotonic()-self.cached_owner[0] < 60:
                return self.cached_owner[1]
            value = await self.personal.request('memos', '/api/v1/auth/me')
            name = value['user']['name']
            if not re.fullmatch(r'users/[A-Za-z0-9_-]{1,64}', name):
                raise ValueError('invalid memo user')
            self.cached_owner = (time.monotonic(), name)
            return name

    def normalize(self, memo):
        identifier = memo['name'].removeprefix('memos/')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identifier):
            raise ValueError('invalid memo name')
        return {'id': identifier,
                'created_at': local_time(memo.get('createTime'), self.personal.now().tzinfo),
                'updated_at': local_time(memo.get('updateTime'), self.personal.now().tzinfo),
                'content': memo['content'], 'tags': memo.get('tags', []),
                'visibility': memo.get('visibility'), 'pinned': memo.get('pinned', False),
                'url': self.personal.settings.memos_public_url.rstrip('/')+'/m/'+identifier,
                'attachments': [{k: a.get(k) for k in ('name', 'filename', 'type')} for a in memo.get('attachments', [])]}

    async def list(self, page_size=20, page_token='', tag='', q=''):
        owner = await self.owner()
        clauses = ['creator == '+json.dumps(owner)]
        if tag:
            clauses.append(json.dumps(tag, ensure_ascii=False)+' in tags')
        if q:
            clauses.append('content.contains('+json.dumps(q, ensure_ascii=False)+')')
        value = await self.personal.request('memos', '/api/v1/memos', {
            'page_size': page_size, 'page_token': page_token, 'state': 'NORMAL',
            'order_by': 'create_time desc', 'filter': ' && '.join('('+c+')' for c in clauses)})
        # A privileged source token can read other creators; never expose them even if a filter regresses.
        rows = value.get('memos', [])
        if any(m['creator'] != owner for m in rows):
            raise ValueError('memo ownership filter mismatch')
        return {'items': [self.normalize(m) for m in rows[:page_size]],
                'next_page_token': value.get('nextPageToken') or None}

    async def own(self, identifier):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identifier):
            raise NotOwnMemo()
        owner = await self.owner()
        value = await self.personal.request('memos', '/api/v1/memos/'+identifier)
        if value['creator'] != owner or value['name'] != 'memos/'+identifier:
            raise NotOwnMemo()
        return value

    async def module(self):
        owner = await self.owner()
        memos, stats = await asyncio.gather(self.list(), self.personal.request('memos', '/api/v1/'+owner+':getStats'))
        return {'recent': memos['items'], 'tags': [{'name': name, 'count': count}
            for name, count in sorted(stats.get('tagCount', {}).items(), key=lambda p: (-p[1], p[0]))]}
