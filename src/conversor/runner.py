"""Runs one sandboxed worker process and turns its output into Qt signals."""

import json

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .appdirs import cache_dir
from .sandbox import Job, worker_command

IDLE_TIMEOUT_MS = 10 * 60 * 1000  # kill a worker that reports nothing for 10 minutes


class WorkerRun(QObject):
    event = Signal(dict)
    finished = Signal()

    def __init__(self, tasks: list[dict], settings: dict, memory_limit: int, parent=None,
                 processes: int = 1) -> None:
        super().__init__(parent)
        self.ids = {t["id"] for t in tasks}
        self._payload = json.dumps({"settings": settings, "tasks": tasks}) + "\n"
        self._job = Job(memory_limit, processes)
        self._buffer = b""
        self._done = False
        self._proc = QProcess(self)
        # Never run with the user's folder as cwd: Windows searches it for DLLs.
        workdir = cache_dir()
        workdir.mkdir(parents=True, exist_ok=True)
        self._proc.setWorkingDirectory(str(workdir))
        self._proc.started.connect(self._on_started)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._watchdog = QTimer(self, singleShot=True, interval=IDLE_TIMEOUT_MS)
        self._watchdog.timeout.connect(self.cancel)
        self._log = open(workdir / "worker.log", "ab")

    def start(self) -> None:
        cmd = worker_command()
        self._proc.start(cmd[0], cmd[1:])

    def cancel(self) -> None:
        self._job.kill()

    def _on_started(self) -> None:
        # The worker blocks on stdin until it gets the job, so it does nothing before this.
        self._job.assign(self._proc.processId())
        self._proc.write(self._payload.encode("utf-8"))
        self._proc.closeWriteChannel()
        self._watchdog.start()

    def _on_stdout(self) -> None:
        self._watchdog.start()
        self._buffer += bytes(self._proc.readAllStandardOutput())
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            if line.strip():
                try:
                    self.event.emit(json.loads(line))
                except ValueError:
                    pass

    def _on_stderr(self) -> None:
        data = bytes(self._proc.readAllStandardError())
        if self._log.tell() < 5 * 1024 * 1024:
            self._log.write(data)
            self._log.flush()

    def _on_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish()

    def _on_finished(self, *_):
        self._on_stdout()
        self._finish()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._watchdog.stop()
        self._job.close()
        self._log.close()
        self.finished.emit()
