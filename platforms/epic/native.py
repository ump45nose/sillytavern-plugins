"""One invocation owns its browser, account profile, login and claim journal.

Narrow GPL adaptations of Ronchy2000/epic-freebies-helper at upstream-contract.json.
No upstream service, scheduler, settings singleton or video recorder is imported.
"""
import json
import asyncio
import os
import sys
from pathlib import Path
import time
import shutil
import re
from urllib.parse import parse_qs, urlsplit, urljoin

from common.model import atomic_json
from .browser_driver import BrowserDriver, STORE, clean_target
from .workflow import ClaimWorkflow, Paused

LOGIN = "https://store.epicgames.com/login"
CHALLENGE_TIMEOUT = 300


async def report_purchase_error(response):
    """Keep the payment service's rejection code, never its account/token data."""
    target = urlsplit(response.url)
    if (response.status < 400 or target.hostname != "payment-website-pci.ol.epicgames.com"
            or response.request.resource_type not in {"xhr", "fetch"}):
        return
    record = {"event": "epic_purchase_error", "status": response.status}
    if re.fullmatch(r"/v2/purchase/[a-z][a-z-]{1,50}", target.path):
        record["operation"] = target.path.rsplit("/", 1)[1]
    try:
        raw = await asyncio.wait_for(response.body(), timeout=3)
        if len(raw) <= 65536:
            data = json.loads(raw)
            if isinstance(data, dict):
                code = data.get("errorCode")
                if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", code):
                    record["error_code"] = code
                if type(data.get("numericErrorCode")) is int:
                    record["numeric_code"] = data["numericErrorCode"]
    except Exception as error:
        record["read_error"] = type(error).__name__
    print(json.dumps(record), flush=True)


def _browser_options(config, state_dir):
    """Keep the browser identity with its cookies instead of rotating it on restart."""
    from camoufox.utils import launch_options

    identity_path = Path(state_dir) / "browser-identity.json"
    stored = identity_path.exists()
    identity = json.loads(identity_path.read_text(encoding="utf-8")) if stored else None
    if stored and (not isinstance(identity, dict) or not identity):
        raise ValueError("browser_identity_invalid")
    # Firefox must expose Turnstile's cross-origin frame for the normal click.
    options = dict(user_data_dir=str(Path(state_dir) / "browser"),
                   headless=True, disable_coop=True, humanize=0.2, locale="en-US",
                   firefox_user_prefs={"network.dns.disableIPv6": True, "network.trr.mode": 5})
    if config.get("proxy"):
        options["proxy"] = {"server": config["proxy"]}
    options = launch_options(config=identity, **options)
    if not stored:
        chunks = sorted((int(key.rsplit("_", 1)[1]), value)
                        for key, value in options["env"].items() if key.startswith("CAMOU_CONFIG_"))
        atomic_json(identity_path, json.loads("".join(value for _, value in chunks)))
    return options


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

    async def sso(self, obstacle, *, timeout):
        page, offer = self.driver.page, self.driver.offer
        if (obstacle.phase != "checkout" or (obstacle.payload or {}).get("_container") is not page
                or offer is None or offer.id not in self.driver.prepared
                or clean_target(page.url) != LOGIN
                or obstacle.target != clean_target(page.url)):
            raise Paused("login_not_confirmed")
        key = ("sso", offer.id)
        if key in self.acted:
            raise Paused("login_not_confirmed")
        self.acted.add(key)
        # The store login transition retains the pending purchase in its URL.
        # Let the storefront build its OAuth request and preserve its pending
        # purchase. Never invent authentication client/state parameters.
        await self.driver._goto(page.url, timeout)
        await page.wait_for_timeout(3000)

    async def captcha(self, obstacle, *, timeout):
        page = self.driver.page
        for frame in page.frames:
            if urlsplit(frame.url).hostname == "challenges.cloudflare.com":
                box = await (await frame.frame_element()).bounding_box()
                if box and box["width"] >= 200 and box["height"] >= 40:
                    await page.mouse.click(box["x"] + 28, box["y"] + box["height"] / 2)
                    await page.wait_for_timeout(5000)
                    return
        if (obstacle.payload or {}).get("_provider") == "cloudflare":
            # Managed Challenges can verify automatically without a visible
            # widget. Keep this document open, then let the workflow re-observe;
            # it must not be sent to the unrelated hCaptcha model handler.
            await page.wait_for_timeout(min(5000, int(timeout * 1000)))
            return
        if self.challenge is None:
            captured = self.driver.challenge_responses
            self.challenge = build_challenge(page, self.config, initial_responses=(
                captured[kind] for kind in ("script", "payload") if kind in captured))
        try:
            outcome = await self.challenge.handle(obstacle, timeout=min(timeout, CHALLENGE_TIMEOUT))
        except TimeoutError:
            raise Paused("challenge_timeout") from None
        signal = outcome.get("solver_signal")
        if signal in {"challenge_execution_timeout", "challenge_response_timeout"}:
            raise Paused("challenge_timeout")
        if signal != "success":
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
        email_box, password_box = page.locator("#email"), page.locator("#password")
        if await page.get_by_text("Welcome back", exact=True).is_visible() and await remembered.is_visible():
            if "remembered" in self.acted: raise Paused("login_stagnant")
            self.acted.add("remembered")
            await remembered.click(timeout=5000)
        elif await password_box.is_visible() and await email_box.is_visible():
            # Current account page shows both fields and submits with Continue.
            if "credentials" in self.acted: raise Paused("login_not_confirmed")
            self.acted.add("credentials")
            await email_box.fill(email)
            await password_box.fill(password)
            submit = page.locator("#sign-in")
            if not await submit.is_visible():
                submit = page.locator("#continue")
            await submit.click(timeout=10000)
        elif await password_box.is_visible():
            if "password" in self.acted: raise Paused("login_not_confirmed")
            self.acted.add("password")
            await password_box.fill(password)
            await page.locator("#sign-in").click(timeout=10000)
        elif await email_box.is_visible():
            if "email" in self.acted: raise Paused("login_not_confirmed")
            self.acted.add("email")
            await page.locator("#email").fill(email)
            await page.locator("#continue").click(timeout=10000)
        elif (urlsplit(page.url).hostname == "store.epicgames.com"
                and await page.locator('egs-navigation[isloggedin="false"]').count() == 1):
            if "store_authentication" in self.acted:
                raise Paused("login_not_confirmed")
            names = re.compile(r"^(Sign In|Log In|Login|登录)$", re.I)
            visible = []
            for role in ("link", "button"):
                controls = page.get_by_role(role, name=names)
                if await controls.count() > 16:
                    raise Paused("login_layout_unavailable")
                for index in range(await controls.count()):
                    control = controls.nth(index)
                    if await control.is_visible():
                        visible.append(control)
            if len(visible) != 1:
                raise Paused("login_layout_unavailable")
            href = await visible[0].get_attribute("href")
            if href:
                clean_target(urljoin(page.url, href))
            self.acted.add("store_authentication")
            await visible[0].click(timeout=min(10000, int(timeout * 1000)))
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


