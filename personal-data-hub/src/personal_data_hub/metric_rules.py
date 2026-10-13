"""仪表盘、日报和阅读对象共用的确定性计算规则。"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import json

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


HEALTH = {
    'steps': ('count', ('end_time', 'start_time'), '步', '步数', 'cumulative_max', 1),
    'sleep': ('duration_seconds', ('session_end_time',), '小时', '睡眠', 'interval_union', 1 / 3600),
    'resting_heart_rate': ('bpm', ('time',), '次/分', '静息心率', 'latest', 1),
    'heart_rate': ('bpm', ('time',), '次/分', '心率', 'range_average', 1),
    'active_calories': ('calories', ('end_time', 'start_time'), '千卡', '活动热量', 'cumulative_max', 1),
    'total_calories': ('calories', ('end_time', 'start_time'), '千卡', '总热量', 'cumulative_max', 1),
    'oxygen_saturation': ('percentage', ('time',), '%', '血氧', 'latest', 1),
    'basal_metabolic_rate': ('watts', ('time',), 'W', '基础代谢率', 'latest', 1),
    'exercise': ('duration_seconds', ('end_time',), '分钟', '运动记录时长', 'interval_union', 1 / 60),
}


def health_samples(payload, keys=None):
    if isinstance(payload, str): payload = json.loads(payload)
    result = {}
    for key in keys or HEALTH:
        field, times, *_ = HEALTH[key]
        source = payload.get(key, [])
        if not isinstance(source, list): source = [{field: source, times[0]: payload.get('timestamp')}] if number(source) is not None else []
        values = []
        for index, sample in enumerate(source):
            if not isinstance(sample, dict): continue
            value = number(sample.get(field)); timestamp = next((when(sample.get(k)) for k in times if when(sample.get(k))), None)
            if value is None or timestamp is None: continue
            meta = sample.get('metadata') or {}
            item = dict(time=timestamp.isoformat(), value=value, origin=str(meta.get('data_origin') or '')[:160], device=str(meta.get('device') or '')[:160])
            if key in ('steps', 'active_calories', 'total_calories') and when(sample.get('start_time')) and when(sample['start_time']) <= timestamp:
                item['day_time'] = when(sample['start_time']).isoformat()
            values.append((index, item))
        result[key] = values
    return result


def health_value(key, samples):
    """Input samples are already deduplicated and restricted to a business day."""
    if not samples: return None
    method, factor = HEALTH[key][-2:]
    if method == 'interval_union':
        intervals = sorted((when(s['time']) - timedelta(seconds=s['value']), when(s['time'])) for s in samples if 0 < s['value'] <= 86400)
        merged = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]: merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else: merged.append((start, end))
        value = sum((b-a).total_seconds() for a,b in merged) if merged else None
    elif method == 'cumulative_max': value = max(s['value'] for s in samples)
    elif method == 'range_average': value = sum(s['value'] for s in samples) / len(samples)
    else: value = max(samples, key=lambda s: when(s['time']))['value']
    return round(value * factor, 2) if value is not None else None


def bill_kind(value):
    return 'transfer' if value == 'Transfer' else 'expense' if value.startswith('Expend') else 'income' if value.startswith('Income') else 'unknown'


def finance_totals(bills):
    totals = {}
    for bill in bills:
        currency = bill.get('currency') or '未知币种'
        values = totals.setdefault(currency, dict(currency=currency, expense=Decimal(0), income=Decimal(0), transfer=Decimal(0), pending_count=0, unclassified_count=0))
        kind = bill_kind(str(bill.get('type', '')))
        try: amount = Decimal(str(bill.get('amount', '')))
        except InvalidOperation: amount = Decimal('NaN')
        if bill.get('state') == 'Wait2Edit': values['pending_count'] += 1
        elif kind == 'unknown' or not amount.is_finite(): values['unclassified_count'] += 1
        else: values[kind] += amount
    return [{k: str(v) if isinstance(v, Decimal) else v for k,v in value.items()} for _,value in sorted(totals.items())]


def sum_field(items, key):
    values = [number(item.get(key)) for item in items]
    present = [value for value in values if value is not None]
    return sum(present) if present else None
