import asyncio, json, os, re, sys
from pathlib import Path
from urllib.parse import urlparse
from loguru import logger
from services.browser_context import open_browser_context
from services.epic_authorization_service import EpicAuthorization

os.umask(0o077)
os.environ.pop("DISPLAY", None) # base image has no running X server; Camoufox owns Xvfb
def redact(s):
    for key in ('EPIC_EMAIL','EPIC_PASSWORD','GLM_API_KEY'):
        value=os.getenv(key)
        if value: s=s.replace(value,'[REDACTED]')
    s=re.sub(r'https?://[^\s\"\']+', lambda m: m[0].split('?')[0], s)
    return s
logger.remove()
logger.add(lambda msg: print(redact(str(msg)),end='',flush=True), format='{time:HH:mm:ss} {level} {message}', diagnose=False)
import login_compat
from settings import settings
settings.AUTH_MAX_ATTEMPTS=1
async def main():
    async with open_browser_context(headless='virtual') as browser:
        page=browser.pages[0] if browser.pages else await browser.new_page()
        auth=EpicAuthorization(page)
        probe=await browser.new_page()
        ok=await EpicAuthorization(probe)._has_account_session()
        await probe.close()
        if not ok: ok=await auth.invoke()
        # Server-side account session check also handles completed-login redirects
        # whose analytics event is absent in the current Epic frontend.
        if not ok:
            probe=await browser.new_page()
            ok=await EpicAuthorization(probe)._has_account_session()
            await probe.close()
        if not page.is_closed():
            await page.screenshot(path='/opt/epic-helper/app/volumes/login-result.png')
        if not ok: raise RuntimeError('Epic authentication failed')
        await login_compat.ensure_store_session(page)
        if len(sys.argv)>1 and sys.argv[1]=='claim':
            import claim_guard
            from services.epic_games_service import EpicAgent
            from services.epic_collection_summary_service import collect_epic_games_with_summary
            summary=await collect_epic_games_with_summary(EpicAgent(await browser.new_page()))
            data=summary.model_dump(mode='json')
            # Order history can return a non-JSON gate while the authenticated
            # storefront still shows ownership. Confirm each unresolved game
            # separately; a disabled button alone is not enough.
            ui_confirmed=[]
            if summary.unconfirmed_promotions and not summary.failed_promotions:
                check=await browser.new_page()
                try:
                    for game in summary.unconfirmed_promotions:
                        if urlparse(game.url).hostname!='store.epicgames.com': break
                        await check.goto(game.url,wait_until='domcontentloaded',timeout=45000)
                        button=check.locator('[data-testid="purchase-cta-button"]')
                        await button.wait_for(timeout=20000)
                        if (await button.inner_text()).strip()!='In Library': break
                        ui_confirmed.append(game)
                finally:
                    await check.close()
            if ui_confirmed:
                data['storefront_confirmed_promotions']=[g.model_dump(mode='json') for g in ui_confirmed]
            confirmed=len(ui_confirmed)==len(summary.unconfirmed_promotions)
            success=bool(summary.all_promotions) and not summary.failed_promotions and confirmed and (not summary.error_message or bool(ui_confirmed))
            return {'authenticated':True,'phase':'claim','success':success,'verification':'storefront-library' if ui_confirmed else 'order-history','summary':data}
        return {'authenticated':True, 'phase':'login','success':True}
try:
    result=asyncio.run(asyncio.wait_for(main(),1200))
except Exception as e:
    result={'success':False,'error':redact(str(e)),'type':type(e).__name__}
    if hasattr(e,'summary'): result['summary']=e.summary.model_dump(mode='json')
Path('/opt/epic-helper/app/volumes/'+('claim' if len(sys.argv)>1 and sys.argv[1]=='claim' else 'login')+'-result.json').write_text(json.dumps(result))
print(json.dumps(result),flush=True)
sys.exit(0 if result.get('success') else 1)
