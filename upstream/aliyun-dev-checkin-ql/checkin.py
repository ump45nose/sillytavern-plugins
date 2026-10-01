"""Aliyun community sign-in and claim only; no generated posts or interactions."""
import sys, os, importlib.util, time, json
from pathlib import Path
if not any(os.getenv(k) for k in ('ALIYUN_ACCOUNTS','ALIYUN_COOKIE','ALIYUN_WEB_DATA','aliyunWeb_data','ALIYUN_USER','ALIYUN_PHONE')):
    sys.exit('待配置：在青龙环境变量添加 ALIYUN_COOKIE（开发者社区 Cookie）')
p=Path(os.environ.get('ALIYUN_DAILY_PATH', 'aliyun_dev/daily.py')).expanduser().resolve()
if not p.is_file():
    sys.exit(f'Upstream script not found: {p}; set ALIYUN_DAILY_PATH')
spec=importlib.util.spec_from_file_location('aliyun_daily',p)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
def sign_only(self):
    before=self.get_user_score()
    if before is None: raise RuntimeError('Unable to read account score')
    verified=0
    failures=[]
    self.cfg.max_retries=1  # never replay a timed-out sign/claim automatically
    self.stats['score_before']=before
    for group in m.TASK_GROUPS:
        def detail():
            response=self.request('GET',f'{m.API}/sign/getUserSpaceSignInDetail',params={'excode':group['code']})
            return response.get('data') or {}
        d=detail()
        gid=d.get('taskGroupId')
        if not gid:
            self.stats['sign_skip']+=1
            continue
        today=next((x for x in d.get('signInList',[]) if x.get('today')),None)
        if not today:
            failures.append(group['name']+': no current-day state');continue
        if str(today.get('status'))!='2':
            body=self.get_tasks(str(gid))
            if not body:
                failures.append(group['name']+': no current-day task');continue
            body['activityCode']=body.get('actionCode')
            self.request('POST',f'{m.API}/task/actionLog',data=body,headers={'Content-Type':'application/x-www-form-urlencoded;charset=utf-8'})
            # The task can finish before the sign-in detail becomes consistent.
            # Re-read only; never replay the state-changing actionLog request.
            for _ in range(30):
                time.sleep(2)
                d=detail()
                today=next((x for x in d.get('signInList',[]) if x.get('today')),None)
                if today and str(today.get('status'))=='2': break
        if not today or str(today.get('status'))!='2':
            failures.append(group['name']+': sign-in not confirmed');continue
        verified+=1
        print(f"{group['name']}: 今日签到已核实",flush=True)
        bonus=self.request('GET',f'{m.API}/sign/assessSignInBonusQualification',params={'taskGroupId':gid})
        if str(bonus.get('code'))=='200':
            result=self.request('POST',f'{m.API}/sign/receiveSignInBonus',data={'taskGroupId':gid},headers={'Content-Type':'application/x-www-form-urlencoded;charset=utf-8'})
            if str(result.get('code'))!='200':failures.append(group['name']+': bonus unconfirmed')
    pending=self.get_pending_score()
    if pending:
        result=self.receive_all_pending()
        if not result.get('ok'):failures.append('pending points unconfirmed')
    after=self.get_user_score()
    if after is None: raise RuntimeError('Unable to verify final score')
    self.stats.update(score_now=after,score_delta=after-before)
    print(f'阿里云签到核实 {verified} 个社区：before={before}, after={after}, delta={after-before}',flush=True)
    if failures or not verified:raise RuntimeError('; '.join(failures) or 'No verified sign-in')
    self.stats['sign_ok']=verified
m.AliyunDevClient.run_earn_tasks=sign_only
m.AliyunDevClient.run_cleanup=lambda self: None
original_run=m.AliyunDevClient.run
outcomes=[]
def strict_run(self, *, force_phase=None):
    result=original_run(self, force_phase=force_phase)
    if not self.cfg.dry_run and not self.stats.get('sign_ok'):
        result['ok']=False
        result['message']=result.get('message') or 'Sign-in not confirmed'
    message=str(result.get('message') or '')
    outcomes.append({'success':bool(result.get('ok')) and bool(self.stats.get('sign_ok')),
                     'reason':None if result.get('ok') and self.stats.get('sign_ok') else 'authentication_invalid' if 'Cookie' in message and '失效' in message else 'sign_in_unconfirmed'})
    return result
m.AliyunDevClient.run=strict_run
code=m.main()
success=bool(outcomes) and all(x['success'] for x in outcomes) and code in (0,None)
print('BENEFIT_RESULT='+json.dumps({'platform':'aliyun','success':success,
      'reason':next((x['reason'] for x in outcomes if not x['success']),None) if outcomes else 'no_verified_result'},ensure_ascii=False))
sys.exit(0 if success else 1)
