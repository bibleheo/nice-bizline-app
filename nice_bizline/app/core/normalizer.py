"""필드 정규화 - 금액, 날짜, 사업자번호 통일."""
from __future__ import annotations

import re
from datetime import datetime


_NUM_RE = re.compile(r"[^\d\-]")
_DATE_PATTERNS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d", "%Y년 %m월 %d일")


def normalize_amount(value) -> int | None:
    """금액 문자열에서 숫자만 추출. '1,234백만원' → 1234. 단위는 별도 헤더에 명시."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    # 음수 부호 보존, 그 외 비숫자 제거
    cleaned = _NUM_RE.sub("", s)
    if cleaned in ("", "-"):
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def normalize_date(value) -> str | None:
    """날짜를 YYYY-MM-DD로 통일."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s  # 형식 불명이면 원본 유지


def normalize_biz_number(value) -> str | None:
    """사업자번호 000-00-00000 형식 통일."""
    if value is None or value == "":
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 10:
        return str(value).strip()  # 형식 이상이면 원본
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def normalize_record(raw: dict) -> dict:
    """수집기에서 받은 원본 dict를 정규화."""
    out = dict(raw)
    if "사업자번호" in out:
        out["사업자번호"] = normalize_biz_number(out["사업자번호"])
    if "설립일" in out:
        out["설립일"] = normalize_date(out["설립일"])
    for key in ("매출액", "영업이익", "당기순이익", "종업원수"):
        if key in out:
            out[key] = normalize_amount(out[key])
    return out
