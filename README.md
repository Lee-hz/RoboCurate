# RoboCurate

**Reference-driven review:** connect a company vision-language service to infer task stages and observable goals from a reference demo, then review each attempt with timestamped evidence and separate human corrections. See [workflow setup and limits](docs/TASKFLOW.md).

A local workbench for robot demonstrations: synchronized cameras and motion, VLM stage and goal evidence, and traceable human decisions.

[中文说明](README.zh-CN.md) · [Models](docs/MODELS.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

**Source preview.** This repository provides source code and a synthetic demo. The supplied base-viewer's license is still under review; no repository-wide open-source license has been applied. See [license status and the exact file list](LICENSE_STATUS.md).

## Download

- Historical release (before this VLM update): [Download the v0.1.0-preview.3 source package](https://github.com/Lee-hz/RoboCurate/releases/download/v0.1.0-preview.3/RoboCurate-v0.1.0-preview.3-source.zip), or open [Releases](https://github.com/Lee-hz/RoboCurate/releases) and select the ZIP under **Assets**.
- For the latest source, choose **Code → Download ZIP** on the repository page, or [download main](https://github.com/Lee-hz/RoboCurate/archive/refs/heads/main.zip).

Extract the ZIP and follow the instructions below. This is a source distribution for local setup, not a standalone installer. Recordings are excluded. Trained weights are available in a separate [model pack](https://github.com/Lee-hz/RoboCurate/releases/download/v0.1.0-preview.3/RoboCurate-v0.1.0-preview.3-models.zip); the installer below works with **Code → Download ZIP** too.

## Current workflow

1. Open **MiniMax 接入** in the top bar. Enter your own image-capable company gateway endpoint and API key, then save.
2. Add local MCAP recordings or upload a reference video.
3. Parse the reference into stage definitions and observable completion criteria; inspect and edit the proposal.
4. Open another recording, select the template, and start MiniMax review.
5. Review individual attempts with synchronized video, 3D motion, joint feedback, model-input evidence and human corrections.

The current product focuses on VLM task review. Historical technical scores are not acceptance criteria. Generated templates are editable proposals; a separate approval/activation state is not yet implemented.

Each person runs a local instance and uses their own API quota. The connection form uses **HORIZON-MiniMax**, an image-capable company Chat Completions model, with no OG fallback. This is not a universal alias for arbitrary MiniMax public API models. Save does not call the model; connection success is reported after a successful task request.

Credentials are stored only in `workspace/taskflow/minimax-local.json`, with owner-only file permissions. They are never returned by the settings API or stored in browser storage, and are excluded from source packages. This is a local API connection, not a website account or multi-user login system. See [setup and limits](docs/TASKFLOW.md).

## Run locally

Requirements: Python 3.10+, a browser, and Python virtual-environment support. Linux is the platform tested in development. ROS itself is not required.

From the extracted source directory:

```bash
./start.sh
```

The script creates `.venv` and installs application dependencies on first run. Open **http://127.0.0.1:8421/** and add a recording directory. Alternatively:

```bash
./start.sh /path/to/recordings
```

The server binds to loopback. It is intended for a local operator, not a public multi-user service. Recordings are read-only; caches, reviews and exports are stored in `workspace/`.

## Historical stage models (optional; not needed for MiniMax review)

Run from the extracted source directory (about 94 MB of model assets; no account required):

```bash
python3 -m venv workspace/warp-env
workspace/warp-env/bin/python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
workspace/warp-env/bin/python -m pip install -r requirements-warp.txt
python3 scripts/install_models.py
workspace/warp-env/bin/python scripts/verify_models.py
```

The pack contains the pinned DINOv2-S/14 backbone, G1 stage v1/v2/v3 and the public-video WARP temporal head. Select **g1-stage-v3** for the banana-transfer task. [Offline installation](docs/MODELS.md) and [all training/research code](docs/TRAINING.md) are documented. Raw training videos and annotations are not distributed.

## Synthetic demo

No laboratory recording or model download is required:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/create_demo.py
./start.sh workspace/demo --workspace workspace/demo-session --analyze
```

The six-second MCAP contains generated camera diagrams, 41-dimensional state/action data, a controlled arm offset and a deliberate head-camera gap. Every image is labelled **SYNTHETIC DEMO**. It exercises playback, technical checks, review and export; it is not a visual-model benchmark and has no success label.

<details>
<summary>View the synthetic sample used for trying the interface without recordings</summary>

![Synthetic MCAP sample with generated diagrams](docs/images/synthetic-demo.png)

</details>

Task-stage and WARP inference require appropriate checkpoints in a separate model environment. The source includes model and training implementations; the Release model pack supplies the matching pretrained encoder and trained heads. Private recordings are excluded. See [model setup](docs/MODELS.md).

## Scores and exports

`quality.rating.max_score` is `10`, and rating schema version is `3`. The previous 100-point score is divided by ten: `92.3 → 9.23`. Dimensions, weighted contributions, the catalog and new exports use the same scale. Coverage and model probabilities remain percentages; WARP retains its relative-speed unit.

Exports retain `robot-data-studio.v1` for reader compatibility. Training bundles contain 41-dimensional state/action arrays, JPEG images, timestamps and validity masks. This is a generic format, not native LeRobot/RLDS or an RGB-D conversion. `dataset_reader.py` provides a reader.

## Development

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONPATH=. .venv/bin/python -m pytest tests/test_demo.py tests/test_scoring.py tests/test_grading.py -q
node --test tests/*.test.mjs
```

Synthetic end-to-end tests generate MCAP, inspect known faults and export a reviewed clip. Full model tests require model dependencies. Historical integration tests are explicitly skipped when the private development recordings are absent; skips are not evidence of real-data evaluation.

See [contributing](CONTRIBUTING.md), [changes](CHANGELOG.md), [validation scope](docs/VALIDATION.md), [source packaging](docs/SOURCE_PACKAGE.md), [publication status](RELEASE_STATUS.json), and [security scope](SECURITY.md). Raw recordings, review databases, browser profiles, login caches and model weights do not belong in the source repository.

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).
