"""Sway IPC helpers for focused-window metadata and output geometry."""

import json
import subprocess


def query(message_type: str):
    result = subprocess.run(
        ["swaymsg", "-r", "-t", message_type], capture_output=True,
        text=True, timeout=4,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                           or "swaymsg failed")
    return json.loads(result.stdout)


def outputs() -> list[dict]:
    return [o for o in query("get_outputs") if o.get("active")]


def active_title() -> str | None:
    def find_focused(node):
        if node.get("focused"):
            return node
        for child in (*node.get("nodes", []), *node.get("floating_nodes", [])):
            found = find_focused(child)
            if found:
                return found
        return None

    focused = find_focused(query("get_tree"))
    if not focused:
        return None
    return focused.get("name") or focused.get("app_id") or None
