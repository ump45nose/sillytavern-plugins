"""Lazy bridge to the original hcaptcha-challenger approach.

No model package, API key, browser or network is loaded at module import.
The public task binds its authorized challenge scope and private model config.
"""

import asyncio
import importlib
import sys


def load_sdk(name="hcaptcha_challenger.agent"):
    # Package initialization installs file sinks inside site-packages before
    # AgentConfig can redirect its runtime files. Dependencies are read-only for
    # the task identity, and SDK debug logs may contain challenge tokens.
    from loguru import logger
    add = logger.add
    logger.remove()
    try:
        logger.add = lambda *args, **kwargs: 0
        return importlib.import_module(name)
    finally:
        logger.add = add
        logger.remove()


class HCaptchaHandler:
    def __init__(self, page, config, *, loader=load_sdk):
        self.page = page
        self.config = config
        self.loader = loader
        self.agent = None

    async def handle(self, obstacle, *, timeout):
        if obstacle.kind != "captcha" or timeout <= 0:
            raise ValueError("invalid_challenge")
        # On-demand loading, analogous to upstream hcaptcha_runtime, but without
        # eagerly importing all OpenCV/model patches for non-challenge tasks.
        module = self.loader("hcaptcha_challenger.agent")
        logging_module = sys.modules.get("loguru")
        if logging_module is not None:
            # The real SDK already imports loguru; injected smoke drivers need
            # no optional package. SDK debug output can contain challenge tokens.
            logging_module.logger.remove()
        if self.agent is None:
            self.agent = module.AgentV(page=self.page, agent_config=self.config)
        signal = await asyncio.wait_for(
            self.agent.wait_for_challenge(), timeout=timeout
        )
        # The caller must observe the page again, regardless of solver response.
        return {
            "solver_signal": getattr(signal, "value", "unknown"),
            "requires_readback": True,
        }

    async def close(self):
        # Never close the caller's browser from a challenge plugin. The task
        # closes context/browser once and exits its Python process after use.
        if self.agent is not None:
            close = getattr(self.agent, "aclose", None)
            if close is not None:
                await asyncio.wait_for(close(), timeout=2)
        self.agent = None
