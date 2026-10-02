"""End-to-end check on a real QGIS. Run with QGIS's Python, standalone:

    "C:\\Program Files\\QGIS 3.44.12\\bin\\python-qgis-ltr.bat" live_check.py

Four runs -- an ordinary buffer, a buffer whose distance is in degrees, an
algorithm that fails, and an area computed with and without an ellipsoid --
and every manifest must pass the specification's validator. Exits non-zero on
any surprise.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "validator"))

from qgis.core import (  # noqa: E402
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingContext,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

app = QgsApplication([], False)
app.initQgis()
# Processing is a core plugin, outside sys.path for a standalone script.
sys.path.insert(0, str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins"))

from processing.core.Processing import Processing  # noqa: E402
from qgis.analysis import QgsNativeAlgorithms  # noqa: E402

Processing.initialize()
if QgsApplication.processingRegistry().providerById("native") is None:
    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

import validate  # noqa: E402
from provenance_manifest_qgis.qgis import run  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="qgis-prov-live-"))
failures: list[str] = []
summary: dict = {}


def layer(name: str, crs: str, geometries: list[QgsGeometry], kind: str) -> str:
    memory = QgsVectorLayer(f"{kind}?crs={crs}", name, "memory")
    features = []
    for g in geometries:
        f = QgsFeature()
        f.setGeometry(g)
        features.append(f)
    memory.dataProvider().addFeatures(features)
    path = str(work / f"{name}.gpkg")
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerName = name
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory, path, QgsProcessingContext().transformContext(), options
    )
    if error[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"could not write {path}: {error}")
    return f"{path}|layername={name}"


def inspect(label: str, manifests: list[Path], expect: dict[str, bool]) -> dict:
    if not manifests:
        failures.append(f"{label}: no manifest written")
        return {}
    record = json.loads(Path(manifests[0]).read_text(encoding="utf-8"))
    problems = validate.problems(record)
    checks = {c["name"].split(":")[-1]: c["passed"] for c in record["verification"]}
    summary[label] = {
        "manifest": Path(manifests[0]).name,
        "valid": not problems,
        "checks": checks,
        "inputs": [
            (Path(i["path"]).name, i.get("layer"), i.get("argument")) for i in record["inputs"]
        ],
        "environment": record.get("environment"),
    }
    if problems:
        failures.append(f"{label}: invalid manifest: {problems}")
    for name, passed in expect.items():
        if checks.get(name) is not passed:
            failures.append(f"{label}: expected {name}={passed}, got {checks.get(name)}")
    return record


utm = layer(
    "wells",
    "EPSG:32633",
    [QgsGeometry.fromPointXY(QgsPointXY(500000 + 100 * i, 5000000)) for i in range(3)],
    "Point",
)
wgs = layer(
    "wells_wgs",
    "EPSG:4326",
    [QgsGeometry.fromPointXY(QgsPointXY(9.0 + 0.01 * i, 45.0)) for i in range(3)],
    "Point",
)
square = QgsGeometry.fromRect(QgsRectangle(9.0, 45.0, 9.0038, 45.0027))
field = layer("field", "EPSG:4326", [square], "Polygon")

# 1. An ordinary buffer: every check passes.
_, m = run("native:buffer", {"INPUT": utm, "DISTANCE": 500, "OUTPUT": str(work / "buf.gpkg")})
record = inspect(
    "buffer",
    m,
    {
        "algorithm_succeeded": True,
        "input_crs_present": True,
        "crs_present": True,
        "result_not_empty": True,
    },
)
if record and record["parameters"].get("SEGMENTS") != 5:
    failures.append(f"buffer: the default SEGMENTS was not recorded: {record['parameters']}")
if record and not any(
    i.get("argument") == "INPUT" and i.get("layer") == "wells" for i in record["inputs"]
):
    failures.append(f"buffer: the input lost its argument or its layer: {record['inputs']}")

# 2. The same distance on a layer in degrees: QGIS runs it silently, the record says so.
_, m = run("native:buffer", {"INPUT": wgs, "DISTANCE": 500, "OUTPUT": str(work / "buf_deg.gpkg")})
inspect("buffer in degrees", m, {"algorithm_succeeded": True, "distance_not_in_degrees": False})

# 3. A run that fails still leaves a record, and the error is raised afterwards.
try:
    run(
        "native:buffer",
        {"INPUT": str(work / "missing.gpkg"), "DISTANCE": 1, "OUTPUT": str(work / "never.gpkg")},
    )
    failures.append("failing run: no exception was raised")
except Exception:
    pass
never = work / "never.gpkg.provenance.json"
if never.exists():
    inspect("failing run", [never], {"algorithm_succeeded": False, "inputs_hashed": False})
else:
    failures.append("failing run: no record beside the output that was never written")

# 4. $area with and without an ellipsoid: the numbers differ, and the environment says why.
areas = {}
for label, ellipsoid in (("area, no ellipsoid", None), ("area, WGS 84", "EPSG:7030")):
    context = QgsProcessingContext()
    # Square metres asked for in both runs, as `qgis_process --AREA_UNITS=m2` does;
    # only the ellipsoid differs.
    context.setAreaUnit(Qgis.AreaUnit.SquareMeters)
    if ellipsoid:
        context.setEllipsoid(ellipsoid)
    out = str(work / f"area_{'ell' if ellipsoid else 'none'}.gpkg")
    _, m = run(
        "native:fieldcalculator",
        {"INPUT": field, "FIELD_NAME": "a", "FIELD_TYPE": 0, "FORMULA": "$area", "OUTPUT": out},
        context=context,
    )
    inspect(label, m, {"algorithm_succeeded": True})
    areas[label] = next(QgsVectorLayer(out, "", "ogr").getFeatures())["a"]
summary["areas"] = areas
envs = {
    summary[k]["environment"]["ellipsoid"]
    for k in ("area, no ellipsoid", "area, WGS 84")
    if k in summary
}
if len(envs) != 2:
    failures.append(f"area: the two runs recorded the same ellipsoid: {envs}")
# 9.0-9.0038 E, 45.0-45.0027 N: 89900.02 m2 geodesic on WGS 84 (pyproj), and
# 127142.22 m2 with no ellipsoid, the equatorial factor (QGIS issue S2, D-103).
expected = {"area, no ellipsoid": 127142.22, "area, WGS 84": 89900.02}
for label, value in expected.items():
    if abs(float(areas.get(label, 0)) - value) > 0.05:
        failures.append(f"{label}: {areas.get(label)} m2, expected {value}")

print(json.dumps(summary, indent=1, default=str))
print("QGIS", Qgis.version())
if failures:
    print("FAILURES:\n  " + "\n  ".join(failures))
    sys.exit(1)
print("all four runs recorded and valid")
