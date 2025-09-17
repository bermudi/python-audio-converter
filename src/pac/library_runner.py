"""Orchestration for FLAC library maintenance."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import time
import threading

from loguru import logger

from .config import PacSettings
from .db import PacDB
from .scheduler import WorkerPool
from .library_planner import plan_library_actions, LibraryPlanItem
from .flac_tools import flac_test, recompress_flac, resample_to_cd_flac, extract_art, generate_spectrogram
from .scanner import scan_flac_files
from .convert_dir import cmd_convert_dir  # Import the existing convert-dir function


def cmd_manage_library(
    cfg: PacSettings,
    root: str,
    *,
    mirror_out: Optional[str] = None,
    dry_run: bool = False,
    **kwargs
) -> Tuple[int, Dict[str, Any]]:
    """Manage FLAC library: maintenance + optional mirror update."""
    root_path = Path(root).resolve()
    if not root_path.exists():
        logger.error(f"Root directory does not exist: {root_path}")
        return 1, {}

    # DB init
    db = None
    if cfg.db_enable:
        db_path = Path(cfg.db_path).expanduser()
        db = PacDB(db_path)

    now_ts = int(time.time())

    # Scan FLAC files
    logger.info(f"Scanning FLAC library: {root_path}")
    sources = scan_flac_files(
        root_path,
        compute_flac_md5=True,
        max_workers=cfg.workers or 4,
        db=db,
        now_ts=now_ts
    )

    if not sources:
        logger.info("No FLAC files found")
        return 0, {"scanned": 0}

    # Plan actions
    logger.info(f"Planning actions for {len(sources)} files")
    plan = plan_library_actions(sources, cfg, db, now_ts)

    # Group by action type
    actions_by_type = {}
    for item in plan:
        actions_by_type.setdefault(item.action, []).append(item)

    # Summary
    summary = {
        "scanned": len(sources),
        "planned": len(plan),
        "test_integrity": len(actions_by_type.get("test_integrity", [])),
        "resample_to_cd": len(actions_by_type.get("resample_to_cd", [])),
        "recompress": len(actions_by_type.get("recompress", [])),
        "extract_art": len(actions_by_type.get("extract_art", [])),
        "hold": len(actions_by_type.get("hold", [])),
    }

    if dry_run:
        logger.info("Dry run - showing plan:")
        for action, items in actions_by_type.items():
            logger.info(f"  {action}: {len(items)} files")
        return 0, summary

    # Execute phases
    logger.info("Executing FLAC library maintenance...")
    timing = {}

    # Phase 1: Integrity tests
    if "test_integrity" in actions_by_type:
        logger.info("Phase 1: Integrity checks")
        start_time = time.time()
        integrity_results = _execute_integrity_phase(actions_by_type["test_integrity"], analysis_pool, db, now_ts, cfg, stop_event, pause_event)
        timing["integrity"] = time.time() - start_time
        # Update summary with integrity results
        summary["integrity_ok"] = sum(1 for r in integrity_results if r[1])
        summary["integrity_failed"] = sum(1 for r in integrity_results if not r[1])

    # Phase 3: Resampling
    if "resample_to_cd" in actions_by_type:
        logger.info("Phase 3: Resampling to CD quality")
        start_time = time.time()
        _execute_resample_phase(actions_by_type["resample_to_cd"], encode_pool, db, now_ts, cfg, stop_event, pause_event)
        timing["resample"] = time.time() - start_time

    # Phase 4: Recompression
    if "recompress" in actions_by_type:
        logger.info("Phase 4: Recompression")
        start_time = time.time()
        _execute_recompress_phase(actions_by_type["recompress"], encode_pool, db, now_ts, cfg, stop_event, pause_event)
        timing["recompress"] = time.time() - start_time

    # Phase 5: Artwork extraction
    if "extract_art" in actions_by_type:
        logger.info("Phase 5: Artwork extraction")
        start_time = time.time()
        _execute_art_phase(actions_by_type["extract_art"], art_pool, db, now_ts, cfg, stop_event, pause_event)
        timing["artwork"] = time.time() - start_time

    # Add timing to summary
    summary["timing_s"] = timing
    summary["total_time_s"] = sum(timing.values())

    # Optional mirror update
    if mirror_out and cfg.lossy_mirror_auto:
        logger.info(f"Phase 6: Updating lossy mirror to {mirror_out}")
        start_time = time.time()

        # Filter sources to only include clean (non-held) files
        clean_sources = []
        held_md5s = set()

        # Collect MD5s of held files
        for item in plan:
            if item.action == "hold":
                held_md5s.add(item.flac_md5)

        # Filter sources to only include clean files
        for src in sources:
            if src.flac_md5 not in held_md5s:
                clean_sources.append(src)

        if clean_sources:
            logger.info(f"Found {len(clean_sources)} clean sources for mirror update")
            # For now, implement a simple approach by calling the main convert-dir logic
            # This is a placeholder - the full implementation would require extracting
            # the convert-dir logic from main.py into a reusable function
            logger.info("Mirror update: Would process clean sources (implementation pending)")
            timing["mirror"] = time.time() - start_time
            summary["mirror"] = {"clean_sources": len(clean_sources), "status": "pending_implementation"}
        else:
            logger.info("No clean sources found for mirror update")
            timing["mirror"] = time.time() - start_time
            summary["mirror"] = {"clean_sources": 0, "status": "no_clean_sources"}

    logger.info("FLAC library maintenance complete")
    return 0, summary


def _execute_integrity_phase(items: List[LibraryPlanItem], pool: WorkerPool, db: PacDB, now_ts: int, cfg: PacSettings, stop_event, pause_event) -> List[Tuple[LibraryPlanItem, bool]]:
    """Execute integrity testing phase with parallel execution."""
    results = []
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window

    def task(item: LibraryPlanItem):
        success, error_msg = flac_test(item.src_path)
        if db:
            db.begin()
            db.conn.execute("""
                INSERT OR REPLACE INTO flac_checks
                (md5, last_test_ts, test_ok, test_msg, streaminfo_md5, bit_depth, sample_rate, channels)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.flac_md5,
                now_ts,
                1 if success else 0,
                error_msg,
                item.params.get("streaminfo", {}).get("md5"),
                item.params.get("streaminfo", {}).get("bit_depth"),
                item.params.get("streaminfo", {}).get("sample_rate"),
                item.params.get("streaminfo", {}).get("channels"),
            ))
            db.commit()
        return item, success

    for item, (result_item, success) in pool.imap_unordered_bounded(
        task, items, max_pending, stop_event=stop_event, pause_event=pause_event
    ):
        results.append((result_item, success))
        logger.info(f"Integrity test {'OK' if success else 'FAILED'}: {item.rel_path}")

        # Early stop on error if configured
        if not success and cfg.flac_stop_on in ["error", "suspect"]:
            logger.warning(f"Stopping on integrity failure for {item.rel_path}")
            break

    return results




