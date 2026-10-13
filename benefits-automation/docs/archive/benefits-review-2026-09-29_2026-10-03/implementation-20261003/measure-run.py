import subprocess,os,time,pathlib,json,sys
root=pathlib.Path('/proc'); env=dict(os.environ)
p=subprocess.Popen(sys.argv[1:],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env=env)
peak=0; max_children=0
while p.poll() is None:
 rows={}
 for f in root.glob('[0-9]*/stat'):
  try:
   raw=f.read_text(); end=raw.rfind(')'); fields=raw[end+2:].split()
   rows[int(f.parent.name)]=(int(fields[1]),int(fields[21])*os.sysconf('SC_PAGE_SIZE'))
  except (OSError,ValueError,IndexError): pass
 children={p.pid}; changed=True
 while changed:
  expanded=children|{pid for pid,(parent,_) in rows.items() if parent in children}
  changed=expanded!=children; children=expanded
 peak=max(peak,sum(rows.get(pid,(0,0))[1] for pid in children))
 max_children=max(max_children,len(children))
 time.sleep(1)
output=p.stdout.read(); print(output.strip())
print(json.dumps({'measurement':'summed_process_RSS_shared_pages_may_repeat','peak_MiB':round(peak/1024/1024,1),'max_processes':max_children,'exit_code':p.returncode}))
sys.exit(p.returncode)
