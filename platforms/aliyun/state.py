"""Bounded, account/day-local action facts; no provider payloads or credentials."""

import json
import os
from pathlib import Path
from common.model import atomic_json

STATES = {"unknown", "pending", "complete", "not_applicable"}


class Journal:
    def __init__(self, context, codes, directory=None):
        if len(codes) > 15 or len(set(codes)) != len(codes):
            raise ValueError("invalid_communities")
        self.path = Path(directory) / "http-actions.json" if directory else None
        self.value = {
            "version": 1,
            "account": context["account"],
            "date": context["business_date"],
            "groups": {},
            "pending_score": "unknown",
        }
        if self.path:
            try:
                with self.path.open("rb") as stream:
                    raw = stream.read(16385)
                if len(raw) > 16384:
                    raise ValueError("invalid_action_state")
                old = json.loads(raw)
                if (
                    set(old) != set(self.value)
                    or old["version"] != 1
                    or old["account"] != context["account"]
                    or not isinstance(old["date"], str)
                    or old["pending_score"] not in STATES
                    or not isinstance(old["groups"], dict)
                    or len(old["groups"]) > 15
                ):
                    raise ValueError("invalid_action_state")
                for code, facts in old["groups"].items():
                    if (
                        not isinstance(code, str)
                        or len(code) > 32
                        or not isinstance(facts, dict)
                        or set(facts) != {"sign", "bonus"}
                        or any(v not in STATES for v in facts.values())
                    ):
                        raise ValueError("invalid_action_state")
                if old["date"] == context["business_date"]:
                    self.value = old
                else:
                    # Sign-in is a new daily action; an unresolved bonus/points
                    # claim can still be the same action after midnight.
                    self.value["groups"] = {
                        code: {
                            "sign": "unknown",
                            "bonus": "pending"
                            if facts["bonus"] == "pending"
                            else "unknown",
                        }
                        for code, facts in old["groups"].items()
                    }
                    if old["pending_score"] == "pending":
                        self.value["pending_score"] = "pending"
            except FileNotFoundError:
                pass
        self.value["groups"] = {
            code: self.value["groups"].get(
                code, {"sign": "unknown", "bonus": "unknown"}
            )
            for code in codes
        }

    def get(self, code, key):
        return self.value["groups"][code][key]

    def set(self, code, key, value):
        self.value["groups"][code][key] = value
        self.save()

    def set_pending(self, value):
        self.value["pending_score"] = value
        self.save()

    def save(self):
        if self.path:
            atomic_json(self.path, self.value)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
