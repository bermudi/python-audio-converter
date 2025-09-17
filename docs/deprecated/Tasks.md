# Tasks

Generated: 2025-09-01 19:31:48 -06:00

Priority is top-down. Each task has a brief scope and acceptance criteria.

## Pivot: DB-less, stateless mirror (v0.2)

The project pivots to a stateless design. We remove the local SQLite DB and use filesystem + embedded PAC_* tags in outputs as the single source of truth.

[x] # A. Embed PAC_* fingerprint/settings in outputs (MP4/Opus)
- Why: Make outputs self-describing and enable stateless change detection.
- Scope:
  - Write PAC_SRC_MD5, PAC_ENCODER, PAC_QUALITY, PAC_VERSION, PAC_SOURCE_REL on encode.
  - Mutagen MP4 freeform atoms: `"----:org.pac:..."`; Opus via Vorbis comments.
- Accept: New outputs contain PAC_*; verify step can read them.
- Refs: `src/pac/metadata.py`.

[x] # B. Destination index (scan + PAC_* readers)
- Why: Plan by comparing source vs destination without a DB.
- Scope: New `dest_index.py`; build indices `by_rel` and `by_md5` from `.m4a/.opus` under dest root.
- Accept: Scan lists entries and fingerprints; handles duplicates deterministically.
- Refs: `src/pac/dest_index.py` (new).

[x] # C. Planner v2 (stateless actions)
- Why: Decide {skip, convert, rename, retag, prune} from source/dest + PAC_*.
- Scope: Replace DB-based planner; implement rules per Design v0.2.
- Accept: Dry-run shows counts; executes correctly; JSON summary unchanged in spirit.
- Refs: `src/pac/planner.py`.

[x] # D. CLI cleanup and new flags
- Why: Simpler UX; remove DB knobs.
- Scope: Drop `init-db`, `commit-batch-size`, `--mode {reconcile,sync-tags,force-rebuild}`.
  - Add `--retag-existing` (default on), `--rename` (default on), `--prune`, `--no-adopt`, `--force-reencode`.
- Accept: Help text reflects new flags; old options removed.
- Refs: `main.py`.

[x] # E. GUI: plan categories and execution
- Why: Expose new planner outcomes and progress.
- Scope: Show counts by action; support pause/cancel; apply rename/retag/prune per flags.
- Accept: Smooth progress; responsive UI; summary matches CLI.
- Refs: `app/gui/main.py`.

[x] # F. Adopt policy (default) and retag
- Why: Keep prior outputs; add PAC_* when missing.
- Scope: If output exists at expected relpath but lacks PAC_*, treat as up-to-date and retag to add PAC_* unless `--no-adopt`.
- Accept: Legacy outputs retained and annotated; strict mode re-encodes.
- Refs: `src/pac/metadata.py`, `src/pac/planner.py`.

[x] # G. Orphan prune (optional)
- Why: Clean destination of files with no source counterpart.
- Scope: Plan orphans; delete only with `--prune` (confirm in GUI/CLI).
- Accept: Dry-run shows orphans; deletes honored only when requested.
- Refs: `src/pac/planner.py`, `main.py`.

[x] # H. Perf polish for scans
- Why: Large libraries; fast re-scans.
- Scope: Parallel tag reads; memory-bounded iteration; efficient I/O.
- Accept: Scan scales to 100k+ files with stable memory.
- Refs: `src/pac/dest_index.py`, `src/pac/scanner.py`.

[x] # I. Docs update (Quickstart/Design/SRS)
- Why: Reflect DB-less pivot and flags.
- Scope: Update Design.md, SRS.md, README.md; describe PAC_*; rename/prune behavior.
- Accept: Docs match code.
- Refs: `docs/`, `README.md`.

[x] # 1. Harden encoder invocations: explicit stream mapping, faststart, decode intent
- Why: Prevent accidental multi-stream issues; improve player compatibility; make decode predictable.
- Scope:
  - Add -map 0:a:0 to all ffmpeg commands (libfdk path and decode-to-WAV).
  - Add -movflags +use_metadata_tags+faststart for MP4 output.
  - Ensure -vn -sn -dn present on decode; keep -threads 1 explicit.
  - Expose pcm_codec (pcm_s24le | pcm_f32le | pcm_s16le) via settings and CLI `--pcm-codec`.
