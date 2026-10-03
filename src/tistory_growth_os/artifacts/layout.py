from __future__ import annotations

from pathlib import Path, PurePath
from typing import final


@final
class ArtifactWriteError(ValueError):
    __slots__ = ("code", "path", "message")

    code: str
    path: str
    message: str

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


def safe_output_root(project_root: Path, relative: str) -> Path:
    path = PurePath(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ArtifactWriteError(
            "OUTPUT_PATH_INVALID",
            "/output",
            "output must be a non-empty project-relative path",
        )
    root = project_root.resolve()
    candidate = root.joinpath(*path.parts)
    current = root
    if project_root.is_symlink():
        _symlink_error(project_root)
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            _symlink_error(current)
    try:
        _ = candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as error:
        raise ArtifactWriteError(
            "OUTPUT_PATH_INVALID",
            "/output",
            "output escapes project root",
        ) from error
    return candidate


def _symlink_error(path: Path) -> None:
    raise ArtifactWriteError(
        "OUTPUT_PATH_INVALID",
        "/output",
        f"symlink component is forbidden: {path.name}",
    )
