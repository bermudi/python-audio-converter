# Troubleshooting Guide for Python Audio Converter

This guide addresses common issues encountered when installing, running, or using the Python Audio Converter (PAC). Issues are categorized by area (installation, CLI, GUI, conversion). If a solution doesn't resolve your problem, check the [User Guide](user_guide.md), [Migration Notes](migration_notes.md), or open a GitHub issue with logs.

## Installation Issues

### FFmpeg Not Found or Command Fails

**Symptoms**: Error like "ffmpeg: command not found" or "FFmpeg not installed" during conversion. Script exits with non-zero code.

**Causes**: FFmpeg is missing, not in PATH, or version too old (<4.0).

**Solutions**:
1. Verify installation: `ffmpeg -version`. Should show version 4.0+.
2. Install/update FFmpeg:
   - Linux (Ubuntu/Debian): `sudo apt update && sudo apt install ffmpeg`
   - macOS (Homebrew): `brew install ffmpeg`
   - Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html), extract, add `bin/` to PATH (e.g., `C:\ffmpeg\bin`).
3. Custom path: Edit `src/pac/config.py` and set `FFMPEG_PATH = "/path/to/ffmpeg"`. Restart the app.
4. Test: Run `uv run python -c "from src.pac.ffmpeg_check import check_ffmpeg; check_ffmpeg()"`.

### uv Sync Fails or Dependencies Not Installed

**Symptoms**: "No such file or directory: '.venv'" or import errors like "ModuleNotFoundError: No module named 'mutagen'".

**Causes**: uv not installed, pyproject.toml issues, or network/proxy problems.

