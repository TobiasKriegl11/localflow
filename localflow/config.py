"""YAML settings, stored per-user (survives app reinstalls)."""

import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


def config_dir() -> Path:
    if sys.platform == "win32":
        import os
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path.home() / ".config"
    return base / "LocalFlow"


CONFIG_PATH = config_dir() / "settings.yaml"


# NOTE: earlier versions seeded the default language from the OS UI locale
# (returning "de" on a German Windows, etc.). That silently FORCED a single
# language and disabled detection entirely, so bilingual users had their other
# language mangled into the forced one (English spoken → "Ich möchte das in eine
# Real-Funktion..."). Auto-detect is the correct default: it picks de/en per take.


@dataclass
class Settings:
    model: str = "auto"          # auto | tiny.en | base.en | small.en | tiny | base | small
    language: str = "auto"       # auto (detect de/en per take) | en | de
    llm_cleanup: bool = True     # AI punctuation/filler cleanup (off = raw Whisper)
    hotkey: str = "ctrl+win" if sys.platform == "win32" else "ctrl+alt"
    delivery: str = "paste"      # paste | type (reserved)
    pre_roll_seconds: float = 0.5
    cleanup_timeout: float = 3.0
    start_on_login: bool = False
    tiered_model: str = ""       # cached speed-benchmark decision (auto mode)
    auto_stop_silence: float = 1.5   # tap mode: stop after this many s of silence
    max_take_seconds: float = 90.0   # hard cap per dictation
    show_overlay: bool = True
    language_hint: str = ""      # auto mode: dominant language of past sessions
    sound_feedback: bool = True  # blip on record start/stop
    # Use the 'small' multilingual model. ~3x slower than base on CPU, but the
    # only tier that cleanly transcribes mid-sentence de/en code-switching
    # (base garbles the minority-language span). Opt-in; needs the small model
    # (bundled in the full installer, else downloaded on first enable).
    high_accuracy: bool = False
    # Auto mode only considers these languages (empty list = all 99).
    auto_languages: list = field(default_factory=lambda: ["de", "en"])
    _extra: dict = field(default_factory=dict, repr=False)

    @property
    def hotkey_combo(self) -> frozenset[str]:
        return frozenset(p.strip().lower() for p in self.hotkey.split("+") if p.strip())


def load() -> Settings:
    s = Settings()
    try:
        if CONFIG_PATH.exists():
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            known = {k for k in Settings.__dataclass_fields__ if not k.startswith("_")}
            for k, v in data.items():
                if k in known:
                    setattr(s, k, v)
                else:
                    s._extra[k] = v  # preserve unknown keys across save
    except Exception:
        log.exception("Bad settings file, using defaults")
    if isinstance(s.auto_languages, str):  # hand-edited scalar, e.g. "de, en"
        s.auto_languages = s.auto_languages.replace(",", " ").split()
    return s


def save(s: Settings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(s).items() if not k.startswith("_")}
    data.update(s._extra)
    CONFIG_PATH.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    log.info("Settings saved to %s", CONFIG_PATH)
