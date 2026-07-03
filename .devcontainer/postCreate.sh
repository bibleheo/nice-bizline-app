#!/usr/bin/env bash
# Codespace 생성 시 1회 자동 실행: 패키지 + 브라우저 + 시스템 라이브러리 설치
set -e

echo "[1/3] 파이썬 패키지 설치..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "[2/3] 크롬 실행용 시스템 라이브러리 설치 (libatk 등)..."
sudo "$(which python)" -m playwright install-deps chromium

echo "[3/3] Playwright 크롬 설치..."
python -m playwright install chromium

echo "설치 완료. 웹앱 실행:  python -m streamlit run nice_bizline/app/web/streamlit_app.py"
