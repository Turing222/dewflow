"""Compatibility import for the moved streaming chat workflow."""

import sys

from backend.application.chat import web_stream_workflow as _module
from backend.application.chat.web_stream_workflow import *  # noqa: F403

sys.modules[__name__] = _module

