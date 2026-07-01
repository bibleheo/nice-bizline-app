"""나이스비즈라인 기업정보 조회 자동화 - 앱 진입점.

사용법:
  python -m nice_bizline.main           # 일반 모드 (Playwright 필요)
  python -m nice_bizline.main --mock    # 모의 모드 (사이트 접근 없이 UI/파이프라인 검증)

명세 v1. config.yaml의 셀렉터는 실제 사이트 DOM을 확인한 뒤 채워야 합니다.
"""
from __future__ import annotations

import argparse
import os
import sys

import yaml

from nice_bizline.app.ui.main_window import MainWindow


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="나이스비즈라인 자동화")
    parser.add_argument("--config", default=None, help="config.yaml 경로")
    parser.add_argument("--mock", action="store_true",
                        help="사이트 접근 없이 모의 데이터로 실행")
    args = parser.parse_args()

    cfg_path = args.config or os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(cfg_path):
        print(f"[오류] config.yaml을 찾을 수 없습니다: {cfg_path}", file=sys.stderr)
        return 1

    config = _load_config(cfg_path)
    app = MainWindow(config, mock=args.mock)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
