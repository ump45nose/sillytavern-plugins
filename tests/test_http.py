"""Exercise the actual private HTTP boundary with temporary state and fake Memos."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from zoneinfo import ZoneInfo

import pytest
import yaml

from review.domain import TimeWindow
from review.http import ReviewAPI, server
from review.state import StateRepository
from test_state_and_reviews import FakeMemos


class ReadMemos(FakeMemos):
    token = 'SENTINEL-MEMOS-TOKEN'
    broken = False

    def latest_comment(self, name):
        if self.broken: raise RuntimeError(self.token)
        return {'text':'用户进度原文', 'created_at':'2026-10-20T08:00:00Z'}


@pytest.fixture
def api(tmp_path):
    policy=yaml.safe_load((Path(__file__).parents[1]/'config/review.yaml').read_text())
    jobs=tmp_path/'jobs.json';jobs.write_text('{"jobs": []}')
    config=SimpleNamespace(policy=policy, timezone=ZoneInfo('Asia/Shanghai'), flags=SimpleNamespace(tasks=False),
        values={'REVIEW_DAILY_TIME':'21:30','REVIEW_WEEKLY_TIME':'SUN 21:50'},
        path=lambda name: jobs if name=='REVIEW_JOBS_FILE' else tmp_path/'executions.db')
    state=StateRepository(tmp_path/'review.db');state.initialize()
    result=ReviewAPI(config,state,ReadMemos())
    now=result.now();day=now.replace(hour=0,minute=0,second=0,microsecond=0)
    result.daily.prepare(TimeWindow(day,day.replace(hour=21,minute=30)),[],[])
    return result


@pytest.fixture
def client(api):
    token='SENTINEL-HTTP-TOKEN'
    http=server(api,sha256(token.encode()).hexdigest(),('127.0.0.1',0))
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    opener=build_opener(ProxyHandler({}))
    def send(path,body=None,authorized=True):
        headers={'Authorization':'Bearer '+token} if authorized else {}
        if body is not None: headers['Content-Type']='application/json'
        req=Request(f'http://127.0.0.1:{http.server_port}'+path,headers=headers,
                    data=json.dumps(body).encode() if body is not None else None)
        try: response=opener.open(req,timeout=5)
        except HTTPError as error: response=error
        with response:
            raw=response.read().decode()
            assert token not in raw and api.memos.token not in raw
            return response.status,json.loads(raw),response.headers
    yield send
    http.shutdown();http.server_close();thread.join()


def test_auth_list_detail_preview_errors_and_no_business_writes(api,client):
    assert client('/v1/reviews',authorized=False)[0]==401
    code,payload,_=client('/v1/reviews?kind=daily&limit=14')
    assert code==200 and len(payload['items'])==1
    identifier=payload['items'][0]['id']
    code,detail,_=client('/v1/reviews/'+identifier)
    assert code==200 and detail['status']=='open' and detail['delivered'] is None
    assert set(detail['material'])=={'sections','template'}
    assert detail['rules']['auto_fields']==['健康','财务']
    code,error,_=client('/v1/reviews/'+identifier+'/preview',{'content':detail['material']['template']})
    assert code==422 and error['error']['field']=='一句话总结今天'
    assert error['error']['message']=='日报必须包含一句话总结'
    text=f'#日报 {identifier.split(":",1)[1]}\n一句话总结今天：完成真实交付\n留痕：保留我的原文'
    code,result,_=client('/v1/reviews/'+identifier+'/preview',{'content':text})
    assert code==200 and '保留我的原文' in result['content']
    assert api.memos.created==[] and api.state.load_session(identifier)['status']=='open'
    assert client('/v1/reviews/missing')[0]==404
    assert client('/v1/reviews?limit=101')[0]==400
    with api.state.connect() as db:
        db.execute('UPDATE review_sessions SET expires_at=?',((api.now()-timedelta(seconds=1)).isoformat(),))
    assert client('/v1/reviews')[1]['items'][0]['status']=='expired'
    code,error,_=client('/v1/reviews/'+identifier+'/preview',{'content':text})
    assert code==409 and error['error']['code']=='expired'


def seed_stage(api):
    cycle=api.stages.create_cycle(api.now()-timedelta(days=10))
    api.stages.publish_mainline(None,{k:'原文' for k in ('direction','purpose','meaning','status','recent_change')})
    goal=api.stages.add_goal(cycle,'事业',{'goal':'交付','progress':'还在做','deadline':'2026-12-31','success_criteria':'上线','stop_signal':'取消'})
    api.stages.publish_goal(goal)
    return cycle,goal


def test_stage_all_close_states_comments_and_no_read_mutation(api,client):
    assert client('/v1/stage')[1]['cycle'] is None
    cycle,goal=seed_stage(api)
    code,result,headers=client('/v1/stage')
    assert code==200 and result['cycle']['index']==1 and result['cycle']['day']==11
    assert result['close']['status']=='none'
    assert result['goals'][0]['latest_comment']['created_at']=='2026-10-20T16:00:00+08:00'
    assert result['goals'][0]['progress']=='还在做'
    assert '_partial' not in result and headers.get('X-Review-Partial') is None
    initial=api.now()
    api.now=lambda:initial+timedelta(days=31,hours=1)
    result=client('/v1/stage')[1]
    assert result['close']['status']=='preclose' and result['close']['template']==api.stages.close_template(cycle)
    assert api.state.get_idempotent('stage-preclose',cycle) is None
    api.now=lambda:initial+timedelta(days=33)
    assert client('/v1/stage')[1]['close']['status']=='awaiting_close'
    with api.state.connect() as db: db.execute("UPDATE stage_cycles SET status='closed' WHERE id=?",(cycle,))
    result=client('/v1/stage')[1]
    assert result['cycle'] is None and result['goals']==[] and result['close']['status']=='closed'


def test_comments_failure_is_partial_and_sanitized(api,client):
    seed_stage(api);api.memos.broken=True
    code,result,headers=client('/v1/stage')
    assert code==200 and headers['X-Review-Partial']=='true'
    assert result['goals'][0]['latest_comment'] is None


def test_weekly_legacy_material_comes_from_frozen_rows(api,client):
    end=api.now().replace(hour=21,minute=50,second=0,microsecond=0)
    identifier,_=api.weekly.prepare(TimeWindow(end-timedelta(days=6),end),[],[])
    code,detail,_=client('/v1/reviews/'+identifier)
    assert code==200 and set(detail['material'])=={'sections','template'}
    assert detail['material']['template'].startswith('#周报 ')
    assert detail['rules']['auto_fields']==['身体']
    assert 'summary_max_chars' not in detail['rules']
    code,error,_=client('/v1/reviews/'+identifier+'/preview',{'content':detail['material']['template']})
    assert code==422 and error['error']['message']=='周报至少需要一项用户确认内容'
    assert api.memos.created==[]


def test_delivered_exposes_only_response_of_successful_execution(api,client):
    import sqlite3
    job={'id':'daily-job','name':'personal-review-daily-2130'}
    jobs=api.config.path('REVIEW_JOBS_FILE');jobs.write_text(json.dumps({'jobs':[job]}))
    identifier=api.sessions('daily')['items'][0]['id']
    stamp=api.now().replace(microsecond=0)
    folder=jobs.parent/'output'/'daily-job';folder.mkdir(parents=True)
    output=folder/(stamp.strftime('%Y-%m-%d_%H-%M-%S')+'.md')
    output.write_text('## Prompt\nPRIVATE-PROMPT\n## Response\n实际投递正文')
    with sqlite3.connect(api.config.path('REVIEW_HERMES_EXECUTIONS_DB')) as db:
        db.execute('CREATE TABLE executions(job_id,status,error,started_at,finished_at)')
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?)',('daily-job','completed',None,stamp.isoformat(),(stamp+timedelta(seconds=2)).isoformat()))
    code,detail,_=client('/v1/reviews/'+identifier)
    assert code==200 and detail['delivered']['text']=='实际投递正文'
    assert 'PRIVATE-PROMPT' not in json.dumps(detail)
    job['last_run_at']=(stamp+timedelta(seconds=2)).isoformat();job['last_delivery_error']='failed'
    jobs.write_text(json.dumps({'jobs':[job]}))
    assert client('/v1/reviews/'+identifier)[1]['delivered'] is None
