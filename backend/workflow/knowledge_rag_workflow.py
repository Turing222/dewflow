"""Compatibility import for the moved knowledge ingestion workflow."""

import sys

from backend.application.knowledge import ingestion_workflow as _module
from backend.application.knowledge.ingestion_workflow import *  # noqa: F403

sys.modules[__name__] = _module

