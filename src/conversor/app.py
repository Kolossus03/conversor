import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .backend import Backend

QML_DIR = Path(__file__).parent / "qml"
APP_ID = "Conversor.App"  # must match the AppUserModelID on the shortcuts


def _set_app_id() -> None:
    """Make Windows group the taskbar button under Conversor's icon, not python.exe's."""
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def run(args: list[str]) -> int:
    _set_app_id()
    QQuickStyle.setStyle("FluentWinUI3")
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Conversor")
    app.setOrganizationName("Conversor")
    icon = QML_DIR / "icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        return 1
    if args:  # files passed by Explorer "Send to" or the command line
        backend.addPaths(args)
    code = app.exec()
    del engine  # tear down QML before the backend it binds to
    return code
