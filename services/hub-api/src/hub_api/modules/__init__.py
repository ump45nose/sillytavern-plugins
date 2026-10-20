import asyncio
from .crm import assemble as crm_module
from .token import assemble as token_module

MODULE_SOURCES = {
    "health": ["records_health"], "bills": ["records_bills"],
    "crm": ["crm", "plaud"], "media": ["emby", "navidrome", "moviepilot", "qbittorrent"],
    "token": ["token"], "net": ["usage"], "git": ["github"], "memos": ["memos"],
    "subs": [], "attention": [],
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
    source_ids = list(dict.fromkeys(s for m in ids for s in MODULE_SOURCES[m]))
    values = dict(zip(source_ids, await asyncio.gather(*(manager.get(s) for s in source_ids))))
    output = {}
    for identifier in ids:
        results = [values[s] for s in MODULE_SOURCES[identifier]]
        data = results[0]["data"] if len(results) == 1 else None
        if identifier == "crm":
            data = crm_module(values["crm"]["data"], values["plaud"]["data"], manager.now())
        if identifier == "token":
            data = token_module(values["token"]["data"], token_range, manager.now())
        if identifier == "net" and values["usage"]["data"] is not None:
            data = values["usage"]["data"]["net"]
        output[identifier] = envelope(identifier, results, data)
        if identifier == "net" and values["usage"]["data"] and values["usage"]["data"].get("partial") and output[identifier]["status"] == "ok":
            output[identifier]["status"] = "partial"
    return output
