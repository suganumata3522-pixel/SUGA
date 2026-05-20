# PyInstaller スペックファイル（YHG-Sleeve / 梁スリーブ貫通補強チェック）。
# Windows 上で  pyinstaller yhg_sleeve.spec  を実行すると dist/YHG-Sleeve.exe が生成される。
# yhg.spec と中身はほぼ同じだが、エントリポイントが run_sleeve.py で、
# 生成物名と exe 内部メタが YHG-Sleeve になる。
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

datas = [
    ("app/static", "static"),
    ("app/assets", "app/assets"),
]
datas += collect_data_files("pdfminer")
datas += collect_data_files("pymupdf", include_py_files=False)

a = Analysis(
    ["run_sleeve.py"],
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
    name="YHG-Sleeve",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
