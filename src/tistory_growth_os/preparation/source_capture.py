from collections.abc import Callable
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Final
from xml.etree import ElementTree

from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, as_object, text
from .contracts import PreparationError
from .package import write_immutable
from .source_transport import fetch_public


FEED_URL: Final = 'https://mediahub.seoul.go.kr/news/rss/'
MAX_BYTES: Final = 2_000_000
VOID_TAGS: Final = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img',
                            'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'))


class ArticleBody:
    def __init__(self) -> None:
        self.parser: HTMLParser = HTMLParser(convert_charrefs=True)
        self.parser.handle_starttag = self.handle_starttag
        self.parser.handle_endtag = self.handle_endtag
        self.parser.handle_startendtag = self.handle_startendtag
        self.parser.handle_data = self.handle_data
        self.depth: int = 0
        self.skip: int = 0
        self.parts: list[str] = []
        self.links: list[str] = []
        self.complete: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self.depth and 'news_detail_cont' in (attributes.get('class') or '').split():
            self.depth = 1
            return
        if self.depth:
            if tag not in VOID_TAGS:
                self.depth += 1
            if tag in ('script', 'style'):
                self.skip += 1
            if tag == 'a' and (attributes.get('href') or '').startswith('https://'):
                self.links.append(attributes['href'] or '')
            if tag in ('br', 'p', 'div', 'h2', 'li'):
                self.parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if self.depth and tag not in VOID_TAGS:
            self.depth -= 1
            if tag in ('script', 'style') and self.skip:
                self.skip -= 1
            if not self.depth:
                self.complete = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.depth and not self.skip:
            self.parts.append(data)


def fetch_official(url: str) -> bytes:
    if url != FEED_URL and re.fullmatch(r'https://mediahub\.seoul\.go\.kr/archives/[0-9]+', url) is None:
        raise PreparationError('source_destination_denied')
    try:
        return fetch_public(url)
    except PreparationError as error:
        if error.code != 'source_fetch_unavailable':
            raise
        raise PreparationError('official_body_fetch_failed') from error


def capture_sources(directory: Path, now: datetime,
                    fetch: Callable[[str], bytes] = fetch_official) -> str:
    pool = directory / 'source-pool.json'
    if pool.exists():
        source = pool.read_text()
        fields = Fields(as_object(parse_json(source), ''), '', ())
        for raw in array(fields, 'documents', True):
            entry = Fields(as_object(raw, ''), '', ())
            if sha256(text(entry, 'body').encode()).hexdigest() != text(entry, 'body_sha256'):
                raise PreparationError('source_snapshot_changed')
        return source
    if (directory / 'source-capture.attempt').exists():
        raise PreparationError('source_capture_incomplete')
    write_immutable(directory / 'source-capture.attempt', now.isoformat().encode())
    feed = fetch(FEED_URL)
    write_immutable(directory / 'official-feed.xml', feed)
    if len(feed) > MAX_BYTES or b'<!DOCTYPE' in feed.upper() or b'<!ENTITY' in feed.upper():
        raise PreparationError('official_feed_invalid')
    try:
        items = ElementTree.fromstring(feed).findall('./channel/item')
    except ElementTree.ParseError as error:
        raise PreparationError('official_feed_invalid') from error
    documents: list[dict[str, str | list[str]]] = []
    rejected: list[dict[str, str]] = []
    attempted: set[str] = set()
    for item in items:
        url = item.findtext('link', '')
        if re.fullmatch(r'https://mediahub\.seoul\.go\.kr/archives/[0-9]+', url) is None or url in attempted:
            continue
        try:
            published = parsedate_to_datetime(item.findtext('pubDate', ''))
        except (TypeError, ValueError):
            continue
        if published.utcoffset() is None or not timedelta(0) <= now - published < timedelta(hours=24):
            continue
        if len(attempted) == 8:
            break
        attempted.add(url)
        try:
            html = fetch(url)
        except PreparationError as error:
            if error.code != 'official_body_fetch_failed':
                raise
            rejected.append({'url': url, 'reason': error.code})
            continue
        parser = ArticleBody()
        parser.parser.feed(html.decode('utf-8'))
        body = re.sub(r'[ \t\r\f\v\u00a0]+', ' ', ''.join(parser.parts)).strip()
        if not parser.complete or not 400 <= len(body) <= 25_000 or '\ufffd' in body:
            rejected.append({'url': url, 'reason': 'official_article_body_missing'})
            continue
        documents.append({'url': url, 'title': item.findtext('title', ''),
            'published_at': published.isoformat(), 'checked_at': now.isoformat(),
            'body': body, 'body_sha256': sha256(body.encode()).hexdigest(),
            'response_sha256': sha256(html).hexdigest(), 'links': sorted(set(parser.links))})
    write_immutable(directory / 'source-capture-result.json', json.dumps({
        'readable': len(documents), 'attempted': len(attempted), 'rejected': rejected}).encode())
    if not documents:
        raise PreparationError('readable_source_pool_empty')
    source = json.dumps({'feed_url': FEED_URL, 'checked_at': now.isoformat(),
                         'documents': documents}, ensure_ascii=False)
    write_immutable(pool, source.encode())
    return source
