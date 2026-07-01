# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - 나이스비즈라인 자동화 데스크톱 앱.

빌드 (Windows에서 실행 권장):
  python -m pip install pyinstaller
  python -m pip install -r requirements.txt
  python -m playwright install chromium
  pyinstaller nice_bizline.spec --clean --noconfirm

산출물:
  dist/나이스비즈라인_조회/                          ← 폴더 배포
  dist/나이스비즈라인_조회/나이스비즈라인_조회.exe   ← 실행 파일
  dist/나이스비즈라인_조회/_internal/config.yaml     ← 설정 파일 (셀렉터 수정 가능)

Playwright 브라우저는 별도 설치가 필요합니다. 첫 실행 시 사용자가
`python -m playwright install chromium`을 실행해야 하거나,
PLAYWRIGHT_BROWSERS_PATH 환경변수로 사내 공용 경로를 지정하세요.
"""
import os

block_cipher = None

# config.yaml은 사용자가 셀렉터를 수정해야 하므로 _internal에 함께 배치
datas = [
    ('nice_bizline/config.yaml', 'nice_bizline'),
]

# 동적 import 명시 (keyring 백엔드는 platform별로 런타임 결정)
hidden_imports = [
    'keyring.backends.Windows',
    'keyring.backends.macOS',
    'keyring.backends.SecretService',
    'keyring.backends.kwallet',
]

a = Analysis(
    ['nice_bizline/main.py'],
    pathex=['.'],            # nice_bizline 패키지가 보이도록
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='나이스비즈라인_조회',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # Windows: GUI 앱이므로 콘솔 창 숨김
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='나이스비즈라인_조회',
)
