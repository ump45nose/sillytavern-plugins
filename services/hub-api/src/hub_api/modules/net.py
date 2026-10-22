def assemble(source, subscriptions, now):
    """Supplier quotas and local router traffic are separate observations."""
    pools = []
    for item in (subscriptions or {}).get('items', []):
        if item.get('category') != 'network' or not item.get('active'): continue
        quota = item.get('quota') or {}
        reading = quota.get('reading') or {}
        window = next((w for w in reading.get('windows', []) if w['id'] == 'traffic'), {})
        valid = quota.get('status') == 'ok' and not quota.get('stale', True)
        pools.append({'id': item['id'], 'name': item['name'],
            'total_bytes': window.get('limit') if valid else None,
            'used_bytes': window.get('used') if valid else None,
            'period_start': None, 'period_end': None,
            'expires_on': (reading.get('expires_at') or item.get('expires_on') or '')[:10] or None,
            'source': 'supplier', 'status': quota.get('status', 'unknown'), 'observed_at': reading.get('observed_at')})
    return {**(source['net'] if source else {}), 'pools': pools}
