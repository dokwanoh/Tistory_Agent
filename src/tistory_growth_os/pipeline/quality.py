from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Final
from urllib.parse import urlsplit

from tistory_growth_os.contracts.json_decode import JsonDecodeError
from tistory_growth_os.domain.common import (
    ClaimKind,
    DisclosureBasis,
    OwnerEvidenceStatus,
    SupportState,
)
from tistory_growth_os.domain.content import (
    ArticleDraft,
    Claim,
    OfflineRunRequest,
    SourceEvidence,
)
from tistory_growth_os.domain.ids import QualityReportId, SourceId
from tistory_growth_os.domain.publishing import (
    FindingCode,
    FindingSeverity,
    QualityFinding,
    QualityReport,
    ReportStatus,
)

from ._quality_policy import PolicyInput, normalize_policy_findings
from ._quality_sources import source_rights_findings
from .evidence import validate_request_references


_KST: Final = timezone(timedelta(hours=9))
_POINTS_PER_ERROR: Final = Decimal(10)
_POINTS_PER_WARNING: Final = Decimal(2)


def evaluate_quality(
    request: OfflineRunRequest,
    draft: ArticleDraft,
    policy_findings: PolicyInput = (),
) -> QualityReport:
    findings = list(normalize_policy_findings(policy_findings))
    _check_references(request, findings)
    _check_claims(request, findings)
    _check_structure(request, draft, findings)
    _check_media(request, findings)
    _check_source_urls(request, findings)
    findings.extend(source_rights_findings(request.evidence))
    _check_disclosure(request, findings)
    ordered = tuple(sorted(findings, key=_finding_sort_key))
    error_count = sum(1 for finding in ordered if _is_error(finding))
    warning_count = len(ordered) - error_count
    penalty = _POINTS_PER_ERROR * error_count + _POINTS_PER_WARNING * warning_count
    score = max(Decimal(0), Decimal(100) - penalty)
    status = ReportStatus.BLOCKED if error_count else ReportStatus.PASS
    evaluated_at = max(
        (evidence.checked_at for evidence in request.evidence),
        default=datetime.combine(request.topic.as_of, time.min, _KST),
    )
    identity = sha256(_identity_material(draft, ordered, evaluated_at)).hexdigest()
    return QualityReport(
        report_id=QualityReportId(f"quality_{identity}"),
        draft_id=draft.draft_id,
        status=status,
        score=score,
        findings=ordered,
        claim_evidence_coverage=_claim_coverage(request),
        evaluated_at=evaluated_at,
    )


def _check_references(
    request: OfflineRunRequest,
    findings: list[QualityFinding],
) -> None:
    try:
        validate_request_references(request)
    except JsonDecodeError as error:
        findings.append(_finding(
            FindingCode.CONTRACT_INVALID,
            error.issue.pointer,
            error.issue.message,
        ))


def _check_claims(
    request: OfflineRunRequest,
    findings: list[QualityFinding],
) -> None:
    sources = {evidence.source_id: evidence for evidence in request.evidence}
    for index, claim in enumerate(request.claims):
        match claim.kind:
            case ClaimKind.FACTUAL:
                supported = _factual_claim_is_supported(claim, sources)
                if not supported:
                    findings.append(_finding(
                        FindingCode.CLAIM_EVIDENCE_REQUIRED,
                        f"/claims/{index}",
                        "factual claim requires reciprocal supported evidence",
                    ))
            case ClaimKind.FIRST_PERSON_EXPERIENCE:
                match claim.owner_evidence_status:
                    case OwnerEvidenceStatus.VERIFIED:
                        pass
                    case OwnerEvidenceStatus.NOT_REQUIRED | OwnerEvidenceStatus.REQUIRED:
                        findings.append(_finding(
                            FindingCode.OWNER_EVIDENCE_REQUIRED,
                            f"/claims/{index}/owner_evidence_status",
                            "first-person claim requires verified owner evidence",
                        ))
            case ClaimKind.DISCLOSURE | ClaimKind.OPINION:
                pass


def _factual_claim_is_supported(
    claim: Claim,
    sources: dict[SourceId, SourceEvidence],
) -> bool:
    match claim.support_state:
        case SupportState.SUPPORTED:
            state_supported = True
        case SupportState.UNSUPPORTED | SupportState.OWNER_VERIFICATION_REQUIRED | SupportState.DISPUTED:
            state_supported = False
    if not state_supported or not claim.evidence_ids:
        return False
    return all(
        source_id in sources and claim.claim_id in sources[source_id].supports_claim_ids
        for source_id in claim.evidence_ids
    )


