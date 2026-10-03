from __future__ import annotations

from typing import final


@final
class PublishingInvariantError(ValueError):
    __slots__ = ("code", "path", "message")

    code: str
    path: str
    message: str

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")
