"""Content digests for the datasets a GIS engine reads and writes.

A manifest says ``sha256`` is "of the bytes", which is unambiguous for a
single-file format and undefined for the two shapes a desktop GIS writes most:

* a **shapefile** is a set of sibling files (``.shp``, ``.shx``, ``.dbf``,
  ``.prj``, ...). Hashing the ``.shp`` alone covers the geometry and leaves the
  attributes and the coordinate reference system out of the digest.
* a **file geodatabase** is a directory. Its layers live in dozens of files
  whose names say nothing about which layer they hold.

Both get the rule of section 3.3 of the specification (draft.9): the SHA-256
of a sorted listing, one line per member, ``<name>\\0<sha256>\\n``. A
shapefile member is named by its lowercased extension, so renaming the
shapefile keeps its digest; a container member by its path relative to the
container, with ``/``. The digest changes when any member changes and does
not depend on the order the filesystem lists them in.

Lock files (``*.lock``) are excluded, and never opened: a file geodatabase
creates them only while it is open, they cannot be read while they exist, and
their names carry the host name and a process id -- so including them would
make the digest depend on who has the data open, and would put the machine's
name in a record. Measured on ArcGIS Pro 3.7.1: reading a geodatabase, with a
cursor or as a tool input, changes none of its other bytes.

This module is the standard library only, so the rule can be tested without an
engine installed. It is a copy of the ArcGIS Pro emitter's module, not an
import: each emitter installs alone into its engine's Python. Both are held to
the specification's reference function by ``tests/test_multi_file_digest.py``,
so a copy that drifted would fail there rather than disagree quietly.

A GeoPackage layer arrives from QGIS as ``path|layername=roads``. The ``|``
part is not a path; ``qgis.py`` splits it off and records it as the layer, and
the digest covers the whole file, as section 3.3 says for a file that holds
several layers.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 1 << 20

# The data-defining files of a shapefile, as section 3.3 of the specification
# lists them since draft.9. Spatial indexes and .shp.xml metadata are left out
# on purpose: a digest that changed when an index was rebuilt would report an
# edit that never touched the data.
SHAPEFILE_MEMBERS = (".shp", ".shx", ".dbf", ".prj", ".cpg")

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


# What an operating system drops into any folder it displays; no file
# geodatabase file is named like this (spec section 3.3).
NOT_MEMBERS = ("thumbs.db", "desktop.ini")


def _excluded(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(".lock") or name.startswith(".") or lowered in NOT_MEMBERS


def directory_members(root: Path) -> dict[str, str]:
    members: dict[str, str] = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not (Path(dirpath) / d).is_symlink()]
        for name in files:
            if _excluded(name):
                continue  # a lock file is never opened
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            members[path.relative_to(root).as_posix()] = file_sha256(path)
    return members


def shapefile_members(shp: Path) -> dict[str, str]:
    """Members named by their lowercased extension, so a renamed shapefile keeps its digest."""
    stem = shp.name[: -len(".shp")].lower()
    found: dict[str, Path] = {}
    for candidate in shp.parent.iterdir():
        if not candidate.is_file() or candidate.is_symlink():
            continue
        for ext in SHAPEFILE_MEMBERS:
            if candidate.name.lower() == stem + ext:
                if ext in found:
                    raise ValueError(
                        f"two files match the {ext} member of {shp.name}: "
                        f"{found[ext].name} and {candidate.name}; the specification forbids "
                        "choosing one"
                    )
                found[ext] = candidate
    return {ext: file_sha256(path) for ext, path in found.items()}


@dataclass(frozen=True)
class DatasetDigest:
    """What a manifest records about one dataset.

    ``path`` is the file or container that was hashed, ``layer`` the dataset
    inside a container when there is one, and ``kind`` which rule of section
    3.3 produced the digest. The record does not carry ``kind``: since draft.9 a
    consumer derives the rule from the path and ``spec_version``.
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
        if ".shp" not in members:
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
