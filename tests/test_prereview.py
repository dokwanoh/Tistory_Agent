import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tistory_growth_os.research.prereview import parse_completion
from tistory_growth_os.research.usage import UsageError
from tistory_growth_os.research.prereview_cli import check_response


def test_receipt_when_turn_completes() -> None:
    # Given: provider-shaped events, with reasoning already included in output.
    events = '\n'.join(json.dumps(event) for event in [
        {'type': 'thread.started', 'thread_id': 'fixture-thread'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{}'}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 40,
            'output_tokens': 20, 'reasoning_output_tokens': 10}}])
    # When: decode the actual completion boundary.
    receipt, response = parse_completion(events)
    # Then: output is not double-counted.
    assert (receipt.input_tokens, receipt.cached_input_tokens, receipt.output_tokens, response) == (100, 40, 20, '{}')


@pytest.mark.parametrize('event', [
    {'type': 'turn.failed'}, {'type': 'error'},
    {'type': 'item.started', 'item': {'type': 'command_execution'}},
    {'type': 'turn.completed', 'usage': {'input_tokens': 1, 'cached_input_tokens': 0, 'output_tokens': 1}},
])
def test_receipt_when_incomplete_or_tool_using(event: dict[str, str | dict[str, str | int]]) -> None:
    # Given / When / Then: no valid single text-only completion means no usable receipt.
    with pytest.raises(UsageError):
        _ = parse_completion(json.dumps(event))


@pytest.mark.parametrize('query,verified,eligible', [('invented', False, False),
    ('AI', True, False), ('AI', False, True)])
def test_review_when_model_overclaims(query: str, verified: bool, eligible: bool) -> None:
    # Given / When / Then: model output cannot invent candidates or certify publication.
    response = json.dumps({'publication_eligible': eligible, 'candidates': [{'query': query,
        'reader_question': 'question', 'rationale': 'reason', 'missing_evidence': 'primary source',
        'event_verified': verified}]})
    with pytest.raises(UsageError):
        _ = check_response(response, ('AI',))


def test_cli_when_provider_process_returns_a_review(tmp_path: Path) -> None:
    # Given: an isolated executable provider fixture, never a real account call.
    feed = tmp_path / 'feed.rss'
    _ = feed.write_text('<rss><channel><item><title>AI</title><pubDate>Wed, 02 Jan 2030 11:00:00 +0900</pubDate></item></channel></rss>')
    response = json.dumps({'publication_eligible': False, 'candidates': [{'query': 'AI',
        'reader_question': 'question', 'rationale': 'reason', 'missing_evidence': 'primary source',
        'event_verified': False}]})
    events = '\n'.join(json.dumps(event) for event in [
        {'type': 'thread.started', 'thread_id': 'fixture-thread'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': response}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 20}}])
    binary = tmp_path / 'codex'
    _ = binary.write_text(f'#!{sys.executable}\nimport sys\n_ = sys.stdin.read()\nprint({events!r})\n')
    binary.chmod(0o700)
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ.get('PATH', ''))
    output = tmp_path / 'review.json'
    command = [sys.executable, '-m', 'tistory_growth_os.research.prereview_cli', '--feed', str(feed),
        '--as-of', '2030-01-02T12:00:00+09:00', '--output', str(output), '--execute']
    # When: drive the actual CLI and process boundary.
    result = subprocess.run(command, capture_output=True, text=True, check=False, env=env)
    # Then: metering is recorded but semantic approval is still absent.
    assert result.returncode == 0, result.stderr
    assert '"quality_passed": false' in output.read_text()
    assert '"input_tokens": 100' in output.read_text()


def test_cli_when_attempt_already_exists(tmp_path: Path) -> None:
    # Given: prior attempted execution, even without a final result.
    output = tmp_path / 'review.json'
    _ = output.with_suffix('.attempt.json').write_text('{}')
    # When: replay requests the same output identity.
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.research.prereview_cli',
        '--feed', '/nonexistent', '--as-of', '2030-01-02T12:00:00+09:00', '--output', str(output),
        '--execute'], capture_output=True, text=True, check=False)
    # Then: guard fires before file reads or account calls.
    assert result.returncode == 2 and 'new_run_path_required' in result.stderr
