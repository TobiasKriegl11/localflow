# PyInstaller spec for LocalFlow (Windows one-dir build).
# Build: .venv\Scripts\pyinstaller localflow.spec --noconfirm
# Models are NOT bundled into the exe — the installer ships <app>/models/.

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hiddenimports = [], [], []

# Native libs + package data that PyInstaller misses without help.
for pkg in ("llama_cpp", "faster_whisper", "ctranslate2"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# sounddevice ships portaudio in _sounddevice_data
binaries += collect_dynamic_libs("sounddevice")
hiddenimports += ["sounddevice", "pystray._win32", "pynput.keyboard._win32",
                  "pynput.mouse._win32"]

a = Analysis(
    ["localflow_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # tkinter is required (recording overlay + first-run download window).
    excludes=["test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LocalFlow",
    debug=False,
    console=False,          # tray app: no console window
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LocalFlow",
)
