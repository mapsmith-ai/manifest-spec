# Provenance Manifest add-in for ArcGIS Pro

An ArcGIS Pro add-in that writes a provenance manifest beside every dataset a geoprocessing tool
writes — for tools run from the Geoprocessing pane, the Python window, or another add-in. It is
the interactive side of the [reference emitter](../README.md): the add-in sees each tool start
and finish, and the digests and the record come from the emitter's Python package, embedded in
the add-in, so the digest rule of [section 3.3](../../../spec/manifest-v1.md#33-field-semantics-that-are-easy-to-get-wrong)
has one implementation.

*Not affiliated with, sponsored or endorsed by Esri. ArcGIS, ArcGIS Pro and ArcPy are trademarks
of Esri.*

**Status: early.** Tested end to end on ArcGIS Pro 3.7.1 and 3.7.2 by its autotest (below).
Source only: build it with your own ArcGIS Pro.

## It does nothing until you ask

Installed, the add-in is **inert**. Writing a file beside every output of every session is not
something an add-in should start doing because it was installed. It records only when ArcGIS Pro
was started with `/provenance-manifest`, or when the file
`%LOCALAPPDATA%\ProvenanceManifest\enabled` exists (create it to opt in, delete it to stop).

## Build and install

Requires ArcGIS Pro 3.7 and the .NET 10 SDK. From this folder:

```
dotnet build -c Release
```

This builds against the ArcGIS Pro installed on the machine and produces
`bin\Release\net10.0-windows\ProvenanceManifest.esriAddinX`. The build tries to register it; check
that `Documents\ArcGIS\AddIns\ArcGISPro\{e112c006-a107-43ff-9015-4c2ee5397807}` exists, and if not,
double-click the `.esriAddinX` (the build ignores the registration's exit code).

## What it records, and what it cannot

For each run: the tool, the parameters it ran with, the input digests, each output's digest, CRS
and row count, the environments set for that run, the tool's messages, and checks — in a manifest
beside the output (for a layer in a file geodatabase, beside the geodatabase, §3.1). Working files
and a log are in `%LOCALAPPDATA%\ProvenanceManifest`.

Measured on ArcGIS Pro 3.7, and stated in the record rather than hidden:

- **Input digests are taken at tool start, concurrently with the tool.** The event the add-in
  listens to does not block the tool. Exact for a tool that only reads its inputs.
- **A tool that edits its input in place** (Calculate Field, Add Field, Append) is recorded with
  `writes_to_input: true`: its input digest may already describe the edited state. The record it
  would overwrite — the one of the operation that created the dataset — is kept beside it under a
  dated name, `<name>.<timestamp>.provenance.json`, and named in the new record.
- **A run with no parameters at its start** (a tool run from code without adding to the project
  history) has its inputs hashed after the run, and the record says so.
- **A layer name** (the Python window passes names, not paths) is resolved to the dataset behind the
  layer before hashing.
- **Not covered yet: models run from ModelBuilder.** No geoprocessing event fires for them. A model
  run as a tool from code raises one event for the model and none for the tools inside it.

## Autotest

`run_autotest.ps1 -PristineProject <folder>` copies any ArcGIS Pro project folder with a map (it is
never modified), starts Pro on the copy with `/provenance-manifest-autotest`, lets the add-in run
a fixed sequence (create a fishnet, buffer it by path and by layer name, copy without history,
then add and calculate a field in place), waits for Pro to exit, and checks every manifest with
this repository's validator (`check_manifests.py`). No clicks; about a minute.

Licence: Apache-2.0, like the rest of the code in this repository. The build references ArcGIS
Pro's own assemblies on your machine and ships none of them.
