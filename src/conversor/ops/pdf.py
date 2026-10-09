"""PDF operations: pdfium (rendering, text) and qpdf via pikepdf (structure). Worker only."""

import io
import shutil
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
from PIL import Image

from ..safepaths import new_output_dir, write_new_file
from .images import load as load_image

MAX_PAGES = 5000
MAX_RENDER_PIXELS = 60_000_000

ROTATIONS = {"90° right": 90, "180°": 180, "90° left": 270}
COMPRESSION = {"Strong": (45, 1200), "Balanced": (65, 2000), "Light": (82, 3000)}  # JPEG quality, max side


class PdfError(ValueError):
    pass


def _open(src: Path, password: str = "") -> pikepdf.Pdf:
    try:
        pdf = pikepdf.open(src, password=password)
    except pikepdf.PasswordError:
        raise PdfError("Wrong password" if password else
                       "This PDF is password-protected. Use the Unlock tool first.") from None
    except pikepdf.PdfError as exc:
        raise PdfError(f"This PDF is damaged: {str(exc)[:150]}") from None
    if len(pdf.pages) > MAX_PAGES:
        raise PdfError(f"PDFs over {MAX_PAGES} pages are not supported")
    return pdf


def _save(pdf: pikepdf.Pdf, out_dir: Path, stem: str, **kw) -> Path:
    return write_new_file(out_dir, stem, "pdf", lambda tmp: pdf.save(tmp, **kw))


def _in_new_folder(out_dir: Path, name: str, fill) -> Path:
    folder = new_output_dir(out_dir, name)
    try:
        fill(folder)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def _pdfium(src: Path) -> pdfium.PdfDocument:
    try:
        doc = pdfium.PdfDocument(src)
    except pdfium.PdfiumError as exc:
        msg = str(exc).lower()
        raise PdfError("This PDF is password-protected. Use the Unlock tool first." if "password" in msg
                       else "This PDF is damaged or not supported") from None
    if len(doc) > MAX_PAGES:
        raise PdfError(f"PDFs over {MAX_PAGES} pages are not supported")
    return doc


def to_images(src: Path, target: str, options: dict, out_dir: Path, ctx) -> Path:
    dpi = int(str(options.get("dpi", "150")).split()[0])
    quality = int(options.get("quality", 90))
    doc = _pdfium(src)

    def fill(folder: Path) -> None:
        total = len(doc)
        for i in range(total):
            page = doc[i]
            w, h = page.get_size()
            scale = dpi / 72
            if w * h * scale * scale > MAX_RENDER_PIXELS:
                scale = (MAX_RENDER_PIXELS / (w * h)) ** 0.5
            im = page.render(scale=scale).to_pil()
            name = folder / f"{src.stem} - page {i + 1:03d}.{target}"
            if target == "jpg":
                im.convert("RGB").save(name, "JPEG", quality=quality, optimize=True)
            else:
                im.save(name, "PNG", optimize=True)
            ctx.progress((i + 1) / total)

    try:
        return _in_new_folder(out_dir, f"{src.stem} (pages)", fill)
    finally:
        doc.close()


def to_text(src: Path, out_dir: Path, ctx) -> Path:
    doc = _pdfium(src)
    try:
        parts = []
        for i in range(len(doc)):
            parts.append(doc[i].get_textpage().get_text_bounded())
            ctx.progress((i + 1) / len(doc))
        text = "\n\n".join(p.replace("\r\n", "\n") for p in parts)
    finally:
        doc.close()
    if not text.strip():
        raise PdfError("This PDF has no text layer (it is probably scanned). Use the \"Read scanned text\" tool instead.")
    return write_new_file(out_dir, src.stem, "txt", lambda tmp: tmp.write_text(text, encoding="utf-8"))


def merge(srcs: list[Path], options: dict, out_dir: Path, ctx) -> Path:
    out = pikepdf.new()
    sources = []  # must stay open until the merged file is saved
    for i, src in enumerate(srcs):
        sources.append(_open(src))
        out.pages.extend(sources[-1].pages)
        ctx.progress((i + 1) / len(srcs) * 0.9)
    if len(out.pages) > MAX_PAGES:
        raise PdfError(f"The merged PDF would be over {MAX_PAGES} pages")
    return _save(out, out_dir, f"{srcs[0].stem} (merged)")


def split(src: Path, options: dict, out_dir: Path, ctx) -> Path:
    pdf = _open(src)

    def fill(folder: Path) -> None:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            single = pikepdf.new()
            single.pages.append(page)
            single.save(folder / f"{src.stem} - page {i + 1:03d}.pdf")
            ctx.progress((i + 1) / total)

    return _in_new_folder(out_dir, f"{src.stem} (pages)", fill)


