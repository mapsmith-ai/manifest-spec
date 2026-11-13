# Changelog

All notable changes to this repository are documented here. The specification and its
emitters use draft pre-release labels until the independence condition in section 1 is met.

## [1.0.0-draft.12] - 2026-11-13

### Added

- **Narrow, fail-closed ModelBuilder coverage in the ArcGIS Pro add-in.** One interactive
  model with exactly one directly executed `analysis.Buffer` and one identified output can
  now produce a manifest for the inner operation. Parent and inner identity, success and
  timing stay separate; history and output metadata must agree. Multi-step, nested,
  iterating, concurrent, repeated, failed, cancelled, ambiguous and localized-without-
  `Executing` runs are explicit coverage gaps rather than guessed records.
- **After-run input evidence for the supported ModelBuilder path.** Inputs resolve only
  through confined absolute paths or one unique project map layer. Layer filters record
  neutral layer/source counts, digest times remain distinct, and same-container input/output
  limitations are disclosed. A missing output retains a manifest with a failed digest check.

### Fixed

- **Harden ModelBuilder path and output handling.** Reject UNC, traversal, aliases and
  outside-project sources before ArcGIS reads them; refuse ambiguous layer names; and write
  sidecars by atomic replacement so an existing hard-linked sidecar cannot overwrite its
  other target.

The normative record shape is unchanged from draft.11.

## [1.0.0-draft.11] - 2026-11-02

### Fixed

- Treat Windows directory junctions and mount points as non-followed links in multi-file
  dataset fingerprints, consistently in the specification, reference digest and emitters.
- Clarify that an engine-reported accuracy of `-1` does not decide `is_ballpark`.
