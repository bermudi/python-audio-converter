# Python Audio Converter (PAC)

Mirror a FLAC library to an AAC (M4A) or Opus library with 1:1 directory structure and metadata parity. Optimized for Linux power users. Prefers FFmpeg with libfdk_aac; falls back to qaac or fdkaac.

This tool is **stateless**. It does not use a database. Instead, it embeds `PAC_*` tags into the output files to track their relationship to the source files. This allows for resumable and incremental runs without a persistent local database.

- Specs: see [openspec/specs/](openspec/specs/) for requirements and design
- Package: `src/pac/`
- GUI entry point: `pac-gui` ([app/gui/main.py](app/gui/main.py))
- Debug/testing CLI entry point: `pac-cli` ([src/pac/cli.py](src/pac/cli.py))

## Features

- Mirror FLAC → AAC (M4A) or Opus, preserving directories and filenames
- Stateless operation: derives state from embedded tags in output files
- Encoder selection: ffmpeg+libfdk_aac > qaac(pipe) > fdkaac(pipe)
- Quality targets around ~256 kbps VBR for AAC (configurable)
- Tag and cover art copy (FLAC → MP4/Opus)
- Parallel workers; atomic writes; resumable runs
- Adopts existing untagged files by default
- Can prune orphaned files from the destination
- Can rename destination files when source files are moved
- Dry-run planning and clear summaries
- Exit codes for automation
- GUI for interactive use

## Requirements

- Python: 3.12+
- Linux
- System tools:
  - Required: FFmpeg
  - Preferred: FFmpeg with libfdk_aac enabled
  - Optional fallbacks: `qaac` CLI, `fdkaac` CLI
- Python deps are declared in [pyproject.toml](pyproject.toml) (managed with uv)

Notes:
- libfdk_aac availability varies by distro. If missing, PAC will try `qaac` (true VBR) then `fdkaac`.
- `qaac` on Linux requires user-provided Apple CoreAudio components (non-trivial). If unavailable, `fdkaac` is a simpler fallback.

## Install (with uv)

Use uv for environments and dependencies (no raw pip).

- Bootstrap venv and install deps:
  - `uv sync`
- Verify the interpreter is from the uv venv:
  - `uv run which python`
- Run commands via uv:
  - `uv run pac-cli preflight`

## GUI Quick Start (Primary Experience)

1. Install dependencies with uv:
   ```
   uv sync
   ```
2. Launch the GUI (starts encoder preflight automatically):
   ```
   uv run pac-gui
   ```
3. (Optional) Pre-populate paths when launching:
   ```
   uv run pac-gui --flac-library "/music/FLAC" --mirror-library "/music/AAC"
   ```
4. Configure operations in the GUI (Library tab or Convert tab), dry-run if desired, then run.

## Debug / Testing CLI Quick Start

The CLI is available for automation, testing, and advanced troubleshooting. It is not the primary user workflow, but remains fully supported.

1. Preflight encoders:
   ```
   uv run pac-cli preflight
   ```
2. Batch convert a directory (dry-run first to see the plan):
   ```
   uv run pac-cli convert-dir --in "/music/FLAC" --out "/music/AAC" --dry-run
   ```
3. Run for real with parallel workers:
   ```
   uv run pac-cli convert-dir \
     --in "/music/FLAC" \
     --out "/music/AAC" \
     --workers 8 \
     --vbr 5 \
     --tvbr 96 \
     --pcm-codec pcm_s24le \
     --hash \
     -v
   ```
4. Prune orphaned files from the destination (use with care):
   ```
   uv run pac-cli convert-dir --in "/music/FLAC" --out "/music/AAC" --prune
   ```

## GUI

An interactive GUI is also available.

### Launch

```bash
uv run pac-gui
```

Optional startup arguments (pre-populate fields):

```bash
uv run pac-gui \
  --flac-library "/music/FLAC" \
  --mirror-library "/music/AAC"
```

### Library GUI (Library tab)

The **Library** tab is for maintaining a FLAC library and (optionally) keeping a lossy mirror in sync. It has three main areas:

- **Top bar**
  - **Library:** FLAC library root (drag-and-drop a folder or browse).
  - **Mirror:** Optional output directory used for mirror-related features.
  - **Settings…** Library-specific settings (resample behavior, target compression, artwork extraction settings, worker counts).
- **Operations panel (left)**
  - Checkboxes for which operations to run.
  - **Scope** (Entire Library vs Selection Only).
  - **Dry Run** toggle.
  - **Run** button (and **Pause/Cancel** during an active run).
- **Browser panel (right)**
  - A table view of files plus status columns.
  - View mode and filter controls to focus on the files you care about.

