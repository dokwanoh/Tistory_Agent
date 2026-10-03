from dataclasses import replace
from pathlib import Path

from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.domain.common import (
    DisclosureBasis,
    OwnerEvidenceStatus,
)
from tistory_growth_os.domain.content import (
    ArticleDraft,
    Disclosure,
    OfflineRunRequest,
)
from tistory_growth_os.domain.ids import SourceId
from tistory_growth_os.domain.publishing import (
    FindingCode,
    FindingSeverity,
    QualityFinding,
    ReportStatus,
)
from tistory_growth_os.domain.content_decode import decode_offline_run_request
from tistory_growth_os.pipeline.brief import build_content_brief
from tistory_growth_os.pipeline.draft import build_article_draft
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.quality import evaluate_quality
from tistory_growth_os.policy.gates import (
    GateCode,
    GateName,
    GateOutcome,
    PolicyEvaluation,
    PolicyGateResult,
)


ROOT = Path(__file__).resolve().parents[1]
DIGEST = parse_canonical_input_digest("2" * 64)


def _request(name: str = "topic_supported.json") -> OfflineRunRequest:
    return decode_offline_run_request(parse_json_file(ROOT / "tests/fixtures" / name))


def _draft(request: OfflineRunRequest) -> ArticleDraft:
    return build_article_draft(request, build_content_brief(request, DIGEST), DIGEST)


def _codes(request: OfflineRunRequest, draft: ArticleDraft) -> tuple[FindingCode, ...]:
    return tuple(item.code for item in evaluate_quality(request, draft).findings)


def test_supported_fixture_passes_with_deterministic_identity_and_full_coverage() -> None:
    # Given: a supported request and its deterministic draft.
    request = _request()
    draft = _draft(request)

    # When: the local quality gate evaluates the same values twice.
    report = evaluate_quality(request, draft)
    repeated = evaluate_quality(request, draft)

    # Then: the report is stable, passing, and completely evidence-backed.
    assert report == repeated
    assert report.status is ReportStatus.PASS
    assert report.findings == ()
    assert report.score == 100
    assert report.claim_evidence_coverage == 1
    assert report.external_write_count == 0


def test_unsupported_factual_claim_blocks_with_exact_code() -> None:
    # Given: a fixture whose factual claim is explicitly unsupported.
    request = _request("topic_unsupported_claim.json")

    # When: the quality gate evaluates its deterministic draft.
    report = evaluate_quality(request, _draft(request))

    # Then: packaging is blocked by the stable evidence code.
    assert report.status is ReportStatus.BLOCKED
    assert tuple(item.code for item in report.findings) == (
        FindingCode.CLAIM_EVIDENCE_REQUIRED,
    )


def test_first_person_claim_requires_verified_owner_evidence_regardless_of_fixture_status() -> None:
    # Given: a first-person claim misleadingly marked as not requiring owner evidence.
    request = _request("topic_unverified_experience.json")
    assert request.claims[0].owner_evidence_status is OwnerEvidenceStatus.NOT_REQUIRED

    # When: the quality gate independently evaluates the claim class.
    report = evaluate_quality(request, _draft(request))

    # Then: owner verification is required and the report cannot pass.
    assert report.status is ReportStatus.BLOCKED
    assert report.findings[0].code is FindingCode.OWNER_EVIDENCE_REQUIRED


def test_dangling_evidence_reference_is_a_contract_failure() -> None:
    # Given: a typed request with a claim referencing an unknown source.
    request = _request()
    broken_claim = replace(request.claims[0], evidence_ids=(SourceId("src_missing"),))
    broken = replace(request, claims=(broken_claim, *request.claims[1:]))

    # When: the gate checks the corrupted request against the existing draft.
    codes = _codes(broken, _draft(request))

    # Then: the cross-reference defect fails closed before evidence scoring.
    assert codes[0] is FindingCode.CONTRACT_INVALID


