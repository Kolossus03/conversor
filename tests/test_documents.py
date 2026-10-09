from pathlib import Path

import pikepdf
import pytest
from PIL import Image, ImageDraw

from conversor.formats import OLE_MAGIC, detect
from conversor.ops import pdf


class Ctx:
    gpu = False

    def progress(self, _):
        pass


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    pages = []
    for i in range(3):
        im = Image.new("RGB", (400, 300), "white")
        ImageDraw.Draw(im).rectangle((20, 20, 380, 280), outline="black", width=5)
        pages.append(im)
    p = tmp_path / "doc.pdf"
    pages[0].save(p, "PDF", save_all=True, append_images=pages[1:])
    return p


def test_detects_documents_by_container(tmp_path):
    cases = {
        "a.pdf": (b"%PDF-1.7\n", "pdf"), "a.docx": (b"PK\x03\x04rest", "document"),
        "a.xlsx": (b"PK\x03\x04rest", "spreadsheet"), "a.ppt": (OLE_MAGIC + b"rest", "presentation"),
        "locked.docx": (OLE_MAGIC + b"rest", "document"), "a.rtf": (b"{\\rtf1 hello", "document"),
        "notes.txt": (b"plain words", "document"), "fake.docx": (b"MZ\x90\x00", "unknown"),
        "bin.txt": (b"a\x00b", "unknown"),
    }
    for name, (data, kind) in cases.items():
        (tmp_path / name).write_bytes(data)
        assert detect(tmp_path / name).kind == kind, name


def test_split_rotate_merge(tmp_path, sample_pdf):
    folder = pdf.split(sample_pdf, {}, tmp_path, Ctx())
    parts = sorted(folder.iterdir())
    assert len(parts) == 3
    merged = pdf.merge(parts, {}, tmp_path, Ctx())
    assert len(pikepdf.open(merged).pages) == 3
    rotated = pdf.rotate(sample_pdf, {"angle": "90° left"}, tmp_path, Ctx())
    with pikepdf.open(rotated) as result:
        assert result.pages[0].Rotate == 270


def test_protect_then_unlock(tmp_path, sample_pdf):
    locked = pdf.protect(sample_pdf, {"password": "hunter22"}, tmp_path, Ctx())
    with pytest.raises(pdf.PdfError, match="password-protected"):
        pdf.rotate(locked, {}, tmp_path, Ctx())
    with pytest.raises(pdf.PdfError, match="Wrong password"):
        pdf.unlock(locked, {"password": "nope"}, tmp_path, Ctx())
    unlocked = pdf.unlock(locked, {"password": "hunter22"}, tmp_path, Ctx())
    assert not pikepdf.open(unlocked).is_encrypted


def test_short_password_refused(tmp_path, sample_pdf):
    with pytest.raises(pdf.PdfError):
        pdf.protect(sample_pdf, {"password": "abc"}, tmp_path, Ctx())


def test_pages_to_images(tmp_path, sample_pdf):
    folder = pdf.to_images(sample_pdf, "jpg", {"dpi": "72 dpi"}, tmp_path, Ctx())
    images = sorted(folder.glob("*.jpg"))
    assert len(images) == 3 and Image.open(images[0]).size == (400, 300)


def test_scanned_pdf_has_no_text(tmp_path, sample_pdf):
    with pytest.raises(pdf.PdfError, match="no text layer"):
        pdf.to_text(sample_pdf, tmp_path, Ctx())


def test_damaged_pdf_reports_cleanly(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\n garbage garbage")
    with pytest.raises(pdf.PdfError):
        pdf.rotate(bad, {}, tmp_path, Ctx())
