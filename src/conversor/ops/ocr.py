"""Text recognition (OCR) with RapidOCR's bundled PP-OCR ONNX models. Fully offline."""

import sys
import types
from pathlib import Path

import numpy as np

from ..safepaths import write_new_file


def _install_shapely_stand_in() -> None:
    """RapidOCR imports shapely only for a polygon's area and perimeter, but Windows Smart App
    Control can block shapely's native GEOS DLL. Provide those two numbers with numpy instead."""
    if "shapely.geometry" in sys.modules:
        return

    class Polygon:
        def __init__(self, points):
            self._p = np.asarray(points, dtype=np.float64).reshape(-1, 2)

        @property
        def area(self) -> float:
            x, y = self._p[:, 0], self._p[:, 1]
            return float(abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2)

        @property
        def length(self) -> float:
            return float(np.linalg.norm(self._p - np.roll(self._p, 1, axis=0), axis=1).sum())

    shapely = types.ModuleType("shapely")
    geometry = types.ModuleType("shapely.geometry")
    geometry.Polygon = Polygon
    shapely.geometry = geometry
    sys.modules["shapely"] = shapely
    sys.modules["shapely.geometry"] = geometry


_engine = None


def _ocr():
    global _engine
    if _engine is None:
        _install_shapely_stand_in()
        from rapidocr import RapidOCR

        _engine = RapidOCR(params={"Global.log_level": "error"})
    return _engine


def read_text(im) -> str:
    """Recognised lines in reading order."""
    arr = np.asarray(im.convert("RGB"))[:, :, ::-1]  # RapidOCR expects BGR like OpenCV
    result = _ocr()(arr)
    if result is None or result.txts is None or result.boxes is None:
        return ""
    lines = sorted(zip(result.boxes, result.txts), key=lambda b: (round(float(b[0][0][1]) / 12), float(b[0][0][0])))
    out, last_row = [], None
    for box, text in lines:
        row = round(float(box[0][1]) / 12)
        if last_row is not None and row == last_row:
            out[-1] += " " + text
        else:
            out.append(text)
        last_row = row
    return "\n".join(out)


def image_to_text(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    from .images import load

    ctx.progress(0.2)
    text = read_text(load(src, fmt))
    if not text.strip():
        raise ValueError("No text found in this image")
    return write_new_file(out_dir, src.stem, "txt", lambda tmp: tmp.write_text(text, encoding="utf-8"))


def pdf_to_text(src: Path, options: dict, out_dir: Path, ctx) -> Path:
    """For scanned PDFs: render each page and recognise its text."""
    from .pdf import _pdfium

    doc = _pdfium(src)
    try:
        pages = []
        for i in range(len(doc)):
            pages.append(read_text(doc[i].render(scale=200 / 72).to_pil()))
            ctx.progress((i + 1) / len(doc))
    finally:
        doc.close()
    text = "\n\n".join(pages)
    if not text.strip():
        raise ValueError("No text found in this PDF")
    return write_new_file(out_dir, f"{src.stem} (OCR)", "txt", lambda tmp: tmp.write_text(text, encoding="utf-8"))
