"""입력 엑셀 읽기 - 회사명/사업자번호/대표자명 컬럼을 유연하게 매칭."""
from __future__ import annotations

import re
import openpyxl


_NORMALIZE = re.compile(r"[\s()\[\]]")


def _norm(s: str) -> str:
    return _NORMALIZE.sub("", str(s)).lower()


_HEADER_ALIASES = {
    "회사명": {"회사명", "상호", "회사", "기업명", "companyname", "company"},
    "사업자번호": {"사업자번호", "사업자등록번호", "사업자등록", "bizno", "businessno"},
    "대표자명": {"대표자명", "대표자", "대표", "ceo", "representative"},
}


def _match_header(cell_value) -> str | None:
    n = _norm(cell_value or "")
    if not n:
        return None
    for canonical, aliases in _HEADER_ALIASES.items():
        if any(_norm(a) == n for a in aliases):
            return canonical
    return None


def read_company_list(path: str) -> list[dict]:
    """첫 시트 1행을 헤더로 보고, 2행부터 데이터를 읽어 dict 리스트로 반환.

    회사명은 필수. 사업자번호/대표자명은 있으면 매칭 정확도 향상.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.active

    rows = ws.iter_rows(values_only=True)
    header_row = next(rows, None)
    if not header_row:
        wb.close()
        return []

    col_map: dict[int, str] = {}
    for idx, val in enumerate(header_row):
        canon = _match_header(val)
        if canon:
            col_map[idx] = canon

    if "회사명" not in col_map.values():
        # 헤더 매칭 실패 시 첫 컬럼을 회사명으로 간주 (단순 1열 입력 호환)
        col_map = {0: "회사명"}

    out: list[dict] = []
    for row in rows:
        rec: dict = {}
        for idx, key in col_map.items():
            if idx < len(row) and row[idx] is not None:
                rec[key] = str(row[idx]).strip()
        if rec.get("회사명"):
            out.append(rec)
    wb.close()
    return out
