# Change: Add Library Management GUI Tab

## Why
The CLI `library` command exists but the GUI lacks a functional Library tab for interactive FLAC maintenance. Users need to run integrity checks, recompression, and artwork extraction from the GUI with progress visibility.

## What Changes
- Implement Library tab UI with settings (compression level, resample toggle, art root/pattern)
- Add Plan/Run buttons with dry-run support
- Add progress counters per phase (integrity, resample, recompress, art)
- Add "Issues Found" panel showing held files
- Wire up to `cmd_manage_library` backend

## Impact
- Affected specs: `library-management`
- Affected code: `app/gui/main.py`
