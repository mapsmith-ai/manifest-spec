# Manifest specification contributor instructions

This repository defines a provenance format; it is not a MapSmith package. A manifest records what was done and does not certify that the result was correct.

## Sources of truth

- `spec/manifest-v1.md`: human-readable specification.
- `schema/manifest-v1.schema.json`: normative JSON Schema.
- `validator/validate.py`: standalone, standard-library-only validator.
- `conformance/valid/` and `conformance/invalid/`: records that must be accepted or rejected for the declared reason.
- `examples/`: minimal producers and consumers that third parties can copy.
- `emitters/`: engine-specific reference emitters, isolated from one another.

Keep the prose, schema, validator, conformance corpus and examples aligned. Test both directions: a record accepted by one implementation and rejected by another is a defect. Preserve the validator's lack of runtime dependencies and its Python 3.9 floor.

A version label is spent once published. Do not rewrite tagged specifications or silently change the meaning of an existing field. Coordinate producer-facing changes with real emitted records and document extension keys and version implications.

## Checks

```bash
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m pytest -q
.venv/Scripts/python validator/validate.py conformance/valid/*.json
```

The suite must also work from a source archive without Git metadata. Public artifacts, identifiers and commit messages are in English. The specification text is CC-BY-4.0; code, schema, fixtures, examples and emitters are Apache-2.0. Do not commit, push, tag or release unless explicitly requested.
