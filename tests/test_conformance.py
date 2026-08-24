"""The conformance suite is the referee between the two implementations.

The JSON Schema is the normative contract; the standalone validator re-states it
in plain Python. Independence is the point — one toolchain-free, one usable by
any jsonschema implementation in any language — and drift is the risk. These
tests run every fixture through BOTH: a record that one accepts and the other
rejects is a bug in one of them, and the failure says which.
"""

from __future__ import annotations

import json
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
