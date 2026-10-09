from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from conversor import models, registry
from conversor.formats import detect
from conversor.ops import images
from conversor.safepaths import UnsafePath, check_input, write_new_file


class Ctx:
    gpu = False

    def progress(self, _):
        pass

    def compare(self, *_):
        pass


@pytest.fixture
def png(tmp_path) -> Path:
    im = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((20, 20, 280, 180), fill=(200, 30, 80, 255))
    p = tmp_path / "logo.png"
    im.save(p)
    return p


def test_detect_uses_content_not_extension(tmp_path, png):
    fake = tmp_path / "photo.jpg"
    fake.write_bytes(png.read_bytes())
    assert detect(fake).fmt == "png"
    html = tmp_path / "page.jpg"
    html.write_text("<html><body>not an image</body></html>")
    assert detect(html).kind == "unknown"


def test_never_overwrites(tmp_path):
    def writer(tmp):
        tmp.write_bytes(b"x")

    first = write_new_file(tmp_path, "out", "txt", writer)
    second = write_new_file(tmp_path, "out", "txt", writer)
    assert first.name == "out.txt" and second.name == "out 2.txt"
    assert not list(tmp_path.glob("*.conversor-tmp*"))


@pytest.mark.parametrize("raw", [r"\\.\PhysicalDrive0", r"C:\Windows\win.ini:secret", "relative.png", r"C:\tmp\CON"])
def test_rejects_unsafe_inputs(raw):
    with pytest.raises((UnsafePath, OSError)):
        check_input(raw)


def test_ico_has_all_sizes_and_is_square(tmp_path, png):
    out = images.convert(png, "png", "ico", {"ico_sizes": [16, 32, 256]}, tmp_path, Ctx())
    ico = Image.open(out)
    assert ico.info["sizes"] == {(16, 16), (32, 32), (256, 256)}


@pytest.mark.parametrize("target", ["jpg", "webp", "avif", "pdf", "bmp", "tiff", "gif"])
def test_convert_targets(tmp_path, png, target):
    out = images.convert(png, "png", target, {}, tmp_path, Ctx())
    assert out.suffix == f".{target}" and out.stat().st_size > 0


def test_strip_removes_exif(tmp_path):
    src = tmp_path / "gps.jpg"
    im = Image.new("RGB", (64, 64), "red")
    exif = im.getexif()
    exif[0x010F] = "SecretCam"
    im.save(src, exif=exif.tobytes())
    out = images.strip_metadata(src, "jpeg", {}, tmp_path, Ctx())
    assert len(Image.open(out).getexif()) == 0


def test_svg_cannot_read_local_files(tmp_path):
    svg = tmp_path / "x.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><!DOCTYPE x [<!ENTITY a "a">]></svg>')
    with pytest.raises(images.ImageError):
        images.load(svg, "svg")


def test_decompression_bomb_refused(tmp_path):
    Image.MAX_IMAGE_PIXELS, saved = 1000, Image.MAX_IMAGE_PIXELS
    try:
        big = tmp_path / "big.png"
        Image.new("L", (100, 100)).save(big)
        with pytest.raises((Image.DecompressionBombError, Image.DecompressionBombWarning)):
            images.load(big, "png")
    finally:
        Image.MAX_IMAGE_PIXELS = saved


def test_tampered_model_is_refused(tmp_path, monkeypatch):
    spec = models.ModelSpec("t", "test", "https://example.invalid", "0" * 64, 4)
    monkeypatch.setitem(models.MODELS, "t", spec)
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    (tmp_path / "t.onnx").write_bytes(b"evil")
    with pytest.raises(models.ModelError):
        models.verified_path("t")


def test_registry_targets_skip_noop():
    assert "png" not in registry.targets_for("image", ["png", "png"])
    assert registry.targets_for("image", ["png"])[0] == "ico"
    assert registry.targets_for("document", ["docx"])[0] == "pdf"
