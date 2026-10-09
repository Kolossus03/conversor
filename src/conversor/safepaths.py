"""Path validation and never-overwrite output writing."""

import os
import re
from pathlib import Path

MAX_INPUT_BYTES = 2 * 1024**3

_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$", re.IGNORECASE)


class UnsafePath(ValueError):
    pass


def check_input(raw: str) -> Path:
    """Return a canonical path to a regular, readable local file, or raise UnsafePath."""
    if raw.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise UnsafePath("Device paths are not allowed")
    path = Path(raw)
    if not path.is_absolute():
        raise UnsafePath("Path must be absolute")
    _check_components(path)
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise UnsafePath("Not a regular file")
    if resolved.stat().st_size > MAX_INPUT_BYTES:
        raise UnsafePath("File is larger than 2 GB")
    return resolved


def check_output_dir(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise UnsafePath("Output folder must be absolute")
    _check_components(path)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise UnsafePath("Output folder does not exist")
    return resolved


def _check_components(path: Path) -> None:
    drive_less = str(path)[len(path.drive):]
    if ":" in drive_less:
        raise UnsafePath("Alternate data streams are not allowed")
    for part in path.parts[1:]:
        if _RESERVED.match(part.rstrip(" .")):
            raise UnsafePath(f"Reserved device name: {part}")


def _sanitize_stem(stem: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).rstrip(" .")
    if not stem or _RESERVED.match(stem):
        stem = f"_{stem}"
    return stem[:180]


def write_new_file(out_dir: Path, stem: str, ext: str, data_writer) -> Path:
    """Write via a temp file, then rename to the first free name. Never overwrites.

    `data_writer(tmp_path)` must create the file at tmp_path.
    """
    stem = _sanitize_stem(stem)
    # Keep the real extension: Office picks formats (and may append extensions) by it.
    tmp = out_dir / f".{stem}.{os.getpid()}.conversor-tmp.{ext}"
    try:
        data_writer(tmp)
        for n in range(1, 1000):
            name = f"{stem}.{ext}" if n == 1 else f"{stem} {n}.{ext}"
            target = out_dir / name
            try:
                os.rename(tmp, target)  # fails if target exists on Windows: atomic no-overwrite
                return target
            except FileExistsError:
                continue
        raise OSError("No free output file name")
    finally:
        tmp.unlink(missing_ok=True)


def new_output_dir(out_dir: Path, stem: str) -> Path:
    """Create a fresh folder for multi-file results, e.g. one image per PDF page."""
    stem = _sanitize_stem(stem)
    for n in range(1, 1000):
        target = out_dir / (stem if n == 1 else f"{stem} {n}")
        try:
            target.mkdir()
            return target
        except FileExistsError:
            continue
    raise OSError("No free output folder name")
