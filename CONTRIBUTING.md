# Development

Use Python 3.10+, FFmpeg and Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests -q
node --test tests/*.test.mjs
```

Optional model-runtime tests require PyTorch. Tests that depend on unavailable recordings or optional dependencies are explicitly skipped. Synthetic fixtures must remain clearly labelled and must not be saved as production review results.

Use `scripts/create_demo.py` to generate a synthetic MCAP for playback checks. API tests use temporary workspaces and fake credentials; they do not call a paid model service.

Keep recordings read-only and human review saves explicit. Preserve time precision, source provenance and missing-data masks. Test credential redaction, interrupted jobs and cache invalidation when changing the review pipeline. Describe behavior and verification in pull requests.

The UI uses one font family throughout. Page titles are 24 px, dialog and stage titles 18 px, body and section text 14 px, controls 13 px and annotations 12 px. Use tabular digits for times; reserve monospace for raw structured data. Playback and review panels share a timeline.

Do not commit credentials, recordings, private screenshots, databases, generated caches or experiment outputs. See [license status](LICENSE_STATUS.md) and [source packaging](docs/SOURCE_PACKAGE.md).
