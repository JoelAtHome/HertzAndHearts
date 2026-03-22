import json

from hnh import ble_diagnostics as bd


def test_append_ble_diagnostic_writes_json_line(monkeypatch, tmp_path):
    monkeypatch.setattr(bd, "app_data_root", lambda: tmp_path)
    p = bd.append_ble_diagnostic("c", "e", message="m", qt_code=3)
    assert p == tmp_path / bd.LOG_FILENAME
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["component"] == "c"
    assert row["event"] == "e"
    assert row["message"] == "m"
    assert row["qt_code"] == 3
    assert "ts" in row
