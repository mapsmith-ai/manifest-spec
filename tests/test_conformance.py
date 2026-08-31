"""The conformance suite is the referee between the two implementations.

The JSON Schema is the normative contract; the standalone validator re-states it
in plain Python. Independence is the point — one toolchain-free, one usable by
any jsonschema implementation in any language — and drift is the risk. These
tests run every fixture through BOTH: a record that one accepts and the other
rejects is a bug in one of them, and the failure says which.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "validator"))
from validate import problems  # noqa: E402

SCHEMA = json.loads((ROOT / "schema" / "manifest-v1.schema.json").read_text(encoding="utf-8"))
VALID = sorted((ROOT / "conformance" / "valid").glob("*.json"))
INVALID = sorted(
    p for p in (ROOT / "conformance" / "invalid").glob("*.json") if p.name != "expected.json"
)
EXPECTED = json.loads(
    (ROOT / "conformance" / "invalid" / "expected.json").read_text(encoding="utf-8")
)

# The one class of rule a schema cannot express: relations between two fields.
# Everything else must be caught by BOTH implementations.
SEMANTIC_ONLY = {"finished-before-started.json"}


def _schema_errors(record: dict) -> list[str]:
    jsonschema = pytest.importorskip("jsonschema")
    checker = jsonschema.Draft202012Validator(SCHEMA)
    return [error.message for error in checker.iter_errors(record)]


def test_the_suite_is_not_vacuous():
    assert len(VALID) >= 5 and len(INVALID) >= 10
    assert set(EXPECTED) == {p.name for p in INVALID}, (
        "every invalid fixture needs its expected reason, and no reason may be orphaned"
    )


@pytest.mark.parametrize("fixture", VALID, ids=lambda p: p.stem)
def test_valid_fixtures_conform_in_both_implementations(fixture: Path):
    record = json.loads(fixture.read_text(encoding="utf-8"))
    assert problems(record) == []
    assert _schema_errors(record) == []


@pytest.mark.parametrize("fixture", INVALID, ids=lambda p: p.stem)
def test_invalid_fixtures_are_rejected_for_the_expected_reason(fixture: Path):
    record = json.loads(fixture.read_text(encoding="utf-8"))
    found = problems(record)
    assert found, f"{fixture.name}: the validator accepted a record that must be rejected"
    reason = EXPECTED[fixture.name]
    assert any(reason.lower() in f.lower() for f in found), (
        f"{fixture.name}: rejected, but not for the expected reason {reason!r}: {found}"
    )
    if fixture.name not in SEMANTIC_ONLY:
        assert _schema_errors(record), (
            f"{fixture.name}: the schema accepted a record the validator rejects — "
            "the two implementations have drifted"
        )


def test_semantic_only_rules_are_declared_not_discovered():
    """A fixture the schema accepts must be LISTED as semantic-only, so a schema
    that silently weakens shows up as a failure here rather than as a gap."""
    for fixture in INVALID:
        record = json.loads(fixture.read_text(encoding="utf-8"))
        schema_catches = bool(_schema_errors(record))
        if fixture.name in SEMANTIC_ONLY:
            assert not schema_catches, (
                f"{fixture.name}: listed as semantic-only but the schema now catches it — "
                "remove it from the list"
            )
        else:
            assert schema_catches, f"{fixture.name}: only the validator catches this"


def test_the_minimal_emitter_emits_conforming_records(tmp_path):
    """The proof the format is not one product's output: a stdlib-only producer
    whose records pass the same gate as everyone else's."""
    run = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "emitter_minimal.py")],
        capture_output=True, text=True, timeout=60, check=True,
    )
    manifest = Path(run.stdout.strip())
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert problems(record) == []
    assert _schema_errors(record) == []
    assert record["verification"][0]["passed"] is True



