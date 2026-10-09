"""Audio and video through ffmpeg (run as a child of the sandboxed worker, same job limits).

Hardening: the demuxer is forced from the detected format (no auto-probing into playlist or
concat formats that could pull in other files), only the "file" protocol is allowed (no network),
only the first video stream and audio streams are kept, metadata such as GPS location is dropped,
and ffmpeg never overwrites anything.
"""

import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from PIL import Image

from ..safepaths import write_new_file

CREATE_NO_WINDOW = 0x08000000

DEMUXERS = {
    "mp4": "mov", "mov": "mov", "m4a": "mov", "heic": "mov", "mkv": "matroska", "webm": "matroska",
    "avi": "avi", "wav": "wav", "mp3": "mp3", "flac": "flac", "ogg": "ogg", "aac": "aac",
    "wmv": "asf", "wma": "asf", "flv": "flv", "ts": "mpegts", "aiff": "aiff",
}

QUALITY_CRF = {"High": 18, "Balanced": 23, "Small": 28}
COMPRESS = {"Light": (23, 1080), "Balanced": (27, 1080), "Strong": (31, 720)}  # crf, max height
HEIGHTS = {"1080p": 1080, "720p": 720, "480p": 480}

# Which codecs each container can take as-is (then we copy instead of re-encoding: instant, lossless).
_COPYABLE = {
    "mp4": ({"h264", "hevc", "av1", "mpeg4"}, {"aac", "mp3", "alac", "opus", "ac3"}),
    "mov": ({"h264", "hevc", "mpeg4", "prores"}, {"aac", "mp3", "alac", "pcm_s16le"}),
    "mkv": (None, None),  # anything
    "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}),
}

AUDIO_CODECS = {
    "mp3": ["-c:a", "libmp3lame"], "m4a": ["-c:a", "aac"], "ogg": ["-c:a", "libvorbis"],
    "opus": ["-c:a", "libopus"], "wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac"],
}
LOSSLESS_AUDIO = {"wav", "flac"}


class MediaError(RuntimeError):
    pass


def find_tool(name: str) -> str:
    """Absolute path to ffmpeg/ffprobe; resolves Scoop shims (a shim would add an extra process)."""
    found = shutil.which(name)
    if not found:
        raise MediaError("ffmpeg is needed for audio and video but wasn't found on this PC")
    path = Path(found)
    shim = path.with_suffix(".shim")
    if shim.exists():
        m = re.search(r'path\s*=\s*"?([^"\r\n]+)', shim.read_text(encoding="utf-8", errors="replace"))
        if m and Path(m.group(1)).exists():
            return m.group(1)
    return str(path)


def _input(src: Path, fmt: str) -> list[str]:
    return ["-protocol_whitelist", "file", "-f", DEMUXERS[fmt], "-i", str(src)]


def probe(src: Path, fmt: str) -> dict:
    cmd = [find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
           *_input(src, fmt)]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise MediaError("Reading this file took too long; it may be damaged") from None
    if res.returncode != 0:
        raise MediaError("This file is damaged or not a supported audio/video format")
    info = json.loads(res.stdout or b"{}")
    info["duration"] = float(info.get("format", {}).get("duration") or 0)
    info["video"] = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
                          and not s.get("disposition", {}).get("attached_pic")), None)
    info["audio"] = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    return info


_DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
_FRIENDLY = (
    ("matches no streams", "This file doesn't have the audio or video track this needs"),
    ("Invalid data found", "This file is damaged or not a supported audio/video format"),
    ("Output file is empty", "Nothing to save: the chosen times are outside the file"),
)


