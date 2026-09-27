"""Build a manifest conforming to the geospatial provenance manifest specification.

Standard library only. The engine-specific code (``arcgis.py``) gathers the
facts; this module only puts them in the shape the specification defines, so
the shape can be tested without an engine.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .digest import DatasetDigest

SPEC_VERSION = "1.0.0-draft.8"
PRODUCER = "provenance-manifest-arcgis-pro"
PRODUCER_VERSION = "0.0.1"
# Every key the specification does not define carries this prefix (spec 3.5,
# enforced inside crs_decisions and repairs since draft.8), and the same
# string as producer.name.
PREFIX = "x-provenance-manifest-arcgis-pro"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dataset_entry(d: DatasetDigest) -> dict:
    entry: dict = {"path": d.path, "sha256": d.sha256}
    if d.layer is not None:
        entry["layer"] = d.layer
    if d.kind != "file":
        # A consumer recomputing the digest must know it is not the SHA-256 of
        # one file. Not a spec field yet: until the specification defines the
        # digest of a multi-file dataset, the rule is ours and says so.
        entry[f"{PREFIX}:digest_rule"] = f"{d.kind}-listing-v1"
        entry[f"{PREFIX}:member_files"] = d.members
    return entry


def check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def build(
    *,
    operation: str,
    parameters: dict,
    inputs: list[DatasetDigest],
    output: DatasetDigest | None,
    output_crs: str | None,
    engine: dict,
    checks: list[dict],
    started_at: str,
    finished_at: str,
    environment: dict[str, str] | None = None,
    messages: list[dict] | None = None,
) -> dict:
    if not checks:
        raise ValueError("a manifest needs at least one verification check")
    record: dict = {
        "spec_version": SPEC_VERSION,
        "operation": operation,
        "parameters": parameters,
        "inputs": [dataset_entry(d) for d in inputs],
        "engine": engine,
        "verification": checks,
        "started_at": started_at,
        "finished_at": finished_at,
        "producer": {"name": PRODUCER, "version": PRODUCER_VERSION},
    }
    if output is not None:
        out = dataset_entry(output)
        if output_crs:
            out["crs"] = output_crs
        record["output"] = out
    if environment:
        record["environment"] = environment
    if messages:
        record[f"{PREFIX}:messages"] = messages
    return record


def sidecar_path(output: DatasetDigest) -> Path:
    """Where the manifest goes.

    Beside a file: ``<file>.provenance.json``, as the specification recommends.
    For a layer inside a container, the manifest cannot go inside the container
    -- it would change the container's own digest -- so it goes beside it:
    ``<container>.<layer>.provenance.json``, with ``/`` in the layer name
    replaced by ``.``. Provisional: where such a record belongs is an open
    question for the specification.
    """
    base = Path(output.path)
    if output.layer:
        return base.with_name(f"{base.name}.{output.layer.replace('/', '.')}.provenance.json")
    return base.with_name(base.name + ".provenance.json")


def write(record: dict, path: Path) -> Path:
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
