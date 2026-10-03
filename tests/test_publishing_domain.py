from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest

from tistory_growth_os.contracts.json_ast import (
    JsonArray,
    JsonBoolean,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
)
from tistory_growth_os.contracts.json_decode import JsonDecodeError
from tistory_growth_os.domain.ids import (
    DraftId,
    IdempotencyKey,
    ManifestId,
    MetricsId,
    OwnerDecisionId,
    PackageId,
    PostId,
)
from tistory_growth_os.domain.publishing import (
    ArtifactDescriptor,
    MetricSource,
    MetricStatus,
    MetricValue,
    PostMetrics,
    PublishManifest,
)
from tistory_growth_os.domain.publishing_catalog import PUBLISHING_ENTITY_CONTRACTS
from tistory_growth_os.domain.publishing_decode import (
    decode_evolution_proposal,
    decode_experiment,
    decode_post_metrics,
    decode_publish_manifest,
)


STAMP = "2026-08-15T02:00:00+09:00"
DAY = "2026-08-15"
HEX = "a" * 64
ROOT = Path(__file__).resolve().parents[1]


def _member(key: str, value: str) -> JsonMember:
    return JsonMember(key, JsonString(value))


def _manifest_json() -> JsonObject:
    artifact = JsonObject((
        _member("name", "article"),
        _member("relative_path", "article.html"),
        _member("media_type", "text/html; charset=utf-8"),
        JsonMember("byte_count", JsonNumber(17)),
        _member("sha256", HEX),
        _member("schema_version", "1.0.0"),
    ))
    return JsonObject((
        _member("schema_version", "1.0.0"),
        _member("manifest_id", "manifest_aaaaaaaaaaaaaaaa"),
        _member("package_id", "package_aaaaaaaaaaaaaaaa"),
        _member("draft_id", "draft_aaaaaaaaaaaaaaaa"),
        _member("idempotency_key", "fixture-v1"),
        _member("body_hash", f"sha256:{HEX}"),
        _member("policy_snapshot_digest", f"sha256:{HEX}"),
        _member("publish_mode", "approval_required"),
        _member("state", "ready_for_approval"),
        JsonMember("external_write_count", JsonNumber(0)),
        JsonMember("artifacts", JsonArray((artifact,))),
        JsonMember("pending_owner_decision_ids", JsonArray((JsonString("ODR-001"),))),
        _member("created_at", STAMP),
    ))


def _metrics_json(status: str, values: JsonArray) -> JsonObject:
    return JsonObject((
        _member("schema_version", "1.0.0"),
        _member("metrics_id", "metrics_fixture"),
        _member("post_id", "post_fixture"),
        _member("source", "naver_search_advisor"),
        _member("surface", "search-performance"),
        _member("status", status),
        _member("interval_start", DAY),
        _member("interval_end", DAY),
        _member("update_basis_date", DAY),
        _member("ingested_at", STAMP),
        JsonMember("retention_days", JsonNumber(90)),
        JsonMember("is_truncated", JsonBoolean(True)),
        JsonMember("values", values),
    ))


def test_manifest_is_approval_only_and_immutable() -> None:
    manifest = decode_publish_manifest(_manifest_json())

    assert manifest.publish_mode == "approval_required"
    assert manifest.state == "ready_for_approval"
    assert manifest.external_write_count == 0
    assert manifest.artifacts[0].relative_path == "article.html"
    with pytest.raises(FrozenInstanceError):
        setattr(manifest, "body_hash", "sha256:changed")


def test_manifest_direct_construction_cannot_override_invariants() -> None:
    descriptor = ArtifactDescriptor(
        "article", "article.html", "text/html", 17, HEX, "1.0.0"
    )
    manifest = PublishManifest(
        ManifestId("manifest_aaaaaaaaaaaaaaaa"),
        PackageId("package_aaaaaaaaaaaaaaaa"),
        DraftId("draft_aaaaaaaaaaaaaaaa"),
        IdempotencyKey("fixture-v1"),
        f"sha256:{HEX}",
        f"sha256:{HEX}",
        (descriptor,),
        (OwnerDecisionId("ODR-001"),),
        decode_publish_manifest(_manifest_json()).created_at,
    )

    assert (manifest.publish_mode, manifest.state, manifest.external_write_count) == (
        "approval_required", "ready_for_approval", 0
    )


def test_unknown_metrics_preserve_absence_instead_of_zero() -> None:
    metrics = decode_post_metrics(_metrics_json("unknown", JsonArray(())))

    assert metrics.status is MetricStatus.UNKNOWN
    assert metrics.values == ()
    assert metrics.source is MetricSource.NAVER_SEARCH_ADVISOR
    assert metrics.retention_days == 90
    assert metrics.is_truncated is True


def test_zero_without_observation_is_rejected() -> None:
    value = JsonObject((
        _member("metric", "clicks"),
        JsonMember("value", JsonNumber(0)),
        _member("unit", "count"),
    ))
    with pytest.raises(JsonDecodeError) as caught:
        decode_post_metrics(_metrics_json("unauthorized", JsonArray((value,))))

    assert caught.value.issue.pointer == "/values"
    assert caught.value.issue.code == "CONTRACT_INVALID"


