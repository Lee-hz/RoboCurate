# RoboCurate

A VLM workbench for robot teleoperation data. Build a task template from a reference recording, review other recordings against its stages and completion criteria, and inspect synchronized video, 3D poses and joint feedback.

[Download](https://github.com/Lee-hz/RoboCurate/releases/latest) · [中文说明](README.zh-CN.md)

## Run

Requires Python 3.10+, FFmpeg and a browser. On Ubuntu / Debian:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg
./start.sh
```

Open http://127.0.0.1:8421/. The first launch creates a Python environment and installs dependencies. Use `./start.sh /path/to/recordings` to select an MCAP directory.

## Workflow

1. **Connect MiniMax**: enter your gateway URL and API key in **MiniMax 接入**.
2. **Build a template**: open **任务范本**, add a recording under **导入数据**, then select it as **范本录像**. Parse and edit its stages and completion criteria.
3. **Review a recording**: open another recording, choose the template and review range, and start analysis.
4. **Inspect and save**: check evidence and model inputs alongside playback, save human corrections, and export review JSON.

Uses **HORIZON-MiniMax** through a multi-image Chat Completions gateway. Internal gateways require company network or VPN access. Each operator runs a local instance with their own API key.

Supports G1 MCAP and video files. MCAP supplies camera and robot feedback; video supplies images. Results and settings are saved in `workspace/`.

## Documentation

[Workflow](docs/TASKFLOW.md) · [Development](CONTRIBUTING.md) · [Packaging](docs/SOURCE_PACKAGE.md) · [Security](SECURITY.md) · [Contributors](CONTRIBUTORS.md) · [License status](LICENSE_STATUS.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)
