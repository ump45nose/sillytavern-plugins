exec(open('/home/yuwk/benefits-review/implementation-20261003/aliyun-probe.py').read().split('try:\n for g')[0])
try:
 r=c.request('GET',p.API+'/sign/getUserSpaceSignInDetail',params={'excode':''});g=r['data']['taskGroupId']
 for route in ('assessSignInBonusQualification',):
  r=c.request('GET',p.API+'/sign/'+route,params={'taskGroupId':g});print(json.dumps({'code':r.get('code'),'data':r.get('data'),'message':str(r.get('message',''))[:120]}))
finally:c.session.close()
