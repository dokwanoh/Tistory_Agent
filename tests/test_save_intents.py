from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from sqlite3 import OperationalError

import pytest

from tistory_growth_os.delivery.save_intents import SaveIntentJournal


def test_first_attempt_is_claimed_but_restart_cannot_repeat(tmp_path: Path) -> None:
    path = tmp_path / "delivery.sqlite3"
    assert SaveIntentJournal(path).claim("2026-09-13/1200", "a" * 64)
    assert not SaveIntentJournal(path).claim("2026-09-13/1200", "a" * 64)


def test_changed_package_cannot_reuse_uncertain_slot(tmp_path: Path) -> None:
    journal = SaveIntentJournal(tmp_path / "delivery.sqlite3")
    assert journal.claim("2026-09-13/1200", "a" * 64)
    assert not journal.claim("2026-09-13/1200", "b" * 64)
    assert journal.claim("2026-09-13/1900", "b" * 64)


def test_concurrent_claims_have_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "delivery.sqlite3"
    journal = SaveIntentJournal(path)
    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(lambda _: journal.claim("slot", "a" * 64), range(16)))
    assert sum(outcomes) == 1


@pytest.mark.parametrize("key,digest", [("", "a" * 64), (" slot", "a" * 64), ("slot", "bad"), ("slot", "g" * 64)])
def test_invalid_identity_rejected(tmp_path: Path, key: str, digest: str) -> None:
    journal = SaveIntentJournal(tmp_path / "delivery.sqlite3")
    with pytest.raises(ValueError):
        journal.claim(key, digest)


def test_missing_parent_fails_without_fallback(tmp_path: Path) -> None:
    with pytest.raises(OperationalError, match="unable to open database"):
        SaveIntentJournal(tmp_path / "missing" / "delivery.sqlite3")
