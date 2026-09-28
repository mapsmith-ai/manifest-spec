"""Run an ArcGIS Pro geoprocessing tool and write a provenance manifest beside each output.

Runs inside ArcGIS Pro's Python environment, where ``arcpy`` is importable::

    from provenance_manifest_arcgis_pro.arcgis import run
    result, manifests = run("analysis.Buffer", r"C:\\data\\in.gdb\\wells",
                            r"C:\\data\\out.gdb\\wells_500m", "500 Meters")

The wrapper hashes every input dataset **before** the tool runs, so the digest
describes what was read rather than what was on disk afterwards; runs the tool
through arcpy; then hashes each output and records the parameters the tool
**ran with** -- ``Result.getInput`` returns defaults filled in, which is what
the specification asks for -- together with the engine version, the
geoprocessing environments in effect, the tool's messages and a set of
deterministic checks.

A failing tool still gets a manifest (the audit trail must survive the error it
documents), and the error is re-raised afterwards.

ArcGIS Pro already keeps a geoprocessing history: tool, parameters, times,
messages. What this adds is what that history does not hold -- the digest of
the bytes read and written, and checks recorded next to the result -- in a
format a consumer can read without ArcGIS.
"""

from __future__ import annotations

from pathlib import Path

import arcpy

from . import record as rec
from .digest import DatasetDigest, dataset_digest, split_container

# Parameter data types that name a dataset on disk. A value of one of these
# types that is not an existing path (a layer in a map, an in-memory dataset)
# is recorded as a parameter and reported in a check instead of being hashed.
DATASET_TYPES = {
    "Feature Layer",
    "Feature Class",
    "Shapefile",
    "Raster Layer",
    "Raster Dataset",
    "Mosaic Layer",
    "Mosaic Dataset",
    "Table",
    "Table View",
    "Dataset",
    "Composite Layer",
    "Feature Dataset",
    "Workspace",
    "File",
    "Terrain Layer",
    "LAS Dataset Layer",
}


def _tool(name: str):
    """Resolve ``"analysis.Buffer"`` to the arcpy function and its tool id ``Buffer_analysis``."""
    alias, _, tool = name.partition(".")
    if not tool:
        raise ValueError(f"expected '<toolbox alias>.<Tool>', e.g. 'analysis.Buffer'; got {name!r}")
    func = getattr(getattr(arcpy, alias), tool)
    return func, f"{tool}_{alias}"


def _types(param) -> set[str]:
    dt = param.datatype
    return set(dt) if isinstance(dt, (list, tuple)) else {dt}


def _dataset_paths(value) -> list[str]:
    if value in (None, ""):
        return []
    text = str(value)
    return [part.strip().strip("'\"") for part in text.split(";") if part.strip()]


def _posix(value: str) -> str:
    return str(value).replace("\\", "/")


def _has_crs_slot(path: str) -> bool:
    """A table has no spatial reference to declare, so crs_present does not apply."""
    try:
        return hasattr(arcpy.Describe(path), "spatialReference")
    except Exception:
        return False


def _crs(path: str) -> str | None:
    try:
        sr = arcpy.Describe(path).spatialReference
    except Exception:
        return None
    if sr is None or sr.name in ("", "Unknown"):
        return None
    return f"EPSG:{sr.factoryCode}" if sr.factoryCode else sr.name


def _count(path: str) -> int | None:
    try:
        return int(arcpy.management.GetCount(path)[0])
    except Exception:
        return None


def _environment() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in sorted(arcpy.env.keys()):
        try:
            value = arcpy.env[key]
        except Exception:
            continue
        if value is None or value == "":
            continue
        env[key] = str(value)
    return env


def _engine() -> dict:
    info = arcpy.GetInstallInfo()
    return {
        "name": "ArcGIS Pro",
        "version": info["Version"],
        f"{rec.PREFIX}:build": str(info.get("BuildNumber", "")),
        f"{rec.PREFIX}:license_level": arcpy.ProductInfo(),
    }


def _messages(result_or_none, fallback: str | None) -> list[dict]:
    levels = {0: "info", 1: "warning", 2: "error"}
    if result_or_none is None:
        return [{"severity": "error", "text": fallback}] if fallback else []
    return [
        {
            "severity": levels.get(
                result_or_none.getSeverity(i), str(result_or_none.getSeverity(i))
            ),
            "text": result_or_none.getMessage(i),
        }
        for i in range(result_or_none.messageCount)
    ]


