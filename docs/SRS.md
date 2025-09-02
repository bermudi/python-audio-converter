# Software Requirements Specification (SRS)

Project: Python Audio Converter (FLAC → AAC Mirror)
Version: 0.2 (DB-less, stateless addendum)
Date: 2025-08-19
Owner: daniel

---

## 1. Introduction

- Purpose: Define requirements for a desktop application that mirrors a local FLAC library to an AAC (M4A) library for Bluetooth streaming, preserving directory structure and metadata. Optimized for a power user automating batch conversions on Linux.
- Scope: Scan a source library directory, convert new/changed FLAC files to AAC using Fraunhofer FDK AAC at ~256 kbps VBR, store conversion state locally (not on the destination), and provide a GUI with parallel processing and progress visibility. No audio processing beyond encode (no normalization, no resampling unless required by encoder). Metadata parity is a must.
- Personas: Power user with large hi‑fi FLAC collection; prefers automation and repeatable runs.
- Definitions:
  - FLAC: Free Lossless Audio Codec
  - AAC: Advanced Audio Coding
  - FDK AAC: Fraunhofer FDK AAC encoder (libfdk_aac)
  - M4A: MP4 container for AAC audio

## 2. System Overview

- High-level flow (v0.2): Source scan → Destination scan (PAC_* read) → Stateless plan → Parallel transcodes (AAC/Opus backends) → Tag copy + embed PAC_* → Atomic write/rename → Optional retag/rename/prune → Report.
- Backend is selected once per run (stable selection) to keep planning and DB decisions consistent.
- Components:
  - Scanner: Walks source directory, computes identifiers for change detection (see §5.2).
  - Destination Index (v0.2): Filesystem scan of outputs (.m4a/.opus) that reads embedded PAC_* tags to derive state without a local DB.
  - Scheduler: Batches and runs conversion jobs in parallel with backpressure.
  - Encoder Backend: Preferred FFmpeg+libfdk_aac. Fallbacks: FFmpeg decode piped to `qaac` (true VBR) then to `fdkaac`.
  - Metadata Copier: Ensures tags and cover art are preserved (1:1 when feasible).
  - GUI: Desktop app for configuring paths, running scans, starting/stopping jobs, and viewing progress/logs.
- External dependencies: FFmpeg (required). Encoders: libfdk_aac (preferred) via FFmpeg; `qaac` and `fdkaac` supported as fallbacks. System-level install on Linux.

## 3. Functional Requirements

FR-1: The system shall mirror a source FLAC library to an AAC (M4A) destination, preserving relative directory structure and file base names, changing only the extension to .m4a.

FR-2: The system shall encode AAC using this ordered backend selection: (1) FFmpeg with libfdk_aac; (2) FFmpeg decode piped to `qaac`; (3) FFmpeg decode piped to `fdkaac`. If none are available, preflight shall fail with clear remediation guidance.

FR-3: The system shall target a VBR mode that yields approximately 256 kbps for typical stereo content. The VBR quality level shall be configurable; default quality shall be chosen to approximate ~256 kbps on average across a corpus. The system shall record the chosen quality in the state DB.

FR-4: The system shall perform no audio processing beyond encode (no normalization, EQ, DRC, silence trimming, channel remixing), except where the encoder requires format adaptation (e.g., converting non‑PCM to PCM before encoding).

FR-5: The system shall preserve metadata tags (artist, album, title, track number, disc, date/year, genre, album artist, compilation flag, MusicBrainz IDs when present) and cover art when possible. Failures to copy any field or art shall be logged per file.

FR-A (stateless): The system shall not require a local database. All change detection derives from current source tree, destination tree, and metadata embedded in outputs.

FR-B (fingerprint): The system shall embed in each output: PAC_SRC_MD5 (FLAC STREAMINFO MD5), PAC_ENCODER, PAC_QUALITY, PAC_VERSION, PAC_SOURCE_REL.

FR-C (move/rename): The system shall detect moved/renamed sources by matching PAC_SRC_MD5 in destination and may rename outputs instead of re-encoding.

FR-D (adoption): When outputs lack PAC_* (older runs), the system shall optionally adopt them as up-to-date if present at expected path and retag to add PAC_*; a `--no-adopt` policy forces re-encode instead.

FR-E (prune): The system shall optionally identify/prune orphan outputs whose PAC_SRC_MD5 has no source counterpart.

FR-8: The system shall support parallel conversion with a configurable number of workers. Default shall be a sensible fraction of available CPU cores.

