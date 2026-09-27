"""Every record this producer builds passes the specification's own validator."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "validator"))

from provenance_manifest_arcgis_pro import record as rec  # noqa: E402
from provenance_manifest_arcgis_pro.digest import DatasetDigest  # noqa: E402

validate = pytest.importorskip("validate")


def _record(**over):
    args = dict(
        operation="Buffer_analysis",
        parameters={"in_features": "C:/d/t.gdb/pts", "buffer_distance_or_field": "10 Meters"},
        inputs=[DatasetDigest("C:/d/t.gdb", "a" * 64, "container", "pts", 60)],
        output=DatasetDigest("C:/d/o.gdb", "b" * 64, "container", "buf", 12),
        output_crs="EPSG:32633",
        engine={
            "name": "ArcGIS Pro",
            "version": "3.7.1",
            "x-provenance-manifest-arcgis-pro:build": "1901",
        },
        checks=[rec.check("crs_present", True, "output declares EPSG:32633")],
        started_at="2026-09-27T10:00:00Z",
        finished_at="2026-09-27T10:00:02Z",
        environment={"outputCoordinateSystem": "None"},
        messages=[{"severity": "info", "text": "Succeeded"}],
    )
    args.update(over)
    return rec.build(**args)


def _errors(record):
    return validate.problems(record)


def test_a_full_record_is_valid():
    assert _errors(_record()) == []


def test_a_failed_tool_with_no_output_is_still_a_valid_record():
    r = _record(
        output=None,
        output_crs=None,
        checks=[
            rec.check("x-provenance-manifest-arcgis-pro:tool_succeeded", False, "ExecuteError: ...")
        ],
    )
    assert _errors(r) == []


SPEC_TOP_LEVEL = {
    "spec_version",
    "operation",
    "parameters",
    "inputs",
    "engine",
    "verification",
    "started_at",
    "finished_at",
    "producer",
    "output",
    "environment",
    "crs_decisions",
    "repairs",
    "notes",
}


def _keys(obj, where=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield where, k
            yield from _keys(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for item in obj:
            yield from _keys(item, where + "[]")


def test_every_key_of_ours_carries_the_prefix():
    # Spec 3.5 permits unknown top-level fields and only RECOMMENDS a prefix;
    # the validator enforces it inside crs_decisions, repairs and
    # transformations. This producer holds itself to the stricter rule.
    r = _record()
    ours = [k for k in r if k not in SPEC_TOP_LEVEL]
    assert ours and all(k.startswith(rec.PREFIX + ":") for k in ours), ours
    for where, key in _keys(r["inputs"] + [r["output"], r["engine"]]):
        if key not in {"path", "sha256", "layer", "crs", "name", "version"}:
            assert key.startswith(rec.PREFIX + ":"), (where, key)


def test_the_sidecar_of_a_container_layer_sits_beside_the_container():
    d = DatasetDigest("C:/d/o.gdb", "b" * 64, "container", "transport/buf", 3)
    assert rec.sidecar_path(d) == Path("C:/d/o.gdb.transport.buf.provenance.json")


def test_a_record_without_checks_is_refused():
    with pytest.raises(ValueError):
        _record(checks=[])
