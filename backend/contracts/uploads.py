"""Upload file contracts shared outside the web layer."""

from typing import Protocol


class UploadFileLike(Protocol):
    """Minimal async upload object shape used by services and workflows."""

    filename: str | None
    size: int | None

    async def read(self, size: int = -1) -> bytes: ...
