"""Daily reference rates; collection writes, reads only use the saved snapshot."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import httpx


RATE_URL = "https://open.er-api.com/v6/latest/USD"
SOURCE_URL = "https://www.exchangerate-api.com"


def money(value):
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def convert(amount, currency, snapshot):
    if amount is None:
        return {}
    amount = Decimal(str(amount))
    result = {currency: money(amount)} if currency in ("USD", "CNY") else {}
    rates = snapshot.get("rates", {})
    if currency in rates:
        usd = amount / Decimal(rates[currency])
        result.update({target: money(usd * Decimal(rates[target])) for target in ("USD", "CNY")})
    return result


def refresh(store, client=None):
    now = datetime.now(timezone.utc)
    previous = store.exchange_rates()
    attempted = previous.get("last_attempt_at")
    # Provider updates daily. Rate-limit failed retries as well as successful refreshes.
    if attempted and (now - datetime.fromisoformat(attempted)).total_seconds() < 3600:
        return "cached"
    updated = previous.get("observed_at")
    if updated and (now - datetime.fromisoformat(updated)).total_seconds() < 86400:
        return "cached"
    try:
        if client is None:
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as own_client:
                return refresh(store, own_client)
        response = client.get(RATE_URL)
        response.raise_for_status()
        raw = response.json()
        if raw.get("result") != "success" or raw.get("base_code") != "USD":
            raise ValueError("invalid rate response")
        observed = datetime.fromtimestamp(raw["time_last_update_unix"], timezone.utc)
        if not 0 <= (now - observed).total_seconds() <= 7 * 86400:
            raise ValueError("invalid rate timestamp")
        rates = {key: Decimal(str(value)) for key, value in raw["rates"].items()}
        if any(not value.is_finite() or value <= 0 for value in rates.values()):
            raise ValueError("invalid rate value")
        if rates["USD"] != 1 or not {"CNY", "BOB", "INR"} <= rates.keys():
            raise ValueError("missing rate")
        snapshot = {"base": "USD", "rates": {k: str(v) for k, v in rates.items()},
                    "observed_at": observed.isoformat(), "source_url": SOURCE_URL}
        store.save_exchange_rates({**snapshot, "last_attempt_at": now.isoformat(), "error": None})
        return "ok"
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError, ArithmeticError):
        store.save_exchange_rates({**previous, "last_attempt_at": now.isoformat(), "error": "rates_unavailable"})
        return "unavailable"
