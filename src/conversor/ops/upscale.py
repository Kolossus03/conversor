"""AI upscaling with Real-ESRGAN (BSD-3-Clause), run tile by tile so any image size fits in memory."""

from pathlib import Path

import numpy as np
from PIL import Image

from ..safepaths import write_new_file
from .ai import session
from .images import load

TILE = 256
PAD = 16  # context around each tile, so the seams don't show
MAX_OUTPUT_PIXELS = 100_000_000


class UpscaleError(ValueError):
    pass


def _upscale_rgb(rgb: Image.Image, model_id: str, gpu: bool, progress) -> Image.Image:
    sess = session(model_id, gpu)
    name = sess.get_inputs()[0].name
    src = np.asarray(rgb, dtype=np.float32).transpose(2, 0, 1) / 255.0
    _, h, w = src.shape
    out = np.zeros((3, h * 4, w * 4), dtype=np.float32)
    tiles = [(y, x) for y in range(0, h, TILE) for x in range(0, w, TILE)]
    for n, (y, x) in enumerate(tiles):
        y0, x0 = max(0, y - PAD), max(0, x - PAD)
        y1, x1 = min(h, y + TILE + PAD), min(w, x + TILE + PAD)
        res = sess.run(None, {name: src[None, :, y0:y1, x0:x1]})[0][0]
        ty, tx = (y - y0) * 4, (x - x0) * 4
        th, tw = (min(y + TILE, h) - y) * 4, (min(x + TILE, w) - x) * 4
        out[:, y * 4:y * 4 + th, x * 4:x * 4 + tw] = res[:, ty:ty + th, tx:tx + tw]
        progress(0.1 + 0.85 * (n + 1) / len(tiles))
    return Image.fromarray((out.clip(0, 1).transpose(1, 2, 0) * 255 + 0.5).astype(np.uint8), "RGB")


def upscale(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    from ..registry import required_model

    factor = 2 if options.get("scale") == "2×" else 4
    im = load(src, fmt)
    if im.width * im.height * 16 > MAX_OUTPUT_PIXELS:
        raise UpscaleError("This image is already large; upscaling would exceed 100 megapixels")
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    rgba = im.convert("RGBA")
    big = _upscale_rgb(rgba.convert("RGB"), required_model("image.upscale", options), ctx.gpu, ctx.progress)
    if has_alpha:  # the model only handles colour; scale transparency conventionally
        big.putalpha(rgba.getchannel("A").resize(big.size, Image.Resampling.LANCZOS))
    if factor == 2:
        big = big.resize((im.width * 2, im.height * 2), Image.Resampling.LANCZOS)
    ctx.compare(im, big)
    return write_new_file(out_dir, f"{src.stem} (upscaled {factor}x)", "png",
                          lambda tmp: big.save(tmp, "PNG"))
