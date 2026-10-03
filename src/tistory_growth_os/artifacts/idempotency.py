from __future__ import annotations

from pathlib import Path

from ..contracts.json_ast import JsonObject, JsonString, JsonValue
from ..contracts.json_decode import JsonDecodeError, parse_json_file
from .layout import ArtifactWriteError


def existing_bundle_identity(bundle: Path) -> tuple[str, str, str]:
    manifest = bundle / "publish-manifest.json"
    try:
        value = parse_json_file(manifest)
    except (JsonDecodeError, OSError) as error:
        raise ArtifactWriteError(
            "EXISTING_BUNDLE_INVALID",
            "/bundle/publish-manifest.json",
            "existing manifest cannot be read",
        ) from error
    mapping = _object(value)
    return (
        _string(mapping.get("package_id"), "/package_id"),
        _string(mapping.get("idempotency_key"), "/idempotency_key"),
        _string(mapping.get("manifest_id"), "/manifest_id"),
    )


def _object(value: JsonValue) -> JsonObject:
    match value:
        case JsonObject() as mapping:
            return mapping
        case _:
            raise ArtifactWriteError(
                "EXISTING_BUNDLE_INVALID",
                "/bundle/publish-manifest.json",
                "manifest must be an object",
            )


def _string(value: JsonValue | None, path: str) -> str:
    match value:
        case JsonString(value=text) if text:
            return text
        case _:
            raise ArtifactWriteError(
                "EXISTING_BUNDLE_INVALID",
                path,
                "manifest identity must be a non-empty string",
            )
