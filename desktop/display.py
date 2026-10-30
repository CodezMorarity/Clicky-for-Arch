"""Snapshot Qt screen geometry on the GUI thread for capture workers.

Hyprland's logical coordinates and XWayland's coordinates differ when
force_zero_scaling is enabled. Match outputs by name, never divide global
origins by a primary-monitor scale. Windows keeps its existing DPI path.
"""

_screens: dict[str, tuple[int, int, int, int]] = {}


def attach(app) -> None:
    def refresh(*_):
        global _screens
        _screens = {s.name(): s.geometry().getRect() for s in app.screens()}

    def added(screen):
        screen.geometryChanged.connect(refresh)
        refresh()

    for screen in app.screens():
        added(screen)
    app.screenAdded.connect(added)
    app.screenRemoved.connect(refresh)


def geometry(output: dict) -> tuple[int, int, int, int]:
    if output["name"] not in _screens:
        raise RuntimeError(
            f"No Qt screen geometry for {output['name']}. "
            "Start Clicky in the Hyprland desktop using the XWayland Qt backend."
        )
    return _screens[output["name"]]


def bounds() -> tuple[int, int, int, int] | None:
    """Return the union of the logical monitor rectangles cached from Qt."""
    if not _screens:
        return None
    left = min(rect[0] for rect in _screens.values())
    top = min(rect[1] for rect in _screens.values())
    right = max(rect[0] + rect[2] for rect in _screens.values())
    bottom = max(rect[1] + rect[3] for rect in _screens.values())
    return left, top, right - left, bottom - top


def screen_count() -> int:
    return len(_screens)
