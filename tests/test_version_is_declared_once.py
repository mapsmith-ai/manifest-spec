"""Every place that declares the current spec version must say the same thing.

This is not hypothetical tidiness. Section 3.6 of the specification closed the
check-name vocabulary under an unchanged `draft.2` label, so a record that
conformed one day did not the next and carried no version to say so. The label
is the only thing a reader of a draft has; when it drifts, the draft lies.

The subtlety worth keeping is that not every mention of a version is a
declaration. `spec/manifest-v1.md` says "Until `1.0.0-draft.3` this field was
declared an object with string values" — a statement about the past, which stays
true forever and must NOT be rewritten when the version moves. Only the present
tense is checked here. It is the same distinction the project applies to
published figures: a number is either recomputed or attached to a date.

The specification document's own title is the source of truth. Everything else
follows it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SPEC = ROOT / "spec" / "manifest-v1.md"


def current_version() -> str:
    """The version in the specification's title, which is what the others follow."""
    first_line = SPEC.read_text(encoding="utf-8").splitlines()[0]
    found = re.search(r"v(\d+\.\d+\.\d+(?:-[\w.]+)?)\s*$", first_line)
    assert found, f"the spec title does not end in a version: {first_line!r}"
    return found.group(1)


# Each entry: the file, and a pattern whose single capture group is the version
# that file declares. A pattern is a claim that the file says this; if it matches
# nothing, the prose was rewritten and the guard went quiet without anyone
# deciding that — so a pattern matching nothing is a failure, not a skip.
DECLARATIONS = [
    ("CITATION.cff", r'^version:\s*"([^"]+)"', "the citation metadata"),
    ("examples/emitter_minimal.py", r'^SPEC_VERSION\s*=\s*"([^"]+)"', "the reference producer"),
    ("README.md", r'"spec_version":\s*"([^"]+)"', "the example record on the front page"),
    ("README.md", r"\*\*Status: draft\*\*\s*\(`([^`]+)`\)", "the status line"),
    (".zenodo.json", r'"version":\s*"([^"]+)"', "the archive metadata"),
]


@pytest.mark.parametrize(("relative_path", "pattern", "what"), DECLARATIONS)
def test_every_declaration_agrees_with_the_spec_title(
    relative_path: str, pattern: str, what: str
) -> None:
    expected = current_version()
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    found = re.findall(pattern, text, flags=re.MULTILINE)

    assert found, (
        f"{relative_path}: nothing matched the pattern for {what}. Either the "
        f"declaration was removed, or it was reworded and this guard has been "
        f"silently switched off. Fix the pattern or restore the declaration."
    )
    for declared in found:
        assert declared == expected, (
            f"{relative_path} declares {declared!r} in {what}, but the "
            f"specification title says {expected!r}. A draft whose label drifts "
            f"is worse than one that never moved: readers use the label to know "
            f"whether the document changed under them."
        )


def test_the_citation_file_is_about_this_repository() -> None:
    """A CITATION.cff copied from a sibling project is the likely failure here."""
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "mapsmith-ai/manifest-spec" in text, "repository-code does not point here"
    assert "CC-BY-4.0" in text and "Apache-2.0" in text, (
        "both licences must appear: the specification text is CC-BY-4.0 and the "
        "schema, validator, fixtures and examples are Apache-2.0"
    )


def test_the_release_date_is_not_in_the_future() -> None:
    """`date-released` is set by hand before tagging, and a slipped tag leaves it wrong."""
    import datetime as dt

    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    found = re.search(r'^date-released:\s*"(\d{4}-\d{2}-\d{2})"', text, flags=re.MULTILINE)
    assert found, "CITATION.cff has no date-released"
    released = dt.date.fromisoformat(found.group(1))
    assert released <= dt.date.today(), (
        f"CITATION.cff claims a release on {released}, which has not happened yet. "
        f"The date is written by hand before tagging; when the tag slips, this is "
        f"the line that quietly becomes false."
    )


def test_the_archive_metadata_declares_one_licence_as_a_string() -> None:
    """The defect this test exists for cost a failed release.

    Zenodo's metadata model has a single `license` field, typed as one string
    from a controlled vocabulary. CITATION.cff can list several, and this
    repository genuinely has two — CC-BY-4.0 for the specification text,
    Apache-2.0 for the schema, validator, fixtures and examples. Converted to
    Zenodo's shape that becomes `"license": {"id": ["CC-BY-4.0", "Apache-2.0"]}`,
    which Zenodo rejects, and the release fails with no DOI.

    `.zenodo.json` therefore names one licence, and the dual licensing has to be
    stated in the description instead — because a record that silently declares
    one licence for a dual-licensed archive is a true field leaving a false
    impression, which is the failure mode this project spends its time catching
    in other people's software.
    """
    import json

    metadata = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))

    licence = metadata.get("license")
    assert isinstance(licence, str), (
        f"license must be a single string from Zenodo's vocabulary, got "
        f"{type(licence).__name__}: {licence!r}. A list is what failed before."
    )
    assert licence == licence.lower(), (
        f"Zenodo's licence identifiers are lowercase; {licence!r} is not"
    )

    description = metadata.get("description", "")
    for other in ("CC-BY-4.0", "Apache-2.0"):
        assert other in description, (
            f"the description must name {other}: the single licence field cannot "
            f"express that this archive is dual-licensed, so the prose must"
        )


def test_the_archive_metadata_and_the_citation_file_do_not_contradict() -> None:
    """Zenodo ignores CITATION.cff entirely when .zenodo.json exists.

    That makes disagreement between them invisible at release time and visible
    only to a human reading both — the exact conditions under which two copies
    of the same fact drift apart.
    """
    import json
    import re as regex

    metadata = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")

    title = regex.search(r"^title:\s*\"(.+)\"", citation, flags=regex.MULTILINE)
    assert title, "CITATION.cff has no title"
    assert metadata["title"] == title.group(1), (
        f".zenodo.json titles the record {metadata['title']!r} while CITATION.cff "
        f"says {title.group(1)!r}"
    )

    creators = [c["name"] for c in metadata["creators"]]
    for name in creators:
        assert name in citation, (
            f".zenodo.json credits {name!r}, which does not appear in CITATION.cff"
        )
