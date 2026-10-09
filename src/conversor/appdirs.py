import os
from pathlib import Path

APP = "Conversor"


def _base(env: str) -> Path:
    root = os.environ.get(env) or str(Path.home() / "AppData" / ("Roaming" if env == "APPDATA" else "Local"))
    return Path(root) / APP


def config_dir() -> Path:
    return _base("APPDATA")


def models_dir() -> Path:
    return _base("LOCALAPPDATA") / "models"


def cache_dir() -> Path:
    return _base("LOCALAPPDATA") / "cache"