#### 1) Set paths (required)

1. Set **Library** to the root folder that contains your `.flac` library.
2. (Optional) Set **Mirror** to your destination library folder if you use:
    - `Adopt Legacy`
    - `Update Mirror`
    - Correlated/side-by-side/output-only browsing modes

Notes:

- The path fields accept folder drag-and-drop.
- Some features are disabled until a valid **Mirror** path is set.

#### 2) Browse and filter the library

The browser table shows one row per file and includes columns:

- **Path**
- **Status** (e.g. OK / Needs Action / Error)
- **Integrity** (e.g. Untested / OK / Failed)
- **Format** (bit-depth/sample-rate)
- **Compression** (FLAC compression tag status)
- **Art** (embedded/exported art status)
- **Size**

Use these controls above the table:

- **View**
  - **Source Only**: scan and show the FLAC library.
  - **With Outputs**: correlate source files with mirror outputs (requires **Mirror**).
  - **Side-by-Side**: two synchronized tables (source and mirror) to compare (requires **Mirror**).
  - **Outputs Only**: analyze the mirror/output directory.
- **Filter** (the list changes based on the selected view)
  - In **Source Only** view:
    - **All Files**
    - **Needs Action**
    - **Hi-Res Only**
    - **Integrity Unknown**
    - **Integrity Failed**
    - **Needs Recompress**
    - **Legacy (No PAC tags)**
  - In **With Outputs** / **Side-by-Side** view:
    - **All Files**
    - **Needs Conversion**
    - **Synced**
    - **Outdated**
    - **Missing**
    - **Orphaned Outputs**
  - In **Outputs Only** view:
    - **All Files**
    - **Legacy (No PAC tags)**
    - **Orphaned Outputs**
- **Clear** resets filtering.
- **Rescan** re-runs the analysis to refresh statuses.

 Notes:

 - Changing **Library** path triggers an automatic scan once the path is valid (the field gets a green border when valid).
 - **With Outputs**, **Side-by-Side**, and **Outputs Only** require a valid **Mirror** path and will show a warning if it’s missing.

Quick filters are also available via the clickable stats buttons:

- **Total**
- **Hi-Res**
- **Untested**
- **Failed**
- **Recompress**
- **Legacy**

#### 3) Choose scope (Entire Library vs Selection Only)

In the Operations panel:

- **Entire Library** runs the selected operations on everything under **Library**.
- **Selection Only** runs only on rows you select in the browser table.
  - Select multiple rows with Shift/Ctrl.
  - If you choose Selection Only but nothing is selected, the GUI will block the run.

#### 4) Run operations

Select the operations you want in the left panel:

- **Integrity Check**: tests FLAC files for corruption.
- **Resample to CD**: resamples hi-res sources to 16-bit / 44.1kHz (behavior controlled by Settings).
- **Recompress FLAC**: recompresses FLAC to the target compression level.
- **Extract Artwork**: extracts embedded artwork based on your library settings.
- **Adopt Legacy**: adds missing `PAC_*` tags to existing outputs (requires **Mirror**).
- **Update Mirror**: updates the lossy mirror outputs (requires **Mirror**).

Then:

1. (Recommended) enable **Dry Run** first to see what would happen.
2. Click **Run**.
3. While running:
   - **Pause** temporarily stops processing (click again to Resume).
   - **Cancel** requests a stop.

 Notes:

- If you select **Adopt Legacy** *only*, it runs via a dedicated “adopt” phase.
- If you select **Adopt Legacy** plus other operations, adoption is handled separately from the other phases.

#### 5) Watch progress, issues, and logs

- The app has a shared **log panel** at the bottom.
  - Use the **Log** toggle ("▶ Log" / "▼ Log") to collapse/expand it.
  - In the Library tab you can also expand **Details**:
    - Status counters (scanned, integrity OK/failed, resampled, recompressed, art exported, adopted, held)
    - A compact **Issues** list for notable problems

Tip:

- The browser panel also has selection actions (**Run Integrity** and **Adopt Selected**) that become enabled when you select one or more rows.

### Safety notes (read before running destructive actions)

- **Dry Run** is strongly recommended before running anything on a large library.
- **Adopt Legacy** and **Update Mirror** act on your mirror/output library; confirm the **Mirror** path is correct.
- This project also has a separate **Convert** tab for full directory mirroring and includes options like:
  - `Prune orphans (deletes files)`
  - `Force re-encode all`
  If you enable those, read the confirmation dialogs carefully.

## CLI Reference

Commands are implemented in [`src/pac/cli.py`](src/pac/cli.py).

- `preflight`
  - Checks for FFmpeg, libfdk_aac, and optional `qaac`/`fdkaac`
