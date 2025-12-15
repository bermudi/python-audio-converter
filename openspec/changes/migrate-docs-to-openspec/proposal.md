# Change: Migrate Documentation to OpenSpec

## Why
The project has accumulated documentation in `docs/` that is outdated, duplicated, or inconsistent. OpenSpec provides a structured, spec-driven approach that keeps requirements, design decisions, and implementation in sync. Making OpenSpec the single source of truth will improve maintainability and enable AI-assisted development workflows.

## What Changes
- **BREAKING**: Delete entire `docs/` directory (including `docs/deprecated/`)
- Migrate core requirements from `docs/deprecated/SRS.md` to `openspec/specs/audio-conversion/spec.md`
- Migrate architecture from `docs/deprecated/Design.md` to `openspec/specs/audio-conversion/design.md`
- Create new `openspec/specs/library-management/` capability from `docs/plan.md`
- Update `openspec/project.md` with project conventions
- Consolidate user-facing docs (user_guide, troubleshooting, migration_notes) into README.md

## Impact
- Affected specs: `audio-conversion` (new), `library-management` (new)
- Affected code: None (documentation-only change)
- Affected files:
  - `docs/` (deleted)
  - `openspec/project.md` (updated)
  - `openspec/specs/audio-conversion/` (new)
  - `openspec/specs/library-management/` (new)
  - `README.md` (updated with consolidated user docs)
