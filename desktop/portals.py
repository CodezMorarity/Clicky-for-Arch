"""XDG desktop portal screenshot and global-shortcut clients."""

import asyncio
import logging
import threading
import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

_BUS_NAME = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_SHORTCUT_IFACE = "org.freedesktop.portal.GlobalShortcuts"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SESSION_IFACE = "org.freedesktop.portal.Session"
_log = logging.getLogger("clicky.desktop.portals")


async def _connect_bus():
    try:
        from dbus_next import BusType
        from dbus_next.aio import MessageBus
    except ImportError as exc:
        raise RuntimeError(
            "Wayland desktop portals require the dbus-next Python package. "
            "Install Clicky's Linux requirements."
        ) from exc
    return await MessageBus(bus_type=BusType.SESSION).connect()


class _PortalRequests:
    def __init__(self, bus):
        self.bus = bus
        self.loop = asyncio.get_running_loop()
        self.pending = {}
        self.responses = {}
        bus.add_message_handler(self._handle)

    async def subscribe(self):
        from dbus_next import Message, MessageType

        reply = await self.bus.call(Message(
            destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus", member="AddMatch", signature="s",
            body=["type='signal',sender='org.freedesktop.portal.Desktop',"
                  "interface='org.freedesktop.portal.Request',member='Response'"],
        ))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError("Could not subscribe to desktop portal responses")

    def _handle(self, message):
        if (message.interface == _REQUEST_IFACE and message.member == "Response"
                and message.body):
            path = message.path
            response = message.body
            future = self.pending.pop(path, None)
            if future and not future.done():
                future.set_result(response)
            else:
                self.responses[path] = response
        return False

    async def request(self, interface, member, signature, body):
        from dbus_next import Message, MessageType
        reply = await self.bus.call(Message(
            destination=_BUS_NAME, path=_PORTAL_PATH, interface=interface,
            member=member, signature=signature, body=body,
        ))
        if reply.message_type == MessageType.ERROR:
            detail = ": ".join(str(v) for v in reply.body)
            raise RuntimeError(f"Desktop portal {member} failed: {detail or reply.error_name}")
        handle = reply.body[0]
        if handle in self.responses:
            response = self.responses.pop(handle)
        else:
            future = self.loop.create_future()
            self.pending[handle] = future
            response = await asyncio.wait_for(future, timeout=90)
        status, results = response
        if status != 0:
            reason = "cancelled" if status == 1 else "denied or unavailable"
            raise PermissionError(f"Desktop portal request was {reason}")
        return results


async def _take_screenshot():
    bus = await _connect_bus()
    from dbus_next import Variant

    requests = _PortalRequests(bus)
    try:
        await requests.subscribe()
        options = {
            "handle_token": Variant("s", "clicky_" + uuid.uuid4().hex[:16]),
            # Keep unknown active-window cases explicit and user approved.
            "interactive": Variant("b", True),
            "target": Variant("u", 1),  # complete screen, not a cropped region
        }
        try:
            results = await requests.request(
                "org.freedesktop.portal.Screenshot", "Screenshot", "sa{sv}",
                ["", options],
            )
        except RuntimeError as exc:
            # target was added in Screenshot portal v3; older backends retain
            # the historical full-screen default.
            if "Screenshot failed" not in str(exc):
                raise
            options.pop("target", None)
            results = await requests.request(
                "org.freedesktop.portal.Screenshot", "Screenshot", "sa{sv}",
                ["", options],
            )
        uri = results.get("uri")
        if isinstance(uri, Variant):
            uri = uri.value
        if not uri:
            raise RuntimeError("Screenshot portal returned no image URI")
        return uri
    finally:
        bus.remove_message_handler(requests._handle)
        bus.disconnect()


def screenshot_image():
    """Take an interactive full-screen screenshot and return a PIL RGB image."""
    from pathlib import Path
    from urllib.parse import unquote, urlparse
    from PIL import Image

    uri = asyncio.run(_take_screenshot())
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise RuntimeError("Screenshot portal returned an unsupported image URI")
    path = Path(unquote(parsed.path))
    try:
        with Image.open(path) as image:
            return image.convert("RGB")
    except OSError as exc:
        raise RuntimeError(f"Could not read the screenshot selected in the desktop portal: {exc}") from exc


def _preferred_trigger(hotkey):
    names = {
        "ctrl": "Control", "control": "Control", "alt": "Alt",
        "shift": "Shift", "win": "Super", "windows": "Super",
        "super": "Super", "cmd": "Super", "space": "space",
        "esc": "Escape", "escape": "Escape",
    }
    parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
    if len(parts) < 1 or parts[-1] in names and names[parts[-1]] in {
            "Control", "Alt", "Shift", "Super"}:
        raise ValueError("Wayland shortcuts need a terminal key, e.g. ctrl+alt+space")
    modifiers = []
    for part in parts[:-1]:
        if part not in names or names[part] not in {"Control", "Alt", "Shift", "Super"}:
            raise ValueError(f"Unsupported Wayland shortcut modifier: {part}")
        token = names[part]
        if token not in modifiers:
            modifiers.append(token)
    key = names.get(parts[-1], parts[-1])
    return "".join(f"<{modifier}>" for modifier in modifiers) + key


