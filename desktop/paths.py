"""Writable user paths, keeping Windows and existing Linux data intact."""

import os
from pathlib import Path

from desktop import is_windows


def _xdg(variable: str, default: str) -> Path:
    value = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / default


def data_dir() -> Path:
    override = os.environ.get("CLICKY_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_windows():
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Clicky"
    legacy = Path.home() / "Clicky"
    if legacy.is_dir():
        return legacy
    return _xdg("XDG_DATA_HOME", ".local/share") / "clicky"


def ensure_data_dir() -> Path:
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def config_file(app_dir: Path) -> Path:
    override = os.environ.get("CLICKY_CONFIG_FILE")
    if override:
        return Path(override).expanduser().resolve()
    if is_windows():
        return app_dir / ".env"
    return _xdg("XDG_CONFIG_HOME", ".config") / "clicky" / ".env"


def recordings_dir() -> Path:
    if is_windows():
        return Path.home() / "Documents" / "Clicky Lessons"
    return data_dir() / "recordings"
