from pathlib import Path
import socket
import subprocess

import pytest

from tistory_growth_os.audit.source import audit_source
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.source_transport import fetch_public


def test_read_only_dns_exception_does_not_allow_network_in_domain(tmp_path: Path) -> None:
    source = tmp_path / 'src/tistory_growth_os/domain/probe.py'
    source.parent.mkdir(parents=True)
    _ = source.write_text('import socket\n')
    report = audit_source(tmp_path)
    assert report.boundary.external_adapters == ('src/tistory_growth_os/domain/probe.py',)


def test_private_dns_address_stops_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(_host: str, _port: int, *, type: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert type == socket.SOCK_STREAM
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]

    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    with pytest.raises(PreparationError, match='source_destination_denied'):
        _ = fetch_public('https://example.org/guide')


def test_public_read_pins_dns_and_never_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(_host: str, _port: int, *, type: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert type == socket.SOCK_STREAM
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]

    def run(argv: list[str], *, capture_output: bool, check: bool, timeout: int) -> subprocess.CompletedProcess[bytes]:
        assert capture_output and not check and timeout == 25
        assert 'example.org:443:93.184.216.34' in argv
        assert '--noproxy' in argv and '--disable' in argv
        assert not {'--location', '-L', '--data', '--cookie', '--insecure'} & set(argv)
        return subprocess.CompletedProcess(argv, 0, b'body\n200', b'')

    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(subprocess, 'run', run)
    assert fetch_public('https://example.org/guide') == b'body'
