import asyncio
from .crm import assemble as crm_module

MODULE_SOURCES = {
    "health": ["records_health"], "bills": ["records_bills"],
    "crm": ["crm", "plaud"], "media": ["emby", "navidrome", "moviepilot", "qbittorrent"],
    "token": ["token", "usage"], "net": ["usage"], "git": ["github"], "memos": ["memos"],
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


async def modules(manager, ids):
    source_ids = list(dict.fromkeys(s for m in ids for s in MODULE_SOURCES[m]))
    values = dict(zip(source_ids, await asyncio.gather(*(manager.get(s) for s in source_ids))))
    output = {}
    for identifier in ids:
        results = [values[s] for s in MODULE_SOURCES[identifier]]
        data = results[0]["data"] if len(results) == 1 else None
        if identifier == "crm":
            data = crm_module(values["crm"]["data"], values["plaud"]["data"], manager.now())
        output[identifier] = envelope(identifier, results, data)
    return output
