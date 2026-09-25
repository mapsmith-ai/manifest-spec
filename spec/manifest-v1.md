# Provenance manifests for geospatial datasets — v1.0.0-draft.7

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

**`output`** — the `path` and `sha256` of the dataset this record sits beside, and since
`1.0.0-draft.4` its `crs`. Without the digest, a consumer cannot verify that the sidecar describes
the bytes next to it, and the record cannot be wrapped in an in-toto attestation (whose `subject`
requires a digest — see §8). Recommended rather than mandatory only because a producer may emit
the manifest before the output is durably on disk; when the digest can be computed, it SHOULD be.

**`output.crs`** — the coordinate reference system the written dataset declares, when it has one.
Section 3.7 has said since `1.0.0-draft.2` that the output CRS belongs here rather than among the
CRS decisions, and until `draft.4` there was nowhere here to put it: producers put it in
`crs_decisions` instead, where it is a claim about a file made by code that has not yet written
one, and therefore false on every path that fails between the decision and the write. A producer
that cannot compute it — because the write has not happened — SHOULD omit it rather than predict
it.

**Optional fields of the mandatory objects.** The schema has carried these since `1.0.0-draft.3`,
and until this paragraph was added — after `draft.6` was tagged — the prose did not describe
them, so a producer reading it alone would not emit them and a consumer would not know what their
absence means. It is a clarification in the sense of §5: no record's conformance moves, because
the schema already said all of it.

| field | holds |
|---|---|
| `verification[].critical` | boolean: whether a failure of this check should have stopped the pipeline. **Absent means the producer makes no claim about severity** — not that the check is minor (§6 says what a consumer may not conclude from that silence) |
| `verification[].hint` | string or null: what to do about a failure, for the reader who has to act on it |
| `verification[].argument` | string or null: which input or parameter the check is about. Without it, one check run on two inputs produces two identically named entries that a consumer indexing by name collapses into one |
| `inputs[].crs` | string or null: the input's coordinate reference system as a short label (e.g. `EPSG:32610`), null when it declares none. A label, not an identity: a consumer comparing coordinate systems compares the systems, not the spellings |

`crs_decisions` (each decision **with its reason** — the what without the why loses the part an
auditor needs), `notes` (how inputs were handled before the engine saw them), `repairs` (every
mechanical repair, disclosed — an undisclosed repair makes the manifest describe a file that
never existed), `parameters_redacted` (true when redaction changed anything: a record that
silently differs from what ran is a worse defect than the secret it protects), `producer`
(the emitting software, as distinct from the engine).

**The shape of a `repairs` entry, new in `1.0.0-draft.5`.** Until then this field was declared
`type: object` and nothing more, so two producers disclosing the same repair could share no key
and both conform — which is disclosure a consumer cannot read. A producer that records a repair
MUST use these names for these meanings, and MUST NOT use them for anything else; other keys are
permitted under section 3.5 and SHOULD carry a producer prefix.

| key | meaning |
|---|---|
| `action` | **REQUIRED.** What was done, in the producer's own words. Nullable, and the null is load-bearing: it says a repair was attempted and achieved nothing, with `error` saying why. An *absent* `action` cannot be told apart from a producer that did not record one, and an entry that does not say what was done discloses nothing |
| `check` | which check the repair was made for, named as in `verification[].name`. It MAY name a check that appears in no entry of `verification[]` — a repair applied to an **input** happens before anything is verified, so this name is the only thing a consumer has to look it up by |
| `error` | why the repair failed, when it did |
| `resolved` | whether the check passed afterwards. `false` beside a non-null `action` is the case worth reading: something was changed and the problem remained |

This is the same argument as section 3.6 one field over. `repairs` is a field a consumer branches
on — *was this geometry altered before it was measured?* — and a field whose values cannot be
compared across producers answers that question for no one.

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
left to each producer. It is an object; `analysis_crs` and `reason` are strings; `source_crs`
and `target_crs` are strings or null; `transformation` and `round_trip` are objects of the shapes
defined below; keys this section does not define may hold values of any type. When a producer
records a decision it SHOULD use these keys:

