"""X11 focused-window lookup and low-level-free global shortcut listener."""

import subprocess

from PyQt6.QtCore import QObject, pyqtSignal


def active_title() -> str | None:
    """Read the EWMH active title through xprop; return None when unavailable."""
    try:
        active = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True,
            text=True, timeout=2, check=True,
        ).stdout
        window = active.rsplit("#", 1)[-1].strip()
        if not window or window in ("0x0", "0"):
            return None
        title = subprocess.run(
            ["xprop", "-id", window, "-notype", "-f", "_NET_WM_NAME", "8u",
             "-len", "2048", "_NET_WM_NAME"],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout
        if "=" not in title:
            title = subprocess.run(
                ["xprop", "-id", window, "-notype", "WM_NAME"],
                capture_output=True, text=True, timeout=2, check=True,
            ).stdout
        value = title.split("=", 1)[-1].strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value or ""
    except (OSError, subprocess.SubprocessError):
        return None


class PynputShortcut(QObject):
    """Observe an X11 shortcut without requiring root or /dev/input access."""

    failed = pyqtSignal(str)

    _MODIFIERS = {
        "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
        "win": "win", "windows": "win", "super": "win", "cmd": "win",
    }

    def __init__(self, hotkey, on_press, on_release=None, *, non_consuming=False):
        super().__init__()
        self._parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
        if not self._parts:
            raise ValueError("Shortcut cannot be empty")
        self._need = {self._normalize(part) for part in self._parts}
        self._on_press, self._on_release = on_press, on_release
        self._held = False
        self._listener = None
        self._pressed = set()

    @classmethod
    def _normalize(cls, value):
        value = str(value).lower().removeprefix("key.")
        aliases = {
            "ctrl_l": "ctrl", "ctrl_r": "ctrl", "control_l": "ctrl",
            "control_r": "ctrl", "alt_l": "alt", "alt_r": "alt",
            "shift_l": "shift", "shift_r": "shift", "cmd": "win",
            "cmd_l": "win", "cmd_r": "win", "super_l": "win",
            "super_r": "win", "space": "space", "esc": "esc",
            "escape": "esc",
        }
        return aliases.get(value, cls._MODIFIERS.get(value, value))

    @staticmethod
    def _event_name(key):
        char = getattr(key, "char", None)
        if char:
            return char.lower()
        return str(key)

    def _press_key(self, key):
        self._pressed.add(self._normalize(self._event_name(key)))
        if not self._held and self._need.issubset(self._pressed):
            self._held = True
            self._on_press()

    def _release_key(self, key):
        self._pressed.discard(self._normalize(self._event_name(key)))
        if self._held and not self._need.issubset(self._pressed):
            self._held = False
            if self._on_release:
                self._on_release()

    def start(self):
        try:
            from pynput import keyboard
        except (ImportError, OSError) as exc:
            raise RuntimeError("X11 shortcuts require pynput and a working X server") from exc
        self._pressed = set()
        self._listener = keyboard.Listener(
            on_press=self._press_key, on_release=self._release_key,
        )
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
