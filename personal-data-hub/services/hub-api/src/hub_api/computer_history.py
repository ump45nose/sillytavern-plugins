"""Read published summary manifests only; never collect or copy device data."""
import asyncio
import base64
import hashlib
import hmac
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query

from .sources.base import Adapter, SourceManager

ZONE = ZoneInfo('Asia/Shanghai')
NAME = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-[A-Za-z0-9]+-(10min|6h)-memory-summary\.md')


class Archive:
    def __init__(self, settings, store, now):
        self.settings, self.store, self.now = settings, store, now
        self.manager = SourceManager([Adapter('computer_history','Computer History',30,self.fetch if settings.computer_history_root else None)], now, settings.source_timeout_seconds)

    def opaque_id(self, value):
        return hmac.new(self.store.cursor_key, value.encode(), hashlib.sha256).hexdigest()

    def scan(self):
        root = self.settings.computer_history_root
        devices = self.settings.computer_history_devices
        if not devices:
            raise ValueError('archive devices must be explicitly pinned')
        windows, coverage, stamps, snapshots = {}, [], [], []
        for label, instance in sorted(devices.items()):
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', label) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', instance):
                raise ValueError('invalid configured archive identity')
            directory = (root/'devices'/label).resolve()
            if not directory.is_relative_to(root.resolve()):
                raise ValueError('invalid archive directory')
            device_windows = []
            try:
                manifest = directory/'manifest.json'
                if not manifest.resolve().is_relative_to(directory) or manifest.stat().st_size>8*1024*1024:
                    raise ValueError('invalid manifest')
                raw = manifest.read_bytes()
                if len(raw)>8*1024*1024:
                    raise ValueError('manifest too large')
                data = json.loads(raw)
                if data['device_id']!=label or data['instance_id']!=instance or not isinstance(data['entries'],dict):
                    raise ValueError('archive identity mismatch')
                cutoff=datetime.fromisoformat(data['cutoff'].replace('Z','+00:00'))
                if cutoff.tzinfo is None:
                    raise ValueError('cutoff must include timezone')
                checked=datetime.fromtimestamp(manifest.stat().st_mtime, timezone.utc)
                received=checked.isoformat()
                missing=0
                for name, entry in data['entries'].items():
                    match=NAME.fullmatch(name)
                    if not match or entry.get('name')!=name or not re.fullmatch('[0-9a-f]{64}',entry['sha256']):
                        raise ValueError('invalid archive entry')
                    start=datetime.strptime(match[1],'%Y-%m-%dT%H-%M-%S').replace(tzinfo=timezone.utc)
                    finish=start+timedelta(hours=6) if match[2]=='6h' else start+timedelta(minutes=10)
                    path=(directory/'objects'/entry['sha256']/name).resolve()
                    if not path.is_relative_to(directory/'objects') or not path.is_file():
                        raise ValueError('missing published object')
                    identifier=self.opaque_id(self.store.owner_id+':'+instance+':'+name)
                    row={'id':identifier, 'source_device_id':instance, 'source_device_name':label,
                         'started_at':start.isoformat(), 'ended_at':finish.isoformat(),
                         'granularity':match[2], 'revision':entry['sha256'], 'received_at':received,
                         '_path':str(path)}
                    device_windows.append(row)
                # Without an explicit inventory assertion, omissions are not deletions.
                key=self.opaque_id(str(root)+':'+instance)
                previous=self.store.source_snapshot(key) or {}
                current={r['id']:r for r in device_windows}
                deleted=data.get('deleted_records', [])
                complete=data.get('complete_inventory', False)
                if type(complete) is not bool or not isinstance(deleted,list) or any(not isinstance(n,str) or not NAME.fullmatch(n) for n in deleted):
                    raise ValueError('invalid deletion inventory')
                deleted_ids={self.opaque_id(self.store.owner_id+':'+instance+':'+n) for n in deleted}
                if deleted_ids & current.keys():
                    raise ValueError('contradictory deletion inventory')
                unconfirmed=0
                if not complete:
                    for identifier, row in previous.items():
                        if identifier not in current and identifier not in deleted_ids:
                            current[identifier]={**row,'presence':'unconfirmed'}
                            unconfirmed+=1
                device_windows=list(current.values())
                self.store.source_snapshot(key,current)
                intervals=sorted((datetime.fromisoformat(r['started_at']), datetime.fromisoformat(r['ended_at'])) for r in device_windows)
                gaps=[]
                end=intervals[0][0] if intervals else cutoff
                for start, finish in intervals:
                    if start>end:
                        gaps.append({'start':end.isoformat(),'end':start.isoformat()})
                    end=max(end,finish)
                if intervals and end<cutoff:
                    gaps.append({'start':end.isoformat(),'end':cutoff.isoformat()})
                coverage.append({'source_device_id':instance,'name':label,'status':'partial',
                    'received_at':received,'archive_cutoff':cutoff.isoformat(),
                    'received_through':max((b for _,b in intervals),default=None).isoformat() if intervals else None,
                    'first_window_at':intervals[0][0].isoformat() if intervals else None,
                    'last_window_at':max((b for _,b in intervals),default=None).isoformat() if intervals else None,
                    'gaps':gaps,'missing_objects':missing,'completeness':'unknown',
                    'unconfirmed_removals':unconfirmed,
                    # The daily 09:00 job publishes a manifest even when the device is idle.
                    # Give publication two hours of grace and its midnight cutoff three.
                    'stale':self.now()-checked>timedelta(hours=26) or self.now()-cutoff>timedelta(hours=36)})
                snapshots.append([instance,hashlib.sha256(raw).hexdigest(),self.opaque_id(json.dumps(current,sort_keys=True))])
                stamps.append(received)
                windows.update({r['id']:r for r in device_windows})
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                coverage.append({'source_device_id':instance,'name':label,'status':'error','completeness':'unknown'})
                snapshots.append([instance,'error'])
        if all(c['status']=='error' for c in coverage):
            raise ValueError('no readable archive manifests')
        return {'windows':windows,'coverage':coverage,'source_updated_at':max(stamps,default=None),
                'snapshot':self.opaque_id(json.dumps(snapshots,sort_keys=True))}

    async def fetch(self):
        result=await asyncio.to_thread(self.scan)
        previous=self.manager.cache.get('computer_history',{}).get('data')
        if previous:
            failed={c['source_device_id'] for c in result['coverage'] if c['status']=='error'}
            result['windows'].update({k:v for k,v in previous['windows'].items() if v['source_device_id'] in failed})
        return result

    def cursor(self, payload):
        raw=json.dumps(payload, separators=(',',':')).encode()
        return base64.urlsafe_b64encode(hmac.digest(self.store.cursor_key,raw,'sha256')+raw).rstrip(b'=').decode()

    def offset(self, cursor, scope):
        if cursor is None:
            return 0
        try:
            if len(cursor)>4096:
                raise ValueError()
            raw=base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4))
            if not hmac.compare_digest(raw[:32],hmac.digest(self.store.cursor_key,raw[32:],'sha256')):
                raise ValueError()
            data=json.loads(raw[32:])
            if data['scope']!=scope or type(data['offset']) is not int or data['offset']<0:
                raise ValueError()
            return data['offset']
        except (ValueError, KeyError, TypeError):
            return None


