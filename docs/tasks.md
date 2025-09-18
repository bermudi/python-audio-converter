Here’s a focused code review with concrete issues, fixes, and suggestions. I grouped them by severity and impact.

High-priority blockers (cause runtime errors or broken flows)
- GUI: undefined names and missing imports
  - app/gui/main.py calls configure_logging() but never imports/defines it. Either:
    - import it from your CLI main module (from main import configure_logging), or
    - define a small console logger in GUI (or reuse setup_logger_for_gui only and drop configure_logging call).
  - ConvertWorker uses cmd_convert_dir but the GUI never imports it.
  - GUI references EXIT_OK, EXIT_WITH_FILE_ERRORS, EXIT_PREFLIGHT_FAILED but doesn’t import/define them.
  - Minimal quick fix:
    - from main import configure_logging, cmd_convert_dir, EXIT_OK, EXIT_WITH_FILE_ERRORS, EXIT_PREFLIGHT_FAILED
    - Longer-term: move those constants and cmd_convert_dir into pac (see “Architecture” below).

- pac.convert_dir is a placeholder
  - src/pac/convert_dir.py returns 0, {}. pac.library_runner imports cmd_convert_dir from here for mirror operations; the GUI ConvertWorker should call the real one too. This must be the full implementation (currently in main.py). Move the real cmd_convert_dir from main.py to src/pac/convert_dir.py and have CLI/GUI both import it from there.

- Library runner: undefined variables (crashes on run, not on dry-run)
  - In src/pac/library_runner.py, cmd_manage_library refers to analysis_pool, encode_pool, art_pool, stop_event, pause_event but never defines them.
  - Fix: instantiate WorkerPool for each phase and add stop_event/pause_event args to cmd_manage_library, then pass them from GUI LibraryWorker:
    - analysis_pool = WorkerPool(cfg.flac_analysis_workers or (cfg.workers or 4))
    - encode_pool = WorkerPool(cfg.flac_workers or (cfg.workers or 4))
    - art_pool = WorkerPool(cfg.flac_art_workers or min((cfg.workers or 4), 4))
    - Add stop_event/pause_event to cmd_manage_library signature and wire through to the _execute_* helpers.

- Planner: library artwork actions missing (tests fail)
  - src/pac/library_planner.py computes art_needed but never appends an extract_art action.
  - Add plan.append(LibraryPlanItem(action="extract_art", ...)) when art_needed is True.

- Tests: dry-run summary mismatch (tests fail)
  - tests/test_library.py expects "planned" in summary for dry-run. cmd_manage_library returns early with {"scanned": 0} when no FLACs are found; it should also include "planned".
  - Fix: on the early “no files” path, return 0, {"scanned": 0, "planned": 0}.

- Main convert-dir: encodes twice + crashes when sync_tags planned
  - Duplicate encode loop: cmd_convert_dir iterates over to_convert twice (copy/paste bug). This re-encodes every file twice.
  - Sync tags counter vs list: you define to_sync_tags twice (list then int). Later you iterate for pi in to_sync_tags after you’ve set it to 0; that will crash.
  - Fix:
    - Keep a single encode loop and collect successful_encodes as list of (pi, elapsed_s).
    - Use distinct names, e.g. to_sync_items = [pi for ...] and synced_tags_count = 0. Iterate over to_sync_items and increment synced_tags_count.

- f-string syntax error (would break import of main.py if it’s ever imported)
  - In db.add_observation you have f'{"elapsed_ms": {int(elapsed_s*1000)}}'. This f-string is invalid.
  - Fix: f'{{"elapsed_ms": {int(elapsed_s*1000)}}}' (note the doubled braces), or better, json.dumps({"elapsed_ms": int(elapsed_s*1000)}).

- Bad relative import
  - src/pac/flac_tools.py > extract_art uses from ..metadata import _first_front_cover (two dots). This is inside the pac package, so it should be from .metadata import _first_front_cover.

Correctness, robustness, and DB API issues
- DB upsert_many_outputs signature/shape is inconsistent
  - The type hint says it takes 10-tuple; the SQL has 11 columns; the method recomputes last_seen_ts and last_seen_had_pac_tags and ignores a passed-in “had” flag from dest_index. Meanwhile, main’s upserts pass 9 items; dest_index passes 10 (with a wasted last flag).
  - Recommendation: normalize one shape:
    - inputs: (md5, dest_rel, container, encoder, quality, pac_version, seen_ts, size, mtime_ns, had_pac_tags)
    - inside: set first_seen_ts=seen_ts when new, last_seen_ts=seen_ts always, and use had_pac_tags directly.
  - Update both call sites (dest_index and main) to pass that shape, and update SQL/placeholders to match.

- Logging size variable ‘sz’ uses locals() guard
  - Define sz = None before try, then set sz when stat() succeeds. Simpler and clearer than checking 'sz' in locals().

- CLI syntax oddity
  - p_dir = sub.add_subparser if False else sub.add_parser("convert-dir", ...) works but is confusing. Replace with straightforward sub.add_parser("convert-dir", ...).

