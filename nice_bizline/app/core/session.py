"""세션 만료 타이머 - 10분 만료 대비 9분에 선제 재로그인."""
from __future__ import annotations

from datetime import datetime, timedelta


class SessionManager:
    def __init__(self, relogin_threshold_minutes: float = 9.0):
        self._threshold = timedelta(minutes=relogin_threshold_minutes)
        self._started_at: datetime | None = None

    def mark_login(self) -> None:
        self._started_at = datetime.now()

    def needs_relogin(self) -> bool:
        if self._started_at is None:
            return True
        return datetime.now() - self._started_at > self._threshold

    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return (datetime.now() - self._started_at).total_seconds()
