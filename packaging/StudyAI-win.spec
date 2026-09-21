# Windows 빌드 설정 — Windows에서 `python -m PyInstaller StudyAI-win.spec`.
#
# 맥과 다른 점만 적는다.
#   - Swift 헬퍼(audio_capture)가 없다. 시스템 소리는 WASAPI 루프백(soundcard)으로 잡는다.
#   - .app 번들 대신 폴더 하나(dist/StudyAI/)가 나온다. 그 안의 StudyAI.exe가 실행 파일.
#   - 권한 설명 키(Info.plist)는 Windows에 해당 사항이 없다.

# 경로는 이 파일 위치(SPECPATH) 기준으로 잡는다. 어느 폴더에서 실행하든 같다.
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "app", "main.py")],
    pathex=[os.path.join(ROOT, "app")],
    binaries=[],
    datas=[(os.path.join(ROOT, "assets"), "assets")],
    hiddenimports=["sounddevice", "customtkinter", "soundcard"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pyinstaller", "PyInstaller"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StudyAI",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # 콘솔 창 안 뜨게
    icon=os.path.join(ROOT, "assets", "AppIcon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StudyAI",
)