def _check_structure(
    request: OfflineRunRequest,
    draft: ArticleDraft,
    findings: list[QualityFinding],
) -> None:
    if not draft.title.strip() or not draft.summary.strip() or not draft.sections:
        findings.append(_finding(
            FindingCode.CONTRACT_INVALID,
            "/article_draft",
            "draft title, summary, and sections must be populated",
        ))
    if len(draft.sections) != len(request.outline):
        findings.append(_finding(
            FindingCode.CONTRACT_INVALID,
            "/article_draft/sections",
            "draft sections must match the outline count and TOC order",
        ))
    for index, (section, outline) in enumerate(zip(draft.sections, request.outline, strict=False)):
        if (
            not section.heading.strip()
            or section.section_id != outline.section_id
            or section.heading != outline.heading
            or section.claim_ids != outline.claim_ids
        ):
            findings.append(_finding(
                FindingCode.CONTRACT_INVALID,
                f"/article_draft/sections/{index}",
                "section heading, identity, claims, and TOC order must match the outline",
            ))
    fingerprints = tuple(
        (" ".join(section.heading.split()).casefold(), " ".join(section.body.split()).casefold())
        for section in draft.sections
    )
    if len(fingerprints) != len(set(fingerprints)):
        findings.append(_finding(
            FindingCode.CONTRACT_INVALID,
            "/article_draft/sections",
            "duplicate low-value sections require merge or differentiation",
        ))


def _check_media(
    request: OfflineRunRequest,
    findings: list[QualityFinding],
) -> None:
    for index, media in enumerate(request.media):
        if not media.alt.strip():
            findings.append(_finding(
                FindingCode.ACCESSIBILITY_REQUIRED,
                f"/media/{index}/alt",
                "media requires non-empty alternative text",
            ))


def _check_source_urls(
    request: OfflineRunRequest,
    findings: list[QualityFinding],
) -> None:
    for index, evidence in enumerate(request.evidence):
        parsed = urlsplit(evidence.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            findings.append(_finding(
                FindingCode.POLICY_EVIDENCE_REQUIRED,
                f"/source_evidence/{index}/url",
                "source evidence URL must use safe HTTP(S)",
            ))


def _check_disclosure(
    request: OfflineRunRequest,
    findings: list[QualityFinding],
) -> None:
    disclosure = request.disclosure
    match disclosure.basis:
        case DisclosureBasis.NONE:
            required = False
        case DisclosureBasis.ADVERTISING | DisclosureBasis.AFFILIATE | DisclosureBasis.SPONSORSHIP | DisclosureBasis.AI_VIRTUAL_PERSON:
            required = True
    if required and (not disclosure.required or not disclosure.text.strip()):
        findings.append(_finding(
            FindingCode.DISCLOSURE_REQUIRED,
            "/disclosure",
            "consideration or virtual-person basis requires an explicit disclosure",
        ))


def _claim_coverage(request: OfflineRunRequest) -> Decimal:
    factual = tuple(claim for claim in request.claims if claim.kind is ClaimKind.FACTUAL)
    if not factual:
        return Decimal(1)
    sources = {evidence.source_id: evidence for evidence in request.evidence}
    supported = sum(1 for claim in factual if _factual_claim_is_supported(claim, sources))
    return Decimal(supported) / Decimal(len(factual))


def _finding(code: FindingCode, path: str, message: str) -> QualityFinding:
    return QualityFinding(code, FindingSeverity.ERROR, path, message)


def _is_error(finding: QualityFinding) -> bool:
    match finding.severity:
        case FindingSeverity.ERROR:
            return True
        case FindingSeverity.WARNING:
            return False


def _finding_sort_key(finding: QualityFinding) -> tuple[int, str, str]:
    match finding.code:
        case FindingCode.CONTRACT_INVALID:
            precedence = 0
        case FindingCode.OWNER_EVIDENCE_REQUIRED:
            precedence = 1
        case FindingCode.CLAIM_EVIDENCE_REQUIRED:
            precedence = 2
        case FindingCode.POLICY_EVIDENCE_REQUIRED:
            precedence = 3
        case FindingCode.DISCLOSURE_REQUIRED:
            precedence = 4
        case FindingCode.PROHIBITED_AD_FORMAT:
            precedence = 5
        case FindingCode.ACCESSIBILITY_REQUIRED:
            precedence = 6
    return (precedence, finding.path, finding.message)


def _identity_material(
    draft: ArticleDraft,
    findings: tuple[QualityFinding, ...],
    evaluated_at: datetime,
) -> bytes:
    serialized = "\n".join(
        f"{finding.code.value}\0{finding.severity.value}\0{finding.path}\0{finding.message}"
        for finding in findings
    )
    return f"{draft.draft_id}\0{evaluated_at.isoformat()}\0{serialized}".encode("utf-8")
