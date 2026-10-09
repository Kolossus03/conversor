import shutil
import subprocess

import pikepdf
import pytest
from PIL import Image, ImageDraw

from conversor.ops import images, media, pdf


class Ctx:
    gpu = False
    kind = "video"

    def progress(self, _):
        pass

    def compare(self, *_):
        pass


def test_png_to_gif_keeps_transparency(tmp_path):
    src = tmp_path / "logo.png"
    im = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((10, 10, 110, 70), fill=(200, 30, 80, 255))
    im.save(src)
    gif = Image.open(images.convert(src, "png", "gif", {}, tmp_path, Ctx())).convert("RGBA")
    assert gif.getpixel((0, 0))[3] == 0  # corner stays see-through
    assert gif.getpixel((60, 40))[3] == 255  # shape stays solid


def test_animated_png_stays_animated(tmp_path):
    src = tmp_path / "anim.png"
    frames = [Image.new("RGBA", (40, 40), c) for c in ("red", "green", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=100)
    out = images.convert(src, "png", "gif", {}, tmp_path, Ctx())
    assert Image.open(out).n_frames == 3


def test_image_compress_to_target_size(tmp_path):
    src = tmp_path / "photo.png"
    noise = Image.effect_noise((1600, 1200), 80).convert("RGB")
    noise.save(src)
    out = images.compress(src, "png", {"mode": "Target size", "target_kb": 150}, tmp_path, Ctx())
    assert out.suffix == ".jpg" and out.stat().st_size <= 150_000


@pytest.mark.parametrize("text,expected", [("1-3, 7", [0, 1, 2, 6]), ("8-", [7, 8, 9]), ("2,2,1", [0, 1])])
def test_parse_pages(text, expected):
    assert pdf.parse_pages(text, 10) == expected


@pytest.mark.parametrize("text", ["", "0", "11", "5-2", "abc"])
def test_parse_pages_rejects(text):
    with pytest.raises(pdf.PdfError):
        pdf.parse_pages(text, 10)


def test_pick_and_remove_pages(tmp_path):
    src = tmp_path / "doc.pdf"
    doc = pikepdf.new()
    for _ in range(5):
        doc.add_blank_page()
    doc.save(src)
    kept = pdf.pick_pages(src, {"pages": "2-3"}, tmp_path, Ctx())
    removed = pdf.pick_pages(src, {"pages": "2-3", "action": "Remove them"}, tmp_path, Ctx())
    with pikepdf.open(kept) as a, pikepdf.open(removed) as b:
        assert len(a.pages) == 2 and len(b.pages) == 3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_video_compress_to_target_size(tmp_path):
    src = tmp_path / "clip.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=1280x720:rate=30:duration=8", "-f", "lavfi", "-i", "anoisesrc=d=8",
                    "-c:v", "libx264", "-crf", "12", "-c:a", "aac", "-shortest", str(src)], check=True)
    out = media.compress_video(src, "mp4", {"mode": "Target size", "target_mb": 1}, tmp_path, Ctx())
    assert out.stat().st_size <= 1_000_000
