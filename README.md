# LocalFlow

Self-contained, **offline** voice dictation — a local, privacy-first Wispr Flow clone.
Hold a hotkey, speak, release: clean, punctuated text appears at your cursor in any app.
No cloud, no subscription, no account. Everything runs on your machine.

## How it works

```
hold Ctrl+Win ──► mic (with 500 ms pre-roll ring buffer)
release       ──► Silero VAD trim ──► faster-whisper (base.en int8, CPU)
              ──► Llama-3.2-1B cleanup (punctuation, filler removal; 3 s timeout
                   → falls back to raw text; toggle in tray)
              ──► clipboard paste at cursor (your old clipboard is restored)
```

- **Auto-tiering:** first launch benchmarks your CPU and picks the largest whisper
  model that keeps dictation fast (base.en on most laptops, small.en on fast
  desktops, CUDA if an NVIDIA GPU is present, tiny.en under 6 GB RAM).
- **Tray icon:** history of the last 5 dictations (click = copy), vocabulary editor,
  language, AI cleanup, sounds, start on login, update check, quit. Icon turns red
  while recording.
- **Vocabulary:** tray → „Wörterbuch / Vocabulary" opens a text file; names/terms
  listed there (one per line) are recognized much more reliably. No restart needed.
- **Sound feedback:** subtle rising blip on record start, falling blip on stop
  (toggle in tray).
- Settings: `%APPDATA%\LocalFlow\settings.yaml` (Win) / `~/Library/Application Support/LocalFlow` (Mac).
- Logs: `localflow.log` in the same folder.

## Install (family & friends)

Two installers, same app:

- **`LocalFlow-Setup-Slim-<version>.exe` (~100 MB, recommended for sharing)** —
  downloads the speech models (~1 GB, once, with a progress window) on first launch.
- **`LocalFlow-Setup-<version>.exe` (~1 GB)** — models bundled, fully offline from
  the first second.

Click through, done. No Python, no terminal. Updates: tray →
**Nach Updates suchen / Check for updates** (opens the download page when a newer
release exists).

> The build is unsigned, so Windows SmartScreen may warn: click
> **More info → Run anyway**. On macOS: right-click the app → **Open**.

## Run from source (dev)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
.venv\Scripts\python -m localflow
```

First run downloads whisper base.en (~145 MB); put
`Llama-3.2-1B-Instruct-Q4_K_M.gguf` in `models/` for AI cleanup (or it runs raw).

## Build the Windows installer

```powershell
.venv\Scripts\pyinstaller localflow.spec --noconfirm
# stage models next to the exe (full installer only; slim skips them)
New-Item -ItemType Directory -Force dist\LocalFlow\models
Copy-Item models\Llama-3.2-1B-Instruct-Q4_K_M.gguf dist\LocalFlow\models\
Copy-Item models\faster-whisper-base.en dist\LocalFlow\models\ -Recurse
Copy-Item models\faster-whisper-base dist\LocalFlow\models\ -Recurse
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\localflow.iss       # full, ~1 GB
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\localflow_slim.iss  # slim, ~100 MB
```

For the update checker to work, set `GITHUB_REPO` in `localflow/updater.py` to the
public GitHub repo that hosts the release `.exe` files, and tag releases `v<version>`.

macOS: `bash installer/build_mac.sh` **on a Mac** (untested on real hardware yet —
needs Accessibility + Microphone permissions on first run).

## Measured on the reference machine (i5-1235U, 16 GB, CPU-only)

| Stage | Time |
|---|---|
| whisper base.en, 5 s utterance | ~1.1 s |
| LLM cleanup (warm) | ~0.65 s |
| **Total (release → text)** | **~1.7 s** |

## Known limitations

- `llama-cpp-python` is pinned to **0.2.90**: newer prebuilt CPU wheels crash with
  illegal instruction on CPUs without AVX-512.
- Unsigned binaries (SmartScreen/Gatekeeper warnings) until a code-signing cert is added.
- No live streaming preview yet (text appears after you stop speaking).
- Languages: German and English get AI cleanup; other languages transcribe raw
  (tray → Sprache/Language → Automatisch).
