import pytest

from tistory_growth_os.delivery import editor_body_fingerprint as fingerprint
from tistory_growth_os.delivery.native_article_source import NativeAlt


@pytest.mark.parametrize('change', ['equivalent', 'text', 'link', 'style', 'alt', 'order', 'heading', 'duplicate_style'])
def test_fingerprint_accepts_editor_serialization_but_detects_article_changes(change: str) -> None:
    # Given: a reviewed template and the editor's observed serialization conventions.
    media = tuple(NativeAlt(f'{n}.jpg', f'설명 {n}') for n in range(1, 5))
    template = '<div style="color:#26231f;font-size:17px;"><h2>질문</h2><p><strong>강조</strong> 본문 <a href="https://example.test/a">근거</a></p>' + ''.join(f'{{{{MEDIA{n}}}}}' for n in range(1, 5)) + '</div>'
    actual = template.replace('<strong>', '<b>').replace('</strong>', '</b>').replace('color:#26231f;font-size:17px;', 'font-size: 17px; color: #26231f;').replace('<p>', '<p data-ke-size="size16">').replace('<h2>', '<h2 data-ke-size="size26">')
    for n in range(1, 5):
        actual = actual.replace(f'{{{{MEDIA{n}}}}}', f'<figure data-ke-type="image"><img src="https://cdn.test/{n}" data-filename="{n}.jpg" alt="설명 {n}"></figure>')
    variants = {'text': actual.replace('본문', '다른 본문'),
                'link': actual.replace('example.test/a', 'example.test/b'),
                'style': actual.replace('17px', '7px'),
                'alt': actual.replace('설명 1', '다른 설명'),
                'order': actual.replace('1.jpg', 'z.jpg').replace('2.jpg', '1.jpg').replace('z.jpg', '2.jpg'),
                'heading': actual.replace('h2', 'h3'),
                'duplicate_style': actual.replace('font-size: 17px;', 'font-size: 7px;font-size: 17px;')}
    # When: canonicalizing only known nonsemantic editor transformations.
    expected = fingerprint.article_body_digest(template, media)
    observed = fingerprint.article_body_digest(variants.get(change, actual), media)
    # Then: content, position, links and authored presentation remain part of the contract.
    assert expected is not None
    assert (expected == observed) is (change == 'equivalent')


def test_duplicate_css_declarations_cannot_collide_after_sorting() -> None:
    media = tuple(NativeAlt(f'{n}.jpg', f'설명 {n}') for n in range(1, 5))
    source = '<p style="font-size:7px;font-size:17px">글</p>' + ''.join(f'{{{{MEDIA{n}}}}}' for n in range(1, 5))
    assert fingerprint.article_body_digest(source, media) is None
