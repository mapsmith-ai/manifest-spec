"""The digest rules, with answers computed by hand from hashlib."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from provenance_manifest_arcgis_pro.digest import (
    dataset_digest,
    listing_sha256,
    split_container,
)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_a_single_file_is_the_sha256_of_its_bytes(tmp_path):
    f = tmp_path / "a.gpkg"
    f.write_bytes(b"abc")
    d = dataset_digest(f)
    assert (d.kind, d.sha256, d.layer) == ("file", sha(b"abc"), None)


def test_the_listing_digest_is_exactly_the_documented_lines():
    members = {"b.dbf": sha(b"2"), "a.shp": sha(b"1")}
    expected = sha(f"a.shp\0{sha(b'1')}\nb.dbf\0{sha(b'2')}\n".encode())
    assert listing_sha256(members) == expected


def test_a_shapefile_digest_covers_the_attributes_and_the_crs(tmp_path):
    for suffix, content in (
        (".shp", b"geom"),
        (".shx", b"idx"),
        (".dbf", b"attrs"),
        (".prj", b"crs"),
    ):
        (tmp_path / f"roads{suffix}").write_bytes(content)
    (tmp_path / "roads.txt").write_bytes(b"not part of the dataset")
    before = dataset_digest(tmp_path / "roads.shp")
    assert (before.kind, before.members) == ("shapefile", 4)
    (tmp_path / "roads.dbf").write_bytes(b"attrs edited")
    assert dataset_digest(tmp_path / "roads.shp").sha256 != before.sha256
    (tmp_path / "roads.dbf").write_bytes(b"attrs")
    (tmp_path / "roads.prj").write_bytes(b"another crs")
    assert dataset_digest(tmp_path / "roads.shp").sha256 != before.sha256


def test_an_unrelated_file_with_the_same_stem_does_not_move_the_digest(tmp_path):
    (tmp_path / "roads.shp").write_bytes(b"geom")
    before = dataset_digest(tmp_path / "roads.shp").sha256
    (tmp_path / "roads.txt").write_bytes(b"notes")
    assert dataset_digest(tmp_path / "roads.shp").sha256 == before


def test_a_container_layer_is_split_and_the_whole_directory_hashed(tmp_path):
    gdb = tmp_path / "t.gdb"
    gdb.mkdir()
    (gdb / "a00000001.gdbtable").write_bytes(b"one")
    (gdb / "a00000002.gdbtable").write_bytes(b"two")
    d = dataset_digest(gdb / "transport" / "roads")
    assert (d.kind, d.layer, d.members) == ("container", "transport/roads", 2)
    assert d.sha256 == listing_sha256(
        {"a00000001.gdbtable": sha(b"one"), "a00000002.gdbtable": sha(b"two")}
    )


def test_lock_files_are_neither_opened_nor_counted(tmp_path):
    gdb = tmp_path / "t.gdb"
    gdb.mkdir()
    (gdb / "a00000001.gdbtable").write_bytes(b"one")
    before = dataset_digest(gdb / "roads").sha256
    (gdb / "_gdb.SOMEHOST.1234.5678.sr.lock").write_bytes(b"volatile")
    assert dataset_digest(gdb / "roads").sha256 == before


def test_a_directory_with_no_rule_is_refused(tmp_path):
    (tmp_path / "folder").mkdir()
    with pytest.raises(ValueError, match="no rule"):
        dataset_digest(tmp_path / "folder")


def test_split_container_leaves_a_plain_path_alone():
    assert split_container("C:/data/a.gpkg") == (Path("C:/data/a.gpkg"), None)
