"""Metadata helpers using mutagen for FLAC -> MP4 tag copying."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def _first_front_cover(flac_obj) -> Optional[bytes]:
    """Return raw image bytes for front cover if present, else None."""
    # Mutagen FLAC exposes .pictures (list of Picture)
    for pic in getattr(flac_obj, "pictures", []) or []:
        if getattr(pic, "type", None) == 3 and pic.data:
            return bytes(pic.data)
    # Some files store picture in tag 'METADATA_BLOCK_PICTURE' as base64, mutagen usually parses already
    return None


def copy_tags_flac_to_mp4(src_flac: Path, dst_mp4: Path) -> None:
    """Copy common tags and cover art from FLAC to MP4/M4A.

    This is best-effort and idempotent; missing tags are skipped.
    """
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4, MP4Cover

    f = FLAC(str(src_flac))
    m = MP4(str(dst_mp4))

    def set_if_present(mp4_key: str, flac_keys: list[str]):
        for k in flac_keys:
            if k in f and f[k]:
                # MP4 expects list-like values for text atoms
                m[mp4_key] = [f[k][0]]
                return

    set_if_present("\xa9nam", ["title"])  # Title
    set_if_present("\xa9ART", ["artist", "albumartist"])  # Prefer artist
    set_if_present("aART", ["albumartist"])  # Album artist
    set_if_present("\xa9alb", ["album"])  # Album
    set_if_present("\xa9wrt", ["composer"])  # Composer
    set_if_present("\xa9gen", ["genre"])  # Genre (string)
    set_if_present("\xa9day", ["date", "year"])  # Year/Date
    set_if_present("\xa9grp", ["grouping"])  # Grouping
    set_if_present("\xa9cmt", ["comment"])  # Comment

    # Track/disc numbers
    def _int(s: str) -> Optional[int]:
        try:
            return int(str(s).strip())
        except Exception:
            return None

    trk = _int((f.get("tracknumber") or [None])[0])
    trk_tot = _int((f.get("tracktotal") or f.get("totaltracks") or [None])[0])
    if trk or trk_tot:
        m["trkn"] = [(trk or 0, trk_tot or 0)]

    dsk = _int((f.get("discnumber") or [None])[0])
    dsk_tot = _int((f.get("disctotal") or f.get("totaldiscs") or [None])[0])
    if dsk or dsk_tot:
        m["disk"] = [(dsk or 0, dsk_tot or 0)]

    # Tempo
    tempo = _int((f.get("tempo") or [None])[0])
    if tempo is not None:
        m["tmpo"] = [tempo]

    # Compilation
    comp = (f.get("compilation") or [None])[0]
    if isinstance(comp, str):
        comp_val = comp.strip() in {"1", "true", "True", "yes", "Yes"}
        if comp_val:
            m["cpil"] = [1]

    # Cover art
    img = _first_front_cover(f)
    if img:
        # Try to guess format by simple magic
        fmt = MP4Cover.FORMAT_JPEG if img[:3] == b"\xff\xd8\xff" else MP4Cover.FORMAT_PNG
        m["covr"] = [MP4Cover(img, imageformat=fmt)]

    m.save()
