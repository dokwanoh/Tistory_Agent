from pathlib import Path

import pytest

from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse, completion, require_stage_tools
import json


def test_skill_budget_warning_is_not_a_tool_when_turn_completed(tmp_path: Path) -> None:
    # Given the exact CLI warning observed in the read-only reproduction.
    warning = ('Skill descriptions were shortened to fit the skills context budget. Codex can still see every skill, '
               'but some descriptions are shorter. Disable unused skills or plugins to leave more room for the rest.')
    events = '\n'.join(json.dumps(event) for event in (
        {'type': 'thread.started', 'thread_id': 'fixture'},
        {'type': 'item.completed', 'item': {'type': 'error', 'message': warning}},
        {'type': 'item.completed', 'item': {'type': 'web_search'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{}'}},
        {'type': 'turn.completed'},
    ))
    # When a completed stream reaches the stage policy.
    parsed = completion(events, model='gpt-reserve')
    require_stage_tools(StageRequest('discovery', 'fixture', tmp_path), parsed)
    # Then only actual search counts as a tool and the warning remains observable.
    assert parsed.tool_kinds == ('web_search',)
    assert parsed.warnings == ('skill_descriptions_shortened',)
    with pytest.raises(PreparationError, match='provider_completion_required'):
        _ = completion(events.rsplit('\n', 1)[0], model='gpt-reserve')
    with pytest.raises(PreparationError, match='provider_turn_failed'):
        _ = completion(events + '\n{"type":"error","message":"fatal"}', model='gpt-reserve')


def test_other_item_errors_are_not_waived(tmp_path: Path) -> None:
    events = '\n'.join((
        '{"type":"thread.started","thread_id":"fixture"}',
        '{"type":"item.completed","item":{"type":"error","message":"authentication failed"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"{}"}}',
        '{"type":"turn.completed"}',
    ))
    with pytest.raises(PreparationError):
        require_stage_tools(StageRequest('discovery', 'fixture', tmp_path), completion(events))


def test_unexpected_tool_records_kind_without_response_content(tmp_path: Path) -> None:
    request = StageRequest('discovery', 'fixture', tmp_path)
    response = StageResponse('private response must not be logged', 'fixture', ('unknown_tool',))
    with pytest.raises(PreparationError, match='unexpected_provider_tool'):
        require_stage_tools(request, response)
    record = (tmp_path / 'discovery.error.json').read_text()
    assert 'unknown_tool' in record
    assert 'private response' not in record


def test_search_required_but_not_permitted_in_text_stage(tmp_path: Path) -> None:
    with pytest.raises(PreparationError, match='live_research_evidence_required'):
        require_stage_tools(StageRequest('discovery', 'fixture', tmp_path), StageResponse('{}', 'fixture', ()))
    with pytest.raises(PreparationError, match='text_only_stage_used_tools'):
        require_stage_tools(StageRequest('writing', 'fixture', tmp_path),
                            StageResponse('{}', 'fixture', ('web_search',)))


def test_observed_search_is_accepted(tmp_path: Path) -> None:
    require_stage_tools(StageRequest('discovery', 'fixture', tmp_path),
                        StageResponse('{}', 'fixture', ('web_search',)))
    assert not (tmp_path / 'discovery.error.json').exists()
