from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from tests.review_support import synthetic_review, write_review
from tistory_growth_os.artifacts import package_review as gate
from tistory_growth_os.artifacts.review_contract import ReviewDigest, ReviewSubject
from tistory_growth_os.contracts.json_ast import JsonMember, JsonObject, JsonString


NOW: Final = datetime.fromisoformat("2026-09-07T07:00:00+00:00")
SUBJECT: Final = ReviewSubject(ReviewDigest("a" * 64), NOW - timedelta(hours=1))


@pytest.mark.parametrize("case", [
    ("decision", "approved", "REVIEW_APPROVED"),
    ("decision", "hold", "REVIEW_HELD"),
    ("decision", "rejected", "REVIEW_REJECTED"),
    ("decision", "magic", "REVIEW_INVALID"),
    ("subject_sha256", "b" * 64, "REVIEW_MISMATCH"),
    ("reviewed_at", "2026-09-07T07:01:00Z", "REVIEW_NOT_YET_VALID"),
    ("reviewed_at", "2026-09-07T05:00:00Z", "REVIEW_EVIDENCE_NEWER"),
    ("reviewed_at", "2026-09-07T06:59:00", "REVIEW_INVALID"),
    ("valid_until", "2026-09-07T07:00:00Z", "REVIEW_EXPIRED"),
    ("valid_until", "2026-09-07T07:00:01Z", "REVIEW_APPROVED"),
    ("valid_until", "2026-09-07T06:59:59Z", "REVIEW_EXPIRED"),
    ("evidence_valid_until", "2026-09-07T07:00:00Z", "REVIEW_EXPIRED"),
    ("policy_valid_until", "2026-09-07T07:00:00Z", "REVIEW_EXPIRED"),
    ("valid_until", "2026-09-07T16:00:00+09:00", "REVIEW_EXPIRED"),
    ("valid_until", "2026-09-07T06:00:00Z", "REVIEW_INVALID"),
    ("scope", "external_publish", "REVIEW_INVALID"),
    ("reviewer_kind", "author", "REVIEW_INVALID"),
])
def test_review_contract_and_exclusive_time_boundary(
    tmp_path: Path, case: tuple[str, str, str],
) -> None:
    # Given: one deliberate change to a structurally complete synthetic review.
    original = synthetic_review(SUBJECT.digest, NOW)
    field, value, expected = case
    changed = JsonObject(tuple(JsonMember(item.key, JsonString(value))
                               if item.key == field else item for item in original.members))
    _ = write_review(tmp_path, SUBJECT.digest, changed)
    # When: the supplied operational clock evaluates that exact subject.
    result = gate.check_review(tmp_path, SUBJECT, NOW)
    # Then: invalid, stale, held or mismatched records never imply approval.
    assert result.code.value == expected


def test_missing_review_remains_required(tmp_path: Path) -> None:
    # Given: no receipt exists for the requested artifact hash.
    subject = SUBJECT
    # When: the review gate resolves the subject.
    result = gate.check_review(tmp_path, subject, NOW)
    # Then: absence is a blocking state rather than implicit consent.
    assert result.code.value == "REVIEW_REQUIRED"


def test_unknown_review_fields_are_invalid(tmp_path: Path) -> None:
    # Given: a review with an extra field cannot bypass the strict boundary.
    value = synthetic_review(SUBJECT.digest, NOW)
    changed = JsonObject((*value.members, JsonMember("bypass", JsonString("true"))))
    _ = write_review(tmp_path, SUBJECT.digest, changed)
    # When: the record is decoded and evaluated.
    result = gate.check_review(tmp_path, SUBJECT, NOW)
    # Then: unrecognized controls are rejected.
    assert result.code.value == "REVIEW_INVALID"
