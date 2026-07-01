"""검색 결과 페이지네이션 - config 값 인식 동작 확인."""
import os
import yaml

from nice_bizline.app.core.collector import MockCollector


def test_config_has_max_search_pages():
    with open(os.path.join(os.path.dirname(__file__), "..", "config.yaml"),
              encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert "max_search_pages" in cfg["timing"]
    assert isinstance(cfg["timing"]["max_search_pages"], int)


def test_config_has_next_page_selector_key():
    """next_page_btn 키가 selectors.search 아래에 존재해야 한다(빈 값이어도)."""
    with open(os.path.join(os.path.dirname(__file__), "..", "config.yaml"),
              encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert "next_page_btn" in cfg["selectors"]["search"]


def test_mock_collector_unchanged_by_pagination_settings():
    """MockCollector는 단일 페이지로 동작 - 페이지네이션 설정과 무관."""
    with open(os.path.join(os.path.dirname(__file__), "..", "config.yaml"),
              encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    c = MockCollector(cfg)
    c.login("u", "p")
    rows = c.search("삼성전자")
    assert len(rows) == 1
