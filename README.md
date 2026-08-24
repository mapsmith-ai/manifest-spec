# Provenance manifests for geospatial datasets

A specification for one small JSON document, written next to one output dataset, that records
what was done to produce it — completely enough that **someone who was not there can re-run the
operation and disagree with it**.

```json
{
  "spec_version": "1.0.0-draft.1",
  "operation": "watershed",
  "parameters": {"method": "d8", "n_pour_points": 6},
  "inputs": [
    {"path": "fixtures/dem.tif", "sha256": "166b1e4e…", "crs": "EPSG:32610"}
  ],
  "engine": {"name": "whitebox-workflows", "version": "2.0.6"},
  "verification": [
    {"name": "crs_matches", "passed": true, "detail": "expected EPSG:32610, got EPSG:32610"}
  ],
  "started_at": "2026-08-23T10:12:04Z",
  "finished_at": "2026-08-23T10:12:09Z"
}
```

**Status: draft** (`1.0.0-draft.1`). Field names may still change; anything that does is visible
in this repository's history.

## What is in this repository

| | |
|---|---|
| [`spec/manifest-v1.md`](spec/manifest-v1.md) | The specification — short, and honest about what a manifest does **not** claim |
| [`schema/manifest-v1.schema.json`](schema/manifest-v1.schema.json) | The normative contract, JSON Schema 2020-12 |
| [`validator/validate.py`](validator/validate.py) | A standalone validator, **stdlib only** — checking a record needs no toolchain |
| [`conformance/`](conformance/) | Records that MUST validate and records that MUST be rejected, each with its expected reason |
| [`examples/emitter_minimal.py`](examples/emitter_minimal.py) | A complete conforming producer in under a hundred lines, importing nothing beyond the standard library |

The schema and the validator are **independent implementations**, kept in agreement by the
conformance suite: a record one accepts and the other rejects is a bug in one of them, and the
suite says which. A validator that disagrees with `conformance/` is wrong, whoever wrote it —
including us.

## What a manifest does not claim

**A manifest records what was done; it does not certify that it was right.** A record can carry
seven passing checks next to a wrong number if none of the checks looks at the number — the
reference implementation's own record did exactly that, and the finding is published on the
first page of [Argleton's results](https://argleton.org/#results). Measuring correctness is an
evaluation suite's job; recording what happened, verifiably, is this format's.

## Try it

```bash
python examples/emitter_minimal.py          # emit a conforming record
python validator/validate.py conformance/valid/*.json
pip install jsonschema pytest && pytest -q  # the full conformance suite
```

## Origin

Extracted from [MapSmith](https://mapsmith.dev), which emits a manifest beside every dataset it
writes and is one implementation of this specification, not its definition. The format is
useful exactly in proportion to how many producers that are not MapSmith emit it — hence the
hundred-line emitter, the toolchain-free validator, and the permissive licences.

## Licences

The specification text: **CC-BY-4.0** ([LICENSE-SPEC](LICENSE-SPEC)). Schema, validator,
conformance fixtures, examples: **Apache-2.0** ([LICENSE-CODE](LICENSE-CODE)).
