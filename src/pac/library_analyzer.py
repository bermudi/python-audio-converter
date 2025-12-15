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


class SyncStatus(Enum):
    """Sync status between source and output files."""
    SYNCED = "synced"        # Output exists and matches source MD5
    OUTDATED = "outdated"    # Output exists but source MD5 differs
    MISSING = "missing"      # Source exists but no output
    ORPHAN = "orphan"        # Output exists but no source


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


@dataclass
class OutputInfo:
    """Information about an output file."""
    path: Path
    rel_path: Path
    size: int
    codec: Optional[str] = None  # e.g., "aac", "opus"
    quality: Optional[str] = None  # e.g., "VBR 5", "128 kbps"
    pac_src_md5: Optional[str] = None
    has_pac_tags: bool = False


@dataclass
class CorrelatedFile:
    """A source file correlated with its output status."""
    source: Optional[AnalyzedFile]
    output: Optional[OutputInfo]
    sync_status: SyncStatus
    
    @property
    def rel_path(self) -> Path:
        """Return the relative path (from source or output)."""
        if self.source:
            return self.source.rel_path
        elif self.output:
            return self.output.rel_path
        return Path("")
    
    @property
    def display_path(self) -> str:
        """Return display path without extension for matching."""
        return str(self.rel_path.with_suffix(""))


@dataclass
class CorrelatedAnalysis:
    """Analysis correlating source and output directories."""
    source_root: Path
    output_root: Path
    files: List[CorrelatedFile]
    
    # Summary statistics
    total_sources: int = 0
    total_outputs: int = 0
    synced_count: int = 0
    outdated_count: int = 0
    missing_count: int = 0
    orphan_count: int = 0


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


def _get_output_extension_map(output_root: Path) -> Dict[str, str]:
    """Detect output file extensions present in the output directory.
    
    Returns a mapping of base path (without extension) to actual extension found.
    """
    ext_map: Dict[str, str] = {}
    output_extensions = (".m4a", ".mp4", ".opus")
    
    for dirpath, _, filenames in os.walk(output_root):
        for name in filenames:
            name_lower = name.lower()
            for ext in output_extensions:
                if name_lower.endswith(ext):
                    full_path = Path(dirpath) / name
                    try:
                        rel_path = full_path.relative_to(output_root)
                        base_path = str(rel_path.with_suffix(""))
                        ext_map[base_path] = ext
                    except ValueError:
                        pass
                    break
    
    return ext_map


def _analyze_output_file_for_correlation(path: Path, root: Path) -> Optional[OutputInfo]:
    """Analyze a single output file for correlation purposes."""
    try:
        rel_path = path.relative_to(root)
        stat = path.stat()
        
        result = OutputInfo(
            path=path,
            rel_path=rel_path,
            size=stat.st_size,
        )
        
        # Determine codec from extension
        ext = path.suffix.lower()
        if ext in (".m4a", ".mp4"):
            result.codec = "aac"
        elif ext == ".opus":
            result.codec = "opus"
        
        # Read PAC tags
        pac_tags = read_pac_tags(path)
        if pac_tags.get("PAC_SRC_MD5"):
            result.has_pac_tags = True
            result.pac_src_md5 = pac_tags.get("PAC_SRC_MD5")
            # Try to extract quality info from tags
            if pac_tags.get("PAC_ENCODER"):
                result.quality = pac_tags.get("PAC_ENCODER")
        
        return result
        
    except Exception as e:
        logger.warning(f"Failed to analyze output {path}: {e}")
        return None


