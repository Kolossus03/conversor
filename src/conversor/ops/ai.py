"""Shared ONNX Runtime session handling for the AI tools (CUDA GPU when available, else CPU)."""

import importlib.util
import os
import sys
from functools import cache
from pathlib import Path

from .. import models

_sessions: dict[tuple[str, bool], object] = {}


@cache
def cuda_installed() -> bool:
    """Whether the CUDA provider and NVIDIA libraries are on disk, where onnxruntime.preload_dlls
    looks for them. The CPU-only installer leaves them out; checked without importing onnxruntime."""
    spec = importlib.util.find_spec("onnxruntime")
    if spec is None or not spec.origin:
        return False
    ort_dir = Path(spec.origin).parent
    return ((ort_dir / "capi" / "onnxruntime_providers_cuda.dll").is_file()
            and (ort_dir.parent / "nvidia" / "cudnn").is_dir())


def session(model_id: str, gpu: bool):
    gpu = gpu and cuda_installed()
    key = (model_id, gpu)
    if key not in _sessions:
        # NVIDIA caches the GPU kernels it compiles on first use; the default 256 MB is too small.
        os.environ.setdefault("CUDA_CACHE_MAXSIZE", str(4 * 1024**3))
        import onnxruntime as ort

        path = models.verified_path(model_id)
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        providers: list = ["CPUExecutionProvider"]
        if gpu and "CUDAExecutionProvider" in ort.get_available_providers():
            ort.preload_dlls()
            providers.insert(0, ("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}))
        # Falls back to CPU by itself if the GPU cannot be initialised.
        _sessions[key] = ort.InferenceSession(str(path), sess_options=opts, providers=providers)
        print(f"{model_id}: {_sessions[key].get_providers()[0]}", file=sys.stderr)
    return _sessions[key]