def parse_pages(text: str, total: int) -> list[int]:
    """'1-3, 7, 10-' -> zero-based page indexes, in document order."""
    chosen: set[int] = set()
    for part in str(text or "").replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                first, last = int(a or 1), int(b or total)
            else:
                first = last = int(part)
        except ValueError:
            raise PdfError(f"Can't read '{part}'. Use page numbers like 1-3, 7") from None
        if first < 1 or last > total or first > last:
            raise PdfError(f"'{part}' is outside this PDF's {total} pages")
        chosen.update(range(first - 1, last))
    if not chosen:
        raise PdfError("Enter the pages in Options, like 1-3, 7")
    return sorted(chosen)


def pick_pages(src: Path, options: dict, out_dir: Path, ctx) -> Path:
    pdf = _open(src)
    pages = parse_pages(options.get("pages", ""), len(pdf.pages))
    remove = options.get("action") == "Remove them"
    keep = [i for i in range(len(pdf.pages)) if (i in pages) != remove]
    if not keep:
        raise PdfError("That would remove every page")
    out = pikepdf.new()
    for i in keep:
        out.pages.append(pdf.pages[i])
    label = "without pages" if remove else "pages"
    return _save(out, out_dir, f"{src.stem} ({label} {str(options.get('pages')).strip()})")


def rotate(src: Path, options: dict, out_dir: Path, ctx) -> Path:
    pdf = _open(src)
    angle = ROTATIONS.get(options.get("angle"), 90)
    for page in pdf.pages:
        page.rotate(angle, relative=True)
    return _save(pdf, out_dir, f"{src.stem} (rotated)")


def _recompress_images(pdf: pikepdf.Pdf, quality: int, max_side: int) -> None:
    seen = set()
    for page in pdf.pages:
        for _, raw in page.images.items():
            if raw.objgen in seen:
                continue
            seen.add(raw.objgen)
            try:
                pimg = pikepdf.PdfImage(raw)
                if pimg.image_mask or pimg.colorspace not in ("/DeviceRGB", "/DeviceGray") or pimg.bits_per_component != 8:
                    continue
                im = pimg.as_pil_image()
            except Exception:  # unusual encodings: leave the image untouched
                continue
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.convert("L" if pimg.colorspace == "/DeviceGray" else "RGB").save(buf, "JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) >= len(raw.read_raw_bytes()):
                continue
            raw.write(data, filter=pikepdf.Name.DCTDecode)
            raw.Width, raw.Height = im.size
            raw.ColorSpace = pikepdf.Name.DeviceGray if im.mode == "L" else pikepdf.Name.DeviceRGB
            raw.BitsPerComponent = 8
            for key in ("/DecodeParms", "/Decode"):
                if key in raw:
                    del raw[key]


def compress(src: Path, options: dict, out_dir: Path, ctx) -> Path:
    quality, max_side = COMPRESSION.get(options.get("level"), COMPRESSION["Balanced"])
    pdf = _open(src)
    _recompress_images(pdf, quality, max_side)
    ctx.progress(0.7)
    buf = io.BytesIO()
    pdf.remove_unreferenced_resources()
    pdf.save(buf, compress_streams=True, recompress_flate=True,
             object_stream_mode=pikepdf.ObjectStreamMode.generate)
    data = buf.getvalue()
    if len(data) >= src.stat().st_size:
        raise PdfError("This PDF is already as small as it can get")
    return write_new_file(out_dir, f"{src.stem} (compressed)", "pdf", lambda tmp: tmp.write_bytes(data))


def protect(src: Path, options: dict, out_dir: Path, ctx) -> Path:
    password = str(options.get("password", ""))
    if len(password) < 4:
        raise PdfError("Choose a password of at least 4 characters (in Options)")
    pdf = _open(src)
    enc = pikepdf.Encryption(user=password, owner=password, R=6)  # AES-256
    return _save(pdf, out_dir, f"{src.stem} (protected)", encryption=enc)


def unlock(src: Path, options: dict, out_dir: Path, ctx) -> Path:
    pdf = _open(src, str(options.get("password", "")))
    if not pdf.is_encrypted:
        raise PdfError("This PDF isn't password-protected")
    return _save(pdf, out_dir, f"{src.stem} (unlocked)")


def images_to_pdf(srcs: list[Path], fmts: list[str], options: dict, out_dir: Path, ctx) -> Path:
    pages = []
    for i, (src, fmt) in enumerate(zip(srcs, fmts)):
        im = load_image(src, fmt)
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, "white")
            flat.paste(rgba, mask=rgba.getchannel("A"))
            im = flat
        pages.append(im.convert("RGB"))
        ctx.progress((i + 1) / len(srcs) * 0.8)
    first, rest = pages[0], pages[1:]
    return write_new_file(out_dir, f"{srcs[0].stem} (combined)", "pdf",
                          lambda tmp: first.save(tmp, "PDF", resolution=96, save_all=True, append_images=rest))


def preview(src: Path, dest: Path, max_side: int) -> Path:
    """First page as a small PNG, for the file list."""
    doc = _pdfium(src)
    try:
        page = doc[0]
        w, h = page.get_size()
        page.render(scale=max_side / max(w, h, 1)).to_pil().save(dest, "PNG")
    finally:
        doc.close()
    return dest
