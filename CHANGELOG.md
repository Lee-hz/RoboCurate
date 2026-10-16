# 2026-10-16 · MiniMax VLM review update

- Unified reference-driven review: shared camera/3D playback, stage timeline, actual model inputs and joint feedback, and separate human review.
- Consistent library typography and VLM review filters; recoverable analysis failures and elapsed-time feedback.
- Added local MiniMax connection form with private per-install credentials, redacted settings API, disconnect and active-job guards; new reviews reject non-MiniMax models.
- Source package now includes taskflow and curation modules. No private recordings, credentials, review database or inference traces are packaged.
- Kept contributor attribution and directory rescan. The published application runs on loopback for individual local use; the earlier default LAN launcher is replaced.
- Updated historical export tests with explicit synthetic admission fixtures; these fixtures never alter production reviews or claim measured model accuracy.

## Unreleased — 2026-10-09 — stage execution quality

- Add an in-workbench presentation demo for 24 recorded simulations: world-coordinate robot/object replay, synchronized cached camera frames, low-speed interval locations and explicit same-batch reference comparisons. Illustration geometry and provisional grades are labelled; no new MuJoCo optimal rollout is claimed.
- Quantify 23 execution indicators with formulas, units, data requirements and explicitly provisional engineering limits. Add bounded 100 Hz time-weighted IMU summaries, separate native peaks, sustained excursions and debounced hand-closure candidates.
- Keep unmeasured geometry/contact criteria unknown. Recompute all 18 recordings and publish local descriptive reports without treating duration distributions as qualified references or trial-range values as safe execution.
- Add stage execution checks for safe approach, accurate grasp, stable transport, accurate placement, and safe withdrawal of both the arm and the whole robot.
- Measure candidate duration and native motion evidence; allow reviewed interval corrections and recompute evidence before saving.
- Compare duration with an explicit, documented target only after confirming execution requirements and interval completeness. Unknowns and failures cannot be offset by speed.
- Save human decisions and evidence in separate revisioned audit tables. Stage predictions, existing grades and export admission are unchanged.
- Validate all 18 local recordings, backend decision guards, and browser review/save/reload behavior in an isolated workspace. No automated safety or task-success certification is claimed.

## v0.1.0-preview.3 — complete training source and model distribution

- Publish the remaining research/training, calibration, ablation, validation and historical delivery scripts with frozen protocols and a source index.
- Distribute the exact four installed DINOv2-based models plus the pinned backbone as a separate 93.68 MB model ZIP.
- Add checksum-verified, conflict-preserving online/offline installation and a real model forward-pass verifier.
- Exercise the previously external training helpers in source CI. Private recordings, labels, features, credentials and review state remain excluded.
- No new model training or accuracy improvement is claimed in this packaging release.

# Changes

## v0.1.0-preview.2 — 2026-09-18

- Update the interface gallery with measured pose ghosts, recorded control-target poses and target trajectories, captured directly from the application.
- Explain the visual overlays and provide a matching source download.

## v0.1.0-preview.1 — 2026-09-18

- Rename the application to RoboCurate and migrate saved browser preferences.
- Reduce review navigation to Task, Quality checks and Review; move advanced tools into disclosures.
- Keep one synchronized progress curve and switch quality/task timelines with the active view.
- Show current model evidence and actionable review intervals without duplicate summary cards.
- Change ratings, dimensions, API values and new exports to ten points; preserve grade gates and percentage metrics.
- Add a portable synthetic MCAP demo and an end-to-end review/export test with no private recording.
- Remove machine-specific default recording paths and inventory third-party origins.
- Provide source-only packaging, download instructions and GitHub Actions tests under Lee-hz/RoboCurate; keep the unresolved base-viewer license review explicit.
- Show actual G1 camera, robot and stage-model screenshots in the README, with the synthetic example kept in a separate disclosure.
- Include SciPy in development dependencies so WARP sampler parity checks run on a fresh CI installation.
