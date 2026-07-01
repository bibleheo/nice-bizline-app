"""수집 파이프라인 코어 - generator로 진행 이벤트 스트리밍.

Worker 스레드와 Streamlit 웹 UI가 이 함수를 공유합니다.
Worker: 스레드에서 이 generator를 소비하며 콜백으로 UI에 전달.
Streamlit: 메인 스레드에서 generator를 for-loop으로 소비하며 위젯 갱신.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

from . import checkpoint
from .collector import CollectorError, LoginRequired
from .matcher import pick
from .normalizer import normalize_amount, normalize_record
from .session import SessionManager


@dataclass
class PipelineState:
    records: list[dict] = field(default_factory=list)
    unfound: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    processed_keys: set = field(default_factory=set)
    summary: dict = field(default_factory=dict)


@dataclass
class PipelineOptions:
    user_id: str
    password: str
    companies: list[dict]
    finance_years: int = 1
    input_path: str = ""
    resume: bool = False
    checkpoint_every: int = 10


def run_pipeline(collector, cfg: dict, opts: PipelineOptions,
                 state: PipelineState | None = None,
                 stop_check=lambda: False) -> Iterator[dict]:
    """수집 파이프라인을 실행하며 이벤트를 yield.

    이벤트 형식:
      {"type": "log", "level": "info|warn|error", "message": "..."}
      {"type": "progress", "current": N, "total": M, "name": "..."}
      {"type": "done", "state": PipelineState}

    stop_check: 매 회사 처리 전 호출. True면 안전 정지.
    """
    if state is None:
        state = PipelineState()

    started = datetime.now()
    state.summary["started_at"] = started.strftime("%Y-%m-%d %H:%M:%S")

    session = SessionManager(cfg["timing"].get("relogin_threshold_minutes", 9))
    weights = cfg.get("matching", {})

    # 재개
    if opts.resume and opts.input_path:
        loaded = checkpoint.load(opts.input_path)
        if loaded:
            state.records = list(loaded.get("records", []))
            state.unfound = list(loaded.get("unfound", []))
            state.ambiguous = list(loaded.get("ambiguous", []))
            state.processed_keys = set(loaded.get("processed_keys", []))
            yield _log("info", f"체크포인트 로드 - 이미 처리된 {len(state.processed_keys)}건 스킵")

    # 로그인
    try:
        collector.login(opts.user_id, opts.password)
        session.mark_login()
        yield _log("info", "로그인 성공")
    except CollectorError as e:
        yield _log("error", f"로그인 실패: {e}")
        _finalize(state, opts, session, stopped=False, collector=collector)
        yield {"type": "done", "state": state}
        return

    total = len(opts.companies)
    stopped = False
    for i, query in enumerate(opts.companies, 1):
        if stop_check():
            yield _log("warn", "사용자 중단 - 처리분까지 저장합니다.")
            stopped = True
            break

        name = query.get("회사명", "")
        key = _key_for(query)

        # 재개 시 이미 처리된 것 스킵
        if key in state.processed_keys:
            yield {"type": "progress", "current": i, "total": total,
                   "name": f"{name} (이미 처리 - 스킵)"}
            continue

        yield {"type": "progress", "current": i, "total": total, "name": name}

        # 선제 재로그인
        if session.needs_relogin():
            yield _log("info", "세션 만료 임박 → 재로그인")
            try:
                collector.login(opts.user_id, opts.password)
                session.mark_login()
            except CollectorError as e:
                yield _log("error", f"재로그인 실패: {e}")
                _record_error(state, name, f"재로그인 실패: {e}")
                state.processed_keys.add(key)
                continue

        yield from _process_one(collector, opts, state, session, weights, query, name)
        state.processed_keys.add(key)

        # 주기적 체크포인트
        if opts.input_path and i % max(1, opts.checkpoint_every) == 0:
            if checkpoint.save(opts.input_path, checkpoint.build_state(
                processed_keys=sorted(state.processed_keys),
                records=state.records,
                unfound=state.unfound,
                ambiguous=state.ambiguous,
                total=total,
                finance_years=opts.finance_years,
            )):
                yield _log("info", f"체크포인트 저장 ({len(state.processed_keys)}건)")

    _finalize(state, opts, session, stopped=stopped, collector=collector)
    yield {"type": "done", "state": state}


def _process_one(collector, opts, state, session, weights, query, name):
    for attempt in (1, 2):
        try:
            yield from _collect(collector, opts, state, weights, query, name)
            return
        except LoginRequired:
            if attempt == 2:
                _record_error(state, name, "세션 만료 재시도 실패")
                return
            yield _log("warn", f"[{name}] 세션 만료 감지 → 재로그인 후 재시도")
            try:
                collector.login(opts.user_id, opts.password)
                session.mark_login()
            except CollectorError as e:
                _record_error(state, name, f"재로그인 실패: {e}")
                return
        except CollectorError as e:
            yield _log("error", f"[{name}] 수집 오류: {e}")
            _record_error(state, name, str(e))
            return
        except Exception as e:
            yield _log("error", f"[{name}] 예외: {e}")
            _record_error(state, name, f"예외: {e}")
            return


def _collect(collector, opts, state, weights, query, name):
    candidates = collector.search(name)
    match = pick(query, candidates, weights)

    if match.status == "none":
        yield _log("warn", f"[{name}] 미발견")
        state.unfound.append({"회사명": name, "조회상태": "미발견", "사유": "검색 결과 0건"})
        state.records.append(_blank_row(name, "미발견"))
        return

    if match.status == "ambiguous":
        others_desc = "; ".join(
            f"{c.get('회사명','')}/{c.get('사업자번호','')}" for c in match.others[:3]
        )
        yield _log("warn", f"[{name}] 후보 다수 - 확인필요")
        state.ambiguous.append({
            "회사명": name,
            "채택후보": (match.candidate or {}).get("회사명", ""),
            "다른후보들": others_desc,
            "사유": f"점수 {match.score} - 임계치 미달",
        })
        try:
            detail = collector.fetch_detail(match.candidate, opts.finance_years)
            rec = normalize_record(detail)
            rec.update(_finance_columns(rec, opts.finance_years))
            rec["조회상태"] = "확인필요"
            rec["조회일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rec["비고"] = f"동명 후보 {1 + len(match.others)}건"
            state.records.append(rec)
        except CollectorError:
            state.records.append(_blank_row(name, "확인필요", "상세 파싱 실패"))
        return

    # auto / unique
    detail = collector.fetch_detail(match.candidate, opts.finance_years)
    rec = normalize_record(detail)
    rec.update(_finance_columns(rec, opts.finance_years))
    rec["조회상태"] = "성공"
    rec["조회일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    missing = [k for k in ("매출액", "영업이익", "당기순이익", "신용등급")
               if rec.get(k) in (None, "")]
    rec["비고"] = f"권한없음/미제공: {', '.join(missing)}" if missing else ""
    state.records.append(rec)
    yield _log("info", f"[{rec.get('회사명', name)}] 수집 완료")


def _finalize(state, opts, session, stopped, collector):
    if opts.input_path:
        checkpoint.save(opts.input_path, checkpoint.build_state(
            processed_keys=sorted(state.processed_keys),
            records=state.records,
            unfound=state.unfound,
            ambiguous=state.ambiguous,
            total=len(opts.companies),
            finance_years=opts.finance_years,
        ))

    s = state.summary
    s["ended_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s["total"] = len(opts.companies)
    s["success"] = sum(1 for r in state.records if r.get("조회상태") == "성공")
    s["not_found"] = sum(1 for r in state.records if r.get("조회상태") == "미발견")
    s["ambiguous"] = sum(1 for r in state.records if r.get("조회상태") == "확인필요")
    s["error"] = sum(1 for r in state.records if r.get("조회상태") == "오류")
    s["stopped"] = stopped
    try:
        collector.close()
    except Exception:
        pass


def _log(level: str, message: str) -> dict:
    return {"type": "log", "level": level, "message": message}


def _key_for(query: dict) -> str:
    return f"{query.get('회사명', '')}|{query.get('사업자번호', '')}"


def _record_error(state, name: str, reason: str) -> None:
    state.unfound.append({"회사명": name, "조회상태": "오류", "사유": reason})
    state.records.append(_blank_row(name, "오류", reason))


def _blank_row(name: str, status: str, reason: str = "") -> dict:
    return {
        "회사명": name,
        "조회상태": status,
        "조회일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "비고": reason,
    }


def _finance_columns(rec: dict, finance_years: int) -> dict:
    if finance_years <= 1:
        return {
            "매출액(백만원)": rec.get("매출액"),
            "영업이익(백만원)": rec.get("영업이익"),
            "당기순이익(백만원)": rec.get("당기순이익"),
        }
    out: dict = {}
    for entry in (rec.get("재무_연도별") or [])[:finance_years]:
        year = entry.get("연도", "?")
        out[f"매출액({year})"] = normalize_amount(entry.get("매출액"))
        out[f"영업이익({year})"] = normalize_amount(entry.get("영업이익"))
        out[f"당기순이익({year})"] = normalize_amount(entry.get("당기순이익"))
    return out