def build_challenge(page, config, *, initial_responses=()):
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
        RETRY_ON_FAILURE=False, EXECUTION_TIMEOUT=CHALLENGE_TIMEOUT, RESPONSE_TIMEOUT=60,
        cache_dir=temporary / "cache", challenge_dir=temporary / "images",
        captcha_response_dir=temporary / "responses")
    return HCaptchaHandler(page, settings, initial_responses=initial_responses)


async def _minimize(page):
    try:
        session = await page.context.new_cdp_session(page)
        info = await session.send("Browser.getWindowForTarget")
        await session.send("Browser.setWindowBounds", {
            "windowId": info["windowId"],
            "bounds": {"windowState": "minimized"},
        })
    except Exception as error:
        print(json.dumps({"event": "epic_chrome_window", "type": type(error).__name__}), flush=True)


async def _claim(browser, context, config, state_dir):
    async def identity_encoding(route):
        headers = await route.request.all_headers()
        headers["accept-encoding"] = "identity"
        await route.continue_(headers=headers)
    await browser.route("**/hsw.js*", identity_encoding)
    page = browser.pages[0] if browser.pages else await browser.new_page()
    await _minimize(page)
    driver = BrowserDriver(browser, page, Journal(state_dir), checkout_evidence=checkout_evidence)
    browser.on("response", driver.observe_response)
    browser.on("response", report_purchase_error)
    await driver._goto(STORE + "/free-games", 45)
    await page.wait_for_timeout(5000)
    auth = Login(driver, config)
    driver.sso_login = auth.sso
    workflow = ClaimWorkflow(driver, context, deadline=time.monotonic() + 1100,
        expires_at=context["business_date"] + "T23:59:59+08:00",
        automatic_kinds={"login", "captcha", "account_link"},
        handlers={"login": auth.login, "captcha": auth.captcha, "account_link": auth.link})
    try:
        return await workflow.run()
    finally:
        if auth.challenge: await auth.challenge.close()
        shutil.rmtree(Path(os.environ["TMPDIR"]) / "challenge", ignore_errors=True)