class PortalShortcutRegistry(QObject):
    event = pyqtSignal(str, bool)
    failure = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._adapters = {}
        self._timer_started = False
        self._thread = None
        self._loop = None
        self._bus = None
        self._session = None
        self._handler = None

    def add(self, adapter):
        if self._thread:
            raise RuntimeError("Restart Clicky before changing portal shortcuts")
        self._adapters[adapter.shortcut_id] = adapter
        if not self._timer_started:
            self._timer_started = True
            # Push-to-talk registers before the Qt event loop starts.
            QTimer.singleShot(0, self._launch)

    def remove(self, adapter):
        self._adapters.pop(adapter.shortcut_id, None)
        if not self._adapters and self._thread:
            self.shutdown()

    def _launch(self):
        if not self._adapters:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="clicky-portals")
        self._thread.start()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._initialize())
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()

    async def _initialize(self):
        items = list(self._adapters.items())
        requests = None
        try:
            from dbus_next import Message, MessageType, Variant

            self._bus = await _connect_bus()
            self._handler = self._handle_signal
            self._bus.add_message_handler(self._handler)
            match = await self._bus.call(Message(
                destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                body=["type='signal',sender='org.freedesktop.portal.Desktop',"
                      f"interface='{_SHORTCUT_IFACE}'"],
            ))
            if match.message_type == MessageType.ERROR:
                raise RuntimeError("Could not subscribe to desktop shortcut events")
            requests = _PortalRequests(self._bus)
            await requests.subscribe()
            token = uuid.uuid4().hex[:16]
            created = await requests.request(
                _SHORTCUT_IFACE, "CreateSession", "a{sv}", [{
                    "handle_token": Variant("s", "clicky_" + token),
                    "session_handle_token": Variant("s", "clicky_session_" + token),
                }],
            )
            handle = created.get("session_handle")
            self._session = handle.value if isinstance(handle, Variant) else handle
            shortcuts = []
            for shortcut_id, adapter in items:
                shortcuts.append((shortcut_id, {
                    "description": Variant("s", adapter.description),
                    "preferred_trigger": Variant("s", _preferred_trigger(adapter.hotkey)),
                }))
            bound = await requests.request(
                _SHORTCUT_IFACE, "BindShortcuts", "oa(sa{sv})sa{sv}",
                [self._session, shortcuts, "", {
                    "handle_token": Variant("s", "clicky_bind_" + token),
                }],
            )
            self._bus.remove_message_handler(requests._handle)
            response = bound.get("shortcuts")
            accepted = response.value if isinstance(response, Variant) else response
            accepted_ids = {item[0] for item in (accepted or [])}
            for shortcut_id, _ in items:
                if shortcut_id not in accepted_ids:
                    self.failure.emit(shortcut_id,
                        "The desktop portal did not bind this shortcut. Use the panel button or choose another key.")
        except Exception as exc:
            _log.info("Wayland portal shortcut registration failed: %s", exc)
            for shortcut_id, _ in items:
                self.failure.emit(shortcut_id, str(exc))
            if self._bus:
                if requests:
                    self._bus.remove_message_handler(requests._handle)
                if self._handler:
                    self._bus.remove_message_handler(self._handler)
                self._bus.disconnect()
                self._bus = None
            asyncio.get_running_loop().call_soon(asyncio.get_running_loop().stop)

    def _handle_signal(self, message):
        if (message.interface == _SHORTCUT_IFACE and
                message.member in ("Activated", "Deactivated") and len(message.body) >= 2):
            shortcut_id = message.body[1]
            if shortcut_id in self._adapters:
                self.event.emit(shortcut_id, message.member == "Activated")
        return False

    def shutdown(self):
        loop, thread = self._loop, self._thread
        if loop and loop.is_running():
            async def close():
                if self._bus and self._session:
                    try:
                        await self._bus.call(Message(
                            destination=_BUS_NAME, path=self._session,
                            interface=_SESSION_IFACE, member="Close",
                        ))
                    except Exception:
                        pass
                if self._bus:
                    if self._handler:
                        self._bus.remove_message_handler(self._handler)
                    self._bus.disconnect()
                loop.call_soon(loop.stop)
            from dbus_next import Message
            future = asyncio.run_coroutine_threadsafe(close(), loop)
            try:
                future.result(timeout=2)
            except Exception:
                loop.call_soon_threadsafe(loop.stop)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = self._loop = None
        self._bus = self._session = self._handler = None


_registry = None


def shortcut_registry():
    global _registry
    if _registry is None:
        _registry = PortalShortcutRegistry()
    return _registry


class PortalShortcut(QObject):
    failed = pyqtSignal(str)

    def __init__(self, hotkey, on_press, on_release=None, *, non_consuming=False):
        super().__init__()
        self.hotkey = hotkey
        self.description = "Clicky push-to-talk" if on_release else "Clicky cancel"
        self.shortcut_id = "clicky_" + uuid.uuid4().hex
        self._press, self._release = on_press, on_release
        self._registry = shortcut_registry()
        self._registry.event.connect(self._on_event)
        self._registry.failure.connect(self._on_failure)

    def start(self):
        try:
            _preferred_trigger(self.hotkey)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        self._registry.add(self)

    @pyqtSlot(str, bool)
    def _on_event(self, shortcut_id, active):
        if shortcut_id != self.shortcut_id:
            return
        callback = self._press if active else self._release
        if callback:
            callback()

    @pyqtSlot(str, str)
    def _on_failure(self, shortcut_id, reason):
        if shortcut_id == self.shortcut_id:
            self.failed.emit(reason)

    def stop(self):
        try:
            self._registry.event.disconnect(self._on_event)
            self._registry.failure.disconnect(self._on_failure)
        except (TypeError, RuntimeError):
            pass
        self._registry.remove(self)
