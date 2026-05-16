# PyInstaller スペックファイル。
# Windows 上で  pyinstaller suga.spec  を実行すると dist/SUGA.exe が生成される。
# ビルド前に scripts/build_frontend.sh 等でフロントを backend/app/static に
# 配置しておくこと。
# ruff: noqa
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("pdfplumber")
    + collect_submodules("pdfminer")
    + collect_submodules("fitz")
    + collect_submodules("app")
)

datas = [("app/static", "static")]
datas += collect_data_files("pdfminer")
datas += collect_data_files("pymupdf", include_py_files=False)

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SUGA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 起動状況が見えるようコンソールを残す
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
