@echo off
REM ============================================================
REM  나이스비즈라인 조회 - 웹 UI 실행 바로가기
REM  더블클릭하면 필요한 패키지를 설치하고 Streamlit 웹앱을 엽니다.
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo [1/2] 필요한 패키지 확인/설치 중... (처음 한 번만 시간이 걸립니다)
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo [오류] 패키지 설치에 실패했습니다.
    echo   - Python 이 설치되어 있는지 확인하세요 ^(3.11 권장^).
    echo   - 명령어: python --version
    echo.
    pause
    exit /b 1
)

echo.
echo [2/2] 웹앱을 시작합니다. 잠시 후 브라우저가 자동으로 열립니다.
echo       종료하려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo.
python -m streamlit run nice_bizline\app\web\streamlit_app.py

pause
endlocal
