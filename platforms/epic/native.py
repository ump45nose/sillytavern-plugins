"""One invocation owns its browser, account profile, login and claim journal.

Narrow GPL adaptations of Ronchy2000/epic-freebies-helper at upstream-contract.json.
No upstream service, scheduler, settings singleton or video recorder is imported.
"""
import json
import os
from pathlib import Path
import time
import shutil
import re
from urllib.parse import parse_qs, urlsplit

from common.model import atomic_json
from .browser_driver import BrowserDriver, STORE, clean_target
from .workflow import ClaimWorkflow, Paused

LOGIN = "https://www.epicgames.com/id/login?lang=en-US&noHostRedirect=true&redirectUrl=" + STORE + "/free-games"


class Journal:
    def __init__(self, directory):
        self.path = Path(directory) / "claim-journal.json"
        self.rows = {}
        if self.path.exists():
            with self.path.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("claim_journal_invalid")
            self.rows = json.loads(raw)
        if (not isinstance(self.rows, dict) or len(self.rows) > 200 or
                any(v not in {"submitting", "submitted", "uncertain", "confirmed"}
                    for v in self.rows.values())):
            raise ValueError("claim_journal_invalid")

    async def read(self, identity):
        return self.rows.get(identity)

    async def write(self, identity, state):
        if identity not in self.rows and len(self.rows) >= 200:
            raise Paused("claim_journal_limit")
        self.rows[identity] = state
        atomic_json(self.path, self.rows)


async def checkout_evidence(container, *, timeout):
    """Exact identity from the active official checkout URL, never product text."""
    clean_target(container.url, checkout=True)
    query = parse_qs(urlsplit(container.url).query)
    if any(len(query.get(key, [])) > 1 for key in ("namespace", "offers", "offerId")):
        return {"complete": False}
    namespace = query.get("namespace", [None])[0]
    offers = query.get("offers", [None])[0]
    identities = []
    if offers:
        try:
            rows = json.loads(offers)
        except (ValueError, TypeError):
            rows = offers.split(",")
        if not isinstance(rows, list) or len(rows) > 100:
            return {"complete": False}
        for row in rows:
            if isinstance(row, dict):
                ns, oid = row.get("namespace"), row.get("offerId") or row.get("id")
            else:
                # Current /purchase uses quantity-namespace-offerId--. Bind
                # only the observed single-unit format; extra fields/quantity
                # remain unknown rather than silently dropping them.
                modern = re.fullmatch(r"1-([a-f0-9]{32})-([a-f0-9]{32})--", row) if isinstance(row, str) else None
                if modern:
                    ns, oid = modern.groups()
                    if namespace is not None and namespace != ns:
                        return {"complete": False}
                elif namespace:
                    ns, oid = namespace, row
                else:
                    return {"complete": False}
            if not ns or not isinstance(oid, str) or len(oid) > 128:
                return {"complete": False}
            identities.append(str(ns) + ":" + oid)
    elif namespace and query.get("offerId"):
        identities = [namespace + ":" + query["offerId"][0]]
    return {"complete": bool(identities), "offer_ids": identities}


