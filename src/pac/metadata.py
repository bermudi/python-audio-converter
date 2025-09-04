"""Metadata helpers using mutagen for FLAC -> MP4/Opus tag copying.

Copies common text tags, track/disc numbers, cover art, and where possible,
MusicBrainz identifiers into MP4 freeform atoms.

Also supports writing/reading PAC_* stateless tags so outputs are
self-describing for planning without any local DB.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict
import base64
from io import BytesIO


def _resize_cover_art(img_data: bytes, max_size: int) -> bytes:
    """Resize image if its larger dimension exceeds max_size."""
    try:
        from PIL import Image

        img = Image.open(BytesIO(img_data))
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size))
            out_buffer = BytesIO()
            # Preserve format, fall back to JPEG
            img_format = img.format if img.format in ["JPEG", "PNG"] else "JPEG"
            img.save(out_buffer, format=img_format)
            return out_buffer.getvalue()
    except Exception:
        # If anything fails, return original data
        return img_data
    return img_data


def _first_front_cover(flac_obj) -> Optional[bytes]:
    """Return raw image bytes for front cover if present, else None.

    Handles multiple cover art storage patterns seen in FLAC files:
    - Proper FLAC PICTURE blocks via ``FLAC.pictures``.
    - Base64-encoded ``METADATA_BLOCK_PICTURE`` tag values.
    - Legacy ``coverart``/``coverartmime`` Vorbis comment tags.
    """
    # 1) Preferred: FLAC PICTURE blocks parsed by mutagen
    pictures = list(getattr(flac_obj, "pictures", []) or [])
    for pic in pictures:
        if getattr(pic, "type", None) == 3 and getattr(pic, "data", None):  # 3 = Front cover
            return bytes(pic.data)
    # If no explicit front-cover, and there is exactly one picture, accept it
    if len(pictures) == 1 and getattr(pictures[0], "data", None):
        return bytes(pictures[0].data)

    # 2) Fallback: Some tools store METADATA_BLOCK_PICTURE as base64 in Vorbis comments
    try:
        mbp_values = list(flac_obj.tags.get("METADATA_BLOCK_PICTURE", [])) if getattr(flac_obj, "tags", None) else []
    except Exception:
        mbp_values = []
    if mbp_values:
        try:
            from mutagen.flac import Picture
            for val in mbp_values:
                try:
                    raw = base64.b64decode(val) if isinstance(val, (str, bytes, bytearray)) else None
                    if not raw and isinstance(val, list) and val:
                        raw = base64.b64decode(val[0])
                    if not raw:
                        continue
                    pic = Picture()
                    pic.from_data(raw)
                    if getattr(pic, "type", None) == 3 and getattr(pic, "data", None):
                        return bytes(pic.data)
                except Exception:
                    continue
        except Exception:
            pass
        # If only a single MBP value exists and no type-3 detected, accept it as cover
        if len(mbp_values) == 1:
            try:
                val = mbp_values[0]
                raw = base64.b64decode(val) if isinstance(val, (str, bytes, bytearray)) else None
                if not raw and isinstance(val, list) and val:
                    raw = base64.b64decode(val[0])
                if raw:
                    from mutagen.flac import Picture
                    pic = Picture(); pic.from_data(raw)
                    if getattr(pic, "data", None):
                        return bytes(pic.data)
            except Exception:
                pass

    # 3) Legacy: coverart (base64) + optional coverartmime
    try:
        cov_vals = flac_obj.tags.get("coverart", []) if getattr(flac_obj, "tags", None) else []
    except Exception:
        cov_vals = []
    if cov_vals:
        try:
            # mutagen normalizes keys to lowercase; values are usually base64 strings
            val = cov_vals[0]
            if isinstance(val, (bytes, bytearray)):
                # Some tools may already store raw bytes; accept as-is
                return bytes(val)
            if isinstance(val, str):
                return base64.b64decode(val)
        except Exception:
            pass

    # No cover art found
    return None


def copy_tags_flac_to_mp4(
    src_flac: Path,
    dst_mp4: Path,
    pac: Optional[Dict[str, str]] = None,
    *,
    cover_art_resize: bool = True,
    cover_art_max_size: int = 1500,
) -> None:
    """Copy common tags and cover art from FLAC to MP4/M4A.

    This is best-effort and idempotent; missing tags are skipped.
    """
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

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
        if cover_art_resize:
            img = _resize_cover_art(img, cover_art_max_size)
        # Try to guess format by simple magic
        fmt = MP4Cover.FORMAT_JPEG if img[:3] == b"\xff\xd8\xff" else MP4Cover.FORMAT_PNG
        m["covr"] = [MP4Cover(img, imageformat=fmt)]

    # MusicBrainz IDs -> MP4 freeform atoms (best-effort)
    # Common FLAC keys are typically lowercased by mutagen
    mb_map = {
        "musicbrainz_trackid": "MusicBrainz Track Id",
        "musicbrainz_albumid": "MusicBrainz Album Id",
        "musicbrainz_artistid": "MusicBrainz Artist Id",
        "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
        "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    }
    for flac_key, ff_name in mb_map.items():
        val = (f.get(flac_key) or [None])[0]
        if isinstance(val, str) and val.strip():
            try:
                m[f"----:com.apple.iTunes:{ff_name}"] = [MP4FreeForm(val.strip().encode("utf-8"))]
            except Exception:
                # Non-fatal; continue copying other tags
                pass

    # PAC_* embedding (freeform atoms) when provided
    if pac:
        _mp4_set_pac_tags(m, pac)

    m.save()


def copy_tags_flac_to_opus(
    src_flac: Path,
    dst_opus: Path,
    pac: Optional[Dict[str, str]] = None,
    *,
    cover_art_resize: bool = True,
    cover_art_max_size: int = 1500,
) -> None:
    """Copy all Vorbis comments and cover art from FLAC to Opus."""
    from mutagen.flac import FLAC, Picture
    from mutagen.oggopus import OggOpus

    f = FLAC(str(src_flac))
    o = OggOpus(str(dst_opus))

    # Copy all text tags
    for k, v in f.tags.items():
        o.tags[k] = v

    # Cover art
    img_data = _first_front_cover(f)
    if img_data:
        if cover_art_resize:
            img_data = _resize_cover_art(img_data, cover_art_max_size)
        pic = Picture()
        pic.data = img_data
        # Try to guess format from magic bytes
        if img_data.startswith(b"\xff\xd8\xff"):
            pic.mime = "image/jpeg"
        elif img_data.startswith(b"\x89PNG\r\n\x1a\n"):
            pic.mime = "image/png"

        # OggOpus expects METADATA_BLOCK_PICTURE to be a base64 string
        o.tags["METADATA_BLOCK_PICTURE"] = base64.b64encode(pic.write()).decode("ascii")

    # PAC_* embedding as Vorbis comments when provided
    if pac:
        _opus_set_pac_tags(o, pac)

    o.save()


def verify_tags_flac_vs_opus(src_flac: Path, dst_opus: Path) -> list[str]:
    """Verify a subset of tags and cover presence persisted FLAC -> Opus.

    Returns a list of discrepancy messages. Empty list means OK.
    """
    from mutagen.flac import FLAC
    from mutagen.oggopus import OggOpus

    f = FLAC(str(src_flac))
    o = OggOpus(str(dst_opus))
    disc: list[str] = []

    # Cover art
    had_cover = _first_front_cover(f) is not None
    has_cover = "metadata_block_picture" in o.tags or "coverart" in o.tags
    if had_cover and not has_cover:
        disc.append("cover: missing")

    # Compare a few common tags
    for key in ["title", "artist", "album", "tracknumber"]:
        exp = (f.tags.get(key) or [None])[0]
        got = (o.tags.get(key) or [None])[0]
        if exp and exp != got:
            disc.append(f"{key}: expected='{exp}' got='{got}'")

    return disc


import unicodedata


def _norm_str_nfc(v: Optional[str]) -> str:
    """Normalize string to NFC and strip whitespace."""
    if v is None:
        return ""
    return unicodedata.normalize("NFC", str(v)).strip()


def _first_year(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    import re
    m = re.search(r"(\d{4})", s)
    return m.group(1) if m else None


def verify_tags_flac_vs_mp4(src_flac: Path, dst_mp4: Path) -> list[str]:
    """Verify a subset of tags and cover presence persisted FLAC -> MP4.

    Returns a list of discrepancy messages. Empty list means OK.
    Compared fields: title, artist, album, albumartist, track/disc numbers,
    date/year (by year), genre, composer, compilation, and cover presence.
    All string comparisons use Unicode NFC normalization.
    """
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4

    f = FLAC(str(src_flac))
    m = MP4(str(dst_mp4))

    disc: list[str] = []

    # Presence of cover art
    had_cover = _first_front_cover(f) is not None
    has_covr = bool(m.tags and m.tags.get("covr"))
    if had_cover and not has_covr:
        disc.append("cover: missing")

    # String fields
    def first(flac_key: str) -> Optional[str]:
        try:
            v = f.get(flac_key)
            return v[0] if v else None
        except Exception:
            return None

    checks = [
        ("title", _norm_str_nfc(first("title")), _norm_str_nfc((m.tags.get("\xa9nam") or [""])[0] if m.tags else "")),
        ("artist", _norm_str_nfc(first("artist")), _norm_str_nfc((m.tags.get("\xa9ART") or [""])[0] if m.tags else "")),
        ("album", _norm_str_nfc(first("album")), _norm_str_nfc((m.tags.get("\xa9alb") or [""])[0] if m.tags else "")),
        ("albumartist", _norm_str_nfc(first("albumartist")), _norm_str_nfc((m.tags.get("aART") or [""])[0] if m.tags else "")),
        ("genre", _norm_str_nfc(first("genre")), _norm_str_nfc((m.tags.get("\xa9gen") or [""])[0] if m.tags else "")),
        ("composer", _norm_str_nfc(first("composer")), _norm_str_nfc((m.tags.get("\xa9wrt") or [""])[0] if m.tags else "")),
    ]
    for field, exp, got in checks:
        if exp and exp != got:
            disc.append(f"{field}: expected='{exp}' got='{got}'")

    # Compilation flag
    comp_str = (first("compilation") or "0").strip()
    exp_comp = comp_str in {"1", "true", "True", "yes", "Yes"}
    got_comp = (m.tags.get("cpil") or [False])[0] if m.tags else False
    if exp_comp and not got_comp:
        disc.append(f"compilation: expected='true' got='{str(got_comp).lower()}'")

    # Date/Year by leading year
    exp_year = _first_year(first("date") or first("year"))
    got_year = _first_year(((m.tags.get("\xa9day") or [""])[0] if m.tags else ""))
    if exp_year and got_year and exp_year != got_year:
        disc.append(f"date: expected-year='{exp_year}' got-year='{got_year}'")

    # Track/disc numbers
    def _int_or_none(x: Optional[str]) -> Optional[int]:
        try:
            return int(str(x).strip()) if x is not None else None
        except Exception:
            return None

    trk = _int_or_none(first("tracknumber"))
    trk_tot = _int_or_none(first("tracktotal") or first("totaltracks"))
    got_trkn = m.tags.get("trkn") if m.tags else None
    if got_trkn and isinstance(got_trkn, list) and got_trkn:
        g_trk, g_tot = got_trkn[0]
    else:
        g_trk, g_tot = None, None
    # Only compare when source has value
    if trk is not None and trk != (g_trk or 0):
        disc.append(f"track: expected='{trk}' got='{g_trk or 0}'")
    if trk_tot is not None and trk_tot != (g_tot or 0):
        disc.append(f"tracktotal: expected='{trk_tot}' got='{g_tot or 0}'")

    dsk = _int_or_none(first("discnumber"))
    dsk_tot = _int_or_none(first("disctotal") or first("totaldiscs"))
    got_disk = m.tags.get("disk") if m.tags else None
    if got_disk and isinstance(got_disk, list) and got_disk:
        g_dsk, g_dtot = got_disk[0]
    else:
        g_dsk, g_dtot = None, None
    if dsk is not None and dsk != (g_dsk or 0):
        disc.append(f"disc: expected='{dsk}' got='{g_dsk or 0}'")
    if dsk_tot is not None and dsk_tot != (g_dtot or 0):
        disc.append(f"disctotal: expected='{dsk_tot}' got='{g_dtot or 0}'")

    return disc


# ---------------------------------------------------------------------------
# PAC_* helpers (stateless tags)
# ---------------------------------------------------------------------------

PAC_KEYS = (
    "PAC_SRC_MD5",
    "PAC_ENCODER",
    "PAC_QUALITY",
    "PAC_VERSION",
    "PAC_SOURCE_REL",
)


def _mp4_set_pac_tags(m, pac: Dict[str, str]) -> None:
    """Set PAC_* tags on a mutagen MP4 object using freeform atoms."""
    from mutagen.mp4 import MP4FreeForm

    mapping = {
        "PAC_SRC_MD5": "----:org.pac:src_md5",
        "PAC_ENCODER": "----:org.pac:encoder",
        "PAC_QUALITY": "----:org.pac:quality",
        "PAC_VERSION": "----:org.pac:version",
        "PAC_SOURCE_REL": "----:org.pac:source_rel",
    }
    for k, atom in mapping.items():
        v = str(pac.get(k, ""))
        if not v:
            continue
        try:
            m[atom] = [MP4FreeForm(v.encode("utf-8"))]
        except Exception:
            # Non-fatal; continue setting other tags
            pass


def write_pac_tags_mp4(dst_mp4: Path, *, src_md5: str, encoder: str, quality: str | int, version: str, source_rel: str) -> None:
    """Write PAC_* freeform atoms to an MP4/M4A file."""
    from mutagen.mp4 import MP4

    m = MP4(str(dst_mp4))
    _mp4_set_pac_tags(
        m,
        {
            "PAC_SRC_MD5": src_md5,
            "PAC_ENCODER": encoder,
            "PAC_QUALITY": str(quality),
            "PAC_VERSION": version,
            "PAC_SOURCE_REL": source_rel,
        },
    )
    m.save()


def read_pac_tags_mp4(dst_mp4: Path) -> Dict[str, str]:
    """Read PAC_* tags from an MP4/M4A if present; returns empty strings when missing."""
    from mutagen.mp4 import MP4

    m = MP4(str(dst_mp4))
    out: Dict[str, str] = {k: "" for k in PAC_KEYS}
    mapping = {
        "PAC_SRC_MD5": "----:org.pac:src_md5",
        "PAC_ENCODER": "----:org.pac:encoder",
        "PAC_QUALITY": "----:org.pac:quality",
        "PAC_VERSION": "----:org.pac:version",
        "PAC_SOURCE_REL": "----:org.pac:source_rel",
    }
    try:
        tags = m.tags or {}
        for k, atom in mapping.items():
            val_list = tags.get(atom)
            if val_list and isinstance(val_list, list) and val_list:
                v = val_list[0]
                try:
                    out[k] = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
                except Exception:
                    out[k] = str(v)
    except Exception:
        pass
    return out


def _opus_set_pac_tags(o, pac: Dict[str, str]) -> None:
    """Set PAC_* tags on a mutagen OggOpus object as Vorbis comments."""
    tags = o.tags
    for k in PAC_KEYS:
        v = str(pac.get(k, ""))
        if v:
            tags[k] = v


def write_pac_tags_opus(dst_opus: Path, *, src_md5: str, encoder: str, quality: str | int, version: str, source_rel: str) -> None:
    """Write PAC_* Vorbis comments to an Opus file."""
    from mutagen.oggopus import OggOpus

    o = OggOpus(str(dst_opus))
    _opus_set_pac_tags(
        o,
        {
            "PAC_SRC_MD5": src_md5,
            "PAC_ENCODER": encoder,
            "PAC_QUALITY": str(quality),
            "PAC_VERSION": version,
            "PAC_SOURCE_REL": source_rel,
        },
    )
    o.save()


def read_pac_tags_opus(dst_opus: Path) -> Dict[str, str]:
    """Read PAC_* tags from an Opus file; returns empty strings when missing."""
    from mutagen.oggopus import OggOpus

    o = OggOpus(str(dst_opus))
    out: Dict[str, str] = {k: "" for k in PAC_KEYS}
    try:
        tags = o.tags or {}
        for k in PAC_KEYS:
            val = (tags.get(k) or [None])[0]
            if isinstance(val, str):
                out[k] = val
    except Exception:
        pass
    return out


def read_pac_tags(path: Path) -> Dict[str, str]:
    """Container-dispatching reader for PAC_* tags based on file suffix."""
    suf = path.suffix.lower()
    if suf in {".m4a", ".mp4", ".mp4a"}:
        return read_pac_tags_mp4(path)
    if suf in {".opus"}:
        return read_pac_tags_opus(path)
    return {k: "" for k in PAC_KEYS}
