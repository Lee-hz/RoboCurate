# RoboCurate

A local VLM review workbench for robot teleoperation recordings. Define task stages and completion criteria from a reference demonstration, review individual attempts, and inspect synchronized video, 3D poses, joint feedback and human corrections.

[Download source](https://github.com/Lee-hz/RoboCurate/archive/refs/heads/main.zip) · [中文说明](README.zh-CN.md)

## Run

Requires Python 3.10+, FFmpeg and a browser. Tested on Linux; ROS is not required.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg
./start.sh
```

Open http://127.0.0.1:8421/. The launcher creates a Python environment and installs dependencies on first use. To select a recording directory at startup, run `./start.sh /path/to/recordings`.

## Workflow

1. Open **MiniMax 接入** and save your endpoint and API key.
2. Open **任务范本**. In **导入数据**, select a recording and click **加入审核数据** (or upload a video). Then select it under **范本录像**, parse its stages and completion criteria, and inspect the proposed definitions.
3. Open another recording, choose the template and review range, and start analysis.
4. Inspect each attempt with timestamped evidence, actual model inputs, video, 3D playback and joint feedback.
5. Save human corrections and export review JSON as needed.

The supported gateway model is **HORIZON-MiniMax**, with multi-image Chat Completions support. Connect to the company network or VPN before accessing an internal gateway. Configuration alone does not call the model. Analysis uses the operator's own API quota.

Each operator runs their own local instance. Keys are stored in `workspace/taskflow/minimax-local.json` with owner-only permissions and are never returned to the browser. Recordings remain read-only. Reviews, caches and exports are stored in `workspace/`; credentials, recordings and model weights are excluded from the source repository.

## Scope

G1 MCAP can provide camera and robot-state evidence; ordinary video provides visual evidence only. Stages may repeat or move backwards. Outcomes are completed, not completed or uncertain. Model output requires evidence review; joint motion alone cannot establish object grasp or placement. Precise spatial measurements and independently validated task accuracy are not provided. Templates are editable proposals without a separate approval state.

## Development and licensing

[Workflow details](docs/TASKFLOW.md) · [Development](CONTRIBUTING.md) · [Packaging](docs/SOURCE_PACKAGE.md) · [Security](SECURITY.md) · [Contributors](CONTRIBUTORS.md)

Redistribution permission for the supplied base viewer remains unverified. No repository-wide open-source license has been applied. See [license status](LICENSE_STATUS.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
