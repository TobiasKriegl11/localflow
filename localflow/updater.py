"""Update check against GitHub Releases.

No self-patching: if a newer release exists we notify and open its download
page. Set GITHUB_REPO to the "owner/name" of the public repo whose Releases
carry the LocalFlow-Setup-*.exe assets.
"""

import json
import logging
import re
import urllib.request
import webbrowser

from localflow import __version__

log = logging.getLogger(__name__)

GITHUB_REPO = "TobiasKriegl11/localflow"
RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"


def _parse(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:3]) or (0,)


def check_for_update(timeout: float = 10.0) -> tuple[str, str] | None:
    """Return (version, download page url) when a newer release exists."""
    req = urllib.request.Request(
        RELEASES_API.format(repo=GITHUB_REPO),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "LocalFlow"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    tag = data.get("tag_name") or ""
    if _parse(tag) > _parse(__version__):
        url = data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest"
        return tag.lstrip("v"), url
    return None


def _notify(icon, message: str) -> None:
    try:
        icon.notify(message, "LocalFlow")
    except Exception:  # notifications unsupported on this backend
        log.info("Update check: %s", message)


def check_and_notify(icon) -> None:
    """Tray-menu action: check GitHub and tell the user the result."""
    try:
        update = check_for_update()
    except Exception:
        log.exception("Update check failed")
        _notify(icon, "Update-Prüfung fehlgeschlagen — bitte Internetverbindung "
                      "prüfen. / Update check failed.")
        return
    if update:
        version, url = update
        _notify(icon, f"LocalFlow {version} ist verfügbar — die Download-Seite "
                      f"wird geöffnet. / Update available.")
        webbrowser.open(url)
    else:
        _notify(icon, f"LocalFlow {__version__} ist aktuell. / You are up to date.")
