from __future__ import annotations

from pathlib import Path

from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.policy.gates import (
    GateCode,
    GateName,
    GateOutcome,
    PolicyBoundary,
    PolicyContext,
    evaluate_policy,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "topic_supported.json"


def _request():
    return decode_offline_run_request(parse_json_file(FIXTURE))


def _copy_catalogs(destination: Path) -> Path:
    contracts = destination / "contracts"
    contracts.mkdir(parents=True)
    for name in ("policy-evidence.json", "owner-decisions.json"):
        source = ROOT / "contracts" / name
        _ = (contracts / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def test_policy_evaluation_passes_the_checked_in_synthetic_offline_fixture() -> None:
    # Given: the checked-in evidence catalogs and a supported synthetic request.
    request = _request()

    # When: deterministic policy evaluation stays at the offline boundary.
    evaluation = evaluate_policy(ROOT, request)

    # Then: every independent policy surface passes in stable order with no remote writes.
    assert tuple(item.gate for item in evaluation.outcomes) == (
        GateName.GOOGLE_SEARCH,
        GateName.NAVER_SEARCH,
        GateName.ADSENSE,
        GateName.TISTORY,
        GateName.KFTC_DISCLOSURE,
        GateName.PRIVACY,
        GateName.TELEMETRY,
    )
    assert {item.outcome for item in evaluation.outcomes} == {GateOutcome.PASS}
    assert evaluation.external_write_count == 0


def test_policy_evaluation_blocks_missing_policy_source_or_checked_date(tmp_path: Path) -> None:
    # Given: the Google policy record lacks its source URL and checked date.
    root = _copy_catalogs(tmp_path)
    path = root / "contracts" / "policy-evidence.json"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '"source_url": "https://developers.google.com/search/docs/essentials/spam-policies",\n      "checked_at": "2026-09-06"',
        '"source_url": "",\n      "checked_at": ""',
        1,
    )
    _ = path.write_text(source, encoding="utf-8")

    # When: the same offline request is evaluated against incomplete policy evidence.
    result = evaluate_policy(root, _request()).for_gate(GateName.GOOGLE_SEARCH)

    # Then: the specific evidence defect fails closed with a stable evidence ID.
    assert result.outcome is GateOutcome.BLOCK
    assert result.code is GateCode.POLICY_EVIDENCE_REQUIRED
    assert result.path == "/claims/CL-003"
    assert result.evidence_claim_ids == ("CL-003",)


def test_policy_evaluation_blocks_malformed_policy_date(tmp_path: Path) -> None:
    root = _copy_catalogs(tmp_path)
    path = root / "contracts" / "policy-evidence.json"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '"source_url": "https://developers.google.com/search/docs/essentials/spam-policies",\n      "checked_at": "2026-09-06"',
        '"source_url": "https://developers.google.com/search/docs/essentials/spam-policies",\n      "checked_at": "not-a-date"',
        1,
    )
    _ = path.write_text(source, encoding="utf-8")

    result = evaluate_policy(root, _request()).for_gate(GateName.GOOGLE_SEARCH)

    assert result.outcome is GateOutcome.BLOCK
    assert result.code is GateCode.POLICY_EVIDENCE_REQUIRED
    assert result.evidence_claim_ids == ("CL-003",)


def test_policy_evaluation_requires_owner_decision_only_for_live_boundary() -> None:
    # Given: the checked-in pending owner decisions and a supported synthetic request.
    request = _request()

    # When: evaluation is asked to cross the future live delivery boundary.
    result = evaluate_policy(
        ROOT,
        request,
        PolicyContext(boundary=PolicyBoundary.LIVE_EXTERNAL),
    ).for_gate(GateName.TISTORY)

    # Then: only the live path is owner-gated, without performing a write.
    assert result.outcome is GateOutcome.OWNER_DECISION_REQUIRED
    assert result.code is GateCode.OWNER_DECISION_REQUIRED
    assert result.owner_decision_ids == ("ODR-001", "ODR-006")


def test_policy_evaluation_blocks_catalogued_prohibited_tistory_ad_format() -> None:
    # Given: the catalogued Tistory policy and a requested anchor advertisement.
    request = _request()

    # When: policy evaluation receives the proposed local ad format descriptor.
    result = evaluate_policy(
        ROOT,
        request,
        PolicyContext(ad_formats=("anchor",)),
    ).for_gate(GateName.TISTORY)

    # Then: the catalogued prohibited format is blocked before a package can exist.
    assert result.outcome is GateOutcome.BLOCK
    assert result.code is GateCode.PROHIBITED_AD_FORMAT
    assert result.path == "/context/ad_formats/0"
    assert result.evidence_claim_ids == ("CL-010",)


def test_policy_evaluation_keeps_order_stable_when_multiple_boundaries_apply() -> None:
    # Given: simultaneous private telemetry and a prohibited local ad descriptor.
    request = _request()
    context = PolicyContext(
        boundary=PolicyBoundary.PRIVATE_TELEMETRY,
        ad_formats=("anchor",),
    )

    # When: the independent gate records are evaluated twice.
    first = evaluate_policy(ROOT, request, context)
    second = evaluate_policy(ROOT, request, context)

    # Then: output ordering and policy codes are byte-for-byte deterministic in memory.
    assert first == second
    assert tuple(item.gate for item in first.outcomes) == tuple(
        item.gate for item in second.outcomes
    )
    assert first.for_gate(GateName.TISTORY).code is GateCode.PROHIBITED_AD_FORMAT
    assert first.for_gate(GateName.TELEMETRY).outcome is GateOutcome.OWNER_DECISION_REQUIRED
