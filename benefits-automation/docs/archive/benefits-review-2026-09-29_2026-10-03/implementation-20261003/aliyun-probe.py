import sys,logging,json
sys.path.insert(0,'/home/yuwk/benefits-automation')
from platforms.aliyun.adapter import load_provider
from common.cookiecloud import cookie_header
logging.disable(logging.CRITICAL)
p=load_provider('/vol2/1000/Docker/qinglong/data/scripts/WillpowerJin_ql-scripts_main/aliyun_dev/daily.py')
a=p.Account(name='default',cookie=cookie_header('/vol2/1000/Docker/benefits-automation/cookiecloud.json','developer.aliyun.com',('login_aliyunid_ticket',)))
c=p.AliyunDevClient(a,p.AppConfig(accounts=[a],timeout=20,max_retries=1),{})
c.session.trust_env=False
try:
 for g in p.TASK_GROUPS:
  code=g['code'];r=c.request('GET',p.API+'/sign/getUserSpaceSignInDetail',params={'excode':code})
  d=r.get('data');print(json.dumps({'group':code,'code':r.get('code'),'data_type':type(d).__name__,'keys':list(d) if isinstance(d,dict) else [],'groupid_type':type(d.get('taskGroupId')).__name__ if isinstance(d,dict) else None}))
 print('pending',type(c.get_pending_score()).__name__)
finally:c.session.close()
