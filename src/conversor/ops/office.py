"""Word, Excel and PowerPoint conversions through the user's own Microsoft Office.

Hardening:
- a private, hidden Office instance per batch (DispatchEx), never the user's open windows
- macros force-disabled, files opened read-only, nothing added to recent files
- a dummy password, so protected files fail fast instead of showing a password prompt
- a watchdog kills the Office process if one file hangs; the app also gets the process
  id, so Office never outlives the job even if this worker is killed
"""

import contextlib
import os
import threading
import winreg
from pathlib import Path

import pywintypes
import win32api
import win32com.client
import win32con
import win32process

from ..formats import OLE_MAGIC
from ..safepaths import new_output_dir, write_new_file

MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3
DUMMY_PASSWORD = "conversor-no-password"
FILE_TIMEOUT = 120  # seconds per file

# Office's own format codes.
WORD_FORMATS = {"pdf": 17, "docx": 16, "odt": 23, "rtf": 6, "txt": 7}
EXCEL_FORMATS = {"xlsx": 51, "csv": 62, "ods": 60}
POWERPOINT_FORMATS = {"pdf": 32, "pptx": 24, "odp": 35}


class OfficeError(RuntimeError):
    pass


def _processes_named(exe: str) -> set[int]:
    found = set()
    for pid in win32process.EnumProcesses():
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        except pywintypes.error:
            continue
        try:
            if os.path.basename(win32process.GetModuleFileNameEx(handle, None)).lower() == exe:
                found.add(pid)
        except pywintypes.error:
            pass
        finally:
            win32api.CloseHandle(handle)
    return found


