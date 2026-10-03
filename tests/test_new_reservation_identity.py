from dataclasses import replace
from datetime import timedelta

import pytest

from tistory_growth_os.delivery.new_reservation_identity import (
    NewReservationIntent, SavedIdentity, bind_new_reservation,
)
from tistory_growth_os.delivery.reservation_readback import (
    ReservationObservation, SavedVisibility, verify_reservation,
)
from tistory_growth_os.domain.ids import PostId
from tistory_growth_os.domain.publishing_errors import PublishingInvariantError
from tistory_growth_os.domain.publishing_future import VerificationStatus
from tests.test_reservation_execution import attempt


def intent() -> NewReservationIntent:
    existing = attempt()
    return NewReservationIntent(existing.target.scheduled_at, existing.target.content,
                                existing.package_digest)


def identity(post_id: str = "92") -> SavedIdentity:
    return SavedIdentity(PostId(post_id), f"https://example.tistory.com/{post_id}")


def test_new_intent_needs_no_fabricated_post_id() -> None:
    request = intent()
    assert request.content == attempt().target.content
    target = bind_new_reservation(request, identity(), frozenset({PostId("91")}))
    assert target.post_id == "92"
    assert target.content == request.content
    assert target.scheduled_at == request.scheduled_at


def test_preexisting_identity_cannot_bind() -> None:
    with pytest.raises(PublishingInvariantError, match="IDENTITY_PREEXISTING"):
        _ = bind_new_reservation(intent(), identity("91"), frozenset({PostId("91")}))


@pytest.mark.parametrize("post_id,url", [
    ("", "https://example.tistory.com/92"),
    ("fixture", "https://example.tistory.com/92"),
    ("092", "https://example.tistory.com/92"),
    ("92", "https://example.tistory.com/91"),
    ("92", "https://example.tistory.com/manage/newpost/92"),
    ("92", "https://example.com/92"),
    ("92", "https://example.tistory.com/92?token=secret"),
])
def test_malformed_or_conflicting_identity_rejected(post_id: str, url: str) -> None:
    with pytest.raises(PublishingInvariantError):
        _ = SavedIdentity(PostId(post_id), url)


def test_missing_inventory_is_not_proof_of_new_identity() -> None:
    with pytest.raises(PublishingInvariantError, match="INVENTORY_REQUIRED"):
        _ = bind_new_reservation(intent(), identity(), None)


def test_binding_does_not_replace_independent_content_readback() -> None:
    request = intent()
    target = bind_new_reservation(request, identity(), frozenset({PostId("91")}))
    now = request.scheduled_at - timedelta(minutes=10)
    wrong = replace(target, content=replace(target.content, title="다른 글"))
    check = verify_reservation(target, ReservationObservation(wrong, SavedVisibility.SCHEDULED, now), now)
    assert check.status is VerificationStatus.MISMATCH
    assert check.mismatches == ("title",)
    assert verify_reservation(target, None, now).status is VerificationStatus.UNKNOWN


@pytest.mark.parametrize("change", ["digest", "slot"])
def test_intent_preserves_contract_guards(change: str) -> None:
    with pytest.raises(PublishingInvariantError):
        if change == "digest":
            _ = replace(intent(), package_digest="invalid")
        else:
            _ = replace(intent(), scheduled_at=intent().scheduled_at + timedelta(minutes=1))
