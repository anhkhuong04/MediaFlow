# MediaFlow

Windows desktop media download manager using Python, PySide6, yt-dlp and FFmpeg.
Currently at engineering baseline: no GUI or download functionality yet.
See [task.md](task.md) for progress and [overview](docs/overview.md) for product scope.

## Development (PowerShell, Windows x64)

Use CPython **3.13.x** (locally verified on 3.13.2). The project deliberately supports
one minor version. PySide6 6.11.2 requires Python >=3.10,<3.15; yt-dlp 2026.8.19
requires >=3.10. Sources: [PySide6 metadata](https://pypi.org/project/PySide6/6.11.2/)
and [yt-dlp metadata](https://pypi.org/project/yt-dlp/2026.8.19/).

```powershell
py -3.13 -m pip install uv==0.12.10
uv sync --locked --extra dev --python 3.13
.\.venv\Scripts\python -c "import mediaflow"
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy
.\.venv\Scripts\python -m pytest
uv pip check
```

Package metadata, exact direct dependencies and tool configuration live in
`pyproject.toml`. The generated `uv.lock` pins transitive dependencies and hashes;
commit it alongside dependency changes. Run `uv lock` after deliberately changing
dependencies; normal setup and CI use `--locked` to reject a stale lockfile.
Ruff handles formatting/lint; mypy runs in strict mode.
Use `python -m ruff format .` to format edits. SQLite uses the standard library.
FFmpeg/FFprobe installation and process integration are deferred to C6.

## Tests and CI

The default suite runs unit and local integration tests with sockets disabled by
pytest-socket. Use temporary directories and fake external tools; do not access
browser profiles or real user downloads. Subprocesses must also remain offline;
pytest-socket only intercepts sockets in the pytest process.

Future live checks must use `@pytest.mark.smoke`. Run them explicitly with
`python -m pytest -o addopts='' -m smoke` only with authorized media and known
external executables. They are excluded from the Windows CI quality gate.

## Logging

Call `configure_logging(Path(...))` from `mediaflow.logging_setup` at startup,
before launching workers; call `shutdown_logging()` after stopping workers.
The caller selects a writable application-data directory, never the source tree.
Default rotation: 2 MiB per file, 3 backups, UTF-8 JSON lines, UTC timestamps.

Use reviewed event codes (`application.started`, `application.stopped`,
`application.failed`) and a UUID `task_id` as structured context. Unknown messages
are suppressed. Arguments, arbitrary extras, exception messages and stack traces
are omitted. Extend the event schema with tests when new diagnostics are needed;
do not attach raw engine logs or add arbitrary text fields. Root logging is untouched.

## Repository hygiene

Agent instructions/skills, environments, logs, databases and secrets stay local.
Review `git diff --cached` before committing; ignore patterns cannot detect secrets
embedded in source files. Only sanitized fixtures belong in tests.
