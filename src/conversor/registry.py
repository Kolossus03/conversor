"""What the app can do, as plain data. The UI builds itself from this; the worker executes it."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    type: str  # "slider" | "choice" | "toggle" | "number" | "multi" | "password" | "text"
    default: Any
    choices: tuple = ()
    min: int = 0
    max: int = 100
    step: int = 1
    suffix: str = ""
    targets: tuple[str, ...] = ()  # only shown for these convert targets; empty = always
    when: tuple = ()  # (other_key, value): only shown while that option has that value
    secret: bool = False  # e.g. passwords: kept in memory only, never written to settings

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "type": self.type, "default": self.default,
            "choices": list(self.choices), "min": self.min, "max": self.max, "step": self.step,
            "suffix": self.suffix, "targets": list(self.targets), "when": list(self.when),
            "secret": self.secret,
        }


@dataclass(frozen=True)
class Operation:
    id: str
    label: str
    kind: str
    role: str  # "convert" | "tool"
    options: tuple[Option, ...] = ()
    model: str | None = None  # AI model required, see models.py
    hint: str = ""
    targets: tuple[str, ...] = field(default=())
    combine: bool = False  # all files of the group go into one output (e.g. merge PDFs)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "role": self.role, "hint": self.hint,
            "model": self.model, "options": [o.to_dict() for o in self.options],
        }


IMAGE_TARGETS = ("png", "jpg", "webp", "ico", "pdf", "avif", "bmp", "tiff", "gif")

# Most useful targets first, per input format. The first one is preselected.
_PREFERRED = {
    "png": ("ico", "jpg", "webp", "pdf"),
    "jpeg": ("png", "webp", "pdf", "ico"),
    "webp": ("png", "jpg", "gif"),
    "avif": ("png", "jpg", "webp"),
    "heic": ("jpg", "png", "webp"),
    "svg": ("png", "ico", "pdf", "webp"),
    "ico": ("png", "webp"),
    "gif": ("webp", "png", "jpg"),
    "bmp": ("png", "jpg", "webp"),
    "tiff": ("jpg", "png", "pdf"),
    "mp4": ("mp3", "gif", "webm", "mov"),
    "mov": ("mp4", "mp3", "gif"), "mkv": ("mp4", "mp3"), "webm": ("mp4", "mp3", "gif"),
    "avi": ("mp4", "mp3"), "wmv": ("mp4", "mp3"), "flv": ("mp4", "mp3"), "ts": ("mp4", "mp3"),
    "wav": ("mp3", "flac", "m4a"), "flac": ("mp3", "m4a", "wav"), "mp3": ("wav", "m4a", "flac"),
    "m4a": ("mp3", "wav"), "aac": ("mp3", "m4a"), "ogg": ("mp3", "wav"), "wma": ("mp3", "m4a"),
    "aiff": ("mp3", "wav", "flac"),
    "csv": ("xlsx", "json"), "tsv": ("csv", "xlsx"), "json": ("csv", "xlsx", "yaml"), "yaml": ("json",),
}
_SAME = {"jpeg": "jpg", "docm": "docx", "xlsm": "xlsx", "pptm": "pptx"}

_TARGET_LABELS = {
    ("pdf", "png"): "PNG images", ("pdf", "jpg"): "JPG images", ("pdf", "docx"): "Word (DOCX)",
    ("pdf", "txt"): "Text", ("presentation", "png"): "PNG slides", ("document", "txt"): "Text",
    ("data", "xlsx"): "Excel (XLSX)",
    ("video", "mp3"): "MP3 (sound only)", ("video", "wav"): "WAV (sound only)",
}


def target_label(kind: str, target: str) -> str:
    return _TARGET_LABELS.get((kind, target), target.upper())


ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

IMAGE_CONVERT = Operation(
    id="image.convert", label="Convert", kind="image", role="convert",
    targets=IMAGE_TARGETS,
    options=(
        Option("quality", "Quality", "slider", 90, min=10, max=100, step=5, suffix="%",
               targets=("jpg", "webp", "avif")),
        Option("ico_sizes", "Icon sizes", "multi", list(ICO_SIZES), choices=ICO_SIZES,
               suffix="px", targets=("ico",)),
        Option("keep_metadata", "Keep photo metadata (EXIF, GPS)", "toggle", False,
               targets=("jpg", "webp", "avif", "png", "tiff")),
    ),
)

IMAGE_TOOLS = (
    Operation(
        id="image.remove_bg", label="Remove background", kind="image", role="tool",
        model="birefnet-lite",
        hint="AI cut-out, saved as a transparent PNG",
        options=(
            Option("quality", "Model", "choice", "Fast", choices=("Fast", "Best")),
            Option("crop", "Crop to subject", "toggle", False),
        ),
    ),
    Operation(
        id="image.resize", label="Resize", kind="image", role="tool",
        hint="Shrink or enlarge, keeping proportions",
        options=(
            Option("mode", "Resize by", "choice", "Longest side", choices=("Longest side", "Percent")),
            Option("size", "Longest side", "number", 1920, min=8, max=16384, suffix="px",
                   when=("mode", "Longest side")),
            Option("percent", "Percent", "slider", 50, min=5, max=400, step=5, suffix="%",
                   when=("mode", "Percent")),
        ),
    ),
    Operation(
        id="image.compress", label="Compress", kind="image", role="tool",
        hint="Smaller file, same format",
        options=(
            Option("quality", "Quality", "slider", 75, min=10, max=100, step=5, suffix="%"),
            Option("reduce_colors", "Reduce PNG colors (much smaller, slightly lossy)", "toggle", False),
        ),
    ),
    Operation(
        id="image.strip", label="Remove metadata", kind="image", role="tool",
        hint="Removes EXIF, GPS location, camera info",
    ),
    Operation(
        id="image.upscale", label="Upscale", kind="image", role="tool", model="esrgan-fast",
        hint="AI enlargement that adds real detail, saved as PNG",
        options=(
            Option("scale", "Enlarge", "choice", "4×", choices=("2×", "4×")),
            Option("quality", "Model", "choice", "Fast", choices=("Fast", "Best")),
        ),
    ),
    Operation(
        id="image.ocr", label="Extract text", kind="image", role="tool",
        hint="Reads the text in the image (OCR) into a .txt file",
    ),
    Operation(
        id="image.to_pdf", label="Combine into PDF", kind="image", role="tool", combine=True,
        hint="All images, in list order, as pages of one PDF",
    ),
)

_PASSWORD = Option("password", "Password", "password", "", secret=True)

DOCUMENT_OPS = (
    Operation(id="document.convert", label="Convert", kind="document", role="convert",
              targets=("pdf", "docx", "txt", "odt", "rtf")),
    Operation(id="spreadsheet.convert", label="Convert", kind="spreadsheet", role="convert",
              targets=("pdf", "xlsx", "csv", "ods")),
    Operation(id="presentation.convert", label="Convert", kind="presentation", role="convert",
              targets=("pdf", "pptx", "png", "odp")),
    Operation(
        id="pdf.convert", label="Convert", kind="pdf", role="convert", targets=("docx", "png", "jpg", "txt"),
        options=(
            Option("dpi", "Resolution", "choice", "150 dpi", choices=("72 dpi", "150 dpi", "300 dpi"),
                   targets=("png", "jpg")),
            Option("quality", "Quality", "slider", 90, min=10, max=100, step=5, suffix="%", targets=("jpg",)),
        ),
    ),
    Operation(id="pdf.ocr", label="Read scanned text", kind="pdf", role="tool",
              hint="OCR for scanned PDFs: recognises the text of each page into a .txt file"),
    Operation(id="pdf.merge", label="Merge", kind="pdf", role="tool", combine=True,
              hint="All PDFs, in list order, into one file"),
    Operation(id="pdf.split", label="Split pages", kind="pdf", role="tool",
              hint="One PDF per page, in a new folder"),
    Operation(id="pdf.compress", label="Compress", kind="pdf", role="tool",
              hint="Shrinks embedded images; text stays sharp",
              options=(Option("level", "Compression", "choice", "Balanced",
                              choices=("Light", "Balanced", "Strong")),)),
    Operation(id="pdf.rotate", label="Rotate", kind="pdf", role="tool", hint="Rotates every page",
              options=(Option("angle", "Rotate", "choice", "90° right",
                              choices=("90° right", "180°", "90° left")),)),
    Operation(id="pdf.protect", label="Add password", kind="pdf", role="tool",
              hint="AES-256 encryption; set the password in Options", options=(_PASSWORD,)),
    Operation(id="pdf.unlock", label="Remove password", kind="pdf", role="tool",
              hint="Needs the current password (in Options)", options=(_PASSWORD,)),
)

_SPREADSHEET_HINTS = {"csv": "CSV keeps only the first sheet"}

_VIDEO_OUT = ("mp4", "webm", "mkv", "mov")
_LOSSY_AUDIO = ("mp3", "m4a", "ogg", "opus")
_BITRATE = Option("bitrate", "Audio quality", "choice", "192 kbps", choices=("128 kbps", "192 kbps", "320 kbps"),
                  targets=_LOSSY_AUDIO)


def _trim(kind: str) -> Operation:
    return Operation(
        id=f"{kind}.trim", label="Trim", kind=kind, role="tool", hint="Keep only part of it (times like 1:30)",
        options=(
            Option("start", "Start", "text", "0:00"),
            Option("end", "End (empty = until the end)", "text", ""),
            *((Option("exact", "Cut exactly at these times (re-encodes, slower)", "toggle", False),)
              if kind == "video" else ()),
        ),
    )


MEDIA_OPS = (
    Operation(
        id="video.convert", label="Convert", kind="video", role="convert",
        targets=("mp4", "webm", "mkv", "mov", "gif", "mp3", "wav"),
        options=(
            Option("quality", "Quality", "choice", "Keep original",
                   choices=("Keep original", "High", "Balanced", "Small"), targets=_VIDEO_OUT),
            Option("resolution", "Resolution", "choice", "Original",
                   choices=("Original", "1080p", "720p", "480p"), targets=_VIDEO_OUT),
            Option("gif_width", "Width", "choice", "480 px", choices=("320 px", "480 px", "720 px"),
                   targets=("gif",)),
            Option("gif_fps", "Smoothness", "choice", "12 fps", choices=("10 fps", "12 fps", "15 fps", "24 fps"),
                   targets=("gif",)),
            _BITRATE,
            Option("keep_metadata", "Keep metadata (GPS location, camera, dates)", "toggle", False),
        ),
    ),
    _trim("video"),
    Operation(id="video.compress", label="Compress", kind="video", role="tool",
              hint="Smaller MP4 for sharing; also shrinks very large resolutions",
              options=(Option("level", "Compression", "choice", "Balanced",
                              choices=("Light", "Balanced", "Strong")),)),
    Operation(id="video.mute", label="Remove sound", kind="video", role="tool",
              hint="Same video without its audio track (instant, no quality loss)"),
    Operation(
        id="audio.convert", label="Convert", kind="audio", role="convert",
        targets=("mp3", "m4a", "wav", "flac", "ogg", "opus"),
        options=(_BITRATE, Option("keep_metadata", "Keep tags (artist, album)", "toggle", True)),
    ),
    _trim("audio"),
    Operation(id="audio.normalize", label="Normalize volume", kind="audio", role="tool",
              hint="Evens out loudness to a standard level"),
)

DATA_OPS = (
    Operation(id="data.convert", label="Convert", kind="data", role="convert",
              targets=("xlsx", "csv", "json", "yaml", "tsv")),
)

OPERATIONS = {op.id: op for op in (IMAGE_CONVERT, *IMAGE_TOOLS, *DOCUMENT_OPS, *MEDIA_OPS, *DATA_OPS)}


def operations_for(kind: str) -> list[Operation]:
    return [op for op in OPERATIONS.values() if op.kind == kind]


def convert_op(kind: str) -> Operation | None:
    return next((op for op in OPERATIONS.values() if op.kind == kind and op.role == "convert"), None)


def targets_for(kind: str, formats: list[str]) -> list[str]:
    """Order convert targets for a group of input formats; skip a no-op target."""
    op = convert_op(kind)
    if not formats or op is None:
        return []
    main = Counter(formats).most_common(1)[0][0]
    preferred = _PREFERRED.get(main, ())
    ordered = list(preferred) + [t for t in op.targets if t not in preferred]
    if len(set(formats)) == 1:
        same = _SAME.get(main, main)
        ordered = [t for t in ordered if t != same]
    return ordered


def target_hint(kind: str, target: str) -> str:
    return _SPREADSHEET_HINTS.get(target, "") if kind == "spreadsheet" else ""


def default_options(op: Operation) -> dict:
    return {o.key: o.default for o in op.options}


def required_model(op_id: str, options: dict) -> str | None:
    if op_id == "image.remove_bg":
        return "birefnet" if options.get("quality") == "Best" else "birefnet-lite"
    if op_id == "image.upscale":
        return "esrgan" if options.get("quality") == "Best" else "esrgan-fast"
    return OPERATIONS[op_id].model
