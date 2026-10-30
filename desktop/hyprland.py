"""Native Hyprland queries; XWayland is used only to paint the existing UI."""

import json
import subprocess


def command(*args: str) -> str:
    result = subprocess.run(
        ["hyprctl", *args], capture_output=True, text=True, timeout=4,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def query(name: str):
    return json.loads(command("-j", name))


def monitors() -> list[dict]:
    return sorted(
        (m for m in query("monitors") if not m.get("disabled")
         and m.get("mirrorOf", "none") in ("none", "", None)),
        key=lambda m: m["id"],
    )


def active_title() -> str:
    return query("activewindow").get("title", "")
