"""Remove everything Conversor put outside its own folder: shortcuts, settings, cache and AI models.

Your converted files are never touched. Afterwards, delete the project folder itself to finish.
"""

import os
import shutil
from pathlib import Path

APPDATA = Path(os.environ["APPDATA"])
LOCAL = Path(os.environ["LOCALAPPDATA"])
ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    (APPDATA / "Microsoft/Windows/Start Menu/Programs/Conversor.lnk", "Start Menu shortcut"),
    (APPDATA / "Microsoft/Windows/SendTo/Conversor.lnk", 'Explorer "Send to" entry'),
    (ROOT / "Conversor.lnk", "shortcut in the app folder"),
    (APPDATA / "Conversor", "settings"),
    (LOCAL / "Conversor", "cache and downloaded AI models"),
]


def size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> None:
    present = [(p, label) for p, label in TARGETS if p.exists()]
    if not present:
        print("Nothing to remove: Conversor is already uninstalled.")
    else:
        print("This will remove:")
        for p, label in present:
            print(f"  - {label}  ({size(p) / 1024**2:.0f} MB)  {p}")
        print("\nYour converted files are not touched.")
        if input("\nType YES to uninstall: ").strip() != "YES":
            print("Cancelled. Nothing was removed.")
            return
        for p, label in present:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            print(f"Removed {label}")
    print(f"\nTo finish, close this window and delete the folder:\n  {ROOT}")


if __name__ == "__main__":
    main()
    input("\nPress Enter to close.")
