"""Worker process: parses untrusted files so the UI process never has to.

Launched by sandbox.py inside a Windows Job Object. Reads one JSON job from stdin,
writes one JSON event per line to stdout.
"""

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

from .appdirs import cache_dir
from .safepaths import UnsafePath, check_input, check_output_dir


class Emitter:
    def __init__(self) -> None:
        # Keep the real stdout for the protocol; anything libraries print goes to stderr.
        self._out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
        os.dup2(2, 1)
        sys.stdout = sys.stderr

    def __call__(self, **event) -> None:
        self._out.write(json.dumps(event) + "\n")
        self._out.flush()


class Context:
    def __init__(self, emit: Emitter, task_id: str, gpu: bool, kind: str = "") -> None:
        self._emit, self.id, self.gpu, self.kind = emit, task_id, gpu, kind
        self.extra: dict = {}

    def office_process(self, pid: int) -> None:
        """Office runs outside our sandbox; tell the app so it can clean up after us."""
        self._emit(event="office", pid=pid)

    def progress(self, value: float) -> None:
        self._emit(id=self.id, event="progress", progress=round(value, 3))

    def compare(self, before, after) -> None:
        folder = cache_dir() / "previews"
        folder.mkdir(parents=True, exist_ok=True)
        paths = {}
        stem = hashlib.sha1(self.id.encode()).hexdigest()[:16]
        for name, im in (("before", before), ("after", after)):
            im = im.copy()
            im.thumbnail((1600, 1600))
            dest = folder / f"{stem}-{name}.png"
            im.save(dest, "PNG")
            paths[name] = str(dest)
        self.extra["compare"] = paths


def _friendly(exc: BaseException) -> str:
    from PIL import Image, UnidentifiedImageError

    if isinstance(exc, (Image.DecompressionBombError, Image.DecompressionBombWarning)):
        return "Image is too large (over 150 megapixels)"
    if isinstance(exc, UnidentifiedImageError):
        return "File is damaged or not a supported image"
    if isinstance(exc, MemoryError):
        return "Not enough memory for this file"
    if isinstance(exc, (UnsafePath, ValueError, RuntimeError, OSError)) and str(exc):
        return str(exc)[:300]
    return f"{type(exc).__name__}: {exc}"[:300]


def _thumb(src: Path, kind: str, fmt: str) -> Path:
    from .ops import images

    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
    dest = cache_dir() / "thumbs" / f"{key}.png"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "pdf":
            from .ops import pdf

            pdf.preview(src, dest, 128)
        elif kind == "video":
            from .ops import media

            im = media.still_image(src, fmt)
            im.thumbnail((128, 128))
            im.save(dest, "PNG")
        else:
            images.preview(src, fmt, dest, 128)
    return dest


def _operation(op: str):
    """Map an operation id to f(srcs, fmts, target, options, out_dir, ctx). Imports lazily."""
    from .ops import background, data, images, media, ocr, office, pdf, upscale

    single = {
        "image.convert": lambda s, f, t, o, d, c: images.convert(s, f, t, o, d, c),
        "image.resize": lambda s, f, t, o, d, c: images.resize(s, f, o, d, c),
        "image.compress": lambda s, f, t, o, d, c: images.compress(s, f, o, d, c),
        "image.strip": lambda s, f, t, o, d, c: images.strip_metadata(s, f, o, d, c),
        "image.remove_bg": lambda s, f, t, o, d, c: background.remove_background(s, f, o, d, c),
        "image.upscale": lambda s, f, t, o, d, c: upscale.upscale(s, f, o, d, c),
        "image.ocr": lambda s, f, t, o, d, c: ocr.image_to_text(s, f, o, d, c),
        "pdf.ocr": lambda s, f, t, o, d, c: ocr.pdf_to_text(s, o, d, c),
        "data.convert": data.convert,
        "document.convert": office.convert_document,
        "spreadsheet.convert": office.convert_spreadsheet,
        "presentation.convert": office.convert_presentation,
        "pdf.convert": _pdf_convert,
        "pdf.split": lambda s, f, t, o, d, c: pdf.split(s, o, d, c),
        "pdf.rotate": lambda s, f, t, o, d, c: pdf.rotate(s, o, d, c),
        "pdf.compress": lambda s, f, t, o, d, c: pdf.compress(s, o, d, c),
        "pdf.protect": lambda s, f, t, o, d, c: pdf.protect(s, o, d, c),
        "pdf.unlock": lambda s, f, t, o, d, c: pdf.unlock(s, o, d, c),
        "video.convert": media.convert_video,
        "video.trim": lambda s, f, t, o, d, c: media.trim(s, f, o, d, c),
        "video.compress": lambda s, f, t, o, d, c: media.compress_video(s, f, o, d, c),
        "video.mute": lambda s, f, t, o, d, c: media.remove_audio(s, f, o, d, c),
        "audio.convert": media.convert_audio,
        "audio.trim": lambda s, f, t, o, d, c: media.trim(s, f, o, d, c),
        "audio.normalize": lambda s, f, t, o, d, c: media.normalize(s, f, o, d, c),
    }
    combined = {
        "pdf.merge": lambda ss, fs, t, o, d, c: pdf.merge(ss, o, d, c),
        "image.to_pdf": lambda ss, fs, t, o, d, c: pdf.images_to_pdf(ss, fs, o, d, c),
    }
    if op in single:
        return False, single[op]
    if op in combined:
        return True, combined[op]
    raise ValueError(f"Unknown operation: {op}")


def _pdf_convert(src, fmt, target, options, out_dir, ctx):
    from .ops import office, pdf

    if target == "docx":
        return office.pdf_to_docx(src, out_dir, ctx)
    if target == "txt":
        return pdf.to_text(src, out_dir, ctx)
    if target in ("png", "jpg"):
        return pdf.to_images(src, target, options, out_dir, ctx)
    raise ValueError(f"Unknown target: {target}")


def run_task(task: dict, ctx: Context) -> dict:
    op = task["op"]
    if op == "model.download":
        from . import models

        models.download(task["model"], ctx.progress)
        return {}
    if op == "thumb":
        return {"thumb": str(_thumb(check_input(task["input"]), task.get("kind", "image"), task["fmt"]))}

    out_dir = check_output_dir(task["out_dir"])
    options = task.get("options") or {}
    combine, run = _operation(op)
    if combine:
        srcs = [check_input(p) for p in task["inputs"]]
        out = run(srcs, task["fmts"], task.get("target"), options, out_dir, ctx)
    else:
        out = run(check_input(task["input"]), task["fmt"], task.get("target"), options, out_dir, ctx)
    size = sum(f.stat().st_size for f in out.iterdir()) if out.is_dir() else out.stat().st_size
    return {"output": str(out), "size": size, "folder": out.is_dir()}


def main() -> int:
    emit = Emitter()
    job = json.loads(sys.stdin.readline())
    gpu = bool(job.get("settings", {}).get("gpu", True))
    for task in job["tasks"]:
        ctx = Context(emit, task["id"], gpu, task.get("kind", ""))
        emit(id=ctx.id, event="start")
        try:
            result = run_task(task, ctx)
            emit(id=ctx.id, event="done", **result, **ctx.extra)
        except Exception as exc:  # report per file, keep going with the rest of the batch
            traceback.print_exc()
            emit(id=ctx.id, event="error", message=_friendly(exc))
    if "conversor.ops.office" in sys.modules:
        sys.modules["conversor.ops.office"].shutdown()
    emit(event="exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
