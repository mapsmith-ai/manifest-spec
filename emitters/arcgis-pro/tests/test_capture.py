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
