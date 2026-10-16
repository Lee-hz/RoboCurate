# Local deployment

Run one local instance per operator. RoboCurate listens on `127.0.0.1` and uses local filesystem access; it has no multi-user authentication.

## Credentials

API keys are saved in `workspace/taskflow/minimax-local.json` with owner-only permissions (`0600`). The browser neither stores nor receives saved keys. Protect workspace backups and keep credentials out of shared logs and source packages.

Disconnecting disables submissions. Running tasks must finish before connection settings can change.

## Data

Analysis sends sampled images and selected feedback summaries to the configured gateway. Use an endpoint approved for the recordings.

Load model checkpoints from trusted sources. Validate imported media, model responses and template text before use.
