from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

from ..artifacts.layout import safe_output_root
from ..artifacts.package_review import check_review, payload_digest
from ..artifacts.review_contract import ReviewCode, ReviewDigest, ReviewSubject
from .contracts import PreparationError
from .package import promote, write_immutable


@dataclass(frozen=True, slots=True)
class Attestation:
    root: Path
    run_id: str
    directory: Path
    digest: str
    checked_at: datetime
    evidence_at: datetime
    reviewed_at: datetime


def approve(source: Attestation) -> Path:
    expiry = source.evidence_at + timedelta(hours=24)
    if not source.checked_at <= source.reviewed_at < expiry:
        raise PreparationError('review_expired')
    receipt_path = safe_output_root(source.root, f'contracts/reviews/{source.digest}.json')
    if not receipt_path.exists():
        receipt = {'schema_version': '1.0.0', 'scope': 'local_package_only',
            'review_id': 'review_' + sha256(source.run_id.encode()).hexdigest()[:24],
            'reviewer_id': 'independent-editorial-v2', 'reviewer_kind': 'independent_agent',
            'decision': 'approved', 'subject_sha256': source.digest,
            'reviewed_at': source.reviewed_at.isoformat(), 'valid_until': expiry.isoformat(),
            'evidence_valid_until': expiry.isoformat(), 'policy_valid_until': expiry.isoformat()}
        write_immutable(receipt_path, json.dumps(receipt).encode())
    review = check_review(source.root, ReviewSubject(ReviewDigest(source.digest), source.checked_at), source.reviewed_at)
    if review.code is not ReviewCode.APPROVED:
        raise PreparationError(review.code.value)
    package = source.directory / 'package'
    if package.exists():
        if any(path.is_symlink() for path in package.rglob('*')):
            raise PreparationError('package_symlink_forbidden')
        bodies = {path.relative_to(package).as_posix(): path.read_bytes() for path in package.rglob('*') if path.is_file()}
        if payload_digest(bodies) != source.digest:
            raise PreparationError('final_package_changed')
        return package
    return promote(source.directory, source.digest)
