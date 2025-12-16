## 1. Specification and Documentation
- [x] 1.1 Update `openspec/project.md` to describe PAC as GUI-first and clarify CLI scope (debug/testing).
- [x] 1.2 Update `README.md` to lead with GUI install/launch, and move CLI usage into a Debug/Testing section.
- [x] 1.3 Add/adjust OpenSpec deltas under `openspec/changes/make-gui-primary/specs/` for `audio-conversion` and `library-management` to reflect GUI-first positioning.

## 2. Packaging / Entry Points
- [x] 2.1 Confirm `pyproject.toml` exposes the GUI entrypoint as the primary script (`pac-gui`).
- [x] 2.2 Decide whether to add a separate CLI script name (`pac-cli` or `pac-debug`) or keep CLI as `uv run python main.py ...` only.
- [x] 2.3 If a CLI script is added, ensure the help text and docs explicitly mark it as debug/testing.

## 3. Code Adjustments (if needed)
- [x] 3.1 Ensure GUI does not depend on importing the repo-root `main.py` in a way that makes packaging brittle (prefer importing conversion functionality from `src/pac/`).
- [x] 3.2 Ensure CLI commands remain functional for tests/debugging.

## 4. Validation
- [x] 4.1 Run `openspec validate make-gui-primary --strict`.
- [x] 4.2 Run `uv run python -m pytest` (optional smoke check) after implementation.