def public(row):
    return {k:v for k,v in row.items() if not k.startswith('_')}


def register(app, settings, store, authenticated, now):
    archive=Archive(settings,store,now)
    app.state.computer_history=archive

    def failure(code, status):
        return app.router.default_response_class({'error':{'code':code,'message':code}},status_code=status)

    async def snapshot():
        value=await archive.manager.get('computer_history')
        if value['status']=='unconfigured':
            return None,failure('computer_history_unconfigured',503)
        if value['data'] is None:
            return None,failure('computer_history_source_error',502)
        return value,None

    def page(value, rows, cursor, scope, limit, source_device_id):
        data=value['data']
        scope=[scope,data['snapshot'],'Asia/Shanghai',limit,store.bindings(store.owner_id)['version']]
        offset=archive.offset(cursor,scope)
        if offset is None:
            return failure('cursor_expired',409)
        coverage=[c for c in data['coverage'] if source_device_id is None or c['source_device_id']==source_device_id]
        return {'items':rows[offset:offset+limit],
                'next_cursor':archive.cursor({'scope':scope,'offset':offset+limit}) if offset+limit<len(rows) else None,
                'source_updated_at':data['source_updated_at'],'coverage':coverage,
                'status':'stale' if value['status']=='stale' else 'partial', 'timezone':'Asia/Shanghai'}

    def validate_device(source_device_id):
        if source_device_id is not None and source_device_id not in settings.computer_history_devices.values():
            raise HTTPException(404)

    @app.get('/api/v1/computer-history/days')
    async def days(start_date:date|None=None,end_date:date|None=None,source_device_id:str|None=None,cursor:str|None=None,
                   limit:int=Query(30,ge=1,le=100),identity=Depends(authenticated)):
        validate_device(source_device_id)
        if start_date and end_date and start_date>end_date:
            raise HTTPException(400)
        value,error=await snapshot()
        if error is not None:
            return error
        counts={}
        for row in value['data']['windows'].values():
            if source_device_id and row['source_device_id']!=source_device_id:
                continue
            first=datetime.fromisoformat(row['started_at']).astimezone(ZONE).date()
            last=(datetime.fromisoformat(row['ended_at'])-timedelta(microseconds=1)).astimezone(ZONE).date()
            for day in (first, last) if last!=first else (first,):
                if (not start_date or day>=start_date) and (not end_date or day<=end_date):
                    entry=counts.setdefault(day.isoformat(),{'date':day.isoformat(),'window_count':0,'source_device_ids':set()})
                    entry['window_count']+=1
                    entry['source_device_ids'].add(row['source_device_id'])
        rows=[{**r,'source_device_ids':sorted(r['source_device_ids'])} for _,r in sorted(counts.items(),reverse=True)]
        return page(value,rows,cursor,['days',identity['user_id'],str(start_date),str(end_date),source_device_id],limit,source_device_id)

    @app.get('/api/v1/computer-history/windows')
    async def windows(day:date=Query(alias='date'),source_device_id:str|None=None,cursor:str|None=None,
                      limit:int=Query(50,ge=1,le=200),identity=Depends(authenticated)):
        validate_device(source_device_id)
        value,error=await snapshot()
        if error is not None:
            return error
        start=datetime.combine(day,time(),ZONE)
        finish=start+timedelta(days=1)
        rows=[public(r) for r in value['data']['windows'].values() if (source_device_id is None or r['source_device_id']==source_device_id)
              and datetime.fromisoformat(r['started_at'])<finish and datetime.fromisoformat(r['ended_at'])>start]
        rows.sort(key=lambda r:(r['started_at'],r['source_device_id'],r['id']),reverse=True)
        return page(value,rows,cursor,['windows',identity['user_id'],str(day),source_device_id],limit,source_device_id)

    @app.get('/api/v1/computer-history/windows/{window_id}')
    async def detail(window_id:str,identity=Depends(authenticated)):
        value,error=await snapshot()
        if error is not None:
            return error
        row=value['data']['windows'].get(window_id)
        if row is None:
            raise HTTPException(404)
        def read():
            path=Path(row['_path'])
            if path.stat().st_size>4*1024*1024:
                raise ValueError('summary too large')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=row['revision']:
                raise ValueError('summary checksum mismatch')
            text=raw.decode('utf-8')
            parts=[]
            for section in ('Memory summary','Recording summary'):
                match=re.search(r'(?ms)^## '+section+r'\s*\n(.*?)(?=^##\s|\Z)',text)
                if match:
                    body=re.split(r'(?mi)^(?:#{1,6}\s*)?(?:Relevant prior context|Important non-obvious context about the user)\s*$',match[1],maxsplit=1)[0].strip()
                    parts.append('## '+section+'\n'+body)
            return '\n\n'.join(parts)
        try:
            async with asyncio.timeout(settings.source_timeout_seconds):
                summary=await asyncio.to_thread(read)
        except (OSError,ValueError,TimeoutError):
            return failure('computer_history_source_error',502)
        return {**public(row),'summary_markdown':summary,'source_updated_at':value['data']['source_updated_at'],'status':value['status']}
