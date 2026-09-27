# Provenance manifest emitter for ArcGIS Pro

A reference emitter: it runs an ArcGIS Pro geoprocessing tool through ArcPy and writes a
manifest conforming to this specification beside each output. It imports nothing from any other
producer, and what it writes passes the same validator as every other record.

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

## What goes in the record

- **Inputs, hashed before the tool runs**, so the digest describes what was read, not what was on
  disk afterwards. **Outputs, hashed after.**
- **The parameters the tool ran with**, not the ones passed: `Result.getInput` returns the
  defaults filled in (`method: PLANAR`, `dissolve_option: NONE`), which is what section 3.2 asks
  for. Paths are written with `/`.
- `engine`: ArcGIS Pro, its version and build, and the licence level.
- `environment` (section 3.8): the geoprocessing environments in effect.
- The tool's messages.
- Checks. From the core vocabulary: `input_crs_present`, `inputs_share_crs`, `crs_present`,
  `result_not_empty`. Extensions: `x-provenance-manifest-arcgis-pro:tool_succeeded`,
  `...:inputs_hashed` (an input that is not a dataset on disk, or does not exist, is named instead
  of being given a digest), and `...:linear_unit_declared` — ArcGIS accepts a distance with no
  unit and runs it as `'10 Unknown'`, in the units of the data, which is a number whose meaning the
  call never stated.

A tool that fails still gets a manifest, and the error is raised afterwards: the audit trail has
to survive the error it documents.

ArcGIS Pro already keeps a geoprocessing history — tool, parameters, times, messages. What this
adds is what that history does not hold: the digest of the bytes read and written, and the checks,
in a format a consumer can read without ArcGIS.

## Two things this emitter decides that the specification does not yet

**The digest of a dataset made of several files.** Section 3.3 says `sha256` is of the bytes,
which is undefined for a file geodatabase (a directory: sixty files for one layer) or a shapefile
(`.shp` + `.dbf` + `.prj` + …). Here both are digested as the SHA-256 of a sorted listing, one
line per member file, `<relative-path>\0<sha256>\n`, with `/` as the separator, and the entry says
so in `x-provenance-manifest-arcgis-pro:digest_rule`. Lock files (`*.lock`) are excluded and never
opened: a file geodatabase creates them only while it is open, they cannot be read while they
exist, and their names carry the host name and a process id. Measured on ArcGIS Pro 3.7.1: reading
a geodatabase, with a cursor or as a tool input, changes none of its other bytes. A layer is named
in `inputs[].layer`.

**Where the record of a layer inside a container goes.** Not inside the container, which would
change the container's digest: beside it, as `<container>.<layer>.provenance.json`
(`out.gdb.wells_500m.provenance.json`).

Both are proposals for a future draft, not rules of this one.

## Tests

`pytest emitters/arcgis-pro/tests` runs without ArcGIS: the digest rules, with answers computed
from `hashlib`, and the record shape against the validator. The end-to-end check needs ArcGIS Pro
and is run by hand with its Python — three runs (an ordinary buffer, a buffer on data with no CRS
and a distance with no unit, a tool that fails), every manifest validated:

```
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" emitters\arcgis-pro\live_check.py
```

Licence: Apache-2.0, like the rest of the code in this repository.
