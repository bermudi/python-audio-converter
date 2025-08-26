# Design Document: Python Audio Converter (FLAC → AAC Mirror)

Version: 0.2 (Draft)
Date: 2025-08-19
Related: docs/SRS.md

## 1. Overview and Goals

- Mirror a local FLAC library to an AAC (M4A) library with a 1:1 directory structure.
- Encode to AAC (M4A) targeting ~256 kbps VBR. Preferred backend: FFmpeg with libfdk_aac. Fallbacks: FFmpeg decode piped to `qaac` (true VBR), then to `fdkaac`. No additional audio processing.
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
- Detect available encoder backends:
  - `ffmpeg` and whether `libfdk_aac` is enabled (via `ffmpeg -hide_banner -encoders`).
  - `qaac` CLI (version/info via `qaac --check`).
  - `fdkaac` CLI.
- Record paths and versions in runtime info. Do not block conversion if `libfdk_aac` is missing; select the best available backend per policy: ffmpeg+libfdk_aac > qaac(pipe) > fdkaac(pipe).
- If none are available, report actionable guidance to install at least one backend and block conversion.
 - Probe is executed once per run to select a stable backend for planning and execution, ensuring consistent DB decisions within a run. Selection order: ffmpeg+libfdk_aac > qaac(pipe) > fdkaac(pipe).

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
    last_converted_at DATETIME NULL,
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
 - Indexes: files(rel_path), files(output_rel), files(last_converted_at), file_runs(run_id), file_runs(src_path), file_runs(status).
 - Migration v3 adds the above indexes and sets CHECK constraint on file_runs.status where missing.

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
- Subprocess pipelines, selected in this order:
  1) FFmpeg with `libfdk_aac` (single process):
     - Flags:
       - `-nostdin -hide_banner -loglevel error -threads 1`
       - `-map 0:a:0 -vn` (explicit first audio stream; ignore video/subs/data)
       - `-map_metadata 0 -movflags +use_metadata_tags+faststart`
       - `-c:a libfdk_aac -vbr <q>` (default q≈5 for ~256 kbps)
  2) FFmpeg decode → `qaac` encode (pipe, true VBR):
     - FFmpeg decode to WAV on stdout with explicit mapping and decode intent:
       `-map 0:a:0 -vn -sn -dn -acodec pcm_s24le -f wav -`
       Encoder reads from stdin: `qaac --tvbr <n> -o "{tmp_out}" -` (default 96 ~256 kbps).
  3) FFmpeg decode → `fdkaac` encode (pipe):
     - FFmpeg decode to WAV on stdout with explicit mapping and decode intent:
       `-map 0:a:0 -vn -sn -dn -acodec pcm_s24le -f wav -`
       Encoder reads from stdin: `fdkaac -m <mode> -o "{tmp_out}" -` (target ~256 kbps).
- Threads: use `-threads 1` per encode; overall concurrency controlled by worker pool.
- Metadata handling:
  - Always run a post-encode step using Mutagen to ensure tag and cover art parity (FLAC → MP4). This guarantees consistent cover art even when encoders differ in automatic mapping.
- Output workflow:
  - Write to temporary file under destination (`.part` extension), then atomically rename to final path on success. On failure, remove temp file and log reason.
 - PCM precision: Default is 24‑bit (`pcm_s24le`) to preserve headroom; allow `pcm_f32le` via settings.

### 3.6 Metadata Copier/Verifier
- Use Mutagen:
  - Read Vorbis Comments from FLAC, map to MP4 atoms where possible.
  - Preserve common fields: title, artist, album, albumartist, track/totaltracks, disc/totaldiscs, date/year, genre, compilation, MusicBrainz IDs, comment.
  - Copy embedded cover art (prefer front cover) to MP4 covr atom; if the source art is too large or in an unsupported format, convert to JPEG/PNG and optionally cap the longer side to a configurable maximum (e.g., 1500 px).
- Verification (optional, `--verify-tags`):
  - After encode and tag copy, re-open FLAC and MP4 and compare a subset:
    - Title (©nam)
    - Artist (©ART)
    - Album (©alb)
    - Album Artist (aART)
    - Track/total (trkn) and Disc/total (disk)
    - Date/Year (©day) comparing by leading year when both present
    - Genre (©gen) as a string
    - Cover presence (covr exists if source had art)
  - Normalization rules:
    - Normalize Unicode to NFC and trim whitespace on both sides before comparison. Keep case‑sensitive comparison.
    - Parse integers for track/disc tuples; treat missing as 0.
    - For dates, compare the first 4-digit year if both provided.
  - Output: a list of discrepancy strings, e.g., `"title: expected='X' got='Y'"`, `"cover: missing"`.
  - Reporting: when enabled, include verification totals in the run summary: `checked`, `ok`, `warn`, `failed`.
  - Policy: When strict verification is enabled, any tag‑copy exception or verification discrepancy marks the file as failed.
  - Logging: emit a `verify` event with `status=ok|warn|failed` and an array of discrepancies.
  - Strict mode (`--verify-strict`): if discrepancies exist, mark file as failed.

### 3.7 Scheduler and Parallelism
 - Use a bounded worker pool managing subprocess jobs (only O(workers) tasks in flight), providing backpressure on very large catalogs.
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
- Key fields:
  - log_level, log_json
  - tvbr (qaac), vbr (libfdk/fdkaac), workers
  - hash_streaminfo, force, commit_batch_size
  - verify_tags, verify_strict
  - future: pcm_codec (pcm_s24le|pcm_f32le), faststart toggle, scan_duration, progress default, log rotation/retention
  - Note: Settings are merged from defaults + TOML + env (PAC_*) + CLI overrides; `--write-config` emits the effective TOML.

