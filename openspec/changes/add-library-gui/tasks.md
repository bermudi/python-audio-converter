## 1. UI Components
- [ ] 1.1 Add Library root directory selector
- [ ] 1.2 Add compression level spinbox (1-12, default 8)
- [ ] 1.3 Add resample-to-cd checkbox
- [ ] 1.4 Add art root path selector and pattern input
- [ ] 1.5 Add Plan (dry-run) and Run buttons

## 2. Progress Display
- [ ] 2.1 Add phase counters (integrity, resample, recompress, art export)
- [ ] 2.2 Add overall progress bar
- [ ] 2.3 Add "Issues Found" list widget showing held files

## 3. Backend Integration
- [ ] 3.1 Create LibraryWorker thread wrapping cmd_manage_library
- [ ] 3.2 Connect signals for progress updates
- [ ] 3.3 Handle pause/cancel via stop_event

## 4. Testing
- [ ] 4.1 Manual test with small FLAC library
- [ ] 4.2 Verify dry-run shows plan without modifications
