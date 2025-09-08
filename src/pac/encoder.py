"""Encoder command construction and execution.

- Primary: FFmpeg with libfdk_aac (single process) when available.
- Fallbacks: FFmpeg decode -> qaac (pipe) or -> fdkaac (pipe).

Implements atomic outputs by writing to a temporary file in the destination
directory and renaming on success, so truncated files aren't left behind on
failure.

For qaac/fdkaac pipe workflows, default to decoding as 24-bit PCM WAV to avoid
premature quantization of high-bit-depth sources. Optionally allow float.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import List, Optional

from loguru import logger


def build_ffmpeg_cmd(src: Path, out_tmp: Path, vbr_quality: int = 5) -> List[str]:
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0:a:0",  # explicit first audio stream only
        "-vn",  # drop any video streams
        "-map_metadata",
        "0",
        "-movflags",
        "+use_metadata_tags+faststart",  # ensure MP4 opens quickly
        "-c:a",
        "libfdk_aac",
        "-vbr",
        str(vbr_quality),
        "-threads",
        "1",
        str(out_tmp),
    ]


def run_ffmpeg(cmd: List[str]) -> tuple[int, str]:
    """Run FFmpeg and return the exit code and stderr."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    err = proc.stderr or ""
    return proc.returncode, err


def cmd_to_string(cmd: List[str]) -> str:
    return " ".join(shlex.quote(p) for p in cmd)


def build_ffmpeg_decode_wav_cmd(src: Path, *, pcm_codec: str = "pcm_s24le", threads: int = 1) -> List[str]:
    """Build ffmpeg command to decode input audio to WAV on stdout.

    pcm_codec: one of "pcm_s16le", "pcm_s24le", "pcm_f32le".
    threads: explicit ffmpeg thread count for decode (default 1).
    Default is 24-bit PCM to preserve precision when source >16-bit.
    """
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        str(threads),
        "-vn",
        "-sn",
        "-dn",
        "-i",
        str(src),
        "-map",
        "0:a:0",  # decode only the first audio stream
        "-acodec",
        pcm_codec,
        "-f",
        "wav",
        "-",
    ]


def _temp_out_path(final_path: Path) -> Path:
    """Return a unique temp file path in the same directory as final_path."""
    suffix = f".part-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    return final_path.with_name(final_path.name + suffix)


def encode_with_ffmpeg_libfdk(src: Path, dest: Path, *, vbr_quality: int = 5) -> tuple[int, str]:
    """Encode using ffmpeg/libfdk_aac writing atomically to dest.

    Writes to a temporary file in dest's directory then renames to dest on success.
    Returns (0, "") on success, (non-zero, stderr) on failure.
    """
    out_tmp = _temp_out_path(dest)
    cmd = build_ffmpeg_cmd(src, out_tmp, vbr_quality=vbr_quality)
    logger.debug("Running ffmpeg: {}", cmd_to_string(cmd))
    rc, err = run_ffmpeg(cmd)
    if rc != 0:
        try:
            if out_tmp.exists():
                out_tmp.unlink()
        except Exception:
            pass
        return rc, err
    # Atomic replace/move
    try:
        os.replace(str(out_tmp), str(dest))
    except Exception as e:
        err_str = f"Rename failed: {e}"
        logger.error(err_str)
        try:
            if out_tmp.exists():
                out_tmp.unlink()
        except Exception:
            pass
        return 1, err_str
    return 0, ""


def build_ffmpeg_opus_cmd(src: Path, out_tmp: Path, vbr_kbps: int = 160) -> List[str]:
    """Build FFmpeg command to encode a file to Opus."""
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-vn",
        "-map_metadata",
        "0",
        "-c:a",
        "libopus",
        "-vbr",
        "on",
        "-b:a",
        f"{vbr_kbps}k",
        "-threads",
        "1",
        "-f",
        "opus",
        str(out_tmp),
    ]


def encode_with_ffmpeg_libopus(src: Path, dest: Path, *, vbr_kbps: int = 160) -> tuple[int, str]:
    """Encode using ffmpeg/libopus writing atomically to dest."""
    out_tmp = _temp_out_path(dest)
    cmd = build_ffmpeg_opus_cmd(src, out_tmp, vbr_kbps=vbr_kbps)
    logger.debug("Running ffmpeg: {}", cmd_to_string(cmd))
    rc, err = run_ffmpeg(cmd)
    if rc != 0:
        try:
            if out_tmp.exists():
                out_tmp.unlink()
        except Exception:
            pass
        return rc, err
    try:
        os.replace(str(out_tmp), str(dest))
    except Exception as e:
        err_str = f"Rename failed: {e}"
        logger.error(err_str)
        try:
            if out_tmp.exists():
                out_tmp.unlink()
        except Exception:
            pass
        return 1, err_str
    return 0, ""


