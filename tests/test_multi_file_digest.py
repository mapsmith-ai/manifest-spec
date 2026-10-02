"""Section 3.3's rule for datasets made of several files, with answers built from hashlib by hand.

And the reference emitter must compute the same digests as the reference
function: two implementations of one rule in one repository that disagree
would make the rule whatever the reader happened to run.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples"))
sys.path.insert(0, str(ROOT / "emitters" / "arcgis-pro"))
sys.path.insert(0, str(ROOT / "emitters" / "qgis"))

from multi_file_digest import dataset_sha256  # noqa: E402
from provenance_manifest_arcgis_pro.digest import dataset_digest as arcgis_digest  # noqa: E402
from provenance_manifest_qgis.digest import dataset_digest as qgis_digest  # noqa: E402


def dataset_digest(path):
    """Both emitters' digest, which must agree -- in value and in refusing.

    The QGIS emitter carries a copy of the module rather than importing it, so
    each installs alone into its engine's Python; a copy can drift, and this is
    where it would show. Exactly one of the two raising is a failure; both
    raising re-raises the first, so `pytest.raises` below still sees it.
    """
    results = []
    for digest in (arcgis_digest, qgis_digest):
        try:
            results.append(digest(path))
        except Exception as exc:  # compared, then re-raised
            results.append(exc)
    first, second = results
    if isinstance(first, Exception) or isinstance(second, Exception):
        assert type(first) is type(second), f"one emitter raised and the other did not: {results}"
        raise first
    same = (first.sha256, first.kind, first.layer) == (second.sha256, second.kind, second.layer)
    assert same, results
    return first


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def by_hand(lines: list) -> str:
    return sha("".join(f"{p}\0{s}\n" for p, s in lines).encode("utf-8"))


SHAPEFILE = {
    ".shp": b"geom", ".shx": b"idx", ".dbf": b"attrs", ".prj": b"crs", ".cpg": b"UTF-8",
    ".sbn": b"spatial index", ".shp.xml": b"metadata",
}
SHAPEFILE_DIGEST = by_hand([
    (".cpg", sha(b"UTF-8")), (".dbf", sha(b"attrs")), (".prj", sha(b"crs")),
    (".shp", sha(b"geom")), (".shx", sha(b"idx")),
])


def _shapefile(folder: Path, stem: str = "roads") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for suffix, content in SHAPEFILE.items():
        (folder / f"{stem}{suffix}").write_bytes(content)
    return folder / f"{stem}.shp"


def test_a_shapefile_is_its_five_data_files_named_by_extension(tmp_path):
    assert dataset_sha256(_shapefile(tmp_path)) == SHAPEFILE_DIGEST


def test_renaming_a_shapefile_does_not_change_its_digest(tmp_path):
    # Section 6 walks lineage by content so that a copy under another name
    # still resolves; a digest that included the file name would break it.
    a = _shapefile(tmp_path / "a", "roads")
    b = _shapefile(tmp_path / "b", "delivered_2026")
    assert dataset_sha256(a) == dataset_sha256(b) == SHAPEFILE_DIGEST
    assert dataset_digest(a).sha256 == dataset_digest(b).sha256 == SHAPEFILE_DIGEST


def test_editing_the_attributes_moves_the_digest_and_an_index_does_not(tmp_path):
    shp = _shapefile(tmp_path)
    (tmp_path / "roads.sbn").write_bytes(b"rebuilt index")
    (tmp_path / "roads.shp.xml").write_bytes(b"rewritten metadata")
    assert dataset_sha256(shp) == SHAPEFILE_DIGEST
    (tmp_path / "roads.dbf").write_bytes(b"edited attrs")
    assert dataset_sha256(shp) != SHAPEFILE_DIGEST


def test_members_are_matched_without_regard_to_case_by_both_implementations(tmp_path):
    (tmp_path / "ROADS.SHP").write_bytes(b"geom")
    (tmp_path / "roads.dbf").write_bytes(b"attrs")
    expected = by_hand([(".dbf", sha(b"attrs")), (".shp", sha(b"geom"))])
    assert dataset_sha256(tmp_path / "roads.shp") == expected
    assert dataset_digest(tmp_path / "roads.shp").sha256 == expected


def test_two_files_for_one_member_are_refused_by_both(tmp_path):
    probe_a, probe_b = tmp_path / "Case", tmp_path / "case"
    probe_a.write_bytes(b"")
    if probe_b.exists():
        pytest.skip("case-insensitive filesystem: two such files cannot exist here")
    (tmp_path / "roads.shp").write_bytes(b"geom")
    (tmp_path / "roads.dbf").write_bytes(b"a")
    (tmp_path / "roads.DBF").write_bytes(b"b")
    with pytest.raises(ValueError, match="two files"):
        dataset_sha256(tmp_path / "roads.shp")
    with pytest.raises(ValueError, match="two files"):
        dataset_digest(tmp_path / "roads.shp")


def test_a_container_is_its_files_but_locks_hidden_files_and_os_litter(tmp_path):
    gdb = tmp_path / "data.gdb"
    (gdb / "sub").mkdir(parents=True)
    (gdb / "b.gdbtable").write_bytes(b"two")
    (gdb / "a.gdbtable").write_bytes(b"one")
    (gdb / "sub" / "c.spx").write_bytes(b"three")
    (gdb / "_gdb.HOST.123.456.sr.lock").write_bytes(b"volatile")
    (gdb / ".DS_Store").write_bytes(b"finder")
    (gdb / "Thumbs.db").write_bytes(b"explorer")
    expected = by_hand([
        ("a.gdbtable", sha(b"one")), ("b.gdbtable", sha(b"two")), ("sub/c.spx", sha(b"three")),
    ])
    assert dataset_sha256(gdb) == expected
    assert dataset_digest(gdb / "roads").sha256 == expected


def test_an_empty_container_is_the_sha256_of_the_empty_listing(tmp_path):
    gdb = tmp_path / "empty.gdb"
    gdb.mkdir()
    (gdb / "only.lock").write_bytes(b"volatile")
    assert dataset_sha256(gdb) == sha(b"")
    assert dataset_digest(gdb).sha256 == sha(b"")


def test_a_single_file_is_the_sha256_of_its_bytes(tmp_path):
    f = tmp_path / "a.gpkg"
    f.write_bytes(b"abc")
    assert dataset_sha256(f) == sha(b"abc")
    assert dataset_digest(f).sha256 == sha(b"abc")
