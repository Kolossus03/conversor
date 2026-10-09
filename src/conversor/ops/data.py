"""Data files: CSV / TSV / JSON / YAML, plus writing Excel. Pure Python, in the worker.

Safety: YAML is read with safe_load (no object construction), and text that looks like a
spreadsheet formula ("=HYPERLINK(...)") is written to Excel as plain text, never as a formula.
"""

import csv
import io
import json
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from ..safepaths import write_new_file

MAX_BYTES = 200 * 1024 * 1024


class DataError(ValueError):
    pass


def _read_text(src: Path) -> str:
    if src.stat().st_size > MAX_BYTES:
        raise DataError("Data files over 200 MB are not supported")
    raw = src.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _load(src: Path, fmt: str):
    text = _read_text(src)
    if fmt in ("csv", "tsv"):
        try:
            dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|") if fmt == "csv" else csv.excel_tab
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(io.StringIO(text), dialect=dialect))
    try:
        if fmt == "json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise DataError(f"This {fmt.upper()} file has a syntax error: {str(exc).splitlines()[0][:150]}") from None


def _table(data) -> tuple[list[str], list[dict]]:
    """Turn data into columns + rows; accepts a list of objects or an object of lists/values."""
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if len(lists) == 1 else [data]
    if not isinstance(data, list) or not data:
        raise DataError("This data isn't a table (expected a list of records)")
    rows = [r if isinstance(r, dict) else {"value": r} for r in data]
    columns: list[str] = []
    for r in rows:
        for k in r:
            if str(k) not in columns:
                columns.append(str(k))
    return columns, [{str(k): v for k, v in r.items()} for r in rows]


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _write_csv(tmp: Path, data, delimiter: str = ",") -> None:
    columns, rows = _table(data)
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel opens UTF-8 correctly
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(columns)
        for r in rows:
            w.writerow([_cell_text(r.get(c)) for c in columns])


def _write_xlsx(tmp: Path, data) -> None:
    columns, rows = _table(data)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Data")

    def cell(value):
        c = WriteOnlyCell(ws, value=value if isinstance(value, (int, float)) and not isinstance(value, bool)
                          else _cell_text(value))
        if isinstance(c.value, str):
            c.data_type = "s"  # never let text become a formula
        return c

    ws.append([cell(c) for c in columns])
    for r in rows:
        ws.append([cell(r.get(c)) for c in columns])
    wb.save(tmp)


def convert(src: Path, fmt: str, target: str, options: dict, out_dir: Path, ctx) -> Path:
    data = _load(src, fmt)
    ctx.progress(0.5)
    writers = {
        "csv": lambda tmp: _write_csv(tmp, data),
        "tsv": lambda tmp: _write_csv(tmp, data, "\t"),
        "xlsx": lambda tmp: _write_xlsx(tmp, data),
        "json": lambda tmp: tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str),
                                           encoding="utf-8"),
        "yaml": lambda tmp: tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                                           encoding="utf-8"),
    }
    if target not in writers:
        raise DataError(f"Unknown target: {target}")
    return write_new_file(out_dir, src.stem, target, writers[target])
