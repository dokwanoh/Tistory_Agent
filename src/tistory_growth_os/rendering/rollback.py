from __future__ import annotations

from pathlib import PurePosixPath

from ..contracts.json_ast import JsonArray, JsonMember, JsonObject, JsonString


def build_local_rollback(affected_paths: tuple[str, ...]) -> JsonObject:
    for value in affected_paths:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("rollback path must stay inside the local bundle")
    return JsonObject((
        JsonMember("action", JsonString("discard_local_bundle")),
        JsonMember("precondition", JsonString("not_published")),
        JsonMember("remote_actions", JsonArray(())),
        JsonMember(
            "affected_paths",
            JsonArray(tuple(JsonString(value) for value in affected_paths)),
        ),
    ))
