from datetime import date, datetime, timedelta
import re
import math
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request

from .configuration import json_body, preferences
from .modules.crm import assemble as crm_module
from .modules.net import assemble as net_module


TOOL_NAMES = {'antigravity':'Antigravity','claude':'Claude','codex':'Codex',
              'copilot':'Copilot','cursor':'Cursor','grok':'Grok','zai':'Z.ai'}


def limit_label(provider, window):
    name=TOOL_NAMES.get(provider.lower(),provider)
    label=(window or '').strip()
    if re.match(re.escape(name)+r'(?=\W|$)',label,re.IGNORECASE):
        return name+label[len(name):]
    return (name+' '+label).strip()


def day_label(day, today):
    if day==today: return '今天'
    if day==today+timedelta(days=1): return '明天'
    return (f'{day.year}年' if day.year!=today.year else '')+f'{day.month}月{day.day}日'


def reset_subtitle(value, now):
    reset=instant(value)
    if reset is None: return None
    reset=reset.astimezone(ZoneInfo('Asia/Shanghai'))
    today=now.astimezone(reset.tzinfo).date()
    prefix='' if reset.date()==today else day_label(reset.date(),today)+' '
    return prefix+reset.strftime('%H:%M')+' 重置'


def instant(value):
    if not isinstance(value,str) or not value: return None
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        return result if result.tzinfo else None
    except (ValueError,TypeError): return None


def visible(state, now):
    return not state['dismissed'] and (not state['snooze_until'] or instant(state['snooze_until'])<=now)


