from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets
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
from pac.library_runner import cmd_manage_library  # noqa: E402


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

    def run(self) -> None:  # type: ignore[override]
        try:
            st = probe_ffmpeg()
            st_qa = probe_qaac(light=False)
            st_fd = probe_fdkaac()

            # An encoder is OK if we have a way to encode either AAC or Opus
            aac_ok = st.available and (st.has_libfdk_aac or st_qa.available or st_fd.available)
            opus_ok = st.available and st.has_libopus
            ok = aac_ok or opus_ok

            res = {
                "ffmpeg": st.ffmpeg_version or st.error or "unknown",
                "ffmpeg_path": st.ffmpeg_path,
                "libfdk_aac": bool(st.has_libfdk_aac),
                "libopus": bool(st.has_libopus),
                "qaac": st_qa.qaac_version if st_qa.available else None,
                "qaac_path": st_qa.qaac_path,
                "fdkaac": st_fd.fdkaac_version if st_fd.available else None,
                "fdkaac_path": st_fd.fdkaac_path,
                "ok": ok,
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
        try:
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
            if plan:
                self.plan_ready.emit(plan)
        except Exception:
            code = EXIT_WITH_FILE_ERRORS
        self.finished_with_code.emit(code)


class LibraryWorker(QtCore.QThread):
    finished_with_code = QtCore.Signal(int)
    summary_ready = QtCore.Signal(dict)

    def __init__(
        self,
        cfg: PacSettings,
        root: str,
        *,
        mirror_out: Optional[str] = None,
        dry_run: bool = False,
        **kwargs
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.root = root
        self.mirror_out = mirror_out
        self.dry_run = dry_run
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

    def run(self) -> None:  # type: ignore[override]
        try:
            exit_code, summary = cmd_manage_library(
                self.cfg,
                self.root,
                mirror_out=self.mirror_out,
                dry_run=self.dry_run,
            )
            self.summary_ready.emit(summary)
            self.finished_with_code.emit(exit_code)
        except Exception as e:
            logger.error(f"Library operation failed: {e}")
            self.finished_with_code.emit(1)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Python Audio Converter")
        self.resize(1000, 700)

        # Load defaults
        self.settings = PacSettings.load()
        # Encoder selected by preflight: one of None, "libfdk_aac", "qaac", "fdkaac"
        self.selected_encoder: Optional[str] = None

        # Central layout with tabs
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)

        # Create tab widget
        self.tabs = QtWidgets.QTabWidget()
        outer.addWidget(self.tabs, 1)

        # Convert tab
        self.convert_tab = QtWidgets.QWidget()
        self.tabs.addTab(self.convert_tab, "Convert")
        self._setup_convert_tab()

        # Library tab
        self.library_tab = QtWidgets.QWidget()
        self.tabs.addTab(self.library_tab, "Library")
        self._setup_library_tab()

        # Shared components
        self._setup_shared_components(outer)

        # Connections
        self.btn_preflight.clicked.connect(self.on_preflight)
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

    def _setup_convert_tab(self) -> None:
        """Setup the convert tab with existing functionality."""
        layout = QtWidgets.QVBoxLayout(self.convert_tab)

        # I/O selectors
        form = QtWidgets.QFormLayout()
        self.edit_src = QtWidgets.QLineEdit()
        self.edit_src.setPlaceholderText("Source directory with .flac files")
        self.btn_src = QtWidgets.QPushButton("Browse…")
        src_row = QtWidgets.QHBoxLayout()
        src_row.addWidget(self.edit_src)
        src_row.addWidget(self.btn_src)
        form.addRow("Source:", self._wrap_row(src_row))

        self.edit_dest = QtWidgets.QLineEdit()
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

    def _setup_library_tab(self) -> None:
        """Setup the library management tab."""
        layout = QtWidgets.QVBoxLayout(self.library_tab)

        # Library path selector
        form = QtWidgets.QFormLayout()
        self.edit_lib_root = QtWidgets.QLineEdit()
        self.edit_lib_root.setPlaceholderText("FLAC library root directory")
        self.btn_lib_root = QtWidgets.QPushButton("Browse…")
        lib_row = QtWidgets.QHBoxLayout()
        lib_row.addWidget(self.edit_lib_root)
        lib_row.addWidget(self.btn_lib_root)
        form.addRow("Library Root:", self._wrap_row(lib_row))

        # Mirror output selector
        self.edit_mirror_out = QtWidgets.QLineEdit()
        self.edit_mirror_out.setPlaceholderText("Optional: Auto-run convert-dir to this directory")
        self.btn_mirror_out = QtWidgets.QPushButton("Browse…")
        mirror_row = QtWidgets.QHBoxLayout()
        mirror_row.addWidget(self.edit_mirror_out)
        mirror_row.addWidget(self.btn_mirror_out)
        form.addRow("Mirror Output:", self._wrap_row(mirror_row))
        layout.addLayout(form)

        # Library settings
        settings_group = QtWidgets.QGroupBox("Library Settings")
        settings_layout = QtWidgets.QVBoxLayout(settings_group)

        # Compression settings
        comp_layout = QtWidgets.QHBoxLayout()
        comp_layout.addWidget(QtWidgets.QLabel("Target Compression:"))
        self.spin_lib_compression = QtWidgets.QSpinBox()
        self.spin_lib_compression.setRange(0, 8)
        self.spin_lib_compression.setValue(self.settings.flac_target_compression)
        self.spin_lib_compression.setToolTip("FLAC compression level (0-8)")
        comp_layout.addWidget(self.spin_lib_compression)
        comp_layout.addStretch(1)
        settings_layout.addLayout(comp_layout)

        # Resample setting
        resample_layout = QtWidgets.QHBoxLayout()
        self.chk_lib_resample = QtWidgets.QCheckBox("Resample hi-res to CD quality")
        self.chk_lib_resample.setChecked(self.settings.flac_resample_to_cd)
        resample_layout.addWidget(self.chk_lib_resample)
        resample_layout.addStretch(1)
        settings_layout.addLayout(resample_layout)

        # Spectrogram generation setting
        spec_layout = QtWidgets.QHBoxLayout()
        self.chk_lib_generate_specs = QtWidgets.QCheckBox("Generate spectrograms")
        self.chk_lib_generate_specs.setChecked(False)  # Default off as it's optional
        self.chk_lib_generate_specs.setToolTip("Generate spectrogram visualizations for audio files")
        spec_layout.addWidget(self.chk_lib_generate_specs)
        spec_layout.addStretch(1)
        settings_layout.addLayout(spec_layout)

        # Artwork settings
        art_layout = QtWidgets.QFormLayout()
        self.edit_lib_art_root = QtWidgets.QLineEdit()
        self.edit_lib_art_root.setText(str(self.settings.flac_art_root or ""))
        self.edit_lib_art_root.setPlaceholderText("Root directory for extracted artwork")
        self.btn_lib_art_root = QtWidgets.QPushButton("Browse…")
        art_root_row = QtWidgets.QHBoxLayout()
        art_root_row.addWidget(self.edit_lib_art_root)
        art_root_row.addWidget(self.btn_lib_art_root)
        art_layout.addRow("Art Root:", self._wrap_row(art_root_row))

        self.edit_lib_art_pattern = QtWidgets.QLineEdit()
        self.edit_lib_art_pattern.setText(self.settings.flac_art_pattern or "")
        self.edit_lib_art_pattern.setPlaceholderText("Pattern for artwork paths (e.g. {albumartist}/{album}/front.jpg)")
        art_layout.addRow("Art Pattern:", self.edit_lib_art_pattern)
        settings_layout.addLayout(art_layout)

        # Worker settings
        workers_layout = QtWidgets.QGridLayout()
        workers_layout.addWidget(QtWidgets.QLabel("FLAC Workers:"), 0, 0)
        self.spin_lib_flac_workers = QtWidgets.QSpinBox()
        self.spin_lib_flac_workers.setRange(1, max(1, (QtCore.QThread.idealThreadCount() or 8)))
        self.spin_lib_flac_workers.setValue(self.settings.flac_workers or (QtCore.QThread.idealThreadCount() or 2))
        workers_layout.addWidget(self.spin_lib_flac_workers, 0, 1)

        workers_layout.addWidget(QtWidgets.QLabel("Analysis Workers:"), 0, 2)
        self.spin_lib_analysis_workers = QtWidgets.QSpinBox()
        self.spin_lib_analysis_workers.setRange(1, max(1, (QtCore.QThread.idealThreadCount() or 8)))
        self.spin_lib_analysis_workers.setValue(self.settings.flac_analysis_workers or (QtCore.QThread.idealThreadCount() or 4))
        workers_layout.addWidget(self.spin_lib_analysis_workers, 0, 3)

        workers_layout.addWidget(QtWidgets.QLabel("Art Workers:"), 1, 0)
        self.spin_lib_art_workers = QtWidgets.QSpinBox()
        self.spin_lib_art_workers.setRange(1, max(1, (QtCore.QThread.idealThreadCount() or 8)))
        self.spin_lib_art_workers.setValue(self.settings.flac_art_workers or min(QtCore.QThread.idealThreadCount() or 4, 4))
        workers_layout.addWidget(self.spin_lib_art_workers, 1, 1)
        settings_layout.addLayout(workers_layout)

        # Mirror settings
        mirror_settings_layout = QtWidgets.QHBoxLayout()
        mirror_settings_layout.addWidget(QtWidgets.QLabel("Mirror Codec:"))
        self.combo_lib_mirror_codec = QtWidgets.QComboBox()
        self.combo_lib_mirror_codec.addItems(["aac", "opus"])
        self.combo_lib_mirror_codec.setCurrentText(self.settings.lossy_mirror_codec or "aac")
        mirror_settings_layout.addWidget(self.combo_lib_mirror_codec)
        mirror_settings_layout.addStretch(1)
        settings_layout.addLayout(mirror_settings_layout)

        layout.addWidget(settings_group)

        # Counters and issues panel
        self.counters_group = QtWidgets.QGroupBox("Library Status")
        counters_layout = QtWidgets.QVBoxLayout(self.counters_group)

        # Status counters
        status_layout = QtWidgets.QGridLayout()
        self.lbl_lib_scanned = QtWidgets.QLabel("Scanned: 0")
        self.lbl_lib_tested_ok = QtWidgets.QLabel("Integrity OK: 0")
        self.lbl_lib_tested_err = QtWidgets.QLabel("Integrity Failed: 0")
        self.lbl_lib_resampled = QtWidgets.QLabel("Resampled: 0")
        self.lbl_lib_recompressed = QtWidgets.QLabel("Recompressed: 0")
        self.lbl_lib_art_exported = QtWidgets.QLabel("Artwork Exported: 0")
        self.lbl_lib_held = QtWidgets.QLabel("Held: 0")
        self.lbl_lib_spectrograms = QtWidgets.QLabel("Spectrograms Generated: 0")

        status_layout.addWidget(self.lbl_lib_scanned, 0, 0)
        status_layout.addWidget(self.lbl_lib_tested_ok, 0, 1)
        status_layout.addWidget(self.lbl_lib_tested_err, 0, 2)
        status_layout.addWidget(self.lbl_lib_resampled, 1, 0)
        status_layout.addWidget(self.lbl_lib_recompressed, 1, 1)
        status_layout.addWidget(self.lbl_lib_art_exported, 1, 2)
        status_layout.addWidget(self.lbl_lib_spectrograms, 2, 1)
        status_layout.addWidget(self.lbl_lib_held, 2, 2)

        counters_layout.addLayout(status_layout)

        # Issues panel
        issues_group = QtWidgets.QGroupBox("Issues")
        issues_layout = QtWidgets.QVBoxLayout(issues_group)
        self.lib_issues_list = QtWidgets.QListWidget()
        self.lib_issues_list.setMaximumHeight(100)
        issues_layout.addWidget(self.lib_issues_list)
        # Spectrogram links panel
        spec_group = QtWidgets.QGroupBox("Spectrogram Links")
        spec_layout = QtWidgets.QVBoxLayout(spec_group)
        self.spec_links_list = QtWidgets.QListWidget()
        self.spec_links_list.setMaximumHeight(150)
        self.spec_links_list.itemDoubleClicked.connect(self._open_spectrogram_link)
        spec_layout.addWidget(self.spec_links_list)
        counters_layout.addWidget(spec_group)

        # Action buttons
        actions = QtWidgets.QHBoxLayout()
        self.btn_lib_plan = QtWidgets.QPushButton("Plan Library")
        self.btn_lib_run = QtWidgets.QPushButton("Run Library Maintenance")
        self.btn_lib_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_lib_cancel.hide()
        self.btn_lib_pause = QtWidgets.QPushButton("Pause")
        self.btn_lib_pause.hide()

        actions.addStretch(1)
        actions.addWidget(self.btn_lib_plan)
        actions.addWidget(self.btn_lib_run)
        actions.addWidget(self.btn_lib_pause)
        actions.addWidget(self.btn_lib_cancel)
        layout.addLayout(actions)

        # Connect library tab signals
        self.btn_lib_root.clicked.connect(lambda: self._pick_dir(self.edit_lib_root))
        self.btn_lib_art_root.clicked.connect(lambda: self._pick_dir(self.edit_lib_art_root))
        self.btn_mirror_out.clicked.connect(lambda: self._pick_dir(self.edit_mirror_out))
        self.btn_lib_plan.clicked.connect(self.on_lib_plan)
        self.btn_lib_run.clicked.connect(self.on_lib_run)
        self.btn_lib_cancel.clicked.connect(self.on_lib_cancel)
        self.btn_lib_pause.clicked.connect(self.on_lib_pause_resume)

    def _open_spectrogram_link(self, item):
        """Open spectrogram file in default viewer."""
        spec_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if spec_path and Path(spec_path).exists():
            import subprocess
            import sys
            try:
                if sys.platform == "darwin":  # macOS
                    subprocess.run(["open", spec_path])
                elif sys.platform == "win32":  # Windows
                    subprocess.run(["start", spec_path], shell=True)
                else:  # Linux
                    subprocess.run(["xdg-open", spec_path])
            except Exception as e:
                logger.error(f"Failed to open spectrogram: {e}")
        else:
            logger.error(f"Spectrogram file not found: {spec_path}")

    def on_lib_plan(self) -> None:
        """Plan library maintenance (dry run)."""
        self.log.clear()
        self.counters_group.hide()
        self.lib_issues_list.clear()
        self._start_lib_operation(dry_run=True)

    def on_lib_run(self) -> None:
        """Run library maintenance."""
        self.log.clear()
        self.counters_group.hide()
        self.lib_issues_list.clear()
        self._start_lib_operation(dry_run=False)

    def on_lib_cancel(self) -> None:
        """Cancel library operation."""
        logger.warning("Cancel requested by user.")
        if hasattr(self, "lib_worker") and self.lib_worker.isRunning():
            self.lib_worker.cancel()
        self.btn_lib_cancel.setEnabled(False)
        self.btn_lib_pause.setEnabled(False)

    def on_lib_pause_resume(self) -> None:
        """Pause/resume library operation."""
        if hasattr(self, "lib_worker") and self.lib_worker.isRunning():
            self.lib_worker.toggle_pause()
            if self.btn_lib_pause.text() == "Pause":
                logger.info("Pausing...")
                self.btn_lib_pause.setText("Resume")
            else:
                logger.info("Resuming...")
                self.btn_lib_pause.setText("Pause")

    def _start_lib_operation(self, *, dry_run: bool) -> None:
        """Start library operation."""
        lib_root = self.edit_lib_root.text().strip()
        if not lib_root or not Path(lib_root).exists():
            QtWidgets.QMessageBox.warning(self, "Missing Library Root", "Please select a valid FLAC library root directory")
            return

        mirror_out = self.edit_mirror_out.text().strip() if self.edit_mirror_out.text().strip() else None

        # Update settings with library-specific values
        lib_overrides = {
            "flac_target_compression": self.spin_lib_compression.value(),
            "flac_resample_to_cd": self.chk_lib_resample.isChecked(),
            "flac_generate_spectrograms": self.chk_lib_generate_specs.isChecked(),
            "flac_art_root": Path(self.edit_lib_art_root.text().strip()) if self.edit_lib_art_root.text().strip() else None,
            "flac_art_pattern": self.edit_lib_art_pattern.text().strip() or None,
            "flac_workers": self.spin_lib_flac_workers.value(),
            "flac_analysis_workers": self.spin_lib_analysis_workers.value(),
            "flac_art_workers": self.spin_lib_art_workers.value(),
            "lossy_mirror_codec": self.combo_lib_mirror_codec.currentText(),
        }

        # Apply overrides to settings
        lib_settings = self.settings.model_copy(update=lib_overrides)

        # Disable UI during run
        for w in [self.btn_lib_plan, self.btn_lib_run, self.btn_preflight, self.btn_lib_root, self.btn_lib_art_root, self.btn_mirror_out]:
            w.hide()

        self.btn_lib_pause.show()
        self.btn_lib_cancel.show()
        self.btn_lib_pause.setEnabled(True)
        self.btn_lib_cancel.setEnabled(True)
        self.btn_lib_pause.setText("Pause")
        self.progress.show()

        # Start library worker
        self.lib_worker = LibraryWorker(
            cfg=lib_settings,
            root=lib_root,
            mirror_out=mirror_out,
            dry_run=dry_run,
        )
        self.lib_worker.summary_ready.connect(self._on_lib_summary_ready)
        self.lib_worker.finished_with_code.connect(self._on_lib_done)
        self.lib_worker.finished.connect(self._reenable_lib_ui)
        self.lib_worker.start()

    def _on_lib_summary_ready(self, summary: dict) -> None:
        """Update UI with library summary."""
        self.counters_group.show()

        # Update counters
        self.lbl_lib_scanned.setText(f"Scanned: {summary.get('scanned', 0)}")
        self.lbl_lib_tested_ok.setText(f"Integrity OK: {summary.get('integrity_ok', 0)}")
        self.lbl_lib_tested_err.setText(f"Integrity Failed: {summary.get('integrity_failed', 0)}")
        self.lbl_lib_resampled.setText(f"Resampled: {summary.get('resample_to_cd', 0)}")
        self.lbl_lib_recompressed.setText(f"Recompressed: {summary.get('recompress', 0)}")
        self.lbl_lib_art_exported.setText(f"Artwork Exported: {summary.get('extract_art', 0)}")
        self.lbl_lib_spectrograms.setText(f"Spectrograms Generated: {summary.get('generate_spectrogram', 0)}")
        self.lbl_lib_held.setText(f"Held: {summary.get('hold', 0)}")

        # Show timing information
        timing = summary.get("timing_s", {})
        if timing:
            total_time = summary.get("total_time_s", 0)
            logger.info(f"Library operation timing: total={total_time:.1f}s")
            for phase, time_taken in timing.items():
                logger.info(f"  {phase}: {time_taken:.1f}s")

    def _on_lib_done(self, code: int) -> None:
        """Handle library operation completion."""
        if code == 0:
            QtWidgets.QMessageBox.information(self, "Library Complete", "Library maintenance completed successfully")
        else:
            QtWidgets.QMessageBox.warning(self, "Library Complete", "Library maintenance completed with errors. See log for details.")

    def _reenable_lib_ui(self) -> None:
        """Re-enable library UI after operation."""
        self.progress.hide()
        self.btn_lib_pause.hide()
        self.btn_lib_cancel.hide()
        for w in [self.btn_lib_plan, self.btn_lib_run, self.btn_preflight, self.btn_lib_root, self.btn_lib_art_root, self.btn_mirror_out]:
            w.show()
            w.setEnabled(True)
        self._apply_encoder_ui()

    def _setup_shared_components(self, outer: QtWidgets.QVBoxLayout) -> None:
        """Setup components shared between tabs (preflight, progress, log)."""
        # Preflight row
        pf_row = QtWidgets.QHBoxLayout()
        self.btn_preflight = QtWidgets.QPushButton("Preflight")
        self.lbl_preflight = QtWidgets.QLabel("Not checked")
        pf_row.addWidget(self.btn_preflight)
        pf_row.addWidget(self.lbl_preflight, 1)
        outer.addLayout(pf_row)

        # Progress + log
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)

        self.log = QtWidgets.QTextEdit(readOnly=True)
        self.log.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        outer.addWidget(self.log, 1)

    def append_log(self, line: str) -> None:
        self.log.append(line)

    def _pick_dir(self, target: QtWidgets.QLineEdit) -> None:
        start = target.text() or str(Path.home())
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory", start)
        if d:
            target.setText(d)

    def on_preflight(self) -> None:
        self.btn_preflight.setEnabled(False)
        self.lbl_preflight.setText("Checking…")
        self.pf = PreflightWorker()
        self.pf.result.connect(self._on_preflight_ok)
        self.pf.failed.connect(self._on_preflight_err)
        self.pf.finished.connect(lambda: self.btn_preflight.setEnabled(True))
        self.pf.start()

    def _on_preflight_ok(self, res: dict) -> None:
        self.preflight_results = res
        if res.get("ok"):
            txt = (
                f"ffmpeg: {res.get('ffmpeg')}\n"
                f"libfdk_aac: {'YES' if res.get('libfdk_aac') else 'NO'} | "
                f"libopus: {'YES' if res.get('libopus') else 'NO'} | "
                f"qaac: {res.get('qaac') or 'NO'} | "
                f"fdkaac: {res.get('fdkaac') or 'NO'}"
            )
            self.lbl_preflight.setText(txt)
            logger.info("Preflight OK")
            self._on_codec_change(self.combo_codec.currentText())
        else:
            self.lbl_preflight.setText("No suitable AAC or Opus encoder found")
            logger.error("No suitable encoder available.")
            self.selected_encoder = None
            self._apply_encoder_ui()

    def _on_preflight_err(self, msg: str) -> None:
        self.lbl_preflight.setText(f"Preflight error: {msg}")
        logger.error(f"Preflight error: {msg}")
        self.selected_encoder = None
        self.preflight_results = None
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
            if res.get("libfdk_aac"):
                selected_encoder = "libfdk_aac"
                self.spin_vbr.setEnabled(True)
                self.lbl_quality_hint.setText("Using VBR for libfdk_aac (1-5)")
            elif res.get("qaac"):
                selected_encoder = "qaac"
                self.spin_tvbr.setEnabled(True)
                self.lbl_quality_hint.setText("Using TVBR for qaac (0-127)")
            elif res.get("fdkaac"):
                selected_encoder = "fdkaac"
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
        for w in [self.btn_plan, self.btn_convert, self.btn_preflight, self.btn_src, self.btn_dest]:
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
        for w in [self.btn_plan, self.btn_convert, self.btn_preflight, self.btn_src, self.btn_dest]:
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


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    # Configure a basic console logger early to catch startup
    configure_logging()
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
