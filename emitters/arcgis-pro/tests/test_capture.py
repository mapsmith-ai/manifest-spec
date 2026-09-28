"""The `start` step of a capture: standard library only, digests what the add-in names."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from provenance_manifest_arcgis_pro import capture  # noqa: E402


def _capture(tmp_path: Path, parameters: list, version: int = 1) -> Path:
    path = tmp_path / "run.capture.json"
    path.write_text(json.dumps({
        "capture_version": version, "tool": "management.GetCount", "run_id": "r1",
        "launch": "python_window", "started_at": "2026-09-27T10:00:00Z",
        "parameters": parameters,
    }), encoding="utf-8")
    return path


def test_start_digests_every_input_dataset_and_only_those(tmp_path):
    data = tmp_path / "a.gpkg"
    data.write_bytes(b"abc")
    path = _capture(tmp_path, [
        {"name": "in_rows", "type": "GPFeatureLayer", "value": "a", "is_input": True,
         "path": str(data)},
        {"name": "row_count", "type": "GPLong", "value": "0", "is_input": False, "path": None},
        {"name": "note", "type": "GPString", "value": "x", "is_input": True, "path": None},
    ])
    result = capture.start(path)
    assert [i["sha256"] for i in result["inputs"]] == [hashlib.sha256(b"abc").hexdigest()]
    assert result["unhashed"] == []
    assert json.loads(path.read_text(encoding="utf-8"))["input_digests_taken_at"].endswith("Z")


def test_an_input_that_cannot_be_read_is_named_not_given_a_digest(tmp_path):
    path = _capture(tmp_path, [
        {"name": "in_rows", "type": "DEFeatureClass", "value": "x", "is_input": True,
         "path": str(tmp_path / "missing.gpkg")},
    ])
    result = capture.start(path)
    assert result["inputs"] == []
    assert result["unhashed"] and result["unhashed"][0].startswith("in_rows=")


def test_start_does_not_import_arcpy(tmp_path):
    # `start` must run as soon as the tool starts, and importing ArcPy costs
    # seconds: the module has to stay importable without it.
    assert "arcpy" not in sys.modules
    capture.start(_capture(tmp_path, []))
    assert "arcpy" not in sys.modules


def test_an_unknown_capture_version_is_refused(tmp_path):
    with pytest.raises(ValueError, match="capture_version"):
        capture.start(_capture(tmp_path, [], version=2))


def test_tool_ids_follow_the_arcpy_naming():
    assert capture._tool_id("analysis.Buffer") == "Buffer_analysis"
    assert capture._tool_id(None) == "unknown_tool"


def test_an_output_that_is_also_an_input_is_an_in_place_edit():
    cap = {"parameters": [
        {"name": "in_table", "is_input": True, "path": r"C:\d\t.gdb\roads"},
        {"name": "out_table", "is_input": False, "path": "C:/d/t.gdb/roads"},
        {"name": "other_out", "is_input": False, "path": "C:/d/t.gdb/new"},
    ]}
    assert capture.writes_to_input(cap) == {"C:/d/t.gdb/roads"}


def test_the_record_an_edit_would_overwrite_is_kept_under_a_dated_name(tmp_path):
    sidecar = tmp_path / "t.gdb.roads.provenance.json"
    sidecar.write_text("{}", encoding="utf-8")
    kept = capture.keep_previous(sidecar, "2026-09-27T17:00:00Z")
    assert kept.name == "t.gdb.roads.20260927T170000Z.provenance.json"
    assert kept.exists() and not sidecar.exists()
    sidecar.write_text("{}", encoding="utf-8")
    again = capture.keep_previous(sidecar, "2026-09-27T17:00:00Z")
    assert again.name == "t.gdb.roads.20260927T170000Z-2.provenance.json"
    assert capture.keep_previous(tmp_path / "absent.provenance.json", "x") is None


def test_a_multi_value_parameter_digests_every_dataset_and_names_what_it_cannot(tmp_path):
    a, b = tmp_path / "a.gpkg", tmp_path / "b.gpkg"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    path = _capture(tmp_path, [
        {"name": "inputs", "type": "GPMultiValue", "value": "a;b;roads_view", "is_input": True,
         "path": None, "paths": [str(a), str(b)], "unresolved": ["roads_view"]},
    ])
    result = capture.start(path)
    assert [i["sha256"] for i in result["inputs"]] == [
        hashlib.sha256(b"a").hexdigest(), hashlib.sha256(b"b").hexdigest()]
    assert result["unhashed"] == ["inputs=roads_view (not resolved to a dataset on disk)"]
    # draft.10: each digest names the parameter it was read through.
    assert [i["argument"] for i in result["inputs"]] == ["inputs", "inputs"]


def test_a_view_only_tool_writes_no_record_and_does_not_need_arcpy(tmp_path):
    # SelectLayerByAttribute reports the layer it was given as its output; read
    # as a writer it would claim an in-place edit of the dataset behind it.
    data = tmp_path / "a.gpkg"
    data.write_bytes(b"abc")
    path = tmp_path / "sel.capture.json"
    path.write_text(json.dumps({
        "capture_version": 1, "tool": "management.SelectLayerByAttribute", "run_id": "r2",
        "launch": "python_window", "started_at": "2026-09-27T10:00:00Z", "succeeded": True,
        "parameters": [
            {"name": "in_layer_or_view", "is_input": True, "value": "a", "path": str(data)},
            {"name": "out_layer_or_view", "is_input": False, "value": "a", "path": str(data)},
        ],
    }), encoding="utf-8")
    assert capture.finish(path) == []
    assert list(tmp_path.glob("*.provenance.json")) == []
    assert "arcpy" not in sys.modules


@pytest.fixture
def fake_arcgis(monkeypatch):
    """The ArcPy-facing helpers `finish` calls, without ArcPy."""
    import types

    fake = types.ModuleType("provenance_manifest_arcgis_pro.arcgis")
    fake._posix = lambda value: str(value).replace("\\", "/")
    fake._has_crs_slot = lambda path: False
    fake._crs = lambda path: None
    fake._count = lambda path: None
    fake._engine = lambda: {"name": "ArcGIS Pro", "version": "test"}
    monkeypatch.setitem(sys.modules, "provenance_manifest_arcgis_pro.arcgis", fake)
    return fake


def test_a_selection_on_the_input_layer_is_a_failed_non_critical_check(tmp_path, fake_arcgis):
    data = tmp_path / "a.gpkg"
    data.write_bytes(b"abc")
    out = tmp_path / "out.gpkg"
    out.write_bytes(b"out")
    path = tmp_path / "buf.capture.json"
    path.write_text(json.dumps({
        "capture_version": 1, "tool": "analysis.Buffer", "run_id": "r3",
        "launch": "python_window", "started_at": "2026-09-27T10:00:00Z", "succeeded": True,
        "error_code": 0, "inputs_hashed": "at_start",
        "parameters": [
            {"name": "in_features", "is_input": True, "value": "roads_view", "dataset": True,
             "path": str(data), "paths": [str(data)], "unresolved": [],
             "layer_filters": [{"layer": "roads_view", "selection_count": 3,
                                "definition_query": None}]},
            {"name": "out_feature_class", "is_input": False, "value": str(out), "dataset": True,
             "path": str(out), "paths": [str(out)]},
        ],
    }), encoding="utf-8")
    capture.start(path)
    [manifest] = capture.finish(path)
    record = json.loads(manifest.read_text(encoding="utf-8"))
    check = next(c for c in record["verification"]
                 if c["name"].endswith(":input_read_whole"))
    assert check["passed"] is False and check["critical"] is False
    assert "roads_view (3 selected)" in check["detail"]
    [kept] = record["x-provenance-manifest-arcgis-pro:layer_filters"]
    assert kept["parameter"] == "in_features" and kept["selection_count"] == 3
    assert record["parameters"]["in_features"] == "roads_view"
    [only] = record["inputs"]
    assert only["argument"] == "in_features"
