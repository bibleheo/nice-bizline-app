"""나이스비즈라인 수집기.

- BaseCollector: 인터페이스 (공식 API 전환 시 교체 지점)
- NiceBizlineCollector: Playwright 기반 수집기
- MockCollector: 사이트 접근 없이 파이프라인 검증용

실제 사용 전 config.yaml의 selectors를 실제 페이지 DOM으로 채워야 합니다.
"""
from __future__ import annotations

import random
import re
import time
from typing import Protocol

from .normalizer import amount_to_millions


class CollectorError(Exception):
    pass


class LoginRequired(CollectorError):
    """세션 만료로 로그인 페이지로 튕긴 경우."""


class BaseCollector(Protocol):
    def login(self, user_id: str, password: str) -> None: ...
    def search(self, company_name: str) -> list[dict]: ...
    def fetch_detail(self, candidate: dict, finance_years: int = 1) -> dict: ...
    def extend_session(self) -> bool: ...
    def is_login_page(self) -> bool: ...
    def close(self) -> None: ...


# ── 실 수집기 (Playwright) ────────────────────────────────────────────────────


class NiceBizlineCollector:
    """Playwright 기반 나이스비즈라인 수집기.

    셀렉터는 config['selectors']에서 모두 외부 주입.
    재무 권한이 없는 항목은 None으로 반환 (호출자가 비고에 사유 기록).
    """

    def __init__(self, config: dict):
        # 지연 import: GUI만 띄울 때는 Playwright가 없어도 됩니다.
        from playwright.sync_api import sync_playwright

        self._cfg = config
        self._pw = sync_playwright().start()
        browser_cfg = config.get("browser", {})
        self._browser = self._pw.chromium.launch(headless=browser_cfg.get("headless", True))
        ctx_kwargs = {}
        if ua := browser_cfg.get("user_agent"):
            ctx_kwargs["user_agent"] = ua
        self._context = self._browser.new_context(**ctx_kwargs)
        self._page = self._context.new_page()
        self._page.set_default_timeout(int(config["timing"].get("page_timeout_sec", 30)) * 1000)

    def close(self) -> None:
        try:
            self._context.close()
            self._browser.close()
        finally:
            self._pw.stop()

    # ── 로그인 ──
    def login(self, user_id: str, password: str) -> None:
        sel = self._cfg["selectors"]["login"]
        self._page.goto(self._cfg["site"]["login_url"])
        # 세션이 아직 살아있으면 로그인 폼 대신 '나의정보' 마커가 바로 보인다.
        # (선제 재로그인 타이머가 일찍 돌아도 실제로는 로그인 유지 중일 수 있음)
        if self._visible(sel["logged_in_marker"], timeout=4000):
            return
        if not self._visible(sel["id_input"], timeout=4000):
            raise CollectorError("로그인 폼을 찾지 못함 (팝업 또는 페이지 구조 변경 가능)")
        self._page.fill(sel["id_input"], user_id)
        self._page.fill(sel["pw_input"], password)
        self._page.click(sel["submit_btn"])
        # 동시접속 제한 팝업이 뜨면 기존 접속을 강제 종료
        self._dismiss_concurrent_popup()
        if not self._visible(sel["logged_in_marker"], timeout=15000):
            raise CollectorError(
                "로그인 후 '나의정보' 미노출 (동시접속 팝업 처리 실패 가능)")

    def _dismiss_concurrent_popup(self) -> bool:
        """동시접속 제한(1명) 팝업 처리: 기존 접속 강제 종료 후 팝업 닫기.

        순서: 접속 종료 → 예 → 확인. 팝업이 없으면 아무것도 안 하고 False.
        """
        sess = self._cfg["selectors"].get("session", {}) or {}
        first = sess.get("disconnect_btn") or "button:has-text('접속 종료'):visible"
        if not self._visible(first, timeout=3000):
            return False
        steps = [
            first,
            sess.get("disconnect_confirm_btn") or "button:has-text('예'):visible",
            sess.get("disconnect_done_btn") or "button:has-text('확인'):visible",
        ]
        for s in steps:
            try:
                self._page.locator(s).first.click(timeout=5000)
            except Exception:
                pass
        return True

    def _visible(self, selector: str, timeout: int = 4000) -> bool:
        try:
            self._page.wait_for_selector(selector, timeout=timeout, state="visible")
            return True
        except Exception:
            return False

    # ── 세션 연장 ──
    def extend_session(self) -> bool:
        """'로그인 연장' 버튼을 눌러 세션을 10분 연장. 성공 시 True.

        재로그인(중복 로그인 팝업 등으로 실패)을 피하기 위한 기본 유지 방식.
        버튼이 현재 화면에 없으면 False (호출측이 재로그인으로 폴백).
        """
        btn_sel = (self._cfg["selectors"].get("session", {}) or {}).get(
            "extend_btn") or "button:has-text('로그인 연장')"
        if not self._visible(btn_sel, timeout=2000):
            return False
        try:
            self._page.click(btn_sel, timeout=3000)
            return True
        except Exception:
            return False

    # ── 검색 (페이지네이션) ──
    def search(self, company_name: str) -> list[dict]:
        self._delay()
        sel = self._cfg["selectors"]["search"]
        self._open_search(company_name)

        out: list[dict] = []
        for row in self._each_result_row(sel):
            name = _text(row, sel["result_company_name"])
            if not name:
                continue
            out.append({
                "회사명": name,
                "사업자번호": _text(row, sel["result_biz_no"]),
                "대표자명": _text(row, sel["result_ceo"]),
                "주소": _text(row, sel["result_address"]),
            })
        return out

    def _open_search(self, company_name: str) -> None:
        """검색창을 확보한 뒤 회사명을 입력하고 검색을 실행.

        검색 URL 경로 토큰이 세션마다 바뀔 수 있으므로, 현재 페이지에 검색창이
        있으면 그대로 쓰고, 없으면 search_url → base_url 순으로 이동해 확보한다.
        입력 상호의 (주)/주식회사 등 법인격 표기는 검색 정확도를 위해 제거한다.
        """
        sel = self._cfg["selectors"]["search"]
        q = sel["query_input"]
        company_name = _search_term(company_name) or company_name
        if not self._search_box_ready(q):
            for url in (self._cfg["site"].get("search_url"),
                        self._cfg["site"].get("base_url")):
                if not url:
                    continue
                self._page.goto(url)
                if self.is_login_page():
                    raise LoginRequired()
                if self._search_box_ready(q):
                    break
        if not self._search_box_ready(q):
            raise CollectorError("검색창을 찾지 못함")

        self._page.fill(q, company_name)
        # SPA 검색 실행: 검색 아이콘 클릭 우선, 실패 시 Enter
        btn = self._page.query_selector(sel.get("submit_btn") or "")
        if btn:
            try:
                btn.click()
                return
            except Exception:
                pass
        self._page.press(q, "Enter")

    def _search_box_ready(self, selector: str, timeout: int = 3000) -> bool:
        try:
            self._page.wait_for_selector(selector, timeout=timeout, state="visible")
            return True
        except Exception:
            return False

    def _each_result_row(self, sel):
        """결과 표의 행을 페이지네이션 한도까지 순회하며 yield."""
        max_pages = int(self._cfg.get("timing", {}).get("max_search_pages", 1))
        next_sel = sel.get("next_page_btn") or ""
        for page_num in range(1, max(1, max_pages) + 1):
            try:
                self._page.wait_for_selector(sel["result_rows"], timeout=5000)
            except Exception:
                return
            for row in self._page.query_selector_all(sel["result_rows"]):
                yield row
            if not next_sel or page_num >= max_pages:
                return
            nxt = self._page.query_selector(next_sel)
            if not nxt:
                return
            self._delay()
            try:
                nxt.click()
            except Exception:
                return

    # ── 상세 파싱 ──
    # 상세는 검색 결과에서 '개요' 클릭 시 같은 페이지에 인라인 렌더된다(href 없음).
    def fetch_detail(self, candidate: dict, finance_years: int = 1) -> dict:
        self._delay()
        self._open_detail(candidate)
        return self._parse_detail(candidate)

    def _open_detail(self, candidate: dict) -> None:
        sel = self._cfg["selectors"]["search"]
        dsel = self._cfg["selectors"]["detail"]
        target_biz = _digits(candidate.get("사업자번호"))
        target_name = _norm_name(candidate.get("회사명"))

        # 상세 진입 전 항상 새로 검색해 깨끗한 결과 목록에서 대상 행을 찾는다.
        # (직전에 상세를 본 뒤 목록이 사라지거나 어긋나 '행 못 찾음'이 나던 문제 방지)
        self._open_search(candidate.get("회사명") or "")

        row = None
        for cand_row in self._each_result_row(sel):
            rb = _digits(_text(cand_row, sel["result_biz_no"]))
            rn = _norm_name(_text(cand_row, sel["result_company_name"]))
            if target_biz and rb == target_biz:
                row = cand_row
                break
            if not target_biz and rn == target_name:
                row = cand_row
                break
        if row is None:
            raise CollectorError("상세 진입 대상 행을 찾지 못함")

        btn = row.query_selector(sel["result_detail_btn"])
        if btn is None:
            raise CollectorError("'개요' 버튼을 찾지 못함")
        btn.click()
        try:
            self._page.wait_for_selector(dsel["ready_marker"], timeout=10000)
        except Exception as e:
            if self.is_login_page():
                raise LoginRequired()
            raise CollectorError(f"상세 로딩 실패: {e}")
        if self.is_login_page():
            raise LoginRequired()

    def _parse_detail(self, candidate: dict) -> dict:
        dsel = self._cfg["selectors"]["detail"]
        data = self._page.evaluate(_DETAIL_JS, {
            "card": dsel["finance_card"],
            "label": dsel["finance_label"],
            "value": dsel["finance_value"],
            "symbol": dsel["finance_symbol"],
            "addr": dsel["address_value"],
            "settle": dsel.get("settlement_text", "결산 일자"),
        })
        basic = data.get("basic", {})
        fin = data.get("fin", {})

        def fin_amt(key):
            e = fin.get(key)
            return amount_to_millions(e["v"], e["u"]) if e else None

        out = {
            "회사명": candidate.get("회사명"),
            "사업자번호": candidate.get("사업자번호"),
            "대표자": _lookup(basic, dsel["label_ceo"]),
            "주소": data.get("address") or candidate.get("주소"),
            "업종": _lookup(basic, dsel["label_industry"]),
            "설립일": _lookup(basic, dsel["label_founded"]),
            "대표번호": None,
            "종업원수": _lookup(basic, dsel["label_employees"]),
            "매출액": fin_amt("매출액"),
            "영업이익": fin_amt("영업이익"),
            "당기순이익": fin_amt("당기순이익"),
            "신용등급": None,   # '개요'에는 없음(신용/등급 탭). 미제공으로 기록됨.
            "결산일자": _first_date(data.get("settlement")),
        }
        return out

    def is_login_page(self) -> bool:
        marker = self._cfg["selectors"]["login_page_markers"]
        url_hint = marker.get("url_contains")
        dom_hint = marker.get("dom_marker")
        if url_hint and url_hint in self._page.url:
            return True
        if dom_hint and self._page.query_selector(dom_hint):
            return True
        return False

    def _delay(self) -> None:
        t = self._cfg["timing"]
        time.sleep(random.uniform(
            float(t.get("request_delay_min_sec", 1.0)),
            float(t.get("request_delay_max_sec", 3.0)),
        ))


def _text(el, css: str) -> str | None:
    node = el.query_selector(css)
    return (node.inner_text().strip() if node else None) or None


def _digits(s) -> str:
    return re.sub(r"\D", "", s or "")


# 검색어에서 법인격 표기만 제거(핵심 상호로 검색해 적중률↑). 공백은 유지.
_SEARCH_STRIP = re.compile(
    r"㈜|\(\s*(?:주|유|재|사)\s*\)"
    r"|주식회사|유한회사|유한책임회사|합자회사|합명회사|재단법인|사단법인|의료법인|학교법인")


def _search_term(name) -> str:
    s = _SEARCH_STRIP.sub(" ", name or "")
    return re.sub(r"\s+", " ", s).strip()


# 이름 비교용 정규화(법인격 표기·기호 제거). matcher._norm_company와 동일 취지.
_NAME_STRIP = re.compile(
    r"㈜|\(\s*(?:주|유|재|사)\s*\)|주식회사|유한회사|[\s()\[\]·.,\-_/]")


def _norm_name(s) -> str:
    return _NAME_STRIP.sub("", s or "").lower()


def _lookup(basic: dict, label: str) -> str | None:
    """기본정보 라벨→값 dict에서 라벨(부분일치 허용)로 값을 찾는다."""
    if not label:
        return None
    v = basic.get(label)
    if v is None:
        v = next((val for k, val in basic.items() if label in k), None)
    if v is None:
        return None
    v = v.strip()
    return v or None


_DATE_IN = re.compile(r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}")


def _first_date(text) -> str | None:
    if not text:
        return None
    m = _DATE_IN.search(str(text))
    return m.group(0) if m else None


# 상세(개요) 페이지 파싱 JS.
#  - 기본정보: th(scope=row) 라벨 → 다음 td 값
#  - 재무: KPI 카드 라벨 → 값(단위 심볼 분리)
#  - 주소/결산일자
_DETAIL_JS = """
(s) => {
  const basic = {};
  document.querySelectorAll('th[scope="row"]').forEach(th => {
    const td = th.nextElementSibling;
    if (td && td.tagName === 'TD') basic[th.innerText.trim()] = td.innerText.trim();
  });
  const fin = {};
  document.querySelectorAll(s.card).forEach(card => {
    const labelEl = card.querySelector(s.label);
    const valEl = card.querySelector(s.value);
    if (!labelEl || !valEl) return;
    const symEl = valEl.querySelector(s.symbol);
    const unit = symEl ? symEl.innerText.trim() : "";
    let v = valEl.innerText.trim();
    if (unit) v = v.replace(unit, "").trim();
    fin[labelEl.innerText.trim()] = { v: v, u: unit };
  });
  const addrEl = document.querySelector(s.addr);
  const address = addrEl ? addrEl.innerText.trim() : "";
  let settlement = "";
  for (const el of document.querySelectorAll('span, div')) {
    const t = (el.innerText || "").trim();
    if (t.indexOf(s.settle) === 0) { settlement = t; break; }
  }
  return { basic: basic, fin: fin, address: address, settlement: settlement };
}
"""


