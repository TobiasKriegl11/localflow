"""Start-on-login: HKCU Run key on Windows, LaunchAgent on macOS."""

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "LocalFlow"


def _launch_command() -> str:
    """Command that starts LocalFlow — the frozen exe, or pythonw -m localflow."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name(
        "pythonw.exe" if sys.platform == "win32" else "python")
    return f'"{pythonw}" -m localflow'


def set_start_on_login(enabled: bool) -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            with key:
                if enabled:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _launch_command())
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
        elif sys.platform == "darwin":
            plist = Path.home() / f"Library/LaunchAgents/com.localflow.app.plist"
            if enabled:
                import shlex
                args = "".join(f"<string>{a}</string>"
                               for a in shlex.split(_launch_command()))
                plist.parent.mkdir(parents=True, exist_ok=True)
                plist.write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>'
                    '<key>Label</key><string>com.localflow.app</string>'
                    f'<key>ProgramArguments</key><array>{args}</array>'
                    '<key>RunAtLoad</key><true/>'
                    '</dict></plist>\n')
            else:
                plist.unlink(missing_ok=True)
        else:
            return False
        log.info("Start on login %s", "enabled" if enabled else "disabled")
        return True
    except Exception:
        log.exception("Failed to update start-on-login")
        return False


def is_enabled() -> bool:
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        elif sys.platform == "darwin":
            return (Path.home() / "Library/LaunchAgents/com.localflow.app.plist").exists()
    except OSError:
        pass
    return False
