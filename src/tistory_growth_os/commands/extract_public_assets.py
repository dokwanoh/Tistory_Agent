from __future__ import annotations

from hashlib import sha256
import sys

from ..contracts.json_ast import JsonArray, JsonBoolean, JsonMember, JsonNumber, JsonObject, JsonString
from ..inventory.assets import AssetExtractionError, extract_page_assets


def execute_asset_extraction(page_url: str) -> tuple[int, JsonObject]:
    raw = sys.stdin.buffer.read(5_000_001)
    try:
        if len(raw) > 5_000_000:
            raise AssetExtractionError("input exceeds page size limit")
        page = extract_page_assets(raw.decode("utf-8"), page_url)
    except (AssetExtractionError, UnicodeDecodeError):
        return 2, JsonObject((
            JsonMember("result_code", JsonString("ASSET_EXTRACTION_INVALID")),
            JsonMember("external_write_count", JsonNumber(0)),
        ))
    return 0, JsonObject((
        JsonMember("schema_version", JsonString("1.0.0")),
        JsonMember("page_url", JsonString(page.page_url)),
        JsonMember("html_sha256", JsonString(sha256(raw).hexdigest())),
        JsonMember("status", JsonString("extracted")),
        JsonMember("image_count", JsonNumber(page.image_count)),
        JsonMember("missing_alt_count", JsonNumber(page.missing_alt_count)),
        JsonMember("empty_alt_count", JsonNumber(page.empty_alt_count)),
        JsonMember("omitted_reference_count", JsonNumber(page.omitted_reference_count)),
        JsonMember("source_hint_present", JsonBoolean(page.source_hint_present)),
        JsonMember("media_provenance_status", JsonString("unknown")),
        JsonMember("external_write_count", JsonNumber(0)),
        JsonMember("assets", JsonArray(tuple(JsonObject((
            JsonMember("kind", JsonString(asset.kind)),
            JsonMember("url", JsonString(asset.url)),
            JsonMember("host", JsonString(asset.host)),
            JsonMember("query_redacted", JsonBoolean(asset.query_redacted)),
        )) for asset in page.assets))),
    ))
