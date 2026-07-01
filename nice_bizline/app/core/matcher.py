"""검색 결과 후보에서 1건 채택하기 위한 점수 매칭."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class MatchResult:
    candidate: dict | None
    score: int
    status: str          # 'auto' | 'unique' | 'ambiguous' | 'none'
    others: list[dict]   # ambiguous일 때 다른 후보들 (검수용)


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _addr_tokens(addr: str | None) -> set[str]:
    """주소에서 시/구 단위 키워드 추출 (간단 토큰화)."""
    if not addr:
        return set()
    tokens = re.findall(r"[가-힣A-Za-z]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)", addr)
    return set(tokens)


def score_candidate(query: dict, candidate: dict, weights: dict) -> int:
    """입력값(query)과 후보(candidate)의 일치 점수."""
    score = 0
    q_biz = _digits(query.get("사업자번호"))
    c_biz = _digits(candidate.get("사업자번호"))
    if q_biz and c_biz and q_biz == c_biz:
        score += int(weights.get("weight_biz_no", 100))

    q_ceo = (query.get("대표자명") or "").strip()
    c_ceo = (candidate.get("대표자명") or "").strip()
    if q_ceo and c_ceo and q_ceo == c_ceo:
        score += int(weights.get("weight_ceo", 30))

    q_tokens = _addr_tokens(query.get("주소"))
    c_tokens = _addr_tokens(candidate.get("주소"))
    if q_tokens & c_tokens:
        score += int(weights.get("weight_address", 20))

    return score


def pick(query: dict, candidates: list[dict], weights: dict) -> MatchResult:
    if not candidates:
        return MatchResult(None, 0, "none", [])
    if len(candidates) == 1:
        return MatchResult(candidates[0], 0, "unique", [])

    # 사업자번호 일치는 즉시 확정
    q_biz = _digits(query.get("사업자번호"))
    if q_biz:
        for c in candidates:
            if _digits(c.get("사업자번호")) == q_biz:
                return MatchResult(c, int(weights.get("weight_biz_no", 100)), "auto", [])

    scored = sorted(
        ((score_candidate(query, c, weights), c) for c in candidates),
        key=lambda x: x[0],
        reverse=True,
    )
    top_score, top_cand = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    threshold = int(weights.get("accept_threshold", 25))

    # 최상위가 임계치 이상이고 2위와 차이가 있으면 채택
    if top_score >= threshold and top_score > second_score:
        return MatchResult(top_cand, top_score, "auto", [c for _, c in scored[1:]])

    return MatchResult(top_cand, top_score, "ambiguous", [c for _, c in scored[1:]])