def test_observed_zero_is_valid_and_domain_constructor_enforces_status() -> None:
    metric = MetricValue("clicks", Decimal(0), "count")
    metrics = PostMetrics(
        MetricsId("metrics_fixture"), PostId("post_fixture"),
        MetricSource.OWNER, "owner-export", MetricStatus.OBSERVED,
        decode_post_metrics(_metrics_json("unknown", JsonArray(()))).interval_start,
        decode_post_metrics(_metrics_json("unknown", JsonArray(()))).interval_end,
        decode_post_metrics(_metrics_json("unknown", JsonArray(()))).update_basis_date,
        decode_post_metrics(_metrics_json("unknown", JsonArray(()))).ingested_at,
        0, False, (metric,),
    )
    assert metrics.values[0].value == 0

    with pytest.raises(ValueError):
        PostMetrics(
            metrics.metrics_id, metrics.post_id, metrics.source, metrics.surface,
            MetricStatus.UNKNOWN, metrics.interval_start, metrics.interval_end,
            metrics.update_basis_date, metrics.ingested_at, 0, False, (metric,),
        )


def test_published_post_has_no_decoder_or_producible_catalog_entry() -> None:
    from tistory_growth_os.domain import publishing_decode

    assert not hasattr(publishing_decode, "decode_published_post")
    published = next(
        entry for entry in PUBLISHING_ENTITY_CONTRACTS
        if entry.name == "published-post"
    )
    assert published.producible is False


def test_publishing_catalog_maps_six_contracts_exactly() -> None:
    assert tuple(entry.name for entry in PUBLISHING_ENTITY_CONTRACTS) == (
        "quality-report", "publish-manifest", "published-post", "post-metrics",
        "experiment", "evolution-proposal",
    )
    assert len({entry.schema_id for entry in PUBLISHING_ENTITY_CONTRACTS}) == 6
    assert {entry.version for entry in PUBLISHING_ENTITY_CONTRACTS} == {"1.0.0"}


def test_decode_rejects_wrong_manifest_field_type_and_unknown_field() -> None:
    source = _manifest_json()
    wrong = JsonObject(tuple(
        JsonMember(item.key, JsonString("zero"))
        if item.key == "external_write_count" else item
        for item in source.members
    ))
    with pytest.raises(JsonDecodeError) as wrong_caught:
        decode_publish_manifest(wrong)
    assert wrong_caught.value.issue.pointer == "/external_write_count"

    extra = JsonObject((*source.members, _member("remote_write", "yes")))
    with pytest.raises(JsonDecodeError) as extra_caught:
        decode_publish_manifest(extra)
    assert extra_caught.value.issue.pointer == "/remote_write"


def test_decode_normalizes_artifact_invariants_to_contract_issues() -> None:
    source = _manifest_json()
    artifacts = source.get("artifacts")
    assert isinstance(artifacts, JsonArray)
    artifact = artifacts.items[0]
    assert isinstance(artifact, JsonObject)
    unsafe = JsonObject(tuple(
        JsonMember(item.key, JsonString("../article.html"))
        if item.key == "relative_path" else item
        for item in artifact.members
    ))
    changed = JsonObject(tuple(
        JsonMember(item.key, JsonArray((unsafe,)))
        if item.key == "artifacts" else item
        for item in source.members
    ))

    with pytest.raises(JsonDecodeError) as caught:
        decode_publish_manifest(changed)

    assert caught.value.issue.pointer == "/artifacts/0/relative_path"


def test_evolution_factory_requires_owner_for_policy_or_schema_change() -> None:
    proposal = JsonObject((
        _member("schema_version", "1.0.0"),
        _member("proposal_id", "evo_fixture"),
        _member("observed_trace_id", "trace-1"),
        _member("bdw_class", "waste"),
        _member("root_cause_hypothesis", "중복 검토"),
        _member("change_target", "policy"),
        _member("expected_effect", "검토 감소"),
        _member("regression_risk", "정책 약화"),
        JsonMember("eval_ids", JsonArray((JsonString("eval-policy"),))),
        JsonMember("acceptance_threshold", JsonNumber(Decimal("0.95"))),
        JsonMember("cost_budget_krw", JsonNumber(1000)),
        JsonMember("latency_budget_seconds", JsonNumber(30)),
        _member("canary_scope", "shadow only"),
        _member("rollback_condition", "any policy regression"),
        _member("decision", "pending"),
        JsonMember("owner_approval_required", JsonBoolean(False)),
        _member("recorded_at", STAMP),
    ))
    with pytest.raises(JsonDecodeError) as caught:
        decode_evolution_proposal(proposal)
    assert caught.value.issue.pointer == "/owner_approval_required"


def test_experiment_threshold_preserves_negative_delta_target() -> None:
    experiment = JsonObject((
        _member("schema_version", "1.0.0"),
        _member("experiment_id", "exp_fixture"),
        JsonMember("post_ids", JsonArray((JsonString("post_fixture"),))),
        _member("hypothesis", "오류율이 낮아진다"),
        _member("controllable_factor", "quality_prompt_version"),
        _member("primary_metric", "error_rate_delta"),
        JsonMember("acceptance_threshold", JsonNumber(Decimal("-0.05"))),
        _member("status", "shadow"),
        _member("started_at", STAMP),
        _member("observation_end", "2026-08-16T02:00:00+09:00"),
        _member("rollback_condition", "오류율이 증가하면 중단"),
    ))

    decoded = decode_experiment(experiment)

    assert decoded.acceptance_threshold == Decimal("-0.05")


def test_owned_source_uses_readable_statements_and_line_width() -> None:
    domain = ROOT / "src/tistory_growth_os/domain"
    paths = tuple(sorted(domain.glob("publishing*.py"))) + tuple(
        sorted(domain.glob("evolution*.py"))
    )
    violations: list[str] = []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if len(line) > 100:
                violations.append(f"{path.name}:{number}:line-too-long")
            if ";" in line:
                violations.append(f"{path.name}:{number}:statement-packing")

    assert violations == []
