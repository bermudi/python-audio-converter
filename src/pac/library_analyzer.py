"""Non-destructive library analysis for browsing file status.

This module analyzes a FLAC library without modifying anything,
returning structured data suitable for GUI display.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from loguru import logger

from .config import PacSettings
from .db import PacDB
from .scanner import SourceFile, read_flac_streaminfo_md5
from .flac_tools import flac_stream_info, needs_cd_downmix, get_flac_tag
from .metadata import read_pac_tags


class FileStatus(Enum):
    """Status indicators for library files."""
    UNKNOWN = "unknown"
    OK = "ok"
    NEEDS_ACTION = "needs_action"
    ERROR = "error"


class IntegrityStatus(Enum):
    """Integrity check status."""
    UNKNOWN = "unknown"
    PASSED = "passed"
    FAILED = "failed"
    NEVER_TESTED = "never_tested"


@dataclass
class AnalyzedFile:
    """Analysis result for a single file."""
    path: Path
    rel_path: Path
    size: int
    flac_md5: Optional[str] = None
    
    # Audio format info
    bit_depth: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    is_hires: bool = False
    
    # Status flags
    integrity_status: IntegrityStatus = IntegrityStatus.UNKNOWN
    integrity_message: Optional[str] = None
    last_integrity_test: Optional[int] = None
    
    # Compression info
    compression_level: Optional[int] = None
    compression_tag: Optional[str] = None
    needs_recompress: bool = False
    
    # PAC tags (for output files)
    has_pac_tags: bool = False
    pac_src_md5: Optional[str] = None
    is_legacy: bool = False  # Output without PAC tags
    
    # Artwork
    has_embedded_art: bool = False
    art_exported: bool = False
    
    # Overall status for display
    overall_status: FileStatus = FileStatus.UNKNOWN
    status_reasons: List[str] = field(default_factory=list)


@dataclass
class LibraryAnalysis:
    """Complete analysis of a library directory."""
    root: Path
    files: List[AnalyzedFile]
    
    # Summary statistics
    total_files: int = 0
    hires_count: int = 0
    integrity_unknown_count: int = 0
    integrity_passed_count: int = 0
    integrity_failed_count: int = 0
    needs_recompress_count: int = 0
    legacy_count: int = 0
    has_art_count: int = 0
    art_exported_count: int = 0
    
    # By directory for tree view
    by_directory: Dict[str, List[AnalyzedFile]] = field(default_factory=dict)


def analyze_library(
    root: Path,
    cfg: PacSettings,
    *,
    db: Optional[PacDB] = None,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    max_workers: Optional[int] = None,
) -> LibraryAnalysis:
    """Analyze a FLAC library without modifying anything.
    
    Args:
        root: Root directory of the FLAC library
        cfg: PAC settings for determining status thresholds
        db: Optional database for cached integrity/compression info
        stop_event: Threading event to signal cancellation
        progress_callback: Optional callback(current, total) for progress
        max_workers: Max parallel workers for analysis
    
    Returns:
        LibraryAnalysis with all file status information
    """
    root = Path(root).resolve()
    if not root.exists():
        logger.error(f"Root directory does not exist: {root}")
        return LibraryAnalysis(root=root, files=[])
    
    # Discover all FLAC files
    logger.info(f"Scanning for FLAC files in {root}")
    flac_paths = []
    for dirpath, _, filenames in os.walk(root):
        if stop_event and stop_event.is_set():
            break
        for name in filenames:
            if name.lower().endswith(".flac"):
                flac_paths.append(Path(dirpath) / name)
    
    total = len(flac_paths)
    logger.info(f"Found {total} FLAC files to analyze")
    
    if not flac_paths:
        return LibraryAnalysis(root=root, files=[])
    
    # Analyze files in parallel
    workers = max_workers or cfg.flac_analysis_workers or 4
    analyzed_files: List[AnalyzedFile] = []
    completed = 0
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_path = {
            executor.submit(_analyze_single_file, path, root, cfg, db): path 
            for path in flac_paths
        }
        
        for future in as_completed(future_to_path):
            if stop_event and stop_event.is_set():
                break
            
            try:
                result = future.result()
                if result:
                    analyzed_files.append(result)
            except Exception as e:
                path = future_to_path[future]
                logger.warning(f"Error analyzing {path}: {e}")
            
            completed += 1
            if progress_callback:
                progress_callback(completed, total)
    
    # Build analysis result with statistics
    analysis = _build_analysis(root, analyzed_files)
    return analysis


def analyze_output_directory(
    root: Path,
    source_root: Optional[Path] = None,
    *,
    extensions: tuple = (".m4a", ".mp4", ".opus"),
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    max_workers: Optional[int] = None,
) -> LibraryAnalysis:
    """Analyze an output directory for legacy files without PAC tags.
    
    Args:
        root: Root directory of the output library
        source_root: Optional source FLAC root for matching
        extensions: File extensions to scan
        stop_event: Threading event to signal cancellation
        progress_callback: Optional callback(current, total) for progress
        max_workers: Max parallel workers
    
    Returns:
        LibraryAnalysis with legacy file information
    """
    root = Path(root).resolve()
    if not root.exists():
        return LibraryAnalysis(root=root, files=[])
    
    # Discover output files
    output_paths = []
    for ext in extensions:
        for dirpath, _, filenames in os.walk(root):
            if stop_event and stop_event.is_set():
                break
            for name in filenames:
                if name.lower().endswith(ext):
                    output_paths.append(Path(dirpath) / name)
    
    total = len(output_paths)
    if not output_paths:
        return LibraryAnalysis(root=root, files=[])
    
    # Analyze files
    analyzed_files: List[AnalyzedFile] = []
    completed = 0
    workers = max_workers or 4
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_path = {
            executor.submit(_analyze_output_file, path, root): path 
            for path in output_paths
        }
        
        for future in as_completed(future_to_path):
            if stop_event and stop_event.is_set():
                break
            
            try:
                result = future.result()
                if result:
                    analyzed_files.append(result)
            except Exception as e:
                path = future_to_path[future]
                logger.warning(f"Error analyzing output {path}: {e}")
            
            completed += 1
            if progress_callback:
                progress_callback(completed, total)
    
    return _build_analysis(root, analyzed_files)


def _analyze_single_file(
    path: Path,
    root: Path,
    cfg: PacSettings,
    db: Optional[PacDB],
) -> Optional[AnalyzedFile]:
    """Analyze a single FLAC file."""
    try:
        rel_path = path.relative_to(root)
        stat = path.stat()
        
        # Read FLAC MD5 from STREAMINFO
        flac_md5 = read_flac_streaminfo_md5(path)
        
        # Get stream info
        info = flac_stream_info(path)
        
        result = AnalyzedFile(
            path=path,
            rel_path=rel_path,
            size=stat.st_size,
            flac_md5=flac_md5,
        )
        
        if info:
            result.bit_depth = info.get("bit_depth")
            result.sample_rate = info.get("sample_rate")
            result.channels = info.get("channels")
            result.is_hires = needs_cd_downmix(info)
        
        # Check compression tag
        compression_tag = get_flac_tag(path, "COMPRESSION")
        if compression_tag:
            result.compression_tag = compression_tag
            import re
            match = re.search(r'level=(\d+)', compression_tag)
            if match:
                result.compression_level = int(match.group(1))
        
        # Check if recompression needed
        if result.compression_level is None or result.compression_level != cfg.flac_target_compression:
            result.needs_recompress = True
        
        # Check embedded artwork
        try:
            from mutagen.flac import FLAC
            flac_obj = FLAC(str(path))
            if flac_obj and flac_obj.pictures:
                result.has_embedded_art = True
        except Exception:
            pass
        
        # Check database for integrity status
        if db and flac_md5:
            try:
                row = db.conn.execute(
                    "SELECT last_test_ts, test_ok, test_msg FROM flac_checks WHERE md5 = ?",
                    (flac_md5,)
                ).fetchone()
                if row:
                    result.last_integrity_test = row["last_test_ts"]
                    if row["test_ok"] == 1:
                        result.integrity_status = IntegrityStatus.PASSED
                    elif row["test_ok"] == 0:
                        result.integrity_status = IntegrityStatus.FAILED
                        result.integrity_message = row["test_msg"]
                    else:
                        result.integrity_status = IntegrityStatus.NEVER_TESTED
                else:
                    result.integrity_status = IntegrityStatus.NEVER_TESTED
                
                # Check art export status
                art_row = db.conn.execute(
                    "SELECT last_export_ts FROM art_exports WHERE md5 = ?",
                    (flac_md5,)
                ).fetchone()
                if art_row:
                    result.art_exported = True
            except Exception as e:
                logger.debug(f"DB lookup error for {path}: {e}")
        else:
            result.integrity_status = IntegrityStatus.NEVER_TESTED
        
        # Determine overall status
        _compute_overall_status(result)
        
        return result
        
    except Exception as e:
        logger.warning(f"Failed to analyze {path}: {e}")
        return None


def _analyze_output_file(path: Path, root: Path) -> Optional[AnalyzedFile]:
    """Analyze a single output file for PAC tags."""
    try:
        rel_path = path.relative_to(root)
        stat = path.stat()
        
        result = AnalyzedFile(
            path=path,
            rel_path=rel_path,
            size=stat.st_size,
        )
        
        # Read PAC tags
        pac_tags = read_pac_tags(path)
        if pac_tags.get("PAC_SRC_MD5"):
            result.has_pac_tags = True
            result.pac_src_md5 = pac_tags.get("PAC_SRC_MD5")
        else:
            result.is_legacy = True
            result.status_reasons.append("No PAC_* tags (legacy file)")
        
        _compute_overall_status(result)
        return result
        
    except Exception as e:
        logger.warning(f"Failed to analyze output {path}: {e}")
        return None


def _compute_overall_status(file: AnalyzedFile) -> None:
    """Compute overall status and reasons for a file."""
    file.status_reasons = []
    needs_action = False
    has_error = False
    
    # Check integrity
    if file.integrity_status == IntegrityStatus.FAILED:
        has_error = True
        file.status_reasons.append("Integrity check failed")
    elif file.integrity_status == IntegrityStatus.NEVER_TESTED:
        needs_action = True
        file.status_reasons.append("Never integrity tested")
    
    # Check compression
    if file.needs_recompress:
        needs_action = True
        if file.compression_level is not None:
            file.status_reasons.append(f"Compression level {file.compression_level} (needs recompress)")
        else:
            file.status_reasons.append("No compression tag")
    
    # Check hi-res
    if file.is_hires:
        file.status_reasons.append(f"Hi-res: {file.bit_depth}bit/{file.sample_rate}Hz")
    
    # Check legacy
    if file.is_legacy:
        needs_action = True
    
    # Set overall status
    if has_error:
        file.overall_status = FileStatus.ERROR
    elif needs_action:
        file.overall_status = FileStatus.NEEDS_ACTION
    elif file.integrity_status == IntegrityStatus.PASSED:
        file.overall_status = FileStatus.OK
    else:
        file.overall_status = FileStatus.UNKNOWN


def _build_analysis(root: Path, files: List[AnalyzedFile]) -> LibraryAnalysis:
    """Build LibraryAnalysis with statistics from analyzed files."""
    analysis = LibraryAnalysis(root=root, files=files)
    
    # Compute statistics
    analysis.total_files = len(files)
    
    by_dir: Dict[str, List[AnalyzedFile]] = {}
    
    for f in files:
        # Count by category
        if f.is_hires:
            analysis.hires_count += 1
        
        if f.integrity_status == IntegrityStatus.NEVER_TESTED:
            analysis.integrity_unknown_count += 1
        elif f.integrity_status == IntegrityStatus.PASSED:
            analysis.integrity_passed_count += 1
        elif f.integrity_status == IntegrityStatus.FAILED:
            analysis.integrity_failed_count += 1
        
        if f.needs_recompress:
            analysis.needs_recompress_count += 1
        
        if f.is_legacy:
            analysis.legacy_count += 1
        
        if f.has_embedded_art:
            analysis.has_art_count += 1
        
        if f.art_exported:
            analysis.art_exported_count += 1
        
        # Group by directory
        dir_key = str(f.rel_path.parent)
        if dir_key not in by_dir:
            by_dir[dir_key] = []
        by_dir[dir_key].append(f)
    
    analysis.by_directory = by_dir
    
    return analysis
