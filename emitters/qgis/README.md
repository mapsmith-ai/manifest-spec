# Provenance manifest emitter for QGIS

A reference emitter: it runs a QGIS Processing algorithm and writes a manifest conforming to
[the specification in this repository](../../spec/manifest-v1.md) beside each output. It imports
nothing from any other producer, and what it writes passes the same
[validator](../../validator/validate.py) as every other record.

*Not affiliated with, sponsored or endorsed by QGIS.ORG or the QGIS project. QGIS is a
trademark of QGIS.ORG.*

**Status: a first step.** Runs started from code, through `run`, are recorded; runs from the
Processing Toolbox, the model designer and the history are not yet. Tested end to end on QGIS
3.44.12 and 4.2.3 (`live_check.py`). Not on PyPI or on the QGIS plugin repository yet.

## Use

In QGIS's Python (the console, a script, or a standalone script with `qgis.core` initialised),
with this folder on `sys.path`:

```python
from provenance_manifest_qgis.qgis import run

results, manifests = run("native:buffer", {
    "INPUT": "C:/data/wells.gpkg|layername=wells",
    "DISTANCE": 500,
    "OUTPUT": "C:/data/wells_500m.gpkg",
})
```

`run` takes what `processing.run` takes (an optional `context` and `feedback` too) and returns
its results with the paths of the manifests it wrote.

**Why a wrapper first, and not a hook.** A wrapper sees every run made through it on every QGIS
version. The pre- and post-execution scripts in the Processing settings are not a way in:
measured on QGIS 3.44.12 and 4.2.3, neither runs, whether the algorithm is started with
`processing.run` or through the executor the Processing dialog uses; the settings are saved and
read back, and no code in either version reads them. So recording the runs started from the
Toolbox needs its own design: that is the next step, not a setting.

## What goes in the record

- **Inputs, hashed before the algorithm runs**, by the rule of
  [section 3.3](../../spec/manifest-v1.md#33-field-semantics-that-are-easy-to-get-wrong): a
  shapefile by its member files, a file geodatabase by its listing. A GeoPackage layer passed as
  `path|layername=wells` is recorded as the file with `layer: wells`. Each input names the
  parameter it was read through (`inputs[].argument`, since `draft.10`).
- **The parameters the algorithm ran with**: the ones passed, plus the default of every one left
  out, because [section 3.2](../../spec/manifest-v1.md#32-mandatory-fields) asks for what ran.
- `engine`: QGIS and its version, and the versions of GDAL, PROJ and GEOS, which change answers
  on their own: since GDAL 3.11, `gdaldem slope` derives the scale of a geographic raster itself.
- `environment` ([section 3.8](../../spec/manifest-v1.md#38-environment-the-configuration-that-changed-the-answer)):
  the ellipsoid and the distance and area units of the processing context. With no ellipsoid,
  `$area` on a layer in degrees converts with an equatorial factor: the end-to-end check measures
  127142.22 m² where the ground area is 89900.02 m², and the two records differ only there.
- The algorithm's messages.
- Checks. From the [core vocabulary](../../spec/manifest-v1.md#36-check-names-a-closed-core-and-prefixed-extensions):
  `input_crs_present`, `inputs_share_crs`, `crs_present`, `result_not_empty`. Extensions:
  `x-provenance-manifest-qgis:algorithm_succeeded`, `...:inputs_hashed` (an input that is not a
  dataset on disk is named instead of given a digest), and `...:distance_not_in_degrees`: a
  distance applied to a layer in a geographic CRS is a number of degrees. The Processing dialog
  warns about it; run from code, QGIS does not, and the record does.

A run that fails still gets a record, and the error is raised afterwards: the audit trail has to
survive the error it documents. An output written to a memory layer (`TEMPORARY_OUTPUT`) has no
file to put a record beside, so it gets none.

Paths are recorded as given, as section 3.3 requires. A dataset under your user folder puts your
user name in the record.

`digest.py` and `record.py` are copies of the ArcGIS Pro emitter's, so that each emitter installs
alone into its engine's Python; [`tests/test_multi_file_digest.py`](../../tests/test_multi_file_digest.py)
holds both copies to the specification's reference function, so one that drifted would fail there.

## Tests

`pytest emitters/qgis/tests` runs without QGIS: the record shape against the validator, and how
a QGIS source string becomes a path and a layer. The end-to-end check needs QGIS and is run by
hand with its Python — four runs (an ordinary buffer, a buffer whose distance is in degrees, an
algorithm that fails, an area with and without an ellipsoid), every manifest validated:

```
"C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" emitters\qgis\live_check.py
"C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat" emitters\qgis\live_check.py
```

## Licence

Apache-2.0, like the rest of the code in this repository ([`LICENSE-CODE`](../../LICENSE-CODE)).
The QGIS plugin repository asks for a licence compatible with GPLv2 or later; Apache-2.0 is,
through GPLv3.
