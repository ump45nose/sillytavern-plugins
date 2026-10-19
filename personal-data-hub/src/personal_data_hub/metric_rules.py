"""仪表盘、日报和阅读对象共用的确定性计算规则。"""

# Helpers retain the existing export timestamp and finite-number semantics.
def number(value):
    import math
    try:
        result = float(value)
        return result if not isinstance(value, bool) and math.isfinite(result) else None
    except (ValueError, TypeError): return None


def when(value):
    from datetime import datetime, timezone
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError): return None


def sum_field(items, key):
    values = [number(item.get(key)) for item in items]
    present = [value for value in values if value is not None]
    return sum(present) if present else None