def _decrypt_chrome_cookie(encrypted, key, host):
    if not encrypted.startswith(b"v10") or len(encrypted) <= 3:
        return None
    from hashlib import sha256
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    padded = decryptor.update(encrypted[3:]) + decryptor.finalize()
    pad = padded[-1]
    if not 1 <= pad <= 16 or padded[-pad:] != bytes([pad]) * pad:
        return None
    body = padded[:-pad]
    # Current Chrome binds each value to its host with a SHA-256 prefix.
    prefix = sha256(host.encode()).digest()
    if body.startswith(prefix):
        body = body[len(prefix):]
    try:
        return body.decode()
    except UnicodeDecodeError:
        return None


def _mac_home():
    """Ignore a redirected HOME; Chrome and its keychain stay in the login home."""
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def local_chrome_cookies():
    """Epic cookies from the Mac's normal Chrome profile. Values stay in memory."""
    import shutil
    import sqlite3
    import subprocess
    import tempfile
    from hashlib import pbkdf2_hmac

    home = _mac_home()
    password = subprocess.check_output(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome",
         str(home / "Library/Keychains/login.keychain-db")],
        text=True,
    ).strip()
    key = pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, 16)
    root = home / "Library/Application Support/Google/Chrome"
    profiles = [root / "Default", *sorted(path for path in root.glob("Profile *") if path.is_dir())]
    same_site = {-1: "Lax", 0: "None", 1: "Lax", 2: "Strict"}
    cookies = []
    for profile in profiles:
        database = profile / "Cookies"
        if not database.is_file():
            continue
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "Cookies"
            shutil.copy(database, copied)
            for suffix in ("-wal", "-shm"):
                extra = Path(str(database) + suffix)
                if extra.is_file():
                    shutil.copy(extra, Path(str(copied) + suffix))
            connection = sqlite3.connect(f"file:{copied}?mode=ro", uri=True)
            try:
                rows = connection.execute(
                    "SELECT host_key, name, encrypted_value, path, expires_utc, "
                    "is_secure, is_httponly, samesite FROM cookies "
                    "WHERE host_key LIKE '%epicgames.com'"
                )
                for host, name, encrypted, path, expires, secure, http_only, site in rows:
                    value = _decrypt_chrome_cookie(encrypted, key, host)
                    if not value or not host or not name:
                        continue
                    item = {
                        "name": name,
                        "value": value,
                        "domain": host,
                        "path": path or "/",
                        "secure": bool(secure),
                        "httpOnly": bool(http_only),
                        "sameSite": same_site.get(site, "Lax"),
                    }
                    if expires:
                        unix = int(expires / 1_000_000 - 11_644_473_600)
                        if unix > 0:
                            item["expires"] = unix
                    cookies.append(item)
            finally:
                connection.close()
    return cookies


async def _chrome_context(playwright, config, state_dir):
    """macOS uses the installed Google Chrome instead of the Linux Camoufox build."""
    profile = Path(state_dir) / "chrome"
    profile.mkdir(mode=0o700, exist_ok=True)
    # Headless Chrome is a different client, so the daily Chrome session and
    # Cloudflare clearance do not carry over. Keep the real Chrome window and
    # minimize it before any navigation.
    options = dict(channel="chrome", headless=False, locale="zh-CN",
                   args=["--disable-blink-features=AutomationControlled"])
    if config.get("proxy"):
        options["proxy"] = {"server": config["proxy"]}
    browser = await playwright.chromium.launch_persistent_context(str(profile), **options)
    try:
        cookies = local_chrome_cookies()
    except Exception as error:
        print(json.dumps({"event": "epic_chrome_cookies", "type": type(error).__name__}), flush=True)
        cookies = []
    if cookies:
        await browser.add_cookies(cookies)
        print(json.dumps({"event": "epic_chrome_cookies", "count": len(cookies)}), flush=True)
    return browser


async def execute(context, config, state_dir):
    # Importing HTTP platforms does not import Camoufox/numpy/Playwright.
    if sys.platform == "darwin":
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await _chrome_context(playwright, config, state_dir)
            try:
                return await _claim(browser, context, config, state_dir)
            finally:
                await browser.close()
    from camoufox import AsyncCamoufox
    from camoufox import pkgman
    cache = Path(config["browser_cache"])
    if not cache.is_absolute() or not (cache / "camoufox-bin").is_file():
        raise Paused("browser_cache_unavailable")
    pkgman.INSTALL_DIR = cache
    async with AsyncCamoufox(from_options=_browser_options(config, state_dir),
                            persistent_context=True) as browser:
        return await _claim(browser, context, config, state_dir)