class Login:
    def __init__(self, driver, config):
        self.driver, self.config = driver, config
        self.acted = set()
        self.challenge = None

    async def captcha(self, obstacle, *, timeout):
        page = self.driver.page
        for frame in page.frames:
            if urlsplit(frame.url).hostname == "challenges.cloudflare.com":
                box = await (await frame.frame_element()).bounding_box()
                if box and box["width"] >= 200 and box["height"] >= 40:
                    await page.mouse.click(box["x"] + 28, box["y"] + box["height"] / 2)
                    await page.wait_for_timeout(5000)
                    return
        if self.challenge is None:
            self.challenge = build_challenge(page, self.config)
        try:
            outcome = await self.challenge.handle(obstacle, timeout=min(timeout, 120))
        except TimeoutError:
            raise Paused("challenge_timeout") from None
        if outcome.get("solver_signal") != "success":
            raise Paused("challenge_unconfirmed")

    async def login(self, obstacle, *, timeout):
        page = self.driver.page
        clean_target(page.url)
        if "/mfa" in urlsplit(page.url).path:
            raise Paused("mfa_data_required")
        email, password = self.config.get("email"), self.config.get("password")
        if not email or not password:
            raise Paused("login_credentials_required")
        remembered = page.get_by_text(email, exact=True)
        if await page.get_by_text("Welcome back", exact=True).is_visible() and await remembered.is_visible():
            if "remembered" in self.acted: raise Paused("login_stagnant")
            self.acted.add("remembered")
            await remembered.click(timeout=5000)
        elif await page.locator("#password").is_visible():
            if "password" in self.acted: raise Paused("login_not_confirmed")
            self.acted.add("password")
            await page.locator("#password").fill(password)
            await page.locator("#sign-in").click(timeout=10000)
        elif await page.locator("#email").is_visible():
            if "email" in self.acted: raise Paused("login_not_confirmed")
            self.acted.add("email")
            await page.locator("#email").fill(email)
            await page.locator("#continue").click(timeout=10000)
        else:
            raise Paused("login_layout_unavailable")
        await page.wait_for_timeout(3000)

    async def link(self, obstacle, *, timeout):
        page = self.driver.page
        button = page.get_by_role("button", name="Done linking", exact=True)
        if "link" in self.acted or await button.count() != 1:
            raise Paused("link_control_unconfirmed")
        self.acted.add("link")
        await button.click(timeout=5000)
        await page.wait_for_timeout(3000)


def build_challenge(page, config):
    """Only the challenge path loads the model SDK/image libraries."""
    from .challenges import HCaptchaHandler, load_sdk
    AgentConfig = load_sdk().AgentConfig
    from .model_bridge import install
    from hcaptcha_challenger.tools.internal.providers.gemini import GeminiProvider
    from tenacity import stop_after_attempt
    model = config.get("model", {})
    if not model.get("api_key") or not model.get("name"):
        raise Paused("challenge_model_not_configured")
    install(model)
    # AgentConfig's retry flag does not disable the provider's HTTP decorator.
    GeminiProvider.generate_with_images.retry.stop = stop_after_attempt(1)
    temporary = Path(os.environ["TMPDIR"]) / "challenge"
    temporary.mkdir(mode=0o700, exist_ok=True)
    settings = AgentConfig(GEMINI_API_KEY=model["api_key"],
        RETRY_ON_FAILURE=False, EXECUTION_TIMEOUT=120, RESPONSE_TIMEOUT=60,
        cache_dir=temporary / "cache", challenge_dir=temporary / "images",
        captcha_response_dir=temporary / "responses")
    return HCaptchaHandler(page, settings)


async def execute(context, config, state_dir):
    # Importing HTTP platforms does not import Camoufox/numpy/Playwright.
    from camoufox import AsyncCamoufox
    from camoufox import pkgman
    cache = Path(config["browser_cache"])
    if not cache.is_absolute() or not (cache / "camoufox-bin").is_file():
        raise Paused("browser_cache_unavailable")
    pkgman.INSTALL_DIR = cache
    options = dict(persistent_context=True, user_data_dir=str(Path(state_dir) / "browser"),
                   headless=True, humanize=0.2, locale="en-US",
                   firefox_user_prefs={"network.dns.disableIPv6": True, "network.trr.mode": 5})
    if config.get("proxy"):
        options["proxy"] = {"server": config["proxy"]}
    async with AsyncCamoufox(**options) as browser:
        async def identity_encoding(route):
            headers = await route.request.all_headers()
            headers["accept-encoding"] = "identity"
            await route.continue_(headers=headers)
        await browser.route("**/hsw.js*", identity_encoding)
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(STORE + "/free-games", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)
        driver = BrowserDriver(browser, page, Journal(state_dir), checkout_evidence=checkout_evidence)
        browser.on("response", driver.observe_asset_response)
        if await page.locator('egs-navigation[isloggedin="true"]').count() == 0:
            await page.goto(LOGIN, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)
        auth = Login(driver, config)
        workflow = ClaimWorkflow(driver, context, deadline=time.monotonic() + 1100,
            expires_at=context["business_date"] + "T23:59:59+08:00",
            automatic_kinds={"login", "captcha", "account_link"},
            handlers={"login": auth.login, "captcha": auth.captcha, "account_link": auth.link})
        try:
            return await workflow.run()
        finally:
            if auth.challenge: await auth.challenge.close()
            shutil.rmtree(Path(os.environ["TMPDIR"]) / "challenge", ignore_errors=True)
