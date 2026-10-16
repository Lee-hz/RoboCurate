# Source packaging

```bash
python3 scripts/build_source_candidate.py --label robocurate-source
```

The output is a source directory, ZIP, SHA-256 checksum and verification report under `dist/`. Existing outputs are not overwritten. `SOURCE_MANIFEST.json` records each file's path, size and hash; ZIP CRC and file hashes are checked after packaging.

An explicit allowlist includes application code, frontend and robot assets, tests, current documentation and third-party notices. It excludes credentials, workspace databases, recordings, model weights, research reports, development captures and local handoff material. Credential-pattern checks supplement the allowlist.

For an independent startup check, extract the ZIP into a new directory, install Python dependencies and FFmpeg, and run `./start.sh`. The library should be empty and MiniMax should be unconfigured.
