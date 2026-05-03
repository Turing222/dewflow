"""Compatibility import for moved knowledge worker tasks."""

import sys

from backend.worker.tasks import knowledge_tasks as _module
from backend.worker.tasks.knowledge_tasks import *  # noqa: F403

sys.modules[__name__] = _module

