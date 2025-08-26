# Tasks

Generated: 2025-08-22 21:31:28 -06:00

Priority is top-down. Each task has a brief scope and acceptance criteria.

1) Structured logging + JSON run report (CLI)
- Why: SRS §11 requires structured logs/reporting; current code uses prints.
- Scope: Integrate loguru in `main.py`, `src/pac/encoder.py`, `src/pac/ffmpeg_check.py`.
  Add `--log-level`, `--log-json PATH` (JSON lines), and human console logs.
  Emit a per-run JSON summary file for `convert-dir`.
- Accept: Console logs configurable by level; JSON lines file contains events with timestamps and fields (action, file, status, elapsed_ms, bytes_out).
  A run summary JSON is written with totals and timings.
- Refs: `main.py`, `src/pac/encoder.py`, `src/pac/ffmpeg_check.py`.

2) Persist runs/file_runs in DB (schema v2)
- Why: SRS §5.2 tracking; tables exist but are unused and lack constraints.
- Scope: Add migration v2 to add `CHECK(status IN ('converted','skipped','failed'))` and indexes.
  In `convert-dir`, insert `runs` (start/finish, settings, ffmpeg/qaac versions) and `file_runs` per file with status, reason, elapsed.
- Accept: After a run, `runs` row present; `file_runs` count equals processed files.
  Status and timing populated; migration applied automatically.
- Refs: `src/pac/db.py`, `main.py`.

3) Pydantic settings + TOML config
- Why: Centralized config per Design §3.9; currently CLI only.
- Scope: Create `src/pac/config.py` (Pydantic BaseSettings).
  Support `~/.config/python-audio-converter/config.toml` and env vars; CLI overrides.
- Accept: `convert-dir` uses settings defaults; `--write-config` emits current effective config.
- Refs: `pyproject.toml` (pydantic), `main.py`.

4) Destination path sanitization and collision handling (FR‑12)
- Why: Ensure safe filenames across filesystems; avoid overwrites.
- Scope: Implement sanitizer for destination `rel_path` (e.g., replace illegal chars, trim trailing dots/spaces, normalize unicode).
  Add deterministic collision resolver (e.g., suffix `(1)`, `(2)` or hash stub).
- Accept: Unit tests cover pathological names; no crashes due to invalid paths; collisions resolved deterministically.
- Refs: `main.py` path mapping, `src/pac/planner.py`.

5) Post-encode tag verification (optional)
- Why: Ensure critical tags/cover art survive copy (FR‑15 quality, Design §3.6).
- Scope: After `copy_tags_flac_to_mp4`, reopen MP4 and verify a small set (title, artist/album, track/disc, year, genre, cover presence when source had art).
  Controlled by `--verify-tags` (enable) and `--verify-strict` (treat discrepancies as failures).
- Accept: When enabled, discrepancies are logged as `verify` events; JSON run summary includes `verification.enabled/strict` and counts: `verification.checked`, `verification.ok`, `verification.warn`, `verification.failed`. Pipeline succeeds unless `--verify-strict`.
- Refs: `src/pac/metadata.py` (`verify_tags_flac_vs_mp4()`), `main.py` CLI and convert paths, `docs/SRS.md` FR‑15, `docs/Design.md` §3.6.

6) Enrich scan with duration (optional)
- Why: Better reporting; potential bitrate QA.
- Scope: Add optional duration extraction via `ffprobe` or mutagen; store `duration_ms` in DB and run reports (behind `--scan-duration`).
- Accept: When enabled, `files.duration_ms` populated; appears in JSON report.
- Refs: `src/pac/scanner.py`, `src/pac/db.py`.

7) CLI progress UI (tqdm/rich)
- Why: Better UX for long runs; current output is line-per-file.
- Scope: Add `--progress` default on TTY using `tqdm` or `rich` progress bars; keep per-file summary lines optionally via `--verbose`.
- Accept: Smooth progress bar with ETA and counts; non-TTY falls back to plain logs.
- Refs: `main.py`, `pyproject.toml` (tqdm, rich).

8) GUI scaffold (PySide6)
- Why: SRS FR‑9; currently missing.
- Scope: Create `app/gui/` with minimal main window: Preflight → Select In/Out → Plan → Convert.
  Show progress, per-file status, and summary. Use `WorkerPool` and signals.
- Accept: Basic end-to-end conversion from GUI works for a small folder; errors surfaced to the user.
- Refs: `app/`, `src/pac/scheduler.py`, `main.py` logic to reuse.

9) Test suite (pytest)
- Why: Reliability (SRS §8, Design §9).
- Scope: Add pytest config; unit tests for `scanner.read_flac_streaminfo_md5`, planner decisions, DB migrations, metadata copy (with fixtures), and a tiny integration test (1–2 FLACs) using ffmpeg stub if needed.
- Accept: `uv run pytest` passes locally; CI-ready.
- Refs: `tests/`, `src/pac/*`.

10) Docs and installation guidance update
- Why: Help users install ffmpeg/qaac/fdkaac on Linux; document CLI/JSON logs/config.
- Scope: Expand `README.md` with system requirements, preflight instructions, encoder selection rules, examples, and troubleshooting.
  Add section on configuration and logging/reporting.
- Accept: README covers quickstart and advanced options; links to Tasks/Design/SRS.
- Refs: `README.md`, `docs/`.
