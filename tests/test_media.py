import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from conversor.formats import detect
from conversor.ops import media

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


class Ctx:
    gpu = False
    kind = "audio"

    def progress(self, _):
        pass


@pytest.fixture
def tone(tmp_path) -> Path:
    p = tmp_path / "tone.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(16000)))
    return p


def test_detects_media_containers(tmp_path):
    cases = {
        "a.mp4": (b"\x00\x00\x00\x18ftypisom", "video"), "a.m4a": (b"\x00\x00\x00\x18ftypM4A ", "audio"),
        "a.mkv": (b"\x1a\x45\xdf\xa3" + b"\x00" * 8 + b"matroska", "video"),
        "a.avi": (b"RIFF\x00\x00\x00\x00AVI LIST", "video"), "a.mp3": (b"ID3\x04\x00", "audio"),
        "b.mp3": (b"\xff\xfb\x90\x00", "audio"), "a.flac": (b"fLaC\x00", "audio"), "a.ogg": (b"OggS\x00", "audio"),
        "a.heic": (b"\x00\x00\x00\x18ftypheic", "image"),
    }
    for name, (data, kind) in cases.items():
        (tmp_path / name).write_bytes(data + b"\x00" * 64)
        assert detect(tmp_path / name).kind == kind, name


@pytest.mark.parametrize("text,seconds", [("90", 90), ("1:30", 90), ("0:01:30.5", 90.5), ("1,5", 1.5), ("", None)])
def test_parse_time(text, seconds):
    assert media._parse_time(text) == seconds


def test_parse_time_rejects_garbage():
    with pytest.raises(media.MediaError):
        media._parse_time("soon")


@needs_ffmpeg
def test_wav_to_mp3_and_trim(tmp_path, tone):
    mp3 = media.convert_audio(tone, "wav", "mp3", {"bitrate": "128 kbps"}, tmp_path, Ctx())
    assert detect(mp3).fmt == "mp3"
    cut = media.trim(tone, "wav", {"start": "0:00.5", "end": "1.5"}, tmp_path, Ctx())
    with wave.open(str(cut)) as w:
        assert abs(w.getnframes() / w.getframerate() - 1.0) < 0.05


@needs_ffmpeg
def test_trim_rejects_backwards_times(tmp_path, tone):
    with pytest.raises(media.MediaError, match="after the start"):
        media.trim(tone, "wav", {"start": "1", "end": "0.5"}, tmp_path, Ctx())


@needs_ffmpeg
def test_damaged_media_reports_cleanly(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"ID3" + b"\x00" * 200)
    with pytest.raises(media.MediaError):
        media.convert_audio(bad, "mp3", "wav", {}, tmp_path, Ctx())
