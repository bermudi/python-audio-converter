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
from .flac_tools import flac_test, recompress_flac, resample_to_cd_flac, extract_art
from .scanner import scan_flac_files
from .convert_dir import cmd_convert_dir  # Import the existing convert-dir function


# Phase names for selective execution
PHASE_SCAN = "scan"
PHASE_INTEGRITY = "integrity"
PHASE_RESAMPLE = "resample"
PHASE_RECOMPRESS = "recompress"
PHASE_ARTWORK = "artwork"
PHASE_ADOPT = "adopt"
PHASE_MIRROR = "mirror"

ALL_PHASES = frozenset({
    PHASE_SCAN, PHASE_INTEGRITY, PHASE_RESAMPLE,
    PHASE_RECOMPRESS, PHASE_ARTWORK, PHASE_ADOPT, PHASE_MIRROR
})


def cmd_manage_library(
    cfg: PacSettings,
    root: str,
    *,
    mirror_out: Optional[str] = None,
    dry_run: bool = False,
    phases: Optional[set] = None,
    stop_event: Optional[threading.Event] = None,
    pause_event: Optional[threading.Event] = None,
    progress_callback: Optional[callable] = None,
    **kwargs
) -> Tuple[int, Dict[str, Any]]:
    """Manage FLAC library: maintenance + optional mirror update.
    
    Args:
        cfg: PAC settings
        root: Root directory of the FLAC library
        mirror_out: Optional output directory for lossy mirror
        dry_run: If True, only plan actions without executing
        phases: Set of phases to run. If None, runs all phases.
                Valid phases: scan, integrity, resample, recompress, artwork, adopt, mirror
        stop_event: Threading event to signal cancellation
        pause_event: Threading event to signal pause/resume
        progress_callback: Optional callback(phase_name, current, total) for progress updates
    """
    # Default to all phases if not specified
    if phases is None:
        phases = ALL_PHASES.copy()
    else:
        # Validate phases
        invalid = set(phases) - ALL_PHASES
        if invalid:
            logger.error(f"Invalid phases: {invalid}. Valid: {ALL_PHASES}")
            return 1, {}
    
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

    # Scan FLAC files (always needed for planning)
    if PHASE_SCAN in phases or any(p in phases for p in [PHASE_INTEGRITY, PHASE_RESAMPLE, PHASE_RECOMPRESS, PHASE_ARTWORK]):
        logger.info(f"Scanning FLAC library: {root_path}")
        if progress_callback:
            progress_callback(PHASE_SCAN, 0, 0)
        sources = scan_flac_files(
            root_path,
            compute_flac_md5=True,
            max_workers=cfg.workers or 4,
            db=db,
            now_ts=now_ts
        )

        if not sources:
            logger.info("No FLAC files found")
            return 0, {"scanned": 0, "planned": 0}
    else:
        sources = []

    # Plan actions
    logger.info(f"Planning actions for {len(sources)} files")
    plan = plan_library_actions(sources, cfg, db, now_ts)

    # Group by action type
    actions_by_type = {}
    for item in plan:
        actions_by_type.setdefault(item.action, []).append(item)

    # Summary
    held_items = actions_by_type.get("hold", [])
    summary = {
        "scanned": len(sources),
        "planned": len(plan),
        "test_integrity": len(actions_by_type.get("test_integrity", [])),
        "resample_to_cd": len(actions_by_type.get("resample_to_cd", [])),
        "recompress": len(actions_by_type.get("recompress", [])),
        "extract_art": len(actions_by_type.get("extract_art", [])),
        "hold": len(held_items),
        "held_files": [{"path": str(item.rel_path), "reason": item.reason} for item in held_items],
    }

    if dry_run:
        logger.info("Dry run - showing plan:")
        for action, items in actions_by_type.items():
            logger.info(f"  {action}: {len(items)} files")
        return 0, summary

    # Create worker pools
    analysis_pool = WorkerPool(cfg.flac_analysis_workers or (cfg.workers or 4))
    encode_pool = WorkerPool(cfg.flac_workers or (cfg.workers or 2))
    art_pool = WorkerPool(cfg.flac_art_workers or min((cfg.workers or 4), 4))

    # Execute phases
    logger.info("Executing FLAC library maintenance...")
    timing = {}

    # Phase 1: Integrity tests
    if PHASE_INTEGRITY in phases and "test_integrity" in actions_by_type:
        logger.info("Phase 1: Integrity checks")
        start_time = time.time()
        items = actions_by_type["test_integrity"]
        if progress_callback:
            progress_callback(PHASE_INTEGRITY, 0, len(items))
        integrity_results = execute_integrity_phase(items, analysis_pool, db, now_ts, cfg, stop_event, pause_event, progress_callback)
        timing["integrity"] = time.time() - start_time
        # Update summary with integrity results
        summary["integrity_ok"] = sum(1 for r in integrity_results if r[1])
        summary["integrity_failed"] = sum(1 for r in integrity_results if not r[1])

    # Phase 2: Resampling
    if PHASE_RESAMPLE in phases and "resample_to_cd" in actions_by_type:
        logger.info("Phase 2: Resampling to CD quality")
        start_time = time.time()
        items = actions_by_type["resample_to_cd"]
        if progress_callback:
            progress_callback(PHASE_RESAMPLE, 0, len(items))
        execute_resample_phase(items, encode_pool, db, now_ts, cfg, stop_event, pause_event, progress_callback)
        timing["resample"] = time.time() - start_time

    # Phase 3: Recompression
    if PHASE_RECOMPRESS in phases and "recompress" in actions_by_type:
        logger.info("Phase 3: Recompression")
        start_time = time.time()
        items = actions_by_type["recompress"]
        if progress_callback:
            progress_callback(PHASE_RECOMPRESS, 0, len(items))
        execute_recompress_phase(items, encode_pool, db, now_ts, cfg, stop_event, pause_event, progress_callback)
        timing["recompress"] = time.time() - start_time

    # Phase 4: Artwork extraction
    if PHASE_ARTWORK in phases and "extract_art" in actions_by_type:
        logger.info("Phase 4: Artwork extraction")
        start_time = time.time()
        items = actions_by_type["extract_art"]
        if progress_callback:
            progress_callback(PHASE_ARTWORK, 0, len(items))
        execute_art_phase(items, art_pool, db, now_ts, cfg, stop_event, pause_event, progress_callback)
        timing["artwork"] = time.time() - start_time

    # Add timing to summary
    summary["timing_s"] = timing
    summary["total_time_s"] = sum(timing.values())

    # Optional mirror update
    if PHASE_MIRROR in phases and mirror_out and cfg.lossy_mirror_auto:
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
            # Create temporary source directory for clean sources using symlinks to avoid copying
            import tempfile
            import shutil
            with tempfile.TemporaryDirectory() as temp_src:
                temp_src_path = Path(temp_src)
                for src_file in clean_sources:
                    rel = src_file.rel_path
                    temp_path = temp_src_path / rel
                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path.symlink_to(src_file.path, target_is_symlink=True)
                # Call cmd_convert_dir with temp_src as source, mirror_out as dest
                mirror_codec = cfg.lossy_mirror_codec
                exit_code, mirror_summary = cmd_convert_dir(
                    cfg,
                    str(temp_src_path),
                    mirror_out,
                    codec=mirror_codec,
                    tvbr=cfg.tvbr if mirror_codec == "aac" else 0,  # default for aac
                    vbr=cfg.vbr if mirror_codec == "aac" else 0,
                    opus_vbr_kbps=cfg.opus_vbr_kbps if mirror_codec == "opus" else 0,
                    workers=cfg.workers,
                    verbose=True,
                    dry_run=False,
                    force_reencode=False,
                    allow_rename=True,
                    retag_existing=True,
                    prune_orphans=False,
                    no_adopt=False,
                    sync_tags=False,
                    log_json_path=None,
                    verify_tags=cfg.verify_tags,
                    verify_strict=cfg.verify_strict,
                    cover_art_resize=cfg.cover_art_resize,
                    cover_art_max_size=cfg.cover_art_max_size,
                    stop_event=stop_event,
                    pause_event=pause_event,
                    interactive=False,
                )
                timing["mirror"] = time.time() - start_time
                summary["mirror"] = {
                    "clean_sources": len(clean_sources),
                    "exit_code": exit_code,
                    "summary": mirror_summary
                }
                if exit_code != 0:
                    logger.warning(f"Mirror update completed with errors (code {exit_code})")
        else:
            logger.info("No clean sources found for mirror update")
            timing["mirror"] = time.time() - start_time
            summary["mirror"] = {"clean_sources": 0, "status": "no_clean_sources"}

    logger.info("FLAC library maintenance complete")
    return 0, summary


