# Provenance manifest emitter for ArcGIS Pro

A reference emitter: it runs an ArcGIS Pro geoprocessing tool through ArcPy and writes a
manifest conforming to [the specification in this repository](../../spec/manifest-v1.md) beside
each output. It imports nothing from any other producer, and what it writes passes the same
[validator](../../validator/validate.py) as every other record.

*Not affiliated with, sponsored or endorsed by Esri. ArcGIS, ArcGIS Pro and ArcPy are trademarks
of Esri.*

**Status: early.** Tested end to end on ArcGIS Pro 3.7.1 (`live_check.py`). Not on PyPI yet.

## Use

Inside ArcGIS Pro's Python environment, with this folder on `sys.path`:

```python
from provenance_manifest_arcgis_pro.arcgis import run

result, manifests = run(
    "analysis.Buffer",
    r"C:\data\in.gdb\wells",
    r"C:\data\out.gdb\wells_500m",
    "500 Meters",
)
```

`run` takes the tool as `"<toolbox alias>.<Tool>"` and the tool's own arguments, positional or by
name. It returns the ArcPy `Result` and the paths of the manifests it wrote.

**For tools run interactively** — from the Geoprocessing pane or the Python window — the
[add-in](addin/README.md) records them as they run, through the same package
(`provenance_manifest_arcgis_pro.capture`). It is source only, does nothing until you enable it,
and its README lists what it does not record yet.

## What goes in the record

- **Inputs, hashed before the tool runs**, so the digest describes what was read, not what was on
  disk afterwards. **Outputs, hashed after.**
- **The parameters the tool ran with**, not the ones passed: `Result.getInput` returns the
  defaults filled in (`method: PLANAR`, `dissolve_option: NONE`), which is what
  [section 3.2](../../spec/manifest-v1.md#32-mandatory-fields) asks for. Paths are written with `/`.
- `engine`: ArcGIS Pro, its version and build, and the licence level.
- `environment` ([section 3.8](../../spec/manifest-v1.md#38-environment-the-configuration-that-changed-the-answer)):
  the geoprocessing environments in effect.
- The tool's messages.
- Checks. From the [core vocabulary](../../spec/manifest-v1.md#36-check-names-a-closed-core-and-prefixed-extensions): `input_crs_present`, `inputs_share_crs`, `crs_present`,
  `result_not_empty`. Extensions: `x-provenance-manifest-arcgis-pro:tool_succeeded`,
  `...:inputs_hashed` (an input that is not a dataset on disk, or does not exist, is named instead
  of being given a digest), and `...:linear_unit_declared` — ArcGIS accepts a distance with no
  unit and runs it as `'10 Unknown'`, in the units of the data, which is a number whose meaning the
  call never stated.

A tool that fails still gets a manifest, and the error is raised afterwards: the audit trail has
to survive the error it documents. That holds for any exception the call raises, not only a
geoprocessing error.

Paths are recorded as given, as section 3.3 requires. A dataset under your user folder puts your
user name in the record: keep shared data somewhere that does not, or know that it travels with
the manifest.

ArcGIS Pro already keeps a geoprocessing history — tool, parameters, times, messages. What this
adds is what that history does not hold: the digest of the bytes read and written, and the checks,
in a format a consumer can read without ArcGIS.

## Datasets made of several files, and layers inside a container

A file geodatabase is a directory of dozens of files, even for one layer, and a shapefile is a set
of sibling files. Since `draft.9`,
[section 3.3](../../spec/manifest-v1.md#33-field-semantics-that-are-easy-to-get-wrong) digests
both as the listing of their member files, and
[section 3.1](../../spec/manifest-v1.md#31-placement-and-naming) puts the record of a layer beside
its container, as `<container>.<layer>.provenance.json` (`out.gdb.wells_500m.provenance.json`) --
inside, it would change the container's digest. This emitter implements both, and a test in the
suite checks that its digests equal the reference function's
([`examples/multi_file_digest.py`](../../examples/multi_file_digest.py)).

Both rules came from building this emitter. Measured on ArcGIS Pro 3.7.1: reading a geodatabase,
with a cursor or as a tool input, changes none of its other bytes; the lock files it creates while open
cannot be read and carry the host name in theirs, which is why the rule excludes them.

## Tests

`pytest emitters/arcgis-pro/tests` runs without ArcGIS: the digest rules, with answers computed
from `hashlib`, and the record shape against the validator. The end-to-end check needs ArcGIS Pro
and is run by hand with its Python — three runs (an ordinary buffer, a buffer on data with no CRS
and a distance with no unit, a tool that fails), every manifest validated:

```
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" emitters\arcgis-pro\live_check.py
```

Licence: Apache-2.0, like the rest of the code in this repository.