def _execute_resample_phase(items: List[LibraryPlanItem], pool: WorkerPool, db: PacDB, now_ts: int, cfg: PacSettings, stop_event, pause_event):
    """Execute resampling phase with parallel execution."""
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window

    def task(item: LibraryPlanItem):
        rc = resample_to_cd_flac(item.src_path, cfg.flac_target_compression, verify=True)
        return item, rc

    for item, (result_item, rc) in pool.imap_unordered_bounded(
        task, items, max_pending, stop_event=stop_event, pause_event=pause_event
    ):
        logger.info(f"Resample {'OK' if rc == 0 else 'FAILED'}: {item.rel_path}")


def _execute_recompress_phase(items: List[LibraryPlanItem], pool: WorkerPool, db: PacDB, now_ts: int, cfg: PacSettings, stop_event, pause_event):
    """Execute recompression phase with parallel execution."""
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window

    def task(item: LibraryPlanItem):
        rc = recompress_flac(item.src_path, cfg.flac_target_compression, verify=True)
        if rc == 0:
            # Update compression tag
            from .flac_tools import set_flac_tag
            tag_value = f"flac 1.4.3; level={cfg.flac_target_compression}; verify=1; ts={now_ts}"
            set_flac_tag(item.src_path, "COMPRESSION", tag_value)
            if db:
                db.begin()
                db.conn.execute("""
                    INSERT OR REPLACE INTO flac_policy
                    (md5, compression_level, last_compress_ts, compression_tag)
                    VALUES (?, ?, ?, ?)
                """, (item.flac_md5, cfg.flac_target_compression, now_ts, tag_value))
                db.commit()
        return item, rc

    for item, (result_item, rc) in pool.imap_unordered_bounded(
        task, items, max_pending, stop_event=stop_event, pause_event=pause_event
    ):
        logger.info(f"Recompress {'OK' if rc == 0 else 'FAILED'}: {item.rel_path}")


def _execute_art_phase(items: List[LibraryPlanItem], pool: WorkerPool, db: PacDB, now_ts: int, cfg: PacSettings, stop_event, pause_event):
    """Execute artwork extraction phase with parallel execution."""
    art_root = Path(cfg.flac_art_root).expanduser()
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window

    def task(item: LibraryPlanItem):
        art_path = extract_art(item.src_path, art_root, cfg.flac_art_pattern)
        if art_path and db:
            db.begin()
            db.conn.execute("""
                INSERT OR REPLACE INTO art_exports
                (md5, path, last_export_ts, mime, size)
                VALUES (?, ?, ?, ?, ?)
            """, (item.flac_md5, str(art_path), now_ts, "image/jpeg", art_path.stat().st_size if art_path.exists() else 0))
            db.commit()
        return item, art_path

    for item, (result_item, art_path) in pool.imap_unordered_bounded(
        task, items, max_pending, stop_event=stop_event, pause_event=pause_event
    ):
        logger.info(f"Artwork {'OK' if art_path else 'SKIP'}: {item.rel_path}")


def _was_held(md5: str, plan: List[LibraryPlanItem]) -> bool:
    """Check if a file was held during planning/execution."""
    for item in plan:
        if item.flac_md5 == md5 and item.action == "hold":
            return True
    return False