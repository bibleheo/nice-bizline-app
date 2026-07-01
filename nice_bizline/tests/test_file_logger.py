"""파일 로거 단위 테스트."""
import logging
import os

from nice_bizline.app.core import file_logger


def test_setup_creates_file(tmp_path):
    inp = str(tmp_path / "고객사목록.xlsx")
    logger, log_path = file_logger.setup_run_logger(inp)
    try:
        assert os.path.exists(log_path)
        assert log_path.startswith(str(tmp_path / "고객사목록_나이스비즈라인로그_"))
        assert log_path.endswith(".log")
        assert isinstance(logger, logging.Logger)
    finally:
        file_logger.close(logger)


def test_write_levels(tmp_path):
    inp = str(tmp_path / "in.xlsx")
    logger, log_path = file_logger.setup_run_logger(inp)
    file_logger.write(logger, "info", "정보 메시지")
    file_logger.write(logger, "warn", "경고 메시지")
    file_logger.write(logger, "error", "오류 메시지")
    file_logger.write(logger, "unknown", "기본값으로 INFO 처리")
    file_logger.close(logger)

    with open(log_path, encoding="utf-8") as f:
        content = f.read()
    assert "[INFO]  정보 메시지" in content
    assert "[WARNING]  경고 메시지" in content
    assert "[ERROR]  오류 메시지" in content
    assert "기본값으로 INFO 처리" in content


def test_setup_called_twice_does_not_duplicate(tmp_path):
    """동일 logger를 두 번 setup해도 핸들러가 중복되지 않는다."""
    inp = str(tmp_path / "in.xlsx")
    logger1, _ = file_logger.setup_run_logger(inp)
    # 의도적으로 같은 분단위 timestamp가 나올 가능성이 있어,
    # 다른 logger 객체가 보장되진 않지만 핸들러 누적은 막아야 함
    handler_count = len(logger1.handlers)
    logger2, _ = file_logger.setup_run_logger(inp)
    if logger1 is logger2:
        assert len(logger2.handlers) == handler_count  # 누적되지 않음
    file_logger.close(logger1)
    file_logger.close(logger2)


def test_close_removes_handlers(tmp_path):
    inp = str(tmp_path / "in.xlsx")
    logger, _ = file_logger.setup_run_logger(inp)
    assert len(logger.handlers) >= 1
    file_logger.close(logger)
    assert len(logger.handlers) == 0