FR-9: The system shall provide a GUI that allows:
  - Selecting the source FLAC directory and destination (local path or removable/media mount path for staging/export).
  - Scanning to show counts of new/changed/unchanged files and estimated work.
  - Starting/stopping/pause/resume of the conversion job.
  - Viewing per‑file progress, current workers, and overall progress.
  - Viewing recent logs and errors; exporting a run report.

FR-10: The system shall provide a dry-run (scan only) that produces a plan without encoding.

FR-11: The system shall produce deterministic output paths using a template (default: preserve relative path; `.flac` → `.m4a`). Template shall be configurable in settings.

FR-12: The system shall handle name conflicts and illegal characters in destination filesystem, applying safe transformations and logging any changes. Include case-insensitive collision safety for common removable filesystems (e.g., FAT/exFAT).

FR-13: The system shall allow re-scan and incremental runs without manual cleanup.

FR-14: The system shall exit with non‑zero code when any file fails, and shall summarize failures in the report.

FR-15: The system shall optionally verify a subset of metadata tags and cover art after encoding and tag copy. When enabled, the system shall re-open the output M4A and compare Title, Artist, Album, Album Artist, Track/Disc numbers, Date/Year, Genre, and the presence of cover art (only when the source had art). Discrepancies shall be logged and included in the structured report. A strict mode shall cause the file to be marked as failed when any discrepancy is detected.

Optional (future): CLI parity for headless automation.

FR-16: The system shall emit structured JSON line events (optional) and shall always write a per‑run summary JSON including counts, timing, and verification totals. Log rotation/retention shall be configurable.

FR-17: The system shall allow configuring the PCM decode codec used when piping FFmpeg to external encoders via a setting and CLI flag `--pcm-codec` with choices `pcm_s24le`, `pcm_f32le`, or `pcm_s16le`. The default shall be `pcm_s24le`.

FR-18..FR-20 (legacy modes): Replaced by simpler flags and planner actions in v0.2:
- `--retag-existing` (default on), `--rename` (default on), `--prune`, `--no-adopt`, `--force-reencode`.

## 4. Non‑Functional Requirements

NFR-1 Performance: With N workers on an 8‑core CPU and SSD storage, the system should achieve near‑linear scaling up to saturation of CPU or I/O for typical stereo FLACs. Target throughput and CPU utilization thresholds to be finalized in acceptance (§8).

NFR-2 Reliability: Re‑runnable and idempotent without external state. If interrupted, a subsequent run re-plans from filesystem and embedded PAC_* tags.

NFR-3 Usability: GUI shall expose safe defaults and advanced settings behind an “Advanced” pane. Progress shall be clear and actionable.

NFR-4 Portability: Linux (primary). GUI and dependencies shall be available via Python packaging. Other OS may be considered later.

NFR-5 Observability: Structured logs (JSON lines optional) and human‑readable logs. Per‑file summaries include input, output, bitrate, duration, tag copy result, verification discrepancies when enabled, and elapsed time. Logs follow a consistent schema and support rotation/retention to bound disk usage.

NFR-6 Security/Privacy: No external telemetry. No upload of audio content. Store state locally under user’s config/data directory.

NFR-7 Scalability of scheduling: The scheduler shall bound in‑flight work items to O(workers) to maintain stable memory and file descriptor usage on catalogs ≥100k files.

## 5. Constraints and Assumptions

5.1 Licensing: libfdk_aac availability varies and may be non‑free in some contexts. The app shall not bundle any encoder. It shall rely on system tools: FFmpeg (required), and optionally `qaac`/`fdkaac`. Documentation shall provide install guidance for each.

5.2 Local state: None (v0.2). The filesystem and PAC_* tags are the single source of truth. When STREAMINFO MD5 is unavailable, fallback heuristics may use size+mtime or full SHA256 as configured.

5.3 Environment: Python 3.12. System FFmpeg (libfdk_aac preferred). Optional `qaac` and `fdkaac` as fallbacks. GUI via Qt (PySide6) on Linux.

## 6. GUI Specification (High‑Level)

- Main Views:
  - Setup: choose Source dir; choose Destination root (local path for staging/export to player).
  - Scan Results: counts of New/Changed/Unchanged, list preview with filters.
  - Convert: live progress table (file, status, bitrate, elapsed), overall progress bar, workers panel, logs pane.
  - Settings: workers (parallelism), VBR quality (default ~256 kbps target), output template, hashing toggle, logging level, state DB location, advanced FFmpeg args (read‑only by default).
- Behaviors:
  - Pause/Resume; Cancel (graceful stop after current files); Retry failed only.
  - Double‑click a file to view detailed log and tag mapping.

## 7. Processing Pipeline and Encoding Parameters

