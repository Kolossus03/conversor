import json

import pytest
from openpyxl import load_workbook

from conversor.formats import detect
from conversor.ops import data, ocr


class Ctx:
    def progress(self, _):
        pass


def test_csv_to_xlsx_keeps_formulas_as_text(tmp_path):
    src = tmp_path / "people.csv"
    src.write_text('name;note\nAna;=HYPERLINK("http://x","y")\n', encoding="utf-8")
    assert detect(src).kind == "data"
    out = data.convert(src, "csv", "xlsx", {}, tmp_path, Ctx())
    cell = load_workbook(out).active["B2"]
    assert cell.data_type == "s" and cell.value.startswith("=HYPERLINK")


def test_json_round_trip(tmp_path):
    src = tmp_path / "items.json"
    src.write_text(json.dumps({"items": [{"id": 1, "tags": ["a"]}, {"id": 2, "extra": True}]}))
    csv_out = data.convert(src, "json", "csv", {}, tmp_path, Ctx())
    lines = csv_out.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "id,tags,extra" and lines[2] == "2,,True"
    yaml_out = data.convert(src, "json", "yaml", {}, tmp_path, Ctx())
    assert "items:" in yaml_out.read_text(encoding="utf-8")


def test_yaml_cannot_run_code(tmp_path):
    src = tmp_path / "evil.yaml"
    src.write_text('!!python/object/apply:os.system ["echo pwned"]\n')
    with pytest.raises(data.DataError):
        data.convert(src, "yaml", "json", {}, tmp_path, Ctx())


def test_non_table_json_to_csv_is_explained(tmp_path):
    src = tmp_path / "scalar.json"
    src.write_text("42")
    with pytest.raises(data.DataError, match="isn't a table"):
        data.convert(src, "json", "csv", {}, tmp_path, Ctx())


def test_shapely_stand_in_matches_geometry():
    ocr._install_shapely_stand_in()
    from shapely.geometry import Polygon

    square = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    assert square.area == 4 and square.length == 8
