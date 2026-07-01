"""체크포인트 저장/로드 + 워커 재개 동작 검증."""
import json
import os
import yaml

from nice_bizline.app.core import checkpoint
from nice_bizline.app.core.collector import MockCollector
from nice_bizline.app.core.worker import RunOptions, Worker, WorkerCallbacks


def _cfg():
    with open(os.path.join(os.path.dirname(__file__), "..", "config.yaml"),
              encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── checkpoint 모듈 ────────────────────────────────────────────────


def test_path_for(tmp_path):
    inp = str(tmp_path / "고객사.xlsx")
    assert checkpoint.path_for(inp).endswith(".progress.json")


def test_exists_load_nonexistent(tmp_path):
    inp = str(tmp_path / "x.xlsx")
    assert checkpoint.exists(inp) is False
    assert checkpoint.load(inp) is None


def test_save_load_roundtrip(tmp_path):
    inp = str(tmp_path / "x.xlsx")
    state = checkpoint.build_state(
        processed_keys=["A|", "B|123"],
        records=[{"회사명": "A"}],
        unfound=[],
        ambiguous=[],
        total=10,
        finance_years=3,
    )
    assert checkpoint.save(inp, state) is True
    assert checkpoint.exists(inp) is True
    loaded = checkpoint.load(inp)
    assert loaded["total"] == 10
    assert loaded["finance_years"] == 3
    assert loaded["processed_keys"] == ["A|", "B|123"]
    assert loaded["records"][0]["회사명"] == "A"


def test_clear_removes_file(tmp_path):
    inp = str(tmp_path / "x.xlsx")
    checkpoint.save(inp, checkpoint.build_state([], [], [], [], 1, 1))
    checkpoint.clear(inp)
    assert not checkpoint.exists(inp)


def test_load_malformed_returns_none(tmp_path):
    inp = str(tmp_path / "x.xlsx")
    with open(checkpoint.path_for(inp), "w") as f:
        f.write("not valid json {{{")
    assert checkpoint.load(inp) is None


# ── 워커 통합 ────────────────────────────────────────────────────


def _run(opts, companies):
    cfg = _cfg()
    done = {}
    cb = WorkerCallbacks(
        on_log=lambda *_: None,
        on_progress=lambda *_: None,
        on_done=done.update,
    )
    opts.companies = companies
    w = Worker(MockCollector(cfg), cfg, opts, cb)
    w.start()
    w.join(timeout=10)
    return w, done


def test_worker_writes_checkpoint_on_finalize(tmp_path):
    inp = str(tmp_path / "in.xlsx")
    opts = RunOptions(user_id="u", password="p", companies=[],
                      input_path=inp, checkpoint_every=100)
    _run(opts, [{"회사명": "삼성전자"}, {"회사명": "현대자동차"}])
    assert checkpoint.exists(inp)
    state = checkpoint.load(inp)
    assert state["total"] == 2
    assert len(state["processed_keys"]) == 2


def test_worker_resume_skips_processed(tmp_path):
    inp = str(tmp_path / "in.xlsx")
    # 1차 실행: 1건만 처리한 척 체크포인트 직접 작성
    state = checkpoint.build_state(
        processed_keys=["삼성전자|"],
        records=[{"회사명": "삼성전자(주)", "조회상태": "성공"}],
        unfound=[],
        ambiguous=[],
        total=2,
        finance_years=1,
    )
    checkpoint.save(inp, state)

    # 2차 실행: resume=True로 시작 - 삼성전자는 스킵, 현대자동차만 처리
    opts = RunOptions(user_id="u", password="p", companies=[],
                      input_path=inp, resume=True, checkpoint_every=100)
    w, done = _run(opts, [{"회사명": "삼성전자"}, {"회사명": "현대자동차"}])

    # 결과에는 1차 처리분 + 2차 신규 처리분 모두 있어야 함
    names = [r.get("회사명") for r in w.state.records]
    assert "삼성전자(주)" in names      # 복원된 1차 결과
    assert "현대자동차(주)" in names    # 2차 신규 처리
    assert len(w.state.records) == 2


def test_worker_resume_disabled_by_default(tmp_path):
    """resume=False(기본)면 체크포인트가 있어도 무시하고 새로 시작."""
    inp = str(tmp_path / "in.xlsx")
    checkpoint.save(inp, checkpoint.build_state(
        processed_keys=["삼성전자|"],
        records=[{"회사명": "OLD", "조회상태": "성공"}],
        unfound=[], ambiguous=[], total=99, finance_years=1,
    ))
    opts = RunOptions(user_id="u", password="p", companies=[],
                      input_path=inp, resume=False, checkpoint_every=100)
    w, _ = _run(opts, [{"회사명": "삼성전자"}])
    # OLD 레코드는 복원되지 않고, 새로 처리한 결과만 있어야 함
    assert all(r.get("회사명") != "OLD" for r in w.state.records)


def test_periodic_save_every_n(tmp_path):
    """checkpoint_every=1로 두면 매 건마다 저장."""
    inp = str(tmp_path / "in.xlsx")
    opts = RunOptions(user_id="u", password="p", companies=[],
                      input_path=inp, checkpoint_every=1)
    _run(opts, [{"회사명": "삼성전자"}, {"회사명": "현대자동차"}])
    # 마지막 _finalize에서도 저장하므로 파일 존재 보장
    assert checkpoint.exists(inp)
    state = checkpoint.load(inp)
    assert len(state["processed_keys"]) == 2
