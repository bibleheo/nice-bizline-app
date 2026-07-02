"""실제 모드 시험 실행 스크립트 (웹 UI/포트 없이 터미널에서 바로).

사용법 (저장소 루트에서):
    python trial.py                 # examples/샘플_입력.xlsx 로 실제 모드
    python trial.py 내파일.xlsx      # 다른 입력 파일로
    python trial.py --mock          # 모의 모드(사이트 접속 없이 흐름만)

ID/PW는 실행 중 입력하며, PW는 화면에 표시되지 않습니다(getpass).
로그가 터미널에 그대로 찍히니, 막히는 지점을 바로 확인할 수 있습니다.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nice_bizline.app.core.collector import MockCollector, NiceBizlineCollector
from nice_bizline.app.core.pipeline import PipelineOptions, run_pipeline
from nice_bizline.app.excelio.reader import read_company_list
from nice_bizline.app.excelio.writer import write_results


def main() -> None:
    args = [a for a in sys.argv[1:]]
    mock = "--mock" in args
    args = [a for a in args if a != "--mock"]
    inp = args[0] if args else str(_ROOT / "examples" / "샘플_입력.xlsx")

    cfg = yaml.safe_load((_ROOT / "nice_bizline" / "config.yaml").read_text(encoding="utf-8"))

    companies = read_company_list(inp)
    print(f"\n입력 파일: {inp}")
    print(f"입력 {len(companies)}건: {[c.get('회사명') for c in companies]}\n")
    if not companies:
        print("입력이 비었습니다. 파일을 확인하세요.")
        return

    if mock:
        print("=== 모의(mock) 모드 ===")
        collector = MockCollector(cfg)
        uid, pw = "mock", "mock"
    else:
        print("=== 실제 모드 (headless 브라우저) ===")
        uid = input("나이스비즈라인 ID: ").strip()
        pw = getpass.getpass("나이스비즈라인 PW (입력해도 화면에 안 보입니다): ")
        print("\n브라우저 시작 중... (playwright chromium)\n")
        collector = NiceBizlineCollector(cfg)

    opts = PipelineOptions(
        user_id=uid, password=pw, companies=companies,
        finance_years=1, input_path=inp,
    )

    state = None
    for ev in run_pipeline(collector, cfg, opts):
        t = ev.get("type")
        if t == "log":
            print(f"  [{ev['level']:>5}] {ev['message']}")
        elif t == "progress":
            print(f">>> {ev['current']}/{ev['total']}  {ev['name']}")
        elif t == "done":
            state = ev["state"]

    if state is not None:
        outp = str(Path(inp).with_suffix("")) + "_결과.xlsx"
        write_results(
            outp, records=state.records, unfound=state.unfound,
            ambiguous=state.ambiguous, summary=state.summary, finance_years=1,
        )
        print("\n" + "=" * 50)
        print("요약:", state.summary)
        print("결과 저장:", outp)
        print("=" * 50)


if __name__ == "__main__":
    main()
