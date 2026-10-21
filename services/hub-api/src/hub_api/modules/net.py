from datetime import timedelta


def assemble(source, plans, now):
    """Manual quotas share the router counter; never allocate usage among plans."""
    data = source['net'] if source else {}
    pools = []
    for plan in plans:
        start = now.date().replace(day=plan['reset_day'])
        if start > now.date():
            start = (start.replace(day=1) - timedelta(days=1)).replace(day=plan['reset_day'])
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=plan['reset_day'])
        pools.append({
            'id': plan['id'], 'name': plan['name'], 'total_bytes': plan['total_bytes'],
            'used_bytes': data.get('month_bytes') if plan['reset_day'] == 1 else None,
            'period_start': start.isoformat(), 'period_end': (next_month - timedelta(days=1)).isoformat(),
            'expires_on': plan['expires_on'], 'source': 'manual',
        })
    return {**data, 'pools': pools}
