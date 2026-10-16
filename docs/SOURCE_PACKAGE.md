# Source packaging

```bash
python3 scripts/build_source_candidate.py --label robocurate-source
```

Outputs under `dist/`:

- Source directory and ZIP archive.
- SHA-256 checksum and verification report.
- `SOURCE_MANIFEST.json` with each source file's path, size and hash.

The builder uses an explicit file allowlist and verifies archive CRCs and file hashes. Existing outputs are preserved. Credentials, recordings, workspace data and model weights are excluded.

Extract the ZIP and follow the [startup instructions](../README.md#run).
