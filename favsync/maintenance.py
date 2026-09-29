"""Explicit historical layout maintenance, outside the daily sync CLI."""
import argparse
import json
import os

from .common import process_lock
from .config import load


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("command", choices=["telegram-relayout"])
    args = parser.parse_args()
    from .engine import Engine
    from .migrate import relayout
    cfg = load(args.config, source="telegram")
    with process_lock(cfg["state_dir"]):
        engine = Engine(cfg)
        try:
            print(json.dumps(relayout(engine), ensure_ascii=False, indent=2))
        finally:
            engine.store.close()


if __name__ == "__main__":
    main()
