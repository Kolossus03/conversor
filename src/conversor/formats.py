"""Detect file types from their content (magic bytes), never from the extension alone."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileType:
    kind: str  # broad group: "image", "unknown", ...
    fmt: str  # concrete format: "png", "jpeg", ...


UNKNOWN = FileType("unknown", "unknown")

# Office files are ZIP or OLE2 containers. The container is checked from content; which
# Office format it is comes from the extension (the worker then lets Office validate it),
# so the UI process never has to parse the archive itself.
_ZIP_OFFICE = {
    "docx": "document", "docm": "document", "odt": "document",
    "xlsx": "spreadsheet", "xlsm": "spreadsheet", "ods": "spreadsheet",
    "pptx": "presentation", "pptm": "presentation", "odp": "presentation",
}
_OLE_OFFICE = {"doc": "document", "xls": "spreadsheet", "ppt": "presentation"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
_AVIF_BRANDS = {b"avif", b"avis"}
_DATA = {"csv": "csv", "tsv": "tsv", "json": "json", "yaml": "yaml", "yml": "yaml"}
_ASF_GUID = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")


def detect(path: Path) -> FileType:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return UNKNOWN

    ext = path.suffix.lower().lstrip(".")
    if b"%PDF-" in head[:1024]:
        return FileType("pdf", "pdf")
    if head.startswith(b"PK\x03\x04") and ext in _ZIP_OFFICE:
        return FileType(_ZIP_OFFICE[ext], ext)
    if head.startswith(OLE_MAGIC) and ext in _OLE_OFFICE:
        return FileType(_OLE_OFFICE[ext], ext)
    if head.startswith(OLE_MAGIC) and ext in _ZIP_OFFICE:  # password-protected docx/xlsx/pptx
        return FileType(_ZIP_OFFICE[ext], ext)
    if head.startswith(b"{\\rtf"):
        return FileType("document", "rtf")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileType("image", "png")
    if head.startswith(b"\xff\xd8\xff"):
        return FileType("image", "jpeg")
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return FileType("image", "gif")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return FileType("image", "webp")
    if head[:2] == b"BM":
        return FileType("image", "bmp")
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return FileType("image", "tiff")
    if head[:4] == b"\x00\x00\x01\x00":
        return FileType("image", "ico")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _AVIF_BRANDS:
            return FileType("image", "avif")
        if brand in _HEIF_BRANDS:
            return FileType("image", "heic")
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return FileType("audio", "m4a")
        return FileType("video", "mov" if brand == b"qt  " else "mp4")
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return FileType("video", "webm" if b"webm" in head[:64] else "mkv")
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return FileType("video", "avi")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return FileType("audio", "wav")
    if head.startswith(b"FLV\x01"):
        return FileType("video", "flv")
    if head.startswith(_ASF_GUID):
        return FileType("audio", "wma") if ext == "wma" else FileType("video", "wmv")
    if len(head) > 376 and head[0] == 0x47 and head[188] == 0x47 and head[376] == 0x47:
        return FileType("video", "ts")
    if head.startswith(b"fLaC"):
        return FileType("audio", "flac")
    if head.startswith(b"OggS"):
        return FileType("audio", "ogg")
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return FileType("audio", "aiff")
    if head.startswith(b"ID3"):
        return FileType("audio", "mp3")
    if len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:  # MPEG audio frame sync
        return FileType("audio", "aac" if head[1] & 0x06 == 0 else "mp3")
    if _looks_like_svg(head):
        return FileType("image", "svg")
    if ext == "txt" and _looks_like_text(head):
        return FileType("document", "txt")
    if ext in _DATA and _looks_like_text(head):
        return FileType("data", _DATA[ext])
    return UNKNOWN


def _looks_like_svg(head: bytes) -> bool:
    text = head.lstrip(b"\xef\xbb\xbf").lstrip().lower()
    if not text.startswith(b"<"):
        return False
    return b"<svg" in text


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        return e.start > len(head) - 4  # a multi-byte character cut off at the end


KIND_NOUNS = {  # (singular, plural)
    "image": ("image", "images"), "pdf": ("PDF", "PDFs"), "document": ("document", "documents"),
    "spreadsheet": ("spreadsheet", "spreadsheets"), "presentation": ("presentation", "presentations"),
    "video": ("video", "videos"), "data": ("data file", "data files"), "audio": ("audio file", "audio files"),
    "unknown": ("unsupported file", "unsupported files"),
}
