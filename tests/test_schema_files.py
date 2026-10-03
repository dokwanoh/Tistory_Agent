from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMAS = CONTRACTS / "schemas"
FIXTURES = ROOT / "tests" / "fixtures"
DOMAIN_NAMES = (
    "topic-candidate",
    "content-opportunity",
    "source-evidence",
    "claim",
    "content-brief",
    "article-draft",
    "quality-report",
    "publish-manifest",
    "published-post",
    "post-metrics",
    "experiment",
    "evolution-proposal",
)
SUPPORT_NAMES = (
    "offline-run-request",
    "run-report",
    "process-traceability",
    "policy-evidence",
    "owner-decision",
    "public-blog-inventory",
)
ALL_NAMES = DOMAIN_NAMES + SUPPORT_NAMES


def _json_tool(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, "-m", "json.tool", str(path)),
        check=False,
        capture_output=True,
        text=True,
    )


def test_catalog_registers_all_domain_and_support_schemas() -> None:
    # Given / When
    catalog = (CONTRACTS / "catalog.json").read_text(encoding="utf-8")

    # Then
    assert catalog.count('"name":') == len(ALL_NAMES)
    assert catalog.count('"version": "1.0.0"') == len(ALL_NAMES)
    for name in ALL_NAMES:
        assert catalog.count(f'"name": "{name}"') == 1
        assert catalog.count(f'"file": "schemas/{name}.schema.json"') == 1


def test_catalog_schemas_are_strict_draft_2020_12() -> None:
    # Given / When
    registered = tuple(
        (
            name,
            SCHEMAS / f"{name}.schema.json",
        )
        for name in ALL_NAMES
    )

    # Then
    for name, path in registered:
        result = _json_tool(path)
        text = path.read_text(encoding="utf-8")
        assert result.returncode == 0, result.stderr
        assert '"$schema": "https://json-schema.org/draft/2020-12/schema"' in text
        assert f'"$id": "urn:tistory-growth-os:schema:{name}:1.0.0"' in text
        assert '"schema_version": {"type": "string", "const": "1.0.0"}' in text
        assert '"additionalProperties": false' in text
        assert '"required": [' in text
        assert '"schema_version"' in text
        assert '"$ref": "http' not in text
        for unsupported in ('"allOf"', '"anyOf"', '"not"', '"if"', '"then"'):
            assert unsupported not in text


def test_supported_fixture_carries_offline_contract_facts() -> None:
    # Given / When
    text = (FIXTURES / "topic_supported.json").read_text(encoding="utf-8")
    result = _json_tool(FIXTURES / "topic_supported.json")

    # Then
    assert result.returncode == 0, result.stderr
    assert '"title": "티스토리 글 발행 전 품질 체크리스트"' in text
    assert '"as_of": "2026-08-15"' in text
    assert '"idempotency_key": "fixture-supported-v1"' in text
    assert '"kind": "first_person_experience"' not in text
    assert '"alt": "티스토리 글 발행 전 점검 항목을 보여 주는 이미지 자리표시자"' in text
    assert "https://notice.tistory.com/2664" in text


def test_opportunity_scores_allow_unknown_baselines() -> None:
    # Given / When
    text = (SCHEMAS / "content-opportunity.schema.json").read_text(
        encoding="utf-8"
    )

    # Then
    score_fields = (
        "demand_score",
        "authority_score",
        "reader_value_score",
        "monetization_score",
        "risk_penalty",
        "cannibalization_penalty",
    )
    assert text.count('"oneOf": [') == len(score_fields)
    assert text.count('{"type": "string", "const": "unknown"}') == len(
        score_fields
    )


def test_publish_manifest_artifacts_are_audit_complete() -> None:
    # Given / When
    text = (SCHEMAS / "publish-manifest.schema.json").read_text(encoding="utf-8")

    # Then
    assert '"relative_path": {"type": "string", "minLength": 1}' in text
    assert '"media_type": {"type": "string", "minLength": 1}' in text
    assert '"byte_count": {"type": "integer", "minimum": 0}' in text
    assert '"schema_version": {"type": "string", "const": "1.0.0"}' in text
    assert (
        '"required": ["name", "relative_path", "media_type", '
        '"byte_count", "sha256", "schema_version"]'
    ) in text


def test_fixture_delta_changes_only_the_named_claim_gate() -> None:
    # Given
    supported_result = _json_tool(FIXTURES / "topic_supported.json")
    unsupported_result = _json_tool(FIXTURES / "topic_unsupported_claim.json")
    experience_result = _json_tool(FIXTURES / "topic_unverified_experience.json")
    assert supported_result.returncode == 0, supported_result.stderr
    assert unsupported_result.returncode == 0, unsupported_result.stderr
    assert experience_result.returncode == 0, experience_result.stderr

    # When
    supported = supported_result.stdout.splitlines()
    unsupported_delta = tuple(
        difflib.ndiff(supported, unsupported_result.stdout.splitlines())
    )
    experience_delta = tuple(
        difflib.ndiff(supported, experience_result.stdout.splitlines())
    )

    # Then
    assert sum(line.startswith("- ") for line in unsupported_delta) == 1
    assert sum(line.startswith("+ ") for line in unsupported_delta) == 1
    assert any('"support_state": "unsupported"' in line for line in unsupported_delta)
    assert sum(line.startswith("- ") for line in experience_delta) == 1
    assert sum(line.startswith("+ ") for line in experience_delta) == 1
    assert any('"kind": "first_person_experience"' in line for line in experience_delta)


def test_malformed_fixture_is_the_only_syntax_invalid_fixture() -> None:
    # Given / When
    results = {
        path.name: _json_tool(path).returncode
        for path in sorted(FIXTURES.glob("topic_*.json"))
    }

    # Then
    assert results == {
        "topic_malformed.json": 1,
        "topic_rights_pending.json": 0,
        "topic_supported.json": 0,
        "topic_text_only.json": 0,
        "topic_unsupported_claim.json": 0,
        "topic_unverified_experience.json": 0,
    }
