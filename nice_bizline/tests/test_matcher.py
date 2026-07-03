from nice_bizline.app.core.matcher import pick, select_matches, _norm_company

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


def test_norm_company_strips_corp_forms_but_keeps_syllables():
    assert _norm_company("삼성전자(주)") == _norm_company("삼성전자")
    assert _norm_company("주식회사 가나") == _norm_company("가나")
    # 단독 음절 '주'는 법인격 표기가 아니므로 유지
    assert _norm_company("주성엔지니어링") == "주성엔지니어링"


def test_select_matches_drops_non_company():
    r = select_matches({"회사명": "가나"}, [
        {"회사명": "가나(주)", "사업자번호": "111-11-11111"},
        {"회사명": "가나펀드", "사업자번호": "-"},
    ], WEIGHTS)
    assert r.dropped == 1
    assert r.status == "single"
    assert len(r.picks) == 1


def test_select_matches_multiple_same_name():
    r = select_matches({"회사명": "동명"}, [
        {"회사명": "동명(주)", "사업자번호": "111-11-11111"},
        {"회사명": "동명(주)", "사업자번호": "222-22-22222"},
    ], WEIGHTS)
    assert r.status == "multiple"
    assert len(r.picks) == 2


def test_select_matches_biz_number_confirms():
    r = select_matches({"회사명": "동명", "사업자번호": "222-22-22222"}, [
        {"회사명": "동명(주)", "사업자번호": "111-11-11111"},
        {"회사명": "동명(주)", "사업자번호": "222-22-22222"},
    ], WEIGHTS)
    assert r.status == "biz"
    assert r.picks[0]["사업자번호"] == "222-22-22222"


def test_select_matches_narrow_by_ceo():
    """입력에 대표자명이 있으면 동명 후보를 대표자로 좁힌다."""
    r = select_matches({"회사명": "세명", "대표자명": "이경환"}, [
        {"회사명": "세명(주)", "사업자번호": "111-11-11111", "대표자명": "김철수"},
        {"회사명": "세명(주)", "사업자번호": "222-22-22222", "대표자명": "이경환"},
        {"회사명": "세명(주)", "사업자번호": "333-33-33333", "대표자명": "박영수"},
    ], WEIGHTS)
    assert r.status == "single"
    assert r.picks[0]["사업자번호"] == "222-22-22222"


def test_select_matches_narrow_by_address():
    """입력에 주소가 있으면 지역(앞부분)으로 좁힌다."""
    r = select_matches({"회사명": "세명", "주소": "대구 북구"}, [
        {"회사명": "세명(주)", "사업자번호": "111-11-11111", "주소": "서울 강남구"},
        {"회사명": "세명(주)", "사업자번호": "222-22-22222", "주소": "(41513) 대구 북구 검단로"},
    ], WEIGHTS)
    assert r.status == "single"
    assert r.picks[0]["사업자번호"] == "222-22-22222"


def test_select_matches_narrow_no_match_keeps_all():
    """좁힐 값이 아무 후보와도 안 맞으면 원본 유지(오탈자/정보 불일치 대비)."""
    r = select_matches({"회사명": "세명", "대표자명": "없는사람"}, [
        {"회사명": "세명(주)", "사업자번호": "111-11-11111", "대표자명": "김철수"},
        {"회사명": "세명(주)", "사업자번호": "222-22-22222", "대표자명": "이경환"},
    ], WEIGHTS)
    assert r.status == "multiple"
    assert len(r.picks) == 2


def test_select_matches_none_when_all_noise():
    r = select_matches({"회사명": "X"},
                       [{"회사명": "X펀드", "사업자번호": "-"}], WEIGHTS)
    assert r.status == "none"


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
