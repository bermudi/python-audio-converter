# Python Audio Converter (PAC)

Mirror a FLAC library to an AAC (M4A) library with 1:1 directory structure and metadata parity. Optimized for Linux power users. Prefers FFmpeg with libfdk_aac; falls back to qaac or fdkaac. Parallel, resumable runs with a local SQLite state DB.

- Docs: see [docs/SRS.md](cci:7://file:///home/daniel/build/python-audio-converter/docs/SRS.md:0:0-0:0) and [docs/Design.md](cci:7://file:///home/daniel/build/python-audio-converter/docs/Design.md:0:0-0:0)
- Package: `src/pac/`
- Entry point: [main.py](cci:7://file:///home/daniel/build/python-audio-converter/main.py:0:0-0:0)

## Features

- Mirror FLAC → AAC (M4A) preserving directories and filenames
- Encoder selection: ffmpeg+libfdk_aac > qaac(pipe) > fdkaac(pipe)
- Quality targets around ~256 kbps VBR (configurable)
- Tag and cover art copy (FLAC → MP4)
- Parallel workers; atomic writes; resumable runs
- Local SQLite DB to skip unchanged files even if destination is not mounted
- Dry-run planning and clear summaries
- Exit codes for automation

## Requirements

- Python: 3.12+
- Linux
- System tools:
  - Required: FFmpeg
  - Preferred: FFmpeg with libfdk_aac enabled
  - Optional fallbacks: `qaac` CLI, `fdkaac` CLI
- Python deps are declared in [pyproject.toml](cci:7://file:///home/daniel/build/python-audio-converter/pyproject.toml:0:0-0:0) (managed with uv)

Notes:
- libfdk_aac availability varies by distro. If missing, PAC will try `qaac` (true VBR) then `fdkaac`.
- `qaac` on Linux requires user-provided Apple CoreAudio components (non-trivial). If unavailable, `fdkaac` is a simpler fallback.

## Install (with uv)

Use uv for environments and dependencies (no raw pip).

- Bootstrap venv and install deps:
  - uv sync
- Verify the interpreter is from the uv venv:
  - uv run which python
- Run commands via uv:
  - uv run python main.py preflight

## Quick Start

1) Preflight encoders:
```
uv run python main.py preflight
```
2) Initialize state DB (one-time):
```
uv run python main.py init-db
```
3) Convert a single file:
```
uv run python main.py convert "/path/in.flac" "/path/out.m4a" --tvbr 96 --pcm-codec pcm_s24le
```
4) Batch convert a directory (dry-run first):
```
uv run python main.py convert-dir --in "/music/FLAC" --out "/music/AAC" --dry-run
```
5) Run for real with parallel workers:
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

## CLI Reference