def run_ffmpeg(args: list[str], duration: float, ctx) -> None:
    """Run ffmpeg, reporting progress. Without a known duration, read it from ffmpeg's own log
    (saves a separate ffprobe launch, which costs seconds for a large unsigned binary)."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-n", "-loglevel", "info",
           "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=CREATE_NO_WINDOW)
    log: list[str] = []
    total = [duration]

    def read_log():
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            log.append(line)
            m = _DURATION.search(line)
            if m and not total[0]:
                h, mnt, sec = m.groups()
                total[0] = int(h) * 3600 + int(mnt) * 60 + float(sec)

    reader = threading.Thread(target=read_log, daemon=True)
    reader.start()
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("out_time_us=") and total[0] > 0:
            try:
                ctx.progress(min(0.99, int(line.split("=", 1)[1]) / 1e6 / total[0]))
            except ValueError:
                pass
    proc.wait()
    reader.join(timeout=5)
    if proc.returncode != 0:
        text = "\n".join(log)
        for needle, message in _FRIENDLY:
            if needle in text:
                raise MediaError(message)
        errors = [ln for ln in log if "rror" in ln] or log
        raise MediaError("ffmpeg failed: " + (errors[-1].strip()[:200] if errors else f"exit code {proc.returncode}"))


_nvenc_ok: bool | None = None


def _nvenc_available() -> bool:
    """NVIDIA hardware encoding needs a recent driver; test once with a tiny encode."""
    global _nvenc_ok
    if _nvenc_ok is None:
        cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi",
               "-i", "color=black:s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"]
        try:
            _nvenc_ok = subprocess.run(cmd, capture_output=True, timeout=30,
                                       creationflags=CREATE_NO_WINDOW).returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            _nvenc_ok = False
    return _nvenc_ok


def _h264(crf: int, gpu: bool) -> list[str]:
    if gpu and _nvenc_available():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 1), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]


def _scale(max_height: int | None) -> list[str]:
    if not max_height:
        return []
    # Only ever shrink; keep even dimensions for the encoders.
    return ["-vf", f"scale=-2:'min({max_height},ih)':flags=lanczos"]


def _metadata(options: dict) -> list[str]:
    return [] if options.get("keep_metadata") else ["-map_metadata", "-1", "-map_chapters", "-1"]


def _write(out_dir: Path, stem: str, ext: str, args: list[str], duration: float, ctx) -> Path:
    return write_new_file(out_dir, stem, ext, lambda tmp: run_ffmpeg([*args, str(tmp)], duration, ctx))


def _bitrate(options: dict) -> list[str]:
    return ["-b:a", str(options.get("bitrate", "192 kbps")).split()[0] + "k"]


def convert_video(src: Path, fmt: str, target: str, options: dict, out_dir: Path, ctx) -> Path:
    base = [*_input(src, fmt), *_metadata(options), "-sn", "-dn"]

    if target in AUDIO_CODECS:  # extract the sound track
        codec = AUDIO_CODECS[target] + ([] if target in LOSSLESS_AUDIO else _bitrate(options))
        return _write(out_dir, src.stem, target, [*base, "-map", "0:a:0", "-vn", *codec], 0, ctx)
    if target == "gif":
        width = int(str(options.get("gif_width", "480 px")).split()[0])
        fps = int(str(options.get("gif_fps", "12 fps")).split()[0])
        graph = (f"[0:v:0]fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
                 f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4[out]")
        return _write(out_dir, src.stem, "gif", [*base, "-filter_complex", graph, "-map", "[out]", "-loop", "0"],
                      0, ctx)

    quality = options.get("quality", "Keep original")
    height = HEIGHTS.get(options.get("resolution", "Original"))
    vcodec, acodecs = _COPYABLE[target]
    can_copy = quality == "Keep original" and not height
    duration = 0.0
    if can_copy and vcodec is not None:  # is a lossless stream copy possible for this container?
        info = probe(src, fmt)
        if info["video"] is None:
            raise MediaError("This file has no video stream")
        duration = info["duration"]
        can_copy = (info["video"]["codec_name"] in vcodec
                    and all(a["codec_name"] in acodecs for a in info["audio"]))
    maps = ["-map", "0:v:0", "-map", "0:a?"]
    if can_copy:
        codec = ["-c", "copy"]
    else:
        crf = QUALITY_CRF.get(quality, QUALITY_CRF["High"])
        if target == "webm":
            codec = ["-c:v", "libvpx-vp9", "-crf", str(crf + 12), "-b:v", "0", "-row-mt", "1",
                     "-deadline", "good", "-cpu-used", "4", "-c:a", "libopus", "-b:a", "128k"]
        else:
            codec = [*_h264(crf, ctx.gpu), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
        codec = [*_scale(height), *codec]
    if target in ("mp4", "mov"):
        codec += ["-movflags", "+faststart"]
    return _write(out_dir, src.stem, target, [*base, *maps, *codec], duration, ctx)


def _parse_time(text: str) -> float | None:
    text = str(text or "").strip()
    if not text:
        return None
    try:
        seconds = 0.0
        for part in text.replace(",", ".").split(":"):
            seconds = seconds * 60 + float(part)
        return seconds
    except ValueError:
        raise MediaError(f"Can't read the time '{text}'. Use a format like 1:30 or 0:01:30.5") from None


def trim(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    start = _parse_time(options.get("start")) or 0.0
    end = _parse_time(options.get("end"))
    if end is not None and end <= start:
        raise MediaError("The end time must be after the start time")
    ext = fmt  # stream copy keeps the original container
    timing = ["-ss", f"{start:.3f}", *(["-t", f"{end - start:.3f}"] if end is not None else [])]
    if options.get("exact") and ctx.kind == "video":
        codec = [*_h264(18, ctx.gpu), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
        ext = "mp4"
        args = [*_input(src, fmt), *timing]
    else:
        codec = ["-c", "copy"]
        args = [*timing[:2], *_input(src, fmt), *timing[2:]]  # seek before input: fast, keyframe-aligned
    maps = ["-map", "0:v:0?", "-map", "0:a?"]
    return _write(out_dir, f"{src.stem} (trimmed)", ext, [*args, *_metadata(options), "-sn", "-dn", *maps, *codec],
                  (end - start) if end is not None else 0, ctx)


def compress_video(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    crf, height = COMPRESS.get(options.get("level"), COMPRESS["Balanced"])
    args = [*_input(src, fmt), *_metadata(options), "-sn", "-dn", "-map", "0:v:0", "-map", "0:a?",
            *_scale(height), *_h264(crf, ctx.gpu), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart"]
    return _write(out_dir, f"{src.stem} (compressed)", "mp4", args, 0, ctx)


def remove_audio(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    ext = fmt if fmt in ("mp4", "mov", "mkv", "webm") else "mkv"
    args = [*_input(src, fmt), *_metadata(options), "-map", "0:v:0", "-an", "-sn", "-dn", "-c", "copy"]
    return _write(out_dir, f"{src.stem} (no sound)", ext, args, 0, ctx)


def convert_audio(src: Path, fmt: str, target: str, options: dict, out_dir: Path, ctx) -> Path:
    if target not in AUDIO_CODECS:
        raise MediaError(f"Unknown target: {target}")
    codec = AUDIO_CODECS[target] + ([] if target in LOSSLESS_AUDIO else _bitrate(options))
    args = [*_input(src, fmt), *_metadata(options), "-map", "0:a:0", "-vn", *codec]
    return _write(out_dir, src.stem, target, args, 0, ctx)


def normalize(src: Path, fmt: str, options: dict, out_dir: Path, ctx) -> Path:
    target = fmt if fmt in AUDIO_CODECS else "m4a"
    codec = AUDIO_CODECS[target] + ([] if target in LOSSLESS_AUDIO else ["-b:a", "192k"])
    args = [*_input(src, fmt), *_metadata(options), "-map", "0:a:0", "-vn",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *codec]
    return _write(out_dir, f"{src.stem} (normalized)", target, args, 0, ctx)


def still_image(src: Path, fmt: str) -> Image.Image:
    """Decode one frame (HEIC photos, video thumbnails) via ffmpeg into a Pillow image."""
    # Videos: a frame 1 s in looks more representative than a black first frame.
    attempts = [[]] if fmt == "heic" else [["-ss", "1"], []]
    with tempfile.TemporaryDirectory() as tmp:
        for i, seek in enumerate(attempts):
            out = Path(tmp) / f"frame{i}.png"
            cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-n", "-loglevel", "error", *seek,
                   *_input(src, fmt), "-map", "0:v:0", "-frames:v", "1", str(out)]
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
            except subprocess.TimeoutExpired:
                break
            if res.returncode == 0 and out.exists():
                im = Image.open(out)
                im.load()
                return im
    raise MediaError("Couldn't decode an image from this file")
