from .base import Adapter
from zoneinfo import ZoneInfo
from .personal import local_time
import asyncio


def usage_parts(counts, costs=None, models=False):
    if counts is None:
        return None
    return [{'id': key, 'name': key, 'total': count, 'cost': (costs or {}).get(key),
             **({'provider': None} if models else {})} for key, count in counts.items()]


def history_day(row):
    def parts(field):
        values = row.get(field)
        if values is None:
            return None
        return [{'id': key, 'name': key, 'total': v.get('tokens'), 'cost': v.get('cost'),
                 **({'provider': None} if field == 'perModel' else {})} for key, v in values.items()]
    return {'total': row.get('tokens'), 'cost': row.get('cost'),
            'tools': parts('perClient'), 'models': parts('perModel')}


class Usage:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    async def token(self):
        async def read(path):
            response = await self.client.get(self.settings.token_url.rstrip('/')+path,
                headers={'Authorization': 'Bearer '+self.settings.token_secret.get_secret_value()})
            response.raise_for_status()
            return response.json()
        raw, history, device_history = await asyncio.gather(read('/api/stats'), read('/api/history'), read('/api/devices'))
        today = raw["periods"]["today"]
        daily = {r['date']: history_day(r) for r in history['daily']}
        histories = {d['deviceId']: {r['date']: {'total': r.get('tokens'), 'cost': r.get('cost')}
                                  for r in d.get('history', {}).get('daily', [])}
                     for d in device_history['devices'] if d.get('historyAvailable') and d.get('history') is not None}
        devices = [{'id': d['deviceId'], 'name': d.get('hostname'),
                    'total': d.get('periods', {}).get('today', {}).get('totalTokens'),
                    'cost': d.get('periods', {}).get('today', {}).get('costUsd')}
                   for d in raw.get('devices', [])]
        def sessions(period):
            data = raw['periods'].get(period, {})
            if 'sessions' not in data or raw.get('sessionDetailsOmitted', {}).get(period, 0):
                return None
            rows = sorted(data['sessions'].items(), key=lambda r: (-(r[1].get('totalTokens') or 0), r[0]))[:20]
            names = {}
            for d in raw.get('devices', []):
                for key in d.get('periods', {}).get(period, {}).get('sessions', {}):
                    names.setdefault(key, set()).add(d.get('hostname') or d['deviceId'])
            result = []
            for key, row in rows:
                models = row.get('models') or {}
                owners = names.get(key, set())
                result.append({'id': key, 'title': row.get('title') or None, 'tool': row.get('client'),
                    'model': next(iter(models)) if len(models) == 1 else None,
                    'device': next(iter(owners)) if len(owners) == 1 else None,
                    'total': row.get('totalTokens'), 'cost': row.get('costUsd'),
                    'updated_at': local_time(row.get('lastUsedAt'), ZoneInfo('Asia/Shanghai'))})
            return result
        # Account display identity is authenticated metadata; no credentials or conversation content.
        return {"today": {"total": today.get("totalTokens"), "cost": today.get("costUsd")},
                'tools': usage_parts(today.get('clients'), today.get('clientCosts')),
                'models': usage_parts(today.get('models'), today.get('modelCosts'), models=True),
                'devices': devices, 'device_daily': histories,
                'sessions': {'day': sessions('today'), 'calendar_month': sessions('month')},
                "daily": daily,
                "limits": [{"tool": p["provider"], "plan": p.get("planLabel"),
                            "id": p.get("webAccountKey") or p.get("accountKey"),
                            "account": p.get("accountName") or p.get("accountEmail"),
                            "windows": [{"label": w.get("label") or w.get("kind"),
                                "percent": w.get("usedPercent") if p.get("status") == "ok" and not p.get("stale") else None,
                                "resets_at": local_time(w.get("resetsAt"), ZoneInfo("Asia/Shanghai"))} for w in p.get("windows", [])]}
                           for p in raw.get("limits", {}).get("providers", [])],
                "observed_at": raw.get("updatedAt")}

    async def net(self):
        response = await self.client.get(self.settings.usage_url.rstrip("/") + "/api/v1/net",
            headers={"Authorization": "Bearer " + self.settings.usage_token.get_secret_value()})
        response.raise_for_status()
        raw = response.json()
        return {"net": raw["data"], "observed_at": raw.get("updated_at"), "partial": bool(raw.get("gaps"))}

    def adapters(self):
        return [Adapter("token", "Token Monitor Hub", 30, self.token if self.settings.token_secret else None),
                Adapter("usage", "Usage Monitor / ShellCrash", 30, self.net if self.settings.usage_token else None)]
