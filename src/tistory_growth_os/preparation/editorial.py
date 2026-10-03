from dataclasses import dataclass
from html import escape
import re
from typing import Final
from urllib.parse import urlsplit

from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, strings, text
from .contracts import Candidate, PreparationError


CATEGORIES: Final = ('IT', '경제', '생활정보', '과학', '블로그 운영', '스포츠')
TOPICS: Final = ('국내여행', '해외여행', '캠핑·등산', '맛집', '카페·디저트', '생활정보', '인테리어',
    '패션·뷰티', '요리', '일상', '연애·결혼', '육아', '해외생활', '군대', '반려동물', 'IT 인터넷',
    '모바일', '과학', 'IT 제품리뷰', '경영·직장', '정치', '사회', '교육', '국제', '경제', '책',
    '창작', 'TV', '스타', '영화', '음악', '만화·애니', '공연·전시·축제', '취미', '건강',
    '스포츠일반', '축구', '야구', '농구', '배구', '골프', '자동차', '게임', '사진')
P_STYLE: Final = 'margin:0 0 20px !important;'


@dataclass(frozen=True, slots=True)
class Scene:
    brief: str
    alt: str


@dataclass(frozen=True, slots=True)
class Draft:
    title: str
    html: str
    category: str
    home_topic: str
    tags: tuple[str, ...]
    scenes: tuple[Scene, ...]


def paragraph(value: str) -> str:
    return f'<p style="{P_STYLE}">{escape(value)}</p>'


def parse_draft(source: str, candidate: Candidate) -> Draft:
    fields = Fields.parse(parse_json(source), '', ('title', 'lead', 'summary', 'sections',
                         'ending', 'category', 'home_topic', 'tags', 'scenes'))
    category, topic = text(fields, 'category'), text(fields, 'home_topic')
    if category not in CATEGORIES or topic not in TOPICS:
        raise PreparationError('classification_unknown')
    summary = strings(fields, 'summary', True, r'[\s\S]+')
    if not 2 <= len(summary) <= 4:
        raise PreparationError('summary_required')
    html = ['<div style="color:#26231f;font-size:17px;line-height:1.8;overflow-wrap:break-word;">',
            paragraph(text(fields, 'lead')), '{{MEDIA1}}',
            '<div style="background-color:#f6f2eb;border-left:4px solid #625c54;padding:24px;margin:32px 0 !important;">',
            '<p><strong>📌 30초 요약</strong></p>', *(paragraph(line) for line in summary), '</div>']
    sections = array(fields, 'sections', True)
    if not 4 <= len(sections) <= 6:
        raise PreparationError('article_sections_required')
    linked: set[str] = set()
    for index, raw in enumerate(sections):
        section = Fields.parse(raw, '/sections', ('heading', 'paragraphs', 'source_urls'))
        html.append('<h2 style="font-size:24px;line-height:1.45;margin:40px 0 16px !important;">'
                    + escape(text(section, 'heading')) + '</h2>')
        html.extend(paragraph(line) for line in strings(section, 'paragraphs', True, r'[\s\S]+'))
        for url in strings(section, 'source_urls', False, r'https://\S+'):
            if url not in candidate.urls:
                raise PreparationError('unresearched_article_link')
            linked.add(url)
            html.append('<p><a style="color:#075f9c;text-decoration:underline;word-break:keep-all;overflow-wrap:anywhere;" href="'
                        + escape(url, quote=True) + '">' + escape(text(section, 'heading'))
                        + ' · ' + escape(urlsplit(url).netloc.removeprefix('www.')) + ' 원문</a></p>')
        if index in (0, 1, 3):
            html.append('{{MEDIA' + str({0: 2, 1: 3, 3: 4}[index]) + '}}')
    html.extend((paragraph(text(fields, 'ending')), '</div>'))
    scenes: list[Scene] = []
    for raw in array(fields, 'scenes', True):
        scene = Fields.parse(raw, '/scenes', ('brief', 'alt'))
        scenes.append(Scene(text(scene, 'brief'), text(scene, 'alt')))
    if len(scenes) != 4 or len({scene.brief for scene in scenes}) != 4 or not linked:
        raise PreparationError('four_scenes_and_sources_required')
    result = '\n'.join(html)
    prose = re.sub(r'<[^>]+>', '', result)
    if (len(re.findall('[가-힣]', prose)) < 800 or '\ufffd' in source
            or any(word in prose for word in ('Google Trends', '실검', '선정 이유', '상위 5위권'))):
        raise PreparationError('article_text_gate')
    return Draft(text(fields, 'title'), result, category, topic,
                 strings(fields, 'tags', True, r'[^\s#][^\r\n]*'), tuple(scenes))
