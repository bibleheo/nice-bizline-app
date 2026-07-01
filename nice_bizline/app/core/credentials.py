"""OS 자격증명 저장소(keyring) 연동 - ID/PW 평문 저장 방지.

Windows: 자격 증명 관리자 / macOS: Keychain / Linux: Secret Service.
백엔드가 없는 환경에서는 조용히 비활성화되어 매 실행 시 재입력 모드로 동작.
"""
from __future__ import annotations

SERVICE = "nice_bizline_app"
_LAST_ID_KEY = "__last_id__"

# 백엔드 탐지 비용/실패 잡음 최소화를 위해 1회 캐싱
_backend_cache: object = "uninitialized"


def _try_backend():
    """사용 가능한 keyring 백엔드를 반환. 없으면 None. (1회 캐싱)"""
    global _backend_cache
    if _backend_cache != "uninitialized":
        return _backend_cache
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        kr = keyring.get_keyring()
        _backend_cache = None if isinstance(kr, FailKeyring) else keyring
    except BaseException:
        _backend_cache = None
    return _backend_cache


def is_available() -> bool:
    return _try_backend() is not None


def load() -> tuple[str, str]:
    """저장된 (id, pw) 반환. 없거나 백엔드 부재 시 ('', '')."""
    keyring = _try_backend()
    if keyring is None:
        return "", ""
    try:
        uid = keyring.get_password(SERVICE, _LAST_ID_KEY) or ""
        if not uid:
            return "", ""
        pw = keyring.get_password(SERVICE, uid) or ""
        return uid, pw
    except BaseException:
        return "", ""


def save(user_id: str, password: str) -> bool:
    """저장 성공 시 True. 백엔드 부재나 빈 ID는 False."""
    keyring = _try_backend()
    if keyring is None or not user_id:
        return False
    try:
        keyring.set_password(SERVICE, user_id, password)
        keyring.set_password(SERVICE, _LAST_ID_KEY, user_id)
        return True
    except BaseException:
        return False


def clear() -> None:
    """저장된 자격증명 삭제 (마지막으로 저장된 ID 기준)."""
    keyring = _try_backend()
    if keyring is None:
        return
    try:
        uid = keyring.get_password(SERVICE, _LAST_ID_KEY)
    except BaseException:
        return
    for key in (uid, _LAST_ID_KEY):
        if not key:
            continue
        try:
            keyring.delete_password(SERVICE, key)
        except BaseException:
            pass