class _Instance:
    progid = ""
    name = ""
    exe = ""

    def __init__(self) -> None:
        self.app = None
        self.pid = 0

    def get(self, ctx):
        if self.app is None:
            before = _processes_named(self.exe)
            try:
                self.app = win32com.client.DispatchEx(self.progid)
            except pywintypes.com_error:
                raise OfficeError(f"Microsoft {self.name} is needed for this file but isn't installed") from None
            # DispatchEx always starts a new process: the one that wasn't there before is ours.
            new = _processes_named(self.exe) - before
            self.pid = new.pop() if len(new) == 1 else 0
            if self.pid:
                ctx.office_process(self.pid)
            self.configure(self.app)
        return self.app

    def configure(self, app) -> None:
        raise NotImplementedError

    def kill(self) -> None:
        if self.pid:
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, self.pid)
                win32api.TerminateProcess(handle, 1)
                win32api.CloseHandle(handle)
            except pywintypes.error:
                pass
        self.app, self.pid = None, 0

    def quit(self) -> None:
        if self.app is not None:
            try:
                self.app.Quit()
            except pywintypes.com_error:
                self.kill()
        self.app, self.pid = None, 0

    def run(self, ctx, work, src: Path):
        """Run work(app) with a timeout; a hung Office gets killed, which unblocks the call."""
        if src.suffix.lower() in (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"):
            with open(src, "rb") as f:
                if f.read(8) == OLE_MAGIC:  # modern Office files are only wrapped like this when encrypted
                    raise OfficeError("This file is password-protected. Remove the password in Office first.")
        app = self.get(ctx)
        timer = threading.Timer(FILE_TIMEOUT, self.kill)
        timer.start()
        try:
            return work(app)
        except pywintypes.com_error as exc:
            if self.app is None:
                raise OfficeError(f"{self.name} took too long (is the file password-protected or damaged?)") from None
            raise OfficeError(_com_message(exc, self.name)) from None
        finally:
            timer.cancel()


def _com_message(exc, app_name: str) -> str:
    detail = ""
    if len(exc.args) > 2 and exc.args[2] and len(exc.args[2]) > 2 and exc.args[2][2]:
        detail = str(exc.args[2][2]).strip()
    if "password" in detail.lower():
        return "This file is password-protected"
    return f"{app_name} couldn't open or convert this file" + (f": {detail[:200]}" if detail else "")


class _Word(_Instance):
    progid, name, exe = "Word.Application", "Word", "winword.exe"

    def configure(self, app) -> None:
        app.Visible = False
        app.DisplayAlerts = 0  # wdAlertsNone
        app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
        app.Options.UpdateLinksAtOpen = False
        app.Options.ConfirmConversions = False
        app.Options.DoNotPromptForConvert = True

    def convert(self, src: Path, target: str, out: Path, ctx) -> None:
        def work(app):
            doc = app.Documents.Open(
                FileName=str(src), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False,
                PasswordDocument=DUMMY_PASSWORD, Visible=False, OpenAndRepair=False, NoEncodingDialog=True,
            )
            try:
                ctx.progress(0.5)
                if target == "txt":
                    doc.SaveAs2(FileName=str(out), FileFormat=WORD_FORMATS["txt"], Encoding=65001,
                                AddToRecentFiles=False)
                else:
                    doc.SaveAs2(FileName=str(out), FileFormat=WORD_FORMATS[target], AddToRecentFiles=False)
            finally:
                doc.Close(SaveChanges=0)

        self.run(ctx, work, src)


class _Excel(_Instance):
    progid, name, exe = "Excel.Application", "Excel", "excel.exe"

    def configure(self, app) -> None:
        app.Visible = False
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        app.EnableEvents = False
        app.ScreenUpdating = False
        app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE

    def convert(self, src: Path, target: str, out: Path, ctx) -> None:
        def work(app):
            wb = app.Workbooks.Open(
                Filename=str(src), UpdateLinks=0, ReadOnly=True, Password=DUMMY_PASSWORD,
                WriteResPassword=DUMMY_PASSWORD, IgnoreReadOnlyRecommended=True, Notify=False, AddToMru=False,
            )
            try:
                ctx.progress(0.5)
                if target == "pdf":
                    wb.ExportAsFixedFormat(Type=0, Filename=str(out), Quality=0, IncludeDocProperties=False,
                                           IgnorePrintAreas=False, OpenAfterPublish=False)
                else:
                    wb.SaveAs(Filename=str(out), FileFormat=EXCEL_FORMATS[target], AddToMru=False)
            finally:
                wb.Close(SaveChanges=False)

        self.run(ctx, work, src)


class _PowerPoint(_Instance):
    progid, name, exe = "PowerPoint.Application", "PowerPoint", "powerpnt.exe"

    def configure(self, app) -> None:
        app.DisplayAlerts = 1  # ppAlertsNone
        app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE

    def _open(self, app, src: Path):
        # "file::password::" supplies a password, so protected files error instead of prompting.
        return app.Presentations.Open(FileName=f"{src}::{DUMMY_PASSWORD}::", ReadOnly=True, Untitled=False,
                                      WithWindow=False)

    def convert(self, src: Path, target: str, out: Path, ctx) -> None:
        def work(app):
            pres = self._open(app, src)
            try:
                ctx.progress(0.5)
                pres.SaveAs(str(out), POWERPOINT_FORMATS[target])
            finally:
                pres.Close()

        self.run(ctx, work, src)

    def export_slides(self, src: Path, folder: Path, ctx) -> None:
        def work(app):
            pres = self._open(app, src)
            try:
                slides = pres.Slides
                total = slides.Count
                width = 1920
                height = round(width * pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth)
                for i in range(1, total + 1):
                    slides.Item(i).Export(str(folder / f"{src.stem} - slide {i:03d}.png"), "PNG", width, height)
                    ctx.progress(i / total)
            finally:
                pres.Close()

        self.run(ctx, work, src)


_word, _excel, _powerpoint = _Word(), _Excel(), _PowerPoint()
_word_pdf = _Word()  # separate instance: it must start while the PDF prompt is switched off


def shutdown() -> None:
    for inst in (_word, _word_pdf, _excel, _powerpoint):
        inst.quit()


def convert_document(src: Path, fmt: str, target: str, options: dict, out_dir: Path, ctx) -> Path:
    if target not in WORD_FORMATS:
        raise OfficeError(f"Unknown target: {target}")
    return write_new_file(out_dir, src.stem, target, lambda tmp: _word.convert(src, target, tmp, ctx))


def convert_spreadsheet(src: Path, fmt: str, target: str, options: dict, out_dir: Path, ctx) -> Path:
    if target not in ("pdf", *EXCEL_FORMATS):
        raise OfficeError(f"Unknown target: {target}")
    return write_new_file(out_dir, src.stem, target, lambda tmp: _excel.convert(src, target, tmp, ctx))


def convert_presentation(src: Path, fmt: str, target: str, options: dict, out_dir: Path, ctx) -> Path:
    if target == "png":
        folder = new_output_dir(out_dir, f"{src.stem} (slides)")
        try:
            _powerpoint.export_slides(src, folder, ctx)
        except BaseException:
            _remove_tree(folder)
            raise
        return folder
    if target not in POWERPOINT_FORMATS:
        raise OfficeError(f"Unknown target: {target}")
    return write_new_file(out_dir, src.stem, target, lambda tmp: _powerpoint.convert(src, target, tmp, ctx))


_WORD_OPTIONS_KEY = r"Software\Microsoft\Office\16.0\Word\Options"


@contextlib.contextmanager
def _no_pdf_reflow_prompt():
    """Word asks "convert this PDF?" even when automated, which would hang the job.

    Word reads this setting when it starts, so it is switched off before the dedicated Word
    instance starts and restored right after the conversion.
    """
    name = "DisableConvertPdfWarning"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _WORD_OPTIONS_KEY) as key:
        try:
            previous = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            previous = None
        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)
        try:
            yield
        finally:
            if previous is None:
                winreg.DeleteValue(key, name)
            else:
                winreg.SetValueEx(key, name, 0, previous[1], previous[0])


def pdf_to_docx(src: Path, out_dir: Path, ctx) -> Path:
    """Word can reflow a PDF into an editable document."""
    with _no_pdf_reflow_prompt():
        return write_new_file(out_dir, src.stem, "docx", lambda tmp: _word_pdf.convert(src, "docx", tmp, ctx))


def _remove_tree(folder: Path) -> None:
    import shutil

    shutil.rmtree(folder, ignore_errors=True)