def execute_integrity_phase(
    items: List[LibraryPlanItem],
    pool: WorkerPool,
    db: PacDB,
    now_ts: int,
    cfg: PacSettings,
    stop_event=None,
    pause_event=None,
    progress_callback=None
) -> List[Tuple[LibraryPlanItem, bool]]:
    """Execute integrity testing phase with parallel execution.
    
    Can be called independently for granular control.
    """
    results = []
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window
    total = len(items)
    completed = 0

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
        completed += 1
        if progress_callback:
            progress_callback(PHASE_INTEGRITY, completed, total)
        logger.info(f"Integrity test {'OK' if success else 'FAILED'}: {item.rel_path}")

        # Early stop on error if configured
        if not success and cfg.flac_stop_on in ["error", "suspect"]:
            logger.warning(f"Stopping on integrity failure for {item.rel_path}")
            break

    return results




def execute_resample_phase(
    items: List[LibraryPlanItem],
    pool: WorkerPool,
    db: PacDB,
    now_ts: int,
    cfg: PacSettings,
    stop_event=None,
    pause_event=None,
    progress_callback=None
) -> List[Tuple[LibraryPlanItem, int]]:
    """Execute resampling phase with parallel execution.
    
    Can be called independently for granular control.
    """
    results = []
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window
    total = len(items)
    completed = 0

    def task(item: LibraryPlanItem):
        rc = resample_to_cd_flac(item.src_path, cfg.flac_target_compression, verify=True)
        return item, rc

    for item, (result_item, rc) in pool.imap_unordered_bounded(
        task, items, max_pending, stop_event=stop_event, pause_event=pause_event
    ):
        results.append((result_item, rc))
        completed += 1
        if progress_callback:
            progress_callback(PHASE_RESAMPLE, completed, total)
        logger.info(f"Resample {'OK' if rc == 0 else 'FAILED'}: {item.rel_path}")
    
    return results


