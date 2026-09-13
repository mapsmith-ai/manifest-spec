"""The demonstration behind section 6: two manifests, one chain, no new field.

Run it. It needs nothing but the standard library, it touches no network, and it
prints a two-step lineage resolved from a single output file.

    python examples/chain_resolves_by_digest.py

WHY THIS EXISTS, and it is not a happy reason. Section 6 has said since draft.1
that multi-step lineage is "expressible by pointing an input's `path` at a
dataset that has its own manifest". That sentence was never demonstrated: on
2026-09-13 a count of every record shipped with this specification found
twenty-six of them, two carrying an output digest, and **zero** where one
record's output was another record's input. A claim of composability that
nothing exercises is a claim no reader can check and no change can break, which
is the failure mode this specification was written to make harder.

WHAT IT DOES. It writes three files -- a source, an intermediate, and a final --
emits a conforming manifest beside each of the last two using the reference
emitter, and then throws away everything except the final file. From those bytes
alone it rebuilds the lineage.

HOW THE WALK WORKS, and this is the whole point: the chain is followed by
CONTENT, not by name and not by a pointer between records.

    1. hash the file you hold
    2. find the manifest whose `output.sha256` is that digest -- that is the
       operation that produced these exact bytes
    3. for each of its `inputs`, take the `sha256` and go back to step 2
    4. stop where no manifest claims the digest: that is an original

A path can be renamed, copied, or reused by a later run. A digest cannot: it
either matches the bytes or it does not. So the link survives everything except
the one event that should break it -- the data changing.

WHY NOT A FIELD POINTING AT THE UPSTREAM MANIFEST, which is the obvious design
and is worse. A record can be regenerated, reformatted, or re-emitted by a
different producer, and any of those changes its digest while the data it
describes is untouched; the link would break on an event that is not a change to
the lineage. Worse, it would let a record ASSERT its own ancestry. Under the walk
above nothing is asserted: the upstream manifest is found because it accounts for
bytes that exist, or it is not found at all.

WHAT IT PRINTS, and the digests are stable because the bytes are fixed:

    final.txt
      <- transform            8fe5b289...  final.txt
         <- terminate            b96fe937...  middle.txt
            <- (unresolved: nothing claims these bytes) 38939c41...

THE HONEST LIMITS, and section 6 lists all three. Two of them show up here.

The link exists only where the upstream producer recorded `output`, which is
RECOMMENDED and not REQUIRED: a manifest may be emitted before the output is
durably on disk, which is also what a run that died before writing leaves
behind. So a walk reports where it stops rather than claiming a complete
history -- `unresolved` above is not an error, it is the only honest thing to
print. Here it marks `source.txt`, which nothing produced.

And a resolved hop is not a successful hop. Section 3.1 requires a manifest even
when verification fails, so a run that crashed after writing part of its output
leaves a conforming record carrying the digest of those partial bytes, and this
walk finds it like any other. The record is accurate and the history is not one
to repeat. A real consumer reads `verification[]` on every hop; this example
does not, because every record it writes passes, and pretending otherwise in a
file people copy would teach the wrong shape. Section 6 carries the requirement.
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emitter_minimal import _utcnow, emit_manifest

ENGINE = {"name": "stdlib", "version": ".".join(str(n) for n in sys.version_info[:3])}
PASSED = [{"name": "result_not_empty", "passed": True, "detail": "1 byte or more"}]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_by_output(directory: Path) -> dict[str, dict]:
    """Every manifest in `directory`, keyed by the digest of the bytes it describes.

    A record with no `output` is skipped, not rejected: it is valid and simply
    cannot be an answer to "what produced these bytes".
    """
    by_digest: dict[str, dict] = {}
    for manifest in sorted(directory.glob("*.provenance.json")):
        record = json.loads(manifest.read_text(encoding="utf-8"))
        digest = (record.get("output") or {}).get("sha256")
        if digest:
            by_digest[digest] = record
    return by_digest


def walk(
    digest: str, by_digest: dict[str, dict], depth: int = 0, seen: frozenset = frozenset()
) -> list[tuple]:
    """The four steps from the docstring, plus the one guard they need.

    Returns one row per hop: (depth, operation-or-None, digest, path). A row
    whose operation is None is where the walk stopped -- an original that no
    manifest claims, an upstream whose producer recorded no output digest, or
    the cycle described below. All three are reported rather than guessed at.

    THE GUARD, and it was not in the first draft of this file: an operation
    whose output is byte-identical to its input -- a copy, a format conversion
    that changes nothing, a reprojection to the CRS the data already had --
    produces a record whose `output.sha256` equals one of its own
    `inputs[].sha256`. Following that link returns to the same record, forever.
    The first run of this example died in a RecursionError at depth 998, which
    is a better way to learn it than a reader hitting it in production.

    It is worth being precise about whose defect this is. The record is correct:
    those really are the bytes in and the bytes out. What is undecidable is the
    QUESTION, because content addressing identifies data and not events, and
    when two events leave the data identical there is nothing in the bytes to
    tell them apart. A walker either carries this guard or hangs.

    `seen` holds the ancestors of the CURRENT path, not every digest the walk has
    ever touched, and the difference is not a detail. A lineage that rejoins --
    two inputs derived from one upstream dataset -- is ordinary; a global visited
    set would skip the second branch and print a shorter history with no sign
    that anything was dropped, which trades a hang for a quiet wrong answer.
    """
    record = by_digest.get(digest)
    if record is None:
        return [(depth, None, digest, None)]
    if digest in seen:
        return [(depth, None, digest, None)]
    rows = [(depth, record["operation"], digest, (record.get("output") or {}).get("path"))]
    for upstream in record.get("inputs") or []:
        rows.extend(walk(upstream["sha256"], by_digest, depth + 1, seen | {digest}))
    return rows


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)

        source = directory / "source.txt"
        source.write_bytes(b"48.8583,2.2945\n")

        middle = directory / "middle.txt"
        middle.write_bytes(source.read_bytes().replace(b"\n", b";\n"))
        emit_manifest(
            output=middle,
            operation="terminate",
            parameters={"terminator": ";"},
            inputs=[source],
            engine=ENGINE,
            checks=PASSED,
            started_at=_utcnow(),
        )

        final = directory / "final.txt"
        final.write_bytes(middle.read_bytes().replace(b",", b" "))
        emit_manifest(
            output=final,
            operation="transform",
            parameters={"separator": " "},
            inputs=[middle],
            engine=ENGINE,
            checks=PASSED,
            started_at=_utcnow(),
        )

        # From here on, pretend the only thing anyone kept is `final`. Nothing
        # below reads a filename to decide what came before it.
        by_digest = index_by_output(directory)
        rows = walk(sha256(final), by_digest)

        print(final.name)
        for depth, operation, digest, path in rows:
            indent = "   " * depth
            label = operation if operation else "(unresolved: nothing claims these bytes)"
            # The basename, not the recorded path: this runs in a temporary
            # directory and the CI log of this repository is public.
            name = Path(path).name if path else ""
            print(f"  {indent}<- {label:20} {digest[:8]}...  {name}".rstrip())

        operations = [operation for _, operation, _, _ in rows if operation]
        if operations != ["transform", "terminate"]:
            print(f"\nFAIL: the chain did not resolve; got {operations}", file=sys.stderr)
            return 1
        print("\nTwo hops resolved from one file, by content, with no field added.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