### 3.10 Logging & Reporting
- Use `loguru` with human console logs and optional structured JSON lines. Standard event fields: ts, action, file, rel_path, status, elapsed_ms, bytes_out, encoder, quality, run_id. A per‑run JSON summary is always written. Support log rotation/retention via settings.
- Per-file and per-run summaries, including ffmpeg stderr snippets on error.
- Exit codes per SRS.
 - Event types include: `preflight`, `scan`, `plan`, `encode`, `verify` (when enabled).

## 4. Concurrency & Performance
- Each encode uses `-threads 1` to make throughput mostly proportional to number of workers; avoid CPU oversubscription.
- I/O considerations: stagger job start, prefer sequential writes by limiting concurrent outputs or by randomizing start order to avoid hot directories.
- Temp files: write to same filesystem as destination to keep atomic rename cheap.
- Large libraries: use incremental commits to DB; wrap batches in transactions for performance.
 - Task submission is bounded (~2×workers) to maintain a stable memory/FD footprint on catalogs with ≥100k files.

## 5. FFmpeg Invocation Details
- Base command template (preferred, libfdk_aac):
```
ffmpeg -nostdin -hide_banner -loglevel error
  -i "{src}" -map 0:a:0 -vn
  -map_metadata 0 -movflags +use_metadata_tags+faststart
  -c:a libfdk_aac -vbr {q} -threads 1
  "{tmp_out}"
```
 - Pipe to qaac (true VBR), approximate shell representation:
```
ffmpeg -nostdin -hide_banner -loglevel error
  -i "{src}" -map 0:a:0 -vn -sn -dn -acodec pcm_s24le -f wav -
| qaac --tvbr {tvbr} -o "{tmp_out}" -
```

 - Pipe to fdkaac (example, adjust quality flags per target):
```
ffmpeg -nostdin -hide_banner -loglevel error
  -i "{src}" -map 0:a:0 -vn -sn -dn -acodec pcm_s24le -f wav -
| fdkaac -m 5 -o "{tmp_out}" -
```

 - Notes:
  - Always use explicit stream mapping (`-map 0:a:0`) to avoid accidental multi‑stream behavior.
  - `-vn` ensures no video streams are carried over; cover art is later ensured via Mutagen if missing.
  - For piping, we use robust subprocess management without temp WAV files; stderr is captured for diagnostics.

## 6. Change Detection Algorithm
- Primary key: `src_path` (absolute) and `rel_path` for output mapping.
- Compare current scan to DB entry:
  - If FLAC MD5 available: use it; otherwise rely on `size` + `mtime`; optional `sha256` when hashing enabled.
  - If encoder settings changed (e.g., VBR quality), mark as stale.
- When destination is mounted, optionally verify the presence and container/bitrate of existing outputs; however, correctness relies solely on local DB.

## 7. File Naming and Templates
- Default: preserve relative directory and base name; replace `.flac` with `.m4a`.
- Template tokens (future): `{artist}/{album}/{track:02d} {title}.m4a` etc. For v1, keep default simple; expose read-only preview in UI.
 - Destination sanitization and collision resolution are deterministic and case‑insensitive‑safe for FAT/exFAT targets.

## 8. Error Handling
- Categories: Preflight (missing libfdk_aac), Encode failure, Metadata failure, Filesystem errors.
- Retries: one retry for transient I/O; no retries for deterministic encode errors.
- Cleanup: remove tmp files on failure; leave logs.
 - Filesystem errors report errno and perform best‑effort cleanup of temporary outputs; a single retry is allowed for transient errors (e.g., EBUSY).

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
- Risk: Users lacking libfdk_aac. Mitigation: clear checks and automatic fallback to `qaac` or `fdkaac`; document runtime requirements (qaac needs user-supplied Apple CoreAudio components).
- Risk: Metadata mapping gaps FLAC→MP4. Mitigation: post-process with Mutagen; document non-mappable fields.
- Risk: High I/O contention on HDDs. Mitigation: limit concurrent writes; allow user to tune workers.

## 12. Open Questions
- Exact default VBR quality to hit ~256 kbps for typical stereo; initial pick q=5, verify on corpus and document.
- Behavior when cover art is too large/unsupported format—resize or reject? (Current plan: convert to JPEG/PNG within limits.)

## 13. Implementation Plan (Mapping to Modules)
- `src/pac/ffmpeg_check.py`: probe for ffmpeg + libfdk_aac, and presence/versions of `qaac` and `fdkaac`.
- `src/pac/scanner.py`: filesystem walk, FLAC MD5/duration extraction.
- `src/pac/db.py`: SQLite access, migrations, CRUD for files/runs.
- `src/pac/planner.py`: change detection and plan generation; dry-run formatter.
- `src/pac/encoder.py`: FFmpeg command builder, pipe-to-qaac/fdkaac execution, tmp→final move, stderr capture.
- `src/pac/metadata.py`: tag mapping FLAC→MP4, cover art ensure/verify.
- `src/pac/scheduler.py`: worker pool; backpressure; pause/resume/cancel hooks.
- `app/gui/`: PySide6 main window, models, views, controllers.
- `tests/`: unit and integration suites with fixtures.
 - `src/pac/paths.py`: destination sanitization and collision resolution (case‑insensitive aware).

## 14. Tooling and Packaging
- Python 3.12, managed via `uv` (no raw pip).
- Dependencies (initial): PySide6, mutagen, pydantic, loguru, rich, tqdm, tomlkit.
- Runtime encoder backends (external, not Python deps):
  - FFmpeg built with libfdk_aac (preferred), or
  - `qaac` CLI (requires Apple CoreAudio components provided by user), or
  - `fdkaac` CLI.
- Scripts: development runner for GUI, and optional headless entry point later.
