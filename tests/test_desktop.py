import base64
import io
from types import SimpleNamespace

from PIL import Image
import pytest


def test_wayland_capture_uses_native_pixels_and_qt_origins(monkeypatch):
    from screen import capture
    from desktop import display, hyprland
    monkeypatch.setattr(capture, "is_wayland", lambda: True)
    monkeypatch.setattr(capture, "is_hyprland", lambda: True)
    monkeypatch.setattr(capture.shutil, "which", lambda _: "/usr/bin/grim")
    monkeypatch.setattr(hyprland, "monitors", lambda: [
        {"id": 0, "name": "A", "scale": 1.25},
        {"id": 1, "name": "B", "scale": 2.0},
    ])
    monkeypatch.setattr(display, "_screens", {
        "A": (0, 0, 1920, 1080), "B": (-1280, 100, 1280, 720),
    })
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        size = (1920, 1080) if args[2] == "A" else (2560, 1440)
        buf = io.BytesIO()
        Image.new("RGB", size, "white").save(buf, "PNG")
        return SimpleNamespace(returncode=0, stdout=buf.getvalue())
    monkeypatch.setattr(capture.subprocess, "run", run)
    first, second = capture.capture_all_screens()
    assert calls[0] == ["grim", "-o", "A", "-s", "1.25", "-"]
    assert first.image_to_overlay(640, 360) == (960, 540)
    assert second.image_to_overlay(640, 360) == (-640, 460)
    assert second.dpi_scale == 2
    assert Image.open(io.BytesIO(base64.b64decode(first.base64_jpeg))).size == (1280, 720)


def test_wayland_capture_fails_explicitly_without_grim(monkeypatch):
    from screen import capture
    monkeypatch.setattr(capture, "is_wayland", lambda: True)
    monkeypatch.setattr(capture, "is_hyprland", lambda: True)
    monkeypatch.setattr(capture.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="requires grim"):
        capture.capture_all_screens()


def test_hyprland_hotkey_validation():
    from desktop.shortcuts import parse_hotkey
    assert parse_hotkey("ctrl+alt+space") == ("CTRL + ALT + SPACE", 12, "SPACE")
    assert parse_hotkey("esc") == ("Escape", 0, "Escape")
    with pytest.raises(ValueError, match="terminal key"):
        parse_hotkey("ctrl+win")
    with pytest.raises(ValueError):
        parse_hotkey('ctrl+"; os.execute("bad")')


def test_shortcut_preserves_foreign_bindings(qapp, monkeypatch):
    import desktop.shortcuts as shortcuts
    commands = []
    monkeypatch.setattr(shortcuts, "command", lambda *a: commands.append(a) or "ok")
    monkeypatch.setattr(shortcuts, "query", lambda _: [
        {"key": "SPACE", "modmask": 12, "description": "Existing app"},
    ])
    shortcut = shortcuts.HyprShortcut("ctrl+alt+space", lambda: None)
    shortcut._descriptions = ["Clicky test"]
    with pytest.raises(RuntimeError, match="already bound"):
        shortcut._register()
    shortcut.stop()
    assert commands == []


def test_shortcut_dispatch_deduplicates_press_and_release(qapp):
    from desktop.shortcuts import HyprShortcut
    events = []
    shortcut = HyprShortcut("ctrl+alt+space", lambda: events.append("press"),
                            lambda: events.append("release"))
    for action in ("release", "press", "press", "release", "release"):
        shortcut._dispatch(action)
    assert events == ["press", "release"]


def test_wayland_workflow_is_explicitly_unavailable(monkeypatch):
    from tutor_features import workflow_capture
    monkeypatch.setattr(workflow_capture, "is_wayland", lambda: True)
    capture = workflow_capture.WorkflowCapture()
    assert not capture.start()
    assert not capture.is_running


def test_pointer_uses_supplied_capture_and_maps_offset(monkeypatch):
    from ai import hybrid_pointer
    from screen.capture import ScreenShot
    buf = io.BytesIO()
    Image.new("RGB", (100, 50)).save(buf, "JPEG")
    shot = ScreenShot(1, 100, 50, base64.b64encode(buf.getvalue()).decode(),
                      200, 100, -400, 200, 2, -200, 100)
    monkeypatch.setattr(hybrid_pointer, "is_windows", lambda: False)
    monkeypatch.setattr(hybrid_pointer, "_find_tesseract", lambda q, im:
        hybrid_pointer.Target(50, 25, (40, 20, 60, 30), "Save", "ocr", 1.0))
    target = hybrid_pointer.find_target("Save", screenshot=shot)
    assert target.center_xy == (-150, 125)
    assert target.bbox == (-160, 120, -140, 130)