def test_empty_media_alt_blocks_accessibility() -> None:
    # Given: a local media placeholder with no alternative text.
    request = _request()
    inaccessible = replace(request, media=(replace(request.media[0], alt=""),))

    # When: the quality gate evaluates accessibility.
    codes = _codes(inaccessible, _draft(request))

    # Then: the accessibility finding blocks the approval package.
    assert codes == (FindingCode.ACCESSIBILITY_REQUIRED,)


def test_unsafe_source_url_blocks_policy_evidence() -> None:
    # Given: typed evidence containing a non-HTTP URL scheme.
    request = _request()
    unsafe = replace(request.evidence[0], url="javascript:alert(1)")
    changed = replace(request, evidence=(unsafe, *request.evidence[1:]))

    # When: the gate checks source transport safety.
    codes = _codes(changed, _draft(request))

    # Then: unsafe evidence cannot satisfy the policy gate.
    assert codes == (FindingCode.POLICY_EVIDENCE_REQUIRED,)


def test_affiliate_basis_without_required_disclosure_blocks() -> None:
    # Given: consideration exists while disclosure is marked unnecessary.
    request = _request()
    undisclosed = replace(
        request,
        disclosure=Disclosure(False, "", DisclosureBasis.AFFILIATE),
    )

    # When: the disclosure predicate is evaluated.
    codes = _codes(undisclosed, _draft(request))

    # Then: commercial consideration requires a disclosure.
    assert codes == (FindingCode.DISCLOSURE_REQUIRED,)


def test_policy_findings_are_propagated_and_sorted_by_stable_precedence() -> None:
    # Given: independently evaluated policy findings in reverse priority order.
    request = _request()
    supplied = (
        QualityFinding(
            FindingCode.PROHIBITED_AD_FORMAT,
            FindingSeverity.ERROR,
            "/policy/tistory",
            "prohibited format",
        ),
        QualityFinding(
            FindingCode.POLICY_EVIDENCE_REQUIRED,
            FindingSeverity.ERROR,
            "/policy/google",
            "policy evidence is unknown",
        ),
    )

    # When: quality evaluation incorporates the supplied policy outcomes.
    report = evaluate_quality(request, _draft(request), supplied)

    # Then: both blocks remain independent and use global stable ordering.
    assert tuple(item.code for item in report.findings) == (
        FindingCode.POLICY_EVIDENCE_REQUIRED,
        FindingCode.PROHIBITED_AD_FORMAT,
    )
    assert report.status is ReportStatus.BLOCKED


def test_policy_outcomes_are_converted_without_an_aggregate_score() -> None:
    # Given: typed policy outcomes with unknown evidence and a prohibited format.
    evaluation = PolicyEvaluation((
        PolicyGateResult(
            GateName.GOOGLE_SEARCH,
            GateOutcome.UNKNOWN,
            GateCode.POLICY_EVIDENCE_REQUIRED,
            "/gates/google_search",
            (),
        ),
        PolicyGateResult(
            GateName.TISTORY,
            GateOutcome.BLOCK,
            GateCode.PROHIBITED_AD_FORMAT,
            "/context/ad_formats/0",
            ("CL-010",),
        ),
    ))
    request = _request()

    # When: the quality gate consumes the independent policy evaluation.
    report = evaluate_quality(request, _draft(request), evaluation)

    # Then: outcomes remain distinct blocking findings in stable precedence.
    assert tuple(item.code for item in report.findings) == (
        FindingCode.POLICY_EVIDENCE_REQUIRED,
        FindingCode.PROHIBITED_AD_FORMAT,
    )


def test_outline_mismatch_and_duplicate_low_value_sections_fail_contract_first() -> None:
    # Given: an incoherent draft containing a repeated, low-value section.
    request = _request()
    draft = _draft(request)
    repeated = replace(
        draft.sections[1],
        heading=draft.sections[0].heading,
        body=draft.sections[0].body,
    )
    broken = replace(draft, sections=(draft.sections[0], repeated, *draft.sections[2:]))

    # When: multiple structural defects are evaluated together.
    codes = _codes(request, broken)

    # Then: contract failures have first precedence and stable deduplication.
    assert codes[0] is FindingCode.CONTRACT_INVALID
    assert codes.count(FindingCode.CONTRACT_INVALID) >= 1
