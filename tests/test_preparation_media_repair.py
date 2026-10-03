from dataclasses import replace
from pathlib import Path

import pytest
from typing_extensions import override

from tests.preparation_fixture import FixtureProvider
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute


class MediaRepairFixture(FixtureProvider):
    defect: str = 'images'
    persistent: bool = False

    @override
    def __call__(self, request: StageRequest) -> StageResponse:
        response = super().__call__(request)
        response = replace(response, session_id=str(request.directory) + '-' + request.stage)
        repairing = 'media-repair' in request.directory.parts
        if repairing and self.defect == 'self_review' and request.stage == 'review':
            return replace(response, session_id=str(request.directory.parent) + '-review')
        if self.persistent or not repairing:
            if request.stage == 'media' and self.defect == 'credit':
                return replace(response, response=response.response.replace('Fixture organization', ''))
            if request.stage == 'media' and self.defect == 'jpeg':
                _ = (request.directory / 'media/01.jpg').write_bytes(b'broken' * 200)
            if request.stage == 'review' and self.defect not in ('credit', 'jpeg'):
                check = 'images' if self.defect in ('self_review', 'wrong_digest') else self.defect
                rejected = response.response.replace('"approved": true', '"approved": false')
                rejected = rejected.replace('"' + check + '": true', '"' + check + '": false')
                rejected = rejected.replace('"issues": []', '"issues": ["Replace unsuitable media"]')
                if self.defect == 'wrong_digest':
                    rejected = rejected.replace('"subject_sha256": "', '"subject_sha256": "wrong')
                return replace(response, response=rejected)
        return response


@pytest.mark.parametrize('defect', ['credit', 'jpeg', 'images', 'diversity', 'rights'])
def test_media_defect_is_replaced_before_fresh_package_review(tmp_path: Path, defect: str) -> None:
    # Given recorded media that fails a file, attribution or independent quality check.
    run, provider = prepared_run(tmp_path), MediaRepairFixture()
    provider.defect = defect
    # When the normal preparation command executes its bounded replacement path.
    package = execute(run, provider)
    # Then only the independently reviewed replacement becomes the approval package.
    assert package == run.directory / 'media-repair/package'
    assert (run.directory / 'media.json').is_file()
    assert (package.parent / 'review.receipt.json').is_file()
    assert provider.calls.count('media') == 2
    assert provider.calls.count('writing') == 1
    assert not (run.directory / 'package').exists()


def test_media_repair_replay_does_not_generate_again(tmp_path: Path) -> None:
    # Given a completed replacement package and its immutable receipts.
    run, provider = prepared_run(tmp_path), MediaRepairFixture()
    first = execute(run, provider)
    calls = list(provider.calls)
    # When the same identity is replayed.
    replay = execute(run, provider)
    # Then all provider work and the final package identity are reused.
    assert replay == first
    assert provider.calls == calls


@pytest.mark.parametrize('defect', ['images', 'rights', 'credit'])
def test_persistent_media_rejection_retains_work_without_approval(tmp_path: Path, defect: str) -> None:
    # Given an image defect that is still present after replacement.
    run, provider = prepared_run(tmp_path), MediaRepairFixture()
    provider.persistent = True
    provider.defect = defect
    # When the correction budget is consumed.
    with pytest.raises(PreparationError, match='media_enrichment_exhausted'):
        _ = execute(run, provider)
    # Then no third production pass or approval is possible.
    assert provider.calls.count('media') == 2
    assert not list(run.directory.rglob('package'))


@pytest.mark.parametrize(('defect', 'reason'), [
    ('self_review', 'independent_review_session_required'),
    ('wrong_digest', 'independent_review_held'),
    ('policy', 'independent_review_held'),
])
def test_media_repair_preserves_integrity_and_nonmedia_boundaries(tmp_path: Path, defect: str, reason: str) -> None:
    # Given a review with an integrity or unrelated policy failure.
    run, provider = prepared_run(tmp_path), MediaRepairFixture()
    provider.defect = defect
    # When preparation attempts to finish.
    with pytest.raises(PreparationError, match=reason):
        _ = execute(run, provider)
    # Then media replacement cannot turn it into approval.
    assert not list(run.directory.rglob('package'))
    assert provider.calls.count('media') == (2 if defect == 'self_review' else 1)


def test_media_correction_then_text_correction_keep_both_reviews(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), MediaRepairFixture()

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'review' and request.directory.name == 'media-repair':
            return replace(response, response=response.response.replace('"approved": true', '"approved": false')
                .replace('"voice": true', '"voice": false')
                .replace('"issues": []', '"issues": ["Correct awkward wording"]'))
        return response

    package = execute(run, provider)
    assert package == run.directory / 'media-repair/text-repair/package'
    assert (run.directory / 'media-repair/review.receipt.json').is_file()
    assert (package.parent / 'text_review.receipt.json').is_file()
