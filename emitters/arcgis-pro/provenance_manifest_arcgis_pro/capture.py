"""Turn a geoprocessing run captured inside ArcGIS Pro into a provenance manifest.

The ArcGIS Pro add-in sees a tool start and finish (``GPExecuteToolEvent``) but
the digest rule and the record live here, in one implementation. It writes a
capture file and starts two short processes with ArcGIS Pro's Python::

    python -m provenance_manifest_arcgis_pro.capture start  <capture.json>
    python -m provenance_manifest_arcgis_pro.capture finish <capture.json>

``start`` imports nothing but the standard library, so it runs as soon as the
tool starts: it digests every input dataset the capture names and writes the
digests back into the capture. The event does not block the tool (measured on
ArcGIS Pro 3.7.1), so these digests are taken **concurrently** with the tool:
exact for a tool that only reads its inputs, and possibly already the edited
state for one that writes to them in place -- the record says which timing
applied. ``finish`` imports ArcPy, digests each output, reads its CRS and row
count, and writes the manifest beside it.

The capture, written by the add-in (``capture_version`` 1)::

    {"capture_version": 1, "tool": "analysis.Buffer", "run_id": "...",
     "launch": "geoprocessing_pane" | "python_window" | "code" | "project_history",
     "inputs_hashed": "at_start" | "after_run",
     "started_at": "...Z", "finished_at": "...Z",
     "parameters": [{"name", "type", "value", "is_input", "path"}],
     "succeeded": true, "error_code": 0, "messages": ["..."],
     "environments": {"name": "value"}}

``path`` is the dataset on disk a parameter refers to, resolved by the add-in
when the value is a layer name; null when the parameter names no dataset.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import record as rec
from .digest import DatasetDigest, dataset_digest

CAPTURE_VERSION = 1

# Tools that change a layer -- its selection, its definition, its symbology --
# and write no dataset. Their output parameter is the layer they were given, so
# without this list the add-in would read them as editing the dataset behind
# the layer in place and write a record claiming so. Matched on the tool name
# ArcGIS reports (`<toolbox alias>.<Tool>`), case-insensitively.
VIEW_ONLY_TOOLS = frozenset(
    name.lower()
    for name in (
        "management.SelectLayerByAttribute",
        "management.SelectLayerByLocation",
        "management.MakeFeatureLayer",
        "management.MakeTableView",
        "management.MakeRasterLayer",
        "management.MakeQueryLayer",
        "management.ApplySymbologyFromLayer",
        "management.GetCount",
    )
)

# When the input digests were taken, stated in the record because it decides
# what they prove (see the module docstring).
TIMING = {
    "at_start": "at tool start, concurrently with the tool",
    "after_run": "after the run: the tool start carried no parameters to hash from",
}


def _load(path: Path) -> dict:
    capture = json.loads(path.read_text(encoding="utf-8"))
    if capture.get("capture_version") != CAPTURE_VERSION:
        raise ValueError(f"unsupported capture_version {capture.get('capture_version')!r}")
    return capture


def _save(path: Path, capture: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(capture, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _as_dict(d: DatasetDigest) -> dict:
    return {"path": d.path, "sha256": d.sha256, "kind": d.kind, "layer": d.layer}


def _paths(param: dict) -> list[str]:
    """Every dataset path a parameter names: `paths` for a multi-value one."""
    paths = [p for p in (param.get("paths") or []) if p]
    if not paths and param.get("path"):
        paths = [param["path"]]
    return paths


def start(path: Path) -> dict:
    """Digest the inputs the capture names. Standard library only."""
    capture = _load(path)
    inputs, unhashed = [], []
    for param in capture.get("parameters", []):
        if not param.get("is_input"):
            continue
        for target in _paths(param):
            try:
                inputs.append(dict(_as_dict(dataset_digest(target)), argument=param.get("name")))
            except (OSError, ValueError) as exc:
                unhashed.append(f"{param.get('name')}={str(target).replace(chr(92), '/')} ({exc})")
        for value in param.get("unresolved") or []:
            # Named a dataset and resolved to no file: a layer from a service, a
            # name no map holds. Said, not dropped.
            unhashed.append(f"{param.get('name')}={value} (not resolved to a dataset on disk)")
    capture["inputs"] = inputs
    capture["unhashed"] = unhashed
    capture["input_digests_taken_at"] = rec.utcnow()
    _save(path, capture)
    return capture


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").rstrip("/").lower()


def writes_to_input(capture: dict) -> set[str]:
    """Outputs that are also inputs: the tool edited a dataset in place.

    Calculate Field, Add Field, Append and the like report the dataset they
    change as a derived output with the same value as an input. Their input
    digest was taken concurrently with the edit (or after it), so it cannot be
    presented as the state the tool read; and the manifest they write sits where
    the record of the operation that created the dataset sat.
    """
    params = capture.get("parameters", [])
    ins = {_norm(path) for p in params if p.get("is_input") for path in _paths(p)}
    return {
        path
        for p in params
        if not p.get("is_input")
        for path in _paths(p)
        if _norm(path) in ins
    }


def keep_previous(sidecar: Path, stamp: str) -> Path | None:
    """Keep the record an in-place edit would overwrite, under a dated name.

    `<name>.provenance.json` becomes `<name>.<stamp>.provenance.json`: still a
    `*.provenance.json` file a lineage walker scanning a folder will index, so
    the history of the dataset survives its edit. Where such a record belongs is
    not defined by the specification yet; this is the emitter's choice, named
    in the new record.
    """
    if not sidecar.exists():
        return None
    base = sidecar.name[: -len(".provenance.json")]
    safe = stamp.replace(":", "").replace("-", "")
    target = sidecar.with_name(f"{base}.{safe}.provenance.json")
    n = 1
    while target.exists():
        n += 1
        target = sidecar.with_name(f"{base}.{safe}-{n}.provenance.json")
    sidecar.replace(target)
    return target


def _tool_id(tool: str | None) -> str:
    if not tool:
        return "unknown_tool"
    alias, _, name = tool.partition(".")
    return f"{name}_{alias}" if name else tool


def finish(path: Path) -> list[Path]:
    """Write the manifest beside each output. Imports ArcPy."""
    capture = _load(path)
    if str(capture.get("tool") or "").lower() in VIEW_ONLY_TOOLS:
        return []  # no dataset written, so no record to write beside one

    from . import arcgis  # imports arcpy: only here, never in `start`

    tool_id = _tool_id(capture.get("tool"))
    succeeded = bool(capture.get("succeeded"))
    inputs = [
        DatasetDigest(path=i["path"], sha256=i["sha256"], kind=i["kind"], layer=i.get("layer"))
        for i in capture.get("inputs", [])
    ]
    # The tool parameter each input came from (draft.10, `inputs[].argument`).
    input_arguments = [i.get("argument") for i in capture.get("inputs", [])]
    parameters = {
        p["name"]: (
            arcgis._posix(p["value"]) if (p.get("dataset") or _paths(p)) else p.get("value")
        )
        for p in capture.get("parameters", [])
    }
    checks = [
        rec.check(
            f"{rec.PREFIX}:tool_succeeded",
            succeeded,
            f"{tool_id} finished with error code {capture.get('error_code')}",
        )
    ]
    input_crs = {
        path: arcgis._crs(path)
        for p in capture.get("parameters", [])
        if p.get("is_input")
        for path in _paths(p)
        if arcgis._has_crs_slot(path)
    }
    filters = [
        dict(f, parameter=p.get("name"))
        for p in capture.get("parameters", [])
        if p.get("is_input")
        for f in (p.get("layer_filters") or [])
    ]
    if filters:
        checks.append({
            "name": f"{rec.PREFIX}:input_read_whole",
            "passed": False,
            "critical": False,
            "detail": "the tool read a subset of a layer, while the input digest covers the whole "
            "dataset: " + "; ".join(
                f"{f['layer']} ({f.get('selection_count') or 0} selected"
                + (
                    f", definition query {f['definition_query']!r}"
                    if f.get("definition_query")
                    else ""
                )
                + ")"
                for f in filters
            ),
        })
    if input_crs:
        missing = [path for path, crs in input_crs.items() if crs is None]
        checks.append(
            rec.check(
                "input_crs_present",
                not missing,
                "every input declares a CRS: " + ", ".join(str(c) for c in input_crs.values())
                if not missing
                else "no CRS declared by: " + ", ".join(arcgis._posix(m) for m in missing),
            )
        )
    if capture.get("unhashed"):
        checks.append(
            rec.check(
                f"{rec.PREFIX}:inputs_hashed",
                False,
                "no digest could be recorded for: " + "; ".join(capture["unhashed"]),
            )
        )
    messages = [{"severity": "info", "text": m} for m in capture.get("messages", [])]
    engine = arcgis._engine()
    timing = TIMING.get(capture.get("inputs_hashed"), "unknown")
    in_place = {_norm(x) for x in writes_to_input(capture)}
    manifests = []
    outputs = [
        path for p in capture.get("parameters", []) if not p.get("is_input") for path in _paths(p)
    ]
    for out_path in outputs:
        out_checks = list(checks)
        crs = None
        try:
            digest = dataset_digest(out_path)
        except (OSError, ValueError):
            digest = None
        if digest is not None and succeeded:
            if arcgis._has_crs_slot(out_path):
                crs = arcgis._crs(out_path)
                out_checks.append(
                    rec.check(
                        "crs_present",
                        crs is not None,
                        f"output declares {crs}" if crs else "output declares no CRS",
                    )
                )
            n = arcgis._count(out_path)
            if n is not None:
                out_checks.append(rec.check("result_not_empty", n > 0, f"output has {n} row(s)"))
        record = rec.build(
            operation=tool_id,
            parameters=parameters,
            inputs=inputs,
            input_arguments=input_arguments,
            output=digest,
            output_crs=crs,
            engine=engine,
            checks=out_checks,
            started_at=capture.get("started_at") or rec.utcnow(),
            finished_at=capture.get("finished_at") or rec.utcnow(),
            environment={k: str(v) for k, v in (capture.get("environments") or {}).items()},
            messages=messages,
        )
        record[f"{rec.PREFIX}:launch"] = capture.get("launch")
        if filters:
            record[f"{rec.PREFIX}:layer_filters"] = filters
        record[f"{rec.PREFIX}:input_digests_taken"] = timing
        if digest is None:
            from .digest import split_container

            container, layer = split_container(out_path)
            digest = DatasetDigest(container.as_posix(), "0" * 64, "file", layer)
        sidecar = rec.sidecar_path(digest)
        if _norm(out_path) in in_place:
            record[f"{rec.PREFIX}:writes_to_input"] = True
            record[f"{rec.PREFIX}:input_digests_taken"] = (
                timing + "; the tool edits this input in place, so the input digest may "
                "already describe the edited state"
            )
            kept = keep_previous(sidecar, record["finished_at"])
            if kept is not None:
                record[f"{rec.PREFIX}:previous_record"] = kept.name
        manifests.append(rec.write(record, sidecar))
    return manifests


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("start", "finish"):
        print("usage: python -m provenance_manifest_arcgis_pro.capture start|finish <capture.json>")
        return 2
    step, capture = argv[1], Path(argv[2])
    if step == "start":
        start(capture)
    else:
        for m in finish(capture):
            print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
