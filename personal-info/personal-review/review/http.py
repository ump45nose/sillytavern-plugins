"""Private HTTP surface for existing review services; no request/body logging."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from review.daily import DailyReviewService
from review.weekly import WeeklyReviewService
from review.stages import StageService


class APIError(Exception):
    def __init__(self, status, code, message, field=None):
        self.status, self.code, self.message, self.field = status, code, message, field


def validation_error(error):
    message = str(error)
    if '已经过期' in message:
        return APIError(409, 'expired', message)
    if '尚未结案' in message or '同一目标已有不同内容' in message:
        return APIError(409, 'conflict', message)
    field = next((field for prefix, field in [
        ('一句话总结', '一句话总结今天'), ('日报必须包含一句话总结', '一句话总结今天'),
        ('瞬间', '瞬间'), ('日报未解', '未解'), ('阶段评论', 'text'),
        ('阶段总结原文', 'text'), ('必须为每个阶段目标', 'outcomes'),
        ('未知主线领域', 'domain'),
        ('活跃阶段目标', 'goals'),
    ] if message.startswith(prefix)), None)
    if message.startswith('阶段目标字段不能为空'):
        field=next((k for k in ('goal','progress','deadline','success_criteria','stop_signal') if repr(k) in message),None)
    return APIError(422, 'validation', message, field)


class ReviewAPI:
    def __init__(self, config, state, memos, now=None):
        self.config, self.state, self.memos = config, state, memos
        self.now = now or (lambda: datetime.now(config.timezone))
        self.daily = DailyReviewService(state, config.policy, memos, config.flags.tasks)
        self.weekly = WeeklyReviewService(state, config.policy, memos, config.flags.tasks)
        self.stages = StageService(state, config.policy, memos, config.flags.tasks)
        self.notifier = None

    @staticmethod
    def check(body, required, optional=None):
        optional=optional or {}
        if set(body)-set(required)-set(optional): raise APIError(422,'validation','请求包含未知字段')
        for name,kind in required.items():
            if name not in body or not isinstance(body[name],kind): raise APIError(422,'validation','字段类型无效',name)
        for name,kind in optional.items():
            if name in body and not isinstance(body[name],kind): raise APIError(422,'validation','字段类型无效',name)

    def finalize(self, identifier, content):
        with self.state.operation():
            row=self.session(identifier);already=row['status']=='finalized'
            result=(self.daily if row['kind']=='daily' else self.weekly).finalize(identifier,content,confirmation_source='app')
        if not already and self.notifier: self.notifier(row['kind'],identifier.split(':',1)[1])
        return {'status':'finalized','memo_name':result['memo_name'],'already':already}

    def iso(self, value):
        return datetime.fromisoformat(value).astimezone(self.config.timezone).isoformat() if value else None

    def summary(self, row):
        status = row['status']
        if status != 'finalized' and datetime.fromisoformat(row['expires_at']) <= self.now():
            status = 'expired'
        return {key: value for key, value in {
            'id': row['id'], 'label': row['id'].split(':', 1)[1], 'status': status,
            'prepared_at': self.iso(row['prepared_at']), 'expires_at': self.iso(row['expires_at']),
            'memo_name': row['memo_name'],
        }.items()}

    def session(self, identifier):
        row = self.state.load_session(identifier)
        if row is None or row['kind'] not in ('daily', 'weekly'):
            raise APIError(404, 'not_found', '复盘会话不存在')
        return row

    def sessions(self, kind=None, limit=14):
        if kind not in (None, 'daily', 'weekly') or not 1 <= limit <= 100:
            raise APIError(400, 'bad_request', '会话查询参数无效')
        with self.state.connect() as db:
            rows = db.execute("SELECT * FROM review_sessions WHERE kind IN ('daily','weekly') "
                              "AND (? IS NULL OR kind=?) ORDER BY id DESC LIMIT ?", (kind, kind, limit)).fetchall()
        return {'items': [self.summary(row) for row in rows]}

    def detail(self, identifier):
        row = self.session(identifier)
        material = json.loads(row['material_json']) if row['material_json'] else {}
        if row['kind'] == 'weekly' and not material:
            frozen = json.loads(row['evidence_json'])
            material = {'sections': [{'title': '已确认日报', 'blocks': [x['content'] for x in frozen.get('daily', [])]}],
                        'template': self.weekly.blank_template(identifier.split(':', 1)[1])}
        policy = self.config.policy[row['kind']]
        rules = {'fields': policy['fields'], 'auto_fields': ['健康', '财务'] if row['kind'] == 'daily' else ['身体']}
        if row['kind'] == 'daily':
            rules.update({key: policy[key] for key in ('summary_max_chars', 'summary_max_list_separators',
                         'max_unresolved', 'moment_min_chars', 'emotion_words')})
        return {**self.summary(row), 'kind': row['kind'],
                'material': {'sections': [{'title': s['title'], 'blocks': s['blocks']} for s in material.get('sections', [])],
                             'template': material.get('template') or self.daily.blank_template(identifier.split(':', 1)[1])},
                'delivered': self.delivered(row), 'final_content': row['final_content'], 'rules': rules}

    def delivered(self, row):
        """Read only a matching successful execution's Response, never its prompt/log."""
        try:
            jobs_file = self.config.path('REVIEW_JOBS_FILE')
            name = 'personal-review-daily-2130' if row['kind'] == 'daily' else 'personal-review-weekly-2150'
            jobs = [j for j in json.loads(jobs_file.read_text())['jobs'] if j.get('name') == name]
            if len(jobs) != 1: return None
            job = jobs[0]
            day = datetime.fromisoformat(row['window_end']).astimezone(self.config.timezone).date()
            folder = jobs_file.parent / 'output' / str(job['id'])
            candidates = []
            for path in folder.glob(day.isoformat() + '_*.md'):
                try: stamp = datetime.strptime(path.stem, '%Y-%m-%d_%H-%M-%S').replace(tzinfo=self.config.timezone)
                except ValueError: continue
                candidates.append((stamp, path))
            for stamp, path in sorted(candidates, reverse=True):
                with sqlite3.connect(f"file:{self.config.path('REVIEW_HERMES_EXECUTIONS_DB')}?mode=ro", uri=True) as db:
                    execution = db.execute('SELECT started_at,finished_at FROM executions WHERE job_id=? AND status=? '
                        'AND error IS NULL AND julianday(started_at)<=julianday(?) AND julianday(finished_at)>=julianday(?) '
                        'ORDER BY finished_at DESC LIMIT 1',
                        (job['id'], 'completed', (stamp+timedelta(seconds=1)).isoformat(), (stamp-timedelta(seconds=1)).isoformat())).fetchone()
                if not execution: continue
                if job.get('last_run_at') and abs((datetime.fromisoformat(job['last_run_at'])-datetime.fromisoformat(execution[1])).total_seconds()) <= 5 and job.get('last_delivery_error'):
                    continue
                with path.open() as stream: document = stream.read(1_048_577)
                if len(document)>1_048_576: continue
                _, separator, response = document.rpartition('\n## Response\n')
                if separator and response.strip():
                    return {'text': response.strip(), 'delivered_at': self.iso(execution[1])}
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            pass
        return None

    def preview(self, identifier, content):
        row = self.session(identifier)
        if row['status'] == 'finalized': return {'content': row['final_content']}
        result = (self.daily if row['kind']=='daily' else self.weekly).finalize(identifier, content, dry_run=True)
        return {'content': result['content']}

    def next_run(self, kind):
        now = self.now()
        configured = self.config.values['REVIEW_DAILY_TIME' if kind=='daily' else 'REVIEW_WEEKLY_TIME']
        clock = configured.split()[-1]
        hour, minute = map(int, clock.split(':'))
        day = now.date()
        if kind=='weekly':
            target = ['MON','TUE','WED','THU','FRI','SAT','SUN'].index(configured.split()[0])
            day += timedelta(days=(target-day.weekday()) % 7)
        result = datetime.combine(day, time(hour,minute), self.config.timezone)
        if result<=now: result+=timedelta(days=1 if kind=='daily' else 7)
        return result.isoformat()

    def stage(self):
        with self.state.connect() as db:
            mainline = db.execute('SELECT * FROM mainlines WHERE domain=?', (self.config.policy['stages']['mainline_domain'],)).fetchone()
            cycle = db.execute("SELECT * FROM stage_cycles WHERE status IN ('active','awaiting_close') ORDER BY starts_at DESC LIMIT 1").fetchone()
            latest = db.execute('SELECT * FROM stage_cycles ORDER BY starts_at DESC LIMIT 1').fetchone()
            goals = db.execute('SELECT * FROM stage_goals WHERE cycle_id=? ORDER BY id', (cycle['id'],)).fetchall() if cycle else []
            index = db.execute('SELECT count(*) FROM stage_cycles WHERE starts_at<=?', (cycle['starts_at'],)).fetchone()[0] if cycle else None
        result = {'mainline': {**json.loads(mainline['payload_json']), 'domain': mainline['domain'], 'memo_name': mainline['memo_name'],
                              'updated_at': self.iso(mainline['updated_at'])} if mainline else None,
                  'cycle': None, 'goals': [], 'reviews': {'daily': None, 'weekly': None,
                    'next_daily_at': self.next_run('daily'), 'next_weekly_at': self.next_run('weekly')},
                  'close': {'status': 'closed' if latest and latest['status']=='closed' else 'none',
                            'cycle_id': latest['id'] if latest else None, 'template': None}, '_partial': False}
        for kind in ('daily','weekly'):
            rows = self.sessions(kind,1)['items'];result['reviews'][kind] = rows[0] if rows else None
        if not cycle: return result
        start,end = (datetime.fromisoformat(cycle[key]).astimezone(self.config.timezone) for key in ('starts_at','ends_at'))
        total = int(self.config.policy['stages']['cycle_days'])
        preclose = end-timedelta(days=int(self.config.policy['stages']['preclose_days']))
        result['cycle'] = {'id':cycle['id'],'index':index,'status':cycle['status'], 'starts_at':start.isoformat(),
            'ends_at':end.isoformat(),'day':max(1,min(total,(self.now().date()-start.date()).days+1)), 'total':total,'preclose_at':preclose.isoformat()}
        status = 'awaiting_close' if self.now()>=end or cycle['status']=='awaiting_close' else 'preclose' if self.now()>=preclose else 'none'
        frozen = self.state.get_idempotent('stage-preclose', cycle['id'])
        result['close'] = {'status':status,'cycle_id':cycle['id'], 'template':(frozen['template'] if frozen else self.stages.close_template(cycle['id'])) if status!='none' else None}
        for row in goals:
            comment = None
            if row['memo_name']:
                try:
                    if self.memos is None: raise RuntimeError('Memos unavailable')
                    comment = self.memos.latest_comment(row['memo_name'])
                    if comment: comment['created_at'] = self.iso(comment['created_at'])
                except (RuntimeError, OSError, ValueError, KeyError): result['_partial'] = True
            result['goals'].append({**json.loads(row['payload_json']), 'id':row['id'],'domain':row['domain'],
                'status':row['status'],'memo_name':row['memo_name'],'latest_comment':comment})
        return result

    def dispatch(self, method, path, query, body):
        parts = [unquote(x) for x in path.strip('/').split('/')]
        if method=='GET' and parts==['v1','reviews']:
            return self.sessions(query.get('kind',[None])[0], int(query.get('limit',['14'])[0]))
        if method=='GET' and parts==['v1','stage']: return self.stage()
        if len(parts)==3 and parts[:2]==['v1','reviews'] and method=='GET': return self.detail(parts[2])
        if len(parts)==4 and parts[:2]==['v1','reviews'] and method=='POST' and parts[3]=='preview':
            if set(body)!={'content'} or not isinstance(body['content'],str): raise APIError(422,'validation','正文必须是字符串','content')
            return self.preview(parts[2],body['content'])
        if len(parts)==4 and parts[:2]==['v1','reviews'] and method=='POST' and parts[3]=='finalize':
            self.check(body,{'content':str})
            return self.finalize(parts[2],body['content'])
        if method=='POST' and parts==['v1','stage','cycles']:
            self.check(body,{}, {'starts_at':(str,type(None)),'dry_run':bool})
            try: start=datetime.fromisoformat(body['starts_at']) if body.get('starts_at') else self.now()
            except ValueError: raise APIError(422,'validation','起始时间无效','starts_at') from None
            if start.tzinfo is None: raise APIError(422,'validation','起始时间必须包含时区','starts_at')
            dry=body.get('dry_run',False)
            result=self.stages.create_cycle(start.astimezone(self.config.timezone),dry_run=dry)
            return {'status':'dry-run' if dry else 'created','cycle_id':result}
        if method=='POST' and len(parts)==5 and parts[:3]==['v1','stage','goals'] and parts[4]=='comments':
            self.check(body,{'text':str},{'dry_run':bool})
            return self.stages.comment_goal(parts[3],body['text'],body.get('dry_run',False))
        if method=='POST' and len(parts)==5 and parts[:3]==['v1','stage','cycles']:
            if parts[4]=='goals':
                fields={'domain':str,'goal':str,'progress':str,'deadline':str,'success_criteria':str,'stop_signal':str}
                self.check(body,fields,{'dry_run':bool})
                return self.stages.create_published_goal(parts[3],body['domain'],{k:body[k] for k in fields if k!='domain'},body.get('dry_run',False))
            if parts[4]=='close':
                self.check(body,{'text':str,'outcomes':dict},{'dry_run':bool})
                if any(not isinstance(k,str) or not isinstance(v,str) for k,v in body['outcomes'].items()):
                    raise APIError(422,'validation','目标结果必须是字符串','outcomes')
                with self.state.operation():
                    already=self.state.get_idempotent('stage-close',parts[3]) is not None
                    result=self.stages.close_cycle(parts[3],body['text'],body['outcomes'],body.get('dry_run',False),confirmation_source='app')
                if not already and not body.get('dry_run',False) and self.notifier: self.notifier('stage',parts[3])
                return {key:value for key,value in result.items() if key!='confirmed_from'}
        raise APIError(404,'not_found','接口不存在')


