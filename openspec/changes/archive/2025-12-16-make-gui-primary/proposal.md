# Change: Make GUI the Primary Interface

## Why
PAC already ships a rich PySide6 GUI and a packaged GUI entrypoint (`pac-gui`), but the project framing and documentation still present the CLI as the primary user-facing interface. This change aligns specs and docs with the product direction: GUI-first for desktop users managing libraries, with a CLI that remains available but is not highlighted.

## What Changes
- Update OpenSpec requirements to treat the GUI as the primary interface.
- Re-scope CLI commands as a supported interface intended for debug/testing and advanced usage, but not the default user path.
- Ship a separate CLI entrypoint (`pac-cli`) while keeping `pac-gui` as the primary entrypoint.
- Update project docs (`README.md`, `openspec/project.md`) and packaging guidance to lead with `pac-gui`.

## Impact
- Affected specs:
  - `audio-conversion`
  - `library-management`
- Affected code/docs (implementation phase):
  - `README.md`
  - `openspec/project.md`
  - `pyproject.toml` (scripts/entrypoints)
  - `main.py` (CLI) and `app/gui/main.py` (GUI)
