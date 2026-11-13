"""Fail-closed reconstruction of one ModelBuilder operation.

History identifies the parent model and the inner command, while the output's
metadata supplies the canonical lineage process. Only one inner operation and
one identified output are supported. Every ambiguity is a coverage gap.
"""

from __future__ import annotations

import os
import re
import shlex
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKSLASH = "__PM_BACKSLASH__"
_EXECUTING = re.compile(r"^Executing \(([^)]+)\):\s*(.*)$")
_ISO_LOCAL = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_NAMED_LOCAL = re.compile(r"(?:\w+ \d{1,2},|\d{1,2} \w+) \d{4} \d{2}:\d{2}:\d{2}")


def _gap(capture: dict, reason: str) -> dict:
    result = dict(capture)
    result["coverage_gap"] = reason
    return result


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _tokens(command: str) -> list[str]:
    if _BACKSLASH in command:
        raise ValueError("sentinel in command")
    protected = command.replace("\\", _BACKSLASH)
    return [_unquote(token).replace(_BACKSLASH, "\\")
            for token in shlex.split(protected, posix=True)]


def _comparison_tokens(command: str) -> list[str]:
    return [token.lower() for token in _tokens(command)]


def _executing_steps(messages: list[str]) -> list[tuple[str, str]]:
    steps = []
    for message in messages:
        match = _EXECUTING.match(message)
        if match:
            steps.append((match.group(1), match.group(2)))
    return steps


def is_model_capture(capture: dict) -> bool:
    tool = str(capture.get("tool") or "").lower()
    candidate = (
        bool(capture.get("model_evidence")) or tool.endswith(".model") or tool.startswith("t.")
    )
    return candidate and bool(_executing_steps(capture.get("messages") or []))


def _metadata_processes(output: Path):
    import arcpy

    xml = arcpy.metadata.Metadata(str(output)).xml
    if not xml:
        raise ValueError("missing metadata")
    root = ET.fromstring(xml)
    return root.findall(".//lineage/Process")


def _process_tokens(process) -> list[str]:
    return _comparison_tokens(process.text or "")


def _parent_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _local_instant(message: str) -> datetime | None:
    match = _ISO_LOCAL.search(message)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    named = _NAMED_LOCAL.search(message)
    if not named:
        return None
    words = named.group(0).replace(",", "").split()
    if words[0].isdigit():
        day, month_name, year, clock = words
    else:
        month_name, day, year, clock = words
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
        "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    }
    month = months.get(month_name.lower())
    if month is None:
        return None
    hour, minute, second = (int(part) for part in clock.split(":"))
    return datetime(int(year), month, int(day), hour, minute, second, tzinfo=timezone.utc)


def _inner_bounds(capture: dict) -> tuple[datetime, datetime, datetime]:
    messages = capture.get("messages") or []
    executing = next((index for index, message in enumerate(messages)
                      if _EXECUTING.match(message)), None)
    if executing is None:
        raise ValueError("inner success not evidenced")
    start_message = next((message for message in messages[executing + 1:]
                          if message.startswith("Start Time:")), None)
    success_message = next((message for message in messages[executing + 1:]
                            if message.startswith("Succeeded at")), None)
    if start_message is None or success_message is None:
        raise ValueError("inner success not evidenced")
    inner_start = _local_instant(start_message)
    inner_success = _local_instant(success_message)
    if inner_start is None or inner_success is None:
        raise ValueError("inner success not evidenced")
    parent_start = _parent_instant(capture["started_at"])
    offset = inner_start - parent_start
    nearest_hour = round(offset.total_seconds() / 3600) * 3600
    if abs(offset.total_seconds() - nearest_hour) > 300 or abs(offset.total_seconds()) > 14 * 3600:
        raise ValueError("unvalidated timezone offset")
    return inner_start, inner_success, timedelta(seconds=nearest_hour)


def _metadata_time_raw(process) -> datetime:
    raw = f"{process.get('Date')}T{process.get('Time')}"
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("missing metadata time") from exc


def _matching_processes(output: Path, tool: str, command: str, capture: dict):
    inner_start, inner_success, offset = _inner_bounds(capture)
    expected = _comparison_tokens(command)
    matches = []
    for process in _metadata_processes(output):
        source = (process.get("ToolSource") or "").replace("\\", "/").lower()
        if (process.get("Name") or "").casefold() != tool.casefold():
            continue
        if not source.endswith("analysis tools.tbx/buffer"):
            continue
        if _process_tokens(process) != expected:
            continue
        process_time = _metadata_time_raw(process) - offset
        if inner_start - offset <= process_time <= inner_success - offset:
            matches.append(process)
    return matches


def _project_root(capture: dict) -> Path:
    project_path = capture.get("project_path")
    if not project_path:
        raise ValueError("missing project path for path containment")
    return Path(project_path).resolve().parent


def _safe_path(value: str, capture: dict) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("output path is not absolute")
    if value.startswith(("\\\\", "//")):
        raise ValueError("network paths are not supported")
    if ".." in path.parts:
        raise ValueError("path traversal is not supported")
    absolute = Path(os.path.abspath(path))
    resolved = path.resolve()
    if os.path.normcase(str(absolute)) != os.path.normcase(str(resolved)):
        raise ValueError("path aliases are not supported")
    try:
        resolved.relative_to(_project_root(capture))
    except ValueError as exc:
        raise ValueError("path is outside the project workspace") from exc
    return resolved


