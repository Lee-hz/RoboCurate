# Development

## Tests

Requires Python 3.10+, FFmpeg and Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests -q
node --test tests/*.test.mjs
```

Optional model tests require PyTorch. Tests requiring unavailable recordings or dependencies are skipped. API tests use temporary workspaces and fake credentials.

`scripts/create_demo.py` generates a synthetic MCAP for playback checks.

## UI

Use one font family and a shared playback timeline.

| Text | Size |
| --- | --- |
| Page titles | 24 px |
| Dialog and stage titles | 18 px |
| Body and section text | 14 px |
| Controls | 13 px |
| Annotations | 12 px |

Use tabular digits for time and monospace for structured data.

## File-based gateway configuration

Without a personal connection file, the service reads `ROBOCURATE_VLM_CONFIG` or `workspace/taskflow/company-vlm.json`. Use model `HORIZON-MiniMax` and provide credentials through `api_key_file` or `api_key_env`.

Personal settings take precedence. Disconnecting retains a disabled marker that prevents fallback to the file-based configuration.

## Data handling

Keep recordings read-only, human corrections separate from model output, and source timestamps and missing-data masks intact. Pipeline changes should cover credential redaction, interrupted jobs and cache invalidation.

Keep credentials, recordings and generated workspace files outside version control. See [security](SECURITY.md), [source packaging](docs/SOURCE_PACKAGE.md) and [license status](LICENSE_STATUS.md).
