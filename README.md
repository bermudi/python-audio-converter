# Python Audio Converter (PAC)

Mirror a FLAC library to an AAC (M4A) or Opus library with 1:1 directory structure and metadata parity. Optimized for Linux power users. Prefers FFmpeg with libfdk_aac; falls back to qaac or fdkaac.

This tool is **stateless**. It does not use a database. Instead, it embeds `PAC_*` tags into the output files to track their relationship to the source files. This allows for resumable and incremental runs without a persistent local database.

- Specs: see [openspec/specs/](openspec/specs/) for requirements and design
- Package: `src/pac/`
- Entry point: [main.py](main.py)

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
  - `uv run python main.py preflight`

## Quick Start

1) Preflight encoders:
```
uv run python main.py preflight
```
2) Batch convert a directory (dry-run first to see the plan):
```
uv run python main.py convert-dir --in "/music/FLAC" --out "/music/AAC" --dry-run
```
3) Run for real with parallel workers:
```
uv run python main.py convert-dir \
  --in "/music/FLAC" \
  --out "/music/AAC" \
  --workers 8 \
  --vbr 5 \
  --tvbr 96 \
  --pcm-codec pcm_s24le \
  --hash \
  -v
```
4) Prune orphaned files from the destination (use with care):
```
uv run python main.py convert-dir --in "/music/FLAC" --out "/music/AAC" --prune
```

## GUI

An interactive GUI is also available.

```
uv run python app/gui/main.py
```

## CLI Reference

Commands are implemented in [main.py](main.py).

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

- [main.py](main.py) — CLI entry point
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
