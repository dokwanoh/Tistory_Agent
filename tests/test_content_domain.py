from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest

from tistory_growth_os.contracts.json_ast import (
    JsonArray,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
    JsonValue,
)
from tistory_growth_os.contracts.json_decode import JsonDecodeError, parse_json_file
from tistory_growth_os.domain.common import UnknownScore
from tistory_growth_os.domain.content_decode import (
    decode_content_opportunity,
    decode_offline_run_request,
)
from tistory_growth_os.domain.content_catalog import CONTENT_ENTITY_CONTRACTS
from tistory_growth_os.domain.ids import (
    EvolutionProposalId,
    ExperimentId,
    ManifestId,
    MetricsId,
    PackageId,
    PostId,
    QualityReportId,
)


ROOT = Path(__file__).resolve().parents[1]


def _member(key: str, value: str) -> JsonMember:
    return JsonMember(key, JsonString(value))


def _member_number(key: str, value: int | Decimal) -> JsonMember:
    return JsonMember(key, JsonNumber(value))


def _replace_first_outline_claim(value: JsonValue, claim_id: str) -> JsonArray:
    assert isinstance(value, JsonArray)
    first = value.items[0]
    assert isinstance(first, JsonObject)
    changed_first = JsonObject(
        tuple(
            JsonMember(member.key, JsonArray((JsonString(claim_id),)))
            if member.key == "claim_ids"
            else member
            for member in first.members
        )
    )
    return JsonArray((changed_first, *value.items[1:]))


def _opportunity_value(evaluated_at: str) -> JsonObject:
    return JsonObject(
        (
            _member("schema_version", "1.0.0"),
            _member("opportunity_id", "opp_fixture"),
            _member("topic_id", "topic_fixture"),
            _member("demand_score", "unknown"),
            _member("authority_score", "unknown"),
            _member("reader_value_score", "unknown"),
            _member_number("monetization_score", Decimal("25.5")),
            _member_number("risk_penalty", 10),
            _member("cannibalization_penalty", "unknown"),
            _member("confidence", "low"),
            _member("score_version", "hypothesis-v1"),
            _member("evaluated_at", evaluated_at),
        )
    )


def test_supported_fixture_decodes_immutable_korean_provenance() -> None:
    request = decode_offline_run_request(
        parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    )

    assert request.topic.title == "티스토리 글 발행 전 품질 체크리스트"
    assert request.evidence[0].publisher == "Tistory"
    assert request.evidence[0].checked_at.isoformat() == "2026-08-15T00:00:00+09:00"
    assert request.outline[0].claim_ids == (request.claims[0].claim_id,)
    with pytest.raises(FrozenInstanceError):
        setattr(request.topic, "title", "변경")


def test_unknown_opportunity_scores_are_preserved() -> None:
    opportunity = decode_content_opportunity(
        _opportunity_value("2026-08-15T01:00:00.123Z")
    )

    assert opportunity.demand_score is UnknownScore.UNKNOWN
    assert opportunity.monetization_score == Decimal("25.5")
    assert opportunity.evaluated_at.isoformat() == "2026-08-15T01:00:00.123000+00:00"


def test_opportunity_datetime_requires_explicit_timezone() -> None:
    with pytest.raises(JsonDecodeError) as caught:
        decode_content_opportunity(_opportunity_value("2026-08-15T01:00:00.123"))

    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == "/evaluated_at"


@pytest.mark.parametrize(
    ("value", "pointer"),
    (
        (JsonObject(()), "/schema_version"),
        (
            JsonObject((_member("schema_version", "1.0.0"), _member("opportunity_id", "opp_fixture"))),
            "/topic_id",
        ),
    ),
)
def test_missing_required_field_fails_with_stable_issue(value: JsonObject, pointer: str) -> None:
    with pytest.raises(JsonDecodeError) as caught:
        decode_content_opportunity(value)

    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == pointer


def test_wrong_type_fails_at_exact_path() -> None:
    source = parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    assert isinstance(source, JsonObject)
    changed = JsonObject(
        tuple(
            type(member)(member.key, JsonNumber(3) if member.key == "title" else member.value)
            for member in source.members
        )
    )

    with pytest.raises(JsonDecodeError) as caught:
        decode_offline_run_request(changed)

    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == "/title"


def test_dangling_claim_reference_fails_closed() -> None:
    source = parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    assert isinstance(source, JsonObject)
    outline = source.get("outline")
    assert outline is not None
    changed_outline = _replace_first_outline_claim(outline, "claim_missing")
    changed = JsonObject(
        tuple(
            type(member)(member.key, changed_outline if member.key == "outline" else member.value)
            for member in source.members
        )
    )

    with pytest.raises(JsonDecodeError) as caught:
        decode_offline_run_request(changed)

    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == "/outline/0/claim_ids/0"


def test_dangling_evidence_reference_fails_closed() -> None:
    source = parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    assert isinstance(source, JsonObject)
    claims = source.get("claims")
    assert isinstance(claims, JsonArray)
    first = claims.items[0]
    assert isinstance(first, JsonObject)
    changed_first = JsonObject(
        tuple(
            JsonMember(member.key, JsonArray((JsonString("src_missing"),)))
            if member.key == "evidence_ids"
            else member
            for member in first.members
        )
    )
    changed_claims = JsonArray((changed_first, *claims.items[1:]))
    changed = JsonObject(
        tuple(
            JsonMember(member.key, changed_claims if member.key == "claims" else member.value)
            for member in source.members
        )
    )

    with pytest.raises(JsonDecodeError) as caught:
        decode_offline_run_request(changed)

    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == "/claims/0/evidence_ids/0"


def test_content_catalog_registers_six_runtime_entities_one_to_one() -> None:
    expected_names = (
        "topic-candidate",
        "content-opportunity",
        "source-evidence",
        "claim",
        "content-brief",
        "article-draft",
    )
    assert tuple(entry.name for entry in CONTENT_ENTITY_CONTRACTS) == expected_names
    assert len({entry.schema_id for entry in CONTENT_ENTITY_CONTRACTS}) == 6
    assert {entry.version for entry in CONTENT_ENTITY_CONTRACTS} == {"1.0.0"}

    catalog = parse_json_file(ROOT / "contracts/catalog.json")
    assert isinstance(catalog, JsonObject)
    schemas = catalog.get("schemas")
    assert isinstance(schemas, JsonArray)
    registered: list[tuple[str, str, str]] = []
    for value in schemas.items:
        assert isinstance(value, JsonObject)
        name = value.get("name")
        schema_id = value.get("$id")
        version = value.get("version")
        assert isinstance(name, JsonString)
        assert isinstance(schema_id, JsonString)
        assert isinstance(version, JsonString)
        if name.value in expected_names:
            registered.append((name.value, schema_id.value, version.value))
    assert tuple(registered) == tuple(
        (entry.name, entry.schema_id, entry.version) for entry in CONTENT_ENTITY_CONTRACTS
    )


def test_downstream_entity_ids_remain_distinct_brands() -> None:
    brands = (
        QualityReportId,
        ManifestId,
        PackageId,
        PostId,
        MetricsId,
        ExperimentId,
        EvolutionProposalId,
    )
    assert tuple(brand.__name__ for brand in brands) == (
        "QualityReportId",
        "ManifestId",
        "PackageId",
        "PostId",
        "MetricsId",
        "ExperimentId",
        "EvolutionProposalId",
    )
