from __future__ import annotations

import os
from pathlib import Path
import tempfile

from ..artifacts.layout import safe_output_root
from ..contracts.json_ast import JsonValue
from ..contracts.json_encode import encode_json, encode_json_bytes


def write_stdout(value: JsonValue) -> None:
    print(encode_json(value), end="")


def write_stderr(value: JsonValue) -> None:
    import sys

    _ = sys.stderr.write(encode_json(value))


def write_optional_json(root: Path, relative: str | None, value: JsonValue) -> None:
    if relative is None:
        return
    path = safe_output_root(root, relative)
    _ = path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(encode_json_bytes(value))
        _ = os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise
