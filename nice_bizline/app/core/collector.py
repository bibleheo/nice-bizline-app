"""나이스비즈라인 수집기.

- BaseCollector: 인터페이스 (공식 API 전환 시 교체 지점)
- NiceBizlineCollector: Playwright 기반 수집기
- MockCollector: 사이트 접근 없이 파이프라인 검증용

실제 사용 전 config.yaml의 selectors를 실제 페이지 DOM으로 채워야 합니다.
"""
from __future__ import annotations

import random
import time
from typing import Protocol


class CollectorError(Exception):
    pass


class LoginRequired(CollectorError):
    """세션 만료로 로그인 페이지로 튕긴 경우."""


class BaseCollector(Protocol):
    def login(self, user_id: str, password: str) -> None: ...
    def search(self, company_name: str) -> list[dict]: ...
    def fetch_detail(self, candidate: dict, finance_years: int = 1) -> dict: ...
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
        self._page.fill(sel["id_input"], user_id)
        self._page.fill(sel["pw_input"], password)
        self._page.click(sel["submit_btn"])
        try:
            self._page.wait_for_selector(sel["logged_in_marker"])
        except Exception as e:
            raise CollectorError(f"로그인 실패: {e}")

    # ── 검색 (페이지네이션) ──
    def search(self, company_name: str) -> list[dict]:
        self._delay()
        sel = self._cfg["selectors"]["search"]
        max_pages = int(self._cfg.get("timing", {}).get("max_search_pages", 1))
        next_sel = sel.get("next_page_btn") or ""

        self._page.goto(self._cfg["site"]["search_url"])
        if self.is_login_page():
            raise LoginRequired()
        self._page.fill(sel["query_input"], company_name)
        self._page.click(sel["submit_btn"])

        out: list[dict] = []
        for page_num in range(1, max(1, max_pages) + 1):
            try:
                self._page.wait_for_selector(sel["result_rows"], timeout=5000)
            except Exception:
                break

            for row in self._page.query_selector_all(sel["result_rows"]):
                out.append({
                    "회사명": _text(row, sel["result_company_name"]),
                    "사업자번호": _text(row, sel["result_biz_no"]),
                    "대표자명": _text(row, sel["result_ceo"]),
                    "주소": _text(row, sel["result_address"]),
                    "_detail_link": _attr(row, sel["result_link"], "href"),
                })

            # 다음 페이지: 셀렉터 없음/한도 도달/버튼 없음이면 종료
            if not next_sel or page_num >= max_pages:
                break
            next_btn = self._page.query_selector(next_sel)
            if not next_btn:
                break
            self._delay()
            try:
                next_btn.click()
            except Exception:
                break
        return out

    # ── 상세 파싱 ──
    def fetch_detail(self, candidate: dict, finance_years: int = 1) -> dict:
        self._delay()
        link = candidate.get("_detail_link")
        if not link:
            raise CollectorError("상세 페이지 링크 없음")
        if link.startswith("/"):
            link = self._cfg["site"]["base_url"].rstrip("/") + link
        self._page.goto(link)
        if self.is_login_page():
            raise LoginRequired()

        sel = self._cfg["selectors"]["detail"]
        out = {
            "회사명": _text_page(self._page, sel["company_name"]) or candidate.get("회사명"),
            "대표자": _text_page(self._page, sel["ceo"]),
            "사업자번호": _text_page(self._page, sel["biz_no"]) or candidate.get("사업자번호"),
            "주소": _text_page(self._page, sel["address"]) or candidate.get("주소"),
            "업종": _text_page(self._page, sel["industry"]),
            "설립일": _text_page(self._page, sel["founded"]),
            "대표번호": _text_page(self._page, sel["phone"]),
            "종업원수": _text_page(self._page, sel["employees"]),
            "매출액": _text_page(self._page, sel["sales"]),
            "영업이익": _text_page(self._page, sel["operating_profit"]),
            "당기순이익": _text_page(self._page, sel["net_income"]),
            "신용등급": _text_page(self._page, sel["credit_rating"]),
        }
        if finance_years > 1:
            out["재무_연도별"] = self._parse_financial_table(finance_years)
        return out

    def _parse_financial_table(self, n_years: int) -> list[dict]:
        """다년 재무표 파싱. 최신 연도부터 n_years개를 반환."""
        ft = self._cfg["selectors"]["detail"].get("financial_table") or {}
        rows_sel = ft.get("rows")
        if not rows_sel:
            return []
        rows = self._page.query_selector_all(rows_sel)
        out: list[dict] = []
        for row in rows:
            out.append({
                "연도": _text(row, ft.get("year", "")),
                "매출액": _text(row, ft.get("sales", "")),
                "영업이익": _text(row, ft.get("operating_profit", "")),
                "당기순이익": _text(row, ft.get("net_income", "")),
            })
            if len(out) >= n_years:
                break
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


def _attr(el, css: str, name: str) -> str | None:
    node = el.query_selector(css)
    return node.get_attribute(name) if node else None


def _text_page(page, css: str) -> str | None:
    node = page.query_selector(css)
    return (node.inner_text().strip() if node else None) or None


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

    def is_login_page(self) -> bool:
        return not self._logged_in

    def close(self) -> None:
        self._logged_in = False
