"""FFmpeg preflight checks.

Uses only the Python standard library.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class FFmpegStatus:
    available: bool
    ffmpeg_path: Optional[str] = None
    ffmpeg_version: Optional[str] = None
    has_libfdk_aac: Optional[bool] = None
    has_libopus: Optional[bool] = None
    error: Optional[str] = None


@dataclass
class FdkaacStatus:
    available: bool
    fdkaac_path: Optional[str] = None
    fdkaac_version: Optional[str] = None
    error: Optional[str] = None


@dataclass
class QaacStatus:
    available: bool
    qaac_path: Optional[str] = None
    qaac_version: Optional[str] = None
    error: Optional[str] = None


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:  # pragma: no cover - defensive
        return 1, "", str(exc)


def probe_qaac(light: bool = True) -> QaacStatus:
    """Probe qaac availability.

    light=True: only check PATH (fast), skip invoking qaac which can be slow on some systems.
    light=False: attempt to capture version text by running qaac (may be slow).
    """
    path = shutil.which("qaac")
    if not path:
        return QaacStatus(available=False, error="qaac not found in PATH")
    if light:
        return QaacStatus(available=True, qaac_path=path, qaac_version=None, error=None)
    # Full probe for version
    rc1, out1, err1 = _run([path])
    rc2, out2, err2 = _run([path, "--check"])  # ignore rc; some builds return non-zero
    text = (out2 or "") + (err2 or "")
    if not text:
        text = (out1 or "") + (err1 or "")
    version = None
    for line in (text.splitlines() if text else []):
        s = line.strip()
        if s:
            version = s
            break
    return QaacStatus(available=True, qaac_path=path, qaac_version=version, error=None)


def probe_ffmpeg() -> FFmpegStatus:
    path = shutil.which("ffmpeg")
    if not path:
        return FFmpegStatus(available=False, error="ffmpeg not found in PATH")

    # Version (stdout)
    rc_v, out_v, err_v = _run([path, "-version"])  # version printed to stdout
    version = out_v.splitlines()[0].strip() if out_v else None

    # Encoders (stdout)
    rc_e, out_e, err_e = _run([path, "-hide_banner", "-encoders"])  # encoders on stdout
    encoders_text = (out_e or "").lower()
    has_fdk = "libfdk_aac" in encoders_text
    has_opus = "libopus" in encoders_text

    status = FFmpegStatus(
        available=(rc_v == 0),
        ffmpeg_path=path,
        ffmpeg_version=version,
        has_libfdk_aac=(has_fdk if rc_e == 0 else False),
        has_libopus=(has_opus if rc_e == 0 else False),
        error=None if rc_v == 0 else (err_v or "ffmpeg -version failed"),
    )
    return status


def probe_fdkaac() -> FdkaacStatus:
    path = shutil.which("fdkaac")
    if not path:
        return FdkaacStatus(available=False, error="fdkaac not found in PATH")
    # fdkaac prints version on bare call or with -h
    rc_h, out_h, err_h = _run([path])
    text = (out_h or "") + (err_h or "")
    version = None
    for line in (text.splitlines() if text else []):
        line = line.strip()
        if line.lower().startswith("fdkaac "):
            version = line
            break
    return FdkaacStatus(
        available=True,
        fdkaac_path=path,
        fdkaac_version=version,
        error=None,
    )


if __name__ == "__main__":
    s = probe_ffmpeg()
    print(s)
