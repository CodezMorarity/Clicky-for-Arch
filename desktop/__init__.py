"""Small OS adapters; no Qt, audio, or network side effects at import time."""

import os
import sys


def is_windows() -> bool:
    return sys.platform == "win32"


def is_wayland() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        return True
    if session == "x11":
        return False
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def is_x11() -> bool:
    return sys.platform.startswith("linux") and not is_wayland() and bool(
        os.environ.get("DISPLAY")
    )


def is_hyprland() -> bool:
    return is_wayland() and bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


def is_sway() -> bool:
    return is_wayland() and bool(os.environ.get("SWAYSOCK"))


def uses_portal_capture() -> bool:
    """True when no native compositor screenshot adapter is available."""
    return is_wayland() and not (is_hyprland() or is_sway())


def overlay_positioning_available() -> bool:
    """XWayland supports positioned overlays; native Wayland generally does not."""
    override = os.environ.get("CLICKY_QT_PLATFORM", "").lower()
    if override and override not in {"xcb", "windows"}:
        return False
    if is_windows() or is_x11():
        return True
    if not is_wayland() or not os.environ.get("DISPLAY"):
        return False
    if is_hyprland() or is_sway():
        return True
    try:
        from desktop.display import screen_count
        return screen_count() == 1
    except Exception:
        return False


def prepare_qt() -> None:
    """Use XWayland for movable Linux windows when the session provides it."""
    override = os.environ.get("CLICKY_QT_PLATFORM")
    if override:
        os.environ["QT_QPA_PLATFORM"] = override
    elif is_wayland() and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def desktop_capabilities() -> dict[str, str | bool]:
    if is_windows():
        return {"session": "windows", "capture": "native", "shortcuts": "native",
                "active_window": "native", "overlay": True}
    if is_hyprland():
        return {"session": "hyprland-wayland", "capture": "grim",
                "shortcuts": "hyprland-ipc", "active_window": "hyprland-ipc",
                "overlay": overlay_positioning_available()}
    if is_sway():
        return {"session": "sway-wayland", "capture": "grim",
                "shortcuts": "portal-if-available", "active_window": "sway-ipc",
                "overlay": overlay_positioning_available()}
    if is_wayland():
        return {"session": "wayland", "capture": "screenshot-portal",
                "shortcuts": "global-shortcuts-portal-if-available",
                "active_window": "unavailable",
                "overlay": "xwayland-single-output" if os.environ.get("DISPLAY") else False}
    if is_x11():
        return {"session": "x11", "capture": "mss", "shortcuts": "pynput",
                "active_window": "xprop", "overlay": True}
    return {"session": "unknown", "capture": "unavailable",
            "shortcuts": "unavailable", "active_window": "unavailable",
            "overlay": False}


def open_path(path) -> bool:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
