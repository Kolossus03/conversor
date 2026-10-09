"""The bridge between QML and the rest of the app. Never opens user files itself."""

import itertools
import os
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import (
    Property, QAbstractListModel, QByteArray, QModelIndex, QObject, Qt, QUrl, Signal, Slot,
)
from PySide6.QtGui import QDesktopServices, QGuiApplication

from . import models, registry
from .formats import KIND_NOUNS, detect
from .runner import WorkerRun
from .safepaths import UnsafePath, check_input, check_output_dir
from .sandbox import AI_WORKER_MEMORY_LIMIT, WORKER_MEMORY_LIMIT, kill_if_office
from .settings import Settings

MAX_FOLDER_FILES = 500
_uids = itertools.count(1)


@dataclass
class FileItem:
    path: str
    kind: str
    fmt: str
    uid: str = field(default_factory=lambda: f"f{next(_uids)}")
    status: str = "ready"  # ready | queued | running | done | error | unsupported
    progress: float = 0.0
    message: str = ""
    output: str = ""
    thumb: str = ""
    before: str = ""
    after: str = ""

    @property
    def name(self) -> str:
        return Path(self.path).name


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _needs_ffmpeg(kind: str, fmt: str) -> bool:
    """These jobs start ffmpeg as a second process, so their sandbox must allow one child."""
    return kind in ("video", "audio") or fmt == "heic"


def _file_url(path: str | None) -> str:
    return QUrl.fromLocalFile(path).toString() if path else ""


class FileModel(QAbstractListModel):
    ROLES = ("uid", "name", "path", "kind", "fmt", "status", "progress", "message",
             "output", "thumb", "before", "after")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[FileItem] = []

    def roleNames(self):
        return {Qt.ItemDataRole.UserRole + i: QByteArray(r.encode()) for i, r in enumerate(self.ROLES)}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        name = self.ROLES[role - Qt.ItemDataRole.UserRole] if role >= Qt.ItemDataRole.UserRole else None
        return getattr(item, name) if name else None

    def add(self, items: list[FileItem]) -> None:
        if not items:
            return
        self.beginInsertRows(QModelIndex(), len(self.items), len(self.items) + len(items) - 1)
        self.items.extend(items)
        self.endInsertRows()

    def find(self, uid: str) -> FileItem | None:
        return next((i for i in self.items if i.uid == uid), None)

    def update(self, uid: str, **changes) -> None:
        for row, item in enumerate(self.items):
            if item.uid == uid:
                for k, v in changes.items():
                    setattr(item, k, v)
                idx = self.index(row)
                self.dataChanged.emit(idx, idx)
                return

    def remove(self, uid: str) -> None:
        for row, item in enumerate(self.items):
            if item.uid == uid:
                self.beginRemoveRows(QModelIndex(), row, row)
                del self.items[row]
                self.endRemoveRows()
                return

    def clear(self) -> None:
        self.beginResetModel()
        self.items.clear()
        self.endResetModel()


