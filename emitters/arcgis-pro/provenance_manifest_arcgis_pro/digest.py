"""Content digests for the datasets a GIS engine reads and writes.

A manifest says ``sha256`` is "of the bytes", which is unambiguous for a
single-file format and undefined for the two shapes a desktop GIS writes most:

* a **shapefile** is a set of sibling files (``.shp``, ``.shx``, ``.dbf``,
  ``.prj``, ...). Hashing the ``.shp`` alone covers the geometry and leaves the
  attributes and the coordinate reference system out of the digest.
* a **file geodatabase** is a directory. Its layers live in dozens of files
  whose names say nothing about which layer they hold.

Both get the same rule here: the SHA-256 of a sorted listing, one line per
member file, ``<relative-path>\\0<sha256-of-that-file>\\n``, with ``/`` as the
separator. The digest changes when any member changes and does not depend on
the order the filesystem lists them in.

Lock files (``*.lock``) are excluded, and never opened: a file geodatabase
creates them only while it is open, they cannot be read while they exist, and
their names carry the host name and a process id -- so including them would
make the digest depend on who has the data open, and would put the machine's
name in a record. Measured on ArcGIS Pro 3.7.1: reading a geodatabase, with a
cursor or as a tool input, changes none of its other bytes.

This module is the standard library only, so the rule can be tested without an
engine installed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 1 << 20

# Every file that belongs to a shapefile named ``<stem>.shp`` shares its stem.
# The list is the one the format and its common companions define; anything
# else beside the .shp with the same stem (an unrelated ``roads.txt``) is not
# part of the dataset and is not hashed.
SHAPEFILE_MEMBERS = (
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".qix",
    ".sbn",
    ".sbx",
    ".fbn",
    ".fbx",
    ".ain",
    ".aih",
    ".atx",
    ".ixs",
    ".mxs",
    ".shp.xml",
)

CONTAINER_SUFFIXES = (".gdb",)


def file_sha256(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def listing_sha256(members: dict[str, str]) -> str:
    """The digest of ``{relative_path: sha256}``, independent of listing order."""
    lines = "".join(f"{rel}\0{sha}\n" for rel, sha in sorted(members.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _is_lock(name: str) -> bool:
    return name.lower().endswith(".lock")


def directory_members(root: Path) -> dict[str, str]:
    members: dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if _is_lock(name):
                continue
            path = Path(dirpath) / name
            members[path.relative_to(root).as_posix()] = file_sha256(path)
    return members


def shapefile_members(shp: Path) -> dict[str, str]:
    members: dict[str, str] = {}
    stem = shp.name[: -len(".shp")]
    lowered = {p.name.lower(): p for p in shp.parent.iterdir() if p.is_file()}
    for suffix in SHAPEFILE_MEMBERS:
        path = lowered.get((stem + suffix).lower())
        if path is not None:
            members[path.name] = file_sha256(path)
    return members


@dataclass(frozen=True)
class DatasetDigest:
    """What a manifest records about one dataset.

    ``path`` is the file or container that was hashed, ``layer`` the dataset
    inside a container when there is one, and ``kind`` which rule produced the
    digest -- a consumer recomputing it needs to know.
    """

    path: str
    sha256: str
    kind: str  # "file" | "shapefile" | "container"
    layer: str | None = None
    members: int = 1


def split_container(path: str | os.PathLike) -> tuple[Path, str | None]:
    """Split ``C:/data/t.gdb/roads`` into (``C:/data/t.gdb``, ``roads``).

    A feature dataset adds one level (``t.gdb/transport/roads``); the layer is
    everything after the container, joined with ``/``.
    """
    p = Path(path)
    parts = p.parts
    for i, part in enumerate(parts):
        if part.lower().endswith(CONTAINER_SUFFIXES):
            container = Path(*parts[: i + 1])
            rest = parts[i + 1 :]
            return container, ("/".join(rest) if rest else None)
    return p, None


def dataset_digest(path: str | os.PathLike) -> DatasetDigest:
    """Digest a dataset given the path a GIS tool was called with."""
    container, layer = split_container(path)
    if container.suffix.lower() in CONTAINER_SUFFIXES:
        if not container.is_dir():
            raise FileNotFoundError(f"no such container: {container}")
        members = directory_members(container)
        return DatasetDigest(
            path=container.as_posix(),
            sha256=listing_sha256(members),
            kind="container",
            layer=layer,
            members=len(members),
        )
    p = Path(path)
    if p.suffix.lower() == ".shp":
        members = shapefile_members(p)
        if p.name not in members:
            raise FileNotFoundError(f"no such shapefile: {p}")
        return DatasetDigest(
            path=p.as_posix(),
            sha256=listing_sha256(members),
            kind="shapefile",
            members=len(members),
        )
    if p.is_dir():
        raise ValueError(
            f"{p} is a directory this module has no rule for; digesting it as a "
            "container would claim a meaning nobody defined"
        )
    return DatasetDigest(path=p.as_posix(), sha256=file_sha256(p), kind="file")
