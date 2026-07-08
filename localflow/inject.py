"""Inject text at the cursor: clipboard + simulated paste, restoring the clipboard.

Windows: Ctrl+V via ctypes SendInput. macOS: Cmd+V via pynput (pyobjc CGEvent later).
"""

import logging
import sys
import time

import pyperclip

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56
    VK_LWIN = 0x5B
    VK_RWIN = 0x5C
    VK_MENU = 0x12  # Alt

    ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        # Must be in the union even though unused: it is the largest member,
        # and without it sizeof(INPUT) is wrong -> SendInput fails (error 87).
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]

    def _key_event(vk: int, up: bool = False) -> INPUT:
        flags = KEYEVENTF_KEYUP if up else 0
        ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)
        return INPUT(type=INPUT_KEYBOARD, union=_INPUT_UNION(ki=ki))

    def _send_inputs(inputs: list) -> None:
        arr = (INPUT * len(inputs))(*inputs)
        sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise ctypes.WinError(ctypes.get_last_error())

    def _modifiers_held() -> bool:
        """True if a modifier that would corrupt Ctrl+V is physically held."""
        for vk in (VK_LWIN, VK_RWIN, VK_MENU):
            if user32.GetAsyncKeyState(vk) & 0x8000:
                return True
        return False

    def _paste_keystroke() -> None:
        _send_inputs([
            _key_event(VK_CONTROL),
            _key_event(VK_V),
            _key_event(VK_V, up=True),
            _key_event(VK_CONTROL, up=True),
        ])

else:
    def _modifiers_held() -> bool:
        return False

    def _paste_keystroke() -> None:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        with kb.pressed(Key.cmd):
            kb.press("v")
            kb.release("v")


def inject_text(text: str, restore_delay: float = 0.3) -> None:
    """Paste `text` at the cursor of the focused app, then restore the clipboard."""
    if not text:
        return

    # Wait briefly for hotkey modifiers (esp. Win — Win+V opens clipboard history)
    # to be physically released before we synthesize Ctrl+V.
    deadline = time.monotonic() + 2.0
    while _modifiers_held() and time.monotonic() < deadline:
        time.sleep(0.02)

    try:
        previous = pyperclip.paste()
    except Exception:
        previous = None

    pyperclip.copy(text)
    time.sleep(0.05)  # let the clipboard settle before the paste keystroke
    _paste_keystroke()
    log.info("Injected %d chars", len(text))

    if previous is not None:
        time.sleep(restore_delay)  # target app must read the clipboard first
        try:
            pyperclip.copy(previous)
        except Exception:
            pass
