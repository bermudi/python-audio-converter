Below is a practical, staged plan to evolve PAC into a dual‑library manager that maintains a “master” FLAC library and keeps a lossy mirror (Opus by default, AAC optional). It builds on the existing architecture (scanner → index → planner → scheduler) and adds a “FLAC Library” pipeline with strong verification, compression policy, authenticity analysis, artwork extraction, and parallel controls. It also includes how to track runs and issues.

High‑level goals
- Keep all current features (AAC/Opus mirror) and add a first‑class FLAC Library manager.
- Make FLAC maintenance safe, deterministic, and auditable:
  - Re‑encode down to CD quality (16‑bit/44.1 kHz, 2ch) when source is higher.
  - Enforce compression level with verification and a COMPRESSION tag policy.
  - Integrity checks: MD5 (STREAMINFO) consistency and full decode test.
  - Authenticity analysis via auCDtect and Lossless Audio Checker (LAC), with optional spectrograms for suspect results.
  - Artwork extraction to structured folders.
  - Parallel execution across phases with smart bounds.
  - Early‑stop when issues are detected to prevent cascading changes.
- Orchestrate both flows in one “manage” command: stabilize FLAC library, then update the lossy mirror using the existing conversion pipeline, gating on “clean” sources only.

What we will add (by component)
1) New modules
- pac.flac_tools
  - probe_flac(): detect flac/metaflac versions and capabilities.
  - flac_stream_info(path): sr, bit depth, channels, duration, md5, tags (via mutagen or metaflac).
  - needs_cd_downmix(info): returns True if bitdepth > 16 or samplerate != 44100 or channels != 2 (configurable).
  - recompress_flac(src, level, verify=True): in‑place (atomic tmp + rename) or rewrite to new path; writes COMPRESSION tag; uses flac -V -{level}; skips if tag matches.
  - resample_to_cd_flac(src, level, verify=True): decode/resample/dither → flac -V -{level}:
    - ffmpeg pipeline example: ffmpeg -nostdin -hide_banner -loglevel error -i src -ac 2 -ar 44100 -sample_fmt s16 -f wav - | flac -V -{level} -o tmp -
    - Optionally use sox (soxr) for high‑quality resampling + dither.
  - flac_test(src): run flac -t; returns pass/fail + stderr.
  - flac_md5_consistency(src): compare STREAMINFO MD5 vs decode (flac -t covers this; we still record STREAMINFO MD5 via existing read_flac_streaminfo_md5()).
  - set_flac_tag(src, key, value) and get_flac_tag(src, key): manage “COMPRESSION” and other policy tags via mutagen.
  - extract_art(src, out_root, pattern): write front cover to structured path (Artist/Album/front.jpg or configurable).
  - generate_spectrogram(src, png_path): ffmpeg -i input -lavfi showspectrumpic=s=1280x720:legend=disabled:color=rainbow out.png (optional).

- pac.auth_tools
  - probe_auth_tools(): locate aucdtect, LAC.
  - run_aucdtect(src): parse score/classification; skip for >16‑bit and when configured/tagged as “lossy mastered”.
  - run_lac(src): parse CLI output or JSON if available; same skipping rules.
  - classify_authenticity(aucdtect, lac): combine into one status: ok/suspect/error with rationale.

- pac.library_planner
  - Produces actions for FLAC maintenance:
    - test_integrity, resample_to_cd, recompress, extract_art, analyze_auth, skip, hold.
  - Inputs: scan of FLAC sources, config, DB, tool availability.
  - Rules:
    - Early‑stop: On first “issue” (error or suspect per config) → emit hold and do not queue further actions for that file.
    - Recompress skip when COMPRESSION tag equals target and file already verified recently (DB cache).
    - Resample_to_cd only when >CD specs.
    - Extract art when not present/changed in art store.
    - Analyze auth only if eligible (<=16‑bit; not lossy‑mastered when that option is on).

- pac.library_runner
  - Orchestrates execution by phase with WorkerPool(s).
  - Parallel controls per phase: analysis_workers, encode_workers, art_workers.
  - Emits structured events and updates DB.
  - Optionally calls existing cmd_convert_dir at the end to update the lossy mirror, limited to “clean” sources.

