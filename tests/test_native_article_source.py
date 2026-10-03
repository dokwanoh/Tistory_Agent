import pytest

from tistory_growth_os.delivery import native_article_source as writer


@pytest.mark.parametrize('case', ['valid', 'missing', 'duplicate_filename', 'wrong_filename', 'duplicate_marker'])
def test_composition_preserves_native_identity_and_binds_alt_to_filename(case: str) -> None:
    # Given: four observed native codes and a separately reviewed article template.
    codes = ''.join(f'[##_Image|native-{n}?signed=fixture|CDM|1.3|{{"filename":"{n}.jpg","originWidth":900}}_##]' for n in range(1, 5))
    template = '<p>새 본문</p>' + ''.join(f'{{{{MEDIA{n}}}}}<p>단락 {n}</p>' for n in range(1, 5))
    media = tuple(writer.NativeAlt(f'{n}.jpg', f'설명 {n}') for n in range(1, 5))
    if case == 'missing':
        codes = codes[:codes.rfind('[##_Image')]
    if case == 'duplicate_filename':
        codes = codes.replace('4.jpg', '3.jpg')
    if case == 'wrong_filename':
        codes = codes.replace('4.jpg', 'foreign.jpg')
    if case == 'duplicate_marker':
        template += '{{MEDIA1}}'
    # When: composing without guessing or replacing native upload identities.
    result = writer.compose_native_article(template, codes, media)
    # Then: wrong identities/markers fail closed; the valid output preserves each code.
    if case == 'valid':
        assert result is not None
        assert result.count('[##_Image|') == 4
        assert '{{MEDIA' not in result
        assert '\n_##]' not in result
        for n in range(1, 5):
            assert f'native-{n}?signed=fixture|CDM|1.3|' in result
            assert f'"alt":"설명 {n}"' in result
            assert f'<p>단락 {n}</p>' in result
    else:
        assert result is None
