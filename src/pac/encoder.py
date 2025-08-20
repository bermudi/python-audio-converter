"""Encoder command construction and execution.

- Primary: FFmpeg with libfdk_aac (single process) when available.
- Fallbacks: FFmpeg decode -> qaac (pipe) or -> fdkaac (pipe) handled elsewhere.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import List, Optional


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


def build_ffmpeg_decode_wav_cmd(src: Path) -> List[str]:
    """Build ffmpeg command to decode input audio to WAV on stdout."""
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-vn",
        "-sn",
        "-dn",
        "-i",
        str(src),
        "-acodec",
        "pcm_s16le",
        "-f",
        "wav",
        "-",
    ]


def build_qaac_encode_from_stdin_cmd(out_path: Path, tvbr: int = 96, extra_args: Optional[List[str]] = None) -> List[str]:
    """Build qaac command to read WAV from stdin and write M4A.

    Uses true VBR (tvbr). The `tvbr` scale typically ranges roughly 0-127; common
    transparent settings are around 91-96 for ~256 kbps, depending on content.
    """
    cmd = [
        "qaac",
        "--moov-before-mdat",
        "--tvbr",
        str(tvbr),
        "-o",
        str(out_path),
        "-",
    ]
    if extra_args:
        # insert after binary for predictable order
        cmd[1:1] = list(extra_args)
    return cmd


def run_ffmpeg_pipe_to_qaac(src: Path, dest: Path, tvbr: int = 96) -> int:
    """Run ffmpeg decoding to WAV and pipe into qaac for encoding.

    Returns qaac's exit code (non-zero indicates failure).
    """
    ffmpeg_cmd = build_ffmpeg_decode_wav_cmd(src)
    qaac_cmd = build_qaac_encode_from_stdin_cmd(dest, tvbr=tvbr)

    p_ff = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,  # binary PCM
    )
    try:
        p_qc = subprocess.Popen(
            qaac_cmd,
            stdin=p_ff.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Important: allow ffmpeg to receive SIGPIPE when qaac exits
        if p_ff.stdout is not None:
            p_ff.stdout.close()
        _, err_qc = p_qc.communicate()
        # Ensure ffmpeg exits
        _, err_ff = p_ff.communicate()
        # If qaac failed, propagate failure
        return p_qc.returncode or 0
    finally:
        # Best-effort cleanup
        for proc in (p_ff,):
            if proc.poll() is None:
                proc.kill()


def build_fdkaac_encode_from_stdin_cmd(out_path: Path, vbr_mode: int = 5, extra_args: Optional[List[str]] = None) -> List[str]:
    """Build fdkaac command to read WAV from stdin and write M4A.

    vbr_mode typically ranges 1-5 for increasing quality; 5 targets ~256 kbps for AAC-LC.
    """
    cmd = [
        "fdkaac",
        "-m",
        str(vbr_mode),
        "-o",
        str(out_path),
        "-",
    ]
    if extra_args:
        cmd[1:1] = list(extra_args)
    return cmd


def run_ffmpeg_pipe_to_fdkaac(src: Path, dest: Path, vbr_mode: int = 5) -> int:
    """Run ffmpeg decoding to WAV and pipe into fdkaac for encoding.

    Returns fdkaac's exit code (non-zero indicates failure).
    """
    ffmpeg_cmd = build_ffmpeg_decode_wav_cmd(src)
    fdkaac_cmd = build_fdkaac_encode_from_stdin_cmd(dest, vbr_mode=vbr_mode)

    p_ff = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,  # binary PCM
    )
    try:
        p_fd = subprocess.Popen(
            fdkaac_cmd,
            stdin=p_ff.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if p_ff.stdout is not None:
            p_ff.stdout.close()
        _, err_fd = p_fd.communicate()
        _, err_ff = p_ff.communicate()
        return p_fd.returncode or 0
    finally:
        if p_ff.poll() is None:
            p_ff.kill()
