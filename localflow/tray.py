"""System tray icon (pystray): status, AI-cleanup toggle, start-on-login, quit."""

import logging
import threading

import pyperclip
import pystray
from PIL import Image, ImageDraw

from localflow import autostart, config

log = logging.getLogger(__name__)


def _make_icon(active: bool) -> Image.Image:
    """Simple mic glyph: blue circle, red while recording."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (220, 60, 60, 255) if active else (70, 130, 240, 255)
    d.ellipse((14, 6, 50, 42), fill=color)                  # capsule head
    d.rectangle((29, 40, 35, 52), fill=color)               # stem
    d.arc((10, 24, 54, 56), start=0, end=180, fill=color, width=5)
    return img


LANGUAGES = [("auto", "Automatisch / Auto"), ("de", "Deutsch"), ("en", "English")]


class Tray:
    def __init__(self, settings: config.Settings, status: str,
                 on_toggle_cleanup, on_set_language, on_quit,
                 history=None, on_open_vocab=None, on_toggle_accuracy=None) -> None:
        self.settings = settings
        self._on_toggle_cleanup = on_toggle_cleanup
        self._on_set_language = on_set_language
        self._on_quit = on_quit
        self._history = history if history is not None else []
        self._on_open_vocab = on_open_vocab
        self._on_toggle_accuracy = on_toggle_accuracy
        lang_items = [
            pystray.MenuItem(label, self._make_lang_setter(code), radio=True,
                             checked=(lambda code: lambda _:
                                      self.settings.language == code)(code))
            for code, label in LANGUAGES
        ]
        menu = pystray.Menu(
            pystray.MenuItem(f"LocalFlow — {status}", None, enabled=False),
            pystray.MenuItem(f"Hotkey: hold {settings.hotkey}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Verlauf / History",
                             pystray.Menu(self._history_items)),
            pystray.MenuItem("Wörterbuch / Vocabulary…", self._open_vocab),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sprache / Language", pystray.Menu(*lang_items)),
            pystray.MenuItem("Höhere Genauigkeit / Higher accuracy",
                             self._toggle_accuracy,
                             checked=lambda _: self.settings.high_accuracy),
            pystray.MenuItem("AI cleanup", self._toggle_cleanup,
                             checked=lambda _: self.settings.llm_cleanup),
            pystray.MenuItem("Töne / Sounds", self._toggle_sounds,
                             checked=lambda _: self.settings.sound_feedback),
            pystray.MenuItem("Start on login", self._toggle_login,
                             checked=lambda _: self.settings.start_on_login),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Nach Updates suchen / Check for updates",
                             self._check_updates),
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon("LocalFlow", _make_icon(False), "LocalFlow", menu)

    def _make_lang_setter(self, code: str):
        def setter(_icon, _item) -> None:
            self._on_set_language(code)
        return setter

    def _history_items(self):
        """Last dictations; clicking one copies it back to the clipboard."""
        entries = list(self._history)
        if not entries:
            yield pystray.MenuItem("(leer / empty)", None, enabled=False)
            return
        for stamp, text in entries:
            label = text if len(text) <= 45 else text[:44] + "…"
            yield pystray.MenuItem(f"{stamp}  {label}", self._make_copier(text))

    def _make_copier(self, text: str):
        def copy(icon, _item) -> None:
            pyperclip.copy(text)
            try:
                icon.notify("In Zwischenablage kopiert / Copied", "LocalFlow")
            except Exception:
                pass
        return copy

    def _open_vocab(self, _icon, _item) -> None:
        if self._on_open_vocab:
            self._on_open_vocab()

    def _toggle_sounds(self, _icon, _item) -> None:
        self.settings.sound_feedback = not self.settings.sound_feedback
        config.save(self.settings)

    def refresh(self) -> None:
        """Re-render the menu (e.g. after a new history entry)."""
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _toggle_cleanup(self, _icon, _item) -> None:
        self.settings.llm_cleanup = not self.settings.llm_cleanup
        config.save(self.settings)
        self._on_toggle_cleanup(self.settings.llm_cleanup)

    def _toggle_accuracy(self, _icon, _item) -> None:
        if self._on_toggle_accuracy:
            self._on_toggle_accuracy(not self.settings.high_accuracy)

    def _toggle_login(self, _icon, _item) -> None:
        target = not self.settings.start_on_login
        if autostart.set_start_on_login(target):
            self.settings.start_on_login = target
            config.save(self.settings)

    def _check_updates(self, icon, _item) -> None:
        def work() -> None:
            from localflow import updater
            updater.check_and_notify(icon)
        threading.Thread(target=work, daemon=True).start()

    def _quit(self, _icon, _item) -> None:
        self.icon.stop()
        self._on_quit()

    def set_recording(self, active: bool) -> None:
        self.icon.icon = _make_icon(active)

    def run(self) -> None:
        """Blocks. Call from the main thread."""
        self.icon.run()