- Accept: Encodes succeed with first audio stream only; MP4 opens quickly; commands logged include these flags.
- Refs: src/pac/encoder.py, src/pac/config.py.

[x] # 2. Bounded concurrency for large libraries
- Why: Avoid creating O(N) futures/memory/FD pressure on big runs.
- Scope: Submit up to 2×workers tasks; enqueue next as one finishes (producer-consumer), or implement a bounded queue inside WorkerPool.
- Accept: Peak futures ≈ O(workers). Memory/FD footprint stays stable on 100k-file catalog.
- Refs: main.py (cmd_convert_dir), src/pac/scheduler.py.

[x] # 3. Strengthen collision resolution and case-insensitive safety
- Why: Current resolve_collisions can be O(n²) and doesn’t guard against case-insensitive destinations.
- Scope: Maintain taken and planned_taken sets; compare with a normalized lowercase key. Keep deterministic ordering. Optimize membership checks.
- Accept: Resolves N=100k planned outputs within seconds; no collisions on case-insensitive volumes (FAT/exFAT) after copy.
- Refs: src/pac/paths.py.

[ ] # 4. Make metadata copy and verification first-class outcomes
- Why: FR‑15; copy failures should be observable; strict policy should be coherent.
- Scope:
  - Emit structured tags events: action="tags", status=ok|warn|error, fields: file, rel_path, reason.
  - If copy_tags_flac_to_mp4 raises and verify_strict is enabled, mark file as failed.
  - Expand verify normalization (Unicode NFC, whitespace) and include composer/compilation checks.
- Accept: JSON log lines contain tags events; strict mode fails files with copy or verify errors; warnings for benign mismatches.
- Refs: main.py (_encode_one_selected), src/pac/metadata.py.

[x] # 5. Record last_converted_at and richer per-run stats (DEPRECATED – DB removed)
- Replaced by stateless summaries; keep structured per-run JSON only.
- Refs: remove `src/pac/db.py` usage.

[ ] # 6. Consistent structured log schema + rotation
- Why: Easier downstream parsing and GUI consumption; avoid unbounded log growth.
- Scope:
  - Standardize fields: ts, action, file, rel_path, status, elapsed_ms, bytes_out, encoder, quality, run_id.
  - Add rotation/retention options to configure_logging (size or time-based).
- Accept: All per-file events use the schema; JSON logs rotate at configured size/time; GUI respects same rotation policy when file sink used.
- Refs: main.py (configure_logging, emit sites), app/gui/main.py.

- [ ] # 7. Duration in scan (optional)
- Why: Reporting and bitrate QA (SRS §7, Tasks 6).
- Scope: Add --scan-duration to compute duration_ms via ffprobe or mutagen; store in DB and summary; expose in JSON logs for each file (optional).
- Accept: duration_ms present when enabled; appears in summary JSON; negligible overhead when disabled.
- Refs: src/pac/scanner.py, src/pac/db.py, main.py.

[ ] # 8. CLI progress UI (rich/tqdm)
- Why: Long-run UX (Tasks 7).
- Scope: Show overall progress, converted/failed counts, ETA; auto-enable on TTY; fallback to logs on non‑TTY.
- Accept: Smooth progress; toggled by --progress/--no-progress; compatible with verbose logs.
- Refs: main.py, pyproject.toml.

[x] # 9. GUI: progress, cancel/pause, encoder-aware hints
- Why: FR‑9; current GUI can run plan/convert but lacks cancel/pause and detailed progress.
- Scope:
  - Add counts and ETA labels; per-file table later.
  - Implement Cancel via threading.Event checked between jobs; Pause via Semaphore gating WorkerPool dispatch.
  - Ensure log initialization order so early logs appear in the UI sink; avoid double logger reconfiguration.
  - Persist last used paths and settings via PacSettings.
