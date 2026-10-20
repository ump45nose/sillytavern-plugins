"""Native Playwright binding for the Epic workflow.

No Playwright import or browser starts at import time. The caller supplies an
authenticated context and trusted obstacle handlers. This binding has no
password/model auto-discovery, no constant recording, and no autonomous retry
of checkout submission. Site acceptance is recorded separately from code checks.
"""

import asyncio
import hashlib
import math
import uuid
from dataclasses import replace
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from common.interventions import fingerprint
from .catalog import parse_catalog, storefront_owned
from .challenges import response_kind
from .guard import zero_total
from .obstacles import classify
from .workflow import Paused

STORE = "https://store.epicgames.com/en-US"
CHECKOUT = "https://store.epicgames.com/purchase"
PROMOTIONS = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
ALLOWED = {"store.epicgames.com", "www.epicgames.com", "accounts.epicgames.com"}
PURCHASE_NAMES = re.compile(
    r"^(Get|Free|Add to cart|Buy now|In library|In your library|获取|免费|加入购物车|已在库中)$",
    re.I,
)
DIRECT_PURCHASE_NAMES = re.compile(
    r"^(Get|Free|Buy now|In library|In your library|获取|免费|已在库中)$", re.I)
CART_PURCHASE_NAMES = re.compile(r"^(Add to cart|加入购物车)$", re.I)


def _challenge_frame(container):
    """A rendered challenge frame counts even when its checkbox iframe is invisible."""
    frames = list(getattr(container, "frames", []) or [])
    if not frames:
        frames = [container, *list(getattr(container, "child_frames", []) or [])]
    for frame in frames:
        url = getattr(frame, "url", "") or ""
        host = urlsplit(url).hostname or ""
        if host == "challenges.cloudflare.com":
            return True
        if host == "hcaptcha.com" or host.endswith(".hcaptcha.com"):
            if "frame=challenge" in url:
                return True
    return False


def clean_target(url, *, checkout=False):
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or not (
            p.hostname in ALLOWED
            or checkout
            and p.hostname
            and (p.hostname == "epicgames.com" or p.hostname.endswith(".epicgames.com"))
        )
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        raise Paused("unexpected_origin")
    return f"https://{p.hostname}{p.path}"


def _is_playwright_timeout(error):
    # The adapter has no eager browser dependency. Once a read-only browser
    # operation fails, use the real class rather than matching exception names
    # or messages (which could hide selector/protocol/authorization errors).
    try:
        from playwright.async_api import TimeoutError as BrowserTimeoutError
    except ImportError:
        return False
    return isinstance(error, BrowserTimeoutError)


