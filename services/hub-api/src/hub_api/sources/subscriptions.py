from .base import Adapter


class Subscriptions:
    def __init__(self, client, settings): self.client, self.settings = client, settings

    async def request(self, method, path, *, write=False, **kwargs):
        token = self.settings.subscriptions_write_token if write else self.settings.subscriptions_token
        return await self.client.request(method, self.settings.subscriptions_url.rstrip('/')+'/api/v1/'+path,
            headers={'Authorization': 'Bearer '+token.get_secret_value(), **kwargs.pop('headers', {})}, **kwargs)

    async def fetch(self):
        response = await self.request('GET', 'subscriptions/summary')
        response.raise_for_status()
        raw = response.json()
        items = []
        for item in raw['items']:
            items.append({**item, 'price': float(item['price']) if item['price'] is not None else None,
                          'monthly_equivalent': float(item['monthly_equivalent']) if item['monthly_equivalent'] is not None else None,
                          'price_converted': {k: float(v) for k,v in item.get('price_converted', {}).items()},
                          'monthly_converted': {k: float(v) for k,v in item.get('monthly_converted', {}).items()},
                          'last_charge': None})
        totals = {k: float(v) for k,v in raw['monthly_by_currency'].items()}
        converted = {k: float(v) for k,v in raw.get('monthly_converted', {}).items()}
        return {**raw, 'items': items, 'monthly_by_currency': totals,
                'monthly_converted': converted,
                'monthly_total': converted.get('CNY', totals.get('CNY') if totals and not (set(totals)-{'CNY'}) else None)}

    def adapter(self):
        return Adapter('subscriptions', 'Personal Subscriptions', 30, self.fetch if self.settings.subscriptions_token else None)
