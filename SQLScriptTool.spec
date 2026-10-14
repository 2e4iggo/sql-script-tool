# PyInstaller spec for SQL Script Tool. Build with build.bat (or: python -m PyInstaller SQLScriptTool.spec)
# One-folder build: dist\SQLScriptTool\SQLScriptTool.exe. Faster start-up than --onefile,
# which would unpack ~100 MB (pandas) to a temp folder on every launch.

a = Analysis(
    ["SQL-Generate(v4).py"],
    pathex=["."],
    datas=[("assets/app.ico", "assets")],
    hiddenimports=[
        "keyring.backends.Windows",     # keyring finds backends via entry points
        "win32ctypes.core",
        "openpyxl",                      # pandas loads Excel engines lazily
    ],
    excludes=[
        "matplotlib", "scipy", "IPython", "jupyter", "notebook", "pytest", "tests",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "sqlalchemy", "pyarrow",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SQLScriptTool",
    icon="assets/app.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SQLScriptTool", upx=False)
