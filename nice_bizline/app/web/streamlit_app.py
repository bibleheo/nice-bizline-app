"""나이스비즈라인 자동화 - Streamlit 웹 UI.

브라우저에서 직접 실행 가능. GitHub Codespaces에서 바로 사용 가능.

실행:
  streamlit run nice_bizline/app/web/streamlit_app.py
"""
from __future__ import annotations

import io
import os
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import yaml

from ..core.collector import MockCollector, NiceBizlineCollector
from ..core.pipeline import PipelineOptions, PipelineState, run_pipeline
from ..excelio.reader import read_company_list
from ..excelio.writer import write_results


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


@st.cache_data
def _load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _init_session():
    for key, default in [
        ("running", False),
        ("logs", []),
        ("done_summary", None),
        ("state", None),
        ("output_bytes", None),
        ("output_name", None),
        ("finance_years", 1),
        ("mock", True),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default


def main():
    st.set_page_config(page_title="나이스비즈라인 자동화", layout="wide")
    _init_session()
    cfg = _load_config()

    st.title("나이스비즈라인 기업정보 조회 자동화")
    st.caption("웹 UI 버전 - Codespaces 지원. 데스크톱 앱과 동일한 파이프라인.")

    # ─── 사이드바 ───
    with st.sidebar:
        st.header("실행 설정")
        st.session_state.mock = st.toggle(
            "모의 모드 (사이트 접근 없이 더미 데이터)",
            value=st.session_state.mock,
            help="셀렉터가 채워지지 않은 상태에서는 반드시 켜세요.",
        )

        if not st.session_state.mock:
            st.warning("실제 모드는 config.yaml의 DOM 셀렉터를 실 사이트에서 추출해 채워야 동작합니다.")

        st.session_state.finance_years = st.radio(
            "재무 범위", options=[1, 3],
            format_func=lambda n: f"최근 {n}개년",
            horizontal=True,
        )

    # ─── 입력 파일 ───
    st.subheader("① 입력 파일")
    uploaded = st.file_uploader(
        "회사 목록 엑셀 (.xlsx)",
        type=["xlsx"],
        help="첫 열이 회사명. 사업자번호/대표자명 컬럼이 있으면 매칭 정확도 향상.",
        disabled=st.session_state.running,
    )

    companies: list[dict] = []
    input_path = ""
    if uploaded is not None:
        # 임시 파일로 저장 (reader가 파일 경로 요구)
        input_path = str(Path(tempfile.gettempdir()) / uploaded.name)
        with open(input_path, "wb") as f:
            f.write(uploaded.getbuffer())
        try:
            companies = read_company_list(input_path)
            st.success(f"입력 로드 완료 - {len(companies)}건 (컬럼: {list(companies[0].keys()) if companies else []})")
            with st.expander("첫 5건 미리보기"):
                st.dataframe([{"회사명": c.get("회사명"), "사업자번호": c.get("사업자번호", ""),
                               "대표자명": c.get("대표자명", "")} for c in companies[:5]])
        except Exception as e:
            st.error(f"엑셀 읽기 실패: {e}")

    # ─── 계정 (모의 모드는 스킵) ───
    st.subheader("② 계정")
    col1, col2 = st.columns(2)
    with col1:
        user_id = st.text_input(
            "아이디",
            value="mock_user" if st.session_state.mock else "",
            disabled=st.session_state.running or st.session_state.mock,
        )
    with col2:
        password = st.text_input(
            "비밀번호", type="password",
            value="mock" if st.session_state.mock else "",
            disabled=st.session_state.running or st.session_state.mock,
        )

    # ─── 시작 버튼 ───
    st.subheader("③ 실행")
    start_disabled = (
        st.session_state.running
        or not companies
        or (not st.session_state.mock and not (user_id and password))
    )
    if st.button("▶ 조회 시작", type="primary", disabled=start_disabled):
        _run_collection(cfg, companies, user_id, password, input_path)

    # ─── 진행/결과 표시 ───
    if st.session_state.done_summary:
        _render_results()


def _run_collection(cfg, companies, user_id, password, input_path):
    """파이프라인을 동기 실행하며 Streamlit UI를 갱신."""
    st.session_state.running = True
    st.session_state.logs = []
    st.session_state.done_summary = None
    st.session_state.output_bytes = None

    progress_bar = st.progress(0, text="시작 중...")
    log_placeholder = st.empty()
    status_placeholder = st.empty()

    collector = (MockCollector(cfg) if st.session_state.mock
                 else NiceBizlineCollector(cfg))

    opts = PipelineOptions(
        user_id=user_id, password=password,
        companies=companies,
        finance_years=st.session_state.finance_years,
        input_path=input_path,
        checkpoint_every=10,
    )
    pstate = PipelineState()

    logs: list[str] = []
    for event in run_pipeline(collector, cfg, opts, pstate):
        t = event["type"]
        if t == "log":
            level = event["level"]
            emoji = {"info": "ℹ️", "warn": "⚠️", "error": "❌"}.get(level, "•")
            ts = datetime.now().strftime("%H:%M:%S")
            logs.append(f"{ts}  {emoji} {event['message']}")
            log_placeholder.code("\n".join(logs[-25:]), language=None)
        elif t == "progress":
            cur, total, name = event["current"], event["total"], event["name"]
            pct = cur / max(1, total)
            progress_bar.progress(pct, text=f"{cur}/{total}  ({int(pct*100)}%)  {name}")
        elif t == "done":
            summary = event["state"].summary
            st.session_state.state = event["state"]
            st.session_state.done_summary = summary
            st.session_state.logs = logs

    # 결과 엑셀을 메모리 버퍼로 생성
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    base = Path(input_path).stem if input_path else "결과"
    out_name = f"{base}_나이스비즈라인결과_{ts}.xlsx"
    tmp_path = Path(tempfile.gettempdir()) / out_name
    write_results(
        str(tmp_path),
        records=pstate.records,
        unfound=pstate.unfound,
        ambiguous=pstate.ambiguous,
        summary=pstate.summary,
        finance_years=st.session_state.finance_years,
    )
    with open(tmp_path, "rb") as f:
        st.session_state.output_bytes = f.read()
    st.session_state.output_name = out_name

    st.session_state.running = False
    st.rerun()


def _render_results():
    s = st.session_state.done_summary
    st.subheader("④ 결과")

    cols = st.columns(5)
    cols[0].metric("전체", s.get("total", 0))
    cols[1].metric("성공", s.get("success", 0))
    cols[2].metric("미발견", s.get("not_found", 0))
    cols[3].metric("확인필요", s.get("ambiguous", 0))
    cols[4].metric("오류", s.get("error", 0))

    if st.session_state.output_bytes:
        st.download_button(
            "📥 결과 엑셀 다운로드",
            data=st.session_state.output_bytes,
            file_name=st.session_state.output_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

    if st.session_state.logs:
        with st.expander("실행 로그 전체 보기", expanded=False):
            st.code("\n".join(st.session_state.logs), language=None)


if __name__ == "__main__":
    main()
