"""Bounded catalog and ownership parsing; no browser or network dependencies."""

from dataclasses import dataclass
import math
from datetime import datetime, timezone
from urllib.parse import quote
from .workflow import Offer


@dataclass
class Inventory:
    offers: list[Offer]
    complete: bool
    reason: str


def _date(value):
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timezone_missing")
    return d.astimezone(timezone.utc)


def parse_catalog(raw, *, now):
    if now.tzinfo is None:
        return Inventory([], False, "invalid_clock")
    try:
        rows = raw["data"]["Catalog"]["searchStore"]["elements"]
    except (KeyError, TypeError):
        return Inventory([], False, "inventory_missing")
    if not isinstance(rows, list) or len(rows) > 500:
        return Inventory([], False, "inventory_invalid")
    offers, seen, uncertain = [], set(), False
    for row in rows:
        if not isinstance(row, dict):
            uncertain = True
            continue
        if "promotions" not in row:
            uncertain = True
            continue
        promo = row.get("promotions")
        if promo is None:  # Explicitly no promotional block.
            continue
        if not isinstance(promo, dict) or not isinstance(
            promo.get("promotionalOffers"), list
        ):
            uncertain = True
            continue
        active_free = False
        try:
            for group in promo["promotionalOffers"]:
                promotions = group["promotionalOffers"]
                if not isinstance(promotions, list) or len(promotions) > 100:
                    raise ValueError("invalid_promotions")
                for p in promotions:
                    if _date(p["startDate"]) <= now < _date(p["endDate"]):
                        percentage = p["discountSetting"]["discountPercentage"]
                        if (
                            type(percentage) not in (int, float)
                            or not math.isfinite(percentage)
                            or not 0 <= percentage <= 100
                        ):
                            raise ValueError("invalid_discount")
                        active_free |= percentage == 0
            if not active_free:
                continue
            price = row["price"]["totalPrice"]
            # Require both current campaign and explicit current zero price.
            if type(price["discountPrice"]) is not int or price["discountPrice"] != 0:
                uncertain = True
                continue
            if (
                not isinstance(price.get("currencyCode"), str)
                or not price["currencyCode"]
            ):
                uncertain = True
                continue
            identity = str(row["namespace"]) + ":" + str(row["id"])
            if (
                not row["namespace"]
                or not row["id"]
                or len(identity) > 128
                or identity in seen
            ):
                uncertain = True
                continue
            mappings = row.get("offerMappings")
            slug = (
                mappings[0].get("pageSlug")
                if isinstance(mappings, list) and mappings
                else None
            )
            slug = slug or row.get("productSlug") or row.get("urlSlug")
            if not isinstance(slug, str) or not slug or len(slug) > 300:
                raise ValueError("slug_missing")
            if any(x in slug for x in ("..", "?", "#", "\\", "://")):
                raise ValueError("slug_invalid")
            categories = row.get("categories") or []
            bundle = row.get("offerType") == "BUNDLE" or any(
                isinstance(c, dict) and "bundle" in str(c.get("path", "")).lower()
                for c in categories
            )
            route = "bundles" if bundle else "p"
            url = (
                "https://store.epicgames.com/en-US/"
                + route
                + "/"
                + quote(slug.strip("/"), safe="/-_.")
            )
            title = row.get("title")
            title = title if isinstance(title, str) else ""
            title = "".join(c for c in title if ord(c) >= 32)[:200]
            offers.append(Offer(identity, url, True, title))
            seen.add(identity)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            uncertain = True
    return Inventory(
        offers,
        not uncertain,
        "inventory_partial" if uncertain else "inventory_confirmed",
    )


def purchase_candidates(raw):
    """Purchase history candidates only, never proof of current ownership.

    Refund/cancellation semantics are not validated against a live payload.
    Consumers must reconcile with current storefront ownership. Missing or
    non-PURCHASE inventory returns unknown instead of guessing entitlement.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("orders"), list):
        return None
    if len(raw["orders"]) > 1000:
        return None
    found = set()
    total_items = 0
    for order in raw["orders"]:
        if not isinstance(order, dict) or not isinstance(order.get("items"), list):
            return None
        if order.get("orderType") != "PURCHASE":
            return None
        total_items += len(order["items"])
        if len(order["items"]) > 100 or total_items > 2000:
            return None
        for item in order["items"]:
            if (
                not isinstance(item, dict)
                or not item.get("namespace")
                or not item.get("offerId")
            ):
                return None
            found.add(str(item["namespace"]) + ":" + str(item["offerId"]))
    return found


def storefront_owned(button_text):
    """Disabled, coming-soon, unavailable or generic body text is not ownership."""
    return isinstance(button_text, str) and button_text.strip().casefold() in {
        "in library",
        "in your library",
    }
