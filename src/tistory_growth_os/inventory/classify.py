from __future__ import annotations

from typing import Final
from datetime import date
import re

from .models import (
    ActionCandidate,
    ClassifiedPost,
    FreshnessClass,
    IntentHint,
    PublicInventoryRequest,
    PublicPostSnapshot,
    RiskClass,
)


_HOW_TO: Final = ("방법", "신청", "발급", "보내기", "고치기", "사용법")
_SCHEDULE: Final = (
    "일정",
    "예매",
    "개봉",
    "일출",
    "휴장",
    "거래시간",
    "시상식",
    "대진표",
    "출시일",
)
_COMPARISON: Final = ("비교", "차이", " vs ", "대결")
_TIME_SENSITIVE: Final = _SCHEDULE + (
    "2019",
    "2020",
    "운세",
    "공휴일",
    "새여권",
    "개정",
    "인상",
    "연봉",
)
_HIGH_RISK: Final = (
    "알벤다졸",
    "복용",
    "부작용",
    "항암",
    "빈혈",
    "철분결핍",
    "세금",
    "취득세",
    "종부세",
    "담보대출",
)
_MEDIUM_RISK: Final = (
    "규제",
    "법",
    "면허",
    "주민등록증",
    "여권",
    "가상자산",
    "비트코인",
)
_ACTION_BY_STATE: Final = {
    (RiskClass.HIGH, FreshnessClass.REVIEW_REQUIRED): ActionCandidate.HIGH_RISK_REVIEW,
    (RiskClass.MEDIUM, FreshnessClass.REVIEW_REQUIRED): ActionCandidate.CLUSTER_REVIEW,
    (RiskClass.LOW, FreshnessClass.REVIEW_REQUIRED): ActionCandidate.CLUSTER_REVIEW,
    (RiskClass.HIGH, FreshnessClass.TIME_SENSITIVE_STALE): ActionCandidate.HIGH_RISK_REVIEW,
    (RiskClass.HIGH, FreshnessClass.EVERGREEN_REVIEW_DUE): ActionCandidate.HIGH_RISK_REVIEW,
    (RiskClass.MEDIUM, FreshnessClass.TIME_SENSITIVE_STALE): ActionCandidate.REFRESH_OR_RETIRE,
    (RiskClass.MEDIUM, FreshnessClass.EVERGREEN_REVIEW_DUE): ActionCandidate.CLUSTER_REVIEW,
    (RiskClass.LOW, FreshnessClass.TIME_SENSITIVE_STALE): ActionCandidate.REFRESH_OR_RETIRE,
    (RiskClass.LOW, FreshnessClass.EVERGREEN_REVIEW_DUE): ActionCandidate.CLUSTER_REVIEW,
}


def classify_inventory(request: PublicInventoryRequest) -> tuple[ClassifiedPost, ...]:
    return tuple(
        _classify(post, request.checked_date)
        for post in sorted(
            request.posts,
            key=lambda item: (item.published_at, item.canonical_url),
            reverse=True,
        )
    )


def _classify(post: PublicPostSnapshot, checked_date: date) -> ClassifiedPost:
    text = post.title.casefold()
    intent = _intent(text)
    age_days = (checked_date - post.modified_at.date()).days
    time_sensitive = _contains(text, _TIME_SENSITIVE) or bool(re.search(r"\b20\d{2}\b", text))
    freshness = FreshnessClass.REVIEW_REQUIRED
    if time_sensitive and age_days >= 90:
        freshness = FreshnessClass.TIME_SENSITIVE_STALE
    elif age_days >= 365:
        freshness = FreshnessClass.EVERGREEN_REVIEW_DUE
    risk = _risk(text, post.category)
    action = _action(risk, freshness)
    return ClassifiedPost(post, intent, freshness, risk, action)


def _intent(text: str) -> IntentHint:
    if _contains(text, _HOW_TO):
        return IntentHint.HOW_TO
    if _contains(text, _SCHEDULE):
        return IntentHint.SCHEDULE
    if _contains(text, _COMPARISON):
        return IntentHint.COMPARISON
    return IntentHint.EXPLANATION


def _risk(text: str, category: str) -> RiskClass:
    if _contains(text, _HIGH_RISK):
        return RiskClass.HIGH
    if category == "경제" or _contains(text, _MEDIUM_RISK):
        return RiskClass.MEDIUM
    return RiskClass.LOW


def _action(risk: RiskClass, freshness: FreshnessClass) -> ActionCandidate:
    return _ACTION_BY_STATE[(risk, freshness)]


def _contains(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
