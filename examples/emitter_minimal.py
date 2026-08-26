"""A complete, conforming producer in under a hundred lines of stdlib.

This file is the proof that the manifest is a format and not one product's
output JSON: it imports nothing beyond the standard library, knows nothing
about any particular engine, and what it emits passes the same validator and
conformance suite as everyone else's records.

The demo at the bottom "processes" a file by copying it — the least interesting
operation with the most honest record. Run it:

    python emitter_minimal.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SPEC_VERSION = "1.0.0-draft.2"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def emit_manifest(
    output: Path,
    operation: str,
    parameters: dict,
    inputs: list[Path],
    engine: dict,
    checks: list[dict],
    started_at: str,
) -> Path:
    """Write ``<output>.provenance.json`` beside the output, and return its path.

    ``checks`` must hold at least one entry of the form
    ``{"name": ..., "passed": ..., "detail": ...}`` — including failed ones:
    the record must be written even when verification fails.
    """
    record = {
        "spec_version": SPEC_VERSION,
        "operation": operation,
        "parameters": parameters,
        "inputs": [
            # as_posix(), not str(): the spec requires `/` on every platform,
            # so two producers on two hosts describe the same run identically.
            {"path": p.as_posix(), "sha256": _sha256(p)}
            for p in inputs
        ],
        "engine": engine,
        # The digest of the thing the record sits beside: without it a consumer
        # cannot verify the sidecar describes these bytes.
        "output": {"path": output.as_posix(), "sha256": _sha256(output)},
        "verification": checks,
        "started_at": started_at,
        "finished_at": _utcnow(),
        "producer": {"name": "emitter-minimal", "version": "1.0"},
    }
    manifest = output.with_name(output.name + ".provenance.json")
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import shutil
    import sys
    import tempfile

    workdir = Path(tempfile.mkdtemp(prefix="emitter-demo-"))
    source = workdir / "input.bin"
    source.write_bytes(b"sixteen honest bytes")
    started = _utcnow()

    target = workdir / "output.bin"
    shutil.copy(source, target)  # the "operation"

    # One deterministic check, recorded with what was observed — a failed copy
    # would be recorded too, with passed: false.
    same = _sha256(source) == _sha256(target)
    manifest = emit_manifest(
        output=target,
        operation="copy_file",
        parameters={},
        inputs=[source],
        engine={"name": "shutil", "version": "3"},
        checks=[{
            # Not a core name from section 3.6, so it carries the producer prefix the
        # spec requires. This is the whole extension rule, in one line.
        "name": "x-emitter-minimal:bytes_identical",
            "passed": same,
            "detail": "sha256(output) == sha256(input)" if same else "checksums differ",
        }],
        started_at=started,
    )
    print(manifest)
    sys.exit(0 if same else 1)
