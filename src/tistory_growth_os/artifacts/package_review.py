from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import assert_never

from ..contracts.json_ast import JsonMember, JsonNumber, JsonObject, JsonString
from ..contracts.json_encode import encode_json_bytes
from ..contracts.json_decode import JsonDecodeError, parse_json_file
from .layout import ArtifactWriteError, safe_output_root
from .review_contract import (
    ReviewCheck, ReviewCode, ReviewDecision, ReviewDigest, ReviewSubject, decode_package_review,
)


def payload_digest(payloads: Mapping[str, bytes]) -> ReviewDigest:
    digest = sha256(b"tistory-package-review-v1\x00")
    for name, body in sorted(payloads.items()):
        name_bytes = name.encode("utf-8")
        digest.update(len(name_bytes).to_bytes(8, "big"))
        digest.update(name_bytes)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return ReviewDigest(digest.hexdigest())


def current_time() -> datetime:
    return datetime.now(timezone.utc)


def enforce_package_review(root: Path, output: Path, subject: ReviewSubject) -> None:
    now = current_time()
    result = check_review(root, subject, now)
    event = JsonObject((
        JsonMember("event", JsonString("package_review_checked")),
        JsonMember("result_code", JsonString(result.code.value)),
        JsonMember("review_id", JsonString(result.review_id)),
        JsonMember("reviewer_kind", JsonString(result.reviewer_kind)),
        JsonMember("subject_sha256", JsonString(subject.digest)),
        JsonMember("evaluated_at", JsonString(now.isoformat())),
        JsonMember("external_write_count", JsonNumber(0)),
    ))
    _ = output.mkdir(parents=True, exist_ok=True)
    audit = safe_output_root(root, (output / "review-audit.jsonl").relative_to(root.resolve()).as_posix())
    with audit.open("ab") as stream:
        _ = stream.write(encode_json_bytes(event))
    if result.code is not ReviewCode.APPROVED:
        raise ArtifactWriteError(result.code.value, "/review", subject.digest)


def check_review(root: Path, subject: ReviewSubject, now: datetime) -> ReviewCheck:
    if now.tzinfo is None or subject.evidence_checked_at.tzinfo is None:
        return ReviewCheck(ReviewCode.INVALID)
    path = safe_output_root(root, f"contracts/reviews/{subject.digest}.json")
    if not path.exists():
        return ReviewCheck(ReviewCode.REQUIRED)
    try:
        record = decode_package_review(parse_json_file(path))
    except (JsonDecodeError, OSError):
        return ReviewCheck(ReviewCode.INVALID)
    if record.subject_sha256 != subject.digest:
        code = ReviewCode.MISMATCH
    elif now < record.reviewed_at:
        code = ReviewCode.NOT_YET_VALID
    elif record.reviewed_at < subject.evidence_checked_at:
        code = ReviewCode.EVIDENCE_NEWER
    elif now >= min(record.valid_until, record.evidence_valid_until, record.policy_valid_until):
        code = ReviewCode.EXPIRED
    else:
        match record.decision:
            case ReviewDecision.APPROVED:
                code = ReviewCode.APPROVED
            case ReviewDecision.HOLD:
                code = ReviewCode.HELD
            case ReviewDecision.REJECTED:
                code = ReviewCode.REJECTED
            case _:
                assert_never(record.decision)
    return ReviewCheck(code, record.review_id, record.reviewer_kind.value)
