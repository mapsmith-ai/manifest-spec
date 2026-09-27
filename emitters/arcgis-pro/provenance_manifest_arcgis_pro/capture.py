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
     "launch": "geoprocessing_pane" | "python_window" | "project_history",
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

# When the input digests were taken, stated in the record because it decides
# what they prove (see the module docstring).
TIMING = {
    "geoprocessing_pane": "at tool start, concurrently with the tool",
    "python_window": "at tool start, concurrently with the tool",
    "project_history": "after the run, from the project's geoprocessing history",
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


def start(path: Path) -> dict:
    """Digest the inputs the capture names. Standard library only."""
    capture = _load(path)
    inputs, unhashed = [], []
    for param in capture.get("parameters", []):
        target = param.get("path")
        if not param.get("is_input") or not target:
            continue
        try:
            inputs.append(_as_dict(dataset_digest(target)))
        except (OSError, ValueError) as exc:
            unhashed.append(f"{param.get('name')}={str(target).replace(chr(92), '/')} ({exc})")
    capture["inputs"] = inputs
    capture["unhashed"] = unhashed
    capture["input_digests_taken_at"] = rec.utcnow()
    _save(path, capture)
    return capture


def _tool_id(tool: str | None) -> str:
    if not tool:
        return "unknown_tool"
    alias, _, name = tool.partition(".")
    return f"{name}_{alias}" if name else tool


def finish(path: Path) -> list[Path]:
    """Write the manifest beside each output. Imports ArcPy."""
    from . import arcgis  # imports arcpy: only here, never in `start`

    capture = _load(path)
    tool_id = _tool_id(capture.get("tool"))
    succeeded = bool(capture.get("succeeded"))
    inputs = [
        DatasetDigest(path=i["path"], sha256=i["sha256"], kind=i["kind"], layer=i.get("layer"))
        for i in capture.get("inputs", [])
    ]
    parameters = {
        p["name"]: (arcgis._posix(p["value"]) if p.get("path") else p.get("value"))
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
        p["path"]: arcgis._crs(p["path"])
        for p in capture.get("parameters", [])
        if p.get("is_input") and p.get("path") and arcgis._has_crs_slot(p["path"])
    }
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
    timing = TIMING.get(capture.get("launch"), "unknown")
    manifests = []
    outputs = [
        p["path"] for p in capture.get("parameters", []) if not p.get("is_input") and p.get("path")
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
        record[f"{rec.PREFIX}:input_digests_taken"] = timing
        if digest is None:
            from .digest import split_container

            container, layer = split_container(out_path)
            digest = DatasetDigest(container.as_posix(), "0" * 64, "file", layer)
        manifests.append(rec.write(record, rec.sidecar_path(digest)))
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
