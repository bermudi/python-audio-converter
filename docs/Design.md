# Design Document: Python Audio Converter (FLAC → AAC Mirror)

Version: 0.1 (Draft)
Date: 2025-08-19
Related: docs/SRS.md

## 1. Overview and Goals

- Mirror a local FLAC library to an AAC (M4A) library with a 1:1 directory structure.
- Encode using FFmpeg with libfdk_aac at ~256 kbps VBR (default), no additional audio processing.
- Preserve metadata and cover art as faithfully as possible.
- Provide a Linux desktop GUI with parallel conversion and resumable, incremental runs.
- Maintain a local SQLite state database to avoid re-encoding unchanged files even when the destination is absent.

Non-goals (for v1):
- Cross-platform packaging beyond Linux.
- Advanced DSP features (normalization, EQ, trimming, resampling).
- Streaming or server mode.

## 2. High-Level Architecture

Data flow:

1) Scan Source → 2) Plan (Change Detection vs DB) → 3) Job Queue → 4) Parallel Encoders → 5) Metadata/Art ensure → 6) Output Write → 7) State DB Update → 8) Report

Components:
- Scanner
- Planner
- Scheduler (worker pool)
- Encoder Worker (FFmpeg)
- Metadata Copier/Verifier
- State DB (SQLite)
- GUI (PySide6)
- Config + Logging

## 3. Component Design

### 3.1 FFmpeg Preflight
- At startup (and on demand), run `ffmpeg -hide_banner -encoders` and verify `libfdk_aac` is present.
- Capture `ffmpeg -version` and encoder flags in settings/runtime info.
- Failure: show actionable guidance to install FFmpeg with libfdk_aac; block conversion.

### 3.2 Scanner
- Walk source directory recursively.
- For each `.flac` file, collect:
  - relpath (relative to source root)
  - size (bytes), mtime (ns)
  - FLAC STREAMINFO MD5 (if available) without hashing full file
  - duration (optional; via ffprobe or mutagen)
- Output: list of `SourceFile` records.

### 3.3 State DB (SQLite)
- Location: `~/.local/share/python-audio-converter/state.sqlite` (configurable).
- Initial schema (aligned with SRS §5.2):
  - files(
    src_path TEXT PRIMARY KEY,
    rel_path TEXT NOT NULL,
    size BIGINT NOT NULL,
    mtime BIGINT NOT NULL,
    flac_md5 TEXT NULL,
    sha256 TEXT NULL,
    duration_ms INT NULL,
    encoder TEXT NOT NULL,
    vbr_quality INT NOT NULL,
    container TEXT NOT NULL,
    last_converted_at DATETIME NOT NULL,
    output_rel TEXT NOT NULL
  )
  - runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    ffmpeg_version TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    stats_json TEXT NULL
  )
  - file_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INT NOT NULL REFERENCES runs(id),
    src_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('converted','skipped','failed')),
    reason TEXT NULL,
    elapsed_ms INT NULL
  )
- Migration strategy: minimal, versioned via `PRAGMA user_version`; simple forward migrations encoded in code.

### 3.4 Planner (Change Detection)
- For each scanned file, lookup prior record by `src_path`.
- A file is “stale” if any of:
  - Not in DB.
  - `size` or `mtime` differs.
  - FLAC MD5 differs (if available and stored).
  - Encoder settings differ (encoder name, VBR quality, container).
- Plan entries include: input path, output relative path, chosen `-vbr` level, and metadata copy plan.
- Dry-run produces a human-readable and JSON plan.

### 3.5 Encoder Worker
- Subprocess invocation of FFmpeg. Default flags:
  - `-y` (overwrite only when explicitly allowed by app setting during staging; otherwise write to temp file then move)
  - `-nostdin -hide_banner -loglevel error`
  - Input: source FLAC
  - Audio: `-c:a libfdk_aac -vbr <q>` (default q≈5 for ~256 kbps)
  - Threads: `-threads 1` to avoid oversubscription; overall concurrency controlled by worker pool
  - Metadata: `-map_metadata 0` to copy input tags
  - Container: M4A (file extension `.m4a`)
  - MP4 metadata: `-movflags +use_metadata_tags`
- Cover art handling:
  - FFmpeg’s automatic mapping from FLAC attached pictures to MP4 cover art is inconsistent; to guarantee results, perform a post-encode step using Mutagen to embed front cover into MP4 atom if not present after encode.
- Output workflow:
  - Write to temporary file under destination (`.part` extension), then atomically rename to final path on success.
  - On failure, remove temp file and log reason.

### 3.6 Metadata Copier/Verifier
- Use Mutagen:
  - Read Vorbis Comments from FLAC, map to MP4 atoms where possible.
  - Preserve common fields: title, artist, album, albumartist, track/totaltracks, disc/totaldiscs, date/year, genre, compilation, MusicBrainz IDs, comment.
  - Copy embedded cover art (prefer front cover) to MP4 covr atom; scale/convert image only if required by MP4 constraints.
- Verification:
  - After encode, re-open output and compare a subset of tags; warn if any field fails to persist.

### 3.7 Scheduler and Parallelism
- Use a bounded worker pool managing subprocess jobs.
- Implementation options:
  - Python `concurrent.futures.ThreadPoolExecutor` (sufficient since heavy work is in FFmpeg).
  - Or Qt `QThreadPool` to integrate tightly with GUI. The UI will remain responsive either way via signals.
