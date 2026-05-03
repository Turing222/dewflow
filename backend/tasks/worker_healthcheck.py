"""Compatibility import for moved worker healthcheck helpers."""

import sys

from backend.worker.tasks import healthcheck as _module
from backend.worker.tasks.healthcheck import *  # noqa: F403

sys.modules[__name__] = _module

