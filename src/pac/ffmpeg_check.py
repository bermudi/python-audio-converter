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


def probe_ffmpeg() -> FFmpegStatus:
    path = shutil.which("ffmpeg")
    if not path:
        return FFmpegStatus(available=False, error="ffmpeg not found in PATH")

    rc_v, out_v, err_v = _run([path, "-version"])  # version printed to stdout
    version = out_v.splitlines()[0].strip() if out_v else None

    rc_e, out_e, err_e = _run([path, "-hide_banner", "-encoders"])  # encoders on stdout
    has_fdk = "libfdk_aac" in out_e or "libfdk_aac" in out_v or "libfdk_aac" in out_e or "libfdk_aac" in out_e
    # safer:
    has_fdk = "libfdk_aac" in (out_e + out_v + out_e)

    status = FFmpegStatus(
        available=(rc_v == 0),
        ffmpeg_path=path,
        ffmpeg_version=version,
        has_libfdk_aac=has_fdk if rc_e == 0 else False,
        error=None if rc_v == 0 else (err_v or "ffmpeg -version failed"),
    )
    return status


if __name__ == "__main__":
    s = probe_ffmpeg()
    print(s)
