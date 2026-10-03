from tistory_growth_os.preparation import v2_prompts


def test_discovery_requires_search_before_final_json() -> None:
    instruction = v2_prompts.DISCOVERY
    assert 'Invoke the web search tool BEFORE returning candidates' in instruction
    assert 'RSS/history are leads, not a substitute for this tool call' in instruction
    assert 'JSON-only applies to your FINAL response' in instruction
