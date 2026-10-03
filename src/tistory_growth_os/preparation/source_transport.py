"""Bounded public read-only transport, shared by intake and enrichment."""
from ipaddress import ip_address
import socket
import subprocess
from typing import Final
from urllib.parse import urlsplit

from ..research.intake import public_source_url
from .contracts import PreparationError

MAX_BYTES: Final = 2_000_000


def fetch_public(url: str) -> bytes:
    if not public_source_url(url):
        raise PreparationError('source_destination_denied')
    host = urlsplit(url).hostname or ''
    try:
        addresses = sorted({str(entry[4][0]) for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except socket.gaierror as error:
        raise PreparationError('source_fetch_unavailable') from error
    if not addresses or any(not ip_address(address).is_global for address in addresses):
        raise PreparationError('source_destination_denied')
    address = addresses[0]
    pinned = f'[{address}]' if ':' in address else address
    # No redirects, cookies, proxy, curlrc or re-resolution into a private address.
    try:
        result = subprocess.run(['/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error',
            '--noproxy', '*', '--proto', '=https', '--resolve', f'{host}:443:{pinned}',
            '--connect-timeout', '5', '--max-time', '20', '--max-filesize', str(MAX_BYTES),
            '--write-out', '\n%{http_code}', '--url', url], capture_output=True, check=False, timeout=25)
    except subprocess.TimeoutExpired as error:
        raise PreparationError('source_fetch_unavailable') from error
    body, _, status = result.stdout.rpartition(b'\n')
    if result.returncode or status != b'200' or len(body) > MAX_BYTES:
        raise PreparationError('source_fetch_unavailable')
    return body