- Default workers: `min(physical_cores, 8)`; configurable.
- Backpressure: limit queue size; compute expected disk and CPU load; optionally stagger job start to avoid disk thrash.

### 3.8 GUI (PySide6)
- Windows/Views:
  - Setup: choose Source and Destination; test FFmpeg.
  - Scan Results: counts, preview list, filters (new/changed/failed previously).
  - Convert: overall progress + table with per-file status, bitrate, elapsed; pause/resume/cancel; retry failed.
  - Settings: VBR quality, workers, output template, hashing toggle, DB location, logging level.
  - Logs/Report: live log pane, export run report (JSON and text).
- Architecture:
  - MVC-ish: a `JobModel` (QAbstractTableModel) for file rows; a `Controller` to orchestrate scanner/planner/scheduler; `Views` bound to model.
  - Signals/slots for progress and status updates.

### 3.9 Config
- Pydantic settings model; persisted as TOML under `~/.config/python-audio-converter/config.toml`.
- Key fields: source, destination, vbr_quality (default 5), workers, hashing mode (none|flac_md5|sha256), output template, logging level, db path.

### 3.10 Logging & Reporting
- Use `loguru` + optional JSON logs (one line per event) to file.
- Per-file and per-run summaries, including ffmpeg stderr snippets on error.
- Exit codes per SRS.

## 4. Concurrency & Performance
- Each encode uses `-threads 1` to make throughput mostly proportional to number of workers; avoid CPU oversubscription.
- I/O considerations: stagger job start, prefer sequential writes by limiting concurrent outputs or by randomizing start order to avoid hot directories.
- Temp files: write to same filesystem as destination to keep atomic rename cheap.
- Large libraries: use incremental commits to DB; wrap batches in transactions for performance.

## 5. FFmpeg Invocation Details
- Base command template:
```
ffmpeg -nostdin -hide_banner -loglevel error \
  -i "{src}" \
  -map_metadata 0 -movflags +use_metadata_tags \
  -c:a libfdk_aac -vbr {q} -threads 1 \
  -vn \
  "{tmp_out}"
```
- Notes:
  - `-vn` ensures no video streams are carried over; cover art is later ensured via Mutagen if missing.
  - If source has multiple audio streams (rare for FLAC), map the first by default; log a warning.

## 6. Change Detection Algorithm
- Primary key: `src_path` (absolute) and `rel_path` for output mapping.
- Compare current scan to DB entry:
  - If FLAC MD5 available: use it; otherwise rely on `size` + `mtime`; optional `sha256` when hashing enabled.
  - If encoder settings changed (e.g., VBR quality), mark as stale.
- When destination is mounted, optionally verify the presence and container/bitrate of existing outputs; however, correctness relies solely on local DB.

## 7. File Naming and Templates
- Default: preserve relative directory and base name; replace `.flac` with `.m4a`.
- Template tokens (future): `{artist}/{album}/{track:02d} {title}.m4a` etc. For v1, keep default simple; expose read-only preview in UI.

## 8. Error Handling
- Categories: Preflight (missing libfdk_aac), Encode failure, Metadata failure, Filesystem errors.
- Retries: one retry for transient I/O; no retries for deterministic encode errors.
- Cleanup: remove tmp files on failure; leave logs.

## 9. Testing Strategy
- Unit tests: path mapping, DB ops, change detection, config, FFmpeg preflight parsing.
- Integration tests:
  - Small FLAC fixtures with diverse tags and embedded art.
  - Validate output: container, average bitrate range for q=5, tag parity, cover presence.
- Concurrency: simulate N workers, ensure DB consistency and UI responsiveness.

## 10. Security, Privacy, Licensing
- No telemetry. All data local.
- libfdk_aac licensing: do not bundle; require system FFmpeg with libfdk_aac. Provide distro-specific guidance in docs.

## 11. Risks and Mitigations
- Risk: Users lacking libfdk_aac. Mitigation: clear checks and docs.
- Risk: Metadata mapping gaps FLAC→MP4. Mitigation: post-process with Mutagen; document non-mappable fields.
- Risk: High I/O contention on HDDs. Mitigation: limit concurrent writes; allow user to tune workers.

## 12. Open Questions
- Exact default VBR quality to hit ~256 kbps for typical stereo; initial pick q=5, verify on corpus and document.
- Behavior when cover art is too large/unsupported format—resize or reject? (Current plan: convert to JPEG/PNG within limits.)

## 13. Implementation Plan (Mapping to Modules)
- `src/pac/ffmpeg_check.py`: probe for ffmpeg + libfdk_aac, parse versions.
- `src/pac/scanner.py`: filesystem walk, FLAC MD5/duration extraction.
- `src/pac/db.py`: SQLite access, migrations, CRUD for files/runs.
- `src/pac/planner.py`: change detection and plan generation; dry-run formatter.
- `src/pac/encoder.py`: FFmpeg command builder, execution, tmp→final move, stderr capture.
- `src/pac/metadata.py`: tag mapping FLAC→MP4, cover art ensure/verify.
- `src/pac/scheduler.py`: worker pool; backpressure; pause/resume/cancel hooks.
- `app/gui/`: PySide6 main window, models, views, controllers.
- `tests/`: unit and integration suites with fixtures.

## 14. Tooling and Packaging
- Python 3.12, managed via `uv` (no raw pip).
- Dependencies (initial): PySide6, mutagen, pydantic, loguru, rich, tqdm.
- Scripts: development runner for GUI, and optional headless entry point later.
