"""Handle the visible Cloudflare gate without clearing a valid browser session."""
import asyncio,time,json
from contextlib import suppress
from pathlib import Path
from loguru import logger
from settings import settings
from services.epic_authorization_service import EpicAuthorization
from playwright.async_api import TimeoutError

async def click_gate(page):
    for frame in page.frames:
        if 'challenges.cloudflare.com' not in frame.url: continue
        with suppress(Exception):
            element=await frame.frame_element()
            box=await element.bounding_box()
            if box and box['width']>=200 and box['height']>=40:
                await page.mouse.click(box['x']+28,box['y']+box['height']/2)
                logger.info('Clicked visible Cloudflare verification checkbox')
                await page.wait_for_timeout(5000)
                return True
    return False

async def wait_form(self, point_url):
    deadline=time.monotonic()+90
    gates=0
    while time.monotonic()<deadline:
        if await self.page.get_by_text('Welcome back',exact=True).is_visible():
            account=self.page.get_by_text(settings.EPIC_EMAIL,exact=True)
            if await account.is_visible():
                await account.click()
                logger.info('Selected remembered Epic account')
                await self.page.wait_for_timeout(2000)
                continue
        button=self.page.get_by_role('button',name='Done linking',exact=True)
        if await button.is_visible():
            await button.click()
            logger.info('Completed remembered post-login Done linking page')
            raise RuntimeError('Post-login link finished; verify account session')
        if await self.page.locator('#email').is_visible(): return
        if gates<3 and await click_gate(self.page): gates+=1
        await self.page.wait_for_timeout(1000)
    raise TimeoutError('Epic login form unavailable after visible security verification')

original_submit=EpicAuthorization._submit_login_or_accept_challenge
async def submit(self):
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        if await self._has_visible_hcaptcha(): return
        if await self.page.locator('#sign-in').is_visible(): return await original_submit(self)
        await click_gate(self.page)
        await self.page.wait_for_timeout(1000)
    details=await self.page.locator('button').evaluate_all('(els)=>els.map(e=>({id:e.id,text:e.innerText,disabled:e.disabled}))')
    Path('/opt/epic-helper/app/volumes/login-buttons.json').write_text(json.dumps(details))
    raise TimeoutError('Sign-in button absent; saved button states')

EpicAuthorization._wait_for_login_form=wait_form
EpicAuthorization._submit_login_or_accept_challenge=submit

original_outcome=EpicAuthorization._await_login_outcome
async def outcome(self,*args,**kwargs):
    async def finish_linking():
        while True:
            with suppress(Exception):
                button=self.page.get_by_role('button',name='Done linking',exact=True)
                if await button.is_visible():
                    await button.click()
                    logger.info('Completed post-login Done linking page')
                    return
            await asyncio.sleep(0.5)
    monitor=asyncio.create_task(finish_linking())
    try: return await original_outcome(self,*args,**kwargs)
    finally:
        monitor.cancel()
        with suppress(asyncio.CancelledError): await monitor
EpicAuthorization._await_login_outcome=outcome

async def ensure_store_session(page):
    from services.epic_games_service import URL_LOGIN,URL_CLAIM
    await page.goto(URL_CLAIM,wait_until='domcontentloaded')
    for _ in range(10):
        nav=page.locator('egs-navigation')
        if await nav.count() and await nav.get_attribute('isloggedin')=='true':
            logger.success('Reused authenticated Epic store session')
            return
        await page.wait_for_timeout(1000)
    await page.goto(URL_LOGIN,wait_until='domcontentloaded')
    selected_account=False
    policy_continued=False
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        if not policy_continued and '/id/login/correction/privacy-policy' in page.url:
            button=page.get_by_role('button',name='Continue',exact=True)
            if await button.is_visible():
                policy_continued=True
                with suppress(TimeoutError): await button.click(timeout=5000,no_wait_after=True)
                logger.info('Continued past Epic privacy-policy notice')
                await page.wait_for_timeout(2000)
                continue
        navigation=page.locator('egs-navigation')
        if await navigation.count() and await navigation.get_attribute('isloggedin')=='true':
            logger.success('Epic store session verified after SSO redirect')
            return
        if not selected_account and await page.get_by_text('Welcome back',exact=True).is_visible():
            account=page.get_by_text(settings.EPIC_EMAIL,exact=True)
            if await account.is_visible():
                selected_account=True
                with suppress(TimeoutError): await account.click(timeout=5000)
                logger.info('Selected remembered account for store SSO')
                await page.wait_for_timeout(2000)
                continue
        button=page.get_by_role('button',name='Done linking',exact=True)
        if await button.is_visible():
            await button.click()
            logger.info('Completed account linking for store SSO')
        await click_gate(page)
        await page.wait_for_timeout(1000)
    logger.warning('Store SSO stopped at {}',page.url.split('?')[0])
    await page.screenshot(path='/opt/epic-helper/app/volumes/store-sso-failed.png')
    raise RuntimeError('Epic store SSO not confirmed')
