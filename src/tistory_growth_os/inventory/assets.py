from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from ipaddress import ip_address
from typing import Final, Literal, final
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


AssetKind = Literal["link", "image", "embed"]
_ATTRIBUTES: Final = {"a": "href", "img": "src", "iframe": "src"}
_KINDS: Final[dict[str, AssetKind]] = {"a": "link", "img": "image", "iframe": "embed"}


@final
class AssetExtractionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PublicAsset:
    kind: AssetKind
    url: str
    host: str
    query_redacted: bool


@dataclass(frozen=True, slots=True)
class PageAssets:
    page_url: str
    assets: tuple[PublicAsset, ...]
    image_count: int
    missing_alt_count: int
    empty_alt_count: int
    omitted_reference_count: int
    source_hint_present: bool


def public_reference(raw: str, page_url: str) -> tuple[str, str, bool] | None:
    if not raw or raw.startswith("#") or any(ord(char) < 32 for char in raw):
        return None
    try:
        parsed = urlsplit(urljoin(page_url, raw))
        host = parsed.hostname or ""
        if (parsed.scheme not in {"http", "https"} or not host or parsed.username
            or parsed.password or parsed.port not in {None, 80, 443}
            or "." not in host or host.endswith((".local", ".internal", ".localhost"))):
            return None
        try:
            _ = ip_address(host)
        except ValueError:
            is_numeric_host = False
        else:
            is_numeric_host = True
        if is_numeric_host:
            return None
        path = quote(parsed.path, safe="/%!$&'()*+,;=:@-._~")
        cleaned = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        return cleaned, host, bool(parsed.query)
    except ValueError:
        return None


@final
class _ArticleParser:
    """Accumulates only asset metadata while inside the article body."""

    def __init__(self, page_url: str) -> None:
        self.page_url: str = page_url
        self.depth: int = 0
        self.body_count: int = 0
        self.assets: list[PublicAsset] = []
        self.image_count: int = 0
        self.missing_alt: int = 0
        self.empty_alt: int = 0
        self.omitted: int = 0
        self.source_hint: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif "contents_style" in (attributes.get("class") or "").split():
                self.depth = 1
                self.body_count += 1
        if not self.depth or tag not in _ATTRIBUTES:
            return
        if tag == "img":
            self.image_count += 1
            if "alt" not in attributes:
                self.missing_alt += 1
            elif not (attributes.get("alt") or "").strip():
                self.empty_alt += 1
        reference = public_reference(attributes.get(_ATTRIBUTES[tag]) or "", self.page_url)
        if reference is None:
            self.omitted += 1
            return
        url, host, redacted = reference
        self.assets.append(PublicAsset(_KINDS[tag], url, host, redacted))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and "출처" in data:
            self.source_hint = True


def extract_page_assets(html: str, page_url: str) -> PageAssets:
    validated = public_reference(page_url, page_url)
    if validated is None or validated[2]:
        raise AssetExtractionError("invalid public page URL")
    parser = _ArticleParser(validated[0])
    reader = HTMLParser(convert_charrefs=True)
    reader.handle_starttag = parser.handle_starttag
    reader.handle_endtag = parser.handle_endtag
    reader.handle_startendtag = parser.handle_startendtag
    reader.handle_data = parser.handle_data
    reader.feed(html)
    reader.close()
    if parser.body_count != 1 or parser.depth:
        raise AssetExtractionError("expected exactly one closed article body")
    return PageAssets(
        validated[0], tuple(parser.assets), parser.image_count,
        parser.missing_alt, parser.empty_alt, parser.omitted, parser.source_hint,
    )