Commands are implemented in [main.py](cci:7://file:///home/daniel/build/python-audio-converter/main.py:0:0-0:0).

- preflight
  - Checks for FFmpeg, libfdk_aac, and optional `qaac`/`fdkaac`
- init-db
  - Creates SQLite DB under `~/.local/share/python-audio-converter/state.sqlite`
- convert SRC DEST [--tvbr N]
  - Converts a single file to `.m4a`
  - `--tvbr`: qaac true-VBR scale (default 96 ≈ ~256 kbps typical)
  - `--pcm-codec {pcm_s24le|pcm_f32le|pcm_s16le}`: PCM codec used for ffmpeg decode when piping to qaac/fdkaac (default: `pcm_s24le`)
- convert-dir --in DIR --out DIR [options]
  - Recursively scans `.flac` and mirrors to `.m4a`
  - Options:
    - `--workers INT` (default: CPU cores)
    - `--tvbr INT` (qaac scale; default 96)
    - `--vbr INT` (libfdk_aac/fdkaac 1..5; default 5 ≈ ~256 kbps)
    - `--pcm-codec {pcm_s24le|pcm_f32le|pcm_s16le}` (default `pcm_s24le`)
    - `--hash` / `--no-hash` (default: no-hash)
    - `--verbose` or `-v` (per-phase timing, probe details)
    - `--dry-run` (plan only; prints actions and reasons)
    - `--commit-batch-size INT` (DB commit every N successes; default 32)

Exit codes:
- 0: success
- 2: completed with file failures
- 3: preflight failed (no suitable AAC encoder)

## How It Works

- Preflight: [src/pac/ffmpeg_check.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/ffmpeg_check.py:0:0-0:0) selects encoder once per run:
  - Prefer `ffmpeg` with `libfdk_aac`
  - Else `ffmpeg` decode → `qaac`
  - Else `ffmpeg` decode → `fdkaac`
- Scan: [src/pac/scanner.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/scanner.py:0:0-0:0) catalogs `.flac` (size, mtime, optional FLAC MD5)
- Plan: [src/pac/planner.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/planner.py:0:0-0:0) compares against DB to determine convert/skip and reasons (not in DB, changed size/mtime/md5, quality/encoder change)
- Encode: [src/pac/encoder.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/encoder.py:0:0-0:0) runs the chosen backend
  - libfdk_aac path uses a single ffmpeg process
  - qaac/fdkaac paths pipe WAV from ffmpeg to the encoder
  - Writes to a temp file then atomically renames to final path
- Tags: [src/pac/metadata.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/metadata.py:0:0-0:0) best-effort tag/art copy FLAC → MP4
- Parallelism: [src/pac/scheduler.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/scheduler.py:0:0-0:0) worker pool controls concurrency
- State DB: [src/pac/db.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/db.py:0:0-0:0) SQLite tracks prior conversions by `src_path`, attributes, encoder, vbr, and `output_rel`

## Quality Settings

- Preferred libfdk_aac/fdkaac: VBR mode 1..5; 5 ≈ ~256 kbps typical
- qaac: `--tvbr` scale; 96 is a common transparent setting (~256 kbps typical)
- Actual bitrate varies by content; defaults are chosen to target ~256 kbps on average

## State DB Details

- Location: `~/.local/share/python-audio-converter/state.sqlite` (created automatically)
- Tracks: source path, rel path, size, mtime, (optional) FLAC MD5, encoder, vbr quality, container, output relative path
- Change detection: re-encode only on changes to file attributes, content hash (if stored), or encoder settings
- Destination presence is not required; DB drives decisions

## Project Structure

- [main.py](cci:7://file:///home/daniel/build/python-audio-converter/main.py:0:0-0:0) — CLI entry point
- `src/pac/`
  - [__init__.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/__init__.py:0:0-0:0) — version
  - [ffmpeg_check.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/ffmpeg_check.py:0:0-0:0) — tool detection and versions
  - [scanner.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/scanner.py:0:0-0:0) — source file discovery
  - [planner.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/planner.py:0:0-0:0) — change detection and planning
  - [encoder.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/encoder.py:0:0-0:0) — command builders and pipelines
  - [metadata.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/metadata.py:0:0-0:0) — tag/art copy helpers
  - [db.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/db.py:0:0-0:0) — SQLite lifecycle and queries
  - [scheduler.py](cci:7://file:///home/daniel/build/python-audio-converter/src/pac/scheduler.py:0:0-0:0) — bounded worker pool
- `docs/`
  - [SRS.md](cci:7://file:///home/daniel/build/python-audio-converter/docs/SRS.md:0:0-0:0) — requirements
  - [Design.md](cci:7://file:///home/daniel/build/python-audio-converter/docs/Design.md:0:0-0:0) — architecture and rationale
- `app/` — GUI scaffolding (PySide6) to be added
- `tests/` — unit/integration tests (to be expanded)

## Troubleshooting

- Preflight says “No AAC encoder available”:
  - Install FFmpeg. Prefer a build with libfdk_aac
  - If unavailable, install `fdkaac` (simpler) or `qaac` (requires CoreAudio components)
- Encode failures:
  - Re-run with `-v` to see per-phase timing and stderr capture
- Skips when you expected converts:
  - Use `--hash` for stronger change detection if files are being edited in place without mtime/size change
  - Change `--vbr`/`--tvbr` to force re-encode via settings change

## Roadmap

- PySide6 GUI (configure, scan, run, pause/resume, logs)
- Config persistence with Pydantic (TOML)
- JSON run report export
- More robust tag mapping and cover normalization
- Tests and fixtures for end-to-end verification

## Acknowledgments

- FFmpeg and libfdk_aac
- qaac and fdkaac
- Mutagen

Summary of status
- Drafted a comprehensive README covering install (uv), requirements, CLI usage, workflow, DB behavior, structure, and roadmap.
- Say the word and I’ll write this into README.md for you.