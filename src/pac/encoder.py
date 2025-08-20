"""Encoder command construction and execution (FFmpeg)."""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import List


def build_ffmpeg_cmd(src: Path, out_tmp: Path, vbr_quality: int = 5) -> List[str]:
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map_metadata",
        "0",
        "-movflags",
        "+use_metadata_tags",
        "-c:a",
        "libfdk_aac",
        "-vbr",
        str(vbr_quality),
        "-threads",
        "1",
        "-vn",
        str(out_tmp),
    ]


def run_ffmpeg(cmd: List[str]) -> int:
    """Run FFmpeg and return the exit code."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode


def cmd_to_string(cmd: List[str]) -> str:
    return " ".join(shlex.quote(p) for p in cmd)