**Solutions**:
1. Install uv: Follow [astral.sh/uv](https://astral.sh/uv) instructions (e.g., `curl -LsSf https://astral.sh/uv/install.sh | sh`).
2. Verify: `uv --version`.
3. Clean and resync: `rm -rf .venv uv.lock && uv sync`.
4. If behind proxy: Set `HTTP_PROXY` env var or use `uv sync --no-cache`.
5. Manual add: `uv add mutagen` (for metadata) or other missing deps from pyproject.toml.
6. Avoid pip: Do not use `pip install`; always use uv to prevent conflicts.

### Python Version Mismatch

**Symptoms**: "Python 3.8+ required" or syntax errors on run.

**Causes**: System Python too old; uv using wrong interpreter.

**Solutions**:
1. Check: `python --version` (should be 3.8+).
2. Set version: Create `.python-version` file with "3.11" (or desired), then `uv sync`.
3. Use pyenv (optional): Install pyenv, set global/local version, then uv sync.

## CLI Usage Issues

### No Files Found During Scan

**Symptoms**: "No audio files detected" or empty output directory.

**Causes**: Wrong path, unsupported extensions, or non-recursive scan.

**Solutions**:
1. Verify path: Use absolute paths, e.g., `uv run python main.py --input-dir /full/path/to/music`.
2. Check extensions: PAC scans .mp3, .flac, .wav, .ogg, .aac, .m4a, .opus by default. Edit `src/pac/scanner.py` for customs.
3. Enable recursive: Add `--recursive` flag for subdirs.
4. Test scan: `uv run python -m src.pac.scanner --path /test/dir --dry-run` to list detected files.

### Permission Denied on Input/Output Files

**Symptoms**: "PermissionError: [Errno 13]" or "Access denied".

**Causes**: Read-only files, insufficient user permissions, or output dir not writable.

**Solutions**:
1. Check permissions: `ls -la /path/to/files`. Ensure user owns files.
2. Fix ownership: `sudo chown -R $USER:$USER /path/to/music` (Linux/macOS).
3. Create output dir: `mkdir -p /path/to/output && chmod 755 /path/to/output`.
4. Run as non-root: Avoid `sudo` for PAC; use your user account.
5. Windows: Run VSCode/terminal as admin if needed, but prefer user perms.

### Conversion Hangs or Slow Performance

**Symptoms**: Process stuck at 0%, high CPU/memory, or timeouts on large files.

**Causes**: Large files, too many threads, or FFmpeg codec issues.

**Solutions**:
1. Reduce threads: Edit `src/pac/config.py` `THREADS = 2` (start low, increase gradually).
2. Monitor: Use `--verbose` flag for progress logs.
3. Split batches: Convert subdirs separately for libraries >1000 files.
4. FFmpeg flags: Add custom via config.py, e.g., `-threads 1` for single-threaded encodes.
5. System resources: Close other apps; ensure >4GB RAM free for batches.

## GUI Issues

### GUI Fails to Launch

**Symptoms**: "No module named 'tkinter'" or window doesn't open.

**Causes**: Tkinter missing (Linux), display issues (headless), or import errors.

**Solutions**:
1. Install Tkinter:
   - Linux: `sudo apt install python3-tk`
   - macOS: Usually bundled; reinstall Python if missing.
   - Windows: Included in standard Python.
2. Launch command: `uv run python -m app.gui.main`.
3. Headless test: If on server, use `xvfb-run uv run python -m app.gui` (install xvfb).
4. Logs: Check terminal output; add `print("GUI starting")` in app/gui/main.py for debug.

### GUI Freezes During Conversion

**Symptoms**: Interface unresponsive after "Start", no progress update.

**Causes**: Blocking operations in threads, or Tkinter event loop issues.

**Solutions**:
1. Update to latest: Ensure uv sync for bug fixes.
2. Reduce load: Limit file count (<100 initially); increase `THREADS` carefully.
3. Debug: Run CLI version first to isolate GUI issue.
4. Restart: Close/reopen GUI; clear temp files in output_dir/.

## Conversion-Specific Issues

### Output Files Have No Audio or Corrupted

**Symptoms**: File plays but silent, wrong duration, or "Invalid data found".

**Causes**: Incompatible formats, missing codecs, or bitrate too high/low.

**Solutions**:
1. Check FFmpeg logs: Run with `--verbose` and review errors (e.g., "Codec not supported").
2. Supported formats: Stick to MP3, FLAC, AAC, Opus, WAV. Avoid exotic ones.
3. Bitrate adjust: Use standard like `--bitrate 192k`; test with `ffprobe output.flac`.
4. Re-encode: Delete output, retry single file: `uv run python main.py input.mp3 test.flac`.
5. Update FFmpeg: Reinstall for latest codecs.

### Metadata Not Preserved

**Symptoms**: Output lacks artist/title tags; `ffprobe -show_entries format_tags output.flac` shows empty.

**Causes**: Mutagen/FFmpeg incompatibility, or `--preserve-metadata` disabled.

**Solutions**:
1. Verify flag: Ensure `--preserve-metadata` (default on).
2. Check input: Use `ffprobe input.mp3 -show_entries format_tags` to confirm tags exist.
3. Library issue: `uv add mutagen --upgrade` then sync.
4. Manual fix: Post-conversion, use `ffmpeg -i input.mp3 -i output.flac -map 0 -map 1 -c copy -id3v2_version 3 fixed.flac`.
5. Config: Ensure `ENABLE_METADATA = True` in src/pac/config.py.

### Unsupported Format Error

**Symptoms**: "Format not supported" or "Unknown encoder".

**Causes**: Output format invalid or FFmpeg lacks codec.

**Solutions**:
1. List supported: `ffmpeg -formats | grep -E ' (D|E) '` for decoders/encoders.
2. Common fixes: For AAC, use .m4a extension; for Opus, ensure libopus in FFmpeg.
3. Fallback: Convert to WAV first, then to target.
4. Edit config: Add to SUPPORTED_FORMATS in src/pac/config.py.

### Database or Index Errors

**Symptoms**: "SQLite error" or "Index out of range" in library scanning.

**Causes**: Corrupt DB, version mismatch, or concurrent access.

**Solutions**:
1. Reset DB: Delete `pac.db` (if exists) in project root, restart.
2. Check schema: `uv run python -c "from src.pac.db import init_db; init_db()"`.
3. Single-thread: Set `THREADS = 1` for DB ops.
4. Backup: If custom DB, copy before reset.

## General Tips

- **Logs**: Always use `--verbose` or check `output_dir/pac-run-summary-*.json` for details.
- **Dry Run**: Test with `--dry-run` before real conversions.
- **Environment**: Ensure no conflicting Python installs; use `uv run` exclusively.
- **Updates**: `git pull && uv sync` for fixes.
- **Community**: Search GitHub issues or forums for similar errors.

If unresolved, provide: OS/Python/FFmpeg versions, exact command, full error log, and sample file (if privacy allows).