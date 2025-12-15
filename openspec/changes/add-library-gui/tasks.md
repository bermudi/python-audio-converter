## 1. UI Components
- [x] 1.1 Add Library root directory selector
- [x] 1.2 Add compression level spinbox (0-8, FLAC standard range)
- [x] 1.3 Add resample-to-cd checkbox
- [x] 1.4 Add art root path selector and pattern input
- [x] 1.5 Add Plan (dry-run) and Run buttons

## 2. Progress Display
- [x] 2.1 Add phase counters (integrity, resample, recompress, art export)
- [x] 2.2 Add overall progress bar (indeterminate style)
- [x] 2.3 Add "Issues Found" list widget showing held files

## 3. Backend Integration
- [x] 3.1 Create LibraryWorker thread wrapping cmd_manage_library
- [x] 3.2 Connect signals for progress updates
- [x] 3.3 Handle pause/cancel via stop_event

## 4. Testing
- [x] 4.1 Manual test with small FLAC library
- [x] 4.2 Verify dry-run shows plan without modifications
