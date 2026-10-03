"""One immutable source body per URL and operation; never model-asserted access."""
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin

from ..contracts.json_decode import parse_json
from ..contracts.json_ast import JsonString, JsonValue
from ..domain.common import Fields, as_object, strings, text
from ..research.intake import public_source_url
from .contracts import PreparationError
from .package import write_immutable
from .source_transport import MAX_BYTES, fetch_public


@dataclass(frozen=True, slots=True)
class SourceDocument:
    url: str
    checked_at: str
    access: str
    body: str
    body_sha256: str
    response_sha256: str
    links: tuple[str, ...]
    published_at: str = ''
    title: str = ''


class SourceHTML:
    """Mutable parser accumulator; exclude non-content and preserve complete text."""
    def __init__(self, url: str) -> None:
        self.url: str = url
        self.parser: HTMLParser = HTMLParser(convert_charrefs=True)
        self.parser.handle_starttag = self.start
        self.parser.handle_endtag = self.end
        self.parser.handle_data = self.data
        self.parts: list[str] = []
        self.links: list[str] = []
        self.skip: list[str] = []
        self.content_depth: int = 0
        self.seen_content: bool = False

    def start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ('script', 'style', 'nav', 'footer', 'header', 'noscript'):
            self.skip.append(tag)
        if tag in ('main', 'article', 'body'):
            self.content_depth += 1
            self.seen_content = True
        if not self.skip and self.content_depth:
            if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3'):
                self.parts.append('\n')
            href = dict(attrs).get('href')
            if tag == 'a' and href:
                target = urljoin(self.url, href)
                if public_source_url(target):
                    self.links.append(target)

    def end(self, tag: str) -> None:
        if self.skip and tag == self.skip[-1]:
            _ = self.skip.pop()
        if tag in ('main', 'article', 'body') and self.content_depth:
            self.content_depth -= 1

    def data(self, data: str) -> None:
        if self.content_depth and not self.skip:
            self.parts.append(data)


def extract_document(url: str, html: bytes, checked_at: datetime) -> SourceDocument:
    parser = SourceHTML(url)
    try:
        parser.parser.feed(html.decode('utf-8'))
        parser.parser.close()
    except UnicodeDecodeError:
        return unavailable(url, checked_at)
    body = re.sub(r'[ \t\r\f\v\u00a0]+', ' ', ''.join(parser.parts)).strip()
    if (len(html) > MAX_BYTES or not parser.seen_content or parser.content_depth
            or not 200 <= len(body) <= 60_000 or '\ufffd' in body
            or any(marker in body.casefold() for marker in ('access denied', 'checking your browser', 'enable javascript'))):
        return unavailable(url, checked_at)
    return SourceDocument(url, checked_at.isoformat(), 'full_text', body,
        sha256(body.encode()).hexdigest(), sha256(html).hexdigest(), tuple(sorted(set(parser.links))))


def unavailable(url: str, checked_at: datetime) -> SourceDocument:
    return SourceDocument(url, checked_at.isoformat(), 'unavailable', '', sha256(b'').hexdigest(), '', ())


def parse_document(raw: str) -> SourceDocument:
    return document_from_value(parse_json(raw))


def document_from_value(raw: JsonValue) -> SourceDocument:
    value = as_object(raw, '')
    keys = ('url', 'checked_at', 'access', 'body', 'body_sha256', 'response_sha256', 'links')
    keys += tuple(key for key in ('published_at', 'title') if value.get(key) is not None)
    fields = Fields.parse(value, '', keys)
    # Empty strings are valid for unavailable records, not affirmative evidence.
    body_value = fields.required('body')
    response_value = fields.required('response_sha256')
    if not isinstance(body_value, JsonString) or not isinstance(response_value, JsonString):
        raise PreparationError('source_snapshot_changed')
    body = body_value.value
    if sha256(body.encode()).hexdigest() != text(fields, 'body_sha256'):
        raise PreparationError('source_snapshot_changed')
    if (not public_source_url(text(fields, 'url')) or text(fields, 'access') not in ('full_text', 'unavailable')
            or (text(fields, 'access') == 'full_text' and (len(body) < 200 or not response_value.value))):
        raise PreparationError('source_snapshot_changed')
    try:
        checked_at = datetime.fromisoformat(text(fields, 'checked_at'))
    except ValueError as error:
        raise PreparationError('source_snapshot_changed') from error
    if checked_at.utcoffset() is None:
        raise PreparationError('source_snapshot_changed')
    published = value.get('published_at') or JsonString('')
    title = value.get('title') or JsonString('')
    if not isinstance(published, JsonString) or not isinstance(title, JsonString):
        raise PreparationError('source_snapshot_changed')
    return SourceDocument(text(fields, 'url'), text(fields, 'checked_at'), text(fields, 'access'),
        body, text(fields, 'body_sha256'), response_value.value,
        strings(fields, 'links', False, r'https://\S+'), published.value, title.value)


@dataclass(frozen=True, slots=True)
class SourceReader:
    directory: Path
    fetch: Callable[[str], bytes] = fetch_public
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def path(self, url: str) -> Path:
        return self.directory / (sha256(url.encode()).hexdigest() + '.json')

    def remember(self, document: SourceDocument) -> None:
        path = self.path(document.url)
        raw = json.dumps(asdict(document), ensure_ascii=False).encode()
        write_immutable(path, raw)
        write_immutable(path.with_suffix('.sha256'), sha256(raw).hexdigest().encode())

    def read(self, url: str) -> SourceDocument:
        if not public_source_url(url):
            raise PreparationError('source_destination_denied')
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(url)
        if path.is_symlink():
            raise PreparationError('source_snapshot_changed')
        if path.exists():
            if path.stat().st_size > 500_000:
                raise PreparationError('source_snapshot_changed')
            digest = path.with_suffix('.sha256')
            raw = path.read_text()
            if digest.is_symlink() or not digest.is_file() or digest.read_text() != sha256(raw.encode()).hexdigest():
                raise PreparationError('source_snapshot_changed')
            document = parse_document(raw)
            if document.url != url:
                raise PreparationError('source_snapshot_changed')
            return document
        checked = self.clock()
        try:
            html = self.fetch(url)
            document = extract_document(url, html, checked)
        except PreparationError as error:
            if error.code != 'source_fetch_unavailable':
                raise
            document = unavailable(url, checked)
        self.remember(document)
        return document
