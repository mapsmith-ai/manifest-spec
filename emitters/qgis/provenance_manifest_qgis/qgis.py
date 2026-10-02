"""Run a QGIS Processing algorithm and write a manifest beside each output.

Inside QGIS's own Python -- the Python console, a script, a plugin, or a
standalone script with ``qgis.core`` initialised::

    from provenance_manifest_qgis.qgis import run

    results, manifests = run("native:buffer", {
        "INPUT": "C:/data/wells.gpkg|layername=wells",
        "DISTANCE": 500,
        "OUTPUT": "C:/data/wells_500m.gpkg",
    })

``run`` takes the same arguments as ``processing.run`` and returns its
results with the paths of the manifests written. It is the minimal form of
the provider: runs started from the Toolbox, the model designer or the
history are not recorded yet. That is deliberate. A wrapper around
``processing.run`` sees every run made through it on every QGIS version,
while the post-execution hook of the Processing settings no longer fires on
QGIS 4 (measured by another project, GeoProvenance, on 4.2.1), so the
interactive capture needs its own design rather than a hook.

What a record holds, and why each part is there:

- **inputs, hashed before the run**, by the rule of section 3.3 (a shapefile
  by its member files, a file geodatabase by its listing), each naming the
  parameter it was read through (``inputs[].argument``, draft.10). A
  GeoPackage layer passed as ``path|layername=x`` is the file plus ``layer``.
- **the parameters the algorithm ran with**: the ones passed, plus each
  default the call left out -- section 3.2 asks for what ran, and a default
  is part of it.
- ``engine``: QGIS, its version, and the versions of GDAL, PROJ and GEOS,
  because those move answers: GDAL 3.11 changed what ``gdaldem slope`` does on
  a geographic raster.
- ``environment``: the ellipsoid and units of the processing context. They are
  configuration that changes the answer: ``$area`` with no ellipsoid on a
  geographic layer converts square degrees with an equatorial factor, 41% high
  at 45 degrees north.
- checks: ``input_crs_present``, ``inputs_share_crs``, ``crs_present`` and
  ``result_not_empty`` from the core vocabulary, and three of this producer's:
  ``algorithm_succeeded``, ``inputs_hashed``, and ``distance_not_in_degrees``
  -- a distance parameter applied to a layer in a geographic CRS is a number
  of degrees. The Processing dialog warns about it; run from code, QGIS says
  nothing, and the record does.

A run that fails still gets a record, and the error is raised afterwards: the
audit trail has to survive the error it documents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import record as rec
from .digest import DatasetDigest, dataset_digest

#: Parameter types (``QgsProcessingParameterDefinition.type()``) that name a
#: dataset read by the algorithm.
INPUT_TYPES = frozenset({"source", "vector", "raster", "layer", "multilayer", "mesh", "pointcloud"})
#: Destination types whose value, after the run, is a file a record can sit beside.
OUTPUT_TYPES = frozenset({"sink", "vectorDestination", "rasterDestination", "fileDestination"})


def _posix(value: str) -> str:
    return str(value).replace("\\", "/")


def split_layer(value: str) -> tuple[str, str | None]:
    """``C:/d/a.gpkg|layername=roads`` -> (``C:/d/a.gpkg``, ``roads``).

    QGIS appends OGR options after ``|``; only ``layername`` names a dataset,
    the rest (``layerid``, ``subset``, ``geometrytype``) do not change which
    bytes were read and are left in the parameters, where they are recorded.
    """
    path, _, options = str(value).partition("|")
    layer = None
    for option in options.split("|") if options else []:
        key, _, val = option.partition("=")
        if key.strip().lower() == "layername" and val:
            layer = val
    return path, layer


def _source_strings(value: Any) -> list[str]:
    """Every source string a parameter value names: layers, definitions, lists."""
    from qgis.core import QgsMapLayer, QgsProcessingFeatureSourceDefinition

    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _source_strings(item)]
    if isinstance(value, QgsProcessingFeatureSourceDefinition):
        return [value.source.staticValue()]
    if isinstance(value, QgsMapLayer):
        return [value.source()]
    return [str(value)]


def _crs_of(source: str) -> tuple[str | None, bool | None]:
    """The CRS a source declares, and whether it is geographic; (None, None) if none."""
    from qgis.core import QgsRasterLayer, QgsVectorLayer

    layer = QgsVectorLayer(source, "provenance-probe", "ogr")
    if not layer.isValid():
        layer = QgsRasterLayer(source, "provenance-probe")
    if not layer.isValid() or not layer.crs().isValid():
        return None, None
    crs = layer.crs()
    return (crs.authid() or "unnamed CRS"), crs.isGeographic()


def _count(source: str) -> int | None:
    from qgis.core import QgsVectorLayer

    layer = QgsVectorLayer(source, "provenance-probe", "ogr")
    return int(layer.featureCount()) if layer.isValid() else None


def _engine() -> dict:
    from osgeo import gdal
    from qgis.core import Qgis, QgsProjUtils

    proj = f"{QgsProjUtils.projVersionMajor()}.{QgsProjUtils.projVersionMinor()}"
    return {
        "name": "QGIS",
        "version": Qgis.version(),
        f"{rec.PREFIX}:gdal": gdal.__version__,
        f"{rec.PREFIX}:proj": proj,
        f"{rec.PREFIX}:geos": Qgis.geosVersion(),
    }


def _environment(context) -> dict[str, str]:
    from qgis.core import QgsUnitTypes

    return {
        "ellipsoid": context.ellipsoid() or "NONE",
        "distance_unit": QgsUnitTypes.toString(context.distanceUnit()),
        "area_unit": QgsUnitTypes.toString(context.areaUnit()),
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return str(value)


class _Feedback:
    """Collects what the algorithm reports, and passes it on to the caller's feedback."""

    def __new__(cls, forward=None):
        from qgis.core import QgsProcessingFeedback

        class Collecting(QgsProcessingFeedback):
            def __init__(self):
                super().__init__()
                self.messages: list[dict] = []

            def pushInfo(self, info):
                self.messages.append({"severity": "info", "text": info})
                if forward is not None:
                    forward.pushInfo(info)

            def pushWarning(self, warning):
                self.messages.append({"severity": "warning", "text": warning})
                if forward is not None:
                    forward.pushWarning(warning)

            def reportError(self, error, fatalError=False):
                self.messages.append({"severity": "error", "text": error})
                if forward is not None:
                    forward.reportError(error, fatalError)

        return Collecting()


