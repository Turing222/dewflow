"""Compatibility import for moved LLM worker tasks."""

import sys

from backend.worker.tasks import llm_tasks as _module
from backend.worker.tasks.llm_tasks import *  # noqa: F403

sys.modules[__name__] = _module

