"""
Lesson recording.

Captures Clicky lessons as:
  • MP4 video — primary monitor, 8 fps, Clicky's pointer overlaid
  • Markdown transcript — Q&A + timestamps next to the video

Output:  ~/Documents/Clicky Lessons/<timestamp>/

Backend: imageio-ffmpeg (auto-bundles ffmpeg, no system install needed).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from desktop.paths import recordings_dir
from desktop import uses_portal_capture
from screen.capture import capture_primary_image
from PIL import Image


FPS = 8


class LessonRecorder:
    """Headless screen recorder. Markdown transcript built up alongside."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._writer = None
        self._md_lines: list[str] = []
        self._t0: float = 0.0
        self._out_dir: Optional[Path] = None
        self.is_recording = False
        self.last_error = ""
        self.on_error = None

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> Optional[Path]:
        """Begin recording. Returns the output directory or None on failure."""
        if self.is_recording:
            return self._out_dir
        if uses_portal_capture():
            self.last_error = (
                "Continuous lesson recording is not available through this desktop's "
                "one-shot screenshot portal. Use a supported wlroots compositor or X11."
            )
            return None

        try:
            import imageio_ffmpeg   # noqa: F401  (required by imageio[ffmpeg])
            import imageio
        except ImportError:
            return None

        self.last_error = ""
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        self._out_dir = recordings_dir() / ts
        try:
            first = capture_primary_image()
            # H.264 requires even dimensions; keep one size through hotplug.
            self._size = (first.width // 2 * 2, first.height // 2 * 2)
            self._out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._writer = imageio.get_writer(
                str(self._out_dir / "lesson.mp4"), fps=FPS, codec="libx264",
                quality=7, macro_block_size=None,
            )
            self._writer.append_data(_to_array(first.resize(self._size)))
        except Exception as exc:
            self.last_error = str(exc)
            if self._writer:
                self._writer.close()
                self._writer = None
            return None
        self._md_lines = [f"# Clicky Lesson — {ts}", ""]
        self._t0 = time.monotonic()
        self._stop_evt.clear()
        self.is_recording = True

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self._out_dir

    def stop(self) -> Optional[Path]:
        """Stop and flush. Returns the output directory."""
        if self._thread is None:
            return None
        self._stop_evt.set()
        self._thread.join(timeout=12.0)
        if self._thread.is_alive():
            self.last_error = "Recorder is still flushing; please wait before quitting."
            return None
        self._thread = None
        self.is_recording = False
        return self._out_dir

    # ── Transcript hooks (manager calls these) ──────────────────────────────

    def log_question(self, q: str):
        if self.is_recording:
            t = time.monotonic() - self._t0
            self._md_lines.append(f"\n## [{t:6.1f}s] Q: {q}\n")

    def log_answer(self, a: str):
        if self.is_recording:
            self._md_lines.append(f"**A:** {a.strip()}\n")

    # ── Internal ────────────────────────────────────────────────────────────

    def _loop(self):
        interval = 1.0 / FPS
        try:
            while not self._stop_evt.is_set():
                started = time.monotonic()
                img = capture_primary_image().resize(self._size)
                self._writer.append_data(_to_array(img))
                self._stop_evt.wait(max(0, interval - (time.monotonic() - started)))
        except Exception as exc:
            self.last_error = str(exc)
            logging.getLogger("clicky.recorder").exception("Recording failed")
            if self.on_error:
                self.on_error(self.last_error)
        finally:
            try:
                self._writer.close()
            finally:
                self._writer = None
                (self._out_dir / "transcript.md").write_text(
                    "\n".join(self._md_lines), encoding="utf-8")
                self.is_recording = False


def _to_array(img: Image.Image):
    import numpy as np
    return np.array(img)
