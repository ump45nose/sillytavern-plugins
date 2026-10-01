"""Native Playwright binding for the Epic workflow.

No Playwright import or browser starts at import time. The caller supplies an
authenticated context and trusted obstacle handlers. This binding has no
password/model auto-discovery, no constant recording, and no autonomous retry
of checkout submission. Real-site integration is still unverified.
"""

import asyncio
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from common.interventions import fingerprint
from .catalog import parse_catalog, storefront_owned
from .guard import zero_total
from .obstacles import classify
from .workflow import Paused

STORE = "https://store.epicgames.com/en-US"
PROMOTIONS = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
ALLOWED = {"store.epicgames.com", "www.epicgames.com", "accounts.epicgames.com"}


def clean_target(url):
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname not in ALLOWED
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        raise Paused("unexpected_origin")
    return f"https://{p.hostname}{p.path}"


class BrowserDriver:
    def __init__(
        self,
        context,
        page,
        journal,
        *,
        now=None,
        checkout_evidence=None,
        cart_evidence=None,
    ):
        self.context, self.page, self.journal = context, page, journal
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.offer = None
        self.checkout = None
        self.checkout_button = None
        self.prepared = set()
        self.checkout_evidence = checkout_evidence
        self.cart_evidence = cart_evidence
        self.current_offer_ids = set()

    async def _visible(self, locator):
        try:
            return await locator.count() > 0 and await locator.first.is_visible(
                timeout=500
            )
        except Exception:
            return False

    async def _text(self, container=None, limit=262144):
        container = container or self.page
        # Size is capped inside the browser before transfer.
        value = await container.locator("body").evaluate(
            "(node,limit)=>{const t=node.innerText||'';return t.length>limit?null:t;}",
            limit,
        )
        if not isinstance(value, str):
            raise Paused("page_evidence_too_large")
        return value

    async def _goto(self, url, timeout):
        clean_target(url)
        try:
            await self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=min(45000, int(timeout * 1000)),
            )
        except Exception:
            # A navigation timeout may occur after useful DOM arrived. Require
            # the same expected path and a visible business marker to continue.
            if clean_target(self.page.url) != clean_target(
                url
            ) or not await self._visible(
                self.page.locator('[data-testid="purchase-cta-button"],egs-navigation')
            ):
                raise
        clean_target(self.page.url)

    async def observe(self, phase, *, timeout):
        target = clean_target(self.page.url)
        text = (await self._text()).lower()
        signals = {}
        signals["rate_limited"] = any(
            x in text
            for x in (
                "please wait 24 hours before trying to redeem",
                "unable to download any more free games",
            )
        )
        signals["account_restricted"] = any(
            x in text
            for x in (
                "account has been banned",
                "account is locked",
                "account has been disabled",
            )
        )
        signals["new_terms"] = await self._visible(
            self.page.locator('label[for="agree"]')
        )
        signals["privacy_acceptance"] = "/correction/privacy-policy" in target
        signals["age_confirmation"] = bool(
            re.search(r"date of birth|verify your age|age verification", text)
        )
        signals["account_link"] = await self._visible(
            self.page.get_by_role("button", name="Done linking", exact=True)
        )
        signals["security_setting"] = "/id/login/mfa/add" in target
        signals["visible_captcha"] = (
            await self._visible(
                self.page.locator(
                    'iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"]'
                )
            )
            or "verify you are human" in text
        )
        signals["mfa_required"] = (
            "/id/login/mfa" in target and not signals["security_setting"]
        )
        signals["login_required"] = await self._visible(
            self.page.locator("#email,#password")
        )
        signals["remembered_account"] = "welcome back" in text and "/id/" in target
        signals["device_modal"] = "device not supported" in text
        # No generic overlay flag from an arbitrary Continue label.
        signals["ready"] = not any(signals.values())
        challenge_sources = []
        for frame in self.page.frames[:16]:
            source = getattr(frame, "url", "")
            if "hcaptcha" in source or "challenges.cloudflare.com" in source:
                challenge_sources.append(source)
        # Bind a grant to current visible content/challenge identity. Raw source
        # URLs/text remain local memory and are never written to checkpoint.
        digest = fingerprint(
            target,
            phase,
            sorted(k for k, v in signals.items() if v),
            text
            if any(
                signals.get(k)
                for k in (
                    "new_terms",
                    "privacy_acceptance",
                    "age_confirmation",
                    "account_link",
                    "security_setting",
                )
            )
            else "",
            challenge_sources,
        )
        return classify(
            signals, phase=phase, target=target, evidence_fingerprint=digest
        )

    async def recover(self, obstacle, *, timeout):
        if obstacle.kind in {"delayed_result", "navigation_partial", "stale_locator"}:
            await asyncio.sleep(min(1, timeout))
            return
        if obstacle.kind == "browser_page_rebuild":
            old = self.page
            self.page = await self.context.new_page()
            await self._goto(obstacle.target, timeout)
            await old.close()
            return
        # Remembered-account selection, SSO and device warnings need explicit
        # binding/context; never click a generic Yes/Continue here.
        raise Paused("recovery_binding_pending")

    async def inventory(self, *, timeout):
        await self._goto(STORE + "/free-games", timeout)
        raw = await self.page.evaluate(
            """async ({url,max,ms})=>{
              const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),ms);
              try {
                const response=await fetch(url,{signal:controller.signal,redirect:'error'});
                if(!response.ok||!response.body)throw Error('catalog_unavailable');
                const reader=response.body.getReader(),decoder=new TextDecoder();
                let length=0,text='';
                while(true){
                  const {done,value}=await reader.read();if(done)break;
                  length+=value.byteLength;
                  if(length>max){await reader.cancel();throw Error('catalog_too_large');}
                  text+=decoder.decode(value,{stream:true});
                }
                return JSON.parse(text+decoder.decode());
              } finally {clearTimeout(timer);}
            }""",
            {
                "url": PROMOTIONS,
                "max": 4 * 1024 * 1024,
                "ms": min(30000, int(timeout * 1000)),
            },
        )
        inventory = parse_catalog(raw, now=self.now())
        self.current_offer_ids = (
            {offer.id for offer in inventory.offers} if inventory.complete else set()
        )
        return inventory

    async def open_offer(self, offer, *, timeout):
        self.offer = offer
        await self._goto(offer.url, timeout)

    async def verify(self, offer, *, timeout):
        await self._goto(offer.url, timeout)
        button = self.page.locator('[data-testid="purchase-cta-button"]').first
        if not await self._visible(button):
            return "unknown"
        text = (await button.inner_text(timeout=min(5000, int(timeout * 1000)))).strip()
        if storefront_owned(text):
            return "owned"
        if text.casefold() in {
            "get",
            "free",
            "add to cart",
            "buy now",
            "获取",
            "免费",
            "加入购物车",
        }:
            return "not_owned"
        return "unknown"

    async def prepare_cart(self, *, timeout):
        await self._goto(STORE + "/cart", timeout)

    async def inspect_cart(self, *, timeout):
        cards = self.page.locator('[data-testid="offer-card-layout-wrapper"]')
        count = await cards.count()
        if count > 100:
            return "unknown"
        if count == 0:
            text = (await self._text()).lower()
            return (
                "empty_confirmed"
                if any(x in text for x in ("your cart is empty", "购物车为空"))
                else "unknown"
            )
        if self.cart_evidence is None:
            return "unknown"
        # A word Free in a product title is not semantic price evidence. This
        # binding must be supplied by a separately verified DOM/response parser.
        items = await self.cart_evidence(self.page, timeout=timeout)
        if not isinstance(items, list) or len(items) != count:
            return "unknown"
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("offer_id") not in self.current_offer_ids
                or type(item.get("price_minor")) is not int
                or item["price_minor"] != 0
                or not isinstance(item.get("currency"), str)
                or not item["currency"]
            ):
                return "paid_or_unknown"
        return "only_free_confirmed"

    async def prepare_checkout(self, offer, *, timeout):
        if offer.id in self.prepared:
            raise Paused("checkout_already_started")
        await self.open_offer(offer, timeout=timeout)
        button = self.page.locator('[data-testid="purchase-cta-button"]').first
        text = (await button.inner_text(timeout=5000)).strip().casefold()
        if text not in {
            "get",
            "free",
            "add to cart",
            "buy now",
            "获取",
            "免费",
            "加入购物车",
        }:
            raise Paused("purchase_control_unknown")
        self.prepared.add(offer.id)
        await button.click(timeout=min(5000, int(timeout * 1000)))
        if text in {"add to cart", "加入购物车"}:
            await self._goto(STORE + "/cart", timeout)
            # Recheck the full cart after adding the free item, before checkout.
            if await self.inspect_cart(timeout=timeout) != "only_free_confirmed":
                raise Paused("cart_preserved")
            checkout = self.page.get_by_role(
                "button", name=re.compile(r"^(Check Out|Checkout|结账)$", re.I)
            )
            if not await self._visible(checkout):
                raise Paused("checkout_control_unknown")
            await checkout.first.click(timeout=min(5000, int(timeout * 1000)))

    async def _checkout_controls(self):
        candidates = []
        for container in [
            self.page,
            *[f for f in self.page.frames if f is not self.page.main_frame],
        ]:
            url = getattr(container, "url", "")
            if container is not self.page:
                try:
                    parsed = urlsplit(url)
                    if parsed.scheme != "https" or not (
                        parsed.hostname == "epicgames.com"
                        or parsed.hostname.endswith(".epicgames.com")
                    ):
                        continue
                except Exception:
                    continue
            locator = container.get_by_role(
                "button", name=re.compile(r"^(Place Order|Add to library)$", re.I)
            )
            count = await locator.count()
            if count > 8:
                raise Paused("checkout_controls_ambiguous")
            for i in range(count):
                if await locator.nth(i).is_visible():
                    candidates.append((container, locator.nth(i)))
        # Do not guess which of multiple simultaneously visible order controls is active.
        return candidates

    async def checkout_total(self, *, timeout):
        controls = await self._checkout_controls()
        # Main frame is excluded above; multiple remaining controls are ambiguous.
        if len(controls) != 1:
            return "unknown"
        container, button = controls[0]
        if self.offer is None or self.checkout_evidence is None:
            return "unknown"
        evidence = await self.checkout_evidence(container, timeout=timeout)
        if (
            not isinstance(evidence, dict)
            or evidence.get("complete") is not True
            or evidence.get("offer_ids") != [self.offer.id]
        ):
            return "unknown"
        text = await self._text(container)
        label = (await button.inner_text()).strip().casefold()
        if not zero_total(text, add_to_library=label == "add to library"):
            return "unknown"
        self.checkout, self.checkout_button = container, button
        return "explicit_zero"

    async def submit_once(self, offer, *, timeout):
        if (
            self.checkout_button is None
            or await self.checkout_total(timeout=timeout) != "explicit_zero"
        ):
            raise Paused("checkout_price_unconfirmed")
        await self.checkout_button.click(timeout=min(5000, int(timeout * 1000)))
