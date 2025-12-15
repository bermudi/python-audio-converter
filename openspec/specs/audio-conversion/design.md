# Audio Conversion Design

## Overview
Mirror a local FLAC library to an AAC (M4A) or Opus library with 1:1 directory structure, preserving metadata and cover art.

## Architecture

### Data Flow
```
1) Scan Source → 2) Scan Destination (PAC_* read) → 3) Stateless Plan → 
4) Parallel Encoders → 5) Tag copy + embed PAC_* → 6) Atomic Output Write/Rename → 
7) Optional rename/retag/prune → 8) Report
```

### Components
- **Scanner** (`src/pac/scanner.py`): Walks source directory, collects SourceFile records with relpath, size, mtime, FLAC STREAMINFO MD5
- **Destination Index** (`src/pac/dest_index.py`): Scans outputs, reads PAC_* tags to build in-memory index
- **Planner** (`src/pac/planner.py`): Compares source scan with destination index, produces PlanItems with actions: skip, convert, rename, retag, prune
- **Encoder** (`src/pac/encoder.py`): FFmpeg command builders, pipe-to-qaac/fdkaac execution, atomic writes
- **Metadata Copier** (`src/pac/metadata.py`): Tag mapping FLAC→MP4/Opus via Mutagen, cover art handling
- **Scheduler** (`src/pac/scheduler.py`): Bounded worker pool with backpressure
- **GUI** (`app/gui/`): PySide6 application

## Encoder Selection
Preflight probes once per run:
1. FFmpeg with libfdk_aac (preferred)
2. FFmpeg decode → qaac pipe (true VBR)
3. FFmpeg decode → fdkaac pipe

## FFmpeg Invocation

### Primary (libfdk_aac)
```bash
ffmpeg -nostdin -hide_banner -loglevel error
  -i "{src}" -map 0:a:0 -vn
  -map_metadata 0 -movflags +use_metadata_tags+faststart
  -c:a libfdk_aac -vbr {q} -threads 1
  "{tmp_out}"
```

### Pipe to qaac
```bash
ffmpeg -nostdin -hide_banner -loglevel error
  -i "{src}" -map 0:a:0 -vn -sn -dn -acodec pcm_s24le -f wav -
| qaac --tvbr {tvbr} -o "{tmp_out}" -
```

## Change Detection
- Use PAC_SRC_MD5 embedded in outputs to match against source FLAC STREAMINFO MD5
- If encoder settings change, re-encode mismatched outputs
- Detect moves by locating destination entry with matching MD5

## Atomic Writes
- Write to `.part` file under destination
- Atomically rename to final path on success
- Remove temp file on failure

## Concurrency
- Each encode uses `-threads 1`
- Worker pool limits concurrent encodes (default: min(cores, 8))
- Bounded task queue (~2×workers) for stable memory/FD footprint on large catalogs

## Configuration
Pydantic settings model persisted as TOML at `~/.config/python-audio-converter/config.toml`:
- `tvbr` (qaac), `vbr` (libfdk/fdkaac), `workers`
- `pcm_codec` (pcm_s24le|pcm_f32le|pcm_s16le)
- `verify_tags`, `verify_strict`
