"""Compatibility import for the moved knowledge upload workflow."""

import sys

from backend.application.knowledge import upload_workflow as _module
from backend.application.knowledge.upload_workflow import *  # noqa: F403

sys.modules[__name__] = _module

