## 1. Path Input Enhancement

- [x] 1.1 Create `DebouncedLineEdit` widget or add debounce logic to `edit_lib_root`
- [x] 1.2 Connect `textChanged` signal to debounced validation handler
- [x] 1.3 Implement path validation (exists, is directory, is readable)
- [x] 1.4 Show validation indicator (green check / red X) inline with path field

## 2. Auto-Scan Integration

- [x] 2.1 Trigger `on_browser_scan()` when debounced path becomes valid
- [x] 2.2 Show inline "Scanning..." indicator in path field or adjacent label
- [x] 2.3 Disable path input during scan to prevent race conditions
- [x] 2.4 Re-enable input and update browser on scan completion

## 3. Edge Cases

- [x] 3.1 Clear browser table when path is cleared
- [x] 3.2 Clear browser table when path becomes invalid
- [x] 3.3 Cancel in-progress scan if path changes before completion
- [x] 3.4 Handle file browser dialog selection (should also trigger scan)

## 4. Manual Refresh

- [x] 4.1 Keep "Scan Library" button visible for manual refresh
- [x] 4.2 Rename button to "Refresh" or "Rescan" for clarity

## 5. Testing

- [x] 5.1 Manual test: Type valid path → scan starts automatically after pause
- [x] 5.2 Manual test: Paste path → scan starts
- [x] 5.3 Manual test: Browse dialog → scan starts on selection
- [x] 5.4 Manual test: Clear path → browser clears
- [x] 5.5 Manual test: Invalid path → no scan, error indicator shown