def test_the_minimal_emitter_can_carry_the_recommended_fields(tmp_path):
    """The two fields draft.3 exists for, emitted by the reference producer.

    The demo in `emitter_minimal.py` copies bytes: it has no CRS decision and no
    configuration that could change its answer, so passing it either field would
    be a lie in the one artefact implementers copy. The parameters still need a
    test, because a parameter nothing exercises is how a field that "exists"
    turns out not to work.
    """
    import sys

    sys.path.insert(0, str(ROOT / "examples"))
    from emitter_minimal import emit_manifest

    source = tmp_path / "in.bin"
    source.write_bytes(b"twenty bytes exactly")
    target = tmp_path / "out.bin"
    target.write_bytes(source.read_bytes())

    manifest = emit_manifest(
        output=target,
        operation="reproject_layer",
        parameters={"target_crs": "EPSG:4326"},
        inputs=[source],
        engine={"name": "demo", "version": "1"},
        checks=[{"name": "crs_present", "passed": True, "detail": "EPSG:4326"}],
        started_at="2026-08-26T10:00:00Z",
        crs_decisions={
            "analysis_crs": "EPSG:4326",
            "reason": "the question is in degrees",
            "source_crs": "EPSG:4267",
            "target_crs": "EPSG:4326",
            "transformation": {
                "pipeline": "+proj=noop",
                "accuracy_m": None,
                # The case the field exists for: no datum shift was available.
                "is_ballpark": True,
            },
        },
        environment={"PROJ_NETWORK": "OFF", "PROJ_DATA": "/usr/share/proj"},
    )
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert problems(record) == []
    assert _schema_errors(record) == []
    # The point of the whole change: a consumer can branch on this.
    assert record["crs_decisions"]["transformation"]["is_ballpark"] is True
    assert record["environment"]["PROJ_NETWORK"] == "OFF"

