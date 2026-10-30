"""Local pointer resolution in Qt overlay coordinates.

Windows uses UI Automation then RapidOCR. Linux uses Tesseract. OCR runs on
an existing screenshot so the manager's privacy decision is preserved. The
manager owns the asynchronous vision fallback when local matching fails.
"""

from __future__ import annotations

import base64
import io
import logging
from desktop import is_windows
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

log = logging.getLogger("clicky.pointer")


@dataclass
class Target:
    """A pointing target with exact pixel coordinates in LOGICAL screen space."""
    x: int                # center X
    y: int                # center Y
    bbox: Tuple[int, int, int, int]   # (left, top, right, bottom)
    label: str            # what we matched (button text, control type, etc.)
    source: str           # "uia" | "ocr"
    confidence: float     # 0.0–1.0

    @property
    def center_xy(self) -> Tuple[int, int]:
        return (self.x, self.y)


# ──────────────────────────────────────────────────────────────────────────────
#  TIER 1 — Windows UI Automation
# ──────────────────────────────────────────────────────────────────────────────

_INTERACTIVE_TYPES = {
    # Most reliable click targets in UIA
    "Button", "Hyperlink", "MenuItem", "TabItem", "TreeItem", "ListItem",
    "RadioButton", "CheckBox", "ComboBox", "Edit", "Text",
    "Custom",  # often used by Electron / web apps
}


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _score_match(query: str, element_name: str, element_type: str) -> float:
    """Fuzzy match score 0..1. Boosts:
      - exact substring match in the element name
      - interactive control types
      - whole-word match
    """
    q = _normalize(query)
    name = _normalize(element_name)
    if not q or not name:
        return 0.0
    score = 0.0
    if q == name:
        score = 1.0
    elif q in name:
        score = 0.85
    else:
        # Word overlap
        q_words = set(q.split())
        n_words = set(name.split())
        if q_words and n_words:
            overlap = len(q_words & n_words) / max(len(q_words), 1)
            score = overlap * 0.7
    if element_type in _INTERACTIVE_TYPES:
        score = min(1.0, score + 0.1)
    return score


