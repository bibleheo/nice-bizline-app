"""credentials 모듈은 백엔드 부재 환경에서도 절대 예외를 던지지 않아야 한다."""
from nice_bizline.app.core import credentials


def test_is_available_returns_bool():
    result = credentials.is_available()
    assert isinstance(result, bool)


def test_load_returns_tuple_of_strings():
    uid, pw = credentials.load()
    assert isinstance(uid, str)
    assert isinstance(pw, str)


def test_save_empty_id_returns_false():
    assert credentials.save("", "pw") is False


def test_clear_does_not_raise():
    # 어떤 상황에서도 예외 없음
    credentials.clear()


def test_save_returns_bool():
    result = credentials.save("__test_user__", "__test_pw__")
    assert isinstance(result, bool)
    # 부수효과 정리
    credentials.clear()


def test_repeated_is_available_consistent():
    """캐싱이 적용되어도 동일한 결과가 안정적으로 반환."""
    a = credentials.is_available()
    b = credentials.is_available()
    assert a == b
