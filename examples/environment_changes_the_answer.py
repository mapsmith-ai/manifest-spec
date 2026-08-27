"""The demonstration behind section 3.8: the same file, the same call, two answers.

Run it. It needs `rasterio` and nothing else, it touches no network, and it
prints two different areas for one raster.

    python examples/environment_changes_the_answer.py

Why this exists. A specification that asks producers to record their environment
has to show that the environment changes the answer, or it is asking for a field
on faith. This is the shortest case we could find that is reproducible on any
machine, offline, in one file.

WHAT IT DOES. It writes a 2x2 GeoTIFF whose own georeferencing puts it at
(500000, 5030000) with 10 m pixels — 400 m2 of ground — and beside it a
`.aux.xml` sidecar claiming (600000, 5040000) with 20 m pixels. Then it opens the
raster three times, changing nothing but the process environment.

WHAT IT PRINTS, measured on GDAL 3.x / rasterio 1.5:

    default                      1600.0 m2   at 600000, 5039960
    GDAL_PAM_ENABLED=NO           400.0 m2   at 500000, 5029980
    GDAL_GEOREF_SOURCES=INTERNAL  400.0 m2   at 500000, 5029980

A factor of four in area and a hundred kilometres in position, from one file and
one line of code. Nothing in the output of any of the three runs says which
georeferencing was used.

WHY IT IS NOT A BUG. GDAL's documented default precedence puts the PAM sidecar
ahead of the file's own georeferencing, on purpose: a sidecar is how a user
overrides georeferencing they know to be wrong. Both answers are the library
behaving as documented. That is exactly what makes it worth a field in a manifest
rather than an issue in a tracker — there is nothing to fix, and everything to
record.

WHY SIDECARS DIVERGE IN PRACTICE, so this does not read as a contrived case:
`.aux.xml` files are written by GDAL itself for statistics and overviews, they
are copied along with rasters by ordinary file operations, and they are left
behind when a raster is rewritten in place. A stale one is not exotic; it is the
normal end state of a dataset that has been through more than one tool.

WHAT A CONFORMING RECORD WOULD SAY. `environment` is where the answer stops
depending on something invisible:

    "environment": {
      "GDAL_PAM_ENABLED": "(unset)",
      "GDAL_GEOREF_SOURCES": "(unset)",
      "georeferencing_source": "PAM sidecar (scene.tif.aux.xml)"
    }

With that line the two runs above are still different, and they are no longer
indistinguishable. The correct answer is not a number; it is this number with
this configuration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

READER = '''
import json, sys, warnings
warnings.filterwarnings("ignore")
import rasterio

with rasterio.open(sys.argv[1]) as src:
    left, bottom, right, top = src.bounds
    print(json.dumps({
        "area_m2": round((right - left) * (top - bottom), 1),
        "origin": [round(left, 1), round(bottom, 1)],
        "pixel_m": list(src.res),
    }))
'''


def build(workdir: Path) -> Path:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    raster = workdir / "scene.tif"
    with rasterio.open(
        raster, "w", driver="GTiff", width=2, height=2, count=1, dtype="int32",
        crs="EPSG:32632", transform=from_origin(500_000, 5_030_000, 10, 10),
    ) as dst:
        dst.write(np.array([[1, 2], [3, 4]], dtype="int32"), 1)

    # The sidecar, disagreeing with the file it sits beside. Written by hand
    # here; in the field it is written by a tool and outlives the raster it
    # described.
    (workdir / "scene.tif.aux.xml").write_text(
        "<PAMDataset>\n"
        "  <SRS>EPSG:32632</SRS>\n"
        "  <GeoTransform>600000.0, 20.0, 0.0, 5040000.0, 0.0, -20.0</GeoTransform>\n"
        "</PAMDataset>\n",
        encoding="utf-8",
    )
    return raster


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="environment-demo-") as tmp:
        workdir = Path(tmp)
        raster = build(workdir)
        reader = workdir / "read.py"
        reader.write_text(READER, encoding="utf-8")

        answers = {}
        for label, extra in (
            ("default", {}),
            ("GDAL_PAM_ENABLED=NO", {"GDAL_PAM_ENABLED": "NO"}),
            ("GDAL_GEOREF_SOURCES=INTERNAL", {"GDAL_GEOREF_SOURCES": "INTERNAL"}),
        ):
            done = subprocess.run(
                [sys.executable, str(reader), str(raster)],
                capture_output=True, text=True, env={**os.environ, **extra}, check=True,
            )
            read = json.loads(done.stdout)
            answers[label] = read
            print(
                f"{label:30} {read['area_m2']:>8} m2   at {read['origin'][0]:.0f}, "
                f"{read['origin'][1]:.0f}   pixels {read['pixel_m'][0]:.0f} m"
            )

        distinct = {a["area_m2"] for a in answers.values()}
        print()
        if len(distinct) == 1:
            print(
                "This build of GDAL gave one answer in all three environments, so the "
                "demonstration did not reproduce here. That is worth reporting: the "
                "section it supports assumes the precedence documented for GDAL 3.x."
            )
            return 1
        print(
            f"One file, one line of code, {len(distinct)} different answers: "
            f"{sorted(distinct)} m2.\n"
            "None of the three runs said which georeferencing it used. That is the field."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
