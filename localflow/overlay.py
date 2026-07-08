"""On-screen recording indicator: white pill, animated black soundwave.

Shown at the lower middle of the screen while recording; pulsing dots while
transcribing. Runs tkinter in its own thread; the window never takes focus
(WS_EX_NOACTIVATE on Windows) so the target text field keeps the cursor.
"""

import logging
import math
import sys
import threading
from collections import deque

log = logging.getLogger(__name__)

W, H = 220, 56
BARS = 15
TRANSPARENT = "#ff00ff"  # color-keyed away on Windows

HIDDEN, RECORDING, PROCESSING = "hidden", "recording", "processing"


class Overlay:
    def __init__(self) -> None:
        self._state = HIDDEN
        self._levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self._lock = threading.Lock()
        self._ready = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(timeout=5)

    # -- public API (any thread) ------------------------------------------
    def set_state(self, state: str) -> None:
        self._state = state

    def feed_level(self, rms: float) -> None:
        with self._lock:
            self._levels.append(min(1.0, rms * 18))  # normalize speech RMS ~0.05

    # -- tkinter thread ----------------------------------------------------
    def _run(self) -> None:
        try:
            import tkinter as tk

            self.root = tk.Tk()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{sh - H - 90}")
            if sys.platform == "win32":
                self.root.attributes("-transparentcolor", TRANSPARENT)
            self.canvas = tk.Canvas(self.root, width=W, height=H,
                                    bg=TRANSPARENT, highlightthickness=0)
            self.canvas.pack()
            self.root.withdraw()
            if sys.platform == "win32":
                self._no_activate()
            self._visible = False
            self._phase = 0
            self._ready.set()
            self.root.after(50, self._tick)
            self.root.mainloop()
        except Exception:
            log.exception("Overlay unavailable")
            self._ready.set()

    def _no_activate(self) -> None:
        """WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW: never steal focus, no taskbar."""
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x08000000, 0x00000080
        self.root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongPtrW(
            hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def _tick(self) -> None:
        state = self._state
        if state == HIDDEN:
            if self._visible:
                self.root.withdraw()
                self._visible = False
        else:
            if not self._visible:
                self.root.deiconify()
                self._visible = True
            self._draw(state)
        self.root.after(50, self._tick)

    def _draw(self, state: str) -> None:
        c = self.canvas
        c.delete("all")
        # White pill with a soft border.
        r = H // 2
        c.create_oval(0, 0, H, H, fill="white", outline="#d0d0d0")
        c.create_oval(W - H, 0, W, H, fill="white", outline="#d0d0d0")
        c.create_rectangle(r, 0, W - r, H, fill="white", outline="white")
        c.create_line(r, 0, W - r, 0, fill="#d0d0d0")
        c.create_line(r, H - 1, W - r, H - 1, fill="#d0d0d0")

        self._phase += 1
        if state == RECORDING:
            with self._lock:
                levels = list(self._levels)
            slot = (W - 2 * r) / BARS
            x0 = r + slot / 2
            for i, lvl in enumerate(levels):
                # Idle wave: keeps the bars visibly alive during silence;
                # real speech levels take over as soon as they exceed it.
                idle = 0.16 + 0.12 * math.sin(self._phase * 0.35 + i * 0.9)
                h = max(3, int(max(lvl, idle) * (H - 20)))
                x = x0 + i * slot
                c.create_line(x, H // 2 - h // 2, x, H // 2 + h // 2,
                              fill="black", width=3, capstyle="round")
        else:  # PROCESSING: three pulsing dots
            for i in range(3):
                grow = 2 if (self._phase // 3) % 3 == i else 0
                x = W // 2 + (i - 1) * 18
                c.create_oval(x - 3 - grow, H // 2 - 3 - grow,
                              x + 3 + grow, H // 2 + 3 + grow, fill="black")
