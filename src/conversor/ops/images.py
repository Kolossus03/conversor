"""Image operations. Runs only inside the sandboxed worker process."""

import tempfile
import warnings
from pathlib import Path

import pillow_heif
import resvg_py
from PIL import Image, ImageOps

from ..safepaths import write_new_file

try:
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:  # its native DLL can be blocked by Windows Smart App Control
    HEIF_AVAILABLE = False

# Decompression bombs: refuse anything above ~150 megapixels instead of only warning.
Image.MAX_IMAGE_PIXELS = 150_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)

MAX_SVG_BYTES = 20 * 1024 * 1024
MAX_SVG_SIDE = 8192

# Pillow format names for our target extensions.
_PIL_FORMAT = {
    "png": "PNG", "jpg": "JPEG", "webp": "WEBP", "avif": "AVIF", "ico": "ICO",
    "pdf": "PDF", "bmp": "BMP", "tiff": "TIFF", "gif": "GIF",
}
# Format to write when a tool keeps "the same" format as the input.
_SAME_TARGET = {
    "png": "png", "jpeg": "jpg", "webp": "webp", "avif": "avif", "heic": "jpg",
    "svg": "png", "ico": "png", "gif": "gif", "bmp": "bmp", "tiff": "tiff",
}


class ImageError(ValueError):
    pass


def load(path: Path, fmt: str, min_side: int = 0) -> Image.Image:
    if fmt == "svg":
        return _render_svg(path, min_side)
    if fmt == "heic" and not HEIF_AVAILABLE:
        # pillow-heif's DLL can be blocked by Smart App Control; ffmpeg decodes HEIC too.
        from .media import still_image

        return still_image(path, "heic")
    im = Image.open(path)
    im.load()
    return ImageOps.exif_transpose(im)


def _render_svg(path: Path, min_side: int) -> Image.Image:
    data = path.read_bytes()
    if len(data) > MAX_SVG_BYTES:
        raise ImageError("SVG file is too large")
    if b"<!ENTITY" in data:
        raise ImageError("SVG files with entity declarations are not supported (unsafe)")
    text = data.decode("utf-8", errors="replace")
    # Empty resources dir: the SVG cannot pull in other files from disk.
    with tempfile.TemporaryDirectory() as empty:
        def render(**size) -> Image.Image:
            png = resvg_py.svg_to_bytes(svg_string=text, resources_dir=empty, **size)
            with tempfile.SpooledTemporaryFile() as buf:
                buf.write(bytes(png))
                buf.seek(0)
                img = Image.open(buf)
                img.load()
                return img

        im = render()
        longest = max(im.size)
        want = min(max(min_side, longest), MAX_SVG_SIDE)
        if want != longest:
            scale = want / longest
            im = render(width=max(1, round(im.width * scale)), height=max(1, round(im.height * scale)))
        return im


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)


def _flatten(im: Image.Image, color=(255, 255, 255)) -> Image.Image:
    if _has_alpha(im):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, color)
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return im.convert("RGB")


