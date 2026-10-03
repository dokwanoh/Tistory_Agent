from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
import re
from typing import Final

from .native_article_source import NativeAlt


BODY_ALGORITHM: Final = 'tistory-article-structure-v1'
_TAGS: Final = frozenset(('div', 'p', 'h2', 'h3', 'strong', 'a', 'br', 'ul', 'ol', 'li', 'em', 'blockquote'))


class _ArticleParser:
    tokens: list[str]
    stack: list[str]
    images: list[NativeAlt]
    invalid: bool
    figure: bool
    figure_images: int

    def __init__(self) -> None:
        self.tokens = []
        self.stack = []
        self.images = []
        self.invalid = False
        self.figure = False
        self.figure_images = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if len(values) != len(attrs):
            self.invalid = True
        if tag == 'figure' and values.get('data-ke-type') == 'image' and not self.figure:
            self.figure = True
            self.figure_images = 0
            return
        if self.figure:
            if tag != 'img':
                self.invalid = True
                return
            filename, alt = values.get('data-filename'), values.get('alt')
            if not filename or not alt:
                self.invalid = True
                return
            self.images.append(NativeAlt(filename, alt))
            self.tokens.append(json.dumps(('image', filename, alt), ensure_ascii=False))
            self.figure_images += 1
            return
        canonical = {'b': 'strong', 'i': 'em'}.get(tag, tag)
        if canonical not in _TAGS:
            self.invalid = True
            return
        kept: list[tuple[str, str | None]] = []
        for key, value in attrs:
            if (key.startswith('data-mce-') or
                    (key == 'data-ke-size' and (tag, value) in (('p', 'size16'), ('h2', 'size26')))):
                continue
            if key == 'style' and value is not None:
                declarations = tuple(sorted(re.sub(r'\s+', ' ', part.strip()).replace(': ', ':')
                                            for part in value.split(';') if part.strip()))
                keys = tuple(part.partition(':')[0].strip().lower() for part in declarations)
                if len(set(keys)) != len(keys) or any(':' not in part for part in declarations):
                    self.invalid = True
                kept.append((key, ';'.join(declarations)))
            else:
                kept.append((key, value))
        self.tokens.append(json.dumps(('start', canonical, sorted(kept)), ensure_ascii=False))
        if canonical != 'br':
            self.stack.append(canonical)

    def handle_endtag(self, tag: str) -> None:
        if self.figure:
            if tag != 'figure' or self.figure_images != 1:
                self.invalid = True
            self.figure = False
            return
        canonical = {'b': 'strong', 'i': 'em'}.get(tag, tag)
        if not self.stack or self.stack.pop() != canonical:
            self.invalid = True
        self.tokens.append(json.dumps(('end', canonical)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in ('img', 'br'):
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if data.strip():
            if self.figure or '\ufffd' in data:
                self.invalid = True
            self.tokens.append(json.dumps(('text', data), ensure_ascii=False))


def article_body_digest(html: str, media: tuple[NativeAlt, ...]) -> str | None:
    if len(media) != 4 or len({item.filename for item in media}) != 4:
        return None
    source = html
    for index, item in enumerate(media, 1):
        marker = f'{{{{MEDIA{index}}}}}'
        if source.count(marker) > 1:
            return None
        source = source.replace(marker, '<figure data-ke-type="image"><img data-filename="'
                                + escape(item.filename, quote=True) + '" alt="'
                                + escape(item.alt, quote=True) + '"></figure>')
    state = _ArticleParser()
    parser = HTMLParser(convert_charrefs=True)
    parser.handle_starttag = state.handle_starttag
    parser.handle_endtag = state.handle_endtag
    parser.handle_startendtag = state.handle_startendtag
    parser.handle_data = state.handle_data
    parser.feed(source)
    parser.close()
    if (state.invalid or state.figure or state.stack or tuple(state.images) != media
            or '{{MEDIA' in source or not state.tokens):
        return None
    return sha256((BODY_ALGORITHM + '\n' + '\n'.join(state.tokens)).encode()).hexdigest()
