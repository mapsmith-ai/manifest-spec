"""Check what one autotest run of the add-in produced. Exit 0 only if all expected holds.

Expected, from the sequence in Autotest.cs: a manifest beside the container for
at_fishnet, at_buffer, at_buffer_from_layer and at_copy; each valid under the
specification's validator; inputs hashed at start for the three runs that went
to the history, after the run for CopyFeatures (run without it); the buffer from
a layer name resolved to the dataset behind the layer.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "validator"))
import validate

project = Path(sys.argv[1])
gdb = next(project.glob("*.gdb")).name
prefix = "x-provenance-manifest-arcgis-pro:"
expected = {
    "at_fishnet": ("CreateFishnet_management", "at tool start", []),
    "at_buffer": ("Buffer_analysis", "at tool start", ["at_fishnet"]),
    "at_buffer_from_layer": ("Buffer_analysis", "at tool start", ["at_fishnet"]),
    "at_copy": ("CopyFeatures_management", "after the run", ["at_buffer"]),
}
failures = []
for layer, (operation, timing, input_layers) in expected.items():
    manifest = project / f"{gdb}.{layer}.provenance.json"
    if not manifest.exists():
        failures.append(f"{layer}: no manifest at {manifest.name}")
        continue
    record = json.loads(manifest.read_text(encoding="utf-8"))
    problems = validate.problems(record)
    if problems:
        failures.append(f"{layer}: invalid: {problems}")
    if record.get("operation") != operation:
        failures.append(f"{layer}: operation {record.get('operation')!r}, expected {operation!r}")
    taken = record.get(prefix + "input_digests_taken", "")
    if not taken.startswith(timing):
        failures.append(f"{layer}: inputs hashed {taken!r}, expected {timing!r}")
    got_layers = [i.get("layer") for i in record.get("inputs", [])]
    if got_layers != input_layers:
        failures.append(f"{layer}: input layers {got_layers}, expected {input_layers}")
    if (record.get("output") or {}).get("layer") != layer:
        failures.append(f"{layer}: output.layer {(record.get('output') or {}).get('layer')!r}")
    checks = {c["name"]: c["passed"] for c in record["verification"]}
    print(f"{layer}: {operation} | inputs {got_layers} | hashed {taken[:20]} | checks {checks}")

# In-place edits on at_edit: CopyFeatures created it, AddField and CalculateField
# edited it. The live record is CalculateField's; the two before it are kept
# under dated names, each still a valid *.provenance.json.
live = project / f"{gdb}.at_edit.provenance.json"
if not live.exists():
    failures.append("at_edit: no live manifest")
else:
    record = json.loads(live.read_text(encoding="utf-8"))
    if record.get("operation") != "CalculateField_management":
        failures.append(f"at_edit: live record is {record.get('operation')!r}")
    if record.get(prefix + "writes_to_input") is not True:
        failures.append("at_edit: live record does not declare writes_to_input")
    previous = record.get(prefix + "previous_record")
    if not previous or not (project / previous).exists():
        failures.append(f"at_edit: previous_record {previous!r} missing")
    kept = sorted(project.glob(f"{gdb}.at_edit.*.provenance.json"))
    kept_ops = sorted(json.loads(k.read_text(encoding="utf-8")).get("operation") for k in kept)
    if kept_ops != ["AddField_management", "CopyFeatures_management"]:
        failures.append(f"at_edit: kept records {kept_ops}")
    for k in [*kept, live]:
        problems = validate.problems(json.loads(k.read_text(encoding="utf-8")))
        if problems:
            failures.append(f"{k.name}: invalid: {problems}")
    print(f"at_edit: live {record.get('operation')} | kept {kept_ops} | "
          f"{record.get(prefix + 'input_digests_taken', '')[:70]}")

log = Path(os.environ["LOCALAPPDATA"]) / "ProvenanceManifest" / "addin.log"
if log.exists():
    for line in log.read_text(encoding="utf-8").splitlines():
        # "-error " is how Emitter.cs logs an exception; "error=0" is a tool's
        # success code and matched a plain "error" test on the first run.
        step = " python start " in line or " python finish " in line
        if "-error " in line or (step and "exit=0" not in line) or "timed out" in line \
                or ("error=" in line and "error=0" not in line):
            failures.append("log: " + line[:300])
if log.exists():
    lines = log.read_text(encoding="utf-8").splitlines()
    history = [line for line in lines if " history-item " in line]
    # A measurement, not a pass/fail: does the history event fire for runs that
    # go to the project history? Six runs of the autotest do.
    print(f"history items seen by ProjectItemsChangedEvent: {len(history)}")
    for line in history[:3]:
        print("   ", line[28:200])
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
