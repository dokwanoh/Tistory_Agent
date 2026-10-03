from pathlib import Path

import pytest

from tistory_growth_os.delivery.save_intents import SaveIntentJournal
from tistory_growth_os.domain.publishing_errors import PublishingInvariantError
from tests.test_new_reservation_identity import identity


def test_receipt_survives_restart_and_identical_replay(tmp_path: Path) -> None:
    path = tmp_path / 'journal.db'
    journal = SaveIntentJournal(path)
    assert journal.claim('slot', 'a' * 64)
    journal.record_receipt('slot', 'a' * 64, identity())
    journal.record_receipt('slot', 'a' * 64, identity())
    assert SaveIntentJournal(path).receipt('slot', 'a' * 64) == identity()
    assert not journal.claim('slot', 'a' * 64)


@pytest.mark.parametrize('claimed', [False, True])
def test_receipt_requires_matching_claim(tmp_path: Path, claimed: bool) -> None:
    journal = SaveIntentJournal(tmp_path / 'journal.db')
    if claimed:
        assert journal.claim('slot', 'b' * 64)
    with pytest.raises(PublishingInvariantError):
        journal.record_receipt('slot', 'a' * 64, identity())
    assert journal.receipt('slot', 'a' * 64) is None


def test_receipt_cannot_be_replaced(tmp_path: Path) -> None:
    journal = SaveIntentJournal(tmp_path / 'journal.db')
    assert journal.claim('slot', 'a' * 64)
    journal.record_receipt('slot', 'a' * 64, identity())
    with pytest.raises(PublishingInvariantError):
        journal.record_receipt('slot', 'a' * 64, identity('93'))
    assert journal.receipt('slot', 'a' * 64) == identity()
    assert journal.receipt('slot', 'b' * 64) is None