# ── 모의 수집기 (UI/파이프라인 검증용) ────────────────────────────────────────

_MOCK_DB = {
    "삼성전자": [{
        "회사명": "삼성전자(주)", "사업자번호": "1248100998", "대표자명": "한종희",
        "주소": "경기 수원시 영통구",
        "_detail": {
            "업종": "반도체 제조업", "설립일": "1969-01-13", "대표번호": "031-200-1114",
            "종업원수": "125819", "매출액": "258900000", "영업이익": "6566900",
            "당기순이익": "15486800", "신용등급": "AAA",
        },
        "_finance_years": [
            {"연도": "2025", "매출액": "258900000", "영업이익": "6566900", "당기순이익": "15486800"},
            {"연도": "2024", "매출액": "302231000", "영업이익": "32827300", "당기순이익": "26970300"},
            {"연도": "2023", "매출액": "279604800", "영업이익": "43376800", "당기순이익": "55654100"},
        ],
    }],
    "현대자동차": [{
        "회사명": "현대자동차(주)", "사업자번호": "1018114965", "대표자명": "장재훈",
        "주소": "서울 서초구",
        "_detail": {
            "업종": "자동차 제조업", "설립일": "1967-12-29", "대표번호": "02-3464-1114",
            "종업원수": "75091", "매출액": "162663700", "영업이익": "15126700",
            "당기순이익": "12270200", "신용등급": "AA+",
        },
        "_finance_years": [
            {"연도": "2025", "매출액": "162663700", "영업이익": "15126700", "당기순이익": "12270200"},
            {"연도": "2024", "매출액": "142523000", "영업이익": "9824400", "당기순이익": "7991800"},
            {"연도": "2023", "매출액": "117610000", "영업이익": "6679000", "당기순이익": "5693400"},
        ],
    }],
}


class MockCollector:
    """사이트 접근 없이 GUI/파이프라인을 검증할 수 있는 가짜 수집기."""

    def __init__(self, config: dict | None = None):
        self._logged_in = False

    def login(self, user_id: str, password: str) -> None:
        if not user_id or not password:
            raise CollectorError("ID/PW 누락")
        time.sleep(0.2)
        self._logged_in = True

    def search(self, company_name: str) -> list[dict]:
        time.sleep(0.1)
        for key, rows in _MOCK_DB.items():
            if key in company_name or company_name in key:
                return [{k: v for k, v in r.items() if not k.startswith("_")} | {"_detail_link": key}
                        for r in rows]
        return []

    def fetch_detail(self, candidate: dict, finance_years: int = 1) -> dict:
        time.sleep(0.1)
        key = candidate.get("_detail_link")
        for k, rows in _MOCK_DB.items():
            if k == key:
                base = {kk: vv for kk, vv in rows[0].items() if not kk.startswith("_")}
                base["대표자"] = base.pop("대표자명", None)
                base.update(rows[0]["_detail"])
                if finance_years > 1:
                    base["재무_연도별"] = rows[0].get("_finance_years", [])[:finance_years]
                return base
        raise CollectorError("상세 정보 없음")

    def extend_session(self) -> bool:
        return self._logged_in

    def is_login_page(self) -> bool:
        return not self._logged_in

    def close(self) -> None:
        self._logged_in = False