- Decode: FLAC via FFmpeg.
- Encode: AAC LC via preferred libfdk_aac; fallbacks: `qaac` (true VBR, e.g., `--tvbr 96`) then `fdkaac` (e.g., VBR mode 5).
- Container: M4A (MP4). FFmpeg should write metadata tags compatible with MP4.
- Suggested defaults (subject to validation):
  - Primary (FFmpeg libfdk_aac): include explicit mapping and faststart:
    `-map 0:a:0 -vn -map_metadata 0 -movflags +use_metadata_tags+faststart -c:a libfdk_aac -vbr <q> -threads 1`.
  - Fallback (qaac pipe): decode with explicit mapping and decode intent:
    `-map 0:a:0 -vn -sn -dn -acodec <pcm_codec> -f wav -` piped to `qaac --tvbr <n>`.
  - Fallback (fdkaac pipe): same decode mapping to `fdkaac -m <mode>`.
  - Default PCM precision is 24‑bit (`pcm_s24le`) to preserve headroom; allow `pcm_f32le` or `pcm_s16le` via setting/CLI `--pcm-codec`.
  - Always include `-vn -sn -dn` during decode and set `-movflags +use_metadata_tags+faststart` for MP4 output.
  - Cover art/tags normalized post‑encode via Mutagen to ensure parity.
- No resample/channel change unless required by encoder.

## 8. Testing and QA

- Unit: path templating, DB schema ops, change detection logic, settings.
- Integration: end‑to‑end encode of sample FLACs; verify duration, container, average bitrate range, and tag parity (mutagen).
- Golden samples: curated FLAC set with various tag combinations and embedded art.
- Concurrency: stress tests with N workers; ensure no DB contention or race conditions.
 - Collision resolution tests include case‑insensitive scenarios.
 - Scheduling tests confirm bounded in‑flight tasks under large catalogs.
 - Verification tests include Unicode normalization and whitespace rules.
- Failure modes: missing libfdk_aac, corrupted FLAC, write permission errors, out‑of‑space.

## 9. Acceptance Criteria (Initial Targets)

AC-1: On a corpus of ≥10k stereo FLAC tracks, repeated runs convert only new/changed files; unchanged files are skipped with zero re‑encodes.

AC-2: For default settings, average AAC bitrate over the corpus shall be approximately 256 kbps for stereo content (tolerance band to be measured on test corpus; document actual result).

AC-3: Metadata parity: ≥99.5% tag fields and cover art successfully copied where applicable; failures logged with reason.

AC-4: Stability: Zero crashes across 3 full library runs; all failures reported per file with actionable messages.

AC-5: Performance: With parallelism set to min(physical_cores, 8), sustained throughput scales with workers until CPU saturates; no more than 10% slowdown caused by DB overhead.

AC-6 (Collision safety): On a destination mounted with a case‑insensitive filesystem, no collisions occur after sanitization and resolution; outputs are deterministic.

AC-7 (Scheduler footprint): With W workers and catalog size ≥50k, peak in‑flight tasks ≤2W and memory/FD footprint remains stable.

## 10. Deployment and Packaging

- Python packaging managed with `uv`.
- App distributed as a Python package; runs as a GUI application.
- Preflight validates presence of at least one suitable AAC backend (prefer `libfdk_aac`; otherwise `qaac` or `fdkaac`) and reports the selected backend.
- Optional: Provide a Dockerfile for development, noting libfdk_aac constraints.

## 11. Error Handling and Logging

- Structured logs with file context, encoder version, and error codes.
- Exit codes: 0 (success, no failures), 2 (completed with file failures), 3 (preflight failure: no suitable AAC encoder found).
- GUI displays last N errors; export full JSON report.
 - Per‑file structured events use a standard schema; a per‑run summary JSON is always written. Rotation/retention are configurable.

## 12. Risks and Open Questions

- libfdk_aac availability varies; users may need custom FFmpeg builds.
- Exact VBR quality setting to hit ~256 kbps varies with content; default will be empirically chosen and documented.
- Destination is not always mounted; only local DB signals completed conversions. Provide optional verification mode when destination is available.
- Verification is best-effort; normalization differences (e.g., whitespace, casing, date formats) may cause benign mismatches. Strict mode should be used carefully.
 - Case‑insensitive/reserved names on removable media may still surface edge cases; mitigated by enhanced sanitizer and collision resolution.
 - Cover art downscaling policy (max dimensions/format) is configurable; defaults will be documented.

## 13. References and Glossary

- FFmpeg documentation (encoders, metadata mapping).
- Mutagen (Python metadata library) documentation.
- AAC/MP4 tagging references.
