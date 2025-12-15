# Migration Notes for Python Audio Converter

This document outlines changes between versions of the Python Audio Converter (PAC), including breaking changes, deprecated features, and step-by-step migration instructions. PAC follows semantic versioning (SemVer): MAJOR.MINOR.PATCH.

## Current Version: 1.0.0

This is the initial stable release of PAC. It introduces a modular architecture with CLI and GUI interfaces, FFmpeg-based conversion, metadata handling, and library scanning capabilities.

### Key Changes from Pre-1.0 Development

Prior to v1.0.0, the project was in early development with experimental features documented in the `docs/deprecated/` directory (e.g., initial SRS, Design.md, Tasks.md). These have been refactored or removed:

- **Deprecated Files**: Contents from `docs/deprecated/Code_Analysis_Report.md`, `docs/deprecated/Design.md`, `docs/deprecated/SRS.md`, and `docs/deprecated/Tasks.md` are now integrated into the main codebase and updated documentation. These files are preserved for historical reference but should not be used for current development.
- **Removed Experimental Features**:
  - Early logging system in `first_run.log` has been replaced with structured logging in `src/pac/library_runner.py`.
  - Initial task-based workflow in `Tasks.md` is now handled by `src/pac/scheduler.py` and `src/pac/planner.py`.
- **Breaking Changes**:
  - Command-line interface has changed from ad-hoc scripts to a unified `main.py` entrypoint. Old scripts (if any) must be updated to use `uv run python main.py`.
  - Configuration moved from inline hardcoded values to `src/pac/config.py`. Review and update any custom configs.
  - Database schema in `src/pac/db.py` is now versioned; v1.0.0 uses SQLite with a simple conversions table. If using pre-1.0 DB files, recreate them.

### Migration Steps for Pre-1.0 Users

1. **Backup Your Data**:
   - Copy your existing project directory and any output/conversion logs.
   - If using a custom database, export data: `uv run python -c "from src.pac.db import export_db; export_db('backup.json')"` (implement export if not present).

2. **Update Dependencies**:
   - Remove old virtual environments: `rm -rf .venv`
   - Sync with new `pyproject.toml`: `uv sync`
   - If using pip previously, migrate to uv: `uv add` for any custom packages.

3. **Refactor Code/Custom Scripts**:
   - Replace direct imports of old modules (e.g., from deprecated designs) with current ones:
     - Scanner/Planner: Use `src/pac/scanner.py` and `src/pac/planner.py`.
     - Conversion: Use `src/pac/encoder.py` and `src/pac/convert_dir.py`.
   - Update CLI calls: Old `python script.py` → `uv run python main.py --input ...`
   - GUI Launch: Now `uv run python -m app.gui` instead of direct `app/gui/main.py`.

4. **Test Migration**:
   - Run a dry-run conversion: `uv run python main.py --input-dir test_dir --dry-run`
   - Verify metadata: Convert a sample file and check tags with `ffprobe output.flac`.
   - If issues arise, consult the [Troubleshooting Guide](troubleshooting.md).

5. **Clean Up**:
   - Optionally remove `docs/deprecated/` after confirming migration: `rm -rf docs/deprecated/`
   - Update any IDE configurations to point to the new `.venv`.

## Upgrading from v1.0.0 to Future Versions

### v1.1.0 (Planned)

- **New Features**: Enhanced GUI themes, cloud storage integration (optional).
- **Breaking Changes**: None anticipated, but config.py may add new optional keys.
- **Migration Steps**:
  1. `git pull` or download new release.
  2. `uv sync` to update dependencies (e.g., newer mutagen for better metadata support).
  3. Review changelog in GitHub releases.
  4. Test with existing libraries.

### General Upgrade Process

1. **Check Release Notes**: Always read the GitHub release or changelog for version-specific instructions.
2. **Dependency Update**: `uv sync` handles most updates automatically via `uv.lock`. If locked versions cause issues, `uv lock --upgrade`.
3. **Database Migration**: Future versions may include schema updates in `src/pac/db.py`. Run any provided migration script: `uv run python src/pac/db.py --migrate`.
4. **Configuration Review**: Compare `src/pac/config.py` with the new version. Merge custom changes manually.
5. **Test Thoroughly**: Use the test suite: `uv run pytest tests/`
6. **FFmpeg Compatibility**: Ensure FFmpeg is updated (`ffmpeg -version` should be 4.0+). PAC may require specific codecs in future releases.

## Deprecated Features

- **uv Replacement for pip**: All installation now uses uv exclusively. Pip commands are unsupported and will fail.
- **Old Module Paths**: Direct access to internal modules (e.g., `from pac.flac_tools import ...`) is deprecated in favor of the main entrypoint. Use imports via `main.py` or GUI.
- **Legacy Logging**: Console-only output is being phased out; future versions will require structured logs (JSON/CSV) for batch jobs.

## Known Issues and Workarounds

- If migrating from Windows to Linux/macOS, path separators in configs may need adjustment (use `src/pac/paths.py` utilities).
- Custom FFmpeg builds: Set `FFMPEG_PATH` in config.py if not in PATH.
- For large libraries (>10k files), increase `THREADS` in config.py gradually to avoid system overload.

## Contributing to Migration Docs

If you encounter migration issues, please open a GitHub issue with:
- Your old/new versions.
- Steps to reproduce.
- Environment details (OS, Python/FFmpeg versions).

For developers, update this file during releases by documenting changes in `docs/plan.md` first.

See the [User Guide](user_guide.md) for current usage and [Troubleshooting](troubleshooting.md) for runtime issues.