def _find_via_uia(query: str, min_score: float = 0.5) -> Optional[Target]:
    """Walk the UIA tree for the foreground window + descendants, find best match."""
    try:
        import uiautomation as auto
    except ImportError:
        log.warning("uiautomation not installed — Tier 1 (UIA) disabled")
        return None

    try:
        # Get the focused (foreground) window — pointing is almost always
        # for the active app, and walking the whole desktop is slow.
        root = auto.GetForegroundControl()
        if root is None:
            root = auto.GetRootControl()
    except Exception as e:
        log.debug("UIA root lookup failed: %s", e)
        return None

    best: Optional[Tuple[float, "auto.Control"]] = None
    # Bounded walk — UIA trees can be huge in Chrome/Electron
    queue: List[Tuple["auto.Control", int]] = [(root, 0)]
    visited = 0
    MAX_NODES = 3500
    MAX_DEPTH = 40

    while queue and visited < MAX_NODES:
        node, depth = queue.pop(0)
        visited += 1
        try:
            name = node.Name or ""
            ctrl_type = node.ControlTypeName or ""
            rect = node.BoundingRectangle  # mss/uia returns Rect
        except Exception:
            continue
        # Skip off-screen / zero-size
        if not rect or rect.width() <= 0 or rect.height() <= 0:
            pass
        else:
            score = _score_match(query, name, ctrl_type)
            # Also try AutomationId and HelpText as backup match sources
            if score < 0.85:
                try:
                    aid = getattr(node, "AutomationId", "") or ""
                    if aid:
                        score = max(score, _score_match(query, aid, ctrl_type) * 0.8)
                except Exception:
                    pass
            if score >= min_score and (best is None or score > best[0]):
                best = (score, node)

        if depth < MAX_DEPTH:
            try:
                for child in node.GetChildren():
                    queue.append((child, depth + 1))
            except Exception:
                continue

    if not best:
        log.debug("UIA: no match for %r (scanned %d nodes)", query, visited)
        return None

    score, node = best
    r = node.BoundingRectangle
    cx = int((r.left + r.right) // 2)
    cy = int((r.top + r.bottom) // 2)
    log.info("UIA hit: %r -> %s [%s] @ (%d,%d) score=%.2f",
             query, node.Name, node.ControlTypeName, cx, cy, score)
    return Target(
        x=cx, y=cy,
        bbox=(int(r.left), int(r.top), int(r.right), int(r.bottom)),
        label=node.Name or node.ControlTypeName,
        source="uia",
        confidence=score,
    )


# ──────────────────────────────────────────────────────────────────────────────
#  TIER 2 — Offline OCR (RapidOCR, ONNX)
# ──────────────────────────────────────────────────────────────────────────────

_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        except ImportError:
            log.warning("rapidocr-onnxruntime not installed — Tier 2 (OCR) disabled")
            return None
        except Exception as e:
            log.warning("OCR engine init failed: %s", e)
            return None
    return _ocr_engine


def _find_via_ocr(query: str, screenshot_path: Optional[str] = None,
                  pil_image=None, min_score: float = 0.5) -> Optional[Target]:
    """Run OCR on the primary screen, fuzzy-match the query against detected text."""
    ocr = _get_ocr()
    if ocr is None:
        return None

    try:
        if pil_image is None and screenshot_path is None:
            # Capture primary screen at full resolution
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[1]
                raw = sct.grab(mon)
                from PIL import Image
                pil_image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        import numpy as np
        if pil_image is not None:
            img_arr = np.array(pil_image)
        else:
            img_arr = screenshot_path  # RapidOCR accepts paths directly

        result, _ = ocr(img_arr)
        if not result:
            log.debug("OCR returned no detections")
            return None

        best: Optional[Tuple[float, dict]] = None
        for det in result:
            # RapidOCR format: [bbox(4 corners), text, score]
            try:
                box, text, conf = det
            except Exception:
                continue
            if conf < 0.4:
                continue
            score = _score_match(query, text, "")
            if score >= min_score and (best is None or score > best[0]):
                # Compute bbox from 4 corners
                xs = [int(p[0]) for p in box]
                ys = [int(p[1]) for p in box]
                best = (score, {
                    "text": text,
                    "bbox": (min(xs), min(ys), max(xs), max(ys)),
                    "conf": conf,
                })

        if not best:
            log.debug("OCR: no text matched %r", query)
            return None

        score, hit = best
        l, t, r, b = hit["bbox"]
        cx, cy = (l + r) // 2, (t + b) // 2
        log.info("OCR hit: %r -> %r @ (%d,%d) score=%.2f",
                 query, hit["text"], cx, cy, score)
        return Target(
            x=cx, y=cy, bbox=hit["bbox"],
            label=hit["text"], source="ocr",
            confidence=score * hit["conf"],
        )
    except Exception as e:
        log.warning("OCR tier failed: %s", e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  TIER 3 — Vision LLM grid fallback (delegated to existing element_locator)
# ──────────────────────────────────────────────────────────────────────────────

def _find_tesseract(query: str, image) -> Optional[Target]:
    """Find a word or line using the installed Linux OCR engine."""
    try:
        import pytesseract
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT,
                                        timeout=8)
        lines = {}
        candidates = []
        for i, text in enumerate(data["text"]):
            if not text.strip() or float(data["conf"][i]) < 40:
                continue
            x, y, w, h = (data[k][i] for k in ("left", "top", "width", "height"))
            item = (text, (x, y, x+w, y+h))
            candidates.append(item)
            key = tuple(data[k][i] for k in ("block_num", "par_num", "line_num"))
            lines.setdefault(key, []).append(item)
        for words in lines.values():
            boxes = [w[1] for w in words]
            candidates.append((" ".join(w[0] for w in words),
                               (min(b[0] for b in boxes), min(b[1] for b in boxes),
                                max(b[2] for b in boxes), max(b[3] for b in boxes))))
        if not candidates:
            return None
        text, box = max(candidates, key=lambda c: _score_match(query, c[0], ""))
        score = _score_match(query, text, "")
        if score < 0.5:
            return None
        l, t, r, b = box
        return Target((l+r)//2, (t+b)//2, box, text, "ocr", score)
    except Exception as exc:
        log.debug("Tesseract pointer unavailable: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def find_target(
    query: str,
    *,
    screenshot=None,
    pil_image=None,
    llm_provider=None,
    skip_uia: bool = False,
    skip_ocr: bool = False,
    skip_vision: bool = False,
) -> Optional[Target]:
    """Resolve text with UIA/OCR and return Qt overlay coordinates.

    Legacy llm_provider/skip_vision arguments remain accepted for callers;
    vision is asynchronous and belongs to the companion manager.
    """
    if not query or not query.strip():
        return None

    # Return one coordinate contract: Qt overlay coordinates, including origin.
    if not skip_uia and is_windows():
        target = _find_via_uia(query)
        if target is not None:
            scale = screenshot.dpi_scale if screenshot else 1.0
            target.x, target.y = round(target.x / scale), round(target.y / scale)
            target.bbox = tuple(round(v / scale) for v in target.bbox)
            return target
    if skip_ocr:
        return None
    if screenshot is None:
        # Use the shared capture adapter, never an implicit X11 screenshot.
        from screen.capture import capture_primary
        screenshot = capture_primary()
    if screenshot is None:
        return None
    from PIL import Image
    if pil_image is None:
        pil_image = Image.open(io.BytesIO(base64.b64decode(screenshot.base64_jpeg))).convert("RGB")
    target = (_find_via_ocr(query, pil_image=pil_image) if is_windows()
              else _find_tesseract(query, pil_image))
    if target is None:
        # The caller already owns the asynchronous vision fallback.
        return None
    def convert(x, y):
        return screenshot.image_to_overlay(x * screenshot.width / pil_image.width,
                                           y * screenshot.height / pil_image.height)
    target.x, target.y = convert(target.x, target.y)
    l, t, r, b = target.bbox
    target.bbox = (*convert(l, t), *convert(r, b))
    return target


__all__ = ["Target", "find_target"]