class Backend(QObject):
    filesChanged = Signal()  # files added or removed
    countsChanged = Signal()  # a file's status changed
    groupsChanged = Signal()
    busyChanged = Signal()
    settingsChanged = Signal()
    modelsChanged = Signal()
    downloadChanged = Signal()
    modelNeeded = Signal(str, str, int)  # id, label, size in MB
    toast = Signal(str)
    optionsRequested = Signal(str)  # open the options panel of a file kind

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = Settings()
        self._files = FileModel(self)
        self._runs: list[WorkerRun] = []
        self._active: WorkerRun | None = None
        self._cancelled = False
        self._thumb_queue: list[str] = []
        self._thumb_run: WorkerRun | None = None
        self._download_run: WorkerRun | None = None
        self._download = {"model": "", "progress": 0.0}
        self._start_after_download = False
        self._outputs: set[str] = set()  # files this app created; only these may be opened
        self._secrets: dict[str, dict] = {}
        self._members: dict[str, list[str]] = {}  # combined task id -> all file uids in it
        self._office_pids: set[int] = set()
        self._files.rowsInserted.connect(self.filesChanged)
        self._files.rowsRemoved.connect(self.filesChanged)
        self._files.modelReset.connect(self.filesChanged)
        self._files.dataChanged.connect(self.countsChanged)
        self.filesChanged.connect(self.groupsChanged)
        self.filesChanged.connect(self.countsChanged)
        self.apply_theme()

    # ---- properties -------------------------------------------------------------------

    @Property(QObject, constant=True)
    def files(self):
        return self._files

    @Property(int, notify=filesChanged)
    def fileCount(self) -> int:
        return len(self._files.items)

    @Property(int, notify=countsChanged)
    def pendingCount(self) -> int:
        return len(self._pending())

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._active is not None or bool(self._runs)

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self) -> dict:
        s = self._settings
        return {"outputMode": s["output_mode"], "outputFolder": s["output_folder"],
                "gpu": s["gpu"], "theme": s["theme"]}

    @Property(str, notify=settingsChanged)
    def outputLabel(self) -> str:
        if self._settings["output_mode"] == "folder" and self._settings["output_folder"]:
            return f"Saving to {Path(self._settings['output_folder']).name}"
        return "Saving next to the originals"

    @Property("QVariantList", notify=modelsChanged)
    def models(self) -> list:
        return [m.to_dict() | {"sizeText": _human_size(m.size)} for m in models.MODELS.values()]

    @Property("QVariantMap", notify=downloadChanged)
    def download(self) -> dict:
        return dict(self._download)

    @Property("QVariantList", notify=groupsChanged)
    def groups(self) -> list:
        by_kind: dict[str, list[FileItem]] = {}
        for item in self._files.items:
            by_kind.setdefault(item.kind, []).append(item)
        return [self._group(kind, items) for kind, items in by_kind.items()]

    # ---- groups & choices ---------------------------------------------------------------

    def _group(self, kind: str, items: list[FileItem]) -> dict:
        n = len(items)
        one, many = KIND_NOUNS.get(kind, (kind, kind))
        label = f"{n} {one if n == 1 else many}"
        convert = registry.convert_op(kind)
        if convert is None:
            return {"kind": kind, "label": label, "supported": False, "targets": [], "tools": [],
                    "convertOp": "", "op": "", "target": "", "hint": "", "options": []}
        targets = registry.targets_for(kind, [i.fmt for i in items])
        op, target = self._choice(kind, targets)
        operation = registry.OPERATIONS[op]
        hint = operation.hint or (registry.target_hint(kind, target) if operation.role == "convert" else "")
        return {
            "kind": kind, "label": label, "supported": True, "convertOp": convert.id,
            "targets": [{"id": t, "label": registry.target_label(kind, t)} for t in targets],
            "tools": [{"id": o.id, "label": o.label} for o in registry.operations_for(kind) if o.role == "tool"],
            "op": op, "target": target, "hint": hint,
            "options": self._visible_options(operation, target),
        }

    def _choice(self, kind: str, targets: list[str]) -> tuple[str, str]:
        convert = registry.convert_op(kind).id
        last = self._settings["last_choice"].get(kind, {})
        op = last.get("op", convert)
        if op not in registry.OPERATIONS or registry.OPERATIONS[op].kind != kind:
            op = convert
        target = last.get("target", "")
        if op == convert and target not in targets:
            target = targets[0] if targets else ""
        return op, target

    def _options(self, op_id: str) -> dict:
        op = registry.OPERATIONS[op_id]
        defaults = registry.default_options(op)
        saved = self._settings["op_options"].get(op_id, {}) | self._secrets.get(op_id, {})
        return defaults | {k: v for k, v in saved.items() if k in defaults}

    def _visible_options(self, op: registry.Operation, target: str) -> list:
        values = self._options(op.id)
        out = []
        for opt in op.options:
            if op.role == "convert" and opt.targets and target not in opt.targets:
                continue
            if opt.when and values.get(opt.when[0]) != opt.when[1]:
                continue
            out.append(opt.to_dict() | {"value": values[opt.key]})
        return out

    @Slot(str, str, str)
    def choose(self, kind: str, op_id: str, target: str) -> None:
        if op_id not in registry.OPERATIONS or self.busy:
            return
        choices = dict(self._settings["last_choice"])
        choices[kind] = {"op": op_id, "target": target}
        self._settings["last_choice"] = choices
        # A new choice makes already-converted files of this kind pending again.
        for item in self._files.items:
            if item.kind == kind and item.status in ("done", "error"):
                self._files.update(item.uid, status="ready", progress=0.0, message="", output="",
                                   before="", after="")
        self.groupsChanged.emit()

    @Slot(str, str, "QVariant")
    def setOption(self, op_id: str, key: str, value) -> None:
        if op_id not in registry.OPERATIONS:
            return
        opt = next((o for o in registry.OPERATIONS[op_id].options if o.key == key), None)
        if opt is None:
            return
        if opt.secret:  # passwords live in memory only
            self._secrets.setdefault(op_id, {})[key] = value
            self.groupsChanged.emit()
            return
        all_opts = dict(self._settings["op_options"])
        current = dict(all_opts.get(op_id, {}))
        current[key] = value
        all_opts[op_id] = current
        self._settings["op_options"] = all_opts
        self.groupsChanged.emit()

    # ---- files --------------------------------------------------------------------------

    @Slot("QVariantList")
    def addUrls(self, urls) -> None:
        paths = []
        for u in urls:
            url = u if isinstance(u, QUrl) else QUrl(str(u))
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        self.addPaths(paths)

    def addPaths(self, raw_paths: list[str]) -> None:
        known = {i.path for i in self._files.items}
        new: list[FileItem] = []
        skipped = 0
        for raw in self._expand(raw_paths):
            try:
                path = str(check_input(os.path.abspath(raw)))
            except (UnsafePath, OSError):
                skipped += 1
                continue
            if path in known:
                continue
            known.add(path)
            ft = detect(Path(path))
            item = FileItem(path=path, kind=ft.kind, fmt=ft.fmt)
            if registry.convert_op(ft.kind) is None:
                item.status, item.message = "unsupported", "This file type isn't supported yet"
            new.append(item)
        self._files.add(new)
        if skipped:
            self.toast.emit(f"Skipped {skipped} item(s) that can't be opened safely")
        self._queue_thumbs([i.uid for i in new if i.kind in ("image", "pdf", "video")])

    def _expand(self, raw_paths: list[str]):
        for raw in raw_paths:
            p = Path(raw)
            if p.is_dir():
                files = (f for f in sorted(p.rglob("*")) if f.is_file())
                yield from (str(f) for f in itertools.islice(files, MAX_FOLDER_FILES))
            else:
                yield raw

    @Slot(str)
    def removeFile(self, uid: str) -> None:
        item = self._files.find(uid)
        if item and item.status not in ("queued", "running"):
            self._files.remove(uid)

    @Slot()
    def clear(self) -> None:
        if not self.busy:
            self._files.clear()

    def _pending(self) -> list[FileItem]:
        return [i for i in self._files.items if i.status in ("ready", "error")
                and registry.convert_op(i.kind) is not None]

    # ---- conversion ---------------------------------------------------------------------

    def _output_dir(self, item: FileItem) -> str:
        if self._settings["output_mode"] == "folder" and self._settings["output_folder"]:
            return self._settings["output_folder"]
        return str(Path(item.path).parent)

    @Slot()
    def start(self) -> None:
        if self.busy:
            return
        pending = self._pending()
        if not pending:
            return
        if self._settings["output_mode"] == "folder":
            try:
                check_output_dir(self._settings["output_folder"])
            except (UnsafePath, OSError):
                self.toast.emit("The output folder is missing. Choose another one in Settings.")
                return

        groups = {g["kind"]: g for g in self.groups}
        by_kind: dict[str, list[FileItem]] = {}
        for item in pending:
            by_kind.setdefault(item.kind, []).append(item)

        plain, ai, media = [], [], []
        self._members.clear()
        for kind, items in by_kind.items():
            g = groups[kind]
            options = self._options(g["op"])
            model_id = registry.required_model(g["op"], options)
            if model_id and not models.MODELS[model_id].installed():
                spec = models.MODELS[model_id]
                self._start_after_download = True
                self.modelNeeded.emit(spec.id, spec.label, round(spec.size / 1024**2))
                return
            missing = [o.label for o in registry.OPERATIONS[g["op"]].options
                       if o.type == "password" and not str(options.get(o.key, "")).strip()]
            if missing:
                self._expand_options(kind)
                self.toast.emit(f"Enter a {missing[0].lower()} in Options first")
                return
            base = {"op": g["op"], "target": g["target"], "options": options, "kind": kind}
            if registry.OPERATIONS[g["op"]].combine:
                # One output from every file of the group, in list order (done ones included).
                members = [i for i in self._files.items if i.kind == kind]
                tasks = [base | {"id": members[0].uid, "inputs": [i.path for i in members],
                                 "fmts": [i.fmt for i in members], "out_dir": self._output_dir(members[0])}]
                self._members[members[0].uid] = [i.uid for i in members]
            else:
                tasks = [base | {"id": i.uid, "input": i.path, "fmt": i.fmt, "out_dir": self._output_dir(i)}
                         for i in items]
            if model_id:
                ai.extend(tasks)
            else:
                for task in tasks:
                    (media if _needs_ffmpeg(kind, task.get("fmt") or "") else plain).append(task)

        for task in plain + media + ai:
            for uid in self._members.get(task["id"], [task["id"]]):
                self._files.update(uid, status="queued", progress=0.0, message="", output="")
        self._cancelled = False
        if plain:
            self._runs.append(self._make_run(plain, WORKER_MEMORY_LIMIT))
        if media:
            self._runs.append(self._make_run(media, WORKER_MEMORY_LIMIT, processes=2))
        if ai:
            self._runs.append(self._make_run(ai, AI_WORKER_MEMORY_LIMIT))
        self._next_run()

    def _expand_options(self, kind: str) -> None:
        self.optionsRequested.emit(kind)

    def _make_run(self, tasks, limit, processes: int = 1) -> WorkerRun:
        run = WorkerRun(tasks, {"gpu": bool(self._settings["gpu"])}, limit, self, processes)
        run.ids = {uid for t in tasks for uid in self._members.get(t["id"], [t["id"]])}
        run.event.connect(self._on_event)
        run.finished.connect(self._on_run_finished)
        return run

    def _next_run(self) -> None:
        self._active = self._runs.pop(0) if self._runs else None
        if self._active:
            self._active.start()
        self.busyChanged.emit()

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True
        for run in self._runs:
            run.deleteLater()
        self._runs.clear()
        if self._active:
            self._active.cancel()

    def _on_event(self, ev: dict) -> None:
        uid, kind = ev.get("id"), ev.get("event")
        if kind == "office" and isinstance(ev.get("pid"), int):
            self._office_pids.add(ev["pid"])
            return
        if not uid:
            return
        for member in self._members.get(uid, [uid]):
            self._apply_event(member, kind, ev)

    def _apply_event(self, uid: str, kind: str, ev: dict) -> None:
        if kind == "start":
            self._files.update(uid, status="running", progress=0.05)
        elif kind == "progress":
            self._files.update(uid, progress=float(ev.get("progress", 0)))
        elif kind == "done":
            out = ev.get("output", "")
            self._outputs.add(out)
            compare = ev.get("compare") or {}
            what = "Saved to folder" if ev.get("folder") else "Saved as"
            self._files.update(uid, status="done", progress=1.0, output=out,
                               message=f"{what} {Path(out).name} · {_human_size(int(ev.get('size', 0)))}",
                               before=_file_url(compare.get("before")), after=_file_url(compare.get("after")))
        elif kind == "error":
            self._files.update(uid, status="error", progress=0.0, message=ev.get("message", "Failed"))

    def _on_run_finished(self) -> None:
        finished = self._active
        for uid in finished.ids if finished else ():
            item = self._files.find(uid)
            if item and item.status in ("queued", "running"):
                if self._cancelled:
                    self._files.update(uid, status="ready", progress=0.0, message="Cancelled")
                else:
                    self._files.update(uid, status="error", progress=0.0,
                                       message="Stopped unexpectedly (file too large or damaged?)")
        if finished:
            finished.deleteLater()
        self._kill_orphaned_office()
        if self._cancelled:  # runs that never started
            for item in self._files.items:
                if item.status == "queued":
                    self._files.update(item.uid, status="ready", message="Cancelled")
        self._next_run()
        if not self.busy and not self._cancelled:
            done = sum(1 for i in self._files.items if i.status == "done")
            failed = sum(1 for i in self._files.items if i.status == "error")
            self.toast.emit(f"{done} done" + (f", {failed} failed" if failed else ""))

    def _kill_orphaned_office(self) -> None:
        """The worker quits Office when it finishes; this catches crashes and cancels."""
        for pid in self._office_pids:
            kill_if_office(pid)
        self._office_pids.clear()

    # ---- thumbnails ---------------------------------------------------------------------

    def _queue_thumbs(self, uids: list[str]) -> None:
        self._thumb_queue.extend(uids)
        if self._thumb_run is None and self._thumb_queue:
            tasks = []
            for uid in self._thumb_queue:
                item = self._files.find(uid)
                if item:
                    tasks.append({"id": uid, "op": "thumb", "input": item.path, "kind": item.kind,
                                  "fmt": item.fmt})
            self._thumb_queue.clear()
            run = WorkerRun(tasks, {}, WORKER_MEMORY_LIMIT, self, processes=2)  # video frames need ffmpeg
            run.event.connect(self._on_thumb)
            run.finished.connect(self._on_thumbs_finished)
            self._thumb_run = run
            run.start()

    def _on_thumb(self, ev: dict) -> None:
        if ev.get("event") == "done" and ev.get("thumb"):
            self._files.update(ev["id"], thumb=_file_url(ev["thumb"]))

    def _on_thumbs_finished(self) -> None:
        self._thumb_run.deleteLater()
        self._thumb_run = None
        self._queue_thumbs([])

    # ---- models -------------------------------------------------------------------------

    @Slot(str)
    def downloadModel(self, model_id: str) -> None:
        if model_id not in models.MODELS or self._download_run:
            return
        self._download = {"model": model_id, "progress": 0.0}
        self.downloadChanged.emit()
        run = WorkerRun([{"id": "download", "op": "model.download", "model": model_id}], {},
                        WORKER_MEMORY_LIMIT, self)
        run.event.connect(self._on_download_event)
        run.finished.connect(self._on_download_finished)
        self._download_run = run
        run.start()

    def _on_download_event(self, ev: dict) -> None:
        if ev.get("event") == "progress":
            self._download = {**self._download, "progress": float(ev.get("progress", 0))}
            self.downloadChanged.emit()
        elif ev.get("event") == "error":
            self._start_after_download = False
            self.toast.emit(f"Download failed: {ev.get('message', '')}")

    def _on_download_finished(self) -> None:
        self._download_run.deleteLater()
        self._download_run = None
        self._download = {"model": "", "progress": 0.0}
        self.downloadChanged.emit()
        self.modelsChanged.emit()
        if self._start_after_download:
            self._start_after_download = False
            self.start()

    @Slot()
    def cancelDownload(self) -> None:
        self._start_after_download = False
        if self._download_run:
            self._download_run.cancel()

    @Slot()
    def declineDownload(self) -> None:
        self._start_after_download = False

    @Slot(str)
    def deleteModel(self, model_id: str) -> None:
        if model_id in models.MODELS and not self.busy:
            models.delete(model_id)
            self.modelsChanged.emit()

    # ---- settings & shell ---------------------------------------------------------------

    @Slot(str, "QVariant")
    def setSetting(self, key: str, value) -> None:
        mapping = {"outputMode": "output_mode", "gpu": "gpu", "theme": "theme"}
        if key in mapping:
            self._settings[mapping[key]] = value
            if key == "theme":
                self.apply_theme()
            self.settingsChanged.emit()

    @Slot("QVariant")
    def setOutputFolder(self, url) -> None:
        url = url if isinstance(url, QUrl) else QUrl(str(url))
        try:
            folder = check_output_dir(url.toLocalFile())
        except (UnsafePath, OSError):
            self.toast.emit("That folder can't be used")
            return
        self._settings["output_folder"] = str(folder)
        self._settings["output_mode"] = "folder"
        self.settingsChanged.emit()

    def apply_theme(self) -> None:
        hints = QGuiApplication.styleHints()
        scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(
            self._settings["theme"], Qt.ColorScheme.Unknown)
        hints.setColorScheme(scheme)

    @Slot(str)
    def openFile(self, path: str) -> None:
        if path in self._outputs and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def showInFolder(self, path: str) -> None:
        if path not in self._outputs or not os.path.exists(path):
            return
        from win32com.shell import shell

        folder_pidl = shell.SHILCreateFromPath(os.path.dirname(path), 0)[0]
        item_pidl = shell.SHILCreateFromPath(path, 0)[0]
        shell.SHOpenFolderAndSelectItems(folder_pidl, (item_pidl,), 0)
