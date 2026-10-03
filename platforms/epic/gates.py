"""Known Epic UI continuations, invoked only by a trusted authorized host.

No credential lookup, generic Continue clicking, or automatic agreement grant.
The claim workflow re-observes and validates the exact approval scope before
calling these handlers. The host must disclose agreements before authorizing.
Bindings follow the pinned upstream selectors; live layouts remain unverified.
"""

from urllib.parse import urlsplit
from .workflow import Paused
from .browser_driver import clean_target


def official_page(page):
    clean_target(page.url, checkout=True)


def current_container(page, obstacle):
    """Use only the current driver-observed container, never arbitrary frames."""
    payload = obstacle.payload if isinstance(obstacle.payload, dict) else {}
    container = payload.get("_container", page)
    if container is not page and not any(
        container is frame for frame in getattr(page, "frames", [])
    ):
        raise Paused("gate_container_changed")
    official_page(container)
    if clean_target(container.url, checkout=True) != obstacle.target:
        raise Paused("gate_target_changed")
    return container


async def unique_visible(locator):
    count = await locator.count()
    if count > 16:
        raise Paused("gate_controls_ambiguous")
    matches = []
    for index in range(count):
        item = locator.nth(index)
        if await item.is_visible():
            matches.append(item)
    if len(matches) != 1:
        raise Paused("gate_control_unconfirmed")
    return matches[0]


class RememberedAccountHandler:
    """Reuse an exact host-supplied account, never guess the first account."""

    def __init__(self, page, account_identifier):
        if not isinstance(account_identifier, str) or not account_identifier.strip():
            raise ValueError("account_identifier_required")
        self.page = page
        self.account_identifier = account_identifier

    async def __call__(self, obstacle, *, timeout):
        if (
            obstacle.kind != "login"
            or not isinstance(obstacle.payload, dict)
            or obstacle.payload.get("subtype") != "remembered_account"
        ):
            raise Paused("wrong_login_handler")
        page = current_container(self.page, obstacle)
        await unique_visible(page.get_by_text("Welcome back", exact=True))
        account = await unique_visible(
            page.get_by_text(self.account_identifier, exact=True)
        )
        await account.click(timeout=min(5000, int(timeout * 1000)))
        return {"requires_readback": True}


class AccountLinkHandler:
    """A separately approved Done linking step, not an implicit login side effect."""

    def __init__(self, page):
        self.page = page

    async def __call__(self, obstacle, *, timeout):
        if obstacle.kind != "account_link":
            raise Paused("wrong_account_link_handler")
        page = current_container(self.page, obstacle)
        button = await unique_visible(
            page.get_by_role("button", name="Done linking", exact=True)
        )
        await button.click(timeout=min(5000, int(timeout * 1000)))
        return {"requires_readback": True}


class LicenseHandler:
    """Accept the known license form after current exact terms were approved.

    The trusted host's disclosure callback must verify the current agreement
    text/links against what it showed the owner. A bare boolean setting or a
    file of grants is not supported. It must also report actual acceptance to
    the owner with the agreement link; this class only returns action evidence.
    """

    def __init__(self, page, verify_disclosure):
        if not callable(verify_disclosure):
            raise ValueError("trusted_disclosure_callback_required")
        self.page = page
        self.verify_disclosure = verify_disclosure

    async def __call__(self, obstacle, *, timeout):
        if obstacle.kind != "terms":
            raise Paused("wrong_terms_handler")
        page = current_container(self.page, obstacle)
        # The privacy correction flow is a different agreement and form.
        if "/correction/privacy-policy" in page.url:
            raise Paused("privacy_correction_binding_pending")
        await unique_visible(page.locator('label[for="agree"]'))
        evidence = await self.verify_disclosure(page, obstacle, timeout=timeout)
        if (
            not isinstance(evidence, dict)
            or evidence.get("fingerprint") != obstacle.fingerprint
        ):
            raise Paused("agreement_disclosure_mismatch")
        links = evidence.get("agreement_links")
        if not isinstance(links, list) or not 1 <= len(links) <= 8:
            raise Paused("agreement_links_required")
        for link in links:
            parsed = urlsplit(link) if isinstance(link, str) else None
            if (
                parsed is None
                or parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise Paused("agreement_link_invalid")
        checkbox = page.locator("#agree")
        if (
            await checkbox.count() != 1
            or await checkbox.get_attribute("type") != "checkbox"
        ):
            raise Paused("agreement_checkbox_unconfirmed")
        # check is idempotent: a pre-checked checkbox is not toggled off.
        await checkbox.check(timeout=min(5000, int(timeout * 1000)))
        button = await unique_visible(
            page.get_by_role("button", name="Accept", exact=True)
        )
        if not await button.is_enabled():
            raise Paused("agreement_accept_disabled")
        await button.click(timeout=min(5000, int(timeout * 1000)))
        return {
            "acceptance_attempted": True,
            "agreement_links": links,
            "requires_readback": True,
        }
