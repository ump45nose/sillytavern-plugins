import asyncio
from .crm import assemble as crm_module
from .token import assemble as token_module

MODULE_SOURCES = {
    "health": ["records_health"], "bills": ["records_bills"],
    "crm": ["crm", "plaud"], "media": ["emby", "navidrome", "moviepilot", "qbittorrent"],
    "token": ["token"], "net": ["usage"], "git": ["github"], "memos": ["memos"],
    "subs": ["records_subscriptions"], "goals": ["review"], "attention": [],
}


def envelope(identifier, results, data=None):
    statuses = [r["status"] for r in results]
    available = [r for r in results if r["data"] is not None]
    if not available:
        status = "unconfigured" if all(s == "unconfigured" for s in statuses) else "error"
        data = None
    elif len(available) < len(results):
        status = "partial"
    elif "stale" in statuses:
        status = "stale"
    else:
        status = "ok"
    return {"module": identifier, "status": status,
            "updated_at": max((r["updated_at"] for r in available), default=None),
            "sources": [{k: r[k] for k in ("id", "status", "updated_at")} for r in results], "data": data}


async def modules(manager, ids, token_range="day"):
    from ..configuration import preferences, subscriptions
    p = preferences(manager.store)
    source_ids = list(dict.fromkeys(s for m in ids for s in MODULE_SOURCES[m]))
    values = dict(zip(source_ids, await asyncio.gather(*(manager.get(s) for s in source_ids))))
    output = {}
    for identifier in ids:
        results = [values[s] for s in MODULE_SOURCES[identifier]]
        data = results[0]["data"] if len(results) == 1 else None
        if identifier == "crm":
            data = crm_module(values["crm"]["data"], values["plaud"]["data"], manager.now(), p["stale_contact_days"], p["cycle_start"])
        if identifier == "media":
            def part(source, field):
                value = values[source]["data"]
                return value.get(field) if value is not None else None
            data = {"continue_watching": part("emby", "continue_watching"), "latest": part("emby", "latest"),
                    "recent_albums": part("navidrome", "recent_albums"), "downloads": part("qbittorrent", "downloads"),
                    "services": [{"id": s, "status": "ok" if values[s]["status"] == "ok" else "error",
                                  "link": manager.media_links[s]} for s in MODULE_SOURCES["media"]]}
        if identifier == "token":
            data = token_module(values["token"]["data"], token_range, manager.now())
        if identifier == "net" and values["usage"]["data"] is not None:
            data = values["usage"]["data"]["net"]
        if identifier == "health" and data is not None:
            data = {**data, **{k:p[k] for k in ("step_goal","kcal_goal","exercise_goal")}}
        if identifier == "bills" and data is not None:
            data = {**data, "month_budget":p["month_budget"]}
        if identifier == "subs":
            from decimal import Decimal
            charges = values["records_subscriptions"]["data"]
            items = [{**item,"monthly_equivalent":float((Decimal(str(item["price"]))/ (12 if item["cycle"]=="year" else 1)).quantize(Decimal("0.01"))),
                      "last_charge":charges["charges"].get(item["id"]) if charges else None} for item in subscriptions(manager.store)]
            data = {"items":items,"monthly_total":float(sum((Decimal(str(x["monthly_equivalent"])) for x in items),Decimal(0)))}
        partial = False
        if identifier in ("git","goals") and data is not None:
            partial = data.get("_partial", False)
            data = {k: v for k, v in data.items() if not k.startswith("_")}
        output[identifier] = envelope(identifier, results, data)
        if identifier == "subs":
            output[identifier]["data"] = data
            if not data["items"]:
                output[identifier]["status"] = "ok"
            elif values["records_subscriptions"]["status"] in ("error","unconfigured") or (values["records_subscriptions"]["data"] or {}).get("partial"):
                output[identifier]["status"] = "partial"
            output[identifier]["updated_at"] = (manager.store.document("subscriptions") or {}).get("updated_at") or manager.now().isoformat()
        if partial and output[identifier]["status"] == "ok":
            output[identifier]["status"] = "partial"
        if identifier == "net" and values["usage"]["data"] and values["usage"]["data"].get("partial") and output[identifier]["status"] == "ok":
            output[identifier]["status"] = "partial"
    from ..attention import calculate, visible
    attention, states = calculate(manager)
    if "git" in output and output["git"]["data"]:
        git = output["git"]["data"]
        output["git"]["data"] = {**git, **{f:[x for x in git[f] if visible(states[x["id"]],manager.now())] for f in ("waiting","blocked")}}
    if "attention" in output:
        output["attention"] = {"module":"attention","status":"ok","updated_at":manager.now().isoformat(),"sources":[],"data":{"items":attention}}
    return output
