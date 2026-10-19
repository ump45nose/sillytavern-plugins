"""One daily claim intent; an uncertain submission is reconciled read-only."""

import json
import os
from pathlib import Path
from common.model import atomic_json


class Journal:
    def __init__(self, context, directory):
        self.context = context
        self.path = Path(directory) / "claim.json"
        self.status = "unknown"
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(4097)
            old = json.loads(raw)
            if (len(raw) > 4096 or not isinstance(old, dict)
                    or set(old) != {"version", "account", "date", "status"}
                    or old["version"] != 1 or old["account"] != context["account"]
                    or not isinstance(old["date"], str)
                    or old["status"] not in {"pending", "complete"}):
                raise ValueError("invalid_action_state")
            if old["date"] == context["business_date"]:
                self.status = old["status"]
        except FileNotFoundError:
            pass

    def set(self, status):
        if status not in {"pending", "complete"}:
            raise ValueError("invalid_action_state")
        atomic_json(self.path, {"version": 1, "account": self.context["account"],
                               "date": self.context["business_date"], "status": status})
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.status = status
