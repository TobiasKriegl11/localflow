#!/bin/bash
# Build LocalFlow.app + .dmg on macOS. Run ON A MAC from the repo root:
#   bash installer/build_mac.sh
# Prereqs: Python 3.12 (python.org or brew), Xcode CLT.
set -euo pipefail

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# llama-cpp-python: build with Metal for Apple Silicon (no prebuilt-wheel pin needed on mac)
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python==0.2.90
pip install faster-whisper sounddevice pynput pyperclip numpy pystray pillow pyyaml
pip install pyobjc-framework-Quartz  # CGEvent paste path
pip install pyinstaller

# Fetch models if not present
python - <<'EOF'
from pathlib import Path
from huggingface_hub import hf_hub_download, snapshot_download
models = Path("models"); models.mkdir(exist_ok=True)
gguf = models / "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
if not gguf.exists():
    hf_hub_download(repo_id="bartowski/Llama-3.2-1B-Instruct-GGUF",
                    filename=gguf.name, local_dir=models)
base = models / "faster-whisper-base.en"
if not (base / "model.bin").exists():
    snapshot_download(repo_id="Systran/faster-whisper-base.en", local_dir=base)
EOF

pyinstaller localflow.spec --noconfirm
mkdir -p dist/LocalFlow/models
cp models/Llama-3.2-1B-Instruct-Q4_K_M.gguf dist/LocalFlow/models/
cp -R models/faster-whisper-base.en dist/LocalFlow/models/

# .app bundle + dmg
# For a signed/notarized build add: codesign --deep --sign "Developer ID ..." and notarytool.
hdiutil create -volname LocalFlow -srcfolder dist/LocalFlow -ov -format UDZO \
    dist/LocalFlow-0.1.0.dmg
echo "Done: dist/LocalFlow-0.1.0.dmg"
echo "NOTE: macOS needs Accessibility + Microphone permissions on first run"
echo "(System Settings > Privacy & Security). Unsigned builds: right-click > Open."
