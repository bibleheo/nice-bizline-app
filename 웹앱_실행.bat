@echo off
REM ============================================================
REM  나이스비즈라인 조회 - 로컬 웹앱 실행 (더블클릭)
REM  1) 파이썬 확인  2) 패키지/브라우저 설치  3) 웹앱 실행
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM ── 파이썬 찾기 (python 또는 py 런처) ──
set "PY=python"
%PY% --version >nul 2>&1
if errorlevel 1 (
    set "PY=py -3"
    %PY% --version >nul 2>&1
)
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [오류] Python 을 찾을 수 없습니다.
    echo   1. https://www.python.org/downloads/ 에서 Python 3.12 설치
    echo   2. 설치 시 "Add python.exe to PATH" 체크 필수!
    echo.
    pause
    exit /b 1
)
echo 사용 파이썬:
%PY% --version

echo.
echo [1/3] 패키지 설치/확인... (처음 한 번만 오래 걸립니다)
%PY% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [오류] 패키지 설치 실패. 인터넷 연결과 Python 버전(3.11~3.12 권장)을 확인하세요.
    pause
    exit /b 1
)

echo [2/3] 크롬 브라우저 설치/확인... (처음 한 번만, 이후엔 즉시 통과)
%PY% -m playwright install chromium

echo [3/3] 웹앱 시작 - 잠시 후 브라우저가 자동으로 열립니다.
echo        종료: 이 검은 창을 닫으세요.
echo.
%PY% -m streamlit run nice_bizline/app/web/streamlit_app.py

pause
endlocal