- `convert SRC DEST [--tvbr N]`
  - Converts a single file to `.m4a`
  - `--tvbr`: qaac true-VBR scale (default 96 ≈ ~256 kbps typical)
  - `--pcm-codec {pcm_s24le|pcm_f32le|pcm_s16le}`: PCM codec used for ffmpeg decode when piping to qaac/fdkaac (default: `pcm_s24le`)
- `convert-dir --in DIR --out DIR [options]`
  - Recursively scans `.flac` and mirrors to `.m4a` or `.opus`
  - Options:
    - `--workers INT` (default: CPU cores)
    - `--codec {aac|opus}` (default: aac)
    - `--tvbr INT` (qaac scale; default 96)
    - `--vbr INT` (libfdk_aac/fdkaac 1..5; default 5 ≈ ~256 kbps)
    - `--opus-vbr-kbps INT` (Opus VBR bitrate; default 160)
    - `--pcm-codec {pcm_s24le|pcm_f32le|pcm_s16le}` (default `pcm_s24le`)
    - `--hash` / `--no-hash` (default: hash)
    - `--verbose` or `-v` (per-phase timing, probe details)
    - `--dry-run` (plan only; prints actions and reasons)
    - `--force-reencode`: Force re-encode all sources regardless of existing outputs
    - `--rename` / `--no-rename`: Allow planner to rename existing outputs to new paths (default: on)
    - `--retag-existing` / `--no-retag-existing`: Retag existing outputs with missing/old PAC_* tags (default: on)
    - `--prune`: Delete destination files whose source no longer exists
    - `--no-adopt`: Do not adopt/retag outputs missing PAC_* tags even if content matches
    - `--sync-tags`: Sync tags for files that are otherwise up-to-date.
    - `--verify-tags` / `--verify-strict`: Check tags after conversion and fail on mismatch (with `--verify-strict`).
    - `--cover-art-resize` / `--no-cover-art-resize`: Control resizing of large cover art.
    - `--cover-art-max-size INT`: Set max dimension for cover art (default 1500).

Exit codes:
- 0: success
- 2: completed with file failures
- 3: preflight failed (no suitable AAC encoder)

## How It Works

- **Preflight**: [src/pac/ffmpeg_check.py](src/pac/ffmpeg_check.py) selects encoder once per run.
- **Scan**: [src/pac/scanner.py](src/pac/scanner.py) catalogs source `.flac` files (size, mtime, optional FLAC MD5).
- **Destination Index**: [src/pac/dest_index.py](src/pac/dest_index.py) scans the destination directory and reads `PAC_*` tags from existing files to build an in-memory index.
- **Plan**: [src/pac/planner.py](src/pac/planner.py) compares the source scan with the destination index to determine actions: `convert`, `skip`, `rename`, `retag`, or `prune`.
- **Encode**: [src/pac/encoder.py](src/pac/encoder.py) runs the chosen backend.
- **Tags**: [src/pac/metadata.py](src/pac/metadata.py) copies tags and cover art and embeds the `PAC_*` tags.
- **Parallelism**: [src/pac/scheduler.py](src/pac/scheduler.py) worker pool controls concurrency.

## Project Structure

- [`src/pac/cli.py`](src/pac/cli.py) — CLI entry point (exposed via `pac-cli`)
- `src/pac/`
  - [ffmpeg_check.py](src/pac/ffmpeg_check.py) — tool detection and versions
  - [scanner.py](src/pac/scanner.py) — source file discovery
  - [dest_index.py](src/pac/dest_index.py) — destination index creation
  - [planner.py](src/pac/planner.py) — change detection and planning
  - [encoder.py](src/pac/encoder.py) — command builders and pipelines
  - [metadata.py](src/pac/metadata.py) — tag/art copy helpers
  - [scheduler.py](src/pac/scheduler.py) — bounded worker pool
- `openspec/` — specifications and design docs
  - `specs/audio-conversion/` — core conversion requirements
  - `specs/library-management/` — FLAC library maintenance
- `app/` — GUI application (PySide6)
- `tests/` — unit/integration tests

## Troubleshooting

### FFmpeg Not Found
```bash
# Verify FFmpeg is installed
ffmpeg -version

# Install on Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg
```

### libfdk_aac Not Available
PAC will automatically fall back to qaac or fdkaac. To check available encoders:
```bash
uv run python main.py preflight
```

### uv Sync Fails
```bash
# Clean and resync
rm -rf .venv uv.lock && uv sync
```

### No Files Found During Scan
- Use absolute paths for `--in` and `--out`
- Ensure source directory contains `.flac` files
- Try `--dry-run` first to see what would be processed
