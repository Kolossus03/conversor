"""Create (or with --remove, delete) Conversor shortcuts.

Default: a shortcut in this project folder.  --start-menu and --send-to add the
Start Menu entry and the Explorer right-click "Send to > Conversor" entry.
"""
import os
import sys
from pathlib import Path

import pythoncom
import win32com.client
from win32com.propsys import propsys, pscon

ROOT = Path(__file__).resolve().parent.parent
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
ICON = ROOT / "src" / "conversor" / "qml" / "icon.ico"
APP_ID = "Conversor.App"  # same as conversor.app.APP_ID, so pinned shortcuts keep the icon


def set_app_id(lnk: Path) -> None:
    store = propsys.SHGetPropertyStoreFromParsingName(str(lnk), None, 2, propsys.IID_IPropertyStore)  # GPS_READWRITE
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()


def targets(args: list[str]) -> list[Path]:
    out = [ROOT / "Conversor.lnk"]
    if "--start-menu" in args:
        out.append(Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Conversor.lnk")
    if "--send-to" in args:
        out.append(Path(os.environ["APPDATA"]) / "Microsoft/Windows/SendTo/Conversor.lnk")
    return out


def main(args: list[str]) -> None:
    shell = win32com.client.Dispatch("WScript.Shell")
    for lnk in targets(args):
        if "--remove" in args:
            lnk.unlink(missing_ok=True)
            print("removed", lnk)
            continue
        sc = shell.CreateShortcut(str(lnk))
        sc.TargetPath = str(PYTHONW)
        sc.Arguments = "-m conversor"
        sc.WorkingDirectory = str(ROOT)
        sc.IconLocation = str(ICON)
        sc.Description = "Convert files locally"
        sc.Save()
        set_app_id(lnk)
        print("created", lnk)


if __name__ == "__main__":
    main(sys.argv[1:])
