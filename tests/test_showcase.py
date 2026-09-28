"""What a visitor reads must lead somewhere, and must cover what is here.

The rest of the suite checks the format. This file checks the pages around it,
because "written" and "published" are two different acts and nothing else sees
the difference: a folder nobody links to does not exist for a visitor, a link
whose target moved is a dead end on the one page meant to explain, and a licence
paragraph that lists the directories it covers says nothing about the one added
after it was written.

Every list here is derived from the repository -- the Markdown files git tracks,
the directories under `emitters/`, the top-level directories -- so a new page,
emitter or directory is checked the day it lands, without anyone remembering
to add it to a list.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
EMITTERS = ROOT / "emitters"

LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def tracked_files() -> list[str]:
    """The repository's files, relative and with `/`.

    `git ls-files` in a checkout. Outside one -- the GitHub tarball the README
    tells readers to run the suite from -- the tree itself, minus caches and
    dot-directories: that is the file set `git archive` produced. This suite
    failed exactly there on 2026-09-26, and this file repeated it the next day.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
        return [line for line in out.splitlines() if line.strip()]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if path.is_file() and not any(
                part.startswith(".") or part == "__pycache__" for part in rel.parts
            ):
                files.append(rel.as_posix())
        return files


def tracked_markdown() -> list[Path]:
    files = [ROOT / rel for rel in tracked_files() if rel.endswith(".md")]
    # Deriving the list is only worth something if the derivation cannot come
    # back empty: an empty list makes every test below pass.
    assert README in files, "the file listing did not include README.md: the derivation is broken"
    return files


def _prose_lines(text: str) -> list[str]:
    """Lines outside fenced code blocks, where a `](...)` is not a link."""
    lines, fenced = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


def github_anchors(path: Path) -> set[str]:
    """The anchors GitHub generates for the headings of a Markdown file."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for line in _prose_lines(path.read_text(encoding="utf-8")):
        m = HEADING.match(line)
        if not m:
            continue
        slug = re.sub(r"[^\w\- ]", "", m.group(1).lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchors.add(slug if n == 0 else f"{slug}-{n}")
    return anchors


def relative_links(path: Path) -> list[str]:
    links = []
    for line in _prose_lines(path.read_text(encoding="utf-8")):
        for target in LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # https:, mailto:
                continue
            links.append(target)
    return links


@pytest.mark.parametrize("page", tracked_markdown(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_relative_link_resolves(page: Path):
    """GitHub renders these pages, so a relative link is a path in this checkout."""
    dead = []
    for target in relative_links(page):
        file_part, _, anchor = target.partition("#")
        dest = (page.parent / file_part).resolve() if file_part else page
        if not dest.exists():
            dead.append(f"{target} (no such path)")
            continue
        if anchor and dest.suffix == ".md" and anchor not in github_anchors(dest):
            dead.append(f"{target} (no heading gives #{anchor})")
    assert not dead, f"{page.relative_to(ROOT).as_posix()} links to: " + "; ".join(dead)


SELF_URL = re.compile(
    r"https://(?:raw\.githubusercontent\.com/mapsmith-ai/manifest-spec/main/"
    r"|github\.com/mapsmith-ai/manifest-spec/(?:blob|tree)/main/)([^\s)\"'<>#]+)"
)


@pytest.mark.parametrize("page", tracked_markdown(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_url_into_this_repository_names_a_file_that_exists(page: Path):
    """The quickstart tells a reader to `curl` files by URL, code blocks included.

    A relative link is checked above; an absolute URL into this repository is
    the same promise written differently, and a file moved or renamed would
    leave the quickstart downloading a 404 page into validate.py.
    """
    text = page.read_text(encoding="utf-8")
    missing = sorted({p for p in SELF_URL.findall(text) if not (ROOT / p).exists()})
    where = page.relative_to(ROOT).as_posix()
    assert not missing, f"{where} points at files that are not here: {missing}"


def test_the_quickstart_urls_are_found_at_all():
    # A pattern that matches nothing makes the test above pass on every page.
    assert len(SELF_URL.findall(README.read_text(encoding="utf-8"))) >= 2


def emitter_dirs() -> list[Path]:
    if not EMITTERS.is_dir():
        return []
    return sorted(p for p in EMITTERS.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def test_the_emitter_list_is_not_empty():
    """Guards the two tests below: over an empty list they would pass on nothing."""
    assert emitter_dirs(), "emitters/ holds no emitter, or this derivation no longer finds them"


@pytest.mark.parametrize("emitter", emitter_dirs(), ids=lambda p: p.name)
def test_every_emitter_is_reachable_from_the_front_page(emitter: Path):
    link = f"(emitters/{emitter.name}/)"
    assert link in README.read_text(encoding="utf-8"), (
        f"emitters/{emitter.name}/ exists and the README does not link to it: a visitor "
        "reading the front page cannot know it is here"
    )


@pytest.mark.parametrize("emitter", emitter_dirs(), ids=lambda p: p.name)
def test_every_emitter_says_it_is_not_affiliated_with_the_engine(emitter: Path):
    """An emitter carries an engine's name in its own; its README says whose name it is."""
    readme = emitter / "README.md"
    assert readme.is_file(), f"emitters/{emitter.name}/ has no README.md"
    assert "Not affiliated with" in readme.read_text(encoding="utf-8"), (
        f"emitters/{emitter.name}/README.md has no non-affiliation line for the engine it names"
    )


def emitter_readmes() -> list[str]:
    """Every README under `emitters/`, at any depth: an add-in or a plugin inside an
    emitter has its own page, and a visitor can land on it first."""
    readmes = [
        rel for rel in tracked_files() if rel.startswith("emitters/") and rel.endswith("/README.md")
    ]
    assert readmes, "no README under emitters/: the derivation is broken"
    return sorted(readmes)


@pytest.mark.parametrize("readme", emitter_readmes())
def test_every_page_under_emitters_says_it_is_not_affiliated(readme: str):
    assert "Not affiliated with" in (ROOT / readme).read_text(encoding="utf-8"), (
        f"{readme} names an engine and has no non-affiliation line"
    )


# Top-level directories the Apache-2.0 sentence does not have to name: the
# specification text is the other licence, and the tests are not a deliverable.
NOT_UNDER_THE_CODE_LICENCE_SENTENCE = {"spec", "tests"}


def code_directories() -> list[str]:
    """Top-level directories holding tracked files, minus the two exempt ones."""
    dirs = {rel.split("/", 1)[0] for rel in tracked_files() if "/" in rel}
    dirs = {d for d in dirs if not d.startswith(".")}
    assert "validator" in dirs, "the derivation of top-level directories is broken"
    return sorted(dirs - NOT_UNDER_THE_CODE_LICENCE_SENTENCE)


def _names(sentence: str, directory: str) -> bool:
    word = directory.rstrip("s").lower()
    return word in sentence.lower()


def test_the_readme_licence_paragraph_names_every_code_directory():
    text = README.read_text(encoding="utf-8")
    section = text.split("## Licences", 1)[-1]
    missing = [d for d in code_directories() if not _names(section, d)]
    assert not missing, (
        f"the README's licence paragraph does not say which licence covers {missing}"
    )


def test_the_archive_description_names_every_code_directory():
    """The Zenodo record is what a citer reads, and it is written at release time."""
    description = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))["description"]
    licences = description.split("Licences", 1)[-1]
    missing = [d for d in code_directories() if not _names(licences, d)]
    assert not missing, (
        f"the licence sentence in .zenodo.json does not say which licence covers {missing}"
    )
