import time

from nice_bizline.app.core.session import SessionManager


def test_needs_relogin_before_mark():
    s = SessionManager(relogin_threshold_minutes=9)
    assert s.needs_relogin() is True


def test_does_not_need_after_fresh_login():
    s = SessionManager(relogin_threshold_minutes=9)
    s.mark_login()
    assert s.needs_relogin() is False


def test_needs_after_threshold():
    """임계치를 매우 짧게 설정해 만료 동작 확인."""
    s = SessionManager(relogin_threshold_minutes=0.01)  # 0.6초
    s.mark_login()
    assert s.needs_relogin() is False
    time.sleep(0.8)
    assert s.needs_relogin() is True


def test_elapsed_seconds():
    s = SessionManager()
    assert s.elapsed_seconds() == 0.0
    s.mark_login()
    time.sleep(0.05)
    assert s.elapsed_seconds() >= 0.05
