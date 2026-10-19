"""Exercise current product markup with Camoufox and intercepted store pages."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platforms.epic.browser_driver import BrowserDriver
from platforms.epic.workflow import Offer, Paused


async def main(cache):
    from camoufox import AsyncCamoufox, pkgman
    pkgman.INSTALL_DIR = Path(cache)
    if not (pkgman.INSTALL_DIR / "camoufox-bin").is_file():
        raise ValueError("browser_cache_unavailable")
    async with AsyncCamoufox(headless=True) as browser:
        context = await browser.new_context()
        markup = {"body": '<main><button type="button" class="_sidebarBuyButton_fixture" '
                  'onclick="window.clicks=(window.clicks||0)+1">Get</button>'
                  '<button aria-label="Add to Cart"></button></main>'}
        navigations = []
        async def route(request):
            navigations.append(request.request.url)
            await request.fulfill(status=200, content_type="text/html", body=markup["body"])
        await context.route("https://store.epicgames.com/**", route)
        page = await context.new_page()
        offer = Offer("fixture", "https://store.epicgames.com/p/fixture", True)
        driver = BrowserDriver(context, page, None)
        await driver.open_offer(offer, timeout=10)
        assert await page.locator('[data-testid="purchase-cta-button"]').count() == 0
        assert await driver.observe("product", timeout=10) is None
        assert await driver.verify(offer, timeout=10) == "not_owned"
        assert await driver.checkout_uses_cart(offer, timeout=10) is False
        await driver.prepare_checkout(offer, timeout=10)
        assert len(navigations) == 1
        assert await page.evaluate("window.clicks") == 1
        markup["body"] = '<main><button disabled>In Library</button></main>'
        assert await driver.verify_readonly(offer, timeout=10) == "owned"
        await page.set_content('<main><button>Get</button><button>Get</button></main>')
        try:
            await driver._ready(page, "product", "Get")
        except Paused as error:
            assert error.reason == "purchase_controls_ambiguous"
        else:
            raise AssertionError("ambiguous purchase controls were accepted")
        await page.set_content('<main><button>Get help</button></main>')
        assert await driver._purchase_button(page) is None
        await page.set_content('<main><button hidden>Get</button><button>Get</button></main>')
        assert await driver._purchase_button(page) is not None
        markup["body"] = '<main><button aria-label="Add to Cart"></button></main>'
        await page.set_content(markup["body"])
        assert await driver.verify(offer, timeout=10) == "not_owned"
        assert await driver.checkout_uses_cart(offer, timeout=10) is True
        print("PASS: product readiness, ownership, checkout route, one click, separate readback, ambiguity and exact names")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-cache", required=True)
    asyncio.run(main(parser.parse_args().browser_cache))
