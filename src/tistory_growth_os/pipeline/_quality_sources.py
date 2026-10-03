from __future__ import annotations

from typing import assert_never

from ..domain.common import LicenseStatus
from ..domain.content import SourceEvidence
from ..domain.publishing import FindingCode, FindingSeverity, QualityFinding


def source_rights_findings(sources: tuple[SourceEvidence, ...]) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    for index, source in enumerate(sources):
        match source.license_status:
            case LicenseStatus.REVIEW_REQUIRED:
                findings.append(QualityFinding(
                    FindingCode.POLICY_EVIDENCE_REQUIRED,
                    FindingSeverity.ERROR,
                    f"/source_evidence/{index}/license_status",
                    "source reuse review is required before approval packaging",
                ))
            case LicenseStatus.LINK_AND_PARAPHRASE | LicenseStatus.QUOTED_WITH_LIMIT | LicenseStatus.OWNER_PROVIDED:
                continue
            case _:
                assert_never(source.license_status)
    return tuple(findings)