def execute_recompress_phase(
    items: List[LibraryPlanItem],
    pool: WorkerPool,
    db: PacDB,
    now_ts: int,
    cfg: PacSettings,
    stop_event=None,
    pause_event=None,
    progress_callback=None
) -> List[Tuple[LibraryPlanItem, int]]:
    """Execute recompression phase with parallel execution.
    
    Can be called independently for granular control.
    """
    results = []
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window
    total = len(items)
    completed = 0

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
        results.append((result_item, rc))
        completed += 1
        if progress_callback:
            progress_callback(PHASE_RECOMPRESS, completed, total)
        logger.info(f"Recompress {'OK' if rc == 0 else 'FAILED'}: {item.rel_path}")
    
    return results


def execute_art_phase(
    items: List[LibraryPlanItem],
    pool: WorkerPool,
    db: PacDB,
    now_ts: int,
    cfg: PacSettings,
    stop_event=None,
    pause_event=None,
    progress_callback=None
) -> List[Tuple[LibraryPlanItem, Optional[Path]]]:
    """Execute artwork extraction phase with parallel execution.
    
    Can be called independently for granular control.
    """
    results = []
    art_root = Path(cfg.flac_art_root).expanduser()
    max_pending = min(len(items), pool._max_workers * 4)  # 4x workers for bounded window
    total = len(items)
    completed = 0

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
        results.append((result_item, art_path))
        completed += 1
        if progress_callback:
            progress_callback(PHASE_ARTWORK, completed, total)
        logger.info(f"Artwork {'OK' if art_path else 'SKIP'}: {item.rel_path}")
    
    return results




def _was_held(md5: str, plan: List[LibraryPlanItem]) -> bool:
    """Check if a file was held during planning/execution."""
    for item in plan:
        if item.flac_md5 == md5 and item.action == "hold":
            return True
    return False


def scan_adoptable_files(
    output_dir: Path,
    extensions: tuple = (".m4a", ".mp4", ".opus"),
) -> List[Dict[str, Any]]:
    """Scan for output files without PAC_* tags that can be adopted.
    
    Returns list of dicts with path, extension, and current tags info.
    """
    from .metadata import read_pac_tags, PAC_KEYS
    
    adoptable = []
    output_path = Path(output_dir).resolve()
    
    if not output_path.exists():
        return adoptable
    
    for ext in extensions:
        for file_path in output_path.rglob(f"*{ext}"):
            try:
                pac_tags = read_pac_tags(file_path)
                # File is adoptable if it has no PAC_SRC_MD5 tag
                if not pac_tags.get("PAC_SRC_MD5"):
                    adoptable.append({
                        "path": file_path,
                        "rel_path": file_path.relative_to(output_path),
                        "extension": ext,
                        "existing_tags": pac_tags,
                    })
            except Exception as e:
                logger.warning(f"Error reading tags from {file_path}: {e}")
    
    return adoptable


