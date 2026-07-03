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


@dataclass
class SelectResult:
    """검색 결과에서 실제로 수집할 대상을 고른 결과.

    status:
      'none'      - 실제 기업 후보 없음 (검색 0건 또는 전부 펀드/ETF)
      'biz'       - 입력 사업자번호와 일치하는 1건 확정
      'single'    - 동명 회사 1건
      'multiple'  - 동명 회사 여러 건 → 전부 수집
      'ambiguous' - 이름이 정확히 일치하는 후보가 없어 판단 보류 (검수 필요)
    picks:   상세를 수집할 대상 리스트 (multiple이면 2건 이상)
    others:  검수용으로 남기는 나머지 후보
    dropped: 사업자번호가 없어 제외된 비기업(펀드/ETF 등) 건수
    """
    status: str
    picks: list[dict]
    others: list[dict]
    dropped: int = 0


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


# 상호에서 법인격 표기를 제거해 이름 비교를 정확히 한다.
# 주의: 괄호형((주)/㈜)과 명시적 단어형만 제거. 단독 음절 '주'는 건드리지 않음
# (예: '주성엔지니어링'의 '주'는 유지).
_CORP_FORM = re.compile(
    r"㈜|\(\s*(?:주|유|재|사|합|유한책임)\s*\)"
    r"|주식회사|유한회사|유한책임회사|합자회사|합명회사|재단법인|사단법인|의료법인|학교법인"
)
_STRIP_NON_NAME = re.compile(r"[\s()\[\]·.,\-_/]")


def _norm_company(name: str | None) -> str:
    s = _CORP_FORM.sub("", name or "")
    s = _STRIP_NON_NAME.sub("", s)
    return s.lower()


def _has_biz(candidate: dict) -> bool:
    """실제 기업이면 사업자번호가 있다. 펀드/ETF 등은 '-'/공란."""
    return bool(_digits(candidate.get("사업자번호")))


def _dedup_by_biz(cands: list[dict]) -> list[dict]:
    """사업자번호 기준 중복 제거(첫 등장 유지)."""
    seen: set[str] = set()
    out: list[dict] = []
    for c in cands:
        b = _digits(c.get("사업자번호"))
        if b in seen:
            continue
        seen.add(b)
        out.append(c)
    return out


def select_matches(query: dict, candidates: list[dict], weights: dict) -> SelectResult:
    """수집 대상 후보를 선별한다.

    규칙:
      1. 사업자번호 없는 후보(펀드/ETF 등)는 제외한다.
      2. 입력에 사업자번호가 있으면 그 번호와 일치하는 1건만 확정한다.
      3. 사업자번호를 모르면, 상호가 정확히 일치하는 실제 기업을 모두 채택한다.
         - 1건이면 'single', 여러 건(동명이인)이면 'multiple' → 전부 수집.
         - 정확 일치가 없으면 'ambiguous'로 두어 검수하도록 한다.
    """
    real = [c for c in candidates if _has_biz(c)]
    dropped = len(candidates) - len(real)

    if not real:
        return SelectResult("none", [], [], dropped)

    # 2) 입력 사업자번호로 확정
    q_biz = _digits(query.get("사업자번호"))
    if q_biz:
        exact = [c for c in real if _digits(c.get("사업자번호")) == q_biz]
        if exact:
            others = [c for c in real if c not in exact]
            return SelectResult("biz", exact[:1], others, dropped)
        # 사업자번호를 줬는데 결과에 없음 → 이름으로 재판단 (아래로 진행)

    # 3) 상호 정확 일치로 동명 회사 전부 채택
    qn = _norm_company(query.get("회사명"))
    name_matches = [c for c in real if _norm_company(c.get("회사명")) == qn] if qn else []
    # 같은 회사가 상호 표기만 달리해 여러 번 뜨는 경우 사업자번호로 중복 제거
    name_matches = _dedup_by_biz(name_matches)
    others = [c for c in real if c not in name_matches]

    if not name_matches:
        return SelectResult("ambiguous", [], real, dropped)
    if len(name_matches) == 1:
        return SelectResult("single", name_matches, others, dropped)
    return SelectResult("multiple", name_matches, others, dropped)


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
