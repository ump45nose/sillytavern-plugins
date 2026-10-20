import json
from datetime import timedelta

import httpx
from pydantic import SecretStr
from fastapi.testclient import TestClient

from hub_api.app import create_app
from hub_api.sources.github import GitHub
from test_records import NOW


def viewer():
    return {'login':'me','today':{'totalCommitContributions':3},
        'month':{'totalCommitContributions':20,'totalRepositoriesWithContributedCommits':2},
        'year':{'totalRepositoriesWithContributedCommits':2,'commitContributionsByRepository':[
            {'contributions':{'pageInfo':{'hasNextPage':False},'nodes':[
                {'occurredAt':(NOW-timedelta(days=i)).isoformat(),'commitCount':1} for i in [0,1,2,4]]}}]},
        'pullRequests':{'pageInfo':{'hasNextPage':False},'nodes':[]}}


def issue(author='them',state='OPEN'):
    return {'id':'I_1','number':1,'title':'Question','url':'https://github.com/o/r/issues/1',
        'state':state,'updatedAt':NOW.isoformat(),'author':{'login':'me'},'repository':{'nameWithOwner':'o/r'},
        'comments':{'nodes':[{'author':{'login':author},'bodyText':'x'*200,'createdAt':(NOW-timedelta(days=2)).isoformat()}]}}


def test_git_normalization_read_only_and_last_comment(settings):
    settings.github_token=SecretStr('SENTINEL-GITHUB')
    calls=[]
    def handle(request):
        calls.append(request)
        if request.url.path=='/notifications':
            return httpx.Response(200,json=[{'reason':'mention','subject':{'type':'Issue','url':'https://api.github.com/repos/o/r/issues/1'},'updated_at':(NOW-timedelta(days=2)).isoformat()}])
        body=json.loads(request.content)
        assert body['query'].startswith('query ')
        if 'HubOverview' in body['query']: return httpx.Response(200,json={'data':{'viewer':viewer()}})
        return httpx.Response(200,json={'data':{'n0':{'issueOrPullRequest':issue()}}})
    with TestClient(create_app(settings,now=lambda:NOW,transport=httpx.MockTransport(handle))) as client:
        response=client.get('/api/v1/modules/git',headers={'Authorization':'Bearer '+settings.dev_token.get_secret_value()})
        data=response.json()['data']
        assert response.json()['status']=='ok' and len(data['waiting'])==1
        assert len(data['waiting'][0]['quote'])==140 and data['activity']['streak_days']==3
        assert settings.github_token.get_secret_value() not in response.text
    assert all(r.method=='GET' or (r.method=='POST' and r.url.path=='/graphql') for r in calls)
    g=GitHub(None,settings,lambda:NOW)
    assert g.waiting_row(issue('ME'),'reply','me') is None
    assert g.waiting_row(issue(state='CLOSED'),'mention','me') is None
    item=issue();item['reviewRequests']={'nodes':[{'requestedReviewer':{'login':'me'}}]}
    assert g.waiting_row(item,'review','me') is not None
    item['reviewRequests']['nodes']=[]
    assert g.waiting_row(item,'review','me') is None


def test_git_block_reasons_unknown_onset_and_streak_coverage(settings):
    g=GitHub(None,settings,lambda:NOW)
    v=viewer()
    v['pullRequests']['nodes']=[dict(issue(),createdAt=(NOW-timedelta(days=5)).isoformat(),isDraft=False,
        mergeable='CONFLICTING',reviewDecision='CHANGES_REQUESTED',latestReviews={'nodes':[{'state':'CHANGES_REQUESTED','submittedAt':NOW.isoformat()}]},
        reviews={'totalCount':0},commits={'nodes':[{'commit':{'statusCheckRollup':{'state':'FAILURE','contexts':{'nodes':[{'name':'build','conclusion':'FAILURE','completedAt':NOW.isoformat()}]}}}}]})]
    rows=g.blocked(v)
    assert {r['reason'] for r in rows}=={'ci_failed','conflict','changes_requested','no_review'}
    assert next(r for r in rows if r['reason']=='conflict')['since'] is None
    v['year']['totalRepositoriesWithContributedCommits']=101
    assert g.activity(v)['streak_days'] is None
    v=viewer();c=v['year']['commitContributionsByRepository'][0]['contributions']
    c['nodes']=c['nodes'][:2];c['pageInfo']['hasNextPage']=True
    assert g.activity(v)['streak_days'] is None
