"""Compatibility import for the moved non-streaming chat workflow."""

import sys

from backend.application.chat import web_nonstream_workflow as _module
from backend.application.chat.web_nonstream_workflow import *  # noqa: F403

sys.modules[__name__] = _module