def calculate(manager):
    """Only inspect bounded source caches. Attention requests never fetch business data."""
    now=manager.now();store=manager.store;p=preferences(store)
    active, rows, scopes = {}, {}, set()
    def cached(identifier):
        item=manager.cache.get(identifier)
        return item['data'] if item and now-instant(item['updated_at'])<=timedelta(hours=24) else None
    def add(identifier,rule,title,module,since=None,subtitle=None,url=None,severity='warn'):
        active[identifier]=since
        rows[identifier]={'id':identifier,'rule':rule,'severity':severity,'title':title,'subtitle':subtitle,'since':since,'target':{'module':module},'url':url}
    token=cached('token')
    if token is not None:
        scopes.add('token-limit')
        limits={}
        for tool in token.get('limits') or []:
            for w in tool.get('windows') or []:
                if w.get('percent') is None: continue
                key=f"token-limit:{tool['tool']}:{w['label']}:{w.get('resets_at') or ''}"
                if tool.get('id'): key += ':'+tool['id']
                if key not in limits or w['percent']>limits[key][1]['percent']: limits[key]=(tool,w)
        for key,(tool,w) in limits.items():
            if w['percent']>=p['token_limit_percent']:
                account = ' · '+tool['account'] if tool.get('account') else ''
                add(key,'token_limit',f"{limit_label(tool['tool'],w['label'])}{account} 额度已用 {w['percent']:g}%",'token',subtitle=reset_subtitle(w.get('resets_at'),now))
    usage=cached('usage')
    subscription_data=cached('subscriptions')
    if subscription_data is not None:
        scopes.add('traffic-low')
    for pool in net_module(usage, subscription_data, now)['pools']:
        total,used=pool.get('total_bytes'),pool.get('used_bytes')
        low=total is not None and total>0 and used is not None and (total-used)/total*100<p['traffic_remaining_percent']
        expires=pool.get('expires_on');days=(date.fromisoformat(expires)-now.date()).days if expires else None
        if low or (days is not None and days<=p['traffic_expiry_days']):
            add('traffic-low:'+pool['id'],'traffic_low',pool['name']+' 流量不足或临近到期','net',
                subtitle=day_label(date.fromisoformat(expires),now.date())+' 到期' if expires else None)
    git=cached('github')
    if git is not None:
        if not git.get('_partial'): scopes.update(('git-waiting','pr-blocked'))
        for field,rule,threshold in [('waiting','git_waiting',timedelta(hours=p['git_reply_hours'])),('blocked','pr_blocked',timedelta(days=p['pr_blocked_days']))]:
            for item in git.get(field) or []:
                active[item['id']]=item.get('since')
                # Unknown conflict onset starts when Hub first sees the condition.
                rows[item['id']]={'id':item['id'],'rule':rule,'severity':'warn','title':item['title'],'subtitle':item['repo'],
                    'since':item.get('since'),'target':{'module':'git'},'url':item['url'],'_threshold':threshold}
    if subscription_data is not None: scopes.add('subs-renew')
    for item in (subscription_data or {}).get('items', []):
        if not item.get('active'): continue
        if item['next_renewal'] and 0<=(date.fromisoformat(item['next_renewal'])-now.date()).days<=p['subs_renew_days']:
            add('subs-renew:'+item['id'],'subs_renew',item['name']+' 即将续费','subs',
                subtitle=day_label(date.fromisoformat(item['next_renewal']),now.date())+' 续费',severity='info')
    crm=cached('crm')
    if crm is not None:
        scopes.add('stale-contact')
        stale=crm_module(crm,None,now,p['stale_contact_days'])['stale']
        if stale: add('stale-contact:summary','stale_contact','有联系人久未联系','crm',subtitle='、'.join(x['name'] or '' for x in stale),severity='info')
    review=cached('review')
    if review is not None:
        scopes.update(('review','stage'))
        for kind in ('daily','weekly'):
            session=review['reviews'].get(kind)
            expires=instant(session.get('expires_at')) if session else None
            if not session or session['status']!='open' or expires is None or expires<=now: continue
            seconds=(expires-now).total_seconds()
            subtitle=f'{math.ceil(seconds/3600)} 小时后过期' if seconds>=3600 else f'{math.ceil(seconds/60)} 分钟后过期'
            label=session['label']
            if kind=='daily':
                day=date.fromisoformat(label);title=f'{day.month}/{day.day} 日报待确认'
            else: title=label+' 周报待确认'
            add(f'review:{kind}:{label}','review_pending',title,'goals',session.get('prepared_at'),subtitle)
        close=review['close'];cycle=review.get('cycle')
        if cycle and close['status'] in ('preclose','awaiting_close'):
            end=instant(cycle['ends_at'])
            frozen=close['status']=='awaiting_close'
            add('stage:close:'+cycle['id'],'stage_close','阶段待结案','goals',cycle.get('preclose_at'),
                '已过结案日，目标已冻结' if frozen else f'{end.month}/{end.day} 结案',severity='critical' if frozen else 'warn')
    scopes.add('source-down')
    for identifier,adapter in manager.adapters.items():
        if adapter.fetch is None: continue
        state=manager.states.get(identifier,{})
        failed=state.get('failed_since')
        item=manager.cache.get(identifier)
        observed=instant((item['data'] or {}).get('observed_at')) if item else None
        updated=observed or (instant(item['updated_at']) if item else None)
        old=updated is not None and now-updated>timedelta(hours=6)
        if (failed is not None and now-failed>timedelta(minutes=30)) or old:
            add('source-down:'+identifier,'source_down',adapter.name+' 同步失败或长时间未更新',
                next((m for m,ss in manager.module_sources.items() if identifier in ss),'attention'),
                (failed if failed is not None else updated).isoformat())
    states=store.observe_attention(active,scopes,now.isoformat())
    output=[]
    for identifier,row in rows.items():
        state=states[identifier];row['since']=state['since']
        threshold=row.pop('_threshold',None)
        if threshold is not None and now-instant(row['since'])<=threshold: continue
        if visible(state,now): output.append(row)
    output.sort(key=lambda r:({'critical':0,'warn':1,'info':2}[r['severity']],r['since'],r['id']))
    return output, states


def register(app,manager,authenticated,now):
    @app.post('/api/v1/attention/{identifier}/dismiss',status_code=204,dependencies=[Depends(authenticated)])
    def dismiss(identifier:str):
        calculate(manager)
        if not manager.store.handle_attention(identifier): raise HTTPException(404)
        from fastapi.responses import Response
        return Response(status_code=204)

    @app.post('/api/v1/attention/{identifier}/snooze',status_code=204,dependencies=[Depends(authenticated)])
    async def snooze(identifier:str,request:Request):
        body=await json_body(request,4096)
        until=instant(body.get('until'))
        if set(body)!={'until'} or until is None or until<=now(): raise HTTPException(400)
        calculate(manager)
        if not manager.store.handle_attention(identifier,until.astimezone(now().tzinfo).isoformat()): raise HTTPException(404)
        from fastapi.responses import Response
        return Response(status_code=204)
