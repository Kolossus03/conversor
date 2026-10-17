# PyInstaller spec for Conversor: one --onedir, windowed build.
# Run through scripts/build_installer.py, which adds ffmpeg and makes the two installers.
import re
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src" / "conversor"
SITE = Path(sysconfig.get_paths()["purelib"])

# NVIDIA's CUDA and cuDNN DLLs, kept where onnxruntime.preload_dlls looks for them
# (site-packages/nvidia/...). Added as data so PyInstaller doesn't scan or relocate them.
nvidia = [(str(dll), str(dll.parent.relative_to(SITE))) for dll in (SITE / "nvidia").rglob("*.dll")]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(SRC / "qml"), "conversor/qml"), *collect_data_files("rapidocr"), *nvidia],
    hiddenimports=["win32timezone"],
    excludes=["tkinter", "pytest", "_pytest", "unittest", "pydoc_data", "IPython", "matplotlib",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtCharts",
              "PySide6.QtWidgets", "PySide6.QtPdf", "PySide6.QtLocation"],
)

# PySide6's QML hook collects every QML module Qt ships. The app imports only QtQuick, Controls
# (FluentWinUI3 style), Layouts, Shapes and Dialogs, so drop the rest and the Qt DLLs behind them.
_QT = r"PySide6[\\/]"
_DROP = re.compile("|".join([
    _QT + r"qml[\\/](Qt3D|Qt5Compat|QtCharts|QtDataVisualization|QtGraphs|QtLocation|QtMultimedia"
          r"|QtPositioning|QtRemoteObjects|QtScxml|QtSensors|QtTest|QtTextToSpeech|QtWebChannel"
          r"|QtWebEngine|QtWebSockets|QtWebView|QtQuick3D|QtNetwork)",
    _QT + r"qml[\\/]QtQuick[\\/](VirtualKeyboard|Pdf|Particles|Scene2D|Scene3D|Timeline|LocalStorage"
          r"|Test|VectorImage|Studio)",
    _QT + r"qml[\\/]QtQuick[\\/]Controls[\\/](Material|Imagine|Universal|iOS|macOS)",
    _QT + r"(Qt6)?(WebEngine|Quick3D|3D|Multimedia|Pdf|Charts|Graphs|DataVisualization|Location"
          r"|Positioning|VirtualKeyboard|Sensors|TextToSpeech|RemoteObjects|Scxml|WebChannel|WebSockets"
          r"|WebView|SpatialAudio|Test|QuickTest|Bluetooth|Nfc|SerialPort|Sql|Designer|Help|ShaderTools"
          r"|QuickParticles|QuickTimeline)",
    _QT + r"plugins[\\/](multimedia|position|sensors|sqldrivers|qmltooling|webview|texttospeech"
          r"|geoservices|canbus|scenegraph|sceneparsers|renderers|renderplugins|geometryloaders)",
    _QT + r"translations[\\/](?!qtbase_en|qt_en)",
    _QT + r"(opengl32sw\.dll|resources[\\/]qtwebengine|QtWebEngineProcess)",
]), re.IGNORECASE)
# TensorRT isn't used; its provider drags in a 210 MB nvinfer DLL found on PATH.
_NO_TENSORRT = re.compile(r"onnxruntime[\\/]capi[\\/]onnxruntime_providers_tensorrt|nvinfer|nvonnxparser",
                          re.IGNORECASE)
a.binaries = [b for b in a.binaries if not _NO_TENSORRT.match(b[0])]
a.datas = [d for d in a.datas if not _DROP.match(d[0])]
a.binaries = [b for b in a.binaries if not _DROP.match(b[0])]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Conversor",
    console=False,
    icon=str(SRC / "qml" / "icon.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Conversor", upx=False)
