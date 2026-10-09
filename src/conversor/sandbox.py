"""Windows Job Object limits for worker processes.

Each worker gets its own job: capped memory, no child processes, killed when the job
handle closes (so workers never outlive the app, even if it crashes).
"""

import os
import sys
from pathlib import Path

import win32api
import win32con
import win32job
import win32process



def _physical_memory() -> int:
    return win32api.GlobalMemoryStatusEx()["TotalPhys"]


# Plain conversions get a tight cap. AI jobs need more: CUDA commits a lot of host memory.
WORKER_MEMORY_LIMIT = min(8 * 1024**3, _physical_memory() // 2)
AI_WORKER_MEMORY_LIMIT = int(_physical_memory() * 0.75)


def worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    # A venv's python.exe is a launcher that spawns the real interpreter as a child, which the
    # one-process job limit forbids. Start the base interpreter directly with the venv's packages.
    site_dirs = [p for p in sys.path if p.endswith("site-packages")]
    boot = (
        "import site, sys\n"
        f"for d in {site_dirs!r}: site.addsitedir(d)\n"
        "from conversor.worker import main\n"
        "sys.exit(main())"
    )
    base = Path(sys._base_executable)
    windowless = base.with_name("pythonw.exe")  # no console window flashing up per job
    return [str(windowless if windowless.exists() else base), "-I", "-c", boot]


class Job:
    def __init__(self, memory_limit: int = WORKER_MEMORY_LIMIT, processes: int = 1) -> None:
        self.handle = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(self.handle, win32job.JobObjectExtendedLimitInformation)
        basic = info["BasicLimitInformation"]
        basic["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | win32job.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        )
        basic["ActiveProcessLimit"] = processes  # 2 when the worker must run ffmpeg
        info["ProcessMemoryLimit"] = memory_limit
        win32job.SetInformationJobObject(self.handle, win32job.JobObjectExtendedLimitInformation, info)

    def assign(self, pid: int) -> None:
        proc = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        try:
            win32job.AssignProcessToJobObject(self.handle, proc)
        finally:
            win32api.CloseHandle(proc)

    def kill(self) -> None:
        try:
            win32job.TerminateJobObject(self.handle, 1)
        except Exception:
            pass

    def close(self) -> None:
        if self.handle:
            self.handle.Close()
            self.handle = None


_OFFICE_EXES = {"winword.exe", "excel.exe", "powerpnt.exe"}


def kill_if_office(pid: int) -> None:
    """Terminate a leftover Office process we started, checking it really is Office first."""
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_TERMINATE | win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return  # already gone
    try:
        exe = os.path.basename(win32process.GetModuleFileNameEx(handle, None)).lower()
        if exe in _OFFICE_EXES:
            win32api.TerminateProcess(handle, 1)
    except Exception:
        pass
    finally:
        win32api.CloseHandle(handle)
