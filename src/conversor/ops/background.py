"""AI background removal with BiRefNet on ONNX Runtime (CUDA GPU, CPU fallback)."""

from pathlib import Path

import numpy as np
from PIL import Image

from ..safepaths import write_new_file
from . import ai
from .images import load

_SIZE = 1024
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_REFINE_MAX_PIXELS = 30_000_000


def predict_mask(im: Image.Image, model_id: str, gpu: bool) -> Image.Image:
    session = ai.session(model_id, gpu)
    small = im.convert("RGB").resize((_SIZE, _SIZE), Image.Resampling.BILINEAR)
    x = (np.asarray(small, dtype=np.float32) / 255.0 - _MEAN) / _STD
    x = x.transpose(2, 0, 1)[None]
    out = session.run(None, {session.get_inputs()[0].name: x})[0][0, 0]
    pred = 1.0 / (1.0 + np.exp(-out))
    lo, hi = float(pred.min()), float(pred.max())
    pred = (pred - lo) / max(hi - lo, 1e-6)
    mask = Image.fromarray((pred * 255).astype(np.uint8), mode="L")
    return mask.resize(im.size, Image.Resampling.LANCZOS)


def _box_blur(x: np.ndarray, r: int) -> np.ndarray:
    """Mean filter with a (2r+1) window via integral images; x is HxW or HxWxC."""
    pad = [(r + 1, r), (r + 1, r)] + [(0, 0)] * (x.ndim - 2)
    s = np.pad(x, pad, mode="edge").astype(np.float64)
    s = s.cumsum(0).cumsum(1)
    k = 2 * r + 1
    out = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    return (out / (k * k)).astype(np.float32)


def _estimate_foreground(image: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Approximate fast foreground colour estimation (Forte & Pitié, 2021).

    Removes the halo of old background colour that otherwise bleeds into soft edges.
    """
    a = alpha[..., None]

    def step(F, B, r):
        blur_a = _box_blur(a, r)
        blur_F = _box_blur(F * a, r) / (blur_a + 1e-5)
        blur_B = _box_blur(B * (1 - a), r) / ((1 - blur_a) + 1e-5)
        F = blur_F + a * (image - a * blur_F - (1 - a) * blur_B)
        return np.clip(F, 0, 1), blur_B

    F, blur_B = step(image, image, 90)
    F, _ = step(F, blur_B, 6)
    return F


def remove_background(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    from ..registry import required_model

    im = original = load(src, fmt).convert("RGB")
    ctx.progress(0.15)
    mask = predict_mask(im, required_model("image.remove_bg", options), ctx.gpu)
    ctx.progress(0.7)

    if im.width * im.height <= _REFINE_MAX_PIXELS:
        rgb = np.asarray(im, dtype=np.float32) / 255.0
        alpha = np.asarray(mask, dtype=np.float32) / 255.0
        fg = _estimate_foreground(rgb, alpha)
        im = Image.fromarray((fg * 255 + 0.5).astype(np.uint8), mode="RGB")
    ctx.progress(0.9)

    full = im.convert("RGBA")
    full.putalpha(mask)
    result = full
    if options.get("crop"):
        bbox = mask.point(lambda v: 255 if v > 10 else 0).getbbox()
        if bbox:
            result = full.crop(bbox)

    out = write_new_file(out_dir, f"{src.stem} (no background)", "png",
                         lambda tmp: result.save(tmp, "PNG", optimize=False))
    ctx.compare(original, full)
    return out