def _same_target(actual, expected):
    # The store canonicalizes its English /en-US/ path to the same / path.
    target = clean_target(expected)
    try:
        current = clean_target(actual)
    except Paused:
        return False
    return re.sub(r"/en-US/", "/", current) == re.sub(r"/en-US/", "/", target)


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
        sso_login=None,
    ):
        self.context, self.page, self.journal = context, page, journal
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.offer = None
        self.checkout = None
        self.checkout_button = None
        self.prepared = set()
        self.checkout_evidence = checkout_evidence
        self.cart_evidence = cart_evidence
        self.sso_login = sso_login
        self.current_offer_ids = set()
        self.observation_session = uuid.uuid4().hex
        self.device_acknowledged = set()
        self.assets_denied = False
        self.cloudflare_document = None
        self.challenge_responses = {}

    def observe_response(self, response):
        target = urlsplit(response.url)
        if (target.hostname == "store.epicgames.com" and target.path.startswith("/egs-v2/assets/")
                and response.status == 403):
            self.assets_denied = True
        if (response.request.resource_type == "document"
                and response.frame is self.page.main_frame):
            self.challenge_responses.pop("payload", None)
            self.cloudflare_document = (
                clean_target(response.url)
                if target.hostname in ALLOWED and response.headers.get("cf-mitigated") == "challenge"
                else None
            )
        kind = response_kind(response)
        if kind in {"script", "payload"} and response.frame.page is self.page:
            # At most the latest script and payload, held only in this process.
            # A failed replacement must not leave an older puzzle to be replayed.
            self.challenge_responses.pop(kind, None)
            if response.status == 200:
                self.challenge_responses[kind] = response

    def _purchase_controls(self, page):
        # Both storefront versions expose named buttons. Test IDs are absent
        # from the current product page; generated CSS classes are not an API.
        return page.get_by_role("button", name=PURCHASE_NAMES)

    async def _purchase_button(self, page):
        # The current sidebar offers Get alongside an optional cart icon.
        # Prefer the direct route; use the cart route only when it is primary.
        for names in (DIRECT_PURCHASE_NAMES, CART_PURCHASE_NAMES):
            controls = page.get_by_role("button", name=names)
            count = await controls.count()
            if count > 32:
                raise Paused("purchase_controls_ambiguous")
            visible = []
            for index in range(count):
                button = controls.nth(index)
                if await button.is_visible():
                    visible.append(button)
            if len(visible) > 1:
                raise Paused("purchase_controls_ambiguous")
            if visible:
                return visible[0]
        return None

    async def _purchase_text(self, button, timeout):
        text = (await button.inner_text(timeout=min(5000, int(timeout * 1000)))).strip()
        return text or (await button.get_attribute("aria-label") or "").strip()

    async def _visible(self, locator):
        try:
            count = await locator.count()
            if count > 32:
                raise Paused("observation_controls_ambiguous")
            # Hidden provider iframes can precede an active visible challenge.
            for index in range(count):
                # Camoufox's patched Frame.is_visible omits the deprecated
                # timeout argument. Visibility is an immediate observation;
                # bounded hydration waits belong in observe(), not this call.
                if await locator.nth(index).is_visible():
                    return True
            return False
        except Paused:
            raise
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
        except Exception as error:
            # A navigation timeout may occur after useful DOM arrived. Require
            # the same expected path and a visible business marker to continue.
            if not _is_playwright_timeout(error):
                raise
            if not _same_target(self.page.url, url) or not (
                # egs-navigation uses display:contents and has no visible box.
                await self.page.locator("egs-navigation").count() == 1
                or await self._purchase_button(self.page) is not None
                or await self._visible(self.page.locator("#email,#password"))
            ):
                raise
        clean_target(self.page.url)

    async def _containers(self, phase):
        containers = [self.page]
        if phase not in {"checkout", "post_submit"}:
            return containers
        frames = [f for f in self.page.frames if f is not self.page.main_frame]
        if len(frames) > 16:
            raise Paused("observation_frames_ambiguous")
        for frame in frames:
            try:
                clean_target(frame.url, checkout=True)
            except Paused:
                continue
            # Ignore hidden stale checkout frames, never a visibility failure.
            if await (await frame.frame_element()).is_visible():
                containers.append(frame)
        return containers

    async def _captcha_evidence(self, container, *, timeout):
        """Hash current visible pixels, not stable provider iframe URLs.

        Bytes are transient, bounded and never saved. This also detects refreshes
        implemented with canvas/blob images inside an unchanged iframe. A new
        browser instance/container cannot reuse a previous approval.
        """
        selector = 'iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"]'
        frames = container.locator(selector)
        count = await frames.count()
        if count > 32:
            raise Paused("observation_controls_ambiguous")
        visible = []
        for index in range(count):
            frame = frames.nth(index)
            if await frame.is_visible():
                visible.append(frame)
        if not visible:
            visible = [container.locator("body")]
        if len(visible) > 4:
            raise Paused("challenge_evidence_ambiguous")
        digests = []
        for surface in visible:
            box = await surface.bounding_box()
            if (
                not box
                or any(
                    not isinstance(box.get(k), (int, float))
                    or not math.isfinite(box[k])
                    for k in ("width", "height")
                )
                or box["width"] <= 0
                or box["height"] <= 0
                or box["width"] * box["height"] > 1024 * 1024
            ):
                raise Paused("challenge_evidence_unavailable")
            pixels = await surface.screenshot(
                type="png", scale="css", timeout=min(5000, int(timeout * 1000))
            )
            if not isinstance(pixels, bytes) or not 0 < len(pixels) <= 4 * 1024 * 1024:
                raise Paused("challenge_evidence_unavailable")
            digests.append(hashlib.sha256(pixels).hexdigest())
        return [self.observation_session, id(container), digests]

    async def _ready(self, container, phase, text):
        if phase == "session":
            # The navigation web component uses display:contents in the live
            # storefront; its own bounding box is empty even while logged in.
            return await container.locator('egs-navigation[isloggedin="true"]').count() == 1
        if phase in {"product", "verification"}:
            return await self._purchase_button(container) is not None
        if phase == "cart":
            return any(
                x in text for x in ("your cart is empty", "购物车为空")
            ) or await self._visible(
                container.locator('[data-testid="offer-card-layout-wrapper"]')
            )
        if phase in {"checkout", "post_submit"}:
            controls = await self._checkout_controls()
            return len(controls) == 1 and controls[0][0] is container
        return False

    async def observe(self, phase, *, timeout):
        # DOMContentLoaded precedes the store's hydrated purchase controls.
        # Re-probe without navigation or interaction before declaring a layout gap.
        attempts = 20 if phase in {"checkout", "post_submit"} else 8
        for attempt in range(attempts):
            state = await self._observe_once(phase, timeout=timeout)
            if state is None or state.kind != "unknown":
                return state
            if attempt == 0 and phase in {"product", "verification"}:
                try:
                    await self._purchase_controls(self.page).first.wait_for(
                        state="visible", timeout=min(20000, int(timeout * 1000)))
                except Exception as error:
                    if not _is_playwright_timeout(error):
                        raise
            if attempt == attempts - 1:
                # A denied optional script does not negate a working control,
                # ownership marker or a visible login/challenge. Report resource
                # denial when the bounded observation cannot establish a state.
                if self.assets_denied:
                    raise Paused("store_assets_access_denied")
                return state
            await asyncio.sleep(min(1, timeout / attempts))

    async def _observe_once(self, phase, *, timeout):
        observations = []
        ready = False
        for container in await self._containers(phase):
            state = await self._observe_container(container, phase, timeout=timeout)
            if state is None:
                ready = True
            elif state.kind != "unknown":
                observations.append(state)
        if len(observations) > 1:
            raise Paused("observation_containers_ambiguous")
        if observations:
            return observations[0]
        if ready:
            return None
        return classify(
            {},
            phase=phase,
            target=clean_target(self.page.url),
            evidence_fingerprint=fingerprint("unconfirmed", phase),
        )

    async def _observe_container(self, container, phase, *, timeout):
        target = clean_target(container.url, checkout=container is not self.page)
        raw_text = await self._text(container)
        text = raw_text.lower()
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
            container.locator('label[for="agree"]')
        )
        signals["privacy_acceptance"] = "/correction/privacy-policy" in target
        signals["age_confirmation"] = bool(
            re.search(r"date of birth|verify your age|age verification", text)
        )
        signals["account_link"] = await self._visible(
            container.get_by_role("button", name="Done linking", exact=True)
        )
        signals["security_setting"] = "/id/login/mfa/add" in target
        cloudflare = container is self.page and self.cloudflare_document == target
        signals["visible_captcha"] = cloudflare or await self._visible(
            container.locator(
                'iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"]'
            )
        ) or _challenge_frame(container) or any(
            marker in text
            for marker in (
                "verify you are human",
                "checking your browser",
                "请完成安全检查以继续",
            )
        )
        signals["mfa_required"] = (
            "/id/login/mfa" in target and not signals["security_setting"]
        )
        signals["login_required"] = await self._visible(
            container.locator("#email,#password")
        )
        signals["remembered_account"] = "welcome back" in text and "/id/" in target
        if phase in {"session", "product"} and not any(signals.values()):
            signals["login_required"] = await container.locator(
                'egs-navigation[isloggedin="false"]'
            ).count() == 1
        signals["store_sso"] = (
            urlsplit(target).hostname == "store.epicgames.com"
            and urlsplit(target).path == "/login"
        )
        signals["device_modal"] = "device not supported" in text
        # No generic overlay flag from an arbitrary Continue label.
        signals["ready"] = not any(signals.values()) and await self._ready(
            container, phase, text
        )
        challenge_evidence = (
            await self._captcha_evidence(container, timeout=timeout)
            if signals["visible_captcha"]
            else None
        )
        # Bind a grant to current visible content/challenge identity. Raw source
        # URLs/text remain local memory and are never written to checkpoint.
        digest = fingerprint(
            target,
            phase,
            sorted(k for k, v in signals.items() if v),
            hashlib.sha256(raw_text.encode()).hexdigest()
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
            self.observation_session,
            id(container),
            challenge_evidence,
        )
        state = classify(
            signals, phase=phase, target=target, evidence_fingerprint=digest
        )
        if state is not None:
            state = replace(
                state, payload={**(state.payload or {}), "_container": container,
                    **({"_provider": "cloudflare"} if cloudflare and state.kind == "captcha" else {})}
            )
        return state

    async def recover(self, obstacle, *, timeout):
        if obstacle.kind == "store_sso" and self.sso_login is not None:
            await self.sso_login(obstacle, timeout=timeout)
            return
        if obstacle.kind in {"delayed_result", "navigation_partial", "stale_locator"}:
            await asyncio.sleep(min(1, timeout))
            return
        if obstacle.kind == "browser_page_rebuild":
            old = self.page
            self.page = await self.context.new_page()
            await self._goto(obstacle.target, timeout)
            await old.close()
            return
        if (obstacle.kind == "region_layout" and obstacle.phase == "checkout"
                and (obstacle.payload or {}).get("subtype") == "device_modal"
                and (obstacle.payload or {}).get("_container") is self.page
                and self.offer is not None and self.offer.id in self.prepared
                and urlsplit(self.page.url).hostname == "store.epicgames.com"
                and obstacle.target == clean_target(self.page.url)):
            dialog = self.page.get_by_role("dialog")
            expected = "Device not supported This product is not compatible with your current device Cancel Continue"
            if (await dialog.count() != 1 or not await dialog.is_visible()
                    or " ".join((await dialog.inner_text()).split()) != expected):
                raise Paused("device_modal_unconfirmed")
            button = dialog.get_by_role("button", name="Continue", exact=True)
            if (await button.count() != 1 or not await button.is_visible()
                    or not await button.is_enabled()):
                raise Paused("device_modal_unconfirmed")
            if self.offer.id in self.device_acknowledged:
                raise Paused("device_modal_stagnant")
            # This dialog only warns that the NAS cannot run a Windows game.
            # Continue to the existing exact-offer/zero-price gate, once.
            self.device_acknowledged.add(self.offer.id)
            await button.click(timeout=min(5000, int(timeout * 1000)))
            await dialog.wait_for(state="hidden", timeout=min(10000, int(timeout * 1000)))
            return
        # Remembered-account selection, SSO and device warnings need explicit
        # binding/context; never click a generic Yes/Continue here.
        raise Paused("recovery_binding_pending")

    async def inventory(self, *, timeout):
        # Session settlement already brought the public entry to this page.
        # Keep that session instead of restarting the storefront before fetch.
        if not _same_target(self.page.url, STORE + "/free-games"):
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

    def _at_offer(self, page, offer):
        return _same_target(page.url, offer.url)

    async def verify(self, offer, *, timeout):
        if not self._at_offer(self.page, offer):
            await self._goto(offer.url, timeout)
        return await self._ownership(self.page, offer, timeout=timeout)

    async def verify_readonly(self, offer, *, timeout):
        """Never navigate away from a pending checkout/challenge for readback."""
        page = await self.context.new_page()
        try:
            clean_target(offer.url)
            await page.goto(
                offer.url,
                wait_until="domcontentloaded",
                timeout=min(20000, int(timeout * 1000)),
            )
            return await self._ownership(page, offer, timeout=timeout)
        except Exception as error:
            if _is_playwright_timeout(error):
                # Playwright's TimeoutError is not Python's TimeoutError. Only
                # this read-only navigation/ownership boundary is normalized;
                # creation/cleanup failures and all other browser errors escape.
                raise TimeoutError("readonly_browser_timeout") from error
            raise
        finally:
            await page.close()

    async def _ownership(self, page, offer, *, timeout):
        # The current store can canonicalize /en-US/p/x to /p/x.
        if not self._at_offer(page, offer):
            return "unknown"
        try:
            await self._purchase_controls(page).first.wait_for(
                state="visible", timeout=min(15000, int(timeout * 1000)))
        except Exception as error:
            if not _is_playwright_timeout(error):
                raise
            if self.assets_denied:
                raise Paused("store_assets_access_denied") from None
            return "unknown"
        button = await self._purchase_button(page)
        if button is None:
            if self.assets_denied:
                raise Paused("store_assets_access_denied")
            return "unknown"
        text = await self._purchase_text(button, timeout)
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

    async def checkout_uses_cart(self, offer, *, timeout):
        """Observe the current product route before touching an existing cart."""
        if self.offer is None or self.offer.id != offer.id:
            raise Paused("purchase_control_unknown")
        button = await self._purchase_button(self.page)
        if button is None:
            raise Paused("purchase_control_unknown")
        text = (await self._purchase_text(button, timeout)).casefold()
        if text in {"add to cart", "加入购物车"}:
            return True
        if text in {"get", "free", "buy now", "获取", "免费"}:
            return False
        raise Paused("purchase_control_unknown")

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
        if not self._at_offer(self.page, offer):
            await self.open_offer(offer, timeout=timeout)
        await self._purchase_controls(self.page).first.wait_for(
            state="visible", timeout=min(20000, int(timeout * 1000)))
        button = await self._purchase_button(self.page)
        if button is None:
            raise Paused("purchase_control_unknown")
        text = (await self._purchase_text(button, timeout)).casefold()
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
        if text not in {"add to cart", "加入购物车"}:
            # Get now runs an automatic quick-purchase before any order page.
            # Open the official independent checkout instead, so the workflow
            # still checks its exact identity/zero total and journals submission.
            identity = re.fullmatch(r"([a-f0-9]{32}):([a-f0-9]{32})", offer.id)
            if identity is None:
                raise Paused("checkout_identity_unconfirmed")
            self.prepared.add(offer.id)
            await self._goto(CHECKOUT + "?offers=1-" + identity[1] + "-" + identity[2] + "--", timeout)
            return
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
                "button", name=re.compile(r"^(Place Order|Add to library|添加到库)$", re.I)
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
        if not zero_total(text, add_to_library=label in {"add to library", "添加到库"}):
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
