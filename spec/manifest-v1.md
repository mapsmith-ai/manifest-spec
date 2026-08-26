# Provenance manifests for geospatial datasets — v1.0.0-draft.3

**Status: draft.** Field names and semantics may still change; anything that does will be
visible in this repository's history. The draft label comes off when a second, independent
implementation emits conforming records.

## 1. What this is

A provenance manifest is one JSON document written **next to one output dataset**, recording what
was done to produce it: the inputs with their checksums, the exact parameters, the engine and its
version, the coordinate-system decisions and why, and the deterministic checks that ran on the
result — pass or fail.

The bar it aims at: **someone who was not there can re-run the operation and disagree with it.**
That is a higher bar than being able to read what happened, and every mandatory field exists to
clear it.

One thing this format deliberately does not claim: **a manifest records what was done; it does
not certify that it was right.** A record can carry seven passing checks next to a wrong number
if none of the checks looks at the number. Measuring that second property is a job for evaluation
suites (see [Argleton](https://argleton.org), whose first published result demonstrates exactly
this gap — on the software this specification was extracted from).

## 2. Terminology

The key words MUST, MUST NOT, SHOULD, and MAY are to be interpreted as described in RFC 2119.

- **Producer** — software that emits manifests.
- **Consumer** — software or person that reads them.
- **Engine** — the software that computed the result, as distinct from the producer that
  orchestrated it and wrote the record.

## 3. The record

The normative contract is the JSON Schema in
[`schema/manifest-v1.schema.json`](../schema/manifest-v1.schema.json); this section explains the
intent. Where the two disagree, the schema wins and the disagreement is a bug in this document.

### 3.1 Placement and naming

A manifest describes exactly one output dataset. Producers SHOULD write it beside the output as
`<output-filename>.provenance.json`. A manifest MUST be written even when verification fails:
the audit trail has to survive the error it documents.

### 3.2 Mandatory fields

| field | what it records |
|---|---|
| `spec_version` | The version of this specification. The one field that can never be optional: without it, a record cannot be interpreted once the format has more than one version. |
| `operation` | What was done, as a stable identifier. Producers choose their vocabulary. |
| `parameters` | The parameters the engine **ran with** — not the ones requested. Present even when empty: an absent field cannot be told apart from "nobody recorded them". |
| `inputs[]` | Every dataset read, each with `path` and `sha256`. May be empty for pure generators. |
| `engine` | `name` and `version` of what computed the result. An engine without a version is not reproducible, only imitable. |
| `verification[]` | At least one deterministic check, with `name`, `passed`, `detail`. Failed checks MUST be recorded, not suppressed. |
| `started_at`, `finished_at` | RFC 3339, UTC only. `finished_at` MUST NOT precede `started_at`. |

### 3.3 Field semantics that are easy to get wrong

**Paths use `/` as the only separator, on every platform.** A path carrying the host's separator
makes two manifests for the same run on the same bytes differ in a field that describes nothing
about the computation — and gives any consumer keying on paths two entries for one file. This
rule exists because the reference implementation shipped without it and the defect was found the
day the manifest went on a web page. Paths are otherwise recorded **as given**: rewriting an
absolute path to a relative one, or the reverse, would misstate what ran.

**`sha256` is of the bytes, not the file identity.** Lowercase hex, 64 characters. A manifest
whose input has been edited since stops matching, and says so. For container formats holding
multiple layers, the checksum necessarily covers the whole container; the RECOMMENDED
`inputs[].layer` field records which layer was actually read, because without it an auditor
holding a five-layer container cannot tell which layer produced the numbers.

**Timestamps are UTC and end in `Z`.** Local times make two manifests disagree about the order
of events depending on where they are read.

**`verification[].detail` is prose, not a boolean.** "expected EPSG:32610, got EPSG:32610" can
be argued with; `true` cannot. A check that only reports *that* something passed wastes the
diagnosis it already has.

### 3.4 Recommended fields

**`output`** — the `path` and `sha256` of the dataset this record sits beside. Without it, a
consumer cannot verify that the sidecar describes the bytes next to it, and the record cannot be
wrapped in an in-toto attestation (whose `subject` requires a digest — see §8). Recommended
rather than mandatory only because a producer may emit the manifest before the output is durably
on disk; when the digest can be computed, it SHOULD be.

`crs_decisions` (each decision **with its reason** — the what without the why loses the part an
auditor needs), `notes` (how inputs were handled before the engine saw them), `repairs` (every
mechanical repair, disclosed — an undisclosed repair makes the manifest describe a file that
never existed), `parameters_redacted` (true when redaction changed anything: a record that
silently differs from what ran is a worse defect than the secret it protects), `producer`
(the emitting software, as distinct from the engine).

### 3.5 Extensions

Unknown fields are permitted everywhere; consumers MUST ignore fields they do not understand.
Producers adding their own fields SHOULD choose names unlikely to collide with future versions of
this specification (a producer prefix does this well). A field defined here MUST NOT be reused
with different semantics.

### 3.6 Check names: a closed core, and prefixed extensions

`verification[].name` is the field a consumer branches on, so it is the one field whose *values*
this specification constrains. Without that, two conforming records cannot be compared, and the
question an auditor actually asks — *does this system check X?* — has no mechanical answer.

**The core.** These names have fixed meaning. A producer that performs the corresponding check
MUST use the core name for it, and MUST NOT use a core name for anything else.

| name | passes when |
|---|---|
| `crs_present` | the output declares a coordinate reference system |
| `crs_matches` | the output's CRS is the one the operation was meant to produce |
| `geometry_valid` | no geometry in the output is invalid under OGC simple-features rules |
| `feature_count_exact` | the output's feature count equals a count derived before the operation ran |
| `feature_count_bounded` | the output's feature count respects a bound derived before the operation ran (e.g. a clip cannot grow) |
| `row_count_exact` | a tabular output's row count equals a count derived before the operation ran — the counterpart of `feature_count_exact` for records that carry no geometry |
| `result_not_empty` | the output contains at least one feature or one valid cell |
| `extent_within_expected` | the output's extent lies inside the extent the operation could produce |
| `shape_preserved` | a raster output has the same grid dimensions as its input |
| `values_in_expected_range` | every value in the output lies within a range the operation guarantees |
| `input_crs_present` | every input declares a coordinate reference system — a precondition, checked before the operation runs |
| `input_not_empty` | no input is empty — a precondition, and usually a warning rather than a failure |
| `inputs_share_crs` | the inputs are in the same coordinate reference system, so comparing them means something — a precondition, and the check whose absence from this list would have every producer naming it differently |
| `inputs_may_intersect` | the inputs' extents overlap, so an empty result would be a finding rather than the obvious outcome |
| `geometry_types` | the output's geometry types are the ones the operation produces |

The last four describe **preconditions** — checks on the inputs, before the operation. They are
in the core because the distinction between checking what you were given and checking what you
produced belongs to the format, not to one implementation.

A producer performing none of these is unusual but conforming: the core constrains *naming*, not
*behaviour*. What it forbids is calling a CRS check `check_1`, or calling something else
`crs_present`.

**Extensions.** Any other check MUST be named `x-<producer>:<name>` — for example
`x-mapsmith:no_invented_class_codes`. A name that is neither in the core nor prefixed is a
conformance error: without that rule the vocabulary becomes, one producer at a time, no
vocabulary at all.

The core is deliberately small. A check enters it only if an independent producer could
reasonably compute the same thing and mean the same by it; anything that depends on one
implementation's internals stays an extension, however useful.

### 3.7 `crs_decisions`: the shape

`crs_decisions` is where this format earns its keep, so its structure is specified rather than
left to each producer. It is an object; `analysis_crs` and `reason` are strings; other values may
be of any type. When a producer records a decision it SHOULD use these keys:

| key | holds |
|---|---|
| `analysis_crs` | the coordinate system the operation actually computed in |
| `reason` | why that system, in words a reader can check — naming the alternative rejected, where there was one |
| `source_crs` | the coordinate system the coordinates were in before the operation |
| `target_crs` | the coordinate system they were put into, when the operation transformed them |
| `transformation` | an object describing *how* they were transformed: `pipeline` (the operation string the engine used), `accuracy_m` (the transformation's stated accuracy in metres, or null when the engine states none), `is_ballpark` (true when no datum transformation was available and the engine fell back to treating the datums as equivalent) |

Additional keys are permitted under the extension rule above.

**Why the values are not all strings.** Until `1.0.0-draft.3` this field was declared "an object
of string values", which sounds harmless and is not: it makes the most consequential question a
consumer can ask unanswerable in a form a program can use. *Was this transformation a ballpark
one?* — a ballpark transformation is the engine saying "I have no datum shift for this pair, so I
will pretend the datums coincide", which on a NAD27-to-WGS84 pair is a hundred metres of error
delivered without a warning. With string-only values the answer could only be prose inside
`reason`, and prose is what section 7 faults other formats for. **`is_ballpark` is a boolean
because a consumer has to be able to branch on it.**

Two things this field is not: a place for the output CRS (that belongs in `output`), and a place
for a CRS name with no justification. *"Reprojected to EPSG:32632"* records the what and loses the
why, which is the half that cannot be recovered from the data afterwards.

### 3.8 `environment`: the configuration that changed the answer

RECOMMENDED. An object of strings holding the configuration that influenced the result and lives
neither in the data nor in the call: `PROJ_NETWORK`, the `GDAL_*` variables that change how a
dataset is read, a project-level ellipsoid or datum setting, `AREA_OR_POINT`, the presence or
absence of a datum grid on the machine.

**Why a field of its own.** `parameters` holds the parameters of the operation — what the caller
asked for. `engine` holds what computed it. Neither holds the state of the machine, and that state
can change the number: the same thousand-metre square measures 1,000,530.603 m² or exactly
1,000,000 m² depending on a project setting that appears in no argument and no output. A record
that omits it describes a computation nobody can reproduce while looking complete, which is the
failure mode this format exists to remove.

The principle, and it is the shortest statement of what a manifest is for: **the correct answer is
not a number, it is this number with this configuration.**

A producer records what it knows influenced the result; it is not required to dump the
environment. An empty or absent `environment` claims nothing, exactly like an absent
`crs_decisions`.

## 4. Conformance

**A conforming record** validates against the schema and satisfies the semantic rules a schema
cannot express: `finished_at >= started_at`, and every `verification[].name` is either a core name
from §3.6 or carries an `x-<producer>:` prefix.

**A conforming producer** emits a conforming record for every dataset it writes, including
failed runs.

**A conforming consumer** accepts any conforming record, ignores unknown fields, and does not
require any recommended field.

The [`conformance/`](../conformance/) directory holds records that MUST validate and records that
MUST be rejected, each rejection with its expected reason. A validator that disagrees with that
directory is wrong, whoever wrote it — including us. The standalone validator in
[`validator/`](../validator/) implements this specification with no dependencies; the schema and
the validator are independent implementations, kept in agreement by a conformance suite that
mutates every field the schema declares and requires **both** to reject it.

## 5. Versioning

Semantic versioning on the specification itself. Within major version 1: adding optional fields
is a minor bump; clarifying prose without changing meaning is a patch; anything that makes a
previously conforming record non-conforming is a new major version. `spec_version` in each record
names what the producer targeted; the schema for major version 1 accepts any `1.x.y`.

**Before `1.0.0` final, the pre-release label carries the tightenings.** A draft may narrow what
conforms — that is what a draft is for — and every narrowing MUST change the label: `draft.2` →
`draft.3`. This rule exists because it was broken: section 3.6 closed the check-name vocabulary
under an unchanged `draft.2`, so a record that conformed one day did not the next and carried no
version to say so. A reader of a draft is entitled to know that the draft moved under them.

## 6. What is deliberately out of scope

- **Chaining and graphs.** A manifest describes one operation. Multi-step lineage is expressible
  by pointing an input's `path` at a dataset that has its own manifest; a dedicated plan-level
  format may standardise more later, informed by use.
- **Signatures and attestation.** Integrity of the manifest itself is a transport and storage
  concern; formats exist for it and this one composes with them rather than duplicating them.
- **Semantics of operations.** What `watershed` means is between the producer and its
  documentation; this format records that it happened, with what, and what was checked.

## 7. Prior art, and why this format exists anyway

The right first question about a new format is "why not the existing one?", so here is the
honest survey (full census with sources: the reference implementation's research notes). The
case to cover: a file beside the output, checkable offline, with input digests and
verification checks recorded pass or fail.

| neighbour | what it has | why it does not cover the case |
|---|---|---|
| **W3C PROV** (PROV-JSON / PROV-JSONLD) | the provenance vocabulary | both JSON serialisations are Member Submissions (2013, 2024), not Recommendations; the Entity/Activity/Agent graph has no native place for content digests or pass/fail checks, and a minimal emitter is far from a hundred lines |
| **STAC** + `processing` extension | the geospatial cataloguing world | `processing:lineage` is **free text** ("free text information about how observations were processed", v1.2.0); parameters, input digests and checks have no structured home |
| **OpenLineage** | the closest thing to `verification[]` (the `dataQualityAssertions` facet) | an event stream to a backend, not a file beside the output; datasets are identified by namespace and name, **not by content digest** |
| **in-toto attestations** | subject and materials with sha256 digests, huge adoption | built for software supply chains: no operation semantics, no CRS, no verification checks — it is a wrapper, not a record (and a good wrapper: §8) |
| **ISO 19115 / OGC lineage** | the formal geographic-metadata lineage model | XML lineage historically; recent OGC testbed work demonstrates provenance in OGC API — Processes and itself concludes that consistent guidance is missing |

Nothing in the Model Context Protocol space covers this either; the question has been asked
there and is open. If any of these grows to cover the case, the right move is to adopt it and
retire this document — that is what the draft label is for.

## 8. Composing with the neighbours

This format is designed to sit **inside** the adjacent standards rather than compete with them.

**in-toto**: a manifest becomes the `predicate` of an in-toto Statement; the Statement's
`subject` is the output dataset with the same sha256 the manifest's `output` field carries, and
`predicateType` is a versioned URI naming this specification. That is the upgrade path to signed
provenance: nothing in the record changes, it gains an envelope.

**STAC**: a STAC Item SHOULD reference the manifest as an asset
(`"roles": ["metadata"]`), placing a checkable record behind a catalogue entry whose own
`processing:lineage` remains prose. The `file:checksum` of the output asset (Multihash) and the
manifest's `output.sha256` describe the same bytes in two encodings; consumers can cross-check.

## Licence

This document: CC-BY-4.0. The schema, validator, conformance fixtures and examples: Apache-2.0.
