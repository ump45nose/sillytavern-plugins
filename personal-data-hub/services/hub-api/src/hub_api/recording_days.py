import asyncio
import time
from collections import OrderedDict
from datetime import timedelta

from .modules.crm import overlap_score
from .sources.personal import local_time


class RecordingDays:
    def __init__(self, personal):
        self.personal = personal
        self.lock = asyncio.Lock()
        self.cache = OrderedDict()

    async def get(self, before, limit):
        key = (before, limit)
        async with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 60:
                self.cache.move_to_end(key)
                return cached[1]
            async with asyncio.timeout(self.personal.settings.source_timeout_seconds):
                result = await self.fetch(before, limit)
            self.cache[key] = (time.monotonic(), result)
            self.cache.move_to_end(key)
            while len(self.cache) > 32:
                self.cache.popitem(last=False)
            return result

    async def fetch(self, before, limit):
        p = self.personal
        page = await p.request('plaud', '/api/v1/archives', {
            'end_date': (before-timedelta(days=1)).isoformat(), 'limit': limit+1, 'audio_only': 'true'})
        rows = page['items']
        selected = rows[:limit]
        if not selected:
            return {'days': [], 'next_before': None}
        details = []
        # Bound task fan-out as well as Personal's shared four-request I/O semaphore.
        for offset in range(0, len(selected), 4):
            details.extend(await asyncio.gather(*(p.request('plaud', '/api/v1/archives/'+d['date'],
                {'metadata_only': 'true'}) for d in selected[offset:offset+4])))
        days = []
        for detail in details:
            day = detail['date']
            recordings = [{
                'id': 'plaud:'+day+':'+a['id'], 'title': a['name'],
                'start_at': local_time(a.get('start_at'), p.now().tzinfo),
                'duration_seconds': a['duration_ms']/1000 if a.get('duration_ms') is not None else None,
            } for a in detail['audio']]
            if recordings:
                days.append({'date': day, 'recordings': recordings,
                             'has_transcript': detail['has_transcript'], 'people': []})
        if days and p.settings.crm_token:
            names = {}
            async for people in p.pages('people'):
                names.update((person['id'], person.get('name')) for person in people)
                if len(names) > 10000:
                    raise ValueError('contact list exceeds supported bound')
            count = 0
            by_date = {d['date']: d for d in days}
            matches = {d['date']: set() for d in days}
            async for items in p.pages('interactions', start=min(by_date), end=max(by_date)):
                count += len(items)
                if count > 10000:
                    raise ValueError('interaction list exceeds supported bound')
                for item in items:
                    day = by_date.get(item['date'])
                    if day and any(overlap_score(item, r, p.now().tzinfo) is not None for r in day['recordings']):
                        matches[day['date']].update(names[pid] for pid in item['person_ids'] if names.get(pid))
            for day in days:
                day['people'] = sorted(matches[day['date']])
        return {'days': sorted(days, key=lambda d: d['date'], reverse=True),
                'next_before': selected[-1]['date'] if len(rows) > limit else None}