def correlate_libraries(
    source_analysis: LibraryAnalysis,
    output_root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    max_workers: Optional[int] = None,
) -> CorrelatedAnalysis:
    """Correlate source library files with output directory.
    
    Args:
        source_analysis: Analysis of the source FLAC library
        output_root: Root directory of the output files
        stop_event: Threading event to signal cancellation
        progress_callback: Optional callback(current, total) for progress
        max_workers: Max parallel workers for output analysis
    
    Returns:
        CorrelatedAnalysis with matched source↔output pairs
    """
    output_root = Path(output_root).resolve()
    
    # Build extension map from output directory
    logger.info(f"Scanning output directory {output_root} for correlation")
    ext_map = _get_output_extension_map(output_root)
    
    # Build output files index by base path (without extension)
    output_by_base: Dict[str, OutputInfo] = {}
    workers = max_workers or 4
    
    # Scan and analyze output files
    output_paths = []
    for base_path, ext in ext_map.items():
        output_paths.append(output_root / (base_path + ext))
    
    total_outputs = len(output_paths)
    logger.info(f"Found {total_outputs} output files to analyze")
    
    if output_paths:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_path = {
                executor.submit(_analyze_output_file_for_correlation, path, output_root): path
                for path in output_paths
            }
            
            completed = 0
            for future in as_completed(future_to_path):
                if stop_event and stop_event.is_set():
                    break
                
                try:
                    result = future.result()
                    if result:
                        base_path = str(result.rel_path.with_suffix(""))
                        output_by_base[base_path] = result
                except Exception as e:
                    path = future_to_path[future]
                    logger.warning(f"Error analyzing output {path}: {e}")
                
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_outputs)
    
    # Correlate sources with outputs
    correlated_files: List[CorrelatedFile] = []
    matched_bases: set = set()
    
    for source_file in source_analysis.files:
        if stop_event and stop_event.is_set():
            break
        
        base_path = str(source_file.rel_path.with_suffix(""))
        output_info = output_by_base.get(base_path)
        
        if output_info:
            matched_bases.add(base_path)
            # Determine sync status by comparing MD5
            if output_info.pac_src_md5 and source_file.flac_md5:
                if output_info.pac_src_md5 == source_file.flac_md5:
                    sync_status = SyncStatus.SYNCED
                else:
                    sync_status = SyncStatus.OUTDATED
            elif output_info.has_pac_tags:
                # Has PAC tags but can't verify MD5
                sync_status = SyncStatus.SYNCED  # Assume synced if tagged
            else:
                # No PAC tags - legacy file, consider outdated
                sync_status = SyncStatus.OUTDATED
            
            correlated_files.append(CorrelatedFile(
                source=source_file,
                output=output_info,
                sync_status=sync_status,
            ))
        else:
            # Source without output = MISSING
            correlated_files.append(CorrelatedFile(
                source=source_file,
                output=None,
                sync_status=SyncStatus.MISSING,
            ))
    
    # Find orphans (outputs without sources)
    for base_path, output_info in output_by_base.items():
        if base_path not in matched_bases:
            correlated_files.append(CorrelatedFile(
                source=None,
                output=output_info,
                sync_status=SyncStatus.ORPHAN,
            ))
    
    # Build result with statistics
    result = CorrelatedAnalysis(
        source_root=source_analysis.root,
        output_root=output_root,
        files=correlated_files,
        total_sources=len(source_analysis.files),
        total_outputs=len(output_by_base),
    )
    
    # Count by status
    for cf in correlated_files:
        if cf.sync_status == SyncStatus.SYNCED:
            result.synced_count += 1
        elif cf.sync_status == SyncStatus.OUTDATED:
            result.outdated_count += 1
        elif cf.sync_status == SyncStatus.MISSING:
            result.missing_count += 1
        elif cf.sync_status == SyncStatus.ORPHAN:
            result.orphan_count += 1
    
    logger.info(f"Correlation complete: {result.synced_count} synced, "
                f"{result.outdated_count} outdated, {result.missing_count} missing, "
                f"{result.orphan_count} orphan")
    
    return result


def analyze_library_with_outputs(
    source_root: Path,
    output_root: Path,
    cfg: PacSettings,
    *,
    db: Optional[PacDB] = None,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    max_workers: Optional[int] = None,
) -> CorrelatedAnalysis:
    """Convenience function to analyze source library and correlate with outputs.
    
    Args:
        source_root: Root directory of the FLAC source library
        output_root: Root directory of the output files
        cfg: PAC settings for analysis
        db: Optional database for cached info
        stop_event: Threading event to signal cancellation
        progress_callback: Optional callback(current, total, phase) for progress
        max_workers: Max parallel workers
    
    Returns:
        CorrelatedAnalysis with all source↔output correlations
    """
    # Phase 1: Analyze source library
    def source_progress(current: int, total: int) -> None:
        if progress_callback:
            progress_callback(current, total, "source")
    
    source_analysis = analyze_library(
        source_root,
        cfg,
        db=db,
        stop_event=stop_event,
        progress_callback=source_progress,
        max_workers=max_workers,
    )
    
    if stop_event and stop_event.is_set():
        return CorrelatedAnalysis(
            source_root=Path(source_root),
            output_root=Path(output_root),
            files=[],
        )
    
    # Phase 2: Correlate with outputs
    def output_progress(current: int, total: int) -> None:
        if progress_callback:
            progress_callback(current, total, "output")
    
    return correlate_libraries(
        source_analysis,
        output_root,
        stop_event=stop_event,
        progress_callback=output_progress,
        max_workers=max_workers,
    )
