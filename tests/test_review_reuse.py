from dataclasses import replace
import json
from pathlib import Path

import pytest
from typing_extensions import override

from tests.test_preparation_flow import prepared_run
from tests.test_preparation_pre_media_repair import RepairFixture
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.contracts.json_ast import JsonArray, JsonMember, JsonObject
from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.contracts.json_encode import encode_json
from tistory_growth_os.domain.common import Fields, array, as_object, strings, text


class DeltaFixture(RepairFixture):
    mode: str = 'voice'
    requested: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.requested = []

    @override
    def __call__(self, request: StageRequest) -> StageResponse:
        response = super().__call__(request)
        if request.stage != 'text_review':
            return response
        if request.directory.name != 'pre-media-repair':
            result = response.response.replace('"temporal_consistency": false', '"temporal_consistency": true')
            result = result.replace('"voice": true', '"voice": false')
            result = result.replace('"scope": "temporal_source_binding"', '"scope": "targeted"')
            if self.mode == 'links':
                result = result.replace('"source_links": true', '"source_links": false')
            return replace(response, response=result)
        envelope = Fields(as_object(parse_json(request.prompt.split('\nText subject:\n', 1)[1]), ''), '', ())
        self.requested = list(strings(envelope, 'review_block_ids', False, r'[\w/-]+'))
        result = Fields(as_object(parse_json(response.response), ''), '', ())
        rows = tuple(row for row in array(result, 'blocks', True)
                     if text(Fields(as_object(row, ''), '', ()), 'identity') in self.requested)
        return replace(response, response=encode_json(JsonObject(tuple(JsonMember(member.key,
            JsonArray(rows) if member.key == 'blocks' else member.value) for member in result.value.members))))


@pytest.mark.parametrize('change', ['prose', 'link', 'evidence', 'binding'])
def test_changed_inputs_invalidate_inherited_records(change: str, tmp_path: Path) -> None:
    from tests.preparation_fixture import NOW, evidence_response, research_response, writing_response, text_review_response
    from tistory_growth_os.preparation.contracts import PreparationError, parse_research
    from tistory_growth_os.preparation.evidence import enrich_candidate
    from tistory_growth_os.preparation.text_review import text_subject
    from tistory_growth_os.preparation.review_reuse import ReviewContext, reusable_blocks

    candidate = enrich_candidate(evidence_response(), parse_research(research_response(), NOW).candidates[0], NOW)
    original = text_subject(writing_response(), candidate, NOW)
    raw = text_review_response(StageRequest('text_review', '\nText subject:\n' + json.dumps({
        'subject_sha256': original.digest, 'payload': original.payload}), tmp_path))
    context = ReviewContext(frozenset(), original.payload, raw)
    revised = original
    if change == 'prose':
        revised = text_subject(writing_response().replace('"lead": "', '"lead": "변경 '), candidate, NOW)
    if change == 'link':
        revised = text_subject(writing_response().replace(
            '["https://example.org/official", "https://example.org/guide"]',
            '["https://example.org/guide"]', 1), candidate, NOW)
    if change == 'evidence':
        revised = replace(original, payload=original.payload.replace('idea PDF', 'new requirement'))
    if change == 'binding':
        context = replace(context, previous_review=raw.replace(original.digest, '0' * 64))
        with pytest.raises(PreparationError, match='text_review_subject_mismatch'):
            _ = reusable_blocks(context, original.payload)
        return
    reused = reusable_blocks(context, revised.payload)
    ids = {text(Fields(row, '', ()), 'identity') for row in reused}
    if change == 'prose':
        assert 'lead' not in ids and 'ending' in ids
    if change == 'link':
        assert not any(identity.startswith('sections/0/') for identity in ids)
        assert 'lead' in ids
    if change == 'evidence':
        assert not ids


@pytest.mark.parametrize('mode', ['voice', 'links'])
def test_targeted_repair_reuses_other_claim_records_and_existing_evidence(tmp_path: Path, mode: str) -> None:
    # Given an exact-bound review identifying only the lead as defective.
    run, provider = prepared_run(tmp_path), DeltaFixture()
    provider.mode = mode
    # When the repair model returns only that corrected block's claim assessment.
    package = execute(run, provider)
    # Then all other records are reused, evidence is not requalified, and replay is inert.
    assert package.is_dir()
    assert provider.requested == ['lead']
    assert provider.calls.count('evidence') == 1
    before = list(provider.calls)
    assert execute(run, provider) == package
    assert provider.calls == before


def test_targeted_voice_repair_cannot_rewrite_unlisted_ending(tmp_path: Path) -> None:
    from tistory_growth_os.preparation.contracts import PreparationError
    # Given a writer exceeding the explicit one-block repair scope.
    run, provider = prepared_run(tmp_path), DeltaFixture()
    provider.failure = 'scope_change'
    # When it changes an unrelated ending as well.
    with pytest.raises(PreparationError, match='pre_media_repair_scope_changed'):
        _ = execute(run, provider)
    # Then no media or approval is produced.
    assert 'media' not in provider.calls
