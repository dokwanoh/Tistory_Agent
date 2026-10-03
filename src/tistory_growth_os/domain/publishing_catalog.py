from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class PublishingEntityContract:
    name: str
    schema_id: str
    version: str
    producible: bool


PUBLISHING_ENTITY_CONTRACTS: Final[tuple[PublishingEntityContract, ...]] = (
    PublishingEntityContract(
        "quality-report",
        "urn:tistory-growth-os:schema:quality-report:1.0.0",
        "1.0.0",
        True,
    ),
    PublishingEntityContract(
        "publish-manifest",
        "urn:tistory-growth-os:schema:publish-manifest:1.0.0",
        "1.0.0",
        True,
    ),
    PublishingEntityContract(
        "published-post",
        "urn:tistory-growth-os:schema:published-post:1.0.0",
        "1.0.0",
        False,
    ),
    PublishingEntityContract(
        "post-metrics",
        "urn:tistory-growth-os:schema:post-metrics:1.0.0",
        "1.0.0",
        False,
    ),
    PublishingEntityContract(
        "experiment",
        "urn:tistory-growth-os:schema:experiment:1.0.0",
        "1.0.0",
        False,
    ),
    PublishingEntityContract(
        "evolution-proposal",
        "urn:tistory-growth-os:schema:evolution-proposal:1.0.0",
        "1.0.0",
        False,
    ),
)