def _map_input_source(capture: dict, value: str):
    project_path = capture.get("project_path")
    if not project_path:
        return None, None, "unresolved"
    import arcpy

    project = arcpy.mp.ArcGISProject(project_path)
    layers = [
        (layer, _safe_path(str(layer.dataSource), capture))
        for map_ in project.listMaps()
        for layer in map_.listLayers(value)
        if getattr(layer, "dataSource", None)
    ]
    if len(layers) > 1:
        raise ValueError("ambiguous map-layer filters")
    sources = {os.path.normcase(str(source)) for _, source in layers}
    if len(sources) != 1:
        return None, None, "unresolved"
    layer, source = layers[0]
    count = int(arcpy.GetCount_management(layer).getOutput(0))
    total = int(arcpy.GetCount_management(source).getOutput(0))
    filters = {
        "layer": value,
        "layer_count": count,
        "source_count": total,
        "definition_query": getattr(layer, "definitionQuery", None),
        "scope": "after_run",
    }
    evidence = filters if count != total or filters["definition_query"] else None
    return source.as_posix(), evidence, "map_layer"


def _parameter(parameter, value: str, output: Path, capture: dict) -> dict:
    is_input = parameter.direction == "Input"
    dataset = parameter.name in ("in_features", "out_feature_class")
    result = {
        "name": parameter.name,
        "type": parameter.datatype,
        "value": value if value != "#" else None,
        "is_input": is_input,
        "dataset": dataset,
        "path": None,
        "paths": [],
        "unresolved": [],
    }
    if not dataset:
        return result
    if parameter.name == "out_feature_class":
        resolved = _safe_path(value, capture)
        result["path"] = resolved.as_posix()
        result["paths"] = [resolved.as_posix()]
        return result

    import arcpy

    if Path(value).is_absolute():
        candidate = _safe_path(value, capture)
        resolution = "absolute_path"
        filter_evidence = None
    else:
        source, filter_evidence, resolution = _map_input_source(capture, value)
        if source is None:
            result["resolution"] = resolution
            result["unresolved"] = [value]
            return result
        candidate = _safe_path(source, capture)
    if not arcpy.Exists(str(candidate)):
        result["resolution"] = resolution
        result["unresolved"] = [value]
        return result
    result["path"] = candidate.as_posix()
    result["paths"] = [candidate.as_posix()]
    result["resolution"] = resolution
    if filter_evidence:
        result["layer_filters"] = [filter_evidence]
    return result


def enrich(capture: dict) -> dict:
    if not capture.get("started_at") or not capture.get("finished_at"):
        return _gap(capture, "missing parent timing")
    if not capture.get("succeeded") or capture.get("error_code") != 0:
        return _gap(capture, "parent run not successful")
    steps = _executing_steps(capture.get("messages") or [])
    if not steps:
        return _gap(capture, "missing executing message")
    if len(steps) != 1:
        return _gap(capture, "multiple executing steps")
    tool, command = steps[0]
    if tool.casefold() != "buffer":
        return _gap(capture, f"unsupported inner operation: {tool}")
    try:
        _inner_bounds(capture)
        tokens = _tokens(command)
        if len(tokens) < 3:
            raise ValueError("invalid executing command")
        output = _safe_path(tokens[2], capture)
        import arcpy
        definitions = list(arcpy.GetParameterInfo("analysis.Buffer"))
        arguments = tokens[1:]
        if len(arguments) != len(definitions):
            return _gap(capture, "parameter count differs from tool schema")
        parameters = [
            _parameter(definition, _unquote(value), output, capture)
            for definition, value in zip(definitions, arguments, strict=True)
        ]
        process = None
        if arcpy.Exists(str(output)):
            matches = _matching_processes(output, tool, command, capture)
            if not matches:
                return _gap(capture, "no matching lineage process")
            if len(matches) != 1:
                return _gap(capture, "multiple matching lineage processes")
            process = matches[0]
            arguments = _tokens(process.text or "")[1:]
            if len(arguments) != len(definitions):
                return _gap(capture, "parameter count differs from tool schema")
            parameters = [
                _parameter(definition, _unquote(value), output, capture)
                for definition, value in zip(definitions, arguments, strict=True)
            ]
    except ValueError as exc:
        if "closing quotation" in str(exc).lower():
            return _gap(capture, "invalid executing command")
        return _gap(capture, str(exc))
    except (OSError, RuntimeError, AttributeError, ET.ParseError) as exc:
        return _gap(capture, str(exc))

    result = dict(capture)
    result.pop("coverage_gap", None)
    result["tool"] = "analysis.Buffer"
    result["capture_kind"] = "model"
    result["parameters"] = parameters
    result["inputs_hashed"] = "after_run"
    result["timing_scope"] = "parent_model"
    previous_evidence = capture.get("model_evidence") or {}
    result["model_evidence"] = {
        "parent_run_id": capture.get("run_id"),
        "history_tool": previous_evidence.get("history_tool") or capture.get("tool"),
        "captured_launch": previous_evidence.get("captured_launch") or capture.get("launch"),
        "observed_model_name": (
            previous_evidence.get("observed_model_name") or capture.get("observed_model_name")
        ),
        "inner_step_ordinal": 1,
        "inner_step_source": (
            "output_metadata_lineage" if process is not None else "history_executing_message"
        ),
        "metadata_time_raw": (
            f"{process.get('Date')}T{process.get('Time')}" if process is not None else None
        ),
        "input_resolution": {
            parameter["name"]: parameter.get("resolution")
            for parameter in parameters if parameter["name"] == "in_features"
        },
        "inner_success_evidence": next(
            message for message in capture.get("messages") or []
            if message.startswith("Succeeded at")
        ),
    }
    return result