2) DB changes (sqlite)
- New tables:
  - flac_checks(md5 PRIMARY KEY, last_test_ts INT, test_ok INT, test_msg TEXT, streaminfo_md5 TEXT, bit_depth INT, sample_rate INT, channels INT)
  - flac_policy(md5 PRIMARY KEY, compression_level INT, last_compress_ts INT, compression_tag TEXT)
  - authenticity(md5 PRIMARY KEY, aucdtect_score REAL, aucdtect_class TEXT, lac_result TEXT, analyzed_ts INT, status TEXT CHECK(status IN ('ok','suspect','error')), spectrogram_path TEXT)
  - art_exports(md5 PRIMARY KEY, path TEXT, last_export_ts INT, mime TEXT, size INT)
- Keep using observations for append‑only history: events like flac_test_ok, flac_test_err, recompress_ok, recompress_skip, resample_ok, auth_ok, auth_suspect, auth_skip, art_export_ok. This gives you a lightweight audit log.

3) CLI
- New top‑level command: pac library
  - Inputs
    - --root: FLAC library root
    - --target-compression 8 (or 12 if you prefer), default from config
    - --resample-to-cd on|off (default on)
    - --auth on|off (default on)
    - --auth-skip-highbit on|off (default on)
    - --auth-skip-lossy-mastered on|off (default on)
    - --spectrogram on|off (default off)
    - --art-root path, --art-pattern "{artist}/{album}/front.jpg"
    - --flac-workers N, --analysis-workers N, --art-workers N
    - --stop-on "error|suspect|never" (default error; “suspect” means stop on either)
    - --dry-run: plan only
    - --continue-on-issues: override stop rule
    - --mirror-out path (optional) to run convert-dir afterward for the lossy library
    - --mirror-codec opus|aac; reuse existing quality settings
  - Outputs
    - Exit codes like existing ones
    - Summary JSON (same sink as convert-dir) with new sections counts.library and details by phase
    - Optional “hold list” file with the md5/paths that need human attention

- Update GUI
  - Add a “FLAC Library” tab: Preflight tools, settings (checkboxes), Plan (dry-run), Run, counters per phase, “Issues found” panel, and artifact links (spectrograms).

4) Config (pydantic)
Extend PacSettings with:
- flac_target_compression: int = 8
- flac_resample_to_cd: bool = True
- flac_stop_on: Literal["never","suspect","error"] = "error"
- flac_auth_enabled: bool = True
- flac_auth_skip_highbit: bool = True
- flac_auth_skip_lossy_mastered: bool = True
- flac_art_root: str = "~/Music/_art"
- flac_art_pattern: str = "{albumartist}/{album}/front.jpg"
- flac_workers: Optional[int] = None
- flac_analysis_workers: Optional[int] = None
- flac_art_workers: Optional[int] = None
- spectrogram_enabled: bool = False
- spectrogram_resolution: str = "1280x720"
- spectrogram_color: str = "rainbow"
- lossy_mirror_auto: bool = False
- lossy_mirror_codec: Literal["opus","aac"] = "opus"

Add CLI → settings overrides (like existing cli_overrides_from_args).

5) Planning rules (FLAC)
For each SourceFile (already provided by scanner):

- Phase 0: Preflight
  - Detect flac, metaflac, ffmpeg/sox, auCDtect, LAC availability; record versions.

- Phase 1: Integrity and eligibility
  - flac_test (flac -t) → if fail: log error, mark hold, STOP further operations for this file.
  - Record STREAMINFO MD5 (already in scanner); compare if needed.

- Phase 2: Authenticity (optional; respects skip rules)
  - If bit depth > 16 and flac_auth_skip_highbit: skip auth.
  - If COMPRESSION/RELEASE/SOURCE tags indicate “lossy mastered” and skip configured: skip auth.
  - Else run auCDtect and LAC in parallel workers; combine results:
    - If either flags “likely lossy/transcoded” → status=suspect; record; optionally make spectrogram; if stop_on ∈ {"suspect","error"} → hold STOP.
    - Else status=ok; continue.

- Phase 3: Resample to CD if needed
  - if needs_cd_downmix(info): run resample_to_cd_flac (ffmpeg/sox → flac -V -{level}).
  - Update COMPRESSION tag and DB.

- Phase 4: Recompress policy
  - Read COMPRESSION tag:
    - If equals target level and file was verified recently → skip.
    - Else recompress with flac -V -{level}; set COMPRESSION tag = f"flac {version}; level={level}; verify=1; ts={now}".
  - Early exit on encode failure.

- Phase 5: Artwork export
  - If cover present and exported copy missing/older (compare mtime/size or no DB row) → extract to flac_art_root/art_pattern.
  - Write DB entry art_exports.

- Phase 6 (optional): Mirror update
  - If lossy_mirror_auto or CLI provided mirror-out → call cmd_convert_dir with:
    - Only include sources whose file was not held in phases above.
    - You can pass a predicate set of allowed md5s to the planner (small change) or filter inputs before invoking convert-dir.