def server(api, token_hash, address):
    if len(token_hash)!=64 or any(c not in '0123456789abcdef' for c in token_hash):
        raise ValueError('invalid HTTP token hash')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def log_error(self, *args): pass

        def respond(self, status, payload):
            partial = payload.pop('_partial',False)
            encoded = json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
            secrets = [getattr(api.memos,'token',''),self.headers.get('Authorization','').removeprefix('Bearer ')]
            for secret in secrets:
                if secret: encoded=encoded.replace(secret.encode(),b'[redacted]')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(encoded)))
            if partial: self.send_header('X-Review-Partial','true')
            self.end_headers();self.wfile.write(encoded)

        def handle_api(self):
            try:
                self.connection.settimeout(10)
                parsed=urlsplit(self.path)
                if self.command=='GET' and parsed.path=='/healthz': return self.respond(200,{'status':'ok'})
                authorization=self.headers.get('Authorization','')
                if not authorization.startswith('Bearer ') or not hmac.compare_digest(hashlib.sha256(authorization[7:].encode()).hexdigest(),token_hash):
                    raise APIError(401,'unauthorized','未授权')
                body={}
                if self.command=='POST':
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=131072: raise APIError(400,'bad_request','请求正文大小无效')
                    body=json.loads(self.rfile.read(length))
                    if not isinstance(body,dict): raise APIError(400,'bad_request','请求正文必须是对象')
                payload=api.dispatch(self.command,parsed.path,parse_qs(parsed.query),body)
                self.respond(200,payload)
            except ValueError as error:
                failure=validation_error(error)
                self.respond(failure.status,{'error':{'code':failure.code,'message':failure.message,'field':failure.field}})
            except APIError as failure:
                self.respond(failure.status,{'error':{'code':failure.code,'message':failure.message,'field':failure.field}})
            except Exception:
                self.respond(502,{'error':{'code':'upstream','message':'复盘服务暂时不可用'}})

        do_GET=handle_api
        do_POST=handle_api

    return ThreadingHTTPServer(address,Handler)


def serve(config,state,memos,host,port,token_hash_file):
    digest=Path(token_hash_file).read_text().strip()
    with server(ReviewAPI(config,state,memos),digest,(host,port)) as http:
        http.serve_forever()
