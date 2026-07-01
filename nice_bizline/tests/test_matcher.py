from nice_bizline.app.core.matcher import pick

WEIGHTS = {
    "weight_biz_no": 100,
    "weight_ceo": 30,
    "weight_address": 20,
    "accept_threshold": 25,
}


def test_no_candidates_returns_none():
    r = pick({"회사명": "X"}, [], WEIGHTS)
    assert r.status == "none"
    assert r.candidate is None


def test_single_candidate_unique():
    r = pick({"회사명": "X"}, [{"회사명": "X사"}], WEIGHTS)
    assert r.status == "unique"
    assert r.candidate == {"회사명": "X사"}


def test_biz_no_match_auto_confirmed():
    """사업자번호 일치 시 다른 후보가 더 많아도 즉시 확정."""
    r = pick(
        {"회사명": "X", "사업자번호": "123-45-67890"},
        [
            {"회사명": "A사", "사업자번호": "9999999999"},
            {"회사명": "B사", "사업자번호": "1234567890"},
        ],
        WEIGHTS,
    )
    assert r.status == "auto"
    assert r.candidate["회사명"] == "B사"


def test_ceo_and_address_score_passes_threshold():
    r = pick(
        {"회사명": "X", "대표자명": "홍길동", "주소": "서울 강남구 역삼동"},
        [
            {"회사명": "A사", "대표자명": "홍길동", "주소": "서울 강남구"},  # 30+20=50
            {"회사명": "B사", "대표자명": "김철수", "주소": "부산 해운대구"},  # 0
        ],
        WEIGHTS,
    )
    assert r.status == "auto"
    assert r.candidate["회사명"] == "A사"


def test_below_threshold_returns_ambiguous():
    """일치 신호가 없으면 임계치 미달로 확인필요 분류."""
    r = pick(
        {"회사명": "X"},
        [
            {"회사명": "A사", "주소": "서울"},
            {"회사명": "B사", "주소": "부산"},
        ],
        WEIGHTS,
    )
    assert r.status == "ambiguous"
    # 최상위 후보 + 나머지가 others에 채워짐
    assert r.candidate is not None
    assert len(r.others) >= 1


def test_ambiguous_when_top_ties_second():
    """동점이면 임계치를 넘어도 ambiguous로 분류 (안전판)."""
    r = pick(
        {"회사명": "X", "대표자명": "홍길동"},
        [
            {"회사명": "A사", "대표자명": "홍길동"},
            {"회사명": "B사", "대표자명": "홍길동"},
        ],
        WEIGHTS,
    )
    assert r.status == "ambiguous"
