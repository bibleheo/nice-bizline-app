"""워커 파이프라인 통합 테스트: MockCollector 기반 엔드투엔드."""
import yaml

from nice_bizline.app.core.collector import MockCollector, LoginRequired
from nice_bizline.app.core.worker import RunOptions, Worker, WorkerCallbacks


def _load_cfg():
    import os
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _run(companies, collector=None):
    cfg = _load_cfg()
    done = {}
    logs = []
    opts = RunOptions(user_id="u", password="p", companies=companies)
    cb = WorkerCallbacks(
        on_log=lambda lvl, msg: logs.append((lvl, msg)),
        on_progress=lambda c, t, n: None,
        on_done=done.update,
    )
    w = Worker(collector or MockCollector(cfg), cfg, opts, cb)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive(), "워커가 시간 내 종료되지 않음"
    return w, done, logs


def test_success_path():
    w, summary, _ = _run([{"회사명": "삼성전자"}, {"회사명": "현대자동차"}])
    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["not_found"] == 0


def test_not_found():
    w, summary, _ = _run([{"회사명": "존재하지않는회사XYZ"}])
    assert summary["not_found"] == 1
    assert any(r["조회상태"] == "미발견" for r in w.state.records)
    assert len(w.state.unfound) == 1


def test_mixed_results():
    w, summary, _ = _run([
        {"회사명": "삼성전자"},
        {"회사명": "없는회사1"},
        {"회사명": "현대자동차"},
        {"회사명": "없는회사2"},
    ])
    assert summary["success"] == 2
    assert summary["not_found"] == 2
    assert summary["error"] == 0


def test_login_failure_records_errors():
    """로그인이 실패하면 모든 건이 오류 처리되지 않고 finalize까지 진행."""
    cfg = _load_cfg()

    class BrokenCollector(MockCollector):
        def login(self, user_id, password):
            from nice_bizline.app.core.collector import CollectorError
            raise CollectorError("자격증명 거부")

    w, summary, logs = _run([{"회사명": "삼성전자"}], collector=BrokenCollector(cfg))
    assert summary["total"] == 1
    assert any("로그인 실패" in m for _, m in logs)


def test_login_required_triggers_relogin_retry():
    """첫 호출에서 LoginRequired → 재로그인 후 1회 재시도 후 성공."""
    cfg = _load_cfg()

    class FlakyCollector(MockCollector):
        def __init__(self, cfg):
            super().__init__(cfg)
            self._search_count = 0

        def search(self, name):
            self._search_count += 1
            if self._search_count == 1:
                raise LoginRequired()
            return super().search(name)

    w, summary, logs = _run([{"회사명": "삼성전자"}], collector=FlakyCollector(cfg))
    assert summary["success"] == 1
    assert any("세션 만료 감지" in m for _, m in logs)


def test_duplicate_input_logs_and_skips():
    """같은 실행 안에서 동일 회사명|사업자번호가 반복되면 경고 로그 후 1회만 처리."""
    w, summary, logs = _run([
        {"회사명": "삼성전자"},
        {"회사명": "삼성전자"},
        {"회사명": "현대자동차"},
    ])
    assert summary["total"] == 3
    # 삼성전자(1회) + 현대자동차(1회) = 2건만 수집, 중복 삼성전자는 스킵
    assert summary["success"] == 2
    assert len(w.state.records) == 2  # 중복 삼성전자는 record에 추가되지 않음
    assert any("중복 입력" in m for lvl, m in logs if lvl == "warn")


def test_stop_safely_finalizes():
    """stop() 호출 후에도 finalize가 호출되어 결과를 반환."""
    cfg = _load_cfg()
    done = {}
    opts = RunOptions(user_id="u", password="p", companies=[{"회사명": "삼성전자"}] * 20)
    cb = WorkerCallbacks(
        on_log=lambda *_: None,
        on_progress=lambda *_: None,
        on_done=done.update,
    )
    w = Worker(MockCollector(cfg), cfg, opts, cb)
    w.start()
    w.stop()  # 즉시 중단
    w.join(timeout=5)
    assert not w.is_alive()
    assert "total" in done