def build_qaac_encode_from_stdin_cmd(out_path: Path, tvbr: int = 96, extra_args: Optional[List[str]] = None) -> List[str]:
    """Build qaac command to read WAV from stdin and write M4A.

    Uses true VBR (tvbr). The `tvbr` scale typically ranges roughly 0-127; common
    transparent settings are around 91-96 for ~256 kbps, depending on content.
    """
    cmd = [
        "qaac",
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


def run_ffmpeg_pipe_to_qaac(src: Path, dest: Path, tvbr: int = 96, *, pcm_codec: str = "pcm_s24le") -> tuple[int, str]:
    """Run ffmpeg decoding to WAV and pipe into qaac for encoding atomically.

    Decodes as 24-bit PCM WAV by default to avoid pre-quantization. Set
    pcm_codec to "pcm_f32le" to pipe floats if preferred.

    Returns (0, "") on success; (non-zero, combined_stderr) on failure.
    """
    out_tmp = _temp_out_path(dest)
    ffmpeg_cmd = build_ffmpeg_decode_wav_cmd(src, pcm_codec=pcm_codec)
    qaac_cmd = build_qaac_encode_from_stdin_cmd(out_tmp, tvbr=tvbr)
    logger.debug("Running ffmpeg (decode): {}", cmd_to_string(ffmpeg_cmd))
    logger.debug("Running qaac: {}", cmd_to_string(qaac_cmd))

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
        err_ff_bytes, _ = p_ff.communicate()
        err_ff = err_ff_bytes.decode("utf-8", errors="replace") if err_ff_bytes else ""

        rc = p_qc.returncode or 0
        if rc != 0:
            err = f"qaac:\n{err_qc}\n\nffmpeg:\n{err_ff}"
            try:
                if out_tmp.exists():
                    out_tmp.unlink()
            except Exception:
                pass
            return rc, err
        # Atomic replace/move
        try:
            os.replace(str(out_tmp), str(dest))
        except Exception as e:
            err_str = f"Rename failed: {e}"
            logger.error(err_str)
            try:
                if out_tmp.exists():
                    out_tmp.unlink()
            except Exception:
                pass
            return 1, err_str
        return 0, ""
    finally:
        # Best-effort cleanup of decoder process
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


def run_ffmpeg_pipe_to_fdkaac(src: Path, dest: Path, vbr_mode: int = 5, *, pcm_codec: str = "pcm_s24le") -> tuple[int, str]:
    """Run ffmpeg decoding to WAV and pipe into fdkaac for encoding atomically.

    Decodes as 24-bit PCM WAV by default to avoid pre-quantization. Set
    pcm_codec to "pcm_f32le" to pipe floats if preferred.

    Returns (0, "") on success; (non-zero, combined_stderr) on failure.
    """
    out_tmp = _temp_out_path(dest)
    ffmpeg_cmd = build_ffmpeg_decode_wav_cmd(src, pcm_codec=pcm_codec)
    fdkaac_cmd = build_fdkaac_encode_from_stdin_cmd(out_tmp, vbr_mode=vbr_mode)
    logger.debug("Running ffmpeg (decode): {}", cmd_to_string(ffmpeg_cmd))
    logger.debug("Running fdkaac: {}", cmd_to_string(fdkaac_cmd))

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
        err_ff_bytes, _ = p_ff.communicate()
        err_ff = err_ff_bytes.decode("utf-8", errors="replace") if err_ff_bytes else ""
        rc = p_fd.returncode or 0
        if rc != 0:
            err = f"fdkaac:\n{err_fd}\n\nffmpeg:\n{err_ff}"
            try:
                if out_tmp.exists():
                    out_tmp.unlink()
            except Exception:
                pass
            return rc, err
        # Atomic replace/move
        try:
            os.replace(str(out_tmp), str(dest))
        except Exception as e:
            err_str = f"Rename failed: {e}"
            logger.error(err_str)
            try:
                if out_tmp.exists():
                    out_tmp.unlink()
            except Exception:
                pass
            return 1, err_str
        return 0, ""
    finally:
        if p_ff.poll() is None:
            p_ff.kill()
