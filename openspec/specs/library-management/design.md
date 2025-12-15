# Library Management Design

## Overview
Maintain a "master" FLAC library with integrity checks, compression policy, CD-quality resampling, and artwork extraction. Optionally triggers lossy mirror conversion for clean sources.

## Architecture

### Modules
- **`src/pac/flac_tools.py`**: FLAC utilities
  - `probe_flac()`: Detect flac/metaflac versions
  - `flac_stream_info(path)`: Sample rate, bit depth, channels, duration, MD5
  - `needs_cd_downmix(info)`: Check if >CD quality
  - `recompress_flac(src, level, verify=True)`: Atomic recompress with COMPRESSION tag
  - `resample_to_cd_flac(src, level)`: FFmpeg/sox → flac pipeline
  - `flac_test(src)`: Run `flac -t`, return pass/fail + stderr
  - `extract_art(src, art_root, pattern)`: Write front cover to structured path

- **`src/pac/library_planner.py`**: Produces maintenance actions
  - Actions: `test_integrity`, `resample_to_cd`, `recompress`, `extract_art`, `skip`, `hold`
  - Early-stop on first error per file

- **`src/pac/library_runner.py`**: Orchestrates execution by phase
  - Separate WorkerPools per phase
  - Emits structured events, updates DB
  - Optionally calls `cmd_convert_dir` for mirror

## Database Schema

```sql
-- Integrity checks
CREATE TABLE flac_checks (
    md5 TEXT PRIMARY KEY,
    last_test_ts INTEGER,
    test_ok INTEGER,
    test_msg TEXT,
    streaminfo_md5 TEXT,
    bit_depth INTEGER,
    sample_rate INTEGER,
    channels INTEGER
);

-- Compression policy
CREATE TABLE flac_policy (
    md5 TEXT PRIMARY KEY,
    compression_level INTEGER,
    last_compress_ts INTEGER,
    compression_tag TEXT
);

-- Artwork exports
CREATE TABLE art_exports (
    md5 TEXT PRIMARY KEY,
    last_export_ts INTEGER,
    size INTEGER
);
```

## Phase Execution

1. **Preflight**: Detect flac, metaflac, ffmpeg/sox availability
2. **Integrity**: `flac -t` for each file; hold on failure
3. **Resample**: If >CD specs, resample to 16-bit/44.1kHz/stereo
4. **Recompress**: Apply target compression level, set COMPRESSION tag
5. **Extract Art**: Write front cover to structured folders
6. **Mirror** (optional): Run convert-dir for clean sources only

## Concurrency Model
- `analysis_pool`: For integrity checks (CPU-bound)
- `encode_pool`: For recompress/resample (CPU-bound, ~cores/2)
- `art_pool`: For artwork extraction (I/O-bound, ~min(cores, 4))

## COMPRESSION Tag Format
```
flac 1.4.3; level=8; verify=1; date=2025-09-17
```

## CLI
```bash
pac library --root ~/Music/FLAC \
  --target-compression 8 \
  --resample-to-cd \
  --art-root ~/Music/_art \
  --art-pattern "{albumartist}/{album}/front.jpg" \
  --mirror-out ~/Music/Opus \
  --mirror-codec opus
```

## Configuration (PacSettings)
```python
flac_target_compression: int = 8
flac_resample_to_cd: bool = True
flac_stop_on: Literal["never", "error"] = "error"
flac_art_root: str = "~/Music/_art"
flac_art_pattern: str = "{albumartist}/{album}/front.jpg"
flac_workers: Optional[int] = None
flac_analysis_workers: Optional[int] = None
flac_art_workers: Optional[int] = None
lossy_mirror_auto: bool = False
lossy_mirror_codec: Literal["opus", "aac"] = "opus"
```
