"""Build both Windows installers: uv run python scripts/build_installer.py

Freezes the app with PyInstaller (packaging/conversor.spec), adds a pinned ffmpeg, then runs
Inno Setup (packaging/conversor.iss) twice: a CPU-only installer and one with the NVIDIA libraries.
Downloads are cached in build/cache; the app goes to dist/app/Conversor, installers to dist/.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP = DIST / "app" / "Conversor"

FFMPEG_URL = ("https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/"
              "ffmpeg-9.0.2-full_build-shared.zip")
FFMPEG_SHA256 = "8d31e162f1616e37aab3fa2db991b97e1b8dbeb1c8465fd81a81be16ff91b328"
ISCC = Path(os.environ.get("ISCC") or Path.home() / "scoop/apps/inno-setup/current/ISCC.exe")
VARIANTS = {"cpu": "setup", "nvidia": "setup-nvidia"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def ffmpeg_zip() -> Path:
    path = BUILD / "cache" / FFMPEG_URL.rsplit("/", 1)[1]
    if path.is_file() and sha256(path) == FFMPEG_SHA256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    print("downloading", FFMPEG_URL)
    with urllib.request.urlopen(FFMPEG_URL, timeout=120) as resp, open(part, "wb") as out:
        shutil.copyfileobj(resp, out, 4 * 1024 * 1024)
    if sha256(part) != FFMPEG_SHA256:
        part.unlink()
        sys.exit("ffmpeg download failed its SHA-256 check")
    os.replace(part, path)
    return path


def add_ffmpeg(archive: Path, dest: Path) -> None:
    """Only ffmpeg, ffprobe, their DLLs and the license: no ffplay, headers or import libraries."""
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            parts = name.split("/")
            leaf = parts[-1]
            wanted = (parts[1:] == ["LICENSE"]
                      or parts[1:2] == ["bin"] and (leaf in ("ffmpeg.exe", "ffprobe.exe") or leaf.endswith(".dll")))
            if wanted:
                (dest / ("LICENSE.txt" if leaf == "LICENSE" else leaf)).write_bytes(z.read(name))


def freeze() -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "conversor.spec"),
                    "--noconfirm", "--log-level", "WARN",
                    "--distpath", str(APP.parent), "--workpath", str(BUILD / "pyinstaller")], check=True)


def installer(version: str, variant: str) -> Path:
    subprocess.run([str(ISCC), "/Q", f"/DAppVersion={version}", f"/DSourceDir={APP}", f"/DVariant={variant}",
                    f"/O{DIST}", str(ROOT / "packaging" / "conversor.iss")], check=True)
    return DIST / f"Conversor-{version}-{VARIANTS[variant]}.exe"


def size(path: Path) -> str:
    total = path.stat().st_size if path.is_file() else sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{total / 1024**2:,.0f} MB"


def main() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    archive = ffmpeg_zip()
    freeze()
    add_ffmpeg(archive, APP / "ffmpeg")
    outputs = [installer(version, v) for v in VARIANTS]
    print(f"\nConversor {version}")
    print(f"  app folder  {APP}  ({size(APP)}, of which NVIDIA {size(APP / '_internal' / 'nvidia')})")
    for out in outputs:
        print(f"  installer   {out}  ({size(out)})")


if __name__ == "__main__":
    main()
