import os

import pytest


os.environ['TISTORY_BLOG_HOST'] = 'example.tistory.com'
os.environ['TISTORY_MODEL'] = 'gpt-reserve'
os.environ['TISTORY_ALLOW_MODEL_EXECUTION'] = '1'


@pytest.fixture(autouse=True)
def isolate_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('TISTORY_BLOG_HOST', 'example.tistory.com')
    monkeypatch.setenv('TISTORY_MODEL', 'gpt-reserve')
    monkeypatch.setenv('TISTORY_ALLOW_MODEL_EXECUTION', '1')