| key | holds |
|---|---|
| `analysis_crs` | the coordinate system the operation actually computed in |
| `reason` | why that system, in words a reader can check — naming the alternative rejected, where there was one |
| `source_crs` | the coordinate system the coordinates were in before the operation |
| `target_crs` | the coordinate system they were put into, when the operation transformed them |
| `transformation` | an object describing *how* they were transformed: `pipeline` (the operation string the engine used, or null when it reports none), `accuracy_m` (the transformation's stated accuracy in metres, or null when the engine states none), `is_ballpark` (true when no datum transformation was available and the engine fell back to treating the datums as equivalent), `better_available_m` (see below) |
| `round_trip` | when the operation computed in `analysis_crs` and wrote its output back in the caller's CRS: an object with two legs, `transformation` (the caller's CRS to `analysis_crs`) and `return_transformation` (`analysis_crs` back to the caller's CRS), each of the same shape as `transformation` above (see below) |

**Any other key MUST be named `x-<producer>:<name>`**, in the grammar of an extension check name
(§3.6). New in `1.0.0-draft.7`. Until then this sentence permitted additional keys "under the
extension rule above", which could be read as §3.5 — a SHOULD with no syntax — or as §3.6 — a
MUST with one; the reference implementation applied the second, and an emitter reading only this
document had no reason to. This is the field where a consumer asks *which of these keys are the
format's?*, and without a fixed prefix the answer is one producer at a time, which is no answer.

**`round_trip`, and the two rules that come with it.** An operation that needs metres on a layer
in degrees computes somewhere else and hands back its output in the CRS it was given. The trip is
not free: an estimated UTM zone is usually on WGS 84 whatever the input's datum is, so a layer on
NAD27 crosses a datum on the way out and again on the way back — metres each way, which largely
cancel over one feature, which is why nobody sees them. A record that says nothing about the trip
leaves the reader to assume it did not happen. New in `1.0.0-draft.6`.

*The legs are two, and each is measured.* They are different records even on the simplest pair
there is: from WGS 84 to a UTM zone on WGS 84 the outbound leg is the projection and the return
leg is its *inverse*, so a copy of the outbound record would name the wrong operation. Across a
datum change the engine may also choose the operation per coordinate rather than per pair, which
makes the reverse leg something to ask the engine about rather than to assume. A producer MUST
record each leg as the engine reports it for that direction, and MUST NOT derive one from the
other.

*The name is fixed.* A producer that records this fact MUST use `round_trip` and MUST NOT record
it under a prefixed extension name — for the reason section 3.6 gives for check names: a fact two
producers name differently is two facts to a consumer.

*The moment is fixed.* `round_trip` MUST be written only once the output is back in the caller's
CRS. A record written on a failing path — which section 3.1 requires when verification fails,
and which a producer may also write when the run fails before verifying — MUST NOT carry
`round_trip` for a trip that did not complete. This rule is here because the reference
implementation broke it: it built the key before the return leg ran, and a return leg that raised
produced a record asserting a round trip that never finished. The failure record survived the
error, as it must; the sentence inside it had become false. Where the output ended up is
`output.crs`, not a field of this object — see the last paragraph of this section.

*How much of this a validator can check, which is less than the three rules suggest.* The shape
it can: both legs present, each of the shape of `transformation`. Of the name rule it checks one
spelling, `x-<producer>:round_trip`, which is the likeliest way to break it — a producer that did
not migrate — and not the rule itself, since the same fact under an unrelated name is not
something a program can recognise. That a leg was measured rather than derived, no validator can
see. And the moment rule it cannot check at all: a record cannot show whether the trip it
describes finished, because the output can come home and the run still fail afterwards — a write
that raises once the coordinates are back — and then `round_trip` is true and belongs in the
record. So a failed run carrying `round_trip` is not evidence of a violation, and a passing
validator is not evidence of compliance. This is said so that nobody reads the conformance suite
as covering these rules; the reference implementation tests the moment at the point where the trip
happens.

**`better_available_m`, and the difference it is the only field that carries.** When
`is_ballpark` is true and a published operation for this pair nevertheless exists, this holds that
operation's stated accuracy in metres; otherwise it is absent or null. The distinction it draws is
the one an operator acts on. *There is no datum transformation for this pair* and *there is one,
and this machine has not got the grid file* are different problems with different fixes: the first
is a fact about the world and the second is a download. Without this field a record cannot tell
them apart, and a consumer reading `is_ballpark: true` has no way to know whether the hundred
metres were unavoidable or merely uninstalled. New in `1.0.0-draft.4`, optional, and the only
field in this format whose value is about what the environment is *missing* rather than about what
it did.

**Why the values are not all strings.** Until `1.0.0-draft.3` this field was declared "an object
of string values", which sounds harmless and is not: it makes the most consequential question a
consumer can ask unanswerable in a form a program can use. *Was this transformation a ballpark
one?* — a ballpark transformation is the engine saying "I have no datum shift for this pair, so I
will pretend the datums coincide", which on a NAD27-to-WGS84 pair is a hundred metres of error
delivered without a warning. With string-only values the answer could only be prose inside
`reason`, and prose is what section 7 faults other formats for. **`is_ballpark` is a boolean
because a consumer has to be able to branch on it.**

Two things this field is not: a place for the output CRS (that belongs in `output.crs`, which
exists since `1.0.0-draft.4` -- until then this sentence named a field that had not been
built, and producers put the value here instead), and a place
for a CRS name with no justification. *"Reprojected to EPSG:32632"* records the what and loses the
why, which is the half that cannot be recovered from the data afterwards.

### 3.8 `environment`: the configuration that changed the answer

RECOMMENDED. An object of strings holding the configuration that influenced the result and lives
neither in the data nor in the call: `PROJ_NETWORK`, the `GDAL_*` variables that change how a
dataset is read, a project-level ellipsoid or datum setting, the presence or absence of a datum
grid on the machine.

`AREA_OR_POINT` was in that list until a clarification after `draft.6`, and did not belong: it is
a tag **inside** the raster, so it is data, and the definition above excludes it. What a producer
concludes from it — whether a value describes a cell or a point at its centre — is a decision
about where the values sit, and goes in `crs_decisions` under an `x-<producer>:<name>` key (§3.7).

**Why a field of its own.** `parameters` holds the parameters of the operation — what the caller
asked for. `engine` holds what computed it. Neither holds the state of the machine, and that state
can change the number: the same thousand-metre square measures 1,000,530.603 m² or exactly
1,000,000 m² depending on a project setting that appears in no argument and no output. A record
that omits it describes a computation nobody can reproduce while looking complete, which is the
failure mode this format exists to remove.

The principle, and it is the shortest statement of what a manifest is for: **the correct answer is
not a number, it is this number with this configuration.**

**This is demonstrated, not asserted.** Run
[`examples/environment_changes_the_answer.py`](../examples/environment_changes_the_answer.py) —
`rasterio` and nothing else, no network, one file. It writes a GeoTIFF whose own georeferencing
puts it at (500000, 5030000) with 10 m pixels, and beside it a `.aux.xml` sidecar claiming
(600000, 5040000) with 20 m pixels. Then it opens the raster three times, changing nothing but the
process environment:

| environment | area | origin |
|---|---|---|
| default | **1600 m²** | 600000, 5039960 |
| `GDAL_PAM_ENABLED=NO` | **400 m²** | 500000, 5029980 |
| `GDAL_GEOREF_SOURCES=INTERNAL` | **400 m²** | 500000, 5029980 |

A factor of four in area and a hundred kilometres in position, from one file and one line of code.
**None of the three runs says which georeferencing it used.**

And it is not a bug to be fixed somewhere else: GDAL's documented precedence puts the sidecar ahead
of the file's own georeferencing on purpose, because a sidecar is how a user overrides
georeferencing they know to be wrong. Both answers are the library behaving as documented. That is
what makes this a field in a record rather than an issue in a tracker — there is nothing to fix,
and everything to state.

A producer records what it knows influenced the result; it is not required to dump the
environment. An empty or absent `environment` claims nothing, exactly like an absent
`crs_decisions`.

## 4. Conformance

**A conforming record** validates against the schema and satisfies the rule the schema cannot
express, `finished_at >= started_at`. Two naming rules are part of the schema and are worth
stating because a consumer branches on them: every `verification[].name` is a core name from §3.6
or carries an `x-<producer>:` prefix, and so, since `1.0.0-draft.7`, does every key of
`crs_decisions` that §3.7 does not define.

**A conforming producer** emits a conforming record for every dataset it writes, including
failed runs.

**The `conformance/` directory cannot prove that sentence, and says so.** It validates records;
whether a producer leaves a dataset with no record beside it is a property of the producer, and
the only way to see it is to run the producer and make it fail. Every record a producer emits can
conform while the producer does not: on 2026-09-25 the reference implementation had 28 of 58
writers doing exactly that, and no validator could have noticed. A producer tests the sentence on
itself this way: for every operation that writes, inject a failure **after the output's bytes
reach the disk** — once in the write itself, once after it — and require, beside every dataset
that failure leaves, a record that says the run did not complete. A sabotage that never fires
proves nothing, so the test fails when it does not. MapSmith's
[`tests/test_failure_manifest.py`](https://github.com/mapsmith-ai/MapSmith/blob/main/tests/test_failure_manifest.py)
is one such test, deriving the operations from its own catalogue.

**A conforming consumer** accepts any conforming record, ignores unknown fields, and does not
require any recommended field. **A consumer that walks a chain of records has two further
obligations, and they are in §6** — read `verification[]` on every hop, and track the ancestors
of the path currently being descended. They are stated there because that is where the walk is
described, and they are pointed at from here because a section titled "what is deliberately out
of scope" is not where an implementer goes looking for requirements. That is not hypothetical:
the first walker written against this document skipped both readings of the first obligation.

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

**The schema declares which version it is**, in `x-spec-version` at its top level. An
unknown keyword there is ignored by every JSON Schema validator, and the field exists because a
schema file travels alone: it gets vendored into a consumer's test fixtures, attached to a bug
report, pinned in a lockfile. Until `1.0.0-draft.3` a reader holding the file could not tell
which draft it was -- the `spec_version` rule inside it accepts any `1.x.y` on purpose, so the
document said nothing about itself. A consumer can now compare the label of the schema it
vendored against the label in the records it receives, which is the comparison that catches a
stale copy.

**Before `1.0.0` final, the pre-release label carries the tightenings.** A draft may narrow what
conforms — that is what a draft is for — and every narrowing MUST change the label: `draft.2` →
`draft.3`. This rule exists because it was broken: section 3.6 closed the check-name vocabulary
under an unchanged `draft.2`, so a record that conformed one day did not the next and carried no
version to say so. A reader of a draft is entitled to know that the draft moved under them.

**And the rule applies to what is READABLE, not only to what is tagged.** `draft.5` fixes the
shape of a `repairs` entry, which narrows what conforms; `draft.4` had never been tagged or
archived when that narrowing was written, so the label could have absorbed it unnoticed. It did
not, because this repository is public: a consumer who vendored the schema from the default
branch holds a file whose `x-spec-version` says `draft.4`, and redefining `draft.4` underneath
that copy is precisely the failure of the preceding paragraph, with a shorter fuse. A label is
spent the moment it is published, and pushing is publishing.

**The rules above are written about records, and that is not everything this document
constrains.** Section 6 places a requirement on a *consumer* walking a chain, and no rule here
covered that case until one arose. The line: a requirement on producers or on the shape of a
record follows the paragraphs above; a requirement on consumers does not move the label, because
no record that conformed stops conforming and no producer has to change anything. What it does
require is that the requirement be new text rather than a reinterpretation of old text — a
consumer rule discovered inside an existing sentence is the same trap as a narrowing under an
unchanged label, wearing the other hat.

## 6. What is deliberately out of scope

- **Chaining and graphs.** A manifest describes one operation, and no field of this format points
  at another record. Multi-step lineage does not need one: it is recovered from the digests that
  are already there. Hash the file in hand, find the manifest whose `output.sha256` is that
  digest — that is the operation that produced these exact bytes — then take each of its
  `inputs[].sha256` and repeat. The walk ends at a digest no manifest claims.

  The link is by **content**, not by name, and that is deliberate: a path can be renamed, copied
  or reused by a later run, while a digest either matches the bytes or does not. A field pointing
  at the upstream *record* would be weaker in both directions — it would break when a record is
  reformatted or re-emitted, which is not a change to the lineage, and it would let a record
  assert its own ancestry rather than be found because it accounts for bytes that exist.

  Three limits, stated because a reader will meet all three.

  **A found hop is not a successful hop.** Section 3.1 REQUIRES a manifest even when verification
  fails, so the records a walk meets include runs that did not finish. A run that crashed after
  writing part of its output leaves a conforming record carrying the digest of those partial
  bytes, and the walk resolves it like any other: the record is accurate — that operation really
  did produce exactly those bytes — and it is not a history anyone should repeat. **A walker MUST
  read `verification[]` on every hop it resolves** and MUST NOT present a failed run as
  provenance without saying so. This is the limit most likely to be missed, because the format
  guarantees such records exist and nothing about a digest hints that one is unsound.

  And there is a second reading of the same sentence that has to be closed, because the first
  walker written against this section got it wrong. `critical` is OPTIONAL, and §3.4 says its
  absence means the producer makes no claim about severity. **A walker MUST NOT treat a failed
  check that carries no `critical` as a non-critical one.** Silence is not reassurance: of the
  three things absence could mean — not serious, serious, nobody decided — reading it as the
  first is the only one the producer did not say, and it is the one that turns a record
  announcing a failure into a clean bill of health. A walker may report such a check as being of
  undeclared severity, or as critical; it may not report the hop as sound. The correctness of
  this is easy to check and easy to get wrong in a way no test notices, which is why it is a MUST
  and not advice: `critical` is written by producers that care about the distinction and omitted
  by every producer that does not, so the records where it is missing are exactly the records
  written by the least careful producers.

  **The chain reaches only as far as producers recorded `output`**, which is RECOMMENDED and not
  REQUIRED for the reason §3.4 gives: a manifest may be emitted before the output is durably on
  disk, which is also what happens when a run dies before writing anything. Such a record has no
  digest to be found by, so a walk reports where it stopped instead of claiming a complete
  history. A producer whose operations answer questions without writing datasets is outside this
  entirely — it has no output to sit beside and emits no manifest at all.

  **An operation can point at itself.** Where the output is byte-identical to the input — a copy,
  a conversion that changes nothing, a reprojection to the CRS the data already had — the record's
  `output.sha256` equals one of its own `inputs[].sha256`, and following that link returns to the
  same record forever. **A walker MUST therefore track the digests of the ancestors on the path it
  is currently descending** and stop when one repeats. Ancestors on the *current path*, not every
  digest ever visited: a lineage that rejoins — two branches sharing an upstream dataset — is
  ordinary, and a global visited set would silently prune the second branch, turning a hang into
  a quieter wrong answer. That a cycle can occur is not a defect in the record, which is accurate:
  content addressing identifies data and not events, and when two events leave the data identical
  the bytes cannot tell them apart.

  `examples/chain_resolves_by_digest.py` is the walk in about twenty lines of standard library,
  and the conformance suite runs it. A dedicated plan-level format may standardise more later,
  informed by use.
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
