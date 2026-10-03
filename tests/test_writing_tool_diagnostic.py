import json
from pathlib import Path
import subprocess

import pytest

from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, codex_provider


def test_rejected_writing_preserves_tool_class_without_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a completed writer that unexpectedly executed a tool.
    events = '\n'.join(json.dumps(item) for item in (
        {'type': 'thread.started', 'thread_id': 'fixture'},
        {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'private-payload'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{}'}},
        {'type': 'turn.completed'}))

    def run(argv: list[str], *, input: str, text: bool, capture_output: bool,
            check: bool, timeout: int) -> subprocess.CompletedProcess[str]:
        _ = input, text, capture_output, check, timeout
        return subprocess.CompletedProcess(argv, 0, events, '')

    monkeypatch.setattr(subprocess, 'run', run)
    request = StageRequest('writing', 'fixture', tmp_path, source_urls=('https://example.com/source',))
    # When the provider enforces its unchanged text-only boundary.
    with pytest.raises(PreparationError, match='text_only_stage_used_tools'):
        _ = codex_provider(request)
    # Then the operator gets safe classes, not raw tool payloads or a success receipt.
    diagnostic = (tmp_path / 'writing.error.json').read_text()
    assert json.loads(diagnostic) == {
        'stage': 'writing', 'reason': 'text_only_stage_used_tools', 'tool_kinds': ['command_execution']}
    assert 'private-payload' not in diagnostic
