"""The QGIS emitter's records pass the specification's validator, without QGIS installed.

The engine-facing code (`qgis.py`) imports `qgis` only inside its functions, so
the parts that decide the record's shape -- the record itself, and how a QGIS
source string becomes a path and a layer -- are tested here with no engine.
The end-to-end check against a real QGIS is `live_check.py`, run by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "validator"))

# Imported, not importorskip: if the validator moved, these tests must fail.
import validate  # noqa: E402
from provenance_manifest_qgis import record as rec  # noqa: E402
from provenance_manifest_qgis.digest import DatasetDigest  # noqa: E402
from provenance_manifest_qgis.qgis import split_layer  # noqa: E402


def _record(**over):
    args = dict(
        operation="native:buffer",
        parameters={"INPUT": "C:/d/wells.gpkg|layername=wells", "DISTANCE": 500, "SEGMENTS": 5},
        inputs=[DatasetDigest("C:/d/wells.gpkg", "a" * 64, "file", "wells")],
        input_arguments=["INPUT"],
        output=DatasetDigest("C:/d/buf.gpkg", "b" * 64, "file"),
        output_crs="EPSG:32633",
        engine={
            "name": "QGIS",
            "version": "3.44.12-Solothurn",
            "x-provenance-manifest-qgis:gdal": "3.13.1",
        },
        checks=[
            rec.check("x-provenance-manifest-qgis:algorithm_succeeded", True, "returned OUTPUT"),
            rec.check("crs_present", True, "output declares EPSG:32633"),
        ],
        started_at="2026-10-02T10:00:00Z",
        finished_at="2026-10-02T10:00:01Z",
        environment={"ellipsoid": "NONE", "distance_unit": "meters", "area_unit": "square meters"},
        messages=[{"severity": "info", "text": "Results: {'OUTPUT': ...}"}],
    )
    args.update(over)
    return rec.build(**args)


def test_a_full_record_is_valid():
    assert validate.problems(_record()) == []


def test_the_producer_is_this_emitter_and_its_prefix_matches():
    record = _record()
    assert record["producer"]["name"] == "provenance-manifest-qgis"
    assert "x-" + record["producer"]["name"] == rec.PREFIX


def test_a_failed_run_with_no_output_is_still_a_valid_record():
    record = _record(
        output=None,
        output_crs=None,
        checks=[rec.check("x-provenance-manifest-qgis:algorithm_succeeded", False, "raised")],
    )
    assert validate.problems(record) == []


def test_a_degrees_distance_is_a_failed_check_and_the_record_stays_valid():
    record = _record(
        checks=[
            rec.check("x-provenance-manifest-qgis:algorithm_succeeded", True, "returned OUTPUT"),
            rec.check(
                "x-provenance-manifest-qgis:distance_not_in_degrees",
                False,
                "DISTANCE=500 was applied to INPUT, which is in EPSG:4326",
            ),
        ]
    )
    assert validate.problems(record) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("C:/d/a.gpkg|layername=roads", ("C:/d/a.gpkg", "roads")),
        ("C:/d/a.gpkg|layerid=0|layername=roads|subset=x>1", ("C:/d/a.gpkg", "roads")),
        ("C:/d/a.gpkg|layerid=0", ("C:/d/a.gpkg", None)),
        ("C:/d/roads.shp", ("C:/d/roads.shp", None)),
    ],
)
def test_a_qgis_source_string_splits_into_the_file_and_the_layer(source, expected):
    assert split_layer(source) == expected


def test_a_geopackage_layer_record_sits_beside_the_file():
    d = DatasetDigest("C:/d/out.gpkg", "b" * 64, "file", "buf")
    assert rec.sidecar_path(d) == Path("C:/d/out.gpkg.buf.provenance.json")
