# Change: Lazy Wine-Based Encoder Probing

## Why
The auto-preflight feature runs `probe_qaac()` on startup, which invokes Wine on Linux systems. This can trigger unwanted dialogs (e.g., Wine Mono Installer) and cause 50+ second delays. Users who only use Opus or have libfdk_aac available don't need qaac probing at all.

Additionally, users may want to choose between AAC encoders (libfdk_aac, qaac, fdkaac) based on quality preferences rather than having the system auto-select.

## What Changes
- Add `probe_wine_encoders` setting (default: `false`) to control whether qaac is probed on startup
- Startup preflight skips qaac when `probe_wine_encoders=false`
- Add "Check Wine Encoders" button in GUI to manually trigger qaac detection
- Add AAC encoder preference dropdown when multiple encoders are available
- Store encoder preference in settings for persistence

## Impact
- Affected specs: `audio-conversion` (Encoder Backend Selection requirement)
- Affected code: 
  - `src/pac/config.py` (new setting)
  - `src/pac/ffmpeg_check.py` (conditional probing)
  - `app/gui/main.py` (PreflightWorker, encoder selection UI)
