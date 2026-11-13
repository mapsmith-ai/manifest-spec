from __future__ import annotations

import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from provenance_manifest_arcgis_pro import model  # noqa: E402

PARAMETERS = [
    ("in_features", "Feature Layer", "Input"),
    ("out_feature_class", "Feature Class", "Output"),
    ("buffer_distance_or_field", ["Linear Unit", "Field"], "Input"),
    ("line_side", "String", "Input"),
    ("line_end_type", "String", "Input"),
    ("dissolve_option", "String", "Input"),
    ("dissolve_field", "Field", "Input"),
    ("method", "String", "Input"),
]


def _params():
    return [types.SimpleNamespace(name=name, datatype=kind, direction=direction)
            for name, kind, direction in PARAMETERS]


def _command(output: Path, input_name="fishnet") -> str:
    return f'Buffer {input_name} {output} "1 Meters" FULL ROUND NONE # PLANAR'


def _xml(command: str, duplicates=False) -> str:
    process = (
        f'<Process Name="Buffer" ToolSource="c:\\program files\\arcgis\\pro\\Resources\\'
        f'ArcToolbox\\toolboxes\\Analysis Tools.tbx\\Buffer" Date="20261112" Time="191834">'
        f'{command}</Process>'
    )
    return (
        '<metadata><Esri><DataProperties><lineage>'
        '<Process Name="CreateFishnet" Date="20260927" Time="180850">CreateFishnet old</Process>'
        + process + (process if duplicates else "")
        + '</lineage></DataProperties></Esri></metadata>'
    )


def _capture(output: Path, command: str) -> dict:
    return {
        "capture_version": 1,
        "tool": "t.Model",
        "run_id": "parent-1",
        "launch": "geoprocessing_pane",
        "started_at": "2026-11-12T18:18:30Z",
        "finished_at": "2026-11-12T18:18:36Z",
        "parameters": [],
        "inputs": [],
        "succeeded": True,
        "error_code": 0,
        "messages": [
            f"Executing (Buffer): {command}",
            "Start Time: Thursday, November 12, 2026 19:18:32",
            "Succeeded at Thursday, November 12, 2026 19:18:35",
        ],
    }


def _fixture(tmp_path: Path, command=None, xml_text=None):
    container = tmp_path / "test.gdb"
    container.mkdir(exist_ok=True)
    output = container / "model_buffer"
    output.write_bytes(b"out")
    (container / "fishnet").write_bytes(b"in")
    command = command or _command(output)
    capture = _capture(output, command)
    metadata = types.SimpleNamespace(Metadata=lambda path: types.SimpleNamespace(
        xml=_xml(command) if xml_text is None else xml_text,
    ))
    arcpy = types.ModuleType("arcpy")
    arcpy.metadata = metadata
    arcpy.GetParameterInfo = lambda tool: _params()
    arcpy.Exists = lambda path: Path(path).exists()
    arcpy.GetCount_management = lambda value: types.SimpleNamespace(getOutput=lambda index: "0")
    layer = types.SimpleNamespace(dataSource=str(output.parent / "fishnet"))
    project = types.SimpleNamespace(listMaps=lambda: [
        types.SimpleNamespace(listLayers=lambda name: [layer]),
    ])
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda path: project)
    capture["project_path"] = str(tmp_path / "test.aprx")
    return capture, arcpy


