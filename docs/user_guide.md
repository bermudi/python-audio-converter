# Python Audio Converter User Guide

This guide provides comprehensive instructions for installing, setting up, and using the Python Audio Converter (PAC) tool. PAC is a versatile audio file conversion utility that supports batch processing, metadata preservation, and conversion between various audio formats using FFmpeg as the backend. It offers both command-line interface (CLI) and graphical user interface (GUI) modes for flexibility.

## Prerequisites

Before installing PAC, ensure your system meets the following requirements:

- **Python 3.8+**: PAC is built with Python. Check your version with `python --version`.
- **FFmpeg**: Required for audio encoding/decoding. Download and install from [ffmpeg.org](https://ffmpeg.org/download.html).
  - On Linux (Ubuntu/Debian): `sudo apt update && sudo apt install ffmpeg`
  - On macOS (with Homebrew): `brew install ffmpeg`
  - On Windows: Download the executable from the FFmpeg website and add it to your PATH.
- **uv**: A fast Python package manager and runner. Install from [astral.sh/uv](https://astral.sh/uv). This replaces traditional `pip` for dependency management.

Verify installations:
- `python --version`
- `ffmpeg -version`
- `uv --version`

## Installation

1. Clone or download the project repository to your desired location:
   ```
   git clone https://github.com/your-repo/python-audio-converter.git
   cd python-audio-converter
   ```

2. Set up the virtual environment and install dependencies using uv:
   ```
   uv sync
   ```
   This creates a `.venv` environment, installs runtime dependencies (e.g., FFmpeg wrappers), and dev dependencies if needed.

3. (Optional) For development, add extra tools:
   ```
   uv add --dev pytest black
   ```

The project uses `pyproject.toml` for configuration and `uv.lock` for reproducible builds.

## Quick Start

### CLI Usage

Run conversions directly from the terminal using `uv run`.

- **Convert a single file**:
  ```
  uv run python main.py input.mp3 output.flac
  ```
  This converts `input.mp3` to `output.flac`, preserving metadata.

- **Batch convert a directory**:
  ```
  uv run python main.py --input-dir /path/to/music --output-dir /path/to/converted --format aac
  ```
  Converts all audio files in the input directory to AAC format.

- **Help**:
  ```
  uv run python main.py --help
  ```

Key options:
- `--format TARGET_FORMAT`: Specify output format (e.g., mp3, flac, opus, wav).
- `--bitrate 320k`: Set output bitrate.
- `--preserve-metadata`: Keep ID3 tags (default: true).
- `--dry-run`: Preview conversions without executing.
- `--recursive`: Scan subdirectories for files.

Supported formats: MP3, FLAC, OGG, AAC, Opus, WAV, and more (limited by FFmpeg).

### GUI Usage

The GUI provides a visual interface for selecting files, formats, and settings.

1. Launch the GUI:
   ```
   uv run python -m app.gui.main
   ```

2. In the interface:
   - **Input**: Drag-and-drop files or folders, or use "Browse" to select.
   - **Output**: Choose destination folder and format from dropdown (e.g., FLAC, MP3).
   - **Settings**: Adjust bitrate, sample rate, metadata options, and threading for batch jobs.
   - **Convert**: Click "Start Conversion" to begin. Progress is shown in real-time.
   - **Logs**: View conversion logs and errors in the bottom panel.

The GUI uses Tkinter for cross-platform compatibility and supports multi-threaded processing for efficiency.

## Features

- **Batch Processing**: Convert entire libraries or directories recursively.
- **Format Flexibility**: Supports common audio formats via FFmpeg, including lossless (FLAC, WAV) and lossy (MP3, AAC, Opus).
- **Metadata Handling**: Preserves artist, album, title, and other tags using libraries like mutagen.
- **Error Resilience**: Continues processing on individual file failures, with detailed logging.
- **Customization**: Configurable via `src/pac/config.py` for advanced users (e.g., FFmpeg flags).
- **Database Integration**: Optional SQLite tracking for conversion history and library management.
- **Cross-Platform**: Works on Linux, macOS, and Windows.

## Examples

### Example 1: Convert MP3 Collection to FLAC (Lossless)

CLI:
```
uv run python main.py --input-dir ~/Music/MP3s --output-dir ~/Music/FLAC --format flac --recursive
```

GUI:
1. Launch GUI.
2. Select input folder `~/Music/MP3s`.
3. Set output to `~/Music/FLAC`, format to FLAC.
4. Enable recursive scan.
5. Start conversion.

This upgrades your lossy MP3s to lossless FLAC while keeping metadata.

### Example 2: High-Quality AAC for Mobile Devices

CLI:
```
uv run python main.py input.wav output.m4a --bitrate 256k --preserve-metadata
```

GUI:
1. Add `input.wav` to the list.
2. Choose AAC/M4A format, 256k bitrate.
3. Convert.

### Example 3: Directory Scan and Planning

For large libraries, use the planner:
```
uv run python -m src.pac.planner --scan /path/to/library --report conversions.json
```
This generates a JSON report of planned conversions, which can be reviewed before execution.

## Configuration

Edit `src/pac/config.py` for defaults:
- `DEFAULT_BITRATE = "192k"`
- `SUPPORTED_FORMATS = ["mp3", "flac", "ogg", "aac"]`
- `THREADS = 4`  # For parallel processing

Restart the application after changes.

## Best Practices

- Always back up original files before batch conversions.
- Use `--dry-run` for testing on new setups.
- Monitor disk space for large libraries.
- For Opus output (e.g., for web/audio books), specify `--bitrate 128k` for good quality/size balance.
- If FFmpeg paths are custom, set `FFMPEG_PATH` in config.py.

## Next Steps

- Explore the [Troubleshooting Guide](troubleshooting.md) for common issues.
- Review [Migration Notes](migration_notes.md) if upgrading from older versions.
- Contribute or report issues via GitHub.

For developer documentation, see `src/pac/` modules and `tests/`.