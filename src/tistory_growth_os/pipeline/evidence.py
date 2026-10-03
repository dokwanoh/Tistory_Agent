from __future__ import annotations

from hashlib import sha256
import re
from typing import Final, Never, NewType

from tistory_growth_os.contracts.json_decode import ContractIssue, JsonDecodeError
from tistory_growth_os.domain.content import OfflineRunRequest, SourceEvidence
from tistory_growth_os.domain.ids import ClaimId, SectionId, SourceId


PIPELINE_VERSION: Final = "0.2.1"
CanonicalInputDigest = NewType("CanonicalInputDigest", str)
_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")


def parse_canonical_input_digest(value: str) -> CanonicalInputDigest:
    if _SHA256_HEX.fullmatch(value) is None:
        raise JsonDecodeError(
            ContractIssue(
                pointer="/input_digest",
                keyword="pattern",
                message="expected lowercase SHA-256 hexadecimal digest",
            )
        )
    return CanonicalInputDigest(value)


def derive_identity(type_tag: str, input_digest: CanonicalInputDigest) -> str:
    material = f"{type_tag}\x00{input_digest}\x00{PIPELINE_VERSION}".encode("ascii")
    return sha256(material).hexdigest()


def build_evidence_pack(
    request: OfflineRunRequest,
    input_digest: CanonicalInputDigest,
) -> tuple[SourceEvidence, ...]:
    _ = input_digest
    validate_request_references(request)
    return tuple(sorted(request.evidence, key=lambda item: item.source_id))


def validate_request_references(request: OfflineRunRequest) -> None:
    claim_positions = _unique_claim_positions(request)
    source_positions = _unique_source_positions(request)
    _unique_section_ids(request)
    _validate_outline_references(request, claim_positions)
    _validate_claim_references(request, source_positions)
    _validate_evidence_references(request, claim_positions)


def _unique_claim_positions(request: OfflineRunRequest) -> dict[ClaimId, int]:
    positions: dict[ClaimId, int] = {}
    for index, claim in enumerate(request.claims):
        if claim.claim_id in positions:
            _issue("/claims", "uniqueItems", "claim_id values must be unique")
        positions[claim.claim_id] = index
    return positions


def _unique_source_positions(request: OfflineRunRequest) -> dict[SourceId, int]:
    positions: dict[SourceId, int] = {}
    for index, evidence in enumerate(request.evidence):
        if evidence.source_id in positions:
            _issue("/source_evidence", "uniqueItems", "source_id values must be unique")
        positions[evidence.source_id] = index
    return positions


def _unique_section_ids(request: OfflineRunRequest) -> None:
    positions: dict[SectionId, int] = {}
    for index, outline in enumerate(request.outline):
        if outline.section_id in positions:
            _issue(f"/outline/{index}/section_id", "uniqueItems", "section_id values must be unique")
        positions[outline.section_id] = index


def _validate_outline_references(
    request: OfflineRunRequest,
    claim_positions: dict[ClaimId, int],
) -> None:
    for outline_index, outline in enumerate(request.outline):
        for claim_index, claim_id in enumerate(outline.claim_ids):
            if claim_id not in claim_positions:
                _issue(
                    f"/outline/{outline_index}/claim_ids/{claim_index}",
                    "reference",
                    "unknown claim_id",
                )


def _validate_claim_references(
    request: OfflineRunRequest,
    source_positions: dict[SourceId, int],
) -> None:
    for claim_index, claim in enumerate(request.claims):
        for source_index, source_id in enumerate(claim.evidence_ids):
            position = source_positions.get(source_id)
            if position is None:
                _issue(
                    f"/claims/{claim_index}/evidence_ids/{source_index}",
                    "reference",
                    "unknown source_id",
                )
            evidence = request.evidence[position]
            if claim.claim_id not in evidence.supports_claim_ids:
                _issue(
                    f"/claims/{claim_index}/evidence_ids/{source_index}",
                    "reference",
                    "source does not support claim_id",
                )


def _validate_evidence_references(
    request: OfflineRunRequest,
    claim_positions: dict[ClaimId, int],
) -> None:
    for evidence_index, evidence in enumerate(request.evidence):
        for claim_index, claim_id in enumerate(evidence.supports_claim_ids):
            position = claim_positions.get(claim_id)
            if position is None:
                _issue(
                    f"/source_evidence/{evidence_index}/supports_claim_ids/{claim_index}",
                    "reference",
                    "unknown claim_id",
                )
            claim = request.claims[position]
            if evidence.source_id not in claim.evidence_ids:
                _issue(
                    f"/source_evidence/{evidence_index}/supports_claim_ids/{claim_index}",
                    "reference",
                    "claim does not reference source_id",
                )


def _issue(pointer: str, keyword: str, message: str) -> Never:
    raise JsonDecodeError(ContractIssue(pointer=pointer, keyword=keyword, message=message))
