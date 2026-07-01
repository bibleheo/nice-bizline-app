import openpyxl

from nice_bizline.app.excelio.reader import read_company_list
from nice_bizline.app.excelio.writer import write_results


def _make_input(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


class TestReader:
    def test_standard_headers(self, tmp_path):
        p = tmp_path / "in.xlsx"
        _make_input(p, [
            ["회사명", "사업자번호", "대표자명"],
            ["삼성전자", "1248100998", "한종희"],
            ["현대자동차", None, None],
        ])
        rows = read_company_list(str(p))
        assert len(rows) == 2
        assert rows[0] == {"회사명": "삼성전자", "사업자번호": "1248100998", "대표자명": "한종희"}
        assert rows[1] == {"회사명": "현대자동차"}

    def test_alias_headers(self, tmp_path):
        """한글 alias (상호/사업자등록번호/대표) 도 인식."""
        p = tmp_path / "in.xlsx"
        _make_input(p, [
            ["상호", "사업자등록번호", "대표"],
            ["X사", "1234567890", "홍길동"],
        ])
        rows = read_company_list(str(p))
        assert rows[0]["회사명"] == "X사"
        assert rows[0]["사업자번호"] == "1234567890"
        assert rows[0]["대표자명"] == "홍길동"

    def test_upche_myeong_alias(self, tmp_path):
        """'업체명' 도 회사명으로 인식."""
        p = tmp_path / "in.xlsx"
        _make_input(p, [
            ["업체명", "사업자번호"],
            ["가나건설", "1112233445"],
        ])
        rows = read_company_list(str(p))
        assert rows[0]["회사명"] == "가나건설"
        assert rows[0]["사업자번호"] == "1112233445"

    def test_address_column_captured(self, tmp_path):
        """'주소'(및 alias '소재지') 컬럼을 캡처해 매칭에 활용."""
        p = tmp_path / "in.xlsx"
        _make_input(p, [
            ["회사명", "소재지"],
            ["한빛엔지니어링", "서울특별시 강남구 테헤란로 1"],
        ])
        rows = read_company_list(str(p))
        assert rows[0]["회사명"] == "한빛엔지니어링"
        assert rows[0]["주소"] == "서울특별시 강남구 테헤란로 1"

    def test_no_header_falls_back_to_first_column(self, tmp_path):
        """헤더 인식 실패 시 1열을 회사명으로 처리."""
        p = tmp_path / "in.xlsx"
        _make_input(p, [
            ["abcdefg"],   # 매칭 안 됨 → 첫 데이터로 간주되지 않고 헤더 후보
            ["회사1"],
            ["회사2"],
        ])
        rows = read_company_list(str(p))
        # 헤더 매칭 실패 → 첫 컬럼을 회사명으로 보고 데이터 행만 채택 (헤더 행 1개는 건너뜀)
        assert all("회사명" in r for r in rows)
        # 첫 행이 헤더로 소비되었으므로 2개가 남음
        assert len(rows) == 2

    def test_skips_empty_company(self, tmp_path):
        p = tmp_path / "in.xlsx"
        _make_input(p, [
            ["회사명"],
            ["A"],
            [None],
            [""],
            ["B"],
        ])
        rows = read_company_list(str(p))
        assert [r["회사명"] for r in rows] == ["A", "B"]


class TestWriter:
    def test_creates_four_sheets(self, tmp_path):
        p = tmp_path / "out.xlsx"
        write_results(str(p), records=[], unfound=[], ambiguous=[], summary={})
        wb = openpyxl.load_workbook(p)
        assert wb.sheetnames == ["결과", "미발견·오류", "확인필요", "실행로그"]

    def test_writes_record_values(self, tmp_path):
        p = tmp_path / "out.xlsx"
        write_results(
            str(p),
            records=[{
                "회사명": "삼성전자", "대표자": "한종희", "사업자번호": "124-81-00998",
                "조회상태": "성공", "매출액(백만원)": 258900000,
            }],
            unfound=[{"회사명": "없는회사", "조회상태": "미발견", "사유": "검색 0건"}],
            ambiguous=[{"회사명": "동명", "채택후보": "A", "다른후보들": "B; C", "사유": "동점"}],
            summary={"total": 3, "success": 1, "not_found": 1, "ambiguous": 1, "error": 0,
                     "started_at": "2026-01-01 00:00:00"},
        )
        wb = openpyxl.load_workbook(p)
        ws = wb["결과"]
        # 헤더 + 1 데이터 행
        assert ws.cell(1, 1).value == "회사명"
        assert ws.cell(2, 1).value == "삼성전자"
        # 미발견 시트
        ws2 = wb["미발견·오류"]
        assert ws2.cell(2, 1).value == "없는회사"
        # 확인필요 시트
        ws3 = wb["확인필요"]
        assert ws3.cell(2, 2).value == "A"
        # 실행로그 시트에 통계 기록
        ws4 = wb["실행로그"]
        labels = [ws4.cell(r, 1).value for r in range(2, 9)]
        assert "총 건수" in labels
        assert "성공" in labels
