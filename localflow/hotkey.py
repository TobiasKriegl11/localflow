"""Global push-to-talk hotkey via pynput. Default: hold Ctrl+Win, release to transcribe."""

import logging
import sys
from collections.abc import Callable

from pynput import keyboard

log = logging.getLogger(__name__)

# Normalize left/right variants to one logical name.
_KEY_ALIASES = {
    keyboard.Key.ctrl: "ctrl",
    keyboard.Key.ctrl_l: "ctrl",
    keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.cmd: "win",  # Windows key / macOS Cmd
    keyboard.Key.cmd_l: "win",
    keyboard.Key.cmd_r: "win",
    keyboard.Key.alt: "alt",
    keyboard.Key.alt_l: "alt",
    keyboard.Key.alt_r: "alt",
    keyboard.Key.shift: "shift",
    keyboard.Key.shift_l: "shift",
    keyboard.Key.shift_r: "shift",
}

DEFAULT_COMBO = frozenset({"ctrl", "win"}) if sys.platform == "win32" else frozenset({"ctrl", "alt"})


class PushToTalk:
    """Calls on_start when the full combo is held, on_stop when any combo key lifts."""

    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None],
                 combo: frozenset[str] = DEFAULT_COMBO) -> None:
        self.on_start = on_start
        self.on_stop = on_stop
        self.combo = combo
        self._pressed: set[str] = set()
        self._active = False
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release)

    def _name(self, key) -> str | None:
        return _KEY_ALIASES.get(key)

    def _on_press(self, key) -> None:
        name = self._name(key)
        if name is None:
            return
        self._pressed.add(name)
        if not self._active and self.combo <= self._pressed:
            self._active = True
            self.on_start()

    def _on_release(self, key) -> None:
        name = self._name(key)
        if name is None:
            return
        self._pressed.discard(name)
        if self._active and name in self.combo:
            self._active = False
            self.on_stop()

    def start(self) -> None:
        self._listener.start()
        log.info("Push-to-talk ready: hold %s", "+".join(sorted(self.combo)))

    def join(self) -> None:
        self._listener.join()

    def stop(self) -> None:
        self._listener.stop()
