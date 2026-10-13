import sys,json
sys.path.insert(0,'/home/yuwk/benefits-review/acceptance-20261003')
from run_acceptance import invoke
r=invoke('aliyun',{'COOKIECLOUD_CONFIG':'/vol2/1000/Docker/benefits-automation/cookiecloud.json','ALIYUN_UPSTREAM_PATH':'/vol2/1000/Docker/qinglong/data/scripts/WillpowerJin_ql-scripts_main/aliyun_dev/daily.py'},['--execute'],480)
