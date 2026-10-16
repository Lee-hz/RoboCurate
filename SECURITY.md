# Local deployment

RoboCurate listens on `127.0.0.1` and reads paths selected by the local operator. It does not provide multi-user authentication or authorization. Run a separate local instance for each operator.

MiniMax credentials are stored in an owner-only file under `workspace/taskflow/`. The settings API does not return keys, and the browser does not persist them. Protect workstation access and workspace backups. Disconnecting disables further submissions; an in-flight request must finish before credentials can be changed.

Model requests send sampled images and selected feedback to the configured gateway. Use an endpoint authorized for the recording data. Never include credentials or private recordings in issues, logs shared externally, or source packages.

Only load trusted model checkpoints. Treat imported video, model responses and template text as untrusted data.
