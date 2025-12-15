from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from PySide6 import QtCore, QtGui, QtWidgets
from loguru import logger

# Ensure local src/ is importable when running from project root
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import project modules after adjusting sys.path
from pac.ffmpeg_check import probe_ffmpeg, probe_fdkaac, probe_qaac  # noqa: E402
from pac.config import PacSettings  # noqa: E402
from pac.library_runner import (  # noqa: E402
    cmd_manage_library,
    scan_adoptable_files,
    execute_adopt_phase,
    PHASE_SCAN, PHASE_INTEGRITY, PHASE_RESAMPLE, PHASE_RECOMPRESS, PHASE_ARTWORK, PHASE_ADOPT, PHASE_MIRROR,
    ALL_PHASES,
)
from pac.library_analyzer import (  # noqa: E402
    analyze_library,
    analyze_output_directory,
    analyze_library_with_outputs,
    correlate_libraries,
    AnalyzedFile,
    LibraryAnalysis,
    CorrelatedFile,
    CorrelatedAnalysis,
    OutputInfo,
    FileStatus,
    IntegrityStatus,
    SyncStatus,
)
from main import configure_logging, cmd_convert_dir, EXIT_OK, EXIT_WITH_FILE_ERRORS, EXIT_PREFLIGHT_FAILED  # noqa: E402


class DropLineEdit(QtWidgets.QLineEdit):
    """QLineEdit subclass that accepts directory drops via drag-and-drop.
    
    Works on both X11 and Wayland (including KDE Plasma) using Qt6's native
    drag-drop support with text/uri-list MIME type.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
    
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept drag events containing file/folder URIs."""
        if event.mimeData().hasUrls():
            # Check if any URL is a local directory
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_dir():
                        event.acceptProposedAction()
                        return
        event.ignore()
    
    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        """Accept drag move events for valid drops."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        """Handle drop events by extracting directory path."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_dir():
                        self.setText(str(path))
                        event.acceptProposedAction()
                        return
        event.ignore()


class LogEmitter(QtCore.QObject):
    message = QtCore.Signal(str)


def setup_logger_for_gui(emitter: LogEmitter, level: str = "INFO", json_path: Optional[str] = None) -> None:
    """Configure Loguru to forward logs to the GUI log panel and optional JSON file.

    This replaces existing sinks to avoid duplicate outputs.
    """
    logger.remove()
    # Human-readable line for the GUI and stderr
    fmt = "<level>{level: <8}</level> | <green>{time:HH:mm:ss}</green> | <cyan>{message}</cyan>"

    def qt_sink(msg: "loguru.Message") -> None:  # type: ignore[name-defined]
        try:
            text = msg.record.get("message", msg)
            if not isinstance(text, str):
                text = str(msg)
            emitter.message.emit(text.rstrip())
        except Exception:
            # As a fallback, do nothing to avoid crashing the UI thread
            pass

    # Send to UI
    logger.add(qt_sink, level=level.upper(), format=fmt, enqueue=True)
    # Also keep stderr for convenience
    logger.add(sys.stderr, level=level.upper(), format=fmt, enqueue=True, backtrace=False, diagnose=False)
    # Optional JSON lines
    if json_path:
        logger.add(json_path, level="DEBUG", serialize=True, enqueue=True)


class PreflightWorker(QtCore.QThread):
    result = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, skip_wine: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.skip_wine = skip_wine

    def run(self) -> None:  # type: ignore[override]
        try:
            st = probe_ffmpeg(check_aac=True)
            st_fd = probe_fdkaac()
            
            # Only probe qaac if not skipping Wine encoders
            if self.skip_wine:
                st_qa_available = False
                st_qa_version = None
                st_qa_path = None
            else:
                st_qa = probe_qaac(light=False)
                st_qa_available = st_qa.available
                st_qa_version = st_qa.qaac_version if st_qa.available else None
                st_qa_path = st_qa.qaac_path

            # An encoder is OK if we have a way to encode either AAC or Opus
            aac_ok = st.available and (st.has_libfdk_aac or st_qa_available or st_fd.available)
            opus_ok = st.available and st.has_libopus
            ok = aac_ok or opus_ok

            res = {
                "ffmpeg": st.ffmpeg_version or st.error or "unknown",
                "ffmpeg_path": st.ffmpeg_path,
                "libfdk_aac": bool(st.has_libfdk_aac),
                "libopus": bool(st.has_libopus),
                "qaac": st_qa_version,
                "qaac_path": st_qa_path,
                "fdkaac": st_fd.fdkaac_version if st_fd.available else None,
                "fdkaac_path": st_fd.fdkaac_path,
                "ok": ok,
                "wine_skipped": self.skip_wine,
            }
            self.result.emit(res)
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))


