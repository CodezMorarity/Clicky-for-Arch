"""Session-only Hyprland shortcuts, no root hooks or config file edits."""

import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import sys
import tempfile
import threading

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from desktop.hyprland import command, query

_MODS = {"ctrl": ("CTRL", 4), "control": ("CTRL", 4),
         "alt": ("ALT", 8), "shift": ("SHIFT", 1),
         "win": ("SUPER", 64), "windows": ("SUPER", 64),
         "super": ("SUPER", 64), "cmd": ("SUPER", 64)}


def parse_hotkey(hotkey: str) -> tuple[str, int, str]:
    parts = [p.strip().lower() for p in hotkey.split("+")]
    if not parts or parts[-1] in _MODS or not re.fullmatch(r"[a-z0-9_]+", parts[-1]):
        raise ValueError("On Hyprland use a terminal key, e.g. HOTKEY=ctrl+alt+space.")
    if any(p not in _MODS for p in parts[:-1]):
        raise ValueError(f"Unsupported shortcut: {hotkey}")
    key = {"esc": "Escape", "space": "SPACE"}.get(parts[-1], parts[-1].upper())
    mods = list(dict.fromkeys(_MODS[p][0] for p in parts[:-1]))
    mask = sum({_MODS[p][1] for p in parts[:-1]})
    return " + ".join([*mods, key]), mask, key


class HyprShortcut(QObject):
    activated = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, hotkey, on_press, on_release=None, *, non_consuming=False):
        super().__init__()
        self.chord, self.mask, self.key = parse_hotkey(hotkey)
        self._press, self._release = on_press, on_release
        self._non_consuming = non_consuming
        self._held = False
        self._directory = None
        self._socket = None
        self._thread = None
        self._closed = threading.Event()
        self._descriptions = []
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._restore)
        self.activated.connect(self._dispatch)

    def _matching(self, bindings):
        return [b for b in bindings if b.get("key", "").lower() == self.key.lower()
                and b.get("modmask") == self.mask]

    def _register(self):
        bindings = self._matching(query("binds"))
        # A process killed without Qt cleanup can leave session-only binds.
        # Reclaim only a whole chord owned by a verified dead Clicky process.
        if bindings and all(self._stale(b) for b in bindings):
            command("eval", f"hl.unbind({json.dumps(self.chord)})")
            bindings = []
        if any(b.get("description") not in self._descriptions for b in bindings):
            raise RuntimeError(f"{self.chord} is already bound. Change HOTKEY in Clicky's settings file.")
        existing = {b.get("description") for b in bindings}
        for action, description in zip(("press", "release"), self._descriptions):
            if description in existing:
                continue
            cmd = shlex.join([sys.executable, str(Path(__file__).with_name("control.py")),
                              self._path, action])
            flags = [f"description={json.dumps(description)}"]
            if action == "release":
                flags += ["release=true", "ignore_mods=true"]
            if self._non_consuming or action == "release":
                flags.append("non_consuming=true")
            result = command("eval", f"hl.bind({json.dumps(self.chord)}, "
                             f"hl.dsp.exec_cmd({json.dumps(cmd)}), {{{', '.join(flags)}}})")
            if "error" in result.lower():
                raise RuntimeError(result)

    @staticmethod
    def _stale(binding):
        match = re.fullmatch(r"Clicky (\d+) clicky-shortcut-[\w-]+ (press|release)",
                             binding.get("description", ""))
        if not match:
            return False
        try:
            os.kill(int(match[1]), 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def start(self):
        self._directory = tempfile.TemporaryDirectory(prefix="clicky-shortcut-",
                                                     dir=os.environ.get("XDG_RUNTIME_DIR"))
        self._path = str(Path(self._directory.name) / "control.sock")
        self._descriptions = [f"Clicky {os.getpid()} {Path(self._directory.name).name} press"]
        if self._release:
            self._descriptions.append(self._descriptions[0].removesuffix("press") + "release")
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(self._path)
        os.chmod(self._path, 0o600)
        self._socket.listen(8)
        self._socket.settimeout(0.25)
        try:
            self._register()
        except Exception:
            self.stop()
            raise
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        self._timer.start()

    def _listen(self):
        while not self._closed.is_set():
            try:
                connection, _ = self._socket.accept()
                with connection:
                    connection.settimeout(1)
                    _, uid, _ = struct.unpack("3i", connection.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid == os.getuid():
                        action = connection.recv(32).decode("ascii", errors="ignore")
                        if action in ("press", "release"):
                            self.activated.emit(action)
            except (TimeoutError, OSError):
                continue

    def _dispatch(self, action):
        if self._closed.is_set():
            return
        if action == "press" and (not self._held or self._release is None):
            self._held = True
            self._press()
        elif action == "release" and self._held:
            self._held = False
            if self._release:
                self._release()

    def _restore(self):
        try:
            self._register()
        except Exception as exc:
            self._timer.stop()
            self.failed.emit(str(exc))

    def stop(self):
        self._timer.stop()
        self._closed.set()
        try:
            matches = self._matching(query("binds"))
            # unbind removes a whole chord. Never remove someone else's bind.
            if matches and all(b.get("description") in self._descriptions for b in matches):
                command("eval", f"hl.unbind({json.dumps(self.chord)})")
        except Exception:
            pass
        if self._socket:
            self._socket.close()
        if self._thread:
            self._thread.join(timeout=1.5)
        if self._directory:
            self._directory.cleanup()
