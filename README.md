# Provenance manifests for geospatial datasets

A specification for one small JSON document, written next to one output dataset, that records
what was done to produce it — completely enough that **someone who was not there can re-run the
operation and disagree with it**.

```json
{
  "spec_version": "1.0.0-draft.6",
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

**Status: draft** (`1.0.0-draft.6`). Field names may still change; anything that does is visible
in this repository's history.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22205213.svg)](https://doi.org/10.5281/zenodo.22205213)

Cite it as `10.5281/zenodo.22205213`, the concept DOI, which resolves to the latest archived
version. To cite the exact draft you read, take its version DOI from the
[Zenodo record](https://doi.org/10.5281/zenodo.22205213).

**One gap, stated because a reader can hit it.** `draft.4` was never tagged and never archived,
so it has no version DOI; it is citable only by commit. For five weeks neither had `draft.5`,
while this paragraph claimed the concept DOI "always resolves to the current version" — false
for every reader since draft.4. That is the discipline this document demands of a label, six
sections down (*a label is spent the moment it is published, and pushing is publishing*),
applied to producers and not to us. `draft.5` was archived on 21 September 2026. `draft.6` was
released on 24 September and **is not archived yet**: Zenodo accepted the release and has not
created the record, so until it does the concept DOI still resolves to `draft.5` and `draft.6`
is citable by its tag, `v1.0.0-draft.6`. This paragraph said it was archived, in the release
itself, written before the archive existed; the archive is checked from outside now before a
sentence claims it.

## What is in this repository

| | |
|---|---|
| [`spec/manifest-v1.md`](spec/manifest-v1.md) | The specification — short, and honest about what a manifest does **not** claim |
| [`schema/manifest-v1.schema.json`](schema/manifest-v1.schema.json) | The normative contract, JSON Schema 2020-12 |
| [`validator/validate.py`](validator/validate.py) | A standalone validator, **stdlib only** — checking a record needs no toolchain |
| [`conformance/`](conformance/) | Records that MUST validate and records that MUST be rejected, each with its expected reason |
| [`examples/emitter_minimal.py`](examples/emitter_minimal.py) | A complete conforming producer in under a hundred lines, importing nothing beyond the standard library |
| [`examples/chain_resolves_by_digest.py`](examples/chain_resolves_by_digest.py) | Multi-step lineage recovered from one file, by content, with no field pointing at another record — §6 |

The schema and the validator are **independent implementations**, kept in agreement by a
conformance suite that mutates every field the schema declares — required and recommended — and
requires **both** to reject it. A record one accepts and the other rejects is a bug in one of
them, and the suite says which one is the lenient one. A validator that disagrees with `conformance/` is wrong, whoever wrote it —
including us.

## What a manifest does not claim

**A manifest records what was done; it does not certify that it was right.** A record can carry
seven passing checks next to a wrong number if none of the checks looks at the number — the
reference implementation's own record did exactly that, and the finding is published on the
first page of [Argleton's results](https://argleton.org/#results). Measuring correctness is an
evaluation suite's job; recording what happened, verifiably, is this format's.

## Try it without adopting anything

The validator is one file, standard library only, and it does not need this
repository. Check a record you already have:

```bash
curl -O https://raw.githubusercontent.com/mapsmith-ai/manifest-spec/main/validator/validate.py
python validate.py my-dataset.tif.provenance.json
```

It prints one line per problem and exits 1, or prints `conforming` and exits 0 —
so it drops into a pipeline as a gate without anything else being installed.
There is nothing to `pip install`, and that is deliberate: a format whose point
is that checking it needs no toolchain cannot ship as a package that needs one.

Produce one, if you have not got one yet. The reference emitter is also a single
stdlib file, and it imports nothing from any product:

```bash
curl -O https://raw.githubusercontent.com/mapsmith-ai/manifest-spec/main/examples/emitter_minimal.py
python emitter_minimal.py | xargs python validate.py
```

And check a validator of your own — yours, ours, anyone's — against the
conformance corpus, which is the part that settles arguments:

```bash
curl -sL https://github.com/mapsmith-ai/manifest-spec/archive/refs/heads/main.tar.gz | tar xz
cd manifest-spec-main && pip install jsonschema pytest && pytest -q
```

`conformance/valid/` holds records that MUST validate, `conformance/invalid/`
records that MUST be rejected with the reason each one is rejected for, and the
suite mutates every field the schema declares to check that the schema and the
validator agree on all of them. A validator that disagrees with that directory is
wrong, whoever wrote it — including us.

### From a checkout

```bash
python examples/emitter_minimal.py          # emit a conforming record
python validator/validate.py conformance/valid/*.json
python examples/environment_changes_the_answer.py   # why section 3.8 exists
python examples/chain_resolves_by_digest.py         # walk a two-step lineage, section 6
pip install jsonschema pytest && pytest -q  # the full conformance suite
```

## Origin

Extracted from [MapSmith](https://mapsmith.dev), which emits a manifest beside every dataset it
writes and is one implementation of this specification, not its definition. The format is
useful exactly in proportion to how many producers that are not MapSmith emit it — hence the
hundred-line emitter, the toolchain-free validator, and the permissive licences.

MapSmith is also, as of 2026-09-21, the first **consumer** of §6: its `get_lineage` walks a
chain of records by content digest. That is worth naming here and not in the specification,
where the reference remains the twenty-line
[`examples/chain_resolves_by_digest.py`](examples/chain_resolves_by_digest.py) — a document that
points at its own author's implementation as the thing to match is not a specification. Writing
that consumer is what produced the second reading of §6's first limit: a failed check carrying
no `critical` must not be read as a non-critical one, because absence means the producer made
no claim. The first walker written against this text got it wrong, and now the text says so and
`conformance/valid/` carries a record that catches it.

## Licences

The specification text: **CC-BY-4.0** ([LICENSE-SPEC](LICENSE-SPEC)). Schema, validator,
conformance fixtures, examples: **Apache-2.0** ([LICENSE-CODE](LICENSE-CODE)).