def test_the_cli_exit_codes_mean_what_they_say(tmp_path):
    ok = subprocess.run(
        [sys.executable, str(ROOT / "validator" / "validate.py"), str(VALID[0])],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert ok.returncode == 0
    bad = subprocess.run(
        [sys.executable, str(ROOT / "validator" / "validate.py"), str(INVALID[0])],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert bad.returncode == 1

# ---------------------------------------------------------------------------
# The direction the suite was missing until 2026-08-26.
#
# Everything above starts from a fixture the VALIDATOR rejects and asks whether
# the schema agrees. Nothing asked the opposite, so twelve ways of writing a
# record that the schema rejects and the validator accepts sat there unseen —
# all of them on the RECOMMENDED fields, which the validator simply did not
# look at. The claim at the top of this file was false about its own subject,
# which is the worst place for a claim to be false in a project that sells
# verifiability.
#
# The fix is generative rather than three more fixtures: the mutations are
# DERIVED from the schema, so the day a field is added to the format this test
# starts checking it without anyone remembering to. Three fixtures would have
# closed the three cases we happened to notice.

_MISSING = object()

# Ordered so the first candidate whose JSON type is not allowed wins. Every
# JSON type appears, so a wrong value exists for any declared type.
_WRONG_CANDIDATES = ({}, [], "a-string", 12345, True, None)


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"  # before int: in Python a bool IS an int
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _wrong_value(spec: dict) -> object:
    """A value of a type this sub-schema does not allow, or _MISSING if untyped."""
    declared = spec.get("type")
    if not declared:
        return _MISSING
    allowed = {declared} if isinstance(declared, str) else set(declared)
    if "number" in allowed:
        allowed.add("integer")
    if "integer" in allowed:
        allowed.add("number")
    for candidate in _WRONG_CANDIDATES:
        if _json_type(candidate) not in allowed:
            return candidate
    return _MISSING


def _mutations() -> list[tuple[tuple, object]]:
    """One (path, wrong value) per typed field the schema declares, nested included.

    Descends to **any** depth. It used to go exactly one level, and
    `crs_decisions.transformation` is two: the object was mutated as a
    container while `pipeline`, `accuracy_m` and `is_ballpark` — the three keys
    draft.3 added — were never mutated at all. The assertion that the suite
    covers `("crs_decisions", "transformation")` found the container and passed
    while the leaves were uncovered, which is how the validator came to reject
    `pipeline: null` while the schema accepted it for four days.
    """
    found: list[tuple[tuple, object]] = []

    def descend(prefix: tuple, spec: dict) -> None:
        for sub, sub_spec in (spec.get("properties") or {}).items():
            wrong = _wrong_value(sub_spec)
            if wrong is not _MISSING:
                found.append(((*prefix, sub), wrong))
            if isinstance(sub_spec, dict) and sub_spec.get("properties"):
                descend((*prefix, sub), sub_spec)

    for name, spec in SCHEMA["properties"].items():
        wrong = _wrong_value(spec)
        if wrong is not _MISSING:
            found.append(((name,), wrong))
        descend((name,), spec)
        items = spec.get("items")
        if isinstance(items, dict):
            if items.get("properties"):
                for sub, sub_spec in items["properties"].items():
                    wrong = _wrong_value(sub_spec)
                    if wrong is not _MISSING:
                        found.append(((name, 0, sub), wrong))
            else:
                wrong = _wrong_value(items)
                if wrong is not _MISSING:
                    found.append(((name, 0), wrong))
        extra = spec.get("additionalProperties")
        if isinstance(extra, dict):
            wrong = _wrong_value(extra)
            if wrong is not _MISSING:
                found.append(((name, "x-any-extra-key"), wrong))
    return found


MUTATIONS = _mutations()


def _maximal_record() -> dict:
    """A record carrying every field the format declares, required and recommended.

    The mutation test is only as good as its starting point: a field absent from
    the base record can still be mutated (the mutation adds it), but a field
    whose CONTAINER is absent cannot, so the base has to hold them all.
    """
    record = json.loads(
        (ROOT / "conformance" / "valid" / "full-featured.json").read_text(encoding="utf-8")
    )
    record["output"] = {
        "path": "out/basins.tif",
        "sha256": "3f79bb7b435b05321651daefd374cdc681dc06faa65e374e38337b88ca046dea",
    }
    record["notes"] = ["the DEM was copied to a workspace path before the engine saw it"]
    record["repairs"] = [{"check": "geometry_valid", "action": "make_valid", "resolved": True}]
    record["parameters_redacted"] = False
    record["environment"] = {"PROJ_NETWORK": "OFF", "GDAL_NUM_THREADS": "1"}
    record["crs_decisions"]["transformation"] = {
        "pipeline": "noop", "accuracy_m": 0.0, "is_ballpark": False,
    }
    return record


def _place(record: dict, path: tuple, value: object) -> None:
    target = record
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value


def test_the_maximal_record_is_valid_in_both():
    """Guards the mutation test below: if the base record were already invalid,
    every mutation would 'pass' for the wrong reason and prove nothing."""
    record = _maximal_record()
    assert problems(record) == []
    assert _schema_errors(record) == []


def test_the_mutation_table_covers_the_declared_surface():
    """A generative test that generates nothing is the quietest way to lose a check."""
    paths = {path for path, _ in MUTATIONS}
    assert len(MUTATIONS) >= 25, f"only {len(MUTATIONS)} mutations derived from the schema"
    for expected in (
        ("producer",), ("producer", "name"),
        ("crs_decisions",), ("crs_decisions", "analysis_crs"),
        ("notes",), ("notes", 0), ("repairs",), ("repairs", 0),
        ("parameters_redacted",),
        ("inputs", 0, "layer"), ("inputs", 0, "crs"),
        ("verification", 0, "critical"), ("verification", 0, "argument"),
        ("environment",), ("crs_decisions", "transformation"),
        ("crs_decisions", "source_crs"),
        # The three leaves draft.3 added, two levels down. Named individually
        # because the container above them was covered and they were not: the
        # table listed `("crs_decisions", "transformation")`, that assertion
        # passed, and nothing mutated the keys inside it. Covering a container
        # is not covering what it holds.
        ("crs_decisions", "transformation", "pipeline"),
        ("crs_decisions", "transformation", "accuracy_m"),
        ("crs_decisions", "transformation", "is_ballpark"),
    ):
        assert expected in paths, f"the schema no longer yields a mutation for {expected}"

    # Every typed leaf the schema declares, at any depth, and not a list to
    # maintain by hand. Without this the recursion in `_mutations` can be
    # removed and nothing fails — which is a guard that is not guarding.
    def leaves(prefix: tuple, spec: dict) -> set[tuple]:
        out: set[tuple] = set()
        for sub, sub_spec in (spec.get("properties") or {}).items():
            if not isinstance(sub_spec, dict):
                continue
            if sub_spec.get("properties"):
                out |= leaves((*prefix, sub), sub_spec)
            elif _wrong_value(sub_spec) is not _MISSING:
                out.add((*prefix, sub))
        return out

    declared: set[tuple] = set()
    for name, spec in SCHEMA["properties"].items():
        if isinstance(spec, dict):
            declared |= leaves((name,), spec)
    missing = sorted(declared - paths)
    assert not missing, (
        f"the schema declares these typed leaves and nothing mutates them: "
        f"{missing}. A field the suite never mutates is a field where the two "
        f"implementations may already disagree."
    )


@pytest.mark.parametrize(
    ("path", "wrong"), MUTATIONS,
    ids=[".".join(str(step) for step in path) for path, _ in MUTATIONS],
)
def test_both_implementations_reject_the_same_wrong_type(path: tuple, wrong: object):
    """Neither implementation may be the lenient one.

    Stated as one test over both rather than two suites, because the failure a
    reader needs is not "the validator missed this" but "these two disagree" —
    and which of them is wrong is a judgement, not a fact the test can settle.
    """
    record = _maximal_record()
    _place(record, path, wrong)
    where = ".".join(str(step) for step in path)
    by_validator = problems(record)
    by_schema = _schema_errors(record)
    assert by_validator or by_schema, (
        f"{where} = {wrong!r}: both implementations accepted a wrongly typed field. "
        "Either the schema declares a type nobody enforces, or the type is wrong."
    )
    assert by_validator, (
        f"{where} = {wrong!r}: the schema rejects this and the standalone validator "
        "does not — the two implementations have drifted, and the validator is the "
        f"lenient one. Schema said: {by_schema[:2]}"
    )
    assert by_schema, (
        f"{where} = {wrong!r}: the validator rejects this and the schema does not — "
        "the two implementations have drifted, and the schema is the lenient one. "
        f"Validator said: {by_validator[:2]}"
    )

def test_the_paths_the_readme_tells_strangers_to_download_still_exist():
    """The README hands out raw URLs. A rename breaks a stranger's paste.

    Nothing in this repository needs installing, which is the point and also the
    risk: the way people use it is by fetching two files by path from `main`. So
    the paths are part of the contract, and moving one is a breaking change that
    no import would catch. This test does not hit the network — it checks that
    every path the README publishes is a file that exists here.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    published = re.findall(
        r"raw\.githubusercontent\.com/mapsmith-ai/manifest-spec/main/(\S+)", readme
    )
    assert published, "the README no longer publishes any raw URL — update this test with it"
    for relative in published:
        assert (ROOT / relative).is_file(), (
            f"the README tells people to download {relative}, which is not here any more. "
            "Renaming a published path breaks every pasted command in the wild."
        )


# --- the direction the suite was missing ------------------------------------


def _nullable_paths() -> list[tuple]:
    """Every path the schema declares nullable, at any depth.

    Derived from the schema rather than listed, so a field made nullable later
    is covered without anybody remembering to add it.
    """
    found: list[tuple] = []

    def nullable(spec: object) -> bool:
        return isinstance(spec, dict) and "null" in (
            spec.get("type") if isinstance(spec.get("type"), list) else []
        )

    def descend(prefix: tuple, spec: dict) -> None:
        for sub, sub_spec in (spec.get("properties") or {}).items():
            if nullable(sub_spec):
                found.append((*prefix, sub))
            if isinstance(sub_spec, dict) and sub_spec.get("properties"):
                descend((*prefix, sub), sub_spec)
        items = spec.get("items")
        if isinstance(items, dict) and items.get("properties"):
            for sub, sub_spec in items["properties"].items():
                if nullable(sub_spec):
                    found.append((*prefix, 0, sub))

    for name, spec in SCHEMA["properties"].items():
        if nullable(spec):
            found.append((name,))
        if isinstance(spec, dict):
            descend((name,), spec)
    return found


NULLABLE = _nullable_paths()


def test_the_schema_declares_some_fields_nullable():
    """If this list is empty the parametrised test below is vacuous."""
    assert NULLABLE, (
        "no nullable field found in the schema — either the schema stopped "
        "declaring any, or this derivation stopped working and the test that "
        "depends on it is now checking nothing"
    )


@pytest.mark.parametrize("path", NULLABLE, ids=lambda p: ".".join(str(x) for x in p))
def test_both_implementations_accept_null_where_the_schema_allows_it(path):
    """The direction this suite did not have, and it cost four days of divergence.

    Every other test here checks that both implementations REJECT a value the
    schema forbids. None checked that both ACCEPT one the schema allows — and
    `null` on a nullable field is exactly that case. `pipeline` was the only
    nullable field the validator wrote the non-nullable way, so it rejected a
    record the schema accepted and MapSmith emitted, on the NAD27-to-WGS84 pair
    section 3.7 uses as its headline example.

    Section 3 says the schema wins where they disagree, so a disagreement in
    either direction is a bug in the validator.
    """
    record = _maximal_record()
    target = record
    for step in path[:-1]:
        target = target[step]
    if path[-1] not in target:
        pytest.skip(f"the maximal record does not carry {'.'.join(map(str, path))}")
    target[path[-1]] = None

    schema_problems = _schema_errors(record)
    assert not schema_problems, (
        f"the schema rejects null at {path}, which contradicts its own type "
        f"declaration: {schema_problems}"
    )
    assert problems(record) == [], (
        f"the validator rejects null at {path} while the schema accepts it. "
        f"Section 3: where the two disagree, the schema wins."
    )
