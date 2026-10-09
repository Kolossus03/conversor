import json
import os

from .appdirs import config_dir

DEFAULTS = {
    "output_mode": "beside",  # "beside" the original, or a fixed "folder"
    "output_folder": "",
    "gpu": True,
    "theme": "system",  # "system" | "light" | "dark"
    "op_options": {},  # remembered options per operation id
    "last_choice": {},  # remembered {op, target} per file kind
}


class Settings:
    def __init__(self) -> None:
        self.path = config_dir() / "settings.json"
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
