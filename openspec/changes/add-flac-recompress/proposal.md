# Change: Complete FLAC Recompress and Resample Features

## Why
The library management spec includes recompression and resampling phases, but these need end-to-end testing and integration with the library runner. The `flac_tools.py` functions exist but haven't been fully validated in the pipeline.

## What Changes
- Validate `recompress_flac()` handles COMPRESSION tag correctly
- Validate `resample_to_cd_flac()` produces correct CD-quality output
- Add unit tests for recompress/resample functions
- Ensure library_runner executes recompress/resample phases correctly

## Impact
- Affected specs: `library-management`
- Affected code: `src/pac/flac_tools.py`, `src/pac/library_runner.py`, `tests/`
