from pathlib import Path
import yaml,requests,subprocess,shutil
backup=Path('/home/yuwk/benefits-review/backups/rewards-extra-20260929')
p=Path('/etc/ShellCrash/yamls/rules.yaml');effective=Path('/tmp/ShellCrash/config.yaml')
d=yaml.safe_load(effective.read_text());s=requests.Session();s.trust_env=False;s.headers['Authorization']='Bearer '+str(d.get('secret',''));u='http://127.0.0.1:9999'
before={k:v.get('now') for k,v in s.get(u+'/proxies',timeout=10).json()['proxies'].items() if v.get('now')}
rules=['DOMAIN,www.bing.com,🧭 廉价手动','DOMAIN,rewards.bing.com,🧭 廉价手动','DOMAIN,edgeservices.bing.com,🧭 廉价手动']
src=p.read_text();new=[r for r in rules if '- '+r not in src];p.write_text(src+'\n# Rewards browser: dashboard, Bing and flyout use the selected proxy.\n'+''.join('- '+r+'\n' for r in new))
src=effective.read_text().replace('rules:\n','rules:\n'+''.join(' - '+r+'\n' for r in rules if r not in d['rules']),1);effective.write_text(src)
check=subprocess.run(['/tmp/ShellCrash/CrashCore','-t','-d','/etc/ShellCrash','-f',str(effective)],capture_output=True)
if check.returncode:
 shutil.copyfile(backup/'rules.yaml',p);shutil.copyfile(backup/'config.yaml',effective);raise SystemExit('validation failed; restored')
r=s.put(u+'/configs',json={'path':str(effective)},timeout=20);r.raise_for_status()
after={k:v.get('now') for k,v in s.get(u+'/proxies',timeout=10).json()['proxies'].items() if v.get('now')};assert before==after,'Unexpected group selection change'
actual=s.get(u+'/rules',timeout=10).json()['rules'];print('Verified targeted rules:',[{k:x[k] for k in ['type','payload','proxy']} for x in actual if x.get('payload') in ['www.bing.com','rewards.bing.com','edgeservices.bing.com']])
for c in s.get(u+'/connections',timeout=10).json()['connections']:
 if c.get('metadata',{}).get('host') in ['www.bing.com','rewards.bing.com','edgeservices.bing.com']:s.delete(u+'/connections/'+c['id'],timeout=5)
print('Core config valid; group selections unchanged')
