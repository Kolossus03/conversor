"""Shared ONNX Runtime session handling for the AI tools (CUDA GPU when available, else CPU)."""

import os

from .. import models

_sessions: dict[tuple[str, bool], object] = {}


def session(model_id: str, gpu: bool):
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
    return _sessions[key]
