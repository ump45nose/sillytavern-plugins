import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from mcp_platform import RuntimeConfig


def secret(name):
    value, filename = os.getenv(name, ""), os.getenv(name+"_FILE", "")
    if value and filename: raise ValueError("configure only one credential source: "+name)
    return Path(filename).read_text().strip() if filename else value


def collection_config():
    path = os.getenv("SUBSCRIPTIONS_COLLECTORS_FILE")
    return json.loads(Path(path).read_text()) if path else {}


@dataclass
class Settings:
    database: str
    runtime: RuntimeConfig
    read_token: str = field(repr=False)
    write_token: str = field(repr=False)

    def __post_init__(self):
        if not self.read_token or not self.write_token or self.read_token == self.write_token:
            raise ValueError("distinct nonempty API read and write tokens required")

    @classmethod
    def from_env(cls):
        runtime = RuntimeConfig.from_env("personal-subscriptions")
        runtime.allowed_hosts.extend(("personal-subscriptions", "192.168.31.201"))
        return cls(os.getenv("SUBSCRIPTIONS_DATABASE", "/data/subscriptions.sqlite"), runtime,
                   secret("SUBSCRIPTIONS_API_READ_TOKEN"), secret("SUBSCRIPTIONS_API_WRITE_TOKEN"))
