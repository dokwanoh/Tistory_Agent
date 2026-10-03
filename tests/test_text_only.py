from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Final

import pytest
from tests.review_support import approve_fixture

from tistory_growth_os.contracts.json_ast import JsonArray, JsonMember, JsonNumber, JsonObject, JsonString
from tistory_growth_os.contracts.json_decode import parse_json, parse_json_file
from tistory_growth_os.contracts.json_encode import encode_json
from tistory_growth_os.contracts.registry import ContractRegistry
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.domain.results import PipelineReady
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline


ROOT: Final = Path(__file__).resolve().parents[1]


def text_only_value() -> JsonObject:
    value = parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    assert isinstance(value, JsonObject)
    return JsonObject(tuple(
        JsonMember("media", JsonArray(())) if item.key == "media" else item
        for item in value.members
    ))


def test_explicit_empty_media_passes_schema() -> None:
    # Given: an explicit text-only input, not a missing field.
    value = text_only_value()
    # When: the request contract is applied.
    issues = ContractRegistry.load(ROOT / "contracts").validate("offline-run-request", value)
    # Then: zero media is a valid editorial choice.
    assert issues == ()


def test_explicit_empty_media_decodes_to_empty_tuple() -> None:
    # Given: a text-only input at the typed boundary.
    value = text_only_value()
    # When: the decoder parses it.
    request = decode_offline_run_request(value)
    # Then: no placeholder is invented.
    assert request.media == ()


def test_text_only_render_omits_entire_media_region() -> None:
    # Given: typed text-only data independent of the incoming schema.
    original = decode_offline_run_request(parse_json_file(ROOT / "tests/fixtures/topic_supported.json"))
    request = replace(original, media=())
    # When: the full in-memory pipeline renders it.
    result = run_offline_pipeline(ROOT, request, parse_canonical_input_digest("c" * 64))
    # Then: no empty media landmark or image exists; source navigation remains.
    assert isinstance(result, PipelineReady)
    assert 'class="media-region"' not in result.article_html
    assert 'id="media-title"' not in result.article_html
    assert "<img" not in result.article_html
    assert 'class="sources"' in result.article_html


@pytest.mark.parametrize("malformed", [None, JsonString("none"), JsonArray((JsonObject(()),))])
def test_missing_or_malformed_media_stays_invalid(malformed: JsonString | JsonArray | None) -> None:
    # Given: absence, a wrong container, or an incomplete supplied media item.
    value = text_only_value()
    members = tuple(item for item in value.members if item.key != "media")
    invalid = JsonObject(members if malformed is None else (*members, JsonMember("media", malformed)))
    # When: the boundary contract evaluates the input.
    issues = ContractRegistry.load(ROOT / "contracts").validate("offline-run-request", invalid)
    # Then: only an explicit valid array can express a media choice.
    assert issues


@pytest.mark.parametrize("held", [False, True])
def test_text_only_cli_keeps_quality_boundary_and_replay(tmp_path: Path, held: bool) -> None:
    # Given: text-only content with either declared use or an unresolved source hold.
    _ = shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    raw = encode_json(text_only_value())
    if held:
        raw = raw.replace('"link_and_paraphrase"', '"review_required"', 1)
    _ = (tmp_path / "input.json").write_text(raw)
    if not held:
        _ = approve_fixture(tmp_path, tmp_path / "input.json")
    command = [sys.executable, "-m", "tistory_growth_os", "run", "--root", str(tmp_path),
               "--fixture", "input.json", "--output", "output", "--dry-run"]
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    # When: the real CLI runs; only ready packages support same-output replay.
    runs = tuple(subprocess.run(command, env=environment, capture_output=True, text=True,
                                check=False, timeout=15) for _ in range(1 if held else 2))
    # Then: replay preserves identity or the hold, with zero external writes.
    expected = "POLICY_EVIDENCE_REQUIRED" if held else "READY_FOR_APPROVAL"
    payloads = tuple(parse_json(run.stderr if held else run.stdout) for run in runs)
    if not held:
        assert payloads[0] == payloads[1]
    for run, payload in zip(runs, payloads, strict=True):
        assert run.returncode == (2 if held else 0)
        assert isinstance(payload, JsonObject)
        assert payload.get("result_code") == JsonString(expected)
        assert payload.get("external_write_count") == JsonNumber(0)
    bundle = tmp_path / "output/bundle"
    assert bundle.exists() is not held
    if not held:
        assert "<img" not in (bundle / "article.html").read_text()
    else:
        report = parse_json_file(tmp_path / "output/diagnostics/quality-report.json")
        assert ContractRegistry.load(tmp_path / "contracts").validate("quality-report", report) == ()
