# Source package contents

Build a local source package from the app source directory:

```bash
python3 scripts/build_source_candidate.py --label vlm-minimax-20261016
```

The builder creates a new directory and ZIP under `dist/`; existing outputs are never overwritten. `SOURCE_MANIFEST.json` records each selected file's size and SHA-256. ZIP CRC and file hashes are verified, with a companion checksum and verification report.

Files are selected with an explicit allowlist. Application code, frontend assets, model implementation, full project training/research scripts, frozen protocols, model-install metadata, synthetic tests, the demo generator, robot assets, attribution and CI configuration are included. Workspace databases, raw recordings, weights, cached features, private study inputs, browser profiles and login state are excluded. Credential-pattern checks supplement this selection; they are not a guarantee that every possible secret can be detected.

The historical interface gallery contains three screenshots from the earlier scoring-oriented application with real G1 camera frames, robot-state playback and installed stage-model results. A separately labelled screenshot illustrates the synthetic demo. Only these selected still images are included; the underlying MCAP recordings, features, review database and checkpoints are excluded. The current MiniMax workflow does not use those historical scores for acceptance. The default startup has an empty library until the operator imports recordings.

Run `tests/check_demo_ui.py` with Firefox and geckodriver for the portable browser workflow. It uses a generated MCAP and isolated workspace, saves a review, and checks an actual training-bundle export. For example:

```bash
PYTHONPATH=. .venv/bin/python tests/check_demo_ui.py --geckodriver /path/to/geckodriver
```

The supplied GitHub Actions workflow runs source tests on push and pull requests; see [Actions](https://github.com/Lee-hz/RoboCurate/actions) for actual results. Local Python/JavaScript and browser results are recorded separately; absent private recordings and optional downloaded upstream artifacts produce explicit skips. Public training-helper tests run without those inputs.

The [release status](../RELEASE_STATUS.json) records download availability separately from the unresolved base-viewer license review. The builder preserves these license-status fields; it performs no upload and does not apply a license to unresolved files. Its historical filename is retained for compatibility.

Workflow setup follows the official [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python) and [setup-node](https://github.com/actions/setup-node) usage. It uses GitHub-hosted runners and read-only repository permissions.

The model ZIP is built separately by `scripts/build_model_bundle.py`; it contains only the registered heads, pinned backbone files, provenance and the DINOv2 license. `models/release.json` pins its exact SHA-256. The source ZIP and Code → Download ZIP contain `scripts/install_models.py` to fetch and install it.
