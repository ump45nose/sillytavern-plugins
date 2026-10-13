"""Require explicit zero checkout total and preserve pre-existing paid cart items."""
import re
import asyncio
from contextlib import suppress
from services.epic_games_service import EpicGames

async def zero_total(container):
    text=await container.locator('body').inner_text(timeout=5000)
    # Epic's free-only checkout omits a Total label.
    amounts=re.findall(r'(?im)^\s*[A-Z]{3}\s+([0-9]+[.,][0-9]{2})\s*$',text)
    if 'This is free. Add it to your library to get started.' in text and amounts and all(float(v.replace(',','.'))==0 for v in amounts):
        if await container.get_by_role('button',name='Add to library',exact=True).count(): return
    # Fail closed if the checkout layout or currency format is unfamiliar.
    match=re.search(r'(?im)^\s*(?:total|order total)\s*:?\s*\n?\s*((?:[A-Z]{2,3}\s*)?[$€£¥]?\s*[0-9]+[.,][0-9]{2})(?:\s|$)',text)
    if not match: raise RuntimeError('Checkout total not identifiable; order not submitted')
    amount=re.search(r'[0-9]+[.,][0-9]{2}',match[1])[0]
    if float(amount.replace(',','.'))!=0: raise RuntimeError('Checkout total is not zero; order not submitted')

async def preserve_cart(self,page,wait_rerender=30):
    cards=page.locator('[data-testid="offer-card-layout-wrapper"]')
    for i in range(await cards.count()):
        if not await cards.nth(i).get_by_text('Free',exact=True).count():
            raise RuntimeError('Cart contains non-free or unrecognized items; cart preserved')
    return True

original_submit=EpicGames._submit_place_order
async def submit(self,button,url):
    container,_=await self._active_purchase_container(self.page)
    await zero_total(container)
    await button.click(timeout=5000,no_wait_after=True)
    await asyncio.sleep(3)
    with suppress(Exception):
        await asyncio.wait_for(self.page.screenshot(path='/opt/epic-helper/app/volumes/after-submit.png'),timeout=5)
    # Hand off directly to upstream challenge/outcome handling; avoid repeated clicks.
    return True
original_confirm=EpicGames._uk_confirm_order
async def confirm(container):
    await zero_total(container)
    return await original_confirm(container)
EpicGames._empty_cart=preserve_cart
EpicGames._submit_place_order=submit
EpicGames._uk_confirm_order=staticmethod(confirm)
