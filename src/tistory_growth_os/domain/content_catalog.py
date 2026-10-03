from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ContentEntityContract:
    name: str
    schema_id: str
    version: str


CONTENT_ENTITY_CONTRACTS: Final[tuple[ContentEntityContract, ...]] = (
    ContentEntityContract(
        name="topic-candidate",
        schema_id="urn:tistory-growth-os:schema:topic-candidate:1.0.0",
        version="1.0.0",
    ),
    ContentEntityContract(
        name="content-opportunity",
        schema_id="urn:tistory-growth-os:schema:content-opportunity:1.0.0",
        version="1.0.0",
    ),
    ContentEntityContract(
        name="source-evidence",
        schema_id="urn:tistory-growth-os:schema:source-evidence:1.0.0",
        version="1.0.0",
    ),
    ContentEntityContract(
        name="claim",
        schema_id="urn:tistory-growth-os:schema:claim:1.0.0",
        version="1.0.0",
    ),
    ContentEntityContract(
        name="content-brief",
        schema_id="urn:tistory-growth-os:schema:content-brief:1.0.0",
        version="1.0.0",
    ),
    ContentEntityContract(
        name="article-draft",
        schema_id="urn:tistory-growth-os:schema:article-draft:1.0.0",
        version="1.0.0",
    ),
)
