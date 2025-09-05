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

# Reuse CLI core to avoid duplication
from main import (  # type: ignore # noqa: E402
    cmd_convert_dir,
    configure_logging,
    EXIT_OK,
    EXIT_PREFLIGHT_FAILED,
    EXIT_WITH_FILE_ERRORS,
)


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
        sync_tags: bool,
        verify_tags: bool,
        verify_strict: bool,
        log_json_path: Optional[str],
        no_adopt: bool,
        cover_art_resize: bool,
        cover_art_max_size: int,
    ) -> None:
        super().__init__()
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
                sync_tags=self.sync_tags,
                log_json_path=self.log_json_path,
                verify_tags=self.verify_tags,
                verify_strict=self.verify_strict,
                no_adopt=self.no_adopt,
                cover_art_resize=self.cover_art_resize,
                cover_art_max_size=self.cover_art_max_size,
                stop_event=self.stop_event,
                pause_event=self.pause_event,
            )
            if plan:
                self.plan_ready.emit(plan)
        except Exception:
            code = EXIT_WITH_FILE_ERRORS
        self.finished_with_code.emit(code)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Python Audio Converter")
        self.resize(1000, 700)

        # Load defaults
        self.settings = PacSettings.load()
        # Encoder selected by preflight: one of None, "libfdk_aac", "qaac", "fdkaac"
        self.selected_encoder: Optional[str] = None

        # Central layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)

        # Preflight row
        pf_row = QtWidgets.QHBoxLayout()
        self.btn_preflight = QtWidgets.QPushButton("Preflight")
        self.lbl_preflight = QtWidgets.QLabel("Not checked")
        pf_row.addWidget(self.btn_preflight)
        pf_row.addWidget(self.lbl_preflight, 1)
        outer.addLayout(pf_row)

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
        self.chk_rename.setChecked(True)  # Default on
        self.chk_retag = QtWidgets.QCheckBox("Retag existing files")
        self.chk_retag.setChecked(True)  # Default on
        self.chk_prune = QtWidgets.QCheckBox("Prune orphans (deletes files)")
        self.chk_prune.setChecked(False)  # Default off
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
        outer.addLayout(form)

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
        self.plan_group.hide()  # Initially hidden
        outer.addWidget(self.plan_group)

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
        outer.addLayout(actions)

        # Progress + log
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)

        self.log = QtWidgets.QTextEdit(readOnly=True)
        self.log.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        outer.addWidget(self.log, 1)

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
        self.worker = ConvertWorker(**params)
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
