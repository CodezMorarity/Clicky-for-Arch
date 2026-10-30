"""Run with .venv/bin/python scripts/check_environment.py [--live]."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _portal_interfaces():
    busctl = shutil.which("busctl")
    if not busctl:
        return []
    try:
        result = subprocess.run(
            [busctl, "--user", "introspect", "org.freedesktop.portal.Desktop",
             "/org/freedesktop/portal/desktop"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode:
        return []
    output = result.stdout
    return [name for name in (
        "org.freedesktop.portal.Screenshot",
        "org.freedesktop.portal.GlobalShortcuts",
        "org.freedesktop.portal.ScreenCast",
    ) if name in output]


def main():
    parser = argparse.ArgumentParser(description="Clicky Linux environment check")
    parser.add_argument("--live", action="store_true",
                        help="Query desktop capture, audio, and Ollama (may open a portal prompt)")
    args = parser.parse_args()
    from desktop import desktop_capabilities, is_hyprland, prepare_qt
    from desktop.paths import config_file, data_dir
    report = {
        "python": platform.python_version(), "platform": platform.platform(),
        "session": os.environ.get("XDG_SESSION_TYPE", ""), "hyprland": is_hyprland(),
        "desktop_capabilities": desktop_capabilities(),
        "config": str(config_file(Path(__file__).resolve().parents[1])),
        "data": str(data_dir()), "errors": [],
        "portal_interfaces": _portal_interfaces(),
    }
    report["commands"] = {name: shutil.which(name) for name in
                          ("hyprctl", "swaymsg", "xprop", "grim", "busctl",
                           "tesseract", "ollama", "ffmpeg")}
    report["packages"] = {}
    for name in ("PyQt6", "av", "faster-whisper", "sounddevice", "httpx",
                 "edge-tts", "dbus-next"):
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["errors"].append(f"Missing Python package: {name}")
    if args.live:
        prepare_qt()
        from PyQt6.QtWidgets import QApplication
        from desktop.display import attach
        app = QApplication(["clicky-check"])
        attach(app)
        report["qt_platform"] = app.platformName()
        try:
            from screen.capture import capture_all_screens
            report["screens"] = [
                {"index": s.index, "pixels": [s.physical_width, s.physical_height],
                 "overlay_origin": [s.logical_left, s.logical_top], "overlay_scale": s.dpi_scale}
                for s in capture_all_screens()
            ]
        except Exception as exc:
            report["errors"].append(f"Screen capture: {exc}")
        try:
            import sounddevice as sd
            report["audio_devices"] = [dict(d) for d in sd.query_devices()]
            report["audio_defaults"] = list(sd.default.device)
        except Exception as exc:
            report["errors"].append(f"Audio: {exc}")
        from ai.ollama_bootstrap import is_ollama_running, list_installed_models
        report["ollama_running"] = is_ollama_running()
        report["ollama_models"] = list_installed_models()
        app.quit()
    print(json.dumps(report, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