def _square(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    side = max(im.size)
    if im.width == im.height:
        return im
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return canvas


_GIF_CLEAR = 255  # palette slot reserved for "transparent"


def _to_gif_frame(im: Image.Image) -> Image.Image:
    """GIF has 256 colours and on/off transparency: use 255 colours, keep slot 255 for clear pixels."""
    rgba = im.convert("RGBA")
    frame = rgba.convert("RGB").quantize(255, dither=Image.Dither.FLOYDSTEINBERG)
    clear = rgba.getchannel("A").point(lambda a: 255 if a < 128 else 0)
    frame.paste(_GIF_CLEAR, mask=clear)
    return frame


def _is_animated(im: Image.Image) -> bool:
    return getattr(im, "n_frames", 1) > 1


def save(im: Image.Image, target: str, tmp: Path, *, quality: int = 90, exif: bytes | None = None,
         icc: bytes | None = None, ico_sizes=None, reduce_colors: bool = False,
         jpeg_keep: bool = False) -> None:
    fmt = _PIL_FORMAT[target]
    extra = {}
    if exif and target in ("jpg", "webp", "avif", "png", "tiff"):
        extra["exif"] = exif
    if icc and target in ("jpg", "webp", "avif", "png", "tiff"):
        extra["icc_profile"] = icc

    if target == "jpg":
        if not jpeg_keep:  # "keep" needs the original JPEG object, which is already RGB/L/CMYK
            im = _flatten(im)
        q = "keep" if jpeg_keep else quality
        im.save(tmp, fmt, quality=q, optimize=not jpeg_keep, progressive=True, **extra)
    elif target == "png":
        if reduce_colors:
            rgba = im.convert("RGBA")
            im = rgba.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
        elif im.mode not in ("RGB", "RGBA", "L", "LA", "P", "I;16"):
            im = im.convert("RGBA" if _has_alpha(im) else "RGB")
        im.save(tmp, fmt, optimize=True, **extra)
    elif target in ("webp", "avif"):
        im = im.convert("RGBA" if _has_alpha(im) else "RGB")
        opts = {"lossless": True} if target == "webp" and quality >= 100 else {"quality": quality}
        im.save(tmp, fmt, **opts, **extra)
    elif target == "ico":
        sizes = sorted({int(s) for s in (ico_sizes or [16, 32, 48, 256]) if 8 <= int(s) <= 256})
        sq = _square(im)
        if sq.width < max(sizes):  # upscale small sources so every requested size exists
            sq = sq.resize((max(sizes), max(sizes)), Image.Resampling.LANCZOS)
        sq.save(tmp, fmt, sizes=[(s, s) for s in sizes])
    elif target == "pdf":
        _flatten(im).save(tmp, fmt, resolution=96)
    elif target == "gif":
        _to_gif_frame(im).save(tmp, fmt, transparency=_GIF_CLEAR)
    elif target == "bmp":
        im.convert("RGBA" if _has_alpha(im) else "RGB").save(tmp, fmt)
    elif target == "tiff":
        if im.mode not in ("RGB", "RGBA", "L", "LA", "CMYK"):
            im = im.convert("RGBA" if _has_alpha(im) else "RGB")
        im.save(tmp, fmt, compression="tiff_lzw", **extra)
    else:
        raise ImageError(f"Unsupported target: {target}")


def _metadata(im: Image.Image) -> tuple[bytes | None, bytes | None]:
    exif = im.getexif()
    return (exif.tobytes() if len(exif) else None), im.info.get("icc_profile")


def convert(src: Path, fmt: str, target: str, options: dict, out_dir: Path, ctx) -> Path:
    if target not in _PIL_FORMAT:
        raise ImageError(f"Unknown target format: {target}")
    quality = int(options.get("quality", 90))

    if fmt in ("gif", "webp", "png") and target in ("gif", "webp"):  # png: animated PNG (APNG)
        im = Image.open(src)
        if _is_animated(im):
            ctx.progress(0.3)
            kw = {"quality": quality} if target == "webp" else {"optimize": True}
            return write_new_file(out_dir, src.stem, target,
                                  lambda tmp: im.save(tmp, _PIL_FORMAT[target], save_all=True, **kw))

    im = load(src, fmt, min_side=256 if target == "ico" else 0)
    ctx.progress(0.4)
    exif, icc = _metadata(im) if options.get("keep_metadata") else (None, im.info.get("icc_profile"))
    return write_new_file(
        out_dir, src.stem, target,
        lambda tmp: save(im, target, tmp, quality=quality, exif=exif, icc=icc,
                         ico_sizes=options.get("ico_sizes")),
    )


def resize(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    im = load(src, fmt)
    exif, icc = _metadata(im)
    w, h = im.size
    if options.get("mode") == "Percent":
        scale = int(options.get("percent", 50)) / 100
    else:
        scale = int(options.get("size", 1920)) / max(w, h)
    new = (max(1, round(w * scale)), max(1, round(h * scale)))
    if new[0] * new[1] > Image.MAX_IMAGE_PIXELS:
        raise ImageError("Resulting image would be too large")
    ctx.progress(0.4)
    im = im.resize(new, Image.Resampling.LANCZOS)
    target = _SAME_TARGET[fmt]
    return write_new_file(out_dir, f"{src.stem} (resized)", target,
                          lambda tmp: save(im, target, tmp, quality=92, exif=exif, icc=icc))


def _fit_size(im: Image.Image, target_bytes: int, exif, icc, ctx) -> tuple[bytes, str]:
    """Smallest-effort encoding under target_bytes: binary-search the quality, then shrink if needed."""
    import io

    fmt = "webp" if _has_alpha(im) else "jpg"
    best = None
    for step in range(12):
        lo, hi = 10, 95
        while lo <= hi:  # highest quality that still fits
            q = (lo + hi) // 2
            buf = io.BytesIO()
            save(im, fmt, buf, quality=q, exif=exif, icc=icc)
            if buf.tell() <= target_bytes:
                best, lo = buf.getvalue(), q + 1
            else:
                hi = q - 1
        if best is not None:
            return best, fmt
        im = im.resize((max(1, int(im.width * 0.8)), max(1, int(im.height * 0.8))), Image.Resampling.LANCZOS)
        ctx.progress(min(0.9, 0.4 + step * 0.05))
    raise ImageError("Couldn't get the image that small")


def compress(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    im = load(src, fmt)
    exif, icc = _metadata(im)
    ctx.progress(0.4)
    if options.get("mode") == "Target size":
        data, ext = _fit_size(im, int(float(options.get("target_kb", 1000)) * 1000), exif, icc, ctx)
        return write_new_file(out_dir, f"{src.stem} (compressed)", ext, lambda tmp: tmp.write_bytes(data))
    target = _SAME_TARGET[fmt]
    return write_new_file(
        out_dir, f"{src.stem} (compressed)", target,
        lambda tmp: save(im, target, tmp, quality=int(options.get("quality", 75)), exif=exif, icc=icc,
                         reduce_colors=bool(options.get("reduce_colors"))),
    )


def strip_metadata(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    jpeg_keep = False
    if fmt == "jpeg":
        raw = Image.open(src)
        raw.load()
        # Re-use the original JPEG quantization (no visible quality loss) unless it needs rotating.
        jpeg_keep = raw.getexif().get(0x0112, 1) == 1
    im = raw if jpeg_keep else load(src, fmt)
    icc = im.info.get("icc_profile")
    ctx.progress(0.4)
    target = _SAME_TARGET[fmt]
    return write_new_file(
        out_dir, f"{src.stem} (clean)", target,
        lambda tmp: save(im, target, tmp, quality=95, icc=icc, jpeg_keep=jpeg_keep),
    )


def preview(src: Path, fmt: str, dest: Path, max_side: int) -> Path:
    """Small PNG rendered in the sandbox so the UI never decodes untrusted files itself."""
    im = load(src, fmt)
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    im.convert("RGBA").save(dest, "PNG")
    return dest