class ConvertWorker(QtCore.QThread):
    finished_with_code = QtCore.Signal(int)
    plan_ready = QtCore.Signal(dict)

    def __init__(
        self,
        *,
        cfg: PacSettings,
        src_dir: Path,
        out_dir: Path,
        codec: str,
        tvbr: int,
        vbr: int,
        opus_vbr_kbps: int,
        workers: int,
        
        verbose: bool,
        dry_run: bool,
        force_reencode: bool,
        allow_rename: bool,
        retag_existing: bool,
        prune_orphans: bool,
        sync_tags: bool,
        verify_tags: bool,
        verify_strict: bool,
        log_json_path: Optional[str],
        no_adopt: bool,
        cover_art_resize: bool,
        cover_art_max_size: int,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.src_dir = src_dir
        self.out_dir = out_dir
        self.codec = codec
        self.tvbr = tvbr
        self.vbr = vbr
        self.opus_vbr_kbps = opus_vbr_kbps
        self.workers = workers
        
        self.verbose = verbose
        self.dry_run = dry_run
        self.force_reencode = force_reencode
        self.allow_rename = allow_rename
        self.retag_existing = retag_existing
        self.prune_orphans = prune_orphans
        self.sync_tags = sync_tags
        self.verify_tags = verify_tags
        self.verify_strict = verify_strict
        self.log_json_path = log_json_path
        self.no_adopt = no_adopt
        self.cover_art_resize = cover_art_resize
        self.cover_art_max_size = cover_art_max_size

        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Not paused by default

    def cancel(self) -> None:
        self.stop_event.set()

    def toggle_pause(self) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()  # Pause
        else:
            self.pause_event.set()  # Resume

    def run(self) -> None:  # type: ignore[override]
        code = EXIT_OK
        plan = None
        try:
            logger.info("Starting cmd_convert_dir in worker")
            # The new cmd_convert_dir will return a tuple (exit_code, plan_summary)
            code, plan = cmd_convert_dir(
                self.cfg,
                str(self.src_dir),
                str(self.out_dir),
                codec=self.codec,
                tvbr=self.tvbr,
                vbr=self.vbr,
                opus_vbr_kbps=self.opus_vbr_kbps,
                workers=self.workers,

                verbose=self.verbose,
                dry_run=self.dry_run,
                force_reencode=self.force_reencode,
                allow_rename=self.allow_rename,
                retag_existing=self.retag_existing,
                prune_orphans=self.prune_orphans,
                sync_tags=self.sync_tags,
                log_json_path=self.log_json_path,
                verify_tags=self.verify_tags,
                verify_strict=self.verify_strict,
                no_adopt=self.no_adopt,
                cover_art_resize=self.cover_art_resize,
                cover_art_max_size=self.cover_art_max_size,
                stop_event=self.stop_event,
                pause_event=self.pause_event,
                interactive=False,
            )
            logger.info(f"cmd_convert_dir completed with code {code}")
            if plan:
                self.plan_ready.emit(plan)
        except Exception as e:
            logger.error(f"Exception in ConvertWorker: {e}", exc_info=True)
            code = EXIT_WITH_FILE_ERRORS
        self.finished_with_code.emit(code)


class LibraryWorker(QtCore.QThread):
    finished_with_code = QtCore.Signal(int)
    summary_ready = QtCore.Signal(dict)
    progress_update = QtCore.Signal(str, int, int)  # phase_name, current, total

    def __init__(
        self,
        cfg: PacSettings,
        root: str,
        *,
        mirror_out: Optional[str] = None,
        dry_run: bool = False,
        phases: Optional[set] = None,
        only_rel_paths: Optional[List[str]] = None,
        **kwargs
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.root = root
        self.mirror_out = mirror_out
        self.dry_run = dry_run
        self.phases = phases
        self.only_rel_paths = only_rel_paths
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Not paused initially

    def cancel(self) -> None:
        self.stop_event.set()

    def toggle_pause(self) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
        else:
            self.pause_event.set()

    def _progress_callback(self, phase: str, current: int, total: int) -> None:
        self.progress_update.emit(phase, current, total)

    def run(self) -> None:  # type: ignore[override]
        try:
            exit_code, summary = cmd_manage_library(
                self.cfg,
                self.root,
                mirror_out=self.mirror_out,
                dry_run=self.dry_run,
                phases=self.phases,
                only_rel_paths=self.only_rel_paths,
                stop_event=self.stop_event,
                pause_event=self.pause_event,
                progress_callback=self._progress_callback,
            )
            self.summary_ready.emit(summary)
            self.finished_with_code.emit(exit_code)
        except Exception as e:
            logger.error(f"Library operation failed: {e}")
            self.finished_with_code.emit(1)


class AdoptWorker(QtCore.QThread):
    """Worker thread for adopting legacy files without PAC_* tags."""
    finished_with_code = QtCore.Signal(int)
    summary_ready = QtCore.Signal(dict)
    progress_update = QtCore.Signal(str, int, int)  # phase_name, current, total

    def __init__(
        self,
        cfg: PacSettings,
        output_dir: str,
        source_dir: str,
        *,
        dry_run: bool = False,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.output_dir = output_dir
        self.source_dir = source_dir
        self.dry_run = dry_run
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()

    def cancel(self) -> None:
        self.stop_event.set()

    def toggle_pause(self) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
        else:
            self.pause_event.set()

    def _progress_callback(self, phase: str, current: int, total: int) -> None:
        self.progress_update.emit(phase, current, total)

    def run(self) -> None:  # type: ignore[override]
        try:
            summary = execute_adopt_phase(
                Path(self.output_dir),
                Path(self.source_dir),
                self.cfg,
                dry_run=self.dry_run,
                stop_event=self.stop_event,
                pause_event=self.pause_event,
                progress_callback=self._progress_callback,
            )
            self.summary_ready.emit(summary)
            self.finished_with_code.emit(0 if summary.get("failed", 0) == 0 else 1)
        except Exception as e:
            logger.error(f"Adopt operation failed: {e}")
            self.finished_with_code.emit(1)


class BrowserWorker(QtCore.QThread):
    """Worker thread for scanning library for browser view."""
    finished_with_result = QtCore.Signal(object)  # LibraryAnalysis or CorrelatedAnalysis
    progress_update = QtCore.Signal(int, int)  # current, total

    # View modes
    MODE_SOURCE_ONLY = "source_only"
    MODE_WITH_OUTPUTS = "with_outputs"
    MODE_OUTPUTS_ONLY = "outputs_only"

    def __init__(
        self,
        cfg: PacSettings,
        root: str,
        *,
        scan_outputs: bool = False,
        output_dir: Optional[str] = None,
        correlation_mode: str = MODE_SOURCE_ONLY,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.root = root
        self.scan_outputs = scan_outputs
        self.output_dir = output_dir
        self.correlation_mode = correlation_mode
        self.stop_event = threading.Event()

    def cancel(self) -> None:
        self.stop_event.set()

    def _progress_callback(self, current: int, total: int) -> None:
        self.progress_update.emit(current, total)

    def _progress_callback_phased(self, current: int, total: int, phase: str) -> None:
        self.progress_update.emit(current, total)

    def run(self) -> None:  # type: ignore[override]
        from pac.db import PacDB
        try:
            db = None
            if self.cfg.db_enable:
                db_path = Path(self.cfg.db_path).expanduser()
                db = PacDB(db_path)

            if self.correlation_mode == self.MODE_WITH_OUTPUTS:
                # Correlated view: source + output status
                if not self.output_dir:
                    logger.error("Correlated mode requires output_dir")
                    self.finished_with_result.emit(None)
                    return
                
                analysis = analyze_library_with_outputs(
                    Path(self.root),
                    Path(self.output_dir),
                    self.cfg,
                    db=db,
                    stop_event=self.stop_event,
                    progress_callback=self._progress_callback_phased,
                )
                self.finished_with_result.emit(analysis)
            elif self.correlation_mode == self.MODE_OUTPUTS_ONLY or (self.scan_outputs and self.output_dir):
                # Outputs only view
                analysis = analyze_output_directory(
                    Path(self.output_dir) if self.output_dir else Path(self.root),
                    source_root=Path(self.root) if self.root else None,
                    stop_event=self.stop_event,
                    progress_callback=self._progress_callback,
                )
                self.finished_with_result.emit(analysis)
            else:
                # Source only view (default)
                analysis = analyze_library(
                    Path(self.root),
                    self.cfg,
                    db=db,
                    stop_event=self.stop_event,
                    progress_callback=self._progress_callback,
                )
                self.finished_with_result.emit(analysis)
        except Exception as e:
            logger.error(f"Browser scan failed: {e}")
            self.finished_with_result.emit(None)


class LibraryTableModel(QtCore.QAbstractTableModel):
    """Table model for displaying analyzed library files."""
    
    COLUMNS = ["Path", "Status", "Integrity", "Format", "Compression", "Art", "Size"]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: List[AnalyzedFile] = []
        self._filtered_files: List[AnalyzedFile] = []
        self._filter_status: Optional[FileStatus] = None
        self._filter_integrity: Optional[IntegrityStatus] = None
        self._filter_hires: Optional[bool] = None
        self._filter_legacy: Optional[bool] = None
        self._filter_needs_action: Optional[bool] = None
    
    def set_files(self, files: List[AnalyzedFile]) -> None:
        self.beginResetModel()
        self._files = files
        self._apply_filters()
        self.endResetModel()
    
    def set_filter(
        self,
        status: Optional[FileStatus] = None,
        integrity: Optional[IntegrityStatus] = None,
        hires: Optional[bool] = None,
        legacy: Optional[bool] = None,
        needs_action: Optional[bool] = None,
    ) -> None:
        self.beginResetModel()
        self._filter_status = status
        self._filter_integrity = integrity
        self._filter_hires = hires
        self._filter_legacy = legacy
        self._filter_needs_action = needs_action
        self._apply_filters()
        self.endResetModel()
    
    def clear_filters(self) -> None:
        self.set_filter()
    
    def _apply_filters(self) -> None:
        self._filtered_files = []
        for f in self._files:
            if self._filter_status and f.overall_status != self._filter_status:
                continue
            if self._filter_integrity and f.integrity_status != self._filter_integrity:
                continue
            if self._filter_hires is True and not f.is_hires:
                continue
            if self._filter_legacy is True and not f.is_legacy:
                continue
            if self._filter_needs_action is True and f.overall_status != FileStatus.NEEDS_ACTION:
                continue
            self._filtered_files.append(f)
    
    def rowCount(self, parent=None) -> int:
        return len(self._filtered_files)
    
    def columnCount(self, parent=None) -> int:
        return len(self.COLUMNS)
    
    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.COLUMNS[section]
        return None
    
    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._filtered_files):
            return None
        
        f = self._filtered_files[index.row()]
        col = index.column()
        
        if role == QtCore.Qt.DisplayRole:
            if col == 0:  # Path
                return str(f.rel_path)
            elif col == 1:  # Status
                return f.overall_status.value.title()
            elif col == 2:  # Integrity
                return f.integrity_status.value.replace("_", " ").title()
            elif col == 3:  # Format
                if f.bit_depth and f.sample_rate:
                    return f"{f.bit_depth}bit/{f.sample_rate//1000}kHz"
                return "-"
            elif col == 4:  # Compression
                if f.compression_level is not None:
                    return f"Level {f.compression_level}"
                return "No tag"
            elif col == 5:  # Art
                if f.has_embedded_art:
                    return "✓ Exported" if f.art_exported else "✓ Embedded"
                return "-"
            elif col == 6:  # Size
                return f"{f.size / 1024 / 1024:.1f} MB"
        
        elif role == QtCore.Qt.ForegroundRole:
            if f.overall_status == FileStatus.ERROR:
                return QtCore.Qt.red
            elif f.overall_status == FileStatus.NEEDS_ACTION:
                return QtCore.Qt.darkYellow
            elif f.overall_status == FileStatus.OK:
                return QtCore.Qt.darkGreen
        
        elif role == QtCore.Qt.ToolTipRole:
            if f.status_reasons:
                return "\n".join(f.status_reasons)
        
        elif role == QtCore.Qt.UserRole:
            return f  # Return the full AnalyzedFile for selection handling
        
        return None
    
    def get_file_at(self, row: int) -> Optional[AnalyzedFile]:
        if 0 <= row < len(self._filtered_files):
            return self._filtered_files[row]
        return None
    
    def get_selected_files(self, indexes) -> List[AnalyzedFile]:
        rows = set(idx.row() for idx in indexes)
        return [self._filtered_files[r] for r in rows if 0 <= r < len(self._filtered_files)]


class CorrelatedTableModel(QtCore.QAbstractTableModel):
    """Table model for displaying correlated source↔output files."""
    
    COLUMNS = ["Path", "Sync Status", "Source Status", "Output Codec", "Output Quality", "Output Size"]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: List[CorrelatedFile] = []
        self._filtered_files: List[CorrelatedFile] = []
        self._filter_sync_status: Optional[SyncStatus] = None
        self._filter_needs_conversion: bool = False
        self._filter_orphans: bool = False
        self._filter_synced: bool = False
    
    def set_files(self, files: List[CorrelatedFile]) -> None:
        self.beginResetModel()
        self._files = files
        self._apply_filters()
        self.endResetModel()
    
    def set_filter(
        self,
        sync_status: Optional[SyncStatus] = None,
        needs_conversion: bool = False,
        orphans: bool = False,
        synced: bool = False,
    ) -> None:
        self.beginResetModel()
        self._filter_sync_status = sync_status
        self._filter_needs_conversion = needs_conversion
        self._filter_orphans = orphans
        self._filter_synced = synced
        self._apply_filters()
        self.endResetModel()
    
    def clear_filters(self) -> None:
        self.set_filter()
    
    def _apply_filters(self) -> None:
        self._filtered_files = []
        for f in self._files:
            if self._filter_sync_status and f.sync_status != self._filter_sync_status:
                continue
            if self._filter_needs_conversion and f.sync_status not in (SyncStatus.MISSING, SyncStatus.OUTDATED):
                continue
            if self._filter_orphans and f.sync_status != SyncStatus.ORPHAN:
                continue
            if self._filter_synced and f.sync_status != SyncStatus.SYNCED:
                continue
            self._filtered_files.append(f)
    
    def rowCount(self, parent=None) -> int:
        return len(self._filtered_files)
    
    def columnCount(self, parent=None) -> int:
        return len(self.COLUMNS)
    
    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.COLUMNS[section]
        return None
    
    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._filtered_files):
            return None
        
        cf = self._filtered_files[index.row()]
        col = index.column()
        
        if role == QtCore.Qt.DisplayRole:
            if col == 0:  # Path
                return cf.display_path
            elif col == 1:  # Sync Status
                return cf.sync_status.value.title()
            elif col == 2:  # Source Status
                if cf.source:
                    return cf.source.overall_status.value.title()
                return "-"
            elif col == 3:  # Output Codec
                if cf.output:
                    return cf.output.codec.upper() if cf.output.codec else "-"
                return "-"
            elif col == 4:  # Output Quality
                if cf.output and cf.output.quality:
                    return cf.output.quality
                return "-"
            elif col == 5:  # Output Size
                if cf.output:
                    return f"{cf.output.size / 1024 / 1024:.1f} MB"
                return "-"
        
        elif role == QtCore.Qt.ForegroundRole:
            # Color coding for sync status
            if cf.sync_status == SyncStatus.SYNCED:
                return QtCore.Qt.darkGreen
            elif cf.sync_status == SyncStatus.OUTDATED:
                return QtCore.Qt.darkYellow
            elif cf.sync_status == SyncStatus.MISSING:
                return QtCore.Qt.red
            elif cf.sync_status == SyncStatus.ORPHAN:
                return QtCore.Qt.darkMagenta
        
        elif role == QtCore.Qt.ToolTipRole:
            tips = [f"Sync: {cf.sync_status.value}"]
            if cf.source:
                tips.append(f"Source: {cf.source.rel_path}")
                if cf.source.flac_md5:
                    tips.append(f"Source MD5: {cf.source.flac_md5[:8]}...")
            if cf.output:
                tips.append(f"Output: {cf.output.rel_path}")
                if cf.output.pac_src_md5:
                    tips.append(f"PAC_SRC_MD5: {cf.output.pac_src_md5[:8]}...")
            return "\n".join(tips)
        
        elif role == QtCore.Qt.UserRole:
            return cf  # Return the full CorrelatedFile for selection handling
        
        return None
    
    def get_file_at(self, row: int) -> Optional[CorrelatedFile]:
        if 0 <= row < len(self._filtered_files):
            return self._filtered_files[row]
        return None
    
    def get_selected_files(self, indexes) -> List[CorrelatedFile]:
        rows = set(idx.row() for idx in indexes)
        return [self._filtered_files[r] for r in rows if 0 <= r < len(self._filtered_files)]


class LibrarySettingsDialog(QtWidgets.QDialog):
    """Modal dialog for library settings."""
    
    def __init__(self, settings: PacSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Library Settings")
        self.setMinimumWidth(500)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        
        # Tab widget for organized settings
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)
        
        # General tab
        general_tab = QtWidgets.QWidget()
        general_layout = QtWidgets.QFormLayout(general_tab)
        
        self.spin_compression = QtWidgets.QSpinBox()
        self.spin_compression.setRange(0, 8)
        self.spin_compression.setValue(self.settings.flac_target_compression)
        self.spin_compression.setToolTip("FLAC compression level (0-8)")
        general_layout.addRow("Target Compression:", self.spin_compression)
        
        self.chk_resample = QtWidgets.QCheckBox("Resample hi-res to CD quality")
        self.chk_resample.setChecked(self.settings.flac_resample_to_cd)
        general_layout.addRow("", self.chk_resample)
        
        self.combo_mirror_codec = QtWidgets.QComboBox()
        self.combo_mirror_codec.addItems(["aac", "opus"])
        self.combo_mirror_codec.setCurrentText(self.settings.lossy_mirror_codec or "aac")
        general_layout.addRow("Mirror Codec:", self.combo_mirror_codec)
        
        tabs.addTab(general_tab, "General")
        
        # Artwork tab
        art_tab = QtWidgets.QWidget()
        art_layout = QtWidgets.QFormLayout(art_tab)
        
        self.edit_art_root = QtWidgets.QLineEdit()
        self.edit_art_root.setText(str(self.settings.flac_art_root or ""))
        self.edit_art_root.setPlaceholderText("Root directory for extracted artwork")
        self.btn_art_root = QtWidgets.QPushButton("Browse…")
        self.btn_art_root.clicked.connect(self._browse_art_root)
        art_root_row = QtWidgets.QHBoxLayout()
        art_root_row.addWidget(self.edit_art_root)
        art_root_row.addWidget(self.btn_art_root)
        art_layout.addRow("Art Root:", art_root_row)
        
        self.edit_art_pattern = QtWidgets.QLineEdit()
        self.edit_art_pattern.setText(self.settings.flac_art_pattern or "")
        self.edit_art_pattern.setPlaceholderText("{albumartist}/{album}/front.jpg")
        art_layout.addRow("Art Pattern:", self.edit_art_pattern)
        
        tabs.addTab(art_tab, "Artwork")
        
        # Workers tab
        workers_tab = QtWidgets.QWidget()
        workers_layout = QtWidgets.QFormLayout(workers_tab)
        
        max_threads = max(1, QtCore.QThread.idealThreadCount() or 8)
        
        self.spin_flac_workers = QtWidgets.QSpinBox()
        self.spin_flac_workers.setRange(1, max_threads)
        self.spin_flac_workers.setValue(self.settings.flac_workers or max(1, max_threads // 2))
        workers_layout.addRow("FLAC Workers:", self.spin_flac_workers)
        
        self.spin_analysis_workers = QtWidgets.QSpinBox()
        self.spin_analysis_workers.setRange(1, max_threads)
        self.spin_analysis_workers.setValue(self.settings.flac_analysis_workers or max_threads)
        workers_layout.addRow("Analysis Workers:", self.spin_analysis_workers)
        
        self.spin_art_workers = QtWidgets.QSpinBox()
        self.spin_art_workers.setRange(1, max_threads)
        self.spin_art_workers.setValue(self.settings.flac_art_workers or min(4, max_threads))
        workers_layout.addRow("Art Workers:", self.spin_art_workers)
        
        tabs.addTab(workers_tab, "Workers")
        
        # Dialog buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _browse_art_root(self) -> None:
        start = self.edit_art_root.text() or str(Path.home())
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Art Root", start)
        if d:
            self.edit_art_root.setText(d)
    
    def get_values(self) -> dict:
        """Return the current settings values."""
        return {
            "flac_target_compression": self.spin_compression.value(),
            "flac_resample_to_cd": self.chk_resample.isChecked(),
            "lossy_mirror_codec": self.combo_mirror_codec.currentText(),
            "flac_art_root": self.edit_art_root.text().strip() or None,
            "flac_art_pattern": self.edit_art_pattern.text().strip() or None,
            "flac_workers": self.spin_flac_workers.value(),
            "flac_analysis_workers": self.spin_analysis_workers.value(),
            "flac_art_workers": self.spin_art_workers.value(),
        }


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        *,
        flac_library: Optional[str] = None,
        mirror_library: Optional[str] = None,
        source: Optional[str] = None,
        output: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Python Audio Converter")
        self.resize(1000, 700)
        
        # Store CLI arguments for later population
        self._init_flac_library = flac_library
        self._init_mirror_library = mirror_library
        self._init_source = source
        self._init_output = output

        self._ui_settings = QtCore.QSettings("python-audio-converter", "gui")
        self._log_collapsed = bool(self._ui_settings.value("log_collapsed", False, type=bool))
        self._log_last_sizes: Optional[list[int]] = None

        # Load defaults
        self.settings = PacSettings.load()
        # Encoder selected by preflight: one of None, "libfdk_aac", "qaac", "fdkaac"
        self.selected_encoder: Optional[str] = None

        # Central layout with tabs
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        outer.addWidget(self.main_splitter, 1)

        top = QtWidgets.QWidget()
        top_outer = QtWidgets.QVBoxLayout(top)
        top_outer.setContentsMargins(0, 0, 0, 0)
        top_outer.setSpacing(0)

        # Create tab widget
        self.tabs = QtWidgets.QTabWidget()
        top_outer.addWidget(self.tabs, 1)

        # Library tab (main tab)
        self.library_tab = QtWidgets.QWidget()
        self.tabs.addTab(self.library_tab, "Library")
        self._setup_library_tab()

        # Convert tab
        self.convert_tab = QtWidgets.QWidget()
        self.tabs.addTab(self.convert_tab, "Convert")
        self._setup_convert_tab()

        # Shared components
        self._setup_shared_components(top_outer)

        self._setup_log_panel()

        self.main_splitter.addWidget(top)
        self.main_splitter.addWidget(self.log)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, True)

        saved_sizes = self._ui_settings.value("main_splitter_sizes", None)
        if isinstance(saved_sizes, list) and all(isinstance(x, int) for x in saved_sizes) and len(saved_sizes) == 2:
            self.main_splitter.setSizes(saved_sizes)
            self._log_last_sizes = saved_sizes
        else:
            self.main_splitter.setSizes([750, 200])
            self._log_last_sizes = [750, 200]

        if self._log_collapsed:
            self._collapse_log(store_size=False)

        # Connections
        self.btn_recheck_encoders.clicked.connect(self.on_preflight)
        self.btn_src.clicked.connect(lambda: self._pick_dir(self.edit_src))
        self.btn_dest.clicked.connect(lambda: self._pick_dir(self.edit_dest))
        self.btn_plan.clicked.connect(self.on_plan)
        self.btn_convert.clicked.connect(self.on_convert)
        self.btn_cancel.clicked.connect(self.on_cancel)
        self.btn_pause.clicked.connect(self.on_pause_resume)
        self.combo_codec.currentTextChanged.connect(self._on_codec_change)

        # Logger → UI
        self.log_emitter = LogEmitter()
        self.log_emitter.message.connect(self.append_log)
        setup_logger_for_gui(self.log_emitter, level=self.settings.log_level, json_path=self.settings.log_json)

        # Populate path fields from CLI arguments
        self._populate_cli_paths()

        # Auto-run preflight on startup (after event loop starts)
        QtCore.QTimer.singleShot(100, self._auto_preflight)

    def _setup_convert_tab(self) -> None:
        """Setup the convert tab with existing functionality."""
        layout = QtWidgets.QVBoxLayout(self.convert_tab)

        # I/O selectors
        form = QtWidgets.QFormLayout()
        self.edit_src = DropLineEdit()
        self.edit_src.setPlaceholderText("Source directory with .flac files")
        self.btn_src = QtWidgets.QPushButton("Browse…")
        src_row = QtWidgets.QHBoxLayout()
        src_row.addWidget(self.edit_src)
        src_row.addWidget(self.btn_src)
        form.addRow("Source:", self._wrap_row(src_row))

        self.edit_dest = DropLineEdit()
        self.edit_dest.setPlaceholderText("Destination root for outputs")
        self.btn_dest = QtWidgets.QPushButton("Browse…")
        dest_row = QtWidgets.QHBoxLayout()
        dest_row.addWidget(self.edit_dest)
        dest_row.addWidget(self.btn_dest)
        form.addRow("Destination:", self._wrap_row(dest_row))

        # Settings row
        self.combo_codec = QtWidgets.QComboBox()
        self.combo_codec.addItems(["aac", "opus"])
        self.combo_codec.setCurrentText(self.settings.codec)

        self.spin_workers = QtWidgets.QSpinBox()
        self.spin_workers.setRange(1, max(1, (QtCore.QThread.idealThreadCount() or 8)))
        self.spin_workers.setValue(self.settings.workers or (QtCore.QThread.idealThreadCount() or 4))

        self.spin_tvbr = QtWidgets.QSpinBox()
        self.spin_tvbr.setRange(0, 127)
        self.spin_tvbr.setValue(self.settings.tvbr)
        self.spin_tvbr.setToolTip("Used for AAC encode with qaac (tvbr scale, ~256 kbps at ~96)")

        self.spin_vbr = QtWidgets.QSpinBox()
        self.spin_vbr.setRange(1, 5)
        self.spin_vbr.setValue(self.settings.vbr)
        self.spin_vbr.setToolTip("Used for AAC encode with libfdk_aac or fdkaac (1..5; 5 ~ 256 kbps)")

        self.spin_opus_vbr = QtWidgets.QSpinBox()
        self.spin_opus_vbr.setRange(32, 512)
        self.spin_opus_vbr.setValue(self.settings.opus_vbr_kbps)
        self.spin_opus_vbr.setToolTip("Used for Opus encode (VBR bitrate in kbps)")

        self.chk_verify = QtWidgets.QCheckBox("Verify tags after encode")
        self.chk_verify.setChecked(self.settings.verify_tags)
        self.chk_verify_strict = QtWidgets.QCheckBox("Strict verification (fail on mismatch)")
        self.chk_verify_strict.setChecked(self.settings.verify_strict)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Codec"), 0, 0)
        grid.addWidget(self.combo_codec, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Workers"), 0, 2)
        grid.addWidget(self.spin_workers, 0, 3)

        grid.addWidget(QtWidgets.QLabel("AAC (qaac) tvbr"), 1, 0)
        grid.addWidget(self.spin_tvbr, 1, 1)
        grid.addWidget(QtWidgets.QLabel("AAC (libfdk) vbr"), 1, 2)
        grid.addWidget(self.spin_vbr, 1, 3)
        grid.addWidget(QtWidgets.QLabel("Opus vbr (kbps)"), 1, 4)
        grid.addWidget(self.spin_opus_vbr, 1, 5)

        grid.addWidget(self.chk_verify, 2, 3, 1, 2)
        grid.addWidget(self.chk_verify_strict, 2, 5, 1, 1)

        # New stateless planner flags
        self.chk_rename = QtWidgets.QCheckBox("Rename moved files")
        self.chk_rename.setChecked(True)
        self.chk_retag = QtWidgets.QCheckBox("Retag existing files")
        self.chk_retag.setChecked(True)
        self.chk_prune = QtWidgets.QCheckBox("Prune orphans (deletes files)")
        self.chk_prune.setChecked(False)
        self.chk_force = QtWidgets.QCheckBox("Force re-encode all")
        self.chk_force.setChecked(False)
        self.chk_no_adopt = QtWidgets.QCheckBox("Do not adopt legacy files")
        self.chk_no_adopt.setChecked(False)
        self.chk_sync_tags = QtWidgets.QCheckBox("Sync tags")
        self.chk_sync_tags.setChecked(False)

        self.chk_cover_resize = QtWidgets.QCheckBox("Resize cover art")
        self.chk_cover_resize.setChecked(self.settings.cover_art_resize)
        self.spin_cover_max_size = QtWidgets.QSpinBox()
        self.spin_cover_max_size.setRange(300, 4000)
        self.spin_cover_max_size.setValue(self.settings.cover_art_max_size)
        self.spin_cover_max_size.setToolTip("Max dimension for cover art (px)")

        grid.addWidget(self.chk_rename, 3, 0, 1, 2)
        grid.addWidget(self.chk_retag, 3, 2, 1, 2)
        grid.addWidget(self.chk_prune, 3, 4, 1, 2)
        grid.addWidget(self.chk_force, 4, 0, 1, 2)
        grid.addWidget(self.chk_no_adopt, 4, 2, 1, 2)
        grid.addWidget(self.chk_sync_tags, 4, 4, 1, 2)

        grid.addWidget(self.chk_cover_resize, 5, 0, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Max size:"), 5, 2)
        grid.addWidget(self.spin_cover_max_size, 5, 3)

        form.addRow("Settings:", self._wrap_row(grid))

        # Encoder/quality hint labels
        self.lbl_encoder_status = QtWidgets.QLabel("Encoder: unknown")
        self.lbl_quality_hint = QtWidgets.QLabel("Quality used: (depends on encoder)")
        form.addRow("Encoder:", self.lbl_encoder_status)
        form.addRow("Quality used:", self.lbl_quality_hint)
        layout.addLayout(form)

        # Plan summary
        self.plan_group = QtWidgets.QGroupBox("Plan Summary")
        plan_layout = QtWidgets.QHBoxLayout()
        self.lbl_plan_convert = QtWidgets.QLabel("Convert: 0")
        self.lbl_plan_skip = QtWidgets.QLabel("Skip: 0")
        self.lbl_plan_retag = QtWidgets.QLabel("Retag: 0")
        self.lbl_plan_rename = QtWidgets.QLabel("Rename: 0")
        self.lbl_plan_prune = QtWidgets.QLabel("Prune: 0")
        self.lbl_plan_sync_tags = QtWidgets.QLabel("Sync Tags: 0")
        plan_layout.addWidget(self.lbl_plan_convert)
        plan_layout.addWidget(self.lbl_plan_skip)
        plan_layout.addWidget(self.lbl_plan_retag)
        plan_layout.addWidget(self.lbl_plan_rename)
        plan_layout.addWidget(self.lbl_plan_prune)
        plan_layout.addWidget(self.lbl_plan_sync_tags)
        self.plan_group.setLayout(plan_layout)
        self.plan_group.hide()
        layout.addWidget(self.plan_group)

        # Action buttons
        actions = QtWidgets.QHBoxLayout()
        self.btn_plan = QtWidgets.QPushButton("Plan (Dry‑Run)")
        self.btn_convert = QtWidgets.QPushButton("Convert")
        self.btn_convert.setDefault(True)
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.hide()
        self.btn_pause = QtWidgets.QPushButton("Pause")
        self.btn_pause.hide()

        actions.addStretch(1)
        actions.addWidget(self.btn_plan)
        actions.addWidget(self.btn_convert)
        actions.addWidget(self.btn_pause)
        actions.addWidget(self.btn_cancel)
        layout.addLayout(actions)

    @staticmethod
    def _wrap_row(w: QtWidgets.QLayout | QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        if isinstance(w, QtWidgets.QLayout):
            box.setLayout(w)
        else:
            lay = QtWidgets.QHBoxLayout()
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(w)
            box.setLayout(lay)
        return box

    def _populate_cli_paths(self) -> None:
        """Populate path fields from CLI arguments provided at startup."""
        if self._init_flac_library:
            self.edit_lib_root.setText(self._init_flac_library)
        if self._init_mirror_library:
            self.edit_mirror_out.setText(self._init_mirror_library)
        if self._init_source:
            self.edit_src.setText(self._init_source)
        if self._init_output:
            self.edit_dest.setText(self._init_output)

    def _setup_library_tab(self) -> None:
        """Setup the library management tab with browser-first layout."""
        layout = QtWidgets.QVBoxLayout(self.library_tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # === TOP BAR: Library paths + Settings button ===
        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setSpacing(8)
        
        # Library root
        top_bar.addWidget(QtWidgets.QLabel("Library:"))
        self.edit_lib_root = DropLineEdit()
        self.edit_lib_root.setPlaceholderText("FLAC library root")
        self.btn_lib_root = QtWidgets.QPushButton("…")
        self.btn_lib_root.setFixedWidth(30)
        top_bar.addWidget(self.edit_lib_root, 2)
        top_bar.addWidget(self.btn_lib_root)
        
        # Mirror output
        top_bar.addWidget(QtWidgets.QLabel("Mirror:"))
        self.edit_mirror_out = DropLineEdit()
        self.edit_mirror_out.setPlaceholderText("Optional output dir")
        self.btn_mirror_out = QtWidgets.QPushButton("…")
        self.btn_mirror_out.setFixedWidth(30)
        top_bar.addWidget(self.edit_mirror_out, 1)
        top_bar.addWidget(self.btn_mirror_out)
        
        # Settings button
        self.btn_lib_settings = QtWidgets.QPushButton("Settings…")
        self.btn_lib_settings.setToolTip("Open library settings dialog")
        top_bar.addWidget(self.btn_lib_settings)
        
        layout.addLayout(top_bar)

        # === MAIN AREA: Horizontal splitter (operations panel + browser) ===
        self.lib_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        
        # --- LEFT: Compact operations panel ---
        ops_widget = QtWidgets.QWidget()
        ops_widget.setMaximumWidth(220)
        ops_widget.setMinimumWidth(160)
        ops_layout = QtWidgets.QVBoxLayout(ops_widget)
        ops_layout.setContentsMargins(0, 0, 0, 0)
        ops_layout.setSpacing(4)
        
        # Operations header
        ops_header = QtWidgets.QLabel("<b>Operations</b>")
        ops_layout.addWidget(ops_header)
        
        # Dry run toggle
        self.chk_lib_dry_run = QtWidgets.QCheckBox("Dry Run")
        self.chk_lib_dry_run.setChecked(False)
        self.chk_lib_dry_run.setToolTip("Plan only, no changes")
        ops_layout.addWidget(self.chk_lib_dry_run)
        
        # Operation checkboxes (compact, no individual run buttons)
        self.chk_op_integrity = QtWidgets.QCheckBox("Integrity Check")
        self.chk_op_integrity.setChecked(True)
        self.chk_op_integrity.setToolTip("Test FLAC files for corruption")
        ops_layout.addWidget(self.chk_op_integrity)
        
        self.chk_op_resample = QtWidgets.QCheckBox("Resample to CD")
        self.chk_op_resample.setChecked(self.settings.flac_resample_to_cd)
        self.chk_op_resample.setToolTip("Resample hi-res to 16-bit/44.1kHz")
        ops_layout.addWidget(self.chk_op_resample)
        
        self.chk_op_recompress = QtWidgets.QCheckBox("Recompress FLAC")
        self.chk_op_recompress.setChecked(True)
        self.chk_op_recompress.setToolTip("Recompress to target level")
        ops_layout.addWidget(self.chk_op_recompress)
        
        self.chk_op_artwork = QtWidgets.QCheckBox("Extract Artwork")
        self.chk_op_artwork.setChecked(True)
        self.chk_op_artwork.setToolTip("Extract embedded artwork")
        ops_layout.addWidget(self.chk_op_artwork)
        
        self.chk_op_adopt = QtWidgets.QCheckBox("Adopt Legacy")
        self.chk_op_adopt.setChecked(False)
        self.chk_op_adopt.setToolTip("Add PAC_* tags to outputs (requires Mirror)")
        self.lbl_adoptable_count = QtWidgets.QLabel("")
        adopt_row = QtWidgets.QHBoxLayout()
        adopt_row.addWidget(self.chk_op_adopt)
        adopt_row.addWidget(self.lbl_adoptable_count)
        adopt_row.addStretch()
        ops_layout.addLayout(adopt_row)
        
        self.chk_op_mirror = QtWidgets.QCheckBox("Update Mirror")
        self.chk_op_mirror.setChecked(False)
        self.chk_op_mirror.setToolTip("Update lossy mirror (requires Mirror)")
        ops_layout.addWidget(self.chk_op_mirror)
        
        ops_layout.addSpacing(8)
        
        # Scope control
        scope_label = QtWidgets.QLabel("<b>Scope</b>")
        ops_layout.addWidget(scope_label)
        
        self.radio_scope_library = QtWidgets.QRadioButton("Entire Library")
        self.radio_scope_library.setChecked(True)
        self.radio_scope_selection = QtWidgets.QRadioButton("Selection Only")
        self.radio_scope_selection.setToolTip("Run on selected files in browser")
        ops_layout.addWidget(self.radio_scope_library)
        ops_layout.addWidget(self.radio_scope_selection)
        
        ops_layout.addStretch()
        
        # Run button
        self.btn_lib_run = QtWidgets.QPushButton("Run")
        self.btn_lib_run.setToolTip("Run checked operations")
        self.btn_lib_run.setMinimumHeight(32)
        ops_layout.addWidget(self.btn_lib_run)
        
        # Pause/Cancel (hidden by default)
        self.btn_lib_pause = QtWidgets.QPushButton("Pause")
        self.btn_lib_pause.hide()
        ops_layout.addWidget(self.btn_lib_pause)
        self.btn_lib_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_lib_cancel.hide()
        ops_layout.addWidget(self.btn_lib_cancel)
        
        self.lib_splitter.addWidget(ops_widget)
        
        # --- RIGHT: Browser panel (primary workspace) ---
        browser_widget = QtWidgets.QWidget()
        browser_layout = QtWidgets.QVBoxLayout(browser_widget)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(4)
        
        # Statistics bar (compact, clickable to filter)
        stats_bar = QtWidgets.QHBoxLayout()
        stats_bar.setSpacing(2)
        self.btn_stat_total = QtWidgets.QPushButton("Total: 0")
        self.btn_stat_total.setFlat(True)
        self.btn_stat_total.setToolTip("Show all files")
        self.btn_stat_hires = QtWidgets.QPushButton("Hi-Res: 0")
        self.btn_stat_hires.setFlat(True)
        self.btn_stat_hires.setToolTip("Filter hi-res files")
        self.btn_stat_integrity_unknown = QtWidgets.QPushButton("Untested: 0")
        self.btn_stat_integrity_unknown.setFlat(True)
        self.btn_stat_integrity_failed = QtWidgets.QPushButton("Failed: 0")
        self.btn_stat_integrity_failed.setFlat(True)
        self.btn_stat_integrity_failed.setStyleSheet("color: red;")
        self.btn_stat_needs_recompress = QtWidgets.QPushButton("Recompress: 0")
        self.btn_stat_needs_recompress.setFlat(True)
        self.btn_stat_legacy = QtWidgets.QPushButton("Legacy: 0")
        self.btn_stat_legacy.setFlat(True)
        
        stats_bar.addWidget(self.btn_stat_total)
        stats_bar.addWidget(self.btn_stat_hires)
        stats_bar.addWidget(self.btn_stat_integrity_unknown)
        stats_bar.addWidget(self.btn_stat_integrity_failed)
        stats_bar.addWidget(self.btn_stat_needs_recompress)
        stats_bar.addWidget(self.btn_stat_legacy)
        stats_bar.addStretch(1)
        browser_layout.addLayout(stats_bar)
        
        # View mode + Filter + Scan row
        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(QtWidgets.QLabel("View:"))
        self.combo_view_mode = QtWidgets.QComboBox()
        self.combo_view_mode.addItems(["Source Only", "With Outputs", "Outputs Only"])
        self.combo_view_mode.setToolTip("Source Only: FLAC library\nWith Outputs: Correlated view\nOutputs Only: Mirror directory")
        filter_row.addWidget(self.combo_view_mode)
        
        filter_row.addWidget(QtWidgets.QLabel("Filter:"))
        self.combo_browser_filter = QtWidgets.QComboBox()
        self.combo_browser_filter.addItems([
            "All Files", "Needs Action", "Hi-Res Only",
            "Integrity Unknown", "Integrity Failed",
            "Needs Recompress", "Legacy (No PAC tags)",
        ])
        filter_row.addWidget(self.combo_browser_filter)
        self.btn_browser_clear_filter = QtWidgets.QPushButton("Clear")
        self.btn_browser_clear_filter.setFixedWidth(50)
        filter_row.addWidget(self.btn_browser_clear_filter)
        filter_row.addStretch(1)
        self.btn_browser_scan = QtWidgets.QPushButton("Rescan")
        self.btn_browser_scan.setToolTip("Rescan library (non-destructive)")
        filter_row.addWidget(self.btn_browser_scan)
        browser_layout.addLayout(filter_row)
        
        # Table view (primary workspace)
        self.browser_table = QtWidgets.QTableView()
        self.browser_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.browser_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.browser_table.setSortingEnabled(True)
        self.browser_table.setAlternatingRowColors(True)
        self.browser_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.browser_table.horizontalHeader().setStretchLastSection(True)
        self.browser_table.verticalHeader().setVisible(False)
        
        self.browser_model = LibraryTableModel(self)
        self.correlated_model = CorrelatedTableModel(self)
        self.browser_proxy_model = QtCore.QSortFilterProxyModel(self)
        self.browser_proxy_model.setSourceModel(self.browser_model)
        self.browser_table.setModel(self.browser_proxy_model)
        
        # Track current view mode
        self._current_view_mode = "Source Only"
        
        browser_layout.addWidget(self.browser_table, 1)
        
        # Selection info row
        selection_row = QtWidgets.QHBoxLayout()
        self.lbl_browser_selection = QtWidgets.QLabel("Selected: 0 files")
        selection_row.addWidget(self.lbl_browser_selection)
        selection_row.addStretch(1)
        self.btn_browser_run_integrity = QtWidgets.QPushButton("Run Integrity")
        self.btn_browser_run_integrity.setEnabled(False)
        self.btn_browser_run_adopt = QtWidgets.QPushButton("Adopt Selected")
        self.btn_browser_run_adopt.setEnabled(False)
        selection_row.addWidget(self.btn_browser_run_integrity)
        selection_row.addWidget(self.btn_browser_run_adopt)
        browser_layout.addLayout(selection_row)
        
        self.lib_splitter.addWidget(browser_widget)
        
        # Set splitter sizes (operations panel narrow, browser wide)
        self.lib_splitter.setSizes([180, 600])
        self.lib_splitter.setStretchFactor(0, 0)
        self.lib_splitter.setStretchFactor(1, 1)
        
        layout.addWidget(self.lib_splitter, 1)

        # === COLLAPSIBLE DETAILS AREA ===
        self.details_toggle = QtWidgets.QPushButton("▶ Details")
        self.details_toggle.setFlat(True)
        self.details_toggle.setCheckable(True)
        self.details_toggle.setChecked(False)
        self.details_toggle.setToolTip("Show/hide operation details and issues")
        layout.addWidget(self.details_toggle)
        
        self.details_widget = QtWidgets.QWidget()
        self.details_widget.setVisible(False)
        details_layout = QtWidgets.QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        
        # Status counters
        self.counters_group = QtWidgets.QGroupBox("Status")
        counters_layout = QtWidgets.QVBoxLayout(self.counters_group)
        
        status_grid = QtWidgets.QGridLayout()
        self.lbl_lib_scanned = QtWidgets.QLabel("Scanned: 0")
        self.lbl_lib_tested_ok = QtWidgets.QLabel("Integrity OK: 0")
        self.lbl_lib_tested_err = QtWidgets.QLabel("Integrity Failed: 0")
        self.lbl_lib_resampled = QtWidgets.QLabel("Resampled: 0")
        self.lbl_lib_recompressed = QtWidgets.QLabel("Recompressed: 0")
        self.lbl_lib_art_exported = QtWidgets.QLabel("Art Exported: 0")
        self.lbl_lib_adopted = QtWidgets.QLabel("Adopted: 0")
        self.lbl_lib_held = QtWidgets.QLabel("Held: 0")
        
        status_grid.addWidget(self.lbl_lib_scanned, 0, 0)
        status_grid.addWidget(self.lbl_lib_tested_ok, 0, 1)
        status_grid.addWidget(self.lbl_lib_tested_err, 0, 2)
        status_grid.addWidget(self.lbl_lib_resampled, 0, 3)
        status_grid.addWidget(self.lbl_lib_recompressed, 1, 0)
        status_grid.addWidget(self.lbl_lib_art_exported, 1, 1)
        status_grid.addWidget(self.lbl_lib_adopted, 1, 2)
        status_grid.addWidget(self.lbl_lib_held, 1, 3)
        counters_layout.addLayout(status_grid)
        
        self.lbl_lib_current_op = QtWidgets.QLabel("")
        counters_layout.addWidget(self.lbl_lib_current_op)
        
        details_layout.addWidget(self.counters_group)
        
        # Issues list
        issues_group = QtWidgets.QGroupBox("Issues")
        issues_layout = QtWidgets.QVBoxLayout(issues_group)
        self.lib_issues_list = QtWidgets.QListWidget()
        self.lib_issues_list.setMaximumHeight(80)
        issues_layout.addWidget(self.lib_issues_list)
        details_layout.addWidget(issues_group)
        
        layout.addWidget(self.details_widget)

        # === AUTO-SCAN SETUP ===
        # Debounce timer for path validation
        self._lib_path_debounce_timer = QtCore.QTimer(self)
        self._lib_path_debounce_timer.setSingleShot(True)
        self._lib_path_debounce_timer.setInterval(400)  # 400ms debounce
        self._lib_path_debounce_timer.timeout.connect(self._on_lib_path_debounce_timeout)
        
        # Track last validated path to avoid redundant scans
        self._last_scanned_lib_path = ""
        
        # === CONNECT SIGNALS ===
        # Top bar
        self.btn_lib_root.clicked.connect(self._on_lib_root_browse)
        self.edit_lib_root.textChanged.connect(self._on_lib_path_changed)
        self.btn_mirror_out.clicked.connect(lambda: self._pick_dir(self.edit_mirror_out))
        self.btn_lib_settings.clicked.connect(self._on_lib_settings)
        
        # Operations
        self.btn_lib_run.clicked.connect(self.on_lib_run)
        self.btn_lib_cancel.clicked.connect(self.on_lib_cancel)
        self.btn_lib_pause.clicked.connect(self.on_lib_pause_resume)
        self.edit_mirror_out.textChanged.connect(self._update_mirror_dependent_ops)
        
        # Browser
        self.btn_browser_scan.clicked.connect(self.on_browser_scan)
        self.combo_view_mode.currentTextChanged.connect(self._on_view_mode_change)
        self.combo_browser_filter.currentTextChanged.connect(self._on_browser_filter_change)
        self.btn_browser_clear_filter.clicked.connect(self._on_browser_clear_filter)
        self.browser_table.selectionModel().selectionChanged.connect(self._on_browser_selection_changed)
        self.browser_table.customContextMenuRequested.connect(self._on_browser_context_menu)
        
        # Stats buttons to filters
        self.btn_stat_total.clicked.connect(lambda: self.combo_browser_filter.setCurrentText("All Files"))
        self.btn_stat_hires.clicked.connect(lambda: self.combo_browser_filter.setCurrentText("Hi-Res Only"))
        self.btn_stat_integrity_unknown.clicked.connect(lambda: self.combo_browser_filter.setCurrentText("Integrity Unknown"))
        self.btn_stat_integrity_failed.clicked.connect(lambda: self.combo_browser_filter.setCurrentText("Integrity Failed"))
        self.btn_stat_needs_recompress.clicked.connect(lambda: self.combo_browser_filter.setCurrentText("Needs Recompress"))
        self.btn_stat_legacy.clicked.connect(lambda: self.combo_browser_filter.setCurrentText("Legacy (No PAC tags)"))
        
        # Selection actions
        self.btn_browser_run_integrity.clicked.connect(self._on_browser_run_integrity)
        self.btn_browser_run_adopt.clicked.connect(self._on_browser_run_adopt)
        
        # Details toggle
        self.details_toggle.toggled.connect(self._on_details_toggle)
        
        # Update scope when selection changes
        self.browser_table.selectionModel().selectionChanged.connect(self._on_selection_scope_update)

    def _on_lib_settings(self) -> None:
        """Open library settings modal dialog."""
        dialog = LibrarySettingsDialog(self.settings, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            values = dialog.get_values()
            self._lib_settings_cache = values
            logger.info("Library settings updated")
    
    def _on_details_toggle(self, checked: bool) -> None:
        """Toggle details panel visibility."""
        self.details_widget.setVisible(checked)
        self.details_toggle.setText("▼ Details" if checked else "▶ Details")
    
    def _on_selection_scope_update(self) -> None:
        """Update scope radio when selection changes."""
        indexes = self.browser_table.selectionModel().selectedRows()
        if len(indexes) > 0:
            self.radio_scope_selection.setChecked(True)
    
    def _get_lib_settings_overrides(self) -> dict:
        """Get library settings from cache or defaults."""
        if hasattr(self, "_lib_settings_cache"):
            return self._lib_settings_cache
        return {
            "flac_target_compression": self.settings.flac_target_compression,
            "flac_resample_to_cd": self.chk_op_resample.isChecked(),
            "lossy_mirror_codec": self.settings.lossy_mirror_codec or "aac",
            "flac_art_root": self.settings.flac_art_root,
            "flac_art_pattern": self.settings.flac_art_pattern,
            "flac_workers": self.settings.flac_workers,
            "flac_analysis_workers": self.settings.flac_analysis_workers,
            "flac_art_workers": self.settings.flac_art_workers,
        }

    def _update_mirror_dependent_ops(self) -> None:
        """Enable/disable adopt and mirror operations based on mirror output path."""
        has_mirror = bool(self.edit_mirror_out.text().strip())
        self.chk_op_adopt.setEnabled(has_mirror)
        self.chk_op_mirror.setEnabled(has_mirror)
        if not has_mirror:
            self.chk_op_adopt.setChecked(False)
            self.chk_op_mirror.setChecked(False)

    def _get_selected_phases(self) -> set:
        """Get the set of phases selected by checkboxes."""
        phases = set()
        # Always include scan for other FLAC operations
        if self.chk_op_integrity.isChecked():
            phases.add(PHASE_INTEGRITY)
        if self.chk_op_resample.isChecked():
            phases.add(PHASE_RESAMPLE)
        if self.chk_op_recompress.isChecked():
            phases.add(PHASE_RECOMPRESS)
        if self.chk_op_artwork.isChecked():
            phases.add(PHASE_ARTWORK)
        if self.chk_op_adopt.isChecked():
            phases.add(PHASE_ADOPT)
        if self.chk_op_mirror.isChecked():
            phases.add(PHASE_MIRROR)
        return phases

    def _run_single_op(self, phase: str) -> None:
        """Run a single operation."""
        self.log.clear()
        self.counters_group.hide()
        self.lib_issues_list.clear()
        
        # For adopt, use AdoptWorker directly
        if phase == PHASE_ADOPT:
            self._start_adopt_operation()
        else:
            self._start_lib_operation(
                dry_run=self.chk_lib_dry_run.isChecked(),
                phases={phase}
            )

    def on_scan_adoptable(self) -> None:
        """Scan for adoptable files and show count."""
        mirror_out = self.edit_mirror_out.text().strip()
        if not mirror_out or not Path(mirror_out).exists():
            QtWidgets.QMessageBox.warning(
                self, "Missing Mirror Output",
                "Please select a valid mirror output directory to scan for adoptable files"
            )
            return
        
        logger.info(f"Scanning for adoptable files in {mirror_out}")
        adoptable = scan_adoptable_files(Path(mirror_out))
        count = len(adoptable)
        self.lbl_adoptable_count.setText(f"({count} found)")
        
        if count > 0:
            logger.info(f"Found {count} adoptable files without PAC_* tags")
        else:
            logger.info("No adoptable files found")

    def on_lib_run(self) -> None:
        """Run selected library operations."""
        self.log.clear()
        self.counters_group.hide()
        self.lib_issues_list.clear()
        
        phases = self._get_selected_phases()
        if not phases:
            QtWidgets.QMessageBox.warning(
                self, "No Operations Selected",
                "Please select at least one operation to run"
            )
            return
        
        # Handle adopt separately if it's the only phase
        if phases == {PHASE_ADOPT}:
            self._start_adopt_operation()
        else:
            # Remove adopt from phases - it's handled separately
            lib_phases = phases - {PHASE_ADOPT}
            if lib_phases:
                self._start_lib_operation(
                    dry_run=self.chk_lib_dry_run.isChecked(),
                    phases=lib_phases
                )

    def on_lib_cancel(self) -> None:
        """Cancel library operation."""
        logger.warning("Cancel requested by user.")
        if hasattr(self, "lib_worker") and self.lib_worker.isRunning():
            self.lib_worker.cancel()
        if hasattr(self, "adopt_worker") and self.adopt_worker.isRunning():
            self.adopt_worker.cancel()
        self.btn_lib_cancel.setEnabled(False)
        self.btn_lib_pause.setEnabled(False)

    def on_lib_pause_resume(self) -> None:
        """Pause/resume library operation."""
        worker = None
        if hasattr(self, "lib_worker") and self.lib_worker.isRunning():
            worker = self.lib_worker
        elif hasattr(self, "adopt_worker") and self.adopt_worker.isRunning():
            worker = self.adopt_worker
        
        if worker:
            worker.toggle_pause()
            if self.btn_lib_pause.text() == "Pause":
                logger.info("Pausing...")
                self.btn_lib_pause.setText("Resume")
            else:
                logger.info("Resuming...")
                self.btn_lib_pause.setText("Pause")

    def _start_adopt_operation(self) -> None:
        """Start adopt legacy files operation."""
        lib_root = self.edit_lib_root.text().strip()
        mirror_out = self.edit_mirror_out.text().strip()
        
        if not lib_root or not Path(lib_root).exists():
            QtWidgets.QMessageBox.warning(
                self, "Missing Library Root",
                "Please select a valid FLAC library root directory"
            )
            return
        
        if not mirror_out or not Path(mirror_out).exists():
            QtWidgets.QMessageBox.warning(
                self, "Missing Mirror Output",
                "Please select a valid mirror output directory for adopting files"
            )
            return
        
        # Disable UI during run
        self._disable_lib_ui()
        
        # Start adopt worker
        self.adopt_worker = AdoptWorker(
            cfg=self.settings,
            output_dir=mirror_out,
            source_dir=lib_root,
            dry_run=self.chk_lib_dry_run.isChecked(),
        )
        self.adopt_worker.summary_ready.connect(self._on_adopt_summary_ready)
        self.adopt_worker.progress_update.connect(self._on_lib_progress_update)
        self.adopt_worker.finished_with_code.connect(self._on_lib_done)
        self.adopt_worker.finished.connect(self._reenable_lib_ui)
        self.adopt_worker.start()

    def _start_lib_operation(self, *, dry_run: bool, phases: Optional[set] = None) -> None:
        """Start library operation with specified phases."""
        lib_root = self.edit_lib_root.text().strip()
        if not lib_root or not Path(lib_root).exists():
            QtWidgets.QMessageBox.warning(self, "Missing Library Root", "Please select a valid FLAC library root directory")
            return

        mirror_out = self.edit_mirror_out.text().strip() if self.edit_mirror_out.text().strip() else None

        # Determine scope: gather selected file paths if "Selection Only" is chosen
        only_rel_paths = None
        if self.radio_scope_selection.isChecked():
            indexes = self.browser_table.selectionModel().selectedRows()
            if not indexes:
                QtWidgets.QMessageBox.warning(
                    self, "No Selection",
                    "Please select files in the browser, or switch scope to 'Entire Library'."
                )
                return
            only_rel_paths = []
            for idx in indexes:
                source_idx = self.browser_proxy_model.mapToSource(idx)
                f = self.browser_model.get_file_at(source_idx.row())
                if f:
                    only_rel_paths.append(str(f.rel_path))
            logger.info(f"Running on selection: {len(only_rel_paths)} files")

        # Update settings with library-specific values from modal dialog cache
        lib_overrides = self._get_lib_settings_overrides()

        # Apply overrides to settings
        lib_settings = self.settings.model_copy(update=lib_overrides)

        # Disable UI during run
        self._disable_lib_ui()

        # Start library worker
        self.lib_worker = LibraryWorker(
            cfg=lib_settings,
            root=lib_root,
            mirror_out=mirror_out,
            dry_run=dry_run,
            phases=phases,
            only_rel_paths=only_rel_paths,
        )
        self.lib_worker.summary_ready.connect(self._on_lib_summary_ready)
        self.lib_worker.progress_update.connect(self._on_lib_progress_update)
        self.lib_worker.finished_with_code.connect(self._on_lib_done)
        self.lib_worker.finished.connect(self._reenable_lib_ui)
        self.lib_worker.start()

    def _on_lib_progress_update(self, phase: str, current: int, total: int) -> None:
        """Handle progress updates from library worker."""
        if total > 0:
            self.lbl_lib_current_op.setText(f"{phase}: {current}/{total}")
        else:
            self.lbl_lib_current_op.setText(f"{phase}: scanning...")

    def _on_lib_summary_ready(self, summary: dict) -> None:
        """Update UI with library summary."""
        self.counters_group.show()
        self.lbl_lib_current_op.setText("")

        # Update counters
        self.lbl_lib_scanned.setText(f"Scanned: {summary.get('scanned', 0)}")
        self.lbl_lib_tested_ok.setText(f"Integrity OK: {summary.get('integrity_ok', 0)}")
        self.lbl_lib_tested_err.setText(f"Integrity Failed: {summary.get('integrity_failed', 0)}")
        self.lbl_lib_resampled.setText(f"Resampled: {summary.get('resample_to_cd', 0)}")
        self.lbl_lib_recompressed.setText(f"Recompressed: {summary.get('recompress', 0)}")
        self.lbl_lib_art_exported.setText(f"Artwork Exported: {summary.get('extract_art', 0)}")
        self.lbl_lib_held.setText(f"Held: {summary.get('hold', 0)}")

        # Populate issues list with held files
        self.lib_issues_list.clear()
        for held_file in summary.get("held_files", []):
            path = held_file.get("path", "unknown")
            reason = held_file.get("reason", "unknown reason")
            self.lib_issues_list.addItem(f"{path}: {reason}")

        # Show timing information
        timing = summary.get("timing_s", {})
        if timing:
            total_time = summary.get("total_time_s", 0)
            logger.info(f"Library operation timing: total={total_time:.1f}s")
            for phase, time_taken in timing.items():
                logger.info(f"  {phase}: {time_taken:.1f}s")

    def _on_adopt_summary_ready(self, summary: dict) -> None:
        """Update UI with adopt operation summary."""
        self.counters_group.show()
        self.lbl_lib_current_op.setText("")
        
        # Update adopt counter
        self.lbl_lib_adopted.setText(f"Adopted: {summary.get('adopted', 0)}")
        
        # Log details
        logger.info(f"Adopt summary: {summary.get('adopted', 0)} adopted, "
                    f"{summary.get('skipped', 0)} skipped, {summary.get('failed', 0)} failed")

    def _on_lib_done(self, code: int) -> None:
        """Handle library operation completion."""
        self.activateWindow()
        self.raise_()
        if code == 0:
            QtWidgets.QMessageBox.information(self, "Library Complete", "Library maintenance completed successfully")
        else:
            QtWidgets.QMessageBox.warning(self, "Library Complete", "Library maintenance completed with errors. See log for details.")

    def _disable_lib_ui(self) -> None:
        """Disable library UI during operation."""
        # Hide Run button, show pause/cancel
        self.btn_lib_run.hide()
        self.btn_lib_pause.show()
        self.btn_lib_cancel.show()
        self.btn_lib_pause.setEnabled(True)
        self.btn_lib_cancel.setEnabled(True)
        self.btn_lib_pause.setText("Pause")
        self.progress.show()
        
        # Auto-expand details area during run
        self.details_toggle.setChecked(True)

    def _reenable_lib_ui(self) -> None:
        """Re-enable library UI after operation."""
        self.progress.hide()
        self.btn_lib_pause.hide()
        self.btn_lib_cancel.hide()
        self.lbl_lib_current_op.setText("")
        
        # Show Run button
        self.btn_lib_run.show()
        self.btn_lib_run.setEnabled(True)
        
        # Re-apply mirror-dependent state
        self._update_mirror_dependent_ops()
        self._apply_encoder_ui()

    # Auto-scan methods
    def _on_lib_root_browse(self) -> None:
        """Handle browse button for library root - triggers immediate scan on selection."""
        start = self.edit_lib_root.text() or str(Path.home())
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select FLAC Library Root", start)
        if d:
            self.edit_lib_root.setText(d)
            # File dialog selection should trigger immediate scan (bypass debounce)
            self._trigger_auto_scan(d)

    def _on_lib_path_changed(self, text: str) -> None:
        """Handle library path text change - starts debounce timer."""
        # Stop any pending debounce
        self._lib_path_debounce_timer.stop()
        
        path = text.strip()
        if not path:
            # Path cleared - clear browser
            self._clear_browser()
            self._update_path_validation_indicator(None)
            return
        
        # Start debounce timer
        self._lib_path_debounce_timer.start()

    def _on_lib_path_debounce_timeout(self) -> None:
        """Called after debounce period - validate and auto-scan if valid."""
        path = self.edit_lib_root.text().strip()
        if not path:
            return
        
        # Validate path
        path_obj = Path(path)
        if path_obj.exists() and path_obj.is_dir():
            self._update_path_validation_indicator(True)
            self._trigger_auto_scan(path)
        else:
            self._update_path_validation_indicator(False)
            self._clear_browser()

    def _trigger_auto_scan(self, path: str) -> None:
        """Trigger automatic scan if path changed since last scan."""
        if path == self._last_scanned_lib_path:
            return  # Already scanned this path
        
        # Cancel any in-progress scan
        if hasattr(self, 'browser_worker') and self.browser_worker.isRunning():
            self.browser_worker.cancel()
            self.browser_worker.wait(500)  # Wait up to 500ms for cancellation
        
        self._last_scanned_lib_path = path
        self.on_browser_scan()

    def _update_path_validation_indicator(self, valid: Optional[bool]) -> None:
        """Update visual indicator for path validation status."""
        if valid is None:
            # Clear state
            self.edit_lib_root.setStyleSheet("")
            self.edit_lib_root.setToolTip("FLAC library root")
        elif valid:
            # Valid path - green border
            self.edit_lib_root.setStyleSheet("border: 1px solid green;")
            self.edit_lib_root.setToolTip("Valid directory")
        else:
            # Invalid path - red border
            self.edit_lib_root.setStyleSheet("border: 1px solid red;")
            self.edit_lib_root.setToolTip("Directory does not exist")

    def _clear_browser(self) -> None:
        """Clear browser table and statistics."""
        self.browser_model.set_files([])
        self.correlated_model.set_files([])
        self._last_scanned_lib_path = ""
        
        # Reset statistics
        self.btn_stat_total.setText("Total: 0")
        self.btn_stat_hires.setText("Hi-Res: 0")
        self.btn_stat_integrity_unknown.setText("Untested: 0")
        self.btn_stat_integrity_failed.setText("Failed: 0")
        self.btn_stat_needs_recompress.setText("Needs Recompress: 0")
        self.btn_stat_legacy.setText("Legacy: 0")

    # Browser methods
    def _on_view_mode_change(self, mode: str) -> None:
        """Handle view mode change."""
        self._current_view_mode = mode
        
        # Update filter options based on view mode
        self.combo_browser_filter.blockSignals(True)
        self.combo_browser_filter.clear()
        
        if mode == "With Outputs":
            self.combo_browser_filter.addItems([
                "All Files", "Needs Conversion", "Synced", "Outdated", "Missing", "Orphaned Outputs",
            ])
        elif mode == "Outputs Only":
            self.combo_browser_filter.addItems([
                "All Files", "Legacy (No PAC tags)", "Orphaned Outputs",
            ])
        else:  # Source Only
            self.combo_browser_filter.addItems([
                "All Files", "Needs Action", "Hi-Res Only",
                "Integrity Unknown", "Integrity Failed",
                "Needs Recompress", "Legacy (No PAC tags)",
            ])
        
        self.combo_browser_filter.blockSignals(False)
        
        # Swap table model based on view mode
        if mode == "With Outputs":
            self.browser_proxy_model.setSourceModel(self.correlated_model)
        else:
            self.browser_proxy_model.setSourceModel(self.browser_model)
        
        # Trigger rescan if we have a valid path
        lib_root = self.edit_lib_root.text().strip()
        if lib_root and Path(lib_root).exists():
            self.on_browser_scan()

    def on_browser_scan(self) -> None:
        """Start browser scan of library."""
        lib_root = self.edit_lib_root.text().strip()
        if not lib_root or not Path(lib_root).exists():
            QtWidgets.QMessageBox.warning(
                self, "Missing Library Root",
                "Please select a valid FLAC library root directory"
            )
            return
        
        # Check if correlated mode requires mirror path
        mirror_out = self.edit_mirror_out.text().strip()
        view_mode = self.combo_view_mode.currentText()
        
        if view_mode == "With Outputs" and (not mirror_out or not Path(mirror_out).exists()):
            QtWidgets.QMessageBox.warning(
                self, "Missing Mirror Output",
                "Correlated view requires a valid Mirror output directory"
            )
            return
        
        if view_mode == "Outputs Only" and (not mirror_out or not Path(mirror_out).exists()):
            QtWidgets.QMessageBox.warning(
                self, "Missing Mirror Output",
                "Outputs Only view requires a valid Mirror output directory"
            )
            return
        
        # Map view mode to correlation mode
        if view_mode == "With Outputs":
            correlation_mode = BrowserWorker.MODE_WITH_OUTPUTS
        elif view_mode == "Outputs Only":
            correlation_mode = BrowserWorker.MODE_OUTPUTS_ONLY
        else:
            correlation_mode = BrowserWorker.MODE_SOURCE_ONLY
        
        logger.info(f"Starting browser scan of {lib_root} (mode: {view_mode})")
        self.btn_browser_scan.setEnabled(False)
        self.btn_browser_scan.setText("Scanning...")
        self.progress.show()
        
        # Start browser worker
        self.browser_worker = BrowserWorker(
            cfg=self.settings,
            root=lib_root,
            output_dir=mirror_out if mirror_out else None,
            correlation_mode=correlation_mode,
        )
        self.browser_worker.progress_update.connect(self._on_browser_progress)
        self.browser_worker.finished_with_result.connect(self._on_browser_scan_complete)
        self.browser_worker.start()

    def _on_browser_progress(self, current: int, total: int) -> None:
        """Handle browser scan progress updates."""
        if total > 0:
            self.lbl_lib_current_op.setText(f"Scanning: {current}/{total}")

    def _on_browser_scan_complete(self, analysis) -> None:
        """Handle browser scan completion."""
        self.btn_browser_scan.setEnabled(True)
        self.btn_browser_scan.setText("Rescan")
        self.progress.hide()
        self.lbl_lib_current_op.setText("")
        
        if analysis is None:
            logger.error("Browser scan failed")
            return
        
        # Store analysis for later use
        self._current_analysis = analysis
        
        # Handle different analysis types
        if isinstance(analysis, CorrelatedAnalysis):
            logger.info(f"Correlated scan complete: {len(analysis.files)} files "
                       f"({analysis.synced_count} synced, {analysis.missing_count} missing)")
            
            # Update correlated table model
            self.correlated_model.set_files(analysis.files)
            
            # Update statistics for correlated view
            self._update_correlated_statistics(analysis)
        else:
            # LibraryAnalysis
            logger.info(f"Browser scan complete: {analysis.total_files} files")
            
            # Update table model
            self.browser_model.set_files(analysis.files)
            
            # Update statistics
            self._update_browser_statistics(analysis)
        
        # Resize columns to content
        self.browser_table.resizeColumnsToContents()

    def _update_browser_statistics(self, analysis: LibraryAnalysis) -> None:
        """Update the statistics bar with analysis results."""
        self.btn_stat_total.setText(f"Total: {analysis.total_files}")
        self.btn_stat_hires.setText(f"Hi-Res: {analysis.hires_count}")
        self.btn_stat_integrity_unknown.setText(f"Untested: {analysis.integrity_unknown_count}")
        self.btn_stat_integrity_failed.setText(f"Failed: {analysis.integrity_failed_count}")
        self.btn_stat_needs_recompress.setText(f"Needs Recompress: {analysis.needs_recompress_count}")
        self.btn_stat_legacy.setText(f"Legacy: {analysis.legacy_count}")
        
        # Show all stat buttons for source view
        self.btn_stat_hires.show()
        self.btn_stat_integrity_unknown.show()
        self.btn_stat_integrity_failed.show()
        self.btn_stat_needs_recompress.show()
        self.btn_stat_legacy.show()

    def _update_correlated_statistics(self, analysis: CorrelatedAnalysis) -> None:
        """Update the statistics bar for correlated view."""
        total = len(analysis.files)
        self.btn_stat_total.setText(f"Total: {total}")
        self.btn_stat_hires.setText(f"Synced: {analysis.synced_count}")
        self.btn_stat_integrity_unknown.setText(f"Outdated: {analysis.outdated_count}")
        self.btn_stat_integrity_failed.setText(f"Missing: {analysis.missing_count}")
        self.btn_stat_needs_recompress.setText(f"Orphan: {analysis.orphan_count}")
        
        # Hide legacy button in correlated view, repurpose others
        self.btn_stat_legacy.hide()
        self.btn_stat_hires.show()
        self.btn_stat_integrity_unknown.show()
        self.btn_stat_integrity_failed.show()
        self.btn_stat_needs_recompress.show()
        
        # Update tooltips for repurposed buttons
        self.btn_stat_hires.setToolTip("Filter synced files")
        self.btn_stat_integrity_unknown.setToolTip("Filter outdated files")
        self.btn_stat_integrity_failed.setToolTip("Filter missing files")
        self.btn_stat_needs_recompress.setToolTip("Filter orphaned outputs")

    def _on_browser_filter_change(self, filter_text: str) -> None:
        """Handle filter combobox change."""
        view_mode = self._current_view_mode
        
        if view_mode == "With Outputs":
            # Correlated view filters
            if filter_text == "All Files":
                self.correlated_model.clear_filters()
            elif filter_text == "Needs Conversion":
                self.correlated_model.set_filter(needs_conversion=True)
            elif filter_text == "Synced":
                self.correlated_model.set_filter(synced=True)
            elif filter_text == "Outdated":
                self.correlated_model.set_filter(sync_status=SyncStatus.OUTDATED)
            elif filter_text == "Missing":
                self.correlated_model.set_filter(sync_status=SyncStatus.MISSING)
            elif filter_text == "Orphaned Outputs":
                self.correlated_model.set_filter(orphans=True)
        else:
            # Source view filters (also used for Outputs Only)
            if filter_text == "All Files":
                self.browser_model.clear_filters()
            elif filter_text == "Needs Action":
                self.browser_model.set_filter(needs_action=True)
            elif filter_text == "Hi-Res Only":
                self.browser_model.set_filter(hires=True)
            elif filter_text == "Integrity Unknown":
                self.browser_model.set_filter(integrity=IntegrityStatus.NEVER_TESTED)
            elif filter_text == "Integrity Failed":
                self.browser_model.set_filter(integrity=IntegrityStatus.FAILED)
            elif filter_text == "Needs Recompress":
                self.browser_model.set_filter(status=FileStatus.NEEDS_ACTION)
            elif filter_text == "Legacy (No PAC tags)":
                self.browser_model.set_filter(legacy=True)
            elif filter_text == "Orphaned Outputs":
                # For Outputs Only view - filter legacy files which are orphans
                self.browser_model.set_filter(legacy=True)

    def _on_browser_clear_filter(self) -> None:
        """Clear browser filters."""
        self.combo_browser_filter.setCurrentText("All Files")
        if self._current_view_mode == "With Outputs":
            self.correlated_model.clear_filters()
        else:
            self.browser_model.clear_filters()

    def _on_browser_selection_changed(self) -> None:
        """Handle browser table selection changes."""
        indexes = self.browser_table.selectionModel().selectedRows()
        count = len(indexes)
        self.lbl_browser_selection.setText(f"Selected: {count} files")
        
        # Enable/disable action buttons based on selection
        self.btn_browser_run_integrity.setEnabled(count > 0)
        self.btn_browser_run_adopt.setEnabled(count > 0)

    def _on_browser_context_menu(self, pos) -> None:
        """Show context menu for browser table."""
        indexes = self.browser_table.selectionModel().selectedRows()
        if not indexes:
            return
        
        menu = QtWidgets.QMenu(self)
        
        action_integrity = menu.addAction("Run Integrity Check")
        action_integrity.triggered.connect(self._on_browser_run_integrity)
        
        action_adopt = menu.addAction("Adopt (add PAC tags)")
        action_adopt.triggered.connect(self._on_browser_run_adopt)
        
        menu.addSeparator()
        
        action_show_in_folder = menu.addAction("Show in Folder")
        action_show_in_folder.triggered.connect(self._on_browser_show_in_folder)
        
        menu.exec_(self.browser_table.viewport().mapToGlobal(pos))

    def _on_browser_run_integrity(self) -> None:
        """Run integrity check on selected files."""
        indexes = self.browser_table.selectionModel().selectedRows()
        if not indexes:
            return
        
        # Get selected files from proxy model
        selected_files = []
        for idx in indexes:
            source_idx = self.browser_proxy_model.mapToSource(idx)
            f = self.browser_model.get_file_at(source_idx.row())
            if f:
                selected_files.append(f)
        
        if not selected_files:
            return
        
        logger.info(f"Running integrity check on {len(selected_files)} selected files")
        # TODO: Implement targeted integrity check on selected files
        QtWidgets.QMessageBox.information(
            self, "Not Implemented",
            f"Integrity check on {len(selected_files)} selected files will be implemented.\n"
            "For now, use 'Run Integrity' button for full library check."
        )

    def _on_browser_run_adopt(self) -> None:
        """Adopt selected legacy files."""
        indexes = self.browser_table.selectionModel().selectedRows()
        if not indexes:
            return
        
        # Get selected files from proxy model
        selected_files = []
        for idx in indexes:
            source_idx = self.browser_proxy_model.mapToSource(idx)
            f = self.browser_model.get_file_at(source_idx.row())
            if f and f.is_legacy:
                selected_files.append(f)
        
        if not selected_files:
            QtWidgets.QMessageBox.information(
                self, "No Legacy Files",
                "No legacy files (files without PAC tags) in selection."
            )
            return
        
        logger.info(f"Adopting {len(selected_files)} selected legacy files")
        # TODO: Implement targeted adopt on selected files
        QtWidgets.QMessageBox.information(
            self, "Not Implemented",
            f"Adopt on {len(selected_files)} selected legacy files will be implemented.\n"
            "For now, use 'Run' button with 'Adopt Legacy Files' checked."
        )

    def _on_browser_show_in_folder(self) -> None:
        """Open folder containing selected file."""
        indexes = self.browser_table.selectionModel().selectedRows()
        if not indexes:
            return
        
        source_idx = self.browser_proxy_model.mapToSource(indexes[0])
        f = self.browser_model.get_file_at(source_idx.row())
        if f:
            import subprocess
            import platform
            folder = str(f.path.parent)
            if platform.system() == "Windows":
                subprocess.run(["explorer", folder])
            elif platform.system() == "Darwin":
                subprocess.run(["open", folder])
            else:
                subprocess.run(["xdg-open", folder])

    def _setup_shared_components(self, outer: QtWidgets.QVBoxLayout) -> None:
        """Setup components shared between tabs (preflight, progress, log)."""
        # Encoder status row (persistent display)
        encoder_row = QtWidgets.QHBoxLayout()
        self.lbl_encoder_icon = QtWidgets.QLabel("⏳")
        self.lbl_encoder_icon.setFixedWidth(20)
        self.lbl_preflight = QtWidgets.QLabel("Checking encoders...")
        self.btn_recheck_encoders = QtWidgets.QPushButton("Re-check Encoders")
        self.btn_recheck_encoders.setToolTip("Re-run encoder detection")
        self.btn_recheck_encoders.setEnabled(False)  # Disabled during auto-preflight
        
        # Wine encoder probe button (shown when Wine probing is skipped)
        self.btn_check_wine = QtWidgets.QPushButton("Check Wine Encoders")
        self.btn_check_wine.setToolTip("Probe Wine-based encoders (qaac) - may trigger Wine dialogs")
        self.btn_check_wine.clicked.connect(self._on_check_wine_encoders)
        self.btn_check_wine.hide()  # Hidden by default, shown after startup preflight if Wine was skipped
        
        encoder_row.addWidget(self.lbl_encoder_icon)
        encoder_row.addWidget(self.lbl_preflight, 1)
        encoder_row.addWidget(self.btn_check_wine)
        encoder_row.addWidget(self.btn_recheck_encoders)
        outer.addLayout(encoder_row)
        
        # AAC encoder preference row (shown when multiple AAC encoders available)
        self.aac_pref_row = QtWidgets.QWidget()
        aac_pref_layout = QtWidgets.QHBoxLayout(self.aac_pref_row)
        aac_pref_layout.setContentsMargins(0, 0, 0, 0)
        aac_pref_layout.addWidget(QtWidgets.QLabel("AAC Encoder:"))
        self.combo_aac_encoder = QtWidgets.QComboBox()
        self.combo_aac_encoder.setToolTip("Select preferred AAC encoder")
        self.combo_aac_encoder.currentTextChanged.connect(self._on_aac_encoder_changed)
        aac_pref_layout.addWidget(self.combo_aac_encoder)
        aac_pref_layout.addStretch(1)
        self.aac_pref_row.hide()  # Hidden until multiple encoders detected
        outer.addWidget(self.aac_pref_row)

        # Progress
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)

        # Log toggle row (stays visible even when log is collapsed)
        log_toggle_row = QtWidgets.QHBoxLayout()
        self.btn_toggle_log = QtWidgets.QToolButton()
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(not self._log_collapsed)
        self.btn_toggle_log.setToolTip("Show/hide the log panel")
        self.btn_toggle_log.clicked.connect(self._toggle_log)
        log_toggle_row.addWidget(self.btn_toggle_log)
        log_toggle_row.addStretch(1)
        outer.addLayout(log_toggle_row)

    def _setup_log_panel(self) -> None:
        self._update_log_toggle_text()
        self.log = QtWidgets.QTextEdit(readOnly=True)
        self.log.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)

    def _update_log_toggle_text(self) -> None:
        if self._log_collapsed:
            self.btn_toggle_log.setText("▶ Log")
        else:
            self.btn_toggle_log.setText("▼ Log")

    def _toggle_log(self) -> None:
        if self._log_collapsed:
            self._expand_log()
        else:
            self._collapse_log()

    def _collapse_log(self, *, store_size: bool = True) -> None:
        if store_size:
            sizes = self.main_splitter.sizes()
            if isinstance(sizes, list) and len(sizes) == 2 and sizes[1] > 0:
                self._log_last_sizes = sizes
        self._log_collapsed = True
        self.btn_toggle_log.setChecked(False)
        self._update_log_toggle_text()
        self.main_splitter.setSizes([1, 0])
        self._ui_settings.setValue("log_collapsed", True)

    def _expand_log(self) -> None:
        self._log_collapsed = False
        self.btn_toggle_log.setChecked(True)
        self._update_log_toggle_text()
        sizes = self._log_last_sizes
        if not (isinstance(sizes, list) and len(sizes) == 2 and sizes[1] > 0):
            sizes = [600, 150]
        self.main_splitter.setSizes(sizes)
        self._ui_settings.setValue("log_collapsed", False)

    def append_log(self, line: str) -> None:
        self.log.append(line)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        sizes = self.main_splitter.sizes()
        if isinstance(sizes, list) and len(sizes) == 2:
            if self._log_collapsed and self._log_last_sizes:
                self._ui_settings.setValue("main_splitter_sizes", self._log_last_sizes)
            else:
                self._ui_settings.setValue("main_splitter_sizes", sizes)
        self._ui_settings.setValue("log_collapsed", self._log_collapsed)
        return super().closeEvent(event)

    def _pick_dir(self, target: QtWidgets.QLineEdit) -> None:
        start = target.text() or str(Path.home())
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory", start)
        if d:
            target.setText(d)

    def _auto_preflight(self) -> None:
        """Auto-run preflight check on startup."""
        skip_wine = not self.settings.probe_wine_encoders
        if skip_wine:
            logger.info("Auto-running preflight check (skipping Wine encoders)...")
        else:
            logger.info("Auto-running preflight check...")
        self._run_preflight(skip_wine=skip_wine)

    def on_preflight(self) -> None:
        """Re-run preflight encoder detection (respects setting)."""
        skip_wine = not self.settings.probe_wine_encoders
        self._run_preflight(skip_wine=skip_wine)

    def _on_check_wine_encoders(self) -> None:
        """Manually probe Wine-based encoders (qaac)."""
        logger.info("Probing Wine encoders (qaac)...")
        self._run_preflight(skip_wine=False)

    def _run_preflight(self, skip_wine: bool) -> None:
        """Run preflight encoder detection with optional Wine skip."""
        self.btn_recheck_encoders.setEnabled(False)
        self.btn_check_wine.setEnabled(False)
        self.lbl_preflight.setText("Checking encoders...")
        self.lbl_encoder_icon.setText("⏳")
        self.pf = PreflightWorker(skip_wine=skip_wine)
        self.pf.result.connect(self._on_preflight_ok)
        self.pf.failed.connect(self._on_preflight_err)
        self.pf.finished.connect(self._on_preflight_finished)
        self.pf.start()

    def _on_preflight_finished(self) -> None:
        """Re-enable preflight buttons after check completes."""
        self.btn_recheck_encoders.setEnabled(True)
        self.btn_check_wine.setEnabled(True)

    def _on_preflight_ok(self, res: dict) -> None:
        self.preflight_results = res
        wine_skipped = res.get("wine_skipped", False)
        
        # Show/hide Wine encoder button based on whether Wine was skipped
        if wine_skipped and not self.settings.probe_wine_encoders:
            self.btn_check_wine.show()
        else:
            self.btn_check_wine.hide()
        
        if res.get("ok"):
            # Build compact encoder status
            encoders = []
            if res.get("libfdk_aac"):
                encoders.append("libfdk_aac")
            if res.get("libopus"):
                encoders.append("libopus")
            if res.get("qaac"):
                encoders.append(f"qaac {res.get('qaac')}")
            if res.get("fdkaac"):
                encoders.append(f"fdkaac {res.get('fdkaac')}")
            
            status_parts = [f"ffmpeg {res.get('ffmpeg', 'unknown')}"]
            if encoders:
                status_parts.append(f"Available: {', '.join(encoders)}")
            if wine_skipped:
                status_parts.append("(Wine skipped)")
            
            txt = " | ".join(status_parts)
            self.lbl_preflight.setText(txt)
            self.lbl_encoder_icon.setText("✅")
            logger.info("Preflight OK - encoders available")
            
            # Update AAC encoder dropdown
            self._update_aac_encoder_combo(res)
            
            self._on_codec_change(self.combo_codec.currentText())
        else:
            self.lbl_preflight.setText("No suitable AAC or Opus encoder found")
            self.lbl_encoder_icon.setText("❌")
            logger.error("No suitable encoder available.")
            self.selected_encoder = None
            self.aac_pref_row.hide()
            self._apply_encoder_ui()

    def _on_preflight_err(self, msg: str) -> None:
        self.lbl_preflight.setText(f"Encoder check failed: {msg}")
        self.lbl_encoder_icon.setText("❌")
        logger.error(f"Preflight error: {msg}")
        self.selected_encoder = None
        self.preflight_results = None
        self._apply_encoder_ui()

    def _update_aac_encoder_combo(self, res: dict) -> None:
        """Update AAC encoder dropdown based on available encoders."""
        available_aac = []
        if res.get("libfdk_aac"):
            available_aac.append("libfdk_aac")
        if res.get("qaac"):
            available_aac.append("qaac")
        if res.get("fdkaac"):
            available_aac.append("fdkaac")
        
        # Only show dropdown if multiple AAC encoders available
        if len(available_aac) > 1:
            self.combo_aac_encoder.blockSignals(True)
            self.combo_aac_encoder.clear()
            self.combo_aac_encoder.addItems(available_aac)
            
            # Restore saved preference if valid
            pref = self.settings.aac_encoder_preference
            if pref and pref in available_aac:
                self.combo_aac_encoder.setCurrentText(pref)
            
            self.combo_aac_encoder.blockSignals(False)
            self.aac_pref_row.show()
        else:
            self.aac_pref_row.hide()

    def _on_aac_encoder_changed(self, encoder: str) -> None:
        """Handle AAC encoder preference change."""
        if not encoder:
            return
        logger.info(f"AAC encoder preference changed to: {encoder}")
        self.settings.aac_encoder_preference = encoder
        try:
            self.settings.write()
            logger.info("Saved encoder preference to config")
        except Exception as e:
            logger.warning(f"Failed to save encoder preference: {e}")
        self._apply_encoder_ui()

    def _on_codec_change(self, codec: str) -> None:
        self._apply_encoder_ui()

    def _apply_encoder_ui(self) -> None:
        """Enable/disable quality controls based on selected codec and preflight results."""
        res = getattr(self, "preflight_results", None)
        codec = self.combo_codec.currentText()

        # Default to disabled
        self.spin_tvbr.setEnabled(False)
        self.spin_vbr.setEnabled(False)
        self.spin_opus_vbr.setEnabled(False)
        self.btn_plan.setEnabled(False)
        self.btn_convert.setEnabled(False)

        if not res or not res.get("ok"):
            self.lbl_encoder_status.setText("unknown (run Preflight)")
            self.lbl_quality_hint.setText("N/A")
            return

        selected_encoder = None
        if codec == "opus":
            self.spin_opus_vbr.setEnabled(True)
            if res.get("libopus"):
                selected_encoder = "libopus"
                self.lbl_quality_hint.setText("Using Opus VBR bitrate (kbps)")
        else:  # aac
            # Check for user preference first
            pref = self.settings.aac_encoder_preference
            if pref and res.get(pref.replace("libfdk_aac", "libfdk_aac")):
                # Validate preference is actually available
                pref_available = (
                    (pref == "libfdk_aac" and res.get("libfdk_aac")) or
                    (pref == "qaac" and res.get("qaac")) or
                    (pref == "fdkaac" and res.get("fdkaac"))
                )
                if pref_available:
                    selected_encoder = pref
                else:
                    logger.warning(f"Preferred encoder '{pref}' not available, falling back")
            
            # Fall back to default order if no preference or preference unavailable
            if not selected_encoder:
                if res.get("libfdk_aac"):
                    selected_encoder = "libfdk_aac"
                elif res.get("qaac"):
                    selected_encoder = "qaac"
                elif res.get("fdkaac"):
                    selected_encoder = "fdkaac"
            
            # Set quality controls based on selected encoder
            if selected_encoder == "libfdk_aac":
                self.spin_vbr.setEnabled(True)
                self.lbl_quality_hint.setText("Using VBR for libfdk_aac (1-5)")
            elif selected_encoder == "qaac":
                self.spin_tvbr.setEnabled(True)
                self.lbl_quality_hint.setText("Using TVBR for qaac (0-127)")
            elif selected_encoder == "fdkaac":
                self.spin_vbr.setEnabled(True)
                self.lbl_quality_hint.setText("Using VBR for fdkaac (1-5)")

        self.selected_encoder = selected_encoder
        if selected_encoder:
            self.lbl_encoder_status.setText(f"{selected_encoder}")
            self.btn_plan.setEnabled(True)
            self.btn_convert.setEnabled(True)
        else:
            self.lbl_encoder_status.setText(f"No suitable encoder found for {codec}")
            self.lbl_quality_hint.setText("N/A")

    def _gather_params(self) -> dict:
        return {
            "src_dir": Path(self.edit_src.text().strip()) if self.edit_src.text().strip() else None,
            "out_dir": Path(self.edit_dest.text().strip()) if self.edit_dest.text().strip() else None,
            "codec": self.combo_codec.currentText(),
            "tvbr": int(self.spin_tvbr.value()),
            "vbr": int(self.spin_vbr.value()),
            "opus_vbr_kbps": int(self.spin_opus_vbr.value()),
            "workers": int(self.spin_workers.value()),
            
            "verbose": True,
            "dry_run": False,
            "force_reencode": bool(self.chk_force.isChecked()),
            "allow_rename": bool(self.chk_rename.isChecked()),
            "retag_existing": bool(self.chk_retag.isChecked()),
            "prune_orphans": bool(self.chk_prune.isChecked()),
            "no_adopt": bool(self.chk_no_adopt.isChecked()),
            "sync_tags": bool(self.chk_sync_tags.isChecked()),
            "verify_tags": bool(self.chk_verify.isChecked()),
            "verify_strict": bool(self.chk_verify_strict.isChecked()),
            "log_json_path": self.settings.log_json,
            "cover_art_resize": bool(self.chk_cover_resize.isChecked()),
            "cover_art_max_size": int(self.spin_cover_max_size.value()),
        }

    def _start_convert(self, *, dry_run: bool) -> None:
        params = self._gather_params()
        if not params["src_dir"] or not params["src_dir"].exists():
            QtWidgets.QMessageBox.warning(self, "Missing Source", "Please select a valid source directory")
            return
        if not params["out_dir"]:
            QtWidgets.QMessageBox.warning(self, "Missing Destination", "Please select a destination directory")
            return

        if params.get("prune_orphans") and not dry_run:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm Prune",
                "This will delete files from the destination directory that do not exist in the source. This cannot be undone. Are you sure?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.No:
                return

        if params.get("force_reencode") and not dry_run:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm Force Re-encode",
                "This will re-encode all files regardless of existing outputs. Are you sure?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.No:
                return

        # Disable UI during run
        for w in [self.btn_plan, self.btn_convert, self.btn_recheck_encoders, self.btn_src, self.btn_dest]:
            w.hide()

        self.btn_pause.show()
        self.btn_cancel.show()
        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.btn_pause.setText("Pause")
        self.progress.show()

        params["dry_run"] = dry_run
        self.worker = ConvertWorker(cfg=self.settings, **params)
        self.worker.plan_ready.connect(self._on_plan_ready)
        self.worker.finished_with_code.connect(self._on_convert_done)
        self.worker.finished.connect(self._reenable_ui)
        self.worker.start()

    def _reenable_ui(self) -> None:
        self.progress.hide()
        self.btn_pause.hide()
        self.btn_cancel.hide()
        for w in [self.btn_plan, self.btn_convert, self.btn_recheck_encoders, self.btn_src, self.btn_dest]:
            w.show()
            w.setEnabled(True)
        self._apply_encoder_ui()

    def _on_plan_ready(self, plan: dict) -> None:
        self.plan_group.show()
        self.lbl_plan_convert.setText(f"Convert: {plan.get('to_convert', 0)}")
        self.lbl_plan_skip.setText(f"Skip: {plan.get('skipped', 0)}")
        self.lbl_plan_retag.setText(f"Retag: {plan.get('retagged', 0)}")
        self.lbl_plan_rename.setText(f"Rename: {plan.get('renamed', 0)}")
        self.lbl_plan_prune.setText(f"Prune: {plan.get('pruned', 0)}")
        self.lbl_plan_sync_tags.setText(f"Sync Tags: {plan.get('to_sync_tags', 0)}")

    def _on_convert_done(self, code: int) -> None:
        self.activateWindow()
        self.raise_()
        if code == EXIT_OK:
            QtWidgets.QMessageBox.information(self, "Done", "Operation completed successfully")
        elif code == EXIT_PREFLIGHT_FAILED:
            QtWidgets.QMessageBox.critical(self, "Preflight Failed", "No suitable AAC encoder found. See log for details.")
        else:
            QtWidgets.QMessageBox.warning(self, "Completed with Errors", "Some files failed. See log and summary JSON for details.")

    # Slots
    def on_plan(self) -> None:
        self.log.clear()
        self.plan_group.hide()
        logger.info("Starting dry‑run (plan)…")
        self._start_convert(dry_run=True)

    def on_convert(self) -> None:
        self.log.clear()
        self.plan_group.hide()
        logger.info("Starting conversion…")
        self._start_convert(dry_run=False)

    def on_cancel(self) -> None:
        logger.warning("Cancel requested by user.")
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.btn_pause.setEnabled(False)

    def on_pause_resume(self) -> None:
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.toggle_pause()
            if self.btn_pause.text() == "Pause":
                logger.info("Pausing...")
                self.btn_pause.setText("Resume")
            else:
                logger.info("Resuming...")
                self.btn_pause.setText("Pause")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for GUI startup."""
    parser = argparse.ArgumentParser(
        description="Python Audio Converter GUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--flac-library",
        metavar="DIR",
        help="Pre-populate Library tab FLAC library path",
    )
    parser.add_argument(
        "--mirror-library",
        metavar="DIR",
        help="Pre-populate Library tab mirror output path",
    )
    parser.add_argument(
        "--source",
        metavar="DIR",
        help="Pre-populate Convert tab source directory",
    )
    parser.add_argument(
        "--output",
        metavar="DIR",
        help="Pre-populate Convert tab output directory",
    )
    return parser.parse_args()


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    args = parse_args()
    # Configure a basic console logger early to catch startup
    configure_logging()
    w = MainWindow(
        flac_library=args.flac_library,
        mirror_library=args.mirror_library,
        source=args.source,
        output=args.output,
    )
    w.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
