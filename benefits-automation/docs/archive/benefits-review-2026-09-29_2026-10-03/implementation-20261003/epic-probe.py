import sys,json,asyncio,os
from pathlib import Path
sys.path.insert(0,'/home/yuwk/benefits-automation')
from platforms.epic.browser_driver import BrowserDriver
from platforms.epic.native import execute
original_ready=BrowserDriver._ready
async def ready(self,container,phase,text):
 r=await original_ready(self,container,phase,text)
 if phase=='product':
  loc=container.locator('[data-testid="purchase-cta-button"]')
  try: print(json.dumps({'probe':'ready','ready':r,'count':await loc.count(),'visible':await loc.first.is_visible(timeout=500),'box':await loc.first.bounding_box()}))
  except Exception as e: print(type(e).__name__,str(e)[:200])
 return r
BrowserDriver._ready=ready
original=BrowserDriver.observe
async def observe(self,phase,**kwargs):
 r=await original(self,phase,**kwargs)
 if phase == 'product':
  Path('/home/yuwk/benefits-review/implementation-20261003/epic-product.private.html').write_text(await self.page.content())
  print(json.dumps(await self.page.evaluate("()=>({testids:[...document.querySelectorAll('[data-testid]')].map(x=>x.dataset.testid).filter(x=>/buy|purchase|price|cta|offer|cart/i.test(x)),controls:[...document.querySelectorAll('button,a,[role=button]')].filter(x=>/^(get|free|buy now|add to cart|in library|owned)$/i.test(x.innerText.trim())).map(x=>({tag:x.tagName,role:x.getAttribute('role'),testid:x.getAttribute('data-testid'),text:x.innerText,cls:x.className}))})")))
 print(json.dumps({'phase':phase,'obstacle':r.kind if r else None,'target':r.target if r else None,'dom':await self.page.evaluate("()=>({title:document.title,path:location.pathname,nav:[...document.querySelectorAll('egs-navigation')].map(x=>x.getAttribute('isloggedin')),email:!!document.querySelector('#email'),password:!!document.querySelector('#password'),buttons:[...document.querySelectorAll('button')].map(x=>x.innerText).filter(x=>['Continue','Sign In','Done linking','Sign in','Login','Get'].includes(x)).slice(0,8),captcha:[...document.querySelectorAll('iframe')].map(x=>x.src).filter(x=>/hcaptcha|cloudflare/.test(x)).map(x=>new URL(x).hostname)})")}))
 return r
BrowserDriver.observe=observe
os.environ['TMPDIR']='/home/yuwk/benefits-review/implementation-20261003'
print(asyncio.run(execute({'run_id':'probe','account':'default','platform':'epic','business_date':'2026-10-03'},json.load(open('/vol2/1000/Docker/benefits-automation/epic.json')),'/vol2/1000/Docker/benefits-automation/acceptance-20261003/state/epic/default')).reason)
