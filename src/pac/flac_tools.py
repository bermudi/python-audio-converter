"""FLAC-specific tools for library management."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import os
import shutil

from loguru import logger
import re
from string import Formatter


class FlacProbeResult:
    """Result of probing FLAC tools."""

    def __init__(self, available: bool, version: Optional[str] = None, path: Optional[str] = None, error: Optional[str] = None):
        self.available = available
        self.version = version
        self.path = path
        self.error = error


def probe_flac() -> FlacProbeResult:
    """Probe for flac binary and return version info."""
    try:
        result = subprocess.run(
            ["flac", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # Parse version from output like "flac 1.4.3"
            lines = result.stdout.strip().split('\n')
            if lines:
                version_line = lines[0]
                if 'flac' in version_line.lower():
                    version = version_line.split()[1] if len(version_line.split()) > 1 else None
                    path = shutil.which("flac")
                    return FlacProbeResult(available=True, version=version, path=path)
        return FlacProbeResult(available=False, error="flac not found or failed")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return FlacProbeResult(available=False, error=str(e))


def flac_stream_info(path: Path) -> Optional[Dict[str, Any]]:
    """Extract stream info from FLAC file using mutagen."""
    try:
        from mutagen.flac import FLAC
        audio = FLAC(str(path))
        if audio.info:
            info = {
                'sample_rate': audio.info.sample_rate,
                'bit_depth': audio.info.bits_per_sample,
                'channels': audio.info.channels,
                'total_samples': audio.info.total_samples,
                'duration': audio.info.length,
                'md5': None,  # mutagen doesn't provide MD5 directly
            }
            return info
        else:
            logger.warning(f"No stream info found for {path}")
            return None
    except Exception as e:
        logger.warning(f"Error reading stream info for {path}: {e}")
        return None


def needs_cd_downmix(info: Dict[str, Any]) -> bool:
    """Check if file needs downmix to CD quality (16-bit/44.1kHz/2ch)."""
    return (
        info.get('bit_depth', 16) > 16 or
        info.get('sample_rate', 44100) != 44100 or
        info.get('channels', 2) != 2
    )


def flac_test(path: Path) -> Tuple[bool, str]:
    """Test FLAC integrity with flac -t."""
    try:
        result = subprocess.run(
            ["flac", "-t", str(path)],
            capture_output=True,
            text=True,
            timeout=60,  # Allow more time for large files
        )
        success = result.returncode == 0
        error_msg = result.stderr.strip() if not success else ""
        return success, error_msg
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)


def recompress_flac(src: Path, level: int, verify: bool = True) -> int:
    """Recompress FLAC to target level with atomic write."""
    if not src.exists():
        return 1

    # Create temp file in same directory with unique name
    import uuid
    temp_name = f"{src.stem}_recompress_{uuid.uuid4().hex[:8]}.flac"
    tmp_path = src.parent / temp_name

    try:
        cmd = ["flac", f"-{level}"]
        if verify:
            cmd.append("-V")
        cmd.extend(["-o", str(tmp_path), str(src)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"Recompress failed: {result.stderr}")
            tmp_path.unlink(missing_ok=True)
            return result.returncode

        # Atomic replace
        tmp_path.replace(src)
        return 0
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error(f"Recompress error: {e}")
        tmp_path.unlink(missing_ok=True)
        return 1


def resample_to_cd_flac(src: Path, level: int, verify: bool = True, tool: str = "ffmpeg") -> int:
    """Resample to CD quality and recompress."""
    if not src.exists():
        return 1

    with tempfile.NamedTemporaryFile(
        dir=src.parent,
        suffix='.flac',
        delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        if tool == "ffmpeg":
            # ffmpeg pipeline: decode -> resample/dither -> encode
            cmd = [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(src),
                "-ac", "2", "-ar", "44100", "-sample_fmt", "s16",
                "-f", "wav", "-",
                "|",
                "flac", f"-{level}", "-o", str(tmp_path), "-"
            ]
            if verify:
                cmd.insert(-1, "-V")
        else:
            # sox pipeline (if available)
            logger.warning("sox tool not implemented yet, falling back to ffmpeg")
            return resample_to_cd_flac(src, level, verify, "ffmpeg")

        # For piped commands, use shell
        full_cmd = " ".join(cmd)
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"Resample failed: {result.stderr}")
            tmp_path.unlink(missing_ok=True)
            return result.returncode

        # Atomic replace
        tmp_path.replace(src)
        return 0
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error(f"Resample error: {e}")
        tmp_path.unlink(missing_ok=True)
        return 1


def set_flac_tag(src: Path, key: str, value: str) -> bool:
    """Set a Vorbis comment tag in FLAC file."""
    try:
        result = subprocess.run(
            ["metaflac", f"--set-tag={key}={value}", str(src)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def get_flac_tag(src: Path, key: str) -> Optional[str]:
    """Get a Vorbis comment tag from FLAC file."""
    try:
        result = subprocess.run(
            ["metaflac", f"--show-tag={key}", str(src)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Output format: TAG=value (may have multiple lines)
            lines = result.stdout.strip().split('\n')
            # Return the last (most recent) tag
            for line in reversed(lines):
                line = line.strip()
                if '=' in line:
                    return line.split('=', 1)[1]
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _resolve_art_pattern(pattern: str, flac_obj, art_root: Path) -> Path:
    """Resolve pattern placeholders with FLAC tag values."""
    # Extract field names from pattern
    field_names = set()
    formatter = Formatter()
    try:
        for literal_text, field_name, format_spec, conversion in formatter.parse(pattern):
            if field_name:
                field_names.add(field_name)
    except ValueError:
        # If pattern is malformed, treat as literal
        return art_root / pattern

    # Build substitution dict from FLAC tags
    substitutions = {}
    for field in field_names:
        # Try common variations of field names
        candidates = [field, field.lower(), field.upper()]
        if field == 'albumartist':
            candidates.extend(['artist', 'performer'])

        value = None
        for candidate in candidates:
            if candidate in flac_obj.tags:
                tag_values = flac_obj.tags[candidate]
                if tag_values:
                    value = str(tag_values[0]).strip()
                    break

        # Sanitize filename
        if value:
            # Replace problematic characters
            value = re.sub(r'[<>:"/\\|?*]', '_', value)
            # Limit length
            value = value[:100]
        else:
            value = 'Unknown'

        substitutions[field] = value

    # Apply substitutions
    try:
        resolved = pattern.format(**substitutions)
    except (KeyError, ValueError):
        # If substitution fails, use pattern as-is
        resolved = pattern

    return art_root / resolved


def extract_art(src: Path, art_root: Path, pattern: str) -> Optional[Path]:
    """Extract front cover artwork to structured path."""
    try:
        from mutagen.flac import FLAC
        from ..metadata import _first_front_cover

        # Load FLAC file
        flac_obj = FLAC(str(src))
        if not flac_obj:
            logger.warning(f"Could not load FLAC file: {src}")
            return None

        # Get front cover image data
        img_data = _first_front_cover(flac_obj)
        if not img_data:
            logger.debug(f"No front cover found in {src}")
            return None

        # Parse pattern and substitute tags
        output_path = _resolve_art_pattern(pattern, flac_obj, art_root)

        # Create parent directories
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write image data
        with open(output_path, 'wb') as f:
            f.write(img_data)

        logger.info(f"Extracted artwork: {src} -> {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Failed to extract artwork from {src}: {e}")
        return None


def generate_spectrogram(src: Path, png_path: Path) -> bool:
    """Generate spectrogram using ffmpeg."""
    try:
        result = subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-lavfi", "showspectrumpic=s=1280x720:legend=disabled:color=rainbow",
            str(png_path)
        ], capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False