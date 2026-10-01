"""Lazy bridge to the original hcaptcha-challenger approach.

No model package, API key, browser or network is loaded at module import. Real
use requires a trusted runtime authorization and separately configured model
credentials/data-sharing permission. This module is not wired to public claim
yet; no live challenge was used in tests.
"""

import asyncio
import importlib


class HCaptchaHandler:
    def __init__(self, page, config, *, loader=importlib.import_module):
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
