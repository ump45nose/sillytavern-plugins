"""Lazy bridge to the original hcaptcha-challenger approach.

No model package, API key, browser or network is loaded at module import.
The public task binds its authorized challenge scope and private model config.
"""

import asyncio
import importlib
import sys
from urllib.parse import urlsplit


def response_kind(response):
    """Only provider requests carry challenge data; CORS preflights do not."""
    target = urlsplit(response.url)
    if target.scheme != "https" or not target.hostname or not (
        target.hostname == "hcaptcha.com" or target.hostname.endswith(".hcaptcha.com")
    ):
        return None
    method = response.request.method
    if method == "GET" and target.path.endswith("/hsw.js"):
        return "script"
    if method == "POST" and "/getcaptcha/" in target.path:
        return "payload"
    if method == "POST" and "/checkcaptcha/" in target.path:
        return "answer"
    return None


def _sdk_error(message):
    import json
    record = message.record
    exception = record["exception"]
    print(json.dumps({"event": "epic_challenge_error", "source": record["file"].name,
        "line": record["line"], "function": record["function"],
        "type": exception.type.__name__ if exception else None}), flush=True)


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
    def __init__(self, page, config, *, loader=load_sdk, initial_responses=()):
        self.page = page
        self.config = config
        self.loader = loader
        self.agent = None
        self.initial_responses = tuple(initial_responses)

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
            class CaptchaAgent(module.AgentV):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    arm = self.robotic_arm
                    skill_prompt = arm._match_user_prompt

                    def prompt(kind):
                        question = (arm.captcha_payload.get_requester_question()
                                    if arm.captcha_payload else arm._challenge_prompt)
                        return "\n".join(text for text in (question, skill_prompt(kind)) if text)

                    # The SDK's unmatched skill returns only a generic JobType.
                    # Keep the actual question for each new payload as well.
                    arm._match_user_prompt = prompt

                async def _task_handler(self, response):
                    if response_kind(response) is not None:
                        await super()._task_handler(response)

            self.agent = CaptchaAgent(page=self.page, agent_config=self.config)
        # The SDK catches some internal errors itself. Retain their locations
        # without forwarding its messages, challenge tokens or model responses.
        logger = logging_module.logger if logging_module is not None else None
        sink = logger.add(_sdk_error, level="ERROR", backtrace=False, diagnose=False) if logger else None
        async def solve():
            # The widget can finish getcaptcha before it becomes visible. Feed
            # its observed script/payload once; never repeat a network request.
            responses, self.initial_responses = self.initial_responses, ()
            for response in responses:
                await self.agent._task_handler(response)
            return await self.agent.wait_for_challenge()
        try:
            signal = await asyncio.wait_for(
                solve(), timeout=timeout
            )
        finally:
            if sink is not None:
                logger.remove(sink)
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