def test_single_buffer_is_reconstructed_with_parent_and_inner_evidence(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    assert "coverage_gap" not in result
    assert result["tool"] == "analysis.Buffer"
    assert result["inputs_hashed"] == "after_run"
    assert result["timing_scope"] == "parent_model"
    evidence = result["model_evidence"]
    assert evidence["parent_run_id"] == "parent-1"
    assert evidence["history_tool"] == "t.Model"
    assert evidence["captured_launch"] == "geoprocessing_pane"
    assert evidence["inner_step_ordinal"] == 1
    assert evidence["inner_step_source"] == "output_metadata_lineage"
    assert evidence["metadata_time_raw"] == "20261112T191834"
    assert evidence["observed_model_name"] is None
    params = {p["name"]: p for p in result["parameters"]}
    assert (
        params["in_features"]["path"].endswith("test.gdb/fishnet")
        or params["in_features"]["path"].endswith(r"test.gdb\fishnet")
    )
    assert params["in_features"]["resolution"] == "map_layer"
    assert params["out_feature_class"]["path"].endswith("model_buffer")
    assert params["dissolve_field"]["value"] is None
    assert params["method"]["value"] == "PLANAR"
    assert params["buffer_distance_or_field"]["value"] == "1 Meters"


def test_missing_executing_message_is_a_gap_not_timestamp_correlation(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["messages"] = ["Start Time: only metadata time exists"]
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    assert "missing executing message" in result["coverage_gap"]
    assert result["parameters"] == []


def test_duplicate_executing_messages_are_rejected(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["messages"].insert(1, capture["messages"][0])
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "multiple executing steps" in model.enrich(capture)["coverage_gap"]


def test_missing_metadata_is_an_explicit_gap(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path, xml_text="")
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "missing metadata" in model.enrich(capture)["coverage_gap"]


def test_duplicate_matching_lineage_is_rejected(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path, xml_text=_xml(
        _command(tmp_path / "test.gdb" / "model_buffer"), duplicates=True))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "multiple matching lineage processes" in model.enrich(capture)["coverage_gap"]


def test_command_mismatch_is_not_rewritten_into_a_match(tmp_path, monkeypatch):
    output = tmp_path / "test.gdb" / "model_buffer"
    capture, arcpy = _fixture(tmp_path, xml_text=_xml(
        _command(output).replace("1 Meters", "2 Meters")))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "no matching lineage process" in model.enrich(capture)["coverage_gap"]


def test_unresolved_input_is_named_for_the_partial_capture(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    (tmp_path / "test.gdb" / "fishnet").unlink()
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    assert "coverage_gap" not in result
    params = {p["name"]: p for p in result["parameters"]}
    assert params["in_features"]["unresolved"] == ["fishnet"]
    assert params["in_features"]["resolution"] == "map_layer"


def test_multiple_inner_steps_are_out_of_scope(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    output = tmp_path / "test.gdb" / "model_buffer"
    capture["messages"].insert(1, f"Executing (Clip): Clip fishnet other {output}")
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "multiple executing steps" in model.enrich(capture)["coverage_gap"]


def test_geodatabase_layer_existence_uses_arcpy_not_plain_files(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    (tmp_path / "test.gdb" / "fishnet").unlink()
    arcpy.Exists = lambda path: str(path).endswith("fishnet")
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    assert "coverage_gap" not in result
    params = {p["name"]: p for p in result["parameters"]}
    assert params["in_features"]["unresolved"] == []


def test_retry_after_gap_clears_the_gap_and_preserves_parent_identity(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    original_messages = list(capture["messages"])
    capture["messages"] = []
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    first = model.enrich(capture)
    assert first["coverage_gap"] == "missing executing message"

    capture = first
    capture["messages"] = original_messages
    second = model.enrich(capture)

    assert "coverage_gap" not in second
    evidence = second["model_evidence"]
    assert evidence["history_tool"] == "t.Model"
    assert evidence["parent_run_id"] == "parent-1"


def test_repeated_enrichment_never_rewrites_history_tool(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["observed_model_name"] = "ProvenanceBufferV2"
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    first = model.enrich(capture)
    assert model.is_model_capture(first) is True
    second = model.enrich(first)
    third = model.enrich(second)

    assert third["model_evidence"]["history_tool"] == "t.Model"
    assert third["model_evidence"]["parent_run_id"] == "parent-1"
    assert third["model_evidence"]["observed_model_name"] == "ProvenanceBufferV2"


def test_wrong_tool_source_is_not_relabelled_analysis_buffer(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path, xml_text=_xml(
        _command(tmp_path / "test.gdb" / "model_buffer")).replace(
            "Analysis Tools.tbx", "Custom Tools.tbx"))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "no matching lineage process" in model.enrich(capture)["coverage_gap"]


def test_stale_identical_command_is_not_parent_correlation(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path, xml_text=_xml(
        _command(tmp_path / "test.gdb" / "model_buffer")).replace(
            'Date="20261112" Time="191834"', 'Date="20200101" Time="000000"'))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "no matching lineage process" in model.enrich(capture)["coverage_gap"]


def test_parent_success_alone_is_not_inner_success(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["messages"] = [capture["messages"][0], "Succeeded at parent model only"]
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "inner success not evidenced" in model.enrich(capture)["coverage_gap"]


def test_relative_input_without_map_evidence_is_not_guessed(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda path: types.SimpleNamespace(
        listMaps=lambda: [],
    ))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    params = {p["name"]: p for p in result["parameters"]}
    assert params["in_features"]["unresolved"] == ["fishnet"]
    assert params["in_features"]["resolution"] != "output_container"


def test_named_model_without_english_history_is_a_gap(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["tool"] = "t.ProvenanceBufferV2"
    capture["messages"] = ["localized model history without an English marker"]
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "missing executing message" in model.enrich(capture)["coverage_gap"]


def test_ordinary_tool_is_not_reclassified_by_executing_text(tmp_path):
    capture, _ = _fixture(tmp_path)
    capture["tool"] = "analysis.Buffer"
    capture["capture_kind"] = "tool"

    assert model.is_model_capture(capture) is False


def test_malformed_quoting_and_missing_parent_times_are_gaps(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["messages"][0] = 'Executing (Buffer): Buffer fishnet "unclosed'
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "invalid executing command" in model.enrich(capture)["coverage_gap"]

    capture, arcpy = _fixture(tmp_path)
    del capture["started_at"]
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)
    assert "missing parent timing" in model.enrich(capture)["coverage_gap"]


def test_missing_metadata_time_is_not_none_t_none(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path, xml_text=_xml(
        _command(tmp_path / "test.gdb" / "model_buffer")).replace(
            'Date="20261112" Time="191834"', 'Date="20200101" Time="000000"'))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)
    assert "NoneTNone" not in result.get("model_evidence", {}).get("metadata_time_raw", "")


def test_italian_history_month_is_accepted(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["started_at"] = "2026-11-13T10:20:13Z"
    capture["finished_at"] = "2026-11-13T10:20:14Z"
    capture["messages"] = [
        capture["messages"][0],
        "Start Time: venerdì 13 novembre 2026 11:20:13",
        "Succeeded at venerdì 13 novembre 2026 11:20:14",
    ]
    output = tmp_path / "test.gdb" / "model_buffer"
    capture["messages"][0] = capture["messages"][0].replace("191834", "112014")
    arcpy.metadata = types.SimpleNamespace(Metadata=lambda path: types.SimpleNamespace(
        xml=_xml(_command(output)).replace('Date="20261112" Time="191834"',
                                          'Date="20261113" Time="112014"'),
    ))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    assert "coverage_gap" not in result
    assert result["model_evidence"]["metadata_time_raw"] == "20261113T112014"


def test_quoted_output_path_with_spaces_is_preserved(tmp_path, monkeypatch):
    output = tmp_path / "test with space.gdb" / "model_buffer"
    command = _command(f'"{output}"')
    capture, arcpy = _fixture(tmp_path, command=command)
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    assert "coverage_gap" not in result
    params = {p["name"]: p for p in result["parameters"]}
    assert params["out_feature_class"]["value"].replace("\\", "/").endswith(
        "test with space.gdb/model_buffer"
    )


def test_final_tool_name_overrides_an_initially_unknown_kind(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["capture_kind"] = "unknown"
    capture["tool"] = "t.ProvenanceBufferV2"
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert model.is_model_capture(capture) is True


def test_script_tool_without_executing_marker_is_not_a_model(tmp_path):
    capture, _ = _fixture(tmp_path)
    capture["capture_kind"] = "model"
    capture["tool"] = "t.CustomScript"
    capture["messages"] = []

    assert model.is_model_capture(capture) is False


def test_relative_or_unsafe_output_paths_are_rejected(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["messages"][0] = capture["messages"][0].replace(
        str(tmp_path / "test.gdb" / "model_buffer"),
        r"..\outside.gdb\layer",
    )
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "output path is not absolute" in model.enrich(capture)["coverage_gap"]


def test_missing_input_layer_cannot_get_a_container_digest(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    arcpy.Exists = lambda path: False
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)
    params = {p["name"]: p for p in result["parameters"]}
    assert params["in_features"]["path"] is None
    assert params["in_features"]["paths"] == []
    assert params["in_features"]["unresolved"] == ["fishnet"]


def test_sentinel_in_a_path_is_rejected_not_rewritten(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    capture["messages"][0] = capture["messages"][0].replace(
        str(tmp_path / "test.gdb" / "model_buffer"),
        str(tmp_path / "test__PM_BACKSLASH__folder.gdb" / "model_buffer"),
    )
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "sentinel" in model.enrich(capture)["coverage_gap"]


def test_path_alias_inside_project_is_rejected(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    real_output = tmp_path / "test.gdb" / "model_buffer"
    alias_output = tmp_path / "alias.gdb" / "model_buffer"
    capture["messages"][0] = capture["messages"][0].replace(str(real_output), str(alias_output))
    original_resolve = Path.resolve

    def resolve(path):
        if path == alias_output:
            return real_output
        return original_resolve(path)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "path aliases are not supported" in model.enrich(capture)["coverage_gap"]


def test_map_layer_count_and_definition_query_survive(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    layer = arcpy.mp.ArcGISProject("test.aprx").listMaps()[0].listLayers("fishnet")[0]
    layer.definitionQuery = "OID <= 3"
    arcpy.GetCount_management = lambda value: types.SimpleNamespace(
        getOutput=lambda index: "9" if isinstance(value, str) else "3"
    )
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    result = model.enrich(capture)

    params = {p["name"]: p for p in result["parameters"]}
    filters = params["in_features"]["layer_filters"]
    assert filters[0]["layer"] == "fishnet"
    assert filters[0]["layer_count"] == 3
    assert "selection_count" not in filters[0]
    assert filters[0]["definition_query"] == "OID <= 3"
    assert filters[0]["scope"] == "after_run"


def test_same_source_with_different_filters_is_ambiguous(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    layer = arcpy.mp.ArcGISProject("test.aprx").listMaps()[0].listLayers("fishnet")[0]
    other = types.SimpleNamespace(dataSource=layer.dataSource, definitionQuery="OID > 3")
    project = types.SimpleNamespace(listMaps=lambda: [
        types.SimpleNamespace(listLayers=lambda name: [layer]),
        types.SimpleNamespace(listLayers=lambda name: [other]),
    ])
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda path: project)
    arcpy.GetCount_management = lambda value: types.SimpleNamespace(
        getOutput=lambda index: "9" if isinstance(value, str) else "3"
    )
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "ambiguous map-layer filters" in model.enrich(capture)["coverage_gap"]


def test_same_count_but_distinct_selections_are_ambiguous(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    layer = arcpy.mp.ArcGISProject("test.aprx").listMaps()[0].listLayers("fishnet")[0]
    layer.definitionQuery = "OID <= 3"
    layer.selected_oids = [1, 2, 3]
    other = types.SimpleNamespace(
        dataSource=layer.dataSource, definitionQuery="OID <= 3", selected_oids=[4, 5, 6]
    )
    project = types.SimpleNamespace(listMaps=lambda: [
        types.SimpleNamespace(listLayers=lambda name: [layer]),
        types.SimpleNamespace(listLayers=lambda name: [other]),
    ])
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda path: project)
    arcpy.GetCount_management = lambda value: types.SimpleNamespace(
        getOutput=lambda index: "9" if isinstance(value, str) else "3"
    )
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "ambiguous map-layer filters" in model.enrich(capture)["coverage_gap"]


def test_outside_map_source_is_rejected_before_any_arcgis_read(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    outside = tmp_path.parent / "outside.gdb" / "fishnet"
    layer = types.SimpleNamespace(dataSource=str(outside), definitionQuery=None)
    project = types.SimpleNamespace(listMaps=lambda: [
        types.SimpleNamespace(listLayers=lambda name: [layer]),
    ])
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda path: project)
    reads = []

    def get_count(value):
        reads.append(str(value))
        return types.SimpleNamespace(getOutput=lambda index: "0")

    arcpy.GetCount_management = get_count
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "outside the project workspace" in model.enrich(capture)["coverage_gap"]
    assert reads == []


def test_same_name_with_distinct_sources_is_ambiguous(tmp_path, monkeypatch):
    capture, arcpy = _fixture(tmp_path)
    layers = [
        types.SimpleNamespace(dataSource=str(tmp_path / f"{name}.gdb" / "fishnet"))
        for name in ("a", "b")
    ]
    project = types.SimpleNamespace(listMaps=lambda: [
        types.SimpleNamespace(listLayers=lambda name, layer=layer: [layer])
        for layer in layers
    ])
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda path: project)
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    assert "ambiguous map-layer filters" in model.enrich(capture)["coverage_gap"]