- GUI config type mismatch (minor)
  - In GUI, overrides set flac_art_root to Path. PacSettings defines it as str. Pydantic will coerce, but to be explicit, convert to str().

- Mirror step is a stub
  - In library_runner mirror phase, the code logs “pending_implementation.” Since pac.convert_dir is supposed to be the shared function, once it’s moved, call it for mirror_out (filtered to clean sources if you want).
  - For GUI mirror integration, reflect codec from cfg.lossy_mirror_codec and pass through cover_art_* options and verify options (or defaults).

- Spectrograms feature is surfaced in GUI but not implemented
  - GUI has “Generate spectrograms” toggle and “Spectrogram Links” list. There is no implementation in library_planner/runner. Either remove from UI for now or add a no-op summary key to avoid confusing users.

- Packaging and entry-point robustness
  - pac-gui script points to app.gui.main:main. That module currently references configure_logging that lives in the project root main.py, not in the package. After packaging, root-level modules may not be importable. Avoid cross-referencing root main from GUI.
  - Prefer: move configure_logging to pac.logging (new file), and have both CLI and GUI import from there.

Quality-of-life and UX
- Preflight in GUI
  - Good overall. Consider showing chosen encoder based on codec selection, e.g. “AAC -> libfdk_aac/qaac/fdkaac” vs “Opus -> libopus” and path to binary (you already do this in CLI; mirror that in GUI).

- Cover art
  - You already have cover_art_resize and max size; good. Consider warning in logs when image is resized (debug-level is fine).

- Thread counts
  - WorkerPool sizing uses (cfg.workers or os.cpu_count()). For decode->encode pipelines, you might cap to CPU cores to avoid oversubscription (which you roughly do). Optionally, derive for decode stages vs encode stages differently (future improvement).

Minimal patches to unblock you
- In GUI (app/gui/main.py) add imports or switch to pac.*
  - Option A (quick): import from main (works only in dev):
    - from main import configure_logging, cmd_convert_dir, EXIT_OK, EXIT_PREFLIGHT_FAILED, EXIT_WITH_FILE_ERRORS
  - Option B (better): after moving cmd_convert_dir/constants to pac, import from there:
    - from pac.convert_dir import cmd_convert_dir
    - from pac.constants import EXIT_OK, EXIT_PREFLIGHT_FAILED, EXIT_WITH_FILE_ERRORS
    - from pac.logging import configure_logging

- In src/pac/convert_dir.py replace placeholder with the full implementation from main.py.

- In main.py fix encoding loop + sync tags counter
  - Remove the first duplicate loop and use a single loop that appends (pi, elapsed_s).
  - Use to_sync_items vs synced_tags_count.

- In src/pac/flac_tools.py change the import in extract_art:
  - from .metadata import _first_front_cover

- In src/pac/library_planner.py add extract_art plan:
  - if art_needed: plan.append(LibraryPlanItem("extract_art", "export front cover", src_path, rel_path, md5, {...}))

- In src/pac/library_runner.py
  - Create the worker pools before phases.
  - Add stop_event and pause_event to cmd_manage_library signature and use them when iterating pool.imap_unordered_bounded.
  - Ensure dry_run summary includes “planned” even when scanned is 0.

- In main.py fix the f-string for JSON details:
  - details = json.dumps({"elapsed_ms": int(elapsed_s*1000)})
  - db.add_observation(..., details)

- In pac/db.py normalize upsert_many_outputs to one clear tuple shape and update dest_index/main callers accordingly.

Suggested follow-up tests
- test_convert_dir_sync_tags_and_no_duplicates
  - Create plan with one sync_tags item and one convert item; assert:
    - it does not attempt to iterate an int
    - encode called exactly once per file
    - sync-tags counter increments and logged OK
- test_library_planner_extract_art
  - With mock FLAC having cover art, assert that extract_art actions are produced.
- test_library_runner_dry_run_summary
  - Ensure summary contains scanned and planned keys when there are 0 and >0 files.
- test_flac_tools_import
  - Import extract_art to catch wrong relative import early.

Architecture refactor (medium-term)
- Centralize shared constants and logging/config
  - Create pac/constants.py for EXIT_OK/… and any shared string literals.
  - Create pac/logging.py with configure_logging used by both CLI and GUI.
- Single source of truth for cmd_convert_dir
  - Keep only in pac.convert_dir and import it from CLI and GUI.
- Keep CLI main.py light
  - Only parse args and dispatch into pac.* modules.

Quick checklist you might have missed
- Duplicate encode loop in main.py (major).
- Drop-in placeholder for pac.convert_dir (major, breaks library mirror and GUI integration).
- Undefined pools/stop/pause in library_runner (major).
- extract_art import path is wrong (major).
- Missing extract_art plan items (tests will fail).
- GUI undefined names/imports (major).
- f-string JSON details bug (minor but real).
- DB tuple shape mismatch (clean this up to avoid future confusion).
- Dry-run summary should always include “planned”.

If you want, I can draft the exact replacement code for the convert-dir function (moving it to src/pac/convert_dir.py) and a minimal patch for the GUI imports and library runner pools.