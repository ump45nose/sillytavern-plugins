"""Compatibility import; implementation lives in media-capabilities."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("media_capabilities.acquisition.media_types")
