"""DingTalk polling sources; delivery belongs to mcp_platform.events."""

from .producer import DingTalkProducer, build_producer

__all__ = ["DingTalkProducer", "build_producer"]
