"""AI models: pinned URLs and SHA-256 hashes. A model is only ever loaded after its hash matches."""

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .appdirs import models_dir


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    url: str
    sha256: str
    size: int

    @property
    def path(self) -> Path:
        return models_dir() / f"{self.id}.onnx"

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "size": self.size, "installed": self.installed()}

    def installed(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size == self.size


_RELEASES = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
# ONNX exports of the official Real-ESRGAN weights, pinned to one commit.
_ESRGAN = "https://huggingface.co/jonathanst29/tinier-upscale-models/resolve/899dc1e4b22bbf1955c2f1739c085edc080cb366/"

MODELS = {
    m.id: m
    for m in (
        ModelSpec(
            "birefnet-lite", "Background removal: Fast (BiRefNet lite, MIT)",
            _RELEASES + "BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
            "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333", 224005088,
        ),
        ModelSpec(
            "birefnet", "Background removal: Best (BiRefNet, MIT)",
            _RELEASES + "BiRefNet-general-epoch_244.onnx",
            "58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c", 972666916,
        ),
        ModelSpec(
            "esrgan-fast", "Upscaling: Fast (Real-ESRGAN general v3, BSD)",
            _ESRGAN + "realesr-general-x4v3.onnx",
            "924ebad6532777303582d4ce7811849b88869231a3ae7093e0f21200249df8d5", 4866396,
        ),
        ModelSpec(
            "esrgan", "Upscaling: Best (Real-ESRGAN x4plus, BSD)",
            _ESRGAN + "realesrgan-x4plus.onnx",
            "4ed6a45a8185bde6c8d7c7790a6e80e3c5b9f608946f634021068dd0fd0473c8", 67051618,
        ),
    )
}


class ModelError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def verified_path(model_id: str) -> Path:
    spec = MODELS[model_id]
    if not spec.installed():
        raise ModelError(f"Model '{spec.label}' is not downloaded")
    if _sha256(spec.path) != spec.sha256:
        raise ModelError(f"Model '{spec.label}' failed its integrity check; delete and re-download it")
    return spec.path


def download(model_id: str, on_progress) -> Path:
    """Download over HTTPS, verify size and SHA-256, then move into place."""
    spec = MODELS[model_id]
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    part = spec.path.with_suffix(".part")
    h = hashlib.sha256()
    received = 0
    req = urllib.request.Request(spec.url, headers={"User-Agent": "Conversor"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
            if not resp.geturl().startswith("https://"):
                raise ModelError("Refusing non-HTTPS redirect")
            while chunk := resp.read(1024 * 1024):
                received += len(chunk)
                if received > spec.size:
                    raise ModelError("Download is larger than expected")
                h.update(chunk)
                out.write(chunk)
                on_progress(received / spec.size)
        if received != spec.size or h.hexdigest() != spec.sha256:
            raise ModelError("Downloaded file failed its integrity check")
        os.replace(part, spec.path)
        return spec.path
    finally:
        part.unlink(missing_ok=True)


def delete(model_id: str) -> None:
    MODELS[model_id].path.unlink(missing_ok=True)
