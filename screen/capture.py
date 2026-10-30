"""
Multi-monitor screenshot helper.

The tricky part is keeping THREE coordinate systems straight:

  1. PHYSICAL  — what mss.grab() returns. Real GPU pixels. e.g. 2560x1440.
  2. LOGICAL   — what the OS / Qt cursor uses after DPI scaling. e.g. 1707x960
                 on a 150%-DPI 2560x1440 display.
  3. DOWNSCALED — what we send to the LLM (1280-wide JPEG to keep tokens low).

The overlay plots in LOGICAL coordinates. The element-detector model sees the
downscaled image. So `detect_element` must return coords in LOGICAL space, with
the monitor's logical-origin offset applied for multi-monitor setups.

ScreenShot now carries every number needed to convert between them.
"""

import base64
import ctypes
import io
import shutil
import subprocess
from dataclasses import dataclass
from typing import List

from PIL import Image
from desktop import is_hyprland, is_sway, is_wayland, uses_portal_capture


@dataclass
class ScreenShot:
    index: int

    # Downscaled image actually sent to the LLM
    width: int            # downscaled width (pixels in JPEG)
    height: int           # downscaled height
    base64_jpeg: str

    # Real (physical) monitor size and origin in mss virtual-screen coords
    physical_width: int
    physical_height: int
    physical_left: int    # mss-reported origin (physical px)
    physical_top: int

    # DPI scale (physical / logical). 1.0 on normal displays, 1.5 on 150% DPI.
    dpi_scale: float

    # Convenience: where this monitor's top-left sits in LOGICAL screen space
    logical_left: int
    logical_top: int
    coordinate_scale_x: float | None = None
    coordinate_scale_y: float | None = None

    def image_to_overlay(self, x: float, y: float) -> tuple[int, int]:
        scale_x = self.coordinate_scale_x or self.dpi_scale
        scale_y = self.coordinate_scale_y or self.dpi_scale
        return (round(self.logical_left + x / self.width * self.physical_width / scale_x),
                round(self.logical_top + y / self.height * self.physical_height / scale_y))


def capture_frames():
    """Yield full-resolution RGB images and their overlay coordinate metadata."""
    if is_wayland() and (is_hyprland() or is_sway()):
        if not shutil.which("grim"):
            raise RuntimeError("Wayland screen capture requires grim (install the Arch package 'grim').")
        from desktop.display import geometry
        if is_hyprland():
            from desktop.hyprland import monitors
            outputs = monitors()
        else:
            from desktop.sway import outputs
            outputs = outputs()
        if not outputs:
            raise RuntimeError("The Wayland compositor has no active outputs to capture.")
        for index, output in enumerate(outputs, 1):
            if is_hyprland():
                left, top, width, height = geometry(output)
                scale = output["scale"]
            else:
                rect = output["rect"]
                left, top = rect["x"], rect["y"]
                width, height = rect["width"], rect["height"]
                scale = output.get("scale", 1.0)
            result = subprocess.run(
                ["grim", "-o", output["name"], "-s", str(scale), "-"],
                capture_output=True, timeout=5,
            )
            if result.returncode:
                raise RuntimeError("Wayland capture failed: " + result.stderr.decode(errors="replace"))
            img = Image.open(io.BytesIO(result.stdout)).convert("RGB")
            scale = img.width / width
            if abs(img.height / scale - height) > 2:
                raise RuntimeError(
                    "Qt and compositor output geometry disagree; restart Clicky "
                    "after changing monitors."
                )
            yield index, img, round(left * scale), round(top * scale), scale, left, top
        return
    if uses_portal_capture():
        from desktop.display import bounds
        from desktop.portals import screenshot_image
        img = screenshot_image()
        bounds_rect = bounds()
        if bounds_rect:
            left, top, logical_width, logical_height = bounds_rect
            scale_x = img.width / max(1, logical_width)
            scale_y = img.height / max(1, logical_height)
        else:
            left = top = 0
            logical_width, logical_height = img.size
            scale_x = scale_y = 1.0
        # The portal returns a virtual desktop image. A single linear mapping
        # cannot describe mixed-scale monitors, so overlays are disabled when
        # the desktop does not expose reliable XWayland placement.
        scale = (scale_x + scale_y) / 2
        yield 1, img, 0, 0, scale, left, top, scale_x, scale_y
        return
    import mss
    dpi = _query_dpi_scale()
    with mss.mss() as sct:
        for index, monitor in enumerate(sct.monitors[1:], 1):
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            left, top = monitor["left"], monitor["top"]
            yield index, img, left, top, dpi, round(left / dpi), round(top / dpi)


def capture_primary_image() -> Image.Image:
    return next(capture_frames())[1]


def _query_dpi_scale() -> float:
    """Best-effort DPI scale for the primary monitor.
    Returns 1.0 if anything goes wrong."""
    try:
        # GetDpiForSystem returns DPI as integer (96 = 100%, 144 = 150%)
        u = ctypes.windll.user32
        u.SetProcessDPIAware()
        gdfs = getattr(u, "GetDpiForSystem", None)
        if gdfs:
            return max(1.0, gdfs() / 96.0)
        # Fallback: ratio of GetSystemMetrics(physical) vs (logical)
        return 1.0
    except Exception:
        return 1.0


def capture_all_screens(max_width: int = 1280) -> List[ScreenShot]:
    """Capture all monitors. Each ScreenShot carries everything needed
    to convert detection coords back into logical screen space."""
    results = []
    for frame in capture_frames():
        i, img, phys_left, phys_top, dpi, logical_left, logical_top = frame[:7]
        scale_x = frame[7] if len(frame) > 7 else None
        scale_y = frame[8] if len(frame) > 8 else None
        phys_w, phys_h = img.size
        if img.width > max_width:
            img = img.resize((max_width, max(1, round(img.height * max_width / img.width))),
                             Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        results.append(ScreenShot(
            index=i, width=img.width, height=img.height,
            base64_jpeg=base64.b64encode(buf.getvalue()).decode("ascii"),
            physical_width=phys_w, physical_height=phys_h,
            physical_left=phys_left, physical_top=phys_top, dpi_scale=dpi,
            logical_left=logical_left, logical_top=logical_top,
            coordinate_scale_x=scale_x, coordinate_scale_y=scale_y,
        ))

    return results


def capture_primary() -> ScreenShot:
    """Capture only the primary monitor."""
    screens = capture_all_screens()
    return screens[0] if screens else None


def screen_count() -> int:
    if is_hyprland() or is_sway():
        if is_hyprland():
            from desktop.hyprland import monitors
            return len(monitors())
        from desktop.sway import outputs
        return len(outputs())
    if uses_portal_capture():
        from desktop.display import screen_count
        return screen_count()
    import mss
    with mss.mss() as sct:
        return len(sct.monitors) - 1