def run(tool: str, *args, **kwargs):
    """Run ``tool`` with provenance. Returns ``(result, [manifest paths])``."""
    func, tool_id = _tool(tool)
    params = list(arcpy.GetParameterInfo(tool_id))
    names = [p.name for p in params]
    call: dict = dict(zip(names, args))
    unknown = set(kwargs) - set(names)
    if unknown:
        raise TypeError(f"{tool_id} has no parameter(s) {sorted(unknown)}; it has {names}")
    call.update(kwargs)

    inputs: list[DatasetDigest] = []
    input_arguments: list[str] = []
    unhashed: list[str] = []
    input_crs: dict[str, str | None] = {}
    for p in params:
        if p.direction != "Input" or not (_types(p) & DATASET_TYPES):
            continue
        for path in _dataset_paths(call.get(p.name)):
            # Exists first: the digest of a container says nothing about whether
            # the layer named inside it is there, and a record must not claim to
            # have read a layer that does not exist.
            if not arcpy.Exists(path):
                unhashed.append(f"{p.name}={_posix(path)} (does not exist)")
                continue
            try:
                d = dataset_digest(path)
            except (FileNotFoundError, ValueError):
                unhashed.append(f"{p.name}={_posix(path)}")
                continue
            inputs.append(d)
            input_arguments.append(p.name)
            input_crs[path] = _crs(path)

    environment = _environment()
    started = rec.utcnow()
    result = None
    error: str | None = None
    raised: BaseException | None = None
    try:
        result = func(*args, **kwargs)
    except arcpy.ExecuteError:
        error = arcpy.GetMessages(2)
    except Exception as exc:
        # Not only a tool error: a bad argument or a crash in ArcPy itself must
        # leave a record too, and then propagate unchanged.
        error = f"{type(exc).__name__}: {exc}"
        raised = exc
    finished = rec.utcnow()

    # The parameters the tool ran with: Result lists input values in parameter
    # order with defaults filled, and output values likewise.
    ran_with: dict = {}
    if result is not None:
        in_params = [p.name for p in params if p.direction == "Input"]
        out_params = [p.name for p in params if p.direction == "Output"]
        for i in range(result.inputCount):
            if i < len(in_params):
                ran_with[in_params[i]] = str(result.getInput(i))
        for i in range(result.outputCount):
            if i < len(out_params):
                ran_with[out_params[i]] = str(result.getOutput(i))
    else:
        ran_with = {k: str(v) for k, v in call.items()}
    # The specification writes paths with `/` on every platform, so two hosts
    # describe the same run identically; that holds for a path passed as a
    # parameter as much as for `inputs[].path`.
    dataset_params = {p.name for p in params if _types(p) & DATASET_TYPES}
    ran_with = {k: (_posix(v) if k in dataset_params else v) for k, v in ran_with.items()}

    checks: list[dict] = []
    succeeded = result is not None and result.maxSeverity < 2
    checks.append(
        rec.check(
            f"{rec.PREFIX}:tool_succeeded",
            succeeded,
            f"{tool_id} finished with status {getattr(result, 'status', 'n/a')} and highest "
            f"message severity {getattr(result, 'maxSeverity', 'n/a')}"
            if result is not None
            else f"{tool_id} raised ExecuteError: {error}",
        )
    )
    if input_crs:
        missing = [p for p, c in input_crs.items() if c is None]
        checks.append(
            rec.check(
                "input_crs_present",
                not missing,
                "every input declares a CRS: " + ", ".join(f"{c}" for c in input_crs.values())
                if not missing
                else f"no CRS declared by: {', '.join(missing)}",
            )
        )
        declared = {c for c in input_crs.values() if c}
        if len(input_crs) > 1:
            checks.append(
                rec.check(
                    "inputs_share_crs",
                    len(declared) == 1,
                    f"input CRSs: {sorted(declared)}",
                )
            )
    if unhashed:
        checks.append(
            rec.check(
                f"{rec.PREFIX}:inputs_hashed",
                False,
                "not a dataset on disk, so no digest could be recorded: " + "; ".join(unhashed),
            )
        )
    # A linear distance with no unit: ArcGIS accepts '10 Unknown' and interprets
    # it in the units of the data, which is a number whose meaning the call
    # never stated.
    for p in params:
        if "Linear Unit" in _types(p) and str(ran_with.get(p.name, "")).endswith(" Unknown"):
            checks.append(
                rec.check(
                    f"{rec.PREFIX}:linear_unit_declared",
                    False,
                    f"{p.name} ran as {ran_with[p.name]!r}: the distance was applied in the "
                    "units of the data, not in a unit the call declared",
                )
            )

    outputs: list[str] = []
    for p in params:
        if p.direction == "Output" and (_types(p) & DATASET_TYPES):
            outputs.extend(_dataset_paths(ran_with.get(p.name) or call.get(p.name)))

    messages = _messages(result, error)
    engine = _engine()
    manifests: list[Path] = []
    for out_path in outputs:
        out_checks = list(checks)
        crs = None
        try:
            digest = dataset_digest(out_path)
        except (FileNotFoundError, ValueError):
            digest = None  # a failed tool may have written nothing
        if digest is not None and succeeded:
            if _has_crs_slot(out_path):
                crs = _crs(out_path)
                out_checks.append(
                    rec.check(
                        "crs_present",
                        crs is not None,
                        f"output declares {crs}" if crs else "output declares no CRS",
                    )
                )
            n = _count(out_path)
            if n is not None:
                out_checks.append(
                    rec.check(
                        "result_not_empty",
                        n > 0,
                        f"output has {n} row(s)",
                    )
                )
        record = rec.build(
            operation=tool_id,
            parameters=ran_with,
            inputs=inputs,
            input_arguments=input_arguments,
            output=digest,
            output_crs=crs,
            engine=engine,
            checks=out_checks,
            started_at=started,
            finished_at=finished,
            environment=environment,
            messages=messages,
        )
        if digest is None:
            # Where the record would sit had the output been written -- never
            # inside a container, which would change the container's digest.
            container, layer = split_container(out_path)
            digest_for_path = DatasetDigest(
                path=container.as_posix(), sha256="0" * 64, kind="file", layer=layer
            )
            target = rec.sidecar_path(digest_for_path)
        else:
            target = rec.sidecar_path(digest)
        manifests.append(rec.write(record, target))

    if raised is not None:
        raise raised
    if error is not None:
        raise arcpy.ExecuteError(error)
    return result, manifests