def execute_adopt_phase(
    output_dir: Path,
    source_dir: Path,
    cfg: PacSettings,
    *,
    dry_run: bool = False,
    stop_event=None,
    pause_event=None,
    progress_callback=None,
) -> Dict[str, Any]:
    """Adopt legacy output files by adding PAC_* tags without re-encoding.
    
    Scans output_dir for files without PAC_* tags, attempts to match them
    to source FLAC files, and writes PAC_* metadata.
    
    Returns summary with counts of adopted, skipped, and failed files.
    """
    from .metadata import write_pac_tags_mp4, write_pac_tags_opus, read_pac_tags
    from .scanner import scan_flac_files
    import hashlib
    
    output_path = Path(output_dir).resolve()
    source_path = Path(source_dir).resolve()
    
    summary = {
        "scanned": 0,
        "adoptable": 0,
        "adopted": 0,
        "skipped": 0,
        "failed": 0,
        "details": [],
    }
    
    # Scan for adoptable files
    logger.info(f"Scanning for adoptable files in {output_path}")
    adoptable = scan_adoptable_files(output_path)
    summary["scanned"] = len(adoptable)
    summary["adoptable"] = len(adoptable)
    
    if not adoptable:
        logger.info("No adoptable files found")
        return summary
    
    logger.info(f"Found {len(adoptable)} adoptable files")
    
    if dry_run:
        for item in adoptable:
            summary["details"].append({
                "path": str(item["rel_path"]),
                "action": "would_adopt",
            })
        return summary
    
    # Scan source files to build lookup by relative path (stem)
    logger.info(f"Scanning source library for matching files")
    sources = scan_flac_files(
        source_path,
        compute_flac_md5=True,
        max_workers=cfg.workers or 4,
    )
    
    # Build lookup: stem -> source info
    source_lookup = {}
    for src in sources:
        stem = src.rel_path.stem if hasattr(src.rel_path, 'stem') else Path(src.rel_path).stem
        # Store by relative path without extension for matching
        rel_stem = str(src.rel_path).rsplit('.', 1)[0]
        source_lookup[rel_stem] = src
    
    total = len(adoptable)
    completed = 0
    
    for item in adoptable:
        if stop_event and stop_event.is_set():
            break
        if pause_event:
            pause_event.wait()
        
        file_path = item["path"]
        rel_path = item["rel_path"]
        ext = item["extension"]
        
        # Try to find matching source by relative path stem
        rel_stem = str(rel_path).rsplit('.', 1)[0]
        source = source_lookup.get(rel_stem)
        
        if not source:
            logger.warning(f"No matching source found for {rel_path}")
            summary["skipped"] += 1
            summary["details"].append({
                "path": str(rel_path),
                "action": "skipped",
                "reason": "no_matching_source",
            })
        else:
            try:
                # Determine encoder and quality from file if possible
                encoder = "unknown"
                quality = "unknown"
                
                pac_data = {
                    "src_md5": source.flac_md5,
                    "encoder": encoder,
                    "quality": quality,
                    "version": "adopted",
                    "source_rel": str(source.rel_path),
                }
                
                if ext in (".m4a", ".mp4"):
                    write_pac_tags_mp4(file_path, **pac_data)
                elif ext == ".opus":
                    write_pac_tags_opus(file_path, **pac_data)
                
                logger.info(f"Adopted: {rel_path}")
                summary["adopted"] += 1
                summary["details"].append({
                    "path": str(rel_path),
                    "action": "adopted",
                    "source": str(source.rel_path),
                })
            except Exception as e:
                logger.error(f"Failed to adopt {rel_path}: {e}")
                summary["failed"] += 1
                summary["details"].append({
                    "path": str(rel_path),
                    "action": "failed",
                    "error": str(e),
                })
        
        completed += 1
        if progress_callback:
            progress_callback(PHASE_ADOPT, completed, total)
    
    logger.info(f"Adopt phase complete: {summary['adopted']} adopted, {summary['skipped']} skipped, {summary['failed']} failed")
    return summary