def run(algorithm_id: str, parameters: dict, context=None, feedback=None):
    """``processing.run`` with provenance. Returns ``(results, [manifest paths])``."""
    import processing
    from qgis.core import QgsApplication, QgsProcessingContext

    algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
    if algorithm is None:
        raise ValueError(f"no Processing algorithm {algorithm_id!r} is registered")
    definitions = {d.name(): d for d in algorithm.parameterDefinitions()}
    unknown = set(parameters) - set(definitions)
    if unknown:
        raise TypeError(
            f"{algorithm_id} has no parameter(s) {sorted(unknown)}; it has {sorted(definitions)}"
        )
    context = context or QgsProcessingContext()
    collecting = _Feedback(feedback)

    inputs: list[DatasetDigest] = []
    input_arguments: list[str] = []
    unhashed: list[str] = []
    input_crs: dict[str, tuple[str | None, bool | None]] = {}
    for name, definition in definitions.items():
        if definition.type() not in INPUT_TYPES or name not in parameters:
            continue
        for source in _source_strings(parameters[name]):
            path, layer = split_layer(source)
            try:
                digest = dataset_digest(path)
            except (OSError, ValueError) as exc:
                unhashed.append(f"{name}={_posix(source)} ({exc})")
                continue
            if layer is not None:
                digest = DatasetDigest(
                    digest.path, digest.sha256, digest.kind, layer, digest.members
                )
            inputs.append(digest)
            input_arguments.append(name)
            input_crs[source] = _crs_of(source)

    environment = _environment(context)
    started = rec.utcnow()
    results: dict | None = None
    raised: BaseException | None = None
    try:
        results = processing.run(algorithm_id, parameters, context=context, feedback=collecting)
    except Exception as exc:  # the record must survive any failure, then it propagates
        raised = exc
        collecting.messages.append({"severity": "error", "text": f"{type(exc).__name__}: {exc}"})
    finished = rec.utcnow()

    # What ran: the parameters passed, and the default of every one left out.
    ran_with: dict = {}
    for name, definition in definitions.items():
        value = parameters[name] if name in parameters else definition.defaultValue()
        if definition.type() in INPUT_TYPES or definition.type() in OUTPUT_TYPES:
            value = (
                [_posix(s) for s in _source_strings(value)]
                if isinstance(value, (list, tuple))
                else (_posix(_source_strings(value)[0]) if value is not None else None)
            )
        ran_with[name] = _json_value(value)

    checks: list[dict] = [
        rec.check(
            f"{rec.PREFIX}:algorithm_succeeded",
            raised is None,
            f"{algorithm_id} returned {sorted(results)}"
            if raised is None
            else f"{algorithm_id} raised {type(raised).__name__}: {raised}",
        )
    ]
    if input_crs:
        missing = [s for s, (crs, _) in input_crs.items() if crs is None]
        checks.append(
            rec.check(
                "input_crs_present",
                not missing,
                "every input declares a CRS: "
                + ", ".join(sorted({c for c, _ in input_crs.values() if c}))
                if not missing
                else f"no CRS declared by: {', '.join(_posix(s) for s in missing)}",
            )
        )
        declared = {c for c, _ in input_crs.values() if c}
        if len(input_crs) > 1:
            checks.append(
                rec.check("inputs_share_crs", len(declared) == 1, f"input CRSs: {sorted(declared)}")
            )
    if unhashed:
        checks.append(
            rec.check(
                f"{rec.PREFIX}:inputs_hashed",
                False,
                "not a dataset on disk, so no digest could be recorded: " + "; ".join(unhashed),
            )
        )
    for name, definition in definitions.items():
        if definition.type() != "distance" or name not in ran_with:
            continue
        parent = definition.parentParameterName()
        sources = _source_strings(parameters.get(parent))
        geographic = [s for s in sources if _crs_of(s)[1]]
        if geographic:
            checks.append(
                rec.check(
                    f"{rec.PREFIX}:distance_not_in_degrees",
                    False,
                    f"{name}={ran_with[name]} was applied to {parent}, which is in "
                    f"{_crs_of(geographic[0])[0]}, a geographic CRS: the distance is in degrees",
                )
            )

    engine = _engine()
    manifests: list[Path] = []
    for name, definition in definitions.items():
        if definition.type() not in OUTPUT_TYPES:
            continue
        value = (results or {}).get(name) or parameters.get(name)
        if not isinstance(value, str) or not value or value == "TEMPORARY_OUTPUT":
            continue
        path, layer = split_layer(value)
        out_checks = list(checks)
        crs = None
        try:
            digest = dataset_digest(path)
        except (OSError, ValueError):
            digest = None  # a failed run, or a memory layer: no file to describe
        if digest is not None and layer is not None:
            digest = DatasetDigest(digest.path, digest.sha256, digest.kind, layer, digest.members)
        if digest is not None and raised is None:
            crs, _ = _crs_of(value)
            out_checks.append(
                rec.check(
                    "crs_present",
                    crs is not None,
                    f"output declares {crs}" if crs else "output declares no CRS",
                )
            )
            n = _count(value)
            if n is not None:
                out_checks.append(
                    rec.check("result_not_empty", n > 0, f"output has {n} feature(s)")
                )
        record = rec.build(
            operation=algorithm_id,
            parameters=ran_with,
            inputs=inputs,
            input_arguments=input_arguments,
            output=digest,
            output_crs=crs,
            engine=engine,
            checks=out_checks,
            started_at=started,
            finished_at=finished,
            environment=environment,
            messages=collecting.messages,
        )
        target = rec.sidecar_path(digest or DatasetDigest(_posix(path), "0" * 64, "file", layer))
        manifests.append(rec.write(record, target))

    if raised is not None:
        raise raised
    return results, manifests
