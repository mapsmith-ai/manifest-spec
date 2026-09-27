# Provenance Manifest add-in for ArcGIS Pro

An ArcGIS Pro add-in that writes a provenance manifest beside each dataset a geoprocessing tool
writes — for tools run from the Geoprocessing pane, the Python window, or another add-in, with the
exceptions listed [below](#what-it-records-and-what-it-cannot). It is
the interactive side of the [reference emitter](../README.md): the add-in sees each tool start
and finish, and the digests and the record come from the emitter's Python package, embedded in
the add-in, so the digest rule of [section 3.3](../../../spec/manifest-v1.md#33-field-semantics-that-are-easy-to-get-wrong)
has one implementation.

*Not affiliated with, sponsored or endorsed by Esri. ArcGIS, ArcGIS Pro and ArcPy are trademarks
of Esri.*

**Status: early.** Tested end to end on ArcGIS Pro 3.7.1 and 3.7.2 by its autotest (below), which
runs tools from code, the way another add-in does. That the same event fires for the
Geoprocessing pane and the Python window is measured; a manifest written from each of them has not
yet been checked end to end. Source only: build it with your own ArcGIS Pro.

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

The checks are fewer than [`run`](../README.md#what-goes-in-the-record) writes:
`x-provenance-manifest-arcgis-pro:tool_succeeded`, `input_crs_present`, `crs_present`,
`result_not_empty`, and `...:inputs_hashed` when an input could not be given a digest. Not yet
`inputs_share_crs` or `...:linear_unit_declared`.

Measured on ArcGIS Pro 3.7, and stated in the record rather than hidden:

- **Input digests are taken at tool start, concurrently with the tool.** The event the add-in
  listens to does not block the tool. Exact for a tool that only reads its inputs.
- **A tool that edits its input in place** (Calculate Field, Add Field, Append) is recorded with
  `x-provenance-manifest-arcgis-pro:writes_to_input: true`: its input digest may already
  describe the edited state. The record it would overwrite — the one of the operation that
  created the dataset — is kept beside it under a dated name,
  `<name>.<timestamp>.provenance.json`, and named in the new record.
- **A run with no parameters at its start** (a tool run from code without adding to the project
  history) has its inputs hashed after the run, and the record says so.
- **A layer name** (the Python window passes names, not paths) is resolved to the dataset behind the
  layer before hashing, in the active map first and then in the project's other maps.
- **A layer with a selection or a definition query** is recorded as such: the tool read a subset,
  while the input digest covers the whole dataset behind the layer, so a re-run on that dataset can
  give a different answer. The record carries `x-provenance-manifest-arcgis-pro:layer_filters`
  (layer, selection count, definition query) and a failed, non-critical check
  `x-provenance-manifest-arcgis-pro:input_read_whole`. The selected IDs themselves are not recorded.
- **A parameter holding several datasets** (the inputs of Merge) is split, and each dataset gets its
  own digest. A name that leads to no file (a service layer, a name no map holds) gets no digest
  and is named in `...:inputs_hashed`.
- **Tools that change a layer and write no dataset** (Select Layer By Attribute or By Location,
  Make Feature Layer and the other Make ... Layer tools, Apply Symbology From Layer, Get Count)
  write no record: their output is the layer they were given, and read as a writer they would
  claim an in-place edit of the dataset behind it.
- **Not covered yet: models run from ModelBuilder.** No geoprocessing event fires for them. A model
  run as a tool from code raises one event for the model and none for the tools inside it.

## Autotest

`run_autotest.ps1 -PristineProject <folder>` copies any ArcGIS Pro project folder with a map (it is
never modified), starts Pro on the copy with `/provenance-manifest-autotest`, lets the add-in open a
view on the project's first map and run a fixed sequence (create a fishnet, buffer it by path and
by layer name, copy without history, copy again and add and calculate a field on that copy in
place, merge two datasets in one parameter, select three features on a layer and buffer the
layer), waits for Pro to exit, and checks every manifest with this repository's validator and
against what the sequence should produce (`check_manifests.py`). No clicks. It refuses to start
when the installed add-in is not the build output, and it deletes the add-in's log and capture
files in `%LOCALAPPDATA%\ProvenanceManifest` before it starts.

The map view is part of the test on purpose: without one, a layer made by a tool lives only in the
geoprocessing session, and no map holds it for the add-in to resolve. With it, each tool waits for
a redraw -- a few minutes in all, more on a locked session.

Licence: Apache-2.0, like the rest of the code in this repository. The build references ArcGIS
Pro's own assemblies on your machine and ships none of them.
