"""Strict Rewards aggregation. Null counters and unknown eligibility stay unknown."""

from common.model import progress


def aggregate(items, inventory_complete=False):
    if not isinstance(items, list) or not inventory_complete:
        return "unknown"
    if not items:
        return "not_applicable"
    states = []
    for item in items:
        if not isinstance(item, dict):
            states.append("unknown")
            continue
        eligibility = item.get("eligibility")
        if eligibility == "not_applicable":
            states.append("not_applicable")
        elif eligibility == "blocked":
            states.append("blocked")
        elif eligibility == "eligible":
            states.append(progress(item.get("current"), item.get("max")))
        else:
            states.append("unknown")
    if "unknown" in states:
        return "unknown"
    if "incomplete" in states:
        return "incomplete"
    if "blocked" in states:
        return "blocked"
    return "complete" if "complete" in states else "not_applicable"


def summarize(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("fresh") is not True:
        return {k: "unknown" for k in ("daily", "desktop_search", "explore", "reward")}
    return {
        k: aggregate(snapshot.get(k), snapshot.get(k + "_inventory_complete") is True)
        for k in ("daily", "desktop_search", "explore", "reward")
    }
