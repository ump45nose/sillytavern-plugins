"""Fail-closed checkout parser, testable without importing browsers or upstream."""

import re
from decimal import Decimal


def zero_total(text, add_to_library=False):
    amounts = re.findall(r"(?im)^\s*[A-Z]{3}\s+([0-9]+[.,][0-9]{2})\s*$", text)
    if (
        not re.search(r"(?im)^\s*(?:total|order total)\b", text)
        and "This is free. Add it to your library to get started." in text
        and amounts
        and add_to_library
    ):
        return all(Decimal(x.replace(",", ".")) == 0 for x in amounts)
    totals = re.findall(
        r"(?im)^\s*(?:total|order total)\s*:?\s*\n?\s*(?:[A-Z]{2,3}\s*)?[$€£¥]?\s*([0-9]+[.,][0-9]{2})[ \t]*$",
        text,
    )
    labels = re.findall(r"(?im)^\s*(?:total|order total)\b", text)
    # Multiple totals or unrecognized trailing text are ambiguous even if one is zero.
    return (
        len(labels) == 1
        and len(totals) == 1
        and Decimal(totals[0].replace(",", ".")) == 0
    )


def cart_safe(items):
    # Empty list is safe; unknown inventory is not.
    return isinstance(items, list) and all(
        isinstance(x, dict) and x.get("explicit_free") is True for x in items
    )
