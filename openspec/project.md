# Project Context

## Purpose
Python Audio Converter (PAC) mirrors FLAC libraries to AAC (M4A) or Opus with 1:1 directory structure and metadata parity. Designed for Linux power users automating batch conversions. Also provides FLAC library maintenance (integrity checks, recompression, artwork extraction).

## Tech Stack
- **Language**: Python 3.12+
- **GUI**: PySide6 (Qt)
- **Metadata**: Mutagen
- **Config**: Pydantic + TOML
- **Logging**: Loguru
- **Package Manager**: uv (no raw pip)
- **External Tools**: FFmpeg (required), flac, metaflac, qaac, fdkaac (optional)

## Project Conventions

### Code Style
- Type hints everywhere
- Docstrings for public functions
- snake_case for functions/variables, PascalCase for classes
- No inline comments unless clarifying non-obvious logic

### Architecture Patterns
- **Pipeline**: Scanner → Index → Planner → Scheduler → Encoder → Metadata
- **Stateless**: PAC_* tags embedded in outputs for change detection (no mandatory DB)
- **Atomic writes**: Always write to `.part` file, then rename
- **Bounded concurrency**: Worker pools with backpressure

### Testing Strategy
- Unit tests for planners, path utilities, config
- Integration tests with FLAC fixtures (behind markers)
- Run with `uv run python -m pytest`

### Git Workflow
- Main branch for stable code
- Feature branches for new work
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`

## Domain Context
- **FLAC STREAMINFO MD5**: Content hash embedded in FLAC files, used for change detection
- **PAC_* tags**: Custom metadata fields (PAC_SRC_MD5, PAC_ENCODER, PAC_QUALITY, PAC_VERSION, PAC_SOURCE_REL) embedded in outputs
- **Encoder priority**: libfdk_aac > qaac > fdkaac
- **VBR targets**: ~256 kbps for AAC, ~160 kbps for Opus

## Important Constraints
- Linux-only (primary target)
- No bundled encoders (system FFmpeg required)
- libfdk_aac may require custom FFmpeg builds
- qaac requires Apple CoreAudio components (non-trivial on Linux)

## External Dependencies
- **FFmpeg**: Required for decoding and encoding
- **flac/metaflac**: Required for library management features
- **qaac**: Optional AAC encoder (true VBR)
- **fdkaac**: Optional AAC encoder fallback