Early‑stop logic
- Maintain per‑file “issues” list with severity.
- At each phase end: if issues and severity ≥ stop_on threshold → enqueue hold action and skip remaining phases for that file.
- Observations log one event per decision, so audits show why a file was held.

6) Concurrency model
- Reuse WorkerPool; define separate pools per phase to avoid head‑of‑line blocking:
  - analysis_pool = WorkerPool(flac_analysis_workers or CPU)
  - encode_pool = WorkerPool(flac_workers or CPU/2)
  - art_pool = WorkerPool(flac_art_workers or min(CPU, 4))
- Use imap_unordered_bounded for bounded in‑flight tasks per phase (you already have it).
- If in future flac ≥ 1.5.0 gains internal threads, detect via probe_flac() and optionally lower encode_pool size (process concurrency) to avoid oversubscription.
- Continue to support pause/cancel via stop_event/pause_event (already designed in scheduler).

7) Tracking and reporting
- JSON lines log (existing): add action values: flac_test, flac_recompress, flac_resample, flac_auth, art_export with status=ok|skip|warn|error|suspect and structured fields.
- Summary JSON (new sections)
  - library: { scanned, tested_ok, tested_err, resampled, recompressed, recompress_skipped, auth_ok, auth_suspect, auth_skipped, art_exported, held, failed }
  - mirror: reuse existing counts
- DB: write rows into new tables; also append observations for each step.
- Hold list: write markdown/CSV with file, reason, tool outputs, spectrogram link for triage.

Key data structures (sketch)
- pac/library_planner.py
  - @dataclass class LibraryPlanItem:
    - action: Literal["test_integrity","analyze_auth","resample_to_cd","recompress","extract_art","hold","skip"]
    - reason: str
    - src_path: Path
    - rel_path: Path
    - flac_md5: str
    - params: dict
- pac/library_runner.py
  - def cmd_manage_library(cfg: PacSettings, root: str, mirror_out: Optional[str], …) -> tuple[int, dict]:
    - Scan -> Plan (dry-run option)
    - Execute per phase with pools and early-stop gating
    - Optionally run cmd_convert_dir for lossy mirror with filtered sources
    - Write summary JSON and return

CLI examples
- Dry run:
  - pac library --root ~/Music/FLAC --target-compression 8 --auth --spectrogram --dry-run
- Run and mirror:
  - pac library --root ~/Music/FLAC --mirror-out ~/Music/Opus --mirror-codec opus --target-compression 8 --resample-to-cd

Example of COMPRESSION tag management
- On successful (re)encode:
  - COMPRESSION = "flac 1.4.3; level=8; verify=1; date=2025-09-17"
- Skip rule:
  - If COMPRESSION contains level=<target> and last_test_ts within grace (e.g., 90 days), skip recompress.

Spectrogram generation (optional)
- Use ffmpeg: showspectrumpic filter:
  - ffmpeg -nostdin -hide_banner -loglevel error -i input.flac -lavfi "showspectrumpic=s=1280x720:legend=disabled:color=rainbow" out.png
- Store under art root (or a separate “analysis” root), e.g., _analysis/{albumartist}/{album}/{track}.png.

Testing strategy
- Unit tests
  - planner decisions: downsample needed, recompress skip on COMPRESSION tag, early-stop on test error or auth suspect.
  - art extraction using tiny in‑repo FLAC fixtures or mocked metadata.
  - auth skip logic for >16‑bit and lossy‑mastered tags.
- Integration tests (behind markers)
  - Requires local flac/ffmpeg; run on CI with containers.
  - End‑to‑end: given small set of fixtures, generate plan, run, verify DB and files.
- Property tests
  - sanitize + art paths mapping stable and reversible for typical unicode edge cases.
- Performance
  - Scanner + planner over 10k fake entries; ensure bounded memory; windowed scheduling verified.

Milestones (with acceptance criteria)
- M0: Plumbing and preflight
  - Add pac.flac_tools, probe_flac; add new settings; pass CI.
- M1: Integrity checks
  - flac_test integrated; DB flac_checks; early-stop on error; summary counts.
- M2: Recompress policy
  - COMPRESSION tag read/write; skip and recompress behavior; -V verification; atomic writes; tests.
- M3: Resample to CD
  - Resample pipeline (ffmpeg|sox → flac -V); only for >CD; tests with synthetic hi‑res WAV→FLAC.
