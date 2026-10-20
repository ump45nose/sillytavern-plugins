from .base import Adapter
from zoneinfo import ZoneInfo
from .personal import local_time


class Usage:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    async def token(self):
        response = await self.client.get(self.settings.token_url.rstrip("/") + "/api/stats",
            headers={"Authorization": "Bearer " + self.settings.token_secret.get_secret_value()})
        response.raise_for_status()
        raw = response.json()
        today = raw["periods"]["today"]
        daily = {r["date"]: {"total": r.get("tokens"), "cost": r.get("cost")} for r in raw.get("historyPreview", {}).get("daily", [])}
        # Retain no session, project, account, credential or conversation fields.
        return {"today": {"total": today.get("totalTokens"), "cost": today.get("costUsd")},
                "tools": [{"id": key, "name": key, "total": count} for key, count in today.get("clients", {}).items()],
                "devices": [{"id": d["deviceId"], "name": d.get("hostname"), "total": d.get("periods", {}).get("today", {}).get("totalTokens")}
                            for d in raw.get("devices", [])],
                "daily": daily,
                "limits": [{"tool": p["provider"], "plan": p.get("planLabel"),
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
