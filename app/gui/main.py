from __future__ import annotations

import sys
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
            ok = st.available and (st.has_libfdk_aac or st_qa.available or st_fd.available)
            res = {
                "ffmpeg": st.ffmpeg_version or st.error or "unknown",
                "ffmpeg_path": st.ffmpeg_path,
                "libfdk_aac": bool(st.has_libfdk_aac),
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

    def __init__(
        self,
        *,
        src_dir: Path,
        out_dir: Path,
        tvbr: int,
        vbr: int,
        workers: int,
        hash_streaminfo: bool,
        verbose: bool,
        dry_run: bool,
        force: bool,
        commit_batch_size: int,
        verify_tags: bool,
        verify_strict: bool,
        log_json_path: Optional[str],
    ) -> None:
        super().__init__()
        self.src_dir = src_dir
        self.out_dir = out_dir
        self.tvbr = tvbr
        self.vbr = vbr
        self.workers = workers
        self.hash_streaminfo = hash_streaminfo
        self.verbose = verbose
        self.dry_run = dry_run
        self.force = force
        self.commit_batch_size = commit_batch_size
        self.verify_tags = verify_tags
        self.verify_strict = verify_strict
        self.log_json_path = log_json_path

    def run(self) -> None:  # type: ignore[override]
        try:
            code = cmd_convert_dir(
                str(self.src_dir),
                str(self.out_dir),
                tvbr=self.tvbr,
                vbr=self.vbr,
                workers=self.workers,
                hash_streaminfo=self.hash_streaminfo,
                verbose=self.verbose,
                dry_run=self.dry_run,
                force=self.force,
                commit_batch_size=self.commit_batch_size,
                log_json_path=self.log_json_path,
                verify_tags=self.verify_tags,
                verify_strict=self.verify_strict,
            )
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
        self.edit_dest.setPlaceholderText("Destination root for .m4a outputs")
        self.btn_dest = QtWidgets.QPushButton("Browse…")
        dest_row = QtWidgets.QHBoxLayout()
        dest_row.addWidget(self.edit_dest)
        dest_row.addWidget(self.btn_dest)
        form.addRow("Destination:", self._wrap_row(dest_row))

        # Settings row (workers, vbr, tvbr, hash, verify)
        self.spin_workers = QtWidgets.QSpinBox()
        self.spin_workers.setRange(1, max(1, (QtCore.QThread.idealThreadCount() or 8)))
        self.spin_workers.setValue(self.settings.workers or (QtCore.QThread.idealThreadCount() or 4))

        self.spin_tvbr = QtWidgets.QSpinBox()
        self.spin_tvbr.setRange(0, 127)
        self.spin_tvbr.setValue(self.settings.tvbr)
        self.spin_tvbr.setToolTip("Used only when encoder is qaac (tvbr scale, ~256 kbps at ~96)")

        self.spin_vbr = QtWidgets.QSpinBox()
        self.spin_vbr.setRange(1, 5)
        self.spin_vbr.setValue(self.settings.vbr)
        self.spin_vbr.setToolTip("Used when encoder is libfdk_aac or fdkaac (1..5; 5 ~ 256 kbps)")

        self.chk_hash = QtWidgets.QCheckBox("Compute FLAC STREAMINFO MD5 (slower)")
        self.chk_hash.setChecked(self.settings.hash_streaminfo)

        self.chk_verify = QtWidgets.QCheckBox("Verify tags after encode")
        self.chk_verify.setChecked(self.settings.verify_tags)
        self.chk_verify_strict = QtWidgets.QCheckBox("Strict verification (fail on mismatch)")
        self.chk_verify_strict.setChecked(self.settings.verify_strict)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Workers"), 0, 0)
        grid.addWidget(self.spin_workers, 0, 1)
        grid.addWidget(QtWidgets.QLabel("qaac tvbr"), 0, 2)
        grid.addWidget(self.spin_tvbr, 0, 3)
        grid.addWidget(QtWidgets.QLabel("libfdk/fdkaac vbr"), 0, 4)
        grid.addWidget(self.spin_vbr, 0, 5)
        grid.addWidget(self.chk_hash, 1, 0, 1, 3)
        grid.addWidget(self.chk_verify, 1, 3, 1, 2)
        grid.addWidget(self.chk_verify_strict, 1, 5, 1, 1)
        form.addRow("Settings:", self._wrap_row(grid))
        # Encoder/quality hint labels
        self.lbl_encoder_status = QtWidgets.QLabel("Encoder: unknown")
        self.lbl_quality_hint = QtWidgets.QLabel("Quality used: (depends on encoder)")
        form.addRow("Encoder:", self.lbl_encoder_status)
        form.addRow("Quality used:", self.lbl_quality_hint)
        outer.addLayout(form)

        # Action buttons
        actions = QtWidgets.QHBoxLayout()
        self.btn_plan = QtWidgets.QPushButton("Plan (Dry‑Run)")
        self.btn_convert = QtWidgets.QPushButton("Convert")
        self.btn_convert.setDefault(True)
        actions.addStretch(1)
        actions.addWidget(self.btn_plan)
        actions.addWidget(self.btn_convert)
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
        if res.get("ok"):
            txt = (
                f"ffmpeg: {res.get('ffmpeg')}\n"
                f"libfdk_aac: {'YES' if res.get('libfdk_aac') else 'NO'}\n"
                f"qaac: {res.get('qaac') or 'NOT FOUND'}\n"
                f"fdkaac: {res.get('fdkaac') or 'NOT FOUND'}"
            )
            self.lbl_preflight.setText(txt)
            logger.info("Preflight OK")
            # Decide encoder exactly like the CLI does
            enc: Optional[str]
            if res.get("libfdk_aac"):
                enc = "libfdk_aac"
            elif bool(res.get("qaac")):
                enc = "qaac"
            elif bool(res.get("fdkaac")):
                enc = "fdkaac"
            else:
                enc = None
            self.selected_encoder = enc
            self._apply_encoder_ui(enc)
        else:
            self.lbl_preflight.setText("No suitable AAC encoder found")
            logger.error("No AAC encoder available. Install ffmpeg with libfdk_aac, or fdkaac, or qaac.")
            self.selected_encoder = None
            self._apply_encoder_ui(None)

    def _on_preflight_err(self, msg: str) -> None:
        self.lbl_preflight.setText(f"Preflight error: {msg}")
        logger.error(f"Preflight error: {msg}")
        self.selected_encoder = None
        self._apply_encoder_ui(None)

    def _apply_encoder_ui(self, enc: Optional[str]) -> None:
        """Enable/disable tvbr vs vbr controls and show a hint based on encoder.

        enc: one of None, "libfdk_aac", "qaac", "fdkaac".
        """
        if enc is None:
            self.lbl_encoder_status.setText("unknown (run Preflight)")
            self.lbl_quality_hint.setText("tvbr (qaac) or vbr (libfdk/fdkaac), depending on availability")
            self.spin_tvbr.setEnabled(True)
            self.spin_vbr.setEnabled(True)
            return
        self.lbl_encoder_status.setText(enc)
        if enc == "qaac":
            self.spin_tvbr.setEnabled(True)
            self.spin_vbr.setEnabled(False)
            self.lbl_quality_hint.setText("Using qaac tvbr (only tvbr applies)")
        else:  # libfdk_aac or fdkaac
            self.spin_tvbr.setEnabled(False)
            self.spin_vbr.setEnabled(True)
            self.lbl_quality_hint.setText("Using VBR for libfdk_aac/fdkaac (only vbr applies)")

    def _gather_params(self) -> tuple[Optional[Path], Optional[Path], int, int, int, bool, bool, bool, int, bool, bool]:
        src = Path(self.edit_src.text().strip()) if self.edit_src.text().strip() else None
        dest = Path(self.edit_dest.text().strip()) if self.edit_dest.text().strip() else None
        tvbr = int(self.spin_tvbr.value())
        vbr = int(self.spin_vbr.value())
        workers = int(self.spin_workers.value())
        hash_streaminfo = bool(self.chk_hash.isChecked())
        verbose = True
        dry_run = False
        commit = int(self.settings.commit_batch_size)
        verify = bool(self.chk_verify.isChecked())
        verify_strict = bool(self.chk_verify_strict.isChecked())
        return src, dest, tvbr, vbr, workers, hash_streaminfo, verbose, dry_run, commit, verify, verify_strict

    def _start_convert(self, *, dry_run: bool) -> None:
        params = self._gather_params()
        src, dest = params[0], params[1]
        if not src or not src.exists():
            QtWidgets.QMessageBox.warning(self, "Missing Source", "Please select a valid source directory")
            return
        if not dest:
            QtWidgets.QMessageBox.warning(self, "Missing Destination", "Please select a destination directory")
            return

        # Disable UI during run
        for w in [self.btn_plan, self.btn_convert, self.btn_preflight, self.btn_src, self.btn_dest]:
            w.setEnabled(False)
        self.progress.show()

        src_p, dest_p, tvbr, vbr, workers, hash_streaminfo, verbose, _dry, commit, verify, verify_strict = params
        self.worker = ConvertWorker(
            src_dir=src_p,  # type: ignore[arg-type]
            out_dir=dest_p,  # type: ignore[arg-type]
            tvbr=tvbr,
            vbr=vbr,
            workers=workers,
            hash_streaminfo=hash_streaminfo,
            verbose=verbose,
            dry_run=dry_run,
            force=False,
            commit_batch_size=commit,
            verify_tags=verify,
            verify_strict=verify_strict,
            log_json_path=self.settings.log_json,
        )
        self.worker.finished_with_code.connect(self._on_convert_done)
        self.worker.finished.connect(self._reenable_ui)
        self.worker.start()

    def _reenable_ui(self) -> None:
        self.progress.hide()
        for w in [self.btn_plan, self.btn_convert, self.btn_preflight, self.btn_src, self.btn_dest]:
            w.setEnabled(True)

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
        logger.info("Starting dry‑run (plan)…")
        self._start_convert(dry_run=True)

    def on_convert(self) -> None:
        logger.info("Starting conversion…")
        self._start_convert(dry_run=False)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    # Configure a basic console logger early to catch startup
    configure_logging()
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