- M4: Artwork extraction
  - Export into structured folders; DB art_exports; tests.
- M5: Authenticity analysis
  - auCDtect + LAC integration with skip rules; spectrogram optional; early-stop on suspect; tests behind markers.
- M6: Parallelism & orchestration
  - Separate WorkerPools per phase; pause/cancel; bounded windows; summary timing; tests.
- M7: Mirror orchestration
  - pac library optionally calls convert-dir for “clean” sources only; end‑to‑end test.
- M8: GUI
  - New tab with plan/run; counters and issues panel; spectrogram links.
- M9: Docs and polish
  - User guide; migration notes; troubleshooting.

Tracking the work
- GitHub Projects board with Epics aligned to milestones above.
- Issues per task with clear DoD; link PRs; labels: area:flac, area:auth, area:art, perf, db.
- Observability checklist per PR:
  - Adds/updates JSON events
  - DB migrations handled
  - Summary JSON updated
  - Unit/integration tests added
  - Docs updated

Run/summary JSON (example)
{
  "mode": "library",
  "root": "/home/user/Music/FLAC",
  "tools": {"flac": "1.4.3", "ffmpeg": "6.1", "aucdtect": "0.8.2", "lac": "1.0"},
  "counts": {
    "scanned": 1250,
    "tested_ok": 1245,
    "tested_err": 5,
    "auth_ok": 1200,
    "auth_suspect": 20,
    "auth_skipped": 30,
    "resampled": 50,
    "recompressed": 400,
    "recompress_skipped": 795,
    "art_exported": 1100,
    "held": 25,
    "failed": 3
  },
  "timing_s": {...},
  "timestamp": 1694912345
}

Key implementation notes and safeguards
- Atomic writes: always write new FLAC to sibling .part file then os.replace.
- Verification: flac -V on every write; abort on non‑zero exit.
- Metadata copy: when resampling, copy all Vorbis comments and pictures (mutagen) or pipe via ffmpeg and then re‑apply tags via mutagen to be safe.
- Early stop: treat “suspect” from auth as configurable stop; never recompress or mirror such files in the same run.
- Eligibility: skip auCDtect on >16‑bit, and optionally on files tagged by patterns (config: auth_skip_tags = ["LOSSYMASTERED", "WEB", ...]).
- Structured art: reuse your existing _first_front_cover() and write bytes to the art path; if image exceeds max, optionally resize (you already have PIL logic).

Small cleanups/opportunities spotted in current codebase (quick wins)
- cmd_convert_dir currently processes to_convert twice (duplicate imap_unordered_bounded loop). Remove the first loop and keep a single pass; also fix successful_encodes type (list of (pi, elapsed_s)).
- dest_index → PacDB.upsert_many_outputs: the tuple lengths/indices don’t match the SQL columns; align the function signature and call site (include both first_seen_ts and last_seen_ts or compute inside).
- Summary keys: “to_sync_tags” vs “synced_tags” naming is inconsistent. Normalize across GUI/CLI/JSON.
- observations details_json values should be valid JSON strings (use json.dumps).

Minimal API sketch
- pac/library_runner.py
  - def cmd_manage_library(cfg: PacSettings, root: str, *, mirror_out: Optional[str] = None, ...) -> tuple[int, dict]
- pac/flac_tools.py
  - def recompress_flac(src: Path, level: int, verify: bool = True) -> int
  - def resample_to_cd_flac(src: Path, level: int, verify: bool = True, tool: Literal["ffmpeg","sox"]="ffmpeg") -> int
  - def flac_test(src: Path) -> tuple[bool, str]
  - def extract_art(src: Path, art_root: Path, pattern: str) -> Optional[Path]
- pac/auth_tools.py
  - def run_aucdtect(src: Path) -> dict
  - def run_lac(src: Path) -> dict
  - def classify_auth(au: dict, lac: dict) -> tuple[str, dict]  # ("ok"|"suspect"|"error", details)

How this fits your current project
- Reuses:
  - scanner (SourceFile), scheduler (WorkerPool), metadata.cover utilities, config/logging/JSON sink, GUI logging and plan display components, DB layer (extend it).
- Adds:
  - A parallel “library” planner/runner pipeline that feeds (optionally) into the existing convert-dir mirror pipeline.
- Keeps consistency:
  - All actions produce structured logs and DB observations so you get uniform run summaries.

If you want, I can draft the exact function signatures (and stub implementations) for pac.flac_tools, pac.auth_tools, pac.library_planner, and pac.library_runner next, and a CLI wiring for pac library that mirrors how convert-dir is implemented.