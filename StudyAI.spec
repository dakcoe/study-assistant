# PyInstaller 빌드 설정 — `.venv/bin/python -m PyInstaller StudyAI.spec` 로 빌드.
#
# .app 번들로 묶는 이유: 터미널에서 python을 직접 띄우면 macOS가 권한 주체를
# 부모 앱(터미널/에디터)으로 보기 때문에 마이크 권한 요청이 뜨지 않는다.
# 번들 안에 실행 바이너리를 넣어야 앱이 자기 이름으로 권한을 받는다.

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # ScreenCaptureKit 헬퍼. 이게 있어야 가상 오디오 장치 없이 앱 소리를 잡는다.
    # 아이콘 폰트(Material Icons, Apache-2.0). 번들에 넣고 실행할 때 이 프로세스에만
    # 등록하므로, 앱을 받은 사람 컴퓨터에 폰트를 설치할 필요가 없다.
    # assets/ 에 아이콘 폰트와 도움말 그림이 함께 들어 있다.
    datas=[("audio_capture", "."), ("assets", "assets")],
    hiddenimports=["sounddevice", "customtkinter"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pyinstaller", "PyInstaller"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StudyAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 터미널 창 안 뜨게
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StudyAI",
)

app = BUNDLE(
    coll,
    name="Study AI.app",
    icon="assets/AppIcon.icns",
    bundle_identifier="com.superbleo.studyai",
    info_plist={
        # 이게 없으면 macOS가 영어 앱으로 보고 저장 패널과 시스템 폴더 이름을
        # (서류/데스크탑 대신 Documents/Desktop) 영어로 그린다.
        # Resources/ko.lproj 도 있어야 실제로 한국어로 인식한다 (build.sh에서 만든다).
        "CFBundleDevelopmentRegion": "ko_KR",
        "CFBundleLocalizations":   ["ko", "en"],
        "CFBundleName":            "Study AI",
        "CFBundleDisplayName":     "Study AI",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion":         "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion":  "11.0",
        # 이 두 개가 없으면 macOS가 권한 요청 자체를 띄우지 않는다
        "NSMicrophoneUsageDescription":
            "수업 중 말소리를 받아 적기 위해 마이크를 사용합니다.",
        "NSAppleEventsUsageDescription":
            "복사한 내용을 어느 앱에서 가져왔는지 확인하기 위해 사용합니다.",
    },
)