- Accept: User can cancel/pause/resume; progress updates live; no UI freeze; startup logs visible in GUI.
- Refs: app/gui/main.py, src/pac/scheduler.py, main.py.

[x] # 10. DB migration v3: indexes and integrity (REMOVED)
- DB eliminated in v0.2.

[ ] # 11. Single source of truth for backend selection
- Why: Avoid divergence between single-file and directory code paths.
- Scope: Implement choose_encoder() returning encoder name, versions, and paths. Use in cmd_convert and cmd_convert_dir.
- Accept: Both code paths pick the same backend under same environment; logs show one consistent selection block.
- Refs: main.py, maybe src/pac/ffmpeg_check.py.

[ ] # 12. Config expansion and cleanup
- Why: Align with Design §3.9; remove code smells.
- Scope:
  - Add settings: pcm_codec, faststart, scan_duration, verify_policy (off|warn|strict), progress default, rotation/retention.
  - Clean argparse oddity (p_dir = sub.add_subparser if False …) and unify naming.
  - Ensure --write-config writes all effective settings with comments (optional).
- Accept: Config round-trips to TOML; CLI overrides reflected in write-config; argparse is tidy.
- Refs: src/pac/config.py, main.py.

[ ] # 13. Tests (unit + small integration)
- Why: Reliability (Tasks 9).
- Scope:
  - Unit: read_flac_streaminfo_md5, sanitize_rel_path, resolve_collisions edge cases, planner decisions, db migrations (v1→v2→v3), ffmpeg_check parsing, metadata verify normalization.
  - Integration: 1–2 tiny FLACs via ffmpeg stub or sample; exercise libfdk path if available else skip.
- Accept: uv run pytest passes locally; CI configuration ready.
- Refs: tests/, src/pac/*.

[ ] # 14. Docs update (Quickstart, install guidance, encoder matrix)
- Why: Reflect new behaviors and options (Tasks 10).
- Scope: Document encoder selection, faststart, pcm precision choice, verify policy, progress, log rotation, cancel/pause, case-insensitive destinations, and DB paths. Add troubleshooting for “no encoder” and permission/disk-full errors.
- Accept: README and docs reflect current CLI/GUI; link SRS/Design; examples updated.
- Refs: README.md, docs/.

[ ] # 15. Optional: Output file atomics and fs errors polish
- Why: Better failure messages and cleanup.
- Scope: On rename failures, report errno, include short stderr snippet; retry once for transient errors; ensure temp cleanup on exceptions.
- Accept: Clear error messages; no orphaned .part files after failures.
- Refs: src/pac/encoder.py.

What’s already done from your original list
- Structured logging + JSON run report: Implemented. main.py configures loguru, emits structured events, and writes run summary JSON.
- Persist runs/file_runs in DB (schema v2): Implemented. v2 migration adds CHECK and indexes; runs and file_runs are written.
- Pydantic settings + TOML config: Implemented. PacSettings with env + TOML + CLI overrides; --write-config supported.
- Destination sanitization and collision handling: Implemented. sanitize_rel_path and resolve_collisions exist; needs optimization (Task 3).
- Post-encode tag verification: Implemented with verify-tags and verify-strict; needs stronger copy error handling and normalization (Task 4).
- GUI scaffold: Implemented minimal PySide6 app with Preflight, plan, convert; needs progress/cancel/pause (Task 9).
 - Hardened FFmpeg flags and pcm precision selection complete. CLI exposes `--pcm-codec`; run summaries/logs include selected PCM and mapping/faststart are enforced.

Deprioritized or rolled into others
- CLI progress UI remains important (Task 8), but correctness/perf hardening (Tasks 1–3) should come first on large libraries.

[x] # 16. Mode: Reconcile destination (REMOVED)
- Superseded by stateless planner with PAC_* adoption and rename detection.

[x] # 17. Mode: Metadata sync (REMOVED)
- Superseded by `retag` action in stateless planner.

[ ] # 18. Force re-encode (kept but simplified)
- New flag `--force-reencode` replaces prior mode; no DB updates.