def test_panel_talk_button_emits_and_local_model_is_automatic(qapp):
    from ui.panel import CompanionPanel
    panel = CompanionPanel()
    events = []
    panel.on_push_to_talk_pressed.connect(lambda: events.append("press"))
    panel.on_push_to_talk_released.connect(lambda: events.append("release"))
    panel._ptt_btn.click()
    panel._set_models_for("lmstudio")
    assert events == ["press", "release"]
    assert panel._model_combo.currentData() == ""
    panel.close()


def test_x11_session_takes_precedence_over_stale_wayland_display(monkeypatch):
    import desktop
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    assert not desktop.is_wayland()
    assert desktop.is_x11()


def test_x11_shortcut_normalizes_pynput_modifier_names():
    from desktop.x11 import PynputShortcut
    assert PynputShortcut._normalize("Key.ctrl_l") == "ctrl"
    assert PynputShortcut._normalize("Key.alt_r") == "alt"
    assert PynputShortcut._normalize("Key.space") == "space"
    assert PynputShortcut._normalize("Key.esc") == "esc"


def test_portal_shortcut_trigger_uses_xdg_accelerator_format():
    from desktop.portals import _preferred_trigger
    assert _preferred_trigger("ctrl+alt+space") == "<Control><Alt>space"
    assert _preferred_trigger("esc") == "Escape"
    with pytest.raises(ValueError, match="terminal key"):
        _preferred_trigger("ctrl+win")


def test_portal_wayland_leaves_escape_for_focused_application(monkeypatch):
    import hotkey
    monkeypatch.setattr(hotkey, "is_hyprland", lambda: False)
    monkeypatch.setattr(hotkey, "is_wayland", lambda: True)
    monkeypatch.setattr(hotkey, "is_x11", lambda: False)
    watcher = hotkey.StopHotkey(lambda: None)
    watcher.start()
    assert watcher._adapter is None


def test_portal_capture_maps_full_screen_image_to_qt_bounds(monkeypatch):
    from desktop import display
    from screen import capture
    monkeypatch.setattr(capture, "is_wayland", lambda: True)
    monkeypatch.setattr(capture, "is_hyprland", lambda: False)
    monkeypatch.setattr(capture, "is_sway", lambda: False)
    monkeypatch.setattr(capture, "uses_portal_capture", lambda: True)
    monkeypatch.setattr(display, "_screens", {"screen": (0, 0, 100, 50)})
    from desktop import portals
    monkeypatch.setattr(portals, "screenshot_image", lambda: Image.new("RGB", (200, 100)))
    shot = capture.capture_all_screens()[0]
    assert shot.image_to_overlay(100, 50) == (50, 25)


def test_unknown_window_is_sensitive_to_the_privacy_guard():
    from tutor import is_sensitive_window
    assert is_sensitive_window(None)
    assert is_sensitive_window("Bitwarden vault")
    assert not is_sensitive_window("Firefox")


def test_sway_focused_window_title_uses_focused_tree_node(monkeypatch):
    from desktop import sway
    monkeypatch.setattr(sway, "query", lambda _kind: {
        "focused": False,
        "nodes": [{"focused": True, "name": "Code — main.py", "nodes": []}],
    })
    assert sway.active_title() == "Code — main.py"


def test_portal_request_denial_is_reported_as_cancellation(monkeypatch):
    import asyncio
    import sys
    from types import ModuleType, SimpleNamespace
    from desktop import portals

    class FakeMessage:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_dbus = ModuleType("dbus_next")
    fake_dbus.Message = FakeMessage
    fake_dbus.MessageType = SimpleNamespace(ERROR="error")
    monkeypatch.setitem(sys.modules, "dbus_next", fake_dbus)

    class FakeBus:
        def add_message_handler(self, handler):
            self.handler = handler

        async def call(self, _message):
            self.handler(SimpleNamespace(
                interface=portals._REQUEST_IFACE, member="Response",
                path="/request/1", body=[1, {}],
            ))
            return SimpleNamespace(message_type="return", body=["/request/1"])

    async def invoke():
        requests = portals._PortalRequests(FakeBus())
        return await requests.request("portal.test", "Capture", "", [])

    with pytest.raises(PermissionError, match="cancelled"):
        asyncio.run(invoke())


def test_missing_dbus_dependency_fails_with_install_hint(monkeypatch):
    import asyncio
    import sys
    from desktop import portals
    monkeypatch.setitem(sys.modules, "dbus_next", None)
    with pytest.raises(RuntimeError, match="Install Clicky's Linux requirements"):
        asyncio.run(portals._connect_bus())
