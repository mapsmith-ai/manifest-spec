"""End-to-end check on a real ArcGIS Pro. Run with ArcGIS Pro's Python:

    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" live_check.py

Three runs -- an ordinary buffer, a buffer on data with no CRS and a distance
with no unit, and a tool that fails -- and every manifest must pass the
specification's validator. Exits non-zero on any surprise.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "validator"))

import arcpy  # noqa: E402
import validate  # noqa: E402
from provenance_manifest_arcgis_pro.arcgis import run  # noqa: E402

arcpy.env.overwriteOutput = True
work = Path(tempfile.mkdtemp(prefix="gp-prov-live-"))
src = arcpy.management.CreateFileGDB(str(work), "src.gdb")[0]
dst = arcpy.management.CreateFileGDB(str(work), "dst.gdb")[0]


def points(name, sr):
    fc = arcpy.management.CreateFeatureclass(src, name, "POINT", spatial_reference=sr)[0]
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY"]) as cur:
        for i in range(3):
            cur.insertRow(((500000.0 + 100 * i, 5000000.0),))
    return fc


utm = points("wells", arcpy.SpatialReference(32633))
bare = points("wells_nocrs", None)
arcpy.management.ClearWorkspaceCache()

failures = []
summary = {}


def inspect(label, manifests, expect):
    for m in manifests:
        record = json.loads(Path(m).read_text(encoding="utf-8"))
        problems = validate.problems(record)
        checks = {c["name"]: c["passed"] for c in record["verification"]}
        summary[label] = {
            "manifest": Path(m).name,
            "valid": not problems,
            "checks": checks,
            "inputs": [(i["path"].split("/")[-1], i.get("layer")) for i in record["inputs"]],
            "parameters": record["parameters"],
        }
        if problems:
            failures.append(f"{label}: invalid manifest: {problems}")
        for name, passed in expect.items():
            if checks.get(name) is not passed:
                failures.append(f"{label}: expected {name}={passed}, got {checks.get(name)}")


_, ms = run("analysis.Buffer", utm, os.path.join(dst, "wells_100m"), "100 Meters")
inspect(
    "ordinary",
    ms,
    {
        "x-provenance-manifest-arcgis-pro:tool_succeeded": True,
        "input_crs_present": True,
        "crs_present": True,
        "result_not_empty": True,
    },
)

_, ms = run("analysis.Buffer", bare, os.path.join(dst, "wells_10"), "10")
inspect(
    "no_crs_no_unit",
    ms,
    {
        "x-provenance-manifest-arcgis-pro:tool_succeeded": True,
        "input_crs_present": False,
        "x-provenance-manifest-arcgis-pro:linear_unit_declared": False,
    },
)

try:
    run(
        "analysis.Buffer",
        os.path.join(src, "does_not_exist"),
        os.path.join(dst, "never"),
        "5 Meters",
    )
    failures.append("failing: the tool did not raise")
except arcpy.ExecuteError:
    written = list(work.glob("dst.gdb.never.provenance.json"))
    if not written:
        failures.append("failing: no manifest was written for the failed run")
    else:
        inspect(
            "failing",
            written,
            {
                "x-provenance-manifest-arcgis-pro:tool_succeeded": False,
                "x-provenance-manifest-arcgis-pro:inputs_hashed": False,
            },
        )
        if summary["failing"]["inputs"]:
            failures.append("failing: a layer that does not exist was recorded as read")

inside = [p for p in (work / "dst.gdb").iterdir() if p.name.endswith(".json")]
if inside:
    failures.append(f"a manifest was written inside the container: {inside}")

for label, s in summary.items():
    if any("\\" in str(v) for v in s["parameters"].values()):
        failures.append(f"{label}: a parameter path uses the Windows separator")
print(json.dumps(summary, indent=1))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
