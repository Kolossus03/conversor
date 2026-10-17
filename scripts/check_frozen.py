"""Smoke-test a frozen Conversor.exe: uv run python scripts/check_frozen.py [Conversor.exe] [--office]

Pipes real jobs into `Conversor.exe --worker` inside the same Job Object limits the app uses,
with PATH cut down to System32 (so the bundled ffmpeg must be used) and APPDATA pointed at a
temporary folder (so your settings are never read or changed). AI models come from the real
%LOCALAPPDATA%\\Conversor\\models. Defaults to the PyInstaller build in dist/app; pass the
installed exe to check an install. --office also converts an Excel file through Office.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

from conversor.sandbox import AI_WORKER_MEMORY_LIMIT, WORKER_MEMORY_LIMIT, Job

ROOT = Path(__file__).resolve().parent.parent


def make_inputs(exe: Path, inp: Path) -> None:
    shape = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(shape).ellipse((32, 32, 224, 224), fill=(220, 60, 60, 255))
    shape.save(inp / "shape.png")

    shutil.copy(ROOT / "tests" / "fixtures" / "ocr_mixed_tops.png", inp / "text.png")  # words with different tops

    pages = [Image.new("RGB", (600, 800), c) for c in ("white", "lightblue")]
    pages[0].save(inp / "doc.pdf", save_all=True, append_images=pages[1:])

    photo = Image.new("RGB", (640, 480), (90, 140, 200))
    ImageDraw.Draw(photo).rectangle((220, 120, 420, 400), fill=(240, 200, 60))
    photo.save(inp / "photo.jpg", quality=90)

    ffmpeg = exe.parent / "ffmpeg" / "ffmpeg.exe"
    subprocess.run([str(ffmpeg), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac",
                    str(inp / "clip.mkv")], check=True)

    if "--office" in sys.argv:
        import openpyxl

        wb = openpyxl.Workbook()
        wb.active["A1"] = "hello"
        wb.save(inp / "sheet.xlsx")


def task(inp: Path, out: Path, i, op, src, fmt, kind, target=None, options=None):
    return {"id": i, "op": op, "input": str(inp / src), "fmt": fmt, "kind": kind, "target": target,
            "options": options or {}, "out_dir": str(out)}


def runs(inp: Path, out: Path) -> list:
    t = lambda *a, **k: task(inp, out, *a, **k)
    result = [
        ("plain", WORKER_MEMORY_LIMIT, 1, [
            t("png2jpg", "image.convert", "shape.png", "png", "image", "jpg"),
            t("png2ico", "image.convert", "shape.png", "png", "image", "ico"),
            t("pdf2png", "pdf.convert", "doc.pdf", "pdf", "pdf", "png"),
            t("ocr", "image.ocr", "text.png", "png", "image"),
        ]),
        ("media", WORKER_MEMORY_LIMIT, 2, [
            t("mp4", "video.convert", "clip.mkv", "mkv", "video", "mp4"),
            t("gif", "video.convert", "clip.mkv", "mkv", "video", "gif"),
            t("mp3", "video.convert", "clip.mkv", "mkv", "video", "mp3"),
            t("compress", "video.compress", "clip.mkv", "mkv", "video"),
        ]),
        ("ai", AI_WORKER_MEMORY_LIMIT, 1, [
            t("bg", "image.remove_bg", "photo.jpg", "jpeg", "image", None, {"quality": "Fast"}),
        ]),
    ]
    if "--office" in sys.argv:
        result.append(("office", WORKER_MEMORY_LIMIT, 1, [
            t("xlsx2pdf", "spreadsheet.convert", "sheet.xlsx", "xlsx", "spreadsheet", "pdf")]))
    return result


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    exe = Path(args[0]) if args else ROOT / "dist" / "app" / "Conversor" / "Conversor.exe"
    if not exe.is_file():
        sys.exit(f"not found: {exe}")
    tmp = Path(tempfile.mkdtemp(prefix="conversor-check-"))
    inp, out, appdata = tmp / "in", tmp / "out", tmp / "appdata"
    for d in (inp, out, appdata):
        d.mkdir()
    make_inputs(exe, inp)
    env = {**os.environ, "PATH": r"C:\Windows\System32;C:\Windows", "APPDATA": str(appdata)}

    ok = True
    outputs = {}
    for name, limit, procs, tasks in runs(inp, out):
        job = Job(limit, procs)
        start = time.time()
        proc = subprocess.Popen([str(exe), "--worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=str(tmp), env=env)
        job.assign(proc.pid)
        stdout, stderr = proc.communicate(json.dumps({"settings": {"gpu": True}, "tasks": tasks}).encode() + b"\n",
                                          timeout=900)
        job.close()
        events = [json.loads(line) for line in stdout.decode().splitlines() if line.strip()]
        print(f"== {name} (exit {proc.returncode}, {time.time() - start:.1f} s)")
        for e in events:
            if e.get("event") == "done":
                path = Path(e["output"])
                outputs[e["id"]] = path
                ok &= path.exists()
                print(f"  {'PASS' if path.exists() else 'FAIL'} {e['id']}: {path.name} ({e['size']:,} bytes)")
            elif e.get("event") == "error":
                ok = False
                print(f"  FAIL {e['id']}: {e['message']}")
        missing = {t["id"] for t in tasks} - {e.get("id") for e in events if e.get("event") in ("done", "error")}
        for i in sorted(missing):
            ok = False
            print(f"  FAIL {i}: no result")
        for line in stderr.decode("utf-8", "replace").splitlines():
            if "ExecutionProvider" in line:
                print("  provider:", line.strip())

    if "ocr" in outputs:
        text = outputs["ocr"].read_text(encoding="utf-8")
        good = text.strip() == "Hello Conversor 2026"
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} ocr text: {text!r}")
    if "compress" in outputs:
        probe = subprocess.run([str(exe.parent / "ffmpeg" / "ffprobe.exe"), "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream_tags=encoder", "-of", "default=nw=1:nk=1",
                                str(outputs["compress"])], capture_output=True, text=True)
        print("  video encoder:", probe.stdout.strip() or "unknown")
    print(f"\n{'ALL OK' if ok else 'SOME FAILED'}  (files in {tmp})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
