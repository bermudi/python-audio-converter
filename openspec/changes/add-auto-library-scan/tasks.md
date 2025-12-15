## 1. Path Input Enhancement

- [ ] 1.1 Create `DebouncedLineEdit` widget or add debounce logic to `edit_lib_root`
- [ ] 1.2 Connect `textChanged` signal to debounced validation handler
- [ ] 1.3 Implement path validation (exists, is directory, is readable)
- [ ] 1.4 Show validation indicator (green check / red X) inline with path field

## 2. Auto-Scan Integration

- [ ] 2.1 Trigger `on_browser_scan()` when debounced path becomes valid
- [ ] 2.2 Show inline "Scanning..." indicator in path field or adjacent label
- [ ] 2.3 Disable path input during scan to prevent race conditions
- [ ] 2.4 Re-enable input and update browser on scan completion

## 3. Edge Cases

- [ ] 3.1 Clear browser table when path is cleared
- [ ] 3.2 Clear browser table when path becomes invalid
- [ ] 3.3 Cancel in-progress scan if path changes before completion
- [ ] 3.4 Handle file browser dialog selection (should also trigger scan)

## 4. Manual Refresh

- [ ] 4.1 Keep "Scan Library" button visible for manual refresh
- [ ] 4.2 Rename button to "Refresh" or "Rescan" for clarity

## 5. Testing

- [ ] 5.1 Manual test: Type valid path → scan starts automatically after pause
- [ ] 5.2 Manual test: Paste path → scan starts
- [ ] 5.3 Manual test: Browse dialog → scan starts on selection
- [ ] 5.4 Manual test: Clear path → browser clears
- [ ] 5.5 Manual test: Invalid path → no scan, error indicator shown
