"""Metadata helpers using mutagen for FLAC -> MP4 tag copying.

Copies common text tags, track/disc numbers, cover art, and where possible,
MusicBrainz identifiers into MP4 freeform atoms.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import base64


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


def copy_tags_flac_to_mp4(src_flac: Path, dst_mp4: Path) -> None:
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

    m.save()


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
