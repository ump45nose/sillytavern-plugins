#!/usr/bin/env python3
"""Stateless JSON planning through the existing Lingjun runtime provider."""
import json
import os
from pathlib import Path
import sys

PROFILE = Path("/home/hermes/.hermes/profiles/lingjun")
REPO = Path("/home/hermes/.hermes/hermes-agent")


def main():
    os.environ["HERMES_HOME"] = str(PROFILE)
    sys.path.insert(0, str(REPO))
    from dotenv import load_dotenv
    load_dotenv(PROFILE / ".env", override=False)
    from agent.secret_scope import build_profile_secret_scope, set_secret_scope
    set_secret_scope(build_profile_secret_scope(PROFILE))
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from agent.auxiliary_client import call_llm
    runtime = resolve_runtime_provider(requested="custom:cpa-local", target_model="grok-4.7")
    if "--window" in sys.argv:
        from agent.model_metadata import get_model_context_length
        from hermes_cli.config import load_config
        cfg = load_config()
        print(get_model_context_length("grok-4.7", base_url=runtime.get("base_url", ""),
                                       api_key=runtime.get("api_key", ""), provider="custom:cpa-local",
                                       config_context_length=cfg.get("model", {}).get("context_length")))
        return
    value = json.load(sys.stdin)
    response = call_llm(task="companion_planning", provider="custom:cpa-local", model="grok-4.7",
                        main_runtime={**runtime, "model": "grok-4.7"},
                        messages=value["messages"], temperature=0.65,
                        max_tokens=value.get("max_tokens", 4000), timeout=240)
    if not response.choices[0].message.content:
        raise RuntimeError("empty planning result")
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
